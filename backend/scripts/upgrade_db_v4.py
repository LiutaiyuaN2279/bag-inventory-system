r"""第五轮升级：AI 单据识别记录保留「所识别的原照片」。

运行：进入 backend 目录后执行  .venv/Scripts/python.exe scripts/upgrade_db_v4.py

说明：只加列 + 建上传目录，不写入任何默认数据、不新增权限码
（权限码由 setup_roles.py 统一维护）。

新增列：
  ai_ocr_records.image_path  归档原图的相对路径（相对 settings.UPLOAD_DIR）
  ai_ocr_records.image_ext   归档原图的扩展名（决定响应 Content-Type）

历史记录（升级前产生的）没有原图，image_path 为空串，
前端「照片」列会显示「未留存」而不是破图。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.core.config import settings
from app.core.database import Base, engine
from app.models.ai_ocr import AiOcrItem, AiOcrRecord  # noqa: F401  注册模型到 Base.metadata

TABLE = "ai_ocr_records"
COLUMNS = [
    # (列名, 列定义)：DEFAULT '' 保证已有行升级后不为 NULL
    ("image_path", "VARCHAR(255) DEFAULT ''"),
    ("image_ext", "VARCHAR(16) DEFAULT ''"),
]


def _has_column(conn, table: str, col: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == col for r in rows)


def upload_root() -> str:
    """归档目录的绝对路径（相对 backend 工作目录）。"""
    return os.path.abspath(settings.UPLOAD_DIR)


def run():
    print("[1/3] 确保表结构存在 ...")
    Base.metadata.create_all(bind=engine)
    cols = [c.name for c in AiOcrRecord.__table__.columns]
    for wanted in ("image_path", "image_ext"):
        if wanted not in cols:
            raise RuntimeError(f"模型缺少列 {wanted}，请检查 app/models/ai_ocr.py")

    print("[2/3] 补齐原图归档列 ...")
    with engine.begin() as conn:
        for col, ddl in COLUMNS:
            if _has_column(conn, TABLE, col):
                print(f"  - {TABLE}.{col} 已存在，跳过")
                continue
            conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {col} {ddl}"))
            print(f"  + {TABLE}.{col} 已添加")

    print("[3/3] 准备原图归档目录 ...")
    root = upload_root()
    os.makedirs(os.path.join(root, "ocr"), exist_ok=True)
    print(f"  - 归档目录：{root}")

    with engine.begin() as conn:
        after = [r[1] for r in conn.execute(text(f"PRAGMA table_info({TABLE})")).fetchall()]
        print(f"  - {TABLE} 列：{after}")
        has_img = conn.execute(text(
            "SELECT COUNT(*) FROM ai_ocr_records WHERE image_path IS NOT NULL AND image_path != ''"
        )).scalar()
        total = conn.execute(text("SELECT COUNT(*) FROM ai_ocr_records")).scalar()
        print(f"  - 识别记录：{total} 条，其中已留存原图 {has_img} 条（历史记录无原图属正常）")
    print("升级完成！")


if __name__ == "__main__":
    run()
