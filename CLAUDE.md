# tinyriscv 项目指南

## UPF ISO 植入工具

位置: `tools/upf/`

从 Power Domain Excel 一键完成 RTL 植入 + UPF 更新。

### 命令

```bash
# 预览 (安全，不写文件)
PYTHONPATH=tools/upf python3 -m upf_tool insert \
    --excel <excel>.xlsx --upf <upf文件> --rtl-dir <rtl目录>/ --dry-run

# 执行
PYTHONPATH=tools/upf python3 -m upf_tool insert \
    --excel <excel>.xlsx --upf <upf文件> --rtl-dir <rtl目录>/

# 回滚
PYTHONPATH=tools/upf python3 -m upf_tool revert --log upf_changes.md
```

### Excel 列

| 列 | 列名 | 说明 |
|----|------|------|
| A | pd_name | Power Domain 名 |
| B | sys_name | UPF 中 set_isolation 名称 |
| C | iso使能 | ISO 使能信号 |
| D | 需要插入iso的信号名 | 信号名 |
| E | iso tie 0/1 | clamp 值 |

### 规则

- Excel 是唯一权威来源 — UPF elements 增删都跟 Excel 走
- UPF 不加 `_fpga` 后缀，`_fpga` 只在 RTL assign 语句中使用
- 幂等：重复运行安全
- 回滚：根据 Markdown 日志撤销

### 适配其他项目

1. 复制 `tools/upf/` 到目标项目
2. 修改 `column_map.json` 适配对方 Excel 列名
3. 填入目标项目的 Excel/UPF/RTL
4. 运行命令
