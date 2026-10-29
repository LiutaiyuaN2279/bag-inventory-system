import request from '@/utils/request'

/** 物料管理 */
export const materialApi = {
  list: (params) => request({ url: '/materials', method: 'get', params }),
  suggestCode: (params) => request({ url: '/materials/suggest-code', method: 'get', params }),
  create: (data) => request({ url: '/materials', method: 'post', data }),
  update: (id, data) => request({ url: `/materials/${id}`, method: 'put', data }),
  remove: (id) => request({ url: `/materials/${id}`, method: 'delete' }),
  batch: (data) => request({ url: '/materials/batch', method: 'post', data })
}

/** 供应商管理 */
export const supplierApi = {
  list: (params) => request({ url: '/suppliers', method: 'get', params }),
  suggestCode: () => request({ url: '/suppliers/suggest-code', method: 'get' }),
  create: (data) => request({ url: '/suppliers', method: 'post', data }),
  update: (id, data) => request({ url: `/suppliers/${id}`, method: 'put', data }),
  remove: (id) => request({ url: `/suppliers/${id}`, method: 'delete' }),
  batch: (data) => request({ url: '/suppliers/batch', method: 'post', data })
}

/** 仓库管理 */
export const warehouseApi = {
  list: (params) => request({ url: '/warehouses', method: 'get', params }),
  all: () => request({ url: '/warehouses/all', method: 'get' }),
  suggestCode: () => request({ url: '/warehouses/suggest-code', method: 'get' }),
  create: (data) => request({ url: '/warehouses', method: 'post', data }),
  update: (id, data) => request({ url: `/warehouses/${id}`, method: 'put', data }),
  remove: (id) => request({ url: `/warehouses/${id}`, method: 'delete' }),
  batch: (data) => request({ url: '/warehouses/batch', method: 'post', data })
}
