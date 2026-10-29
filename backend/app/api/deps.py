"""API 依赖：当前用户解析 + 权限校验工厂。"""
import jwt
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import AuthException, PermissionException
from app.crud.crud_auth import (
    get_user_permission_overrides,
    get_user_permissions,
    get_user_roles,
)
from app.models.rbac import User


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthException()
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256"])
        user_id = int(payload.get("sub"))
    except Exception:
        raise AuthException()
    # 重新校验签名
    from app.core.security import decode_token
    try:
        decode_token(token)
    except Exception:
        raise AuthException()
    user = db.get(User, user_id)
    if not user or not user.status:
        raise AuthException()
    return user


def require_permissions(*perm_codes: str):
    """权限校验依赖工厂：传入所需权限码，满足其一即可。

    判定顺序：用户级「明确禁止」优先于一切（含 admin 全放行）→ admin 放行 → 权限码匹配。
    仅当所有要求的权限码都被禁用时才拦截，避免误伤「满足其一」的多码接口。
    """

    def checker(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if not perm_codes:
            return user
        _grants, denies = get_user_permission_overrides(db, user)
        if all(p in denies for p in perm_codes):
            raise PermissionException("该权限已被单独禁用，请联系系统管理员")
        if "admin" in get_user_roles(db, user):
            return user
        perms = get_user_permissions(db, user)
        if not any(p in perms for p in perm_codes):
            raise PermissionException()
        return user

    return checker
