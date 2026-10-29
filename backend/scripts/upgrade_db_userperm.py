r"""第五轮升级：新增「用户级权限覆盖」表 user_permissions 及索引。
运行：进入 backend 目录后执行  .venv/Scripts/python.exe scripts/upgrade_db_userperm.py
说明：只建表建索引，不写入任何默认数据、不新增权限码（权限码由 setup_roles.py 统一维护）。
      该表用于在角色权限之上对单个用户「额外授予（grant）」或「明确禁用（deny）」某项权限，
      有效权限 = (全部角色权限 ∪ grant) − deny。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.core.database import Base, engine
from app.models.rbac import UserPermission  # noqa: F401  注册模型到 Base.metadata

TABLE = "user_permissions"

# 建表/建索引 SQL（显式写出，便于人工核对；与 Base.metadata 定义保持一致）
CREATE_SQL = [
    """
    CREATE TABLE IF NOT EXISTS user_permissions (
        user_id        INTEGER NOT NULL,
        permission_id  INTEGER NOT NULL,
        effect         VARCHAR(8) NOT NULL DEFAULT 'grant',
        PRIMARY KEY (user_id, permission_id),
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (permission_id) REFERENCES permissions (id)
    )
    """,
]

INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS ix_user_permissions_user_id ON user_permissions (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_user_permissions_permission_id ON user_permissions (permission_id)",
]


def _table_exists(conn, table: str) -> bool:
    rows = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"), {"n": table}
    ).fetchall()
    return bool(rows)


def run():
    print("[1/3] 确保表结构存在 ...")
    # 优先用模型元数据建表（与代码定义严格一致，且幂等）
    Base.metadata.create_all(bind=engine)
    print(f"  - {TABLE} 已就绪")

    print("[2/3] 补齐建表/索引 SQL（兼容历史库缺表、缺索引的情况）...")
    with engine.begin() as conn:
        for sql in CREATE_SQL:
            conn.execute(text(sql))
        if not _table_exists(conn, TABLE):
            raise RuntimeError(f"建表失败：{TABLE} 不存在")
        before = {r[1] for r in conn.execute(text(f"PRAGMA index_list('{TABLE}')")).fetchall()}
        for sql in INDEX_SQL:
            conn.execute(text(sql))
            print(f"  + {sql[:88]} ...")
        after = {r[1] for r in conn.execute(text(f"PRAGMA index_list('{TABLE}')")).fetchall()}
        print(f"  - {TABLE} 索引：{sorted(after)}（原有 {sorted(before)}）")

    print("[3/3] 校验 ...")
    with engine.begin() as conn:
        cols = [r[1] for r in conn.execute(text(f"PRAGMA table_info({TABLE})")).fetchall()]
        print(f"  - {TABLE} 列：{cols}")
    print("升级完成！")


if __name__ == "__main__":
    run()
