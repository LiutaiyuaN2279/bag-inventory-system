<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Search /></el-icon>库存查询</h2>
        <div class="ph-desc">按物料 / 仓库查看现存量与安全库存 · 共 <b>{{ total }}</b> 条</div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
        <el-button type="primary" :icon="EditPen" v-permission="'inventory:adjust'" @click="adjustVisible = true">其他出入库</el-button>
      </div>
    </div>

    <el-card shadow="never" class="card-fill">
      <div class="toolbar">
        <el-form :inline="true" :model="query" class="tb-left filter-grid">
          <el-form-item label="关键字">
            <el-input v-model="query.keyword" placeholder="物料编码 / 名称" clearable @keyup.enter="onSearch" />
          </el-form-item>
          <el-form-item label="仓库">
            <el-select v-model="query.warehouse_id" placeholder="全部仓库" clearable>
              <el-option v-for="w in warehouses" :key="w.id" :label="w.warehouse_name" :value="w.id" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :icon="Search" @click="onSearch">查询</el-button>
            <el-button :icon="Refresh" @click="onReset">重置</el-button>
          </el-form-item>
        </el-form>
      </div>
      <SortChips :rules="sortRules" @remove="removeSort" @clear="clearSort" />
      <!-- 只读页：本页只有「导出选中」，无批量写动作（后端无库存行批量写接口） -->
      <BatchBar :batch="batch" :actions="batchActions" @action="onBatchAction" />
      <div class="table-wrap">
        <el-table :ref="batch.bindTable" :data="list" :row-key="(row) => row.id" v-loading="loading" border stripe
          @sort-change="onSortChange" @selection-change="batch.onSelectionChange">
          <el-table-column type="selection" width="50" align="center" reserve-selection />
          <!-- 物料编码/安全库存取自本页已加载的 materials（下方「其他出入库」弹窗同一份数据），纯展示映射 -->
          <el-table-column label="物料编码" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">{{ codeOf(row.material_id) }}</template>
          </el-table-column>
          <el-table-column prop="material_name" label="物料" min-width="220" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="warehouse_name" label="仓库" min-width="140" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="qty" label="现存数量" width="120" align="right" class-name="col-num" sortable="custom">
            <template #default="{ row }"><span :class="{ 'low': row.qty < 0 }">{{ row.qty }}</span></template>
          </el-table-column>
          <el-table-column label="安全库存" width="120" align="right" class-name="col-num">
            <template #default="{ row }">{{ safetyOf(row.material_id) }}</template>
          </el-table-column>
          <el-table-column prop="last_move_date" label="最后变动" width="150" align="right" sortable="custom" show-overflow-tooltip />
        </el-table>
      </div>
      <div class="pager">
        <span class="hint">共 <b>{{ total }}</b> 条 · 第 {{ query.page }} / {{ pageCount }} 页</span>
        <el-pagination background layout="sizes, prev, pager, next" :total="total"
          v-model:current-page="query.page" v-model:page-size="query.page_size"
          :page-sizes="[10, 20, 50, 100]" @current-change="fetchList" @size-change="fetchList" />
      </div>
    </el-card>

    <el-dialog v-model="adjustVisible" title="其他出入库" width="480px">
      <el-form :model="adj" label-width="90px">
        <el-form-item label="类型">
          <el-radio-group v-model="adj.direction">
            <el-radio value="in">入库</el-radio><el-radio value="out">出库</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="物料">
          <el-select v-model="adj.material_id" filterable style="width:100%">
            <el-option v-for="m in materials" :key="m.id" :label="m.material_code+' '+m.material_name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="仓库">
          <el-select v-model="adj.warehouse_id" style="width:100%"><el-option v-for="w in warehouses" :key="w.id" :label="w.warehouse_name" :value="w.id" /></el-select>
        </el-form-item>
        <el-form-item label="数量"><el-input-number v-model="adj.qty" :min="0.01" :precision="2" style="width:100%" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="adjustVisible=false">取消</el-button><el-button type="primary" @click="onAdjust">确定</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Search, Refresh, EditPen } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { inventoryApi } from '@/api/inventory'
import { materialApi, warehouseApi } from '@/api/basicData'
import { useSort } from '@/composables/useSort'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import SortChips from '@/components/SortChips.vue'
import BatchBar from '@/components/BatchBar.vue'

const query = reactive({ page: 1, page_size: 20, keyword: '', warehouse_id: null })
const list = ref([]); const total = ref(0); const loading = ref(false)
const materials = ref([]); const warehouses = ref([])
const adjustVisible = ref(false)
const adj = reactive({ direction: 'in', material_id: null, warehouse_id: null, qty: 1 })
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))
/** material_id → 物料编码（接口 /inventory 只返回 material_id，本页已为弹窗加载了全部物料） */
function codeOf(id) {
  const m = materials.value.find(i => i.id === id)
  return m?.material_code || '—'
}
/** material_id → 该物料的安全库存（同一份 materials 数据里的真实字段，未加载时显示「—」） */
function safetyOf(id) {
  const m = materials.value.find(i => i.id === id)
  const v = m?.safety_stock
  return v === undefined || v === null ? '—' : v
}
async function fetchList() { loading.value = true; try { const res = await inventoryApi.list({ ...query }); list.value = res.list || []; total.value = res.total || 0 } finally { loading.value = false } }
const { onSortChange, sortRules, removeSort, clearSort } = useSort(query, fetchList)

// ---- 批量操作（只读页：仅导出选中） ----
const batch = useBatch({ fetchList })
const batchActions = [
  { key: 'export', label: '导出选中', perm: 'inventory:view' }
]
// 导出列与表格列一一对应；物料编码/安全库存来自本页 materials 映射，同样用 formatter 还原
const exportColumns = [
  { prop: 'material_code', label: '物料编码', formatter: (r) => codeOf(r.material_id) },
  { prop: 'material_name', label: '物料' },
  { prop: 'warehouse_name', label: '仓库' },
  { prop: 'qty', label: '现存数量' },
  { prop: 'safety_stock', label: '安全库存', formatter: (r) => safetyOf(r.material_id) },
  { prop: 'last_move_date', label: '最后变动' }
]

function onBatchAction(key) {
  if (key === 'export') exportRows(batch.selected.value, exportColumns, '库存查询')
}

function onSearch() { query.page = 1; batch.clearSelection(); fetchList() }
function onReset() { query.keyword = ''; query.warehouse_id = null; onSearch() }
async function onAdjust() {
  if (!adj.material_id || !adj.warehouse_id) return ElMessage.warning('请选择物料和仓库')
  await inventoryApi.adjust({ ...adj, txn_type: adj.direction === 'in' ? '其他入库' : '其他出库' })
  ElMessage.success('操作成功'); adjustVisible.value = false; fetchList()
}
onMounted(async () => {
  fetchList()
  const [m, w] = await Promise.all([materialApi.list({ page: 1, page_size: 1000 }), warehouseApi.all()])
  materials.value = m.list || []; warehouses.value = w || []; adj.warehouse_id = w?.[0]?.id ?? null
})
</script>
<style scoped>
/* 筛选行铺满整行：两列自适应 + 按钮列，避免右侧留大片空白 */
.filter-grid.el-form--inline { display: grid; grid-template-columns: 1fr 1fr auto; width: 100%; }
.filter-grid .el-form-item { width: 100%; margin: 0; }
.filter-grid :deep(.el-form-item__content) { flex: 1 1 auto; min-width: 0; }
.filter-grid :deep(.el-input),
.filter-grid :deep(.el-select) { width: 100%; }
.low { color: #f56c6c; font-weight: 600; }
</style>
