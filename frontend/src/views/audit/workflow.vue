<template>
  <div class="page">
    <!-- 页头 -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Operation /></el-icon>审计作业执行流程</h2>
        <div class="ph-desc">
          从审计立项到生成审计工作底稿的六阶段作业轨迹 ·
          本次执行共扫描 <b>{{ totalRecords }}</b> 条业务记录，用时
          <b>{{ (runLog.elapsed_ms || 0) / 1000 }}</b> 秒
        </div>
      </div>
      <div class="ph-actions">
        <el-tag :type="running ? 'warning' : 'success'" effect="dark" round>
          {{ running ? '执行中' : '执行完成' }}
        </el-tag>
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="VideoPlay" :loading="running" @click="onRun">重新执行审计</el-button>
      </div>
    </div>

    <!-- 六阶段流程条 -->
    <el-card shadow="never" class="flow-card">
      <div class="flow-steps">
        <template v-for="(s, i) in steps" :key="s.step">
          <div :class="['flow-step', stepClass(i)]">
            <div class="fs-badge">
              <el-icon v-if="i < steps.length - 1"><Select /></el-icon>
              <el-icon v-else><Loading v-if="running" class="spin" /><Select v-else /></el-icon>
            </div>
            <div class="fs-body">
              <div class="fs-name">{{ s.step }}</div>
              <div class="fs-meta">{{ s.ms }} ms</div>
            </div>
          </div>
          <div v-if="i < steps.length - 1" class="flow-arrow">
            <el-icon><ArrowRight /></el-icon>
          </div>
        </template>
      </div>
      <div class="flow-bar">
        <div class="fb-left">
          <span class="fb-label">执行进度</span>
          <el-progress
            :percentage="progress"
            :stroke-width="8"
            :color="progress >= 100 ? '#10b981' : '#409eff'"
            class="fb-progress"
          />
        </div>
        <div class="fb-right">
          总耗时 <b>{{ (runLog.elapsed_ms || 0) }} ms</b>
        </div>
      </div>
    </el-card>

    <!-- 主体：左步骤明细 / 右数据概览 + 日志 -->
    <div class="grid-main">
      <el-card shadow="never" class="card-fill">
        <template #header>
          <span>执行步骤明细</span>
          <span class="card-tip">共 {{ steps.length }} 个步骤</span>
        </template>
        <div class="table-wrap">
          <el-table :data="steps" border stripe size="small" row-key="step">
            <el-table-column type="index" label="#" width="52" align="center" />
            <el-table-column prop="step" label="步骤" width="130" />
            <el-table-column label="状态" width="96" align="center">
              <template #default="{ row }">
                <el-tag type="success" size="small" effect="plain" round>{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="耗时" width="96" align="right" class-name="col-num">
              <template #default="{ row }">{{ row.ms }} ms</template>
            </el-table-column>
            <el-table-column prop="note" label="执行说明" min-width="300" show-overflow-tooltip />
          </el-table>
        </div>
        <div class="pager">
          <span class="hint">
            审计引擎以只读模式连接被审计业务库，全程不执行任何 INSERT / UPDATE / DELETE 语句
          </span>
        </div>
      </el-card>

      <div class="side-col">
        <el-card shadow="never" class="stat-card">
          <template #header>
            <span>数据概览</span>
            <span class="card-tip">{{ statsCount }} 张业务表</span>
          </template>
          <div class="ds-grid">
            <div v-for="d in dataStats" :key="d.key" class="ds-item">
              <div class="ds-num">{{ num(d.value) }}</div>
              <div class="ds-label">{{ d.label }}</div>
            </div>
          </div>
          <div class="ds-total">
            本次共扫描 <b>{{ num(totalRecords) }}</b> 条业务记录
          </div>
        </el-card>

        <el-card shadow="never" class="clean-card">
          <template #header>数据清洗结果</template>
          <div class="cl-list">
            <div class="cl-row">
              <span class="cl-label">剔除作废单据</span>
              <span class="cl-value">{{ num(clean.void_docs) }} 张</span>
            </div>
            <div class="cl-row">
              <span class="cl-label">单价为空/为零明细</span>
              <span class="cl-value">{{ num(clean.zero_price_items) }} 条</span>
            </div>
            <div class="cl-row">
              <span class="cl-label">缺仓库的到货明细</span>
              <span class="cl-value">{{ num(clean.no_warehouse_items) }} 条</span>
            </div>
            <div class="cl-row cl-kept">
              <span class="cl-label">清洗后参与校验</span>
              <span class="cl-value">{{ num(clean.kept_records) }} 条</span>
            </div>
          </div>
        </el-card>

        <el-card shadow="never" class="log-card">
          <template #header>执行日志</template>
          <div class="log-list">
            <div v-for="(l, i) in logs" :key="i" class="log-item">
              <span class="lg-time">{{ l.time }}</span>
              <span class="lg-text">{{ l.text }}</span>
            </div>
          </div>
        </el-card>
      </div>
    </div>

    <el-card shadow="never" class="note-card">
      <template #header>数据质量说明</template>
      <div class="note-text">{{ note }}</div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Refresh, VideoPlay, Operation, Select, ArrowRight, Loading,
} from '@element-plus/icons-vue'
import { auditApi } from '@/api/audit'

