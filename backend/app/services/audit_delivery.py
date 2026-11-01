"""B002-C02/C03/C09: evidence-qualified quantity arithmetic, without persistence.

Inputs must come from a separately authorised, version-aware adapter. This module
does not approve evidence, activate allocations, infer FIFO, or grant permissions.
The legacy database cannot currently supply these inputs; its adapter stays gated.
WP-1 validates both public entrypoints, then stops at the V2 readiness gate.
The preserved arithmetic bodies below are not a V2 fallback implementation.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from functools import wraps

from .audit_delivery_contract import (
    MISSING, qualify_date, require_v2_pipeline, validate_core_request,
)


def quantity(value) -> Decimal:
    # Floats and booleans would conceal conversion/rounding decisions.
    if isinstance(value, (float, bool)) or value is None:
        raise ValueError("quantity_requires_exact_decimal")
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("invalid_quantity") from None
    if not result.is_finite() or result < 0:
        raise ValueError("invalid_quantity")
    return result


def _summarize_delivery_facts_v2_candidate(*, raw_request: dict, snapshot_payload: dict):
    """Internal synthetic candidate adapter, never an approved business API."""
    from .audit_delivery_contract import prepare_quantity_snapshot
    from .audit_delivery_quantity import summarize_quantity_snapshot
    prepared = prepare_quantity_snapshot(operation="facts_summary", raw_request=raw_request,
                                         snapshot_payload=snapshot_payload)
    return summarize_quantity_snapshot(prepared)


def _evaluate_delivery_scope_v2_candidate(*, raw_request: dict, snapshot_payload: dict):
    """Internal synthetic candidate adapter; public readiness gate stays closed."""
    from .audit_delivery_contract import prepare_quantity_snapshot
    from .audit_delivery_quantity import evaluate_quantity_snapshot
    prepared = prepare_quantity_snapshot(operation="order_item", raw_request=raw_request,
                                         snapshot_payload=snapshot_payload)
    return evaluate_quantity_snapshot(prepared)


@dataclass(frozen=True)
class Portion:
    portion_id: str
    order_id: str
    item_id: str
    unit: str
    effective_quantity: str
    commitment_date: date | None
    due_date: date | None
    evidence_verified: bool = False
    calculation_eligible: bool = False
    day_basis: str | None = None  # explicit natural_days; contract calendars not implemented
    commitment_date_verified: bool | None = field(default=None, kw_only=True)


@dataclass(frozen=True)
class Delivery:
    delivery_id: str
    source_event_key: str
    order_id: str | None
    item_id: str | None
    unit: str
    delivered_quantity: str
    actual_date: date | None
    evidence_verified: bool = False
    # Only an evidence-backed candidate scope may narrow the unknown's impact.
    candidate_portion_ids: tuple[str, ...] = ()
    # Named date declaration only. None is UNKNOWN, never generic-flag consent.
    # True also requires matching versioned evidence; it grants no source trust.
    actual_date_verified: bool | None = None


@dataclass(frozen=True)
class Allocation:
    allocation_id: str
    delivery_id: str
    portion_id: str
    allocated_quantity: str
    version_id: str
    status: str = "pending"  # usable/pending/disputed/awaiting_recovery
    evidence_verified: bool = False
    # Explicit evidence-backed partition of this delivery, NOT arrival order/FIFO.
    delivery_offset: str | None = None


def versioned_input_boundary(fn):
    @wraps(fn)
    def guarded(**kwargs):
        report = validate_core_request(fn.__name__, kwargs, record_types={
            "portions": Portion, "deliveries": Delivery, "allocations": Allocation,
        }, quantity_validator=quantity)
        # Runs BEFORE Decimal traversal, quantity algorithms and future-date exits.
        # WP-1 never delegates V2 or unversioned requests to the legacy body.
        require_v2_pipeline(report)
    return guarded


def exact_arithmetic(fn):
    @wraps(fn)
    def call(**kwargs):
        values = [quantity(getattr(row, field)) for key, field in (
            ("portions", "effective_quantity"), ("deliveries", "delivered_quantity"),
            ("allocations", "allocated_quantity")) for row in kwargs.get(key, ())]
        values += [quantity(a.delivery_offset) for a in kwargs.get("allocations", ()) if a.delivery_offset is not None]
        with localcontext() as ctx:
            if values:
                ctx.prec = max(28, max(v.adjusted() for v in values) + 1
                               - min(v.as_tuple().exponent for v in values) + len(str(len(values) + 1)) + 2)
            return fn(**kwargs)
    return call


def _index_delivery_facts(deliveries: list[Delivery], unit: str) -> dict[str, Delivery]:
    """One physical event once; shared by the fact and order-line views."""
    dmap, sources = {}, set()
    for d in deliveries:
        if not d.delivery_id or d.delivery_id in dmap or not d.source_event_key or d.source_event_key in sources:
            raise ValueError("duplicate_delivery_fact")
        if d.unit != unit:
            raise ValueError("delivery_scope_mismatch")
        quantity(d.delivered_quantity)
        dmap[d.delivery_id] = d
        sources.add(d.source_event_key)
    return dmap


def _has_verified_actual_date(d: Delivery, **qualification) -> bool:
    result = qualify_date(flag=d.actual_date_verified, value=d.actual_date,
                          field_name="actual_date", **qualification)
    # No real-source resolver exists in WP-1; even synthetic bindings cannot
    # turn an unbound date into a reliable business-period exclusion.
    return result.formal_eligible


@versioned_input_boundary
@exact_arithmetic
def summarize_delivery_facts(*, deliveries: list[Delivery], unit: str, cutoff: date,
                             contract_version=MISSING, contract_context=MISSING) -> dict:
    """AD-B02: summarize only the SUPPLIED physical facts, without allocating.

    This is not a factory-wide total or proof that the input scope is complete.
    Quantities are exact, single-unit verified subsets. Unverified facts remain
    explicitly listed; dates not verified cannot be assigned to either side of
    the cutoff. Consumers must not sum this same fact view across order views.
    """
    dmap = _index_delivery_facts(deliveries, unit)
    names = ("verified_quantity", "membership_identified_quantity", "membership_pending_quantity")
    buckets = {key: {name: Decimal(0) for name in names} for key in
               ("on_or_before_cutoff", "after_cutoff", "date_unverified")}
    verified_ids, unverified_ids = [], []
    for did, d in dmap.items():
        if not d.evidence_verified:
            unverified_ids.append(did)
            continue
        verified_ids.append(did)
        bucket = "date_unverified"
        if _has_verified_actual_date(d):
            bucket = "after_cutoff" if d.actual_date > cutoff else "on_or_before_cutoff"
        q = quantity(d.delivered_quantity)
        buckets[bucket]["verified_quantity"] += q
        membership = ("membership_pending_quantity" if d.order_id is None or d.item_id is None
                      else "membership_identified_quantity")
        buckets[bucket][membership] += q
    totals = {name: sum((row[name] for row in buckets.values()), Decimal(0)) for name in names}
    return {"scope_level": "supplied_delivery_facts", "unit": unit,
            "business_cutoff": cutoff.isoformat(),
            "verified_received_quantity": str(totals["verified_quantity"]),
            "membership_identified_quantity": str(totals["membership_identified_quantity"]),
            "membership_pending_quantity": str(totals["membership_pending_quantity"]),
            "verified_delivery_ids": verified_ids, "unverified_delivery_ids": unverified_ids,
            "by_date": {key: {name: str(q) for name, q in row.items()} for key, row in buckets.items()}}


def _pending_quantities_fit(capacities: dict[str, Decimal], demands: list[tuple[Decimal, set[str]]]) -> bool:
    """RV-01: check simultaneous capacity feasibility, NEVER allocate a receipt.

    A residual-capacity graph checks overlapping uncertainty scopes together.
    Its temporary paths are discarded; only a boolean is returned. Feasibility
    does not approve evidence, choose a portion, or release an affected balance.
    """
    required = sum((q for q, _ in demands), Decimal(0))
    source, sink = ("source",), ("sink",)
    graph = {source: {}, sink: {}}

    def edge(a, b, capacity):
        graph.setdefault(a, {})[b] = capacity
        graph.setdefault(b, {})[a] = Decimal(0)

    for pid, capacity in capacities.items():
        edge(("portion", pid), sink, capacity)
    for i, (q, scope) in enumerate(demands):
        node = ("demand", i)
        edge(source, node, q)
        for pid in scope & capacities.keys():
            edge(node, ("portion", pid), q)
    sent = Decimal(0)
    while sent < required:
        parents, queue = {source: None}, [source]
        for node in queue:
            for nxt, spare in graph[node].items():
                if spare > 0 and nxt not in parents:
                    parents[nxt] = node
                    queue.append(nxt)
            if sink in parents:
                break
        if sink not in parents:
            return False
        amount, node = required - sent, sink
        while node != source:
            prior = parents[node]
            amount = min(amount, graph[prior][node])
            node = prior
        node = sink
        while node != source:
            prior = parents[node]
            graph[prior][node] -= amount
            graph[node][prior] += amount
            node = prior
        sent += amount
    return True


@versioned_input_boundary
@exact_arithmetic
def evaluate_delivery_scope(*, order_id: str, item_id: str, unit: str, cutoff: date,
                            portions: list[Portion], deliveries: list[Delivery],
                            allocations: list[Allocation],
                            commitment_scope_complete: bool = False,
                            delivery_scope_complete: bool = False,
                            contract_version=MISSING, contract_context=MISSING) -> dict:
    """Evaluate one order line/unit. Unknown quantities are null, never inferred.

    effective_quantity is the externally verified original/addition balance AFTER
    expressly targeted reductions. Return/replenishment and conflicting versions
    must be resolved by their own policies, not by this function.
    """
    pmap, aids = {}, set()
    for p in portions:
        if not p.portion_id or p.portion_id in pmap:
            raise ValueError("duplicate_portion")
        if (p.order_id, p.item_id, p.unit) != (order_id, item_id, unit):
            raise ValueError("portion_scope_mismatch")
        quantity(p.effective_quantity)
        pmap[p.portion_id] = p
    dmap = _index_delivery_facts(deliveries, unit)
    for d in dmap.values():
        if d.order_id not in (None, order_id) or d.item_id not in (None, item_id):
            raise ValueError("delivery_scope_mismatch")
        if not set(d.candidate_portion_ids) <= pmap.keys():
            raise ValueError("unknown_candidate_portion")
    by_delivery = {key: [] for key in dmap}
    for a in allocations:
        if not a.allocation_id or a.allocation_id in aids or not a.version_id:
            raise ValueError("duplicate_or_unversioned_allocation")
        aids.add(a.allocation_id)
        if a.delivery_id not in dmap or a.portion_id not in pmap:
            raise ValueError("allocation_reference_missing")
        if a.status not in {"usable", "pending", "disputed", "awaiting_recovery"}:
            raise ValueError("unknown_allocation_status")
        if quantity(a.allocated_quantity) <= 0:
            raise ValueError("allocation_must_be_positive")
        by_delivery[a.delivery_id].append(a)
    # DEC-017 allows unchanged old fragments beside approved changed fragments.
    # Accept an explicit, non-overlapping effective manifest; never select latest.
    for did, rows in by_delivery.items():
        if sum((quantity(a.allocated_quantity) for a in rows), Decimal(0)) > quantity(dmap[did].delivered_quantity):
            raise ValueError("allocation_exceeds_delivery")
        spans = []
        for a in rows:
            if a.delivery_offset is not None:
                start = quantity(a.delivery_offset)
                end = start + quantity(a.allocated_quantity)
                overlaps = [version for c, b, version in spans if start < b and end > c]
                if any(version != a.version_id for version in overlaps):
                    raise ValueError("conflicting_effective_versions")
                if end > quantity(dmap[did].delivered_quantity) or overlaps:
                    raise ValueError("overlapping_or_outside_delivery_range")
                spans.append((start, end, a.version_id))

    eligible = {k for k, p in pmap.items() if p.evidence_verified and p.calculation_eligible
                and p.commitment_date is not None and p.commitment_date <= cutoff}
    future = {k for k, p in pmap.items() if p.evidence_verified and p.commitment_date is not None
              and p.commitment_date > cutoff}
    assigned = {k: Decimal(0) for k in pmap}
    confirmed_assigned = {k: Decimal(0) for k in pmap}
    verified_total = calc_total = suspended = Decimal(0)
    affected, reasons = set(), []
    pending_demands = []
    complete = delivery_scope_complete
    if not complete:
        affected.update(pmap)
        reasons.append("delivery_scope_incomplete")
    for did, d in dmap.items():
        candidates = set(d.candidate_portion_ids) or set(pmap)
        # AD-B03: only a reliable actual date can exclude a post-cutoff fact.
        # Unknown order membership must not taint an earlier period in that case.
        if _has_verified_actual_date(d) and d.actual_date > cutoff:
            continue
        if not d.evidence_verified or not _has_verified_actual_date(d) or d.order_id is None or d.item_id is None:
            # AD-B01: candidate revisions cannot release existing target scopes.
            affected.update(candidates | {a.portion_id for a in by_delivery[did]})
            complete = False
            reasons.append("delivery_fact_or_order_membership_unverified")
            continue
        amount = quantity(d.delivered_quantity)
        verified_total += amount
        represented = Decimal(0)
        for a in by_delivery[did]:
            q = quantity(a.allocated_quantity)
            represented += q
            if a.portion_id in future:
                raise ValueError("delivery_before_commitment")
            p = pmap[a.portion_id]
            if (a.evidence_verified and p.evidence_verified and p.commitment_date
                    and d.actual_date < p.commitment_date):
                raise ValueError("delivery_before_commitment")
            if a.evidence_verified and a.status in {"usable", "awaiting_recovery"} and a.delivery_offset is not None:
                confirmed_assigned[a.portion_id] += q
            if a.evidence_verified and a.status == "usable" and a.portion_id in eligible and a.delivery_offset is not None:
                assigned[a.portion_id] += q
                calc_total += q
            elif a.evidence_verified and a.status == "awaiting_recovery" and a.delivery_offset is not None:
                suspended += q
                affected.add(a.portion_id)
            else:
                scope = candidates | {a.portion_id}
                affected.update(scope)
                pending_demands.append((q, scope))
        if represented < amount:
            affected.update(candidates)
            pending_demands.append((amount - represented, candidates))
    for pid, used in confirmed_assigned.items():
        if used > quantity(pmap[pid].effective_quantity):
            raise ValueError("allocation_exceeds_portion")
    known_commitments = commitment_scope_complete and (eligible | future) == pmap.keys()
    total_q = sum((quantity(pmap[k].effective_quantity) for k in eligible), Decimal(0))
    order_remaining = total_q - verified_total if known_commitments and complete else None
    if order_remaining is not None and order_remaining < 0:
        raise ValueError("delivery_exceeds_effective_commitment")
    if order_remaining is not None and not _pending_quantities_fit(
            {pid: quantity(pmap[pid].effective_quantity) - confirmed_assigned[pid] for pid in eligible},
            pending_demands):
        # Do not turn an impossible uncertainty scope into a definite line total.
        # Keep independently supported portions and physical facts unchanged.
        order_remaining = None
        reasons.append("pending_scope_capacity_insufficient")
    results = []
    for pid, p in pmap.items():
        if pid in future:
            continue
        remaining = quantity(p.effective_quantity) - assigned[pid] if pid in eligible and pid not in affected else None
        overdue_qty = overdue_days = age_days = None
        state = "不可确定"
        if remaining is not None:
            state = "可支持"
            if remaining == 0:
                overdue_qty = Decimal(0)
            else:
                age_days = (cutoff - p.commitment_date).days
                if p.due_date is not None and p.day_basis == "natural_days":
                    overdue_days = max(0, (cutoff - p.due_date).days)
                    overdue_qty = remaining if overdue_days > 0 else Decimal(0)
        results.append({"portion_id": pid, "state": state,
                        "remaining_quantity": str(remaining) if remaining is not None else None,
                        "age_days": age_days,
                        "overdue_quantity": str(overdue_qty) if overdue_qty is not None else None,
                        "overdue_days": overdue_days,
                        "overdue_limitation": None if overdue_qty is not None else "份额、交期或合同计日日历依据不足"})
    pending = verified_total - calc_total - suspended
    # A negative item-level arrival flag alone must never become a whole-order
    # R10 conclusion; the future adapter must verify the complete order scope.
    return {"order_id": order_id, "item_id": item_id, "unit": unit, "scope_level": "order_item",
            "business_cutoff": cutoff.isoformat(),
            # Separate fact view; do not add it to this order-line subset below.
            "delivery_facts": summarize_delivery_facts(deliveries=deliveries, unit=unit, cutoff=cutoff),
            "verified_delivery_quantity": str(verified_total),
            "delivery_scope_complete": complete,
            "verified_assigned_quantity": str(calc_total + suspended),
            "calculable_allocated_quantity": str(calc_total),
            "awaiting_recovery_quantity": str(suspended),
            "allocation_pending_quantity": str(pending),
            "remaining_quantity": str(order_remaining) if order_remaining is not None else None,
            "has_verified_arrival": True if verified_total > 0 else (False if complete else None),
            "limitations": sorted(set(reasons)), "portions": results}
