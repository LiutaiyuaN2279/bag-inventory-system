"""WP-1 only. Synthetic data; no app startup, DB, filesystem or source service.

These tests assert validation reports and qualification helpers directly. They
do not treat not_ready as proof that quantity or partial-result tests passed.
"""
from copy import deepcopy
from dataclasses import fields, replace
from datetime import date, datetime, timezone
from decimal import Decimal
import unittest
from unittest.mock import Mock, patch

from app.services import audit_delivery as core
from app.services import audit_delivery_contract as contract


CUTOFF = date(2026, 9, 30)
MODELS = {"portions": core.Portion, "deliveries": core.Delivery, "allocations": core.Allocation}


class HostileTruth:
    def __bool__(self):
        raise AssertionError("must_not_coerce_bool")

    def __str__(self):
        raise AssertionError("must_not_coerce_str")

    def __eq__(self, other):
        raise AssertionError("must_not_use_loose_equality")


class DateSubclass(date):
    pass


def raw_request(entry="evaluate_delivery_scope"):
    request = {
        "contract_version": contract.V2,
        "contract_context": {"contract_version": contract.V2, "input_manifest_ref": "manifest@1",
                             "qualification_context_ref": "observation@1"},
        "unit": "件", "cutoff": CUTOFF,
        "deliveries": [{"delivery_id": "D", "source_event_key": "receipt-D", "order_id": "PO",
                        "item_id": "LINE", "unit": "件", "delivered_quantity": "80",
                        "actual_date": date(2026, 10, 1), "evidence_verified": True,
                        "actual_date_verified": None}],
    }
    if entry == "evaluate_delivery_scope":
        request.update(order_id="PO", item_id="LINE", commitment_scope_complete=True,
                       delivery_scope_complete=True,
                       portions=[{"portion_id": "A", "order_id": "PO", "item_id": "LINE", "unit": "件",
                                  "effective_quantity": "100", "commitment_date": date(2026, 9, 1),
                                  "due_date": date(2026, 9, 10), "evidence_verified": True,
                                  "calculation_eligible": True, "commitment_date_verified": None}],
                       allocations=[{"allocation_id": "AL", "delivery_id": "D", "portion_id": "A",
                                     "allocated_quantity": "80", "version_id": "relation@1",
                                     "evidence_verified": True, "delivery_offset": "0"}])
    return request


def typed_request(entry="evaluate_delivery_scope"):
    request = raw_request(entry)
    for group, cls in MODELS.items():
        if group in request:
            request[group] = [cls(**row) for row in request[group]]
    return request


def claim(field_name="actual_date"):
    return dict(flag=True, value=date(2026, 10, 1),
                subject_ref=("delivery" if field_name == "actual_date" else "portion", "D", "receipt-D", "fact@1"),
                field_name=field_name, precision="date", time_zone="Asia/Shanghai",
                timezone_basis_ref="normalization@1", qualification_context_ref="observation@1")


def basis_for(data):
    return {key: value for key, value in data.items() if key != "flag"} | {
        "evidence_id": "original-E", "evidence_version": "E@1", "decision_id": "decision-1",
        "decision_version": "1", "scope_ref": "field-scope@1", "scope_fields": (data["field_name"],),
        "decision_status": "active", "conclusion": True, "assurance_level": "synthetic_only",
    }


class BoundaryAssertions(unittest.TestCase):
    def inspect(self, data, entry="evaluate_delivery_scope"):
        return contract.validate_core_request(entry, data, record_types=MODELS, quantity_validator=core.quantity)

    def gate(self, entry, data, code="quantity_contract_not_ready"):
        with self.assertRaises(contract.ContractError) as caught:
            getattr(core, entry)(**data)
        self.assertEqual(caught.exception.code, code)
        return caught.exception.report


