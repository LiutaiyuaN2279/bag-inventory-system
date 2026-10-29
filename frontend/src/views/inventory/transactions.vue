<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Tickets /></el-icon>出入库流水</h2>
        <div class="ph-desc">所有采购入库、退货出库、盘点盈亏与其他出入库的记账明细 · 共 <b>{{ total }}</b> 条</div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
      </div>
    </div>

    <el-card shadow="never" class="card-fill">
      <div class="toolbar">
        <el-form :inline="true" :model="query" class="tb-left filter-grid">
          <el-form-item label="关键字">
            <el-input v-model="query.keyword" placeholder="物料名称" clearable @keyup.enter="onSearch" />
          </el-form-item>
          <el-form-item label="类型">
            <el-select v-model="query.txn_type" placeholder="全部类型" clearable>
              <el-option v-for="t in types" :key="t" :label="t" :value="t" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :icon="Search" @click="onSearch">查询</el-button>
            <el-button :icon="Refresh" @click="onReset">重置</el-button>
          </el-form-item>
        </el-form>
      </div>
      <SortChips :rules="sortRules" @remove="removeSort" @clear="clearSort" />
      <!-- 只读页：本页只有「导出选中」，无批量写动作（流水不可改） -->
      <BatchBar :batch="batch" :actions="batchActions" @action="onBatchAction" />
      <div class="table-wrap">
        <el-table :ref="batch.bindTable" :data="list" :row-key="(row) => row.id" v-loading="loading" border stripe
          @sort-change="onSortChange" @selection-change="batch.onSelectionChange">
          <el-table-column type="selection" width="50" align="center" reserve-selection />
          <el-table-column prop="txn_no" label="流水号" min-width="190" sortable="custom" show-overflow-tooltip />
          <el-table-column label="类型" width="110" align="center">
            <template #default="{ row }"><el-tag size="small" :type="row.in_qty>0?'success':'danger'">{{ row.txn_type }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="material_name" label="物料" min-width="170" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="warehouse_name" label="仓库" min-width="130" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="in_qty" label="入库" width="100" align="right" class-name="col-num" sortable="custom" />
          <el-table-column prop="out_qty" label="出库" width="100" align="right" class-name="col-num" sortable="custom" />
          <el-table-column prop="ref_type" label="来源单据" width="120" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="operator" label="操作人" width="90" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="txn_time" label="时间" width="170" sortable="custom" show-overflow-tooltip />
        </el-table>
      </div>
      <div class="pager">
        <span class="hint">共 <b>{{ total }}</b> 条 · 第 {{ query.page }} / {{ pageCount }} 页</span>
        <el-pagination background layout="sizes, prev, pager, next" :total="total"
          v-model:current-page="query.page" v-model:page-size="query.page_size"
          :page-sizes="[10, 20, 50, 100]" @current-change="fetchList" @size-change="fetchList" />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Search, Refresh, Tickets } from '@element-plus/icons-vue'
import { inventoryApi } from '@/api/inventory'
import { useSort } from '@/composables/useSort'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import SortChips from '@/components/SortChips.vue'
import BatchBar from '@/components/BatchBar.vue'

const types = ['采购入库', '采购退货出库', '盘盈入库', '盘亏出库', '其他入库', '其他出库']
const query = reactive({ page: 1, page_size: 20, keyword: '', txn_type: '' })
const list = ref([]); const total = ref(0); const loading = ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))
async function fetchList() { loading.value = true; try { const res = await inventoryApi.transactions({ ...query }); list.value = res.list || []; total.value = res.total || 0 } finally { loading.value = false } }
const { onSortChange, sortRules, removeSort, clearSort } = useSort(query, fetchList)

// ---- 批量操作（只读页：仅导出选中） ----
const batch = useBatch({ fetchList })
const batchActions = [
  { key: 'export', label: '导出选中', perm: 'inventory:view' }
]
// 导出列与表格列一一对应：入库/出库按方向转中文，与列表标签口径一致
const exportColumns = [
  { prop: 'txn_no', label: '流水号' },
  { prop: 'txn_type', label: '类型' },
  { prop: 'material_name', label: '物料' },
  { prop: 'warehouse_name', label: '仓库' },
  { prop: 'in_qty', label: '入库' },
  { prop: 'out_qty', label: '出库' },
  { prop: 'ref_type', label: '来源单据' },
  { prop: 'operator', label: '操作人' },
  { prop: 'txn_time', label: '时间' }
]

function onBatchAction(key) {
  if (key === 'export') exportRows(batch.selected.value, exportColumns, '出入库流水')
}

function onSearch() { query.page = 1; batch.clearSelection(); fetchList() }
function onReset() { query.keyword = ''; query.txn_type = ''; onSearch() }
onMounted(fetchList)
</script>
<style scoped>
/* 筛选行铺满整行：两列自适应 + 按钮列，与库存查询保持一致 */
.filter-grid.el-form--inline { display: grid; grid-template-columns: 1fr 1fr auto; width: 100%; }
.filter-grid .el-form-item { width: 100%; margin: 0; }
.filter-grid :deep(.el-form-item__content) { flex: 1 1 auto; min-width: 0; }
.filter-grid :deep(.el-input),
.filter-grid :deep(.el-select) { width: 100%; }
</style>
