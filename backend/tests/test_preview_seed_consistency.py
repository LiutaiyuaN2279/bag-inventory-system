"""采购演示单据一致性：只在替代数据库模块及全新内存库中执行真实生成函数。"""
import contextlib
import importlib.util
import io
from pathlib import Path
import random
import sys
import types
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


class PreviewSeedConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        database = types.ModuleType("app.core.database")
        database.Base = declarative_base()
        database.engine = cls.engine
        database.SessionLocal = sessionmaker(bind=cls.engine)
        cls.modules = patch.dict(sys.modules)
        cls.modules.start()
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        sys.modules["app.core.database"] = database
        sys.modules["app.services.file_store"] = types.ModuleType("app.services.file_store")
        backend = Path(__file__).resolve().parents[1]
        cls.path = patch.object(sys, "path", [str(backend), *sys.path])
        cls.path.start()
        spec = importlib.util.spec_from_file_location("_preview_seed_under_test", backend / "scripts/seed_data.py")
        cls.seed = importlib.util.module_from_spec(spec)
        state = random.getstate()
        try:
            spec.loader.exec_module(cls.seed)
        finally:
            random.setstate(state)
        cls.base = database.Base

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        cls.path.stop()
        cls.modules.stop()

    def generate(self, seed_number, forced_status=None, pending=False, upper=False):
        s = self.seed
        self.base.metadata.drop_all(self.engine)
        self.base.metadata.create_all(self.engine)
        db = s.SessionLocal()
        self.addCleanup(db.close)
        db.add(s.Material(material_code="M1", material_name="合成物料", unit="个"))
        db.add(s.Supplier(supplier_code="S1", supplier_name="合成供应商"))
        db.add(s.Warehouse(warehouse_code="W1", warehouse_name="合成仓库"))
        db.commit()
        rng = random.Random(seed_number)
        original_choice, original_randint = rng.choice, rng.randint

        def choose(values):
            if forced_status and values == ["已审核", "已完成", "已完成", "部分到货", "草稿"]:
                return forced_status
            if forced_status and values == ["已验收", "待验收"]:
                return "待验收" if pending else "已验收"
            return original_choice(values)

        def integer(low, high):
            if forced_status and low == 1 and high >= 99:
                return high if upper else low
            return original_randint(low, high)

        rng.choice = choose
        rng.randint = integer
        with patch.object(s, "random", rng), contextlib.redirect_stdout(io.StringIO()):
            s.seed_procurement(db)
        return db

    def assert_consistent(self, db):
        s = self.seed
        orders = db.query(s.PurchaseOrder).all()
        self.assertEqual(len(orders), 70)
        self.assertEqual(db.query(s.PurchaseRequisition).count(), 90)
        self.assertEqual(db.query(s.PurchaseReturn).count(), 18)
        arrivals = {a.id: a for a in db.query(s.PurchaseArrival)}
        items = {i.id: i for i in db.query(s.PurchaseOrderItem)}
        arrived = dict.fromkeys(items, 0)
        inbound = dict.fromkeys(items, 0)
        orders_by_id = {o.id: o for o in orders}
        for a in arrivals.values():
            order = orders_by_id[a.order_id]
            self.assertEqual(a.supplier_id, order.supplier_id)
            self.assertGreaterEqual(a.created_at, order.created_at)
            self.assertLessEqual(a.created_at, s.TODAY)
            self.assertNotIn(order.status, ("草稿", "已审核"))
            self.assertGreater(db.query(s.PurchaseArrivalItem).filter_by(arrival_id=a.id).count(), 0)
        for ai in db.query(s.PurchaseArrivalItem):
            a, oi = arrivals[ai.arrival_id], items[ai.order_item_id]
            self.assertEqual(oi.order_id, a.order_id)
            self.assertEqual(ai.material_id, oi.material_id)
            self.assertGreater(ai.arrived_qty, 0)
            self.assertGreaterEqual(ai.qualified_qty, 0)
            self.assertLessEqual(ai.qualified_qty, ai.arrived_qty)
            if a.status != "已驳回":
                arrived[oi.id] += ai.arrived_qty
            if a.status == "已验收":
                inbound[oi.id] += ai.qualified_qty
        for order in orders:
            lines = [i for i in items.values() if i.order_id == order.id]
            self.assertTrue(lines)
            for oi in lines:
                self.assertGreater(oi.qty, 0)
                self.assertGreaterEqual(oi.inbound_qty, 0)
                self.assertLessEqual(oi.inbound_qty, oi.arrived_qty)
                self.assertLessEqual(oi.arrived_qty, oi.qty)
                self.assertEqual(oi.arrived_qty, arrived[oi.id])
                self.assertEqual(oi.inbound_qty, inbound[oi.id])
                if order.status == "已完成":
                    self.assertEqual(oi.inbound_qty, oi.qty)
                if order.status in ("草稿", "已审核"):
                    self.assertEqual((oi.arrived_qty, oi.inbound_qty), (0, 0))
            if order.status == "部分到货":
                self.assertGreater(sum(i.arrived_qty for i in lines), 0)
                self.assertTrue(any(i.inbound_qty < i.qty for i in lines))
        # 同一物料多明细也必须逐order_item_id对应，不能按material_id合并。
        self.assertTrue(any(sum(i.order_id == o.id for i in items.values()) > 1 for o in orders))
        self.assertEqual(db.query(s.Inventory).count(), 0)
        self.assertEqual(db.query(s.InventoryTransaction).count(), 0)

    def test_full_generated_documents_across_seeds(self):
        for number in range(20):
            with self.subTest(seed=number):
                db = self.generate(number)
                self.assert_consistent(db)
                self.assertEqual({o.status for o in db.query(self.seed.PurchaseOrder)},
                                 {"草稿", "已审核", "部分到货", "已完成"})
                self.assertEqual({a.status for a in db.query(self.seed.PurchaseArrival)},
                                 {"待验收", "已验收"})
                partial_ids = {o.id for o in db.query(self.seed.PurchaseOrder).filter_by(status="部分到货")}
                self.assertEqual({a.status for a in db.query(self.seed.PurchaseArrival) if a.order_id in partial_ids},
                                 {"待验收", "已验收"})
                db.close()

    def test_completed_all_lines_fully_received(self):
        self.assert_consistent(self.generate(42, "已完成"))

    def test_draft_has_no_arrivals(self):
        db = self.generate(42, "草稿")
        self.assert_consistent(db)
        self.assertEqual(db.query(self.seed.PurchaseArrival).count(), 0)

    def test_approved_without_arrival_has_no_empty_document(self):
        db = self.generate(42, "已审核")
        self.assert_consistent(db)
        self.assertEqual(db.query(self.seed.PurchaseArrival).count(), 0)

    def test_pending_partial_does_not_contribute_inbound(self):
        db = self.generate(42, "部分到货", pending=True)
        self.assert_consistent(db)
        self.assertTrue(all(i.inbound_qty == 0 for i in db.query(self.seed.PurchaseOrderItem)))
        self.assertTrue(all(i.qualified_qty > 0 for i in db.query(self.seed.PurchaseArrivalItem)))

    def test_accepted_partial_minimum_and_remaining_one(self):
        for upper in (False, True):
            with self.subTest(upper=upper):
                db = self.generate(42, "部分到货", upper=upper)
                self.assert_consistent(db)
                for i in db.query(self.seed.PurchaseOrderItem):
                    self.assertEqual(i.arrived_qty, i.qty - 1 if upper else 1)
                    self.assertEqual(i.inbound_qty, i.arrived_qty)
                db.close()


if __name__ == "__main__":
    unittest.main()

