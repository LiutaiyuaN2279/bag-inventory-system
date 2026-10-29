"""采购订单：列表 / 详情 / 新增 / 编辑 / 审核 / 驳回 / 作废 / 反作废 / 批量操作。
审核后可被到货单引用；到货与入库数量回写，状态自动联动（部分到货/已完成）。
作废时回滚明细占用的请购已订数量，反作废时按同一口径重新累加。"""
from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.api._batch import run_batch_guarded
from app.api._helpers import load_maps, material_meta
from app.api.deps import get_current_user, require_permissions
from app.core.database import get_db
from app.core.exceptions import BizException
from app.crud.crud_base import apply_ordering
from app.models.master_data import Material, Supplier
from app.models.procurement import (
    PurchaseArrival, PurchaseOrder, PurchaseOrderItem, PurchaseRequisitionItem,
)
from app.models.rbac import User
from app.schemas.batch import BatchIn
from app.schemas.procurement import OrderCreate, OrderUpdate
from app.utils.numbering import gen_no
from app.utils.response import page_result, success

router = APIRouter(prefix="/purchase-orders", tags=["采购-采购订单"])


def _row_dict(r, sups):
    return {
        "id": r.id, "order_no": r.order_no, "supplier_id": r.supplier_id,
        "supplier_name": sups.get(r.supplier_id, ""), "pr_id": r.pr_id,
        "status": r.status, "reject_reason": r.reject_reason, "total_amount": r.total_amount, "remark": r.remark,
        "created_at": str(r.created_at)[:19],
    }


def _round_qty(qty):
    """数量/金额精度统一：转 float 并保留 2 位小数，避免浮点尾差。"""
    return round(float(qty or 0), 2)


def _add_ordered(db, pr_item_id, qty):
    """累加请购明细的已订数量（明细未关联请购行时跳过）。"""
    if not pr_item_id:
        return
    pr_item = db.get(PurchaseRequisitionItem, pr_item_id)
    if pr_item:
        pr_item.ordered_qty = _round_qty((pr_item.ordered_qty or 0) + qty)


def _rollback_ordered(db, order_item):
    """回滚单条采购明细占用的请购已订数量，max(0,...) 兜底防止出现负数。"""
    if not order_item.pr_item_id:
        return
    pr_item = db.get(PurchaseRequisitionItem, order_item.pr_item_id)
    if pr_item:
        pr_item.ordered_qty = max(0.0, _round_qty((pr_item.ordered_qty or 0) - (order_item.qty or 0)))


def _prepare_items(raw_items, db, pr_id=None):
    """校验并归一化采购明细，返回 [{pr_item_id, material_id, qty, unit_price, unit}]。
    全部校验通过后才返回，调用方可据此安全地重建明细。"""
    rows = []
    for idx, it in enumerate(raw_items or [], start=1):
        material_id = it.get("material_id")
        if not material_id:
            raise BizException(f"第 {idx} 行缺少料号，请选择物料")
        material = db.get(Material, material_id)
        if not material:
            raise BizException(f"第 {idx} 行物料不存在（料号 {material_id}）")
        try:
            qty = _round_qty(it.get("qty", 0))
            price = _round_qty(it.get("unit_price", 0))
        except (TypeError, ValueError):
            raise BizException(f"第 {idx} 行数量/单价格式不正确")
        if qty <= 0:
            raise BizException(f"第 {idx} 行数量必须大于 0")
        if price < 0:
            raise BizException(f"第 {idx} 行单价不能为负数")
        pr_item_id = it.get("pr_item_id") or None
        if pr_item_id:
            pr_item = db.get(PurchaseRequisitionItem, pr_item_id)
            if not pr_item:
                raise BizException(f"第 {idx} 行关联的请购明细不存在")
            if pr_item.material_id != material_id:
                raise BizException(f"第 {idx} 行物料与关联的请购明细不一致")
            if pr_id and pr_item.pr_id != pr_id:
                raise BizException(f"第 {idx} 行关联的请购明细不属于当前来源请购单")
        rows.append({
            "pr_item_id": pr_item_id, "material_id": material_id, "qty": qty,
            "unit_price": price, "unit": it.get("unit") or material.unit or "个",
        })
    if not rows:
        raise BizException("请添加采购明细")
    return rows


