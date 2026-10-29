"""报销单接口：下拉数据 / 票据识别 / 保存 / 修改 / 详情 / 列表 / 作废 / 原件 / 删除。

流程说明：
1. `POST /rmb-bills/recognize` 上传票据并调用大模型识别，识别结果与文件信息
   以 token 形式暂存（uploads/rmb/tmp/{token}.json），前端核对后再保存；
2. `POST /rmb-bills/save` 在事务内取当日流水号生成 BX-YYYYMMDD-NNNN 并落库，
   报销单进入「待判读 / 未判读」；发票号与票据文件哈希重复都会被拒绝；
3. 报销人（无制单权限）只能为本人报销，只能看到/操作本人的报销单；
   制单员、复核员、管理员可查看全部。

服务层（invoice_ai 等）由同事并行开发，**一律在函数内部延迟导入**：
这样即使服务层尚未就绪，本模块的只读接口（meta/列表/详情）也能独立工作。
"""
import json

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permissions
from app.api.v1.reimburse._common import (
    APPROVAL_NONE,
    APPROVAL_PASSED,
    APPROVAL_RANK_LABELS,
    APPROVAL_REJECTED,
    APPROVER_LEVELS,
    CHECKABLE_STATUS,
    COMPLIANCE_UNTESTED,
    DELETABLE_STATUS,
    EDITABLE_STATUS,
    RESULT_CHOICES,
    SCOPE_ALL,
    SCOPE_DEPT,
    SCOPE_SELF,
    STATUS_CHECK_FAILED,
    STATUS_VOID,
    STATUS_VOUCHER_DONE,
    STATUS_WAIT_CHECK,
    STATUS_WAIT_CONFIRM,
    STATUS_WAIT_VOUCHER,
    VOID_PERM_CODE,
    approver_options,
    bill_in_scope,
    bill_log_path,
    bill_logs,
    bill_row,
    can_approve,
    can_choose_employee,
    can_view_all,
    check_brief,
    ensure_bill_visible,
    ensure_can_void,
    has_perm,
    invoice_row,
    is_bill_owner,
    latest_check,
    load_bill_maps,
    load_recognized,
    money_float,
    my_employee,
    next_bill_no,
    now,
    parse_day,
    parse_day_optional,
    parse_int,
    required_approval_rank,
    user_approval_rank,
    user_data_scope,
    parse_money,
    remove_recognized,
    remove_ticket,
    safe_filename,
    save_recognized,
    save_ticket,
    sys_params,
    ticket_media_type,
    today_str,
    visible_bill_query,
    write_log,
    begin_immediate,
)
from app.core.database import get_db
from app.core.exceptions import BizException, PermissionException
from app.crud.crud_base import apply_ordering
from app.models.rbac import User
from app.models.reimburse import (
    RmbCityLevel,
    RmbComplianceCheck,
    RmbComplianceIssue,
    RmbEmployee,
    RmbExpenseType,
    RmbInvoice,
    RmbReimbursement,
    RmbSettlementMethod,
    RmbVoucher,
)
from app.schemas.reimburse import (
    BillApproveIn,
    BillVoidIn,
    InvoiceIn,
    ReasonSuggestIn,
    ReimburseCreate,
    ReimburseUpdate,
)
from app.services import file_store
from app.utils.response import page_result, success

router = APIRouter(prefix="/rmb-bills", tags=["报销单"])

#: 作废/删除的权限码：`reimburse:bill:delete` 是作废专用权限（单据名称即「报销单-作废」），
#: `reimburse:bill:edit` 也接受 —— 报销人只有填写/修改权，但制度要求他能作废自己的不合规单据。
#: 两者都是「满足其一即可」，再在 _ensure_can_void 里按本人/他人区分范围。
BILL_VOID_PERMS = ("reimburse:bill:delete", "reimburse:bill:edit")


