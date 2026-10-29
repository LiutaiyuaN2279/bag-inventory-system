"""把演示数据的业务时间整体平移到「今天」，让看板的今日/近 7 天数据重新有值。

运行：进入 backend 目录后执行
    .venv/Scripts/python.exe scripts/refresh_demo_dates.py

## 背景

`seed_data.py` 用 `TODAY = datetime.now()` 锚定「今天」生成数据，所以刚灌完库时
看板的「今日入库 / 近 7 天趋势」都有值。但演示库一旦放几天，数据日期就停在灌库那天，
看板趋势全变成 0 —— 看起来像功能坏了，其实只是数据陈旧。

## 为什么不用 reset_demo_data.py

`reset_demo_data.py` 会**删库重建**，而它只执行 9 个脚本（init_db / upgrade_* / seed_data /
setup_roles），**只创建 5 个基础账号**（admin / manager / buyer / keeper / qc）。
另外 7 个报销账号（gm / finance / finmaker / director / depthead / sales / tech）
与报销业务数据由 `add_reimburse_users.py`、`add_approval_roles.py` 等独立脚本追加，
不在重置链路里 —— 直接重灌会把这 7 个账号和全部报销数据一起抹掉。

本脚本只**平移时间字段**，不动任何业务记录、账号与权限，等价于「把旧数据挪到当前时间轴」。

## 做法

1. 取业务表里最大的时间戳作为「数据锚点」；
2. 计算 锚点 → 今天 的整数天差 delta；
3. 把所有业务时间字段整体 +delta 天（datetime 与纯 date 两种格式分别处理）。

delta <= 0 时不做任何修改（数据已经是最新的），因此可以反复执行。
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.config import settings  # noqa: E402

#: (表名, 时间列, 格式) —— 格式 datetime = 'YYYY-MM-DD HH:MM:SS[.ffffff]'；date = 'YYYY-MM-DD'
#: 只列业务表：账号、角色、权限、报销模块的数据不动（它们与采购库存的时间轴无关）。
TIME_COLUMNS = [
    ("inventory_transactions", "txn_time", "datetime"),
    ("inventory", "last_move_date", "date"),
    ("purchase_requisitions", "created_at", "datetime"),
    ("purchase_requisitions", "updated_at", "datetime"),
    ("purchase_requisition_items", "requirement_date", "date"),
    ("purchase_orders", "created_at", "datetime"),
    ("purchase_orders", "updated_at", "datetime"),
    ("purchase_arrivals", "created_at", "datetime"),
    ("purchase_returns", "created_at", "datetime"),
    ("iqc_orders", "created_at", "datetime"),
    ("fqc_orders", "created_at", "datetime"),
    ("outsource_orders", "created_at", "datetime"),
    ("stocktakes", "created_at", "datetime"),
    ("transfer_orders", "created_at", "datetime"),
    ("transfer_orders", "updated_at", "datetime"),
    ("transfer_orders", "approve_time", "datetime"),
    ("transfer_orders", "void_time", "datetime"),
    ("materials", "created_at", "datetime"),
    ("materials", "updated_at", "datetime"),
    ("suppliers", "created_at", "datetime"),
    ("suppliers", "updated_at", "datetime"),
    ("warehouses", "created_at", "datetime"),
    ("warehouses", "updated_at", "datetime"),
    ("bom_headers", "created_at", "datetime"),
    ("bom_headers", "updated_at", "datetime"),
    ("locations", "created_at", "datetime"),
    ("material_color_batches", "created_at", "datetime"),
    ("operation_logs", "created_at", "datetime"),
    ("ai_ocr_records", "created_at", "datetime"),
]

#: 用来判定「数据有多旧」的锚点列：(表, 列)
ANCHORS = [
    ("inventory_transactions", "txn_time"),
    ("purchase_orders", "created_at"),
    ("purchase_arrivals", "created_at"),
    ("iqc_orders", "created_at"),
]


def resolve_db_path() -> str:
    url = settings.DATABASE_URL
    if not url.startswith("sqlite"):
        raise SystemExit(f"当前仅支持 SQLite 演示库，实际为：{url}")
    path = url.split("///", 1)[-1]
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(base, path))


def parse_dt(value: str):
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt), fmt
        except ValueError:
            continue
    return None, None


def shift(value: str, days: int) -> str:
    """按原格式平移 days 天；无法解析的值原样返回。"""
    dt, fmt = parse_dt(value)
    if dt is None:
        return value
    return (dt + timedelta(days=days)).strftime(fmt)


def run() -> int:
    import sqlite3

    db_path = resolve_db_path()
    if not os.path.exists(db_path):
        raise SystemExit(f"数据库不存在：{db_path}")

    conn = sqlite3.connect(db_path)
    try:
        # 1) 找数据锚点
        latest = None
        for table, col in ANCHORS:
            row = conn.execute(f"select max({col}) from {table}").fetchone()
            if not row or not row[0]:
                continue
            dt, _ = parse_dt(str(row[0]))
            if dt and (latest is None or dt > latest[0]):
                latest = (dt, f"{table}.{col}")

        if latest is None:
            raise SystemExit("✗ 找不到任何业务时间数据，请先运行 seed_data.py")

        today = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        delta = (today.date() - latest[0].date()).days
        print(f"数据锚点：{latest[1]} = {latest[0]}")
        print(f"当前日期：{today:%Y-%m-%d}")
        print(f"相差：{delta} 天")

        if delta <= 0:
            print("✓ 数据已经是当前时间轴，无需平移。")
            return 0

        # 2) 逐列平移
        print(f"\n开始平移，+{delta} 天 ...")
        total = 0
        for table, col, _kind in TIME_COLUMNS:
            rows = conn.execute(
                f"select id, {col} from {table} where {col} is not null and {col} <> ''"
            ).fetchall()
            if not rows:
                continue
            updates = []
            for rid, val in rows:
                new_val = shift(str(val), delta)
                if new_val != str(val):
                    updates.append((new_val, rid))
            if updates:
                conn.executemany(f"update {table} set {col} = ? where id = ?", updates)
                total += len(updates)
                print(f"  {table}.{col:<16} {len(updates):>5} 行")

        conn.commit()
        print(f"\n✓ 平移完成，共更新 {total} 个时间值。")

        # 3) 自检：近 7 天是否有数据
        print("\n自检（近 7 天数据量）：")
        start = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
        checks = [
            ("inventory_transactions", "txn_time", "出入库流水"),
            ("purchase_orders", "created_at", "采购订单"),
            ("purchase_arrivals", "created_at", "到货单"),
            ("iqc_orders", "created_at", "来料质检"),
        ]
        ok = True
        for table, col, label in checks:
            n = conn.execute(
                f"select count(*) from {table} where date({col}) >= ?", (start,)
            ).fetchone()[0]
            flag = "✓" if n > 0 else "✗"
            if n == 0:
                ok = False
            print(f"  {flag} {label}({table}): {n} 条")
        if not ok:
            print("  ! 有表近 7 天无数据，看板对应趋势可能仍为 0（演示数据本身的分布所致）。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(run())
