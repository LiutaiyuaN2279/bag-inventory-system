"""操作日志查询（仅系统管理员可见）。

中间件（`app/main.py`）把每一次 API 调用都记到 `operation_logs`：操作人、方法、
路径、查询串、HTTP 状态码、耗时、IP、User-Agent，写操作还有 `detail` 业务明细。
本模块只提供查询能力，日志由中间件写入，接口本身不产生日志（避免自激）。

权限：列表 / 详情 / 统计三个接口都要求 `system:log`，该权限码只授予 admin 角色。
"""
from datetime import date, datetime, timedelta
import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import require_permissions
from app.core.database import get_db
from app.crud.crud_base import apply_ordering
from app.models.quality import OperationLog
from app.models.rbac import User
from app.utils.response import page_result, success

router = APIRouter(prefix="/operation-logs", tags=["系统日志"])


def _date_range(date_from: str | None, date_to: str | None):
    """把 YYYY-MM-DD 转成 [起, 止) 的 datetime 边界。"""
    start = end = None
    if date_from:
        start = datetime.combine(date.fromisoformat(date_from), datetime.min.time())
    if date_to:
        end = datetime.combine(date.fromisoformat(date_to) + timedelta(days=1), datetime.min.time())
    return start, end


def _base_query(db: Session, username: str | None, keyword: str | None, method: str | None,
                status: str | None, date_from: str | None, date_to: str | None):
    q = db.query(OperationLog)
    if username:
        q = q.filter(OperationLog.username.like(f"%{username}%"))
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            OperationLog.path.like(like)
            | OperationLog.action.like(like)
            | OperationLog.query.like(like)
            | OperationLog.detail.like(like)
        )
    if method:
        q = q.filter(OperationLog.method == method.upper())
    if status == "fail":
        q = q.filter(OperationLog.status_code >= 400)
    elif status == "success":
        q = q.filter(OperationLog.status_code < 400)
    start, end = _date_range(date_from, date_to)
    if start:
        q = q.filter(OperationLog.created_at >= start)
    if end:
        q = q.filter(OperationLog.created_at < end)
    return q


def _login_result(r: OperationLog) -> str:
    """登录类日志从 detail 里取出结果（成功 / 密码错误 / 已锁定）。

    状态码 40100 只能说明「未登录」，具体是密码错还是被锁定要看 detail，
    单独提出一个字段，前端「结果」列才能直接显示，不用点进详情。
    """
    if not r.detail or '"login"' not in r.detail:
        return ""
    try:
        return str((json.loads(r.detail) or {}).get("login", {}).get("result") or "")
    except Exception:
        return ""


def _row(r: OperationLog) -> dict:
    return {
        "id": r.id, "username": r.username, "method": r.method, "path": r.path,
        "action": r.action, "ip": r.ip, "query": r.query, "ua": r.ua,
        "status_code": r.status_code, "elapsed_ms": r.elapsed_ms,
        "created_at": str(r.created_at)[:19],
        "login_result": _login_result(r),
    }


@router.get("")
def list_logs(page: int = 1, page_size: int = 20, keyword: str | None = None,
              username: str | None = None, method: str | None = None,
              status: str | None = Query(default=None, description="success / fail"),
              date_from: str | None = None, date_to: str | None = None,
              sort_by: str | None = None, sort_order: str | None = None,
              db: Session = Depends(get_db), _=Depends(require_permissions("system:log"))):
    """分页查询操作日志：支持按用户、方法、路径/动作/明细关键字、结果、日期范围过滤。"""
    q = _base_query(db, username, keyword, method, status, date_from, date_to)
    total = q.count()
    rows = apply_ordering(q, OperationLog, sort_by, sort_order) \
        .offset((page - 1) * page_size).limit(page_size).all()
    return success(page_result([_row(r) for r in rows], total))


@router.get("/stats")
def log_stats(days: int = Query(default=7, ge=1, le=30),
              db: Session = Depends(get_db), _=Depends(require_permissions("system:log"))):
    """近 N 天的日志概览：总量、今日量、活跃用户、失败请求、每日趋势、高频用户与接口。"""
    today_start = datetime.combine(date.today(), datetime.min.time())
    window_start = today_start - timedelta(days=days - 1)

    total = db.query(func.count(OperationLog.id)).scalar() or 0
    today_total = db.query(func.count(OperationLog.id)) \
        .filter(OperationLog.created_at >= today_start).scalar() or 0
    # 「匿名 / 未认证」是无令牌请求的占位名，不是真实账号，统计活跃账号时排除
    invisible = ("匿名", "未认证", "")
    today_users = db.query(func.count(func.distinct(OperationLog.username))) \
        .filter(OperationLog.created_at >= today_start,
                OperationLog.username.notin_(invisible)).scalar() or 0
    today_fail = db.query(func.count(OperationLog.id)) \
        .filter(OperationLog.created_at >= today_start, OperationLog.status_code >= 400).scalar() or 0

    # 每日趋势（补齐没有日志的日期，前端画图不会断点）
    day_col = func.date(OperationLog.created_at)
    rows = db.query(day_col.label("d"), func.count(OperationLog.id)) \
        .filter(OperationLog.created_at >= window_start).group_by(day_col).all()
    counts = {str(d): c for d, c in rows}
    trend = []
    for i in range(days):
        d = (window_start + timedelta(days=i)).date().isoformat()
        trend.append({"date": d, "count": counts.get(d, 0)})

    top_users = [
        {"username": u or "匿名", "count": c}
        for u, c in db.query(OperationLog.username, func.count(OperationLog.id))
        .filter(OperationLog.created_at >= window_start)
        .group_by(OperationLog.username)
        .order_by(func.count(OperationLog.id).desc()).limit(8).all()
    ]
    top_paths = [
        {"path": p, "count": c}
        for p, c in db.query(OperationLog.path, func.count(OperationLog.id))
        .filter(OperationLog.created_at >= window_start)
        .group_by(OperationLog.path)
        .order_by(func.count(OperationLog.id).desc()).limit(8).all()
    ]
    return success({
        "total": total, "today_total": today_total, "today_users": today_users,
        "today_fail": today_fail, "days": days, "trend": trend,
        "top_users": top_users, "top_paths": top_paths,
    })


@router.get("/{log_id}")
def log_detail(log_id: int, db: Session = Depends(get_db),
               _=Depends(require_permissions("system:log"))):
    """单条日志详情：含业务明细 detail（报销判读结论、制单修改等）。"""
    r = db.get(OperationLog, log_id)
    if not r:
        from app.core.exceptions import BizException
        raise BizException("日志不存在")
    real_name = ""
    user = db.query(User).filter(User.username == r.username).first()
    if user:
        real_name = user.real_name or ""
    data = _row(r)
    data["detail"] = r.detail or ""
    data["real_name"] = real_name
    return success(data)
