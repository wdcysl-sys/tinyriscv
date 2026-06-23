"""
RTL 植入器模块

功能:
1. 在 RTL 目录中搜索信号所在的文件和模块
2. 从 wire 声明中提取信号位宽
3. 在模块的最后一个 wire 声明之后插入 ISO assign 代码
4. 幂等性检查：如果 _fpga 赋值已存在则跳过
"""

import os
import re
from typing import Dict, List, Optional, Tuple

from .models import IsoSignal, ChangeRecord


def _find_v_files(rtl_dir: str) -> List[str]:
    """递归查找 rtl_dir 下所有 .v 文件，返回绝对路径列表"""
    v_files = []
    for root, dirs, files in os.walk(rtl_dir):
        for f in files:
            if f.endswith(".v"):
                v_files.append(os.path.join(root, f))
    return v_files


def _parse_module(lines: List[str], module_name: str, start_from: int = 0) -> Optional[Tuple[int, int]]:
    """
    在 lines 中查找指定 module 的边界

    返回: (module_start_line, module_end_line) 或 None
      module_start_line — "module xxx" 所在行号 (0-based)
      module_end_line   — "endmodule" 所在行号 (0-based)
    """
    # 找 "module <name>" 行
    module_start = None
    pattern = re.compile(r"^\s*module\s+" + re.escape(module_name) + r"\b")
    for i in range(start_from, len(lines)):
        if pattern.search(lines[i]):
            module_start = i
            break

    if module_start is None:
        return None

    # 在 module_start 之后找第一个 "endmodule"
    for i in range(module_start + 1, len(lines)):
        if re.match(r"^\s*endmodule\b", lines[i]):
            return (module_start, i)

    return None


def search_signal_in_rtl(signal_name: str, rtl_dir: str,
                         prefer_module: str = "") -> Optional[Tuple[str, str, int]]:
    """
    在 RTL 中搜索信号，返回 (文件路径, 模块名, 位宽)

    搜索策略:
    1. 如果指定了 prefer_module，优先搜索该模块所在的文件
    2. 搜索 wire/input/output 声明提取位宽
    3. 如果 prefer_module 匹配了模块名，直接返回

    返回 None 表示信号未找到。
    """
    v_files = _find_v_files(rtl_dir)

    # 如果指定了优先模块，把它的文件排到最前面
    if prefer_module:
        preferred = []
        rest = []
        for fp in v_files:
            fname = os.path.basename(fp)
            # 文件名匹配 prefer_module (如 "timer.v" matches "timer")
            if prefer_module.lower() in fname.lower():
                preferred.append(fp)
            else:
                rest.append(fp)
        v_files = preferred + rest

    decl_pattern = re.compile(
        r"^\s*(?:input|output|inout)?\s*(?:wire|reg)?\s*"
        r"(?:\[(\d+)\s*:\s*(\d+)\])?\s*"
        + re.escape(signal_name) + r"\b"
    )

    for filepath in v_files:
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception:
            continue

        for i, line in enumerate(lines):
            m = decl_pattern.search(line)
            if not m:
                continue

            if m.group(1) is not None:
                high = int(m.group(1))
                low = int(m.group(2))
                width = abs(high - low) + 1
            else:
                width = 1

            for j in range(i, -1, -1):
                mod_match = re.match(r"^\s*module\s+(\w+)", lines[j])
                if mod_match:
                    found_module = mod_match.group(1)
                    # 如果指定了 prefer_module 且不匹配，继续搜索
                    if prefer_module and prefer_module.lower() != found_module.lower():
                        break  # 这个 module 不是目标，退出找下一个文件
                    return (filepath, found_module, width)

    return None


