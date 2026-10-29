"""数据视野（visibility）：按「部门 × 职位」决定一个账号能看到多少业务数据。

## 为什么需要

系统原有 5 个业务账号各司其职，视野天然清晰。报销模块新增的 7 个角色原本与业务
数据完全隔离，被并入基础账号体系后又统一拿到了**同一套**只读业务权限——
结果「销售部普通员工」与「总经理」看到的是完全相同的全公司采购金额、库存和操作日志，
这既不符合最小权限，也让演示中的角色差异消失。

本模块把视野拆成两个正交的维度：

1. **模块可见性（按职位）**：这个岗位需不需要看这类数据。
   普通员工不该看采购单据与库存流水；部门管理层要看本部门业务；财务与总经办需要全局。

2. **数据范围（按部门）**：同一个模块里能看到哪些行。
   总经理 / 财务 = 全公司；部门负责人 / 总监 = 本部门；普通员工 = 仅本人。

## 数据模型的现实约束

只有 `purchase_requisitions` 带 `dept` 字段。采购订单、到货、退货、库存流水、
质检、外发等表**没有部门归属列**，`purchase_orders.pr_id` 也全为 NULL，
无法经请购单反推。因此：

- 能按部门过滤的（请购单）→ 真正做行级过滤；
- 不能的（订单 / 到货 / 库存 …）→ 只能按职位决定「整块功能是否可见」，
  可见即全公司，不可见则菜单与接口都不开放。这是当前 schema 下能做到的最细粒度。

## 视野分级

| 角色 | 部门（演示数据） | 职位 | 视野 | 可见模块 |
| --- | --- | --- | --- | --- |
| general_manager | 总经办 | 总经理 | 全公司 | 15 项完整只读 |
| finance_approve / maker / reviewer | 财务部 | 财务审批 / 制单 / 复核 | 全公司（职能条线） | 15 项完整只读 |
| dept_head / dept_director | 销售部 | 部门负责人 / 总监 | 本部门 | 基础主数据 + 本部门请购 |
| staff | 各部门 | 普通员工 | 仅本人 | 基础主数据（填单够用） |
"""
from sqlalchemy.orm import Session

from app.models.rbac import User
from app.models.procurement import PurchaseRequisition
from app.models.reimburse import RmbDepartment, RmbEmployee

# ---------------- 数据范围 ----------------
SCOPE_ALL = "all"     # 全公司
SCOPE_DEPT = "dept"   # 本部门
SCOPE_SELF = "self"   # 仅本人

SCOPE_ORDER = {SCOPE_ALL: 3, SCOPE_DEPT: 2, SCOPE_SELF: 1}

#: 角色 → 数据范围。一人多岗时取最宽的那个。
ROLE_SCOPE = {
    "admin": SCOPE_ALL,
    "manager": SCOPE_ALL,
    "buyer": SCOPE_ALL,          # 采购员对接全公司请购，按业务需要看全部
    "keeper": SCOPE_ALL,         # 仓管员管所有仓库
    "qc": SCOPE_ALL,             # 质检员检验全公司来料与成品
    "general_manager": SCOPE_ALL,
    "finance_approve": SCOPE_ALL,
    "maker": SCOPE_ALL,
    "reviewer": SCOPE_ALL,
    "finance_review": SCOPE_ALL,
    "dept_head": SCOPE_DEPT,
    "dept_director": SCOPE_DEPT,
    "staff": SCOPE_SELF,
}

# ---------------- 模块可见性（只读业务权限） ----------------
#: 全公司视野：完整只读（含 AI 识别记录等全局信息）
#: 不含 `system:log`：操作日志记录的是所有账号的行为，只授予系统管理员
PERMS_ALL = [
    "basic:material:list", "basic:supplier:list", "basic:warehouse:list",
    "inventory:view", "inventory:alert",
    "purchase:requisition:list", "purchase:order:list",
    "purchase:arrival:list", "purchase:return:list",
    "bom:view", "qc:view", "outsource:list",
    "report:view", "ai:ocr:list",
]

