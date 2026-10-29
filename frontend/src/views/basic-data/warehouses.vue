<template>
  <div class="page">
    <!-- 页头：标题 + 说明 + 主操作 -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><OfficeBuilding /></el-icon>仓库管理</h2>
        <div class="ph-desc">
          维护仓库主数据（原料仓 / 成品仓 / 外发暂存 / 不良品仓），编码可自动生成 · 共 <b>{{ total }}</b> 个
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
        <el-button type="primary" :icon="Plus" v-permission="'basic:warehouse:add'" @click="onAdd">新增仓库</el-button>
      </div>
    </div>

    <!-- 列表卡：筛选条 + 表格 + 分页，卡片撑满内容区，表格区内部滚动 -->
    <el-card shadow="never" class="card-fill">
      <div class="toolbar">
        <el-form :inline="true" :model="query" class="tb-left">
          <el-form-item label="关键字">
            <el-input v-model="query.keyword" placeholder="编码 / 名称 / 负责人" clearable style="width: 200px" @keyup.enter="onSearch" />
          </el-form-item>
          <el-form-item label="类型">
            <el-select v-model="query.type" placeholder="全部" clearable style="width: 130px">
              <el-option v-for="t in types" :key="t" :label="t" :value="t" />
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
          <el-table-column prop="warehouse_code" label="仓库编码" width="130" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="warehouse_name" label="仓库名称" min-width="180" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="type" label="类型" width="110" sortable="custom" align="center">
            <template #default="{ row }">
              <el-tag size="small">{{ row.type }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="manager" label="负责人" width="120" sortable="custom" show-overflow-tooltip />
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status ? 'success' : 'info'" size="small">{{ row.status ? '启用' : '停用' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="remark" label="备注" min-width="200" sortable="custom" show-overflow-tooltip />
          <el-table-column label="操作" width="150" fixed="right" align="center">
            <template #default="{ row }">
              <el-button link type="primary" v-permission="'basic:warehouse:edit'" @click="onEdit(row)">编辑</el-button>
              <el-button link type="danger" v-permission="'basic:warehouse:delete'" @click="onDelete(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="pager">
        <span class="hint">共 <b>{{ total }}</b> 个仓库 · 第 {{ query.page }} / {{ pageCount }} 页</span>
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
    <el-dialog v-model="dialog.visible" :title="dialog.isEdit ? '编辑仓库' : '新增仓库'" width="560px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="仓库编码" prop="warehouse_code">
          <el-input v-model="form.warehouse_code" :disabled="dialog.isEdit" placeholder="自动生成，可修改" @input="codeManual = true">
            <template #append v-if="!dialog.isEdit">
              <el-button @click="genCode(true)">生成</el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item label="仓库名称" prop="warehouse_name">
          <el-input v-model="form.warehouse_name" />
        </el-form-item>
        <el-form-item label="类型" prop="type">
          <el-select v-model="form.type" style="width: 100%">
            <el-option v-for="t in types" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="负责人"><el-input v-model="form.manager" /></el-form-item>
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
import { Search, Refresh, Plus, OfficeBuilding } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { warehouseApi } from '@/api/basicData'
import { useSort } from '@/composables/useSort'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import SortChips from '@/components/SortChips.vue'
import BatchBar from '@/components/BatchBar.vue'

const types = ['原料仓', '成品仓', '外发暂存', '不良品仓']
const query = reactive({ page: 1, page_size: 20, keyword: '', type: '' })
const list = ref([])
const total = ref(0)
const loading = ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))

const dialog = reactive({ visible: false, isEdit: false })
const submitting = ref(false)
const formRef = ref()
const form = reactive({ id: null, warehouse_code: '', warehouse_name: '', type: '原料仓', manager: '', status: true, remark: '' })
const rules = {
  warehouse_code: [{ required: true, message: '请输入仓库编码', trigger: 'blur' }],
  warehouse_name: [{ required: true, message: '请输入仓库名称', trigger: 'blur' }],
  type: [{ required: true, message: '请选择类型', trigger: 'change' }]
}

async function fetchList() {
  loading.value = true
  try {
    const res = await warehouseApi.list({ ...query })
    list.value = res.list || []
    total.value = res.total || 0
  } finally { loading.value = false }
}
const { onSortChange, sortRules, removeSort, clearSort } = useSort(query, fetchList)

// ---- 批量操作 ----
const batch = useBatch({ fetchList })
// 动作按权限过滤：无权限的按钮不渲染（与行操作按钮一致）
const batchActions = [
  { key: 'enable', label: '批量启用', perm: 'basic:warehouse:edit' },
  { key: 'disable', label: '批量停用', perm: 'basic:warehouse:edit' },
  { key: 'delete', label: '批量删除', type: 'danger', perm: 'basic:warehouse:delete' },
  { key: 'export', label: '导出选中', perm: 'basic:warehouse:list' }
]
// 导出用列定义与表格列保持一致，避免导出后对不上
const exportColumns = [
  { prop: 'warehouse_code', label: '仓库编码' },
  { prop: 'warehouse_name', label: '仓库名称' },
  { prop: 'type', label: '类型' },
  { prop: 'manager', label: '负责人' },
  { prop: 'status', label: '状态', formatter: (r) => (r.status ? '启用' : '停用') },
  { prop: 'remark', label: '备注' }
]

async function onBatchAction(key) {
  if (key === 'export') {
    exportRows(batch.selected.value, exportColumns, '仓库清单')
    return
  }
  const labels = { enable: '批量启用', disable: '批量停用', delete: '批量删除' }
  const label = labels[key] || '批量操作'
  const n = batch.count.value
  // 删除不可逆，提示语里点明数量与不可恢复
  const confirm = key === 'delete'
    ? `确认删除选中的 ${n} 个仓库？删除后不可恢复，若该仓库已有库存/出入库流水等业务关联请改用「批量停用」。`
    : `确认对选中的 ${n} 个仓库执行「${label.slice(2)}」？`
  await batch.run(warehouseApi.batch, key, { label, confirm })
}

function onSearch() { query.page = 1; batch.clearSelection(); fetchList() }
function onReset() { query.keyword = ''; query.type = ''; onSearch() }

function resetForm() {
  Object.assign(form, { id: null, warehouse_code: '', warehouse_name: '', type: '原料仓', manager: '', status: true, remark: '' })
  codeManual.value = false
}
const codeManual = ref(false)
async function genCode(force = false) {
  if (dialog.isEdit) return
  if (!force && codeManual.value) return
  try { form.warehouse_code = (await warehouseApi.suggestCode()).code } catch (e) { /* 失败可手填 */ }
}
function onAdd() { resetForm(); dialog.isEdit = false; dialog.visible = true; genCode() }
function onEdit(row) { resetForm(); Object.assign(form, row); dialog.isEdit = true; dialog.visible = true }

async function onSubmit() {
  if (!(await formRef.value.validate().catch(() => false))) return
  submitting.value = true
  try {
    if (dialog.isEdit) { await warehouseApi.update(form.id, form); ElMessage.success('修改成功') }
    else { await warehouseApi.create(form); ElMessage.success('新增成功') }
    dialog.visible = false; fetchList()
  } finally { submitting.value = false }
}
async function onDelete(row) {
  try { await ElMessageBox.confirm(`确认删除仓库「${row.warehouse_name}」？`, '提示', { type: 'warning' }) } catch { return }
  await warehouseApi.remove(row.id); ElMessage.success('删除成功'); fetchList()
}
onMounted(fetchList)
</script>
