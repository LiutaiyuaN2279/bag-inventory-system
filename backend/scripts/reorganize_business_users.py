"""整理采购库存业务账号：补真实姓名、归入对口部门（幂等）。

运行：进入 backend 目录后执行
    .venv/Scripts/python.exe scripts/reorganize_business_users.py

## 背景

采购库存模块的四个业务账号原先显示名是**岗位名**而非人名，且部门归属不对口：

| 账号 | 原显示名 | 原部门 | 问题 |
| --- | --- | --- | --- |
| `manager` | 运营主管 | 财务部 | 显示岗位名，看不出是谁 |
| `buyer` | 采购员 | **销售部** | 采购员挂在销售部 |
| `keeper` | 仓管员 | **行政部** | 仓管员挂在行政部 |
| `qc` | 质检员 | **信息技术部** | 质检员挂在信息技术部 |

这些账号在系统里都已有员工档案（E001 陈静 / E002 王五 / E004 孙七 / E003 赵六），
只是 `users.real_name` 没同步成人名，部门归属也是为了凑数随手挂的。

## 调整内容

1. **显示名改为人名**：运营主管 → 陈静、采购员 → 王五、仓管员 → 孙七、质检员 → 赵六
2. **新建对口部门**：采购部（D06）、仓储部（D07）、质检部（D08）
3. **员工档案调整部门**：
   - 王五（采购员）→ 采购部
   - 孙七（仓管员）→ 仓储部
   - 赵六（质检员）→ 质检部
   - 陈静（运营主管）→ **保持财务部**（制度第四条的「财务复核（陈静）」点名在财务部）
4. **系统管理员（admin）不动**：无员工档案、无部门归属，独立于业务组织架构

## 历史单据的部门归属

已保存的报销单 `department_id` 是**提交时的部门快照**，本次不回溯修改：
员工调岗后历史单据仍归属原部门，这是正常的业务语义。因此：

- 王五的 5 张单据仍记在「销售部」，销售部负责人（depthead）仍可看到并审批；
- 赵六的 5 张单据仍记在「信息技术部」；
- 王五 / 赵六本人作为报销人，数据范围是「仅本人」，不受部门变更影响。

## 注意

`users.real_name` 只用于**界面显示**，不参与任何权限判定（权限按角色 / 数据范围）。
本次调整不影响报销、审批、制单、复核的任何既有权限。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.database import SessionLocal
from app.models.rbac import User
from app.models.reimburse import RmbDepartment, RmbEmployee

# ---------------- 新建部门 ----------------
NEW_DEPARTMENTS = [
    ("D06", "采购部"),
    ("D07", "仓储部"),
    ("D08", "质检部"),
]

# ---------------- 员工档案调整 ----------------
# emp_no -> (姓名, 目标部门编码)
EMPLOYEE_DEPT = {
    "E002": ("王五", "D06"),   # 采购员 → 采购部
    "E003": ("赵六", "D08"),   # 质检员 → 质检部
    "E004": ("孙七", "D07"),   # 仓管员 → 仓储部
    # E001 陈静 保持财务部（制度点名财务复核在财务部）
}

# ---------------- 用户显示名 → 人名 ----------------
# username -> （员工档案里的真实姓名，用于校验一致性）
USER_REAL_NAMES = {
    "manager": ("陈静", "E001"),
    "buyer": ("王五", "E002"),
    "keeper": ("孙七", "E004"),
    "qc": ("赵六", "E003"),
}


def ensure_departments(db) -> dict:
    """确保对口部门存在，返回 {code: RmbDepartment}。"""
    for code, name in NEW_DEPARTMENTS:
        dept = db.query(RmbDepartment).filter(RmbDepartment.code == code).first()
        if dept:
            print(f"  · 部门 {code} {name} 已存在")
        else:
            dept = RmbDepartment(code=code, name=name)
            db.add(dept)
            db.flush()
            print(f"  + 部门 {code} {name} 已创建")
    return {d.code: d for d in db.query(RmbDepartment).all()}


def adjust_employees(db, dept_map: dict) -> dict:
    """把业务岗位员工调整到对口部门，返回 {emp_no: RmbEmployee}。"""
    result = {}
    for emp_no, (expected_name, dept_code) in EMPLOYEE_DEPT.items():
        emp = db.query(RmbEmployee).filter(RmbEmployee.emp_no == emp_no).first()
        if not emp:
            print(f"  ! 员工 {emp_no} 不存在，跳过")
            continue
        if emp.name != expected_name:
            print(f"  ! 员工 {emp_no} 姓名是「{emp.name}」，与预期「{expected_name}」不一致，按现有姓名继续")
        target = dept_map.get(dept_code)
        if not target:
            print(f"  ! 部门 {dept_code} 不存在，跳过")
            continue
        if emp.department_id == target.id:
            print(f"  · {emp_no} {emp.name} 已在 {target.name}")
        else:
            old = db.get(RmbDepartment, emp.department_id) if emp.department_id else None
            emp.department_id = target.id
            print(f"  → {emp_no} {emp.name}：{old.name if old else '（无部门）'} → {target.name}")
        result[emp_no] = emp
    return result


def sync_user_names(db, employees: dict) -> None:
    """把用户显示名从岗位名改成真实姓名。"""
    for username, (real_name, emp_no) in USER_REAL_NAMES.items():
        user = db.query(User).filter(User.username == username).first()
        if not user:
            print(f"  ! 用户 {username} 不存在，跳过")
            continue
        # 校验用户关联的员工档案姓名与目标一致，避免张冠李戴
        emp = employees.get(emp_no)
        if emp and emp.name != real_name:
            print(f"  ! {username} 关联员工姓名为「{emp.name}」，与目标「{real_name}」不一致，跳过")
            continue
        if user.real_name == real_name:
            print(f"  · {username} 显示名已是「{real_name}」")
        else:
            old = user.real_name or "（空）"
            user.real_name = real_name
            print(f"  → {username}：{old} → {real_name}")
        # 顺手确保员工档案关联存在
        if emp and not user.employee_id:
            user.employee_id = emp.id
            print(f"    （已补员工档案关联 {emp_no}）")


def print_summary(db) -> None:
    print("\n" + "=" * 72)
    print("采购库存业务账号（系统管理员除外）")
    print("=" * 72)
    print(f"{'账号':<11}{'姓名':<8}{'部门':<10}{'员工编号'}")
    print("-" * 72)
    for username in ("manager", "buyer", "keeper", "qc"):
        user = db.query(User).filter(User.username == username).first()
        if not user:
            continue
        emp = db.get(RmbEmployee, user.employee_id) if user.employee_id else None
        dept = db.get(RmbDepartment, emp.department_id) if emp and emp.department_id else None
        print(f"{username:<11}{user.real_name or '':<8}"
              f"{(dept.name if dept else '—'):<10}{emp.emp_no if emp else '—'}")

    admin = db.query(User).filter(User.username == "admin").first()
    if admin:
        print(f"\n  {admin.username:<9}{admin.real_name or '':<8}（系统管理员，不纳入业务部门）")

    print("\n" + "=" * 72)
    print("全部部门")
    print("=" * 72)
    for dept in db.query(RmbDepartment).order_by(RmbDepartment.code).all():
        emps = db.query(RmbEmployee).filter(RmbEmployee.department_id == dept.id).all()
        names = "、".join(f"{e.name}({e.emp_no})" for e in emps) or "（无）"
        print(f"  {dept.code} {dept.name:<10} {names}")


def run():
    db = SessionLocal()
    try:
        print("[1/3] 创建对口部门 ...")
        dept_map = ensure_departments(db)

        print("[2/3] 调整员工档案部门 ...")
        employees = adjust_employees(db, dept_map)

        print("[3/3] 同步用户显示名为人名 ...")
        sync_user_names(db, employees)

        db.commit()
        print("\n完成。")
        print_summary(db)
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(run())
