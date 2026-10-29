"""大模型接入配置：读取「启用中的模型档案」，供 AI 单据识别使用。

为什么单独一层：识别服务（`ocr_service`）每次调用都要知道「用哪个引擎、哪个地址、
哪个密钥」，而这份配置现在可以来自两处——
- 数据库里的模型档案（界面可改，即时生效）；
- `.env` 里的 `AI_OCR_*`（部署期默认值）。

优先级：**启用的档案 > .env > 引擎预设**。档案表不存在或查询失败时静默回落到 .env，
保证「还没跑升级脚本的老库」也能照常识别（不因为缺表直接 500）。

每次识别都读库会多一次查询，且识别本身要几秒钟，这点开销可忽略；但为了避免
后台批量识别时重复查库，这里加了 3 秒的进程内缓存，任何写操作都会主动失效。
"""
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.database import SessionLocal

#: 各引擎的默认网关与视觉模型（档案里显式填写 base_url / model 时以其为准）
PROVIDER_PRESETS = {
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "dashscope": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen3-vl-plus"},
    "ark": {"base_url": "https://ark.cn-beijing.volces.com/api/v3", "model": "doubao-1.5-vision-pro-32k"},
    "zhipu": {"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4v-plus"},
}

#: 引擎中文名（前端下拉与提示文案共用，接口里一起返回，避免两处维护）
PROVIDER_LABELS = {
    "mock": "离线演示引擎（无需密钥）",
    "dashscope": "阿里云百炼 · 通义千问-VL",
    "ark": "火山方舟 · 豆包视觉",
    "zhipu": "智谱 GLM-4V",
    "openai": "OpenAI",
    "custom": "自定义 OpenAI 兼容网关",
}

#: 进程内缓存：{“ts”: 读取时间戳, “cfg”: 档案字典或 None}
_CACHE = {"ts": 0.0, "cfg": None}
_CACHE_TTL = 3.0


def invalidate_cache() -> None:
    """清缓存：档案新增 / 修改 / 启用 / 删除后必须调用，否则要等 3 秒才生效。"""
    _CACHE["ts"] = 0.0
    _CACHE["cfg"] = None


def provider_options() -> list[dict]:
    """引擎下拉选项：value/label/预设地址与模型，前端据此自动填充。"""
    return [
        {
            "value": key,
            "label": label,
            "base_url": PROVIDER_PRESETS.get(key, {}).get("base_url", ""),
            "model": PROVIDER_PRESETS.get(key, {}).get("model", ""),
            "is_remote": key != "mock",
        }
        for key, label in PROVIDER_LABELS.items()
    ]


def _load_active_row() -> dict | None:
    """读启用中的档案（带 3 秒缓存）；表不存在 / 查询异常返回 None。"""
    now = datetime.now().timestamp()
    if _CACHE["cfg"] is not None and now - _CACHE["ts"] < _CACHE_TTL:
        return _CACHE["cfg"]
    if _CACHE["cfg"] is None and now - _CACHE["ts"] < _CACHE_TTL:
        return None
    db = SessionLocal()
    try:
        # 延迟导入：模型层依赖不到这里，但放在函数内可避免循环导入
        from app.models.ai_ocr import AiModelConfig

        row = db.query(AiModelConfig).filter(AiModelConfig.is_active.is_(True)).first()
        cfg = None
        if row:
            cfg = {
                "id": row.id,
                "name": row.name or "",
                "provider": (row.provider or "mock").strip().lower(),
                "base_url": (row.base_url or "").strip(),
                "model": (row.model or "").strip(),
                "api_key": row.api_key or "",
                "timeout": int(row.timeout or settings.AI_OCR_TIMEOUT),
                "json_mode": bool(row.json_mode),
                "retry": int(row.retry if row.retry is not None else settings.AI_OCR_RETRY),
            }
        _CACHE["cfg"] = cfg
        _CACHE["ts"] = now
        return cfg
    except SQLAlchemyError:
        # 老库还没建表：缓存一个 None，避免每次识别都去撞一次不存在表
        _CACHE["cfg"] = None
        _CACHE["ts"] = now
        return None
    finally:
        db.close()


