<template>
  <div class="page">
    <!-- 页头：标题 + 说明 + 主操作 -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Wallet /></el-icon>费用报销</h2>
        <div class="ph-desc">
          差旅费与业务招待费报销单，保存后由 AI 对照《差旅与业务招待费报销管理制度》逐条判读 · 共 <b>{{ total }}</b> 条
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
        <el-button type="primary" :icon="Plus" v-permission="'reimburse:bill:add'" @click="onAdd">填写报销单</el-button>
      </div>
    </div>

    <el-card shadow="never" class="card-fill">
      <div class="toolbar">
        <el-form :inline="true" :model="query" class="tb-left">
          <el-form-item label="关键字">
            <el-input v-model="query.keyword" placeholder="报销单号 / 报销人 / 事由" clearable
                      style="width: 210px" @keyup.enter="onSearch" />
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="query.status" placeholder="全部" clearable style="width: 132px">
              <el-option v-for="s in BILL_STATUS" :key="s" :label="s" :value="s" />
            </el-select>
          </el-form-item>
          <el-form-item label="费用类型">
            <el-select v-model="query.expense_type_id" placeholder="全部" clearable style="width: 140px">
              <el-option v-for="t in expenseTypes" :key="t.id" :label="t.name" :value="t.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="报销日期">
            <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD"
                            range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期"
                            style="width: 250px" @change="onSearch" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :icon="Search" @click="onSearch">查询</el-button>
            <el-button :icon="RefreshLeft" @click="onReset">重置</el-button>
          </el-form-item>
        </el-form>
      </div>

      <div class="table-wrap">
        <el-table :data="list" v-loading="loading" border stripe empty-text="暂无报销单，点击右上角「填写报销单」开始">
          <el-table-column prop="bill_no" label="报销单号" width="168" fixed="left" show-overflow-tooltip>
            <template #default="{ row }">
              <el-button link type="primary" class="no-btn" @click="onView(row)">{{ row.bill_no }}</el-button>
            </template>
          </el-table-column>
          <el-table-column prop="bill_date" label="报销日期" width="112" align="center">
            <template #default="{ row }">{{ orDash(row.bill_date) }}</template>
          </el-table-column>
          <el-table-column prop="employee_name" label="报销人" width="100" show-overflow-tooltip />
          <el-table-column prop="department_name" label="部门" width="120" show-overflow-tooltip>
            <template #default="{ row }">{{ orDash(row.department_name) }}</template>
          </el-table-column>
          <el-table-column prop="expense_type_name" label="费用类型" width="128" show-overflow-tooltip />
          <el-table-column prop="occur_date" label="发生日期" width="112" align="center" />
          <el-table-column prop="amount" label="金额(元)" width="126" align="right" class-name="col-num">
            <template #default="{ row }"><span class="amount">{{ fmtMoney(row.amount) }}</span></template>
          </el-table-column>
          <el-table-column label="判读结论" width="108" align="center">
            <template #default="{ row }">
              <el-tag :type="RESULT_TYPE[row.compliance_result] || 'info'" size="small" effect="light">
                {{ row.compliance_result || '未判读' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="审批" width="96" align="center">
            <template #default="{ row }">
              <el-tooltip
                :content="row.approval_status === '已审批'
                  ? `审批人：${row.approval_by || '—'}${row.approval_comment ? '；意见：' + row.approval_comment : ''}`
                  : (row.approval_status === '已驳回'
                    ? `驳回人：${row.approval_by || '—'}${row.approval_comment ? '；原因：' + row.approval_comment : ''}`
                    : '尚未完成分级审批（制度第四条）')"
                placement="top">
                <el-tag :type="APPROVAL_TYPE[row.approval_status] || 'info'" size="small" effect="plain">
                  {{ row.approval_status || '未审批' }}
                </el-tag>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="112" align="center">
            <template #default="{ row }">
              <el-tag :type="BILL_STATUS_TYPE[row.status] || 'info'" size="small">{{ row.status }}</el-tag>
              <el-tooltip v-if="row.override_flag" content="该报销单经人工覆盖判定" placement="top">
                <el-tag type="danger" size="small" effect="plain" class="ov-tag">覆盖</el-tag>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="252" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="onView(row)">查看</el-button>
              <el-button link type="primary" :disabled="!canEdit(row)" v-permission="'reimburse:bill:edit'"
                         @click="onEdit(row)">编辑</el-button>
              <el-button link type="warning" :disabled="!canCheck(row)" v-permission="'reimburse:check:run'"
                         @click="onCheck(row)">判读</el-button>
              <el-button link type="success" :disabled="!canMakeVoucher(row)" v-permission="'reimburse:voucher:make'"
                         @click="onMakeVoucher(row)">制证</el-button>
              <el-tooltip :disabled="!voidBlockedTip(row)" placement="top" :content="voidBlockedTip(row)">
                <span>
                  <el-button link type="danger" :disabled="!canVoid(row)"
                             v-permission="['reimburse:bill:delete', 'reimburse:bill:edit']" @click="onVoid(row)">作废</el-button>
                </span>
              </el-tooltip>
              <el-button link type="danger" :disabled="!canDelete(row)"
                         v-permission="['reimburse:bill:delete', 'reimburse:bill:edit']" @click="onDelete(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="pager">
        <span class="hint">共 <b>{{ total }}</b> 条 · 第 {{ query.page }} / {{ pageCount }} 页</span>
        <el-pagination background layout="sizes, prev, pager, next" :total="total"
                       v-model:current-page="query.page" v-model:page-size="query.page_size"
                       :page-sizes="[10, 20, 50, 100]"
                       @current-change="fetchList" @size-change="fetchList" />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Search, Refresh, RefreshLeft, Plus, Wallet } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { reimburseApi } from '@/api/reimburse'
import {
  BILL_STATUS, BILL_STATUS_TYPE, RESULT_TYPE, APPROVAL_TYPE, fmtMoney, orDash
} from './constants'

const router = useRouter()

// ---- 筛选与分页 ----
const query = reactive({ page: 1, page_size: 20, keyword: '', status: '', expense_type_id: null, date_from: '', date_to: '' })
const dateRange = ref([])
const list = ref([])
const total = ref(0)
const loading = ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))

