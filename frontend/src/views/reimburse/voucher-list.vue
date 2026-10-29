<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Tickets /></el-icon>{{ isPending ? '待制证' : '凭证列表' }}</h2>
        <div class="ph-desc">
          {{ isPending
            ? '合规判读通过且待制证的报销单，点击「AI 制证」生成记账凭证 · 共 '
            : '已生成的记账凭证，未复核凭证需经复核后方可记账 · 共 ' }}<b>{{ total }}</b> 条
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
      </div>
    </div>

    <el-card shadow="never" class="card-fill">
      <div class="toolbar">
        <el-form :inline="true" :model="query" class="tb-left">
          <el-form-item v-if="!isPending" label="状态">
            <el-select v-model="query.status" placeholder="全部" clearable style="width: 128px">
              <el-option v-for="s in VOUCHER_STATUS" :key="s" :label="s" :value="s" />
            </el-select>
          </el-form-item>
          <el-form-item label="期间">
            <el-date-picker v-model="query.period" type="month" value-format="YYYY-MM"
                            placeholder="选择期间" clearable style="width: 150px" @change="onSearch" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :icon="Search" @click="onSearch">查询</el-button>
            <el-button :icon="RefreshLeft" @click="onReset">重置</el-button>
          </el-form-item>
        </el-form>
      </div>

      <!-- ============ 待制证：报销单清单 ============ -->
      <div v-if="isPending" class="table-wrap">
        <el-table :data="list" v-loading="loading" border stripe empty-text="暂无待制证的报销单">
          <el-table-column prop="bill_no" label="报销单号" width="166" show-overflow-tooltip />
          <el-table-column prop="employee_name" label="报销人" width="100" />
          <el-table-column prop="department_name" label="部门" width="120" show-overflow-tooltip>
            <template #default="{ row }">{{ orDash(row.department_name) }}</template>
          </el-table-column>
          <el-table-column prop="expense_type_name" label="费用类型" width="130" />
          <el-table-column prop="occur_date" label="发生日期" width="112" align="center" />
          <el-table-column prop="amount" label="金额(元)" width="126" align="right" class-name="col-num">
            <template #default="{ row }"><b class="amount">{{ fmtMoney(row.amount) }}</b></template>
          </el-table-column>
          <el-table-column label="判读结论" width="110" align="center">
            <template #default="{ row }">
              <el-tag :type="RESULT_TYPE[row.compliance_result] || 'info'" size="small">
                {{ row.compliance_result || '未判读' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="人工覆盖" width="94" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.override_flag" type="danger" size="small" effect="plain">已覆盖</el-tag>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="180" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="goBill(row)">查看报销单</el-button>
              <el-button link type="success" :icon="MagicStick" v-permission="'reimburse:voucher:make'"
                         @click="goMake(row)">AI 制证</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- ============ 凭证列表 ============ -->
      <div v-else class="table-wrap">
        <el-table :data="list" v-loading="loading" border stripe empty-text="暂无凭证">
          <el-table-column prop="voucher_code" label="凭证字号" width="150" fixed="left">
            <template #default="{ row }">
              <el-button link type="primary" class="code-btn" @click="goDetail(row)">{{ row.voucher_code }}</el-button>
            </template>
          </el-table-column>
          <el-table-column prop="voucher_date" label="日期" width="112" align="center" />
          <el-table-column prop="summary" label="摘要" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">{{ row.summary || row.first_summary || '—' }}</template>
          </el-table-column>
          <el-table-column label="金额(元)" width="132" align="right" class-name="col-num">
            <template #default="{ row }"><b class="amount">{{ fmtMoney(row.total_debit ?? row.amount) }}</b></template>
          </el-table-column>
          <el-table-column prop="employee_name" label="报销人" width="100">
            <template #default="{ row }">{{ row.employee_name || row.bill?.employee_name || '—' }}</template>
          </el-table-column>
          <el-table-column prop="maker" label="制单人" width="100">
            <template #default="{ row }">{{ row.maker || '—' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="VOUCHER_STATUS_TYPE[row.status] || 'info'" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="reviewer" label="复核人" width="100">
            <template #default="{ row }">{{ row.reviewer || '—' }}</template>
          </el-table-column>
          <el-table-column label="人工覆盖" width="94" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.override_flag || row.bill?.override_flag" type="danger" size="small" effect="plain">已覆盖</el-tag>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="goDetail(row)">查看</el-button>
              <el-button v-if="row.status === '已退回'" link type="warning" v-permission="'reimburse:voucher:make'"
                         @click="goEdit(row)">修改</el-button>
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
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Search, Refresh, RefreshLeft, Tickets, MagicStick } from '@element-plus/icons-vue'
import { voucherApi } from '@/api/voucher'
import {
  VOUCHER_STATUS, VOUCHER_STATUS_TYPE, RESULT_TYPE, fmtMoney, orDash
} from './constants'

const route = useRoute()
const router = useRouter()

// 同一个组件服务两个路由：待制证 / 凭证列表
const isPending = computed(() => route.name === 'RmbVoucherPending')

const query = reactive({ page: 1, page_size: 20, status: '', period: '' })
const list = ref([])
const total = ref(0)
const loading = ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))

async function fetchList() {
  loading.value = true
  try {
    const params = { ...query }
    if (!params.status) delete params.status
    if (!params.period) delete params.period
    const res = isPending.value ? await voucherApi.pending(params) : await voucherApi.list(params)
    list.value = res?.list || []
    total.value = res?.total || 0
  } finally {
    loading.value = false
  }
}

function onSearch() { query.page = 1; fetchList() }
function onReset() { query.status = ''; query.period = ''; onSearch() }

function goBill(row) { router.push(`/rmb/bill/${row.id}`) }
function goMake(row) { router.push(`/rmb/voucher/new/${row.id}`) }
function goDetail(row) { router.push(`/rmb/voucher/${row.id}`) }
function goEdit(row) { router.push(`/rmb/voucher/${row.id}/edit`) }

// 两个路由复用本组件：切换时重置分页并重新加载
watch(() => route.name, () => {
  query.page = 1
  query.status = ''
  list.value = []
  total.value = 0
  fetchList()
})

onMounted(fetchList)
</script>

<style scoped>
.code-btn { font-weight: 600; font-family: ui-monospace, Menlo, Consolas, monospace; }
.amount { font-variant-numeric: tabular-nums; }
.muted { color: var(--text-3); }
</style>
