"""删除通用制单员「张三（maker）」与通用复核员「李四（reviewer）」两个账号（幂等）。

运行：进入 backend 目录后执行
    .venv/Scripts/python.exe scripts/remove_generic_maker_reviewer.py

## 为什么删除

这两个账号是报销模块早期的「通用制单员 / 通用复核员」占位账号，没有员工档案、
没有部门归属。财务岗已经补全后，制单与复核职能由财务部员工承担：

| 职能 | 账号 | 姓名 | 部门 |
| --- | --- | --- | --- |
| 制单 | `finmaker` | 吴强 | 财务部（制单员 + 财务审批）|
| 复核 | `finance` | 周敏 | 财务部（复核员 + 财务审批）|

张三 / 李四 与吴强 / 周敏 的角色完全重复，且没有部门归属，留在演示账号里只会
让人困惑「为什么有两个制单员、两个复核员，其中一个还不属于任何部门」。

## 删除范围

- 删除 `users` 记录；
- 删除 `user_roles` 角色绑定；
- 删除 `user_permissions` 用户级权限覆盖（若有）；
- **保留** `maker` / `reviewer` 两个**角色**（吴强、周敏仍在用）；
- **保留** `operation_logs` 里的历史日志（审计轨迹不可删，用户名是字符串快照）；
- 不触碰任何报销单 / 凭证（本就没有关联数据）。

## 安全前提

脚本会先检查这两个账号是否产生过业务数据（创建的报销单、制单/复核的凭证），
若发现有关联则拒绝删除并提示人工处理，避免破坏审计链。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.database import SessionLocal
from app.models.rbac import User
from app.models.reimburse import RmbReimbursement, RmbVoucher

#: 待删除的账号（用户名 → 姓名，仅用于输出）
TARGETS = [
    ("maker", "张三"),
    ("reviewer", "李四"),
]


def check_safe(db, username: str) -> tuple[bool, str]:
    """检查该账号是否产生过业务数据；有则拒绝删除。"""
    bills = db.query(RmbReimbursement).filter(
        RmbReimbursement.created_by == username).count()
    if bills:
        return False, f"该账号创建过 {bills} 张报销单，请先转移或作废后再删除"
    made = db.query(RmbVoucher).filter(RmbVoucher.maker == username).count()
    if made:
        return False, f"该账号制作过 {made} 张凭证，会破坏审计链，不允许删除"
    reviewed = db.query(RmbVoucher).filter(RmbVoucher.reviewer == username).count()
    if reviewed:
        return False, f"该账号复核过 {reviewed} 张凭证，会破坏审计链，不允许删除"
    return True, ""


def run():
    db = SessionLocal()
    try:
        print("检查待删除账号 ...")
        removed = []
        for username, real_name in TARGETS:
            user = db.query(User).filter(User.username == username).first()
            if not user:
                print(f"  · {username}（{real_name}）不存在，跳过")
                continue

            ok, reason = check_safe(db, username)
            if not ok:
                print(f"  ✗ {username}（{real_name}）：{reason}")
                continue

            # 解除角色关联：必须通过 relationship 清空，不能直接 DELETE user_roles，
            # 否则 ORM 删除 user 时还会再删一次关联，抛 StaleDataError。
            n_roles = len(user.roles or [])
            user.roles.clear()
            # 用户级权限覆盖：relationship 已配置 cascade="all, delete-orphan"，随用户删除
            n_perms = len(user.perm_overrides or [])
            db.flush()
            db.delete(user)
            db.flush()
            removed.append((username, real_name, n_roles, n_perms))
            print(f"  - 已删除 {username}（{real_name}）：解除角色 {n_roles} 个、"
                  f"用户级权限 {n_perms} 条")

        db.commit()
        print()

        if not removed:
            print("没有需要删除的账号（可能已删除过）。")
        else:
            print(f"共删除 {len(removed)} 个账号。")

        # 输出剩余账号，便于核对
        print()
        print("=" * 66)
        print("剩余全部账号")
        print("=" * 66)
        users = db.query(User).order_by(User.id).all()
        for u in users:
            roles = "、".join(r.role_name for r in u.roles) or "-"
            print(f"  {u.username:<11}{u.real_name or '':<8}{roles}")
        print()
        print("说明：maker / reviewer 两个【角色】仍保留，由吴强、周敏使用。")
        print("      制单员 = finmaker（吴强），复核员 = finance（周敏）。")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(run())
