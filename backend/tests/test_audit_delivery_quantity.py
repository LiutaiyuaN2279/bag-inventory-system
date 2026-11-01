"""WP-3 synthetic integration, original matrices unchanged; no I/O in tests."""
from copy import deepcopy
from dataclasses import replace, fields
from datetime import date, datetime, timedelta
from decimal import Decimal, getcontext, localcontext
import unittest

from app.services import audit_delivery as core
from app.services import audit_delivery_contract as c
from app.services import audit_delivery_fragments as f
from app.services import audit_delivery_restrictions as r
from app.services import audit_delivery_quantity as q
from test_audit_delivery_fragments import fixture, combine, NoCompare
from test_audit_delivery_restrictions import GraphFixture, pnode


CUTOFF = date(2026, 9, 30)
START = date(2026, 9, 1)
ACTUAL = date(2026, 9, 20)
SPEC_RESULTS = []


def portion(pid, amount="100", commit=START, due=date(2026, 9, 10), mode="natural_days"):
    return dict(portion_id=pid, order_id="PO", item_id="LINE", unit="件", effective_quantity=amount,
                commitment_date=commit, due_date=due, evidence_verified=True, calculation_eligible=True,
                day_basis=mode, commitment_date_verified=True)


def delivery(did, amount, candidates, actual=ACTUAL, verified=True, date_verified=True, order="PO"):
    return dict(delivery_id=did, source_event_key="source-" + did, order_id=order, item_id="LINE" if order else None,
                unit="件", delivered_quantity=amount, actual_date=actual, evidence_verified=verified,
                candidate_portion_ids=tuple(candidates), actual_date_verified=date_verified)


def allocation(did, amount, target, status="pending", offset="0", aid=None):
    return dict(allocation_id=aid or "AL-" + did, delivery_id=did, portion_id=target, allocated_quantity=amount,
                version_id="v1", status=status, evidence_verified=True, delivery_offset=offset)


def attest(payload, subject, name, value, *, conclusion=True):
    i = len(payload["verification_decisions"])
    body = dict(subject_ref=subject, field_name=name, value=value, declared_verified=True,
                qualification_context_ref=payload["qualification_context_ref"],
                precision="date" if name in ("actual_date", "commitment_date") else None,
                time_zone="Asia/Shanghai" if name in ("actual_date", "commitment_date") else None,
                timezone_basis_ref="tz-evidence@1" if name in ("actual_date", "commitment_date") else None)
    frozen = q.freeze(body)
    dr, er = ("decision-" + str(i), "v1"), ("evidence-" + str(i), "v1")
    payload["field_claims"] += (dict(body, decision_refs=(dr,)),)
    payload["verification_decisions"] += (dict(ref=dr, claim_content=frozen, conclusion=conclusion,
        status="active", evidence_refs=(er,), observation_ref=payload["qualification_context_ref"], assurance_level="synthetic_only"),)
    payload["evidence_records"] += (dict(ref=er, assertions=(frozen,)),)


def cover(raw, payload, scopes):
    # Rebuild the current coverage selection after an intentional fixture edit.
    # Historical decision/evidence records remain; do not assert two different
    # contents as the current coverage of the same scope.
    payload["field_claims"] = tuple(x for x in payload["field_claims"] if x["field_name"] != "coverage")
    payload["coverage_records"] = ()
    content = q.binding_content(raw, payload)
    for scope in scopes:
        payload["coverage_records"] += (dict(scope_ref=scope, declared_complete=True, content=content),)
        attest(payload, scope, "coverage", content)


def request(ps, ds, als=(), *, summary=False, omit=(), exclude=None, calendar=False, graph_change=None, cover_line=True):
    operation = "facts_summary" if summary else "order_item"
    raw = dict(contract_version=c.V2, contract_context=dict(contract_version=c.V2,
        input_manifest_ref="manifest@1", qualification_context_ref="observation@1"), unit="件", cutoff=CUTOFF, deliveries=list(ds))
    if not summary:
        raw.update(order_id="PO", item_id="LINE", portions=list(ps), allocations=list(als),
                   commitment_scope_complete=True, delivery_scope_complete=True)
    payload = dict(contract_version=c.V2, operation=operation, input_manifest_ref="manifest@1",
        fact_collection_ref=("facts", "v1"), qualification_context_ref="observation@1", business_cutoff=CUTOFF,
        unit="件", business_timezone="Asia/Shanghai", target_scope=None if summary else ("PO", "LINE", "件"),
        rule_binding=dict(q.RULES), fact_slots=(), portion_slots=None if summary else (),
        relation_slots=None if summary else (), fragment_manifest=None, restriction_manifest=None,
        field_claims=(), verification_decisions=(), evidence_records=(), coverage_records=())
    manifests, keys = [], {}
    for d in ds:
        did = d["delivery_id"]
        rows = [a for a in als if a["delivery_id"] == did]
        segments = []
        amount = Decimal(d["delivered_quantity"])
        if rows:
            for a in rows:
                start = Decimal(a["delivery_offset"] or "0")
                aq = Decimal(a["allocated_quantity"])
                segments.append((a["allocation_id"], str(start), str(start + aq), str(aq), "G-" + a["allocation_id"]))
        elif amount > 0:
            segments = [("S-" + did, "0", str(amount), str(amount), "G-" + did)]
        m = fixture(d["source_event_key"], str(amount), tuple(segments))
        m = replace(m, facts=(replace(m.facts[0], delivery_id=did),))
        manifests.append(m)
        keys.update({k.key.fragment_id: k.key for k in m.definitions})
        ref = m.facts[0].ref
        payload["fact_slots"] += (dict(id=did, ref=ref, content=deepcopy(d)),)
        subject = ("delivery", did, ref.source_event_key, ref.version)
        for name, value in (("quantity", amount), ("unit", d["unit"]),
                             ("membership", (d.get("order_id"), d.get("item_id")))):
            attest(payload, subject, name, value)
        if type(d.get("actual_date")) is date:
            attest(payload, subject, "actual_date", d["actual_date"])
    for p in ps:
        ref = (p["order_id"], p["item_id"], p["unit"], p["portion_id"], "v1")
        if not summary:
            payload["portion_slots"] += (dict(id=p["portion_id"], ref=ref, content=deepcopy(p)),)
        subject = ("portion", p["portion_id"], p["portion_id"], "v1")
        for name, value in (("effective_quantity", Decimal(p["effective_quantity"])), ("commitment_date", p["commitment_date"]),
                            ("due_date", p["due_date"]), ("day_basis", p["day_basis"])):
            if value is not None:
                attest(payload, subject, name, value)
    if not summary:
        for a in als:
            key = keys[a["allocation_id"]]
            payload["relation_slots"] += (dict(id=a["allocation_id"], ref=(a["allocation_id"], a["version_id"], key), content=deepcopy(a)),)
            target = ("PO", "LINE", "件", a["portion_id"], "v1")
            attest(payload, ("relation", a["allocation_id"], a["version_id"], key.parent_fact_ref.source_event_key),
                   "relation_content", q.freeze(dict(record=q.freeze(a), key=q.freeze(key), target=target)))
        if manifests:
            manifest = combine(*manifests)
        else:
            manifest = f.FragmentManifest(f.ValidationContext(c.V2, "manifest@1", "observation@1"), (), (), ())
        target_map = {a["allocation_id"]: a["portion_id"] for a in als}
        g = GraphFixture(manifest, names=tuple(p["portion_id"] for p in ps), targets=target_map)
        by_did = {d["delivery_id"]: d for d in ds}
        for fact in g.fragments.facts:
            d = by_did[fact.delivery_id]
            for frag in (x for x in g.fragments.definitions if x.key.parent_fact_ref == fact.ref):
                node = r.fragment_node(frag.key)
                g.edge(r.fact_node(fact.ref), node)
                a = next((a for a in als if a["allocation_id"] == frag.key.fragment_id), None)
                original = () if a is None else (pnode(a["portion_id"]),)
                candidates = tuple(pnode(x) for x in d["candidate_portion_ids"]) or tuple(pnode(p["portion_id"]) for p in ps)
                if a is not None and a["status"] in ("usable", "awaiting_recovery"):
                    candidates = original  # explicit independent segment scope evidence
                g.scope(node, candidates, original)
                if a is not None:
                    g.edge(node, pnode(a["portion_id"]))
                    if a["status"] in ("pending", "disputed", "awaiting_recovery"):
                        g.seed(a["allocation_id"], "allocation_" + a["status"] if a["status"] != "awaiting_recovery" else a["status"], node)
            if d["evidence_verified"] is not True:
                g.seed("q-" + fact.delivery_id, "quantity_unverified", r.fact_node(fact.ref))
            if d["actual_date_verified"] is not True or d["actual_date"] is None:
                g.seed("date-" + fact.delivery_id, "actual_date_unverified", r.fact_node(fact.ref))
            if d["order_id"] is None:
                g.seed("member-" + fact.delivery_id, "membership_unverified", r.fact_node(fact.ref))
        for fragment_id in omit:
            absent = r.fragment_node(keys[fragment_id])
            g.nodes.remove(absent)
            g.dependencies = [edge for edge in g.dependencies if absent not in (edge.source, edge.target)]
            g.scopes = [scope for scope in g.scopes if scope.subject != absent]
            g.protections = [p for p in g.protections if p.subject != absent]
        excluded = {pnode(pid): tuple(r.fact_node(f.FactRef("source-" + did, "fv1")) for did in ids)
                    for pid, ids in (exclude or {}).items()}
        graph = g.finish(exclude=excluded)
        if graph_change is not None:
            graph = graph_change(graph)
        payload["fragment_manifest"], payload["restriction_manifest"] = graph.fragments, graph
    if calendar:
        start, end = date(2026, 1, 1), date(2026, 12, 31)
        cal = dict(ref=("contract-calendar", "v1"), valid_from=start, valid_to=end,
                   days=tuple((start + timedelta(days=i), True) for i in range(365)), contract_ref=("contract", "v1"))
        payload["rule_binding"].update(calendar_ref=cal["ref"], calendar_content=q.freeze(cal))
        attest(payload, ("calendar",), "calendar_content", q.freeze(cal))
    scopes = [("facts",)]
    if not summary:
        if cover_line:
            scopes.append(("line", "PO", "LINE", "件"))
        scopes.extend(("portion", "PO", "LINE", "件", p["portion_id"], "v1") for p in ps)
    cover(raw, payload, scopes)
    return raw, payload


def evaluate(req):
    return core._evaluate_delivery_scope_v2_candidate(raw_request=req[0], snapshot_payload=req[1])


def value(metric):
    return metric["value"]


def pmap(result):
    return {p["portion_ref"][3]: p for p in result["portions"]}


def issue_codes(result):
    return {x["code"] for x in result["issues"]} | {x["code"] for x in result["line"]["line_total_reasons"]}


