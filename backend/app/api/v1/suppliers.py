"""供应商管理接口。"""
import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api._batch import run_batch_guarded
from app.api.deps import get_current_user, require_permissions
from app.core.database import get_db
from app.core.exceptions import BizException
from app.crud.crud_base import CRUDBase
from app.models.master_data import Supplier
from app.models.rbac import User
from app.schemas.batch import BatchIn
from app.schemas.master_data import SupplierCreate, SupplierUpdate
from app.utils.response import page_result, success

router = APIRouter(prefix="/suppliers", tags=["供应商管理"])
crud = CRUDBase(Supplier)

SEARCH_FIELDS = ["supplier_code", "supplier_name", "contact"]


@router.get("/suggest-code")
def suggest_code(db: Session = Depends(get_db), _=Depends(require_permissions("basic:supplier:list"))):
    """生成与现有格式统一的建议供应商编码：S-001（取最大序号 +1，保证唯一）。"""
    rows = db.query(Supplier.supplier_code).all()
    max_seq = 0
    for (code,) in rows:
        m = re.search(r"(\d+)$", code or "")
        if m:
            max_seq = max(max_seq, int(m.group(1)))
    seq = max_seq + 1
    code = f"S-{seq:03d}"
    while db.query(Supplier).filter(Supplier.supplier_code == code).first():
        seq += 1
        code = f"S-{seq:03d}"
    return success({"code": code})


@router.get("")
def list_suppliers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
    keyword: str | None = None,
    status: int | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(require_permissions("basic:supplier:list")),
):
    filters = {"status": bool(status)} if status is not None else None
    rows, total = crud.get_multi(
        db, page=page, page_size=page_size, keyword=keyword,
        search_fields=SEARCH_FIELDS, filters=filters,
        sort_by=sort_by, sort_order=sort_order,
    )
    data = [
        {
            "id": r.id, "supplier_code": r.supplier_code, "supplier_name": r.supplier_name,
            "contact": r.contact, "phone": r.phone, "address": r.address,
            "payment_term": r.payment_term, "lead_time_days": r.lead_time_days,
            "status": r.status, "remark": r.remark,
        }
        for r in rows
    ]
    return success(page_result(data, total))


@router.post("")
def create_supplier(data: SupplierCreate, db: Session = Depends(get_db), _=Depends(require_permissions("basic:supplier:add"))):
    if db.query(Supplier).filter(Supplier.supplier_code == data.supplier_code).first():
        raise BizException("供应商编码已存在")
    return success(crud.create(db, data.model_dump()), message="新增成功")


@router.put("/{item_id}")
def update_supplier(item_id: int, data: SupplierUpdate, db: Session = Depends(get_db), _=Depends(require_permissions("basic:supplier:edit"))):
    obj = crud.get(db, item_id)
    if not obj:
        raise BizException("供应商不存在")
    return success(crud.update(db, obj, data.model_dump(exclude_unset=True)), message="修改成功")


@router.delete("/{item_id}")
def delete_supplier(item_id: int, db: Session = Depends(get_db), _=Depends(require_permissions("basic:supplier:delete"))):
    if not crud.remove(db, item_id):
        raise BizException("供应商不存在或已删除")
    return success(message="删除成功")


# ---------------- 批量操作 ----------------
BATCH_PERMS = {
    "enable": "basic:supplier:edit",
    "disable": "basic:supplier:edit",
    "delete": "basic:supplier:delete",
}


def _one_supplier(db: Session, item_id: int, action: str) -> None:
    obj = crud.get(db, item_id)
    if not obj:
        raise BizException("供应商不存在或已删除")
    if action == "delete":
        db.delete(obj)
    elif action == "enable":
        obj.status = True
    elif action == "disable":
        obj.status = False
    else:
        raise BizException(f"不支持的批量动作：{action}")


@router.post("/batch")
def batch_suppliers(payload: BatchIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """批量启用/停用/删除供应商（逐条独立事务，返回失败明细）。"""
    return run_batch_guarded(db, user, payload, BATCH_PERMS, _one_supplier)
