import { useRoute } from 'vue-router'

/**
 * 把路由 query 中的字段同步到列表筛选 query 对象。
 * 用途：从首页「我的待办」点击跳转后，自动带上状态筛选（如 ?status=草稿），
 *       列表页挂载时据此预先填好筛选条件，fetchList 即按筛选加载。
 * 特性：一次性、URL 驱动，不写入本地存储；无 query 时不影响页面默认行为。
 */
export function applyRouteFilter(query, keys = ['status']) {
  const route = useRoute()
  for (const k of keys) {
    const v = route.query[k]
    if (v !== undefined && v !== null && v !== '') {
      query[k] = Array.isArray(v) ? v[0] : v
    }
  }
}
