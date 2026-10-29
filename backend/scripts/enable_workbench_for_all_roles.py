"""给所有角色补齐首页访问权限（dashboard:view），并注册报销工作台路由（幂等）。

运行：进入 backend 目录后执行
    .venv/Scripts/python.exe scripts/enable_workbench_for_all_roles.py

## 背景

首页 `/dashboard` 的路由守卫要求 `dashboard:view`。原系统只有采购/库存/管理岗位
（admin / manager / buyer / keeper / qc）具备该权限；报销模块新增的 7 个角色
（财务审批、制单员、复核员、普通员工、部门负责人、部门总监、总经理）都没有，
登录后会被守卫直接送到「报销单列表」，看不到任何首页。

## 方案：一个入口，两种看板

补齐 `dashboard:view` 后，首页组件再按**是否有采购报表权限（report:view）**分发：

| 用户类型 | 有 report:view | 首页显示 |
| --- | --- | --- |
| 采购 / 库存 / 管理岗 | 是 | 采购库存看板（原有 KPI + 趋势 + 待办）|
| 报销专用角色 | 否 | **报销工作台**（报销 KPI + 待办 + 最近单据 + 本月费用构成）|

这样所有角色登录后都有可用首页，且各自看到与自己工作相关的数据，
不会出现「报销角色打开采购看板、接口 403 变空壳」的割裂体验。

## 注意

`dashboard:view` 只是**访问首页**的权限，不含任何业务数据权限；
数据仍由各接口按角色权限与数据范围裁剪。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.database import SessionLocal
from app.models.rbac import Permission, Role, RolePermission

#: 首页访问权限码
PERM_CODE = "dashboard:view"

#: 需要补齐首页权限的角色（报销模块新增的 7 个）
TARGET_ROLES = [
    "finance_approve",   # 财务审批
    "finance_review",    # 财务复核
    "maker",             # 制单员
    "reviewer",          # 复核员
    "staff",             # 普通员工
    "dept_head",         # 部门负责人
    "dept_director",     # 部门总监
    "general_manager",   # 总经理
]


def run():
    db = SessionLocal()
    try:
        perm = db.query(Permission).filter(Permission.perm_code == PERM_CODE).first()
        if not perm:
            print(f"! 权限码 {PERM_CODE} 不存在，请先运行 scripts/init_db.py")
            return 1

        print(f"给角色补齐 {PERM_CODE}（首页访问权限）...")
        added = 0
        for code in TARGET_ROLES:
            role = db.query(Role).filter(Role.role_code == code).first()
            if not role:
                print(f"  ! 角色 {code} 不存在，跳过")
                continue
            exists = db.query(RolePermission).filter(
                RolePermission.role_id == role.id,
                RolePermission.permission_id == perm.id,
            ).first()
            if exists:
                print(f"  · {code}（{role.role_name}）已具备")
                continue
            db.add(RolePermission(role_id=role.id, permission_id=perm.id))
            added += 1
            print(f"  + {code}（{role.role_name}）← {PERM_CODE}")

        db.commit()
        print(f"\n完成，新增 {added} 条角色权限。\n")

        # 校验：是否所有启用角色都能进首页
        print("=" * 60)
        print("各角色的首页访问权限")
        print("=" * 60)
        for role in db.query(Role).order_by(Role.id).all():
            has = any(p.perm_code == PERM_CODE for p in role.permissions)
            print(f"  {'✓' if has else '✗'} {role.role_code:<18}{role.role_name}")
        print("\n说明：有 report:view → 采购库存看板；否则 → 报销工作台。")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(run())
