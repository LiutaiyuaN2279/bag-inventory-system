"""大模型调用公共封装（差旅与业务招待费报销智能体专用）。

与已有的 `ocr_service.py`（采购单据识别）互不影响：那个模块服务于采购到货场景，
本模块服务于报销场景，统一提供「文本对话 / 图片识别 / JSON 解析 / 重试与留痕」。

为什么单独成一个模块而不复用 ocr_service：
- ocr_service 把提示词、字段归一化、供应商预设和 mock 样例都写死在采购单据上，
  报销场景需要的是「任意提示词 + 任意模型」的通用通道；
- 本项目不引入 openai SDK，所有调用统一用标准库 urllib（与 ocr_service 一致），
  避免新增依赖，也便于在离线环境排查问题。

配置复用现有环境变量（不新增配置项）：
- AI_OCR_API_KEY   API Key（dashscope / ark / zhipu / openai 通用）
- AI_OCR_BASE_URL  网关地址，留空按 AI_OCR_PROVIDER 的预设（默认百炼兼容模式）
- AI_OCR_TIMEOUT   调用超时（秒）
- AI_OCR_RETRY     网络异常/5xx 的重试次数

模型名可用环境变量覆盖，未配置时取下列默认值：
- INVOICE_IMAGE_MODEL  票据识别用视觉模型，默认 qwen3-vl-plus
- RULE_MODEL           合规判读用文本模型，默认 qwen-plus
- VOUCHER_MODEL        凭证制作用文本模型，默认 qwen-plus
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request

from app.core.config import settings

# 各提供方的默认网关（.env 中显式填写 AI_OCR_BASE_URL 时以其为准）
PROVIDER_PRESETS = {
    "openai": "https://api.openai.com/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "ark": "https://ark.cn-beijing.volces.com/api/v3",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
}

# 默认模型：识别用视觉模型，判读与制证用文本模型（均可被环境变量覆盖）
DEFAULT_INVOICE_MODEL = "qwen3-vl-plus"
DEFAULT_RULE_MODEL = "qwen-plus"
DEFAULT_VOUCHER_MODEL = "qwen-plus"

# 系统提示词：三个业务场景共用的身份设定
DEFAULT_SYSTEM = "你是箱包制造企业的财务 AI 助手，只输出被要求的内容，不要闲聊。"


class LLMError(Exception):
    """大模型调用或解析失败。

    携带 `raw_text`（模型的原始输出，失败时可能有部分内容），便于：
    1. 排查问题（把原始输出一起报给使用者）；
    2. 落库留痕（合规判读表的 ai_raw_text 字段）。
    """

    def __init__(self, message: str, raw_text: str = ""):
        self.message = message
        self.raw_text = raw_text
        super().__init__(message)


# ---------------------------------------------------------------- 配置解析
def resolved_config() -> dict:
    """合并 .env 与 provider 预设，得到本次调用实际生效的网关配置。"""
    provider = (settings.AI_OCR_PROVIDER or "dashscope").strip().lower()
    preset = PROVIDER_PRESETS.get(provider, "")
    base_url = (settings.AI_OCR_BASE_URL or preset or "").strip().rstrip("/")
    return {
        "provider": provider,
        "base_url": base_url,
        "api_key": (settings.AI_OCR_API_KEY or "").strip(),
        "timeout": int(settings.AI_OCR_TIMEOUT or 120),
        "retry": int(settings.AI_OCR_RETRY or 0),
    }


def _env_model(key: str, default: str) -> str:
    """读取模型名：环境变量优先，其次默认值。"""
    return (os.getenv(key) or default).strip()


def invoice_model() -> str:
    """票据识别模型（视觉理解）。"""
    return _env_model("INVOICE_IMAGE_MODEL", DEFAULT_INVOICE_MODEL)


def rule_model() -> str:
    """合规判读模型（文本）。"""
    return _env_model("RULE_MODEL", DEFAULT_RULE_MODEL)


def voucher_model() -> str:
    """凭证制作模型（文本）。"""
    return _env_model("VOUCHER_MODEL", DEFAULT_VOUCHER_MODEL)


# ---------------------------------------------------------------- 底层 HTTP
def _post_chat(payload: dict, cfg: dict) -> dict:
    """POST /chat/completions。

    网络异常与 5xx 做有限重试（密钥/参数错误这类 4xx 重试无意义，直接报错）。
    所有失败统一抛 LLMError，消息为中文并带上服务端返回的片段。
    """
    if not cfg["base_url"]:
        raise LLMError("未配置大模型网关地址（AI_OCR_BASE_URL），请在 backend/.env 中填写")
    if not cfg["api_key"]:
        raise LLMError("未配置大模型 API Key（AI_OCR_API_KEY），请在 backend/.env 中填写")
    url = cfg["base_url"] + "/chat/completions"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['api_key']}",
    }
    last_err = "未知错误"
    for _ in range(cfg["retry"] + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if not isinstance(body, dict):
                raise LLMError("大模型服务返回结构异常，请检查网关配置")
            return body
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")[:300]
            if exc.code in (401, 403):
                raise LLMError(
                    f"大模型鉴权失败（HTTP {exc.code}）：请检查 API Key 是否正确、"
                    f"是否为与网关地址匹配的地域。服务端返回：{detail}"
                )
            if 400 <= exc.code < 500:
                raise LLMError(f"大模型调用失败（HTTP {exc.code}）：{detail}")
            last_err = f"HTTP {exc.code}：{detail}"
        except LLMError:
            raise
        except urllib.error.URLError as exc:
            last_err = f"网络不可达：{exc.reason}"
        except TimeoutError:
            last_err = f"调用超时（超过 {cfg['timeout']} 秒）"
        except Exception as exc:  # 网络中断、响应非 JSON 等
            last_err = str(exc)
    raise LLMError(f"大模型调用失败：{last_err}")


def _content_of(body: dict) -> str:
    """从响应体中取出模型文本；兼容 content 为字符串或分段数组两种形态。"""
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("大模型返回结构异常（缺少 choices[0].message.content），请检查网关配置")
    if isinstance(content, list):
        content = "".join(
            p.get("text", "") for p in content if isinstance(p, dict)
        )
    text = (content or "").strip()
    if not text:
        raise LLMError("大模型未返回任何内容，请稍后重试")
    return text


def _build_payload(model: str, messages: list, json_mode: bool | None = None) -> dict:
    """构造请求体：统一 temperature=0，尽量要求 JSON 输出。

    JSON Mode 的启用条件（不满足时只靠提示词约束 + parse_json 兜底）：
    1. .env 中 AI_OCR_JSON_MODE 未关闭；
    2. 调用方未显式要求关闭（json_mode=False）；
    3. 请求里能读到 "json" 字样 —— 百炼兼容模式要求开启 response_format=json_object 时
       消息中必须出现 json 关键词，否则直接返回 400，这是踩过的坑。
    """
    payload = {"model": model, "messages": messages, "temperature": 0}
    if not json_mode or not settings.AI_OCR_JSON_MODE:
        return payload
    if json_mode is None:
        text = " ".join(str(m.get("content", "")) for m in messages).lower()
        if "json" not in text:
            return payload
    payload["response_format"] = {"type": "json_object"}
    return payload


# ---------------------------------------------------------------- 对外接口
def chat_text(prompt: str, model: str = "", system: str = "") -> str:
    """纯文本对话：用于合规判读、AI 制证等任务。返回模型原始文本。"""
    cfg = resolved_config()
    model = (model or DEFAULT_RULE_MODEL).strip()
    messages = [
        {"role": "system", "content": (system or DEFAULT_SYSTEM).strip()},
        {"role": "user", "content": prompt or ""},
    ]
    return _content_of(_post_chat(_build_payload(model, messages), cfg))


def chat_with_image(image_bytes: bytes, mime: str, prompt: str, model: str = "") -> str:
    """图片对话：把图片转 base64 交给视觉理解模型（票据识别）。

    mime 取上传时的 Content-Type（image/jpeg、image/png 等），
    留空时按 jpeg 处理；图片内容为空直接报错，不发无意义的请求。
    """
    if not image_bytes:
        raise LLMError("上传的票据图片为空，无法识别")
    cfg = resolved_config()
    model = (model or DEFAULT_INVOICE_MODEL).strip()
    mime = (mime or "image/jpeg").split(";")[0].strip().lower()
    if not mime.startswith("image/"):
        mime = "image/jpeg"
    b64 = base64.b64encode(image_bytes).decode("ascii")
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                },
                {"type": "text", "text": prompt or "请识别这张票据"},
            ],
        }
    ]
    return _content_of(_post_chat(_build_payload(model, messages), cfg))


def parse_json(text: str) -> dict:
    """从模型回复中稳妥地取出 JSON。

    兼容三种常见形态：```json 代码块、前后夹带说明文字、正常的 JSON 串。
    做法是截取第一个 "{" 到最后一个 "}" 再 json.loads（与实验文档要求一致）。
    """
    if not text or not text.strip():
        raise LLMError("大模型未返回内容，无法解析 JSON")
    s = text.strip()
    # 去掉 Markdown 代码块标记（```json / ```），避免干扰定位
    s = re.sub(r"^\s*```(?:json|JSON)?\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s).strip()
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMError("大模型返回的内容不是有效的 JSON，请重试或检查提示词", text)
    try:
        data = json.loads(s[start:end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"大模型返回的 JSON 解析失败：{exc}", text)
    if not isinstance(data, dict):
        raise LLMError("大模型返回的 JSON 不是对象（应为 {...}），请检查提示词", text)
    return data


def call_json(func, *args, **kwargs) -> tuple[dict, str, float]:
    """调用大模型并解析 JSON。

    返回 `(数据, 原始输出, 耗时秒数)`；任何异常统一转为 LLMError，
    并在消息中保留原始输出片段，便于排查与留痕。
    """
    begin = time.time()
    try:
        raw_text = func(*args, **kwargs)
    except LLMError:
        raise
    except Exception as exc:  # 兜底：保证上层只需要处理 LLMError
        raise LLMError(f"调用大模型失败：{exc}")
    elapsed = round(time.time() - begin, 2)
    data = parse_json(raw_text)
    return data, raw_text, elapsed


def test_connection(model: str = "") -> dict:
    """连通性自检：校验网关、密钥与文本模型是否可用（供自测/运维排查）。"""
    cfg = resolved_config()
    base = {
        "provider": cfg["provider"],
        "base_url": cfg["base_url"],
        "model": (model or DEFAULT_RULE_MODEL).strip(),
    }
    try:
        text = chat_text("只回复两个字：正常", model=base["model"])
    except LLMError as exc:
        return {"ok": False, "message": str(exc), **base}
    return {"ok": True, "message": "连接成功", "reply": text, **base}


if __name__ == "__main__":
    # 手工验证：python -m app.services.llm_client_new
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("当前配置：", json.dumps(
        {k: v for k, v in resolved_config().items() if k != "api_key"},
        ensure_ascii=False, indent=2))
    print("票据识别模型：", invoice_model())
    print("合规判读模型：", rule_model())
    print("凭证制作模型：", voucher_model())
    print("连通性自检：", json.dumps(test_connection(), ensure_ascii=False, indent=2))
