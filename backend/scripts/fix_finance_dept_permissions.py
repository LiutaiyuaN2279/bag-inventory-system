"""按「财务部」岗位职责补齐财务岗权限（幂等）。

运行：进入 backend 目录后执行
    .venv/Scripts/python.exe scripts/fix_finance_dept_permissions.py

## 问题

财务部三名员工原先挂的是「通用职能角色」，只覆盖了财务工作的一小块：

| 账号 | 姓名 | 部门 | 原角色 | 报销权限 | 缺失 |
| --- | --- | --- | --- | --- | --- |
| `manager` | 陈静 | 财务部 | 运营主管 + 财务复核 | 12 项 | —— |
| `finance` | 周敏 | 财务部 | 复核员 | 3 项 | **审批、判读、覆盖** |
| `finmaker` | 吴强 | 财务部 | 制单员 | 5 项 | **审批** |

财务岗的日常是「看单 → 审批 → 判读 → 制单/复核」，审批（制度第四条的
「财务复核」口径）和合规判读是财务的基本职能，不配齐就无法完成本职工作。

## 为什么不能只手工授予权限码

审批层级 `APPROVAL_RANK_BY_ROLE` 是按**角色**算的，不是按权限码：
制单员/复核员在映射表里没有审批层级（rank=0），即使后台勾上
`reimburse:bill:approve`，审批时仍会被判「层级不足」。

## 方案

新增角色 `finance_approve`（财务审批），专门承载财务岗的审批与判读职能：

- 权限：`bill:list` / `bill:approve` / `check:run` / `check:override` / `voucher:list`
- 审批层级：1 级（< 5,000 元，对应制度第四条「财务复核」口径）
- 数据范围：全公司（财务是职能条线）

**刻意不含** `voucher:make`（制单）与 `voucher:review`（复核）：
制单和复核必须保持分离，这两项仍由制单员 / 复核员角色承担。

分配后：

| 账号 | 角色组合 | 效果 |
| --- | --- | --- |
| `finmaker` 吴强 | 制单员 + 财务审批 | 制证 + 审批 + 判读 + 覆盖（不能复核）|
| `finance` 周敏 | 复核员 + 财务审批 | 复核 + 审批 + 判读 + 覆盖（不能制单）|
| `manager` 陈静 | 运营主管 + 财务复核 | 不变（已是全财务职能）|
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.database import SessionLocal
from app.models.rbac import Permission, Role, RolePermission, User, UserRole

# ---------------- 新增角色：财务审批 ----------------
ROLE_CODE = "finance_approve"
ROLE_NAME = "财务审批"
ROLE_REMARK = (
    "制度第四条：财务岗在本部门/全公司范围内审批低于 5,000 元的报销单，"
    "并执行 AI 合规判读与人工覆盖判定（不含制单与复核，保持职责分离）"
)

ROLE_PERMS = [
    "reimburse:bill:list",       # 查看报销单
    "reimburse:bill:approve",    # 审批（制度第四条财务复核口径）
    "reimburse:bill:delete",     # 作废/撤回报销单（与 upgrade_db_v6_reimburse 的 ROLE_GRANTS 一致）
    "reimburse:check:run",       # 执行 AI 合规判读
    "reimburse:check:override",  # 人工覆盖判定（制度第六/十四条：财务有权退单）
    "reimburse:voucher:list",    # 查看凭证进度
]

# 需要赋予该角色的财务部账号
TARGET_USERS = ["finmaker", "finance"]


def run():
    db = SessionLocal()
    try:
        print("[1/3] 创建「财务审批」角色 ...")
        role = db.query(Role).filter(Role.role_code == ROLE_CODE).first()
        if role:
            print(f"  · 角色 {ROLE_CODE} 已存在")
        else:
            role = Role(role_code=ROLE_CODE, role_name=ROLE_NAME,
                        remark=f"{ROLE_REMARK}｜审批层级 1")
            db.add(role)
            db.flush()
            print(f"  + 角色 {ROLE_CODE}（{ROLE_NAME}）已创建")

        print("[2/3] 分配角色权限 ...")
        perms = {p.perm_code: p for p in db.query(Permission).all()}
        for code in ROLE_PERMS:
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
                print(f"    + {ROLE_CODE} ← {code}")
            else:
                print(f"    · {ROLE_CODE} 已具备 {code}")

        print("[3/3] 授予财务部账号 ...")
        for username in TARGET_USERS:
            user = db.query(User).filter(User.username == username).first()
            if not user:
                print(f"  ! 用户 {username} 不存在，跳过")
                continue
            exists = db.query(UserRole).filter(
                UserRole.user_id == user.id, UserRole.role_id == role.id
            ).first()
            if exists:
                print(f"  · {username}（{user.real_name}）已具备财务审批角色")
                continue
            db.add(UserRole(user_id=user.id, role_id=role.id))
            print(f"  + {username}（{user.real_name}）← 财务审批")

        db.commit()
        print("\n完成。\n")
        print_finance_summary(db)
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def print_finance_summary(db):
    """打印财务部员工的最终权限，便于核对。"""
    print("=" * 78)
    print("财务部员工权限一览")
    print("=" * 78)

    from app.models.reimburse import RmbDepartment, RmbEmployee

    rows = (
        db.query(User)
        .join(RmbEmployee, RmbEmployee.id == User.employee_id)
        .join(RmbDepartment, RmbDepartment.id == RmbEmployee.department_id)
        .filter(RmbDepartment.name == "财务部")
        .order_by(User.id)
        .all()
    )
    for user in rows:
        roles = "、".join(r.role_name for r in user.roles if r.role_name) or "-"
        perms = set()
        for r in user.roles:
            perms |= {p.perm_code for p in r.permissions}
        rmb = sorted(p.replace("reimburse:", "") for p in perms if p.startswith("reimburse:"))
        print(f"\n  {user.username}（{user.real_name}）")
        print(f"    角色：{roles}")
        print(f"    报销权限（{len(rmb)} 项）：{'、'.join(rmb)}")
        # 关键能力打勾
        ability = []
        ability.append("审批 ✓" if "reimburse:bill:approve" in perms else "审批 ✗")
        ability.append("判读 ✓" if "reimburse:check:run" in perms else "判读 ✗")
        ability.append("覆盖 ✓" if "reimburse:check:override" in perms else "覆盖 ✗")
        ability.append("制单 ✓" if "reimburse:voucher:make" in perms else "制单 ✗")
        ability.append("复核 ✓" if "reimburse:voucher:review" in perms else "复核 ✗")
        print(f"    能力：{'  '.join(ability)}")

    print("\n" + "-" * 78)
    print("财务审批角色不含制单/复核：吴强制证由周敏复核，职责分离保持有效。")


if __name__ == "__main__":
    sys.exit(run())
