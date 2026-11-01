"""WP-2: reason/metric masks over a fixed SYNTHETIC proof-bound graph.

No supported numeric results, real-source approval, date inference or RV-01 calls.
An absence of restrictions is NOT proof of calculation eligibility.
"""
from collections import deque
from dataclasses import dataclass

from .audit_delivery_fragments import (
    EffectiveRelation, FactRef, Fragment, FragmentKey, FragmentValidation, ParentFact, fact_ref, fragment_key,
    strings, text, validate_fragment_manifest,
)


PORTION_METRICS = frozenset(("portion_balance", "age_days", "overdue_quantity", "overdue_days"))
METRICS = PORTION_METRICS | frozenset((
    "physical_receipt", "cutoff_receipt", "calculation_inclusion", "allocation_use",
    "line_total", "arrival_absence", "historical_traceability", "formal_eligibility",
))
_RELATION_LIMIT = PORTION_METRICS | {"calculation_inclusion", "allocation_use", "line_total"}
_SCOPE_SENSITIVE = METRICS - {"overdue_quantity", "overdue_days", "historical_traceability", "formal_eligibility"}
# v0.3 section 4. These masks restrict; they never classify any quantity as W/Ep.
REASON_METRICS = {
    "invalid_record": frozenset(_RELATION_LIMIT),
    "quantity_unverified": METRICS - {"historical_traceability", "formal_eligibility"},
    "actual_date_unverified": frozenset(_RELATION_LIMIT | {"cutoff_receipt", "arrival_absence"}),
    "membership_unverified": frozenset(_RELATION_LIMIT | {"cutoff_receipt", "arrival_absence"}),
    "time_conflict": frozenset(_RELATION_LIMIT),
    "commitment_time_unverified": frozenset(_RELATION_LIMIT),
    "allocation_pending": PORTION_METRICS,
    "allocation_disputed": PORTION_METRICS,
    "awaiting_recovery": PORTION_METRICS,
    "capacity_unproven": frozenset(_RELATION_LIMIT),
    "portion_basis_unverified": frozenset(_RELATION_LIMIT),
    "coverage_unproven": frozenset(("line_total", "arrival_absence")),
    "due_basis_missing": frozenset(("overdue_quantity", "overdue_days")),
    "reliable_post_cutoff": frozenset(),
    "history_limited": frozenset(("historical_traceability", "formal_eligibility")),
}
# Field limitations necessarily apply to every structural child of that fact.
# These negative dependencies cannot grant evidence/relationship eligibility.
_REQUIRED_PARENT_METRICS = REASON_METRICS["quantity_unverified"]


@dataclass(frozen=True, order=True)
class Node:
    kind: str
    identity: tuple


def valid_node(value):
    lengths = {"fact": 2, "fragment": 4, "group": 4, "basis": 4, "portion": 5}
    return (type(value) is Node and type(value.kind) is str and value.kind in lengths
            and strings(value.identity, lengths[value.kind]))


def fact_node(ref):
    if not fact_ref(ref):
        raise ValueError("invalid_fact_node")
    return Node("fact", (ref.source_event_key, ref.version))


def fragment_node(key):
    if not fragment_key(key):
        raise ValueError("invalid_fragment_node")
    return Node("fragment", (key.parent_fact_ref.source_event_key, key.parent_fact_ref.version,
                             key.partition_version, key.fragment_id))


def token(node):
    return (node.kind,) + node.identity


@dataclass(frozen=True)
class BindingProof:
    ref: tuple
    purpose: str
    subject: Node
    # Entire immutable payload, not merely a path, label, flag or digest.
    binding: tuple
    manifest_ref: str
    observation_ref: str
    evidence_ref: tuple


@dataclass(frozen=True)
class Dependency:
    source: Node
    target: Node
    metrics: tuple
    proof_ref: tuple


@dataclass(frozen=True)
class RequiredParentDependency:
    source: Node
    target: Node
    metrics: tuple
    manifest_ref: str
    observation_ref: str
    origin: str = "structural_parent_binding"


