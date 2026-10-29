"""一键重置演示数据。

用法（必须在 backend 目录下执行）：
    .venv\\Scripts\\python.exe scripts\\reset_demo_data.py

作用：删除现有 SQLite 数据库，然后依次重建表结构、写入演示数据、配置角色权限，
把系统恢复到「干净且数据饱满」的初始状态。演示前跑一次即可。

注意：会清空所有业务数据，请勿在有真实数据的环境使用。
"""
import os
import sqlite3
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app.core.config import settings  # noqa: E402

# 按依赖顺序执行的脚本；不存在的会被跳过（例如尚未引入的升级脚本）
#
# 顺序不可随意调整：
#   1) init_db.py        建表 + 演示账号 + 基础权限/示例主数据（唯一创建 users 的地方）
#   2) upgrade_db.py     追加采购/库存/BOM 权限码，且用 scalar_one() 硬依赖 M-FB-001
#                        等 init_db.py 创建的物料 → 必须在 init_db.py 之后、且此时
#                        物料表还没有被 seed_data.py 灌满
#   3) upgrade_db_v2/v3  追加外发/质检/报表权限码与「驳回原因」列
#   3b) upgrade_db_userperm/v4  用户级权限覆盖表；AI 识别记录的原图归档列
#   4) seed_data.py      灌入业务演示数据（物料/供应商/BOM/库存/采购/质检/AI识别/日志）
#   5) setup_roles.py    配置角色权限并绑定用户 → 必须在所有权限码落库之后，
#                        否则 codes() 会静默丢弃尚未存在的权限码，导致角色缺权
#   6) 以下脚本一律放在 setup_roles.py 之后：setup_roles.py 会先 delete() 再重建
#      各角色权限，任何「增量授权」放在它前面都会被整段抹掉：
#        upgrade_db_v6_reimburse.py       16 张 rmb_* 表 + 报销权限码 + 科目/规则等
#                                         基础数据，并按 ROLE_GRANTS 给 admin / manager
#                                         / buyer 等角色授报销权限 → 该脚本自身要求
#                                         「请先运行 setup_roles.py」（角色不存在则跳过），
#                                         且它的授权属于增量授权，必须排在 setup_roles 之后
#        upgrade_db_v5.py                 智能审计权限码 + admin/manager 授权
#        import_policy_text.py            制度正文写入 rmb_policy（AI 合规判读的依据）
#        add_approval_roles.py            按制度第四条建 4 个分级审批角色
#        link_reimburse_users.py          系统用户 ↔ 报销员工档案关联；并创建 maker /
#                                        reviewer 两个角色 → 必须排在 add_reimburse_users
#                                        之前，否则该脚本绑定「财务制单=maker / 复核=
#                                        reviewer」时角色还不存在，会静默跳过
#        add_reimburse_users.py           报销专用账号（报销人 / 财务制单 / 复核 …）
#        reorganize_business_users.py     业务账号补真实姓名、归口部门
#        merge_reimburse_into_business.py 报销角色补只读业务权限
#        fix_finance_dept_permissions.py  财务岗位权限
#        fix_business_role_permissions.py 仓管/质检在报销模块的权限
#        fix_admin_reimburse_approve.py   管理员报销审批权限
#        align_permissions_by_dept_position.py 按「部门 × 职位」对齐并修职责分离
#        tune_visibility_by_dept_position.py   收敛账号的业务视野
#        restore_qc_permissions.py        恢复质检员被误禁的业务权限
#        remove_generic_maker_reviewer.py 删掉通用制单 / 复核账号
#        enable_workbench_for_all_roles.py 所有角色补首页看板权限
#   7) seed_rmb_scenarios.py  生成报销测试场景单据（依赖上面的账号与 rmb_* 表）
#   8) upgrade_db_v7_oplog.py 补 operation_logs 的审计列，并撤销除 admin 外所有角色
#      /用户级覆盖里的 system:log → 必须排在最后：任何在前面执行的授权脚本（尤其是
#      setup_roles.py 的 delete+重建、tune_visibility_by_dept_position.py 按视野补权限）
#      都会把日志权限重新发给管理岗，收权只有放在链路末尾才成立
#   9) upgrade_db_v8_ai_model.py 建模型档案表 ai_model_configs、补 ai:ocr:config 权限
#      （只给 admin）并插入默认 mock 档案。放在最后的原因：权限码必须在 setup_roles.py
#      之后创建，否则 admin 的「全部权限」快照里不会有它
SCRIPTS = [
    "init_db.py",
    "upgrade_db.py",
    "upgrade_db_v2.py",
    "upgrade_db_v3.py",
    "upgrade_db_transfer.py",
    "upgrade_db_userperm.py",
    "upgrade_db_v4.py",
    "seed_data.py",
    "setup_roles.py",
    "upgrade_db_v6_reimburse.py",
    "upgrade_db_v5.py",
    "import_policy_text.py",
    "add_approval_roles.py",
    "link_reimburse_users.py",
    "add_reimburse_users.py",
    "reorganize_business_users.py",
    "merge_reimburse_into_business.py",
    "fix_finance_dept_permissions.py",
    "fix_business_role_permissions.py",
    "fix_admin_reimburse_approve.py",
    "align_permissions_by_dept_position.py",
    "tune_visibility_by_dept_position.py",
    "restore_qc_permissions.py",
    "remove_generic_maker_reviewer.py",
    "enable_workbench_for_all_roles.py",
    "seed_rmb_scenarios.py",
    "upgrade_db_v7_oplog.py",
    "upgrade_db_v8_ai_model.py",
]


