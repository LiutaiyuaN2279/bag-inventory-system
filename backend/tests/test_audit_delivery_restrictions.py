"""WP-2 TR08/TR11/P201 restriction subassertions; no balance/day/total tests."""
from copy import deepcopy
from dataclasses import replace
import unittest

from app.services import audit_delivery_fragments as f
from app.services import audit_delivery_restrictions as r
from test_audit_delivery_fragments import fixture, combine, NoCompare


ALL = ("physical_receipt", "cutoff_receipt", "calculation_inclusion", "allocation_use", "portion_balance",
       "age_days", "overdue_quantity", "overdue_days", "line_total", "arrival_absence",
       "historical_traceability", "formal_eligibility")


def nt(node):
    return (node.kind,) + node.identity


def pnode(name):
    return r.Node("portion", ("PO", "LINE", "件", name, "v1"))


class GraphFixture:
    """Construct explicit synthetic proof payloads, never patch validators."""
    def __init__(self, fragments, names=("A", "B", "C"), targets=None):
        targets = {} if targets is None else targets
        rows = []
        for index, d in enumerate(fragments.definitions):
            target = targets.get(d.key.fragment_id, targets.get(d.key.parent_fact_ref.source_event_key))
            if target is not None:
                rows.append(f.EffectiveRelation("R" + str(index), "v1", d.key, pnode(target).identity, ("approval", "v1")))
        self.fragments = replace(fragments, active_relations=tuple(rows))
        self.nodes = {r.fact_node(x.ref) for x in fragments.facts}
        self.nodes.update(r.fragment_node(x.key) for x in fragments.definitions)
        self.nodes.update(pnode(n) for n in names)
        self.proofs, self.dependencies, self.scopes, self.protections, self.seeds = [], [], [], [], []

    def proof(self, purpose, subject, binding):
        ref = ("proof-" + str(len(self.proofs)), "v1")
        c = self.fragments.context
        self.proofs.append(r.BindingProof(ref, purpose, subject, binding, c.manifest_ref, c.observation_ref, ("evidence", "v1")))
        return ref

    def edge(self, source, target, metrics=ALL):
        self.nodes.update((source, target))
        proof = self.proof("dependency", source, (nt(target), tuple(sorted(metrics))))
        self.dependencies.append(r.Dependency(source, target, tuple(metrics), proof))

    def scope(self, subject, candidates, original=(), possible=()):
        self.nodes.add(subject)
        self.nodes.update(candidates + original + possible)
        protection = self.proof("protection", subject, tuple(nt(n) for n in sorted(original)))
        self.protections.append(r.Protection(subject, tuple(original), protection))
        payload = tuple(tuple(nt(n) for n in sorted(group)) for group in (candidates, original, possible))
        proof = self.proof("scope", subject, payload)
        self.scopes.append(r.ImpactScope(subject, tuple(candidates), tuple(original), tuple(possible), proof))

    def seed(self, reason, kind, subject):
        self.seeds.append(r.RestrictionSeed(reason, kind, subject, (("reason-evidence", "v1"),)))

    def finish(self, exclude=None, omit_closure=()):
        exclude = {} if exclude is None else exclude
        incoming = {n: set() for n in self.nodes}
        for edge in self.dependencies:
            incoming[edge.target].add(edge.source)
        for scope in self.scopes:
            for target in scope.candidate_targets + scope.original_targets + scope.possible_targets:
                incoming[target].add(scope.subject)
        closures = []
        universe = tuple(nt(n) for n in sorted(self.nodes))
        for node in sorted(self.nodes):
            if node.kind == "portion" and node not in omit_closure:
                excluded = tuple(exclude.get(node, ()))
                binding = (universe, tuple(nt(n) for n in sorted(incoming[node])), tuple(nt(n) for n in sorted(excluded)))
                proof = self.proof("closure", node, binding)
                closures.append(r.Closure(node, excluded, proof))
        return r.RestrictionManifest(self.fragments, tuple(sorted(self.nodes)), tuple(self.proofs),
                                     tuple(self.dependencies), tuple(self.scopes), tuple(self.protections), tuple(closures), tuple(self.seeds))


def three(scoped=True, candidates=None):
    g = GraphFixture(combine(fixture("D"), fixture("C", "20")), targets={"D": "B", "C": "C"})
    d, c = (r.fragment_node(x.key) for x in g.fragments.definitions)
    for fact, segment in zip(g.fragments.facts, (d, c)):
        g.edge(r.fact_node(fact.ref), segment)
    g.edge(c, pnode("C"))
    if scoped:
        g.scope(d, (pnode("B"),) if candidates is None else candidates, (pnode("B"),))
    return g, d, c


def rows(result):
    return {row.node: row for row in result.node_restrictions}


def blocked(result, node):
    return dict(rows(result)[node].blocked)


def icodes(result):
    return {i.code for i in result.issues}


