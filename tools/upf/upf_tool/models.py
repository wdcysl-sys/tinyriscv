"""
数据模型定义

IsoSignal   — 从 Excel 一行解析出的 ISO 信号信息
UpfBlock    — UPF 文件中一个 set_isolation 命令块
ChangeRecord — 单条修改记录
ChangeLog   — 一次运行的修改汇总
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class IsoSignal:
    """
    从 Excel 一行解析出的 ISO 信号信息

    每个实例对应 Excel 中的一行（一个需要 ISO 的信号），
    是工具处理的最小数据单元，贯穿整个 pipeline。
    """
    signal_name: str       # 原始信号名，如 "cpu_core_en"
    iso_enable: str        # ISO 使能信号名，如 "a_iso"（来自 set_isolation_control）
    iso_value: int         # clamp 值: 0 或 1
    pd_name: str           # 目标 Power Domain 名，如 "PD_A"
    target_file: str       # 目标模块/文件标识，如 "iso_b_to_a"
    signal_width: int = 1  # 信号位宽，默认 1（单比特）；多比特从 RTL wire 声明中提取
    target_module: str = ""  # 信号所在的 Verilog 模块名（RTL 搜索后填入）
    target_path: str = ""    # 信号所在的 .v 文件路径（RTL 搜索后填入）

    @property
    def fpga_signal_name(self) -> str:
        """生成 _fpga 后缀的信号名，如 cpu_core_en_fpga"""
        return f"{self.signal_name}_fpga"

    @property
    def tie_value_str(self) -> str:
        """
        生成 tie 值的 Verilog 常量字符串:
          单比特: 1'b0 或 1'b1
          多比特: 32'h0 或 32'hffffffff
        """
        if self.signal_width == 1:
            return f"1'b{self.iso_value}"
        hex_digits = self.signal_width // 4
        if self.iso_value == 1:
            return f"{self.signal_width}'h{'f' * hex_digits}"
        else:
            return f"{self.signal_width}'h0"

    @property
    def assign_code(self) -> str:
        """
        生成完整的 Verilog assign 语句

        单比特示例:
          assign cpu_core_en_fpga = a_iso ? 1'b1 : cpu_core_en;
        多比特示例:
          assign axi_m_awready_fpga[31:0] = a_iso ? 32'hffffffff : axi_m_awready[31:0];
        """
        if self.signal_width == 1:
            return (
                f"assign {self.fpga_signal_name} = "
                f"{self.iso_enable} ? {self.tie_value_str} : {self.signal_name};"
            )
        high = self.signal_width - 1
        return (
            f"assign {self.fpga_signal_name}[{high}:0] = "
            f"{self.iso_enable} ? {self.tie_value_str} : {self.signal_name}[{high}:0];"
        )

    @property
    def comment_line(self) -> str:
        """生成 ISO 信号的注释行，记录 domain 关系和 clamp 值"""
        return f"// UPF ISO: {self.pd_name}, clamp={self.iso_value}"


@dataclass
class UpfBlock:
    """
    UPF 文件中一个 set_isolation 命令块

    示例:
      set_isolation iso_b_to_a \
          -domain PD_A \
          -clamp_value 1 \
          -elements {
              cpu_core_en/
              axi_m_awready/
          }
    """
    name: str                    # ISO 策略名称，如 "iso_b_to_a"
    domain: str                  # -domain 值，如 "PD_A"
    clamp_value: Optional[int]   # -clamp_value 值: 0/1/None（缺失时）
    elements: List[str]          # -elements 中的信号名列表（不含 / 后缀）
    start_line: int              # 块开始行号（"set_isolation ..." 行）
    end_line: int                # 块结束行号（elements 的 "}" 行）
    raw_text: str                # 块原始文本，用于替换


@dataclass
class ChangeRecord:
    """
    单条修改记录

    每次对文件的修改（RTL 插入一行、UPF 替换一段）都生成一条记录。
    所有记录汇总成 ChangeLog，最终输出为 Markdown 日志文件。
    """
    change_type: str     # "rtl_insert" | "upf_elements_update" | "upf_clamp_value_add"
    file_path: str       # 被修改的文件路径
    line_number: int     # 修改所在行号
    old_value: str       # 修改前的值（用于回滚；新增时为空字符串）
    new_value: str       # 修改后的值
    signal_name: str     # 关联的信号名（方便日志检索）
    description: str     # 人类可读的修改描述


@dataclass
class ChangeLog:
    """
    修改日志汇总

    包含一次运行的所有修改记录，用于:
    1. 生成 Markdown 日志文件
    2. revert 回滚（遍历 records 逐个撤销）
    """
    execution_time: str = ""
    excel_file: str = ""
    upf_file: str = ""
    rtl_dir: str = ""
    dry_run: bool = False
    records: List[ChangeRecord] = field(default_factory=list)

    @property
    def rtl_changes(self) -> List[ChangeRecord]:
        """筛选 RTL 相关修改"""
        return [r for r in self.records if r.change_type == "rtl_insert"]

    @property
    def upf_changes(self) -> List[ChangeRecord]:
        """筛选 UPF 相关修改"""
        return [r for r in self.records if r.change_type.startswith("upf_")]

    @property
    def skipped_count(self) -> int:
        """因幂等检查跳过的数量"""
        return len([r for r in self.records if r.change_type == "skipped"])

    @property
    def error_count(self) -> int:
        """错误数量"""
        return len([r for r in self.records if r.change_type == "error"])
