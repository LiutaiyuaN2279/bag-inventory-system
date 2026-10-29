"""基础数据 Schema：物料 / 供应商 / 仓库。字段与数据表保持一致。"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------- 物料 ----------------
class MaterialBase(BaseModel):
    material_code: str = Field(..., max_length=64)
    material_name: str = Field(..., max_length=128)
    category: Optional[str] = ""
    spec: Optional[str] = ""
    unit: Optional[str] = "个"
    default_color_no: Optional[str] = ""
    safety_stock: Optional[float] = 0
    min_order_qty: Optional[float] = 0
    status: Optional[bool] = True
    remark: Optional[str] = ""


class MaterialCreate(MaterialBase):
    pass


class MaterialUpdate(BaseModel):
    material_name: Optional[str] = None
    category: Optional[str] = None
    spec: Optional[str] = None
    unit: Optional[str] = None
    default_color_no: Optional[str] = None
    safety_stock: Optional[float] = None
    min_order_qty: Optional[float] = None
    status: Optional[bool] = None
    remark: Optional[str] = None


class MaterialOut(MaterialBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---------------- 供应商 ----------------
class SupplierBase(BaseModel):
    supplier_code: str = Field(..., max_length=64)
    supplier_name: str = Field(..., max_length=128)
    contact: Optional[str] = ""
    phone: Optional[str] = ""
    address: Optional[str] = ""
    payment_term: Optional[str] = ""
    lead_time_days: Optional[int] = 0
    status: Optional[bool] = True
    remark: Optional[str] = ""


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(BaseModel):
    supplier_name: Optional[str] = None
    contact: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    payment_term: Optional[str] = None
    lead_time_days: Optional[int] = None
    status: Optional[bool] = None
    remark: Optional[str] = None


class SupplierOut(SupplierBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---------------- 仓库 ----------------
class WarehouseBase(BaseModel):
    warehouse_code: str = Field(..., max_length=64)
    warehouse_name: str = Field(..., max_length=128)
    type: Optional[str] = "原料仓"
    manager: Optional[str] = ""
    status: Optional[bool] = True
    remark: Optional[str] = ""


class WarehouseCreate(WarehouseBase):
    pass


class WarehouseUpdate(BaseModel):
    warehouse_name: Optional[str] = None
    type: Optional[str] = None
    manager: Optional[str] = None
    status: Optional[bool] = None
    remark: Optional[str] = None


class WarehouseOut(WarehouseBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
