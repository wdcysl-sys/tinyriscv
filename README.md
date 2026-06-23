
![tinyriscv整体框架](./pic/arch.jpg)

开发备忘录：


现在的完整架构：

```
tools/upf/
├── upf-insert.sh          ← 🔑 通用入口 (任何 AI / 任何人都能调)
├── column_map.json
├── README.md
└── upf_tool/
    ├── cli.py             ← Python CLI 本体
    ├── models.py
    ├── excel_reader.py
    ├── rtl_inserter.py
    ├── upf_updater.py
    ├── change_logger.py
    └── revert.py
```

 **三种调用方式** ：

| 方式        | 谁用         | 命令                                                                          |
| ----------- | ------------ | ----------------------------------------------------------------------------- |
| Shell 脚本  | 任何 AI / 人 | `./tools/upf/upf-insert.sh` (预览) `--execute` (执行) `--revert` (回滚) |
| Python CLI  | 同上         | `PYTHONPATH=tools/upf python3 -m upf_tool insert ...`                       |
| Claude 对话 | Claude Code  | 直接说 "跑一下 UPF 植入" → AI 读 CLAUDE.md 自动调                            |

 **Qwen 用的话** ：让它执行 `./tools/upf/upf-insert.sh` 就行。想在 Qwen 里一句话调用，要看它的 VSCode 插件支不支持自定义 tool / rule 配置 — 类似 Cursor 的 `.cursorrules` 或 Copilot 的 `.github/copilot-instructions.md`。


## 核心区别

|                 | CLI                           | MCP                                |
| --------------- | ----------------------------- | ---------------------------------- |
| AI 怎么发现工具 | 读 README / 猜命令            | 自动注册，AI 直接看到函数签名      |
| 参数传递        | 拼字符串 `--excel foo.xlsx` | 结构化传参 `{excel: "foo.xlsx"}` |
| 返回结果        | 解析 stdout 文本              | 结构化 JSON 返回                   |
| 错误处理        | AI 看报错文本再猜原因         | 错误码 + 结构化错误信息            |
| 多工具组合      | AI 逐个拼命令                 | AI 编排多个 MCP tool 调用链        |

 **一句话** ：CLI 是人用的接口，MCP 是 AI 用的接口。5 个参数以下的简单工具 CLI 够了，参数多、需要和其他工具组合的时候就显出 MCP 的价值。你的 `upf_tool` 参数很少，CLI 完全够用。
