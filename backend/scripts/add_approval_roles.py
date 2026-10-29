"""按《差旅与业务招待费报销管理制度》第四条创建分级审批角色（幂等）。

运行：进入 backend 目录后执行
    .venv/Scripts/python.exe scripts/add_approval_roles.py

## 制度依据（第四条）

| 单笔报销金额 | 审批权限 |
| --- | --- |
| 低于 5,000 元 | 部门负责人 / 财务复核 即可 |
| 5,000 元（含）至 20,000 元 | 须经部门总监审批 |
| 20,000 元（含）以上 | 须经总经理审批 |

因此设 4 个审批角色，与报销单上的「审批层级」一一对应：

| 角色编码 | 角色名称 | 审批层级 | 可审批金额上限 |
| --- | --- | --- | --- |
| dept_head | 部门负责人 | 1 级 | < 5,000 元 |
| finance_review | 财务复核 | 1 级 | < 5,000 元（财务口径复核） |
| dept_director | 部门总监 | 2 级 | < 20,000 元 |
| general_manager | 总经理 | 3 级 | 不限（含 2 万元以上） |

审批权限采用「向上兼容」：层级高的人可审批层级低的单据（总经理当然能批 3,000 元的单），
但层级低的人不能越权审批（部门负责人不能批 8,500 元的单）。这与制度第五条
「拆分报销以规避审批权限」的防范逻辑一致。

## 同时完成

1. 新增权限码 `reimburse:bill:approve`（报销单-审批）；
2. 报销单表补充审批留痕字段：approval_status / approval_by / approval_at / approval_comment / approval_rank；
3. 创建演示账号：
   - depthead  李强   销售部   部门负责人
   - director  王建国 销售部   部门总监
   - gm        张总   总经理   总经理
   - 财务复核角色授予现有 manager（陈静）—— 制度原文写的就是「财务复核（陈静）」
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import text

from app.core.database import SessionLocal, engine
from app.core.security import hash_password
from app.models.rbac import Permission, Role, RolePermission, User, UserRole
from app.models.reimburse import RmbDepartment, RmbEmployee

DEMO_PASSWORD = "admin123"

# ---------------- 新增权限码 ----------------
NEW_PERMISSIONS = [
    ("reimburse:bill:approve", "报销单-审批", "reimburse"),
]

# ---------------- 分级审批角色（第四条）----------------
# (role_code, role_name, approval_rank, remark, 权限码列表)
APPROVAL_ROLES = [
    (
        "dept_head", "部门负责人", 1,
        "制度第四条：单笔低于 5,000 元的报销由部门负责人审批",
        [
            "reimburse:bill:list",      # 查看待审批报销单
            "reimburse:bill:approve",   # 审批
            "reimburse:bill:delete",    # 作废/撤回本人经手的报销单
            "reimburse:check:run",      # 执行 AI 合规判读
            "reimburse:voucher:list",   # 查看凭证进度
        ],
    ),
    (
        "finance_review", "财务复核", 1,
        "制度第四条：单笔低于 5,000 元可由财务复核审批；第六条赋予财务退单权",
        [
            "reimburse:bill:list",
            "reimburse:bill:approve",
            "reimburse:check:run",
            "reimburse:voucher:list",
            "reimburse:voucher:review",  # 财务复核天然承担凭证复核
        ],
    ),
    (
        "dept_director", "部门总监", 2,
        "制度第四条：5,000（含）至 20,000 元须经部门总监审批；第七条②招待超标亦须总监审批",
        [
            "reimburse:bill:list",
            "reimburse:bill:approve",
            "reimburse:check:run",
            "reimburse:check:override",  # 可作为超标招待的人工覆盖人
            "reimburse:voucher:list",
        ],
    ),
    (
        "general_manager", "总经理", 3,
        "制度第四条：20,000 元以上须经总经理审批；第七/十一条的无票、超标特批权",
        [
            "reimburse:bill:list",
            "reimburse:bill:approve",
            "reimburse:check:run",
            "reimburse:check:override",
            "reimburse:voucher:list",
            "reimburse:policy:manage",   # 制度第十五条：制度由财务部解释，总经理可管理
        ],
    ),
]

# ---------------- 演示账号 ----------------
# (username, real_name, emp_no, [role_codes])
NEW_USERS = [
    ("depthead", "李强", "E009", ["dept_head"]),
    ("director", "王建国", "E010", ["dept_director"]),
    ("gm", "张总", "E011", ["general_manager"]),
]

# ---------------- 新增员工档案 ----------------
NEW_EMPLOYEES = [
    ("E009", "李强", "D02"),    # 销售部 · 部门负责人
    ("E010", "王建国", "D02"),  # 销售部 · 部门总监
    ("E011", "张总", "D05"),    # 总经办 · 总经理（总经理不挂具体业务部门）
]

# 需要补充的部门（D05 总经办是审批角色引入的，原系统只有 D01～D04）
NEW_DEPARTMENTS = [
    ("D05", "总经办"),
]

# 财务复核角色授予现有账号（制度原文点名「财务复核（陈静）」）
FINANCE_REVIEW_TO_USER = "manager"


def ensure_columns(db) -> None:
    """给报销单表补充审批留痕字段。"""
    cols = {r[1] for r in db.execute(text("PRAGMA table_info(rmb_reimbursement)")).fetchall()}
    additions = [
        ("approval_status", "TEXT DEFAULT '未审批'"),   # 未审批 / 已审批 / 已驳回
        ("approval_by", "TEXT DEFAULT ''"),             # 审批人
        ("approval_at", "DATETIME"),                    # 审批时间
        ("approval_comment", "TEXT DEFAULT ''"),        # 审批意见
        ("approval_rank", "INTEGER"),                   # 审批时的层级（1/2/3）
    ]
    for name, ddl in additions:
        if name in cols:
            print(f"  · rmb_reimbursement.{name} 已存在，跳过")
            continue
        db.execute(text(f"ALTER TABLE rmb_reimbursement ADD COLUMN {name} {ddl}"))
        print(f"  + rmb_reimbursement.{name} 已添加")
    db.commit()


def ensure_permissions(db) -> dict:
    """新增审批权限码。"""
    for code, name, module in NEW_PERMISSIONS:
        p = db.query(Permission).filter(Permission.perm_code == code).first()
        if p:
            print(f"  · 权限码 {code} 已存在")
        else:
            db.add(Permission(perm_code=code, perm_name=name, module=module))
            print(f"  + 权限码 {code}（{name}）")
    db.flush()
    return {p.perm_code: p for p in db.query(Permission).all()}


def ensure_roles(db, perms: dict) -> dict:
    """创建 4 个分级审批角色并分配权限。"""
    for code, name, rank, remark, perm_codes in APPROVAL_ROLES:
        role = db.query(Role).filter(Role.role_code == code).first()
        if role:
            print(f"  · 角色 {code}（{name}）已存在")
        else:
            role = Role(role_code=code, role_name=name, remark=f"{remark}｜审批层级 {rank}")
            db.add(role)
            db.flush()
            print(f"  + 角色 {code}（{name}）审批层级 {rank}")

        for pc in perm_codes:
            perm = perms.get(pc)
            if not perm:
                print(f"    ! 权限 {pc} 不存在，跳过")
                continue
            exists = db.query(RolePermission).filter(
                RolePermission.role_id == role.id,
                RolePermission.permission_id == perm.id,
            ).first()
            if not exists:
                db.add(RolePermission(role_id=role.id, permission_id=perm.id))
                print(f"    + {code} ← {pc}")
    db.flush()
    return {r.role_code: r for r in db.query(Role).all()}


def ensure_employees(db) -> dict:
    """补充审批人对应的员工档案与所需部门。"""
    # 先补齐部门（D05 总经办等）
    for code, name in NEW_DEPARTMENTS:
        dept = db.query(RmbDepartment).filter(RmbDepartment.code == code).first()
        if not dept:
            db.add(RmbDepartment(code=code, name=name))
            db.flush()
            print(f"  + 部门 {code} {name}")
    dept_map = {d.code: d.id for d in db.query(RmbDepartment).all()}

    result = {}
    for emp_no, name, dept_code in NEW_EMPLOYEES:
        emp = db.query(RmbEmployee).filter(RmbEmployee.emp_no == emp_no).first()
        if emp:
            # 已存在时校正部门归属（例如总经理原先误挂财务部）
            target = dept_map.get(dept_code)
            if target and emp.department_id != target:
                emp.department_id = target
                print(f"  · 员工 {emp_no} {name} 部门已校正为 {dept_code}")
            else:
                print(f"  · 员工 {emp_no} {name} 已存在")
        else:
            emp = RmbEmployee(emp_no=emp_no, name=name,
                              department_id=dept_map.get(dept_code))
            db.add(emp)
            db.flush()
            print(f"  + 员工 {emp_no} {name}（部门 {dept_code}）")
        result[emp_no] = emp
    return result


def ensure_users(db, roles: dict, employees: dict) -> None:
    """创建审批人演示账号，并把财务复核角色授予陈静（manager）。"""
    for username, real_name, emp_no, role_codes in NEW_USERS:
        user = db.query(User).filter(User.username == username).first()
        if user:
            print(f"  · 用户 {username}（{user.real_name}）已存在")
        else:
            user = User(username=username, password_hash=hash_password(DEMO_PASSWORD),
                        real_name=real_name, status=True)
            db.add(user)
            db.flush()
            print(f"  + 用户 {username}（{real_name}）")
        emp = employees.get(emp_no)
        if emp and not user.employee_id:
            user.employee_id = emp.id
            print(f"    → 关联员工 {emp_no} {emp.name}")
        for rc in role_codes:
            role = roles.get(rc)
            if not role:
                continue
            exists = db.query(UserRole).filter(
                UserRole.user_id == user.id, UserRole.role_id == role.id).first()
            if not exists:
                db.add(UserRole(user_id=user.id, role_id=role.id))
                print(f"    → 绑定角色 {rc}（{role.role_name}）")

    # 财务复核角色授予现有 manager（陈静）——制度原文点名
    user = db.query(User).filter(User.username == FINANCE_REVIEW_TO_USER).first()
    role = roles.get("finance_review")
    if user and role:
        exists = db.query(UserRole).filter(
            UserRole.user_id == user.id, UserRole.role_id == role.id).first()
        if not exists:
            db.add(UserRole(user_id=user.id, role_id=role.id))
            print(f"  + {FINANCE_REVIEW_TO_USER}（{user.real_name}）← 角色 finance_review（财务复核）")
        else:
            print(f"  · {FINANCE_REVIEW_TO_USER} 已具备财务复核角色")


def print_summary(db):
    print("\n" + "=" * 78)
    print("分级审批角色一览（依据制度第四条）")
    print("=" * 78)
    print(f"{'角色编码':<16}{'角色名称':<10}{'层级':<6}{'可审批金额':<20}{'演示账号'}")
    print("-" * 78)
    limits = {
        "dept_head": "低于 5,000 元",
        "finance_review": "低于 5,000 元",
        "dept_director": "5,000 ～ 20,000 元",
        "general_manager": "20,000 元以上",
    }
    for code, name, rank, _remark, _perms in APPROVAL_ROLES:
        users = (
            db.query(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .filter(Role.role_code == code)
            .all()
        )
        accounts = "、".join(f"{u.username}({u.real_name})" for u in users) or "（待分配）"
        print(f"{code:<16}{name:<10}{rank:<6}{limits.get(code, ''):<20}{accounts}")
    print("-" * 78)
    print("审批权限向上兼容：总经理可审批任意金额，部门负责人不能越权审批大额单据。")
    print("所有账号口令：admin123")


def run():
    db = SessionLocal()
    try:
        print("[1/5] 补充审批留痕字段 ...")
        ensure_columns(db)

        print("[2/5] 新增审批权限码 ...")
        perms = ensure_permissions(db)

        print("[3/5] 创建分级审批角色 ...")
        roles = ensure_roles(db, perms)

        print("[4/5] 补充员工档案与演示账号 ...")
        employees = ensure_employees(db)
        ensure_users(db, roles, employees)

        db.commit()
        print("[5/5] 完成\n")
        print_summary(db)
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(run())
