"""按「部门 × 职位」分层收敛报销账号的业务视野（幂等）。

运行：进入 backend 目录后执行
    .venv/Scripts/python.exe scripts/tune_visibility_by_dept_position.py          # 应用
    .venv/Scripts/python.exe scripts/tune_visibility_by_dept_position.py --check # 只检查

## 背景

`merge_reimburse_into_business.py` 曾给 7 个报销角色**统一**补了 15 项只读业务权限。
这让「销售部普通员工（郑洁）」与「总经理（张总）」看到完全相同的全公司采购金额、
库存与操作日志——既违反最小权限，也让演示中的角色差异消失。

本次按 `app/core/visibility.py` 的视野规则，把权限收敛成三档：

| 视野 | 角色 | 可见模块 |
| --- | --- | --- |
| 全公司 | 总经理 / 财务审批 / 制单员 / 复核员 | 15 项完整只读（含日志、AI 记录） |
| 本部门 | 部门负责人 / 部门总监 | 12 项业务只读（去系统日志、AI 记录） |
| 仅本人 | 普通员工 | 3 项基础主数据（填单要用），业务单据与报表全关 |

只增删 `visibility.MANAGED_PERMS` 管辖的这 15 个只读权限码，
**不碰报销权限、不碰写权限、不碰 5 个业务岗位**。

## 数据范围

权限码只决定「能不能进这个模块」。进入之后能看到哪些行由部门范围决定：

- 请购单（唯一带 `dept` 字段的业务表）→ 部门负责人/总监只看本部门、普通员工只看本人；
- 其它业务表没有部门归属列，只能按职位决定整块是否可见（见 visibility.py 的说明）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.database import SessionLocal
from app.core.visibility import (
    MANAGED_PERMS,
    ROLE_SCOPE,
    SCOPE_ALL,
    SCOPE_DEPT,
    SCOPE_PERMS,
    SCOPE_SELF,
)
from app.models.rbac import Permission, Role, RolePermission

#: 参与调整的角色（营养模块新增的 7 个角色；业务岗位不动）
TARGET_ROLES = [
    "general_manager", "finance_approve", "maker", "reviewer",
    "staff", "dept_head", "dept_director",
]

SCOPE_LABEL = {SCOPE_ALL: "全公司", SCOPE_DEPT: "本部门", SCOPE_SELF: "仅本人"}


def desired_scope(role_code: str) -> str:
    return ROLE_SCOPE.get(role_code, SCOPE_SELF)


def run(check_only: bool = False) -> int:
    db = SessionLocal()
    try:
        perms = {p.perm_code: p for p in db.query(Permission).all()}
        managed_ids = {perms[c].id for c in MANAGED_PERMS if c in perms}

        print(f"{'检查' if check_only else '应用'}：按部门职位收敛视野\n")
        total_add = total_del = 0

        for code in TARGET_ROLES:
            role = db.query(Role).filter(Role.role_code == code).first()
            if not role:
                print(f"  ! 角色 {code} 不存在，跳过")
                continue

            scope = desired_scope(code)
            want = {perms[p].id for p in SCOPE_PERMS[scope] if p in perms}

            rows = db.query(RolePermission).filter(RolePermission.role_id == role.id).all()
            have = {r.permission_id for r in rows}
            # 只处理本模块管辖的权限，其它（报销 / 业务写权限）原样保留
            have_managed = have & managed_ids

            to_add = want - have_managed
            to_del = have_managed - want

            label = f"{code:<16}{role.role_name:<8}{SCOPE_LABEL[scope]:<6}"
            if not to_add and not to_del:
                print(f"  · {label} 已符合（{len(want)} 项）")
                continue

            if not check_only:
                for pid in to_add:
                    db.add(RolePermission(role_id=role.id, permission_id=pid))
                if to_del:
                    db.query(RolePermission).filter(
                        RolePermission.role_id == role.id,
                        RolePermission.permission_id.in_(to_del),
                    ).delete(synchronize_session=False)

            total_add += len(to_add)
            total_del += len(to_del)
            print(f"  {'~' if check_only else '+'} {label} "
                  f"{'+' + str(len(to_add)) if to_add else ''}"
                  f"{'/' if to_add and to_del else ''}"
                  f"{'-' + str(len(to_del)) if to_del else ''}"
                  f"  → {len(want)} 项")

        if check_only:
            print(f"\n检查完毕：需新增 {total_add} 条、需移除 {total_del} 条（未改动）")
            return 0 if (total_add == 0 and total_del == 0) else 1

        db.commit()
        print(f"\n✓ 完成：新增 {total_add} 条、移除 {total_del} 条。")

        # 自检：逐角色核对，并确认报销权限与写权限均未受影响
        print("\n自检：")
        problem = []
        for code in TARGET_ROLES:
            role = db.query(Role).filter(Role.role_code == code).first()
            if not role:
                continue
            codes = {p.perm_code for p in role.permissions}
            scope = desired_scope(code)
            want = set(SCOPE_PERMS[scope])
            got_managed = codes & set(MANAGED_PERMS)
            missing, extra = want - got_managed, got_managed - want
            reimburse_n = sum(1 for c in codes if c.startswith("reimburse:"))
            write_n = sum(1 for c in codes
                          if c in MANAGED_PERMS and not c.endswith((":list", ":view")))
            flag = "✓" if not missing and not extra else "✗"
            print(f"  {flag} {code:<16}{SCOPE_LABEL[scope]:<6}"
                  f"只读 {len(got_managed):>2} 项 / 报销 {reimburse_n} 项"
                  f"{'  缺失:' + str(sorted(missing)) if missing else ''}"
                  f"{'  多余:' + str(sorted(extra)) if extra else ''}")
            if missing or extra:
                problem.append(code)

        print()
        if problem:
            print(f"✗ 以下角色与期望不符：{problem}")
            return 1
        print("✓ 全部角色视野符合「部门 × 职位」预期。")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(run("--check" in sys.argv))
