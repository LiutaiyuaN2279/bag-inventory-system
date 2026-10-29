"""认证接口：登录 / GitHub 快捷登录 / 当前用户信息 / 登出。"""
import json
import logging
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core import login_guard
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import AuthException, BizException
from app.core.security import create_access_token, hash_password
from app.crud.crud_auth import (
    authenticate,
    get_user_denied_permissions,
    get_user_permissions,
    get_user_roles,
)
from app.models.rbac import Role, User, UserRole
from app.models.reimburse import RmbDepartment, RmbEmployee
from app.schemas.auth import GithubExchangeIn, LoginIn
from app.services import github_oauth
from app.utils.response import success

router = APIRouter(prefix="/auth", tags=["认证"])

logger = logging.getLogger(__name__)


# ---------------- 登录页账号排序 ----------------
#: 部门展示顺序（按管理层级 → 职能 → 业务前线）。系统账号无部门，排最前。
DEPT_ORDER = {
    "总经办": 1,
    "财务部": 2,
    "销售部": 3,
    "采购部": 4,
    "仓储部": 5,
    "质检部": 6,
    "信息技术部": 7,
    "行政部": 8,
}

#: 职级权重（数字越小越靠前）。一人多岗时取最高职级（最小值）。
#: 「总经办」的总经理已由部门顺序体现，这里仍给最高权重便于同部门内排序。
POSITION_ORDER = {
    "general_manager": 1,   # 总经理
    "dept_director": 2,     # 部门总监
    "dept_head": 3,         # 部门负责人
    "manager": 4,           # 运营主管
    "finance_review": 5,    # 财务复核
    "finance_approve": 6,   # 财务审批
    "reviewer": 7,          # 复核员
    "maker": 8,             # 制单员
    "staff": 9,             # 普通员工
    "buyer": 9,             # 采购员
    "keeper": 9,            # 仓管员
    "qc": 9,                # 质检员
    "admin": 0,             # 系统管理员（无部门，排最前）
}


def _account_sort_key(username: str, dept_name: str, role_codes: list[str]) -> tuple:
    """账号排序键：(部门顺序, 职级顺序, 用户名)。

    系统管理员无部门 → 部门序 0（最前）；其余按 DEPT_ORDER；
    未见过的部门排到末尾但仍稳定。
    """
    dept_rank = 0 if not dept_name else DEPT_ORDER.get(dept_name, 99)
    if not dept_name and "admin" in role_codes:
        dept_rank = -1          # 系统管理员永远第一个
    pos_rank = min(
        (POSITION_ORDER.get(code, 9) for code in role_codes),
        default=9,
    )
    return (dept_rank, pos_rank, username)


@router.get("/accounts")
def accounts(db: Session = Depends(get_db)):
    """登录页账号选择：返回启用用户列表（公开，不含密码）。

    除用户名/姓名外，附带**部门**与**职位**（取角色名），便于登录时识别身份。
    部门来自报销模块的员工档案（users.employee_id → rmb_employee → rmb_department）；
    系统账号没有员工档案，部门留空、只显示职位。

    返回结果**按「部门 → 职位」排序**：同部门的人聚在一起，部门内管理岗在前、
    执行岗在后，便于在登录页按组织架构找到目标账号。
    """
    rows = db.query(User).filter(User.status == True).all()  # noqa: E712

    # 批量取员工与部门，避免逐个查询造成 N+1
    emp_ids = [u.employee_id for u in rows if u.employee_id]
    employees = {}
    if emp_ids:
        employees = {
            e.id: e for e in db.query(RmbEmployee).filter(RmbEmployee.id.in_(emp_ids)).all()
        }
    dept_ids = {e.department_id for e in employees.values() if e.department_id}
    departments = {}
    if dept_ids:
        departments = {
            d.id: d.name
            for d in db.query(RmbDepartment).filter(RmbDepartment.id.in_(dept_ids)).all()
        }

    result = []
    for u in rows:
        emp = employees.get(u.employee_id)
        dept_name = departments.get(emp.department_id) if emp and emp.department_id else ""
        # 角色即职位；一人多岗时用「、」连接（如「运营主管、财务复核」）
        role_names = [r.role_name for r in (u.roles or [])]
        role_codes = [r.role_code for r in (u.roles or [])]
        result.append({
            "username": u.username,
            "real_name": u.real_name or u.username,
            "department": dept_name,
            # 无部门时（系统账号）部门留空，前端只显示职位
            "position": "、".join(role_names),
            "roles": role_codes,
        })

    # 按「部门 → 职位」排序（同部门聚在一起，管理岗在前）
    result.sort(key=lambda a: _account_sort_key(
        a["username"], a["department"], a["roles"]))
    return success(result)


