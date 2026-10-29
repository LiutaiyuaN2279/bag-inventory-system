"""质检：来料质检(IQC) + 成品质检(FQC)。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api._batch import run_batch_guarded
from app.api._helpers import load_maps
from app.api.deps import get_current_user, require_permissions
from app.core.database import get_db
from app.core.exceptions import BizException
from app.crud.crud_base import apply_ordering
from app.models.quality import FqcOrder, IqcItem, IqcOrder
from app.models.rbac import User
from app.schemas.batch import BatchIn
from app.utils.numbering import gen_no
from app.utils.response import page_result, success

router = APIRouter(tags=["质量管理"])

# 质检单已判定的状态集合：批量判定时不再重复改判，避免覆盖人工录入的明细结果
IQC_DONE = ("合格", "让步接收", "不合格")


def _apply_iqc_items(db: Session, o: IqcOrder, items) -> None:
    """按 items=[{id, result, qualified_qty}] 写入明细结果并汇总整单状态（不 commit）。
    单条录入检验结果端点与批量 approve 共用。"""
    results = []
    for it in items or []:
        item = db.get(IqcItem, it["id"])
        if item and item.iqc_id == o.id:
            item.result = it.get("result", "合格")
            item.qualified_qty = it.get("qualified_qty", item.qualified_qty)
            results.append(item.result)
    if results:
        o.status = "合格" if all(r == "合格" for r in results) else ("让步接收" if "让步接收" in results else "不合格")


def _apply_fqc_fields(db: Session, o: FqcOrder, payload: dict) -> None:
    """按字段覆盖成品质检单（不 commit）。单条 PUT 端点与批量 approve/reject 共用。"""
    for k in ("check_qty", "qualified_qty", "status", "inspector", "remark"):
        if k in payload:
            setattr(o, k, payload[k])


# ---------------- IQC 来料质检 ----------------
@router.get("/iqc")
def list_iqc(page: int = 1, page_size: int = 20, status: str | None = None,
             sort_by: str | None = None, sort_order: str | None = None,
             db: Session = Depends(get_db), _=Depends(require_permissions("qc:view"))):
    q = db.query(IqcOrder)
    if status:
        q = q.filter(IqcOrder.status == status)
    total = q.count()
    rows = apply_ordering(q, IqcOrder, sort_by, sort_order).offset((page - 1) * page_size).limit(page_size).all()
    _, _, sups = load_maps(db)
    return success(page_result([{"id": r.id, "qc_no": r.qc_no, "supplier_name": sups.get(r.supplier_id, ""),
                                 "arrival_id": r.arrival_id, "status": r.status, "inspector": r.inspector,
                                 "created_at": str(r.created_at)[:19]} for r in rows], total))


# ---------------- IQC 批量操作 ----------------
# 动作 → 所需权限：合格判定与驳回都属于质检录入
IQC_BATCH_PERMS = {
    "approve": "qc:edit",
    "reject": "qc:edit",
}


def _one_iqc(db: Session, obj_id: int, action: str) -> None:
    """单条 IQC 批量动作：取单据 → 校验 → 改明细/状态（不 commit，由 run_batch 统一提交）。

    批量的 approve 语义 = 整单判定合格：该单下所有明细置为「合格」，
    合格数缺失（为 0）时按抽检数补齐，最后按原汇总规则（check_iqc 同款）汇总整单状态。
    """
    o = db.get(IqcOrder, obj_id)
    if not o:
        raise BizException("单据不存在")
    if action == "approve":
        if o.status in IQC_DONE:
            raise BizException("该质检单已判定，如需改判请单独录入")
        items = db.query(IqcItem).filter(IqcItem.iqc_id == obj_id).all()
        if not items:
            raise BizException("该质检单没有明细，无法批量判定")
        _apply_iqc_items(db, o, [
            {"id": it.id, "result": "合格", "qualified_qty": it.qualified_qty or it.sample_qty}
            for it in items
        ])
    elif action == "reject":
        if o.status == "不合格":
            raise BizException("该质检单已是不合格状态")
        o.status = "不合格"
    else:
        raise BizException(f"不支持的批量动作：{action}")


@router.post("/iqc/batch")
def batch_iqc(payload: BatchIn, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """批量判定来料质检单：approve=整单合格（明细全部置合格并汇总）/ reject=整单不合格。"""
    return run_batch_guarded(db, user, payload, IQC_BATCH_PERMS, _one_iqc)


@router.get("/iqc/{iid}")
def detail_iqc(iid: int, db: Session = Depends(get_db), _=Depends(require_permissions("qc:view"))):
    o = db.get(IqcOrder, iid)
    if not o:
        raise BizException("单据不存在")
    mats, _, sups = load_maps(db)
    items = db.query(IqcItem).filter(IqcItem.iqc_id == iid).all()
    return success({"id": o.id, "qc_no": o.qc_no, "supplier_name": sups.get(o.supplier_id, ""),
                    "status": o.status, "inspector": o.inspector,
                    "items": [{"id": i.id, "material_id": i.material_id, "material_name": mats.get(i.material_id, ""),
                               "sample_qty": i.sample_qty, "qualified_qty": i.qualified_qty, "result": i.result} for i in items]})


@router.post("/iqc")
def create_iqc(payload: dict, db: Session = Depends(get_db), _=Depends(require_permissions("qc:edit"))):
    o = IqcOrder(qc_no=gen_no("IQC"), supplier_id=payload.get("supplier_id"), arrival_id=payload.get("arrival_id"),
                 inspector=payload.get("inspector", ""), remark=payload.get("remark", ""), status="待检")
    db.add(o); db.flush()
    for it in payload.get("items", []):
        db.add(IqcItem(iqc_id=o.id, material_id=it["material_id"], sample_qty=it.get("sample_qty", 0),
                       qualified_qty=it.get("qualified_qty", 0), result="待检"))
    db.commit(); db.refresh(o)
    return success({"id": o.id, "qc_no": o.qc_no}, message="新增成功")


@router.post("/iqc/{iid}/check")
def check_iqc(iid: int, payload: dict, db: Session = Depends(get_db), _=Depends(require_permissions("qc:edit"))):
    """录入检验结果：items=[{id, result, qualified_qty}]，并汇总整单状态。"""
    o = db.get(IqcOrder, iid)
    if not o:
        raise BizException("单据不存在")
    _apply_iqc_items(db, o, payload.get("items", []))
    o.inspector = payload.get("inspector", o.inspector)
    db.commit()
    return success(message="检验结果已保存")


# ---------------- FQC 成品质检 ----------------
@router.get("/fqc")
def list_fqc(page: int = 1, page_size: int = 20, status: str | None = None,
             sort_by: str | None = None, sort_order: str | None = None,
             db: Session = Depends(get_db), _=Depends(require_permissions("qc:view"))):
    q = db.query(FqcOrder)
    if status:
        q = q.filter(FqcOrder.status == status)
    total = q.count()
    rows = apply_ordering(q, FqcOrder, sort_by, sort_order).offset((page - 1) * page_size).limit(page_size).all()
    mats, _, _ = load_maps(db)
    return success(page_result([{"id": r.id, "qc_no": r.qc_no, "product_name": mats.get(r.product_id, ""),
                                 "batch_no": r.batch_no, "check_qty": r.check_qty, "qualified_qty": r.qualified_qty,
                                 "status": r.status, "inspector": r.inspector, "created_at": str(r.created_at)[:19]}
                                for r in rows], total))


@router.post("/fqc")
def create_fqc(payload: dict, db: Session = Depends(get_db), _=Depends(require_permissions("qc:edit"))):
    o = FqcOrder(qc_no=gen_no("FQC"), product_id=payload["product_id"], batch_no=payload.get("batch_no", ""),
                 check_qty=payload.get("check_qty", 0), qualified_qty=payload.get("qualified_qty", 0),
                 inspector=payload.get("inspector", ""), status=payload.get("status", "待检"),
                 remark=payload.get("remark", ""))
    db.add(o); db.commit(); db.refresh(o)
    return success({"id": o.id, "qc_no": o.qc_no}, message="新增成功")


# ---------------- FQC 批量操作 ----------------
# 动作 → 所需权限：合格判定与驳回都属于质检录入
FQC_BATCH_PERMS = {
    "approve": "qc:edit",
    "reject": "qc:edit",
}


def _one_fqc(db: Session, obj_id: int, action: str) -> None:
    """单条 FQC 批量动作：取单据 → 校验 → 改状态（不 commit，由 run_batch 统一提交）。

    FQC 没有单条审核端点（只有 PUT 改写），批量 approve 语义 = 整单置「合格」，
    合格数为 0 时按检验数补齐（沿用 PUT /fqc/{fid} 的字段覆盖方式）。
    """
    o = db.get(FqcOrder, obj_id)
    if not o:
        raise BizException("单据不存在")
    if action == "approve":
        if o.status == "合格":
            raise BizException("该成品质检单已是合格状态")
        _apply_fqc_fields(db, o, {"status": "合格", "qualified_qty": o.qualified_qty or o.check_qty})
    elif action == "reject":
        if o.status == "不合格":
            raise BizException("该质检单已是不合格状态")
        _apply_fqc_fields(db, o, {"status": "不合格"})
    else:
        raise BizException(f"不支持的批量动作：{action}")


@router.post("/fqc/batch")
def batch_fqc(payload: BatchIn, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """批量判定成品质检单：approve=置合格（合格数为 0 时补为检验数）/ reject=置不合格。"""
    return run_batch_guarded(db, user, payload, FQC_BATCH_PERMS, _one_fqc)


@router.put("/fqc/{fid}")
def update_fqc(fid: int, payload: dict, db: Session = Depends(get_db), _=Depends(require_permissions("qc:edit"))):
    o = db.get(FqcOrder, fid)
    if not o:
        raise BizException("单据不存在")
    _apply_fqc_fields(db, o, payload)
    db.commit()
    return success(message="修改成功")
