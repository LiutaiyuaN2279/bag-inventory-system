<template>
  <div class="page">
    <!-- 页头：标题 + 说明 + 主操作（原表格卡里孤零零的按钮移到这里） -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Van /></el-icon>到货验收</h2>
        <div class="ph-desc">登记采购订单的到货明细，验收后按合格数自动入库并回写订单进度 · 共 <b>{{ total }}</b> 条</div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
        <el-button type="primary" :icon="Plus" v-permission="'purchase:arrival:add'" @click="onAdd">到货登记</el-button>
      </div>
    </div>

    <!-- 列表卡：筛选条 + 表格 + 分页（原独立筛选卡已并入 .toolbar，省掉约 88px 空白） -->
    <el-card shadow="never" class="card-fill">
      <div class="toolbar">
        <el-form :inline="true" :model="query" class="tb-left">
          <el-form-item label="单号">
            <el-input v-model="query.keyword" placeholder="到货单号" clearable style="width:180px" @keyup.enter="onSearch" />
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="query.status" placeholder="全部" clearable style="width:130px">
              <el-option label="待验收" value="待验收" /><el-option label="已验收" value="已验收" /><el-option label="已驳回" value="已驳回" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :icon="Search" @click="onSearch">查询</el-button>
            <el-button :icon="Refresh" @click="onReset">重置</el-button>
          </el-form-item>
        </el-form>
        <SortChips :rules="sortRules" @remove="removeSort" @clear="clearSort" />
      </div>

      <!-- 批量操作条：勾选后才出现，不占固定高度 -->
      <BatchBar :batch="batch" :actions="batchActions" @action="onBatchAction" />

      <div class="table-wrap">
        <el-table :ref="batch.bindTable" :data="list" :row-key="(row) => row.id" v-loading="loading" border stripe style="width: 100%"
          @sort-change="onSortChange" @selection-change="batch.onSelectionChange">
          <el-table-column type="selection" width="50" align="center" reserve-selection />
          <el-table-column type="index" label="#" width="55" align="center" />
          <el-table-column prop="arrival_no" label="到货单号" width="186" sortable="custom" show-overflow-tooltip />
          <!-- 供应商内容最长仅 11 字，收窄到 150px，宽度让给单号与时间 -->
          <!-- 供应商列用 min-width（不写 width）：吸收剩余宽度，使表格铺满卡片，消除右侧留白 -->
          <el-table-column prop="supplier_name" label="供应商" min-width="150" sortable="custom" show-overflow-tooltip />
          <el-table-column label="状态" width="92" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status==='已验收'?'success':(row.status==='已驳回'?'danger':'warning')" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="登记时间" width="162" sortable="custom" show-overflow-tooltip />
          <el-table-column label="操作" width="178" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="onDetail(row)">详情</el-button>
              <el-button link type="success" v-permission="'purchase:arrival:approve'" :disabled="row.status!=='待验收'" @click="onApprove(row)">验收入库</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="pager">
        <span class="hint">共 <b>{{ total }}</b> 条 · 第 {{ query.page }} / {{ pageCount }} 页</span>
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

    <el-dialog v-model="dialog.visible" title="到货登记（验收后自动入库）" width="820px">
      <el-form ref="formRef" :model="form" label-width="90px">
        <el-form-item label="采购订单">
          <el-select v-model="form.order_id" filterable placeholder="选择采购订单" style="width:100%" @change="onOrderChange">
            <el-option v-for="o in orders" :key="o.id" :label="o.order_no" :value="o.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="仓库">
          <el-select v-model="defaultWarehouse" placeholder="默认入库仓库" style="width:260px" @change="applyWarehouse">
            <el-option v-for="w in warehouses" :key="w.id" :label="w.warehouse_name" :value="w.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="到货明细">
          <el-table :data="form.items" border size="small">
            <el-table-column prop="material_name" label="物料" min-width="160" show-overflow-tooltip />
            <el-table-column prop="spec" label="规格" width="140" show-overflow-tooltip />
            <el-table-column prop="unit" label="单位" width="70" align="center" />
            <el-table-column label="到货数" width="120" align="right" class-name="col-num"><template #default="{ row }"><el-input-number v-model="row.arrived_qty" :min="0" :precision="2" style="width:100%" /></template></el-table-column>
            <el-table-column label="合格数" width="120" align="right" class-name="col-num"><template #default="{ row }"><el-input-number v-model="row.qualified_qty" :min="0" :precision="2" style="width:100%" /></template></el-table-column>
            <el-table-column label="入库仓库" width="160">
              <template #default="{ row }">
                <el-select v-model="row.warehouse_id" style="width:100%"><el-option v-for="w in warehouses" :key="w.id" :label="w.warehouse_name" :value="w.id" /></el-select>
              </template>
            </el-table-column>
          </el-table>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="form.remark" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialog.visible=false">取消</el-button><el-button type="primary" :loading="submitting" @click="onSubmit">确定</el-button></template>
    </el-dialog>

    <DetailDialog v-model="detail.visible" title="到货单详情" :doc-no="detail.data?.arrival_no"
      :status="detail.data?.status" :status-type="detail.data?.status==='已验收'?'success':(detail.data?.status==='已驳回'?'danger':'warning')" width="1000px" :print-data="buildPrintDoc">
      <template v-if="detail.data">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="到货单号">{{ detail.data.arrival_no }}</el-descriptions-item>
          <el-descriptions-item label="状态"><el-tag :type="detail.data.status==='已验收'?'success':(detail.data.status==='已驳回'?'danger':'warning')">{{ detail.data.status }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="供应商" :span="2">{{ detail.data.supplier_name }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.data.reject_reason" label="驳回原因" :span="2">
            <span style="color:#f56c6c">{{ detail.data.reject_reason }}</span>
          </el-descriptions-item>
        </el-descriptions>
        <el-table :data="detail.data.items" border size="small" style="margin-top:16px">
          <el-table-column prop="material_name" label="物料" min-width="150" show-overflow-tooltip />
          <el-table-column prop="spec" label="规格" width="140" show-overflow-tooltip />
          <el-table-column prop="unit" label="单位" width="70" align="center" />
          <el-table-column prop="arrived_qty" label="到货" width="80" align="right" class-name="col-num" />
          <el-table-column prop="qualified_qty" label="合格" width="80" align="right" class-name="col-num" />
          <el-table-column prop="warehouse_name" label="仓库" width="120" show-overflow-tooltip />
        </el-table>
      </template>
    </DetailDialog>

    <ApprovalDialog v-model="apv.visible" title="到货验收入库" :doc-no="apv.data?.arrival_no" :status="apv.data?.status"
      :status-type="apv.data?.status==='已验收'?'success':(apv.data?.status==='已驳回'?'danger':'warning')" :loading="apv.loading" confirm-text="确认验收入库"
      warn="验收后将按合格数自动入库，并更新对应采购订单的到货/入库进度。" @skip="onSkip" @reject="onReject" @confirm="onApproveConfirm">
      <template v-if="apv.data">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="到货单号">{{ apv.data.arrival_no }}</el-descriptions-item>
          <el-descriptions-item label="供应商">{{ apv.data.supplier_name }}</el-descriptions-item>
          <el-descriptions-item label="登记时间">{{ apv.data.created_at }}</el-descriptions-item>
          <el-descriptions-item label="备注">{{ apv.data.remark || '—' }}</el-descriptions-item>
        </el-descriptions>
        <div style="font-weight:600;margin:12px 0 8px;color:#606266">到货明细（按合格数入库）</div>
        <el-table :data="apv.data.items" border size="small">
          <el-table-column prop="material_name" label="物料" min-width="180" show-overflow-tooltip />
          <el-table-column prop="spec" label="规格" width="140" show-overflow-tooltip />
          <el-table-column prop="unit" label="单位" width="70" align="center" />
          <el-table-column prop="arrived_qty" label="到货数" width="100" align="right" class-name="col-num" />
          <el-table-column prop="qualified_qty" label="合格数" width="100" align="right" class-name="col-num" />
          <el-table-column prop="warehouse_name" label="入库仓库" min-width="120" show-overflow-tooltip />
        </el-table>
      </template>
    </ApprovalDialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Search, Refresh, Plus, Van } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { arrivalApi, orderApi } from '@/api/procurement'
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

const query = reactive({ page: 1, page_size: 20, keyword: '', status: '' })
applyRouteFilter(query) // 首页待办跳转自动带筛选
const list = ref([]); const total = ref(0); const loading = ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))
const orders = ref([]); const warehouses = ref([])
const dialog = reactive({ visible: false }); const submitting = ref(false); const formRef = ref()
const form = reactive({ order_id: null, remark: '', items: [] })
const defaultWarehouse = ref(null)
const detail = reactive({ visible: false, data: null })
const apv = reactive({ visible: false, loading: false, data: null })

