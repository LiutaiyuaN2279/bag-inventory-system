import request from '@/utils/request'

export const outsourceApi = {
  list: (params) => request({ url: '/outsource-orders', method: 'get', params }),
  detail: (id) => request({ url: `/outsource-orders/${id}`, method: 'get' }),
  create: (data) => request({ url: '/outsource-orders', method: 'post', data }),
  update: (id, data) => request({ url: `/outsource-orders/${id}`, method: 'put', data }),
  issue: (id) => request({ url: `/outsource-orders/${id}/issue`, method: 'post' }),
  receive: (id, data) => request({ url: `/outsource-orders/${id}/receive`, method: 'post', data }),
  // 批量：{ ids, action: 'issue' | 'receive' }
  batch: (data) => request({ url: '/outsource-orders/batch', method: 'post', data })
}
