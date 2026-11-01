"""WP-1: non-coercing candidate input boundary; no V2 quantity computation.

This module has no database, clock, source-service or permission dependencies.
Binding consistency is necessary, but is never proof of source authenticity.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation


class _Missing:
    def __repr__(self):
        return "MISSING"

    def __bool__(self):
        raise TypeError("missing_has_no_truth_value")


MISSING = _Missing()
V2 = "b002-quantity-v2-candidate"
V1 = "b002-quantity-v1"
ENTRY_POINTS = ("evaluate_delivery_scope", "summarize_delivery_facts")


@dataclass(frozen=True)
class FieldObservation:
    path: str
    presence: str
    raw_type: str


@dataclass(frozen=True)
class InputIssue:
    code: str
    path: str
    presence: str
    raw_type: str
    category: str
    record_ref: tuple = ()  # Declared references, NOT verified business identity.
    fatal: bool = False
    localization_status: str = "unproven"
    localization_basis_refs: tuple = ()
    localization_reason: str = "business_scope_resolution_not_implemented"


@dataclass
class ValidationReport:
    request_issues: list = field(default_factory=list)
    record_issues: list = field(default_factory=list)
    observations: list = field(default_factory=list)
    date_qualifications: dict = field(default_factory=dict)

    @property
    def root_valid(self):
        return not any(issue.fatal for issue in self.request_issues)

    @property
    def types_and_values_valid(self):
        return not self.request_issues and not self.record_issues


class ContractError(ValueError):
    def __init__(self, code, report):
        super().__init__(code)
        self.code, self.report = code, report


class QuantityContractNotReady(ContractError):
    """Capability gate, not an A-class classification of the business data."""

    def __init__(self, report):
        super().__init__("quantity_contract_not_ready", report)


def _observe(path, value, *, provided=MISSING):
    presence = ("present" if provided is True else "missing") if value is MISSING else (
        "null" if value is None else "present")
    return FieldObservation(path, presence, "MISSING" if value is MISSING else type(value).__name__)


def _issue(report, code, path, value, *, record_ref=None, fatal=False, category="field_type", provided=MISSING):
    observed = _observe(path, value, provided=provided)
    issue = InputIssue(code, path, observed.presence, observed.raw_type, category,
                       () if record_ref is None else record_ref, fatal)
    (report.request_issues if record_ref is None else report.record_issues).append(issue)


def _text(value):
    return type(value) is str and len(value.strip()) > 0


def _subject_reference(value):
    # Both sides must have exact built-in types before identity comparison.
    return type(value) is tuple and len(value) == 4 and all(_text(part) for part in value)


def _version_and_context(data, report):
    version = data.get("contract_version", MISSING)
    report.observations.append(_observe("contract_version", version))
    if version is MISSING:
        code = "missing_request_contract"
    elif not _text(version):
        code = "invalid_request_contract"
    elif version == V1:
        code = "legacy_quantity_calculation_disabled"
    elif version != V2:
        code = "unsupported_request_contract"
    else:
        code = None
    if code is not None:
        _issue(report, code, "contract_version", version, fatal=True, category="request_contract")
        return
    context = data.get("contract_context", MISSING)
    report.observations.append(_observe("contract_context", context))
    if context is MISSING:
        code = "missing_contract_context"
    elif type(context) is not dict or not all(_text(context.get(key, MISSING)) for key in
            ("contract_version", "input_manifest_ref", "qualification_context_ref")):
        code = "invalid_contract_context"
    elif context["contract_version"] != version:
        code = "contract_context_version_mismatch"
    else:
        code = None
    if code is not None:
        _issue(report, code, "contract_context", context, fatal=True, category="request_contract")


# Defaults are applied only AFTER raw validation. Explicit None is never omitted.
SCHEMAS = {
    "portions": {
        "required": ("portion_id", "order_id", "item_id", "unit", "effective_quantity",
                     "commitment_date", "due_date"),
        "defaults": {"evidence_verified": False, "calculation_eligible": False,
                     "day_basis": None, "commitment_date_verified": None},
        "flags": ("evidence_verified", "calculation_eligible"),
        "date_flags": ("commitment_date_verified",),
        "dates": ("commitment_date", "due_date"),
        "quantity": ("effective_quantity",),
        "identity": ("portion_id", "order_id", "item_id"),
    },
    "deliveries": {
        "required": ("delivery_id", "source_event_key", "order_id", "item_id", "unit",
                     "delivered_quantity", "actual_date"),
        "defaults": {"evidence_verified": False, "candidate_portion_ids": (),
                     "actual_date_verified": None},
        "flags": ("evidence_verified",), "date_flags": ("actual_date_verified",),
        "dates": ("actual_date",), "quantity": ("delivered_quantity",),
        "identity": ("delivery_id", "source_event_key", "order_id", "item_id"),
    },
    "allocations": {
        "required": ("allocation_id", "delivery_id", "portion_id", "allocated_quantity", "version_id"),
        "defaults": {"status": "pending", "evidence_verified": False, "delivery_offset": None},
        "flags": ("evidence_verified",), "date_flags": (), "dates": (),
        "quantity": ("allocated_quantity", "delivery_offset"),
        "identity": ("allocation_id", "delivery_id", "portion_id", "version_id"),
    },
}


def _exact_quantity(value):
    # Same scalar policy as audit_delivery.quantity; no quantity algorithm here.
    if isinstance(value, (float, bool)) or value is None:
        raise ValueError("quantity_requires_exact_decimal")
    try:
        q = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("invalid_quantity") from None
    if not q.is_finite() or q < 0:
        raise ValueError("invalid_quantity")
    return q


@dataclass(frozen=True)
class DateQualification:
    status: str
    reasons: tuple
    assurance_level: str = "unverified_producer"
    formal_eligible: bool = False
    decision_refs: tuple = ()


def qualify_date(*, flag=MISSING, value=MISSING, subject_ref=MISSING, field_name=MISSING,
                 precision=MISSING, time_zone=MISSING, timezone_basis_ref=MISSING,
                 qualification_context_ref=MISSING, bases=()):
    """Check a named date claim, without granting real-source qualification.

    subject_ref=(kind, id, source-key, version). The producer must supply each
    version; neither record order nor a generic quantity flag can create one.
    Only explicit synthetic bindings can demonstrate a qualified matcher result.
    There is deliberately no formal-source resolver or production trust switch.
    """
    if flag is not MISSING and flag is not None and type(flag) is not bool:
        return DateQualification("unverified", ("invalid_date_verification_type",))
    if flag is not True:
        return DateQualification("unverified", ("named_date_not_verified",))
    if type(value) is not date:
        return DateQualification("unverified", ("exact_business_date_required",))
    if (not _subject_reference(subject_ref)
            or type(field_name) is not str or field_name not in ("actual_date", "commitment_date")
            or subject_ref[0] != ("delivery" if field_name == "actual_date" else "portion")
            or type(precision) is not str or precision not in ("date", "minute", "second", "higher")
            or type(time_zone) is not str or time_zone != "Asia/Shanghai"
            or not _text(timezone_basis_ref) or not _text(qualification_context_ref)):
        return DateQualification("unverified", ("date_claim_binding_incomplete",))
    if type(bases) not in (list, tuple) or not bases:
        return DateQualification("unverified", ("qualification_basis_required",))
    match = {"subject_ref": subject_ref, "field_name": field_name, "value": value,
             "precision": precision, "time_zone": time_zone,
             "timezone_basis_ref": timezone_basis_ref,
             "qualification_context_ref": qualification_context_ref}
    # Preflight EVERY basis before matching ANY of them. A valid first basis
    # must not hide an invalid later reference; no custom element can compare.
    for basis in bases:
        if type(basis) is not dict:
            return DateQualification("conflict", ("invalid_qualification_basis",))
        if (not _subject_reference(basis.get("subject_ref", MISSING))
                or any(type(basis.get(key, MISSING)) is not type(expected) for key, expected in match.items())):
            return DateQualification("conflict", ("date_basis_binding_mismatch",))
    decisions, conclusions = {}, set()
    for basis in bases:
        if any(basis[key] != expected for key, expected in match.items()):
            return DateQualification("conflict", ("date_basis_binding_mismatch",))
        if not all(_text(basis.get(key, MISSING)) for key in
                   ("evidence_id", "evidence_version", "decision_id", "decision_version", "scope_ref")):
            return DateQualification("unverified", ("qualification_basis_incomplete",))
        if type(basis.get("decision_status")) is not str or basis["decision_status"] != "active":
            return DateQualification("unverified", ("qualification_decision_not_active",))
        conclusion = basis.get("conclusion", MISSING)
        if type(conclusion) is not bool:
            return DateQualification("unverified", ("invalid_decision_conclusion",))
        # Scope binds the exact claim; a nonempty scope label alone grants nothing.
        scope_fields = basis.get("scope_fields")
        if (type(scope_fields) is not tuple or len(scope_fields) != 1
                or type(scope_fields[0]) is not str or scope_fields[0] != field_name):
            return DateQualification("conflict", ("decision_scope_mismatch",))
        key = (basis["decision_id"], basis["decision_version"])
        if key in decisions and decisions[key] != basis:
            return DateQualification("conflict", ("decision_identity_conflict",))
        decisions[key] = basis
        conclusions.add(conclusion)
    refs = tuple(decisions)
    if len(conclusions) > 1:
        return DateQualification("conflict", ("contradictory_active_decisions",), decision_refs=refs)
    if conclusions != {True}:
        return DateQualification("unverified", ("date_decision_not_approved",), decision_refs=refs)
    if all(type(basis.get("assurance_level")) is str and basis["assurance_level"] == "synthetic_only"
           for basis in decisions.values()):
        return DateQualification("qualified", ("synthetic_binding_only",), "synthetic_only", False, refs)
    return DateQualification("unverified", ("real_source_resolver_not_connected",), decision_refs=refs)


def _validate(entry, data, *, raw, record_types=None, quantity_validator=_exact_quantity):
    report = ValidationReport()
    if type(entry) is not str or entry not in ENTRY_POINTS:
        _issue(report, "invalid_core_entry", "entry", entry, fatal=True, category="request_structure")
        return report
    if type(data) is not dict:
        _issue(report, "invalid_request_structure", "$", data, fatal=True, category="request_structure")
        return report
    _version_and_context(data, report)
    if not report.root_valid:
        return report
    fields = ("unit", "cutoff") + (("order_id", "item_id") if entry == ENTRY_POINTS[0] else ())
    for name in fields:
        value = data.get(name, MISSING)
        report.observations.append(_observe(name, value))
        valid = type(value) is date if name == "cutoff" else _text(value)
        if not valid:
            _issue(report, "invalid_" + name, name, value, fatal=True, category="request_structure")
    groups = tuple(SCHEMAS) if entry == ENTRY_POINTS[0] else ("deliveries",)
    allowed = set(fields) | set(groups) | {"contract_version", "contract_context"}
    if entry == ENTRY_POINTS[0]:
        for name in ("commitment_scope_complete", "delivery_scope_complete"):
            allowed.add(name)
            provided = name in data
            value = data.get(name, MISSING)
            report.observations.append(_observe(name, value, provided=provided))
            if provided and value is MISSING:
                _issue(report, "explicit_missing_sentinel", name, value, category="coverage_field", provided=True)
            elif provided and type(value) is not bool:
                _issue(report, "invalid_verification_type", name, value, category="coverage_field")
    for name in data.keys() - allowed:
        _issue(report, "unsupported_input_field", "root", data[name], category="request_field")
    quantity_rows = []
    for group in groups:
        rows = data.get(group, MISSING)
        if type(rows) not in (list, tuple):
            _issue(report, "invalid_record_collection", group, rows, fatal=True, category="request_structure")
            continue
        schema = SCHEMAS[group]
        for index, row in enumerate(rows):
            path = f"{group}[{index}]"
            if (raw and type(row) is not dict) or (not raw and type(row) is not record_types[group]):
                _issue(report, "invalid_record_type", path, row, record_ref=(), category="record_structure")
                continue
            get = row.get if raw else lambda key, default=MISSING: getattr(row, key, default)
            ref = tuple((key, get(key)) for key in schema["identity"] if _text(get(key)))
            names = schema["required"] + tuple(schema["defaults"])
            if raw:
                for key in row.keys() - set(names):
                    _issue(report, "unsupported_record_field", path, row[key], record_ref=ref)
            for key in names:
                provided = key in row if raw else hasattr(row, key)
                value = get(key, MISSING)
                field_path = path + "." + key
                report.observations.append(_observe(field_path, value, provided=provided))
                if value is MISSING:
                    if provided:
                        _issue(report, "explicit_missing_sentinel", field_path, value, record_ref=ref, provided=True)
                    elif key in schema["required"] or not raw:
                        _issue(report, "missing_record_field", field_path, value, record_ref=ref)
                    continue
                if key in schema["flags"] and type(value) is not bool:
                    _issue(report, "invalid_verification_type", field_path, value, record_ref=ref)
                if key in schema["date_flags"] and value is not None and type(value) is not bool:
                    _issue(report, "invalid_date_verification_type", field_path, value, record_ref=ref)
                if key in schema["dates"] and value is not None and type(value) is not date:
                    _issue(report, "invalid_business_date_type", field_path, value, record_ref=ref)
                if key in schema["quantity"] and not (key == "delivery_offset" and value is None):
                    quantity_rows.append((field_path, value, ref))
            for flag_name in schema["date_flags"]:
                date_name = "actual_date" if flag_name == "actual_date_verified" else "commitment_date"
                # Existing dataclasses carry no fact/portion version or provenance.
                # Do not invent those from a generic flag or the context manifest.
                report.date_qualifications[path + "." + date_name] = qualify_date(
                    flag=get(flag_name, MISSING), value=get(date_name, MISSING))
    # All flags/dates collected before any quantity conversion or future-date path.
    for path, value, ref in quantity_rows:
        try:
            quantity_validator(value)
        except (ValueError, TypeError, InvalidOperation):
            _issue(report, "invalid_exact_quantity", path, value, record_ref=ref, category="quantity_value")
    return report


def validate_raw_request(entry, raw_request):
    """First boundary for NEW raw Python mappings, before coercion/model/defaults.

    No JSON/date parser is installed here. External payloads need an authorised
    adapter retaining raw values; this function cannot undo prior conversions.
    """
    return _validate(entry, raw_request, raw=True)


def validate_core_request(entry, arguments, *, record_types, quantity_validator):
    """Repeat checks on actual dataclass inputs, not their annotations/truthiness."""
    return _validate(entry, arguments, raw=False, record_types=record_types,
                     quantity_validator=quantity_validator)


@dataclass(frozen=True)
class PreparedRequest:
    report: ValidationReport
    arguments: dict | None


def prepare_raw_request(entry, raw_request, *, record_types):
    """Validate ALL records before calling any supplied model constructor.

    An invalid record stays in the report; no subset is silently constructed or
    calculated. This is not a decision that all business ranges are invalid.
    """
    report = validate_raw_request(entry, raw_request)
    if not report.types_and_values_valid:
        return PreparedRequest(report, None)
    arguments = dict(raw_request)
    groups = tuple(SCHEMAS) if entry == ENTRY_POINTS[0] else ("deliveries",)
    for group in groups:
        schema = SCHEMAS[group]
        arguments[group] = [record_types[group](**(schema["defaults"] | row)) for row in raw_request[group]]
    if entry == ENTRY_POINTS[0]:
        arguments.setdefault("commitment_scope_complete", False)
        arguments.setdefault("delivery_scope_complete", False)
    return PreparedRequest(report, arguments)


def require_v2_pipeline(report):
    if not report.root_valid:
        raise ContractError(next(issue.code for issue in report.request_issues if issue.fatal), report)
    # WP-2/3 are NOT implemented. No caller-provided flag may open this gate.
    raise QuantityContractNotReady(report)


# WP-3 candidate-only structures. None of these opens the public capability gate.
@dataclass(frozen=True)
class FrozenContent:
    entries: tuple

    def __getitem__(self, key):
        for name, value in self.entries:
            if name == key:
                return value
        raise KeyError(key)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default


@dataclass(frozen=True)
class OpaqueInput:
    type_name: str
    object_identity: int
    captured_scalar: tuple = ()  # Lossless rejected scalar metadata, NEVER a quantity.


@dataclass(frozen=True)
class QuantityIssue:
    code: str
    category: str
    subject_refs: tuple = ()
    basis_refs: tuple = ()
    path: str = ""
    blocking: bool = True
    phase: str = "static"


@dataclass(frozen=True)
class QuantitySlot:
    group: str
    source_index: int
    ref: object
    content: FrozenContent
    accepted: bool
    issues: tuple


@dataclass(frozen=True)
class QuantitySnapshot:
    contract_version: str
    operation: str
    input_manifest_ref: str
    fact_collection_ref: tuple
    qualification_context_ref: str
    business_cutoff: date
    unit: str
    business_timezone: str
    target_scope: tuple | None
    rule_binding: FrozenContent
    fact_slots: tuple
    portion_slots: tuple | None
    relation_slots: tuple | None
    fragment_manifest: object
    restriction_manifest: object
    field_claims: tuple
    verification_decisions: tuple
    evidence_records: tuple
    coverage_records: tuple
    raw_capture: tuple
    wp1_report: FrozenContent
    rejected_records: tuple
    localization_records: tuple


_QUANTITY_PREPARATION_TOKEN = object()


@dataclass(frozen=True)
class PreparedQuantityInput:
    snapshot: QuantitySnapshot | None
    issues: tuple
    raw_capture: tuple
    raw_sources: tuple
    wp1_report: FrozenContent
    rejection_code: str | None
    _token: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class EvaluationOutcome:
    content: FrozenContent

    def __getitem__(self, key):
        return self.content[key]

    def get(self, key, default=None):
        return self.content.get(key, default)


def prepare_quantity_snapshot(*, operation: str, raw_request: dict, snapshot_payload: dict) -> PreparedQuantityInput:
    """Separate WP-3 preparation; the accepted WP-1 preparation is unchanged.

    Imports occur at call time, after contract/fragment modules are initialized.
    Every source row is retained, including rejected rows and original WP-1
    diagnostics. This entry never runs the legacy quantity bodies.
    """
    from .audit_delivery_quantity import _prepare_quantity_snapshot
    return _prepare_quantity_snapshot(operation=operation, raw_request=raw_request,
                                      snapshot_payload=snapshot_payload)
