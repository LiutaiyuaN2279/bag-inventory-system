r"""第四轮升级：新增「仓库调拨」两张表（调拨单 + 调拨明细）及索引。
运行：进入 backend 目录后执行  .venv/Scripts/python.exe scripts/upgrade_db_transfer.py
说明：只建表建索引，不写入任何默认数据、不新增权限码（权限码由 setup_roles.py 统一维护）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.core.database import Base, engine
from app.models.inventory import TransferItem, TransferOrder  # noqa: F401  注册模型到 Base.metadata

TABLES = ["transfer_orders", "transfer_items"]

# 建表/建索引 SQL（显式写出，便于人工核对；与 Base.metadata 定义保持一致）
CREATE_SQL = [
    # 调拨单：单号唯一
    """
    CREATE TABLE IF NOT EXISTS transfer_orders (
        id                 INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
        transfer_no        VARCHAR(32) NOT NULL,
        from_warehouse_id  INTEGER NOT NULL,
        to_warehouse_id    INTEGER NOT NULL,
        status             VARCHAR(16) DEFAULT '草稿',
        executed           BOOLEAN DEFAULT 0,
        operator           VARCHAR(64) DEFAULT '',
        remark             VARCHAR(255) DEFAULT '',
        created_at         DATETIME,
        updated_at         DATETIME,
        approve_time       DATETIME,
        void_time          DATETIME
    )
    """,
    # 调拨明细：按单号（transfer_id）查明细的索引
    """
    CREATE TABLE IF NOT EXISTS transfer_items (
        id                INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
        transfer_id       INTEGER NOT NULL,
        material_id       INTEGER NOT NULL,
        color_batch_id    INTEGER,
        qty               FLOAT DEFAULT 0,
        unit              VARCHAR(16) DEFAULT '个',
        from_location_id  INTEGER,
        to_location_id    INTEGER,
        remark            VARCHAR(255) DEFAULT ''
    )
    """,
]

INDEX_SQL = [
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_transfer_orders_transfer_no ON transfer_orders (transfer_no)",
    "CREATE INDEX IF NOT EXISTS ix_transfer_orders_from_warehouse_id ON transfer_orders (from_warehouse_id)",
    "CREATE INDEX IF NOT EXISTS ix_transfer_orders_to_warehouse_id ON transfer_orders (to_warehouse_id)",
    "CREATE INDEX IF NOT EXISTS ix_transfer_items_transfer_id ON transfer_items (transfer_id)",
]


def _table_exists(conn, table: str) -> bool:
    rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"), {"n": table}).fetchall()
    return bool(rows)


def run():
    print("[1/3] 确保表结构存在 ...")
    # 优先用模型元数据建表（与代码定义严格一致，且幂等）
    Base.metadata.create_all(bind=engine)
    for t in TABLES:
        print(f"  - {t} 已就绪")

    print("[2/3] 补齐建表/索引 SQL（兼容历史库缺表、缺索引的情况）...")
    with engine.begin() as conn:
        for sql in CREATE_SQL:
            conn.execute(text(sql))
        for t in TABLES:
            if not _table_exists(conn, t):
                raise RuntimeError(f"建表失败：{t} 不存在")
        before = {r[1] for r in conn.execute(text("PRAGMA index_list('transfer_orders')")).fetchall()}
        for sql in INDEX_SQL:
            conn.execute(text(sql))
            print(f"  + {sql[:88]} ...")
        after = {r[1] for r in conn.execute(text("PRAGMA index_list('transfer_orders')")).fetchall()}
        print(f"  - transfer_orders 索引：{sorted(after)}（原有 {sorted(before)}）")

    print("[3/3] 校验 ...")
    with engine.begin() as conn:
        for t in TABLES:
            cols = [r[1] for r in conn.execute(text(f"PRAGMA table_info({t})")).fetchall()]
            print(f"  - {t} 列：{cols}")
    print("升级完成！")


if __name__ == "__main__":
    run()
