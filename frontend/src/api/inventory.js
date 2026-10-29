import request from '@/utils/request'

/** 库存查询 / 流水 / 其他出入库 */
export const inventoryApi = {
  list: (params) => request({ url: '/inventory', method: 'get', params }),
  transactions: (params) => request({ url: '/inventory/transactions', method: 'get', params }),
  adjust: (data) => request({ url: '/inventory/adjust', method: 'post', data }),
  alerts: (params) => request({ url: '/inventory/alerts', method: 'get', params }),
  // 低库存一键补货：按「安全库存 − 现存数量」生成草稿请购单
  restock: (data) => request({ url: '/inventory/alerts/restock', method: 'post', data })
}

/** 盘点 */
export const stocktakeApi = {
  list: (params) => request({ url: '/stocktakes', method: 'get', params }),
  detail: (id) => request({ url: `/stocktakes/${id}`, method: 'get' }),
  create: (data) => request({ url: '/stocktakes', method: 'post', data }),
  count: (id, data) => request({ url: `/stocktakes/${id}/count`, method: 'post', data }),
  approve: (id) => request({ url: `/stocktakes/${id}/approve`, method: 'post' }),
  reject: (id, reason) => request({ url: `/stocktakes/${id}/reject`, method: 'post', data: { reason } }),
  // 批量：{ ids, action: 'approve' | 'reject', reason }
  batch: (data) => request({ url: '/stocktakes/batch', method: 'post', data })
}
