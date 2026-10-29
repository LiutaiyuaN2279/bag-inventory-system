"""登录失败限流与临时锁定。

演示系统里所有账号口令相同（`admin123`），登录接口原本可以无限次尝试。
这里用进程内计数器做最小防护：

- **账号维度**：同一用户名在 `LOGIN_FAIL_WINDOW` 秒内失败 `LOGIN_MAX_FAILS` 次即锁定
  `LOGIN_LOCK_SECONDS` 秒；
- **IP 维度**：同一 IP 的阈值放宽到 `LOGIN_IP_MAX_FAILS` 次——演示环境里所有请求都来自
  127.0.0.1，若与账号同阈值，一次误操作会把整台机器上所有人都锁在门外；
- 登录成功立即清零。

计数只存在内存里（单进程 uvicorn 足够）。多进程 / 多实例部署时应当换成 Redis 或数据库表，
否则计数会被拆散到各进程。锁表按需惰性清理，不会随运行时间无限增长。
"""
import threading
import time
from dataclasses import dataclass

from app.core.config import settings

_lock = threading.Lock()

#: key -> 窗口内失败时间戳列表（key 形如 ``u:admin`` / ``ip:127.0.0.1``）
_fails: dict[str, list[float]] = {}
#: key -> 解封时间（time.time() 时间轴）
_locked_until: dict[str, float] = {}
#: 上次惰性清理时间
_last_gc = 0.0

#: 两次清理的最小间隔，避免每个请求都遍历全表
_GC_INTERVAL = 60.0


@dataclass
class GuardState:
    """一次登录尝试的保护状态。"""

    locked: bool = False        # 当前是否处于锁定期
    remaining: int = 0          # 距解锁还有多少秒
    fail_count: int = 0         # 当前窗口内该账号的失败次数
    limit: int = 0              # 该账号的失败阈值
    scope: str = ""             # 触发了哪个维度的限制：username / ip


def _account_key(username: str) -> str:
    return f"u:{(username or '').strip().lower()}"


def _ip_key(ip: str) -> str:
    return f"ip:{ip}" if ip else ""


def _prune(now: float) -> None:
    """丢弃窗口外的失败时间戳，并清理解封的锁定记录。"""
    window = max(1, settings.LOGIN_FAIL_WINDOW)
    for key, stamps in list(_fails.items()):
        keep = [t for t in stamps if now - t < window]
        if keep:
            _fails[key] = keep
        else:
            _fails.pop(key, None)
    for key, until in list(_locked_until.items()):
        if until <= now:
            _locked_until.pop(key, None)


def _maybe_gc(now: float) -> None:
    global _last_gc
    if now - _last_gc >= _GC_INTERVAL:
        _prune(now)
        _last_gc = now


def check(username: str, ip: str = "") -> GuardState:
    """登录**前**调用：该账号 / IP 是否已被锁定。"""
    now = time.time()
    with _lock:
        _maybe_gc(now)

        ip_limit = max(1, settings.LOGIN_IP_MAX_FAILS)
        targets = [(_account_key(username), max(1, settings.LOGIN_MAX_FAILS) - 1, "username")] if username else []
        if ip:
            targets.append((_ip_key(ip), ip_limit - 1, "ip"))

        for key, _threshold, scope in targets:
            until = _locked_until.get(key, 0.0)
            if until > now:
                return GuardState(
                    locked=True,
                    remaining=int(until - now) + 1,
                    fail_count=len(_fails.get(key, [])),
                    limit=(max(1, settings.LOGIN_MAX_FAILS) if scope == "username" else ip_limit),
                    scope=scope,
                )

        account_fails = len(_fails.get(_account_key(username), [])) if username else 0
        return GuardState(
            locked=False,
            fail_count=account_fails,
            limit=max(1, settings.LOGIN_MAX_FAILS),
        )


def record_failure(username: str, ip: str = "") -> GuardState:
    """登录**失败**后调用：累加计数，达到阈值则开始锁定。"""
    now = time.time()
    window = max(1, settings.LOGIN_FAIL_WINDOW)
    account_limit = max(1, settings.LOGIN_MAX_FAILS)
    ip_limit = max(1, settings.LOGIN_IP_MAX_FAILS)
    lock_seconds = max(1, settings.LOGIN_LOCK_SECONDS)

    with _lock:
        _maybe_gc(now)

        def _bump(key: str, limit: int, scope: str) -> GuardState | None:
            stamps = [t for t in _fails.get(key, []) if now - t < window]
            stamps.append(now)
            _fails[key] = stamps
            if len(stamps) >= limit:
                _locked_until[key] = now + lock_seconds
                return GuardState(
                    locked=True, remaining=lock_seconds,
                    fail_count=len(stamps), limit=limit, scope=scope,
                )
            return None

        state = GuardState()
        if username:
            hit = _bump(_account_key(username), account_limit, "username")
            state = hit or GuardState(fail_count=len(_fails[_account_key(username)]), limit=account_limit)
        if ip:
            hit = _bump(_ip_key(ip), ip_limit, "ip")
            if hit:
                state = hit
        return state


def clear(username: str, ip: str = "") -> None:
    """登录成功后清零该账号（以及该 IP）的失败记录。"""
    with _lock:
        if username:
            _fails.pop(_account_key(username), None)
            _locked_until.pop(_account_key(username), None)
        if ip:
            _fails.pop(_ip_key(ip), None)
            _locked_until.pop(_ip_key(ip), None)


def reset_all() -> None:
    """测试用：清空所有计数与锁定。"""
    with _lock:
        _fails.clear()
        _locked_until.clear()