#: 本部门视野：只保留「能真正按部门过滤」的模块。
#: 库存 / 采购订单 / 到货 / 退货 / 质检 / 外发等表**没有部门归属列**，
#: 无法按部门切分，给部门管理岗看就等于放行全公司数据，故一律不开。
#: 基础主数据（物料/供应商/仓库）是全公司共用的字典，只读无妨；
#: 业务单据只留请购单 —— 它是唯一带 dept 字段、可以按本部门过滤的。
PERMS_DEPT = [
    "basic:material:list", "basic:supplier:list", "basic:warehouse:list",
    "purchase:requisition:list",
]

#: 仅本人视野：只保留填单要用的基础主数据，业务单据与全局统计一概不开
PERMS_SELF = [
    "basic:material:list", "basic:supplier:list", "basic:warehouse:list",
]

#: 数据范围 → 应具备的只读业务权限
SCOPE_PERMS = {SCOPE_ALL: PERMS_ALL, SCOPE_DEPT: PERMS_DEPT, SCOPE_SELF: PERMS_SELF}

#: 本模块管辖的权限码全集（用于增量授权/回收，避免碰到报销与写权限）
MANAGED_PERMS = sorted(set(PERMS_ALL) | set(PERMS_DEPT) | set(PERMS_SELF))


# ---------------- 查询辅助 ----------------
def user_scope(db: Session, user: User) -> str:
    """当前用户的数据范围：取所有角色里最宽的一个；无角色时按仅本人。"""
    best = SCOPE_SELF
    for role in (user.roles or []):
        scope = ROLE_SCOPE.get(role.role_code)
        if scope and SCOPE_ORDER[scope] > SCOPE_ORDER[best]:
            best = scope
    return best


def user_department(db: Session, user: User) -> RmbDepartment | None:
    """当前用户的部门（经员工档案）；系统账号没有档案时返回 None。"""
    employee_id = getattr(user, "employee_id", None)
    if not employee_id:
        return None
    emp = db.get(RmbEmployee, employee_id)
    if not emp or not emp.department_id:
        return None
    return db.get(RmbDepartment, emp.department_id)


def user_department_name(db: Session, user: User) -> str | None:
    dept = user_department(db, user)
    return dept.name if dept else None


def should_scope_requisitions(db: Session, user: User) -> str | None:
    """请购单是否需要按范围过滤：返回 None 表示可看全部。

    注意：业务岗位（采购 / 仓储 / 质检 / 管理员 / 运营主管）本就以全公司为工作范围，
    不受此限制；只有「部门管理岗」与「普通员工」需要按部门 / 本人收敛。
    """
    scope = user_scope(db, user)
    if scope == SCOPE_ALL:
        return None
    return scope


def scope_requisitions(db: Session, user: User, query):
    """给请购单查询套上数据范围过滤，返回新的 query。

    - 全公司：原样返回（采购 / 仓储 / 质检 / 管理岗的工作范围就是全公司）；
    - 本部门：`dept` 等于本人部门名；
    - 仅本人：`requisitioner` 等于本人姓名。

    找不到部门归属时收敛为「空集」而不是放行——宁可不显示，也不能越权看到别人的单据。
    """
    scope = should_scope_requisitions(db, user)
    if scope is None:
        return query
    if scope == SCOPE_DEPT:
        name = user_department_name(db, user)
        if not name:
            return query.filter(False)
        return query.filter(PurchaseRequisition.dept == name)
    # SCOPE_SELF
    real_name = getattr(user, "real_name", "") or ""
    if not real_name:
        return query.filter(False)
    return query.filter(PurchaseRequisition.requisitioner == real_name)


def requisition_meta(db: Session, user: User) -> dict:
    """给前端展示「你当前能看到哪些范围的请购单」，便于解释为什么看不到某些单据。"""
    scope = should_scope_requisitions(db, user)
    if scope is None:
        return {"scope": SCOPE_ALL, "label": "全公司", "dept": None}
    if scope == SCOPE_DEPT:
        name = user_department_name(db, user)
        return {"scope": SCOPE_DEPT, "label": f"本部门（{name or '未归属'}）", "dept": name}
    return {"scope": SCOPE_SELF, "label": "仅本人", "dept": None}

