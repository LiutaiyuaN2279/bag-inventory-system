"""验证视野边界：跨部门详情访问应被拒绝，看板与列表口径应一致。"""
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
    """返回 (业务码, 数据)。本系统统一用 HTTP 200 + body.code 表达业务错误，
    所以判断「有没有权限」要看 code，而不是 HTTP 状态码。"""
    req = urllib.request.Request(BASE + path, headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = json.loads(r.read())
            return body.get("code", 0), body.get("data")
    except urllib.error.HTTPError as e:
        return e.code, None


def ok_code(code) -> bool:
    return code == 0


def main() -> int:
    problems = []

    # 1) 找到一个「非销售部」的请购单 id
    admin_tok = post("/auth/login", {"username": "admin", "password": "admin123"})["data"]["access_token"]
    _, body = get("/purchase-requisitions?page=1&page_size=100", admin_tok)
    all_rows = body["list"]
    foreign = next((r for r in all_rows if r["dept"] != "销售部"), None)
    own = next((r for r in all_rows if r["dept"] == "销售部"), None)
    print(f"参照单据：部门外 #{foreign['id']}({foreign['dept']}) / 本部门 #{own['id']}({own['dept']})")

    # 2) 部门负责人：本部门详情应可看，跨部门应被拒
    for user, label in [("depthead", "部门负责人"), ("director", "部门总监")]:
        tok = post("/auth/login", {"username": user, "password": "admin123"})["data"]["access_token"]
        c_own, _ = get(f"/purchase-requisitions/{own['id']}", tok)
        c_foreign, _ = get(f"/purchase-requisitions/{foreign['id']}", tok)
        ok = ok_code(c_own) and not ok_code(c_foreign)
        print(f"  {label}({user}): 本部门详情 code={c_own} 跨部门详情 code={c_foreign}  {'✓' if ok else '✗'}")
        if not ok:
            problems.append(f"{user} 详情越权")

    # 3) 普通员工：无采购单据权限，列表与详情都该被业务码拒绝
    for user in ("sales", "tech"):
        tok = post("/auth/login", {"username": user, "password": "admin123"})["data"]["access_token"]
        c_list, body = get("/purchase-requisitions?page=1&page_size=1", tok)
        c_detail, _ = get(f"/purchase-requisitions/{own['id']}", tok)
        ok = not ok_code(c_list) and not ok_code(c_detail)
        print(f"  普通员工({user}): 列表 code={c_list} 详情 code={c_detail}  {'✓' if ok else '✗'}")
        if not ok:
            problems.append(f"{user} 越权")

    # 4) 业务岗不应被收窄（采购员看全部）
    for user in ("admin", "manager", "buyer"):
        tok = post("/auth/login", {"username": user, "password": "admin123"})["data"]["access_token"]
        _, b = get("/purchase-requisitions?page=1&page_size=1", tok)
        total = b["total"]
        ok = total == len(all_rows)
        print(f"  业务岗({user}): 可见 {total} 条 {'✓' if ok else '✗'}")

    # 5) 看板请购待办与列表口径一致（部门负责人）
    tok = post("/auth/login", {"username": "depthead", "password": "admin123"})["data"]["access_token"]
    _, dd = get("/reports/workbench", tok)
    todo_req = next((t["count"] for t in dd.get("todos", []) if "请购" in t["title"]), None)
    _, b = get("/purchase-requisitions?page=1&page_size=1&status=" + urllib.parse.quote("草稿"), tok)
    list_draft = b["total"]
    same = (todo_req == list_draft) if todo_req is not None else (list_draft == 0)
    print(f"\n  部门负责人看板请购待办={todo_req} / 列表草稿数={list_draft}  {'✓' if same else '✗'}")
    if not same:
        problems.append("看板与列表口径不一致")

    print()
    if problems:
        print("✗ 存在问题：", problems)
        return 1
    print("✓ 视野边界全部正确")
    return 0


if __name__ == "__main__":
    sys.exit(main())
