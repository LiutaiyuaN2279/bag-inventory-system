"""BOM 模型：多版本 BOM 主表 + 明细（含裁床损耗率）。"""
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, func

from app.core.database import Base


class BomHeader(Base):
    __tablename__ = "bom_headers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("materials.id"), nullable=False, index=True)
    version = Column(String(32), nullable=False)          # 版本号 V1.0
    version_name = Column(String(64), default="")          # 版本说明 试产/量产
    status = Column(String(16), default="草稿")            # 草稿/生效/失效/已驳回
    reject_reason = Column(String(255), default="")        # 驳回原因
    effective_date = Column(String(16), default="")
    default_loss_rate = Column(Float, default=0)           # 默认裁床损耗率%
    remark = Column(String(255), default="")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class BomItem(Base):
    __tablename__ = "bom_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bom_id = Column(Integer, ForeignKey("bom_headers.id"), nullable=False, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    qty = Column(Float, default=0)                         # 单耗用量
    loss_rate = Column(Float, default=0)                   # 损耗率%
    unit = Column(String(16), default="个")
    is_substitute = Column(Boolean, default=False)         # 是否替代料
    substitute_for = Column(Integer, nullable=True)        # 被替代的明细行
    remark = Column(String(255), default="")
