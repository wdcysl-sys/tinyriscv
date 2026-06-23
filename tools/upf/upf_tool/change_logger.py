"""
修改日志生成模块

将所有 ChangeRecord 汇总生成 Markdown 格式的修改日志文件。
同时提供日志解析功能，用于 revert 回滚。
"""

import re
from datetime import datetime
from typing import List

from .models import ChangeRecord, ChangeLog


def generate_log(change_log: ChangeLog, output_path: str) -> str:
    """
    生成 Markdown 格式的修改日志并写入文件

    参数:
      change_log: 修改记录汇总
      output_path: 日志输出文件路径

    返回: Markdown 内容字符串
    """
    lines: List[str] = []
    dry_mark = " [DRY-RUN 预览]" if change_log.dry_run else ""

    # 标题
    lines.append(f"# UPF ISO 植入修改日志{dry_mark}")
    lines.append("")

    # 概要
    lines.append(f"**执行时间**: {change_log.execution_time}")
    lines.append(f"**Excel 文件**: {change_log.excel_file}")
    lines.append(f"**UPF 文件**: {change_log.upf_file}")
    lines.append(f"**RTL 目录**: {change_log.rtl_dir}")
    lines.append(f"**模式**: {'预览 (dry-run)' if change_log.dry_run else '实际修改'}")
    lines.append("")

    real = [r for r in change_log.records if r.change_type not in ("skipped", "error", "warning")]
    total_signals = len(set(r.signal_name for r in change_log.records if r.signal_name))
    lines.append(
        f"**信号总数**: {total_signals} | "
        f"**已修改**: {len(real)} | "
        f"**跳过**: {change_log.skipped_count} | "
        f"**错误/警告**: {change_log.error_count}"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # RTL 修改部分
    rtl_records = [r for r in change_log.records
                   if r.change_type in ("rtl_insert", "skipped", "error")
                   and r.signal_name]
    if rtl_records:
        lines.append("## RTL 修改")
        lines.append("")

        # 按文件分组
        file_groups: dict = {}
        for r in rtl_records:
            if r.file_path not in file_groups:
                file_groups[r.file_path] = []
            file_groups[r.file_path].append(r)

        for filepath, recs in file_groups.items():
            inserted = [r for r in recs if r.change_type == "rtl_insert"]
            skipped = [r for r in recs if r.change_type == "skipped"]
            errors = [r for r in recs if r.change_type == "error"]

            lines.append(f"### 文件: {filepath}")
            lines.append("")
            lines.append(f"插入 {len(inserted)} 条 / 跳过 {len(skipped)} 条 / 错误 {len(errors)} 条")
            lines.append("")

            if inserted:
                lines.append("| # | 信号 | 修改内容 |")
                lines.append("|---|------|----------|")
                for i, r in enumerate(inserted, 1):
                    lines.append(f"| {i} | `{r.signal_name}` | {r.description} |")
                lines.append("")

                # 展示插入的代码
                lines.append("**插入代码**:")
                lines.append("```verilog")
                for r in inserted:
                    lines.append(f"// UPF ISO: {r.signal_name}")
                    lines.append(f"{r.new_value}")
                lines.append("```")
                lines.append("")

            if skipped:
                lines.append("**跳过 (已存在)**:")
                for r in skipped:
                    lines.append(f"- `{r.signal_name}`: {r.description}")
                lines.append("")

            if errors:
                lines.append("**错误**:")
                for r in errors:
                    lines.append(f"- `{r.signal_name}`: {r.description}")
                lines.append("")

        lines.append("---")
        lines.append("")

    # UPF 修改部分
    upf_records = [r for r in change_log.records
                   if r.change_type.startswith("upf_")]
    if upf_records:
        lines.append("## UPF 修改")
        lines.append("")

        lines.append(f"### 文件: {change_log.upf_file}")
        lines.append("")

        elem_updates = [r for r in upf_records if r.change_type == "upf_elements_update"]
        clamp_updates = [r for r in upf_records if r.change_type == "upf_clamp_value_add"]
        skipped_upf = [r for r in upf_records if r.change_type == "skipped"]

        if elem_updates:
            lines.append("**-elements 更新**:")
            lines.append("")
            lines.append("| # | 信号 | 修改 |")
            lines.append("|---|------|------|")
            for i, r in enumerate(elem_updates, 1):
                action = "新增" if not r.old_value else f"`{r.old_value}` → `{r.new_value}`"
                lines.append(f"| {i} | `{r.signal_name}` | {action} |")
            lines.append("")

        if clamp_updates:
            lines.append("**-clamp_value 修改**:")
            for r in clamp_updates:
                lines.append(f"- {r.description}")
            lines.append("")

        if skipped_upf:
            lines.append("**跳过 (已更新)**:")
            for r in skipped_upf:
                lines.append(f"- `{r.signal_name}`: {r.description}")
            lines.append("")

        lines.append("---")
        lines.append("")

    # 摘要
    lines.append("## 修改摘要")
    lines.append("")
    lines.append("| 类型 | 数量 |")
    lines.append("|------|------|")
    lines.append(f"| RTL 插入 | {len([r for r in change_log.records if r.change_type == 'rtl_insert'])} |")
    lines.append(f"| UPF elements 更新 | {len([r for r in change_log.records if r.change_type == 'upf_elements_update'])} |")
    lines.append(f"| UPF clamp_value 新增/修改 | {len([r for r in change_log.records if r.change_type == 'upf_clamp_value_add'])} |")
    lines.append(f"| 跳过 (已存在) | {change_log.skipped_count} |")
    error_count = len([r for r in change_log.records if r.change_type == 'error'])
    warn_count = len([r for r in change_log.records if r.change_type == 'warning'])
    if error_count:
        lines.append(f"| 错误 | {error_count} |")
    if warn_count:
        lines.append(f"| 警告 | {warn_count} |")
    lines.append("")

    # 回滚提示
    if not change_log.dry_run and len(real) > 0:
        lines.append("---")
        lines.append("")
        lines.append("## 回滚")
        lines.append("")
        lines.append("如需撤销以上修改，执行:")
        lines.append("```bash")
        lines.append(f"python upf_tool.py revert --log {output_path}")
        lines.append("```")

    md_content = "\n".join(lines)

    # 写文件
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return md_content


def parse_log(log_path: str) -> List[ChangeRecord]:
    """
    从 Markdown 日志文件中解析 ChangeRecord 列表（用于 revert）

    解析策略:
    - 查找 "| # | 信号 | 修改内容 |" 表格 → 提取插入的行号
    - 查找 "-elements 更新" 部分 → 提取 old_value/new_value
    """
    records: List[ChangeRecord] = []

    with open(log_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 从文件头提取元信息
    upf_file_match = re.search(r"\*\*UPF 文件\*\*:\s*(.+)", content)
    upf_file = upf_file_match.group(1).strip() if upf_file_match else ""

    # 解析 RTL 修改表格
    # 格式: | 1 | `sig_name` | 在模块 'mod' 中插入 assign sig_fpga ... |
    rtl_section = re.findall(
        r"### 文件:\s*(.+?)\n.*?\| # \| 信号 \| 修改内容 \|(.*?)(?:\n\n|```verilog)",
        content, re.DOTALL
    )
    for filepath, table_body in rtl_section:
        filepath = filepath.strip()
        for row_match in re.finditer(
            r"\|\s*(\d+)\s*\|\s*`(\w+)`\s*\|\s*(.+?)\s*\|",
            table_body
        ):
            num = row_match.group(1)
            sig_name = row_match.group(2)
            desc = row_match.group(3).strip()

            # 提取代码详情
            code_match = re.search(
                r"assign\s+" + re.escape(sig_name) + r"_fpga\b[^;]*;",
                content
            )
            new_value = code_match.group(0) if code_match else ""

            records.append(ChangeRecord(
                change_type="rtl_insert",
                file_path=filepath,
                line_number=0,
                old_value="",
                new_value=new_value,
                signal_name=sig_name,
                description=desc,
            ))

    # 解析 UPF elements 更新
    elem_section = re.findall(
        r"\|\s*(\d+)\s*\|\s*`(\w+)`\s*\|\s*(.+?)\s*\|",
        content
    )
    # 从 UPF 修改表格中提取（与 RTL 表格分开处理）

    return records
