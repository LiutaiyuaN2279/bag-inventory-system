import request from '@/utils/request'

export const qualityApi = {
  iqcList: (params) => request({ url: '/iqc', method: 'get', params }),
  iqcDetail: (id) => request({ url: `/iqc/${id}`, method: 'get' }),
  iqcCreate: (data) => request({ url: '/iqc', method: 'post', data }),
  iqcCheck: (id, data) => request({ url: `/iqc/${id}/check`, method: 'post', data }),
  fqcList: (params) => request({ url: '/fqc', method: 'get', params }),
  fqcCreate: (data) => request({ url: '/fqc', method: 'post', data }),
  fqcUpdate: (id, data) => request({ url: `/fqc/${id}`, method: 'put', data }),
  // 批量（IQC / FQC 是两张表、两套 id 空间，故分两个端点）
  // { ids, action: 'approve' | 'reject', reason }
  iqcBatch: (data) => request({ url: '/iqc/batch', method: 'post', data }),
  fqcBatch: (data) => request({ url: '/fqc/batch', method: 'post', data })
}
