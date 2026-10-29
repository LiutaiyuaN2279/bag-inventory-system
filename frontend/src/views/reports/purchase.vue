<template>
  <div class="page">
    <!-- 页头：标题 + 说明 + 刷新 -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Histogram /></el-icon>采购报表</h2>
        <div class="ph-desc">
          按供应商与物料统计采购金额、入库数量，图表与明细同源联动 ·
          共 <b>{{ bySupplier.length }}</b> 家供应商 / <b>{{ byMaterial.length }}</b> 种物料
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <!-- 筛选卡：与库存报表保持同一套结构 -->
    <el-card shadow="never" class="filter-card">
      <div class="toolbar">
        <el-form :inline="true" :model="range" class="tb-left">
          <el-form-item label="起止日期">
            <el-date-picker v-model="range.value" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始" end-placeholder="结束" style="width:260px" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :icon="Search" @click="onSearch">查询</el-button>
            <el-button :icon="Refresh" @click="onReset">重置</el-button>
          </el-form-item>
        </el-form>
        <div class="tb-right"><span class="tb-hint">日期留空表示统计全部时间</span></div>
      </div>
    </el-card>

    <!-- KPI 统计条：铺满整行，与筛选行同一视觉层级 -->
    <div class="stat-strip">
      <div class="stat-item">
        <div class="si-icon si-blue"><el-icon><OfficeBuilding /></el-icon></div>
        <div>
          <div class="si-num">{{ bySupplier.length }}</div>
          <div class="si-label">供应商数</div>
        </div>
      </div>
      <div class="stat-item">
        <div class="si-icon si-teal"><el-icon><Tickets /></el-icon></div>
        <div>
          <div class="si-num">{{ totalOrders }}</div>
          <div class="si-label">订单总数</div>
        </div>
      </div>
      <div class="stat-item">
        <div class="si-icon si-amber"><el-icon><Money /></el-icon></div>
        <div>
          <div class="si-num">¥ {{ fmt(totalAmount) }}</div>
          <div class="si-label">采购总额（元）</div>
        </div>
      </div>
    </div>

    <!-- 图表区：与下方明细表格同源（同一份查询结果），随筛选条件联动 -->
    <div class="grid-2">
      <el-card shadow="never" class="chart-card">
        <template #header>采购金额按供应商分布</template>
        <div ref="supPieRef" class="chart-box" />
      </el-card>
      <el-card shadow="never" class="chart-card">
        <template #header>
          <span>采购入库数量 Top10（按物料）</span>
          <span class="chart-tip">接口按入库数量汇总，无金额字段</span>
        </template>
        <div ref="matBarRef" class="chart-box" />
      </el-card>
    </div>

    <!-- 明细表：卡片撑满剩余高度，表格内部滚动，底部信息条常驻 -->
    <el-card shadow="never" class="card-fill">
      <el-tabs v-model="tab">
        <el-tab-pane label="按供应商汇总" name="supplier">
          <!-- 批量操作条：只读统计页只提供「导出选中」，勾选后才出现、不占固定高度 -->
          <BatchBar :batch="supBatch" :actions="batchActions" @action="onSupBatchAction" />
          <div class="table-wrap">
            <el-table :ref="supBatch.bindTable" :data="bySupplier" :row-key="(row) => row.supplier_id" border stripe
              @selection-change="supBatch.onSelectionChange">
              <el-table-column type="selection" width="50" align="center" reserve-selection />
              <el-table-column type="index" label="#" width="55" align="center" />
              <el-table-column prop="supplier_code" label="供应商编码" width="130" show-overflow-tooltip />
              <el-table-column prop="supplier_name" label="供应商" min-width="180" sortable show-overflow-tooltip />
              <el-table-column prop="contact" label="联系人" width="110" show-overflow-tooltip />
              <el-table-column prop="phone" label="电话" width="130" show-overflow-tooltip />
              <el-table-column prop="orders" label="订单数" width="100" sortable align="right" class-name="col-num" />
              <el-table-column prop="amount" label="采购金额(元)" width="150" sortable align="right" class-name="col-num">
                <template #default="{ row }">¥ {{ fmt(row.amount) }}</template>
              </el-table-column>
              <el-table-column prop="avg_amount" label="平均金额(元)" width="140" align="right" class-name="col-num">
                <template #default="{ row }">¥ {{ fmt(row.avg_amount) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="90" fixed="right" align="center">
                <template #default="{ row }">
                  <el-button link type="primary" @click="showSupplierDetail(row)">详情</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div class="pager">
            <span class="hint">共 <b>{{ bySupplier.length }}</b> 家供应商 · 接口返回全量数据，表格内可滚动</span>
          </div>
        </el-tab-pane>
        <el-tab-pane label="按物料入库" name="material">
          <!-- 与「按供应商汇总」各自独立勾选：两张表行主键不同，共用一个 batch 会串行 -->
          <BatchBar :batch="matBatch" :actions="batchActions" @action="onMatBatchAction" />
          <div class="table-wrap">
            <el-table :ref="matBatch.bindTable" :data="byMaterial" :row-key="(row) => row.material_id" border stripe
              @selection-change="matBatch.onSelectionChange">
              <el-table-column type="selection" width="50" align="center" reserve-selection />
              <el-table-column type="index" label="#" width="55" align="center" />
              <el-table-column prop="material_code" label="物料编码" width="130" show-overflow-tooltip />
              <el-table-column prop="material_name" label="物料" min-width="170" sortable show-overflow-tooltip />
              <el-table-column prop="spec" label="规格" min-width="120" show-overflow-tooltip />
              <el-table-column prop="category" label="分类" width="90" align="center" />
              <el-table-column prop="unit" label="单位" width="70" align="center" />
              <el-table-column prop="txns" label="入库次数" width="100" align="right" class-name="col-num" />
              <el-table-column prop="qty" label="采购入库数量" width="150" sortable align="right" class-name="col-num">
                <template #default="{ row }">{{ row.qty }} {{ row.unit }}</template>
              </el-table-column>
              <el-table-column label="操作" width="90" fixed="right" align="center">
                <template #default="{ row }">
                  <el-button link type="primary" @click="showMaterialDetail(row)">详情</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div class="pager">
            <span class="hint">共 <b>{{ byMaterial.length }}</b> 种物料 · 接口返回全量数据，表格内可滚动</span>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 供应商订单明细 -->
    <DetailDialog v-model="supDialog.visible" :title="`采购订单明细 — ${supDialog.name}`" :width="1040">
      <el-table :data="supDialog.rows" border stripe>
        <el-table-column type="index" label="#" width="55" align="center" />
        <el-table-column prop="order_no" label="订单号" width="190" show-overflow-tooltip />
        <el-table-column prop="created_at" label="下单日期" width="120" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="100" align="center" />
        <el-table-column prop="item_qty" label="订购数量" width="110" align="right" class-name="col-num" />
        <el-table-column prop="arrived_qty" label="已到货" width="110" align="right" class-name="col-num" />
        <el-table-column prop="total_amount" label="金额(元)" width="130" align="right" class-name="col-num">
          <template #default="{ row }">¥ {{ fmt(row.total_amount) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="showOrderDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </DetailDialog>

    <!-- 采购订单物料明细 -->
    <DetailDialog v-model="orderDlg.visible" :title="`订单物料明细 — ${orderDlg.orderNo}`" :width="1080">
      <el-descriptions v-if="orderDlg.order" :column="3" border size="small" style="margin-bottom:14px">
        <el-descriptions-item label="订单号">{{ orderDlg.order.order_no }}</el-descriptions-item>
        <el-descriptions-item label="供应商">{{ orderDlg.order.supplier_name }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ orderDlg.order.status }}</el-descriptions-item>
        <el-descriptions-item label="下单日期">{{ orderDlg.order.created_at }}</el-descriptions-item>
        <el-descriptions-item label="订单金额" :span="2">¥ {{ fmt(orderDlg.order.total_amount) }}</el-descriptions-item>
      </el-descriptions>
      <el-table :data="orderDlg.items" border stripe>
        <el-table-column type="index" label="#" width="55" align="center" />
        <el-table-column prop="material_code" label="物料编码" width="120" show-overflow-tooltip />
        <el-table-column prop="material_name" label="物料" min-width="150" show-overflow-tooltip />
        <el-table-column prop="spec" label="规格" min-width="110" show-overflow-tooltip />
        <el-table-column prop="unit" label="单位" width="70" align="center" />
        <el-table-column prop="qty" label="订购数量" width="100" align="right" class-name="col-num" />
        <el-table-column prop="arrived_qty" label="已到货" width="90" align="right" class-name="col-num" />
        <el-table-column prop="inbound_qty" label="已入库" width="90" align="right" class-name="col-num" />
        <el-table-column prop="unit_price" label="单价" width="100" align="right" class-name="col-num">
          <template #default="{ row }">¥ {{ fmt(row.unit_price) }}</template>
        </el-table-column>
        <el-table-column prop="subtotal" label="小计" width="120" align="right" class-name="col-num">
          <template #default="{ row }">¥ {{ fmt(row.subtotal) }}</template>
        </el-table-column>
      </el-table>
    </DetailDialog>

    <!-- 物料入库明细 -->
    <DetailDialog v-model="matDialog.visible" :title="`采购入库明细 — ${matDialog.name}`" :width="920">
      <el-table :data="matDialog.rows" border stripe>
        <el-table-column type="index" label="#" width="55" align="center" />
        <el-table-column prop="txn_no" label="流水号" width="190" show-overflow-tooltip />
        <el-table-column prop="txn_time" label="入库时间" width="160" show-overflow-tooltip />
        <el-table-column prop="warehouse" label="仓库" min-width="120" show-overflow-tooltip />
        <el-table-column prop="in_qty" label="入库数量" width="120" align="right" class-name="col-num" />
        <el-table-column prop="operator" label="操作人" width="110" show-overflow-tooltip />
      </el-table>
    </DetailDialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Search, Refresh, Histogram, OfficeBuilding, Tickets, Money } from '@element-plus/icons-vue'
