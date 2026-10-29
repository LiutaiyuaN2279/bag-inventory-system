"""BOM 相关 Schema。"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class _Flex(BaseModel):
    model_config = ConfigDict(extra="allow")


class BomCreate(_Flex):
    product_id: int
    version: str
    version_name: str = ""
    status: str = "草稿"
    effective_date: str = ""
    default_loss_rate: float = 0
    remark: str = ""
    items: list[dict] = Field(default_factory=list)  # {material_id, qty, loss_rate, unit, is_substitute, substitute_for}


class BomUpdate(_Flex):
    version_name: Optional[str] = None
    status: Optional[str] = None
    effective_date: Optional[str] = None
    default_loss_rate: Optional[float] = None
    remark: Optional[str] = None
    items: Optional[list[dict]] = None


class BomCalculateIn(BaseModel):
    product_id: int
    version: Optional[str] = None   # 不填取最新生效版本
    qty: float = 1


class BomToRequisitionIn(BomCalculateIn):
    """算料结果一键转请购单：算料入参 + 算料结果明细。"""
    model_config = ConfigDict(extra="allow")

    items: list[dict] = Field(default_factory=list)  # 前端算料结果明细 {material_id, required_qty, unit}，留空则后端按算料入参重新算料
    requisitioner: str = ""                          # 不填取当前登录人
    dept: str = ""                                   # 不填按采购部
    remark: str = ""                                 # 追加到请购单备注（自动带「由 BOM 算料自动生成」）
    requirement_date: str = ""                       # 期望到货日期 yyyy-mm-dd，落到请购明细