def resolve_engine() -> dict:
    """得到当前生效的识别引擎配置。

    返回键与历史版本保持一致（provider / is_remote / base_url / model / api_key），
    另外多了 timeout / json_mode / retry / source / config_name。
    """
    active = _load_active_row()
    if active:
        provider = active["provider"] or "mock"
        preset = PROVIDER_PRESETS.get(provider, {})
        return {
            "provider": provider,
            "is_remote": provider != "mock",
            "base_url": (active["base_url"] or preset.get("base_url", "")).rstrip("/"),
            "model": active["model"] or preset.get("model", ""),
            "api_key": active["api_key"] or "",
            "timeout": active["timeout"],
            "json_mode": active["json_mode"],
            "retry": active["retry"],
            "source": "database",
            "config_name": active["name"],
            "config_id": active["id"],
        }
    provider = (settings.AI_OCR_PROVIDER or "mock").strip().lower()
    preset = PROVIDER_PRESETS.get(provider, {})
    return {
        "provider": provider,
        "is_remote": provider != "mock",
        "base_url": (settings.AI_OCR_BASE_URL or preset.get("base_url", "")).rstrip("/"),
        "model": settings.AI_OCR_MODEL or preset.get("model", ""),
        "api_key": settings.AI_OCR_API_KEY or "",
        "timeout": settings.AI_OCR_TIMEOUT,
        "json_mode": settings.AI_OCR_JSON_MODE,
        "retry": settings.AI_OCR_RETRY,
        "source": "env",
        "config_name": "",
        "config_id": None,
    }


def mask_key(key: str) -> str:
    """密钥脱敏：只保留末 4 位，够管理员辨认是哪把 key，又不会把明文显示在页面上。"""
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{'*' * 8}{key[-4:]}"


def to_dict(row, with_secret: bool = False) -> dict:
    """档案 → 接口字典（默认脱敏；with_secret 供后端内部使用）。"""
    provider = (row.provider or "mock").strip().lower()
    preset = PROVIDER_PRESETS.get(provider, {})
    data = {
        "id": row.id,
        "name": row.name or "",
        "provider": provider,
        "provider_label": PROVIDER_LABELS.get(provider, provider),
        "base_url": row.base_url or "",
        "model": row.model or "",
        "effective_base_url": (row.base_url or preset.get("base_url", "")).rstrip("/"),
        "effective_model": row.model or preset.get("model", ""),
        "key_configured": bool((row.api_key or "").strip()),
        "api_key_masked": mask_key(row.api_key),
        "timeout": int(row.timeout or settings.AI_OCR_TIMEOUT),
        "json_mode": bool(row.json_mode),
        "retry": int(row.retry if row.retry is not None else settings.AI_OCR_RETRY),
        "is_active": bool(row.is_active),
        "remark": row.remark or "",
        "created_by": row.created_by or "",
        "created_at": str(row.created_at)[:19] if row.created_at else "",
        "updated_at": str(row.updated_at)[:19] if row.updated_at else "",
    }
    if with_secret:
        data["api_key"] = row.api_key or ""
    return data


def describe(row) -> dict:
    """把一个档案转换为可直接喂给识别服务的引擎配置（测试连接时用）。"""
    provider = (row.provider or "mock").strip().lower()
    preset = PROVIDER_PRESETS.get(provider, {})
    return {
        "provider": provider,
        "is_remote": provider != "mock",
        "base_url": (row.base_url or preset.get("base_url", "")).rstrip("/"),
        "model": row.model or preset.get("model", ""),
        "api_key": row.api_key or "",
        "timeout": int(row.timeout or settings.AI_OCR_TIMEOUT),
        "json_mode": bool(row.json_mode),
        "retry": int(row.retry if row.retry is not None else settings.AI_OCR_RETRY),
    }
