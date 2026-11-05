<template>
  <div class="page">
    <!-- 页头：标题 + 说明 + 主操作（原表格卡里的孤立按钮移到这里） -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><DocumentChecked /></el-icon>来料质检</h2>
        <div class="ph-desc">
          逐明细明确检验结论和整批允许量，再独立质量放行；本批只支持整张正常全量放行，部分/让步/处置暂不开放 · 共 <b>{{ total }}</b> 条
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
        <el-button type="primary" :icon="Plus" v-permission="'qc:edit'" @click="onAdd">新建质检单</el-button>
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
          <el-form-item label="检验员">
            <el-input v-model="query.inspector" placeholder="姓名/工号" clearable style="width:120px" @keyup.enter="onSearch" />
          </el-form-item>
          <el-form-item label="单号">
            <el-input v-model="query.qc_no" placeholder="质检单号" clearable style="width:150px" @keyup.enter="onSearch" />
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
          <!-- 两列都用 min-width：剩余宽度摊到「供应商 + 检验员」，避免全部堆在单列形成大片空白 -->
          <el-table-column prop="supplier_name" label="供应商" min-width="240" sortable="custom" show-overflow-tooltip />
          <el-table-column label="状态" width="104" align="center">
            <template #default="{ row }"><el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="release_status" label="质量放行" width="110" />
          <el-table-column prop="inspector" label="检验员" min-width="120" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="created_at" label="时间" width="176" sortable="custom" show-overflow-tooltip />
          <el-table-column label="操作" width="190" fixed="right" align="center">
            <template #default="{ row }">
              <el-button link type="primary" v-permission="'qc:edit'"  :disabled="row.status!=='待检'" @click="onCheck(row)">录入结果</el-button>
              <el-button link type="success" v-permission="'qc:edit'" :disabled="row.status!=='合格' || row.release_status==='已放行'" @click="onRelease(row)">独立放行</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="pager">
        <span class="hint">
          <template v-if="clientFiltered">筛选后 {{ viewList.length }} / 本页 {{ list.length }} 条 · </template>
          共 <b>{{ total }}</b> 条 · 第 {{ query.page }} / {{ pageCount }} 页
          <span v-if="clientFiltered" class="cli-tip">（检验员/单号为当前页前端筛选，后端仅支持按状态筛选）</span>
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

    <el-dialog v-model="dialog.visible" title="关联新到货：建立待检明细" width="800px">
      <el-alert title="旧种子记录仅展示；没有实际收货日期和逐行绑定的记录不授信。不会默认给出合格结论。" type="info" :closable="false" />
      <el-select v-model="form.arrival_id" filterable placeholder="选择新登记待验收到货" @change="onArrivalChange">
        <el-option v-for="a in arrivals" :key="a.id" :value="a.id" :label="a.arrival_no" />
      </el-select>
      <el-table :data="form.items" border>
        <el-table-column prop="arrival_item_id" label="到货明细ID" />
        <el-table-column prop="material_name" label="物料" />
        <el-table-column prop="arrived_qty" label="实际到货声明量" />
      </el-table>
      <template #footer><el-button @click="dialog.visible=false">取消</el-button><el-button type="primary" :disabled="!form.items.length" @click="onSubmit">建立待检单</el-button></template>
    </el-dialog>
    <el-drawer v-model="check.visible" title="完整一次明确检验结论（尚未放行）" size="900px">
      <el-alert title="抽检合格数不是整批允许接收量；本批必须完整一次提交所有行。实际日期为人员声明，来源尚未正式核验。" type="warning" :closable="false" />
      <el-date-picker v-model="check.inspection_date" type="date" value-format="YYYY-MM-DD" placeholder="明确实际检验完成日" />
      <el-table :data="check.items || []" border>
        <el-table-column prop="arrival_item_id" label="到货明细ID" width="100" />
        <el-table-column prop="material_name" label="物料" />
        <el-table-column prop="arrived_qty" label="实际到货声明量" />
        <el-table-column label="抽检数"><template #default="{row}"><el-input-number v-model="row.sample_qty" :min="0" :precision="2" /></template></el-table-column>
        <el-table-column label="抽检合格数"><template #default="{row}"><el-input-number v-model="row.qualified_qty" :min="0" :precision="2" /></template></el-table-column>
        <el-table-column label="整批允许接收量"><template #default="{row}"><el-input-number v-model="row.accepted_qty" :min="0" :precision="2" /></template></el-table-column>
        <el-table-column label="明确最终结论"><template #default="{row}"><el-select v-model="row.result" placeholder="不得默认合格"><el-option label="合格" value="合格"/><el-option label="不合格（仅记录，不放行）" value="不合格"/><el-option label="让步（仅记录，不放行）" value="让步接收"/></el-select></template></el-table-column>
      </el-table>
      <el-button type="primary" @click="saveCheck">保存全部明确结论</el-button>
    </el-drawer>
    <el-dialog v-model="release.visible" title="独立正常全量质量放行" width="650px">
      <p>只允许全部明细合格、整批允许量与到货及原登记量一致；不从抽检比例推算放行。</p>
      <p>检验完成日：{{ release.inspection_date || '未提供' }}；放行状态：{{ release.release_status || '未提供' }}</p>
      <el-table :data="release.items" border><el-table-column prop="arrival_item_id" label="到货明细ID"/><el-table-column prop="material_name" label="物料"/><el-table-column prop="arrived_qty" label="到货声明量"/><el-table-column prop="declared_qualified_qty" label="原预填合格声明"/><el-table-column prop="accepted_qty" label="正式整批允许量"/></el-table>
      <el-date-picker v-model="release.release_date" type="date" value-format="YYYY-MM-DD" placeholder="明确实际放行日" />
      <el-input v-model="release.release_basis" type="textarea" placeholder="明确整批接收依据；记录与检验结论分开保存" />
      <template #footer><el-button @click="release.visible=false">取消</el-button><el-button type="primary" @click="saveRelease">确认独立放行</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Search, Refresh, Plus, DocumentChecked } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { qualityApi } from '@/api/quality'
