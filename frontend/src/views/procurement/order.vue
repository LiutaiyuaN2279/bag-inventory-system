<template>
  <div class="page">
    <!-- 页头：标题 + 说明 + 主操作（原表格卡里孤零零的按钮移到这里） -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><ShoppingCart /></el-icon>采购订单</h2>
        <div class="ph-desc">向供应商下单并跟踪到货进度，审核后生效、可被到货单引用 · 共 <b>{{ total }}</b> 条</div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
        <el-button type="primary" :icon="Plus" v-permission="'purchase:order:add'" @click="onAdd">新增订单</el-button>
      </div>
    </div>

    <!-- 列表卡：筛选条 + 表格 + 分页（原独立筛选卡已并入 .toolbar，省掉约 88px 空白） -->
    <el-card shadow="never" class="card-fill">
      <div class="toolbar">
        <el-form :inline="true" :model="query" class="tb-left">
          <el-form-item label="单号">
            <el-input v-model="query.keyword" placeholder="采购订单号" clearable style="width:180px" @keyup.enter="onSearch" />
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="query.status" placeholder="全部" clearable style="width:130px">
              <el-option v-for="s in statusList" :key="s" :label="s" :value="s" />
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
          <el-table-column prop="order_no" label="订单号" width="176" sortable="custom" show-overflow-tooltip />
          <!-- 供应商列用 min-width（不写 width）：吸收剩余宽度，使表格铺满卡片，消除右侧留白 -->
          <el-table-column prop="supplier_name" label="供应商" min-width="150" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="total_amount" label="金额(元)" width="118" sortable="custom" align="right" class-name="col-num">
            <template #default="{ row }">{{ fmtMoney(row.total_amount) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }"><el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" width="162" sortable="custom" show-overflow-tooltip />
          <el-table-column label="操作" width="270" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="onDetail(row)">详情</el-button>
              <el-button link type="primary" v-permission="'purchase:order:edit'" :disabled="row.status!=='草稿'" @click="onEdit(row)">编辑</el-button>
              <el-button link type="success" v-permission="'purchase:order:approve'" :disabled="row.status!=='草稿'" @click="onApprove(row)">审核</el-button>
              <el-button link type="danger" v-permission="'purchase:order:approve'" :disabled="!canVoid(row)" @click="onVoid(row)">作废</el-button>
              <el-button link type="warning" v-permission="'purchase:order:approve'" :disabled="row.status!=='已作废'" @click="onUnvoid(row)">反作废</el-button>
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

    <el-dialog v-model="dialog.visible" :title="dialog.isEdit?'编辑采购订单':'新增采购订单'" width="780px">
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
        <el-form-item label="明细">
          <div style="margin-bottom:8px"><el-button size="small" :icon="Plus" @click="addItem">添加明细</el-button></div>
          <el-table :data="form.items" border size="small">
            <el-table-column label="物料" min-width="200">
              <template #default="{ row }">
                <el-select v-model="row.material_id" filterable placeholder="选择物料" style="width:100%">
                  <el-option v-for="m in materials" :key="m.id" :label="m.material_code+' '+m.material_name" :value="m.id" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="规格" width="140"><template #default="{ row }">{{ matSpec(row.material_id) }}</template></el-table-column>
            <el-table-column label="数量" width="110"><template #default="{ row }"><el-input-number v-model="row.qty" :min="0" :precision="2" style="width:100%" /></template></el-table-column>
            <el-table-column label="单价" width="120"><template #default="{ row }"><el-input-number v-model="row.unit_price" :min="0" :precision="2" style="width:100%" /></template></el-table-column>
            <el-table-column label="单位" width="80"><template #default="{ row }"><el-input v-model="row.unit" /></template></el-table-column>
            <el-table-column label="操作" width="70"><template #default="{ $index }"><el-button link type="danger" @click="form.items.splice($index,1)">删除</el-button></template></el-table-column>
          </el-table>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="dialog.visible=false">取消</el-button><el-button type="primary" :loading="submitting" @click="onSubmit">确定</el-button></template>
    </el-dialog>

    <DetailDialog v-model="detail.visible" title="采购订单详情" :doc-no="detail.data?.order_no"
      :status="detail.data?.status" :status-type="statusType(detail.data?.status)" width="1000px" :print-data="buildPrintDoc">
      <template v-if="detail.data">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="订单号">{{ detail.data.order_no }}</el-descriptions-item>
          <el-descriptions-item label="状态"><el-tag :type="statusType(detail.data.status)">{{ detail.data.status }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="供应商">{{ detail.data.supplier_name }}</el-descriptions-item>
          <el-descriptions-item label="订单金额">¥ {{ fmtMoney(detail.data.total_amount) }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.data.reject_reason" label="驳回原因" :span="2">
            <span style="color:#f56c6c">{{ detail.data.reject_reason }}</span>
          </el-descriptions-item>
        </el-descriptions>
        <el-table :data="detail.data.items" border size="small" style="margin-top:16px">
          <el-table-column prop="material_name" label="物料" min-width="160" show-overflow-tooltip />
          <el-table-column prop="spec" label="规格" width="140" show-overflow-tooltip />
          <el-table-column prop="qty" label="订购" width="90" align="right" class-name="col-num" />
          <el-table-column prop="unit" label="单位" width="70" align="center" />
          <el-table-column prop="arrived_qty" label="已到货" width="90" align="right" class-name="col-num" />
          <el-table-column prop="inbound_qty" label="已入库" width="90" align="right" class-name="col-num" />
          <el-table-column prop="unit_price" label="单价" width="90" align="right" class-name="col-num" />
        </el-table>
      </template>
    </DetailDialog>

    <ApprovalDialog v-model="apv.visible" title="采购订单审核" :doc-no="apv.data?.order_no" :status="apv.data?.status"
      :status-type="statusType(apv.data?.status)" :loading="apv.loading" confirm-text="确认通过审核"
      warn="审核通过后该订单将生效，可被到货单引用。" @skip="onSkip" @reject="onReject" @confirm="onApproveConfirm">
      <template v-if="apv.data">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="订单号">{{ apv.data.order_no }}</el-descriptions-item>
          <el-descriptions-item label="供应商">{{ apv.data.supplier_name }}</el-descriptions-item>
          <el-descriptions-item label="订单金额">¥ {{ fmtMoney(apv.data.total_amount) }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ apv.data.created_at }}</el-descriptions-item>
          <el-descriptions-item label="备注" :span="2">{{ apv.data.remark || '—' }}</el-descriptions-item>
        </el-descriptions>
        <div style="font-weight:600;margin:12px 0 8px;color:#606266">订单明细</div>
        <el-table :data="apv.data.items" border size="small">
          <el-table-column prop="material_name" label="物料" min-width="180" show-overflow-tooltip />
          <el-table-column prop="spec" label="规格" width="140" show-overflow-tooltip />
          <el-table-column prop="qty" label="数量" width="90" align="right" class-name="col-num" />
          <el-table-column prop="unit" label="单位" width="70" align="center" />
          <el-table-column prop="unit_price" label="单价" width="100" align="right" class-name="col-num">
            <template #default="{ row }">{{ fmtMoney(row.unit_price) }}</template>
          </el-table-column>
          <el-table-column label="小计" width="110" align="right" class-name="col-num">
            <template #default="{ row }">{{ fmtMoney(Number(row.qty) * Number(row.unit_price)) }}</template>
          </el-table-column>
        </el-table>
      </template>
    </ApprovalDialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Search, Refresh, Plus, ShoppingCart } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { orderApi } from '@/api/procurement'
