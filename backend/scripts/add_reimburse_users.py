"""为差旅报销模块新增专用账号（幂等，可重复执行）。

运行：进入 backend 目录后执行
    .venv/Scripts/python.exe scripts/add_reimburse_users.py

## 为什么需要这些账号

原系统的五个演示账号（admin / manager / buyer / keeper / qc）是采购与库存业务岗位，
报销流程中的财务角色由两个无法体现部门的通用账号（maker 张三 / reviewer 李四）承担，
演示「财务制单 → 财务复核」时缺少真实感。本脚本补充：

1. **员工档案**：财务部与业务部门的报销人员工记录（rmb_employee）
2. **普通员工角色**（staff）：报销人专用角色，与采购员 buyer 的操作权限区分开，
   避免把销售/技术岗的人塞进「采购员」角色造成语义混乱
3. **报销专用账号**：
   - finance  财务经理 → 复核员（凭证复核、退回）
   - finmaker 财务专员 → 制单员（AI 制证、凭证保存）
   - sales    销售专员 → 报销人
   - tech     IT 工程师 → 报销人

## 职责分离说明

`finance`（复核）与 `finmaker`（制单）是**两个不同账号**，这是有意设计：
系统要求制单人不能复核自己制作的凭证，若合并成一个财务账号，演示复核时必然被拦截。
同理 `maker` / `reviewer` 也保持分离。

## 口令

全部为 `admin123`，与既有演示账号一致。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.rbac import Permission, Role, RolePermission, User, UserRole
from app.models.reimburse import RmbDepartment, RmbEmployee

DEMO_PASSWORD = "admin123"

# ---------------- 新增员工档案 ----------------
# (emp_no, name, department_code)
NEW_EMPLOYEES = [
    ("E005", "周敏", "D01"),   # 财务部 · 财务经理（复核）
    ("E006", "吴强", "D01"),   # 财务部 · 财务专员（制单）
    ("E007", "郑洁", "D02"),   # 销售部 · 销售专员（报销人）
    ("E008", "冯磊", "D03"),   # 信息技术部 · IT 工程师（报销人）
]

# ---------------- 新增角色：普通员工（报销人）----------------
STAFF_ROLE = ("staff", "普通员工", "各部门普通员工：填写与提交本人报销单、执行 AI 合规判读")
STAFF_PERMS = [
    "reimburse:bill:list",     # 查看本人报销单
    "reimburse:bill:add",      # 填写报销单
    "reimburse:bill:edit",     # 修改本人报销单
    "reimburse:check:run",     # 执行 AI 合规判读
    "reimburse:voucher:list",  # 查看凭证（了解审批进度）
]

# ---------------- 新增用户 ----------------
# (username, real_name, emp_no, [role_codes], 说明)
NEW_USERS = [
    ("finance", "周敏", "E005", ["reviewer"], "财务经理 · 凭证复核"),
    ("finmaker", "吴强", "E006", ["maker"], "财务专员 · AI 制证与凭证保存"),
    ("sales", "郑洁", "E007", ["staff"], "销售专员 · 报销人"),
    ("tech", "冯磊", "E008", ["staff"], "IT 工程师 · 报销人"),
]


def ensure_departments(db) -> dict:
    """确保四个部门存在，返回 {code: id}。"""
    dept_map = {d.code: d.id for d in db.query(RmbDepartment).all()}
    for code, name in [("D01", "财务部"), ("D02", "销售部"),
                       ("D03", "信息技术部"), ("D04", "行政部")]:
        if code not in dept_map:
            d = RmbDepartment(code=code, name=name)
            db.add(d)
            db.flush()
            dept_map[code] = d.id
            print(f"  + 补充部门 {code} {name}")
    return dept_map


def ensure_employees(db, dept_map: dict) -> dict:
    """新增员工档案，返回 {emp_no: RmbEmployee}。"""
    result = {}
    for emp_no, name, dept_code in NEW_EMPLOYEES:
        emp = db.query(RmbEmployee).filter(RmbEmployee.emp_no == emp_no).first()
        if emp:
            print(f"  · 员工 {emp_no} {name} 已存在，跳过")
        else:
            emp = RmbEmployee(emp_no=emp_no, name=name, department_id=dept_map.get(dept_code))
            db.add(emp)
            db.flush()
            print(f"  + 员工 {emp_no} {name}（部门 {dept_code}）")
        result[emp_no] = emp
    return result


def ensure_staff_role(db) -> Role:
    """新增「普通员工」角色并授予报销基础权限。"""
    role = db.query(Role).filter(Role.role_code == STAFF_ROLE[0]).first()
    if role:
        print(f"  · 角色 {STAFF_ROLE[0]} 已存在")
    else:
        role = Role(role_code=STAFF_ROLE[0], role_name=STAFF_ROLE[1], remark=STAFF_ROLE[2])
        db.add(role)
        db.flush()
        print(f"  + 角色 {STAFF_ROLE[0]}（{STAFF_ROLE[1]}）")

    perms = {p.perm_code: p for p in db.query(Permission).all()}
    for code in STAFF_PERMS:
        perm = perms.get(code)
        if not perm:
            print(f"    ! 权限 {code} 不存在，跳过（请先运行 upgrade_db_v6_reimburse.py）")
            continue
        exists = db.query(RolePermission).filter(
            RolePermission.role_id == role.id,
            RolePermission.permission_id == perm.id,
        ).first()
        if not exists:
            db.add(RolePermission(role_id=role.id, permission_id=perm.id))
            print(f"    + {STAFF_ROLE[0]} ← {code}")
    return role


def ensure_users(db, employees: dict):
    """新增用户、绑定角色与员工档案。"""
    roles = {r.role_code: r for r in db.query(Role).all()}
    for username, real_name, emp_no, role_codes, desc in NEW_USERS:
        user = db.query(User).filter(User.username == username).first()
        if user:
            print(f"  · 用户 {username}（{user.real_name}）已存在，跳过创建")
        else:
            user = User(
                username=username,
                password_hash=hash_password(DEMO_PASSWORD),
                real_name=real_name,
                status=True,
            )
            db.add(user)
            db.flush()
            print(f"  + 用户 {username}（{real_name}）· {desc}")

        # 关联员工档案
        emp = employees.get(emp_no)
        if emp and not user.employee_id:
            user.employee_id = emp.id
            print(f"    → 关联员工档案 {emp_no} {emp.name}")

        # 绑定角色
        for rc in role_codes:
            role = roles.get(rc)
            if not role:
                print(f"    ! 角色 {rc} 不存在，跳过")
                continue
            exists = db.query(UserRole).filter(
                UserRole.user_id == user.id, UserRole.role_id == role.id
            ).first()
            if not exists:
                db.add(UserRole(user_id=user.id, role_id=role.id))
                print(f"    → 绑定角色 {rc}（{role.role_name}）")


def print_summary(db):
    """打印报销模块可用的全部账号。"""
    print("\n" + "=" * 74)
    print("报销功能账号一览（口令统一 admin123）")
    print("=" * 74)

    rows = (
        db.query(User)
        .join(UserRole, UserRole.user_id == User.id, isouter=True)
        .join(Role, Role.id == UserRole.role_id, isouter=True)
        .order_by(User.id)
        .all()
    )
    seen = {}
    for user in db.query(User).order_by(User.id).all():
        roles = "、".join(r.role_name for r in user.roles) or "-"
        emp = db.get(RmbEmployee, user.employee_id) if user.employee_id else None
        dept = db.get(RmbDepartment, emp.department_id) if emp and emp.department_id else None
        # 只关心与报销相关的账号（有报销权限或报销角色）
        perm_codes = set()
        for r in user.roles:
            perm_codes |= {p.perm_code for p in r.permissions}
        rmb_perms = [c for c in perm_codes if c.startswith("reimburse:")]
        has_admin = any(r.role_code == "admin" for r in user.roles)
        if not rmb_perms and not has_admin:
            continue

        if "admin" in [r.role_code for r in user.roles]:
            ability = "全部功能（含制度管理）"
        elif "reimburse:policy:manage" in perm_codes:
            ability = "制度与参数管理"
        elif ("reimburse:voucher:make" in perm_codes
              and "reimburse:voucher:review" in perm_codes):
            ability = "制单 + 复核（跨角色，不推荐）"
        elif "reimburse:voucher:make" in perm_codes:
            ability = "AI 制证、凭证保存、人工覆盖判定"
        elif "reimburse:voucher:review" in perm_codes:
            ability = "凭证复核（通过/退回）"
        else:
            ability = "填写报销单、执行 AI 判读"
        seen[user.username] = (user.real_name, dept.name if dept else "-", roles, ability)

    print(f"{'账号':<11}{'姓名':<7}{'部门':<12}{'角色':<20}{'报销能力'}")
    print("-" * 74)
    for username, (name, dept, roles, ability) in seen.items():
        print(f"{username:<11}{name or '-':<7}{dept:<12}{roles:<20}{ability}")
    print("-" * 74)
    print("说明：finance（复核）与 finmaker（制单）是分离的两个账号，")
    print("      因为系统要求制单人不能复核自己制作的凭证。")


def run():
    db = SessionLocal()
    try:
        print("[1/5] 检查部门 ...")
        dept_map = ensure_departments(db)

        print("[2/5] 新增员工档案 ...")
        employees = ensure_employees(db, dept_map)

        print("[3/5] 新增「普通员工」角色 ...")
        ensure_staff_role(db)

        print("[4/5] 新增用户并绑定角色 ...")
        ensure_users(db, employees)

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
