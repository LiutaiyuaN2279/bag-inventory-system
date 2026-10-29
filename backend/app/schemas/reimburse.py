"""差旅与业务招待费报销智能体：Schema 定义。

字段与 `app/models/reimburse.py` 的 16 张 rmb_* 表一一对应。
全部字段用 Optional 并给出默认值：报销模块的字段是「制度要求项」而不是「接口必填项」，
缺失的要素应由后续 AI 合规判读给出提示，而不是让前端在 422 参数校验里直接报错。
真正的必填校验（报销人、费用类型、发生日期、金额等）统一在接口层用中文提示完成。
"""
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ==================== 一、报销单与票据 ====================
class InvoiceIn(BaseModel):
    """票据信息（字段对齐 rmb_invoice 表）。items 传数组，入库时序列化为 items_json。"""

    document_type: Optional[str] = ""
    is_invoice: Optional[int] = 1
    invoice_code: Optional[str] = ""
    invoice_number: Optional[str] = ""
    issue_date: Optional[str] = ""

    buyer_name: Optional[str] = ""
    buyer_tax_id: Optional[str] = ""
    seller_name: Optional[str] = ""
    seller_tax_id: Optional[str] = ""

    amount_without_tax: Optional[float] = 0
    tax_rate: Optional[str] = ""
    tax_amount: Optional[float] = 0
    total_amount: Optional[float] = 0
    total_amount_cn: Optional[str] = ""
    items: Optional[list[Any]] = None

    # 差旅要素
    passenger_name: Optional[str] = ""
    travel_from: Optional[str] = ""
    travel_to: Optional[str] = ""
    travel_date: Optional[str] = ""
    checkin_date: Optional[str] = ""
    checkout_date: Optional[str] = ""
    nights: Optional[int] = 0
    consume_city: Optional[str] = ""

    # 文件归档信息（相对 settings.UPLOAD_DIR 的路径）
    file_path: Optional[str] = ""
    original_filename: Optional[str] = ""
    file_hash: Optional[str] = ""

    # AI 识别留痕
    llm_model: Optional[str] = ""
    llm_raw_json: Optional[str] = ""
    remark: Optional[str] = ""

    # AI 建议的费用类型：只用于确认页提示「AI 建议类型与所选类型不一致」，
    # rmb_invoice 表没有这一列，保存时会被 _invoice_payload 的列白名单过滤掉，不入库。
    suggested_expense_type: Optional[str] = ""


