"""数据库引擎与会话。SQLite 需关闭同线程限制。"""
import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

connect_args = {}
engine_kwargs = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    # 等待锁的秒数，避免并发写入直接抛 database is locked
    connect_args["timeout"] = 30
    # 数据库文件位于可移动磁盘时可能出现瞬时 I/O 故障，连接一旦失效，
    # 后续请求会持续报 disk I/O error。开启预检测可在取用连接前发现并自动重连。
    engine_kwargs["pool_pre_ping"] = True
    # 确保 data 目录存在
    db_path = settings.DATABASE_URL.replace("sqlite:///", "").replace("sqlite:////", "/")
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, future=True, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
        """SQLite 连接级优化。

        - `journal_mode=WAL`：读不阻塞写、写不阻塞读。操作日志由后台任务批量写入，
          若仍是默认的 rollback journal，写日志会把并发查询整体挡住。
        - `synchronous=NORMAL`：WAL 下仍然安全（断电最多丢最后一批事务），但快很多。
        - `busy_timeout`：写锁冲突时最多等 10 秒，而不是立刻抛 database is locked。
        """
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=10000")
        finally:
            cur.close()


def get_db():
    """FastAPI 依赖：提供数据库会话并自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
