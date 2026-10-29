<template>
  <div class="page">
    <!-- 页头：标题 + 说明 + 刷新 -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><TrendCharts /></el-icon>库存报表</h2>
        <div class="ph-desc">
          近 7 天出入库趋势与当前结存分布，收发存汇总可筛选 ·
          共 <b>{{ filteredSummary.length }}</b> / {{ summary.length }} 种库存物料
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <!-- 筛选卡：与采购报表保持同一套结构 -->
    <el-card shadow="never" class="filter-card">
      <div class="toolbar">
        <el-form :inline="true" :model="filter" class="tb-left">
          <el-form-item label="物料关键字">
            <el-input v-model="filter.keyword" placeholder="物料编码 / 名称" clearable style="width: 200px" @keyup.enter="onSearch" />
          </el-form-item>
          <el-form-item label="分类">
            <el-select v-model="filter.category" placeholder="全部" clearable style="width: 130px">
              <el-option v-for="c in categoryOptions" :key="c" :label="c" :value="c" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :icon="Search" @click="onSearch">查询</el-button>
            <el-button :icon="Refresh" @click="onReset">重置</el-button>
          </el-form-item>
        </el-form>
        <div class="tb-right"><span class="tb-hint">筛选同时作用于下方汇总表格与分类分布图</span></div>
      </div>
    </el-card>

    <!-- KPI 统计条：铺满整行，与筛选行同一视觉层级 -->
    <div class="stat-strip">
      <div class="stat-item">
        <div class="si-icon si-blue"><el-icon><Box /></el-icon></div>
        <div>
          <div class="si-num">{{ filteredSummary.length }}</div>
          <div class="si-label">库存物料种类</div>
        </div>
      </div>
      <div class="stat-item">
        <div class="si-icon si-teal"><el-icon><Coin /></el-icon></div>
        <div>
          <div class="si-num">{{ totalStock }}</div>
          <div class="si-label">结存总量</div>
        </div>
      </div>
      <div class="stat-item">
        <div class="si-icon" :class="lowStock > 0 ? 'si-red' : 'si-gray'"><el-icon><Warning /></el-icon></div>
        <div>
          <div class="si-num" :style="{ color: lowStock > 0 ? '#f56c6c' : '' }">{{ lowStock }}</div>
          <div class="si-label">低于安全库存</div>
        </div>
      </div>
    </div>

    <!-- 图表区：与采购报表统一卡片与高度 -->
    <div class="grid-2">
      <el-card shadow="never" class="chart-card">
        <template #header>近 7 天出入库趋势</template>
        <div ref="trendRef" class="chart-box" />
      </el-card>
      <el-card shadow="never" class="chart-card">
        <template #header>库存结存按分类分布</template>
        <div ref="pieRef" class="chart-box" />
      </el-card>
    </div>

    <!-- 收发存汇总：卡片撑满剩余高度，表格内部滚动，底部信息条常驻 -->
    <el-card shadow="never" class="card-fill">
      <!-- 批量操作条：只读统计页只提供「导出选中」，勾选后才出现、不占固定高度 -->
      <BatchBar :batch="batch" :actions="batchActions" @action="onBatchAction" />

      <div class="table-wrap">
        <el-table :ref="batch.bindTable" :data="filteredSummary" :row-key="(row) => row.material_id" border stripe
          @selection-change="batch.onSelectionChange">
          <el-table-column type="selection" width="50" align="center" reserve-selection />
          <el-table-column type="index" label="#" width="55" align="center" />
          <el-table-column prop="material_code" label="物料编码" width="130" show-overflow-tooltip />
          <el-table-column prop="material_name" label="物料" min-width="170" sortable show-overflow-tooltip />
          <el-table-column prop="spec" label="规格" min-width="120" show-overflow-tooltip />
          <el-table-column prop="category" label="分类" width="90" align="center" />
          <el-table-column prop="unit" label="单位" width="70" align="center" />
          <el-table-column prop="stock_qty" label="结存数量" width="140" sortable align="right" class-name="col-num">
            <template #default="{ row }">{{ row.stock_qty }} {{ row.unit }}</template>
          </el-table-column>
          <el-table-column label="安全库存" width="110" align="right" class-name="col-num">
            <template #default="{ row }">{{ row.safety_stock }}</template>
          </el-table-column>
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.stock_qty <= row.safety_stock" type="danger" size="small">偏低</el-tag>
              <el-tag v-else type="success" size="small">正常</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right" align="center">
            <template #default="{ row }">
              <el-button link type="primary" @click="showDetail(row)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div class="pager">
        <span class="hint">
          共 <b>{{ filteredSummary.length }}</b> 条 · 全部 {{ summary.length }} 种物料<span v-if="isFiltered">（已筛选）</span>
        </span>
      </div>
    </el-card>

    <DetailDialog v-model="dlg.visible" :title="`库存明细 — ${dlg.name}`" :width="1000">
      <div class="detail-title">各仓结存</div>
      <el-table :data="dlg.byWarehouse" border size="small" style="margin-bottom:16px">
        <el-table-column type="index" label="#" width="50" align="center" />
        <el-table-column prop="warehouse" label="仓库" min-width="160" show-overflow-tooltip />
        <el-table-column prop="stock_qty" label="结存数量" align="right" class-name="col-num" />
      </el-table>
      <div class="detail-title">最近出入库流水</div>
      <el-table :data="dlg.flows" border size="small" max-height="320">
        <el-table-column type="index" label="#" width="50" align="center" />
        <el-table-column prop="txn_no" label="流水号" width="180" show-overflow-tooltip />
        <el-table-column prop="txn_time" label="时间" width="150" show-overflow-tooltip />
        <el-table-column prop="txn_type" label="类型" width="120" show-overflow-tooltip />
        <el-table-column prop="warehouse" label="仓库" min-width="120" show-overflow-tooltip />
        <el-table-column prop="in_qty" label="入库" width="90" align="right" class-name="col-num" />
        <el-table-column prop="out_qty" label="出库" width="90" align="right" class-name="col-num" />
        <el-table-column prop="operator" label="操作人" width="100" show-overflow-tooltip />
      </el-table>
    </DetailDialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Search, Refresh, TrendCharts, Box, Coin, Warning } from '@element-plus/icons-vue'
