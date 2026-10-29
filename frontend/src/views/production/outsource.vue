<template>
  <div class="page">
    <!-- 页头：标题 + 说明 + 主操作（原表格卡里孤零零的按钮移到这里） -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Van /></el-icon>外发加工</h2>
        <div class="ph-desc">
          发外加工单的发料出库与成品收回入库，库存实时联动 · 共 <b>{{ total }}</b> 条
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
        <el-button type="primary" :icon="Plus" v-permission="'outsource:edit'" @click="onAdd">新增加工单</el-button>
      </div>
    </div>

    <!-- 列表卡：筛选条 + 本页状态分布 + 表格 + 分页（原独立筛选卡已并入 .toolbar） -->
    <el-card shadow="never" class="card-fill">
      <div class="toolbar">
        <el-form :inline="true" :model="query" class="tb-left">
          <el-form-item label="单号">
            <el-input v-model="query.keyword" placeholder="加工单号" clearable style="width:180px" @keyup.enter="onSearch" />
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

        <!-- 本页状态分布：填充筛选条右侧留白，替代后端尚不支持的加工商/日期筛选 -->
        <div class="tb-right">
          <span v-for="s in statusList" :key="s" class="os-stat">
            <span class="dot" :style="{ color: chipColor(s) }">{{ s }}</span>
            <b>{{ statusStats[s] }}</b>
          </span>
        </div>
        <SortChips :rules="sortRules" @remove="removeSort" @clear="clearSort" />
      </div>

      <!-- 批量操作条：勾选后才出现，不占固定高度 -->
      <BatchBar :batch="batch" :actions="batchActions" @action="onBatchAction" />

      <div class="table-wrap">
        <el-table :ref="batch.bindTable" :data="list" :row-key="(row) => row.id" v-loading="loading" border stripe
          @sort-change="onSortChange" @selection-change="batch.onSelectionChange">
          <el-table-column type="selection" width="50" align="center" reserve-selection />
          <el-table-column type="index" label="#" width="55" align="center" />
          <el-table-column prop="order_no" label="加工单号" width="160" sortable="custom" show-overflow-tooltip />
          <!-- 加工商与收回成品内容较长，宽度向它们倾斜 -->
          <el-table-column prop="supplier_name" label="加工商" min-width="180" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="product_name" label="收回成品" min-width="170" sortable="custom" show-overflow-tooltip />
          <!-- 仓库名最长「外发暂存库」，收窄到 104px -->
          <el-table-column prop="out_warehouse_name" label="发料仓" width="104" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="in_warehouse_name" label="收回仓" width="104" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="plan_qty" label="计划" width="88" sortable="custom" align="right" class-name="col-num" />
          <el-table-column prop="received_qty" label="已收回" width="88" sortable="custom" align="right" class-name="col-num" />
          <el-table-column label="状态" width="104" align="center">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="270" fixed="right" align="center">
            <template #default="{ row }">
              <el-button link type="primary" @click="onDetail(row)">详情</el-button>
              <el-button link type="primary" v-permission="'outsource:edit'" :disabled="row.status!=='草稿'" @click="onEdit(row)">编辑</el-button>
              <el-button link type="warning" v-permission="'outsource:edit'" :disabled="row.status!=='草稿'" @click="onIssue(row)">发料</el-button>
              <el-button link type="success" v-permission="'outsource:edit'" :disabled="!['已发料','部分收回'].includes(row.status)" @click="onReceive(row)">收回</el-button>
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

    <el-dialog v-model="dialog.visible" :title="dialog.isEdit?'编辑加工单':'新增加工单'" width="800px">
      <el-form ref="formRef" :model="form" label-width="90px">
        <el-row :gutter="16">
          <el-col :span="8"><el-form-item label="加工商"><el-select v-model="form.supplier_id" filterable style="width:100%"><el-option v-for="s in suppliers" :key="s.id" :label="s.supplier_name" :value="s.id" /></el-select></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="收回成品"><el-select v-model="form.product_id" filterable style="width:100%"><el-option v-for="m in materials" :key="m.id" :label="m.material_code+' '+m.material_name" :value="m.id" /></el-select></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="计划数量"><el-input-number v-model="form.plan_qty" :min="0" :precision="2" style="width:100%" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="发料仓"><el-select v-model="form.out_warehouse_id" style="width:100%"><el-option v-for="w in warehouses" :key="w.id" :label="w.warehouse_name" :value="w.id" /></el-select></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="收回仓"><el-select v-model="form.in_warehouse_id" style="width:100%"><el-option v-for="w in warehouses" :key="w.id" :label="w.warehouse_name" :value="w.id" /></el-select></el-form-item></el-col>
        </el-row>
        <el-form-item label="发料明细">
          <div style="margin-bottom:8px"><el-button size="small" :icon="Plus" @click="addItem">添加原料</el-button></div>
          <el-table :data="form.items" border size="small">
            <el-table-column label="原料" min-width="180"><template #default="{ row }"><el-select v-model="row.material_id" filterable style="width:100%"><el-option v-for="m in materials" :key="m.id" :label="m.material_code+' '+m.material_name" :value="m.id" /></el-select></template></el-table-column>
            <el-table-column label="数量" width="130"><template #default="{ row }"><el-input-number v-model="row.qty" :min="0" :precision="2" style="width:100%" /></template></el-table-column>
            <el-table-column label="单位" width="90"><template #default="{ row }"><el-input v-model="row.unit" /></template></el-table-column>
            <el-table-column label="操作" width="70"><template #default="{ $index }"><el-button link type="danger" @click="form.items.splice($index,1)">删除</el-button></template></el-table-column>
          </el-table>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="form.remark" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialog.visible=false">取消</el-button><el-button type="primary" :loading="submitting" @click="onSubmit">确定</el-button></template>
    </el-dialog>

    <DetailDialog v-model="detail.visible" title="加工单详情" :doc-no="detail.data?.order_no"
      :status="detail.data?.status" :status-type="statusType(detail.data?.status)" width="980px" :print-data="buildPrintDoc">
      <template v-if="detail.data">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="单号">{{ detail.data.order_no }}</el-descriptions-item>
          <el-descriptions-item label="状态"><el-tag :type="statusType(detail.data.status)">{{ detail.data.status }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="加工商">{{ detail.data.supplier_name }}</el-descriptions-item>
          <el-descriptions-item label="收回成品">{{ detail.data.product_name }}</el-descriptions-item>
          <el-descriptions-item label="计划/已收回">{{ detail.data.plan_qty }} / {{ detail.data.received_qty }}</el-descriptions-item>
        </el-descriptions>
        <el-table :data="detail.data.items" border size="small" style="margin-top:16px">
          <el-table-column prop="material_name" label="原料" />
          <el-table-column prop="qty" label="应发" width="90" />
          <el-table-column prop="issued_qty" label="已发" width="90" />
          <el-table-column prop="unit" label="单位" width="80" />
        </el-table>
      </template>
    </DetailDialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Search, Refresh, Plus, Van } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { outsourceApi } from '@/api/outsource'
