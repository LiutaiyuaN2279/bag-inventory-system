"""凭证接口：待制证 / AI 制证草稿 / 校验 / 保存 / 修改退回凭证 / 列表 / 详情 / 复核。

关键控制点（与实验文档第 12 步一致）：
- 制单（make）与复核（review）权限分离，制单人不能是报销人本人，复核人不能是制单人也不能是报销人；
- 凭证字号由程序在事务内取号（BEGIN IMMEDIATE + MAX(voucher_no)+1），大模型不参与编号，
  保证「记-YYYYMM-NNNN」不重号；
- 保存与复核都会再次走 validate_voucher，errors 非空一律拒绝，避免只靠前端校验；
- 已复核凭证不允许修改；被退回的凭证修改后凭证号不变、状态回到未复核并清空复核人；
- 经人工覆盖或判读「需关注」的凭证，复核意见必填且不允许批量复核（必须逐张看清理由）。

服务层 voucher_ai 由同事并行开发，**在函数内部延迟导入**，服务未就绪时不影响只读接口。
"""
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permissions
from app.api.v1.reimburse._common import (
    RESULT_CONCERN,
    STATUS_VOID,
    STATUS_VOUCHER_DONE,
    STATUS_WAIT_VOUCHER,
    VOUCHER_RETURNED,
    VOUCHER_REVIEWED,
    VOUCHER_UNREVIEWED,
    account_subject_map,
    begin_immediate,
    bill_log_path,
    bill_row,
    check_brief,
    default_voucher_word,
    ensure_bill_visible,
    ensure_not_bill_owner,
    invoice_row,
    is_bill_employee,
    latest_check,
    load_bill_maps,
    money_float,
    next_voucher_no,
    parse_day,
    to_decimal,
    voucher_code_of,
    voucher_log_path,
    voucher_logs,
    write_log,
)
from app.core.database import get_db
from app.core.exceptions import BizException
from app.crud.crud_base import apply_ordering
from app.models.rbac import User
from app.models.reimburse import (
    RmbAccountSubject,
    RmbComplianceCheck,
    RmbInvoice,
    RmbReimbursement,
    RmbVoucher,
    RmbVoucherEntry,
)
from app.schemas.reimburse import (
    VoucherDraftIn,
    VoucherReviewBatchIn,
    VoucherReviewIn,
    VoucherSaveIn,
    VoucherValidateIn,
)
from app.utils.response import page_result, success

router = APIRouter(prefix="/rmb-vouchers", tags=["凭证"])


# ==================== 内部辅助 ====================
def _load_bill(db: Session, bill_id: int) -> RmbReimbursement:
    bill = db.get(RmbReimbursement, bill_id)
    if not bill:
        raise BizException("报销单不存在")
    return bill


def _load_voucher(db: Session, voucher_id: int) -> RmbVoucher:
    voucher = db.get(RmbVoucher, voucher_id)
    if not voucher:
        raise BizException("凭证不存在")
    return voucher


def _entries_from_rows(rows: list[RmbVoucherEntry]) -> list[dict]:
    return [
        {
            "id": row.id, "line_no": row.line_no or 0, "summary": row.summary or "",
            "subject_code": row.subject_code or "", "subject_name": row.subject_name or "",
            "debit_amount": row.debit_amount or 0, "credit_amount": row.credit_amount or 0,
        }
        for row in rows
    ]


def _normalize_entries(db: Session, entries: list | None) -> list[dict]:
    """把前端/AI 提交的分录规范化为统一字典列表。

    - 金额用 Decimal 规整到分后再回写 float，避免 0.30000000000000004 之类的尾差；
    - 科目名称以科目表 full_name 为准（大模型可能给出简称或编造名称）；
    - 借贷方向只保留一边（同时填两边视为脏数据，这里保留原值交给校验器报错）。
    """
    subjects = account_subject_map(db)
    rows: list[dict] = []
    for index, raw in enumerate(entries or [], start=1):
        item = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw or {})
        code = str(item.get("subject_code") or "").strip()
        subject = subjects.get(code) if code else None
        name = (subject.full_name if subject else "") or str(item.get("subject_name") or "").strip()
        rows.append({
            "line_no": int(item.get("line_no") or index),
            "summary": str(item.get("summary") or "").strip(),
            "subject_code": code,
            "subject_name": name,
            "debit_amount": money_float(item.get("debit_amount") or 0),
            "credit_amount": money_float(item.get("credit_amount") or 0),
        })
    return rows


