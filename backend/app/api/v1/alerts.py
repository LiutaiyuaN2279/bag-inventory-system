"""库存预警：安全库存预警 + 呆滞料预警（按库龄）。实时计算，不落表。"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api._helpers import load_maps
from app.api.deps import get_current_user, require_permissions
from app.core.database import get_db
from app.core.exceptions import BizException
from app.models.inventory import Inventory
from app.models.master_data import Material
from app.models.procurement import PurchaseOrder, PurchaseOrderItem, PurchaseRequisition, PurchaseRequisitionItem
from app.models.rbac import User
from app.utils.numbering import gen_no
from app.utils.response import success

router = APIRouter(prefix="/inventory/alerts", tags=["库存-预警"])

DEAD_STOCK_DAYS = 90  # 兼容旧调用的默认全局阈值；不传时按物料特性差异化计算


class RestockIn(BaseModel):
    """低库存一键补货入参：items 留空时由后端按全部安全库存预警物料自动算补货量。"""
    model_config = ConfigDict(extra="allow")

    items: list[dict] = Field(default_factory=list)  # {material_id, qty?}，qty 不传则按「安全库存 − 现存」自动计算
    requisitioner: str = ""                          # 不填取当前登录人
    dept: str = ""                                   # 不填按仓储部
    remark: str = ""                                 # 追加到请购单备注（自动带「由库存预警自动生成」）
    requirement_date: str = ""                       # 期望到货日期 yyyy-mm-dd，落到请购明细


def recommend_dead_stock_days(m: Material) -> int:
    """根据物料分类 + 名称关键词，给出符合客观规律的呆滞库存预警天数（库龄阈值）。
    规律：成品季节性强→短；五金/包材稳定→长；真皮怕潮、干燥剂有保质期→特殊处理。"""
    cat = (m.category or "").strip()
    name = m.material_name or ""
    days = {
        "成品": 90, "面料": 150, "里料": 180,
        "辅料": 180, "五金": 300, "包材": 180,
    }.get(cat, 120)

    # 名称关键词微调（更贴合物料物理/经营特性）
    if any(k in name for k in ["真皮", "牛皮", "皮革"]):
        days = 120                                          # 真皮怕潮、易贬值，不宜久放
    elif any(k in name for k in ["拉链", "日字扣", "D形扣", "插扣", "铆钉", "气眼", "磁扣", "拉头"]):
        days = 360                                          # 五金件性质稳定，可长期存放
    elif any(k in name for k in ["纸箱", "纸盒"]):
        days = 180                                          # 包材怕压怕潮
    elif "干燥剂" in name:
        days = 90                                           # 有保质期
    elif cat == "成品" and any(k in name for k in ["学生", "书包", "新款", "春夏", "秋冬", "旅行"]):
        days = 60                                           # 季节性/潮流成品，贬值快

    return max(30, min(days, 365))


def build_alerts(db: Session, dead_days: int | None = None) -> list:
    """生成库存预警列表（安全库存分级预警 + 呆滞料预警），供预警接口与看板复用。"""
    mats, whs, _ = load_maps(db)
    materials = {m.id: m for m in db.query(Material).all()}
    invs = db.query(Inventory).all()
    result = []
    today = date.today()
    override = dead_days if (dead_days and dead_days > 0) else None

    # 按 (物料, 仓库) 汇总现存数量，用于按仓库维度的安全库存分级预警
    stock_by_mat_wh = {}
    for inv in invs:
        key = (inv.material_id, inv.warehouse_id)
        stock_by_mat_wh[key] = stock_by_mat_wh.get(key, 0) + (inv.qty or 0)

    for (mid, wid), total_qty in stock_by_mat_wh.items():
        m = materials.get(mid)
        if not m or not m.safety_stock or m.safety_stock <= 0:
            continue
        if total_qty < m.safety_stock:
            ratio = total_qty / m.safety_stock
            # 分级：低于安全库存的 50% 为“严重缺货”，否则为“库存偏低”
            if ratio < 0.5:
                level, level_name = "critical", "严重缺货"
            else:
                level, level_name = "warning", "库存偏低"
            wh_name = whs.get(wid, "")
            result.append({
                "alert_type": "安全库存预警",
                "level": level, "level_name": level_name,
                "material_id": mid, "material_name": m.material_name,
                "warehouse_name": wh_name,
                "stock_qty": total_qty, "safety_stock": m.safety_stock,
                "ratio": round(ratio * 100, 1),
                "message": f"{wh_name} 现存 {total_qty}，为安全库存 {m.safety_stock} 的 {round(ratio * 100)}%（{level_name}）",
            })

    # 呆滞料：库龄超过该物料的呆滞阈值（或自定义全局阈值）且仍有库存
    for inv in invs:
        if (inv.qty or 0) <= 0 or not inv.last_move_date:
            continue
        m = materials.get(inv.material_id)
        threshold = override if override else (recommend_dead_stock_days(m) if m else DEAD_STOCK_DAYS)
        try:
            last = datetime.strptime(inv.last_move_date, "%Y-%m-%d").date()
        except ValueError:
            continue
        age = (today - last).days
        if age >= threshold:
            result.append({
                "alert_type": "呆滞料预警",
                "material_id": inv.material_id,
                "material_name": mats.get(inv.material_id, ""),
                "warehouse_name": whs.get(inv.warehouse_id, ""),
                "stock_qty": inv.qty, "stock_days": age,
                "dead_days": threshold,
                "message": f"库龄 {age} 天，已超过该物料呆滞阈值 {threshold} 天，建议处理（替代挪用/变卖/退供）",
            })

    return result


@router.get("")
def alerts(db: Session = Depends(get_db), _=Depends(require_permissions("inventory:alert")),
           dead_days: int | None = Query(None, description="自定义全局呆滞阈值(天)，不传则按物料特性自动判定")):
    result = build_alerts(db, dead_days)
    return success({"list": result, "total": len(result)})


def _gen_pr_no(db) -> str:
    """生成请购单号：gen_no 同秒仅 90 种组合，重复则重试，避免演示时撞唯一索引。"""
    for _ in range(20):
        no = gen_no("PR")
        if not db.query(PurchaseRequisition.id).filter(PurchaseRequisition.req_no == no).first():
            return no
    raise BizException("请购单号生成失败，请重试")


def _pending_hints(db):
    """已有待审请购 + 在途采购订单的未完成量，仅用于提示重复采购，不强制拦截。"""
    pr_status = {r[0]: r[1] for r in db.query(PurchaseRequisition.id, PurchaseRequisition.status).all()}
    pr_pending = {}
    for it in db.query(PurchaseRequisitionItem).all():
        if pr_status.get(it.pr_id) == "草稿":     # 草稿=待审请购，未转订单部分
            pr_pending[it.material_id] = pr_pending.get(it.material_id, 0) + max((it.qty or 0) - (it.ordered_qty or 0), 0)

    order_status = {r[0]: r[1] for r in db.query(PurchaseOrder.id, PurchaseOrder.status).all()}
    in_transit = {}
    for it in db.query(PurchaseOrderItem).all():
        if order_status.get(it.order_id) not in ("已完成", "已作废", "已驳回"):   # 其余状态视为在途
            in_transit[it.material_id] = in_transit.get(it.material_id, 0) + max((it.qty or 0) - (it.arrived_qty or 0), 0)
    return pr_pending, in_transit


@router.post("/restock")
def restock(data: RestockIn, db: Session = Depends(get_db), user: User = Depends(get_current_user),
            _=Depends(require_permissions("purchase:requisition:add", "inventory:alert"))):
    """低库存一键补货：按「安全库存 − 现存数量」生成一张草稿请购单。
    已有待审请购/在途订单的物料只在返回信息和明细备注里提示，不强制拦截（演示系统以简单可靠为先）。"""
    materials = {m.id: m for m in db.query(Material).all()}

    # 现存数量按物料汇总全仓：预警列表是「物料+仓库」维度，补货必须按物料汇总，避免同一物料重复下单
    stock = {}
    for inv in db.query(Inventory).all():
        stock[inv.material_id] = stock.get(inv.material_id, 0) + (inv.qty or 0)

    # 1) 整理补货需求：前端传了明细就用明细，否则自动取全部「现存 < 安全库存」的物料
    demand, skipped = {}, []
    if data.items:
        for it in data.items:
            mid = it.get("material_id")
            if not mid:
                continue
            mid = int(mid)
            m = materials.get(mid)
            if not m:
                skipped.append({"material_id": mid, "material_name": "", "reason": "物料不存在"})
                continue
            sq, safe = stock.get(mid, 0), (m.safety_stock or 0)
            try:
                qty = float(it.get("qty")) if it.get("qty") not in (None, "") else round(safe - sq, 2)
            except (TypeError, ValueError):
                qty = round(safe - sq, 2)          # 数量传了非法值则回退为自动计算
            if qty <= 0:                            # 防呆：补货量不得为负或 0
                skipped.append({"material_id": mid, "material_name": m.material_name,
                                "reason": "现存已达安全库存，无需补货"})
                continue
            demand[mid] = round(demand.get(mid, 0) + qty, 2)
    else:
        for mid, m in materials.items():
            safe, sq = (m.safety_stock or 0), stock.get(mid, 0)
            if safe > 0 and sq < safe:
                demand[mid] = round(safe - sq, 2)

    if not demand:
        raise BizException("当前没有需要补货的物料，无需生成请购单")

    # 2) 组织明细（在途/待审只在备注与 notices 中提示，不扣减补货量）
    pr_pending, in_transit = _pending_hints(db)
    notices, items_out = [], []
    for mid, qty in demand.items():
        m = materials.get(mid)
        name = m.material_name if m else ""
        sq, safe = round(stock.get(mid, 0), 2), (m.safety_stock if m else 0)
        unit = (m.unit if m else "") or "个"
        hint = ""
        if pr_pending.get(mid) or in_transit.get(mid):
            hint = (f"已有待审请购 {round(pr_pending.get(mid, 0), 2)}{unit}、"
                    f"在途 {round(in_transit.get(mid, 0), 2)}{unit}，请注意避免重复采购")
            notices.append(f"{name}：{hint}")
        items_out.append({
            "material_id": mid, "material_code": m.material_code if m else "",
            "material_name": name, "spec": (m.spec if m else "") or "", "unit": unit,
            "stock_qty": sq, "safety_stock": safe, "qty": qty,
            "remark": (f"库存预警自动补货：现存 {sq}，安全库存 {safe}，补货 {qty}" + (f"；{hint}" if hint else ""))[:255],
        })

    # 3) 生成请购单（初始状态草稿，需人工审核）
    remark = (data.remark or "").strip()
    pr = PurchaseRequisition(
        req_no=_gen_pr_no(db),
        requisitioner=(data.requisitioner or "").strip() or user.real_name or user.username,
        dept=(data.dept or "").strip() or "仓储部",
        remark=("由库存预警自动生成" + (f"；{remark}" if remark else ""))[:255],
        status="草稿",
    )
    db.add(pr); db.flush()
    for it in items_out:
        db.add(PurchaseRequisitionItem(pr_id=pr.id, material_id=it["material_id"], qty=it["qty"],
                                       unit=it["unit"], requirement_date=data.requirement_date or "",
                                       remark=it["remark"]))
    db.commit(); db.refresh(pr)
    return success({
        "id": pr.id, "req_no": pr.req_no, "status": pr.status, "remark": pr.remark,
        "item_count": len(items_out), "skipped": skipped, "notices": notices,
        "items": items_out,
    }, message=f"已生成请购单 {pr.req_no}")