// 费用类型下拉来自填单页同一份 meta（普通用户也有该权限）
const expenseTypes = ref([])

async function loadMeta() {
  try {
    const res = await reimburseApi.meta()
    expenseTypes.value = res?.expense_types || []
  } catch {
    expenseTypes.value = []
  }
}

async function fetchList() {
  loading.value = true
  try {
    query.date_from = dateRange.value?.[0] || ''
    query.date_to = dateRange.value?.[1] || ''
    const res = await reimburseApi.list({ ...query, date_from: query.date_from || undefined, date_to: query.date_to || undefined })
    list.value = res?.list || []
    total.value = res?.total || 0
  } finally {
    loading.value = false
  }
}

function onSearch() { query.page = 1; fetchList() }
function onReset() {
  query.keyword = ''
  query.status = ''
  query.expense_type_id = null
  dateRange.value = []
  onSearch()
}

// ---- 状态 → 可用操作（前端只做引导，最终以后端返回的标记与校验为准） ----
const EDITABLE = ['待判读', '判读不合规', '待确认']
const CHECKABLE = ['待判读', '判读不合规', '待确认']
const canEdit = (row) => EDITABLE.includes(row.status)
const canCheck = (row) => CHECKABLE.includes(row.status)
const canMakeVoucher = (row) => row.status === '待制证'
const canDelete = (row) => ['待判读', '判读不合规'].includes(row.status)
// 作废可用性由后端判定（含「已审批后报销人不能自行作废」「已生成凭证/已作废不能作废」），
// 前端只读 can_void 标记，避免两端口径不一致
const canVoid = (row) => !!row.can_void
/** 作废被禁用时的原因提示（后端在详情里给，列表按状态/审批状态推导同一口径） */
function voidBlockedTip(row) {
  if (row.can_void) return ''
  if (['已作废', '已生成凭证'].includes(row.status)) {
    return row.status === '已作废' ? '该报销单已作废' : '该报销单已生成凭证，不允许作废'
  }
  if (row.approval_status === '已审批') {
    return '该报销单已审批通过，报销人不能自行作废，请联系具备作废权限的管理人员处理'
  }
  return ''
}

// ---- 跳转 ----
function onAdd() { router.push('/reimburse/new') }
function onView(row) { router.push(`/rmb/bill/${row.id}`) }
function onEdit(row) { router.push(`/rmb/bill/${row.id}/edit`) }
function onCheck(row) { router.push(`/rmb/compliance/${row.id}?auto=1`) }
function onMakeVoucher(row) { router.push(`/rmb/voucher/new/${row.id}`) }

async function onVoid(row) {
  let reason = ''
  try {
    const res = await ElMessageBox.prompt(
      `确认作废报销单「${row.bill_no}」？作废后不可再参与判读与制证。`,
      '作废报销单', {
        type: 'warning',
        inputLabel: '作废原因',
        inputPlaceholder: '请填写作废原因（必填）',
        inputValidator: (v) => (v && v.trim().length >= 2) || '请填写不少于 2 个字的作废原因',
        confirmButtonText: '确认作废', cancelButtonText: '取消'
      }
    )
    reason = res.value.trim()
  } catch { return }
  await reimburseApi.void(row.id, { reason })
  ElMessage.success('已作废')
  fetchList()
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除报销单「${row.bill_no}」？删除后不可恢复，票据文件一并失效。`,
      '删除报销单', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }
    )
  } catch { return }
  await reimburseApi.remove(row.id)
  ElMessage.success('已删除')
  fetchList()
}

onMounted(async () => {
  await loadMeta()
  fetchList()
})
</script>

<style scoped>
.no-btn { font-weight: 600; }
.amount { font-variant-numeric: tabular-nums; font-weight: 600; }
.ov-tag { margin-left: 4px; }
</style>

