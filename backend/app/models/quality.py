"""质检：来料质检(IQC) + 成品质检(FQC)。"""
from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, func

from app.core.database import Base


class IqcOrder(Base):
    """来料质检单（关联采购到货单）。"""
    __tablename__ = "iqc_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    qc_no = Column(String(32), unique=True, nullable=False, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    arrival_id = Column(Integer, nullable=True, index=True)      # 关联到货单
    status = Column(String(16), default="待检")                  # 待检/合格/不合格/让步接收
    inspector = Column(String(64), default="")
    remark = Column(String(255), default="")
    created_at = Column(DateTime, default=func.now())


class IqcItem(Base):
    __tablename__ = "iqc_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    iqc_id = Column(Integer, ForeignKey("iqc_orders.id"), nullable=False, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    sample_qty = Column(Float, default=0)       # 抽检数
    qualified_qty = Column(Float, default=0)    # 合格数
    result = Column(String(16), default="待检")  # 合格/不合格/让步接收
    remark = Column(String(255), default="")


class FqcOrder(Base):
    """成品质检单（成品入库前/库存抽检）。"""
    __tablename__ = "fqc_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    qc_no = Column(String(32), unique=True, nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    batch_no = Column(String(64), default="")
    check_qty = Column(Float, default=0)       # 检验数
    qualified_qty = Column(Float, default=0)
    status = Column(String(16), default="待检")
    inspector = Column(String(64), default="")
    remark = Column(String(255), default="")
    created_at = Column(DateTime, default=func.now())


class OperationLog(Base):
    """操作日志：记录写操作请求。

    detail 字段用于存放业务明细（JSON 字符串），例如报销模块的 AI 判读结论、
    所用模型、耗时、不一致项数、人工覆盖理由、制单员对 AI 草稿的修改等。
    实验要求"审计轨迹可追溯"——只有动作名而没有业务数据，事后无法复核对错。
    """
    __tablename__ = "operation_logs"

    #: 日志页最常用的两个筛选项（操作人、结果）各建一条复合索引，
    #: 单列 created_at 已有索引；复合索引让「某人某段时间」「只看失败」不必全表扫。
    __table_args__ = (
        Index("ix_operation_logs_username_created", "username", "created_at"),
        Index("ix_operation_logs_status_created", "status_code", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), default="")
    method = Column(String(8), default="")
    path = Column(String(255), default="")
    action = Column(String(64), default="")     # 业务动作描述
    ip = Column(String(64), default="")
    detail = Column(Text, default="")           # 业务明细（JSON）
    status_code = Column(Integer, default=0)    # HTTP 状态码（200/4xx/5xx）
    elapsed_ms = Column(Integer, default=0)     # 服务端处理耗时（毫秒）
    query = Column(String(255), default="")     # 查询串（?page=1&...），便于事后还原筛选条件
    ua = Column(String(255), default="")        # User-Agent，区分网页端 / 安卓 APK / 脚本
    created_at = Column(DateTime, default=func.now(), index=True)