# ---------------- GitHub 快捷登录 ----------------
# 演示系统提供的一种免口令登录方式：用 GitHub 账号一键进入，登录即 admin。
# 未配置 GITHUB_CLIENT_ID/SECRET 时 enabled() 为 False，登录页不显示按钮，
# 原有「演示账号 + 口令」登录链路完全不受影响。


def _upsert_github_user(db: Session, gh_user: dict) -> User:
    """GitHub 用户 → 本地账号：不存在就创建，存在就补齐 admin 角色。

    用户名统一带 ``gh_`` 前缀（见 ``github_oauth.local_username``），密码是随机串，
    即「只能走 GitHub 登录、不能用口令登录」。账号被停用时直接拒绝，不自动启用。
    """
    username = github_oauth.local_username(gh_user["login"])
    user = db.query(User).filter(User.username == username).one_or_none()
    if user is None:
        user = User(
            username=username,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            real_name=gh_user.get("name") or gh_user["login"],
            status=True,
        )
        db.add(user)
        db.flush()
    else:
        if not user.status:
            raise BizException("该 GitHub 账号对应的系统账号已被停用，请联系管理员")
        # GitHub 昵称可能被改过，同步显示名
        if gh_user.get("name") and user.real_name != gh_user["name"]:
            user.real_name = gh_user["name"]

    role = (
        db.query(Role)
        .filter(Role.role_code == settings.GITHUB_ADMIN_ROLE)
        .one_or_none()
    )
    if role is None:
        raise BizException(
            f"系统缺少「{settings.GITHUB_ADMIN_ROLE}」角色，请先初始化角色数据"
        )
    linked = (
        db.query(UserRole)
        .filter(UserRole.user_id == user.id, UserRole.role_id == role.id)
        .first()
    )
    if not linked:
        db.add(UserRole(user_id=user.id, role_id=role.id))
    db.commit()
    db.refresh(user)
    return user


@router.get("/github/status")
def github_status():
    """登录页用：是否显示「使用 GitHub 登录」按钮。

    公开接口，只回显配置是否就绪，不含 client_secret。
    """
    return success(
        {
            "enabled": github_oauth.enabled(),
            "login_url": "/api/v1/auth/github/login",
            "redirect_uri": settings.GITHUB_REDIRECT_URI,
            "admin_role": settings.GITHUB_ADMIN_ROLE,
        }
    )


@router.get("/github/login")
def github_login():
    """跳转到 GitHub 授权页（scope=read:user，只读基本资料）。"""
    if not github_oauth.enabled():
        raise BizException(
            "未启用 GitHub 登录：请在 backend/.env 填写 GITHUB_CLIENT_ID 与 "
            "GITHUB_CLIENT_SECRET（见 README「GitHub 快捷登录」）"
        )
    return RedirectResponse(github_oauth.authorize_url(github_oauth.new_state()), status_code=302)


