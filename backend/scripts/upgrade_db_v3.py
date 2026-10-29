r"""第三轮升级：为审核类单据增加「驳回原因」字段。
运行：进入 backend 目录后执行  .venv/Scripts/python.exe scripts/upgrade_db_v3.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.core.database import Base, engine

TABLES = [
    "purchase_requisitions",
    "purchase_orders",
    "purchase_arrivals",
    "purchase_returns",
    "stocktakes",
    "bom_headers",
]


def _has_column(conn, table: str, col: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == col for r in rows)


def run():
    print("确保表结构存在 ...")
    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        for t in TABLES:
            if _has_column(conn, t, "reject_reason"):
                print(f"  - {t}.reject_reason 已存在，跳过")
                continue
            conn.execute(text(f'ALTER TABLE {t} ADD COLUMN reject_reason VARCHAR(255) DEFAULT ""'))
            print(f"  + {t}.reject_reason 已添加")
    print("升级完成！")


if __name__ == "__main__":
    run()
