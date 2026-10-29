"""库存核心服务：所有库存变动统一入口，保证流水与台账一致。
入库/出库操作不自动提交，由调用方在单据审核时整体 commit/rollback，保证单据级原子性。"""
from datetime import date

from sqlalchemy import and_, select

from app.core.exceptions import BizException
from app.models.inventory import Inventory, InventoryTransaction
from app.utils.numbering import gen_no


def _eq_or_none(col, value):
    """可空字段的匹配条件：None 用 IS NULL。"""
    return col.is_(None) if value is None else (col == value)


def _get_inventory(db, material_id, warehouse_id, location_id, color_batch_id):
    stmt = select(Inventory).where(
        and_(
            Inventory.material_id == material_id,
            Inventory.warehouse_id == warehouse_id,
            _eq_or_none(Inventory.location_id, location_id),
            _eq_or_none(Inventory.color_batch_id, color_batch_id),
        )
    )
    return db.execute(stmt).scalar_one_or_none()


def _move(db, *, material_id, warehouse_id, location_id, color_batch_id,
          signed_qty, in_qty, out_qty, txn_type, ref_type, ref_id, operator):
    inv = _get_inventory(db, material_id, warehouse_id, location_id, color_batch_id)
    if inv:
        inv.qty = (inv.qty or 0) + signed_qty
    else:
        if signed_qty < 0:
            raise BizException("库存不足，无法出库")
        inv = Inventory(
            material_id=material_id, warehouse_id=warehouse_id,
            location_id=location_id, color_batch_id=color_batch_id, qty=signed_qty,
        )
        db.add(inv)
    if inv.qty < 0:
        raise BizException(f"物料库存不足，当前仅剩 {inv.qty - signed_qty}")
    inv.last_move_date = date.today().isoformat()

    txn = InventoryTransaction(
        txn_no=gen_no("TXN"), txn_type=txn_type, material_id=material_id,
        color_batch_id=color_batch_id, warehouse_id=warehouse_id, location_id=location_id,
        in_qty=in_qty, out_qty=out_qty, ref_type=ref_type, ref_id=ref_id, operator=operator,
    )
    db.add(txn)
    db.flush()


def post_inbound(db, *, material_id, warehouse_id, location_id=None, color_batch_id=None,
                 qty, txn_type="采购入库", ref_type="", ref_id=None, operator=""):
    if qty <= 0:
        raise BizException("入库数量必须大于 0")
    _move(db, material_id=material_id, warehouse_id=warehouse_id, location_id=location_id,
          color_batch_id=color_batch_id, signed_qty=qty, in_qty=qty, out_qty=0,
          txn_type=txn_type, ref_type=ref_type, ref_id=ref_id, operator=operator)


def post_outbound(db, *, material_id, warehouse_id, location_id=None, color_batch_id=None,
                  qty, txn_type="其他出库", ref_type="", ref_id=None, operator=""):
    if qty <= 0:
        raise BizException("出库数量必须大于 0")
    _move(db, material_id=material_id, warehouse_id=warehouse_id, location_id=location_id,
          color_batch_id=color_batch_id, signed_qty=-qty, in_qty=0, out_qty=qty,
          txn_type=txn_type, ref_type=ref_type, ref_id=ref_id, operator=operator)
