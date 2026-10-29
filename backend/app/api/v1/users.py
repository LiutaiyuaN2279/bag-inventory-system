"""用户管理接口：用户增删改查 + 角色分配 + 用户级权限覆盖。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api._batch import run_batch_guarded
from app.api.deps import get_current_user, require_permissions
from app.core.database import get_db
from app.core.exceptions import BizException
from app.core.security import hash_password
from app.crud.crud_base import CRUDBase
from app.models.rbac import Permission, Role, User, UserPermission
from app.schemas.batch import BatchIn
from app.schemas.rbac import (
    PasswordReset,
    UserCreate,
    UserPermissionsIn,
    UserUpdate,
)
from app.utils.response import page_result, success

router = APIRouter(prefix="/users", tags=["用户管理"])
crud = CRUDBase(User)

SEARCH_FIELDS = ["username", "real_name"]

# 内置账号：不允许删除
BUILTIN_USERNAMES = {"admin"}


def _user_row(u: User) -> dict:
    """用户序列化（绝不输出 password_hash）。"""
    return {
        "id": u.id,
        "username": u.username,
        "real_name": u.real_name,
        "status": u.status,
        "created_at": str(u.created_at)[:19] if u.created_at else None,
        "roles": [r.role_code for r in u.roles],
        "role_ids": [r.id for r in u.roles],
        "override_count": len(u.perm_overrides or []),
    }


def _validated_roles(db: Session, role_ids: list[int]) -> list[Role]:
    """校验并返回角色对象；存在无效 id 时抛业务错。
    必须在写库之前调用，避免写入后再报错留下脏数据。"""
    ids = sorted(set(role_ids or []))
    if not ids:
        return []
    roles = db.query(Role).filter(Role.id.in_(ids)).all()
    missing = [i for i in ids if i not in {r.id for r in roles}]
    if missing:
        raise BizException(f"角色不存在: {missing}")
    return roles


# ---------------- 批量操作 ----------------
# 动作 → 所需权限：启用/停用属于编辑，删除单独要删除权限，避免「能编辑就能删」
BATCH_PERMS = {
    "enable": "system:user:edit",
    "disable": "system:user:edit",
    "delete": "system:user:delete",
}


def _do_delete_user(db: Session, uid: int, current: User) -> None:
    """删除用户业务核心：校验存在性 → 内置账号保护 → 不可删除自己 → 删除。

    不 commit，由调用方（单条端点 / 批量执行器）统一提交。
    保护规则与单条删除端点完全一致，批量路径不比单条更宽松。
    """
    obj = crud.get(db, uid)
    if not obj:
        raise BizException("用户不存在或已删除")
    if obj.username in BUILTIN_USERNAMES:
        raise BizException("内置管理员账号 admin 不允许删除")
    if obj.id == current.id:
        raise BizException("不允许删除当前登录用户")
    db.delete(obj)


def _make_one_user(current: User):
    """构造批量 handler：闭包捕获当前登录用户，用于「不可删除自己」判定。"""

    def _one_user(db: Session, item_id: int, action: str) -> None:
        if action == "delete":
            _do_delete_user(db, item_id, current)
            return
        obj = crud.get(db, item_id)
        if not obj:
            raise BizException("用户不存在或已删除")
        if action == "enable":
            obj.status = True
        elif action == "disable":
            # 比单条删除更严：内置账号既不可删也不可停用，避免误锁死系统
            if obj.username in BUILTIN_USERNAMES:
                raise BizException("内置管理员账号 admin 不允许停用")
            obj.status = False
        else:
            raise BizException(f"不支持的批量动作：{action}")

    return _one_user


# 注意：必须声明在任何 /{uid} 动态路由之前，否则 batch 会被当成 uid 匹配
@router.post("/batch")
def batch_users(payload: BatchIn, db: Session = Depends(get_db),
                current: User = Depends(get_current_user)):
    """批量启用/停用/删除用户（逐条独立事务，返回失败明细）。"""
    return run_batch_guarded(db, current, payload, BATCH_PERMS, _make_one_user(current))


@router.get("")
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
    keyword: str | None = None,
    status: bool | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(require_permissions("system:user:list")),
):
    filters = {"status": status} if status is not None else None
    rows, total = crud.get_multi(
        db, page=page, page_size=page_size, keyword=keyword,
        search_fields=SEARCH_FIELDS, filters=filters,
        sort_by=sort_by, sort_order=sort_order,
    )
    return success(page_result([_user_row(u) for u in rows], total))


@router.post("")
def create_user(data: UserCreate, db: Session = Depends(get_db), _=Depends(require_permissions("system:user:add"))):
    if db.query(User).filter(User.username == data.username).first():
        raise BizException("用户名已存在")
    roles = _validated_roles(db, data.role_ids)  # 先校验角色，再写库
    # 密码只以哈希形式落库，接口永不回显
    obj = crud.create(db, {
        "username": data.username,
        "password_hash": hash_password(data.password),
        "real_name": data.real_name or "",
        "status": data.status if data.status is not None else True,
    })
    if roles:
        obj.roles = roles
        db.commit()
        db.refresh(obj)
    return success(_user_row(obj), message="新增成功")


@router.put("/{uid}")
def update_user(uid: int, data: UserUpdate, db: Session = Depends(get_db), _=Depends(require_permissions("system:user:edit"))):
    obj = crud.get(db, uid)
    if not obj:
        raise BizException("用户不存在")
    # 先校验角色，再写库，避免部分成功
    roles = _validated_roles(db, data.role_ids) if data.role_ids is not None else None
    # 仅 real_name / status（schema 中不含 username，故 username 天然不可改）；
    # role_ids 走全量覆盖，故从字段更新中排除
    fields = data.model_dump(exclude_unset=True, exclude={"role_ids"})
    if fields:
        obj = crud.update(db, obj, fields)
    if roles is not None:
        obj.roles = roles
        db.commit()
        db.refresh(obj)
    return success(_user_row(obj), message="修改成功")


@router.put("/{uid}/password")
def reset_password(uid: int, data: PasswordReset, db: Session = Depends(get_db), _=Depends(require_permissions("system:user:edit"))):
    obj = crud.get(db, uid)
    if not obj:
        raise BizException("用户不存在")
    obj.password_hash = hash_password(data.password)
    db.commit()
    return success(message="密码重置成功")


@router.get("/{uid}/permissions")
def user_permissions(uid: int, db: Session = Depends(get_db), _=Depends(require_permissions("system:user:perm"))):
    """查询某用户的权限覆盖明细：角色权限 / 额外授予 / 明确禁用 / 有效权限。

    同时返回权限 id 与权限码，前端按 id 回填、按码展示。
    """
    obj = crud.get(db, uid)
    if not obj:
        raise BizException("用户不存在")
    role_ids = {p.id for r in obj.roles for p in r.permissions}
    grant_ids = {o.permission_id for o in obj.perm_overrides if o.effect != "deny"}
    deny_ids = {o.permission_id for o in obj.perm_overrides if o.effect == "deny"}
    code_of = {p.id: p.perm_code for p in db.query(Permission).all()}
    return success({
        "user_id": obj.id,
        "username": obj.username,
        "role_perm_ids": sorted(role_ids),
        "grant_ids": sorted(grant_ids),
        "deny_ids": sorted(deny_ids),
        "grant_codes": sorted(code_of[i] for i in grant_ids if i in code_of),
        "deny_codes": sorted(code_of[i] for i in deny_ids if i in code_of),
        # 有效权限 = (角色权限 ∪ grant) − deny
        "effective_ids": sorted((role_ids | grant_ids) - deny_ids),
    })


@router.put("/{uid}/permissions")
def set_user_permissions(uid: int, data: UserPermissionsIn, db: Session = Depends(get_db), _=Depends(require_permissions("system:user:perm"))):
    """全量覆盖用户级权限项；同一权限不可既 grant 又 deny。"""
    obj = crud.get(db, uid)
    if not obj:
        raise BizException("用户不存在")
    pairs: dict[int, str] = {}
    for item in data.items or []:
        if item.perm_id in pairs:
            raise BizException(f"权限 id {item.perm_id} 重复提交")
        pairs[item.perm_id] = item.effect
    if pairs:
        found = {p.id for p in db.query(Permission).filter(Permission.id.in_(list(pairs))).all()}
        missing = [i for i in pairs if i not in found]
        if missing:
            raise BizException(f"权限不存在: {missing}")
    db.query(UserPermission).filter(UserPermission.user_id == uid).delete()
    for perm_id, effect in pairs.items():
        db.add(UserPermission(user_id=uid, permission_id=perm_id, effect=effect))
    db.commit()
    db.refresh(obj)
    return success(_user_row(obj), message="权限配置已保存")


@router.delete("/{uid}")
def delete_user(uid: int, db: Session = Depends(get_db),
                current: User = Depends(require_permissions("system:user:delete"))):
    """删除用户（内置账号 admin 与当前登录用户均不可删除）。"""
    _do_delete_user(db, uid, current)
    db.commit()
    return success(message="删除成功")
