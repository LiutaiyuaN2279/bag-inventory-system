<template>
  <div class="page">
    <!-- 页头：审计名称 + 说明 + 执行/刷新 -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Cpu /></el-icon>智能审计工作台</h2>
        <div class="ph-desc">
          {{ meta.audit_name || '采购付款循环审计' }} ·
          审计期间 {{ meta.period || '—' }} ·
          <b>{{ summary.procedure_total || 0 }}</b> 项审计程序 /
          <b>{{ summary.finding_total || 0 }}</b> 条审计发现 ·
          数据源 {{ meta.data_source || '—' }}
        </div>
      </div>
      <div class="ph-actions">
        <el-tag :type="riskTagType(summary.overall_risk)" effect="dark" round size="large" class="risk-tag">
          总体风险：{{ summary.overall_risk || '—' }}
        </el-tag>
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="VideoPlay" :loading="running" @click="onRun">执行审计</el-button>
      </div>
    </div>

    <!-- KPI 统计条 -->
    <div class="stat-strip">
      <div class="stat-item">
        <div class="si-icon si-blue"><el-icon><List /></el-icon></div>
        <div>
          <div class="si-num">{{ summary.procedure_total || 0 }}</div>
          <div class="si-label">审计程序（命中 {{ summary.procedure_hit || 0 }} 项）</div>
        </div>
      </div>
      <div class="stat-item">
        <div class="si-icon si-teal"><el-icon><Aim /></el-icon></div>
        <div>
          <div class="si-num">{{ hitRate }}<span class="si-unit">%</span></div>
          <div class="si-label">程序命中率</div>
        </div>
      </div>
      <div class="stat-item">
        <div class="si-icon si-amber"><el-icon><Warning /></el-icon></div>
        <div>
          <div class="si-num">{{ summary.finding_total || 0 }}<span class="si-sub">条</span></div>
          <div class="si-label">审计发现（高风险 {{ levelOf('高') }} 条）</div>
        </div>
      </div>
      <div class="stat-item">
        <div class="si-icon si-red"><el-icon><Money /></el-icon></div>
        <div>
          <div class="si-num">¥ {{ short(summary.amount_total) }}</div>
          <div class="si-label">涉及金额（占采购额 {{ amountPct }}%）</div>
        </div>
      </div>
    </div>

    <!-- 主体：左程序执行情况 / 右风险分布 + 审计范围 -->
    <div class="grid-main">
      <el-card shadow="never" class="card-fill">
        <template #header>
          <span>审计程序执行情况</span>
          <span class="card-tip">共 {{ procedures.length }} 项，命中 {{ summary.procedure_hit || 0 }} 项</span>
        </template>
        <div class="table-wrap">
          <el-table :data="procedures" border stripe size="small" row-key="code" :row-class-name="procRowClass">
            <el-table-column prop="code" label="编号" width="62" align="center" />
            <el-table-column prop="name" label="审计程序" min-width="190" show-overflow-tooltip />
            <el-table-column prop="objective" label="审计目标" min-width="230" show-overflow-tooltip />
            <el-table-column prop="rule" label="判定规则" min-width="210" show-overflow-tooltip />
            <el-table-column label="命中" width="76" align="center">
              <template #default="{ row }">
                <span :class="['hit-num', row.hit_count ? 'hit-on' : 'hit-off']">{{ row.hit_count }}</span>
              </template>
            </el-table-column>
            <el-table-column label="风险" width="88" align="center">
              <template #default="{ row }">
                <el-tag :type="riskTagType(row.risk_level)" size="small" effect="plain" round>
                  {{ row.risk_level }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <div class="pager">
          <span class="hint">
            程序命中判定：命中数 &gt; 0 记为「命中」，否则按程序性质报告为「通过」或「无」；
            共扫描 <b>{{ totalRecords }}</b> 条业务记录
          </span>
        </div>
      </el-card>

      <div class="side-col">
        <el-card shadow="never" class="chart-card">
          <template #header>
            <span>风险等级分布</span>
            <span class="card-tip">共 {{ summary.finding_total || 0 }} 条</span>
          </template>
          <div ref="riskChartRef" class="chart-box" />
        </el-card>

        <el-card shadow="never" class="scope-card">
          <template #header>审计范围与重要性水平</template>
          <div class="scope-list">
            <div class="scope-row">
              <span class="sl-label">审计期间</span>
              <span class="sl-value">{{ meta.period || '—' }}</span>
            </div>
            <div class="scope-row">
              <span class="sl-label">期间采购总额</span>
              <span class="sl-value num">¥ {{ fmt(scope.total_purchase_amount) }}</span>
            </div>
            <div class="scope-row">
              <span class="sl-label">重要性水平</span>
              <span class="sl-value num sl-hl">¥ {{ fmt(scope.materiality) }}</span>
            </div>
            <div class="scope-row">
              <span class="sl-label">涉及金额合计</span>
              <span class="sl-value num sl-red">¥ {{ fmt(summary.amount_total) }}</span>
            </div>
            <div class="scope-row">
              <span class="sl-label">审计基准日</span>
              <span class="sl-value">{{ meta.audit_date || '—' }}</span>
            </div>
          </div>
          <div class="scope-note">{{ scope.materiality_note || '按期间采购总额的固定比例确定' }}</div>
        </el-card>
      </div>
    </div>

    <!-- 数据说明 -->
    <el-card shadow="never" class="note-card">
      <template #header>数据说明</template>
      <div class="note-text">{{ note }}</div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Refresh, VideoPlay, List, Aim, Warning, Money, Cpu,
} from '@element-plus/icons-vue'
import { auditApi } from '@/api/audit'
import { useUserStore } from '@/store/user'
import { CHART_TOOLTIP, useChart } from '@/composables/useChart'

