import request from '@/utils/request'

/**
 * 大模型相关接口单独放宽超时：票据识别（视觉模型）通常 20～120 秒，
 * request.js 的默认 15 秒会把它们全部截断成「请求超时」。
 */
const AI_TIMEOUT = 180000

/**
 * 差旅与业务招待费报销：报销单接口
 *
 * 后端统一响应 {code, message, data}，request.js 已拆包，这里拿到的就是 data。
 * 票据原件是二进制，走 responseType:'blob'（request.js 对该类型直通，不套壳）。
 */
export const reimburseApi = {
  /** 填单页下拉数据：费用类型 / 结算方式 / 部门 / 员工 / 城市等级 / 系统参数 / 服务器当前日期 */
  meta: () => request({ url: '/rmb-bills/meta', method: 'get' }),

  /** 报销工作台：KPI、待办、最近单据、本月费用构成（按数据范围与角色裁剪） */
  workbench: () => request({ url: '/rmb-bills/workbench', method: 'get' }),

  /** 上传票据并调大模型识别（multipart：file + 表单字段），返回 {token, warnings, invoice} */
  recognize: (formData) => request({
    url: '/rmb-bills/recognize', method: 'post', data: formData, timeout: AI_TIMEOUT,
    headers: { 'Content-Type': 'multipart/form-data' }
  }),

  /** AI 生成报销事由：传入已填写的报销信息与票据识别结果，返回 {reason, model} */
  suggestReason: (data) => request({
    url: '/rmb-bills/suggest-reason', method: 'post', data, timeout: AI_TIMEOUT
  }),

  /** 保存报销单（新建） */
  save: (data) => request({ url: '/rmb-bills/save', method: 'post', data }),

  /** 修改报销单（仅待判读 / 判读不合规 / 待确认可改，改后回到待判读） */
  update: (id, data) => request({ url: `/rmb-bills/${id}`, method: 'put', data }),

  /** 报销单详情（含票据、最近一次判读摘要、审计轨迹） */
  detail: (id) => request({ url: `/rmb-bills/${id}`, method: 'get' }),

  /** 报销单列表（分页 + 状态 / 费用类型 / 日期 / 关键字筛选） */
  list: (params) => request({ url: '/rmb-bills', method: 'get', params }),

  /** 作废报销单（须填原因） */
  void: (id, data) => request({ url: `/rmb-bills/${id}/void`, method: 'post', data }),

  /**
   * 审批报销单（制度第四条分级审批）。
   * data: { action: 'approve' | 'reject', comment }
   * 审批层级由单笔金额决定，层级不足会被后端拒绝。
   */
  approve: (id, data) => request({ url: `/rmb-bills/${id}/approve`, method: 'post', data }),

  /** 删除报销单（仅本人且待判读 / 判读不合规） */
  remove: (id) => request({ url: `/rmb-bills/${id}`, method: 'delete' }),

  /** 票据原件（二进制）：预览用，需带 Bearer 头，故走 blob 而不用 img src */
  invoiceFile: (id) => request({ url: `/rmb-bills/${id}/invoice-file`, method: 'get', responseType: 'blob' })
}
