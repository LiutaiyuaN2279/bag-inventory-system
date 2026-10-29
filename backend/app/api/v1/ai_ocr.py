"""AI 单据识别：上传送货单/发票/单据照片 → OCR 提取单号/供应商/物料/数量 → 核对导入。

- POST /ai-ocr/recognize        上传图片识别，落库识别记录（状态：待确认）
- GET  /ai-ocr/records          识别记录列表
- GET  /ai-ocr/records/{id}     识别记录详情（含明细）
- GET  /ai-ocr/records/{id}/image  取回该记录识别时的原照片（归档在 data/uploads/ocr/）
- POST /ai-ocr/records/{id}/import  确认导入：留档识别结果；条件满足时生成采购到货单（待验收）
- DELETE /ai-ocr/records/{id}   删除识别记录（连同归档原图）
- GET  /ai-ocr/info             识别引擎信息（供前端提示当前是否为演示模式）
- GET  /ai-ocr/model-configs    大模型配置列表（档案 + 引擎预设 + 当前生效来源）
- POST /ai-ocr/model-configs    新增模型档案（第一条自动启用）
- PUT  /ai-ocr/model-configs/{id}      修改档案
- POST /ai-ocr/model-configs/{id}/activate  启用档案（即时生效，无需重启）
- POST /ai-ocr/model-configs/{id}/test      测试该档案连通性（不必先启用）
- DELETE /ai-ocr/model-configs/{id}   删除档案（删启用项则回落 .env）

原图归档：识别成功时把上传的图片落到 `settings.UPLOAD_DIR/ocr/`，
记录里只存相对路径（`image_path`），因此「历史记录」在升级后没有原图是正常的，
前端对该情况显示「未留存」而不是破图。
"""
import os

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api._batch import run_batch_guarded
from app.api._helpers import load_maps
from app.api.deps import get_current_user, require_permissions
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import BizException
from app.crud.crud_base import apply_ordering
from app.models.ai_ocr import AiModelConfig, AiOcrItem, AiOcrRecord
from app.models.master_data import Material, Supplier
from app.models.procurement import PurchaseOrder, PurchaseOrderItem
from app.models.rbac import User
from app.schemas.ai_ocr import AiModelConfigIn, OcrImport
from app.schemas.batch import BatchIn
from app.services import ai_model_config, file_store, ocr_service
from app.services.arrival_service import create_arrival as build_arrival
from app.utils.response import page_result, success

router = APIRouter(prefix="/ai-ocr", tags=["AI-单据识别"])

_IMAGE_EXTS = ("jpg", "jpeg", "png", "bmp", "webp", "gif", "tif", "tiff")


def _match_supplier(db: Session, name: str) -> int | None:
    """按名称匹配供应商：精确 → 模糊 → 反向包含。"""
    name = (name or "").strip()
    if not name:
        return None
    s = db.query(Supplier).filter(Supplier.supplier_name == name).first()
    if s:
        return s.id
    s = db.query(Supplier).filter(Supplier.supplier_name.like(f"%{name}%")).first()
    if s:
        return s.id
    for x in db.query(Supplier).all():
        nm = x.supplier_name or ""
        if nm and (name in nm or nm in name):
            return x.id
    return None


def _match_material(db: Session, name: str) -> int | None:
    """按物料名称匹配：精确 → 模糊 → 反向包含。"""
    name = (name or "").strip()
    if not name:
        return None
    m = db.query(Material).filter(Material.material_name == name).first()
    if m:
        return m.id
    m = db.query(Material).filter(Material.material_name.like(f"%{name}%")).first()
    if m:
        return m.id
    for x in db.query(Material).all():
        nm = x.material_name or ""
        if nm and (name in nm or nm in name):
            return x.id
    return None


def _item_dict(it: AiOcrItem, mats: dict) -> dict:
    return {
        "id": it.id, "material_name": it.material_name, "spec": it.spec, "unit": it.unit,
        "qty": it.qty, "material_id": it.material_id, "matched": bool(it.material_id),
        "matched_name": mats.get(it.material_id, ""),
    }


