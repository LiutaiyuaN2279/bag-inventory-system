<template>
  <div class="page voucher-detail-page">
    <div class="page-head no-print">
      <div>
        <h2 class="ph-title"><el-icon><Document /></el-icon>凭证详情</h2>
        <div class="ph-desc">
          记账凭证 {{ voucher.voucher_code || '' }} · 只读查看，可按凭证样式打印归档
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Back" @click="goBack">返回</el-button>
        <el-button :icon="Printer" @click="onPrint">打印凭证</el-button>
        <el-button v-if="voucher.status === '已退回'" type="warning" :icon="EditPen"
                   v-permission="'reimburse:voucher:make'" @click="goEdit">修改凭证</el-button>
      </div>
    </div>

    <div v-loading="loading" class="vd-body">
      <div class="vd-grid">
        <!-- ============ 左侧：凭证主体（打印区域） ============ -->
        <div class="vd-main">
          <div id="voucher-print-area" class="voucher-sheet">
            <h1 class="vs-title">记 账 凭 证</h1>

            <!-- 凭证头 -->
            <div class="vs-meta">
              <div class="vs-meta-left">
                <span class="vs-label">凭证字号</span>
                <span class="vs-code">{{ voucher.voucher_word || '记' }}-{{ voucher.period }}-{{ paddedNo }}</span>
              </div>
              <div class="vs-meta-center">
                <span class="vs-label">日期</span>
                <span class="vs-val">{{ voucher.voucher_date || '—' }}</span>
              </div>
              <div class="vs-meta-right">
                <span class="vs-label">附单据</span>
                <span class="vs-val">{{ voucher.attachment_count || 0 }}</span>
                <span class="vs-label">张</span>
              </div>
            </div>

            <!-- 分录表 -->
            <table class="entry-table">
              <thead>
                <tr>
                  <th class="col-idx">序号</th>
                  <th class="col-summary">摘 要</th>
                  <th class="col-subject">会计科目</th>
                  <th class="col-money">借方金额</th>
                  <th class="col-money">贷方金额</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, idx) in entries" :key="row.id || idx">
                  <td class="col-idx">{{ idx + 1 }}</td>
                  <td class="col-summary">{{ row.summary || '—' }}</td>
                  <td class="col-subject">
                    <span class="subj-code">{{ row.subject_code }}</span>
                    <span class="subj-name">{{ row.subject_name }}</span>
                  </td>
                  <td class="col-money num">{{ Number(row.debit_amount) ? fmtAmount(row.debit_amount) : '' }}</td>
                  <td class="col-money num">{{ Number(row.credit_amount) ? fmtAmount(row.credit_amount) : '' }}</td>
                </tr>
                <tr v-if="!entries.length">
                  <td colspan="5" class="empty-cell">暂无分录</td>
                </tr>
                <!-- 合计行 -->
                <tr class="total-row">
                  <td class="col-idx" />
                  <td class="col-summary total-label">合计：{{ moneyToChinese(totalDebit) }}</td>
                  <td class="col-subject" />
                  <td class="col-money total-num">{{ fmtAmount(totalDebit) }}</td>
                  <td class="col-money total-num">{{ fmtAmount(totalCredit) }}</td>
                </tr>
              </tbody>
            </table>

            <!-- 签字栏 -->
            <div class="vs-footer">
              <div class="vf-item"><span class="vf-l">制单人</span><span class="vf-v">{{ voucher.maker || '—' }}</span></div>
              <div class="vf-item"><span class="vf-l">复核人</span><span class="vf-v">{{ voucher.reviewer || '（未复核）' }}</span></div>
              <div class="vf-item"><span class="vf-l">复核时间</span><span class="vf-v">{{ voucher.reviewed_at ? fmtTime(voucher.reviewed_at) : '—' }}</span></div>
              <div class="vf-item"><span class="vf-l">状态</span>
                <el-tag :type="VOUCHER_STATUS_TYPE[voucher.status] || 'info'" size="small" class="no-print">{{ voucher.status }}</el-tag>
                <span class="print-only">{{ voucher.status }}</span>
              </div>
            </div>

            <!-- 复核意见 -->
            <div v-if="voucher.review_comment" class="review-note">
              <span class="rn-l">复核意见</span>
              <span class="rn-v">{{ voucher.review_comment }}</span>
            </div>
          </div>
        </div>

        <!-- ============ 右侧：关联信息（不打印） ============ -->
        <div class="vd-side no-print">
          <!-- 报销单 -->
          <el-card shadow="never" class="side-card">
            <template #header><div class="side-head"><span class="side-title">关联报销单</span></div></template>
            <div v-if="bill.id" class="info-list">
              <div class="il-row"><span class="il-l">报销单号</span>
                <el-button link type="primary" class="il-link" @click="goBill">{{ bill.bill_no }}</el-button>
              </div>
              <div class="il-row"><span class="il-l">报销人</span><span class="il-v">{{ bill.employee_name || '—' }}</span></div>
              <div class="il-row"><span class="il-l">费用类型</span><span class="il-v">{{ bill.expense_type_name || '—' }}</span></div>
              <div class="il-row"><span class="il-l">报销金额</span><span class="il-v amount">¥ {{ fmtMoney(bill.amount) }}</span></div>
              <div class="il-row"><span class="il-l">结算方式</span><span class="il-v">{{ bill.settlement_method_name || '—' }}</span></div>
              <div class="il-row"><span class="il-l">事由</span><span class="il-v">{{ bill.reason || '—' }}</span></div>
            </div>
            <div v-else class="side-empty">未关联报销单</div>
          </el-card>

          <!-- 合规判读结论 -->
          <el-card shadow="never" class="side-card">
            <template #header>
              <div class="side-head">
                <span class="side-title">合规判读结论</span>
                <el-tag v-if="check.overall_result" :type="RESULT_TYPE[check.overall_result] || 'info'" size="small">
                  {{ check.overall_result }}
                </el-tag>
              </div>
            </template>
            <div v-if="bill.override_flag" class="override-box">
              <div class="ob-head"><el-icon><WarningFilled /></el-icon>本单经人工覆盖判定</div>
              <div class="ob-line">覆盖人：<b>{{ bill.override_by || '—' }}</b></div>
              <div class="ob-line">覆盖理由：<b>{{ bill.override_reason || '—' }}</b></div>
            </div>
            <div v-if="issueSummary.length" class="issue-list">
              <div v-for="(it, i) in issueSummary" :key="i" class="il-item" :class="it.cls">
                <span class="il-code">{{ it.rule_code }}</span>
                <span class="il-text">{{ it.check_item }}：{{ it.result }}</span>
              </div>
            </div>
            <div v-else-if="check.id" class="side-empty ok">判读无不合规 / 需关注项</div>
            <div v-else class="side-empty">暂无判读结论</div>
            <el-button v-if="bill.id" link type="primary" class="side-more" @click="goCompliance">查看完整判读结果</el-button>
          </el-card>

          <!-- AI 制证说明 -->
          <el-card shadow="never" class="side-card">
            <template #header>
              <div class="side-head"><span class="side-title">AI 制证说明</span>
                <el-tag v-if="voucher.ai_model" size="small" effect="plain">{{ voucher.ai_model }}</el-tag>
              </div>
            </template>
            <div v-if="voucher.ai_explanation" class="ai-block">
              <div class="ai-label">分录说明</div>
              <div class="ai-text">{{ voucher.ai_explanation }}</div>
            </div>
            <div v-if="voucher.ai_tax_treatment" class="ai-block">
              <div class="ai-label">税务处理</div>
              <div class="ai-text tax">{{ voucher.ai_tax_treatment }}</div>
            </div>
            <div v-if="!voucher.ai_explanation && !voucher.ai_tax_treatment" class="side-empty">暂无 AI 说明</div>
          </el-card>

          <!-- 审计轨迹 -->
          <el-card shadow="never" class="side-card">
            <template #header><div class="side-head"><span class="side-title">审计轨迹</span></div></template>
            <el-timeline v-if="logs.length" class="log-timeline">
              <el-timeline-item v-for="(l, i) in logs" :key="i" :timestamp="fmtTime(l.created_at)" placement="top" size="normal">
                <div class="log-item">
                  <span class="log-user">{{ l.username }}</span>
                  <span class="log-action">{{ l.action }}</span>
                  <div v-if="l.detail" class="log-detail">{{ l.detail }}</div>
                </div>
              </el-timeline-item>
            </el-timeline>
            <div v-else class="side-empty">暂无审计记录</div>
          </el-card>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Document, Back, Printer, EditPen, WarningFilled
} from '@element-plus/icons-vue'
import { voucherApi } from '@/api/voucher'
import {
  VOUCHER_STATUS_TYPE, RESULT_TYPE, fmtMoney, fmtAmount, fmtTime, moneyToChinese
} from './constants'

