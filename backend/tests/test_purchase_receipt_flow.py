"""采购分批收货：仅组装真实采购路由，以HTTPX ASGI请求访问全新内存库。"""
import asyncio
import itertools
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool


class PurchaseReceiptFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = patch.dict(sys.modules)
        cls.modules.start()
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        cls.path = patch.object(sys, "path", [str(Path(__file__).resolve().parents[1]), *sys.path])
        cls.path.start()
        database = types.ModuleType("app.core.database")
        database.Base = declarative_base()
        database.engine = cls.engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                                                     connect_args={"check_same_thread": False})
        @event.listens_for(cls.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        database.SessionLocal = cls.Session = sessionmaker(bind=cls.engine)
        def get_db():
            raise AssertionError("must override DB dependency with synthetic session")
        database.get_db = get_db
        sys.modules["app.core.database"] = database
        security = types.ModuleType("app.core.security")
        def unused_password(*_):
            raise AssertionError("password authentication is not part of this synthetic test")
        security.verify_password = unused_password
        sys.modules["app.core.security"] = security
        from app import models
        from app.api import deps
        from app.api.v1 import purchase_orders, purchase_arrivals, quality
        from app.core.exceptions import BizException
        from app.services import arrival_service, stock_service
        from app.utils.response import error
        cls.models, cls.deps, cls.database, cls.base = models, deps, database, database.Base
        cls.app = FastAPI()
        cls.app.include_router(purchase_orders.router, prefix="/api/v1")
        cls.app.include_router(purchase_arrivals.router, prefix="/api/v1")
        cls.app.include_router(quality.router, prefix="/api/v1")
        @cls.app.exception_handler(BizException)
        async def handle_business_error(_request, exc):
            return error(exc.message, exc.code)
        counter = itertools.count(1)
        def number(prefix):
            return prefix + "TEST" + str(next(counter))
        # 单号唯一性与时钟不属于本批，避免旧随机两位尾数让集成断言偶发碰撞。
        cls.number_patches = [patch.object(module, "gen_no", number)
                             for module in (purchase_orders, arrival_service, stock_service, quality)]
        for p in cls.number_patches:
            p.start()
        cls.loop = getattr(sys, "_preview_test_loop", None) or asyncio.new_event_loop()
        cls.owns_loop = not hasattr(sys, "_preview_test_loop")

    @classmethod
    def tearDownClass(cls):
        if cls.owns_loop:
            cls.loop.close()
        for p in reversed(cls.number_patches):
            p.stop()
        cls.engine.dispose()
        cls.path.stop()
        cls.modules.stop()

    def setUp(self):
        self.base.metadata.drop_all(self.engine)
        self.base.metadata.create_all(self.engine)
        self.db = self.Session()
        self.addCleanup(self.db.close)
        m = self.models
        self.material = m.Material(material_code="M", material_name="合成物料", unit="个")
        self.supplier = m.Supplier(supplier_code="S", supplier_name="合成供应商")
        self.warehouse = m.Warehouse(warehouse_code="W", warehouse_name="合成仓库")
        self.user = m.User(username="synthetic-admin", password_hash="not-a-login-credential",
                           roles=[m.Role(role_code="admin", role_name="合成管理员")])
        self.db.add_all([self.material, self.supplier, self.warehouse, self.user])
        self.db.commit()
        self.app.dependency_overrides[self.database.get_db] = lambda: self.db
        self.app.dependency_overrides[self.deps.get_current_user] = lambda: self.user

    def request(self, method, path, body=None, expected=0, params=None):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                         base_url="http://synthetic.invalid") as client:
                return await client.request(method, "/api/v1" + path, json=body, params=params)
        response = self.loop.run_until_complete(run())
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["code"], expected, data)
        if expected:
            self.assertIsNone(data["data"])
        return data["data"]

    def order(self, quantities=(100,)):
        data = self.request("POST", "/purchase-orders",
                            {"supplier_id": self.supplier.id, "items": [
                                {"material_id": self.material.id, "qty": qty, "unit_price": 2}
                                for qty in quantities]})
        self.request("POST", f"/purchase-orders/{data['id']}/approve")
        detail = self.request("GET", f"/purchase-orders/{data['id']}")
        return detail["id"], [i["id"] for i in detail["items"]]

    def delivery(self, order_id, item_id, qty, expected=0):
        return self.request("POST", "/purchase-arrivals", {"order_id": order_id, "actual_receipt_date": "2026-11-01", "items": [
            {"order_item_id": item_id, "arrived_qty": qty, "qualified_qty": qty,
             "warehouse_id": self.warehouse.id}]}, expected=expected)

    def prepare_quality(self, aid):
        arrival = self.request("GET", f"/purchase-arrivals/{aid}")
        iqc = self.request("POST", "/iqc", {"arrival_id": aid, "supplier_id": arrival["supplier_id"],
            "items": [{"arrival_item_id": i["id"], "material_id": i["material_id"]} for i in arrival["items"]]})
        detail = self.request("GET", f"/iqc/{iqc['id']}")
        quantities = {i["id"]: i["arrived_qty"] for i in arrival["items"]}
        self.request("POST", f"/iqc/{iqc['id']}/check", {"inspection_date": "2026-11-01",
            "items": [{"id": i["id"], "sample_qty": quantities[i["arrival_item_id"]],
                       "qualified_qty": quantities[i["arrival_item_id"]],
                       "accepted_qty": quantities[i["arrival_item_id"]], "result": "合格"} for i in detail["items"]]})
        self.request("POST", f"/iqc/{iqc['id']}/release", {"release_date": "2026-11-01", "release_basis": "合成完整整批明确接收依据"})

    def state(self, order_id):
        data = self.request("GET", f"/purchase-orders/{order_id}")
        inventory = sum(i.qty for i in self.db.query(self.models.Inventory))
        transactions = self.db.query(self.models.InventoryTransaction).order_by(
            self.models.InventoryTransaction.id).all()
        return data, inventory, transactions

    def test_two_deliveries_40_60_and_duplicate_approval(self):
        oid, (iid,) = self.order()
        first = self.delivery(oid, iid, 40)
        data, inventory, transactions = self.state(oid)
        self.assertEqual((data["status"], data["items"][0]["arrived_qty"],
                          data["items"][0]["inbound_qty"], inventory, len(transactions)),
                         ("部分到货", 40, 0, 0, 0))
        self.prepare_quality(first["id"])
        self.request("POST", f"/purchase-arrivals/{first['id']}/approve")
        data, inventory, transactions = self.state(oid)
        self.assertEqual((data["items"][0]["inbound_qty"], inventory, len(transactions)), (40, 40, 1))
        second = self.delivery(oid, iid, 60)
        data, inventory, transactions = self.state(oid)
        self.assertEqual((data["items"][0]["arrived_qty"], data["items"][0]["inbound_qty"],
                          inventory, len(transactions)), (100, 40, 40, 1))
        self.prepare_quality(second["id"])
        self.request("POST", f"/purchase-arrivals/{second['id']}/approve")
        data, inventory, transactions = self.state(oid)
        self.assertEqual((data["status"], data["items"][0]["arrived_qty"],
                          data["items"][0]["inbound_qty"], inventory), ("已完成", 100, 100, 100))
        self.assertEqual([(t.in_qty, t.out_qty, t.txn_type, t.ref_type, t.ref_id) for t in transactions],
                         [(40, 0, "采购入库", "采购到货", first["id"]),
                          (60, 0, "采购入库", "采购到货", second["id"])])
        self.request("POST", f"/purchase-arrivals/{first['id']}/approve", expected=50000)
        self.request("POST", f"/purchase-arrivals/{second['id']}/approve", expected=50000)
        self.assertEqual((self.state(oid)[1], len(self.state(oid)[2])), (100, 2))
        print("FLOW40_60", {"arrived": 100, "inbound": 100, "inventory": 100, "transactions": [40, 60]})

    def test_pending_reserves_quota_and_rejection_releases_it(self):
        oid, (iid,) = self.order()
        arrival = self.delivery(oid, iid, 100)
        self.delivery(oid, iid, 1, expected=50000)
        self.assertEqual(self.state(oid)[1], 0)
        self.request("POST", f"/purchase-arrivals/{arrival['id']}/reject", {"reason": "合成驳回"})
        data, inventory, transactions = self.state(oid)
        self.assertEqual((data["status"], data["items"][0]["arrived_qty"], inventory, len(transactions)),
                         ("已审核", 0, 0, 0))
        replacement = self.delivery(oid, iid, 100)
        self.prepare_quality(replacement["id"])
        self.request("POST", f"/purchase-arrivals/{replacement['id']}/approve")
        self.assertEqual((self.state(oid)[1], len(self.state(oid)[2])), (100, 1))

    def test_cross_order_and_duplicate_rows_cannot_exceed_quota(self):
        oid, (iid,) = self.order()
        other, _ = self.order()
        self.delivery(other, iid, 10, expected=50000)
        rows = [{"order_item_id": iid, "arrived_qty": 60, "qualified_qty": 60,
                 "warehouse_id": self.warehouse.id}] * 2
        self.request("POST", "/purchase-arrivals", {"order_id": oid, "actual_receipt_date": "2026-11-01", "items": rows}, expected=50000)
        self.assertEqual(self.db.query(self.models.PurchaseArrival).count(), 0)
        self.assertEqual(self.state(oid)[0]["items"][0]["arrived_qty"], 0)

    def test_multiple_lines_same_material_keep_separate_remaining(self):
        oid, ids = self.order((100, 50))
        first = self.delivery(oid, ids[0], 100)
        self.prepare_quality(first["id"])
        self.request("POST", f"/purchase-arrivals/{first['id']}/approve")
        second = self.delivery(oid, ids[1], 50)
        self.prepare_quality(second["id"])
        self.request("POST", f"/purchase-arrivals/{second['id']}/approve")
        data, inventory, transactions = self.state(oid)
        self.assertEqual(data["status"], "已完成")
        self.assertEqual([(i["id"], i["inbound_qty"]) for i in data["items"]], [(ids[0], 100), (ids[1], 50)])
        self.assertEqual((inventory, len(transactions)), (150, 2))

    def test_invalid_arrival_does_not_write_business_records(self):
        oid, (iid,) = self.order()
        for arrived, qualified in ((0, 0), (-1, 0), (20, 21), (20, -1)):
            with self.subTest(arrived=arrived, qualified=qualified):
                self.request("POST", "/purchase-arrivals", {"order_id": oid, "actual_receipt_date": "2026-11-01", "items": [
                    {"order_item_id": iid, "arrived_qty": arrived, "qualified_qty": qualified,
                     "warehouse_id": self.warehouse.id}]}, expected=50000)
        self.assertEqual(self.db.query(self.models.PurchaseArrival).count(), 0)
        self.assertEqual(self.state(oid)[1], 0)

    def test_list_state_filter_search_and_later_pages(self):
        m = self.models
        self.db.add_all([m.PurchaseOrder(order_no=f"PAGE-{n:03}", supplier_id=self.supplier.id,
                                         status="部分到货" if n % 2 else "已审核")
                         for n in range(205)])
        self.db.commit()
        collected = []
        for status, expected in (("已审核", 103), ("部分到货", 102)):
            for page in (1, 2):
                data = self.request("GET", "/purchase-orders",
                                    params={"status": status, "page": page, "page_size": 100})
                self.assertEqual(data["total"], expected)
                self.assertTrue(all(o["status"] == status for o in data["list"]))
                collected.extend(o["id"] for o in data["list"])
        self.assertEqual(len(set(collected)), 205)
        found = self.request("GET", "/purchase-orders", params={"keyword": "PAGE-204", "page": 1, "page_size": 100})
        self.assertEqual([o["order_no"] for o in found["list"]], ["PAGE-204"])


if __name__ == "__main__":
    unittest.main()

