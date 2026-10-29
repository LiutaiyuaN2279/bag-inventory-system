<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Finished /></el-icon>凭证复核</h2>
        <div class="ph-desc">
          复核制单员生成的记账凭证，重点核查人工覆盖与判读需关注的凭证 · 待复核 <b>{{ total }}</b> 张
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
        <el-tooltip v-if="blockingSelected.length" placement="bottom">
          <template #content>
            以下证人选中项经人工覆盖或判读需关注，不允许批量复核，请逐张复核：
            <br />{{ blockingSelected.map((r) => r.voucher_code).join('、') }}
          </template>
          <span><el-button type="primary" :icon="Finished" disabled>批量复核通过</el-button></span>
        </el-tooltip>
        <el-button v-else type="primary" :icon="Finished" :loading="batchLoading"
                   :disabled="!selectedIds.length" v-permission="'reimburse:voucher:review'"
                   @click="onBatchApprove">批量复核通过{{ selectedIds.length ? `（${selectedIds.length}）` : '' }}</el-button>
      </div>
    </div>

    <el-card shadow="never" class="card-fill">
      <!-- 统计条 -->
      <div class="stat-strip">
        <div class="stat-item">
          <div class="si-icon" style="background:#fff7e6;color:#e6a23c"><el-icon><Tickets /></el-icon></div>
          <div><div class="si-num">{{ total }}</div><div class="si-label">待复核凭证</div></div>
        </div>
        <div class="stat-item">
          <div class="si-icon" style="background:#fef0f0;color:#f56c6c"><el-icon><WarningFilled /></el-icon></div>
          <div><div class="si-num">{{ overrideCount }}</div><div class="si-label">人工覆盖（须逐张复核）</div></div>
        </div>
        <div class="stat-item">
          <div class="si-icon" style="background:#fdf6ec;color:#b88230"><el-icon><Warning /></el-icon></div>
          <div><div class="si-num">{{ concernCount }}</div><div class="si-label">判读需关注</div></div>
        </div>
        <div class="stat-item">
          <div class="si-icon" style="background:#f0f9eb;color:#529b2e"><el-icon><CircleCheck /></el-icon></div>
          <div><div class="si-num">{{ normalCount }}</div><div class="si-label">常规待复核</div></div>
        </div>
      </div>

      <div class="toolbar">
        <el-form :inline="true" :model="query" class="tb-left">
          <el-form-item label="期间">
            <el-date-picker v-model="query.period" type="month" value-format="YYYY-MM"
                            placeholder="选择期间" clearable style="width: 150px" @change="onSearch" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :icon="Search" @click="onSearch">查询</el-button>
            <el-button :icon="RefreshLeft" @click="onReset">重置</el-button>
          </el-form-item>
        </el-form>
        <div class="tb-right">
          <span class="sel-hint">已选 <b>{{ selectedIds.length }}</b> 张</span>
        </div>
      </div>

      <div class="table-wrap">
        <el-table :data="list" v-loading="loading" border stripe row-key="id" empty-text="暂无待复核凭证"
                  @selection-change="onSelectionChange">
          <el-table-column type="selection" width="50" align="center" :selectable="canSelect" reserve-selection />
          <el-table-column prop="voucher_code" label="凭证字号" width="150" fixed="left">
            <template #default="{ row }">
              <el-button link type="primary" class="code-btn" @click="openReview(row)">{{ row.voucher_code }}</el-button>
            </template>
          </el-table-column>
          <el-table-column prop="voucher_date" label="日期" width="112" align="center" />
          <el-table-column prop="summary" label="摘要" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">{{ row.summary || row.first_summary || '—' }}</template>
          </el-table-column>
          <el-table-column label="金额(元)" width="130" align="right" class-name="col-num">
            <template #default="{ row }"><b class="amount">{{ fmtMoney(row.total_debit ?? row.amount) }}</b></template>
          </el-table-column>
          <el-table-column prop="employee_name" label="报销人" width="100">
            <template #default="{ row }">{{ row.employee_name || row.bill?.employee_name || '—' }}</template>
          </el-table-column>
          <el-table-column prop="maker" label="制单人" width="100">
            <template #default="{ row }">{{ row.maker || '—' }}</template>
          </el-table-column>
          <el-table-column label="判读结论" width="112" align="center">
            <template #default="{ row }">
              <el-tag :type="RESULT_TYPE[row.compliance_result || row.bill?.compliance_result] || 'info'" size="small">
                {{ row.compliance_result || row.bill?.compliance_result || '未判读' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="人工覆盖" width="106" align="center">
            <template #default="{ row }">
              <el-tag v-if="isOverride(row)" type="danger" size="small" effect="dark">已覆盖</el-tag>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openReview(row)">复核</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="pager">
        <span class="hint">共 <b>{{ total }}</b> 条 · 第 {{ query.page }} / {{ pageCount }} 页</span>
        <el-pagination background layout="sizes, prev, pager, next" :total="total"
                       v-model:current-page="query.page" v-model:page-size="query.page_size"
                       :page-sizes="[10, 20, 50]" @current-change="fetchList" @size-change="fetchList" />
      </div>
    </el-card>

    <!-- ============ 复核详情弹窗 ============ -->
    <el-dialog v-model="dlg.visible" title="凭证复核" width="1080px" :close-on-click-modal="false" class="review-dlg"
               :destroy-on-close="true">
      <div v-loading="dlg.loading" class="rv-body">
        <template v-if="dlg.data">
          <!-- 人工覆盖红色横幅 -->
          <el-alert v-if="isOverride(dlg.data)" type="error" :closable="false" show-icon class="rv-alert"
                    title="本凭证对应的报销单经人工覆盖判定，不允许批量复核，须逐张核查覆盖依据">
            <template #default>
              <div class="ov-body">
                <div>覆盖人：<b>{{ dlg.data.bill?.override_by || dlg.data.override_by || '—' }}</b></div>
                <div>覆盖理由：<b class="ov-reason">{{ dlg.data.bill?.override_reason || dlg.data.override_reason || '—' }}</b></div>
                <div>原判读结论：<b>{{ dlg.data.check?.overall_result || '—' }}</b>
                  （覆盖后直接进入待制证，请确认覆盖依据充分）</div>
              </div>
            </template>
          </el-alert>

          <!-- 判读需关注黄色横幅 -->
          <el-alert v-else-if="isConcern(dlg.data)" type="warning" :closable="false" show-icon class="rv-alert"
                    title="本凭证对应的报销单判读结论为「需关注」，复核意见必填" />

          <!-- 只读凭证样式 -->
          <div class="rv-sheet">
            <h1 class="rv-title">记 账 凭 证</h1>
            <div class="rv-meta">
              <div><span class="rm-l">凭证字号</span><b class="rm-code">{{ dlg.data.voucher_code }}</b></div>
              <div><span class="rm-l">日期</span><b>{{ dlg.data.voucher_date || '—' }}</b></div>
              <div><span class="rm-l">附单据</span><b>{{ dlg.data.attachment_count || 0 }}</b> 张</div>
              <div><span class="rm-l">制单人</span><b>{{ dlg.data.maker || '—' }}</b></div>
            </div>
            <table class="rv-table">
              <thead>
                <tr>
                  <th class="t-idx">序号</th>
                  <th class="t-sum">摘 要</th>
                  <th class="t-subj">会计科目</th>
                  <th class="t-money">借方金额</th>
                  <th class="t-money">贷方金额</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(e, i) in dlg.data.entries || []" :key="e.id || i">
                  <td class="t-idx">{{ i + 1 }}</td>
                  <td>{{ e.summary || '—' }}</td>
                  <td>
                    <span class="subj-code">{{ e.subject_code }}</span>
                    <span class="subj-name">{{ e.subject_name }}</span>
                  </td>
                  <td class="t-money num">{{ Number(e.debit_amount) ? fmtAmount(e.debit_amount) : '' }}</td>
                  <td class="t-money num">{{ Number(e.credit_amount) ? fmtAmount(e.credit_amount) : '' }}</td>
                </tr>
                <tr class="rv-total">
                  <td class="t-idx" />
                  <td class="total-label">合计：{{ moneyToChinese(dlgTotalDebit) }}</td>
                  <td />
                  <td class="t-money total-num">{{ fmtAmount(dlgTotalDebit) }}</td>
                  <td class="t-money total-num">{{ fmtAmount(dlgTotalCredit) }}</td>
                </tr>
              </tbody>
            </table>
            <div class="rv-foot">
              <span>制单人：{{ dlg.data.maker || '—' }}</span>
              <span>复核人：{{ dlg.data.reviewer || '（待复核）' }}</span>
              <span>制单时间：{{ fmtTime(dlg.data.made_at) || '—' }}</span>
            </div>
          </div>

          <!-- 下方信息区：两列 -->
          <div class="rv-grid">
            <!-- 左：报销信息 + 票据 + 判读问题 -->
            <div class="rv-col">
              <el-card shadow="never" class="mini-card">
                <template #header><span class="mini-title">报销信息</span></template>
                <div class="info-list" v-if="dlg.data.bill">
                  <div class="il-row"><span class="il-l">报销单号</span>
                    <el-button link type="primary" class="il-link" @click="goBill(dlg.data.bill.id)">
                      {{ dlg.data.bill.bill_no }}
                    </el-button>
                  </div>
                  <div class="il-row"><span class="il-l">报销人</span><span class="il-v">{{ dlg.data.bill.employee_name || '—' }}</span></div>
                  <div class="il-row"><span class="il-l">部门</span><span class="il-v">{{ orDash(dlg.data.bill.department_name) }}</span></div>
                  <div class="il-row"><span class="il-l">费用类型</span><span class="il-v">{{ dlg.data.bill.expense_type_name || '—' }}</span></div>
                  <div class="il-row"><span class="il-l">发生日期</span><span class="il-v">{{ dlg.data.bill.occur_date || '—' }}</span></div>
                  <div class="il-row"><span class="il-l">报销金额</span><span class="il-v amount">¥ {{ fmtMoney(dlg.data.bill.amount) }}</span></div>
                  <div class="il-row"><span class="il-l">结算方式</span><span class="il-v">{{ dlg.data.bill.settlement_method_name || '—' }}</span></div>
                  <div class="il-row"><span class="il-l">事由</span><span class="il-v">{{ dlg.data.bill.reason || '—' }}</span></div>
                </div>
                <div v-else class="mini-empty">未关联报销单</div>
              </el-card>

              <!-- 票据原件 -->
              <el-card shadow="never" class="mini-card">
                <template #header>
                  <div class="mini-head">
                    <span class="mini-title">票据原件</span>
                    <el-button v-if="invoiceUrl" link type="primary" @click="openInvoice">查看大图</el-button>
                  </div>
                </template>
                <div class="invoice-box">
                  <img v-if="invoiceUrl && invoiceIsImage" :src="invoiceUrl" alt="票据原件" class="inv-img" />
                  <iframe v-else-if="invoiceUrl" :src="invoiceUrl" class="inv-pdf" title="票据 PDF" />
                  <div v-else class="mini-empty">{{ invoiceError || '无票据原件' }}</div>
                </div>
              </el-card>

              <!-- 判读问题清单 -->
              <el-card shadow="never" class="mini-card">
                <template #header>
                  <div class="mini-head">
                    <span class="mini-title">判读问题清单</span>
                    <el-tag v-if="dlg.data.check?.overall_result" size="small"
                            :type="RESULT_TYPE[dlg.data.check.overall_result] || 'info'">
                      {{ dlg.data.check.overall_result }}
                    </el-tag>
                  </div>
                </template>
                <div v-if="reviewIssues.length" class="issue-list">
                  <div v-for="(it, i) in reviewIssues" :key="i" class="issue-item" :class="it.cls">
                    <div class="ii-head">
                      <span class="ii-code">{{ it.rule_code }}</span>
                      <span class="ii-item">{{ it.check_item }}</span>
                      <span class="ii-clause" v-if="it.clause_no">{{ it.clause_no }}</span>
                      <el-tag :type="RESULT_TYPE[it.result] || 'info'" size="small" effect="plain">{{ it.result }}</el-tag>
                    </div>
                    <div class="ii-reason">{{ it.reason || '—' }}</div>
                    <div class="ii-suggest" v-if="it.suggestion">建议：{{ it.suggestion }}</div>
                  </div>
                </div>
                <div v-else class="mini-empty">判读无不合规 / 需关注项</div>
              </el-card>
            </div>

            <!-- 右：AI 说明 + 制单员修改记录 + 复核意见 -->
            <div class="rv-col">
              <el-card shadow="never" class="mini-card">
                <template #header>
                  <div class="mini-head">
                    <span class="mini-title">AI 制证说明</span>
                    <el-tag v-if="dlg.data.ai_model" size="small" effect="plain">{{ dlg.data.ai_model }}</el-tag>
                  </div>
                </template>
                <div v-if="dlg.data.ai_explanation" class="ai-block">
                  <div class="ai-label">分录说明</div>
                  <div class="ai-text">{{ dlg.data.ai_explanation }}</div>
                </div>
                <div v-if="dlg.data.ai_tax_treatment" class="ai-block">
                  <div class="ai-label">税务处理</div>
                  <div class="ai-text tax">{{ dlg.data.ai_tax_treatment }}</div>
                </div>
                <div v-if="!dlg.data.ai_explanation && !dlg.data.ai_tax_treatment" class="mini-empty">暂无 AI 说明</div>
              </el-card>

              <el-card shadow="never" class="mini-card">
                <template #header><span class="mini-title">制单员修改记录</span></template>
                <el-timeline v-if="makerLogs.length" class="log-timeline">
                  <el-timeline-item v-for="(l, i) in makerLogs" :key="i" :timestamp="fmtTime(l.created_at)" placement="top">
                    <div class="log-item">
                      <span class="log-user">{{ l.username }}</span>
                      <span class="log-action">{{ l.action }}</span>
                      <div v-if="l.detail" class="log-detail">{{ l.detail }}</div>
                    </div>
                  </el-timeline-item>
                </el-timeline>
                <div v-else class="mini-empty">制单员未修改 AI 草稿，或无留痕记录</div>
              </el-card>

              <!-- 复核意见 -->
              <el-card shadow="never" class="mini-card review-card">
                <template #header><span class="mini-title">复核意见</span></template>
                <el-input v-model="dlg.comment" type="textarea" :rows="4" maxlength="500" show-word-limit
                          :placeholder="commentPlaceholder" />
                <div class="comment-hint" :class="{ need: commentRequired && dlg.comment.trim().length < 2 }">
                  {{ commentHint }}
                </div>
              </el-card>
            </div>
          </div>
        </template>
      </div>
      <template #footer>
        <el-button @click="dlg.visible = false">关 闭</el-button>
        <el-button type="danger" plain :icon="CircleClose" :loading="dlg.acting === 'reject'"
                   v-permission="'reimburse:voucher:review'" @click="doReview('reject')">退回修改</el-button>
        <el-button type="primary" :icon="CircleCheck" :loading="dlg.acting === 'approve'"
                   :disabled="commentRequired && dlg.comment.trim().length < 2"
                   v-permission="'reimburse:voucher:review'" @click="doReview('approve')">复核通过</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  Finished, Search, Refresh, RefreshLeft, Tickets, Warning, WarningFilled, CircleCheck, CircleClose
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { voucherApi } from '@/api/voucher'
import { reimburseApi } from '@/api/reimburse'
import { RESULT_TYPE, fmtMoney, fmtAmount, fmtTime, moneyToChinese, orDash } from './constants'

const router = useRouter()

const query = reactive({ page: 1, page_size: 20, period: '' })
const list = ref([])
const total = ref(0)
const loading = ref(false)
const batchLoading = ref(false)
const selected = ref([])
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))

