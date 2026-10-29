<template>
  <!--
    首页按「是否业务岗位」分发：
    - 业务岗（采购/仓储/质检/管理）→ 采购库存看板
    - 只有报销权限的财务与审批岗 → 报销工作台
    这样所有角色登录后都有可用的首页，而不是被路由守卫直接丢到列表页。
    ⚠️ 判据不能用 report:view（采购报表权限）：buyer/keeper/qc 都没有报表权限，
       却必须看到各自的采购库存看板；用报表权限判定会把它们误判成报销角色。
  -->
  <ReimburseWorkbench v-if="!isBusinessView" />
  <div v-else v-loading="loading" class="dashboard" element-loading-text="看板加载中…">
    <!-- ================= 第 1 行：问候横幅（内容高度） ================= -->
    <div class="greet">
      <div class="greet-main">
        <div class="greet-hello">你好，{{ realName }} 👋</div>
        <div class="greet-sub">
          <span v-if="roleLabel" class="greet-role">{{ roleLabel }}</span>
          <span class="greet-hint" :style="{ color: hint.color }">{{ hint.text }}</span>
        </div>
      </div>
      <div class="greet-side">
        <div class="greet-chips">
          <span v-if="loadError" class="gchip gchip-err" @click="loadWorkbench">数据加载失败，点击重试</span>
          <span class="greet-date">{{ today }}</span>
        </div>
        <div v-if="bannerTodos.length" class="greet-todos">
          <span v-for="t in bannerTodos" :key="t.title" class="g-todo" @click="goTodo(t)">
            {{ t.title }} <b>{{ t.count }}</b> ›
          </span>
        </div>
      </div>
    </div>

    <!-- ================= 第 2 行：KPI 卡条（内容高度，一行铺满） ================= -->
    <div v-if="kpis.length" class="kpi-row">
      <div v-for="c in kpis" :key="c.label" class="kpi-card">
        <div class="kpi-icon" :style="{ background: softBg(c.color), color: c.color || 'var(--brand)' }">
          <el-icon :size="20"><component :is="c.icon || 'DataLine'" /></el-icon>
        </div>
        <div class="kpi-text">
          <div class="kpi-num">{{ c.value }}</div>
          <div class="kpi-label" :title="c.label">{{ c.label }}</div>
        </div>
      </div>
    </div>
    <div v-else class="kpi-empty">
      <el-icon><DataLine /></el-icon><span>暂无指标数据</span>
    </div>

    <!-- ================= 第 3 行：快速入口（内容高度，一行胶囊） ================= -->
    <div class="panel panel-auto">
      <div class="panel-title">
        快速入口
        <span class="panel-tip">只展示你有权限的功能</span>
        <span class="panel-count">{{ quickEntries.length }} 个入口</span>
      </div>
      <div v-if="quickEntries.length" class="quick-wrap">
        <div
          v-for="q in quickEntries" :key="q.path" class="quick-item"
          :style="{ '--c': q.color }" @click="go(q.path)"
        >
          <el-icon :size="16"><component :is="q.icon" /></el-icon>
          <span>{{ q.name }}</span>
        </div>
      </div>
      <div v-else class="empty-box empty-inline">
        <el-icon><Lock /></el-icon><span>暂无可访问的功能入口</span>
      </div>
    </div>

    <!-- ================= 第 4 行：我的待办（内容高度，横排卡片） ================= -->
    <div class="panel panel-auto">
      <div class="panel-title">
        我的待办
        <span class="panel-count">{{ wb.todos.length }} 类</span>
      </div>
      <div v-if="wb.todos.length" class="todo-grid">
        <div v-for="t in wb.todos" :key="t.title" class="todo-card" @click="goTodo(t)">
          <div class="todo-head">
            <span class="todo-title" :title="t.title">{{ t.title }}</span>
            <span class="todo-num" :class="{ hot: Number(t.count) > 0 }">{{ t.count }}</span>
          </div>
          <div class="todo-foot">
            <span class="todo-action">{{ t.action || '去处理' }} ›</span>
            <span v-if="t.status" class="todo-status">{{ t.status }}</span>
          </div>
        </div>
      </div>
      <div v-else class="empty-box empty-inline">
        <el-icon><CircleCheck /></el-icon><span>暂无待办，一切正常</span>
      </div>
    </div>

    <!-- ================= 第 5 行：主区（吸收剩余高度） ================= -->
    <div class="main-row">
      <!-- 左：角色主图表 -->
      <div class="panel panel-chart">
        <div class="panel-title">
          {{ mainMeta.title }}
          <span class="panel-tip">{{ mainMeta.tip }}</span>
          <span class="panel-count">{{ mainCount }}</span>
        </div>
        <div class="panel-body">
          <div ref="mainRef" class="chart-box" />
        </div>
      </div>

      <!-- 右：角色单据清单 -->
      <div class="panel panel-docs">
        <div class="panel-title">
          与我相关的单据
          <span class="panel-tip">按角色推送，点击直达</span>
          <span class="panel-count">{{ docList.length }} 条</span>
        </div>
        <div v-if="docList.length" class="doc-list">
          <div v-for="(d, i) in docList" :key="d.no || d.title || i" class="doc-item" @click="goDoc(d)">
            <div class="doc-main">
              <div class="doc-line">
                <span class="doc-kind">{{ d.kind || '单据' }}</span>
                <span v-if="d.no" class="doc-no">{{ d.no }}</span>
                <span class="doc-title" :title="d.title">{{ d.title || '-' }}</span>
              </div>
              <div v-if="d.sub" class="doc-sub" :title="d.sub">{{ d.sub }}</div>
            </div>
            <div class="doc-right">
              <span v-if="d.value" class="doc-value">{{ d.value }}</span>
              <el-tag v-if="d.status" size="small" effect="light" :type="statusType(d.status)">{{ d.status }}</el-tag>
            </div>
          </div>
        </div>
        <div v-else class="empty-box">
          <el-icon><Tickets /></el-icon><span>暂无相关单据</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/store/user'