class VersionContextTests(BoundaryAssertions):
    def test_missing_version_both_entries(self):
        for entry in contract.ENTRY_POINTS:
            data = typed_request(entry)
            del data["contract_version"]
            self.gate(entry, data, "missing_request_contract")

    def test_invalid_version_exact_types_both_entries(self):
        for entry in contract.ENTRY_POINTS:
            for bad in (None, "", " ", 0, 1, True, False, [], HostileTruth()):
                with self.subTest(entry=entry, bad_type=type(bad).__name__):
                    data = typed_request(entry) | {"contract_version": bad}
                    self.gate(entry, data, "invalid_request_contract")

    def test_version_aliases_and_legacy_never_fallback(self):
        for entry in contract.ENTRY_POINTS:
            for version, code in ((contract.V1, "legacy_quantity_calculation_disabled"),
                                  ("V2", "unsupported_request_contract"),
                                  ("b002-p0-v1", "unsupported_request_contract"),
                                  ("unknown", "unsupported_request_contract")):
                with self.subTest(entry=entry, version=version):
                    self.gate(entry, typed_request(entry) | {"contract_version": version}, code)

    def test_missing_context_both_entries(self):
        for entry in contract.ENTRY_POINTS:
            data = typed_request(entry)
            del data["contract_context"]
            self.gate(entry, data, "missing_contract_context")

    def test_invalid_context_both_entries(self):
        for entry in contract.ENTRY_POINTS:
            for bad in (None, {}, [], True, "context", {"contract_version": contract.V2}):
                with self.subTest(entry=entry, context_type=type(bad).__name__):
                    self.gate(entry, typed_request(entry) | {"contract_context": bad}, "invalid_contract_context")

    def test_context_version_mismatch_both_entries(self):
        for entry in contract.ENTRY_POINTS:
            data = typed_request(entry)
            data["contract_context"]["contract_version"] = contract.V1
            self.gate(entry, data, "contract_context_version_mismatch")

    def test_valid_v2_both_entries_stop_before_any_legacy_arithmetic(self):
        for entry in contract.ENTRY_POINTS:
            with patch.object(core, "_index_delivery_facts", side_effect=AssertionError("legacy_body_entered")), \
                    patch.object(core, "_pending_quantities_fit", side_effect=AssertionError("capacity_body_entered")):
                report = self.gate(entry, typed_request(entry))
                self.assertTrue(report.types_and_values_valid)

    def test_client_capability_claims_cannot_open_gate(self):
        for entry in contract.ENTRY_POINTS:
            data = typed_request(entry)
            data["contract_context"].update(ready=True, skip_validation=True, trusted_legacy=True)
            self.gate(entry, data)
            report = self.gate(entry, data | {"ready": True})
            self.assertIn("unsupported_input_field", [i.code for i in report.request_issues])

    def test_context_version_cannot_fill_missing_top_version(self):
        data = typed_request()
        del data["contract_version"]
        self.gate("evaluate_delivery_scope", data, "missing_request_contract")

    def test_cutoff_requires_exact_date_both_entries(self):
        for entry in contract.ENTRY_POINTS:
            for bad in (None, "2026-09-30", datetime(2026, 9, 30), DateSubclass(2026, 9, 30)):
                with self.subTest(entry=entry, bad_type=type(bad).__name__):
                    self.gate(entry, typed_request(entry) | {"cutoff": bad}, "invalid_cutoff")

    def test_invalid_collection_is_root_issue_not_empty_scope(self):
        for entry in contract.ENTRY_POINTS:
            self.gate(entry, typed_request(entry) | {"deliveries": None}, "invalid_record_collection")


