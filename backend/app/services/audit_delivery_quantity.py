"""Bounded synthetic WP-3 candidate core; no I/O, approval or public dispatch.

The original request, graph and rejected slots remain available. Mathematical
support is never real-source assurance or permission to issue a formal report.
"""
from dataclasses import fields, is_dataclass, replace
from datetime import date, datetime
from decimal import Decimal, localcontext
from contextvars import ContextVar
from functools import wraps
from struct import pack

from . import audit_delivery_fragments as f
from . import audit_delivery_restrictions as r
from .audit_delivery_contract import (
    MISSING, V2, EvaluationOutcome, FrozenContent, OpaqueInput, PreparedQuantityInput,
    QuantityIssue, QuantitySlot, QuantitySnapshot, _QUANTITY_PREPARATION_TOKEN,
    qualify_date, validate_raw_request, InputIssue, FieldObservation, DateQualification,
)
from .audit_delivery import quantity, _pending_quantities_fit


LIMITS = {"deliveries": 32, "portions": 32, "definitions": 128, "active_relations": 128,
          "history_relations": 256, "nodes": 256, "dependencies": 512, "seeds": 256,
          "evidence_records": 512, "verification_decisions": 512}
RULES = {"quantity_rule_version": "wp3-candidate-1", "age_rule_version": "natural-exclude-start-v1",
         "overdue_rule_version": "natural-exclude-start-v1", "timezone_rule_version": "Asia-Shanghai-v1",
         "first_day_rule": "exclude_start"}
_ROOT_FIELDS = frozenset(("contract_version", "operation", "input_manifest_ref", "fact_collection_ref",
    "qualification_context_ref", "business_cutoff", "unit", "business_timezone", "target_scope",
    "rule_binding", "fact_slots", "portion_slots", "relation_slots", "fragment_manifest",
    "restriction_manifest", "field_claims", "verification_decisions", "evidence_records", "coverage_records"))
_DATA_TYPES = tuple(value for module in (f, r) for value in vars(module).values()
                    if type(value) is type and is_dataclass(value)) + (QuantityIssue, QuantitySlot, InputIssue, FieldObservation, DateQualification)
_BASIS_CAPTURE = ContextVar("wp3_quantity_basis_capture", default=None)


def _collect_basis(function):
    @wraps(function)
    def invoke(prepared):
        token = _BASIS_CAPTURE.set({})
        try:
            return function(prepared)
        finally:
            _BASIS_CAPTURE.reset(token)
    return invoke


def _record_basis(key, references, binding):
    capture = _BASIS_CAPTURE.get()
    if capture is not None:
        row = capture.setdefault(key, {"actual_refs": set(), "bindings": []})
        row["actual_refs"].update(references)
        if not any(capture_same(binding, old) for old in row["bindings"]): row["bindings"].append(binding)


def _used_basis_catalog(data):
    """Resolve only referenced, actually evaluated entries within this result.

    Stable per-field/scope pointers support input order invariance; they are NOT
    positive evidence or localization proofs. Actual source IDs, versions and
    bindings live in the immutable result catalog and original raw capture.
    """
    used = set()
    def visit(value):
        if type(value) is dict:
            if "basis_refs" in value: used.update(value["basis_refs"])
            for item in value.values(): visit(item)
        elif type(value) is FrozenContent:
            if value.get("basis_refs") is not None: used.update(value["basis_refs"])
            for _, item in value.entries: visit(item)
        elif type(value) in (tuple, list):
            for item in value: visit(item)
    # Do not scan raw snapshots/catalogs and mistake stored evidence for use.
    for name in ("physical_facts", "line", "portions", "capacity_checks"):
        visit(data.get(name))
    capture = _BASIS_CAPTURE.get() or {}
    return tuple({"basis_ref": key, "actual_refs": tuple(sorted(capture[key]["actual_refs"])),
                  "bindings": tuple(sorted(capture[key]["bindings"], key=repr)),
                  "assurance_level": "synthetic_only", "formal_eligible": False}
                 for key in sorted(used) if key in capture)


def freeze(value, depth=0, seen=None):
    """Capture built-ins without invoking arbitrary equality/coercion/copy hooks."""
    if depth > 16:
        raise ValueError("synthetic_scale_limit_exceeded")
    if value is MISSING:
        return ("MISSING",)
    if value is None or type(value) in (str, bool, int, date, Decimal):
        return value
    if type(value) is float:
        return OpaqueInput("float", id(value), ("float.hex", float.hex(value)))
    if type(value) is OpaqueInput:
        if (type(value.type_name) is str and type(value.object_identity) is int
                and type(value.captured_scalar) is tuple and all(type(x) is str for x in value.captured_scalar)):
            return value
        return OpaqueInput("malformed_opaque_input", id(value))
    seen = set() if seen is None else seen
    if id(value) in seen:
        raise ValueError("cyclic_input_structure")
    seen.add(id(value))
    try:
        if type(value) is FrozenContent:
            if (type(value.entries) is not tuple or not all(type(x) is tuple and len(x) == 2
                    and type(x[0]) is str for x in value.entries)
                    or len({x[0] for x in value.entries}) != len(value.entries)):
                raise ValueError("invalid_frozen_content")
            return FrozenContent(tuple((k, freeze(v, depth + 1, seen)) for k, v in sorted(value.entries)))
        if type(value) is dict and all(type(k) is str for k in value):
            return FrozenContent(tuple((k, freeze(v, depth + 1, seen)) for k, v in sorted(value.items())))
        if type(value) in (tuple, list):
            return tuple(freeze(v, depth + 1, seen) for v in value)
        if type(value) in _DATA_TYPES:
            return FrozenContent(tuple(sorted((("_type", type(value).__name__),) + tuple(
                (field.name, freeze(getattr(value, field.name), depth + 1, seen)) for field in fields(value)))))
        return OpaqueInput(type(value).__name__, id(value))
    finally:
        seen.remove(id(value))


def plain(value):
    """Explicit evidence/log representation, not an input conversion path."""
    if type(value) is EvaluationOutcome:
        return plain(value.content)
    if type(value) is FrozenContent:
        return {k: plain(v) for k, v in value.entries}
    if type(value) is tuple:
        return [plain(v) for v in value]
    if type(value) is date:
        return value.isoformat()
    if type(value) is Decimal:
        return str(value)
    if type(value) is OpaqueInput:
        return {"unsupported_type": value.type_name, "object_identity": value.object_identity,
                "captured_scalar": value.captured_scalar}
    return value


def safe(value):
    return (value is None or type(value) in (str, bool, int, date) or type(value) is Decimal and value.is_finite()
            or type(value) is tuple and all(safe(v) for v in value)
            or type(value) is FrozenContent and all(type(k) is str and safe(v) for k, v in value.entries))


def same(left, right):
    """Type-preserving content equality; bool/int and custom equality never bind."""
    if type(left) is not type(right):
        return False
    if type(left) is FrozenContent:
        return len(left.entries) == len(right.entries) and all(k == rk and same(v, rv)
                    for (k, v), (rk, rv) in zip(left.entries, right.entries))
    if type(left) is tuple:
        return len(left) == len(right) and all(same(a, b) for a, b in zip(left, right))
    return safe(left) and left == right


def capture_same(left, right):
    # Opaque objects remain rejected; this only compares their retained identity
    # in the capture, never grants content/evidence qualification to them.
    if type(left) is not type(right):
        return False
    if type(left) is Decimal:
        # Capture identity is representation equality, NOT quantity eligibility
        # or Decimal numeric equality (NaN != itself; sNaN comparison may trap).
        # Exact built-in Decimal only: no custom equality/hash or subclass hooks.
        return Decimal.as_tuple(left) == Decimal.as_tuple(right)
    if type(left) is OpaqueInput:
        return (left.type_name == right.type_name and left.object_identity == right.object_identity
                and left.captured_scalar == right.captured_scalar)
    if type(left) is FrozenContent:
        return len(left.entries) == len(right.entries) and all(k == rk and capture_same(v, rv)
                for (k, v), (rk, rv) in zip(left.entries, right.entries))
    if type(left) is tuple:
        return len(left) == len(right) and all(capture_same(a, b) for a, b in zip(left, right))
    return same(left, right)


def capture_raw_types(value):
    """Immutable, type-sensitive original capture; NEVER qualification material.

    Flat records avoid adding nesting to the legacy business representation.
    Known scalars use exact built-in operations; opaque objects expose only type
    and object identity, not attributes, equality, hash or conversion hooks.
    Dict order is immaterial; ordered containers and their exact types remain.
    """
    records, seen = [], set()
    def visit(item, path, depth):
        if depth > 16: raise ValueError("synthetic_scale_limit_exceeded")
        kind = type(item)
        if item is MISSING: records.append((path,"MISSING",()));return
        if item is None: records.append((path,"NoneType",()));return
        if kind is bool: records.append((path,"bool",item));return
        if kind is int: records.append((path,"int",item));return
        if kind is str: records.append((path,"str",item));return
        if kind is Decimal:
            parts = Decimal.as_tuple(item)
            records.append((path,"Decimal",(parts.sign,parts.digits,parts.exponent)));return
        if kind is float: records.append((path,"float-binary64",pack("!d",item).hex()));return
        if kind is date: records.append((path,"date",date.toordinal(item)));return
        if kind is datetime:
            records.append((path,"datetime",(item.year,item.month,item.day,item.hour,item.minute,item.second,item.microsecond,item.fold)))
            # Do not call a user-supplied tzinfo.utcoffset()/tzname().
            records.append((path+("tzinfo",),"opaque",(id(type(item.tzinfo)),id(item.tzinfo))));return
        if kind is not dict and kind is not tuple and kind is not list and kind is not FrozenContent and not any(
                kind is approved for approved in _DATA_TYPES + (OpaqueInput,)):
            records.append((path,"opaque",(id(kind),id(item))));return
        if id(item) in seen: raise ValueError("cyclic_input_structure")
        seen.add(id(item))
        try:
            if kind is FrozenContent:
                entries = item.entries
                records.append((path,"FrozenContent",()))
                if type(entries) is not tuple or not all(type(pair) is tuple and len(pair)==2 and type(pair[0]) is str for pair in entries):
                    records.append((path+("entries",),"invalid-entries",(id(type(entries)),id(entries))));return
                records.append((path+("entries",),"tuple",len(entries)))
                for index,(key,child) in enumerate(entries):
                    records.append((path+("entries",index),"tuple",2))
                    records.append((path+("entries",index,0),"str",key))
                    visit(child,path+("entries",index,1),depth+1)
            elif kind is dict:
                if all(type(key) is str for key in item):
                    records.append((path,"dict",tuple(sorted(item))))
                    for key,child in sorted(item.items()):visit(child,path+(key,),depth+1)
                else:
                    # Read items directly: never look up/hash/compare an unsafe key.
                    rows=sorted(item.items(),key=lambda pair:(id(type(pair[0])),id(pair[0])))
                    records.append((path,"dict-with-untrusted-keys",len(rows)))
                    for index,(key,child) in enumerate(rows):
                        visit(key,path+(index,"key"),depth+1);visit(child,path+(index,"value"),depth+1)
            elif kind is tuple or kind is list:
                records.append((path,"tuple" if kind is tuple else "list",len(item)))
                for index,child in enumerate(item):visit(child,path+(index,),depth+1)
            else:
                records.append((path,"dataclass",kind.__module__+"."+kind.__qualname__))
                for field in fields(item):visit(getattr(item,field.name),path+(field.name,),depth+1)
        finally:
            seen.remove(id(item))
    visit(value,(),0)
    return tuple(records)