import DetailDialog from '@/components/DetailDialog.vue'
import { materialApi, supplierApi, warehouseApi } from '@/api/basicData'
import { useSort } from '@/composables/useSort'
import { applyRouteFilter } from '@/composables/useAutoFilter'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import SortChips from '@/components/SortChips.vue'
import BatchBar from '@/components/BatchBar.vue'
import { sumBy } from '@/utils/print'

const statusList = ['草稿', '已发料', '部分收回', '已完成', '在途']
const statusType = (s) => ({ 草稿: 'info', 已发料: 'warning', 部分收回: 'warning', 已完成: 'success', 在途: 'warning' }[s] || '')
const chipColor = (s) => ({ 草稿: '#909399', 已发料: '#e6a23c', 部分收回: '#e6a23c', 已完成: '#10b981', 在途: '#e6a23c' }[s] || '#909399')
const query = reactive({ page: 1, page_size: 20, keyword: '', status: '' })
applyRouteFilter(query) // 首页待办跳转自动带筛选
const list = ref([]); const total = ref(0); const loading = ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))
// 本页各行状态计数（仅统计当前页数据，纯展示）
const statusStats = computed(() => {
  const acc = {}
  for (const s of statusList) acc[s] = 0
  for (const r of list.value) {
    for (const s of statusList) {
      if (s === '在途' ? ['已发料', '部分收回'].includes(r.status) : r.status === s) acc[s]++
    }
  }
  return acc
})
const materials = ref([]); const suppliers = ref([]); const warehouses = ref([])
const dialog = reactive({ visible: false, isEdit: false }); const submitting = ref(false); const formRef = ref()
const form = reactive({ id: null, supplier_id: null, product_id: null, out_warehouse_id: null, in_warehouse_id: null, plan_qty: 0, remark: '', items: [] })
const detail = reactive({ visible: false, data: null })
function addItem() { form.items.push({ material_id: null, qty: 1, unit: '个' }) }
function resetForm() { Object.assign(form, { id: null, supplier_id: null, product_id: null, out_warehouse_id: warehouses.value[0]?.id, in_warehouse_id: warehouses.value[0]?.id, plan_qty: 0, remark: '', items: [] }); addItem() }
async function fetchList() { loading.value = true; try { const res = await outsourceApi.list({ ...query }); list.value = res.list || []; total.value = res.total || 0 } finally { loading.value = false } }
const { onSortChange, sortRules, removeSort, clearSort } = useSort(query, fetchList)

// ---- 批量操作 ----
const batch = useBatch({ fetchList })
// 动作按权限过滤：与后端 outsource.py 的 BATCH_PERMS 一致（issue/receive 都是 outsource:edit）
const batchActions = [
  { key: 'issue', label: '批量发料', type: 'warning', perm: 'outsource:edit' },
  { key: 'receive', label: '批量收回', type: 'success', perm: 'outsource:edit' },
  { key: 'export', label: '导出选中', perm: 'outsource:list' }
]
// 导出列与表格列一一对应（remark/created_at 未在表格展示，故不导出）
const exportColumns = [
  { prop: 'order_no', label: '加工单号' },
  { prop: 'supplier_name', label: '加工商' },
  { prop: 'product_name', label: '收回成品' },
  { prop: 'out_warehouse_name', label: '发料仓' },
  { prop: 'in_warehouse_name', label: '收回仓' },
  { prop: 'plan_qty', label: '计划' },
  { prop: 'received_qty', label: '已收回' },
  { prop: 'status', label: '状态' }
]

