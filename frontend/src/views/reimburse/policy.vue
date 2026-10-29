<template>
  <div class="page policy-page">
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Setting /></el-icon>制度与参数管理</h2>
        <div class="ph-desc">
          维护《差旅与业务招待费报销管理制度》文件版本、AI 检查规则与阈值参数，仅管理员可操作
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" :loading="loading" @click="loadAll">刷新</el-button>
      </div>
    </div>

    <!-- 顶部醒目提示 -->
    <el-alert type="warning" :closable="false" show-icon class="top-alert"
              title="阈值参数用于程序交叉校验。制度修订时，须同步修改制度文件、检查规则和阈值参数。"
              description="三者不一致会导致「程序校验不一致」被大量触发，合规判读结论不可信。修改规则或参数后请重新执行判读验证。" />

    <el-card shadow="never" class="card-fill">
      <el-tabs v-model="activeTab" class="policy-tabs" @tab-change="onTabChange">
        <!-- ================= (1) 制度文件 ================= -->
        <el-tab-pane label="制度文件" name="policy">
          <div class="pane-body">
            <!-- 当前生效制度 -->
            <div class="active-policy">
              <div class="ap-label">当前生效制度</div>
              <template v-if="activePolicy">
                <div class="ap-main">
                  <div class="ap-name">{{ activePolicy.policy_name || '—' }}</div>
                  <div class="ap-meta">
                    <el-tag size="small" type="success">生效中</el-tag>
                    <span>文号：{{ orDash(activePolicy.policy_no) }}</span>
                    <span>生效日期：{{ orDash(activePolicy.effective_date) }}</span>
                    <span>上传人：{{ orDash(activePolicy.uploaded_by) }}</span>
                    <span>上传时间：{{ fmtTime(activePolicy.uploaded_at) }}</span>
                  </div>
                </div>
                <el-button link type="primary" @click="previewPolicy(activePolicy)">预览正文</el-button>
              </template>
              <div v-else class="ap-empty">尚未设置生效制度，请先上传并设为生效</div>
            </div>

            <!-- 上传区 -->
            <div class="upload-row">
              <el-upload ref="policyUploadRef" drag :auto-upload="false" :show-file-list="false" :limit="1"
                         accept=".docx,.pdf" :on-change="onPolicyFileChange" :on-exceed="onPolicyExceed">
                <el-icon class="up-icon"><UploadFilled /></el-icon>
                <div class="up-text">上传制度文件，或<em>点击选择</em></div>
                <div class="up-sub">支持 DOCX / PDF，单个文件不超过 20MB</div>
              </el-upload>
              <div class="upload-form">
                <el-form :model="uploadForm" label-width="88px" size="default">
                  <el-form-item label="制度文号">
                    <el-input v-model="uploadForm.policy_no" placeholder="如 ZD-CW-2026-001" maxlength="64" />
                  </el-form-item>
                  <el-form-item label="制度名称">
                    <el-input v-model="uploadForm.policy_name" placeholder="如 差旅与业务招待费报销管理制度（2026 修订）" maxlength="128" />
                  </el-form-item>
                  <el-form-item label="生效日期">
                    <el-date-picker v-model="uploadForm.effective_date" type="date" value-format="YYYY-MM-DD"
                                    placeholder="选择生效日期" style="width: 100%" />
                  </el-form-item>
                  <el-form-item label="设为生效">
                    <el-switch v-model="uploadForm.set_active" active-text="上传后立即启用" />
                  </el-form-item>
                  <el-form-item>
                    <div class="up-file-line">
                      <span v-if="policyFile" class="upf-name" :title="policyFile.name">{{ policyFile.name }}</span>
                      <span v-else class="upf-empty">未选择文件</span>
                      <el-button type="primary" :loading="uploading" :disabled="!policyFile"
                                 v-permission="'reimburse:policy:manage'" @click="onUploadPolicy">上传制度</el-button>
                    </div>
                  </el-form-item>
                </el-form>
              </div>
            </div>

            <!-- 历史版本 -->
            <div class="sec-title">历史版本（{{ policyList.length }} 个）</div>
            <el-table :data="policyList" border size="small" empty-text="暂无制度文件">
              <el-table-column prop="policy_name" label="制度名称" min-width="200" show-overflow-tooltip />
              <el-table-column prop="policy_no" label="文号" width="150" show-overflow-tooltip />
              <el-table-column prop="effective_date" label="生效日期" width="112" align="center" />
              <el-table-column label="状态" width="92" align="center">
                <template #default="{ row }">
                  <el-tag v-if="row.is_active" type="success" size="small">生效中</el-tag>
                  <span v-else class="muted">历史版本</span>
                </template>
              </el-table-column>
              <el-table-column prop="uploaded_by" label="上传人" width="100" />
              <el-table-column label="上传时间" width="150">
                <template #default="{ row }">{{ fmtTime(row.uploaded_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="180" fixed="right">
                <template #default="{ row }">
                  <el-button link type="primary" @click="previewPolicy(row)">预览正文</el-button>
                  <el-button v-if="!row.is_active" link type="success"
                             v-permission="'reimburse:policy:manage'" @click="onActivate(row)">设为生效</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <!-- ================= (2) 解析测试 ================= -->
        <el-tab-pane label="解析测试" name="parse">
          <div class="pane-body">
            <div class="parse-head">
              <div>
                <div class="parse-title">制度解析测试</div>
                <div class="parse-sub">
                  调用大模型解析当前生效制度，检查章节与要点是否能被正确提取。
                  判读时 AI 会直接引用该正文，解析结果异常说明制度文件排版或正文提取有问题。
                </div>
              </div>
              <el-button type="primary" :icon="MagicStick" :loading="parsing"
                         :disabled="!activePolicy" v-permission="'reimburse:policy:manage'"
                         @click="onParseTest">
                {{ parsing ? '解析中，请稍候……' : '开始解析测试' }}
              </el-button>
            </div>
            <el-alert v-if="!activePolicy" type="info" :closable="false" show-icon
                      title="请先在「制度文件」页签上传并启用一份制度，再进行解析测试" />
            <div v-if="parsing" class="parsing-box">
              <el-progress :percentage="100" :indeterminate="true" :duration="3" :show-text="false" :stroke-width="5" />
              <span>大模型正在解析制度正文，约 20～60 秒……</span>
            </div>
            <div v-if="parseResult" class="parse-result">
              <div class="pr-head">
                <span class="pr-title">解析结果（章节要点）</span>
                <el-button link type="primary" @click="copyText(parseResult)">复制</el-button>
              </div>
              <pre class="pr-content">{{ parseResult }}</pre>
            </div>
            <el-empty v-else-if="!parsing && activePolicy" description="点击右上角「开始解析测试」查看解析结果" :image-size="90" />

            <!-- 正文预览 -->
            <template v-if="activePolicy?.content_text">
              <div class="sec-title">制度正文（{{ activePolicy.content_text.length }} 字）</div>
              <pre class="pr-content raw">{{ activePolicy.content_text }}</pre>
            </template>
          </div>
        </el-tab-pane>

        <!-- ================= (3) 检查规则 ================= -->
        <el-tab-pane label="检查规则" name="rules">
          <div class="pane-body">
            <div class="rules-head">
              <div class="rules-hint">
                共 <b>{{ rules.length }}</b> 条检查规则（R01～R14）。修改规则会写入审计日志；
                「检查方式」为 AI+程序 的规则，AI 结论会与程序校验结果交叉比对。
              </div>
            </div>
            <el-table :data="rules" border size="small" v-loading="loadingRules" empty-text="暂无检查规则">
              <el-table-column prop="rule_code" label="编号" width="72" align="center">
                <template #default="{ row }"><span class="rule-code">{{ row.rule_code }}</span></template>
              </el-table-column>
              <el-table-column label="检查项" width="160">
                <template #default="{ row }">
                  <el-input v-if="row._editing" v-model="row.check_item" size="small" maxlength="64" />
                  <span v-else class="rule-item">{{ row.check_item }}</span>
                </template>
              </el-table-column>
              <el-table-column label="判断规则" min-width="260">
                <template #default="{ row }">
                  <el-input v-if="row._editing" v-model="row.judge_rule" type="textarea" :rows="3" size="small" />
                  <span v-else class="rule-judge">{{ row.judge_rule || '—' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="制度条款" width="112">
                <template #default="{ row }">
                  <el-input v-if="row._editing" v-model="row.clause_no" size="small" maxlength="32" />
                  <span v-else>{{ row.clause_no || '—' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="风险等级" width="104" align="center">
                <template #default="{ row }">
                  <el-select v-if="row._editing" v-model="row.risk_level" size="small" style="width: 78px">
                    <el-option label="高" value="高" />
                    <el-option label="中" value="中" />
                    <el-option label="低" value="低" />
                  </el-select>
                  <el-tag v-else size="small" :type="riskType(row.risk_level)">{{ row.risk_level || '—' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="检查方式" width="110" align="center">
                <template #default="{ row }">
                  <el-select v-if="row._editing" v-model="row.check_mode" size="small" style="width: 96px">
                    <el-option label="AI+程序" value="AI+程序" />
                    <el-option label="AI" value="AI" />
                  </el-select>
                  <span v-else>{{ row.check_mode || '—' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="启用" width="78" align="center">
                <template #default="{ row }">
                  <el-switch v-model="row.is_active" size="small" :disabled="row._editing" />
                </template>
              </el-table-column>
              <el-table-column label="操作" width="130" fixed="right">
                <template #default="{ row, $index }">
                  <template v-if="row._editing">
                    <el-button link type="primary" :loading="row._saving" @click="saveRule(row)">保存</el-button>
                    <el-button link @click="cancelRule(row)">取消</el-button>
                  </template>
                  <el-button v-else link type="primary" v-permission="'reimburse:policy:manage'"
                             @click="editRule(row, $index)">编辑</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <!-- ================= (4) 参数与基础数据 ================= -->
        <el-tab-pane label="参数与基础数据" name="params">
          <div class="pane-body">
            <!-- 系统参数 -->
            <div class="sec-title">系统参数</div>
            <div class="param-tip">以下阈值用于程序交叉校验与规则判定，须与制度条款保持一致。</div>
            <el-table :data="paramRows" border size="small" v-loading="loadingParams" empty-text="暂无系统参数">
              <el-table-column prop="key" label="参数键" width="230">
                <template #default="{ row }"><span class="param-key">{{ row.key }}</span></template>
              </el-table-column>
              <el-table-column prop="remark" label="说明" min-width="200" show-overflow-tooltip>
                <template #default="{ row }">{{ row.remark || '—' }}</template>
              </el-table-column>
              <el-table-column label="参数值" width="250">
                <template #default="{ row }">
                  <el-input v-model="row._value" size="small" :placeholder="row.value" />
                </template>
              </el-table-column>
              <el-table-column label="操作" width="90" align="center">
                <template #default="{ row }">
                  <el-button link type="primary" :disabled="row._value === row.value"
                             v-permission="'reimburse:policy:manage'" @click="saveParam(row)">保存</el-button>
                </template>
              </el-table-column>
            </el-table>

            <!-- 城市等级 -->
            <div class="sec-title row-title">
              <span>城市等级与住宿标准（{{ cityLevels.length }} 条）</span>
              <el-button size="small" type="primary" plain :icon="Plus"
                         v-permission="'reimburse:policy:manage'" @click="addCityLevel">新增城市</el-button>
            </div>
            <el-table :data="cityLevels" border size="small" empty-text="暂无城市等级数据">
              <el-table-column label="城市名称" min-width="160">
                <template #default="{ row }">
                  <el-input v-if="row._editing" v-model="row.city_name" size="small" maxlength="64" />
                  <span v-else class="city-name">{{ row.city_name }}</span>
                </template>
              </el-table-column>
              <el-table-column label="城市等级" width="200">
                <template #default="{ row }">
                  <el-select v-if="row._editing" v-model="row.city_level" size="small" style="width: 170px">
                    <el-option v-for="l in CITY_LEVELS" :key="l" :label="l" :value="l" />
                  </el-select>
                  <el-tag v-else size="small" :type="row.city_level === '一线城市' ? 'warning' : 'info'">
                    {{ row.city_level }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="住宿上限(元/晚)" width="180" align="right" class-name="col-num">
                <template #default="{ row }">
                  <el-input-number v-if="row._editing" v-model="row.lodging_limit" :min="0" :precision="2"
                                   :controls="false" size="small" style="width: 140px" />
                  <b v-else>{{ fmtMoney(row.lodging_limit) }}</b>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="140" align="center">
                <template #default="{ row }">
                  <template v-if="row._editing">
                    <el-button link type="primary" :loading="row._saving" @click="saveCityLevel(row)">保存</el-button>
                    <el-button link @click="cancelRow(row, 'city')">取消</el-button>
                  </template>
                  <template v-else>
                    <el-button link type="primary" v-permission="'reimburse:policy:manage'"
                               @click="startEdit(row)">编辑</el-button>
                    <el-button link type="danger" v-permission="'reimburse:policy:manage'"
                               :disabled="row.city_name === '其他城市'" @click="removeCityLevel(row)">删除</el-button>
                  </template>
                </template>
              </el-table-column>
            </el-table>

            <!-- 节假日 -->
            <div class="sec-title row-title">
              <span>节假日与调休（{{ holidays.length }} 条）</span>
              <el-button size="small" type="primary" plain :icon="Plus"
                         v-permission="'reimburse:policy:manage'" @click="addHoliday">新增日期</el-button>
            </div>
            <el-table :data="holidays" border size="small" max-height="420" empty-text="暂无节假日数据">
              <el-table-column label="日期" width="180">
                <template #default="{ row }">
                  <el-date-picker v-if="row._editing" v-model="row.holiday_date" type="date" value-format="YYYY-MM-DD"
                                  size="small" style="width: 150px" />
                  <span v-else class="date-cell">{{ row.holiday_date }}</span>
                </template>
              </el-table-column>
              <el-table-column label="名称" min-width="160">
                <template #default="{ row }">
                  <el-input v-if="row._editing" v-model="row.holiday_name" size="small" maxlength="64" />
                  <span v-else>{{ row.holiday_name || '—' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="类型" width="180">
                <template #default="{ row }">
                  <el-select v-if="row._editing" v-model="row.day_type" size="small" style="width: 150px">
                    <el-option v-for="t in DAY_TYPES" :key="t" :label="t" :value="t" />
                  </el-select>
                  <el-tag v-else size="small" :type="row.day_type === '调休上班日' ? 'warning' : 'danger'">
                    {{ row.day_type }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="140" align="center">
                <template #default="{ row }">
                  <template v-if="row._editing">
                    <el-button link type="primary" :loading="row._saving" @click="saveHoliday(row)">保存</el-button>
                    <el-button link @click="cancelRow(row, 'holiday')">取消</el-button>
                  </template>
                  <template v-else>
                    <el-button link type="primary" v-permission="'reimburse:policy:manage'"
                               @click="startEdit(row)">编辑</el-button>
                    <el-button link type="danger" v-permission="'reimburse:policy:manage'"
                               @click="removeHoliday(row)">删除</el-button>
                  </template>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 制度正文预览弹窗 -->
    <el-dialog v-model="previewDlg.visible" :title="`制度正文预览 · ${previewDlg.data?.policy_name || ''}`"
               width="860px" :close-on-click-modal="false">
      <div class="preview-meta">
        <span>文号：{{ orDash(previewDlg.data?.policy_no) }}</span>
        <span>生效日期：{{ orDash(previewDlg.data?.effective_date) }}</span>
        <span>文件：{{ orDash(previewDlg.data?.original_filename) }}</span>
      </div>
      <pre class="pr-content in-dialog">{{ previewDlg.data?.content_text || '（该制度未提取到正文）' }}</pre>
      <template #footer>
        <el-button @click="previewDlg.visible = false">关 闭</el-button>
        <el-button type="primary" @click="copyText(previewDlg.data?.content_text || '')">复制正文</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import {
  Setting, Refresh, UploadFilled, MagicStick, Plus
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { policyApi } from '@/api/policy'
import { fmtMoney, fmtTime, orDash } from './constants'

/** 城市等级候选（与后端 rmb_city_level.city_level 取值一致） */
const CITY_LEVELS = ['一线城市', '其他城市']
/** 日期类型候选（与后端 rmb_holiday.day_type 取值一致） */
const DAY_TYPES = ['法定节假日', '调休上班日']

const loading = ref(false)
const activeTab = ref('policy')

// ---- 制度文件 ----
const activePolicy = ref(null)
const policyList = ref([])
const policyUploadRef = ref()
const policyFile = ref(null)
const uploading = ref(false)
const uploadForm = reactive({ policy_no: '', policy_name: '', effective_date: '', set_active: true })
const previewDlg = reactive({ visible: false, data: null })

// ---- 解析测试 ----
const parsing = ref(false)
const parseResult = ref('')

// ---- 检查规则 ----
const rules = ref([])
const loadingRules = ref(false)
const ruleBackup = new WeakMap()

// ---- 参数与基础数据 ----
const paramRows = ref([])
const cityLevels = ref([])
const holidays = ref([])
const loadingParams = ref(false)

function riskType(level) {
  return { 高: 'danger', 中: 'warning', 低: 'info' }[level] || 'info'
}

// ==================== 加载 ====================
async function loadPolicy() {
  const res = await policyApi.list()
  activePolicy.value = res?.active || null
  policyList.value = res?.list || []
}

async function loadRules() {
  loadingRules.value = true
  try {
    const res = await policyApi.rules()
    rules.value = (Array.isArray(res) ? res : res?.list || []).map((r) => ({ ...r, _editing: false, _saving: false }))
  } finally {
    loadingRules.value = false
  }
}

async function loadParams() {
  loadingParams.value = true
  try {
    const res = await policyApi.params()
    const params = res?.params || {}
    // params 既可能是 {k: v} 也可能是 {k: {value, remark}}，统一成行
    const remarks = res?.param_remarks || {}
    paramRows.value = Object.keys(params).map((k) => {
      const raw = params[k]
      const isObj = raw && typeof raw === 'object'
      const value = isObj ? raw.value : raw
      return {
        key: k,
        value: value === null || value === undefined ? '' : String(value),
        remark: (isObj ? raw.remark : remarks[k]) || '',
        _value: value === null || value === undefined ? '' : String(value)
      }
    })
    cityLevels.value = (res?.city_levels || []).map((c) => ({ ...c, _editing: false, _saving: false }))
    holidays.value = (res?.holidays || []).map((h) => ({ ...h, _editing: false, _saving: false }))
  } finally {
    loadingParams.value = false
  }
}

async function loadAll() {
  loading.value = true
  try {
    await loadPolicy()
    // 首次进入只加载当前页签需要的数据，其余页签切换时再加载
    if (activeTab.value === 'rules' && !rules.value.length) await loadRules()
    if (activeTab.value === 'params' && !paramRows.value.length) await loadParams()
  } finally {
    loading.value = false
  }
}

function onTabChange(name) {
  if (name === 'rules' && !rules.value.length) loadRules()
  if (name === 'params' && !paramRows.value.length) loadParams()
}

// ==================== (1) 制度文件 ====================
function onPolicyFileChange(uploadFile) {
  const raw = uploadFile?.raw
  policyUploadRef.value?.clearFiles()
  if (!raw) return
  if (raw.size > 20 * 1024 * 1024) return ElMessage.warning('制度文件不能超过 20MB')
  const ok = /\.(docx|pdf)$/i.test(raw.name)
  if (!ok) return ElMessage.warning('仅支持 DOCX / PDF 格式的制度文件')
  policyFile.value = raw
  // 名称未填时用文件名（去掉扩展名）预填
  if (!uploadForm.policy_name) uploadForm.policy_name = raw.name.replace(/\.(docx|pdf)$/i, '')
}
function onPolicyExceed() {
  ElMessage.warning('一次只能上传一个制度文件，请先移除已选文件')
}

async function onUploadPolicy() {
  if (!policyFile.value) return ElMessage.warning('请先选择制度文件')
  if (!uploadForm.policy_name.trim()) return ElMessage.warning('请填写制度名称')
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', policyFile.value)
    fd.append('policy_no', uploadForm.policy_no || '')
    fd.append('policy_name', uploadForm.policy_name || '')
    fd.append('effective_date', uploadForm.effective_date || '')
    fd.append('set_active', uploadForm.set_active ? '1' : '0')
    await policyApi.upload(fd)
    ElMessage.success('制度上传成功')
    policyFile.value = null
    uploadForm.policy_no = ''
    uploadForm.policy_name = ''
    uploadForm.effective_date = ''
    await loadPolicy()
  } finally {
    uploading.value = false
  }
}

function previewPolicy(row) {
  previewDlg.data = row
  previewDlg.visible = true
}

async function onActivate(row) {
  try {
    await ElMessageBox.confirm(
      `确认将「${row.policy_name}」设为当前生效制度？原生效版本将自动失效，后续 AI 判读将引用新制度正文。`,
      '设为生效', { type: 'warning', confirmButtonText: '确认启用', cancelButtonText: '取消' }
    )
  } catch { return }
  await policyApi.activate(row.id)
  ElMessage.success('已设为当前生效制度')
  await loadPolicy()
}

// ==================== (2) 解析测试 ====================
async function onParseTest() {
  parsing.value = true
  parseResult.value = ''
  try {
    const res = await policyApi.parseTest()
    parseResult.value = typeof res === 'string' ? res : (res?.result || JSON.stringify(res, null, 2))
    ElMessage.success('制度解析完成')
  } finally {
    parsing.value = false
  }
}

async function copyText(text) {
  if (!text) return ElMessage.warning('没有可复制的内容')
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    // 非 HTTPS / 权限受限时降级
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    try {
      document.execCommand('copy')
      ElMessage.success('已复制到剪贴板')
    } catch {
      ElMessage.warning('复制失败，请手动选择文本')
    }
    document.body.removeChild(ta)
  }
}

// ==================== (3) 检查规则 ====================
function editRule(row, idx) {
  ruleBackup.set(row, { ...row })
  row._editing = true
}

async function saveRule(row) {
  if (!row.check_item?.trim()) return ElMessage.warning('检查项不能为空')
  row._saving = true
  try {
    await policyApi.ruleUpdate(row.id, {
      check_item: row.check_item,
      judge_rule: row.judge_rule,
      clause_no: row.clause_no,
      risk_level: row.risk_level,
      check_mode: row.check_mode,
      is_active: row.is_active
    })
    ElMessage.success(`规则 ${row.rule_code} 已保存`)
    row._editing = false
  } finally {
    row._saving = false
  }
}

function cancelRule(row) {
  const bak = ruleBackup.get(row)
  if (bak) Object.assign(row, bak, { _editing: false })
  else row._editing = false
}

/** 城市等级 / 节假日行编辑（新行与已有行共用） */
function startEdit(row) {
  row._backup = { ...row }
  row._editing = true
}
function cancelRow(row, type) {
  if (row._backup) {
    const backup = row._backup
    delete backup._backup
    Object.assign(row, backup, { _editing: false })
  } else if (type === 'city') {
    const i = cityLevels.value.indexOf(row)
    if (i >= 0) cityLevels.value.splice(i, 1)
  } else {
    const i = holidays.value.indexOf(row)
    if (i >= 0) holidays.value.splice(i, 1)
  }
}

// ==================== (4) 参数与基础数据 ====================
async function saveParam(row) {
  if (row._value === '') return ElMessage.warning('参数值不能为空')
  await policyApi.paramUpdate({ key: row.key, value: row._value })
  row.value = row._value
  ElMessage.success('参数已保存')
}

function addCityLevel() {
  if (cityLevels.value.some((c) => c._isNew)) return ElMessage.warning('请先保存正在新增的城市')
  cityLevels.value.unshift({
    city_name: '', city_level: '其他城市', lodging_limit: 400,
    _editing: true, _saving: false, _isNew: true, _backup: null
  })
}

async function saveCityLevel(row) {
  if (!row.city_name?.trim()) return ElMessage.warning('城市名称不能为空')
  row._saving = true
  try {
    if (row._isNew) {
      await policyApi.cityLevelCreate({
        city_name: row.city_name.trim(), city_level: row.city_level, lodging_limit: Number(row.lodging_limit) || 0
      })
      ElMessage.success('城市已新增')
    } else {
      await policyApi.cityLevelUpdate(row.city_name, {
        city_name: row.city_name.trim(), city_level: row.city_level, lodging_limit: Number(row.lodging_limit) || 0
      })
      ElMessage.success('城市已保存')
    }
    row._editing = false
    row._isNew = false
    await loadParams()
  } finally {
    row._saving = false
  }
}

async function removeCityLevel(row) {
  try {
    await ElMessageBox.confirm(`确认删除城市「${row.city_name}」？删除后该城市将按「其他城市」标准判读。`, '删除城市', { type: 'warning' })
  } catch { return }
  await policyApi.cityLevelRemove(row.city_name)
  ElMessage.success('已删除')
  await loadParams()
}

function addHoliday() {
  if (holidays.value.some((h) => h._isNew)) return ElMessage.warning('请先保存正在新增的日期')
  holidays.value.unshift({
    holiday_date: '', holiday_name: '', day_type: '法定节假日',
    _editing: true, _saving: false, _isNew: true, _backup: null
  })
}

async function saveHoliday(row) {
  if (!row.holiday_date) return ElMessage.warning('请选择日期')
  row._saving = true
  try {
    if (row._isNew) {
      await policyApi.holidayCreate({
        holiday_date: row.holiday_date, holiday_name: row.holiday_name || '', day_type: row.day_type
      })
      ElMessage.success('日期已新增')
    } else {
      await policyApi.holidayUpdate(row.holiday_date, {
        holiday_date: row.holiday_date, holiday_name: row.holiday_name || '', day_type: row.day_type
      })
      ElMessage.success('日期已保存')
    }
    row._editing = false
    row._isNew = false
    await loadParams()
  } finally {
    row._saving = false
  }
}

async function removeHoliday(row) {
  try {
    await ElMessageBox.confirm(`确认删除 ${row.holiday_date}「${row.holiday_name || ''}」？`, '删除日期', { type: 'warning' })
  } catch { return }
  await policyApi.holidayRemove(row.holiday_date)
  ElMessage.success('已删除')
  await loadParams()
}

onMounted(loadAll)
</script>

<style scoped>
.top-alert { flex: 0 0 auto; }
.card-fill { overflow: hidden; }
.card-fill :deep(.el-card__body) { padding: 0 16px 14px; overflow: hidden; display: flex; flex-direction: column; min-height: 0; }
.policy-tabs { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
.policy-tabs :deep(.el-tabs__header) { margin-bottom: 12px; flex: 0 0 auto; }
.policy-tabs :deep(.el-tabs__content) { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding-right: 4px; }
.pane-body { display: flex; flex-direction: column; gap: 12px; padding-bottom: 8px; }

/* 当前生效制度 */
.active-policy {
  display: flex; align-items: center; gap: 16px; padding: 12px 16px;
  background: linear-gradient(90deg, #ecfdf5, #f9fefb); border: 1px solid #b7ecd4;
  border-radius: 9px; flex-wrap: wrap;
}
.ap-label { font-size: 12px; font-weight: 700; color: #0f9d76; flex: 0 0 auto; }
.ap-main { flex: 1 1 auto; min-width: 0; }
.ap-name { font-size: 14px; font-weight: 700; color: var(--text-1); }
.ap-meta { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: 3px; font-size: 12px; color: var(--text-2); }
.ap-empty { font-size: 13px; color: #b88230; }

/* 上传区 */
.upload-row { display: grid; grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr); gap: 14px; }
.upload-row :deep(.el-upload), .upload-row :deep(.el-upload-dragger) { width: 100%; height: 100%; }
.upload-row :deep(.el-upload-dragger) {
  padding: 18px 14px; display: flex; flex-direction: column; align-items: center; justify-content: center;
}
.up-icon { font-size: 38px; color: var(--brand); }
.up-text { margin-top: 6px; font-size: 14px; color: var(--text-1); }
.up-text em { font-style: normal; font-weight: 600; color: var(--brand); }
.up-sub { margin-top: 4px; font-size: 12px; color: var(--text-3); }
.upload-form :deep(.el-form-item) { margin-bottom: 10px; }
.up-file-line { display: flex; align-items: center; gap: 12px; width: 100%; }
.upf-name { flex: 1; font-size: 12px; color: var(--text-1); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.upf-empty { flex: 1; font-size: 12px; color: var(--text-3); }

.sec-title {
  font-size: 13px; font-weight: 700; color: var(--text-1); margin-top: 4px;
  padding-left: 9px; border-left: 3px solid var(--brand);
}
.row-title { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 12px; }
.muted { color: var(--text-3); }

/* 解析测试 */
.parse-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.parse-title { font-size: 14px; font-weight: 700; color: var(--text-1); }
.parse-sub { font-size: 12px; line-height: 1.7; color: var(--text-2); margin-top: 4px; max-width: 760px; }
.parsing-box { display: flex; align-items: center; gap: 12px; font-size: 13px; color: var(--brand-dark); }
.parsing-box :deep(.el-progress) { flex: 1; }
.parse-result { display: flex; flex-direction: column; gap: 8px; }
.pr-head { display: flex; align-items: center; justify-content: space-between; }
.pr-title { font-size: 13px; font-weight: 700; color: var(--text-1); }
.pr-content {
  margin: 0; padding: 12px 14px; background: #f7f9fc; border: 1px solid var(--border); border-radius: 8px;
  font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; line-height: 1.7;
  color: #334155; max-height: 460px; overflow: auto; white-space: pre-wrap; word-break: break-word;
}
.pr-content.raw { max-height: 400px; }
.pr-content.in-dialog { max-height: 50vh; }
.preview-meta { display: flex; gap: 18px; flex-wrap: wrap; font-size: 12px; color: var(--text-2); margin-bottom: 10px; }

/* 规则 */
.rules-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.rules-hint { font-size: 12px; line-height: 1.7; color: var(--text-2); }
.rules-hint b { color: var(--brand-dark); }
.rule-code { font-family: ui-monospace, Menlo, Consolas, monospace; font-weight: 700; }
.rule-item { font-weight: 600; color: var(--text-1); }
.rule-judge { font-size: 12px; line-height: 1.6; color: var(--text-2); white-space: pre-wrap; }

/* 参数 */
.param-tip { font-size: 12px; color: var(--text-3); margin-top: -6px; }
.param-key { font-family: ui-monospace, Menlo, Consolas, monospace; font-weight: 600; color: var(--text-1); }
.city-name { font-weight: 600; }
.date-cell { font-family: ui-monospace, Menlo, Consolas, monospace; }

@media (max-width: 992px) {
  .upload-row { grid-template-columns: minmax(0, 1fr); }
}
</style>