def exact_q(value):
    if type(value) not in (str, int, Decimal):
        raise ValueError("quantity_requires_exact_decimal")
    q = quantity(value)
    if len(q.as_tuple().digits) > 128 or abs(q.as_tuple().exponent) > 128:
        raise ValueError("synthetic_scale_limit_exceeded")
    return q


def _scale(raw, payload):
    for key, limit in (("deliveries", 32), ("portions", 32), ("allocations", 128)):
        if type(raw.get(key)) in (tuple, list) and len(raw[key]) > limit:
            return False
    for key in ("evidence_records", "verification_decisions"):
        if type(payload.get(key)) is tuple and len(payload[key]) > LIMITS[key]:
            return False
    manifest = payload.get("fragment_manifest")
    graph = payload.get("restriction_manifest")
    for obj, keys in ((manifest, ("definitions", "active_relations", "history_relations")),
                      (graph, ("nodes", "dependencies", "seeds"))):
        if type(obj) not in (f.FragmentManifest, r.RestrictionManifest):
            continue
        for key in keys:
            rows = getattr(obj, key)
            if type(rows) is tuple and len(rows) > LIMITS[key]:
                return False
    if type(graph) is r.RestrictionManifest:
        scopes = graph.scopes
        if type(scopes) is tuple and sum(len(x) for s in scopes if type(s) is r.ImpactScope
                for x in (s.candidate_targets, s.original_targets, s.possible_targets) if type(x) is tuple) > 2048:
            return False
    rules = payload.get("rule_binding")
    calendar = rules.get("calendar_content") if type(rules) is dict else None
    if type(calendar) is FrozenContent and type(calendar.get("days")) is tuple and len(calendar["days"]) > 3660:
        return False
    return True


def _capture_report(report):
    return freeze({"request_issues": tuple(report.request_issues), "record_issues": tuple(report.record_issues),
                   "observations": tuple(report.observations), "date_qualifications": tuple(sorted(report.date_qualifications.items()))})


def _freeze_qualification_row(value, path, problem):
    """Check raw scope types before normal capture can turn a list into tuple.

    Keep every row and the complete original capture. An invalid scope value is
    opaque in the qualification view, never a legitimate field set or default.
    Inputs already converted before this boundary cannot be reverse-engineered.
    """
    if type(value) in (dict, FrozenContent):
        pairs = value.items() if type(value) is dict else value.entries
        result = []
        for key, item in pairs:
            if type(key) is not str:
                return freeze(value)
            valid = True
            if key == "scope_fields":
                valid = type(item) is tuple and all(f.text(x) for x in item)
            elif key in ("scope_ref", "applicability_ref"):
                valid = f.text(item) or type(item) is tuple and bool(item) and all(f.text(x) for x in item)
            if not valid:
                problem("invalid_qualification_scope_type", path=path + "." + key)
                item = OpaqueInput("invalid_" + key + ":" + type(item).__name__, id(item))
            elif key in ("claim_content", "assertions"):
                item = _freeze_qualification_row(item, path + "." + key, problem)
            else:
                item = freeze(item)
            result.append((key, item))
        return FrozenContent(tuple(sorted(result)))
    if type(value) in (tuple, list):
        return tuple(_freeze_qualification_row(x, path + "[" + str(i) + "]", problem) for i, x in enumerate(value))
    return freeze(value)


def _prepare_quantity_snapshot(*, operation, raw_request, snapshot_payload):
    entry = "summarize_delivery_facts" if operation == "facts_summary" else "evaluate_delivery_scope"
    report = validate_raw_request(entry, raw_request)
    wp1 = _capture_report(report)
    issues, rejected, localization = [], [], []
    capture = ()

    def problem(code, category="input", refs=(), path="", phase="static"):
        item = QuantityIssue(code, category, tuple(refs), (), path, True, phase)
        issues.append(item)
        return item

    def reject(code, category="input"):
        problem(code, category)
        return PreparedQuantityInput(None, tuple(issues), capture, (raw_request, snapshot_payload), wp1,
                                     code, _QUANTITY_PREPARATION_TOKEN)

    if type(operation) is not str or operation not in ("facts_summary", "order_item"):
        return reject("invalid_quantity_operation")
    if type(raw_request) is not dict or type(snapshot_payload) is not dict:
        return reject("invalid_quantity_request_structure")
    if not _scale(raw_request, snapshot_payload):
        return reject("synthetic_scale_limit_exceeded", "capability")
    try:
        capture = (freeze(raw_request), freeze(snapshot_payload))
        strict_capture = (capture_raw_types(raw_request), capture_raw_types(snapshot_payload))
    except ValueError as error:
        return reject(error.args[0], "capability" if error.args[0] == "synthetic_scale_limit_exceeded" else "input")
    if not report.root_valid:
        return reject(next(x.code for x in report.request_issues if x.fatal))
    p = snapshot_payload
    if any(type(k) is not str for k in p) or set(p) - _ROOT_FIELDS:
        return reject("unsupported_snapshot_field")
    root_text = ("input_manifest_ref", "qualification_context_ref", "unit")
    if (type(p.get("contract_version")) is not str or p["contract_version"] != V2
            or type(p.get("operation")) is not str or p["operation"] != operation
            or not all(f.text(p.get(k)) for k in root_text)
            or type(p.get("business_cutoff")) is not date or type(p.get("business_timezone")) is not str or p["business_timezone"] != "Asia/Shanghai"
            or not f.strings(p.get("fact_collection_ref"), 2)):
        return reject("invalid_snapshot_context")
    context = raw_request["contract_context"]
    if (p["input_manifest_ref"] != context["input_manifest_ref"]
            or p["qualification_context_ref"] != context["qualification_context_ref"]
            or p["business_cutoff"] != raw_request["cutoff"] or p["unit"] != raw_request["unit"]):
        return reject("snapshot_context_binding_conflict")
    target = p.get("target_scope", MISSING)
    if operation == "facts_summary":
        if target is not None:
            return reject("summary_target_scope_must_be_none")
    elif (not f.strings(target, 3) or target != (raw_request["order_id"], raw_request["item_id"], raw_request["unit"])):
        return reject("target_scope_binding_conflict")
    if type(p.get("rule_binding")) is not dict:
        return reject("missing_rule_binding")
    rule_binding = freeze(p["rule_binding"])
    if not all(f.text(rule_binding.get(k)) for k in RULES):
        return reject("invalid_rule_binding")
    if any(rule_binding.get(k) != RULES[k] for k in ("quantity_rule_version", "timezone_rule_version")):
        return reject("unsupported_rule_binding")
    for name in ("fact_slots", "field_claims", "verification_decisions", "evidence_records", "coverage_records"):
        if type(p.get(name)) is not tuple:
            return reject("invalid_snapshot_collection:" + name)
    for name in ("portion_slots", "relation_slots"):
        value = p.get(name, None)
        if operation == "order_item" and type(value) is not tuple:
            problem("missing_snapshot_collection", path=name)
        elif operation == "facts_summary" and not (value is None or type(value) is tuple and not value):
            return reject("summary_has_order_records")

    def slots(group, name):
        raw_rows = raw_request.get(group, ())
        links = p.get(name)
        links = links if type(links) is tuple else ()
        if type(raw_rows) not in (list, tuple):
            return ()
        if not all(type(link) is dict for link in links):
            problem("invalid_record_binding_collection", path=name)
            links = ()
        result = []
        for index, row in enumerate(raw_rows):
            path = f"{group}[{index}]"
            frozen_row = freeze(row)
            identity = (row.get("delivery_id") if group == "deliveries" else row.get("portion_id") if group == "portions"
                        else row.get("allocation_id")) if type(row) is dict else None
            matches = [link for link in links if f.text(identity) and type(link.get("id")) is str and link["id"] == identity]
            errors, ref = [], None
            if len(matches) != 1:
                errors.append(problem("missing_or_duplicate_record_binding", path=path))
            else:
                link = matches[0]
                ref = link.get("ref")
                good_ref = (f.fact_ref(ref) if group == "deliveries" else f.strings(ref, 5) if group == "portions"
                            else type(ref) is tuple and len(ref) == 3 and f.text(ref[0]) and f.text(ref[1]) and f.fragment_key(ref[2]))
                if not good_ref:
                    errors.append(problem("invalid_record_reference", path=path))
                    ref = None
                if not same(freeze(link.get("content", MISSING)), frozen_row):
                    errors.append(problem("record_content_binding_conflict", refs=(() if ref is None else (ref,)), path=path))
                if type(row) is dict and ref is not None:
                    declared = ((row.get("source_event_key"),) if group == "deliveries" else
                                tuple(row.get(k) for k in ("order_id", "item_id", "unit", "portion_id"))
                                if group == "portions" else tuple(row.get(k) for k in ("allocation_id", "version_id")))
                    expected = (ref.source_event_key,) if group == "deliveries" else ref[:4] if group == "portions" else ref[:2]
                    bound = f.strings(declared) and expected == declared
                    if not bound:
                        errors.append(problem("record_identity_binding_conflict", refs=(ref,), path=path))
            if type(row) is not dict:
                errors.append(problem("invalid_record_type", path=path))
            else:
                for key in (("delivered_quantity",) if group == "deliveries" else ("effective_quantity",) if group == "portions"
                            else ("allocated_quantity",)):
                    try:
                        exact_q(row.get(key, MISSING))
                    except ValueError as error:
                        if error.args[0] == "synthetic_scale_limit_exceeded":
                            raise
                        errors.append(problem("invalid_quantity", refs=(() if ref is None else (ref,)), path=path + "." + key))
            slot = QuantitySlot(group, index, ref, frozen_row if type(frozen_row) is FrozenContent else FrozenContent(()),
                                not errors, tuple(errors))
            result.append(slot)
            if errors:
                rejected.append(slot)
            localization.append((path, ref, "reference_bound" if ref is not None else "unproven"))
        # Unmatched sidecar definitions are not discarded as harmless metadata.
        if len(links) != len(raw_rows):
            problem("record_binding_manifest_mismatch", path=name)
        return tuple(result)

    try:
        facts = slots("deliveries", "fact_slots")
        portions = slots("portions", "portion_slots") if operation == "order_item" else None
        relations = slots("allocations", "relation_slots") if operation == "order_item" else None
    except ValueError as error:
        return reject(error.args[0], "capability")
    manifest, graph = p.get("fragment_manifest"), p.get("restriction_manifest")
    if operation == "order_item":
        if type(manifest) is not f.FragmentManifest or type(graph) is not r.RestrictionManifest:
            problem("quantity_structure_not_provided", category="evidence")
        elif (any(type(getattr(manifest, name)) is not tuple for name in
                  ("facts", "partition_bases", "definitions", "active_relations", "history_relations", "issue_references"))
              or any(type(getattr(graph, name)) is not tuple for name in
                     ("nodes", "proofs", "dependencies", "scopes", "protections", "closures", "seeds"))):
            return reject("invalid_quantity_structure_collection")
        elif (not f.valid_context(manifest.context) or not same(freeze(graph.fragments), freeze(manifest)) or manifest.context.manifest_ref != p["input_manifest_ref"]
              or manifest.context.observation_ref != p["qualification_context_ref"]):
            problem("graph_content_binding_conflict")
    qualification_rows = {name: tuple(_freeze_qualification_row(x, name + "[" + str(i) + "]", problem)
                         for i,x in enumerate(p[name])) for name in ("field_claims", "verification_decisions", "evidence_records")}
    snapshot = QuantitySnapshot(V2, operation, p["input_manifest_ref"], p["fact_collection_ref"], p["qualification_context_ref"],
        p["business_cutoff"], p["unit"], p["business_timezone"], target, rule_binding, facts, portions, relations,
        manifest, graph, qualification_rows["field_claims"], qualification_rows["verification_decisions"],
        qualification_rows["evidence_records"], tuple(freeze(x) for x in p["coverage_records"]), strict_capture,
        wp1, tuple(rejected), tuple(localization))
    return PreparedQuantityInput(snapshot, tuple(issues), capture, (raw_request, snapshot_payload), wp1, None,
                                 _QUANTITY_PREPARATION_TOKEN)


