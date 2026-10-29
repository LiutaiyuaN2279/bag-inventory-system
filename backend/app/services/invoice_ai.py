"""AI 票据识别服务（差旅与业务招待费报销场景）。

职责划分（与实验指导书步骤 4 对应）：
1. `recognize_invoice()`：调用视觉理解模型，把票据图片识别成结构化 JSON；
2. `check_invoice()`：纯程序校验（不调大模型），做金额规范化、勾稽校验、
   大写比对、日期规范化、晚数核对、购买方核对等；
3. `money_to_chinese()`：小写金额转中文大写，供大写金额比对使用。

设计要点：
- 只做「识别 + 校验」，不写数据库。落库（票据表）由 API 层在事务中完成，
  避免服务层与业务表耦合，也便于单元测试。
- 大模型输出一律当作「待核对的数据」：识别结果先由程序规范化与校验，
  再把 warnings 交给人工在确认页核对，绝不直接采信。
- PDF 票据走双路径（见 `recognize_invoice`）：
  ① 电子发票类 PDF 通常带文本层，用 pypdf 提取文本后交文本模型解析，
     比截图识别更准、更快、也更省 token；
  ② 扫描件 PDF 没有文本层，用 pypdfium2 把首页渲染成 PNG 后交视觉模型识别。
  两个库都是轻量包（pypdfium2 自带预编译二进制，无需外部 poppler）。
- 只使用标准库 urllib（经 llm_client_new 封装），与项目既有 OCR 模块风格一致。
"""
import io
import json
import re
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app.core.config import settings
from app.core.exceptions import BizException
from app.services import llm_client_new
from app.services.llm_client_new import LLMError

# ---------------------------------------------------------------- 常量
# 只允许的票据类型（与实验指导书步骤 4 的枚举一致，顺序不要改动）
DOCUMENT_TYPES = (
    "增值税专用发票",
    "增值税普通发票",
    "电子发票（增值税专用发票）",
    "电子发票（普通发票）",
    "电子发票（铁路电子客票）",
    "航空运输电子客票行程单",
    "出租车发票",
    "定额发票",
    "收据",
    "其他",
)

# 支持的图片扩展名 → MIME
IMAGE_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}

# 视为「合规发票」的类型（收据、定额发票以外的判断交给 is_invoice 字段）
INVOICE_DOC_TYPES = tuple(t for t in DOCUMENT_TYPES if t != "其他")

# 识别结果必须齐备的字段（缺字段补空，避免下游 KeyError）
INVOICE_FIELDS = {
    "document_type": "",
    "is_invoice": True,
    "invoice_code": "",
    "invoice_number": "",
    "issue_date": "",
    "buyer_name": "",
    "buyer_tax_id": "",
    "seller_name": "",
    "seller_tax_id": "",
    "amount_without_tax": 0,
    "tax_rate": "",
    "tax_amount": 0,
    "total_amount": 0,
    "total_amount_cn": "",
    "items": [],
    "passenger_name": "",
    "travel_from": "",
    "travel_to": "",
    "travel_date": "",
    "checkin_date": "",
    "checkout_date": "",
    "nights": 0,
    "consume_city": "",
    "remark": "",
    "suggested_expense_type": "",
}

# 金额比较允许的误差（分）
AMOUNT_TOLERANCE = Decimal("0.01")


# ---------------------------------------------------------------- 提示词
_SYSTEM_PROMPT = (
    "你是箱包制造企业的财务票据识别专家，只负责把票据图像上的信息如实转录为结构化数据。"
    "看不清的字段留空，不要猜测、不要编造。严格只输出 JSON，不要输出解释文字或 Markdown 代码块。"
)

# PDF 文本模式使用的系统提示词：输入是文字不是图像，措辞要相应调整
_PDF_TEXT_SYSTEM_PROMPT = (
    "你是箱包制造企业的财务票据识别专家，只负责把票据 PDF 的文字内容如实提取为结构化数据。"
    "文本中没有的字段留空，不要猜测、不要编造。严格只输出 JSON，不要输出解释文字或 Markdown 代码块。"
)

