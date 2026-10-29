r"""第二轮升级：外发加工 / 质检 / 日志表 + 权限码。运行：进入 backend 后 .venv/Scripts/python.exe scripts/upgrade_db_v2.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.core.database import Base, SessionLocal, engine
from app.models import *  # noqa: F401,F403
from app.models.rbac import Permission, Role, RolePermission

NEW_PERMISSIONS = [
    ("outsource:list", "外发加工-查看", "outsource"),
    ("outsource:edit", "外发加工-维护", "outsource"),
    ("qc:view", "质检-查看", "qc"),
    ("qc:edit", "质检-录入", "qc"),
    ("report:view", "报表-查看", "report"),
    ("system:log", "系统-操作日志", "system"),
]


def run():
    print("创建新表 ...")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        role = db.execute(select(Role).where(Role.role_code == "admin")).scalar_one()
        for code, name, module in NEW_PERMISSIONS:
            p = db.execute(select(Permission).where(Permission.perm_code == code)).scalar_one_or_none()
            if not p:
                p = Permission(perm_code=code, perm_name=name, module=module)
                db.add(p); db.flush()
            if not db.execute(select(RolePermission).where(
                    RolePermission.role_id == role.id, RolePermission.permission_id == p.id)).scalar_one_or_none():
                db.add(RolePermission(role_id=role.id, permission_id=p.id))
        db.commit()
        print("升级完成！")
    finally:
        db.close()


if __name__ == "__main__":
    run()