import { reportApi } from '@/api/report'
import ReimburseWorkbench from '@/views/reimburse/workbench.vue'
import {
  AXIS_LABEL, AXIS_LINE, CHART_TOOLTIP, COLOR_IN, COLOR_OUT, DEFAULT_GRID, SPLIT_LINE,
  areaGradient, axisTooltipFormatter, ellipsis, emptyOption, hBarGradient, numText, useChart,
} from '@/composables/useChart'

const router = useRouter()
const store = useUserStore()
const go = (path) => { if (path) router.push(path) }

// 是否业务岗位：决定首页显示「采购库存看板」还是「报销工作台」
// 判据是「有任何一项业务权限」，而不是单看 report:view —— 采购员/仓管员/质检员
// 都没有采购报表权限，但他们的日常就是采购与库存业务，必须看到业务看板。
// 报销专用角色（财务制单/复核/审批/部门负责人/普通员工）一项业务权限都没有，
// 才走报销工作台。
const BUSINESS_PERMS = [
  'report:view',
  'purchase:requisition:list', 'purchase:order:list',
  'purchase:arrival:list', 'purchase:return:list',
  'inventory:view', 'inventory:alert', 'inventory:stocktake',
  'qc:view', 'bom:view', 'outsource:list',
  'basic:material:list', 'basic:supplier:list', 'basic:warehouse:list',
]
const isBusinessView = computed(() => {
  const roles = store.roles || []
  if (roles.includes('admin') || roles.includes('manager')) return true
  return BUSINESS_PERMS.some((p) => store.hasPermission(p))
})
// 点击待办：带状态筛选跳转，目标页据此自动筛选（如未审核=草稿）
const goTodo = (t) => {
  if (!t || !t.to) return
  router.push(t.status ? { path: t.to, query: { status: t.status } } : t.to)
}
// 点击单据：优先用后端给的 status_query（老字段 status 兜底）
const goDoc = (d) => {
  if (!d || !d.to) return
  const st = d.status_query ?? d.status
  router.push(st ? { path: d.to, query: { status: st } } : d.to)
}

const today = new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' })

/* ------------------------------ 权限与角色 ------------------------------ */
const primaryRole = computed(() => {
  const roles = store.roles || []
  return roles.includes('admin') ? 'admin' : (roles[0] || 'admin')
})