const selectedIds = computed(() => selected.value.map((r) => r.id))
/** 选中项中不允许批量复核的（人工覆盖 / 判读需关注） */
const blockingSelected = computed(() => selected.value.filter((r) => isOverride(r) || isConcern(r)))

const overrideCount = computed(() => list.value.filter((r) => isOverride(r)).length)
const concernCount = computed(() => list.value.filter((r) => isConcern(r)).length)
const normalCount = computed(() => list.value.filter((r) => !isOverride(r) && !isConcern(r)).length)

function isOverride(row) {
  return !!(row.override_flag ?? row.bill?.override_flag)
}
function isConcern(row) {
  const r = row.compliance_result || row.bill?.compliance_result
  return r === '需关注'
}
/** 复选框可勾选：经人工覆盖或需关注的凭证不允许批量复核 */
function canSelect(row) {
  return !isOverride(row) && !isConcern(row)
}

async function fetchList() {
  loading.value = true
  try {
    const params = { ...query }
    if (!params.period) delete params.period
    const res = await voucherApi.reviewList(params)
    list.value = res?.list || []
    total.value = res?.total || 0
  } finally {
    loading.value = false
  }
}

function onSelectionChange(rows) { selected.value = rows }
function onSearch() { query.page = 1; fetchList() }
function onReset() { query.period = ''; onSearch() }

