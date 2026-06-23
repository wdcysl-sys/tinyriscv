"""
UPF 更新器模块

功能:
1. 解析 UPF 文件中的 set_isolation 命令块
2. 根据 Excel 的 ISO 信号信息更新 -elements 信号列表
3. 补齐缺失的 -clamp_value
4. 保持 UPF 格式和注释不变
"""

import re
from typing import Dict, List, Optional, Tuple

from .models import IsoSignal, UpfBlock, ChangeRecord


def _parse_upf_blocks(upf_text: str) -> List[UpfBlock]:
    """
    解析 UPF 文件中的 set_isolation 命令块

    UPF 格式示例:
      set_isolation iso_b_to_a \
          -domain PD_A \
          -clamp_value 1 \
          -elements {
              cpu_core_en/
              axi_m_awready/
          }

    返回: UpfBlock 列表（按 start_line 排序）
    """
    lines = upf_text.split("\n")
    blocks: List[UpfBlock] = []

    i = 0
    while i < len(lines):
        # 找 set_isolation 开头（但不是 set_isolation_control）
        if re.match(r"^\s*set_isolation\s+\w+", lines[i]) and "set_isolation_control" not in lines[i]:
            start_line = i
            block_text_lines = [lines[i]]

            # 提取名称
            name_match = re.match(r"^\s*set_isolation\s+(\w+)", lines[i])
            name = name_match.group(1) if name_match else ""

            domain = ""
            clamp_value: Optional[int] = None
            elements: List[str] = []
            elements_lines: List[str] = []
            in_elements = False

            # 读取块内容（以反斜杠 \ 连接的多行，直到遇到非续行）
            i += 1
            while i < len(lines):
                line = lines[i]
                block_text_lines.append(line)

                # 提取 -domain
                dm = re.match(r"^\s*-domain\s+(\w+)", line)
                if dm:
                    domain = dm.group(1)

                # 提取 -clamp_value
                cm = re.match(r"^\s*-clamp_value\s+(\d)", line)
                if cm:
                    clamp_value = int(cm.group(1))

                # 提取 -elements { ... }
                if re.search(r"-elements\s*\{", line):
                    in_elements = True
                    # 如果 { 后面有信号，也提取
                    rest = line.split("{", 1)[1]
                    if rest.strip() and rest.strip() != "":
                        elements_lines.append(rest.strip())
                    i += 1
                    while i < len(lines):
                        block_text_lines.append(lines[i])
                        if "}" in lines[i]:
                            # elements 块结束（} 行是 block 的最后一行）
                            ele_line = lines[i].split("}")[0].strip()
                            if ele_line:
                                elements_lines.append(ele_line + "}")
                            in_elements = False
                            # } 行就是 block 的最后一行，跳到 block 结束处理
                            break
                        else:
                            elements_lines.append(lines[i].strip())
                        i += 1

                    # 解析 elements 信号列表
                    for ele_line in elements_lines:
                        # 每行可能包含多个 "sig/" 或 "sig}" 条目
                        # (UPF 中 elements 最后一个信号后面紧跟 }，不带 /)
                        items = re.findall(r"(\w+)\s*[}/]", ele_line)
                        elements.extend(items)

                    # elements 块处理完后，如果是因为 } break 的，
                    # 则 i 指向 } 行，end_line 应该就是 i
                    if not in_elements:
                        end_line = i
                        blocks.append(UpfBlock(
                            name=name, domain=domain, clamp_value=clamp_value,
                            elements=elements,
                            start_line=start_line, end_line=end_line,
                            raw_text="\n".join(block_text_lines),
                        ))
                        # 跳过后续处理，继续外循环
                        i += 1
                        continue

                # 如果行不以反斜杠结尾，且不在 elements 内部，块结束
                if not in_elements and not line.rstrip().endswith("\\"):
                    break
                i += 1

            end_line = i - 1
            raw_text = "\n".join(block_text_lines)

            blocks.append(UpfBlock(
                name=name,
                domain=domain,
                clamp_value=clamp_value,
                elements=elements,
                start_line=start_line,
                end_line=end_line,
                raw_text=raw_text,
            ))

        i += 1

    return blocks


def _match_block_for_signal(
    sig: IsoSignal, blocks: List[UpfBlock]
) -> Optional[UpfBlock]:
    """
    为信号找到匹配的 UPF block

    匹配条件（按优先级）:
    1. block.name == sig.target_file（sys_name 匹配 set_isolation 名称）
       AND block.clamp_value == sig.iso_value
    2. block.domain == sig.pd_name AND block.clamp_value == sig.iso_value
    3. 同 domain 但 clamp_value 为 None（需要补全）
    """
    # 精确匹配: sys_name + clamp_value
    for block in blocks:
        if block.name == sig.target_file and block.clamp_value == sig.iso_value:
            return block

    # 次选: domain + clamp_value
    for block in blocks:
        if block.domain == sig.pd_name and block.clamp_value == sig.iso_value:
            return block

    # 宽松匹配: 同 domain 但 clamp_value 为 None（需要补全）
    for block in blocks:
        if block.domain == sig.pd_name and block.clamp_value is None:
            return block

    return None


