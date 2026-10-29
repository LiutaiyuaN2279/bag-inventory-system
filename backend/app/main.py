"""FastAPI 应用入口：跨域 / 异常处理 / 操作日志 / 路由挂载。"""
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import auth, materials, suppliers, warehouses, users, roles
from app.api.v1 import (
    purchase_requisitions, purchase_orders, purchase_arrivals, purchase_returns,
    inventory, stocktake, transfers, alerts, bom,
    outsource, quality, reports, logs, excel, ai_ocr, audit,
)
from app.core.config import settings
from app.api.v1.reimburse import bills as rmb_bills
from app.api.v1.reimburse import compliance as rmb_compliance
from app.api.v1.reimburse import vouchers as rmb_vouchers
from app.api.v1.reimburse import policy as rmb_policy
from app.core.database import SessionLocal
from app.core.exceptions import (
    AuthException,
    BizException,
    CODE_BIZ_ERROR,
    CODE_FORBIDDEN,
    CODE_SUCCESS,
    CODE_UNAUTHORIZED,
    PermissionException,
)
from app.core.security import decode_token
from app.models.quality import OperationLog
from app.models.rbac import User
from sqlalchemy import text

logger = logging.getLogger(__name__)


# ---------- 操作日志：后台异步批量落库 ----------
# 为什么不在中间件里直接写库：SQLite 同一时刻只有一个写者，每个请求都同步 INSERT+COMMIT
# 会让日志写入串行化到业务请求上（并发高时会看到明显的延迟抖动）。改成「请求线程只入队、
# 后台任务攒批落库」后，请求链路上几乎没有额外开销。
#: 自身查询接口（列表 / 统计 / 详情）都不记录，否则「看一眼日志」又会生成一条日志，形成自激
_LOG_SKIP_PREFIX = "/api/v1/operation-logs"
#: 同一用户 2 秒内对同一接口的重复请求只记一条；写操作不受此限制，一律记录
_LOG_DEDUP_WINDOW_S = 2.0
_LOG_MAX_DEDUP_ENTRIES = 5000

_log_dedup_cache: dict[tuple, float] = {}
#: 待写日志队列；lifespan 启动时创建（模块导入时还没有事件循环）
_log_queue: asyncio.Queue | None = None
#: 队列满时丢弃的条数（只在服务端日志里提示，不抛给业务）
_log_dropped = 0


def _get_log_queue() -> asyncio.Queue:
    global _log_queue
    if _log_queue is None:
        _log_queue = asyncio.Queue(maxsize=10000)
    return _log_queue


def _flush_logs(rows: list[dict]) -> None:
    """把一批日志写进数据库（在线程里跑，避免阻塞事件循环）。"""
    if not rows:
        return
    db = SessionLocal()
    try:
        db.bulk_insert_mappings(OperationLog, rows)
        db.commit()
    finally:
        db.close()


async def _log_writer_loop() -> None:
    """后台消费者：等一小会儿把同一波请求的日志并成一批再写。"""
    queue = _get_log_queue()
    while True:
        try:
            first = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        batch = [first]
        delay = max(0.0, settings.OPLOG_FLUSH_DELAY)
        if delay:
            await asyncio.sleep(delay)
        while len(batch) < max(1, settings.OPLOG_BATCH_MAX):
            try:
                batch.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        try:
            await asyncio.to_thread(_flush_logs, batch)
        except Exception:  # 日志写失败不能影响业务，只记录
            logger.warning("操作日志批量写入失败，丢弃 %d 条", len(batch), exc_info=True)


async def _drain_logs() -> None:
    """进程退出前把队列里剩下的日志尽量写完。"""
    queue = _get_log_queue()
    rows = []
    while True:
        try:
            rows.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    if rows:
        try:
            await asyncio.to_thread(_flush_logs, rows)
        except Exception:
            logger.warning("退出前写操作日志失败，丢弃 %d 条", len(rows), exc_info=True)


