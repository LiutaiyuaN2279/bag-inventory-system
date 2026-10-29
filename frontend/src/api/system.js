import request from '@/utils/request'

export const systemApi = {
  logs: (params) => request({ url: '/operation-logs', method: 'get', params }),
  logStats: (params) => request({ url: '/operation-logs/stats', method: 'get', params }),
  logDetail: (id) => request({ url: `/operation-logs/${id}`, method: 'get' })
}

/** 导入一律走 multipart/form-data，字段名固定为 file */
const upload = (url, formData) => request({
  url, method: 'post', data: formData,
  headers: { 'Content-Type': 'multipart/form-data' }
})

export const excelApi = {
  importMaterials: (formData) => upload('/import/materials', formData),
  importSuppliers: (formData) => upload('/import/suppliers', formData),
  importInventory: (formData) => upload('/import/inventory', formData)
}
