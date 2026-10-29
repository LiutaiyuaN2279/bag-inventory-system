<template>
  <div class="page">
    <!-- 页头：标题 + 说明 + 主操作（原表格卡里孤零零的按钮移到这里） -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><RefreshLeft /></el-icon>采购退货</h2>
        <div class="ph-desc">登记退给供应商的物料，审核后按明细数量扣减仓库库存且不可撤销 · 共 <b>{{ total }}</b> 条</div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
        <el-button type="primary" :icon="Plus" v-permission="'purchase:return:add'" @click="onAdd">新增退货</el-button>
      </div>
    </div>

    <!-- 列表卡：筛选条 + 表格 + 分页（原独立筛选卡已并入 .toolbar，省掉约 88px 空白） -->
    <el-card shadow="never" class="card-fill">
      <div class="toolbar">
        <el-form :inline="true" :model="query" class="tb-left">
          <el-form-item label="单号">
            <el-input v-model="query.keyword" placeholder="退货单号" clearable style="width:180px" @keyup.enter="onSearch" />
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="query.status" placeholder="全部" clearable style="width:130px">
              <el-option label="草稿" value="草稿" /><el-option label="已审核" value="已审核" /><el-option label="已驳回" value="已驳回" />
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
          <el-table-column prop="return_no" label="退货单号" width="178" sortable="custom" show-overflow-tooltip />
          <!-- 供应商内容最长仅 11 字，收窄到 150px，宽度让给单号与时间 -->
          <!-- 供应商列用 min-width（不写 width）：吸收剩余宽度，使表格铺满卡片，消除右侧留白 -->
          <el-table-column prop="supplier_name" label="供应商" min-width="150" sortable="custom" show-overflow-tooltip />
          <el-table-column label="状态" width="92" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status==='已审核'?'success':(row.status==='已驳回'?'danger':'info')" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" width="162" sortable="custom" show-overflow-tooltip />
          <el-table-column label="操作" width="178" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="onDetail(row)">详情</el-button>
              <el-button link type="success" v-permission="'purchase:return:approve'" :disabled="row.status!=='草稿'" @click="onApprove(row)">审核出库</el-button>
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

    <el-dialog v-model="dialog.visible" title="新增采购退货" width="780px">
      <el-form ref="formRef" :model="form" label-width="90px">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="供应商">
              <el-select v-model="form.supplier_id" filterable placeholder="选择供应商" style="width:100%">
                <el-option v-for="s in suppliers" :key="s.id" :label="s.supplier_name" :value="s.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12"><el-form-item label="备注"><el-input v-model="form.remark" /></el-form-item></el-col>
        </el-row>
        <el-form-item label="退货明细">
          <div style="margin-bottom:8px"><el-button size="small" :icon="Plus" @click="addItem">添加明细</el-button></div>
          <el-table :data="form.items" border size="small">
            <el-table-column label="物料" min-width="180">
              <template #default="{ row }">
                <el-select v-model="row.material_id" filterable style="width:100%">
                  <el-option v-for="m in materials" :key="m.id" :label="m.material_code+' '+m.material_name" :value="m.id" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="规格" width="140"><template #default="{ row }">{{ matSpec(row.material_id) }}</template></el-table-column>
            <el-table-column label="单位" width="80" align="center"><template #default="{ row }">{{ matUnit(row.material_id) }}</template></el-table-column>
            <el-table-column label="数量" width="120" align="right" class-name="col-num"><template #default="{ row }"><el-input-number v-model="row.qty" :min="0" :precision="2" style="width:100%" /></template></el-table-column>
            <el-table-column label="仓库" width="160">
              <template #default="{ row }"><el-select v-model="row.warehouse_id" style="width:100%"><el-option v-for="w in warehouses" :key="w.id" :label="w.warehouse_name" :value="w.id" /></el-select></template>
            </el-table-column>
            <el-table-column label="操作" width="70"><template #default="{ $index }"><el-button link type="danger" @click="form.items.splice($index,1)">删除</el-button></template></el-table-column>
          </el-table>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="dialog.visible=false">取消</el-button><el-button type="primary" :loading="submitting" @click="onSubmit">确定</el-button></template>
    </el-dialog>

    <DetailDialog v-model="detail.visible" title="退货单详情" :doc-no="detail.data?.return_no"
      :status="detail.data?.status" :status-type="detail.data?.status==='已审核'?'success':(detail.data?.status==='已驳回'?'danger':'info')" width="980px" :print-data="buildPrintDoc">
      <template v-if="detail.data">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="退货单号">{{ detail.data.return_no }}</el-descriptions-item>
          <el-descriptions-item label="状态"><el-tag :type="detail.data.status==='已审核'?'success':(detail.data.status==='已驳回'?'danger':'info')">{{ detail.data.status }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="供应商" :span="2">{{ detail.data.supplier_name }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.data.reject_reason" label="驳回原因" :span="2">
            <span style="color:#f56c6c">{{ detail.data.reject_reason }}</span>
          </el-descriptions-item>
        </el-descriptions>
        <el-table :data="detail.data.items" border size="small" style="margin-top:16px">
          <el-table-column prop="material_name" label="物料" min-width="150" show-overflow-tooltip />
          <el-table-column prop="spec" label="规格" width="140" show-overflow-tooltip />
          <el-table-column prop="unit" label="单位" width="70" align="center" />
          <el-table-column prop="qty" label="数量" width="100" align="right" class-name="col-num" />
          <el-table-column prop="warehouse_name" label="仓库" width="140" show-overflow-tooltip />
        </el-table>
      </template>
    </DetailDialog>

    <ApprovalDialog v-model="apv.visible" title="退货审核出库" :doc-no="apv.data?.return_no" :status="apv.data?.status"
      :status-type="apv.data?.status==='已审核'?'success':(apv.data?.status==='已驳回'?'danger':'info')" :loading="apv.loading" confirm-text="确认审核出库"
      warn="审核通过后将按明细数量扣减对应仓库库存，出库后不可撤销。" @skip="onSkip" @reject="onReject" @confirm="onApproveConfirm">
      <template v-if="apv.data">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="退货单号">{{ apv.data.return_no }}</el-descriptions-item>
          <el-descriptions-item label="供应商">{{ apv.data.supplier_name }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ apv.data.created_at }}</el-descriptions-item>
          <el-descriptions-item label="备注">{{ apv.data.remark || '—' }}</el-descriptions-item>
        </el-descriptions>
        <div style="font-weight:600;margin:12px 0 8px;color:#606266">退货明细</div>
        <el-table :data="apv.data.items" border size="small">
          <el-table-column prop="material_name" label="物料" min-width="200" show-overflow-tooltip />
          <el-table-column prop="spec" label="规格" width="140" show-overflow-tooltip />
          <el-table-column prop="unit" label="单位" width="70" align="center" />
          <el-table-column prop="qty" label="退货数量" width="120" align="right" class-name="col-num" />
          <el-table-column prop="warehouse_name" label="出库仓库" min-width="140" show-overflow-tooltip />
        </el-table>
      </template>
    </ApprovalDialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Search, Refresh, Plus, RefreshLeft } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { returnApi } from '@/api/procurement'
