<template>
  <div class="page">
    <!-- 页头：标题 + 说明 + 主操作（原表格卡里的孤立按钮移到这里） -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Stamp /></el-icon>成品质检</h2>
        <div class="ph-desc">
          成品入库前的批次抽检，记录检验数与合格数并判定批次结果 · 共 <b>{{ total }}</b> 条
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
        <el-button type="primary" :icon="Plus" v-permission="'qc:edit'" @click="onAdd">新增质检</el-button>
      </div>
    </div>

    <!-- 列表卡：筛选条 + 本页状态分布 + 表格 + 分页（原独立筛选卡已并入 .toolbar） -->
    <el-card shadow="never" class="card-fill">
      <div class="toolbar">
        <el-form :inline="true" :model="query" class="tb-left">
          <el-form-item label="状态">
            <el-select v-model="query.status" placeholder="全部" clearable style="width:120px">
              <el-option v-for="s in statusList" :key="s" :label="s" :value="s" />
            </el-select>
          </el-form-item>
          <el-form-item label="成品">
            <el-input v-model="query.product_name" placeholder="成品名称" clearable style="width:140px" @keyup.enter="onSearch" />
          </el-form-item>
          <el-form-item label="批次">
            <el-input v-model="query.batch_no" placeholder="批次号" clearable style="width:130px" @keyup.enter="onSearch" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :icon="Search" @click="onSearch">查询</el-button>
            <el-button :icon="Refresh" @click="onReset">重置</el-button>
          </el-form-item>
        </el-form>

        <!-- 本页状态分布：填充筛选条右侧留白 -->
        <div class="tb-right">
          <span v-for="s in statusList" :key="s" class="qc-stat">
            <span class="dot" :style="{ color: chipColor(s) }">{{ s }}</span>
            <b>{{ statusStats[s] }}</b>
          </span>
        </div>
        <SortChips :rules="sortRules" @remove="removeSort" @clear="clearSort" />
      </div>

      <!-- 批量操作条：勾选后才出现，不占固定高度 -->
      <BatchBar :batch="batch" :actions="batchActions" @action="onBatchAction" />

      <div class="table-wrap">
        <el-table :ref="batch.bindTable" :data="viewList" :row-key="(row) => row.id" v-loading="loading" border stripe
          @sort-change="onSortChange" @selection-change="batch.onSelectionChange">
          <el-table-column type="selection" width="50" align="center" reserve-selection />
          <el-table-column type="index" label="#" width="55" align="center" />
          <el-table-column prop="qc_no" label="质检单号" width="180" sortable="custom" show-overflow-tooltip />
          <!-- 两列都用 min-width：剩余宽度摊到「成品 + 批次」，避免全堆在成品一列形成大片空白 -->
          <el-table-column prop="product_name" label="成品" min-width="200" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="batch_no" label="批次" min-width="130" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="check_qty" label="检验数" width="96" sortable="custom" align="right" class-name="col-num" />
          <el-table-column prop="qualified_qty" label="合格数" width="96" sortable="custom" align="right" class-name="col-num" />
          <el-table-column label="合格率" width="92" align="right" class-name="col-num">
            <template #default="{ row }">{{ row.check_qty ? ((row.qualified_qty/row.check_qty)*100).toFixed(1)+'%' : '-' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="104" align="center">
            <template #default="{ row }"><el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="inspector" label="检验员" width="120" sortable="custom" show-overflow-tooltip />
          <el-table-column label="操作" width="110" fixed="right" align="center">
            <template #default="{ row }">
              <el-button link type="primary" v-permission="'qc:edit'" @click="onEdit(row)">结果</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="pager">
        <span class="hint">
          <template v-if="clientFiltered">筛选后 {{ viewList.length }} / 本页 {{ list.length }} 条 · </template>
          共 <b>{{ total }}</b> 条 · 第 {{ query.page }} / {{ pageCount }} 页
          <span v-if="clientFiltered" class="cli-tip">（成品/批次为当前页前端筛选，后端仅支持按状态筛选）</span>
        </span>
        <el-pagination
          background
          layout="sizes, prev, pager, next"
          :total="total"
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :page-sizes="[10, 20, 50, 100]"
          @current-change="fetchList"
          @size-change="fetchList"
        />
      </div>
    </el-card>

    <el-dialog v-model="dialog.visible" :title="dialog.isEdit?'录入质检结果':'新增成品质检'" width="480px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="成品" v-if="!dialog.isEdit"><el-select v-model="form.product_id" filterable style="width:100%"><el-option v-for="m in products" :key="m.id" :label="m.material_code+' '+m.material_name" :value="m.id" /></el-select></el-form-item>
        <el-form-item label="批次"><el-input v-model="form.batch_no" /></el-form-item>
        <el-form-item label="检验数"><el-input-number v-model="form.check_qty" :min="0" :precision="2" style="width:100%" /></el-form-item>
        <el-form-item label="合格数"><el-input-number v-model="form.qualified_qty" :min="0" :precision="2" style="width:100%" /></el-form-item>
        <el-form-item label="结果"><el-select v-model="form.status" style="width:100%"><el-option v-for="s in statusList" :key="s" :label="s" :value="s" /></el-select></el-form-item>
        <el-form-item label="检验员"><el-input v-model="form.inspector" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialog.visible=false">取消</el-button><el-button type="primary" @click="onSubmit">确定</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Search, Refresh, Plus, Stamp } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { qualityApi } from '@/api/quality'
