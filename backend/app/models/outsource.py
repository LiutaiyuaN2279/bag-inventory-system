"""外发加工：发外加工单 —— 发料出库 + 收回入库，状态联动库存。"""
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, func

from app.core.database import Base


class OutsourceOrder(Base):
    __tablename__ = "outsource_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_no = Column(String(32), unique=True, nullable=False, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)   # 加工商
    product_id = Column(Integer, ForeignKey("materials.id"), nullable=False)    # 收回的成品/半成品
    out_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)   # 发料仓
    in_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)    # 收回仓
    received_qty = Column(Float, default=0)                 # 已收回数量
    plan_qty = Column(Float, default=0)                     # 计划收回数量
    status = Column(String(16), default="草稿")             # 草稿/已发料/部分收回/已完成
    remark = Column(String(255), default="")
    created_at = Column(DateTime, default=func.now())


class OutsourceOrderItem(Base):
    """发出的原料明细。"""
    __tablename__ = "outsource_order_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("outsource_orders.id"), nullable=False, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    qty = Column(Float, default=0)                          # 应发数量
    issued_qty = Column(Float, default=0)                   # 已发数量
    unit = Column(String(16), default="个")
    remark = Column(String(255), default="")
