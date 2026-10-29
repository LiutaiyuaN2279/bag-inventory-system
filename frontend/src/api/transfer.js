import request from '@/utils/request'

/** 仓库调拨：列表 / 详情 / 新增 / 编辑 / 审核 / 作废
 *  后端返回 {code,message,data}，request 拦截器已剥壳：
 *  code === 0 时 Promise 直接 resolve 成 data 字段，code !== 0 时自动弹错误并 reject。
 */
export const transferApi = {
  /** 分页列表：page / page_size / keyword / status / start_date / end_date / from_warehouse_id / to_warehouse_id / sort_by / sort_order */
  list: (params) => request({ url: '/transfers', method: 'get', params }),
  /** 单据详情（含 items 明细） */
  detail: (id) => request({ url: `/transfers/${id}`, method: 'get' }),
  /** 新增调拨单（初始状态「草稿」） */
  create: (data) => request({ url: '/transfers', method: 'post', data }),
  /** 编辑调拨单（仅草稿可编辑，items 传了即整体覆盖） */
  update: (id, data) => request({ url: `/transfers/${id}`, method: 'put', data }),
  /** 审核：整单校验调出仓库库存后真实出入库，状态转「已审核」 */
  approve: (id) => request({ url: `/transfers/${id}/approve`, method: 'post' }),
  /** 作废：已执行过的单据会反向回滚库存（void 是保留字，故方法名用 voidOrder） */
  voidOrder: (id) => request({ url: `/transfers/${id}/void`, method: 'post' }),
  /** 批量：{ ids, action: 'approve' | 'void' }，void 对应本文件的 voidOrder */
  batch: (data) => request({ url: '/transfers/batch', method: 'post', data })
}
