"""
CLI 入口模块

命令:
  python -m upf_tool insert  — 主命令: Excel → RTL植入 + UPF更新 + 日志
  python -m upf_tool revert  — 回滚: 根据日志撤销修改
  python -m upf_tool check   — 检查: 只解析 Excel，打印结果
"""

import argparse
import os
import sys
from datetime import datetime

from .models import ChangeLog
from .config import load_column_map
from .excel_reader import parse_excel
from .rtl_inserter import insert_iso_to_rtl
from .upf_updater import update_upf
from .change_logger import generate_log
from .revert import revert_from_log


def cmd_insert(args):
    """主命令: 执行 RTL 植入 + UPF 更新"""
    # ====== 参数校验 ======
    if not os.path.exists(args.excel):
        print(f"错误: Excel 文件不存在 → {args.excel}")
        sys.exit(1)
    if not os.path.exists(args.upf):
        print(f"错误: UPF 文件不存在 → {args.upf}")
        sys.exit(1)
    if not os.path.isdir(args.rtl_dir):
        print(f"错误: RTL 目录不存在 → {args.rtl_dir}")
        sys.exit(1)

    column_map = load_column_map()

    # ====== 第1步: 解析 Excel ======
    print("=" * 60)
    print("▶ 第1步/共4步: 解析 Excel 表格 ...")
    signals = parse_excel(args.excel, column_map)
    print(f"  解析出 {len(signals)} 条 ISO 信号")

    # ====== 初始化修改日志 ======
    change_log = ChangeLog(
        execution_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        excel_file=args.excel,
        upf_file=args.upf,
        rtl_dir=args.rtl_dir,
        dry_run=args.dry_run,
    )

    # ====== 第2步: RTL 植入 ======
    print("▶ 第2步/共4步: 往 RTL 中植入 ISO 代码 ...")
    rtl_records = insert_iso_to_rtl(signals, args.rtl_dir, dry_run=args.dry_run)
    change_log.records.extend(rtl_records)

    n_ok = len([r for r in rtl_records if r.change_type == "rtl_insert"])
    n_skip = len([r for r in rtl_records if r.change_type == "skipped"])
    n_err = len([r for r in rtl_records if r.change_type == "error"])
    print(f"  植入 {n_ok} 条 / 跳过 {n_skip} 条 / 错误 {n_err} 条")

    # ====== 第3步: UPF 更新 ======
    print("▶ 第3步/共4步: 更新 UPF 文件 ...")
    upf_records = update_upf(signals, args.upf, dry_run=args.dry_run)
    change_log.records.extend(upf_records)

    n_upd = len([r for r in upf_records if r.change_type in ("upf_elements_update", "upf_clamp_value_add")])
    n_skip_upf = len([r for r in upf_records if r.change_type == "skipped"])
    n_warn = len([r for r in upf_records if r.change_type == "warning"])
    print(f"  更新 {n_upd} 处 / 跳过 {n_skip_upf} 处 / 警告 {n_warn} 处")

    # ====== 第4步: 生成日志 ======
    print("▶ 第4步/共4步: 生成修改日志 ...")
    log_path = args.log or "upf_changes.md"
    generate_log(change_log, log_path)
    print(f"  日志已写入 → {log_path}")

    # ====== 汇总 ======
    print("=" * 60)
    total_real = len([r for r in change_log.records
                      if r.change_type not in ("skipped", "error", "warning")])
    if args.dry_run:
        print(f"🔍 [预览模式] 共 {total_real} 处待修改 (文件尚未被修改)")
        print(f"  确认无误后，去掉 --dry-run 参数重新执行即可实际修改")
    else:
        print(f"✅ 完成! 共修改 {total_real} 处")
        print(f"  如需回滚: python -m upf_tool revert --log {log_path}")


def cmd_revert(args):
    """回滚命令: 根据日志撤销修改"""
    if not os.path.exists(args.log):
        print(f"错误: 日志文件不存在 → {args.log}")
        sys.exit(1)

    print("=" * 60)
    print("🔄 正在回滚 ...")
    messages = revert_from_log(args.log)
    for msg in messages:
        print(f"  {msg}")
    print("=" * 60)
    print("✅ 回滚完成")