class StrictInputTests(BoundaryAssertions):
    def test_all_record_boolean_fields_reject_non_bool_and_collect(self):
        for group, fields_to_check in (("portions", ("evidence_verified", "calculation_eligible", "commitment_date_verified")),
                                       ("deliveries", ("evidence_verified", "actual_date_verified")),
                                       ("allocations", ("evidence_verified",))):
            for name in fields_to_check:
                illegal = ("false", "true", 0, 1, 0.0, [], {}, HostileTruth(), contract.MISSING)
                if not name.endswith("date_verified"):
                    illegal += (None,)
                for bad in illegal:
                    with self.subTest(group=group, field=name, bad_type=type(bad).__name__):
                        data = typed_request()
                        data[group][0] = replace(data[group][0], **{name: bad})
                        report = self.gate("evaluate_delivery_scope", data)
                        self.assertIn(f"{group}[0].{name}", [i.path for i in report.record_issues])
                        self.assertFalse(report.types_and_values_valid)

    def test_summary_direct_flags_never_bypass(self):
        for name in ("evidence_verified", "actual_date_verified"):
            for bad in ("false", 0, 1, HostileTruth()):
                with self.subTest(field=name, bad_type=type(bad).__name__):
                    data = typed_request("summarize_delivery_facts")
                    data["deliveries"][0] = replace(data["deliveries"][0], **{name: bad})
                    report = self.gate("summarize_delivery_facts", data)
                    self.assertEqual(report.record_issues[0].path, "deliveries[0]." + name)

    def test_true_false_and_named_none_type_valid(self):
        for value in (True, False):
            data = typed_request()
            for group, schema in contract.SCHEMAS.items():
                data[group] = [replace(data[group][0], **{name: value for name in schema["flags"]})]
            self.assertTrue(self.inspect(data).types_and_values_valid)
        self.assertTrue(self.inspect(typed_request()).types_and_values_valid)

    def test_root_scope_flags_exact_types_and_not_auto_A(self):
        for name in ("commitment_scope_complete", "delivery_scope_complete"):
            for bad in (None, "false", 0, 1, HostileTruth()):
                report = self.gate("evaluate_delivery_scope", typed_request() | {name: bad})
                issue = report.request_issues[0]
                self.assertEqual(issue.path, name)
                self.assertFalse(issue.fatal)
                self.assertTrue(report.root_valid)
                self.assertEqual(issue.localization_status, "unproven")

    def test_future_date_cannot_skip_illegal_allocation_and_portion_flags(self):
        data = typed_request()
        data["deliveries"][0] = replace(data["deliveries"][0], actual_date_verified=True)
        data["allocations"][0] = replace(data["allocations"][0], evidence_verified="false")
        data["portions"][0] = replace(data["portions"][0], calculation_eligible=1)
        report = self.gate("evaluate_delivery_scope", data)
        self.assertEqual({i.path for i in report.record_issues},
                         {"allocations[0].evidence_verified", "portions[0].calculation_eligible"})

    def test_empty_allocations_cannot_skip_delivery_flags(self):
        data = typed_request()
        data["allocations"] = []
        data["deliveries"][0] = replace(data["deliveries"][0], evidence_verified="false")
        report = self.gate("evaluate_delivery_scope", data)
        self.assertEqual(report.record_issues[0].path, "deliveries[0].evidence_verified")

    def test_all_records_checked_path_is_not_scope_evidence(self):
        data = typed_request()
        data["deliveries"] = [replace(data["deliveries"][0], evidence_verified="false"),
                              replace(data["deliveries"][0], delivery_id="D2", source_event_key="receipt-D2",
                                      evidence_verified=None)]
        report = self.gate("evaluate_delivery_scope", data)
        self.assertEqual(len(report.record_issues), 2)
        self.assertEqual(dict(report.record_issues[1].record_ref)["delivery_id"], "D2")
        for issue in report.record_issues:
            self.assertEqual(issue.localization_status, "unproven")
            self.assertEqual(issue.localization_basis_refs, ())
            self.assertFalse(issue.fatal)

    def test_presence_null_missing_and_raw_type_are_preserved(self):
        data = raw_request()
        del data["deliveries"][0]["actual_date_verified"]
        data["portions"][0]["commitment_date_verified"] = None
        data["allocations"][0]["evidence_verified"] = "false"
        report = contract.validate_raw_request("evaluate_delivery_scope", data)
        observed = {f.path: f for f in report.observations}
        self.assertEqual(observed["deliveries[0].actual_date_verified"].presence, "missing")
        self.assertEqual(observed["portions[0].commitment_date_verified"].presence, "null")
        self.assertEqual(observed["allocations[0].evidence_verified"].raw_type, "str")

    def test_exact_business_dates_not_datetime_or_subclass(self):
        for group, name in (("deliveries", "actual_date"), ("portions", "commitment_date"), ("portions", "due_date")):
            for value in (datetime(2026, 9, 30), datetime(2026, 9, 30, 16, 30, tzinfo=timezone.utc),
                          DateSubclass(2026, 9, 30), "2026-09-30"):
                data = typed_request()
                data[group][0] = replace(data[group][0], **{name: value})
                report = self.gate("evaluate_delivery_scope", data)
                self.assertEqual(report.record_issues[0].code, "invalid_business_date_type")

    def test_flags_checked_before_quantity_validation(self):
        data = typed_request()
        data["deliveries"][0] = replace(data["deliveries"][0], evidence_verified="false", delivered_quantity="-1")
        report = self.gate("evaluate_delivery_scope", data)
        self.assertEqual([i.code for i in report.record_issues], ["invalid_verification_type", "invalid_exact_quantity"])

    def test_existing_exact_scalar_policy_retained(self):
        for value in ("0.000000000000000000000001", Decimal("1.2"), 1, 0):
            self.assertEqual(core.quantity(value), Decimal(value))
        for value in (True, False, None, 0.1, "-1", "NaN", "Infinity"):
            with self.assertRaises(ValueError):
                core.quantity(value)

    def test_record_bad_structure_does_not_hide_next_record_issue(self):
        data = typed_request()
        data["deliveries"] = [None, replace(data["deliveries"][0], evidence_verified="false")]
        report = self.gate("evaluate_delivery_scope", data)
        self.assertEqual([i.code for i in report.record_issues], ["invalid_record_type", "invalid_verification_type"])

    def test_no_hidden_defaults_shift_old_positional_fields(self):
        p = core.Portion("A", "PO", "LINE", "件", "100", date(2026, 9, 1), None, True, True, "natural_days")
        self.assertTrue(p.evidence_verified)
        self.assertEqual(p.day_basis, "natural_days")
        self.assertIsNone(p.commitment_date_verified)
        self.assertTrue(fields(core.Portion)[-1].kw_only)
        with self.assertRaises(TypeError):
            core.Portion("A", "PO", "LINE", "件", "100", None, None, True, True, None, True)


