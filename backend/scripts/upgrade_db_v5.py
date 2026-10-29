"""第六轮升级：新增「智能审计」权限码并分配给各角色（幂等）。

运行：进入 backend 目录后执行  .venv/Scripts/python.exe scripts/upgrade_db_v5.py

说明：智能审计工作台是本系统内的审计端页面，权限码统一由本脚本维护；
重复执行不会产生重复记录。

权限码：
  audit:view   智能审计-查看（进入工作台、查看审计程序与审计发现）
  audit:run    智能审计-执行（重新运行审计程序）

角色分配遵循最小权限：
  admin    两个权限全给（系统管理员）
  manager  两个全给（运营主管承担内部复核职责）
  buyer/keeper/qc  不给 —— 被审计业务岗位不应持有审计端权限，
                   这正是审计独立性要求在权限设计上的体现。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.rbac import Permission, Role, RolePermission

NEW_PERMISSIONS = [
    ("audit:view", "智能审计-查看", "audit"),
    ("audit:run", "智能审计-执行", "audit"),
]

# 角色 -> 授予的权限码
ROLE_GRANTS = {
    "admin": ["audit:view", "audit:run"],
    "manager": ["audit:view", "audit:run"],
}


def run():
    db = SessionLocal()
    try:
        print("[1/3] 补齐审计权限码 ...")
        for code, name, module in NEW_PERMISSIONS:
            p = db.query(Permission).filter(Permission.perm_code == code).first()
            if p:
                print(f"  - {code} 已存在，跳过")
            else:
                db.add(Permission(perm_code=code, perm_name=name, module=module))
                print(f"  + {code} 已添加")
        db.flush()

        perms = {p.perm_code: p for p in db.query(Permission).all()}

        print("[2/3] 为角色授予审计权限 ...")
        for role_code, codes in ROLE_GRANTS.items():
            role = db.query(Role).filter(Role.role_code == role_code).first()
            if not role:
                print(f"  ! 角色 {role_code} 不存在，跳过（请先运行 scripts/setup_roles.py）")
                continue
            for code in codes:
                perm = perms.get(code)
                if not perm:
                    continue
                exists = db.query(RolePermission).filter(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == perm.id,
                ).first()
                if exists:
                    continue
                db.add(RolePermission(role_id=role.id, permission_id=perm.id))
                print(f"  + {role_code} <- {code}")
        db.commit()

        print("[3/3] 核对结果 ...")
        for r in db.query(Role).all():
            codes = sorted(p.perm_code for p in r.permissions if p.perm_code.startswith("audit:"))
            print(f"  {r.role_code}({r.role_name}): {codes or '无审计权限'}")
        print("升级完成！")
    finally:
        db.close()


if __name__ == "__main__":
    run()
