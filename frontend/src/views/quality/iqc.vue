<template>
  <div class="page">
    <!-- 页头：标题 + 说明 + 主操作（原表格卡里的孤立按钮移到这里） -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><DocumentChecked /></el-icon>来料质检</h2>
        <div class="ph-desc">
          原材料到货后的抽检与合格数判定，结果回写供应商来料记录 · 共 <b>{{ total }}</b> 条
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
        <el-button type="primary" :icon="Plus" v-permission="'qc:edit'" @click="onAdd">新建质检单</el-button>
      </div>
    </div>

    <!-- 列表卡：筛选条 + 本页状态分布 + 表格 + 分页（原独立筛选卡已并入 .toolbar） -->
    <el-card shadow="never" class="card-fill">
      <div class="toolbar">
        <el-form :inline="true" :model="query" class="tb-left">
          <el-form-item label="状态">
            <el-select v-model="query.status" placeholder="全部" clearable style="width:120px">
              <el-option v-for="s in statusList" :key="s" :label="s" :value="s" />
            </el-select>
          </el-form-item>
          <el-form-item label="检验员">
            <el-input v-model="query.inspector" placeholder="姓名/工号" clearable style="width:120px" @keyup.enter="onSearch" />
          </el-form-item>
          <el-form-item label="单号">
            <el-input v-model="query.qc_no" placeholder="质检单号" clearable style="width:150px" @keyup.enter="onSearch" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :icon="Search" @click="onSearch">查询</el-button>
            <el-button :icon="Refresh" @click="onReset">重置</el-button>
          </el-form-item>
        </el-form>

        <!-- 本页状态分布：填充筛选条右侧留白 -->
        <div class="tb-right">
          <span v-for="s in statusList" :key="s" class="qc-stat">
            <span class="dot" :style="{ color: chipColor(s) }">{{ s }}</span>
            <b>{{ statusStats[s] }}</b>
          </span>
        </div>
        <SortChips :rules="sortRules" @remove="removeSort" @clear="clearSort" />
      </div>

      <!-- 批量操作条：勾选后才出现，不占固定高度 -->
      <BatchBar :batch="batch" :actions="batchActions" @action="onBatchAction" />

      <div class="table-wrap">
        <el-table :ref="batch.bindTable" :data="viewList" :row-key="(row) => row.id" v-loading="loading" border stripe
          @sort-change="onSortChange" @selection-change="batch.onSelectionChange">
          <el-table-column type="selection" width="50" align="center" reserve-selection />
          <el-table-column type="index" label="#" width="55" align="center" />
          <el-table-column prop="qc_no" label="质检单号" width="180" sortable="custom" show-overflow-tooltip />
          <!-- 两列都用 min-width：剩余宽度摊到「供应商 + 检验员」，避免全部堆在单列形成大片空白 -->
          <el-table-column prop="supplier_name" label="供应商" min-width="240" sortable="custom" show-overflow-tooltip />
          <el-table-column label="状态" width="104" align="center">
            <template #default="{ row }"><el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="inspector" label="检验员" min-width="120" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="created_at" label="时间" width="176" sortable="custom" show-overflow-tooltip />
          <el-table-column label="操作" width="130" fixed="right" align="center">
            <template #default="{ row }">
              <el-button link type="primary" v-permission="'qc:edit'" @click="onCheck(row)">录入结果</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="pager">
        <span class="hint">
          <template v-if="clientFiltered">筛选后 {{ viewList.length }} / 本页 {{ list.length }} 条 · </template>
          共 <b>{{ total }}</b> 条 · 第 {{ query.page }} / {{ pageCount }} 页
          <span v-if="clientFiltered" class="cli-tip">（检验员/单号为当前页前端筛选，后端仅支持按状态筛选）</span>
        </span>
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

    <el-dialog v-model="dialog.visible" title="新建来料质检单" width="720px">
      <el-form ref="formRef" :model="form" label-width="90px">
        <el-row :gutter="16">
          <el-col :span="8"><el-form-item label="供应商"><el-select v-model="form.supplier_id" filterable style="width:100%"><el-option v-for="s in suppliers" :key="s.id" :label="s.supplier_name" :value="s.id" /></el-select></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="检验员"><el-input v-model="form.inspector" /></el-form-item></el-col>
        </el-row>
        <el-form-item label="检验明细">
          <div style="margin-bottom:8px"><el-button size="small" :icon="Plus" @click="form.items.push({material_id:null,sample_qty:0,qualified_qty:0})">添加</el-button></div>
          <el-table :data="form.items" border size="small">
            <el-table-column label="物料" min-width="200" show-overflow-tooltip><template #default="{ row }"><el-select v-model="row.material_id" filterable style="width:100%"><el-option v-for="m in materials" :key="m.id" :label="m.material_code+' '+m.material_name" :value="m.id" /></el-select></template></el-table-column>
            <el-table-column label="抽检数" width="130" align="right" class-name="col-num"><template #default="{ row }"><el-input-number v-model="row.sample_qty" :min="0" :precision="2" style="width:100%" /></template></el-table-column>
            <el-table-column label="合格数" width="130" align="right" class-name="col-num"><template #default="{ row }"><el-input-number v-model="row.qualified_qty" :min="0" :precision="2" style="width:100%" /></template></el-table-column>
            <el-table-column label="操作" width="80" align="center"><template #default="{ $index }"><el-button link type="danger" @click="form.items.splice($index,1)">删除</el-button></template></el-table-column>
          </el-table>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="dialog.visible=false">取消</el-button><el-button type="primary" @click="onSubmit">确定</el-button></template>
    </el-dialog>

    <el-drawer v-model="check.visible" title="录入检验结果" size="600px">
      <template v-if="check.items">
        <el-table :data="check.items" border size="small">
          <el-table-column label="物料" show-overflow-tooltip><template #default="{ row }">{{ mapName(row.material_id) }}</template></el-table-column>
          <el-table-column label="抽检" prop="sample_qty" width="90" align="right" class-name="col-num" />
          <el-table-column label="合格数" width="130" align="right" class-name="col-num"><template #default="{ row }"><el-input-number v-model="row.qualified_qty" :min="0" :precision="2" style="width:100%" /></template></el-table-column>
          <el-table-column label="结果" width="140" align="center"><template #default="{ row }"><el-select v-model="row.result" style="width:100%"><el-option label="合格" value="合格" /><el-option label="不合格" value="不合格" /><el-option label="让步接收" value="让步接收" /></el-select></template></el-table-column>
        </el-table>
        <div style="margin-top:12px;text-align:right"><el-button type="primary" @click="saveCheck">保存结果</el-button></div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Search, Refresh, Plus, DocumentChecked } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { qualityApi } from '@/api/quality'
