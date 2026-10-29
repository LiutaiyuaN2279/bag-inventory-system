"""认证相关 Schema。"""
from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserInfoOut(BaseModel):
    id: int
    username: str
    real_name: str
    roles: list[str] = []
    permissions: list[str] = []
