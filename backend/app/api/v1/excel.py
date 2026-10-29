"""Excel 导入导出（openpyxl 内存流）。

约定：
- 导出：主数据 / 库存 / 流水 / 采购单据，统一经 _xlsx_response 生成 .xlsx 下载流；
- 模板：Sheet1 **只有表头**（与导入解析的行号约定一致，数据从第 2 行开始），填写说明放 Sheet2，
  这样用户下载模板后直接填数即可导入，不会因为"示例行没删"而导入脏数据；
- 导入：先整体校验、全部合法才落库；任何一行有错就整单回滚，并把出错行号一次性反馈给用户，
  避免"导了一半"的中间状态。
"""
import io
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from app.api.deps import require_permissions
from app.core.database import get_db
from app.core.exceptions import BizException
from app.models.inventory import Inventory, InventoryTransaction
from app.models.master_data import Location, Material, Supplier, Warehouse
from app.models.procurement import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseRequisition,
    PurchaseRequisitionItem,
)
from app.services.stock_service import post_inbound
from app.utils.response import success

router = APIRouter(tags=["Excel导入导出"])

MAX_IMPORT_ROWS = 2000          # 单次导入行数上限，防止超大文件拖垮进程
MAX_ERRORS_SHOWN = 8            # 错误提示里最多列出几条明细


# ==================== 公共工具 ====================

def _safe(value):
    """防止 Excel 公式注入：openpyxl 只把以 = 开头的字符串当公式，
    因此仅需给这类文本加前导单引号，不会污染正常的负数/以 - 开头的备注。"""
    if isinstance(value, str) and value.startswith("="):
        return "'" + value
    return "" if value is None else value


def _xlsx_response(rows, filename, sheet_title="Sheet1", widths=None, notes=None):
    """把二维列表写成 .xlsx 下载流；notes 非空时额外生成"填写说明"工作表。"""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title[:31] or "Sheet1"
    for row in rows:
        ws.append([_safe(v) for v in row])
    if widths:
        for idx, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(idx)].width = width
    if notes:
        ns = wb.create_sheet("填写说明")
        for line in notes:
            ns.append([line])
        ns.column_dimensions["A"].width = 90
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


def _text(value):
    """单元格转字符串：None→''，整数型浮点去掉 .0（避免物料编码变成 1001.0）。"""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _bool_text(value, default=True):
    t = _text(value).lower()
    if not t:
        return default
    if t in ("停用", "禁用", "否", "no", "n", "false", "0"):
        return False
    if t in ("启用", "正常", "是", "yes", "y", "true", "1"):
        return True
    return default


def _num(value, field, rowno, errors, default=0.0):
    """解析数字，失败或负数则记录错误并返回默认值。"""
    if value is None or _text(value) == "":
        return default
    try:
        num = float(value)
    except (TypeError, ValueError):
        errors.append({"row": rowno, "msg": f"{field}必须是数字（当前为「{_text(value)}」）"})
        return default
    if num < 0:
        errors.append({"row": rowno, "msg": f"{field}不能为负数"})
        return default
    return num


async def _read_sheet(file: UploadFile):
    """读上传文件的活动工作表，文件损坏/格式不对时给出中文提示而不是 500。"""
    raw = await file.read()
    if not raw:
        raise BizException("未收到文件内容，请重新选择文件")
    try:
        wb = load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
    except Exception as exc:  # openpyxl 对非 xlsx / 加密 / 损坏文件抛各种异常
        raise BizException(f"文件无法解析（{exc.__class__.__name__}），请使用下载的 .xlsx 模板填写后上传")
    return wb.active


def _check_row_limit(ws):
    if ws.max_row and ws.max_row - 1 > MAX_IMPORT_ROWS:
        raise BizException(f"单次导入最多 {MAX_IMPORT_ROWS} 行，当前文件有 {ws.max_row - 1} 行")


