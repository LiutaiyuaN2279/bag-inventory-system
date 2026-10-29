import request from '@/utils/request'

/**
 * 智能审计工作台接口
 *
 * 后端以只读模式打开被审计业务库（SQLite），接口按工作台的展示需要
 * 把审计结果切片、筛选、排序后返回，不写回任何业务数据。
 */
export const auditApi = {
  /** 审计配置：审计名称、期间、审计基准日、重要性水平比例与各项判定阈值 */
  config: () => request({ url: '/audit/config', method: 'get' }),

  /** 执行审计：重新运行全部审计程序并返回完整结果（对应「执行审计」按钮） */
  run: () => request({ url: '/audit/run', method: 'post' }),

  /** 审计报告全量数据：报告元信息、审计范围、数据概览、汇总、程序清单与执行日志 */
  report: () => request({ url: '/audit/report', method: 'get' }),

  /** 审计程序执行情况清单 */
  procedures: () => request({ url: '/audit/procedures', method: 'get' }),

  /** 审计发现清单（支持按风险等级、程序编号、关键字筛选与分页） */
  findings: (params) => request({ url: '/audit/findings', method: 'get', params }),

  /** 审计发现详情：含证据链、审计建议与所关联的审计程序 */
  findingDetail: (findingId) => request({ url: `/audit/findings/${findingId}`, method: 'get' }),

  /** 审计工作底稿：按审计程序归集全部审计发现 */
  workpaper: () => request({ url: '/audit/workpaper', method: 'get' })
}
