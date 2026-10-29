"""制度与参数管理接口：制度文件版本 / 生效版本 / 解析测试 / 检查规则 / 参数 / 城市等级 / 节假日。

本模块对应「变更管理」控制点：制度正文、检查规则、阈值参数三者必须在同一处维护并留痕，
否则 AI 判读依据与程序交叉校验的口径会不一致。因此：
- 全部接口要求 `reimburse:policy:manage` 权限；
- 所有写操作都在业务事务提交之后写 operation_logs，detail 记录修改前后的值；
- 同一时间只允许一个制度版本生效（置为生效时其它版本自动取消）。

制度文件上传后：原件归档到 <项目根>/docs/policies/，正文解析后写入 content_text，
判读提示词直接引用该正文（不依赖百炼文件上传，离线演示与审计留痕更可靠）。
docx 解析优先用 python-docx（若环境已安装），否则用标准库 zipfile 读 word/document.xml；
pdf 用标准库尝试抽取文本流，失败时提示改为上传 docx 或手工粘贴正文。
"""
import hashlib
import os
import re
import zipfile
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permissions
from app.api.v1.reimburse._common import (
    active_policy,
    is_truthy,
    parse_day_optional,
    parse_float,
    request_path,
    safe_filename,
    sys_params,
    write_log,
)
from app.core.database import get_db
from app.core.exceptions import BizException
from app.models.rbac import User
from app.models.reimburse import (
    RmbCityLevel,
    RmbHoliday,
    RmbPolicy,
    RmbPolicyRule,
    RmbSysParam,
)
from app.schemas.reimburse import (
    CityLevelIn,
    CityLevelUpdate,
    HolidayIn,
    HolidayUpdate,
    PolicyRuleUpdate,
    SysParamUpdate,
)
from app.utils.response import success

router = APIRouter(prefix="/rmb-policy", tags=["制度管理"])

POLICY_DIR_NAME = "policies"
_MAX_POLICY_BYTES = 10 * 1024 * 1024
_POLICY_EXTS = ("docx", "pdf", "txt", "md")
_CONTENT_PREVIEW_LEN = 300
_DOCX_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


# ==================== 内部辅助 ====================
def policy_dir() -> str:
    """制度文件归档目录：<项目根>/docs/policies/。

    本文件位于 backend/app/api/v1/reimburse/policy.py，向上 5 层是 backend，
    再上一层即项目根；与 scripts/import_policy_text.py 导入的制度文件放在同一目录，
    便于「历史版本」与初始化版本统一管理。
    """
    here = os.path.abspath(__file__)
    backend_dir = here
    for _ in range(5):
        backend_dir = os.path.dirname(backend_dir)
    project_dir = os.path.dirname(backend_dir)
    return os.path.join(project_dir, "docs", POLICY_DIR_NAME)


def _policy_row(policy: RmbPolicy, with_content: bool = False) -> dict:
    content = policy.content_text or ""
    data = {
        "id": policy.id,
        "policy_no": policy.policy_no or "",
        "policy_name": policy.policy_name or "",
        "effective_date": policy.effective_date or "",
        "file_path": policy.file_path or "",
        "original_filename": policy.original_filename or "",
        "file_hash": policy.file_hash or "",
        "dashscope_file_id": policy.dashscope_file_id or "",
        "is_active": bool(policy.is_active),
        "uploaded_by": policy.uploaded_by or "",
        "uploaded_at": str(policy.uploaded_at)[:19] if policy.uploaded_at else "",
        "remark": policy.remark or "",
        "content_length": len(content),
        "content_preview": content[:_CONTENT_PREVIEW_LEN].replace("\n", " "),
    }
    if with_content:
        data["content_text"] = content
    return data


def _rule_row(rule: RmbPolicyRule) -> dict:
    return {
        "id": rule.id,
        "rule_code": rule.rule_code or "",
        "check_item": rule.check_item or "",
        "judge_rule": rule.judge_rule or "",
        "clause_no": rule.clause_no or "",
        "risk_level": rule.risk_level or "中",
        "check_mode": rule.check_mode or "AI+程序",
        "is_active": bool(rule.is_active),
        "sort_no": rule.sort_no or 0,
        "updated_by": rule.updated_by or "",
        "updated_at": str(rule.updated_at)[:19] if rule.updated_at else "",
    }


def _city_row(city: RmbCityLevel) -> dict:
    return {
        "id": city.id, "city_name": city.city_name or "", "city_level": city.city_level or "其他城市",
        "lodging_limit": city.lodging_limit or 0,
    }


