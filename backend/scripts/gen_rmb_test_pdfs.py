"""生成 PDF 测试票据（文本型与扫描件型各一张）。

用于验证 `invoice_ai.recognize_invoice()` 的 PDF 双路径：
1. `住宿费专票_文本型.pdf` —— 文字可选中的电子发票，走「文本层 → 文本模型」路径；
2. `住宿费专票_扫描件.pdf` —— 把图片压进 PDF（无文本层），走「渲染 → 视觉模型」路径。

样票内容与 `test_docs/rmb/住宿费专票_上海1650元.png` 一致，便于对比两条路径的识别结果。
仅使用项目已安装的 pypdf / pypdfium2 / Pillow，不引入额外依赖。

运行（在 backend 目录）：
    .venv/Scripts/python.exe scripts/gen_rmb_test_pdfs.py
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "test_docs", "rmb",
)


def build_text_pdf() -> bytes:
    """构造文本型 PDF：手写一个最小 PDF，文字是可提取的文本。

    直接手写 PDF 语法，避免引入 reportlab 依赖。中文用 PDF 的 CID 字体方案较复杂，
    这里采用「英文 + 数字」布局，把中文品名用拼音/英文替代 —— 目的是验证
    「文本能抽出并交给模型」这条链路，而不追求与样票逐字一致。
    实际业务中的电子发票 PDF 由开票系统生成，自带完整中文字体与文本层。
    """
    lines = [
        ("VAT SPECIAL INVOICE", 16),
        ("(Electronic Invoice)", 10),
        ("Invoice Code: 031002400111", 9),
        ("Invoice No: 26312000000098765432", 9),
        ("Issue Date: 2026-10-15", 9),
        ("Buyer: Xingchen Technology Co., Ltd.", 9),
        ("Buyer Tax ID: 91330000MA2XXXXX1Y", 9),
        ("Seller: Shanghai Jinjiang Inn Hotel Management Co., Ltd.", 9),
        ("Seller Tax ID: 91310115MA1H8XYZ2K", 9),
        ("", 9),
        ("Item                 Qty    Amount    TaxRate   Tax", 9),
        ("Accommodation       3      1556.60   6%        93.40", 9),
        ("", 9),
        ("Amount excl. tax: 1556.60", 9),
        ("Tax amount: 93.40", 9),
        ("Total (incl. tax): 1650.00", 11),
        ("Total in words: ONE THOUSAND SIX HUNDRED FIFTY", 9),
        ("", 9),
        ("Check-in: 2026-10-12  Check-out: 2026-10-15  Nights: 3", 9),
        ("City: Shanghai", 9),
        ("Billing remark: travel accommodation", 9),
    ]

    def esc(text: str) -> str:
        return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    content_parts = ["BT", "/F1 16 Tf", "50 760 Td", "18 TL"]
    first = True
    for text, size in lines:
        if not first:
            content_parts.append("T*")
        first = False
        if text:
            content_parts.append(f"/F1 {size} Tf")
            content_parts.append(f"({esc(text)}) Tj")
    content_parts.append("ET")
    stream = "\n".join(content_parts).encode("latin-1")

    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
    )
    objects.append(
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode())
        out.write(obj)
        out.write(b"\nendobj\n")
    xref_pos = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    )
    return out.getvalue()


def build_scanned_pdf(image_path: str) -> bytes:
    """把一张图片压进 PDF，得到「扫描件型」PDF（无文本层）。"""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise RuntimeError("缺少 pypdfium2，无法生成扫描件 PDF")

    from PIL import Image

    img = Image.open(image_path).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    jpeg_bytes = buf.getvalue()

    # pypdfium2 不能直接创建 PDF，这里手写一个含图片的 PDF
    w, h = img.size
    page_w, page_h = 595, 842
    scale = min(page_w / w, page_h / h) * 0.95
    draw_w, draw_h = w * scale, h * scale
    offset_x = (page_w - draw_w) / 2
    offset_y = (page_h - draw_h) / 2

    content = (
        f"q {draw_w:.2f} 0 0 {draw_h:.2f} {offset_x:.2f} {offset_y:.2f} cm /Im1 Do Q\n"
    ).encode()

    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /XObject << /Im1 5 0 R >> >> /Contents 4 0 R >>"
    )
    objects.append(
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"
    )
    objects.append(
        b"<< /Type /XObject /Subtype /Image /Width " + str(w).encode()
        + b" /Height " + str(h).encode()
        + b" /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length "
        + str(len(jpeg_bytes)).encode()
        + b" >>\nstream\n" + jpeg_bytes + b"\nendstream"
    )

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode())
        out.write(obj)
        out.write(b"\nendobj\n")
    xref_pos = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    )
    return out.getvalue()


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    text_pdf = build_text_pdf()
    text_path = os.path.join(OUT_DIR, "住宿费专票_文本型.pdf")
    with open(text_path, "wb") as f:
        f.write(text_pdf)
    print(f"已生成文本型 PDF: {text_path}（{len(text_pdf)} 字节）")

    png_path = os.path.join(OUT_DIR, "住宿费专票_上海1650元.png")
    if os.path.exists(png_path):
        scanned_pdf = build_scanned_pdf(png_path)
        scan_path = os.path.join(OUT_DIR, "住宿费专票_扫描件.pdf")
        with open(scan_path, "wb") as f:
            f.write(scanned_pdf)
        print(f"已生成扫描件 PDF: {scan_path}（{len(scanned_pdf)} 字节）")
    else:
        print(f"跳过扫描件 PDF：找不到源图 {png_path}")

    # 自检：验证两个 PDF 的文本层情况
    from app.services.invoice_ai import pdf_extract_text

    print("\n=== 文本层自检 ===")
    with open(text_path, "rb") as f:
        t = pdf_extract_text(f.read())
    print(f"文本型 PDF 抽出 {len(t)} 字：{t[:80]!r}")

    scan_path = os.path.join(OUT_DIR, "住宿费专票_扫描件.pdf")
    if os.path.exists(scan_path):
        with open(scan_path, "rb") as f:
            t2 = pdf_extract_text(f.read())
        print(f"扫描件 PDF 抽出 {len(t2)} 字（应接近 0）：{t2[:40]!r}")


if __name__ == "__main__":
    main()
