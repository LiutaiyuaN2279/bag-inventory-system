"""RBAC Schema：用户 / 角色 / 权限。字段与数据表保持一致。"""
from typing import Optional

from pydantic import BaseModel, Field


# ---------------- 用户 ----------------
class UserCreate(BaseModel):
    username: str = Field(..., max_length=64)
    password: str = Field(..., min_length=1, max_length=128)
    real_name: Optional[str] = ""
    status: Optional[bool] = True
    role_ids: Optional[list[int]] = []


class UserUpdate(BaseModel):
    """仅允许修改 real_name / status / role_ids，username 不可改。"""
    real_name: Optional[str] = None
    status: Optional[bool] = None
    role_ids: Optional[list[int]] = None


class PasswordReset(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)


# ---------------- 角色 ----------------
class RoleCreate(BaseModel):
    role_code: str = Field(..., max_length=64)
    role_name: str = Field(..., max_length=64)
    remark: Optional[str] = ""


class RoleUpdate(BaseModel):
    """仅允许修改 role_name / remark，role_code 不可改。"""
    role_name: Optional[str] = None
    remark: Optional[str] = None


class RolePermissionsIn(BaseModel):
    """设置角色权限：perm_ids 全量覆盖。"""
    perm_ids: Optional[list[int]] = []


# ---------------- 用户级权限覆盖 ----------------
class UserPermissionItem(BaseModel):
    """单条用户级权限覆盖：effect = grant（额外授予）/ deny（明确禁用）。"""
    perm_id: int
    effect: str = Field("grant", pattern="^(grant|deny)$")


class UserPermissionsIn(BaseModel):
    """设置用户级权限覆盖：items 全量覆盖该用户的全部覆盖项。"""
    items: Optional[list[UserPermissionItem]] = []