def resolve_db_path() -> str:
    """把 DATABASE_URL 解析成实际文件路径（相对路径按 backend 目录解析）。"""
    url = settings.DATABASE_URL
    if not url.startswith("sqlite"):
        raise SystemExit(f"当前仅支持 SQLite 演示库，实际为：{url}")
    path = url.split("///", 1)[-1]
    if not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)
    return os.path.normpath(path)


def remove_db(path: str) -> None:
    removed = []
    for suffix in ("", "-journal", "-wal", "-shm"):
        target = path + suffix
        if os.path.exists(target):
            try:
                os.remove(target)
            except PermissionError:
                raise SystemExit(
                    f"无法删除 {target}：数据库正在被占用。\n"
                    "请先停止正在运行的后端服务（uvicorn），再重新执行本脚本。"
                )
            removed.append(os.path.basename(target))
    if removed:
        print("已删除旧数据库文件：", ", ".join(removed))
    else:
        print("未发现旧数据库文件，将直接初始化。")


def run_script(name: str) -> None:
    script_path = os.path.join(BASE_DIR, "scripts", name)
    if not os.path.exists(script_path):
        print(f"跳过（脚本不存在）：{name}")
        return
    print(f"\n===== 执行 {name} =====")
    result = subprocess.run([sys.executable, script_path], cwd=BASE_DIR)
    if result.returncode != 0:
        raise SystemExit(f"{name} 执行失败（退出码 {result.returncode}），请检查上方输出。")


def remove_uploads() -> None:
    """清空 AI 识别归档的原图。

    数据库被删掉后旧照片就再没有记录指向它，留着只会持续占磁盘，
    所以重置时一并清掉（只清 ocr 子目录，不动其它上传物）。
    """
    root = os.path.abspath(settings.UPLOAD_DIR)
    ocr_dir = os.path.join(root, "ocr")
    if not os.path.isdir(ocr_dir):
        print("未发现归档原图目录，跳过。")
        return
    kept = 0
    for name in os.listdir(ocr_dir):
        target = os.path.join(ocr_dir, name)
        if not os.path.isfile(target):
            continue
        try:
            os.remove(target)
            kept += 1
        except OSError:
            pass
    print(f"已清理归档原图 {kept} 个（{ocr_dir}）")


def verify(db_path: str) -> None:
    """重置后自检：账号是否齐、权限是否全。历史上这里曾因漏跑 init_db.py 而产出无人可登录的空库。"""
    conn = sqlite3.connect(db_path)
    try:
        def count(sql: str, *args) -> int:
            return conn.execute(sql, args).fetchone()[0]

        users = [r[0] for r in conn.execute("select username from users order by id").fetchall()]
        perms = count("select count(*) from permissions")
        roles = conn.execute(
            "select r.role_code, count(rp.permission_id) from roles r "
            "left join role_permissions rp on rp.role_id = r.id group by r.id order by r.id"
        ).fetchall()

        print("\n重置结果自检：")
        print(f"  演示账号（{len(users)}）：{', '.join(users) if users else '（空！）'}")
        print(f"  权限码总数：{perms}")
        for code, n in roles:
            print(f"  {code:<8} 权限 {n} 项")

        missing = [u for u in ("admin", "manager", "buyer", "keeper", "qc") if u not in users]
        if missing:
            raise SystemExit(f"✗ 重置失败：缺少演示账号 {', '.join(missing)}，请检查 init_db.py 是否执行成功。")
        if perms < 50:
            raise SystemExit(
                f"✗ 重置失败：权限码只有 {perms} 条（应为 53 条），"
                "通常是 upgrade_db.py / upgrade_db_v2.py 未执行成功。"
            )
        print("  ✓ 自检通过")
    finally:
        conn.close()


def main() -> None:
    db_path = resolve_db_path()
    print(f"演示数据库位置：{db_path}")
    remove_db(db_path)
    remove_uploads()
    for name in SCRIPTS:
        run_script(name)

    verify(db_path)

    print("\n" + "=" * 52)
    print("演示数据重置完成 ✅")
    print("演示账号：admin / manager / buyer / keeper / qc / depthead /")
    print("          director / gm / finance / finmaker / sales / tech")
    print("统一口令：admin123")
    print("=" * 52)


if __name__ == "__main__":
    main()