async function fetchList() { loading.value = true; try { const res = await arrivalApi.list({ ...query }); list.value = res.list || []; total.value = res.total || 0 } finally { loading.value = false } }
const { onSortChange, sortRules, removeSort, clearSort } = useSort(query, fetchList)
function onSearch() { query.page = 1; batch.clearSelection(); fetchList() }
function onReset() { query.keyword = ''; query.status = ''; onSearch() }

// ---- 批量操作 ----
const batch = useBatch({ fetchList })
// 动作按权限过滤：无权限的按钮不渲染（与行操作按钮一致）
// 动作名与权限码对齐后端 purchase_arrivals.py 的 BATCH_PERMS
const batchActions = [
  { key: 'approve', label: '批量验收入库', perm: 'purchase:arrival:approve' },
  { key: 'reject', label: '批量驳回', type: 'warning', perm: 'purchase:arrival:approve' },
  { key: 'export', label: '导出选中', perm: 'purchase:arrival:list' }
]
// 导出用列定义与表格列保持一致，避免导出后对不上
const exportColumns = [
  { prop: 'arrival_no', label: '到货单号' },
  { prop: 'supplier_name', label: '供应商' },
  { prop: 'status', label: '状态' },
  { prop: 'created_at', label: '登记时间' }
]

async function onBatchAction(key) {
  if (key === 'export') {
    exportRows(batch.selected.value, exportColumns, '到货单清单')
    return
  }
  const labels = { approve: '批量验收入库', reject: '批量驳回' }
  const label = labels[key] || '批量操作'
  const n = batch.count.value
  // 验收有库存副作用，确认文案必须点明「按明细数量真实入库并生成库存流水」
  const confirms = {
    approve: `确认对选中的 ${n} 张到货单执行验收入库？将按每张单的明细合格数量真实入库并生成库存流水，同时回写对应采购订单的到货/入库进度，入库后不可撤销。`,
    reject: `确认驳回选中的 ${n} 张到货单？驳回会回滚订单明细已累计的到货数并置为「已驳回」。`
  }
  // 驳回必须填原因（后端 _do_reject 在原因为空时会报「请填写驳回原因」）
  await batch.run(arrivalApi.batch, key, {
    label,
    confirm: confirms[key] || `确认对选中的 ${n} 张到货单执行「${label.slice(2)}」？`,
    reasonRequired: key === 'reject'
  })
}

