"""生成差旅报销测试用的票据样张（图片）。

生成 4 张教学样票，内容与《信息系统审计 实验一》表 8-1 的测试场景 T03/T05/T13 对应：
1. 住宿费增值税专用发票（上海，3 晚 1650 元，可抵扣）→ 用于 T03 合规样例、T17 AI 制证
2. 餐饮服务发票（2026-10-03 国庆，2400 元）→ 用于 T05 招待多项违规
3. 铁路电子客票（杭州→上海）→ 用于 T02 票据识别、T08 审批越权
4. 收据（非发票）→ 用于 T10 缺发票、T07 非发票单据识别

样票为虚构数据，仅用于教学演示。
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test_docs", "rmb")
os.makedirs(OUT_DIR, exist_ok=True)

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
]


def get_font(size, bold=False):
    """取中文字体，取不到就退回 PIL 默认字体（英文可显示，中文会乱码）。"""
    candidates = ([r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\simhei.ttf"] if bold
                  else FONT_CANDIDATES)
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


W, H = 1100, 720


def new_canvas():
    img = Image.new("RGB", (W, H), "#FFFFFF")
    return img, ImageDraw.Draw(img)


def draw_header(d, title, subtitle="", color="#1a5490"):
    f_title = get_font(30, bold=True)
    f_sub = get_font(16)
    d.text((W // 2, 44), title, font=f_title, fill=color, anchor="mm")
    if subtitle:
        d.text((W // 2, 84), subtitle, font=f_sub, fill="#666666", anchor="mm")
    d.line([(60, 110), (W - 60, 110)], fill=color, width=3)


def draw_rows(d, rows, start_y=150, label_x=80, value_x=330, gap=38, size=17):
    f = get_font(size)
    f_bold = get_font(size, bold=True)
    y = start_y
    for label, value in rows:
        d.text((label_x, y), label, font=f, fill="#444444")
        d.text((value_x, y), str(value), font=f_bold, fill="#111111")
        y += gap
    return y


def draw_table(d, headers, rows, top, col_x, row_h=38, size=15):
    """画一个简单表格。"""
    f = get_font(size)
    f_b = get_font(size, bold=True)
    left, right = col_x[0] - 12, col_x[-1] + 250
    # 表头
    d.rectangle([left, top, right, top + row_h], fill="#eef4fa", outline="#9db9d4")
    for i, h in enumerate(headers):
        d.text((col_x[i], top + row_h // 2), h, font=f_b, fill="#1a5490", anchor="lm")
    y = top + row_h
    for r in rows:
        d.rectangle([left, y, right, y + row_h], outline="#d5e0ea")
        for i, c in enumerate(r):
            d.text((col_x[i], y + row_h // 2), str(c), font=f, fill="#222222", anchor="lm")
        y += row_h
    return y


def invoice_1_lodging():
    """住宿费增值税专用发票：上海 3 晚 1650 元（不含税 1556.60 + 税额 93.40）。"""
    img, d = new_canvas()
    draw_header(d, "上海增值税专用发票", "电子发票（增值税专用发票）")
    rows = [
        ("发票代码", "031002400111"),
        ("发票号码", "26312000000098765432"),
        ("开票日期", "2026年10月15日"),
        ("购买方名称", "星辰科技股份有限公司"),
        ("纳税人识别号", "91330000MA2XXXXX1Y"),
        ("销售方名称", "上海锦江之星酒店管理有限公司"),
        ("纳税人识别号", "91310115MA1H8XYZ2K"),
    ]
    y = draw_rows(d, rows, start_y=140, gap=34, size=16)
    y += 14
    d.text((80, y), "货物或应税劳务、服务名称", font=get_font(15, bold=True), fill="#1a5490")
    y = draw_table(
        d,
        ["项目名称", "数量", "金额", "税率", "税额"],
        [["*住宿服务*住宿费", "3晚", "1556.60", "6%", "93.40"]],
        top=y + 30, col_x=[100, 480, 620, 760, 880],
    )
    y += 24
    f = get_font(17)
    f_b = get_font(19, bold=True)
    d.text((480, y), "合计金额（不含税）", font=f, fill="#444444")
    d.text((660, y), "¥1556.60", font=f_b, fill="#111111")
    d.text((480, y + 38), "税额", font=f, fill="#444444")
    d.text((660, y + 38), "¥93.40", font=f_b, fill="#111111")
    d.line([(80, y + 82), (W - 80, y + 82)], fill="#1a5490", width=2)
    d.text((80, y + 96), "价税合计（大写）", font=f, fill="#444444")
    d.text((330, y + 96), "壹仟陆佰伍拾圆整", font=f_b, fill="#c00000")
    d.text((700, y + 96), "（小写）¥1650.00", font=f_b, fill="#c00000")
    d.text((80, H - 60), "入住日期：2026-10-12    离店日期：2026-10-15    住宿晚数：3",
           font=get_font(15), fill="#444444")
    d.text((W - 320, H - 34), "收款人：李娜   开票人：王芳", font=get_font(14), fill="#666666")
    return img


def invoice_2_dining():
    """餐饮服务发票：2026-10-03 国庆期间，2400 元（用于 T05 违规场景）。"""
    img, d = new_canvas()
    draw_header(d, "浙江增值税电子普通发票", "电子发票（普通发票）")
    rows = [
        ("发票代码", "033002100211"),
        ("发票号码", "26332000000045678901"),
        ("开票日期", "2026年10月03日"),
        ("购买方名称", "星辰科技股份有限公司"),
        ("纳税人识别号", "91330000MA2XXXXX1Y"),
        ("销售方名称", "杭州西湖春天餐饮有限公司"),
        ("纳税人识别号", "91330106MA2AB6CD7P"),
    ]
    y = draw_rows(d, rows, start_y=140, gap=34, size=16)
    y += 14
    d.text((80, y), "货物或应税劳务、服务名称", font=get_font(15, bold=True), fill="#1a5490")
    y = draw_table(
        d,
        ["项目名称", "数量", "金额", "税率", "税额"],
        [["*餐饮服务*餐费", "1次", "2400.00", "免税", "0.00"]],
        top=y + 30, col_x=[100, 480, 620, 760, 880],
    )
    y += 24
    f = get_font(17)
    f_b = get_font(19, bold=True)
    d.text((480, y), "合计金额（不含税）", font=f, fill="#444444")
    d.text((660, y), "¥2400.00", font=f_b, fill="#111111")
    d.text((480, y + 38), "税额", font=f, fill="#444444")
    d.text((660, y + 38), "¥0.00", font=f_b, fill="#111111")
    d.line([(80, y + 82), (W - 80, y + 82)], fill="#1a5490", width=2)
    d.text((80, y + 96), "价税合计（大写）", font=f, fill="#444444")
    d.text((330, y + 96), "贰仟肆佰圆整", font=f_b, fill="#c00000")
    d.text((700, y + 96), "（小写）¥2400.00", font=f_b, fill="#c00000")
    d.text((80, H - 60), "消费城市：杭州    备注：业务招待用餐", font=get_font(15), fill="#444444")
    d.text((W - 320, H - 34), "收款人：—   开票人：张伟", font=get_font(14), fill="#666666")
    return img


def invoice_3_train():
    """铁路电子客票：杭州东 → 上海虹桥，用于 T02 识别与 T08 审批越权场景。"""
    img, d = new_canvas()
    draw_header(d, "电子发票（铁路电子客票）", "中国铁路上海局集团有限公司", color="#8b1a1a")
    rows = [
        ("发票号码", "26332000000013579246"),
        ("开票日期", "2026年10月12日"),
        ("乘车人", "赵六"),
        ("出行日期", "2026-10-12  08:35 开"),
        ("出发站", "杭州东"),
        ("到达站", "上海虹桥"),
        ("车次", "G7502"),
        ("席别", "二等座"),
    ]
    y = draw_rows(d, rows, start_y=140, gap=36, size=17, label_x=100, value_x=340)
    y += 10
    f = get_font(17)
    f_b = get_font(19, bold=True)
    d.line([(80, y), (W - 80, y)], fill="#8b1a1a", width=2)
    d.text((100, y + 18), "票价", font=f, fill="#444444")
    d.text((340, y + 18), "¥553.00", font=f_b, fill="#c00000")
    d.text((100, y + 60), "购买方名称", font=f, fill="#444444")
    d.text((340, y + 60), "星辰科技股份有限公司", font=f_b, fill="#111111")
    d.text((100, y + 102), "纳税人识别号", font=f, fill="#444444")
    d.text((340, y + 102), "91330000MA2XXXXX1Y", font=f_b, fill="#111111")
    d.text((80, H - 58), "备注：限乘车当日有效。电子客票，无需换取纸质车票。",
           font=get_font(14), fill="#666666")
    return img


def invoice_4_receipt():
    """收据（非发票）：用于 T10 缺发票识别，is_invoice 应为 false。"""
    img, d = new_canvas()
    d.rectangle([40, 40, W - 40, H - 40], outline="#999999", width=3)
    draw_header(d, "收  款  收  据", "（非发票，仅作收款凭证）", color="#555555")
    rows = [
        ("日期", "2026年10月14日"),
        ("付款单位", "星辰科技股份有限公司"),
        ("收款事由", "出租车费（市内交通）"),
        ("金额（大写）", "叁佰陆拾圆整"),
        ("金额（小写）", "¥360.00"),
        ("收款人", "刘师傅"),
        ("收款单位", "杭州市个体出租车（无发票资质）"),
    ]
    y = draw_rows(d, rows, start_y=160, gap=42, size=18, label_x=110, value_x=380)
    d.line([(80, y + 20), (W - 80, y + 20)], fill="#999999", width=2, joint=None) if False else None
    d.text((W // 2, H - 90), "本收据不能作为报销发票使用", font=get_font(17, bold=True),
           fill="#c00000", anchor="mm")
    d.text((W // 2, H - 55), "（盖章处）", font=get_font(14), fill="#999999", anchor="mm")
    return img


def main():
    samples = [
        ("住宿费专票_上海1650元.png", invoice_1_lodging),
        ("餐饮发票_杭州2400元.png", invoice_2_dining),
        ("火车票_杭州至上海.png", invoice_3_train),
        ("收据_出租车360元.png", invoice_4_receipt),
    ]
    for name, fn in samples:
        path = os.path.join(OUT_DIR, name)
        fn().save(path, "PNG")
        print(f"已生成 {path}")

    print(f"\n共 {len(samples)} 张测试样票 -> {OUT_DIR}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None
    main()