_PROMPT_TEMPLATE = """请识别这张票据图像，输出一个 JSON 对象，结构如下（字段名与取值必须完全一致）：
{{
  "document_type": "",
  "is_invoice": true,
  "invoice_code": "",
  "invoice_number": "",
  "issue_date": "YYYY-MM-DD",
  "buyer_name": "",
  "buyer_tax_id": "",
  "seller_name": "",
  "seller_tax_id": "",
  "amount_without_tax": 0,
  "tax_rate": "",
  "tax_amount": 0,
  "total_amount": 0,
  "total_amount_cn": "",
  "items": [{{"item_name": "", "quantity": 0, "amount": 0, "tax_amount": 0}}],
  "passenger_name": "",
  "travel_from": "",
  "travel_to": "",
  "travel_date": "YYYY-MM-DD",
  "checkin_date": "YYYY-MM-DD",
  "checkout_date": "YYYY-MM-DD",
  "nights": 0,
  "consume_city": "",
  "remark": "",
  "suggested_expense_type": ""
}}

识别要求：
1. document_type 只能从以下选项中选一个：{doc_types}。
2. is_invoice：**可用于报销的合规凭证一律为 true** —— 增值税专用/普通发票、电子发票，以及**铁路电子客票、航空运输电子客票行程单、出租车票**等铁路/航空/公路客运票据都属于可报销凭证；只有收据、购物小票、付款截图这类非正式凭证才为 false。
3. 金额一律填数字（不带货币符号、不带千分位逗号）：
   amount_without_tax=不含税金额，tax_rate=税率（如 "6%"、"免税"，无则空），
   tax_amount=税额，total_amount=价税合计；total_amount_cn 照抄票面大写金额（如“壹仟陆佰伍拾圆整”）。
4. 日期一律用 YYYY-MM-DD。无法识别或票据上没有的字段填空字符串或 0，不要编造。
5. items 为货物或应税劳务明细，每行含名称、数量、金额、税额。
6. 火车票、机票行程单、出租车票等交通票据必须识别：passenger_name（乘车人）、
   travel_from（出发地）、travel_to（到达地）、travel_date（乘车/乘机日期）。
7. 住宿发票必须识别 checkin_date（入住）、checkout_date（离店）、nights（晚数）、
   consume_city（消费所在城市）。
8. suggested_expense_type 只能从这些费用类型中选一个：{expense_types}；
   判断不了就填空字符串。
9. 只输出 JSON 对象本身，不要任何前后说明。"""


# PDF 文本模式专用提示词：输入是 PDF 抽取出来的文字（不是图像），
# 措辞上把「识别这张票据图像」换成「下面是一张票据的 PDF 文本内容」，
# 其余字段与规则保持一致，保证两种模式产出同构结果。
_PROMPT_TEMPLATE_PDF_TEXT = """下面是一张票据（电子发票）经 PDF 解析得到的文本内容，请从中提取信息，
输出一个 JSON 对象，结构如下（字段名与取值必须完全一致）：
{{
  "document_type": "",
  "is_invoice": true,
  "invoice_code": "",
  "invoice_number": "",
  "issue_date": "YYYY-MM-DD",
  "buyer_name": "",
  "buyer_tax_id": "",
  "seller_name": "",
  "seller_tax_id": "",
  "amount_without_tax": 0,
  "tax_rate": "",
  "tax_amount": 0,
  "total_amount": 0,
  "total_amount_cn": "",
  "items": [{{"item_name": "", "quantity": 0, "amount": 0, "tax_amount": 0}}],
  "passenger_name": "",
  "travel_from": "",
  "travel_to": "",
  "travel_date": "YYYY-MM-DD",
  "checkin_date": "YYYY-MM-DD",
  "checkout_date": "YYYY-MM-DD",
  "nights": 0,
  "consume_city": "",
  "remark": "",
  "suggested_expense_type": ""
}}

提取要求：
1. document_type 只能从以下选项中选一个：{doc_types}。
2. is_invoice：**可用于报销的合规凭证一律为 true** —— 增值税专用/普通发票、电子发票，以及**铁路电子客票、航空运输电子客票行程单、出租车票**等铁路/航空/公路客运票据都属于可报销凭证；只有收据、购物小票、付款截图这类非正式凭证才为 false。
3. 金额一律填数字（不带货币符号、不带千分位逗号）：
   amount_without_tax=不含税金额，tax_rate=税率（如 "6%"、"免税"，无则空），
   tax_amount=税额，total_amount=价税合计；total_amount_cn 照抄票面大写金额。
4. 日期一律用 YYYY-MM-DD。文本中没有的字段填空字符串或 0，不要编造；
   注意区分「开票日期」与「入住/离店/乘车日期」。
5. items 为货物或应税劳务明细，每行含名称、数量、金额、税额；文本里的明细行可能连续排列，请还原成数组。
6. 火车票、机票行程单、出租车票等交通票据必须提取：passenger_name（乘车人）、
   travel_from（出发地）、travel_to（到达地）、travel_date（乘车/乘机日期）。
7. 住宿发票必须提取 checkin_date（入住）、checkout_date（离店）、nights（晚数）、
   consume_city（消费所在城市）。
8. suggested_expense_type 只能从这些费用类型中选一个：{expense_types}；
   判断不了就填空字符串。
9. 只输出 JSON 对象本身，不要任何前后说明。

【票据 PDF 文本】
{content}"""


