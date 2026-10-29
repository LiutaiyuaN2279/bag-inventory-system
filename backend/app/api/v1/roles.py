"""角色权限接口：角色增删改查 + 权限分配。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api._batch import run_batch_guarded
from app.api.deps import get_current_user, require_permissions
from app.core.database import get_db
from app.core.exceptions import BizException
from app.crud.crud_base import CRUDBase
from app.models.rbac import Permission, Role, User, UserRole
from app.schemas.batch import BatchIn
from app.schemas.rbac import RoleCreate, RolePermissionsIn, RoleUpdate
from app.utils.response import page_result, success

router = APIRouter(prefix="/roles", tags=["角色权限"])
crud = CRUDBase(Role)

SEARCH_FIELDS = ["role_code", "role_name"]

# 内置角色：不允许删除
BUILTIN_ROLE_CODES = {"admin"}


def _role_row(r: Role) -> dict:
    return {
        "id": r.id,
        "role_code": r.role_code,
        "role_name": r.role_name,
        "remark": r.remark,
        "user_count": len(r.users),
        "perm_count": len(r.permissions),
        # perm_ids 供前端「配置权限」弹窗直接回显，省掉逐角色再查一次
        "perm_ids": sorted(p.id for p in r.permissions),
    }


# ---------------- 批量操作 ----------------
# 动作 → 所需权限：仅删除
BATCH_PERMS = {
    "delete": "system:role:delete",
}


def _do_delete_role(db: Session, rid: int) -> None:
    """删除角色业务核心：校验存在性 → 内置角色保护 → 被用户引用保护 → 删除。

    不 commit，由调用方（单条端点 / 批量执行器）统一提交。
    保护规则与单条删除端点完全一致。关联表 role_permissions 由 ORM 级联清理
    （Role.permissions 为 secondary 关系，删除 Role 时自动清空关联行）。
    """
    obj = crud.get(db, rid)
    if not obj:
        raise BizException("角色不存在或已删除")
    if obj.role_code in BUILTIN_ROLE_CODES:
        raise BizException("内置管理员角色 admin 不允许删除")
    if db.query(UserRole).filter(UserRole.role_id == rid).first():
        raise BizException("该角色仍被用户引用，请先解除用户绑定")
    db.delete(obj)


def _one_role(db: Session, item_id: int, action: str) -> None:
    """单条批量动作：取对象 → 校验 → 删除（不 commit，由 run_batch 统一提交）。"""
    if action == "delete":
        _do_delete_role(db, item_id)
    else:
        raise BizException(f"不支持的批量动作：{action}")


# 注意：必须声明在任何 /{rid} 动态路由之前，否则 batch 会被当成 rid 匹配
@router.post("/batch")
def batch_roles(payload: BatchIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """批量删除角色（逐条独立事务，返回失败明细）。"""
    return run_batch_guarded(db, user, payload, BATCH_PERMS, _one_role)


@router.get("")
def list_roles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
    keyword: str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(require_permissions("system:role:list")),
):
    rows, total = crud.get_multi(
        db, page=page, page_size=page_size, keyword=keyword,
        search_fields=SEARCH_FIELDS, sort_by=sort_by, sort_order=sort_order,
    )
    return success(page_result([_role_row(r) for r in rows], total))


@router.get("/permissions")
def list_permissions(db: Session = Depends(get_db), _=Depends(require_permissions("system:role:list"))):
    """全部权限（供前端权限树按 module 分组）。"""
    rows = db.query(Permission).order_by(Permission.id).all()
    return success([
        {"id": p.id, "perm_code": p.perm_code, "perm_name": p.perm_name, "module": p.module}
        for p in rows
    ])


@router.post("")
def create_role(data: RoleCreate, db: Session = Depends(get_db), _=Depends(require_permissions("system:role:add"))):
    if db.query(Role).filter(Role.role_code == data.role_code).first():
        raise BizException("角色编码已存在")
    obj = crud.create(db, {
        "role_code": data.role_code,
        "role_name": data.role_name,
        "remark": data.remark or "",
    })
    return success(_role_row(obj), message="新增成功")


@router.put("/{rid}")
def update_role(rid: int, data: RoleUpdate, db: Session = Depends(get_db), _=Depends(require_permissions("system:role:edit"))):
    obj = crud.get(db, rid)
    if not obj:
        raise BizException("角色不存在")
    # 仅 role_name / remark（schema 中不含 role_code，故 role_code 不可改）
    fields = data.model_dump(exclude_unset=True)
    if "role_name" in fields and not (fields["role_name"] or "").strip():
        raise BizException("角色名称不能为空")
    if fields:
        obj = crud.update(db, obj, fields)
    return success(_role_row(obj), message="修改成功")


@router.put("/{rid}/permissions")
def set_role_permissions(rid: int, data: RolePermissionsIn, db: Session = Depends(get_db), _=Depends(require_permissions("system:role:edit"))):
    """设置角色权限：perm_ids 全量覆盖（空列表表示清空）。"""
    obj = crud.get(db, rid)
    if not obj:
        raise BizException("角色不存在")
    ids = sorted(set(data.perm_ids or []))
    perms = db.query(Permission).filter(Permission.id.in_(ids)).all() if ids else []
    missing = [i for i in ids if i not in {p.id for p in perms}]
    if missing:
        raise BizException(f"权限不存在: {missing}")
    obj.permissions = perms
    db.commit()
    db.refresh(obj)
    return success(_role_row(obj), message="权限设置成功")


@router.delete("/{rid}")
def delete_role(rid: int, db: Session = Depends(get_db), _=Depends(require_permissions("system:role:delete"))):
    """删除角色（内置角色与仍被用户引用的角色不可删除）。"""
    _do_delete_role(db, rid)
    db.commit()
    return success(message="删除成功")