async function onBatchAction(key) {
  if (key === 'export') {
    exportRows(batch.selected.value, exportColumns, '外发加工单')
    return
  }
  const n = batch.count.value
  // 两个动作都有真实库存副作用，confirm 必须写明
  const confirm = key === 'issue'
    ? `确认对选中的 ${n} 张外发加工单批量发料？发料会按每张单的发料明细真实扣减「发料仓」的原料库存，并生成库存出库流水；仅草稿状态且有发料明细的单据可发料，其余会被后端逐条拒绝（失败明细在结果弹窗中列出）。`
    : `确认对选中的 ${n} 张外发加工单批量收回？收回会按「计划数量 − 已收回数量」的差额真实增加「收回仓」的成品库存，并生成库存入库流水；仅已发料 / 部分收回的单据可收回，计划数量已收满或为 0 的单据会被后端逐条拒绝（失败明细在结果弹窗中列出）。`
  await batch.run(outsourceApi.batch, key, {
    label: key === 'issue' ? '批量发料' : '批量收回',
    confirm
  })
}

function onSearch() { query.page = 1; batch.clearSelection(); fetchList() }
function onReset() { query.keyword = ''; query.status = ''; onSearch() }
function onAdd() { resetForm(); dialog.isEdit = false; dialog.visible = true }
async function onEdit(row) { const res = await outsourceApi.detail(row.id); Object.assign(form, { id: res.id, supplier_id: res.supplier_id, product_id: res.product_id, out_warehouse_id: res.out_warehouse_id, in_warehouse_id: res.in_warehouse_id, plan_qty: res.plan_qty, remark: res.remark, items: res.items.map(i => ({ material_id: i.material_id, qty: i.qty, unit: i.unit })) }); dialog.isEdit = true; dialog.visible = true }
async function onDetail(row) { detail.data = await outsourceApi.detail(row.id); detail.visible = true }

/** 组装打印数据（与 BOM 明细页同一契约）：meta 取单头字段，行用详情已有的发料明细，footer 放应发合计 */
function buildPrintDoc() {
  const d = detail.data
  if (!d) return null
  const items = d.items || []
  return {
    title: '外发加工单',
    docNo: d.order_no,
    meta: [
      { label: '加工商', value: d.supplier_name },
      { label: '收回成品', value: d.product_name },
      { label: '发料仓', value: d.out_warehouse_name },
      { label: '收回仓', value: d.in_warehouse_name },
      { label: '计划数量', value: d.plan_qty },
      { label: '已收回', value: d.received_qty },
      { label: '状态', value: d.status },
      { label: '制单时间', value: d.created_at }
    ],
    columns: [
      { label: '原料', prop: 'material_name', width: 200 },
      { label: '应发', prop: 'qty', width: 90, align: 'right' },
      { label: '已发', prop: 'issued_qty', width: 90, align: 'right' },
      { label: '单位', prop: 'unit', width: 70, align: 'center' }
    ],
    rows: items,
    footer: [
      { label: '明细行数', value: items.length },
      { label: '应发合计', value: sumBy(items, 'qty') },
      { label: '备注', value: d.remark }
    ]
  }
}
async function onSubmit() {
  if (!form.supplier_id || !form.product_id) return ElMessage.warning('请选择加工商与成品')
  if (form.items.some(i => !i.material_id)) return ElMessage.warning('请完善发料明细')
  submitting.value = true
  try { dialog.isEdit ? await outsourceApi.update(form.id, form) : await outsourceApi.create(form); ElMessage.success('保存成功'); dialog.visible = false; fetchList() } finally { submitting.value = false }
}
async function onIssue(row) { try { await ElMessageBox.confirm('发料将扣减原料库存，确认？', '提示', { type: 'warning' }) } catch { return }; await outsourceApi.issue(row.id); ElMessage.success('发料成功'); fetchList() }
async function onReceive(row) {
  let value
  try {
    ({ value } = await ElMessageBox.prompt('请输入收回数量', '收回入库', { inputType: 'number', inputValue: (row.plan_qty - (row.received_qty || 0)) || 1 }))
  } catch { return } // 用户取消不报错
  await outsourceApi.receive(row.id, { qty: Number(value) }); ElMessage.success('收回成功'); fetchList()
}
onMounted(async () => {
  fetchList()
  const [m, s, w] = await Promise.all([materialApi.list({ page: 1, page_size: 1000 }), supplierApi.list({ page: 1, page_size: 1000 }), warehouseApi.all()])
  materials.value = m.list || []; suppliers.value = s.list || []; warehouses.value = w || []
})
</script>
<style scoped>
/* 本页专属：筛选条右侧的本页状态分布 */
.os-stat { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); }
.os-stat b { font-variant-numeric: tabular-nums; color: var(--text-1); }
</style>