// ---- 复核详情 ----
const dlg = reactive({ visible: false, loading: false, data: null, comment: '', acting: '' })
const invoiceUrl = ref('')
const invoiceIsImage = ref(true)
const invoiceError = ref('')

const dlgTotalDebit = computed(() => {
  const rows = dlg.data?.entries || []
  return rows.reduce((s, r) => s + Math.round((Number(r.debit_amount) || 0) * 100), 0) / 100
})
const dlgTotalCredit = computed(() => {
  const rows = dlg.data?.entries || []
  return rows.reduce((s, r) => s + Math.round((Number(r.credit_amount) || 0) * 100), 0) / 100
})

const reviewIssues = computed(() => (dlg.data?.check?.issues || [])
  .filter((i) => ['不合规', '需关注'].includes(i.result))
  .map((i) => ({ ...i, cls: i.result === '不合规' ? 'err' : 'warn' })))

/** 制单员修改记录：从审计轨迹里筛出凭证相关的写操作 */
const makerLogs = computed(() => (dlg.data?.logs || []))
const commentRequired = computed(() => !!(dlg.data && (isOverride(dlg.data) || isConcern(dlg.data))))
const commentPlaceholder = computed(() => (commentRequired.value
  ? '本凭证经人工覆盖或判读需关注，复核意见必填（请说明核查过程与结论依据）'
  : '填写复核意见（退回修改时必填）'))