def _update_elements_in_block(
    block: UpfBlock,
    signals: List[IsoSignal],
) -> Tuple[str, List[ChangeRecord]]:
    """
    根据 Excel 信号列表整体重写 UPF block 的 -elements { ... }

    Excel 是信号来源的唯一权威，UPF 的 elements 直接用 Excel 中的信号名（不加 _fpga）。

    策略: 不逐行删改，而是整体重建 elements 块内容，避免行号错位和格式破坏。

    返回: (更新后的 raw_text, 修改记录列表)
    """
    updated_text = block.raw_text
    changes: List[ChangeRecord] = []

    # Excel 中属于此 block 的信号名集合（原名，不加 _fpga）
    excel_names = [s.signal_name for s in signals]  # 保持 Excel 顺序
    upf_names = set(block.elements)

    if set(excel_names) == upf_names:
        changes.append(ChangeRecord(
            change_type="skipped",
            file_path="",
            line_number=block.start_line,
            old_value="",
            new_value="",
            signal_name=",".join(excel_names),
            description=f"UPF elements 与 Excel 一致，跳过（幂等）",
        ))
        return updated_text, changes

    # 提取原 block 中 elements 的缩进风格
    indent = "        "  # 默认 8 空格缩进
    brace_on_last = False  # 最后一个信号后是否紧跟 }
    for line in block.raw_text.split("\n"):
        if re.search(r"-elements\s*\{", line):
            # 提取缩进：数 -elements 前的空格
            m = re.match(r"^(\s*)", line)
            if m:
                indent = m.group(1) + "    "  # 信号行比 -elements 多缩进 4 空格
        if re.search(r"\w+}", line):  # "sig}" 格式
            brace_on_last = True

    # 记录变更
    removed = upf_names - set(excel_names)
    added = set(excel_names) - upf_names
    for name in removed:
        changes.append(ChangeRecord(
            change_type="upf_elements_update",
            file_path="",
            line_number=block.start_line,
            old_value=f"{name}/",
            new_value="",
            signal_name=name,
            description=f"UPF -elements: 移除 {name}/ (不在 Excel 中)",
        ))
    for name in added:
        changes.append(ChangeRecord(
            change_type="upf_elements_update",
            file_path="",
            line_number=block.start_line,
            old_value="",
            new_value=f"{name}/",
            signal_name=name,
            description=f"UPF -elements: 新增 {name}/ (来自 Excel)",
        ))

    # 整体重建 elements 块
    if excel_names:
        if brace_on_last:
            # 格式: 所有信号用 / 结尾，最后一个信号后直接跟 }
            ele_lines = [f"{indent}{name}/" for name in excel_names[:-1]]
            ele_lines.append(f"{indent}{excel_names[-1]}}}")
        else:
            # 格式: 所有信号用 / 结尾，} 单独一行
            ele_lines = [f"{indent}{name}/" for name in excel_names]
            ele_lines.append(f"{indent[:-4]}}}")
    else:
        # 无信号 → 空 elements
        ele_lines = [f"{indent[:-4]}}}"]
        changes.append(ChangeRecord(
            change_type="warning",
            file_path="",
            line_number=block.start_line,
            old_value=",".join(upf_names),
            new_value="(空)",
            signal_name="",
            description=f"UPF -elements: block 变空 (Excel 中无对应信号)",
        ))

    # 用正则替换原 elements { ... } 部分
    # 匹配: -elements { ... (到最近的独立 } 或行尾 })
    new_elements = "-elements {\n" + "\n".join(ele_lines)
    updated_text = re.sub(
        r"-elements\s*\{[^}]*\}",
        new_elements,
        updated_text,
        flags=re.DOTALL,
    )

    return updated_text, changes


def _ensure_clamp_value(
    block: UpfBlock, iso_value: int, current_text: str = None
) -> Tuple[str, Optional[ChangeRecord]]:
    """
    确保 UPF block 有 -clamp_value

    如果缺失则生成，如果存在但不一致则更新。

    参数:
      block: 原始 UPF block（用于读取 clamp_value 状态）
      iso_value: 目标 clamp 值
      current_text: 当前文本（可能已被 _update_elements_in_block 修改过）
                    如果不传则使用 block.raw_text

    返回: (更新后的文本, 修改记录或None)
    """
    updated_text = current_text if current_text is not None else block.raw_text

    if block.clamp_value is None:
        # 缺失 clamp_value → 在 -domain 行之后插入
        domain_match = re.search(r"(-domain\s+\w+\s*\\?\s*)", updated_text)
        if domain_match:
            insert_pos = domain_match.end()
            indent = "    "
            new_clamp = f"{indent}-clamp_value {iso_value} \\\n"
            updated_text = (
                updated_text[:insert_pos]
                + "\n"
                + new_clamp
                + updated_text[insert_pos:]
            )
        return updated_text, ChangeRecord(
            change_type="upf_clamp_value_add",
            file_path="",
            line_number=block.start_line,
            old_value="(缺失)",
            new_value=str(iso_value),
            signal_name="",
            description=f"UPF {block.name}: 补充 -clamp_value {iso_value}",
        )

    elif block.clamp_value != iso_value:
        # clamp_value 不一致 → 更新（罕见情况）
        old_str = f"-clamp_value {block.clamp_value}"
        new_str = f"-clamp_value {iso_value}"
        updated_text = updated_text.replace(old_str, new_str, 1)
        return updated_text, ChangeRecord(
            change_type="upf_clamp_value_add",
            file_path="",
            line_number=block.start_line,
            old_value=str(block.clamp_value),
            new_value=str(iso_value),
            signal_name="",
            description=f"UPF {block.name}: clamp_value {block.clamp_value} → {iso_value}",
        )

    return updated_text, None


