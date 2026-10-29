"""差旅与业务招待费报销智能体：接口层公共工具。

四个路由模块（bills / compliance / vouchers / policy）共用的内容都在这里：
- 权限判定：报销人、制单人、复核人「三分离」需要按业务动作动态判权，
  不能只靠路由级依赖一刀切，因此提供 has_perm / ensure_perm / can_view_all。
- 操作日志：operation_logs 只有 action 字段（没有 detail 列），
  业务动作与明细统一写进 action，用「｜」分隔，读取时再拆开，避免改动既有模型。
- 单号生成：报销单号 BX-YYYYMMDD-NNNN、凭证号 记-YYYYMM-NNNN 都在事务内取号，
  配合 begin_immediate() 的写锁保证并发下不重号。
- 文件归档：票据原件存 data/uploads/rmb/（相对路径入库），
  制度文件存 <项目根>/docs/policies/。
- 行转字典：把 ORM 对象转成前端需要的扁平结构（含人员/部门/费用类型名称）。
"""
import hashlib
import json
import logging
import os
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import BizException, PermissionException
from app.crud.crud_auth import (
    get_user_permission_overrides,
    get_user_permissions,
    get_user_roles,
)
from app.models.quality import OperationLog
from app.models.rbac import User
from app.models.reimburse import (
    RmbAccountSubject,
    RmbComplianceCheck,
    RmbComplianceIssue,
    RmbDepartment,
    RmbEmployee,
    RmbExpenseType,
    RmbInvoice,
    RmbPolicy,
    RmbReimbursement,
    RmbSettlementMethod,
    RmbSysParam,
    RmbVoucher,
)
from app.services import file_store

logger = logging.getLogger(__name__)

# ---------------- 状态常量（与 models/reimbursement 注释、前端标签保持一致） ----------------
STATUS_WAIT_CHECK = "待判读"
STATUS_CHECK_FAILED = "判读不合规"
STATUS_WAIT_CONFIRM = "待确认"
STATUS_WAIT_VOUCHER = "待制证"
STATUS_VOUCHER_DONE = "已生成凭证"
STATUS_VOID = "已作废"

#: 允许报销人修改的报销单状态
EDITABLE_STATUS = (STATUS_WAIT_CHECK, STATUS_CHECK_FAILED, STATUS_WAIT_CONFIRM)
#: 允许删除的报销单状态
DELETABLE_STATUS = (STATUS_WAIT_CHECK, STATUS_CHECK_FAILED)
#: 允许重新判读的状态
CHECKABLE_STATUS = (STATUS_WAIT_CHECK, STATUS_CHECK_FAILED, STATUS_WAIT_CONFIRM)

COMPLIANCE_UNTESTED = "未判读"
RESULT_COMPLIANT = "合规"
RESULT_CONCERN = "需关注"
RESULT_NONCOMPLIANT = "不合规"
RESULT_NA = "不适用"
RESULT_CHOICES = (RESULT_COMPLIANT, RESULT_CONCERN, RESULT_NONCOMPLIANT, RESULT_NA)

VOUCHER_UNREVIEWED = "未复核"
VOUCHER_REVIEWED = "已复核"
VOUCHER_RETURNED = "已退回"

APPROVER_LEVELS = ("部门负责人", "财务复核", "部门总监", "总经理")

# ---------------- 分级审批（制度第四条）----------------
#: 审批状态
APPROVAL_NONE = "未审批"
APPROVAL_PASSED = "已审批"
APPROVAL_REJECTED = "已驳回"
APPROVAL_STATUSES = (APPROVAL_NONE, APPROVAL_PASSED, APPROVAL_REJECTED)

#: 角色 → 审批层级。数字越大权限越高，采用「向上兼容」：
#: 总经理（3 级）可审批任意金额，部门负责人（1 级）不能越权批大额单据。
#: admin 视为 3 级，便于管理员代行审批与故障处理。
APPROVAL_RANK_BY_ROLE = {
    "dept_head": 1,          # 部门负责人：< 5,000 元
    "finance_review": 1,     # 财务复核：< 5,000 元
    "finance_approve": 1,    # 财务审批：财务岗的审批职能（制度第四条财务复核口径）
    "dept_director": 2,      # 部门总监：5,000 ～ 20,000 元
    "general_manager": 3,    # 总经理：≥ 20,000 元
    "admin": 3,
}

#: 审批层级的中文说明，用于错误提示
APPROVAL_RANK_LABELS = {1: "部门负责人 / 财务复核", 2: "部门总监", 3: "总经理"}

#: 审批角色 → 填单页「审批层级」的选项文案（与 APPROVER_LEVELS 对齐，供审批人下拉带出层级）
APPROVER_LEVEL_BY_ROLE = {
    "dept_head": "部门负责人",
    "finance_review": "财务复核",
    "finance_approve": "财务复核",
    "dept_director": "部门总监",
    "general_manager": "总经理",
}

#: 审批权限码：拥有该权限的用户才会出现在「审批人姓名」下拉里
APPROVE_PERM_CODE = "reimburse:bill:approve"