const route = useRoute()
const router = useRouter()
const voucherId = computed(() => route.params.id)

const loading = ref(false)
const voucher = reactive({})
const entries = ref([])
const bill = reactive({})
const check = reactive({ issues: [] })
const logs = ref([])

const paddedNo = computed(() => String(voucher.voucher_no || 0).padStart(4, '0'))
const cents = (v) => Math.round((Number(v) || 0) * 100)
const totalDebit = computed(() => entries.value.reduce((s, r) => s + cents(r.debit_amount), 0) / 100)
const totalCredit = computed(() => entries.value.reduce((s, r) => s + cents(r.credit_amount), 0) / 100)

const issueSummary = computed(() => (check.issues || [])
  .filter((i) => ['不合规', '需关注'].includes(i.result))
  .slice(0, 6)
  .map((i) => ({
    rule_code: i.rule_code,
    check_item: i.check_item,
    result: i.result,
    cls: i.result === '不合规' ? 'err' : 'warn'
  })))

async function load() {
  loading.value = true
  try {
    const d = await voucherApi.detail(voucherId.value)
    Object.keys(voucher).forEach((k) => delete voucher[k])
    Object.assign(voucher, {
      id: d.id, voucher_code: d.voucher_code, voucher_word: d.voucher_word, period: d.period,
      voucher_no: d.voucher_no, voucher_date: d.voucher_date, attachment_count: d.attachment_count,
      total_debit: d.total_debit, total_credit: d.total_credit, status: d.status,
      maker: d.maker, reviewer: d.reviewer, reviewed_at: d.reviewed_at, review_comment: d.review_comment,
      ai_explanation: d.ai_explanation, ai_tax_treatment: d.ai_tax_treatment, ai_model: d.ai_model
    })
    entries.value = d.entries || []
    if (d.bill) {
      Object.assign(bill, {
        id: d.bill.id, bill_no: d.bill.bill_no, employee_name: d.bill.employee_name,
        expense_type_name: d.bill.expense_type_name, amount: d.bill.amount, reason: d.bill.reason,
        settlement_method_name: d.bill.settlement_method_name,
        override_flag: d.bill.override_flag, override_by: d.bill.override_by, override_reason: d.bill.override_reason
      })
    }
    if (d.check) {
      Object.assign(check, {
        id: d.check.id, overall_result: d.check.overall_result, issues: d.check.issues || []
      })
    }
    logs.value = d.logs || []
  } finally {
    loading.value = false
  }
}