@dataclass(frozen=True)
class ImpactScope:
    subject: Node
    candidate_targets: tuple
    original_targets: tuple
    possible_targets: tuple
    proof_ref: tuple


@dataclass(frozen=True)
class Protection:
    subject: Node
    targets: tuple
    proof_ref: tuple


@dataclass(frozen=True)
class Closure:
    subject: Node
    # Explicit independent coverage may exclude otherwise unlocalized subjects.
    excluded_subjects: tuple
    proof_ref: tuple


@dataclass(frozen=True)
class RestrictionSeed:
    reason_id: str
    kind: str
    subject: Node
    basis_refs: tuple = ()


@dataclass(frozen=True)
class RestrictionManifest:
    fragments: object
    nodes: tuple
    proofs: tuple
    dependencies: tuple = ()
    scopes: tuple = ()
    protections: tuple = ()
    closures: tuple = ()
    seeds: tuple = ()


@dataclass(frozen=True)
class RestrictionIssue:
    code: str
    subjects: tuple = ()
    localization_status: str = "unproven"
    basis_refs: tuple = ()


@dataclass(frozen=True)
class NodeRestriction:
    node: Node
    state: str  # restricted / scope_unproven / unrestricted_by_supplied_reasons
    blocked: tuple  # (metric, unique reason IDs)


@dataclass(frozen=True)
class TraceOrigin:
    namespace: str
    seed: RestrictionSeed
    source_issue: object = None


@dataclass(frozen=True)
class RestrictionTrace:
    node: Node
    metric: str
    reason_id: str
    origins: tuple
    causal_edges: tuple


@dataclass(frozen=True)
class ClosureTrace:
    node: Node
    passed: bool
    unresolved_sources: tuple
    incoming_sources: tuple
    declared_closures: tuple
    claimed_targets: tuple
    proof_binding_valid: bool
    exclusions_valid: bool


@dataclass(frozen=True)
class RestrictionResult:
    input_manifest: object
    fragment_validation: FragmentValidation | None
    status: str
    node_restrictions: tuple
    protected_targets: tuple
    used_dependencies: tuple
    issues: tuple
    propagation_steps: int
    calculation_performed: bool = False
    formal_eligible: bool = False
    required_parent_dependencies: tuple = ()
    causal_trace: tuple = ()
    closure_trace: tuple = ()


def _trace_restrictions(nodes, seeds, edges, automatic_origins, manual_keys):
    """Read-only finite provenance union, separate from decision propagation.

    It retains all roots and edges, not one convenient path. Cycles only add
    members of finite sets; decision steps and blocked masks are untouched.
    No reason_id parsing or string-based inference of business origins.
    """
    adjacency = {n: [] for n in nodes}
    for edge in edges:
        adjacency[edge.source].append(edge)
    states, queue, queued = {}, deque(), set()

    def merge(key, roots, links):
        state = states.setdefault(key, (set(), set()))
        changed = not roots <= state[0] or not links <= state[1]
        state[0].update(roots)
        state[1].update(links)
        if changed and key not in queued:
            queue.append(key)
            queued.add(key)

    for seed in seeds:
        identity = (seed.reason_id, seed.subject, seed.kind, seed.basis_refs)
        roots = {TraceOrigin("fragment_validation", seed, problem) for problem in automatic_origins.get(identity, ())}
        if identity in manual_keys:
            roots.add(TraceOrigin("input_seed", seed))
        for metric in REASON_METRICS[seed.kind]:
            merge((seed.subject, metric, seed.reason_id), roots, set())
    while queue:
        key = queue.popleft()
        queued.remove(key)
        node, metric, reason = key
        roots, links = states[key]
        for edge in adjacency[node]:
            if metric in edge.metrics:
                merge((edge.target, metric, reason), set(roots), set(links) | {edge})

    def root_key(origin):
        s, p = origin.seed, origin.source_issue
        return (origin.namespace, token(s.subject), s.kind, s.reason_id, s.basis_refs,
                () if p is None else (p.code, p.record_paths))

    def edge_key(edge):
        return (token(edge.source), token(edge.target), edge.metrics,
                ("proof",) + edge.proof_ref if type(edge) is Dependency else
                ("structural", edge.manifest_ref, edge.observation_ref))

    return tuple(RestrictionTrace(n, m, reason, tuple(sorted(roots, key=root_key)),
                                  tuple(sorted(links, key=edge_key)))
                 for (n, m, reason), (roots, links) in sorted(states.items()))