# PDF 处理的参数
PDF_TEXT_MIN_CHARS = 30      # 文本层长度达到该阈值才认为「有文本层」，可直接走文本模型
PDF_MAX_PAGES = 3            # 最多读取/渲染的页数（发票通常 1～2 页，留余量）
PDF_RENDER_SCALE = 2.2       # 扫描件渲染倍率，2.2 倍约 200 DPI，兼顾清晰度与体积
PDF_MAX_PDF_BYTES = 20 * 1024 * 1024  # PDF 单文件上限（渲染与解析都更吃资源）


# ---------------------------------------------------------------- 金额与日期工具
def to_decimal(value) -> Decimal | None:
    """把各种形态的金额转成 Decimal（两位小数），无法转换时返回 None。

    兼容：数字、"¥1,650.00"、"￥ 1650"、"1650.00元"、None、空串。
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, (int, float)):
        d = Decimal(str(value))
    else:
        s = str(value).strip()
        if not s:
            return None
        # 去掉货币符号、千分位逗号、空格、“元”等噪声
        s = re.sub(r"[¥￥,，\s元人民币RMBrmb]", "", s)
        s = s.replace("。", ".").replace("．", ".")
        # 括号表示负数（会计写法），这里极少数票据会出现
        negative = s.startswith("(") and s.endswith(")")
        s = s.strip("()")
        if s in ("", "-", "--"):
            return None
        try:
            d = Decimal(s)
        except InvalidOperation:
            return None
        if negative:
            d = -d
    try:
        return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def money_float(value) -> float:
    """金额统一转成两位小数的 float（数据库字段是 Float，入库前先规范化）。"""
    d = to_decimal(value)
    return float(d) if d is not None else 0.0


_CN_DIGITS = "零壹贰叁肆伍陆柒捌玖"
_CN_UNITS = ("", "拾", "佰", "仟")
_CN_SECTIONS = ("", "万", "亿", "万亿")


def _int_to_chinese(number: int) -> str:
    """整数转中文大写（内部函数，供 money_to_chinese 使用）。"""
    if number == 0:
        return "零"
    s = str(number)
    pad = (4 - len(s) % 4) % 4          # 从高位补齐到 4 的倍数，便于按“万/亿”分节
    s = "0" * pad + s
    sections = len(s) // 4
    out = ""
    for i in range(sections):
        block = s[i * 4:(i + 1) * 4]
        block_value = int(block)
        block_text = ""
        zero_pending = False
        for j, ch in enumerate(block):
            digit = int(ch)
            unit = _CN_UNITS[3 - j]
            if digit == 0:
                zero_pending = True
            else:
                if zero_pending and block_text:
                    block_text += "零"
                block_text += _CN_DIGITS[digit] + unit
                zero_pending = False
        if block_value == 0:
            # 整节为 0：若后面还有非零节，补一个“零”占位（如 壹亿零叁）
            rest = s[(i + 1) * 4:]
            if out and not out.endswith("零") and rest and int(rest) > 0:
                out += "零"
            continue
        # 非零节且首位为 0（如 壹万零叁），需与前面内容补一个“零”
        if out and block.startswith("0") and not out.endswith("零"):
            out += "零"
        out += block_text + _CN_SECTIONS[sections - 1 - i]
    return out


def money_to_chinese(amount) -> str:
    """小写金额转中文大写，如 1650.00 → 壹仟陆佰伍拾圆整。

    规则要点（与银行票据写法一致）：
    - 用“圆”不用“元”（比对时两者视为相同）；
    - 角分全为零时，整数部分后加“整”；
    - 金额小于 1 元时省略“零圆”，直接写“伍分”“伍角”；
    - 有分无角时写“零”占位，如 壹圆零伍分。
    """
    d = to_decimal(amount)
    if d is None:
        return ""
    d = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    negative = d < 0
    d = abs(d)
    integer = int(d)
    cents = int((d - integer) * 100)
    jiao, fen = divmod(cents, 10)

    text = ""
    if integer:
        text = _int_to_chinese(integer) + "圆"
    if jiao == 0 and fen == 0:
        text = (text + "整") if text else "零圆整"
    else:
        if jiao:
            text += _CN_DIGITS[jiao] + "角"
        elif text:
            # 有分无角，中间补“零”，如 壹圆零伍分
            text += "零"
        if fen:
            text += _CN_DIGITS[fen] + "分"
        else:
            text += "整"          # 如 壹圆伍角整
    return ("负" + text) if negative else text


def _cn_amount_comparable(text: str) -> str:
    """把大写金额规范成可比较的形式：去空格、“元”统一为“圆”、去结尾“整”。"""
    s = re.sub(r"[\s　]", "", str(text or ""))
    s = s.replace("元", "圆").replace("正", "整")
    return s.rstrip("整")


def normalize_date_str(value) -> str:
    """把各种写法的日期统一成 YYYY-MM-DD；无法识别或明显是占位值时返回空串。

    兼容：2026-10-15、2026/10/15、2026.10.15、2026年10月15日、
    20261015、带时间的 2026-10-15 08:30:00。
    视觉模型对票据上不存在的日期字段，常返回 1900-01-01、0000-00-00 这类占位值，
    这些不是真实日期，统一丢弃，避免下游误判为“离店日期早于入住日期”。
    """
    s = str(value or "").strip()
    if not s:
        return ""
    s = s.split(" ")[0].split("T")[0]
    s = s.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").replace(".", "-")
    s = re.sub(r"-+", "-", s).strip("-")
    # 纯数字：可能是 20261015
    if re.fullmatch(r"\d{8}", s):
        s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if not m:
        return ""
    y, mo, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
    # 视觉模型对票面不存在的日期字段，常返回 1900-01-01、1970-01-01（Unix 纪元）、
    # 0000-00-00 之类的占位值。真实报销票据不可能早于 2000 年，
    # 因此把 2000 年之前的日期一律视为“模型没识别到”，置空而不是当作真实日期。
    if y < 2000 or mo < 1 or dd < 1:
        return ""
    try:
        return date(y, mo, dd).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _date_diff(a: str, b: str) -> int | None:
    """两个 YYYY-MM-DD 相差的天数（a - b），任一为空或非法返回 None。"""
    da = normalize_date_str(a)
    db_ = normalize_date_str(b)
    if not da or not db_:
        return None
    try:
        return (datetime.strptime(da, "%Y-%m-%d").date()
                - datetime.strptime(db_, "%Y-%m-%d").date()).days
    except ValueError:
        return None


# ---------------------------------------------------------------- 字段规范化
def _norm_text(value) -> str:
    """字符串字段统一：转字符串、去首尾空白、全角空格也算空白。"""
    if value is None:
        return ""
    return str(value).replace("　", " ").strip()


def _norm_bool(value) -> bool:
    """大模型常把 is_invoice 返回成 "true"/"false"/1/0，统一成 bool。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    s = str(value or "").strip().lower()
    if s in ("false", "no", "0", "否", "不是", "非发票", "无"):
        return False
    if s in ("true", "yes", "1", "是", "发票", "有"):
        return True
    return True          # 默认按发票处理，具体由 warnings 提示人工核对