def _raise_if_errors(errors):
    if not errors:
        return
    shown = "；".join(f"第 {e['row']} 行：{e['msg']}" for e in errors[:MAX_ERRORS_SHOWN])
    tail = f"（共 {len(errors)} 处错误，已全部取消导入）" if len(errors) > MAX_ERRORS_SHOWN else "（已全部取消导入）"
    raise BizException(f"导入失败，请修正后重试 —— {shown}{tail}")


# ==================== 导出：主数据 ====================

@router.get("/export/materials")
def export_materials(db: Session = Depends(get_db), _=Depends(require_permissions("basic:material:list"))):
    rows = db.query(Material).order_by(Material.material_code).all()
    data = [["物料编码", "物料名称", "分类", "规格", "单位", "主色号", "安全库存", "最小批量", "状态", "备注"]]
    for m in rows:
        data.append([m.material_code, m.material_name, m.category, m.spec, m.unit, m.default_color_no,
                     m.safety_stock, m.min_order_qty, "启用" if m.status else "停用", m.remark or ""])
    return _xlsx_response(data, "物料档案.xlsx", "物料档案",
                          widths=[14, 22, 10, 20, 8, 12, 10, 10, 8, 24])


@router.get("/export/suppliers")
def export_suppliers(db: Session = Depends(get_db), _=Depends(require_permissions("basic:supplier:list"))):
    rows = db.query(Supplier).order_by(Supplier.supplier_code).all()
    data = [["供应商编码", "供应商名称", "联系人", "电话", "地址", "付款方式", "交货天数", "状态", "备注"]]
    for s in rows:
        data.append([s.supplier_code, s.supplier_name, s.contact, s.phone, s.address,
                     s.payment_term, s.lead_time_days, "启用" if s.status else "停用", s.remark or ""])
    return _xlsx_response(data, "供应商档案.xlsx", "供应商档案",
                          widths=[14, 24, 10, 16, 30, 14, 10, 8, 24])


# ==================== 导出：库存与流水 ====================

@router.get("/export/inventory")
def export_inventory(keyword: str | None = None, warehouse_id: int | None = None,
                     db: Session = Depends(get_db), _=Depends(require_permissions("inventory:view"))):
    mats = {m.id: m for m in db.query(Material).all()}
    whs = {w.id: w.warehouse_name for w in db.query(Warehouse).all()}
    locs = {l.id: l.location_code for l in db.query(Location).all()}
    q = db.query(Inventory)
    if warehouse_id:
        q = q.filter(Inventory.warehouse_id == warehouse_id)
    rows = q.all()
    data = [["物料编码", "物料名称", "仓库", "库位", "缸号/批次", "现存数量", "最后变动"]]
    for r in rows:
        m = mats.get(r.material_id)
        data.append([m.material_code if m else "", m.material_name if m else "",
                     whs.get(r.warehouse_id, ""), locs.get(r.location_id, ""),
                     r.color_batch_id or "", r.qty, r.last_move_date])
    return _xlsx_response(data, "库存查询.xlsx", "库存查询",
                          widths=[14, 22, 16, 12, 14, 12, 14])


@router.get("/export/transactions")
def export_transactions(db: Session = Depends(get_db), _=Depends(require_permissions("inventory:view"))):
    mats = {m.id: m for m in db.query(Material).all()}
    whs = {w.id: w.warehouse_name for w in db.query(Warehouse).all()}
    rows = db.query(InventoryTransaction).order_by(InventoryTransaction.id.desc()).limit(5000).all()
    data = [["流水号", "类型", "物料编码", "物料名称", "仓库", "入库", "出库", "来源", "操作人", "时间"]]
    for r in rows:
        m = mats.get(r.material_id)
        data.append([r.txn_no, r.txn_type, m.material_code if m else "", m.material_name if m else "",
                     whs.get(r.warehouse_id, ""), r.in_qty, r.out_qty, r.ref_type, r.operator,
                     str(r.txn_time)[:19]])
    return _xlsx_response(data, "出入库流水.xlsx", "出入库流水",
                          widths=[20, 16, 14, 22, 16, 10, 10, 14, 12, 20])