def refresh_order_status(db, order_id):
    """根据明细到货/入库进度回写订单状态（含到货被驳回后的状态回退）。"""
    order = db.get(PurchaseOrder, order_id)
    if not order or order.status in ("已作废",):
        return
    items = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.order_id == order_id).all()
    if not items:
        return
    total = sum(i.qty or 0 for i in items)
    inbound = sum(i.inbound_qty or 0 for i in items)
    arrived = sum(i.arrived_qty or 0 for i in items)
    if total > 0 and inbound >= total:
        order.status = "已完成"
    elif arrived > 0 or inbound > 0:
        if order.status in ("已审核", "部分到货"):
            order.status = "部分到货"
    elif order.status == "部分到货":
        # 到货单被驳回后累计到货已回滚为 0，订单状态退回已审核
        order.status = "已审核"


@router.get("")
def list_orders(page: int = 1, page_size: int = 20, keyword: str | None = None,
                status: str | None = None, sort_by: str | None = None,
                sort_order: str | None = None, db: Session = Depends(get_db),
                _=Depends(require_permissions("purchase:order:list"))):
    q = db.query(PurchaseOrder)
    if keyword:
        q = q.filter(PurchaseOrder.order_no.like(f"%{keyword}%"))
    if status:
        q = q.filter(PurchaseOrder.status == status)
    total = q.count()
    rows = apply_ordering(q, PurchaseOrder, sort_by, sort_order).offset((page - 1) * page_size).limit(page_size).all()
    _, _, sups = load_maps(db)
    return success(page_result([_row_dict(r, sups) for r in rows], total))


@router.get("/{oid}")
def detail_order(oid: int, db: Session = Depends(get_db), _=Depends(require_permissions("purchase:order:list"))):
    order = db.get(PurchaseOrder, oid)
    if not order:
        raise BizException("采购订单不存在")
    mats, _, sups = load_maps(db)
    meta = material_meta(db)
    items = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.order_id == oid).all()
    data = _row_dict(order, sups)
    data["items"] = [
        {"id": i.id, "material_id": i.material_id, "material_name": mats.get(i.material_id, ""),
         "spec": meta.get(i.material_id, {}).get("spec", ""),
         "qty": i.qty, "unit_price": i.unit_price, "arrived_qty": i.arrived_qty,
         "inbound_qty": i.inbound_qty, "unit": i.unit or meta.get(i.material_id, {}).get("unit", "")}
        for i in items
    ]
    return success(data)


@router.post("")
def create_order(data: OrderCreate, db: Session = Depends(get_db), _=Depends(require_permissions("purchase:order:add"))):
    supplier = db.get(Supplier, data.supplier_id)
    if not supplier:
        raise BizException("供应商不存在")
    rows = _prepare_items(data.items, db, data.pr_id)
    order = PurchaseOrder(order_no=gen_no("PO"), supplier_id=data.supplier_id,
                          pr_id=data.pr_id, remark=data.remark, status="草稿")
    db.add(order); db.flush()
    try:
        total = 0.0
        for r in rows:
            db.add(PurchaseOrderItem(order_id=order.id, pr_item_id=r["pr_item_id"],
                                     material_id=r["material_id"], qty=r["qty"],
                                     unit_price=r["unit_price"], unit=r["unit"]))
            total += r["qty"] * r["unit_price"]
            # 回写请购单已订数量
            _add_ordered(db, r["pr_item_id"], r["qty"])
        order.total_amount = _round_qty(total)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(order)
    return success(_row_dict(order, {supplier.id: supplier.supplier_name}), message="新增成功")


