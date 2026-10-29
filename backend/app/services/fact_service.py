"""判读事实计算服务（纯程序，不调用大模型）。

对应实验指导书表 5-3「程序计算的事实数据」。合规判读分四个阶段，本模块是第一阶段：
大模型不擅长精确的日期推算和数值计算，也不能直接查询数据库中的历史报销单，
因此星期、节假日、人均金额、每晚金额、关联报销单、重复报销等「事实」必须由程序算好，
再连同原始数据一起交给大模型判读。程序算错，AI 的结论一定错。

对外提供两个函数：
- `compute_facts(db, reimbursement_id)`：算出全部事实（dict，可直接 json.dumps 入库）；
- `program_flags_from_facts(facts, params)`：对 R01～R09 这 9 条量化规则独立判断触发条件，
  用于对 AI 结论做交叉校验（不考虑特批等例外，例外交给 AI 阅读制度原文判断）。

设计约束：
- 金额一律用 decimal.Decimal 计算，输出时转两位小数的 float（便于 JSON 序列化）；
- 阈值全部从 rmb_sys_param 读取，任何金额/天数都不写死在代码里；
- 与费用类型无关的规则不出现在 program_flags 中（差旅单不返回 R03～R05）。
"""
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy.orm import Session

from app.core.exceptions import BizException
from app.models.reimburse import (
    RmbCityLevel,
    RmbEmployee,
    RmbExpenseType,
    RmbHoliday,
    RmbInvoice,
    RmbReimbursement,
    RmbSettlementMethod,
    RmbSysParam,
)

# 审批层级 → 排序值（部门负责人、财务复核为 1，部门总监为 2，总经理为 3）
APPROVER_RANK = {
    "部门负责人": 1,
    "财务复核": 1,
    "部门总监": 2,
    "总经理": 3,
}

# 星期中文名（date.weekday()：0=星期一）
WEEKDAY_CN = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")

# 已作废状态不参与拆分/重复检查
VOID_STATUS = "已作废"

# 参数默认值：仅当 rmb_sys_param 缺项时兜底，正常情况一律以数据库为准
PARAM_DEFAULTS = {
    "approval_level2_amount": "5000",
    "approval_level3_amount": "20000",
    "entertain_per_capita_limit": "300",
    "entertain_single_limit": "2000",
    "split_days_window": "3",
    "company_name": "",
    "company_tax_id": "",
}

TWO = Decimal("0.01")


# ---------------------------------------------------------------- 数值与日期工具
def to_decimal(value, default: Decimal | None = None) -> Decimal | None:
    """把任意数值/字符串转成 Decimal；无法转换时返回 default。"""
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    s = str(value).strip().replace(",", "").replace("¥", "").replace("￥", "")
    if not s:
        return default
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return default


def money(value) -> Decimal:
    """金额统一量化为两位小数（四舍五入到分）。"""
    d = to_decimal(value, Decimal("0"))
    return (d or Decimal("0")).quantize(TWO, rounding=ROUND_HALF_UP)


def money_float(value) -> float:
    """金额输出为 float（两位小数），便于 json.dumps 与前端展示。"""
    return float(money(value))