def binding_content(raw_request, snapshot_payload):
    """Actual finite contents, excluding self-referential attestations, NOT a caller digest."""
    return freeze({"raw_request": raw_request, "snapshot": {k: v for k, v in snapshot_payload.items()
        if k not in ("field_claims", "verification_decisions", "evidence_records", "coverage_records")}})


def _registry(rows):
    result, conflicting = {}, set()
    for row in rows:
        if type(row) is not FrozenContent or not f.strings(row.get("ref"), 2) or not safe(row):
            continue
        key = row["ref"]
        if key in result and not same(result[key], row):
            conflicting.add(key)
        else:
            result[key] = row
    return {k: v for k, v in result.items() if k not in conflicting}, conflicting


def _scope_relation(candidate, expected, name):
    """Field-set meaning, not spelling equality of optional metadata.

    A bare opaque scope label is not evidence of disjointness. The existing
    contract proves field applicability through its exact tuple of field names;
    an empty field set or an unbound label remains unproven, never a free pass.
    """
    def fields(body):
        values = [v for k,v in body.entries if k == "scope_fields"]
        if not values: return {name}, "valid"
        value = values[0]
        if type(value) is not tuple or not all(f.text(x) for x in value): return set(), "invalid"
        return set(value), "valid" if value else "unproven"
    left, a = fields(candidate);right, b = fields(expected)
    if "invalid" in (a,b): return "invalid"
    for key in ("scope_ref", "applicability_ref"):
        for body in (candidate,expected):
            values = [v for k,v in body.entries if k == key]
            if values and not (f.text(values[0]) or type(values[0]) is tuple and bool(values[0])
                               and all(f.text(x) for x in values[0])):
                return "invalid"
    if a == "valid" and b == "valid" and (name not in left or name not in right):
        return "disjoint"
    if "unproven" in (a,b): return "unproven"
    for key in ("scope_ref", "applicability_ref"):
        left_ref = tuple(v for k,v in candidate.entries if k == key)
        right_ref = tuple(v for k,v in expected.entries if k == key)
        if not same(left_ref,right_ref): return "unproven"
    return "applies"


def _field_body_equal(left, right, name):
    """Equivalent scope_fields representations only; other bindings stay exact."""
    if type(left) is not FrozenContent or type(right) is not FrozenContent or not safe(left) or not safe(right):
        return False
    if _scope_relation(left,right,name) != "applies": return False
    return same(FrozenContent(tuple((k,v) for k,v in left.entries if k != "scope_fields")),
                FrozenContent(tuple((k,v) for k,v in right.entries if k != "scope_fields")))


def _qualification_issue(code, subject, refs):
    capture = _BASIS_CAPTURE.get()
    if capture is not None:
        issue = QuantityIssue(code, "input" if code == "invalid_qualification_scope_type" else "evidence",
                              (subject,), tuple(("decision",)+ref for ref in refs), "", True, "qualification")
        rows = capture.setdefault(("qualification_diagnostics",), [])
        if issue not in rows: rows.append(issue)


def _qualification(snapshot, subject, name, value, flag=True, *, projection=None):
    """Synthetic content attestation, never a real-source resolver."""
    if flag is not True or not safe(value):
        return "unverified", ()
    def body_view(body):
        if projection is None or type(body) is not FrozenContent:
            return body
        return FrozenContent(tuple((k, projection(v) if k == "value" else v) for k, v in body.entries))
    decision_rows = tuple(FrozenContent(tuple((k, body_view(v) if k == "claim_content" else v) for k,v in row.entries))
                          if type(row) is FrozenContent else row for row in snapshot.verification_decisions)
    evidence_rows = tuple(FrozenContent(tuple((k, tuple(body_view(x) for x in v) if k == "assertions" and type(v) is tuple else v)
                          for k,v in row.entries)) if type(row) is FrozenContent else row for row in snapshot.evidence_records)
    claims = tuple(body_view(x) for x in snapshot.field_claims)
    def same_field(candidate, expected):
        if type(candidate) is not FrozenContent: return False
        if not all(same(candidate.get(key), expected.get(key)) for key in
                   ("subject_ref", "field_name", "value", "qualification_context_ref")): return False
        return True
    decisions, dc = _registry(decision_rows)
    evidence, ec = _registry(evidence_rows)
    matches = [x for x in claims if type(x) is FrozenContent
               and same(x.get("subject_ref"), subject) and same(x.get("field_name"), name)]
    if not matches:
        return "unverified", ()
    conclusions, refs, date_bases = set(), set(), []
    for claim in matches:
        if (not safe(claim) or type(claim.get("declared_verified")) is not bool or claim["declared_verified"] is not True
                or not same(claim.get("value", MISSING), value) or claim.get("qualification_context_ref") != snapshot.qualification_context_ref
                or type(claim.get("decision_refs")) is not tuple):
            return "conflict", tuple(sorted(refs))
        body = FrozenContent(tuple((k, v) for k, v in claim.entries if k != "decision_refs"))
        if not claim["decision_refs"]:
            return "unverified", ()
        # References are audit links, never a whitelist capable of hiding an
        # applicable active opposing decision. Inactive/other-content decisions
        # do not become current merely because they are present in the snapshot.
        applicable = {row["ref"] for row in decision_rows if type(row) is FrozenContent
                      and f.strings(row.get("ref"), 2) and row.get("status") == "active"
                      and row.get("observation_ref") == snapshot.qualification_context_ref
                      and same_field(row.get("claim_content"), body)}
        supplied_refs = claim["decision_refs"]
        if not all(f.strings(ref, 2) for ref in supplied_refs):
            return "conflict", tuple(sorted(refs | applicable))
        all_refs = applicable | set(supplied_refs)
        refs.update(all_refs)
        for ref in sorted(all_refs):
            # An invalid raw scope must not vanish because safe() excludes its
            # opaque qualification view from the registry.
            candidates = [row for row in decision_rows if type(row) is FrozenContent and f.strings(row.get("ref"),2)
                          and row["ref"] == ref and same_field(row.get("claim_content"),body)
                          and row.get("status") == "active" and row.get("observation_ref") == snapshot.qualification_context_ref]
            relations = [_scope_relation(row["claim_content"],body,name) for row in candidates]
            if "invalid" in relations or "unproven" in relations:
                _qualification_issue("invalid_qualification_scope_type" if "invalid" in relations else
                                     "qualification_scope_relation_unproven", subject, tuple(sorted(all_refs)))
                return "conflict", tuple(sorted(refs))
            if not f.strings(ref, 2) or ref in dc or ref not in decisions:
                return "conflict", tuple(sorted(refs))
            decision = decisions[ref]
            er = decision.get("evidence_refs")
            decision_body = decision.get("claim_content")
            if (decision.get("status") != "active" or decision.get("observation_ref") != snapshot.qualification_context_ref
                    or not same_field(decision_body, body)):
                continue
            relation = _scope_relation(decision_body, body, name)
            if (type(decision.get("conclusion")) is not bool or decision.get("assurance_level") != "synthetic_only"
                    or type(er) is not tuple or not er
                    or decision.get("conclusion") is True and relation != "disjoint" and not _field_body_equal(decision_body, body, name)):
                return "conflict", tuple(sorted(refs))
            for e in er:
                if (not f.strings(e, 2) or e in ec or e not in evidence
                        or type(evidence[e].get("assertions")) is not tuple or not any(
                            same(decision_body, a) or _field_body_equal(decision_body,a,name) for a in evidence[e]["assertions"])):
                    return "conflict", tuple(sorted(refs))
            if relation == "disjoint":
                # Only the source-bound explicit field exclusion proves this.
                continue
            if relation != "applies":
                _qualification_issue("qualification_scope_relation_unproven", subject, tuple(sorted(all_refs)))
                return "conflict", tuple(sorted(refs))
            conclusions.add(decision["conclusion"])
            refs.add(ref)
            if name in ("actual_date", "commitment_date"):
                date_bases.append({"subject_ref": subject, "field_name": name, "value": value,
                    "precision": claim.get("precision"), "time_zone": claim.get("time_zone"),
                    "timezone_basis_ref": claim.get("timezone_basis_ref"),
                    "qualification_context_ref": snapshot.qualification_context_ref,
                    "evidence_id": er[0][0], "evidence_version": er[0][1], "decision_id": ref[0], "decision_version": ref[1],
                    "scope_ref": "bound-field", "scope_fields": (name,), "decision_status": "active",
                    "conclusion": decision["conclusion"], "assurance_level": "synthetic_only"})
    if conclusions != {True}:
        return ("conflict" if len(conclusions) > 1 else "unverified"), tuple(sorted(refs))
    if date_bases:
        claim = matches[0]
        qualified = qualify_date(flag=flag, value=value, subject_ref=subject, field_name=name,
            precision=claim.get("precision"), time_zone=claim.get("time_zone"),
            timezone_basis_ref=claim.get("timezone_basis_ref"), qualification_context_ref=snapshot.qualification_context_ref,
            bases=date_bases)
        return qualified.status, qualified.decision_refs
    return "qualified", tuple(sorted(refs))