@router.put("/{oid}")
def update_order(oid: int, data: OrderUpdate, db: Session = Depends(get_db), _=Depends(require_permissions("purchase:order:edit"))):
    order = db.get(PurchaseOrder, oid)
    if not order:
        raise BizException("采购订单不存在")
    if order.status != "草稿":
        raise BizException("仅草稿状态可编辑")
    if data.supplier_id is not None and data.supplier_id != order.supplier_id:
        if not db.get(Supplier, data.supplier_id):
            raise BizException("供应商不存在")
        order.supplier_id = data.supplier_id
    if data.remark is not None:
        order.remark = data.remark
    if data.items is None:
        db.commit()
        return success(message="修改成功")
    old_items = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.order_id == oid).all()
    # 前端编辑时不回传 pr_item_id：按物料沿用旧明细的请购关联，避免回滚后无法重新累加
    fallback = {}
    for oi in old_items:
        if oi.pr_item_id:
            fallback.setdefault(oi.material_id, []).append(oi.pr_item_id)
    raw_items = []
    for it in data.items:
        it = dict(it)
        if not it.get("pr_item_id"):
            pool = fallback.get(it.get("material_id")) or []
            if pool:
                it["pr_item_id"] = pool.pop(0)
        raw_items.append(it)
    rows = _prepare_items(raw_items, db, order.pr_id)   # 先全校验，通过后才动数据
    try:
        # 1) 回滚旧明细占用的请购已订数量
        for oi in old_items:
            _rollback_ordered(db, oi)
        # 2) 删除并按新明细重建（保留 pr_item_id 关联）
        db.query(PurchaseOrderItem).filter(PurchaseOrderItem.order_id == oid).delete()
        total = 0.0
        for r in rows:
            db.add(PurchaseOrderItem(order_id=oid, pr_item_id=r["pr_item_id"],
                                     material_id=r["material_id"], qty=r["qty"],
                                     unit_price=r["unit_price"], unit=r["unit"]))
            total += r["qty"] * r["unit_price"]
            # 3) 按新明细重新累加请购已订数量
            _add_ordered(db, r["pr_item_id"], r["qty"])
        order.total_amount = _round_qty(total)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return success(message="修改成功")


def _load_order(db: Session, oid: int) -> PurchaseOrder:
    """取采购订单，不存在则报错。单条端点与批量 handler 共用，保证校验口径一致。"""
    order = db.get(PurchaseOrder, oid)
    if not order:
        raise BizException("采购订单不存在")
    return order


# ---------------- 单条业务逻辑（单条端点与批量 handler 复用同一份实现） ----------------
def _do_approve_order(db: Session, order: PurchaseOrder) -> None:
    """审核：仅草稿可审核 → 置为已审核。不 commit，由调用方决定事务边界。"""
    if order.status != "草稿":
        raise BizException("仅草稿可审核")
    order.status = "已审核"


def _do_reject_order(db: Session, order: PurchaseOrder, reason: str | None) -> None:
    """驳回：仅草稿可驳回 → 记录截断到 255 的驳回原因 → 置为已驳回。不 commit。"""
    if order.status != "草稿":
        raise BizException("仅草稿可驳回")
    if not (reason or "").strip():
        raise BizException("请填写驳回原因")
    order.status = "已驳回"
    order.reject_reason = reason.strip()[:255]


def _do_void_order(db: Session, order: PurchaseOrder) -> None:
    """作废：校验到货单 → 回滚明细占用的请购已订数量 → 置为已作废。不 commit。

    与单条端点完全同一份逻辑：存在未驳回到货单时直接报错，
    回滚方向是「已在订单上的数量」逐条减去（_rollback_ordered）。
    """
    if order.status == "已作废":
        raise BizException("单据已作废")
    # 存在未驳回的到货单时不允许作废：需先驳回/删除到货单，释放已回写的到货数量
    arrival = db.query(PurchaseArrival).filter(
        PurchaseArrival.order_id == order.id, PurchaseArrival.status != "已驳回").first()
    if arrival:
        raise BizException(f"该订单已有到货单 {arrival.arrival_no}，请先驳回或删除到货单后再作废")
    items = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.order_id == order.id).all()
    # 回滚明细占用的请购已订数量
    for it in items:
        _rollback_ordered(db, it)
    order.status = "已作废"


