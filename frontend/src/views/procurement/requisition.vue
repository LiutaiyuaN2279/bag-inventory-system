<template>
  <div class="page">
    <!-- 页头：标题 + 说明 + 主操作（原表格卡里孤零零的按钮移到这里） -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><DocumentAdd /></el-icon>采购请购</h2>
        <div class="ph-desc">登记部门请购需求，审核通过后生效，可转为采购订单 · 共 <b>{{ total }}</b> 条</div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
        <el-button type="primary" :icon="Plus" v-permission="'purchase:requisition:add'" @click="onAdd">新增请购</el-button>
      </div>
    </div>

    <!-- 列表卡：筛选条 + 表格 + 分页（原独立筛选卡已并入 .toolbar，省掉约 88px 空白） -->
    <el-card shadow="never" class="card-fill">
      <div class="toolbar">
        <el-form :inline="true" :model="query" class="tb-left">
          <el-form-item label="单号">
            <el-input v-model="query.keyword" placeholder="请购单号" clearable style="width:180px" @keyup.enter="onSearch" />
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
          <el-table-column prop="req_no" label="请购单号" width="178" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="requisitioner" label="申请人" width="96" sortable="custom" show-overflow-tooltip />
          <!-- 部门列用 min-width（不写 width）：吸收剩余宽度，使表格铺满卡片，消除右侧留白 -->
          <el-table-column prop="dept" label="部门" min-width="112" sortable="custom" show-overflow-tooltip />
          <el-table-column label="状态" width="88" align="center">
            <template #default="{ row }"><el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" width="162" sortable="custom" show-overflow-tooltip />
          <el-table-column label="操作" width="240" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="onDetail(row)">详情</el-button>
              <el-button link type="primary" v-permission="'purchase:requisition:edit'" :disabled="row.status!=='草稿'" @click="onEdit(row)">编辑</el-button>
              <el-button link type="success" v-permission="'purchase:requisition:approve'" :disabled="row.status!=='草稿'" @click="onApprove(row)">审核</el-button>
              <el-button link type="warning" v-permission="'purchase:requisition:approve'" :disabled="row.status==='已作废'" @click="onVoid(row)">作废</el-button>
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

    <!-- 新增/编辑 -->
    <el-dialog v-model="dialog.visible" :title="dialog.isEdit?'编辑请购单':'新增请购单'" width="760px">
      <el-form ref="formRef" :model="form" label-width="90px">
        <el-row :gutter="16">
          <el-col :span="8"><el-form-item label="申请人"><el-input v-model="form.requisitioner" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="部门"><el-input v-model="form.dept" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="备注"><el-input v-model="form.remark" /></el-form-item></el-col>
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
            <el-table-column label="数量" width="120"><template #default="{ row }"><el-input-number v-model="row.qty" :min="0" :precision="2" style="width:100%" /></template></el-table-column>
            <el-table-column label="单位" width="90"><template #default="{ row }"><el-input v-model="row.unit" /></template></el-table-column>
            <el-table-column label="需求日期" width="150"><template #default="{ row }"><el-date-picker v-model="row.requirement_date" type="date" value-format="YYYY-MM-DD" style="width:100%" /></template></el-table-column>
            <el-table-column label="操作" width="70"><template #default="{ $index }"><el-button link type="danger" @click="form.items.splice($index,1)">删除</el-button></template></el-table-column>
          </el-table>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="dialog.visible=false">取消</el-button><el-button type="primary" :loading="submitting" @click="onSubmit">确定</el-button></template>
    </el-dialog>

    <!-- 详情 -->
    <DetailDialog v-model="detail.visible" title="请购单详情" :doc-no="detail.data?.req_no"
      :status="detail.data?.status" :status-type="statusType(detail.data?.status)" width="1000px" :print-data="buildPrintDoc">
      <template v-if="detail.data">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="单号">{{ detail.data.req_no }}</el-descriptions-item>
          <el-descriptions-item label="状态"><el-tag :type="statusType(detail.data.status)">{{ detail.data.status }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="申请人">{{ detail.data.requisitioner }}</el-descriptions-item>
          <el-descriptions-item label="部门">{{ detail.data.dept }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.data.reject_reason" label="驳回原因" :span="2">
            <span style="color:#f56c6c">{{ detail.data.reject_reason }}</span>
          </el-descriptions-item>
        </el-descriptions>
        <el-table :data="detail.data.items" border size="small" style="margin-top:16px">
          <el-table-column prop="material_name" label="物料" min-width="160" show-overflow-tooltip />
          <el-table-column prop="spec" label="规格" width="140" show-overflow-tooltip />
          <el-table-column prop="qty" label="数量" width="100" align="right" class-name="col-num" />
          <el-table-column prop="unit" label="单位" width="80" align="center" />
          <el-table-column prop="ordered_qty" label="已转订" width="90" align="right" class-name="col-num" />
          <el-table-column prop="requirement_date" label="需求日期" width="120" align="center" />
        </el-table>
      </template>
    </DetailDialog>

    <ApprovalDialog v-model="apv.visible" title="请购单审核" :doc-no="apv.data?.req_no" :status="apv.data?.status"
      :status-type="statusType(apv.data?.status)" :loading="apv.loading" confirm-text="确认通过审核"
      warn="审核通过后请购单生效，可转为采购订单。" @skip="onSkip" @reject="onReject" @confirm="onApproveConfirm">
      <template v-if="apv.data">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="请购单号">{{ apv.data.req_no }}</el-descriptions-item>
          <el-descriptions-item label="申请人">{{ apv.data.requisitioner }}</el-descriptions-item>
          <el-descriptions-item label="部门">{{ apv.data.dept }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ apv.data.created_at }}</el-descriptions-item>
          <el-descriptions-item label="备注" :span="2">{{ apv.data.remark || '—' }}</el-descriptions-item>
        </el-descriptions>
        <div style="font-weight:600;margin:12px 0 8px;color:#606266">请购明细</div>
        <el-table :data="apv.data.items" border size="small">
          <el-table-column prop="material_name" label="物料" min-width="180" show-overflow-tooltip />
          <el-table-column prop="spec" label="规格" width="140" show-overflow-tooltip />
          <el-table-column prop="qty" label="数量" width="100" align="right" class-name="col-num" />
          <el-table-column prop="unit" label="单位" width="80" align="center" />
          <el-table-column prop="ordered_qty" label="已转订" width="90" align="right" class-name="col-num" />
          <el-table-column prop="requirement_date" label="需求日期" width="120" align="center" />
        </el-table>
      </template>
    </ApprovalDialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Search, Refresh, Plus, DocumentAdd } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { requisitionApi } from '@/api/procurement'
