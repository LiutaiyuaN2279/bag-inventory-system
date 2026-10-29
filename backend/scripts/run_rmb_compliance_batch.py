"""批量执行合规判读并汇总结果（真实调用大模型）。

用途：一次跑完 9 个测试场景的 AI 判读，把「预期方向」与「实际结论」并排列出，
便于核对 AI 判读准确性（对应实验文档表 8-1 与第九部分「AI 表现分析」）。

运行（在 backend 目录，需先启动后端服务）：
    .venv/Scripts/python.exe scripts/run_rmb_compliance_batch.py
    .venv/Scripts/python.exe scripts/run_rmb_compliance_batch.py --only T03,T05
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = os.environ.get("RMB_BASE", "http://127.0.0.1:8000")

# 场景预期方向（实验文档表 8-1）
EXPECT = {
    "T03": ("合规", "总体合规；R06 每晚 550 元未超过 600 元"),
    "T04": ("不合规", "R06 住宿超标：每晚 500 > 400"),
    "T05": ("不合规", "R03/R04/R05 不合规，禁止制证"),
    "T06": ("需关注", "R04 满足例外条件（有说明且总监审批）"),
    "T08": ("不合规", "R01 审批越权：8500 元仅部门负责人审批"),
    "T10": ("不合规", "R07 缺发票且无特批"),
    "T11": ("不合规/需关注", "R08 跨期；补说明后为需关注"),
    "T14": ("不合规/需关注", "R14 内部聚餐不属于业务招待"),
    "T15": ("不合规", "注入无效，仍判不合规"),
    "T20": ("合规/需关注", "25,600 元大额差旅，总经理审批；R01 应合规，可能因与 T08 同期被拆分规则关注"),
}


def http(method, path, token=None, body=None, timeout=240):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
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


def login():
    d = http("POST", "/api/v1/auth/login",
             body={"username": "admin", "password": "admin123"})
    if d.get("code") != 0:
        raise RuntimeError(f"登录失败：{d}")
    return d["data"]["access_token"]


def find_scenes(token):
    """取所有场景报销单，按 T 编号排序。"""
    d = http("GET", "/api/v1/rmb-bills?page=1&page_size=200", token)
    if d.get("code") != 0:
        raise RuntimeError(f"取报销单失败：{d}")
    rows = d["data"]["list"]
    scenes = []
    for r in rows:
        reason = r.get("reason") or ""
        if not reason.startswith("【场景】"):
            continue
        # 从 reason 提取 T 编号：形如「【场景】T03 上海出差住宿费」，
        # 编号紧贴前缀，不能用空格切分（首个 token 是「【场景】T03」整体）
        tag = ""
        body = reason[len("【场景】"):].strip()
        m = re.match(r"(T\d{2})", body)
        if m:
            tag = m.group(1)
        scenes.append({
            "id": r["id"],
            "bill_no": r["bill_no"],
            "tag": tag,
            "reason": reason,
            "amount": r.get("amount"),
            "status": r.get("status"),
            "compliance_result": r.get("compliance_result"),
        })
    scenes.sort(key=lambda x: x["tag"])
    return scenes


def run_one(token, scene):
    """执行判读并取回明细。"""
    d = http("POST", f"/api/v1/rmb-compliance/run/{scene['id']}", token)
    if d.get("code") != 0:
        return {"error": d.get("message", "未知错误")}
    check_id = d["data"].get("id")
    d2 = http("GET", f"/api/v1/rmb-compliance/{scene['id']}", token)
    detail = d2.get("data", {}) if d2.get("code") == 0 else {}
    return {"run": d["data"], "detail": detail}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="只跑指定场景，逗号分隔，如 T03,T05")
    args = parser.parse_args()

    only = {x.strip().upper() for x in args.only.split(",") if x.strip()}

    print("=" * 78)
    print("批量合规判读（真实调用大模型）")
    print("=" * 78)

    token = login()
    print("登录成功\n")

    scenes = find_scenes(token)
    if only:
        scenes = [s for s in scenes if s["tag"] in only]
    if not scenes:
        print("没有可判读的场景报销单，请先运行 scripts/seed_rmb_scenarios.py")
        return 1

    results = []
    for i, s in enumerate(scenes, start=1):
        print(f"[{i}/{len(scenes)}] {s['tag']}  {s['bill_no']}  "
              f"金额 {s['amount']}  状态 {s['status']}")
        t0 = time.time()
        r = run_one(token, s)
        elapsed = time.time() - t0
        if "error" in r:
            print(f"    判读失败：{r['error']}\n")
            results.append({"scene": s, "error": r["error"]})
            continue

        run = r["run"]
        detail = r.get("detail", {})
        check = detail.get("check") or {}
        issues = check.get("issues") or []
        bad = [x for x in issues if x.get("result") == "不合规"]
        warn = [x for x in issues if x.get("result") == "需关注"]
        inconsistent = [x for x in issues if x.get("consistency") == "不一致"]

        overall = run.get("overall_result") or check.get("overall_result")
        expect, expect_desc = EXPECT.get(s["tag"], ("?", ""))
        expect_ok = any(e in (overall or "") for e in expect.split("/"))
        mark = "OK " if expect_ok else "!! "

        print(f"    {mark}结论：{overall}（预期 {expect}）  "
              f"不合规 {len(bad)} 项 / 需关注 {len(warn)} 项 / 不一致 {len(inconsistent)} 项  "
              f"{elapsed:.1f}s")
        if bad:
            print(f"       不合规规则：{', '.join(x['rule_code'] for x in bad)}")
        if warn:
            print(f"       需关注规则：{', '.join(x['rule_code'] for x in warn)}")
        if inconsistent:
            print(f"       不一致规则：{', '.join(x['rule_code'] for x in inconsistent)}")

        results.append({
            "scene": s, "overall": overall, "expect": expect, "ok": expect_ok,
            "summary": check.get("summary") or run.get("summary"),
            "bad": [x["rule_code"] for x in bad],
            "warn": [x["rule_code"] for x in warn],
            "inconsistent": len(inconsistent),
            "elapsed": elapsed,
            "issues": issues,
        })
        print()

    # 汇总
    print("=" * 78)
    print("汇总")
    print("=" * 78)
    ok = [r for r in results if r.get("ok")]
    bad_results = [r for r in results if r.get("error")]
    mismatch = [r for r in results if not r.get("ok") and not r.get("error")]
    print(f"共 {len(results)} 个场景：方向符合预期 {len(ok)}，"
          f"方向不符 {len(mismatch)}，调用失败 {len(bad_results)}")
    if mismatch:
        print("\n方向不符的场景：")
        for r in mismatch:
            print(f"  {r['scene']['tag']}: 实际 {r['overall']} / 预期 {r['expect']}")
    if bad_results:
        print("\n调用失败：")
        for r in bad_results:
            print(f"  {r['scene']['tag']}: {r['error']}")
    total_elapsed = sum(r.get("elapsed", 0) for r in results)
    print(f"\n判读总耗时 {total_elapsed:.1f} 秒，平均 "
          f"{total_elapsed / max(len(results), 1):.1f} 秒/单")
    print("\n提示：AI 判读存在一定不确定性，方向不符时请查看判读理由，"
          "判断是 AI 误判、事实数据有误还是规则描述不清。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
