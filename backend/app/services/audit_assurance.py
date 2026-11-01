"""B002-C02/C07/D01 output gates. No business approval or historical backfill."""


def legacy_assurance() -> dict:
    return {
        "version": "b002-p0-gates-v1",
        "formal_audit_eligible": False,
        "history_scope_status": "不可确定",
        "historical_traceability": "受限",
        "supported_ranges": [],
        "limited_ranges": [{"scope": "当前数据库旧口径线索", "reason": "仅作核查参考，不代表新口径正式审计结果"}],
        "undetermined_ranges": [
            {"issue": "B002-C02", "scope": "R03/R10采购份额余额、账龄、逾期及完全无到货判断",
             "reason": "缺少核验后的实际交付、份额、交期及有效分配版本"},
            {"issue": "B002-C07", "scope": "正式历史报告完整重现",
             "reason": "试算快照保留当次数据与规则，不补造缺失的历史证据及日历版本"},
            {"issue": "B002-D01", "scope": "全部历史期间审计资格",
             "reason": "历史可信范围尚未核定，不得把缺失数据或零命中解释为通过"},
        ],
        "notice": "受限试算，非正式历史审计报告。历史可信范围未核定；份额或证据不足的结果不计算，不以零代替未知。",
    }


def blocked_delivery_procedure(code: str, name: str) -> dict:
    return {"code": code, "name": name, "objective": "依可靠实际交付和采购份额证据审计",
            "rule": "先核验事实、有效份额/交期版本及计算资格，缺证不计算",
            "hit_count": None, "risk_level": "无法确定", "status": "数据不足",
            "note": "B002-C02/D01：旧数据库不能证明实际交付及份额关系，未执行确定性判断；不是零异常或审计通过。"}
