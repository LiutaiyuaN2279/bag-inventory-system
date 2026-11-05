"""新合成流程的全量正常质量门禁；抽检、整批声明和质量放行各自记录。"""
from datetime import date, datetime, timedelta, timezone
import math
import re
import json

from app.core.exceptions import BizException
from app.models.procurement import PurchaseArrival, PurchaseArrivalItem
from app.models.quality import IqcItem, IqcOrder


def business_today():
    return datetime.now(timezone(timedelta(hours=8))).date()


def declared_date(value, name):
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise BizException(f"请明确填写{name}，格式YYYY-MM-DD；不使用创建时间替代")
    try:
        result = date.fromisoformat(value)
    except ValueError:
        raise BizException(f"{name}无效")
    if result > business_today():
        raise BizException(f"{name}不能晚于业务今天")
    return result


def quantity(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise BizException(f"{name}必须是有限非负数，不能用空值或布尔值代替")
    return value


def arrival_binding(arrival, rows):
    return json.dumps({"arrival_id": arrival.id, "order_id": arrival.order_id,
        "supplier_id": arrival.supplier_id, "actual_receipt_date": arrival.actual_receipt_date,
        "items": [{"id": r.id, "order_item_id": r.order_item_id, "material_id": r.material_id,
                   "warehouse_id": r.warehouse_id, "location_id": r.location_id,
                   "color_batch_id": r.color_batch_id,
                   "arrived_qty": float(quantity(r.arrived_qty, "到货数量")),
                   "qualified_qty": float(quantity(r.qualified_qty, "原登记合格数"))}
                  for r in sorted(rows, key=lambda r: r.id)]}, sort_keys=True, allow_nan=False)


def bound_items(db, iqc):
    arrival = db.get(PurchaseArrival, iqc.arrival_id) if type(iqc.arrival_id) is int else None
    if not arrival or arrival.status != "待验收" or iqc.supplier_id != arrival.supplier_id:
        raise BizException("质检与待验收到货单/供应商绑定不完整")
    declared_date(arrival.actual_receipt_date, "实际收货日")
    siblings = db.query(IqcOrder).filter_by(arrival_id=arrival.id).all()
    if len(siblings) != 1 or siblings[0].id != iqc.id:
        raise BizException("同一到货存在多份或冲突质检依据，不能选择latest放行")
    source = {i.id: i for i in db.query(PurchaseArrivalItem).filter_by(arrival_id=arrival.id)}
    if not iqc.arrival_binding or iqc.arrival_binding != arrival_binding(arrival, source.values()):
        raise BizException("到货内容相对质检建立时已变化或缺少绑定，不能沿用旧放行")
    items = db.query(IqcItem).filter_by(iqc_id=iqc.id).all()
    keys = [i.arrival_item_id for i in items]
    if not source or len(keys) != len(set(keys)) or set(keys) != set(source):
        raise BizException("质检未精确覆盖全部到货明细，旧无绑定记录不能授信")
    for item in items:
        raw = source[item.arrival_item_id]
        if raw.material_id != item.material_id:
            raise BizException("质检物料与到货明细不一致")
        arrived = quantity(raw.arrived_qty, "到货数量")
        if arrived <= 0:
            raise BizException("到货数量必须大于0")
    return arrival, source, items


def validate_normal_full_release(db, iqc):
    arrival, source, items = bound_items(db, iqc)
    if iqc.status != "合格" or not iqc.inspection_recorded_at or not iqc.inspected_by:
        raise BizException("仅完整最终合格的正常整批结论可放行；不支持部分、让步或不合格处置")
    inspected = declared_date(iqc.inspection_date, "实际检验完成日")
    if inspected < declared_date(arrival.actual_receipt_date, "实际收货日"):
        raise BizException("检验完成日不能早于实际收货日")
    for item in items:
        raw = source[item.arrival_item_id]
        sample = quantity(item.sample_qty, "抽检数")
        passed = quantity(item.qualified_qty, "抽检合格数")
        accepted = quantity(item.accepted_qty, "整批允许接收数")
        if item.result != "合格" or not 0 < sample <= raw.arrived_qty or passed != sample:
            raise BizException("存在未完成或不合格的逐明细检验结论")
        if accepted != raw.arrived_qty:
            raise BizException("本批仅支持各明细全量正常放行，不支持部分质量放行")
        if quantity(raw.qualified_qty, "原登记合格数") != accepted:
            raise BizException("原登记合格数与正式允许接收量不同；本批不支持登记纠错，不自动抬高原声明")
    return arrival, source, items


def require_released_arrival(db, arrival):
    iqcs = db.query(IqcOrder).filter_by(arrival_id=arrival.id).all()
    if len(iqcs) != 1:
        raise BizException("必须有唯一可靠的新绑定质检及独立放行记录")
    iqc = iqcs[0]
    _, source, items = validate_normal_full_release(db, iqc)
    if (iqc.release_status != "已放行" or not iqc.release_recorded_at
            or not iqc.released_by or not (iqc.release_basis or "").strip()):
        raise BizException("尚未完成独立质量放行，管理员也不能绕过")
    if declared_date(iqc.release_date, "实际放行日") < declared_date(iqc.inspection_date, "实际检验完成日"):
        raise BizException("实际放行日不能早于实际检验完成日")
    for item in items:
        if quantity(item.released_qty, "质量放行量") != item.accepted_qty:
            raise BizException("放行量与冻结质量结论不一致")
    return source
