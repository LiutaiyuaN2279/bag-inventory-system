"""把 7 个报销专用角色并入「基础账号体系」：补只读业务权限，报销权限全保留。

运行：进入 backend 目录后执行
    .venv/Scripts/python.exe scripts/merge_reimburse_into_business.py

## 背景

系统原有 12 个账号分两类：

| 类别 | 账号 | 首页 |
| --- | --- | --- |
| 5 个业务基础账号 | admin / manager / buyer / keeper / qc | 采购库存看板 |
| 7 个报销专用账号 | gm / finance / finmaker / director / depthead / sales / tech | 报销工作台（只有报销） |

后一类的角色只有 `reimburse:*` + `dashboard:view`，没有任何采购/库存/基础数据权限。
于是它们登录后看不到完整的系统功能，首页也只渲染报销工作台，与「基础账号」割裂。

## 本次改造

给这 7 个角色补齐**只读的业务权限**，让它们与基础账号一样能浏览系统全局数据
（物料 / 供应商 / 仓库 / 库存 / 采购单据 / BOM / 质检 / 报表 / AI 记录）：

    basic:material:list / basic:supplier:list / basic:warehouse:list
    inventory:view / inventory:alert
    purchase:requisition:list / purchase:order:list
    purchase:arrival:list / purchase:return:list
    bom:view / qc:view / outsource:list
    report:view / ai:ocr:list

（操作日志 `system:log` 不在其中：该权限只授予系统管理员，见 scripts/upgrade_db_v7_oplog.py）

**只加 list / view 类只读权限，不加任何 add / edit / delete / approve / adjust** ——
报销岗不承担采购制单与库存操作职能，写入能力仍然只属于业务岗位。
报销权限（`reimburse:*`）一条不删，报销全流程保持可用。

## 效果

- 首页：`isBusinessView` 判定为真 → 渲染采购库存看板（KPI / 快速入口 / 待办 / 图表 / 单据），
  不再只有报销工作台；
- 侧边栏：出现基础数据、采购管理、库存管理、报表中心等菜单（只读）；
- 报销模块：菜单与全部操作不受影响。

## 幂等

只补缺失项，已存在的不重复添加；不删除、不修改任何现有权限与用户级覆盖。
清理这些新增权限：`--revert` 参数会移除本脚本添加的那批只读权限（报销权限不动）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.database import SessionLocal
from app.models.rbac import Permission, Role, RolePermission

#: 需要并入基础账号体系的报销角色
TARGET_ROLES = [
    "general_manager",   # gm 张总
    "finance_approve",   # 财务审批（finance / finmaker 共用）
    "maker",             # 制单员（finmaker）
    "reviewer",          # 复核员（finance）
    "staff",             # 普通员工（sales / tech）
    "dept_head",         # 部门负责人（depthead）
    "dept_director",     # 部门总监（director）
]

#: 补齐的只读业务权限 —— 全部是 list / view，不含任何写操作
READONLY_PERMS = [
    "basic:material:list",
    "basic:supplier:list",
    "basic:warehouse:list",
    "inventory:view",
    "inventory:alert",
    "purchase:requisition:list",
    "purchase:order:list",
    "purchase:arrival:list",
    "purchase:return:list",
    "bom:view",
    "qc:view",
    "outsource:list",
    "report:view",
    "ai:ocr:list",
]


def run(revert: bool = False) -> int:
    db = SessionLocal()
    try:
        perms = {p.perm_code: p for p in db.query(Permission).all()}
        missing = [c for c in READONLY_PERMS if c not in perms]
        if missing:
            raise SystemExit(f"✗ 权限码不存在，请先运行 init_db/upgrade：{', '.join(missing)}")

        action = "移除" if revert else "补齐"
        print(f"{action}只读业务权限（{len(READONLY_PERMS)} 项 × {len(TARGET_ROLES)} 个角色）\n")

        total = 0
        for code in TARGET_ROLES:
            role = db.query(Role).filter(Role.role_code == code).first()
            if not role:
                print(f"  ! 角色 {code} 不存在，跳过")
                continue

            existing = {rp.permission_id for rp in
                        db.query(RolePermission).filter(RolePermission.role_id == role.id).all()}

            if revert:
                to_remove = [perms[p] for p in READONLY_PERMS
                             if p in perms and perms[p].id in existing]
                for p in to_remove:
                    db.query(RolePermission).filter(
                        RolePermission.role_id == role.id,
                        RolePermission.permission_id == p.id,
                    ).delete()
                total += len(to_remove)
                print(f"  - {code:<15}{role.role_name:<10} 移除 {len(to_remove):>2} 项")
            else:
                added = []
                for p_code in READONLY_PERMS:
                    p = perms[p_code]
                    if p.id in existing:
                        continue
                    db.add(RolePermission(role_id=role.id, permission_id=p.id))
                    added.append(p_code)
                total += len(added)
                state = f"+{len(added)}" if added else "已齐"
                print(f"  + {code:<15}{role.role_name:<10} {state}")

        db.commit()
        print(f"\n✓ 完成，共变更 {total} 条角色权限。")

        # 自检
        print("\n自检 —— 各角色权限总数：")
        for code in TARGET_ROLES:
            role = db.query(Role).filter(Role.role_code == code).first()
            if not role:
                continue
            codes = {p.perm_code for p in role.permissions}
            biz = sum(1 for c in codes if c in READONLY_PERMS)
            reimb = sum(1 for c in codes if c.startswith("reimburse:"))
            print(f"  {code:<15}{role.role_name:<10} 只读业务 {biz:>2} 项 / 报销 {reimb:>2} 项 / 合计 {len(codes)} 项")

        # 关键校验：写权限不能被误加
        WRITE_MARKERS = (":add", ":edit", ":delete", ":approve", ":adjust", ":make", ":review", "manage")
        bad = []
        for code in TARGET_ROLES:
            role = db.query(Role).filter(Role.role_code == code).first()
            if not role:
                continue
            for p in role.permissions:
                c = p.perm_code
                if c in READONLY_PERMS:
                    continue
                if c.startswith("reimburse:") or c in (
                    "dashboard:view", "report:view", "bom:view", "inventory:view",
                    "qc:view", "outsource:list", "ai:ocr:list",
                ):
                    continue
                if any(m in c for m in WRITE_MARKERS):
                    bad.append((code, c))
        if bad:
            print("\n! 注意：以下角色出现非报销写权限（应核查是否越权）：")
            for code, c in bad:
                print(f"    {code}: {c}")
        else:
            print("\n✓ 校验通过：未给报销角色添加任何业务写权限。")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(run(revert="--revert" in sys.argv))
