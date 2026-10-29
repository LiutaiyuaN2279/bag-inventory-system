<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Van /></el-icon>仓库调拨</h2>
        <div class="ph-desc">跨仓库调拨单的建单、审核与作废，审核后自动增减两仓库存 · 共 <b>{{ total }}</b> 条</div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
        <el-button type="primary" :icon="Plus" v-permission="'inventory:transfer:add'" @click="onAdd">新增调拨</el-button>
      </div>
    </div>

    <!-- ===== 搜索 + 列表区（合并为一张撑满卡片） ===== -->
    <el-card shadow="never" class="card-fill">
      <div class="toolbar">
        <el-form :inline="true" :model="query" class="tb-left">
          <el-form-item label="关键字">
            <el-input v-model="query.keyword" placeholder="调拨单号" clearable style="width: 200px" @keyup.enter="onSearch" />
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="query.status" placeholder="全部" clearable style="width: 140px">
              <el-option label="草稿" value="草稿" />
              <el-option label="已审核" value="已审核" />
              <el-option label="已作废" value="已作废" />
            </el-select>
          </el-form-item>
          <template v-if="searchExpanded">
            <el-form-item label="调出仓库">
              <el-select v-model="query.from_warehouse_id" placeholder="全部" clearable style="width: 160px">
                <el-option v-for="w in warehouses" :key="w.id" :label="w.warehouse_name" :value="w.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="调入仓库">
              <el-select v-model="query.to_warehouse_id" placeholder="全部" clearable style="width: 160px">
                <el-option v-for="w in warehouses" :key="w.id" :label="w.warehouse_name" :value="w.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="创建日期">
              <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" unlink-panels
                range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" style="width: 260px" />
            </el-form-item>
          </template>
          <el-form-item>
            <el-button type="primary" :icon="Search" @click="onSearch">查询</el-button>
            <el-button :icon="Refresh" @click="onReset">重置</el-button>
            <el-button :icon="searchExpanded ? ArrowUp : ArrowDown" @click="searchExpanded = !searchExpanded">
              {{ searchExpanded ? '收起筛选' : '更多筛选' }}
            </el-button>
          </el-form-item>
        </el-form>
      </div>
      <SortChips :rules="sortRules" @remove="removeSort" @clear="clearSort" />
      <BatchBar :batch="batch" :actions="batchActions" @action="onBatchAction" />
      <div class="table-wrap">
        <el-table :ref="batch.bindTable" :data="list" :row-key="(row) => row.id" v-loading="loading" border stripe
          @sort-change="onSortChange" @selection-change="batch.onSelectionChange">
          <el-table-column type="selection" width="50" align="center" reserve-selection />
          <el-table-column type="index" label="#" width="55" align="center" />
          <el-table-column prop="transfer_no" label="调拨单号" min-width="190" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="from_warehouse_name" label="调出仓库" min-width="150" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="to_warehouse_name" label="调入仓库" min-width="150" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="item_count" label="明细数" width="100" align="right" class-name="col-num" sortable="custom" />
          <el-table-column prop="status" label="状态" width="100" align="center" sortable="custom">
            <template #default="{ row }">
              <el-tag :type="statusTag(row.status)" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="operator" label="经办人" width="100" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="created_at" label="创建时间" width="170" sortable="custom" show-overflow-tooltip />
          <el-table-column label="操作" width="240" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="onDetail(row)">详情</el-button>
              <el-button v-if="row.status === '草稿'" link type="primary" v-permission="'inventory:transfer:edit'"
                @click="onEdit(row)">编辑</el-button>
              <el-button v-if="row.status === '草稿'" link type="success" v-permission="'inventory:transfer:approve'"
                @click="onApprove(row)">审核</el-button>
              <el-button v-if="row.status === '草稿' || row.status === '已审核'" link type="danger"
                v-permission="'inventory:transfer:delete'" @click="onVoid(row)">作废</el-button>
            </template>
          </el-table-column>
          <!-- 空态：文案与「新增调拨」入口放在同一个视觉块里，不留空旷的白块 -->
          <template #empty>
            <div class="empty-block">
              <div class="eb-title">暂无调拨单</div>
              <div class="eb-desc">仓库之间转移物料时先建调拨单：审核后自动扣减调出仓、增加调入仓库存。</div>
              <el-button type="primary" :icon="Plus" v-permission="'inventory:transfer:add'" @click="onAdd">新增调拨</el-button>
            </div>
          </template>
        </el-table>
      </div>
      <div class="pager">
        <span class="hint">共 <b>{{ total }}</b> 条 · 第 {{ query.page }} / {{ pageCount }} 页</span>
        <el-pagination background layout="sizes, prev, pager, next" :total="total"
          v-model:current-page="query.page" v-model:page-size="query.page_size"
          :page-sizes="[10, 20, 50, 100]" @current-change="fetchList" @size-change="fetchList" />
      </div>
    </el-card>

    <!-- ===== 新增 / 编辑弹窗 ===== -->
    <el-dialog v-model="dialog.visible" :title="dialog.isEdit ? '编辑调拨单' : '新增调拨单'" width="1020px"
      :close-on-click-modal="false" @closed="onDialogClosed">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="调出仓库" prop="from_warehouse_id">
              <el-select v-model="form.from_warehouse_id" placeholder="请选择调出仓库" clearable style="width: 100%"
                @change="onFromWarehouseChange">
                <el-option v-for="w in warehouses" :key="w.id" :label="w.warehouse_name" :value="w.id"
                  :disabled="w.id === form.to_warehouse_id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="调入仓库" prop="to_warehouse_id">
              <el-select v-model="form.to_warehouse_id" placeholder="请选择调入仓库" clearable style="width: 100%">
                <el-option v-for="w in warehouses" :key="w.id" :label="w.warehouse_name" :value="w.id"
                  :disabled="w.id === form.from_warehouse_id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="经办人">
              <el-input v-model="form.operator" placeholder="留空则取当前登录用户" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="备注">
              <el-input v-model="form.remark" placeholder="选填" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>

      <div class="items-head">
        <span class="items-title">调拨明细</span>
        <span class="items-tip">物料需从「调出仓库」的现有库存中选择，库位与缸号批次会自动带出</span>
        <el-button type="primary" :icon="Plus" size="small" @click="addItem">添加一行</el-button>
      </div>
      <el-table :data="form.items" border size="small" :empty-text="form.from_warehouse_id ? '暂无明细，请点击「添加一行」' : '请先选择调出仓库'">
        <el-table-column label="物料（来自调出仓库库存）" min-width="320">
          <template #default="{ row }">
            <el-select v-model="row.inv_id" filterable clearable :disabled="!form.from_warehouse_id"
              :placeholder="form.from_warehouse_id ? '请选择物料/库位/批次' : '请先选择调出仓库'" style="width: 100%"
              @change="(v) => onInvChange(row, v)">
              <el-option v-for="o in optionsForRow(row)" :key="o.id" :label="invLabel(o)" :value="o.id" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="可用库存" width="100">
          <template #default="{ row }">
            <span :class="{ 'low': overQty(row) }">{{ row.available == null ? '-' : row.available }}</span>
          </template>
        </el-table-column>
        <el-table-column label="调拨数量" width="170">
          <template #default="{ row }">
            <el-input-number v-model="row.qty" :min="0.01" :precision="2" :step="1" controls-position="right"
              style="width: 100%" />
            <div v-if="overQty(row)" class="qty-warn">超出可用库存 {{ row.available }}</div>
          </template>
        </el-table-column>
        <el-table-column label="单位" width="90">
          <template #default="{ row }"><el-input v-model="row.unit" placeholder="个" /></template>
        </el-table-column>
        <el-table-column label="备注" min-width="140">
          <template #default="{ row }"><el-input v-model="row.remark" placeholder="选填" /></template>
        </el-table-column>
        <el-table-column label="操作" width="70" fixed="right">
          <template #default="{ $index }">
            <el-button link type="danger" @click="removeItem($index)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <template #footer>
        <el-button @click="dialog.visible = false">取 消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmit">确 定</el-button>
      </template>
    </el-dialog>

    <!-- ===== 详情弹窗 ===== -->
    <el-dialog v-model="detail.visible" title="调拨单详情" width="1000px">
      <template v-if="detail.data">
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="调拨单号">{{ detail.data.transfer_no }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTag(detail.data.status)" size="small">{{ detail.data.status }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="经办人">{{ detail.data.operator || '-' }}</el-descriptions-item>
          <el-descriptions-item label="调出仓库">{{ detail.data.from_warehouse_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="调入仓库">{{ detail.data.to_warehouse_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="库存已执行">{{ detail.data.executed ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ detail.data.created_at || '-' }}</el-descriptions-item>
          <el-descriptions-item label="审核时间">{{ detail.data.approve_time || '-' }}</el-descriptions-item>
          <el-descriptions-item label="作废时间">{{ detail.data.void_time || '-' }}</el-descriptions-item>
          <el-descriptions-item label="备注" :span="3">{{ detail.data.remark || '-' }}</el-descriptions-item>
        </el-descriptions>

        <div class="detail-title">调拨明细（{{ detail.data.items?.length || 0 }} 行）</div>
        <el-table :data="detail.data.items || []" border size="small">
          <el-table-column type="index" label="#" width="55" />
          <el-table-column prop="material_name" label="物料名称" min-width="140" />
          <el-table-column label="规格" width="120">
            <template #default="{ row }">{{ row.spec || '-' }}</template>
          </el-table-column>
          <el-table-column prop="qty" label="数量" width="90" />
          <el-table-column prop="unit" label="单位" width="80" />
          <el-table-column label="缸号/色号" width="120">
            <template #default="{ row }">{{ row.color_batch_no || '-' }}</template>
          </el-table-column>
          <el-table-column label="调出库位" width="120">
            <template #default="{ row }">{{ row.from_location_name || '-' }}</template>
          </el-table-column>
          <el-table-column label="调入库位" width="120">
            <template #default="{ row }">{{ row.to_location_name || '-' }}</template>
          </el-table-column>
          <el-table-column label="备注" min-width="120">
            <template #default="{ row }">{{ row.remark || '-' }}</template>
          </el-table-column>
        </el-table>
        <div class="detail-total">合计数量：{{ detailTotalQty }}</div>
      </template>
      <template #footer>
        <el-button @click="detail.visible = false">关 闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Search, Refresh, Plus, ArrowDown, ArrowUp, Van } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { transferApi } from '@/api/transfer'
import { inventoryApi } from '@/api/inventory'
import { materialApi, warehouseApi } from '@/api/basicData'
import { useSort } from '@/composables/useSort'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import SortChips from '@/components/SortChips.vue'
import BatchBar from '@/components/BatchBar.vue'

// ---------------- 列表 ----------------
const query = reactive({
  page: 1, page_size: 20, keyword: '', status: '',
  from_warehouse_id: null, to_warehouse_id: null
})
const list = ref([])
const total = ref(0)
const loading = ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))
const searchExpanded = ref(false)
const dateRange = ref([])
const warehouses = ref([])
const unitMap = ref({}) // { material_id: 单位 }

// 状态 → el-tag 类型：草稿 info、已审核 success、已作废 danger
const statusTag = (s) => (s === '已审核' ? 'success' : (s === '已作废' ? 'danger' : 'info'))

async function fetchList() {
  loading.value = true
  try {
    const res = await transferApi.list({
      ...query,
      start_date: dateRange.value?.[0] || '',
      end_date: dateRange.value?.[1] || ''
    })
    list.value = res.list || []
    total.value = res.total || 0
  } catch (e) {
    // 错误提示由 request 拦截器统一负责，这里只兜底数据，避免页面崩溃
    list.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}
const { onSortChange, sortRules, removeSort, clearSort } = useSort(query, fetchList)

// ---- 批量操作 ----
const batch = useBatch({ fetchList })
// 权限码取自后端 transfers.py 的 BATCH_PERMS：approve → inventory:transfer:approve、void → inventory:transfer:delete
const batchActions = [
  { key: 'approve', label: '批量审核', perm: 'inventory:transfer:approve' },
  { key: 'void', label: '批量作废', type: 'danger', perm: 'inventory:transfer:delete' },
  { key: 'export', label: '导出选中', perm: 'inventory:view' }
]
const exportColumns = [
  { prop: 'transfer_no', label: '调拨单号' },
  { prop: 'from_warehouse_name', label: '调出仓库' },
  { prop: 'to_warehouse_name', label: '调入仓库' },
  { prop: 'item_count', label: '明细数' },
  { prop: 'status', label: '状态' },
  { prop: 'operator', label: '经办人' },
  { prop: 'created_at', label: '创建时间' }
]

async function onBatchAction(key) {
  if (key === 'export') {
    exportRows(batch.selected.value, exportColumns, '仓库调拨')
    return
  }
  const n = batch.count.value
  if (key === 'approve') {
    await batch.run(transferApi.batch, 'approve', {
      label: '批量审核',
      confirm: `确认审核选中的 ${n} 张调拨单？`
        + '审核会真实执行库存动作：按每条明细的调出仓库扣减、调入仓库增加；'
        + '调出仓库库存不足的单据会被拒绝并逐条列出原因（该单库存不被改动）。仅「草稿」单据可审核。'
    })
    return
  }
  // 批量作废：方法名是 voidOrder，但批量动作 key 仍是 'void'
  await batch.run(transferApi.batch, 'void', {
    label: '批量作废',
    confirm: `确认作废选中的 ${n} 张调拨单？`
      + '对已执行过库存动作的单据，作废会把调出仓库库存加回、调入仓库扣减（反向冲回）；'
      + '若调入仓库库存不足，作废会被拒绝并逐条列出原因。'
  })
}

function onSearch() { query.page = 1; batch.clearSelection(); fetchList() }
function onReset() {
  query.keyword = ''
  query.status = ''
  query.from_warehouse_id = null
  query.to_warehouse_id = null
  dateRange.value = []
  onSearch()
}

// ---------------- 新增 / 编辑 ----------------
const dialog = reactive({ visible: false, isEdit: false })
const submitting = ref(false)
const formRef = ref()
const form = reactive({
  id: null, from_warehouse_id: null, to_warehouse_id: null, operator: '', remark: '', items: []
})
const rules = {
  from_warehouse_id: [{ required: true, message: '请选择调出仓库', trigger: 'change' }],
  to_warehouse_id: [{ required: true, message: '请选择调入仓库', trigger: 'change' }]
}
// 调出仓库的库存台账（物料 + 库位 + 缸号批次），明细行只能从这里选，保证与后端扣减维度一致
const invOptions = ref([])
// 兜底选项 id 计数器：编辑回填时若库存下拉里找不到原维度，用合成选项显示原文本，避免显示空白
let fbSeq = 0
const newFallbackId = () => `fb-${++fbSeq}`

function newItem() {
  return {
    inv_id: null, material_id: null, material_name: '', qty: 1, unit: '个',
    color_batch_id: null, from_location_id: null,
    available: null, fallbackId: '', fallback: '', remark: ''
  }
}
function resetForm() {
  Object.assign(form, {
    id: null, from_warehouse_id: null, to_warehouse_id: null, operator: '', remark: '', items: []
  })
  formRef.value?.clearValidate?.()
}
function onDialogClosed() {
  resetForm()
  invOptions.value = []
}
function onAdd() {
  resetForm()
  invOptions.value = []
  dialog.isEdit = false
  dialog.visible = true
  form.items.push(newItem())
}
async function onEdit(row) {
  resetForm()
  invOptions.value = []
  dialog.isEdit = true
  dialog.visible = true
  try {
    const d = await transferApi.detail(row.id)
    form.id = d.id
    form.from_warehouse_id = d.from_warehouse_id ?? null
    form.to_warehouse_id = d.to_warehouse_id ?? null
    form.operator = d.operator || ''
    form.remark = d.remark || ''
    await loadInventory() // 先按调出仓库拉库存，再回填明细（程序赋值不会触发 change，明细不会被清空）
    form.items = (d.items || []).map((it) => backfillItem(it))
  } catch (e) {
    // 详情拉取失败：request 拦截器已提示，直接关掉弹窗，不留半截数据
    dialog.visible = false
  }
}

/** 拉取调出仓库的现有库存作为明细行候选项 */
async function loadInventory() {
  invOptions.value = []
  if (!form.from_warehouse_id) return
  try {
    const res = await inventoryApi.list({ warehouse_id: form.from_warehouse_id, page: 1, page_size: 1000 })
    invOptions.value = res.list || []
  } catch (e) {
    invOptions.value = [] // 拦截器已提示，保持空选项即可
  }
}

/** 切换调出仓库：库存维度整体变化，已选明细必须清空重选 */
async function onFromWarehouseChange() {
  form.items.forEach((it) => {
    Object.assign(it, newItem(), { qty: it.qty })
  })
  ElMessage.info('调出仓库已变更，请重新选择明细物料')
  await loadInventory()
}

function addItem() { form.items.push(newItem()) }
function removeItem(idx) { form.items.splice(idx, 1) }

/** 选项 label：物料名 + 库位ID + 批次ID + 可用数量（同一物料的多个库位/批次可区分） */
function invLabel(o) {
  if (o.__fallback) return o.label
  const parts = [o.material_name || `物料#${o.material_id}`]
  if (o.location_id != null) parts.push(`库位ID: ${o.location_id}`)
  if (o.color_batch_id != null) parts.push(`批次ID: ${o.color_batch_id}`)
  parts.push(`可用 ${o.qty}`)
  return parts.join(' | ')
}

/** 某行可选的下拉项：库存台账 + 编辑回填时找不到维度的兜底合成项 */
function optionsForRow(row) {
  if (row.fallbackId && !invOptions.value.some((o) => o.id === row.inv_id)) {
    return [...invOptions.value, { id: row.fallbackId, __fallback: true, label: row.fallback }]
  }
  return invOptions.value
}

/** 选中库存行：把物料/库位/缸号批次三个维度一起落到明细行上 */
function onInvChange(row, val) {
  if (val == null || val === '') {
    // 清空选择：三个维度一起清掉，避免留下「有物料没库位」的半截数据
    Object.assign(row, newItem(), { qty: row.qty, remark: row.remark })
    return
  }
  const o = invOptions.value.find((x) => x.id === val)
  if (!o) return // 兜底合成项：维度沿用回填时的值，不覆盖
  row.material_id = o.material_id ?? null
  row.material_name = o.material_name || ''
  row.color_batch_id = o.color_batch_id ?? null
  row.from_location_id = o.location_id ?? null
  row.available = Number(o.qty)
  row.unit = unitMap.value[o.material_id] || '个'
  row.fallbackId = ''
  row.fallback = ''
}

/** 编辑回填：优先匹配库存下拉中同维度（物料+库位+缸号批次）的行 */
function backfillItem(it) {
  const row = newItem()
  row.qty = Number(it.qty) || 1
  row.unit = it.unit || '个'
  row.remark = it.remark || ''
  row.material_id = it.material_id ?? null
  row.material_name = it.material_name || ''
  row.color_batch_id = it.color_batch_id ?? null
  row.from_location_id = it.from_location_id ?? null
  const hit = invOptions.value.find((o) => o.material_id === row.material_id
    && (o.color_batch_id ?? null) === row.color_batch_id
    && (o.location_id ?? null) === row.from_location_id)
  if (hit) {
    row.inv_id = hit.id
    row.available = Number(hit.qty)
  } else {
    // 当前库存里没有该维度（可能已被扣完），用详情返回的文本兜底显示，不让用户以为数据丢了
    row.fallbackId = newFallbackId()
    row.inv_id = row.fallbackId
    row.available = null
    row.fallback = [
      it.material_name || `物料#${it.material_id}`,
      it.color_batch_no ? `缸号/色号: ${it.color_batch_no}` : '',
      it.from_location_name ? `调出库位: ${it.from_location_name}` : '',
      '（当前库存中未找到该维度，提交后后端会校验）'
    ].filter(Boolean).join(' | ')
  }
  return row
}

/** 行内超额提示：填写的调拨数量大于可用库存 */
function overQty(row) {
  return row.available != null && Number(row.qty) > Number(row.available)
}

async function onSubmit() {
  // 表头必填 + 两仓库不能相同
  if (!formRef.value || !(await formRef.value.validate().catch(() => false))) return
  if (form.from_warehouse_id === form.to_warehouse_id) return ElMessage.warning('调出仓库与调入仓库不能相同')
  if (!form.items.length) return ElMessage.warning('请至少添加一条调拨明细')
  // 逐行校验：必须选了物料、数量必须大于 0
  for (let i = 0; i < form.items.length; i++) {
    const it = form.items[i]
    const no = i + 1
    if (it.inv_id == null || it.material_id == null) return ElMessage.warning(`第 ${no} 行：请选择调拨物料`)
    if (!(Number(it.qty) > 0)) return ElMessage.warning(`第 ${no} 行：调拨数量必须大于 0`)
  }
  submitting.value = true
  try {
    const payload = {
      from_warehouse_id: form.from_warehouse_id,
      to_warehouse_id: form.to_warehouse_id,
      operator: form.operator || '',
      remark: form.remark || '',
      items: form.items.map((it) => ({
        material_id: it.material_id,
        qty: Number(it.qty) || 0,
        unit: it.unit || '个',
        color_batch_id: it.color_batch_id ?? null,
        from_location_id: it.from_location_id ?? null,
        to_location_id: null,
        remark: it.remark || ''
      }))
    }
    if (dialog.isEdit) {
      await transferApi.update(form.id, payload)
      ElMessage.success('修改成功')
    } else {
      await transferApi.create(payload)
      ElMessage.success('新增成功')
    }
    dialog.visible = false
    fetchList()
  } catch (e) {
    // 校验失败（如数量为 0）由 request 拦截器统一提示，这里不重复弹窗
  } finally {
    submitting.value = false
  }
}

// ---------------- 详情 ----------------
const detail = reactive({ visible: false, data: null })
const detailTotalQty = computed(() => {
  const sum = (detail.data?.items || []).reduce((s, i) => s + (Number(i.qty) || 0), 0)
  return Number(sum.toFixed(2))
})
async function onDetail(row) {
  try {
    detail.data = await transferApi.detail(row.id)
    detail.visible = true
  } catch (e) {
    // 拦截器已提示
  }
}

// ---------------- 审核 / 作废 ----------------
async function onApprove(row) {
  try {
    await ElMessageBox.confirm(
      `确认审核调拨单「${row.transfer_no}」？审核会真实执行库存动作：调出仓库按明细扣减、调入仓库同步增加，状态变为「已审核」。`,
      '审核确认',
      { type: 'warning', confirmButtonText: '确认审核', cancelButtonText: '取消' }
    )
  } catch { return } // 点取消：静默返回
  try {
    await transferApi.approve(row.id)
    ElMessage.success('审核成功，调拨已完成，库存已更新')
    fetchList()
  } catch (e) {
    // 库存不足等业务错误由拦截器统一提示，库存未被改动
  }
}
async function onVoid(row) {
  const tip = row.executed
    ? `调拨单「${row.transfer_no}」已执行过库存动作，作废会把调出仓库的库存加回、调入仓库扣减（反向回滚）；若调入仓库库存不足，作废会被拒绝。确认作废？`
    : `确认作废调拨单「${row.transfer_no}」？作废后不可再审核。`
  try {
    await ElMessageBox.confirm(tip, '作废确认', { type: 'warning', confirmButtonText: '确认作废', cancelButtonText: '取消' })
  } catch { return } // 点取消：静默返回
  try {
    await transferApi.voidOrder(row.id)
    ElMessage.success(row.executed ? '已作废，库存已反向回滚' : '已作废')
    fetchList()
  } catch (e) {
    // 拦截器已提示
  }
}

onMounted(async () => {
  fetchList()
  try {
    const [w, m] = await Promise.all([warehouseApi.all(), materialApi.list({ page: 1, page_size: 1000 })])
    warehouses.value = w || []
    // 单位表：拿不到就统一落回「个」
    unitMap.value = (m.list || []).reduce((acc, x) => { if (x.unit) acc[x.id] = x.unit; return acc }, {})
  } catch (e) {
    warehouses.value = []
  }
})
</script>

<style scoped>
/* 空态：文案与「新增调拨」入口同一视觉块 */
.empty-block { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 10px 0 16px; }
.eb-title { font-size: 14px; font-weight: 600; color: var(--text-1); }
.eb-desc { max-width: 460px; font-size: 12px; line-height: 1.6; color: var(--text-2); }
.items-head { display: flex; align-items: center; gap: 10px; margin: 4px 0 10px; }
.items-title { font-weight: 600; color: var(--text-1); }
.items-tip { flex: 1; font-size: 12px; color: var(--text-3); }
.qty-warn { margin-top: 2px; font-size: 12px; color: #f56c6c; line-height: 1.4; }
.low { color: #f56c6c; font-weight: 600; }
.detail-title { font-weight: 600; color: var(--text-2); margin: 12px 0 8px; }
.detail-total { margin-top: 10px; text-align: right; font-weight: 600; color: var(--brand); }
</style>