class InvoiceOut(InvoiceIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reimbursement_id: Optional[int] = None
    created_by: Optional[str] = ""
    created_at: Optional[str] = None


class ReimburseBase(BaseModel):
    """报销单公共字段。报销单号与报销日期由服务器生成，不接受前端传入。"""

    employee_id: Optional[int] = None
    department_id: Optional[int] = None
    expense_type_id: Optional[int] = None

    reason: Optional[str] = ""
    occur_date: Optional[str] = ""
    amount: Optional[float] = 0
    has_invoice: Optional[int] = 1
    approver_name: Optional[str] = ""
    approver_level: Optional[str] = ""

    travel_city: Optional[str] = ""
    travel_start: Optional[str] = ""
    travel_end: Optional[str] = ""
    nights: Optional[int] = 0

    guest_company: Optional[str] = ""
    guest_count: Optional[int] = 0

    special_approver: Optional[str] = ""
    explanation: Optional[str] = ""
    settlement_method_id: Optional[int] = None


class ReimburseCreate(ReimburseBase):
    """新建报销单：票据随单一起提交。token 为识别阶段返回的临时数据标识。"""

    token: Optional[str] = None
    invoice: Optional[InvoiceIn] = None


class ReimburseUpdate(BaseModel):
    """修改报销单：未传的字段保持原值（按 exclude_unset 处理）。"""

    employee_id: Optional[int] = None
    department_id: Optional[int] = None
    expense_type_id: Optional[int] = None
    reason: Optional[str] = None
    occur_date: Optional[str] = None
    amount: Optional[float] = None
    has_invoice: Optional[int] = None
    approver_name: Optional[str] = None
    approver_level: Optional[str] = None
    travel_city: Optional[str] = None
    travel_start: Optional[str] = None
    travel_end: Optional[str] = None
    nights: Optional[int] = None
    guest_company: Optional[str] = None
    guest_count: Optional[int] = None
    special_approver: Optional[str] = None
    explanation: Optional[str] = None
    settlement_method_id: Optional[int] = None
    token: Optional[str] = None
    invoice: Optional[InvoiceIn] = None


class ReimburseOut(ReimburseBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bill_no: str
    bill_date: str
    status: Optional[str] = ""
    compliance_result: Optional[str] = ""
    override_flag: Optional[int] = 0
    override_reason: Optional[str] = ""
    override_by: Optional[str] = ""
    override_at: Optional[str] = None
    created_by: Optional[str] = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class BillVoidIn(BaseModel):
    """作废报销单（须填原因）。"""

    reason: Optional[str] = ""


class BillApproveIn(BaseModel):
    """审批报销单（制度第四条分级审批）。

    action：
    - approve 批准（进入 AI 合规判读环节）
    - reject  驳回（退回报销人修改）
    """

    action: Optional[str] = "approve"
    comment: Optional[str] = ""


class BillSaveOut(BaseModel):
    id: int
    bill_no: str


class ReasonSuggestIn(BaseModel):
    """AI 生成报销事由的入参：已填写的报销信息 + 票据识别结果（均可选）。

    只是给大模型组织文案的上下文，缺失字段不影响调用；
    真正的必填校验仍在保存接口里完成。
    """

    expense_type_id: Optional[int] = None
    occur_date: Optional[str] = ""
    amount: Optional[float] = None
    has_invoice: Optional[int] = 1
    travel_city: Optional[str] = ""
    travel_start: Optional[str] = ""
    travel_end: Optional[str] = ""
    nights: Optional[int] = 0
    guest_company: Optional[str] = ""
    guest_count: Optional[int] = 0
    invoice: Optional[dict[str, Any]] = None


# ==================== 二、合规判读 ====================
class ComplianceRunIn(BaseModel):
    """执行判读的可选参数：不传则使用系统默认制度与模型。"""

    model: Optional[str] = None
    policy_id: Optional[int] = None
    remark: Optional[str] = ""


class ComplianceIssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    rule_code: Optional[str] = ""
    check_item: Optional[str] = ""
    clause_no: Optional[str] = ""
    result: Optional[str] = ""
    reason: Optional[str] = ""
    suggestion: Optional[str] = ""
    evidence: Optional[str] = ""
    program_triggered: Optional[int] = None
    consistency: Optional[str] = "未校验"
    sort_no: Optional[int] = 0


class ComplianceCheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reimbursement_id: Optional[int] = None
    check_no: Optional[int] = 1
    policy_id: Optional[int] = None
    model: Optional[str] = ""
    overall_result: Optional[str] = ""
    ai_overall_result: Optional[str] = ""
    summary: Optional[str] = ""
    inconsistency_count: Optional[int] = 0
    elapsed: Optional[float] = 0
    checked_by: Optional[str] = ""
    checked_at: Optional[str] = None
    handle_action: Optional[str] = ""
    handle_comment: Optional[str] = ""
    handled_by: Optional[str] = ""
    handled_at: Optional[str] = None
    facts: Optional[dict] = None
    issues: Optional[list[ComplianceIssueOut]] = None


class ComplianceHandleIn(BaseModel):
    """处理判读结论：submit 提交制证 / void 作废 / override 人工覆盖。"""

    action: Optional[str] = ""
    comment: Optional[str] = ""


# ==================== 三、凭证 ====================
class VoucherEntryIn(BaseModel):
    """凭证分录（AI 草稿与人工编辑共用同一结构）。"""

    line_no: Optional[int] = None
    summary: Optional[str] = ""
    subject_code: Optional[str] = ""
    subject_name: Optional[str] = ""
    debit_amount: Optional[float] = 0
    credit_amount: Optional[float] = 0


class VoucherHeaderIn(BaseModel):
    """凭证头。凭证字号由程序在保存时生成，这里传入的值只作草稿预览。"""

    voucher_word: Optional[str] = ""
    period: Optional[str] = ""
    voucher_no: Optional[int] = None
    voucher_date: Optional[str] = ""
    attachment_count: Optional[int] = None


class VoucherDraftIn(BaseModel):
    reimbursement_id: Optional[int] = None


class VoucherValidateIn(BaseModel):
    reimbursement_id: Optional[int] = None
    header: Optional[VoucherHeaderIn] = None
    entries: Optional[list[VoucherEntryIn]] = Field(default_factory=list)


class VoucherSaveIn(VoucherValidateIn):
    """保存凭证：附带 AI 草稿标识，便于留痕「制单员对 AI 草稿做了哪些修改」。"""

    compliance_check_id: Optional[int] = None
    ai_model: Optional[str] = ""
    ai_raw_json: Optional[str] = ""
    ai_explanation: Optional[str] = ""
    ai_tax_treatment: Optional[str] = ""
    ai_entries: Optional[list[dict]] = None


class VoucherOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    voucher_word: Optional[str] = "记"
    period: Optional[str] = ""
    voucher_no: Optional[int] = 0
    voucher_code: Optional[str] = ""
    voucher_date: Optional[str] = ""
    attachment_count: Optional[int] = 0
    reimbursement_id: Optional[int] = None
    compliance_check_id: Optional[int] = None
    total_debit: Optional[float] = 0
    total_credit: Optional[float] = 0
    ai_model: Optional[str] = ""
    ai_explanation: Optional[str] = ""
    ai_tax_treatment: Optional[str] = ""
    status: Optional[str] = ""
    maker: Optional[str] = ""
    made_at: Optional[str] = None
    reviewer: Optional[str] = ""
    reviewed_at: Optional[str] = None
    review_comment: Optional[str] = ""
    entries: Optional[list[VoucherEntryIn]] = None


class VoucherReviewIn(BaseModel):
    """复核：approve 复核通过 / reject 退回修改。"""

    action: Optional[str] = ""
    comment: Optional[str] = ""


class VoucherReviewBatchIn(BaseModel):
    ids: Optional[list[int]] = Field(default_factory=list)
    action: Optional[str] = ""
    comment: Optional[str] = ""


# ==================== 四、制度与参数管理 ====================
class PolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    policy_no: Optional[str] = ""
    policy_name: Optional[str] = ""
    effective_date: Optional[str] = ""
    file_path: Optional[str] = ""
    original_filename: Optional[str] = ""
    file_hash: Optional[str] = ""
    dashscope_file_id: Optional[str] = ""
    is_active: Optional[bool] = False
    uploaded_by: Optional[str] = ""
    uploaded_at: Optional[str] = None
    remark: Optional[str] = ""
    content_length: Optional[int] = 0
    content_preview: Optional[str] = ""


class PolicyRuleUpdate(BaseModel):
    check_item: Optional[str] = None
    judge_rule: Optional[str] = None
    clause_no: Optional[str] = None
    risk_level: Optional[str] = None
    check_mode: Optional[str] = None
    is_active: Optional[bool] = None
    sort_no: Optional[int] = None


class SysParamUpdate(BaseModel):
    """修改系统参数。

    兼容三种前端写法：{key, value} / {param_key, param_value} / {items:[{key,value}]}。
    """

    key: Optional[str] = None
    value: Optional[str] = None
    param_key: Optional[str] = None
    param_value: Optional[str] = None
    remark: Optional[str] = None
    items: Optional[list[dict]] = None


class CityLevelIn(BaseModel):
    city_name: Optional[str] = ""
    city_level: Optional[str] = "其他城市"
    lodging_limit: Optional[float] = 400


class CityLevelUpdate(BaseModel):
    city_name: Optional[str] = None
    city_level: Optional[str] = None
    lodging_limit: Optional[float] = None


class HolidayIn(BaseModel):
    holiday_date: Optional[str] = ""
    holiday_name: Optional[str] = ""
    day_type: Optional[str] = "法定节假日"


class HolidayUpdate(BaseModel):
    holiday_name: Optional[str] = None
    day_type: Optional[str] = None
