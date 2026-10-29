"""给系统管理员补齐报销审批权限（幂等）。

运行：进入 backend 目录后执行
    .venv/Scripts/python.exe scripts/fix_admin_reimburse_approve.py

## 问题

`reimburse:bill:approve`（报销单-审批）是 `add_approval_roles.py` 后期新增的权限码。
`init_db.py` 创建 admin 角色时是按「当时已有的全部权限」授权的，之后新增的权限码
不会被自动补到 admin 上，于是出现：

- `APPROVAL_RANK_BY_ROLE` 明确把 **admin 定义为 3 级审批人**（可代行审批、故障处理）；
- 但 admin 角色实际没有 `reimburse:bill:approve`，导致管理员**看不到也批不了**报销单，
  首页「待我审批」恒为 0，与设计意图矛盾。

## 修复

只给 admin 角色补这一条审批权限。admin 本就应拥有全部权限，属于补齐而非扩权。
幂等：已存在则跳过。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.database import SessionLocal
from app.models.rbac import Permission, Role, RolePermission

PERM_CODE = "reimburse:bill:approve"
ROLE_CODE = "admin"


def run() -> int:
    db = SessionLocal()
    try:
        perm = db.query(Permission).filter(Permission.perm_code == PERM_CODE).first()
        if not perm:
            print(f"! 权限码 {PERM_CODE} 不存在，请先运行 scripts/add_approval_roles.py")
            return 1

        role = db.query(Role).filter(Role.role_code == ROLE_CODE).first()
        if not role:
            print(f"! 角色 {ROLE_CODE} 不存在")
            return 1

        exists = db.query(RolePermission).filter(
            RolePermission.role_id == role.id,
            RolePermission.permission_id == perm.id,
        ).first()
        if exists:
            print(f"· {ROLE_CODE}（{role.role_name}）已有 {PERM_CODE}，无需处理")
            return 0

        db.add(RolePermission(role_id=role.id, permission_id=perm.id))
        db.commit()
        print(f"+ {ROLE_CODE}（{role.role_name}）← {PERM_CODE}")

        # 自检：admin 是否已覆盖全部报销权限码
        all_reimburse = [p.perm_code for p in
                         db.query(Permission).filter(Permission.perm_code.like("reimburse:%")).all()]
        owned = {p.perm_code for p in role.permissions}
        missing = [c for c in all_reimburse if c not in owned]
        print(f"\n自检：admin 报销权限 {len(all_reimburse) - len(missing)}/{len(all_reimburse)} 项")
        if missing:
            print("  仍缺少：" + ", ".join(missing))
        else:
            print("  ✓ 已覆盖全部报销权限码")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(run())
