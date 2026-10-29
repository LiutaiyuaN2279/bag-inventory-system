"""BOM 管理：清单维护（多版本）+ BOM 算料（递归展开，含损耗）。"""
from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session
import math

from app.api._batch import run_batch_guarded
from app.api._helpers import load_maps
from app.api.deps import get_current_user, require_permissions
from app.core.database import get_db
from app.core.exceptions import BizException
from app.crud.crud_base import apply_ordering
from app.models.bom import BomHeader, BomItem
from app.models.procurement import PurchaseRequisition, PurchaseRequisitionItem
from app.models.rbac import User
from app.schemas.batch import BatchIn
from app.schemas.bom import BomCalculateIn, BomCreate, BomToRequisitionIn, BomUpdate
from app.utils.numbering import gen_no
from app.utils.response import page_result, success

router = APIRouter(prefix="/bom", tags=["BOM管理"])

# 离散单位：算料/请购数量向上取整，避免出现 0.33 个拉链头
DISCRETE_UNITS = {'个', '条', '件', '套', '张', '双', '块', '只', '副', '箱'}


def _row_dict(r, mats):
    from app.models.master_data import Material
    name = ""
    return {"id": r.id, "product_id": r.product_id, "version": r.version,
            "version_name": r.version_name, "status": r.status, "reject_reason": r.reject_reason,
            "effective_date": r.effective_date, "default_loss_rate": r.default_loss_rate,
            "remark": r.remark}


# ---------------- 单条业务核心（单条端点与批量端点共用） ----------------
def _do_activate(db: Session, bid: int) -> None:
    """BOM 设为生效：同成品的其他生效版本一并置为失效，保证单版本生效。
    涉及 BomHeader 主表（不 commit，由调用方统一提交）。"""
    bom = db.get(BomHeader, bid)
    if not bom:
        raise BizException("BOM 不存在")
    # 同成品其他生效版本置为失效，保证单版本生效
    others = db.query(BomHeader).filter(BomHeader.product_id == bom.product_id,
                                        BomHeader.status == "生效", BomHeader.id != bid).all()
    for o in others:
        o.status = "失效"
    bom.status = "生效"


def _do_reject(db: Session, bid: int, reason: str) -> None:
    """BOM 驳回：仅非「生效/已驳回」状态可驳回，必须填写原因。不 commit。"""
    bom = db.get(BomHeader, bid)
    if not bom:
        raise BizException("BOM 不存在")
    if bom.status in ("生效", "已驳回"):
        raise BizException("当前状态不可驳回")
    if not (reason or "").strip():
        raise BizException("请填写驳回原因")
    bom.status = "已驳回"
    bom.reject_reason = reason.strip()[:255]


@router.get("")
def list_bom(page: int = 1, page_size: int = 20, keyword: str | None = None,
             product_id: int | None = None, sort_by: str | None = None,
             sort_order: str | None = None, db: Session = Depends(get_db),
             _=Depends(require_permissions("bom:view"))):
    mats, _, _ = load_maps(db)
    q = db.query(BomHeader)
    if product_id:
        q = q.filter(BomHeader.product_id == product_id)
    if keyword:
        ids = [mid for mid, name in mats.items() if keyword in name]
        q = q.filter(BomHeader.product_id.in_(ids)) if ids else q.filter(False)
    total = q.count()
    rows = apply_ordering(q, BomHeader, sort_by, sort_order).offset((page - 1) * page_size).limit(page_size).all()
    data = []
    for r in rows:
        d = _row_dict(r, mats)
        d["product_name"] = mats.get(r.product_id, "")
        data.append(d)
    return success(page_result(data, total))


# ---------------- 批量操作 ----------------
# 动作 → 所需权限：生效/驳回都沿用 BOM 审核权限（与单条端点一致）
BATCH_PERMS = {
    "activate": "bom:approve",
    "reject": "bom:approve",
}


def _one_bom(db: Session, bid: int, action: str, reason: str | None) -> None:
    """单条批量动作：取对象 → 校验 → 改状态（不 commit，由 run_batch 统一提交）。"""
    if action == "activate":
        _do_activate(db, bid)
    elif action == "reject":
        _do_reject(db, bid, reason or "")
    else:
        raise BizException(f"不支持的批量动作：{action}")