class RawBoundaryTests(BoundaryAssertions):
    def test_bad_values_rejected_before_any_model_or_bool_str_conversion(self):
        for bad in ("false", 0, 1, None, HostileTruth()):
            data = raw_request()
            data["deliveries"][0]["evidence_verified"] = bad
            # Simulates a lossy adapter; it must never get the invalid input.
            def lossy_model(**row):
                row["evidence_verified"] = bool(row["evidence_verified"])
                row["source_event_key"] = str(row["source_event_key"])
                return core.Delivery(**row)
            factory = Mock(side_effect=lossy_model)
            prepared = contract.prepare_raw_request("evaluate_delivery_scope", data,
                                                    record_types=MODELS | {"deliveries": factory})
            factory.assert_not_called()
            self.assertIsNone(prepared.arguments)
            self.assertTrue(prepared.report.record_issues)

    def test_none_not_deleted_before_defaulting(self):
        for entry in contract.ENTRY_POINTS:
            data = raw_request(entry)
            data["deliveries"][0]["evidence_verified"] = None
            factory = Mock(side_effect=lambda **row: core.Delivery(**{k: v for k, v in row.items() if v is not None}))
            prepared = contract.prepare_raw_request(entry, data, record_types=MODELS | {"deliveries": factory})
            factory.assert_not_called()
            issue = prepared.report.record_issues[0]
            self.assertEqual((issue.presence, issue.raw_type), ("null", "NoneType"))

    def test_datetime_never_truncated_before_raw_validation(self):
        data = raw_request("summarize_delivery_facts")
        original = datetime(2026, 9, 30, 16, 30, tzinfo=timezone.utc)
        data["deliveries"][0]["actual_date"] = original
        factory = Mock(side_effect=lambda **row: core.Delivery(**(row | {"actual_date": row["actual_date"].date()})))
        prepared = contract.prepare_raw_request("summarize_delivery_facts", data, record_types={"deliveries": factory})
        factory.assert_not_called()
        self.assertIs(data["deliveries"][0]["actual_date"], original)
        self.assertEqual(prepared.report.record_issues[0].code, "invalid_business_date_type")

    def test_missing_defaults_only_after_all_raw_fields_valid(self):
        for entry in contract.ENTRY_POINTS:
            data = raw_request(entry)
            del data["deliveries"][0]["evidence_verified"]
            del data["deliveries"][0]["actual_date_verified"]
            original = deepcopy(data)
            prepared = contract.prepare_raw_request(entry, data, record_types=MODELS)
            self.assertTrue(prepared.report.types_and_values_valid)
            self.assertIs(prepared.arguments["deliveries"][0].evidence_verified, False)
            self.assertIsNone(prepared.arguments["deliveries"][0].actual_date_verified)
            self.assertEqual(data, original)
            self.gate(entry, prepared.arguments)

    def test_raw_explicit_named_none_preserved_after_model_construction(self):
        prepared = contract.prepare_raw_request("evaluate_delivery_scope", raw_request(), record_types=MODELS)
        self.assertIsNone(prepared.arguments["deliveries"][0].actual_date_verified)
        self.assertIsNone(prepared.arguments["portions"][0].commitment_date_verified)
        self.assertEqual(prepared.report.date_qualifications["deliveries[0].actual_date"].status, "unverified")

    def test_both_raw_entry_schemas_and_typed_entry_rechecks(self):
        for entry in contract.ENTRY_POINTS:
            prepared = contract.prepare_raw_request(entry, raw_request(entry), record_types=MODELS)
            self.assertIsNotNone(prepared.arguments)
            args = prepared.arguments
            args["deliveries"][0] = replace(args["deliveries"][0], actual_date_verified=1)
            report = self.gate(entry, args)
            self.assertEqual(report.record_issues[0].code, "invalid_date_verification_type")

    def test_missing_required_raw_field_is_not_filled(self):
        data = raw_request()
        del data["deliveries"][0]["actual_date"]
        prepared = contract.prepare_raw_request("evaluate_delivery_scope", data, record_types=MODELS)
        self.assertIsNone(prepared.arguments)
        self.assertIn("missing_record_field", [i.code for i in prepared.report.record_issues])

    def test_invalid_raw_root_and_entry(self):
        for entry, raw in (("evaluate_delivery_scope", None), ("other", raw_request())):
            report = contract.validate_raw_request(entry, raw)
            self.assertFalse(report.root_valid)

    def test_explicit_missing_sentinel_never_reaches_model(self):
        data = raw_request()
        data["deliveries"][0]["evidence_verified"] = contract.MISSING
        factory = Mock()
        prepared = contract.prepare_raw_request("evaluate_delivery_scope", data,
                                                record_types=MODELS | {"deliveries": factory})
        factory.assert_not_called()
        self.assertEqual(prepared.report.record_issues[0].code, "explicit_missing_sentinel")
        self.assertIsNone(prepared.arguments)

    def test_raw_scope_none_is_not_dropped_for_default(self):
        data = raw_request() | {"delivery_scope_complete": None}
        prepared = contract.prepare_raw_request("evaluate_delivery_scope", data, record_types=MODELS)
        self.assertIsNone(prepared.arguments)
        self.assertEqual(prepared.report.request_issues[0].path, "delivery_scope_complete")
        self.assertEqual(prepared.report.request_issues[0].presence, "null")

    def test_raw_quantity_ints_valid_but_invalid_scalars_not_constructed(self):
        for value in (0, 1, "0.5", Decimal("0.125")):
            data = raw_request()
            data["deliveries"][0]["delivered_quantity"] = value
            self.assertTrue(contract.validate_raw_request("evaluate_delivery_scope", data).types_and_values_valid)
        for value in (True, None, 0.1, "-1", "NaN", "Infinity"):
            data["deliveries"][0]["delivered_quantity"] = value
            prepared = contract.prepare_raw_request("evaluate_delivery_scope", data, record_types=MODELS)
            self.assertIsNone(prepared.arguments)
            self.assertEqual(prepared.report.record_issues[0].code, "invalid_exact_quantity")

    def test_raw_validator_does_not_reconstruct_lost_provenance(self):
        data = raw_request()
        # Demonstrate limitation honestly: prior external conversion is unknowable.
        data["deliveries"][0]["evidence_verified"] = bool("false")
        report = contract.validate_raw_request("evaluate_delivery_scope", data)
        self.assertTrue(report.types_and_values_valid)
        self.assertFalse(report.date_qualifications["deliveries[0].actual_date"].formal_eligible)
        self.gate("evaluate_delivery_scope", typed_request())