import { materialApi, supplierApi, warehouseApi } from '@/api/basicData'
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
const materials = ref([]); const suppliers = ref([]); const warehouses = ref([])
const matSpec = (id) => materials.value.find(m => m.id === id)?.spec || '-'
const matUnit = (id) => materials.value.find(m => m.id === id)?.unit || '个'
const dialog = reactive({ visible: false }); const submitting = ref(false); const formRef = ref()
const form = reactive({ supplier_id: null, remark: '', items: [] })
const detail = reactive({ visible: false, data: null })
const apv = reactive({ visible: false, loading: false, data: null })
function addItem() { form.items.push({ material_id: null, qty: 1, warehouse_id: warehouses.value[0]?.id }) }
function resetForm() { Object.assign(form, { supplier_id: null, remark: '', items: [] }); addItem() }
async function fetchList() { loading.value = true; try { const res = await returnApi.list({ ...query }); list.value = res.list || []; total.value = res.total || 0 } finally { loading.value = false } }
const { onSortChange, sortRules, removeSort, clearSort } = useSort(query, fetchList)
function onSearch() { query.page = 1; batch.clearSelection(); fetchList() }
function onReset() { query.keyword = ''; query.status = ''; onSearch() }

// ---- 批量操作 ----
const batch = useBatch({ fetchList })
// 动作按权限过滤：无权限的按钮不渲染（与行操作按钮一致）
// 动作名与权限码对齐后端 purchase_returns.py 的 BATCH_PERMS
const batchActions = [
  { key: 'approve', label: '批量审核出库', perm: 'purchase:return:approve' },
  { key: 'reject', label: '批量驳回', type: 'warning', perm: 'purchase:return:approve' },
  { key: 'export', label: '导出选中', perm: 'purchase:return:list' }
]
// 导出用列定义与表格列保持一致，避免导出后对不上
const exportColumns = [
  { prop: 'return_no', label: '退货单号' },
  { prop: 'supplier_name', label: '供应商' },
  { prop: 'status', label: '状态' },
  { prop: 'created_at', label: '创建时间' }
]

