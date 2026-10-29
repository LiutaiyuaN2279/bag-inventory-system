import request from '@/utils/request'

/** 请购单 */
export const requisitionApi = {
  list: (params) => request({ url: '/purchase-requisitions', method: 'get', params }),
  detail: (id) => request({ url: `/purchase-requisitions/${id}`, method: 'get' }),
  create: (data) => request({ url: '/purchase-requisitions', method: 'post', data }),
  update: (id, data) => request({ url: `/purchase-requisitions/${id}`, method: 'put', data }),
  approve: (id) => request({ url: `/purchase-requisitions/${id}/approve`, method: 'post' }),
  reject: (id, reason) => request({ url: `/purchase-requisitions/${id}/reject`, method: 'post', data: { reason } }),
  // 批量：{ ids, action: 'approve' | 'reject' | 'void', reason }
  batch: (data) => request({ url: '/purchase-requisitions/batch', method: 'post', data })
}

/** 采购订单 */
export const orderApi = {
  list: (params) => request({ url: '/purchase-orders', method: 'get', params }),
  detail: (id) => request({ url: `/purchase-orders/${id}`, method: 'get' }),
  create: (data) => request({ url: '/purchase-orders', method: 'post', data }),
  update: (id, data) => request({ url: `/purchase-orders/${id}`, method: 'put', data }),
  approve: (id) => request({ url: `/purchase-orders/${id}/approve`, method: 'post' }),
  reject: (id, reason) => request({ url: `/purchase-orders/${id}/reject`, method: 'post', data: { reason } }),
  void: (id) => request({ url: `/purchase-orders/${id}/void`, method: 'post' }),
  unvoid: (id) => request({ url: `/purchase-orders/${id}/unvoid`, method: 'post' }),
  // 批量：{ ids, action: 'approve' | 'reject' | 'void' | 'unvoid', reason }
  batch: (data) => request({ url: '/purchase-orders/batch', method: 'post', data })
}

/** 到货入库 */
export const arrivalApi = {
  list: (params) => request({ url: '/purchase-arrivals', method: 'get', params }),
  detail: (id) => request({ url: `/purchase-arrivals/${id}`, method: 'get' }),
  create: (data) => request({ url: '/purchase-arrivals', method: 'post', data }),
  approve: (id) => request({ url: `/purchase-arrivals/${id}/approve`, method: 'post' }),
  reject: (id, reason) => request({ url: `/purchase-arrivals/${id}/reject`, method: 'post', data: { reason } }),
  // 批量：{ ids, action: 'approve' | 'reject', reason }
  batch: (data) => request({ url: '/purchase-arrivals/batch', method: 'post', data })
}

/** 采购退货 */
export const returnApi = {
  list: (params) => request({ url: '/purchase-returns', method: 'get', params }),
  detail: (id) => request({ url: `/purchase-returns/${id}`, method: 'get' }),
  create: (data) => request({ url: '/purchase-returns', method: 'post', data }),
  approve: (id) => request({ url: `/purchase-returns/${id}/approve`, method: 'post' }),
  reject: (id, reason) => request({ url: `/purchase-returns/${id}/reject`, method: 'post', data: { reason } }),
  // 批量：{ ids, action: 'approve' | 'reject', reason }
  batch: (data) => request({ url: '/purchase-returns/batch', method: 'post', data })
}
