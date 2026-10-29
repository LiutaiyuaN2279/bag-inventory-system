<template>
  <div class="page">
    <!-- 页头：标题 + 说明 + 主操作（原表格卡里的孤立按钮移到这里） -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Files /></el-icon>BOM 清单</h2>
        <div class="ph-desc">
          成品物料清单版本管理，生效版本用于生产领料与算料 · 共 <b>{{ total }}</b> 条
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
        <el-button type="primary" :icon="Plus" v-permission="'bom:edit'" @click="onAdd">新增 BOM</el-button>
      </div>
    </div>

    <!-- 列表卡：筛选条 + 本页状态分布 + 表格 + 分页（原独立筛选卡已并入 .toolbar） -->
    <el-card shadow="never" class="card-fill">
      <div class="toolbar">
        <el-form :inline="true" :model="query" class="tb-left">
          <el-form-item label="成品">
            <el-input v-model="query.keyword" placeholder="成品名称" clearable style="width:200px" @keyup.enter="onSearch" />
          </el-form-item>
          <el-form-item label="版本">
            <el-select v-model="query.version" placeholder="全部" clearable style="width:120px" @change="batch.clearSelection()">
              <el-option v-for="v in versionOptions" :key="v" :label="v" :value="v" />
            </el-select>
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="query.status" placeholder="全部" clearable style="width:120px" @change="batch.clearSelection()">
              <el-option v-for="s in statusList" :key="s" :label="s" :value="s" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :icon="Search" @click="onSearch">查询</el-button>
            <el-button :icon="Refresh" @click="onReset">重置</el-button>
          </el-form-item>
        </el-form>

        <!-- 本页状态分布：填充筛选条右侧留白 -->
        <div class="tb-right">
          <span v-for="s in statusList" :key="s" class="bom-stat">
            <span class="dot" :style="{ color: chipColor(s) }">{{ s }}</span>
            <b>{{ statusStats[s] }}</b>
          </span>
        </div>
        <SortChips :rules="sortRules" @remove="removeSort" @clear="clearSort" />
      </div>

      <BatchBar :batch="batch" :actions="batchActions" @action="onBatchAction" />
      <div class="table-wrap">
        <el-table :ref="batch.bindTable" :data="viewList" :row-key="(row) => row.id" v-loading="loading" border stripe
          @sort-change="onSortChange" @selection-change="batch.onSelectionChange">
          <el-table-column type="selection" width="50" align="center" reserve-selection />
          <el-table-column type="index" label="#" width="55" align="center" />
          <el-table-column prop="product_name" label="成品" min-width="200" sortable="custom" show-overflow-tooltip />
          <!-- 版本列表头与值统一居中 -->
          <el-table-column prop="version" label="版本" width="96" sortable="custom" align="center" show-overflow-tooltip />
          <!-- 版本说明内容很短，收窄到 120 把余量让给成品列 -->
          <el-table-column prop="version_name" label="版本说明" min-width="120" sortable="custom" show-overflow-tooltip />
          <el-table-column label="状态" width="104" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status==='生效'?'success':row.status==='失效'?'info':row.status==='已驳回'?'danger':'warning'" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <!-- 「默认损耗%」表头折行撑高表头，缩短为「损耗%」并保持不换行 -->
          <el-table-column prop="default_loss_rate" label="损耗%" width="96" sortable="custom" align="right" class-name="col-num" />
          <!-- 三个操作按钮给足宽度（≥160），统一 link 风格 -->
          <el-table-column label="操作" width="208" fixed="right" align="center">
            <template #default="{ row }">
              <el-button link type="primary" @click="onDetail(row)">明细</el-button>
              <el-button link type="primary" v-permission="'bom:edit'" @click="onEdit(row)">编辑</el-button>
              <el-button link type="success" v-permission="'bom:approve'" :disabled="row.status==='生效'" @click="onActivate(row)">设为生效</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="pager">
        <span class="hint">
          <template v-if="clientFiltered">筛选后 {{ viewList.length }} / 本页 {{ list.length }} 条 · </template>
          共 <b>{{ total }}</b> 条 · 第 {{ query.page }} / {{ pageCount }} 页
          <span v-if="clientFiltered" class="cli-tip">（版本/状态为当前页前端筛选，后端仅支持成品名称）</span>
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

    <el-dialog v-model="dialog.visible" :title="dialog.isEdit?'编辑 BOM':'新增 BOM'" width="820px">
      <el-form ref="formRef" :model="form" label-width="100px">
        <el-row :gutter="16">
          <el-col :span="8"><el-form-item label="成品">
            <el-select v-model="form.product_id" filterable :disabled="dialog.isEdit" style="width:100%">
              <el-option v-for="p in products" :key="p.id" :label="p.material_code+' '+p.material_name" :value="p.id" />
            </el-select>
          </el-form-item></el-col>
          <el-col :span="5"><el-form-item label="版本"><el-input v-model="form.version" :disabled="dialog.isEdit" placeholder="V1.0" /></el-form-item></el-col>
          <el-col :span="6"><el-form-item label="版本说明"><el-input v-model="form.version_name" /></el-form-item></el-col>
          <el-col :span="5"><el-form-item label="默认损耗%"><el-input-number v-model="form.default_loss_rate" :min="0" :precision="2" style="width:100%" /></el-form-item></el-col>
        </el-row>
        <el-form-item label="BOM 明细">
          <div style="margin-bottom:8px"><el-button size="small" :icon="Plus" @click="addItem">添加用料</el-button></div>
          <el-table :data="form.items" border size="small">
            <el-table-column label="物料" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <el-select v-model="row.material_id" filterable style="width:100%">
                  <el-option v-for="m in materials" :key="m.id" :label="m.material_code+' '+m.material_name" :value="m.id" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="单耗" width="110" align="right" class-name="col-num"><template #default="{ row }"><el-input-number v-model="row.qty" :min="0" :precision="3" style="width:100%" /></template></el-table-column>
            <el-table-column label="损耗%" width="100" align="right" class-name="col-num"><template #default="{ row }"><el-input-number v-model="row.loss_rate" :min="0" :precision="2" style="width:100%" /></template></el-table-column>
            <el-table-column label="单位" width="80" align="center"><template #default="{ row }"><el-input v-model="row.unit" /></template></el-table-column>
            <el-table-column label="操作" width="80" align="center"><template #default="{ $index }"><el-button link type="danger" @click="form.items.splice($index,1)">删除</el-button></template></el-table-column>
          </el-table>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="form.remark" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialog.visible=false">取消</el-button><el-button type="primary" :loading="submitting" @click="onSubmit">确定</el-button></template>
    </el-dialog>

    <DetailDialog v-model="detail.visible" title="BOM 明细" :doc-no="detail.data?.version"
      :status="detail.data?.status" :status-type="detail.data?.status==='生效'?'success':detail.data?.status==='已驳回'?'danger':'info'" width="1000px" :print-data="buildPrintDoc">
      <template v-if="detail.data">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="成品">{{ detail.data.product_name }}</el-descriptions-item>
          <el-descriptions-item label="版本">{{ detail.data.version }}（{{ detail.data.version_name }}）</el-descriptions-item>
          <el-descriptions-item label="状态"><el-tag :type="detail.data.status==='生效'?'success':detail.data.status==='已驳回'?'danger':'info'">{{ detail.data.status }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="默认损耗%">{{ detail.data.default_loss_rate }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.data.reject_reason" label="驳回原因" :span="2">
            <span style="color:#f56c6c">{{ detail.data.reject_reason }}</span>
          </el-descriptions-item>
        </el-descriptions>
        <el-table :data="detail.data.items" border size="small" style="margin-top:16px">
          <el-table-column prop="material_name" label="物料" show-overflow-tooltip />
          <el-table-column prop="qty" label="单耗" width="100" align="right" class-name="col-num" />
          <el-table-column prop="loss_rate" label="损耗%" width="96" align="right" class-name="col-num" />
          <el-table-column prop="unit" label="单位" width="80" align="center" />
        </el-table>
      </template>
    </DetailDialog>

    <ApprovalDialog v-model="apv.visible" title="BOM 生效审核" :doc-no="apv.data?.version" :status="apv.data?.status"
      :status-type="apv.data?.status==='生效'?'success':apv.data?.status==='失效'?'info':apv.data?.status==='已驳回'?'danger':'warning'" :loading="apv.loading"
      confirm-text="确认设为生效" warn="设为生效后，同成品的其他生效版本将自动失效，BOM 将用于生产领料计算。" @skip="onSkip" @reject="onReject" @confirm="onActivateConfirm">
      <template v-if="apv.data">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="成品">{{ apv.data.product_name }}</el-descriptions-item>
          <el-descriptions-item label="版本">{{ apv.data.version }}（{{ apv.data.version_name || '—' }}）</el-descriptions-item>
          <el-descriptions-item label="默认损耗%">{{ apv.data.default_loss_rate }}</el-descriptions-item>
          <el-descriptions-item label="备注">{{ apv.data.remark || '—' }}</el-descriptions-item>
        </el-descriptions>
        <div style="font-weight:600;margin:12px 0 8px;color:#606266">用料明细</div>
        <el-table :data="apv.data.items" border size="small">
          <el-table-column prop="material_name" label="物料" min-width="200" show-overflow-tooltip />
          <el-table-column prop="qty" label="单耗" width="100" align="right" class-name="col-num" />
          <el-table-column prop="loss_rate" label="损耗%" width="100" align="right" class-name="col-num" />
          <el-table-column prop="unit" label="单位" width="80" align="center" />
        </el-table>
      </template>
    </ApprovalDialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Search, Refresh, Plus, Files } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { bomApi } from '@/api/bom'
import { materialApi } from '@/api/basicData'
import { useSort } from '@/composables/useSort'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import SortChips from '@/components/SortChips.vue'
import BatchBar from '@/components/BatchBar.vue'
import ApprovalDialog from '@/components/ApprovalDialog.vue'
import DetailDialog from '@/components/DetailDialog.vue'
import { sumBy } from '@/utils/print'

const statusList = ['生效', '草稿', '已驳回', '失效']
const chipColor = (s) => ({ 生效: '#10b981', 草稿: '#e6a23c', 已驳回: '#f56c6c', 失效: '#909399' }[s] || '#909399')
// version / status 为本页前端筛选（后端仅支持成品名称 keyword，调用参数保持原样）
const query = reactive({ page: 1, page_size: 20, keyword: '', version: '', status: '' })
const list = ref([]); const total = ref(0); const loading = ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))
// 版本候选来自当前页数据；状态分布同样只统计当前页（纯展示）
const versionOptions = computed(() => [...new Set(list.value.map(r => r.version).filter(Boolean))])
const statusStats = computed(() => {
  const acc = {}
  for (const s of statusList) acc[s] = 0
  for (const r of list.value) if (acc[r.status] !== undefined) acc[r.status]++
  return acc
})
const clientFiltered = computed(() => !!(query.version || query.status))
const viewList = computed(() => {
  if (!clientFiltered.value) return list.value
  return list.value.filter(r =>
    (!query.version || r.version === query.version) &&
    (!query.status || r.status === query.status))
})
const materials = ref([]); const products = ref([])
const dialog = reactive({ visible: false, isEdit: false }); const submitting = ref(false); const formRef = ref()
const form = reactive({ id: null, product_id: null, version: '', version_name: '', default_loss_rate: 5, remark: '', items: [] })
const detail = reactive({ visible: false, data: null })
const apv = reactive({ visible: false, loading: false, data: null })