# ---------------- 数据范围（部门 × 职位）----------------
#: 权限码只解决「能不能做这个动作」，数据范围解决「能对哪些单据做」。
#: 制度第四条的分级审批是按部门层层上报的：部门负责人只对本部门单据负责，
#: 财务复核/总经理则对公司整体负责。
SCOPE_ALL = "all"      # 全公司
SCOPE_DEPT = "dept"    # 本部门
SCOPE_SELF = "self"    # 仅本人

#: 数据范围优先级：all > dept > self（一人多岗时取最高）
SCOPE_ORDER = {SCOPE_ALL: 3, SCOPE_DEPT: 2, SCOPE_SELF: 1}

#: 角色 → 数据范围
ROLE_DATA_SCOPE = {
    # 系统与财务职能岗：跨部门
    "admin": SCOPE_ALL,
    "manager": SCOPE_ALL,          # 运营主管（兼财务复核）：偏管理与复核口径
    "maker": SCOPE_ALL,            # 制单员：为全公司制证
    "reviewer": SCOPE_ALL,         # 复核员：复核全公司凭证
    "finance_review": SCOPE_ALL,   # 财务复核：财务是职能条线，不受部门边界限制
    "finance_approve": SCOPE_ALL,  # 财务审批：同上
    "general_manager": SCOPE_ALL,  # 总经理：全公司
    # 部门管理岗：只看本部门
    "dept_head": SCOPE_DEPT,       # 部门负责人：审批本部门单据
    "dept_director": SCOPE_DEPT,   # 部门总监：审批本部门单据
    # 业务岗：只看本人
    "staff": SCOPE_SELF,
    "buyer": SCOPE_SELF,
    "keeper": SCOPE_SELF,
    "qc": SCOPE_SELF,
}

#: 拥有其一即可查看/处理全部报销单的权限（制单、覆盖、复核、制度管理）；
#: 注意：真正的数据边界由 ROLE_DATA_SCOPE 决定，这些权限只是「有资格」，
#: 部门负责人虽持有 approve 权限，但数据范围仍是本部门。
WIDE_VIEW_PERMS = (
    "reimburse:voucher:make",
    "reimburse:check:override",
    "reimburse:voucher:review",
    "reimburse:policy:manage",
    "reimburse:bill:approve",
)

# ---------------- 文件归档 ----------------
#: 票据原件归档子目录（相对 settings.UPLOAD_DIR）
RMB_FILE_SUBDIR = "rmb"
#: 识别结果暂存子目录：uploads/rmb/tmp/{token}.json
RMB_TMP_SUBDIR = "rmb/tmp"

_TICKET_MIME = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "bmp": "image/bmp",
    "webp": "image/webp",
    "gif": "image/gif",
    "tif": "image/tiff",
    "tiff": "image/tiff",
}
_TICKET_EXTS = tuple(_TICKET_MIME)
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
# 单张票据归档上限。PDF 要留足空间（识别时 PDF 上限也是 20MB，两处保持一致，
# 否则会出现「能保存但识别必失败」的割裂），图片实际识别上限 8MB 见 invoice_ai。
_MAX_TICKET_BYTES = 20 * 1024 * 1024


# ==================== 一、通用小工具 ====================
def now() -> datetime:
    return datetime.now()


def today_str() -> str:
    """服务器当前日期（报销日期只取服务器日期，前端不可指定）。"""
    return date.today().isoformat()


