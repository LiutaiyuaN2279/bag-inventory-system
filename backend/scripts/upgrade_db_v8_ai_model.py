"""第八轮升级：AI 单据识别支持「界面配置大模型」（幂等）。

运行：进入 backend 目录后执行  .venv/Scripts/python.exe scripts/upgrade_db_v8_ai_model.py

## 背景

识别引擎的 地址 / 模型 / 密钥 原来只能写在 `backend/.env`（`AI_OCR_*`），
换一家模型要改文件并重启后端，演示时很不方便。本次升级新增 `ai_model_configs` 表：
可以保存多份模型档案（通义千问-VL / 豆包视觉 / 智谱 / 本地网关…），
界面点「启用」即时切换，识别服务下次调用就用新档案（优先级：启用档案 > .env > 引擎预设）。

## 做三件事

1. 建表 `ai_model_configs`（模型档案）。
2. 补权限码 `ai:ocr:config`（AI单据识别-模型配置），**只授予 admin**：
   密钥是与钱同级的敏感信息，普通业务岗（含采购员/主管）只需要用识别功能，不需要改模型。
3. 表为空时插入一条默认「离线演示引擎（mock）」并设为启用，
   保证升级后打开页面就能看到一条可用的配置，而不是空白列表。

重复执行无副作用：表存在跳过、权限码存在跳过、已有档案则不插默认值。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import inspect

from app.core.database import SessionLocal, engine
from app.models.ai_ocr import AiModelConfig
from app.models.rbac import Permission, Role, RolePermission

PERM_CODE = "ai:ocr:config"
PERM_NAME = "AI单据识别-模型配置"
PERM_MODULE = "ai"

#: 允许配置大模型的角色（密钥属敏感信息，只给系统管理员）
ALLOWED_ROLES = {"admin"}

DEFAULT_CONFIG = {
    "name": "离线演示引擎（mock）",
    "provider": "mock",
    "remark": "无需密钥，返回与演示基础数据吻合的样例结果；接入真实模型请新建档案并启用",
}


def ensure_table() -> None:
    """建 ai_model_configs 表；已存在则跳过。"""
    print("[1/3] 检查 ai_model_configs 表 ...")
    if inspect(engine).has_table("ai_model_configs"):
        print("  · ai_model_configs 已存在，跳过")
        return
    AiModelConfig.__table__.create(bind=engine, checkfirst=True)
    print("  + ai_model_configs 已创建")


def ensure_permission(db) -> Permission:
    print("[2/3] 核对权限码 ...")
    perm = db.query(Permission).filter(Permission.perm_code == PERM_CODE).first()
    if perm:
        print(f"  · {PERM_CODE} 已存在，跳过")
        return perm
    perm = Permission(perm_code=PERM_CODE, perm_name=PERM_NAME, module=PERM_MODULE)
    db.add(perm)
    db.flush()
    print(f"  + {PERM_CODE} 已添加")
    return perm


def grant_admin(db, perm: Permission) -> None:
    """把权限码授予 admin；其它角色若有残留一并撤销（保证「只有管理员能改模型」）。"""
    print("[3/3] 授予系统管理员 / 创建默认档案 ...")
    for rp in db.query(RolePermission).filter(RolePermission.permission_id == perm.id).all():
        role = db.get(Role, rp.role_id)
        if role and role.role_code in ALLOWED_ROLES:
            continue
        db.delete(rp)
        print(f"  - 撤销角色 {role.role_code if role else rp.role_id} 的 {PERM_CODE}")
    for role_code in ALLOWED_ROLES:
        role = db.query(Role).filter(Role.role_code == role_code).first()
        if not role:
            print(f"  ! 角色 {role_code} 不存在，跳过（请先运行 scripts/setup_roles.py）")
            continue
        exists = db.query(RolePermission).filter(
            RolePermission.role_id == role.id,
            RolePermission.permission_id == perm.id,
        ).first()
        if exists:
            print(f"  · {role_code} 已持有 {PERM_CODE}，跳过")
            continue
        db.add(RolePermission(role_id=role.id, permission_id=perm.id))
        print(f"  + {role_code} 获得 {PERM_CODE}")

    if db.query(AiModelConfig).count() == 0:
        db.add(AiModelConfig(**DEFAULT_CONFIG, is_active=True, created_by="system"))
        print("  + 已插入默认模型档案「离线演示引擎（mock）」并启用")
    else:
        print("  · 已有模型档案，跳过默认值")


def run() -> int:
    ensure_table()
    db = SessionLocal()
    try:
        perm = ensure_permission(db)
        grant_admin(db, perm)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print("\n第八轮升级完成：AI 单据识别可在「模型配置」中配置大模型（仅管理员）。")
    return 0


if __name__ == "__main__":
    sys.exit(run())