# ==================== 导出：采购单据 ====================

@router.get("/export/purchase-requisitions")
def export_requisitions(db: Session = Depends(get_db), _=Depends(require_permissions("purchase:requisition:list"))):
    mats = {m.id: m for m in db.query(Material).all()}
    rows = (db.query(PurchaseRequisitionItem, PurchaseRequisition)
            .join(PurchaseRequisition, PurchaseRequisition.id == PurchaseRequisitionItem.pr_id)
            .order_by(PurchaseRequisition.id.desc(), PurchaseRequisitionItem.id)
            .all())
    data = [["请购单号", "申请人", "申请部门", "单据状态", "物料编码", "物料名称", "单位",
             "请购数量", "已转订单", "需求日期", "明细备注", "创建时间"]]
    for it, pr in rows:
        m = mats.get(it.material_id)
        data.append([pr.req_no, pr.requisitioner, pr.dept, pr.status,
                     m.material_code if m else "", m.material_name if m else "", it.unit,
                     it.qty, it.ordered_qty, it.requirement_date, it.remark or "",
                     str(pr.created_at)[:19]])
    return _xlsx_response(data, "采购请购单.xlsx", "请购单明细",
                          widths=[20, 12, 14, 10, 14, 22, 8, 12, 12, 14, 20, 20])


@router.get("/export/purchase-orders")
def export_orders(db: Session = Depends(get_db), _=Depends(require_permissions("purchase:order:list"))):
    mats = {m.id: m for m in db.query(Material).all()}
    sups = {s.id: s.supplier_name for s in db.query(Supplier).all()}
    rows = (db.query(PurchaseOrderItem, PurchaseOrder)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.order_id)
            .order_by(PurchaseOrder.id.desc(), PurchaseOrderItem.id)
            .all())
    data = [["采购单号", "供应商", "单据状态", "物料编码", "物料名称", "单位",
             "采购数量", "单价", "金额", "已到货", "已入库", "下单时间"]]
    total = 0.0
    for it, po in rows:
        m = mats.get(it.material_id)
        amount = round((it.qty or 0) * (it.unit_price or 0), 2)
        total += amount
        data.append([po.order_no, sups.get(po.supplier_id, ""), po.status,
                     m.material_code if m else "", m.material_name if m else "", it.unit,
                     it.qty, it.unit_price, amount, it.arrived_qty, it.inbound_qty,
                     str(po.created_at)[:19]])
    data.append([])
    data.append(["", "", "", "", "", "", "", "合计金额", round(total, 2)])
    return _xlsx_response(data, "采购订单.xlsx", "采购订单明细",
                          widths=[20, 24, 10, 14, 22, 8, 12, 12, 14, 12, 12, 20])


# ==================== 导入模板下载 ====================

@router.get("/export/template/materials")
def template_materials(_=Depends(require_permissions("basic:material:list"))):
    data = [["物料编码", "物料名称", "分类", "规格", "单位", "主色号", "安全库存", "最小批量", "状态", "备注"]]
    notes = [
        "物料导入模板使用说明",
        "1. 请在 Sheet1 的【第 2 行起】填写数据，第 1 行表头请勿修改，填完保存为 .xlsx 再上传。",
        "2. 物料编码、物料名称为必填；物料编码已存在的行会被自动跳过（不覆盖原数据）。",
        "3. 分类可填：面料 / 里料 / 辅料 / 五金 / 包材 / 成品，留空默认「辅料」。",
        "4. 单位可填：米 / 码 / 个 / 套 / kg，留空默认「个」。",
        "5. 安全库存、最小批量填数字（不能为负），留空按 0 处理。",
        "6. 状态填「启用」或「停用」，留空默认「启用」。",
        "示例行（请填在 Sheet1 第 2 行）：MAT-DEMO-001 | 示例面料 | 面料 | 150D 涤纶 | 米 | PANTONE 19-4052 | 500 | 100 | 启用 | 可删除",
        "注意：导入是「全部校验通过才写入」，只要有一行有问题，整份文件都不会导入，并会提示出错行号。",
    ]
    return _xlsx_response(data, "物料导入模板.xlsx", "物料导入",
                          widths=[16, 24, 10, 20, 8, 18, 12, 12, 10, 24], notes=notes)