const userStore = useUserStore()
const loading = ref(false)
const running = ref(false)
const meta = ref({})
const scope = ref({})
const stats = ref({})
const summary = ref({})
const procedures = ref([])
const runLog = ref({})
const note = ref('')

const canRun = computed(() => userStore.hasPermission('audit:run'))
const levelOf = (lv) => (summary.value.by_level || {})[lv] || 0
const fmt = (v) => Number(v || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
/** 大额缩写：亿级才缩写，万级仍显示完整金额（保留小数便于与底稿核对） */
const short = (v) => {
  const n = Number(v || 0)
  if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(2) + '亿'
  return fmt(n)
}
const hitRate = computed(() => {
  const t = summary.value.procedure_total || 0
  if (!t) return '0.0'
  return (((summary.value.procedure_hit || 0) / t) * 100).toFixed(1)
})
const amountPct = computed(() => {
  const base = scope.value.total_purchase_amount || 0
  if (!base) return '0.0'
  return (((summary.value.amount_total || 0) / base) * 100).toFixed(1)
})
const totalRecords = computed(() => {
  const s = stats.value
  return (s.purchase_orders || 0) + (s.purchase_order_items || 0) + (s.purchase_arrivals || 0)
    + (s.purchase_arrival_items || 0) + (s.purchase_returns || 0) + (s.purchase_return_items || 0)
    + (s.suppliers || 0) + (s.materials || 0) + (s.inventory_records || 0) + (s.inventory_transactions || 0)
})

const RISK_COLOR = { 高: '#f56c6c', 中: '#e6a23c', 低: '#10b981' }
function riskTagType(lv) {
  if (lv === '高') return 'danger'
  if (lv === '中') return 'warning'
  if (lv === '低') return 'success'
  return 'info'
}
/** 命中行高亮，让审计人员一眼定位有发现的程序 */
const procRowClass = ({ row }) => (row.hit_count > 0 ? 'row-hit' : '')

/* ---------------- 图表：风险等级分布（横向条形图） ----------------
 * 只注册了 Line/Bar/PieChart，故用横向条形图而非环形图，保证图表可用。
 */
const riskChartRef = ref(null)
function riskOption() {
  const bl = summary.value.by_level || {}
  const levels = ['高', '中', '低']
  const values = levels.map((lv) => bl[lv] || 0)
  const total = values.reduce((a, b) => a + b, 0) || 1
  return {
    tooltip: {
      ...CHART_TOOLTIP,
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const p = Array.isArray(params) ? params[0] : params
        const lv = levels[p.dataIndex]
        return `${p.marker}${lv}风险<br/>审计发现：<b>${p.value}</b> 条（${((p.value / total) * 100).toFixed(1)}%）`
      },
    },
    grid: { left: 8, right: 52, top: 10, bottom: 4, containLabel: true },
    xAxis: { type: 'value', show: false },
    yAxis: {
      type: 'category',
      data: levels.map((lv) => lv + '风险'),
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: { color: '#64748b', fontSize: 12, fontWeight: 600 },
    },
    series: [{
      type: 'bar',
      barWidth: 16,
      itemStyle: {
        borderRadius: [0, 8, 8, 0],
        color: (p) => RISK_COLOR[levels[p.dataIndex]],
      },
      label: {
        show: true,
        position: 'right',
        color: '#64748b',
        fontSize: 12,
        formatter: (p) => `${p.value} 条`,
      },
      data: values,
    }],
  }
}
useChart(riskChartRef, riskOption, { watchSources: () => [summary.value] })