def _scoped_coverage_content(prepared, scope, content):
    """Positive scope material, separate from the complete rejected-input capture.

    No opaque value is compared or qualified. A projection is allowed only for
    a proof-closed portion, and includes the complete graph plus every source's
    influence ledger; different IDs alone never prove independence.
    """
    if not f.strings(scope, 6) or scope[0] != "portion" or type(content) is not FrozenContent:
        return None
    s = prepared.snapshot
    if type(s.restriction_manifest) is not r.RestrictionManifest or type(s.fragment_manifest) is not f.FragmentManifest:
        return None
    result = r.map_restrictions(s.restriction_manifest)
    node = r.Node("portion", scope[1:])
    closure = next((x for x in result.closure_trace if x.node == node), None)
    if closure is None or not closure.passed:
        return None
    raw, payload = content.get("raw_request"), content.get("snapshot")
    if type(raw) is not FrozenContent or type(payload) is not FrozenContent:
        return None
    deliveries, portions, allocations = (raw.get(k) for k in ("deliveries", "portions", "allocations"))
    if not all(type(rows) is tuple and all(type(x) is FrozenContent for x in rows) for rows in (deliveries, portions, allocations)):
        return None
    pid = scope[4]
    selected, ledger = set(), []
    for row in deliveries:
        did, source, candidates = row.get("delivery_id"), row.get("source_event_key"), row.get("candidate_portion_ids", ())
        if not f.text(did) or not f.text(source) or type(candidates) is not tuple or not all(f.text(x) for x in candidates):
            return None
        ledger.append(("fact", did, source, row.get("order_id"), row.get("item_id"), row.get("unit"), candidates))
        if pid in candidates:
            selected.add(did)
    for row in allocations:
        ids = tuple(row.get(k) for k in ("allocation_id", "delivery_id", "portion_id", "version_id"))
        if not f.strings(ids, 4):
            return None
        ledger.append(("relation",) + ids)
        if row["portion_id"] == pid:
            selected.add(row["delivery_id"])
    # Actual validated dependency ancestors may add sources that raw labels
    # alone would miss. Never remove a declared or historical original target.
    ancestors = {node}
    edges = result.used_dependencies + result.required_parent_dependencies
    while True:
        expanded = ancestors | {edge.source for edge in edges if edge.target in ancestors}
        if expanded == ancestors:
            break
        ancestors = expanded
    for fact in s.fragment_manifest.facts:
        if type(fact) is f.ParentFact and f.fact_ref(fact.ref) and r.fact_node(fact.ref) in ancestors:
            selected.add(fact.delivery_id)
    raw_view = FrozenContent(tuple((k, tuple(x for x in v if x.get("delivery_id") in selected) if k in ("deliveries", "allocations")
                                  else tuple(x for x in v if x.get("portion_id") == pid) if k == "portions" else v)
                                  for k,v in raw.entries))
    def selected_slots(name, rows):
        if type(rows) is not tuple or not all(type(x) is FrozenContent for x in rows):
            return None
        return tuple(x for x in rows if x.get("id") == pid) if name == "portion_slots" else tuple(
            x for x in rows if type(x.get("content")) is FrozenContent and x["content"].get("delivery_id") in selected)
    snapshot_view = FrozenContent(tuple((k, selected_slots(k,v) if k in ("fact_slots","portion_slots","relation_slots") else v)
                                        for k,v in payload.entries))
    view = freeze({"scope_ref": scope, "raw_request": raw_view, "snapshot": snapshot_view,
                   "complete_influence_ledger": tuple(ledger)})
    return view if safe(view) else None


def _coverage_result(prepared, scope):
    snapshot = prepared.snapshot
    expected = binding_content(*prepared.raw_sources)
    rows = [row for row in snapshot.coverage_records if type(row) is FrozenContent and same(row.get("scope_ref"), scope)]
    if len(rows) != 1 or rows[0].get("declared_complete") is not True:
        return False, ()
    if safe(expected) and same(rows[0].get("content"), expected):
        status, refs = _qualification(snapshot, scope, "coverage", expected)
        return status == "qualified", refs
    projection = lambda value: _scoped_coverage_content(prepared, scope, value)
    projected = projection(expected)
    if projected is None or not same(projection(rows[0].get("content")), projected):
        return False, ()
    status, refs = _qualification(snapshot, scope, "coverage", projected, projection=projection)
    return status == "qualified", refs


def _covered(prepared, scope):
    return _coverage_result(prepared, scope)[0]


def _decision_basis(s, refs):
    result = set()
    for row in s.verification_decisions:
        if type(row) is FrozenContent and f.strings(row.get("ref"), 2) and row["ref"] in refs:
            body = row.get("claim_content")
            if type(body) is not FrozenContent or not f.strings(body.get("subject_ref")) or not f.text(body.get("field_name")):
                continue
            key = ("qualification",) + body["subject_ref"] + (body["field_name"], s.qualification_context_ref)
            actual = {("decision",) + row["ref"]}
            for ref in row.get("evidence_refs", ()) if type(row.get("evidence_refs")) is tuple else ():
                if f.strings(ref, 2): actual.add(("evidence",) + ref)
            _record_basis(key, actual, freeze({"subject_ref": body["subject_ref"], "field_name": body["field_name"],
                "value": body.get("value") if body["field_name"] != "coverage" else None,
                "full_content_location": ("raw_capture", 1, "verification_decisions", row["ref"]),
                "observation_ref": s.qualification_context_ref}))
            result.add(key)
    return result


def _field_basis(s, subject, name, value, flag=True):
    return _decision_basis(s, _qualification(s, subject, name, value, flag)[1])


def _coverage_basis(prepared, scope):
    qualified, refs = _coverage_result(prepared, scope)
    return _decision_basis(prepared.snapshot, refs) | ({("coverage_scope",) + scope} if qualified else set())


def _rule_basis(s, *names):
    return {("rule", name, s.rule_binding[name]) for name in names} | {
        ("observation", s.input_manifest_ref, s.qualification_context_ref),
        ("cutoff", s.business_cutoff.isoformat(), s.business_timezone)}


def _actual_graph_basis(s, result, refs):
    """Only the actual dependency ancestors/closure of the requested portions."""
    if result is None or type(s.fragment_manifest) is not f.FragmentManifest or type(s.restriction_manifest) is not r.RestrictionManifest:
        return set()
    nodes = {r.Node("portion", ref) for ref in refs if f.strings(ref, 5)}
    edges = result.used_dependencies + result.required_parent_dependencies
    while True:
        expanded = nodes | {edge.source for edge in edges if edge.target in nodes}
        if expanded == nodes: break
        nodes = expanded
    basis = set()
    for row in s.restriction_manifest.closures:
        if type(row) is r.Closure and r.valid_node(row.subject) and row.subject in nodes and f.strings(row.proof_ref, 2):
            basis.add(("binding_proof",) + row.proof_ref)
    for edge in edges:
        if edge.source in nodes and edge.target in nodes and type(edge) is r.Dependency:
            basis.add(("binding_proof",) + edge.proof_ref)
    for definition in s.fragment_manifest.definitions:
        if type(definition) is f.Fragment and f.fragment_key(definition.key) and r.fragment_node(definition.key) in nodes:
            if f.strings(definition.basis_ref, 2): basis.add(("partition_basis",) + definition.basis_ref)
    for row in s.fragment_manifest.active_relations:
        if type(row) is f.EffectiveRelation and f.fragment_key(row.fragment) and r.fragment_node(row.fragment) in nodes and f.text(row.relation_id) and f.text(row.version):
            basis.add(("effective_relation", row.relation_id, row.version))
    return basis


def _graph_basis(s, result, refs):
    pointers = set()
    for ref in sorted(refs):
        if f.strings(ref, 5):
            key = ("graph_scope",) + ref + (s.qualification_context_ref,)
            actual = _actual_graph_basis(s, result, (ref,))
            if actual:
                _record_basis(key, actual, freeze({"scope_ref": ref, "input_manifest_ref": s.input_manifest_ref,
                                                   "observation_ref": s.qualification_context_ref}))
                pointers.add(key)
    return pointers


def _issue(code, category, refs=(), phase="metric", blocking=True):
    return QuantityIssue(code, category, tuple(refs), (), "", blocking, phase)


def _metric(value, *, reasons=(), applicable=True, constant=False, supported=False,
            unsupported=False, scope=(), coverage="complete", subset=False, basis_refs=()):
    """Approved D1 precedence, applied separately to EVERY metric."""
    reasons = tuple(sorted(set(reasons), key=lambda x: (x.code, x.category, repr(freeze(x.subject_refs)), x.path, x.phase)))
    business = any(x.blocking and x.category != "capability" for x in reasons)
    if not applicable:
        status, value = "not_applicable", None
        reasons = tuple(replace(x, blocking=False) for x in reasons)
    elif constant:
        status = "supported"
        reasons = tuple(replace(x, blocking=False) for x in reasons)
    elif business:
        status, value = "undetermined", None
    elif unsupported:
        status, value = "unsupported", None
    elif supported:
        status = "supported"
    else:
        status, value = "undetermined", None
    if type(value) is Decimal:
        rendered = format(value, "f")
        value = rendered.rstrip("0").rstrip(".") if "." in rendered else rendered
    return freeze({"value": value, "status": status, "basis_type": "verified_subset" if subset else
                   "not_applicable" if not applicable else "complete_scope", "scope_ref": scope,
                   "coverage": coverage, "reasons": tuple(freeze(x) for x in reasons),
                   "basis_refs": tuple(sorted(set(basis_refs) | {ref for x in reasons for ref in x.basis_refs})),
                   "assurance_level": "synthetic_only", "formal_eligible": False})