def _record_dict(db: Session, r: AiOcrRecord, with_items: bool = False, maps=None) -> dict:
    mats, _, sups = maps if maps else load_maps(db)
    # has_image：原图是否真的还在磁盘上。历史记录 image_path 为空、
    # 或归档文件被手工清理，都会是 False，前端据此显示「未留存」而非破图。
    # image_url 与 has_image 保持一致口径，避免前端拿到一个必然 404 的地址。
    has_image = file_store.exists(r.image_path)
    data = {
        "id": r.id, "image_name": r.image_name, "image_size": r.image_size,
        "image_path": r.image_path or "",
        "has_image": has_image,
        "image_url": f"/api/v1/ai-ocr/records/{r.id}/image" if has_image else "",
        "doc_type": r.doc_type, "doc_no": r.doc_no,
        "supplier_name": r.supplier_name, "supplier_id": r.supplier_id,
        "supplier_matched_name": sups.get(r.supplier_id, ""),
        "order_id": r.order_id, "arrival_id": r.arrival_id, "status": r.status,
        "provider": r.provider, "message": r.message, "raw_text": r.raw_text,
        "created_by": r.created_by, "created_at": str(r.created_at)[:19],
    }
    if with_items:
        items = db.query(AiOcrItem).filter(AiOcrItem.record_id == r.id).order_by(AiOcrItem.id).all()
        data["items"] = [_item_dict(i, mats) for i in items]
    return data


def _do_delete_record(db: Session, rid: int) -> None:
    """删除识别记录业务核心：校验存在性与「已生成到货单不可删」→ 先删明细再删主表。

    不 commit，由调用方（单条端点 / 批量执行器）统一提交。
    明细为手动删除（模型未配置 ORM 级联），必须一并清理，避免留下孤儿明细。

    归档原图也在删行之前一并删除：数据库里已经没有记录指向它，留着只会占磁盘。
    这里不做「等 commit 成功再删文件」的两段式 —— 万一本条后续提交失败，
    该记录只会退化成「原图未留存」（前端已有该文案），不会产生破图或报错。
    """
    rec = db.get(AiOcrRecord, rid)
    if not rec:
        raise BizException("识别记录不存在")
    if rec.arrival_id:
        raise BizException("该识别记录已生成到货单，请先处理到货单后再删除")
    file_store.remove(rec.image_path)
    db.query(AiOcrItem).filter(AiOcrItem.record_id == rid).delete()
    db.delete(rec)


# ---------------- 批量操作 ----------------
# 只做 delete：批量 import（生成到货单）会一次性新建多张到货单且明细需人工核对，风险过高，不开放。
# 注意：必须声明在任何 {rid} 形式的动态路由之前，否则 batch 会被当成 id 匹配。
BATCH_PERMS = {
    "delete": "ai:ocr:delete",
}


def _one_ocr_record(db: Session, item_id: int, action: str) -> None:
    """单条批量动作：取对象 → 校验 → 删除（不 commit，由 run_batch 统一提交）。"""
    if action == "delete":
        _do_delete_record(db, item_id)
    else:
        raise BizException(f"不支持的批量动作：{action}")


