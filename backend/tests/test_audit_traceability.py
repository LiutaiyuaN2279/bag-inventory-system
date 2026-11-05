"""实际详情API只读取同run归档；冻结候选不冒充核验来源。"""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import httpx
import test_purchase_receipt_flow as flow


class AuditTraceabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flow.PurchaseReceiptFlowTests.setUpClass.__func__(cls)
        config = types.ModuleType("app.core.config")
        config.settings = types.SimpleNamespace(DATABASE_URL="sqlite:///:memory:",
            AUDIT_TRIAL_ARCHIVE_DIR="never-created-synthetic-archive")
        sys.modules["app.core.config"] = config
        cls.audit = importlib.import_module("app.api.v1.audit")
        cls.app.include_router(cls.audit.router, prefix="/api/v1")
        archive_module = importlib.import_module("app.services.audit_trial_archive")
        cls.archive = archive_module.TrialArchive(Path.cwd() / "never-created-synthetic-archive")
        cls.canonical = staticmethod(archive_module.canonical_bytes)

    tearDownClass = classmethod(flow.PurchaseReceiptFlowTests.tearDownClass.__func__)
    setUp = flow.PurchaseReceiptFlowTests.setUp

    def payload(self, run_id, quantity=0, rows=1):
        finding = {"finding_id": "F001", "rule_code": "R02", "amount": None,
                   "refs": [{"type": "采购订单", "no": "PO-1"}], "evidence": [], "suggestion": "规则模板"}
        report = {"report_meta": {"run_id": run_id, "formal_report": False}, "procedures": [], "findings": [finding]}
        basis = {key: [] for key in ("calendar_versions", "evidence_versions")}
        basis.update({"period_start": "2026-09-01", "period_end": "2026-09-30", "business_cutoff": "2026-09-30",
            "snapshot_at": "2026-11-01T00:00:00Z", "rule_version": "frozen-rule-v1", "rules_source": "PRIVATE_SOURCE",
            "rule_config": {}, "business_data": [{"sql": "PRIVATE_SQL", "rows": [
                {"order_no": "PO-1", "qty": quantity, "api_key": "PRIVATE_KEY", "password": "PRIVATE_PASSWORD"} for _ in range(rows)]}]})
        return {"run_id": run_id, "kind": "original_trial", "original_run_id": run_id,
                "parent_run_id": None, "report": report, "basis": basis}

    def encoded(self, payload, corrupt=False):
        digest = hashlib.sha256(self.canonical(payload)).hexdigest()
        return self.canonical({"schema": "b002-trial-archive-v1", "sha256": "bad" if corrupt else digest, "payload": payload})

    def request(self, run_id, archive_files, expected=0):
        original = Path.read_bytes
        def read(path):
            if path.parent == self.archive.root:
                if path.name not in archive_files:
                    raise FileNotFoundError(path.name)
                return archive_files[path.name]
            return original(path)
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                base_url="http://synthetic.invalid", headers={"X-Audit-Contract": "b002-p0-v1"}) as client:
                return await client.get("/api/v1/audit/findings/F001", params={"run_id": run_id})
        with patch.object(Path, "read_bytes", read), patch.object(self.audit, "trial_archive", return_value=self.archive), \
             patch.object(self.audit, "run_audit", side_effect=AssertionError("must not recalculate current data")):
            response = self.loop.run_until_complete(run())
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json(); self.assertEqual(body["code"], expected, body)
        return body["data"]

    def test_actual_old_run_api_is_frozen_and_exposes_only_matched_safe_fields(self):
        old, new = "a" * 32, "b" * 32
        originals = {old + ".json": self.encoded(self.payload(old, 0)),
                     new + ".json": self.encoded(self.payload(new, 99))}
        before = copy.deepcopy(originals)
        self.assertEqual(self.request(new, originals)["traceability"]["candidates"][0]["fields"]["qty"], 99)
        result = self.request(old, originals)
        trace = result["traceability"]
        self.assertEqual(trace["run_id"], old)
        self.assertEqual(trace["candidates"][0]["fields"]["qty"], 0)
        self.assertEqual((trace["status"], trace["coverage"], trace["formal_eligible"]), ("unproven", "unproven", False))
        self.assertEqual((trace["ai_advice"], trace["human_confirmation"]), ("not_provided", "not_recorded"))
        self.assertTrue(trace["review_checklist"])
        text = json.dumps(result)
        for secret in ("PRIVATE_SQL", "PRIVATE_SOURCE", "PRIVATE_KEY", "PRIVATE_PASSWORD"):
            self.assertNotIn(secret, text)
        self.assertEqual(before, originals)

    def test_missing_or_corrupt_snapshot_returns_business_error_without_current_fallback(self):
        run_id = "c" * 32
        for files in ({}, {run_id + ".json": self.encoded(self.payload(run_id), corrupt=True)}):
            with self.subTest(kind="missing" if not files else "corrupt"):
                self.assertIsNone(self.request(run_id, files, expected=50000))

    def test_candidate_limit_and_unbound_finding_remain_unproven(self):
        from app.services.audit_traceability import explain_finding
        payload = self.payload("d" * 32, rows=23)
        before = copy.deepcopy(payload)
        result = explain_finding(payload, payload["report"]["findings"][0])
        self.assertEqual(len(result["candidates"]), 20)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["coverage"], "unproven")
        unrelated = {**payload["report"]["findings"][0], "finding_id": "OTHER"}
        self.assertEqual(explain_finding(payload, unrelated)["candidates"], [])
        self.assertEqual(before, payload)

