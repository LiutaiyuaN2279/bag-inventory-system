"""应用配置：读取 .env，环境变量优先。"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "箱包采购与库存管理系统"
    APP_ENV: str = "dev"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    DATABASE_URL: str = "sqlite:///./data/app.db"
    # Independent non-formal trial archive; does not migrate the business database.
    AUDIT_TRIAL_ARCHIVE_DIR: str = "data/audit_trials"

    # 上传文件归档目录（相对 backend 工作目录）。
    # AI 单据识别会把上传的原图落盘保存在这里，识别记录只存相对路径。
    UPLOAD_DIR: str = "./data/uploads"

    SECRET_KEY: str = "bag-purchasing-inventory-secret-key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # 逗号分隔的跨域源。
    # 最后一项是打包成 APK 后 WebView 的固定源（WebViewAssetLoader 提供），
    # 不加上它，手机端所有请求都会被 CORS 预检拒绝。
    CORS_ORIGINS: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "https://appassets.androidplatform.net"
    )

    # ---- AI 单据识别（OCR）----
    # provider：mock（离线演示，无需密钥）
    #         | dashscope（阿里云百炼 · 通义千问-VL）
    #         | ark（火山方舟 · 豆包视觉）
    #         | zhipu（智谱 GLM-4V）
    #         | openai（OpenAI）
    #         | custom（自定义 OpenAI 兼容网关，需同时填 BASE_URL 与 MODEL）
    AI_OCR_PROVIDER: str = "mock"
    AI_OCR_API_KEY: str = ""
    AI_OCR_BASE_URL: str = ""         # 留空则使用所选 provider 的预设地址
    AI_OCR_MODEL: str = ""            # 留空则使用所选 provider 的预设模型
    AI_OCR_TIMEOUT: int = 60          # 调用识别接口超时（秒）
    AI_OCR_MAX_MB: int = 8            # 上传图片大小上限（MB）
    AI_OCR_JSON_MODE: bool = True     # 请求 response_format=json_object（个别网关不支持时可关闭）
    AI_OCR_RETRY: int = 1             # 网络异常/5xx 时的重试次数

    # ---- 操作日志 ----
    #: 日志保留天数：启动时与每 6 小时清理一次更早的记录，避免表无限增长。
    #: 设为 0 表示不清理（演示时想把历史都留着可以这样配）。
    OPLOG_RETENTION_DAYS: int = 90
    #: 单批落库上限与攒批等待时间：日志走后台队列异步写入，不占用请求链路
    OPLOG_BATCH_MAX: int = 200
    OPLOG_FLUSH_DELAY: float = 0.3

    # ---- 登录保护 ----
    #: 同一账号或同一 IP 在窗口期内连续失败达到该次数即临时锁定
    LOGIN_MAX_FAILS: int = 5
    #: IP 维度阈值放宽：演示环境所有请求都来自 127.0.0.1，与账号同阈值会误锁所有人
    LOGIN_IP_MAX_FAILS: int = 20
    #: 失败计数的时间窗口与锁定时长（秒）
    LOGIN_FAIL_WINDOW: int = 300
    LOGIN_LOCK_SECONDS: int = 300

    # ---- GitHub 快捷登录（OAuth App）----
    # 演示用途：用 GitHub 账号一键登录，免去记演示口令。留空 CLIENT_ID/SECRET
    # 时登录页不会显示该按钮（enabled() 为 False），不影响原有账号登录。
    #: 总开关：false 时即使填了凭证也不启用
    GITHUB_OAUTH_ENABLED: bool = True
    #: 在 https://github.com/settings/developers → OAuth Apps 新建应用后获得
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    #: 回调地址，必须与 OAuth App 里填的 Authorization callback URL 完全一致
    GITHUB_REDIRECT_URI: str = "http://127.0.0.1:8000/api/v1/auth/github/callback"
    #: 登录成功后回跳的前端地址（浏览器里的站点根地址，不带 #）
    GITHUB_FRONTEND_URL: str = "http://127.0.0.1:5173"
    #: GitHub 用户映射到本系统的角色：默认 admin，即登录后拥有全部权限
    GITHUB_ADMIN_ROLE: str = "admin"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
