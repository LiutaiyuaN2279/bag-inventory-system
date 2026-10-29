r"""全库数据填充：为主数据、采购单据、库存流水、BOM、外发、质检等补充合理规模的演示数据。
幂等：重复运行不会重复生成（以物料数/流水数为判据）。
运行：进入 backend 后执行  .venv/Scripts/python.exe scripts/seed_data.py
"""
import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))          # backend/scripts
ROOT_DIR = os.path.dirname(os.path.dirname(BASE_DIR))          # 仓库根目录

from sqlalchemy import select

from app.core.database import Base, SessionLocal, engine
from app.models import *  # noqa: F401,F403
from app.models.inventory import (
    Inventory,
    InventoryTransaction,
    Stocktake,
    StocktakeItem,
    TransferItem,
    TransferOrder,
)
from app.models.master_data import Location, Material, MaterialColorBatch, Supplier, Warehouse
from app.models.procurement import (
    PurchaseArrival, PurchaseArrivalItem, PurchaseOrder, PurchaseOrderItem,
    PurchaseRequisition, PurchaseRequisitionItem, PurchaseReturn, PurchaseReturnItem,
)
from app.models.ai_ocr import AiOcrItem, AiOcrRecord
from app.models.bom import BomHeader, BomItem
from app.models.outsource import OutsourceOrder, OutsourceOrderItem
from app.models.quality import FqcOrder, IqcItem, IqcOrder, OperationLog
from app.models.rbac import User
from app.services import file_store
from app.utils.numbering import gen_no as _gen_no

random.seed(42)
TODAY = datetime.now()  # 锚定“今天”，保证看板的今日出入库 / 近 7 天趋势有数据

# 幂等唯一单号：时间戳前缀 + 单调计数器，避免同秒冲突
_seq = {"n": 0}
def seq_no(prefix):
    _seq["n"] += 1
    return f"{prefix}{TODAY.strftime('%Y%m%d')}{_seq['n']:05d}"


# ---------- 名称池（贴合箱包行业） ----------
FABRIC = ["600D涤纶牛津布", "420D尼龙牛津布", "1680D双股牛津布", "帆布", "潜水料SBR", "提花布", "迷彩布", "PVC夹网布", "水洗牛皮纸", "绒布"]
LINING = ["210D里布", "190T涤塔夫", "佳积布", "色丁里布", "网眼布", "天鹅绒里"]
ACCESSORY = ["织带", "松紧带", "魔术贴", "包边条", "缝纫线", "拉链布带", "捆条", "泡棉", "PE板", "硬纸板"]
HARDWARE = ["5#尼龙拉链", "8#树脂拉链", "金属拉链", "日字扣", "D形扣", "插扣", "铆钉", "气眼", "磁扣", "拉头", "肩垫", "挂锁"]
PACKING = ["OPP袋", "无纺布袋", "纸箱", "吊牌", "合格证", "干燥剂"]
PRODUCTS = ["商务双肩包", "休闲双肩包", "学生书包", "旅行背包", "电脑包", "单肩斜挎包", "腰包", "手提公文包", "拉杆包", "登山包", "妈咪包", "化妆包"]
COLORS = ["黑色", "藏青", "灰色", "卡其", "军绿", "酒红", "深蓝", "棕色"]
CATEGORY_MAP = {"面料": (FABRIC, "米"), "里料": (LINING, "米"), "辅料": (ACCESSORY, "个"), "五金": (HARDWARE, "个"), "包材": (PACKING, "个")}
DEPT = ["采购部", "生产部", "研发部", "仓储部", "销售部"]


def pick_name(pool, i):
    return f"{pool[i % len(pool)]}{'' if i < len(pool) else '-' + str(i // len(pool) + 1)}"