class QuantityIntegrationTests(unittest.TestCase):
    def check(self, spec, req, vector, remaining=None, balances=None, code=None):
        before = deepcopy(req,{id(c.MISSING):c.MISSING})
        result = evaluate(req)
        self.assertNotEqual(result["result_status"], "rejected", q.plain(result))
        actual = tuple(Decimal(value(result["line"][name])) for name in ("F", "T", "W", "Cc", "Rr", "Ep", "Z", "Pp"))
        expected = tuple(Decimal(str(v)) for v in vector)
        self.assertEqual(actual, expected, spec)
        with localcontext() as ctx:
            ctx.prec=1024
            self.assertEqual(actual[1], actual[2] + actual[6])
            self.assertEqual(actual[2], actual[3] + actual[4] + actual[5])
            self.assertEqual(actual[7], actual[5] + actual[6])
            self.assertEqual(Decimal(value(result["line"]["verified_assigned_quantity"])), actual[3] + actual[4])
        for alias,key in (("verified_delivery_quantity","T"),("calculation_included_quantity","W"),
                          ("calculable_allocated_quantity","Cc"),("awaiting_recovery_quantity","Rr"),
                          ("allocation_pending_quantity","Pp")):
            self.assertEqual(result["line"][alias],result["line"][key])
        self.assertEqual(value(result["line"]["remaining_quantity"]), None if remaining is None else str(remaining))
        self.assertEqual(result["line"]["line_total_status"], "undetermined" if remaining is None else "supported")
        for pid, balance in (balances or {}).items():
            self.assertEqual(value(pmap(result)[pid]["remaining_quantity"]), None if balance is None else str(balance), (spec, pid))
        if code:
            self.assertIn(code, issue_codes(result))
        self.assertEqual(req, before)
        self.assertEqual(result["assurance_level"], "synthetic_only")
        self.assertFalse(result["formal_eligible"])
        SPEC_RESULTS.append(dict(spec=spec, expected_vector=[str(v) for v in expected], actual={k:q.plain(result[k]) for k in
            ("result_status","line","physical_facts","portions","issues","capacity_checks","quantity_ranges","assurance_level","formal_eligible")},
                                 assertions="numeric vector, invariants, line, selected portions, identity/protection", status="passed"))
        return result

    def assert_c(self, result, pid="C", amount="80"):
        row = pmap(result)[pid]
        self.assertEqual([value(row[k]) for k in ("remaining_quantity", "age_days", "overdue_quantity", "overdue_days")],
                         [amount, 29, amount, 20])

    def test_conflict80_independent20(self):
        for affects_a in (False, True):
            with self.subTest(affects_a=affects_a):
                ps = [portion("A"), portion("B", commit=date(2026, 9, 25)), portion("C")]
                req = request(ps, [delivery("D", "80", ("A", "B") if affects_a else ("B",)), delivery("DC", "20", ("C",))],
                              [allocation("D", "80", "B", "disputed"), allocation("DC", "20", "C", "usable")])
                result = self.check("P101-01/TR02-01-02", req, (100,100,20,20,0,0,80,80), balances={"A":None if affects_a else 100,"B":None,"C":80})
                self.assert_c(result)
                self.assertIs(value(result["line"]["has_verified_arrival"]), True)

    def test_reliable50_disputed30_and_recovery(self):
        for status, conflict in (("disputed", True), ("awaiting_recovery", False)):
            with self.subTest(status=status):
                req = request([portion("A"),portion("B", commit=date(2026,9,25) if conflict else START)],
                    [delivery("D","80",("B",))], [allocation("D","50","A","usable"),allocation("D","30","B",status,"50","AL-30")])
                result = self.check("P101-02/TR03-01/TR03-07",req,(80,80,50,50,0,0,30,30) if conflict else (80,80,80,50,30,0,0,0),
                    remaining=None if conflict else 120,balances={"A":50,"B":None})
                self.assertEqual(len(result["physical_facts"]["declared_records"]),1)

    def test_tr0506_usable_overallocation_with_unknown_date(self):
        req=request([portion("A","10"),portion("X")],[delivery("DX","7",("X",),None),delivery("D","80",("A",))],
                    [allocation("D","80","A","usable")])
        result=self.check("TR05-06",req,(87,80,0,0,0,0,80,80),balances={"A":None,"X":None},code="allocation_exceeds_portion")
        self.assertEqual(result["physical_facts"]["by_date"]["date_unverified"]["verified_quantity"],"7")
        self.assertNotIn("pending_scope_capacity_insufficient",issue_codes(result))

    def test_tr0508_pending_capacity_with_independent_scopes(self):
        req=request([portion("A","10"),portion("B"),portion("X"),portion("C")],
            [delivery("D","80",("A",)),delivery("DX","7",("X",),None),delivery("DC","20",("C",))],
            [allocation("D","80","A"),allocation("DC","20","C","usable")])
        result=self.check("TR05-08",req,(107,100,20,20,0,0,80,80),balances={"A":None,"X":None,"B":100,"C":80},code="pending_scope_capacity_insufficient")
        self.assert_c(result)
        self.assertNotIn("allocation_exceeds_portion",issue_codes(result))

    def test_g1_g2_complete(self):
        for g2 in (False,True):
            with self.subTest(g2=g2):
                names=("A","B","C","D","X") if g2 else ("A","B","C","X")
                ps=[portion(n,commit=date(2026,9,25) if n=="B" else START) for n in names]
                ds=[delivery("D1","40",("A","C") if g2 else ("A","B")),delivery("D2","30",("C","D") if g2 else ("B","C")),delivery("DX","20",("X",))]
                als=[allocation("D1","40","B","disputed"),allocation("DX","20","X","usable")]
                req=request(ps,ds,als)
                result=self.check("TR08-02/G2" if g2 else "TR08-01/G1",req,(90,90,50,20,0,30,40,70) if g2 else (90,90,20,20,0,0,70,70),balances={"X":80})
                self.assert_c(result,"X")
                self.assertIn(pnode("B"),req[1]["restriction_manifest"].protections[0].targets)

    def test_tr0509_date_variants(self):
        alpha="0.20000000000000000000000000001"; total="0.30000000000000000000000000001"
        for case in ("M-074","M-076","M-078","M-088","M-089"):
            for actual in (ACTUAL,date(2026,8,31),None):
                with self.subTest(case=case,actual=str(actual)):
                    last="D2"; als=[]
                    if case=="M-074":
                        ps=[portion(n,"10" if n in "ABC" else "100") for n in "ABCDE"]
                        ds=[delivery("D1","15",("A","B")),delivery("D2","15",("B","C")),delivery("D3","15",("A","C")),delivery("D4","1",("C","D"),actual)]
                        last="D4"; v=(46,45,0,0,0,0,45,45) if actual is None else (46,46,0,0,0,0,46,46)
                        verdict="infeasible"; independent="E"; remaining=None
                    elif case in ("M-076","M-078"):
                        recovery=case=="M-078"; ps=[portion("A"),portion("B")]
                        ds=[delivery("D1","70",("A",)),delivery("D2","40",("A",),actual)]
                        als=[allocation("D1","70","A","awaiting_recovery" if recovery else "usable"),allocation("D2","40","A")]
                        v=(110,70 if actual is None else 110,70,0 if recovery else 70,70 if recovery else 0,0,0 if actual is None else 40,0 if actual is None else 40)
                        verdict="undetermined" if actual is None else "infeasible"; independent="B"; remaining=None
                    else:
                        tiny=case=="M-089"; ps=[portion("A","0.3"),portion("B")]
                        ds=[delivery("D1","0.1",("A",)),delivery("D2",alpha if tiny else "0.2",("A",),actual)]
                        if actual is None:v=(total if tiny else "0.3","0.1",0,0,0,0,"0.1","0.1")
                        elif actual==ACTUAL and not tiny:v=("0.3","0.3","0.3",0,0,"0.3",0,"0.3")
                        elif not tiny:v=("0.3","0.3","0.1",0,0,"0.1","0.2","0.3")
                        else:v=(total,total,0,0,0,0,total,total)
                        verdict="undetermined" if actual is None else "infeasible" if tiny else "feasible"
                        independent="B"; remaining=100 if actual==ACTUAL and not tiny else None
                    result=self.check("TR05-09/"+case+"/"+str(actual),request(ps,ds,als),v,remaining=remaining,balances={independent:100,"A":None})
                    checks=[x for x in result["capacity_checks"] if x["kind"]=="shared_capacity"]
                    self.assertTrue(any(x["capacity_status"]==verdict for x in checks))
                    self.assertTrue(any(x["demand_period_status"]==("undetermined" if actual is None else "complete") for x in checks))
                    if case=="M-074" and actual is None:
                        self.assertEqual(result["physical_facts"]["by_date"]["date_unverified"]["verified_quantity"],"1")
                        self.assertTrue(any(x["violation_witnesses"] and x["conditional_demands"] for x in checks))

    def test_partial_fragment_omission_parent_date_unverified(self):
        req=request([portion("A"),portion("B",commit=date(2026,9,25)),portion("C")],
            [delivery("D","80",("A","B"),date_verified=None),delivery("DC","20",("C",))],
            [allocation("D","50","A","usable"),allocation("D","30","B","disputed","50","AL-30"),allocation("DC","20","C","usable")],
            omit=("AL-30",),exclude={"C":("D",)})
        key=next(x.key for x in req[1]["fragment_manifest"].definitions if x.key.fragment_id=="AL-30")
        self.assertNotIn(r.fragment_node(key),req[1]["restriction_manifest"].nodes)
        result=self.check("IR03-partial/P101-03",req,(100,20,20,20,0,0,0,0),balances={"A":None,"B":None,"C":80})
        self.assert_c(result)
        self.assertNotIn(r.fragment_node(key),req[1]["restriction_manifest"].nodes)

    def test_status_combinations_calendar_and_zero(self):
        for kind in ("missing_due","disputed","unsupported","natural","zero"):
            with self.subTest(kind=kind):
                amount="100" if kind=="zero" else "20"
                req=request([portion("C",due=None if kind=="missing_due" else date(2026,9,10),mode="natural_days" if kind=="natural" else "contract_workdays")],
                    [delivery("DC",amount,("C",))],[allocation("DC",amount,"C","disputed" if kind=="disputed" else "usable")],calendar=True)
                disputed=kind=="disputed"
                result=self.check("DR03-"+kind,req,(amount,amount,amount,0 if disputed else amount,0,amount if disputed else 0,0,amount if disputed else 0),remaining=0 if kind=="zero" else 80,balances={"C":None if disputed else 0 if kind=="zero" else 80})
                row=pmap(result)["C"]
                expected="undetermined" if kind in ("missing_due","disputed") else "unsupported" if kind=="unsupported" else "supported"
                self.assertEqual(row["overdue_quantity"]["status"],expected)
                self.assertEqual(row["overdue_days"]["status"],"not_applicable" if kind=="zero" else expected)
                self.assertEqual(row["age_days"]["status"],"not_applicable" if kind=="zero" else "undetermined" if disputed else "supported")
                if kind=="zero":self.assertIsNone(value(row["age_days"]))
                if kind in ("missing_due","disputed","unsupported"):
                    self.assertTrue(any(x["category"]=="capability" for x in row["overdue_quantity"]["reasons"]))
                if kind=="natural":self.assert_c(result)

    def test_independent_summary_does_not_require_membership(self):
        req=request([], [delivery("D","80",(),order=None)],summary=True)
        result=core._summarize_delivery_facts_v2_candidate(raw_request=req[0],snapshot_payload=req[1])
        self.assertEqual(value(result["physical_facts"]["verified_received_quantity"]),"80")
        self.assertEqual(result["physical_facts"]["membership_pending_quantity"],"80")
        self.assertIsNone(result["line"])
        self.assertEqual(result["portions"],())
        self.assertFalse(result["formal_eligible"])

    def test_reliable_future80_and_unknown_period80(self):
        for actual in (date(2026,10,1),None):
            with self.subTest(actual=str(actual)):
                req=request([portion("A","10"),portion("B")],[delivery("D","80",("A",),actual,order=None if actual else "PO")])
                result=self.check("M-085/086",req,(80,0,0,0,0,0,0,0),remaining=110 if actual else None,balances={"A":10 if actual else None,"B":100})
                self.assertEqual(value(result["line"]["has_verified_arrival"]),False if actual else None)

    def test_public_entries_remain_not_ready(self):
        req=request([portion("A")],[])
        with self.assertRaises(c.QuantityContractNotReady):core.evaluate_delivery_scope(**c.prepare_raw_request("evaluate_delivery_scope",req[0],record_types={"portions":core.Portion,"deliveries":core.Delivery,"allocations":core.Allocation}).arguments)
        raw,payload=request([],[],summary=True)
        with self.assertRaises(c.QuantityContractNotReady):core.summarize_delivery_facts(**raw)

    def test_rv01_integration_matrix(self):
        tiny="0.20000000000000000000000000001"; total="0.30000000000000000000000000001"
        for number in range(62,90):
            with self.subTest(original_spec="M-"+str(number)):
                ps=[portion("A","10"),portion("B")];ds=[delivery("D","80",("A",))];als=[allocation("D","80","A")]
                vector=(80,80,0,0,0,0,80,80); remaining=None;balances={"A":None,"B":100};code=None
                if number==63:als[0]["status"]="disputed"
                elif number==64:als[0]["status"]="awaiting_recovery";code="allocation_exceeds_portion"
                elif number==65:
                    ps=[portion("A","10"),portion("B","10"),portion("C")];als=[allocation("D","80","B","disputed")];balances={"A":None,"B":None,"C":100}
                elif number==66:
                    ps+=[portion("C")];ds+=[delivery("DC","20",("C",))];als[0]["status"]="disputed";als+=[allocation("DC","20","C","usable")];vector=(100,100,20,20,0,0,80,80);balances["C"]=80
                elif number==67:
                    ps=[portion("A","50"),portion("B","50"),portion("C")];ds=[delivery("D","80",("A","B"))];als=[allocation("D","80","A","disputed")];vector=(80,80,80,0,0,80,0,80);remaining=120;balances={"A":None,"B":None,"C":100}
                elif number in (68,69):
                    ps=[portion("A","80"),portion("B")];amount="80" if number==68 else "80.1";ds=[delivery("D",amount,("A",))];als=[allocation("D",amount,"A")];vector=(amount,amount,amount if number==68 else 0,0,0,amount if number==68 else 0,0 if number==68 else amount,amount);remaining=100 if number==68 else None
                elif number==70:
                    ps=[portion("A"),portion("B")];ds=[delivery("D1","60",("A",)),delivery("D2","60",("A",))];als=[allocation("D1","60","A"),allocation("D2","60","A")];vector=(120,120,0,0,0,0,120,120)
                elif number==71:
                    ps=[portion(x) for x in "ABC"];ds=[delivery("D1","60",("A",)),delivery("D2","70",("B",))];als=[allocation("D1","60","A"),allocation("D2","70","B","disputed")];vector=(130,130,130,0,0,130,0,130);remaining=170;balances={"A":None,"B":None,"C":100}
                elif number==72:
                    ps=[portion("A","30"),portion("B","30"),portion("C"),portion("D")];ds=[delivery("D1","70",("A","B")),delivery("D2","10",("B","C"))];als=[allocation("D1","70","A"),allocation("D2","10","B")];vector=(80,80,0,0,0,0,80,80);balances={"A":None,"B":None,"C":None,"D":100}
                elif number in (73,75):
                    ps=[portion("A","50"),portion("B","50"),portion("C")];ds=[delivery("D1","50",("A","B")),delivery("D2","50",("A",))];als=[allocation("D1","50","A"),allocation("D2","50","A")];vector=(100,100,100,0,0,100,0,100);remaining=100;balances={"A":None,"B":None,"C":100}
                elif number==74:
                    ps=[portion(n,"10" if n in "ABC" else "100") for n in "ABCDE"];ds=[delivery("D1","15",("A","B")),delivery("D2","15",("B","C")),delivery("D3","15",("A","C")),delivery("D4","1",("C","D"))];als=[];vector=(46,46,0,0,0,0,46,46);balances={**{n:None for n in "ABCD"},"E":100}
                elif number in (76,77,78):
                    ps=[portion("A"),portion("B")];second="30" if number==77 else "40";ds=[delivery("D1","70",("A",)),delivery("D2",second,("A",))];als=[allocation("D1","70","A","awaiting_recovery" if number==78 else "usable"),allocation("D2",second,"A")];vector=(100 if number==77 else 110,100 if number==77 else 110,100 if number==77 else 70,0 if number==78 else 70,70 if number==78 else 0,30 if number==77 else 0,0 if number==77 else 40,30 if number==77 else 40);remaining=100 if number==77 else None
                elif number==79:
                    ps=[portion("A"),portion("B")];als=[allocation("D","80","A","awaiting_recovery")];vector=(80,80,80,0,80,0,0,0);remaining=120
                elif number==80:
                    ps=[portion("A")];ds=[delivery("D","-1",("A",))];als=[];vector=(0,0,0,0,0,0,0,0);balances={"A":None};code="invalid_quantity"
                elif number==81:
                    ps=[portion("A")];als=[allocation("D","81","A")];balances={"A":None};code="allocation_exceeds_delivery"
                elif number==82:als=[allocation("D","80","A","usable")];code="allocation_exceeds_portion"
                elif number==83:
                    ps=[portion("A","0"),portion("B")];ds=[delivery("D","10",("A",))];als=[];vector=(10,10,0,0,0,0,10,10)
                elif number==84:
                    ps=[portion("A","0"),portion("B")];ds=[];als=[];vector=(0,0,0,0,0,0,0,0);remaining=100;balances={"A":0,"B":100}
                elif number==85:
                    ds=[delivery("D","80",("A",),date(2026,10,1),order=None)];als=[];vector=(80,0,0,0,0,0,0,0);remaining=110;balances={"A":10,"B":100}
                elif number==86:ds=[delivery("D","80",("A",),None)];als=[];vector=(80,0,0,0,0,0,0,0)
                elif number==87:
                    ps=[portion("A","50"),portion("B","50")];ds=[delivery("D","80",("A","B"))];als=[allocation("D","30","A","usable"),allocation("D","50","B","usable","30","AL2")];vector=(80,80,80,80,0,0,0,0);remaining=20;balances={"A":20,"B":0}
                elif number in (88,89):
                    ps=[portion("A","0.3"),portion("B")];ds=[delivery("D1","0.1",("A",)),delivery("D2",tiny if number==89 else "0.2",("A",))];als=[];amount=total if number==89 else "0.3";vector=(amount,amount,0 if number==89 else amount,0,0,0 if number==89 else amount,amount if number==89 else 0,amount);remaining=None if number==89 else 100
                req=request(ps,ds,als)
                result=self.check("M-"+str(number),req,vector,remaining=remaining,balances=balances,code=code)
                if number==66:self.assert_c(result)
                if number==75:
                    reversed_req=request(ps[::-1],ds[::-1],als[::-1])
                    other=self.check("M-075-reversed",reversed_req,vector,remaining=remaining,balances=balances)
                    self.assertEqual(pmap(result),pmap(other))

    def test_missing_edges_nodes_and_three_parent_reasons(self):
        for kind in ("edge","node","quantity","membership"):
            with self.subTest(kind=kind):
                ds=[delivery("D","80",("B",),verified=kind!="quantity",date_verified=None if kind in ("edge","node") else True,order=None if kind=="membership" else "PO"),delivery("DC","20",("C",))]
                def change(graph):
                    key=next(x.key for x in graph.fragments.definitions if x.key.parent_fact_ref.source_event_key=="source-D")
                    node=r.fragment_node(key)
                    return replace(graph,dependencies=tuple(e for e in graph.dependencies if not(e.source==r.fact_node(key.parent_fact_ref) and e.target==node)))
                req=request([portion("A"),portion("B"),portion("C")],ds,[allocation("D","80","B","disputed"),allocation("DC","20","C","usable")],
                    omit=("AL-D",) if kind!="edge" else (),exclude={"C":("D",)},graph_change=change if kind=="edge" else None)
                key=req[1]["fragment_manifest"].definitions[0].key
                if kind!="edge":self.assertNotIn(r.fragment_node(key),req[1]["restriction_manifest"].nodes)
                else:self.assertFalse(any(e.source==r.fact_node(key.parent_fact_ref) and e.target==r.fragment_node(key) for e in req[1]["restriction_manifest"].dependencies))
                result=self.check("IR03/"+kind,req,(20 if kind=="quantity" else 100,20,20,20,0,0,0,0),balances={"B":None,"C":80})
                self.assert_c(result)

    def test_content_mismatch_and_bad_types_do_not_upgrade(self):
        for change in ("wrong_fact","wrong_value","false_flag","integer_flag","explicit_missing","none_flag"):
            with self.subTest(change=change):
                req=request([portion("A")],[delivery("D","80",("A",),date(2026,10,1))])
                if change in ("wrong_fact","wrong_value"):
                    claim=next(x for x in req[1]["field_claims"] if x["field_name"]=="actual_date")
                    if change=="wrong_fact":claim["subject_ref"]=("delivery","OTHER","source-OTHER","fv1")
                    else:claim["value"]=date(2026,9,20)
                else:
                    req[0]["deliveries"][0]["actual_date_verified"]={"false_flag":"false","integer_flag":1,"explicit_missing":c.MISSING,"none_flag":None}[change]
                    req[1]["fact_slots"][0]["content"]=deepcopy(req[0]["deliveries"][0],{id(c.MISSING):c.MISSING})
                cover(req[0],req[1],[("facts",),("line","PO","LINE","件"),("portion","PO","LINE","件","A","v1")])
                result=self.check("TR01/TR04/"+change,req,(80,0,0,0,0,0,0,0),balances={"A":None})
                self.assertEqual(result["physical_facts"]["by_date"]["date_unverified"]["verified_quantity"],"80")

    def test_cross_partition_and_reversed_input_keep_c(self):
        def mixed(graph):
            definitions=list(graph.fragments.definitions);a=definitions[0]
            key=replace(a.key,partition_version="pv2")
            b=f.Fragment(key,"40","80","40",a.unit,"G2",("partition-mix","pv2"))
            first=replace(a,end="40",quantity="40")
            bases=(replace(graph.fragments.partition_bases[0],ranges=((first.key.fragment_id,"0","40","40",first.control_group),)),
                   f.PartitionBasis(b.basis_ref,b.key.parent_fact_ref,"pv2",b.unit,"manifest@1","observation@1",("mix","1"),((b.key.fragment_id,"40","80","40","G2"),)))+graph.fragments.partition_bases[1:]
            manifest=replace(graph.fragments,definitions=(first,b)+tuple(definitions[1:]),partition_bases=bases)
            # Deliberately leave graph requirements incomplete, never repair it.
            return replace(graph,fragments=manifest)
        def reversed_mixed(graph):
            graph=mixed(graph)
            return replace(graph,nodes=graph.nodes[::-1],dependencies=graph.dependencies[::-1],proofs=graph.proofs[::-1],
                seeds=graph.seeds[::-1],fragments=replace(graph.fragments,definitions=graph.fragments.definitions[::-1],
                    partition_bases=graph.fragments.partition_bases[::-1],active_relations=graph.fragments.active_relations[::-1]))
        results=[]
        for reverse in (False,True):
            with self.subTest(reverse=reverse):
                req=request([portion("B"),portion("C")],[delivery("D","80",("B",)),delivery("DC","20",("C",))],
                            [allocation("D","80","B","disputed"),allocation("DC","20","C","usable")],exclude={"C":("D",)},
                            graph_change=reversed_mixed if reverse else mixed)
                result=self.check("P202-cross-partition/"+str(reverse),req,(100,100,20,20,0,0,80,80),balances={"B":None,"C":80})
                self.assert_c(result)
                self.assertTrue(any(x.code=="partition_composition_unproven" for x in r.map_restrictions(req[1]["restriction_manifest"]).fragment_validation.issues))
                results.append(result)
        self.assertEqual(pmap(results[0]),pmap(results[1]))

    def test_same_day_and_missing_calendar(self):
        for kind in ("same_day","calendar_missing"):
            with self.subTest(kind=kind):
                same=kind=="same_day"
                req=request([portion("C",commit=ACTUAL if same else START,mode="natural_days" if same else "contract_workdays")],
                            [delivery("DC","20",("C",))],[allocation("DC","20","C","usable")])
                result=self.check("BIZ-01/"+kind,req,(20,20,0,0,0,0,20,20) if same else (20,20,20,20,0,0,0,0),remaining=None if same else 80,balances={"C":None if same else 80})
                row=pmap(result)["C"]
                self.assertEqual(row["overdue_days"]["status"],"undetermined")
                if not same:
                    self.assertEqual(value(row["age_days"]),29)
                    self.assertTrue(any(x["category"]=="capability" for x in row["overdue_days"]["reasons"]))

    def test_preparation_and_snapshot_invariance(self):
        req=request([portion("A")],[delivery("D","20",("A",))],[allocation("D","20","A","usable")])
        prepared=c.prepare_quantity_snapshot(operation="order_item",raw_request=req[0],snapshot_payload=req[1])
        self.assertEqual(len(prepared.snapshot.fact_slots),len(req[0]["deliveries"]))
        self.assertIs(prepared.raw_sources[0],req[0])
        req[0]["deliveries"][0]["delivered_quantity"]="21"
        result=q.evaluate_quantity_snapshot(prepared)
        self.assertEqual(result["result_status"],"rejected")
        self.assertEqual(result["rejection_code"],"input_changed_after_preparation")

    def test_scale_limit_rejects_without_truncation(self):
        req=request([],[],summary=True)
        req[0]["deliveries"]=[delivery(str(i),"1",()) for i in range(33)]
        result=core._summarize_delivery_facts_v2_candidate(raw_request=req[0],snapshot_payload=req[1])
        self.assertEqual(result["result_status"],"rejected")
        self.assertEqual(result["rejection_code"],"synthetic_scale_limit_exceeded")
        self.assertIsNone(result["physical_facts"])
        self.assertEqual(len(req[0]["deliveries"]),33)

    def test_coverage_insufficient_c_independent_and_zero_receipt_scope(self):
        req=request([portion("A"),portion("C")],[delivery("DC","20",("C",))],[allocation("DC","20","C","usable")],cover_line=False)
        result=self.check("TR11-03",req,(20,20,20,20,0,0,0,0),balances={"C":80})
        self.assert_c(result)
        empty=request([portion("A","0")],[])
        result=self.check("TR10-03/true-empty",empty,(0,0,0,0,0,0,0,0),remaining=0,balances={"A":0})
        self.assertEqual(pmap(result)["A"]["age_days"]["status"],"not_applicable")
        self.assertEqual(value(result["line"]["has_verified_arrival"]),False)

    def test_type_preserving_claim_values_and_mixed_decisions(self):
        for mutation in ("bool_quantity","wrong_evidence","opposite_decision"):
            with self.subTest(mutation=mutation):
                req=request([], [delivery("D","0",())],summary=True)
                claim=next(x for x in req[1]["field_claims"] if x["field_name"]=="quantity")
                if mutation=="bool_quantity":claim["value"]=False
                elif mutation=="wrong_evidence":
                    dr=claim["decision_refs"][0];decision=next(x for x in req[1]["verification_decisions"] if x["ref"]==dr)
                    er=decision["evidence_refs"][0];evidence=next(x for x in req[1]["evidence_records"] if x["ref"]==er)
                    evidence["assertions"]=()
                else:
                    dr=claim["decision_refs"][0];decision=next(x for x in req[1]["verification_decisions"] if x["ref"]==dr)
                    new=dict(decision,ref=("opposite","v1"),conclusion=False)
                    req[1]["verification_decisions"]+=(new,);claim["decision_refs"]+=(new["ref"],)
                result=core._summarize_delivery_facts_v2_candidate(raw_request=req[0],snapshot_payload=req[1])
                self.assertEqual(len(result["physical_facts"]["unverified_fact_refs"]),1)
                self.assertEqual(result["result_status"],"partial")

    def test_root_context_versions_missing_none_and_custom_types(self):
        for field,invalid in (("contract_version",None),("business_cutoff",datetime(2026,9,30)),("unit",1),
                              ("fact_collection_ref",None),("business_timezone",NoCompare())):
            with self.subTest(field=field):
                req=request([],[],summary=True);req[1][field]=invalid
                result=core._summarize_delivery_facts_v2_candidate(raw_request=req[0],snapshot_payload=req[1])
                self.assertEqual(result["result_status"],"rejected")
                self.assertIsNone(result["physical_facts"])
                if type(invalid) is NoCompare:self.assertEqual(invalid.calls,0)

    def test_legal_maximum_facts_and_precise_scalar_bound(self):
        req=request([], [delivery("D"+str(i),"1",(),order=None) for i in range(32)],summary=True)
        result=core._summarize_delivery_facts_v2_candidate(raw_request=req[0],snapshot_payload=req[1])
        self.assertEqual(value(result["physical_facts"]["verified_received_quantity"]),"32")
        self.assertEqual(len(result["physical_facts"]["declared_records"]),32)
        with localcontext() as ctx:
            ctx.prec=1024
            self.assertEqual(q.exact_q("1e-128"),Decimal("1e-128"))
        for scalar in ("1e-129","1"*129):
            with self.subTest(scalar=scalar[:12]):
                with self.assertRaisesRegex(ValueError,"synthetic_scale_limit_exceeded"):q.exact_q(scalar)

    def test_partial50_disputed30_may_still_affect_a(self):
        req=request([portion("A"),portion("B",commit=date(2026,9,25)),portion("C")],
            [delivery("D","80",("A","B")),delivery("DC","20",("C",))],
            [allocation("D","50","A","usable"),allocation("D","30","B","disputed","50","AL30"),
             allocation("DC","20","C","usable")])
        result=self.check("TR03-02",req,(100,100,70,70,0,0,30,30),balances={"A":None,"B":None,"C":80})
        self.assert_c(result)
        self.assertEqual(len(result["physical_facts"]["declared_records"]),2)
        self.assertEqual(sorted(x["quantity"] for x in result["quantity_ranges"]),[Decimal(20),Decimal(30),Decimal(50)])

    def test_unproven50_30_does_not_manufacture_usable_subset(self):
        def remove_basis(graph):
            return replace(graph,fragments=replace(graph.fragments,partition_bases=tuple(
                x for x in graph.fragments.partition_bases if x.parent_fact_ref.source_event_key!="source-D")))
        req=request([portion("A"),portion("B",commit=date(2026,9,25)),portion("C")],
            [delivery("D","80",("A","B")),delivery("DC","20",("C",))],
            [allocation("D","50","A","usable"),allocation("D","30","B","disputed","50","AL30"),
             allocation("DC","20","C","usable")],exclude={"C":("D",)},graph_change=remove_basis)
        self.assertFalse(any(x.parent_fact_ref.source_event_key=="source-D" for x in req[1]["fragment_manifest"].partition_bases))
        result=self.check("TR03-03",req,(100,100,20,20,0,0,80,80),balances={"A":None,"B":None,"C":80})
        self.assert_c(result)

    def test_independent_quantity_and_date_qualification(self):
        for future in (False,True):
            with self.subTest(future=future):
                req=request([portion("A","10"),portion("B")],[delivery("D","80",("A",),
                    date(2026,10,1) if future else ACTUAL,verified=False)])
                result=self.check("TR05-quantity-unverified/"+str(future),req,(0,0,0,0,0,0,0,0),
                    remaining=110 if future else None,balances={"A":10 if future else None,"B":100})
                self.assertEqual(len(result["physical_facts"]["unverified_fact_refs"]),1)
                self.assertEqual(value(result["line"]["has_verified_arrival"]),False if future else None)
                self.assertEqual(result["physical_facts"]["declared_records"][0]["quantity"],"80")

    def test_summary_missing_membership_and_duplicate_fact_identity(self):
        req=request([], [delivery("D","80",(),order=None)],summary=True)
        for key in ("order_id","item_id"):
            del req[0]["deliveries"][0][key]
        req[1]["fact_slots"][0]["content"]=deepcopy(req[0]["deliveries"][0])
        cover(req[0],req[1],[("facts",)])
        result=core._summarize_delivery_facts_v2_candidate(raw_request=req[0],snapshot_payload=req[1])
        self.assertEqual(value(result["physical_facts"]["verified_received_quantity"]),"80")
        self.assertEqual(result["physical_facts"]["membership_pending_quantity"],"80")
        missing=[x for x in result["wp1_report"]["observations"] if x["presence"]=="missing"]
        self.assertTrue(any(x["path"]=="deliveries[0].order_id" for x in missing))
        self.assertTrue(any(x["path"]=="deliveries[0].item_id" for x in missing))
        req=request([], [delivery("D","80",(),order=None),delivery("D","80",(),order=None)],summary=True)
        result=core._summarize_delivery_facts_v2_candidate(raw_request=req[0],snapshot_payload=req[1])
        self.assertEqual(result["result_status"],"partial")
        self.assertEqual(len(result["physical_facts"]["declared_records"]),2)
        self.assertEqual(len(result["physical_facts"]["unverified_fact_refs"]),2)
        self.assertEqual(result["physical_facts"]["verified_received_quantity"]["coverage"],"undetermined")
        self.assertTrue(any(x["code"]=="duplicate_delivery_fact" for x in result["issues"]))

    def test_history_and_many_issue_references_do_not_add_quantities(self):
        def references(graph):
            manifest=graph.fragments;key=manifest.definitions[0].key
            reference=f.FragmentReference(key.fragment_id,key.parent_fact_ref,key.partition_version)
            old=replace(manifest.active_relations[0],version="old-version")
            return replace(graph,fragments=replace(manifest,issue_references=(reference,)*5,history_relations=(old,)))
        req=request([portion("C")],[delivery("DC","20",("C",))],[allocation("DC","20","C","usable")],graph_change=references)
        result=self.check("TR09/TR11-history-unique",req,(20,20,20,20,0,0,0,0),remaining=80,balances={"C":80})
        self.assert_c(result)
        self.assertEqual(len(result["historical_relations"]),1)
        self.assertEqual(len(result["quantity_ranges"]),1)

    def test_due_mask_and_age_capability_are_metric_specific(self):
        def due_only(graph):
            node=r.fragment_node(graph.fragments.definitions[0].key)
            return replace(graph,seeds=graph.seeds+(r.RestrictionSeed("due-only","due_basis_missing",node),))
        req=request([portion("C")],[delivery("DC","20",("C",))],[allocation("DC","20","C","usable")],graph_change=due_only)
        result=self.check("P201-due-mask",req,(20,20,20,20,0,0,0,0),remaining=80,balances={"C":80})
        row=pmap(result)["C"]
        self.assertEqual(value(row["age_days"]),29)
        self.assertEqual(row["overdue_quantity"]["status"],"undetermined")
        self.assertEqual(row["overdue_days"]["status"],"undetermined")
        req=request([portion("C")],[delivery("DC","20",("C",))],[allocation("DC","20","C","usable")])
        req[1]["rule_binding"]["age_rule_version"]="unimplemented-age-rule"
        cover(req[0],req[1],[("facts",),("line","PO","LINE","件"),("portion","PO","LINE","件","C","v1")])
        result=self.check("DR03-independent-capability",req,(20,20,20,20,0,0,0,0),remaining=80,balances={"C":80})
        row=pmap(result)["C"]
        self.assertEqual(row["age_days"]["status"],"unsupported")
        self.assertEqual(value(row["overdue_quantity"]),"80")
        self.assertEqual(value(row["overdue_days"]),20)

    def test_calendar_content_incomplete_is_not_algorithm_only_limitation(self):
        req=request([portion("C",mode="contract_workdays")],[delivery("DC","20",("C",))],
            [allocation("DC","20","C","usable")],calendar=True)
        original=req[1]["rule_binding"]["calendar_content"]
        bad=c.FrozenContent(tuple((k,v[:-1] if k=="days" else v) for k,v in original.entries))
        req[1]["rule_binding"]["calendar_content"]=bad
        req[1]["field_claims"]=tuple(x for x in req[1]["field_claims"] if x["field_name"]!="calendar_content")
        attest(req[1],("calendar",),"calendar_content",bad)
        cover(req[0],req[1],[("facts",),("line","PO","LINE","件"),("portion","PO","LINE","件","C","v1")])
        result=self.check("DR03-calendar-incomplete",req,(20,20,20,20,0,0,0,0),remaining=80,balances={"C":80})
        row=pmap(result)["C"]
        self.assertEqual(value(row["age_days"]),29)
        self.assertEqual(row["overdue_quantity"]["status"],"undetermined")
        self.assertTrue(any(x["code"]=="contract_calendar_basis_missing" for x in row["overdue_quantity"]["reasons"]))
        self.assertTrue(any(x["category"]=="capability" for x in row["overdue_quantity"]["reasons"]))

    def test_bounded_content_and_manifest_limits_reject_without_truncating(self):
        for field in ("portions","definitions","active_relations","history_relations","nodes","dependencies","seeds",
                      "evidence_records","verification_decisions","allocations","calendar_days","scope_refs","depth"):
            with self.subTest(field=field):
                req=request([portion("C")],[delivery("DC","20",("C",))],[allocation("DC","20","C","usable")])
                raw,payload=req;manifest=payload["fragment_manifest"];graph=payload["restriction_manifest"]
                if field in ("portions","allocations"):
                    raw[field]=[raw[field][0]]*((32 if field=="portions" else 128)+1)
                elif field in ("definitions","active_relations","history_relations"):
                    rows=getattr(manifest,field) or manifest.active_relations
                    payload["fragment_manifest"]=replace(manifest,**{field:rows*(q.LIMITS[field]+1)})
                elif field in ("nodes","dependencies","seeds"):
                    rows=getattr(graph,field) or (r.RestrictionSeed("x","time_conflict",r.fragment_node(manifest.definitions[0].key)),)
                    payload["restriction_manifest"]=replace(graph,**{field:rows*(q.LIMITS[field]+1)})
                elif field in ("evidence_records","verification_decisions"):
                    payload[field]=(payload[field][0],)*513
                elif field=="calendar_days":payload["rule_binding"]["calendar_content"]=q.freeze({"days":(True,)*3661})
                elif field=="scope_refs":
                    scope=graph.scopes[0];payload["restriction_manifest"]=replace(graph,scopes=(replace(scope,candidate_targets=(pnode("C"),)*2049),))
                else:
                    nested=True
                    for _ in range(18):nested=c.FrozenContent((("next",nested),))
                    payload["rule_binding"]["deep"]=nested
                result=evaluate(req)
                self.assertEqual(result["result_status"],"rejected")
                self.assertEqual(result["rejection_code"],"synthetic_scale_limit_exceeded")
                self.assertIsNone(result["line"])

    def test_bad_record_identity_does_not_invoke_custom_comparison(self):
        req=request([portion("B"),portion("C")],[delivery("D","80",("B",)),delivery("DC","20",("C",))],
            [allocation("D","80","B","disputed"),allocation("DC","20","C","usable")],exclude={"C":("D",)})
        bad=NoCompare()
        req[0]["deliveries"][0]["source_event_key"]=bad
        req[1]["fact_slots"][0]["content"]["source_event_key"]=bad
        result=evaluate(req)
        self.assertEqual(bad.calls,0)
        self.assertNotEqual(result["result_status"],"supported")
        self.assertTrue(result["rejected_records"])
        self.assertTrue(any(x["code"]=="record_identity_binding_conflict" for x in result["issues"]))
        self.assertFalse(result["formal_eligible"])

    def test_structure_collection_failure_is_request_rejection(self):
        req=request([portion("C")],[delivery("DC","20",("C",))],[allocation("DC","20","C","usable")])
        req[1]["fragment_manifest"]=replace(req[1]["fragment_manifest"],facts=None)
        result=evaluate(req)
        self.assertEqual(result["result_status"],"rejected")
        self.assertEqual(result["rejection_code"],"invalid_quantity_structure_collection")
        self.assertIsNone(result["line"])


