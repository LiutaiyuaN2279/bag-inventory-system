<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Bell /></el-icon>库存预警看板</h2>
        <div class="ph-desc">
          安全库存分级预警 + 呆滞料预警（实时计算）· 共 <b>{{ data.total }}</b> 条
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchAlerts">刷新</el-button>
        <el-button :icon="Download" :disabled="!selected.length" @click="onExport">导出选中{{ selected.length ? `（${selected.length} 项）` : '' }}</el-button>
        <el-button type="primary" :icon="ShoppingCart" v-permission="'inventory:alert'"
          :disabled="!selected.length" :loading="restocking" @click="onRestock">
          一键补货生成请购单{{ selected.length ? `（已选 ${selected.length} 项）` : '' }}
        </el-button>
      </div>
    </div>

    <!-- 预警构成：三等分统计条，点卡片即切换到对应分段 -->
    <el-card shadow="never">
      <div class="stat-strip">
        <div class="stat-item" :class="{ 'is-on': segment === 'all' }" @click="switchSegment('all')">
          <div class="si-icon si-all"><el-icon><Bell /></el-icon></div>
          <div>
            <div class="si-num">{{ data.total }}</div>
            <div class="si-label">预警总数</div>
          </div>
        </div>
        <div class="stat-item" :class="{ 'is-on': segment === '安全库存预警' }" @click="switchSegment('安全库存预警')">
          <div class="si-icon si-safe"><el-icon><Warning /></el-icon></div>
          <div>
            <div class="si-num">{{ safetyCount }}</div>
            <div class="si-label">安全库存预警</div>
          </div>
        </div>
        <div class="stat-item" :class="{ 'is-on': segment === '呆滞料预警' }" @click="switchSegment('呆滞料预警')">
          <div class="si-icon si-dead"><el-icon><Clock /></el-icon></div>
          <div>
            <div class="si-num">{{ deadCount }}</div>
            <div class="si-label">呆滞料预警</div>
          </div>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="card-fill">
      <!-- 补货结果反馈：跳过原因与重复采购提醒都展示出来，不把返回值悄悄丢掉 -->
      <el-alert v-if="restockResult" show-icon
        :type="restockResult.skipped.length ? 'warning' : 'success'"
        :title="`已生成请购单 ${restockResult.req_no}（共 ${restockResult.item_count} 条明细，草稿状态待审核）`"
        @close="restockResult = null">
        <div v-if="restockResult.notices.length" class="restock-block">
          <div class="restock-title">重复采购提醒</div>
          <ul><li v-for="(n, i) in restockResult.notices" :key="'notice-' + i">{{ n }}</li></ul>
        </div>
        <div v-if="restockResult.skipped.length" class="restock-block">
          <div class="restock-title">已跳过 {{ restockResult.skipped.length }} 项</div>
          <ul>
            <li v-for="(s, i) in restockResult.skipped" :key="'skip-' + i">
              {{ s.material_name || `物料 ${s.material_id}` }}：{{ s.reason || '未生成明细' }}
            </li>
          </ul>
        </div>
      </el-alert>

      <div class="toolbar">
        <div class="tb-left">
          <el-radio-group v-model="segment" @change="onSegmentChange">
            <el-radio-button value="all">全部 {{ data.total }}</el-radio-button>
            <el-radio-button value="安全库存预警">安全库存预警 {{ safetyCount }}</el-radio-button>
            <el-radio-button value="呆滞料预警">呆滞料预警 {{ deadCount }}</el-radio-button>
          </el-radio-group>
        </div>
        <div class="tb-right">
          <el-form :inline="true">
            <el-form-item label="自定义呆滞阈值(天)">
              <el-input-number v-model="deadDays" :min="1" :controls="false"
                placeholder="留空=按物料自动判定" style="width:170px" @change="fetchAlerts" />
            </el-form-item>
          </el-form>
        </div>
      </div>

      <div class="table-wrap">
        <el-table ref="tableRef" :data="pagedRows" :row-key="rowKey" v-loading="loading" border stripe
          @selection-change="onSelectionChange">
          <el-table-column type="selection" width="50" align="center" reserve-selection />
          <!-- 类型列恒显示：文案取自 row.alert_type（安全库存预警/呆滞料预警）映射成的中文短名 -->
          <el-table-column label="类型" width="110" align="center">
            <template #default="{ row }">
              <span class="dot" :class="row.alert_type === '呆滞料预警' ? 'dt-dead' : 'dt-safe'">{{ typeLabel(row) }}</span>
            </template>
          </el-table-column>
          <!-- 级别列恒显示：安全库存预警行取 row.level_name，呆滞料行无 level_name 时显示「—」 -->
          <el-table-column label="级别" width="100" align="center">
            <template #default="{ row }">
              <span v-if="row.level_name" :class="row.level === 'critical' ? 'lv-critical' : 'lv-warn'">{{ row.level_name }}</span>
              <span v-else class="lv-na">—</span>
            </template>
          </el-table-column>
          <el-table-column prop="material_name" label="物料" min-width="170" sortable show-overflow-tooltip />
          <el-table-column prop="warehouse_name" label="仓库" width="120" sortable show-overflow-tooltip />
          <el-table-column prop="stock_qty" label="现存" width="100" align="right" class-name="col-num" sortable />
          <el-table-column v-if="showSafety && segment !== '呆滞料预警'" prop="safety_stock" label="安全库存" width="110"
            align="right" class-name="col-num" sortable>
            <template #default="{ row }">{{ row.safety_stock ?? '—' }}</template>
          </el-table-column>
          <el-table-column v-if="showDead && segment !== '安全库存预警'" prop="stock_days" label="库龄(天)" width="110"
            align="right" class-name="col-num" sortable>
            <template #default="{ row }">{{ row.stock_days ?? '—' }}</template>
          </el-table-column>
          <el-table-column v-if="showDead && segment !== '安全库存预警'" label="呆滞(天)" width="110" align="right"
            class-name="col-num" sortable>
            <template #default="{ row }">{{ row.dead_days ?? '—' }}</template>
          </el-table-column>
          <el-table-column prop="message" label="说明" min-width="300" sortable show-overflow-tooltip />
        </el-table>
      </div>

      <div class="pager">
        <span class="hint">共 <b>{{ rows.length }}</b> 条 · 当前分段：{{ segmentLabel }} · 第 {{ page }} / {{ pageCount }} 页</span>
        <el-pagination background layout="sizes, prev, pager, next" :total="rows.length"
          v-model:current-page="page" v-model:page-size="pageSize"
          :page-sizes="[10, 20, 50, 100]" />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Bell, Clock, Download, Refresh, ShoppingCart, Warning } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { inventoryApi } from '@/api/inventory'
