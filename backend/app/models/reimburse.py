"""差旅与业务招待费报销智能体：数据模型。

对应《信息系统审计 实验一》第四部分设计，共 16 张表，分为三类：
- 基础表：部门 / 员工 / 会计科目 / 费用类型 / 结算方式 / 城市等级 / 节假日 / 系统参数 / 制度 / 检查规则
- 业务表：报销单 / 票据 / 合规判读记录 / 判读明细 / 凭证 / 凭证分录
- 审计表：复用系统已有的 operation_logs（含 AI 模型、耗时等写入 detail）

设计要点（与实验要求的内部控制对应）：
- invoice 上建 UNIQUE(file_hash) 阻止同一张票被反复使用；invoice_number 唯一索引阻止同一张发票重复报销。
- voucher 上建 UNIQUE(reimbursement_id) 保证一张报销单只生成一张凭证；
  UNIQUE(period, voucher_word, voucher_no) 保证凭证号不重号。
- 制度、规则、阈值参数单独成表，便于"变更管理"控制与留痕。
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from app.core.database import Base


# ==================== 一、基础表 ====================
class RmbDepartment(Base):
    """部门表。"""
    __tablename__ = "rmb_department"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(16), unique=True, nullable=False, index=True)
    name = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=func.now())


class RmbEmployee(Base):
    """员工表：报销人与其所属部门。"""
    __tablename__ = "rmb_employee"

    id = Column(Integer, primary_key=True, autoincrement=True)
    emp_no = Column(String(32), unique=True, nullable=False, index=True)
    name = Column(String(64), nullable=False)
    department_id = Column(Integer, ForeignKey("rmb_department.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=func.now())


class RmbAccountSubject(Base):
    """会计科目表：凭证只能使用末级（is_leaf=1）且启用（is_active=1）的科目。"""
    __tablename__ = "rmb_account_subject"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(16), unique=True, nullable=False, index=True)
    name = Column(String(64), nullable=False)
    full_name = Column(String(128), nullable=False)  # 科目全称，凭证分录以此为准
    category = Column(String(16), default="")        # 资产/负债/损益
    balance_direction = Column(String(4), default="借")  # 借/贷
    parent_code = Column(String(16), default="")
    level = Column(Integer, default=1)
    is_leaf = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    remark = Column(String(255), default="")
    created_at = Column(DateTime, default=func.now())


class RmbExpenseType(Base):
    """费用类型表：对应借方科目，以及需要采集的专项信息（差旅/招待/无）。"""
    __tablename__ = "rmb_expense_type"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False, index=True)
    subject_code = Column(String(16), nullable=False)  # 默认借方科目编码
    special_info = Column(String(8), default="无")      # 差旅/招待/无
    remark = Column(String(255), default="")
    sort_no = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())


class RmbSettlementMethod(Base):
    """结算方式表：决定凭证贷方科目。"""
    __tablename__ = "rmb_settlement_method"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False)
    subject_code = Column(String(16), nullable=False)  # 贷方科目编码
    remark = Column(String(255), default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())


class RmbCityLevel(Base):
    """城市等级表：住宿标准上限。含一条 city_name='其他城市' 的兜底记录。"""
    __tablename__ = "rmb_city_level"

    id = Column(Integer, primary_key=True, autoincrement=True)
    city_name = Column(String(64), unique=True, nullable=False, index=True)
    city_level = Column(String(16), default="其他城市")  # 一线城市/其他城市
    lodging_limit = Column(Float, default=400)           # 住宿标准上限（元/晚）
    created_at = Column(DateTime, default=func.now())


class RmbHoliday(Base):
    """节假日表：法定节假日与调休上班日。用于 R05 周末/节假日招待判断。"""
    __tablename__ = "rmb_holiday"

    holiday_date = Column(String(10), primary_key=True)  # YYYY-MM-DD
    holiday_name = Column(String(64), default="")
    day_type = Column(String(16), default="法定节假日")  # 法定节假日/调休上班日
    created_at = Column(DateTime, default=func.now())


class RmbSysParam(Base):
    """系统参数表：审批金额、招待阈值等。与制度文件中的数值必须保持一致。"""
    __tablename__ = "rmb_sys_param"

    param_key = Column(String(64), primary_key=True)
    param_value = Column(String(255), default="")
    remark = Column(String(255), default="")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class RmbPolicy(Base):
    """报销制度表：制度文件版本及其百炼文件 ID。同一时间只能有一个生效版本。"""
    __tablename__ = "rmb_policy"

    id = Column(Integer, primary_key=True, autoincrement=True)
    policy_no = Column(String(64), default="")
    policy_name = Column(String(128), default="")
    effective_date = Column(String(10), default="")
    file_path = Column(String(255), default="")          # 本地存档路径
    original_filename = Column(String(255), default="")
    file_hash = Column(String(64), default="")
    content_text = Column(Text, default="")              # 制度正文纯文本（供 AI 提示词直接引用）
    dashscope_file_id = Column(String(128), default="")  # 百炼文件 ID
    is_active = Column(Boolean, default=False, index=True)
    uploaded_by = Column(String(64), default="")
    uploaded_at = Column(DateTime, default=func.now())
    remark = Column(String(255), default="")


class RmbPolicyRule(Base):
    """制度检查规则表：R01～R14。"""
    __tablename__ = "rmb_policy_rule"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_code = Column(String(16), unique=True, nullable=False, index=True)
    check_item = Column(String(64), nullable=False)
    judge_rule = Column(Text, default="")
    clause_no = Column(String(32), default="")
    risk_level = Column(String(8), default="中")          # 高/中/低
    check_mode = Column(String(16), default="AI+程序")    # AI+程序 / AI
    is_active = Column(Boolean, default=True)
    sort_no = Column(Integer, default=0)
    updated_by = Column(String(64), default="")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


# ==================== 二、业务表 ====================
class RmbReimbursement(Base):
    """报销单表。报销人填写，状态按流程流转。"""
    __tablename__ = "rmb_reimbursement"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bill_no = Column(String(32), unique=True, nullable=False, index=True)  # BX-20261020-0001
    bill_date = Column(String(10), nullable=False)                          # 服务器当前日期

    employee_id = Column(Integer, ForeignKey("rmb_employee.id"), nullable=True, index=True)
    department_id = Column(Integer, ForeignKey("rmb_department.id"), nullable=True)
    expense_type_id = Column(Integer, ForeignKey("rmb_expense_type.id"), nullable=True, index=True)

    reason = Column(Text, default="")             # 报销事由
    occur_date = Column(String(10), nullable=False, index=True)  # 费用发生日期
    amount = Column(Float, nullable=False, default=0)
    has_invoice = Column(Integer, default=1)      # 是否附发票 1/0
    approver_name = Column(String(64), default="")
    approver_level = Column(String(32), default="")  # 部门负责人/财务复核/部门总监/总经理

    # 差旅专项
    travel_city = Column(String(64), default="")
    travel_start = Column(String(10), default="")
    travel_end = Column(String(10), default="")
    nights = Column(Integer, default=0)

    # 招待专项
    guest_company = Column(String(128), default="")
    guest_count = Column(Integer, default=0)

    # 特批与说明
    special_approver = Column(String(128), default="")  # 特批人及职务
    explanation = Column(Text, default="")

    settlement_method_id = Column(Integer, ForeignKey("rmb_settlement_method.id"), nullable=True)

    status = Column(String(16), default="待判读", index=True)
    # 待判读/判读不合规/待确认/待制证/已生成凭证/已作废
    compliance_result = Column(String(16), default="未判读")  # 未判读/合规/需关注/不合规

    # ---- 分级审批（制度第四条）----
    # 按单笔金额定审批层级：<5,000 元→1 级（部门负责人/财务复核）；
    # 5,000～20,000 元→2 级（部门总监）；≥20,000 元→3 级（总经理）。
    # 与 compliance_check（AI 合规判读）是两条独立的控制线：审批管"谁有权批"，
    # 判读管"符不符合制度标准"，两者都通过才能制证。
    approval_status = Column(String(16), default="未审批", index=True)  # 未审批/已审批/已驳回
    approval_by = Column(String(64), default="")        # 审批人
    approval_at = Column(DateTime, nullable=True)       # 审批时间
    approval_comment = Column(Text, default="")         # 审批意见
    approval_rank = Column(Integer, nullable=True)      # 审批时的层级（1/2/3）

    override_flag = Column(Integer, default=0)
    override_reason = Column(Text, default="")
    override_by = Column(String(64), default="")
    override_at = Column(DateTime, nullable=True)

    created_by = Column(String(64), default="")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class RmbInvoice(Base):
    """票据信息表：经人工确认后的票据。一张报销单对应一张票据。"""
    __tablename__ = "rmb_invoice"
    __table_args__ = (
        # 有号码的发票不得被多张报销单使用（invoice_number 为空时不受约束）
        UniqueConstraint("invoice_number", name="uq_rmb_invoice_number"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    reimbursement_id = Column(
        Integer, ForeignKey("rmb_reimbursement.id"), unique=True, nullable=True, index=True
    )

    document_type = Column(String(64), default="")
    is_invoice = Column(Integer, default=1)

    invoice_code = Column(String(32), default="")
    invoice_number = Column(String(64), default="", index=True)
    issue_date = Column(String(10), default="")

    buyer_name = Column(String(128), default="")
    buyer_tax_id = Column(String(64), default="")
    seller_name = Column(String(128), default="")
    seller_tax_id = Column(String(64), default="")

    amount_without_tax = Column(Float, default=0)
    tax_rate = Column(String(16), default="")
    tax_amount = Column(Float, default=0)
    total_amount = Column(Float, default=0)
    total_amount_cn = Column(String(128), default="")
    items_json = Column(Text, default="[]")

    # 差旅要素
    passenger_name = Column(String(64), default="")
    travel_from = Column(String(64), default="")
    travel_to = Column(String(64), default="")
    travel_date = Column(String(10), default="")
    checkin_date = Column(String(10), default="")
    checkout_date = Column(String(10), default="")
    nights = Column(Integer, default=0)
    consume_city = Column(String(64), default="")

    # 文件
    file_path = Column(String(255), default="")
    original_filename = Column(String(255), default="")
    file_hash = Column(String(64), default="", index=True)

    # AI
    llm_model = Column(String(64), default="")
    llm_raw_json = Column(Text, default="")

    created_by = Column(String(64), default="")
    created_at = Column(DateTime, default=func.now())


class RmbComplianceCheck(Base):
    """合规判读记录表：一张报销单可多次判读，保留历次结果供审计。"""
    __tablename__ = "rmb_compliance_check"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reimbursement_id = Column(Integer, ForeignKey("rmb_reimbursement.id"), nullable=False, index=True)
    check_no = Column(Integer, default=1)
    policy_id = Column(Integer, ForeignKey("rmb_policy.id"), nullable=True)

    model = Column(String(64), default="")
    facts_json = Column(Text, default="{}")           # 程序计算的事实
    program_flags_json = Column(Text, default="{}")   # 程序对量化规则的触发判断
    ai_raw_text = Column(Text, default="")            # 大模型原始输出
    ai_overall_result = Column(String(16), default="")  # AI 自己给的结论（仅记录）
    overall_result = Column(String(16), default="")     # 程序汇总的结论（以此为准）
    summary = Column(Text, default="")
    inconsistency_count = Column(Integer, default=0)
    elapsed = Column(Float, default=0)

    checked_by = Column(String(64), default="")
    checked_at = Column(DateTime, default=func.now())

    handle_action = Column(String(32), default="")  # 提交制证/补充说明/修改重判/人工覆盖/作废
    handle_comment = Column(Text, default="")
    handled_by = Column(String(64), default="")
    handled_at = Column(DateTime, nullable=True)


class RmbComplianceIssue(Base):
    """判读明细表：每次判读中每条规则的结论、理由和提示。"""
    __tablename__ = "rmb_compliance_issue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    check_id = Column(Integer, ForeignKey("rmb_compliance_check.id", ondelete="CASCADE"),
                      nullable=False, index=True)

    rule_code = Column(String(16), default="")
    check_item = Column(String(64), default="")
    clause_no = Column(String(32), default="")
    result = Column(String(16), default="")      # 合规/需关注/不合规/不适用
    reason = Column(Text, default="")
    suggestion = Column(Text, default="")
    evidence = Column(Text, default="")
    program_triggered = Column(Integer, nullable=True)  # 1/0/NULL（NULL=无程序校验）
    consistency = Column(String(16), default="未校验")    # 一致/不一致/未校验
    sort_no = Column(Integer, default=0)


class RmbVoucher(Base):
    """凭证主表。凭证号由程序在事务中生成，大模型不参与编号。"""
    __tablename__ = "rmb_voucher"
    __table_args__ = (
        UniqueConstraint("period", "voucher_word", "voucher_no", name="uq_rmb_voucher_no"),
        UniqueConstraint("reimbursement_id", name="uq_rmb_voucher_rmb"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    voucher_word = Column(String(8), default="记")
    period = Column(String(8), default="")            # YYYY-MM
    voucher_no = Column(Integer, default=0)
    voucher_code = Column(String(32), unique=True, default="")  # 记-202610-0001
    voucher_date = Column(String(10), default="")
    attachment_count = Column(Integer, default=0)

    reimbursement_id = Column(Integer, ForeignKey("rmb_reimbursement.id"), nullable=False, index=True)
    compliance_check_id = Column(Integer, ForeignKey("rmb_compliance_check.id"), nullable=True)

    total_debit = Column(Float, default=0)
    total_credit = Column(Float, default=0)

    ai_model = Column(String(64), default="")
    ai_raw_json = Column(Text, default="")
    ai_explanation = Column(Text, default="")
    ai_tax_treatment = Column(Text, default="")

    status = Column(String(16), default="未复核", index=True)  # 未复核/已复核/已退回
    maker = Column(String(64), nullable=False, default="")
    made_at = Column(DateTime, default=func.now())

    reviewer = Column(String(64), default="")
    reviewed_at = Column(DateTime, nullable=True)
    review_comment = Column(Text, default="")


class RmbVoucherEntry(Base):
    """凭证分录表。"""
    __tablename__ = "rmb_voucher_entry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    voucher_id = Column(Integer, ForeignKey("rmb_voucher.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    line_no = Column(Integer, default=1)
    summary = Column(String(128), default="")
    subject_code = Column(String(16), default="")
    subject_name = Column(String(128), default="")
    debit_amount = Column(Float, default=0)
    credit_amount = Column(Float, default=0)


__all__ = [
    "RmbDepartment", "RmbEmployee", "RmbAccountSubject", "RmbExpenseType",
    "RmbSettlementMethod", "RmbCityLevel", "RmbHoliday", "RmbSysParam",
    "RmbPolicy", "RmbPolicyRule",
    "RmbReimbursement", "RmbInvoice", "RmbComplianceCheck", "RmbComplianceIssue",
    "RmbVoucher", "RmbVoucherEntry",
]
