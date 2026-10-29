"""验证制度第四条「分级审批」角色与权限（真实接口调用）。

覆盖：
1. 4 个审批角色存在且层级正确；
2. 按金额计算所需审批层级（<5000→1 级，5000~20000→2 级，≥20000→3 级）；
3. 低层级不能越权审批大额单据；
4. 高层级可审批低层级单据（向上兼容）；
5. 报销人不能审批自己的单据（自审防范）；
6. 无审批权限码的账号不能审批。

运行（需后端已启动）：
    .venv/Scripts/python.exe scripts/verify_approval_roles.py
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = os.environ.get("RMB_BASE", "http://127.0.0.1:8000")
PASSWORD = "admin123"
RESULTS = []


def http(method, path, token=None, body=None, timeout=120):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"code": -1, "message": f"HTTP {exc.code}: {raw[:200]}"}


def login(u):
    d = http("POST", "/api/v1/auth/login", body={"username": u, "password": PASSWORD})
    if d.get("code") != 0:
        raise RuntimeError(f"{u} 登录失败：{d.get('message')}")
    return d["data"]["access_token"]


def check(name, cond, detail=""):
    RESULTS.append({"name": name, "ok": bool(cond), "detail": detail})
    print(f"  {'✓' if cond else '✗'} {name}" + (f"：{detail}" if detail else ""))


def find_bill(token, lo, hi):
    """找一张金额落在 [lo, hi] 区间、状态可审批的演示单据。"""
    d = http("GET", "/api/v1/rmb-bills?page=1&page_size=100", token)
    if d.get("code") != 0:
        return None
    for b in d["data"]["list"]:
        amt = float(b.get("amount") or 0)
        if lo <= amt <= hi and b.get("status") not in ("已作废", "已生成凭证"):
            return b
    return None


def main():
    print("=" * 74)
    print("制度第四条「分级审批」验证")
    print("=" * 74)

    admin = login("admin")
    tokens = {u: login(u) for u in ("depthead", "director", "gm", "buyer", "manager", "sales")}
    print("  账号登录就绪：admin / depthead / director / gm / buyer / manager / sales\n")

    # ---------- 1) 角色与层级 ----------
    print("[1] 审批角色与层级")
    roles = http("GET", "/api/v1/roles?page=1&page_size=100", admin)
    role_codes = {r["role_code"] for r in (roles.get("data", {}).get("list") or [])} \
        if roles.get("code") == 0 else set()
    for code, name in [("dept_head", "部门负责人"), ("finance_review", "财务复核"),
                       ("dept_director", "部门总监"), ("general_manager", "总经理")]:
        check(f"角色 {code}（{name}）存在", code in role_codes)

    # ---------- 2) 按金额算所需层级 ----------
    print("\n[2] 按金额计算所需审批层级（制度第四条）")
    cases = [(0, 1000, 1), (1000, 4999, 1), (5000, 19999, 2), (20000, 30000, 3)]
    for lo, hi, expect in cases:
        bill = find_bill(admin, lo, hi)
        if not bill:
            check(f"{lo}~{hi} 元区间无可用单据", False, "缺少该金额区间的演示数据")
            continue
        detail = http("GET", f"/api/v1/rmb-bills/{bill['id']}", admin)
        need = detail["data"].get("required_approval_rank")
        check(f"金额 {bill['amount']:,.0f} 元 → 需 {need} 级审批（预期 {expect}）",
              need == expect, f"{bill['bill_no']}")

    # ---------- 3~5 用临时单据测试，避免污染演示数据 ----------
    temps = []   # 记录临时创建的单据 id，最后清理

    def make_temp_bill(amount: float, reason: str):
        """以 sales（郑洁，销售部）身份创建一张临时报销单。

        必须用**销售部**员工创建：本脚本要用 depthead / director 审批，
        而部门管理岗的数据范围是本部门（ROLE_DATA_SCOPE），跨部门会被正确拦截。
        不附发票，避免与演示数据的发票号冲突。
        """
        meta = http("GET", "/api/v1/rmb-bills/meta", tokens["sales"])["data"]
        emp = meta.get("current_employee")
        if not emp:
            return None
        lodging = next((x for x in meta["expense_types"] if x["name"] == "差旅住宿费"),
                       meta["expense_types"][0])
        sr = http("POST", "/api/v1/rmb-bills/save", tokens["sales"], {
            "employee_id": emp["id"], "department_id": emp.get("department_id"),
            "expense_type_id": lodging["id"],
            "settlement_method_id": meta["settlement_methods"][0]["id"],
            "reason": f"【审批验证】{reason}",
            "occur_date": "2026-10-12", "amount": amount, "has_invoice": 0,
            "approver_name": "李强", "approver_level": "部门负责人",
            "travel_city": "上海", "travel_start": "2026-10-12",
            "travel_end": "2026-10-15", "nights": 3,
        })
        if sr.get("code") != 0:
            print(f"    （创建失败：{sr.get('message')}）")
            return None
        temps.append(sr["data"]["id"])
        return sr["data"]

    # ---------- 3) 越权审批被拒 ----------
    print("\n[3] 低层级不能越权审批大额单据")
    mid = make_temp_bill(8500.00, "越权审批测试（8500元）")
    if mid:
        r = http("POST", f"/api/v1/rmb-bills/{mid['id']}/approve", tokens["depthead"],
                 {"action": "approve", "comment": "尝试越权审批"})
        check("部门负责人（1级）审批 8,500 元单据 → 应被拒",
              r.get("code") != 0, r.get("message", ""))
        # 2 级审批应通过
        r2 = http("POST", f"/api/v1/rmb-bills/{mid['id']}/approve", tokens["director"],
                  {"action": "approve", "comment": "部门总监审批通过（8500元属2级）"})
        check("部门总监（2级）审批 8,500 元单据 → 应通过",
              r2.get("code") == 0, r2.get("message", ""))
    else:
        check("创建临时单据（8500元）", False)

    # ---------- 4) 向上兼容 ----------
    print("\n[4] 高层级可审批低层级单据（向上兼容）")
    small = make_temp_bill(2400.00, "向上兼容测试（2400元）")
    if small:
        r = http("POST", f"/api/v1/rmb-bills/{small['id']}/approve", tokens["gm"],
                 {"action": "approve", "comment": "总经理审批小额单据，向上兼容验证"})
        check("总经理（3级）审批 2,400 元单据 → 应通过",
              r.get("code") == 0, r.get("message", ""))
    else:
        check("创建临时单据（2400元）", False)

    # ---------- 4b) 大额单据 2 级越权、3 级通过 ----------
    print("\n[4b] 25,600 元大额单据须总经理审批")
    big = make_temp_bill(25600.00, "大额审批测试（25600元）")
    if big:
        r = http("POST", f"/api/v1/rmb-bills/{big['id']}/approve", tokens["director"],
                 {"action": "approve", "comment": "总监尝试审批大额"})
        check("部门总监（2级）审批 25,600 元单据 → 应被拒",
              r.get("code") != 0, r.get("message", ""))
        r2 = http("POST", f"/api/v1/rmb-bills/{big['id']}/approve", tokens["gm"],
                  {"action": "approve", "comment": "总经理审批大额差旅，同意报销"})
        check("总经理（3级）审批 25,600 元单据 → 应通过",
              r2.get("code") == 0, r2.get("message", ""))
    else:
        check("创建临时单据（25600元）", False)

    # ---------- 5) 无审批权限码不能审批 ----------
    print("\n[5] 无审批权限码的账号不能审批")
    target = make_temp_bill(1500.00, "权限码测试（1500元）")
    if target:
        r = http("POST", f"/api/v1/rmb-bills/{target['id']}/approve", tokens["sales"],
                 {"action": "approve", "comment": "普通员工尝试审批"})
        check("普通员工（无 approve 权限码）审批 → 应被拒",
              r.get("code") != 0, r.get("message", ""))
    else:
        check("创建临时单据（1500元）", False)

    # ---------- 6) 报销人不能自审 ----------
    print("\n[6] 报销人不能审批自己提交的单据")
    # manager（陈静）同时有报销权与财务复核审批权
    meta = http("GET", "/api/v1/rmb-bills/meta", tokens["manager"])["data"]
    emp = meta.get("current_employee")
    if emp:
        lodging = next((x for x in meta["expense_types"] if x["name"] == "差旅住宿费"),
                       meta["expense_types"][0])
        sr = http("POST", "/api/v1/rmb-bills/save", tokens["manager"], {
            "employee_id": emp["id"], "department_id": emp.get("department_id"),
            "expense_type_id": lodging["id"],
            "settlement_method_id": meta["settlement_methods"][0]["id"],
            "reason": "【审批验证】自审测试单据",
            "occur_date": "2026-10-12", "amount": 3000.00, "has_invoice": 0,
            "approver_name": "陈静", "approver_level": "财务复核",
            "travel_city": "上海", "travel_start": "2026-10-12",
            "travel_end": "2026-10-15", "nights": 3,
        })
        if sr.get("code") == 0:
            bid = sr["data"]["id"]
            r = http("POST", f"/api/v1/rmb-bills/{bid}/approve", tokens["manager"],
                     {"action": "approve", "comment": "自审测试"})
            check("同一账号「自己报销、自己审批」→ 应被拒",
                  r.get("code") != 0, r.get("message", ""))
            # 该单由 manager 创建，需用同一账号删除（删除仅限本人）
            http("DELETE", f"/api/v1/rmb-bills/{bid}", tokens["manager"])
        else:
            check("创建自审测试单据", False, sr.get("message", ""))

    # ---------- 清理临时单据 ----------
    if temps:
        print(f"\n[清理] 删除 {len(temps)} 张临时测试单据 ...")
        cleaned = 0
        for bid in temps:
            # 删除接口只允许报销人本人操作，这批单据均由 sales 创建
            d = http("DELETE", f"/api/v1/rmb-bills/{bid}", tokens["sales"])
            if d.get("code") == 0:
                cleaned += 1
        print(f"  已删除 {cleaned}/{len(temps)} 张（演示数据未受影响）")

    print("\n" + "=" * 74)
    ok = [x for x in RESULTS if x["ok"]]
    bad = [x for x in RESULTS if not x["ok"]]
    print(f"共 {len(RESULTS)} 项检查：通过 {len(ok)}，失败 {len(bad)}")
    if bad:
        for x in bad:
            print(f"  ✗ {x['name']}：{x['detail']}")
        return 1
    print("分级审批验证全部通过！")
    return 0


if __name__ == "__main__":
    sys.exit(main())
