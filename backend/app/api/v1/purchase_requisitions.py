"""请购单：列表 / 详情 / 新增 / 编辑 / 审核 / 驳回 / 作废 / 批量操作。"""
from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.api._batch import run_batch_guarded
from app.api._helpers import load_maps, material_meta
from app.api.deps import get_current_user, require_permissions
from app.core.database import get_db
from app.core.exceptions import BizException
from app.core.visibility import scope_requisitions
from app.crud.crud_base import apply_ordering
from app.models.procurement import PurchaseRequisition, PurchaseRequisitionItem
from app.models.rbac import User
from app.schemas.batch import BatchIn
from app.schemas.procurement import RequisitionCreate, RequisitionUpdate
from app.utils.numbering import gen_no
from app.utils.response import page_result, success

router = APIRouter(prefix="/purchase-requisitions", tags=["采购-请购单"])


def _row_dict(r):
    return {
        "id": r.id, "req_no": r.req_no, "requisitioner": r.requisitioner, "dept": r.dept,
        "status": r.status, "reject_reason": r.reject_reason, "remark": r.remark, "created_at": str(r.created_at)[:19],
    }


@router.get("")
def list_pr(page: int = 1, page_size: int = 20, keyword: str | None = None,
            status: str | None = None, sort_by: str | None = None,
            sort_order: str | None = None, db: Session = Depends(get_db),
            user: User = Depends(require_permissions("purchase:requisition:list"))):
    q = db.query(PurchaseRequisition)
    # 数据视野：部门负责人/总监只看本部门，普通员工只看本人（采购等业务岗不受限）
    q = scope_requisitions(db, user, q)
    if keyword:
        q = q.filter(PurchaseRequisition.req_no.like(f"%{keyword}%"))
    if status:
        q = q.filter(PurchaseRequisition.status == status)
    total = q.count()
    rows = apply_ordering(q, PurchaseRequisition, sort_by, sort_order).offset((page - 1) * page_size).limit(page_size).all()
    return success(page_result([_row_dict(r) for r in rows], total))


@router.get("/{rid}")
def detail_pr(rid: int, db: Session = Depends(get_db),
              user: User = Depends(require_permissions("purchase:requisition:list"))):
    pr = db.get(PurchaseRequisition, rid)
    # 详情同样受视野约束：否则知道 id 就能绕过列表直接看别的部门/别人的单据
    if pr and scope_requisitions(db, user, db.query(PurchaseRequisition.id)
                                 .filter(PurchaseRequisition.id == rid)).first() is None:
        raise BizException("请购单不存在或无权查看")
    if not pr:
        raise BizException("请购单不存在")
    mats, _, _ = load_maps(db)
    meta = material_meta(db)
    items = db.query(PurchaseRequisitionItem).filter(PurchaseRequisitionItem.pr_id == rid).all()
    data = _row_dict(pr)
    data["items"] = [
        {"id": i.id, "material_id": i.material_id, "material_name": mats.get(i.material_id, ""),
         "spec": meta.get(i.material_id, {}).get("spec", ""),
         "qty": i.qty, "unit": i.unit or meta.get(i.material_id, {}).get("unit", ""),
         "ordered_qty": i.ordered_qty,
         "requirement_date": i.requirement_date, "remark": i.remark}
        for i in items
    ]
    return success(data)


@router.post("")
def create_pr(data: RequisitionCreate, db: Session = Depends(get_db), _=Depends(require_permissions("purchase:requisition:add"))):
    pr = PurchaseRequisition(req_no=gen_no("PR"), requisitioner=data.requisitioner,
                             dept=data.dept, remark=data.remark, status="草稿")
    db.add(pr); db.flush()
    for it in data.items:
        db.add(PurchaseRequisitionItem(pr_id=pr.id, material_id=it["material_id"], qty=it.get("qty", 0),
                                       unit=it.get("unit", "个"), requirement_date=it.get("requirement_date", ""),
                                       remark=it.get("remark", "")))
    db.commit(); db.refresh(pr)
    return success(_row_dict(pr), message="新增成功")