class DateQualificationTests(BoundaryAssertions):
    def test_none_never_inherits_quantity_true(self):
        d = typed_request()["deliveries"][0]
        self.assertIs(d.evidence_verified, True)
        self.assertFalse(core._has_verified_actual_date(d))
        result = contract.qualify_date(flag=None, value=d.actual_date)
        self.assertEqual((result.status, result.reasons), ("unverified", ("named_date_not_verified",)))

    def test_explicit_true_without_binding_does_not_qualify(self):
        d = replace(typed_request()["deliveries"][0], actual_date_verified=True)
        self.assertFalse(core._has_verified_actual_date(d))
        data = claim()
        self.assertEqual(contract.qualify_date(**data).reasons, ("qualification_basis_required",))

    def test_named_false_none_missing_not_overridden_by_basis(self):
        data = claim()
        basis = basis_for(data)
        for flag in (False, None, contract.MISSING):
            result = contract.qualify_date(**(data | {"flag": flag}), bases=[basis])
            self.assertEqual(result.status, "unverified")
            self.assertFalse(result.formal_eligible)

    def test_bad_flag_not_truthiness_or_equality(self):
        for value in ("false", 0, 1, HostileTruth()):
            result = contract.qualify_date(flag=value, value=CUTOFF)
            self.assertEqual(result.reasons, ("invalid_date_verification_type",))

    def test_actual_and_commitment_fields_have_separate_evidence(self):
        actual, commitment = claim(), claim("commitment_date")
        self.assertEqual(contract.qualify_date(**actual, bases=[basis_for(actual)]).status, "qualified")
        self.assertEqual(contract.qualify_date(**commitment, bases=[basis_for(commitment)]).status, "qualified")
        self.assertEqual(contract.qualify_date(**commitment, bases=[basis_for(actual)]).status, "conflict")

    def test_each_binding_dimension_must_match(self):
        data = claim()
        for field_name, bad in (("subject_ref", ("delivery", "OTHER", "receipt-D", "fact@1")),
                                ("subject_ref", ("delivery", "D", "receipt-D", "fact@2")),
                                ("subject_ref", ("delivery", "D", "OTHER-SOURCE", "fact@1")),
                                ("field_name", "supplier_dispatch_date"), ("value", CUTOFF),
                                ("precision", "minute"), ("time_zone", "UTC"),
                                ("timezone_basis_ref", "normalization@2"),
                                ("qualification_context_ref", "observation@2")):
            with self.subTest(field=field_name):
                basis = basis_for(data) | {field_name: bad}
                result = contract.qualify_date(**data, bases=[basis])
                self.assertEqual(result.status, "conflict")
                self.assertFalse(result.formal_eligible)

    def test_incomplete_evidence_or_decision_never_qualifies(self):
        data = claim()
        for key in ("evidence_id", "evidence_version", "decision_id", "decision_version", "scope_ref"):
            basis = basis_for(data)
            del basis[key]
            self.assertEqual(contract.qualify_date(**data, bases=[basis]).status, "unverified")

    def test_missing_unknown_zone_precision_and_subject_version(self):
        data = claim()
        for key, value in (("time_zone", contract.MISSING), ("time_zone", "unknown"),
                           ("precision", None), ("timezone_basis_ref", None),
                           ("subject_ref", ("delivery", "D", "receipt-D", ""))):
            result = contract.qualify_date(**(data | {key: value}), bases=[basis_for(data)])
            self.assertEqual(result.status, "unverified")

    def test_date_value_does_not_gain_precision_through_datetime(self):
        data = claim()
        for value in (None, datetime(2026, 10, 1), DateSubclass(2026, 10, 1)):
            self.assertEqual(contract.qualify_date(**(data | {"value": value}), bases=[basis_for(data)]).status,
                             "unverified")

    def test_synthetic_matching_not_formal_business_qualification(self):
        data = claim()
        result = contract.qualify_date(**data, bases=[basis_for(data)])
        self.assertEqual((result.status, result.assurance_level), ("qualified", "synthetic_only"))
        self.assertFalse(result.formal_eligible)
        d = replace(typed_request()["deliveries"][0], actual_date_verified=True)
        kwargs = {key: value for key, value in data.items() if key not in ("flag", "value", "field_name")}
        self.assertFalse(core._has_verified_actual_date(d, **kwargs, bases=[basis_for(data)]))

    def test_self_declared_real_source_does_not_grant_formal_qualification(self):
        data = claim()
        for source in ("validated_fields", "warehouse", "email", "ocr", "manual"):
            basis = basis_for(data) | {"assurance_level": source}
            result = contract.qualify_date(**data, bases=[basis])
            self.assertEqual(result.reasons, ("real_source_resolver_not_connected",))
            self.assertFalse(result.formal_eligible)

    def test_quantity_and_actual_date_declarations_independent(self):
        data = typed_request()
        data["deliveries"][0] = replace(data["deliveries"][0], evidence_verified=False, actual_date_verified=True)
        report = self.inspect(data)
        self.assertTrue(report.types_and_values_valid)
        # Pure binding matching is independent of the generic quantity declaration.
        date_claim = claim()
        self.assertEqual(contract.qualify_date(**date_claim, bases=[basis_for(date_claim)]).status, "qualified")
        self.assertFalse(report.date_qualifications["deliveries[0].actual_date"].formal_eligible)

    def test_retracted_expired_or_wrong_scope_not_accepted(self):
        data = claim()
        for state in ("revoked", "expired", "pending"):
            result = contract.qualify_date(**data, bases=[basis_for(data) | {"decision_status": state}])
            self.assertEqual(result.status, "unverified")
        self.assertEqual(contract.qualify_date(**data, bases=[basis_for(data) | {"scope_fields": ("quantity",)}]).status,
                         "conflict")

    def test_conflicting_active_decisions_never_select_latest(self):
        data = claim()
        one = basis_for(data)
        two = one | {"decision_id": "decision-2", "conclusion": False}
        for rows in ([one, two], [two, one]):
            result = contract.qualify_date(**data, bases=rows)
            self.assertEqual(result.status, "conflict")
            self.assertEqual(len(result.decision_refs), 2)

    def test_duplicate_decision_ref_not_extra_vote_and_conflicting_payload_rejected(self):
        data = claim()
        basis = basis_for(data)
        result = contract.qualify_date(**data, bases=[basis, deepcopy(basis)])
        self.assertEqual(len(result.decision_refs), 1)
        result = contract.qualify_date(**data, bases=[basis, basis | {"evidence_version": "E@2"}])
        self.assertEqual(result.reasons, ("decision_identity_conflict",))

    def test_claim_type_legal_does_not_mean_relation_or_calculation_eligible(self):
        report = self.inspect(typed_request())
        self.assertTrue(report.types_and_values_valid)
        for result in report.date_qualifications.values():
            self.assertEqual(result.status, "unverified")
            self.assertFalse(result.formal_eligible)
        self.gate("evaluate_delivery_scope", typed_request())

    def test_wrong_subject_kind_not_date_qualified(self):
        data = claim() | {"subject_ref": ("portion", "D", "receipt-D", "fact@1")}
        self.assertEqual(contract.qualify_date(**data, bases=[basis_for(data)]).status, "unverified")

    def test_decision_conclusion_exact_type(self):
        data = claim()
        for value in (None, 1, 0, "false", HostileTruth()):
            result = contract.qualify_date(**data, bases=[basis_for(data) | {"conclusion": value}])
            self.assertEqual(result.reasons, ("invalid_decision_conclusion",))

    def test_cutoff_day_and_next_day_without_named_basis_both_stay_unverified(self):
        for day in (CUTOFF, date(2026, 10, 1), None):
            for flag in (None, False, True):
                d = replace(typed_request()["deliveries"][0], actual_date=day, actual_date_verified=flag)
                self.assertFalse(core._has_verified_actual_date(d))

    def test_originals_not_mutated_by_qualification_matching(self):
        data = claim()
        basis = basis_for(data)
        before = deepcopy(basis)
        contract.qualify_date(**data, bases=[basis, basis])
        self.assertEqual(basis, before)


