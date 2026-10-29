"""建立分角色职权并绑定用户（幂等）。遵循最小权限，杜绝越权。"""
import sys
sys.path.insert(0, '.')
from app.core.database import SessionLocal
from app.models.rbac import Permission, Role, User, UserPermission, UserRole, RolePermission

db = SessionLocal()

# 用户管理 / 角色权限管理的权限码（补充定义，幂等）：先落库，再由下方 admin 全量授权覆盖
NEW_PERMISSIONS = [
    ('system:user:list', '用户-查看', 'system'),
    ('system:user:add', '用户-新增', 'system'),
    ('system:user:edit', '用户-编辑', 'system'),
    ('system:user:delete', '用户-删除', 'system'),
    ('system:user:perm', '用户-配置权限', 'system'),
    ('system:role:list', '角色-查看', 'system'),
    ('system:role:add', '角色-新增', 'system'),
    ('system:role:edit', '角色-编辑', 'system'),
    ('system:role:delete', '角色-删除', 'system'),
    ('inventory:transfer:list', '仓库调拨-查看', 'inventory'),
    ('inventory:transfer:add', '仓库调拨-新增', 'inventory'),
    ('inventory:transfer:edit', '仓库调拨-编辑', 'inventory'),
    ('inventory:transfer:approve', '仓库调拨-审核', 'inventory'),
    ('inventory:transfer:delete', '仓库调拨-作废', 'inventory'),
    ('ai:ocr:list', 'AI单据识别-查看', 'ai'),
    ('ai:ocr:recognize', 'AI单据识别-上传识别', 'ai'),
    ('ai:ocr:import', 'AI单据识别-导入', 'ai'),
    ('ai:ocr:delete', 'AI单据识别-删除', 'ai'),
]
for _code, _name, _module in NEW_PERMISSIONS:
    if not db.query(Permission).filter(Permission.perm_code == _code).first():
        db.add(Permission(perm_code=_code, perm_name=_name, module=_module))
        print('新增权限:', _code)
db.flush()

PERMS = {p.perm_code: p for p in db.query(Permission).all()}
ALL_CODES = list(PERMS.keys())

def codes(*patterns):
    """支持精确码与 'module:*' 通配。"""
    res = []
    for pat in patterns:
        if pat.endswith(':*'):
            pre = pat[:-1]
            res += [c for c in ALL_CODES if c.startswith(pre)]
        elif pat in PERMS:
            res.append(pat)
    return res

# 角色 -> 权限码集合（最小权限设计）
ROLE_PERMS = {
    # 系统管理员：全部权限
    'admin': ALL_CODES,
    # 运营主管：全局只读 + 审核权 + 报表/看板，不做业务录入；操作日志仅管理员可见
    'manager': codes(
        'basic:material:list', 'basic:supplier:list', 'basic:warehouse:list',
        'bom:view', 'dashboard:view', 'inventory:view', 'inventory:alert',
        'outsource:list', 'qc:view', 'report:view',
        'purchase:requisition:list', 'purchase:order:list',
        'purchase:arrival:list', 'purchase:return:list',
        'purchase:requisition:approve', 'purchase:order:approve',
        'purchase:arrival:approve', 'purchase:return:approve', 'bom:approve',
        'ai:ocr:list',
    ),
    # 采购员：采购业务全流程（制单），引用主数据只读，不审核、不碰库存/质检
    'buyer': codes(
        'purchase:requisition:list', 'purchase:requisition:add', 'purchase:requisition:edit',
        'purchase:order:list', 'purchase:order:add', 'purchase:order:edit',
        'purchase:arrival:list', 'purchase:return:list',
        'basic:material:list', 'basic:supplier:list', 'basic:warehouse:list',
        'inventory:view', 'bom:view', 'dashboard:view',
        'ai:ocr:list', 'ai:ocr:recognize', 'ai:ocr:import',
    ),
    # 仓管员：库存 + 收发货（到货验收/退货出库）+ 外发收发料
    'keeper': codes(
        'inventory:view', 'inventory:adjust', 'inventory:stocktake', 'inventory:alert',
        'inventory:transfer:add', 'inventory:transfer:edit',
        'inventory:transfer:approve', 'inventory:transfer:delete',
        'purchase:arrival:list', 'purchase:arrival:add', 'purchase:arrival:approve',
        'purchase:return:list', 'purchase:return:add', 'purchase:return:approve',
        'outsource:list', 'outsource:edit',
        'basic:material:list', 'basic:supplier:list', 'basic:warehouse:list', 'dashboard:view',
        'ai:ocr:list', 'ai:ocr:recognize', 'ai:ocr:import',
    ),
    # 质检员：质检录入与查看，只读相关单据
    'qc': codes(
        'qc:view', 'qc:edit',
        'purchase:arrival:list', 'outsource:list', 'basic:material:list', 'basic:supplier:list', 'dashboard:view',
        'ai:ocr:list',
    ),
}