import { materialApi, supplierApi } from '@/api/basicData'
import { useSort } from '@/composables/useSort'
import { applyRouteFilter } from '@/composables/useAutoFilter'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import SortChips from '@/components/SortChips.vue'
import BatchBar from '@/components/BatchBar.vue'

const statusList = ['待检', '合格', '不合格', '让步接收']
const statusType = (s) => ({ 待检: 'warning', 合格: 'success', 不合格: 'danger', 让步接收: '' }[s] || '')
const chipColor = (s) => ({ 待检: '#e6a23c', 合格: '#10b981', 不合格: '#f56c6c', 让步接收: '#909399' }[s] || '#909399')
const query = reactive({ page: 1, page_size: 20, status: '', inspector: '', qc_no: '' })
applyRouteFilter(query) // 首页待办跳转自动带筛选
const list = ref([]); const total = ref(0); const loading = ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))
// 本页状态计数（仅统计当前页数据，纯展示）
const statusStats = computed(() => {
  const acc = {}
  for (const s of statusList) acc[s] = 0
  for (const r of list.value) if (acc[r.status] !== undefined) acc[r.status]++
  return acc
})
// 检验员 / 单号为当前页前端筛选（后端仅支持 status 参数，调用参数保持原样）
const clientFiltered = computed(() => !!(query.inspector || query.qc_no))
const viewList = computed(() => {
  const kw = query.inspector.trim(); const no = query.qc_no.trim()
  if (!kw && !no) return list.value
  return list.value.filter(r =>
    (!kw || String(r.inspector || '').includes(kw)) &&
    (!no || String(r.qc_no || '').includes(no)))
})
const materials = ref([]); const suppliers = ref([])
const dialog = reactive({ visible: false }); const formRef = ref()
const form = reactive({ supplier_id: null, inspector: '', items: [] })
const check = reactive({ visible: false, id: null, items: null })
const mapName = (id) => materials.value.find(m => m.id === id)?.material_name || id
async function fetchList() { loading.value = true; try { const res = await qualityApi.iqcList({ ...query }); list.value = res.list || []; total.value = res.total || 0 } finally { loading.value = false } }
const { onSortChange, sortRules, removeSort, clearSort } = useSort(query, fetchList)

