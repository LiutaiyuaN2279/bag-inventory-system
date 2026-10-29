"""库存模型：库存台账 + 出入库流水 + 盘点。"""
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, func

from app.core.database import Base


class Inventory(Base):
    """库存台账：按 物料+仓库+库位+缸号批次 归集，实时更新。"""
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    location_id = Column(Integer, nullable=True)
    color_batch_id = Column(Integer, nullable=True, index=True)
    qty = Column(Float, default=0)
    last_move_date = Column(String(16), default="")     # 最近动销日期 yyyy-mm-dd


class InventoryTransaction(Base):
    """出入库流水：所有库存变动的审计记录。"""
    __tablename__ = "inventory_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    txn_no = Column(String(32), nullable=False, index=True)
    txn_type = Column(String(32), nullable=False)       # 采购入库/采购退货出库/盘盈入库/盘亏出库/其他入库/其他出库
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    color_batch_id = Column(Integer, nullable=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    location_id = Column(Integer, nullable=True)
    in_qty = Column(Float, default=0)
    out_qty = Column(Float, default=0)
    ref_type = Column(String(32), default="")           # 来源单据类型
    ref_id = Column(Integer, nullable=True)             # 来源单据 id
    operator = Column(String(64), default="")
    txn_time = Column(DateTime, default=func.now(), index=True)


class Stocktake(Base):
    __tablename__ = "stocktakes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stocktake_no = Column(String(32), unique=True, nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    status = Column(String(16), default="草稿")          # 草稿/盘点中/已完成/已驳回
    reject_reason = Column(String(255), default="")      # 驳回原因
    remark = Column(String(255), default="")
    created_at = Column(DateTime, default=func.now())


class StocktakeItem(Base):
    __tablename__ = "stocktake_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stocktake_id = Column(Integer, ForeignKey("stocktakes.id"), nullable=False, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    color_batch_id = Column(Integer, nullable=True)
    location_id = Column(Integer, nullable=True)
    book_qty = Column(Float, default=0)                 # 账面数量
    counted_qty = Column(Float, default=0)              # 实盘数量


# ---------------- 仓库调拨 ----------------
class TransferOrder(Base):
    """调拨单：从调出仓库出库、向调入仓库入库，走同一套库存流水。"""
    __tablename__ = "transfer_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transfer_no = Column(String(32), unique=True, nullable=False, index=True)
    from_warehouse_id = Column(Integer, nullable=False, index=True)  # 调出仓库
    to_warehouse_id = Column(Integer, nullable=False, index=True)    # 调入仓库
    status = Column(String(16), default="草稿")         # 草稿/已审核/已作废
    executed = Column(Boolean, default=False)           # 是否已执行过库存动作（决定作废时是否反向回滚）
    operator = Column(String(64), default="")           # 经办人
    remark = Column(String(255), default="")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    approve_time = Column(DateTime, nullable=True)      # 审核时间
    void_time = Column(DateTime, nullable=True)         # 作废时间


class TransferItem(Base):
    __tablename__ = "transfer_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transfer_id = Column(Integer, nullable=False, index=True)       # 归属调拨单
    material_id = Column(Integer, nullable=False)
    color_batch_id = Column(Integer, nullable=True)                 # 颜色批次（缸号）
    qty = Column(Float, default=0)
    unit = Column(String(16), default="个")
    from_location_id = Column(Integer, nullable=True)               # 调出库位
    to_location_id = Column(Integer, nullable=True)                 # 调入库位
    remark = Column(String(255), default="")