async function onAdd() {
  form.order_id = null; form.remark = ''; form.items = []
  const res = await orderApi.list({ page: 1, page_size: 1000, status: '已审核' })
  orders.value = res.list || []
  dialog.visible = true
}
async function onOrderChange(oid) {
  const res = await orderApi.detail(oid)
  form.items = res.items.map(i => ({ order_item_id: i.id, material_id: i.material_id, material_name: i.material_name,
    spec: i.spec || '', unit: i.unit || '', arrived_qty: i.qty, qualified_qty: i.qty, warehouse_id: defaultWarehouse.value || warehouses.value[0]?.id }))
}
function applyWarehouse(wid) { form.items.forEach(i => { i.warehouse_id = wid }) }

async function onSubmit() {
  if (!form.order_id) return ElMessage.warning('请选择采购订单')
  if (form.items.some(i => !i.warehouse_id)) return ElMessage.warning('请填写入库仓库')
  if (form.items.some(i => (i.qualified_qty || 0) > (i.arrived_qty || 0))) return ElMessage.warning('合格数不能大于到货数')
  if (form.items.reduce((s, i) => s + (Number(i.arrived_qty) || 0), 0) <= 0) return ElMessage.warning('到货数量不能全为 0，请填写实际到货数')
  submitting.value = true
  try { await arrivalApi.create({ order_id: form.order_id, remark: form.remark, items: form.items }); ElMessage.success('登记成功'); dialog.visible = false; fetchList() } finally { submitting.value = false }
}
async function onDetail(row) { detail.data = await arrivalApi.detail(row.id); detail.visible = true }

/** 组装打印数据：表头复用详情表格的列定义，meta 取单头字段，footer 放合计与备注 */
function buildPrintDoc() {
  const d = detail.data
  if (!d) return null
  const items = d.items || []
  return {
    title: '采购到货单',
    docNo: d.arrival_no,
    meta: [
      { label: '供应商', value: d.supplier_name },
      { label: '状态', value: d.status },
      { label: '登记时间', value: d.created_at },
      { label: '驳回原因', value: d.reject_reason }
    ],
    columns: [
      { label: '物料', prop: 'material_name', width: 150 },
      { label: '规格', prop: 'spec', width: 140 },
      { label: '单位', prop: 'unit', width: 70 },
      { label: '到货', prop: 'arrived_qty', width: 80 },
      { label: '合格', prop: 'qualified_qty', width: 80 },
      { label: '仓库', prop: 'warehouse_name', width: 120 }
    ],
    rows: items,
    footer: [
      { label: '到货合计', value: sumBy(items, 'arrived_qty') },
      { label: '合格合计', value: sumBy(items, 'qualified_qty') },
      { label: '备注', value: d.remark }
    ]
  }
}
async function onApprove(row) {
  apv.loading = true; apv.visible = true
  try { apv.data = await arrivalApi.detail(row.id) } finally { apv.loading = false }
}
const apvPending = (r) => r.status === '待验收'
async function openNextPending(afterId) {
  const from = afterId != null ? list.value.findIndex(r => r.id === afterId) : -1
  let next = list.value.slice(from + 1).find(apvPending) || list.value.slice(0, from + 1).find(apvPending)
  while (!next && query.page * query.page_size < total.value) { query.page++; await fetchList(); next = list.value.find(apvPending) }
  if (next && next.id !== afterId) { await onApprove(next) } else { apv.visible = false; ElMessage.success('已全部验收完成') }
}
const onSkip = () => openNextPending(apv.data.id)
async function onReject(reason) {
  apv.loading = true
  try { await arrivalApi.reject(apv.data.id, reason); ElMessage.success('已驳回'); await fetchList(); await openNextPending(apv.data.id) }
  finally { apv.loading = false }
}
async function onApproveConfirm() {
  apv.loading = true
  try { await arrivalApi.approve(apv.data.id); ElMessage.success('验收成功，库存已更新'); await fetchList(); await openNextPending(apv.data.id) }
  finally { apv.loading = false }
}
onMounted(async () => { fetchList(); warehouses.value = await warehouseApi.all() })
</script>
