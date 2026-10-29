<template>
  <div v-loading="loading" class="rw" element-loading-text="工作台加载中…">
    <!-- ========== 问候横幅 ========== -->
    <div class="greet">
      <div class="greet-main">
        <div class="greet-hello">你好，{{ data.real_name || '—' }} 👋</div>
        <div class="greet-sub">
          <span v-if="data.role_label" class="greet-role">{{ data.role_label }}</span>
          <span class="greet-scope">
            数据范围：{{ scopeLabel }}
          </span>
        </div>
      </div>
      <div class="greet-side">
        <el-button :icon="Refresh" size="small" :loading="loading" @click="load">刷新</el-button>
        <span class="greet-date">{{ data.today || '' }}</span>
      </div>
    </div>

    <!-- ========== KPI 卡片 ========== -->
    <div v-if="kpis.length" class="kpi-row">
      <div v-for="c in kpis" :key="c.label" class="kpi-card" :style="{ '--c': c.color }" @click="go(c.to)">
        <div class="kpi-icon">
          <el-icon :size="20"><component :is="c.icon || 'DataLine'" /></el-icon>
        </div>
        <div class="kpi-text">
          <div class="kpi-num">{{ c.value }}</div>
          <div class="kpi-label" :title="c.label">{{ c.label }}</div>
        </div>
      </div>
    </div>

    <div class="rw-body">
      <!-- ========== 左栏：待办 + 最近单据 ========== -->
      <div class="rw-left">
        <!-- 待办 -->
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="panel-head">
              <span class="panel-title">待办事项</span>
              <el-tag v-if="todos.length" size="small" type="warning" effect="plain">
                {{ todos.length }} 类
              </el-tag>
            </div>
          </template>
          <div v-if="todos.length" class="todo-list">
            <div v-for="t in todos" :key="t.title" class="todo-item" @click="go(t.to)">
              <span class="todo-dot" />
              <span class="todo-title">{{ t.title }}</span>
              <span class="todo-count">{{ t.count }}</span>
              <el-icon class="todo-arrow"><ArrowRight /></el-icon>
            </div>
          </div>
          <el-empty v-else description="暂无待办，一切正常" :image-size="70" />
        </el-card>

        <!-- 最近单据 -->
        <el-card shadow="never" class="panel panel-grow">
          <template #header>
            <div class="panel-head">
              <span class="panel-title">最近报销单</span>
              <el-button link type="primary" size="small" @click="go('/reimburse/list')">
                查看全部 <el-icon><ArrowRight /></el-icon>
              </el-button>
            </div>
          </template>
          <el-table v-if="recent.length" :data="recent" size="small" class="recent-table"
                    @row-click="(row) => go(`/rmb/bill/${row.id}`)">
            <el-table-column prop="bill_no" label="报销单号" width="160" show-overflow-tooltip />
            <el-table-column prop="employee_name" label="报销人" width="82" />
            <el-table-column prop="expense_type_name" label="费用类型" width="112" show-overflow-tooltip />
            <el-table-column prop="amount" label="金额" width="110" align="right">
              <template #default="{ row }">¥ {{ fmtMoney(row.amount) }}</template>
            </el-table-column>
            <el-table-column label="判读" width="90" align="center">
              <template #default="{ row }">
                <el-tag :type="RESULT_TYPE[row.compliance_result] || 'info'" size="small" effect="plain">
                  {{ row.compliance_result || '未判读' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="BILL_STATUS_TYPE[row.status] || 'info'" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="暂无报销单" :image-size="70" />
        </el-card>
      </div>

      <!-- ========== 右栏：本月费用构成 + 快速入口 ========== -->
      <div class="rw-right">
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="panel-head">
              <span class="panel-title">本月费用构成</span>
              <span class="panel-amount">¥ {{ fmtMoney(data.summary?.month_amount) }}</span>
            </div>
          </template>
          <div v-if="byType.length" class="type-list">
            <div v-for="t in byType" :key="t.name" class="type-item">
              <div class="type-head">
                <span class="type-name">{{ t.name }}</span>
                <span class="type-amount">¥ {{ fmtMoney(t.amount) }}</span>
              </div>
              <div class="type-bar">
                <div class="type-bar-inner"
                     :style="{ width: barWidth(t.amount) + '%', background: barColor(t.name) }" />
              </div>
              <div class="type-sub">{{ t.count }} 张</div>
            </div>
          </div>
          <el-empty v-else description="本月暂无费用发生" :image-size="70" />
        </el-card>

        <el-card shadow="never" class="panel">
          <template #header>
            <div class="panel-head"><span class="panel-title">快速入口</span></div>
          </template>
          <div class="quick-wrap">
            <div v-for="q in quickEntries" :key="q.path" class="quick-item"
                 :style="{ '--c': q.color }" @click="go(q.path)">
              <el-icon :size="16"><component :is="q.icon" /></el-icon>
              <span>{{ q.name }}</span>
            </div>
          </div>
        </el-card>

        <el-card shadow="never" class="panel stat-panel">
          <div class="stat-row">
            <div class="stat-item">
              <div class="stat-num">{{ data.summary?.total_count ?? 0 }}</div>
              <div class="stat-label">可见单据总数</div>
            </div>
            <div class="stat-item">
              <div class="stat-num">¥ {{ fmtMoney(data.summary?.total_amount) }}</div>
              <div class="stat-label">累计金额</div>
            </div>
          </div>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Refresh, ArrowRight, Stamp, Tickets, Finished, Document,
  Warning, CircleCheck, EditPen, Files, Checked
} from '@element-plus/icons-vue'
import { reimburseApi } from '@/api/reimburse'
import { BILL_STATUS_TYPE, RESULT_TYPE, fmtMoney } from '@/views/reimburse/constants'

const router = useRouter()
const loading = ref(false)
const data = reactive({
  real_name: '', role_label: '', today: '', data_scope: 'self',
  kpis: [], todos: [], recent: [], by_type: [],
  summary: { total_count: 0, total_amount: 0, month_amount: 0 }
})

const kpis = computed(() => data.kpis || [])
const todos = computed(() => data.todos || [])
const recent = computed(() => data.recent || [])
const byType = computed(() => data.by_type || [])

const SCOPE_LABEL = { all: '全公司', dept: '本部门', self: '仅本人' }
const scopeLabel = computed(() => SCOPE_LABEL[data.data_scope] || '—')

/** 快捷入口：全部指向报销模块，与角色权限无关的入口由后端菜单控制 */
const quickEntries = computed(() => {
  const list = [
    { name: '填写报销单', path: '/reimburse/new', icon: 'EditPen', color: '#409eff' },
    { name: '报销单列表', path: '/reimburse/list', icon: 'Document', color: '#67c23a' }
  ]
  const has = (label) => kpis.value.some((k) => k.label === label)
  if (has('待我审批') || has('待制证')) {
    list.push({ name: '待制证', path: '/reimburse/voucher/pending', icon: 'Tickets', color: '#e6a23c' })
  }
  if (has('待复核凭证')) {
    list.push({ name: '凭证复核', path: '/reimburse/voucher/review', icon: 'Finished', color: '#f56c6c' })
  }
  list.push({ name: '凭证列表', path: '/reimburse/voucher/list', icon: 'Files', color: '#909399' })
  return list
})

const TYPE_COLORS = {
  差旅住宿费: '#409eff', 差旅交通费: '#79bbff', 业务招待费: '#e6a23c',
  市内交通费: '#95d475', 通讯费: '#b1b3b8', 办公费: '#f89898', 其他费用: '#c8c9cc'
}
const barColor = (name) => TYPE_COLORS[name] || '#909399'
const barWidth = (amount) => {
  const max = Math.max(...byType.value.map((t) => t.amount || 0), 1)
  return Math.max(4, Math.round(((amount || 0) / max) * 100))
}

function go(path) {
  if (!path) return
  router.push(path)
}

async function load() {
  loading.value = true
  try {
    const res = await reimburseApi.workbench()
    Object.assign(data, {
      real_name: res.real_name || '',
      role_label: res.role_label || '',
      today: res.today || '',
      data_scope: res.data_scope || 'self',
      kpis: res.kpis || [],
      todos: res.todos || [],
      recent: res.recent || [],
      by_type: res.by_type || [],
      summary: res.summary || { total_count: 0, total_amount: 0, month_amount: 0 }
    })
  } catch (e) {
    ElMessage.error('工作台数据加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.rw {
  height: 100%; min-height: 0; display: flex; flex-direction: column; gap: 12px;
  padding: 0;
}

/* ---------- 问候横幅 ---------- */
.greet {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 16px 20px; border-radius: 12px; color: #fff;
  background: linear-gradient(120deg, #0f9d76 0%, #10b981 55%, #34d9a0 100%);
  box-shadow: 0 6px 18px rgba(16, 185, 129, .18);
}
.greet-hello { font-size: 19px; font-weight: 700; letter-spacing: .3px; }
.greet-sub { display: flex; align-items: center; gap: 10px; margin-top: 6px; font-size: 12.5px; opacity: .95; }
.greet-role {
  padding: 1px 9px; border-radius: 10px; background: rgba(255, 255, 255, .22);
  border: 1px solid rgba(255, 255, 255, .3); font-weight: 600;
}
.greet-scope { opacity: .9; }
.greet-side { display: flex; align-items: center; gap: 12px; }
.greet-date { font-size: 13px; opacity: .9; font-variant-numeric: tabular-nums; }

/* ---------- KPI 卡片 ---------- */
.kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(148px, 1fr)); gap: 12px; }
.kpi-card {
  display: flex; align-items: center; gap: 12px; padding: 14px 16px;
  background: #fff; border: 1px solid var(--border, #e8ebf1); border-radius: 10px;
  cursor: pointer; transition: all .18s ease;
}
.kpi-card:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(0, 0, 0, .07); border-color: var(--c); }
.kpi-icon {
  width: 40px; height: 40px; border-radius: 10px; flex: none;
  display: flex; align-items: center; justify-content: center;
  background: color-mix(in srgb, var(--c) 12%, #fff); color: var(--c);
}
.kpi-num { font-size: 22px; font-weight: 700; color: #1f2937; line-height: 1.1; font-variant-numeric: tabular-nums; }
.kpi-label { font-size: 12px; color: var(--text-3); margin-top: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* ---------- 主体两栏 ---------- */
.rw-body { flex: 1 1 auto; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(0, 1fr); gap: 12px; }
.rw-left, .rw-right { display: flex; flex-direction: column; gap: 12px; min-height: 0; }
.panel { border-radius: 10px; }
.panel-grow { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
.panel-grow :deep(.el-card__body) { flex: 1 1 auto; min-height: 0; overflow: auto; }
.panel-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.panel-title { font-size: 13.5px; font-weight: 700; color: var(--text-1); }
.panel-amount { font-size: 14px; font-weight: 700; color: #0f9d76; font-variant-numeric: tabular-nums; }

/* ---------- 待办 ---------- */
.todo-list { display: flex; flex-direction: column; gap: 2px; }
.todo-item {
  display: flex; align-items: center; gap: 10px; padding: 10px 8px; border-radius: 8px;
  cursor: pointer; transition: background .15s;
}
.todo-item:hover { background: #f6f9fc; }
.todo-dot { width: 6px; height: 6px; border-radius: 50%; background: #e6a23c; flex: none; }
.todo-title { flex: 1 1 auto; font-size: 13px; color: var(--text-1); }
.todo-count {
  font-size: 13px; font-weight: 700; color: #e6a23c;
  background: #fdf6ec; border-radius: 10px; padding: 1px 10px; font-variant-numeric: tabular-nums;
}
.todo-arrow { color: #c0c4cc; font-size: 13px; }

/* ---------- 最近单据 ---------- */
.recent-table { cursor: pointer; }
.recent-table :deep(.el-table__header th) { background: #fafbfd; }

/* ---------- 费用构成 ---------- */
.type-list { display: flex; flex-direction: column; gap: 12px; }
.type-head { display: flex; justify-content: space-between; align-items: baseline; font-size: 12.5px; }
.type-name { color: var(--text-1); font-weight: 600; }
.type-amount { color: #0f9d76; font-variant-numeric: tabular-nums; }
.type-bar { height: 6px; background: #f0f2f5; border-radius: 3px; margin: 5px 0 3px; overflow: hidden; }
.type-bar-inner { height: 100%; border-radius: 3px; transition: width .4s ease; }
.type-sub { font-size: 11.5px; color: var(--text-3); }

/* ---------- 快速入口 ---------- */
.quick-wrap { display: flex; flex-wrap: wrap; gap: 8px; }
.quick-item {
  display: flex; align-items: center; gap: 6px; padding: 7px 12px; border-radius: 18px;
  font-size: 12.5px; cursor: pointer; transition: all .16s ease;
  color: var(--c); background: color-mix(in srgb, var(--c) 8%, #fff);
  border: 1px solid color-mix(in srgb, var(--c) 22%, #fff);
}
.quick-item:hover { background: color-mix(in srgb, var(--c) 16%, #fff); transform: translateY(-1px); }

/* ---------- 汇总 ---------- */
.stat-row { display: flex; justify-content: space-around; text-align: center; }
.stat-num { font-size: 18px; font-weight: 700; color: #1f2937; font-variant-numeric: tabular-nums; }
.stat-label { font-size: 11.5px; color: var(--text-3); margin-top: 3px; }

@media (max-width: 1200px) {
  .rw-body { grid-template-columns: 1fr; }
}
</style>
