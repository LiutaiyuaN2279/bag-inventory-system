<template>
  <div class="page">
    <!-- 页头：标题 + 说明 + 主操作 -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Box /></el-icon>物料管理</h2>
        <div class="ph-desc">
          维护物料主数据（面料 / 里料 / 辅料 / 五金 / 包材 / 成品），编码可按名称自动生成 · 共 <b>{{ total }}</b> 条
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
        <el-button type="primary" :icon="Plus" v-permission="'basic:material:add'" @click="onAdd">新增物料</el-button>
      </div>
    </div>

    <!-- 列表卡：筛选条 + 表格 + 分页，卡片撑满内容区，表格区内部滚动 -->
    <el-card shadow="never" class="card-fill">
      <div class="toolbar">
        <el-form :inline="true" :model="query" class="tb-left">
          <el-form-item label="关键字">
            <el-input v-model="query.keyword" placeholder="编码 / 名称 / 分类" clearable style="width: 200px" @keyup.enter="onSearch" />
          </el-form-item>
          <el-form-item label="分类">
            <el-select v-model="query.category" placeholder="全部" clearable style="width: 130px">
              <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
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
          <el-table-column prop="material_code" label="物料编码" width="130" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="material_name" label="物料名称" min-width="170" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="category" label="分类" width="90" sortable="custom">
            <template #default="{ row }">
              <el-tag size="small">{{ row.category }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="spec" label="规格" min-width="140" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="unit" label="单位" width="88" sortable="custom" align="center" />
          <el-table-column prop="default_color_no" label="主色号" width="100" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="safety_stock" label="安全库存" width="118" sortable="custom" align="right" class-name="col-num" />
          <el-table-column prop="min_order_qty" label="最小批量" width="118" sortable="custom" align="right" class-name="col-num" />
          <el-table-column label="状态" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status ? 'success' : 'info'" size="small">{{ row.status ? '启用' : '停用' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" v-permission="'basic:material:edit'" @click="onEdit(row)">编辑</el-button>
              <el-button link type="danger" v-permission="'basic:material:delete'" @click="onDelete(row)">删除</el-button>
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

    <!-- 新增/编辑弹窗 -->
    <el-dialog v-model="dialog.visible" :title="dialog.isEdit ? '编辑物料' : '新增物料'" width="560px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="物料编码" prop="material_code">
          <el-input v-model="form.material_code" :disabled="dialog.isEdit" placeholder="输入名称后自动生成，可修改" @input="onCodeManual">
            <template #append v-if="!dialog.isEdit">
              <el-button @click="genCode(true)">生成</el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item label="物料名称" prop="material_name">
          <el-input v-model="form.material_name" placeholder="输入名称将自动带出编码" />
        </el-form-item>
        <el-form-item label="分类" prop="category">
          <el-select v-model="form.category" style="width: 100%">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="规格">
          <el-input v-model="form.spec" placeholder="如 幅宽150cm" />
        </el-form-item>
        <el-form-item label="单位">
          <el-select v-model="form.unit" style="width: 100%">
            <el-option v-for="u in units" :key="u" :label="u" :value="u" />
          </el-select>
        </el-form-item>
        <el-form-item label="主色号">
          <el-input v-model="form.default_color_no" placeholder="面料/五金色号" />
        </el-form-item>
        <el-form-item label="安全库存">
          <el-input-number v-model="form.safety_stock" :min="0" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="最小批量">
          <el-input-number v-model="form.min_order_qty" :min="0" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="form.status" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取 消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmit">确 定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Search, Refresh, Plus, Box } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { materialApi } from '@/api/basicData'
import { useSort } from '@/composables/useSort'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import SortChips from '@/components/SortChips.vue'
import BatchBar from '@/components/BatchBar.vue'

const categories = ['面料', '里料', '辅料', '五金', '包材', '成品']
const units = ['米', '码', '个', '套', 'kg']

const query = reactive({ page: 1, page_size: 20, keyword: '', category: '' })
const list = ref([])
const total = ref(0)
const loading = ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))

const dialog = reactive({ visible: false, isEdit: false })
const submitting = ref(false)
const formRef = ref()
const form = reactive({
  id: null, material_code: '', material_name: '', category: '面料', spec: '', unit: '个',
  default_color_no: '', safety_stock: 0, min_order_qty: 0, status: true, remark: ''
})
const rules = {
  material_code: [{ required: true, message: '请输入物料编码', trigger: 'blur' }],
  material_name: [{ required: true, message: '请输入物料名称', trigger: 'blur' }],
  category: [{ required: true, message: '请选择分类', trigger: 'change' }]
}

