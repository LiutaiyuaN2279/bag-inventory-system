"""到货单：创建（回写订单到货数）→ 验收（触发采购入库，库存实时更新）。"""
from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.api._batch import run_batch_guarded
from app.api._helpers import load_maps, material_meta
from app.api.deps import get_current_user, require_permissions
from app.core.database import get_db
from app.core.exceptions import BizException
from app.models.master_data import Material
from app.models.procurement import (
    PurchaseArrival, PurchaseArrivalItem, PurchaseOrderItem,
)
from app.models.rbac import User
from app.crud.crud_base import apply_ordering
from app.schemas.batch import BatchIn
from app.schemas.procurement import ArrivalCreate
from app.services.arrival_service import create_arrival as build_arrival, round_qty
from app.services.stock_service import post_inbound
from app.utils.response import page_result, success
from app.api.v1.purchase_orders import refresh_order_status

router = APIRouter(prefix="/purchase-arrivals", tags=["采购-到货入库"])


def _row_dict(r, sups):
    return {
        "id": r.id, "arrival_no": r.arrival_no, "order_id": r.order_id,
        "supplier_id": r.supplier_id, "supplier_name": sups.get(r.supplier_id, ""),
        "status": r.status, "reject_reason": r.reject_reason, "remark": r.remark, "created_at": str(r.created_at)[:19],
    }


def _get_arrival(db: Session, aid: int) -> PurchaseArrival:
    arr = db.get(PurchaseArrival, aid)
    if not arr:
        raise BizException("到货单不存在")
    return arr


def _do_approve(db: Session, arr: PurchaseArrival, operator: str) -> None:
    """验收核心逻辑：逐明细采购入库 + 回写订单明细入库数 + 刷新订单状态（不 commit）。"""
    if arr.status != "待验收":
        raise BizException("仅待验收单据可验收")
    items = db.query(PurchaseArrivalItem).filter(PurchaseArrivalItem.arrival_id == arr.id).all()
    for it in items:
        if it.qualified_qty > 0:
            post_inbound(
                db, material_id=it.material_id, warehouse_id=it.warehouse_id,
                location_id=it.location_id, color_batch_id=it.color_batch_id,
                qty=it.qualified_qty, txn_type="采购入库",
                ref_type="采购到货", ref_id=arr.id, operator=operator)
            oi = db.get(PurchaseOrderItem, it.order_item_id)
            if oi:
                oi.inbound_qty = (oi.inbound_qty or 0) + it.qualified_qty
    arr.status = "已验收"
    refresh_order_status(db, arr.order_id)


def _do_reject(db: Session, arr: PurchaseArrival, reason: str) -> None:
    """驳回核心逻辑：回滚订单明细到货数 + 置驳回状态 + 刷新订单状态（不 commit）。"""
    if arr.status != "待验收":
        raise BizException("仅待验收单据可驳回")
    if not (reason or "").strip():
        raise BizException("请填写驳回原因")
    items = db.query(PurchaseArrivalItem).filter(PurchaseArrivalItem.arrival_id == arr.id).all()
    _mu = {m.id: (m.unit or '') for m in db.query(Material).all()}
    # 回滚创建到货单时回写到订单明细的到货数，避免驳回后累计到货仍被计入
    for it in items:
        oi = db.get(PurchaseOrderItem, it.order_item_id)
        if oi:
            unit = _mu.get(oi.material_id, '')
            oi.arrived_qty = max(0.0, round_qty((oi.arrived_qty or 0) - (it.arrived_qty or 0), unit))
    arr.status = "已驳回"
    arr.reject_reason = reason.strip()[:255]
    refresh_order_status(db, arr.order_id)   # 同步刷新订单状态（部分到货 → 已审核）


# ---------------- 批量操作 ----------------
# 必须声明在任何 /{xxx} 形式的动态路由之前，否则 batch 会被当作 id 匹配掉（int 转换失败报 422）
BATCH_PERMS = {
    "approve": "purchase:arrival:approve",
    "reject": "purchase:arrival:approve",
}


@router.post("/batch")
def batch_arrivals(payload: BatchIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """批量验收/驳回到货单（逐条独立事务，返回失败明细）。"""
    reason = (payload.reason or "").strip()
    operator = user.username

    def _one(db: Session, item_id: int, action: str) -> None:
        arr = _get_arrival(db, item_id)
        if action == "approve":
            _do_approve(db, arr, operator)
        elif action == "reject":
            _do_reject(db, arr, reason)
        else:
            raise BizException(f"不支持的批量动作：{action}")

    return run_batch_guarded(db, user, payload, BATCH_PERMS, _one)


@router.get("")
def list_arrivals(page: int = 1, page_size: int = 20, keyword: str | None = None,
                  status: str | None = None, sort_by: str | None = None,
                  sort_order: str | None = None, db: Session = Depends(get_db),
                  _=Depends(require_permissions("purchase:arrival:list"))):
    q = db.query(PurchaseArrival)
    if keyword:
        q = q.filter(PurchaseArrival.arrival_no.like(f"%{keyword}%"))
    if status:
        q = q.filter(PurchaseArrival.status == status)
    total = q.count()
    rows = apply_ordering(q, PurchaseArrival, sort_by, sort_order).offset((page - 1) * page_size).limit(page_size).all()
    _, _, sups = load_maps(db)
    return success(page_result([_row_dict(r, sups) for r in rows], total))


@router.get("/{aid}")
def detail_arrival(aid: int, db: Session = Depends(get_db), _=Depends(require_permissions("purchase:arrival:list"))):
    arr = db.get(PurchaseArrival, aid)
    if not arr:
        raise BizException("到货单不存在")
    mats, whs, sups = load_maps(db)
    meta = material_meta(db)
    items = db.query(PurchaseArrivalItem).filter(PurchaseArrivalItem.arrival_id == aid).all()
    data = _row_dict(arr, sups)
    data["items"] = [
        {"id": i.id, "material_id": i.material_id, "material_name": mats.get(i.material_id, ""),
         "spec": meta.get(i.material_id, {}).get("spec", ""),
         "unit": meta.get(i.material_id, {}).get("unit", ""),
         "arrived_qty": i.arrived_qty, "qualified_qty": i.qualified_qty,
         "warehouse_id": i.warehouse_id, "warehouse_name": whs.get(i.warehouse_id, ""),
         "location_id": i.location_id, "color_batch_id": i.color_batch_id}
        for i in items
    ]
    return success(data)


@router.post("")
def create_arrival(data: ArrivalCreate, db: Session = Depends(get_db),
                   _=Depends(require_permissions("purchase:arrival:add"))):
    _, _, sups = load_maps(db)
    try:
        arr = build_arrival(db, data.order_id, data.items, data.remark)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(arr)
    return success(_row_dict(arr, sups), message="到货登记成功")


@router.post("/{aid}/approve")
def approve_arrival(aid: int, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user),
                    _=Depends(require_permissions("purchase:arrival:approve"))):
    arr = _get_arrival(db, aid)
    try:
        _do_approve(db, arr, user.username)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return success(message="验收成功，库存已更新")


@router.post("/{aid}/reject")
def reject_arrival(aid: int, reason: str = Body(..., embed=True), db: Session = Depends(get_db),
                   _=Depends(require_permissions("purchase:arrival:approve"))):
    arr = _get_arrival(db, aid)
    try:
        _do_reject(db, arr, reason)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return success(message="已驳回")