class _WAEqualityProbe:
    def __init__(self, *, raises=False):
        self.calls = 0
        self.raises = raises

    def __eq__(self, other):
        self.calls += 1
        if self.raises:
            raise AssertionError("invalid_reference_must_not_be_compared")
        return True


class _WAStringProbe(str):
    def __new__(cls, value):
        obj = str.__new__(cls, value)
        obj.calls = 0
        return obj

    def __eq__(self, other):
        self.calls += 1
        raise AssertionError("string_subclass_must_not_be_compared")


class _WATupleProbe(tuple):
    def __eq__(self, other):
        raise AssertionError("tuple_subclass_must_not_be_compared")


class WA01ReferenceTypeTests(BoundaryAssertions):
    def test_wa01_true_comparator_rejected_on_both_sides_at_each_position(self):
        for side in ("claim", "basis"):
            for position in range(4):
                with self.subTest(side=side, position=position):
                    data = claim()
                    basis = basis_for(data)
                    probe = _WAEqualityProbe()
                    parts = list(data["subject_ref"])
                    parts[position] = probe
                    (data if side == "claim" else basis)["subject_ref"] = tuple(parts)
                    result = contract.qualify_date(**data, bases=[basis])
                    self.assertEqual(result.status, "unverified" if side == "claim" else "conflict")
                    self.assertEqual(result.reasons, ("date_claim_binding_incomplete" if side == "claim"
                                                     else "date_basis_binding_mismatch",))
                    self.assertEqual(probe.calls, 0)
                    self.assertIs(result.formal_eligible, False)

    def test_wa01_raising_comparator_never_called_on_either_side(self):
        for side in ("claim", "basis"):
            for position in range(4):
                with self.subTest(side=side, position=position):
                    data = claim()
                    basis = basis_for(data)
                    probe = _WAEqualityProbe(raises=True)
                    parts = list(data["subject_ref"])
                    parts[position] = probe
                    (data if side == "claim" else basis)["subject_ref"] = tuple(parts)
                    result = contract.qualify_date(**data, bases=[basis])
                    self.assertEqual(result.status, "unverified" if side == "claim" else "conflict")
                    self.assertEqual(probe.calls, 0)
                    self.assertIs(result.formal_eligible, False)

    def test_wa01_reference_container_and_element_types_are_exact(self):
        good = claim()["subject_ref"]
        cases = [("none", None, None), ("missing", contract.MISSING, None),
                 ("list", list(good), None), ("tuple_subclass", _WATupleProbe(good), None),
                 ("short", good[:-1], None), ("long", good + ("extra",), None)]
        for position in range(4):
            for label, value in (("none", None), ("bool", True), ("int", 1), ("empty", ""), ("blank", " ")):
                parts = list(good)
                parts[position] = value
                cases.append((f"element_{position}_{label}", tuple(parts), None))
            probe = _WAStringProbe(good[position])
            parts = list(good)
            parts[position] = probe
            cases.append((f"element_{position}_str_subclass", tuple(parts), probe))
        for side in ("claim", "basis"):
            for label, reference, probe in cases:
                with self.subTest(side=side, case=label):
                    data = claim()
                    basis = basis_for(data)
                    (data if side == "claim" else basis)["subject_ref"] = reference
                    result = contract.qualify_date(**data, bases=[basis])
                    self.assertEqual(result.status, "unverified" if side == "claim" else "conflict")
                    self.assertIs(result.formal_eligible, False)
                    if probe is not None:
                        self.assertEqual(probe.calls, 0)

    def test_wa01_normal_actual_and_commitment_bindings_keep_synthetic_qualification(self):
        for field_name in ("actual_date", "commitment_date"):
            with self.subTest(field=field_name):
                data = claim(field_name)
                basis = basis_for(data)
                before = deepcopy(basis)
                result = contract.qualify_date(**data, bases=[basis])
                self.assertEqual(result.status, "qualified")
                self.assertEqual(result.assurance_level, "synthetic_only")
                self.assertIs(result.formal_eligible, False)
                self.assertEqual(result.decision_refs, (("decision-1", "1"),))
                self.assertEqual(basis, before)

    def test_wa01_other_binding_requirements_are_not_relaxed(self):
        for field_name in ("actual_date", "commitment_date"):
            data = claim(field_name)
            kind, identity, source, version = data["subject_ref"]
            mutations = (
                ("subject_ref", (kind, "OTHER", source, version)),
                ("subject_ref", (kind, identity, source, "fact@2")),
                ("subject_ref", (kind, identity, "OTHER-SOURCE", version)),
                ("subject_ref", ("other-kind", identity, source, version)),
                ("field_name", "supplier_dispatch_date"), ("value", CUTOFF),
                ("precision", "minute"), ("time_zone", "UTC"),
                ("timezone_basis_ref", "normalization@2"),
                ("qualification_context_ref", "observation@2"),
            )
            for index, (name, value) in enumerate(mutations):
                with self.subTest(field=field_name, mutation=index):
                    result = contract.qualify_date(**data, bases=[basis_for(data) | {name: value}])
                    self.assertEqual(result.status, "conflict")
                    self.assertEqual(result.reasons, ("date_basis_binding_mismatch",))
                    self.assertIs(result.formal_eligible, False)

    def test_wa01_mixed_valid_invalid_bases_never_qualify_in_either_order(self):
        for position in range(4):
            for bad_first in (True, False):
                with self.subTest(position=position, bad_first=bad_first):
                    data = claim()
                    good = basis_for(data)
                    probe = _WAEqualityProbe()
                    parts = list(data["subject_ref"])
                    parts[position] = probe
                    bad = basis_for(data) | {"subject_ref": tuple(parts), "decision_id": "other-decision"}
                    bases = [bad, good] if bad_first else [good, bad]
                    result = contract.qualify_date(**data, bases=bases)
                    self.assertEqual(result.status, "conflict")
                    self.assertEqual(result.reasons, ("date_basis_binding_mismatch",))
                    self.assertEqual(probe.calls, 0)
                    self.assertIs(result.formal_eligible, False)
                    self.assertIs(bad["subject_ref"][position], probe)
                    self.assertIs(bases[0], bad if bad_first else good)
                    self.assertEqual(len(bases), 2)


