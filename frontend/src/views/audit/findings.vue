<template>
  <div class="page">
    <AuditAssuranceNotice :meta="meta" />
    <!-- 页头 -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Warning /></el-icon>审计发现</h2>
        <div class="ph-desc">
          共 <b>{{ total }}</b> 条审计发现，其中高风险 <b>{{ levelCount('高') }}</b> 条，
          涉及金额 <b>¥ {{ fmt(amountTotal) }}</b> ·
          以下为旧口径核查线索，不代表已核验的正式审计结论
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Download" :disabled="!tableRows.length" @click="onExport">导出清单</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <!-- 筛选区 -->
    <el-card shadow="never" class="filter-card">
      <div class="toolbar">
        <el-form :inline="true" class="tb-left">
          <el-form-item label="风险等级">
            <el-select v-model="query.risk_level" placeholder="全部等级" clearable style="width:130px" @change="onSearch">
              <el-option label="高风险" value="高" />
              <el-option label="中风险" value="中" />
              <el-option label="低风险" value="低" />
            </el-select>
          </el-form-item>
          <el-form-item label="审计程序">
            <el-select v-model="query.rule_code" placeholder="全部程序" clearable style="width:230px" @change="onSearch">
              <el-option
                v-for="p in procedures"
                :key="p.code"
                :label="`${p.code}　${p.name}`"
                :value="p.code"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="关键字">
            <el-input
              v-model="query.keyword"
              placeholder="发现标题 / 涉及对象 / 说明"
              clearable
              style="width:230px"
              @keyup.enter="onSearch"
              @clear="onSearch"
            />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :icon="Search" @click="onSearch">查询</el-button>
            <el-button :icon="RefreshLeft" @click="onReset">重置</el-button>
          </el-form-item>
        </el-form>
        <div class="tb-right">
          <span class="tb-hint">已按风险分值降序排列</span>
        </div>
      </div>
    </el-card>

    <!-- 发现清单表 -->
    <el-card shadow="never" class="card-fill">
      <div class="table-wrap">
        <el-table
          :data="tableRows"
          border
          stripe
          size="small"
          row-key="finding_id"
          @row-dblclick="(row) => openDetail(row)"
        >
          <el-table-column prop="finding_id" label="编号" width="72" align="center" fixed />
          <el-table-column label="风险等级" width="92" align="center">
            <template #default="{ row }">
              <el-tag :type="riskTagType(row.risk_level)" size="small" effect="dark" round>
                {{ row.risk_level }}风险
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="风险分值" width="104" align="center" sortable :sort-by="(r) => r.risk_score">
            <template #default="{ row }">
              <div class="score-cell">
                <span :class="['score-num', scoreClass(row.risk_score)]">{{ row.risk_score }}</span>
                <el-progress
                  :percentage="row.risk_score"
                  :stroke-width="4"
                  :show-text="false"
                  :color="scoreColor(row.risk_score)"
                  class="score-bar"
                />
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="rule_code" label="程序" width="66" align="center" />
          <el-table-column prop="title" label="审计发现" min-width="230" show-overflow-tooltip />
          <el-table-column prop="subject" label="涉及对象" min-width="240" show-overflow-tooltip />
          <el-table-column label="涉及金额(元)" width="132" align="right" class-name="col-num" sortable :sort-by="(r) => r.amount">
            <template #default="{ row }">
              <span :class="{ 'amt-zero': row.amount === 0 }">{{ row.amount == null ? '—' : '¥ ' + fmt(row.amount) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="88" align="center" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openDetail(row)">查看详情</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div class="pager">
        <span class="hint">
          共 <b>{{ total }}</b> 条记录，当前显示第 {{ rangeText }} 条
        </span>
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          :page-sizes="[20, 50, 100, 200]"
          layout="sizes, prev, pager, next, jumper"
          background
          small
          @current-change="load"
          @size-change="onSizeChange"
        />
      </div>
    </el-card>

    <!-- 审计发现详情 -->
    <el-dialog
      v-model="detail.visible"
      :title="`审计发现详情　${detail.data.finding_id || ''}`"
      width="1080px"
      align-center
      draggable
      destroy-on-close
      class="finding-dialog"
    >
      <div v-loading="detail.loading" class="fd-body">
        <div class="fd-head">
          <div class="fd-head-main">
            <div class="fd-title">{{ detail.data.title || '—' }}</div>
            <div class="fd-tags">
              <el-tag :type="riskTagType(detail.data.risk_level)" effect="dark" round>
                {{ detail.data.risk_level }}风险
              </el-tag>
              <el-tag type="info" effect="plain" round>关联程序 {{ detail.data.rule_code }}</el-tag>
              <el-tag type="info" effect="plain" round>编号 {{ detail.data.finding_id }}</el-tag>
            </div>
          </div>
          <div class="fd-score">
            <div class="fs-num" :style="{ color: scoreColor(detail.data.risk_score) }">{{ detail.data.risk_score }}</div>
            <div class="fs-label">风险分值</div>
          </div>
        </div>

        <div class="fd-kpi">
          <div class="fk-item">
            <div class="fk-label">涉及对象</div>
            <div class="fk-value">{{ detail.data.subject || '—' }}</div>
          </div>
          <div class="fk-item">
            <div class="fk-label">涉及金额</div>
            <div class="fk-value fk-money">
              {{ detail.data.amount == null ? '—' : '¥ ' + fmt(detail.data.amount) }}
            </div>
          </div>
          <div class="fk-item">
            <div class="fk-label">证据链</div>
            <div class="fk-value">{{ (detail.data.evidence || []).length }} 条</div>
          </div>
        </div>

        <el-divider content-position="left">审计说明</el-divider>
        <div class="fd-text">{{ detail.data.description || '—' }}</div>

        <el-divider content-position="left">证据链</el-divider>
        <div v-if="(detail.data.evidence || []).length" class="ev-list">
          <div v-for="(e, i) in detail.data.evidence" :key="i" class="ev-item">
            <span class="ev-idx">{{ i + 1 }}</span>
            <span class="ev-text">{{ e }}</span>
          </div>
        </div>
        <el-empty v-else description="该发现暂无结构化证据条目" :image-size="52" />

        <el-divider content-position="left">规则生成的核查建议</el-divider>
        <p>以下建议由确定规则模板生成；未提供独立AI建议，未记录人工确认，不代表已批准审计结论。</p>
        <div class="fd-suggest">
          <el-icon class="sug-icon"><Opportunity /></el-icon>
          <span>{{ detail.data.suggestion || '—' }}</span>
        </div>

        <template v-if="detail.data.traceability">
          <el-divider content-position="left">当次冻结输入定位（待核实）</el-divider>
          <p>运行版本：{{ detail.data.traceability.run_id || '—' }}；规则版本：{{ detail.data.traceability.rule_version || '—' }}</p>
          <p v-for="(notice, i) in detail.data.traceability.limitations" :key="i">{{ notice }}</p>
          <p>仍需核验的材料清单（未逐项核验，不表示材料实际不存在）：</p>
          <p v-for="(item, i) in detail.data.traceability.review_checklist" :key="'check-'+i">{{ item }}</p>
          <el-empty v-if="!detail.data.traceability.candidates.length" description="没有可定位的冻结候选行；不使用当前数据替代" :image-size="52" />
          <div v-for="(source, i) in detail.data.traceability.candidates" :key="i" class="ev-item">
            <span>冻结查询索引 {{ source.query_index }} / 行索引 {{ source.row_index }}（从0开始，仅单号匹配，尚未证明来源资格）</span>
            <span>{{ source.fields }}</span>
          </div>
          <p v-if="detail.data.traceability.truncated">仅展示前20条候选定位，不能视为完整覆盖。</p>
        </template>

        <template v-if="detail.data.procedure">
          <el-divider content-position="left">关联审计程序</el-divider>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="程序编号">{{ detail.data.procedure.code }}</el-descriptions-item>
            <el-descriptions-item label="程序名称">{{ detail.data.procedure.name }}</el-descriptions-item>
            <el-descriptions-item label="审计目标" :span="2">{{ detail.data.procedure.objective }}</el-descriptions-item>
            <el-descriptions-item label="判定规则" :span="2">{{ detail.data.procedure.rule }}</el-descriptions-item>
            <el-descriptions-item label="本程序命中" :span="2">
              共 {{ detail.data.procedure.hit_count }} 条（风险等级：{{ detail.data.procedure.risk_level }}）
            </el-descriptions-item>
          </el-descriptions>
        </template>

        <template v-if="(detail.data.refs || []).length">
          <el-divider content-position="left">关联单据</el-divider>
          <div class="ref-list">
            <el-tag v-for="(r, i) in detail.data.refs" :key="i" type="info" effect="plain" class="ref-tag">
              {{ r.type }}：{{ r.no }}
            </el-tag>
          </div>
        </template>
      </div>
      <template #footer>
        <div class="fd-footer">
          <span class="fd-footer-hint">审计发现编号 {{ detail.data.finding_id }} · 关联程序 {{ detail.data.rule_code }}</span>
          <el-button @click="detail.visible = false">关闭</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import {
  Search, Refresh, RefreshLeft, Download, Warning, Opportunity,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { auditApi } from '@/api/audit'
import AuditAssuranceNotice from '@/components/AuditAssuranceNotice.vue'
import { formatAuditNumber, withAuditDisclosure, auditDisclosureColumns } from '@/utils/auditPresentation'
import { exportRows } from '@/utils/exportRows'

const loading = ref(false)
const tableRows = ref([])
const total = ref(0)
const procedures = ref([])
const summary = ref({})
const meta = ref({})
const query = reactive({ risk_level: '', rule_code: '', keyword: '', page: 1, page_size: 20 })
const detail = reactive({ visible: false, loading: false, data: {} })

const fmt = formatAuditNumber
const levelCount = (lv) => ((summary.value.by_level || {})[lv] || 0)
const amountTotal = computed(() => summary.value.amount_total || 0)
const rangeText = computed(() => {
  if (!total.value) return '0'
  const start = (query.page - 1) * query.page_size + 1
  const end = Math.min(query.page * query.page_size, total.value)
  return `${start}-${end}`
})

function riskTagType(lv) {
  if (lv === '高') return 'danger'
  if (lv === '中') return 'warning'
  if (lv === '低') return 'success'
  return 'info'
}
function scoreColor(score) {
  const n = Number(score || 0)
  if (n >= 70) return '#f56c6c'
  if (n >= 50) return '#e6a23c'
  return '#10b981'
}
function scoreClass(score) {
  const n = Number(score || 0)
  if (n >= 70) return 'score-high'
  if (n >= 50) return 'score-mid'
  return 'score-low'
}

async function load() {
  loading.value = true
  try {
    const res = await auditApi.findings({
      risk_level: query.risk_level,
      rule_code: query.rule_code,
      keyword: query.keyword,
      page: query.page,
      page_size: query.page_size,
    })
    tableRows.value = res.list || []
    total.value = res.total || 0
    summary.value = res.summary || {}
    meta.value = res.report_meta || {}
  } catch (e) {
    tableRows.value = []
    total.value = 0
    console.warn('audit findings load failed', e)
  } finally {
    loading.value = false
  }
}

async function loadProcedures() {
  try {
    procedures.value = (await auditApi.procedures()) || []
  } catch {
    procedures.value = []
  }
}

function onSearch() {
  query.page = 1
  load()
}
function onReset() {
  query.risk_level = ''
  query.rule_code = ''
  query.keyword = ''
  query.page = 1
  load()
}
function onSizeChange() {
  query.page = 1
  load()
}

async function openDetail(row) {
  detail.data = { ...row }
  detail.visible = true
  detail.loading = true
  try {
    detail.data = await auditApi.findingDetail(row.finding_id, meta.value.run_id)
  } catch (e) {
    console.warn('audit finding detail failed', e)
  } finally {
    detail.loading = false
  }
}

function onExport() {
  const columns = [
    { prop: 'finding_id', label: '编号' },
    { prop: 'risk_level', label: '风险等级' },
    { prop: 'risk_score', label: '风险分值' },
    { prop: 'rule_code', label: '关联程序' },
    { prop: 'title', label: '审计发现' },
    { prop: 'subject', label: '涉及对象' },
    { prop: 'amount', label: '涉及金额(元)', formatter: (r) => fmt(r.amount) },
    { prop: 'description', label: '审计说明' },
    { prop: 'suggestion', label: '审计建议' },
  ]
  if (!tableRows.value.length) return ElMessage.warning('当前没有可导出的数据')
  exportRows(withAuditDisclosure(tableRows.value, meta.value), [...auditDisclosureColumns, ...columns], '受限试算线索清单')
}

onMounted(() => {
  loadProcedures()
  load()
})
</script>

<style scoped>
.filter-card { flex: 0 0 auto; }
.filter-card :deep(.el-card__body) { padding: 12px 16px; }
.tb-hint { font-size: 12px; color: var(--text-3); }

/* 分值列：数字 + 迷你进度条 */
.score-cell { display: flex; flex-direction: column; gap: 3px; align-items: center; }
.score-num { font-variant-numeric: tabular-nums; font-weight: 700; font-size: 13px; line-height: 1.1; }
.score-high { color: #e5484d; }
.score-mid { color: #d97706; }
.score-low { color: #0f9d76; }
.score-bar { width: 100%; }
.score-bar :deep(.el-progress-bar__outer) { background: #eef1f6; }
.amt-zero { color: var(--text-3); }

/* 详情弹窗 */
.finding-dialog :deep(.el-dialog__body) { padding-top: 8px; }
.fd-body { max-height: 66vh; overflow: auto; padding-right: 4px; }
.fd-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.fd-head-main { min-width: 0; }
.fd-title { font-size: 16px; font-weight: 700; color: var(--text-1); line-height: 1.4; }
.fd-tags { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 9px; }
.fd-score { flex: 0 0 auto; text-align: center; padding: 4px 14px; border-radius: 10px; background: #fbfcfe; border: 1px solid var(--border); }
.fs-num { font-size: 26px; font-weight: 800; line-height: 1.1; font-variant-numeric: tabular-nums; }
.fs-label { font-size: 11.5px; color: var(--text-3); margin-top: 1px; }

.fd-kpi { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
.fk-item { padding: 9px 12px; border: 1px solid var(--border); border-radius: 9px; background: linear-gradient(180deg, #fbfdff, #fff); }
.fk-label { font-size: 11.5px; color: var(--text-3); }
.fk-value { font-size: 13px; font-weight: 600; color: var(--text-1); margin-top: 3px; word-break: break-all; }
.fk-money { color: #e5484d; font-variant-numeric: tabular-nums; }

.fd-text { font-size: 13px; line-height: 1.85; color: #374151; text-align: justify; white-space: pre-wrap; }

.ev-list { display: flex; flex-direction: column; gap: 6px; }
.ev-item { display: flex; align-items: flex-start; gap: 9px; padding: 7px 11px; background: #f8fafc; border-left: 3px solid #cbd5e1; border-radius: 0 8px 8px 0; }
.ev-idx { flex: 0 0 18px; height: 18px; line-height: 18px; text-align: center; border-radius: 50%; background: #e2e8f0; color: #475569; font-size: 11px; font-weight: 700; }
.ev-text { font-size: 12.5px; line-height: 1.6; color: #334155; word-break: break-all; }

.fd-suggest { display: flex; align-items: flex-start; gap: 9px; padding: 11px 13px; background: #f0fdf9; border: 1px solid #d1fae5; border-radius: 9px; font-size: 13px; line-height: 1.75; color: #065f46; text-align: justify; }
.sug-icon { flex: 0 0 auto; margin-top: 3px; font-size: 16px; color: #10b981; }

.ref-list { display: flex; flex-wrap: wrap; gap: 7px; }
.ref-tag { font-size: 12px; }

.fd-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.fd-footer-hint { font-size: 12px; color: var(--text-3); }
.finding-dialog :deep(.el-dialog) { max-width: 96vw; }
</style>
