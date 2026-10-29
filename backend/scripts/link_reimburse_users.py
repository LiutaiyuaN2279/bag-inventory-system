"""建立系统用户与报销员工档案的关联，并补充复核角色（幂等）。

运行：进入 backend 目录后执行
    .venv/Scripts/python.exe scripts/link_reimburse_users.py

背景：
现有系统的 users 表只有 username / real_name / 角色，没有关联员工档案。
报销模块需要知道"当前登录人是谁的员工档案"（用于固定报销人、校验职责分离）。
本脚本在 users 表上增加 employee_id 列（若不存在），并按姓名匹配 rmb_employee。

同时补充两个与职责分离相关的角色：
- 制单员（maker）：可制证，不可复核
- 复核员（reviewer）：可复核，不可制单
这样"报销人 / 制单人 / 复核人三分离"在角色层面就成立，而不是只靠代码判断。

演示账号约定（口令统一 admin123）：
- admin    系统管理员  → 全部权限
- manager  运营主管    → 制单 + 判读覆盖
- buyer    采购员      → 报销人（王五）
- keeper   仓管员      → 同 buyer（报销人）
- qc       质检员      → 同 buyer（报销人）
- maker    制单员（张三）→ 仅制单
- reviewer 复核员（李四）→ 仅复核
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.core.database import SessionLocal, engine
from app.core.security import hash_password
from app.models.rbac import Permission, Role, RolePermission, User, UserRole
from app.models.reimburse import RmbDepartment, RmbEmployee

DEMO_PASSWORD = "admin123"

# username -> (real_name, emp_no 或 None, [role_code])
# 注意：早期版本这里还会创建「maker 张三 / reviewer 李四」两个通用制单/复核账号，
# 它们没有员工档案与部门归属，与财务部的吴强/周敏职能重复，已被删除
# （见 scripts/remove_generic_maker_reviewer.py）。此处不再创建，重跑也不会复活。
USER_SETUP = [
    ("buyer", None, "E002", None),      # 王五，销售部
    ("keeper", None, "E004", None),     # 孙七，行政部
    ("qc", None, "E003", None),         # 赵六，信息技术部
    ("manager", None, "E001", None),    # 陈静，财务部
]

NEW_ROLES = [
    ("maker", "制单员", "负责 AI 制证与凭证编辑保存，不得复核自己制作的凭证"),
    ("reviewer", "复核员", "负责凭证复核，不得制单，也不得复核自己是报销人的凭证"),
]

MAKER_PERMS = [
    "reimburse:bill:list", "reimburse:voucher:list", "reimburse:voucher:make",
    "reimburse:check:run", "reimburse:check:override",
]
REVIEWER_PERMS = [
    "reimburse:bill:list", "reimburse:voucher:list", "reimburse:voucher:review",
]


def ensure_column(db):
    """users 表增加 employee_id 列。"""
    cols = [r[1] for r in db.execute(text("PRAGMA table_info(users)")).fetchall()]
    if "employee_id" in cols:
        print("  · users.employee_id 已存在，跳过")
        return
    db.execute(text("ALTER TABLE users ADD COLUMN employee_id INTEGER"))
    db.commit()
    print("  + users.employee_id 已添加")


def run():
    db = SessionLocal()
    try:
        print("[1/5] 检查并补充 users.employee_id 列 ...")
        ensure_column(db)

        print("[2/5] 补充制单员 / 复核员角色 ...")
        for code, name, remark in NEW_ROLES:
            role = db.query(Role).filter(Role.role_code == code).first()
            if not role:
                db.add(Role(role_code=code, role_name=name, remark=remark))
                print(f"  + 角色 {code}（{name}）已添加")
            else:
                print(f"  · 角色 {code} 已存在")
        db.flush()

        print("[3/5] 为制单员 / 复核员分配权限 ...")
        perms = {p.perm_code: p for p in db.query(Permission).all()}
        role_map = {r.role_code: r for r in db.query(Role).all()}
        for role_code, codes in (("maker", MAKER_PERMS), ("reviewer", REVIEWER_PERMS)):
            role = role_map.get(role_code)
            if not role:
                continue
            for code in codes:
                perm = perms.get(code)
                if not perm:
                    print(f"    ! 权限 {code} 不存在，跳过")
                    continue
                exists = db.query(RolePermission).filter(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == perm.id,
                ).first()
                if not exists:
                    db.add(RolePermission(role_id=role.id, permission_id=perm.id))
                    print(f"    + {role_code} ← {code}")
        db.flush()

        print("[4/5] 建立用户与员工档案的关联 ...")
        emps = {e.emp_no: e for e in db.query(RmbEmployee).all()}
        for username, real_name, emp_no, role_codes in USER_SETUP:
            user = db.query(User).filter(User.username == username).first()
            if not user:
                print(f"  · 用户 {username} 不存在，跳过")
                continue
            if emp_no and emp_no in emps:
                user.employee_id = emps[emp_no].id
                print(f"  + {username} → {emps[emp_no].name}（{emp_no}）")
            if role_codes:
                for rc in role_codes:
                    role = role_map.get(rc)
                    if not role:
                        continue
                    exists = db.query(UserRole).filter(
                        UserRole.user_id == user.id, UserRole.role_id == role.id
                    ).first()
                    if not exists:
                        db.add(UserRole(user_id=user.id, role_id=role.id))
                        print(f"  + {username} ← 角色 {rc}")
        db.flush()

        # 制单员 / 复核员账号已改由 scripts/add_reimburse_users.py 创建（财务部员工），
        # 这里不再创建无部门的通用账号（张三 / 李四 已删除）。
        db.commit()
        print("\n关联完成！")
        print("报销流程演示账号（口令均为 admin123）：")
        print("  报销人：buyer(王五) / keeper(孙七) / qc(赵六) / sales(郑洁) / tech(冯磊)")
        print("  财务制单：finmaker(吴强)    财务复核：finance(周敏)")
        print("  分级审批：depthead(李强) / director(王建国) / gm(张总)")
        print("  管理员：admin")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
