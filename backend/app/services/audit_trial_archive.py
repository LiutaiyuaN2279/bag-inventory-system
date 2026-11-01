"""B002-C07: append-only local TRIAL snapshots, never formal publication.

No business database writes. Publication/revision authorisation remains unresolved.
Stored query results are current snapshot inputs, not reconstructed historical facts.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import uuid


class TrialArchiveError(ValueError):
    pass


def canonical_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


class TrialArchive:
    SCHEMA = "b002-trial-archive-v1"
    KINDS = {"original_trial", "revision_candidate", "followup_trial"}
    REQUIRED_BASIS = {"period_start", "period_end", "business_cutoff", "snapshot_at",
                      "business_data", "rule_version", "rules_source", "rule_config",
                      "calendar_versions", "evidence_versions"}

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _path(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise TrialArchiveError("试算运行编号无效")
        p = self.root / (run_id + ".json")
        if p.resolve().parent != self.root or p.is_symlink():
            raise TrialArchiveError("试算归档路径不安全")
        return p

    def read(self, run_id: str) -> dict:
        try:
            obj = json.loads(self._path(run_id).read_bytes())
        except (OSError, ValueError) as exc:
            raise TrialArchiveError("试算快照不存在或不可读取，不使用当前数据替代") from exc
        try:
            payload = obj["payload"]
            if (obj["schema"] != self.SCHEMA or payload["run_id"] != run_id
                    or payload["kind"] not in self.KINDS
                    or obj["sha256"] != hashlib.sha256(canonical_bytes(payload)).hexdigest()
                    or payload["report"]["report_meta"]["run_id"] != run_id
                    or payload["report"]["report_meta"]["formal_report"] is not False
                    or not self.REQUIRED_BASIS <= payload["basis"].keys()):
                raise ValueError("invalid_envelope")
        except (KeyError, TypeError, ValueError) as exc:
            raise TrialArchiveError("试算快照完整性异常，不使用当前数据重算冒充原版") from exc
        return payload

    def save(self, report: dict, basis: dict, *, kind: str = "original_trial",
             parent_run_id: str | None = None, run_id: str | None = None) -> dict:
        if kind not in self.KINDS or not self.REQUIRED_BASIS <= basis.keys():
            raise TrialArchiveError("试算类型或重现依据不完整")
        run_id = run_id or uuid.uuid4().hex
        destination = self._path(run_id)
        parent = None
        if kind == "original_trial":
            if parent_run_id is not None:
                raise TrialArchiveError("原始试算不能冒用前版关系")
        else:
            if not parent_run_id:
                raise TrialArchiveError("修订候选或期后追踪必须关联原记录")
            parent = self.read(parent_run_id)
            if kind == "revision_candidate" and any(basis[k] != parent["basis"][k]
                    for k in ("period_start", "period_end", "business_cutoff")):
                raise TrialArchiveError("修订候选不能改变原期间和业务截止")
        # Copy at the boundary: later mutations of callers cannot change the snapshot.
        payload = json.loads(canonical_bytes({"run_id": run_id, "kind": kind,
            "parent_run_id": parent_run_id,
            "original_run_id": (parent["original_run_id"] if parent else run_id),
            "report": report, "basis": basis}))
        meta = payload["report"].setdefault("report_meta", {})
        meta.update({"run_id": run_id, "snapshot_kind": kind, "formal_report": False,
                     "parent_run_id": parent_run_id, "original_run_id": payload["original_run_id"],
                     "historical_traceability": "受限", "publication_status": "未发布的受限试算"})
        envelope = {"schema": self.SCHEMA, "sha256": hashlib.sha256(canonical_bytes(payload)).hexdigest(),
                    "payload": payload}
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / (".pending-" + uuid.uuid4().hex)
        try:
            with temporary.open("xb") as out:
                out.write(canonical_bytes(envelope))
                out.flush()
                os.fsync(out.fileno())
            # A hard-link publishes a complete file without ever replacing another ID.
            os.link(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()
        return payload
