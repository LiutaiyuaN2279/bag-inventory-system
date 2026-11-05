"""新合成库的演示角色初始化。无顶层写库；既有角色、账号和定制授权不覆盖。"""
from app.models.rbac import Permission, Role, RolePermission, User, UserPermission, UserRole

PERMISSION_CODES = ('ai:ocr:config', 'ai:ocr:delete', 'ai:ocr:import', 'ai:ocr:list', 'ai:ocr:recognize', 'audit:view', 'basic:material:add', 'basic:material:delete', 'basic:material:edit', 'basic:material:list', 'basic:supplier:add', 'basic:supplier:delete', 'basic:supplier:edit', 'basic:supplier:list', 'basic:warehouse:add', 'basic:warehouse:delete', 'basic:warehouse:edit', 'basic:warehouse:list', 'bom:approve', 'bom:edit', 'bom:view', 'dashboard:view', 'inventory:adjust', 'inventory:alert', 'inventory:stocktake', 'inventory:transfer:add', 'inventory:transfer:approve', 'inventory:transfer:delete', 'inventory:transfer:edit', 'inventory:transfer:list', 'inventory:view', 'outsource:edit', 'outsource:list', 'purchase:arrival:add', 'purchase:arrival:approve', 'purchase:arrival:list', 'purchase:order:add', 'purchase:order:approve', 'purchase:order:edit', 'purchase:order:list', 'purchase:requisition:add', 'purchase:requisition:approve', 'purchase:requisition:edit', 'purchase:requisition:list', 'purchase:return:add', 'purchase:return:approve', 'purchase:return:list', 'qc:edit', 'qc:view', 'reimburse:bill:add', 'reimburse:bill:approve', 'reimburse:bill:delete', 'reimburse:bill:edit', 'reimburse:bill:list', 'reimburse:check:override', 'reimburse:check:run', 'reimburse:policy:manage', 'reimburse:voucher:list', 'reimburse:voucher:make', 'reimburse:voucher:review', 'report:view', 'system:log', 'system:role:add', 'system:role:delete', 'system:role:edit', 'system:role:list', 'system:user:add', 'system:user:delete', 'system:user:edit', 'system:user:list', 'system:user:perm')

ROLE_PATTERNS = {'manager': ['basic:material:list', 'basic:supplier:list', 'basic:warehouse:list', 'bom:view', 'dashboard:view', 'inventory:view', 'inventory:alert', 'outsource:list', 'qc:view', 'report:view', 'purchase:requisition:list', 'purchase:order:list', 'purchase:arrival:list', 'purchase:return:list', 'purchase:requisition:approve', 'purchase:order:approve', 'purchase:return:approve', 'bom:approve', 'ai:ocr:list'], 'buyer': ['purchase:requisition:list', 'purchase:requisition:add', 'purchase:requisition:edit', 'purchase:order:list', 'purchase:order:add', 'purchase:order:edit', 'purchase:arrival:list', 'purchase:return:list', 'basic:material:list', 'basic:supplier:list', 'basic:warehouse:list', 'inventory:view', 'bom:view', 'dashboard:view', 'ai:ocr:list', 'ai:ocr:recognize', 'ai:ocr:import'], 'keeper': ['inventory:view', 'inventory:adjust', 'inventory:stocktake', 'inventory:alert', 'inventory:transfer:add', 'inventory:transfer:edit', 'inventory:transfer:approve', 'inventory:transfer:delete', 'purchase:arrival:list', 'purchase:arrival:add', 'purchase:arrival:approve', 'purchase:return:list', 'purchase:return:add', 'purchase:return:approve', 'outsource:list', 'outsource:edit', 'basic:material:list', 'basic:supplier:list', 'basic:warehouse:list', 'dashboard:view', 'ai:ocr:list', 'ai:ocr:recognize', 'ai:ocr:import', 'purchase:order:list'], 'qc': ['qc:view', 'qc:edit', 'purchase:arrival:list', 'outsource:list', 'basic:material:list', 'basic:supplier:list', 'dashboard:view', 'ai:ocr:list']}

ROLE_NAMES = {'admin': '系统管理员', 'manager': '运营主管', 'buyer': '采购员', 'keeper': '仓管员', 'qc': '质检员'}

def initialize_demo_roles(db, hash_password):
    """调用方负责提交；仅新建角色获得默认权，仅新建账号获得默认绑定。"""
    permissions = {p.perm_code: p for p in db.query(Permission).all()}
    for code in PERMISSION_CODES:
        if code not in permissions:
            permission = Permission(perm_code=code, perm_name=code, module=code.split(":")[0])
            db.add(permission)
            db.flush()
            permissions[code] = permission
    roles = {r.role_code: r for r in db.query(Role).all()}
    for code, name in ROLE_NAMES.items():
        if code in roles:
            continue
        role = Role(role_code=code, role_name=name)
        db.add(role)
        db.flush()
        roles[code] = role
        wanted = set(permissions) if code == "admin" else {
            candidate for candidate in permissions for pattern in ROLE_PATTERNS[code]
            if candidate == pattern or (pattern.endswith(":*") and candidate.startswith(pattern[:-1]))
        }
        for permission in sorted(wanted):
            db.add(RolePermission(role_id=role.id, permission_id=permissions[permission].id))
    for username, name in ROLE_NAMES.items():
        if db.query(User).filter_by(username=username).first():
            continue
        user = User(username=username, real_name=name, password_hash=hash_password("admin123"), status=True)
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=roles[username].id))
        overrides = {"buyer": [("ai:ocr:import", "deny")], "qc": [("ai:ocr:recognize", "grant")]}
        for permission, effect in overrides.get(username, []):
            db.add(UserPermission(user_id=user.id, permission_id=permissions[permission].id, effect=effect))