class RestrictionTests(unittest.TestCase):
    def test_repeated_dependency_reference_has_canonical_order_and_no_extra_effect(self):
        g, d, c = three()
        g.seed("time", "time_conflict", d)
        request = g.finish()
        edge = request.dependencies[0]
        reversed_metrics = replace(edge, metrics=edge.metrics[::-1])
        one = replace(request, dependencies=request.dependencies + (reversed_metrics,))
        two = replace(request, dependencies=(reversed_metrics,) + request.dependencies)
        a, b = r.map_restrictions(one), r.map_restrictions(two)
        self.assertEqual(a.used_dependencies, b.used_dependencies)
        self.assertEqual(a.node_restrictions, b.node_restrictions)
        self.assertEqual(a.propagation_steps, b.propagation_steps)
        self.assertEqual(len(a.fragment_validation.canonical_fact_refs), 2)
        self.assertIs(one.dependencies[-1], reversed_metrics)

    def test_history_only_bad_reference_does_not_taint_current_independent_fragments(self):
        g, d, c = three()
        g.fragments = replace(g.fragments, history_relations=(None,))
        result = r.map_restrictions(g.finish())
        self.assertIn("historical_reference_limited", icodes(result))
        self.assertEqual(result.status, "partial")
        self.assertEqual(rows(result)[pnode("C")].state, "unrestricted_by_supplied_reasons")
        self.assertEqual(len(result.fragment_validation.structurally_valid_keys), 2)
        self.assertEqual(result.input_manifest.fragments.history_relations, (None,))
        self.assertFalse(result.formal_eligible)

    def test_due_and_history_only_fragment_reasons_do_not_invent_quantity_uncertainty(self):
        for kind, expected in (("due_basis_missing", {"overdue_quantity", "overdue_days"}),
                               ("history_limited", {"historical_traceability", "formal_eligibility"})):
            with self.subTest(kind=kind):
                g, d, c = three()
                g.seed("non-quantity-C", kind, c)
                result = r.map_restrictions(g.finish())
                self.assertEqual(set(blocked(result, pnode("C"))), expected)
                self.assertEqual(rows(result)[pnode("C")].state, "restricted")
                self.assertNotIn("portion_balance", blocked(result, pnode("C")))
                self.assertNotIn("propagated_restriction_scope_missing", icodes(result))

    def test_empty_uncertainty_scope_cannot_prove_no_portion_is_affected(self):
        g = GraphFixture(combine(fixture("D"), fixture("C", "20")), targets={"C": "C"})
        d, c = (r.fragment_node(x.key) for x in g.fragments.definitions)
        g.edge(c, pnode("C"))
        g.scope(d, (), ())
        g.seed("pending-D", "allocation_pending", d)
        result = r.map_restrictions(g.finish(exclude={pnode("C"): (d,)}))
        self.assertIn("impact_scope_unproven", icodes(result))
        self.assertEqual(rows(result)[pnode("A")].state, "scope_unproven")
        self.assertEqual(rows(result)[pnode("C")].state, "unrestricted_by_supplied_reasons")
        self.assertEqual(len(result.fragment_validation.canonical_fact_refs), 2)

    def test_scope_and_relation_dependencies_cannot_convert_units(self):
        for via in ("scope", "dependency"):
            with self.subTest(via=via):
                m = combine(fixture("D", unit="米" if via == "scope" else "件"),
                            fixture("C", "20", unit="米" if via == "dependency" else "件"))
                g = GraphFixture(m, targets={"D": "B", "C": "C"})
                d, c = (r.fragment_node(x.key) for x in m.definitions)
                g.scope(d, (pnode("B"),), (pnode("B"),))
                g.edge(c, pnode("C"))
                g.seed("time-D", "time_conflict", d)
                result = r.map_restrictions(g.finish())
                if via == "scope":
                    self.assertIn("impact_scope_unproven", icodes(result))
                    self.assertEqual(rows(result)[pnode("B")].state, "scope_unproven")
                else:
                    self.assertIn("dependency_binding_unproven", icodes(result))
                    self.assertEqual(rows(result)[pnode("C")].state, "scope_unproven")

    def test_parent_field_dependency_cannot_bind_another_facts_fragment(self):
        g, d, c = three()
        wrong_parent = r.fact_node(g.fragments.facts[0].ref)
        g.edge(wrong_parent, c)
        g.seed("date-D", "actual_date_unverified", wrong_parent)
        result = r.map_restrictions(g.finish())
        self.assertIn("dependency_binding_unproven", icodes(result))
        self.assertFalse(any(e.source == wrong_parent and e.target == c for e in result.used_dependencies))

    def test_bad_local_metadata_does_not_discard_independent_c(self):
        for kind in ("partition_basis", "effective_relation"):
            with self.subTest(kind=kind):
                g, d, c = three()
                m = g.fragments
                if kind == "partition_basis":
                    g.fragments = replace(m, partition_bases=(replace(m.partition_bases[0], ref=None),) + m.partition_bases[1:])
                else:
                    g.fragments = replace(m, active_relations=(replace(m.active_relations[0], target_ref=None),) + m.active_relations[1:])
                result = r.map_restrictions(g.finish())
                self.assertEqual(rows(result)[pnode("C")].state, "unrestricted_by_supplied_reasons")
                self.assertIn(m.definitions[1].key, result.fragment_validation.structurally_valid_keys)

    def test_v03_reason_metric_matrix_has_exact_masks(self):
        portion = {"portion_balance", "age_days", "overdue_quantity", "overdue_days"}
        relation = portion | {"calculation_inclusion", "allocation_use", "line_total"}
        expected = {
            "invalid_record": relation,
            "quantity_unverified": set(ALL) - {"historical_traceability", "formal_eligibility"},
            "actual_date_unverified": relation | {"cutoff_receipt", "arrival_absence"},
            "membership_unverified": relation | {"cutoff_receipt", "arrival_absence"},
            "time_conflict": relation, "commitment_time_unverified": relation,
            "allocation_pending": portion, "allocation_disputed": portion,
            "awaiting_recovery": portion, "capacity_unproven": relation,
            "portion_basis_unverified": relation, "coverage_unproven": {"line_total", "arrival_absence"},
            "due_basis_missing": {"overdue_quantity", "overdue_days"},
            "reliable_post_cutoff": set(), "history_limited": {"historical_traceability", "formal_eligibility"},
        }
        for kind, mask in expected.items():
            with self.subTest(kind=kind):
                g, d, c = three()
                g.seed("matrix", kind, d)
                result = r.map_restrictions(g.finish())
                self.assertEqual(set(blocked(result, d)), mask)
                self.assertEqual(blocked(result, pnode("C")), {})
                self.assertFalse(result.calculation_performed)

    def test_p201_local_time_conflict_preserves_independent_c_and_original_target(self):
        g, d, c = three(candidates=(pnode("A"),))
        g.seed("time-D", "time_conflict", d)
        result = r.map_restrictions(g.finish())
        self.assertEqual(rows(result)[pnode("B")].state, "restricted")
        self.assertIn("portion_balance", blocked(result, pnode("B")))
        self.assertEqual(rows(result)[pnode("C")].state, "unrestricted_by_supplied_reasons")
        self.assertIn(pnode("B"), result.protected_targets)
        self.assertIn(c, rows(result))
        self.assertEqual(len(result.fragment_validation.canonical_fact_refs), 2)
        self.assertFalse(result.calculation_performed)
        self.assertFalse(result.formal_eligible)

    def test_missing_independent_coverage_is_not_silently_accepted(self):
        g, d, c = three()
        g.seed("time-D", "time_conflict", d)
        result = r.map_restrictions(g.finish(omit_closure=(pnode("A"), pnode("C"))))
        self.assertEqual(rows(result)[pnode("A")].state, "scope_unproven")
        self.assertEqual(rows(result)[pnode("C")].state, "scope_unproven")
        self.assertIn(c, rows(result))
        self.assertIn(c.identity[-1], {k.fragment_id for k in result.fragment_validation.structurally_valid_keys})

    def test_p201_due_calendar_restricts_only_overdue_metrics(self):
        g, d, c = three()
        calendar = r.Node("basis", ("calendar", "missing", "v1", "due"))
        g.edge(calendar, pnode("C"))
        g.seed("calendar-C", "due_basis_missing", calendar)
        result = r.map_restrictions(g.finish())
        self.assertEqual(set(blocked(result, pnode("C"))), {"overdue_quantity", "overdue_days"})
        self.assertNotIn("portion_balance", blocked(result, pnode("C")))
        self.assertNotIn("age_days", blocked(result, pnode("C")))

    def test_p201_two_reasons_do_not_create_extra_fragments_or_facts(self):
        g, d, c = three()
        g.seed("time-D", "time_conflict", d)
        g.seed("capacity-D", "capacity_unproven", d)
        result = r.map_restrictions(g.finish())
        self.assertEqual(set(blocked(result, pnode("B"))["portion_balance"]), {"time-D", "capacity-D"})
        self.assertEqual(len(result.fragment_validation.canonical_fact_refs), 2)
        self.assertEqual(len(result.fragment_validation.structurally_valid_keys), 2)
        self.assertEqual(blocked(result, pnode("C")), {})

    def test_p201_pending_disputed_and_awaiting_recovery_never_auto_restore(self):
        for kind in ("allocation_pending", "allocation_disputed", "awaiting_recovery"):
            with self.subTest(kind=kind):
                g, d, c = three()
                g.seed("state-D", kind, d)
                request = g.finish()
                result = r.map_restrictions(request)
                self.assertEqual(set(blocked(result, pnode("B"))),
                                 {"portion_balance", "age_days", "overdue_quantity", "overdue_days"})
                self.assertNotIn("calculation_inclusion", blocked(result, d))
                self.assertFalse(result.formal_eligible)
                self.assertIs(result.input_manifest, request)

    def test_tr08_50_plus_30_keeps_one_parent_and_reliable_fifty(self):
        for may_affect_a in (False, True):
            with self.subTest(may_affect_a=may_affect_a):
                m = fixture(segments=(("S50", "0", "50", "50", "G50"), ("S30", "50", "80", "30", "G30")))
                g = GraphFixture(m, ("A", "B"), {"S50": "A", "S30": "B"})
                a, b = (r.fragment_node(x.key) for x in m.definitions)
                g.edge(a, pnode("A"))
                g.scope(b, (pnode("B"),), (pnode("B"),), (pnode("A"),) if may_affect_a else ())
                g.seed("conflict-30", "time_conflict", b)
                result = r.map_restrictions(g.finish())
                self.assertEqual(len(result.fragment_validation.canonical_fact_refs), 1)
                self.assertIn(m.definitions[0].key, result.fragment_validation.structurally_valid_keys)
                self.assertEqual(rows(result)[pnode("A")].state,
                                 "restricted" if may_affect_a else "unrestricted_by_supplied_reasons")
                self.assertIn("portion_balance", blocked(result, pnode("B")))

    def test_no_partition_basis_cannot_turn_declared_fifty_into_reliable_segment(self):
        m = fixture(segments=(("S50", "0", "50", "50", "G50"), ("S30", "50", "80", "30", "G30")))
        m = replace(m, partition_bases=())
        g = GraphFixture(m, ("A", "B"), {"S50": "A", "S30": "B"})
        for definition, name in zip(m.definitions, ("A", "B")):
            subject = r.fragment_node(definition.key)
            g.scope(subject, (pnode(name),), (pnode(name),))
        result = r.map_restrictions(g.finish())
        self.assertEqual(result.fragment_validation.structurally_valid_keys, ())
        self.assertEqual(len(result.fragment_validation.canonical_fact_refs), 1)
        self.assertTrue(all("portion_balance" in blocked(result, pnode(n)) for n in ("A", "B")))

    def test_tr08_overlapping_domains_merge_reasons_not_quantities(self):
        g = GraphFixture(combine(fixture("D1", "40"), fixture("D2", "30"), fixture("X", "20")),
                         ("A", "B", "C", "X"), {"D1": "B", "D2": "C", "X": "X"})
        s1, s2, sx = (r.fragment_node(x.key) for x in g.fragments.definitions)
        g.scope(s1, (pnode("A"), pnode("B")), (pnode("B"),))
        g.scope(s2, (pnode("B"), pnode("C")), (pnode("C"),))
        g.edge(sx, pnode("X"))
        g.seed("D1-time", "time_conflict", s1)
        g.seed("D2-pending", "allocation_pending", s2)
        result = r.map_restrictions(g.finish())
        self.assertEqual(set(blocked(result, pnode("B"))["portion_balance"]), {"D1-time", "D2-pending"})
        self.assertEqual(rows(result)[pnode("X")].state, "unrestricted_by_supplied_reasons")
        self.assertEqual(len(result.fragment_validation.canonical_fact_refs), 3)

    def test_tr08_dependency_cycle_terminates_and_does_not_invent_reverse_edges(self):
        g = GraphFixture(combine(fixture("D1", "40"), fixture("D2", "30"), fixture("X", "20")),
                         ("A", "B", "X"), {"D1": "A", "D2": "B", "X": "X"})
        s1, s2, sx = (r.fragment_node(x.key) for x in g.fragments.definitions)
        g.scope(s1, (pnode("A"),), (pnode("A"),))
        g.scope(s2, (pnode("B"),), (pnode("B"),))
        g.edge(s1, s2)
        g.edge(s2, s1)
        g.edge(sx, pnode("X"))
        g.seed("cycle", "allocation_disputed", s1)
        request = g.finish()
        result = r.map_restrictions(request)
        self.assertLessEqual(result.propagation_steps, len(request.nodes) * len(ALL))
        self.assertIn("portion_balance", blocked(result, pnode("A")))
        self.assertIn("portion_balance", blocked(result, pnode("B")))
        self.assertEqual(blocked(result, pnode("X")), {})

    def test_tr11_missing_scope_proof_cannot_localize_using_candidate_names(self):
        g, d, c = three()
        g.seed("time-D", "time_conflict", d)
        request = g.finish()
        scope_ref = request.scopes[0].proof_ref
        request = replace(request, proofs=tuple(p for p in request.proofs if p.ref != scope_ref))
        result = r.map_restrictions(request)
        self.assertIn("impact_scope_unproven", icodes(result))
        self.assertEqual(rows(result)[pnode("B")].state, "scope_unproven")
        self.assertEqual(rows(result)[pnode("C")].state, "scope_unproven")
        self.assertIn(pnode("B"), result.protected_targets)
        self.assertIn(c, rows(result))

    def test_independent_closure_can_retain_c_while_other_scope_remains_unproven(self):
        g, d, c = three()
        g.seed("time-D", "time_conflict", d)
        request = g.finish(exclude={pnode("C"): (d,)})
        scope_ref = request.scopes[0].proof_ref
        request = replace(request, proofs=tuple(p for p in request.proofs if p.ref != scope_ref))
        result = r.map_restrictions(request)
        self.assertEqual(rows(result)[pnode("C")].state, "unrestricted_by_supplied_reasons")
        self.assertEqual(rows(result)[pnode("B")].state, "scope_unproven")
        self.assertIn(c, rows(result))
        self.assertFalse(result.formal_eligible)

    def test_original_target_omission_is_not_cured_by_empty_protection_proof(self):
        g, d, c = three(scoped=False)
        g.scope(d, (pnode("A"),), ())
        g.seed("disputed-D", "allocation_disputed", d)
        result = r.map_restrictions(g.finish(exclude={pnode("B"): (d,), pnode("C"): (d,)}))
        self.assertIn("protection_basis_unproven", icodes(result))
        self.assertIn(pnode("B"), result.protected_targets)
        self.assertEqual(rows(result)[pnode("B")].state, "scope_unproven")

    def test_propagated_date_restriction_still_requires_original_scope(self):
        g, d, c = three(scoped=False)
        g.seed("date-D", "actual_date_unverified", r.fact_node(g.fragments.facts[0].ref))
        result = r.map_restrictions(g.finish(exclude={pnode("B"): (d,), pnode("C"): (d,)}))
        self.assertIn("propagated_restriction_scope_missing", icodes(result))
        self.assertIn(pnode("B"), result.protected_targets)
        self.assertEqual(rows(result)[pnode("B")].state, "scope_unproven")

    def test_date_and_membership_unknown_preserve_physical_fact_reference(self):
        for kind in ("actual_date_unverified", "membership_unverified", "quantity_unverified"):
            with self.subTest(kind=kind):
                g, d, c = three()
                subject = r.fact_node(g.fragments.facts[0].ref)
                g.seed("unknown-D", kind, subject)
                result = r.map_restrictions(g.finish())
                self.assertIn("cutoff_receipt", blocked(result, subject))
                self.assertEqual("physical_receipt" in blocked(result, subject), kind == "quantity_unverified")
                self.assertEqual(len(result.fragment_validation.canonical_fact_refs), 2)
                self.assertEqual(rows(result)[pnode("C")].state, "unrestricted_by_supplied_reasons")

    def test_reliable_post_cutoff_label_cannot_clear_other_reasons(self):
        g, d, c = three()
        g.seed("date-unknown", "actual_date_unverified", d)
        g.seed("future-claim", "reliable_post_cutoff", d)
        result = r.map_restrictions(g.finish())
        self.assertEqual(blocked(result, pnode("B"))["portion_balance"], ("date-unknown",))
        self.assertIn("cutoff_receipt", blocked(result, d))

    def test_coverage_restricts_absence_claim_not_positive_arrival_or_all_metrics(self):
        g, d, c = three()
        basis = r.Node("basis", ("coverage", "missing", "v1", "line"))
        g.nodes.add(basis)
        g.seed("coverage", "coverage_unproven", basis)
        result = r.map_restrictions(g.finish())
        self.assertEqual(set(blocked(result, basis)), {"line_total", "arrival_absence"})
        self.assertEqual(blocked(result, pnode("C")), {})
        self.assertNotIn("arrival_presence", blocked(result, basis))

    def test_capacity_mask_keeps_original_targets_without_running_or_changing_solver(self):
        g, d, c = three(candidates=(pnode("A"),))
        g.seed("RV01-capacity", "capacity_unproven", d)
        request = g.finish()
        before = deepcopy(request)
        result = r.map_restrictions(request)
        self.assertIn("line_total", blocked(result, pnode("A")))
        self.assertIn("line_total", blocked(result, pnode("B")))
        self.assertIn(pnode("B"), result.protected_targets)
        self.assertEqual(request, before)
        self.assertFalse(hasattr(result, "capacity_allocation"))

    def test_history_limit_is_not_a_current_balance_restriction(self):
        g, d, c = three()
        g.seed("history", "history_limited", d)
        result = r.map_restrictions(g.finish())
        self.assertEqual(set(blocked(result, pnode("B"))), {"historical_traceability", "formal_eligibility"})
        self.assertNotIn("portion_balance", blocked(result, pnode("B")))

    def test_multiple_identical_reason_references_do_not_duplicate_propagation(self):
        g, d, c = three()
        g.seed("same", "time_conflict", d)
        request = g.finish()
        a = r.map_restrictions(request)
        b = r.map_restrictions(replace(request, seeds=request.seeds * 3))
        self.assertEqual(a.node_restrictions, b.node_restrictions)
        self.assertEqual(a.propagation_steps, b.propagation_steps)

    def test_conflicting_reason_ids_never_select_last(self):
        g, d, c = three()
        g.seed("same", "allocation_pending", d)
        g.seed("same", "time_conflict", d)
        request = g.finish()
        for seeds in (request.seeds, request.seeds[::-1]):
            with self.subTest(first=seeds[0].kind):
                result = r.map_restrictions(replace(request, seeds=seeds))
                self.assertIn("reason_identity_conflict", icodes(result))
                self.assertIn("line_total", blocked(result, d))
                self.assertEqual(rows(result)[d].state, "scope_unproven")
                self.assertEqual(rows(result)[pnode("C")].state, "unrestricted_by_supplied_reasons")

    def test_unknown_reason_cannot_default_to_no_restriction(self):
        g, d, c = three()
        g.seed("unknown", "NOT_A_REASON", d)
        result = r.map_restrictions(g.finish())
        self.assertIn("invalid_or_unknown_restriction_reason", icodes(result))
        self.assertNotEqual(rows(result)[pnode("C")].state, "unrestricted_by_supplied_reasons")

    def test_tr11_wrong_snapshot_proof_does_not_grant_independence(self):
        for name in ("manifest_ref", "observation_ref"):
            with self.subTest(field=name):
                g, d, c = three()
                g.seed("conflict", "time_conflict", d)
                request = g.finish()
                request = replace(request, proofs=tuple(replace(p, **{name: "OLD"}) for p in request.proofs))
                result = r.map_restrictions(request)
                self.assertIn("impact_scope_unproven", icodes(result))
                self.assertEqual(rows(result)[pnode("C")].state, "scope_unproven")

    def test_conflicting_proof_definitions_do_not_select_first_or_latest(self):
        g, d, c = three()
        g.seed("conflict", "time_conflict", d)
        request = g.finish()
        scope_ref = request.scopes[0].proof_ref
        proof = next(p for p in request.proofs if p.ref == scope_ref)
        extra = replace(proof, evidence_ref=("other", "v2"))
        for proofs in (request.proofs + (extra,), (extra,) + request.proofs):
            with self.subTest(extra_first=proofs[0] is extra):
                result = r.map_restrictions(replace(request, proofs=proofs))
                self.assertIn("duplicate_or_conflicting_binding_proof", icodes(result))
                self.assertEqual(rows(result)[pnode("B")].state, "scope_unproven")

    def test_reverse_portion_dependency_is_not_invented_or_accepted(self):
        g, d, c = three()
        g.edge(pnode("B"), c)
        g.seed("conflict", "time_conflict", d)
        result = r.map_restrictions(g.finish())
        self.assertIn("dependency_binding_unproven", icodes(result))
        self.assertFalse(any(edge.source.kind == "portion" for edge in result.used_dependencies))

    def test_bad_graph_identity_is_not_hashed_or_compared(self):
        g, d, c = three()
        probe = NoCompare()
        request = g.finish()
        result = r.map_restrictions(replace(request, nodes=request.nodes + (r.Node("portion", ("PO", "I", "件", probe, "1")),)))
        self.assertEqual(result.status, "request_rejected")
        self.assertEqual(probe.calls, 0)

    def test_fragment_identity_conflict_stays_local_and_retains_c(self):
        g, d, c = three()
        m = g.fragments
        first = m.definitions[0]
        altered = replace(first, end="40", quantity="40")
        g.fragments = replace(m, definitions=m.definitions + (altered,))
        result = r.map_restrictions(g.finish())
        self.assertIn("fragment_identity_conflict", {i.code for i in result.fragment_validation.issues})
        self.assertEqual(rows(result)[pnode("C")].state, "unrestricted_by_supplied_reasons")
        self.assertIn(m.definitions[1].key, result.fragment_validation.structurally_valid_keys)

    def test_input_permutation_does_not_change_masks_and_never_mutates_input(self):
        g, d, c = three(candidates=(pnode("A"),))
        g.seed("time", "time_conflict", d)
        g.seed("pending", "allocation_pending", d)
        request = g.finish()
        before = deepcopy(request)
        reverse = replace(request, nodes=request.nodes[::-1], proofs=request.proofs[::-1], dependencies=request.dependencies[::-1],
                          seeds=request.seeds[::-1], closures=request.closures[::-1], protections=request.protections[::-1])
        a, b = r.map_restrictions(request), r.map_restrictions(reverse)
        self.assertEqual(a.node_restrictions, b.node_restrictions)
        self.assertEqual(a.protected_targets, b.protected_targets)
        self.assertEqual(a.propagation_steps, b.propagation_steps)
        self.assertEqual(request, before)

    def test_no_numeric_audit_result_or_formal_qualification_is_returned(self):
        g, d, c = three()
        result = r.map_restrictions(g.finish())
        for name in ("remaining_quantity", "age_days", "overdue_quantity", "verified_received_quantity", "qualified_delivery_quantity"):
            self.assertFalse(hasattr(result, name))
        self.assertFalse(result.calculation_performed)
        self.assertFalse(result.formal_eligible)


