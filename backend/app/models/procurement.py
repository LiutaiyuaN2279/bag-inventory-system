"""采购模型：请购单 → 采购订单 → 到货单(入库) → 采购退货。
状态联动：请购审核后可转订单；到货验收合格触发采购入库（实时更新库存）；
采购退货审核触发出库。"""
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, func

from app.core.database import Base


# ---------------- 请购单 ----------------
class PurchaseRequisition(Base):
    __tablename__ = "purchase_requisitions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    req_no = Column(String(32), unique=True, nullable=False, index=True)
    requisitioner = Column(String(64), default="")       # 申请人
    dept = Column(String(64), default="")                # 申请部门
    status = Column(String(16), default="草稿")          # 草稿/已审核/已关闭/已作废/已驳回
    reject_reason = Column(String(255), default="")      # 驳回原因
    remark = Column(String(255), default="")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class PurchaseRequisitionItem(Base):
    __tablename__ = "purchase_requisition_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pr_id = Column(Integer, ForeignKey("purchase_requisitions.id"), nullable=False, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    qty = Column(Float, default=0)
    unit = Column(String(16), default="个")
    ordered_qty = Column(Float, default=0)              # 已转采购订单数量
    requirement_date = Column(String(16), default="")
    remark = Column(String(255), default="")


# ---------------- 采购订单 ----------------
class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_no = Column(String(32), unique=True, nullable=False, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    pr_id = Column(Integer, nullable=True)               # 来源请购单
    status = Column(String(16), default="草稿")          # 草稿/已审核/部分到货/已完成/已作废/已驳回
    reject_reason = Column(String(255), default="")      # 驳回原因
    total_amount = Column(Float, default=0)
    remark = Column(String(255), default="")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False, index=True)
    pr_item_id = Column(Integer, nullable=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    qty = Column(Float, default=0)
    unit_price = Column(Float, default=0)
    arrived_qty = Column(Float, default=0)              # 累计到货
    inbound_qty = Column(Float, default=0)              # 累计入库
    unit = Column(String(16), default="个")


# ---------------- 到货单 ----------------
class PurchaseArrival(Base):
    __tablename__ = "purchase_arrivals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    arrival_no = Column(String(32), unique=True, nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    status = Column(String(16), default="待验收")        # 待验收/已验收/已驳回
    actual_receipt_date = Column(String(10), nullable=True)  # 人工声明实际收货日；旧记录不回填
    inbound_posted_at = Column(DateTime, nullable=True)     # 实际过账记录时间，不回填业务日期
    reject_reason = Column(String(255), default="")      # 驳回原因
    remark = Column(String(255), default="")
    created_at = Column(DateTime, default=func.now())


class PurchaseArrivalItem(Base):
    __tablename__ = "purchase_arrival_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    arrival_id = Column(Integer, ForeignKey("purchase_arrivals.id"), nullable=False, index=True)
    order_item_id = Column(Integer, ForeignKey("purchase_order_items.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    arrived_qty = Column(Float, default=0)
    qualified_qty = Column(Float, default=0)            # 合格数量（入库数）
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    location_id = Column(Integer, nullable=True)
    color_batch_id = Column(Integer, nullable=True)


# ---------------- 采购退货 ----------------
class PurchaseReturn(Base):
    __tablename__ = "purchase_returns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    return_no = Column(String(32), unique=True, nullable=False, index=True)
    order_id = Column(Integer, nullable=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    status = Column(String(16), default="草稿")          # 草稿/已审核/已驳回
    reject_reason = Column(String(255), default="")      # 驳回原因
    remark = Column(String(255), default="")
    created_at = Column(DateTime, default=func.now())


class PurchaseReturnItem(Base):
    __tablename__ = "purchase_return_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    return_id = Column(Integer, ForeignKey("purchase_returns.id"), nullable=False, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    qty = Column(Float, default=0)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    location_id = Column(Integer, nullable=True)
    color_batch_id = Column(Integer, nullable=True)
    remark = Column(String(255), default="")
