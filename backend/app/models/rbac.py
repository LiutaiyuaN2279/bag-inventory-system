"""RBAC 模型：用户 / 角色 / 权限 多对多。"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    real_name = Column(String(64), default="")
    status = Column(Boolean, default=True)  # True 启用
    # 关联报销员工档案（rmb_employee.id）。报销模块据此确定"当前登录人是哪位员工"，
    # 用于固定报销人身份与职责分离校验。不建外键约束，避免 rmb_* 表与 users 表建表顺序耦合。
    employee_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    roles = relationship(
        "Role",
        secondary="user_roles",
        back_populates="users",
        lazy="selectin",
    )
    # 用户级权限覆盖（grant / deny）；随用户删除自动清理
    perm_overrides = relationship(
        "UserPermission",
        back_populates="user",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    role_code = Column(String(64), unique=True, nullable=False)
    role_name = Column(String(64), nullable=False)
    remark = Column(String(255), default="")

    users = relationship("User", secondary="user_roles", back_populates="roles", lazy="selectin")
    permissions = relationship(
        "Permission",
        secondary="role_permissions",
        back_populates="roles",
        lazy="selectin",
    )


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    perm_code = Column(String(64), unique=True, nullable=False)
    perm_name = Column(String(64), nullable=False)
    module = Column(String(32), default="")  # 所属模块，用于前端菜单分组

    roles = relationship("Role", secondary="role_permissions", back_populates="permissions", lazy="selectin")


# 关联表（以映射类形式定义，relationship 通过表名字符串 secondary 引用）


class UserRole(Base):
    """显式映射关联表，便于直接增删。"""
    __tablename__ = "user_roles"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id"), primary_key=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id = Column(Integer, ForeignKey("roles.id"), primary_key=True)
    permission_id = Column(Integer, ForeignKey("permissions.id"), primary_key=True)


class UserPermission(Base):
    """用户级权限覆盖：在角色权限之上「追加授权」或「显式禁用」单个用户的某项权限。

    有效权限 = (全部角色权限 ∪ grant) − deny，deny 优先级最高，可覆盖角色授权，
    用于满足「同一角色下个别用户的权限差异」（如采购员临时收回导入权）。
    """
    __tablename__ = "user_permissions"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    permission_id = Column(Integer, ForeignKey("permissions.id"), primary_key=True)
    effect = Column(String(8), nullable=False, default="grant")

    user = relationship("User", back_populates="perm_overrides")
    permission = relationship("Permission", lazy="selectin")
