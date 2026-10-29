"""按「部门 × 职位」对齐报销模块权限，并修正职责分离缺陷（幂等）。

运行：进入 backend 目录后执行
    .venv/Scripts/python.exe scripts/align_permissions_by_dept_position.py

## 本次修正的问题

`manager`（陈静，财务部）同时持有**制单**（`voucher:make`）与**凭证复核**
（`voucher:review`）两项权限 —— 同一个人既能制证又能复核，违反了系统反复强调的
职责分离原则（虽然后端校验「复核人不能是制单人」能挡住自审，但持有互斥权限本身
就是控制设计缺陷：她可以复核别人制的证，同时又能制证给别人复核，形成串通风险）。

## 财务岗的正确分工（制度第四条 + 职责分离）

| 岗位 | 账号 | 职责 | 不应拥有 |
| --- | --- | --- | --- |
| 财务复核（管理） | `manager` 陈静 | 审批、判读、人工覆盖 | 制单、复核凭证 |
| 财务制单 | `finmaker` 吴强 | 制证、审批、判读、覆盖 | 复核凭证 |
| 财务复核（执行） | `finance` 周敏 | 复核凭证、审批、判读、覆盖 | 制单 |

三人**都可审批**（制度第四条允许财务复核审 <5,000 元），但制单与复核严格互斥：
- 只有吴强能制证
- 只有周敏能复核
- 陈静只做审批与判定，不碰凭证的编制与复核

## 实现方式

用**用户级权限覆盖**（`user_permissions` 表，effect=deny）禁用陈静的制单/复核权限，
不改动 `manager` 角色本身 —— 该角色还承载采购/库存/报表等 30 项业务权限，
只针对报销模块的两项互斥权限做减法。

系统 `require_permissions` 的判定顺序是「用户级 deny 优先于一切（含 admin 放行）」，
因此 deny 能可靠生效，且「用户管理 → 配置权限」页面能看到这两个被取消勾选的项。

## 附：部门负责人覆盖情况（不新增账号）

制度第四条规定 <5,000 元由「部门负责人 **或** 财务复核」审批。当前只有销售部设有
部门负责人（`depthead` 李强）与部门总监（`director` 王建国）；采购部、仓储部、
质检部、信息技术部、行政部均无部门负责人。

这些部门的报销单由其**财务复核**（全公司数据范围）或总经理审批即可，完全符合制度
第四条 —— 因此不额外新建部门负责人账号，避免为 1 人部门设置「自己审自己」的伪岗位。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.database import SessionLocal
from app.models.rbac import Permission, User, UserPermission

# ---------------- 需要禁用的互斥权限 ----------------
# username -> [(perm_code, 理由)]
DENY_RULES = {
    "manager": [
        ("reimburse:voucher:make",
         "财务复核岗不直接制证（制单由 finmaker 吴强负责）"),
        ("reimburse:voucher:review",
         "财务复核岗不直接复核凭证（复核由 finance 周敏负责）"),
    ],
}

# ---------------- 财务岗分工期望（用于校验）----------------
EXPECTED_FINANCE = {
    "manager": {"make": False, "review": False, "approve": True},
    "finmaker": {"make": True, "review": False, "approve": True},
    "finance": {"make": False, "review": True, "approve": True},
}


def apply_deny(db) -> int:
    """给目标用户加用户级 deny。返回新增条数。"""
    perms = {p.perm_code: p for p in db.query(Permission).all()}
    added = 0
    for username, rules in DENY_RULES.items():
        user = db.query(User).filter(User.username == username).first()
        if not user:
            print(f"  ! 用户 {username} 不存在，跳过")
            continue
        for code, reason in rules:
            perm = perms.get(code)
            if not perm:
                print(f"  ! 权限码 {code} 不存在，跳过")
                continue
            row = db.query(UserPermission).filter(
                UserPermission.user_id == user.id,
                UserPermission.permission_id == perm.id,
            ).first()
            if row:
                if row.effect == "deny":
                    print(f"  · {username} 已禁用 {code}")
                    continue
                row.effect = "deny"
                print(f"  → {username}：{code} 由 {row.effect} 改为 deny")
                added += 1
            else:
                db.add(UserPermission(user_id=user.id, permission_id=perm.id,
                                      effect="deny"))
                print(f"  + {username} 禁用 {code}（{reason}）")
                added += 1
    return added


def effective_perms(db, user: User) -> set:
    """计算用户实际生效的报销权限码（角色权限 − 用户级 deny）。"""
    granted = set()
    for role in user.roles:
        granted |= {p.perm_code for p in role.permissions}
    denied = {
        db.get(Permission, row.permission_id).perm_code
        for row in db.query(UserPermission).filter(
            UserPermission.user_id == user.id,
            UserPermission.effect == "deny",
        ).all()
        if db.get(Permission, row.permission_id)
    }
    return {p for p in granted if p not in denied}


def verify_finance(db) -> bool:
    """校验财务岗三人的职责分离是否成立。"""
    print("\n" + "=" * 74)
    print("财务岗职责分离校验")
    print("=" * 74)
    all_ok = True
    for username, expect in EXPECTED_FINANCE.items():
        user = db.query(User).filter(User.username == username).first()
        if not user:
            print(f"  ! {username} 不存在")
            all_ok = False
            continue
        perms = effective_perms(db, user)
        make = "reimburse:voucher:make" in perms
        review = "reimburse:voucher:review" in perms
        approve = "reimburse:bill:approve" in perms
        ok = (make == expect["make"] and review == expect["review"]
              and approve == expect["approve"])
        all_ok = all_ok and ok
        print(f"  {'✓' if ok else '✗'} {user.real_name or username:<6}"
              f"制单={'✓' if make else '✗'}  复核={'✓' if review else '✗'}  "
              f"审批={'✓' if approve else '✗'}")
    return all_ok


def check_global_separation(db) -> None:
    """全局检查：是否还有人同时持有制单与复核。

    admin（系统管理员）豁免：它是超级用户，需要能代行任何操作（含故障处理），
    但**业务上不使用**它做日常制单/复核；且后端「复核人不能是制单人」的校验
    即使在 admin 自审时也会拦截，因此不视为缺陷。业务岗位则必须互斥。
    """
    print("\n全局职责分离检查（制单 × 复核 互斥，系统管理员豁免）")
    conflicts = []
    for user in db.query(User).all():
        if any(r.role_code == "admin" for r in user.roles):
            continue
        perms = effective_perms(db, user)
        if ("reimburse:voucher:make" in perms
                and "reimburse:voucher:review" in perms):
            conflicts.append(user)
    if conflicts:
        for u in conflicts:
            print(f"  ✗ {u.username}（{u.real_name}）同时具备制单与复核")
    else:
        print("  ✓ 所有业务岗位均无制单与复核共存的情况")


def print_matrix(db) -> None:
    """打印「部门 × 职位 × 权限」矩阵。"""
    print("\n" + "=" * 96)
    print("部门 × 职位 × 报销权限矩阵")
    print("=" * 96)

    from app.models.reimburse import RmbDepartment, RmbEmployee
    from app.api.v1.reimburse._common import ROLE_DATA_SCOPE

    scope_label = {"all": "全公司", "dept": "本部门", "self": "仅本人"}

    users = (
        db.query(User)
        .order_by(User.id)
        .all()
    )
    print(f"{'部门':<12}{'姓名':<8}{'职位（角色）':<24}{'范围':<7}{'能力'}")
    print("-" * 96)

    def sort_key(u):
        emp = db.get(RmbEmployee, u.employee_id) if u.employee_id else None
        dept = db.get(RmbDepartment, emp.department_id) if emp and emp.department_id else None
        return (dept.code if dept else "Z99", u.id)

    for user in sorted(users, key=sort_key):
        emp = db.get(RmbEmployee, user.employee_id) if user.employee_id else None
        dept = db.get(RmbDepartment, emp.department_id) if emp and emp.department_id else None
        dept_name = dept.name if dept else "（独立）"
        role_names = "、".join(r.role_name for r in user.roles) or "-"
        perms = effective_perms(db, user)
        scopes = {ROLE_DATA_SCOPE.get(r.role_code, "self") for r in user.roles}
        scope = "all" if "all" in scopes else ("dept" if "dept" in scopes else "self")

        ability = []
        if "reimburse:bill:add" in perms:
            ability.append("填单")
        if "reimburse:bill:approve" in perms:
            ability.append("审批")
        if "reimburse:check:run" in perms:
            ability.append("判读")
        if "reimburse:check:override" in perms:
            ability.append("覆盖")
        if "reimburse:voucher:make" in perms:
            ability.append("制单")
        if "reimburse:voucher:review" in perms:
            ability.append("复核")
        if "reimburse:policy:manage" in perms:
            ability.append("制度")
        if not ability:
            ability = ["（无报销权限）"]

        print(f"{dept_name:<12}{user.real_name or user.username:<8}"
              f"{role_names:<24}{scope_label[scope]:<7}{'、'.join(ability)}")

    print("-" * 96)
    print("说明：审批层级由角色决定（部门负责人/财务审批=1 级，部门总监=2 级，总经理=3 级）；")
    print("      数据范围：财务/总经理/制单/复核=全公司，部门管理岗=本部门，业务岗=仅本人。")


def run():
    db = SessionLocal()
    try:
        print("[1/3] 按职位修正互斥权限（职责分离）...")
        n = apply_deny(db)
        db.commit()
        print(f"  本次变更 {n} 条用户级权限覆盖")

        print("\n[2/3] 校验财务岗分离与全局冲突 ...")
        ok = verify_finance(db)
        check_global_separation(db)

        print("\n[3/3] 输出部门 × 职位 × 权限矩阵 ...")
        print_matrix(db)

        if not ok:
            print("\n⚠ 财务岗职责分离校验未通过，请检查上面的输出")
            return 1
        print("\n权限对齐完成。")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(run())