import { reportApi } from '@/api/report'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import DetailDialog from '@/components/DetailDialog.vue'
import BatchBar from '@/components/BatchBar.vue'
import {
  AXIS_LABEL, AXIS_LINE, CHART_COLORS, CHART_TOOLTIP, COLOR_IN, COLOR_OUT, DEFAULT_GRID, SPLIT_LINE,
  areaGradient, axisTooltipFormatter, emptyOption, numText, useChart,
} from '@/composables/useChart'

const trend = ref([])
const summary = ref([])
const dlg = ref({ visible: false, name: '', byWarehouse: [], flows: [] })

// 筛选条件（本页筛选为纯前端过滤，不改动任何接口请求参数）
const filter = reactive({ keyword: '', category: '' })
const applied = reactive({ keyword: '', category: '' })

const categoryOptions = computed(() => [...new Set(summary.value.map(r => r.category).filter(Boolean))])
const isFiltered = computed(() => !!(applied.keyword || applied.category))
const filteredSummary = computed(() => {
  const kw = applied.keyword.trim().toLowerCase()
  return summary.value.filter(r => {
    if (applied.category && r.category !== applied.category) return false
    if (!kw) return true
    return String(r.material_code || '').toLowerCase().includes(kw)
      || String(r.material_name || '').toLowerCase().includes(kw)
  })
})

const totalStock = computed(() => filteredSummary.value.reduce((s, r) => s + (r.stock_qty || 0), 0).toLocaleString('zh-CN'))
const lowStock = computed(() => filteredSummary.value.filter(r => r.stock_qty <= (r.safety_stock || 0)).length)

/* -------------------- 图表：近 7 天出入库趋势 -------------------- */
const trendRef = ref(null)
function trendOption() {
  const list = trend.value || []
  if (!list.length) return emptyOption('暂无出入库数据')
  return {
    color: [COLOR_IN, COLOR_OUT],
    tooltip: { ...CHART_TOOLTIP, trigger: 'axis', formatter: axisTooltipFormatter() },
    legend: {
      top: 4, right: 4, icon: 'roundRect', itemWidth: 10, itemHeight: 10, itemGap: 18,
      textStyle: { color: '#64748b', fontSize: 12 },
    },
    grid: DEFAULT_GRID,
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: list.map(d => String(d.date || '').slice(5)),
      axisTick: { show: false },
      axisLine: AXIS_LINE,
      axisLabel: AXIS_LABEL,
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: SPLIT_LINE,
      axisLabel: AXIS_LABEL,
    },
    series: [
      {
        name: '入库', type: 'line', smooth: true, symbol: 'circle', symbolSize: 7,
        lineStyle: { width: 2.5, color: COLOR_IN }, itemStyle: { color: COLOR_IN },
        areaStyle: { color: areaGradient(COLOR_IN) },
        data: list.map(d => Number(d.in || 0)),
      },
      {
        name: '出库', type: 'line', smooth: true, symbol: 'circle', symbolSize: 7,
        lineStyle: { width: 2.5, color: COLOR_OUT }, itemStyle: { color: COLOR_OUT },
        areaStyle: { color: areaGradient(COLOR_OUT) },
        data: list.map(d => Number(d.out || 0)),
      },
    ],
  }
}
useChart(trendRef, trendOption, { watchSources: () => [trend.value] })

/* -------------------- 图表：库存结存按分类分布（环形图） --------------------
 * 说明：/reports/inventory-summary 实际返回字段为
 *   material_id / material_code / material_name / spec / category / unit / safety_stock / stock_qty
 * 该接口不含「仓库」维度，也不含金额字段，故此处按 category 聚合 stock_qty 展示数量分布。
 */