class RequiredParentDependencyRegressionTests(unittest.TestCase):
    DATE_METRICS = {"cutoff_receipt", "arrival_absence", "calculation_inclusion", "allocation_use",
                    "portion_balance", "age_days", "overdue_quantity", "overdue_days", "line_total"}

    def request(self, kind="actual_date_unverified"):
        g, d, c = three()
        parent = r.fact_node(g.fragments.facts[0].ref)
        g.seed("parent-D", kind, parent)
        return g.finish(), parent, d, c

    def assert_date_protection(self, result, d, c):
        self.assertEqual(set(blocked(result, d)), self.DATE_METRICS)
        self.assertEqual(set(blocked(result, pnode("B"))), self.DATE_METRICS)
        self.assertNotEqual(rows(result)[pnode("B")].state, "unrestricted_by_supplied_reasons")
        self.assertIn(pnode("B"), result.protected_targets)
        self.assertEqual(blocked(result, c), {})
        self.assertEqual(rows(result)[pnode("C")].state, "unrestricted_by_supplied_reasons")
        self.assertEqual(blocked(result, pnode("C")), {})
        self.assertFalse(result.calculation_performed)
        self.assertFalse(result.formal_eligible)

    def test_original_missing_parent_edge_counterexample_keeps_old_closures(self):
        request, parent, d, c = self.request()
        request = replace(request, dependencies=tuple(e for e in request.dependencies if (e.source, e.target) != (parent, d)))
        before = deepcopy(request)
        result = r.map_restrictions(request)
        self.assert_date_protection(result, d, c)
        self.assertEqual(set(blocked(result, parent)), self.DATE_METRICS)
        self.assertEqual(request, before)
        self.assertEqual(len(result.fragment_validation.canonical_fact_refs), 2)
        links = [e for e in result.required_parent_dependencies if e.source == parent and e.target == d]
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].origin, "structural_parent_binding")
        self.assertEqual(links[0].manifest_ref, request.fragments.context.manifest_ref)
        self.assertEqual(links[0].observation_ref, request.fragments.context.observation_ref)

    def test_empty_partial_and_invalid_masks_cannot_mute_required_metrics(self):
        for metrics in ((), ("physical_receipt",), ("age_days",), None):
            for matching_proof in (False, True):
                with self.subTest(metrics=metrics, matching_proof=matching_proof):
                    request, parent, d, c = self.request()
                    old = next(e for e in request.dependencies if (e.source, e.target) == (parent, d))
                    proofs = request.proofs
                    if matching_proof and metrics is not None:
                        proofs = tuple(replace(p, binding=(nt(d), tuple(sorted(metrics)))) if p.ref == old.proof_ref else p for p in proofs)
                    changed = replace(old, metrics=metrics)
                    request = replace(request, proofs=proofs,
                                      dependencies=tuple(changed if e is old else e for e in request.dependencies))
                    result = r.map_restrictions(request)
                    self.assert_date_protection(result, d, c)
                    if metrics is None or not matching_proof:
                        self.assertTrue(icodes(result) & {"invalid_dependency", "dependency_binding_unproven"})
                        problems = [i for i in result.issues if i.code in ("invalid_dependency", "dependency_binding_unproven")]
                        self.assertTrue(problems)
                        self.assertTrue(all(i.subjects == (d,) and i.localization_status == "synthetic_bounded" for i in problems))

    def test_complete_parent_edge_preserves_existing_date_mask(self):
        request, parent, d, c = self.request()
        result = r.map_restrictions(request)
        self.assert_date_protection(result, d, c)
        self.assertEqual(rows(result)[pnode("B")].state, "restricted")
        self.assertNotIn("physical_receipt", blocked(result, d))

    def test_missing_edge_input_permutations_have_identical_results(self):
        request, parent, d, c = self.request()
        request = replace(request, dependencies=tuple(e for e in request.dependencies if (e.source, e.target) != (parent, d)))
        result = r.map_restrictions(request)
        permuted = replace(request, nodes=request.nodes[::-1], proofs=request.proofs[::-1],
                           dependencies=request.dependencies[::-1], scopes=request.scopes[::-1],
                           closures=request.closures[::-1], protections=request.protections[::-1], seeds=request.seeds[::-1])
        other = r.map_restrictions(permuted)
        self.assert_date_protection(other, d, c)
        self.assertEqual(result.node_restrictions, other.node_restrictions)
        self.assertEqual(result.required_parent_dependencies, other.required_parent_dependencies)
        self.assertEqual(result.propagation_steps, other.propagation_steps)

    def test_required_parent_binding_also_covers_control_group(self):
        g, d, c = three()
        parent = r.fact_node(g.fragments.facts[0].ref)
        group = r.Node("group", parent.identity + ("pv1", "G"))
        g.scope(group, (pnode("B"),), (pnode("B"),))
        g.edge(group, d)
        g.seed("parent-D", "actual_date_unverified", parent)
        request = g.finish()
        request = replace(request, dependencies=tuple(e for e in request.dependencies if (e.source, e.target) != (parent, d)))
        result = r.map_restrictions(request)
        self.assert_date_protection(result, d, c)
        self.assertEqual(set(blocked(result, group)), self.DATE_METRICS)
        self.assertTrue(any(e.source == parent and e.target == group for e in result.required_parent_dependencies))

    def test_parent_history_only_does_not_invent_quantity_restrictions(self):
        request, parent, d, c = self.request("history_limited")
        request = replace(request, dependencies=tuple(e for e in request.dependencies if (e.source, e.target) != (parent, d)))
        result = r.map_restrictions(request)
        self.assertEqual(set(blocked(result, parent)), {"historical_traceability", "formal_eligibility"})
        self.assertEqual(blocked(result, d), {})
        self.assertEqual(blocked(result, pnode("B")), {})
        self.assertEqual(rows(result)[pnode("C")].state, "unrestricted_by_supplied_reasons")

    def test_missing_both_parent_edges_does_not_couple_independent_c(self):
        request, parent, d, c = self.request()
        request = replace(request, dependencies=tuple(e for e in request.dependencies if e.source.kind != "fact"))
        result = r.map_restrictions(request)
        self.assert_date_protection(result, d, c)
        self.assertEqual(len(result.required_parent_dependencies), 2)
        for link in result.required_parent_dependencies:
            self.assertEqual(link.source.identity, link.target.identity[:2])
        self.assertEqual(len(result.fragment_validation.canonical_fact_refs), 2)

    def test_multiple_parent_reasons_are_unioned_without_duplicate_fact(self):
        request, parent, d, c = self.request()
        request = replace(request, dependencies=tuple(e for e in request.dependencies if (e.source, e.target) != (parent, d)),
                          seeds=request.seeds + (r.RestrictionSeed("member-D", "membership_unverified", parent),))
        result = r.map_restrictions(request)
        self.assert_date_protection(result, d, c)
        for reasons in blocked(result, pnode("B")).values():
            self.assertEqual(reasons, ("member-D", "parent-D"))
        self.assertEqual(len(result.fragment_validation.canonical_fact_refs), 2)

    def test_partition_composition_issue_propagates_locally_and_preserves_c(self):
        first = fixture(segments=(("A", "0", "50", "50", "G1"),), partition="pv1")
        second = fixture(segments=(("B", "50", "80", "30", "G2"),), partition="pv2")
        mixed = replace(combine(first, second), facts=first.facts)
        g = GraphFixture(combine(mixed, fixture("C", "20")), targets={"D": "B", "C": "C"})
        d1, d2, c = (r.fragment_node(row.key) for row in g.fragments.definitions)
        for d in (d1, d2):
            g.scope(d, (pnode("B"),), (pnode("B"),))
        g.edge(c, pnode("C"))
        request = g.finish()
        result = r.map_restrictions(request)
        self.assertIn("partition_composition_unproven", {i.code for i in result.fragment_validation.issues})
        self.assertEqual(result.fragment_validation.structurally_valid_keys, (g.fragments.definitions[-1].key,))
        self.assertIn("portion_balance", blocked(result, pnode("B")))
        self.assertEqual(rows(result)[pnode("C")].state, "unrestricted_by_supplied_reasons")
        self.assertEqual(blocked(result, pnode("C")), {})
        self.assertEqual(len(result.fragment_validation.canonical_fact_refs), 2)
        self.assertIs(result.input_manifest, request)
        self.assertFalse(result.calculation_performed)


