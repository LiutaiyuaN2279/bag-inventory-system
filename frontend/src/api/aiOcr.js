import request from '@/utils/request'

/** AI 单据识别（OCR） */
export const aiOcrApi = {
  /** 识别引擎信息（当前 provider / 模型 / 是否演示模式） */
  info: () => request({ url: '/ai-ocr/info', method: 'get' }),
  /** 测试识别引擎连通性 */
  test: () => request({ url: '/ai-ocr/test', method: 'post' }),
  /** 大模型配置：档案列表 + 引擎预设 + 当前生效来源（仅 admin 有权限） */
  configs: () => request({ url: '/ai-ocr/model-configs', method: 'get' }),
  /** 新增模型档案（第一条自动启用） */
  createConfig: (data) => request({ url: '/ai-ocr/model-configs', method: 'post', data }),
  /** 修改模型档案 */
  updateConfig: (id, data) => request({ url: `/ai-ocr/model-configs/${id}`, method: 'put', data }),
  /** 启用档案：即时生效，无需重启后端 */
  activateConfig: (id) => request({ url: `/ai-ocr/model-configs/${id}/activate`, method: 'post' }),
  /** 测试某份档案的连通性（不必先启用，配错也不影响线上识别） */
  testConfig: (id) => request({ url: `/ai-ocr/model-configs/${id}/test`, method: 'post' }),
  /** 删除档案（删的若是启用项，识别自动回落到 .env 配置） */
  removeConfig: (id) => request({ url: `/ai-ocr/model-configs/${id}`, method: 'delete' }),
  /** 识别记录列表 */
  records: (params) => request({ url: '/ai-ocr/records', method: 'get', params }),
  /** 识别记录详情（含明细） */
  detail: (id) => request({ url: `/ai-ocr/records/${id}`, method: 'get' }),
  /**
   * 识别时的原照片（二进制）。
   * 走 blob 是因为该接口需要 Bearer 头，`<img src>` 带不了自定义请求头；
   * request.js 对 responseType=blob 的响应直通，不套 {code,message,data} 外壳。
   */
  image: (id) => request({ url: `/ai-ocr/records/${id}/image`, method: 'get', responseType: 'blob' }),
  /** 上传图片识别（视觉模型耗时较长，单独放宽超时） */
  recognize: (formData) => request({
    url: '/ai-ocr/recognize', method: 'post', data: formData, timeout: 120000,
    headers: { 'Content-Type': 'multipart/form-data' }
  }),
  /** 确认导入（可生成采购到货单） */
  importRecord: (id, data) => request({ url: `/ai-ocr/records/${id}/import`, method: 'post', data }),
  /** 删除识别记录 */
  remove: (id) => request({ url: `/ai-ocr/records/${id}`, method: 'delete' }),
  /** 批量删除：{ ids, action: 'delete' }；已生成到货单的记录会被后端逐条拒绝 */
  batch: (data) => request({ url: '/ai-ocr/batch', method: 'post', data })
}