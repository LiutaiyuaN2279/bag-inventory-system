"""OCR导入只验证合成既有记录和显式收货日，不上传或调用识别服务。"""
import importlib
import os
import secrets
import unittest
from unittest.mock import patch

import test_purchase_receipt_flow as flow


class OcrReceiptDateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flow.PurchaseReceiptFlowTests.setUpClass.__func__(cls)
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:", "AI_OCR_PROVIDER": "mock",
            "AI_OCR_API_KEY": "", "AI_OCR_BASE_URL": "", "SECRET_KEY": secrets.token_hex(32)}):
            config = importlib.import_module("app.core.config")
        cls.ocr = importlib.import_module("app.api.v1.ai_ocr")
        cls.app.include_router(cls.ocr.router, prefix="/api/v1")
        cls.external = patch.object(cls.ocr.ocr_service, "recognize",
                                    side_effect=AssertionError("real AI must never be called"))
        cls.external.start()

    @classmethod
    def tearDownClass(cls):
        cls.external.stop()
        flow.PurchaseReceiptFlowTests.tearDownClass.__func__(cls)

    setUp = flow.PurchaseReceiptFlowTests.setUp
    request = flow.PurchaseReceiptFlowTests.request
    order = flow.PurchaseReceiptFlowTests.order
    state = flow.PurchaseReceiptFlowTests.state
    prepare_quality = flow.PurchaseReceiptFlowTests.prepare_quality

    def record(self):
        record = self.models.AiOcrRecord(image_name="synthetic-not-uploaded.png", provider="mock", status="待确认")
        self.db.add(record); self.db.flush()
        item = self.models.AiOcrItem(record_id=record.id, material_name=self.material.material_name,
                                    material_id=self.material.id, qty=100, unit="个")
        self.db.add(item); self.db.commit()
        return record, item

    def payload(self, oid, item):
        return {"order_id": oid, "warehouse_id": self.warehouse.id,
                "items": [{"id": item.id, "material_id": self.material.id,
                           "material_name": self.material.material_name, "unit": "个", "qty": 100}]}

    def test_generation_requires_explicit_date_and_rolls_back_when_missing(self):
        oid, _ = self.order(); record, item = self.record()
        self.request("POST", f"/ai-ocr/records/{record.id}/import", self.payload(oid, item), expected=50000)
        self.assertEqual(self.db.query(self.models.PurchaseArrival).count(), 0)
        self.assertEqual(self.db.get(self.models.AiOcrRecord, record.id).status, "待确认")

    def test_explicit_date_passes_through_but_does_not_grant_quality_release(self):
        oid, _ = self.order(); record, item = self.record()
        imported = self.request("POST", f"/ai-ocr/records/{record.id}/import",
                                {**self.payload(oid, item), "actual_receipt_date": "2026-11-01"})
        arrival = self.db.get(self.models.PurchaseArrival, imported["arrival_id"])
        self.assertEqual(arrival.actual_receipt_date, "2026-11-01")
        self.request("POST", f"/purchase-arrivals/{arrival.id}/approve", expected=50000)
        self.assertEqual(self.state(oid)[1], 0)
        self.prepare_quality(arrival.id)
        self.request("POST", f"/purchase-arrivals/{arrival.id}/approve")
        self.assertEqual(self.state(oid)[1], 100)

    def test_archive_without_order_and_warehouse_does_not_require_date_or_create_arrival(self):
        record, item = self.record()
        data = self.request("POST", f"/ai-ocr/records/{record.id}/import",
                            {**self.payload(None, item), "warehouse_id": None})
        self.assertIsNone(data["arrival_id"])
        self.assertEqual(self.db.query(self.models.PurchaseArrival).count(), 0)