// ---- 打印：只打印凭证区域（@media print 控制） ----
function onPrint() {
  window.print()
}

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push('/reimburse/voucher/list')
}
function goEdit() { router.push(`/rmb/voucher/${voucherId.value}/edit`) }
function goBill() { if (bill.id) router.push(`/rmb/bill/${bill.id}`) }
function goCompliance() { if (bill.id) router.push(`/rmb/compliance/${bill.id}`) }

onMounted(load)
</script>

<style scoped>
.vd-body { display: flex; flex-direction: column; min-height: 0; }
.vd-grid { display: grid; grid-template-columns: minmax(0, 1fr) 322px; gap: 12px; align-items: start; }
.vd-main { min-width: 0; }
.vd-side { display: flex; flex-direction: column; gap: 12px; }

/* ---------- 凭证纸张（与编辑页同款版式） ---------- */
.voucher-sheet {
  background: #fff; border: 1px solid var(--border); border-radius: var(--radius);
  padding: 20px 22px 16px; box-shadow: var(--shadow-sm);
}
.vs-title {
  margin: 0 0 14px; text-align: center; font-size: 24px; font-weight: 700; letter-spacing: 8px;
  color: #1f2937; padding-bottom: 7px; position: relative;
}
.vs-title::after {
  content: ''; position: absolute; left: 50%; transform: translateX(-50%); bottom: 0;
  width: 190px; height: 3px; border-top: 2px solid #1f2937; border-bottom: 1px solid #1f2937;
}
.vs-meta {
  display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr) minmax(0, 0.8fr);
  align-items: center; gap: 10px; margin-bottom: 10px; font-size: 13px;
}
.vs-meta-left, .vs-meta-center, .vs-meta-right { display: flex; align-items: center; gap: 5px; }
.vs-meta-right { justify-content: flex-end; }
.vs-label { color: var(--text-2); white-space: nowrap; }
.vs-code, .vs-val { font-weight: 700; color: var(--text-1); font-family: ui-monospace, Menlo, Consolas, monospace; }