class WA02RootPresenceTests(BoundaryAssertions):
    def test_wa02_explicit_root_missing_is_invalid_before_any_model(self):
        for name in ("delivery_scope_complete", "commitment_scope_complete"):
            with self.subTest(field=name):
                data = raw_request() | {name: contract.MISSING}
                factories = {group: Mock(wraps=model) for group, model in MODELS.items()}
                report = contract.validate_raw_request("evaluate_delivery_scope", data)
                prepared = contract.prepare_raw_request("evaluate_delivery_scope", data, record_types=factories)
                for checked in (report, prepared.report):
                    self.assertFalse(checked.types_and_values_valid)
                    self.assertTrue(checked.root_valid)
                    issue = next(i for i in checked.request_issues if i.path == name)
                    self.assertEqual(issue.code, "explicit_missing_sentinel")
                    self.assertEqual((issue.presence, issue.raw_type), ("present", "MISSING"))
                    self.assertEqual(issue.localization_status, "unproven")
                    self.assertFalse(issue.fatal)
                for factory in factories.values():
                    factory.assert_not_called()
                self.assertIsNone(prepared.arguments)
                self.assertIs(data[name], contract.MISSING)

    def test_wa02_absent_root_fields_keep_false_default_after_validation(self):
        names = ("delivery_scope_complete", "commitment_scope_complete")
        for name in names:
            with self.subTest(field=name):
                data = raw_request()
                del data[name]
                prepared = contract.prepare_raw_request("evaluate_delivery_scope", data, record_types=MODELS)
                self.assertTrue(prepared.report.types_and_values_valid)
                observation = next(o for o in prepared.report.observations if o.path == name)
                self.assertEqual((observation.presence, observation.raw_type), ("missing", "MISSING"))
                self.assertIs(prepared.arguments[name], False)
                other = names[1] if name == names[0] else names[0]
                self.assertIs(prepared.arguments[other], True)
                self.assertNotIn(name, data)
                self.assertTrue(all(type(prepared.arguments[k]) is bool for k in names))
                report = self.gate("evaluate_delivery_scope", prepared.arguments)
                self.assertTrue(report.types_and_values_valid)

    def test_wa02_explicit_root_none_stays_invalid_and_is_not_defaulted(self):
        for name in ("delivery_scope_complete", "commitment_scope_complete"):
            with self.subTest(field=name):
                data = raw_request() | {name: None}
                factories = {group: Mock(wraps=model) for group, model in MODELS.items()}
                prepared = contract.prepare_raw_request("evaluate_delivery_scope", data, record_types=factories)
                self.assertFalse(prepared.report.types_and_values_valid)
                self.assertIsNone(prepared.arguments)
                issue = next(i for i in prepared.report.request_issues if i.path == name)
                self.assertEqual(issue.code, "invalid_verification_type")
                self.assertEqual((issue.presence, issue.raw_type), ("null", "NoneType"))
                self.assertIs(data[name], None)
                for factory in factories.values():
                    factory.assert_not_called()

    def test_wa02_direct_core_rechecks_missing_and_none_without_entering_arithmetic(self):
        for name in ("delivery_scope_complete", "commitment_scope_complete"):
            for label, value in (("missing", contract.MISSING), ("none", None)):
                with self.subTest(field=name, case=label):
                    data = typed_request() | {name: value}
                    report = self.inspect(data)
                    self.assertFalse(report.types_and_values_valid)
                    expected = "explicit_missing_sentinel" if value is contract.MISSING else "invalid_verification_type"
                    issue = next(i for i in report.request_issues if i.path == name)
                    self.assertEqual(issue.code, expected)
                    self.assertEqual(issue.presence, "present" if value is contract.MISSING else "null")
                    with patch.object(core, "_index_delivery_facts", side_effect=AssertionError("arithmetic_entered")) as body:
                        gated = self.gate("evaluate_delivery_scope", data)
                        body.assert_not_called()
                    self.assertEqual(next(i.code for i in gated.request_issues if i.path == name), expected)

    def test_wa02_root_and_record_presence_contracts_match(self):
        for name in ("delivery_scope_complete", "commitment_scope_complete"):
            for state in ("absent", "missing", "none"):
                with self.subTest(field=name, state=state):
                    data = raw_request()
                    del data[name]
                    del data["deliveries"][0]["evidence_verified"]
                    if state != "absent":
                        value = contract.MISSING if state == "missing" else None
                        data[name] = value
                        data["deliveries"][0]["evidence_verified"] = value
                    factories = {group: Mock(wraps=model) for group, model in MODELS.items()}
                    prepared = contract.prepare_raw_request("evaluate_delivery_scope", data, record_types=factories)
                    record_path = "deliveries[0].evidence_verified"
                    observations = {o.path: o for o in prepared.report.observations}
                    expected_presence = {"absent": "missing", "missing": "present", "none": "null"}[state]
                    expected_type = "NoneType" if state == "none" else "MISSING"
                    for path in (name, record_path):
                        self.assertEqual((observations[path].presence, observations[path].raw_type),
                                         (expected_presence, expected_type))
                    if state == "absent":
                        self.assertTrue(prepared.report.types_and_values_valid)
                        self.assertIs(prepared.arguments[name], False)
                        self.assertIs(prepared.arguments["deliveries"][0].evidence_verified, False)
                    else:
                        self.assertFalse(prepared.report.types_and_values_valid)
                        self.assertIsNone(prepared.arguments)
                        expected_code = "explicit_missing_sentinel" if state == "missing" else "invalid_verification_type"
                        for issues, path in ((prepared.report.request_issues, name),
                                             (prepared.report.record_issues, record_path)):
                            issue = next(i for i in issues if i.path == path)
                            self.assertEqual((issue.code, issue.presence, issue.raw_type),
                                             (expected_code, expected_presence, expected_type))
                        for factory in factories.values():
                            factory.assert_not_called()

    def test_wa02_legal_boolean_values_remain_unchanged(self):
        for name in ("delivery_scope_complete", "commitment_scope_complete"):
            for value in (True, False):
                with self.subTest(field=name, value=value):
                    data = raw_request() | {name: value}
                    prepared = contract.prepare_raw_request("evaluate_delivery_scope", data, record_types=MODELS)
                    self.assertTrue(prepared.report.types_and_values_valid)
                    self.assertIs(prepared.arguments[name], value)
                    observation = next(o for o in prepared.report.observations if o.path == name)
                    self.assertEqual((observation.presence, observation.raw_type), ("present", "bool"))
                    self.assertIs(data[name], value)
                    report = self.gate("evaluate_delivery_scope", prepared.arguments)
                    self.assertTrue(report.types_and_values_valid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