async function onBatchAction(key) {
  if (key === 'export') {
    exportRows(batch.selected.value, exportColumns, '采购退货单清单')
    return
  }
  const labels = { approve: '批量审核出库', reject: '批量驳回' }
  const label = labels[key] || '批量操作'
  const n = batch.count.value
  // 审核有库存副作用，确认文案必须点明「按明细数量真实出库并生成库存流水」
  const confirms = {
    approve: `确认对选中的 ${n} 张退货单执行审核出库？将按每张单的明细数量真实扣减对应仓库库存并生成库存流水，出库后不可撤销。`,
    reject: `确认驳回选中的 ${n} 张退货单？驳回归为「已驳回」状态。`
  }
  // 驳回必须填原因（后端 _do_reject 在原因为空时会报「请填写驳回原因」）
  await batch.run(returnApi.batch, key, {
    label,
    confirm: confirms[key] || `确认对选中的 ${n} 张退货单执行「${label.slice(2)}」？`,
    reasonRequired: key === 'reject'
  })
}
function onAdd() { resetForm(); dialog.visible = true }
async function onDetail(row) { detail.data = await returnApi.detail(row.id); detail.visible = true }

/** 组装打印数据：表头复用详情表格的列定义，meta 取单头字段，footer 放合计与备注 */
function buildPrintDoc() {
  const d = detail.data
  if (!d) return null
  const items = d.items || []
  return {
    title: '采购退货单',
    docNo: d.return_no,
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
      { label: '数量', prop: 'qty', width: 100 },
      { label: '仓库', prop: 'warehouse_name', width: 140 }
    ],
    rows: items,
    footer: [
      { label: '退货合计数量', value: sumBy(items, 'qty') },
      { label: '备注', value: d.remark }
    ]
  }
}
async function onSubmit() {
  if (!form.supplier_id) return ElMessage.warning('请选择供应商')
  if (form.items.some(i => !i.material_id || !i.warehouse_id)) return ElMessage.warning('请完善明细')
  submitting.value = true
  try { await returnApi.create(form); ElMessage.success('保存成功'); dialog.visible = false; fetchList() } finally { submitting.value = false }
}
async function onApprove(row) {
  apv.loading = true; apv.visible = true
  try { apv.data = await returnApi.detail(row.id) } finally { apv.loading = false }
}
const apvPending = (r) => r.status === '草稿'
async function openNextPending(afterId) {
  const from = afterId != null ? list.value.findIndex(r => r.id === afterId) : -1
  let next = list.value.slice(from + 1).find(apvPending) || list.value.slice(0, from + 1).find(apvPending)
  while (!next && query.page * query.page_size < total.value) { query.page++; await fetchList(); next = list.value.find(apvPending) }
  if (next && next.id !== afterId) { await onApprove(next) } else { apv.visible = false; ElMessage.success('已全部审核完成') }
}
const onSkip = () => openNextPending(apv.data.id)
async function onReject(reason) {
  apv.loading = true
  try { await returnApi.reject(apv.data.id, reason); ElMessage.success('已驳回'); await fetchList(); await openNextPending(apv.data.id) }
  finally { apv.loading = false }
}
async function onApproveConfirm() {
  apv.loading = true
  try { await returnApi.approve(apv.data.id); ElMessage.success('审核成功，库存已扣减'); await fetchList(); await openNextPending(apv.data.id) }
  finally { apv.loading = false }
}
onMounted(async () => {
  fetchList()
  const [m, s, w] = await Promise.all([materialApi.list({ page: 1, page_size: 1000 }), supplierApi.list({ page: 1, page_size: 1000 }), warehouseApi.all()])
  materials.value = m.list || []; suppliers.value = s.list || []; warehouses.value = w || []
})
</script>
