<template>
  <div class="page">
    <!-- 页头：标题 + 说明 + 主操作 -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Shop /></el-icon>供应商管理</h2>
        <div class="ph-desc">
          维护供应商主数据（联系方式 / 地址 / 付款方式 / 交货周期），编码可自动生成 · 共 <b>{{ total }}</b> 家
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
        <el-button type="primary" :icon="Plus" v-permission="'basic:supplier:add'" @click="onAdd">新增供应商</el-button>
      </div>
    </div>

    <!-- 列表卡：筛选条 + 表格 + 分页，卡片撑满内容区，表格区内部滚动 -->
    <el-card shadow="never" class="card-fill">
      <div class="toolbar">
        <el-form :inline="true" :model="query" class="tb-left">
          <el-form-item label="关键字">
            <el-input v-model="query.keyword" placeholder="编码 / 名称 / 联系人" clearable style="width: 200px" @keyup.enter="onSearch" />
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="query.status" placeholder="全部" clearable style="width: 120px">
              <el-option label="启用" :value="1" />
              <el-option label="停用" :value="0" />
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
        <el-table :ref="batch.bindTable" :data="list" :row-key="(row) => row.id" v-loading="loading" border stripe
          @sort-change="onSortChange" @selection-change="batch.onSelectionChange">
          <el-table-column type="selection" width="50" align="center" reserve-selection />
          <el-table-column type="index" label="#" width="55" align="center" />
          <el-table-column prop="supplier_code" label="供应商编码" width="122" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="supplier_name" label="供应商名称" min-width="200" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="contact" label="联系人" width="90" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="phone" label="联系电话" width="112" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="address" label="地址" min-width="170" show-overflow-tooltip />
          <el-table-column prop="payment_term" label="付款方式" width="110" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="lead_time_days" label="交货周期" width="110" sortable="custom" align="right" class-name="col-num" />
          <el-table-column prop="remark" label="备注" min-width="130" show-overflow-tooltip />
          <el-table-column label="状态" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status ? 'success' : 'info'" size="small">{{ row.status ? '启用' : '停用' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right" align="center">
            <template #default="{ row }">
              <el-button link type="primary" v-permission="'basic:supplier:edit'" @click="onEdit(row)">编辑</el-button>
              <el-button link type="danger" v-permission="'basic:supplier:delete'" @click="onDelete(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="pager">
        <span class="hint">共 <b>{{ total }}</b> 家供应商 · 第 {{ query.page }} / {{ pageCount }} 页</span>
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

    <!-- 新增/编辑弹窗 -->
    <el-dialog v-model="dialog.visible" :title="dialog.isEdit ? '编辑供应商' : '新增供应商'" width="560px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="供应商编码" prop="supplier_code">
          <el-input v-model="form.supplier_code" :disabled="dialog.isEdit" placeholder="自动生成，可修改" @input="codeManual = true">
            <template #append v-if="!dialog.isEdit">
              <el-button @click="genCode(true)">生成</el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item label="供应商名称" prop="supplier_name">
          <el-input v-model="form.supplier_name" />
        </el-form-item>
        <el-form-item label="联系人"><el-input v-model="form.contact" /></el-form-item>
        <el-form-item label="联系电话"><el-input v-model="form.phone" /></el-form-item>
        <el-form-item label="地址"><el-input v-model="form.address" /></el-form-item>
        <el-form-item label="付款方式"><el-input v-model="form.payment_term" placeholder="如 月结30天" /></el-form-item>
        <el-form-item label="交货周期(天)">
          <el-input-number v-model="form.lead_time_days" :min="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="状态"><el-switch v-model="form.status" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取 消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmit">确 定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Search, Refresh, Plus, Shop } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { supplierApi } from '@/api/basicData'
import { useSort } from '@/composables/useSort'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import SortChips from '@/components/SortChips.vue'
import BatchBar from '@/components/BatchBar.vue'

const query = reactive({ page: 1, page_size: 20, keyword: '', status: null })
const list = ref([])
const total = ref(0)
const loading = ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))