def _nodes(value, kind=None):
    return (type(value) is tuple and all(valid_node(n) and (kind is None or n.kind == kind) for n in value)
            and len(set(value)) == len(value))


def _binding(value):
    # Recursive built-in checks precede hashing/equality; no custom __eq__/hash.
    return type(value) is tuple and all(type(x) is str or _binding(x) for x in value)


def map_restrictions(request):
    issues, unresolved, protected = [], set(), set()

    def issue(code, subjects=(), refs=(), bounded=False):
        issues.append(RestrictionIssue(code, tuple(subjects),
                                       "synthetic_bounded" if bounded else "unproven", tuple(refs)))

    def rejected(fragment_result=None):
        return RestrictionResult(request, fragment_result, "request_rejected", (), (), (), tuple(issues), 0)

    if type(request) is not RestrictionManifest:
        issue("invalid_restriction_manifest")
        return rejected()
    fragments = validate_fragment_manifest(request.fragments)
    if fragments.status == "request_rejected":
        issue("fragment_request_invalid")
        return rejected(fragments)
    context = request.fragments.context
    if not all(type(getattr(request, key)) is tuple for key in
               ("nodes", "proofs", "dependencies", "scopes", "protections", "closures", "seeds")):
        issue("invalid_graph_collection")
        return rejected(fragments)
    if not _nodes(request.nodes):
        issue("invalid_or_duplicate_graph_node")
        return rejected(fragments)
    nodes = set(request.nodes)
    declared_facts = {row.ref for row in request.fragments.facts
                      if type(row) is ParentFact and fact_ref(row.ref)}
    declared_keys = {row.key for row in request.fragments.definitions
                     if type(row) is Fragment and fragment_key(row.key)}
    parent_rows = {}
    for row in request.fragments.facts:
        if type(row) is ParentFact and fact_ref(row.ref):
            parent_rows.setdefault(row.ref, []).append(row)
    units = {ref: rows[0].unit for ref, rows in parent_rows.items()
             if len(rows) == 1 and text(rows[0].unit)}

    def parent_of(node):
        return FactRef(*node.identity[:2]) if node.kind in ("fact", "fragment", "group") else None

    def unit_of(node):
        return units.get(parent_of(node))
    for node in nodes:
        if ((node.kind == "fact" and FactRef(*node.identity) not in declared_facts)
                or (node.kind == "fragment" and FragmentKey(FactRef(*node.identity[:2]), *node.identity[2:]) not in declared_keys)
                or (node.kind == "group" and FactRef(*node.identity[:2]) not in declared_facts)):
            issue("graph_source_binding_missing", (node,))
            unresolved.add(node)

    proof_groups = {}
    for proof in request.proofs:
        if (type(proof) is not BindingProof or not strings(proof.ref, 2) or not valid_node(proof.subject)
                or not text(proof.purpose) or not _binding(proof.binding) or not text(proof.manifest_ref)
                or not text(proof.observation_ref) or not strings(proof.evidence_ref, 2)):
            issue("invalid_binding_proof")
            unresolved.update(nodes)
            continue
        proof_groups.setdefault(proof.ref, []).append(proof)
    proofs = {}
    for ref, rows in proof_groups.items():
        if len(rows) != 1:
            issue("duplicate_or_conflicting_binding_proof", tuple(sorted({r.subject for r in rows})), (ref,))
            unresolved.update(r.subject for r in rows)
        else:
            proofs[ref] = rows[0]

    def matches(ref, purpose, subject, binding):
        if not strings(ref, 2):
            return False
        proof = proofs.get(ref)
        return (proof is not None and proof.purpose == purpose and proof.subject == subject
                and proof.binding == binding and proof.manifest_ref == context.manifest_ref
                and proof.observation_ref == context.observation_ref)

    edges, incoming = {}, {n: set() for n in nodes}
    # Derive mandatory ownership links from registered, parent-bound identities,
    # not caller-supplied edges or closure assertions. Never create a fact node
    # or an allocation target absent from the manifest.
    required_links = tuple(
        RequiredParentDependency(fact_node(parent_of(child)), child,
                                 tuple(sorted(_REQUIRED_PARENT_METRICS)),
                                 context.manifest_ref, context.observation_ref)
        for child in sorted(nodes)
        if child.kind in ("fragment", "group") and child not in unresolved
        and parent_of(child) in declared_facts and fact_node(parent_of(child)) in nodes
    )
    required_pairs = {(link.source, link.target) for link in required_links}

    def required_pair(edge):
        return (type(edge) is Dependency and valid_node(edge.source) and valid_node(edge.target)
                and (edge.source, edge.target) in required_pairs)

    allowed = {"basis": {"fact", "group", "fragment", "portion"}, "fact": {"group", "fragment"},
               "group": {"group", "fragment", "portion"}, "fragment": {"group", "fragment", "portion"},
               "portion": set()}
    for edge in request.dependencies:
        if (type(edge) is not Dependency or not valid_node(edge.source) or not valid_node(edge.target)
                or not strings(edge.metrics) or len(set(edge.metrics)) != len(edge.metrics)
                or not set(edge.metrics) <= METRICS or not strings(edge.proof_ref, 2)):
            # A malformed optional description of a known ownership link is
            # child-local; it cannot erase the mandatory link or taint C's fact.
            if required_pair(edge):
                issue("invalid_dependency", (edge.target,), bounded=True)
                unresolved.add(edge.target)
            else:
                issue("invalid_dependency")
                unresolved.update(nodes)
            continue
        payload = (token(edge.target), tuple(sorted(edge.metrics)))
        if (edge.source not in nodes or edge.target not in nodes or edge.target.kind not in allowed[edge.source.kind]
                or (edge.source.kind == "fact" and parent_of(edge.source) != parent_of(edge.target))
                or (edge.source.kind in ("fragment", "group") and edge.target.kind == "portion"
                    and unit_of(edge.source) != edge.target.identity[2])
                or not matches(edge.proof_ref, "dependency", edge.source, payload)):
            owned = required_pair(edge)
            subjects = (edge.target,) if owned else (edge.source, edge.target)
            issue("dependency_binding_unproven", subjects, (edge.proof_ref,), bounded=owned)
            unresolved.update(subjects)
            continue
        key = (edge.source, edge.target, tuple(sorted(edge.metrics)), edge.proof_ref)
        edges[key] = Dependency(edge.source, edge.target, tuple(sorted(edge.metrics)), edge.proof_ref)
        incoming[edge.target].add(edge.source)

    mandatory_targets = {}
    for relation in request.fragments.active_relations:
        if type(relation) is EffectiveRelation and fragment_key(relation.fragment):
            subject = fragment_node(relation.fragment)
            if strings(relation.target_ref, 5):
                mandatory_targets.setdefault(subject, set()).add(Node("portion", relation.target_ref))
            else:
                issue("relation_target_scope_unproven", (subject,))
                unresolved.add(subject)
    # Reverse-check graph coverage against the manifest, not the graph's own
    # (possibly incomplete) closure universe. These are negative requirements:
    # do not insert missing nodes, infer allocation or certify a scope.
    requirements = {}

    def require(node, parent, refs=(), targets=()):
        entry = requirements.setdefault(node, {"parents": set(), "refs": set(), "targets": set()})
        entry["parents"].add(parent)
        entry["refs"].update(ref for ref in refs if strings(ref, 2))
        entry["targets"].update(targets)

    for ref in declared_facts:
        parent = fact_node(ref)
        require(parent, parent)
    for row in request.fragments.definitions:
        if type(row) is Fragment and fragment_key(row.key):
            parent = fact_node(row.key.parent_fact_ref)
            require(parent, parent, (row.basis_ref,))
            require(fragment_node(row.key), parent, (row.basis_ref,))
    for row in request.fragments.active_relations:
        if type(row) is EffectiveRelation and fragment_key(row.fragment):
            parent = fact_node(row.fragment.parent_fact_ref)
            subject = fragment_node(row.fragment)
            targets = mandatory_targets.get(subject, set())
            for required in (parent, subject, *sorted(targets)):
                require(required, parent, (row.basis_ref,), targets)

    missing_anchors, claimed_targets = {}, {}
    for missing in sorted(set(requirements) - nodes):
        entry = requirements[missing]
        # An existing parent is the conservative source of the unknown range.
        # Only an explicit independent closure may exclude it for C. An original
        # target is a minimum protection set, never an exclusive impact domain.
        anchors = entry["parents"] & nodes
        if not anchors:
            anchors = {n for n in nodes if n.kind in ("fragment", "group")
                       and fact_node(parent_of(n)) in entry["parents"]}
        missing_anchors[missing] = anchors or nodes
        unresolved.update(missing_anchors[missing])
        protected.update(entry["targets"])
        for source in {missing} | anchors:
            claimed_targets.setdefault(source, set()).update(entry["targets"])
        issue("required_graph_node_missing", tuple(sorted({missing} | anchors | entry["targets"])),
              tuple(sorted(entry["refs"])))

    protections = {}
    for row in request.protections:
        if type(row) is not Protection or not valid_node(row.subject) or not _nodes(row.targets, "portion"):
            issue("invalid_protection_manifest")
            unresolved.update(nodes)
            continue
        required = mandatory_targets.get(row.subject, set())
        protected.update(set(row.targets) | required)
        claimed_targets.setdefault(row.subject, set()).update(set(row.targets) | required)
        payload = tuple(token(n) for n in sorted(row.targets))
        if (row.subject in protections or not required <= set(row.targets)
                or not matches(row.proof_ref, "protection", row.subject, payload)):
            issue("protection_basis_unproven", (row.subject,), (row.proof_ref,))
            unresolved.add(row.subject)
            protections[row.subject] = None
        else:
            protections[row.subject] = row.targets
    scoped, scoped_targets = set(), {}
    scope_counts = {}
    for scope in request.scopes:
        if type(scope) is ImpactScope and valid_node(scope.subject):
            scope_counts[scope.subject] = scope_counts.get(scope.subject, 0) + 1
    for scope in request.scopes:
        if (type(scope) is not ImpactScope or not valid_node(scope.subject)
                or not all(_nodes(x, "portion") for x in
                           (scope.candidate_targets, scope.original_targets, scope.possible_targets))):
            issue("invalid_impact_scope")
            unresolved.update(nodes)
            continue
        targets = set(scope.candidate_targets + scope.original_targets + scope.possible_targets)
        claimed_targets.setdefault(scope.subject, set()).update(targets)
        old = protections.get(scope.subject)
        if old is not None:
            targets.update(old)
        protected.update(scope.original_targets)
        payload = (tuple(token(n) for n in sorted(scope.candidate_targets)),
                   tuple(token(n) for n in sorted(scope.original_targets)),
                   tuple(token(n) for n in sorted(scope.possible_targets)))
        if (scope.subject not in nodes or scope.subject.kind not in ("fragment", "group")
                or not targets or not targets <= nodes or old is None or not set(old) <= set(scope.original_targets)
                or any(unit_of(scope.subject) != target.identity[2] for target in targets)
                or scope_counts[scope.subject] != 1 or not matches(scope.proof_ref, "scope", scope.subject, payload)):
            issue("impact_scope_unproven", (scope.subject,), (scope.proof_ref,))
            unresolved.add(scope.subject)
            continue
        scoped.add(scope.subject)
        scoped_targets[scope.subject] = targets
        for target in targets:
            key = (scope.subject, target, tuple(sorted(METRICS)), scope.proof_ref)
            edges[key] = Dependency(scope.subject, target, tuple(sorted(METRICS)), scope.proof_ref)
            incoming[target].add(scope.subject)

    seeds = list(request.seeds)
    automatic_origins = {}
    manual_ids = {id(seed) for seed in request.seeds}
    manual_keys = set()
    for index, problem in enumerate(fragments.issues):
        if problem.localization_status == "history_only":
            # Bad historical metadata limits traceability, not current quantity.
            issue("historical_reference_limited", refs=problem.basis_refs)
            continue
        subjects = tuple(fragment_node(k) for k in problem.fragment_refs) or tuple(fact_node(r) for r in problem.parent_refs)
        if not subjects or problem.localization_status == "unproven":
            issue("fragment_impact_unproven", subjects, problem.basis_refs)
            unresolved.update(subjects or nodes)
        for subject in subjects:
            if subject in nodes:
                generated = RestrictionSeed("fragment:" + problem.code + ":" + repr(token(subject)),
                                             "quantity_unverified" if problem.code in (
                                                 "invalid_parent_quantity", "invalid_parent_payload",
                                                 "duplicate_parent_definition", "conflicting_active_fact_identity") else "invalid_record",
                                             subject, problem.basis_refs)
                seeds.append(generated)
                automatic_origins.setdefault((generated.reason_id, generated.subject, generated.kind, generated.basis_refs), set()).add(problem)
            else:
                issue("fragment_issue_node_missing", (subject,), problem.basis_refs)
                unresolved.add(subject)

    validated_seeds, reason_payloads = {}, {}
    for seed in seeds:
        if (type(seed) is not RestrictionSeed or not text(seed.reason_id) or type(seed.kind) is not str
                or seed.kind not in REASON_METRICS or not valid_node(seed.subject)
                or type(seed.basis_refs) is not tuple or not all(strings(r, 2) for r in seed.basis_refs)):
            issue("invalid_or_unknown_restriction_reason")
            unresolved.update(nodes)
            continue
        if seed.subject not in nodes:
            issue("restriction_subject_missing", (seed.subject,))
            unresolved.add(seed.subject)
            continue
        payload = (seed.kind, seed.subject, seed.basis_refs)
        if id(seed) in manual_ids:
            manual_keys.add((seed.reason_id, seed.subject, seed.kind, seed.basis_refs))
        if seed.reason_id in reason_payloads and reason_payloads[seed.reason_id] != payload:
            issue("reason_identity_conflict", (seed.subject,), seed.basis_refs)
            unresolved.update((seed.subject, reason_payloads[seed.reason_id][1]))
        # Keep all conflicting claims for conservative union; never choose last.
        reason_payloads.setdefault(seed.reason_id, payload)
        validated_seeds[(seed.reason_id, seed.subject, seed.kind, seed.basis_refs)] = seed
        if (seed.subject.kind in ("fragment", "group")
                and REASON_METRICS[seed.kind] & _SCOPE_SENSITIVE and seed.subject not in scoped):
            issue("restriction_scope_basis_missing", (seed.subject,), seed.basis_refs)
            unresolved.add(seed.subject)

    adjacency = {n: [] for n in nodes}
    for edge in edges.values():
        adjacency[edge.source].append(edge)
    for edge in required_links:
        adjacency[edge.source].append(edge)
    blocked = {n: {} for n in nodes}
    queue, seen = deque(), set()

    def enqueue(node, metric, reason):
        key = (node, metric, reason)
        if key not in seen:
            seen.add(key)
            queue.append(key)
    for seed in validated_seeds.values():
        for metric in REASON_METRICS[seed.kind]:
            enqueue(seed.subject, metric, seed.reason_id)
    steps = 0
    while queue:
        node, metric, reason = queue.popleft()
        steps += 1
        blocked[node].setdefault(metric, set()).add(reason)
        for edge in adjacency[node]:
            if metric in edge.metrics:
                enqueue(edge.target, metric, reason)

    # A restriction arriving through a dependency must obey the same scope
    # contract as a direct seed; no missing-scope shortcut may release old targets.
    for node in nodes:
        if node.kind in ("fragment", "group") and set(blocked[node]) & _SCOPE_SENSITIVE and node not in scoped:
            issue("propagated_restriction_scope_missing", (node,))
            unresolved.add(node)
            required = mandatory_targets.get(node, set())
            protected.update(required)
            claimed_targets.setdefault(node, set()).update(required)

    # Later invalid references/seeds can name a known omitted node. Keep their
    # diagnostic identity, but evaluate unknown influence via its registered
    # parent/children, so an explicit independent C proof can still be checked.
    for missing, anchors in missing_anchors.items():
        if missing in unresolved:
            unresolved.remove(missing)
            unresolved.update(anchors)

    closure_groups = {}
    for row in request.closures:
        if (type(row) is not Closure or not valid_node(row.subject) or row.subject.kind != "portion"
                or row.subject not in nodes or not _nodes(row.excluded_subjects)
                or not set(row.excluded_subjects) <= nodes or not strings(row.proof_ref, 2)):
            issue("invalid_closure_basis")
            continue
        closure_groups.setdefault(row.subject, []).append(row)
    results, closure_traces = [], []
    universe = tuple(token(n) for n in sorted(nodes))
    for node in sorted(nodes):
        scope_ok = node not in unresolved
        if node.kind == "portion":
            rows = closure_groups.get(node, ())
            trace_binding_valid = trace_exclusions_valid = False
            if len(rows) == 1:
                row = rows[0]
                payload = (universe, tuple(token(n) for n in sorted(incoming[node])),
                           tuple(token(n) for n in sorted(row.excluded_subjects)))
                # A closure cannot erase an actual blocking edge or exclude itself.
                scope_ok = (matches(row.proof_ref, "closure", node, payload)
                            and not set(row.excluded_subjects) & (incoming[node] | {node})
                            and not any(node in claimed_targets.get(s, ()) for s in row.excluded_subjects)
                            and {s for s in unresolved if s not in scoped_targets or node in scoped_targets[s]}
                            <= set(row.excluded_subjects))
                trace_binding_valid = matches(row.proof_ref, "closure", node, payload)
                trace_exclusions_valid = (not set(row.excluded_subjects) & (incoming[node] | {node})
                                          and not any(node in claimed_targets.get(s, ()) for s in row.excluded_subjects))
            else:
                scope_ok = False
            if not scope_ok:
                issue("portion_independence_unproven", (node,))
            closure_traces.append(ClosureTrace(
                node, scope_ok,
                tuple(sorted(s for s in unresolved if s not in scoped_targets or node in scoped_targets[s])),
                tuple(sorted(incoming[node])), tuple(rows),
                tuple((s, tuple(sorted(targets))) for s, targets in sorted(claimed_targets.items()) if node in targets),
                trace_binding_valid, trace_exclusions_valid))
        state = "restricted" if blocked[node] else "unrestricted_by_supplied_reasons"
        if not scope_ok:
            state = "scope_unproven"
        results.append(NodeRestriction(node, state, tuple((m, tuple(sorted(ids))) for m, ids in sorted(blocked[node].items()))))
    status = "scope_unproven" if any(n.state == "scope_unproven" for n in results) else "partial" if issues or any(blocked.values()) else "validated_restrictions"
    return RestrictionResult(request, fragments, status, tuple(results), tuple(sorted(protected)),
                             tuple(sorted(edges.values(), key=lambda e: (e.source, e.target, e.metrics))),
                             tuple(issues), steps, required_parent_dependencies=required_links,
                             causal_trace=_trace_restrictions(nodes, validated_seeds.values(),
                                                             tuple(edges.values()) + required_links, automatic_origins, manual_keys),
                             closure_trace=tuple(closure_traces))