const loading = ref(false)
const running = ref(false)
const steps = ref([])
const runLog = ref({})
const stats = ref({})
const clean = ref({})
const summary = ref({})
const meta = ref({})
const note = ref('')

const num = (v) => Number(v || 0).toLocaleString('zh-CN')

const DATA_STATS_LABEL = [
  { key: 'purchase_orders', label: '采购订单' },
  { key: 'purchase_order_items', label: '订单明细' },
  { key: 'purchase_arrivals', label: '到货单' },
  { key: 'purchase_arrival_items', label: '到货明细' },
  { key: 'purchase_returns', label: '采购退货单' },
  { key: 'purchase_return_items', label: '退货明细' },
  { key: 'suppliers', label: '供应商' },
  { key: 'materials', label: '物料' },
  { key: 'inventory_records', label: '库存记录' },
  { key: 'inventory_transactions', label: '出入库流水' },
]
const dataStats = computed(() => DATA_STATS_LABEL.map((d) => ({ ...d, value: stats.value[d.key] || 0 })))
const statsCount = computed(() => dataStats.value.filter((d) => d.value > 0).length)
const totalRecords = computed(() => dataStats.value.reduce((s, d) => s + d.value, 0))

/** 全部步骤完成即进度 100%，执行中按已完成步数折算 */
const progress = computed(() => {
  const n = steps.value.length
  if (!n) return 0
  const done = steps.value.filter((s) => s.status === '已完成').length
  return Math.round((done / n) * 100)
})
function stepClass(i) {
  const done = steps.value.filter((s) => s.status === '已完成').length
  if (i < done) return 'is-done'
  return 'is-pending'
}

/** 执行日志：按步骤耗时生成带时间戳的作业轨迹 */
const logs = computed(() => {
  const list = []
  const base = meta.value.generated_at || ''
  let acc = 0
  steps.value.forEach((s) => {
    list.push({
      time: base ? base.slice(11) : '—',
      text: `${s.step}完成（${s.ms} ms）：${s.note}`,
    })
    acc += s.ms || 0
  })
  list.push({
    time: base ? base.slice(11) : '—',
    text: `审计执行完毕，累计 ${acc} ms，生成审计发现 ${summary.value.finding_total || 0} 条`,
  })
  return list
})

async function load() {
  loading.value = true
  try {
    const res = await auditApi.report()
    steps.value = (res.run_log && res.run_log.steps) || []
    runLog.value = res.run_log || {}
    stats.value = res.data_stats || {}
    clean.value = res.clean_stats || {}
    summary.value = res.summary || {}
    meta.value = res.report_meta || {}
    note.value = res.data_quality_note || ''
  } catch (e) {
    console.warn('workflow load failed', e)
  } finally {
    loading.value = false
  }
}

