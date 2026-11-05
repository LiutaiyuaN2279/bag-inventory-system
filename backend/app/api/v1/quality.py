"""质检：来料质检(IQC) + 成品质检(FQC)。"""
from fastapi import APIRouter, Depends, Query
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.api._batch import run_batch_guarded
from app.api._helpers import load_maps
from app.api.deps import get_current_user, require_permissions
from app.core.database import get_db
from app.core.exceptions import BizException
from app.crud.crud_base import apply_ordering
from app.models.quality import FqcOrder, IqcItem, IqcOrder
from app.models.procurement import PurchaseArrival, PurchaseArrivalItem
from app.services.quality_release import (arrival_binding, bound_items, declared_date, quantity, validate_normal_full_release)
from app.models.rbac import User
from app.schemas.batch import BatchIn
from app.utils.numbering import gen_no
from app.utils.response import page_result, success

router = APIRouter(tags=["质量管理"])

# 质检单已判定的状态集合：批量判定时不再重复改判，避免覆盖人工录入的明细结果
IQC_DONE = ("合格", "让步接收", "不合格")


def _apply_iqc_items(db: Session, o: IqcOrder, items, inspection_date, operator_id) -> None:
    """本批仅支持完整一次显式结论；部分提交、改判或自动补合格均拒绝。"""
    arrival, source, rows = bound_items(db, o)
    if o.status != "待检" or o.inspection_recorded_at or o.release_status == "已放行":
        raise BizException("已作最终结论，不支持改判或放行撤回")
    completed = declared_date(inspection_date, "实际检验完成日")
    if completed < declared_date(arrival.actual_receipt_date, "实际收货日"):
        raise BizException("检验完成日不能早于实际收货日")
    if not isinstance(items, list) or not items:
        raise BizException("请完整提交每条到货明细的明确检验结论")
    existing = {row.id: row for row in rows}
    keys = [item.get("id") for item in items if isinstance(item, dict)]
    if len(keys) != len(items) or any(type(key) is not int for key in keys) or len(set(keys)) != len(keys) or set(keys) != set(existing):
        raise BizException("本批需完整一次提交全部质检明细；不遗漏、不重复、不跨单")
    plan = []
    for item in items:
        row = existing[item["id"]]
        raw = source[row.arrival_item_id]
        result = item.get("result")
        if result not in ("合格", "不合格", "让步接收"):
            raise BizException("请逐明细明确最终结论；不能将待检默认合格")
        sample = quantity(item.get("sample_qty"), "抽检数")
        passed = quantity(item.get("qualified_qty"), "抽检合格数")
        accepted = quantity(item.get("accepted_qty"), "整批允许接收数")
        if not 0 < sample <= raw.arrived_qty or passed > sample or accepted > raw.arrived_qty:
            raise BizException("样本或整批数量超范围；抽检数不代表整批允许接收量")
        if result == "合格" and passed != sample:
            raise BizException("合格结论必须与抽检合格数量一致")
        plan.append((row, result, sample, passed, accepted))
    for row, result, sample, passed, accepted in plan:
        row.result, row.sample_qty, row.qualified_qty, row.accepted_qty = result, sample, passed, accepted
    # 完整持久化集合汇总；不合格优先，不把混合不合格降为让步。
    results = [row.result for row in rows]
    o.status = "不合格" if "不合格" in results else ("让步接收" if "让步接收" in results else "合格")
    o.inspection_date = completed.isoformat()
    o.inspected_by = operator_id
    o.inspection_recorded_at = datetime.now(timezone.utc)


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
                                 "release_status": r.release_status,
                                 "created_at": str(r.created_at)[:19]} for r in rows], total))


# ---------------- IQC 批量操作 ----------------
# 动作 → 所需权限：合格判定与驳回都属于质检录入
IQC_BATCH_PERMS = {
    "approve": "qc:edit",
    "reject": "qc:edit",
}


def _one_iqc(db: Session, obj_id: int, action: str) -> None:
    if not db.get(IqcOrder, obj_id):
        raise BizException("单据不存在")
    raise BizException("本批不支持批量自动判定；请逐单明确实际检验日期、各行结论与整批允许接收量")


