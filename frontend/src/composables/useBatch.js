import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

/**
 * 表格批量操作：勾选状态 + 统一调用后端 `POST /xxx/batch` + 结果反馈。
 *
 * 后端批量接口返回结构固定为：
 *   { total, success_count, fail_count, success_ids, failed: [{ id, reason }] }
 * 逐条独立事务，允许部分成功 —— 这里把失败明细原样展示给用户，不吞掉原因。
 *
 * 用法：
 *   const batch = useBatch({ fetchList })
 *   <el-table :ref="batch.bindTable" :row-key="row => row.id" @selection-change="batch.onSelectionChange">
 *     <el-table-column type="selection" width="50" align="center" reserve-selection />
 *   </el-table>
 *   <BatchBar :batch="batch" :actions="actions" @action="onAction" />
 *
 * 注意 `:ref="batch.bindTable"` 不能写成 `ref="batch.tableRef"`：
 * 字符串 ref 不支持点号路径，拿不到组件实例，clearSelection 会静默失效。
 */
export function useBatch(options = {}) {
  const { fetchList, afterDone, maxCount = 500 } = options
  const tableRef = ref(null)
  const selected = ref([])
  const loading = ref(false)

  const count = computed(() => selected.value.length)
  const ids = computed(() => selected.value.map((r) => r.id).filter((v) => v !== null && v !== undefined))

  /**
   * 绑定表格实例：模板里写 `:ref="batch.bindTable"`。
   * 不用 `ref="batch.tableRef"` —— 字符串 ref 不支持点号路径，拿不到实例。
   */
  function bindTable(el) {
    tableRef.value = el
  }

  function onSelectionChange(rows) {
    selected.value = rows || []
  }

  /** 清空勾选：换页/换筛选条件/操作完成后都要调，避免把不可见行带进下一次批量操作 */
  function clearSelection() {
    // clearSelection 会再次触发 selection-change，直接置空即可保持一致
    tableRef.value?.clearSelection()
    selected.value = []
  }

  /**
   * 执行一次批量操作。
   * @param api    (payload) => Promise  后端批量接口，payload = { ids, action, reason }
   * @param action 动作名，交给后端区分（approve / void / delete ...）
   * @param opts   { label, confirm, prompt, reasonRequired, done }
   */
  async function run(api, action, opts = {}) {
    const { label = '批量操作', confirm = '', prompt = '', reasonRequired = false, done } = opts
    if (!ids.value.length) {
      ElMessage.warning('请先勾选要操作的数据')
      return null
    }
    if (ids.value.length > maxCount) {
      ElMessage.warning(`单次最多批量操作 ${maxCount} 条，当前已选 ${ids.value.length} 条`)
      return null
    }
    if (confirm) {
      try {
        await ElMessageBox.confirm(confirm, label, { type: 'warning' })
      } catch (e) {
        return null
      }
    }
    let reason = null
    if (prompt || reasonRequired) {
      try {
        const { value } = await ElMessageBox.prompt(prompt || '请输入原因', label, {
          inputValidator: (v) => (!reasonRequired || String(v || '').trim() ? true : '请输入原因'),
          inputPlaceholder: '将记录到单据上'
        })
        reason = String(value || '').trim()
      } catch (e) {
        return null
      }
    }

    loading.value = true
    try {
      const res = await api({ ids: ids.value, action, reason })
      report(res, label)
      clearSelection()
      await fetchList?.()
      await done?.(res)
      await afterDone?.(res)
      return res
    } catch (e) {
      // 请求拦截器已统一提示错误，这里不再重复弹窗
      return null
    } finally {
      loading.value = false
    }
  }

  return { tableRef, selected, loading, count, ids, onSelectionChange, clearSelection, bindTable, run }
}

/** 统一结果反馈：全成功 → 提示；有失败 → 弹窗列出逐条原因 */
function report(res, label) {
  const ok = res?.success_count ?? 0
  const failed = res?.failed || []
  if (!failed.length) {
    ElMessage.success(res?.message || `已成功处理 ${ok} 条`)
    return
  }
  if (ok === 0) {
    ElMessage.error(`${failed.length} 条均处理失败`)
  } else {
    ElMessage.warning(`成功 ${ok} 条，失败 ${failed.length} 条`)
  }
  const shown = failed.slice(0, 50)
  const html = `<div class="batch-fail">`
    + `<div class="bf-head">失败明细（共 ${failed.length} 条）</div>`
    + `<ul>${shown.map((f) => `<li><b>#${f.id}</b> ${escapeHtml(f.reason || '未知原因')}</li>`).join('')}</ul>`
    + (failed.length > shown.length ? `<div class="bf-more">仅展示前 ${shown.length} 条</div>` : '')
    + `</div>`
  // alert 关闭按钮会让 Promise 变成 rejected，catch 掉避免未捕获拒绝
  ElMessageBox.alert(html, `${label} · 失败明细`, {
    dangerouslyUseHTMLString: true,
    confirmButtonText: '知道了'
  }).catch(() => {})
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}