class TraceIntegrationTests(unittest.TestCase):
    def cycle(self, second_actual=ACTUAL, conflicting_reason_ids=True):
        def add(graph):
            a,b=(r.fragment_node(x.key) for x in graph.fragments.definitions[:2])
            edges=[];proofs=[]
            for index,(source,target) in enumerate(((a,b),(b,a))):
                ref=("cycle-"+str(index),"v1");metrics=tuple(sorted(r.METRICS))
                edges.append(r.Dependency(source,target,metrics,ref))
                proofs.append(r.BindingProof(ref,"dependency",source,(r.token(target),metrics),"manifest@1","observation@1",("cycle-evidence","v1")))
            seeds=tuple(replace(seed,reason_id="shared-root") for seed in graph.seeds) if conflicting_reason_ids else graph.seeds
            return replace(graph,dependencies=graph.dependencies+tuple(edges),proofs=graph.proofs+tuple(proofs),seeds=seeds)
        return request([portion("A"),portion("B"),portion("C")],
             [delivery("D1","40",("A",)),delivery("D2","30",("B",),second_actual),delivery("DC","20",("C",))],
             [allocation("D1","40","A"),allocation("D2","30","B"),allocation("DC","20","C","usable")],graph_change=add)

    def test_complete_origins_cycles_and_reverse_are_finite(self):
        req=self.cycle();graph=req[1]["restriction_manifest"]
        result=r.map_restrictions(graph)
        effect=next(x for x in result.causal_trace if x.node==pnode("A") and x.metric=="portion_balance" and x.reason_id=="shared-root")
        self.assertEqual(len(effect.origins),2)
        self.assertTrue(any(e.source.kind=="fragment" and e.target.kind=="fragment" for e in effect.causal_edges))
        reverse=replace(graph,nodes=graph.nodes[::-1],proofs=graph.proofs[::-1],dependencies=graph.dependencies[::-1],seeds=graph.seeds[::-1],closures=graph.closures[::-1])
        other=r.map_restrictions(reverse)
        self.assertEqual(result.causal_trace,other.causal_trace)
        self.assertEqual(result.closure_trace,other.closure_trace)
        self.assertEqual(result.node_restrictions,other.node_restrictions)
        self.assertEqual(result.propagation_steps,other.propagation_steps)
        self.assertLessEqual(len(result.causal_trace),len(graph.nodes)*len(r.METRICS)*len(graph.seeds))

    def test_repeated_seed_reference_does_not_create_quantity_or_trace_roots(self):
        graph=self.cycle()[1]["restriction_manifest"]
        result=r.map_restrictions(graph)
        repeated=r.map_restrictions(replace(graph,seeds=graph.seeds+graph.seeds))
        self.assertEqual(result.causal_trace,repeated.causal_trace)
        self.assertEqual(result.node_restrictions,repeated.node_restrictions)
        self.assertEqual(result.propagation_steps,repeated.propagation_steps)

    def test_automatic_and_manual_origin_are_both_preserved(self):
        req=request([portion("A")],[delivery("D","80",("A",))])
        graph=req[1]["restriction_manifest"]
        first=graph.fragments.definitions[0]
        bad=replace(graph.fragments,definitions=graph.fragments.definitions+(replace(first,quantity="79"),))
        graph=replace(graph,fragments=bad)
        result=r.map_restrictions(graph)
        automatic=next(o.seed for trace in result.causal_trace for o in trace.origins if o.namespace=="fragment_validation")
        mixed=r.map_restrictions(replace(graph,seeds=graph.seeds+(automatic,)))
        roots={o.namespace for trace in mixed.causal_trace for o in trace.origins if o.seed==automatic}
        self.assertEqual(roots,{"input_seed","fragment_validation"})

    def test_closure_failure_sources_and_no_graph_repair(self):
        req=request([portion("B"),portion("C")],[delivery("D","80",("B",),date_verified=None),delivery("DC","20",("C",))],
                    [allocation("D","80","B","disputed"),allocation("DC","20","C","usable")],omit=("AL-D",),exclude={"C":("D",)})
        graph=req[1]["restriction_manifest"];before=deepcopy(graph)
        result=r.map_restrictions(graph)
        b=next(x for x in result.closure_trace if x.node==pnode("B"))
        ctrace=next(x for x in result.closure_trace if x.node==pnode("C"))
        self.assertFalse(b.passed);self.assertTrue(b.unresolved_sources);self.assertTrue(ctrace.passed)
        self.assertEqual(graph,before)

    def test_period_projection_uses_all_origins_not_convenient_reason_path(self):
        # Different valid reason identities; the separate trace test above
        # deliberately tests conflicting identities and never grants inclusion.
        req=self.cycle(second_actual=date(2026,10,1),conflicting_reason_ids=False)
        result=QuantityIntegrationTests().check("DR02-mixed-origin-period-projection",req,
            (90,60,60,20,0,40,0,40),remaining=240,balances={"A":None,"B":None,"C":80})
        QuantityIntegrationTests().assert_c(result)
        graph_result=r.map_restrictions(req[1]["restriction_manifest"])
        origins={o for t in graph_result.causal_trace if t.node==pnode("B")
            and t.metric=="portion_balance" for o in t.origins}
        self.assertEqual(len(origins),2)
        self.assertEqual({o.seed.subject.identity[0] for o in origins},{"source-D1","source-D2"})