import { arrivalApi } from '@/api/procurement'
import { materialApi, supplierApi } from '@/api/basicData'
import { useSort } from '@/composables/useSort'
import { applyRouteFilter } from '@/composables/useAutoFilter'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import SortChips from '@/components/SortChips.vue'
import BatchBar from '@/components/BatchBar.vue'

const statusList = ['待检', '合格', '不合格', '让步接收']
const statusType = (s) => ({ 待检: 'warning', 合格: 'success', 不合格: 'danger', 让步接收: '' }[s] || '')
const chipColor = (s) => ({ 待检: '#e6a23c', 合格: '#10b981', 不合格: '#f56c6c', 让步接收: '#909399' }[s] || '#909399')
const query = reactive({ page: 1, page_size: 20, status: '', inspector: '', qc_no: '' })
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
// 检验员 / 单号为当前页前端筛选（后端仅支持 status 参数，调用参数保持原样）
const clientFiltered = computed(() => !!(query.inspector || query.qc_no))
const viewList = computed(() => {
  const kw = query.inspector.trim(); const no = query.qc_no.trim()
  if (!kw && !no) return list.value
  return list.value.filter(r =>
    (!kw || String(r.inspector || '').includes(kw)) &&
    (!no || String(r.qc_no || '').includes(no)))
})
const materials = ref([]); const suppliers = ref([])
const dialog = reactive({ visible: false }); const formRef = ref()
const form = reactive({ arrival_id: null, supplier_id: null, items: [] })
const arrivals = ref([])
const release = reactive({ visible: false, id: null, release_date: null, release_basis: '', inspection_date: null, release_status: null, items: [] })
const check = reactive({ visible: false, id: null, inspection_date: null, items: null })
const mapName = (id) => materials.value.find(m => m.id === id)?.material_name || id
async function fetchList() { loading.value = true; try { const res = await qualityApi.iqcList({ ...query }); list.value = res.list || []; total.value = res.total || 0 } finally { loading.value = false } }
const { onSortChange, sortRules, removeSort, clearSort } = useSort(query, fetchList)

// ---- 批量操作 ----
const batch = useBatch({ fetchList })
// 动作按权限过滤：无权限的按钮不渲染（与行操作按钮的 v-permission 一致）
const batchActions = [
  { key: 'export', label: '导出选中', perm: 'qc:view' }
]
// 导出用列定义与表格列保持一致，避免导出后对不上
const exportColumns = [
  { prop: 'qc_no', label: '质检单号' },
  { prop: 'supplier_name', label: '供应商' },
  { prop: 'status', label: '状态' },
  { prop: 'inspector', label: '检验员' },
  { prop: 'created_at', label: '时间' }
]

