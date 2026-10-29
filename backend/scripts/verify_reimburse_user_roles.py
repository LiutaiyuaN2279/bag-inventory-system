"""验证报销专用账号的职责分离（制单 → 复核跨账号流转）。

场景：
1. sales（报销人）创建一张报销单；
2. admin 触发 AI 判读，使其进入「待制证」；
3. finmaker（财务制单员）生成并保存凭证；
4. 验证 finmaker 不能复核自己制作的凭证（应被拒绝）；
5. finance（财务复核员）复核通过（应成功）；
6. 清理本次产生的数据。

运行（需后端已启动）：
    .venv/Scripts/python.exe scripts/verify_reimburse_user_roles.py
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


def http(method, path, token=None, body=None, timeout=240):
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


def login(username):
    d = http("POST", "/api/v1/auth/login",
             body={"username": username, "password": PASSWORD})
    if d.get("code") != 0:
        raise RuntimeError(f"{username} 登录失败：{d.get('message')}")
    return d["data"]["access_token"]


def check(name, cond, detail=""):
    RESULTS.append({"name": name, "ok": bool(cond), "detail": detail})
    print(f"  {'✓' if cond else '✗'} {name}" + (f"：{detail}" if detail else ""))


def main():
    print("=" * 72)
    print("报销专用账号 —— 职责分离验证")
    print("=" * 72)

    tokens = {}
    for u in ("sales", "finmaker", "finance", "admin"):
        tokens[u] = login(u)
        print(f"  {u} 登录成功")

    # ---------- 1) sales 创建报销单 ----------
    print("\n[1] sales 创建报销单 ...")
    meta = http("GET", "/api/v1/rmb-bills/meta", tokens["sales"])["data"]
    employee = meta.get("current_employee")
    if not employee:
        raise RuntimeError("sales 未关联员工档案，无法报销")
    lodging = next((x for x in meta["expense_types"] if x["name"] == "差旅住宿费"),
                   meta["expense_types"][0])
    payload = {
        "employee_id": employee["id"],
        "department_id": employee.get("department_id"),
        "expense_type_id": lodging["id"],
        "settlement_method_id": meta["settlement_methods"][0]["id"],
        "reason": "【角色验证】销售部差旅住宿费",
        "occur_date": "2026-10-12",
        "amount": 1650.00,
        "has_invoice": 0,          # 不附发票：避免发票号与演示数据冲突
        "approver_name": "李强",
        "approver_level": "部门负责人",
        "travel_city": "上海",
        "travel_start": "2026-10-12",
        "travel_end": "2026-10-15",
        "nights": 3,
    }
    sr = http("POST", "/api/v1/rmb-bills/save", tokens["sales"], payload)
    if sr.get("code") != 0:
        print(f"  ✗ 创建失败：{sr.get('message')}")
        return 1
    bill_id = sr["data"]["id"]
    bill_no = sr["data"]["bill_no"]
    print(f"  ✓ 报销单 {bill_no}（id={bill_id}），报销人 {employee['name']}")

    created = {"bill_id": bill_id, "voucher_id": None}
    try:
        # ---------- 2) admin 判读 ----------
        print("\n[2] admin 触发 AI 合规判读 ...")
        cr = http("POST", f"/api/v1/rmb-compliance/run/{bill_id}", tokens["admin"])
        if cr.get("code") != 0:
            print(f"  ✗ 判读失败：{cr.get('message')}")
            return 1
        result = cr["data"].get("overall_result")
        print(f"  ✓ 判读完成：{result}")

        # 判读为合规/需关注才能制证；不合规则人工覆盖
        detail = http("GET", f"/api/v1/rmb-compliance/{bill_id}", tokens["admin"])["data"]
        status = detail["bill"]["status"]
        print(f"  当前状态：{status}")

        if status == "待确认":
            hr = http("POST", f"/api/v1/rmb-compliance/{bill_id}/handle",
                      tokens["admin"], {"action": "submit", "comment": "验证流程，已核对票据"})
            check("需关注单提交制证", hr.get("code") == 0, hr.get("message", ""))
        elif status == "判读不合规":
            hr = http("POST", f"/api/v1/rmb-compliance/{bill_id}/handle", tokens["admin"],
                      {"action": "override",
                       "comment": "验证脚本：该单用于角色权限测试，人工覆盖为可制证状态"})
            check("不合规单人工覆盖", hr.get("code") == 0, hr.get("message", ""))

        # ---------- 3) finmaker 制证并保存 ----------
        print("\n[3] finmaker（财务制单员）生成并保存凭证 ...")
        dr = http("POST", "/api/v1/rmb-vouchers/draft", tokens["finmaker"],
                  {"reimbursement_id": bill_id})
        if dr.get("code") != 0:
            print(f"  ✗ 制证失败：{dr.get('message')}")
            return 1
        draft = dr["data"]
        check("finmaker 可生成凭证草稿", True,
              f"{len(draft['entries'])} 行分录，errors={draft.get('errors')}")

        save_body = {
            "reimbursement_id": bill_id,
            "header": draft["header"],
            "entries": draft["entries"],
            "ai_explanation": draft.get("explanation", ""),
            "ai_tax_treatment": draft.get("tax_treatment", ""),
            "ai_model": draft.get("model", ""),
        }
        sv = http("POST", "/api/v1/rmb-vouchers/save", tokens["finmaker"], save_body)
        if sv.get("code") != 0:
            print(f"  ✗ 保存凭证失败：{sv.get('message')}")
            return 1
        voucher_id = sv["data"]["id"]
        voucher_code = sv["data"]["voucher_code"]
        created["voucher_id"] = voucher_id
        check("finmaker 保存凭证成功", True, f"{voucher_code}（id={voucher_id}）")

        # ---------- 4) finmaker 不能复核自己的凭证 ----------
        print("\n[4] finmaker 尝试复核自己制作的凭证（应被拒绝）...")
        rv = http("POST", f"/api/v1/rmb-vouchers/review/{voucher_id}", tokens["finmaker"],
                  {"action": "approve", "comment": "自审测试"})
        check("制单人不能自审", rv.get("code") != 0, rv.get("message", ""))

        # ---------- 5) finance 复核 ----------
        print("\n[5] finance（财务复核员）复核 ...")
        rv2 = http("POST", f"/api/v1/rmb-vouchers/review/{voucher_id}", tokens["finance"],
                   {"action": "approve",
                    "comment": "凭证分录与制度依据核对无误，进项税额处理正确，同意通过。"})
        check("finance 复核通过", rv2.get("code") == 0, rv2.get("message", ""))

        # ---------- 6) 交叉验证权限 ----------
        print("\n[6] 交叉验证账号权限边界 ...")
        p_review = http("GET", "/api/v1/rmb-vouchers/review?page=1&page_size=1", tokens["finmaker"])
        check("finmaker 无复核权限", p_review.get("code") != 0, p_review.get("message", ""))
        p_make = http("GET", "/api/v1/rmb-vouchers/pending?page=1&page_size=1", tokens["finance"])
        check("finance 无制单权限", p_make.get("code") != 0, p_make.get("message", ""))
        p_policy = http("GET", "/api/v1/rmb-policy", tokens["finance"])
        check("finance 无制度管理权限", p_policy.get("code") != 0, p_policy.get("message", ""))

    finally:
        # ---------- 清理 ----------
        print("\n[清理] 删除本次验证产生的数据 ...")
        if created["voucher_id"]:
            db_ok = http("DELETE", f"/api/v1/rmb-bills/{bill_id}", tokens["admin"])
            print(f"  删除报销单：{'成功' if db_ok.get('code') == 0 else db_ok.get('message')}")
        else:
            db_ok = http("DELETE", f"/api/v1/rmb-bills/{bill_id}", tokens["admin"])
            print(f"  删除报销单：{'成功' if db_ok.get('code') == 0 else db_ok.get('message')}")

    print("\n" + "=" * 72)
    ok = [x for x in RESULTS if x["ok"]]
    bad = [x for x in RESULTS if not x["ok"]]
    print(f"共 {len(RESULTS)} 项检查：通过 {len(ok)}，失败 {len(bad)}")
    if bad:
        for x in bad:
            print(f"  ✗ {x['name']}：{x['detail']}")
        return 1
    print("职责分离验证全部通过！")
    return 0


if __name__ == "__main__":
    sys.exit(main())
