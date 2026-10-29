"""第七轮升级：操作日志全量记录 + 「操作日志仅管理员可见」（幂等）。

运行：进入 backend 目录后执行  .venv/Scripts/python.exe scripts/upgrade_db_v7_oplog.py

## 背景

`operation_logs` 原来只有 用户名/方法/路径/动作/IP/明细 六个字段，且中间件只记
POST / PUT / DELETE —— 查询、登录、失败请求全部看不到，事后无法回答「谁在什么时候
看了哪张单据」。本次升级做两件事：

1. 给 `operation_logs` 补 4 个审计字段：
   - `status_code`  HTTP 状态码（200 成功 / 4xx 无权限或参数错 / 5xx 服务异常）
   - `elapsed_ms`   服务端处理耗时
   - `query`        查询串（还原当时的筛选条件，如 ?page=1&status=fail）
   - `ua`           User-Agent（区分网页端 / 安卓 APK / 脚本）
   中间件改为记录**所有** /api/ 请求（含 GET 查询与登录），写操作还带 `detail` 业务明细。

2. 收紧「操作日志」权限：`system:log` **只授予 admin**。
   为什么：日志记录的是全系统每个账号的操作轨迹，属于管理审计资源；
   运营主管（manager）与报销审批岗（finance_approve / general_manager / maker /
   reviewer）只需看业务数据，不需要看别人的操作轨迹（且能看到审计轨迹的人
   也应是被审计对象之外的角色，保持审计独立性）。
   本脚本会撤销**除 admin 外**所有角色与用户级覆盖里的 `system:log`，重复执行无副作用。

## 与 setup_roles.py 的关系

`setup_roles.py` 会先 delete 再重建角色权限，因此本脚本必须排在**所有会授日志权限的
脚本之后**（reset_demo_data.py 把它放在链路末尾）。setup_roles / merge_reimburse_into_business
里已同步去掉 `system:log`，这里再做一次兜底，防止历史库残留。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import text

from app.core.database import SessionLocal, engine
from app.models.rbac import Permission, Role, RolePermission, User, UserPermission

PERM_CODE = "system:log"
PERM_NAME = "系统-操作日志"
PERM_MODULE = "system"

#: 允许查看操作日志的角色（只保留系统管理员）
ALLOWED_ROLES = {"admin"}

#: 需要补的列（列名 -> DDL 片段）
NEW_COLUMNS = [
    ("status_code", "INTEGER DEFAULT 0"),
    ("elapsed_ms", "INTEGER DEFAULT 0"),
    ("query", "VARCHAR(255) DEFAULT ''"),
    ("ua", "VARCHAR(255) DEFAULT ''"),
]

#: 日志页最常用的两个筛选维度各建一条复合索引（模型里也声明了，这里给老库补上）
NEW_INDEXES = [
    ("ix_operation_logs_username_created", "operation_logs (username, created_at)"),
    ("ix_operation_logs_status_created", "operation_logs (status_code, created_at)"),
]


def ensure_columns() -> None:
    """给 operation_logs 补审计字段；已存在则跳过。"""
    print("[1/4] 补 operation_logs 审计字段 ...")
    with engine.begin() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(operation_logs)"))}
        for name, ddl in NEW_COLUMNS:
            if name in cols:
                print(f"  · {name} 已存在，跳过")
                continue
            conn.execute(text(f"ALTER TABLE operation_logs ADD COLUMN {name} {ddl}"))
            print(f"  + {name} 已添加")


def ensure_indexes() -> None:
    """补「操作人 + 时间」「结果 + 时间」两条复合索引，避免日志页全表扫描。"""
    print("[2/4] 补 operation_logs 查询索引 ...")
    with engine.begin() as conn:
        existing = {r[0] for r in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='operation_logs'"
        ))}
        for name, target in NEW_INDEXES:
            if name in existing:
                print(f"  · {name} 已存在，跳过")
                continue
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {target}"))
            print(f"  + {name} 已创建")


def ensure_permission(db) -> Permission:
    print("[3/4] 核对权限码 ...")
    perm = db.query(Permission).filter(Permission.perm_code == PERM_CODE).first()
    if perm:
        print(f"  · {PERM_CODE} 已存在，跳过")
        return perm
    perm = Permission(perm_code=PERM_CODE, perm_name=PERM_NAME, module=PERM_MODULE)
    db.add(perm)
    db.flush()
    print(f"  + {PERM_CODE} 已添加")
    return perm


def restrict_to_admin(db, perm: Permission) -> None:
    """撤销除 admin 外所有角色 / 用户级覆盖中的 system:log。"""
    print("[4/4] 收紧权限：操作日志只给系统管理员 ...")
    # 角色级
    for rp in db.query(RolePermission).filter(RolePermission.permission_id == perm.id).all():
        role = db.get(Role, rp.role_id)
        if role and role.role_code in ALLOWED_ROLES:
            continue
        db.delete(rp)
        print(f"  - 撤销角色 {role.role_code if role else rp.role_id} 的 {PERM_CODE}")
    # 用户级覆盖（grant 与 deny 一并清掉，避免出现「个人被单独授权看日志」）
    for up in db.query(UserPermission).filter(UserPermission.permission_id == perm.id).all():
        user = db.get(User, up.user_id)
        if user and "admin" in {r.role_code for r in user.roles}:
            continue
        db.delete(up)
        print(f"  - 清除用户 {user.username if user else up.user_id} 的 {PERM_CODE} 覆盖")

    # 确保 admin 角色持有该权限
    admin_role = db.query(Role).filter(Role.role_code == "admin").first()
    if admin_role:
        exists = db.query(RolePermission).filter(
            RolePermission.role_id == admin_role.id,
            RolePermission.permission_id == perm.id,
        ).first()
        if not exists:
            db.add(RolePermission(role_id=admin_role.id, permission_id=perm.id))
            print(f"  + admin <- {PERM_CODE}")
    db.commit()

    holders = []
    for role in db.query(Role).all():
        if any(p.perm_code == PERM_CODE for p in role.permissions):
            holders.append(role.role_code)
    print(f"\n当前持有 {PERM_CODE} 的角色：{', '.join(sorted(holders)) or '（无）'}")


def run() -> int:
    ensure_columns()
    ensure_indexes()
    db = SessionLocal()
    try:
        perm = ensure_permission(db)
        restrict_to_admin(db, perm)
        print("升级完成！")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(run())