def _validate(db: Session, bill: RmbReimbursement, invoice: RmbInvoice | None,
              header: dict | None, entries: list[dict]) -> tuple[list[str], list[str]]:
    """调用服务层校验凭证，返回 (errors, warnings)。

    服务层缺失或抛异常时退化为「程序只能做借贷平衡校验」，并给出提示，
    避免因为服务层未就绪就把整条制证流程堵死。
    """
    try:
        from app.services import voucher_ai
    except ImportError:
        errors, warnings = _fallback_validate(db, bill, entries)
        warnings.append("凭证校验服务尚未就绪，已按借贷平衡做基础校验，请人工复核")
        return errors, warnings
    try:
        result = voucher_ai.validate_voucher(db, entries, header or {}, bill, invoice)
    except BizException:
        raise
    except Exception as exc:  # noqa: BLE001 - 校验服务异常统一转中文提示
        raise BizException(f"凭证校验失败：{exc}")
    if isinstance(result, tuple) and len(result) == 2:
        errors, warnings = result
    else:  # 兼容服务层返回 dict 的写法
        payload = result or {}
        errors, warnings = payload.get("errors") or [], payload.get("warnings") or []
    return [str(item) for item in errors or []], [str(item) for item in warnings or []]


def _fallback_validate(db: Session, bill: RmbReimbursement, entries: list[dict]) -> tuple[list[str], list[str]]:
    """服务层不可用时的基础校验：分录非空、每行仅一方向、借贷平衡且等于报销金额。"""
    errors: list[str] = []
    warnings: list[str] = []
    if len(entries) < 2:
        errors.append("凭证至少需要两行分录")
        return errors, warnings
    debit = Decimal("0.00")
    credit = Decimal("0.00")
    for index, row in enumerate(entries, start=1):
        d, c = to_decimal(row.get("debit_amount")), to_decimal(row.get("credit_amount"))
        if d > 0 and c > 0:
            errors.append(f"第 {index} 行不能同时填写借方和贷方金额")
        if d <= 0 and c <= 0:
            errors.append(f"第 {index} 行借贷金额必须大于 0")
        if not row.get("summary"):
            errors.append(f"第 {index} 行摘要不能为空")
        if not row.get("subject_code"):
            errors.append(f"第 {index} 行未选择会计科目")
        debit += d
        credit += c
    if debit != credit:
        errors.append(f"借贷不平衡：借方合计 {debit} 元，贷方合计 {credit} 元")
    amount = to_decimal(bill.amount)
    if debit != amount:
        errors.append(f"借方合计 {debit} 元与报销金额 {amount} 元不一致")
    return errors, warnings


def _save_entries(db: Session, voucher_id: int, entries: list[dict]) -> None:
    """按提交的分录重建凭证分录（保存/修改共用）。"""
    db.query(RmbVoucherEntry).filter(RmbVoucherEntry.voucher_id == voucher_id).delete(
        synchronize_session=False)
    for row in entries:
        db.add(RmbVoucherEntry(
            voucher_id=voucher_id, line_no=row["line_no"], summary=row["summary"],
            subject_code=row["subject_code"], subject_name=row["subject_name"],
            debit_amount=row["debit_amount"], credit_amount=row["credit_amount"],
        ))


def _totals(entries: list[dict]) -> tuple[float, float]:
    debit = sum((to_decimal(row.get("debit_amount")) for row in entries), Decimal("0.00"))
    credit = sum((to_decimal(row.get("credit_amount")) for row in entries), Decimal("0.00"))
    return money_float(debit), money_float(credit)


def _generate_header(db: Session, bill: RmbReimbursement, header: dict | None,
                     invoice: RmbInvoice | None, voucher: RmbVoucher | None = None) -> dict:
    """生成凭证头：凭证字取系统参数、日期与期间由程序决定，凭证号在保存时取号。"""
    header = header or {}
    word = str(header.get("voucher_word") or "").strip() or default_voucher_word(db)
    voucher_date = parse_day(header.get("voucher_date") or date.today().isoformat(), "凭证日期")
    period = voucher_date[:7]
    attachment_count = header.get("attachment_count")
    if attachment_count is None:
        attachment_count = 1 if invoice is not None else 0
    return {
        "voucher_word": word[:8],
        "period": period,
        "voucher_no": voucher.voucher_no if voucher else (header.get("voucher_no") or None),
        "voucher_date": voucher_date,
        "attachment_count": int(attachment_count or 0),
    }


def _user_display_names(db: Session, usernames) -> dict[str, str]:
    """username → 中文姓名映射（real_name 为空时回退 username）。

    凭证表只存 username（登录账号），展示层统一换成中文姓名；
    原始 username 仍以 maker_username / reviewer_username 返回，便于排障。
    """
    values = {u for u in usernames if u}
    if not values:
        return {}
    rows = (
        db.query(User.username, User.real_name)
        .filter(User.username.in_(values))
        .all()
    )
    return {username: (real_name or username) for username, real_name in rows}