def seed_master(db):
    # 物料：各分类约 30 个 + 成品 12 个
    if db.query(Material).count() < 50:
        idx = 100
        for cat, (pool, unit) in CATEGORY_MAP.items():
            for i in range(30):
                code = f"M-{cat[:2].upper()}-{idx:03d}"; idx += 1
                if db.query(Material).filter(Material.material_code == code).first():
                    continue
                db.add(Material(material_code=code, material_name=pick_name(pool, i + idx),
                                category=cat, spec=f"常规规格-{i}", unit=unit,
                                default_color_no=random.choice(COLORS),
                                safety_stock=random.choice([0, 100, 200, 300, 500]),
                                min_order_qty=random.choice([50, 100, 200]), status=True))
        for i, name in enumerate(PRODUCTS):
            code = f"P-BG-{i+1:03d}"
            if db.query(Material).filter(Material.material_code == code).first():
                continue
            db.add(Material(material_code=code, material_name=name, category="成品",
                            spec=f"{random.choice([14,15,16,17])}寸", unit="个",
                            default_color_no=random.choice(COLORS), status=True))
        db.commit()
        print(f"  物料新增完成，现存 {db.query(Material).count()} 条")

    # 供应商 40 家
    if db.query(Supplier).count() < 30:
        for i in range(40):
            code = f"S-{i+1:03d}"
            if db.query(Supplier).filter(Supplier.supplier_code == code).first():
                continue
            kinds = ["纺织", "五金", "辅料", "包材", "加工"]
            db.add(Supplier(supplier_code=code,
                            supplier_name=f"{random.choice(['华盛','远东','利达','鑫源','恒丰','瑞达','永盛','宏达'])}{random.choice(kinds)}有限公司-{i+1}",
                            contact=f"联系人{i+1}", phone=f"138{random.randint(10000000,99999999)}",
                            address=f"浙江省{random.choice(['义乌','温州','宁波','杭州'])}市某某路{i+1}号",
                            payment_term=random.choice(["月结30天", "货到付款", "预付30%"]),
                            lead_time_days=random.choice([7, 10, 15, 20]), status=True))
        db.commit()
        print(f"  供应商新增完成，现存 {db.query(Supplier).count()} 条")

    # 仓库 8 个 + 库位
    if db.query(Warehouse).count() < 6:
        wh_defs = [("原料仓", "WH-R"), ("成品仓", "WH-F"), ("辅料仓", "WH-A"), ("五金仓", "WH-H"),
                   ("外发暂存", "WH-O"), ("不良品仓", "WH-B"), ("包材仓", "WH-P"), ("退货仓", "WH-T")]
        for i, (typ, prefix) in enumerate(wh_defs):
            code = f"{prefix}{i+1:02d}"
            if db.query(Warehouse).filter(Warehouse.warehouse_code == code).first():
                continue
            w = Warehouse(warehouse_code=code, warehouse_name=f"{typ}{i+1}", type=typ, manager=f"仓管{i+1}", status=True)
            db.add(w); db.flush()
            for z in range(3):
                db.add(Location(warehouse_id=w.id, location_code=f"{code}-A{z+1:02d}", location_name=f"{z+1}号货架"))
        db.commit()
        print(f"  仓库新增完成，现存 {db.query(Warehouse).count()} 条 / 库位 {db.query(Location).count()} 条")

    # 色号缸号 150 条
    if db.query(MaterialColorBatch).count() < 50:
        mats = db.query(Material).filter(Material.category.in_(["面料", "里料"])).all()
        sups = [s.id for s in db.query(Supplier).all()]
        for _ in range(150):
            m = random.choice(mats)
            db.add(MaterialColorBatch(material_id=m.id, color_no=random.choice(COLORS),
                                      vat_no=f"V{random.randint(202401,202609)}-{random.randint(1,99):02d}",
                                      color_diff_level=random.choice(["A", "A", "A", "B", "C"]),
                                      supplier_id=random.choice(sups)))
        db.commit()
        print(f"  色号缸号新增完成，现存 {db.query(MaterialColorBatch).count()} 条")


def seed_bom(db):
    products = db.query(Material).filter(Material.category == "成品").all()
    mats = db.query(Material).filter(Material.category.in_(["面料", "里料", "辅料", "五金"])).all()
    existing = {b.product_id for b in db.query(BomHeader).all()}
    for p in products:
        if p.id in existing:
            continue
        loss = random.choice([3, 5, 5, 8])
        b = BomHeader(product_id=p.id, version="V1.0", version_name="量产版", status="生效", default_loss_rate=loss)
        db.add(b); db.flush()
        chosen = random.sample(mats, k=min(5, len(mats)))
        for i, m in enumerate(chosen):
            if m.unit in ('个', '条', '件', '套', '张', '双', '块', '只', '副', '箱'):
                uq = random.choice([1, 1, 2, 2, 3])      # 离散单位：单耗取整
            else:
                uq = round(random.uniform(0.2, 2.5), 2)  # 连续单位（米/kg…）：保留小数
            db.add(BomItem(bom_id=b.id, material_id=m.id, qty=uq, loss_rate=loss, unit=m.unit))
    db.commit()
    print(f"  BOM 现存 {db.query(BomHeader).count()} 份")


