"""WP-2 TR09/P202 STRUCTURE subassertions only; full numeric cases stay pending."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, getcontext
import unittest

from app.services import audit_delivery_fragments as f
from app.services.audit_delivery_contract import V2


def fixture(source="D", quantity="80", segments=None, version="fv1", partition="pv1", unit="件"):
    if segments is None:
        segments = (("S", "0", quantity, quantity, "G"),)
    context = f.ValidationContext(V2, "manifest@1", "observation@1")
    ref = f.FactRef(source, version)
    basis_ref = ("partition-" + source, partition)
    basis = f.PartitionBasis(basis_ref, ref, partition, unit, context.manifest_ref,
                             context.observation_ref, ("evidence-" + source, "1"), tuple(segments))
    definitions = tuple(f.Fragment(f.FragmentKey(ref, partition, sid), start, end, amount, unit, group, basis_ref)
                        for sid, start, end, amount, group in segments)
    return f.FragmentManifest(context, (f.ParentFact(ref, "receipt-" + source, unit, quantity),),
                              (basis,), definitions)


def combine(*manifests):
    first = manifests[0]
    return replace(first, **{field: sum((getattr(m, field) for m in manifests), ()) for field in
                            ("facts", "partition_bases", "definitions", "active_relations",
                             "history_relations", "issue_references")})


def codes(result):
    return {i.code for i in result.issues}


class NoCompare:
    def __init__(self):
        self.calls = 0

    def __eq__(self, other):
        self.calls += 1
        raise AssertionError("unvalidated_identity_compared")

    def __hash__(self):
        self.calls += 1
        raise AssertionError("unvalidated_identity_hashed")


class FragmentTests(unittest.TestCase):
    def test_tr09_adjacent_ranges_are_structurally_valid(self):
        m = fixture(segments=(("A", "0", "50", "50", "G1"), ("B", "50", "80", "30", "G2")))
        r = f.validate_fragment_manifest(m)
        self.assertEqual(r.status, "validated_structure")
        self.assertEqual(r.structurally_valid_keys, tuple(d.key for d in m.definitions))
        self.assertEqual(r.canonical_fact_refs, (m.facts[0].ref,))
        self.assertEqual(r.uncovered_ranges, ())
        self.assertFalse(r.calculation_performed)
        self.assertFalse(r.formal_eligible)

    def test_p202_same_key_different_legal_payload_conflicts_before_overlap(self):
        m = fixture()
        other = replace(m.definitions[0], end="40", quantity="40")
        r = f.validate_fragment_manifest(replace(m, definitions=m.definitions + (other,)))
        self.assertIn("fragment_identity_conflict", codes(r))
        self.assertNotIn("overlapping_fragment_ranges", codes(r))
        self.assertEqual(r.structurally_valid_keys, ())
        self.assertEqual(r.canonical_fact_refs, (m.facts[0].ref,))
        self.assertEqual(r.uncovered_ranges, ())

    def test_p202_same_key_changed_control_or_basis_is_still_conflict(self):
        m = fixture()
        for change in ({"control_group": "OTHER"}, {"basis_ref": ("OTHER", "1")}):
            with self.subTest(field=next(iter(change))):
                r = f.validate_fragment_manifest(replace(m, definitions=m.definitions + (replace(m.definitions[0], **change),)))
                self.assertIn("fragment_identity_conflict", codes(r))
                self.assertEqual(r.structurally_valid_keys, ())

    def test_p202_duplicate_definition_is_not_silently_deduplicated(self):
        m = fixture()
        r = f.validate_fragment_manifest(replace(m, definitions=m.definitions * 2))
        self.assertIn("duplicate_fragment_definition", codes(r))
        self.assertEqual(r.structurally_valid_keys, ())
        self.assertEqual(len(r.canonical_fact_refs), 1)

    def test_p202_many_issue_references_do_not_duplicate_facts_or_definitions(self):
        m = fixture()
        key = m.definitions[0].key
        ref = f.FragmentReference(key.fragment_id, key.parent_fact_ref, key.partition_version)
        r = f.validate_fragment_manifest(replace(m, issue_references=(ref, ref, ref)))
        self.assertEqual(r.status, "validated_structure")
        self.assertEqual(len(r.canonical_fact_refs), 1)
        self.assertEqual(r.structurally_valid_keys, (key,))
        self.assertEqual(r.resolved_issue_references, (key, key, key))

    def test_p202_same_fragment_name_different_parents_remain_distinct(self):
        m = combine(fixture("D1"), fixture("D2"))
        r = f.validate_fragment_manifest(m)
        self.assertEqual(r.status, "validated_structure")
        self.assertEqual(len(r.canonical_fact_refs), 2)
        self.assertEqual(len(r.structurally_valid_keys), 2)

    def test_p202_bare_reference_is_not_inferred_even_with_one_match(self):
        for m, expected in ((fixture(), "incomplete_fragment_reference"),
                            (combine(fixture("D1"), fixture("D2")), "ambiguous_fragment_reference")):
            with self.subTest(expected=expected):
                r = f.validate_fragment_manifest(replace(m, issue_references=(f.FragmentReference("S"),)))
                self.assertIn(expected, codes(r))
                self.assertEqual(r.resolved_issue_references, ())

    def test_wrong_parent_basis_is_not_moved_to_other_parent(self):
        d, c = fixture(), fixture("C", "20")
        wrong = replace(d.partition_bases[0], parent_fact_ref=c.facts[0].ref)
        m = combine(replace(d, partition_bases=(wrong,)), c)
        r = f.validate_fragment_manifest(m)
        self.assertIn("partition_basis_binding_mismatch", codes(r))
        self.assertNotIn(d.definitions[0].key, r.structurally_valid_keys)
        self.assertIn(c.definitions[0].key, r.structurally_valid_keys)

    def test_full_wrong_parent_reference_never_selects_first(self):
        m = fixture()
        ref = f.FragmentReference("S", f.FactRef("OTHER", "fv1"), "pv1")
        r = f.validate_fragment_manifest(replace(m, issue_references=(ref,)))
        self.assertIn("unavailable_fragment_reference", codes(r))
        self.assertEqual(r.resolved_issue_references, ())
        self.assertEqual(r.status, "scope_unproven")

    def test_tr09_length_mismatch_keeps_parent_and_does_not_manufacture_gap(self):
        m = fixture(segments=(("S", "0", "50", "40", "G"),))
        r = f.validate_fragment_manifest(m)
        self.assertIn("invalid_fragment_interval_or_length", codes(r))
        self.assertEqual(len(r.canonical_fact_refs), 1)
        self.assertEqual(r.uncovered_ranges, ())
        self.assertEqual(r.coverage_undetermined_parents, (m.facts[0].ref,))

    def test_tr09_all_overlaps_including_nested_ranges_are_rejected(self):
        m = fixture(quantity="100", segments=(("A", "0", "70", "70", "G"),
                                              ("B", "10", "20", "10", "G"),
                                              ("C", "30", "40", "10", "G")))
        r = f.validate_fragment_manifest(m)
        self.assertIn("overlapping_fragment_ranges", codes(r))
        self.assertEqual(r.structurally_valid_keys, ())
        self.assertEqual(set(r.rejected_keys), {d.key for d in m.definitions})

    def test_p202_changing_id_does_not_bypass_same_range_overlap(self):
        m = fixture()
        second = replace(m.definitions[0], key=replace(m.definitions[0].key, fragment_id="OTHER"))
        ranges = m.partition_bases[0].ranges + (("OTHER", "0", "80", "80", "G"),)
        m = replace(m, definitions=m.definitions + (second,), partition_bases=(replace(m.partition_bases[0], ranges=ranges),))
        r = f.validate_fragment_manifest(m)
        self.assertIn("overlapping_fragment_ranges", codes(r))
        self.assertEqual(r.structurally_valid_keys, ())

    def test_tr09_gaps_share_control_and_are_not_new_receipts(self):
        m = fixture(segments=(("S", "10", "40", "30", "G"),))
        r = f.validate_fragment_manifest(m)
        self.assertEqual([(g.start, g.end, g.quantity) for g in r.uncovered_ranges],
                         [(Decimal(0), Decimal(10), Decimal(10)), (Decimal(40), Decimal(80), Decimal(40))])
        self.assertEqual(r.uncovered_ranges[0].control_ref, r.uncovered_ranges[1].control_ref)
        self.assertEqual(len(r.canonical_fact_refs), 1)
        self.assertFalse(r.formal_eligible)

    def test_tr09_zero_parent_has_no_fragment(self):
        m = fixture(quantity="0", segments=())
        r = f.validate_fragment_manifest(m)
        self.assertEqual(r.status, "validated_structure")
        self.assertEqual(len(r.canonical_fact_refs), 1)
        self.assertEqual(r.structurally_valid_keys, ())
        self.assertEqual(r.uncovered_ranges, ())

    def test_tr09_invalid_intervals_and_scalar_types_are_not_repaired(self):
        for start, end, amount in (("0", "0", "0"), ("-1", "80", "81"), ("0", "81", "81"),
                                   ("50", "40", "10"), ("0", "80", "-1"), ("0", "80", True),
                                   ("0", "80", 0.1), ("0", "80", None), ("0", "80", "NaN"), ("0", "80", "Infinity")):
            with self.subTest(start=start, end=end, amount_type=type(amount).__name__):
                m = fixture(segments=(("S", start, end, amount, "G"),))
                r = f.validate_fragment_manifest(m)
                self.assertEqual(r.structurally_valid_keys, ())
                self.assertTrue(codes(r) & {"invalid_fragment_value", "invalid_fragment_interval_or_length", "invalid_partition_basis"})
                self.assertFalse(r.formal_eligible)

    def test_tr09_decimal_exactness_and_micro_difference(self):
        for second, valid in (("0.2", True), ("0.20000000000000000000000000001", False)):
            with self.subTest(valid=valid):
                m = fixture(quantity="0.3", segments=(("A", "0", "0.1", "0.1", "G1"),
                                                      ("B", "0.1", "0.3", second, "G2")))
                r = f.validate_fragment_manifest(m)
                self.assertEqual(len(r.structurally_valid_keys), 2 if valid else 1)
                self.assertEqual(r.status, "validated_structure" if valid else "partial")
                if valid:
                    self.assertEqual(r.uncovered_ranges, ())

    def test_long_decimal_coordinates_use_local_precision_without_changing_global_context(self):
        before = getcontext().prec
        q = "100000000000000000000000000000.3"
        m = fixture(quantity=q, segments=(("S", "0.1", q, "100000000000000000000000000000.2", "G"),))
        r = f.validate_fragment_manifest(m)
        self.assertEqual(r.status, "validated_structure")
        self.assertEqual(r.uncovered_ranges[0].quantity, Decimal("0.1"))
        self.assertEqual(getcontext().prec, before)

    def test_tr09_two_effective_versions_cannot_select_latest(self):
        m = fixture()
        key = m.definitions[0].key
        rows = (f.EffectiveRelation("R", "v1", key, ("PO", "I", "件", "A", "1"), ("E", "1")),
                f.EffectiveRelation("R", "v2", key, ("PO", "I", "件", "B", "1"), ("E", "2")))
        for ordered in (rows, rows[::-1]):
            with self.subTest(reversed=ordered[0].version == "v2"):
                r = f.validate_fragment_manifest(replace(m, active_relations=ordered))
                self.assertIn("effective_relation_conflict_or_missing_fragment", codes(r))
                self.assertEqual(r.structurally_valid_keys, ())

    def test_tr09_history_and_nonoverlapping_effective_old_new_relations_are_separate(self):
        m = fixture(segments=(("A", "0", "50", "50", "G1"), ("B", "50", "80", "30", "G2")))
        a, b = (d.key for d in m.definitions)
        first = f.EffectiveRelation("R", "v1", a, ("PO", "I", "件", "A", "1"), ("E", "1"))
        second = f.EffectiveRelation("R", "v2", b, ("PO", "I", "件", "B", "1"), ("E", "2"))
        historical = replace(second, version="v1")
        m = replace(m, active_relations=(first, second), history_relations=(historical, historical))
        r = f.validate_fragment_manifest(m)
        self.assertEqual(r.status, "validated_structure")
        self.assertEqual(len(r.canonical_fact_refs), 1)
        self.assertEqual(len(r.structurally_valid_keys), 2)
        self.assertEqual(len(r.input_manifest.history_relations), 2)

    def test_one_relation_version_can_reference_distinct_nonoverlapping_fragments(self):
        m = fixture(segments=(("A", "0", "50", "50", "G1"), ("B", "50", "80", "30", "G2")))
        rows = tuple(f.EffectiveRelation("R", "v1", d.key, ("PO", "I", "件", d.key.fragment_id, "1"), ("E", "1")) for d in m.definitions)
        r = f.validate_fragment_manifest(replace(m, active_relations=rows))
        self.assertEqual(r.status, "validated_structure")
        self.assertEqual(len(r.structurally_valid_keys), 2)

    def test_active_parent_versions_conflict_but_independent_parent_is_preserved(self):
        m = combine(fixture(version="fv1", partition="p1"), fixture(version="fv2", partition="p2"), fixture("C", "20"))
        r = f.validate_fragment_manifest(m)
        self.assertIn("conflicting_active_fact_identity", codes(r))
        self.assertEqual(r.canonical_fact_refs, (f.FactRef("C", "fv1"),))
        self.assertEqual(r.structurally_valid_keys, (m.definitions[-1].key,))

    def test_duplicate_parent_definition_not_counted_twice(self):
        m = fixture()
        r = f.validate_fragment_manifest(replace(m, facts=m.facts * 2))
        self.assertIn("duplicate_parent_definition", codes(r))
        self.assertEqual(r.canonical_fact_refs, ())

    def test_duplicate_delivery_id_with_different_sources_is_not_arbitrarily_accepted(self):
        a, b = fixture("A"), fixture("B")
        b = replace(b, facts=(replace(b.facts[0], delivery_id=a.facts[0].delivery_id),))
        r = f.validate_fragment_manifest(combine(a, b))
        self.assertIn("conflicting_active_fact_identity", codes(r))
        self.assertEqual(r.canonical_fact_refs, ())

    def test_bad_identity_is_checked_before_hash_or_equality(self):
        for field in ("source", "version", "partition", "fragment"):
            with self.subTest(field=field):
                m = fixture()
                probe = NoCompare()
                key = m.definitions[0].key
                if field in ("source", "version"):
                    key = replace(key, parent_fact_ref=f.FactRef(probe, "fv1") if field == "source" else f.FactRef("D", probe))
                else:
                    key = replace(key, **{"partition_version" if field == "partition" else "fragment_id": probe})
                r = f.validate_fragment_manifest(replace(m, definitions=(replace(m.definitions[0], key=key),)))
                self.assertIn("invalid_fragment_identity", codes(r))
                self.assertEqual(probe.calls, 0)
                self.assertEqual(r.structurally_valid_keys, ())

    def test_context_is_explicit_synthetic_and_not_a_formal_source_switch(self):
        for changes in ({"contract_version": "b002-quantity-v1"}, {"assurance_level": "validated_fields"},
                        {"manifest_ref": None}, {"observation_ref": ""}):
            with self.subTest(field=next(iter(changes))):
                m = fixture()
                r = f.validate_fragment_manifest(replace(m, context=replace(m.context, **changes)))
                self.assertEqual(r.status, "request_rejected")
                self.assertFalse(r.formal_eligible)

    def test_bad_local_fragment_does_not_discard_independent_c(self):
        d = fixture(segments=(("S", "0", "80", "79", "G"),))
        c = fixture("C", "20")
        r = f.validate_fragment_manifest(combine(d, c))
        self.assertEqual(r.status, "partial")
        self.assertIn(c.definitions[0].key, r.structurally_valid_keys)
        self.assertNotIn(d.definitions[0].key, r.structurally_valid_keys)
        self.assertEqual(len(r.canonical_fact_refs), 2)

    def test_same_parent_reliable_fragment_is_retained_beside_bad_fragment(self):
        m = fixture(segments=(("A", "0", "50", "50", "G1"), ("B", "50", "80", "29", "G2")))
        r = f.validate_fragment_manifest(m)
        self.assertEqual(r.structurally_valid_keys, (m.definitions[0].key,))
        self.assertEqual(r.uncovered_ranges, ())
        self.assertEqual(r.coverage_undetermined_parents, (m.facts[0].ref,))

    def test_partition_basis_version_and_observation_cannot_be_reused(self):
        for changes in ({"manifest_ref": "OLD"}, {"observation_ref": "OLD"}, {"partition_version": "OLD"}):
            with self.subTest(field=next(iter(changes))):
                m = fixture()
                r = f.validate_fragment_manifest(replace(m, partition_bases=(replace(m.partition_bases[0], **changes),)))
                self.assertIn("partition_basis_binding_mismatch", codes(r))
                self.assertEqual(r.structurally_valid_keys, ())

    def test_conflicting_basis_definitions_are_not_selected_by_order(self):
        m = fixture()
        bases = (m.partition_bases[0], replace(m.partition_bases[0], evidence_ref=("OTHER", "1")))
        for rows in (bases, bases[::-1]):
            with self.subTest(first=rows[0].evidence_ref[0]):
                r = f.validate_fragment_manifest(replace(m, partition_bases=rows))
                self.assertIn("conflicting_partition_basis", codes(r))
                self.assertEqual(r.structurally_valid_keys, ())

    def test_input_permutation_and_no_mutation(self):
        m = combine(fixture("A"), fixture("B"))
        before = deepcopy(m)
        a = f.validate_fragment_manifest(m)
        b = f.validate_fragment_manifest(replace(m, facts=m.facts[::-1], definitions=m.definitions[::-1], partition_bases=m.partition_bases[::-1]))
        self.assertEqual(a.canonical_fact_refs, b.canonical_fact_refs)
        self.assertEqual(a.structurally_valid_keys, b.structurally_valid_keys)
        self.assertEqual(a.uncovered_ranges, b.uncovered_ranges)
        self.assertEqual(m, before)

    def test_no_numeric_audit_result_is_exposed(self):
        r = f.validate_fragment_manifest(fixture())
        for field in ("remaining_quantity", "age_days", "overdue_quantity", "qualified_delivery_quantity"):
            self.assertFalse(hasattr(r, field))
        self.assertFalse(r.calculation_performed)
        self.assertFalse(r.formal_eligible)


class PartitionCompositionRegressionTests(unittest.TestCase):
    def mixed(self):
        first = fixture(segments=(("A", "0", "50", "50", "G1"),), partition="pv1")
        second = fixture(segments=(("B", "50", "80", "30", "G2"),), partition="pv2")
        return replace(combine(first, second), facts=first.facts)

    def test_same_parent_adjacent_mixed_partitions_need_composition_basis(self):
        m = self.mixed()
        before = deepcopy(m)
        result = f.validate_fragment_manifest(m)
        self.assertIn("partition_composition_unproven", codes(result))
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.structurally_valid_keys, ())
        self.assertEqual(set(result.rejected_keys), {d.key for d in m.definitions})
        self.assertEqual(result.canonical_fact_refs, (m.facts[0].ref,))
        self.assertEqual(result.coverage_undetermined_parents, (m.facts[0].ref,))
        self.assertEqual(result.uncovered_ranges, ())
        self.assertEqual(m, before)
        self.assertIs(result.input_manifest, m)
        self.assertFalse(result.calculation_performed)
        self.assertFalse(result.formal_eligible)

    def test_mixed_parent_does_not_reject_independent_c(self):
        c = fixture("C", "20")
        result = f.validate_fragment_manifest(combine(self.mixed(), c))
        self.assertEqual(result.structurally_valid_keys, (c.definitions[0].key,))
        self.assertEqual(len(result.canonical_fact_refs), 2)
        self.assertEqual(result.coverage_undetermined_parents, (f.FactRef("D", "fv1"),))

    def test_different_parents_can_use_different_partition_versions(self):
        m = combine(fixture("D", partition="pv1"), fixture("C", "20", partition="pv2"))
        result = f.validate_fragment_manifest(m)
        self.assertEqual(result.status, "validated_structure")
        self.assertEqual(len(result.structurally_valid_keys), 2)
        self.assertNotIn("partition_composition_unproven", codes(result))

    def test_relation_versions_and_historical_partition_are_not_current_partition_mix(self):
        m = fixture(segments=(("A", "0", "50", "50", "G1"), ("B", "50", "80", "30", "G2")))
        a, b = (d.key for d in m.definitions)
        old = f.EffectiveRelation("R", "v1", a, ("PO", "I", "件", "A", "1"), ("E", "1"))
        new = f.EffectiveRelation("R", "v2", b, ("PO", "I", "件", "B", "1"), ("E", "2"))
        historical = replace(old, fragment=replace(a, partition_version="pv0"))
        result = f.validate_fragment_manifest(replace(m, active_relations=(old, new), history_relations=(historical,)))
        self.assertEqual(result.status, "validated_structure")
        self.assertEqual(result.structurally_valid_keys, (a, b))
        self.assertEqual(result.input_manifest.history_relations, (historical,))

    def test_partition_mix_is_order_independent_and_never_selects_first(self):
        m = self.mixed()
        a = f.validate_fragment_manifest(m)
        b = f.validate_fragment_manifest(replace(m, definitions=m.definitions[::-1], partition_bases=m.partition_bases[::-1]))
        self.assertEqual(a.status, b.status)
        self.assertEqual(a.structurally_valid_keys, ())
        self.assertEqual(a.rejected_keys, b.rejected_keys)
        self.assertEqual(a.coverage_undetermined_parents, b.coverage_undetermined_parents)
        self.assertIn("partition_composition_unproven", codes(b))

    def test_unused_partition_basis_does_not_create_current_composition(self):
        m = self.mixed()
        result = f.validate_fragment_manifest(replace(m, definitions=m.definitions[:1]))
        self.assertEqual(result.status, "validated_structure")
        self.assertEqual(result.structurally_valid_keys, (m.definitions[0].key,))
        self.assertEqual([g.quantity for g in result.uncovered_ranges], [Decimal("30")])

    def test_mixed_partition_does_not_hide_illegal_quantity(self):
        m = self.mixed()
        for value in ("-1", None, True):
            with self.subTest(value_type=type(value).__name__):
                changed = replace(m, definitions=(m.definitions[0], replace(m.definitions[1], quantity=value)))
                result = f.validate_fragment_manifest(changed)
                self.assertIn("invalid_fragment_value", codes(result))
                self.assertIn("partition_composition_unproven", codes(result))
                self.assertEqual(result.structurally_valid_keys, ())
                self.assertEqual(len(result.canonical_fact_refs), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
