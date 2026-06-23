"""
配置加载模块

加载 column_map.json，将 Excel 的列名映射到工具内部使用的字段名。
如果 json 文件不存在，使用硬编码的默认映射。
"""

import json
import os
from typing import Dict


# 默认列名映射（与 column_map.json 内容一致，做兜底）
DEFAULT_COLUMN_MAP: Dict[str, str] = {
    "pd_name": "pd_name",
    "target_file": "sys_name",
    "iso_enable": "iso使能",
    "signal_name": "需要插入iso的信号名",
    "iso_value": "iso tie 0/1",
}


def load_column_map() -> Dict[str, str]:
    """
    加载 Excel 列名映射配置

    优先读 tools/upf/column_map.json，找不到则用 DEFAULT_COLUMN_MAP。

    返回: {内部字段名: Excel 列名}
      示例: {"signal_name": "需要插入iso的信号名", "iso_value": "iso tie 0/1"}
    """
    # column_map.json 与本模块同级（tools/upf/）
    json_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "column_map.json",
    )
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return dict(DEFAULT_COLUMN_MAP)


def reverse_map(column_map: Dict[str, str]) -> Dict[str, str]:
    """
    反转列名映射: {内部字段名: Excel列名} → {Excel列名: 内部字段名}

    用于 Excel 读取时通过表头快速定位:
      Excel 列名 "iso使能" → 内部字段名 "iso_enable"
    """
    return {v: k for k, v in column_map.items()}
