# UPF ISO 植入工具

从 Power Domain Excel 自动生成 ISO 代码并植入 RTL，同步更新 UPF 文件。

## 快速使用

```bash
cd <project_root>

# 1. 预览修改 (安全，不写文件)
PYTHONPATH=tools/upf python3 -m upf_tool insert \
    --excel <excel文件>.xlsx \
    --upf <upf文件> \
    --rtl-dir <rtl目录>/ \
    --dry-run

# 2. 确认无误后执行
PYTHONPATH=tools/upf python3 -m upf_tool insert \
    --excel <excel文件>.xlsx \
    --upf <upf文件> \
    --rtl-dir <rtl目录>/

# 3. 回滚
PYTHONPATH=tools/upf python3 -m upf_tool revert --log upf_changes.md
```

## Excel 格式要求

| 列 | 列名 | 说明 |
|----|------|------|
| A | pd_name | Power Domain 名称，如 PD_A |
| B | sys_name | ISO 策略标识，对应 UPF 中 set_isolation 名称，如 iso_b_to_a |
| C | iso使能 | ISO 使能信号名，如 a_iso |
| D | 需要插入iso的信号名 | 需要 ISO 的信号名 |
| E | iso tie 0/1 | clamp 值: 0 或 1 |

合并单元格会自动继承上一行的值。

## 适配其他项目

1. 复制 `tools/upf/` 目录到目标项目
2. 修改 `tools/upf/column_map.json` 适配 Excel 列名
3. 修改 Excel，填入目标项目的 pd_name / sys_name / 信号名 / tie 值
4. 放置 UPF 文件和 RTL 目录
5. 运行上述命令

## 工作原理

- **RTL 植入**: 搜索信号 → 找所在模块 → 在最后一个 wire 后插入 `assign sig_fpga = iso_en ? tie : sig;`
- **UPF 更新**: Excel 信号名 ↔ UPF elements 同步（不加 _fpga 后缀），按 sys_name + tie 值匹配 block
- **幂等**: 重复运行安全，已存在的不会重复插入
- **回滚**: 根据 Markdown 日志精确撤销