const commentHint = computed(() => {
  if (commentRequired.value && dlg.comment.trim().length < 2) return '本凭证经人工覆盖 / 判读需关注，复核意见必填'
  if (commentRequired.value) return '已填写复核意见'
  return '复核通过可不填；退回修改须说明原因'
})

async function openReview(row) {
  dlg.visible = true
  dlg.loading = true
  dlg.data = null
  dlg.comment = ''
  resetInvoice()
  try {
    const d = await voucherApi.detail(row.id)
    dlg.data = d
    loadInvoice(d)
  } finally {
    dlg.loading = false
  }
}

function resetInvoice() {
  if (invoiceUrl.value) URL.revokeObjectURL(invoiceUrl.value)
  invoiceUrl.value = ''
  invoiceIsImage.value = true
  invoiceError.value = ''
}

/** 票据原件需带 Bearer 头，走 blob → objectURL */
async function loadInvoice(voucher) {
  const rid = voucher?.bill?.id
  if (!rid) { invoiceError.value = '该凭证未关联报销单'; return }
  try {
    const blob = await reimburseApi.invoiceFile(rid)
    const type = blob?.type || ''
    if (type.includes('json')) { invoiceError.value = '无票据原件'; return }
    invoiceIsImage.value = type.includes('image')
    invoiceUrl.value = URL.createObjectURL(blob)
  } catch {
    invoiceError.value = '票据原件加载失败（可能未上传票据）'
  }
}