// ---- 批量操作 ----
const batch = useBatch({ fetchList })
// 动作按权限过滤：无权限的按钮不渲染（与行操作按钮的 v-permission 一致）
const batchActions = [
  { key: 'approve', label: '批量判定合格', type: 'success', perm: 'qc:edit' },
  { key: 'reject', label: '批量判定不合格', type: 'danger', perm: 'qc:edit' },
  { key: 'export', label: '导出选中', perm: 'qc:view' }
]
// 导出用列定义与表格列保持一致，避免导出后对不上
const exportColumns = [
  { prop: 'qc_no', label: '质检单号' },
  { prop: 'supplier_name', label: '供应商' },
  { prop: 'status', label: '状态' },
  { prop: 'inspector', label: '检验员' },
  { prop: 'created_at', label: '时间' }
]

async function onBatchAction(key) {
  if (key === 'export') {
    exportRows(batch.selected.value, exportColumns, '来料质检单')
    return
  }
  const n = batch.count.value
  // 批量判定是「整单级」动作：用户容易误以为能逐项指定结果，confirm 里必须说清语义
  const confirm = key === 'approve'
    ? `确认将选中的 ${n} 张来料质检单批量判定为「合格」？批量判定合格会把每张单下的全部明细项一次性置为合格，并按汇总规则更新整单状态（不是逐项指定结果）；已判定的单据（合格 / 让步接收 / 不合格）会被后端逐条拒绝，失败明细会在结果弹窗中列出。`
    : `确认将选中的 ${n} 张来料质检单批量判定为「不合格」？该操作直接把整单状态置为不合格（不修改明细结果），已是不合格状态的单据会被后端逐条拒绝。`
  await batch.run(qualityApi.iqcBatch, key, {
    label: key === 'approve' ? '批量判定合格' : '批量判定不合格',
    confirm,
    reasonRequired: key === 'reject',
    prompt: '请输入判定不合格的原因'
  })
}

function onSearch() { query.page = 1; batch.clearSelection(); fetchList() }
function onReset() { query.status = ''; query.inspector = ''; query.qc_no = ''; onSearch() }
function onAdd() { Object.assign(form, { supplier_id: null, inspector: '', items: [] }); form.items.push({ material_id: null, sample_qty: 0, qualified_qty: 0 }); dialog.visible = true }
async function onSubmit() { if (form.items.some(i => !i.material_id)) return ElMessage.warning('请完善明细'); await qualityApi.iqcCreate(form); ElMessage.success('创建成功'); dialog.visible = false; fetchList() }
async function onCheck(row) {
  check.id = row.id
  const res = await qualityApi.iqcDetail(row.id)
  check.items = res.items.map(i => ({ id: i.id, material_id: i.material_id, sample_qty: i.sample_qty, qualified_qty: i.qualified_qty, result: i.result === '待检' ? '合格' : i.result }))
  check.visible = true
}
async function saveCheck() { await qualityApi.iqcCheck(check.id, { items: check.items }); ElMessage.success('已保存'); check.visible = false; fetchList() }
onMounted(async () => { fetchList(); const [m, s] = await Promise.all([materialApi.list({ page: 1, page_size: 1000 }), supplierApi.list({ page: 1, page_size: 1000 })]); materials.value = m.list || []; suppliers.value = s.list || [] })
</script>
<style scoped>
/* 本页专属：筛选条右侧的本页状态分布 + 前端筛选提示 */
.qc-stat { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); }
.qc-stat b { font-variant-numeric: tabular-nums; color: var(--text-1); }
.cli-tip { color: var(--text-3); }
</style>