@router.post("/batch")
def batch_ocr_records(payload: BatchIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """批量删除识别记录（逐条独立事务，返回失败明细）。"""
    return run_batch_guarded(db, user, payload, BATCH_PERMS, _one_ocr_record)


@router.get("/info")
def info(_=Depends(require_permissions("ai:ocr:list"))):
    cfg = ocr_service.resolved_config()
    return success({
        "provider": cfg["provider"],
        "is_remote": cfg["is_remote"],
        "model": cfg["model"],
        "base_url": cfg["base_url"],
        "key_configured": bool(cfg["api_key"]),
        # source：配置来自「界面里的模型档案」还是 .env，前端据此给出不同提示
        "source": cfg.get("source", "env"),
        "config_name": cfg.get("config_name", ""),
        "doc_types": list(ocr_service.DOC_TYPES),
        "max_mb": settings.AI_OCR_MAX_MB,
    })


@router.post("/test")
def test_connection(_=Depends(require_permissions("ai:ocr:list"))):
    """测试当前生效的识别引擎是否可用。"""
    return success(ocr_service.test_connection())


# ---------------- 大模型配置（模型档案） ----------------
# 为什么单独做一层：识别引擎的地址/模型/密钥原来只能写死在 backend/.env，
# 换一家模型就要改文件 + 重启后端。这里改成「界面里保存多份档案、点启用即时切换」，
# 识别服务每次调用从启用档案读参数（见 app/services/ai_model_config.py）。
CONFIG_PERM = require_permissions("ai:ocr:config")


def _get_config(db: Session, cid: int):
    row = db.get(AiModelConfig, cid)
    if not row:
        raise BizException("模型配置不存在")
    return row


def _apply_config(row: AiModelConfig, data: AiModelConfigIn) -> None:
    """把请求体写进档案；api_key 为 None 表示保持原值（编辑时前端不回传脱敏值）。"""
    row.name = (data.name or "").strip()[:64] or row.name or "未命名配置"
    row.provider = (data.provider or "mock").strip().lower()[:32]
    row.base_url = (data.base_url or "").strip()[:255]
    row.model = (data.model or "").strip()[:128]
    if data.api_key is not None:
        row.api_key = (data.api_key or "").strip()[:255]
    row.timeout = int(data.timeout)
    row.json_mode = bool(data.json_mode)
    row.retry = int(data.retry)
    row.remark = (data.remark or "").strip()[:255]


@router.get("/model-configs")
def list_model_configs(db: Session = Depends(get_db), _=Depends(CONFIG_PERM)):
    """模型档案列表：档案清单 + 各引擎预设 + 当前生效来源。"""
    rows = db.query(AiModelConfig).order_by(AiModelConfig.is_active.desc(), AiModelConfig.id).all()
    active = next((r for r in rows if r.is_active), None)
    engine = ocr_service.resolved_config()
    return success({
        "list": [ai_model_config.to_dict(r) for r in rows],
        "active_id": active.id if active else None,
        # 没有任何档案启用时，识别实际用的是 .env，这里如实告诉前端
        "source": engine.get("source", "env"),
        "env_engine": {
            "provider": engine["provider"], "model": engine["model"],
            "base_url": engine["base_url"], "is_remote": engine["is_remote"],
            "key_configured": bool(engine["api_key"]),
        },
        "presets": ai_model_config.provider_options(),
    })


@router.post("/model-configs")
def create_model_config(data: AiModelConfigIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user), _=Depends(CONFIG_PERM)):
    """新增模型档案；第一条档案自动启用，省去「新建完还要再点一次启用」。"""
    row = AiModelConfig(created_by=user.username)
    _apply_config(row, data)
    if not row.name:
        row.name = row.model or "未命名配置"
    db.add(row)
    db.flush()
    if db.query(AiModelConfig).filter(AiModelConfig.is_active.is_(True)).count() == 0:
        row.is_active = True
    db.commit()
    ai_model_config.invalidate_cache()
    db.refresh(row)
    return success(ai_model_config.to_dict(row), message="模型配置已保存")


@router.put("/model-configs/{cid}")
def update_model_config(cid: int, data: AiModelConfigIn, db: Session = Depends(get_db),
                        _=Depends(CONFIG_PERM)):
    row = _get_config(db, cid)
    _apply_config(row, data)
    db.commit()
    ai_model_config.invalidate_cache()
    db.refresh(row)
    return success(ai_model_config.to_dict(row), message="模型配置已更新")


@router.post("/model-configs/{cid}/activate")
def activate_model_config(cid: int, db: Session = Depends(get_db), _=Depends(CONFIG_PERM)):
    """启用某份档案：同表只保留一条 is_active，其它先置 False（避免出现双启用）。"""
    row = _get_config(db, cid)
    db.query(AiModelConfig).filter(AiModelConfig.id != cid).update({"is_active": False})
    row.is_active = True
    db.commit()
    ai_model_config.invalidate_cache()
    return success(ai_model_config.to_dict(row), message=f"已启用「{row.name}」")


@router.post("/model-configs/{cid}/test")
def test_model_config(cid: int, db: Session = Depends(get_db), _=Depends(CONFIG_PERM)):
    """测试某份档案的连通性（不要求先启用，配错也不会影响线上识别）。"""
    row = _get_config(db, cid)
    return success(ocr_service.test_connection(ai_model_config.describe(row)))


@router.delete("/model-configs/{cid}")
def delete_model_config(cid: int, db: Session = Depends(get_db), _=Depends(CONFIG_PERM)):
    """删除档案。删掉的若是当前启用项，识别会自动回落到 .env 配置。"""
    row = _get_config(db, cid)
    was_active = bool(row.is_active)
    db.delete(row)
    db.commit()
    ai_model_config.invalidate_cache()
    return success(message=f"已删除「{row.name}」" + ("，识别已回落到 .env 配置" if was_active else ""))


