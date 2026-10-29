<template>
  <div class="page">
    <!-- 页头：标题 + 说明 + 主操作 -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><MagicStick /></el-icon>AI 单据识别</h2>
        <div class="ph-desc">
          AI 自动识别送货单 / 发票照片，提取「单号 / 供应商 / 物料 / 数量」，核对后一键生成采购到货单（待验收）
        </div>
      </div>
      <div class="ph-actions">
        <el-tooltip :content="engineTip" placement="bottom">
          <el-tag :type="info.is_remote ? 'success' : 'warning'" effect="plain" size="large" class="engine-tag">
            识别引擎：{{ info.provider }}{{ info.model ? ' · ' + info.model : '' }}
          </el-tag>
        </el-tooltip>
        <el-button :icon="Connection" :loading="testing" @click="onTest">测试连接</el-button>
        <!-- 模型配置只对管理员开放（v-permission），业务岗看不到这个入口 -->
        <el-button :icon="Setting" v-permission="'ai:ocr:config'" @click="openConfigs">模型配置</el-button>
        <el-button :icon="Refresh" @click="fetchRecords">刷新记录</el-button>
      </div>
    </div>

    <!-- 未接入真实模型时才提示；已接入的信息由右上角引擎标签承载，避免重复占位 -->
    <el-alert v-if="!info.is_remote" type="warning" :closable="false" show-icon
      title="当前为演示识别引擎（mock），无需密钥即可体验完整流程"
      description="识别结果为一组与基础数据吻合的示例数据。接入真实视觉模型请点右上角「模型配置」新建一份档案（通义千问-VL / 豆包视觉 / 智谱 / OpenAI / 自定义网关）并启用，无需修改 .env。" />
    <el-alert v-else-if="!info.key_configured" type="error" :closable="false" show-icon
      title="已切换到真实识别引擎，但尚未配置 API Key"
      description="请点右上角「模型配置」，编辑当前启用的档案并填写 API Key；保存后即时生效，可用「测试」先验证连通性。" />

    <div class="ai-stack">
      <!-- 识别工作台：流程引导 + 上传 + 识别 -->
      <el-card shadow="never" class="block-card">
        <template #header>
          <div class="card-header">
            <span class="card-title">识别工作台</span>
            <span class="card-hint">支持 jpg / png / bmp / webp，单张不超过 {{ info.max_mb || 8 }}MB，可一次多选批量识别；仅识别采购类单据</span>
          </div>
        </template>

        <!-- 流程引导：随当前进度点亮 -->
        <div class="steps">
          <div v-for="s in stepList" :key="s.n" class="step" :class="stepCls(s.n)">
            <i>{{ stepCls(s.n) === 'done' ? '✓' : s.n }}</i>
            <div class="step-txt">
              <b>{{ s.title }}</b>
              <span>{{ s.desc }}</span>
            </div>
          </div>
        </div>

        <div class="upload-row" :class="{ multi: isBatch }">
          <el-upload ref="uploadRef" drag multiple :auto-upload="false" :limit="MAX_BATCH_FILES"
                     :show-file-list="false" accept="image/*" :on-change="onFilesChange" :on-exceed="onExceed">
            <el-icon class="upload-icon"><UploadFilled /></el-icon>
            <div class="upload-text">将单据照片拖到此处，或<em>点击选择</em></div>
            <div class="upload-sub">
              可一次选择多张批量识别（最多 {{ MAX_BATCH_FILES }} 张）；请保证单据四角完整、画面清晰
            </div>
          </el-upload>
          <div class="upload-side">
            <!-- 单张：沿用原有「预览 + 文件名」版式 -->
            <template v-if="files.length <= 1">
              <div v-if="previewUrl" class="preview">
                <img :src="previewUrl" alt="单据预览" />
              </div>
              <div v-else class="preview empty">
                <el-icon><Picture /></el-icon>
                <span>选择或拖入图片后在此预览</span>
              </div>
              <div class="file-line">
                <span class="file-name" :class="{ empty: !files.length }">
                  {{ files.length ? files[0].name : '未选择文件' }}
                </span>
                <el-button v-if="files.length" link type="primary" @click="removeFile(0)">清除</el-button>
              </div>
            </template>

            <!-- 多张：用队列取代预览，逐张显示状态与失败原因 -->
            <template v-else>
              <div class="queue-head">
                <span>已选 <b>{{ files.length }}</b> 张 · 待识别 <b>{{ pendingList.length }}</b> 张</span>
                <span class="queue-ops">
                  <el-button v-if="failedCount" link type="warning" :disabled="recognizing" @click="retryFailed">
                    重试失败（{{ failedCount }}）
                  </el-button>
                  <el-button link type="primary" :disabled="recognizing" @click="clearFiles">清空</el-button>
                </span>
              </div>
              <div class="queue-list">
                <div v-for="(f, i) in files" :key="f.uid" class="queue-item" :class="f.status">
                  <span class="q-idx">{{ i + 1 }}</span>
                  <span class="q-name" :title="f.name">{{ f.name }}</span>
                  <span class="q-size">{{ Math.max(1, Math.round((f.size || 0) / 1024)) }}KB</span>
                  <el-tag size="small" effect="plain" :type="statusType(f.status)">{{ statusLabel(f.status) }}</el-tag>
                  <el-button v-if="!recognizing" link type="danger" class="q-del" @click="removeFile(i)">移除</el-button>
                  <div v-if="f.reason" class="q-reason" :title="f.reason">{{ f.reason }}</div>
                </div>
              </div>
            </template>

            <!-- 批量进度：串行逐张，实时显示第几张 -->
            <div v-if="recognizing && progress.total > 1" class="progress-line">
              <el-progress :percentage="progressPct" :stroke-width="6" :show-text="false" />
              <span class="progress-text">
                识别中 {{ Math.min(progress.done + 1, progress.total) }}/{{ progress.total }} · {{ progress.current }}
              </span>
            </div>

            <div class="go-row">
              <el-button class="go-btn" type="primary" size="large" :icon="MagicStick" :loading="recognizing"
                         :disabled="!canRecognize" v-permission="'ai:ocr:recognize'" @click="onRecognize">
                {{ recognizeBtnText }}
              </el-button>
              <el-button v-if="recognizing && progress.total > 1" size="large" @click="cancelBatch">停止</el-button>
            </div>
          </div>
        </div>

        <!-- 批量识别结果汇总：成功的已写入下方记录，失败原因逐张列在队列里 -->
        <el-alert v-if="batchResult" class="recog-error" show-icon
                  :type="batchResult.fail ? 'warning' : 'success'" @close="batchResult = null"
                  :title="batchResult.fail
                    ? `批量识别完成：成功 ${batchResult.ok} 张，失败 ${batchResult.fail} 张`
                    : `批量识别完成：${batchResult.ok} 张全部识别成功`"
                  :description="batchResult.fail
                    ? `失败原因见上方队列；成功 ${batchResult.ok} 张已写入下方「识别记录」，请逐条点击「查看」核对后导入。`
                    : '识别结果已写入下方「识别记录」，请逐条点击「查看」核对后导入。'" />

        <!-- 识别失败提示：常驻展示，便于按提示排查（密钥 / 模型 / 网络 / 图片） -->
        <el-alert v-if="recogError" class="recog-error" type="error" show-icon
                  title="识别失败" :description="recogError" @close="recogError = ''" />
      </el-card>

      <!-- 识别记录：卡片撑满剩余高度，表格内部滚动、分页固定卡底 -->
      <el-card shadow="never" class="block-card card-fill">
        <template #header>
          <div class="card-header">
            <span class="card-title">识别记录</span>
            <span class="card-hint">共 {{ total }} 条；点击「查看」可打开核对弹窗继续导入</span>
          </div>
        </template>
        <div class="toolbar">
          <el-form :inline="true" class="tb-left">
            <el-form-item label="关键字">
              <el-input v-model="query.keyword" placeholder="单号 / 供应商" clearable style="width: 180px" @keyup.enter="onSearch" />
            </el-form-item>
            <el-form-item label="状态">
              <el-select v-model="query.status" placeholder="全部" clearable style="width: 120px">
                <el-option label="待确认" value="待确认" />
                <el-option label="已导入" value="已导入" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :icon="Search" @click="onSearch">查询</el-button>
              <el-button :icon="Refresh" @click="onReset">重置</el-button>
            </el-form-item>
          </el-form>
        </div>
        <!-- 批量操作条：勾选后才出现，不占固定高度 -->
        <BatchBar :batch="batch" :actions="batchActions" @action="onBatchAction" />
        <div class="table-wrap">
          <el-table :ref="batch.bindTable" :data="records" :row-key="(row) => row.id" v-loading="loadingRecords" border stripe
                    empty-text="暂无识别记录，先在上方上传单据照片" @selection-change="batch.onSelectionChange">
            <el-table-column type="selection" width="50" align="center" reserve-selection />
            <el-table-column type="index" label="#" width="50" align="center" />
            <el-table-column label="照片" width="72" align="center">
              <template #default="{ row }"><OcrThumb :record="row" :size="46" /></template>
            </el-table-column>
            <el-table-column prop="doc_no" label="单号" min-width="160" show-overflow-tooltip>
              <template #default="{ row }"><span class="doc-no">{{ row.doc_no || '—' }}</span></template>
            </el-table-column>
            <el-table-column prop="doc_type" label="类型" width="90" align="center">
              <template #default="{ row }"><el-tag size="small" effect="plain">{{ row.doc_type || '单据' }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="supplier_name" label="供应商" min-width="160" show-overflow-tooltip />
            <el-table-column label="明细" width="110" align="center">
              <template #default="{ row }">
                <span :class="{ 'num-warn': row.matched_count < row.item_count }">
                  {{ row.matched_count }}/{{ row.item_count }} 已匹配
                </span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="90" align="center">
              <template #default="{ row }">
                <el-tag :type="row.status === '已导入' ? 'success' : 'warning'" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="识别时间" width="160" />
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="onView(row)">查看</el-button>
                <el-button link type="danger" v-permission="'ai:ocr:delete'" :disabled="!!row.arrival_id" @click="onDelete(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <div class="pager">
          <span class="hint">共 <b>{{ total }}</b> 条 · 第 {{ query.page }} / {{ pageCount }} 页</span>
          <el-pagination background layout="sizes, prev, pager, next" :total="total"
                         v-model:current-page="query.page" v-model:page-size="query.page_size"
                         :page-sizes="[10, 20, 50]" @current-change="fetchRecords" @size-change="fetchRecords" />
        </div>
      </el-card>
    </div>

    <!-- 识别结果核对弹窗 -->
    <el-dialog v-model="dialog.visible" title="识别结果核对与导入" width="960px" class="detail-dialog" :close-on-click-modal="false">
      <div v-if="dialog.record" class="detail-body">
        <el-form :inline="true" class="meta-form" label-width="80px">
          <el-form-item label="单据类型">
            <el-select v-model="dialog.form.doc_type" style="width: 130px">
              <el-option v-for="t in info.doc_types" :key="t" :label="t" :value="t" />
            </el-select>
          </el-form-item>
          <el-form-item label="单号">
            <el-input v-model="dialog.form.doc_no" style="width: 200px" placeholder="识别到的单号" />
          </el-form-item>
          <el-form-item label="供应商">
            <el-select v-model="dialog.form.supplier_id" filterable clearable placeholder="请选择供应商" style="width: 240px">
              <el-option v-for="s in suppliers" :key="s.id" :label="s.supplier_name" :value="s.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="原图">
            <span class="muted">{{ dialog.record.image_name }}（{{ (dialog.record.image_size / 1024).toFixed(0) }} KB · {{ dialog.record.provider }}）</span>
          </el-form-item>
        </el-form>

        <div class="src-photo">
          <span class="src-label">识别原照片</span>
          <OcrThumb :record="dialog.record" size="150px" :show-tip="false" fit="contain" />
          <span class="src-hint">核对时可对照原照片，点击图片可放大查看</span>
        </div>

        <el-alert v-if="dialog.form.supplier_name && !dialog.form.supplier_id" type="info" :closable="false" show-icon class="gap"
          :title="`识别到的供应商「${dialog.form.supplier_name}」未匹配到档案，可手工选择后再导入`" />

        <div class="items-head">
          <span class="card-title">物料明细</span>
          <el-button size="small" type="primary" plain :icon="Plus" @click="addRow">添加明细行</el-button>
        </div>
        <el-table :data="dialog.form.items" border size="small" max-height="320">
          <el-table-column type="index" label="#" width="45" align="center" />
          <el-table-column label="识别物料名称" min-width="150">
            <template #default="{ row }"><el-input v-model="row.material_name" size="small" /></template>
          </el-table-column>
          <el-table-column label="匹配系统物料" min-width="200">
            <template #default="{ row }">
              <el-select v-model="row.material_id" filterable remote clearable placeholder="搜索选择物料"
                         :remote-method="(q) => searchMaterial(q, row)" size="small" style="width: 100%"
                         @change="(v) => onMaterialChange(row, v)">
                <el-option v-for="m in row._options || materials" :key="m.id"
                           :label="`${m.material_name}（${m.spec || '无规格'}）`" :value="m.id" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="规格" width="130">
            <template #default="{ row }"><el-input v-model="row.spec" size="small" /></template>
          </el-table-column>
          <el-table-column label="单位" width="80">
            <template #default="{ row }"><el-input v-model="row.unit" size="small" /></template>
          </el-table-column>
          <el-table-column label="数量" width="130">
            <template #default="{ row }">
              <el-input-number v-model="row.qty" :min="0" :precision="qtyPrecision(row.unit)" :controls="false" size="small" style="width: 100%" />
            </template>
          </el-table-column>
          <el-table-column label="状态" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="row.material_id ? 'success' : 'danger'" size="small">{{ row.material_id ? '已匹配' : '未匹配' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="70" align="center">
            <template #default="{ $index }">
              <el-button link type="danger" @click="dialog.form.items.splice($index, 1)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-divider class="divider" />

        <div class="import-head">
          <span class="card-title">导入设置</span>
          <span class="card-hint">填写「关联采购订单 + 收货仓库」并保证明细全部匹配物料时，导入将生成采购到货单（待验收）；否则仅留档识别结果</span>
        </div>
        <el-form :inline="true" label-width="100px">
          <el-form-item label="关联订单">
            <el-select v-model="dialog.form.order_id" filterable clearable placeholder="选择已审核 / 部分到货的采购订单" style="width: 300px">
              <el-option v-for="o in orders" :key="o.id" :label="`${o.order_no} · ${o.supplier_name}（${o.status}）`" :value="o.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="收货仓库">
            <el-select v-model="dialog.form.warehouse_id" clearable placeholder="请选择仓库" style="width: 200px">
              <el-option v-for="w in warehouses" :key="w.id" :label="w.warehouse_name" :value="w.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="dialog.form.remark" style="width: 300px" placeholder="可填来源说明" />
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="dialog.visible = false">关 闭</el-button>
        <el-button type="primary" plain :loading="saving === 'archive'" v-permission="'ai:ocr:import'" @click="onImport(true)">仅留档</el-button>
        <el-button type="primary" :loading="saving === 'arrival'" v-permission="'ai:ocr:import'" @click="onImport(false)">确认导入并生成到货单</el-button>
      </template>
    </el-dialog>

    <!-- 大模型配置抽屉：保存多份档案、点启用即时切换，只有管理员能打开 -->
    <el-drawer v-model="cfgDrawer.visible" title="大模型配置" size="960px" destroy-on-close>
      <div class="cfg-body">
        <el-alert v-if="cfgDrawer.source === 'env'" type="info" :closable="false" show-icon class="cfg-tip"
          title="当前没有启用中的模型档案，识别使用的是 .env 配置"
          :description="`${cfgDrawer.envEngine.provider}${cfgDrawer.envEngine.model ? ' · ' + cfgDrawer.envEngine.model : ''}${cfgDrawer.envEngine.key_configured ? '' : '（未配置密钥）'}。新建一份档案并启用后即改由档案控制，无需重启后端。`" />
        <div class="cfg-head">
          <span class="card-hint">识别引擎参数在「启用」后即时生效；API Key 仅管理员可见且页面只显示脱敏值</span>
          <el-button type="primary" :icon="Plus" @click="openConfigForm(null)">新建配置</el-button>
        </div>

        <el-table :data="cfgDrawer.list" v-loading="cfgDrawer.loading" stripe size="small">
          <el-table-column prop="name" label="配置名称" min-width="150" show-overflow-tooltip />
          <el-table-column label="引擎 / 模型" min-width="200">
            <template #default="{ row }">
              <div>{{ row.provider_label }}</div>
              <div class="muted">{{ row.effective_model || '（默认模型）' }}</div>
            </template>
          </el-table-column>
          <el-table-column label="接口地址" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">{{ row.effective_base_url || '—' }}</template>
          </el-table-column>
          <el-table-column label="API Key" width="130">
            <template #default="{ row }">
              <el-tag :type="row.key_configured ? 'success' : 'info'" size="small" effect="plain">
                {{ row.key_configured ? row.api_key_masked : '未配置' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="超时 / 重试" width="100" align="center">
            <template #default="{ row }">{{ row.timeout }}s / {{ row.retry }}次</template>
          </el-table-column>
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用中' : '未启用' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="250" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" :disabled="row.is_active" @click="onActivate(row)">启用</el-button>
              <el-button link type="primary" :loading="cfgDrawer.testingId === row.id" @click="onTestConfig(row)">测试</el-button>
              <el-button link type="primary" @click="openConfigForm(row)">编辑</el-button>
              <el-button link type="danger" @click="onRemoveConfig(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-drawer>

    <!-- 新增 / 编辑模型档案 -->
    <el-dialog v-model="cfgForm.visible" :title="cfgForm.id ? '编辑模型配置' : '新建模型配置'" width="640px" append-to-body>
      <el-form :model="cfgForm.form" label-width="110px">
        <el-form-item label="配置名称" required>
          <el-input v-model="cfgForm.form.name" maxlength="64" placeholder="如：通义千问-VL（生产）" />
        </el-form-item>
        <el-form-item label="引擎类型" required>
          <el-select v-model="cfgForm.form.provider" style="width: 100%" @change="onProviderChange">
            <el-option v-for="p in cfgDrawer.presets" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="接口地址">
          <el-input v-model="cfgForm.form.base_url" placeholder="留空则使用该引擎的默认地址" />
        </el-form-item>
        <el-form-item label="模型名称">
          <el-input v-model="cfgForm.form.model" placeholder="留空则使用该引擎的默认视觉模型" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="cfgForm.form.api_key" type="password" show-password
            :placeholder="cfgForm.id ? (cfgForm.keyConfigured ? '已配置，留空表示不修改' : '尚未配置') : '填写该引擎的密钥（mock 无需填写）'" />
        </el-form-item>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="cfgForm.form.timeout" :min="3" :max="600" />
          <span class="muted cfg-inline">网络慢的网关可调大到 120</span>
        </el-form-item>
        <el-form-item label="失败重试">
          <el-input-number v-model="cfgForm.form.retry" :min="0" :max="5" />
          <span class="muted cfg-inline">网络异常 / 5xx 时的重试次数</span>
        </el-form-item>
        <el-form-item label="JSON 模式">
          <el-switch v-model="cfgForm.form.json_mode" />
          <span class="muted cfg-inline">个别网关不支持 response_format 时关闭</span>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="cfgForm.form.remark" maxlength="255" placeholder="可填用途、额度说明等" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="cfgForm.visible = false">取 消</el-button>
        <el-button type="primary" :loading="cfgForm.saving" @click="onSaveConfig">保 存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { MagicStick, Search, Refresh, Plus, UploadFilled, Connection, Picture, Setting } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { errorText } from '@/utils/request'
import { aiOcrApi } from '@/api/aiOcr'
import { materialApi, supplierApi, warehouseApi } from '@/api/basicData'
import { orderApi } from '@/api/procurement'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import BatchBar from '@/components/BatchBar.vue'
import OcrThumb from '@/components/OcrThumb.vue'

// 离散单位（个/条/件…）数量取整，连续单位（米/kg…）保留 2 位小数
const DISCRETE_UNITS = ['个', '条', '件', '套', '张', '双', '块', '只', '副', '箱']
const qtyPrecision = (unit) => (DISCRETE_UNITS.includes(unit) ? 0 : 2)

const info = ref({ provider: 'mock', is_remote: false, model: '', base_url: '', key_configured: false, source: 'env', config_name: '', doc_types: ['送货单', '发票', '单据'], max_mb: 8 })
const testing = ref(false)
const recogError = ref('')   // 最近一次识别失败的原因，常驻展示在页面上
// 引擎标签悬浮提示：把配置来源 / 接口地址 / 模型 / 密钥状态收进 tooltip，避免页面上再堆一条成功提示
const engineTip = computed(() => {
  const from = info.value.source === 'database'
    ? `配置来源：模型配置「${info.value.config_name || '未命名'}」`
    : '配置来源：backend/.env'
  return info.value.is_remote
    ? `${from} · 接口地址 ${info.value.base_url} · 模型 ${info.value.model} · 密钥${info.value.key_configured ? '已配置' : '未配置'}`
    : `${from} · 离线演示引擎（mock），无需密钥`
})

// ---- 识别记录列表 ----
const query = reactive({ page: 1, page_size: 20, keyword: '', status: '' })
const records = ref([])
const total = ref(0)
const loadingRecords = ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))

// ---- 上传（支持单张与批量：files.length > 1 即进入批量模式） ----
const MAX_BATCH_FILES = 20   // 与后端无冲突，纯前端节流：串行调视觉模型，20 张约 1~2 分钟
const uploadRef = ref(null)
const files = ref([])        // [{ uid, name, size, raw, status, reason }]
const previewUrl = ref('')
const recognizing = ref(false)
const lastRec = ref(null)    // 最近一次识别成功的记录，用于点亮流程引导
const progress = reactive({ done: 0, total: 0, current: '' })
const batchResult = ref(null)   // 批量识别汇总（成功 N 张 / 失败 M 张）
let cancelFlag = false          // 用户点「停止」后，串行循环在当前张结束后退出

const isBatch = computed(() => files.value.length > 1)
const pendingList = computed(() => files.value.filter((f) => f.status === 'pending'))
const failedCount = computed(() => files.value.filter((f) => f.status === 'fail').length)
// 有待识别或有失败可重试时才可点（失败项在 onRecognize 开头会自动重排回队列）
const canRecognize = computed(() => !recognizing.value
  && (pendingList.value.length > 0 || failedCount.value > 0))
const progressPct = computed(() => (progress.total
  ? Math.round((progress.done / progress.total) * 100) : 0))
const recognizeBtnText = computed(() => {
  if (!recognizing.value) {
    const n = pendingList.value.length
    if (!n) return failedCount.value ? `重试失败的 ${failedCount.value} 张` : '已全部识别完成'
    if (isBatch.value) return `开始批量识别（${n} 张）`
    return failedCount.value ? '识别失败，点击重试' : '开始识别'
  }
  return progress.total > 1
    ? `识别中 ${Math.min(progress.done + 1, progress.total)}/${progress.total}…`
    : '识别中，请稍候…'
})
const STATUS_LABELS = { pending: '待识别', running: '识别中', ok: '已识别', fail: '失败' }
const statusLabel = (s) => STATUS_LABELS[s] || s
const statusType = (s) => (s === 'ok' ? 'success' : (s === 'fail' ? 'danger' : (s === 'running' ? 'primary' : 'info')))

// ---- 流程引导 ----
const stepList = [
  { n: 1, title: '上传单据照片', desc: '可多选批量识别' },
  { n: 2, title: 'AI 识别提取', desc: '单号·供应商·物料·数量' },
  { n: 3, title: '核对并导入', desc: '生成采购到货单' }
]
const currentStep = computed(() => (!files.value.length ? 1 : (lastRec.value ? 3 : 2)))
function stepCls(n) {
  if (n < currentStep.value) return 'done'
  return n === currentStep.value ? 'active' : ''
}

// ---- 下拉选项 ----
const materials = ref([])
const suppliers = ref([])
const warehouses = ref([])
const orders = ref([])

// ---- 核对弹窗 ----
const dialog = reactive({ visible: false, record: null, form: emptyForm() })
const saving = ref('')

function emptyForm() {
  return { doc_type: '送货单', doc_no: '', supplier_id: null, supplier_name: '', order_id: null, warehouse_id: null, remark: '', items: [] }
}

async function loadInfo() {
  try { info.value = { ...info.value, ...(await aiOcrApi.info()) } } catch { /* 使用默认展示 */ }
}

/** 测试当前识别引擎连通性 */
async function onTest() {
  testing.value = true
  try {
    const res = await aiOcrApi.test()
    res.ok
      ? ElMessage.success(res.message || '连接成功')
      : ElMessage.error(res.message || '连接失败')
  } finally {
    testing.value = false
  }
}

// ================= 大模型配置 =================
// 保存多份「模型档案」，点启用即时切换识别引擎；只有 admin 有 ai:ocr:config 权限。
const cfgDrawer = reactive({
  visible: false, loading: false, testingId: 0,
  list: [], presets: [], active_id: null, source: 'env',
  envEngine: { provider: 'mock', model: '', base_url: '', is_remote: false, key_configured: false }
})
const cfgForm = reactive({ visible: false, id: null, saving: false, keyConfigured: false, form: emptyCfgForm() })

function emptyCfgForm() {
  return { name: '', provider: 'mock', base_url: '', model: '', api_key: '', timeout: 60, retry: 1, json_mode: true, remark: '' }
}

async function loadConfigs() {
  cfgDrawer.loading = true
  try {
    const res = await aiOcrApi.configs()
    cfgDrawer.list = res.list || []
    cfgDrawer.presets = res.presets || []
    cfgDrawer.active_id = res.active_id
    cfgDrawer.source = res.source || 'env'
    cfgDrawer.envEngine = res.env_engine || cfgDrawer.envEngine
  } finally {
    cfgDrawer.loading = false
  }
}

async function openConfigs() {
  cfgDrawer.visible = true
  try {
    await loadConfigs()
  } catch (e) {
    ElMessage.error(errorText(e) || '加载模型配置失败')
  }
}

/** 切换引擎时按预设填充地址与模型（用户已手填的不覆盖） */
function onProviderChange(value) {
  const p = cfgDrawer.presets.find((x) => x.value === value)
  if (!p) return
  if (!cfgForm.form.base_url) cfgForm.form.base_url = p.base_url || ''
  if (!cfgForm.form.model) cfgForm.form.model = p.model || ''
}

function openConfigForm(row) {
  cfgForm.id = row ? row.id : null
  cfgForm.keyConfigured = !!(row && row.key_configured)
  cfgForm.form = row
    ? {
        name: row.name, provider: row.provider, base_url: row.base_url, model: row.model,
        api_key: '', timeout: row.timeout, retry: row.retry, json_mode: row.json_mode, remark: row.remark
      }
    : emptyCfgForm()
  cfgForm.visible = true
}

async function onSaveConfig() {
  const f = cfgForm.form
  if (!f.name.trim()) return ElMessage.warning('请填写配置名称')
  cfgForm.saving = true
  try {
    const payload = { ...f, name: f.name.trim() }
    // 编辑时留空 = 不修改密钥：传 null，让后端保留原值（页面只拿到脱敏串，回传会把真 key 覆盖成星号）
    if (cfgForm.id && !f.api_key) payload.api_key = null
    if (cfgForm.id) await aiOcrApi.updateConfig(cfgForm.id, payload)
    else await aiOcrApi.createConfig(payload)
    ElMessage.success('模型配置已保存')
    cfgForm.visible = false
    await loadConfigs()
    await loadInfo()
  } catch (e) {
    ElMessage.error(errorText(e) || '保存失败')
  } finally {
    cfgForm.saving = false
  }
}

async function onActivate(row) {
  try {
    await aiOcrApi.activateConfig(row.id)
    ElMessage.success(`已启用「${row.name}」，下次识别立即使用该配置`)
    await loadConfigs()
    await loadInfo()
  } catch (e) {
    ElMessage.error(errorText(e) || '启用失败')
  }
}

async function onTestConfig(row) {
  cfgDrawer.testingId = row.id
  try {
    const res = await aiOcrApi.testConfig(row.id)
    res.ok ? ElMessage.success(res.message || '连接成功') : ElMessage.error(res.message || '连接失败')
  } catch (e) {
    ElMessage.error(errorText(e) || '测试失败')
  } finally {
    cfgDrawer.testingId = 0
  }
}

async function onRemoveConfig(row) {
  try {
    await ElMessageBox.confirm(`确定删除模型配置「${row.name}」吗？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await aiOcrApi.removeConfig(row.id)
    ElMessage.success('已删除')
    await loadConfigs()
    await loadInfo()
  } catch (e) {
    ElMessage.error(errorText(e) || '删除失败')
  }
}

// 下拉候选（物料/供应商/仓库/采购订单）。各角色权限不同，缺某项权限时接口会 403，
// 因此用 allSettled 兜底：能拉的照常填充，拉不到的留空，绝不因此中断 records 加载。
async function loadOptions() {
  const [mats, sups, whs, ords] = await Promise.allSettled([
    materialApi.list({ page: 1, page_size: 1000 }),
    supplierApi.list({ page: 1, page_size: 1000 }),
    warehouseApi.all(),
    orderApi.list({ page: 1, page_size: 500 })
  ])
  const pick = (r, fallback) => (r.status === 'fulfilled' ? r.value : fallback)
  materials.value = (pick(mats, { list: [] }).list) || []
  suppliers.value = (pick(sups, { list: [] }).list) || []
  warehouses.value = pick(whs, []) || []
  orders.value = ((pick(ords, { list: [] }).list) || []).filter((o) => ['已审核', '部分到货'].includes(o.status))
}

async function fetchRecords() {
  loadingRecords.value = true
  try {
    const res = await aiOcrApi.records({ ...query })
    records.value = res.list || []
    total.value = res.total || 0
  } finally {
    loadingRecords.value = false
  }
}
// ---- 识别记录的批量操作 ----
const batch = useBatch({ fetchList: fetchRecords })
// 只接 delete：后端 BATCH_PERMS 仅开放删除，批量导入（生成到货单）风险过高未做
const batchActions = [
  { key: 'delete', label: '批量删除', type: 'danger', perm: 'ai:ocr:delete' },
  { key: 'export', label: '导出选中', perm: 'ai:ocr:list' }
]
// 导出用列定义与表格列保持一致，避免导出后对不上
const exportColumns = [
  { prop: 'doc_no', label: '单号' },
  { prop: 'doc_type', label: '类型' },
  { prop: 'supplier_name', label: '供应商' },
  // 与表格「明细」列一致：显示 x/y 已匹配
  { prop: 'matched_count', label: '明细', formatter: (r) => `${r.matched_count}/${r.item_count} 已匹配` },
  { prop: 'status', label: '状态' },
  { prop: 'created_at', label: '识别时间' }
]

async function onBatchAction(key) {
  if (key === 'export') {
    exportRows(batch.selected.value, exportColumns, 'AI识别记录')
    return
  }
  const n = batch.count.value
  // 已生成到货单的记录行内按钮就是禁用的，批量删除同样会被后端逐条拒绝，必须提前告知
  const confirm = `确认删除选中的 ${n} 条识别记录？删除后不可恢复；已生成到货单的记录会被自动跳过（后端逐条拒绝，原因在结果弹窗中列出），请先处理对应到货单后再删除。`
  await batch.run(aiOcrApi.batch, key, { label: '批量删除', confirm })
}

function onSearch() { query.page = 1; batch.clearSelection(); fetchRecords() }
function onReset() { query.keyword = ''; query.status = ''; onSearch() }

/** el-upload 每加入一个文件触发一次；统一由 files 数组管理，内部列表即时清空 */
function onFilesChange(uploadFile) {
  const raw = uploadFile?.raw
  uploadRef.value?.clearFiles()
  if (!raw) return
  if (files.value.length >= MAX_BATCH_FILES) {
    return ElMessage.warning(`单次最多选择 ${MAX_BATCH_FILES} 张图片`)
  }
  files.value.push({
    uid: raw.uid || `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    name: raw.name || '未命名图片',
    size: raw.size || 0,
    raw,
    status: 'pending',
    reason: ''
  })
  if (files.value.length === 1) {
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = URL.createObjectURL(raw)   // 单张模式仍显示图片预览
  } else {
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''                          // 进入批量模式改用队列展示
  }
  recogError.value = ''
  lastRec.value = null
  batchResult.value = null
}
function onExceed() {
  ElMessage.warning(`单次最多选择 ${MAX_BATCH_FILES} 张图片，请分批识别`)
}
function removeFile(index) {
  if (recognizing.value) return
  files.value.splice(index, 1)
  // 从批量退回单张时恢复预览
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = files.value.length === 1 && files.value[0].raw
    ? URL.createObjectURL(files.value[0].raw) : ''
  recogError.value = ''
}
/** 清空已选图片，回到初始状态 */
function clearFiles() {
  if (recognizing.value) return
  uploadRef.value?.clearFiles()
  files.value = []
  previewUrl.value = ''
  lastRec.value = null
  recogError.value = ''
  batchResult.value = null
}
/** 把失败的重新放回待识别队列（单张与批量通用） */
function retryFailed() {
  files.value.forEach((f) => {
    if (f.status === 'fail') { f.status = 'pending'; f.reason = '' }
  })
  recogError.value = ''
  batchResult.value = null
}
function cancelBatch() {
  cancelFlag = true
  ElMessage.info('将在当前这张识别完成后停止')
}

async function onRecognize() {
  // 失败过的（含单张模式）自动重排到队列，允许再次点「开始识别」重试
  files.value.forEach((f) => {
    if (f.status === 'fail') { f.status = 'pending'; f.reason = '' }
  })
  const pending = files.value.filter((f) => f.status === 'pending')
  if (!pending.length) return ElMessage.warning('请先选择图片')
  const isBatchRun = isBatch.value
  const queue = isBatchRun ? pending : files.value
  recognizing.value = true
  cancelFlag = false
  recogError.value = ''
  batchResult.value = null
  progress.total = queue.length
  progress.done = 0
  let ok = 0
  let fail = 0
  try {
    for (const item of queue) {   // 串行：真实视觉模型逐张调用更稳，也能逐张回显状态
      if (cancelFlag) break
      progress.current = item.name
      item.status = 'running'
      item.reason = ''
      try {
        const formData = new FormData()
        formData.append('file', item.raw)
        const rec = await aiOcrApi.recognize(formData)
        item.status = 'ok'
        lastRec.value = rec
        ok += 1
        progress.done += 1
        if (!isBatchRun) {
          // 单张：沿用原有体验 —— 提示 + 直接打开核对弹窗
          ElMessage.success('识别完成，请核对后导入')
          fillDialog(rec)
        } else {
          fetchRecords()          // 批量：每成功一张就刷新记录，进度可见
        }
      } catch (err) {
        item.status = 'fail'
        item.reason = errorText(err)
        fail += 1
        progress.done += 1
        if (!isBatchRun) recogError.value = item.reason
      }
    }
  } finally {
    recognizing.value = false
    progress.current = ''
  }
  if (isBatchRun) {
    batchResult.value = { ok, fail }
    fetchRecords()
    if (fail && ok) ElMessage.warning(`批量识别完成：成功 ${ok} 张，失败 ${fail} 张`)
    else if (fail) ElMessage.error(`批量识别失败：${fail} 张均未识别成功`)
    else ElMessage.success(`批量识别完成：${ok} 张全部识别成功`)
  } else if (ok) {
    fetchRecords()
  }
}

/** 把识别记录回填到核对弹窗 */
function fillDialog(rec) {
  dialog.record = rec
  dialog.form = {
    doc_type: rec.doc_type || '送货单',
    doc_no: rec.doc_no || '',
    supplier_id: rec.supplier_id || null,
    supplier_name: rec.supplier_name || '',
    order_id: rec.order_id || null,
    warehouse_id: null,
    remark: '',
    items: (rec.items || []).map((i) => ({ ...i, _options: null }))
  }
  dialog.visible = true
}

async function onView(row) {
  const rec = await aiOcrApi.detail(row.id)
  lastRec.value = rec
  fillDialog(rec)
}

function addRow() {
  dialog.form.items.push({ id: null, material_name: '', material_id: null, spec: '', unit: '', qty: 0, _options: null })
}

/** 远程搜索物料，命中后缓存到该行下拉，避免逐行加载全量 */
function searchMaterial(q, row) {
  const kw = (q || '').trim()
  if (!kw) { row._options = null; return }
  row._options = materials.value.filter((m) => `${m.material_name}${m.spec || ''}`.includes(kw)).slice(0, 50)
}

/** 选中系统物料后回填规格 / 单位 / 名称（留空才覆盖，避免抹掉人工修改） */
function onMaterialChange(row, id) {
  const m = materials.value.find((x) => x.id === id) ||
    (row._options || []).find((x) => x.id === id)
  if (!m) return
  row.material_name = m.material_name
  if (!row.spec) row.spec = m.spec || ''
  if (!row.unit) row.unit = m.unit || ''
}

function buildItemsPayload() {
  return dialog.form.items
    .filter((i) => i.material_id || (i.material_name || '').trim() || i.qty)
    .map((i) => ({
      id: i.id, material_id: i.material_id, material_name: i.material_name,
      spec: i.spec, unit: i.unit, qty: i.qty
    }))
}

async function onImport(archiveOnly) {
  if (!dialog.record) return
  const payload = {
    doc_type: dialog.form.doc_type, doc_no: dialog.form.doc_no,
    supplier_id: dialog.form.supplier_id, supplier_name: dialog.form.supplier_name,
    order_id: dialog.form.order_id, warehouse_id: dialog.form.warehouse_id,
    remark: dialog.form.remark, items: buildItemsPayload()
  }
  if (!archiveOnly) {
    if (!payload.order_id) return ElMessage.warning('请选择关联采购订单')
    if (!payload.warehouse_id) return ElMessage.warning('请选择收货仓库')
    const missing = payload.items.filter((i) => !i.material_id)
    if (!payload.items.length) return ElMessage.warning('明细为空，无法生成到货单')
    if (missing.length) return ElMessage.warning('存在未匹配系统物料的明细，请先选择物料')
    try {
      await ElMessageBox.confirm('将按以上明细生成采购到货单（待验收），确认继续？', '提示', { type: 'warning' })
    } catch { return }
  }
  saving.value = archiveOnly ? 'archive' : 'arrival'
  try {
    const res = await aiOcrApi.importRecord(dialog.record.id, payload)
    ElMessage.success(res.arrival_no ? `已生成到货单 ${res.arrival_no}` : '识别结果已留档')
    dialog.visible = false
    fetchRecords()
  } finally {
    saving.value = ''
  }
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(`确认删除识别记录「${row.doc_no || row.image_name}」？`, '提示', { type: 'warning' })
  } catch { return }
  await aiOcrApi.remove(row.id)
  ElMessage.success('已删除')
  fetchRecords()
}

onMounted(async () => {
  await Promise.all([loadInfo(), loadOptions()])
  fetchRecords()
})
</script>

<style scoped>
/* 上下两张卡片：工作台按内容高度，识别记录吸收剩余高度（避免底部大片留白） */
.ai-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
}
.ai-stack > .block-card {
  flex: 0 0 auto;
}
.ai-stack > .block-card.card-fill {
  flex: 1 1 auto;
  min-height: 0;
}
.block-card {
  border: 1px solid var(--border);
}
.block-card :deep(.el-card__body) {
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
}