def _outcome(prepared, **values):
    snapshot = prepared.snapshot
    data = {"operation": None if snapshot is None else snapshot.operation, "contract_version": V2,
            "input_manifest_ref": None if snapshot is None else snapshot.input_manifest_ref,
            "qualification_context_ref": None if snapshot is None else snapshot.qualification_context_ref,
            "business_cutoff": None if snapshot is None else snapshot.business_cutoff,
            "rule_binding": None if snapshot is None else snapshot.rule_binding,
            # Preserve the old business view / evidence locator. The snapshot's
            # raw_capture separately holds original type-sensitive records.
            "raw_capture": prepared.raw_capture, "wp1_report": prepared.wp1_report,
            "raw_capture_type_schema": "typed-raw-v1",
            "strict_raw_capture": None if snapshot is None else snapshot.raw_capture,
            "rejected_records": () if snapshot is None else snapshot.rejected_records,
            "localization_records": () if snapshot is None else snapshot.localization_records,
            "assurance_level": "synthetic_only", "formal_eligible": False,
            "capabilities": {"natural_days": True, "exclude_start": True,
                "contract_workdays": False, "special_contract_clock": False},
            "issues": prepared.issues, "physical_facts": None, "line": None, "portions": ()}
    data.update(values)
    data["qualification_issues"] = tuple((_BASIS_CAPTURE.get() or {}).get(("qualification_diagnostics",), ()))
    data["basis_catalog"] = _used_basis_catalog(data)
    return EvaluationOutcome(freeze(data))


def _check(prepared, operation):
    if type(prepared) is not PreparedQuantityInput or prepared._token is not _QUANTITY_PREPARATION_TOKEN:
        raise ValueError("unprepared_quantity_input")
    if prepared.rejection_code:
        return _outcome(prepared, result_status="rejected", rejection_code=prepared.rejection_code)
    if prepared.snapshot.operation != operation:
        return _outcome(prepared, result_status="rejected", rejection_code="quantity_operation_mismatch")
    try:
        unchanged = capture_same(tuple(capture_raw_types(x) for x in prepared.raw_sources), prepared.snapshot.raw_capture)
    except ValueError:
        unchanged = False
    if not unchanged:
        return _outcome(prepared, result_status="rejected", rejection_code="input_changed_after_preparation")
    return None


def _facts(prepared):
    s = prepared.snapshot
    result, issues = [], list(prepared.issues)
    by_source, by_id = {}, {}
    for slot in s.fact_slots:
        row, ref = slot.content, slot.ref
        valid = slot.accepted and f.fact_ref(ref)
        subject = ("delivery", row.get("delivery_id"), ref.source_event_key, ref.version) if valid else ()
        amount = None
        try:
            amount = exact_q(row.get("delivered_quantity", MISSING))
        except ValueError:
            pass
        q_ok = (valid and row.get("evidence_verified", False) is True and amount is not None and row.get("unit") == s.unit
                and _qualification(s, subject, "quantity", amount)[0] == "qualified"
                and _qualification(s, subject, "unit", row.get("unit"))[0] == "qualified")
        actual = row.get("actual_date")
        date_ok = (valid and type(actual) is date and _qualification(s, subject, "actual_date", actual,
                    row.get("actual_date_verified"))[0] == "qualified")
        membership = (row.get("order_id"), row.get("item_id"))
        member_ok = (valid and all(f.text(v) for v in membership)
                     and _qualification(s, subject, "membership", membership)[0] == "qualified")
        period = "post_cutoff" if date_ok and actual > s.business_cutoff else "current" if date_ok else "period_undetermined"
        graph = s.restriction_manifest
        if type(graph) is r.RestrictionManifest and type(graph.seeds) is tuple and valid:
            for seed in graph.seeds:
                if (type(seed) is r.RestrictionSeed and r.valid_node(seed.subject)
                        and type(seed.kind) is str and seed.subject == r.fact_node(ref)):
                    if seed.kind == "quantity_unverified":q_ok = False
                    if seed.kind == "membership_unverified":member_ok = False
                    if seed.kind == "actual_date_unverified":
                        date_ok, period = False, "period_undetermined"
        record = {"slot": slot, "ref": ref, "subject": subject, "amount": amount, "quantity_ok": q_ok,
                  "date_ok": date_ok, "membership_ok": member_ok, "period": period, "membership": membership,
                  "actual_date": actual, "valid": valid,
                  "basis": {name: _field_basis(s, subject, name, value, flag) for name, value, flag in
                     (("quantity", amount, row.get("evidence_verified") is True), ("unit", row.get("unit"), True),
                      ("actual_date", actual, row.get("actual_date_verified")), ("membership", membership, True))}}
        result.append(record)
        # Detect conflicting raw identity declarations even when sidecar
        # ambiguity has already prevented any one row from being accepted.
        if f.text(row.get("source_event_key")):
            by_source.setdefault(row["source_event_key"], []).append(record)
        if f.text(row.get("delivery_id")):
            by_id.setdefault(row["delivery_id"], []).append(record)
    for group in tuple(by_source.values()) + tuple(by_id.values()):
        if len(group) > 1:
            for item in group:
                item["valid"] = item["quantity_ok"] = item["date_ok"] = item["membership_ok"] = False
                item["period"] = "period_undetermined"
            issues.append(_issue("duplicate_delivery_fact", "input", tuple(x["ref"] for x in group), "static"))
    return result, issues


def _physical(prepared, facts):
    zero = Decimal(0)
    total = sum((d["amount"] for d in facts if d["quantity_ok"]), zero)
    by_date = {}
    for status, name in (("current", "on_or_before_cutoff"), ("post_cutoff", "after_cutoff"),
                         ("period_undetermined", "date_unverified")):
        rows = [d for d in facts if d["quantity_ok"] and d["period"] == status]
        q = sum((d["amount"] for d in rows), zero)
        known = sum((d["amount"] for d in rows if d["membership_ok"]), zero)
        by_date[name] = {"verified_quantity": str(q), "membership_identified_quantity": str(known),
                         "membership_pending_quantity": str(q - known)}
    known = sum((d["amount"] for d in facts if d["quantity_ok"] and d["membership_ok"]), zero)
    complete = _covered(prepared, ("facts",)) and all(d["quantity_ok"] for d in facts)
    basis = _rule_basis(prepared.snapshot, "quantity_rule_version") | _coverage_basis(prepared, ("facts",))
    for d in facts:
        if d["quantity_ok"]:
            basis.update(d["basis"]["quantity"] | d["basis"]["unit"])
    return freeze({"scope_level": "supplied_delivery_facts", "fact_collection_ref": prepared.snapshot.fact_collection_ref,
        "verified_received_quantity": _metric(total, supported=True, subset=True,
            scope=("facts",) + prepared.snapshot.fact_collection_ref + (prepared.snapshot.unit,),
            coverage="complete" if complete else "undetermined", basis_refs=basis),
        "membership_identified_quantity": str(known), "membership_pending_quantity": str(total - known),
        "by_date": by_date, "unverified_fact_refs": tuple(d["ref"] for d in facts if not d["quantity_ok"]),
        "declared_records": tuple({"ref": d["ref"], "quantity": d["slot"].content.get("delivered_quantity"),
                                    "period_status": d["period"]} for d in facts),
        "assurance_level": "synthetic_only", "formal_eligible": False})


@_collect_basis
def summarize_quantity_snapshot(prepared):
    rejected = _check(prepared, "facts_summary")
    if rejected is not None:
        return rejected
    with _precision(prepared):
        facts, issues = _facts(prepared)
        physical = _physical(prepared, facts)
    partial = bool(issues) or not _covered(prepared, ("facts",)) or any(
        not d["quantity_ok"] or not d["date_ok"] or not d["membership_ok"] for d in facts)
    return _outcome(prepared, result_status="partial" if partial else "supported", physical_facts=physical, issues=tuple(issues))


def _precision(prepared):
    context = localcontext()
    # Exact rational arithmetic within the approved bounded scalar domain.
    ctx = context.__enter__()
    ctx.prec = 1024
    class Scope:
        def __enter__(self):
            return ctx
        def __exit__(self, *args):
            return context.__exit__(*args)
    return Scope()


def _portions(s):
    result = {}
    for slot in s.portion_slots or ():
        row, ref = slot.content, slot.ref
        if not f.strings(ref, 5):
            continue
        valid = slot.accepted and f.strings(ref, 5)
        subject = ("portion", row.get("portion_id"), row.get("portion_id"), ref[4]) if valid else ()
        amount = None
        try:
            amount = exact_q(row.get("effective_quantity", MISSING))
        except ValueError:
            pass
        commit = row.get("commitment_date")
        commit_ok = (type(commit) is date and _qualification(s, subject, "commitment_date", commit,
                      row.get("commitment_date_verified"))[0] == "qualified")
        eligible = (valid and ref[:3] == s.target_scope and amount is not None and row.get("evidence_verified") is True
                    and row.get("calculation_eligible") is True and commit_ok and commit <= s.business_cutoff
                    and _qualification(s, subject, "effective_quantity", amount)[0] == "qualified")
        info = {"slot": slot, "ref": ref, "subject": subject, "amount": amount, "eligible": eligible,
                "future": valid and commit_ok and commit > s.business_cutoff, "commitment_date": commit,
                "reserved": Decimal(0), "assigned": Decimal(0), "reasons": [],
                "basis": _field_basis(s, subject, "effective_quantity", amount, row.get("evidence_verified") is True)
                         | _field_basis(s, subject, "commitment_date", commit, row.get("commitment_date_verified"))}
        if ref in result:
            result[ref]["eligible"] = False
            result[ref]["reasons"].append(_issue("duplicate_portion", "input", (ref,), "static"))
        else:
            result[ref] = info
    return result


def _node_fact(node):
    return f.FactRef(*node.identity[:2]) if r.valid_node(node) and node.kind in ("fact", "fragment", "group") else None