# ---------- 保持台账与流水一致的库存变动 ----------
def move(db, material_id, warehouse_id, signed, txn_time, txn_type, operator):
    inv = db.query(Inventory).filter(
        Inventory.material_id == material_id, Inventory.warehouse_id == warehouse_id).first()
    if inv:
        inv.qty = (inv.qty or 0) + signed
    else:
        if signed < 0:
            return False
        inv = Inventory(material_id=material_id, warehouse_id=warehouse_id, qty=signed)
        db.add(inv)
    if (inv.qty or 0) < 0:
        inv.qty = 0
    inv.last_move_date = txn_time.date().isoformat()
    db.add(InventoryTransaction(txn_no=seq_no("TXN"), txn_type=txn_type, material_id=material_id,
                                warehouse_id=warehouse_id,
                                in_qty=max(signed, 0), out_qty=max(-signed, 0),
                                ref_type="历史数据", operator=operator, txn_time=txn_time))
    return True


def seed_inventory_and_history(db):
    if db.query(InventoryTransaction).count() > 1500:
        print("  库存流水已存在，跳过")
        return
    mats = db.query(Material).filter(Material.category != "成品").all()
    products = db.query(Material).filter(Material.category == "成品").all()
    whs = [w.id for w in db.query(Warehouse).all()]
    raw_whs = whs[:4]; fin_whs = whs[1:2]
    operators = ["admin", "张三", "李四", "王五", "系统"]

    # 1) 为每个原料仓的大部分物料建立初始库存（入库）
    for wid in raw_whs:
        for m in random.sample(mats, k=max(1, int(len(mats) * 0.6))):
            move(db, m.id, wid, random.randint(200, 3000), TODAY - timedelta(days=random.randint(20, 60)),
                 "其他入库", random.choice(operators))
    # 成品库存
    for wid in fin_whs:
        for p in random.sample(products, k=max(1, int(len(products) * 0.7))):
            move(db, p.id, wid, random.randint(50, 800), TODAY - timedelta(days=random.randint(10, 40)),
                 "其他入库", random.choice(operators))
    db.commit()

    # 2) 近 60 天每日随机出入库，形成趋势与流水
    tx_types_in = ["采购入库", "盘盈入库", "其他入库"]
    tx_types_out = ["领料出库", "盘亏出库", "其他出库"]
    for day in range(60):
        d = TODAY - timedelta(days=day)
        for _ in range(random.randint(8, 20)):
            m = random.choice(mats); wid = random.choice(raw_whs)
            if random.random() < 0.55:
                move(db, m.id, wid, random.randint(50, 1500), d.replace(hour=random.randint(8, 17)),
                     random.choice(tx_types_in), random.choice(operators))
            else:
                move(db, m.id, wid, -random.randint(10, 600), d.replace(hour=random.randint(8, 17)),
                     random.choice(tx_types_out), random.choice(operators))
        if day % 5 == 0:
            db.commit()
    db.commit()
    print(f"  库存台账 {db.query(Inventory).count()} 条，流水 {db.query(InventoryTransaction).count()} 条")