def _norm_items(value) -> list:
    """明细列表规范化：过滤掉非字典项，字段补齐并转类型。"""
    items = []
    if not isinstance(value, list):
        return items
    for it in value:
        if not isinstance(it, dict):
            continue
        items.append({
            "item_name": _norm_text(it.get("item_name") or it.get("name") or ""),
            "quantity": money_float(it.get("quantity") or 0),
            "amount": money_float(it.get("amount") or 0),
            "tax_amount": money_float(it.get("tax_amount") or 0),
        })
    return items


def normalize_invoice(data: dict) -> dict:
    """把大模型返回的原始字典规范化成固定字段集（缺字段补空、类型转换）。

    注意：金额与日期只做格式规范化，正确性由 check_invoice 校验。
    """
    if not isinstance(data, dict):
        raise BizException("票据识别结果格式异常，请重试")
    result = dict(INVOICE_FIELDS)
    for key in INVOICE_FIELDS:
        if key in data and data[key] is not None:
            result[key] = data[key]

    # 文本字段
    for key in ("invoice_code", "invoice_number", "buyer_name", "buyer_tax_id",
                "seller_name", "seller_tax_id", "tax_rate", "total_amount_cn",
                "passenger_name", "travel_from", "travel_to", "consume_city",
                "remark", "suggested_expense_type", "document_type"):
        result[key] = _norm_text(result.get(key))

    # 票据类型必须落在枚举内，否则归为“其他”
    if result["document_type"] not in DOCUMENT_TYPES:
        result["document_type"] = "其他"

    result["is_invoice"] = _norm_bool(result.get("is_invoice"))

    # 金额字段转 Decimal 校验后写回 float（JSON 友好、数据库字段也是 Float）
    for key in ("amount_without_tax", "tax_amount", "total_amount"):
        result[key] = money_float(result.get(key))

    # 日期字段统一 YYYY-MM-DD
    for key in ("issue_date", "travel_date", "checkin_date", "checkout_date"):
        result[key] = normalize_date_str(result.get(key))

    # 晚数转整数
    try:
        result["nights"] = int(float(result.get("nights") or 0))
    except (TypeError, ValueError):
        result["nights"] = 0

    result["items"] = _norm_items(result.get("items"))
    return result