def update_upf(
    signals: List[IsoSignal],
    upf_path: str,
    dry_run: bool = False,
) -> List[ChangeRecord]:
    """
    主函数: 增量更新 UPF 文件

    流程:
    1. 解析 UPF 中所有 set_isolation 块
    2. 对每个 ISO 信号，匹配对应的 UPF block
    3. 更新 -elements（信号名 → _fpga 版本）
    4. 确保 -clamp_value 存在且正确
    5. 写回文件

    返回: ChangeRecord 列表
    """
    records: List[ChangeRecord] = []

    with open(upf_path, "r", encoding="utf-8", errors="ignore") as f:
        upf_text = f.read()

    # Step 1: 解析 UPF blocks
    blocks = _parse_upf_blocks(upf_text)

    # 将 blocks 按 domain 分组，方便后续更新
    # 先复制原始行列表，每行对应一个 line，用于精准替换
    lines = upf_text.split("\n")

    # Step 2-4: 逐信号处理
    # 按 (sys_name, clamp_value) 分组信号，匹配 UPF 中的 set_isolation 名称
    signal_groups: Dict[Tuple[str, int], List[IsoSignal]] = {}
    for sig in signals:
        key = (sig.target_file, sig.iso_value)  # target_file = Excel sys_name 列
        signal_groups.setdefault(key, []).append(sig)

    # 倒序处理: 从文件底部往顶部修改，避免行号偏移导致后续替换错位
    # 每个 block 替换后行数可能变化，倒序保证上面的 block 不受影响
    sorted_groups = sorted(
        signal_groups.items(),
        key=lambda x: _match_block_for_signal(x[1][0], blocks).start_line
        if _match_block_for_signal(x[1][0], blocks) else 0,
        reverse=True,
    )

    for (domain, clamp_val), group_signals in sorted_groups:
        # 找匹配的 UPF block
        block = _match_block_for_signal(group_signals[0], blocks)

        if block is None:
            # 没有匹配的 block → 检查是否有同 domain、不同 clamp_value 的 block
            same_domain_blocks = [b for b in blocks if b.domain == domain]
            if same_domain_blocks:
                # 有同 domain 但无此 clamp_value 的 block → 记录
                for sig in group_signals:
                    records.append(ChangeRecord(
                        change_type="warning",
                        file_path=upf_path,
                        line_number=same_domain_blocks[0].start_line,
                        old_value="",
                        new_value="",
                        signal_name=sig.signal_name,
                        description=f"UPF 中 domain={domain} 缺少 clamp_value={clamp_val} 的 set_isolation 块",
                    ))
            else:
                for sig in group_signals:
                    records.append(ChangeRecord(
                        change_type="warning",
                        file_path=upf_path,
                        line_number=0,
                        old_value="",
                        new_value="",
                        signal_name=sig.signal_name,
                        description=f"UPF 中未找到 domain={domain} 的 set_isolation 命令",
                    ))
            continue

        # 更新 -elements（先改 elements，改完的结果传给 clamp_value 检查）
        new_text, elem_changes = _update_elements_in_block(block, group_signals)
        records.extend(elem_changes)

        # 确保 -clamp_value（基于 elements 已更新后的文本继续修改）
        new_text, clamp_change = _ensure_clamp_value(block, clamp_val, current_text=new_text)
        if clamp_change:
            records.append(clamp_change)

        # 将更新后的文本写回 lines 数组
        if new_text != block.raw_text:
            # 替换 block 对应的行范围
            old_block_lines = block.raw_text.split("\n")
            new_block_lines = new_text.split("\n")

            # 在 lines 中替换
            lines[block.start_line:block.end_line + 1] = new_block_lines

    # Step 5: 写回
    if not dry_run and records:
        # 只有在有实际修改时才写回（排除 skipped 和 error 和 warning）
        real_changes = [r for r in records
                        if r.change_type not in ("skipped", "error", "warning")]
        if real_changes:
            with open(upf_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

    return records