import { materialApi } from '@/api/basicData'
import { useSort } from '@/composables/useSort'
import { applyRouteFilter } from '@/composables/useAutoFilter'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import SortChips from '@/components/SortChips.vue'
import BatchBar from '@/components/BatchBar.vue'

const statusList = ['待检', '合格', '不合格', '让步接收']
const statusType = (s) => ({ 待检: 'warning', 合格: 'success', 不合格: 'danger', 让步接收: '' }[s] || '')
const chipColor = (s) => ({ 待检: '#e6a23c', 合格: '#10b981', 不合格: '#f56c6c', 让步接收: '#909399' }[s] || '#909399')
const query = reactive({ page: 1, page_size: 20, status: '', product_name: '', batch_no: '' })
applyRouteFilter(query) // 首页待办跳转自动带筛选
const list = ref([]); const total = ref(0); const loading = ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))
// 本页状态计数（仅统计当前页数据，纯展示）
const statusStats = computed(() => {
  const acc = {}
  for (const s of statusList) acc[s] = 0
  for (const r of list.value) if (acc[r.status] !== undefined) acc[r.status]++
  return acc
})
// 成品 / 批次为当前页前端筛选（后端仅支持 status 参数，调用参数保持原样）
const clientFiltered = computed(() => !!(query.product_name || query.batch_no))
const viewList = computed(() => {
  const pn = query.product_name.trim(); const bn = query.batch_no.trim()
  if (!pn && !bn) return list.value
  return list.value.filter(r =>
    (!pn || String(r.product_name || '').includes(pn)) &&
    (!bn || String(r.batch_no || '').includes(bn)))
})
const products = ref([])
const dialog = reactive({ visible: false, isEdit: false })
const form = reactive({ id: null, product_id: null, batch_no: '', check_qty: 0, qualified_qty: 0, status: '待检', inspector: '' })
async function fetchList() { loading.value = true; try { const res = await qualityApi.fqcList({ ...query }); list.value = res.list || []; total.value = res.total || 0 } finally { loading.value = false } }
const { onSortChange, sortRules, removeSort, clearSort } = useSort(query, fetchList)

// ---- 批量操作 ----
const batch = useBatch({ fetchList })
// 动作按权限过滤：无权限的按钮不渲染（与行操作按钮的 v-permission 一致）
const batchActions = [
  { key: 'approve', label: '批量置为合格', type: 'success', perm: 'qc:edit' },
  { key: 'reject', label: '批量置为不合格', type: 'danger', perm: 'qc:edit' },
  { key: 'export', label: '导出选中', perm: 'qc:view' }
]
// 导出列与表格列一一对应（created_at 未在表格展示，故不导出）
const exportColumns = [
  { prop: 'qc_no', label: '质检单号' },
  { prop: 'product_name', label: '成品' },
  { prop: 'batch_no', label: '批次' },
  { prop: 'check_qty', label: '检验数' },
  { prop: 'qualified_qty', label: '合格数' },
  { prop: 'qualified_rate', label: '合格率', formatter: (r) => (r.check_qty ? ((r.qualified_qty / r.check_qty) * 100).toFixed(1) + '%' : '-') },
  { prop: 'status', label: '状态' },
  { prop: 'inspector', label: '检验员' }
]

async function onBatchAction(key) {
  if (key === 'export') {
    exportRows(batch.selected.value, exportColumns, '成品质检单')
    return
  }
  const n = batch.count.value
  // 批量判定是「整单级」动作，不是逐项录入，confirm 里必须说清语义
  const confirm = key === 'approve'
    ? `确认将选中的 ${n} 张成品质检单批量置为「合格」？批量置合格是整单级覆盖：直接写入合格状态；当该单「合格数」为 0 时，后端会用「检验数」补齐合格数（不是逐项录入检验结果）；已是合格状态的单据会被后端逐条拒绝，失败明细会在结果弹窗中列出。`
    : `确认将选中的 ${n} 张成品质检单批量置为「不合格」？该操作直接把整单状态置为不合格（不修改检验数与合格数），已是不合格状态的单据会被后端逐条拒绝。`
  await batch.run(qualityApi.fqcBatch, key, {
    label: key === 'approve' ? '批量置为合格' : '批量置为不合格',
    confirm,
    reasonRequired: key === 'reject',
    prompt: '请输入置为不合格的原因'
  })
}

function onSearch() { query.page = 1; batch.clearSelection(); fetchList() }
function onReset() { query.status = ''; query.product_name = ''; query.batch_no = ''; onSearch() }
function onAdd() { Object.assign(form, { id: null, product_id: null, batch_no: '', check_qty: 0, qualified_qty: 0, status: '待检', inspector: '' }); dialog.isEdit = false; dialog.visible = true }
function onEdit(row) { Object.assign(form, row); dialog.isEdit = true; dialog.visible = true }
async function onSubmit() {
  if (!dialog.isEdit && !form.product_id) return ElMessage.warning('请选择成品')
  dialog.isEdit ? await qualityApi.fqcUpdate(form.id, form) : await qualityApi.fqcCreate(form)
  ElMessage.success('保存成功'); dialog.visible = false; fetchList()
}
onMounted(async () => { fetchList(); const res = await materialApi.list({ page: 1, page_size: 1000 }); products.value = (res.list || []).filter(m => m.category === '成品') })
</script>
<style scoped>
/* 本页专属：筛选条右侧的本页状态分布 + 前端筛选提示 */
.qc-stat { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); }
.qc-stat b { font-variant-numeric: tabular-nums; color: var(--text-1); }
.cli-tip { color: var(--text-3); }
</style>