async function load() {
  loading.value = true
  try {
    const res = await auditApi.report()
    meta.value = res.report_meta || {}
    scope.value = res.scope || {}
    stats.value = res.data_stats || {}
    summary.value = res.summary || {}
    procedures.value = res.procedures || []
    runLog.value = res.run_log || {}
    note.value = res.data_quality_note || ''
  } catch (e) {
    console.warn('audit report load failed', e)
  } finally {
    loading.value = false
  }
}

async function onRun() {
  running.value = true
  try {
    const res = await auditApi.run()
    summary.value = res.summary || summary.value
    procedures.value = res.procedures || procedures.value
    note.value = res.data_quality_note || note.value
    scope.value = res.scope || scope.value
    meta.value = res.report_meta || meta.value
    const ms = (res.run_log && res.run_log.elapsed_ms) || 0
    ElMessage.success(`审计执行完成，用时 ${ms} ms，发现 ${res.summary.finding_total} 条`)
  } catch (e) {
    console.warn('audit run failed', e)
  } finally {
    running.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.risk-tag { font-weight: 700; }
.si-num .si-unit { font-size: 12px; font-weight: 500; color: var(--text-2); margin-left: 2px; }
.si-num .si-sub { font-size: 12px; font-weight: 500; color: var(--text-2); margin-left: 3px; }
.si-icon.si-blue { background: #eaf2ff; color: #2f6fed; }
.si-icon.si-teal { background: #e6faf7; color: #14b8a6; }
.si-icon.si-amber { background: #fff5e6; color: #d97706; }
.si-icon.si-red { background: #fdecec; color: #e5484d; }

/* 主体两栏：左侧程序表撑满，右侧窄列放图与范围卡 */
.grid-main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 330px;
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
}
.grid-main > * { min-width: 0; }
.side-col { display: flex; flex-direction: column; gap: 12px; min-height: 0; }
.chart-card { flex: 0 0 auto; }
.chart-card :deep(.el-card__body) { padding: 6px 12px 10px; }
.chart-box { width: 100%; height: 168px; }
.scope-card { flex: 0 0 auto; }
.card-tip { font-size: 12px; font-weight: 400; color: #9ca3af; margin-left: 8px; }
:deep(.row-hit) td { background: #fffaf3 !important; }
:deep(.row-hit:hover) td { background: #fff5e6 !important; }
.hit-num { font-variant-numeric: tabular-nums; font-weight: 700; font-size: 13px; }
.hit-num.hit-on { color: #e5484d; }
.hit-num.hit-off { color: #10b981; }

/* 审计范围卡：稠密两列信息，替代表格 */
.scope-list { display: flex; flex-direction: column; gap: 7px; }
.scope-row { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.sl-label { font-size: 12px; color: var(--text-2); flex: 0 0 auto; }
.sl-value { font-size: 12.5px; font-weight: 600; color: var(--text-1); text-align: right; }
.sl-value.sl-hl { color: #0f9d76; }
.sl-value.sl-red { color: #e5484d; }
.scope-note { margin-top: 9px; padding-top: 8px; border-top: 1px dashed var(--border); font-size: 11.5px; line-height: 1.55; color: var(--text-3); }

.note-card { flex: 0 0 auto; }
.note-card :deep(.el-card__body) { padding: 10px 16px; }
.note-text { font-size: 12px; line-height: 1.7; color: var(--text-2); }

@media (max-width: 1280px) {
  .grid-main { grid-template-columns: minmax(0, 1fr); }
  .side-col { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
}
</style>