def seed_procurement(db):
    if db.query(PurchaseOrder).count() > 80:
        print("  采购单据已存在，跳过")
        return
    mats = [m for m in db.query(Material).all()]
    sups = [s.id for s in db.query(Supplier).all()]
    names = ["张伟", "李娜", "王强", "赵敏", "陈静", "刘洋"]

    # 请购单 90
    for _ in range(90):
        pr = PurchaseRequisition(req_no=seq_no("PR"), requisitioner=random.choice(names),
                                 dept=random.choice(DEPT), status=random.choice(["已审核", "已审核", "已关闭", "草稿"]),
                                 created_at=TODAY - timedelta(days=random.randint(0, 120)))
        db.add(pr); db.flush()
        for _ in range(random.randint(1, 4)):
            m = random.choice(mats)
            db.add(PurchaseRequisitionItem(pr_id=pr.id, material_id=m.id, qty=random.randint(50, 2000),
                                           unit=m.unit, ordered_qty=random.randint(0, 100),
                                           requirement_date=(TODAY + timedelta(days=random.randint(-10, 30))).date().isoformat()))

    # 采购订单 70
    for _ in range(70):
        sid = random.choice(sups)
        total = 0
        items = []
        for _ in range(random.randint(1, 4)):
            m = random.choice(mats)
            qty = random.randint(100, 3000); price = round(random.uniform(2, 80), 2)
            total += qty * price
            items.append((m, qty, price))
        po = PurchaseOrder(order_no=seq_no("PO"), supplier_id=sid,
                           status=random.choice(["已审核", "已完成", "已完成", "部分到货", "草稿"]),
                           total_amount=round(total, 2), created_at=TODAY - timedelta(days=random.randint(0, 120)))
        db.add(po); db.flush()
        for m, qty, price in items:
            arrived = random.randint(0, qty) if po.status in ("部分到货", "已完成") else 0
            inbound = arrived if po.status == "已完成" else (arrived if random.random() < 0.7 else max(0, arrived - random.randint(0, 50)))
            db.add(PurchaseOrderItem(order_id=po.id, material_id=m.id, qty=qty, unit_price=price,
                                     unit=m.unit, arrived_qty=arrived, inbound_qty=inbound))

    # 到货单 55（带明细，库存已由 seed_inventory 统一生成，此处仅做单据记录）
    # 每张到货单挂一张「不同的」采购订单：原实现每轮都取最新一张非草稿订单，
    # 结果 55 张到货单全是同一供应商、同一批明细，到货页供应商列因此整列重复。
    whs = [w.id for w in db.query(Warehouse).limit(4).all()]
    pos = db.query(PurchaseOrder).filter(PurchaseOrder.status != "草稿").all()
    random.shuffle(pos)
    for po in pos[:55]:
        items = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.order_id == po.id).all()
        if not items:
            continue
        arr = PurchaseArrival(arrival_no=seq_no("AR"), order_id=po.id, supplier_id=po.supplier_id,
                              status=random.choice(["已验收", "已验收", "待验收"]),
                              created_at=TODAY - timedelta(days=random.randint(0, 90)))
        db.add(arr); db.flush()
        for oi in items:
            db.add(PurchaseArrivalItem(arrival_id=arr.id, order_item_id=oi.id, material_id=oi.material_id,
                                       arrived_qty=oi.arrived_qty, qualified_qty=oi.inbound_qty,
                                       warehouse_id=random.choice(whs)))

    # 采购退货 18
    for _ in range(18):
        rt = PurchaseReturn(return_no=seq_no("RT"), supplier_id=random.choice(sups),
                            status=random.choice(["已审核", "已审核", "草稿"]),
                            created_at=TODAY - timedelta(days=random.randint(0, 80)))
        db.add(rt); db.flush()
        for _ in range(random.randint(1, 3)):
            m = random.choice(mats)
            db.add(PurchaseReturnItem(return_id=rt.id, material_id=m.id, qty=random.randint(10, 300),
                                      warehouse_id=random.choice(whs)))
    db.commit()
    print(f"  请购 {db.query(PurchaseRequisition).count()} / 订单 {db.query(PurchaseOrder).count()} / "
          f"到货 {db.query(PurchaseArrival).count()} / 退货 {db.query(PurchaseReturn).count()}")


def seed_outsource(db):
    if db.query(OutsourceOrder).count() > 15:
        print("  外发加工已存在，跳过"); return
    products = db.query(Material).filter(Material.category == "成品").all()
    mats = db.query(Material).filter(Material.category != "成品").all()
    sups = [s.id for s in db.query(Supplier).all()]
    whs = [w.id for w in db.query(Warehouse).all()]
    for _ in range(25):
        p = random.choice(products)
        plan = random.randint(50, 500)
        received = plan if random.random() < 0.6 else random.randint(0, plan)
        status = "已完成" if received >= plan else ("部分收回" if received > 0 else random.choice(["已发料", "草稿"]))
        o = OutsourceOrder(order_no=seq_no("OS"), supplier_id=random.choice(sups), product_id=p.id,
                           out_warehouse_id=random.choice(whs[:4]), in_warehouse_id=random.choice(whs[1:2]),
                           plan_qty=plan, received_qty=received, status=status,
                           created_at=TODAY - timedelta(days=random.randint(0, 60)))
        db.add(o); db.flush()
        for m in random.sample(mats, k=min(4, len(mats))):
            qty = random.randint(20, 500)
            db.add(OutsourceOrderItem(order_id=o.id, material_id=m.id, qty=qty,
                                      issued_qty=qty if status != "草稿" else 0, unit=m.unit))
    db.commit()
    print(f"  外发加工现存 {db.query(OutsourceOrder).count()} 单")