def _holiday_row(holiday: RmbHoliday) -> dict:
    return {
        "id": holiday.holiday_date, "holiday_date": holiday.holiday_date or "",
        "holiday_name": holiday.holiday_name or "", "day_type": holiday.day_type or "法定节假日",
    }


def _extract_docx_text(data: bytes) -> str:
    """解析 docx 正文：优先 python-docx（保留表格），否则用 zipfile 读 XML。"""
    try:
        from docx import Document  # type: ignore import-not-found
    except ImportError:
        Document = None
    if Document is not None:
        import io

        document = Document(io.BytesIO(data))
        lines = [p.text.strip() for p in document.paragraphs if p.text.strip()]
        for index, table in enumerate(document.tables, start=1):
            lines.append(f"\n【表 {index}】")
            for row in table.rows:
                cells, seen = [], set()
                for cell in row.cells:
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    cells.append(cell.text.strip().replace("\n", " / "))
                if any(cells):
                    lines.append(" | ".join(cells))
        return "\n".join(lines).strip()

    # 兜底：直接读 word/document.xml，段落按 <w:p> 切分，文本取自 <w:t>
    import io

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    paragraphs = re.split(r"</w:p>", xml)
    lines = []
    for paragraph in paragraphs:
        texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", paragraph, flags=re.S)
        line = re.sub(r"<[^>]+>", "", "".join(texts)).strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


def _extract_pdf_text(data: bytes) -> str:
    """解析 pdf 正文：标准库无 pdf 解析能力，只做最基本的文本流抽取。

    抽取失败返回空串，由调用方提示改用 docx 或在页面手工维护正文，
    避免为了一个可选功能引入新的第三方依赖。
    """
    try:
        raw = data.decode("latin-1", errors="ignore")
    except Exception:  # noqa: BLE001 - 解码失败按无法解析处理
        return ""
    chunks = re.findall(r"\((?:[^()\\]|\\.)*\)", raw)
    text = "".join(chunk[1:-1] for chunk in chunks)
    text = text.replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\")
    # 非 ASCII 文本在无压缩流里通常不可读，此时视为解析失败
    if not text.strip():
        return ""
    readable = sum(1 for ch in text if ch.isprintable() or ch in "\n\r\t")
    if readable / max(len(text), 1) < 0.8:
        return ""
    return text.strip()


def _parse_policy_file(data: bytes, filename: str) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if ext == "docx":
        try:
            return _extract_docx_text(data)
        except Exception as exc:  # noqa: BLE001 - 解析失败统一转中文提示
            raise BizException(f"制度文件解析失败（{exc}），请确认是有效的 docx 文件")
    if ext == "pdf":
        text = _extract_pdf_text(data)
        if not text:
            raise BizException("PDF 正文自动解析失败，请改为上传 docx，或上传后在正文中手工维护制度正文")
        return text
    if ext in ("txt", "md"):
        for encoding in ("utf-8", "gbk", "utf-16"):
            try:
                return data.decode(encoding).strip()
            except UnicodeDecodeError:
                continue
        raise BizException("制度文本文件编码无法识别，请另存为 UTF-8 后重新上传")
    raise BizException("制度文件仅支持 docx、pdf、txt 格式")


def _deactivate_others(db: Session, keep_id: int | None) -> None:
    """把除 keep_id 以外的制度版本全部置为不生效（同一时间只能一个生效）。"""
    query = db.query(RmbPolicy)
    if keep_id:
        query = query.filter(RmbPolicy.id != keep_id)
    for policy in query.filter(RmbPolicy.is_active == True).all():  # noqa: E712
        policy.is_active = False


# ==================== 一、制度文件 ====================
@router.get("", summary="制度列表")
def list_policies(
    db: Session = Depends(get_db),
    _=Depends(require_permissions("reimburse:policy:manage")),
):
    """制度版本列表（倒序）+ 当前生效版本。"""
    rows = db.query(RmbPolicy).order_by(RmbPolicy.id.desc()).all()
    active = next((row for row in rows if row.is_active), None)
    return success({
        "active": _policy_row(active, with_content=True) if active else None,
        "list": [_policy_row(row) for row in rows],
    })


