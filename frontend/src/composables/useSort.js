import { ref } from 'vue'

// 全局跟踪 Shift 键，用于“Shift + 点击列头”叠加多级排序。
// 既监听键盘事件，也在点击捕获阶段直接读取 event.shiftKey（兼容自动化/模拟点击）。
let shiftDown = false
if (typeof window !== 'undefined') {
  window.addEventListener('keydown', (e) => { if (e.key === 'Shift') shiftDown = true })
  window.addEventListener('keyup', (e) => { if (e.key === 'Shift') shiftDown = false })
  window.addEventListener('blur', () => { shiftDown = false })
  // 捕获阶段先于表格的 click 处理，确保 sort-change 触发时 shiftDown 为最新状态
  document.addEventListener('click', (e) => { shiftDown = !!e.shiftKey }, true)
}

// 表格多级排序（服务端）：
//   普通点击列头 → 单列排序；按住 Shift 点击 → 叠加为次级排序键。
//   向后端发送 sort_by="a,b"、sort_order="asc,desc"。
// 用法：
//   const { onSortChange, sortRules, removeSort, clearSort } = useSort(query, fetchList)
//   <el-table @sort-change="onSortChange"> ... <el-table-column prop="x" sortable="custom" />
//   <SortChips :rules="sortRules" @remove="removeSort" @clear="clearSort" />
export function useSort(query, fetchList) {
  const sortRules = ref([]) // [{ prop, order:'asc'|'desc', label }]

  function syncQuery() {
    query.sort_by = sortRules.value.map((r) => r.prop).join(',')
    query.sort_order = sortRules.value.map((r) => r.order).join(',')
  }

  function onSortChange({ column, prop, order }) {
    const dir = order === 'ascending' ? 'asc' : 'desc'
    const label = (column && column.label) || prop
    if (!shiftDown) {
      // 普通点击：重置为单列（或清空）
      sortRules.value = order ? [{ prop, order: dir, label }] : []
    } else {
      const idx = sortRules.value.findIndex((r) => r.prop === prop)
      if (!order) {
        if (idx >= 0) sortRules.value.splice(idx, 1)
      } else if (idx >= 0) {
        sortRules.value[idx] = { prop, order: dir, label }
      } else {
        sortRules.value.push({ prop, order: dir, label })
      }
    }
    syncQuery()
    query.page = 1
    fetchList()
  }

  function removeSort(prop) {
    sortRules.value = sortRules.value.filter((r) => r.prop !== prop)
    syncQuery(); query.page = 1; fetchList()
  }
  function clearSort() {
    sortRules.value = []
    syncQuery(); query.page = 1; fetchList()
  }

  // 初始化：确保 query 带这两个字段，避免首次请求缺参
  if (!('sort_by' in query)) query.sort_by = ''
  if (!('sort_order' in query)) query.sort_order = ''

  return { onSortChange, sortRules, removeSort, clearSort }
}