def _read_company() -> tuple[str, str]:
    """从系统参数读取本单位名称与税号（票据购买方核对用）。

    读库失败不阻断识别（识别本身可用，只是少一项校验），返回空串。
    """
    try:
        from app.core.database import SessionLocal
        from app.models.reimburse import RmbSysParam

        db = SessionLocal()
        try:
            rows = db.query(RmbSysParam).filter(
                RmbSysParam.param_key.in_(["company_name", "company_tax_id"])
            ).all()
            mapping = {r.param_key: (r.param_value or "") for r in rows}
        finally:
            db.close()
        return mapping.get("company_name", ""), mapping.get("company_tax_id", "")
    except Exception:
        return "", ""


def _read_expense_types() -> list[str]:
    """读取启用的费用类型名称，用于约束 suggested_expense_type。"""
    try:
        from app.core.database import SessionLocal
        from app.models.reimburse import RmbExpenseType

        db = SessionLocal()
        try:
            rows = db.query(RmbExpenseType).order_by(RmbExpenseType.sort_no).all()
            return [r.name for r in rows if r.is_active]
        finally:
            db.close()
    except Exception:
        return []


# ---------------------------------------------------------------- 程序校验
def _same_company(name: str, company_name: str) -> bool:
    """判断购买方名称与本单位是否一致（允许“（章）”、空格等细微差异）。"""
    def clean(s: str) -> str:
        s = re.sub(r"[（）()【】\[\]\s　]", "", str(s or ""))
        # 去掉常见的票面后缀噪声
        return s.replace("发票专用章", "").replace("财务专用章", "")

    a, b = clean(name), clean(company_name)
    if not a or not b:
        return True                     # 没有可比信息，不判为不一致
    return a == b or a in b or b in a


def check_invoice(data: dict, company_name: str = "", company_tax_id: str = "") -> list[str]:
    """对识别出的票据做纯程序校验，返回中文告警列表（不调用大模型）。

    校验项（对应实验指导书提示词 4-2）：
    1. 金额规范化：去 ¥ ￥ 逗号，转 Decimal 两位小数，写回 data；
    2. 勾稽校验：不含税金额 + 税额 与价税合计差额超过 0.01 元时告警；
    3. 大写金额比对（“元”“圆”视为相同）；
    4. 日期统一 YYYY-MM-DD；离店日期减入住日期与晚数不一致时告警；
    5. is_invoice=false 时告警；是发票但没有发票号码时告警；
    6. 购买方名称或税号与本单位不一致时告警。

    返回的告警由确认页展示给人工核对，不阻断保存（制度层面的结论交给合规判读）。
    """
    warnings: list[str] = []
    if not isinstance(data, dict):
        return ["票据识别结果格式异常，请重新识别"]

    # ---------- 1. 金额规范化（直接在 data 上写回，便于下游使用） ----------
    for key in ("amount_without_tax", "tax_amount", "total_amount"):
        raw = data.get(key)
        d = to_decimal(raw)
        if d is None:
            data[key] = 0.0
            if str(raw or "").strip() not in ("", "0", "0.00", "None"):
                warnings.append(f"未识别的金额格式（{key}={raw!r}），已按 0 处理，请人工核对")
        else:
            data[key] = float(d)

    without_tax = to_decimal(data.get("amount_without_tax")) or Decimal("0.00")
    tax_amount = to_decimal(data.get("tax_amount")) or Decimal("0.00")
    total_amount = to_decimal(data.get("total_amount")) or Decimal("0.00")

    # ---------- 2. 勾稽校验 ----------
    if without_tax > 0 and tax_amount > 0 and total_amount > 0:
        diff = (without_tax + tax_amount - total_amount).copy_abs()
        if diff > AMOUNT_TOLERANCE:
            warnings.append(
                f"金额勾稽不平：不含税 {without_tax} + 税额 {tax_amount} = "
                f"{without_tax + tax_amount}，与价税合计 {total_amount} 相差 {diff} 元，请核对票据原件"
            )
    elif total_amount <= 0 and without_tax > 0:
        # 未识别到价税合计时用“不含税 + 税额”回填，避免报销金额取到 0
        filled = without_tax + tax_amount
        data["total_amount"] = float(filled)
        total_amount = filled
        warnings.append(f"未识别到价税合计，已按不含税金额 + 税额回填为 {filled} 元，请核对")
    elif total_amount > 0 and without_tax <= 0 and tax_amount <= 0:
        # 只识别到价税合计（常见于车票），不含税金额按价税合计填，不告警
        data["amount_without_tax"] = float(total_amount)

    # ---------- 3. 大写金额比对 ----------
    total_cn = _norm_text(data.get("total_amount_cn"))
    if total_cn and total_amount > 0:
        expected = money_to_chinese(total_amount)
        if expected and _cn_amount_comparable(total_cn) != _cn_amount_comparable(expected):
            warnings.append(
                f"大写金额与小写金额不一致：票面大写“{total_cn}”，"
                f"按价税合计 {total_amount} 元应为“{expected}”，请核对"
            )

    # ---------- 4. 日期规范化与晚数核对 ----------
    for key in ("issue_date", "travel_date", "checkin_date", "checkout_date"):
        data[key] = normalize_date_str(data.get(key))

    checkin, checkout = data.get("checkin_date", ""), data.get("checkout_date", "")
    nights = data.get("nights") or 0
    try:
        nights = int(nights)
    except (TypeError, ValueError):
        nights = 0
    data["nights"] = nights
    # 只有同时识别到入住和离店日期时才核对晚数
    if checkin and checkout:
        span = _date_diff(checkout, checkin)
        if span is None:
            warnings.append("入住/离店日期不合法，无法核对住宿晚数")
        elif span <= 0:
            warnings.append(f"离店日期 {checkout} 不晚于入住日期 {checkin}，请核对")
        elif nights and span != nights:
            warnings.append(
                f"住宿晚数与入住离店日期不一致：离店 {checkout} 减入住 {checkin} 为 {span} 晚，"
                f"票面识别为 {nights} 晚，请核对"
            )
        elif not nights:
            data["nights"] = span          # 未识别到晚数时用日期差回填
    elif nights and not (checkin and checkout):
        warnings.append("识别到住宿晚数但缺少入住/离店日期，请人工补充")

    # ---------- 5. 是否发票、发票号码 ----------
    is_invoice = _norm_bool(data.get("is_invoice"))
    data["is_invoice"] = is_invoice
    if not is_invoice:
        warnings.append(
            "该单据不是发票，按制度第十一条须附情况说明并经总经理特批，否则不予报销"
        )
    elif not _norm_text(data.get("invoice_number")):
        warnings.append("该单据被识别为发票，但未识别到发票号码，请人工核对（缺号码无法防重复报销）")

    # ---------- 6. 购买方核对 ----------
    buyer_name = _norm_text(data.get("buyer_name"))
    buyer_tax = _norm_text(data.get("buyer_tax_id"))
    company_name = _norm_text(company_name)
    company_tax_id = _norm_text(company_tax_id)
    # 教学样票的税号可能填的是占位符（含【】），这种情况只比名称
    tax_comparable = bool(company_tax_id) and not re.search(r"[【】\[\]]", company_tax_id)
    if buyer_name and company_name and not _same_company(buyer_name, company_name):
        warnings.append(
            f"购买方不是本单位：票面为“{buyer_name}”，本单位为“{company_name}”，请核实是否可报销"
        )
    elif buyer_tax and tax_comparable and buyer_tax != company_tax_id:
        warnings.append(
            f"购买方税号与本单位不一致：票面为 {buyer_tax}，本单位为 {company_tax_id}，请核实"
        )

    # 去重并保持顺序（同一问题可能被多条规则命中）
    seen, result = set(), []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            result.append(w)
    return result