IR_RESULTS = []


def ir_cover(req):
    scopes=[("facts",),("line","PO","LINE","件")]
    scopes.extend(("portion",)+x["ref"] for x in req[1]["portion_slots"] or ())
    cover(req[0],req[1],scopes)


def ir_relation_claim(req, aid, target):
    slot=next(x for x in req[1]["relation_slots"] if x["id"]==aid)
    key=slot["ref"][2]
    subject=("relation",aid,slot["ref"][1],key.parent_fact_ref.source_event_key)
    req[1]["field_claims"]=tuple(x for x in req[1]["field_claims"] if x["subject_ref"]!=subject)
    attest(req[1],subject,"relation_content",q.freeze(dict(record=q.freeze(slot["content"]),key=q.freeze(key),target=target)))


class IRRegressionTests(unittest.TestCase):
    def run_case(self, label, req):
        before=deepcopy(req,{id(c.MISSING):c.MISSING})
        result=evaluate(req)
        self.assertEqual(req,before)
        IR_RESULTS.append(dict(case=label,actual={k:q.plain(result[k]) for k in
            ("result_status","line","physical_facts","portions","issues","capacity_checks","quantity_ranges","rejected_records","basis_catalog")}))
        return result

    def test_ir01_target_and_graph_parent_conflicts_gate_qualification(self):
        for conflict in ("target","graph_parent"):
            with self.subTest(conflict=conflict):
                req=request([portion("A"),portion("B"),portion("C")],
                    [delivery("D","80",("A","B")),delivery("DC","20",("C",))],
                    [allocation("D","80","B","usable"),allocation("DC","20","C","usable")])
                if conflict=="target":
                    req[0]["allocations"][0]["portion_id"]="A"
                    req[1]["relation_slots"][0]["content"]=deepcopy(req[0]["allocations"][0])
                    ir_relation_claim(req,"AL-D",pnode("B").identity)
                else:
                    graph=req[1]["restriction_manifest"]
                    facts=tuple(replace(x,quantity="81") if x.delivery_id=="D" else x for x in graph.fragments.facts)
                    req[1]["restriction_manifest"]=replace(graph,fragments=replace(graph.fragments,facts=facts))
                    self.assertEqual(req[1]["fragment_manifest"].facts[0].quantity,"80")
                    self.assertEqual(req[1]["restriction_manifest"].fragments.facts[0].quantity,"81")
                ir_cover(req)
                result=self.run_case("IR01-"+conflict,req)
                self.assertEqual([value(result["line"][k]) for k in ("F","T","W","Cc","Z")],["100","100","20","20","80"])
                self.assertIsNone(value(result["line"]["remaining_quantity"]))
                self.assertIsNone(value(pmap(result)["B"]["remaining_quantity"]))
                QuantityIntegrationTests().assert_c(result)

    def test_ir02_unreferenced_opposition_cannot_be_hidden(self):
        req=request([portion("C")],[delivery("DC","20",("C",))],[allocation("DC","20","C","usable")])
        claim=next(x for x in req[1]["field_claims"] if x["field_name"]=="actual_date")
        positive=next(x for x in req[1]["verification_decisions"] if x["ref"]==claim["decision_refs"][0])
        negative=dict(positive,ref=("unlisted-negative","v1"),conclusion=False)
        req[1]["verification_decisions"]+=(negative,)
        self.assertNotIn(negative["ref"],claim["decision_refs"])
        result=self.run_case("IR02-unlisted-opposition",req)
        self.assertEqual([value(result["line"][k]) for k in ("F","T","W")],["20","0","0"])
        self.assertEqual(result["physical_facts"]["by_date"]["date_unverified"]["verified_quantity"],"20")
        self.assertIsNone(value(pmap(result)["C"]["remaining_quantity"]))

    def test_ir03_unknown_candidate_not_removed_from_capacity(self):
        req=request([portion("A"),portion("B")],[delivery("D","80",("A",))],[allocation("D","80","A")])
        req[0]["deliveries"][0]["candidate_portion_ids"]=("A","UNKNOWN")
        req[1]["fact_slots"][0]["content"]=deepcopy(req[0]["deliveries"][0])
        ir_cover(req)
        self.assertFalse(any(n.kind=="portion" and n.identity[3]=="UNKNOWN" for n in req[1]["restriction_manifest"].nodes))
        result=self.run_case("IR03-unknown-candidate",req)
        self.assertEqual([value(result["line"][k]) for k in ("F","T","W","Ep","Z")],["80","80","0","0","80"])
        self.assertIsNone(value(result["line"]["remaining_quantity"]))
        self.assertTrue(any(x["capacity_status"]=="undetermined" for x in result["capacity_checks"]))

    def test_ir04_invalid_float_a_must_preserve_independent_c(self):
        req=request([portion("A"),portion("C")],[delivery("D","80",("A",)),delivery("DC","20",("C",))],
            [allocation("D","80","A","usable"),allocation("DC","20","C","usable")])
        req[0]["allocations"][0]["allocated_quantity"]=80.0
        req[1]["relation_slots"][0]["content"]=deepcopy(req[0]["allocations"][0])
        ir_cover(req)
        result=self.run_case("IR04-float-a-independent-c",req)
        self.assertTrue(result["rejected_records"])
        self.assertIs(type(req[0]["allocations"][0]["allocated_quantity"]),float)
        self.assertIsNone(value(pmap(result)["A"]["remaining_quantity"]))
        QuantityIntegrationTests().assert_c(result)
        self.assertEqual([value(result["line"][k]) for k in ("F","T","W","Cc","Z")],["100","100","20","20","80"])

    def test_ir05_actual_basis_and_incomplete_zero_subset(self):
        req=request([portion("C")],[delivery("DC","20",("C",))],[allocation("DC","20","C","usable")])
        result=self.run_case("IR05-supported-basis",req)
        row=pmap(result)["C"]
        for name in ("remaining_quantity","age_days","overdue_quantity","overdue_days"):
            self.assertTrue(row[name]["basis_refs"],name)
            self.assertEqual(row[name]["scope_ref"],pnode("C").identity)
            self.assertEqual(row[name]["coverage"],"complete")
        req=request([portion("A")],[delivery("D","80",("A",),None)])
        result=self.run_case("IR05-zero-subset-not-whole-zero",req)
        for name in ("T","W"):
            self.assertEqual(value(result["line"][name]),"0")
            self.assertEqual(result["line"][name]["basis_type"],"verified_subset")
            self.assertNotEqual(result["line"][name]["coverage"],"complete")
            self.assertTrue(result["line"][name]["scope_ref"])

    def test_ir01_consistent_and_version_conflict_controls(self):
        for mismatch in (False,True):
            with self.subTest(mismatch=mismatch):
                req=request([portion("B"),portion("C")],[delivery("D","80",("B",)),delivery("DC","20",("C",))],
                    [allocation("D","80","B","usable"),allocation("DC","20","C","usable")])
                if mismatch:
                    graph=req[1]["restriction_manifest"]
                    relations=tuple(replace(x,version="v2") if x.fragment.parent_fact_ref.source_event_key=="source-D" else x
                                    for x in graph.fragments.active_relations)
                    manifest=replace(graph.fragments,active_relations=relations)
                    req[1]["fragment_manifest"]=manifest
                    req[1]["restriction_manifest"]=replace(graph,fragments=manifest)
                    ir_cover(req)
                result=self.run_case("IR01-version/"+str(mismatch),req)
                self.assertEqual(value(result["line"]["Cc"]),"20" if mismatch else "100")
                self.assertEqual(value(result["line"]["remaining_quantity"]),None if mismatch else "100")
                self.assertEqual(value(pmap(result)["B"]["remaining_quantity"]),None if mismatch else "20")
                QuantityIntegrationTests().assert_c(result)

    def test_ir02_opposition_reference_and_order_controls(self):
        outputs=[]
        for listed in (False,True):
            for reverse in (False,True):
                with self.subTest(listed=listed,reverse=reverse):
                    req=request([portion("C")],[delivery("DC","20",("C",))],[allocation("DC","20","C","usable")])
                    claim=next(x for x in req[1]["field_claims"] if x["field_name"]=="actual_date")
                    decision=next(x for x in req[1]["verification_decisions"] if x["ref"]==claim["decision_refs"][0])
                    opposed=dict(decision,ref=("opposed","v2"),conclusion=False)
                    req[1]["verification_decisions"]+=(opposed,)
                    if listed:claim["decision_refs"]+=(opposed["ref"],)
                    if reverse:
                        req[1]["verification_decisions"]=req[1]["verification_decisions"][::-1]
                        req[1]["evidence_records"]=req[1]["evidence_records"][::-1]
                        claim["decision_refs"]=claim["decision_refs"][::-1]
                    result=self.run_case("IR02-order/"+str((listed,reverse)),req)
                    self.assertEqual([value(result["line"][k]) for k in ("F","T","W")],["20","0","0"])
                    self.assertIsNone(value(pmap(result)["C"]["remaining_quantity"]))
                    actual={ref for row in result["basis_catalog"] for ref in row["actual_refs"]}
                    self.assertIn(("decision","opposed","v2"),actual)
                    outputs.append(pmap(result))
        self.assertTrue(all(x==outputs[0] for x in outputs))

    def test_ir02_unrelated_inactive_and_historical_decisions_do_not_pollute(self):
        for kind in ("field","fact_version","value","context","scope","inactive"):
            with self.subTest(kind=kind):
                req=request([portion("C")],[delivery("DC","20",("C",))],[allocation("DC","20","C","usable")])
                claim=next(x for x in req[1]["field_claims"] if x["field_name"]=="actual_date")
                decision=next(x for x in req[1]["verification_decisions"] if x["ref"]==claim["decision_refs"][0])
                body=dict(decision["claim_content"].entries)
                opposed=dict(decision,ref=("irrelevant","v1"),conclusion=False)
                if kind=="field":body["field_name"]="supplier_shipping_date"
                elif kind=="fact_version":body["subject_ref"]=body["subject_ref"][:-1]+("old-version",)
                elif kind=="value":body["value"]=date(2026,10,1)
                elif kind=="context":opposed["observation_ref"]="old-observation"
                elif kind=="scope":body["scope_ref"]=("another-scope","v1")
                else:opposed["status"]="withdrawn"
                opposed["claim_content"]=q.freeze(body)
                req[1]["verification_decisions"]+=(opposed,)
                result=self.run_case("IR02-unrelated/"+kind,req)
                if kind=="scope":
                    # TV-01: label inequality is not evidence of disjointness.
                    self.assertTrue(any(x["code"]=="qualification_scope_relation_unproven" for x in result["qualification_issues"]))
                    self.assertEqual([value(result["line"][k]) for k in ("F","T","W","Cc","Rr","Ep","Z","Pp")],
                                     ["20","0","0","0","0","0","0","0"])
                    self.assertEqual(result["physical_facts"]["by_date"]["date_unverified"]["verified_quantity"],"20")
                    self.assertIsNone(value(result["line"]["remaining_quantity"]))
                    self.assertIsNone(value(result["line"]["has_verified_arrival"]))
                    for metric in ("remaining_quantity","age_days","overdue_quantity","overdue_days"):
                        row=pmap(result)["C"][metric]
                        self.assertIsNone(value(row));self.assertEqual(row["status"],"undetermined")
                        self.assertEqual(row["scope_ref"],pnode("C").identity)
                        self.assertEqual(row["coverage"],"undetermined");self.assertTrue(row["basis_refs"])
                    self.assertEqual(result["line"]["T"]["scope_ref"],("line","PO","LINE","件"))
                    self.assertEqual(result["line"]["T"]["coverage"],"undetermined")
                    self.assertTrue(any(("decision","irrelevant","v1") in row["actual_refs"] for row in result["basis_catalog"]))
                    self.assertTrue(any(("decision",)+claim["decision_refs"][0] in row["actual_refs"] for row in result["basis_catalog"]))
                else:
                    QuantityIntegrationTests().assert_c(result)
                    self.assertEqual(value(result["line"]["W"]),"20")
                    self.assertFalse(any(("decision","irrelevant","v1") in row["actual_refs"] for row in result["basis_catalog"]))

    def test_ir03_resolved_and_unresolved_candidate_controls(self):
        for candidates in (("A",),("A","B"),("A","UNKNOWN"),("UNKNOWN",)):
            with self.subTest(candidates=candidates):
                req=request([portion("A"),portion("B")],[delivery("D","80",("A",))],[allocation("D","80","A")])
                req[0]["deliveries"][0]["candidate_portion_ids"]=candidates
                req[1]["fact_slots"][0]["content"]=deepcopy(req[0]["deliveries"][0])
                ir_cover(req)
                result=self.run_case("IR03-candidates/"+str(candidates),req)
                unknown="UNKNOWN" in candidates
                self.assertEqual([value(result["line"][k]) for k in ("T","W","Ep","Z")],
                                 ["80","0","0","80"] if unknown else ["80","80","80","0"])
                self.assertEqual(value(result["line"]["remaining_quantity"]),None if unknown else "120")
                checks=[x for x in result["capacity_checks"] if x["kind"]=="shared_capacity"]
                self.assertTrue(any(x["capacity_status"]==("undetermined" if unknown else "feasible") for x in checks))
                if unknown:
                    self.assertTrue(any(("unresolved_candidate","UNKNOWN") in x["unresolved_capacity_refs"] for x in checks))
                    self.assertTrue(any(x["capacity_coverage"]=="undetermined" for x in checks))
                self.assertFalse(any(n.kind=="portion" and n.identity[3]=="UNKNOWN" for n in req[1]["restriction_manifest"].nodes))

    def test_ir03_reliable_violation_and_unknown_capacity_coexist_in_both_orders(self):
        results=[]
        for reverse in (False,True):
            with self.subTest(reverse=reverse):
                ds=[delivery("D","80",("A",)),delivery("DU","1",("A",))]
                als=[allocation("D","80","A"),allocation("DU","1","A")]
                req=request([portion("A","10"),portion("B")],ds[::-1] if reverse else ds,als[::-1] if reverse else als)
                index=next(i for i,x in enumerate(req[0]["deliveries"]) if x["delivery_id"]=="DU")
                req[0]["deliveries"][index]["candidate_portion_ids"]=("A","UNKNOWN")
                slot=next(x for x in req[1]["fact_slots"] if x["id"]=="DU")
                slot["content"]=deepcopy(req[0]["deliveries"][index]);ir_cover(req)
                result=self.run_case("IR03-violation-plus-unknown/"+str(reverse),req)
                self.assertEqual([value(result["line"][k]) for k in ("F","T","W","Z")],["81","81","0","81"])
                self.assertIsNone(value(result["line"]["remaining_quantity"]))
                check=next(x for x in result["capacity_checks"] if x["kind"]=="shared_capacity")
                self.assertEqual(check["capacity_status"],"infeasible")
                self.assertEqual(check["demand_period_status"],"complete")
                self.assertTrue(check["violation_witnesses"])
                self.assertIn(("unresolved_candidate","UNKNOWN"),check["unresolved_capacity_refs"])
                self.assertNotIn(("unresolved_candidate","UNKNOWN"),dict(check["capacities"]))
                results.append(pmap(result))
        self.assertEqual(results[0],results[1])

    def test_ir04_independence_reverse_and_lossless_rejected_float_controls(self):
        positive=[]
        for independent in (False,True):
            for reverse in (False,True):
                with self.subTest(independent=independent,reverse=reverse):
                    ds=[delivery("D","80",("A",)),delivery("DC","20",("C",))]
                    als=[allocation("D","80","A","usable"),allocation("DC","20","C","usable")]
                    req=request([portion("A"),portion("C")],ds[::-1] if reverse else ds,als[::-1] if reverse else als)
                    row=next(x for x in req[0]["allocations"] if x["allocation_id"]=="AL-D")
                    row["allocated_quantity"]=80.0
                    next(x for x in req[1]["relation_slots"] if x["id"]=="AL-D")["content"]=deepcopy(row)
                    if not independent:
                        graph=req[1]["restriction_manifest"]
                        req[1]["restriction_manifest"]=replace(graph,closures=tuple(x for x in graph.closures if x.subject!=pnode("C")))
                    ir_cover(req)
                    result=self.run_case("IR04-independent/"+str((independent,reverse)),req)
                    if independent:
                        QuantityIntegrationTests().assert_c(result);positive.append(pmap(result)["C"])
                    else:
                        self.assertTrue(all(value(pmap(result)["C"][k]) is None for k in
                            ("remaining_quantity","age_days","overdue_quantity","overdue_days")))
                    rejected=next(x for x in result["rejected_records"] if x["group"]=="allocations")
                    opaque=rejected["content"]["allocated_quantity"]
                    self.assertIs(type(opaque),c.OpaqueInput)
                    self.assertEqual(opaque.captured_scalar,("float.hex",float.hex(80.0)))
                    self.assertFalse(q.safe(opaque));self.assertFalse(q.same(opaque,opaque))
                    self.assertIs(type(row["allocated_quantity"]),float)
        self.assertEqual(positive[0],positive[1])

    def test_ir05_only_actual_basis_versions_are_resolved(self):
        req=request([portion("C")],[delivery("DC","20",("C",))],[allocation("DC","20","C","usable")])
        attest(req[1],("unused","subject"),"unused_field",True)
        unused=req[1]["verification_decisions"][-1]["ref"]
        original=self.run_case("IR05-original-version",req)
        self.assertFalse(any(("decision",)+unused in row["actual_refs"] for row in original["basis_catalog"]))
        claim=next(x for x in req[1]["field_claims"] if x["field_name"]=="actual_date")
        old=claim["decision_refs"][0]
        decision=next(x for x in req[1]["verification_decisions"] if x["ref"]==old)
        old_e=decision["evidence_refs"][0]
        new=(old[0],"v2");new_e=(old_e[0],"v2")
        decision["ref"]=new;decision["evidence_refs"]=(new_e,);claim["decision_refs"]=(new,)
        next(x for x in req[1]["evidence_records"] if x["ref"]==old_e)["ref"]=new_e
        current=self.run_case("IR05-version-v2",req)
        QuantityIntegrationTests().assert_c(current)
        selected={ref for row in current["basis_catalog"] for ref in row["actual_refs"]}
        self.assertIn(("decision",)+new,selected);self.assertIn(("evidence",)+new_e,selected)
        self.assertNotIn(("decision",)+old,selected);self.assertNotIn(("evidence",)+old_e,selected)
        self.assertFalse(any(("decision",)+unused in row["actual_refs"] for row in current["basis_catalog"]))
        catalog={row["basis_ref"]:row for row in current["basis_catalog"]}
        for field in ("remaining_quantity","age_days","overdue_quantity","overdue_days"):
            metric=pmap(current)["C"][field]
            for ref in metric["basis_refs"]:
                if ref[0] in ("qualification","graph_scope"):
                    self.assertIn(ref,catalog);self.assertTrue(catalog[ref]["actual_refs"])
                elif ref[0]=="rule":self.assertEqual(current["rule_binding"][ref[1]],ref[2])

    def test_ir05_zero_subset_coverage_contrasted_with_reliable_empty_scope(self):
        for unknown in (False,True):
            with self.subTest(unknown=unknown):
                req=request([portion("A")],[delivery("D","80",("A",),None)] if unknown else [])
                result=self.run_case("IR05-zero-coverage/"+str(unknown),req)
                for name in ("T","W"):
                    metric=result["line"][name]
                    self.assertEqual(value(metric),"0")
                    self.assertEqual(metric["coverage"],"undetermined" if unknown else "complete")
                    self.assertEqual(metric["basis_type"],"verified_subset")
                    self.assertEqual(metric["scope_ref"],("line","PO","LINE","件"))
                    self.assertTrue(metric["basis_refs"])
                self.assertEqual(value(result["line"]["remaining_quantity"]),None if unknown else "100")

    def test_ir02_opposition_with_different_precision_is_still_applicable(self):
        req=request([portion("C")],[delivery("DC","20",("C",))],[allocation("DC","20","C","usable")])
        claim=next(x for x in req[1]["field_claims"] if x["field_name"]=="actual_date")
        positive=next(x for x in req[1]["verification_decisions"] if x["ref"]==claim["decision_refs"][0])
        body=dict(positive["claim_content"].entries);body["precision"]="minute"
        opposed=dict(positive,ref=("precision-opposition","v1"),conclusion=False,
                     claim_content=q.freeze(body),evidence_refs=(("precision-evidence","v1"),))
        req[1]["verification_decisions"]+=(opposed,)
        req[1]["evidence_records"]+=(dict(ref=("precision-evidence","v1"),assertions=(q.freeze(body),)),)
        result=self.run_case("IR02-unlisted-different-precision",req)
        self.assertEqual([value(result["line"][k]) for k in ("F","T","W")],["20","0","0"])
        self.assertIsNone(value(pmap(result)["C"]["remaining_quantity"]))

    def test_ir03_illegal_candidate_container_does_not_gain_capacity(self):
        for candidates in (None,["A"],True):
            with self.subTest(candidate_type=type(candidates).__name__):
                req=request([portion("A")],[delivery("D","80",("A",))],[allocation("D","80","A")])
                req[0]["deliveries"][0]["candidate_portion_ids"]=candidates
                req[1]["fact_slots"][0]["content"]=deepcopy(req[0]["deliveries"][0]);ir_cover(req)
                result=self.run_case("IR03-invalid-container/"+type(candidates).__name__,req)
                self.assertEqual([value(result["line"][k]) for k in ("T","W","Z")],["80","0","80"])
                self.assertIsNone(value(result["line"]["remaining_quantity"]))
                self.assertTrue(any(x["code"]=="unknown_candidate_reference" for x in result["issues"]))

    def test_ir03_unknown_scope_c_requires_explicit_independent_basis(self):
        for independent in (False,True):
            with self.subTest(independent=independent):
                req=request([portion("A"),portion("C")],[delivery("D","80",("A",)),delivery("DC","20",("C",))],
                    [allocation("D","80","A"),allocation("DC","20","C","usable")],
                    exclude={"C":("D",)} if independent else None)
                req[0]["deliveries"][0]["candidate_portion_ids"]=("A","UNKNOWN")
                req[1]["fact_slots"][0]["content"]=deepcopy(req[0]["deliveries"][0]);ir_cover(req)
                result=self.run_case("IR03-unknown-scope-independent-c/"+str(independent),req)
                self.assertEqual([value(result["line"][k]) for k in ("F","T","W","Cc","Z")],["100","100","20","20","80"])
                if independent:QuantityIntegrationTests().assert_c(result)
                else:self.assertIsNone(value(pmap(result)["C"]["remaining_quantity"]))

    def test_ir05_catalog_content_locator_and_commitment_subset_coverage(self):
        req=request([portion("C")],[delivery("DC","20",("C",))],[allocation("DC","20","C","usable")])
        result=self.run_case("IR05-catalog-content-locator",req)
        for row in result["basis_catalog"]:
            for binding in row["bindings"]:
                location=binding.get("full_content_location")
                if location is not None:
                    self.assertEqual(location[:3],("raw_capture",1,"verification_decisions"))
                    stored=next(x for x in result["raw_capture"][1]["verification_decisions"] if x["ref"]==location[3])
                    self.assertEqual(stored["claim_content"]["subject_ref"],binding["subject_ref"])
                    self.assertEqual(stored["claim_content"]["field_name"],binding["field_name"])
                    if binding["field_name"]!="coverage":self.assertEqual(stored["claim_content"]["value"],binding["value"])
        req=request([portion("A")],[])
        req[0]["commitment_scope_complete"]=False;ir_cover(req)
        result=self.run_case("IR05-commitment-known-subset",req)
        metric=result["line"]["effective_commitment_quantity"]
        self.assertEqual(value(metric),"100")
        self.assertEqual(metric["status"],"supported")
        self.assertEqual(metric["basis_type"],"verified_subset")
        self.assertEqual(metric["coverage"],"undetermined")
        self.assertIsNone(value(result["line"]["remaining_quantity"]))


