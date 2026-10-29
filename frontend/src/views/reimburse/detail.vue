<template>
  <div class="page bill-detail-page">
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Document /></el-icon>报销单详情</h2>
        <div class="ph-desc">{{ bill.bill_no || '' }} · 查看报销信息、票据原件与最近一次合规判读结论</div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Back" @click="goBack">返回列表</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <!-- 分级审批：仅有权审批本单的人可见（层级足、非本人、非终态） -->
        <el-button v-if="bill.can_approve" type="warning" :icon="Stamp"
                   v-permission="'reimburse:bill:approve'" @click="openApprove">审批</el-button>
        <el-button v-if="canEdit" type="primary" plain :icon="EditPen" v-permission="'reimburse:bill:edit'"
                   @click="goEdit">修改</el-button>
        <el-button v-if="canCheck" type="primary" :icon="MagicStick" v-permission="'reimburse:check:run'"
                   @click="goCompliance">
          {{ bill.latest_check ? '查看/重新判读' : '提交 AI 合规判读' }}
        </el-button>
        <el-button v-if="canMakeVoucher" type="success" :icon="Tickets" v-permission="'reimburse:voucher:make'"
                   @click="goMakeVoucher">生成凭证</el-button>
        <el-button v-if="bill.status === '已生成凭证' && voucherId" :icon="Files" @click="goVoucher">查看凭证</el-button>
        <el-button v-if="canVoid && !bill.override_flag" type="danger" plain :icon="CircleClose"
                   v-permission="['reimburse:bill:delete', 'reimburse:bill:edit']" @click="onVoid">作废</el-button>
        <!-- 已审批的单据不允许报销人自行作废：把原因说明出来，避免「按钮突然消失」的困惑 -->
        <el-tooltip v-else-if="bill.void_blocked_reason" placement="bottom" :content="bill.void_blocked_reason">
          <el-button type="danger" plain :icon="CircleClose" disabled>作废</el-button>
        </el-tooltip>
      </div>
    </div>

    <div v-loading="loading" class="bd-body">
      <!-- ============ 顶部摘要卡 ============ -->
      <el-card shadow="never" class="summary-card">
        <div class="sum-body">
          <div class="sum-left">
            <div class="sum-title">
              <span class="sum-no">{{ bill.bill_no || '—' }}</span>
              <el-tag :type="BILL_STATUS_TYPE[bill.status] || 'info'" size="small">{{ bill.status || '—' }}</el-tag>
              <el-tag :type="RESULT_TYPE[bill.compliance_result] || 'info'" size="small" effect="plain">
                判读：{{ bill.compliance_result || '未判读' }}
              </el-tag>
              <el-tag :type="APPROVAL_TYPE[bill.approval_status] || 'info'" size="small" effect="plain">
                审批：{{ bill.approval_status || '未审批' }}
              </el-tag>
              <el-tag v-if="bill.override_flag" type="danger" size="small" effect="dark">人工覆盖</el-tag>
            </div>
            <div class="sum-grid">
              <div class="sg-item"><span class="sg-l">报销人</span><span class="sg-v">{{ bill.employee_name || '—' }}</span></div>
              <div class="sg-item"><span class="sg-l">部门</span><span class="sg-v">{{ orDash(bill.department_name) }}</span></div>
              <div class="sg-item"><span class="sg-l">费用类型</span><span class="sg-v">{{ bill.expense_type_name || '—' }}</span></div>
              <div class="sg-item"><span class="sg-l">报销日期</span><span class="sg-v">{{ bill.bill_date || '—' }}</span></div>
              <div class="sg-item"><span class="sg-l">发生日期</span><span class="sg-v">{{ bill.occur_date || '—' }}</span></div>
              <div class="sg-item"><span class="sg-l">结算方式</span><span class="sg-v">{{ orDash(bill.settlement_method_name) }}</span></div>
              <div class="sg-item"><span class="sg-l">审批人</span><span class="sg-v">{{ orDash(bill.approver_name) }}</span></div>
              <div class="sg-item"><span class="sg-l">审批层级</span><span class="sg-v">{{ orDash(bill.approver_level) }}</span></div>
              <div class="sg-item">
                <span class="sg-l">应审层级</span>
                <span class="sg-v">
                  {{ bill.required_approver_label || '—' }}
                  <span v-if="bill.required_approval_rank" class="sg-hint">（{{ bill.required_approval_rank }} 级）</span>
                </span>
              </div>
              <div class="sg-item">
                <span class="sg-l">实际审批</span>
                <span class="sg-v">
                  <template v-if="bill.approval_status && bill.approval_status !== '未审批'">
                    {{ bill.approval_by || '—' }}
                    <span v-if="bill.approval_rank" class="sg-hint">（{{ bill.approval_rank }} 级）</span>
                  </template>
                  <template v-else>—</template>
                </span>
              </div>
            </div>
          </div>
          <div class="sum-right">
            <div class="sr-label">报销金额</div>
            <div class="sr-amount">¥ {{ fmtMoney(bill.amount) }}</div>
            <div class="sr-sub">{{ bill.has_invoice ? '附发票' : '无发票' }} · {{ moneyToChinese(bill.amount) }}</div>
          </div>
        </div>
        <!-- 人工覆盖提示 -->
        <div v-if="bill.override_flag" class="ov-bar">
          <el-icon><WarningFilled /></el-icon>
          <span>本单经 <b>{{ bill.override_by || '—' }}</b> 人工覆盖判定：{{ bill.override_reason || '—' }}</span>
        </div>
        <!-- 分级审批留痕（制度第四条） -->
        <div v-if="bill.approval_status && bill.approval_status !== '未审批'" class="ap-bar"
             :class="{ rejected: bill.approval_status === '已驳回' }">
          <el-icon><Stamp /></el-icon>
          <span>
            {{ bill.approval_by || '—' }}（{{ bill.approval_rank || '?' }} 级）
            于 {{ bill.approval_at || '—' }} <b>{{ bill.approval_status }}</b>
            <template v-if="bill.approval_comment">：{{ bill.approval_comment }}</template>
          </span>
        </div>
        <div v-if="bill.can_approve" class="ap-hint">
          <el-icon><InfoFilled /></el-icon>
          <span>
            本单金额 {{ fmtMoney(bill.amount) }} 元，须经
            <b>{{ bill.required_approver_label || '—' }}</b> 审批（{{ bill.required_approval_rank }} 级）；
            您的审批层级为 {{ bill.my_approval_rank }} 级（数据范围：{{ bill.data_scope_label || '—' }}），
            可点击右上角「审批」处理。
          </span>
        </div>
        <!-- 有审批权限但因数据范围/层级不足无法审批时说明原因 -->
        <div v-else-if="bill.approve_blocked_reason" class="ap-blocked">
          <el-icon><WarningFilled /></el-icon>
          <span>{{ bill.approve_blocked_reason }}</span>
        </div>
      </el-card>

      <el-tabs v-model="activeTab" class="bd-tabs">
        <!-- ============ Tab 1：报销信息 ============ -->
        <el-tab-pane label="报销信息" name="info">
          <el-card shadow="never">
            <el-descriptions :column="3" border size="default" class="desc">
              <el-descriptions-item label="报销单号">{{ bill.bill_no || '—' }}</el-descriptions-item>
              <el-descriptions-item label="报销日期">{{ bill.bill_date || '—' }}</el-descriptions-item>
              <el-descriptions-item label="状态">
                <el-tag :type="BILL_STATUS_TYPE[bill.status] || 'info'" size="small">{{ bill.status || '—' }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="报销人">{{ bill.employee_name || '—' }}</el-descriptions-item>
              <el-descriptions-item label="部门">{{ orDash(bill.department_name) }}</el-descriptions-item>
              <el-descriptions-item label="费用类型">{{ bill.expense_type_name || '—' }}</el-descriptions-item>
              <el-descriptions-item label="费用发生日期">{{ bill.occur_date || '—' }}</el-descriptions-item>
              <el-descriptions-item label="报销金额">
                <b class="amount">¥ {{ fmtMoney(bill.amount) }}</b>
              </el-descriptions-item>
              <el-descriptions-item label="是否附发票">{{ bill.has_invoice ? '是' : '否' }}</el-descriptions-item>
              <el-descriptions-item label="结算方式">{{ orDash(bill.settlement_method_name) }}</el-descriptions-item>
              <el-descriptions-item label="审批人">{{ orDash(bill.approver_name) }}</el-descriptions-item>
              <el-descriptions-item label="审批层级">{{ orDash(bill.approver_level) }}</el-descriptions-item>
              <el-descriptions-item label="报销事由" :span="3">{{ bill.reason || '—' }}</el-descriptions-item>
            </el-descriptions>

            <!-- 差旅专项 -->
            <template v-if="isTravel">
              <div class="sec-title">差旅专项</div>
              <el-descriptions :column="3" border class="desc">
                <el-descriptions-item label="出差地点">{{ orDash(bill.travel_city) }}</el-descriptions-item>
                <el-descriptions-item label="出差起止">
                  {{ bill.travel_start || '—' }} 至 {{ bill.travel_end || '—' }}
                </el-descriptions-item>
                <el-descriptions-item label="住宿晚数">{{ bill.nights ?? '—' }} 晚</el-descriptions-item>
                <el-descriptions-item label="每晚金额" :span="3">
                  <template v-if="bill.nights && bill.amount">
                    {{ fmtMoney(Number(bill.amount) / Number(bill.nights)) }} 元 / 晚
                  </template>
                  <template v-else>—</template>
                </el-descriptions-item>
              </el-descriptions>
            </template>

            <!-- 招待专项 -->
            <template v-if="isGuest">
              <div class="sec-title">业务招待专项</div>
              <el-descriptions :column="3" border class="desc">
                <el-descriptions-item label="招待对象单位">{{ orDash(bill.guest_company) }}</el-descriptions-item>
                <el-descriptions-item label="陪同人数">{{ bill.guest_count ?? '—' }} 人</el-descriptions-item>
                <el-descriptions-item label="人均金额">
                  <template v-if="bill.guest_count && bill.amount">
                    {{ fmtMoney(Number(bill.amount) / Number(bill.guest_count)) }} 元 / 人
                  </template>
                  <template v-else>—</template>
                </el-descriptions-item>
              </el-descriptions>
            </template>

            <!-- 特批与说明 -->
            <template v-if="bill.special_approver || bill.explanation">
              <div class="sec-title">特批与情况说明</div>
              <el-descriptions :column="2" border class="desc">
                <el-descriptions-item label="特批人及职务">{{ orDash(bill.special_approver) }}</el-descriptions-item>
                <el-descriptions-item label="情况说明">{{ bill.explanation || '—' }}</el-descriptions-item>
              </el-descriptions>
            </template>

            <!-- 制单人信息 -->
            <div class="meta-foot">
              <span>制单人：{{ orDash(bill.created_by) }}</span>
              <span>创建时间：{{ fmtTime(bill.created_at) }}</span>
            </div>
          </el-card>
        </el-tab-pane>

        <!-- ============ Tab 2：票据信息 ============ -->
        <el-tab-pane label="票据信息" name="invoice">
          <el-card shadow="never">
            <div v-if="!hasInvoice" class="empty-tab">
              <el-empty description="本报销单未附发票，无票据信息" :image-size="90" />
            </div>
            <div v-else class="inv-layout">
              <!-- 左：原件预览 -->
              <div class="inv-left">
                <div class="inv-head">
                  <span class="inv-title">票据原件</span>
                  <el-button v-if="invoiceUrl" link type="primary" @click="openInvoice">查看大图 / 新窗口打开</el-button>
                </div>
                <div class="inv-box">
                  <img v-if="invoiceUrl && invoiceIsImage" :src="invoiceUrl" alt="票据原件" class="inv-img" />
                  <iframe v-else-if="invoiceUrl" :src="invoiceUrl" class="inv-pdf" title="票据 PDF 预览" />
                  <div v-else class="inv-empty">
                    <el-icon><Document /></el-icon>
                    <span>{{ invoiceError || '加载票据原件……' }}</span>
                  </div>
                </div>
              </div>
              <!-- 右：票据字段 -->
              <div class="inv-right">
                <div class="inv-head"><span class="inv-title">票据字段</span></div>
                <el-descriptions :column="2" border size="small" class="desc">
                  <el-descriptions-item label="票据类型">{{ orDash(invoice.document_type) }}</el-descriptions-item>
                  <el-descriptions-item label="是否发票">{{ invoice.is_invoice === 0 ? '否' : '是' }}</el-descriptions-item>
                  <el-descriptions-item label="发票代码">{{ orDash(invoice.invoice_code) }}</el-descriptions-item>
                  <el-descriptions-item label="发票号码">{{ orDash(invoice.invoice_number) }}</el-descriptions-item>
                  <el-descriptions-item label="开票日期">{{ orDash(invoice.issue_date) }}</el-descriptions-item>
                  <el-descriptions-item label="价税合计">
                    <b class="amount">¥ {{ fmtMoney(invoice.total_amount) }}</b>
                  </el-descriptions-item>
                  <el-descriptions-item label="购买方名称" :span="2">{{ orDash(invoice.buyer_name) }}</el-descriptions-item>
                  <el-descriptions-item label="销售方名称" :span="2">{{ orDash(invoice.seller_name) }}</el-descriptions-item>
                  <el-descriptions-item label="不含税金额">{{ fmtMoney(invoice.amount_without_tax) }}</el-descriptions-item>
                  <el-descriptions-item label="税率 / 税额">
                    {{ orDash(invoice.tax_rate) }} / {{ fmtMoney(invoice.tax_amount) }}
                  </el-descriptions-item>
                  <el-descriptions-item label="大写金额" :span="2">{{ orDash(invoice.total_amount_cn) }}</el-descriptions-item>
                  <template v-if="isTravel">
                    <el-descriptions-item label="乘车人">{{ orDash(invoice.passenger_name) }}</el-descriptions-item>
                    <el-descriptions-item label="消费城市">{{ orDash(invoice.consume_city) }}</el-descriptions-item>
                    <el-descriptions-item label="出发地 / 到达地">
                      {{ orDash(invoice.travel_from) }} → {{ orDash(invoice.travel_to) }}
                    </el-descriptions-item>
                    <el-descriptions-item label="乘车日期">{{ orDash(invoice.travel_date) }}</el-descriptions-item>
                    <el-descriptions-item label="入住 / 离店">
                      {{ orDash(invoice.checkin_date) }} / {{ orDash(invoice.checkout_date) }}
                    </el-descriptions-item>
                    <el-descriptions-item label="票据晚数">{{ invoice.nights ?? '—' }} 晚</el-descriptions-item>
                  </template>
                  <el-descriptions-item v-if="invoice.remark" label="备注" :span="2">{{ invoice.remark }}</el-descriptions-item>
                </el-descriptions>

                <!-- 票据一致性比对 -->
                <div v-if="invDiffRows.length" class="diff-block">
                  <div class="diff-title">与报销信息比对</div>
                  <div v-for="(d, i) in invDiffRows" :key="i" class="diff-item" :class="d.level">
                    <el-icon><CircleCheck v-if="d.level === 'ok'" /><WarningFilled v-else /></el-icon>
                    <span>{{ d.text }}</span>
                  </div>
                </div>
                <div class="inv-meta" v-if="invoice.original_filename">
                  文件：{{ invoice.original_filename }}
                  <template v-if="invoice.llm_model"> · 识别模型 {{ invoice.llm_model }}</template>
                </div>
              </div>
            </div>
          </el-card>
        </el-tab-pane>

        <!-- ============ Tab 3：判读结论 ============ -->
        <el-tab-pane label="判读结论" name="check">
          <el-card shadow="never">
            <div v-if="!latestCheck" class="empty-tab">
              <el-empty description="该报销单尚未进行合规判读" :image-size="90">
                <el-button v-if="canCheck" type="primary" :icon="MagicStick" v-permission="'reimburse:check:run'"
                           @click="goCompliance">提交 AI 合规判读</el-button>
              </el-empty>
            </div>
            <template v-else>
              <!-- 判读结论摘要 -->
              <div class="chk-summary" :class="chkClass">
                <div class="cs-left">
                  <div class="cs-label">最近一次判读结论</div>
                  <div class="cs-value">{{ latestCheck.overall_result || '—' }}</div>
                </div>
                <div class="cs-mid">
                  <div class="cs-line">不合规 <b>{{ checkCountBy('不合规') }}</b> 项 ·
                    需关注 <b>{{ checkCountBy('需关注') }}</b> 项 ·
                    合规 <b>{{ checkCountBy('合规') }}</b> 项 ·
                    不适用 <b>{{ checkCountBy('不适用') }}</b> 项</div>
                  <div class="cs-line" v-if="latestCheck.inconsistency_count">
                    程序校验不一致 <b class="err">{{ latestCheck.inconsistency_count }}</b> 项
                  </div>
                  <div class="cs-line meta">
                    判读人 {{ latestCheck.checked_by || '—' }} · {{ fmtTime(latestCheck.checked_at) }}
                    <template v-if="latestCheck.elapsed"> · 耗时 {{ Number(latestCheck.elapsed).toFixed(1) }} 秒</template>
                    <template v-if="latestCheck.check_no"> · 第 {{ latestCheck.check_no }} 次判读</template>
                  </div>
                </div>
                <div class="cs-right">
                  <el-button link type="primary" @click="goCompliance">查看完整判读结果</el-button>
                </div>
              </div>
              <div v-if="latestCheck.summary" class="chk-summary-text">{{ latestCheck.summary }}</div>

              <!-- 14 条规则表格 -->
              <el-table :data="checkIssues" border size="small" class="rule-table"
                        :row-class-name="ruleRowClass" empty-text="判读明细为空">
                <el-table-column prop="rule_code" label="规则" width="72" align="center">
                  <template #default="{ row }">
                    <span class="rule-code">{{ row.rule_code }}</span>
                  </template>
                </el-table-column>
                <el-table-column prop="check_item" label="检查项" width="140" show-overflow-tooltip />
                <el-table-column prop="clause_no" label="条款" width="92" align="center" />
                <el-table-column label="结论" width="92" align="center">
                  <template #default="{ row }">
                    <el-tag :type="RESULT_TYPE[row.result] || 'info'" size="small">{{ row.result }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="reason" label="理由" min-width="260" show-overflow-tooltip />
                <el-table-column prop="suggestion" label="提示与建议" min-width="200" show-overflow-tooltip />
                <el-table-column label="程序校验" width="120" align="center">
                  <template #default="{ row }">
                    <el-tooltip v-if="row.consistency === '不一致'" placement="top"
                                :content="`程序校验结论：${row.program_triggered === 1 ? '该规则被触发' : '该规则未被触发'}，AI 结论与之一致性校验不通过`">
                      <span class="inc-flag"><el-icon><Warning /></el-icon>不一致</span>
                    </el-tooltip>
                    <span v-else-if="row.consistency === '一致'" class="cons-ok">
                      <el-icon><CircleCheck /></el-icon>一致
                    </span>
                    <span v-else class="cons-na">未校验</span>
                  </template>
                </el-table-column>
              </el-table>
            </template>
          </el-card>
        </el-tab-pane>

        <!-- ============ Tab 4：审计轨迹 ============ -->
        <el-tab-pane label="审计轨迹" name="logs">
          <el-card shadow="never">
            <el-timeline v-if="logs.length" class="log-timeline">
              <el-timeline-item v-for="(l, i) in logs" :key="i" :timestamp="fmtTime(l.created_at)"
                                placement="top" :type="logType(l.action)">
                <div class="log-card">
                  <div class="log-head">
                    <span class="log-user">{{ l.username }}</span>
                    <el-tag size="small" effect="plain">{{ l.action }}</el-tag>
                  </div>
                  <div v-if="l.detail" class="log-detail">{{ l.detail }}</div>
                </div>
              </el-timeline-item>
            </el-timeline>
            <el-empty v-else description="暂无审计记录" :image-size="90" />
          </el-card>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 分级审批弹窗（制度第四条） -->
    <el-dialog v-model="approveVisible" title="审批报销单" width="560px" :close-on-click-modal="false">
      <el-alert type="info" :closable="false" show-icon class="ap-alert">
        <template #title>
          单号 {{ bill.bill_no }}　金额 ¥{{ fmtMoney(bill.amount) }}
        </template>
        <div>
          按制度第四条，本单须经 <b>{{ bill.required_approver_label || '—' }}</b>
          审批（{{ bill.required_approval_rank }} 级）；
          您的审批层级为 {{ bill.my_approval_rank }} 级，满足审批要求。
        </div>
      </el-alert>
      <el-form label-width="88px" class="ap-form">
        <el-form-item label="审批结论">
          <el-radio-group v-model="approveForm.action">
            <el-radio-button value="approve">审批通过</el-radio-button>
            <el-radio-button value="reject">驳回修改</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="approveForm.action === 'reject' ? '驳回原因' : '审批意见'">
          <el-input v-model="approveForm.comment" type="textarea" :rows="4"
                    :placeholder="approveForm.action === 'reject'
                      ? '必填：说明退回原因，报销人按此修改'
                      : '二级以上审批须填写审批意见（制度第四条）'" maxlength="500" show-word-limit />
        </el-form-item>
        <el-form-item v-if="approveForm.action === 'reject'">
          <span class="ap-tip">驳回后报销单将退回「待判读」，报销人修改后可重新提交。</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="approveVisible = false">取消</el-button>
        <el-button :type="approveForm.action === 'approve' ? 'primary' : 'danger'"
                   :loading="approving" @click="submitApprove">
          {{ approveForm.action === 'approve' ? '确认通过' : '确认驳回' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Document, Back, Refresh, EditPen, MagicStick, Tickets, Files, CircleClose,
  Warning, WarningFilled, CircleCheck, Stamp, InfoFilled
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { reimburseApi } from '@/api/reimburse'
import { voucherApi } from '@/api/voucher'
import {
  BILL_STATUS_TYPE, RESULT_TYPE, APPROVAL_TYPE, fmtMoney, fmtTime, orDash, moneyToChinese, dayDiff,
  sameCity
} from './constants'

const route = useRoute()
const router = useRouter()
const billId = computed(() => route.params.id)

const loading = ref(false)
const activeTab = ref('info')
const bill = reactive({})
const invoice = reactive({})
const latestCheck = reactive({ issues: [] })
const logs = ref([])
const voucherId = ref(null)

const invoiceUrl = ref('')
const invoiceIsImage = ref(true)
const invoiceError = ref('')

// ---- 分级审批（制度第四条）----
const approveVisible = ref(false)
const approving = ref(false)
const approveForm = reactive({ action: 'approve', comment: '' })

function openApprove() {
  approveForm.action = 'approve'
  approveForm.comment = ''
  approveVisible.value = true
}

async function submitApprove() {
  const isReject = approveForm.action === 'reject'
  if (isReject && !approveForm.comment.trim()) {
    return ElMessage.warning('驳回时必须填写原因')
  }
  // 二级以上审批（5,000 元以上）无论通过与否都要求意见，与后端校验保持一致
  if (!isReject && (bill.required_approval_rank || 1) >= 2 && !approveForm.comment.trim()) {
    return ElMessage.warning('本单须经二级以上审批，请填写审批意见')
  }
  try {
    await ElMessageBox.confirm(
      isReject ? '确认驳回该报销单？驳回后将退回报销人修改。' : '确认审批通过该报销单？',
      '审批确认', { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' }
    )
  } catch { return }

  approving.value = true
  try {
    const res = await reimburseApi.approve(billId.value, {
      action: approveForm.action,
      comment: approveForm.comment.trim()
    })
    ElMessage.success(res?.bill_no ? `${isReject ? '已驳回' : '已通过'}：${res.bill_no}` : '审批完成')
    approveVisible.value = false
    load()
  } catch (e) {
    // request.js 已统一提示错误，这里保持弹窗打开便于修改后重试
  } finally {
    approving.value = false
  }
}

// ---- 派生 ----
const hasInvoice = computed(() => !!bill.has_invoice && !!bill.invoice)
const isTravel = computed(() => (bill.expense_type_name || '').includes('差旅'))
const isGuest = computed(() => (bill.expense_type_name || '').includes('招待'))
const checkIssues = computed(() => latestCheck.issues || [])

const EDITABLE = ['待判读', '判读不合规', '待确认']
const canEdit = computed(() => EDITABLE.includes(bill.status))
const canCheck = computed(() => ['待判读', '判读不合规', '待确认'].includes(bill.status))
const canMakeVoucher = computed(() => bill.status === '待制证')
const canVoid = computed(() => !!bill.can_void)

const chkClass = computed(() => ({
  合规: 'chk-ok', 需关注: 'chk-warn', 不合规: 'chk-danger'
}[latestCheck.overall_result] || 'chk-none'))

const checkCountBy = (r) => checkIssues.value.filter((i) => i.result === r).length

/** 票据与报销信息的一致性比对（详情页用于交叉核对） */
const invDiffRows = computed(() => {
  if (!bill.invoice) return []
  const out = []
  const amtDiff = Math.abs((Number(bill.amount) || 0) - (Number(invoice.total_amount) || 0))
  if (Number(invoice.total_amount) > 0) {
    out.push(amtDiff > 0.01
      ? { level: 'warn', text: `票据价税合计 ${fmtMoney(invoice.total_amount)} 与报销金额 ${fmtMoney(bill.amount)} 不一致（差 ${fmtMoney(amtDiff)} 元）` }
      : { level: 'ok', text: `票据价税合计与报销金额一致（${fmtMoney(bill.amount)} 元）` })
  }
  const d = dayDiff(invoice.issue_date, bill.occur_date)
  if (d !== null) {
    out.push(Math.abs(d) > 3
      ? { level: 'warn', text: `开票日期与费用发生日期相差 ${Math.abs(d)} 天（超过 3 天），属跨期报销` }
      : { level: 'ok', text: `开票日期与费用发生日期相差 ${Math.abs(d)} 天` })
  }
  if (isTravel.value && invoice.consume_city && bill.travel_city) {
    // 统一走 sameCity：容忍「上海市」「上海虹桥」等写法差异，与填单页/后端判读口径一致
    out.push(sameCity(invoice.consume_city, bill.travel_city)
      ? { level: 'ok', text: `票据消费城市与出差地点一致（${bill.travel_city}）` }
      : { level: 'warn', text: `票据消费城市「${invoice.consume_city}」与出差地点「${bill.travel_city}」不一致` })
  }
  if (isTravel.value && Number(invoice.nights) && Number(bill.nights)) {
    out.push(Number(invoice.nights) === Number(bill.nights)
      ? { level: 'ok', text: `票据晚数与填报住宿晚数一致（${bill.nights} 晚）` }
      : { level: 'warn', text: `票据晚数 ${invoice.nights} 晚与填报 ${bill.nights} 晚不一致` })
  }
  return out
})

function ruleRowClass({ row }) {
  if (row.result === '不合规') return 'row-danger'
  if (row.result === '需关注') return 'row-warn'
  return ''
}
function logType(action) {
  const a = String(action || '')
  if (/判读|合规/.test(a)) return 'primary'
  if (/凭证|制证/.test(a)) return 'success'
  if (/作废|覆盖|退回|删除/.test(a)) return 'danger'
  if (/修改|编辑/.test(a)) return 'warning'
  return ''
}

// ---- 加载 ----
async function load() {
  loading.value = true
  try {
    const d = await reimburseApi.detail(billId.value)
    Object.keys(bill).forEach((k) => delete bill[k])
    Object.assign(bill, d)
    // 票据
    Object.keys(invoice).forEach((k) => delete invoice[k])
    Object.assign(invoice, d.invoice || {})
    // 最近判读
    Object.keys(latestCheck).forEach((k) => delete latestCheck[k])
    Object.assign(latestCheck, d.latest_check || { issues: [] })
    latestCheck.issues = d.latest_check?.issues || []
    logs.value = d.logs || []
    // 票据原件
    if (d.has_invoice && d.invoice) {
      await loadInvoiceFile()
    }
    // 已生成凭证时补查凭证 ID（详情契约未直接返回 voucher_id）
    if (d.status === '已生成凭证') await findVoucher(d.id)
  } finally {
    loading.value = false
  }
}

async function loadInvoiceFile() {
  try {
    const blob = await reimburseApi.invoiceFile(billId.value)
    if (blob?.type?.includes('json')) { invoiceError.value = '无票据原件'; return }
    revokeInvoice()
    invoiceIsImage.value = (blob?.type || '').includes('image')
    invoiceUrl.value = URL.createObjectURL(blob)
  } catch {
    invoiceError.value = '票据原件加载失败'
  }
}

/** 通过凭证列表反查该报销单生成的凭证 */
async function findVoucher(rid) {
  try {
    const res = await voucherApi.list({ page: 1, page_size: 100 })
    const hit = (res?.list || []).find((v) => v.reimbursement_id === rid || v.bill?.id === rid)
    voucherId.value = hit?.id || null
  } catch {
    voucherId.value = null
  }
}

function revokeInvoice() {
  if (invoiceUrl.value) URL.revokeObjectURL(invoiceUrl.value)
  invoiceUrl.value = ''
}
function openInvoice() { if (invoiceUrl.value) window.open(invoiceUrl.value, '_blank') }

// ---- 操作 ----
async function onVoid() {
  let reason = ''
  try {
    const res = await ElMessageBox.prompt(
      `确认作废报销单「${bill.bill_no}」？作废后不可再判读与制证。`, '作废报销单', {
        type: 'warning',
        inputLabel: '作废原因',
        inputPlaceholder: '请填写作废原因（必填）',
        inputValidator: (v) => (v && v.trim().length >= 2) || '请填写不少于 2 个字的作废原因',
        confirmButtonText: '确认作废', cancelButtonText: '取消'
      }
    )
    reason = res.value.trim()
  } catch { return }
  await reimburseApi.void(billId.value, { reason })
  ElMessage.success('已作废')
  load()
}

// ---- 跳转 ----
function goBack() { router.push('/reimburse/list') }
function goEdit() { router.push(`/rmb/bill/${billId.value}/edit`) }
function goCompliance() { router.push(`/rmb/compliance/${billId.value}`) }
function goMakeVoucher() { router.push(`/rmb/voucher/new/${billId.value}`) }
function goVoucher() { if (voucherId.value) router.push(`/rmb/voucher/${voucherId.value}`) }

onMounted(load)
onBeforeUnmount(revokeInvoice)
</script>

<style scoped>
.bd-body { display: flex; flex-direction: column; gap: 12px; min-height: 0; }

/* 摘要卡 */
.summary-card :deep(.el-card__body) { padding: 0; }
.sum-body { display: grid; grid-template-columns: minmax(0, 1fr) 262px; }
.sum-left { padding: 16px 18px; }
.sum-title { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.sum-no { font-size: 17px; font-weight: 700; color: var(--text-1); letter-spacing: .3px; }
.sum-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(168px, 1fr)); gap: 9px 16px; }
.sg-item { display: flex; gap: 6px; font-size: 13px; }
.sg-l { flex: 0 0 64px; color: var(--text-3); }
.sg-v { color: var(--text-1); font-weight: 600; }
.sum-right {
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px;
  border-left: 1px solid var(--border); background: linear-gradient(180deg, #fdfdfd, #fff); padding: 16px;
}
.sr-label { font-size: 12px; color: var(--text-3); }
.sr-amount { font-size: 26px; font-weight: 800; color: #c45656; font-variant-numeric: tabular-nums; }
.sr-sub { font-size: 11px; color: var(--text-3); line-height: 1.5; text-align: center; }
.ov-bar {
  display: flex; align-items: center; gap: 7px; padding: 8px 18px 10px;
  background: #fef0f0; color: #c45656; font-size: 12.5px; border-top: 1px solid #fbc4c4;
}
.ov-bar b { font-weight: 700; }

/* 分级审批留痕条（制度第四条） */
.ap-bar {
  display: flex; align-items: center; gap: 7px; padding: 8px 18px 10px;
  background: #f0f9eb; color: #529b2e; font-size: 12.5px; border-top: 1px solid #c2e7b0;
}
.ap-bar.rejected { background: #fef0f0; color: #c45656; border-top-color: #fbc4c4; }
.ap-bar b { font-weight: 700; }
.ap-hint {
  display: flex; align-items: center; gap: 7px; padding: 8px 18px 10px;
  background: #fdf6ec; color: #b88230; font-size: 12.5px; border-top: 1px solid #f5dab1;
}
.ap-hint b { font-weight: 700; }
/* 有审批权但被数据范围/层级挡住时的说明条 */
.ap-blocked {
  display: flex; align-items: center; gap: 7px; padding: 8px 18px 10px;
  background: #fdf6ec; color: #b88230; font-size: 12.5px; border-top: 1px solid #f5dab1;
}
.sg-hint { color: var(--text-3); font-size: 11.5px; }
.ap-alert { margin-bottom: 16px; }
.ap-tip { color: #b88230; font-size: 12.5px; }

/* Tabs */
.bd-tabs { display: flex; flex-direction: column; min-height: 0; }
.bd-tabs :deep(.el-tabs__header) { margin-bottom: 10px; }
.bd-tabs :deep(.el-tabs__content) { flex: 1 1 auto; min-height: 0; overflow: auto; }

.desc { margin-bottom: 14px; }
.amount { color: #c45656; font-variant-numeric: tabular-nums; }
.sec-title {
  font-size: 13px; font-weight: 700; color: var(--text-1); margin: 14px 0 9px;
  padding-left: 9px; border-left: 3px solid var(--brand);
}
.meta-foot {
  display: flex; gap: 22px; flex-wrap: wrap; margin-top: 12px; padding-top: 10px;
  border-top: 1px dashed var(--border); font-size: 12px; color: var(--text-3);
}
.empty-tab { padding: 8px 0; }

/* 票据 */
.inv-layout { display: grid; grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr); gap: 16px; }
.inv-left, .inv-right { min-width: 0; }
.inv-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.inv-title { font-size: 13px; font-weight: 700; color: var(--text-1); }
.inv-box {
  border: 1px solid var(--border); border-radius: 8px; background: #fafbfc; overflow: hidden;
  height: 460px; display: flex; align-items: center; justify-content: center;
}
.inv-img { max-width: 100%; max-height: 100%; object-fit: contain; }
.inv-pdf { width: 100%; height: 100%; border: 0; }
.inv-empty { display: flex; flex-direction: column; align-items: center; gap: 8px; color: var(--text-3); font-size: 13px; }
.inv-empty .el-icon { font-size: 28px; }
.inv-meta { margin-top: 8px; font-size: 12px; color: var(--text-3); }
.diff-block { margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--border); }
.diff-title { font-size: 12px; font-weight: 600; color: var(--text-2); margin-bottom: 6px; }
.diff-item { display: flex; align-items: flex-start; gap: 6px; font-size: 12px; line-height: 1.6; padding: 5px 9px; border-radius: 6px; margin-bottom: 4px; }
.diff-item .el-icon { flex: 0 0 auto; margin-top: 2px; }
.diff-item.ok { background: #f0f9eb; color: #529b2e; }
.diff-item.warn { background: #fdf6ec; color: #b88230; }

/* 判读摘要 */
.chk-summary {
  display: flex; align-items: center; gap: 18px; padding: 12px 16px; border-radius: 8px;
  margin-bottom: 10px; flex-wrap: wrap;
}
.chk-ok { background: #f0f9eb; }
.chk-warn { background: #fdf6ec; }
.chk-danger { background: #fef0f0; }
.chk-none { background: #f4f4f5; }
.cs-left { text-align: center; min-width: 110px; }
.cs-label { font-size: 12px; color: var(--text-3); }
.cs-value { font-size: 24px; font-weight: 800; letter-spacing: 2px; }
.chk-ok .cs-value { color: #529b2e; }
.chk-warn .cs-value { color: #b88230; }
.chk-danger .cs-value { color: #c45656; }
.cs-mid { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; color: var(--text-2); }
.cs-line b { color: var(--text-1); }
.cs-line b.err { color: #f56c6c; }
.cs-line.meta { font-size: 12px; color: var(--text-3); }
.cs-right { flex: 0 0 auto; }
.chk-summary-text {
  font-size: 13px; line-height: 1.8; color: var(--text-2); white-space: pre-wrap;
  padding: 10px 14px; background: #fbfcfe; border-radius: 8px; margin-bottom: 12px;
}
.rule-table :deep(.row-danger) { background: #fef6f6; }
.rule-table :deep(.row-warn) { background: #fffbf2; }
.rule-code { font-family: ui-monospace, Menlo, Consolas, monospace; font-weight: 700; }
.inc-flag { display: inline-flex; align-items: center; gap: 3px; font-size: 12px; font-weight: 600; color: #f56c6c; cursor: help; }
.cons-ok { display: inline-flex; align-items: center; gap: 3px; font-size: 12px; color: #529b2e; }
.cons-na { font-size: 12px; color: var(--text-3); }

/* 审计轨迹 */
.log-timeline { padding-left: 4px; }
.log-timeline :deep(.el-timeline-item__timestamp) { font-size: 12px; color: var(--text-3); }
.log-card { background: #fbfcfe; border: 1px solid var(--border); border-radius: 7px; padding: 8px 12px; }
.log-head { display: flex; align-items: center; gap: 8px; }
.log-user { font-size: 13px; font-weight: 600; color: var(--text-1); }
.log-detail { margin-top: 5px; font-size: 12px; line-height: 1.65; color: var(--text-2); word-break: break-all; }

@media (max-width: 992px) {
  .sum-body { grid-template-columns: minmax(0, 1fr); }
  .sum-right { border-left: 0; border-top: 1px solid var(--border); }
  .inv-layout { grid-template-columns: minmax(0, 1fr); }
  .inv-box { height: 300px; }
}
</style>
