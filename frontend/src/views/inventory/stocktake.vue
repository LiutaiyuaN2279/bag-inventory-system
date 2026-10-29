<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Document /></el-icon>库存盘点</h2>
        <div class="ph-desc">按仓库快照账面生成盘点单，录入实盘后过账自动生成盘盈 / 盘亏 · 共 <b>{{ total }}</b> 条</div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
        <el-button type="primary" :icon="Plus" v-permission="'inventory:stocktake'" @click="createVisible = true">新建盘点</el-button>
      </div>
    </div>

    <el-card shadow="never" class="card-fill">
      <div class="toolbar">
        <el-form :inline="true" :model="query" class="tb-left">
          <el-form-item label="状态">
            <el-select v-model="query.status" placeholder="全部状态" clearable style="width:150px">
              <el-option label="盘点中" value="盘点中" /><el-option label="已完成" value="已完成" /><el-option label="已驳回" value="已驳回" />
            </el-select>
          </el-form-item>
          <el-form-item><el-button type="primary" :icon="Search" @click="onSearch">查询</el-button><el-button :icon="Refresh" @click="onReset">重置</el-button></el-form-item>
        </el-form>
      </div>
      <SortChips :rules="sortRules" @remove="removeSort" @clear="clearSort" />
      <BatchBar :batch="batch" :actions="batchActions" @action="onBatchAction" />
      <div class="table-wrap">
        <el-table :ref="batch.bindTable" :data="list" :row-key="(row) => row.id" v-loading="loading" border stripe
          @sort-change="onSortChange" @selection-change="batch.onSelectionChange">
          <el-table-column type="selection" width="50" align="center" reserve-selection />
          <el-table-column prop="stocktake_no" label="盘点单号" min-width="200" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="warehouse_name" label="仓库" min-width="160" sortable="custom" show-overflow-tooltip />
          <el-table-column label="状态" width="110" align="center"><template #default="{ row }"><el-tag :type="row.status==='已完成'?'success':(row.status==='已驳回'?'danger':'warning')" size="small">{{ row.status }}</el-tag></template></el-table-column>
          <el-table-column prop="created_at" label="创建时间" min-width="180" sortable="custom" show-overflow-tooltip />
          <el-table-column label="操作" width="240" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="onDetail(row)">盘点明细</el-button>
              <el-button link type="success" :disabled="row.status!=='盘点中'" @click="onApprove(row)">完成过账</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div class="pager">
        <span class="hint">共 <b>{{ total }}</b> 条 · 第 {{ query.page }} / {{ pageCount }} 页</span>
        <el-pagination background layout="sizes, prev, pager, next" :total="total"
          v-model:current-page="query.page" v-model:page-size="query.page_size"
          :page-sizes="[10, 20, 50, 100]" @current-change="fetchList" @size-change="fetchList" />
      </div>
    </el-card>

    <el-dialog v-model="createVisible" title="新建盘点单" width="420px">
      <el-form label-width="80px">
        <el-form-item label="仓库">
          <el-select v-model="newWh" style="width:100%"><el-option v-for="w in warehouses" :key="w.id" :label="w.warehouse_name" :value="w.id" /></el-select>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="createVisible=false">取消</el-button><el-button type="primary" @click="onCreate">生成盘点单</el-button></template>
    </el-dialog>

    <DetailDialog v-model="detail.visible" title="盘点明细" :doc-no="detail.data?.stocktake_no"
      :status="detail.data?.status" :status-type="detail.data?.status==='已完成'?'success':(detail.data?.status==='已驳回'?'danger':'warning')" width="1040px" :print-data="buildPrintDoc">
      <template v-if="detail.data">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="盘点单号">{{ detail.data.stocktake_no }}</el-descriptions-item>
          <el-descriptions-item label="状态"><el-tag :type="detail.data.status==='已完成'?'success':(detail.data.status==='已驳回'?'danger':'warning')">{{ detail.data.status }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="仓库" :span="2">{{ detail.data.warehouse_name }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.data.reject_reason" label="驳回原因" :span="2">
            <span style="color:#f56c6c">{{ detail.data.reject_reason }}</span>
          </el-descriptions-item>
        </el-descriptions>
        <div style="margin:12px 0">
          <el-button v-if="detail.data.status==='盘点中'" type="primary" size="small" @click="onSaveCount">保存实盘</el-button>
          <span style="color:#909399;margin-left:8px">差异 = 实盘 - 账面，过账后自动生成盘盈/盘亏</span>
        </div>
        <el-table :data="detail.data.items" border size="small">
          <el-table-column prop="material_name" label="物料" min-width="160" />
          <el-table-column prop="book_qty" label="账面" width="90" />
          <el-table-column label="实盘" width="130">
            <template #default="{ row }"><el-input-number v-model="row.counted_qty" :min="0" :precision="2" :disabled="detail.data.status==='已完成'" style="width:100%" /></template>
          </el-table-column>
          <el-table-column label="差异" width="90"><template #default="{ row }"><span :style="{color: diffQty(row)>0?'#67c23a':diffQty(row)<0?'#f56c6c':'#909399'}">{{ diffQty(row) }}</span></template></el-table-column>
        </el-table>
      </template>
    </DetailDialog>

    <ApprovalDialog v-model="apv.visible" title="盘点完成过账" :doc-no="apv.data?.stocktake_no" :status="apv.data?.status"
      :status-type="apv.data?.status==='已完成'?'success':(apv.data?.status==='已驳回'?'danger':'warning')" :loading="apv.loading" confirm-text="确认完成并过账"
      warn="过账后将按「实盘-账面」差异自动生成盘盈/盘亏并调整库存，完成后不可修改。" @skip="onSkip" @reject="onReject" @confirm="onApproveConfirm">
      <template v-if="apv.data">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="盘点单号">{{ apv.data.stocktake_no }}</el-descriptions-item>
          <el-descriptions-item label="仓库">{{ apv.data.warehouse_name }}</el-descriptions-item>
          <el-descriptions-item label="创建时间" :span="2">{{ apv.data.created_at }}</el-descriptions-item>
        </el-descriptions>
        <div style="font-weight:600;margin:12px 0 8px;color:#606266">盘点明细（差异 = 实盘 - 账面）</div>
        <el-table :data="apv.data.items" border size="small">
          <el-table-column prop="material_name" label="物料" min-width="180" />
          <el-table-column prop="book_qty" label="账面" width="100" />
          <el-table-column prop="counted_qty" label="实盘" width="100" />
          <el-table-column label="差异" width="100">
            <template #default="{ row }">
              <span :style="{ color: row.diff_qty > 0 ? '#67c23a' : row.diff_qty < 0 ? '#f56c6c' : '#909399', fontWeight: 600 }">{{ row.diff_qty }}</span>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </ApprovalDialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Search, Refresh, Plus, Document } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { stocktakeApi } from '@/api/inventory'
import { warehouseApi } from '@/api/basicData'
import { useSort } from '@/composables/useSort'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import { applyRouteFilter } from '@/composables/useAutoFilter'
import SortChips from '@/components/SortChips.vue'
import BatchBar from '@/components/BatchBar.vue'
import ApprovalDialog from '@/components/ApprovalDialog.vue'
import DetailDialog from '@/components/DetailDialog.vue'
import { sumBy } from '@/utils/print'

const query = reactive({ page: 1, page_size: 20, status: '' })
applyRouteFilter(query) // 首页待办跳转自动带筛选
const list = ref([]); const total = ref(0); const loading = ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))
const warehouses = ref([])
const createVisible = ref(false); const newWh = ref(null)
const detail = reactive({ visible: false, data: null })
const apv = reactive({ visible: false, loading: false, data: null })

