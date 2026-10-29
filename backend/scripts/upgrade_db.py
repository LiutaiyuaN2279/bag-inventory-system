r"""数据库升级：创建采购/库存/BOM 新表，追加权限码并授予管理员，补充示例数据。
运行：进入 backend 目录后执行  .venv/Scripts/python.exe scripts/upgrade_db.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.core.database import Base, SessionLocal, engine
from app.models import *  # noqa: F401,F403  注册全部模型
from app.models.bom import BomHeader, BomItem
from app.models.master_data import Material
from app.models.rbac import Permission, Role, RolePermission
from app.services.stock_service import post_inbound

NEW_PERMISSIONS = [
    ("purchase:requisition:list", "请购单-查看", "purchase"),
    ("purchase:requisition:add", "请购单-新增", "purchase"),
    ("purchase:requisition:edit", "请购单-编辑", "purchase"),
    ("purchase:requisition:approve", "请购单-审核", "purchase"),
    ("purchase:order:list", "采购订单-查看", "purchase"),
    ("purchase:order:add", "采购订单-新增", "purchase"),
    ("purchase:order:edit", "采购订单-编辑", "purchase"),
    ("purchase:order:approve", "采购订单-审核", "purchase"),
    ("purchase:arrival:list", "到货入库-查看", "purchase"),
    ("purchase:arrival:add", "到货入库-登记", "purchase"),
    ("purchase:arrival:approve", "到货入库-验收", "purchase"),
    ("purchase:return:list", "采购退货-查看", "purchase"),
    ("purchase:return:add", "采购退货-新增", "purchase"),
    ("purchase:return:approve", "采购退货-审核", "purchase"),
    ("inventory:view", "库存-查询", "inventory"),
    ("inventory:adjust", "库存-其他出入库", "inventory"),
    ("inventory:stocktake", "库存-盘点", "inventory"),
    ("inventory:alert", "库存-预警", "inventory"),
    ("bom:view", "BOM-查看", "bom"),
    ("bom:edit", "BOM-维护", "bom"),
    ("bom:approve", "BOM-版本生效", "bom"),
]


def run():
    print("[1/3] 创建新表 ...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        print("[2/3] 追加权限并授予管理员 ...")
        role = db.execute(select(Role).where(Role.role_code == "admin")).scalar_one()
        for code, name, module in NEW_PERMISSIONS:
            p = db.execute(select(Permission).where(Permission.perm_code == code)).scalar_one_or_none()
            if not p:
                p = Permission(perm_code=code, perm_name=name, module=module)
                db.add(p); db.flush()
            if not db.execute(select(RolePermission).where(
                    RolePermission.role_id == role.id, RolePermission.permission_id == p.id)).scalar_one_or_none():
                db.add(RolePermission(role_id=role.id, permission_id=p.id))

        print("[3/3] 补充示例：成品 + BOM + 初始库存 ...")
        # 成品物料
        product = db.execute(select(Material).where(Material.material_code == "P-BG-001")).scalar_one_or_none()
        if not product:
            product = Material(material_code="P-BG-001", material_name="商务双肩包", category="成品",
                               spec="16寸", unit="个", default_color_no="黑色", status=True)
            db.add(product); db.flush()

        # 取三种原料
        m1 = db.execute(select(Material).where(Material.material_code == "M-FB-001")).scalar_one()
        m2 = db.execute(select(Material).where(Material.material_code == "M-FB-002")).scalar_one()
        m3 = db.execute(select(Material).where(Material.material_code == "M-HW-001")).scalar_one()

        bom = db.execute(select(BomHeader).where(BomHeader.product_id == product.id)).scalar_one_or_none()
        if not bom:
            bom = BomHeader(product_id=product.id, version="V1.0", version_name="量产版",
                            status="生效", default_loss_rate=5)
            db.add(bom); db.flush()
            db.add_all([
                BomItem(bom_id=bom.id, material_id=m1.id, qty=1.2, loss_rate=5, unit="米"),
                BomItem(bom_id=bom.id, material_id=m2.id, qty=0.8, loss_rate=3, unit="米"),
                BomItem(bom_id=bom.id, material_id=m3.id, qty=2, loss_rate=1, unit="条"),
            ])

        # 初始库存（原料仓 WH01，id=1）
        from app.models.inventory import Inventory
        if db.query(Inventory).count() == 0:
            for m, q in [(m1, 1000), (m2, 800), (m3, 500)]:
                post_inbound(db, material_id=m.id, warehouse_id=1, qty=q,
                             txn_type="其他入库", ref_type="初始化", operator="system")

        db.commit()
        print("升级完成！")
    finally:
        db.close()


if __name__ == "__main__":
    run()
