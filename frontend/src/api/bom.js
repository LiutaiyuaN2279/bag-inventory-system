import request from '@/utils/request'

export const bomApi = {
  list: (params) => request({ url: '/bom', method: 'get', params }),
  detail: (id) => request({ url: `/bom/${id}`, method: 'get' }),
  create: (data) => request({ url: '/bom', method: 'post', data }),
  update: (id, data) => request({ url: `/bom/${id}`, method: 'put', data }),
  activate: (id) => request({ url: `/bom/${id}/activate`, method: 'post' }),
  reject: (id, reason) => request({ url: `/bom/${id}/reject`, method: 'post', data: { reason } }),
  calculate: (data) => request({ url: '/bom/calculate', method: 'post', data }),
  // 把算料结果一键生成请购单（净需求 = 需求量 − 现有库存）
  toRequisition: (data) => request({ url: '/bom/to-requisition', method: 'post', data }),
  // 批量：{ ids, action: 'activate' | 'reject', reason }
  batch: (data) => request({ url: '/bom/batch', method: 'post', data })
}