RS_RESULTS = []


def rs_opposition(req, *, fields="absent", listed=False, scope_ref="absent", raw_fields=False):
    claim=next(x for x in req[1]["field_claims"] if x["field_name"]=="actual_date")
    support=next(x for x in req[1]["verification_decisions"] if x["ref"]==claim["decision_refs"][0])
    body=dict(support["claim_content"].entries)
    if fields!="absent":body["scope_fields"]=fields
    if scope_ref!="absent":body["scope_ref"]=scope_ref
    body=body if raw_fields else q.freeze(body)
    opposed=dict(support,ref=("scope-opposition","v2"),conclusion=False,
                 claim_content=body,evidence_refs=(("scope-opposition-source","v2"),))
    req[1]["verification_decisions"]+=(opposed,)
    req[1]["evidence_records"]+=(dict(ref=("scope-opposition-source","v2"),assertions=(body,)),)
    if listed:claim["decision_refs"]+=(opposed["ref"],)
    return claim,opposed


def rs_invalid_a(value, independent=True):
    req=request([portion("A"),portion("C")],[delivery("DA","20",("A",)),delivery("DC","20",("C",))],
        [allocation("DA","20","A","usable"),allocation("DC","20","C","usable")])
    req[0]["allocations"][0]["allocated_quantity"]=value
    req[1]["relation_slots"][0]["content"]["allocated_quantity"]=value
    if not independent:
        graph=req[1]["restriction_manifest"]
        req[1]["restriction_manifest"]=replace(graph,closures=tuple(x for x in graph.closures if x.subject!=pnode("C")))
    ir_cover(req)
    return req