# ---------------------------------------------------------------- PDF 处理
def pdf_extract_text(file_bytes: bytes, max_pages: int = PDF_MAX_PAGES) -> str:
    """用 pypdf 提取 PDF 文本层，返回纯文本（失败或没有文本层时返回空串）。

    电子发票（增值税电子普通发票、铁路电子客票、航空行程单等）绝大多数是
    「文本型 PDF」——文字是可选中的，直接抽取文本比走视觉模型更准确。
    扫描件（图片压进 PDF）没有文本层，这里会返回空串，由调用方转渲染路径。
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        if getattr(reader, "is_encrypted", False):
            # 未设密码的加密 PDF 尝试用空口令解密；设了密码的一律按无法解析处理
            try:
                reader.decrypt("")
            except Exception:  # noqa: BLE001
                return ""
        pages = []
        for page in reader.pages[:max_pages]:
            try:
                pages.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001 - 单页解析失败不影响其他页
                continue
        return "\n".join(pages).strip()
    except Exception:  # noqa: BLE001 - 损坏/非标准 PDF 一律降级处理
        return ""


def pdf_render_png(file_bytes: bytes, scale: float = PDF_RENDER_SCALE) -> tuple[bytes, str]:
    """用 pypdfium2 把 PDF 首页渲染成 PNG，返回 (png_bytes, 'image/png')。

    用于没有文本层的扫描件：渲染成位图后交给视觉模型，效果等同拍照上传。
    渲染失败时抛 BizException（此时已无其他可用的识别路径）。
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise BizException(
            "当前环境缺少 PDF 渲染组件（pypdfium2），且该 PDF 没有可提取的文本层。"
            "请安装依赖后重试，或把票据转为图片上传"
        )
    try:
        doc = pdfium.PdfDocument(io.BytesIO(file_bytes))
        if len(doc) == 0:
            raise BizException("PDF 文件没有任何页面，请检查文件是否完整")
        page = doc[0]
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil()
        buf = io.BytesIO()
        # 统一转白底 RGB：部分 PDF 是 CMYK 或带透明通道，视觉模型对这类图易误判
        if image.mode != "RGB":
            background = __import__("PIL.Image", fromlist=["Image"]).new("RGB", image.size, "white")
            if image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGBA")
                background.paste(image, mask=image.split()[-1])
            else:
                background.paste(image)
            image = background
        image.save(buf, format="PNG", optimize=True)
        page.close()
        doc.close()
        return buf.getvalue(), "image/png"
    except BizException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BizException(f"PDF 渲染失败：{exc}")


