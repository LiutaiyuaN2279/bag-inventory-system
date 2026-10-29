"""验证「部门 × 职位」的数据范围权限（真实接口调用）。

背景：权限码只解决「能不能做某个动作」，但制度第四条的分级审批是按部门
层层上报的 —— 部门负责人只应审批**本部门**单据，财务复核/总经理则对公司
整体负责。本次新增 ROLE_DATA_SCOPE 控制：

| 职位 | 数据范围 |
| --- | --- |
| 部门负责人 / 部门总监 | 本部门 |
| 财务复核 / 总经理 / 制单员 / 复核员 / 管理员 | 全公司 |
| 普通员工 / 采购员 / 仓管员 / 质检员 | 仅本人 |

运行（需后端已启动）：
    .venv/Scripts/python.exe scripts/verify_data_scope.py
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


def list_bills(token, page_size=200):
    d = http("GET", f"/api/v1/rmb-bills?page=1&page_size={page_size}", token)
    if d.get("code") != 0:
        return None
    return d["data"]


def main():
    print("=" * 74)
    print("「部门 × 职位」数据范围验证")
    print("=" * 74)

    tokens = {u: login(u) for u in
              ("admin", "depthead", "director", "gm", "finance", "finmaker",
               "sales", "buyer", "manager")}
    print("  9 个账号登录就绪\n")

    # ---------- 1) 可见数量 ----------
    print("[1] 各角色的单据可见范围")

    all_bills = list_bills(tokens["admin"])
    check("admin（全公司）可见全部", all_bills and all_bills["total"] == 10,
          f"{all_bills['total'] if all_bills else '?'} 张")

    for user, expect_all, label in [
        ("gm", True, "总经理"),
        ("finance", True, "财务复核/财务审批"),
        ("finmaker", True, "财务制单/财务审批"),
        ("manager", True, "运营主管/财务复核"),
    ]:
        d = list_bills(tokens[user])
        ok = d and d["total"] == all_bills["total"]
        check(f"{user}（{label}）可见全部单据", ok,
              f"{d['total'] if d else '?'}/{all_bills['total']} 张")

    # 部门管理岗：只看到本部门
    dept_heads = [("depthead", "销售部"), ("director", "销售部")]
    for user, dept in dept_heads:
        d = list_bills(tokens[user])
        if not d:
            check(f"{user} 列表接口", False)
            continue
        depts = {b.get("department_name") for b in d["list"]}
        only_own = depts <= {dept}
        check(f"{user}（{dept}负责人）只看到本部门单据",
              only_own and d["total"] < all_bills["total"],
              f"{d['total']} 张，部门={'、'.join(sorted(x or '?' for x in depts)) or '无'}")

    # 普通报销人：只看本人
    for user in ("sales", "buyer"):
        d = list_bills(tokens[user])
        if not d:
            check(f"{user} 列表接口", False)
            continue
        names = {b.get("employee_name") for b in d["list"]}
        check(f"{user}（普通员工）只看到本人单据",
              d["total"] == 0 or len(names) <= 1,
              f"{d['total']} 张，报销人={'、'.join(sorted(x or '?' for x in names)) or '无'}")

    # ---------- 2) 跨部门审批被拒 ----------
    print("\n[2] 部门负责人不能审批其他部门的单据")
    # 找一张财务部/技术部的单据（非销售部）
    target = None
    for b in all_bills["list"]:
        if b.get("department_name") != "销售部":
            target = b
            break
    if target:
        r = http("POST", f"/api/v1/rmb-bills/{target['id']}/approve",
                 tokens["depthead"], {"action": "approve", "comment": "尝试跨部门审批"})
        check(f"销售部负责人审批「{target['department_name']}」单据 → 应被拒",
              r.get("code") != 0, r.get("message", ""))
    else:
        check("缺少非销售部单据", False)

    # ---------- 3) 同部门审批通过 ----------
    print("\n[3] 部门负责人可以审批本部门单据")
    own = None
    for b in all_bills["list"]:
        amt = float(b.get("amount") or 0)
        if (b.get("department_name") == "销售部" and amt < 5000
                and b.get("status") not in ("已作废", "已生成凭证")):
            own = b
            break
    if own:
        r = http("POST", f"/api/v1/rmb-bills/{own['id']}/approve", tokens["depthead"],
                 {"action": "approve", "comment": "本部门单据，金额低于5000元，审批通过"})
        check(f"销售部负责人审批本部门单据（{own['amount']:,.0f} 元）→ 应通过",
              r.get("code") == 0, r.get("message", ""))
        # 还原审批状态
        if r.get("code") == 0:
            import sqlite3
            backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(backend, "data", "app.db")
            con = sqlite3.connect(db_path)
            con.execute("""update rmb_reimbursement
                set approval_status='未审批', approval_by='', approval_at=NULL,
                    approval_comment='', approval_rank=NULL where id=?""", (own["id"],))
            con.commit()
            con.close()
            print("    （已还原该单审批状态）")
    else:
        check("缺少销售部可审批单据", False)

    # ---------- 4) 全公司范围可跨部门审批 ----------
    print("\n[4] 全公司范围角色可跨部门审批")
    if target:
        r = http("POST", f"/api/v1/rmb-bills/{target['id']}/approve", tokens["gm"],
                 {"action": "approve", "comment": "总经理跨部门审批，数据范围为全公司"})
        check(f"总经理审批「{target['department_name']}」单据 → 应通过",
              r.get("code") == 0, r.get("message", ""))
        if r.get("code") == 0:
            import sqlite3
            backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            con = sqlite3.connect(os.path.join(backend, "data", "app.db"))
            con.execute("""update rmb_reimbursement
                set approval_status='未审批', approval_by='', approval_at=NULL,
                    approval_comment='', approval_rank=NULL where id=?""", (target["id"],))
            con.commit()
            con.close()
            print("    （已还原该单审批状态）")

    # ---------- 5) 详情可见性 ----------
    print("\n[5] 跨部门单据详情不可见")
    if target:
        r = http("GET", f"/api/v1/rmb-bills/{target['id']}", tokens["depthead"])
        check(f"销售部负责人查看「{target['department_name']}」单据详情 → 应被拒",
              r.get("code") != 0, r.get("message", ""))

    print("\n" + "=" * 74)
    ok = [x for x in RESULTS if x["ok"]]
    bad = [x for x in RESULTS if not x["ok"]]
    print(f"共 {len(RESULTS)} 项检查：通过 {len(ok)}，失败 {len(bad)}")
    if bad:
        for x in bad:
            print(f"  ✗ {x['name']}：{x['detail']}")
        return 1
    print("数据范围验证全部通过！")
    return 0


if __name__ == "__main__":
    sys.exit(main())