def parse_date(value) -> datetime | None:
    """把 YYYY-MM-DD 解析为 datetime；非法返回 None。"""
    s = str(value or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def date_diff_days(later, earlier) -> int | None:
    """两个日期相差的天数（later - earlier）；任一非法返回 None。"""
    a, b = parse_date(later), parse_date(earlier)
    if a is None or b is None:
        return None
    return (a - b).days


# ---------------------------------------------------------------- 参数与基础数据
def load_params(db: Session) -> dict:
    """读取系统参数表（阈值），缺项用默认值兜底。

    返回 dict 同时包含原始字符串与转换后的数值/Decimal：
    - `approval_level2_amount` 等数值键为 Decimal（便于金额比较）；
    - `split_days_window` 为 int；
    - `company_name` / `company_tax_id` 为字符串。
    """
    rows = db.query(RmbSysParam).all()
    raw = {r.param_key: (r.param_value or "") for r in rows}
    merged = dict(PARAM_DEFAULTS)
    merged.update({k: v for k, v in raw.items() if v not in (None, "")})

    params = {
        "company_name": merged.get("company_name", ""),
        "company_tax_id": merged.get("company_tax_id", ""),
        "approval_level2_amount": to_decimal(merged.get("approval_level2_amount"), Decimal("5000")),
        "approval_level3_amount": to_decimal(merged.get("approval_level3_amount"), Decimal("20000")),
        "entertain_per_capita_limit": to_decimal(merged.get("entertain_per_capita_limit"), Decimal("300")),
        "entertain_single_limit": to_decimal(merged.get("entertain_single_limit"), Decimal("2000")),
        "split_days_window": int(to_decimal(merged.get("split_days_window"), Decimal("3")) or 3),
        "default_voucher_word": merged.get("default_voucher_word", "记") or "记",
    }
    return params


def _param_dec(params: dict, key: str, default: str) -> Decimal:
    """从参数表取值并转 Decimal（兼容手工传入的 int/float/str）。"""
    return to_decimal(params.get(key), to_decimal(default, Decimal("0"))) or Decimal("0")


def _param_int(params: dict, key: str, default: int) -> int:
    """从参数表取值并转 int。"""
    d = to_decimal(params.get(key), Decimal(str(default)))
    return int(d) if d is not None else default


def required_rank_of(amount, params: dict) -> int:
    """按金额求所需审批层级：< L2 为 1，< L3 为 2，否则 3（制度第四条）。"""
    a = money(amount)
    l2 = _param_dec(params, "approval_level2_amount", "5000")
    l3 = _param_dec(params, "approval_level3_amount", "20000")
    if a < l2:
        return 1
    if a < l3:
        return 2
    return 3


def approver_rank_of(approver_level: str) -> int:
    """审批层级名称 → 排序值；未填写或无法识别返回 0（会被 R01 判为不匹配）。"""
    name = str(approver_level or "").strip()
    if name in APPROVER_RANK:
        return APPROVER_RANK[name]
    # 容错：数据库里可能存成“部门负责人（陈静）”这类带备注的写法
    for key, rank in APPROVER_RANK.items():
        if key and key in name:
            return rank
    return 0


def _get_bill(db: Session, reimbursement_id: int) -> RmbReimbursement:
    """取报销单，不存在时抛业务异常。"""
    bill = db.query(RmbReimbursement).filter(
        RmbReimbursement.id == reimbursement_id
    ).first()
    if not bill:
        raise BizException(f"报销单不存在（id={reimbursement_id}），请刷新后重试")
    return bill


# ---------------------------------------------------------------- 各维度事实
def _basic_facts(db: Session, bill: RmbReimbursement, params: dict) -> dict:
    """基本事实：费用类型、金额、发票、审批层级。"""
    expense_type = None
    special_info = "无"
    if bill.expense_type_id:
        expense_type = db.query(RmbExpenseType).filter(
            RmbExpenseType.id == bill.expense_type_id
        ).first()
        if expense_type:
            special_info = expense_type.special_info or "无"

    invoice = db.query(RmbInvoice).filter(
        RmbInvoice.reimbursement_id == bill.id
    ).first()

    amount = money(bill.amount)
    approver_rank = approver_rank_of(bill.approver_level)
    return {
        "expense_type": expense_type.name if expense_type else "",
        "special_info": special_info,
        "amount": float(amount),
        "has_invoice": bool(bill.has_invoice),
        "is_invoice": bool(invoice.is_invoice) if invoice else None,
        "approver_name": bill.approver_name or "",
        "approver_level": bill.approver_level or "",
        "approver_rank": approver_rank,
        "required_rank": required_rank_of(amount, params),
    }


def _date_facts(db: Session, bill: RmbReimbursement) -> dict:
    """日期事实：星期、周末、节假日、调休上班日、报销时效。"""
    occur = parse_date(bill.occur_date)
    bill_day = parse_date(bill.bill_date)
    facts = {
        "occur_date": bill.occur_date or "",
        "weekday": "",
        "is_weekend": False,
        "holiday_name": "",
        "is_adjusted_workday": False,
        "bill_date": bill.bill_date or "",
        "cross_year": False,
        "days_from_occur_to_bill": None,
    }
    if occur:
        facts["weekday"] = WEEKDAY_CN[occur.weekday()]
        facts["is_weekend"] = occur.weekday() >= 5
    if bill_day and occur:
        facts["cross_year"] = occur.year != bill_day.year
        facts["days_from_occur_to_bill"] = (bill_day - occur).days

    # 节假日表：法定节假日 / 调休上班日
    if bill.occur_date:
        holiday = db.query(RmbHoliday).filter(
            RmbHoliday.holiday_date == bill.occur_date
        ).first()
        if holiday:
            day_type = holiday.day_type or ""
            if day_type == "法定节假日":
                facts["holiday_name"] = holiday.holiday_name or "法定节假日"
            elif day_type == "调休上班日":
                facts["is_adjusted_workday"] = True
                # 调休上班日也是“周六/周日”，但事实上要按工作日理解，
                # 单独给出名称供 AI 引用制度第八条时说明理由。
                facts["holiday_name"] = ""
    return facts


def _travel_facts(db: Session, bill: RmbReimbursement, special_info: str) -> dict:
    """差旅事实：出差城市等级、住宿标准、晚数、每晚金额、出差天数。

    只有「差旅」类费用且填了出差城市时才去查城市等级表；
    否则 city_level / lodging_limit / per_night_amount 一律为 None，
    避免给招待单、办公费单塞一个无意义的“其他城市 400 元”标准，误导 AI 判读。
    """
    city = (bill.travel_city or "").strip()
    city_row = None
    city_level = None
    lodging_limit = None
    if city:
        city_row = db.query(RmbCityLevel).filter(
            RmbCityLevel.city_name == city
        ).first()
        if city_row is None:
            # 模糊匹配（如“上海市”对“上海”），仍找不到则走“其他城市”兜底
            for row in db.query(RmbCityLevel).all():
                name = row.city_name or ""
                if name and (name in city or city in name):
                    city_row = row
                    break
        if city_row is None:
            city_row = db.query(RmbCityLevel).filter(
                RmbCityLevel.city_name == "其他城市"
            ).first()
        if city_row is not None:
            city_level = city_row.city_level
            lodging_limit = float(money(city_row.lodging_limit))

    nights = int(bill.nights or 0)
    amount = money(bill.amount)
    per_night = None
    if nights > 0:
        per_night = (amount / Decimal(nights)).quantize(TWO, rounding=ROUND_HALF_UP)

    travel_days = None
    if bill.travel_start and bill.travel_end:
        diff = date_diff_days(bill.travel_end, bill.travel_start)
        if diff is not None:
            travel_days = diff + 1

    return {
        "travel_city": city,
        "city_level": city_level,
        "lodging_limit": lodging_limit,
        "nights": nights,
        "per_night_amount": float(per_night) if per_night is not None else None,
        "travel_start": bill.travel_start or "",
        "travel_end": bill.travel_end or "",
        "travel_days": travel_days,
    }


def _entertain_facts(bill: RmbReimbursement) -> dict:
    """招待事实：招待对象、陪同人数、人均金额。"""
    guest_count = int(bill.guest_count or 0)
    per_capita = None
    if guest_count > 0:
        per_capita = (money(bill.amount) / Decimal(guest_count)).quantize(
            TWO, rounding=ROUND_HALF_UP)
    return {
        "guest_company": bill.guest_company or "",
        "guest_count": guest_count,
        "per_capita_amount": float(per_capita) if per_capita is not None else None,
    }


def _related_claims(db: Session, bill: RmbReimbursement, params: dict) -> dict:
    """拆分报销事实：同人同类型、日期相近的其他有效报销单。

    制度第五条：不得将同一事项/同一供应商/同期发生的费用人为拆分以规避审批权限。
    程序这里只做“相近日期 + 同人同类型”的机械筛选，是否构成拆分（是否同一事项）
    仍需 AI 结合事由与制度第五条判断。
    """
    window = _param_int(params, "split_days_window", 3)
    occur = parse_date(bill.occur_date)
    if bill.employee_id is None or bill.expense_type_id is None or occur is None:
        return {"related_claims": [], "combined_amount": money_float(bill.amount),
                "combined_required_rank": required_rank_of(bill.amount, params)}

    candidates = db.query(RmbReimbursement).filter(
        RmbReimbursement.employee_id == bill.employee_id,
        RmbReimbursement.expense_type_id == bill.expense_type_id,
        RmbReimbursement.id != bill.id,
        RmbReimbursement.status != VOID_STATUS,
    ).all()

    related = []
    combined = money(bill.amount)
    for other in candidates:
        diff = date_diff_days(other.occur_date, bill.occur_date)
        if diff is None or abs(diff) > window:
            continue
        related.append({
            "bill_no": other.bill_no,
            "occur_date": other.occur_date or "",
            "amount": money_float(other.amount),
            "approver_level": other.approver_level or "",
            "approver_rank": approver_rank_of(other.approver_level),
            "date_diff_days": diff,
        })
        combined += money(other.amount)

    related.sort(key=lambda x: (x["occur_date"], x["bill_no"]))
    return {
        "related_claims": related,
        "related_claim_count": len(related),
        "combined_amount": money_float(combined),
        "combined_required_rank": required_rank_of(combined, params),
    }


def _duplicate_claims(db: Session, bill: RmbReimbursement) -> dict:
    """重复报销事实：同人 + 同金额 + 同费用类型 + 同发生日期，但单号不同。"""
    amount = money(bill.amount)
    if bill.employee_id is None or bill.expense_type_id is None or not bill.occur_date:
        return {"duplicate_claims": []}

    candidates = db.query(RmbReimbursement).filter(
        RmbReimbursement.employee_id == bill.employee_id,
        RmbReimbursement.expense_type_id == bill.expense_type_id,
        RmbReimbursement.occur_date == bill.occur_date,
        RmbReimbursement.id != bill.id,
        RmbReimbursement.status != VOID_STATUS,
    ).all()

    dups = []
    for other in candidates:
        if money(other.amount) != amount:
            continue
        dups.append({
            "bill_no": other.bill_no,
            "occur_date": other.occur_date or "",
            "amount": money_float(other.amount),
            "status": other.status or "",
            "compliance_result": other.compliance_result or "",
        })
    dups.sort(key=lambda x: x["bill_no"])
    return {"duplicate_claims": dups}


def _missing_fields(bill: RmbReimbursement, special_info: str,
                    invoice: RmbInvoice | None, expense_type: str = "") -> dict:
    """要素缺失检查，按规则归类（供 R10/R11/R12 的 AI 判读引用）。"""
    travel_missing: list[str] = []
    entertain_missing: list[str] = []
    common_missing: list[str] = []

    # ---- R12 通用要素：制度第十三条 ----
    if not (bill.bill_no or "").strip():
        common_missing.append("报销单号")
    if not (bill.bill_date or "").strip():
        common_missing.append("报销日期")
    if bill.employee_id is None:
        common_missing.append("报销人")
    if bill.department_id is None:
        common_missing.append("部门")
    if bill.expense_type_id is None:
        common_missing.append("费用类型")
    if not (bill.reason or "").strip():
        common_missing.append("报销事由")
    if not (bill.occur_date or "").strip():
        common_missing.append("费用发生日期")
    if money(bill.amount) <= 0:
        common_missing.append("报销金额")
    if bill.has_invoice is None:
        common_missing.append("是否附发票")
    if not (bill.approver_name or "").strip():
        common_missing.append("审批人")
    if not (bill.approver_level or "").strip():
        common_missing.append("审批层级")

    # ---- R11 差旅要素：制度第十条 ----
    # 住宿晚数只对「差旅住宿费」有意义，差旅交通费不要求填晚数
    if special_info == "差旅":
        if not (bill.reason or "").strip():
            travel_missing.append("出差事由")
        if not (bill.travel_start or "").strip():
            travel_missing.append("出差开始日期")
        if not (bill.travel_end or "").strip():
            travel_missing.append("出差结束日期")
        if not (bill.travel_city or "").strip():
            travel_missing.append("出差地点")
        if expense_type == "差旅住宿费" and not int(bill.nights or 0):
            travel_missing.append("住宿晚数")

    # ---- R10 招待要素：制度第六条 ----
    if special_info == "招待":
        if not (bill.reason or "").strip():
            entertain_missing.append("招待事由")
        if not (bill.guest_company or "").strip():
            entertain_missing.append("招待对象单位")
        if not int(bill.guest_count or 0):
            entertain_missing.append("陪同人数")

    # ---- 票据要素（供 R13 参考） ----
    invoice_missing: list[str] = []
    if invoice is None:
        if bill.has_invoice:
            invoice_missing.append("票据信息（已选附发票但未上传票据）")
    else:
        if not (invoice.invoice_number or "").strip() and invoice.is_invoice:
            invoice_missing.append("发票号码")
        if not (invoice.issue_date or "").strip():
            invoice_missing.append("开票日期")
        if money(invoice.total_amount) <= 0:
            invoice_missing.append("价税合计")

    all_fields = common_missing + travel_missing + entertain_missing
    return {
        "missing_fields": all_fields,
        "missing_by_rule": {
            "R10": entertain_missing,
            "R11": travel_missing,
            "R12": common_missing,
            "R13": invoice_missing,
        },
    }


def _same_text(a: str, b: str) -> bool:
    """宽松的文本一致性比较：去空白、去“市/省”等常见后缀后互相包含即视为一致。"""
    def clean(s: str) -> str:
        s = str(s or "").replace("　", "").replace(" ", "").strip()
        for suffix in ("市", "省", "自治区", "特别行政区"):
            if s.endswith(suffix) and len(s) > len(suffix) + 1:
                s = s[: -len(suffix)]
        return s

    x, y = clean(a), clean(b)
    if not x or not y:
        return None            # 信息不足，不做判断（None 表示“无法核对”）
    return x == y or x in y or y in x


def _name_matched(passenger: str, employee_name: str) -> bool | None:
    """乘车人是否为本报销人（支持“王五”与“王*五”等脱敏写法）。"""
    p = str(passenger or "").strip()
    e = str(employee_name or "").strip()
    if not p or not e:
        return None
    if p == e:
        return True
    # 脱敏姓名：含 * 或 X 时按首末字比对
    if "*" in p or "x" in p.lower():
        stripped = p.replace("*", "").replace("x", "").replace("X", "")
        if stripped and (stripped[0] == e[0] and stripped[-1] == e[-1]):
            return True
    return False


def _invoice_diffs(db: Session, bill: RmbReimbursement, invoice: RmbInvoice | None,
                   facts: dict) -> dict:
    """票据与报销信息的一致性事实（R13 用）。

    - amount_diff：票据价税合计 - 报销金额
    - date_diff_days：按费用类型取最相关的票据日期（住宿取入住、交通取乘车、其他取开票）
      与费用发生日期之差
    - buyer_matched：购买方是否本单位
    - passenger_matched：乘车人是否报销人
    - city_matched：票据消费城市是否出差城市
    - nights_matched：票面晚数与填报晚数是否一致
    """
    empty = {
        "has_invoice_record": invoice is not None,
        "amount_diff": None,
        "date_diff_days": None,
        "buyer_matched": None,
        "passenger_matched": None,
        "city_matched": None,
        "nights_matched": None,
        "invoice_total_amount": None,
        "bill_amount": money_float(bill.amount),
    }
    if invoice is None:
        return empty

    employee = None
    if bill.employee_id:
        employee = db.query(RmbEmployee).filter(RmbEmployee.id == bill.employee_id).first()

    amount_diff = money(invoice.total_amount) - money(bill.amount)

    # 相关日期：住宿类看入住，交通类看乘车，其余看开票
    expense_type = facts.get("expense_type") or ""
    related_date = ""
    if expense_type == "差旅住宿费" and invoice.checkin_date:
        related_date = invoice.checkin_date
    elif expense_type == "差旅交通费" and invoice.travel_date:
        related_date = invoice.travel_date
    else:
        related_date = invoice.issue_date or invoice.travel_date or invoice.checkin_date

    result = dict(empty)
    result.update({
        "has_invoice_record": True,
        "invoice_total_amount": money_float(invoice.total_amount),
        "amount_diff": float(amount_diff),
        "date_diff_days": date_diff_days(related_date, bill.occur_date),
        "buyer_matched": _same_text(invoice.buyer_name, facts.get("company_name", "")),
        "passenger_matched": _name_matched(invoice.passenger_name,
                                           employee.name if employee else ""),
        "city_matched": _same_text(invoice.consume_city, bill.travel_city),
        "nights_matched": (
            int(invoice.nights or 0) == int(bill.nights or 0)
            if int(invoice.nights or 0) > 0 and int(bill.nights or 0) > 0 else None
        ),
    })
    return result


# ---------------------------------------------------------------- 对外主函数
def compute_facts(db: Session, reimbursement_id: int) -> dict:
    """计算一张报销单的全部判读事实（表 5-3）。

    返回的 dict 可直接写入 rmb_compliance_check.facts_json。
    数据缺失的字段填 None 或空串，而不是省略键——下游提示词与前端直接据此展示。
    """
    bill = _get_bill(db, reimbursement_id)
    params = load_params(db)

    basic = _basic_facts(db, bill, params)
    dates = _date_facts(db, bill)
    travel = _travel_facts(db, bill, basic["special_info"])
    entertain = _entertain_facts(bill)
    related = _related_claims(db, bill, params)
    duplicate = _duplicate_claims(db, bill)

    invoice = db.query(RmbInvoice).filter(
        RmbInvoice.reimbursement_id == bill.id
    ).first()
    missing = _missing_fields(bill, basic["special_info"], invoice,
                              basic["expense_type"])

    # 公司信息放在事实里，既供 R13 比对，也供提示词使用
    facts: dict = {
        "reimbursement_id": bill.id,
        "bill_no": bill.bill_no or "",
        "employee_name": "",
        "department_name": "",
        "expense_type_id": bill.expense_type_id,
        "settlement_method_name": "",
        "settlement_subject_code": "",
        "reason": bill.reason or "",
        "special_approver": bill.special_approver or "",
        "explanation": bill.explanation or "",
        "company_name": params.get("company_name", ""),
        "company_tax_id": params.get("company_tax_id", ""),
        "override_flag": bool(bill.override_flag),
        "status": bill.status or "",
        "compliance_result": bill.compliance_result or "",
    }
    if bill.employee_id:
        emp = db.query(RmbEmployee).filter(RmbEmployee.id == bill.employee_id).first()
        if emp:
            facts["employee_name"] = emp.name or ""
            facts["department_name"] = _department_name(db, emp.department_id)
    if bill.settlement_method_id:
        settle = db.query(RmbSettlementMethod).filter(
            RmbSettlementMethod.id == bill.settlement_method_id
        ).first()
        if settle:
            facts["settlement_method_name"] = settle.name or ""
            facts["settlement_subject_code"] = settle.subject_code or ""

    facts.update(basic)
    facts.update(dates)
    facts.update(travel)
    facts.update(entertain)
    facts.update(related)
    facts.update(duplicate)
    facts.update(missing)
    facts["invoice_diffs"] = _invoice_diffs(db, bill, invoice, facts)
    return facts


def _department_name(db: Session, department_id) -> str:
    """取部门名称（导入放在函数内，避免与模型层循环引用）。"""
    if not department_id:
        return ""
    from app.models.reimburse import RmbDepartment

    row = db.query(RmbDepartment).filter(RmbDepartment.id == department_id).first()
    return row.name if row else ""


# ---------------------------------------------------------------- 程序触发判断
def program_flags_from_facts(facts: dict, params: dict) -> dict:
    """对 R01～R09 判断触发条件是否成立（不考虑特批等例外，例外交给 AI 判断）。

    返回 dict：rule_code -> bool。与费用类型无关的规则不出现在结果中
    （例如差旅单不返回 R03～R05），这样 AI 的“不适用”与程序的“无校验”不会混淆。

    判断口径（与制度第五条至第九条对应）：
    - R01 审批越权：审批层级排序 < 所需层级
    - R02 拆分报销：关联单合计后的所需层级 > 本单审批层级
    - R03 招待人均超标：人均 > 人均标准
    - R04 招待单次超标：金额 > 单次标准
    - R05 周末/节假日招待：周六日或法定节假日
    - R06 住宿超标：每晚金额 > 城市住宿标准
    - R07 缺发票：未附发票（或票据不是发票）
    - R08 跨期报销：报销日期与发生日期不同年
    - R09 疑似重复：存在同人同金额同类型同日期其他单
    """
    if not isinstance(facts, dict):
        return {}
    flags: dict[str, bool] = {}

    amount = money(facts.get("amount"))
    approver_rank = int(facts.get("approver_rank") or 0)
    required_rank = int(facts.get("required_rank") or 0)
    combined_rank = int(facts.get("combined_required_rank") or 0)

    flags["R01"] = approver_rank < required_rank
    flags["R02"] = combined_rank > required_rank

    expense_type = str(facts.get("expense_type") or "")
    special_info = str(facts.get("special_info") or "")

    if expense_type == "业务招待费" or special_info == "招待":
        per_capita = to_decimal(facts.get("per_capita_amount"))
        capita_limit = _param_dec(params, "entertain_per_capita_limit", "300")
        flags["R03"] = per_capita is not None and per_capita > capita_limit
        flags["R04"] = amount > _param_dec(params, "entertain_single_limit", "2000")
        # 第八条约束的是「周末及法定节假日」招待。调休上班日虽然也是周六/周日，
        # 但当天是法定工作日，不构成制度所说的“周末”，故排除；
        # is_adjusted_workday 仍作为事实交给 AI，由它在理由中说明判断依据（T07）。
        on_weekend = bool(facts.get("is_weekend")) and not bool(facts.get("is_adjusted_workday"))
        flags["R05"] = on_weekend or bool(facts.get("holiday_name"))

    if expense_type == "差旅住宿费":
        per_night = to_decimal(facts.get("per_night_amount"))
        lodging_limit = to_decimal(facts.get("lodging_limit"))
        if per_night is not None and lodging_limit is not None:
            flags["R06"] = per_night > lodging_limit

    has_invoice = bool(facts.get("has_invoice"))
    is_invoice = facts.get("is_invoice")
    flags["R07"] = (not has_invoice) or (is_invoice is False)

    flags["R08"] = bool(facts.get("cross_year"))

    duplicates = facts.get("duplicate_claims") or []
    flags["R09"] = len(duplicates) > 0

    return flags


def facts_summary(facts: dict) -> str:
    """把关键事实拼成一句话，供日志与页面摘要使用。"""
    parts = [
        f"金额 {facts.get('amount', 0):.2f} 元",
        f"发生日期 {facts.get('occur_date', '')}（{facts.get('weekday', '')}）",
    ]
    if facts.get("holiday_name"):
        parts.append(f"节假日：{facts['holiday_name']}")
    if facts.get("is_adjusted_workday"):
        parts.append("调休上班日")
    if facts.get("per_night_amount") is not None:
        parts.append(f"每晚 {facts['per_night_amount']:.2f} 元（上限 {facts.get('lodging_limit')}）")
    if facts.get("per_capita_amount") is not None:
        parts.append(f"人均 {facts['per_capita_amount']:.2f} 元")
    if facts.get("duplicate_claims"):
        parts.append(f"疑似重复 {len(facts['duplicate_claims'])} 张")
    return "；".join(parts)


def dump_facts(facts: dict) -> str:
    """facts 转 JSON 字符串（入库与日志用，中文不转义）。"""
    return json.dumps(facts, ensure_ascii=False, default=str)


if __name__ == "__main__":
    # 手工验证：python -m app.services.fact_service <报销单id>
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        if len(sys.argv) > 1:
            rid = int(sys.argv[1])
        else:
            row = db.query(RmbReimbursement).order_by(RmbReimbursement.id.desc()).first()
            if not row:
                print("数据库中没有报销单，请先创建一张测试报销单")
                sys.exit(0)
            rid = row.id
        f = compute_facts(db, rid)
        print(json.dumps(f, ensure_ascii=False, indent=2, default=str))
        print("\n程序触发判断：", json.dumps(
            program_flags_from_facts(f, load_params(db)), ensure_ascii=False))
        print("事实摘要：", facts_summary(f))
    finally:
        db.close()