const pieRef = ref(null)
function pieOption() {
  const list = filteredSummary.value || []
  if (!list.length) return emptyOption('暂无库存数据')
  const grouped = new Map()
  list.forEach(r => {
    const key = r.category || '未分类'
    grouped.set(key, (grouped.get(key) || 0) + Number(r.stock_qty || 0))
  })
  const data = [...grouped.entries()]
    .map(([name, value]) => ({ name, value: Math.round(value * 100) / 100 }))
    .sort((a, b) => b.value - a.value)
  if (!data.length) return emptyOption('暂无库存数据')
  const total = data.reduce((s, d) => s + d.value, 0)
  return {
    color: CHART_COLORS,
    title: {
      text: numText(Math.round(total * 100) / 100),
      subtext: '结存总量',
      left: '50%',
      top: '31%',
      textAlign: 'center',
      textStyle: { color: '#1f2937', fontSize: 16, fontWeight: 700 },
      subtextStyle: { color: '#94a3b8', fontSize: 12 },
    },
    tooltip: {
      ...CHART_TOOLTIP,
      trigger: 'item',
      formatter: (p) => `${p.marker}${p.name}<br/>结存数量：<b>${numText(p.value)}</b>（${p.percent}%）`,
    },
    // 图例整行铺开（plain 自动换行），各分类一次可见，不再翻页
    legend: {
      type: 'plain', bottom: 0, left: 'center', orient: 'horizontal',
      icon: 'circle', itemWidth: 8, itemHeight: 8, itemGap: 10,
      textStyle: { color: '#64748b', fontSize: 11 },
    },
    series: [{
      name: '结存数量',
      type: 'pie',
      radius: ['40%', '58%'],
      center: ['50%', '37%'],
      avoidLabelOverlap: true,
      itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 4 },
      label: { show: false },
      labelLine: { show: false },
      emphasis: { scale: true, scaleSize: 6 },
      data,
    }],
  }
}
useChart(pieRef, pieOption, { watchSources: () => [filteredSummary.value] })

/* ---------------- 批量导出（只读统计页：无批量写动作） ----------------
 * 汇总行主键为 material_id（后端 /reports/inventory-summary 返回），可稳定跨页保留勾选。
 */
const batch = useBatch({})
const batchActions = [{ key: 'export', label: '导出选中', perm: 'report:view' }]
// 导出用列定义与表格列保持一致，避免导出后对不上
const exportColumns = [
  { prop: 'material_code', label: '物料编码' },
  { prop: 'material_name', label: '物料' },
  { prop: 'spec', label: '规格' },
  { prop: 'category', label: '分类' },
  { prop: 'unit', label: '单位' },
  { prop: 'stock_qty', label: '结存数量' },
  { prop: 'safety_stock', label: '安全库存' },
  { prop: 'status', label: '状态', formatter: (r) => (r.stock_qty <= r.safety_stock ? '偏低' : '正常') }
]
function onBatchAction(key) {
  if (key === 'export') exportRows(batch.selected.value, exportColumns, '库存报表_收发存汇总')
}

async function load() {
  // 重新取数会整体换掉表格行，先清空勾选，避免把旧行带进下一次导出
  batch.clearSelection()
  try {
    const [t, s] = await Promise.all([reportApi.inventoryTrend({ days: 7 }), reportApi.inventorySummary()])
    trend.value = t || []
    summary.value = s || []
  } catch (e) {
    // 接口或权限异常时兜底为空数据，图表显示「暂无数据」，不白屏、不报错
    trend.value = []
    summary.value = []
    console.warn('inventory report load failed', e)
  }
}
function onSearch() {
  // 筛选是纯前端过滤：被筛掉的行会「隐身」但仍在勾选里，先清空
  batch.clearSelection()
  applied.keyword = filter.keyword; applied.category = filter.category
}
function onReset() {
  batch.clearSelection()
  filter.keyword = ''; filter.category = ''
  applied.keyword = ''; applied.category = ''
}

async function showDetail(row) {
  dlg.value = { visible: true, name: row.material_name, byWarehouse: [], flows: [] }
  const res = await reportApi.inventoryMaterialDetail({ material_id: row.material_id })
  dlg.value.byWarehouse = res.by_warehouse || []
  dlg.value.flows = res.flows || []
}
onMounted(load)
</script>
<style scoped>
/* 筛选卡：更紧凑的内边距 */
/* 筛选卡：更紧凑的内边距；不参与压缩，保证筛选控件完整可见 */
.filter-card { flex: 0 0 auto; }
.filter-card :deep(.el-card__body) { padding: 12px 16px; }
.tb-hint { font-size: 12px; color: var(--text-3); }
/* KPI 图标配色 */
.si-icon.si-blue { background: #eaf2ff; color: #2f6fed; }
.si-icon.si-teal { background: #e6faf7; color: #14b8a6; }
.si-icon.si-red { background: #fdecec; color: #f56c6c; }
.si-icon.si-gray { background: #f1f5f9; color: #94a3b8; }
/* 图表卡片：与采购报表统一高度，压缩首屏占用 */
.chart-card :deep(.el-card__body) { padding: 8px 12px 10px; }
.chart-box { width: 100%; height: 260px; }
.detail-title { font-weight: 600; color: #0f172a; margin: 2px 0 8px; }
</style>