@router.get("/records")
def list_records(page: int = 1, page_size: int = 20, keyword: str | None = None,
                 status: str | None = None, sort_by: str | None = None,
                 sort_order: str | None = None, db: Session = Depends(get_db),
                 _=Depends(require_permissions("ai:ocr:list"))):
    q = db.query(AiOcrRecord)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter((AiOcrRecord.doc_no.like(like)) | (AiOcrRecord.supplier_name.like(like)))
    if status:
        q = q.filter(AiOcrRecord.status == status)
    total = q.count()
    rows = apply_ordering(q, AiOcrRecord, sort_by, sort_order).offset((page - 1) * page_size).limit(page_size).all()
    maps = load_maps(db)
    data = []
    for r in rows:
        d = _record_dict(db, r, maps=maps)
        items = db.query(AiOcrItem).filter(AiOcrItem.record_id == r.id).order_by(AiOcrItem.id).all()
        d["item_count"] = len(items)
        d["matched_count"] = sum(1 for i in items if i.material_id)
        data.append(d)
    return success(page_result(data, total))


@router.get("/records/{rid}")
def detail_record(rid: int, db: Session = Depends(get_db), _=Depends(require_permissions("ai:ocr:list"))):
    r = db.get(AiOcrRecord, rid)
    if not r:
        raise BizException("识别记录不存在")
    return success(_record_dict(db, r, with_items=True))


@router.get("/records/{rid}/image")
def record_image(rid: int, db: Session = Depends(get_db), _=Depends(require_permissions("ai:ocr:list"))):
    """取回识别时的原照片（内联展示用）。

    归档文件按相对路径存放在 `settings.UPLOAD_DIR` 下，这里解析成绝对路径后直接回文件。
    图片是用户自己上传的单据照片，不含他人隐私，因此不做「按记录创建人隔离」；
    访问仍受 `ai:ocr:list` 权限码约束（与列表/详情一致）。
    """
    r = db.get(AiOcrRecord, rid)
    if not r:
        raise BizException("识别记录不存在")
    path = file_store.resolve(r.image_path)
    if not path or not os.path.isfile(path):
        raise BizException("该识别记录未留存原图（可能上传于升级前，或归档文件已被清理）")
    return FileResponse(
        path,
        media_type=file_store.content_type_of(r.image_path or r.image_name),
        # inline：浏览器/el-image 直接展示；filename 用原始文件名，另存时保留可读名字
        content_disposition_type="inline",
        filename=r.image_name or os.path.basename(path),
    )


@router.post("/recognize")
async def recognize(file: UploadFile = File(...), db: Session = Depends(get_db),
                    user: User = Depends(get_current_user),
                    _=Depends(require_permissions("ai:ocr:recognize"))):
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    if not (file.content_type or "").startswith("image/") and ext not in _IMAGE_EXTS:
        raise BizException("仅支持上传图片文件（jpg/png/bmp/webp 等）")
    image_bytes = await file.read()
    result = ocr_service.recognize(image_bytes, filename=file.filename or "",
                                   content_type=file.content_type or "")
    mats, _, _ = load_maps(db)
    supplier_id = _match_supplier(db, result["supplier_name"])
    try:
        rec = AiOcrRecord(
            image_name=file.filename or "", image_size=len(image_bytes),
            doc_type=result["doc_type"], doc_no=result["doc_no"],
            supplier_name=result["supplier_name"], supplier_id=supplier_id,
            status="待确认", provider=result["provider"], raw_text=result["raw_text"],
            created_by=user.username,
        )
        db.add(rec)
        db.flush()          # 先拿到自增 id，再用它命名归档文件
        # 归档原图：写失败会返回空路径，识别本身仍然成功（前端显示「未留存」）
        rel, ext = file_store.save_image(
            image_bytes, file.filename or "", file.content_type or "", ref=rec.id)
        rec.image_path = rel
        rec.image_ext = ext
        for it in result["items"]:
            mid = _match_material(db, it["material_name"])
            db.add(AiOcrItem(
                record_id=rec.id, material_name=it["material_name"], spec=it["spec"],
                unit=it["unit"], qty=it["qty"], material_id=mid, matched=bool(mid)))
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(rec)
    return success(_record_dict(db, rec, with_items=True), message="识别完成，请核对后导入")


