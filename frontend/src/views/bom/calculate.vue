<template>
  <div class="page">
    <!-- 页头 -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Operation /></el-icon>BOM 算料</h2>
        <div class="ph-desc">选择成品与数量，按 BOM 计算物料需求量与库存缺口</div>
      </div>
      <div class="ph-actions">
        <el-button v-if="result" :icon="Refresh" @click="onResetCalc">重新算料</el-button>
      </div>
    </div>

    <!-- 参数区：单行工具栏，按钮右对齐 -->
    <el-card shadow="never" class="calc-tool">
      <div class="toolbar">
        <el-form :inline="true" :model="form" class="tb-left">
          <el-form-item label="成品">
            <el-select v-model="form.product_id" filterable placeholder="选择成品" style="width:260px" @change="loadVersions">
              <el-option v-for="p in products" :key="p.id" :label="p.material_code+' '+p.material_name" :value="p.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="版本">
            <el-select v-model="form.version" clearable placeholder="生效版本" style="width:160px">
              <el-option v-for="v in versions" :key="v" :label="v" :value="v" />
            </el-select>
          </el-form-item>
          <el-form-item label="数量">
            <el-input-number v-model="form.qty" :min="1" :precision="2" style="width:150px" />
          </el-form-item>
        </el-form>
        <div class="tb-right">
          <el-button type="primary" :icon="Operation" :loading="loading" @click="onCalc">开始算料</el-button>
        </div>
      </div>
    </el-card>

    <!-- 结果区：真实卡片撑满剩余高度，未算料时也不是空白 -->
    <el-card shadow="never" class="card-fill">
      <template v-if="result">
        <!-- 结果标题行 + 生成请购单（按钮在卡片首行右侧） -->
        <div class="result-head">
          <span class="rh-title">
            <el-icon><Tickets /></el-icon>
            BOM 算料结果 —— <b>{{ result.product_name }}</b> × <b>{{ result.qty }}</b>
            <el-tag size="small" type="info" effect="plain">版本 {{ result.version }}</el-tag>
          </span>
          <div class="ph-actions">
            <el-button type="primary" :icon="DocumentAdd" v-permission="'purchase:requisition:add'"
              :loading="generating" @click="onGenerateRequisition">生成请购单</el-button>
          </div>
        </div>

        <!-- 关键指标条：算料后一眼看到总量与缺口 -->
        <div class="stat-strip">
          <div class="stat-item">
            <div class="si-icon"><el-icon><Coin /></el-icon></div>
            <div><div class="si-num">{{ result.items.length }}</div><div class="si-label">物料项数</div></div>
          </div>
          <div class="stat-item">
            <div class="si-icon"><el-icon><Box /></el-icon></div>
            <div><div class="si-num">{{ totalRequired }}</div><div class="si-label">需求量合计</div></div>
          </div>
          <div class="stat-item">
            <div class="si-icon"><el-icon><Refresh /></el-icon></div>
            <div><div class="si-num">{{ totalStock }}</div><div class="si-label">现有库存合计</div></div>
          </div>
          <div class="stat-item">
            <div class="si-icon"><el-icon><Warning /></el-icon></div>
            <div>
              <div class="si-num" :style="{ color: shortageCount ? '#f56c6c' : '#10b981' }">{{ shortageCount }}</div>
              <div class="si-label">存在缺口物料</div>
            </div>
          </div>
        </div>

        <!-- 算料结果是前端计算结果，后端只提供计算接口、没有按 id 的批量写语义，因此只提供「导出选中」 -->
        <BatchBar :batch="batch" :actions="batchActions" @action="onBatchAction" />

        <div class="table-wrap">
          <el-table :ref="batch.bindTable" :data="result.items" :row-key="(row) => row.material_id" border stripe
            @selection-change="batch.onSelectionChange">
            <el-table-column type="selection" width="50" align="center" reserve-selection />
            <el-table-column type="index" label="#" width="55" align="center" />
            <el-table-column prop="material_code" label="物料编码" width="140" show-overflow-tooltip />
            <el-table-column prop="material_name" label="物料名称" min-width="180" show-overflow-tooltip />
            <el-table-column prop="spec" label="规格" min-width="130" show-overflow-tooltip />
            <el-table-column prop="category" label="分类" width="110" align="center" show-overflow-tooltip />
            <el-table-column prop="unit" label="单位" width="76" align="center" show-overflow-tooltip />
            <el-table-column prop="required_qty" label="需求量(含损耗)" width="150" align="right" class-name="col-num">
              <template #default="{ row }">{{ row.required_qty }} {{ row.unit }}</template>
            </el-table-column>
            <el-table-column prop="stock_qty" label="现有库存" width="120" align="right" class-name="col-num" />
            <el-table-column prop="shortage_qty" label="缺口" width="110" align="right" class-name="col-num">
              <template #default="{ row }">
                <span :style="{ color: row.shortage_qty > 0 ? '#f56c6c' : '#67c23a', fontWeight: 600 }">
                  {{ row.shortage_qty > 0 ? row.shortage_qty : '充足' }}
                </span>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <el-alert type="info" :closable="false" show-icon
          title="说明：递归展开 BOM，单耗 × 数量 × (1 + 损耗率)；仅汇总无下级 BOM 的原料。" />
      </template>

      <!-- 未算料（仅当没有可选成品时才会出现，首屏已自动算料）：按钮只保留在工具条上一次 -->
      <div v-else class="calc-empty">
        <el-empty description="">
          <template #description>
            <div class="ce-title">暂无可算料的成品</div>
            <div class="ce-desc">当前物料档案里没有「成品」分类的数据，或成品尚未建立 BOM。请先在「BOM 清单」维护成品的物料清单，再回到本页算料。</div>
          </template>
        </el-empty>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Operation, DocumentAdd, Refresh, Tickets, Coin, Box, Warning } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { bomApi } from '@/api/bom'
