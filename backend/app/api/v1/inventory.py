"""库存查询、出入库流水、其他出入库调整。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api._helpers import load_maps
from app.api.deps import get_current_user, require_permissions
from app.core.database import get_db
from app.core.exceptions import BizException
from app.models.inventory import Inventory, InventoryTransaction
from app.models.master_data import Material
from app.models.rbac import User
from app.crud.crud_base import apply_ordering
from app.services.stock_service import post_inbound, post_outbound
from app.utils.response import page_result, success

router = APIRouter(prefix="/inventory", tags=["库存管理"])


@router.get("")
def list_inventory(page: int = 1, page_size: int = 20, keyword: str | None = None,
                   warehouse_id: int | None = None, sort_by: str | None = None,
                   sort_order: str | None = None, db: Session = Depends(get_db),
                   _=Depends(require_permissions("inventory:view"))):
    mats, whs, _ = load_maps(db)
    q = db.query(Inventory)
    if warehouse_id:
        q = q.filter(Inventory.warehouse_id == warehouse_id)
    if keyword:
        ids = [mid for mid, name in mats.items() if keyword in name]
        # 也匹配物料编码
        code_ids = [m.id for m in db.query(Material).filter(Material.material_code.like(f"%{keyword}%")).all()]
        ids = list(set(ids + code_ids))
        q = q.filter(Inventory.material_id.in_(ids)) if ids else q.filter(False)
    total = q.count()
    rows = apply_ordering(q, Inventory, sort_by, sort_order).offset((page - 1) * page_size).limit(page_size).all()
    data = [
        {"id": r.id, "material_id": r.material_id, "material_name": mats.get(r.material_id, ""),
         "warehouse_id": r.warehouse_id, "warehouse_name": whs.get(r.warehouse_id, ""),
         "location_id": r.location_id, "color_batch_id": r.color_batch_id,
         "qty": r.qty, "last_move_date": r.last_move_date}
        for r in rows
    ]
    return success(page_result(data, total))


@router.get("/transactions")
def list_transactions(page: int = 1, page_size: int = 20, keyword: str | None = None,
                      txn_type: str | None = None, sort_by: str | None = None,
                      sort_order: str | None = None, db: Session = Depends(get_db),
                      _=Depends(require_permissions("inventory:view"))):
    mats, whs, _ = load_maps(db)
    q = db.query(InventoryTransaction)
    if txn_type:
        q = q.filter(InventoryTransaction.txn_type == txn_type)
    if keyword:
        ids = [mid for mid, name in mats.items() if keyword in name]
        q = q.filter(InventoryTransaction.material_id.in_(ids)) if ids else q.filter(False)
    total = q.count()
    rows = apply_ordering(q, InventoryTransaction, sort_by, sort_order).offset((page - 1) * page_size).limit(page_size).all()
    data = [
        {"id": r.id, "txn_no": r.txn_no, "txn_type": r.txn_type,
         "material_id": r.material_id, "material_name": mats.get(r.material_id, ""),
         "warehouse_name": whs.get(r.warehouse_id, ""), "in_qty": r.in_qty, "out_qty": r.out_qty,
         "ref_type": r.ref_type, "operator": r.operator, "txn_time": str(r.txn_time)[:19]}
        for r in rows
    ]
    return success(page_result(data, total))


@router.post("/adjust")
def other_adjust(payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                 _=Depends(require_permissions("inventory:adjust"))):
    """其他出入库：direction=in 入库 / out 出库。"""
    direction = payload.get("direction")
    material_id = payload.get("material_id")
    warehouse_id = payload.get("warehouse_id")
    qty = float(payload.get("qty", 0))
    if not material_id or not warehouse_id or qty <= 0:
        raise BizException("物料、仓库、数量必填且数量大于 0")
    try:
        if direction == "in":
            post_inbound(db, material_id=material_id, warehouse_id=warehouse_id,
                         location_id=payload.get("location_id"), color_batch_id=payload.get("color_batch_id"),
                         qty=qty, txn_type=payload.get("txn_type", "其他入库"), operator=user.username)
        else:
            post_outbound(db, material_id=material_id, warehouse_id=warehouse_id,
                          location_id=payload.get("location_id"), color_batch_id=payload.get("color_batch_id"),
                          qty=qty, txn_type=payload.get("txn_type", "其他出库"), operator=user.username)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return success(message="操作成功，库存已更新")