@router.post("/records/{rid}/import")
def import_record(rid: int, data: OcrImport, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user),
                  _=Depends(require_permissions("ai:ocr:import"))):
    rec = db.get(AiOcrRecord, rid)
    if not rec:
        raise BizException("识别记录不存在")
    if rec.arrival_id:
        raise BizException("该识别记录已生成到货单，请勿重复导入")

    # 1) 回写确认后的单据信息
    if data.doc_no is not None:
        rec.doc_no = (data.doc_no or "").strip()[:64]
    if data.doc_type:
        rec.doc_type = data.doc_type.strip()[:32]
    if data.supplier_name is not None:
        rec.supplier_name = (data.supplier_name or "").strip()[:128]
    if data.supplier_id:
        rec.supplier_id = data.supplier_id
    elif rec.supplier_name:
        rec.supplier_id = _match_supplier(db, rec.supplier_name)

    # 2) 回写明细（按 id 定位；前端未带 id 的行按新增处理）
    existing = {i.id: i for i in db.query(AiOcrItem).filter(AiOcrItem.record_id == rid).all()}
    keep_ids = []
    try:
        for it in data.items or []:
            iid = it.get("id")
            target = existing.get(iid) if iid else None
            if target is None:
                target = AiOcrItem(record_id=rid)
                db.add(target)
            try:
                target.qty = float(it.get("qty") or 0)
            except (TypeError, ValueError):
                raise BizException("明细数量格式不正确")
            target.spec = str(it.get("spec") or "")[:128]
            target.unit = str(it.get("unit") or "")[:16]
            if it.get("material_name") is not None:
                target.material_name = str(it.get("material_name"))[:128]
            mid = it.get("material_id") or _match_material(db, target.material_name)
            target.material_id = mid
            target.matched = bool(mid)
            keep_ids.append(target)
        db.flush()
        # 删除前端已移除的旧明细
        for iid, obj in existing.items():
            if obj not in keep_ids:
                db.delete(obj)
        db.flush()

        # 3) 条件满足时生成采购到货单（待验收）
        items = db.query(AiOcrItem).filter(AiOcrItem.record_id == rid).order_by(AiOcrItem.id).all()
        arrival_no = ""
        if data.order_id and data.warehouse_id:
            if not items:
                raise BizException("识别明细为空，无法生成到货单")
            missing = [i.material_name or f"第{i.id}行" for i in items if not i.material_id]
            if missing:
                raise BizException("以下明细未匹配到物料，无法生成到货单：" + "、".join(missing))
            if not db.get(PurchaseOrder, data.order_id):
                raise BizException("采购订单不存在")
            # 物料 → 订单明细：取该订单中同物料、尚未使用的首条明细
            order_items = db.query(PurchaseOrderItem).filter(
                PurchaseOrderItem.order_id == data.order_id).order_by(PurchaseOrderItem.id).all()
            used = set()
            arr_items = []
            for i in items:
                if i.qty <= 0:
                    raise BizException(f"物料「{i.material_name}」数量必须大于 0")
                oi = next((o for o in order_items
                           if o.material_id == i.material_id and o.id not in used), None)
                if not oi:
                    raise BizException(f"订单中不包含物料「{i.material_name}」，无法登记到货")
                used.add(oi.id)
                arr_items.append({
                    "order_item_id": oi.id, "arrived_qty": i.qty,
                    "qualified_qty": i.qty, "warehouse_id": data.warehouse_id,
                })
            note = data.remark or f"AI识别导入（{rec.doc_no or rec.image_name}）"
            arr = build_arrival(db, data.order_id, arr_items, note)
            rec.arrival_id = arr.id
            arrival_no = arr.arrival_no

        rec.status = "已导入"
        rec.message = f"已生成到货单 {arrival_no}" if arrival_no else "识别结果已留档"
        db.commit()
    except Exception:
        db.rollback()
        raise
    return success({"id": rec.id, "arrival_id": rec.arrival_id, "arrival_no": arrival_no},
                   message=rec.message)


@router.delete("/records/{rid}")
def delete_record(rid: int, db: Session = Depends(get_db),
                  _=Depends(require_permissions("ai:ocr:delete"))):
    """删除识别记录（连同识别明细一起删除）。"""
    try:
        _do_delete_record(db, rid)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return success(message="已删除")