// 快速入口主清单：按权限自动过滤（admin 全显示）
const ALL_QUICK = [
  { name: '新增请购', path: '/procurement/requisition', icon: 'Document', color: '#27D2BF', perm: 'purchase:requisition:add' },
  { name: '采购订单', path: '/procurement/order', icon: 'Tickets', color: '#0ea5e9', perm: 'purchase:order:list' },
  { name: '到货验收', path: '/procurement/arrival', icon: 'Box', color: '#67c23a', perm: 'purchase:arrival:list' },
  { name: '采购退货', path: '/procurement/return', icon: 'RefreshLeft', color: '#f56c6c', perm: 'purchase:return:list' },
  { name: '库存查询', path: '/inventory/query', icon: 'Search', color: '#80C1FF', perm: 'inventory:view' },
  { name: '库存盘点', path: '/inventory/stocktake', icon: 'EditPen', color: '#a78bfa', perm: 'inventory:stocktake' },
  { name: '预警看板', path: '/inventory/alert', icon: 'Bell', color: '#f56c6c', perm: 'inventory:alert' },
  { name: '外发加工', path: '/production/outsource', icon: 'Van', color: '#0ea5e9', perm: 'outsource:list' },
  { name: '来料质检', path: '/quality/iqc', icon: 'DocumentChecked', color: '#14b8a6', perm: 'qc:view' },
  { name: '成品质检', path: '/quality/fqc', icon: 'Medal', color: '#10b981', perm: 'qc:view' },
  { name: '物料管理', path: '/basic-data/materials', icon: 'Goods', color: '#10b981', perm: 'basic:material:list' },
  { name: '供应商', path: '/basic-data/suppliers', icon: 'OfficeBuilding', color: '#27D2BF', perm: 'basic:supplier:list' },
  { name: '仓库管理', path: '/basic-data/warehouses', icon: 'House', color: '#80C1FF', perm: 'basic:warehouse:list' },
  { name: 'BOM 清单', path: '/bom/list', icon: 'Files', color: '#8b5cf6', perm: 'bom:view' },
  { name: '采购报表', path: '/reports/purchase', icon: 'Money', color: '#8b5cf6', perm: 'report:view' },
  { name: '操作日志', path: '/system/logs', icon: 'List', color: '#909399', perm: 'system:log' },
]
const quickEntries = computed(() => ALL_QUICK.filter(q => store.hasPermission(q.perm)))

// 各角色一句话提示（工作重心随身份变化）
const HINT = {
  admin: { text: '欢迎回来，系统全局运行状况如下', color: '#10b981' },
  manager: { text: '以下是待您审核与跟进的单据，请及时处理', color: '#e6a23c' },
  buyer: { text: '从这里开始您的采购制单与跟单工作', color: '#0ea5e9' },
  keeper: { text: '收发货物、盘点与预警处理，一站直达', color: '#67c23a' },
  qc: { text: '待检批次如下，请优先完成质检录入', color: '#14b8a6' },
}

/* ------------------------------ 看板数据 ------------------------------ */
const loading = ref(false)
const loadError = ref(false)

const wb = reactive({
  role: '', role_name: '', real_name: '',
  kpis: [], todos: [], overview: null,
  // 新契约字段（并行开发中，缺失时全部降级为空态）
  todo_total: null, alert_total: null,
  trend: [], stock_top: [], warehouse_stock: [], purchase_trend: [], qc_trend: [], task_docs: [],
})

const role = computed(() => wb.role || primaryRole.value)
const roleLabel = computed(() => wb.role_name || ({ admin: '系统管理员', manager: '运营主管', buyer: '采购员', keeper: '仓管员', qc: '质检员' }[role.value] || ''))
const realName = computed(() => wb.real_name || store.userInfo?.real_name || '同学')
const hint = computed(() => HINT[role.value] || HINT.admin)
const kpis = computed(() => (Array.isArray(wb.kpis) ? wb.kpis : []))

// 兼容旧接口：新平铺字段优先，其次退回 overview 内嵌字段
function listOf(key) {
  const flat = wb[key]
  if (Array.isArray(flat) && flat.length) return flat
  const nested = wb.overview ? wb.overview[key] : null
  if (Array.isArray(nested) && nested.length) return nested
  return Array.isArray(flat) ? flat : (Array.isArray(nested) ? nested : [])
}

const bannerTodos = computed(() => (wb.todos || []).filter(t => Number(t.count) > 0).slice(0, 3))

