"""物料管理接口（含色号缸号字段）。"""
import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api._batch import run_batch_guarded
from app.api.deps import get_current_user, require_permissions
from app.core.database import get_db
from app.core.exceptions import BizException
from app.crud.crud_base import CRUDBase
from app.models.master_data import Material
from app.models.rbac import User
from app.schemas.batch import BatchIn
from app.schemas.master_data import MaterialCreate, MaterialUpdate
from app.utils.response import page_result, success

router = APIRouter(prefix="/materials", tags=["物料管理"])
crud = CRUDBase(Material)

SEARCH_FIELDS = ["material_code", "material_name", "category"]

# 分类 → 编码前缀（与现有物料编码格式保持一致）
CATEGORY_PREFIX = {
    "面料": "M-面料", "里料": "M-里料", "辅料": "M-辅料",
    "五金": "M-五金", "包材": "M-包材", "成品": "P-BG",
}


@router.get("/suggest-code")
def suggest_code(
    category: str | None = Query(None),
    name: str | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(require_permissions("basic:material:list")),
):
    """按分类生成与现有格式统一的建议物料编码：M-面料-001 / P-BG-001。序号在同分类内递增。"""
    prefix = CATEGORY_PREFIX.get((category or "").strip(), "M-其它")
    base = prefix + "-"
    rows = db.query(Material.material_code).filter(Material.material_code.like(base + "%")).all()
    max_seq = 0
    for (code,) in rows:
        m = re.search(r"-(\d+)$", code or "")
        if m:
            max_seq = max(max_seq, int(m.group(1)))
    seq = max_seq + 1
    code = f"{base}{seq:03d}"
    # 极小概率冲突时继续递增，保证唯一
    while db.query(Material).filter(Material.material_code == code).first():
        seq += 1
        code = f"{base}{seq:03d}"
    return success({"code": code})


@router.get("")
def list_materials(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
    keyword: str | None = None,
    category: str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(require_permissions("basic:material:list")),
):
    filters = {"category": category} if category else None
    rows, total = crud.get_multi(
        db, page=page, page_size=page_size, keyword=keyword,
        search_fields=SEARCH_FIELDS, filters=filters,
        sort_by=sort_by, sort_order=sort_order,
    )
    data = [
        {
            "id": r.id, "material_code": r.material_code, "material_name": r.material_name,
            "category": r.category, "spec": r.spec, "unit": r.unit,
            "default_color_no": r.default_color_no, "safety_stock": r.safety_stock,
            "min_order_qty": r.min_order_qty, "status": r.status, "remark": r.remark,
        }
        for r in rows
    ]
    return success(page_result(data, total))


@router.get("/{item_id}")
def get_material(item_id: int, db: Session = Depends(get_db), _=Depends(require_permissions("basic:material:list"))):
    obj = crud.get(db, item_id)
    if not obj:
        raise BizException("物料不存在")
    return success(obj.__dict__)


@router.post("")
def create_material(data: MaterialCreate, db: Session = Depends(get_db), _=Depends(require_permissions("basic:material:add"))):
    if db.query(Material).filter(Material.material_code == data.material_code).first():
        raise BizException("物料编码已存在")
    obj = crud.create(db, data.model_dump())
    return success(obj, message="新增成功")


@router.put("/{item_id}")
def update_material(item_id: int, data: MaterialUpdate, db: Session = Depends(get_db), _=Depends(require_permissions("basic:material:edit"))):
    obj = crud.get(db, item_id)
    if not obj:
        raise BizException("物料不存在")
    obj = crud.update(db, obj, data.model_dump(exclude_unset=True))
    return success(obj, message="修改成功")


@router.delete("/{item_id}")
def delete_material(item_id: int, db: Session = Depends(get_db), _=Depends(require_permissions("basic:material:delete"))):
    if not crud.remove(db, item_id):
        raise BizException("物料不存在或已删除")
    return success(message="删除成功")


# ---------------- 批量操作 ----------------
# 动作 → 所需权限：启用/停用属于编辑，删除单独要删除权限，避免「能编辑就能删」
BATCH_PERMS = {
    "enable": "basic:material:edit",
    "disable": "basic:material:edit",
    "delete": "basic:material:delete",
}


def _one_material(db: Session, item_id: int, action: str) -> None:
    """单条批量动作：取对象 → 校验 → 改状态（不 commit，由 run_batch 统一提交）。"""
    obj = crud.get(db, item_id)
    if not obj:
        raise BizException("物料不存在或已删除")
    if action == "delete":
        db.delete(obj)
    elif action == "enable":
        obj.status = True
    elif action == "disable":
        obj.status = False
    else:
        raise BizException(f"不支持的批量动作：{action}")


@router.post("/batch")
def batch_materials(payload: BatchIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """批量启用/停用/删除物料（逐条独立事务，返回失败明细）。"""
    return run_batch_guarded(db, user, payload, BATCH_PERMS, _one_material)
