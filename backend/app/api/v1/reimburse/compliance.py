"""合规判读接口：执行判读 / 判读结果详情 / 处理结论 / 判读记录列表。

设计要点：
- 判读本身耗时长（大模型 20～60 秒），由服务层 `compliance_ai.run_compliance_check` 完成，
  本模块只负责权限、状态前置校验、结果组装与留痕；**服务层在函数内部延迟导入**，
  这样服务未就绪时其他接口不受影响。
- 「处理结论」的三种动作（提交制证 / 作废 / 人工覆盖）权限与职责分离要求各不相同，
  因此路由统一挂 `reimburse:check:run`，动作级权限在函数内用 ensure_perm 二次校验。
- 人工覆盖是审计重点：要求覆盖人不是报销人本人、理由不少于 10 字，
  并在报销单上写 override_flag/reason/by/at，日志单独记「人工覆盖判定」。
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permissions
from app.api.v1.reimburse._common import (
    APPROVAL_PASSED,
    CHECKABLE_STATUS,
    RESULT_COMPLIANT,
    RESULT_CONCERN,
    RESULT_NONCOMPLIANT,
    STATUS_VOID,
    STATUS_WAIT_CONFIRM,
    STATUS_WAIT_VOUCHER,
    VOID_PERM_CODE,
    bill_log_path,
    bill_row,
    check_brief,
    check_full,
    ensure_bill_visible,
    ensure_can_void,
    ensure_not_bill_owner,
    ensure_perm,
    has_perm,
    invoice_row,
    is_bill_owner,
    latest_check,
    load_bill_maps,
    read_logs,
    write_log,
)
from app.core.database import get_db
from app.core.exceptions import BizException
from app.models.quality import OperationLog
from app.models.rbac import User
from app.models.reimburse import (
    RmbComplianceCheck,
    RmbComplianceIssue,
    RmbInvoice,
    RmbReimbursement,
    RmbVoucher,
)
from app.schemas.reimburse import ComplianceHandleIn
from app.utils.response import page_result, success

router = APIRouter(prefix="/rmb-compliance", tags=["合规判读"])

#: 人工覆盖理由的最少字数（制度变更管理 / 审计留痕要求）
MIN_OVERRIDE_REASON_LEN = 10


# ==================== 内部辅助 ====================
def _load_bill(db: Session, bill_id: int) -> RmbReimbursement:
    bill = db.get(RmbReimbursement, bill_id)
    if not bill:
        raise BizException("报销单不存在")
    return bill


def _latest_check_or_error(db: Session, bill_id: int) -> RmbComplianceCheck:
    check = latest_check(db, bill_id)
    if not check:
        raise BizException("该报销单尚未进行合规判读，请先执行判读")
    return check


def _check_logged_recently(db: Session, bill_id: int, seconds: int = 300) -> bool:
    """判断服务层是否刚为这张单写过判读日志，避免接口层重复记录同一动作。"""
    since = datetime.now() - timedelta(seconds=seconds)
    row = (
        db.query(OperationLog.id)
        .filter(
            OperationLog.path == bill_log_path(bill_id),
            OperationLog.action.like("%合规判读%"),
            OperationLog.created_at >= since,
        )
        .first()
    )
    return row is not None


def _history(db: Session, bill_id: int, limit: int = 20) -> list[dict]:
    """历次判读记录（时间正序，含处理方式）。"""
    rows = (
        db.query(RmbComplianceCheck)
        .filter(RmbComplianceCheck.reimbursement_id == bill_id)
        .order_by(RmbComplianceCheck.id.desc())
        .limit(limit)
        .all()
    )
    result = []
    for check in reversed(rows):
        row = check_brief(check) or {}
        counts = dict(
            db.query(RmbComplianceIssue.result, func.count(RmbComplianceIssue.id))
            .filter(RmbComplianceIssue.check_id == check.id)
            .group_by(RmbComplianceIssue.result)
            .all()
        )
        row["noncompliant_count"] = counts.get(RESULT_NONCOMPLIANT, 0)
        row["concern_count"] = counts.get(RESULT_CONCERN, 0)
        row["compliant_count"] = counts.get(RESULT_COMPLIANT, 0)
        result.append(row)
    return result


def _issue_counts(db: Session, check_id: int) -> dict:
    counts = dict(
        db.query(RmbComplianceIssue.result, func.count(RmbComplianceIssue.id))
        .filter(RmbComplianceIssue.check_id == check_id)
        .group_by(RmbComplianceIssue.result)
        .all()
    )
    return {
        "noncompliant_count": counts.get(RESULT_NONCOMPLIANT, 0),
        "concern_count": counts.get(RESULT_CONCERN, 0),
        "compliant_count": counts.get(RESULT_COMPLIANT, 0),
        "na_count": counts.get("不适用", 0),
    }


def _update_bill_status(db: Session, bill: RmbReimbursement, status: str) -> None:
    bill.status = status


# ==================== 一、执行判读 ====================
@router.post("/run/{bill_id}", summary="执行合规判读")
def run_check(
    bill_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:check:run")),
):
    """调用大模型对报销单逐条判读（20～60 秒，前端需单独放宽超时）。

    - 报销人只能判读自己的单；
    - 只有「待判读 / 判读不合规 / 待确认」状态可以判读；
    - 大模型失败时服务层抛中文错误且不改变单据状态，这里原样返回给前端。
    """
    bill = _load_bill(db, bill_id)
    ensure_bill_visible(db, user, bill)
    if bill.status not in CHECKABLE_STATUS:
        raise BizException(f"当前状态「{bill.status}」不允许判读，"
                           f"仅{'/'.join(CHECKABLE_STATUS)}可判读")

    token_payload = {}

    # 服务层延迟导入：服务未就绪时只影响本接口
    try:
        from app.services import compliance_ai
    except ImportError as exc:
        raise BizException(f"合规判读服务尚未就绪：{exc}")

    started = datetime.now()
    try:
        result = compliance_ai.run_compliance_check(db, bill.id, user.username) or {}
    except BizException:
        db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001 - 大模型/网络/解析异常统一转中文提示
        db.rollback()
        raise BizException(f"AI 合规判读失败：{exc}")

    # 服务层已落库，这里重新读取最新一次判读，返回与数据库一致的结果
    db.expire_all()
    bill = db.get(RmbReimbursement, bill_id)
    check = latest_check(db, bill_id)
    if check is None:
        # 服务层未写库（例如仅返回了内存结果）时，按返回值组装响应
        return success(dict(result), message="判读完成")

    detail = check_full(db, check)
    detail.update(_issue_counts(db, check.id))
    detail["issues_total"] = len(detail.get("issues") or [])

    if not _check_logged_recently(db, bill_id):
        write_log(
            db, user, "AI合规判读", bill_log_path(bill_id),
            detail=f"{bill.bill_no}；{check.model or '未知模型'}；{check.elapsed or 0:.1f}s；"
                   f"结论{check.overall_result or '未知'}；不一致{check.inconsistency_count or 0}项",
            request=request,
        )
    return success(detail, message=f"判读完成：{check.overall_result or '已完成'}")


# ==================== 二、判读记录列表 ====================
@router.get("/list", summary="判读记录列表")
def list_checks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    result: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:bill:list")),
):
    """各报销单最近一次判读的结论汇总（制单员/管理员视角）。

    返回字段：单号、报销人、金额、判读结论、不合规项数、需关注项数、不一致项数、是否人工覆盖。
    """
    latest_ids = (
        db.query(func.max(RmbComplianceCheck.id).label("check_id"))
        .group_by(RmbComplianceCheck.reimbursement_id)
        .subquery()
    )
    query = (
        db.query(RmbComplianceCheck, RmbReimbursement)
        .join(RmbReimbursement, RmbReimbursement.id == RmbComplianceCheck.reimbursement_id)
        .join(latest_ids, latest_ids.c.check_id == RmbComplianceCheck.id)
    )
    if result:
        query = query.filter(RmbComplianceCheck.overall_result == result)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(RmbReimbursement.bill_no.like(like))

    total = query.count()
    rows = (
        query.order_by(RmbComplianceCheck.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    maps = load_bill_maps(db)
    data = []
    for check, bill in rows:
        row = bill_row(bill, maps)
        row["check"] = check_brief(check)
        row.update(_issue_counts(db, check.id))
        row["check"]["noncompliant_count"] = row["noncompliant_count"]
        row["check"]["concern_count"] = row["concern_count"]
        row["overridden"] = bool(bill.override_flag)
        data.append(row)
    return success(page_result(data, total))


# ==================== 三、判读结果详情 ====================
@router.get("/{bill_id}", summary="判读结果详情")
def check_detail(
    bill_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:bill:list")),
):
    """判读结果详情：报销单摘要 + 最近一次判读（含 14 条明细）+ 历次判读 + 程序事实。"""
    bill = _load_bill(db, bill_id)
    ensure_bill_visible(db, user, bill)
    maps = load_bill_maps(db)
    check = latest_check(db, bill_id)
    invoice = db.query(RmbInvoice).filter(RmbInvoice.reimbursement_id == bill.id).first()

    data = {
        "bill": bill_row(bill, maps),
        "invoice": invoice_row(invoice),
        "check": None,
        "history": _history(db, bill_id),
    }
    data["bill"]["can_override"] = (
        bill.status not in (STATUS_VOID,)
        and not is_bill_owner(bill, user)
    )
    # 作废可用性：与报销单接口同一套口径（已审批后报销人不能自行作废、已生成凭证不能作废）
    has_void_perm = has_perm(db, user, VOID_PERM_CODE)
    approved = (bill.approval_status or "") == APPROVAL_PASSED
    refused_by_voucher = (
        db.query(RmbVoucher).filter(RmbVoucher.reimbursement_id == bill.id).first() is not None
    )
    data["bill"]["can_void"] = (
        bill.status != STATUS_VOID
        and not refused_by_voucher
        and (has_void_perm or (is_bill_owner(bill, user) and not approved))
    )
    if check is not None:
        detail = check_full(db, check)
        detail.update(_issue_counts(db, check.id))
        data["check"] = detail
    data["logs"] = read_logs(db, [bill_log_path(bill.id)], limit=60)
    return success(data)


# ==================== 四、处理判读结论 ====================
@router.post("/{bill_id}/handle", summary="处理判读结论")
def handle_check(
    bill_id: int,
    data: ComplianceHandleIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:check:run")),
):
    """处理判读结论。

    - `submit`：合规直接提交制证；需关注须填写说明后提交；不合规不允许提交；
    - `void`：作废报销单（须填原因，已生成凭证的不允许作废）；
    - `override`：人工覆盖（需 reimburse:check:override；操作人不能是报销人本人；
      理由不少于 10 字），状态直接置为待制证。
    """
    action = (data.action or "").strip()
    comment = (data.comment or "").strip()
    if action not in ("submit", "void", "override"):
        raise BizException("不支持的处理动作，应为 submit / void / override")

    bill = _load_bill(db, bill_id)
    ensure_bill_visible(db, user, bill)
    check = _latest_check_or_error(db, bill_id)
    if bill.status == STATUS_VOID:
        raise BizException("该报销单已作废，不能再处理判读结论")

    voucher = db.query(RmbVoucher).filter(RmbVoucher.reimbursement_id == bill.id).first()
    if voucher:
        raise BizException(f"该报销单已生成凭证 {voucher.voucher_code}，不能再处理判读结论")

    action_label = ""

    if action == "submit":
        # 只有合规或需关注可以提交制证；不合规必须先整改后重新判读
        if bill.compliance_result == RESULT_NONCOMPLIANT:
            raise BizException("判读结论为不合规，不能直接提交制证，请修改报销信息后重新判读")
        if bill.compliance_result == RESULT_CONCERN and not comment:
            raise BizException("判读结论为需关注，须填写补充说明后再提交制证")
        if bill.status not in (STATUS_WAIT_VOUCHER, STATUS_WAIT_CONFIRM):
            raise BizException(f"当前状态「{bill.status}」不允许提交制证，请先完成合规判读")
        action_label = "提交制证"

    elif action == "void":
        if not comment:
            raise BizException("请填写作废原因")
        # 与报销单作废接口同一套职责口径：已审批通过的单据不允许报销人自行作废
        ensure_can_void(db, user, bill)
        action_label = "作废"

    else:  # override
        ensure_perm(db, user, "reimburse:check:override")
        ensure_not_bill_owner(bill, user, "人工覆盖判定")
        if len(comment) < MIN_OVERRIDE_REASON_LEN:
            raise BizException(f"人工覆盖理由不能少于 {MIN_OVERRIDE_REASON_LEN} 个字，请说明依据")
        if bill.compliance_result not in (RESULT_NONCOMPLIANT, RESULT_CONCERN):
            raise BizException("当前判读结论无需人工覆盖，请直接提交制证")
        if bill.status == STATUS_WAIT_VOUCHER:
            raise BizException("该报销单已是待制证状态，无需人工覆盖")
        action_label = "人工覆盖"

    try:
        bill.status = STATUS_VOID if action == "void" else STATUS_WAIT_VOUCHER
        check.handle_action = action_label
        check.handle_comment = comment
        check.handled_by = user.username
        check.handled_at = datetime.now()
        if action == "override":
            bill.override_flag = 1
            bill.override_reason = comment
            bill.override_by = user.username
            bill.override_at = datetime.now()
        db.commit()
    except Exception:
        db.rollback()
        raise

    log_action = {"submit": "确认报销单", "void": "作废报销单", "override": "人工覆盖判定"}[action]
    write_log(
        db, user, log_action, bill_log_path(bill.id),
        detail=f"{bill.bill_no}；{action_label}"
               f"（原判读结论：{check.overall_result or '未知'}）"
               + (f"；说明：{comment[:32]}" if comment else ""),
        request=request,
    )
    message = {
        "submit": "已提交制证，请由制单员生成凭证",
        "void": "报销单已作废",
        "override": "已人工覆盖判读结论，报销单进入待制证",
    }[action]
    return success({
        "id": bill.id,
        "bill_no": bill.bill_no,
        "status": bill.status,
        "compliance_result": bill.compliance_result,
        "override_flag": bill.override_flag or 0,
    }, message=message)