const softBg = (color) => (/^#[0-9a-fA-F]{6}$/.test(String(color || '')) ? `${color}1a` : 'rgba(16,185,129,.1)')

const STATUS_TAG = [
  [/驳回|作废|异常|不合格/, 'danger'],
  [/已完成|已入库|已验收|已审核|通过|已出库/, 'success'],
  [/待|草稿|在途|盘点中|部分/, 'warning'],
]
const statusType = (s) => (STATUS_TAG.find(([re]) => re.test(String(s))) || [])[1] || 'info'

// 单据清单：优先 task_docs；后端未上线新字段时用 todos 顶位（避免整块留白）
const docList = computed(() => {
  const docs = listOf('task_docs')
  if (docs.length) return docs.slice(0, 30)
  return (wb.todos || []).map(t => ({
    kind: '待办',
    no: '',
    title: t.title,
    sub: t.status ? `筛选状态：${t.status}` : '',
    value: `${t.count} 项`,
    status: t.status || '',
    to: t.to,
    status_query: t.status,
  }))
})

/* ------------------------------ 角色主图表 ------------------------------ */
// 角色首选图表 + 字段缺失时顺延：角色图 → trend → warehouse_stock → stock_top → 空态
const mainMode = computed(() => {
  const has = (k) => listOf(k).length > 0
  const prefer = { admin: 'trend', manager: 'trend', buyer: 'purchase', keeper: 'warehouse', qc: 'qc' }[role.value] || 'trend'
  if (prefer === 'purchase' && has('purchase_trend')) return 'purchase'
  if (prefer === 'warehouse' && has('warehouse_stock')) return 'warehouse'
  if (prefer === 'qc' && has('qc_trend')) return 'qc'
  if (prefer === 'trend' && has('trend')) return 'trend'
  if (has('trend')) return 'trend'
  if (has('warehouse_stock')) return 'warehouse'
  if (has('stock_top')) return 'stockTop'
  return 'empty'
})

const MAIN_META = {
  trend: { title: '近 7 天出入库趋势', tip: '单位：主计量单位' },
  purchase: { title: '近 7 天采购到货', tip: '数量（左轴）/ 金额（右轴）' },
  warehouse: { title: '各仓库存分布', tip: '单位：主计量单位' },
  stockTop: { title: '库存 Top 物料', tip: '单位：主计量单位' },
  qc: { title: '近 7 天质检趋势', tip: '批次（左轴）/ 一次合格率（右轴）' },
  empty: { title: '数据概览', tip: '暂无可用数据' },
}
const mainMeta = computed(() => MAIN_META[mainMode.value] || MAIN_META.empty)
const mainRows = computed(() => {
  const map = { trend: 'trend', purchase: 'purchase_trend', warehouse: 'warehouse_stock', stockTop: 'stock_top', qc: 'qc_trend' }
  const key = map[mainMode.value]
  return key ? listOf(key) : []
})
const mainCount = computed(() => (mainRows.value.length ? `${mainRows.value.length} 项` : ''))

const dateLabel = (d) => String(d || '').slice(5)
const moneyText = (v) => {
  const n = Number(v || 0)
  const abs = Math.abs(n)
  if (abs >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${(n / 1e4).toFixed(2)}万`
  return numText(n)
}
const tooltipHead = (arr) => `<div style="font-weight:600;margin-bottom:4px">${arr[0].axisValueLabel ?? arr[0].name ?? ''}</div>`

const LEGEND = {
  top: 2, right: 4, icon: 'roundRect', itemWidth: 10, itemHeight: 10, itemGap: 18,
  textStyle: { color: '#64748b', fontSize: 12 },
}
const CAT_AXIS = { axisTick: { show: false }, axisLine: AXIS_LINE, axisLabel: AXIS_LABEL }
const VAL_AXIS = { type: 'value', axisLine: { show: false }, axisTick: { show: false }, splitLine: SPLIT_LINE, axisLabel: AXIS_LABEL }

/** 近 7 天出入库双折线（admin / manager） */
function trendOption() {
  const list = listOf('trend')
  if (!list.length) return emptyOption('暂无数据')
  return {
    color: [COLOR_IN, COLOR_OUT],
    tooltip: { ...CHART_TOOLTIP, trigger: 'axis', formatter: axisTooltipFormatter() },
    legend: LEGEND,
    grid: { ...DEFAULT_GRID, top: 38, bottom: 2 },
    xAxis: { type: 'category', boundaryGap: false, data: list.map(d => dateLabel(d.date)), ...CAT_AXIS },
    yAxis: { ...VAL_AXIS },
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

/** 近 7 天采购到货：数量柱（左轴）+ 金额折线（右轴，万/亿缩写）（buyer） */
function purchaseOption() {
  const list = listOf('purchase_trend')
  if (!list.length) return emptyOption('暂无数据')
  return {
    color: [COLOR_IN, '#e6a23c'],
    tooltip: {
      ...CHART_TOOLTIP,
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const arr = Array.isArray(params) ? params : [params]
        if (!arr.length) return ''
        const rows = arr.map(p => '<div style="display:flex;align-items:center;justify-content:space-between;gap:18px;line-height:20px">'
          + `<span>${p.marker}${p.seriesName}</span><b>${String(p.seriesName || '').includes('金额') ? `¥${moneyText(p.value)}` : `${numText(p.value)} 个`}</b></div>`).join('')
        return tooltipHead(arr) + rows
      },
    },
    legend: LEGEND,
    grid: { ...DEFAULT_GRID, top: 38, right: 54, bottom: 2 },
    xAxis: { type: 'category', data: list.map(d => dateLabel(d.date)), ...CAT_AXIS },
    yAxis: [
      { ...VAL_AXIS, name: '数量', nameTextStyle: { color: '#94a3b8', fontSize: 11 } },
      { ...VAL_AXIS, name: '金额', nameTextStyle: { color: '#94a3b8', fontSize: 11 }, splitLine: { show: false }, axisLabel: { ...AXIS_LABEL, formatter: (v) => moneyText(v) } },
    ],
    series: [
      {
        name: '到货数量', type: 'bar', barWidth: 18,
        itemStyle: { borderRadius: [6, 6, 0, 0], color: areaGradient(COLOR_IN) },
        data: list.map(d => Number(d.qty || 0)),
      },
      {
        name: '采购金额', type: 'line', yAxisIndex: 1, smooth: true, symbol: 'circle', symbolSize: 7,
        lineStyle: { width: 2.5, color: '#e6a23c' }, itemStyle: { color: '#e6a23c' },
        areaStyle: { color: areaGradient('#e6a23c', 0.18, 0.01) },
        data: list.map(d => Number(d.amount || 0)),
      },
    ],
  }
}

/** 横向条形图（各仓库存 / 库存 Top 物料） */
function hBarOption(rows, nameKey) {
  const list = [...rows].reverse() // 横向条形自下而上绘制，反转后最大值落在顶部
  if (!list.length) return emptyOption('暂无数据')
  const nameOf = (r) => r[nameKey] || r.warehouse_name || r.type || r.material_name || '-'
  return {
    tooltip: {
      ...CHART_TOOLTIP,
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const p = Array.isArray(params) ? params[0] : params
        const row = list[p.dataIndex] || {}
        const kinds = row.kinds === undefined || row.kinds === null ? '' : `<br/>品类数：<b>${numText(row.kinds)}</b>`
        return `${p.marker}${nameOf(row)}<br/>库存量：<b>${numText(row.qty)}</b>${kinds}`
      },
    },
    grid: { left: 4, right: 64, top: 8, bottom: 2, containLabel: true },
    xAxis: { type: 'value', show: false, splitLine: { show: false } },
    yAxis: {
      type: 'category',
      data: list.map(d => ellipsis(nameOf(d), 10)),
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: { ...AXIS_LABEL, width: 104, overflow: 'truncate' },
    },
    series: [{
      name: '库存量', type: 'bar', barWidth: 13, barCategoryGap: '42%',
      itemStyle: { borderRadius: [0, 7, 7, 0], color: hBarGradient('#80C1FF') },
      label: { show: true, position: 'right', color: '#64748b', fontSize: 11, formatter: (p) => numText(p.value) },
      data: list.map(d => Number(d.qty || 0)),
    }],
  }
}

/** 质检趋势：IQC/FQC 分组柱 + 一次合格率折线（qc） */
function qcOption() {
  const list = listOf('qc_trend')
  if (!list.length) return emptyOption('暂无数据')
  return {
    color: [COLOR_IN, '#80C1FF', '#e6a23c'],
    tooltip: {
      ...CHART_TOOLTIP,
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const arr = Array.isArray(params) ? params : [params]
        if (!arr.length) return ''
        const rows = arr.map(p => {
          const isRate = String(p.seriesName || '').includes('合格率')
          const text = isRate
            ? (p.value === null || p.value === undefined ? '-' : `${Number(p.value).toFixed(1)}%`)
            : `${numText(p.value)} 批`
          return '<div style="display:flex;align-items:center;justify-content:space-between;gap:18px;line-height:20px">'
            + `<span>${p.marker}${p.seriesName}</span><b>${text}</b></div>`
        }).join('')
        return tooltipHead(arr) + rows
      },
    },
    legend: LEGEND,
    grid: { ...DEFAULT_GRID, top: 38, right: 52, bottom: 2 },
    xAxis: { type: 'category', data: list.map(d => dateLabel(d.date)), ...CAT_AXIS },
    yAxis: [
      { ...VAL_AXIS, name: '批次', minInterval: 1, nameTextStyle: { color: '#94a3b8', fontSize: 11 } },
      {
        ...VAL_AXIS, name: '合格率', min: 0, max: 100, nameTextStyle: { color: '#94a3b8', fontSize: 11 },
        splitLine: { show: false }, axisLabel: { ...AXIS_LABEL, formatter: '{value}%' },
      },
    ],
    series: [
      { name: 'IQC', type: 'bar', barWidth: 12, itemStyle: { borderRadius: [6, 6, 0, 0], color: COLOR_IN }, data: list.map(d => Number(d.iqc || 0)) },
      { name: 'FQC', type: 'bar', barWidth: 12, itemStyle: { borderRadius: [6, 6, 0, 0], color: '#80C1FF' }, data: list.map(d => Number(d.fqc || 0)) },
      {
        name: '一次合格率', type: 'line', yAxisIndex: 1, smooth: true, connectNulls: true,
        symbol: 'circle', symbolSize: 7, lineStyle: { width: 2.5, color: '#e6a23c' }, itemStyle: { color: '#e6a23c' },
        data: list.map(d => (d.pass_rate === null || d.pass_rate === undefined ? null : Number(d.pass_rate))),
      },
    ],
  }
}

function mainOption() {
  switch (mainMode.value) {
    case 'trend': return trendOption()
    case 'purchase': return purchaseOption()
    case 'warehouse': return hBarOption(listOf('warehouse_stock'), 'warehouse_name')
    case 'stockTop': return hBarOption(listOf('stock_top'), 'material_name')
    case 'qc': return qcOption()
    default: return emptyOption('暂无数据')
  }
}

const mainRef = ref(null)
useChart(mainRef, mainOption, {
  // 依赖：角色切换 + 任一可能作图的数据源变化
  watchSources: () => [
    mainMode.value, wb.trend, wb.purchase_trend, wb.warehouse_stock, wb.qc_trend, wb.stock_top, wb.overview,
  ],
})

/* ------------------------------ 数据加载 ------------------------------ */
async function loadWorkbench() {
  loading.value = true
  try {
    const res = (await reportApi.workbench()) || {}
    const arr = (v) => (Array.isArray(v) ? v : [])
    Object.assign(wb, {
      role: res.role || '',
      role_name: res.role_name || '',
      real_name: res.real_name || '',
      kpis: arr(res.kpis),
      todos: arr(res.todos),
      overview: res.overview || null,
      todo_total: typeof res.todo_total === 'number' ? res.todo_total : null,
      alert_total: typeof res.alert_total === 'number' ? res.alert_total : null,
      trend: arr(res.trend),
      stock_top: arr(res.stock_top),
      warehouse_stock: arr(res.warehouse_stock),
      purchase_trend: arr(res.purchase_trend),
      qc_trend: arr(res.qc_trend),
      task_docs: arr(res.task_docs),
    })
    loadError.value = false
  } catch (e) {
    // 权限或网络异常时静默降级为空态，避免看板整块报错/留白
    loadError.value = true
    console.warn('[dashboard] workbench 加载失败', e)
  } finally {
    loading.value = false
  }
}

// 只有采购库存看板才需要拉 workbench 数据；报销工作台由自身组件加载
onMounted(() => { if (isBusinessView.value) loadWorkbench() })

// 顶栏「切换演示身份」是在**同一个路由内**换 token 的：组件不会重新挂载，
// onMounted 不会再执行，于是 KPI / 待办 / 图表 / 单据清单会停留在上一个身份的数据上。
// 这里显式监听当前登录用户，身份一变就按新角色重新拉取看板。
watch(() => store.userInfo?.username, (now, before) => {
  if (now && now !== before && isBusinessView.value) loadWorkbench()
})
</script>

<style scoped>
/* ============================ 页面骨架 ============================ */
/* 只有最下面的主区吸收剩余高度，上面几行一律按内容自适应，避免小内容面板留白 */
.dashboard { height: 100%; min-height: 0; display: flex; flex-direction: column; gap: 12px; }

/* ============================ 问候横幅 ============================ */
.greet {
  flex: none; display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 12px 18px; border: 1px solid var(--border); border-radius: var(--radius);
  background: linear-gradient(120deg, #eef7ff 0%, #eefaf3 58%, #f8fffc 100%);
  box-shadow: var(--shadow-sm);
}
.greet-main { min-width: 0; }
.greet-hello { font-size: 18px; font-weight: 700; color: var(--text-1); }
.greet-sub { margin-top: 5px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12.5px; color: var(--text-2); }
.greet-role {
  padding: 1px 9px; border-radius: 20px; font-size: 12px; color: var(--brand-dark);
  background: rgba(255, 255, 255, .9); border: 1px solid #cdece0;
}
.greet-side { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; align-items: flex-end; gap: 7px; }
.greet-chips { display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }
.gchip {
  display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px; font-size: 12.5px; color: #475569;
  background: rgba(255, 255, 255, .85); border: 1px solid var(--border); border-radius: 20px;
}
.gchip b { font-size: 14px; color: var(--brand-dark); font-variant-numeric: tabular-nums; }
.gchip-warn b { color: #f56c6c; }
.gchip-err { cursor: pointer; color: #f56c6c; border-color: #fbc4c4; background: #fff5f5; }
.greet-date { font-size: 12.5px; color: #94a3b8; white-space: nowrap; }
.greet-todos { display: flex; align-items: center; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
.g-todo {
  display: inline-flex; align-items: center; gap: 5px; padding: 3px 10px; font-size: 12px; color: var(--text-2);
  background: rgba(255, 255, 255, .78); border: 1px solid var(--border); border-radius: 20px; cursor: pointer;
  transition: color .15s, border-color .15s, transform .15s, background .15s;
}
.g-todo:hover { color: var(--brand-dark); border-color: #a7e3cb; background: #fff; transform: translateY(-1px); }
.g-todo b { color: var(--brand-dark); font-variant-numeric: tabular-nums; }

/* ============================ KPI 卡条 ============================ */
.kpi-row { flex: none; display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.kpi-card {
  display: flex; align-items: center; gap: 10px; min-width: 0; padding: 10px 12px; background: #fff;
  border: 1px solid var(--border); border-radius: 10px; box-shadow: var(--shadow-sm);
  transition: box-shadow .2s, transform .2s, border-color .2s;
}
.kpi-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-md); border-color: #d7efe4; }
.kpi-icon { width: 38px; height: 38px; flex: 0 0 38px; border-radius: 10px; display: flex; align-items: center; justify-content: center; }
.kpi-text { min-width: 0; }
.kpi-num { font-size: 20px; font-weight: 700; color: var(--text-1); line-height: 1.15; font-variant-numeric: tabular-nums; }
.kpi-label { margin-top: 2px; font-size: 12px; color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kpi-empty {
  flex: none; display: flex; align-items: center; justify-content: center; gap: 8px; padding: 14px;
  font-size: 13px; color: var(--text-3); background: #fff; border: 1px dashed var(--border); border-radius: var(--radius);
}

/* ============================ 通用面板 ============================ */
.panel {
  min-width: 0; display: flex; flex-direction: column;
  background: #fff; border: 1px solid var(--border); border-radius: var(--radius);
  box-shadow: var(--shadow-sm); padding: 11px 14px;
}
/* 内容高度面板：不为填满而拉高 */
.panel-auto { flex: none; }
.panel-title {
  flex: none; display: flex; align-items: center; gap: 8px;
  margin: 0 0 10px; padding-bottom: 8px; font-size: 14px; font-weight: 600; color: var(--text-1);
  border-bottom: 1px solid var(--border);
}
.panel-title::before {
  content: ''; width: 3px; height: 13px; border-radius: 2px;
  background: linear-gradient(180deg, var(--brand), var(--accent));
}
.panel-tip { font-size: 12px; font-weight: 400; color: var(--text-3); }
.panel-count { margin-left: auto; font-size: 12px; font-weight: 400; color: #94a3b8; white-space: nowrap; }
/* 图表容器：.panel-body 自身作为 flex 容器，让 .chart-box 靠 stretch 拿到真实高度。
   不能只靠 height:100%（父级高度由 min-height / flex-grow 得到时属于「不确定高度」，
   百分比会退化成 auto → 高度 0 → ECharts 报 Can't get DOM width or height 且画布 0 高）。 */
.panel-body { flex: 1 1 auto; min-height: 0; display: flex; }
/* 不写 height:100%：父级高度来自 flex-grow / min-height 时百分比高度会被判为不确定
   （退化成 0），反而覆盖掉 align-self:stretch，导致 ECharts 画布 0 高。 */
.chart-box { flex: 1 1 auto; align-self: stretch; width: 100%; min-width: 0; height: auto; }

/* ============================ 快速入口（一行胶囊，自动换行） ============================ */
.quick-wrap { display: flex; flex-wrap: wrap; gap: 8px; }
.quick-item {
  display: inline-flex; align-items: center; gap: 7px; padding: 8px 14px; font-size: 13px; color: #4b5563;
  border-radius: 9px; cursor: pointer; white-space: nowrap;
  background: color-mix(in srgb, var(--c) 8%, #fff);
  border: 1px solid color-mix(in srgb, var(--c) 22%, #fff);
  transition: transform .15s, box-shadow .2s, border-color .2s, color .15s;
}
.quick-item:hover {
  transform: translateY(-2px); box-shadow: 0 6px 16px rgba(16, 24, 40, .1); color: var(--c);
  border-color: color-mix(in srgb, var(--c) 45%, #fff);
}
.quick-item .el-icon { color: var(--c); }

/* ============================ 我的待办（横排卡片，内容高度） ============================ */
.todo-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; }
.todo-card {
  display: flex; flex-direction: column; gap: 8px; min-width: 0; padding: 10px 13px; cursor: pointer;
  border: 1px solid var(--border); border-radius: 10px; background: #fcfdff;
  transition: background .15s, border-color .15s, transform .15s, box-shadow .2s;
}
.todo-card:hover { background: #f2fbf7; border-color: #a7e3cb; transform: translateY(-2px); box-shadow: 0 6px 16px rgba(16, 24, 40, .08); }
.todo-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.todo-title { font-size: 13px; color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.todo-num { flex: none; font-size: 22px; font-weight: 700; line-height: 1.1; color: #94a3b8; font-variant-numeric: tabular-nums; }
.todo-num.hot { color: #f56c6c; }
.todo-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.todo-action { font-size: 12.5px; font-weight: 600; color: var(--brand); }
.todo-status { font-size: 11.5px; color: var(--text-3); }

/* ============================ 主区（吸收剩余高度） ============================ */
.main-row { flex: 1 1 auto; min-height: 0; display: flex; gap: 12px; }
.panel-chart { flex: 1.9 1 0; min-width: 0; }
.panel-docs { flex: 1.1 1 0; min-width: 0; }

/* ============================ 单据清单（条目自适应，超出滚动） ============================ */
.doc-list { flex: 1 1 auto; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 8px; padding-right: 2px; }
.doc-item {
  flex: 1 1 auto; min-height: 42px; max-height: 64px;
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  padding: 6px 11px; border: 1px solid var(--border); border-radius: 9px; background: #fcfdff; cursor: pointer;
  transition: background .15s, border-color .15s, transform .15s;
}
.doc-item:hover { background: #f2fbf7; border-color: #a7e3cb; transform: translateX(2px); }
.doc-main { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.doc-line { display: flex; align-items: center; gap: 7px; min-width: 0; }
.doc-kind {
  flex: none; padding: 0 6px; font-size: 11px; line-height: 17px; color: var(--brand-dark);
  background: var(--brand-soft); border: 1px solid #cdece0; border-radius: 5px;
}
.doc-no { flex: none; font-size: 11.5px; color: var(--text-3); font-variant-numeric: tabular-nums; }
.doc-title { font-size: 13px; color: #374151; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.doc-sub { font-size: 11.5px; color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.doc-right { flex: none; display: flex; align-items: center; gap: 8px; }
.doc-value { font-size: 12.5px; font-weight: 600; color: var(--text-1); font-variant-numeric: tabular-nums; }

/* ============================ 空态：居中占位，不留白面 ============================ */
.empty-box {
  flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px;
  padding: 16px 0; font-size: 13px; color: #b6bcc6;
}
.empty-inline { flex: none; padding: 10px 0; }
.empty-box .el-icon { font-size: 24px; opacity: .75; }

/* ============================ 窄屏：面板行纵向堆叠，页面整体滚动 ============================ */
@media (max-width: 1200px) {
  .dashboard { height: auto; min-height: 100%; }
  .main-row { flex-direction: column; flex: none; }
  .panel-chart, .panel-docs { flex: none; min-height: 268px; }
  .greet { flex-direction: column; align-items: flex-start; }
  .greet-side { align-items: flex-start; width: 100%; }
  .greet-chips, .greet-todos { justify-content: flex-start; }
}
</style>
