<template>
  <div class="page">
    <!-- 页头：标题 + 说明 + 主操作 -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Files /></el-icon>数据导入导出</h2>
        <div class="ph-desc">
          导出全量业务数据为 .xlsx 文件；导入按模板整份校验，全部通过后才会写入 ·
          <b>{{ EXPORT_GROUPS.length }}</b> 组导出、<b>{{ IMPORT_TYPES.length }}</b> 类导入
        </div>
      </div>
      <div class="ph-actions">
        <el-button type="success" plain :icon="Download" @click="onTemplate(currentType)">下载当前类型模板</el-button>
      </div>
    </div>

    <div class="grid-2">
      <!-- 左栏：数据导出（区块网格铺满卡片宽度）+ 导入模板下载 -->
      <el-card shadow="never" class="block-card">
        <template #header>
          <div class="card-header">
            <span class="card-title">数据导出</span>
            <span class="card-hint">全量数据，不受列表页筛选条件影响</span>
          </div>
        </template>

        <div v-for="group in EXPORT_GROUPS" :key="group.title" class="group">
          <div class="group-title">{{ group.title }}</div>
          <div class="btn-grid">
            <el-button v-for="item in group.items" :key="item.url" type="primary" plain @click="onExport(item)">
              {{ item.label }}
            </el-button>
          </div>
        </div>

        <el-divider class="divider" />

        <div class="group">
          <div class="group-title">导入模板下载</div>
          <div class="btn-grid">
            <el-button v-for="t in IMPORT_TYPES" :key="t.template" type="success" plain @click="onTemplate(t)">
              下载{{ t.label }}模板
            </el-button>
          </div>
        </div>
      </el-card>

      <!-- 右栏：数据导入（类型与文件同一行，操作按钮右对齐） -->
      <el-card shadow="never" class="block-card">
        <template #header>
          <div class="card-header">
            <span class="card-title">数据导入</span>
            <span class="card-hint">整份文件全部校验通过才会写入，任一行有误则不导入并提示行号</span>
          </div>
        </template>

        <div class="toolbar">
          <el-form :inline="true" class="tb-left">
            <el-form-item label="导入类型">
              <el-select v-model="importType" style="width: 170px" @change="resetUpload">
                <el-option v-for="t in IMPORT_TYPES" :key="t.value" :label="t.label" :value="t.value" />
              </el-select>
            </el-form-item>
            <el-form-item label="选择文件">
              <el-upload ref="uploadRef" :auto-upload="false" :limit="1" :show-file-list="false"
                         accept=".xlsx,.xls" :on-change="onFileChange" :on-exceed="onExceed">
                <el-button :icon="UploadFilled">选择文件</el-button>
              </el-upload>
              <span class="file-name" :class="{ empty: !file }">{{ file ? file.name : '未选择文件' }}</span>
            </el-form-item>
          </el-form>
          <div class="tb-right">
            <el-button type="primary" :loading="importing" :disabled="!file" @click="onImport">开始导入</el-button>
            <el-button :disabled="importing" @click="resetUpload">清空</el-button>
          </div>
        </div>

        <el-alert type="info" :closable="false" show-icon class="gap" :title="currentType.tip" />

        <el-alert v-if="importResult" type="success" show-icon class="gap" title="导入完成" :closable="true"
                  @close="importResult = null">
          <template #default>
            成功写入 <b>{{ importResult.imported ?? 0 }}</b> 条
            <span v-if="importResult.skipped">，跳过 {{ importResult.skipped }} 条（已存在或留空）</span>
          </template>
        </el-alert>

        <el-alert v-if="importError" type="error" show-icon class="gap" title="导入失败，未写入任何数据"
                  :description="importError" :closable="true" @close="importError = ''" />
      </el-card>
    </div>

    <!-- 模板字段说明：满宽卡片，填满双栏下方的剩余高度（内容与后端导入模板表头一致） -->
    <el-card shadow="never" class="field-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">导入模板字段说明</span>
          <span class="card-hint">表头为 Sheet1 第 1 行，请勿修改；数据从第 2 行起填写，整份文件全部校验通过才会写入</span>
        </div>
      </template>
      <div class="field-grid">
        <div v-for="spec in FIELD_SPECS" :key="spec.value" class="field-block">
          <div class="field-title">
            <span>{{ spec.label }}</span>
            <el-tag size="small" type="success" effect="plain">必填 {{ spec.required.length }} 项</el-tag>
          </div>
          <div class="field-chips">
            <span v-for="col in spec.columns" :key="col" class="chip" :class="{ req: spec.required.includes(col) }">
              {{ col }}<i v-if="spec.required.includes(col)">*</i>
            </span>
          </div>
          <ul class="field-rules">
            <li v-for="(rule, i) in spec.rules" :key="i">{{ rule }}</li>
          </ul>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Download, Files, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { excelApi } from '@/api/system'