function openInvoice() {
  if (invoiceUrl.value) window.open(invoiceUrl.value, '_blank')
}

async function doReview(action) {
  if (!dlg.data) return
  const comment = dlg.comment.trim()
  if (action === 'reject' && comment.length < 2) return ElMessage.warning('退回修改须填写复核意见')
  if (action === 'approve' && commentRequired.value && comment.length < 2) {
    return ElMessage.warning('本凭证经人工覆盖或判读需关注，复核意见必填')
  }
  try {
    await ElMessageBox.confirm(
      action === 'approve'
        ? `确认复核通过凭证「${dlg.data.voucher_code}」？通过后该凭证即可记账。`
        : `确认将凭证「${dlg.data.voucher_code}」退回制单员修改？`,
      action === 'approve' ? '复核通过' : '退回修改',
      { type: action === 'approve' ? 'success' : 'warning', confirmButtonText: '确认', cancelButtonText: '取消' }
    )
  } catch { return }
  dlg.acting = action
  try {
    await voucherApi.review(dlg.data.id, { action, comment })
    ElMessage.success(action === 'approve' ? '复核通过' : '已退回制单员修改')
    dlg.visible = false
    fetchList()
  } finally {
    dlg.acting = ''
  }
}

// ---- 批量复核 ----
async function onBatchApprove() {
  if (!selectedIds.value.length) return ElMessage.warning('请先勾选要复核的凭证')
  if (blockingSelected.value.length) {
    return ElMessage.warning('选中的凭证中含人工覆盖或判读需关注的凭证，须逐张复核')
  }
  const n = selectedIds.value.length
  let comment = ''
  try {
    const res = await ElMessageBox.prompt(
      `确认对选中的 ${n} 张凭证批量复核通过？通过后即可记账。`,
      '批量复核通过', {
        type: 'warning',
        inputLabel: '复核意见',
        inputPlaceholder: '可填写统一的复核意见（选填）',
        confirmButtonText: '确认通过', cancelButtonText: '取消'
      }
    )
    comment = (res.value || '').trim()
  } catch { return }

  batchLoading.value = true
  try {
    const res = await voucherApi.reviewBatch({ ids: selectedIds.value, action: 'approve', comment })
    const ok = res?.success_count ?? 0
    const failed = res?.failed || []
    if (failed.length) {
      const detail = failed.map((f) => `${f.code || f.id}：${f.reason}`).join('；')
      ElMessageBox.alert(
        `成功 ${ok} 张，失败 ${failed.length} 张。失败原因：${detail}`,
        '批量复核结果', { type: 'warning' }
      )
    } else {
      ElMessage.success(`批量复核通过 ${ok} 张凭证`)
    }
    selected.value = []
    fetchList()
  } finally {
    batchLoading.value = false
  }
}

