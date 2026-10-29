"""AI 单据识别（OCR）服务：可插拔适配器。

统一入口：recognize(image_bytes, filename, content_type) -> dict
返回结构：
    {
        "doc_type": "送货单",           # 单据/发票/送货单 …
        "doc_no":   "DN20260513001",    # 单号
        "supplier_name": "温州宏远面料有限公司",
        "items": [{"material_name": "...", "spec": "...", "qty": 800, "unit": "米"}, ...],
        "raw_text": "...",              # 原始识别文本（无则回填 JSON 串）
        "provider": "mock"
    }

两类提供方（由「启用的模型档案」或 settings.AI_OCR_PROVIDER 决定）：
- mock  ：离线占位实现，返回一套与演示基础数据吻合的样例结果，
          用于无密钥时打通「上传 → 识别 → 导入」全流程与功能演示；
- 其余  ：调用 OpenAI 兼容的多模态（视觉）Chat Completions 接口，把图片识别为上述 JSON。
          内置 dashscope / ark / zhipu / openai 预设，custom 走自定义地址与模型。
          仅使用标准库 urllib，不引入额外依赖。

引擎参数（引擎/地址/模型/密钥/超时/json_mode/重试）统一由 `ai_model_config.resolve_engine()`
给出：优先级是「界面里启用的模型档案 > .env 的 AI_OCR_* > 引擎预设」。
"""
import base64
import json
import re
import urllib.error
import urllib.request
import zlib

from app.core.config import settings
from app.core.exceptions import BizException
from app.services import ai_model_config
from app.services.ai_model_config import PROVIDER_PRESETS  # noqa: F401  （外部仍在引用这个名字）

DOC_TYPES = ("送货单", "发票", "单据")

_SYSTEM_PROMPT = (
    "你是箱包制造企业的采购单据识别助手，只识别采购类单据"
    "（送货单、发票、采购订单、入库单、收据等）。"
    "若图片根本不是这类单据（人物、风景、产品照、截图等），"
    "或画面模糊、内容无法辨认，一律判定为无法识别，不要猜测编造。"
    "严格只输出 JSON，不要输出多余文字或 Markdown 代码块。\n"
    "能够识别时输出："
    '{"is_document":true,"doc_type":"送货单|发票|单据","doc_no":"单号",'
    '"supplier_name":"供应商名称","items":[{"material_name":"物料名称","spec":"规格","qty":数量,"unit":"单位"}]}\n'
    "无法识别时输出："
    '{"is_document":false,"reason":"无法识别的具体原因"}'
)


def _is_false(value) -> bool:
    """判断模型返回的 is_document 是否表示「不是单据」（兼容 false / "false" / 0）。"""
    if value is False:
        return True
    if isinstance(value, str):
        return value.strip().lower() in ("false", "no", "0", "非单据")
    return False


def resolved_config() -> dict:
    """当前生效的识别引擎配置（模型档案 > .env > 预设，见 ai_model_config）。"""
    return ai_model_config.resolve_engine()


def _extract_json(text: str) -> dict:
    """从模型回复中稳妥地取出 JSON（兼容 ```json 代码块与前后缀说明文字）。"""
    if not text:
        raise BizException("识别服务未返回内容")
    s = text.strip()
    s = re.sub(r"^```(?:json)?", "", s).strip()
    s = re.sub(r"```$", "", s).strip()
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise BizException("识别结果不是有效的 JSON，请重试或更换图片")
    try:
        return json.loads(s[start:end + 1])
    except json.JSONDecodeError as exc:
        raise BizException(f"识别结果解析失败：{exc}")