import { materialApi } from '@/api/basicData'
import { useSort } from '@/composables/useSort'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import { applyRouteFilter } from '@/composables/useAutoFilter'
import SortChips from '@/components/SortChips.vue'
import BatchBar from '@/components/BatchBar.vue'
import ApprovalDialog from '@/components/ApprovalDialog.vue'
import DetailDialog from '@/components/DetailDialog.vue'
import { sumBy } from '@/utils/print'

const statusList = ['草稿', '已审核', '已关闭', '已作废', '已驳回']
const statusType = (s) => ({ 草稿: 'info', 已审核: 'success', 已关闭: '', 已作废: 'danger', 已驳回: 'danger' }[s] || '')
const query = reactive({ page: 1, page_size: 20, keyword: '', status: '' })
applyRouteFilter(query) // 首页待办跳转自动带筛选
const list = ref([]); const total = ref(0); const loading = ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))
const materials = ref([])
const matSpec = (id) => materials.value.find(m => m.id === id)?.spec || '-'
const dialog = reactive({ visible: false, isEdit: false }); const submitting = ref(false); const formRef = ref()
const form = reactive({ id: null, requisitioner: '', dept: '', remark: '', items: [] })
const detail = reactive({ visible: false, data: null })
const apv = reactive({ visible: false, loading: false, data: null })

function addItem() { form.items.push({ material_id: null, qty: 1, unit: '个', requirement_date: '' }) }
function resetForm() { Object.assign(form, { id: null, requisitioner: '', dept: '', remark: '', items: [] }); addItem() }

async function fetchList() {
  loading.value = true
  try { const res = await requisitionApi.list({ ...query }); list.value = res.list || []; total.value = res.total || 0 } finally { loading.value = false }
}
const { onSortChange, sortRules, removeSort, clearSort } = useSort(query, fetchList)

// ---- 批量操作 ----
const batch = useBatch({ fetchList })
// 动作按权限过滤：无权限的按钮不渲染（与行操作按钮一致）
// 动作名与权限码对齐后端 purchase_requisitions.py 的 BATCH_PERMS
const batchActions = [
  { key: 'approve', label: '批量审核', perm: 'purchase:requisition:approve' },
  { key: 'reject', label: '批量驳回', type: 'warning', perm: 'purchase:requisition:approve' },
  { key: 'void', label: '批量作废', type: 'danger', perm: 'purchase:requisition:approve' },
  { key: 'export', label: '导出选中', perm: 'purchase:requisition:list' }
]
// 导出用列定义与表格列保持一致，避免导出后对不上
const exportColumns = [
  { prop: 'req_no', label: '请购单号' },
  { prop: 'requisitioner', label: '申请人' },
  { prop: 'dept', label: '部门' },
  { prop: 'status', label: '状态' },
  { prop: 'created_at', label: '创建时间' }
]