import { exportRows } from '@/utils/exportRows'

const deadDays = ref(null)
const data = reactive({ list: [], total: 0 })
const loading = ref(false)
const tableRef = ref()          // 表格实例，用于生成后清空勾选
const selected = ref([])        // 当前勾选的预警行
const restocking = ref(false)   // 一键补货中，防重复点击
const restockResult = ref(null) // 最近一次补货结果：单号 / 跳过原因 / 重复采购提醒
const segment = ref('all')      // 分段：all / 安全库存预警 / 呆滞料预警（仅前端过滤 alert_type）
const page = ref(1)             // 接口一次返回全量预警，分页纯前端切片
const pageSize = ref(20)
const safetyCount = computed(() => data.list.filter(i => i.alert_type === '安全库存预警').length)
const deadCount = computed(() => data.list.filter(i => i.alert_type === '呆滞料预警').length)
// 接口数据里没有该类预警时，对应专属列整列都是「—」，直接不渲染（避免空白列占宽）
const showSafety = computed(() => safetyCount.value > 0)
const showDead = computed(() => deadCount.value > 0)

/** 当前分段展示的行：全部 / 仅安全库存 / 仅呆滞料 */
const rows = computed(() => (segment.value === 'all'
  ? data.list
  : data.list.filter(i => i.alert_type === segment.value)))