/* ---------- 流程引导（单行紧凑） ---------- */
.steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 10px;
}
.step {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 11px;
  border: 1px solid var(--border, #dcdfe6);
  border-radius: 8px;
  background: #fafbfc;
  transition: all 0.2s;
}
.step i {
  flex: 0 0 22px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-style: normal;
  font-size: 12px;
  font-weight: 600;
  background: #e8ecf1;
  color: var(--text-2, #606266);
}
.step-txt {
  display: flex;
  align-items: baseline;
  gap: 6px;
  line-height: 1.3;
  min-width: 0;
}
.step-txt b {
  font-size: 13px;
  color: var(--text-1, #303133);
  white-space: nowrap;
}
.step-txt span {
  font-size: 12px;
  color: var(--text-3, #909399);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.step-txt span::before {
  content: '·';
  margin-right: 5px;
}
.step.active {
  border-color: var(--brand, #409eff);
  background: rgba(64, 158, 255, 0.06);
}
.step.active i {
  background: var(--brand, #409eff);
  color: #fff;
}
.step.done i {
  background: #67c23a;
  color: #fff;
}

/* ---------- 上传区 ---------- */
.upload-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.1fr);
  gap: 10px;
}
.upload-row :deep(.el-upload),
.upload-row :deep(.el-upload-dragger) {
  height: 100%;
}
.upload-row :deep(.el-upload-dragger) {
  padding: 16px 14px;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.upload-icon {
  font-size: 38px;
  color: var(--brand, #409eff);
}
.upload-text {
  margin-top: 6px;
  font-size: 14px;
  color: var(--text-1, #303133);
}
.upload-text em {
  font-style: normal;
  font-weight: 600;
  color: var(--brand, #409eff);
}
.upload-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-3, #909399);
}
.upload-side {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.preview {
  flex: 1 1 auto;
  min-height: 132px;
  border: 1px dashed var(--border, #dcdfe6);
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  background: #fafbfc;
}
.preview img {
  max-width: 100%;
  max-height: 200px;
  object-fit: contain;
}
.preview.empty {
  color: var(--text-3, #909399);
  font-size: 13px;
}
.preview.empty .el-icon {
  font-size: 24px;
  opacity: 0.65;
}
.file-line {
  display: flex;
  align-items: center;
  gap: 10px;
}
.file-name {
  flex: 1;
  font-size: 13px;
  color: var(--text-2, #606266);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-name.empty {
  color: var(--text-3, #909399);
}
/* ---- 批量识别：文件队列 ---- */
.queue-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 13px;
  color: var(--text-2, #606266);
}
.queue-head b {
  color: var(--brand, #409eff);
}
.queue-ops {
  display: flex;
  align-items: center;
  gap: 4px;
}
.queue-list {
  flex: 1 1 auto;
  min-height: 96px;
  max-height: 216px;
  overflow-y: auto;
  border: 1px solid var(--border, #dcdfe6);
  border-radius: 8px;
  background: #fafbfc;
  padding: 6px;
}
.queue-item {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) 54px 62px 46px;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-2, #606266);
}

.queue-item + .queue-item {
  margin-top: 2px;
}
.queue-item.running {
  background: rgba(64, 158, 255, 0.08);
}
.queue-item.ok {
  background: rgba(16, 185, 129, 0.07);
}
.queue-item.fail {
  background: rgba(245, 108, 108, 0.08);
}
.q-idx {
  text-align: center;
  color: var(--text-3, #909399);
}
.q-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.q-size {
  text-align: right;
  color: var(--text-3, #909399);
}
.q-del {
  justify-self: end;
}
/* 失败原因占整行，便于直接看到「密钥未配置 / 网络超时 / 图片过大」 */
.q-reason {
  grid-column: 2 / -1;
  margin: -2px 0 2px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--danger, #f56c6c);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.progress-line {
  display: flex;
  align-items: center;
  gap: 10px;
}
.progress-line :deep(.el-progress) {
  flex: 1 1 auto;
}
.progress-text {
  flex: none;
  font-size: 12px;
  color: var(--text-3, #909399);
  max-width: 46%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.go-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.go-btn {
  flex: 1 1 auto;
}
.card-header {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}
.card-title {
  font-weight: 600;
  color: var(--text-1, #303133);
}
.card-hint {
  font-size: 12px;
  color: var(--text-3, #909399);
  line-height: 1.4;
}
.gap {
  margin-bottom: 12px;
}
.engine-tag {
  margin-right: 4px;
}
.recog-error {
  margin-top: 10px;
}
.divider {
  margin: 10px 0;
}
.detail-body {
  max-height: 66vh;
  overflow: auto;
  padding-right: 6px;
}
.meta-form {
  margin-bottom: 0;
}
.items-head,
.import-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 4px 0 8px;
  flex-wrap: wrap;
}
.import-head {
  justify-content: flex-start;
}
.muted {
  font-size: 12px;
  color: var(--text-3, #909399);
}
/* 模型配置抽屉 */
.cfg-body {
  padding: 0 4px 8px;
}
.cfg-tip {
  margin-bottom: 12px;
}
.cfg-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.cfg-inline {
  margin-left: 10px;
}
.num-warn {
  color: #e6a23c;
  font-weight: 600;
}
.doc-no {
  font-weight: 600;
  color: var(--text-1, #303133);
}
/* 核对弹窗里的识别原照片：贴在元信息下方，核对明细时可随时对照 */
.src-photo {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 8px 12px;
  margin-bottom: 10px;
  background: var(--bg-2, #f7f9fc);
  border-radius: 6px;
}
.src-label {
  flex: none;
  font-size: 13px;
  font-weight: 600;
  line-height: 150px;
  color: var(--text-1, #303133);
}
.src-hint {
  font-size: 12px;
  color: var(--text-3, #909399);
  line-height: 1.6;
  padding-top: 4px;
}
</style>