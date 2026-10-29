"""恢复质检员（qc / 赵六）被误禁的业务权限，只保留设计内的「额外授予」。

运行：进入 backend 目录后执行
    .venv/Scripts/python.exe scripts/restore_qc_permissions.py

## 问题

数据库里 `qc` 用户存在 5 条**用户级 deny**，把它们从角色继承的业务权限全部收回了：

    basic:material:list   物料查看
    basic:supplier:list   供应商查看
    purchase:arrival:list 到货单查看
    outsource:list        外发加工查看
    ai:ocr:list           AI 识别记录查看

后果：赵六登录后首页「快速入口」只剩 2 个（来料质检 / 成品质检），侧边栏看不到
物料、供应商、到货单与外发加工；README 的 AI 识别权限矩阵写明 qc 应具备
`ai:ocr:list`，与实际不符。

## 设计基线（README + setup_roles.py）

qc 的用户级覆盖**只有一条**：额外授予 `ai:ocr:recognize`（质检单据自助上传识别）。
不存在任何 deny —— 上述 5 条 deny 属于后手工改动，与基线不符。

## 修复

只删除这 5 条 deny，**不动角色权限、不动其它用户**（尤其不会触发
`setup_roles.py` 重跑 —— 那会连带清掉 keeper/qc 的报销权限）。幂等，可反复执行。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.database import SessionLocal
from app.models.rbac import Permission, User, UserPermission

#: 需要恢复（删除 deny）的权限码
RESTORE_CODES = [
    "basic:material:list",
    "basic:supplier:list",
    "purchase:arrival:list",
    "outsource:list",
    "ai:ocr:list",
]

#: 设计内应保留的额外授予
GRANT_CODES = ["ai:ocr:recognize"]

USERNAME = "qc"


def run() -> int:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == USERNAME).first()
        if not user:
            print(f"! 用户 {USERNAME} 不存在")
            return 1

        perms = {p.perm_code: p for p in db.query(Permission).all()}
        rows = db.query(UserPermission).filter(UserPermission.user_id == user.id).all()
        by_code = {}
        for r in rows:
            code = next((c for c, p in perms.items() if p.id == r.permission_id), None)
            if code:
                by_code[code] = r

        print(f"用户：{user.username}（{user.real_name}）现有用户级覆盖：")
        if not by_code:
            print("  （无）")
        for code, r in sorted(by_code.items()):
            print(f"  {r.effect:<6} {code}")

        removed = 0
        for code in RESTORE_CODES:
            r = by_code.get(code)
            if r is None:
                continue
            if r.effect == "deny":
                db.delete(r)
                removed += 1
                print(f"  - 删除 deny：{code}")
            else:
                # 已存在 grant 说明是另一种配置，不动，避免破坏
                print(f"  · 跳过 {code}（effect={r.effect}，非 deny）")

        # 确保设计内的 grant 存在
        for code in GRANT_CODES:
            if code not in perms:
                print(f"  ! 权限码不存在：{code}")
                continue
            if code in by_code:
                print(f"  · 已有覆盖：{code}（effect={by_code[code].effect}）")
                continue
            db.add(UserPermission(user_id=user.id, permission_id=perms[code].id, effect="grant"))
            print(f"  + 补充 grant：{code}")

        db.commit()
        print(f"\n✓ 已删除 {removed} 条 deny。")

        # 自检：算出有效权限
        role_codes = {p.perm_code for role in user.roles for p in role.permissions}
        grants = {c for c, r in (
            (code, db.query(UserPermission).filter(
                UserPermission.user_id == user.id,
                UserPermission.permission_id == perms[code].id,
                UserPermission.effect == "grant",
            ).first()) for code in perms
        ) if r}
        denies = {c for c, r in (
            (code, db.query(UserPermission).filter(
                UserPermission.user_id == user.id,
                UserPermission.permission_id == perms[code].id,
                UserPermission.effect == "deny",
            ).first()) for code in perms
        ) if r}
        effective = (role_codes | grants) - denies

        print("\n自检 —— 有效权限：")
        for code in RESTORE_CODES:
            print(f"  {'✓' if code in effective else '✗'} {code}")
        print(f"  {'✓' if 'ai:ocr:recognize' in effective else '✗'} ai:ocr:recognize（授予）")
        print(f"  有效权限总数：{len(effective)}")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(run())