import { reportApi } from '@/api/report'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import DetailDialog from '@/components/DetailDialog.vue'
import BatchBar from '@/components/BatchBar.vue'
import {
  AXIS_LABEL, CHART_COLORS, CHART_TOOLTIP, ellipsis, emptyOption, hBarGradient, numText, useChart,
} from '@/composables/useChart'

const tab = ref('supplier')
const range = reactive({ value: [] })
const bySupplier = ref([])
const byMaterial = ref([])
const supDialog = reactive({ visible: false, name: '', rows: [] })
const matDialog = reactive({ visible: false, name: '', rows: [] })
const orderDlg = reactive({ visible: false, orderNo: '', order: null, items: [] })

const totalOrders = computed(() => bySupplier.value.reduce((s, r) => s + (r.orders || 0), 0))
const totalAmount = computed(() => bySupplier.value.reduce((s, r) => s + (r.amount || 0), 0))
const fmt = (v) => Number(v || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
/* 环图中心金额：金额较大时用「万 / 亿」缩写，保证文案完整落在色环内孔里 */
const moneyShort = (v) => {
  const n = Number(v || 0)
  const abs = Math.abs(n)
  if (abs >= 1e8) return `¥ ${(n / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `¥ ${(n / 1e4).toFixed(1)}万`
  return `¥ ${numText(Math.round(n * 100) / 100)}`
}

/* ---------------- 图表：采购金额按供应商分布（环形图，Top8 + 其他） ----------------
 * 取数字段：/reports/purchase-by-supplier → supplier_name、amount
 */
const supPieRef = ref(null)
function supPieOption() {
  const list = (bySupplier.value || []).filter(r => Number(r.amount || 0) > 0)
  if (!list.length) return emptyOption('暂无采购金额数据')
  const sorted = [...list].sort((a, b) => Number(b.amount || 0) - Number(a.amount || 0))
  const TOP = 8
  const data = sorted.slice(0, TOP).map(r => ({
    name: r.supplier_name || r.supplier_code || '未知供应商',
    value: Number(r.amount || 0),
  }))
  const rest = sorted.slice(TOP)
  if (rest.length) {
    data.push({
      name: `其他（${rest.length} 家）`,
      value: rest.reduce((s, r) => s + Number(r.amount || 0), 0),
    })
  }
  const total = data.reduce((s, d) => s + d.value, 0)
  return {
    color: CHART_COLORS,
    title: {
      text: moneyShort(total),
      subtext: '采购总额',
      left: '37%',
      top: '43%',
      textAlign: 'center',
      textStyle: { color: '#1f2937', fontSize: 15, fontWeight: 700 },
      subtextStyle: { color: '#94a3b8', fontSize: 12 },
    },
    tooltip: {
      ...CHART_TOOLTIP,
      trigger: 'item',
      formatter: (p) => `${p.marker}${p.name}<br/>采购金额：<b>¥ ${fmt(p.value)}</b>（${p.percent}%）`,
    },
    // 图例竖排在右侧：名称完整显示（不做省略），9 项在 260px 高度内一次可见、不翻页
    legend: {
      type: 'scroll', orient: 'vertical', right: 2, top: 'middle',
      icon: 'circle', itemWidth: 8, itemHeight: 8, itemGap: 9,
      textStyle: { color: '#64748b', fontSize: 12 },
    },
    series: [{
      name: '采购金额',
      type: 'pie',
      radius: ['42%', '62%'],
      center: ['37%', '50%'],
      avoidLabelOverlap: true,
      itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 4 },
      label: { show: false },
      labelLine: { show: false },
      emphasis: { scale: true, scaleSize: 6 },
      data,
    }],
  }
}
useChart(supPieRef, supPieOption, { watchSources: () => [bySupplier.value] })

/* ---------------- 图表：采购入库数量 Top10（横向条形图） ----------------
 * 取数字段：/reports/purchase-by-material → material_name、qty、unit、txns
 * 注意：该接口只提供「采购入库数量」，没有金额字段，故此处展示数量。
 */
const matBarRef = ref(null)
function matBarOption() {
  const list = (byMaterial.value || []).filter(r => Number(r.qty || 0) > 0)
  if (!list.length) return emptyOption('暂无采购入库数据')
  // 横向条形图自下而上绘制：升序排列后最大值落在顶部
  const rows = [...list].sort((a, b) => Number(a.qty || 0) - Number(b.qty || 0)).slice(-10)
  return {
    tooltip: {
      ...CHART_TOOLTIP,
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const p = Array.isArray(params) ? params[0] : params
        const row = rows[p.dataIndex] || {}
        return `${p.marker}${row.material_name || '-'}<br/>采购入库数量：<b>${numText(row.qty)}</b> ${row.unit || ''}`
          + `<br/>入库次数：${row.txns || 0} 次`
      },
    },
    grid: { left: 8, right: 64, top: 12, bottom: 4, containLabel: true },
    xAxis: { type: 'value', show: false, splitLine: { show: false } },
    yAxis: {
      type: 'category',
      data: rows.map(r => ellipsis(r.material_name, 10)),
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: AXIS_LABEL,
    },
    series: [{
      name: '采购入库数量',
      type: 'bar',
      barWidth: 13,
      itemStyle: { borderRadius: [0, 7, 7, 0], color: hBarGradient('#80C1FF') },
      label: {
        show: true, position: 'right', color: '#64748b', fontSize: 11,
        formatter: (p) => numText(p.value),
      },
      data: rows.map(r => Number(r.qty || 0)),
    }],
  }
}
useChart(matBarRef, matBarOption, { watchSources: () => [byMaterial.value] })

/* ---------------- 批量导出（只读统计页：无批量写动作） ----------------
 * 两张汇总表行主键不同（supplier_id / material_id），各自独立勾选，互不干扰。
 */
const batchActions = [{ key: 'export', label: '导出选中', perm: 'report:view' }]
const supBatch = useBatch({})
const matBatch = useBatch({})
// 导出用列定义与表格列保持一致，避免导出后对不上
const supExportColumns = [
  { prop: 'supplier_code', label: '供应商编码' },
  { prop: 'supplier_name', label: '供应商' },
  { prop: 'contact', label: '联系人' },
  { prop: 'phone', label: '电话' },
  { prop: 'orders', label: '订单数' },
  { prop: 'amount', label: '采购金额(元)', formatter: (r) => fmt(r.amount) },
  { prop: 'avg_amount', label: '平均金额(元)', formatter: (r) => fmt(r.avg_amount) }
]
const matExportColumns = [
  { prop: 'material_code', label: '物料编码' },
  { prop: 'material_name', label: '物料' },
  { prop: 'spec', label: '规格' },
  { prop: 'category', label: '分类' },
  { prop: 'unit', label: '单位' },
  { prop: 'txns', label: '入库次数' },
  { prop: 'qty', label: '采购入库数量' }
]
function onSupBatchAction(key) {
  if (key === 'export') exportRows(supBatch.selected.value, supExportColumns, '采购报表_按供应商汇总')
}
function onMatBatchAction(key) {
  if (key === 'export') exportRows(matBatch.selected.value, matExportColumns, '采购报表_按物料入库')
}

function rangeParams() {
  const p = {}
  if (range.value && range.value.length === 2) { p.start = range.value[0]; p.end = range.value[1] }
  return p
}
async function load() {
  // 重新取数会整体换掉表格行（含页头「刷新」按钮直调 load），先清空勾选
  supBatch.clearSelection()
  matBatch.clearSelection()
  const params = rangeParams()
  try {
    const [s, m] = await Promise.all([reportApi.purchaseBySupplier(params), reportApi.purchaseByMaterial(params)])
    bySupplier.value = s || []
    byMaterial.value = m || []
  } catch (e) {
    // 接口失败时清空数据，图表显示「暂无数据」，表格为空而非报错
    bySupplier.value = []
    byMaterial.value = []
    console.warn('purchase report load failed', e)
  }
}
function onSearch() { supBatch.clearSelection(); matBatch.clearSelection(); load() }
function onReset() { range.value = []; onSearch() }
async function showSupplierDetail(row) {
  supDialog.name = row.supplier_name
  supDialog.rows = []
  supDialog.visible = true
  supDialog.rows = await reportApi.purchaseSupplierDetail({ supplier_id: row.supplier_id, ...rangeParams() })
}
async function showOrderDetail(row) {
  orderDlg.orderNo = row.order_no
  orderDlg.order = null
  orderDlg.items = []
  orderDlg.visible = true
  const res = await reportApi.purchaseOrderDetail({ order_no: row.order_no })
  orderDlg.order = res.order
  orderDlg.items = res.items || []
}
async function showMaterialDetail(row) {
  matDialog.name = row.material_name
  matDialog.rows = []
  matDialog.visible = true
  matDialog.rows = await reportApi.purchaseMaterialDetail({ material_id: row.material_id, ...rangeParams() })
}
onMounted(load)
</script>
<style scoped>
/* 筛选卡：更紧凑的内边距；不参与压缩，保证日期范围与按钮完整可见 */
.filter-card { flex: 0 0 auto; }
.filter-card :deep(.el-card__body) { padding: 12px 16px; }
.tb-hint { font-size: 12px; color: var(--text-3); }
/* KPI 图标配色 */
.si-icon.si-blue { background: #eaf2ff; color: #2f6fed; }
.si-icon.si-teal { background: #e6faf7; color: #14b8a6; }
.si-icon.si-amber { background: #fff5e6; color: #d97706; }
/* 图表卡片：与库存报表统一高度，压缩首屏占用 */
.chart-card :deep(.el-card__body) { padding: 8px 12px 10px; }
.chart-tip { font-size: 12px; font-weight: 400; color: #9ca3af; margin-left: 6px; }
.chart-box { width: 100%; height: 260px; }
/* 明细表：tabs 撑满卡片，表格内部滚动，底部信息条常驻 */
.card-fill :deep(.el-tabs) { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
.card-fill :deep(.el-tabs__content) { flex: 1 1 auto; min-height: 0; }
.card-fill :deep(.el-tab-pane) { height: 100%; display: flex; flex-direction: column; gap: 8px; }
</style>
