"""采购相关 Schema：单据采用宽松字段（extra allow），明细以列表传入。"""
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Flex(BaseModel):
    model_config = ConfigDict(extra="allow")


class RequisitionCreate(_Flex):
    requisitioner: str = ""
    dept: str = ""
    remark: str = ""
    items: list[dict] = Field(default_factory=list)


class RequisitionUpdate(_Flex):
    requisitioner: Optional[str] = None
    dept: Optional[str] = None
    remark: Optional[str] = None
    items: Optional[list[dict]] = None


class OrderCreate(_Flex):
    supplier_id: int
    pr_id: Optional[int] = None
    remark: str = ""
    items: list[dict] = Field(default_factory=list)


class OrderUpdate(_Flex):
    supplier_id: Optional[int] = None
    remark: Optional[str] = None
    items: Optional[list[dict]] = None


class ArrivalCreate(_Flex):
    order_id: int
    remark: str = ""
    items: list[dict] = Field(default_factory=list)  # {order_item_id, arrived_qty, qualified_qty, warehouse_id, location_id, color_batch_id}


class ReturnCreate(_Flex):
    supplier_id: int
    order_id: Optional[int] = None
    remark: str = ""
    items: list[dict] = Field(default_factory=list)  # {material_id, qty, warehouse_id, location_id, color_batch_id}