// 差异 = 实盘 - 账面，随用户输入实时计算（不依赖服务端返回的 diff_qty）
const diffQty = (row) => Number(((Number(row.counted_qty) || 0) - (Number(row.book_qty) || 0)).toFixed(2))
async function fetchList() { loading.value = true; try { const res = await stocktakeApi.list({ ...query }); list.value = res.list || []; total.value = res.total || 0 } finally { loading.value = false } }
const { onSortChange, sortRules, removeSort, clearSort } = useSort(query, fetchList)

// ---- 批量操作 ----
const batch = useBatch({ fetchList })
// 权限码取自后端 BATCH_PERMS：approve / reject 均为 inventory:stocktake
const batchActions = [
  { key: 'approve', label: '批量过账', perm: 'inventory:stocktake' },
  { key: 'reject', label: '批量驳回', perm: 'inventory:stocktake' },
  { key: 'export', label: '导出选中', perm: 'inventory:stocktake' }
]
const exportColumns = [
  { prop: 'stocktake_no', label: '盘点单号' },
  { prop: 'warehouse_name', label: '仓库' },
  { prop: 'status', label: '状态' },
  { prop: 'created_at', label: '创建时间' }
]

async function onBatchAction(key) {
  if (key === 'export') {
    exportRows(batch.selected.value, exportColumns, '库存盘点')
    return
  }
  const n = batch.count.value
  if (key === 'approve') {
    await batch.run(stocktakeApi.batch, 'approve', {
      label: '批量过账',
      confirm: `确认对选中的 ${n} 张盘点单完成过账？`
        + '过账会按每张单每条明细的「实盘 − 账面」差异生成盘盈入库 / 盘亏出库流水并真实调整库存，'
        + '且不可撤销。仅「盘点中」的单据能过账，其余会逐条失败并列出原因。'
    })
    return
  }
  await batch.run(stocktakeApi.batch, 'reject', {
    label: '批量驳回',
    confirm: `确认驳回选中的 ${n} 张盘点单？仅「盘点中」的单据可驳回，驳回后需重新建单盘点。`,
    reasonRequired: true,
    prompt: '请输入驳回原因（将记录到盘点单上）'
  })
}