# ---------------------------------------------------------------- 对外入口
def _recognize_pdf_invoice(
    file_bytes: bytes, expense_type_hint: str
) -> tuple[dict, str, float, str, str]:
    """PDF 票据识别：优先抽文本走文本模型，无文本层时渲染成图走视觉模型。

    返回 (data, raw_text, elapsed, model, source)，source 取值：
    - "pdf_text"   ：文本型 PDF，pypdf 抽取文本 → 文本模型
    - "pdf_render" ：扫描件 PDF，pypdfium2 渲染首页 → 视觉模型

    为什么优先走文本：电子发票的文字本身就在 PDF 里，直接抽出来交给文本模型，
    既避免图像压缩/倾斜带来的识别误差，token 消耗也低得多，速度更快。
    """
    # ---------- 路径 A：文本型 PDF ----------
    text = pdf_extract_text(file_bytes)
    cleaned = re.sub(r"[ \t\u3000]+", " ", text or "").strip()
    # 有效字符数：排除空白后判断，避免只有页眉页码也被当成「有文本层」
    if len(re.sub(r"\s", "", cleaned)) >= PDF_TEXT_MIN_CHARS:
        prompt = _PROMPT_TEMPLATE_PDF_TEXT.format(
            doc_types="、".join(DOCUMENT_TYPES),
            expense_types=expense_type_hint,
            content=cleaned[:6000],   # 截断保护：票据正文远小于此，避免异常长文本撑爆上下文
        )
        model = llm_client_new.rule_model()   # 纯文本任务，用文本模型即可
        try:
            data, raw_text, elapsed = llm_client_new.call_json(
                llm_client_new.chat_text, prompt, model=model, system=_PDF_TEXT_SYSTEM_PROMPT
            )
        except LLMError as exc:
            detail = f"（模型原始输出片段：{exc.raw_text[:200]}）" if exc.raw_text else ""
            raise BizException(f"PDF 票据识别失败：{exc.message}{detail}")
        return data, raw_text, elapsed, model, "pdf_text"

    # ---------- 路径 B：扫描件 PDF（无文本层）----------
    png_bytes, png_mime = pdf_render_png(file_bytes)
    prompt = _PROMPT_TEMPLATE.format(
        doc_types="、".join(DOCUMENT_TYPES),
        expense_types=expense_type_hint,
    )
    model = llm_client_new.invoice_model()   # 图像任务用视觉模型
    try:
        data, raw_text, elapsed = llm_client_new.call_json(
            llm_client_new.chat_with_image, png_bytes, png_mime, prompt, model=model
        )
    except LLMError as exc:
        detail = f"（模型原始输出片段：{exc.raw_text[:200]}）" if exc.raw_text else ""
        raise BizException(f"PDF 票据识别失败：{exc.message}{detail}")
    return data, raw_text, elapsed, model, "pdf_render"


def _detect_ext(filename: str, mime: str) -> str:
    """从文件名 / MIME 推断扩展名（小写、不带点）。"""
    name = _norm_text(filename)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in IMAGE_MIME or ext == "pdf":
        return ext
    mime = (mime or "").split(";")[0].strip().lower()
    for key, value in IMAGE_MIME.items():
        if value == mime:
            return key
    if mime == "application/pdf":
        return "pdf"
    return ext


