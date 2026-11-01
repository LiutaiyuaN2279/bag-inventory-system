"""WP-2 structural validation only. No allocation, totals, approvals or storage.

All provenance bindings here are synthetic test bindings, never real-source
qualification. A valid fragment is not a supported balance or an approved receipt.
"""
from dataclasses import dataclass
from decimal import Decimal, localcontext

from .audit_delivery_contract import V2, _exact_quantity


def text(value):
    return type(value) is str and len(value.strip()) > 0


def strings(value, length=None):
    return (type(value) is tuple and (length is None or len(value) == length)
            and all(text(v) for v in value))


@dataclass(frozen=True)
class ValidationContext:
    contract_version: str
    manifest_ref: str
    observation_ref: str
    assurance_level: str = "synthetic_only"


def valid_context(value):
    return (type(value) is ValidationContext and text(value.contract_version)
            and value.contract_version == V2 and text(value.manifest_ref)
            and text(value.observation_ref) and type(value.assurance_level) is str
            and value.assurance_level == "synthetic_only")


@dataclass(frozen=True, order=True)
class FactRef:
    source_event_key: str
    version: str


def fact_ref(value):
    return type(value) is FactRef and text(value.source_event_key) and text(value.version)


@dataclass(frozen=True, order=True)
class FragmentKey:
    parent_fact_ref: FactRef
    partition_version: str
    fragment_id: str


def fragment_key(value):
    return (type(value) is FragmentKey and fact_ref(value.parent_fact_ref)
            and text(value.partition_version) and text(value.fragment_id))


@dataclass(frozen=True)
class ParentFact:
    ref: FactRef
    delivery_id: str
    unit: str
    quantity: object


@dataclass(frozen=True)
class PartitionBasis:
    ref: tuple
    parent_fact_ref: FactRef
    partition_version: str
    unit: str
    manifest_ref: str
    observation_ref: str
    evidence_ref: tuple
    # Each range binds (fragment_id, start, end, quantity, control_group).
    ranges: tuple


@dataclass(frozen=True)
class Fragment:
    key: FragmentKey
    start: object
    end: object
    quantity: object
    unit: str
    control_group: str
    basis_ref: tuple


@dataclass(frozen=True)
class FragmentReference:
    fragment_id: str
    parent_fact_ref: FactRef | None = None
    partition_version: str | None = None


@dataclass(frozen=True)
class EffectiveRelation:
    relation_id: str
    version: str
    fragment: FragmentKey
    # Opaque versioned business reference; no business ID format is prescribed.
    target_ref: tuple
    basis_ref: tuple


@dataclass(frozen=True)
class FragmentManifest:
    context: ValidationContext
    facts: tuple
    partition_bases: tuple
    definitions: tuple
    active_relations: tuple = ()
    history_relations: tuple = ()
    issue_references: tuple = ()


@dataclass(frozen=True)
class FragmentIssue:
    code: str
    parent_refs: tuple = ()
    fragment_refs: tuple = ()
    record_paths: tuple = ()
    localization_status: str = "unproven"
    basis_refs: tuple = ()


@dataclass(frozen=True)
class UncoveredRange:
    parent_ref: FactRef
    start: Decimal
    end: Decimal
    quantity: Decimal
    # Multiple gaps share one mathematical control identity, not extra receipts.
    control_ref: tuple


@dataclass(frozen=True)
class FragmentValidation:
    input_manifest: object
    status: str
    canonical_fact_refs: tuple
    structurally_valid_keys: tuple
    rejected_keys: tuple
    resolved_issue_references: tuple
    uncovered_ranges: tuple
    coverage_undetermined_parents: tuple
    issues: tuple
    calculation_performed: bool = False
    formal_eligible: bool = False


