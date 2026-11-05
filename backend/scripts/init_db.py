"""数据库初始化：建表 + 种子数据（演示账号、权限、示例物料/供应商/仓库）。

运行方式（在 backend 目录下）：
    python scripts/init_db.py

说明：本脚本是唯一创建 users 表记录的地方，必须最先执行；四个非 admin 演示账号
由无顶层写库的 demo_roles 初始化绑定；已有账号及角色定制保持不变。
"""
import sys
import os

# 将 backend 目录加入 sys.path，保证 `import app` 可用
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.services.demo_roles import initialize_demo_roles
from app.models import (  # noqa: F401  触发模型注册
    Material,
    Permission,
    Role,
    RolePermission,
    Supplier,
    User,
    UserRole,
    Warehouse,
)
from app.models.master_data import Location, MaterialColorBatch  # noqa: F401


# 权限码定义（模块:资源:动作）
PERMISSIONS = [
    ("dashboard:view", "看板查看", "dashboard"),
    ("basic:material:list", "物料-查看", "basic-data"),
    ("basic:material:add", "物料-新增", "basic-data"),
    ("basic:material:edit", "物料-编辑", "basic-data"),
    ("basic:material:delete", "物料-删除", "basic-data"),
    ("basic:supplier:list", "供应商-查看", "basic-data"),
    ("basic:supplier:add", "供应商-新增", "basic-data"),
    ("basic:supplier:edit", "供应商-编辑", "basic-data"),
    ("basic:supplier:delete", "供应商-删除", "basic-data"),
    ("basic:warehouse:list", "仓库-查看", "basic-data"),
    ("basic:warehouse:add", "仓库-新增", "basic-data"),
    ("basic:warehouse:edit", "仓库-编辑", "basic-data"),
    ("basic:warehouse:delete", "仓库-删除", "basic-data"),
]


# 演示账号：五个角色各一个，口令统一（与 README、登录页提示保持一致）
DEMO_PASSWORD = "admin123"
DEMO_USERS = [
    ("admin", "系统管理员"),
    ("manager", "运营主管"),
    ("buyer", "采购员"),
    ("keeper", "仓管员"),
    ("qc", "质检员"),
]


def init():
    print("[1/3] 创建数据表 ...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        print("[2/3] 初始化 RBAC ...")
        initialize_demo_roles(db, hash_password)

        print("[3/3] 初始化示例主数据 ...")
        # 示例供应商
        if db.query(Supplier).count() == 0:
            db.add_all([
                Supplier(supplier_code="SUP001", supplier_name="温州宏远面料有限公司", contact="李经理",
                         phone="13800000001", payment_term="月结30天", lead_time_days=7, status=True),
                Supplier(supplier_code="SUP002", supplier_name="义乌诚信五金商行", contact="王主管",
                         phone="13800000002", payment_term="货到付款", lead_time_days=3, status=True),
            ])
        # 示例仓库
        if db.query(Warehouse).count() == 0:
            db.add_all([
                Warehouse(warehouse_code="WH01", warehouse_name="原材料仓", type="原料仓", manager="张三", status=True),
                Warehouse(warehouse_code="WH02", warehouse_name="成品仓", type="成品仓", manager="李四", status=True),
                Warehouse(warehouse_code="WH03", warehouse_name="外发暂存仓", type="外发暂存", manager="王五", status=True),
            ])
        # 示例物料（含面料色号、五金）
        if db.query(Material).count() == 0:
            db.add_all([
                Material(material_code="M-FB-001", material_name="600D涤纶牛津布", category="面料",
                         spec="幅宽150cm", unit="米", default_color_no="黑色", safety_stock=500, min_order_qty=100, status=True),
                Material(material_code="M-FB-002", material_name="210D里布", category="里料",
                         spec="幅宽145cm", unit="米", default_color_no="黑色", safety_stock=300, min_order_qty=50, status=True),
                Material(material_code="M-HW-001", material_name="5#尼龙拉链", category="五金",
                         spec="70cm", unit="条", default_color_no="黑色", safety_stock=200, min_order_qty=50, status=True),
            ])

        db.commit()
        print("初始化完成！默认账号 admin / admin123")
    finally:
        db.close()


if __name__ == "__main__":
    init()