def _loose_int(value) -> int | None:
    """宽松解析可选整数：空串/None/非法值一律返回 None。

    用于 multipart 表单里的可选上下文字段。这些字段只是给大模型识别时参考用的，
    前端未填写时会传空串（如 expense_type_id=""）。若把它们声明成 int 类型注解，
    FastAPI 会在进入函数前就因 "unable to parse string as an integer" 报 422，
    把整次票据识别打回；这里容错处理，识别流程不受影响。
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _loose_float(value) -> float | None:
    """宽松解析可选浮点数：空串/None/非法值一律返回 None（同上，用于识别上下文）。"""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _ensure_can_void(db: Session, user: User, bill: RmbReimbursement) -> None:
    """作废的二次校验：统一委托 _common.ensure_can_void。

    规则见 ensure_can_void：有作废权限可操作任意可见单；其余报销人仅限本人单据，
    且已审批通过的单据不允许报销人自行作废（须由管理岗撤回审批结果）。
    """
    ensure_can_void(db, user, bill)

#: rmb_invoice 中可由前端票据表单填充的列（id/关联字段/审计字段由服务端维护）
_INVOICE_COLUMNS = {c.name for c in RmbInvoice.__table__.columns} - {
    "id", "reimbursement_id", "created_by", "created_at",
}


# ==================== 内部辅助 ====================
def _blank_invoice() -> dict:
    """识别失败时返回的空票据结构，保证前端表单渲染不因字段缺失而报错。"""
    data = InvoiceIn().model_dump()
    data["items"] = []
    return data


def _invoice_payload(raw: dict | None) -> dict:
    """校验并规范化前端提交的票据字段，只返回「前端实际提交过」的字段。

    只覆盖传了的字段（而不是用默认值清空），这样编辑报销单时前端可以只改金额等单项。
    items 以数组提交，入库前序列化为 items_json。
    """
    if not raw:
        return {}
    try:
        model = InvoiceIn.model_validate(raw)
    except Exception:  # noqa: BLE001 - pydantic 校验失败统一转中文业务提示
        raise BizException("票据信息格式不正确，请检查金额、晚数等字段")
    fields = set(model.model_fields_set) - {"remark"}
    if not fields:
        return {}
    data = model.model_dump(include=fields)
    if "items" in data:
        items = data.pop("items") or []
        if not isinstance(items, list):
            raise BizException("票据明细格式不正确")
        data["items_json"] = json.dumps(items, ensure_ascii=False)
    return {k: v for k, v in data.items() if k in _INVOICE_COLUMNS}


def _normalize_invoice_text(data: dict) -> dict:
    """票据文本字段去首尾空格、空串转 None（invoice_number 空串会违反唯一索引）。"""
    for key in ("document_type", "invoice_code", "issue_date", "buyer_name", "buyer_tax_id",
                "seller_name", "seller_tax_id", "tax_rate", "total_amount_cn", "passenger_name",
                "travel_from", "travel_to", "travel_date", "checkin_date", "checkout_date",
                "consume_city", "original_filename", "llm_model"):
        if key in data:
            data[key] = (str(data[key]).strip() if data[key] is not None else "") or None
    if "invoice_number" in data:
        number = str(data["invoice_number"] or "").strip()
        data["invoice_number"] = number or None
    if "file_hash" in data:
        digest = str(data["file_hash"] or "").strip().lower()
        data["file_hash"] = digest or None
    if "items_json" in data and not data["items_json"]:
        data["items_json"] = "[]"
    return data


def _check_invoice_number_duplicate(db: Session, number: str | None, exclude_bill_id: int | None = None) -> None:
    """同一张有号码的发票不得被多张报销单使用（制度第十一条 / R09）。"""
    number = (number or "").strip()
    if not number:
        return
    rows = (
        db.query(RmbInvoice, RmbReimbursement)
        .join(RmbReimbursement, RmbReimbursement.id == RmbInvoice.reimbursement_id)
        .filter(RmbInvoice.invoice_number == number)
        .all()
    )
    for _invoice, bill in rows:
        if exclude_bill_id and bill.id == exclude_bill_id:
            continue
        raise BizException(
            f"该发票已于 {bill.bill_date} 在报销单 {bill.bill_no} 中报销，禁止重复报销"
        )


def _check_file_hash_duplicate(db: Session, file_hash: str | None, exclude_bill_id: int | None = None) -> None:
    """同一份票据文件不得被反复使用（invoice 表 file_hash 唯一索引的友好提示）。"""
    digest = (file_hash or "").strip()
    if not digest:
        return
    row = db.query(RmbInvoice).filter(RmbInvoice.file_hash == digest).first()
    if row and (not exclude_bill_id or row.reimbursement_id != exclude_bill_id):
        raise BizException("该票据文件已被使用过，禁止重复报销")


def _resolve_employee(db: Session, user: User, requested_id: int | None) -> RmbEmployee:
    """确定本单报销人：有制单权限的人可选任意员工，其余角色只能为本人报销。"""
    mine = my_employee(db, user)
    if can_choose_employee(db, user):
        if requested_id:
            employee = db.get(RmbEmployee, requested_id)
            if not employee:
                raise BizException("所选报销人不存在")
            return employee
        if mine:
            return mine
        raise BizException("请选择报销人")
    if not mine:
        raise BizException("当前账号未关联员工档案，无法提交报销单，请联系管理员")
    if requested_id and requested_id != mine.id:
        raise BizException("报销人只能为本人提交报销单")
    return mine


def _resolve_expense_type(db: Session, expense_type_id: int | None) -> RmbExpenseType:
    if not expense_type_id:
        raise BizException("请选择费用类型")
    expense_type = db.get(RmbExpenseType, expense_type_id)
    if not expense_type:
        raise BizException("费用类型不存在")
    if not expense_type.is_active:
        raise BizException(f"费用类型「{expense_type.name}」已停用，请选择其他类型")
    return expense_type


def _resolve_settlement(db: Session, settlement_method_id: int | None) -> RmbSettlementMethod | None:
    if not settlement_method_id:
        return None
    settlement = db.get(RmbSettlementMethod, settlement_method_id)
    if not settlement:
        raise BizException("结算方式不存在")
    return settlement


def _resolve_amount(raw_amount, invoice_data: dict, has_invoice: int) -> float:
    """确定报销金额：附发票时缺省取票据价税合计，未附发票时必须手工填写且大于 0。"""
    raw = raw_amount
    if (raw is None or raw == "") and invoice_data.get("total_amount") not in (None, ""):
        raw = invoice_data.get("total_amount")
    if raw is None or raw == "":
        if has_invoice:
            raise BizException("请填写报销金额（有票据时默认取票据价税合计）")
        raise BizException("未附发票时必须手工填写报销金额")
    amount = parse_money(raw, "报销金额")
    if amount <= 0:
        raise BizException("报销金额必须大于 0")
    return money_float(amount)


def _diff_invoice(ai_invoice: dict, final_invoice: dict) -> str:
    """对比 AI 原识别值与人工确认值，返回给日志用的差异摘要。"""
    labels = {
        "document_type": "票据类型", "is_invoice": "是否发票", "invoice_code": "发票代码",
        "invoice_number": "发票号码", "issue_date": "开票日期", "buyer_name": "购买方",
        "seller_name": "销售方", "amount_without_tax": "不含税金额", "tax_amount": "税额",
        "total_amount": "价税合计", "passenger_name": "乘车人", "consume_city": "消费城市",
        "nights": "晚数", "travel_to": "到达地",
    }
    changes = []
    for key, label in labels.items():
        before = ai_invoice.get(key)
        after = final_invoice.get(key)
        if str(before or "") != str(after or ""):
            changes.append(f"{label}:{before or '空'}→{after or '空'}")
    return "；".join(changes)[:48] if changes else ""


def _bill_token_payload(db: Session, bill: RmbReimbursement) -> dict:
    """组装报销单的审计轨迹。"""
    return {
        "logs": bill_logs(db, bill.id),
    }


# ==================== 一、下拉数据 ====================
@router.get("/meta", summary="报销单下拉数据")
def bill_meta(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """填单页所需的全部下拉数据与当前登录人信息。

    `can_choose_employee=false` 时前端把报销人固定为 `current_employee`（本人）且只读。
    """
    from app.utils.response import success as _success

    maps = load_bill_maps(db)
    employees = [
        {
            "id": employee.id, "emp_no": employee.emp_no, "name": employee.name,
            "department_id": employee.department_id,
            "department_name": maps["departments"].get(employee.department_id, ""),
        }
        for employee in maps["employees"].values()
    ]
    employees.sort(key=lambda row: row["id"])
    departments = [{"id": dept_id, "name": name} for dept_id, name in sorted(maps["departments"].items())]
    expense_types = [
        {
            "id": item.id, "name": item.name, "subject_code": item.subject_code,
            "special_info": item.special_info or "无", "remark": item.remark or "",
            "sort_no": item.sort_no or 0,
        }
        for item in sorted(maps["expense_types"].values(), key=lambda row: (row.sort_no or 0, row.id))
        if item.is_active
    ]
    settlements = [
        {"id": item.id, "name": item.name, "subject_code": item.subject_code}
        for item in sorted(maps["settlements"].values(), key=lambda row: row.id)
        if item.is_active
    ]
    cities = [
        {"id": row.id, "city_name": row.city_name, "city_level": row.city_level,
         "lodging_limit": row.lodging_limit or 0}
        for row in db.query(RmbCityLevel).order_by(RmbCityLevel.id).all()
    ]
    mine = my_employee(db, user)
    current_employee = None
    if mine:
        current_employee = {
            "id": mine.id, "emp_no": mine.emp_no, "name": mine.name,
            "department_id": mine.department_id,
            "department_name": maps["departments"].get(mine.department_id, ""),
        }
    return _success({
        "expense_types": expense_types,
        "settlement_methods": settlements,
        "departments": departments,
        "employees": employees,
        "city_levels": cities,
        "params": sys_params(db),
        "today": today_str(),
        "current_employee": current_employee,
        "can_choose_employee": can_choose_employee(db, user),
        "approver_levels": list(APPROVER_LEVELS),
        # 审批人下拉：拥有审批权限的用户及其审批层级，选择后会自动带出「审批层级」
        "approvers": approver_options(db),
        "statuses": ["待判读", "判读不合规", "待确认", "待制证", "已生成凭证", "已作废"],
        "compliance_results": [COMPLIANCE_UNTESTED, *RESULT_CHOICES],
        "checkable_statuses": list(CHECKABLE_STATUS),
        "editable_statuses": list(EDITABLE_STATUS),
    })


# ==================== 二、票据识别（上传 + AI） ====================
@router.post("/recognize", summary="上传票据并 AI 识别")
async def recognize_bill(
    request: Request,
    file: UploadFile = File(...),
    # 注意：这里全部按字符串接收再手工解析，不直接用 int/float 类型注解。
    # multipart 表单里前端未填的可选字段会传空串（如 expense_type_id=""），
    # 直接声明为 int | None 会让 FastAPI 在进入函数前就报 422
    # （"Input should be a valid integer, unable to parse string as an integer"），
    # 导致整张票据识别失败。改为字符串接收后按「空值即未提供」处理，容错更好。
    employee_id: str | None = Form(None),
    expense_type_id: str | None = Form(None),
    occur_date: str | None = Form(None),
    amount: str | None = Form(None),
    has_invoice: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:bill:add")),
):
    """上传票据 → 归档原件 → 调用大模型识别 → 返回 token 供保存阶段使用。

    - 识别成功：返回票据字段与 warnings；
    - 识别失败：仍然返回 token（含已归档文件）与空票据结构 + `recognize_ok=false`，
      前端据此提示「可重试或跳过识别手工填写」，不会因为识别失败就丢掉已上传的文件；
    - 文件类型/大小不合规则直接拒绝。
    """
    content = await file.read()
    filename = file.filename or ""
    content_type = file.content_type or ""
    rel_path, file_hash, ext = save_ticket(content, filename, content_type)
    original_name = safe_filename(filename)

    # 表单字段是「供识别时参考」的可选上下文，解析失败不应阻断识别流程，
    # 因此这里用宽松解析：非法值一律按未提供（None）处理，只在成功时传入 token。
    employee_id_val = _loose_int(employee_id)
    expense_type_id_val = _loose_int(expense_type_id)
    amount_val = _loose_float(amount)
    has_invoice_val = _loose_int(has_invoice)
    if has_invoice_val is None:
        has_invoice_val = 1
    occur_date_val = (occur_date or "").strip() or None

    warnings: list[str] = []
    invoice_data: dict = {}
    model_name = ""
    elapsed = 0.0
    raw_text = ""
    recognize_mode = ""
    recognize_ok = True
    error_message = ""

    # 1) 文件哈希查重：同一份票据文件被多次使用属高风险，先提示（保存阶段会再次拒绝）
    try:
        existed = db.query(RmbInvoice).filter(RmbInvoice.file_hash == file_hash).first()
        if existed:
            warnings.append("该票据文件已被使用过，疑似重复报销")
    except Exception:  # noqa: BLE001 - 查重失败不应阻断识别
        db.rollback()

    # 2) 调用识别服务（延迟导入：服务层由同事并行开发）
    try:
        from app.services import invoice_ai

        result = invoice_ai.recognize_invoice(content, filename, content_type) or {}
        invoice_data = dict(result)
        model_name = str(result.get("model") or "")
        elapsed = float(result.get("elapsed") or 0)
        raw_text = str(result.get("raw_text") or "")
        # 识别通道：image（图片）/ pdf_text（PDF 文本层）/ pdf_render（扫描件渲染）
        recognize_mode = str(result.get("recognize_mode") or "")
        warnings.extend(str(w) for w in (result.get("warnings") or []) if str(w).strip())
    except BizException as exc:
        recognize_ok = False
        error_message = exc.message
    except Exception as exc:  # noqa: BLE001 - 大模型/网络/解析异常统一转中文提示
        recognize_ok = False
        error_message = f"票据识别失败：{exc}"
    if not recognize_ok:
        invoice_data = {}
        warnings.append(f"{error_message}。可重试识别，或跳过识别手工填写票据信息。")

    final_invoice = _blank_invoice()
    for key, value in invoice_data.items():
        if key in final_invoice and value is not None:
            final_invoice[key] = value
    if not isinstance(final_invoice.get("items"), list):
        final_invoice["items"] = []

    # 3) 暂存识别结果：保存阶段凭 token 取回可信的文件路径与识别原始值
    token_payload = {
        "file": {
            "path": rel_path, "hash": file_hash, "ext": ext, "size": len(content),
            "original_filename": original_name, "content_type": content_type,
        },
        "form": {
            "employee_id": employee_id_val, "expense_type_id": expense_type_id_val,
            "occur_date": occur_date_val, "amount": amount_val,
            "has_invoice": has_invoice_val,
        },
        "invoice": final_invoice,
        "raw_text": raw_text,
        "model": model_name,
        "elapsed": elapsed,
        "recognize_mode": recognize_mode,
        "warnings": warnings,
        "recognize_ok": recognize_ok,
        "uploaded_by": user.username,
    }
    token = save_recognized(token_payload)

    # 识别通道的中文说明，写进审计日志，便于事后判断是否走了 PDF 文本解析
    mode_label = {
        "image": "图片识别",
        "pdf_text": "PDF文本解析",
        "pdf_render": "PDF渲染识别",
    }.get(recognize_mode, "")
    write_log(
        db, user, "识别票据", "/api/v1/rmb-bills/recognize",
        detail=f"{original_name}；{mode_label + '；' if mode_label else ''}"
               f"模型{model_name or '未知'}；耗时{elapsed:.1f}s；"
               f"{'成功' if recognize_ok else '失败'}",
        request=request,
    )
    return success({
        "token": token,
        "warnings": warnings,
        "invoice": final_invoice,
        "recognize_ok": recognize_ok,
        "model": model_name,
        "elapsed": elapsed,
        "recognize_mode": recognize_mode,
        "has_file": True,
        "original_filename": original_name,
        "file_hash": file_hash,
    }, message="识别完成，请核对票据信息" if recognize_ok else "识别未完成，可跳过识别手工填写")


# ==================== 二之二、AI 生成报销事由 ====================
@router.post("/suggest-reason", summary="AI 生成报销事由")
def suggest_reason(
    data: ReasonSuggestIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:bill:add")),
):
    """根据已填写信息与票据识别结果，调用文本大模型生成一段报销事由（仅建议，可修改）。

    - 只做文案生成，不做业务校验，生成结果不会自动保存；
    - 输入可为空（信息少时返回概括性事由），但费用类型越完整生成越贴切；
    - 大模型调用失败抛中文提示，报销人可继续手工填写。
    """
    maps = load_bill_maps(db)
    expense = maps["expense_types"].get(data.expense_type_id) if data.expense_type_id else None
    context = {
        "expense_type_name": expense.name if expense else "",
        "occur_date": (data.occur_date or "").strip(),
        "amount": data.amount,
        "has_invoice": data.has_invoice,
        "travel_city": (data.travel_city or "").strip(),
        "travel_start": (data.travel_start or "").strip(),
        "travel_end": (data.travel_end or "").strip(),
        "nights": data.nights,
        "guest_company": (data.guest_company or "").strip(),
        "guest_count": data.guest_count,
        "invoice": data.invoice or {},
    }
    # 服务层延迟导入：与 recognize 一致，模型未就绪不影响其他接口
    from app.services import reason_ai
    from app.services.llm_client_new import LLMError

    try:
        result = reason_ai.suggest_reason(context)
    except LLMError as exc:
        raise BizException(f"AI 生成报销事由失败：{exc}")
    return success({
        "reason": result.get("reason", ""),
        "model": result.get("model", ""),
    }, message="已生成报销事由，可自行修改")


# ==================== 三、保存报销单 ====================
@router.post("/save", summary="保存报销单")
def save_bill(
    data: ReimburseCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:bill:add")),
):
    """保存报销单 + 票据（同一事务）。返回 {id, bill_no}。"""
    has_invoice = 1 if (data.has_invoice is None or int(data.has_invoice)) else 0
    employee = _resolve_employee(db, user, data.employee_id)
    expense_type = _resolve_expense_type(db, data.expense_type_id)
    settlement = _resolve_settlement(db, data.settlement_method_id)
    occur_date = parse_day(data.occur_date, "费用发生日期")

    # 识别暂存数据：文件路径/哈希以 token 为准，不接受前端直接指定磁盘路径
    token_payload: dict = {}
    if data.token:
        token_payload = load_recognized(data.token)

    invoice_payload = _invoice_payload(data.invoice.model_dump(exclude_unset=True) if data.invoice else None)
    if token_payload:
        file_info = token_payload.get("file") or {}
        invoice_payload.setdefault("file_path", file_info.get("path") or "")
        invoice_payload.setdefault("file_hash", file_info.get("hash") or "")
        invoice_payload.setdefault("original_filename", file_info.get("original_filename") or "")
        if token_payload.get("model"):
            invoice_payload.setdefault("llm_model", token_payload.get("model"))
        if token_payload.get("raw_text"):
            invoice_payload.setdefault("llm_raw_json", token_payload.get("raw_text"))
        # 票据字段缺省回填识别结果，前端只提交改动项即可
        for key, value in (token_payload.get("invoice") or {}).items():
            if key in _INVOICE_COLUMNS and key not in invoice_payload and value not in (None, ""):
                invoice_payload[key] = value
    invoice_payload = _normalize_invoice_text(invoice_payload)

    if has_invoice:
        if not invoice_payload.get("file_path") and not invoice_payload.get("invoice_number"):
            raise BizException("附发票时请先上传票据文件")
    amount = _resolve_amount(data.amount, invoice_payload, has_invoice)

    # 业务校验在写事务之前完成；随后 BEGIN IMMEDIATE 取写锁，避免并发下报销单号重号
    try:
        begin_immediate(db)
        _check_invoice_number_duplicate(db, invoice_payload.get("invoice_number"))
        _check_file_hash_duplicate(db, invoice_payload.get("file_hash"))
        bill_no = next_bill_no(db, today_str())
        bill = RmbReimbursement(
            bill_no=bill_no,
            bill_date=today_str(),
            employee_id=employee.id,
            department_id=data.department_id or employee.department_id,
            expense_type_id=expense_type.id,
            reason=(data.reason or "").strip(),
            occur_date=occur_date,
            amount=amount,
            has_invoice=has_invoice,
            approver_name=(data.approver_name or "").strip(),
            approver_level=(data.approver_level or "").strip(),
            travel_city=(data.travel_city or "").strip(),
            travel_start=parse_day_optional(data.travel_start, "出差开始日期"),
            travel_end=parse_day_optional(data.travel_end, "出差结束日期"),
            nights=parse_int(data.nights, "住宿晚数"),
            guest_company=(data.guest_company or "").strip(),
            guest_count=parse_int(data.guest_count, "陪同人数"),
            special_approver=(data.special_approver or "").strip(),
            explanation=(data.explanation or "").strip(),
            settlement_method_id=settlement.id if settlement else None,
            status=STATUS_WAIT_CHECK,
            compliance_result=COMPLIANCE_UNTESTED,
            created_by=user.username,
        )
        db.add(bill)
        db.flush()
        if invoice_payload:
            db.add(RmbInvoice(reimbursement_id=bill.id, created_by=user.username,
                              **invoice_payload))
        db.commit()
    except Exception:
        db.rollback()
        raise

    # 事务提交后再写日志，避免日志把业务改动一起提交
    ai_invoice = (token_payload.get("invoice") or {}) if token_payload else {}
    diff = _diff_invoice(ai_invoice, invoice_payload) if ai_invoice else ""
    write_log(
        db, user, "确认报销单", bill_log_path(bill.id),
        detail=f"{bill.bill_no}；{expense_type.name}；{amount:.2f}元"
               + (f"；AI识别修正：{diff}" if diff else ""),
        request=request,
    )
    if data.token:
        remove_recognized(data.token)
    return success({"id": bill.id, "bill_no": bill.bill_no},
                   message=f"报销单 {bill.bill_no} 已保存，请提交 AI 合规判读")


# ==================== 四、列表与详情 ====================
@router.get("", summary="报销单列表")
def list_bills(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
    keyword: str | None = None,
    status: str | None = None,
    expense_type_id: int | None = None,
    employee_id: int | None = None,
    compliance_result: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:bill:list")),
):
    """报销单分页列表。普通报销人只能看到本人的单据。"""
    query = visible_bill_query(db, user, db.query(RmbReimbursement))
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(or_(
            RmbReimbursement.bill_no.like(like),
            RmbReimbursement.reason.like(like),
            RmbReimbursement.approver_name.like(like),
        ))
    if status:
        query = query.filter(RmbReimbursement.status == status)
    if compliance_result:
        query = query.filter(RmbReimbursement.compliance_result == compliance_result)
    if expense_type_id:
        query = query.filter(RmbReimbursement.expense_type_id == expense_type_id)
    if employee_id:
        query = query.filter(RmbReimbursement.employee_id == employee_id)
    if date_from:
        query = query.filter(RmbReimbursement.bill_date >= parse_day(date_from, "开始日期"))
    if date_to:
        query = query.filter(RmbReimbursement.bill_date <= parse_day(date_to, "结束日期"))

    total = query.count()
    rows = (
        apply_ordering(query, RmbReimbursement, sort_by, sort_order)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    maps = load_bill_maps(db)
    # 作废权限只与当前登录人有关，循环外算一次；「是否本人单据/是否已审批」逐行判断
    has_void_perm = has_perm(db, user, VOID_PERM_CODE)
    data = []
    for bill in rows:
        row = bill_row(bill, maps)
        check = latest_check(db, bill.id)
        row["latest_check"] = check_brief(check)
        approved = (bill.approval_status or "") == APPROVAL_PASSED
        row["can_void"] = (
            bill.status not in (STATUS_VOID, STATUS_VOUCHER_DONE)
            and (has_void_perm or (is_bill_owner(bill, user) and not approved))
        )
        data.append(row)
    return success(page_result(data, total))


@router.get("/workbench", summary="报销工作台")
def reimburse_workbench(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:bill:list")),
):
    """报销工作台：按当前位置返回 KPI、待办与最近单据。

    注意：该路由必须注册在 `/{bill_id}` 之前，否则 "workbench" 会被
    当作 bill_id 解析而报错。

    与采购库存看板（`/reports/workbench`）的区别：那个看板面向采购/库存岗位，
    数据源是采购单据与库存；本接口纯粹面向报销流程，按**数据范围**统计，
    所以部门负责人只看到本部门数字，普通员工只看到本人数字。
    """
    from sqlalchemy import func as sa_func

    today = today_str()
    params = sys_params(db)
    base = visible_bill_query(db, user, db.query(RmbReimbursement))
    scope = user_data_scope(db, user)

    # ---- 统计：按状态分组 ----
    status_counts = dict(
        base.with_entities(RmbReimbursement.status, sa_func.count())
        .group_by(RmbReimbursement.status)
        .all()
    )
    total_count = sum(status_counts.values())
    total_amount = float(
        base.with_entities(sa_func.coalesce(sa_func.sum(RmbReimbursement.amount), 0))
        .scalar() or 0
    )

    # ---- 我的（本人提交的）报销单 ----
    my_query = db.query(RmbReimbursement).filter(
        or_(
            RmbReimbursement.created_by == user.username,
            RmbReimbursement.employee_id == (getattr(user, "employee_id", None) or -1),
        )
    )
    my_counts = dict(
        my_query.with_entities(RmbReimbursement.status, sa_func.count())
        .group_by(RmbReimbursement.status)
        .all()
    )

    # ---- 角色能力判定 ----
    can_approve_perm = has_perm(db, user, "reimburse:bill:approve")
    can_make = has_perm(db, user, "reimburse:voucher:make")
    can_review = has_perm(db, user, "reimburse:voucher:review")

    # 待我审批：状态非终态、未审批、在数据范围内、层级足够、且不是本人单据
    pending_approve = 0
    if can_approve_perm:
        my_rank = user_approval_rank(db, user)
        cand = base.filter(
            RmbReimbursement.status.notin_((STATUS_VOID, STATUS_VOUCHER_DONE)),
            RmbReimbursement.approval_status == APPROVAL_NONE,
        ).all()
        for b in cand:
            if is_bill_owner(b, user):
                continue
            if user_approval_rank(db, user) >= required_approval_rank(b.amount, params):
                pending_approve += 1

    # 待制证 / 待复核
    pending_voucher = int(status_counts.get(STATUS_WAIT_VOUCHER, 0)) if can_make else 0
    pending_review = 0
    if can_review:
        pending_review = (
            db.query(RmbVoucher)
            .filter(RmbVoucher.status == "未复核")
            .count()
        )

    # ---- KPI 卡片（按角色能力裁剪，不展示没权限操作的数字）----
    kpis = []
    if can_approve_perm:
        kpis.append({"label": "待我审批", "value": pending_approve,
                     "icon": "Stamp", "color": "#e6a23c", "to": "/reimburse/list"})
    if can_make:
        kpis.append({"label": "待制证", "value": pending_voucher,
                     "icon": "Tickets", "color": "#409eff", "to": "/reimburse/voucher/pending"})
    if can_review:
        kpis.append({"label": "待复核凭证", "value": pending_review,
                     "icon": "Finished", "color": "#67c23a", "to": "/reimburse/voucher/review"})
    # 所有报销人都关心的「我提交的」统计
    kpis.append({"label": "我提交的报销单",
                 "value": sum(my_counts.values()), "icon": "Document",
                 "color": "#909399", "to": "/reimburse/list"})
    kpis.append({"label": "判读不合规",
                 "value": int(status_counts.get(STATUS_CHECK_FAILED, 0)),
                 "icon": "Warning", "color": "#f56c6c", "to": "/reimburse/list"})
    kpis.append({"label": "已生成凭证",
                 "value": int(status_counts.get(STATUS_VOUCHER_DONE, 0)),
                 "icon": "CircleCheck", "color": "#67c23a", "to": "/reimburse/voucher/list"})

    # ---- 待办清单 ----
    todos = []
    if pending_approve:
        todos.append({"title": "待我审批", "count": pending_approve, "to": "/reimburse/list"})
    if pending_voucher:
        todos.append({"title": "待制证", "count": pending_voucher,
                      "to": "/reimburse/voucher/pending"})
    if pending_review:
        todos.append({"title": "待复核", "count": pending_review,
                      "to": "/reimburse/voucher/review"})
    for cnt, label, status in (
        (status_counts.get(STATUS_WAIT_CHECK, 0), "待判读", STATUS_WAIT_CHECK),
        (status_counts.get(STATUS_WAIT_CONFIRM, 0), "待确认", STATUS_WAIT_CONFIRM),
        (status_counts.get(STATUS_CHECK_FAILED, 0), "判读不合规", STATUS_CHECK_FAILED),
    ):
        if cnt:
            todos.append({"title": label, "count": int(cnt),
                          "to": f"/reimburse/list?status={status}"})

    # ---- 最近单据（按数据范围，取最近 6 张）----
    maps = load_bill_maps(db)
    recent_rows = base.order_by(RmbReimbursement.id.desc()).limit(6).all()
    recent = []
    for b in recent_rows:
        row = bill_row(b, maps)
        recent.append({
            "id": row["id"],
            "bill_no": row["bill_no"],
            "employee_name": row["employee_name"],
            "department_name": row["department_name"],
            "expense_type_name": row["expense_type_name"],
            "amount": row["amount"],
            "status": row["status"],
            "compliance_result": row["compliance_result"],
            "occur_date": row["occur_date"],
        })

    # ---- 费用类型分布（本月）----
    month_prefix = today[:7]
    type_rows = (
        base.filter(RmbReimbursement.occur_date.like(f"{month_prefix}%"))
        .with_entities(RmbReimbursement.expense_type_id, sa_func.count(),
                       sa_func.coalesce(sa_func.sum(RmbReimbursement.amount), 0))
        .group_by(RmbReimbursement.expense_type_id)
        .all()
    )
    type_names = {e.id: e.name for e in db.query(RmbExpenseType).all()}
    by_type = [
        {"name": type_names.get(tid, "其他"), "count": int(cnt), "amount": float(amt)}
        for tid, cnt, amt in type_rows
    ]
    by_type.sort(key=lambda x: x["amount"], reverse=True)

    # 角色标签：取最贴近报销职责的一个
    role_label = "报销人"
    if can_review:
        role_label = "财务复核"
    if can_make:
        role_label = "财务制单"
    if can_approve_perm and user_approval_rank(db, user) >= 3:
        role_label = "总经理"
    elif can_approve_perm:
        role_label = "审批人"
    if any(r.role_code == "admin" for r in user.roles):
        role_label = "系统管理员"

    return success({
        "today": today,
        "real_name": user.real_name or user.username,
        "role_label": role_label,
        "data_scope": scope,
        "kpis": kpis,
        "todos": todos,
        "recent": recent,
        "by_type": by_type,
        "summary": {
            "total_count": total_count,
            "total_amount": round(total_amount, 2),
            "month_amount": round(sum(x["amount"] for x in by_type), 2),
        },
    })


@router.get("/{bill_id}", summary="报销单详情")
def bill_detail(
    bill_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:bill:list")),
):
    """报销单详情：报销信息 + 票据 + 最近一次判读摘要 + 凭证 + 审计轨迹。"""
    bill = db.get(RmbReimbursement, bill_id)
    if not bill:
        raise BizException("报销单不存在")
    ensure_bill_visible(db, user, bill)

    maps = load_bill_maps(db)
    data = bill_row(bill, maps)
    invoice = db.query(RmbInvoice).filter(RmbInvoice.reimbursement_id == bill.id).first()
    data["invoice"] = invoice_row(invoice)
    data["latest_check"] = check_brief(latest_check(db, bill.id))
    data["logs"] = _bill_token_payload(db, bill)["logs"]
    data["can_edit"] = (bill.status in EDITABLE_STATUS) and (
        can_view_all(db, user) or is_bill_owner(bill, user)
    )
    data["can_delete"] = (bill.status in DELETABLE_STATUS) and is_bill_owner(bill, user)
    data["can_check"] = bill.status in CHECKABLE_STATUS
    # 作废：状态非终态，且「有作废权限，或本人单据且尚未审批通过」
    has_void_perm = has_perm(db, user, VOID_PERM_CODE)
    approved = (bill.approval_status or "") == APPROVAL_PASSED
    data["can_void"] = (
        bill.status not in (STATUS_VOID, STATUS_VOUCHER_DONE)
        and (has_void_perm or (is_bill_owner(bill, user) and not approved))
    )
    if bill.status in (STATUS_VOID, STATUS_VOUCHER_DONE):
        data["void_blocked_reason"] = (
            "该报销单已作废" if bill.status == STATUS_VOID
            else "该报销单已生成凭证，不允许作废")
    elif not data["can_void"] and is_bill_owner(bill, user) and approved:
        data["void_blocked_reason"] = "该报销单已审批通过，报销人不能自行作废，请联系具备作废权限的管理人员处理"
    elif not data["can_void"] and not has_void_perm:
        data["void_blocked_reason"] = "作废他人报销单需要「报销单-作废」权限"
    else:
        data["void_blocked_reason"] = ""
    # 分级审批：能否审批本单（层级足、非本人、非终态、在数据范围内）
    params = sys_params(db)
    need_rank = required_approval_rank(bill.amount, params)
    has_approve_perm = has_perm(db, user, "reimburse:bill:approve")
    in_scope = bill_in_scope(db, user, bill)
    rank_ok = user_approval_rank(db, user) >= need_rank
    data["can_approve"] = (
        bill.status not in (STATUS_VOID, "已生成凭证")
        and has_approve_perm
        and not is_bill_owner(bill, user)
        and in_scope
        and rank_ok
    )
    data["required_approval_rank"] = need_rank
    data["required_approver_label"] = APPROVAL_RANK_LABELS.get(need_rank, "")
    data["my_approval_rank"] = user_approval_rank(db, user)
    # 数据范围：让前端能解释「为什么我不能审批这张单」
    scope = user_data_scope(db, user)
    data["data_scope"] = scope
    data["data_scope_label"] = {
        SCOPE_ALL: "全公司", SCOPE_DEPT: "本部门", SCOPE_SELF: "仅本人",
    }.get(scope, "仅本人")
    blocked = ""
    if has_approve_perm and not data["can_approve"]:
        if not in_scope:
            blocked = ("只能审批本部门的报销单" if scope == SCOPE_DEPT
                       else "该报销单不在您的数据范围内")
        elif not rank_ok:
            blocked = f"审批层级不足：须经「{APPROVAL_RANK_LABELS.get(need_rank, '')}」审批"
    data["approve_blocked_reason"] = blocked
    voucher = db.query(RmbVoucher).filter(RmbVoucher.reimbursement_id == bill.id).first()
    data["voucher"] = {
        "id": voucher.id, "voucher_code": voucher.voucher_code or "", "status": voucher.status or "",
        "maker": voucher.maker or "", "reviewer": voucher.reviewer or "",
        "total_debit": voucher.total_debit or 0,
    } if voucher else None
    # 平铺 voucher_id，供前端在「已生成凭证」状态下直接跳转，免去反查凭证列表
    data["voucher_id"] = voucher.id if voucher else None
    return success(data)


@router.get("/{bill_id}/invoice-file", summary="报销单票据原件")
def bill_invoice_file(
    bill_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:bill:list")),
):
    """返回票据原件（内联展示）。仅本人或有全局查看权限者可以访问，防止越权看他人票据。"""
    bill = db.get(RmbReimbursement, bill_id)
    if not bill:
        raise BizException("报销单不存在")
    ensure_bill_visible(db, user, bill)
    invoice = db.query(RmbInvoice).filter(RmbInvoice.reimbursement_id == bill.id).first()
    if invoice is None or not invoice.file_path:
        raise BizException("该报销单未留存票据原件")
    path = file_store.resolve(invoice.file_path)
    if not path:
        raise BizException("票据原件路径无效，请联系管理员")
    import os

    if not os.path.isfile(path):
        raise BizException("票据原件已丢失或被清理，请重新上传")
    return FileResponse(
        path,
        media_type=ticket_media_type(invoice.file_path),
        content_disposition_type="inline",
        filename=invoice.original_filename or os.path.basename(path),
    )


# ==================== 五、修改 / 作废 / 删除 ====================
@router.put("/{bill_id}", summary="修改报销单")
def update_bill(
    bill_id: int,
    data: ReimburseUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:bill:edit")),
):
    """修改报销单：仅 待判读 / 判读不合规 / 待确认 可改，改后回到「待判读 + 未判读」。"""
    bill = db.get(RmbReimbursement, bill_id)
    if not bill:
        raise BizException("报销单不存在")
    ensure_bill_visible(db, user, bill)
    if bill.status == STATUS_VOID:
        raise BizException("已作废的报销单不允许修改")
    if bill.status not in EDITABLE_STATUS:
        raise BizException(f"当前状态「{bill.status}」不允许修改，仅待判读/判读不合规/待确认可修改")

    fields = data.model_dump(exclude_unset=True)
    token_payload: dict = {}
    token = fields.pop("token", None)
    invoice_raw = fields.pop("invoice", None)
    if token:
        token_payload = load_recognized(token)

    # 报销人变更：只有制单权限的人可以改派
    employee = bill.employee_id and db.get(RmbEmployee, bill.employee_id)
    if "employee_id" in fields and fields["employee_id"]:
        employee = _resolve_employee(db, user, fields["employee_id"])
    if "expense_type_id" in fields and fields["expense_type_id"]:
        _resolve_expense_type(db, fields["expense_type_id"])
    if "settlement_method_id" in fields and fields["settlement_method_id"]:
        _resolve_settlement(db, fields["settlement_method_id"])
    if "occur_date" in fields:
        fields["occur_date"] = parse_day(fields["occur_date"], "费用发生日期")
    if "travel_start" in fields:
        fields["travel_start"] = parse_day_optional(fields["travel_start"], "出差开始日期")
    if "travel_end" in fields:
        fields["travel_end"] = parse_day_optional(fields["travel_end"], "出差结束日期")
    if "nights" in fields:
        fields["nights"] = parse_int(fields["nights"], "住宿晚数")
    if "guest_count" in fields:
        fields["guest_count"] = parse_int(fields["guest_count"], "陪同人数")
    if "has_invoice" in fields and fields["has_invoice"] is not None:
        fields["has_invoice"] = 1 if int(fields["has_invoice"]) else 0
    if "amount" in fields and fields["amount"] not in (None, ""):
        amount = parse_money(fields["amount"], "报销金额")
        if amount <= 0:
            raise BizException("报销金额必须大于 0")
        fields["amount"] = money_float(amount)
    if "reason" in fields:
        fields["reason"] = (fields["reason"] or "").strip()
    for key in ("approver_name", "approver_level", "special_approver", "explanation",
                "travel_city", "guest_company"):
        if key in fields:
            fields[key] = (fields[key] or "").strip()
    for key in ("employee_id", "department_id", "expense_type_id", "settlement_method_id"):
        if key in fields and not fields[key]:
            fields.pop(key)

    invoice_payload = _invoice_payload(invoice_raw)
    if token_payload:
        file_info = token_payload.get("file") or {}
        invoice_payload.setdefault("file_path", file_info.get("path") or "")
        invoice_payload.setdefault("file_hash", file_info.get("hash") or "")
        invoice_payload.setdefault("original_filename", file_info.get("original_filename") or "")
        if token_payload.get("model"):
            invoice_payload.setdefault("llm_model", token_payload.get("model"))
        if token_payload.get("raw_text"):
            invoice_payload.setdefault("llm_raw_json", token_payload.get("raw_text"))
    invoice_payload = _normalize_invoice_text(invoice_payload)

    invoice = db.query(RmbInvoice).filter(RmbInvoice.reimbursement_id == bill.id).first()
    if employee is not None and "department_id" not in fields:
        fields.setdefault("department_id", employee.department_id)

    try:
        begin_immediate(db)
        if invoice_payload.get("invoice_number"):
            _check_invoice_number_duplicate(db, invoice_payload["invoice_number"], exclude_bill_id=bill.id)
        if invoice_payload.get("file_hash"):
            _check_file_hash_duplicate(db, invoice_payload["file_hash"], exclude_bill_id=bill.id)
        for key, value in fields.items():
            if hasattr(bill, key):
                setattr(bill, key, value)
        if invoice_payload:
            if invoice is None:
                db.add(RmbInvoice(reimbursement_id=bill.id, created_by=user.username, **invoice_payload))
            else:
                for key, value in invoice_payload.items():
                    setattr(invoice, key, value)
        bill.status = STATUS_WAIT_CHECK
        bill.compliance_result = COMPLIANCE_UNTESTED
        bill.override_flag = 0
        bill.override_reason = ""
        bill.override_by = ""
        bill.override_at = None
        db.commit()
    except Exception:
        db.rollback()
        raise

    changed = "、".join(fields.keys()) if fields else ""
    if invoice_payload:
        changed = (changed + "、" if changed else "") + "票据信息"
    write_log(
        db, user, "修改报销单", bill_log_path(bill.id),
        detail=f"{bill.bill_no}；修改字段：{changed or '无'}；状态重置为待判读",
        method="PUT", request=request,
    )
    if token:
        remove_recognized(token)
    return success({"id": bill.id, "bill_no": bill.bill_no},
                   message="修改成功，请重新提交 AI 合规判读")


@router.post("/{bill_id}/approve", summary="审批报销单（分级审批）")
def approve_bill(
    bill_id: int,
    data: BillApproveIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:bill:approve")),
):
    """按制度第四条做分级审批。

    - 审批层级由单笔金额决定：<5,000 元→1 级（部门负责人/财务复核）；
      5,000～20,000 元→2 级（部门总监）；≥20,000 元→3 级（总经理）。
    - 采用「向上兼容」：层级高的人可审批低层级单据，反之则越权被拒。
    - **数据范围**：部门负责人/部门总监只能审批本部门单据；财务复核、总经理、
      系统管理员可审批全公司（财务与经营是跨部门职能）。
    - 报销人本人不能审批自己的单据（与制单、复核一致的自审防范）。
    - 已生成凭证或已作废的单据不可再审批。
    """
    bill = db.get(RmbReimbursement, bill_id)
    if not bill:
        raise BizException("报销单不存在")
    ensure_bill_visible(db, user, bill)

    if bill.status in (STATUS_VOID, "已生成凭证"):
        raise BizException(f"当前状态「{bill.status}」不允许审批")

    action = (data.action or "approve").strip()
    if action not in ("approve", "reject"):
        raise BizException("不支持的审批动作，应为 approve / reject")
    comment = (data.comment or "").strip()

    # 报销人不能审批自己的单据
    if is_bill_owner(bill, user):
        raise PermissionException("报销人不能审批自己提交的报销单（职责分离要求）")

    # 数据范围：部门管理岗只能审批本部门单据
    if not bill_in_scope(db, user, bill):
        scope = user_data_scope(db, user)
        if scope == SCOPE_DEPT:
            raise PermissionException("只能审批本部门的报销单（数据范围限制）")
        raise PermissionException("该报销单不在您的审批范围内")

    params = sys_params(db)
    need_rank = required_approval_rank(bill.amount, params)
    my_rank = user_approval_rank(db, user)
    if my_rank < need_rank:
        raise PermissionException(
            f"审批权限不足：本单金额 {float(bill.amount or 0):,.2f} 元，"
            f"须经「{APPROVAL_RANK_LABELS.get(need_rank, '')}」审批；"
            f"您的审批层级为「{APPROVAL_RANK_LABELS.get(my_rank, '无') or '无'}」"
        )

    if action == "reject" and not comment:
        raise BizException("驳回时必须填写审批意见（说明退回原因）")
    # 大额单据（2 级及以上）无论通过与否都应留下意见，便于审计追溯
    if action == "approve" and need_rank >= 2 and not comment:
        raise BizException("该单据须经二级以上审批，请填写审批意见")

    try:
        bill.approval_status = APPROVAL_PASSED if action == "approve" else APPROVAL_REJECTED
        bill.approval_by = user.real_name or user.username
        bill.approval_at = now()
        bill.approval_comment = comment
        bill.approval_rank = my_rank
        # 驳回视为退回：状态回到「待判读」，报销人修改后可重新提交
        if action == "reject" and bill.status not in (STATUS_WAIT_CHECK,):
            bill.status = STATUS_WAIT_CHECK
            bill.compliance_result = COMPLIANCE_UNTESTED
        db.commit()
    except Exception:
        db.rollback()
        raise

    label = "审批通过" if action == "approve" else "审批驳回"
    write_log(
        db, user, label, bill_log_path(bill.id),
        detail=f"{bill.bill_no}；金额 {float(bill.amount or 0):,.2f} 元；"
               f"审批层级 {my_rank}（{APPROVAL_RANK_LABELS.get(my_rank, '')}）；"
               f"意见：{comment or '（无）'}",
        request=request,
    )
    return success({
        "id": bill.id,
        "bill_no": bill.bill_no,
        "approval_status": bill.approval_status,
        "approval_by": bill.approval_by,
        "approval_rank": bill.approval_rank,
        "status": bill.status,
    }, message=f"{label}：{bill.bill_no}")


@router.post("/{bill_id}/void", summary="作废报销单")
def void_bill(
    bill_id: int,
    data: BillVoidIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions(*BILL_VOID_PERMS)),
):
    """作废报销单（须填原因）。已生成凭证的单据不允许作废。"""
    bill = db.get(RmbReimbursement, bill_id)
    if not bill:
        raise BizException("报销单不存在")
    ensure_bill_visible(db, user, bill)
    _ensure_can_void(db, user, bill)
    if bill.status == STATUS_VOID:
        raise BizException("该报销单已作废，请勿重复操作")
    reason = (data.reason or "").strip()
    if not reason:
        raise BizException("请填写作废原因")
    voucher = db.query(RmbVoucher).filter(RmbVoucher.reimbursement_id == bill.id).first()
    if voucher:
        raise BizException(f"该报销单已生成凭证 {voucher.voucher_code}，不允许作废")
    try:
        bill.status = STATUS_VOID
        db.commit()
    except Exception:
        db.rollback()
        raise
    write_log(db, user, "作废报销单", bill_log_path(bill.id),
              detail=f"{bill.bill_no}；原因：{reason}", request=request)
    return success(message="报销单已作废")


@router.delete("/{bill_id}", summary="删除报销单")
def delete_bill(
    bill_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions(*BILL_VOID_PERMS)),
):
    """删除报销单（仅本人，且状态为待判读/判读不合规）。票据原件一并清理。"""
    bill = db.get(RmbReimbursement, bill_id)
    if not bill:
        raise BizException("报销单不存在")
    if not is_bill_owner(bill, user):
        raise PermissionException("只能删除本人的报销单")
    if bill.status not in DELETABLE_STATUS:
        raise BizException(f"当前状态「{bill.status}」不允许删除，仅待判读/判读不合规可删除")
    if db.query(RmbVoucher).filter(RmbVoucher.reimbursement_id == bill.id).first():
        raise BizException("该报销单已生成凭证，不允许删除")
    invoice = db.query(RmbInvoice).filter(RmbInvoice.reimbursement_id == bill.id).first()
    file_path = invoice.file_path if invoice else ""
    bill_no = bill.bill_no
    log_path = bill_log_path(bill.id)
    try:
        db.query(RmbComplianceIssue).filter(
            RmbComplianceIssue.check_id.in_(
                db.query(RmbComplianceCheck.id).filter(RmbComplianceCheck.reimbursement_id == bill.id)
            )
        ).delete(synchronize_session=False)
        db.query(RmbComplianceCheck).filter(RmbComplianceCheck.reimbursement_id == bill.id).delete(
            synchronize_session=False)
        if invoice is not None:
            db.delete(invoice)
        db.delete(bill)
        db.commit()
    except Exception:
        db.rollback()
        raise
    remove_ticket(file_path)
    write_log(db, user, "删除报销单", log_path, detail=bill_no,
              method="DELETE", request=request)
    return success(message="报销单已删除")