function onSearch() { query.page = 1; batch.clearSelection(); fetchList() }
function onReset() { query.status = ''; onSearch() }
async function onCreate() {
  if (!newWh.value) return ElMessage.warning('请选择仓库')
  await stocktakeApi.create({ warehouse_id: newWh.value }); ElMessage.success('盘点单已生成（已快照账面）')
  createVisible.value = false; fetchList()
}
async function onDetail(row) { detail.data = await stocktakeApi.detail(row.id); detail.visible = true }

/** 组装打印数据：实盘取弹窗里当前（可能还没保存）的输入值，差异按「实盘 - 账面」现算 */
function buildPrintDoc() {
  const d = detail.data
  if (!d) return null
  const items = (d.items || []).map(i => ({ ...i, diff_qty: diffQty(i) }))
  return {
    title: '库存盘点单',
    docNo: d.stocktake_no,
    meta: [
      { label: '仓库', value: d.warehouse_name },
      { label: '状态', value: d.status },
      { label: '创建时间', value: d.created_at },
      { label: '驳回原因', value: d.reject_reason }
    ],
    columns: [
      { label: '物料', prop: 'material_name', width: 160 },
      { label: '账面', prop: 'book_qty', width: 90 },
      { label: '实盘', prop: 'counted_qty', width: 100 },
      { label: '差异', prop: 'diff_qty', width: 90 }
    ],
    rows: items,
    footer: [
      { label: '账面合计', value: sumBy(items, 'book_qty') },
      { label: '实盘合计', value: sumBy(items, 'counted_qty') },
      { label: '差异合计', value: sumBy(items, 'diff_qty') },
      { label: '备注', value: d.remark }
    ]
  }
}
async function onSaveCount() {
  await stocktakeApi.count(detail.data.id, { items: detail.data.items.map(i => ({ id: i.id, counted_qty: i.counted_qty })) })
  ElMessage.success('已保存'); detail.data = await stocktakeApi.detail(detail.data.id)
}
async function onApprove(row) {
  apv.loading = true; apv.visible = true
  try { apv.data = await stocktakeApi.detail(row.id) } finally { apv.loading = false }
}
const apvPending = (r) => r.status === '盘点中'
async function openNextPending(afterId) {
  const from = afterId != null ? list.value.findIndex(r => r.id === afterId) : -1
  let next = list.value.slice(from + 1).find(apvPending) || list.value.slice(0, from + 1).find(apvPending)
  while (!next && query.page * query.page_size < total.value) { query.page++; await fetchList(); next = list.value.find(apvPending) }
  if (next && next.id !== afterId) { await onApprove(next) } else { apv.visible = false; ElMessage.success('已全部完成过账') }
}
const onSkip = () => openNextPending(apv.data.id)
async function onReject(reason) {
  apv.loading = true
  try { await stocktakeApi.reject(apv.data.id, reason); ElMessage.success('已驳回'); await fetchList(); await openNextPending(apv.data.id) }
  finally { apv.loading = false }
}
async function onApproveConfirm() {
  apv.loading = true
  try { await stocktakeApi.approve(apv.data.id); ElMessage.success('盘点完成，库存已按差异调整'); await fetchList(); await openNextPending(apv.data.id) }
  finally { apv.loading = false }
}
onMounted(async () => { fetchList(); warehouses.value = await warehouseApi.all(); newWh.value = warehouses.value[0]?.id })
</script>