def _norm_result(data: dict, provider: str, raw_text: str = "") -> dict:
    """归一化各提供方的原始输出，保证字段齐备、数量为数值。

    只接受采购单据：模型判定「不是单据/无法辨认」时直接报错；
    即便模型未明确判定，只要没提取到任何有效内容，同样视为识别失败。
    """
    if _is_false(data.get("is_document")):
        reason = str(data.get("reason") or "").strip()
        raise BizException(f"未能识别出单据内容：{reason or '图片不是采购单据，或内容无法辨认'}")
    items = []
    for it in data.get("items") or []:
        if not isinstance(it, dict):
            continue
        try:
            qty = float(it.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        items.append({
            "material_name": str(it.get("material_name") or "").strip(),
            "spec": str(it.get("spec") or "").strip(),
            "unit": str(it.get("unit") or "").strip(),
            "qty": qty,
        })
    doc_type = str(data.get("doc_type") or "单据").strip()
    if doc_type not in DOC_TYPES:
        doc_type = "单据"
    result = {
        "doc_type": doc_type,
        "doc_no": str(data.get("doc_no") or "").strip(),
        "supplier_name": str(data.get("supplier_name") or "").strip(),
        "items": items,
        "raw_text": raw_text or json.dumps(data, ensure_ascii=False),
        "provider": provider,
    }
    # 兜底：单号、供应商、明细三者皆空 → 判定为没识别出内容（mock 样例不触发）
    if not result["doc_no"] and not result["supplier_name"] and not result["items"]:
        raise BizException("未能从图片中识别出单据内容，请上传清晰、完整的送货单/发票照片")
    return result


# 离线演示样例：供应商与物料名都取自演示库里真实存在的档案，保证「供应商匹配 + 明细匹配」全绿。
# 第 0 份即 test_docs/送货单_测试样张.png 的真实内容，README 与截图都以它为准，不要改动顺序。
_MOCK_DOCS = [
    {
        "doc_type": "送货单",
        "doc_no": "DN20260513001",
        "supplier_name": "温州宏远面料有限公司",
        "items": [
            {"material_name": "600D涤纶牛津布", "spec": "幅宽150cm", "qty": 800, "unit": "米"},
            {"material_name": "5#尼龙拉链", "spec": "70cm", "qty": 2000, "unit": "条"},
        ],
    },
    {
        "doc_type": "送货单",
        "doc_no": "DN20260511007",
        "supplier_name": "义乌诚信五金商行",
        "items": [
            {"material_name": "8#树脂拉链-17", "spec": "常规规格-1", "qty": 3000, "unit": "个"},
            {"material_name": "日字扣-17", "spec": "常规规格-2", "qty": 1500, "unit": "个"},
        ],
    },
    {
        "doc_type": "送货单",
        "doc_no": "DN20260508012",
        "supplier_name": "恒丰五金有限公司-1",
        "items": [
            {"material_name": "挂锁-16", "spec": "常规规格-0", "qty": 600, "unit": "个"},
            {"material_name": "5#尼龙拉链", "spec": "70cm", "qty": 1200, "unit": "条"},
        ],
    },
    {
        "doc_type": "发票",
        "doc_no": "FP20260505003",
        "supplier_name": "远东辅料有限公司-3",
        "items": [
            {"material_name": "松紧带-17", "spec": "常规规格-0", "qty": 2000, "unit": "个"},
            {"material_name": "拉链布带-17", "spec": "常规规格-2", "qty": 1800, "unit": "个"},
        ],
    },
    {
        "doc_type": "送货单",
        "doc_no": "DN20260428009",
        "supplier_name": "鑫源包材有限公司-5",
        "items": [
            {"material_name": "干燥剂-37", "spec": "常规规格-0", "qty": 5000, "unit": "个"},
            {"material_name": "无纺布袋-38", "spec": "常规规格-1", "qty": 400, "unit": "个"},
        ],
    },
]


def _recognize_mock(filename: str = "") -> dict:
    """离线占位：返回一套贴合演示数据的样例，便于无密钥时演示全流程。

    批量识别时若每张图都返回同一份样例，演示会失去意义，因此按文件名稳定地取用其中一份
    （用 crc32 而非内置 hash，后者每个进程随机化、结果不可复现）。不带文件名、
    或上传的是仓库自带的测试样张时，始终返回第 0 份 —— 即 README 记录的
    DN20260513001 / 温州宏远面料有限公司，保证文档、截图与实际演示结果一致。
    """
    name = (filename or "").strip()
    if not name or "测试样张" in name:
        idx = 0
    else:
        idx = zlib.crc32(name.encode("utf-8")) % len(_MOCK_DOCS)
    return _norm_result(_MOCK_DOCS[idx], provider="mock")


def _post_chat(cfg: dict, payload: dict) -> dict:
    """POST /chat/completions，对网络异常与 5xx 做有限重试；4xx 直接报错。"""
    url = cfg["base_url"] + "/chat/completions"
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {cfg['api_key']}"}
    timeout = int(cfg.get("timeout") or settings.AI_OCR_TIMEOUT)
    retry = int(cfg.get("retry") if cfg.get("retry") is not None else settings.AI_OCR_RETRY)
    last_err = "未知错误"
    for _ in range(retry + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")[:300]
            if 400 <= exc.code < 500:      # 密钥错误/参数错误等，重试无意义
                raise BizException(f"识别接口调用失败（HTTP {exc.code}）：{detail}")
            last_err = f"HTTP {exc.code}：{detail}"
        except Exception as exc:           # 网络异常/超时等
            last_err = str(exc)
    raise BizException(f"识别接口调用失败：{last_err}")


def _content_of(body: dict) -> str:
    """从响应体中取出模型文本；兼容 content 为字符串或分段数组两种返回形态。"""
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise BizException("识别接口返回结构异常，请检查模型配置")
    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    if not (content or "").strip():
        raise BizException("识别服务未返回内容")
    return content


def _recognize_remote(image_bytes: bytes, content_type: str, cfg: dict) -> dict:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": "请先判断这张图片是否为采购单据；能识别则提取信息，不能识别请按无法识别的格式输出。"},
                {"type": "image_url",
                 "image_url": {"url": f"data:{content_type or 'image/jpeg'};base64,{b64}"}},
            ]},
        ],
        "temperature": 0,
    }
    if cfg.get("json_mode", settings.AI_OCR_JSON_MODE):
        payload["response_format"] = {"type": "json_object"}
    content = _content_of(_post_chat(cfg, payload))
    return _norm_result(_extract_json(content), provider=cfg["provider"], raw_text=content)