/** 当前页的行：接口不分页，这里对过滤后的结果做客户端切片 */
const pagedRows = computed(() => rows.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const pageCount = computed(() => Math.max(1, Math.ceil(rows.value.length / pageSize.value)))
const segmentLabel = computed(() => (segment.value === 'all' ? '全部预警' : segment.value))

/** 表格行 key：预警行是「物料 + 仓库」维度，用它配合 reserve-selection 让勾选跨页保留 */
function rowKey(row) {
  return `${row.alert_type}-${row.material_id}-${row.warehouse_name}`
}

/** 类型列展示文案：去掉「预警」后缀，避免与「级别」列语义重复 */
function typeLabel(row) {
  return row.alert_type === '安全库存预警' ? '安全库存' : (row.alert_type === '呆滞料预警' ? '呆滞料' : (row.alert_type || '—'))
}

/** 切换分段：换数据源前先清空勾选，避免把不可见行带进一键补货 */
function onSegmentChange() {
  page.value = 1
  tableRef.value?.clearSelection()
  selected.value = []
}

/** 统计卡点击 = 切到对应分段 */
function switchSegment(seg) {
  if (segment.value === seg) return
  segment.value = seg
  onSegmentChange()
}

/** 表格多选变化：维护勾选行 */
function onSelectionChange(rows) { selected.value = rows || [] }

/** 导出勾选的预警行（预警是实时计算结果，没有批量写接口，只提供导出） */
const exportColumns = [
  { prop: 'alert_type', label: '类型' },
  { prop: 'level_name', label: '级别', formatter: (r) => r.level_name || '—' },
  { prop: 'material_name', label: '物料' },
  { prop: 'warehouse_name', label: '仓库' },
  { prop: 'stock_qty', label: '现存' },
  { prop: 'safety_stock', label: '安全库存', formatter: (r) => (r.safety_stock ?? '—') },
  { prop: 'stock_days', label: '库龄(天)', formatter: (r) => (r.stock_days ?? '—') },
  { prop: 'dead_days', label: '呆滞(天)', formatter: (r) => (r.dead_days ?? '—') },
  { prop: 'message', label: '说明' }
]
function onExport() { exportRows(selected.value, exportColumns, '库存预警') }

/** 一键补货：对勾选物料按「安全库存 − 现存数量」生成一张草稿请购单 */
async function onRestock() {
  const rows = selected.value || []
  if (!rows.length) { ElMessage.warning('请先勾选需要补货的预警行'); return }
  // 确认框：点取消静默返回，不能产生未捕获的 Promise 拒绝
  try {
    await ElMessageBox.confirm(
      `将为勾选的 ${rows.length} 个物料，按「安全库存 − 现存数量」的缺口生成一张「草稿」状态的请购单`
      + '（需人工审核后才能转采购订单）。是否继续？',
      '一键补货',
      { type: 'warning', confirmButtonText: '确认生成', cancelButtonText: '取消' }
    )
  } catch (e) { return }
  restocking.value = true
  try {
    // 只传 material_id、不传 qty：预警行是「物料 + 仓库」维度，同一物料在多仓可能各有一行，
    // 前端按行累加缺口会重复计算；交给后端按物料全仓汇总后再算「安全库存 − 现存」更准确。
    const items = rows.map(r => ({ material_id: r.material_id }))
    const res = await inventoryApi.restock({ items, remark: '由库存预警页生成' })
    ElMessage.success(`已生成请购单 ${res?.req_no || ''}（共 ${res?.item_count || 0} 条明细）`)
    restockResult.value = {
      req_no: res?.req_no || '',
      item_count: res?.item_count || 0,
      skipped: res?.skipped || [],
      notices: res?.notices || []
    }
    tableRef.value?.clearSelection()
    selected.value = []
    await fetchAlerts()
  } catch (e) {
    // 响应拦截器已统一弹出后端错误提示，这里不再重复提示
  } finally { restocking.value = false }
}

async function fetchAlerts() {
  loading.value = true
  try {
    const params = {}
    if (deadDays.value) params.dead_days = deadDays.value
    const res = await inventoryApi.alerts(params)
    data.list = res.list || []; data.total = res.total || 0
    page.value = 1
  } finally { loading.value = false }
}
onMounted(fetchAlerts)
</script>
<style scoped>
/* KPI 三等分条：给足高度，避免数字+标签两行被卡片内边距/边框挤在一起 */
.stat-strip { min-height: 60px; }
.stat-item { min-height: 60px; cursor: pointer; transition: border-color .2s, box-shadow .2s; }
.stat-item:hover { border-color: var(--brand); }
.stat-item.is-on { border-color: var(--brand); box-shadow: 0 0 0 2px rgba(16, 185, 129, .14); }
.si-all { background: #ecfdf5; color: #10b981; }
.si-safe { background: #fef0f0; color: #f56c6c; }
.si-dead { background: #fdf6ec; color: #e6a23c; }
/* 类型列：沿用全局 .dot（圆点取 currentColor），文字用深色保证可读 */
.dt-safe { color: #065f46; }
.dt-dead { color: #b45309; }
/* 级别列：不用浅色 el-tag，改为深色文字，呆滞料行显示「—」 */
.lv-critical { color: #c0392b; font-weight: 600; }
.lv-warn { color: #b45309; font-weight: 600; }
.lv-na { color: #6b7280; }
.restock-block { margin-top: 6px; }
.restock-title { font-weight: 600; }
.restock-block ul { margin: 4px 0 0; padding-left: 18px; }
</style>