import { materialApi } from '@/api/basicData'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import BatchBar from '@/components/BatchBar.vue'

const router = useRouter()
const products = ref([])
const versions = ref([])
const form = reactive({ product_id: null, version: '', qty: 1 })
const result = ref(null)
const loading = ref(false)
const generating = ref(false)   // 生成请购单中，防重复点击

// 结果汇总（纯展示）：需求量/库存合计与缺口物料数
const num = (v) => Number(v) || 0

// ---- 批量操作（结果页只读：仅导出选中） ----
// 结果行由后端按 material_id 聚合，每行 material_id 唯一，故用它作 row-key（后端不返回行 id）
const batch = useBatch()
const batchActions = [
  { key: 'export', label: '导出选中', perm: 'bom:view' }
]
// 导出列与结果表格列一一对应；缺口为 0 时表格显示「充足」，导出保持同一口径
const exportColumns = [
  { prop: 'material_code', label: '物料编码' },
  { prop: 'material_name', label: '物料名称' },
  { prop: 'spec', label: '规格' },
  { prop: 'category', label: '分类' },
  { prop: 'unit', label: '单位' },
  { prop: 'required_qty', label: '需求量(含损耗)' },
  { prop: 'stock_qty', label: '现有库存' },
  { prop: 'shortage_qty', label: '缺口', formatter: (r) => (num(r.shortage_qty) > 0 ? r.shortage_qty : '充足') }
]

function onBatchAction(key) {
  if (key === 'export') exportRows(batch.selected.value, exportColumns, 'BOM算料结果')
}

const totalRequired = computed(() => num((result.value?.items || []).reduce((s, r) => s + num(r.required_qty), 0).toFixed(2)))
const totalStock = computed(() => num((result.value?.items || []).reduce((s, r) => s + num(r.stock_qty), 0).toFixed(2)))
const shortageCount = computed(() => (result.value?.items || []).filter(r => num(r.shortage_qty) > 0).length)

