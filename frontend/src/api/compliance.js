import request from '@/utils/request'

/** AI 逐条判读制度约 20～60 秒，单独放宽超时 */
const AI_TIMEOUT = 180000

/**
 * 合规判读接口
 *
 * 判读结论、不一致项均由后端程序汇总与交叉校验后返回，
 * 前端只做展示与动作下发，不自行推断结论。
 */
export const complianceApi = {
  /** 执行 AI 合规判读（耗时较长），返回 {check_id, overall_result, summary, ...} */
  run: (id) => request({ url: `/rmb-compliance/run/${id}`, method: 'post', timeout: AI_TIMEOUT }),

  /** 判读结果详情：报销单摘要 + 最近一次判读（含 14 条 issues）+ 历次记录 */
  detail: (id) => request({ url: `/rmb-compliance/${id}`, method: 'get' }),

  /** 处理判读结论：{ action: 'submit' | 'void' | 'override', comment } */
  handle: (id, data) => request({ url: `/rmb-compliance/${id}/handle`, method: 'post', data }),

  /** 判读记录列表（制单员 / 管理员），可按结论筛选 */
  list: (params) => request({ url: '/rmb-compliance/list', method: 'get', params })
}