def _copy_binding_conflicts(s):
    """Compare actual current content per parent; no copy is authoritative by vote."""
    manifest, graph = s.fragment_manifest, s.restriction_manifest
    if type(manifest) is not f.FragmentManifest or type(graph) is not r.RestrictionManifest or type(graph.fragments) is not f.FragmentManifest:
        return {}, {}
    other = graph.fragments
    parents, keys = {}, {}

    def equivalent(left, right):
        left, right = tuple(freeze(x) for x in left), tuple(freeze(x) for x in right)
        return same(tuple(sorted(left, key=repr)), tuple(sorted(right, key=repr)))

    refs = {x.ref for source in (manifest, other) for x in source.facts if type(x) is f.ParentFact and f.fact_ref(x.ref)}
    for ref in refs:
        if (not same(freeze(manifest.context), freeze(other.context)) or not equivalent(
                [x for x in manifest.facts if type(x) is f.ParentFact and f.fact_ref(x.ref) and x.ref == ref],
                [x for x in other.facts if type(x) is f.ParentFact and f.fact_ref(x.ref) and x.ref == ref])):
            parents[ref] = _issue("graph_parent_content_binding_conflict", "input", (ref,), "static")
        for name in ("definitions", "partition_bases", "active_relations"):
            def parent(row):
                if type(row) is f.Fragment and f.fragment_key(row.key): return row.key.parent_fact_ref
                if type(row) is f.PartitionBasis and f.fact_ref(row.parent_fact_ref): return row.parent_fact_ref
                if type(row) is f.EffectiveRelation and f.fragment_key(row.fragment): return row.fragment.parent_fact_ref
                return None
            left = [x for x in getattr(manifest, name) if parent(x) == ref]
            right = [x for x in getattr(other, name) if parent(x) == ref]
            if not equivalent(left, right):
                for row in left + right:
                    key = row.key if type(row) is f.Fragment else row.fragment if type(row) is f.EffectiveRelation else None
                    if f.fragment_key(key):
                        keys[key] = _issue("graph_current_content_binding_conflict", "input", (key,), "static")
                if name == "partition_bases":
                    parents[ref] = _issue("graph_partition_binding_conflict", "input", (ref,), "static")
    return parents, keys


def _period_only(origins, fact_map):
    return bool(origins) and all(
        origin.namespace == "input_seed" and origin.seed.kind in (
            "quantity_unverified", "actual_date_unverified", "membership_unverified", "allocation_pending",
            "allocation_disputed", "awaiting_recovery", "time_conflict", "commitment_time_unverified")
        and _node_fact(origin.seed.subject) in fact_map
        and fact_map[_node_fact(origin.seed.subject)]["period"] == "post_cutoff" for origin in origins)


def _calendar_complete(s):
    cal = s.rule_binding.get("calendar_content")
    if type(cal) is not FrozenContent or not f.strings(s.rule_binding.get("calendar_ref"), 2):
        return False
    start, end, days = cal.get("valid_from"), cal.get("valid_to"), cal.get("days")
    if (not f.strings(cal.get("ref"), 2) or cal.get("ref") != s.rule_binding["calendar_ref"] or type(start) is not date or type(end) is not date
            or start > end or type(days) is not tuple or len(days) != (end - start).days + 1):
        return False
    if not all(type(x) is tuple and len(x) == 2 and type(x[0]) is date and type(x[1]) is bool and start <= x[0] <= end for x in days):
        return False
    return len({x[0] for x in days}) == len(days) and _qualification(s, ("calendar",), "calendar_content", cal)[0] == "qualified"


@_collect_basis
def evaluate_quantity_snapshot(prepared):
    rejected = _check(prepared, "order_item")
    if rejected is not None:
        return rejected
    with _precision(prepared):
        return _evaluate(prepared)


