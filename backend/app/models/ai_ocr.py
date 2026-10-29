"""AI 单据识别（OCR）模型：识别记录 + 识别明细。

场景：上传送货单/发票/单据照片，OCR 提取「单号 / 供应商 / 物料 / 数量」，
经人工核对后可一键导入系统（生成采购到货单草稿并留档识别记录）。
"""
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, func

from app.core.database import Base


class AiOcrRecord(Base):
    """一次图片识别任务：留存原图信息、识别字段与导入结果。"""
    __tablename__ = "ai_ocr_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    image_name = Column(String(255), default="")          # 原始文件名
    image_size = Column(Integer, default=0)               # 原始字节数
    image_path = Column(String(255), default="")          # 归档原图的相对路径（相对 UPLOAD_DIR）
    image_ext = Column(String(16), default="")            # 归档原图的扩展名（用于响应 Content-Type）
    doc_type = Column(String(32), default="")             # 单据/发票/送货单
    doc_no = Column(String(64), default="")               # 识别出的单号
    supplier_name = Column(String(128), default="")       # 识别出的供应商名称
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)  # 匹配到的供应商
    order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True)  # 关联采购订单
    arrival_id = Column(Integer, nullable=True)           # 导入生成的到货单
    status = Column(String(16), default="待确认")          # 待确认/已导入
    provider = Column(String(32), default="")             # 识别引擎标识
    raw_text = Column(Text, default="")                   # 原始识别文本（便于排错）
    message = Column(String(255), default="")             # 识别/导入提示
    created_by = Column(String(64), default="")
    created_at = Column(DateTime, default=func.now())


class AiModelConfig(Base):
    """大模型接入档案：识别引擎的引擎类型 / 接口地址 / 模型名 / 密钥。

    设计成「多条档案 + 一条启用」而不是单行配置：
    演示时可以同时保存「通义千问-VL」「豆包视觉」「本地 vLLM」几套参数，
    点「启用」即时切换，不必改 .env 再重启后端。
    生效优先级：启用的档案 > .env（AI_OCR_*）> 引擎预设。
    """
    __tablename__ = "ai_model_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), default="")                 # 档案名，如「通义千问-VL」
    provider = Column(String(32), default="mock")         # mock/dashscope/ark/zhipu/openai/custom
    base_url = Column(String(255), default="")            # 留空用引擎预设
    model = Column(String(128), default="")               # 留空用引擎预设
    api_key = Column(String(255), default="")             # 明文存储，仅 admin 可读，接口返回脱敏
    timeout = Column(Integer, default=60)                 # 单次识别超时（秒）
    json_mode = Column(Boolean, default=True)             # 是否带 response_format=json_object
    retry = Column(Integer, default=1)                    # 网络异常/5xx 重试次数
    is_active = Column(Boolean, default=False)            # 当前启用（全表最多一条为 True）
    remark = Column(String(255), default="")
    created_by = Column(String(64), default="")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class AiOcrItem(Base):
    """识别明细：OCR 提取的物料行，material_id 为人工/自动匹配到的物料。"""
    __tablename__ = "ai_ocr_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    record_id = Column(Integer, ForeignKey("ai_ocr_records.id"), nullable=False, index=True)
    material_name = Column(String(128), default="")       # 识别出的物料名称
    spec = Column(String(128), default="")                # 规格
    unit = Column(String(16), default="")                 # 单位
    qty = Column(Float, default=0)                        # 数量
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=True)  # 匹配到的物料
    matched = Column(Boolean, default=False)              # 是否已成功匹配物料