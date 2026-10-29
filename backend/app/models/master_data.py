"""基础数据模型：物料 / 色号缸号 / 供应商 / 仓库 / 库位。"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, func

from app.core.database import Base


class Material(Base):
    """物料档案（含成品）。"""
    __tablename__ = "materials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_code = Column(String(64), unique=True, nullable=False, index=True)
    material_name = Column(String(128), nullable=False)
    category = Column(String(32), index=True)  # 面料/里料/辅料/五金/包材/成品
    spec = Column(String(128), default="")
    unit = Column(String(16), default="个")  # 米/码/个/套/kg
    default_color_no = Column(String(32), default="")
    safety_stock = Column(Float, default=0)
    min_order_qty = Column(Float, default=0)
    status = Column(Boolean, default=True)
    remark = Column(String(255), default="")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class MaterialColorBatch(Base):
    """面料色号缸号：一料多色号、一色多缸号，含缸差等级。"""
    __tablename__ = "material_color_batches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False, index=True)
    color_no = Column(String(32), nullable=False)
    vat_no = Column(String(32), nullable=False, index=True)  # 缸号
    color_diff_level = Column(String(8), default="A")  # 缸差 A/B/C
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    remark = Column(String(255), default="")
    created_at = Column(DateTime, default=func.now())


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    supplier_code = Column(String(64), unique=True, nullable=False, index=True)
    supplier_name = Column(String(128), nullable=False)
    contact = Column(String(64), default="")
    phone = Column(String(32), default="")
    address = Column(String(255), default="")
    payment_term = Column(String(64), default="")  # 付款方式
    lead_time_days = Column(Integer, default=0)
    status = Column(Boolean, default=True)
    remark = Column(String(255), default="")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class Warehouse(Base):
    __tablename__ = "warehouses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    warehouse_code = Column(String(64), unique=True, nullable=False, index=True)
    warehouse_name = Column(String(128), nullable=False)
    type = Column(String(32), default="原料仓")  # 原料仓/成品仓/外发暂存/不良品仓
    manager = Column(String(64), default="")
    status = Column(Boolean, default=True)
    remark = Column(String(255), default="")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    location_code = Column(String(64), nullable=False)
    location_name = Column(String(128), default="")
    status = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
