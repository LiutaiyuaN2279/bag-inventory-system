import request from '@/utils/request'

/** AI 制证约 20～120 秒，单独放宽超时 */
const AI_TIMEOUT = 180000

/**
 * 凭证接口：AI 制证草稿、程序校验、保存、复核
 *
 * 凭证号由后端在事务内取号生成（保存时确定），前端只展示预览号。
 */
export const voucherApi = {
  /** 待制证列表（待制证状态的报销单） */
  pending: (params) => request({ url: '/rmb-vouchers/pending', method: 'get', params }),

  /** 让 AI 生成凭证草稿：{reimbursement_id} → {header, entries, explanation, tax_treatment, errors, warnings, model, elapsed} */
  draft: (data) => request({ url: '/rmb-vouchers/draft', method: 'post', data, timeout: AI_TIMEOUT }),

  /** 程序校验：{reimbursement_id, header, entries} → {errors, warnings} */
  validate: (data) => request({ url: '/rmb-vouchers/validate', method: 'post', data }),

  /** 保存凭证（后端二次校验 + 正式取号）→ {id, voucher_code} */
  save: (data) => request({ url: '/rmb-vouchers/save', method: 'post', data }),

  /** 修改被退回的凭证（凭证号不变，改后回到未复核） */
  update: (id, data) => request({ url: `/rmb-vouchers/${id}`, method: 'put', data }),

  /** 凭证列表（分页 + 状态 / 期间筛选） */
  list: (params) => request({ url: '/rmb-vouchers', method: 'get', params }),

  /** 凭证详情（含分录、AI 说明、判读结论、报销单、审计轨迹） */
  detail: (id) => request({ url: `/rmb-vouchers/${id}`, method: 'get' }),

  /** 待复核列表 */
  reviewList: (params) => request({ url: '/rmb-vouchers/review', method: 'get', params }),

  /** 单张复核：{action: 'approve' | 'reject', comment} */
  review: (id, data) => request({ url: `/rmb-vouchers/review/${id}`, method: 'post', data }),

  /** 批量复核：{ids, action, comment} → {success_count, failed:[{id,code,reason}]} */
  reviewBatch: (data) => request({ url: '/rmb-vouchers/review/batch', method: 'post', data }),

  /**
   * 末级启用会计科目清单（供分录行的科目下拉）。
   * 契约中未列出该接口，此处按 /rmb-vouchers/subjects 约定调用；
   * 若后端未提供，页面会降级为「科目编码可手工输入」，不影响制证流程。
   */
  subjects: () => request({ url: '/rmb-vouchers/subjects', method: 'get' })
}