function addItem() { form.items.push({ material_id: null, qty: 1, loss_rate: form.default_loss_rate, unit: '个' }) }
function resetForm() { Object.assign(form, { id: null, product_id: null, version: '', version_name: '', default_loss_rate: 5, remark: '', items: [] }); addItem() }
async function fetchList() { loading.value = true; try { const res = await bomApi.list({ ...query }); list.value = res.list || []; total.value = res.total || 0 } finally { loading.value = false } }
const { onSortChange, sortRules, removeSort, clearSort } = useSort(query, fetchList)

// ---- 批量操作 ----
const batch = useBatch({ fetchList })
// 权限码取自后端 backend/app/api/v1/bom.py 的 BATCH_PERMS：activate / reject 均为 bom:approve
const batchActions = [
  { key: 'activate', label: '批量生效', perm: 'bom:approve' },
  { key: 'reject', label: '批量驳回', perm: 'bom:approve' },
  { key: 'export', label: '导出选中', perm: 'bom:view' }
]
// 导出列与表格列一一对应（状态类字段直接就是中文，无需 formatter）
const exportColumns = [
  { prop: 'product_name', label: '成品' },
  { prop: 'version', label: '版本' },
  { prop: 'version_name', label: '版本说明' },
  { prop: 'status', label: '状态' },
  { prop: 'default_loss_rate', label: '损耗%' }
]