.entry-table { width: 100%; border-collapse: collapse; table-layout: fixed; border: 2px solid #1f2937; }
.entry-table th {
  background: #f4f6fa; border: 1px solid #9aa4b2; padding: 7px 6px;
  font-size: 12.5px; font-weight: 700; color: var(--text-1); text-align: center;
}
.entry-table td { border: 1px solid #c3cad6; padding: 7px 8px; vertical-align: middle; font-size: 13px; }
.col-idx { width: 52px; text-align: center; color: var(--text-2); }
.col-summary { width: 34%; }
.col-subject { width: 26%; }
.col-money { width: 20%; }
.num { text-align: right; font-variant-numeric: tabular-nums; font-family: ui-monospace, Menlo, Consolas, monospace; }
.subj-code { font-family: ui-monospace, Menlo, Consolas, monospace; color: var(--text-2); margin-right: 6px; }
.subj-name { color: var(--text-1); }
.empty-cell { text-align: center; color: var(--text-3); padding: 20px 0; }
.total-row td { border-top: 2px solid #1f2937; background: #fafbfc; height: 42px; }
.total-label { font-weight: 700; color: var(--text-1); }
.total-num { text-align: right; font-weight: 700; color: #1f2937; font-variant-numeric: tabular-nums; font-family: ui-monospace, Menlo, Consolas, monospace; }

.vs-footer {
  display: flex; align-items: center; gap: 26px; flex-wrap: wrap;
  margin-top: 16px; padding-top: 12px; border-top: 1px dashed var(--border); font-size: 13px;
}
.vf-item { display: flex; align-items: center; gap: 6px; }
.vf-l { color: var(--text-3); }
.vf-v { color: var(--text-1); font-weight: 600; }
.review-note { margin-top: 10px; padding: 8px 10px; background: #fdf6ec; border-radius: 6px; font-size: 12.5px; line-height: 1.6; }
.rn-l { color: var(--text-3); margin-right: 8px; }
.rn-v { color: #b88230; }
.print-only { display: none; }

/* ---------- 右侧 ---------- */
.side-card :deep(.el-card__body) { padding: 12px 14px; }
.side-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.side-title { font-size: 13px; font-weight: 700; color: var(--text-1); }
.side-empty { font-size: 12px; color: var(--text-3); padding: 6px 0; line-height: 1.6; }
.side-empty.ok { color: #529b2e; }
.side-more { margin-top: 6px; padding: 0; }
.info-list { display: flex; flex-direction: column; gap: 6px; }
.il-row { display: flex; gap: 8px; font-size: 12px; line-height: 1.6; }
.il-l { flex: 0 0 62px; color: var(--text-3); }
.il-v { color: var(--text-1); word-break: break-all; }
.il-v.amount { color: #c45656; font-weight: 700; }
.il-link { padding: 0; height: auto; font-weight: 600; }
.override-box { background: #fef0f0; border: 1px solid #fbc4c4; border-radius: 7px; padding: 9px 10px; margin-bottom: 9px; }
.ob-head { display: flex; align-items: center; gap: 5px; font-size: 12.5px; font-weight: 700; color: #c45656; margin-bottom: 5px; }
.ob-line { font-size: 12px; line-height: 1.65; color: #c45656; word-break: break-all; }
.issue-list { display: flex; flex-direction: column; gap: 4px; }
.il-item { display: flex; gap: 7px; font-size: 12px; line-height: 1.6; padding: 4px 7px; border-radius: 5px; }
.il-item.err { background: #fef0f0; color: #c45656; }
.il-item.warn { background: #fdf6ec; color: #b88230; }
.il-code { flex: 0 0 auto; font-family: ui-monospace, Menlo, Consolas, monospace; font-weight: 700; }
.il-text { word-break: break-all; }
.ai-block + .ai-block { margin-top: 10px; }
.ai-label { font-size: 12px; font-weight: 600; color: var(--brand-dark); margin-bottom: 4px; }
.ai-text { font-size: 12.5px; line-height: 1.75; color: var(--text-2); white-space: pre-wrap; }
.ai-text.tax { color: #8b5cf6; }
.log-timeline { padding-left: 2px; }
.log-timeline :deep(.el-timeline-item__timestamp) { font-size: 11px; color: var(--text-3); }
.log-item { font-size: 12px; line-height: 1.6; }
.log-user { font-weight: 600; color: var(--text-1); margin-right: 6px; }
.log-action { color: var(--text-2); }
.log-detail { margin-top: 3px; font-size: 11px; color: var(--text-3); word-break: break-all; }

@media (max-width: 1200px) {
  .vd-grid { grid-template-columns: minmax(0, 1fr); }
}

/* ==========================================================
   打印样式：只输出凭证区域，隐藏侧栏与所有操作控件。
   用 visibility 方案（而非 display:none）以保留祖先布局，
   再让凭证纸张绝对定位铺满页面，避免打印出空白页。
   ========================================================== */
@media print {
  :global(body) { background: #fff !important; }
  .no-print { display: none !important; }
  .print-only { display: inline !important; }
  .vd-grid { display: block; }
  .vd-side { display: none !important; }
  /* 打印时隐藏布局的侧边栏与顶栏，只留凭证纸张（layout 不允许改，故用 :global 覆盖） */
  :global(.layout > .aside),
  :global(.layout .header),
  :global(.layout .main) { padding: 0 !important; }
  :global(.layout > .aside),
  :global(.layout .header) { display: none !important; }
  :global(.layout),
  :global(.layout .main) { height: auto !important; }
  :global(.page) { height: auto !important; gap: 0 !important; }
  .voucher-sheet {
    border: 0 !important; border-radius: 0 !important; box-shadow: none !important;
    padding: 0 !important; width: 100%;
  }
  .entry-table { border-color: #000; }
  .entry-table th { background: #f2f2f2 !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .entry-table td, .entry-table th { border-color: #000; }
  .total-row td { background: #f7f7f7 !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  tr { page-break-inside: avoid; break-inside: avoid; }
  thead { display: table-header-group; }
  @page { size: A4 landscape; margin: 12mm; }
}
</style>
