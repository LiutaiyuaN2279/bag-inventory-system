/**
 * 单据打印工具
 * - buildHtml(doc)：纯函数，把单据对象转成一张完整可打印的 HTML 字符串（不依赖 window/document，便于单测）
 * - printDocument(doc)：在新窗口中渲染该 HTML 并调起浏览器打印
 * 打印页样式全部内联在新窗口里，不依赖主应用 CSS 与 Element Plus 主题。
 */
import { ElMessage } from 'element-plus'

/** 系统无衬线字体栈（不引外部字体） */
const FONT_STACK = '"Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", "Helvetica Neue", Arial, sans-serif'
/** 数字类列关键字：数量/金额/比率等自动右对齐 */
const NUMERIC_RE = /qty|price|amount|rate|num|total|count|数量|金额|单价|合计|损耗|差异|库存/i

/** 转义 HTML 特殊字符，避免单号/备注里的尖括号、引号破坏文档结构 */
function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** 单元格显示值：空值统一显示为 — */
function cellText(value) {
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

/** 归一化 meta：兼容 [{ label, value }] 数组与 { label: value } 对象两种写法，丢弃空值项 */
function normalizeMeta(meta) {
  if (meta === null || meta === undefined) return []
  const list = Array.isArray(meta)
    ? meta.map((it) => (it && typeof it === 'object' ? { label: it.label ?? '', value: it.value } : { label: '', value: it }))
    : typeof meta === 'object'
      ? Object.keys(meta).map((k) => ({ label: k, value: meta[k] }))
      : [{ label: '', value: meta }]
  return list.filter((it) => cellText(it.value) !== '—')
}

/** 归一化 footer：兼容字符串 / 字符串数组 / [{ label, value }] / { label: value }，丢弃空值项 */
function normalizeFooter(footer) {
  if (footer === null || footer === undefined || footer === '') return []
  const list = Array.isArray(footer) ? footer : [footer]
  const flat = list.map((it) => (it && typeof it === 'object' ? { label: it.label ?? '', value: it.value } : { label: '', value: it }))
  return flat.filter((it) => cellText(it.value) !== '—')
}

/** 是否为右对齐的数字列：显式 align 优先，否则按列名/字段名关键字推断 */
function isNumericColumn(col) {
  if (col.align) return col.align === 'right' || col.align === 'center'
  return NUMERIC_RE.test(String(col.prop || '')) || NUMERIC_RE.test(String(col.label || ''))
}

/**
 * 按列宽比例分配列宽（缺省宽度按 120 计权重），
 * 保证不论列多少，表格宽度都刚好铺满纸张而不会溢出 A4。
 */
function columnWidthStyles(columns) {
  const weights = columns.map((c) => (Number(c.width) > 0 ? Number(c.width) : 120))
  const total = weights.reduce((s, w) => s + w, 0)
  if (!total) return columns.map(() => '')
  return weights.map((w) => `width:${((w / total) * 100).toFixed(2)}%`)
}

/** 汇总明细中的某个数值列（打印 footer 的合计用），返回去掉多余零的字符串 */
export function sumBy(rows, prop, digits = 2) {
  const total = (Array.isArray(rows) ? rows : []).reduce((s, r) => s + (Number(r?.[prop]) || 0), 0)
  return String(Number(total.toFixed(digits)))
}

/**
 * 把单据对象转成完整的可打印 HTML 字符串（纯函数）。
 * @param {object} doc
 * @param {string} doc.title    单据标题，如「采购订单」
 * @param {string} doc.docNo    单号
 * @param {string} [doc.docNoLabel] 单号前缀文字，默认「单号」
 * @param {Array|object} [doc.meta]  头部键值对 [{ label, value }] 或 { label: value }
 * @param {Array} [doc.columns] 表头 [{ label, prop, width?, align? }]
 * @param {Array} [doc.rows]    数据行
 * @param {string|Array|object} [doc.footer] 合计/备注
 * @returns {string} 完整 HTML（含 <!DOCTYPE html>）
 */
export function buildHtml(doc = {}) {
  const title = String(doc.title || '单据')
  const docNo = doc.docNo === null || doc.docNo === undefined ? '' : String(doc.docNo)
  const docNoLabel = String(doc.docNoLabel || '单号')
  const metaList = normalizeMeta(doc.meta)
  const columns = (Array.isArray(doc.columns) ? doc.columns : []).map((c) => ({
    label: String(c?.label ?? ''),
    prop: c?.prop ?? '',
    align: c?.align || ''
  }))
  const rows = Array.isArray(doc.rows) ? doc.rows : []
  const footerList = normalizeFooter(doc.footer)
  const widthStyles = columnWidthStyles(columns)

  const metaHtml = metaList.length
    ? `<div class="doc-meta">${metaList
        .map((it) => `<div class="meta-item"><span class="meta-label">${it.label ? escapeHtml(it.label) + '：' : ''}</span><span class="meta-value">${escapeHtml(cellText(it.value))}</span></div>`)
        .join('')}</div>`
    : ''

  const colgroup = columns.length ? `<colgroup>${widthStyles.map((s) => `<col style="${s}" />`).join('')}</colgroup>` : ''
  const thead = columns.length
    ? `<thead><tr>${columns.map((c) => `<th class="${isNumericColumn(c) ? 'num' : ''}">${escapeHtml(c.label)}</th>`).join('')}</tr></thead>`
    : ''
  const bodyRows = rows.length
    ? rows
        .map((row) => `<tr>${columns
          .map((c) => `<td class="${isNumericColumn(c) ? 'num' : ''}">${escapeHtml(cellText(row ? row[c.prop] : ''))}</td>`)
          .join('')}</tr>`)
        .join('')
    : `<tr><td class="empty" colspan="${columns.length || 1}">暂无明细数据</td></tr>`
  const tbody = `<tbody>${bodyRows}</tbody>`

  const footerHtml = footerList.length
    ? `<div class="doc-footer">${footerList
        .map((it) => `<div class="footer-line"><span class="flabel">${it.label ? escapeHtml(it.label) + '：' : ''}</span><span class="fvalue">${escapeHtml(cellText(it.value))}</span></div>`)
        .join('')}</div>`
    : ''

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${escapeHtml(title)}${docNo ? ' ' + escapeHtml(docNo) : ''}</title>
<style>
  * { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  @page { size: A4; margin: 14mm; }
  html, body { margin: 0; padding: 0; }
  body { font-family: ${FONT_STACK}; font-size: 13px; line-height: 1.6; color: #303133; background: #f2f3f5; padding: 22px; }
  /* 屏幕上的操作条：打印时隐藏 */
  .toolbar { max-width: 820px; margin: 0 auto 14px; display: flex; align-items: center; gap: 12px; }
  .toolbar button { font: inherit; font-weight: 600; color: #fff; background: #409eff; border: 0; border-radius: 6px; padding: 8px 24px; cursor: pointer; }
  .toolbar button:hover { background: #337ecc; }
  .toolbar .tip { color: #909399; font-size: 12px; }
  .sheet { max-width: 820px; margin: 0 auto; padding: 28px 32px 34px; background: #fff; border-radius: 8px; box-shadow: 0 2px 12px rgba(0, 0, 0, .08); }
  /* 顶部：标题居中大字 + 右侧单号 + 主色横线 */
  .doc-head { position: relative; text-align: center; padding: 2px 0 12px; }
  .doc-title { margin: 0; font-size: 24px; font-weight: 700; letter-spacing: 6px; color: #1f2937; }
  .doc-no { position: absolute; right: 0; bottom: 16px; font-size: 12px; color: #606266; }
  .doc-rule { height: 3px; margin-bottom: 16px; background: #409eff; border-radius: 2px; }
  /* 头部信息网格：三列键值 */
  .doc-meta { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px 18px; padding: 12px 14px; margin-bottom: 16px; border: 1px solid #dcdfe6; border-radius: 6px; }
  .meta-item { display: flex; gap: 2px; min-width: 0; }
  .meta-label { flex: none; color: #909399; }
  .meta-value { color: #1f2937; font-weight: 600; word-break: break-all; }
  table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 12.5px; }
  th { padding: 9px 10px; text-align: left; font-weight: 600; color: #1f2937; background: #f2f3f5; border: 1px solid #c8cdd4; }
  td { padding: 9px 10px; vertical-align: top; color: #303133; border: 1px solid #c8cdd4; overflow-wrap: break-word; word-break: break-word; }
  tbody tr:nth-child(even) td { background: #fafbfc; }
  /* 最后一列不加右边框 */
  th:last-child, td:last-child { border-right: 0; }
  th.num, td.num { text-align: right; font-variant-numeric: tabular-nums; }
  td.empty { padding: 22px 0; text-align: center; color: #909399; }
  /* 避免表格行被跨页截断 */
  tr { page-break-inside: avoid; break-inside: avoid; }
  thead { display: table-header-group; }
  .doc-footer { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; margin-top: 14px; }
  .footer-line { display: flex; gap: 2px; }
  .flabel { color: #909399; }
  .fvalue { font-weight: 700; color: #1f2937; }
  @media print {
    body { padding: 0; background: #fff; }
    .toolbar { display: none !important; }
    .sheet { max-width: none; width: auto; margin: 0; padding: 0; border-radius: 0; box-shadow: none; }
    tbody tr:nth-child(even) td { background: transparent; }
    thead { display: table-header-group; }
    tr { page-break-inside: avoid; break-inside: avoid; }
  }
</style>
</head>
<body>
  <div class="toolbar">
    <button type="button" onclick="window.print()">打 印</button>
    <span class="tip">若打印窗口未自动弹出，请点击左侧按钮</span>
  </div>
  <div class="sheet">
    <div class="doc-head">
      <h1 class="doc-title">${escapeHtml(title)}</h1>
      ${docNo ? `<div class="doc-no">${escapeHtml(docNoLabel)}：${escapeHtml(docNo)}</div>` : ''}
    </div>
    <div class="doc-rule"></div>
    ${metaHtml}
    <table>${colgroup}${thead}${tbody}</table>
    ${footerHtml}
  </div>
</body>
</html>`
}

/**
 * 在新窗口中渲染单据并调起浏览器打印。
 * 弹窗被拦截、写入失败等异常一律提示，不向外抛出（避免未捕获的 Promise 拒绝）。
 * @param {object} doc 同 buildHtml 的单据对象
 */
export function printDocument(doc) {
  try {
    const html = buildHtml(doc)
    // 安卓 WebView 无法可靠地 window.open 到新窗口；有原生打印桥时交给 Android 打印服务
    // （可另存为 PDF 或直接走打印机），否则仍走浏览器弹窗。
    if (window.AndroidBridge && typeof window.AndroidBridge.printHtml === 'function') {
      window.AndroidBridge.printHtml(html)
      return
    }
    const win = window.open('', '_blank', 'width=1024,height=768,menubar=no,toolbar=no,location=no,status=no,resizable=yes,scrollbars=yes')
    if (!win) {
      // 浏览器拦截弹窗：给出提示后安全返回，不抛错
      ElMessage.warning('打印窗口被浏览器拦截，请允许弹出窗口后重试')
      return
    }
    win.document.open()
    win.document.write(html)
    win.document.close()
    // 等新窗口渲染完成再调起打印，避免打印出空白页
    setTimeout(() => {
      try {
        win.focus()
        win.print()
      } catch (e) {
        ElMessage.error('打印失败：' + (e && e.message ? e.message : e))
      }
    }, 300)
  } catch (e) {
    ElMessage.error('打印失败：' + (e && e.message ? e.message : e))
  }
}