class ScopeScalarRegressionTests(unittest.TestCase):
    def record(self,label,req):
        before=q.plain(q.freeze(req))
        result=evaluate(req)
        self.assertEqual(q.plain(q.freeze(req)),before)
        RS_RESULTS.append(dict(case=label,actual={k:q.plain(result.get(k)) for k in
            ("result_status","rejection_code","line","physical_facts","portions","issues","qualification_issues",
             "rejected_records","basis_catalog","capacity_checks","quantity_ranges")}))
        return result

    def test_ir02_default_and_explicit_single_field_cannot_hide_opposition(self):
        req=request([portion("A")],[delivery("D","80",("A",),date(2026,10,1))])
        claim,opposed=rs_opposition(req,fields=("actual_date",))
        self.assertNotIn(opposed["ref"],claim["decision_refs"])
        self.assertNotIn("scope_fields",claim)
        result=self.record("IR02-default-single-field-original",req)
        self.assertEqual(value(result["line"]["F"]),"80")
        self.assertEqual(result["physical_facts"]["by_date"]["date_unverified"]["verified_quantity"],"80")
        self.assertIsNone(value(result["line"]["remaining_quantity"]))
        self.assertIsNone(value(result["line"]["has_verified_arrival"]))
        self.assertIsNone(value(pmap(result)["A"]["remaining_quantity"]))

    def test_ir04_nonfinite_scalar_is_rejected_locally_not_false_change(self):
        for spelling in ("NaN","Infinity"):
            with self.subTest(spelling=spelling):
                req=rs_invalid_a(Decimal(spelling))
                result=self.record("IR04-original-"+spelling,req)
                self.assertNotEqual(result.get("rejection_code"),"input_changed_after_preparation")
                self.assertEqual(result["result_status"],"partial")
                self.assertTrue(result["rejected_records"])
                self.assertIsNone(value(pmap(result)["A"]["remaining_quantity"]))
                QuantityIntegrationTests().assert_c(result)
                self.assertEqual([value(result["line"][k]) for k in ("F","T","W","Cc","Z")],["40","40","20","20","20"])

    def test_ir02_legal_scope_forms_and_reference_order_do_not_hide_opposition(self):
        forms=("absent",("actual_date",),("actual_date","quantity"),("quantity","actual_date"))
        for form in forms:
            for listed in (False,True):
                for reverse in (False,True):
                    with self.subTest(form=form,listed=listed,reverse=reverse):
                        req=request([portion("A")],[delivery("D","80",("A",),date(2026,10,1))])
                        claim,_=rs_opposition(req,fields=form,listed=listed)
                        if reverse:
                            req[1]["verification_decisions"]=req[1]["verification_decisions"][::-1]
                            req[1]["evidence_records"]=req[1]["evidence_records"][::-1]
                            claim["decision_refs"]=claim["decision_refs"][::-1]
                        result=self.record("IR02-forms/"+str((form,listed,reverse)),req)
                        self.assertEqual(value(result["line"]["F"]),"80")
                        self.assertEqual(result["physical_facts"]["by_date"]["date_unverified"]["verified_quantity"],"80")
                        self.assertIsNone(value(result["line"]["remaining_quantity"]))
                        self.assertIsNone(value(result["line"]["has_verified_arrival"]))

    def test_ir02_support_scope_equivalence_and_proven_field_exclusion(self):
        for listed in (False,True):
            for explicit_support in (False,True):
                with self.subTest(listed=listed,explicit_support=explicit_support):
                    req=request([portion("A")],[delivery("D","80",("A",),date(2026,10,1))])
                    claim,_=rs_opposition(req,fields=("quantity",),listed=listed)
                    if explicit_support:claim["scope_fields"]=("actual_date",)
                    result=self.record("IR02-proven-field-exclusion/"+str((listed,explicit_support)),req)
                    self.assertEqual(value(result["line"]["F"]),"80")
                    self.assertEqual(result["physical_facts"]["by_date"]["after_cutoff"]["verified_quantity"],"80")
                    self.assertEqual(value(result["line"]["remaining_quantity"]),"100")
                    self.assertIs(value(result["line"]["has_verified_arrival"]),False)

    def test_ir02_unproven_scope_is_not_proven_disjoint(self):
        for form in ("empty_fields","scope_label","applicability_label"):
            for listed in (False,True):
                with self.subTest(form=form,listed=listed):
                    req=request([portion("A")],[delivery("D","80",("A",),date(2026,10,1))])
                    _,opposed=rs_opposition(req,fields=() if form=="empty_fields" else "absent",listed=listed,
                                           scope_ref=("unknown-range","v1") if form=="scope_label" else "absent")
                    if form=="applicability_label":
                        body=dict(opposed["claim_content"].entries);body["applicability_ref"]=("unknown-applicability","v1")
                        opposed["claim_content"]=q.freeze(body)
                        req[1]["evidence_records"][-1]["assertions"]=(q.freeze(body),)
                    result=self.record("IR02-unproven/"+str((form,listed)),req)
                    self.assertIsNone(value(result["line"]["remaining_quantity"]))
                    self.assertIsNone(value(result["line"]["has_verified_arrival"]))
                    self.assertTrue(any(x["code"]=="qualification_scope_relation_unproven" for x in result["qualification_issues"]))

    def test_ir02_raw_illegal_scope_fields_are_diagnosed_not_coerced(self):
        for form in (["actual_date"],"actual_date",None,1,c.MISSING):
            with self.subTest(form_type=type(form).__name__):
                req=request([portion("A")],[delivery("D","80",("A",),date(2026,10,1))])
                _,opposed=rs_opposition(req)
                body=dict(opposed["claim_content"].entries);body["scope_fields"]=form
                opposed["claim_content"]=body;req[1]["evidence_records"][-1]["assertions"]=(body,)
                result=self.record("IR02-illegal-scope/"+type(form).__name__,req)
                self.assertIsNone(value(result["line"]["remaining_quantity"]))
                self.assertIsNone(value(result["line"]["has_verified_arrival"]))
                self.assertTrue(any(x["code"]=="invalid_qualification_scope_type" for x in result["issues"]))
                self.assertTrue(any(x["code"]=="invalid_qualification_scope_type" for x in result["qualification_issues"]))

    def test_ir04_decimal_sign_payload_and_independence_boundaries(self):
        for spelling in ("NaN","-NaN","NaN123","-NaN456","sNaN","sNaN123","-sNaN987","Infinity","-Infinity"):
            for independent in (False,True):
                with self.subTest(spelling=spelling,independent=independent):
                    bad=Decimal(spelling);req=rs_invalid_a(bad,independent=independent)
                    result=self.record("IR04-boundary/"+str((spelling,independent)),req)
                    self.assertNotEqual(result.get("rejection_code"),"input_changed_after_preparation")
                    self.assertEqual(result["result_status"],"partial")
                    self.assertTrue(result["rejected_records"])
                    preserved=next(x for x in result["rejected_records"] if x["group"]=="allocations")["content"]["allocated_quantity"]
                    self.assertIs(type(preserved),Decimal)
                    self.assertEqual(preserved.as_tuple(),bad.as_tuple())
                    self.assertFalse(q.safe(preserved));self.assertFalse(q.same(preserved,preserved))
                    with self.assertRaises(ValueError):q.exact_q(preserved)
                    self.assertIsNone(value(pmap(result)["A"]["remaining_quantity"]))
                    if independent:QuantityIntegrationTests().assert_c(result)
                    else:self.assertTrue(all(value(pmap(result)["C"][k]) is None for k in
                        ("remaining_quantity","age_days","overdue_quantity","overdue_days")))

    def test_ir04_stable_capture_and_real_changes_remain_distinct(self):
        for change in ("unchanged","nan_to_infinity","nan_payload","nan_sign","other_field"):
            with self.subTest(change=change):
                req=rs_invalid_a(Decimal("NaN123"))
                prepared=c.prepare_quantity_snapshot(operation="order_item",raw_request=req[0],snapshot_payload=req[1])
                self.assertTrue(q.capture_same(q.freeze(req[0]),prepared.raw_capture[0]))
                if change=="nan_to_infinity":req[0]["allocations"][0]["allocated_quantity"]=Decimal("Infinity")
                elif change=="nan_payload":req[0]["allocations"][0]["allocated_quantity"]=Decimal("NaN456")
                elif change=="nan_sign":req[0]["allocations"][0]["allocated_quantity"]=Decimal("-NaN123")
                elif change=="other_field":req[0]["deliveries"][1]["actual_date"]=date(2026,9,21)
                result=q.evaluate_quantity_snapshot(prepared)
                if change=="unchanged":
                    self.assertEqual(result["result_status"],"partial");QuantityIntegrationTests().assert_c(result)
                else:
                    self.assertEqual(result["result_status"],"rejected")
                    self.assertEqual(result["rejection_code"],"input_changed_after_preparation")
                    self.assertIsNone(result["line"])

    def test_capture_never_calls_untrusted_comparison_or_licenses_bad_scope(self):
        bad=NoCompare()
        a=q.freeze({"value":bad});b=q.freeze({"value":bad})
        self.assertTrue(q.capture_same(a,b));self.assertFalse(q.same(a,b));self.assertFalse(q.safe(a))
        req=request([portion("A")],[delivery("D","80",("A",),date(2026,10,1))])
        _,opposed=rs_opposition(req)
        body=dict(opposed["claim_content"].entries);body["scope_fields"]=(bad,)
        opposed["claim_content"]=body;req[1]["evidence_records"][-1]["assertions"]=(body,)
        result=self.record("IR02-custom-scope-element",req)
        self.assertIsNone(value(result["line"]["remaining_quantity"]))
        self.assertEqual(bad.calls,0)

    def test_ir04_finite_nonnegative_quantity_rules_stay_strict(self):
        for amount in (Decimal("-1"),Decimal("20")):
            with self.subTest(amount=str(amount)):
                req=rs_invalid_a(amount)
                if amount>=0:ir_relation_claim(req,"AL-DA",pnode("A").identity);ir_cover(req)
                result=self.record("IR04-finite-control/"+str(amount),req)
                QuantityIntegrationTests().assert_c(result)
                if amount<0:
                    self.assertTrue(result["rejected_records"])
                    self.assertIsNone(value(pmap(result)["A"]["remaining_quantity"]))
                else:
                    self.assertFalse(result["rejected_records"])
                    self.assertEqual(value(pmap(result)["A"]["remaining_quantity"]),"80")
                    self.assertEqual(value(result["line"]["remaining_quantity"]),"160")

    def test_ir02_positive_equivalent_scope_representations_keep_post_cutoff(self):
        for form in ("absent",("actual_date",),("quantity","actual_date"),("actual_date","quantity")):
            with self.subTest(form=form):
                req=request([portion("A")],[delivery("D","80",("A",),date(2026,10,1))])
                claim=next(x for x in req[1]["field_claims"] if x["field_name"]=="actual_date")
                if form!="absent":claim["scope_fields"]=form
                result=self.record("IR02-positive-equivalence/"+str(form),req)
                self.assertEqual(value(result["line"]["F"]),"80")
                self.assertEqual(value(result["line"]["remaining_quantity"]),"100")
                self.assertIs(value(result["line"]["has_verified_arrival"]),False)

    def test_ir04_equal_reconstructed_decimal_is_unchanged(self):
        for spelling in ("NaN123","-sNaN456","-Infinity"):
            with self.subTest(spelling=spelling):
                req=rs_invalid_a(Decimal(spelling))
                prepared=c.prepare_quantity_snapshot(operation="order_item",raw_request=req[0],snapshot_payload=req[1])
                req[0]["allocations"][0]["allocated_quantity"]=Decimal(spelling)
                result=q.evaluate_quantity_snapshot(prepared)
                self.assertEqual(result["result_status"],"partial")
                self.assertNotEqual(result.get("rejection_code"),"input_changed_after_preparation")
                QuantityIntegrationTests().assert_c(result)

    def test_ir04_signaling_nan_capture_does_not_trigger_decimal_comparison_trap(self):
        from decimal import InvalidOperation
        for spelling in ("sNaN","-sNaN89","NaN12"):
            with self.subTest(spelling=spelling),localcontext() as ctx:
                ctx.traps[InvalidOperation]=True
                left=Decimal(spelling);right=Decimal(spelling)
                self.assertTrue(q.capture_same(q.freeze(left),q.freeze(right)))
                self.assertFalse(q.same(left,right))
                result=self.record("IR04-decimal-trap/"+spelling,rs_invalid_a(left))
                QuantityIntegrationTests().assert_c(result)

    def test_ir04_decimal_subclass_cannot_supply_custom_capture_operations(self):
        class UntrustedDecimal(Decimal):
            calls=0
            def as_tuple(self):
                type(self).calls+=1;raise AssertionError("custom_as_tuple_called")
            def __eq__(self,other):
                type(self).calls+=1;raise AssertionError("custom_equality_called")
            def __hash__(self):
                type(self).calls+=1;raise AssertionError("custom_hash_called")
        value_=UntrustedDecimal("NaN")
        a=q.freeze(value_);b=q.freeze(value_)
        self.assertTrue(q.capture_same(a,b));self.assertFalse(q.safe(a));self.assertFalse(q.same(a,b))
        with self.assertRaises(ValueError):q.exact_q(value_)
        result=self.record("IR04-untrusted-decimal-subclass",rs_invalid_a(value_))
        QuantityIntegrationTests().assert_c(result)
        self.assertTrue(result["rejected_records"])
        self.assertEqual(UntrustedDecimal.calls,0)


