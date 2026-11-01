export function formatAuditNumber(value) {
  if (value == null || value === '' || !Number.isFinite(Number(value))) return '—'
  return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export const auditDisclosureColumns = [
  { prop: 'audit_mode', label: '输出性质' },
  { prop: 'audit_run_id', label: '试算运行编号' },
  { prop: 'audit_cutoff', label: '业务观察截止' },
  { prop: 'audit_history_scope', label: '历史可信范围' },
  { prop: 'audit_traceability', label: '历史追溯限制' },
  { prop: 'audit_limitation', label: '范围说明' },
]

export function withAuditDisclosure(rows, meta = {}) {
  return rows.map(row => ({ ...row,
    audit_mode: '受限试算，非正式审计报告',
    audit_run_id: meta.run_id || '版本未核实',
    audit_cutoff: meta.business_cutoff || '未确定',
    audit_history_scope: meta.assurance?.history_scope_status || '不可确定',
    audit_traceability: meta.assurance?.historical_traceability || '受限',
    audit_limitation: meta.assurance?.notice || '可信范围未核定，不能声称全部历史可靠或零线索即通过',
  }))
}
