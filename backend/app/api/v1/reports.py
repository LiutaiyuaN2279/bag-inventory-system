"""报表与数据看板：采购报表、库存报表、看板聚合。"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api._helpers import load_maps
from app.api.deps import require_permissions
from app.api.v1.alerts import build_alerts
from app.core.database import get_db
from app.core.visibility import scope_requisitions, user_scope, SCOPE_DEPT, SCOPE_SELF
from app.crud.crud_auth import get_user_permissions, get_user_roles
from app.models.inventory import Inventory, InventoryTransaction, Stocktake
from app.models.master_data import Material, Supplier, Warehouse
from app.models.outsource import OutsourceOrder
from app.models.procurement import (PurchaseArrival, PurchaseArrivalItem, PurchaseOrder, PurchaseOrderItem,
                                    PurchaseRequisition, PurchaseRequisitionItem, PurchaseReturn)
from app.models.quality import FqcOrder, IqcOrder
from app.utils.response import success

router = APIRouter(prefix="/reports", tags=["报表看板"])


def _parse(d):
    return datetime.strptime(d, "%Y-%m-%d").date() if d else None


@router.get("/purchase-by-supplier")
def purchase_by_supplier(start: str | None = None, end: str | None = None, db: Session = Depends(get_db),
                         _=Depends(require_permissions("report:view"))):
    """按供应商汇总采购订单金额。"""
    q = db.query(PurchaseOrder.supplier_id,
                 func.count(PurchaseOrder.id).label("orders"),
                 func.coalesce(func.sum(PurchaseOrder.total_amount), 0).label("amount"))
    if start:
        q = q.filter(func.date(PurchaseOrder.created_at) >= start)
    if end:
        q = q.filter(func.date(PurchaseOrder.created_at) <= end)
    rows = q.group_by(PurchaseOrder.supplier_id).all()
    sups = {s.id: s for s in db.query(Supplier).all()}
    data = []
    for r in rows:
        s = sups.get(r.supplier_id)
        data.append({
            "supplier_id": r.supplier_id,
            "supplier_code": (s.supplier_code if s else "") or "",
            "supplier_name": (s.supplier_name if s else "") or "",
            "contact": (s.contact if s else "") or "",
            "phone": (s.phone if s else "") or "",
            "orders": r.orders,
            "amount": round(r.amount, 2),
            "avg_amount": round(r.amount / r.orders, 2) if r.orders else 0,
        })
    data.sort(key=lambda x: x["amount"], reverse=True)
    return success(data)


@router.get("/purchase-by-material")
def purchase_by_material(start: str | None = None, end: str | None = None, db: Session = Depends(get_db),
                         _=Depends(require_permissions("report:view"))):
    """按物料汇总采购入库数量。"""
    q = db.query(InventoryTransaction.material_id,
                 func.sum(InventoryTransaction.in_qty).label("qty"),
                 func.count(InventoryTransaction.id).label("txns"))\
        .filter(InventoryTransaction.txn_type == "采购入库")
    if start:
        q = q.filter(func.date(InventoryTransaction.txn_time) >= start)
    if end:
        q = q.filter(func.date(InventoryTransaction.txn_time) <= end)
    rows = q.group_by(InventoryTransaction.material_id).all()
    minfo = {m.id: m for m in db.query(Material).all()}
    data = []
    for r in rows:
        m = minfo.get(r.material_id)
        data.append({
            "material_id": r.material_id,
            "material_code": (m.material_code if m else "") or "",
            "material_name": (m.material_name if m else "") or "",
            "spec": (m.spec if m else "") or "",
            "category": (m.category if m else "") or "",
            "unit": (m.unit if m else "") or "",
            "qty": round(r.qty or 0, 2),
            "txns": r.txns or 0,
        })
    data.sort(key=lambda x: x["qty"], reverse=True)
    return success(data)


@router.get("/purchase-supplier-detail")
def purchase_supplier_detail(supplier_id: int, start: str | None = None, end: str | None = None,
                             db: Session = Depends(get_db), _=Depends(require_permissions("report:view"))):
    """某供应商在区间内的采购订单明细。"""
    q = db.query(PurchaseOrder).filter(PurchaseOrder.supplier_id == supplier_id)
    if start:
        q = q.filter(func.date(PurchaseOrder.created_at) >= start)
    if end:
        q = q.filter(func.date(PurchaseOrder.created_at) <= end)
    orders = q.order_by(PurchaseOrder.created_at.desc()).all()
    oids = [o.id for o in orders]
    item_rows = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.order_id.in_(oids)).all() if oids else []
    iqty = {}; aqty = {}
    for it in item_rows:
        iqty[it.order_id] = iqty.get(it.order_id, 0) + (it.qty or 0)
        aqty[it.order_id] = aqty.get(it.order_id, 0) + (it.arrived_qty or 0)
    data = []
    for o in orders:
        data.append({
            "order_no": o.order_no,
            "status": o.status,
            "created_at": o.created_at.strftime("%Y-%m-%d") if o.created_at else "",
            "total_amount": round(o.total_amount or 0, 2),
            "item_qty": round(iqty.get(o.id, 0), 2),
            "arrived_qty": round(aqty.get(o.id, 0), 2),
        })
    return success(data)


@router.get("/purchase-order-detail")
def purchase_order_detail(order_no: str, db: Session = Depends(get_db),
                          _=Depends(require_permissions("report:view"))):
    """某张采购订单的物料明细行。"""
    o = db.query(PurchaseOrder).filter(PurchaseOrder.order_no == order_no).first()
    if not o:
        return success({"order": None, "items": []})
    minfo = {m.id: m for m in db.query(Material).all()}
    sups = {s.id: s.supplier_name for s in db.query(Supplier).all()}
    items = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.order_id == o.id).all()
    rows = []
    for it in items:
        m = minfo.get(it.material_id)
        rows.append({
            "material_code": (m.material_code if m else "") or "",
            "material_name": (m.material_name if m else "") or "",
            "spec": (m.spec if m else "") or "",
            "unit": it.unit or (m.unit if m else "") or "",
            "qty": round(it.qty or 0, 2),
            "unit_price": round(it.unit_price or 0, 2),
            "subtotal": round((it.qty or 0) * (it.unit_price or 0), 2),
            "arrived_qty": round(it.arrived_qty or 0, 2),
            "inbound_qty": round(it.inbound_qty or 0, 2),
        })
    return success({
        "order": {
            "order_no": o.order_no,
            "status": o.status,
            "supplier_name": sups.get(o.supplier_id, ""),
            "created_at": o.created_at.strftime("%Y-%m-%d") if o.created_at else "",
            "total_amount": round(o.total_amount or 0, 2),
        },
        "items": rows,
    })


@router.get("/purchase-material-detail")
def purchase_material_detail(material_id: int, start: str | None = None, end: str | None = None,
                             db: Session = Depends(get_db), _=Depends(require_permissions("report:view"))):
    """某物料在区间内的采购入库明细。"""
    q = db.query(InventoryTransaction)\
        .filter(InventoryTransaction.material_id == material_id,
                InventoryTransaction.txn_type == "采购入库")
    if start:
        q = q.filter(func.date(InventoryTransaction.txn_time) >= start)
    if end:
        q = q.filter(func.date(InventoryTransaction.txn_time) <= end)
    txns = q.order_by(InventoryTransaction.txn_time.desc()).all()
    from app.models.master_data import Warehouse
    wh = {w.id: w.warehouse_name for w in db.query(Warehouse).all()}
    return success([{
        "txn_no": t.txn_no,
        "txn_time": t.txn_time.strftime("%Y-%m-%d %H:%M") if t.txn_time else "",
        "in_qty": round(t.in_qty or 0, 2),
        "warehouse": wh.get(t.warehouse_id, ""),
        "operator": t.operator or "",
    } for t in txns])


@router.get("/inventory-summary")
def inventory_summary(db: Session = Depends(get_db), _=Depends(require_permissions("report:view"))):
    """库存收发存汇总：按物料统计当前结存。"""
    rows = db.query(Inventory.material_id, func.sum(Inventory.qty).label("qty"))\
        .group_by(Inventory.material_id).all()
    minfo = {m.id: m for m in db.query(Material).all()}
    data = []
    for r in rows:
        m = minfo.get(r.material_id)
        data.append({
            "material_id": r.material_id,
            "material_code": (m.material_code if m else "") or "",
            "material_name": (m.material_name if m else "") or "",
            "spec": (m.spec if m else "") or "",
            "category": (m.category if m else "") or "",
            "unit": (m.unit if m else "") or "",
            "safety_stock": (m.safety_stock if m else 0) or 0,
            "stock_qty": round(r.qty or 0, 2),
        })
    data.sort(key=lambda x: x["stock_qty"], reverse=True)
    return success(data)


@router.get("/inventory-material-detail")
def inventory_material_detail(material_id: int, db: Session = Depends(get_db),
                              _=Depends(require_permissions("report:view"))):
    """某物料的库存分布（按仓库）+ 出入库流水明细。"""
    from app.models.master_data import Warehouse
    wh = {w.id: w.warehouse_name for w in db.query(Warehouse).all()}
    # 各仓结存
    inv_rows = db.query(Inventory).filter(Inventory.material_id == material_id).all()
    by_wh = [{"warehouse": wh.get(i.warehouse_id, ""), "stock_qty": round(i.qty or 0, 2)}
             for i in inv_rows if (i.qty or 0) != 0]
    by_wh.sort(key=lambda x: x["stock_qty"], reverse=True)
    # 出入库流水
    txns = db.query(InventoryTransaction).filter(InventoryTransaction.material_id == material_id)\
        .order_by(InventoryTransaction.txn_time.desc()).limit(200).all()
    flows = [{
        "txn_no": t.txn_no,
        "txn_time": t.txn_time.strftime("%Y-%m-%d %H:%M") if t.txn_time else "",
        "txn_type": t.txn_type,
        "in_qty": round(t.in_qty or 0, 2),
        "out_qty": round(t.out_qty or 0, 2),
        "warehouse": wh.get(t.warehouse_id, ""),
        "operator": t.operator or "",
    } for t in txns]
    return success({"by_warehouse": by_wh, "flows": flows})


@router.get("/inventory-trend")
def inventory_trend(days: int = Query(7, ge=1, le=60), db: Session = Depends(get_db),
                    _=Depends(require_permissions("report:view"))):
    return success(_trend_series(db, days))


def _trend_series(db, days):
    """近 N 天出入库趋势（纯数据，供接口与看板复用）。"""
    start = (date.today() - timedelta(days=days - 1)).isoformat()
    rows = db.query(func.date(InventoryTransaction.txn_time).label("d"),
                    func.sum(InventoryTransaction.in_qty).label("i"),
                    func.sum(InventoryTransaction.out_qty).label("o"))\
        .filter(func.date(InventoryTransaction.txn_time) >= start)\
        .group_by(func.date(InventoryTransaction.txn_time)).all()
    data = {str(r.d): {"in": round(r.i or 0, 2), "out": round(r.o or 0, 2)} for r in rows}
    series = []
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        v = data.get(d, {"in": 0, "out": 0})
        series.append({"date": d, **v})
    return series


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), _=Depends(require_permissions("report:view"))):
    today = date.today().isoformat()
    cards = {
        "materials": db.query(Material).count(),
        "suppliers": db.query(Supplier).count(),
        "stock_kinds": db.query(Inventory).filter(Inventory.qty > 0).count(),
        "today_in": round(db.query(func.coalesce(func.sum(InventoryTransaction.in_qty), 0))
                          .filter(func.date(InventoryTransaction.txn_time) == today).scalar() or 0, 2),
        "today_out": round(db.query(func.coalesce(func.sum(InventoryTransaction.out_qty), 0))
                           .filter(func.date(InventoryTransaction.txn_time) == today).scalar() or 0, 2),
        "pending_orders": db.query(PurchaseOrder).filter(PurchaseOrder.status == "草稿").count(),
        "pending_arrivals": db.query(PurchaseArrival).filter(PurchaseArrival.status == "待验收").count(),
        "pending_alerts": len(build_alerts(db)),
    }
    # 库存 Top10
    mats, _, _ = load_maps(db)
    top = db.query(Inventory.material_id, func.sum(Inventory.qty).label("qty"))\
        .group_by(Inventory.material_id).order_by(func.sum(Inventory.qty).desc()).limit(10).all()
    return success({
        "cards": cards,
        "trend": _trend_series(db, 7),
        "stock_top": [{"material_name": mats.get(r.material_id, ""), "qty": round(r.qty or 0, 2)} for r in top],
    })


ROLE_NAMES = {
    "admin": "系统管理员", "manager": "运营主管",
    "buyer": "采购员", "keeper": "仓管员", "qc": "质检员",
    # 报销岗并入基础账号体系后，首页看板也会按这些角色返回，需有中文名可显示
    "general_manager": "总经理", "finance_approve": "财务审批",
    "maker": "制单员", "reviewer": "复核员", "staff": "普通员工",
    "dept_head": "部门负责人", "dept_director": "部门总监",
}


def _cnt(db, model, **filters):
    q = db.query(model)
    for k, v in filters.items():
        q = q.filter(getattr(model, k) == v)
    return q.count()


# ---------------- 工作台 v2：权限裁剪 + 聚合辅助 ----------------
# 卡片/待办标题 → 依赖的权限码：缺权限即不展示（dashboard:view 所有角色都有，故不作限制，否则会裁空）
CARD_PERM = {
    # KPI 卡
    "物料种类": "basic:material:list", "供应商数": "basic:supplier:list",
    "今日入库": "inventory:view", "今日出库": "inventory:view", "库存种类": "inventory:view",
    "待审订单": "purchase:order:list", "在途订单": "purchase:order:list",
    "待验收到货": "purchase:arrival:list", "待验收单": "purchase:arrival:list",
    "待到货": "purchase:arrival:list",
    "待审核请购": "purchase:requisition:list", "草稿请购": "purchase:requisition:list",
    "退货待审": "purchase:return:list", "待出库退货": "purchase:return:list",
    "库存预警": "inventory:alert", "预警待处理": "inventory:alert",
    "盘点进行中": "inventory:stocktake", "外发在途": "outsource:list",
    "来料待检": "qc:view", "成品待检": "qc:view", "待检合计": "qc:view",
    "近7天检验": "qc:view", "一次合格率": "qc:view",
    # 待办项
    "请购待审核": "purchase:requisition:list", "继续编辑请购单": "purchase:requisition:list",
    "订单待审核": "purchase:order:list", "待提交采购订单": "purchase:order:list",
    "到货待验收": "purchase:arrival:list", "跟进到货": "purchase:arrival:list",
    "采购退货待审": "purchase:return:list", "退货待出库": "purchase:return:list",
    "外发收发料": "outsource:list",
}

QC_PASS = {"合格", "让步接收"}  # 质检通过状态：IQC 单据状态与 FQC 状态同用这一组
QC_DONE = {"合格", "让步接收", "不合格"}  # 已出结论的质检状态：合格率的分母，待检批次不计入

# 角色化任务单据依赖的权限；缺失时降级为最通用的到货单列表，连到货权限都没有则返回空
DOC_PERMS = {
    "admin": {"purchase:requisition:list", "purchase:order:list", "purchase:arrival:list"},
    "manager": {"purchase:requisition:list", "purchase:order:list", "purchase:arrival:list"},
    "buyer": {"purchase:order:list"},
    "keeper": {"inventory:alert"},
    "qc": {"qc:view"},
}


def _allow(label: str, perms: set) -> bool:
    """该卡片/待办是否放行：未登记依赖权限的默认放行。"""
    need = CARD_PERM.get(label)
    return need is None or need in perms


def _last_days(days: int) -> list:
    """近 N 天日期字符串列表（含今天，升序）。"""
    return [(date.today() - timedelta(days=days - 1 - i)).isoformat() for i in range(days)]


def _money(v) -> str:
    """金额展示：千分位 + 2 位小数。"""
    return "¥" + f"{float(v or 0):,.2f}"


def _num(v):
    """数量展示：整数不带小数点，小数保留 2 位（仅用于文案，数值字段仍用 round(x, 2)）。"""
    v = round(float(v or 0), 2)
    return int(v) if v == int(v) else v


def _warehouse_stock(db, whs: dict) -> list:
    """各仓库库存合计 + 有库存的物料种类数，按合计数量倒序（两条聚合查询，不在循环里查库）。"""
    sums = {r.warehouse_id: r.qty for r in db.query(Inventory.warehouse_id, func.sum(Inventory.qty).label("qty"))
            .group_by(Inventory.warehouse_id).all()}
    kinds = {r.warehouse_id: r.k for r in db.query(Inventory.warehouse_id,
                                                   func.count(func.distinct(Inventory.material_id)).label("k"))
             .filter(Inventory.qty > 0).group_by(Inventory.warehouse_id).all()}
    data = []
    for wid, qty in sums.items():
        w = whs.get(wid)
        data.append({
            "warehouse_name": (w.warehouse_name if w else "") or "",
            "type": (w.type if w else "") or "",
            "qty": round(qty or 0, 2),
            "kinds": kinds.get(wid, 0),
        })
    data.sort(key=lambda x: x["qty"], reverse=True)
    return data


def _purchase_trend(db, days: int = 7) -> list:
    """近 N 天到货趋势：数量按到货明细汇总；金额取当日涉及的采购订单金额，同一订单当天多次到货只算一次。"""
    start = _last_days(days)[0]
    rows = db.query(func.date(PurchaseArrival.created_at).label("d"),
                    PurchaseArrival.order_id,
                    PurchaseOrder.total_amount,
                    func.coalesce(func.sum(PurchaseArrivalItem.arrived_qty), 0).label("qty"))\
        .outerjoin(PurchaseArrivalItem, PurchaseArrivalItem.arrival_id == PurchaseArrival.id)\
        .outerjoin(PurchaseOrder, PurchaseOrder.id == PurchaseArrival.order_id)\
        .filter(func.date(PurchaseArrival.created_at) >= start)\
        .group_by(PurchaseArrival.id).all()

    agg, seen = {}, {}
    for r in rows:
        d = str(r.d)
        a = agg.setdefault(d, {"qty": 0.0, "amount": 0.0})
        a["qty"] += r.qty or 0
        if r.order_id not in seen.setdefault(d, set()):     # 同一订单当天只计一次金额
            seen[d].add(r.order_id)
            a["amount"] += r.total_amount or 0
    return [{"date": d, "qty": round(agg.get(d, {}).get("qty", 0), 2),
             "amount": round(agg.get(d, {}).get("amount", 0), 2)} for d in _last_days(days)]


def _qc_series(db, days: int = 7):
    """近 N 天质检趋势：(按日序列, 汇总)。批次数按单据 created_at 分日；
    合格率只以「已出结论」的批次为分母——待检批次还没检验，算进分母会把合格率凭空拉低。"""
    start = _last_days(days)[0]
    agg = {}
    for model, key in ((IqcOrder, "iqc"), (FqcOrder, "fqc")):
        rows = db.query(func.date(model.created_at).label("d"), model.status,
                        func.count(model.id).label("c"))\
            .filter(func.date(model.created_at) >= start)\
            .group_by(func.date(model.created_at), model.status).all()
        for r in rows:
            e = agg.setdefault(str(r.d), {"iqc": 0, "fqc": 0, "pass": 0, "done": 0})
            e[key] += r.c
            if r.status in QC_DONE:
                e["done"] += r.c
            if r.status in QC_PASS:
                e["pass"] += r.c

    series, batches, passed, done = [], 0, 0, 0
    for d in _last_days(days):
        e = agg.get(d)
        if not e:
            series.append({"date": d, "iqc": 0, "fqc": 0, "pass_rate": None})
            continue
        n = e["iqc"] + e["fqc"]
        batches += n
        passed += e["pass"]
        done += e["done"]
        series.append({"date": d, "iqc": e["iqc"], "fqc": e["fqc"],
                       "pass_rate": round(e["pass"] / e["done"] * 100, 1) if e["done"] else None})
    return series, {"batches": batches, "passed": passed, "done": done}


def _docs_fallback(db, sups: dict, limit: int = 8) -> list:
    """最通用的任务单据：最近采购到货单（无单号则给空串）。"""
    rows = db.query(PurchaseArrival, PurchaseOrder.order_no)\
        .outerjoin(PurchaseOrder, PurchaseOrder.id == PurchaseArrival.order_id)\
        .order_by(PurchaseArrival.created_at.desc()).limit(limit).all()
    return [{"kind": "到货单", "no": a.arrival_no, "title": sups.get(a.supplier_id, ""),
             "sub": f"订单 {ono}" if ono else "", "value": "", "status": a.status or "",
             "to": "/procurement/arrival", "status_query": a.status or ""} for a, ono in rows]


def _docs_for_manager(db, sups: dict, limit: int = 8) -> list:
    """管理员/运营主管：请购草稿 + 订单草稿 + 到货待验收各取最近 3 条，合并后整体按创建时间倒序。"""
    reqs = db.query(PurchaseRequisition).filter(PurchaseRequisition.status == "草稿")\
        .order_by(PurchaseRequisition.created_at.desc()).limit(3).all()
    orders = db.query(PurchaseOrder).filter(PurchaseOrder.status == "草稿")\
        .order_by(PurchaseOrder.created_at.desc()).limit(3).all()
    arrivals = db.query(PurchaseArrival, PurchaseOrder.order_no)\
        .outerjoin(PurchaseOrder, PurchaseOrder.id == PurchaseArrival.order_id)\
        .filter(PurchaseArrival.status == "待验收")\
        .order_by(PurchaseArrival.created_at.desc()).limit(3).all()

    # 请购单数量合计（一次聚合查询，避免逐单查明细）
    rqty = {}
    if reqs:
        for it in db.query(PurchaseRequisitionItem.pr_id, func.sum(PurchaseRequisitionItem.qty).label("qty"))\
                .filter(PurchaseRequisitionItem.pr_id.in_([r.id for r in reqs]))\
                .group_by(PurchaseRequisitionItem.pr_id).all():
            rqty[it.pr_id] = it.qty or 0

    merged = []
    for r in reqs:
        merged.append((r.created_at, {
            "kind": "请购单", "no": r.req_no, "title": r.requisitioner or "",
            "sub": r.dept or "", "value": f"合计 {_num(rqty.get(r.id, 0))}" if rqty.get(r.id) else "",
            "status": r.status or "", "to": "/procurement/requisition", "status_query": r.status or ""}))
    for o in orders:
        merged.append((o.created_at, {
            "kind": "采购订单", "no": o.order_no, "title": sups.get(o.supplier_id, ""),
            "sub": "", "value": _money(o.total_amount), "status": o.status or "",
            "to": "/procurement/order", "status_query": o.status or ""}))
    for a, ono in arrivals:
        merged.append((a.created_at, {
            "kind": "到货单", "no": a.arrival_no, "title": sups.get(a.supplier_id, ""),
            "sub": f"订单 {ono}" if ono else "", "value": "", "status": a.status or "",
            "to": "/procurement/arrival", "status_query": a.status or ""}))
    merged.sort(key=lambda x: x[0] or datetime.min, reverse=True)
    return [d for _, d in merged[:limit]]


def _docs_for_buyer(db, sups: dict, limit: int = 8) -> list:
    """采购员：在跟的采购订单（草稿/已审核/部分到货），到货进度用订单明细汇总。"""
    orders = db.query(PurchaseOrder).filter(PurchaseOrder.status.in_(["草稿", "已审核", "部分到货"]))\
        .order_by(PurchaseOrder.created_at.desc()).limit(limit).all()
    agg = {}
    oids = [o.id for o in orders]
    if oids:
        for it in db.query(PurchaseOrderItem).filter(PurchaseOrderItem.order_id.in_(oids)).all():
            e = agg.setdefault(it.order_id, {"qty": 0.0, "arr": 0.0, "units": []})
            e["qty"] += it.qty or 0
            e["arr"] += it.arrived_qty or 0
            u = (it.unit or "").strip()
            if u and u not in e["units"]:
                e["units"].append(u)
    docs = []
    for o in orders:
        e = agg.get(o.id, {"qty": 0.0, "arr": 0.0, "units": []})
        unit = "/".join(e["units"])
        docs.append({
            "kind": "采购订单", "no": o.order_no, "title": sups.get(o.supplier_id, ""),
            "sub": f"已到 {_num(e['arr'])}/{_num(e['qty'])} {unit}".rstrip(),
            "value": _money(o.total_amount), "status": o.status or "",
            "to": "/procurement/order", "status_query": o.status or ""})
    return docs


def _docs_for_keeper(db, mats_obj: dict, alerts: list, limit: int = 8) -> list:
    """仓管员：库存预警前若干条（严重缺货 → 库存偏低各按缺口比例升序，呆滞料排最后）。"""
    def rank(a):
        lvl = a.get("level")
        return ({"critical": 0, "warning": 1}.get(lvl, 2),
                a.get("ratio") if a.get("ratio") is not None else a.get("stock_days", 0))
    docs = []
    for a in sorted(alerts, key=rank)[:limit]:
        m = mats_obj.get(a.get("material_id"))
        dead = a.get("alert_type") == "呆滞料预警"
        docs.append({
            "kind": a.get("alert_type", ""),
            "no": (m.material_code if m else "") or "",
            "title": a.get("material_name", "") or "",
            "sub": a.get("warehouse_name", "") or "",
            "value": (f"库龄 {a.get('stock_days')} 天" if dead
                      else f"现存 {_num(a.get('stock_qty'))} / 安全 {_num(a.get('safety_stock'))}"),
            "status": a.get("level_name") or ("呆滞料" if dead else ""),
            "to": "/inventory/alert", "status_query": ""})
    return docs


def _docs_for_qc(db, mats_obj: dict, sups: dict, limit: int = 8) -> list:
    """质检员：来料待检 + 成品待检各取最近 4 条，合并按创建时间倒序。"""
    iqc = db.query(IqcOrder).filter(IqcOrder.status == "待检")\
        .order_by(IqcOrder.created_at.desc()).limit(4).all()
    fqc = db.query(FqcOrder).filter(FqcOrder.status == "待检")\
        .order_by(FqcOrder.created_at.desc()).limit(4).all()
    merged = [(o.created_at, {
        "kind": "来料质检", "no": o.qc_no, "title": sups.get(o.supplier_id, ""), "sub": "",
        "value": "", "status": o.status or "", "to": "/quality/iqc", "status_query": o.status or ""})
        for o in iqc]
    merged += [(o.created_at, {
        "kind": "成品质检", "no": o.qc_no,
        "title": (mats_obj.get(o.product_id).material_name if mats_obj.get(o.product_id) else ""),
        "sub": o.batch_no or "", "value": f"检验 {_num(o.check_qty)}", "status": o.status or "",
        "to": "/quality/fqc", "status_query": o.status or ""}) for o in fqc]
    merged.sort(key=lambda x: x[0] or datetime.min, reverse=True)
    return [d for _, d in merged[:limit]]


#: 报销岗身份 → 首页「我的待办」前置的报销任务。这些角色原本只看到报销工作台，
#: 并入基础账号体系后首页是采购库存看板，必须把本职的报销待办也并进来。
REIMBURSE_ROLES = {
    "general_manager", "finance_approve", "maker", "reviewer",
    "staff", "dept_head", "dept_director",
}


def _reimburse_digest(db, user, perms) -> tuple[list, list]:
    """返回 (KPI 元组列表, 待办列表)，供报销岗的通用看板追加报销指标。

    KPI 元组格式与 kpi_map 一致：(label, value, icon, color)，
    由调用方统一转成前端要的 dict。

    只统计**该用户有权处理**的项，不越权暴露别人的单据：
    - 待我审批：需 reimburse:bill:approve，且审批层级够、非本人单据；
    - 待制证 / 待复核：需对应制单/复核权限；
    - 我提交的报销单 / 判读不合规：所有报销人可见的本人数据。

    任何异常都静默返回空，避免报销模块的问题拖垮整个首页看板。
    """
    if not any(p.startswith("reimburse:") for p in perms):
        return [], []
    try:
        from app.api.v1.reimburse._common import (
            APPROVAL_NONE, SCOPE_ALL, STATUS_CHECK_FAILED, is_bill_owner,
            required_approval_rank, user_approval_rank, user_data_scope,
            user_department_id,
        )
        from app.models.reimburse import RmbReimbursement, RmbVoucher

        kpis, todos = [], []
        base = db.query(RmbReimbursement)

        # 待我审批
        if "reimburse:bill:approve" in perms:
            my_rank = user_approval_rank(db, user)
            scope = user_data_scope(db, user)
            cand = base.filter(
                RmbReimbursement.status.notin_(("已作废", "已生成凭证")),
                RmbReimbursement.approval_status == APPROVAL_NONE,
            )
            if scope != SCOPE_ALL:
                did = user_department_id(db, user)
                if did is not None:
                    cand = cand.filter(RmbReimbursement.department_id == did)
            pending = 0
            for b in cand.all():
                if is_bill_owner(b, user):
                    continue
                if my_rank >= required_approval_rank(b.amount, None):
                    pending += 1
            if pending:
                kpis.append(("待我审批", pending, "Stamp", "#e6a23c"))
                todos.append({"title": "报销单待我审批", "count": pending,
                              "action": "去审批", "to": "/reimburse/list", "status": ""})

        # 待制证
        if "reimburse:voucher:make" in perms:
            n = base.filter(RmbReimbursement.status == "待制证").count()
            if n:
                kpis.append(("待制证", n, "Tickets", "#409eff"))
                todos.append({"title": "待制证", "count": n, "action": "去制证",
                              "to": "/reimburse/voucher/pending", "status": ""})

        # 待复核
        if "reimburse:voucher:review" in perms:
            n = db.query(RmbVoucher).filter(RmbVoucher.status == "未复核").count()
            if n:
                kpis.append(("待复核凭证", n, "Finished", "#67c23a"))
                todos.append({"title": "凭证待复核", "count": n, "action": "去复核",
                              "to": "/reimburse/voucher/review", "status": ""})

        # 本人提交 / 判读不合规（所有报销人可见）
        mine = base.filter(RmbReimbursement.created_by == getattr(user, "username", ""))
        my_total = mine.count()
        if my_total:
            kpis.append(("我提交的报销单", my_total, "Document", "#909399"))
        bad = mine.filter(RmbReimbursement.status == STATUS_CHECK_FAILED).count()
        if bad:
            kpis.append(("判读不合规", bad, "Warning", "#f56c6c"))
            todos.append({"title": "判读不合规待处理", "count": bad, "action": "去处理",
                          "to": f"/reimburse/list?status={STATUS_CHECK_FAILED}", "status": ""})
        return kpis[:3], todos[:3]
    except Exception:
        return [], []


def _docs_scoped_requisitions(db, user, sups: dict, limit: int = 8) -> list:
    """部门 / 本人视野下的「与我相关的单据」：只列视野内的请购单。

    其它单据（订单/到货/退货）没有部门归属列，无法可靠地按部门切分，
    与其给一份越权的全公司清单，不如只给真正属于本范围的请购单。
    """
    q = scope_requisitions(db, user, db.query(PurchaseRequisition))
    rows = q.order_by(PurchaseRequisition.created_at.desc()).limit(limit).all()
    if not rows:
        return []
    # 合计数量：一次聚合，避免逐单查询
    qty = {}
    for it in db.query(PurchaseRequisitionItem.pr_id,
                       func.sum(PurchaseRequisitionItem.qty).label("qty"))\
            .filter(PurchaseRequisitionItem.pr_id.in_([r.id for r in rows]))\
            .group_by(PurchaseRequisitionItem.pr_id).all():
        qty[it.pr_id] = it.qty or 0
    return [{
        "kind": "请购单", "no": r.req_no, "title": r.requisitioner or "",
        "sub": r.dept or "",
        "value": f"合计 {_num(qty.get(r.id, 0))}" if qty.get(r.id) else "",
        "status": r.status or "", "to": "/procurement/requisition",
        "status_query": r.status or "",
    } for r in rows]


@router.get("/workbench")
def workbench(db: Session = Depends(get_db), user=Depends(require_permissions("dashboard:view"))):
    """按当前用户角色返回定制化首页看板 v2：KPI + 我的待办 + 趋势 + 与我相关的单据。
    仅需 dashboard:view 权限（所有角色均具备），不依赖 report:view，避免越权报错；
    在此之上再按用户真实权限裁剪数据块——前端不该看到自己没权限的数字。"""
    roles = get_user_roles(db, user)
    role = "admin" if "admin" in roles else (roles[0] if roles else "default")
    perms = set(get_user_permissions(db, user))

    today = date.today().isoformat()
    # 预警实时计算且开销最大：无 inventory:alert 的用户既不该看到预警数，也不必白算一遍
    alerts = build_alerts(db) if "inventory:alert" in perms else []
    S = {
        "materials": _cnt(db, Material),
        "suppliers": _cnt(db, Supplier),
        "stock_kinds": db.query(Inventory).filter(Inventory.qty > 0).count(),
        "today_in": round(db.query(func.coalesce(func.sum(InventoryTransaction.in_qty), 0))
                          .filter(func.date(InventoryTransaction.txn_time) == today).scalar() or 0, 2),
        "today_out": round(db.query(func.coalesce(func.sum(InventoryTransaction.out_qty), 0))
                           .filter(func.date(InventoryTransaction.txn_time) == today).scalar() or 0, 2),
        "req_draft": scope_requisitions(
            db, user,
            db.query(PurchaseRequisition).filter(PurchaseRequisition.status == "草稿")
        ).count(),
        "order_draft": _cnt(db, PurchaseOrder, status="草稿"),
        "arrival_pending": _cnt(db, PurchaseArrival, status="待验收"),
        "return_draft": _cnt(db, PurchaseReturn, status="草稿"),
        "iqc_pending": _cnt(db, IqcOrder, status="待检"),
        "fqc_pending": _cnt(db, FqcOrder, status="待检"),
        "outsource_active": db.query(OutsourceOrder)
        .filter(OutsourceOrder.status.in_(["已发料", "部分收回"])).count(),
        "stocktake_active": db.query(Stocktake)
        .filter(Stocktake.status.in_(["草稿", "盘点中"])).count(),
        "alerts": len(alerts),
    }

    # 名称映射一次取齐（任务单据、概览、仓库合计都要用；避免循环里反复查库）
    mat_rows = db.query(Material).all()
    mats_obj = {m.id: m for m in mat_rows}
    mats = {m.id: m.material_name for m in mat_rows}
    whs = {w.id: w for w in db.query(Warehouse).all()}
    sups = {s.id: s.supplier_name for s in db.query(Supplier).all()}

    # 各角色 KPI（贴近其日常关注）
    kpi_map = {
        "admin": [
            ("物料种类", S["materials"], "Goods", "#0FDC78"),
            ("供应商数", S["suppliers"], "OfficeBuilding", "#27D2BF"),
            ("今日入库", S["today_in"], "Download", "#67c23a"),
            ("今日出库", S["today_out"], "Upload", "#f56c6c"),
            ("库存种类", S["stock_kinds"], "Box", "#80C1FF"),
            ("待审订单", S["order_draft"], "Tickets", "#EFAA17"),
            ("待验收到货", S["arrival_pending"], "Box", "#e6a23c"),
            ("预警待处理", S["alerts"], "Bell", "#f56c6c"),
        ],
        "manager": [
            ("待审核请购", S["req_draft"], "Document", "#EFAA17"),
            ("待审核订单", S["order_draft"], "Tickets", "#e6a23c"),
            ("待验收单", S["arrival_pending"], "Box", "#67c23a"),
            ("退货待审", S["return_draft"], "RefreshLeft", "#f56c6c"),
            ("库存预警", S["alerts"], "Bell", "#f56c6c"),
            ("今日入库", S["today_in"], "Download", "#0FDC78"),
            ("今日出库", S["today_out"], "Upload", "#0ea5e9"),
            ("库存种类", S["stock_kinds"], "Box", "#80C1FF"),
        ],
        "buyer": [
            ("草稿请购", S["req_draft"], "Document", "#27D2BF"),
            ("待审订单", S["order_draft"], "Tickets", "#EFAA17"),
            ("待到货", S["arrival_pending"], "Box", "#67c23a"),
            ("供应商数", S["suppliers"], "OfficeBuilding", "#0ea5e9"),
            ("物料种类", S["materials"], "Goods", "#0FDC78"),
            ("库存种类", S["stock_kinds"], "Box", "#80C1FF"),
        ],
        "keeper": [
            ("待验收到货", S["arrival_pending"], "Box", "#67c23a"),
            ("待出库退货", S["return_draft"], "RefreshLeft", "#f56c6c"),
            ("库存预警", S["alerts"], "Bell", "#f56c6c"),
            ("盘点进行中", S["stocktake_active"], "EditPen", "#a78bfa"),
            ("今日入库", S["today_in"], "Download", "#0FDC78"),
            ("今日出库", S["today_out"], "Upload", "#0ea5e9"),
            ("外发在途", S["outsource_active"], "Van", "#0ea5e9"),
            ("库存种类", S["stock_kinds"], "Box", "#80C1FF"),
        ],
        "qc": [
            ("来料待检", S["iqc_pending"], "DocumentChecked", "#14b8a6"),
            ("成品待检", S["fqc_pending"], "Medal", "#10b981"),
            ("待检合计", S["iqc_pending"] + S["fqc_pending"], "CircleCheck", "#e6a23c"),
        ],
    }

    # 各角色「我的待办」：可点击直达对应页面，并附带自动筛选状态（status）
    todo_map = {
        "admin": [
            ("请购待审核", S["req_draft"], "去审核", "/procurement/requisition", "草稿"),
            ("订单待审核", S["order_draft"], "去审核", "/procurement/order", "草稿"),
            ("到货待验收", S["arrival_pending"], "去验收", "/procurement/arrival", "待验收"),
            ("采购退货待审", S["return_draft"], "去处理", "/procurement/return", "草稿"),
            ("来料待检", S["iqc_pending"], "去质检", "/quality/iqc", "待检"),
            ("库存预警", S["alerts"], "去处理", "/inventory/alert", ""),
        ],
        "manager": [
            ("请购待审核", S["req_draft"], "去审核", "/procurement/requisition", "草稿"),
            ("订单待审核", S["order_draft"], "去审核", "/procurement/order", "草稿"),
            ("采购退货待审", S["return_draft"], "去审核", "/procurement/return", "草稿"),
            ("到货待验收", S["arrival_pending"], "去查看", "/procurement/arrival", "待验收"),
            ("库存预警", S["alerts"], "去查看", "/inventory/alert", ""),
        ],
        "buyer": [
            ("继续编辑请购单", S["req_draft"], "去制单", "/procurement/requisition", "草稿"),
            ("待提交采购订单", S["order_draft"], "去处理", "/procurement/order", "草稿"),
            ("跟进到货", S["arrival_pending"], "去查看", "/procurement/arrival", "待验收"),
        ],
        "keeper": [
            ("到货待验收", S["arrival_pending"], "去验收", "/procurement/arrival", "待验收"),
            ("退货待出库", S["return_draft"], "去出库", "/procurement/return", "草稿"),
            ("库存预警", S["alerts"], "去处理", "/inventory/alert", ""),
            ("盘点进行中", S["stocktake_active"], "去盘点", "/inventory/stocktake", "盘点中"),
            ("外发收发料", S["outsource_active"], "去处理", "/production/outsource", "在途"),
        ],
        "qc": [
            ("来料待检", S["iqc_pending"], "去质检", "/quality/iqc", "待检"),
            ("成品待检", S["fqc_pending"], "去质检", "/quality/fqc", "待检"),
        ],
    }

    # 近 7 天质检聚合：qc 的额外 KPI 与 qc_trend 复用同一份结果，只算一次
    qc_trend, qc_sum = [], {"batches": 0, "passed": 0, "done": 0}
    if "qc:view" in perms:
        qc_trend, qc_sum = _qc_series(db, 7)

    # 按权限裁剪 KPI/待办：明显越权的卡片直接不展示
    rows_kpi = [r for r in kpi_map.get(role, kpi_map["admin"]) if _allow(r[0], perms)]
    # 追加 KPI 补齐每行（避免留白）：质检看质检量，采购看在途订单
    if role == "qc" and "qc:view" in perms:
        rate = f"{round(qc_sum['passed'] / qc_sum['done'] * 100, 1)}%" if qc_sum["done"] else "—"
        rows_kpi += [("近7天检验", qc_sum["batches"], "DataLine", "#8b5cf6"),
                     ("一次合格率", rate, "TrendCharts", "#22c55e")]
    elif role == "buyer" and "purchase:order:list" in perms:
        in_transit = db.query(PurchaseOrder).filter(PurchaseOrder.status.in_(["已审核", "部分到货"])).count()
        rows_kpi += [("在途订单", in_transit, "Van", "#8b5cf6")]

    # 报销岗并入基础账号体系后：首页既要看到采购库存全局概览，也要看到自己的报销待办，
    # 否则「待我审批 9 张」这类本职任务在首页消失，反而不如原来的报销工作台好用。
    rb_extra_kpi, rb_extra_todo = _reimburse_digest(db, user, perms)
    if rb_extra_kpi:
        # 卡条最多 8 张，报销指标优先保留（那是本职任务），业务卡从尾部让位
        rows_kpi = (rows_kpi[: max(0, 8 - len(rb_extra_kpi))] + rb_extra_kpi)

    kpis = [{"label": k, "value": v, "icon": ic, "color": c} for (k, v, ic, c) in rows_kpi]

    # 动作文案按「实际有没有该动作的权限」改写：报销岗并入基础体系后拿到的是**只读**
    # 业务权限（如 purchase:requisition:list 但没有 :approve），若照搬 admin 的待办
    # 文案会出现「去审核」却审核不了的误导，这里按待办标题降级为「去查看」。
    TODO_ACTION_PERM = {
        "请购待审核": ("purchase:requisition:approve",),
        "订单待审核": ("purchase:order:approve",),
        "待提交采购订单": ("purchase:order:add", "purchase:order:edit"),
        "继续编辑请购单": ("purchase:requisition:add", "purchase:requisition:edit"),
        "到货待验收": ("purchase:arrival:approve", "purchase:arrival:add"),
        "跟进到货": (),                              # 只读查看即可
        "采购退货待审": ("purchase:return:approve",),
        "退货待出库": ("purchase:return:approve", "purchase:return:add"),
        "来料待检": ("qc:edit",),
        "成品待检": ("qc:edit",),
        "库存预警": (),                              # 有 inventory:alert 就能处理
        "盘点进行中": ("inventory:stocktake",),
        "外发收发料": ("outsource:edit",),
    }

    def _action_for(title: str, action: str) -> str:
        need = TODO_ACTION_PERM.get(title)
        if need is None or not need:          # 无专属权限要求，保持原样
            return action
        return action if any(p in perms for p in need) else "去查看"

    todos = [{"title": t, "count": n, "action": _action_for(t, a), "to": p, "status": st}
             for (t, n, a, p, st) in todo_map.get(role, todo_map["admin"])
             if (n or 0) > 0 and _allow(t, perms)]
    # 报销待办排在最前：这些角色的本职是报销，不能被采购待办淹没
    todos = rb_extra_todo + todos

    # 与我相关的单据：先按角色挑，角色依赖的权限缺失则降级为最通用的到货单列表
    if DOC_PERMS.get(role, set()) <= perms:
        if role in ("admin", "manager"):
            task_docs = _docs_for_manager(db, sups)
        elif role == "buyer":
            task_docs = _docs_for_buyer(db, sups)
        elif role == "keeper":
            task_docs = _docs_for_keeper(db, mats_obj, alerts)
        elif role == "qc":
            task_docs = _docs_for_qc(db, mats_obj, sups)
        else:
            # 未登记角色（如报销岗）不能无条件读到货单：没有到货单权限就不该看到
            task_docs = _docs_fallback(db, sups) if "purchase:arrival:list" in perms else []
    else:
        task_docs = _docs_fallback(db, sups) if "purchase:arrival:list" in perms else []

    # 部门 / 本人视野：到货单等没有部门归属列，给它们看全公司单据等于越权。
    # 请购单是唯一带 dept 的业务表，故按范围改推本部门（或本人）的请购单。
    vscope = user_scope(db, user)
    if vscope in (SCOPE_DEPT, SCOPE_SELF) and "purchase:requisition:list" in perms:
        task_docs = _docs_scoped_requisitions(db, user, sups)

    payload = {
        "role": role,
        "role_name": ROLE_NAMES.get(role, role),
        "real_name": getattr(user, "real_name", "") or "",
        "kpis": kpis,
        "todos": todos,
        "todo_total": sum(t["count"] for t in todos),
        "task_docs": task_docs,
    }

    # 趋势/库存块按权限返回；admin/manager 的 overview 直接复用，不再重复查询
    trend = None
    if "inventory:view" in perms:
        trend = _trend_series(db, 7)
        top = db.query(Inventory.material_id, func.sum(Inventory.qty).label("qty"))\
            .group_by(Inventory.material_id).order_by(func.sum(Inventory.qty).desc()).limit(10).all()
        payload["trend"] = trend
        payload["stock_top"] = [{"material_name": mats.get(r.material_id, ""), "qty": round(r.qty or 0, 2)}
                                for r in top]
        payload["warehouse_stock"] = _warehouse_stock(db, whs)
    if "inventory:alert" in perms:
        payload["alert_total"] = len(alerts)
    if perms & {"report:view", "purchase:order:list", "purchase:arrival:list"}:
        payload["purchase_trend"] = _purchase_trend(db, 7)
    if "qc:view" in perms:
        payload["qc_trend"] = qc_trend

    # 仅管理员/运营主管展示全局概览（趋势 + 库存 Top10）
    if role in ("admin", "manager"):
        payload["overview"] = {
            "trend": trend if trend is not None else _trend_series(db, 7),
            "stock_top": payload.get("stock_top", []),
        }

    return success(payload)
