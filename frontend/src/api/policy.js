import request from '@/utils/request'

/** 制度上传解析 / AI 解析测试耗时较长，单独放宽超时 */
const AI_TIMEOUT = 180000

/** 上传一律走 multipart/form-data，字段名 file + 表单字段 */
const upload = (url, formData) => request({
  url, method: 'post', data: formData, timeout: AI_TIMEOUT,
  headers: { 'Content-Type': 'multipart/form-data' }
})

/**
 * 制度与参数管理接口（全部要求 reimburse:policy:manage 权限）
 *
 * 制度文件、检查规则、阈值参数三者必须同步变更——页面对此有醒目提示。
 */
export const policyApi = {
  /** 制度列表：{active, list} */
  list: () => request({ url: '/rmb-policy', method: 'get' }),

  /** 上传制度文件（docx/pdf）：file + policy_no + policy_name + effective_date + set_active */
  upload: (formData) => upload('/rmb-policy/upload', formData),

  /** 设为当前生效（同一时间只能一个生效） */
  activate: (id) => request({ url: `/rmb-policy/${id}/activate`, method: 'post' }),

  /** 对当前生效制度调大模型解析，返回章节要点 → {result} */
  parseTest: () => request({ url: '/rmb-policy/parse-test', method: 'post', timeout: AI_TIMEOUT }),

  /** 检查规则清单（R01～R14） */
  rules: () => request({ url: '/rmb-policy/rules', method: 'get' }),

  /** 修改单条规则 */
  ruleUpdate: (id, data) => request({ url: `/rmb-policy/rules/${id}`, method: 'put', data }),

  /** 系统参数 + 城市等级 + 节假日 */
  params: () => request({ url: '/rmb-policy/params', method: 'get' }),

  /** 修改单个系统参数：{key, value} */
  paramUpdate: (data) => request({ url: '/rmb-policy/params', method: 'put', data }),

  /** 城市等级表：增删改查 */
  cityLevels: () => request({ url: '/rmb-policy/city-levels', method: 'get' }),
  cityLevelCreate: (data) => request({ url: '/rmb-policy/city-levels', method: 'post', data }),
  cityLevelUpdate: (key, data) => request({ url: `/rmb-policy/city-levels/${encodeURIComponent(key)}`, method: 'put', data }),
  cityLevelRemove: (key) => request({ url: `/rmb-policy/city-levels/${encodeURIComponent(key)}`, method: 'delete' }),

  /** 节假日表：增删改查 */
  holidays: () => request({ url: '/rmb-policy/holidays', method: 'get' }),
  holidayCreate: (data) => request({ url: '/rmb-policy/holidays', method: 'post', data }),
  holidayUpdate: (key, data) => request({ url: `/rmb-policy/holidays/${encodeURIComponent(key)}`, method: 'put', data }),
  holidayRemove: (key) => request({ url: `/rmb-policy/holidays/${encodeURIComponent(key)}`, method: 'delete' })
}
