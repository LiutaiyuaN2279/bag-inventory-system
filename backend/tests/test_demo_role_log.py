"""真实新库初始化、签名令牌、权限及现有日志中间件的隔离验证。"""
import ast
import asyncio
import contextlib
from datetime import datetime
import importlib
import importlib.util
import io
import json
import logging
from pathlib import Path
import secrets
import sys
import time
import types
import unittest

from fastapi import Request
from fastapi.responses import JSONResponse
import test_purchase_receipt_flow as flow


class DemoRoleLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flow.PurchaseReceiptFlowTests.setUpClass.__func__(cls)
        config = types.ModuleType("app.core.config")
        config.settings = types.SimpleNamespace(SECRET_KEY=secrets.token_hex(32), ALGORITHM="HS256",
                                                 ACCESS_TOKEN_EXPIRE_MINUTES=60)
        sys.modules["app.core.config"] = config
        del sys.modules["app.core.security"]
        cls.security = importlib.import_module("app.core.security")
        backend = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("_real_demo_init", backend / "scripts/init_db.py")
        cls.init_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.init_module)
        # 抽取未经改写的现有中间件函数；不导入app.main、不启动后台任务或清理。
        names = {"_get_log_queue", "_flush_logs", "_drain_logs", "_should_log",
                 "_dedup_hit", "_resolve_username", "_write_log", "operation_log_middleware", "biz_handler"}
        tree = ast.parse((backend / "app/main.py").read_text(encoding="utf-8-sig"))
        functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
        cls.log_context = {"app": cls.app, "asyncio": asyncio, "json": json, "time": time,
            "datetime": datetime, "Request": Request, "SessionLocal": cls.Session,
            "JSONResponse": JSONResponse, "BizException": importlib.import_module("app.core.exceptions").BizException,
            "OperationLog": cls.models.OperationLog, "User": cls.models.User,
            "decode_token": cls.security.decode_token, "logger": logging.getLogger("isolated-log-test"),
            "_log_queue": None, "_log_dropped": 0, "_log_dedup_cache": {},
            "_LOG_SKIP_PREFIX": "/api/v1/operation-logs", "_LOG_DEDUP_WINDOW_S": 2.0,
            "_LOG_MAX_DEDUP_ENTRIES": 5000}
        exec(compile(ast.Module(body=functions, type_ignores=[]), "actual-main-middleware", "exec"), cls.log_context)
        cls.app.middleware_stack = None

    tearDownClass = classmethod(flow.PurchaseReceiptFlowTests.tearDownClass.__func__)

    def setUp(self):
        self.base.metadata.drop_all(self.engine); self.base.metadata.create_all(self.engine)
        with contextlib.redirect_stdout(io.StringIO()):
            self.init_module.init()
        self.db = self.Session()
        self.addCleanup(self.db.close)
        self.app.dependency_overrides.clear()
        self.app.dependency_overrides[self.database.get_db] = lambda: self.db
        self.log_context["_log_queue"] = None
        self.log_context["_log_dedup_cache"] = {}
        self.user = "admin"
        self.material = self.db.query(self.models.Material).first()
        self.supplier = self.db.query(self.models.Supplier).first()
        self.warehouse = self.db.query(self.models.Warehouse).first()

    def request(self, method, path, body=None, expected=0, username=None, token=None):
        import httpx
        name = username or self.user
        user = self.db.query(self.models.User).filter_by(username=name).one()
        bearer = token or self.security.create_access_token(user.id)
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                    base_url="http://synthetic.invalid", headers={"Authorization": "Bearer " + bearer}) as client:
                return await client.request(method, "/api/v1" + path, json=body)
        response = self.loop.run_until_complete(run())
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["code"], expected, data)
        return data["data"]

    def test_actual_initialization_and_role_matrix(self):
        from app.crud.crud_auth import get_user_permissions, get_user_roles
        expected = {"buyer": ("purchase:order:add", "purchase:order:approve"),
                    "keeper": ("purchase:arrival:approve", "qc:edit"),
                    "qc": ("qc:edit", "purchase:arrival:approve"),
                    "manager": ("purchase:order:approve", "purchase:arrival:approve")}
        for name, (allowed, forbidden) in expected.items():
            with self.subTest(role=name):
                user = self.db.query(self.models.User).filter_by(username=name).one()
                permissions = get_user_permissions(self.db, user)
                self.assertEqual(get_user_roles(self.db, user), [name])
                self.assertIn(allowed, permissions); self.assertNotIn(forbidden, permissions)
        keeper = self.db.query(self.models.User).filter_by(username="keeper").one()
        self.assertIn("purchase:order:list", get_user_permissions(self.db, keeper))
        buyer = self.db.query(self.models.User).filter_by(username="buyer").one()
        qc = self.db.query(self.models.User).filter_by(username="qc").one()
        self.assertNotIn("ai:ocr:import", get_user_permissions(self.db, buyer))
        self.assertIn("ai:ocr:recognize", get_user_permissions(self.db, qc))

    def test_signed_tokens_and_single_batch_cross_role_denial(self):
        created = self.request("POST", "/purchase-orders", {"supplier_id": self.supplier.id,
            "items": [{"material_id": self.material.id, "qty": 100, "unit_price": 2}]}, username="buyer")
        oid = created["id"]
        self.request("POST", f"/purchase-orders/{oid}/approve", username="buyer", expected=40300)
        self.request("POST", f"/purchase-orders/{oid}/approve", username="manager")
        self.request("GET", "/purchase-orders", username="keeper")
        for username in ("buyer", "qc", "manager"):
            with self.subTest(user=username):
                self.request("POST", "/purchase-arrivals/batch",
                             {"ids": [123], "action": "approve"}, username=username, expected=40300)
                self.request("POST", "/purchase-arrivals/123/approve", username=username, expected=40300)
        self.request("POST", "/iqc/batch", {"ids": [123], "action": "approve"}, username="keeper", expected=40300)
        self.request("GET", "/iqc", username="qc")

    def test_admin_explicit_deny_and_invalid_signature(self):
        admin = self.db.query(self.models.User).filter_by(username="admin").one()
        permission = self.db.query(self.models.Permission).filter_by(perm_code="purchase:order:list").one()
        self.db.add(self.models.UserPermission(user_id=admin.id, permission_id=permission.id, effect="deny"))
        self.db.commit()
        self.request("GET", "/purchase-orders", expected=40300)
        token = self.security.create_access_token(admin.id)
        damaged = token.split(".")
        damaged[2] = ("A" if damaged[2][0] != "A" else "B") + damaged[2][1:]
        self.request("GET", "/purchase-orders", expected=40100, token=".".join(damaged))

    def test_signed_real_roles_complete_full_quality_and_inventory_chain(self):
        order = self.request("POST", "/purchase-orders", {"supplier_id": self.supplier.id,
            "items": [{"material_id": self.material.id, "qty": 100, "unit_price": 2}]}, username="buyer")
        self.request("POST", f"/purchase-orders/{order['id']}/approve", username="manager")
        detail = self.request("GET", f"/purchase-orders/{order['id']}", username="keeper")
        arrival = self.request("POST", "/purchase-arrivals", {"order_id": order["id"],
            "actual_receipt_date": "2026-11-01", "items": [{"order_item_id": detail["items"][0]["id"],
            "arrived_qty": 100, "qualified_qty": 100, "warehouse_id": self.warehouse.id}]}, username="keeper")
        incoming = self.request("GET", f"/purchase-arrivals/{arrival['id']}", username="qc")
        iqc = self.request("POST", "/iqc", {"arrival_id": arrival["id"], "supplier_id": self.supplier.id,
            "items": [{"arrival_item_id": incoming["items"][0]["id"], "material_id": self.material.id}]}, username="qc")
        quality = self.request("GET", f"/iqc/{iqc['id']}", username="qc")
        self.request("POST", f"/iqc/{iqc['id']}/check", {"inspection_date": "2026-11-01", "items": [
            {"id": quality["items"][0]["id"], "result": "合格", "sample_qty": 1,
             "qualified_qty": 1, "accepted_qty": 100}]}, username="qc")
        self.request("POST", f"/iqc/{iqc['id']}/release", {"release_date": "2026-11-01",
            "release_basis": "质检员明确整批正常接收依据"}, username="qc")
        for role in ("buyer", "qc", "manager"):
            with self.subTest(role=role):
                self.request("POST", f"/purchase-arrivals/{arrival['id']}/approve", username=role, expected=40300)
                self.assertEqual(self.db.query(self.models.InventoryTransaction).count(), 0)
        self.request("POST", f"/purchase-arrivals/{arrival['id']}/approve", username="keeper")
        qc = self.db.query(self.models.User).filter_by(username="qc").one()
        record = self.db.get(self.models.IqcOrder, iqc["id"])
        self.assertEqual((record.inspected_by, record.released_by), (qc.id, qc.id))
        txn = self.db.query(self.models.InventoryTransaction).one()
        self.assertEqual((txn.in_qty, txn.operator, txn.ref_id), (100, "keeper", arrival["id"]))
        self.assertEqual(self.db.query(self.models.Inventory).one().qty, 100)

    def test_real_middleware_logs_identity_path_and_business_rejection(self):
        self.request("POST", "/purchase-arrivals/123/approve", username="buyer", expected=40300)
        self.loop.run_until_complete(self.log_context["_drain_logs"]())
        rows = self.db.query(self.models.OperationLog).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].username, rows[0].method, rows[0].path, rows[0].status_code),
                         ("buyer", "POST", "/api/v1/purchase-arrivals/123/approve", 40300))
        self.assertNotIn("Bearer", rows[0].detail or "")

    def test_existing_custom_bindings_permissions_and_admin_denies_are_preserved(self):
        from app.services.demo_roles import initialize_demo_roles
        m = self.models
        admin = self.db.query(m.User).filter_by(username="admin").one()
        permission = self.db.query(m.Permission).filter_by(perm_code="purchase:order:list").one()
        custom = m.Role(role_code="custom", role_name="定制角色")
        self.db.add(custom); self.db.flush()
        self.db.add(m.UserRole(user_id=admin.id, role_id=custom.id))
        self.db.add(m.UserPermission(user_id=admin.id, permission_id=permission.id, effect="deny"))
        self.db.query(m.RolePermission).filter_by(role_id=self.db.query(m.Role).filter_by(role_code="buyer").one().id).delete()
        self.db.commit()
        before = {model.__tablename__: [tuple(getattr(row, col.name) for col in model.__table__.columns)
                  for row in self.db.query(model).order_by(*model.__table__.primary_key.columns)]
                  for model in (m.User, m.Role, m.UserRole, m.RolePermission, m.UserPermission)}
        initialize_demo_roles(self.db, self.security.hash_password); self.db.commit()
        after = {model.__tablename__: [tuple(getattr(row, col.name) for col in model.__table__.columns)
                 for row in self.db.query(model).order_by(*model.__table__.primary_key.columns)]
                 for model in (m.User, m.Role, m.UserRole, m.RolePermission, m.UserPermission)}
        self.assertEqual(before, after)

