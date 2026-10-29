<template>
  <div class="page compliance-page">
    <!-- 页头 -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><CircleCheck /></el-icon>合规判读</h2>
        <div class="ph-desc">
          AI 对照《差旅与业务招待费报销管理制度》逐条判读，结论由程序汇总并以程序交叉校验结果为准
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Back" @click="goDetail">报销单详情</el-button>
        <el-button :icon="RefreshRight" :loading="running" type="primary" plain @click="onRerun">重新判读</el-button>
      </div>
    </div>

    <div v-loading="loading" element-loading-text="加载判读结果……" class="cp-loading-wrap">
      <!-- 判读执行中：整块 loading 提示 -->
      <div v-if="running" class="running-box">
        <el-progress :percentage="100" :indeterminate="true" :duration="3" :show-text="false" :stroke-width="6" />
        <div class="running-text">
          <el-icon class="spin"><Loading /></el-icon>
          <span>AI 正在对照制度逐条判读，约 20～60 秒……</span>
        </div>
        <div class="running-sub">判读期间请勿关闭或刷新页面</div>
      </div>

      <template v-else-if="loaded">
        <!-- ============ 顶部：报销单摘要 + 总体结论 ============ -->
        <el-card shadow="never" class="summary-card">
          <div class="sum-body">
            <!-- 左：报销单摘要 -->
            <div class="sum-left">
              <div class="sum-title">
                <span class="sum-no">{{ bill.bill_no }}</span>
                <el-tag size="small" :type="BILL_STATUS_TYPE[bill.status] || 'info'">{{ bill.status }}</el-tag>
              </div>
              <div class="sum-grid">
                <div class="sg-item"><span class="sg-l">报销人</span><span class="sg-v">{{ bill.employee_name || '—' }}</span></div>
                <div class="sg-item"><span class="sg-l">部门</span><span class="sg-v">{{ orDash(bill.department_name) }}</span></div>
                <div class="sg-item"><span class="sg-l">费用类型</span><span class="sg-v">{{ bill.expense_type_name || '—' }}</span></div>
                <div class="sg-item"><span class="sg-l">发生日期</span><span class="sg-v">{{ bill.occur_date || '—' }}</span></div>
                <div class="sg-item"><span class="sg-l">报销金额</span><span class="sg-v amount">¥ {{ fmtMoney(bill.amount) }}</span></div>
                <div class="sg-item"><span class="sg-l">是否附发票</span><span class="sg-v">{{ bill.has_invoice ? '是' : '否' }}</span></div>
              </div>
            </div>
            <!-- 右：总体结论大标签 -->
            <div class="sum-right" :class="resultClass">
              <div class="res-label">总体判读结论</div>
              <div class="res-value">{{ check.overall_result || '未判读' }}</div>
              <div class="res-count" v-if="check.id">
                不合规 <b>{{ countBy('不合规') }}</b> 项 · 需关注 <b>{{ countBy('需关注') }}</b> 项
                <template v-if="check.inconsistency_count">
                  · 程序校验不一致 <b class="inc">{{ check.inconsistency_count }}</b> 项
                </template>
              </div>
              <div class="res-meta" v-if="check.id">
                判读人 {{ check.checked_by || '—' }} · {{ fmtTime(check.checked_at) }}
                <template v-if="check.elapsed"> · 耗时 {{ Number(check.elapsed).toFixed(1) }} 秒</template>
                <template v-if="check.check_no"> · 第 {{ check.check_no }} 次判读</template>
              </div>
            </div>
          </div>

          <!-- AI 总结 -->
          <div v-if="check.summary" class="ai-summary">
            <div class="as-head"><el-icon><ChatLineSquare /></el-icon><span>AI 判读总结</span></div>
            <div class="as-body">{{ check.summary }}</div>
          </div>
        </el-card>

        <!-- ============ 人工覆盖横幅 ============ -->
        <el-alert v-if="bill.override_flag" type="error" :closable="false" show-icon class="override-alert"
                  title="本报销单已经人工覆盖判定">
          <template #default>
            <div class="ov-body">
              <div>覆盖人：<b>{{ bill.override_by || '—' }}</b>
                <template v-if="bill.override_at"> · {{ fmtTime(bill.override_at) }}</template>
              </div>
              <div>覆盖理由：<b class="ov-reason">{{ bill.override_reason || '—' }}</b></div>
              <div class="ov-tip">人工覆盖记录永久留痕，复核环节将重点检查该覆盖依据。</div>
            </div>
          </template>
        </el-alert>

        <!-- ============ 不合规红色横幅 ============ -->
        <el-alert v-if="check.overall_result === '不合规'" type="error" :closable="false" show-icon
                  class="danger-alert"
                  :title="`本报销单有 ${countBy('不合规')} 项不符合《差旅与业务招待费报销管理制度》，暂不能生成凭证，请根据下列提示整改后重新判读。`" />

        <!-- ============ 需关注黄色横幅 ============ -->
        <el-alert v-else-if="check.overall_result === '需关注'" type="warning" :closable="false" show-icon
                  class="warn-alert"
                  :title="`本报销单有 ${countBy('需关注')} 项需要关注${check.inconsistency_count ? `、${check.inconsistency_count} 项与程序校验不一致` : ''}，确认补充说明后可提交制证。`" />

        <el-alert v-else-if="check.inconsistency_count" type="warning" :closable="false" show-icon class="warn-alert"
                  :title="`判读过程中有 ${check.inconsistency_count} 项 AI 结论与程序校验不一致，已按程序校验结果降级为「需关注」，请人工核查。`" />

        <!-- ============ 问题清单 ============ -->
        <el-card shadow="never" class="list-card">
          <template #header>
            <div class="card-head">
              <span class="card-title">问题清单</span>
              <div class="head-ops">
                <el-radio-group v-model="resultFilter" size="small">
                  <el-radio-button value="">全部 {{ issues.length }}</el-radio-button>
                  <el-radio-button value="不合规">不合规 {{ countBy('不合规') }}</el-radio-button>
                  <el-radio-button value="需关注">需关注 {{ countBy('需关注') }}</el-radio-button>
                  <el-radio-button value="其他">合规/不适用 {{ countBy('合规') + countBy('不适用') }}</el-radio-button>
                </el-radio-group>
                <el-button link type="primary" @click="expandAll = !expandAll">
                  {{ expandAll ? '全部收起' : '全部展开' }}
                </el-button>
              </div>
            </div>
          </template>

          <!-- 主问题（不合规 / 需关注）：完整表格 -->
          <div class="issue-section">
            <div class="sec-label danger">
              <el-icon><WarningFilled /></el-icon>
              <span>需整改 / 需关注项</span>
              <span class="sec-count">{{ mainIssues.length }} 条</span>
            </div>
            <el-table v-if="mainIssues.length" :data="mainIssues" border size="small" class="issue-table"
                      :row-class-name="mainRowClass" empty-text="无">
              <el-table-column label="规则" width="74" align="center">
                <template #default="{ row }">
                  <span class="rule-code">{{ row.rule_code || '—' }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="check_item" label="检查项" width="150" show-overflow-tooltip>
                <template #default="{ row }"><span class="check-item">{{ row.check_item || '—' }}</span></template>
              </el-table-column>
              <el-table-column prop="clause_no" label="制度条款" width="104" align="center">
                <template #default="{ row }">{{ row.clause_no || '—' }}</template>
              </el-table-column>
              <el-table-column label="结论" width="92" align="center">
                <template #default="{ row }">
                  <el-tag :type="RESULT_TYPE[row.result] || 'info'" size="small" effect="dark" class="res-tag">
                    {{ row.result || '—' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="不符合理由" min-width="240">
                <template #default="{ row }">
                  <div class="reason-text" :class="{ highlighted: row.result === '不合规' }">{{ row.reason || '—' }}</div>
                </template>
              </el-table-column>
              <el-table-column label="提示与建议" min-width="220">
                <template #default="{ row }">
                  <div class="suggest-text">{{ row.suggestion || '—' }}</div>
                </template>
              </el-table-column>
              <el-table-column label="依据数据" width="180">
                <template #default="{ row }">
                  <div class="evidence-text" :title="row.evidence || ''">{{ row.evidence || '—' }}</div>
                </template>
              </el-table-column>
              <el-table-column label="程序校验" width="130" align="center">
                <template #default="{ row }">
                  <el-tooltip v-if="row.consistency === '不一致'" placement="top">
                    <template #content>
                      <div class="inc-tip">
                        程序校验结论：{{ programText(row) }}<br />
                        AI 结论与该校验结果相反，已按程序校验降级处理，请人工确认。
                      </div>
                    </template>
                    <span class="inc-flag"><el-icon><Warning /></el-icon>与程序校验不一致</span>
                  </el-tooltip>
                  <span v-else-if="row.consistency === '一致'" class="cons-ok">
                    <el-icon><CircleCheck /></el-icon>一致
                  </span>
                  <span v-else class="cons-na">未校验</span>
                </template>
              </el-table-column>
            </el-table>
            <div v-else class="empty-hint">本次判读未发现不合规或需关注项</div>
          </div>

          <!-- 合规 / 不适用：默认折叠 -->
          <div class="issue-section">
            <div class="sec-label ok" @click="showPassed = !showPassed">
              <el-icon><ArrowRight v-if="!showPassed" /><ArrowDown v-else /></el-icon>
              <span>合规 / 不适用项</span>
              <span class="sec-count">{{ passedIssues.length }} 条（默认收起）</span>
            </div>
            <el-collapse v-show="showPassed || expandAll" v-model="passedCollapse" class="passed-collapse">
              <el-collapse-item v-for="row in passedIssues" :key="row.rule_code || row.id" :name="row.rule_code || String(row.id)">
                <template #title>
                  <div class="pc-title">
                    <span class="rule-code">{{ row.rule_code || '—' }}</span>
                    <span class="pc-item">{{ row.check_item || '—' }}</span>
                    <span class="pc-clause">{{ row.clause_no || '' }}</span>
                    <el-tag :type="RESULT_TYPE[row.result] || 'info'" size="small" effect="plain">{{ row.result }}</el-tag>
                    <span v-if="row.consistency === '不一致'" class="inc-flag small">
                      <el-icon><Warning /></el-icon>与程序校验不一致
                    </span>
                  </div>
                </template>
                <div class="pc-body">
                  <div class="pc-row"><span class="pc-l">理由</span><span class="pc-v">{{ row.reason || '—' }}</span></div>
                  <div class="pc-row"><span class="pc-l">建议</span><span class="pc-v">{{ row.suggestion || '—' }}</span></div>
                  <div class="pc-row"><span class="pc-l">依据数据</span><span class="pc-v">{{ row.evidence || '—' }}</span></div>
                  <div class="pc-row"><span class="pc-l">程序校验</span><span class="pc-v">{{ row.consistency || '未校验' }}</span></div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>
        </el-card>

        <!-- ============ 可折叠：程序事实 / AI 原始输出 / 历次记录 ============ -->
        <el-card shadow="never" class="fold-card">
          <el-collapse v-model="foldPanels">
            <el-collapse-item name="facts">
              <template #title>
                <div class="fold-title"><el-icon><DataLine /></el-icon>程序计算的事实（判读依据）</div>
              </template>
              <div class="fold-hint">
                以下数值由程序从数据库直接计算并写入判读提示词，AI 的星期、节假日、人均金额、每晚金额等判断以此为准。
              </div>
              <pre class="json-box">{{ prettyFacts }}</pre>
            </el-collapse-item>

            <el-collapse-item name="raw">
              <template #title>
                <div class="fold-title"><el-icon><Document /></el-icon>AI 原始输出</div>
              </template>
              <pre class="json-box raw">{{ prettyRaw }}</pre>
            </el-collapse-item>

            <el-collapse-item name="history">
              <template #title>
                <div class="fold-title"><el-icon><Clock /></el-icon>历次判读记录（{{ history.length }} 次）</div>
              </template>
              <el-table v-if="history.length" :data="history" border size="small" empty-text="暂无历史判读">
                <el-table-column prop="check_no" label="次数" width="70" align="center">
                  <template #default="{ row }">第 {{ row.check_no }} 次</template>
                </el-table-column>
                <el-table-column label="结论" width="100" align="center">
                  <template #default="{ row }">
                    <el-tag :type="RESULT_TYPE[row.overall_result] || 'info'" size="small">{{ row.overall_result }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="AI 结论" width="100" align="center">
                  <template #default="{ row }">
                    <span :class="{ 'ai-diff': row.ai_overall_result && row.ai_overall_result !== row.overall_result }">
                      {{ row.ai_overall_result || '—' }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column prop="inconsistency_count" label="不一致" width="80" align="center" />
                <el-table-column prop="summary" label="总结" min-width="240" show-overflow-tooltip />
                <el-table-column prop="checked_by" label="判读人" width="100" />
                <el-table-column label="判读时间" width="150">
                  <template #default="{ row }">{{ fmtTime(row.checked_at) }}</template>
                </el-table-column>
                <el-table-column label="处理" width="150">
                  <template #default="{ row }">
                    <span v-if="row.handle_action">{{ row.handle_action }} · {{ row.handled_by || '' }}</span>
                    <span v-else class="muted">未处理</span>
                  </template>
                </el-table-column>
              </el-table>
              <div v-else class="empty-hint">暂无历史判读记录</div>
            </el-collapse-item>
          </el-collapse>
        </el-card>

        <!-- ============ 底部操作区 ============ -->
        <el-card shadow="never" class="action-card">
          <template #header>
            <div class="card-head"><span class="card-title">处理判读结论</span>
              <span class="card-hint">处理动作会写入审计日志，人工覆盖将永久留痕</span>
            </div>
          </template>
          <div class="act-body">
            <!-- 合规：直接提交制证 -->
            <template v-if="check.overall_result === '合规'">
              <div class="act-tip ok">
                <el-icon><CircleCheck /></el-icon>
                <span>本报销单合规，可直接提交制证。</span>
              </div>
              <div class="act-row">
                <el-button type="primary" :icon="Promotion" :loading="handling === 'submit'"
                           v-permission="'reimburse:check:run'" @click="doSubmit()">提交制证</el-button>
              </div>
            </template>

            <!-- 需关注：填补充说明后提交 -->
            <template v-else-if="check.overall_result === '需关注'">
              <div class="act-tip warn">
                <el-icon><Warning /></el-icon>
                <span>本报销单存在需关注项，提交制证前须填写补充说明，复核时将被重点检查。</span>
              </div>
              <el-input v-model="submitComment" type="textarea" :rows="3" maxlength="500" show-word-limit
                        placeholder="请填写补充说明（必填，不少于 5 个字），如：周末招待客户系展会临时安排，已获总经理特批" />
              <div class="act-row">
                <el-button type="primary" :icon="Promotion" :loading="handling === 'submit'"
                           :disabled="submitComment.trim().length < 5"
                           v-permission="'reimburse:check:run'" @click="doSubmit()">确认并提交制证</el-button>
              </div>
            </template>

            <!-- 不合规：修改 / 重判 / 作废 / 人工覆盖 -->
            <template v-else-if="check.overall_result === '不合规'">
              <div class="act-tip danger">
                <el-icon><CircleClose /></el-icon>
                <span>本报销单存在不合规项，暂不能生成凭证。请先按提示整改后重新判读，或经授权人工覆盖判定。</span>
              </div>
              <div class="act-row">
                <el-button type="primary" plain :icon="EditPen" v-permission="'reimburse:bill:edit'"
                           @click="goEdit">修改报销信息</el-button>
                <el-button type="warning" plain :icon="RefreshRight" v-permission="'reimburse:check:run'"
                           @click="onRerun">重新判读</el-button>
                <el-button v-if="canVoid" type="danger" plain :icon="CircleClose"
                           v-permission="['reimburse:bill:delete', 'reimburse:bill:edit']" @click="onVoid">作废报销单</el-button>
                <el-tooltip v-if="!canOverride" placement="top">
                  <template #content>
                    <span v-if="!hasOverridePerm">需要「人工覆盖判定」权限（reimburse:check:override）</span>
                    <span v-else>不能覆盖本人报销的报销单，请由他人处理</span>
                  </template>
                  <span><el-button type="danger" :icon="WarningFilled" disabled>人工覆盖判定</el-button></span>
                </el-tooltip>
                <el-button v-else type="danger" :icon="WarningFilled" @click="openOverride">人工覆盖判定</el-button>
              </div>
            </template>

            <!-- 无判读结果 -->
            <template v-else>
              <div class="act-tip">
                <el-icon><InfoFilled /></el-icon>
                <span>本报销单尚未判读，请先执行 AI 合规判读。</span>
              </div>
              <div class="act-row">
                <el-button type="primary" :icon="MagicStick" :loading="running"
                           v-permission="'reimburse:check:run'" @click="onRerun">开始 AI 合规判读</el-button>
              </div>
            </template>
          </div>
        </el-card>
      </template>

      <!-- 加载失败 / 无数据 -->
      <el-empty v-else-if="!loading" description="暂无判读数据">
        <el-button type="primary" :loading="running" v-permission="'reimburse:check:run'" @click="onRerun">
          开始 AI 合规判读
        </el-button>
      </el-empty>
    </div>

    <!-- 人工覆盖弹窗 -->
    <el-dialog v-model="overrideDlg.visible" title="人工覆盖判定" width="600px" :close-on-click-modal="false">
      <el-alert type="error" :closable="false" show-icon class="ov-dlg-alert"
                title="人工覆盖将把该不合规报销单直接置为「待制证」"
                description="该操作仅限具备覆盖权限且非报销人本人的用户执行，理由将写入审计日志并永久留痕，复核环节会重点核查。" />
      <div class="ov-dlg-cur">
        <span class="odl">当前判读结论</span>
        <el-tag type="danger">{{ check.overall_result }}</el-tag>
        <span class="odl">不合规项</span>
        <b>{{ countBy('不合规') }} 项</b>
      </div>
      <el-form label-width="88px">
        <el-form-item label="覆盖理由" required>
          <el-input v-model="overrideDlg.reason" type="textarea" :rows="4" maxlength="500" show-word-limit
                    placeholder="请详细说明覆盖依据（不少于 10 个字），如：该笔住宿超标系展会期间市区房价整体上涨，已取得总经理书面特批，特批单号 SP202610001" />
          <div class="ov-len" :class="{ ok: overrideDlg.reason.trim().length >= 10 }">
            已输入 {{ overrideDlg.reason.trim().length }} / 10 字
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="overrideDlg.visible = false">取 消</el-button>
        <el-button type="danger" :loading="handling === 'override'"
                   :disabled="overrideDlg.reason.trim().length < 10" @click="doOverride">确认覆盖并提交制证</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  CircleCheck, CircleClose, Warning, WarningFilled, Back, RefreshRight, Loading, Promotion,
  EditPen, MagicStick, ChatLineSquare, DataLine, Document, Clock, ArrowRight, ArrowDown, InfoFilled
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { complianceApi } from '@/api/compliance'
import { useUserStore } from '@/store/user'
import {
  BILL_STATUS_TYPE, RESULT_TYPE, fmtMoney, fmtTime, orDash
} from './constants'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const billId = computed(() => route.params.id)

const loading = ref(false)
const running = ref(false)
const loaded = ref(false)
const handling = ref('')

const bill = reactive({})
const check = reactive({ issues: [] })
const history = ref([])

// 交互状态
const resultFilter = ref('')
const showPassed = ref(false)
const expandAll = ref(false)
const passedCollapse = ref([])
const foldPanels = ref([])
const submitComment = ref('')

const overrideDlg = reactive({ visible: false, reason: '' })

// ---- 派生 ----
const issues = computed(() => check.issues || [])
const RESULT_ORDER = { 不合规: 0, 需关注: 1, 合规: 2, 不适用: 3 }
/** 主问题：不合规 + 需关注，按「不合规 → 需关注」排序 */
const mainIssues = computed(() => issues.value
  .filter((i) => ['不合规', '需关注'].includes(i.result))
  .filter((i) => {
    if (!resultFilter.value) return true
    if (resultFilter.value === '其他') return false
    return i.result === resultFilter.value
  })
  .slice()
  .sort((a, b) => (RESULT_ORDER[a.result] ?? 9) - (RESULT_ORDER[b.result] ?? 9)
    || String(a.rule_code).localeCompare(String(b.rule_code))))
/** 合规 / 不适用：默认收起 */
const passedIssues = computed(() => issues.value
  .filter((i) => ['合规', '不适用'].includes(i.result) || (resultFilter.value === '其他' && !['不合规', '需关注'].includes(i.result)))
  .slice()
  .sort((a, b) => (RESULT_ORDER[a.result] ?? 9) - (RESULT_ORDER[b.result] ?? 9)
    || String(a.rule_code).localeCompare(String(b.rule_code))))

const countBy = (r) => issues.value.filter((i) => i.result === r).length

const resultClass = computed(() => ({
  合规: 'res-ok', 需关注: 'res-warn', 不合规: 'res-danger'
}[check.overall_result] || 'res-none'))

const prettyFacts = computed(() => {
  const f = check.facts
  if (!f) return '（后端未返回程序计算的事实）'
  try {
    return JSON.stringify(typeof f === 'string' ? JSON.parse(f) : f, null, 2)
  } catch {
    return String(f)
  }
})

/** AI 原始输出：兼容 JSON 字符串，尽量格式化后展示 */
const prettyRaw = computed(() => {
  const raw = check.ai_raw_text
  if (!raw) return '（后端未返回原始输出）'
  const text = String(raw).trim()
  // 去掉可能存在的 ```json 代码块围栏
  const cleaned = text.replace(/^```(?:json)?\s*/i, '').replace(/```\s*$/, '')
  try {
    return JSON.stringify(JSON.parse(cleaned), null, 2)
  } catch {
    return text
  }
})

/** 程序校验结论的文案 */
function programText(row) {
  if (row.program_triggered === 1) return '程序判定该规则被触发'
  if (row.program_triggered === 0) return '程序判定该规则未被触发'
  return '该规则无程序校验'
}

function mainRowClass({ row }) {
  return row.result === '不合规' ? 'row-danger' : (row.result === '需关注' ? 'row-warn' : '')
}

// ---- 人工覆盖权限：需 check:override 且操作人不能是报销人本人 ----
const hasOverridePerm = computed(() => userStore.hasPermission('reimburse:check:override'))
const isSelfBill = computed(() => {
  const me = userStore.userInfo
  if (!me) return false
  const myName = me.real_name || me.username
  return !!bill.employee_name && (bill.employee_name === myName)
})
const canOverride = computed(() => hasOverridePerm.value && !isSelfBill.value)
// ---- 作废权限：由后端按「作废权限 / 是否本人单据 / 是否已审批 / 是否已生成凭证」判定 ----
const canVoid = computed(() => !!bill.can_void)

// ---- 加载与判读 ----
async function load() {
  loading.value = true
  try {
    const res = await complianceApi.detail(billId.value)
    Object.assign(bill, res?.bill || {})
    Object.keys(check).forEach((k) => delete check[k])
    Object.assign(check, res?.check || {})
    // issues / facts 在契约里可能为 JSON 字符串，统一成数组/对象
    check.issues = normalizeIssues(res?.check?.issues)
    history.value = res?.history || []
    loaded.value = !!res?.check
    // 默认展开事实面板（判读依据是重点）
    foldPanels.value = ['facts']
  } finally {
    loading.value = false
  }
}

/** issues 兼容后端返回数组或 JSON 字符串 */
function normalizeIssues(raw) {
  if (Array.isArray(raw)) return raw
  if (typeof raw === 'string' && raw.trim()) {
    try {
      const parsed = JSON.parse(raw)
      return Array.isArray(parsed) ? parsed : []
    } catch { return [] }
  }
  return []
}

async function onRerun() {
  running.value = true
  try {
    await complianceApi.run(billId.value)
    ElMessage.success('判读完成')
    await load()
  } catch {
    // 失败提示已由 request 拦截器给出
    if (!loaded.value) running.value = false
  } finally {
    running.value = false
  }
}

// ---- 处理动作 ----
async function doSubmit() {
  const comment = submitComment.value.trim()
  if (check.overall_result === '需关注' && comment.length < 5) {
    return ElMessage.warning('请填写不少于 5 个字的补充说明')
  }
  try {
    await ElMessageBox.confirm(
      check.overall_result === '合规'
        ? '确认提交制证？提交后本单进入「待制证」，由制单员生成记账凭证。'
        : '确认并提交制证？补充说明将随本单留痕，复核时将重点检查。',
      '提交制证', { type: 'warning', confirmButtonText: '确认提交', cancelButtonText: '取消' }
    )
  } catch { return }
  handling.value = 'submit'
  try {
    await complianceApi.handle(billId.value, { action: 'submit', comment })
    ElMessage.success('已提交制证')
    await load()
  } finally {
    handling.value = ''
  }
}

async function onVoid() {
  let reason = ''
  try {
    const res = await ElMessageBox.prompt('作废后本报销单不可再判读与制证，请填写作废原因。', '作废报销单', {
      type: 'warning',
      inputLabel: '作废原因',
      inputPlaceholder: '请填写作废原因（必填）',
      inputValidator: (v) => (v && v.trim().length >= 2) || '请填写不少于 2 个字的作废原因',
      confirmButtonText: '确认作废', cancelButtonText: '取消'
    })
    reason = res.value.trim()
  } catch { return }
  handling.value = 'void'
  try {
    await complianceApi.handle(billId.value, { action: 'void', comment: reason })
    ElMessage.success('已作废')
    router.push('/reimburse/list')
  } finally {
    handling.value = ''
  }
}

function openOverride() {
  overrideDlg.reason = ''
  overrideDlg.visible = true
}

async function doOverride() {
  const reason = overrideDlg.reason.trim()
  if (reason.length < 10) return ElMessage.warning('覆盖理由不得少于 10 个字')
  try {
    await ElMessageBox.confirm(
      `确认人工覆盖判读结论？该操作会将本单直接置为「待制证」，覆盖人 ${userStore.userInfo?.real_name || ''} 与理由将永久留痕。`,
      '二次确认', { type: 'warning', confirmButtonText: '确认覆盖', cancelButtonText: '取消' }
    )
  } catch { return }
  handling.value = 'override'
  try {
    await complianceApi.handle(billId.value, { action: 'override', comment: reason })
    overrideDlg.visible = false
    ElMessage.success('已人工覆盖判定，本单进入待制证')
    await load()
  } finally {
    handling.value = ''
  }
}

// ---- 跳转 ----
function goDetail() { router.push(`/rmb/bill/${billId.value}`) }
function goEdit() { router.push(`/rmb/bill/${billId.value}/edit`) }

onMounted(async () => {
  await load()
  // 从列表点「判读」进入时带 auto=1：没有任何判读记录则自动执行一次
  if (route.query.auto === '1' && !check.id) {
    await onRerun()
  }
})
</script>

<style scoped>
.cp-loading-wrap { display: flex; flex-direction: column; gap: 12px; min-height: 0; }

/* 判读执行中 */
.running-box {
  display: flex; flex-direction: column; gap: 14px; align-items: center; justify-content: center;
  padding: 60px 24px; background: #fff; border: 1px solid var(--border); border-radius: var(--radius);
}
.running-box :deep(.el-progress) { width: 60%; }
.running-text { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; color: var(--brand-dark); }
.running-sub { font-size: 12px; color: var(--text-3); }
.spin { animation: spin 1.2s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* 摘要卡 */
.summary-card :deep(.el-card__body) { padding: 0; }
.sum-body { display: grid; grid-template-columns: minmax(0, 1fr) 300px; }
.sum-left { padding: 16px 18px; }
.sum-title { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.sum-no { font-size: 17px; font-weight: 700; color: var(--text-1); letter-spacing: .3px; }
.sum-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 9px 16px; }
.sg-item { display: flex; gap: 6px; font-size: 13px; }
.sg-l { flex: 0 0 64px; color: var(--text-3); }
.sg-v { color: var(--text-1); font-weight: 600; }
.sg-v.amount { color: #c45656; font-variant-numeric: tabular-nums; }

.sum-right {
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px;
  padding: 18px 16px; border-left: 1px solid var(--border); text-align: center;
}
.res-label { font-size: 12px; color: var(--text-3); }
.res-value { font-size: 34px; font-weight: 800; letter-spacing: 4px; line-height: 1.15; }
.res-ok .res-value { color: #67c23a; }
.res-warn .res-value { color: #e6a23c; }
.res-danger .res-value { color: #f56c6c; }
.res-none .res-value { color: var(--text-3); }
.res-ok { background: linear-gradient(180deg, #f3fbf0, #fff); }
.res-warn { background: linear-gradient(180deg, #fff9ec, #fff); }
.res-danger { background: linear-gradient(180deg, #fff2f2, #fff); }
.res-count { font-size: 12px; color: var(--text-2); }
.res-count b { color: var(--text-1); }
.res-count b.inc { color: #f56c6c; }
.res-meta { font-size: 12px; color: var(--text-3); line-height: 1.5; }

.ai-summary { padding: 12px 18px 16px; border-top: 1px dashed var(--border); background: #fbfcfe; }
.as-head { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; color: var(--text-1); margin-bottom: 6px; }
.as-body { font-size: 13px; line-height: 1.8; color: var(--text-2); white-space: pre-wrap; }

/* 横幅 */
.override-alert, .danger-alert, .warn-alert { margin: 0; }
.ov-body { display: flex; flex-direction: column; gap: 4px; font-size: 13px; line-height: 1.7; }
.ov-reason { color: #f56c6c; }
.ov-tip { font-size: 12px; opacity: .85; }

/* 问题清单 */
.card-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.card-title { font-weight: 700; color: var(--text-1); }
.card-hint { font-size: 12px; color: var(--text-3); }
.head-ops { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.issue-section + .issue-section { margin-top: 16px; }
.sec-label { display: flex; align-items: center; gap: 7px; font-size: 13px; font-weight: 700; margin-bottom: 9px; }
.sec-label.danger { color: #c45656; }
.sec-label.ok { color: var(--text-2); cursor: pointer; user-select: none; }
.sec-count { font-size: 12px; font-weight: 400; color: var(--text-3); }
.issue-table :deep(.row-danger) { background: #fef6f6; }
.issue-table :deep(.row-warn) { background: #fffbf2; }
.rule-code { font-family: ui-monospace, Menlo, Consolas, monospace; font-weight: 700; color: var(--text-1); }
.check-item { font-weight: 600; color: var(--text-1); }
.res-tag { letter-spacing: 1px; }
.reason-text { font-size: 12.5px; line-height: 1.65; color: var(--text-2); white-space: pre-wrap; }
.reason-text.highlighted { color: #c45656; font-weight: 500; }
.suggest-text { font-size: 12.5px; line-height: 1.65; color: #529b2e; white-space: pre-wrap; }
.evidence-text {
  font-size: 12px; line-height: 1.5; color: var(--text-3); font-family: ui-monospace, Menlo, Consolas, monospace;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
}
.inc-flag { display: inline-flex; align-items: center; gap: 3px; font-size: 12px; font-weight: 600; color: #f56c6c; cursor: help; }
.inc-flag.small { font-size: 11px; }
.inc-tip { font-size: 12px; line-height: 1.7; }
.cons-ok { display: inline-flex; align-items: center; gap: 3px; font-size: 12px; color: #529b2e; }
.cons-na { font-size: 12px; color: var(--text-3); }
.empty-hint { font-size: 13px; color: var(--text-3); padding: 12px 0 4px; }

.passed-collapse { border-top: 1px solid var(--border); border-bottom: 0; }
.passed-collapse :deep(.el-collapse-item__header) { height: auto; padding: 8px 0; line-height: 1.5; }
.pc-title { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 13px; }
.pc-item { font-weight: 600; color: var(--text-2); }
.pc-clause { font-size: 12px; color: var(--text-3); }
.pc-body { padding: 4px 0 10px 12px; display: flex; flex-direction: column; gap: 6px; }
.pc-row { display: flex; gap: 10px; font-size: 12.5px; line-height: 1.65; }
.pc-l { flex: 0 0 62px; color: var(--text-3); }
.pc-v { color: var(--text-2); white-space: pre-wrap; }

/* 折叠区 */
.fold-card :deep(.el-card__body) { padding: 4px 16px; }
.fold-title { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; color: var(--text-1); }
.fold-hint { font-size: 12px; color: var(--text-3); line-height: 1.7; margin-bottom: 8px; }
.json-box {
  margin: 0; padding: 12px 14px; background: #f7f9fc; border: 1px solid var(--border); border-radius: 8px;
  font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; line-height: 1.65;
  color: #334155; max-height: 420px; overflow: auto; white-space: pre-wrap; word-break: break-all;
}
.json-box.raw { background: #fcfcfd; color: #475569; }
.ai-diff { color: #f56c6c; font-weight: 600; }
.muted { color: var(--text-3); }

/* 操作区 */
.act-body { display: flex; flex-direction: column; gap: 12px; }
.act-tip { display: flex; align-items: flex-start; gap: 7px; font-size: 13px; line-height: 1.7; }
.act-tip .el-icon { flex: 0 0 auto; margin-top: 2px; }
.act-tip.ok { color: #529b2e; }
.act-tip.warn { color: #b88230; }
.act-tip.danger { color: #c45656; }
.act-row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }

/* 人工覆盖弹窗 */
.ov-dlg-alert { margin-bottom: 14px; }
.ov-dlg-cur { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; font-size: 13px; }
.odl { color: var(--text-3); }
.ov-len { font-size: 12px; color: var(--text-3); margin-top: 4px; }
.ov-len.ok { color: #529b2e; }

@media (max-width: 992px) {
  .sum-body { grid-template-columns: minmax(0, 1fr); }
  .sum-right { border-left: 0; border-top: 1px solid var(--border); }
}
</style>
