"""库存盘点：建单(快照账面) → 录入实盘 → 审核(盘盈入库/盘亏出库)。"""
from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.api._batch import run_batch_guarded
from app.api._helpers import load_maps
from app.api.deps import get_current_user, require_permissions
from app.core.database import get_db
from app.core.exceptions import BizException
from app.models.inventory import Inventory, Stocktake, StocktakeItem
from app.models.rbac import User
from app.crud.crud_base import apply_ordering
from app.schemas.batch import BatchIn
from app.services.stock_service import post_inbound, post_outbound
from app.utils.numbering import gen_no
from app.utils.response import page_result, success

router = APIRouter(prefix="/stocktakes", tags=["库存-盘点"])


def _row_dict(r, whs):
    return {"id": r.id, "stocktake_no": r.stocktake_no, "warehouse_id": r.warehouse_id,
            "warehouse_name": whs.get(r.warehouse_id, ""), "status": r.status,
            "reject_reason": r.reject_reason, "remark": r.remark, "created_at": str(r.created_at)[:19]}


def _do_approve(db: Session, sid: int, operator: str) -> None:
    """审核核心逻辑：逐明细盘盈入库/盘亏出库 + 置已完成。

    保持原单条端点的语义——**一张盘点单是最小事务单位**，所有明细共用一个事务，
    由调用方（单条端点 / run_batch 的逐条事务）统一 commit 或 rollback（本函数不 commit）。
    """
    st = db.get(Stocktake, sid)
    if not st or st.status != "盘点中":
        raise BizException("仅盘点中单据可审核")
    items = db.query(StocktakeItem).filter(StocktakeItem.stocktake_id == sid).all()
    for it in items:
        diff = (it.counted_qty or 0) - (it.book_qty or 0)
        if diff > 0:
            post_inbound(db, material_id=it.material_id, warehouse_id=st.warehouse_id,
                         location_id=it.location_id, color_batch_id=it.color_batch_id,
                         qty=diff, txn_type="盘盈入库", ref_type="库存盘点",
                         ref_id=st.id, operator=operator)
        elif diff < 0:
            post_outbound(db, material_id=it.material_id, warehouse_id=st.warehouse_id,
                          location_id=it.location_id, color_batch_id=it.color_batch_id,
                          qty=-diff, txn_type="盘亏出库", ref_type="库存盘点",
                          ref_id=st.id, operator=operator)
    st.status = "已完成"


def _do_reject(db: Session, sid: int, reason: str) -> None:
    """驳回核心逻辑：要求盘点中且原因非空，置已驳回并记录原因（不 commit）。"""
    st = db.get(Stocktake, sid)
    if not st or st.status != "盘点中":
        raise BizException("仅盘点中单据可驳回")
    if not (reason or "").strip():
        raise BizException("请填写驳回原因")
    st.status = "已驳回"
    st.reject_reason = reason.strip()[:255]


# ---------------- 批量操作 ----------------
# 必须声明在任何 /{xxx} 形式的动态路由之前，否则 batch 会被当作 id 匹配掉（int 转换失败报 422）
BATCH_PERMS = {
    "approve": "inventory:stocktake",
    "reject": "inventory:stocktake",
}


@router.post("/batch")
def batch_stocktakes(payload: BatchIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """批量审核/驳回盘点单（逐条独立事务，一条盘点单为最小事务单位）。"""
    reason = (payload.reason or "").strip()
    operator = user.username

    def _one(db: Session, item_id: int, action: str) -> None:
        if action == "approve":
            _do_approve(db, item_id, operator)
        elif action == "reject":
            _do_reject(db, item_id, reason)
        else:
            raise BizException(f"不支持的批量动作：{action}")

    return run_batch_guarded(db, user, payload, BATCH_PERMS, _one)


@router.get("")
def list_st(page: int = 1, page_size: int = 20, status: str | None = None,
            sort_by: str | None = None, sort_order: str | None = None,
            db: Session = Depends(get_db), _=Depends(require_permissions("inventory:stocktake"))):
    _, whs, _ = load_maps(db)
    q = db.query(Stocktake)
    if status:
        q = q.filter(Stocktake.status == status)
    total = q.count()
    rows = apply_ordering(q, Stocktake, sort_by, sort_order).offset((page - 1) * page_size).limit(page_size).all()
    return success(page_result([_row_dict(r, whs) for r in rows], total))


@router.get("/{sid}")
def detail_st(sid: int, db: Session = Depends(get_db), _=Depends(require_permissions("inventory:stocktake"))):
    st = db.get(Stocktake, sid)
    if not st:
        raise BizException("盘点单不存在")
    mats, whs, _ = load_maps(db)
    items = db.query(StocktakeItem).filter(StocktakeItem.stocktake_id == sid).all()
    data = _row_dict(st, whs)
    data["items"] = [
        {"id": i.id, "material_id": i.material_id, "material_name": mats.get(i.material_id, ""),
         "color_batch_id": i.color_batch_id, "location_id": i.location_id,
         "book_qty": i.book_qty, "counted_qty": i.counted_qty,
         "diff_qty": (i.counted_qty or 0) - (i.book_qty or 0)}
        for i in items
    ]
    return success(data)


@router.post("")
def create_st(payload: dict, db: Session = Depends(get_db), _=Depends(require_permissions("inventory:stocktake"))):
    warehouse_id = payload.get("warehouse_id")
    if not warehouse_id:
        raise BizException("请选择仓库")
    st = Stocktake(stocktake_no=gen_no("PD"), warehouse_id=warehouse_id,
                   remark=payload.get("remark", ""), status="盘点中")
    db.add(st); db.flush()
    # 快照当前库存账面
    invs = db.query(Inventory).filter(Inventory.warehouse_id == warehouse_id).all()
    for inv in invs:
        db.add(StocktakeItem(stocktake_id=st.id, material_id=inv.material_id,
                             color_batch_id=inv.color_batch_id, location_id=inv.location_id,
                             book_qty=inv.qty, counted_qty=inv.qty))
    db.commit(); db.refresh(st)
    return success(_row_dict(st, {}), message="盘点单已创建")


@router.post("/{sid}/count")
def count_st(sid: int, payload: dict, db: Session = Depends(get_db),
             _=Depends(require_permissions("inventory:stocktake"))):
    st = db.get(Stocktake, sid)
    if not st or st.status == "已完成":
        raise BizException("盘点单不可录入")
    for it in payload.get("items", []):
        item = db.get(StocktakeItem, it["id"])
        if item and item.stocktake_id == sid:
            item.counted_qty = it.get("counted_qty", item.book_qty)
    db.commit()
    return success(message="实盘数据已保存")


@router.post("/{sid}/approve")
def approve_st(sid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user),
               _=Depends(require_permissions("inventory:stocktake"))):
    try:
        _do_approve(db, sid, user.username)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return success(message="盘点完成，差异已调整库存")


@router.post("/{sid}/reject")
def reject_st(sid: int, reason: str = Body(..., embed=True), db: Session = Depends(get_db),
              _=Depends(require_permissions("inventory:stocktake"))):
    try:
        _do_reject(db, sid, reason)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return success(message="已驳回")
