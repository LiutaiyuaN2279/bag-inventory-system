<template>
  <div class="page voucher-edit-page">
    <!-- 页头 -->
    <div class="page-head no-print">
      <div>
        <h2 class="ph-title"><el-icon><Tickets /></el-icon>{{ isEdit ? '修改记账凭证' : 'AI 制证' }}</h2>
        <div class="ph-desc">
          根据报销单与合规判读结论由 AI 生成会计分录，程序校验通过后方可保存；凭证号于保存时由系统取号
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Back" @click="goBack">返回</el-button>
        <el-button :icon="MagicStick" :loading="drafting" @click="onDraft">
          让 AI 重新生成
        </el-button>
        <el-button type="primary" :icon="Check" :loading="saving" :disabled="hasErrors" @click="onSave">
          确认保存
        </el-button>
      </div>
    </div>

    <div v-loading="loading" element-loading-text="加载凭证……" class="ve-body">
      <!-- AI 生成中 -->
      <div v-if="drafting" class="drafting-box no-print">
        <el-progress :percentage="100" :indeterminate="true" :duration="3" :show-text="false" :stroke-width="6" />
        <div class="drafting-text"><el-icon class="spin"><Loading /></el-icon>AI 正在生成会计凭证，约 20～120 秒……</div>
        <div class="drafting-sub">将结合报销信息、票据与最近一次合规判读结论生成借贷分录</div>
      </div>

      <div v-else class="ve-grid">
        <!-- ================= 左：凭证主体 ================= -->
        <div class="ve-main">
          <!-- 记账凭证 -->
          <div class="voucher-sheet">
            <!-- 标题 -->
            <h1 class="vs-title">记 账 凭 证</h1>

            <!-- 凭证字号 / 日期 / 附单据 -->
            <div class="vs-meta">
              <div class="vs-meta-left">
                <span class="vs-label">凭证字号</span>
                <el-select v-model="header.voucher_word" size="small" class="word-select">
                  <el-option v-for="w in VOUCHER_WORDS" :key="w" :label="w" :value="w" />
                </el-select>
                <span class="vs-dash">-</span>
                <span class="vs-period">{{ header.period }}</span>
                <span class="vs-dash">-</span>
                <span class="vs-no">{{ paddedNo }}</span>
                <el-tooltip content="凭证号在保存时由系统按期间顺序取号确定" placement="top">
                  <span class="vs-no-tip">（保存时确定）</span>
                </el-tooltip>
              </div>
              <div class="vs-meta-center">
                <span class="vs-label">日期</span>
                <el-date-picker v-model="header.voucher_date" type="date" value-format="YYYY-MM-DD"
                                size="small" class="date-picker" />
              </div>
              <div class="vs-meta-right">
                <span class="vs-label">附单据</span>
                <el-input-number v-model="header.attachment_count" :min="0" :precision="0" :controls="false"
                                 size="small" class="attach-input" />
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
                  <th class="col-op no-print">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, idx) in entries" :key="row._key" class="entry-row">
                  <td class="col-idx">{{ idx + 1 }}</td>
                  <td class="col-summary">
                    <el-input v-model="row.summary" size="small" maxlength="40" placeholder="摘要（不超 40 字）"
                              class="cell-input" @change="markDirty" />
                  </td>
                  <td class="col-subject">
                    <!-- 有科目清单时用可搜索下拉，否则降级为「编码 + 名称」手工输入 -->
                    <el-select v-if="subjects.length" v-model="row.subject_code" size="small" filterable clearable
                               placeholder="输入编码或名称搜索" class="cell-input"
                               @change="(v) => onSubjectChange(row, v)">
                      <el-option v-for="s in subjects" :key="s.code" :label="`${s.code} ${s.full_name || s.name}`" :value="s.code" />
                    </el-select>
                    <div v-else class="subject-manual">
                      <el-input v-model="row.subject_code" size="small" placeholder="科目编码" style="width: 96px" @change="markDirty" />
                      <el-input v-model="row.subject_name" size="small" placeholder="科目全称" style="flex: 1" @change="markDirty" />
                    </div>
                  </td>
                  <td class="col-money">
                    <el-input v-model="row._debit" size="small" class="cell-input money-input" placeholder="0.00"
                              @input="onDebitInput(row)" @blur="formatMoney(row, 'debit')" />
                  </td>
                  <td class="col-money">
                    <el-input v-model="row._credit" size="small" class="cell-input money-input" placeholder="0.00"
                              @input="onCreditInput(row)" @blur="formatMoney(row, 'credit')" />
                  </td>
                  <td class="col-op no-print">
                    <el-button link type="danger" :icon="Delete" :disabled="entries.length <= 1"
                               @click="removeEntry(idx)" />
                  </td>
                </tr>
                <!-- 空行补位：保持凭证表格版式（与手工凭证一致） -->
                <tr v-for="n in emptyRows" :key="`empty-${n}`" class="empty-row">
                  <td class="col-idx">{{ entries.length + n }}</td>
                  <td class="col-summary" />
                  <td class="col-subject" />
                  <td class="col-money" />
                  <td class="col-money" />
                  <td class="col-op no-print"><el-button link type="primary" :icon="Plus" @click="addEntry" /></td>
                </tr>
                <!-- 合计行 -->
                <tr class="total-row" :class="{ unbalanced: !balanced }">
                  <td class="col-idx" />
                  <td class="col-summary total-label">
                    合计：{{ moneyToChinese(totalDebit) }}
                  </td>
                  <td class="col-subject" />
                  <td class="col-money total-num">{{ fmtAmount(totalDebit) }}</td>
                  <td class="col-money total-num">{{ fmtAmount(totalCredit) }}</td>
                  <td class="col-op no-print" />
                </tr>
              </tbody>
            </table>

            <!-- 借贷平衡提示 -->
            <div class="balance-bar" :class="balanced ? 'ok' : 'bad'">
              <template v-if="balanced">
                <el-icon><CircleCheck /></el-icon>
                <span>借贷平衡 · 合计 {{ fmtMoney(totalDebit) }} 元（{{ moneyToChinese(totalDebit) }}）</span>
              </template>
              <template v-else>
                <el-icon><WarningFilled /></el-icon>
                <span>
                  借贷不平衡 · 借方 {{ fmtMoney(totalDebit) }}，贷方 {{ fmtMoney(totalCredit) }}，
                  差额 <b>{{ fmtMoney(Math.abs(totalDebit - totalCredit)) }}</b> 元
                </span>
              </template>
            </div>

            <!-- 新增分录 -->
            <div class="add-row no-print">
              <el-button type="primary" plain :icon="Plus" @click="addEntry">新增分录</el-button>
              <span class="add-hint">某行填了借方金额后贷方自动清空，反之亦然；金额失焦自动格式化为两位小数</span>
            </div>

            <!-- 凭证底部：制单人 / 复核人 / 关联报销单 -->
            <div class="vs-footer">
              <div class="vf-item"><span class="vf-l">制单人</span><span class="vf-v">{{ makerName }}</span></div>
              <div class="vf-item"><span class="vf-l">复核人</span><span class="vf-v">{{ reviewerName || '（待复核）' }}</span></div>
              <div class="vf-item">
                <span class="vf-l">关联报销单</span>
                <el-button v-if="bill.id" link type="primary" class="vf-link" @click="goBill">
                  {{ bill.bill_no }}
                </el-button>
                <span v-else class="vf-v">—</span>
              </div>
            </div>
          </div>
        </div>

        <!-- ================= 右：三个面板 ================= -->
        <div class="ve-side no-print">
          <!-- (1) AI 制证说明 -->
          <el-card shadow="never" class="side-card">
            <template #header>
              <div class="side-head">
                <span class="side-title"><el-icon><MagicStick /></el-icon>AI 制证说明</span>
                <el-tag v-if="aiMeta.model" size="small" effect="plain">{{ aiMeta.model }}</el-tag>
              </div>
            </template>
            <div v-if="aiMeta.explanation" class="ai-block">
              <div class="ai-label">分录说明</div>
              <div class="ai-text">{{ aiMeta.explanation }}</div>
            </div>
            <div v-if="aiMeta.tax_treatment" class="ai-block">
              <div class="ai-label">税务处理</div>
              <div class="ai-text tax">{{ aiMeta.tax_treatment }}</div>
            </div>
            <div v-if="!aiMeta.explanation && !aiMeta.tax_treatment" class="side-empty">
              暂无 AI 说明{{ isEdit ? '（该凭证为手工录入）' : '' }}
            </div>
            <div v-if="aiMeta.model || aiMeta.elapsed" class="ai-meta">
              <span v-if="aiMeta.model">模型 {{ aiMeta.model }}</span>
              <span v-if="aiMeta.elapsed">耗时 {{ Number(aiMeta.elapsed).toFixed(1) }} 秒</span>
            </div>
          </el-card>

          <!-- (2) 程序校验结果 -->
          <el-card shadow="never" class="side-card">
            <template #header>
              <div class="side-head">
                <span class="side-title"><el-icon><Stamp /></el-icon>程序校验结果</span>
                <el-button link type="primary" size="small" :loading="validating" @click="onValidate">重新校验</el-button>
              </div>
            </template>
            <div v-if="validateState === 'idle'" class="side-empty">尚未校验，修改分录后可点「重新校验」</div>
            <template v-else>
              <div class="check-sum">
                <span class="cs-item err"><b>{{ errors.length }}</b> 错误</span>
                <span class="cs-item warn"><b>{{ warnings.length }}</b> 告警</span>
                <span class="cs-time" v-if="validateAt">校验于 {{ validateAt }}</span>
              </div>
              <div v-if="errors.length" class="msg-group">
                <div class="mg-title err"><el-icon><CircleClose /></el-icon>错误（须修正后才能保存）</div>
                <div v-for="(e, i) in errors" :key="`e${i}`" class="msg-item err">{{ e }}</div>
              </div>
              <div v-if="warnings.length" class="msg-group">
                <div class="mg-title warn"><el-icon><Warning /></el-icon>告警（不影响保存，请复核时留意）</div>
                <div v-for="(w, i) in warnings" :key="`w${i}`" class="msg-item warn">{{ w }}</div>
              </div>
              <div v-if="!errors.length && !warnings.length" class="check-ok">
                <el-icon><CircleCheck /></el-icon><span>校验通过，借贷平衡且科目有效</span>
              </div>
            </template>
          </el-card>

          <!-- (3) 合规判读结论 -->
          <el-card shadow="never" class="side-card">
            <template #header>
              <div class="side-head">
                <span class="side-title"><el-icon><CircleCheck /></el-icon>合规判读结论</span>
                <el-tag v-if="check.overall_result" :type="RESULT_TYPE[check.overall_result] || 'info'" size="small">
                  {{ check.overall_result }}
                </el-tag>
              </div>
            </template>
            <div v-if="check.id || check.overall_result">
              <!-- 人工覆盖：红色醒目 -->
              <div v-if="bill.override_flag" class="override-box">
                <div class="ob-head"><el-icon><WarningFilled /></el-icon>本单经人工覆盖判定</div>
                <div class="ob-line">覆盖人：<b>{{ bill.override_by || '—' }}</b></div>
                <div class="ob-line">覆盖理由：<b>{{ bill.override_reason || '—' }}</b></div>
                <div class="ob-line orig">原判读结论：<b>{{ check.overall_result || '不合规' }}</b></div>
              </div>
              <div class="ck-line" v-if="check.checked_by">
                判读人 {{ check.checked_by }} · {{ fmtTime(check.checked_at) }}
              </div>
              <div class="ck-line" v-if="check.inconsistency_count">
                程序校验不一致 <b class="err-text">{{ check.inconsistency_count }}</b> 项
              </div>
              <div v-if="issueSummary.length" class="issue-mini">
                <div v-for="(it, i) in issueSummary" :key="i" class="im-item" :class="it.cls">
                  <span class="im-code">{{ it.rule_code }}</span>
                  <span class="im-text">{{ it.check_item }}：{{ it.result }}</span>
                </div>
              </div>
              <div v-else class="side-empty">无不合规 / 需关注项</div>
              <el-button v-if="bill.id" link type="primary" class="ck-more" @click="goCompliance">查看完整判读结果</el-button>
            </div>
            <div v-else class="side-empty">该报销单暂无判读结论</div>
          </el-card>

          <!-- 报销单摘要 -->
          <el-card v-if="bill.id" shadow="never" class="side-card">
            <template #header><div class="side-head"><span class="side-title"><el-icon><Document /></el-icon>报销单信息</span></div></template>
            <div class="bill-info">
              <div class="bi-row"><span class="bi-l">报销单号</span><span class="bi-v">{{ bill.bill_no }}</span></div>
              <div class="bi-row"><span class="bi-l">报销人</span><span class="bi-v">{{ bill.employee_name || '—' }}</span></div>
              <div class="bi-row"><span class="bi-l">费用类型</span><span class="bi-v">{{ bill.expense_type_name || '—' }}</span></div>
              <div class="bi-row"><span class="bi-l">报销金额</span><span class="bi-v amount">¥ {{ fmtMoney(bill.amount) }}</span></div>
              <div class="bi-row"><span class="bi-l">结算方式</span><span class="bi-v">{{ bill.settlement_method_name || '—' }}</span></div>
              <div class="bi-row"><span class="bi-l">事由</span><span class="bi-v">{{ bill.reason || '—' }}</span></div>
            </div>
          </el-card>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Tickets, Back, MagicStick, Check, Delete, Plus, Loading, CircleCheck, CircleClose,
  Warning, WarningFilled, Stamp, Document
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { voucherApi } from '@/api/voucher'
import { reimburseApi } from '@/api/reimburse'
import { RESULT_TYPE, fmtMoney, fmtAmount, fmtTime, moneyToChinese } from './constants'