@router.post("/upload", summary="上传制度文件")
async def upload_policy(
    request: Request,
    file: UploadFile = File(...),
    policy_no: str | None = Form(None),
    policy_name: str | None = Form(None),
    effective_date: str | None = Form(None),
    set_active: str | None = Form("true"),
    remark: str | None = Form(None),
    content_text: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:policy:manage")),
):
    """上传制度文件：归档原件、解析正文、新增版本；可选设为当前生效。

    正文解析优先级：手工提交的 content_text > 文件自动解析。
    """
    content = await file.read()
    if not content:
        raise BizException("上传的制度文件为空，请重新上传")
    if len(content) > _MAX_POLICY_BYTES:
        raise BizException(f"制度文件不能超过 {_MAX_POLICY_BYTES // (1024 * 1024)}MB")
    filename = safe_filename(file.filename or "")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _POLICY_EXTS:
        raise BizException("制度文件仅支持 docx、pdf、txt 格式")

    digest = hashlib.sha256(content).hexdigest()
    existed = db.query(RmbPolicy).filter(RmbPolicy.file_hash == digest).first()
    if existed:
        raise BizException(f"该制度文件已上传过（{existed.policy_name or existed.original_filename}），"
                           "请勿重复上传")

    parsed_text = (content_text or "").strip() or _parse_policy_file(content, filename)
    if not parsed_text:
        raise BizException("未能解析出制度正文，请在提交时手工填写制度正文")

    directory = policy_dir()
    os.makedirs(directory, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_name = f"{stamp}_{digest[:8]}.{ext}"
    target_path = os.path.join(directory, target_name)
    try:
        with open(target_path, "wb") as fp:
            fp.write(content)
    except OSError as exc:
        raise BizException(f"制度文件保存失败：{exc}")

    active_flag = is_truthy(set_active) if set_active is not None else True
    try:
        if active_flag:
            _deactivate_others(db, keep_id=None)
        policy = RmbPolicy(
            policy_no=(policy_no or "").strip()[:64],
            policy_name=(policy_name or filename.rsplit(".", 1)[0])[:128],
            effective_date=parse_day_optional(effective_date, "生效日期"),
            file_path=target_path,
            original_filename=filename,
            file_hash=digest,
            content_text=parsed_text,
            is_active=active_flag,
            uploaded_by=user.username,
            remark=(remark or "").strip()[:255],
        )
        db.add(policy)
        db.commit()
    except Exception:
        db.rollback()
        raise

    write_log(
        db, user, "上传制度", request_path("/api/v1/rmb-policy/upload"),
        detail=f"{policy.policy_name}；{filename}；{len(parsed_text)}字"
               f"{'；已设为生效' if active_flag else ''}",
        request=request,
    )
    return success(_policy_row(policy), message="制度文件已上传"
                   + ("并设为当前生效" if active_flag else ""))


@router.post("/{policy_id}/activate", summary="设为当前生效制度")
def activate_policy(
    policy_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:policy:manage")),
):
    """把指定版本设为当前生效（其它版本自动取消生效）。"""
    policy = db.get(RmbPolicy, policy_id)
    if not policy:
        raise BizException("制度版本不存在")
    try:
        _deactivate_others(db, keep_id=policy.id)
        policy.is_active = True
        db.commit()
    except Exception:
        db.rollback()
        raise
    write_log(
        db, user, "设置生效制度", request_path(f"/api/v1/rmb-policy/{policy.id}/activate"),
        detail=f"{policy.policy_name or policy.original_filename}（{policy.policy_no or '无编号'}）",
        request=request,
    )
    return success({"id": policy.id}, message="已设为当前生效制度")


@router.post("/parse-test", summary="制度解析测试")
def parse_test(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:policy:manage")),
):
    """对当前生效制度调大模型解析章节要点，用于确认大模型已正确读取制度。

    大模型调用失败不影响正文本身，返回错误提示与正文摘要供人工核对。
    """
    policy = active_policy(db)
    if policy is None:
        raise BizException("当前没有生效的制度版本，请先上传并设为生效")
    content = (policy.content_text or "").strip()
    if not content:
        raise BizException("当前生效制度没有正文，请重新上传制度文件或手工维护正文")

    prompt = (
        "下面是本公司的《" + (policy.policy_name or "费用报销管理制度") + "》全文。"
        "请列出该制度的章节结构、各条款要点，以及其中出现的全部金额标准、日期要求与审批标准。"
        "要求：分条列出，金额与数字必须与原文一致，不要编造制度中不存在的内容。\n\n"
        "【制度正文】\n" + content
    )

    model = ""
    elapsed = 0.0
    result = ""
    source = "大模型解析"
    try:
        from app.services import llm_client_new

        begin = datetime.now()
        result = llm_client_new.chat_text(prompt, model=llm_client_new.RULE_MODEL
                                          if hasattr(llm_client_new, "RULE_MODEL") else "qwen-plus")
        elapsed = round((datetime.now() - begin).total_seconds(), 2)
        model = "qwen-plus"
    except ImportError:
        source = "本地正文摘要（AI 服务未就绪）"
        result = content
    except Exception as exc:  # noqa: BLE001 - 大模型失败时降级返回正文
        source = "本地正文摘要（AI 解析失败）"
        result = f"大模型解析失败：{exc}\n\n以下是制度正文原文，请人工核对：\n{content}"

    write_log(
        db, user, "制度解析测试", request_path("/api/v1/rmb-policy/parse-test"),
        detail=f"{policy.policy_name}；{model or '本地'}；{elapsed:.1f}s",
        request=request,
    )
    return success({
        "policy_id": policy.id,
        "policy_name": policy.policy_name or "",
        "result": result,
        "model": model,
        "elapsed": elapsed,
        "source": source,
        "content_length": len(content),
    }, message="解析完成")


# ==================== 二、检查规则 ====================
@router.get("/rules", summary="检查规则列表")
def list_rules(
    db: Session = Depends(get_db),
    _=Depends(require_permissions("reimburse:policy:manage")),
):
    rows = db.query(RmbPolicyRule).order_by(RmbPolicyRule.sort_no, RmbPolicyRule.id).all()
    return success([_rule_row(row) for row in rows])


@router.get("/rules/all", summary="检查规则列表（判读服务读取用，权限放宽）")
def list_rules_readonly(
    db: Session = Depends(get_db),
    _=Depends(require_permissions("reimburse:bill:list")),
):
    """给前端判读页面展示规则清单用的只读接口（不需要制度管理权限）。"""
    rows = db.query(RmbPolicyRule).order_by(RmbPolicyRule.sort_no, RmbPolicyRule.id).all()
    return success([_rule_row(row) for row in rows])


@router.put("/rules/{rule_id}", summary="修改检查规则")
def update_rule(
    rule_id: int,
    data: PolicyRuleUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:policy:manage")),
):
    """修改检查规则，日志记录修改前后的值（变更管理留痕）。"""
    rule = db.get(RmbPolicyRule, rule_id)
    if not rule:
        raise BizException("检查规则不存在")
    fields = data.model_dump(exclude_unset=True)
    if not fields:
        return success(message="未做任何修改")
    if "risk_level" in fields and fields["risk_level"] not in ("高", "中", "低"):
        raise BizException("风险等级只能为 高 / 中 / 低")
    if "check_mode" in fields and fields["check_mode"] not in ("AI", "AI+程序"):
        raise BizException("检查方式只能为 AI / AI+程序")

    changes = []
    for key, value in fields.items():
        if not hasattr(rule, key):
            continue
        before = getattr(rule, key)
        if isinstance(before, str):
            value = (value or "").strip()
        if str(before) == str(value):
            continue
        changes.append(f"{key}:{before}→{value}")
        setattr(rule, key, value)
    if not changes:
        return success(message="未做任何修改")
    rule.updated_by = user.username
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    write_log(
        db, user, "修改检查规则", request_path(f"/api/v1/rmb-policy/rules/{rule.id}"),
        detail=f"{rule.rule_code}；{'；'.join(changes)[:40]}",
        method="PUT", request=request,
    )
    return success(_rule_row(rule), message="检查规则已更新")


# ==================== 三、参数与基础数据 ====================
@router.get("/params", summary="系统参数 + 城市等级 + 节假日")
def get_params(
    db: Session = Depends(get_db),
    _=Depends(require_permissions("reimburse:policy:manage")),
):
    rules = db.query(RmbPolicyRule).order_by(RmbPolicyRule.sort_no, RmbPolicyRule.id).all()
    return success({
        "params": sys_params(db),
        "param_items": [
            {"param_key": row.param_key, "param_value": row.param_value or "",
             "remark": row.remark or "",
             "updated_at": str(row.updated_at)[:19] if row.updated_at else ""}
            for row in db.query(RmbSysParam).order_by(RmbSysParam.param_key).all()
        ],
        "city_levels": [_city_row(row) for row in db.query(RmbCityLevel).order_by(RmbCityLevel.id).all()],
        "holidays": [_holiday_row(row) for row in
                      db.query(RmbHoliday).order_by(RmbHoliday.holiday_date).all()],
        "rules": [_rule_row(row) for row in rules],
        "active_policy": _policy_row(active_policy(db)) if active_policy(db) else None,
    })


@router.put("/params", summary="修改系统参数")
def update_params(
    data: SysParamUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:policy:manage")),
):
    """修改系统参数：支持 {key,value}、{param_key,param_value} 或 {items:[{key,value}]} 三种写法。"""
    items: list[dict] = []
    if data.items:
        items = [dict(item) for item in data.items]
    else:
        key = (data.key or data.param_key or "").strip()
        if not key:
            raise BizException("请指定要修改的参数键")
        items = [{"key": key, "value": data.value if data.value is not None else data.param_value,
                  "remark": data.remark}]

    changes = []
    try:
        for item in items:
            key = str(item.get("key") or item.get("param_key") or "").strip()
            if not key:
                raise BizException("参数键不能为空")
            param = db.query(RmbSysParam).filter(RmbSysParam.param_key == key).first()
            if not param:
                raise BizException(f"系统参数「{key}」不存在")
            value = item.get("value", item.get("param_value"))
            if value is None:
                raise BizException(f"参数「{key}」的值不能为空")
            value = str(value).strip()
            if key.endswith("_amount") or key.endswith("_limit") or key.endswith("_window"):
                if parse_float(value, f"参数「{key}」", minimum=0) is None:
                    raise BizException(f"参数「{key}」应为数字")
            if value == (param.param_value or ""):
                continue
            changes.append(f"{key}:{param.param_value}→{value}")
            param.param_value = value
            if item.get("remark") is not None:
                param.remark = str(item.get("remark"))[:255]
        if changes:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise

    if not changes:
        return success(message="未做任何修改")
    write_log(
        db, user, "修改系统参数", request_path("/api/v1/rmb-policy/params"),
        detail="；".join(changes)[:44], method="PUT", request=request,
    )
    return success({"params": sys_params(db), "changed": changes}, message="系统参数已更新")


# ---------------- 城市等级 ----------------
@router.get("/city-levels", summary="城市等级列表")
def list_city_levels(
    db: Session = Depends(get_db),
    _=Depends(require_permissions("reimburse:policy:manage")),
):
    return success([_city_row(row) for row in db.query(RmbCityLevel).order_by(RmbCityLevel.id).all()])


@router.post("/city-levels", summary="新增城市等级")
def create_city_level(
    data: CityLevelIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:policy:manage")),
):
    name = (data.city_name or "").strip()
    if not name:
        raise BizException("请填写城市名称")
    if db.query(RmbCityLevel).filter(RmbCityLevel.city_name == name).first():
        raise BizException(f"城市「{name}」已存在")
    limit = parse_float(data.lodging_limit, "住宿标准上限", minimum=0)
    try:
        city = RmbCityLevel(city_name=name, city_level=(data.city_level or "其他城市").strip() or "其他城市",
                            lodging_limit=limit if limit is not None else 400)
        db.add(city)
        db.commit()
    except Exception:
        db.rollback()
        raise
    write_log(db, user, "新增城市等级", request_path("/api/v1/rmb-policy/city-levels"),
              detail=f"{city.city_name}；{city.city_level}；{city.lodging_limit:.0f}元/晚",
              request=request)
    return success(_city_row(city), message="城市等级已新增")


@router.put("/city-levels/{city_id}", summary="修改城市等级")
def update_city_level(
    city_id: int,
    data: CityLevelUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:policy:manage")),
):
    city = db.get(RmbCityLevel, city_id)
    if not city:
        raise BizException("城市等级记录不存在")
    fields = data.model_dump(exclude_unset=True)
    changes = []
    try:
        for key, value in fields.items():
            if key == "city_name":
                value = (value or "").strip()
                if not value:
                    raise BizException("城市名称不能为空")
                if value != city.city_name and db.query(RmbCityLevel).filter(
                        RmbCityLevel.city_name == value).first():
                    raise BizException(f"城市「{value}」已存在")
                changes.append(f"城市:{city.city_name}→{value}")
            elif key == "lodging_limit":
                value = parse_float(value, "住宿标准上限", minimum=0)
                if value is None:
                    raise BizException("请填写住宿标准上限")
                changes.append(f"标准:{city.lodging_limit}→{value}")
            elif key == "city_level":
                value = (value or "").strip() or city.city_level
                changes.append(f"等级:{city.city_level}→{value}")
            setattr(city, key, value)
        db.commit()
    except Exception:
        db.rollback()
        raise
    if not changes:
        return success(message="未做任何修改")
    write_log(db, user, "修改城市等级", request_path(f"/api/v1/rmb-policy/city-levels/{city.id}"),
              detail=f"{city.city_name}；{'；'.join(changes)[:40]}", method="PUT", request=request)
    return success(_city_row(city), message="城市等级已更新")


@router.delete("/city-levels/{city_id}", summary="删除城市等级")
def delete_city_level(
    city_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:policy:manage")),
):
    city = db.get(RmbCityLevel, city_id)
    if not city:
        raise BizException("城市等级记录不存在")
    if city.city_name == "其他城市":
        raise BizException("兜底记录「其他城市」不允许删除（判读时查不到城市按它取标准）")
    name = city.city_name
    try:
        db.delete(city)
        db.commit()
    except Exception:
        db.rollback()
        raise
    write_log(db, user, "删除城市等级", request_path(f"/api/v1/rmb-policy/city-levels/{city_id}"),
              detail=name, method="DELETE", request=request)
    return success(message="城市等级已删除")


# ---------------- 节假日 ----------------
@router.get("/holidays", summary="节假日列表")
def list_holidays(
    year: str | None = Query(None, description="按年份筛选，如 2026"),
    db: Session = Depends(get_db),
    _=Depends(require_permissions("reimburse:policy:manage")),
):
    query = db.query(RmbHoliday)
    if year:
        query = query.filter(RmbHoliday.holiday_date.like(f"{year.strip()}-%"))
    rows = query.order_by(RmbHoliday.holiday_date).all()
    return success([_holiday_row(row) for row in rows])


@router.post("/holidays", summary="新增节假日")
def create_holiday(
    data: HolidayIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:policy:manage")),
):
    day = parse_day_optional(data.holiday_date, "日期")
    if not day:
        raise BizException("请填写日期")
    if db.query(RmbHoliday).filter(RmbHoliday.holiday_date == day).first():
        raise BizException(f"日期 {day} 已在节假日表中")
    day_type = (data.day_type or "法定节假日").strip() or "法定节假日"
    if day_type not in ("法定节假日", "调休上班日"):
        raise BizException("日期类型只能为 法定节假日 / 调休上班日")
    try:
        holiday = RmbHoliday(holiday_date=day, holiday_name=(data.holiday_name or "").strip()[:64],
                             day_type=day_type)
        db.add(holiday)
        db.commit()
    except Exception:
        db.rollback()
        raise
    write_log(db, user, "新增节假日", request_path("/api/v1/rmb-policy/holidays"),
              detail=f"{day}；{holiday.holiday_name}；{day_type}", request=request)
    return success(_holiday_row(holiday), message="节假日已新增")


@router.put("/holidays/{holiday_date}", summary="修改节假日")
def update_holiday(
    holiday_date: str,
    data: HolidayUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:policy:manage")),
):
    day = parse_day_optional(holiday_date, "日期") or holiday_date
    holiday = db.query(RmbHoliday).filter(RmbHoliday.holiday_date == day).first()
    if not holiday:
        raise BizException("节假日记录不存在")
    fields = data.model_dump(exclude_unset=True)
    if "day_type" in fields and fields["day_type"] not in ("法定节假日", "调休上班日"):
        raise BizException("日期类型只能为 法定节假日 / 调休上班日")
    changes = []
    for key, value in fields.items():
        before = getattr(holiday, key)
        value = (value or "").strip()
        if str(before or "") == value:
            continue
        changes.append(f"{key}:{before}→{value}")
        setattr(holiday, key, value)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    if not changes:
        return success(message="未做任何修改")
    write_log(db, user, "修改节假日", request_path(f"/api/v1/rmb-policy/holidays/{day}"),
              detail=f"{day}；{'；'.join(changes)[:40]}", method="PUT", request=request)
    return success(_holiday_row(holiday), message="节假日已更新")


@router.delete("/holidays/{holiday_date}", summary="删除节假日")
def delete_holiday(
    holiday_date: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("reimburse:policy:manage")),
):
    day = parse_day_optional(holiday_date, "日期") or holiday_date
    holiday = db.query(RmbHoliday).filter(RmbHoliday.holiday_date == day).first()
    if not holiday:
        raise BizException("节假日记录不存在")
    try:
        db.delete(holiday)
        db.commit()
    except Exception:
        db.rollback()
        raise
    write_log(db, user, "删除节假日", request_path(f"/api/v1/rmb-policy/holidays/{day}"),
              detail=f"{day}；{holiday.holiday_name}；{holiday.day_type}",
              method="DELETE", request=request)
    return success(message="节假日已删除")