def _display_name(names: dict[str, str], username: str) -> str:
    return names.get(username) or username or ""


def _voucher_payload(voucher: RmbVoucher, bill: RmbReimbursement, maps: dict,
                     check: RmbComplianceCheck | None, entries: list[dict],
                     names: dict[str, str] | None = None) -> dict:
    names = names or {}
    row = bill_row(bill, maps)
    data = {
        "id": voucher.id,
        "voucher_word": voucher.voucher_word or "记",
        "period": voucher.period or "",
        "voucher_no": voucher.voucher_no or 0,
        "voucher_code": voucher.voucher_code or "",
        "voucher_date": voucher.voucher_date or "",
        "attachment_count": voucher.attachment_count or 0,
        "reimbursement_id": voucher.reimbursement_id,
        "compliance_check_id": voucher.compliance_check_id,
        "total_debit": voucher.total_debit or 0,
        "total_credit": voucher.total_credit or 0,
        "ai_model": voucher.ai_model or "",
        "ai_explanation": voucher.ai_explanation or "",
        "ai_tax_treatment": voucher.ai_tax_treatment or "",
        "status": voucher.status or "",
        # 制单人 / 复核人展示中文姓名；原始登录账号另见 *_username 字段
        "maker": _display_name(names, voucher.maker),
        "maker_username": voucher.maker or "",
        "made_at": str(voucher.made_at)[:19] if voucher.made_at else "",
        "reviewer": _display_name(names, voucher.reviewer),
        "reviewer_username": voucher.reviewer or "",
        "reviewed_at": str(voucher.reviewed_at)[:19] if voucher.reviewed_at else "",
        "review_comment": voucher.review_comment or "",
        "entries": entries,
        "bill": row,
        "bill_no": bill.bill_no,
        "employee_name": row["employee_name"],
        "check": check_brief(check),
        "overridden": bool(bill.override_flag),
        "needs_attention": (bill.override_flag == 1) or (bill.compliance_result == RESULT_CONCERN),
        "summary": entries[0]["summary"] if entries else "",
        "amount": voucher.total_debit or 0,
    }
    return data


def _voucher_list_row(voucher: RmbVoucher, bill: RmbReimbursement, maps: dict,
                      check: RmbComplianceCheck | None, first_summary: str,
                      names: dict[str, str] | None = None) -> dict:
    names = names or {}
    row = bill_row(bill, maps)
    return {
        "id": voucher.id,
        "voucher_code": voucher.voucher_code or "",
        "voucher_word": voucher.voucher_word or "记",
        "period": voucher.period or "",
        "voucher_no": voucher.voucher_no or 0,
        "voucher_date": voucher.voucher_date or "",
        "attachment_count": voucher.attachment_count or 0,
        "reimbursement_id": voucher.reimbursement_id,
        "bill_no": bill.bill_no,
        "employee_name": row["employee_name"],
        "department_name": row["department_name"],
        "expense_type_name": row["expense_type_name"],
        "summary": first_summary,
        "total_debit": voucher.total_debit or 0,
        "total_credit": voucher.total_credit or 0,
        "amount": voucher.total_debit or 0,
        "status": voucher.status or "",
        # 制单人 / 复核人展示中文姓名；原始登录账号另见 *_username 字段
        "maker": _display_name(names, voucher.maker),
        "maker_username": voucher.maker or "",
        "made_at": str(voucher.made_at)[:19] if voucher.made_at else "",
        "reviewer": _display_name(names, voucher.reviewer),
        "reviewer_username": voucher.reviewer or "",
        "reviewed_at": str(voucher.reviewed_at)[:19] if voucher.reviewed_at else "",
        "review_comment": voucher.review_comment or "",
        "compliance_result": bill.compliance_result or "",
        "overridden": bool(bill.override_flag),
        "override_by": bill.override_by or "",
        "override_reason": bill.override_reason or "",
        "needs_attention": (bill.override_flag == 1) or (bill.compliance_result == RESULT_CONCERN),
        "check": check_brief(check),
    }


def _first_summary(db: Session, voucher_id: int) -> str:
    row = (
        db.query(RmbVoucherEntry.summary)
        .filter(RmbVoucherEntry.voucher_id == voucher_id)
        .order_by(RmbVoucherEntry.line_no, RmbVoucherEntry.id)
        .first()
    )
    return (row[0] if row else "") or ""