ROLE_NAMES = {
    'admin': '系统管理员', 'manager': '运营主管',
    'buyer': '采购员', 'keeper': '仓管员', 'qc': '质检员',
}

def set_role_perms(role, perm_codes):
    db.query(RolePermission).filter(RolePermission.role_id == role.id).delete()
    seen = set()
    for c in perm_codes:
        if c in seen or c not in PERMS:
            continue
        seen.add(c)
        db.add(RolePermission(role_id=role.id, permission_id=PERMS[c].id))

for role_code, perm_codes in ROLE_PERMS.items():
    role = db.query(Role).filter(Role.role_code == role_code).first()
    if not role:
        role = Role(role_code=role_code, role_name=ROLE_NAMES[role_code])
        db.add(role)
        db.flush()
        print('创建角色:', role_code)
    else:
        role.role_name = ROLE_NAMES[role_code]
    set_role_perms(role, perm_codes)

# 用户 -> 角色（一一对应，移除非管理员的 admin 越权）
USER_ROLE = {'admin': 'admin', 'manager': 'manager', 'buyer': 'buyer', 'keeper': 'keeper', 'qc': 'qc'}
role_by_code = {r.role_code: r for r in db.query(Role).all()}
for username, role_code in USER_ROLE.items():
    user = db.query(User).filter(User.username == username).first()
    if not user:
        continue
    want_id = role_by_code[role_code].id
    db.query(UserRole).filter(UserRole.user_id == user.id).delete()
    db.add(UserRole(user_id=user.id, role_id=want_id))
    print(f'绑定用户 {username} -> 角色 {role_code}')

db.commit()
print('职权配置完成。各角色权限数：')
for r in db.query(Role).all():
    print(f'  {r.role_code}({r.role_name}): {len(r.permissions)} 项')

# ---------------------------------------------------------------
# 演示用「用户级权限覆盖」：同一角色下个别用户的权限差异
# 有效权限 = (角色权限 ∪ grant) − deny，deny 优先级最高
# ---------------------------------------------------------------
ALL_PERMS = {p.perm_code: p.id for p in db.query(Permission).all()}
USER_OVERRIDES = {
    # 质检员：角色只有「AI单据识别-查看」，额外授予上传识别（质检单据自助录入）
    'qc': [('ai:ocr:recognize', 'grant')],
    # 采购员：角色本可导入，但收回该用户的导入权，识别结果须由主管复核后导入
    'buyer': [('ai:ocr:import', 'deny')],
}
for username, items in USER_OVERRIDES.items():
    user = db.query(User).filter(User.username == username).first()
    if not user:
        continue
    db.query(UserPermission).filter(UserPermission.user_id == user.id).delete()
    for code, effect in items:
        pid = ALL_PERMS.get(code)
        if pid is None:
            print('  ! 权限码不存在，跳过:', code)
            continue
        db.add(UserPermission(user_id=user.id, permission_id=pid, effect=effect))
    db.commit()
    print(f'用户级权限覆盖 {username}: ' + ', '.join(
        f'{"+" if e == "grant" else "-"}{c}' for c, e in items))