def _purge_old_logs() -> None:
    """删除超过保留期的操作日志，并顺手回收 WAL 文件。"""
    days = int(settings.OPLOG_RETENTION_DAYS or 0)
    if days <= 0:
        return
    cutoff = datetime.now() - timedelta(days=days)
    db = SessionLocal()
    try:
        deleted = (
            db.query(OperationLog)
            .filter(OperationLog.created_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
        if deleted:
            logger.info("操作日志过期清理：删除 %d 条（早于 %s）", deleted, cutoff.date())
        if settings.DATABASE_URL.startswith("sqlite"):
            db.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
    except Exception:
        logger.warning("操作日志过期清理失败", exc_info=True)
    finally:
        db.close()


async def _log_retention_loop() -> None:
    """启动时清理一次，之后每 6 小时一次。"""
    while True:
        await asyncio.to_thread(_purge_old_logs)
        await asyncio.sleep(6 * 3600)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动日志后台任务，退出前把队列写完。"""
    tasks = [
        asyncio.create_task(_log_writer_loop(), name="oplog-writer"),
        asyncio.create_task(_log_retention_loop(), name="oplog-retention"),
    ]
    logger.info(
        "操作日志：异步写入已启动（攒批 %d 条 / %.1fs，保留 %s 天）",
        settings.OPLOG_BATCH_MAX, settings.OPLOG_FLUSH_DELAY,
        settings.OPLOG_RETENTION_DAYS or "永久",
    )
    print(
        "操作日志：异步写入已启动（攒批 %s 条 / %ss，保留 %s 天）"
        % (settings.OPLOG_BATCH_MAX, settings.OPLOG_FLUSH_DELAY, settings.OPLOG_RETENTION_DAYS or "永久")
    )
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await _drain_logs()


app = FastAPI(title=settings.APP_NAME, version="1.0.0", lifespan=lifespan)

# 跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 操作日志中间件：记录所有 API 请求（含查询） ----------
def _should_log(request: Request) -> bool:
    path = request.url.path
    if not path.startswith("/api/"):
        return False
    if request.method == "OPTIONS":
        return False
    return not path.startswith(_LOG_SKIP_PREFIX)


def _dedup_hit(username: str, method: str, path: str, query: str) -> bool:
    """写操作不去重；查询类 2 秒内同键只记一次。"""
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        return False
    key = (username, method, path, query)
    now = time.monotonic()
    last = _log_dedup_cache.get(key)
    if last is not None and now - last < _LOG_DEDUP_WINDOW_S:
        return True
    _log_dedup_cache[key] = now
    if len(_log_dedup_cache) > _LOG_MAX_DEDUP_ENTRIES:  # 防止长期运行无限膨胀
        for k, ts in list(_log_dedup_cache.items()):
            if now - ts > _LOG_DEDUP_WINDOW_S:
                _log_dedup_cache.pop(k, None)
    return False


def _resolve_username(request: Request, login_user: str) -> str:
    """从 Bearer 令牌解析操作人；登录请求用请求体里的用户名。"""
    authz = request.headers.get("authorization", "")
    if authz.lower().startswith("bearer "):
        try:
            payload = decode_token(authz.split(" ", 1)[1])
            db = SessionLocal()
            try:
                user = db.get(User, int(payload.get("sub")))
                if user:
                    return user.username
            finally:
                db.close()
        except Exception:
            return "未认证"
    return login_user or "匿名"


async def _write_log(request: Request, status_code: int, elapsed_ms: int, login_user: str) -> None:
    """把一条日志塞进队列，由后台任务批量落库。

    任何异常都只写服务端日志，绝不影响业务请求；队列满时丢弃并在服务端日志里提示。
    """
    global _log_dropped
    try:
        # 解析令牌要查 users 表，放到线程里做，别阻塞事件循环
        username = await asyncio.to_thread(_resolve_username, request, login_user)
        path = request.url.path
        query = request.url.query or ""
        if _dedup_hit(username, request.method, path, query):
            return
        is_login = path.endswith("/auth/login")
        detail = getattr(request.state, "log_detail", "") or ""
        if not isinstance(detail, str):
            detail = json.dumps(detail, ensure_ascii=False)
        row = {
            "username": username,
            "method": request.method,
            "path": path,
            "action": "登录" if is_login else (path.split("/api/v1/")[-1] or path),
            "ip": request.client.host if request.client else "",
            "status_code": status_code,
            "elapsed_ms": elapsed_ms,
            "query": query[:255],
            "ua": (request.headers.get("user-agent") or "")[:255],
            "detail": detail[:4000],
        }
        try:
            _get_log_queue().put_nowait(row)
        except asyncio.QueueFull:
            _log_dropped += 1
            if _log_dropped % 100 == 1:
                logger.warning("操作日志队列已满，累计丢弃 %d 条", _log_dropped)
    except Exception:
        logger.warning("操作日志入队失败: %s %s", request.method, request.url.path, exc_info=True)


@app.middleware("http")
async def operation_log_middleware(request: Request, call_next):
    if not _should_log(request):
        return await call_next(request)

    # 登录请求没有令牌，需要从请求体里取用户名；Request.body() 读取后会被 Starlette
    # 缓存在 request._body 上，下游接口仍能正常再次读取
    login_user = ""
    if request.url.path.endswith("/auth/login"):
        try:
            raw = await request.body()
            login_user = str((json.loads(raw or b"{}") or {}).get("username") or "")[:64]
        except Exception:
            login_user = ""

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        await _write_log(request, getattr(request.state, "biz_code", 0) or 500,
                         int((time.perf_counter() - started) * 1000), login_user)
        raise
    # 本项目业务异常统一返回 HTTP 200 + 响应体 code（40100/40300/50000），
    # 因此失败请求的真实结果要从异常处理器写下的 request.state.biz_code 取，
    # 否则日志里所有「被拒 / 失败」请求都会显示 200，等于没记。
    await _write_log(request, getattr(request.state, "biz_code", 0) or response.status_code,
                     int((time.perf_counter() - started) * 1000), login_user)
    return response

# ---------- 全局异常处理 ----------
@app.exception_handler(BizException)
async def biz_handler(request: Request, exc: BizException):
    request.state.biz_code = exc.code
    return JSONResponse(status_code=200, content={"code": exc.code, "message": exc.message, "data": None})


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    request.state.biz_code = CODE_BIZ_ERROR
    msg = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())
    return JSONResponse(status_code=200, content={"code": CODE_BIZ_ERROR, "message": msg or "参数校验失败", "data": None})


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    # 完整堆栈只写服务端日志，返回给客户端的是固定文案（避免内部实现细节泄露）
    logger.exception("未处理异常 %s %s: %s", request.method, request.url.path, exc)
    request.state.biz_code = CODE_BIZ_ERROR
    return JSONResponse(
        status_code=500,
        content={"code": CODE_BIZ_ERROR, "message": "服务器内部错误，请稍后重试或联系管理员", "data": None},
    )


# ---------- 路由 ----------
api_prefix = "/api/v1"
app.include_router(auth.router, prefix=api_prefix)
app.include_router(materials.router, prefix=api_prefix)
app.include_router(suppliers.router, prefix=api_prefix)
app.include_router(warehouses.router, prefix=api_prefix)
app.include_router(purchase_requisitions.router, prefix=api_prefix)
app.include_router(purchase_orders.router, prefix=api_prefix)
app.include_router(purchase_arrivals.router, prefix=api_prefix)
app.include_router(purchase_returns.router, prefix=api_prefix)
app.include_router(inventory.router, prefix=api_prefix)
app.include_router(stocktake.router, prefix=api_prefix)
app.include_router(transfers.router, prefix=api_prefix)
app.include_router(alerts.router, prefix=api_prefix)
app.include_router(bom.router, prefix=api_prefix)
app.include_router(outsource.router, prefix=api_prefix)
app.include_router(quality.router, prefix=api_prefix)
app.include_router(reports.router, prefix=api_prefix)
app.include_router(logs.router, prefix=api_prefix)
app.include_router(excel.router, prefix=api_prefix)
app.include_router(ai_ocr.router, prefix=api_prefix)
app.include_router(audit.router, prefix=api_prefix)
app.include_router(users.router, prefix=api_prefix)
app.include_router(roles.router, prefix=api_prefix)

# ---------- 差旅与业务招待费报销智能体 ----------
app.include_router(rmb_bills.router, prefix=api_prefix)
app.include_router(rmb_compliance.router, prefix=api_prefix)
app.include_router(rmb_vouchers.router, prefix=api_prefix)
app.include_router(rmb_policy.router, prefix=api_prefix)


@app.get("/api/health")
def health():
    return {"code": CODE_SUCCESS, "message": "ok", "data": {"app": settings.APP_NAME}}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.APP_HOST, port=settings.APP_PORT, reload=True)
