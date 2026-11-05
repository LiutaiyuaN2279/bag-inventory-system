"""到货单创建的统一服务入口。

把「校验明细 → 生成到货单与明细 → 回写订单到货数 → 刷新订单状态」收敛到一处，
供「到货登记」与「AI 识别导入」共用，保证两条入口的校验口径与数据一致性一致。
调用方负责事务提交（本函数不 commit）。
"""
from sqlalchemy.orm import Session

from app.core.exceptions import BizException
from app.models.master_data import Material
from app.models.procurement import (
    PurchaseArrival, PurchaseArrivalItem, PurchaseOrder, PurchaseOrderItem,
)
from app.utils.numbering import gen_no

DISCRETE_UNITS = {'个', '条', '件', '套', '张', '双', '块', '只', '副', '箱'}


def round_qty(qty, unit):
    """离散单位（个/条/件…）取整，连续单位（米/kg…）保留 2 位小数。"""
    if unit in DISCRETE_UNITS:
        return int(round(float(qty or 0)))
    return round(float(qty or 0), 2)


def create_arrival(db: Session, order_id: int, items: list, remark: str = "", actual_receipt_date=None) -> PurchaseArrival:
    from app.services.quality_release import declared_date
    receipt_date = declared_date(actual_receipt_date, "实际收货日")
    order = db.get(PurchaseOrder, order_id)
    if not order:
        raise BizException("采购订单不存在")
    # 草稿 / 已驳回 / 已作废的订单不允许登记到货单
    if order.status in ("草稿", "已驳回", "已作废"):
        raise BizException(f"订单当前状态为「{order.status}」，不允许登记到货单")
    if not items:
        raise BizException("请添加到货明细")
    # 校验循环与写入循环统一使用 round_qty 后的值，避免“校验通过但写库超量”
    _mu = {m.id: (m.unit or '') for m in db.query(Material).all()}
    plan = []
    planned = {}          # order_item_id -> 本次已计划到货数（同一明细重复出现时累计判断）
    total_arrived = 0.0
    for idx, it in enumerate(items, start=1):
        oi = db.get(PurchaseOrderItem, it.get("order_item_id"))
        if not oi:
            raise BizException(f"第 {idx} 行订单明细不存在")
        if oi.order_id != order_id:
            raise BizException(f"第 {idx} 行明细不属于该采购订单，不能跨订单登记到货")
        if not it.get("warehouse_id"):
            raise BizException(f"第 {idx} 行请选择收货仓库")
        unit = _mu.get(oi.material_id, '')
        try:
            arrived = round_qty(it.get("arrived_qty", 0), unit)
            qualified = round_qty(it.get("qualified_qty", arrived), unit)
        except (TypeError, ValueError):
            raise BizException(f"第 {idx} 行到货数量/合格数格式不正确")
        if arrived <= 0:
            raise BizException(f"第 {idx} 行到货数量必须大于 0")
        if qualified < 0:
            raise BizException(f"第 {idx} 行合格数不能为负数")
        if qualified > arrived:
            raise BizException(f"第 {idx} 行合格数不能大于到货数")
        remain = round_qty((oi.qty or 0) - (oi.arrived_qty or 0), unit)
        if round_qty(planned.get(oi.id, 0) + arrived, unit) > remain:
            raise BizException(
                f"第 {idx} 行累计到货数超出订单数量（订单数量 {oi.qty}，已到货 {oi.arrived_qty or 0}）")
        planned[oi.id] = round_qty(planned.get(oi.id, 0) + arrived, unit)
        total_arrived += arrived
        plan.append((it, oi, unit, arrived, qualified))
    if total_arrived <= 0:
        raise BizException("到货数量不能全为 0，请填写实际到货数")

    arr = PurchaseArrival(arrival_no=gen_no("AR"), order_id=order_id,
                          supplier_id=order.supplier_id, remark=remark, status="待验收",
                          actual_receipt_date=receipt_date.isoformat())
    db.add(arr)
    db.flush()
    for it, oi, unit, arrived, qualified in plan:
        db.add(PurchaseArrivalItem(
            arrival_id=arr.id, order_item_id=oi.id, material_id=oi.material_id,
            arrived_qty=arrived, qualified_qty=qualified, warehouse_id=it["warehouse_id"],
            location_id=it.get("location_id"), color_batch_id=it.get("color_batch_id")))
        oi.arrived_qty = round_qty((oi.arrived_qty or 0) + arrived, unit)
    from app.api.v1.purchase_orders import refresh_order_status
    refresh_order_status(db, order_id)
    return arr
