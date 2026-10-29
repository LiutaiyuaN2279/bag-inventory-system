"""补齐业务岗位（仓管员 / 质检员）在报销模块的权限（幂等）。

运行：进入 backend 目录后执行
    .venv/Scripts/python.exe scripts/fix_business_role_permissions.py

## 问题

`upgrade_db_v6_reimburse.py` 初始化时只给 admin / manager / buyer 分配了报销权限，
**漏掉了 keeper（仓管员）和 qc（质检员）**。后果是：

- 孙七（keeper，行政部）、赵六（qc，信息技术部）登录后，侧边栏没有「费用报销」菜单；
- 但使用说明里把这两个账号列为「报销人」，文档与实际不一致；
- 演示数据里赵六（qc）本来就有 5 张报销单，自己却看不到。

## 修复

给 keeper / qc 角色补上与 buyer 相同的报销人权限（数据范围仍是「仅本人」）：

    reimburse:bill:list     查看本人报销单
    reimburse:bill:add      填写报销单
    reimburse:bill:edit     修改本人报销单
    reimburse:check:run     执行 AI 合规判读
    reimburse:voucher:list  查看凭证进度

只补这些基础权限，不给审批 / 制单 / 复核 —— 业务岗位不承担财务职能。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.database import SessionLocal
from app.models.rbac import Permission, Role, RolePermission, User, UserRole

#: 需要补齐的角色
TARGET_ROLES = ["keeper", "qc"]

#: 报销人基础权限（与 buyer / staff 一致）
APPLICANT_PERMS = [
    "reimburse:bill:list",
    "reimburse:bill:add",
    "reimburse:bill:edit",
    "reimburse:check:run",
    "reimburse:voucher:list",
]


def run():
    db = SessionLocal()
    try:
        perms = {p.perm_code: p for p in db.query(Permission).all()}
        missing = [c for c in APPLICANT_PERMS if c not in perms]
        if missing:
            print(f"! 权限码缺失：{missing}")
            print("  请先运行 scripts/upgrade_db_v6_reimburse.py")
            return 1

        print("补齐业务岗位的报销人权限 ...")
        for role_code in TARGET_ROLES:
            role = db.query(Role).filter(Role.role_code == role_code).first()
            if not role:
                print(f"  ! 角色 {role_code} 不存在，跳过")
                continue
            added = 0
            for code in APPLICANT_PERMS:
                perm = perms[code]
                exists = db.query(RolePermission).filter(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == perm.id,
                ).first()
                if not exists:
                    db.add(RolePermission(role_id=role.id, permission_id=perm.id))
                    added += 1
            if added:
                print(f"  + {role_code}（{role.role_name}）补 {added} 项权限")
            else:
                print(f"  · {role_code}（{role.role_name}）权限已完整")

        db.commit()
        print("\n完成。\n")

        # 输出受影响账号，便于核对
        print("=" * 66)
        print("业务岗位账号的报销能力")
        print("=" * 66)
        for role_code in TARGET_ROLES + ["buyer"]:
            role = db.query(Role).filter(Role.role_code == role_code).first()
            if not role:
                continue
            users = (
                db.query(User)
                .join(UserRole, UserRole.user_id == User.id)
                .filter(UserRole.role_id == role.id)
                .all()
            )
            names = "、".join(f"{u.username}({u.real_name})" for u in users) or "（无）"
            print(f"  {role.role_name}（{role_code}）：{names}")
        print("\n  能力：填写本人报销单、执行 AI 判读、查看本人凭证（数据范围：仅本人）")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(run())