@router.get("/export/template/suppliers")
def template_suppliers(_=Depends(require_permissions("basic:supplier:list"))):
    data = [["供应商编码", "供应商名称", "联系人", "电话", "地址", "付款方式", "交货天数", "状态", "备注"]]
    notes = [
        "供应商导入模板使用说明",
        "1. 请在 Sheet1 的【第 2 行起】填写数据，第 1 行表头请勿修改，填完保存为 .xlsx 再上传。",
        "2. 供应商编码、供应商名称为必填；编码已存在的行会被自动跳过。",
        "3. 付款方式示例：款到发货 / 月结 30 天 / 月结 60 天。",
        "4. 交货天数填整数天数，留空按 0 处理。",
        "5. 状态填「启用」或「停用」，留空默认「启用」。",
        "示例行（请填在 Sheet1 第 2 行）：SUP-DEMO-001 | 示例五金供应商 | 张三 | 13800000000 | 广东省广州市 | 月结 30 天 | 7 | 启用 | 可删除",
        "注意：整份文件全部校验通过才会写入，任一行有误会提示行号并且不导入任何数据。",
    ]
    return _xlsx_response(data, "供应商导入模板.xlsx", "供应商导入",
                          widths=[16, 24, 10, 16, 28, 16, 10, 10, 24], notes=notes)


@router.get("/export/template/inventory")
def template_inventory(_=Depends(require_permissions("inventory:view"))):
    data = [["物料编码", "仓库编码", "数量", "说明"]]
    notes = [
        "库存导入（期初/补录）模板使用说明",
        "1. 请在 Sheet1 的【第 2 行起】填写数据，第 1 行表头请勿修改。",
        "2. 物料编码、仓库编码必须已在系统基础数据中存在，否则该行判为错误。",
        "3. 导入动作等同于「其他入库」，会**累加**到现有库存并生成一条出入库流水，不是覆盖。",
        "   如需冲减，请到「库存管理 - 库存查询 - 库存调整」做其他出库。",
        "4. 数量必须为正数。",
        "示例行（请填在 Sheet1 第 2 行）：MAT-DEMO-001 | WH01 | 500 | 期初建账",
        "注意：整份文件全部校验通过才会写入，任一行有误会提示行号并且不导入任何数据。",
    ]
    return _xlsx_response(data, "库存导入模板.xlsx", "库存导入",
                          widths=[18, 16, 12, 30], notes=notes)


# ==================== 导入：物料 ====================

@router.post("/import/materials")
async def import_materials(file: UploadFile = File(...), db: Session = Depends(get_db),
                           _=Depends(require_permissions("basic:material:add"))):
    ws = await _read_sheet(file)
    _check_row_limit(ws)
    errors, pending, seen = [], [], set()
    for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not row or not _text(row[0]) and not _text(row[1] if len(row) > 1 else None):
            continue                                     # 整行空白，跳过
        code = _text(row[0])
        name = _text(row[1]) if len(row) > 1 else ""
        if not code:
            errors.append({"row": idx, "msg": "物料编码不能为空"})
            continue
        if not name:
            errors.append({"row": idx, "msg": "物料名称不能为空"})
            continue
        if code in seen:
            errors.append({"row": idx, "msg": f"物料编码「{code}」在本文件中重复"})
            continue
        seen.add(code)
        if db.query(Material).filter(Material.material_code == code).first():
            continue                                     # 已存在则跳过，不视为错误
        cell = lambda i: (row[i] if len(row) > i else None)
        pending.append(Material(
            material_code=code, material_name=name,
            category=_text(cell(2)) or "辅料", spec=_text(cell(3)),
            unit=_text(cell(4)) or "个", default_color_no=_text(cell(5)),
            safety_stock=_num(cell(6), "安全库存", idx, errors),
            min_order_qty=_num(cell(7), "最小批量", idx, errors),
            status=_bool_text(cell(8), True), remark=_text(cell(9)),
        ))
    _raise_if_errors(errors)
    if not pending:
        return success({"imported": 0}, message="没有可导入的新物料（编码可能已存在）")
    db.add_all(pending)
    db.commit()
    return success({"imported": len(pending)}, message=f"成功导入 {len(pending)} 条物料")