@router.post("/iqc/batch")
def batch_iqc(payload: BatchIn, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """保留旧批量契约并明确拒绝自动判定；本批须逐单明确日期、全部行结论及接收量。"""
    return run_batch_guarded(db, user, payload, IQC_BATCH_PERMS, _one_iqc)


@router.get("/iqc/{iid}")
def detail_iqc(iid: int, db: Session = Depends(get_db), _=Depends(require_permissions("qc:view"))):
    o = db.get(IqcOrder, iid)
    if not o:
        raise BizException("单据不存在")
    mats, _, sups = load_maps(db)
    items = db.query(IqcItem).filter(IqcItem.iqc_id == iid).all()
    arrival_items = {r.id: r for r in db.query(PurchaseArrivalItem).filter_by(arrival_id=o.arrival_id)}
    return success({"id": o.id, "qc_no": o.qc_no, "supplier_name": sups.get(o.supplier_id, ""),
                    "status": o.status, "inspector": o.inspector,
                    "arrival_id": o.arrival_id, "inspection_date": o.inspection_date,
                    "inspected_by": o.inspected_by, "inspection_recorded_at": o.inspection_recorded_at,
                    "release_status": o.release_status, "release_date": o.release_date,
                    "released_by": o.released_by, "release_recorded_at": o.release_recorded_at,
                    "release_basis": o.release_basis, "date_assurance": "declared_unverified",
                    "items": [{"id": i.id, "material_id": i.material_id, "material_name": mats.get(i.material_id, ""),
                               "sample_qty": i.sample_qty, "qualified_qty": i.qualified_qty, "result": i.result,
                               "arrival_item_id": i.arrival_item_id, "accepted_qty": i.accepted_qty,
                               "arrived_qty": arrival_items[i.arrival_item_id].arrived_qty if i.arrival_item_id in arrival_items else None,
                               "declared_qualified_qty": arrival_items[i.arrival_item_id].qualified_qty if i.arrival_item_id in arrival_items else None,
                               "released_qty": i.released_qty} for i in items]})


@router.post("/iqc")
def create_iqc(payload: dict, db: Session = Depends(get_db), _=Depends(require_permissions("qc:edit"))):
    aid = payload.get("arrival_id")
    arrival = db.get(PurchaseArrival, aid) if type(aid) is int else None
    if not arrival or arrival.status != "待验收":
        raise BizException("请选择新登记且待验收的到货单")
    declared_date(arrival.actual_receipt_date, "实际收货日")
    if type(payload.get("supplier_id", arrival.supplier_id)) is not int or payload.get("supplier_id", arrival.supplier_id) != arrival.supplier_id:
        raise BizException("质检供应商与到货不一致")
    if db.query(IqcOrder).filter_by(arrival_id=aid).first():
        raise BizException("到货已有质检记录，不创建重复或latest依据")
    source = {r.id: r for r in db.query(PurchaseArrivalItem).filter_by(arrival_id=aid)}
    items = payload.get("items")
    if not isinstance(items, list) or not items or any(not isinstance(item, dict) for item in items):
        raise BizException("请完整列出关联到货明细")
    keys = [item.get("arrival_item_id") for item in items]
    if any(type(key) is not int for key in keys) or len(set(keys)) != len(keys) or set(keys) != set(source):
        raise BizException("质检需按到货明细ID完整绑定，不按同名物料合并")
    for item in items:
        raw = source[item["arrival_item_id"]]
        if type(item.get("material_id")) is not int or item.get("material_id") != raw.material_id:
            raise BizException("质检物料与到货明细不一致")
    o = IqcOrder(qc_no=gen_no("IQC"), supplier_id=arrival.supplier_id, arrival_id=aid,
                 inspector="", remark=payload.get("remark", ""), status="待检",
                 arrival_binding=arrival_binding(arrival, source.values()))
    try:
        db.add(o); db.flush()
        for item in items:
            db.add(IqcItem(iqc_id=o.id, material_id=item["material_id"],
                           arrival_item_id=item["arrival_item_id"], sample_qty=0,
                           qualified_qty=0, accepted_qty=None, result="待检"))
        db.commit(); db.refresh(o)
    except Exception:
        db.rollback()
        raise
    return success({"id": o.id, "qc_no": o.qc_no}, message="已建立待检绑定；未自动给出质量结论")


@router.post("/iqc/{iid}/check")
def check_iqc(iid: int, payload: dict, db: Session = Depends(get_db),
              user: User = Depends(get_current_user), _=Depends(require_permissions("qc:edit"))):
    o = db.get(IqcOrder, iid)
    if not o:
        raise BizException("单据不存在")
    try:
        _apply_iqc_items(db, o, payload.get("items"), payload.get("inspection_date"), user.id)
        o.inspector = user.username
        db.commit()
    except Exception:
        db.rollback()
        raise
    return success(message="明确检验结论已保存，尚未质量放行")


@router.post("/iqc/{iid}/release")
def release_iqc(iid: int, payload: dict, db: Session = Depends(get_db),
                user: User = Depends(get_current_user), _=Depends(require_permissions("qc:edit"))):
    o = db.get(IqcOrder, iid)
    if not o:
        raise BizException("单据不存在")
    if o.release_status == "已放行":
        raise BizException("已经放行，不重复处理")
    _, _, items = validate_normal_full_release(db, o)
    released = declared_date(payload.get("release_date"), "实际放行日")
    if released < declared_date(o.inspection_date, "实际检验完成日"):
        raise BizException("放行日不能早于检验完成日")
    basis = payload.get("release_basis")
    if type(basis) is not str or not basis.strip():
        raise BizException("请填写明确整批允许接收的放行依据；不从样本自动推断")
    o.release_date, o.release_basis = released.isoformat(), basis.strip()
    o.released_by, o.release_recorded_at = user.id, datetime.now(timezone.utc)
    o.release_status = "已放行"
    for item in items:
        item.released_qty = item.accepted_qty
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return success(message="整张到货正常全量质量放行完成；仍需仓管单独入库")


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
