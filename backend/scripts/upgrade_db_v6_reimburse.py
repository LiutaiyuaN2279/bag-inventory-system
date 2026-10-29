"""第七轮升级：新增「差旅与业务招待费报销智能体」全部数据表与基础数据（幂等）。

运行：进入 backend 目录后执行
    .venv/Scripts/python.exe scripts/upgrade_db_v6_reimburse.py

内容：
1. 建 16 张 rmb_* 表（create_all 对已存在的表自动跳过）。
2. 初始化会计科目、费用类型、结算方式、城市等级、节假日、系统参数、
   检查规则 R01～R14、部门与员工、报销相关权限码。
3. 把《差旅与业务招待费报销管理制度》正文写入 policy 表（若文件存在）。

设计说明：制度里的每个金额阈值都同时存在三处——制度文件正文、policy_rule 判断规则、
sys_param 参数表。本脚本是唯一初始化入口，保证三处初值一致；后续修改必须走
制度管理页并留痕，这是"制度变更管理"控制点。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import Base, SessionLocal, engine
from app.models.rbac import Permission, Role, RolePermission

# 触发模型注册
from app.models import reimburse as rmb  # noqa: F401
from app.models.reimburse import (
    RmbAccountSubject,
    RmbCityLevel,
    RmbDepartment,
    RmbEmployee,
    RmbExpenseType,
    RmbHoliday,
    RmbPolicyRule,
    RmbSettlementMethod,
    RmbSysParam,
)

# ---------------- 权限码 ----------------
NEW_PERMISSIONS = [
    ("reimburse:bill:list", "报销单-查看", "reimburse"),
    ("reimburse:bill:add", "报销单-填写", "reimburse"),
    ("reimburse:bill:edit", "报销单-修改", "reimburse"),
    ("reimburse:bill:delete", "报销单-作废", "reimburse"),
    ("reimburse:check:run", "合规判读-执行", "reimburse"),
    ("reimburse:check:override", "合规判读-人工覆盖", "reimburse"),
    ("reimburse:voucher:list", "凭证-查看", "reimburse"),
    ("reimburse:voucher:make", "凭证-制单", "reimburse"),
    ("reimburse:voucher:review", "凭证-复核", "reimburse"),
    ("reimburse:policy:manage", "制度与参数管理", "reimburse"),
]

# 角色 -> 权限码。遵循职责分离：制单与复核不可授予同一角色。
ROLE_GRANTS = {
    "admin": [
        "reimburse:bill:list", "reimburse:bill:add", "reimburse:bill:edit",
        "reimburse:bill:delete", "reimburse:check:run", "reimburse:check:override",
        "reimburse:voucher:list", "reimburse:voucher:make", "reimburse:voucher:review",
        "reimburse:policy:manage",
    ],
    # 运营主管：既负责制单又承担判读覆盖，但不给复核权限（复核交给财务复核角色）
    "manager": [
        "reimburse:bill:list", "reimburse:bill:add", "reimburse:bill:edit",
        "reimburse:check:run", "reimburse:check:override",
        "reimburse:voucher:list", "reimburse:voucher:make",
    ],
    # 采购员 / 仓管员 / 质检员：都是业务部门员工，在报销模块中作为「报销人」，
    # 只能提自己单据、执行判读、查看凭证进度（数据范围 = 仅本人）。
    # 注意：keeper / qc 最初漏配，导致这两个账号登录后看不到任何报销菜单，已在此补齐。
    "buyer": [
        "reimburse:bill:list", "reimburse:bill:add", "reimburse:bill:edit",
        "reimburse:check:run", "reimburse:voucher:list",
    ],
    "keeper": [
        "reimburse:bill:list", "reimburse:bill:add", "reimburse:bill:edit",
        "reimburse:check:run", "reimburse:voucher:list",
    ],
    "qc": [
        "reimburse:bill:list", "reimburse:bill:add", "reimburse:bill:edit",
        "reimburse:check:run", "reimburse:voucher:list",
    ],
    # 部门负责人 / 财务审批：具备制单、判读覆盖之外，允许撤回报销单（含已审批的本人单据）；
    #   — 部门负责人：对本部门单据可撤回（数据范围按部门负责人规则）；
    #   — 财务审批：全公司单据可撤回（数据范围全公司）。
    "dept_head": [
        "reimburse:bill:list", "reimburse:bill:add", "reimburse:bill:edit",
        "reimburse:bill:delete", "reimburse:check:run", "reimburse:voucher:list",
    ],
    "finance_approve": [
        "reimburse:bill:list", "reimburse:bill:add", "reimburse:bill:edit",
        "reimburse:bill:delete", "reimburse:check:run", "reimburse:check:override",
        "reimburse:voucher:list",
    ],
}

# ---------------- 会计科目（14 个）----------------
ACCOUNT_SUBJECTS = [
    # code, name, full_name, category, direction, parent, level, is_leaf
    ("1001", "库存现金", "库存现金", "资产", "借", "", 1, True),
    ("1002", "银行存款", "银行存款", "资产", "借", "", 1, True),
    ("2221", "应交税费", "应交税费", "负债", "贷", "", 1, False),
    ("222101", "应交增值税", "应交税费—应交增值税", "负债", "贷", "2221", 2, False),
    ("22210101", "进项税额", "应交税费—应交增值税—进项税额", "负债", "借", "222101", 3, True),
    ("2241", "其他应付款", "其他应付款", "负债", "贷", "", 1, False),
    ("224101", "应付员工报销款", "其他应付款—应付员工报销款", "负债", "贷", "2241", 2, True),
    ("6602", "管理费用", "管理费用", "损益", "借", "", 1, False),
    ("660201", "办公费", "管理费用—办公费", "损益", "借", "6602", 2, True),
    ("660202", "差旅费", "管理费用—差旅费", "损益", "借", "6602", 2, True),
    ("660203", "业务招待费", "管理费用—业务招待费", "损益", "借", "6602", 2, True),
    ("660204", "通讯费", "管理费用—通讯费", "损益", "借", "6602", 2, True),
    ("660205", "交通费", "管理费用—交通费", "损益", "借", "6602", 2, True),
    ("660299", "其他", "管理费用—其他", "损益", "借", "6602", 2, True),
]

# ---------------- 费用类型 ----------------
EXPENSE_TYPES = [
    ("差旅住宿费", "660202", "差旅", "出差期间的住宿费", 1),
    ("差旅交通费", "660202", "差旅", "城际火车、飞机、长途客运等", 2),
    ("业务招待费", "660203", "招待", "招待外部客户的餐费等", 3),
    ("市内交通费", "660205", "无", "市内出租车、网约车等", 4),
    ("通讯费", "660204", "无", "话费、流量等", 5),
    ("办公费", "660201", "无", "零星办公用品", 6),
    ("其他费用", "660299", "无", "—", 7),
]

# ---------------- 结算方式 ----------------
SETTLEMENT_METHODS = [
    ("银行转账（付给报销人）", "1002", "付给报销人，记银行存款"),
    ("现金支付", "1001", "现金支付"),
    ("挂账（暂未支付）", "224101", "暂未支付，记其他应付款"),
]

# ---------------- 城市等级 ----------------
CITY_LEVELS = [
    ("北京", "一线城市", 600), ("上海", "一线城市", 600),
    ("广州", "一线城市", 600), ("深圳", "一线城市", 600),
    ("杭州", "其他城市", 400), ("南京", "其他城市", 400),
    ("成都", "其他城市", 400), ("武汉", "其他城市", 400),
    ("西安", "其他城市", 400), ("重庆", "其他城市", 400),
    ("天津", "其他城市", 400), ("苏州", "其他城市", 400),
    ("其他城市", "其他城市", 400),  # 兜底记录，查不到时按此标准
]

# ---------------- 系统参数 ----------------
SYS_PARAMS = [
    ("company_name", "星辰科技股份有限公司", "本单位名称（用真实票据测试时改为票据上的购买方名称）"),
    ("company_tax_id", "91330000MA2XXXXX1Y", "本单位纳税人识别号"),
    ("approval_level2_amount", "5000", "须经部门总监审批的起点金额（第四条）"),
    ("approval_level3_amount", "20000", "须经总经理审批的起点金额（第四条）"),
    ("entertain_per_capita_limit", "300", "业务招待人均标准，元/餐（第七条）"),
    ("entertain_single_limit", "2000", "业务招待单次标准，元（第七条）"),
    ("split_days_window", "3", "拆分报销检查的“相近日期”天数（第五条）"),
    ("default_voucher_word", "记", "默认凭证字"),
    ("policy_no", "XC-CW-2025-008", "制度文件编号"),
    ("policy_name", "差旅与业务招待费报销管理制度", "制度名称"),
]

# ---------------- 检查规则 R01～R14 ----------------
POLICY_RULES = [
    ("R01", "审批权限是否匹配",
     "金额＜5,000 元：部门负责人或财务复核及以上；5,000（含）～20,000 元：部门总监及以上；≥20,000 元：总经理",
     "第四条", "高", "AI+程序"),
    ("R02", "是否拆分报销",
     "同一报销人、同一费用类型、发生日期相同或相近（±3 天）的多笔报销，合计金额达到更高审批层级而未按合计金额审批",
     "第五条", "高", "AI+程序"),
    ("R03", "招待人均是否超标",
     "业务招待费 ÷ 陪同人数 > 300 元", "第七条①", "中", "AI+程序"),
    ("R04", "招待单次是否超标",
     "单次业务招待费 > 2,000 元，且未附情况说明并经部门总监审批", "第七条②", "中", "AI+程序"),
    ("R05", "是否周末/节假日招待",
     "业务招待费发生在周六、周日或法定节假日，且无分管领导事前特批", "第八条", "中", "AI+程序"),
    ("R06", "住宿是否超标",
     "一线城市 > 600 元/晚，其他城市 > 400 元/晚", "第九条", "中", "AI+程序"),
    ("R07", "是否缺发票",
     "未附合规发票，且无情况说明及总经理特批", "第十一条", "高", "AI+程序"),
    ("R08", "是否跨期报销",
     "报销日期年份 ≠ 费用发生日期年份；有说明的提示按权责发生制归属期间", "第十二条", "中", "AI+程序"),
    ("R09", "是否疑似重复",
     "同一报销人、同金额、同费用类型、同发生日期、不同报销单号", "第三条（真实性）", "高", "AI+程序"),
    ("R10", "招待要素是否齐全",
     "业务招待费须注明招待事由、招待对象单位、陪同人数", "第六条", "中", "AI"),
    ("R11", "差旅要素是否齐全",
     "差旅费须注明出差事由、起止日期、出差地点、住宿晚数", "第十条", "中", "AI"),
    ("R12", "单据要素是否齐全",
     "报销单号、日期、报销人、部门、费用类型、事由、发生日期、金额、是否附发票、审批人齐全",
     "第十三条", "低", "AI"),
    ("R13", "票据与填报是否一致",
     "票据金额、日期、城市、购买方抬头、乘车人等与报销信息一致", "第三条、第十一条", "高", "AI"),
    ("R14", "报销事由是否合理",
     "事由与费用类型、票据内容相符，无以娱乐、礼品、内部聚餐等冒充业务招待或差旅的情形", "第三条", "中", "AI"),
]

# ---------------- 部门与员工 ----------------
DEPARTMENTS = [
    ("D01", "财务部"), ("D02", "销售部"), ("D03", "信息技术部"), ("D04", "行政部"),
]
EMPLOYEES = [
    ("E001", "陈静", "D01"), ("E002", "王五", "D02"),
    ("E003", "赵六", "D03"), ("E004", "孙七", "D04"),
]

# ---------------- 2026 年节假日（国务院办公厅安排）----------------
# 只录入与报销判读相关的日期：法定节假日放假日 + 调休上班日
HOLIDAYS_2026 = [
    # 元旦
    ("2026-01-01", "元旦", "法定节假日"),
    ("2026-01-02", "元旦", "法定节假日"),
    ("2026-01-03", "元旦", "法定节假日"),
    ("2026-01-04", "元旦调休上班", "调休上班日"),
    # 春节（2/17 除夕）
    ("2026-02-15", "春节", "法定节假日"),
    ("2026-02-16", "春节", "法定节假日"),
    ("2026-02-17", "春节", "法定节假日"),
    ("2026-02-18", "春节", "法定节假日"),
    ("2026-02-19", "春节", "法定节假日"),
    ("2026-02-20", "春节", "法定节假日"),
    ("2026-02-21", "春节", "法定节假日"),
    ("2026-02-22", "春节", "法定节假日"),
    ("2026-02-14", "春节调休上班", "调休上班日"),
    ("2026-02-28", "春节调休上班", "调休上班日"),
    # 清明
    ("2026-04-04", "清明节", "法定节假日"),
    ("2026-04-05", "清明节", "法定节假日"),
    ("2026-04-06", "清明节", "法定节假日"),
    # 劳动节
    ("2026-05-01", "劳动节", "法定节假日"),
    ("2026-05-02", "劳动节", "法定节假日"),
    ("2026-05-03", "劳动节", "法定节假日"),
    ("2026-05-04", "劳动节", "法定节假日"),
    ("2026-05-05", "劳动节", "法定节假日"),
    ("2026-04-26", "劳动节调休上班", "调休上班日"),
    ("2026-05-09", "劳动节调休上班", "调休上班日"),
    # 端午
    ("2026-06-19", "端午节", "法定节假日"),
    ("2026-06-20", "端午节", "法定节假日"),
    ("2026-06-21", "端午节", "法定节假日"),
    # 中秋 + 国庆（2026 年中秋 9/25，国庆 10/1）
    ("2026-09-25", "中秋节", "法定节假日"),
    ("2026-09-26", "中秋节", "法定节假日"),
    ("2026-09-27", "中秋节", "法定节假日"),
    ("2026-10-01", "国庆节", "法定节假日"),
    ("2026-10-02", "国庆节", "法定节假日"),
    ("2026-10-03", "国庆节", "法定节假日"),
    ("2026-10-04", "国庆节", "法定节假日"),
    ("2026-10-05", "国庆节", "法定节假日"),
    ("2026-10-06", "国庆节", "法定节假日"),
    ("2026-10-07", "国庆节", "法定节假日"),
    ("2026-09-28", "国庆调休上班", "调休上班日"),
    ("2026-10-10", "国庆调休上班", "调休上班日"),
]


def _seed_base(db):
    """基础数据：科目、费用类型、结算方式、城市等级、节假日、参数、规则、部门员工。"""
    print("[2/5] 初始化会计科目 ...")
    for code, name, full_name, cat, direction, parent, level, is_leaf in ACCOUNT_SUBJECTS:
        if not db.query(RmbAccountSubject).filter(RmbAccountSubject.code == code).first():
            db.add(RmbAccountSubject(
                code=code, name=name, full_name=full_name, category=cat,
                balance_direction=direction, parent_code=parent, level=level, is_leaf=is_leaf,
            ))

    print("[3/5] 初始化费用类型 / 结算方式 / 城市等级 / 节假日 / 参数 ...")
    for name, subj, special, remark, sort_no in EXPENSE_TYPES:
        if not db.query(RmbExpenseType).filter(RmbExpenseType.name == name).first():
            db.add(RmbExpenseType(name=name, subject_code=subj, special_info=special,
                                  remark=remark, sort_no=sort_no))

    for name, subj, remark in SETTLEMENT_METHODS:
        if not db.query(RmbSettlementMethod).filter(RmbSettlementMethod.name == name).first():
            db.add(RmbSettlementMethod(name=name, subject_code=subj, remark=remark))

    for city, level, limit in CITY_LEVELS:
        if not db.query(RmbCityLevel).filter(RmbCityLevel.city_name == city).first():
            db.add(RmbCityLevel(city_name=city, city_level=level, lodging_limit=limit))

    for day, name, dtype in HOLIDAYS_2026:
        if not db.query(RmbHoliday).filter(RmbHoliday.holiday_date == day).first():
            db.add(RmbHoliday(holiday_date=day, holiday_name=name, day_type=dtype))

    for key, value, remark in SYS_PARAMS:
        if not db.query(RmbSysParam).filter(RmbSysParam.param_key == key).first():
            db.add(RmbSysParam(param_key=key, param_value=value, remark=remark))

    print("[4/5] 初始化检查规则 R01～R14 ...")
    for i, (code, item, rule, clause, risk, mode) in enumerate(POLICY_RULES, start=1):
        if not db.query(RmbPolicyRule).filter(RmbPolicyRule.rule_code == code).first():
            db.add(RmbPolicyRule(rule_code=code, check_item=item, judge_rule=rule,
                                 clause_no=clause, risk_level=risk, check_mode=mode, sort_no=i))

    print("[5/5] 初始化部门与员工 ...")
    dept_map = {}
    for code, name in DEPARTMENTS:
        d = db.query(RmbDepartment).filter(RmbDepartment.code == code).first()
        if not d:
            d = RmbDepartment(code=code, name=name)
            db.add(d)
            db.flush()
        dept_map[code] = d.id
    for emp_no, name, dept_code in EMPLOYEES:
        if not db.query(RmbEmployee).filter(RmbEmployee.emp_no == emp_no).first():
            db.add(RmbEmployee(emp_no=emp_no, name=name, department_id=dept_map.get(dept_code)))


def _seed_permissions(db):
    """权限码与角色分配。"""
    print("  - 补齐报销模块权限码 ...")
    for code, name, module in NEW_PERMISSIONS:
        p = db.query(Permission).filter(Permission.perm_code == code).first()
        if p:
            print(f"    · {code} 已存在，跳过")
        else:
            db.add(Permission(perm_code=code, perm_name=name, module=module))
            print(f"    + {code} 已添加")
    db.flush()

    perms = {p.perm_code: p for p in db.query(Permission).all()}
    for role_code, codes in ROLE_GRANTS.items():
        role = db.query(Role).filter(Role.role_code == role_code).first()
        if not role:
            print(f"    ! 角色 {role_code} 不存在，跳过（请先运行 scripts/setup_roles.py）")
            continue
        for code in codes:
            perm = perms.get(code)
            if not perm:
                continue
            exists = db.query(RolePermission).filter(
                RolePermission.role_id == role.id,
                RolePermission.permission_id == perm.id,
            ).first()
            if not exists:
                db.add(RolePermission(role_id=role.id, permission_id=perm.id))
                print(f"    + {role_code} ← {code}")


def _seed_policy_text(db):
    """把制度文件正文写入 policy 表，供 AI 判读时直接引用（避免依赖百炼文件上传）。"""
    import hashlib

    docx_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "docs", "policies", "差旅与业务招待费报销管理制度.docx",
    )
    if not os.path.exists(docx_path):
        print(f"  · 制度文件不存在，跳过：{docx_path}")
        return

    try:
        from docx import Document
    except ImportError:
        print("  · 未安装 python-docx，跳过制度正文导入（可手工在制度管理页上传）")
        return

    doc = Document(docx_path)
    lines = []
    for p in doc.paragraphs:
        t = p.text.strip()
        if t:
            lines.append(t)
    # 表格内容转成文本，保证制度速查表也进入提示词
    for ti, table in enumerate(doc.tables, start=1):
        lines.append(f"\n【表 {ti}】")
        for row in table.rows:
            cells = [c.text.strip().replace("\n", " / ") for c in row.cells]
            if any(cells):
                lines.append(" | ".join(cells))
    content = "\n".join(lines)

    with open(docx_path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()

    if db.query(rmb.RmbPolicy).count() > 0:
        print("  · 制度记录已存在，跳过")
        return

    db.add(rmb.RmbPolicy(
        policy_no="XC-CW-2025-008",
        policy_name="差旅与业务招待费报销管理制度",
        effective_date="2025-01-01",
        file_path=docx_path,
        original_filename=os.path.basename(docx_path),
        file_hash=file_hash,
        content_text=content,
        is_active=True,
        uploaded_by="system",
        remark="初始化导入",
    ))
    print(f"  + 制度正文已导入（{len(content)} 字）")


def run():
    print("[1/5] 建表 ...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        _seed_base(db)
        _seed_permissions(db)
        _seed_policy_text(db)
        db.commit()
        print("\n升级完成！差旅与业务招待费报销模块已就绪。")
        print("提示：报销相关账号可直接使用现有账号（admin / manager / buyer）登录。")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