function goBill(id) { if (id) router.push(`/rmb/bill/${id}`) }

onMounted(fetchList)
onBeforeUnmount(resetInvoice)
</script>

<style scoped>
.sel-hint { font-size: 12px; color: var(--text-2); }
.sel-hint b { color: var(--brand-dark); }
.code-btn { font-weight: 600; font-family: ui-monospace, Menlo, Consolas, monospace; }
.amount { font-variant-numeric: tabular-nums; }
.muted { color: var(--text-3); }
.stat-strip { margin-bottom: 2px; }

/* 复核弹窗 */
.rv-body { max-height: 68vh; overflow: auto; padding-right: 6px; }
.rv-alert { margin-bottom: 12px; }
.ov-body { display: flex; flex-direction: column; gap: 3px; font-size: 13px; line-height: 1.7; }
.ov-reason { color: #c45656; }

/* 只读凭证 */
.rv-sheet { border: 1px solid #c3cad6; background: #fff; padding: 16px 18px 12px; border-radius: 8px; margin-bottom: 12px; }
.rv-title {
  margin: 0 0 12px; text-align: center; font-size: 20px; font-weight: 700; letter-spacing: 6px;
  color: #1f2937; padding-bottom: 6px; position: relative;
}
.rv-title::after {
  content: ''; position: absolute; left: 50%; transform: translateX(-50%); bottom: 0;
  width: 160px; height: 3px; border-top: 2px solid #1f2937; border-bottom: 1px solid #1f2937;
}
.rv-meta { display: flex; gap: 26px; flex-wrap: wrap; margin-bottom: 10px; font-size: 13px; }
.rm-l { color: var(--text-3); margin-right: 5px; }
.rm-code { font-family: ui-monospace, Menlo, Consolas, monospace; }
.rv-table { width: 100%; border-collapse: collapse; table-layout: fixed; border: 2px solid #1f2937; }
.rv-table th {
  background: #f4f6fa; border: 1px solid #9aa4b2; padding: 6px; font-size: 12.5px;
  font-weight: 700; color: var(--text-1); text-align: center;
}
.rv-table td { border: 1px solid #c3cad6; padding: 6px 8px; font-size: 12.5px; vertical-align: middle; }
.t-idx { width: 48px; text-align: center; color: var(--text-2); }
.t-sum { width: 34%; }
.t-subj { width: 26%; }
.t-money { width: 20%; }
.num { text-align: right; font-variant-numeric: tabular-nums; font-family: ui-monospace, Menlo, Consolas, monospace; }
.subj-code { font-family: ui-monospace, Menlo, Consolas, monospace; color: var(--text-2); margin-right: 5px; }
.rv-total td { border-top: 2px solid #1f2937; background: #fafbfc; }
.total-label { font-weight: 700; }
.total-num { text-align: right; font-weight: 700; font-variant-numeric: tabular-nums; font-family: ui-monospace, Menlo, Consolas, monospace; }
.rv-foot {
  display: flex; gap: 26px; flex-wrap: wrap; margin-top: 10px; padding-top: 8px;
  border-top: 1px dashed var(--border); font-size: 12px; color: var(--text-2);
}

/* 下方两列 */
.rv-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; align-items: start; }
.rv-col { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.mini-card :deep(.el-card__body) { padding: 10px 12px; }
.mini-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.mini-title { font-size: 13px; font-weight: 700; color: var(--text-1); }
.mini-empty { font-size: 12px; color: var(--text-3); line-height: 1.6; padding: 4px 0; }
.info-list { display: flex; flex-direction: column; gap: 5px; }
.il-row { display: flex; gap: 8px; font-size: 12px; line-height: 1.6; }
.il-l { flex: 0 0 62px; color: var(--text-3); }
.il-v { color: var(--text-1); word-break: break-all; }
.il-v.amount { color: #c45656; font-weight: 700; }
.il-link { padding: 0; height: auto; font-weight: 600; }
.invoice-box {
  border: 1px solid var(--border); border-radius: 6px; background: #fafbfc; overflow: hidden;
  height: 230px; display: flex; align-items: center; justify-content: center;
}
.inv-img { max-width: 100%; max-height: 100%; object-fit: contain; }
.inv-pdf { width: 100%; height: 100%; border: 0; }
.issue-list { display: flex; flex-direction: column; gap: 8px; }
.issue-item { padding: 8px 10px; border-radius: 6px; font-size: 12px; line-height: 1.65; }
.issue-item.err { background: #fef6f6; border-left: 3px solid #f56c6c; }
.issue-item.warn { background: #fffbf2; border-left: 3px solid #e6a23c; }
.ii-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 4px; }
.ii-code { font-family: ui-monospace, Menlo, Consolas, monospace; font-weight: 700; color: var(--text-1); }
.ii-item { font-weight: 600; color: var(--text-1); }
.ii-clause { font-size: 11px; color: var(--text-3); }
.ii-reason { color: var(--text-2); white-space: pre-wrap; }
.ii-suggest { margin-top: 3px; color: #529b2e; }
.ai-block + .ai-block { margin-top: 8px; }
.ai-label { font-size: 12px; font-weight: 600; color: var(--brand-dark); margin-bottom: 3px; }
.ai-text { font-size: 12.5px; line-height: 1.7; color: var(--text-2); white-space: pre-wrap; }
.ai-text.tax { color: #8b5cf6; }
.log-timeline { padding-left: 2px; margin-top: 4px; }
.log-timeline :deep(.el-timeline-item__timestamp) { font-size: 11px; color: var(--text-3); }
.log-item { font-size: 12px; line-height: 1.6; }
.log-user { font-weight: 600; color: var(--text-1); margin-right: 6px; }
.log-detail { margin-top: 3px; font-size: 11px; color: var(--text-3); word-break: break-all; }
.review-card :deep(.el-card__body) { padding: 10px 12px 12px; }
.comment-hint { margin-top: 6px; font-size: 12px; color: var(--text-3); }
.comment-hint.need { color: #f56c6c; }

@media (max-width: 992px) {
  .rv-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
