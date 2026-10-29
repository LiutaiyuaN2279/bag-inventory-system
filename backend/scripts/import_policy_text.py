"""把 docs/policies 下的制度文本导入 rmb_policy 表（幂等）。

运行：进入 backend 目录后执行
    .venv/Scripts/python.exe scripts/import_policy_text.py

说明：AI 合规判读需要一个稳定的制度正文来源。本脚本优先读取
docs/policies/差旅与业务招待费报销管理制度.txt（由 docx 转换而来，含表格内容）；
若不存在则尝试用 python-docx 直接解析 docx。制度正文写入 rmb_policy.content_text，
提示词直接引用该文本，从而不依赖百炼文件上传，也更适合离线演示与审计留痕。
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.reimburse import RmbPolicy

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(BACKEND_DIR)
POLICY_DIR = os.path.join(PROJECT_DIR, "docs", "policies")

DOCX_NAME = "差旅与业务招待费报销管理制度.docx"
TXT_NAME = "差旅与业务招待费报销管理制度.txt"


def load_text():
    """读取制度正文纯文本。"""
    txt_path = os.path.join(POLICY_DIR, TXT_NAME)
    if os.path.exists(txt_path):
        with open(txt_path, encoding="utf-8") as f:
            return f.read().strip(), txt_path

    docx_path = os.path.join(POLICY_DIR, DOCX_NAME)
    if not os.path.exists(docx_path):
        raise FileNotFoundError(f"制度文件不存在：{docx_path}")

    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(docx_path)
    lines = []
    ti = 0
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            t = Paragraph(child, doc).text.strip()
            if t:
                lines.append(t)
        elif child.tag == qn("w:tbl"):
            ti += 1
            lines.append(f"\n【表 {ti}】")
            for row in Table(child, doc).rows:
                cells, seen = [], set()
                for c in row.cells:
                    if id(c._tc) in seen:
                        continue
                    seen.add(id(c._tc))
                    cells.append(c.text.strip().replace("\n", " / "))
                if any(cells):
                    lines.append(" | ".join(cells))
    return "\n".join(lines), docx_path


def run():
    text, src = load_text()
    docx_path = os.path.join(POLICY_DIR, DOCX_NAME)
    file_hash = ""
    if os.path.exists(docx_path):
        with open(docx_path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()

    db = SessionLocal()
    try:
        policy = db.query(RmbPolicy).filter(RmbPolicy.is_active == True).first()  # noqa: E712
        if not policy:
            policy = db.query(RmbPolicy).order_by(RmbPolicy.id.desc()).first()

        if policy:
            policy.content_text = text
            if file_hash:
                policy.file_hash = file_hash
            if not policy.file_path:
                policy.file_path = docx_path
            print(f"已更新制度正文：{policy.policy_name}（{len(text)} 字）")
        else:
            policy = RmbPolicy(
                policy_no="XC-CW-2025-008",
                policy_name="差旅与业务招待费报销管理制度",
                effective_date="2025-01-01",
                file_path=docx_path,
                original_filename=DOCX_NAME,
                file_hash=file_hash,
                content_text=text,
                is_active=True,
                uploaded_by="system",
                remark="初始化导入",
            )
            db.add(policy)
            print(f"已新增制度：{policy.policy_name}（{len(text)} 字）")

        db.commit()
        print(f"正文来源：{src}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