def test_connection(cfg: dict | None = None) -> dict:
    """连通性自检：校验密钥 / 地址 / 模型是否可用。

    cfg 为空时测「当前生效的引擎」；传入档案配置时测该档案——模型配置页的
    「测试」按钮可以在启用之前先验证连通性，避免配错了直接切过去导致识别全挂。
    """
    cfg = cfg or resolved_config()
    base = {"provider": cfg["provider"], "model": cfg["model"], "base_url": cfg["base_url"]}
    if not cfg["is_remote"]:
        return {"ok": True, "message": "当前为离线演示引擎（mock），无需联网", **base}
    if not cfg["api_key"]:
        return {"ok": False,
                "message": "尚未填写 API Key，请在「AI 单据识别 → 模型配置」中补全后重试", **base}
    if not cfg["base_url"] or not cfg["model"]:
        return {"ok": False, "message": "接口地址或模型名不完整，请检查模型档案", **base}
    try:
        _post_chat(cfg, {"model": cfg["model"],
                         "messages": [{"role": "user", "content": "ping"}],
                         "max_tokens": 1})
    except BizException as exc:
        return {"ok": False, "message": str(exc), **base}
    return {"ok": True, "message": "连接成功，识别模型可用", **base}


def recognize(image_bytes: bytes, filename: str = "", content_type: str = "") -> dict:
    """识别入口：按配置分发到具体提供方。"""
    if not image_bytes:
        raise BizException("上传的图片为空")
    limit = settings.AI_OCR_MAX_MB * 1024 * 1024
    if len(image_bytes) > limit:
        raise BizException(f"图片过大，请压缩到 {settings.AI_OCR_MAX_MB}MB 以内")
    cfg = resolved_config()
    if not cfg["is_remote"]:
        return _recognize_mock(filename)
    if not cfg["api_key"]:
        raise BizException("当前识别引擎尚未配置 API Key，请到「AI 单据识别 → 模型配置」补全后重试")
    if not cfg["base_url"] or not cfg["model"]:
        raise BizException("识别引擎的接口地址或模型名不完整，请检查「模型配置」")
    return _recognize_remote(image_bytes, content_type, cfg)