const route = useRoute()
const router = useRouter()

/** 凭证字候选（通用记账凭证默认「记」） */
const VOUCHER_WORDS = ['记', '收', '付', '转']

// 路由形态：/rmb/voucher/new/:rid（AI 制证） | /rmb/voucher/:id/edit（修改退回凭证）
const newRid = computed(() => route.params.rid || null)
const editVoucherId = computed(() => route.params.id || null)
const isEdit = computed(() => !!editVoucherId.value)

const loading = ref(false)
const drafting = ref(false)
const validating = ref(false)
const saving = ref(false)
const validateState = ref('idle')  // idle | done
const validateAt = ref('')

const header = reactive({
  voucher_word: '记', period: currentPeriod(), voucher_no: 0, voucher_date: todayStr(), attachment_count: 0
})
const entries = ref([])
const aiMeta = reactive({ explanation: '', tax_treatment: '', model: '', elapsed: 0 })
const bill = reactive({})
const check = reactive({ issues: [] })
const errors = ref([])
const warnings = ref([])
const subjects = ref([])
const makerName = ref('')
const reviewerName = ref('')
const voucherCode = ref('')

let keySeed = 0
function currentPeriod() {
  const d = new Date()
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}`
}
function todayStr() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// ---- 派生：合计、平衡、大写、补位行 ----
const totalDebit = computed(() => sumCents(entries.value.map((e) => Number(e.debit_amount) || 0)))
const totalCredit = computed(() => sumCents(entries.value.map((e) => Number(e.credit_amount) || 0)))
function sumCents(list) {
  return list.reduce((s, v) => s + Math.round(v * 100), 0) / 100
}
const balanced = computed(() => Math.abs(totalDebit.value - totalCredit.value) < 0.005 && totalDebit.value > 0)
const hasErrors = computed(() => errors.value.length > 0 || !balanced.value)
const paddedNo = computed(() => String(header.voucher_no || 0).padStart(4, '0'))
/** 补位空行：至少显示到 5 行，保持凭证版式 */
const emptyRows = computed(() => Math.max(0, 5 - entries.value.length))

/** 判读问题摘要（不合规 + 需关注，最多 6 条） */
const issueSummary = computed(() => (check.issues || [])
  .filter((i) => ['不合规', '需关注'].includes(i.result))
  .slice(0, 6)
  .map((i) => ({
    rule_code: i.rule_code,
    check_item: i.check_item,
    result: i.result,
    cls: i.result === '不合规' ? 'err' : 'warn'
  })))

// ---- 分录行管理 ----
function newEntry(data = {}) {
  keySeed += 1
  const debit = toNum(data.debit_amount)
  const credit = toNum(data.credit_amount)
  return {
    _key: `e${keySeed}`,
    summary: data.summary || '',
    subject_code: data.subject_code || '',
    subject_name: data.subject_name || '',
    debit_amount: debit,
    credit_amount: credit,
    _debit: debit ? fmtAmount(debit) : '',
    _credit: credit ? fmtAmount(credit) : ''
  }
}

function toNum(v) {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

function addEntry() {
  entries.value.push(newEntry({ summary: entries.value[0]?.summary || '' }))
  markDirty()
}

function removeEntry(idx) {
  if (entries.value.length <= 1) return
  entries.value.splice(idx, 1)
  markDirty()
}

/** 借方输入：清空同行贷方 */
function onDebitInput(row) {
  const raw = String(row._debit ?? '').replace(/[^\d.-]/g, '')
  if (raw !== String(row._debit ?? '')) row._debit = raw
  if (raw && Number(raw) !== 0) {
    row._credit = ''
    row.credit_amount = 0
  }
  row.debit_amount = Number(raw) || 0
  markDirty()
}

/** 贷方输入：清空同行借方 */
function onCreditInput(row) {
  const raw = String(row._credit ?? '').replace(/[^\d.-]/g, '')
  if (raw !== String(row._credit ?? '')) row._credit = raw
  if (raw && Number(raw) !== 0) {
    row._debit = ''
    row.debit_amount = 0
  }
  row.credit_amount = Number(raw) || 0
  markDirty()
}

/** 失焦格式化两位小数 */
function formatMoney(row, side) {
  if (side === 'debit') {
    const n = Number(row._debit)
    row.debit_amount = Number.isFinite(n) ? n : 0
    row._debit = row.debit_amount ? fmtAmount(row.debit_amount) : ''
  } else {
    const n = Number(row._credit)
    row.credit_amount = Number.isFinite(n) ? n : 0
    row._credit = row.credit_amount ? fmtAmount(row.credit_amount) : ''
  }
}

/** 选中科目后回填科目全称 */
function onSubjectChange(row, code) {
  const s = subjects.value.find((x) => x.code === code)
  row.subject_name = s ? (s.full_name || s.name) : ''
  markDirty()
}

/** 分录变动后校验结果置为待重新校验（避免用旧结果误导） */
function markDirty() {
  if (validateState.value === 'done') validateState.value = 'stale'
}

// 监听合计变化：平衡状态变了就提示重新校验
watch(() => balanced.value, (v) => {
  if (!v && validateState.value === 'done') validateState.value = 'stale'
})

// ---- 数据加载 ----
async function loadSubjects() {
  try {
    const res = await voucherApi.subjects()
    const list = Array.isArray(res) ? res : (res?.list || [])
    // 只取末级且启用的科目（后端已过滤，这里再兜一层）
    subjects.value = list.filter((s) => s.is_leaf !== false && s.is_active !== false)
  } catch {
    subjects.value = []   // 降级：手工输入科目编码与名称
  }
}

/** AI 制证：调 /draft 生成草稿 */
async function onDraft(silent = false) {
  const rid = newRid.value || bill.id
  if (!rid) return ElMessage.warning('缺少报销单 ID，无法生成凭证')
  drafting.value = true
  errors.value = []
  warnings.value = []
  try {
    const res = await voucherApi.draft({ reimbursement_id: Number(rid) })
    applyDraft(res)
    ElMessage.success('AI 凭证草稿已生成，请核对分录')
  } catch {
    // 失败提示已由 request 拦截器给出
  } finally {
    drafting.value = false
  }
}

function applyDraft(res) {
  if (!res) return
  const h = res.header || {}
  header.voucher_word = h.voucher_word || '记'
  header.period = h.period || currentPeriod()
  header.voucher_no = Number(h.voucher_no || 0)
  header.voucher_date = h.voucher_date || todayStr()
  header.attachment_count = Number(h.attachment_count || 0)
  entries.value = (res.entries || []).map((e) => newEntry(e))
  if (!entries.value.length) entries.value = [newEntry()]
  aiMeta.explanation = res.explanation || ''
  aiMeta.tax_treatment = res.tax_treatment || ''
  aiMeta.model = res.model || ''
  aiMeta.elapsed = Number(res.elapsed || 0)
  errors.value = res.errors || []
  warnings.value = res.warnings || []
  validateState.value = 'done'
  validateAt.value = nowText()
}

function nowText() {
  const d = new Date()
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}

/** 加载报销单摘要 + 最近判读结论（草稿/详情接口不一定带全，这里补） */
async function loadBill(rid) {
  try {
    const d = await reimburseApi.detail(rid)
    Object.assign(bill, {
      id: d.id, bill_no: d.bill_no, employee_name: d.employee_name,
      expense_type_name: d.expense_type_name, amount: d.amount, reason: d.reason,
      settlement_method_name: d.settlement_method_name, status: d.status,
      override_flag: d.override_flag, override_by: d.override_by, override_reason: d.override_reason
    })
    if (d.latest_check) {
      Object.assign(check, d.latest_check)
      check.issues = d.latest_check.issues || []
    }
    // 制证前置条件提醒（最终由后端拦截，这里只做前端引导）
    if (d.override_flag) {
      ElMessage.warning('该报销单经人工覆盖判定，请复核凭证时重点核查覆盖依据')
    }
  } catch {
    // 报销单详情拉取失败不阻断制证
  }
}

/** 加载合规判读详情（补齐 issues） */
async function loadCheck(rid) {
  if (check.issues?.length) return
  try {
    const res = await complianceApiDetail(rid)
    if (res?.check) {
      Object.assign(check, {
        id: res.check.id, overall_result: res.check.overall_result,
        checked_by: res.check.checked_by, checked_at: res.check.checked_at,
        inconsistency_count: res.check.inconsistency_count,
        issues: res.check.issues || []
      })
    }
  } catch { /* 无判读结果时静默 */ }
}

// 动态引入避免与 compliance 页重复打包
async function complianceApiDetail(rid) {
  const mod = await import('@/api/compliance')
  return mod.complianceApi.detail(rid)
}

/** 修改模式：加载已有凭证 */
async function loadVoucher(id) {
  const d = await voucherApi.detail(id)
  header.voucher_word = d.voucher_word || '记'
  header.period = d.period || currentPeriod()
  header.voucher_no = Number(d.voucher_no || 0)
  header.voucher_date = d.voucher_date || todayStr()
  header.attachment_count = Number(d.attachment_count || 0)
  entries.value = (d.entries || []).map((e) => newEntry(e))
  if (!entries.value.length) entries.value = [newEntry()]
  aiMeta.explanation = d.ai_explanation || ''
  aiMeta.tax_treatment = d.ai_tax_treatment || ''
  aiMeta.model = d.ai_model || ''
  makerName.value = d.maker || ''
  reviewerName.value = d.reviewer || ''
  voucherCode.value = d.voucher_code || ''
  if (d.bill) {
    Object.assign(bill, {
      id: d.bill.id, bill_no: d.bill.bill_no, employee_name: d.bill.employee_name,
      expense_type_name: d.bill.expense_type_name, amount: d.bill.amount, reason: d.bill.reason,
      settlement_method_name: d.bill.settlement_method_name, status: d.bill.status,
      override_flag: d.bill.override_flag, override_by: d.bill.override_by, override_reason: d.bill.override_reason
    })
  }
  if (d.check) {
    Object.assign(check, {
      id: d.check.id, overall_result: d.check.overall_result, checked_by: d.check.checked_by,
      checked_at: d.check.checked_at, inconsistency_count: d.check.inconsistency_count,
      issues: d.check.issues || []
    })
  }
}

// ---- 校验 ----
function buildEntriesPayload() {
  return entries.value.map((e, i) => ({
    line_no: i + 1,
    summary: e.summary,
    subject_code: e.subject_code,
    subject_name: e.subject_name,
    debit_amount: Number(e.debit_amount) || 0,
    credit_amount: Number(e.credit_amount) || 0
  }))
}
function buildHeaderPayload() {
  return {
    voucher_word: header.voucher_word,
    period: header.period,
    voucher_no: Number(header.voucher_no) || 0,
    voucher_date: header.voucher_date,
    attachment_count: Number(header.attachment_count) || 0
  }
}

async function onValidate() {
  const rid = bill.id || newRid.value
  if (!rid) {
    // 无报销单（手工场景）时只做前端平衡校验
    errors.value = balanced.value ? [] : [`借贷不平衡：借方 ${fmtMoney(totalDebit.value)}，贷方 ${fmtMoney(totalCredit.value)}`]
    warnings.value = []
    validateState.value = 'done'
    validateAt.value = nowText()
    return
  }
  validating.value = true
  try {
    const res = await voucherApi.validate({
      reimbursement_id: Number(rid),
      header: buildHeaderPayload(),
      entries: buildEntriesPayload()
    })
    errors.value = res?.errors || []
    warnings.value = res?.warnings || []
    validateState.value = 'done'
    validateAt.value = nowText()
    ElMessage[errors.value.length ? 'warning' : 'success'](
      errors.value.length ? `校验发现 ${errors.value.length} 项错误` : '校验通过'
    )
  } finally {
    validating.value = false
  }
}

// ---- 保存 ----
async function onSave() {
  if (!balanced.value) return ElMessage.warning('借贷不平衡，无法保存')
  const emptySubject = entries.value.find((e) => !e.subject_code)
  if (emptySubject) return ElMessage.warning('存在未选择会计科目的分录')
  const zeroRow = entries.value.find((e) => !(Number(e.debit_amount) > 0) && !(Number(e.credit_amount) > 0))
  if (zeroRow) return ElMessage.warning('存在金额为空的分录，请补全或删除该行')

  try {
    await ElMessageBox.confirm('确认保存该凭证？保存后将提交复核', '保存凭证', {
      type: 'warning', confirmButtonText: '确认保存', cancelButtonText: '再检查一下'
    })
  } catch { return }

  saving.value = true
  try {
    const payload = {
      reimbursement_id: Number(newRid.value || bill.id),
      header: buildHeaderPayload(),
      entries: buildEntriesPayload(),
      ai_explanation: aiMeta.explanation,
      ai_tax_treatment: aiMeta.tax_treatment,
      ai_model: aiMeta.model
    }
    const res = isEdit.value
      ? await voucherApi.update(editVoucherId.value, payload)
      : await voucherApi.save(payload)
    ElMessage.success(`凭证保存成功${res?.voucher_code ? `：${res.voucher_code}` : ''}，已提交复核`)
    router.push(res?.id ? `/rmb/voucher/${res.id}` : '/reimburse/voucher/list')
  } finally {
    saving.value = false
  }
}

// ---- 跳转 ----
function goBack() {
  if (isEdit.value) router.back()
  else router.push('/reimburse/voucher/pending')
}
function goBill() { if (bill.id) router.push(`/rmb/bill/${bill.id}`) }
function goCompliance() { if (bill.id) router.push(`/rmb/compliance/${bill.id}`) }

onMounted(async () => {
  loading.value = true
  try {
    await loadSubjects()
    if (isEdit.value) {
      await loadVoucher(editVoucherId.value)
    } else if (newRid.value) {
      bill.id = Number(newRid.value)
      await Promise.all([loadBill(newRid.value), loadCheck(newRid.value)])
      await onDraft()   // 进入即自动生成草稿
    } else {
      entries.value = [newEntry(), newEntry()]
    }
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
/* ==========================================================
   记账凭证样式：仿财务软件（标题居中双下划线、表格边框、
   金额右对齐等宽数字），打印时隐藏所有操作控件。
   ========================================================== */
.ve-body { display: flex; flex-direction: column; gap: 12px; min-height: 0; }

.drafting-box {
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px;
  padding: 70px 24px; background: #fff; border: 1px solid var(--border); border-radius: var(--radius);
}
.drafting-box :deep(.el-progress) { width: 58%; }
.drafting-text { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; color: var(--brand-dark); }
.drafting-sub { font-size: 12px; color: var(--text-3); }
.spin { animation: spin 1.2s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.ve-grid { display: grid; grid-template-columns: minmax(0, 1fr) 322px; gap: 12px; align-items: start; }
.ve-main { min-width: 0; }
.ve-side { display: flex; flex-direction: column; gap: 12px; position: sticky; top: 0; }

/* ---------- 凭证纸张 ---------- */
.voucher-sheet {
  background: #fff; border: 1px solid var(--border); border-radius: var(--radius);
  padding: 20px 22px 16px; box-shadow: var(--shadow-sm);
}
/* 标题：居中 + 双下划线（用 border-bottom + 伪元素双层线还原纸质凭证） */
.vs-title {
  margin: 0 0 14px; text-align: center; font-size: 24px; font-weight: 700; letter-spacing: 8px;
  color: #1f2937; padding-bottom: 7px; position: relative;
}
.vs-title::after {
  content: ''; position: absolute; left: 50%; transform: translateX(-50%); bottom: 0;
  width: 190px; height: 3px; border-top: 2px solid #1f2937; border-bottom: 1px solid #1f2937;
}

/* 凭证字号 / 日期 / 附单据 */
.vs-meta {
  display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr) minmax(0, 0.8fr);
  align-items: center; gap: 10px; margin-bottom: 10px; font-size: 13px;
}
.vs-meta-left, .vs-meta-center, .vs-meta-right { display: flex; align-items: center; gap: 5px; }
.vs-meta-right { justify-content: flex-end; }
.vs-label { color: var(--text-2); white-space: nowrap; }
.vs-word, .vs-period, .vs-no { font-weight: 700; color: var(--text-1); font-family: ui-monospace, Menlo, Consolas, monospace; }
.vs-dash { color: var(--text-3); }
.vs-no-tip { font-size: 11px; color: var(--text-3); }
.word-select { width: 78px; }
.date-picker { width: 148px; }
.attach-input { width: 62px; }

/* ---------- 分录表 ---------- */
.entry-table {
  width: 100%; border-collapse: collapse; table-layout: fixed;
  border: 2px solid #1f2937;
}
.entry-table th {
  background: #f4f6fa; border: 1px solid #9aa4b2; padding: 7px 6px;
  font-size: 12.5px; font-weight: 700; color: var(--text-1); text-align: center;
}
.entry-table td {
  border: 1px solid #c3cad6; padding: 4px 6px; vertical-align: middle; font-size: 13px;
}
.col-idx { width: 52px; text-align: center; color: var(--text-2); }
.col-summary { width: 30%; }
.col-subject { width: 27%; }
.col-money { width: 17%; }
.col-op { width: 52px; text-align: center; }
.entry-row { height: 40px; }
.empty-row td { height: 34px; color: var(--text-3); }
.cell-input :deep(.el-input__wrapper) { box-shadow: none; background: transparent; padding: 0 4px; }
.cell-input :deep(.el-input__inner) { font-size: 13px; }
.cell-input :deep(.el-input__wrapper:hover) { box-shadow: 0 0 0 1px var(--el-color-primary-light-5) inset; }
.cell-input :deep(.el-input__wrapper.is-focus) { box-shadow: 0 0 0 1px var(--brand) inset; }
.subject-manual { display: flex; gap: 6px; }
.money-input :deep(.el-input__inner) {
  text-align: right; font-variant-numeric: tabular-nums;
  font-family: ui-monospace, Menlo, Consolas, monospace;
}

/* 合计行 */
.total-row td { border-top: 2px solid #1f2937; background: #fafbfc; height: 42px; }
.total-label { font-weight: 700; color: var(--text-1); }
.total-num {
  text-align: right; font-weight: 700; font-variant-numeric: tabular-nums;
  font-family: ui-monospace, Menlo, Consolas, monospace; color: #1f2937;
}
.total-row.unbalanced .total-num { color: #f56c6c; }

/* 平衡提示 */
.balance-bar {
  display: flex; align-items: center; gap: 7px; margin-top: 10px;
  padding: 8px 12px; border-radius: 7px; font-size: 13px;
}
.balance-bar.ok { background: #f0f9eb; color: #529b2e; }
.balance-bar.bad { background: #fef0f0; color: #c45656; }
.balance-bar b { font-variant-numeric: tabular-nums; }

.add-row { display: flex; align-items: center; gap: 12px; margin-top: 12px; }
.add-hint { font-size: 12px; color: var(--text-3); }

/* 凭证底部 */
.vs-footer {
  display: flex; align-items: center; gap: 28px; flex-wrap: wrap;
  margin-top: 16px; padding-top: 12px; border-top: 1px dashed var(--border); font-size: 13px;
}
.vf-item { display: flex; align-items: center; gap: 6px; }
.vf-l { color: var(--text-3); }
.vf-v { color: var(--text-1); font-weight: 600; }
.vf-link { font-weight: 600; }

/* ---------- 右侧面板 ---------- */
.side-card :deep(.el-card__body) { padding: 12px 14px; }
.side-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.side-title { display: flex; align-items: center; gap: 5px; font-size: 13px; font-weight: 700; color: var(--text-1); }
.side-empty { font-size: 12px; color: var(--text-3); padding: 8px 0; line-height: 1.6; }
.ai-block + .ai-block { margin-top: 10px; }
.ai-label { font-size: 12px; font-weight: 600; color: var(--brand-dark); margin-bottom: 4px; }
.ai-text { font-size: 12.5px; line-height: 1.75; color: var(--text-2); white-space: pre-wrap; }
.ai-text.tax { color: #8b5cf6; }
.ai-meta { display: flex; gap: 12px; margin-top: 10px; padding-top: 8px; border-top: 1px dashed var(--border); font-size: 11px; color: var(--text-3); }

.check-sum { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; font-size: 12px; color: var(--text-2); }
.cs-item b { font-size: 15px; font-variant-numeric: tabular-nums; }
.cs-item.err b { color: #f56c6c; }
.cs-item.warn b { color: #e6a23c; }
.cs-time { margin-left: auto; font-size: 11px; color: var(--text-3); }
.msg-group + .msg-group { margin-top: 10px; }
.mg-title { display: flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 700; margin-bottom: 5px; }
.mg-title.err { color: #c45656; }
.mg-title.warn { color: #b88230; }
.msg-item {
  font-size: 12px; line-height: 1.65; padding: 5px 8px; border-radius: 5px; margin-bottom: 4px;
  word-break: break-all;
}
.msg-item.err { background: #fef0f0; color: #c45656; }
.msg-item.warn { background: #fdf6ec; color: #b88230; }
.check-ok { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: #529b2e; padding: 6px 0; }

.override-box {
  background: #fef0f0; border: 1px solid #fbc4c4; border-radius: 7px;
  padding: 9px 10px; margin-bottom: 9px;
}
.ob-head { display: flex; align-items: center; gap: 5px; font-size: 12.5px; font-weight: 700; color: #c45656; margin-bottom: 5px; }
.ob-line { font-size: 12px; line-height: 1.65; color: #c45656; word-break: break-all; }
.ob-line.orig { margin-top: 3px; padding-top: 4px; border-top: 1px dashed #fbc4c4; opacity: .9; }
.ck-line { font-size: 12px; color: var(--text-3); line-height: 1.7; }
.err-text { color: #f56c6c; }
.issue-mini { margin-top: 8px; display: flex; flex-direction: column; gap: 4px; }
.im-item { display: flex; gap: 7px; font-size: 12px; line-height: 1.6; padding: 4px 7px; border-radius: 5px; }
.im-item.err { background: #fef0f0; color: #c45656; }
.im-item.warn { background: #fdf6ec; color: #b88230; }
.im-code { flex: 0 0 auto; font-family: ui-monospace, Menlo, Consolas, monospace; font-weight: 700; }
.im-text { word-break: break-all; }
.ck-more { margin-top: 8px; padding: 0; }

.bill-info { display: flex; flex-direction: column; gap: 6px; }
.bi-row { display: flex; gap: 8px; font-size: 12px; line-height: 1.6; }
.bi-l { flex: 0 0 62px; color: var(--text-3); }
.bi-v { color: var(--text-1); word-break: break-all; }
.bi-v.amount { color: #c45656; font-weight: 700; font-variant-numeric: tabular-nums; }

@media (max-width: 1200px) {
  .ve-grid { grid-template-columns: minmax(0, 1fr); }
  .ve-side { position: static; }
}
@media (max-width: 768px) {
  .vs-meta { grid-template-columns: minmax(0, 1fr); }
  .vs-meta-right { justify-content: flex-start; }
  .voucher-sheet { padding: 14px 12px; }
  .col-op { display: none; }
}
</style>
