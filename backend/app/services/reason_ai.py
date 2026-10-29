"""AI 生成报销事由：根据填单页已填写的信息与票据识别结果，生成一段规范的报销事由。

定位与边界：
- 只生成「报销事由」这一句文案，不做任何业务判断，结果由报销人核对修改后再保存；
- 输入信息不足时，提示模型输出概括性事由，不编造单位、人物、行程；
- 调用失败由 API 层转成中文提示，不阻断填单（用户可手填）。

模型与网关复用 `llm_client_new`（文本模型，默认 qwen-plus，可用 RULE_MODEL 覆盖）。
"""
import re

from app.services.llm_client_new import LLMError, chat_text, rule_model

#: 允许生成的最大长度（报销单 reason 字段为 200，留出编辑余量）
MAX_REASON_LEN = 200

SYSTEM_PROMPT = (
    "你是箱包制造企业的费用报销助理，负责把报销单信息整理成规范、简洁的报销事由。"
    "只输出事由文本本身，不要输出解释、前缀、引号或任何多余文字。"
)

PROMPT_TEMPLATE = """请根据下面的报销单信息，生成一段简洁、规范的报销事由。

要求：
1. 只输出一句话，控制在 20～60 个汉字，最多 {max_len} 字；
2. 尽量包含费用发生的时间（月份或日期）、地点（如有）、事项与费用性质；
3. 只能使用下面提供的信息，不得编造单位名称、人物、行程；
4. 不要加引号、不要加“报销事由：”之类的前缀、不要输出解释或换行；
5. 参考示例：「10 月赴上海出差住宿费（10-12 至 10-15，共 3 晚）」「6 月招待杭州客户餐费（3 人）」；
6. 信息不足时直接省略缺失的部分，不要写“信息缺失”“未知”“待补充”等字样，
   例如只有费用类型时输出「差旅住宿费报销」即可。

报销单信息：
{info}"""

#: 模型偶尔会把「信息不足」写进正文，命中这些词时改由程序拼兜底事由，避免出现负面表述
_PLACEHOLDER_MARKERS = ("信息缺失", "信息不足", "具体时间", "具体地点", "未知", "待补充", "无法确定", "暂缺")


def _fmt_amount(value) -> str:
    """金额格式化为两位小数字符串；无值返回空串。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number <= 0:
        return ""
    return f"{number:.2f}"


def _add(lines: list, label: str, value) -> None:
    """把非空信息追加成「- 标签：值」一行，空值跳过。"""
    text = str(value or "").strip()
    if text and text != "0":
        lines.append(f"- {label}：{text}")


def build_info(context: dict) -> str:
    """把报销单上下文整理成提示词里的「报销单信息」段落。"""
    context = context or {}
    invoice = context.get("invoice") or {}
    lines: list[str] = []

    _add(lines, "费用类型", context.get("expense_type_name"))
    _add(lines, "费用发生日期", context.get("occur_date"))
    _add(lines, "报销金额（元）", _fmt_amount(context.get("amount")))
    _add(lines, "出差地点", context.get("travel_city"))
    if context.get("travel_start") or context.get("travel_end"):
        _add(lines, "出差起止", f"{context.get('travel_start') or '?'} 至 {context.get('travel_end') or '?'}")
    nights = context.get("nights")
    if nights:
        _add(lines, "住宿晚数", f"{int(nights)} 晚")
    _add(lines, "招待对象单位", context.get("guest_company"))
    guest_count = context.get("guest_count")
    if guest_count:
        _add(lines, "陪同人数", f"{int(guest_count)} 人")

    _add(lines, "票据类型", invoice.get("document_type"))
    _add(lines, "票据销售方", invoice.get("seller_name"))
    _add(lines, "票据开票日期", invoice.get("issue_date"))
    _add(lines, "票据消费城市", invoice.get("consume_city"))
    _add(lines, "乘车人", invoice.get("passenger_name"))
    if invoice.get("travel_from") or invoice.get("travel_to"):
        _add(lines, "行程", f"{invoice.get('travel_from') or '?'} → {invoice.get('travel_to') or '?'}")
    _add(lines, "入住 / 离店", " / ".join(
        x for x in (invoice.get("checkin_date"), invoice.get("checkout_date")) if x))
    if invoice.get("remark"):
        _add(lines, "票据备注", invoice.get("remark"))

    if not lines:
        return "- 信息较少，请生成一段概括性的费用报销事由"
    return "\n".join(lines)


def clean_reason(text: str) -> str:
    """清理模型输出：去前缀/引号/多余空白，并限制长度。"""
    s = str(text or "").strip()
    if not s:
        return ""
    # 去掉可能的「报销事由：」前缀与包裹引号、Markdown 代码块
    s = re.sub(r"^```(?:\w+)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    s = re.sub(r"^(报销事由|事由)\s*[:：]\s*", "", s.strip())
    s = s.strip().strip('"“”\'‘’「」')
    # 一句话：换行与连续空白压成单个空格
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > MAX_REASON_LEN:
        s = s[:MAX_REASON_LEN]
    return s


def fallback_reason(context: dict) -> str:
    """信息不足或模型输出不可用时的兜底事由：用已填信息拼一句简短描述。

    例：费用类型「差旅住宿费」+ 发生日期 + 出差地点 → 「10月赴上海差旅住宿费报销」。
    """
    context = context or {}
    name = str(context.get("expense_type_name") or "费用").strip() or "费用"
    parts: list[str] = []
    occur = str(context.get("occur_date") or "").strip()
    if len(occur) >= 7 and occur[4] == "-":
        try:
            parts.append(f"{int(occur[5:7])}月")
        except ValueError:
            pass
    city = str(context.get("travel_city") or "").strip()
    if city:
        parts.append(f"赴{city}")
    reason = "".join(parts) + name
    if "报销" not in reason:
        reason += "报销"
    amount = _fmt_amount(context.get("amount"))
    if amount:
        reason += f"（{amount} 元）"
    return reason[:MAX_REASON_LEN]


def suggest_reason(context: dict) -> dict:
    """调用文本模型生成报销事由，返回 {"reason": 事由, "model": 模型名}。

    生成失败（模型报错 / 返回空 / 输出占位说明）时用程序兜底拼接，
    保证按钮总能给出可用文案；兜底也不可用才抛 LLMError。
    """
    info = build_info(context)
    prompt = PROMPT_TEMPLATE.format(max_len=MAX_REASON_LEN, info=info)
    model = rule_model()
    text = chat_text(prompt, model=model, system=SYSTEM_PROMPT)
    reason = clean_reason(text)
    # 模型偶尔把「信息缺失」等占位说明写进正文：改用程序兜底，避免出现负面表述
    if not reason or any(marker in reason for marker in _PLACEHOLDER_MARKERS):
        reason = fallback_reason(context)
    if not reason:
        raise LLMError("大模型未生成有效的报销事由，请重试或手工填写")
    return {"reason": reason, "model": model}