def _find_last_wire_line(lines: List[str], mod_start: int, mod_end: int) -> int:
    """
    在 module 范围内找到最后一个 wire 声明的行号

    匹配: wire xxx;  或  wire[N:0] xxx;
    不匹配: input/output/inout wire  (这些是端口)

    返回: 最后一个 wire 声明的行号 (0-based)
    如果没有找到 wire 声明，返回端口列表结束的 ); 行号
    """
    wire_pattern = re.compile(
        r"^\s*wire\s+(?:\[[\d\s:]*\]\s*)?\w+"
    )

    last_wire = -1
    for i in range(mod_start, mod_end + 1):
        stripped = lines[i].strip()
        if stripped.startswith("input") or stripped.startswith("output") or stripped.startswith("inout"):
            continue
        if wire_pattern.search(lines[i]):
            last_wire = i

    if last_wire >= 0:
        return last_wire

    # 没有 wire 声明 → 找端口列表结束的 );
    # 从 module 行之后开始找第一个 );
    for i in range(mod_start + 1, mod_end + 1):
        if lines[i].strip() == ");":
            return i

    # 兜底: module 行
    return mod_start


def _check_fpga_exists(lines: List[str], fpga_signal_name: str) -> bool:
    """
    检查文件中是否已存在某个 _fpga 信号的 assign 语句

    匹配: assign <fpga_signal_name> ... 或 assign <fpga_signal_name>[...
    """
    pattern = re.compile(
        r"^\s*assign\s+" + re.escape(fpga_signal_name) + r"\b"
    )
    for line in lines:
        if pattern.search(line):
            return True
    return False


def _find_existing_iso_block(lines: List[str], mod_start: int, mod_end: int) -> Optional[Tuple[int, int]]:
    """
    查找已存在的 ISO 插入块

    匹配:
      // === UPF ISO signals inserted by upf_tool ...
      ...
      // === End UPF ISO signals ===

    返回: (block_start_line, block_end_line) 或 None
    """
    block_start_pattern = re.compile(
        r"^\s*//\s*===\s*UPF ISO signals inserted by upf_tool"
    )
    block_end_pattern = re.compile(
        r"^\s*//\s*===\s*End UPF ISO signals\s*==="
    )

    start = None
    for i in range(mod_start, mod_end + 1):
        if block_start_pattern.search(lines[i]):
            start = i
        if start is not None and block_end_pattern.search(lines[i]):
            return (start, i)

    return None


def _generate_iso_block(signals: List[IsoSignal], timestamp: str) -> List[str]:
    """
    生成 ISO 插入代码块

    返回代码行列表（不含换行符），格式:
        // === UPF ISO signals inserted by upf_tool on <timestamp> ===
        // UPF ISO: <pd_name>, clamp=0
        assign sig1_fpga = iso_en ? 1'b0 : sig1;
        // UPF ISO: <pd_name>, clamp=1
        assign sig2_fpga[31:0] = iso_en ? 32'hffffffff : sig2[31:0];
        // === End UPF ISO signals ===
    """
    lines = []
    lines.append(f"    // === UPF ISO signals inserted by upf_tool on {timestamp} ===")
    for sig in signals:
        lines.append(f"    {sig.comment_line}")
        lines.append(f"    {sig.assign_code}")
    lines.append(f"    // === End UPF ISO signals ===")
    return lines