def validate_fragment_manifest(manifest):
    """Validate a supplied immutable manifest; never select a business version.

    parent_bound is ONLY a structural parent binding. Business impact/locality
    needs the separately bound scope/closure proofs in audit_delivery_restrictions.
    """
    issues, bad_parents, bad_keys = [], set(), set()
    declared_parents = set()

    def issue(code, parents=(), keys=(), paths=(), bases=(), history_only=False):
        parents = tuple(sorted(set(p for p in parents if fact_ref(p))))
        keys = tuple(sorted(set(k for k in keys if fragment_key(k))))
        issues.append(FragmentIssue(code, parents, keys, tuple(paths),
                                    "history_only" if history_only else
                                    "parent_bound" if parents and all(p in declared_parents for p in parents)
                                    else "unproven", tuple(bases)))

    def result(facts=(), keys=(), resolved=(), gaps=()):
        unproven = any(i.localization_status == "unproven" for i in issues)
        status = "scope_unproven" if unproven else "partial" if issues else "validated_structure"
        return FragmentValidation(manifest, status, tuple(sorted(facts)), tuple(sorted(keys)),
                                  tuple(sorted(bad_keys)), tuple(resolved), tuple(gaps),
                                  tuple(sorted(bad_parents)), tuple(issues))

    if type(manifest) is not FragmentManifest or not valid_context(manifest.context):
        issue("invalid_validation_context")
        return FragmentValidation(manifest, "request_rejected", (), (), (), (), (), (), tuple(issues))
    if not all(type(getattr(manifest, key)) is tuple for key in
               ("facts", "partition_bases", "definitions", "active_relations", "history_relations", "issue_references")):
        issue("invalid_manifest_collection")
        return FragmentValidation(manifest, "request_rejected", (), (), (), (), (), (), tuple(issues))

    fact_groups, sources, delivery_ids = {}, {}, {}
    quantities = []
    for index, row in enumerate(manifest.facts):
        path = f"facts[{index}]"
        if type(row) is not ParentFact or not fact_ref(row.ref):
            issue("invalid_parent_identity", paths=(path,))
            continue
        fact_groups.setdefault(row.ref, []).append(row)
        declared_parents.add(row.ref)
        sources.setdefault(row.ref.source_event_key, set()).add(row.ref)
        if not text(row.delivery_id) or not text(row.unit):
            issue("invalid_parent_payload", (row.ref,), paths=(path,))
            bad_parents.add(row.ref)
            continue
        delivery_ids.setdefault(row.delivery_id, set()).add(row.ref)
        try:
            quantities.append(_exact_quantity(row.quantity))
        except ValueError:
            issue("invalid_parent_quantity", (row.ref,), paths=(path,))
            bad_parents.add(row.ref)
    for ref, rows in fact_groups.items():
        if len(rows) != 1:
            issue("duplicate_parent_definition", (ref,))
            bad_parents.add(ref)
    for refs in list(sources.values()) + list(delivery_ids.values()):
        if len(refs) > 1:
            issue("conflicting_active_fact_identity", tuple(refs))
            bad_parents.update(refs)
    parents = {ref: rows[0] for ref, rows in fact_groups.items() if ref not in bad_parents}

    basis_groups = {}
    for index, basis in enumerate(manifest.partition_bases):
        path = f"partition_bases[{index}]"
        if (type(basis) is not PartitionBasis or not strings(basis.ref, 2)
                or not fact_ref(basis.parent_fact_ref)):
            known = (basis.parent_fact_ref,) if type(basis) is PartitionBasis and fact_ref(basis.parent_fact_ref) else ()
            issue("invalid_partition_basis", known, paths=(path,))
            continue
        canonical = None
        try:
            if (not text(basis.partition_version) or not text(basis.unit)
                    or not text(basis.manifest_ref) or not text(basis.observation_ref)
                    or not strings(basis.evidence_ref, 2) or type(basis.ranges) is not tuple):
                raise ValueError()
            ranges = []
            for row in basis.ranges:
                if type(row) is not tuple or len(row) != 5 or not text(row[0]) or not text(row[4]):
                    raise ValueError()
                numbers = tuple(_exact_quantity(v) for v in row[1:4])
                quantities.extend(numbers)
                ranges.append((row[0],) + numbers + (row[4],))
            if len({r[0] for r in ranges}) != len(ranges):
                raise ValueError()
            canonical = tuple(ranges)
        except ValueError:
            issue("invalid_partition_basis", (basis.parent_fact_ref,), paths=(path,), bases=(basis.ref,))
        basis_groups.setdefault(basis.ref, []).append((basis, canonical))
    bases = {}
    for ref, rows in basis_groups.items():
        if len(rows) != 1:
            issue("conflicting_partition_basis", tuple(b.parent_fact_ref for b, _ in rows), bases=(ref,))
        elif rows[0][1] is not None:
            bases[ref] = rows[0]

    groups, parsed = {}, {}
    for index, row in enumerate(manifest.definitions):
        path = f"definitions[{index}]"
        parent = row.key.parent_fact_ref if type(row) is Fragment and type(row.key) is FragmentKey else None
        if type(row) is not Fragment or not fragment_key(row.key):
            issue("invalid_fragment_identity", (parent,), paths=(path,))
            if fact_ref(parent):
                bad_parents.add(parent)
            continue
        groups.setdefault(row.key, []).append(index)
        try:
            numbers = tuple(_exact_quantity(v) for v in (row.start, row.end, row.quantity))
            quantities.extend(numbers)
            if not text(row.unit) or not text(row.control_group) or not strings(row.basis_ref, 2):
                raise ValueError()
            parsed[index] = numbers + (row.unit, row.control_group, row.basis_ref)
        except ValueError:
            issue("invalid_fragment_value", (parent,), (row.key,), (path,))
            bad_keys.add(row.key)
            bad_parents.add(parent)
    for key in sorted(groups):
        indexes = groups[key]
        if len(indexes) > 1:
            values = [parsed.get(i) for i in indexes]
            same = all(v is not None for v in values) and all(v == values[0] for v in values)
            issue("duplicate_fragment_definition" if same else "fragment_identity_conflict",
                  (key.parent_fact_ref,), (key,), tuple(f"definitions[{i}]" for i in indexes))
            bad_keys.add(key)
            bad_parents.add(key.parent_fact_ref)

    # A partition version describes a parent's coordinate system. Disjoint
    # coordinates from different versions are not a composition proof. This
    # manifest has no cross-partition composition contract: retain the parent
    # and original definitions, but do not certify an invented current partition.
    # History-only references and unused bases are not current definitions.
    partitions = {}
    for key in groups:
        partitions.setdefault(key.parent_fact_ref, {}).setdefault(key.partition_version, set()).add(key)
    for parent, versions in sorted(partitions.items()):
        if len(versions) > 1:
            keys = tuple(sorted(k for members in versions.values() for k in members))
            indexes = tuple(i for key in keys for i in groups[key])
            refs = tuple(sorted({manifest.definitions[i].basis_ref for i in indexes
                                 if strings(manifest.definitions[i].basis_ref, 2)}))
            issue("partition_composition_unproven", (parent,), keys,
                  tuple(f"definitions[{i}]" for i in sorted(indexes)), refs)
            bad_keys.update(keys)
            bad_parents.add(parent)

    # Cover every new coordinate in the precision budget; no float/tolerance.
    with localcontext() as ctx:
        if quantities:
            ctx.prec = max(28, max(v.adjusted() for v in quantities) + 1
                           - min(v.as_tuple().exponent for v in quantities) + len(str(len(quantities) + 1)) + 3)
        valid = {}
        for key in sorted(groups):
            if key in bad_keys:
                continue
            i = groups[key][0]
            row = manifest.definitions[i]
            start, end, amount, unit, control, basis_ref = parsed[i]
            parent = parents.get(key.parent_fact_ref)
            basis_pair = bases.get(basis_ref)
            code = None
            if parent is None:
                code = "parent_binding_unavailable"
            elif not (Decimal(0) <= start < end <= _exact_quantity(parent.quantity)) or end - start != amount:
                code = "invalid_fragment_interval_or_length"
            elif unit != parent.unit:
                code = "fragment_unit_mismatch"
            elif basis_pair is None:
                code = "partition_basis_unavailable"
            else:
                basis, ranges = basis_pair
                if (basis.parent_fact_ref != key.parent_fact_ref or basis.partition_version != key.partition_version
                        or basis.unit != unit or basis.manifest_ref != manifest.context.manifest_ref
                        or basis.observation_ref != manifest.context.observation_ref
                        or (key.fragment_id, start, end, amount, control) not in ranges):
                    code = "partition_basis_binding_mismatch"
            if code is not None:
                extra = (basis_pair[0].parent_fact_ref,) if basis_pair else ()
                issue(code, (key.parent_fact_ref,) + extra, (key,), (f"definitions[{i}]",), (basis_ref,))
                bad_keys.add(key)
                bad_parents.add(key.parent_fact_ref)
            else:
                valid[key] = (start, end, amount)
        # Pairwise interval checks catch ALL overlaps, including nested ranges.
        keys = sorted(valid)
        for i, key in enumerate(keys):
            for other in keys[i + 1:]:
                if key.parent_fact_ref == other.parent_fact_ref:
                    a, b, _ = valid[key]
                    c, d, _ = valid[other]
                    if a < d and c < b:
                        issue("overlapping_fragment_ranges", (key.parent_fact_ref,), (key, other))
                        bad_keys.update((key, other))
                        bad_parents.add(key.parent_fact_ref)

        relations = {}
        relation_ids = {}
        for index, relation in enumerate(manifest.active_relations):
            if (type(relation) is not EffectiveRelation or not fragment_key(relation.fragment)
                    or not text(relation.relation_id) or not text(relation.version)
                    or not strings(relation.target_ref) or not relation.target_ref or not strings(relation.basis_ref, 2)):
                known_key = relation.fragment if type(relation) is EffectiveRelation and fragment_key(relation.fragment) else None
                known_parent = (known_key.parent_fact_ref,) if known_key is not None else ()
                issue("invalid_effective_relation", known_parent,
                      (known_key,) if known_key is not None else (), (f"active_relations[{index}]",))
                if known_key is not None:
                    bad_keys.add(known_key)
                    bad_parents.add(known_key.parent_fact_ref)
                continue
            relations.setdefault(relation.fragment, []).append(relation)
            relation_ids.setdefault((relation.relation_id, relation.version, relation.fragment), []).append(relation.fragment)
        for key, rows in relations.items():
            if key not in valid or key in bad_keys or len(rows) != 1:
                issue("effective_relation_conflict_or_missing_fragment", (key.parent_fact_ref,), (key,))
                bad_keys.add(key)
                bad_parents.add(key.parent_fact_ref)
        for refs in relation_ids.values():
            if len(refs) > 1:
                issue("duplicate_effective_relation", tuple(k.parent_fact_ref for k in refs), tuple(refs))
                bad_keys.update(refs)
                bad_parents.update(k.parent_fact_ref for k in refs)
        for index, relation in enumerate(manifest.history_relations):
            if (type(relation) is not EffectiveRelation or not fragment_key(relation.fragment)
                    or not text(relation.relation_id) or not text(relation.version)
                    or not strings(relation.target_ref) or not relation.target_ref or not strings(relation.basis_ref, 2)):
                issue("invalid_history_reference", paths=(f"history_relations[{index}]",), history_only=True)
        resolved = []
        for index, ref in enumerate(manifest.issue_references):
            path = f"issue_references[{index}]"
            if type(ref) is not FragmentReference or not text(ref.fragment_id):
                issue("invalid_fragment_reference", paths=(path,))
                continue
            if ref.parent_fact_ref is None or ref.partition_version is None:
                matches = [k for k in groups if k.fragment_id == ref.fragment_id]
                issue("ambiguous_fragment_reference" if len(matches) > 1 else "incomplete_fragment_reference",
                      tuple(k.parent_fact_ref for k in matches), tuple(matches), (path,))
            elif not fact_ref(ref.parent_fact_ref) or not text(ref.partition_version):
                issue("invalid_fragment_reference", paths=(path,))
            else:
                key = FragmentKey(ref.parent_fact_ref, ref.partition_version, ref.fragment_id)
                if key not in valid or key in bad_keys:
                    issue("unavailable_fragment_reference", (key.parent_fact_ref,), (key,), (path,))
                else:
                    resolved.append(key)  # Repeated references do not create definitions.
        final = {key: value for key, value in valid.items() if key not in bad_keys}
        gaps = []
        for ref, parent in sorted(parents.items()):
            if ref in bad_parents:
                continue  # Never manufacture a complete remainder after rejecting a bad definition.
            position = Decimal(0)
            control = (ref.source_event_key, ref.version, "uncovered")
            for start, end, _ in sorted(value for key, value in final.items() if key.parent_fact_ref == ref):
                if start > position:
                    gaps.append(UncoveredRange(ref, position, start, start - position, control))
                position = end
            q = _exact_quantity(parent.quantity)
            if position < q:
                gaps.append(UncoveredRange(ref, position, q, q - position, control))
        return result(parents, final, resolved, gaps)
