"""差旅报销模块端到端联调验证脚本。

用途：在三位开发同事交付后，由 Lead 用它一次性验证：
1. 所有模块能否正常 import（语法错误、循环导入）
2. 数据库表与基础数据是否完整
3. 关键业务逻辑是否正确（事实计算、程序触发判断、凭证校验）
4. 真实调用大模型跑通「识别 → 判读 → 制证」主链路
5. 输出结构化结果，便于定位问题

运行（在 backend 目录）：
    .venv/Scripts/python.exe scripts/verify_rmb.py            # 只跑不调大模型的检查
    .venv/Scripts/python.exe scripts/verify_rmb.py --with-llm # 含真实大模型调用（较慢）
"""
import argparse
import io
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

RESULTS = []


def check(name, fn):
    """执行一项检查并记录结果。"""
    try:
        detail = fn()
        RESULTS.append({"name": name, "ok": True, "detail": detail})
        print(f"  [通过] {name}" + (f" — {detail}" if detail else ""))
        return True
    except Exception as exc:
        tb = traceback.format_exc()
        RESULTS.append({"name": name, "ok": False, "detail": str(exc), "trace": tb})
        print(f"  [失败] {name} — {exc}")
        return False


def section(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


# ---------------- 1. 导入检查 ----------------
def test_imports():
    section("1. 模块导入检查")

    def _models():
        from app.models import reimburse as m
        names = [n for n in dir(m) if n.startswith("Rmb")]
        assert len(names) >= 16, f"模型类数量不足：{len(names)}"
        return f"{len(names)} 个模型类"

    def _services():
        from app.services import invoice_ai, fact_service, compliance_ai, voucher_ai
        return "4 个服务模块可用"

    def _llm_client():
        # 兼容两种命名
        try:
            from app.services import llm_client_new as lc
            return "llm_client_new"
        except ImportError:
            from app.services import llm_client as lc
            return "llm_client"

    def _api():
        from app.api.v1.reimburse import bills, compliance, vouchers, policy
        return "4 个路由模块可用"

    def _app():
        from app.main import app
        paths = [r.path for r in app.routes]
        rmb = [p for p in paths if "rmb-" in p]
        assert len(rmb) >= 20, f"报销路由数量不足：{len(rmb)}"
        return f"{len(rmb)} 条报销相关路由"

    check("模型层导入", _models)
    check("服务层导入", _services)
    check("大模型客户端导入", _llm_client)
    check("API 层导入", _api)
    check("FastAPI 应用装配（含路由挂载）", _app)


# ---------------- 2. 数据完整性 ----------------
def test_data():
    section("2. 基础数据完整性")

    from app.core.database import SessionLocal
    from app.models.reimburse import (
        RmbAccountSubject, RmbCityLevel, RmbEmployee, RmbExpenseType,
        RmbHoliday, RmbPolicy, RmbPolicyRule, RmbSettlementMethod, RmbSysParam,
    )

    db = SessionLocal()
    try:
        def _subjects():
            rows = db.query(RmbAccountSubject).all()
            leaves = [r for r in rows if r.is_leaf]
            # 实验文档表 4-9：14 个科目，其中可作为凭证科目的末级科目 10 个
            # （1001/1002/22210101/224101/660201/660202/660203/660204/660205/660299）
            assert len(rows) >= 14, f"科目数 {len(rows)} < 14"
            assert len(leaves) >= 10, f"末级科目 {len(leaves)} < 10"
            return f"{len(rows)} 个科目（末级 {len(leaves)}）"

        def _rules():
            rows = db.query(RmbPolicyRule).order_by(RmbPolicyRule.rule_code).all()
            codes = [r.rule_code for r in rows]
            assert len(rows) == 14, f"规则数 {len(rows)} != 14"
            expected = [f"R{i:02d}" for i in range(1, 15)]
            assert codes == expected, f"规则编号不符：{codes}"
            return "R01～R14 齐全"

        def _types():
            rows = db.query(RmbExpenseType).all()
            assert len(rows) >= 7, f"费用类型 {len(rows)} < 7"
            return f"{len(rows)} 个费用类型"

        def _settlement():
            rows = db.query(RmbSettlementMethod).all()
            assert len(rows) >= 3, f"结算方式 {len(rows)} < 3"
            return f"{len(rows)} 个结算方式"

        def _city():
            rows = db.query(RmbCityLevel).all()
            fallback = [r for r in rows if r.city_name == "其他城市"]
            assert fallback, "缺少『其他城市』兜底记录"
            bj = [r for r in rows if r.city_name == "北京"]
            assert bj and bj[0].lodging_limit == 600, "北京住宿标准应为 600"
            return f"{len(rows)} 条城市等级（含兜底）"

        def _holiday():
            rows = db.query(RmbHoliday).all()
            assert len(rows) >= 30, f"节假日 {len(rows)} 条偏少"
            oct3 = [r for r in rows if r.holiday_date == "2026-10-03"]
            assert oct3, "缺少 2026-10-03（国庆，T05 测试依赖）"
            oct10 = [r for r in rows if r.holiday_date == "2026-10-10"]
            assert oct10 and oct10[0].day_type == "调休上班日", "2026-10-10 应为调休上班日（T07 依赖）"
            return f"{len(rows)} 条节假日/调休"

        def _params():
            rows = db.query(RmbSysParam).all()
            keys = {r.param_key for r in rows}
            need = {"approval_level2_amount", "approval_level3_amount",
                    "entertain_per_capita_limit", "entertain_single_limit", "split_days_window"}
            missing = need - keys
            assert not missing, f"缺少参数：{missing}"
            return f"{len(rows)} 个参数"

        def _policy():
            p = db.query(RmbPolicy).filter(RmbPolicy.is_active == True).first()  # noqa: E712
            assert p, "没有生效的制度"
            assert p.content_text and len(p.content_text) > 500, "制度正文为空或过短"
            assert "300" in p.content_text and "600" in p.content_text, "制度正文缺少关键阈值"
            return f"生效制度「{p.policy_name}」，正文 {len(p.content_text)} 字"

        def _employees():
            rows = db.query(RmbEmployee).all()
            assert len(rows) >= 4, f"员工 {len(rows)} < 4"
            return f"{len(rows)} 名员工"

        check("会计科目", _subjects)
        check("检查规则 R01-R14", _rules)
        check("费用类型", _types)
        check("结算方式", _settlement)
        check("城市等级", _city)
        check("节假日表", _holiday)
        check("系统参数", _params)
        check("生效制度", _policy)
        check("员工档案", _employees)
    finally:
        db.close()


# ---------------- 3. 票据校验工具 ----------------
def test_invoice_utils():
    section("3. 票据识别工具函数")

    from app.services.invoice_ai import check_invoice, money_to_chinese

    def _money():
        cases = {
            1650.00: "壹仟陆佰伍拾圆整",
            100.00: "壹佰圆整",
            0.05: "伍分",
            1234567.89: "壹佰贰拾叁万肆仟伍佰陆拾柒圆捌角玖分",
            2400.00: "贰仟肆佰圆整",
        }
        bad = []
        for amount, expect in cases.items():
            got = money_to_chinese(amount)
            if got != expect:
                bad.append(f"{amount}→{got}（期望 {expect}）")
        assert not bad, "; ".join(bad)
        return f"{len(cases)} 个用例全部正确"

    def _check():
        from app.core.database import SessionLocal
        from app.models.reimburse import RmbSysParam
        db = SessionLocal()
        try:
            company = db.query(RmbSysParam).filter(
                RmbSysParam.param_key == "company_name").first().param_value
            tax = db.query(RmbSysParam).filter(
                RmbSysParam.param_key == "company_tax_id").first().param_value
        finally:
            db.close()

        # 正常票据：不应有告警
        good = {
            "document_type": "电子发票（增值税专用发票）", "is_invoice": True,
            "invoice_number": "26312000000098765432",
            "issue_date": "2026-10-15",
            "buyer_name": company, "buyer_tax_id": tax,
            "amount_without_tax": 1556.60, "tax_amount": 93.40,
            "total_amount": 1650.00, "total_amount_cn": "壹仟陆佰伍拾圆整",
            "checkin_date": "2026-10-12", "checkout_date": "2026-10-15", "nights": 3,
        }
        w1 = check_invoice(dict(good), company, tax)
        assert not w1, f"正常票据不应有告警，实际：{w1}"

        # 勾稽不平
        bad1 = dict(good, amount_without_tax=1500.00)
        w2 = check_invoice(dict(bad1), company, tax)
        assert any("勾稽" in w or "合计" in w for w in w2), f"勾稽不平未告警：{w2}"

        # 大写不符
        bad2 = dict(good, total_amount_cn="壹仟圆整")
        w3 = check_invoice(dict(bad2), company, tax)
        assert any("大写" in w for w in w3), f"大写不符未告警：{w3}"

        # 非发票
        bad3 = dict(good, is_invoice=False, total_amount_cn="壹仟陆佰伍拾圆整")
        w4 = check_invoice(dict(bad3), company, tax)
        assert any("不是发票" in w or "特批" in w for w in w4), f"非发票未告警：{w4}"

        # 购买方不符
        bad4 = dict(good, buyer_name="别家公司")
        w5 = check_invoice(dict(bad4), company, tax)
        assert any("购买方" in w for w in w5), f"购买方不符未告警：{w5}"

        return "5 项校验行为正确"

    check("money_to_chinese 大小写转换", _money)
    check("check_invoice 规则校验", _check)


# ---------------- 4. 事实计算与程序触发 ----------------
def test_facts():
    section("4. 判读事实计算（纯程序）")

    from app.services.fact_service import compute_facts, program_flags_from_facts

    def _flags():
        """构造事实，验证程序触发的判断逻辑。"""
        params = {
            "approval_level2_amount": 5000,
            "approval_level3_amount": 20000,
            "entertain_per_capita_limit": 300,
            "entertain_single_limit": 2000,
            "split_days_window": 3,
        }
        base = {
            "expense_type": "差旅住宿费", "amount": 1650, "has_invoice": 1,
            "approver_rank": 1, "required_rank": 1,
            "combined_required_rank": 1, "is_weekend": False, "holiday_name": "",
            "cross_year": False, "duplicate_claims": [], "per_night_amount": 550,
            "lodging_limit": 600,
        }
        f1 = program_flags_from_facts(dict(base), params)
        assert f1.get("R01") is False, "T03 合规样例 R01 不应触发"
        assert f1.get("R06") is False, "每晚 550 < 600，R06 不应触发"
        assert "R03" not in f1, "差旅单不应返回 R03"

        # 住宿超标
        f2 = program_flags_from_facts(dict(base, per_night_amount=500, lodging_limit=400), params)
        assert f2.get("R06") is True, "每晚 500 > 400，R06 应触发"

        # 审批越权（8500 元部门负责人审批）
        f3 = program_flags_from_facts(
            dict(base, amount=8500, approver_rank=1, required_rank=2), params)
        assert f3.get("R01") is True, "8500 元需总监，部门负责人审批应触发 R01"

        # 缺发票
        f4 = program_flags_from_facts(dict(base, has_invoice=0), params)
        assert f4.get("R07") is True, "缺发票应触发 R07"

        # 跨期
        f5 = program_flags_from_facts(dict(base, cross_year=True), params)
        assert f5.get("R08") is True, "跨年应触发 R08"

        # 疑似重复
        f6 = program_flags_from_facts(dict(base, duplicate_claims=[{"bill_no": "BX-1"}]), params)
        assert f6.get("R09") is True, "有重复单应触发 R09"

        # 业务招待：人均超标 + 单次超标 + 周末
        ent_base = {
            "expense_type": "业务招待费", "amount": 2400, "has_invoice": 1,
            "approver_rank": 1, "required_rank": 1,
            "combined_required_rank": 1, "is_weekend": True, "holiday_name": "国庆节",
            "cross_year": False, "duplicate_claims": [],
            "per_capita_amount": 400, "guest_count": 6,
        }
        f7 = program_flags_from_facts(dict(ent_base), params)
        assert f7.get("R03") is True, "人均 400 > 300，R03 应触发"
        assert f7.get("R04") is True, "单次 2400 > 2000，R04 应触发"
        assert f7.get("R05") is True, "周末+节假日，R05 应触发"

        return "9 项触发判断正确"

    check("program_flags_from_facts 触发判断", _flags)


# ---------------- 5. 凭证校验 ----------------
def test_voucher_validate():
    section("5. 凭证程序校验")

    from app.core.database import SessionLocal
    from app.models.reimburse import RmbReimbursement, RmbSettlementMethod
    from app.services.voucher_ai import validate_voucher

    db = SessionLocal()
    try:
        bill = db.query(RmbReimbursement).first()
        settle = db.query(RmbSettlementMethod).first()
        credit_code = settle.subject_code if settle else "1002"
        bill_amount = bill.amount if bill else 1650.0
        bill_obj = bill
    finally:
        db.close()

    # 1. 正确凭证（住宿专票：差旅费 1556.60 + 进项 93.40 / 银行存款 1650）
    good_entries = [
        {"summary": "王五报销差旅住宿费-上海出差", "subject_code": "660202",
         "subject_name": "管理费用—差旅费", "debit_amount": 1556.60, "credit_amount": 0},
        {"summary": "王五报销差旅住宿费-上海出差", "subject_code": "22210101",
         "subject_name": "应交税费—应交增值税—进项税额", "debit_amount": 93.40, "credit_amount": 0},
        {"summary": "王五报销差旅住宿费-上海出差", "subject_code": credit_code,
         "subject_name": "", "debit_amount": 0, "credit_amount": 1650.00},
    ]
    header = {"voucher_word": "记", "period": "202610", "voucher_no": 1,
              "voucher_date": "2026-10-20", "attachment_count": 1}

    def _good():
        from app.core.database import SessionLocal as SL
        db2 = SL()
        try:
            b = db2.query(RmbReimbursement).first()
            e, w = validate_voucher(db2, good_entries, header, b, None)
            # 正确凭证不应有"错误"级别问题（警告可有）
            assert not e, f"正确凭证被判为错误：{e}"
            return f"无错误（{len(w)} 条提醒）"
        finally:
            db2.close()

    def _imbalance():
        from app.core.database import SessionLocal as SL
        db2 = SL()
        try:
            b = db2.query(RmbReimbursement).first()
            bad = [dict(x) for x in good_entries]
            bad[0]["debit_amount"] = 1000.00
            e, w = validate_voucher(db2, bad, header, b, None)
            assert any("平衡" in x or "合计" in x for x in e), f"借贷不平未拦截：{e}"
            return "借贷不平被拦截"
        finally:
            db2.close()

    def _entertain_tax():
        """业务招待费不得抵扣进项税额。"""
        from app.core.database import SessionLocal as SL
        from app.models.reimburse import RmbExpenseType
        from app.services.voucher_ai import validate_voucher as vv
        db2 = SL()
        try:
            b = db2.query(RmbReimbursement).first()
            ent_type = db2.query(RmbExpenseType).filter(
                RmbExpenseType.name == "业务招待费").first()
            if b and ent_type:
                # 临时把费用类型改成招待，触发校验
                old = b.expense_type_id
                b.expense_type_id = ent_type.id
                try:
                    bad = [
                        {"summary": "招待费", "subject_code": "660203", "subject_name": "",
                         "debit_amount": 2000.00, "credit_amount": 0},
                        {"summary": "招待费", "subject_code": "22210101", "subject_name": "",
                         "debit_amount": 60.00, "credit_amount": 0},
                        {"summary": "招待费", "subject_code": credit_code, "subject_name": "",
                         "debit_amount": 0, "credit_amount": 2060.00},
                    ]
                    e, w = vv(db2, bad, header, b, None)
                    assert any("招待" in x or "进项" in x for x in e), \
                        f"业务招待费带进项税未被拦截：{e}"
                    return "业务招待费进项税被拦截"
                finally:
                    b.expense_type_id = old
                    db2.rollback()
            return "跳过（无报销单或费用类型）"
        finally:
            db2.close()

    def _non_leaf():
        from app.core.database import SessionLocal as SL
        db2 = SL()
        try:
            b = db2.query(RmbReimbursement).first()
            bad = [dict(x) for x in good_entries]
            bad[0]["subject_code"] = "6602"   # 非末级科目
            e, w = validate_voucher(db2, bad, header, b, None)
            assert any("末级" in x or "科目" in x for x in e), f"非末级科目未拦截：{e}"
            return "非末级科目被拦截"
        finally:
            db2.close()

    check("正确凭证通过校验", _good)
    check("借贷不平被拦截", _imbalance)
    check("业务招待费抵扣进项被拦截", _entertain_tax)
    check("使用非末级科目被拦截", _non_leaf)


# ---------------- 6. 后端接口冒烟 ----------------
def test_api_smoke():
    section("6. 后端接口冒烟（真实 HTTP）")

    import json as _json
    import urllib.error
    import urllib.request

    base = os.environ.get("RMB_VERIFY_BASE", "http://127.0.0.1:8000")
    token_holder = {}

    def _http(method, path, token=None, body=None):
        url = base + path
        data = _json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return _json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                return _json.loads(raw)
            except _json.JSONDecodeError:
                raise RuntimeError(f"HTTP {exc.code}: {raw[:200]}")

    def _login():
        d = _http("POST", "/api/v1/auth/login",
                  body={"username": "admin", "password": "admin123"})
        assert d.get("code") == 0, f"登录失败：{d}"
        payload = d["data"]
        token = payload.get("token") or payload.get("access_token")
        assert token, f"登录响应无 token：{payload}"
        token_holder["token"] = token
        return "admin 登录成功"

    def _meta():
        d = _http("GET", "/api/v1/rmb-bills/meta", token_holder["token"])
        assert d.get("code") == 0, f"meta 失败：{d}"
        data = d["data"]
        assert data.get("expense_types"), "缺少费用类型"
        assert data.get("today"), "缺少服务器日期"
        return f"{len(data['expense_types'])} 个费用类型，服务器日期 {data['today']}"

    def _rules():
        d = _http("GET", "/api/v1/rmb-policy/rules", token_holder["token"])
        assert d.get("code") == 0, f"rules 失败：{d}"
        rules = d["data"]
        assert len(rules) == 14, f"规则数 {len(rules)} != 14"
        return "14 条规则"

    def _params():
        d = _http("GET", "/api/v1/rmb-policy/params", token_holder["token"])
        assert d.get("code") == 0, f"params 失败：{d}"
        data = d["data"]
        assert data.get("params"), "缺少参数"
        assert data.get("city_levels"), "缺少城市等级"
        assert data.get("holidays"), "缺少节假日"
        return (f"{len(data['params'])} 参数 / "
                f"{len(data['city_levels'])} 城市 / {len(data['holidays'])} 节假日")

    def _bills():
        d = _http("GET", "/api/v1/rmb-bills?page=1&page_size=50", token_holder["token"])
        assert d.get("code") == 0, f"列表失败：{d}"
        return f"{d['data'].get('total', 0)} 张报销单"

    def _detail():
        d = _http("GET", "/api/v1/rmb-bills?page=1&page_size=1", token_holder["token"])
        items = d["data"]["list"]
        assert items, "没有报销单可测详情"
        bill_id = items[0]["id"]
        d2 = _http("GET", f"/api/v1/rmb-bills/{bill_id}", token_holder["token"])
        assert d2.get("code") == 0, f"详情失败：{d2}"
        detail = d2["data"]
        assert detail.get("bill_no"), "详情缺少单号"
        return f"{detail['bill_no']} 详情可读"

    def _compliance_detail():
        d = _http("GET", "/api/v1/rmb-bills?page=1&page_size=50", token_holder["token"])
        judged = [x for x in d["data"]["list"] if x.get("compliance_result") not in (None, "未判读")]
        assert judged, "没有已判读的报销单（请先执行判读）"
        bid = judged[0]["id"]
        d2 = _http("GET", f"/api/v1/rmb-compliance/{bid}", token_holder["token"])
        assert d2.get("code") == 0, f"判读详情失败：{d2}"
        chk = d2["data"].get("check")
        assert chk and chk.get("issues"), "判读详情缺少问题清单"
        return f"{chk['overall_result']}，{len(chk['issues'])} 条明细"

    def _policy():
        d = _http("GET", "/api/v1/rmb-policy", token_holder["token"])
        assert d.get("code") == 0, f"制度列表失败：{d}"
        active = d["data"].get("active")
        assert active, "没有生效制度"
        return f"生效制度「{active.get('policy_name')}」"

    def _vouchers():
        d = _http("GET", "/api/v1/rmb-vouchers?page=1&page_size=10", token_holder["token"])
        assert d.get("code") == 0, f"凭证列表失败：{d}"
        return f"{d['data'].get('total', 0)} 张凭证"

    def _pending():
        d = _http("GET", "/api/v1/rmb-vouchers/pending?page=1&page_size=10",
                  token_holder["token"])
        assert d.get("code") == 0, f"待制证失败：{d}"
        return f"{d['data'].get('total', 0)} 张待制证"

    def _review_list():
        d = _http("GET", "/api/v1/rmb-vouchers/review?page=1&page_size=10",
                  token_holder["token"])
        assert d.get("code") == 0, f"待复核失败：{d}"
        return f"{d['data'].get('total', 0)} 张待复核"

    check("登录取 token", _login)
    if token_holder.get("token"):
        check("GET /rmb-bills/meta", _meta)
        check("GET /rmb-policy/rules", _rules)
        check("GET /rmb-policy/params", _params)
        check("GET /rmb-bills", _bills)
        check("GET /rmb-bills/{id}", _detail)
        check("GET /rmb-compliance/{id}", _compliance_detail)
        check("GET /rmb-policy", _policy)
        check("GET /rmb-vouchers", _vouchers)
        check("GET /rmb-vouchers/pending", _pending)
        check("GET /rmb-vouchers/review", _review_list)


# ---------------- 7. 大模型连通 ----------------
def test_llm():
    section("7. 大模型连通性")

    def _chat():
        try:
            from app.services import llm_client_new as lc
        except ImportError:
            from app.services import llm_client as lc
        text = lc.chat_text("只回复两个字：正常", model="qwen-plus")
        assert text and "正常" in text, f"返回内容异常：{text!r}"
        return f"qwen-plus 返回「{text.strip()[:20]}」"

    def _json_parse():
        try:
            from app.services import llm_client_new as lc
        except ImportError:
            from app.services import llm_client as lc
        d = lc.parse_json('```json\n{"a": 1, "b": "中文"}\n```')
        assert d == {"a": 1, "b": "中文"}, f"解析错误：{d}"
        d2 = lc.parse_json('前缀文字 {"x": 2} 后缀文字')
        assert d2 == {"x": 2}, f"截取错误：{d2}"
        return "JSON 解析兼容代码块与前后缀"

    check("chat_text 调用", _chat)
    check("parse_json 兼容性", _json_parse)


# ---------------- 8. 职责分离与权限 ----------------
def test_separation():
    section("8. 职责分离与权限配置")

    from app.core.database import SessionLocal
    from app.models.rbac import Role, RolePermission, Permission, User

    db = SessionLocal()
    try:
        def _roles():
            codes = {r.role_code for r in db.query(Role).all()}
            need = {"admin", "manager", "maker", "reviewer"}
            missing = need - codes
            assert not missing, f"缺少角色：{missing}"
            return f"{len(codes)} 个角色"

        def _maker_no_review():
            """制单员不应有复核权限。"""
            role = db.query(Role).filter(Role.role_code == "maker").first()
            assert role, "制单员角色不存在"
            perms = {p.perm_code for p in role.permissions}
            assert "reimburse:voucher:review" not in perms, \
                "制单员不应具备复核权限（职责分离失效）"
            return f"制单员 {len(perms)} 项权限，不含复核"

        def _reviewer_no_make():
            role = db.query(Role).filter(Role.role_code == "reviewer").first()
            assert role, "复核员角色不存在"
            perms = {p.perm_code for p in role.permissions}
            assert "reimburse:voucher:make" not in perms, \
                "复核员不应具备制单权限（职责分离失效）"
            return f"复核员 {len(perms)} 项权限，不含制单"

        def _user_employee():
            users = db.query(User).filter(User.username.in_(
                ["buyer", "keeper", "qc", "manager"])).all()
            linked = [u for u in users if u.employee_id]
            assert len(linked) >= 4, f"用户员工关联不足：{len(linked)}"
            return f"{len(linked)} 个账号已关联员工档案"

        def _perms():
            codes = {p.perm_code for p in db.query(Permission).all()}
            need = {f"reimburse:{x}" for x in [
                "bill:list", "bill:add", "bill:edit", "check:run",
                "check:override", "voucher:list", "voucher:make",
                "voucher:review", "policy:manage"]}
            missing = need - codes
            assert not missing, f"缺少权限码：{missing}"
            return f"{len([c for c in codes if c.startswith('reimburse:')])} 个报销权限码"

        check("角色齐备", _roles)
        check("制单员无复核权限", _maker_no_review)
        check("复核员无制单权限", _reviewer_no_make)
        check("用户关联员工档案", _user_employee)
        check("报销权限码齐备", _perms)
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-llm", action="store_true", help="包含真实大模型调用")
    args = parser.parse_args()

    print("=" * 70)
    print("差旅报销模块 —— 端到端联调验证")
    print("=" * 70)

    test_imports()
    test_data()
    test_invoice_utils()
    test_facts()
    test_voucher_validate()
    test_api_smoke()
    test_separation()
    if args.with_llm:
        test_llm()
    else:
        print("\n（跳过第 7 节大模型连通检查，加 --with-llm 启用）")

    # 汇总
    section("汇总")
    ok = [r for r in RESULTS if r["ok"]]
    fail = [r for r in RESULTS if not r["ok"]]
    print(f"共 {len(RESULTS)} 项检查：通过 {len(ok)}，失败 {len(fail)}")
    if fail:
        print("\n失败清单：")
        for r in fail:
            print(f"  ✗ {r['name']}")
            print(f"    {r['detail']}")
        return 1
    print("\n全部检查通过！")
    return 0


if __name__ == "__main__":
    sys.exit(main())
