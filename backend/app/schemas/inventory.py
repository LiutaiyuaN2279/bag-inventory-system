"""库存相关 Schema。"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class _Flex(BaseModel):
    model_config = ConfigDict(extra="allow")


class StocktakeCreate(_Flex):
    warehouse_id: int
    remark: str = ""
    items: list[dict] = Field(default_factory=list)  # {material_id, location_id, color_batch_id, counted_qty}


class StocktakeItemUpdate(_Flex):
    counted_qty: float


class TransferCreate(_Flex):
    """新建调拨单：调出/调入仓库必填，明细以列表传入。"""
    from_warehouse_id: int
    to_warehouse_id: int
    operator: str = ""
    remark: str = ""
    # {material_id, qty, unit, color_batch_id, from_location_id, to_location_id, remark}
    items: list[dict] = Field(default_factory=list)


class TransferUpdate(_Flex):
    """修改草稿调拨单：字段为 None 表示不修改。"""
    from_warehouse_id: Optional[int] = None
    to_warehouse_id: Optional[int] = None
    operator: Optional[str] = None
    remark: Optional[str] = None
    items: Optional[list[dict]] = None