async function loadVersions() {
  versions.value = []; form.version = ''
  if (!form.product_id) return
  const res = await bomApi.list({ product_id: form.product_id, page: 1, page_size: 100 })
  versions.value = [...new Set((res.list || []).map(b => b.version))]
}
async function onCalc() {
  if (!form.product_id) return ElMessage.warning('请选择成品')
  loading.value = true
  batch.clearSelection() // 结果行整体重算，旧的勾选必须清掉
  try { result.value = await bomApi.calculate({ product_id: form.product_id, version: form.version || undefined, qty: form.qty }) } finally { loading.value = false }
}
// 收起结果卡片，回到参数区重新算料（纯展示状态清理）
function onResetCalc() { batch.clearSelection(); result.value = null }
onMounted(async () => {
  const res = await materialApi.list({ page: 1, page_size: 1000 })
  products.value = (res.list || []).filter(m => m.category === '成品')
  // 首屏直接出结果：默认选中第一个成品并自动算料一次（无成品时才落到空态）
  const first = products.value[0]
  if (!first) return
  form.product_id = first.id
  await loadVersions()
  await onCalc()
})

/** 把当前算料结果一键生成请购单：只写入「需求量 − 现有库存」的净缺口明细 */
async function onGenerateRequisition() {
  if (!result.value) { ElMessage.warning('请先执行算料'); return }
  // 确认框：点取消必须静默返回，不能产生未捕获的 Promise 拒绝
  try {
    await ElMessageBox.confirm(
      '将按「需求量 − 现有库存」的净需求生成请购单：库存已充足的行会被自动跳过，'
      + '生成的单据为「草稿」状态，需人工审核后才能转采购订单。是否继续？',
      '生成请购单',
      { type: 'warning', confirmButtonText: '确认生成', cancelButtonText: '取消' }
    )
  } catch (e) { return }
  generating.value = true
  try {
    // 明细按算料结果原样回传：material_id / required_qty / unit 与后端契约一致
    const items = (result.value.items || []).map(r => ({
      material_id: r.material_id,
      required_qty: r.required_qty,
      unit: r.unit
    }))
    const res = await bomApi.toRequisition({
      product_id: result.value.product_id,
      version: result.value.version || undefined,
      qty: result.value.qty,
      items,
      remark: '由 BOM 算料页生成'
    })
    const extra = res?.skipped_count > 0 ? `，${res.skipped_count} 项因库存充足已跳过` : ''
    ElMessage.success(`已生成请购单 ${res?.req_no || ''}（共 ${res?.item_count || 0} 条明细）${extra}`)
    // 询问是否跳转请购单列表，取消同样静默返回
    try {
      await ElMessageBox.confirm('是否立即查看该请购单？', '提示',
        { type: 'success', confirmButtonText: '立即查看', cancelButtonText: '留在本页' })
    } catch (e) { return }
    router.push('/procurement/requisition')
  } catch (e) {
    // 响应拦截器已统一弹出后端错误提示，这里不再重复提示
  } finally { generating.value = false }
}
</script>
<style scoped>
/* 本页专属：参数卡片按内容高度，结果卡片吃满剩余高度；
   空状态垂直居中（全局 .card-fill 只负责撑高，居中在此补齐） */
.calc-tool { flex: 0 0 auto; }
.calc-empty { flex: 1 1 auto; min-height: 0; display: flex; align-items: center; justify-content: center; }
.ce-title { font-size: 15px; font-weight: 600; color: var(--text-1); margin-bottom: 6px; }
.ce-desc { max-width: 460px; margin: 0 auto 14px; font-size: 12px; line-height: 1.7; color: var(--text-2); }
.result-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
.rh-title { display: flex; align-items: center; gap: 8px; font-size: 14px; }
.rh-title b { color: var(--brand-dark); }
</style>
