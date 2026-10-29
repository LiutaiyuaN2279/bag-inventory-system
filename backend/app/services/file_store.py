"""上传文件归档：把上传的原图落盘保存，供识别记录回看。

设计取舍：
- 只存**相对路径**（相对 `settings.UPLOAD_DIR`），不存绝对路径 —— 换机器/换目录后仍然有效。
- 文件名由「日期 + 记录 id + 内容摘要」生成，**不使用用户上传的原始文件名** ——
  避免路径穿越（`../../etc/passwd`）与同名覆盖，原始文件名另存于 `image_name` 供展示。
- 写入失败（磁盘满、目录只读等）不抛异常，只返回空路径：识别本身仍然可用，
  不会因为存不下照片就让整次识别失败；前端该行显示「未留存」。
"""
import hashlib
import os
from datetime import datetime

from app.core.config import settings

# 图片扩展名 → 响应用的 Content-Type
IMAGE_MIME = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "bmp": "image/bmp", "webp": "image/webp", "gif": "image/gif",
    "tif": "image/tiff", "tiff": "image/tiff",
}

_SUBDIR = "ocr"          # 归档子目录：data/uploads/ocr/
_MAX_SAVE_BYTES = 32 * 1024 * 1024   # 单文件落盘上限，防止异常大文件撑爆磁盘


def upload_root() -> str:
    """归档根目录的绝对路径（相对 backend 工作目录解析）。"""
    return os.path.abspath(settings.UPLOAD_DIR)


def normalize_ext(filename: str, content_type: str = "") -> str:
    """从文件名 / MIME 推断图片扩展名，统一小写且不带点；无法判断返回 'png'。"""
    name = (filename or "").strip()
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in IMAGE_MIME:
        return ext
    for key, mime in IMAGE_MIME.items():          # 退一步按 Content-Type 判断
        if content_type and content_type.split(";")[0].strip().lower() == mime:
            return key
    return "png"


def save_image(data: bytes, filename: str, content_type: str = "", ref: int | None = None) -> tuple[str, str]:
    """把图片写入归档目录。

    返回 `(relative_path, ext)`；写失败时返回 `("", ext)` —— 调用方据此落空路径。
    相对路径形如 `ocr/20261014_120001_8_3f2a1b.png`，可直接用于拼接 URL 与再次读盘。
    """
    ext = normalize_ext(filename, content_type)
    if not data or len(data) > _MAX_SAVE_BYTES:
        return "", ext
    digest = hashlib.md5(data).hexdigest()[:6]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rel = f"{_SUBDIR}/{stamp}_{ref if ref is not None else 0}_{digest}.{ext}"
    full = os.path.join(upload_root(), rel.replace("/", os.sep))
    try:
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fp:
            fp.write(data)
    except OSError:
        return "", ext
    return rel, ext


def resolve(rel_path: str) -> str:
    """把相对路径解析为绝对路径，并确认它没有跳出归档根目录。

    历史库/手工改库里可能存了 `../` 或绝对路径，这里统一拦掉，
    返回空串表示「不可读的原图」。
    """
    rel = (rel_path or "").strip().replace("\\", "/")
    if not rel or rel.startswith("/") or os.path.isabs(rel):
        return ""
    root = upload_root()
    full = os.path.abspath(os.path.join(root, rel.replace("/", os.sep)))
    # 必须仍在归档根目录内（commonpath 比 startswith 更严谨，避免 /root2 命中 /root）
    try:
        if os.path.commonpath([root, full]) != root:
            return ""
    except ValueError:            # 不同盘符
        return ""
    return full


def exists(rel_path: str) -> bool:
    """归档文件是否真的还在磁盘上。

    仅判断 `image_path` 非空是不够的：运维手工清理归档目录后，
    数据库里的路径仍然存在，前端会去请求一个 404 的图并显示破图。
    列表接口用本函数给出 `has_image`，前端据此显示「未留存」。
    """
    full = resolve(rel_path)
    return bool(full) and os.path.isfile(full)


def content_type_of(rel_path: str) -> str:
    """按扩展名给 Content-Type，未知一律当 jpeg。"""
    ext = (rel_path or "").rsplit(".", 1)[-1].lower()
    return IMAGE_MIME.get(ext, "image/jpeg")


def remove(rel_path: str) -> None:
    """删除归档文件（识别记录被删除时调用）。文件已不存在视为成功。"""
    full = resolve(rel_path)
    if not full:
        return
    try:
        os.remove(full)
    except OSError:
        pass