@router.get("/github/callback")
def github_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
    db: Session = Depends(get_db),
):
    """GitHub 回调：校验 state → 换 token → 取用户 → 建/补账号 → 带票据回跳前端。

    任何一步失败都 302 回前端登录页并带 ``gh_error``，错误文案直接展示给用户，
    不用跳到一个裸的错误 JSON 页面上。
    """
    front = settings.GITHUB_FRONTEND_URL.rstrip("/")

    def back(**query: str) -> RedirectResponse:
        return RedirectResponse(f"{front}/#/login?{urlencode(query)}", status_code=302)

    if error:
        return back(gh_error=error_description or error)
    if not code:
        return back(gh_error="GitHub 未返回授权码，请重试")
    if not github_oauth.consume_state(state):
        return back(gh_error="登录校验失败（state 无效或已过期），请重新发起登录")

    try:
        gh_user = github_oauth.fetch_user(github_oauth.exchange_code(code))
        user = _upsert_github_user(db, gh_user)
    except Exception as exc:  # 网络、GitHub 报错、角色缺失等
        logger.warning("GitHub 快捷登录失败：%s", exc)
        return back(gh_error=str(exc))

    # 记进操作日志：谁在什么时候用 GitHub 账号登录了系统
    request.state.log_detail = json.dumps(
        {
            "login": {
                "username": user.username,
                "result": "GitHub 快捷登录",
                "github": gh_user["login"],
            }
        },
        ensure_ascii=False,
    )
    # URL 里只带一次性票据，正式 token 由前端调 /auth/github/exchange 换取
    return back(gh_code=github_oauth.issue_ticket(user.id))


@router.post("/github/exchange")
def github_exchange(data: GithubExchangeIn, request: Request, db: Session = Depends(get_db)):
    """一次性票据换正式 token（60 秒内有效、用一次即废）。"""
    user_id = github_oauth.consume_ticket(data.code)
    if not user_id:
        raise AuthException("登录票据无效或已过期，请重新使用 GitHub 登录")
    user = db.get(User, user_id)
    if not user or not user.status:
        raise AuthException("账号不存在或已被停用，请联系管理员")
    ip = request.client.host if request.client else ""
    login_guard.clear(user.username, ip)
    request.state.log_detail = json.dumps(
        {"login": {"username": user.username, "result": "GitHub 快捷登录"}},
        ensure_ascii=False,
    )
    return success(
        {
            "access_token": create_access_token(user.id),
            "token_type": "bearer",
            "username": user.username,
            "real_name": user.real_name,
        }
    )


@router.post("/login")
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    """登录。

    连续失败会被临时锁定（见 ``app.core.login_guard``）：同账号 5 次 / 同 IP 20 次，
    锁 5 分钟。每次尝试的账号与结果写进 ``request.state.log_detail``，由操作日志中间件
    落库，管理员可以在“操作日志”里看到是谁在什么时间试了哪个账号、失败了几次。
    """
    ip = request.client.host if request.client else ""
    state = login_guard.check(data.username, ip)
    if state.locked:
        minutes = max(1, (state.remaining + 59) // 60)
        request.state.log_detail = json.dumps(
            {
                "login": {
                    "username": data.username,
                    "result": "已锁定",
                    "scope": state.scope,
                    "fail_count": state.fail_count,
                    "remaining_seconds": state.remaining,
                }
            },
            ensure_ascii=False,
        )
        raise AuthException(f"尝试次数过多，账号已临时锁定，请 {minutes} 分钟后再试")

    user = authenticate(db, data.username, data.password)
    if not user:
        after = login_guard.record_failure(data.username, ip)
        request.state.log_detail = json.dumps(
            {
                "login": {
                    "username": data.username,
                    "result": "密码错误",
                    "fail_count": after.fail_count,
                    "locked": after.locked,
                    "scope": after.scope,
                    "remaining_seconds": after.remaining,
                }
            },
            ensure_ascii=False,
        )
        if after.locked:
            minutes = max(1, (after.remaining + 59) // 60)
            raise AuthException(f"用户名或密码错误，失败次数过多，已临时锁定 {minutes} 分钟")
        left = max(0, after.limit - after.fail_count)
        raise AuthException(f"用户名或密码错误，再错 {left} 次将临时锁定")

    login_guard.clear(data.username, ip)
    request.state.log_detail = json.dumps(
        {"login": {"username": data.username, "result": "成功"}}, ensure_ascii=False
    )
    token = create_access_token(user.id)
    return success({"access_token": token, "token_type": "bearer"})


@router.get("/userinfo")
def userinfo(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return success(
        {
            "id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "roles": get_user_roles(db, user),
            "permissions": get_user_permissions(db, user),
            # 用户级「明确禁用」的权限码：前端据此在 admin 短路之前先行拦截
            "denied_permissions": get_user_denied_permissions(db, user),
        }
    )


@router.post("/logout")
def logout():
    # 无状态 JWT，前端清除 token 即可
    return success(message="已退出登录")