async function onBatchAction(key) {
  if (key === 'export') {
    exportRows(batch.selected.value, exportColumns, '来料质检单')
    return
  }
  ElMessage.warning('本批仅支持逐单完整明确结论，不支持批量自动判定')
}

function onSearch() { query.page = 1; batch.clearSelection(); fetchList() }
function onReset() { query.status = ''; query.inspector = ''; query.qc_no = ''; onSearch() }
async function onAdd() {
  Object.assign(form, { arrival_id: null, supplier_id: null, items: [] })
  arrivals.value = []
  let page = 1
  while (true) {
    const data = await arrivalApi.list({ status: '待验收', page, page_size: 100 })
    const rows = data.list || []
    arrivals.value.push(...rows.filter(a => a.actual_receipt_date))
    if (!rows.length || page * 100 >= data.total) break
    page++
  }
  dialog.visible = true
}
async function onArrivalChange(id) {
  form.items = []
  if (!id) return
  const data = await arrivalApi.detail(id)
  if (form.arrival_id !== id) return
  form.supplier_id = data.supplier_id
  form.items = data.items.map(i => ({ arrival_item_id: i.id, material_id: i.material_id,
    material_name: i.material_name, arrived_qty: i.arrived_qty }))
}
async function onSubmit() {
  if (!form.arrival_id || !form.items.length) return ElMessage.warning('请关联完整的新登记到货明细')
  await qualityApi.iqcCreate({ arrival_id: form.arrival_id, supplier_id: form.supplier_id,
    items: form.items.map(i => ({ arrival_item_id: i.arrival_item_id, material_id: i.material_id })) })
  ElMessage.success('待检绑定已建立，未自动合格'); dialog.visible = false; fetchList()
}
async function onCheck(row) {
  const res = await qualityApi.iqcDetail(row.id)
  if (!res.arrival_id || res.items.some(i => !i.arrival_item_id)) return ElMessage.warning('旧记录缺少可靠到货明细绑定，只读展示，不能补造新流程资格')
  check.id = row.id
  check.inspection_date = null
  check.items = res.items.map(i => ({ id: i.id, arrival_item_id: i.arrival_item_id,
    material_name: i.material_name, arrived_qty: i.arrived_qty,
    sample_qty: i.sample_qty, qualified_qty: i.qualified_qty, accepted_qty: i.accepted_qty,
    result: i.result === '待检' ? '' : i.result }))
  check.visible = true
}
async function saveCheck() {
  if (!check.inspection_date || check.items.some(i => !i.result)) return ElMessage.warning('请明确实际检验日及所有明细结论，不默认合格')
  await qualityApi.iqcCheck(check.id, { inspection_date: check.inspection_date, items: check.items })
  ElMessage.success('检验结论已保存，仍须独立放行'); check.visible = false; fetchList()
}
async function onRelease(row) {
  Object.assign(release, { visible: false, id: row.id, release_date: null, release_basis: '', items: [] })
  const res = await qualityApi.iqcDetail(row.id)
  if (release.id !== row.id) return
  if (res.items.some(i => !i.arrival_item_id)) return ElMessage.warning('旧记录缺少可靠明细绑定，不授予放行资格')
  release.items = res.items
  release.inspection_date = res.inspection_date
  release.release_status = res.release_status
  release.visible = true
}
async function saveRelease() {
  if (!release.release_date || !release.release_basis.trim()) return ElMessage.warning('请明确实际放行日和整批接收依据')
  await qualityApi.iqcRelease(release.id, { release_date: release.release_date, release_basis: release.release_basis })
  release.visible = false; ElMessage.success('质量放行已记录，仍需仓管入库'); fetchList()
}
onMounted(async () => { fetchList(); const [m, s] = await Promise.all([materialApi.list({ page: 1, page_size: 1000 }), supplierApi.list({ page: 1, page_size: 1000 })]); materials.value = m.list || []; suppliers.value = s.list || [] })
</script>
<style scoped>
/* 本页专属：筛选条右侧的本页状态分布 + 前端筛选提示 */
.qc-stat { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); }
.qc-stat b { font-variant-numeric: tabular-nums; color: var(--text-1); }
.cli-tip { color: var(--text-3); }
</style>
