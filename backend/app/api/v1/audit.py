"""智能审计工作台：采购付款循环审计智能体的接口层。

业务库只读；试算结果与依据写入独立不可覆盖归档，绝不发布正式报告。
"""
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Header

from app.api.deps import require_permissions
from app.models.rbac import User
from app.services.audit_service import AUDIT_CONFIG, run_audit
from app.core.config import settings
from app.core.exceptions import BizException
from app.services.audit_assurance import legacy_assurance
from app.services.audit_trial_archive import TrialArchive, TrialArchiveError
from app.utils.response import success

def require_audit_contract(x_audit_contract: str | None = Header(None)):
    # Old workpaper UIs turn empty/unknown into "no abnormality". Do not serve
    # the new restricted contract to clients which cannot display it (D05).
    if x_audit_contract != "b002-p0-v1":
        raise BizException("审计界面版本过旧，请更新后查看受限试算；其他业务接口不受影响")


router = APIRouter(prefix="/audit", tags=["智能审计"], dependencies=[Depends(require_audit_contract)])

# 一次审计只需几毫秒，但并发请求下没必要重复执行同一份只读分析。
# 用极短的 TTL 缓存把同一瞬间的多份请求合并，同时保证「执行审计」按钮每次都真跑。
_CACHE_TTL_MS = 1500
_cache_lock = threading.Lock()
_cache = {"at": 0.0, "data": None}


def _now_ms() -> float:
    return datetime.now().timestamp() * 1000


def trial_archive() -> TrialArchive:
    root = Path(settings.AUDIT_TRIAL_ARCHIVE_DIR)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[3] / root
    return TrialArchive(root)


def get_audit_result(force: bool = False, run_id: str | None = None) -> dict:
    """取审计结果；force=True 时强制重新执行（对应「执行审计」动作）。"""
    if run_id is not None:
        try:
            return trial_archive().read(run_id)["report"]
        except TrialArchiveError as exc:
            raise BizException(str(exc)) from exc
    with _cache_lock:
        now = _now_ms()
        if not force and _cache["data"] is not None and now - _cache["at"] < _CACHE_TTL_MS:
            return deepcopy(_cache["data"])
        data = run_audit()
        basis = data.pop("_snapshot_basis")
        try:
            data = trial_archive().save(data, basis)["report"]
        except (OSError, ValueError) as exc:
            raise BizException("试算快照保存失败，未生成可查询版本；未修改业务数据") from exc
        _cache["data"] = data
        _cache["at"] = _now_ms()
        return deepcopy(data)


@router.get("/config", summary="审计配置（审计期间、重要性水平与阈值参数）")
def audit_config(_user: User = Depends(require_permissions("audit:view"))):
    return success({
        "audit_name": AUDIT_CONFIG["audit_name"],
        "audit_type": AUDIT_CONFIG["audit_type"],
        "period": AUDIT_CONFIG["period"],
        "period_start": AUDIT_CONFIG.get("period_start", ""),
        "period_end": AUDIT_CONFIG.get("period_end", ""),
        "audit_date": AUDIT_CONFIG["audit_date"],
        "materiality_ratio": AUDIT_CONFIG["materiality_ratio"],
        "params": AUDIT_CONFIG["params"],
        "assurance": legacy_assurance(),
    })


@router.post("/run", summary="执行审计（重新运行全部审计程序）")
def audit_run(_user: User = Depends(require_permissions("audit:view"))):
    data = get_audit_result(force=True)
    return success(data, message="受限试算完成，非正式历史审计报告")


@router.get("/report", summary="审计报告全量数据（含审计程序执行情况与执行日志）")
def audit_report(run_id: str | None = Query(None), _user: User = Depends(require_permissions("audit:view"))):
    data = get_audit_result(run_id=run_id)
    return success({
        "report_meta": data["report_meta"],
        "scope": data["scope"],
        "data_stats": data["data_stats"],
        "clean_stats": data.get("clean_stats", {}),
        "summary": data["summary"],
        "data_quality_note": data["data_quality_note"],
        "procedures": data["procedures"],
        "run_log": data.get("run_log", {}),
    })


@router.get("/procedures", summary="审计程序执行情况")
def audit_procedures(run_id: str | None = Query(None), _user: User = Depends(require_permissions("audit:view"))):
    return success(get_audit_result(run_id=run_id)["procedures"])


@router.get("/findings", summary="审计发现清单（支持按风险等级、程序、关键字筛选）")
def audit_findings(
    risk_level: str = Query("", description="风险等级：高/中/低，留空为全部"),
    rule_code: str = Query("", description="审计程序编号，如 R03"),
    keyword: str = Query("", description="关键字，匹配标题/涉及对象/说明"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    run_id: str | None = Query(None),
    _user: User = Depends(require_permissions("audit:view")),
):
    data = get_audit_result(run_id=run_id)
    rows = data["findings"]

    if risk_level:
        rows = [r for r in rows if r["risk_level"] == risk_level]
    if rule_code:
        rows = [r for r in rows if r["rule_code"] == rule_code.upper()]
    if keyword:
        kw = keyword.strip()
        rows = [r for r in rows if kw in r["title"] or kw in r["subject"] or kw in r["description"]]

    total = len(rows)
    start = (page - 1) * page_size
    return success({
        "list": rows[start:start + page_size],
        "total": total,
        "summary": data["summary"],
        "report_meta": data["report_meta"],
    })


@router.get("/findings/{finding_id}", summary="审计发现详情（含证据链与审计建议）")
def audit_finding_detail(finding_id: str, run_id: str | None = Query(None),
                         _user: User = Depends(require_permissions("audit:view"))):
    data = get_audit_result(run_id=run_id)
    for r in data["findings"]:
        if r["finding_id"] == finding_id:
            proc = next((p for p in data["procedures"] if p["code"] == r["rule_code"]), None)
            return success({**r, "procedure": proc, "report_meta": data["report_meta"]})
    # 编号不存在时按业务错误返回，前端拦截器会给出提示
    from app.core.exceptions import BizException
    raise BizException(f"审计发现 {finding_id} 不存在")


@router.get("/workpaper", summary="审计工作底稿汇总（按审计程序归集）")
def audit_workpaper(run_id: str | None = Query(None), _user: User = Depends(require_permissions("audit:view"))):
    data = get_audit_result(run_id=run_id)
    groups = []
    for p in data["procedures"]:
        items = [f for f in data["findings"] if f["rule_code"] == p["code"]]
        groups.append({
            "code": p["code"],
            "name": p["name"],
            "objective": p["objective"],
            "rule": p["rule"],
            "risk_level": p["risk_level"],
            "note": p["note"],
            "count": None if p.get("status") == "数据不足" else len(items),
            "amount": (None if p.get("status") == "数据不足" else round(sum(float(f["amount"] or 0) for f in items), 2)),
            "status": p.get("status"),
            "findings": items,
        })
    return success({
        "report_meta": data["report_meta"],
        "scope": data["scope"],
        "summary": data["summary"],
        "groups": groups,
    })
