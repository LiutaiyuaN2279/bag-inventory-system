"""采购退货：创建 → 审核（触发出库，库存实时扣减）。"""
from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.api._batch import run_batch_guarded
from app.api._helpers import load_maps, material_meta
from app.api.deps import get_current_user, require_permissions
from app.core.database import get_db
from app.core.exceptions import BizException
from app.models.procurement import PurchaseReturn, PurchaseReturnItem
from app.models.rbac import User
from app.crud.crud_base import apply_ordering
from app.schemas.batch import BatchIn
from app.schemas.procurement import ReturnCreate
from app.services.stock_service import post_outbound
from app.utils.numbering import gen_no
from app.utils.response import page_result, success

router = APIRouter(prefix="/purchase-returns", tags=["采购-退货"])


def _round_qty(qty):
    """数量精度统一：转 float 并保留 2 位小数，避免浮点尾差。"""
    return round(float(qty or 0), 2)


def _row_dict(r, sups):
    return {
        "id": r.id, "return_no": r.return_no, "order_id": r.order_id,
        "supplier_id": r.supplier_id, "supplier_name": sups.get(r.supplier_id, ""),
        "status": r.status, "reject_reason": r.reject_reason, "remark": r.remark, "created_at": str(r.created_at)[:19],
    }


def _get_return(db: Session, rid: int) -> PurchaseReturn:
    ret = db.get(PurchaseReturn, rid)
    if not ret:
        raise BizException("退货单不存在")
    return ret


def _do_approve(db: Session, ret: PurchaseReturn, operator: str) -> None:
    """审核核心逻辑：逐明细采购退货出库 + 置已审核（不 commit）。"""
    if ret.status != "草稿":
        raise BizException("仅草稿可审核")
    items = db.query(PurchaseReturnItem).filter(PurchaseReturnItem.return_id == ret.id).all()
    if not items:
        raise BizException("退货单没有明细，无法审核")
    # 审核前强校验：数量 <= 0 的明细不能被静默跳过，否则会出现“审核通过但没有任何退货出库”的单据
    invalid = [it for it in items if _round_qty(it.qty) <= 0]
    if invalid:
        raise BizException(f"退货数量必须大于 0（有 {len(invalid)} 行数量不合法），请先修改退货明细")
    for it in items:
        post_outbound(db, material_id=it.material_id, warehouse_id=it.warehouse_id,
                      location_id=it.location_id, color_batch_id=it.color_batch_id,
                      qty=it.qty, txn_type="采购退货出库", ref_type="采购退货",
                      ref_id=ret.id, operator=operator)
    ret.status = "已审核"


def _do_reject(db: Session, ret: PurchaseReturn, reason: str) -> None:
    """驳回核心逻辑：置已驳回并记录原因（不 commit）。"""
    if ret.status != "草稿":
        raise BizException("仅草稿可驳回")
    if not (reason or "").strip():
        raise BizException("请填写驳回原因")
    ret.status = "已驳回"
    ret.reject_reason = reason.strip()[:255]


# ---------------- 批量操作 ----------------
# 必须声明在任何 /{xxx} 形式的动态路由之前，否则 batch 会被当作 id 匹配掉（int 转换失败报 422）
BATCH_PERMS = {
    "approve": "purchase:return:approve",
    "reject": "purchase:return:approve",
}


@router.post("/batch")
def batch_returns(payload: BatchIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """批量审核/驳回采购退货单（逐条独立事务，返回失败明细）。"""
    reason = (payload.reason or "").strip()
    operator = user.username

    def _one(db: Session, item_id: int, action: str) -> None:
        ret = _get_return(db, item_id)
        if action == "approve":
            _do_approve(db, ret, operator)
        elif action == "reject":
            _do_reject(db, ret, reason)
        else:
            raise BizException(f"不支持的批量动作：{action}")

    return run_batch_guarded(db, user, payload, BATCH_PERMS, _one)


@router.get("")
def list_returns(page: int = 1, page_size: int = 20, keyword: str | None = None,
                 status: str | None = None, sort_by: str | None = None,
                 sort_order: str | None = None, db: Session = Depends(get_db),
                 _=Depends(require_permissions("purchase:return:list"))):
    q = db.query(PurchaseReturn)
    if keyword:
        q = q.filter(PurchaseReturn.return_no.like(f"%{keyword}%"))
    if status:
        q = q.filter(PurchaseReturn.status == status)
    total = q.count()
    rows = apply_ordering(q, PurchaseReturn, sort_by, sort_order).offset((page - 1) * page_size).limit(page_size).all()
    _, _, sups = load_maps(db)
    return success(page_result([_row_dict(r, sups) for r in rows], total))


@router.get("/{rid}")
def detail_return(rid: int, db: Session = Depends(get_db), _=Depends(require_permissions("purchase:return:list"))):
    ret = db.get(PurchaseReturn, rid)
    if not ret:
        raise BizException("退货单不存在")
    mats, whs, sups = load_maps(db)
    meta = material_meta(db)
    items = db.query(PurchaseReturnItem).filter(PurchaseReturnItem.return_id == rid).all()
    data = _row_dict(ret, sups)
    data["items"] = [
        {"id": i.id, "material_id": i.material_id, "material_name": mats.get(i.material_id, ""),
         "spec": meta.get(i.material_id, {}).get("spec", ""),
         "qty": i.qty, "unit": meta.get(i.material_id, {}).get("unit", ""),
         "warehouse_id": i.warehouse_id, "warehouse_name": whs.get(i.warehouse_id, ""),
         "location_id": i.location_id, "color_batch_id": i.color_batch_id, "remark": i.remark}
        for i in items
    ]
    return success(data)


@router.post("")
def create_return(data: ReturnCreate, db: Session = Depends(get_db), _=Depends(require_permissions("purchase:return:add"))):
    if not data.items:
        raise BizException("请添加退货明细")
    rows = []
    for idx, it in enumerate(data.items, start=1):
        if not it.get("material_id"):
            raise BizException(f"第 {idx} 行缺少料号，请选择物料")
        if not it.get("warehouse_id"):
            raise BizException(f"第 {idx} 行请选择退货出库仓库")
        try:
            qty = _round_qty(it.get("qty", 0))
        except (TypeError, ValueError):
            raise BizException(f"第 {idx} 行退货数量格式不正确")
        if qty <= 0:
            raise BizException(f"第 {idx} 行退货数量必须大于 0")
        rows.append({"material_id": it["material_id"], "qty": qty,
                     "warehouse_id": it["warehouse_id"], "location_id": it.get("location_id"),
                     "color_batch_id": it.get("color_batch_id"), "remark": it.get("remark", "")})
    ret = PurchaseReturn(return_no=gen_no("RT"), supplier_id=data.supplier_id,
                         order_id=data.order_id, remark=data.remark, status="草稿")
    db.add(ret); db.flush()
    for r in rows:
        db.add(PurchaseReturnItem(return_id=ret.id, **r))
    db.commit(); db.refresh(ret)
    _, _, sups = load_maps(db)
    return success(_row_dict(ret, sups), message="新增成功")


@router.post("/{rid}/approve")
def approve_return(rid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                   _=Depends(require_permissions("purchase:return:approve"))):
    ret = _get_return(db, rid)
    try:
        _do_approve(db, ret, user.username)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return success(message="审核成功，库存已扣减")


@router.post("/{rid}/reject")
def reject_return(rid: int, reason: str = Body(..., embed=True), db: Session = Depends(get_db),
                  _=Depends(require_permissions("purchase:return:approve"))):
    ret = _get_return(db, rid)
    try:
        _do_reject(db, ret, reason)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return success(message="已驳回")