def cmd_check(args):
    """检查命令: 只解析 Excel，打印结果，不修改任何文件"""
    if not os.path.exists(args.excel):
        print(f"错误: Excel 文件不存在 → {args.excel}")
        sys.exit(1)

    column_map = load_column_map()
    signals = parse_excel(args.excel, column_map)

    print("=" * 60)
    print(f"📋 Excel 文件: {args.excel}")
    print(f"   解析出 {len(signals)} 条 ISO 信号")
    print()
    print(f"  {'序号':<5} {'信号名':<22} {'使能':<8} {'tie':<5} {'domain':<6} {'分组(sys_name)'}")
    print("  " + "-" * 68)
    for i, s in enumerate(signals, 1):
        print(f"  {i:<5} {s.signal_name:<22} {s.iso_enable:<8} {s.iso_value:<5} "
              f"{s.pd_name:<6} {s.target_file}")
    print("  " + "-" * 68)

    # 如果有 --rtl-dir，验证信号是否在 RTL 中存在
    if hasattr(args, "rtl_dir") and args.rtl_dir and os.path.isdir(args.rtl_dir):
        print()
        print(f"📁 RTL 信号查找验证 (目录: {args.rtl_dir}):")
        from .rtl_inserter import search_signal_in_rtl
        found = 0
        for s in signals:
            result = search_signal_in_rtl(s.signal_name, args.rtl_dir)
            if result:
                fp, mod, w = result
                fname = os.path.basename(fp)
                print(f"  ✅ {s.signal_name:<22} → 模块 {mod:<24} ({fname}, 位宽={w})")
                found += 1
            else:
                print(f"  ❌ {s.signal_name:<22} → 在 RTL 中未找到")
        print(f"  结果: 找到 {found}/{len(signals)} 个信号")
        if found < len(signals):
            print(f"  提示: 未找到的信号可能是新增信号，需要先在 RTL 中定义")


def main():
    parser = argparse.ArgumentParser(
        description="UPF ISO RTL 植入 + UPF 更新工具 —— 从 Excel 自动生成 ISO 代码并更新 UPF",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:

  # 1. 先预览将要做的修改 (安全，不写文件)
  python -m upf_tool insert --excel power_domain_iso.xlsx --upf upf --rtl-dir rtl/ --dry-run

  # 2. 确认无误后，实际执行修改
  python -m upf_tool insert --excel power_domain_iso.xlsx --upf upf --rtl-dir rtl/ --log upf_changes.md

  # 3. 如需撤销，根据日志回滚
  python -m upf_tool revert --log upf_changes.md

  # 4. 单独检查 Excel 解析是否正确 (不修改任何文件)
  python -m upf_tool check --excel power_domain_iso.xlsx --rtl-dir rtl/
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令: insert / revert / check")

    # ---- insert 子命令 ----
    p_insert = subparsers.add_parser("insert", help="执行 RTL 植入 + UPF 更新 (完整流程)")
    p_insert.add_argument("--excel", required=True, help="Power Domain Excel 表格路径")
    p_insert.add_argument("--upf", required=True, help="UPF 文件路径")
    p_insert.add_argument("--rtl-dir", required=True, help="RTL 源码根目录")
    p_insert.add_argument("--log", default="upf_changes.md", help="修改日志输出路径 (默认: upf_changes.md)")
    p_insert.add_argument("--dry-run", action="store_true", help="预览模式: 只输出将要做的修改，不实际改动文件")

    # ---- revert 子命令 ----
    p_revert = subparsers.add_parser("revert", help="根据修改日志回滚所有改动")
    p_revert.add_argument("--log", required=True, help="之前生成的修改日志文件路径")

    # ---- check 子命令 ----
    p_check = subparsers.add_parser("check", help="只解析 Excel，检查列映射是否正确，不修改任何文件")
    p_check.add_argument("--excel", required=True, help="Power Domain Excel 表格路径")
    p_check.add_argument("--rtl-dir", default=None, help="RTL 源码根目录 (可选，额外验证信号是否在 RTL 中存在)")

    args = parser.parse_args()

    if args.command == "insert":
        cmd_insert(args)
    elif args.command == "revert":
        cmd_revert(args)
    elif args.command == "check":
        cmd_check(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