async function onBatchAction(key) {
  if (key === 'export') {
    exportRows(batch.selected.value, exportColumns, 'BOM清单')
    return
  }
  const n = batch.count.value
  if (key === 'activate') {
    await batch.run(bomApi.batch, 'activate', {
      label: '批量生效',
      confirm: `确认把选中的 ${n} 个 BOM 版本设为生效？`
        + '设为生效后，同成品的其他生效版本会自动失效（保证单版本生效），该版本将用于生产领料与算料。'
        + '已生效的版本会被接口拒绝并逐条列出原因。'
    })
    return
  }
  await batch.run(bomApi.batch, 'reject', {
    label: '批量驳回',
    confirm: `确认驳回选中的 ${n} 个 BOM 版本？仅「草稿」状态的版本可驳回，驳回后需修改重新提交。`,
    reasonRequired: true,
    prompt: '请输入驳回原因（将记录到 BOM 上）'
  })
}

function onSearch() { query.page = 1; batch.clearSelection(); fetchList() }
function onReset() { query.keyword = ''; query.version = ''; query.status = ''; onSearch() }
function onAdd() { resetForm(); dialog.isEdit = false; dialog.visible = true }
async function onEdit(row) {
  const res = await bomApi.detail(row.id)
  Object.assign(form, { id: res.id, product_id: res.product_id, version: res.version, version_name: res.version_name, default_loss_rate: res.default_loss_rate, remark: res.remark,
    items: res.items.map(i => ({ material_id: i.material_id, qty: i.qty, loss_rate: i.loss_rate, unit: i.unit })) })
  dialog.isEdit = true; dialog.visible = true
}
async function onDetail(row) { detail.data = await bomApi.detail(row.id); detail.visible = true }