def recognize_invoice(file_bytes: bytes, filename: str = "", mime: str = "") -> dict:
    """票据识别入口：图片走视觉理解模型，返回规范化后的结构化数据。

    返回 dict 包含实验指导书步骤 4 要求的全部字段，并附加：
    - raw_text：模型原始输出（留痕、便于排错）
    - model：本次使用的模型名
    - elapsed：耗时（秒）
    - warnings：程序校验告警列表（check_invoice 的结果）

    失败（图片为空/超限/格式不支持/模型调用失败/JSON 解析失败）统一抛 BizException，
    消息为可直接展示给用户的中文提示。
    """
    if not file_bytes:
        raise BizException("上传的票据文件为空，请重新选择文件")

    ext = _detect_ext(filename, mime)
    if ext not in IMAGE_MIME and ext != "pdf" and not (mime or "").startswith("image/"):
        raise BizException(
            "仅支持 PDF / jpg / jpeg / png / webp 格式的票据文件，请转换格式后重试"
        )

    # 大小限制按类型区分：PDF 需要渲染/解析，允许的体量比图片更大。
    # 注意顺序——先按 ext 判断再校验大小，否则 PDF 会被图片的 8MB 上限提前拦下。
    if ext == "pdf":
        max_bytes, max_hint = PDF_MAX_PDF_BYTES, f"{PDF_MAX_PDF_BYTES // (1024 * 1024)}MB"
    else:
        max_bytes = int(settings.AI_OCR_MAX_MB or 8) * 1024 * 1024
        max_hint = f"{settings.AI_OCR_MAX_MB}MB"
    if len(file_bytes) > max_bytes:
        raise BizException(f"票据文件过大，请压缩到 {max_hint} 以内后重试")

    company_name, company_tax_id = _read_company()
    expense_types = _read_expense_types()
    expense_type_hint = "、".join(expense_types) if expense_types else "差旅住宿费、差旅交通费、业务招待费"

    # ---------- 分支一：PDF 票据 ----------
    if ext == "pdf":
        data, raw_text, elapsed, model, source = _recognize_pdf_invoice(
            file_bytes, expense_type_hint
        )
    # ---------- 分支二：图片票据 ----------
    else:
        content_mime = IMAGE_MIME.get(ext) or (mime or "image/jpeg").split(";")[0].strip()
        prompt = _PROMPT_TEMPLATE.format(
            doc_types="、".join(DOCUMENT_TYPES),
            expense_types=expense_type_hint,
        )
        model = llm_client_new.invoice_model()
        source = "image"
        try:
            data, raw_text, elapsed = llm_client_new.call_json(
                llm_client_new.chat_with_image,
                file_bytes, content_mime, prompt, model=model,
            )
        except LLMError as exc:
            detail = f"（模型原始输出片段：{exc.raw_text[:200]}）" if exc.raw_text else ""
            raise BizException(f"票据识别失败：{exc.message}{detail}")

    result = normalize_invoice(data)

    # 识别不出任何有效内容时给出明确提示，避免把空票存进数据库
    if (not result["total_amount"] and not result["invoice_number"]
            and not result["seller_name"] and not result["items"]):
        hint = ("未能从 PDF 中识别出票据内容，请确认文件清晰完整"
                if ext == "pdf" else
                "未能从图片中识别出票据内容，请上传清晰、完整的票据照片")
        raise BizException(f"{hint}，或跳过识别手工填写")

    result["warnings"] = check_invoice(result, company_name, company_tax_id)
    result["raw_text"] = raw_text or ""
    result["model"] = model
    result["elapsed"] = elapsed
    # 供日志/排错使用：图片识别 image / PDF 文本层 pdf_text / PDF 渲染 pdf_render
    result["recognize_mode"] = source
    return result


def recognize_invoice_or_none(file_bytes: bytes, filename: str = "", mime: str = "") -> dict | None:
    """识别失败返回 None 的包装（供「跳过识别、手工填写」的流程使用）。"""
    try:
        return recognize_invoice(file_bytes, filename, mime)
    except BizException:
        return None


if __name__ == "__main__":
    # 手工验证入口：python -m app.services.invoice_ai [票据图片路径]
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) > 1:
        path = sys.argv[1]
        with open(path, "rb") as fp:
            blob = fp.read()
        ext = path.rsplit(".", 1)[-1].lower()
        print(json.dumps(
            recognize_invoice(blob, path, IMAGE_MIME.get(ext, "")),
            ensure_ascii=False, indent=2,
        ))
    else:
        # 无参数时只跑离线自检（不消耗大模型额度）
        print("【money_to_chinese 自检】")
        for value in ("1650.00", "100", "0.05", "1234567.89", "2400.00", "1.5", "1.05", "0.55"):
            print(f"  {value} → {money_to_chinese(value)}")
        print("\n【check_invoice 自检】")
        sample = {
            "document_type": "电子发票（增值税专用发票）", "is_invoice": True,
            "invoice_number": "26312000000098765432", "issue_date": "2026/10/15",
            "buyer_name": "星辰科技股份有限公司",
            "amount_without_tax": "¥1,556.60", "tax_amount": "93.40",
            "total_amount": "1650.00", "total_amount_cn": "壹仟陆佰伍拾元整",
            "checkin_date": "2026-10-12", "checkout_date": "2026年10月15日", "nights": 3,
        }
        print(json.dumps(sample, ensure_ascii=False, indent=2))
        print("校验结果：", json.dumps(
            check_invoice(sample, "星辰科技股份有限公司", ""), ensure_ascii=False, indent=2))
        print("规范化后：", json.dumps(normalize_invoice(sample), ensure_ascii=False, indent=2))