# ==================== 一、待制证列表 ====================
@router.get("/pending", summary="待制证列表")
def list_pending(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    keyword: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:voucher:make")),
):
    """状态为「待制证」且尚未生成凭证的报销单（制单员的工作台）。"""
    query = (
        db.query(RmbReimbursement)
        .outerjoin(RmbVoucher, RmbVoucher.reimbursement_id == RmbReimbursement.id)
        .filter(RmbReimbursement.status == STATUS_WAIT_VOUCHER, RmbVoucher.id.is_(None))
    )
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(or_(RmbReimbursement.bill_no.like(like),
                                 RmbReimbursement.reason.like(like)))
    total = query.count()
    rows = (
        query.order_by(RmbReimbursement.id.desc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    maps = load_bill_maps(db)
    data = []
    for bill in rows:
        row = bill_row(bill, maps)
        check = latest_check(db, bill.id)
        row["check"] = check_brief(check)
        row["overridden"] = bool(bill.override_flag)
        row["needs_attention"] = (bill.override_flag == 1) or (bill.compliance_result == RESULT_CONCERN)
        data.append(row)
    return success(page_result(data, total))


# ==================== 二、AI 制证草稿 ====================
@router.post("/draft", summary="生成 AI 凭证草稿")
def create_draft(
    data: VoucherDraftIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:voucher:make")),
):
    """调大模型生成凭证草稿（20～60 秒，前端需单独放宽超时）。

    前置校验在服务层内部也会做一遍（状态必须为待制证、制单人不能是报销人本人），
    这里提前校验是为了给出更直接的中文提示。
    """
    bill_id = data.reimbursement_id
    if not bill_id:
        raise BizException("请指定报销单")
    bill = _load_bill(db, bill_id)
    if bill.status == STATUS_VOID:
        raise BizException("该报销单已作废，不能制证")
    if bill.status != STATUS_WAIT_VOUCHER:
        raise BizException(f"当前状态「{bill.status}」不允许制证，仅待制证状态可生成凭证")
    ensure_not_bill_owner(bill, user, "制单人")
    if is_bill_employee(bill, user):
        raise BizException("制单人不能是报销人本人（职责分离要求）")
    existed = db.query(RmbVoucher).filter(RmbVoucher.reimbursement_id == bill.id).first()
    if existed:
        raise BizException(f"该报销单已生成凭证 {existed.voucher_code}，请勿重复制证")

    try:
        from app.services import voucher_ai
    except ImportError as exc:
        raise BizException(f"AI 制证服务尚未就绪：{exc}")

    try:
        result = voucher_ai.generate_voucher_draft(db, bill.id, user.username) or {}
    except BizException:
        db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001 - 大模型/网络/解析异常统一转中文提示
        db.rollback()
        raise BizException(f"AI 生成凭证草稿失败：{exc}")

    payload = dict(result)
    entries = _normalize_entries(db, payload.get("entries"))
    header = _generate_header(db, bill, payload.get("header"), None)
    # 预览凭证号：该期间当前最大号 +1（正式号在保存时重新取，避免并发重号）
    header["voucher_no"] = next_voucher_no(db, header["period"], header["voucher_word"])
    payload["header"] = header
    payload["entries"] = entries
    payload["total_debit"], payload["total_credit"] = _totals(entries)
    payload["reimbursement_id"] = bill.id
    payload["bill"] = bill_row(bill, load_bill_maps(db))
    payload["check"] = check_brief(latest_check(db, bill.id))
    payload["overridden"] = bool(bill.override_flag)

    write_log(
        db, user, "AI生成凭证", bill_log_path(bill.id),
        detail=f"{bill.bill_no}；{payload.get('model') or '未知模型'}；"
               f"{float(payload.get('elapsed') or 0):.1f}s；"
               f"{len(entries)} 行分录；错误{len(payload.get('errors') or [])}项",
        request=request,
    )
    return success(payload, message="AI 凭证草稿已生成，请核对后保存")


# ==================== 三、重新校验 ====================
@router.post("/validate", summary="重新校验凭证")
def validate_voucher_api(
    data: VoucherValidateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:voucher:make")),
):
    """制单员修改分录后重新校验：返回 errors（红色）与 warnings（黄色）。"""
    bill = _load_bill(db, data.reimbursement_id or 0)
    invoice = db.query(RmbInvoice).filter(RmbInvoice.reimbursement_id == bill.id).first()
    entries = _normalize_entries(db, data.entries)
    header = _generate_header(db, bill, data.header.model_dump() if data.header else None, invoice)
    errors, warnings = _validate(db, bill, invoice, header, entries)
    debit, credit = _totals(entries)
    return success({
        "errors": errors,
        "warnings": warnings,
        "total_debit": debit,
        "total_credit": credit,
        "balanced": to_decimal(debit) == to_decimal(credit),
        "amount": bill.amount or 0,
        "diff": money_float(to_decimal(debit) - to_decimal(credit)),
    }, message="校验完成" if not errors else "校验未通过")


# ==================== 四、保存凭证 ====================
@router.post("/save", summary="保存凭证")
def save_voucher(
    data: VoucherSaveIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:voucher:make")),
):
    """保存凭证（同一事务内取号并写入凭证主表 + 分录）。

    - 再次调用 validate_voucher，有 errors 直接拒绝；
    - BEGIN IMMEDIATE 拿写锁后重新取 MAX(voucher_no)+1，生成「记-YYYYMM-NNNN」；
    - 制单人不能是报销人本人；报销单必须为待制证且未生成过凭证；
    - 报销单状态改为「已生成凭证」。
    """
    bill = _load_bill(db, data.reimbursement_id or 0)
    if bill.status == STATUS_VOID:
        raise BizException("该报销单已作废，不能制证")
    if bill.status != STATUS_WAIT_VOUCHER:
        raise BizException(f"当前状态「{bill.status}」不允许制证，仅待制证状态可保存凭证")
    if is_bill_employee(bill, user):
        raise BizException("制单人不能是报销人本人（职责分离要求）")

    invoice = db.query(RmbInvoice).filter(RmbInvoice.reimbursement_id == bill.id).first()
    entries = _normalize_entries(db, data.entries)
    if not entries:
        raise BizException("请填写凭证分录")
    header_input = data.header.model_dump() if data.header else None
    header = _generate_header(db, bill, header_input, invoice)
    errors, warnings = _validate(db, bill, invoice, header, entries)
    if errors:
        raise BizException("凭证校验未通过：" + "；".join(errors[:5]))

    check = latest_check(db, bill.id)
    check_id = data.compliance_check_id or (check.id if check else None)
    debit, credit = _totals(entries)

    try:
        begin_immediate(db)
        if db.query(RmbVoucher).filter(RmbVoucher.reimbursement_id == bill.id).first():
            raise BizException("该报销单已生成凭证，请勿重复保存")
        voucher_no = next_voucher_no(db, header["period"], header["voucher_word"])
        voucher = RmbVoucher(
            voucher_word=header["voucher_word"],
            period=header["period"],
            voucher_no=voucher_no,
            voucher_code=voucher_code_of(header["voucher_word"], header["period"], voucher_no),
            voucher_date=header["voucher_date"],
            attachment_count=header["attachment_count"],
            reimbursement_id=bill.id,
            compliance_check_id=check_id,
            total_debit=debit,
            total_credit=credit,
            ai_model=(data.ai_model or "").strip(),
            ai_raw_json=data.ai_raw_json or "",
            ai_explanation=data.ai_explanation or "",
            ai_tax_treatment=data.ai_tax_treatment or "",
            status=VOUCHER_UNREVIEWED,
            maker=user.username,
        )
        db.add(voucher)
        db.flush()
        _save_entries(db, voucher.id, entries)
        bill.status = STATUS_VOUCHER_DONE
        db.commit()
    except BizException:
        db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001 - 唯一索引冲突等统一转中文提示
        db.rollback()
        raise BizException(f"凭证保存失败：{exc}")

    diff = _diff_entries(data.ai_entries, entries)
    write_log(
        db, user, "保存凭证", voucher_log_path(voucher.id),
        detail=f"{voucher.voucher_code}；报销单{bill.bill_no}；{debit:.2f}元；"
               f"{len(entries)}行" + (f"；对AI草稿修改：{diff}" if diff else ""),
        request=request,
    )
    return success({
        "id": voucher.id,
        "voucher_code": voucher.voucher_code,
        "status": voucher.status,
        "total_debit": debit,
        "total_credit": credit,
        "warnings": warnings,
    }, message=f"凭证 {voucher.voucher_code} 已保存，等待复核")


def _diff_entries(ai_entries: list[dict] | None, entries: list[dict]) -> str:
    """比较 AI 草稿与最终分录，返回修改摘要（用于留痕「制单员改了什么」）。"""
    if not ai_entries:
        return ""
    labels = {"summary": "摘要", "subject_code": "科目", "debit_amount": "借方", "credit_amount": "贷方"}
    changes: list[str] = []
    length = max(len(ai_entries), len(entries))
    for index in range(length):
        before = dict(ai_entries[index] or {}) if index < len(ai_entries) else {}
        after = entries[index] if index < len(entries) else {}
        if not before:
            changes.append(f"第{index + 1}行新增")
            continue
        if not after:
            changes.append(f"第{index + 1}行删除")
            continue
        for key, label in labels.items():
            if str(before.get(key) or "") != str(after.get(key) or ""):
                changes.append(f"第{index + 1}行{label}")
                break
    return "、".join(changes)[:32]


# ==================== 五、列表 ====================
@router.get("", summary="凭证列表")
def list_vouchers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
    status: str | None = None,
    period: str | None = None,
    keyword: str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:voucher:list")),
):
    """凭证分页列表（按状态、期间、关键字筛选）。"""
    query = (
        db.query(RmbVoucher, RmbReimbursement)
        .join(RmbReimbursement, RmbReimbursement.id == RmbVoucher.reimbursement_id)
    )
    if status:
        query = query.filter(RmbVoucher.status == status)
    if period:
        query = query.filter(RmbVoucher.period == period.strip())
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(or_(
            RmbVoucher.voucher_code.like(like),
            RmbVoucher.maker.like(like),
            RmbReimbursement.bill_no.like(like),
        ))
    total = query.count()
    rows = (
        apply_ordering(query, RmbVoucher, sort_by, sort_order)
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    maps = load_bill_maps(db)
    names = _user_display_names(db, [u for voucher, _ in rows for u in (voucher.maker, voucher.reviewer)])
    data = [
        _voucher_list_row(voucher, bill, maps, latest_check(db, bill.id),
                          _first_summary(db, voucher.id), names)
        for voucher, bill in rows
    ]
    return success(page_result(data, total))


# ==================== 六、待复核列表 ====================
@router.get("/review", summary="待复核凭证列表")
def list_review_queue(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    period: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:voucher:review")),
):
    """待复核（未复核）凭证列表。复核人不能看到自己制作或自己是报销人的凭证。"""
    query = (
        db.query(RmbVoucher, RmbReimbursement)
        .join(RmbReimbursement, RmbReimbursement.id == RmbVoucher.reimbursement_id)
        .filter(RmbVoucher.status == VOUCHER_UNREVIEWED)
        .filter(RmbVoucher.maker != user.username)
    )
    if period:
        query = query.filter(RmbVoucher.period == period.strip())
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(or_(RmbVoucher.voucher_code.like(like),
                                 RmbReimbursement.bill_no.like(like)))
    employee_id = getattr(user, "employee_id", None)
    if employee_id:
        # 自己是报销人的凭证也不能由自己复核（职责分离）
        query = query.filter(RmbReimbursement.employee_id != employee_id)
    total = query.count()
    rows = (
        query.order_by(RmbVoucher.id.asc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    maps = load_bill_maps(db)
    names = _user_display_names(db, [u for voucher, _ in rows for u in (voucher.maker, voucher.reviewer)])
    data = [
        _voucher_list_row(voucher, bill, maps, latest_check(db, bill.id),
                          _first_summary(db, voucher.id), names)
        for voucher, bill in rows
    ]
    return success(page_result(data, total))


# ==================== 七、批量复核 ====================
@router.post("/review/batch", summary="批量复核凭证")
def batch_review(
    data: VoucherReviewBatchIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:voucher:review")),
):
    """批量复核：逐张独立事务执行同样的控制规则，返回成功数与失败明细。

    经人工覆盖或判读「需关注」的凭证不允许批量复核（必须逐张看清覆盖理由）。
    """
    action = (data.action or "").strip()
    if action not in ("approve", "reject"):
        raise BizException("不支持的复核动作，应为 approve / reject")
    ids = [int(i) for i in (data.ids or []) if str(i).strip().isdigit()]
    if not ids:
        raise BizException("请先勾选要复核的凭证")
    if len(ids) > 200:
        raise BizException("单次批量复核最多 200 张凭证")

    succeeded = 0
    failed: list[dict] = []
    comment = (data.comment or "").strip()
    for voucher_id in dict.fromkeys(ids):
        try:
            _review_one(db, user, voucher_id, action, comment, batch=True)
            succeeded += 1
        except BizException as exc:
            db.rollback()
            failed.append({"id": voucher_id, "code": exc.code, "reason": exc.message})
        except Exception as exc:  # noqa: BLE001 - 单张失败不影响整批
            db.rollback()
            failed.append({"id": voucher_id, "code": 50000, "reason": str(exc) or "未知错误"})

    write_log(
        db, user, "批量复核凭证", "/api/v1/rmb-vouchers/review/batch",
        detail=f"{'复核通过' if action == 'approve' else '退回'}；成功{succeeded}张；"
               f"失败{len(failed)}张",
        request=request,
    )
    message = f"成功 {succeeded} 张，失败 {len(failed)} 张" if failed else f"已成功处理 {succeeded} 张"
    return success({"success_count": succeeded, "failed": failed,
                    "total": len(ids)}, message=message)


# ==================== 八、复核单张 ====================
@router.post("/review/{voucher_id}", summary="复核凭证")
def review_voucher(
    voucher_id: int,
    data: VoucherReviewIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:voucher:review")),
):
    """复核凭证：approve 复核通过 / reject 退回修改。"""
    action = (data.action or "").strip()
    if action not in ("approve", "reject"):
        raise BizException("不支持的复核动作，应为 approve / reject")
    voucher = _review_one(db, user, voucher_id, action, (data.comment or "").strip())
    message = "复核通过" if action == "approve" else "已退回制单人修改"
    return success({
        "id": voucher.id, "voucher_code": voucher.voucher_code, "status": voucher.status,
    }, message=message)


def _review_one(db: Session, user: User, voucher_id: int, action: str, comment: str,
                batch: bool = False) -> RmbVoucher:
    """单张复核的业务核心（单条端点与批量接口共用同一份规则）。

    控制规则：
    1. 凭证必须为「未复核」；
    2. 复核人不能是制单人，也不能是报销人本人；
    3. 再次校验借贷平衡（errors 非空一律拒绝）；
    4. approve：经人工覆盖或判读需关注的，复核意见必填；批量时直接禁止；
    5. reject：复核意见必填，状态改「已退回」。
    """
    voucher = _load_voucher(db, voucher_id)
    bill = db.get(RmbReimbursement, voucher.reimbursement_id)
    if not bill:
        raise BizException("凭证关联的报销单不存在")
    if is_bill_employee(bill, user):
        raise BizException("复核人不能是报销人本人（职责分离要求）")
    if voucher.status != VOUCHER_UNREVIEWED:
        raise BizException(f"凭证当前状态「{voucher.status}」，仅未复核凭证可以复核")
    if voucher.maker and voucher.maker == user.username:
        raise BizException("复核人不能是制单人（职责分离要求）")
    if batch and ((bill.override_flag == 1) or (bill.compliance_result == RESULT_CONCERN)):
        raise BizException("该凭证经人工覆盖或判读需关注，不允许批量复核，请逐张复核")

    entries = _entries_from_rows(
        db.query(RmbVoucherEntry).filter(RmbVoucherEntry.voucher_id == voucher.id)
        .order_by(RmbVoucherEntry.line_no, RmbVoucherEntry.id).all()
    )
    invoice = db.query(RmbInvoice).filter(RmbInvoice.reimbursement_id == bill.id).first()
    errors, _warnings = _validate(db, bill, invoice, {
        "voucher_word": voucher.voucher_word, "period": voucher.period,
        "voucher_no": voucher.voucher_no, "voucher_date": voucher.voucher_date,
        "attachment_count": voucher.attachment_count,
    }, entries)
    if errors:
        raise BizException("复核前校验未通过：" + "；".join(errors[:5]))

    need_comment = (bill.override_flag == 1) or (bill.compliance_result == RESULT_CONCERN)
    if action == "approve":
        if need_comment and not comment:
            raise BizException("该凭证经人工覆盖或判读需关注，复核意见必填")
        try:
            voucher.status = VOUCHER_REVIEWED
            voucher.reviewer = user.username
            voucher.reviewed_at = datetime.now()
            voucher.review_comment = comment
            db.commit()
        except Exception:
            db.rollback()
            raise
    else:
        if not comment:
            raise BizException("退回修改必须填写复核意见")
        try:
            voucher.status = VOUCHER_RETURNED
            voucher.reviewer = user.username
            voucher.reviewed_at = datetime.now()
            voucher.review_comment = comment
            db.commit()
        except Exception:
            db.rollback()
            raise

    write_log(
        db, user, "复核凭证" if action == "approve" else "退回凭证",
        voucher_log_path(voucher.id),
        detail=f"{voucher.voucher_code}；{bill.bill_no}"
               + (f"；意见：{comment[:30]}" if comment else ""),
    )
    return voucher


# ==================== 九、可用会计科目（凭证编辑页下拉）====================
@router.get("/subjects", summary="可用会计科目")
def list_subjects(
    db: Session = Depends(get_db),
    _=Depends(require_permissions("reimburse:voucher:list")),
):
    """返回末级且启用的会计科目，供凭证编辑页的科目下拉框使用。

    必须注册在 `/{voucher_id}` 之前，否则会被动态路由当作 voucher_id 解析而报错。
    """
    rows = (
        db.query(RmbAccountSubject)
        .filter(RmbAccountSubject.is_leaf == True,      # noqa: E712
                RmbAccountSubject.is_active == True)     # noqa: E712
        .order_by(RmbAccountSubject.code)
        .all()
    )
    return success([
        {
            "code": r.code,
            "name": r.name,
            "full_name": r.full_name,
            "category": r.category,
            "balance_direction": r.balance_direction,
            "is_leaf": bool(r.is_leaf),
            "is_active": bool(r.is_active),
        }
        for r in rows
    ])


# ==================== 十、凭证详情 ====================
@router.get("/{voucher_id}", summary="凭证详情")
def voucher_detail(
    voucher_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:voucher:list")),
):
    """凭证详情：分录 + AI 说明 + 判读结论 + 报销单 + 票据 + 审计轨迹。"""
    voucher = _load_voucher(db, voucher_id)
    bill = db.get(RmbReimbursement, voucher.reimbursement_id)
    if not bill:
        raise BizException("凭证关联的报销单不存在")
    ensure_bill_visible(db, user, bill)

    entries = _entries_from_rows(
        db.query(RmbVoucherEntry).filter(RmbVoucherEntry.voucher_id == voucher.id)
        .order_by(RmbVoucherEntry.line_no, RmbVoucherEntry.id).all()
    )
    check = db.get(RmbComplianceCheck, voucher.compliance_check_id) if voucher.compliance_check_id else None
    if check is None:
        check = latest_check(db, bill.id)
    invoice = db.query(RmbInvoice).filter(RmbInvoice.reimbursement_id == bill.id).first()
    names = _user_display_names(db, (voucher.maker, voucher.reviewer))
    data = _voucher_payload(voucher, bill, load_bill_maps(db), check, entries, names)
    data["invoice"] = invoice_row(invoice)
    data["ai_raw_json"] = voucher.ai_raw_json or ""
    data["logs"] = voucher_logs(db, voucher)
    return success(data)


# ==================== 十一、修改被退回的凭证 ====================
@router.put("/{voucher_id}", summary="修改被退回的凭证")
def update_voucher(
    voucher_id: int,
    data: VoucherSaveIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:voucher:make")),
):
    """修改被退回的凭证：凭证号不变，状态回到未复核并清空复核人。"""
    voucher = _load_voucher(db, voucher_id)
    if voucher.status == VOUCHER_REVIEWED:
        raise BizException("已复核凭证不允许修改")
    if voucher.status != VOUCHER_RETURNED:
        raise BizException(f"凭证当前状态「{voucher.status}」，仅已退回的凭证可以修改")
    bill = db.get(RmbReimbursement, voucher.reimbursement_id)
    if not bill:
        raise BizException("凭证关联的报销单不存在")
    if is_bill_employee(bill, user):
        raise BizException("制单人不能是报销人本人（职责分离要求）")

    invoice = db.query(RmbInvoice).filter(RmbInvoice.reimbursement_id == bill.id).first()
    entries = _normalize_entries(db, data.entries)
    if not entries:
        raise BizException("请填写凭证分录")
    header_input = data.header.model_dump() if data.header else None
    header = _generate_header(db, bill, header_input, invoice, voucher=voucher)
    errors, warnings = _validate(db, bill, invoice, header, entries)
    if errors:
        raise BizException("凭证校验未通过：" + "；".join(errors[:5]))

    debit, credit = _totals(entries)
    try:
        _save_entries(db, voucher.id, entries)
        voucher.voucher_date = header["voucher_date"]
        voucher.attachment_count = header["attachment_count"]
        voucher.total_debit = debit
        voucher.total_credit = credit
        if data.ai_explanation:
            voucher.ai_explanation = data.ai_explanation
        if data.ai_tax_treatment:
            voucher.ai_tax_treatment = data.ai_tax_treatment
        voucher.status = VOUCHER_UNREVIEWED
        voucher.reviewer = ""
        voucher.reviewed_at = None
        voucher.review_comment = ""
        db.commit()
    except Exception:
        db.rollback()
        raise

    write_log(
        db, user, "修改凭证", voucher_log_path(voucher.id),
        detail=f"{voucher.voucher_code}；报销单{bill.bill_no}；{debit:.2f}元；{len(entries)}行",
        method="PUT", request=request,
    )
    return success({
        "id": voucher.id, "voucher_code": voucher.voucher_code,
        "status": voucher.status, "total_debit": debit, "total_credit": credit,
        "warnings": warnings,
    }, message="凭证已修改，重新提交复核")
