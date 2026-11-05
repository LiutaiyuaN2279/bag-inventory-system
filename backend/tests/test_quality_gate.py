"""新合成质量门禁：复用真实采购ASGI夹具，不替代被测业务函数。"""
from datetime import timedelta
import unittest
import test_purchase_receipt_flow as flow


class QualityGateTests(unittest.TestCase):
    setUpClass = classmethod(flow.PurchaseReceiptFlowTests.setUpClass.__func__)
    tearDownClass = classmethod(flow.PurchaseReceiptFlowTests.tearDownClass.__func__)
    setUp = flow.PurchaseReceiptFlowTests.setUp
    request = flow.PurchaseReceiptFlowTests.request
    order = flow.PurchaseReceiptFlowTests.order
    delivery = flow.PurchaseReceiptFlowTests.delivery
    state = flow.PurchaseReceiptFlowTests.state

    def new_iqc(self, aid):
        arrival = self.request("GET", f"/purchase-arrivals/{aid}")
        created = self.request("POST", "/iqc", {"arrival_id": aid, "supplier_id": arrival["supplier_id"],
            "items": [{"arrival_item_id": i["id"], "material_id": i["material_id"]} for i in arrival["items"]]})
        return self.request("GET", f"/iqc/{created['id']}")

    def conclusion(self, detail, quantities, results=None):
        return {"inspection_date": "2026-11-01", "items": [
            {"id": item["id"], "sample_qty": 1, "qualified_qty": 1,
             "accepted_qty": qty, "result": (results or ["合格"] * len(quantities))[n]}
            for n, (item, qty) in enumerate(zip(detail["items"], quantities))]}

    def release(self, iid, expected=0, date="2026-11-01"):
        self.request("POST", f"/iqc/{iid}/release",
                     {"release_date": date, "release_basis": "人工明确整批接收的合成依据"}, expected=expected)

    def test_uninspected_and_unreleased_cannot_inbound_even_admin(self):
        oid, (iid,) = self.order()
        arrival = self.delivery(oid, iid, 100)
        self.request("POST", f"/purchase-arrivals/{arrival['id']}/approve", expected=50000)
        detail = self.new_iqc(arrival["id"])
        self.request("POST", f"/iqc/{detail['id']}/check", self.conclusion(detail, [100]))
        self.request("POST", f"/purchase-arrivals/{arrival['id']}/approve", expected=50000)
        self.assertEqual(self.state(oid)[1], 0)
        self.release(detail["id"])
        self.request("POST", f"/purchase-arrivals/{arrival['id']}/approve")
        self.assertEqual((self.state(oid)[1], len(self.state(oid)[2])), (100, 1))
        self.assertIsNotNone(self.db.get(self.models.PurchaseArrival, arrival["id"]).inbound_posted_at)

    def test_partial_submission_duplicate_or_foreign_rows_do_not_write(self):
        oid, ids = self.order((100, 100))
        arrival = self.request("POST", "/purchase-arrivals", {"order_id": oid, "actual_receipt_date": "2026-11-01",
            "items": [{"order_item_id": i, "arrived_qty": 100, "qualified_qty": 100,
                       "warehouse_id": self.warehouse.id} for i in ids]})
        detail = self.new_iqc(arrival["id"])
        original = self.conclusion(detail, [100, 100])
        for rows in (original["items"][:1], [original["items"][0]] * 2,
                     [*original["items"][:1], {**original["items"][1], "id": 999999}]):
            with self.subTest(rows=[row["id"] for row in rows]):
                self.request("POST", f"/iqc/{detail['id']}/check",
                             {**original, "items": rows}, expected=50000)
        self.assertEqual(self.db.get(self.models.IqcOrder, detail["id"]).status, "待检")
        self.assertTrue(all(row.result == "待检" for row in self.db.query(self.models.IqcItem)))

    def test_sample_pass_is_not_full_quantity_release_and_unsafe_values_rejected(self):
        oid, (iid,) = self.order()
        arrival = self.delivery(oid, iid, 100)
        detail = self.new_iqc(arrival["id"])
        for value in (None, True, -1, 101):
            with self.subTest(accepted=value):
                data = self.conclusion(detail, [value])
                self.request("POST", f"/iqc/{detail['id']}/check", data, expected=50000)
        self.request("POST", f"/iqc/{detail['id']}/check", self.conclusion(detail, [1]))
        self.release(detail["id"], expected=50000)
        self.assertEqual(self.state(oid)[1], 0)

    def test_mixed_rejection_and_concession_are_not_released_and_cannot_be_erased(self):
        oid, ids = self.order((100, 100))
        arrival = self.request("POST", "/purchase-arrivals", {"order_id": oid, "actual_receipt_date": "2026-11-01",
            "items": [{"order_item_id": i, "arrived_qty": 100, "qualified_qty": 100,
                       "warehouse_id": self.warehouse.id} for i in ids]})
        detail = self.new_iqc(arrival["id"])
        payload = self.conclusion(detail, [0, 0], ["不合格", "让步接收"])
        self.request("POST", f"/iqc/{detail['id']}/check", payload)
        self.assertEqual(self.db.get(self.models.IqcOrder, detail["id"]).status, "不合格")
        self.release(detail["id"], expected=50000)
        self.request("POST", f"/iqc/{detail['id']}/check", self.conclusion(detail, [100, 100]), expected=50000)
        for batch in (False, True):
            with self.subTest(batch=batch):
                if batch:
                    result = self.request("POST", "/purchase-arrivals/batch",
                        {"ids": [arrival["id"]], "action": "reject", "reason": "不能抹掉质量事实"})
                    self.assertEqual(result["fail_count"], 1)
                else:
                    self.request("POST", f"/purchase-arrivals/{arrival['id']}/reject",
                                 {"reason": "不能抹掉质量事实"}, expected=50000)
        self.assertEqual(self.state(oid)[0]["items"][0]["arrived_qty"], 100)
        self.assertEqual(self.state(oid)[1], 0)

    def test_released_source_change_and_repeated_release_or_reject_are_refused(self):
        oid, (iid,) = self.order()
        arrival = self.delivery(oid, iid, 100); detail = self.new_iqc(arrival["id"])
        self.request("POST", f"/iqc/{detail['id']}/check", self.conclusion(detail, [100]))
        self.release(detail["id"]); self.release(detail["id"], expected=50000)
        self.request("POST", f"/purchase-arrivals/{arrival['id']}/reject",
                     {"reason": "不允许撤回"}, expected=50000)
        result = self.request("POST", "/purchase-arrivals/batch",
            {"ids": [arrival["id"]], "action": "reject", "reason": "不允许撤回"})
        self.assertEqual(result["fail_count"], 1)
        raw = self.db.query(self.models.PurchaseArrivalItem).filter_by(arrival_id=arrival["id"]).one()
        raw.arrived_qty = 99; self.db.commit()
        self.request("POST", f"/purchase-arrivals/{arrival['id']}/approve", expected=50000)
        self.assertEqual(self.state(oid)[1], 0)

    def test_dates_use_actual_receipt_not_creation_and_do_not_allow_backdated_release(self):
        from app.services.quality_release import business_today
        oid, (iid,) = self.order()
        receipt = (business_today() - timedelta(days=2)).isoformat()
        inspected = (business_today() - timedelta(days=1)).isoformat()
        arrival = self.request("POST", "/purchase-arrivals", {"order_id": oid, "actual_receipt_date": receipt,
            "items": [{"order_item_id": iid, "arrived_qty": 100, "qualified_qty": 100,
                       "warehouse_id": self.warehouse.id}]})
        detail = self.new_iqc(arrival["id"])
        data = self.conclusion(detail, [100])
        data["inspection_date"] = inspected
        self.request("POST", f"/iqc/{detail['id']}/check", data)
        self.release(detail["id"], date=receipt, expected=50000)
        self.release(detail["id"], date=inspected)
        self.request("POST", f"/purchase-arrivals/{arrival['id']}/approve")
        self.assertEqual(self.state(oid)[1], 100)

    def test_old_unbound_or_multiple_iqc_records_never_grant_release(self):
        oid, (iid,) = self.order()
        arrival = self.delivery(oid, iid, 100)
        old = self.models.IqcOrder(qc_no="OLD", arrival_id=arrival["id"],
                                  supplier_id=self.supplier.id, status="合格")
        self.db.add(old); self.db.commit()
        self.request("POST", f"/purchase-arrivals/{arrival['id']}/approve", expected=50000)
        self.db.delete(old); self.db.commit()
        detail = self.new_iqc(arrival["id"])
        self.db.add(self.models.IqcOrder(qc_no="DUP", arrival_id=arrival["id"],
                                        supplier_id=self.supplier.id))
        self.db.commit()
        self.request("POST", f"/iqc/{detail['id']}/check", self.conclusion(detail, [100]), expected=50000)
        self.assertEqual(self.state(oid)[1], 0)

    def test_prefilled_qualified_quantity_is_not_silently_raised(self):
        oid, (iid,) = self.order()
        arrival = self.request("POST", "/purchase-arrivals", {"order_id": oid, "actual_receipt_date": "2026-11-01",
            "items": [{"order_item_id": iid, "arrived_qty": 100, "qualified_qty": 80,
                       "warehouse_id": self.warehouse.id}]})
        detail = self.new_iqc(arrival["id"])
        self.request("POST", f"/iqc/{detail['id']}/check", self.conclusion(detail, [100]))
        self.release(detail["id"], expected=50000)
        self.assertEqual(self.db.query(self.models.PurchaseArrivalItem).one().qualified_qty, 80)
        self.assertEqual(self.state(oid)[1], 0)

