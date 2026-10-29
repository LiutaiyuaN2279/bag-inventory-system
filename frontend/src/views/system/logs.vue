<template>
  <div class="page">
    <!-- 页头：说明记录范围（全量接口调用，含查询与失败），并强调仅管理员可见 -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Tickets /></el-icon>操作日志</h2>
        <div class="ph-desc">
          记录全系统每一次接口调用（含查询、登录与失败请求），逐条留存操作人、路径、查询条件、
          结果与耗时 · 共 <b>{{ total }}</b> 条 · <span class="ph-tip">仅系统管理员可见</span>
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Download" :disabled="!list.length" @click="exportAll">导出当前页</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="loadAll">刷新</el-button>
      </div>
    </div>

    <!-- 统计条：总量 / 今日量 / 今日活跃账号 / 今日失败 + 近 7 日走势 -->
    <div class="stat-strip">
      <div class="stat-card">
        <div class="sc-label">日志总量</div>
        <div class="sc-value">{{ stats.total ?? '—' }}</div>
        <div class="sc-hint">全部时间累计</div>
      </div>
      <div class="stat-card">
        <div class="sc-label">今日操作</div>
        <div class="sc-value">{{ stats.today_total ?? '—' }}</div>
        <div class="sc-hint">今天产生的记录数</div>
      </div>
      <div class="stat-card">
        <div class="sc-label">今日活跃账号</div>
        <div class="sc-value">{{ stats.today_users ?? '—' }}</div>
        <div class="sc-hint">仅统计已登录账号</div>
      </div>
      <div class="stat-card" :class="{ warn: (stats.today_fail || 0) > 0 }">
        <div class="sc-label">今日失败请求</div>
        <div class="sc-value">{{ stats.today_fail ?? '—' }}</div>
        <div class="sc-hint">被拒 / 参数错 / 服务异常</div>
      </div>
      <div class="stat-card trend-card">
        <div class="sc-label">近 {{ stats.days || 7 }} 日走势</div>
        <div class="trend-bars">
          <div v-for="t in stats.trend || []" :key="t.date" class="trend-item" :title="`${t.date}：${t.count} 条`">
            <div class="bar" :style="{ height: barHeight(t.count) }"></div>
            <span class="bar-label">{{ t.date.slice(5) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 筛选卡 -->
    <el-card shadow="never" class="filter-card">
      <div class="toolbar">
        <el-form :inline="true" class="tb-left">
          <el-form-item label="用户">
            <el-select v-model="query.username" placeholder="全部账号" clearable filterable style="width:140px" @change="onSearch">
              <el-option v-for="u in userOptions" :key="u" :label="u" :value="u" />
            </el-select>
          </el-form-item>
          <el-form-item label="结果">
            <el-select v-model="query.status" placeholder="全部" clearable style="width:110px" @change="onSearch">
              <el-option label="成功" value="success" />
              <el-option label="失败" value="fail" />
            </el-select>
          </el-form-item>
          <el-form-item label="方法">
            <el-select v-model="query.method" placeholder="全部" clearable style="width:110px" @change="onSearch">
              <el-option v-for="m in ['GET', 'POST', 'PUT', 'DELETE']" :key="m" :label="m" :value="m" />
            </el-select>
          </el-form-item>
          <el-form-item label="关键字">
            <el-input v-model="query.keyword" placeholder="路径 / 动作 / 查询串 / 明细" clearable style="width:230px"
              @keyup.enter="onSearch" @clear="onSearch" />
          </el-form-item>
          <el-form-item label="日期">
            <el-date-picker v-model="query.range" type="daterange" value-format="YYYY-MM-DD"
              start-placeholder="开始日期" end-placeholder="结束日期" style="width:240px" @change="onSearch" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :icon="Search" @click="onSearch">查询</el-button>
            <el-button :icon="RefreshLeft" @click="onReset">重置</el-button>
          </el-form-item>
        </el-form>
      </div>
    </el-card>

    <!-- 列表卡：只读，仅提供导出选中 -->
    <el-card shadow="never" class="card-fill">
      <BatchBar :batch="batch" :actions="batchActions" @action="onBatchAction" />
      <div class="table-wrap">
        <el-table :ref="batch.bindTable" :data="list" :row-key="(row) => row.id" v-loading="loading" border stripe
          size="small" @sort-change="onSortChange" @selection-change="batch.onSelectionChange"
          @row-dblclick="openDetail">
          <el-table-column type="selection" width="46" align="center" reserve-selection />
          <el-table-column type="index" label="#" width="52" align="center" />
          <el-table-column prop="created_at" label="时间" width="160" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="username" label="操作人" width="120" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="method" label="方法" width="86" align="center" sortable="custom">
            <template #default="{ row }">
              <el-tag size="small" :type="methodTag(row.method)">{{ row.method }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="status_code" label="结果" width="104" align="center" sortable="custom">
            <template #default="{ row }">
              <el-tag size="small" :type="resultTag(row.status_code, row.login_result)" effect="plain">{{ resultText(row.status_code, row.login_result) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="action" label="业务动作" width="170" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="path" label="请求路径" min-width="230" sortable="custom" show-overflow-tooltip />
          <el-table-column prop="query" label="查询条件" min-width="170" show-overflow-tooltip>
            <template #default="{ row }"><span class="mono">{{ row.query || '—' }}</span></template>
          </el-table-column>
          <el-table-column prop="elapsed_ms" label="耗时" width="86" align="right" sortable="custom">
            <template #default="{ row }">{{ row.elapsed_ms }} ms</template>
          </el-table-column>
          <el-table-column prop="ip" label="IP" width="130" sortable="custom" show-overflow-tooltip />
          <el-table-column label="操作" width="76" align="center" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openDetail(row)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="pager">
        <span class="hint">共 <b>{{ total }}</b> 条 · 第 {{ query.page }} / {{ pageCount }} 页</span>
        <el-pagination background layout="sizes, prev, pager, next" :total="total"
          v-model:current-page="query.page" v-model:page-size="query.page_size"
          :page-sizes="[10, 20, 50, 100]" @current-change="fetchList" @size-change="fetchList" />
      </div>
    </el-card>

    <!-- 详情弹窗：单条日志全字段，写操作还带 detail 业务明细 -->
    <el-dialog v-model="detailVisible" title="日志详情" width="720px" class="log-dialog" destroy-on-close>
      <div v-if="detail" class="ld-body">
        <div class="ld-grid">
          <div class="ld-item"><span class="ld-k">操作人</span><span class="ld-v">{{ detail.username }}<template v-if="detail.real_name">（{{ detail.real_name }}）</template></span></div>
          <div class="ld-item"><span class="ld-k">时间</span><span class="ld-v">{{ detail.created_at }}</span></div>
          <div class="ld-item"><span class="ld-k">方法</span><span class="ld-v"><el-tag size="small" :type="methodTag(detail.method)">{{ detail.method }}</el-tag></span></div>
          <div class="ld-item"><span class="ld-k">结果</span><span class="ld-v"><el-tag size="small" :type="resultTag(detail.status_code, detail.login_result)" effect="plain">{{ resultText(detail.status_code, detail.login_result) }}（{{ detail.status_code }}）</el-tag></span></div>
          <div class="ld-item"><span class="ld-k">耗时</span><span class="ld-v">{{ detail.elapsed_ms }} ms</span></div>
          <div class="ld-item"><span class="ld-k">来源 IP</span><span class="ld-v">{{ detail.ip || '—' }}</span></div>
          <div class="ld-item wide"><span class="ld-k">请求路径</span><span class="ld-v mono">{{ detail.path }}</span></div>
          <div class="ld-item wide"><span class="ld-k">查询条件</span><span class="ld-v mono">{{ detail.query || '—' }}</span></div>
          <div class="ld-item wide"><span class="ld-k">User-Agent</span><span class="ld-v mono small">{{ detail.ua || '—' }}</span></div>
        </div>
        <div class="ld-detail">
          <div class="ld-k">业务明细（detail）</div>
          <pre v-if="detail.detail" class="ld-pre">{{ prettyDetail(detail.detail) }}</pre>
          <div v-else class="ld-empty">该请求没有额外业务明细（查询类接口通常为空）</div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Download, Refresh, RefreshLeft, Search, Tickets } from '@element-plus/icons-vue'
import { systemApi } from '@/api/system'
import { useSort } from '@/composables/useSort'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import BatchBar from '@/components/BatchBar.vue'

const allUsers = ref([])
const stats = ref({})
const list = ref([])
const total = ref(0)
const loading = ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))

// 筛选条件：range 是 [开始, 结束]，提交时拆成 date_from / date_to
const query = reactive({ page: 1, page_size: 20, keyword: '', username: '', method: '', status: '', range: null })

function params() {
  const p = { ...query }
  delete p.range
  if (query.range?.length === 2) {
    p.date_from = query.range[0]
    p.date_to = query.range[1]
  }
  return p
}

async function fetchList() {
  loading.value = true
  try {
    const res = await systemApi.logs(params())
    list.value = res.list || []
    total.value = res.total || 0
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  try {
    stats.value = (await systemApi.logStats({ days: 7 })) || {}
  } catch { /* 统计失败不影响列表 */ }
}

function loadAll() { fetchList(); fetchStats() }

const { onSortChange } = useSort(query, fetchList)

// ---- 批量操作：本页只读，仅「导出选中」 ----
const batch = useBatch({ fetchList })
const batchActions = [{ key: 'export', label: '导出选中', perm: 'system:log' }]
const exportColumns = [
  { prop: 'created_at', label: '时间' },
  { prop: 'username', label: '操作人' },
  { prop: 'method', label: '方法' },
  { prop: 'status_code', label: '状态码' },
  { prop: 'action', label: '业务动作' },
  { prop: 'path', label: '请求路径' },
  { prop: 'query', label: '查询条件' },
  { prop: 'elapsed_ms', label: '耗时(ms)' },
  { prop: 'ip', label: 'IP' }
]
function onBatchAction(key) {
  if (key === 'export') exportRows(batch.selected.value, exportColumns, '操作日志')
}
function exportAll() { exportRows(list.value, exportColumns, '操作日志') }

// ---- 详情 ----
const detailVisible = ref(false)
const detail = ref(null)
async function openDetail(row) {
  detail.value = { ...row }
  detailVisible.value = true
  try {
    detail.value = await systemApi.logDetail(row.id)
  } catch { /* 详情失败时保留列表行数据 */ }
}
function prettyDetail(text) {
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    return text
  }
}

// ---- 展示辅助：状态码 40100/40300 是业务码，历史记录里还可能是纯 HTTP 码 ----
// 登录请求优先显示 detail 里记下的结果（成功 / 密码错误 / 已锁定），
// 否则「未登录」看不出到底是密码错还是被限流锁定。
function resultText(code, loginResult) {
  if (loginResult) return loginResult
  if (!code) return '—'
  if (code === 200) return '成功'
  if (code === 40100 || code === 401) return '未登录'
  if (code === 40300 || code === 403) return '无权限'
  if (code === 50000 || code >= 500) return '失败'
  return '失败'
}
function resultTag(code, loginResult) {
  if (loginResult === '已锁定') return 'danger'
  if (loginResult === '密码错误') return 'warning'
  if (code === 200) return 'success'
  if (code === 40100 || code === 401) return 'warning'
  return 'danger'
}
function methodTag(m) {
  return { GET: 'info', POST: 'success', PUT: 'warning', DELETE: 'danger' }[m] || ''
}
function barHeight(count) {
  const max = Math.max(...(stats.value.trend || []).map((t) => t.count), 1)
  return `${Math.max(6, Math.round((count / max) * 100))}%`
}

function onSearch() { query.page = 1; batch.clearSelection(); loadAll() }
function onReset() {
  Object.assign(query, { page: 1, keyword: '', username: '', method: '', status: '', range: null })
  onSearch()
}

onMounted(async () => {
  loadAll()
  // 用户下拉：取当前页出现过的操作人，避免额外接口
  allUsers.value = [...new Set((stats.value.top_users || []).map((u) => u.username))]
  try {
    const res = await systemApi.logs({ page: 1, page_size: 100 })
    allUsers.value = [...new Set([...allUsers.value, ...(res.list || []).map((r) => r.username)])].filter(Boolean)
  } catch { /* 忽略 */ }
})
</script>

<style scoped>
.ph-tip { color: #909399; font-size: 12px; margin-left: 6px; }
.stat-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)) 1.4fr; gap: 12px; margin-bottom: 12px; }
.stat-card { background: #fff; border: 1px solid #ebeef5; border-radius: 8px; padding: 14px 16px; }
.stat-card.warn { border-color: #fbc4c4; background: #fef6f6; }
.sc-label { font-size: 12px; color: #909399; }
.sc-value { font-size: 24px; font-weight: 600; color: #303133; line-height: 1.4; }
.sc-hint { font-size: 12px; color: #c0c4cc; }
.trend-card { display: flex; flex-direction: column; }
.trend-bars { display: flex; align-items: flex-end; gap: 6px; height: 52px; margin-top: 6px; }
.trend-item { flex: 1; display: flex; flex-direction: column; justify-content: flex-end; align-items: center; height: 100%; }
.trend-item .bar { width: 100%; background: linear-gradient(180deg, #79bbff, #409eff); border-radius: 3px 3px 0 0; min-height: 4px; }
.bar-label { font-size: 10px; color: #c0c4cc; margin-top: 2px; }
.mono { font-family: Consolas, Monaco, monospace; font-size: 12px; }
.ld-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px 18px; }
.ld-item { display: flex; flex-direction: column; gap: 4px; }
.ld-item.wide { grid-column: span 3; }
.ld-k { font-size: 12px; color: #909399; }
.ld-v { font-size: 13px; color: #303133; word-break: break-all; }
.ld-v.small { font-size: 12px; color: #606266; }
.ld-detail { margin-top: 16px; border-top: 1px dashed #ebeef5; padding-top: 12px; }
.ld-pre { margin: 8px 0 0; padding: 12px; background: #f5f7fa; border-radius: 6px; font-size: 12px; line-height: 1.7; max-height: 320px; overflow: auto; white-space: pre-wrap; word-break: break-all; }
.ld-empty { margin-top: 8px; font-size: 12px; color: #c0c4cc; }
</style>