def seed_quality(db):
    mats = db.query(Material).filter(Material.category != "成品").all()
    products = db.query(Material).filter(Material.category == "成品").all()
    sups = [s.id for s in db.query(Supplier).all()]
    inspectors = ["质检员A", "质检员B", "质检员C"]
    if db.query(IqcOrder).count() < 20:
        for _ in range(40):
            o = IqcOrder(qc_no=seq_no("IQC"), supplier_id=random.choice(sups),
                         status=random.choice(["合格", "合格", "不合格", "让步接收"]),
                         inspector=random.choice(inspectors), created_at=TODAY - timedelta(days=random.randint(0, 90)))
            db.add(o); db.flush()
            for _ in range(random.randint(1, 3)):
                sample = random.randint(20, 200)
                db.add(IqcItem(iqc_id=o.id, material_id=random.choice(mats).id, sample_qty=sample,
                               qualified_qty=random.randint(int(sample*0.7), sample),
                               result=o.status, remark=""))
        db.commit()
    if db.query(FqcOrder).count() < 20:
        for _ in range(40):
            p = random.choice(products); check = random.randint(30, 300)
            db.add(FqcOrder(qc_no=seq_no("FQC"), product_id=p.id, batch_no=f"B{random.randint(202401,202609):06d}",
                            check_qty=check, qualified_qty=random.randint(int(check*0.8), check),
                            status=random.choice(["合格", "合格", "不合格"]),
                            inspector=random.choice(inspectors), created_at=TODAY - timedelta(days=random.randint(0, 90))))
        db.commit()
    # 待检来料检：质检员首页的「来料待检 / 待检单据」必须有真实可处理的单据，
    # 否则质检员登录后看板只剩空白。挂在最近的「待验收」到货单上（来料检在验收前完成），
    # 抽检数已定、合格数留 0、结果待录，才符合「待检」的真实状态。
    if db.query(IqcOrder).filter(IqcOrder.status == "待检").count() == 0:
        # 取最近若干「待验收」到货单，按供应商去重后取 8 单：避免同一天到货集中在同一家供应商
        arrivals = (db.query(PurchaseArrival).filter(PurchaseArrival.status == "待验收")
                    .order_by(PurchaseArrival.created_at.desc()).limit(80).all())
        picked, seen_supplier = [], set()
        for ar in arrivals:
            if ar.supplier_id in seen_supplier:
                continue
            seen_supplier.add(ar.supplier_id)
            picked.append(ar)
            if len(picked) >= 8:
                break
        if len(picked) < 8:   # 供应商不足 8 家时，用剩余待验收单补足
            chosen = {a.id for a in picked}
            for ar in arrivals:
                if ar.id in chosen:
                    continue
                picked.append(ar)
                if len(picked) >= 8:
                    break
        for ar in picked:
            o = IqcOrder(qc_no=seq_no("IQC"), supplier_id=ar.supplier_id, arrival_id=ar.id,
                         status="待检", inspector=random.choice(inspectors),
                         created_at=TODAY - timedelta(days=random.randint(0, 2), hours=random.randint(0, 5)))
            db.add(o); db.flush()
            for _ in range(random.randint(1, 3)):
                db.add(IqcItem(iqc_id=o.id, material_id=random.choice(mats).id,
                               sample_qty=random.randint(20, 200), qualified_qty=0,
                               result="待检", remark=""))
        db.commit()
    # 待检成品检：同上，给质检员留可执行的成品检验批次（今日 / 近两日新到批次）
    if db.query(FqcOrder).filter(FqcOrder.status == "待检").count() == 0:
        for _ in range(6):
            p = random.choice(products); check = random.randint(30, 300)
            db.add(FqcOrder(qc_no=seq_no("FQC"), product_id=p.id, batch_no=f"B{random.randint(202401, 202609):06d}",
                            check_qty=check, qualified_qty=0, status="待检",
                            inspector=random.choice(inspectors),
                            created_at=TODAY - timedelta(days=random.randint(0, 2), hours=random.randint(0, 5))))
        db.commit()
    print(f"  IQC {db.query(IqcOrder).count()}（待检 {db.query(IqcOrder).filter(IqcOrder.status == '待检').count()}）"
          f" / FQC {db.query(FqcOrder).count()}（待检 {db.query(FqcOrder).filter(FqcOrder.status == '待检').count()}）")


def _match_material_id(db, name):
    """与后端 ai_ocr._match_material 同口径：精确 → 模糊 → 反向包含。

    演示主数据里辅料/面料名带序号后缀（如「420D尼龙牛津布-11」），只精确匹配的话
    这两行明细会永远匹配不上，页面上显示成未匹配，与真实识别流程不一致。
    """
    name = (name or "").strip()
    if not name:
        return None
    m = db.query(Material).filter(Material.material_name == name).first()
    if m:
        return m.id
    m = db.query(Material).filter(Material.material_name.like(f"%{name}%")).first()
    if m:
        return m.id
    for x in db.query(Material).all():
        nm = x.material_name or ""
        if nm and (name in nm or nm in name):
            return x.id
    return None