# ==================== 导入：供应商 ====================

@router.post("/import/suppliers")
async def import_suppliers(file: UploadFile = File(...), db: Session = Depends(get_db),
                           _=Depends(require_permissions("basic:supplier:add"))):
    ws = await _read_sheet(file)
    _check_row_limit(ws)
    errors, pending, seen = [], [], set()
    for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not row or (not _text(row[0]) and not _text(row[1] if len(row) > 1 else None)):
            continue
        code = _text(row[0])
        name = _text(row[1]) if len(row) > 1 else ""
        if not code:
            errors.append({"row": idx, "msg": "供应商编码不能为空"})
            continue
        if not name:
            errors.append({"row": idx, "msg": "供应商名称不能为空"})
            continue
        if code in seen:
            errors.append({"row": idx, "msg": f"供应商编码「{code}」在本文件中重复"})
            continue
        seen.add(code)
        if db.query(Supplier).filter(Supplier.supplier_code == code).first():
            continue
        cell = lambda i: (row[i] if len(row) > i else None)
        days = _num(cell(6), "交货天数", idx, errors)
        pending.append(Supplier(
            supplier_code=code, supplier_name=name,
            contact=_text(cell(2)), phone=_text(cell(3)), address=_text(cell(4)),
            payment_term=_text(cell(5)), lead_time_days=int(days),
            status=_bool_text(cell(7), True), remark=_text(cell(8)),
        ))
    _raise_if_errors(errors)
    if not pending:
        return success({"imported": 0}, message="没有可导入的新供应商（编码可能已存在）")
    db.add_all(pending)
    db.commit()
    return success({"imported": len(pending)}, message=f"成功导入 {len(pending)} 条供应商")


# ==================== 导入：库存（期初/补录） ====================

@router.post("/import/inventory")
async def import_inventory(file: UploadFile = File(...), db: Session = Depends(get_db),
                           _=Depends(require_permissions("inventory:adjust"))):
    ws = await _read_sheet(file)
    _check_row_limit(ws)
    mats = {m.material_code: m for m in db.query(Material).all()}
    whs = {w.warehouse_code: w for w in db.query(Warehouse).all()}
    errors, tasks = [], []
    for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not row or not _text(row[0]):
            continue
        code, wh_code = _text(row[0]), _text(row[1]) if len(row) > 1 else ""
        material, warehouse = mats.get(code), whs.get(wh_code)
        if not material:
            errors.append({"row": idx, "msg": f"物料编码「{code}」不存在"})
        if not wh_code:
            errors.append({"row": idx, "msg": "仓库编码不能为空"})
        elif not warehouse:
            errors.append({"row": idx, "msg": f"仓库编码「{wh_code}」不存在"})
        qty = _num(row[2] if len(row) > 2 else None, "数量", idx, errors)
        if qty <= 0:
            errors.append({"row": idx, "msg": "数量必须大于 0"})
        if material and warehouse and qty > 0:
            tasks.append((material.id, warehouse.id, qty))
    _raise_if_errors(errors)
    if not tasks:
        return success({"imported": 0}, message="没有可导入的库存数据")
    try:
        for material_id, warehouse_id, qty in tasks:
            post_inbound(db, material_id=material_id, warehouse_id=warehouse_id, qty=qty,
                         txn_type="其他入库", ref_type="Excel导入", operator="Excel导入")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return success({"imported": len(tasks)}, message=f"成功导入 {len(tasks)} 行库存（其他入库）")
