"""AI 单据识别相关 Schema。"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class _Flex(BaseModel):
    model_config = ConfigDict(extra="allow")


class OcrImport(_Flex):
    """导入参数：确认后的单据信息 + 明细 + 可选的关联订单/收货仓库。

    仅在「关联采购订单 + 收货仓库 + 全明细均已匹配物料」时才会生成到货单；
    否则只把识别结果留档（状态置为已导入）。
    """
    doc_no: Optional[str] = None
    doc_type: Optional[str] = None
    supplier_name: Optional[str] = None
    supplier_id: Optional[int] = None
    order_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    actual_receipt_date: Optional[str] = None  # 仅生成到货时由人明确声明，不从OCR日期推断
    remark: str = ""
    items: list[dict] = Field(default_factory=list)  # {id?, material_id, spec, unit, qty}


class AiModelConfigIn(_Flex):
    """模型档案：一份可保存/切换的识别引擎参数。

    `api_key` 留空表示「不修改」（编辑时前端不会把脱敏值回传）；
    新增时留空则视为「该档案不需要密钥」（只对 mock 有意义）。
    """
    name: str = Field(default="", max_length=64)
    provider: str = Field(default="mock", max_length=32)
    base_url: str = Field(default="", max_length=255)
    model: str = Field(default="", max_length=128)
    api_key: Optional[str] = Field(default=None, max_length=255)
    timeout: int = Field(default=60, ge=3, le=600)
    json_mode: bool = True
    retry: int = Field(default=1, ge=0, le=5)
    remark: str = Field(default="", max_length=255)