def seed_ai_ocr(db):
    """AI 单据识别的历史识别记录：让「AI 单据识别」页开箱就有可核对的样例。

    默认引擎是 mock，识别结果固定为「温州宏远面料有限公司」的两行面料/拉链，
    这里按同样的口径造两条历史记录（一条待确认、一条已导入），物料与供应商
    都能匹配上演示数据，便于直接演示「核对 → 导入生成到货单」。其中「已导入」
    的那条挂在同一供应商的一张真实到货单上，这样它在前端表现为「不可再导入、
    也不可删除」，与真实导入后的状态一致。

    原图：识别记录现在会保留所识别的原照片，所以种子里也要把图片落到归档目录，
    否则演示时「照片」列全是「未留存」，看不出这个功能。
    图片直接拷贝仓库自带的 `test_docs/送货单_测试样张.png`，
    不额外依赖 Pillow 之类图像库。
    """
    if db.query(AiOcrRecord).count():
        print("  AI 识别记录已存在，跳过")
        return
    supplier = db.query(Supplier).filter(Supplier.supplier_name.like("%宏远%")).first()
    # 「已导入」的样例要挂到一张真实到货单上，否则前端「已导入但可删除」状态自相矛盾
    linked = None
    if supplier:
        linked = (db.query(PurchaseArrival)
                  .filter(PurchaseArrival.supplier_id == supplier.id)
                  .order_by(PurchaseArrival.id.desc()).first())
    samples = [
        # 先插历史（id 小），后插最新的（id 大）——列表默认按 id 倒序，最新的记录显示在最上面
        # (文件名, 单号, 状态, 距今天数, 识别人, 明细[(物料名, 规格, 单位, 数量)])
        ("送货单_20260506.png", "DN20260506018", "已导入", 8, "buyer",
         [("420D尼龙牛津布", "幅宽150cm", "米", 600), ("拉链布带", "宽25mm", "米", 1200)]),
        ("送货单_测试样张.png", "DN20260513001", "待确认", 0, "keeper",
         [("600D涤纶牛津布", "幅宽150cm", "米", 800), ("5#尼龙拉链", "70cm", "条", 2000)]),
    ]
    src = os.path.join(ROOT_DIR, "test_docs", "送货单_测试样张.png")
    src_bytes = b""
    if os.path.isfile(src):
        with open(src, "rb") as fp:
            src_bytes = fp.read()
    else:
        print(f"  ! 未找到样张 {src}，识别记录将没有原图")
    for i, (fname, doc_no, status, days, who, items) in enumerate(samples):
        rec = AiOcrRecord(
            image_name=fname, image_size=(len(src_bytes) or 120988), doc_type="送货单", doc_no=doc_no,
            supplier_name=(supplier.supplier_name if supplier else "温州宏远面料有限公司"),
            supplier_id=(supplier.id if supplier else None),
            arrival_id=(linked.id if (status == "已导入" and linked) else None),
            status=status, provider="mock",
            message="识别完成，请核对后导入" if status == "待确认" else "已生成采购到货单",
            created_by=who,
            created_at=TODAY - timedelta(days=days, hours=random.randint(1, 8)),
        )
        db.add(rec)
        db.flush()
        # 归档原图：与 /ai-ocr/recognize 走同一个 file_store（同样按记录 id 命名）
        if src_bytes:
            rel, ext = file_store.save_image(src_bytes, fname, "image/png", ref=rec.id)
            rec.image_path = rel
            rec.image_ext = ext
            rec.image_size = len(src_bytes)
        for name, spec, unit, qty in items:
            mid = _match_material_id(db, name)
            db.add(AiOcrItem(record_id=rec.id, material_name=name, spec=spec, unit=unit,
                             qty=qty, material_id=mid, matched=bool(mid)))
    db.commit()
    print(f"  AI 识别记录现存 {db.query(AiOcrRecord).count()} 条 / 明细 {db.query(AiOcrItem).count()} 条"
          f" / 原图 {sum(1 for r in db.query(AiOcrRecord).all() if r.image_path)} 张")