def _evaluate(prepared):
    s, zero = prepared.snapshot, Decimal(0)
    facts, issues = _facts(prepared)
    fact_map = {d["ref"]: d for d in facts if d["valid"]}
    portions = _portions(s)
    graph = s.restriction_manifest
    graph_result = r.map_restrictions(graph) if type(graph) is r.RestrictionManifest else None
    node_rows = {} if graph_result is None else {x.node: x for x in graph_result.node_restrictions}
    validation = None if graph_result is None else graph_result.fragment_validation
    traces = {} if graph_result is None else {(x.node, x.metric, x.reason_id): x for x in graph_result.causal_trace}
    closures = {} if graph_result is None else {x.node: x for x in graph_result.closure_trace}
    pids = {p["slot"].content.get("portion_id"): ref for ref, p in portions.items()}
    atoms, conditional, checks, relation_rows = [], [], [], {}
    line_reasons = []
    parent_conflicts, fragment_conflicts = _copy_binding_conflicts(s)
    issues.extend(tuple(parent_conflicts[x] for x in sorted(parent_conflicts)) +
                  tuple(fragment_conflicts[x] for x in sorted(fragment_conflicts)))

    # Scope-independent original number/range checks precede period projection.
    for d in facts:
        related = [a for a in s.relation_slots or () if a.content.get("delivery_id") == d["slot"].content.get("delivery_id")]
        try:
            amounts = [exact_q(a.content.get("allocated_quantity", MISSING)) for a in related]
            if d["amount"] is not None and (sum(amounts, zero) > d["amount"] or any(
                    a.content.get("delivery_offset") is not None and exact_q(a.content["delivery_offset"]) + amount > d["amount"]
                    for a, amount in zip(related, amounts))):
                error = _issue("allocation_exceeds_delivery", "input", (d["ref"],), "static")
                issues.append(error)
                d["allocation_error"] = error
        except ValueError:
            pass

    def restrict(domain, reason):
        for ref in domain:
            if ref in portions:
                portions[ref]["reasons"].append(reason)

    # All effective relationship definitions are retained, not selected by order.
    for slot in s.relation_slots or ():
        if type(slot.ref) is tuple and len(slot.ref) == 3 and f.fragment_key(slot.ref[2]):
            relation_rows.setdefault(slot.ref[2], []).append(slot)

    for d in facts:
        ref, row = d["ref"], d["slot"].content
        raw_candidates = row.get("candidate_portion_ids", ())
        supplied, unresolved = [], set()
        original_row = prepared.raw_sources[0]["deliveries"][d["slot"].source_index]
        original_candidates = original_row.get("candidate_portion_ids", ()) if type(original_row) is dict else MISSING
        if type(original_candidates) is tuple and type(raw_candidates) is tuple:
            for index, candidate in enumerate(raw_candidates):
                if type(candidate) is str and candidate in pids:
                    supplied.append(pids[candidate])
                else:
                    diagnostic = (("unresolved_candidate", candidate) if type(candidate) is str else
                                  ("invalid_candidate", row.get("delivery_id"), str(index)))
                    supplied.append(diagnostic)
                    unresolved.add(diagnostic)
        else:
            diagnostic = ("invalid_candidate_scope", row.get("delivery_id"))
            supplied.append(diagnostic)
            unresolved.add(diagnostic)
        if unresolved:
            issues.append(_issue("unknown_candidate_reference", "input", tuple(sorted(unresolved)), "capacity"))
        d["unresolved_candidate_refs"] = tuple(sorted(unresolved))
        supplied = tuple(supplied)
        if type(original_candidates) is tuple and not raw_candidates:
            supplied = tuple(portions)
        original_fact_targets = set()
        for link in s.relation_slots or ():
            if link.content.get("delivery_id") == row.get("delivery_id") and link.content.get("portion_id") in pids:
                original_fact_targets.add(pids[link.content["portion_id"]])
        if d["period"] == "post_cutoff":
            checks.append({"kind": "period_exclusion", "fact_ref": ref, "quantity": d["amount"],
                           "capacity_status": "feasible", "demand_period_status": "complete",
                           "applicability": "excluded", "reason": "reliable_post_cutoff", "original_domain": supplied})
            continue
        belongs = d["membership_ok"] and d["membership"] == s.target_scope[:2]
        if not d["quantity_ok"] or d["period"] != "current" or not belongs:
            if d["membership_ok"] and d["membership"] != s.target_scope[:2]:
                continue
            reason = _issue("quantity_unverified" if not d["quantity_ok"] else "actual_date_unverified"
                            if d["period"] != "current" else "membership_unverified", "evidence", (ref,), "period")
            conditional_domain = tuple(sorted(set(supplied) | original_fact_targets))
            conditional.append({"fact_ref": ref, "quantity": d["amount"] if d["quantity_ok"] else None,
                                "domain": conditional_domain, "reason": reason})
            restrict(conditional_domain, reason)
            line_reasons.append(reason)
            continue
        definitions = [] if type(s.fragment_manifest) is not f.FragmentManifest else [x for x in s.fragment_manifest.definitions
                         if type(x) is f.Fragment and f.fragment_key(x.key) and x.key.parent_fact_ref == ref]
        good_keys = set(()) if validation is None else set(validation.structurally_valid_keys)
        candidates = [x for x in definitions if x.key in good_keys]
        parents = [] if type(s.fragment_manifest) is not f.FragmentManifest else [p for p in s.fragment_manifest.facts
                   if type(p) is f.ParentFact and f.fact_ref(p.ref) and p.ref == ref]
        try:
            parent_ok = (len(parents) == 1 and f.text(parents[0].delivery_id) and parents[0].delivery_id == row.get("delivery_id")
                         and f.text(parents[0].unit) and parents[0].unit == s.unit and exact_q(parents[0].quantity) == d["amount"])
        except ValueError:
            parent_ok = False
        if not parent_ok:
            issues.append(_issue("parent_content_binding_conflict", "input", (ref,), "static"))
            candidates = []
        if d.get("allocation_error"):
            candidates = []
        represented = zero
        for fragment in candidates:
            q = exact_q(fragment.quantity)
            represented += q
            links = relation_rows.get(fragment.key, ())
            effective = [a for a in s.fragment_manifest.active_relations if type(a) is f.EffectiveRelation
                         and f.fragment_key(a.fragment) and a.fragment == fragment.key]
            link = links[0] if len(links) == 1 else None
            target = effective[0].target_ref if len(effective) == 1 and f.strings(effective[0].target_ref, 5) else None
            original = {target} if target is not None else set()
            if link is not None and type(link.content.get("portion_id")) is str and link.content["portion_id"] in pids:
                original.add(pids[link.content["portion_id"]])
            relation_ok = (link is not None and link.accepted and link.content.get("evidence_verified") is True
                           and _qualification(s, ("relation",) + link.ref[:2] + (ref.source_event_key,),
                               "relation_content", freeze({"record": link.content, "key": freeze(fragment.key), "target": target}))[0] == "qualified")
            domain = set(supplied) | original
            if type(graph) is r.RestrictionManifest:
                scopes = [scope for scope in graph.scopes if type(scope) is r.ImpactScope
                          and r.valid_node(scope.subject) and scope.subject == r.fragment_node(fragment.key)]
                # A separately proven usable/recovery segment may have its own
                # scope; parent background candidates are not unsolved targets.
                # Pending/disputed segments ALWAYS keep the original union.
                if relation_ok and link.content.get("status") in ("usable", "awaiting_recovery") and len(scopes) == 1:
                    scope = scopes[0]
                    valid_scope = (r.fragment_node(fragment.key) in node_rows and not any(
                        x.code in ("impact_scope_unproven", "protection_basis_unproven") and scope.subject in x.subjects
                        for x in graph_result.issues))
                    if valid_scope:
                        domain = set(original) | unresolved
                for scope in scopes:
                    if all(type(x) is tuple for x in (scope.candidate_targets, scope.original_targets, scope.possible_targets)):
                        domain.update(n.identity for n in scope.candidate_targets + scope.original_targets + scope.possible_targets
                                      if r.valid_node(n) and n.kind == "portion")
            atom = {"ref": fragment.key, "parent": ref, "quantity": q, "domain": domain,
                    "target": target, "status": "pending" if link is None else link.content.get("status"),
                    "class": None, "reasons": [], "link": link,
                    "basis": set().union(*d["basis"].values())}
            if link is not None:
                atom["basis"].update(_field_basis(s, ("relation",) + link.ref[:2] + (ref.source_event_key,),
                    "relation_content", freeze({"record": link.content, "key": freeze(fragment.key), "target": target})))
            if ref in parent_conflicts:
                atom["reasons"].append(parent_conflicts[ref])
            if fragment.key in fragment_conflicts:
                atom["reasons"].append(fragment_conflicts[fragment.key])
            if link is not None and (target != pids.get(link.content.get("portion_id"))
                    or len(effective) != 1 or not f.text(effective[0].relation_id)
                    or type(effective[0].version) is not str or effective[0].version != link.ref[1]
                    or link.content.get("delivery_id") != row.get("delivery_id")):
                atom["reasons"].append(_issue("effective_relation_binding_conflict", "input", (fragment.key,), "static"))
            node_result = node_rows.get(r.fragment_node(fragment.key))
            if node_result is not None and (node_result.state == "scope_unproven" or any(
                    metric in ("calculation_inclusion", "allocation_use") for metric, _ in node_result.blocked)):
                atom["reasons"].append(_issue("range_dependency_restriction", "evidence", (fragment.key,)))
            if (r.fragment_node(fragment.key) not in node_rows or len(links) > 1 or len(effective) > 1
                    or link is not None and (not link.accepted or target not in portions
                    or link.content.get("delivery_id") != row.get("delivery_id")
                    or exact_q(link.content.get("allocated_quantity", "0")) != q
                    or link.content.get("delivery_offset") is None
                    or exact_q(link.content["delivery_offset"]) != exact_q(fragment.start))):
                atom["reasons"].append(_issue("allocation_content_or_structure_unproven", "input", (fragment.key,), "static"))
            if any(p not in portions or not portions[p]["eligible"] for p in domain):
                atom["reasons"].append(_issue("portion_basis_unverified", "evidence", tuple(domain), "period"))
            for p in domain:
                if p in portions:
                    commit = portions[p]["commitment_date"]
                    if type(commit) is date and portions[p]["eligible"]:
                        if d["actual_date"] < commit:
                            atom["reasons"].append(_issue("delivery_before_commitment", "input", (fragment.key, p), "period"))
                        elif d["actual_date"] == commit:
                            atom["reasons"].append(_issue("same_day_correspondence_policy_pending", "policy", (fragment.key, p), "period"))
            if atom["status"] not in ("usable", "pending", "disputed", "awaiting_recovery"):
                atom["reasons"].append(_issue("unknown_allocation_status", "input", (fragment.key,), "static"))
            if not atom["reasons"] and relation_ok and atom["status"] in ("usable", "awaiting_recovery"):
                atom["class"] = "Cc" if atom["status"] == "usable" else "Rr"
                portions[target]["reserved"] += q
                if atom["class"] == "Cc":
                    portions[target]["assigned"] += q
            atoms.append(atom)
        residual = d["amount"] - represented
        if residual > 0:
            # A blocked mathematical remainder is not a fabricated fragment.
            atoms.append({"ref": ("parent_residual", ref), "parent": ref, "quantity": residual,
                          "domain": set(supplied) | original_fact_targets, "target": None, "status": "pending", "class": None,
                          "reasons": [_issue("partition_scope_unproven", "evidence", (ref,), "static")], "link": None,
                          "basis": set().union(*d["basis"].values())})
        elif residual < 0:
            issues.append(_issue("allocation_exceeds_delivery", "input", (ref,), "static"))

    # Reliable reservations must be checked even in the presence of conditional facts.
    for ref, p in portions.items():
        if p["eligible"] and p["reserved"] > p["amount"]:
            reason = _issue("allocation_exceeds_portion", "input", (ref,), "capacity")
            p["reasons"].append(reason)
            line_reasons.append(reason)
            issues.append(reason)
            for atom in atoms:
                if atom["target"] == ref and atom["class"] in ("Cc", "Rr"):
                    atom["class"] = "Z"
                    atom["reasons"].append(reason)
            p["assigned"] = p["reserved"] = zero

    demands = [a for a in atoms if a["class"] not in ("Cc", "Rr")]
    # Connectivity includes unknown capacities/periods, not only solver edges.
    nodes = [("d", i, set(a["domain"])) for i, a in enumerate(demands)] + [("u", i, set(a["domain"])) for i, a in enumerate(conditional)]
    components = []
    while nodes:
        member = [nodes.pop(0)]
        domain = set(member[0][2])
        changed = True
        while changed:
            changed = False
            for item in tuple(nodes):
                if domain & item[2]:
                    member.append(item)
                    domain.update(item[2])
                    nodes.remove(item)
                    changed = True
        components.append((member, domain))
    for members, domain in components:
        current = [demands[i] for kind, i, _ in members if kind == "d"]
        unknown = [conditional[i] for kind, i, _ in members if kind == "u"]
        capacities = {p: portions[p]["amount"] - portions[p]["reserved"] for p in domain
                      if p in portions and portions[p]["eligible"]}
        closed = [a for a in current if a["domain"] and a["domain"] <= capacities.keys()]
        violation = not _pending_quantities_fit(capacities, [(a["quantity"], a["domain"]) for a in closed])
        undecided = bool(unknown) or any(p not in capacities for p in domain) or any(not a["domain"] for a in current)
        verdict = "infeasible" if violation else "undetermined" if undecided else "feasible"
        reliable_violations = [reason for atom in current for reason in atom["reasons"]
                               if reason.code == "allocation_exceeds_portion"]
        only_failed_reliable = bool(current) and all(a["status"] in ("usable", "awaiting_recovery") for a in current)
        reason = (reliable_violations[0] if violation and only_failed_reliable and reliable_violations else
                  _issue("pending_scope_capacity_insufficient" if violation else "pending_scope_capacity_undetermined",
                         "capacity", tuple(sorted(domain)), "capacity"))
        checks.append({"kind": "shared_capacity", "capacity_status": verdict,
                       "demand_period_status": "undetermined" if unknown else "complete",
                       "domain": tuple(sorted(domain)), "demands": tuple((a["ref"], a["quantity"], tuple(sorted(a["domain"]))) for a in current),
                       "conditional_demands": tuple((a["fact_ref"], a["quantity"], a["domain"]) for a in unknown),
                       "violation_witnesses": tuple((a["ref"], a["quantity"], tuple(sorted(a["domain"]))) for a in closed) if violation else (),
                       "capacities": tuple(sorted(capacities.items())),
                       "unresolved_capacity_refs": tuple(sorted(p for p in domain if p not in capacities)),
                       "capacity_coverage": "undetermined" if any(p not in capacities for p in domain) else "complete",
                       "basis_refs": tuple(sorted(set().union(*(a["basis"] for a in current),
                           *(portions[p]["basis"] for p in domain if p in portions),
                           *(set().union(*fact_map[a["fact_ref"]]["basis"].values()) for a in unknown if a["fact_ref"] in fact_map),
                           _graph_basis(s, graph_result, domain), _rule_basis(s, "quantity_rule_version"))))})
        if verdict != "feasible":
            line_reasons.append(reason)
            restrict(domain, reason)
        for atom in current:
            if atom["class"] != "Z":
                atom["class"] = "Ep" if verdict == "feasible" and not atom["reasons"] else "Z"
            if verdict != "feasible":
                atom["reasons"].append(reason)

    for atom in atoms:
        atom["class"] = atom["class"] or "Z"
        if atom["class"] != "Cc":
            reason = _issue("awaiting_recovery" if atom["class"] == "Rr" else "allocation_" + atom["status"]
                            if atom["status"] in ("pending", "disputed") else "allocation_unqualified",
                            "workflow", (atom["ref"],))
            restrict(atom["domain"], reason)
        if atom["class"] == "Z":
            line_reasons.extend(atom["reasons"] or (_issue("calculation_inclusion_unproven", "evidence", (atom["ref"],)),))
            restrict(atom["domain"], atom["reasons"][0] if atom["reasons"] else _issue("calculation_inclusion_unproven", "evidence", (atom["ref"],)))

    # Consume each WP-2 metric separately; unrestricted is not positive eligibility.
    metric_blocks = {}
    for ref, p in portions.items():
        node = r.Node("portion", ref)
        row = node_rows.get(node)
        blocks = {}
        for d in facts:
            if d.get("unresolved_candidate_refs") and d["period"] != "post_cutoff":
                closure = closures.get(node)
                excluded = (closure is not None and closure.passed and closure.proof_binding_valid and closure.exclusions_valid
                            and f.fact_ref(d["ref"]) and any(r.fact_node(d["ref"]) in row.excluded_subjects
                                for row in closure.declared_closures))
                if not excluded:
                    p["reasons"].append(_issue("unknown_candidate_independence_unproven", "evidence", (d["ref"],ref)))
        if row is None:
            p["reasons"].append(_issue("portion_graph_coverage_unproven", "evidence", (ref,)))
        else:
            for metric, ids in row.blocked:
                active = [reason for reason in ids if not _period_only(traces.get((node, metric, reason)).origins
                          if (node, metric, reason) in traces else (), fact_map)]
                if active:
                    blocks[metric] = tuple(active)
            if row.state == "scope_unproven":
                trace = closures.get(node)
                solely_post = (trace is not None and trace.unresolved_sources and all(
                    _node_fact(n) in fact_map and fact_map[_node_fact(n)]["period"] == "post_cutoff"
                    for n in trace.unresolved_sources) and trace.proof_binding_valid and trace.exclusions_valid
                    and _covered(prepared, ("portion",) + ref))
                if not solely_post:
                    p["reasons"].append(_issue("portion_independence_unproven", "evidence", (ref,)))
            if "line_total" in blocks:
                line_reasons.append(_issue("line_dependency_restriction", "evidence", (ref,)))
        metric_blocks[ref] = blocks

    total = sum((d["amount"] for d in facts if d["quantity_ok"] and d["period"] == "current"
                 and d["membership_ok"] and d["membership"] == s.target_scope[:2]), zero)
    buckets = {name: sum((a["quantity"] for a in atoms if a["class"] == name), zero) for name in ("Cc", "Rr", "Ep", "Z")}
    w = buckets["Cc"] + buckets["Rr"] + buckets["Ep"]
    if total != w + buckets["Z"]:
        line_reasons.append(_issue("quantity_partition_not_conserved", "input", phase="static"))
    scope_complete = _covered(prepared, ("line",) + s.target_scope)
    raw = prepared.raw_sources[0]
    if raw.get("delivery_scope_complete") is not True or raw.get("commitment_scope_complete") is not True or not scope_complete:
        line_reasons.append(_issue("line_coverage_unproven", "evidence", s.target_scope))
    if len(portions) != len(s.portion_slots or ()) or any(not p["eligible"] and not p["future"] for p in portions.values()):
        line_reasons.append(_issue("commitment_scope_unproven", "evidence"))
    q = sum((p["amount"] for p in portions.values() if p["eligible"]), zero)
    if q < total:
        line_reasons.append(_issue("delivery_exceeds_effective_commitment", "input", phase="capacity"))
    line_value = q - w
    rules_basis = _rule_basis(s, "quantity_rule_version")
    receipt_basis = rules_basis | _coverage_basis(prepared, ("facts",))
    for d in facts:
        for field in ("quantity", "unit", "actual_date", "membership"):
            receipt_basis.update(d["basis"][field])
    line_basis = receipt_basis | _coverage_basis(prepared, ("line",) + s.target_scope)
    for p in portions.values(): line_basis.update(p["basis"])
    for atom in atoms: line_basis.update(atom["basis"])
    for check in checks: line_basis.update(check.get("basis_refs", ()))
    line_basis.update(_graph_basis(s, graph_result, portions))
    t_complete = scope_complete and _covered(prepared, ("facts",)) and all(
        d["period"] == "post_cutoff" or d["membership_ok"] and d["membership"] != s.target_scope[:2]
        or d["quantity_ok"] and d["period"] == "current" and d["membership_ok"] for d in facts)
    quantity_coverage = "complete" if t_complete and not buckets["Z"] else "undetermined"
    line_metric = _metric(line_value, supported=True, reasons=line_reasons, scope=s.target_scope,
                          coverage="complete" if scope_complete and not line_reasons else "undetermined", basis_refs=line_basis)
    arrival = total > 0
    arrival_metric = _metric(arrival, constant=arrival or scope_complete and not conditional,
                            supported=False, reasons=() if arrival else line_reasons,
                            scope=s.target_scope, coverage="complete" if t_complete else "undetermined", basis_refs=receipt_basis)
    output_portions = []
    for ref, p in portions.items():
        if p["future"]:
            continue
        reasons = list(p["reasons"])
        if not p["eligible"]:
            reasons.append(_issue("portion_basis_unverified", "evidence", (ref,)))
        portion_covered = _covered(prepared, ("portion",) + ref)
        if not portion_covered:
            reasons.append(_issue("portion_coverage_unproven", "evidence", (ref,)))
        if "portion_balance" in metric_blocks[ref]:
            reasons.append(_issue("dependency_restriction", "evidence", (ref,)))
        remaining = None if p["amount"] is None else p["amount"] - p["assigned"]
        basis = p["basis"] | rules_basis | _coverage_basis(prepared, ("portion",) + ref) | _graph_basis(s, graph_result, (ref,))
        for atom in atoms:
            if ref in atom["domain"]: basis.update(atom["basis"])
        for check in checks:
            if ref in check.get("domain", ()): basis.update(check.get("basis_refs", ()))
        coverage = "complete" if portion_covered and not reasons else "undetermined"
        balance = _metric(remaining, supported=True, reasons=reasons, scope=ref, coverage=coverage, basis_refs=basis)
        known = balance["status"] == "supported"
        empty = known and remaining == 0
        age_unsupported = s.rule_binding.get("age_rule_version") != RULES["age_rule_version"] or s.rule_binding.get("first_day_rule") != "exclude_start"
        age_reasons = reasons + ([_issue("special_age_rule_not_implemented", "capability", (ref,))] if age_unsupported else [])
        if "age_days" in metric_blocks[ref]:
            age_reasons.append(_issue("age_dependency_restriction", "evidence", (ref,)))
        age = _metric((s.business_cutoff - p["commitment_date"]).days if known and not empty else None,
                      applicable=not empty, supported=known, unsupported=age_unsupported, reasons=age_reasons, scope=ref,
                      coverage=coverage, basis_refs=basis | _rule_basis(s, "age_rule_version", "first_day_rule"))
        row = p["slot"].content
        due = row.get("due_date")
        overdue_reasons = list(reasons)
        due_ok = type(due) is date and _qualification(s, p["subject"], "due_date", due)[0] == "qualified"
        mode = row.get("day_basis")
        mode_ok = _qualification(s, p["subject"], "day_basis", mode)[0] == "qualified"
        calendar_ok = _calendar_complete(s)
        workdays = mode == "contract_workdays" and type(mode) is str
        if not due_ok:
            overdue_reasons.append(_issue("due_date_basis_missing", "evidence", (ref,)))
        if not mode_ok:
            overdue_reasons.append(_issue("day_basis_unverified", "evidence", (ref,)))
        if workdays and not calendar_ok:
            overdue_reasons.append(_issue("contract_calendar_basis_missing", "evidence", (ref,)))
        unsupported = workdays or s.rule_binding.get("overdue_rule_version") != RULES["overdue_rule_version"] or s.rule_binding.get("first_day_rule") != "exclude_start"
        if unsupported:
            overdue_reasons.append(_issue("contract_calendar_calculation_not_implemented" if workdays else "special_counting_rule_not_implemented", "capability", (ref,)))
        days = max(0, (s.business_cutoff - due).days) if due_ok else None
        overdue_basis = (basis | _rule_basis(s, "overdue_rule_version", "first_day_rule")
                         | _field_basis(s, p["subject"], "due_date", due) | _field_basis(s, p["subject"], "day_basis", mode))
        if workdays and calendar_ok:
            overdue_basis.update(_field_basis(s, ("calendar",), "calendar_content", s.rule_binding.get("calendar_content")))
        q_reasons = overdue_reasons + ([_issue("overdue_quantity_dependency_restriction", "evidence", (ref,))] if "overdue_quantity" in metric_blocks[ref] else [])
        days_reasons = overdue_reasons + ([_issue("overdue_days_dependency_restriction", "evidence", (ref,))] if "overdue_days" in metric_blocks[ref] else [])
        over_q = _metric(zero if empty else remaining if days is not None and days > 0 else zero,
                         constant=empty, supported=known and due_ok and mode_ok, unsupported=unsupported,
                         reasons=q_reasons, scope=ref, coverage=coverage, basis_refs=overdue_basis)
        over_days = _metric(days, applicable=not empty, supported=known and due_ok and mode_ok, unsupported=unsupported,
                            reasons=days_reasons, scope=ref, coverage=coverage, basis_refs=overdue_basis)
        output_portions.append({"portion_ref": ref, "state": "可支持" if known else "不可确定",
            "remaining_quantity": balance, "age_days": age, "overdue_quantity": over_q, "overdue_days": over_days})
    vector = {"F": _physical(prepared, facts)["verified_received_quantity"],
              "T": _metric(total, supported=True, subset=True, scope=("line",) + s.target_scope,
                           coverage="complete" if t_complete else "undetermined", basis_refs=receipt_basis),
              "W": _metric(w, supported=True, subset=True, scope=("line",) + s.target_scope,
                           coverage=quantity_coverage, basis_refs=line_basis)}
    vector.update({name: _metric(value, supported=True, subset=True, scope=("line",) + s.target_scope,
                               coverage=quantity_coverage, basis_refs=line_basis) for name, value in buckets.items()})
    vector["Pp"] = _metric(buckets["Ep"] + buckets["Z"], supported=True, subset=True,
                          scope=("line",) + s.target_scope, coverage=quantity_coverage, basis_refs=line_basis)
    vector["verified_assigned_quantity"] = _metric(buckets["Cc"] + buckets["Rr"], supported=True, subset=True,
                          scope=("line",) + s.target_scope, coverage=quantity_coverage, basis_refs=line_basis)
    # Versioned vocabulary aliases reference the SAME result, not extra counts.
    for alias, key in (("verified_delivery_quantity", "T"), ("calculation_included_quantity", "W"),
                       ("calculable_allocated_quantity", "Cc"), ("awaiting_recovery_quantity", "Rr"),
                       ("allocation_pending_quantity", "Pp")):
        vector[alias] = vector[key]
    vector.update({"effective_commitment_quantity": _metric(q, supported=True, subset=True, scope=s.target_scope,
                       coverage="complete" if raw.get("commitment_scope_complete") is True and scope_complete
                           and not any(x.code == "commitment_scope_unproven" for x in line_reasons) else "undetermined",
                       basis_refs=set().union(*(p["basis"] for p in portions.values()), rules_basis,
                                              _coverage_basis(prepared, ("line",) + s.target_scope)),
                       reasons=tuple(x for x in line_reasons if x.code == "commitment_scope_unproven")),
                   "remaining_quantity": line_metric, "has_verified_arrival": arrival_metric,
                   "line_total_status": "supported" if line_metric["status"] == "supported" else "undetermined",
                   "line_total_reasons": () if line_metric["status"] == "supported" else tuple(line_reasons)})
    metrics = (line_metric, arrival_metric) + tuple(row[name] for row in output_portions for name in
                          ("remaining_quantity", "age_days", "overdue_quantity", "overdue_days"))
    partial = bool(issues) or any(m["status"] not in ("supported", "not_applicable") for m in metrics)
    return _outcome(prepared, result_status="partial" if partial else "supported", physical_facts=_physical(prepared, facts),
        line=vector, portions=tuple(output_portions), issues=tuple(issues), capacity_checks=tuple(checks),
        quantity_ranges=tuple({k: tuple(sorted(v)) if type(v) is set else v for k, v in a.items() if k != "link"} for a in atoms),
        supplied_graph=freeze(graph), restriction_result=freeze(graph_result),
        historical_relations=() if type(s.fragment_manifest) is not f.FragmentManifest else s.fragment_manifest.history_relations)