import { download } from '@/utils/download'

/** 导出分组：url 会被拼到 /api/v1 后面 */
const EXPORT_GROUPS = [
  {
    title: '基础数据',
    items: [
      { label: '物料档案', url: '/export/materials', filename: '物料档案.xlsx' },
      { label: '供应商档案', url: '/export/suppliers', filename: '供应商档案.xlsx' }
    ]
  },
  {
    title: '库存',
    items: [
      { label: '库存查询', url: '/export/inventory', filename: '库存查询.xlsx' },
      { label: '出入库流水', url: '/export/transactions', filename: '出入库流水.xlsx' }
    ]
  },
  {
    title: '采购单据',
    items: [
      { label: '请购单明细', url: '/export/purchase-requisitions', filename: '请购单明细.xlsx' },
      { label: '采购订单明细', url: '/export/purchase-orders', filename: '采购订单明细.xlsx' }
    ]
  }
]

/** 导入类型：与后端 /import/* 一一对应 */
const IMPORT_TYPES = [
  {
    value: 'materials',
    label: '物料档案',
    template: '/export/template/materials',
    filename: '物料导入模板.xlsx',
    importFn: excelApi.importMaterials,
    tip: '物料编码、物料名称为必填；编码已存在的行会自动跳过，不会覆盖原有数据。'
  },
  {
    value: 'suppliers',
    label: '供应商档案',
    template: '/export/template/suppliers',
    filename: '供应商导入模板.xlsx',
    importFn: excelApi.importSuppliers,
    tip: '供应商编码、供应商名称为必填；编码已存在的行会自动跳过。'
  },
  {
    value: 'inventory',
    label: '期初库存',
    template: '/export/template/inventory',
    filename: '期初库存导入模板.xlsx',
    importFn: excelApi.importInventory,
    tip: '需先有物料与仓库；按「物料编码 + 仓库编码 + 库位 + 缸号/批次」定位库存并累加入库，同时写入出入库流水。'
  }
]

const importType = ref('materials')
const currentType = computed(() => IMPORT_TYPES.find((t) => t.value === importType.value) || IMPORT_TYPES[0])

/** 导入模板字段说明（表头/必填/规则取自后端 app/api/v1/excel.py 的模板接口，仅供页面展示） */
const FIELD_SPECS = [
  {
    value: 'materials',
    label: '物料档案',
    columns: ['物料编码', '物料名称', '分类', '规格', '单位', '主色号', '安全库存', '最小批量', '状态', '备注'],
    required: ['物料编码', '物料名称'],
    rules: [
      '分类可填：面料 / 里料 / 辅料 / 五金 / 包材 / 成品，留空默认「辅料」',
      '单位可填：米 / 码 / 个 / 套 / kg，留空默认「个」',
      '安全库存、最小批量填数字（不能为负），留空按 0 处理；状态留空默认「启用」',
      '物料编码已存在的行会自动跳过，不覆盖原有数据'
    ]
  },
  {
    value: 'suppliers',
    label: '供应商档案',
    columns: ['供应商编码', '供应商名称', '联系人', '电话', '地址', '付款方式', '交货天数', '状态', '备注'],
    required: ['供应商编码', '供应商名称'],
    rules: [
      '付款方式示例：款到发货 / 月结 30 天 / 月结 60 天',
      '交货天数填整数天数，留空按 0 处理；状态留空默认「启用」',
      '供应商编码已存在的行会自动跳过，不覆盖原有数据'
    ]
  },
  {
    value: 'inventory',
    label: '期初库存',
    columns: ['物料编码', '仓库编码', '数量', '说明'],
    required: ['物料编码', '仓库编码', '数量'],
    rules: [
      '物料编码、仓库编码必须已在系统基础数据中存在，否则该行判为错误',
      '数量必须为正数（大于 0）；导入等同「其他入库」，会累加到现有库存并生成一条出入库流水',
      '如需冲减库存，请到「库存管理 - 库存查询 - 库存调整」做其他出库'
    ]
  }
]

