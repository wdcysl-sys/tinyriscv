#!/bin/bash
# ================================================================
# UPF ISO 植入工具 — 一键脚本 (AI agent 通用入口)
#
# 任何 AI 模型或人都可以直接调用:
#   ./tools/upf/upf-insert.sh                  # 默认 dry-run 预览
#   ./tools/upf/upf-insert.sh --execute        # 实际执行
#   ./tools/upf/upf-insert.sh --revert         # 回滚
#
# 参数:
#   --excel   <path>   Excel 文件路径 (默认: power_domain_iso.xlsx)
#   --upf     <path>   UPF 文件路径 (默认: upf)
#   --rtl-dir <path>   RTL 目录   (默认: rtl/)
# ================================================================

set -e
cd "$(dirname "$0")/../.."   # 回到项目根目录

EXCEL="power_domain_iso.xlsx"
UPF="upf"
RTL_DIR="rtl/"
LOG="upf_changes.md"
MODE="dry-run"

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --excel)   EXCEL="$2"; shift 2 ;;
        --upf)     UPF="$2"; shift 2 ;;
        --rtl-dir) RTL_DIR="$2"; shift 2 ;;
        --execute) MODE="execute"; shift ;;
        --revert)  MODE="revert"; shift ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

case $MODE in
    dry-run)
        echo "🔍 预览模式 (不修改文件)..."
        PYTHONPATH=tools/upf python3 -m upf_tool insert \
            --excel "$EXCEL" --upf "$UPF" --rtl-dir "$RTL_DIR" --dry-run
        ;;
    execute)
        echo "🚀 执行修改..."
        PYTHONPATH=tools/upf python3 -m upf_tool insert \
            --excel "$EXCEL" --upf "$UPF" --rtl-dir "$RTL_DIR" --log "$LOG"
        ;;
    revert)
        echo "🔄 回滚中..."
        PYTHONPATH=tools/upf python3 -m upf_tool revert --log "$LOG"
        ;;
esac
