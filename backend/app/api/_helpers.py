"""接口公共辅助：名称映射、行转字典。"""
from app.models.master_data import Material, Supplier, Warehouse


def load_maps(db):
    materials = {m.id: m.material_name for m in db.query(Material).all()}
    warehouses = {w.id: w.warehouse_name for w in db.query(Warehouse).all()}
    suppliers = {s.id: s.supplier_name for s in db.query(Supplier).all()}
    return materials, warehouses, suppliers


def material_meta(db):
    """返回 {material_id: {"name":..., "spec":..., "unit":...}}，用于明细补全规格/单位。"""
    return {m.id: {"name": m.material_name, "spec": m.spec or "", "unit": m.unit or ""}
            for m in db.query(Material).all()}