class MissingGraphNodeRegressionTests(unittest.TestCase):
    def omitted(self, kind="actual_date_unverified", independent=True, retain_scope=False):
        g, d, c = three(scoped=retain_scope)
        parent = r.fact_node(g.fragments.facts[0].ref)
        g.nodes.remove(d)
        g.dependencies = [edge for edge in g.dependencies if d not in (edge.source, edge.target)]
        if kind is not None:
            g.seed("omitted-D", kind, parent)
        request = g.finish(exclude={pnode("C"): (parent,)} if independent else {})
        # Verify the input, not just the output: finish() must not repair it.
        self.assertNotIn(d, request.nodes)
        self.assertIn(parent, request.nodes)
        self.assertIn(pnode("B"), request.nodes)
        self.assertTrue(any(row.key == g.fragments.definitions[0].key for row in request.fragments.definitions))
        self.assertTrue(any(row.fragment == g.fragments.definitions[0].key and row.target_ref == pnode("B").identity
                            for row in request.fragments.active_relations))
        self.assertFalse(any(d in (e.source, e.target) for e in request.dependencies))
        return request, parent, d, c

    def assert_protected(self, result, request, parent, d, c, kind):
        self.assertNotEqual(result.status, "request_rejected")
        self.assertEqual(rows(result)[pnode("B")].state, "scope_unproven")
        self.assertIn(pnode("B"), result.protected_targets)
        self.assertIn("required_graph_node_missing", icodes(result))
        self.assertEqual(rows(result)[pnode("C")].state, "unrestricted_by_supplied_reasons")
        self.assertEqual(blocked(result, pnode("C")), {})
        self.assertIn(c, rows(result))
        self.assertNotIn(d, rows(result))
        if kind is not None:
            self.assertEqual(set(blocked(result, parent)), set(r.REASON_METRICS[kind]))
        self.assertEqual(len(result.fragment_validation.canonical_fact_refs), 2)
        self.assertEqual(len(result.fragment_validation.structurally_valid_keys), 2)
        self.assertIs(result.input_manifest, request)
        self.assertFalse(result.calculation_performed)
        self.assertFalse(result.formal_eligible)

    def test_missing_fragment_cannot_erase_parent_date_limitation(self):
        request, parent, d, c = self.omitted()
        self.assert_protected(r.map_restrictions(request), request, parent, d, c, "actual_date_unverified")

    def test_missing_fragment_cannot_erase_parent_membership_limitation(self):
        request, parent, d, c = self.omitted("membership_unverified")
        self.assert_protected(r.map_restrictions(request), request, parent, d, c, "membership_unverified")

    def test_missing_fragment_cannot_erase_parent_quantity_limitation(self):
        request, parent, d, c = self.omitted("quantity_unverified")
        self.assert_protected(r.map_restrictions(request), request, parent, d, c, "quantity_unverified")

    def test_partial_fragment_omission_keeps_present_segment_and_independent_c(self):
        m = fixture(segments=(("S50", "0", "50", "50", "G50"), ("S30", "50", "80", "30", "G30")))
        g = GraphFixture(combine(m, fixture("C", "20")), targets={"S50": "A", "S30": "B", "C": "C"})
        a, absent, c = (r.fragment_node(row.key) for row in g.fragments.definitions)
        parent = r.fact_node(m.facts[0].ref)
        g.nodes.remove(absent)
        g.edge(parent, a)
        g.edge(a, pnode("A"))
        g.edge(r.fact_node(g.fragments.facts[1].ref), c)
        g.edge(c, pnode("C"))
        g.scope(a, (pnode("A"),), (pnode("A"),))
        g.seed("date-D", "actual_date_unverified", parent)
        request = g.finish(exclude={pnode("C"): (parent,)})
        self.assertNotIn(absent, request.nodes)
        self.assertEqual(len(request.fragments.definitions), 3)
        result = r.map_restrictions(request)
        self.assertEqual(rows(result)[pnode("B")].state, "scope_unproven")
        self.assertIn(pnode("B"), result.protected_targets)
        self.assertEqual(set(blocked(result, a)), set(r.REASON_METRICS["actual_date_unverified"]))
        self.assertIn("portion_balance", blocked(result, pnode("A")))
        self.assertIn(a, rows(result))
        self.assertNotIn(absent, rows(result))
        self.assertEqual(rows(result)[pnode("C")].state, "unrestricted_by_supplied_reasons")
        self.assertEqual(len(result.fragment_validation.structurally_valid_keys), 3)
        self.assertEqual(len(result.fragment_validation.canonical_fact_refs), 2)

    def test_input_permutation_does_not_select_or_repair_missing_node(self):
        request, parent, d, c = self.omitted()
        expected = r.map_restrictions(request)
        for changes in ({"nodes": request.nodes[::-1]}, {"proofs": request.proofs[::-1]},
                        {"dependencies": request.dependencies[::-1], "closures": request.closures[::-1]},
                        {"fragments": replace(request.fragments, facts=request.fragments.facts[::-1],
                                               definitions=request.fragments.definitions[::-1],
                                               active_relations=request.fragments.active_relations[::-1])}):
            with self.subTest(field=next(iter(changes))):
                candidate = replace(request, **changes)
                result = r.map_restrictions(candidate)
                self.assert_protected(result, candidate, parent, d, c, "actual_date_unverified")
                self.assertEqual(result.node_restrictions, expected.node_restrictions)
                self.assertEqual(result.protected_targets, expected.protected_targets)
                self.assertEqual(result.propagation_steps, expected.propagation_steps)

    def test_missing_full_key_and_relation_basis_are_retained_without_input_mutation(self):
        request, parent, d, c = self.omitted()
        before = deepcopy(request)
        result = r.map_restrictions(request)
        self.assert_protected(result, request, parent, d, c, "actual_date_unverified")
        problems = [i for i in result.issues if i.code == "required_graph_node_missing" and d in i.subjects]
        self.assertTrue(problems)
        self.assertTrue(any(("approval", "v1") in i.basis_refs for i in problems))
        self.assertEqual(d.identity, ("D", "fv1", "pv1", "S"))
        self.assertEqual(request, before)
        self.assertEqual(request.seeds[0].basis_refs, (("reason-evidence", "v1"),))
        self.assertNotIn(d, request.nodes)

    def test_incomplete_closure_alone_cannot_grant_c_independence(self):
        request, parent, d, c = self.omitted(independent=False)
        result = r.map_restrictions(request)
        self.assertEqual(rows(result)[pnode("B")].state, "scope_unproven")
        self.assertEqual(rows(result)[pnode("C")].state, "scope_unproven")
        self.assertIn(c, rows(result))
        self.assertNotEqual(result.status, "request_rejected")
        self.assertIn(pnode("B"), result.protected_targets)

    def test_missing_target_is_preserved_as_protected_reference_not_fabricated_node(self):
        request, parent, d, c = self.omitted()
        request = replace(request, nodes=tuple(n for n in request.nodes if n != pnode("B")),
                          closures=tuple(cl for cl in request.closures if cl.subject != pnode("B")))
        # Rebind C's independent closure to this actually supplied universe.
        cclosure = next(cl for cl in request.closures if cl.subject == pnode("C"))
        request = replace(request, proofs=tuple(replace(p, binding=(tuple(nt(n) for n in sorted(request.nodes)),
                                p.binding[1], p.binding[2])) if p.ref == cclosure.proof_ref else p for p in request.proofs))
        result = r.map_restrictions(request)
        self.assertIn(pnode("B"), result.protected_targets)
        self.assertNotIn(pnode("B"), rows(result))
        self.assertEqual(rows(result)[pnode("C")].state, "unrestricted_by_supplied_reasons")
        self.assertTrue(any(i.code == "required_graph_node_missing" and pnode("B") in i.subjects for i in result.issues))

    def test_omission_is_diagnosed_even_without_a_restriction_seed(self):
        request, parent, d, c = self.omitted(kind=None)
        result = r.map_restrictions(request)
        self.assert_protected(result, request, parent, d, c, None)
        self.assertEqual(request.seeds, ())
        self.assertEqual(blocked(result, parent), {})

    def test_history_only_reference_does_not_require_current_graph_node(self):
        g, d, c = three()
        historical = replace(g.fragments.active_relations[0], version="old",
                             fragment=replace(g.fragments.definitions[0].key, partition_version="pv-history"))
        g.fragments = replace(g.fragments, history_relations=(historical,))
        request = g.finish()
        result = r.map_restrictions(request)
        self.assertNotIn("required_graph_node_missing", icodes(result))
        self.assertEqual(rows(result)[pnode("C")].state, "unrestricted_by_supplied_reasons")
        self.assertEqual(result.input_manifest.fragments.history_relations, (historical,))

    def test_seed_on_known_missing_fragment_remains_local_to_its_parent(self):
        request, parent, d, c = self.omitted(kind=None)
        request = replace(request, seeds=(r.RestrictionSeed("missing-D", "actual_date_unverified", d,
                                                           (("reason-evidence", "v1"),)),))
        result = r.map_restrictions(request)
        self.assert_protected(result, request, parent, d, c, None)
        self.assertIn("restriction_subject_missing", icodes(result))
        self.assertEqual(request.seeds[0].subject, d)

    def test_retained_scope_proof_does_not_repair_missing_graph_node(self):
        request, parent, d, c = self.omitted(retain_scope=True)
        self.assertTrue(any(scope.subject == d for scope in request.scopes))
        result = r.map_restrictions(request)
        self.assert_protected(result, request, parent, d, c, "actual_date_unverified")
        self.assertIn("impact_scope_unproven", icodes(result))

    def test_target_closure_cannot_exclude_known_missing_allocation(self):
        request, parent, d, c = self.omitted()
        bclosure = next(cl for cl in request.closures if cl.subject == pnode("B"))
        request = replace(request,
                          closures=tuple(replace(cl, excluded_subjects=(parent,)) if cl is bclosure else cl for cl in request.closures),
                          proofs=tuple(replace(p, binding=(p.binding[0], p.binding[1], (nt(parent),)))
                                       if p.ref == bclosure.proof_ref else p for p in request.proofs))
        result = r.map_restrictions(request)
        self.assert_protected(result, request, parent, d, c, "actual_date_unverified")


if __name__ == "__main__":
    unittest.main(verbosity=2)
