"""外发加工：发外加工单 —— 发料出库、收回入库，库存实时联动。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api._batch import run_batch_guarded
from app.api._helpers import load_maps
from app.api.deps import get_current_user, require_permissions
from app.core.database import get_db
from app.core.exceptions import BizException
from app.models.outsource import OutsourceOrder, OutsourceOrderItem
from app.models.rbac import User
from app.crud.crud_base import apply_ordering
from app.schemas.batch import BatchIn
from app.services.stock_service import post_inbound, post_outbound
from app.utils.numbering import gen_no
from app.utils.response import page_result, success

router = APIRouter(prefix="/outsource-orders", tags=["外发加工"])


def _row(r, mats, sups, whs):
    return {"id": r.id, "order_no": r.order_no,
            "supplier_id": r.supplier_id, "supplier_name": sups.get(r.supplier_id, ""),
            "product_id": r.product_id, "product_name": mats.get(r.product_id, ""),
            "out_warehouse_name": whs.get(r.out_warehouse_id, ""),
            "in_warehouse_name": whs.get(r.in_warehouse_id, ""),
            "plan_qty": r.plan_qty, "received_qty": r.received_qty, "status": r.status,
            "remark": r.remark, "created_at": str(r.created_at)[:19]}


def _do_issue(db: Session, oid: int, operator: str) -> None:
    """发料业务核心：校验状态 → 按明细出库 → 回写已发数量并流转状态。

    不 commit，由调用方（单条端点 / 批量执行器）统一提交，保证单据级原子性。
    """
    o = db.get(OutsourceOrder, oid)
    if not o or o.status != "草稿":
        raise BizException("仅草稿单据可发料")
    items = db.query(OutsourceOrderItem).filter(OutsourceOrderItem.order_id == oid).all()
    if not items:
        raise BizException("没有发料明细")
    for it in items:
        if it.qty > 0:
            post_outbound(db, material_id=it.material_id, warehouse_id=o.out_warehouse_id,
                          qty=it.qty, txn_type="外发发料出库", ref_type="外发加工",
                          ref_id=o.id, operator=operator)
            it.issued_qty = it.qty
    o.status = "已发料"


def _do_receive(db: Session, oid: int, qty: float, operator: str) -> None:
    """收回业务核心：校验状态与数量 → 成品入库 → 累加已收数量并流转状态。

    不 commit，由调用方统一提交。
    """
    o = db.get(OutsourceOrder, oid)
    if not o or o.status not in ("已发料", "部分收回"):
        raise BizException("仅已发料单据可收回")
    if qty <= 0:
        raise BizException("收回数量必须大于 0")
    post_inbound(db, material_id=o.product_id, warehouse_id=o.in_warehouse_id,
                 qty=qty, txn_type="外发收回入库", ref_type="外发加工",
                 ref_id=o.id, operator=operator)
    o.received_qty = (o.received_qty or 0) + qty
    o.status = "已完成" if (o.plan_qty and o.received_qty >= o.plan_qty) else "部分收回"


# ---------------- 批量操作 ----------------
# 动作 → 所需权限：发料/收回都是编辑类操作，沿用模块内既有的 outsource:edit
BATCH_PERMS = {
    "issue": "outsource:edit",
    "receive": "outsource:edit",
}


def _make_one_os(user: User):
    """构造批量 handler：闭包捕获当前用户，用于库存流水 operator。

    receive 是「按数量收回」，批量场景下没有逐单数量输入，约定按该单
    尚未收回的差额（plan_qty - received_qty）整单收回；plan_qty 为 0 或已收满时无差额可收，该单失败。
    """

    def _one_os(db: Session, item_id: int, action: str) -> None:
        if action == "issue":
            _do_issue(db, item_id, user.username)
            return
        # action == "receive"（其余动作由 run_batch_guarded 提前拦截）
        o = db.get(OutsourceOrder, item_id)
        if not o:
            raise BizException("加工单不存在")
        qty = float(o.plan_qty or 0) - float(o.received_qty or 0)
        if qty <= 0:
            raise BizException("该单据没有待收回数量（计划数量已收满或计划数量为 0）")
        _do_receive(db, item_id, qty, user.username)

    return _one_os


# 注意：必须声明在任何 /{oid} 动态路由之前，否则 batch 会被当成 oid 匹配
@router.post("/batch")
def batch_os(payload: BatchIn, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    """批量发料/收回外发加工单（逐条独立事务，返回失败明细）。"""
    return run_batch_guarded(db, user, payload, BATCH_PERMS, _make_one_os(user))


@router.get("")
def list_os(page: int = 1, page_size: int = 20, keyword: str | None = None,
            status: str | None = None, sort_by: str | None = None,
            sort_order: str | None = None, db: Session = Depends(get_db),
            _=Depends(require_permissions("outsource:list"))):
    q = db.query(OutsourceOrder)
    if keyword:
        q = q.filter(OutsourceOrder.order_no.like(f"%{keyword}%"))
    if status:
        vals = [s for s in status.split(',') if s]
        # 聚合状态「在途」= 已发料 + 部分收回（即需要收发料的在制加工单）
        if vals == ['在途']:
            vals = ['已发料', '部分收回']
        if len(vals) > 1:
            q = q.filter(OutsourceOrder.status.in_(vals))
        else:
            q = q.filter(OutsourceOrder.status == vals[0])
    total = q.count()
    rows = apply_ordering(q, OutsourceOrder, sort_by, sort_order).offset((page - 1) * page_size).limit(page_size).all()
    mats, whs, sups = load_maps(db)
    return success(page_result([_row(r, mats, sups, whs) for r in rows], total))


@router.get("/{oid}")
def detail_os(oid: int, db: Session = Depends(get_db), _=Depends(require_permissions("outsource:list"))):
    o = db.get(OutsourceOrder, oid)
    if not o:
        raise BizException("加工单不存在")
    mats, whs, sups = load_maps(db)
    items = db.query(OutsourceOrderItem).filter(OutsourceOrderItem.order_id == oid).all()
    data = _row(o, mats, sups, whs)
    data["items"] = [{"id": i.id, "material_id": i.material_id, "material_name": mats.get(i.material_id, ""),
                      "qty": i.qty, "issued_qty": i.issued_qty, "unit": i.unit} for i in items]
    return success(data)


@router.post("")
def create_os(payload: dict, db: Session = Depends(get_db), _=Depends(require_permissions("outsource:edit"))):
    o = OutsourceOrder(order_no=gen_no("OS"), supplier_id=payload["supplier_id"], product_id=payload["product_id"],
                       out_warehouse_id=payload["out_warehouse_id"], in_warehouse_id=payload["in_warehouse_id"],
                       plan_qty=payload.get("plan_qty", 0), remark=payload.get("remark", ""), status="草稿")
    db.add(o); db.flush()
    for it in payload.get("items", []):
        db.add(OutsourceOrderItem(order_id=o.id, material_id=it["material_id"], qty=it.get("qty", 0), unit=it.get("unit", "个")))
    db.commit(); db.refresh(o)
    mats, whs, sups = load_maps(db)
    return success(_row(o, mats, sups, whs), message="新增成功")


@router.put("/{oid}")
def update_os(oid: int, payload: dict, db: Session = Depends(get_db), _=Depends(require_permissions("outsource:edit"))):
    o = db.get(OutsourceOrder, oid)
    if not o or o.status != "草稿":
        raise BizException("仅草稿可编辑")
    for k in ("supplier_id", "product_id", "out_warehouse_id", "in_warehouse_id", "plan_qty", "remark"):
        if k in payload:
            setattr(o, k, payload[k])
    if "items" in payload:
        db.query(OutsourceOrderItem).filter(OutsourceOrderItem.order_id == oid).delete()
        for it in payload["items"]:
            db.add(OutsourceOrderItem(order_id=oid, material_id=it["material_id"], qty=it.get("qty", 0), unit=it.get("unit", "个")))
    db.commit()
    return success(message="修改成功")


@router.post("/{oid}/issue")
def issue_os(oid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user),
             _=Depends(require_permissions("outsource:edit"))):
    """发料：按明细发出原料，库存出库。"""
    try:
        _do_issue(db, oid, user.username)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return success(message="发料成功，库存已扣减")


@router.post("/{oid}/receive")
def receive_os(oid: int, payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user),
               _=Depends(require_permissions("outsource:edit"))):
    """收回：成品/半成品入库。"""
    try:
        _do_receive(db, oid, float(payload.get("qty", 0)), user.username)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return success(message="收回成功，库存已增加")
