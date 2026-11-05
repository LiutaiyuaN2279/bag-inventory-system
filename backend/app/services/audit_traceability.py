"""只解释当次冻结试算，不查业务库、不执行SQL、不授予正式证据资格。"""

REF_COLUMNS = {"采购订单": "order_no", "订单": "order_no", "请购单": "req_no",
               "到货单": "arrival_no", "退货单": "return_no", "物料": "material_code"}
VISIBLE_FIELDS = frozenset({"order_no", "req_no", "arrival_no", "return_no", "material_code",
                            "material_name", "unit", "qty", "arrived_qty", "inbound_qty",
                            "ordered_qty", "over_qty", "status", "created_at"})
REVIEW_CHECKLIST = {
    "R01": ["请购批准数量、追加审批及订单对应依据"],
    "R02": ["实际收货、逐行质量结论、独立放行及正式入库的数量/版本对应"],
    "R03": ["核验后的实际交付、份额、交期及有效分配版本；当前缺证不计算"],
    "R04": ["交易条件可比、独立订单样本及观察时点可获得的价格来源"],
    "R05": ["退货批准、实物流转、签收及处置完成依据"],
    "R06": ["实际收货/检验/放行/入库日期及办理依据；不得仅用录入时间"],
    "R07": ["供应商归属与承诺金额有效版本；旧口径不等于新口径通过"],
    "R08": ["库存台账、盘点及保管责任的原始依据"],
    "R09": ["入库过账来源单据、质量放行与数量对应"],
    "R10": ["核验后的实际交付、份额、交期及有效分配版本；当前缺证不计算"],
}


def explain_finding(payload, finding):
    """单号相等仅是冻结候选行定位，不证明其归属、来源真实性或核验资格。"""
    basis = payload.get("basis", {})
    report = payload.get("report", {})
    run_id = payload.get("run_id")
    result = {"run_id": run_id, "status": "unproven", "coverage": "unproven",
              "suggestion_origin": "deterministic_rule_template", "ai_advice": "not_provided",
              "human_confirmation": "not_recorded", "formal_eligible": False,
              "rule_version": basis.get("rule_version"), "candidates": [], "truncated": False,
              "review_checklist": REVIEW_CHECKLIST.get(finding.get("rule_code"), ["原始记录、审批与适用规则的完整依据"]),
              "checklist_status": "not_individually_verified",
              "limitations": ["冻结查询行不等于已核实业务证据；单号匹配不能证明唯一归属",
                              "未提供独立AI建议，未记录人工确认，缺证仍不可确定"]}
    if (not run_id or report.get("report_meta", {}).get("run_id") != run_id
            or finding not in report.get("findings", [])):
        result["limitations"].append("发现与快照未可靠绑定")
        return result
    queries = basis.get("business_data")
    if not isinstance(queries, list):
        result["limitations"].append("冻结输入行缺失")
        return result
    for query_index, query in enumerate(queries):
        if not isinstance(query, dict) or not isinstance(query.get("rows"), list):
            continue
        for row_index, row in enumerate(query["rows"]):
            if not isinstance(row, dict):
                continue
            matched = [column for ref in finding.get("refs", []) if isinstance(ref, dict)
                       and (column := REF_COLUMNS.get(ref.get("type")))
                       and isinstance(ref.get("no"), str) and ref["no"]
                       and row.get(column) == ref["no"]]
            if not matched:
                continue
            if len(result["candidates"]) == 20:
                result["truncated"] = True
                continue
            result["candidates"].append({"query_index": query_index, "row_index": row_index,
                "matched_fields": sorted(set(matched)), "binding": "reference_match_only",
                "fields": {key: value for key, value in row.items()
                           if key in VISIBLE_FIELDS and (value is None or type(value) in (str, int, float, bool))}})
    if not result["candidates"]:
        result["limitations"].append("当前关联单据没有可可靠定位的冻结候选行")
    return result
