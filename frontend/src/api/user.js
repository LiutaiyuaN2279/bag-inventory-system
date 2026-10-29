import request from '@/utils/request'

/** 用户管理（RBAC） */
export const userApi = {
  // params: { page, page_size, keyword, status }
  // 返回 { list, total }；每行含 id/username/real_name/status/created_at/roles(角色code数组)/role_ids
  list: (params) => request({ url: '/users', method: 'get', params }),
  // data: { username, password, real_name, status, role_ids }
  create: (data) => request({ url: '/users', method: 'post', data }),
  // data: { real_name, status, role_ids }
  update: (id, data) => request({ url: `/users/${id}`, method: 'put', data }),
  // data: { password }
  resetPassword: (id, data) => request({ url: `/users/${id}/password`, method: 'put', data }),
  remove: (id) => request({ url: `/users/${id}`, method: 'delete' }),
  // 用户级权限覆盖（在角色权限之上「额外授予 / 明确禁用」，仅对本人生效）
  // 返回 { user_id, username, role_perm_ids, grant_ids, deny_ids, grant_codes, deny_codes, effective_ids }
  permissionsOf: (id) => request({ url: `/users/${id}/permissions`, method: 'get' }),
  // data: { items: [{ perm_id, effect: 'grant' | 'deny' }] }，全量覆盖该用户的覆盖项
  setPermissions: (id, data) => request({ url: `/users/${id}/permissions`, method: 'put', data }),
  // 批量：{ ids, action: 'enable' | 'disable' | 'delete' }（admin 与当前登录用户受保护）
  batch: (data) => request({ url: '/users/batch', method: 'post', data })
}

/** 角色与权限管理（RBAC） */
export const roleApi = {
  // params: { page, page_size, keyword }
  // 返回 { list, total }；每行含 id/role_code/role_name/remark/user_count/perm_count
  list: (params) => request({ url: '/roles', method: 'get', params }),
  // 返回数组：[{ id, perm_code, perm_name, module }]
  permissions: () => request({ url: '/roles/permissions', method: 'get' }),
  // data: { role_code, role_name, remark }
  create: (data) => request({ url: '/roles', method: 'post', data }),
  // data: { role_code, role_name, remark }
  update: (id, data) => request({ url: `/roles/${id}`, method: 'put', data }),
  remove: (id) => request({ url: `/roles/${id}`, method: 'delete' }),
  // data: { perm_ids: [...] }
  setPermissions: (id, data) => request({ url: `/roles/${id}/permissions`, method: 'put', data }),
  // 契约补充（冻结契约未定义）：读取角色已有权限，用于「配置权限」弹窗默认勾选。
  // 页面侧优先使用列表行自带的 perm_ids，仅在缺失时才回退到本接口。
  permissionsOf: (id) => request({ url: `/roles/${id}/permissions`, method: 'get' }),
  // 批量：{ ids, action: 'delete' }（内置角色与被引用角色会被拒绝）
  batch: (data) => request({ url: '/roles/batch', method: 'post', data })
}