@router.post("/batch")
def batch_boms(payload: BatchIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """批量生效/驳回 BOM（逐条独立事务，返回失败明细）。reject 的原因取 payload.reason。

    必须声明在 /{bid} 系列动态路由之前，否则 "batch" 会被当成 bid 匹配（int 转换失败报 422）。
    """
    reason = payload.reason
    return run_batch_guarded(db, user, payload, BATCH_PERMS,
                             lambda d, i, a: _one_bom(d, i, a, reason))


@router.get("/{bid}")
def detail_bom(bid: int, db: Session = Depends(get_db), _=Depends(require_permissions("bom:view"))):
    bom = db.get(BomHeader, bid)
    if not bom:
        raise BizException("BOM 不存在")
    mats, _, _ = load_maps(db)
    items = db.query(BomItem).filter(BomItem.bom_id == bid).all()
    data = _row_dict(bom, mats)
    data["product_name"] = mats.get(bom.product_id, "")
    data["items"] = [
        {"id": i.id, "material_id": i.material_id, "material_name": mats.get(i.material_id, ""),
         "qty": i.qty, "loss_rate": i.loss_rate, "unit": i.unit,
         "is_substitute": i.is_substitute, "substitute_for": i.substitute_for, "remark": i.remark}
        for i in items
    ]
    return success(data)


@router.post("")
def create_bom(data: BomCreate, db: Session = Depends(get_db), _=Depends(require_permissions("bom:edit"))):
    bom = BomHeader(product_id=data.product_id, version=data.version, version_name=data.version_name,
                    status=data.status, effective_date=data.effective_date,
                    default_loss_rate=data.default_loss_rate, remark=data.remark)
    db.add(bom); db.flush()
    for it in data.items:
        db.add(BomItem(bom_id=bom.id, material_id=it["material_id"], qty=it.get("qty", 0),
                       loss_rate=it.get("loss_rate", bom.default_loss_rate), unit=it.get("unit", "个"),
                       is_substitute=it.get("is_substitute", False), substitute_for=it.get("substitute_for"),
                       remark=it.get("remark", "")))
    db.commit(); db.refresh(bom)
    return success(message="新增成功")


@router.put("/{bid}")
def update_bom(bid: int, data: BomUpdate, db: Session = Depends(get_db), _=Depends(require_permissions("bom:edit"))):
    bom = db.get(BomHeader, bid)
    if not bom:
        raise BizException("BOM 不存在")
    for k in ("version_name", "status", "effective_date", "default_loss_rate", "remark"):
        v = getattr(data, k)
        if v is not None:
            setattr(bom, k, v)
    if data.items is not None:
        db.query(BomItem).filter(BomItem.bom_id == bid).delete()
        for it in data.items:
            db.add(BomItem(bom_id=bid, material_id=it["material_id"], qty=it.get("qty", 0),
                           loss_rate=it.get("loss_rate", bom.default_loss_rate), unit=it.get("unit", "个"),
                           is_substitute=it.get("is_substitute", False), substitute_for=it.get("substitute_for")))
    db.commit()
    return success(message="修改成功")


@router.post("/{bid}/activate")
def activate_bom(bid: int, db: Session = Depends(get_db), _=Depends(require_permissions("bom:approve"))):
    _do_activate(db, bid)
    db.commit()
    return success(message="已生效")


@router.post("/{bid}/reject")
def reject_bom(bid: int, reason: str = Body(..., embed=True), db: Session = Depends(get_db),
               _=Depends(require_permissions("bom:approve"))):
    _do_reject(db, bid, reason)
    db.commit()
    return success(message="已驳回")


def _get_bom(db, material_id, version=None):
    """取物料对应 BOM：指定版本则按版本，否则取最新生效版本。"""
    q = db.query(BomHeader).filter(BomHeader.product_id == material_id)
    if version:
        q = q.filter(BomHeader.version == version)
    else:
        q = q.filter(BomHeader.status == "生效").order_by(BomHeader.id.desc())
    return q.first()


def calc_requirements(db, product_id, qty, version=None):
    """BOM 算料核心：递归展开，按单耗×数量×(1+损耗率) 汇总无下级 BOM 的物料需求。
    返回 (required: {物料id: 需求量}, stock: {物料id: 现存数量}, bom: 命中的 BOM)。"""
    from app.models.inventory import Inventory

    stock = {}
    for inv in db.query(Inventory).all():
        stock[inv.material_id] = stock.get(inv.material_id, 0) + (inv.qty or 0)

    required = {}  # material_id -> qty

    def explode(material_id, need_qty, ver, level=0):
        if level > 10:
            return
        bom = _get_bom(db, material_id, ver)
        if not bom:
            # 叶子物料（无 BOM）→ 计入需求
            required[material_id] = required.get(material_id, 0) + need_qty
            return
        for it in db.query(BomItem).filter(BomItem.bom_id == bom.id).all():
            if it.is_substitute:
                continue
            need = it.qty * need_qty * (1 + (it.loss_rate or 0) / 100)
            explode(it.material_id, need, None, level + 1)

    explode(product_id, qty, version)
    return required, stock, _get_bom(db, product_id, version)


def _gen_pr_no(db) -> str:
    """生成请购单号：gen_no 同秒仅 90 种组合，重复则重试，避免演示时撞唯一索引。"""
    for _ in range(20):
        no = gen_no("PR")
        if not db.query(PurchaseRequisition.id).filter(PurchaseRequisition.req_no == no).first():
            return no
    raise BizException("请购单号生成失败，请重试")


@router.post("/calculate")
def calculate(data: BomCalculateIn, db: Session = Depends(get_db), _=Depends(require_permissions("bom:view"))):
    """BOM 算料：递归展开，按单耗×数量×(1+损耗率) 汇总。"""
    from app.models.master_data import Material
    mats, _, _ = load_maps(db)
    minfo = {m.id: m for m in db.query(Material).all()}

    required, stock, bom = calc_requirements(db, data.product_id, data.qty, data.version)

    result = []
    for mid, q in required.items():
        m = minfo.get(mid)
        unit = (m.unit if m else '') or ''
        rq = math.ceil(q) if unit in DISCRETE_UNITS else round(q, 2)
        sq = stock.get(mid, 0)
        result.append({
            "material_id": mid,
            "material_code": m.material_code if m else "",
            "material_name": (m.material_name if m else "") or mats.get(mid, ""),
            "spec": (m.spec if m else "") or "",
            "category": (m.category if m else "") or "",
            "unit": unit,
            "required_qty": rq,
            "stock_qty": round(sq, 2),
            "shortage_qty": round(max(rq - sq, 0), 2),
        })
    return success({
        "product_id": data.product_id,
        "product_name": mats.get(data.product_id, ""),
        "version": bom.version if bom else (data.version or "-"),
        "qty": data.qty,
        "items": result,
    })


@router.post("/to-requisition")
def bom_to_requisition(data: BomToRequisitionIn, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user),
                       _=Depends(require_permissions("purchase:requisition:add"))):
    """BOM 算料结果一键生成请购单：只把「需求量 − 现有库存」的净缺口写进请购单。
    明细可由前端把算料结果原样传回（items），不传则后端按算料入参重新算料。"""
    from app.models.inventory import Inventory
    from app.models.master_data import Material

    mats, _, _ = load_maps(db)
    minfo = {m.id: m for m in db.query(Material).all()}
    bom = _get_bom(db, data.product_id, data.version)
    version_txt = bom.version if bom else (data.version or "-")

    # 1) 整理算料需求：优先用前端算料结果明细，为空则按算料入参重新算料
    need = {}            # material_id -> 需求量
    payload_units = {}   # material_id -> 前端带来的单位（物料档案无单位时兜底）
    if data.items:
        for it in data.items:
            mid = it.get("material_id")
            if not mid:
                continue
            mid = int(mid)
            if mid not in minfo:
                raise BizException(f"物料(id={mid})不存在，无法生成请购单")
            q = float(it.get("required_qty") or 0)
            if q > 0:
                need[mid] = need.get(mid, 0) + q
            if it.get("unit"):
                payload_units[mid] = it["unit"]
    else:
        if not bom:
            raise BizException("该成品未维护生效 BOM，无法算料生成请购单")
        required, _, _ = calc_requirements(db, data.product_id, data.qty, data.version)
        need = {k: v for k, v in required.items() if v > 0}

    if not need:
        raise BizException("算料结果为空，无需请购")

    # 2) 扣减现有库存（全仓汇总，口径同算料接口），只保留净缺口明细
    stock = {}
    for inv in db.query(Inventory).all():
        stock[inv.material_id] = stock.get(inv.material_id, 0) + (inv.qty or 0)

    items_out, skipped = [], 0
    for mid, q in need.items():
        m = minfo.get(mid)
        unit = ((m.unit if m else "") or payload_units.get(mid, "") or "个")
        sq = stock.get(mid, 0)
        net = q - sq
        qty = (math.ceil(net) if unit in DISCRETE_UNITS else round(net, 2)) if net > 0 else 0
        if qty <= 0:      # 库存已够（或取整后为 0）→ 不进请购单
            skipped += 1
            continue
        items_out.append({
            "material_id": mid,
            "material_code": m.material_code if m else "",
            "material_name": (m.material_name if m else "") or mats.get(mid, ""),
            "spec": (m.spec if m else "") or "",
            "unit": unit,
            "required_qty": round(q, 2),
            "stock_qty": round(sq, 2),
            "qty": qty,
            "remark": f"算料需求 {round(q, 2)}，现有库存 {round(sq, 2)}，缺口 {round(net, 2)}",
        })

    if not items_out:
        raise BizException("当前库存已满足需求，无需请购")

    # 3) 生成请购单（初始状态为草稿，需人工审核）
    remark = (data.remark or "").strip()
    auto = f"由 BOM 算料自动生成：{mats.get(data.product_id, '')} × {data.qty}（BOM {version_txt}）"
    pr = PurchaseRequisition(
        req_no=_gen_pr_no(db),
        requisitioner=(data.requisitioner or "").strip() or user.real_name or user.username,
        dept=(data.dept or "").strip() or "采购部",
        remark=(auto + (f"；{remark}" if remark else ""))[:255],
        status="草稿",
    )
    db.add(pr); db.flush()
    for it in items_out:
        db.add(PurchaseRequisitionItem(pr_id=pr.id, material_id=it["material_id"], qty=it["qty"],
                                       unit=it["unit"], requirement_date=data.requirement_date or "",
                                       remark=it["remark"][:255]))
    db.commit(); db.refresh(pr)
    return success({
        "id": pr.id, "req_no": pr.req_no, "status": pr.status, "remark": pr.remark,
        "product_id": data.product_id, "product_name": mats.get(data.product_id, ""),
        "version": version_txt, "qty": data.qty,
        "item_count": len(items_out), "skipped_count": skipped,
        "items": items_out,
    }, message=f"已生成请购单 {pr.req_no}")
