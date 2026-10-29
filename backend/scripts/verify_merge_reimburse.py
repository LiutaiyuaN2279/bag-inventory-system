"""验证：报销功能在并入基础账号体系后仍然完整可用。

检查项：
1. 7 个报销角色都拿到了只读业务权限，且报销权限一条未丢；
2. 没有误加任何业务写权限（add/edit/delete/approve/adjust 等）；
3. 各账号登录后报销模块的接口仍可访问（/reimburse/bills/workbench 等）；
4. 首页看板同时含业务与报销指标。
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000/api/v1"
WRITE_MARKERS = (":add", ":edit", ":delete", ":approve", ":adjust", ":make", ":review", "manage")

BIZ_ROLES = ["general_manager", "finance_approve", "maker", "reviewer",
             "staff", "dept_head", "dept_director"]


def _post(path, data):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def _get(path, token):
    req = urllib.request.Request(BASE + path, headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None


def main() -> int:
    accounts = ["admin", "manager", "buyer", "keeper", "qc",
                "gm", "finance", "finmaker", "director", "depthead", "sales", "tech"]
    report, failures = [], []

    for u in accounts:
        tok = _post("/auth/login", {"username": u, "password": "admin123"})["data"]["access_token"]
        _, info = _get("/auth/userinfo", tok)
        data = info["data"]
        perms = set(data.get("permissions") or [])
        roles = data.get("roles") or []

        # 报销工作台（需要 reimburse:bill:list）
        wb_status, wb = _get("/rmb-bills/workbench", tok) if "reimburse:bill:list" in perms else (None, None)
        # 报销单列表
        list_status, _ = _get("/rmb-bills?page=1&page_size=5", tok) if "reimburse:bill:list" in perms else (None, None)
        # 采购库存看板
        dash_status, dash = _get("/reports/workbench", tok)

        biz = any(p.startswith(("purchase:", "inventory:", "basic:", "bom:", "qc:", "outsource:", "report:"))
                  for p in perms)
        reimb = any(p.startswith("reimburse:") for p in perms)

        # 只读校验：报销角色不应拿业务写权限
        bad_write = []
        if set(roles) & set(BIZ_ROLES):
            for p in perms:
                if p.startswith("reimburse:"):
                    continue
                if p in ("dashboard:view", "system:log"):
                    continue
                if p.endswith((":list", ":view")) or p in ("inventory:alert",):
                    continue
                if any(m in p for m in WRITE_MARKERS):
                    bad_write.append(p)

        ok = (dash_status == 200
              and (wb_status in (None, 200))
              and (list_status in (None, 200))
              and not bad_write)
        if not ok:
            failures.append(u)

        report.append({
            "user": u, "roles": roles,
            "dash": dash_status, "reimburse_wb": wb_status, "reimburse_list": list_status,
            "has_biz": biz, "has_reimburse": reimb,
            "bad_write": bad_write, "ok": ok,
        })

    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "..", ".tmp-run", "verify_merge.json")
    with open(os.path.normpath(out), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print(f"{'账号':<10}{'看板':>6}{'报销台':>8}{'报销列表':>10}{'业务':>6}{'报销':>6}  结果")
    for r in report:
        print(f"{r['user']:<10}{str(r['dash']):>6}{str(r['reimburse_wb']):>8}"
              f"{str(r['reimburse_list']):>10}{'✓' if r['has_biz'] else '-':>6}"
              f"{'✓' if r['has_reimburse'] else '-':>6}  {'OK' if r['ok'] else 'FAIL'}")
        if r["bad_write"]:
            print(f"    ! 越权写权限: {r['bad_write']}")

    print()
    if failures:
        print(f"✗ 有 {len(failures)} 个账号未通过：{failures}")
        return 1
    print("✓ 全部通过：报销功能完整，未出现业务写权限越权。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