def _do_unvoid_order(db: Session, order: PurchaseOrder) -> None:
    """反作废：单据回到草稿（需重新审核），并按同一口径重新累加请购已订数量。不 commit。

    与 _do_void_order 方向相反：逐条把订单明细数量重新累加回请购已订数量（_add_ordered）。
    """
    if order.status != "已作废":
        raise BizException("仅已作废单据可反作废")
    items = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.order_id == order.id).all()
    for it in items:
        _add_ordered(db, it.pr_item_id, it.qty)
    order.status = "草稿"
    order.reject_reason = ""


# ---------------- 批量操作 ----------------
# 注意：/batch 是固定路径，必须声明在任何 /{oid} 动态路由之前，否则 batch 会被当成 oid 匹配掉。
# 动作 → 所需权限：审核 / 驳回 / 作废 / 反作废同属采购订单审核权限，沿用既有权限码，不新增。
BATCH_PERMS = {
    "approve": "purchase:order:approve",
    "reject": "purchase:order:approve",
    "void": "purchase:order:approve",
    "unvoid": "purchase:order:approve",
}


def _one_order(db: Session, oid: int, action: str, reason: str | None) -> None:
    """单条批量动作：取对象 → 校验 → 改状态（不 commit，由 run_batch 统一提交）。"""
    order = _load_order(db, oid)
    if action == "approve":
        _do_approve_order(db, order)
    elif action == "reject":
        _do_reject_order(db, order, reason)
    elif action == "void":
        _do_void_order(db, order)
    elif action == "unvoid":
        _do_unvoid_order(db, order)
    else:
        raise BizException(f"不支持的批量动作：{action}")


@router.post("/batch")
def batch_orders(payload: BatchIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """批量审核/驳回/作废/反作废采购订单（逐条独立事务，返回失败明细）。"""
    reason = payload.reason

    def _one(db_: Session, oid: int, action: str) -> None:
        # 闭包捕获本请求的 reason，逐条复用与单条端点完全相同的业务逻辑
        _one_order(db_, oid, action, reason)

    return run_batch_guarded(db, user, payload, BATCH_PERMS, _one)


@router.post("/{oid}/approve")
def approve_order(oid: int, db: Session = Depends(get_db), _=Depends(require_permissions("purchase:order:approve"))):
    order = _load_order(db, oid)
    _do_approve_order(db, order)
    db.commit()
    return success(message="审核成功")


@router.post("/{oid}/reject")
def reject_order(oid: int, reason: str = Body(..., embed=True), db: Session = Depends(get_db),
                 _=Depends(require_permissions("purchase:order:approve"))):
    order = _load_order(db, oid)
    _do_reject_order(db, order, reason)
    db.commit()
    return success(message="已驳回")


@router.post("/{oid}/void")
def void_order(oid: int, db: Session = Depends(get_db), _=Depends(require_permissions("purchase:order:approve"))):
    order = _load_order(db, oid)
    try:
        _do_void_order(db, order)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return success(message="已作废")


@router.post("/{oid}/unvoid")
def unvoid_order(oid: int, db: Session = Depends(get_db), _=Depends(require_permissions("purchase:order:approve"))):
    """反作废：单据回到草稿（需重新审核），并按同一口径重新累加请购已订数量。"""
    order = _load_order(db, oid)
    try:
        _do_unvoid_order(db, order)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return success(message="已反作废，单据回到草稿状态")
