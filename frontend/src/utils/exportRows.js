import { ElMessage } from 'element-plus'

/**
 * 把当前勾选行导出为 CSV（前端生成，无需后端接口）。
 *
 * 用 CSV 而不是 xlsx：不引入额外依赖，Excel 可直接打开（带 UTF-8 BOM 保证中文不乱码）。
 * 只读表格（出入库流水 / 报表 / 日志 / 算料结果）用「批量导出选中」代替批量写操作。
 *
 * @param rows   勾选的行数据
 * @param columns [{ prop, label, formatter?(row) }]
 * @param filename 不带扩展名
 */
export function exportRows(rows, columns, filename = '导出数据') {
  const list = rows || []
  if (!list.length) {
    ElMessage.warning('请先勾选要导出的数据')
    return
  }
  const head = columns.map((c) => c.label)
  const body = list.map((row) => columns.map((c) => {
    const raw = c.formatter ? c.formatter(row) : row[c.prop]
    if (raw === null || raw === undefined) return ''
    return String(raw)
  }))
  const csv = [head, ...body].map((line) => line.map(csvCell).join(',')).join('\r\n')
  // \ufeff 是 BOM：缺了它 Excel 会把中文读成乱码
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${filename}_${stamp()}.csv`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  // 立即 revoke 在部分浏览器会中断下载，放到下一个事件循环
  setTimeout(() => URL.revokeObjectURL(url), 0)
  ElMessage.success(`已导出 ${list.length} 条`)
}

/** 含逗号/引号/换行的单元格必须用双引号包裹，内部引号翻倍 */
function csvCell(value) {
  const s = String(value)
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

function stamp() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`
}