async function onBatchAction(key) {
  if (key === 'export') {
    exportRows(batch.selected.value, exportColumns, '请购单清单')
    return
  }
  const labels = { approve: '批量审核', reject: '批量驳回', void: '批量作废' }
  const label = labels[key] || '批量操作'
  const n = batch.count.value
  const confirms = {
    approve: `确认审核选中的 ${n} 张请购单？审核通过后请购单生效，可转为采购订单。`,
    reject: `确认驳回选中的 ${n} 张请购单？驳回归为「已驳回」状态。`,
    void: `确认作废选中的 ${n} 张请购单？作废后单据不可再使用。`
  }
  // 驳回必须填原因（后端 _do_reject 在原因为空时会报「请填写驳回原因」）
  await batch.run(requisitionApi.batch, key, {
    label,
    confirm: confirms[key] || `确认对选中的 ${n} 张请购单执行「${label.slice(2)}」？`,
    reasonRequired: key === 'reject'
  })
}

function onSearch() { query.page = 1; batch.clearSelection(); fetchList() }
function onReset() { query.keyword = ''; query.status = ''; onSearch() }

async function loadMaterials() { const res = await materialApi.list({ page: 1, page_size: 1000 }); materials.value = res.list || [] }

function onAdd() { resetForm(); dialog.isEdit = false; dialog.visible = true }
async function onEdit(row) {
  const res = await requisitionApi.detail(row.id)
  Object.assign(form, { id: res.id, requisitioner: res.requisitioner, dept: res.dept, remark: res.remark,
    items: res.items.map(i => ({ material_id: i.material_id, qty: i.qty, unit: i.unit, requirement_date: i.requirement_date })) })
  dialog.isEdit = true; dialog.visible = true
}
async function onDetail(row) { detail.data = await requisitionApi.detail(row.id); detail.visible = true }

/** 组装打印数据：表头复用详情表格的列定义，meta 取单头字段，footer 放合计与备注 */
function buildPrintDoc() {
  const d = detail.data
  if (!d) return null
  const items = d.items || []
  return {
    title: '采购请购单',
    docNo: d.req_no,
    meta: [
      { label: '申请人', value: d.requisitioner },
      { label: '部门', value: d.dept },
      { label: '状态', value: d.status },
      { label: '驳回原因', value: d.reject_reason }
    ],
    columns: [
      { label: '物料', prop: 'material_name', width: 160 },
      { label: '规格', prop: 'spec', width: 140 },
      { label: '数量', prop: 'qty', width: 100 },
      { label: '单位', prop: 'unit', width: 80 },
      { label: '已转订', prop: 'ordered_qty', width: 90 },
      { label: '需求日期', prop: 'requirement_date', width: 120 }
    ],
    rows: items,
    footer: [
      { label: '合计数量', value: sumBy(items, 'qty') },
      { label: '备注', value: d.remark }
    ]
  }
}

async function onSubmit() {
  if (!form.items.length || form.items.some(i => !i.material_id)) return ElMessage.warning('请完善明细')
  submitting.value = true
  try {
    dialog.isEdit ? await requisitionApi.update(form.id, form) : await requisitionApi.create(form)
    ElMessage.success('保存成功'); dialog.visible = false; fetchList()
  } finally { submitting.value = false }
}
async function onApprove(row) {
  apv.loading = true; apv.visible = true
  try { apv.data = await requisitionApi.detail(row.id) } finally { apv.loading = false }
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
  try { await requisitionApi.reject(apv.data.id, reason); ElMessage.success('已驳回'); await fetchList(); await openNextPending(apv.data.id) }
  finally { apv.loading = false }
}
async function onApproveConfirm() {
  apv.loading = true
  try { await requisitionApi.approve(apv.data.id); ElMessage.success('审核成功'); await fetchList(); await openNextPending(apv.data.id) }
  finally { apv.loading = false }
}
async function onVoid(row) { try { await ElMessageBox.confirm('确认作废？', '提示', { type: 'warning' }) } catch { return }; await requisitionApi.void(row.id); ElMessage.success('已作废'); fetchList() }

onMounted(() => { fetchList(); loadMaterials() })
</script>