def insert_iso_to_rtl(
    signals: List[IsoSignal],
    rtl_dir: str,
    dry_run: bool = False,
) -> List[ChangeRecord]:
    """
    主函数：将 ISO 信号植入 RTL

    流程:
    1. 对每个信号，搜索 RTL 找到所在文件和模块
    2. 从 wire 声明提取位宽
    3. 按文件分组，同一文件的信号一起处理
    4. 找到模块内最后一个 wire 位置
    5. 幂等检查（_fpga 是否已存在）
    6. 生成 ISO assign 代码并插入
    7. 写回文件（非 dry-run）

    返回: ChangeRecord 列表
    """
    from datetime import datetime

    records: List[ChangeRecord] = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Step 1+2: 信号搜索（解析 target_path, target_module, signal_width）
    unresolved: List[IsoSignal] = []
    for sig in signals:
        result = search_signal_in_rtl(sig.signal_name, rtl_dir,
                                       prefer_module=sig.target_file)
        if result:
            sig.target_path = result[0]
            sig.target_module = result[1]
            sig.signal_width = result[2]
        else:
            unresolved.append(sig)
            records.append(ChangeRecord(
                change_type="error",
                file_path="",
                line_number=0,
                old_value="",
                new_value="",
                signal_name=sig.signal_name,
                description=f"信号 '{sig.signal_name}' 在 RTL 中未找到，跳过",
            ))

    # 过滤掉未找到的信号
    resolved = [s for s in signals if s.target_path]

    # Step 3: 按 (file_path, target_module) 分组
    #   key: (file_path, target_module) → value: List[IsoSignal]
    groups: Dict[Tuple[str, str], List[IsoSignal]] = {}
    for sig in resolved:
        key = (sig.target_path, sig.target_module)
        groups.setdefault(key, []).append(sig)

    # Step 4-7: 对每个分组处理
    for (filepath, mod_name), group_signals in groups.items():
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        # 定位模块边界
        mod_bounds = _parse_module(lines, mod_name)
        if mod_bounds is None:
            for sig in group_signals:
                records.append(ChangeRecord(
                    change_type="error",
                    file_path=filepath,
                    line_number=0,
                    old_value="",
                    new_value="",
                    signal_name=sig.signal_name,
                    description=f"模块 '{mod_name}' 在文件 '{filepath}' 中未找到",
                ))
            continue

        mod_start, mod_end = mod_bounds

        # 过滤已存在的信号（幂等检查）
        new_signals: List[IsoSignal] = []
        for sig in group_signals:
            if _check_fpga_exists(lines, sig.fpga_signal_name):
                records.append(ChangeRecord(
                    change_type="skipped",
                    file_path=filepath,
                    line_number=0,
                    old_value="",
                    new_value="",
                    signal_name=sig.signal_name,
                    description=f"assign {sig.fpga_signal_name} 已存在，跳过（幂等）",
                ))
            else:
                new_signals.append(sig)

        if not new_signals:
            continue

        # 找到插入位置: endmodule 之前
        existing_block = _find_existing_iso_block(lines, mod_start, mod_end)
        if existing_block:
            # 已有 ISO block，在 block 的 End 行之前追加新信号
            block_start, block_end = existing_block
            insert_at = block_end
            new_code_lines = []
            for sig in new_signals:
                new_code_lines.append(f"    {sig.comment_line}")
                new_code_lines.append(f"    {sig.assign_code}")
            for i, code_line in enumerate(new_code_lines):
                lines.insert(insert_at + i, code_line + "\n")
            for sig in new_signals:
                records.append(ChangeRecord(
                    change_type="rtl_insert",
                    file_path=filepath,
                    line_number=insert_at + 1,
                    old_value="",
                    new_value=sig.assign_code,
                    signal_name=sig.signal_name,
                    description=f"在模块 '{mod_name}' endmodule 前追加 assign {sig.fpga_signal_name}",
                ))
        else:
            # 没有 ISO block，新建在 endmodule 之前
            insert_at = mod_end  # endmodule 行

            new_code_lines = _generate_iso_block(new_signals, timestamp)
            for i, code_line in enumerate(new_code_lines):
                lines.insert(insert_at + i, code_line + "\n")

            for sig in new_signals:
                records.append(ChangeRecord(
                    change_type="rtl_insert",
                    file_path=filepath,
                    line_number=insert_at + 1,
                    old_value="",
                    new_value=sig.assign_code,
                    signal_name=sig.signal_name,
                    description=f"在模块 '{mod_name}' endmodule 前插入 assign {sig.fpga_signal_name}",
                ))

        # 写回文件
        if not dry_run:
            with open(filepath, "w", encoding="utf-8") as f:
                f.writelines(lines)

    return records
