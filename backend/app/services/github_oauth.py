"""GitHub OAuth 快捷登录（只用标准库，不引入第三方 SDK）。

为什么单独成模块
----------------
``auth.py`` 只做路由与业务编排，OAuth 的协议细节（授权地址、换 token、拉用户信息、
state 与一次性票据）集中在这里，方便单独测试。项目后端依赖里没有 requests/httpx，
两个 HTTP 调用用标准库 ``urllib.request`` 完成，不为一种登录方式增加安装负担。

安全约定（演示系统的取舍，README「GitHub 快捷登录」一节已写明）
--------------------------------------------------------------
1. ``state`` 防 CSRF：发起登录时生成随机串存内存，回调校验并立即作废，10 分钟过期。
2. 不把 JWT 直接拼在回跳地址上：先换一张 60 秒内有效、用一次即作废的「登录票据」，
   前端用票据调 ``/auth/github/exchange`` 换正式 token，避免 token 残留在浏览器历史。
3. GitHub 用户统一映射成本地 ``admin`` 角色（由调用方 ``auth.py`` 完成），
   所以这个入口只适合演示环境；公网部署请把 ``GITHUB_OAUTH_ENABLED`` 关掉。
"""
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from app.core.config import settings

#: GitHub 的三个端点
AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"

#: state 有效期（秒）与一次性登录票据有效期（秒）
STATE_TTL = 600
TICKET_TTL = 60

#: 单次 HTTP 调用的超时（秒）
HTTP_TIMEOUT = 10

_lock = threading.Lock()
_states: dict[str, float] = {}     # state -> 过期时间戳
_tickets: dict[str, tuple[int, float]] = {}  # ticket -> (user_id, 过期时间戳)


def _purge(now: float) -> None:
    """清理过期条目，避免字典无限增长（调用方需已持锁）。"""
    for key in [k for k, expire in _states.items() if expire < now]:
        _states.pop(key, None)
    for key in [k for k, (_uid, expire) in _tickets.items() if expire < now]:
        _tickets.pop(key, None)


def _request_json(
    url: str,
    *,
    data: dict | None = None,
    token: str = "",
    method: str = "GET",
) -> dict:
    """发一个请求并解析 JSON；GitHub 报错时抛出带中文说明的 RuntimeError。"""
    body = urllib.parse.urlencode(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Accept", "application/json")
    # GitHub API 要求带 User-Agent，缺失会直接 403
    req.add_header("User-Agent", "bag-inventory-demo")
    if data:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:  # 4xx/5xx
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise RuntimeError(f"GitHub 接口返回 {exc.code}：{detail or exc.reason}") from exc
    except urllib.error.URLError as exc:  # 网络不可达 / DNS / 超时
        raise RuntimeError(f"连接 GitHub 失败（{exc.reason}），请检查网络或代理") from exc
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub 返回的内容不是合法 JSON，请稍后重试") from exc


def enabled() -> bool:
    """是否启用了 GitHub 快捷登录（总开关 + 凭证齐全）。"""
    return bool(
        settings.GITHUB_OAUTH_ENABLED
        and settings.GITHUB_CLIENT_ID.strip()
        and settings.GITHUB_CLIENT_SECRET.strip()
    )


# ---------------- state（防 CSRF）----------------


def new_state() -> str:
    """生成并记录一个 state。"""
    state = secrets.token_urlsafe(24)
    now = time.time()
    with _lock:
        _purge(now)
        _states[state] = now + STATE_TTL
    return state


def consume_state(state: str) -> bool:
    """校验并作废 state；不存在、过期或为空都返回 False。"""
    if not state:
        return False
    now = time.time()
    with _lock:
        _purge(now)
        expire = _states.pop(state, None)
    return bool(expire and expire >= now)


# ---------------- 一次性登录票据 ----------------


def issue_ticket(user_id: int) -> str:
    """签发一次性登录票据（回跳地址里只带它，不带 JWT）。"""
    ticket = secrets.token_urlsafe(32)
    now = time.time()
    with _lock:
        _purge(now)
        _tickets[ticket] = (user_id, now + TICKET_TTL)
    return ticket


def consume_ticket(ticket: str) -> int | None:
    """用掉一张票据，返回 user_id；无效或过期返回 None。"""
    if not ticket:
        return None
    now = time.time()
    with _lock:
        _purge(now)
        item = _tickets.pop(ticket, None)
    if not item:
        return None
    user_id, expire = item
    return user_id if expire >= now else None


# ---------------- OAuth 三步 ----------------


def authorize_url(state: str) -> str:
    """拼授权地址；scope 只要 read:user（读公开资料与姓名，不碰仓库）。"""
    query = urllib.parse.urlencode(
        {
            "client_id": settings.GITHUB_CLIENT_ID.strip(),
            "redirect_uri": settings.GITHUB_REDIRECT_URI.strip(),
            "scope": "read:user",
            "state": state,
            "allow_signup": "true",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def exchange_code(code: str) -> str:
    """用授权码换 access_token。"""
    payload = _request_json(
        TOKEN_URL,
        data={
            "client_id": settings.GITHUB_CLIENT_ID.strip(),
            "client_secret": settings.GITHUB_CLIENT_SECRET.strip(),
            "code": code,
            "redirect_uri": settings.GITHUB_REDIRECT_URI.strip(),
        },
        method="POST",
    )
    if payload.get("error"):
        raise RuntimeError(
            f"GitHub 拒绝授权：{payload.get('error_description') or payload['error']}"
        )
    token = payload.get("access_token") or ""
    if not token:
        raise RuntimeError("GitHub 未返回 access_token，请检查 OAuth App 配置")
    return token


def fetch_user(access_token: str) -> dict:
    """拉取当前 GitHub 用户资料，返回 {login, name, id, avatar_url, html_url}。"""
    data = _request_json(USER_URL, token=access_token)
    login = (data.get("login") or "").strip()
    if not login:
        raise RuntimeError("GitHub 未返回用户名，无法建立本地账号")
    return {
        "login": login,
        "name": (data.get("name") or "").strip(),
        "id": data.get("id") or 0,
        "avatar_url": data.get("avatar_url") or "",
        "html_url": data.get("html_url") or "",
    }


def local_username(login: str) -> str:
    """GitHub 登录名 → 本地用户名：加 ``gh_`` 前缀，只留安全字符。

    加前缀是为了和内置演示账号区分开：一眼能看出「这个账号是 GitHub 登录建出来的」，
    也避免有人把 GitHub 昵称取成 ``admin`` 直接顶掉内置管理员。
    """
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in login.lower())
    return ("gh_" + safe)[:64]
