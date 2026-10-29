/** 权限模块中文名（后端 module 字段 → 展示名），未命中时回退原文。 */
export const MODULE_LABELS = {
  dashboard: '首页看板',
  'basic-data': '基础数据',
  procurement: '采购管理',
  purchase: '采购管理',
  inventory: '库存管理',
  bom: 'BOM 管理',
  production: '生产管理',
  outsource: '生产管理',
  quality: '质量管理',
  qc: '质量管理',
  reports: '报表中心',
  report: '报表中心',
  system: '系统管理',
  ai: 'AI 单据识别'
}

/**
 * 把权限数组按 module 分组为「模块父节点 + 权限叶子节点」，供 el-tree 使用。
 * @param {Array<{id:number,perm_code:string,perm_name:string,module?:string}>} perms
 * @returns {{ nodes: Array, leaves: Set<number> }} nodes 为树数据；leaves 为真实权限（叶子）id 集合
 */
export function buildPermTree(perms) {
  const groups = new Map()
  ;(perms || []).forEach((p) => {
    const key = p.module || '其他'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(p)
  })
  const leaves = new Set()
  const nodes = []
  for (const [mod, items] of groups) {
    const children = items.map((p) => {
      leaves.add(p.id)
      return { id: p.id, label: `${p.perm_name}（${p.perm_code}）` }
    })
    nodes.push({
      id: `group:${mod}`,
      label: `${MODULE_LABELS[mod] || mod} · ${children.length} 项`,
      children
    })
  }
  return { nodes, leaves }
}