@router.put("/{rid}")
def update_pr(rid: int, data: RequisitionUpdate, db: Session = Depends(get_db), _=Depends(require_permissions("purchase:requisition:edit"))):
    pr = db.get(PurchaseRequisition, rid)
    if not pr:
        raise BizException("请购单不存在")
    if pr.status != "草稿":
        raise BizException("仅草稿状态可编辑")
    for k in ("requisitioner", "dept", "remark"):
        v = getattr(data, k)
        if v is not None:
            setattr(pr, k, v)
    if data.items is not None:
        db.query(PurchaseRequisitionItem).filter(PurchaseRequisitionItem.pr_id == rid).delete()
        for it in data.items:
            db.add(PurchaseRequisitionItem(pr_id=rid, material_id=it["material_id"], qty=it.get("qty", 0),
                                           unit=it.get("unit", "个"), requirement_date=it.get("requirement_date", ""),
                                           remark=it.get("remark", "")))
    db.commit()
    return success(message="修改成功")


# ---------------- 单条业务逻辑（单条端点与批量 handler 复用同一份实现） ----------------
def _load_pr(db: Session, rid: int) -> PurchaseRequisition:
    """取请购单，不存在则报错。单条端点与批量 handler 共用，保证校验口径一致。"""
    pr = db.get(PurchaseRequisition, rid)
    if not pr:
        raise BizException("请购单不存在")
    return pr


def _do_approve(db: Session, pr: PurchaseRequisition) -> None:
    """审核：仅草稿可审核 → 置为已审核。不 commit，由调用方决定事务边界。"""
    if pr.status != "草稿":
        raise BizException("仅草稿可审核")
    pr.status = "已审核"


def _do_reject(db: Session, pr: PurchaseRequisition, reason: str | None) -> None:
    """驳回：仅草稿可驳回 → 记录截断到 255 的驳回原因 → 置为已驳回。不 commit。"""
    if pr.status != "草稿":
        raise BizException("仅草稿可驳回")
    if not (reason or "").strip():
        raise BizException("请填写驳回原因")
    pr.status = "已驳回"
    pr.reject_reason = reason.strip()[:255]


def _do_void(db: Session, pr: PurchaseRequisition) -> None:
    """作废：已作废的不能再作废 → 置为已作废。不 commit。"""
    if pr.status == "已作废":
        raise BizException("单据已作废")
    pr.status = "已作废"


# ---------------- 批量操作 ----------------
# 注意：/batch 是固定路径，必须声明在任何 /{rid} 动态路由之前，否则 batch 会被当成 rid 匹配掉。
# 动作 → 所需权限：审核 / 驳回 / 作废同属请购单审核权限，沿用既有权限码，不新增。
BATCH_PERMS = {
    "approve": "purchase:requisition:approve",
    "reject": "purchase:requisition:approve",
    "void": "purchase:requisition:approve",
}


def _one_pr(db: Session, rid: int, action: str, reason: str | None) -> None:
    """单条批量动作：取对象 → 校验 → 改状态（不 commit，由 run_batch 统一提交）。"""
    pr = _load_pr(db, rid)
    if action == "approve":
        _do_approve(db, pr)
    elif action == "reject":
        _do_reject(db, pr, reason)
    elif action == "void":
        _do_void(db, pr)
    else:
        raise BizException(f"不支持的批量动作：{action}")


@router.post("/batch")
def batch_pr(payload: BatchIn, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    """批量审核/驳回/作废请购单（逐条独立事务，返回失败明细）。"""
    reason = payload.reason

    def _one(db_: Session, rid: int, action: str) -> None:
        # 闭包捕获本请求的 reason，逐条复用与单条端点完全相同的业务逻辑
        _one_pr(db_, rid, action, reason)

    return run_batch_guarded(db, user, payload, BATCH_PERMS, _one)


@router.post("/{rid}/approve")
def approve_pr(rid: int, db: Session = Depends(get_db), _=Depends(require_permissions("purchase:requisition:approve"))):
    pr = _load_pr(db, rid)
    _do_approve(db, pr)
    db.commit()
    return success(message="审核成功")


@router.post("/{rid}/reject")
def reject_pr(rid: int, reason: str = Body(..., embed=True), db: Session = Depends(get_db),
              _=Depends(require_permissions("purchase:requisition:approve"))):
    pr = _load_pr(db, rid)
    _do_reject(db, pr, reason)
    db.commit()
    return success(message="已驳回")


@router.post("/{rid}/void")
def void_pr(rid: int, db: Session = Depends(get_db), _=Depends(require_permissions("purchase:requisition:approve"))):
    pr = _load_pr(db, rid)
    _do_void(db, pr)
    db.commit()
    return success(message="已作废")