def seed_logs(db):
    if db.query(OperationLog).count() > 100:
        return
    user = db.query(User).first()
    name = user.username if user else "admin"
    actions = [("POST", "/api/v1/purchase-orders", "采购订单-新增"),
               ("PUT", "/api/v1/bom/1", "BOM-版本生效"),
               ("POST", "/api/v1/outsource-orders/1/issue", "外发加工-发料"),
               ("POST", "/api/v1/purchase-arrivals/1/approve", "到货验收-审核")]
    for _ in range(150):
        m, p, a = random.choice(actions)
        db.add(OperationLog(username=name, method=m, path=p, action=a, ip="127.0.0.1",
                            status_code=200, elapsed_ms=random.randint(3, 60),
                            ua="Mozilla/5.0 (Windows NT 10.0; Win64; x64) DemoBrowser/1.0",
                            created_at=TODAY - timedelta(days=random.randint(0, 60), hours=random.randint(0, 23))))
    db.commit()
    print(f"  操作日志现存 {db.query(OperationLog).count()} 条")


def seed_stocktake_and_transfer(db):
    """盘点单与仓库调拨单：让「库存盘点」「仓库调拨」两个演示页有真实数据。

    盘点差异按 盘盈入库 / 盘亏出库 记流水，已审核的调拨按 调拨出库 / 调拨入库
    记流水，因此台账与流水始终一致（不直接改 qty）。
    """
    if db.query(Stocktake).count() or db.query(TransferOrder).count():
        print("  盘点/调拨已存在，跳过")
        return
    mats = db.query(Material).all()
    raw = [m for m in mats if m.category != "成品"]
    prods = [m for m in mats if m.category == "成品"] or mats
    whs = db.query(Warehouse).all()
    if not raw or len(whs) < 3:
        return
    operators = ["admin", "张三", "李四", "王五"]

    def book_qty(mid, wid):
        inv = db.query(Inventory).filter(Inventory.material_id == mid,
                                          Inventory.warehouse_id == wid).first()
        return float(inv.qty or 0) if inv else 0.0

    # 1) 已完成的盘点单：有盈亏，按差异补流水
    src = whs[0]
    st = Stocktake(stocktake_no=seq_no("PD"), warehouse_id=src.id, status="已完成",
                   remark="月末原料仓全盘", created_at=TODAY - timedelta(days=6))
    db.add(st)
    db.flush()
    for m in random.sample(raw, k=min(9, len(raw))):
        book = book_qty(m.id, src.id)
        counted = max(0.0, book + random.choice([0, 0, 0, 2, -3, 5, -1, 8]))
        db.add(StocktakeItem(stocktake_id=st.id, material_id=m.id,
                             book_qty=book, counted_qty=counted))
        diff = counted - book
        if diff:
            move(db, m.id, src.id, diff, TODAY - timedelta(days=6),
                 "盘盈入库" if diff > 0 else "盘亏出库", "admin")

    # 2) 盘点中的盘点单：成品仓抽盘，实盘暂等账面（待人工录入）
    st2 = Stocktake(stocktake_no=seq_no("PD"), warehouse_id=whs[1].id, status="盘点中",
                    remark="成品仓抽盘（进行中）", created_at=TODAY - timedelta(days=1))
    db.add(st2)
    db.flush()
    for m in random.sample(prods, k=min(6, len(prods))):
        book = book_qty(m.id, whs[1].id)
        db.add(StocktakeItem(stocktake_id=st2.id, material_id=m.id,
                             book_qty=book, counted_qty=book))

    # 2.5) 其余盘点单：跨仓库、跨三个月，状态覆盖 已完成 / 盘点中 / 已驳回。
    # 只放 2~3 张会让「库存盘点」列表大半屏是空白，且不像真实企业的盘点节奏；
    # 已完成的盘点才按差异补流水，盘点中/已驳回一律不入账（保持台账与流水一致）。
    plan = [("盘点中", whs[2], 1, "辅料仓月度循环盘点"),
            ("已完成", whs[3], 8, "五金仓季度全盘"),
            ("已完成", whs[4], 15, "包材仓循环盘点"),
            ("已驳回", whs[5], 22, "原材料仓抽盘（差异未确认）"),
            ("已完成", whs[6], 29, "成品仓月度盘点"),
            ("已完成", whs[7], 37, "原材料仓年度盘点"),
            ("盘点中", whs[8], 44, "辅料仓抽盘（进行中）"),
            ("已完成", whs[9], 52, "五金仓抽盘"),
            ("已完成", whs[10 % len(whs)], 61, "包材仓季度盘点"),
            ("已驳回", whs[0], 74, "成品仓全盘（复核未通过）")]
    for status, wh, ago, note in plan:
        stx = Stocktake(stocktake_no=seq_no("PD"), warehouse_id=wh.id, status=status,
                        remark=note, created_at=TODAY - timedelta(days=ago))
        db.add(stx)
        db.flush()
        pool = [inv.material_id for inv in db.query(Inventory).filter(
            Inventory.warehouse_id == wh.id).all()]
        if not pool:
            pool = [m.id for m in mats]
        for mid in random.sample(pool, k=min(random.randint(4, 9), len(pool))):
            book = book_qty(mid, wh.id)
            if status == "已完成":
                counted = max(0.0, book + random.choice([0, 0, 0, 0, 2, -3, 5, -1, 8, -6]))
            elif status == "盘点中":
                counted = book
            else:  # 已驳回：录过差异但不入账
                counted = max(0.0, book + random.choice([0, 3, -2]))
            db.add(StocktakeItem(stocktake_id=stx.id, material_id=mid,
                                 book_qty=book, counted_qty=counted))
            diff = counted - book
            if status == "已完成" and diff:
                move(db, mid, wh.id, diff, TODAY - timedelta(days=ago),
                     "盘盈入库" if diff > 0 else "盘亏出库", random.choice(operators))

    # 3) 调拨单：已审核（已过账）/ 草稿 / 已作废，跨仓库、跨三个月。
    # 同样是为了让「仓库调拨」列表有真实密度，而不是 3 行 + 半屏空白。
    specs = [("已审核", True, 4), ("草稿", False, 2), ("已作废", False, 9)]
    status_cycle = ["已审核", "草稿", "草稿", "已审核", "已作废", "已审核",
                    "草稿", "已审核", "已作废", "已审核", "草稿", "已审核", "已作废"]
    for k, status in enumerate(status_cycle):
        specs.append((status, status == "已审核", 12 + k * 6))
    for idx, (status, executed, ago) in enumerate(specs):
        fw, tw = whs[idx % len(whs)], whs[(idx + 1) % len(whs)]
        if fw.id == tw.id:
            tw = whs[(idx + 2) % len(whs)]
        op = random.choice(operators)
        when = TODAY - timedelta(days=ago, hours=random.randint(0, 7))
        t = TransferOrder(transfer_no=seq_no("TR"), from_warehouse_id=fw.id,
                          to_warehouse_id=tw.id, status=status, executed=executed,
                          operator=op, remark="仓库间库存调拨", created_at=when,
                          approve_time=when if status == "已审核" else None,
                          void_time=when if status == "已作废" else None)
        db.add(t)
        db.flush()
        # 只从调出仓有库存的物料里选，保证「已审核」的调拨真能过账
        pool = [inv.material_id for inv in db.query(Inventory).filter(
            Inventory.warehouse_id == fw.id, Inventory.qty > 0).all()]
        picks = random.sample(pool, k=min(random.randint(3, 6), len(pool))) if pool else []
        for mid in picks:
            m = db.query(Material).get(mid)
            if not m:
                continue
            qty = float(random.randint(20, 200))
            db.add(TransferItem(transfer_id=t.id, material_id=m.id, qty=qty,
                                unit=m.unit or "个", remark=""))
            if executed:
                move(db, m.id, fw.id, -qty, when, "调拨出库", op)
                move(db, m.id, tw.id, qty, when, "调拨入库", op)
    db.commit()
    print(f"  盘点单 {db.query(Stocktake).count()} 张 / 盘点明细 {db.query(StocktakeItem).count()} 行"
          f" / 调拨单 {db.query(TransferOrder).count()} 张 / 调拨明细 {db.query(TransferItem).count()} 行")


def main():
    print("创建/校验表结构 ...")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_master(db)
        seed_bom(db)
        seed_inventory_and_history(db)
        seed_procurement(db)
        seed_outsource(db)
        seed_quality(db)
        seed_ai_ocr(db)
        seed_stocktake_and_transfer(db)
        seed_logs(db)
        print("\n数据填充完成！各表当前数据量：")
        for cls in [Material, Supplier, Warehouse, Location, MaterialColorBatch,
                    BomHeader, PurchaseRequisition, PurchaseOrder, PurchaseArrival, PurchaseReturn,
                    Inventory, InventoryTransaction, OutsourceOrder, IqcOrder, FqcOrder,
                    Stocktake, StocktakeItem, TransferOrder, TransferItem,
                    AiOcrRecord, AiOcrItem, OperationLog]:
            print(f"  {cls.__tablename__:32s} {db.query(cls).count()}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