import { materialApi, supplierApi } from '@/api/basicData'
import { useSort } from '@/composables/useSort'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import { applyRouteFilter } from '@/composables/useAutoFilter'
import SortChips from '@/components/SortChips.vue'
import BatchBar from '@/components/BatchBar.vue'
import ApprovalDialog from '@/components/ApprovalDialog.vue'
import DetailDialog from '@/components/DetailDialog.vue'
import { sumBy } from '@/utils/print'

const statusList = ['草稿', '已审核', '部分到货', '已完成', '已作废', '已驳回']
const statusType = (s) => ({ 草稿: 'info', 已审核: '', 部分到货: 'warning', 已完成: 'success', 已作废: 'danger', 已驳回: 'danger' }[s] || '')
// 已作废不可再作废；已完成订单一定挂过到货单，作废会被后端拦截，前端直接禁掉避免误导
const canVoid = (row) => ['草稿', '已审核', '部分到货'].includes(row.status)
const query = reactive({ page: 1, page_size: 20, keyword: '', status: '' })
applyRouteFilter(query) // 首页待办跳转自动带筛选
const list = ref([]); const total = ref(0); const loading = ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))
const materials = ref([]); const suppliers = ref([])
const matSpec = (id) => materials.value.find(m => m.id === id)?.spec || '-'
const matUnit = (id) => materials.value.find(m => m.id === id)?.unit || '个'
// 金额统一千分位 + 固定 2 位小数展示
const fmtMoney = (v) => Number(v || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const dialog = reactive({ visible: false, isEdit: false }); const submitting = ref(false); const formRef = ref()
const form = reactive({ id: null, supplier_id: null, remark: '', items: [] })
const detail = reactive({ visible: false, data: null })
const apv = reactive({ visible: false, loading: false, data: null })

function addItem() { form.items.push({ material_id: null, qty: 1, unit_price: 0, unit: '个' }) }
function resetForm() { Object.assign(form, { id: null, supplier_id: null, remark: '', items: [] }); addItem() }
async function fetchList() { loading.value = true; try { const res = await orderApi.list({ ...query }); list.value = res.list || []; total.value = res.total || 0 } finally { loading.value = false } }
const { onSortChange, sortRules, removeSort, clearSort } = useSort(query, fetchList)

// ---- 批量操作 ----
const batch = useBatch({ fetchList })
// 动作按权限过滤：无权限的按钮不渲染（与行操作按钮一致）
// 动作名与权限码对齐后端 purchase_orders.py 的 BATCH_PERMS
const batchActions = [
  { key: 'approve', label: '批量审核', perm: 'purchase:order:approve' },
  { key: 'reject', label: '批量驳回', type: 'warning', perm: 'purchase:order:approve' },
  { key: 'void', label: '批量作废', type: 'danger', perm: 'purchase:order:approve' },
  { key: 'unvoid', label: '批量反作废', type: 'warning', perm: 'purchase:order:approve' },
  { key: 'export', label: '导出选中', perm: 'purchase:order:list' }
]
// 导出用列定义与表格列保持一致，避免导出后对不上
const exportColumns = [
  { prop: 'order_no', label: '订单号' },
  { prop: 'supplier_name', label: '供应商' },
  { prop: 'total_amount', label: '金额(元)', formatter: (r) => fmtMoney(r.total_amount) },
  { prop: 'status', label: '状态' },
  { prop: 'created_at', label: '创建时间' }
]

async function onBatchAction(key) {
  if (key === 'export') {
    exportRows(batch.selected.value, exportColumns, '采购订单清单')
    return
  }
  const labels = { approve: '批量审核', reject: '批量驳回', void: '批量作废', unvoid: '批量反作废' }
  const label = labels[key] || '批量操作'
  const n = batch.count.value
  // 作废与反作废方向相反，文案必须写清各自后果
  const confirms = {
    approve: `确认审核选中的 ${n} 张采购订单？审核通过后订单生效，可被到货单引用。`,
    reject: `确认驳回选中的 ${n} 张采购订单？驳回归为「已驳回」状态。`,
    void: `确认作废选中的 ${n} 张采购订单？作废后该订单转出的请购数量会自动回滚；若订单下已有到货单，需先驳回或删除到货单。`,
    unvoid: `确认将选中的 ${n} 张采购订单恢复为草稿状态？恢复后需重新审核才会生效。`
  }
  // 驳回必须填原因（后端 _do_reject_order 在原因为空时会报「请填写驳回原因」）
  await batch.run(orderApi.batch, key, {
    label,
    confirm: confirms[key] || `确认对选中的 ${n} 张采购订单执行「${label.slice(2)}」？`,
    reasonRequired: key === 'reject'
  })
}

function onSearch() { query.page = 1; batch.clearSelection(); fetchList() }
function onReset() { query.keyword = ''; query.status = ''; onSearch() }
async function loadOpts() {
  const [m, s] = await Promise.all([materialApi.list({ page: 1, page_size: 1000 }), supplierApi.list({ page: 1, page_size: 1000 })])
  materials.value = m.list || []; suppliers.value = s.list || []
}
function onAdd() { resetForm(); dialog.isEdit = false; dialog.visible = true }
async function onEdit(row) {
  const res = await orderApi.detail(row.id)
  Object.assign(form, { id: res.id, supplier_id: res.supplier_id, remark: res.remark,
    items: res.items.map(i => ({ material_id: i.material_id, qty: i.qty, unit_price: i.unit_price, unit: i.unit })) })
  dialog.isEdit = true; dialog.visible = true
}
async function onDetail(row) { detail.data = await orderApi.detail(row.id); detail.visible = true }

/** 组装打印数据：表头复用详情表格的列定义，meta 取单头字段，footer 放合计与备注 */
function buildPrintDoc() {
  const d = detail.data
  if (!d) return null
  const items = d.items || []
  const amount = items.reduce((s, i) => s + (Number(i.qty) || 0) * (Number(i.unit_price) || 0), 0)
  return {
    title: '采购订单',
    docNo: d.order_no,
    meta: [
      { label: '供应商', value: d.supplier_name },
      { label: '状态', value: d.status },
      { label: '订单金额', value: d.total_amount != null ? '¥ ' + Number(d.total_amount).toFixed(2) : '' },
      { label: '下单时间', value: d.created_at },
      { label: '驳回原因', value: d.reject_reason }
    ],
    columns: [
      { label: '物料', prop: 'material_name', width: 160 },
      { label: '规格', prop: 'spec', width: 140 },
      { label: '订购', prop: 'qty', width: 90 },
      { label: '单位', prop: 'unit', width: 70 },
      { label: '已到货', prop: 'arrived_qty', width: 90 },
      { label: '已入库', prop: 'inbound_qty', width: 90 },
      { label: '单价', prop: 'unit_price', width: 90 }
    ],
    rows: items,
    footer: [
      { label: '合计订购数量', value: sumBy(items, 'qty') },
      { label: '明细金额合计', value: '¥ ' + amount.toFixed(2) },
      { label: '备注', value: d.remark }
    ]
  }
}
async function onSubmit() {
  if (!form.supplier_id) return ElMessage.warning('请选择供应商')
  if (!form.items.length || form.items.some(i => !i.material_id)) return ElMessage.warning('请完善明细')
  submitting.value = true
  try { dialog.isEdit ? await orderApi.update(form.id, form) : await orderApi.create(form); ElMessage.success('保存成功'); dialog.visible = false; fetchList() } finally { submitting.value = false }
}
async function onApprove(row) {
  apv.loading = true; apv.visible = true
  try { apv.data = await orderApi.detail(row.id) } finally { apv.loading = false }
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
  try { await orderApi.reject(apv.data.id, reason); ElMessage.success('已驳回'); await fetchList(); await openNextPending(apv.data.id) }
  finally { apv.loading = false }
}
async function onApproveConfirm() {
  apv.loading = true
  try { await orderApi.approve(apv.data.id); ElMessage.success('审核成功'); await fetchList(); await openNextPending(apv.data.id) }
  finally { apv.loading = false }
}
/** 作废订单：后端会回滚请购单的已订数量，已有到货单时会被拦截并说明原因 */
async function onVoid(row) {
  try {
    await ElMessageBox.confirm(
      `确认作废采购订单 ${row.order_no}？作废后该订单转出的请购数量会自动回滚；若订单下已有到货单，需先驳回或删除到货单。`,
      '作废确认', { type: 'warning', confirmButtonText: '确认作废', cancelButtonText: '取消' }
    )
  } catch (e) { return }
  try {
    await orderApi.void(row.id)
    ElMessage.success('已作废')
    await fetchList()
  } catch (e) { /* 失败原因由请求拦截器统一提示 */ }
}

/** 反作废：仅已作废单据可恢复，恢复后回到草稿需要重新审核 */
async function onUnvoid(row) {
  try {
    await ElMessageBox.confirm(
      `确认将采购订单 ${row.order_no} 恢复为草稿状态？恢复后需重新审核才会生效。`,
      '反作废确认', { type: 'warning', confirmButtonText: '确认恢复', cancelButtonText: '取消' }
    )
  } catch (e) { return }
  try {
    await orderApi.unvoid(row.id)
    ElMessage.success('已恢复为草稿')
    await fetchList()
  } catch (e) { /* 失败原因由请求拦截器统一提示 */ }
}

onMounted(() => { fetchList(); loadOpts() })
</script>