const uploadRef = ref(null)
const file = ref(null)
const importing = ref(false)
const importResult = ref(null)
const importError = ref('')

function onExport(item) {
  // download 内部已统一做成功/失败提示与未捕获拒绝兜底
  download(item.url, item.filename)
}

function onTemplate(t) {
  download(t.template, t.filename)
}

function onFileChange(uploadFile) {
  file.value = uploadFile?.raw || null
  importResult.value = null
  importError.value = ''
}

function onExceed(files) {
  // limit=1：再次选择时替换掉上一个，而不是报错卡住
  uploadRef.value?.clearFiles()
  const raw = files?.[0]
  if (raw) {
    file.value = raw
    importResult.value = null
    importError.value = ''
    ElMessage.info(`已替换为：${raw.name}`)
  }
}

function resetUpload() {
  uploadRef.value?.clearFiles()
  file.value = null
  importResult.value = null
  importError.value = ''
}

async function onImport() {
  if (!file.value) {
    ElMessage.warning('请先选择要导入的文件')
    return
  }
  importing.value = true
  importResult.value = null
  importError.value = ''
  try {
    const formData = new FormData()
    formData.append('file', file.value)
    const res = await currentType.value.importFn(formData)
    importResult.value = res || {}
    uploadRef.value?.clearFiles()
    file.value = null
  } catch (e) {
    // 错误提示已由请求拦截器弹出，这里额外把详情留在页面上，方便对照行号修改
    importError.value = e?.message || '导入失败，请检查文件内容后重试'
  } finally {
    importing.value = false
  }
}
</script>

<style scoped>
/* 双栏：两卡等高；整块不参与压缩，剩余高度交给下方「模板字段说明」卡 */
.grid-2 {
  align-items: stretch;
}
.block-card {
  height: 100%;
  border: 1px solid var(--border);
}
.block-card :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
}
/* 满宽字段说明卡：吸收页面剩余高度，避免下半屏整片空白 */
.field-card {
  flex: 1 1 auto;
  min-height: 0;
  border: 1px solid var(--border);
}
.field-card :deep(.el-card__body) {
  min-height: 0;
}
.field-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 12px;
}
.field-block {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 12px;
  background: linear-gradient(180deg, #fbfdff, #ffffff);
}
.field-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-1);
  margin-bottom: 8px;
}
.field-chips {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}
.chip {
  font-size: 12px;
  line-height: 1;
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: #f6f8fb;
  color: var(--text-2);
}
.chip.req {
  border-color: #b7e3d6;
  background: #eafaf5;
  color: #0f766e;
  font-weight: 600;
}
.chip i {
  font-style: normal;
  margin-left: 1px;
  color: #f56c6c;
}
.field-rules {
  margin: 8px 0 0;
  padding-left: 16px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-3);
}
.card-header {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
}
.card-title {
  font-weight: 600;
  color: var(--text-1);
}
.card-hint {
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.6;
}
.group {
  margin-bottom: 12px;
}
.group:last-child {
  margin-bottom: 0;
}
.group-title {
  font-size: 13px;
  color: var(--text-2);
  margin-bottom: 8px;
  padding-left: 8px;
  border-left: 3px solid var(--brand);
  line-height: 1.2;
}
/* 按钮自适应多列网格：铺满卡片宽度，不再挤在左侧留出半张空白 */
.btn-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  align-content: start;
  gap: 8px;
}
.btn-grid .el-button {
  width: 100%;
  margin: 0;
}
.divider {
  margin: 12px 0;
}
.file-name {
  margin-left: 8px;
  font-size: 13px;
  color: var(--text-2);
}
.file-name.empty {
  color: var(--text-3);
}
.gap {
  margin-top: 12px;
}
</style>