async function fetchList() {
  loading.value = true
  try {
    const res = await materialApi.list({ ...query })
    list.value = res.list || []
    total.value = res.total || 0
  } finally {
    loading.value = false
  }
}
const { onSortChange, sortRules, removeSort, clearSort } = useSort(query, fetchList)

// ---- 批量操作 ----
const batch = useBatch({ fetchList })
// 动作按权限过滤：无权限的按钮不渲染（与行操作按钮一致）
const batchActions = [
  { key: 'enable', label: '批量启用', perm: 'basic:material:edit' },
  { key: 'disable', label: '批量停用', perm: 'basic:material:edit' },
  { key: 'delete', label: '批量删除', type: 'danger', perm: 'basic:material:delete' },
  { key: 'export', label: '导出选中', perm: 'basic:material:list' }
]
// 导出用列定义与表格列保持一致，避免导出后对不上
const exportColumns = [
  { prop: 'material_code', label: '物料编码' },
  { prop: 'material_name', label: '物料名称' },
  { prop: 'category', label: '分类' },
  { prop: 'spec', label: '规格' },
  { prop: 'unit', label: '单位' },
  { prop: 'default_color_no', label: '主色号' },
  { prop: 'safety_stock', label: '安全库存' },
  { prop: 'min_order_qty', label: '最小批量' },
  { prop: 'status', label: '状态', formatter: (r) => (r.status ? '启用' : '停用') },
  { prop: 'remark', label: '备注' }
]

async function onBatchAction(key) {
  if (key === 'export') {
    exportRows(batch.selected.value, exportColumns, '物料清单')
    return
  }
  const labels = { enable: '批量启用', disable: '批量停用', delete: '批量删除' }
  const label = labels[key] || '批量操作'
  const n = batch.count.value
  // 删除不可逆，提示语里点明数量与不可恢复
  const confirm = key === 'delete'
    ? `确认删除选中的 ${n} 个物料？删除后不可恢复，若该物料已有库存/单据关联请改用「批量停用」。`
    : `确认对选中的 ${n} 个物料执行「${label.slice(2)}」？`
  await batch.run(materialApi.batch, key, { label, confirm })
}

function onSearch() { query.page = 1; batch.clearSelection(); fetchList() }
function onReset() { query.keyword = ''; query.category = ''; onSearch() }

function resetForm() {
  Object.assign(form, { id: null, material_code: '', material_name: '', category: '面料', spec: '', unit: '个', default_color_no: '', safety_stock: 0, min_order_qty: 0, status: true, remark: '' })
  codeManual.value = false
}
function onAdd() { resetForm(); dialog.isEdit = false; dialog.visible = true }
function onEdit(row) { resetForm(); Object.assign(form, row); dialog.isEdit = true; dialog.visible = true }

// 物料编码自动生成：用户手动改过编码后不再自动覆盖
const codeManual = ref(false)
let genTimer = null
function onCodeManual() { codeManual.value = true }
async function genCode(force = false) {
  if (dialog.isEdit) return
  if (!force && codeManual.value) return
  if (!form.material_name.trim()) { form.material_code = ''; return }
  try {
    const res = await materialApi.suggestCode({ category: form.category, name: form.material_name })
    form.material_code = res.code
  } catch (e) { /* 忽略，用户可手填 */ }
}
// 名称或分类变化时（防抖）自动带出编码
watch(() => [form.category, form.material_name], () => {
  if (dialog.isEdit) return
  clearTimeout(genTimer)
  genTimer = setTimeout(() => { if (!codeManual.value) genCode() }, 400)
})

async function onSubmit() {
  if (!(await formRef.value.validate().catch(() => false))) return
  submitting.value = true
  try {
    if (dialog.isEdit) {
      await materialApi.update(form.id, form)
      ElMessage.success('修改成功')
    } else {
      await materialApi.create(form)
      ElMessage.success('新增成功')
    }
    dialog.visible = false
    fetchList()
  } finally {
    submitting.value = false
  }
}

async function onDelete(row) {
  try { await ElMessageBox.confirm(`确认删除物料「${row.material_name}」？`, '提示', { type: 'warning' }) } catch { return }
  await materialApi.remove(row.id)
  ElMessage.success('删除成功')
  fetchList()
}

onMounted(fetchList)
</script>
