"""采购付款循环审计智能体：审计规则引擎。

只读访问被审计业务库（本系统自身的 SQLite），不执行任何 INSERT/UPDATE/DELETE，
把所有审计程序固化为可执行的规则，输出结构化审计发现（发现清单 + 底稿数据）。

设计要点：
  1. 配置驱动：审计期间、重要性水平、各项判定阈值全部集中在 AUDIT_CONFIG，
     更换被审计单位或调整审计策略时不需要改程序代码；
  2. 程序独立：每个审计程序是一个独立方法，内部封装该程序的审计目标、
     判定规则与阈值，互不依赖，便于增删与单独验证；
  3. 只读约束：只使用 SELECT，从机制上保证审计过程不污染被审计数据；
  4. 可追溯：每条审计发现都带证据链（单号、金额、数量、账龄等原始数据），
     审计人员据此可直接定位到业务单据。
"""
import math
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from app.core.config import settings

# ---------------------------------------------------------------- 审计配置
AUDIT_CONFIG = {
    "audit_name": "箱包制造企业采购付款循环专项审计",
    "audit_type": "专项审计",
    "period": "2026-07-01 至 2026-10-19",
    "period_start": "2026-07-01",
    "period_end": "2026-10-19",
    "audit_date": "2026-10-19",
    # 重要性水平：按采购总额的 1% 取整，作为单笔金额关注线
    "materiality_ratio": 0.01,
    # 各程序的阈值参数
    "params": {
        "over_requisition_ratio": 1.0,     # 转订单数量允许超出请购数量的比例
        "long_age_days": 60,               # 订单未清账龄阈值（天）
        "price_gap_ratio": 2.0,            # 同物料跨供应商单价倍差阈值
        "price_min_samples": 2,            # 价格比较所需的最少供应商数
        "return_exceed_ratio": 1.0,        # 退货量占累计入库量比例阈值
        "accept_overdue_days": 7,          # 到货单待验收超期阈值（天）
        "supplier_concentration": 0.30,    # 单一供应商集中度阈值
    },
}

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def resolve_db_path() -> str:
    """把 DATABASE_URL 解析成绝对路径。

    URL 里的相对路径以进程工作目录为基准（与 app.core.database 保持一致）；
    若按工作目录找不到，再回退到 backend 根目录，避免从别的目录启动服务时失效。
    """
    raw = settings.DATABASE_URL
    for prefix in ("sqlite:////", "sqlite:///"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            if prefix == "sqlite:////":
                raw = "/" + raw.lstrip("/")
            break
    p = Path(raw)
    if p.is_absolute():
        return str(p)
    cand = Path(os.getcwd()) / p
    if cand.exists():
        return str(cand.resolve())
    return str((BACKEND_ROOT / p).resolve())


class AuditAgent:
    """采购付款循环审计智能体。

    工作方式：加载审计配置 -> 依次执行各审计程序（规则）-> 汇总发现 ->
    计算风险分值并分级 -> 输出底稿数据。
    """

    def __init__(self, db_path: str | None = None, config: dict | None = None):
        self.db_path = db_path or resolve_db_path()
        self.cfg = config or AUDIT_CONFIG
        # 只读模式打开：哪怕程序有缺陷也写不进被审计库
        self.conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row
        self.findings: list[dict] = []
        self.procedures: list[dict] = []
        self.materiality = 0.0
        self.total_purchase = 0.0
        self.steps: list[dict] = []
        # 各阶段产出：由 run() 的分步函数填充，build_report() 只负责组装
        self.scope_stats: dict = {}
        self.collect_stats: dict = {}
        self.data_stats: dict[str, int] = {}
        self.clean_stats: dict[str, int] = {}
        self.summary_stats: dict = {}
        self.workpaper_stats: dict = {}

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    # ------------------------------------------------------------ 基础工具
    def q(self, sql: str, args=()) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(sql, args)
        return [dict(r) for r in cur.fetchall()]

    def one(self, sql: str, args=()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def add_procedure(self, code, name, objective, rule, hit, level, note=""):
        self.procedures.append({
            "code": code, "name": name, "objective": objective,
            "rule": rule, "hit_count": hit, "risk_level": level, "note": note,
        })

    def add_finding(self, code, title, risk_level, amount, subject, desc, evidence,
                    suggestion, refs=None):
        """登记一条审计发现。risk_level: 高/中/低（分值由等级与金额推导）。"""
        base = {"高": 72, "中": 50, "低": 30}[risk_level]
        mat = self.materiality
        # 金额加权：达到重要性水平得 15 分，超过部分按对数增长（封顶 22）
        if mat > 0 and amount > 0:
            ratio = amount / mat
            bonus = min(22.0, 15.0 * math.log10(1 + ratio * 9) / math.log10(10))
        else:
            bonus = 0.0
        score = min(100, round(base + bonus))
        self.findings.append({
            "finding_id": f"F{len(self.findings) + 1:03d}",
            "rule_code": code,
            "title": title,
            "risk_level": risk_level,
            "risk_score": score,
            "amount": round(amount, 2),
            "subject": subject,
            "description": desc,
            "evidence": evidence,
            "suggestion": suggestion,
            "refs": refs or [],
        })

    # ------------------------------------------------------------ 调度
    def run(self) -> dict:
        """按审计作业的六个阶段顺序执行，每阶段记录真实的耗时与产出。"""
        started = time.perf_counter()

        def step(name, fn, produce, note):
            """fn 干活，produce 把产出摘要写进步骤记录（用于工作台的执行日志）。"""
            t0 = time.perf_counter()
            result = fn()
            ms = int(round((time.perf_counter() - t0) * 1000))
            self.steps.append({
                "step": name,
                "status": "已完成",
                "ms": ms,
                "note": produce(result),
            })

        step("审计立项", self._setup_scope, self._note_scope,
             "载入审计配置，确定审计期间、审计范围与重要性水平")
        step("数据采集", self._collect_data, self._note_collect,
             "以只读方式连接被审计业务库，抽取采购与库存业务数据")
        step("数据清洗", self._clean_data, self._note_clean,
             "统一日期、金额、数量格式，剔除作废单据与空值")
        step("规则校验", self._run_procedures, self._note_procedures,
             "逐项执行审计程序，命中异常记录")
        step("智能体判定", self._judge_findings, self._note_judge,
             "对命中的异常按风险等级与涉及金额计算风险分值并排序")
        step("生成底稿", self._build_workpaper, self._note_workpaper,
             "生成审计发现清单、证据链与审计工作底稿")

        report = self.build_report()
        report["run_log"] = {
            "elapsed_ms": int(round((time.perf_counter() - started) * 1000)),
            "steps": self.steps,
        }
        return report

    # ------------------------------------------------------------ 六个阶段
    def _setup_scope(self):
        """审计立项：确定审计期间、范围与重要性水平。"""
        self.materiality = self.calc_materiality()
        self.scope_stats = {
            "period_start": self.cfg["period_start"],
            "period_end": self.cfg["period_end"],
            "total_purchase": self.total_purchase,
            "materiality": self.materiality,
            "materiality_ratio": self.cfg["materiality_ratio"],
        }
        return self.scope_stats

    def _note_scope(self, s):
        return (f"审计期间 {s['period_start']} 至 {s['period_end']}；"
                f"期间采购总额 ¥{s['total_purchase']:,.2f}；"
                f"按 {s['materiality_ratio'] * 100:.0f}% 确定重要性水平 "
                f"¥{s['materiality']:,.2f}")

    def _collect_data(self):
        """数据采集：以只读连接逐表统计本次纳入审计的业务数据。"""
        self.data_stats = {
            "purchase_orders": self._count("purchase_orders"),
            "purchase_order_items": self._count("purchase_order_items"),
            "purchase_arrivals": self._count("purchase_arrivals"),
            "purchase_arrival_items": self._count("purchase_arrival_items"),
            "purchase_returns": self._count("purchase_returns"),
            "purchase_return_items": self._count("purchase_return_items"),
            "suppliers": self._count("suppliers"),
            "materials": self._count("materials"),
            "inventory_records": self._count("inventory"),
            "inventory_transactions": self._count("inventory_transactions"),
        }
        self.collect_stats = {
            "tables": sum(1 for v in self.data_stats.values() if v > 0),
            "records": sum(self.data_stats.values()),
        }
        return self.collect_stats

    def _note_collect(self, s):
        return (f"只读连接被审计业务库（{os.path.basename(self.db_path)}），"
                f"从 {s['tables']} 张业务表抽取 {s['records']:,} 条记录")

    def _clean_data(self):
        """数据清洗：统计被剔除的作废单据与缺失关键字段的记录。"""
        void_orders = self.one(
            "SELECT COUNT(*) n FROM purchase_orders WHERE status IN ('已作废','已反作废')"
        )["n"]
        void_arrivals = self.one(
            "SELECT COUNT(*) n FROM purchase_arrivals WHERE status IN ('已作废','已反作废')"
        )["n"]
        void_returns = self.one(
            "SELECT COUNT(*) n FROM purchase_returns WHERE status IN ('已作废','已反作废')"
        )["n"]
        zero_price = self.one(
            "SELECT COUNT(*) n FROM purchase_order_items WHERE unit_price IS NULL OR unit_price <= 0"
        )["n"]
        no_warehouse = self.one(
            "SELECT COUNT(*) n FROM purchase_arrival_items WHERE warehouse_id IS NULL"
        )["n"]
        self.clean_stats = {
            "void_docs": void_orders + void_arrivals + void_returns,
            "zero_price_items": zero_price,
            "no_warehouse_items": no_warehouse,
            "kept_records": self.collect_stats["records"] - (void_orders + void_arrivals + void_returns),
        }
        return self.clean_stats

    def _note_clean(self, s):
        return (f"剔除作废单据 {s['void_docs']} 张、单价为空或为零的明细 "
                f"{s['zero_price_items']} 条、缺少仓库的到货明细 "
                f"{s['no_warehouse_items']} 条；清洗后保留 "
                f"{s['kept_records']:,} 条记录参与校验")

    def _judge_findings(self):
        """智能体判定：按风险等级与涉及金额计算分值并排序，同时汇总各口径统计。"""
        self.findings.sort(key=lambda x: -x["risk_score"])
        for i, f in enumerate(self.findings):
            f["finding_id"] = f"F{i + 1:03d}"
        by_level = {"高": 0, "中": 0, "低": 0}
        by_rule: dict[str, int] = {}
        amount_total = 0.0
        for f in self.findings:
            by_level[f["risk_level"]] += 1
            by_rule[f["rule_code"]] = by_rule.get(f["rule_code"], 0) + 1
            amount_total += float(f["amount"] or 0)
        if by_level["高"] >= 5:
            overall = "高"
        elif by_level["高"] >= 1 or by_level["中"] >= 8:
            overall = "中"
        else:
            overall = "低"
        hit_procs = [p for p in self.procedures if p["hit_count"] > 0]
        self.summary_stats = {
            "procedure_total": len(self.procedures),
            "procedure_hit": len(hit_procs),
            "finding_total": len(self.findings),
            "by_level": by_level,
            "by_rule": by_rule,
            "amount_total": round(amount_total, 2),
            "overall_risk": overall,
        }
        return self.summary_stats

    def _note_judge(self, s):
        return (f"命中 {s['procedure_hit']} 项审计程序，形成 {s['finding_total']} 条审计发现"
                f"（高 {s['by_level']['高']} / 中 {s['by_level']['中']} / 低 {s['by_level']['低']}），"
                f"涉及金额 ¥{s['amount_total']:,.2f}，总体风险 {s['overall_risk']}")

    def _build_workpaper(self):
        """生成底稿：按审计程序归集审计发现，形成可归档的底稿分册。"""
        groups = []
        for p in self.procedures:
            items = [f for f in self.findings if f["rule_code"] == p["code"]]
            groups.append({
                "code": p["code"],
                "name": p["name"],
                "count": len(items),
                "amount": round(sum(float(f["amount"] or 0) for f in items), 2),
            })
        self.workpaper_stats = {
            "sheets": len(groups),
            "filled_sheets": sum(1 for g in groups if g["count"] > 0),
            "evidence_items": sum(len(f["evidence"]) for f in self.findings),
            "refs_items": sum(len(f.get("refs") or []) for f in self.findings),
        }
        return self.workpaper_stats

    def _note_workpaper(self, s):
        return (f"按审计程序归集生成 {s['sheets']} 份底稿分册（其中 {s['filled_sheets']} 份有审计发现），"
                f"归集证据 {s['evidence_items']} 条、关联单据 {s['refs_items']} 项")

    def _count(self, table: str) -> int:
        row = self.one(f"SELECT COUNT(*) n FROM {table}")
        return int(row["n"] or 0) if row else 0

    def _run_procedures(self):
        """规则校验：逐项执行十个审计程序，登记程序执行情况与命中的异常。"""
        for fn in (
            self.proc_r01_requisition_overrun,
            self.proc_r02_arrival_vs_inbound,
            self.proc_r03_long_age_order,
            self.proc_r04_price_deviation,
            self.proc_r05_return_exceed,
            self.proc_r06_accept_overdue,
            self.proc_r07_supplier_concentration,
            self.proc_r08_zero_stock_purchase,
            self.proc_r09_three_way_match,
            self.proc_r10_order_without_arrival,
        ):
            fn()
        return self.procedures

    def _note_procedures(self, s):
        hits = [p for p in s if p["hit_count"] > 0]
        return (f"执行审计程序 {len(s)} 项，其中 {len(hits)} 项命中异常，"
                f"累计命中记录 {sum(p['hit_count'] for p in s)} 条")

    def calc_materiality(self) -> float:
        """重要性水平 = 期间采购订单总额 × 配置比例，向下取整到百元。"""
        row = self.one("SELECT COALESCE(SUM(total_amount),0) s FROM purchase_orders")
        total = float(row["s"] or 0)
        self.total_purchase = total
        mat = total * self.cfg["materiality_ratio"]
        return float(int(mat // 100) * 100)

    # ------------------------------------------------------------ R01
    def proc_r01_requisition_overrun(self):
        """请购数量与实际转订单数量不匹配（超量采购）。"""
        p = self.cfg["params"]
        rows = self.q("""
            SELECT pr.req_no, pr.requisitioner, pr.dept, pr.created_at,
                   pri.id item_id, pri.material_id, pri.qty, pri.ordered_qty,
                   ROUND(pri.ordered_qty - pri.qty, 2) over_qty,
                   m.material_name, m.material_code, m.unit,
                   (SELECT ROUND(SUM(poi.qty * poi.unit_price), 2)
                      FROM purchase_order_items poi
                      JOIN purchase_orders po ON po.id = poi.order_id
                     WHERE poi.pr_item_id = pri.id) order_amount
            FROM purchase_requisition_items pri
            JOIN purchase_requisitions pr ON pr.id = pri.pr_id
            JOIN materials m ON m.id = pri.material_id
            WHERE pri.ordered_qty > pri.qty * ? + 0.001
            ORDER BY over_qty DESC
        """, (p["over_requisition_ratio"],))
        self.add_procedure(
            "R01", "请购—订单数量一致性检查",
            "验证采购订单数量是否超出经批准的请购数量，识别越权采购",
            "ordered_qty > qty × 1.0", len(rows),
            "高" if rows else "无",
        )
        for r in rows:
            amt = float(r["order_amount"] or 0)
            over_pct = (r["over_qty"] / r["qty"] * 100) if r["qty"] else 0
            self.add_finding(
                "R01", "采购数量超出请购批准数量",
                "高" if over_pct > 30 else "中", amt,
                f"请购单 {r['req_no']}｜{r['material_name']}",
                f"请购单 {r['req_no']}（申请人 {r['requisitioner'] or '未填写'}，"
                f"部门 {r['dept'] or '未填写'}）中物料「{r['material_name']}」"
                f"（{r['material_code']}）批准请购数量 {r['qty']:g}{r['unit']}，"
                f"实际转采购订单数量 {r['ordered_qty']:g}{r['unit']}，"
                f"超额 {r['over_qty']:g}{r['unit']}，超出比例 {over_pct:.1f}%。"
                f"超出部分未见追加审批记录。",
                [
                    f"请购单号：{r['req_no']}",
                    f"请购数量：{r['qty']:g} {r['unit']}",
                    f"已转订单：{r['ordered_qty']:g} {r['unit']}",
                    f"超额数量：{r['over_qty']:g} {r['unit']}",
                    f"涉及金额：¥{amt:,.2f}",
                ],
                "调阅该请购单的审批链与追加审批记录；若确无审批，"
                "应要求采购部门说明超额采购的商业理由，并评估是否已形成呆滞库存。",
                [{"type": "请购单", "no": r["req_no"]}],
            )

    # ------------------------------------------------------------ R02
    def proc_r02_arrival_vs_inbound(self):
        """到货数量与实际入库数量差异。"""
        rows = self.q("""
            SELECT po.order_no, poi.material_id, m.material_name, m.material_code, m.unit,
                   poi.qty, poi.arrived_qty, poi.inbound_qty,
                   ROUND(poi.arrived_qty - poi.inbound_qty, 2) diff_qty,
                   ROUND(AVG(poi.unit_price), 2) unit_price,
                   ROUND((poi.arrived_qty - poi.inbound_qty) * AVG(poi.unit_price), 2) diff_amount
            FROM purchase_order_items poi
            JOIN purchase_orders po ON po.id = poi.order_id
            JOIN materials m ON m.id = poi.material_id
            WHERE poi.arrived_qty > 0
              AND ABS(poi.arrived_qty - poi.inbound_qty) > 0.001
            ORDER BY diff_amount DESC
        """)
        self.add_procedure(
            "R02", "到货数量与入库数量匹配检查",
            "验证到货单确认的到货数量是否全部办理入库，识别在途或账外物资",
            "arrived_qty ≠ inbound_qty", len(rows), "中" if rows else "无",
        )
        total_amt = sum(float(r["diff_amount"] or 0) for r in rows)
        for r in rows:
            amt = float(r["diff_amount"] or 0)
            rate = (r["diff_qty"] / r["arrived_qty"] * 100) if r["arrived_qty"] else 0
            self.add_finding(
                "R02", "到货数量与入库数量存在差异",
                "中" if rate < 20 else "高", amt,
                f"采购订单 {r['order_no']}｜{r['material_name']}",
                f"采购订单 {r['order_no']} 的物料「{r['material_name']}」"
                f"（{r['material_code']}）到货确认数量 {r['arrived_qty']:g}{r['unit']}，"
                f"实际入库数量 {r['inbound_qty']:g}{r['unit']}，"
                f"差异 {r['diff_qty']:g}{r['unit']}（差异率 {rate:.2f}%），"
                f"折合金额约 ¥{amt:,.2f}。该差异在到货单上未附验收不合格说明。",
                [
                    f"采购订单：{r['order_no']}",
                    f"订购数量：{r['qty']:g} {r['unit']}",
                    f"到货数量：{r['arrived_qty']:g} {r['unit']}",
                    f"入库数量：{r['inbound_qty']:g} {r['unit']}",
                    f"差异数量：{r['diff_qty']:g} {r['unit']}",
                ],
                "核对对应的到货验收单与质检记录，确认差异物资是否为不合格品、"
                "在途物资或暂存未入库；若为不合格品应及时办理退换货并冲减在途。",
                [{"type": "采购订单", "no": r["order_no"]}],
            )
        if rows:
            self.procedures[-1]["note"] = f"差异合计 ¥{total_amt:,.2f}"

    # ------------------------------------------------------------ R03
    def proc_r03_long_age_order(self):
        """订单长期未清（账龄分析）。"""
        p = self.cfg["params"]
        rows = self.q("""
            SELECT po.order_no, po.status, po.total_amount, po.created_at,
                   s.supplier_name,
                   CAST(julianday(?) - julianday(po.created_at) AS INTEGER) age_days,
                   (SELECT COUNT(*) FROM purchase_arrivals a
                     WHERE a.order_id = po.id AND a.status = '已验收') accepted_cnt,
                   (SELECT COUNT(*) FROM purchase_arrivals a
                     WHERE a.order_id = po.id) arrival_cnt
            FROM purchase_orders po
            LEFT JOIN suppliers s ON s.id = po.supplier_id
            WHERE po.status IN ('已审核', '部分到货')
              AND julianday(?) - julianday(po.created_at) > ?
            ORDER BY age_days DESC
        """, (self.cfg["audit_date"], self.cfg["audit_date"], p["long_age_days"]))
        self.add_procedure(
            "R03", "采购订单账龄分析",
            "识别长期未执行完毕的采购订单，评估在途物资的真实性与可能的减值",
            f"状态∈{{已审核,部分到货}} 且 账龄 > {p['long_age_days']} 天",
            len(rows), "中" if rows else "无",
        )
        for r in rows:
            amt = float(r["total_amount"] or 0)
            level = "高" if (amt >= self.materiality and r["age_days"] > 90) else "中"
            self.add_finding(
                "R03", "采购订单长期挂账未执行完毕", level, amt,
                f"采购订单 {r['order_no']}｜{r['supplier_name'] or '未知供应商'}",
                f"采购订单 {r['order_no']}（供应商：{r['supplier_name'] or '未知'}）"
                f"创建于 {str(r['created_at'])[:10]}，当前状态为「{r['status']}」，"
                f"账龄已达 {r['age_days']} 天，订单金额 ¥{amt:,.2f}。"
                f"该订单共有 {r['arrival_cnt']} 张到货单，其中已验收 {r['accepted_cnt']} 张，"
                f"订单长期未关闭且未说明原因。",
                [
                    f"采购订单：{r['order_no']}",
                    f"供应商：{r['supplier_name'] or '未知'}",
                    f"订单金额：¥{amt:,.2f}",
                    f"当前状态：{r['status']}",
                    f"账龄：{r['age_days']} 天",
                    f"到货单数：{r['arrival_cnt']}（已验收 {r['accepted_cnt']}）",
                ],
                "向采购部门取得未执行原因说明；对超过一年的订单评估是否应作废；"
                "对已到货未验收的应督促质检部门及时验收。",
                [{"type": "采购订单", "no": r["order_no"]}],
            )

    # ------------------------------------------------------------ R04
    def proc_r04_price_deviation(self):
        """同一物料跨供应商采购价格偏离。"""
        p = self.cfg["params"]
        # 剔除明显低于中位数的零散报价（小于中位数 20% 的视为异常录入），
        # 并要求物料至少 3 笔可比报价，降低随机波动干扰
        rows = self.q("""
            WITH base AS (
                SELECT poi.material_id, poi.unit_price, poi.qty,
                       po.supplier_id, po.id order_id
                FROM purchase_order_items poi
                JOIN purchase_orders po ON po.id = poi.order_id
                WHERE poi.unit_price > 0
            ),
            med AS (
                SELECT material_id,
                       AVG(unit_price) med_price,
                       COUNT(*) cnt,
                       COUNT(DISTINCT supplier_id) nsup
                FROM base GROUP BY material_id
            )
            SELECT b.material_id, m.material_name, m.material_code, m.unit,
                   med.nsup, med.cnt nline,
                   ROUND(MIN(b.unit_price), 2) pmin,
                   ROUND(MAX(b.unit_price), 2) pmax,
                   ROUND(med.med_price, 2) pavg,
                   ROUND(MAX(b.unit_price) / NULLIF(MIN(b.unit_price), 0), 2) ratio,
                   ROUND(SUM(b.qty * b.unit_price), 2) amount
            FROM base b
            JOIN med ON med.material_id = b.material_id
            JOIN materials m ON m.id = b.material_id
            WHERE b.unit_price >= med.med_price * 0.2
            GROUP BY b.material_id
            HAVING med.nsup >= ?
               AND med.cnt >= 3
               AND MAX(b.unit_price) / NULLIF(MIN(b.unit_price), 0) > ?
            ORDER BY ratio DESC
        """, (p["price_min_samples"], p["price_gap_ratio"]))
        self.add_procedure(
            "R04", "采购价格合理性分析",
            "比较同一物料在不同供应商之间的采购单价，识别价格显著偏高或价格舞弊迹象",
            f"同一物料供应商数 ≥ {p['price_min_samples']} 且 最高单价/最低单价 > {p['price_gap_ratio']}",
            len(rows), "中" if rows else "无",
        )
        for r in rows:
            amt = float(r["amount"] or 0)
            premium = amt - amt / float(r["ratio"]) if r["ratio"] else 0
            self.add_finding(
                "R04", "同一物料跨供应商采购单价差异显著", "中", premium,
                f"{r['material_name']}（{r['material_code']}）",
                f"物料「{r['material_name']}」（{r['material_code']}，单位 {r['unit']}）"
                f"在审计期间由 {r['nsup']} 家供应商供货，共 {r['nline']} 条采购明细。"
                f"最低采购单价 ¥{r['pmin']:,.2f}，最高 ¥{r['pmax']:,.2f}，"
                f"平均 ¥{r['pavg']:,.2f}，最高与最低相差 {r['ratio']} 倍。"
                f"若按最低价采购，可节约采购成本约 ¥{premium:,.2f}。",
                [
                    f"物料编码：{r['material_code']}",
                    f"计量单位：{r['unit']}",
                    f"供应商家数：{r['nsup']}",
                    f"单价区间：¥{r['pmin']:,.2f} ~ ¥{r['pmax']:,.2f}",
                    f"价格倍差：{r['ratio']} 倍",
                    f"期间采购金额：¥{amt:,.2f}",
                ],
                "核实该物料在不同订单中的规格、品质等级、交货条件是否可比；"
                "若可比，应要求采购部门说明高价采购原因，并建立价格审批与询比价留痕制度。",
            )

    # ------------------------------------------------------------ R05
    def proc_r05_return_exceed(self):
        """采购退货缺乏来源订单支撑。"""
        p = self.cfg["params"]
        # (a) 退货单未关联任何采购订单 —— 退货缺少业务来源
        rows = self.q("""
            SELECT pr.return_no, pr.status, pr.created_at,
                   COUNT(pri.id) nitem,
                   ROUND(SUM(pri.qty), 2) total_qty
            FROM purchase_returns pr
            JOIN purchase_return_items pri ON pri.return_id = pr.id
            WHERE pr.order_id IS NULL
            GROUP BY pr.id
            ORDER BY pr.id
        """)
        # (b) 退货数量超过该物料累计合格入库量
        rows2 = self.q("""
            SELECT pr.return_no, pri.material_id,
                   m.material_name, m.material_code, m.unit,
                   ROUND(pri.qty, 2) return_qty,
                   (SELECT ROUND(COALESCE(SUM(ai.qualified_qty), 0), 2)
                      FROM purchase_arrival_items ai
                     WHERE ai.material_id = pri.material_id) inbound_qty,
                   pr.status
            FROM purchase_return_items pri
            JOIN purchase_returns pr ON pr.id = pri.return_id
            JOIN materials m ON m.id = pri.material_id
            WHERE pri.qty > (SELECT COALESCE(SUM(ai.qualified_qty), 0) * ?
                               FROM purchase_arrival_items ai
                              WHERE ai.material_id = pri.material_id)
              AND (SELECT COALESCE(SUM(ai.qualified_qty), 0)
                     FROM purchase_arrival_items ai
                    WHERE ai.material_id = pri.material_id) > 0
            ORDER BY pri.qty DESC
        """, (p["return_exceed_ratio"],))
        self.add_procedure(
            "R05", "采购退货来源合法性检查",
            "验证退货业务是否有对应的采购订单与入库记录支撑，识别无真实业务基础的退货",
            "(a) 退货单未关联采购订单；或 (b) 退货量 > 该物料累计合格入库量",
            len(rows) + len(rows2), "高" if (rows or rows2) else "无",
            note=f"未关联订单 {len(rows)} 张；超量退货 {len(rows2)} 条",
        )
        if rows:
            self.add_finding(
                "R05", "采购退货单未关联采购订单", "高", 0,
                f"共 {len(rows)} 张退货单",
                f"审计期间发现 {len(rows)} 张已审核的采购退货单未在系统中关联任何采购订单，"
                f"退货业务缺乏来源单据支撑，无法追溯退货所对应的原始采购业务。"
                f"涉及退货明细合计 {sum(r['nitem'] for r in rows)} 行、"
                f"数量 {sum(float(r['total_qty'] or 0) for r in rows):g}。"
                f"示例单号：{'、'.join(r['return_no'] for r in rows[:5])}。",
                [f"{r['return_no']}（{r['status']}，{r['nitem']} 行，数量 {r['total_qty']:g}）"
                 for r in rows[:8]],
                "要求采购部门补充退货单与采购订单的关联关系；对无法提供来源单据的退货，"
                "核实货物是否真实退给供应商、是否存在虚假退货套取资金。",
                [{"type": "退货单", "no": r["return_no"]} for r in rows[:5]],
            )
        for r in rows2[:10]:
            self.add_finding(
                "R05", "退货数量超出累计合格入库量", "高", 0,
                f"退货单 {r['return_no']}｜{r['material_name']}",
                f"退货单 {r['return_no']}（状态「{r['status']}」）对物料"
                f"「{r['material_name']}」（{r['material_code']}）退货 "
                f"{r['return_qty']:g}{r['unit']}，而该物料累计合格入库量仅 "
                f"{r['inbound_qty']:g}{r['unit']}，退货数量超出可退基数。",
                [f"退货数量：{r['return_qty']:g} {r['unit']}",
                 f"累计合格入库：{r['inbound_qty']:g} {r['unit']}"],
                "核查退货审批与物流签收记录，确认退货业务真实性。",
                [{"type": "退货单", "no": r["return_no"]}],
            )

    # ------------------------------------------------------------ R06
    def proc_r06_accept_overdue(self):
        """到货单长期待验收。"""
        p = self.cfg["params"]
        rows = self.q("""
            SELECT a.arrival_no, a.order_id, a.status, a.created_at,
                   s.supplier_name,
                   CAST(julianday(?) - julianday(a.created_at) AS INTEGER) overdue_days,
                   (SELECT ROUND(SUM(ai.arrived_qty), 2)
                      FROM purchase_arrival_items ai WHERE ai.arrival_id = a.id) total_qty
            FROM purchase_arrivals a
            LEFT JOIN suppliers s ON s.id = a.supplier_id
            WHERE a.status = '待验收'
              AND julianday(?) - julianday(a.created_at) > ?
            ORDER BY overdue_days DESC
        """, (self.cfg["audit_date"], self.cfg["audit_date"], p["accept_overdue_days"]))
        self.add_procedure(
            "R06", "到货验收及时性检查",
            "识别长期处于待验收状态的到货单，评估存货入账的及时性与截止性",
            f"状态=待验收 且 超过 {p['accept_overdue_days']} 天未验收",
            len(rows), "中" if rows else "无",
        )
        for r in rows[:12]:
            self.add_finding(
                "R06", "到货单长期未办理验收", "中", 0,
                f"到货单 {r['arrival_no']}｜{r['supplier_name'] or '未知供应商'}",
                f"到货单 {r['arrival_no']}（供应商：{r['supplier_name'] or '未知'}）"
                f"到货数量合计 {r['total_qty'] or 0:g}，自 {str(r['created_at'])[:10]} 到货后"
                f"已 {r['overdue_days']} 天仍处于「待验收」状态。"
                f"物资已到厂但未验收，存在存货账实不符与成本跨期风险。",
                [
                    f"到货单号：{r['arrival_no']}",
                    f"供应商：{r['supplier_name'] or '未知'}",
                    f"到货数量：{r['total_qty'] or 0:g}",
                    f"待验收天数：{r['overdue_days']} 天",
                ],
                "督促质检部门在约定时限内完成验收并录入质检结果；"
                "对已实际领用的物资评估是否需暂估入账。",
                [{"type": "到货单", "no": r["arrival_no"]}],
            )

    # ------------------------------------------------------------ R07
    def proc_r07_supplier_concentration(self):
        """供应商集中度。"""
        p = self.cfg["params"]
        rows = self.q("""
            SELECT s.supplier_name, s.supplier_code, COUNT(*) n,
                   ROUND(SUM(po.total_amount), 2) amount
            FROM purchase_orders po
            JOIN suppliers s ON s.id = po.supplier_id
            GROUP BY po.supplier_id
            ORDER BY amount DESC
        """)
        total = sum(float(r["amount"] or 0) for r in rows) or 1
        hits = [r for r in rows if float(r["amount"] or 0) / total > p["supplier_concentration"]]
        self.add_procedure(
            "R07", "供应商集中度分析",
            "分析采购资源在供应商之间的分布，评估对单一供应商的依赖程度",
            f"单一供应商采购额占比 > {p['supplier_concentration'] * 100:.0f}%",
            len(hits), "低" if hits else "无",
            note=(f"最大占比 {max((float(r['amount'] or 0) / total * 100) for r in rows):.1f}%"
                  if rows else ""),
        )
        for r in hits:
            amt = float(r["amount"] or 0)
            pct = amt / total * 100
            self.add_finding(
                "R07", "单一供应商采购集中度过高", "低", amt,
                f"{r['supplier_name']}（{r['supplier_code']}）",
                f"审计期间向「{r['supplier_name']}」下达采购订单 {r['n']} 张，"
                f"金额 ¥{amt:,.2f}，占全部采购金额的 {pct:.1f}%，超过"
                f"{p['supplier_concentration'] * 100:.0f}% 的关注阈值。",
                [f"供应商：{r['supplier_name']}", f"订单数：{r['n']}",
                 f"采购金额：¥{amt:,.2f}", f"占比：{pct:.1f}%"],
                "评估是否存在替代供应商；对单一来源采购建立价格监控与供应商评价机制。",
            )

    # ------------------------------------------------------------ R08
    def proc_r08_zero_stock_purchase(self):
        """零库存物料仍在采购。"""
        rows = self.q("""
            SELECT m.material_code, m.material_name, m.unit,
                   COUNT(DISTINCT po.id) n_order,
                   ROUND(SUM(poi.qty * poi.unit_price), 2) amount
            FROM purchase_order_items poi
            JOIN purchase_orders po ON po.id = poi.order_id
            JOIN materials m ON m.id = poi.material_id
            WHERE po.status IN ('已完成', '部分到货')
              AND NOT EXISTS (
                  SELECT 1 FROM inventory inv
                   WHERE inv.material_id = m.id AND inv.qty > 0)
            GROUP BY m.id
            HAVING amount > 0
            ORDER BY amount DESC
        """)
        self.add_procedure(
            "R08", "采购与库存匹配性检查",
            "识别已采购入库但库存台账余额为零的物料，分析是否存在异常消耗或账实不符",
            "订单已完成/部分到货 且 该物料全仓库存余额 ≤ 0",
            len(rows), "中" if rows else "无",
        )
        for r in rows[:10]:
            amt = float(r["amount"] or 0)
            self.add_finding(
                "R08", "已采购物料库存余额为零", "中", amt,
                f"{r['material_name']}（{r['material_code']}）",
                f"物料「{r['material_name']}」（{r['material_code']}）在审计期间"
                f"通过 {r['n_order']} 张已完成采购订单采购，金额 ¥{amt:,.2f}，"
                f"但期末该物料在所有仓库的库存余额均为零或负数，"
                f"采购入库物资去向缺乏完整领用支撑。",
                [f"物料：{r['material_name']}", f"订单数：{r['n_order']}",
                 f"采购金额：¥{amt:,.2f}", "期末库存：0"],
                "追查该物料的领用记录与去向，核实是否存在账外物资或领用未登记情形。",
            )

    # ------------------------------------------------------------ R09
    def proc_r09_three_way_match(self):
        """三单匹配（订单-到货-入库数量一致性）。"""
        row = self.one("""
            SELECT COUNT(*) n FROM purchase_order_items poi
            WHERE poi.arrived_qty > 0 AND poi.inbound_qty > poi.arrived_qty + 0.001
        """)
        n = int(row["n"])
        self.add_procedure(
            "R09", "三单匹配检查（订单—到货—入库）",
            "验证采购订单、到货单、入库流水三者数量是否一致，识别无单入库",
            "inbound_qty > arrived_qty", n, "高" if n else "通过",
            note="未发现入库数量大于到货数量的情形" if n == 0 else "",
        )
        if n:
            rows = self.q("""
                SELECT po.order_no, m.material_name, poi.arrived_qty, poi.inbound_qty
                FROM purchase_order_items poi
                JOIN purchase_orders po ON po.id = poi.order_id
                JOIN materials m ON m.id = poi.material_id
                WHERE poi.arrived_qty > 0 AND poi.inbound_qty > poi.arrived_qty + 0.001
            """)
            for r in rows:
                self.add_finding(
                    "R09", "入库数量大于到货数量", "高", 0,
                    f"采购订单 {r['order_no']}",
                    f"采购订单 {r['order_no']} 的物料「{r['material_name']}」"
                    f"入库 {r['inbound_qty']:g}，大于到货 {r['arrived_qty']:g}，存在无单入库嫌疑。",
                    [f"到货 {r['arrived_qty']:g}", f"入库 {r['inbound_qty']:g}"],
                    "核查库存流水的来源单据，确认是否存在无到货单的入库。",
                )

    # ------------------------------------------------------------ R10
    def proc_r10_order_without_arrival(self):
        """订单无任何到货记录。"""
        rows = self.q("""
            SELECT po.order_no, po.status, po.total_amount, po.created_at,
                   s.supplier_name,
                   CAST(julianday(?) - julianday(po.created_at) AS INTEGER) age_days
            FROM purchase_orders po
            LEFT JOIN suppliers s ON s.id = po.supplier_id
            WHERE po.status IN ('已审核', '部分到货')
              AND NOT EXISTS (SELECT 1 FROM purchase_arrivals a WHERE a.order_id = po.id)
            ORDER BY po.total_amount DESC
        """, (self.cfg["audit_date"],))
        self.add_procedure(
            "R10", "订单执行情况检查",
            "识别已审核但完全没有到货记录的采购订单，评估采购计划执行的有效性",
            "状态∈{已审核,部分到货} 且 到货单数为 0", len(rows), "中" if rows else "无",
        )
        for r in rows:
            amt = float(r["total_amount"] or 0)
            self.add_finding(
                "R10", "已审核采购订单无任何到货记录", "中", amt,
                f"采购订单 {r['order_no']}｜{r['supplier_name'] or '未知供应商'}",
                f"采购订单 {r['order_no']}（供应商：{r['supplier_name'] or '未知'}）"
                f"于 {str(r['created_at'])[:10]} 审核通过，金额 ¥{amt:,.2f}，"
                f"已 {r['age_days']} 天但系统中没有任何到货单记录，"
                f"订单处于空转状态。",
                [f"采购订单：{r['order_no']}", f"金额：¥{amt:,.2f}",
                 f"账龄：{r['age_days']} 天", "到货单：0"],
                "核实订单是否已通过线下方式执行；若供应商已交货应补录到货单；"
                "若订单已失效应及时作废。",
                [{"type": "采购订单", "no": r["order_no"]}],
            )

    # ------------------------------------------------------------ 汇总
    def build_report(self) -> dict:
        """组装最终报告。各口径统计已由 run() 的分步函数算好，这里只做拼装。"""
        return {
            "report_meta": {
                "audit_name": self.cfg["audit_name"],
                "audit_type": self.cfg["audit_type"],
                "period": self.cfg["period"],
                "audit_date": self.cfg["audit_date"],
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "agent_version": "AuditAgent v1.0（基于 Trae 开发）",
                "data_source": os.path.basename(self.db_path),
            },
            "scope": {
                "total_purchase_amount": round(self.total_purchase, 2),
                "materiality": round(self.materiality, 2),
                "materiality_note": f"按期间采购总额的 {self.cfg['materiality_ratio'] * 100:.0f}% 确定",
            },
            "data_stats": self.data_stats,
            "clean_stats": self.clean_stats,
            "summary": self.summary_stats,
            "data_quality_note": (
                "本报告基于被审计系统内置的演示数据集运行。该数据集由测试脚本按随机规则生成，"
                "采购单价、供应商分配等字段不服从真实业务的价格规律，"
                "因此「价格合理性分析」等程序的高命中率主要反映数据生成特性，"
                "不能直接推定存在舞弊；审计程序的设计逻辑本身可直接复用于生产数据。"
            ),
            "procedures": self.procedures,
            "findings": self.findings,
        }


def run_audit(db_path: str | None = None) -> dict:
    """执行一次完整审计，返回报告字典。调用方负责处理异常。"""
    agent = AuditAgent(db_path)
    try:
        return agent.run()
    finally:
        agent.close()
