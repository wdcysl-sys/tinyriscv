"""
回滚模块

根据修改日志文件，撤销所有修改，恢复到修改前的状态。
"""

import os
import re
from typing import List

from .models import ChangeRecord


def revert_from_log(log_path: str) -> List[str]:
    """
    根据修改日志撤销修改

    流程:
    1. 解析 Markdown 日志，提取修改记录
    2. 对每个文件:
       - RTL: 找到 ISO 插入块（=== UPF ISO signals ===）并删除
       - UPF: 将 _fpga 信号名恢复为原名

    返回: 回滚操作的状态消息列表
    """
    messages: List[str] = []

    if not os.path.exists(log_path):
        return [f"❌ 错误: 日志文件不存在 → {log_path}"]

    with open(log_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 提取 UPF 文件路径
    upf_match = re.search(r"\*\*UPF 文件\*\*:\s*(.+)", content)
    upf_file = upf_match.group(1).strip() if upf_match else "upf"

    # 提取 RTL 目录
    rtl_match = re.search(r"\*\*RTL 目录\*\*:\s*(.+)", content)
    rtl_dir = rtl_match.group(1).strip() if rtl_match else "rtl"

    # ── RTL 回滚 ──
    rtl_files_section = re.findall(
        r"### 文件:\s*(.+?\.v)",
        content
    )
    for filepath in rtl_files_section:
        filepath = filepath.strip()
        full_path = filepath if os.path.isabs(filepath) else os.path.join(rtl_dir, filepath)

        if not os.path.exists(full_path):
            # 尝试相对路径
            if not os.path.exists(filepath):
                messages.append(f"⚠️ 跳过: RTL 文件不存在 → {filepath}")
                continue
            full_path = filepath

        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        # 删除 ISO 插入块
        block_start = None
        new_lines = []
        skip_until = -1

        for i, line in enumerate(lines):
            if "=== UPF ISO signals inserted by upf_tool" in line:
                block_start = i
                # 不输出此行（开始跳过）
                continue
            if block_start is not None and "=== End UPF ISO signals ===" in line:
                block_start = None
                # 不输出此行（结束跳过）
                continue
            if block_start is not None:
                # 在 ISO block 内部，跳过
                continue
            new_lines.append(line)

        if len(new_lines) < len(lines):
            with open(full_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            removed = len(lines) - len(new_lines)
            messages.append(f"🔄 RTL 回滚: {filepath} — 删除了 {removed} 行 ISO 插入代码")
        else:
            messages.append(f"   RTL 回滚: {filepath} — 未找到 ISO 代码块，跳过")

    # ── UPF 回滚 ──
    if os.path.exists(upf_file):
        with open(upf_file, "r", encoding="utf-8", errors="ignore") as f:
            upf_text = f.read()

        # 将 _fpga 恢复为原名（去掉 _fpga 后缀）
        # 匹配两种格式: "sig_fpga/" 和 "sig_fpga}"（elements 最后一个信号紧跟 }）
        fpga_patterns = re.findall(r"(\w+)_fpga\s*([/}])", upf_text)
        if fpga_patterns:
            updated = upf_text
            for base_name, suffix in set(fpga_patterns):
                # base_name 是 _fpga 之前的原始信号名（如 "cpu_core_en"）
                # 替换: "cpu_core_en_fpga/" → "cpu_core_en/" 或 "cpu_core_en_fpga}" → "cpu_core_en}"
                fpga_full = f"{base_name}_fpga{suffix}"
                orig_full = f"{base_name}{suffix}"
                updated = updated.replace(fpga_full, orig_full)
            with open(upf_file, "w", encoding="utf-8") as f:
                f.write(updated)
            unique_signals = len(set(fpga_patterns))
            messages.append(f"🔄 UPF 回滚: {upf_file} — 恢复了 {unique_signals} 个信号名 (_fpga → 原名)")
        else:
            messages.append(f"   UPF 回滚: {upf_file} — 未找到 _fpga 信号，跳过")
    else:
        messages.append(f"⚠️ 跳过: UPF 文件不存在 → {upf_file}")

    return messages