CT_RESULTS = []


def ct_request(summary=False, fields=("actual_date","quantity")):
    req=request([] if summary else [portion("C")],[delivery("DC","20",("C",))],
                () if summary else [allocation("DC","20","C","usable")],summary=summary)
    claim=next(x for x in req[1]["field_claims"] if x["field_name"]=="actual_date")
    claim["scope_fields"]=fields
    return req,claim


class CaptureTypeRegressionTests(unittest.TestCase):
    def through_adapter(self,label,req,mutate=None,summary=False):
        from unittest.mock import patch
        original=c.prepare_quantity_snapshot
        prepared=[]
        def intercept(**kwargs):
            item=original(**kwargs)
            self.assertIsNotNone(item.snapshot)
            prepared.append(item)
            if mutate is not None:mutate(item)
            return item
        with patch.object(c,"prepare_quantity_snapshot",side_effect=intercept) as hook:
            adapter=core._summarize_delivery_facts_v2_candidate if summary else core._evaluate_delivery_scope_v2_candidate
            result=adapter(raw_request=req[0],snapshot_payload=req[1])
        self.assertEqual(hook.call_count,1)
        CT_RESULTS.append(dict(case=label,operation="facts_summary" if summary else "order_item",actual={
            k:q.plain(result.get(k)) for k in ("result_status","rejection_code","physical_facts","line","portions",
                                                "issues","qualification_issues","basis_catalog")}))
        return result,prepared[0]

    def test_ir06_scope_tuple_to_equal_list_is_rejected_in_both_adapters(self):
        for summary in (False,True):
            for reverse in (False,True):
                with self.subTest(summary=summary,reverse=reverse):
                    fields=("quantity","actual_date") if reverse else ("actual_date","quantity")
                    req,claim=ct_request(summary,fields)
                    def mutate(prepared):
                        self.assertIs(type(claim["scope_fields"]),tuple)
                        captured=next(x for x in prepared.snapshot.field_claims if x["field_name"]=="actual_date")
                        self.assertIs(type(captured["scope_fields"]),tuple)
                        claim["scope_fields"]=list(fields)
                        self.assertIs(type(claim["scope_fields"]),list)
                        self.assertEqual(captured["scope_fields"],fields)
                        self.assertTrue(q.same(q.freeze(fields),q.freeze(claim["scope_fields"])))
                    result,_=self.through_adapter("IR06-original/"+str((summary,reverse)),req,mutate,summary)
                    self.assertEqual(result["result_status"],"rejected")
                    self.assertEqual(result["rejection_code"],"input_changed_after_preparation")
                    self.assertIsNone(result["line"])

    def test_ir06_scope_list_to_equal_tuple_cannot_reuse_invalid_preparation(self):
        for summary in (False,True):
            for reverse in (False,True):
                with self.subTest(summary=summary,reverse=reverse):
                    values=["quantity","actual_date"] if reverse else ["actual_date","quantity"]
                    req,claim=ct_request(summary,values)
                    def mutate(prepared):
                        self.assertTrue(any(x.code=="invalid_qualification_scope_type" for x in prepared.issues))
                        self.assertIs(type(claim["scope_fields"]),list)
                        claim["scope_fields"]=tuple(values)
                    result,_=self.through_adapter("IR06-list-to-tuple/"+str((summary,reverse)),req,mutate,summary)
                    self.assertEqual(result["result_status"],"rejected")
                    self.assertEqual(result["rejection_code"],"input_changed_after_preparation")

    def test_ir06_unchanged_type_and_contents_and_fresh_reverse_controls(self):
        for summary in (False,True):
            for kind in ("tuple","tuple_reverse","list"):
                with self.subTest(summary=summary,kind=kind):
                    values=("quantity","actual_date") if kind=="tuple_reverse" else ("actual_date","quantity")
                    req,_=ct_request(summary,list(values) if kind=="list" else values)
                    before=q.plain(q.freeze(req))
                    result,prepared=self.through_adapter("IR06-unchanged/"+str((summary,kind)),req,summary=summary)
                    self.assertNotEqual(result.get("rejection_code"),"input_changed_after_preparation")
                    self.assertEqual(q.plain(q.freeze(req)),before)
                    self.assertEqual(value(result["physical_facts"]["verified_received_quantity"]),"20")
                    self.assertEqual(result["raw_capture_type_schema"],"typed-raw-v1")
                    self.assertEqual(result["strict_raw_capture"],prepared.snapshot.raw_capture)
                    self.assertTrue(q.capture_same(result["raw_capture"][0],q.freeze(req[0])))
                    if kind=="list":
                        self.assertEqual(result["result_status"],"partial")
                        self.assertTrue(any(x["code"]=="invalid_qualification_scope_type" for x in result["issues"]))
                        if not summary:self.assertIsNone(value(pmap(result)["C"]["remaining_quantity"]))
                    elif not summary:QuantityIntegrationTests().assert_c(result)

    def test_ir06_other_strict_collections_and_reference_container_types(self):
        for summary in (False,True):
            for name in ("fact_slots","field_claims","verification_decisions","evidence_records","coverage_records","decision_refs","candidate_portion_ids"):
                with self.subTest(summary=summary,name=name):
                    req,claim=ct_request(summary)
                    def mutate(prepared):
                        if name=="decision_refs":claim[name]=list(claim[name])
                        elif name=="candidate_portion_ids":
                            req[0]["deliveries"][0][name]=list(req[0]["deliveries"][0][name])
                        else:req[1][name]=list(req[1][name])
                    result,_=self.through_adapter("IR06-container/"+str((summary,name)),req,mutate,summary)
                    self.assertEqual(result["result_status"],"rejected")
                    self.assertEqual(result["rejection_code"],"input_changed_after_preparation")
                    self.assertIsNone(result["physical_facts"])

    def test_ir06_order_record_collections_and_root_delivery_container(self):
        for name in ("portion_slots","relation_slots","allocations","deliveries"):
            with self.subTest(name=name):
                req,_=ct_request()
                def mutate(prepared):
                    if name in ("allocations","deliveries"):req[0][name]=tuple(req[0][name])
                    else:req[1][name]=list(req[1][name])
                result,_=self.through_adapter("IR06-order-container/"+name,req,mutate)
                self.assertEqual(result["rejection_code"],"input_changed_after_preparation")
                self.assertEqual(result["result_status"],"rejected")

    def test_ir06_content_scalar_type_and_presence_changes_still_reject(self):
        for summary in (False,True):
            for change in ("content","order","flag_type","date_type","missing_to_none","none_to_missing"):
                with self.subTest(summary=summary,change=change):
                    req,claim=ct_request(summary)
                    if change=="none_to_missing":req[0]["deliveries"][0]["actual_date_verified"]=None
                    def mutate(prepared):
                        if change=="content":claim["scope_fields"]=("quantity",)
                        elif change=="order":claim["scope_fields"]=claim["scope_fields"][::-1]
                        elif change=="flag_type":req[0]["deliveries"][0]["evidence_verified"]=1
                        elif change=="date_type":req[0]["deliveries"][0]["actual_date"]=datetime(2026,9,20)
                        elif change=="missing_to_none":claim["not_previously_provided"]=None
                        else:req[0]["deliveries"][0]["actual_date_verified"]=c.MISSING
                    result,_=self.through_adapter("IR06-content/"+str((summary,change)),req,mutate,summary)
                    self.assertEqual(result["rejection_code"],"input_changed_after_preparation")
                    self.assertIsNone(result["line"])

    def test_ir06_nonfinite_decimal_capture_keeps_independent_results_in_both_paths(self):
        for summary in (False,True):
            for spelling in ("NaN","sNaN","-sNaN7","Infinity","-Infinity","NaN123","-NaN456"):
                with self.subTest(summary=summary,spelling=spelling):
                    bad=Decimal(spelling)
                    if summary:
                        req=request([],[delivery("DA","20",("A",)),delivery("DC","20",("C",))],summary=True)
                        req[0]["deliveries"][0]["delivered_quantity"]=bad
                        req[1]["fact_slots"][0]["content"]["delivered_quantity"]=bad
                        cover(req[0],req[1],[("facts",)])
                    else:req=rs_invalid_a(bad)
                    result,_=self.through_adapter("IR06-nonfinite/"+str((summary,spelling)),req,summary=summary)
                    self.assertEqual(result["result_status"],"partial")
                    self.assertNotEqual(result.get("rejection_code"),"input_changed_after_preparation")
                    self.assertTrue(result["rejected_records"])
                    self.assertFalse(q.safe(bad));self.assertFalse(q.same(bad,bad))
                    with self.assertRaises(ValueError):q.exact_q(bad)
                    if summary:self.assertEqual(value(result["physical_facts"]["verified_received_quantity"]),"20")
                    else:QuantityIntegrationTests().assert_c(result)

    def test_ir06_unknown_objects_never_run_comparison_hash_bool_or_conversion(self):
        class Untrusted:
            calls=0
            def __eq__(self,other):type(self).calls+=1;raise AssertionError("custom_eq")
            def __hash__(self):type(self).calls+=1;raise AssertionError("custom_hash")
            def __bool__(self):type(self).calls+=1;raise AssertionError("custom_bool")
            def __str__(self):type(self).calls+=1;raise AssertionError("custom_str")
        bad=Untrusted()
        first=q.capture_raw_types(bad);second=q.capture_raw_types(bad)
        self.assertTrue(q.capture_same(first,second))
        req=rs_invalid_a(bad)
        result,_=self.through_adapter("IR06-untrusted-unchanged",req)
        self.assertEqual(result["result_status"],"partial");QuantityIntegrationTests().assert_c(result)
        other=Untrusted()
        self.assertFalse(q.capture_same(first,q.capture_raw_types(other)))
        self.assertEqual(Untrusted.calls,0)

    def test_ir06_capture_metadata_does_not_change_business_binding_or_grant_quantity(self):
        self.assertTrue(q.same(q.freeze(["actual_date"]),q.freeze(("actual_date",))))
        self.assertFalse(q.capture_same(q.capture_raw_types(["actual_date"]),q.capture_raw_types(("actual_date",))))
        self.assertTrue(q.capture_same(q.capture_raw_types({"a":1,"b":True}),q.capture_raw_types({"b":True,"a":1})))
        self.assertFalse(q.capture_same(q.capture_raw_types(True),q.capture_raw_types(1)))
        self.assertFalse(q.capture_same(q.capture_raw_types(None),q.capture_raw_types(c.MISSING)))
        for value_ in (Decimal("NaN123"),Decimal("-sNaN4"),Decimal("-Infinity")):
            with self.subTest(value=str(value_)):
                self.assertTrue(q.capture_same(q.capture_raw_types(value_),q.capture_raw_types(Decimal(str(value_)))))
                with self.assertRaises(ValueError):q.exact_q(q.capture_raw_types(value_))
                self.assertFalse(q.safe(value_));self.assertFalse(q.same(value_,value_))

    def test_ir06_nonfinite_value_change_and_new_cycle_after_preparation_reject(self):
        for change in ("value","cycle"):
            with self.subTest(change=change):
                req=rs_invalid_a(Decimal("NaN123"))
                def mutate(prepared):
                    if change=="value":req[0]["allocations"][0]["allocated_quantity"]=Decimal("Infinity")
                    else:
                        cycle=[];cycle.append(cycle)
                        req[0]["deliveries"][0]["new_cycle"]=cycle
                result,_=self.through_adapter("IR06-invalid-value-change/"+change,req,mutate)
                self.assertEqual(result["result_status"],"rejected")
                self.assertEqual(result["rejection_code"],"input_changed_after_preparation")


if __name__ == "__main__":
    unittest.main(verbosity=2)
