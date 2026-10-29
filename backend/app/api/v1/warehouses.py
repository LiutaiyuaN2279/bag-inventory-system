"""仓库管理接口。"""
import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api._batch import run_batch_guarded
from app.api.deps import get_current_user, require_permissions
from app.core.database import get_db
from app.core.exceptions import BizException
from app.crud.crud_base import CRUDBase
from app.models.master_data import Warehouse
from app.models.rbac import User
from app.schemas.batch import BatchIn
from app.schemas.master_data import WarehouseCreate, WarehouseUpdate
from app.utils.response import page_result, success

router = APIRouter(prefix="/warehouses", tags=["仓库管理"])
crud = CRUDBase(Warehouse)

SEARCH_FIELDS = ["warehouse_code", "warehouse_name", "manager"]


@router.get("/suggest-code")
def suggest_code(db: Session = Depends(get_db), _=Depends(require_permissions("basic:warehouse:list"))):
    """生成与现有格式统一的建议仓库编码：WH-001（取最大序号 +1，保证唯一）。"""
    rows = db.query(Warehouse.warehouse_code).all()
    max_seq = 0
    for (code,) in rows:
        m = re.search(r"(\d+)$", code or "")
        if m:
            max_seq = max(max_seq, int(m.group(1)))
    seq = max_seq + 1
    code = f"WH-{seq:03d}"
    while db.query(Warehouse).filter(Warehouse.warehouse_code == code).first():
        seq += 1
        code = f"WH-{seq:03d}"
    return success({"code": code})


@router.get("")
def list_warehouses(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
    keyword: str | None = None,
    type: str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(require_permissions("basic:warehouse:list")),
):
    filters = {"type": type} if type else None
    rows, total = crud.get_multi(
        db, page=page, page_size=page_size, keyword=keyword,
        search_fields=SEARCH_FIELDS, filters=filters,
        sort_by=sort_by, sort_order=sort_order,
    )
    data = [
        {
            "id": r.id, "warehouse_code": r.warehouse_code, "warehouse_name": r.warehouse_name,
            "type": r.type, "manager": r.manager, "status": r.status, "remark": r.remark,
        }
        for r in rows
    ]
    return success(page_result(data, total))


@router.get("/all")
def all_warehouses(db: Session = Depends(get_db), _=Depends(require_permissions("basic:warehouse:list"))):
    """下拉用：返回全部启用仓库。"""
    rows = db.query(Warehouse).filter(Warehouse.status == True).order_by(Warehouse.id).all()
    return success([{"id": r.id, "warehouse_code": r.warehouse_code, "warehouse_name": r.warehouse_name} for r in rows])


@router.post("")
def create_warehouse(data: WarehouseCreate, db: Session = Depends(get_db), _=Depends(require_permissions("basic:warehouse:add"))):
    if db.query(Warehouse).filter(Warehouse.warehouse_code == data.warehouse_code).first():
        raise BizException("仓库编码已存在")
    return success(crud.create(db, data.model_dump()), message="新增成功")


@router.put("/{item_id}")
def update_warehouse(item_id: int, data: WarehouseUpdate, db: Session = Depends(get_db), _=Depends(require_permissions("basic:warehouse:edit"))):
    obj = crud.get(db, item_id)
    if not obj:
        raise BizException("仓库不存在")
    return success(crud.update(db, obj, data.model_dump(exclude_unset=True)), message="修改成功")


@router.delete("/{item_id}")
def delete_warehouse(item_id: int, db: Session = Depends(get_db), _=Depends(require_permissions("basic:warehouse:delete"))):
    if not crud.remove(db, item_id):
        raise BizException("仓库不存在或已删除")
    return success(message="删除成功")


# ---------------- 批量操作 ----------------
BATCH_PERMS = {
    "enable": "basic:warehouse:edit",
    "disable": "basic:warehouse:edit",
    "delete": "basic:warehouse:delete",
}


def _one_warehouse(db: Session, item_id: int, action: str) -> None:
    obj = crud.get(db, item_id)
    if not obj:
        raise BizException("仓库不存在或已删除")
    if action == "delete":
        db.delete(obj)
    elif action == "enable":
        obj.status = True
    elif action == "disable":
        obj.status = False
    else:
        raise BizException(f"不支持的批量动作：{action}")


@router.post("/batch")
def batch_warehouses(payload: BatchIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """批量启用/停用/删除仓库（逐条独立事务，返回失败明细）。"""
    return run_batch_guarded(db, user, payload, BATCH_PERMS, _one_warehouse)
