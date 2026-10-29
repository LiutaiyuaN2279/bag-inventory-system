"""认证与用户相关数据访问。"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.models.rbac import Permission, Role, User, UserPermission


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.execute(select(User).where(User.username == username)).scalar_one_or_none()


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = get_user_by_username(db, username)
    if not user or not user.status:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def get_role_permissions(user: User) -> set[str]:
    """聚合用户所有角色的权限码（不含用户级覆盖）。"""
    perm_codes: set[str] = set()
    for role in user.roles:
        for perm in role.permissions:
            perm_codes.add(perm.perm_code)
    return perm_codes


def get_user_permission_overrides(db: Session, user: User) -> tuple[set[str], set[str]]:
    """读取用户级权限覆盖，返回 (额外授权码集合, 明确禁用码集合)。"""
    rows = (
        db.query(Permission.perm_code, UserPermission.effect)
        .join(UserPermission, UserPermission.permission_id == Permission.id)
        .filter(UserPermission.user_id == user.id)
        .all()
    )
    grants = {code for code, effect in rows if effect != "deny"}
    denies = {code for code, effect in rows if effect == "deny"}
    return grants, denies


def get_user_permissions(db: Session, user: User) -> list[str]:
    """有效权限 = (全部角色权限 ∪ 用户级 grant) − 用户级 deny。"""
    perm_codes = get_role_permissions(user)
    grants, denies = get_user_permission_overrides(db, user)
    perm_codes |= grants
    perm_codes -= denies
    return sorted(perm_codes)


def get_user_denied_permissions(db: Session, user: User) -> list[str]:
    """用户级「明确禁止」的权限码（前端据此覆盖 admin 短路）。"""
    return sorted(get_user_permission_overrides(db, user)[1])


def get_user_roles(db: Session, user: User) -> list[str]:
    return [r.role_code for r in user.roles]