def to_decimal(value: Any) -> Decimal:
    """任意输入转 Decimal 并四舍五入到分；金额一律走 Decimal 计算避免浮点误差。"""
    if value is None or value == "":
        return Decimal("0.00")
    try:
        return Decimal(str(value).strip()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise BizException("金额格式不正确，应为数字")


def parse_money(value: Any, label: str = "金额") -> Decimal:
    """校验必填金额：空值、非数字、负数都给出中文提示，返回两位小数的 Decimal。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise BizException(f"请填写{label}")
    try:
        amount = Decimal(str(value).strip().replace(",", "").replace("¥", "").replace("￥", ""))
    except (InvalidOperation, ValueError):
        raise BizException(f"{label}格式不正确，应为数字")
    if amount < 0:
        raise BizException(f"{label}不能为负数")
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def money_float(value: Any) -> float:
    return float(to_decimal(value))


def parse_day(value: Any, label: str) -> str:
    """校验必填日期并统一为 YYYY-MM-DD（兼容 YYYY/MM/DD 输入）。"""
    raw = str(value or "").strip()
    if not raw:
        raise BizException(f"请填写{label}")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    raise BizException(f"{label}格式不正确，应为 YYYY-MM-DD")


def parse_day_optional(value: Any, label: str) -> str:
    """可选日期：空值返回空串，非空则校验格式。"""
    raw = str(value or "").strip()
    if not raw:
        return ""
    return parse_day(raw, label)


def parse_int(value: Any, label: str, minimum: int = 0) -> int:
    """可选整数：空值返回 0；非法或小于下限时给出中文提示。"""
    if value is None or value == "":
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise BizException(f"{label}应为整数")
    if number < minimum:
        raise BizException(f"{label}不能小于 {minimum}")
    return number


def parse_float(value: Any, label: str, minimum: float | None = None) -> float | None:
    """可选浮点数：空值返回 None；非法或小于下限时给出中文提示。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        raise BizException(f"{label}应为数字")
    if minimum is not None and number < minimum:
        raise BizException(f"{label}不能小于 {minimum:g}")
    return number


def request_path(path: str) -> str:
    """操作日志里的资源路径（统一去掉末尾斜杠，便于按前缀检索）。"""
    return (path or "").rstrip("/") or "/"


def client_ip(request: Any) -> str:
    """取请求来源 IP（没有 Request 对象时返回空串）。"""
    try:
        return request.client.host if request is not None and request.client else ""
    except Exception:  # noqa: BLE001 - 取 IP 失败不应影响业务
        return ""


# ==================== 二、权限判定与职责分离 ====================
def has_perm(db: Session, user: User, perm_code: str) -> bool:
    """判定用户是否拥有某权限码。

    判定顺序与 require_permissions 保持一致：用户级「明确禁止」优先于一切
    （含 admin 全放行）→ admin 放行 → 权限码命中。
    """
    _grants, denies = get_user_permission_overrides(db, user)
    if perm_code in denies:
        return False
    if "admin" in get_user_roles(db, user):
        return True
    return perm_code in get_user_permissions(db, user)


def any_perm(db: Session, user: User, perm_codes) -> bool:
    return any(has_perm(db, user, code) for code in perm_codes)


def ensure_perm(db: Session, user: User, perm_code: str) -> None:
    """按业务动作二次校验权限（多动作端点内部使用），不满足时抛权限异常。"""
    _grants, denies = get_user_permission_overrides(db, user)
    if perm_code in denies:
        raise PermissionException("该权限已被单独禁用，请联系系统管理员")
    if "admin" in get_user_roles(db, user):
        return
    if perm_code not in get_user_permissions(db, user):
        raise PermissionException()


#: 作废专用权限码（系统权限名「报销单-作废」）
VOID_PERM_CODE = "reimburse:bill:delete"


def ensure_can_void(db: Session, user: User, bill: RmbReimbursement) -> None:
    """作废报销单的统一职责校验（报销单接口与判读处理接口共用）。

    规则：
    - 具备「报销单-作废」权限的人，可作废任意可见单据；
    - 其他报销人只能作废本人单据，且「已审批通过」的单据不允许报销人自行作废 ——
      审批通过后如需撤回，须由具备作废权限的管理人员操作，避免绕过审批结果；
    - 「已作废 / 已生成凭证」的状态拦截由调用方按业务另行处理。
    """
    if has_perm(db, user, VOID_PERM_CODE):
        return
    if not is_bill_owner(bill, user):
        raise PermissionException("只能作废本人的报销单")
    if (bill.approval_status or "") == APPROVAL_PASSED:
        raise PermissionException(
            "该报销单已审批通过，报销人不能自行作废，请联系具备作废权限的管理人员处理"
        )


# ---------------- 数据范围（部门 × 职位）----------------
def user_data_scope(db: Session, user: User) -> str:
    """取用户的数据范围（其所有角色中最高的一档）。

    权限码决定「能不能做」，数据范围决定「能对哪些单据做」：
    - all  全公司：财务职能岗、总经理、系统管理员、制单员、复核员
    - dept 本部门：部门负责人、部门总监
    - self 仅本人：普通报销人

    注意：部门管理岗若没有员工档案（无法判断所属部门），降级为 self ——
    宁可少看，不能越权看到其他部门的单据。
    """
    scopes = [ROLE_DATA_SCOPE.get(r.role_code, SCOPE_SELF) for r in (user.roles or [])]
    if not scopes:
        return SCOPE_SELF
    best = max(scopes, key=lambda s: SCOPE_ORDER.get(s, 0))
    if best == SCOPE_DEPT and not user_department_id(db, user):
        return SCOPE_SELF
    return best


def user_department_id(db: Session, user: User) -> int | None:
    """当前用户所属部门（来自员工档案）；系统账号没有员工档案时返回 None。"""
    employee_id = getattr(user, "employee_id", None)
    if not employee_id:
        return None
    emp = db.get(RmbEmployee, employee_id)
    return emp.department_id if emp else None


def bill_department_id(db: Session, bill: RmbReimbursement) -> int | None:
    """报销单所属部门：优先取单据上的 department_id，缺失时回退到报销人的部门。"""
    if bill.department_id:
        return bill.department_id
    if bill.employee_id:
        emp = db.get(RmbEmployee, bill.employee_id)
        if emp:
            return emp.department_id
    return None


def bill_in_scope(db: Session, user: User, bill: RmbReimbursement) -> bool:
    """这张报销单是否落在当前用户的数据范围内。

    - all  ：全部可见
    - dept ：本部门单据 + 本人经手的单据（代填场景）
    - self ：仅本人单据
    """
    scope = user_data_scope(db, user)
    if scope == SCOPE_ALL:
        return True
    if is_bill_owner(bill, user):
        return True
    if scope == SCOPE_DEPT:
        my_dept = user_department_id(db, user)
        if not my_dept:
            return False
        return bill_department_id(db, bill) == my_dept
    return False


def can_view_all(db: Session, user: User) -> bool:
    """是否可查看/处理全公司报销单（数据范围为 all 的用户）。"""
    return user_data_scope(db, user) == SCOPE_ALL


# ---------------- 分级审批辅助 ----------------
def user_approval_rank(db: Session, user: User) -> int:
    """取当前用户的审批层级（其所有角色中最高的那一级）；无审批类角色返回 0。"""
    ranks = []
    for role in user.roles or []:
        rank = APPROVAL_RANK_BY_ROLE.get(role.role_code)
        if rank:
            ranks.append(rank)
    return max(ranks) if ranks else 0


def approver_options(db: Session) -> list[dict]:
    """填单页「审批人姓名」下拉数据：拥有审批权限的启用用户及其审批层级。

    口径：
    - 只取角色权限包含 `reimburse:bill:approve` 的启用用户；
    - 一人多角色时取其级别最高的角色对应的审批层级；
    - 按审批层级从低到高、再按姓名排序，前端展示为「姓名（审批层级）」。
    """
    from app.models.rbac import Permission, Role, RolePermission, UserRole

    perm_role_codes = {
        code for (code,) in (
            db.query(Role.role_code)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .filter(Permission.perm_code == APPROVE_PERM_CODE)
            .all()
        )
    }
    if not perm_role_codes:
        return []
    rows = (
        db.query(User, Role.role_code, Role.role_name)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .filter(User.status.is_(True), Role.role_code.in_(perm_role_codes))
        .all()
    )
    best: dict[int, dict] = {}
    for user, role_code, role_name in rows:
        level = APPROVER_LEVEL_BY_ROLE.get(role_code)
        if not level:
            continue
        rank = APPROVAL_RANK_BY_ROLE.get(role_code, 0)
        current = best.get(user.id)
        if current is not None and rank <= current["rank"]:
            continue
        best[user.id] = {
            "name": user.real_name or user.username,
            "level": level,
            "role_name": role_name,
            "rank": rank,
        }
    return sorted(best.values(), key=lambda item: (item["rank"], item["name"]))


def required_approval_rank(amount, params: dict | None = None) -> int:
    """按单笔金额计算所需审批层级（制度第四条）。

    < 5,000 元 → 1 级（部门负责人 / 财务复核）
    5,000（含）～ 20,000 元 → 2 级（部门总监）
    ≥ 20,000 元 → 3 级（总经理）
    """
    from decimal import Decimal, InvalidOperation

    try:
        value = Decimal(str(amount or 0))
    except (InvalidOperation, TypeError, ValueError):
        value = Decimal("0")

    p = params or {}
    try:
        level2 = Decimal(str(p.get("approval_level2_amount") or 5000))
    except (InvalidOperation, TypeError, ValueError):
        level2 = Decimal("5000")
    try:
        level3 = Decimal(str(p.get("approval_level3_amount") or 20000))
    except (InvalidOperation, TypeError, ValueError):
        level3 = Decimal("20000")

    if value >= level3:
        return 3
    if value >= level2:
        return 2
    return 1


def can_approve(db: Session, user: User, bill: RmbReimbursement) -> bool:
    """当前用户是否有权审批该报销单。

    需同时满足三个条件：
    1. 具备 `reimburse:bill:approve` 权限码（「能不能审批」）；
    2. 单据在用户数据范围内（「能审哪些」——部门负责人只能审本部门）；
    3. 审批层级 ≥ 单据所需层级（「能审多大金额」），且不是报销人本人。
    """
    if not has_perm(db, user, "reimburse:bill:approve"):
        return False
    if is_bill_owner(bill, user):
        return False
    if not bill_in_scope(db, user, bill):
        return False
    return user_approval_rank(db, user) >= required_approval_rank(bill.amount, sys_params(db))


def can_choose_employee(db: Session, user: User) -> bool:
    """是否可以替他人填报（制单员、管理员），否则只能为本人报销。"""
    return has_perm(db, user, "reimburse:voucher:make")


def is_bill_owner(bill: RmbReimbursement, user: User) -> bool:
    """当前登录人是否是这张报销单的报销人本人。

    users 表通过 employee_id 关联 rmb_employee；同时也比对 created_by，
    避免「管理员代填」时漏判（代填人不是报销人）。
    """
    if bill.created_by and bill.created_by == user.username:
        return True
    employee_id = getattr(user, "employee_id", None)
    return bool(employee_id) and bill.employee_id == employee_id


def is_bill_employee(bill: RmbReimbursement, user: User) -> bool:
    """当前登录人的员工档案是否是这张报销单的报销人。

    与 is_bill_owner 的区别：只看员工档案，不看 created_by。
    用于制单、复核、人工覆盖的职责分离判定 —— 代填人可以替他人填单，
    但他若是本单报销人，仍然不能给自己制证/复核。
    """
    employee_id = getattr(user, "employee_id", None)
    return bool(employee_id) and bill.employee_id == employee_id


def ensure_bill_visible(db: Session, user: User, bill: RmbReimbursement) -> None:
    """报销单查看权限：在数据范围内才可见（all 全公司 / dept 本部门 / self 本人）。"""
    if bill_in_scope(db, user, bill):
        return
    scope = user_data_scope(db, user)
    if scope == SCOPE_DEPT:
        raise PermissionException("只能查看本部门的报销单")
    raise PermissionException("只能查看本人的报销单")


def ensure_not_bill_owner(bill: RmbReimbursement, user: User, action_label: str) -> None:
    """职责分离：人工覆盖、制单、复核的操作人不能是报销人本人。"""
    if is_bill_employee(bill, user):
        raise BizException(f"{action_label}不能是报销人本人（职责分离要求）")


def my_employee(db: Session, user: User) -> RmbEmployee | None:
    employee_id = getattr(user, "employee_id", None)
    if not employee_id:
        return None
    return db.get(RmbEmployee, employee_id)


# ==================== 三、操作日志 ====================
def write_log(
    db: Session,
    user: User | str,
    action: str,
    path: str,
    detail: str = "",
    method: str = "POST",
    request: Any = None,
) -> None:
    """写业务操作日志。

    约定：
    - 必须在业务事务 commit 之后再调用，避免日志把未提交的业务改动一起提交；
    - 明细写入 operation_logs.detail（该列已随报销模块新增），不再受 action 的 64 字符限制，
      AI 模型名、耗时、结论、不一致项数、修改前后值等都能完整留痕；
      为兼容历史数据，读取时仍会解析 action 里的「动作｜明细」旧格式；
    - 日志写失败只告警，不影响已经成功的业务操作。
    """
    username = user if isinstance(user, str) else (user.username or "")
    try:
        db.add(OperationLog(username=username, method=method, path=path[:255],
                            action=(action or "")[:64], detail=detail or "",
                            ip=client_ip(request)))
        db.commit()
    except Exception:  # noqa: BLE001 - 日志失败不阻断业务
        logger.warning("报销模块操作日志写入失败：%s %s", action, path, exc_info=True)
        db.rollback()


def read_logs(db: Session, paths: list[str], limit: int = 80) -> list[dict]:
    """按资源路径前缀取审计轨迹，按时间正序返回。

    用前缀匹配而不是精确匹配，是为了同时命中三种来源的日志：
    - 本模块写的业务日志：/api/v1/rmb-bills/{id}（明细以「动作｜明细」写在 action 里）；
    - main.py 中间件自动记录的写请求：/api/v1/rmb-bills/{id}/void、/rmb-vouchers/review/{id} 等；
    - 服务层自己写的模型调用日志：/rmb/reimbursement/{id}?model=...&elapsed=...，
      它把结构化明细以查询串形式挂在 path 上（模型层没有 detail 列），这里还原成可读明细。
    """
    if not paths:
        return []
    conds = [
        or_(
            OperationLog.path == prefix,
            OperationLog.path.startswith(prefix + "/", autoescape=True),
            OperationLog.path.startswith(prefix + "?", autoescape=True),
        )
        for prefix in paths if prefix
    ]
    if not conds:
        return []
    rows = (
        db.query(OperationLog)
        .filter(or_(*conds))
        .order_by(OperationLog.id.desc())
        .limit(limit)
        .all()
    )
    result = []
    for row in reversed(rows):
        path = row.path or ""
        action_text = row.action or ""
        if "?" in path:
            # 服务层：动作就是 action，明细是查询串里的键值对
            detail = path.split("?", 1)[1].replace("&", "；")
        elif getattr(row, "detail", ""):
            # 新格式：明细直接存在 detail 列，action 是纯动作名
            detail = row.detail
        else:
            # 历史数据：明细以「动作｜明细」写在 action 里
            action_text, _, detail = action_text.partition("｜")
        result.append({
            "id": row.id,
            "created_at": str(row.created_at)[:19],
            "username": row.username,
            "method": row.method,
            "action": action_text,
            "detail": detail,
        })
    return result


def bill_log_path(bill_id: int) -> str:
    return f"/api/v1/rmb-bills/{bill_id}"


def voucher_log_path(voucher_id: int) -> str:
    return f"/api/v1/rmb-vouchers/{voucher_id}"


def service_log_path(target: str, target_id: int) -> str:
    """AI 服务层写入的模型调用日志前缀（如 /rmb/reimbursement/12?model=...）。

    服务层不允许改模型，因此它把「模型/耗时/结论」等明细以查询串挂在 path 上；
    这里统一登记前缀，读取时还原为可读明细，报销单与凭证的审计轨迹才能串起完整链路。
    """
    return f"/rmb/{target}/{target_id}"


def bill_logs(db: Session, bill_id: int, limit: int = 80) -> list[dict]:
    """报销单审计轨迹：报销单本身 + 其凭证 + AI 模型调用（同一张单的完整链路）。"""
    paths = [bill_log_path(bill_id), service_log_path("reimbursement", bill_id)]
    vouchers = db.query(RmbVoucher.id).filter(RmbVoucher.reimbursement_id == bill_id).all()
    paths.extend(voucher_log_path(vid) for (vid,) in vouchers)
    return read_logs(db, paths, limit)


def voucher_logs(db: Session, voucher: RmbVoucher, limit: int = 80) -> list[dict]:
    """凭证审计轨迹：凭证本身 + 关联报销单及其 AI 模型调用的业务日志。"""
    paths = [voucher_log_path(voucher.id)]
    if voucher.reimbursement_id:
        paths.append(bill_log_path(voucher.reimbursement_id))
        paths.append(service_log_path("reimbursement", voucher.reimbursement_id))
    return read_logs(db, paths, limit)


# ==================== 四、单号生成（事务内取号） ====================
def begin_immediate(db: Session) -> None:
    """在 SQLite 上以 BEGIN IMMEDIATE 开启写事务，先拿到写锁再取号。

    先 db.rollback() 结束之前校验查询产生的隐式读事务，否则会报
    「cannot start a transaction within a transaction」。
    非 SQLite 数据库（如以后的 MySQL）退化为普通事务。
    """
    db.rollback()
    if str(settings.DATABASE_URL).startswith("sqlite"):
        db.execute(text("BEGIN IMMEDIATE"))


def next_bill_no(db: Session, day: str) -> str:
    """生成报销单号 BX-YYYYMMDD-NNNN（当日流水，需在 begin_immediate 之后调用）。"""
    prefix = f"BX-{day.replace('-', '')}-"
    rows = db.query(RmbReimbursement.bill_no).filter(RmbReimbursement.bill_no.like(f"{prefix}%")).all()
    seq = 0
    for (bill_no,) in rows:
        tail = (bill_no or "").rsplit("-", 1)[-1]
        if tail.isdigit():
            seq = max(seq, int(tail))
    return f"{prefix}{seq + 1:04d}"


def next_voucher_no(db: Session, period: str, word: str) -> int:
    """生成凭证流水号（该期间+凭证字内的最大号 +1），需在begin_immediate 之后调用。"""
    rows = (
        db.query(RmbVoucher.voucher_no)
        .filter(RmbVoucher.period == period, RmbVoucher.voucher_word == word)
        .all()
    )
    return max((no or 0 for (no,) in rows), default=0) + 1


def voucher_code_of(word: str, period: str, voucher_no: int) -> str:
    """凭证字号：记-202610-0001（期间 YYYY-MM → 去掉连字符）。"""
    return f"{word}-{period.replace('-', '')}-{voucher_no:04d}"


# ==================== 五、票据文件归档 ====================
def normalize_ticket_ext(filename: str, content_type: str = "") -> str:
    """从文件名 / MIME 推断票据扩展名，只允许 pdf 与常见图片。"""
    name = (filename or "").strip()
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in _TICKET_EXTS:
        return ext
    mime = (content_type or "").split(";")[0].strip().lower()
    for key, value in _TICKET_MIME.items():
        if mime == value:
            return key
    raise BizException("仅支持上传 pdf、jpg、jpeg、png 格式的票据文件")


def safe_filename(filename: str) -> str:
    """去掉路径部分与非法字符，只保留可读的文件名用于展示/归档命名。"""
    name = os.path.basename((filename or "").replace("\\", "/")).strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name[:120] or "未命名文件"


def save_ticket(data: bytes, filename: str, content_type: str = "") -> tuple[str, str, str]:
    """把票据原件归档到 data/uploads/rmb/。

    返回 `(relative_path, sha256, ext)`。相对路径入库（相对 settings.UPLOAD_DIR），
    换机器/换目录后仍然有效；文件名不使用用户原始文件名，避免路径穿越与同名覆盖。
    与识别服务的「写失败返回空路径」不同，报销单必须留存票据原件，这里写失败直接报错。
    """
    if not data:
        raise BizException("上传的票据文件为空，请重新上传")
    if len(data) > _MAX_TICKET_BYTES:
        raise BizException(f"票据文件不能超过 {_MAX_TICKET_BYTES // (1024 * 1024)}MB，请压缩后再上传")
    ext = normalize_ticket_ext(filename, content_type)
    digest = hashlib.sha256(data).hexdigest()
    stamp = now().strftime("%Y%m%d_%H%M%S")
    rel = f"{RMB_FILE_SUBDIR}/{stamp}_{uuid.uuid4().hex[:8]}.{ext}"
    full = os.path.join(file_store.upload_root(), rel.replace("/", os.sep))
    try:
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fp:
            fp.write(data)
    except OSError as exc:
        logger.warning("票据文件归档失败：%s", exc, exc_info=True)
        raise BizException("票据文件保存失败，请重试或联系管理员")
    return rel, digest, ext


def ticket_media_type(rel_path: str) -> str:
    ext = (rel_path or "").rsplit(".", 1)[-1].lower()
    return _TICKET_MIME.get(ext, "application/octet-stream")


def remove_ticket(rel_path: str) -> None:
    """删除归档的票据文件（报销单被删除时调用），文件不存在视为成功。"""
    full = file_store.resolve(rel_path)
    if not full:
        return
    try:
        os.remove(full)
    except OSError:
        pass


# ---------------- 识别结果暂存（token） ----------------
def save_recognized(token_payload: dict) -> str:
    """把识别结果与文件信息暂存为 uploads/rmb/tmp/{token}.json，返回 token。

    前端在保存阶段把 token 回传即可，服务端据此取回「可信的文件路径/哈希」，
    不接受前端自行提交的磁盘路径，避免路径穿越。
    """
    token = uuid.uuid4().hex
    directory = os.path.join(file_store.upload_root(), RMB_TMP_SUBDIR.replace("/", os.sep))
    os.makedirs(directory, exist_ok=True)
    payload = dict(token_payload)
    payload["created_at"] = now().isoformat(timespec="seconds")
    with open(os.path.join(directory, f"{token}.json"), "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False)
    return token


def _tmp_full_path(token: str) -> str:
    token = (token or "").strip()
    if not _TOKEN_RE.match(token):
        raise BizException("票据识别数据已失效，请重新上传票据")
    directory = os.path.join(file_store.upload_root(), RMB_TMP_SUBDIR.replace("/", os.sep))
    return os.path.join(directory, f"{token}.json")


def load_recognized(token: str) -> dict:
    """读取识别暂存数据；token 非法或文件已清理时给出中文提示。"""
    path = _tmp_full_path(token)
    if not os.path.isfile(path):
        raise BizException("票据识别数据已失效，请重新上传票据")
    try:
        with open(path, encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, json.JSONDecodeError):
        raise BizException("票据识别数据已损坏，请重新上传票据")


def remove_recognized(token: str) -> None:
    try:
        path = _tmp_full_path(token)
    except BizException:
        return
    try:
        os.remove(path)
    except OSError:
        pass


# ==================== 六、行转字典 ====================
def load_bill_maps(db: Session) -> dict:
    """一次性载入报销单展示需要的人员/部门/费用类型/结算方式映射，避免逐行查库。"""
    return {
        "employees": {e.id: e for e in db.query(RmbEmployee).all()},
        "departments": {d.id: d.name for d in db.query(RmbDepartment).all()},
        "expense_types": {t.id: t for t in db.query(RmbExpenseType).all()},
        "settlements": {s.id: s for s in db.query(RmbSettlementMethod).all()},
    }


def bill_row(bill: RmbReimbursement, maps: dict) -> dict:
    """报销单列表行（不含票据/判读详情）。"""
    employee = maps["employees"].get(bill.employee_id)
    expense_type = maps["expense_types"].get(bill.expense_type_id)
    settlement = maps["settlements"].get(bill.settlement_method_id)
    department_name = maps["departments"].get(bill.department_id, "")
    if not department_name and employee is not None:
        department_name = maps["departments"].get(employee.department_id, "")
    return {
        "id": bill.id,
        "bill_no": bill.bill_no,
        "bill_date": bill.bill_date,
        "employee_id": bill.employee_id,
        "employee_name": employee.name if employee else "",
        "emp_no": employee.emp_no if employee else "",
        "department_id": bill.department_id or (employee.department_id if employee else None),
        "department_name": department_name,
        "expense_type_id": bill.expense_type_id,
        "expense_type_name": expense_type.name if expense_type else "",
        "special_info": expense_type.special_info if expense_type else "无",
        "reason": bill.reason or "",
        "occur_date": bill.occur_date,
        "amount": bill.amount or 0,
        "has_invoice": bill.has_invoice or 0,
        "approver_name": bill.approver_name or "",
        "approver_level": bill.approver_level or "",
        "travel_city": bill.travel_city or "",
        "travel_start": bill.travel_start or "",
        "travel_end": bill.travel_end or "",
        "nights": bill.nights or 0,
        "guest_company": bill.guest_company or "",
        "guest_count": bill.guest_count or 0,
        "special_approver": bill.special_approver or "",
        "explanation": bill.explanation or "",
        "settlement_method_id": bill.settlement_method_id,
        "settlement_method_name": settlement.name if settlement else "",
        "status": bill.status or "",
        "compliance_result": bill.compliance_result or "",
        # 分级审批（制度第四条）
        "approval_status": bill.approval_status or APPROVAL_NONE,
        "approval_by": bill.approval_by or "",
        "approval_at": str(bill.approval_at)[:19] if bill.approval_at else "",
        "approval_comment": bill.approval_comment or "",
        "approval_rank": bill.approval_rank,
        "override_flag": bill.override_flag or 0,
        "override_reason": bill.override_reason or "",
        "override_by": bill.override_by or "",
        "override_at": str(bill.override_at)[:19] if bill.override_at else "",
        "created_by": bill.created_by or "",
        "created_at": str(bill.created_at)[:19] if bill.created_at else "",
        "updated_at": str(bill.updated_at)[:19] if bill.updated_at else "",
    }


def invoice_row(invoice: RmbInvoice | None, with_raw: bool = False) -> dict | None:
    """票据信息（items_json → items 数组，附原件是否留存标记）。"""
    if invoice is None:
        return None
    try:
        items = json.loads(invoice.items_json or "[]")
    except (TypeError, json.JSONDecodeError):
        items = []
    data = {
        "id": invoice.id,
        "reimbursement_id": invoice.reimbursement_id,
        "document_type": invoice.document_type or "",
        "is_invoice": invoice.is_invoice if invoice.is_invoice is not None else 1,
        "invoice_code": invoice.invoice_code or "",
        "invoice_number": invoice.invoice_number or "",
        "issue_date": invoice.issue_date or "",
        "buyer_name": invoice.buyer_name or "",
        "buyer_tax_id": invoice.buyer_tax_id or "",
        "seller_name": invoice.seller_name or "",
        "seller_tax_id": invoice.seller_tax_id or "",
        "amount_without_tax": invoice.amount_without_tax or 0,
        "tax_rate": invoice.tax_rate or "",
        "tax_amount": invoice.tax_amount or 0,
        "total_amount": invoice.total_amount or 0,
        "total_amount_cn": invoice.total_amount_cn or "",
        "items": items if isinstance(items, list) else [],
        "passenger_name": invoice.passenger_name or "",
        "travel_from": invoice.travel_from or "",
        "travel_to": invoice.travel_to or "",
        "travel_date": invoice.travel_date or "",
        "checkin_date": invoice.checkin_date or "",
        "checkout_date": invoice.checkout_date or "",
        "nights": invoice.nights or 0,
        "consume_city": invoice.consume_city or "",
        "original_filename": invoice.original_filename or "",
        "file_hash": invoice.file_hash or "",
        "has_file": file_store.exists(invoice.file_path),
        "llm_model": invoice.llm_model or "",
        "created_by": invoice.created_by or "",
        "created_at": str(invoice.created_at)[:19] if invoice.created_at else "",
    }
    if with_raw:
        data["llm_raw_json"] = invoice.llm_raw_json or ""
    return data


def latest_check(db: Session, reimbursement_id: int) -> RmbComplianceCheck | None:
    """取某张报销单最近一次判读记录（按 id 倒序）。"""
    return (
        db.query(RmbComplianceCheck)
        .filter(RmbComplianceCheck.reimbursement_id == reimbursement_id)
        .order_by(RmbComplianceCheck.id.desc())
        .first()
    )


def check_brief(check: RmbComplianceCheck | None) -> dict | None:
    if check is None:
        return None
    return {
        "id": check.id,
        "reimbursement_id": check.reimbursement_id,
        "check_no": check.check_no,
        "policy_id": check.policy_id,
        "model": check.model or "",
        "overall_result": check.overall_result or "",
        "ai_overall_result": check.ai_overall_result or "",
        "summary": check.summary or "",
        "inconsistency_count": check.inconsistency_count or 0,
        "elapsed": check.elapsed or 0,
        "checked_by": check.checked_by or "",
        "checked_at": str(check.checked_at)[:19] if check.checked_at else "",
        "handle_action": check.handle_action or "",
        "handle_comment": check.handle_comment or "",
        "handled_by": check.handled_by or "",
        "handled_at": str(check.handled_at)[:19] if check.handled_at else "",
    }


def parse_json_dict(raw: str) -> dict:
    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def check_full(db: Session, check: RmbComplianceCheck) -> dict:
    """判读详情：含 14 条规则的明细、程序事实与 AI 原始输出。"""
    issues = (
        db.query(RmbComplianceIssue)
        .filter(RmbComplianceIssue.check_id == check.id)
        .order_by(RmbComplianceIssue.sort_no, RmbComplianceIssue.id)
        .all()
    )
    data = check_brief(check) or {}
    data["facts"] = parse_json_dict(check.facts_json)
    data["program_flags"] = parse_json_dict(check.program_flags_json)
    data["ai_raw_text"] = check.ai_raw_text or ""
    data["issues"] = [
        {
            "id": item.id,
            "rule_code": item.rule_code or "",
            "check_item": item.check_item or "",
            "clause_no": item.clause_no or "",
            "result": item.result or "",
            "reason": item.reason or "",
            "suggestion": item.suggestion or "",
            "evidence": item.evidence or "",
            "program_triggered": item.program_triggered,
            "consistency": item.consistency or "未校验",
            "sort_no": item.sort_no or 0,
        }
        for item in issues
    ]
    return data


def active_policy(db: Session) -> RmbPolicy | None:
    """当前生效制度（正常只有一条 is_active=1）。"""
    return (
        db.query(RmbPolicy)
        .filter(RmbPolicy.is_active == True)  # noqa: E712 - SQLAlchemy 列比较
        .order_by(RmbPolicy.id.desc())
        .first()
    )


def sys_params(db: Session) -> dict:
    """系统参数 {key: value}。"""
    return {row.param_key: row.param_value or "" for row in db.query(RmbSysParam).all()}


def default_voucher_word(db: Session) -> str:
    value = (sys_params(db).get("default_voucher_word") or "").strip()
    return value or "记"


def account_subject_map(db: Session) -> dict[str, RmbAccountSubject]:
    return {row.code: row for row in db.query(RmbAccountSubject).all()}


def visible_bill_query(db: Session, user: User, query):
    """给报销单查询加上数据范围限制。

    - all  ：不加条件（全公司）
    - dept ：本部门单据 ∪ 本人经手的单据
    - self ：本人经手的单据
    """
    scope = user_data_scope(db, user)
    if scope == SCOPE_ALL:
        return query

    conds = [RmbReimbursement.created_by == user.username]
    employee_id = getattr(user, "employee_id", None)
    if employee_id:
        conds.append(RmbReimbursement.employee_id == employee_id)

    if scope == SCOPE_DEPT:
        my_dept = user_department_id(db, user)
        if my_dept:
            # 本部门所有员工（用于匹配单据上的 employee_id）
            dept_emp_ids = db.query(RmbEmployee.id).filter(
                RmbEmployee.department_id == my_dept
            )
            conds.append(RmbReimbursement.department_id == my_dept)
            conds.append(RmbReimbursement.employee_id.in_(dept_emp_ids))

    return query.filter(or_(*conds))


def is_truthy(value: Any) -> bool:
    """前端 FormData / JSON 传来的布尔值可能是 'true'/'1'/'是' 等，统一判定。"""
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("1", "true", "yes", "y", "on", "是")
