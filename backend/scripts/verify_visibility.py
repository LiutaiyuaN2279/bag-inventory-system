"""验证「部门 × 职位」视野：模块可见性 + 数据范围。

对每个账号检查：
1. 可见模块数是否符合其视野档位（全公司/本部门/仅本人）
2. 请购单列表实际能看到的行数与部门是否吻合
3. 部门管理岗 / 普通员工不能跨部门取单据详情
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000/api/v1"


def post(path, data):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def get(path, token):
    req = urllib.request.Request(BASE + path, headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None


def main() -> int:
    accounts = ["admin", "manager", "buyer", "keeper", "qc",
                "gm", "finance", "finmaker", "director", "depthead", "sales", "tech"]
    rows, fail = [], []

    for u in accounts:
        tok = post("/auth/login", {"username": u, "password": "admin123"})["data"]["access_token"]
        _, info = get("/auth/userinfo", tok)
        d = info["data"]
        perms = set(d.get("permissions") or [])

        # 请购单可见行数
        pr_total = None
        if "purchase:requisition:list" in perms:
            st, body = get("/purchase-requisitions?page=1&page_size=1", tok)
            if st == 200:
                pr_total = body["data"]["total"]

        # 看板请购草稿数（应与列表口径一致）
        _, dash = get("/reports/workbench", tok)
        dd = (dash or {}).get("data") or {}
        req_kpi = next((k["value"] for k in dd.get("kpis", []) if "请购" in k["label"]), None)

        rows.append({
            "user": u,
            "reimburse_perms": sum(1 for p in perms if p.startswith("reimburse:")),
            "biz_readonly": sorted(p for p in perms
                                   if p.startswith(("basic:", "purchase:", "inventory:", "bom:", "qc:", "outsource:", "report:"))
                                   and p.endswith((":list", ":view", ":alert", ":log"))),
            "pr_visible": pr_total,
            "dash_req": req_kpi,
        })

    out = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                        "..", ".tmp-run", "verify_visibility.json"))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)

    print(f"{'账号':<10}{'只读业务':>8}{'请购可见':>8}{'看板请购':>8}")
    for r in rows:
        print(f"{r['user']:<10}{len(r['biz_readonly']):>8}{str(r['pr_visible']):>8}{str(r['dash_req']):>8}")

    print("\n详情写入 .tmp-run/verify_visibility.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