/** 组装打印数据：表头复用详情表格的列定义，meta 取单头字段，footer 放合计与备注 */
function buildPrintDoc() {
  const d = detail.data
  if (!d) return null
  const items = d.items || []
  return {
    title: 'BOM 物料清单',
    docNo: d.version,
    meta: [
      { label: '成品', value: d.product_name },
      { label: '版本', value: d.version + (d.version_name ? '（' + d.version_name + '）' : '') },
      { label: '状态', value: d.status },
      { label: '默认损耗%', value: d.default_loss_rate },
      { label: '生效日期', value: d.effective_date },
      { label: '驳回原因', value: d.reject_reason }
    ],
    columns: [
      { label: '物料', prop: 'material_name', width: 200 },
      { label: '单耗', prop: 'qty', width: 100 },
      { label: '损耗%', prop: 'loss_rate', width: 90 },
      { label: '单位', prop: 'unit', width: 80 }
    ],
    rows: items,
    footer: [
      { label: '明细行数', value: items.length },
      { label: '单耗合计', value: sumBy(items, 'qty') },
      { label: '备注', value: d.remark }
    ]
  }
}
async function onSubmit() {
  if (!form.product_id || !form.version) return ElMessage.warning('请选择成品并填写版本')
  if (form.items.some(i => !i.material_id)) return ElMessage.warning('请完善明细')
  submitting.value = true
  try { dialog.isEdit ? await bomApi.update(form.id, form) : await bomApi.create(form); ElMessage.success('保存成功'); dialog.visible = false; fetchList() } finally { submitting.value = false }
}
async function onActivate(row) {
  apv.loading = true; apv.visible = true
  try { apv.data = await bomApi.detail(row.id) } finally { apv.loading = false }
}
const apvPending = (r) => r.status !== '生效'
async function openNextPending(afterId) {
  const from = afterId != null ? list.value.findIndex(r => r.id === afterId) : -1
  let next = list.value.slice(from + 1).find(apvPending) || list.value.slice(0, from + 1).find(apvPending)
  while (!next && query.page * query.page_size < total.value) { query.page++; await fetchList(); next = list.value.find(apvPending) }
  if (next && next.id !== afterId) { await onActivate(next) } else { apv.visible = false; ElMessage.success('已全部设为生效') }
}
const onSkip = () => openNextPending(apv.data.id)
async function onReject(reason) {
  apv.loading = true
  try { await bomApi.reject(apv.data.id, reason); ElMessage.success('已驳回'); await fetchList(); await openNextPending(apv.data.id) }
  finally { apv.loading = false }
}
async function onActivateConfirm() {
  apv.loading = true
  try { await bomApi.activate(apv.data.id); ElMessage.success('已设为生效'); await fetchList(); await openNextPending(apv.data.id) }
  finally { apv.loading = false }
}

onMounted(async () => {
  fetchList()
  const res = await materialApi.list({ page: 1, page_size: 1000 })
  materials.value = res.list || []
  products.value = (res.list || []).filter(m => m.category === '成品')
})
</script>
<style scoped>
/* 本页专属：筛选条右侧的本页状态分布 + 前端筛选提示 */
.bom-stat { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); }
.bom-stat b { font-variant-numeric: tabular-nums; color: var(--text-1); }
.cli-tip { color: var(--text-3); }
</style>
