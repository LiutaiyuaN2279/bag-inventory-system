<template>
  <div class="page">
    <AuditAssuranceNotice :meta="meta" />
    <!-- 页头 -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Document /></el-icon>审计工作底稿</h2>
        <div class="ph-desc">
          受限试算底稿，不是正式历史审计报告 ·
          共 <b>{{ groups.length }}</b> 份底稿分册 / <b>{{ totalFindings }}</b> 条审计发现
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Printer" :disabled="!groups.length" @click="onPrint">打印底稿</el-button>
        <el-button :icon="Download" :disabled="!groups.length" @click="onExport">导出底稿</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <!-- 底稿抬头信息 -->
    <el-card shadow="never" class="head-card">
      <div class="wp-head">
        <div class="wph-item">
          <span class="wph-label">被审计单位</span>
          <span class="wph-value">{{ meta.audit_name || '箱包制造企业采购与库存管理系统' }}</span>
        </div>
        <div class="wph-item">
          <span class="wph-label">审计期间</span>
          <span class="wph-value">{{ meta.period || '—' }}</span>
        </div>
        <div class="wph-item">
          <span class="wph-label">重要性水平</span>
          <span class="wph-value num">¥ {{ fmt(scope.materiality) }}</span>
        </div>
        <div class="wph-item">
          <span class="wph-label">总体风险</span>
          <span class="wph-value">
            <el-tag :type="riskTagType(summary.overall_risk)" effect="dark" round size="small">
              {{ summary.overall_risk || '—' }}
            </el-tag>
          </span>
        </div>
        <div class="wph-item">
          <span class="wph-label">编制日期</span>
          <span class="wph-value">{{ meta.generated_at || '—' }}</span>
        </div>
      </div>
    </el-card>

    <!-- 底稿主体：左侧程序分册目录 / 右侧选中分册明细 -->
    <div class="grid-main">
      <el-card shadow="never" class="toc-card">
        <template #header>
          <span>底稿目录</span>
          <span class="card-tip">{{ groups.length }} 份分册</span>
        </template>
        <div class="toc-list">
          <div
            v-for="(g, i) in groups"
            :key="g.code"
            :class="['toc-item', { 'is-active': i === activeIdx, 'is-zero': !g.count }]"
            @click="activeIdx = i"
          >
            <span class="toc-idx">{{ String(i + 1).padStart(2, '0') }}</span>
            <div class="toc-main">
              <div class="toc-name">{{ g.code }}　{{ g.name }}</div>
              <div class="toc-meta">
                <el-tag :type="riskTagType(g.risk_level)" size="small" effect="plain" round>
                  {{ g.risk_level }}
                </el-tag>
                <span class="toc-count">{{ g.count ?? '—' }} 条</span>
                <span class="toc-amount">¥ {{ fmt(g.amount) }}</span>
              </div>
            </div>
          </div>
        </div>
      </el-card>

      <el-card v-if="activeGroup" shadow="never" class="card-fill">
        <template #header>
          <span>{{ activeGroup.code }}　{{ activeGroup.name }}</span>
          <span class="card-tip">
            线索 {{ activeGroup.count ?? '—' }} 条 / 参考金额 ¥ {{ fmt(activeGroup.amount) }}
          </span>
        </template>
        <div class="sheet-body">
          <!-- 底稿抬头的程序要素 -->
          <div class="sheet-head">
            <div class="sh-row">
              <span class="sh-label">审计目标</span>
              <span class="sh-value">{{ activeGroup.objective }}</span>
            </div>
            <div class="sh-row">
              <span class="sh-label">判定规则</span>
              <span class="sh-value">{{ activeGroup.rule }}</span>
            </div>
            <div class="sh-row">
              <span class="sh-label">审计结论</span>
              <span class="sh-value">
                <b v-if="activeGroup.status === '数据不足'">证据及份额依据不足，结果不可确定；未计算不等于零异常。</b>
                <b v-else-if="activeGroup.count">旧口径形成 {{ activeGroup.count }} 条核查线索，尚非正式审计结论。</b>
                <b v-else>旧口径未生成线索，历史可信范围未核定，不能认定审计通过。</b>
              </span>
            </div>
            <div v-if="activeGroup.note" class="sh-row">
              <span class="sh-label">说明</span>
              <span class="sh-value sh-note">{{ activeGroup.note }}</span>
            </div>
          </div>

          <!-- 底稿明细：本程序下的全部审计发现 -->
          <div class="sheet-table">
            <el-table :data="activeGroup.findings" border stripe size="small" row-key="finding_id">
              <el-table-column prop="finding_id" label="编号" width="72" align="center" />
              <el-table-column label="风险等级" width="90" align="center">
                <template #default="{ row }">
                  <el-tag :type="riskTagType(row.risk_level)" size="small" effect="dark" round>
                    {{ row.risk_level }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="分值" width="62" align="center">
                <template #default="{ row }">
                  <span :class="['sc', row.risk_score >= 70 ? 'sc-h' : row.risk_score >= 50 ? 'sc-m' : 'sc-l']">
                    {{ row.risk_score }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="title" label="审计发现" min-width="200" show-overflow-tooltip />
              <el-table-column prop="subject" label="涉及对象" min-width="210" show-overflow-tooltip />
              <el-table-column label="涉及金额(元)" width="130" align="right" class-name="col-num">
                <template #default="{ row }">
                  {{ row.amount ? '¥ ' + fmt(row.amount) : '—' }}
                </template>
              </el-table-column>
              <el-table-column prop="suggestion" label="审计建议" min-width="200" show-overflow-tooltip />
            </el-table>
          </div>
        </div>
        <div class="pager">
          <span class="hint">
            底稿编号 {{ activeGroup.code }}-WP · 证据链与审计说明详见「审计发现」页对应条目
          </span>
        </div>
      </el-card>
      <el-empty v-else description="暂无底稿数据" />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Refresh, Download, Printer, Document } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { auditApi } from '@/api/audit'
import AuditAssuranceNotice from '@/components/AuditAssuranceNotice.vue'
import { formatAuditNumber, withAuditDisclosure, auditDisclosureColumns } from '@/utils/auditPresentation'
import { exportRows } from '@/utils/exportRows'

const loading = ref(false)
const groups = ref([])
const activeIdx = ref(0)
const meta = ref({})
const scope = ref({})
const summary = ref({})

const fmt = formatAuditNumber
const activeGroup = computed(() => groups.value[activeIdx.value] || null)
const totalFindings = computed(() => groups.value.reduce((s, g) => s + (g.count || 0), 0))

function riskTagType(lv) {
  if (lv === '高') return 'danger'
  if (lv === '中') return 'warning'
  if (lv === '低') return 'success'
  return 'info'
}

async function load() {
  loading.value = true
  try {
    const res = await auditApi.workpaper()
    groups.value = res.groups || []
    meta.value = res.report_meta || {}
    scope.value = res.scope || {}
    summary.value = res.summary || {}
    // 默认定位到第一份有发现的底稿分册
    const first = groups.value.findIndex((g) => g.count > 0)
    activeIdx.value = first >= 0 ? first : 0
  } catch (e) {
    groups.value = []
    console.warn('workpaper load failed', e)
  } finally {
    loading.value = false
  }
}

function onExport() {
  const columns = [
    { prop: 'finding_id', label: '发现编号' },
    { prop: 'risk_level', label: '风险等级' },
    { prop: 'risk_score', label: '风险分值' },
    { prop: 'title', label: '审计发现' },
    { prop: 'subject', label: '涉及对象' },
    { prop: 'amount', label: '涉及金额(元)', formatter: (r) => fmt(r.amount) },
    { prop: 'suggestion', label: '审计建议' },
  ]
  const rows = groups.value.flatMap((g) => (g.findings || []).map((f) => ({ ...f, rule_code: g.code })))
  if (!rows.length) return ElMessage.warning('当前没有可导出的底稿数据')
  exportRows(withAuditDisclosure(rows, meta.value), [...auditDisclosureColumns, { prop: 'rule_code', label: '关联程序' }, ...columns], '受限试算底稿')
}

function onPrint() {
  window.print()
}

onMounted(load)
</script>

<style scoped>
.head-card { flex: 0 0 auto; }
.head-card :deep(.el-card__body) { padding: 11px 16px; }
.wp-head { display: flex; flex-wrap: wrap; gap: 10px 26px; align-items: center; }
.wph-item { display: flex; align-items: center; gap: 7px; }
.wph-label { font-size: 12px; color: var(--text-3); }
.wph-value { font-size: 12.5px; font-weight: 600; color: var(--text-1); }
.wph-value.num { font-variant-numeric: tabular-nums; }

.grid-main {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
}
.grid-main > * { min-width: 0; }
.card-tip { font-size: 12px; font-weight: 400; color: #9ca3af; margin-left: 8px; }

/* 目录：卡片式列表，选中项左侧品牌色条 */
.toc-card { display: flex; flex-direction: column; min-height: 0; }
.toc-card :deep(.el-card__body) { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 8px 10px; }
.toc-list { display: flex; flex-direction: column; gap: 5px; }
.toc-item {
  display: flex; gap: 9px; align-items: flex-start;
  padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px;
  cursor: pointer; transition: all .15s; background: #fff;
}
.toc-item:hover { border-color: #b7ebd6; background: #f6fffb; }
.toc-item.is-active { border-color: var(--brand); background: #f2fdf8; box-shadow: inset 3px 0 0 var(--brand); }
.toc-item.is-zero .toc-name { color: var(--text-2); }
.toc-idx {
  flex: 0 0 20px; height: 20px; line-height: 20px; text-align: center;
  font-size: 11px; font-weight: 700; border-radius: 5px;
  background: #eef2f7; color: #64748b; font-variant-numeric: tabular-nums;
}
.is-active .toc-idx { background: var(--brand); color: #fff; }
.toc-main { min-width: 0; flex: 1 1 auto; }
.toc-name { font-size: 12.5px; font-weight: 600; color: var(--text-1); line-height: 1.4; }
.toc-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; margin-top: 5px; }
.toc-count { font-size: 11.5px; color: var(--text-2); }
.toc-amount { font-size: 11.5px; color: #e5484d; font-variant-numeric: tabular-nums; }

/* 底稿正文 */
.sheet-body { display: flex; flex-direction: column; gap: 11px; flex: 1 1 auto; min-height: 0; }
.sheet-head { display: flex; flex-direction: column; gap: 7px; padding: 11px 13px; background: #f8fafc; border: 1px solid var(--border); border-radius: 9px; flex: 0 0 auto; }
.sh-row { display: flex; gap: 10px; align-items: flex-start; font-size: 12.5px; line-height: 1.65; }
.sh-label { flex: 0 0 62px; color: var(--text-3); text-align: justify; text-align-last: justify; }
.sh-value { flex: 1 1 auto; color: #334155; min-width: 0; }
.sh-value b { color: #0f9d76; font-weight: 700; }
.sh-value b.sh-pass { color: #0f9d76; }
.sh-note { color: var(--text-2); font-size: 12px; }
.sheet-table { flex: 1 1 auto; min-height: 0; overflow: auto; }

.sc { font-variant-numeric: tabular-nums; font-weight: 700; font-size: 12.5px; }
.sc-h { color: #e5484d; }
.sc-m { color: #d97706; }
.sc-l { color: #0f9d76; }

@media (max-width: 1280px) {
  .grid-main { grid-template-columns: minmax(0, 1fr); }
  .toc-card { max-height: 220px; }
}
@media print {
  .ph-actions, .toc-card { display: none !important; }
  .grid-main { grid-template-columns: minmax(0, 1fr); }
}
</style>