async function onRun() {
  running.value = true
  try {
    // 重新执行：后端强制重跑全部审计程序
    await auditApi.run()
    await load()
    ElMessage.success('审计已重新执行完成')
  } catch (e) {
    console.warn('workflow run failed', e)
  } finally {
    running.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.flow-card { flex: 0 0 auto; }
.flow-card :deep(.el-card__body) { padding: 14px 16px 12px; }

/* 流程条：六阶段横排，窄屏自动换行 */
.flow-steps { display: flex; align-items: stretch; gap: 6px; flex-wrap: wrap; }
.flow-step {
  flex: 1 1 130px;
  min-width: 118px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 11px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: linear-gradient(180deg, #fbfdff, #fff);
}
.flow-step.is-done { border-color: #b7ebd6; background: linear-gradient(180deg, #f2fdf8, #fff); }
.flow-step.is-pending { border-color: #f5d9a8; background: linear-gradient(180deg, #fffaf1, #fff); }
.fs-badge {
  flex: 0 0 22px; height: 22px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; color: #fff; background: #10b981;
}
.is-pending .fs-badge { background: #e6a23c; }
.fs-body { min-width: 0; }
.fs-name { font-size: 12.5px; font-weight: 600; color: var(--text-1); white-space: nowrap; }
.fs-meta { font-size: 11px; color: var(--text-3); font-variant-numeric: tabular-nums; }
.flow-arrow { flex: 0 0 auto; display: flex; align-items: center; color: #cbd5e1; font-size: 15px; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.flow-bar { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-top: 12px; padding-top: 11px; border-top: 1px dashed var(--border); }
.fb-left { display: flex; align-items: center; gap: 11px; flex: 1 1 auto; min-width: 0; }
.fb-label { flex: 0 0 auto; font-size: 12px; color: var(--text-2); }
.fb-progress { flex: 1 1 auto; min-width: 0; }
.fb-right { flex: 0 0 auto; font-size: 12px; color: var(--text-2); }
.fb-right b { color: var(--brand-dark); font-variant-numeric: tabular-nums; }

.grid-main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
}
.grid-main > * { min-width: 0; }
.side-col { display: flex; flex-direction: column; gap: 12px; min-height: 0; }
.card-tip { font-size: 12px; font-weight: 400; color: #9ca3af; margin-left: 8px; }

/* 数据概览：两列紧凑格，10 项一次可见 */
.stat-card { flex: 0 0 auto; }
.ds-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; }
.ds-item { padding: 7px 10px; border: 1px solid var(--border); border-radius: 8px; background: #fbfdff; }
.ds-num { font-size: 15px; font-weight: 700; color: var(--text-1); font-variant-numeric: tabular-nums; line-height: 1.2; }
.ds-label { font-size: 11.5px; color: var(--text-2); }
.ds-total { margin-top: 9px; padding-top: 8px; border-top: 1px dashed var(--border); font-size: 12px; color: var(--text-2); }
.ds-total b { color: var(--brand-dark); font-size: 13px; }

/* 数据清洗结果 */
.clean-card { flex: 0 0 auto; }
.clean-card :deep(.el-card__body) { padding: 8px 14px 10px; }
.cl-list { display: flex; flex-direction: column; gap: 6px; }
.cl-row { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; font-size: 12px; }
.cl-label { color: var(--text-2); }
.cl-value { font-weight: 600; color: var(--text-1); font-variant-numeric: tabular-nums; }
.cl-kept { padding-top: 6px; border-top: 1px dashed var(--border); }
.cl-kept .cl-value { color: #0f9d76; }

/* 执行日志 */
.log-card { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
.log-card :deep(.el-card__body) { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 10px 14px; }
.log-list { display: flex; flex-direction: column; gap: 6px; }
.log-item { display: flex; gap: 9px; font-size: 12px; line-height: 1.55; }
.lg-time { flex: 0 0 auto; color: #94a3b8; font-variant-numeric: tabular-nums; font-family: Consolas, monospace; }
.lg-text { color: #475569; word-break: break-all; }

.note-card { flex: 0 0 auto; }
.note-card :deep(.el-card__body) { padding: 10px 16px; }
.note-text { font-size: 12px; line-height: 1.7; color: var(--text-2); }

@media (max-width: 1280px) {
  .grid-main { grid-template-columns: minmax(0, 1fr); }
  .side-col { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
  .log-card { min-height: 180px; }
}
</style>