const dialog = reactive({ visible: false, isEdit: false })
const submitting = ref(false)
const formRef = ref()
const form = reactive({ id: null, supplier_code: '', supplier_name: '', contact: '', phone: '', address: '', payment_term: '', lead_time_days: 0, status: true, remark: '' })
const rules = {
  supplier_code: [{ required: true, message: '请输入供应商编码', trigger: 'blur' }],
  supplier_name: [{ required: true, message: '请输入供应商名称', trigger: 'blur' }]
}

async function fetchList() {
  loading.value = true
  try {
    const res = await supplierApi.list({ ...query })
    list.value = res.list || []
    total.value = res.total || 0
  } finally { loading.value = false }
}
const { onSortChange, sortRules, removeSort, clearSort } = useSort(query, fetchList)

// ---- 批量操作 ----
const batch = useBatch({ fetchList })
// 动作按权限过滤：无权限的按钮不渲染（与行操作按钮一致）
const batchActions = [
  { key: 'enable', label: '批量启用', perm: 'basic:supplier:edit' },
  { key: 'disable', label: '批量停用', perm: 'basic:supplier:edit' },
  { key: 'delete', label: '批量删除', type: 'danger', perm: 'basic:supplier:delete' },
  { key: 'export', label: '导出选中', perm: 'basic:supplier:list' }
]
// 导出用列定义与表格列保持一致，避免导出后对不上
const exportColumns = [
  { prop: 'supplier_code', label: '供应商编码' },
  { prop: 'supplier_name', label: '供应商名称' },
  { prop: 'contact', label: '联系人' },
  { prop: 'phone', label: '联系电话' },
  { prop: 'address', label: '地址' },
  { prop: 'payment_term', label: '付款方式' },
  { prop: 'lead_time_days', label: '交货周期' },
  { prop: 'remark', label: '备注' },
  { prop: 'status', label: '状态', formatter: (r) => (r.status ? '启用' : '停用') }
]

async function onBatchAction(key) {
  if (key === 'export') {
    exportRows(batch.selected.value, exportColumns, '供应商清单')
    return
  }
  const labels = { enable: '批量启用', disable: '批量停用', delete: '批量删除' }
  const label = labels[key] || '批量操作'
  const n = batch.count.value
  // 删除不可逆，提示语里点明数量与不可恢复
  const confirm = key === 'delete'
    ? `确认删除选中的 ${n} 家供应商？删除后不可恢复，若该供应商已有采购订单/到货单等业务关联请改用「批量停用」。`
    : `确认对选中的 ${n} 家供应商执行「${label.slice(2)}」？`
  await batch.run(supplierApi.batch, key, { label, confirm })
}

function onSearch() { query.page = 1; batch.clearSelection(); fetchList() }
function onReset() { query.keyword = ''; query.status = null; onSearch() }

function resetForm() {
  Object.assign(form, { id: null, supplier_code: '', supplier_name: '', contact: '', phone: '', address: '', payment_term: '', lead_time_days: 0, status: true, remark: '' })
  codeManual.value = false
}
const codeManual = ref(false)
async function genCode(force = false) {
  if (dialog.isEdit) return
  if (!force && codeManual.value) return
  try { form.supplier_code = (await supplierApi.suggestCode()).code } catch (e) { /* 失败可手填 */ }
}
function onAdd() { resetForm(); dialog.isEdit = false; dialog.visible = true; genCode() }
function onEdit(row) { resetForm(); Object.assign(form, row); dialog.isEdit = true; dialog.visible = true }

async function onSubmit() {
  if (!(await formRef.value.validate().catch(() => false))) return
  submitting.value = true
  try {
    if (dialog.isEdit) { await supplierApi.update(form.id, form); ElMessage.success('修改成功') }
    else { await supplierApi.create(form); ElMessage.success('新增成功') }
    dialog.visible = false; fetchList()
  } finally { submitting.value = false }
}
async function onDelete(row) {
  try { await ElMessageBox.confirm(`确认删除供应商「${row.supplier_name}」？`, '提示', { type: 'warning' }) } catch { return }
  await supplierApi.remove(row.id); ElMessage.success('删除成功'); fetchList()
}
onMounted(fetchList)
</script>
