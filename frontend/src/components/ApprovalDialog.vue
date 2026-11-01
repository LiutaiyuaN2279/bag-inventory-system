<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="880px"
    align-center
    draggable
    destroy-on-close
    class="approval-dialog"
    @close="onClose"
    @update:model-value="(v) => $emit('update:modelValue', v)"
  >
    <template #header>
      <div class="apv-header">
        <div class="apv-title">
          <el-icon class="apv-title-icon"><CircleCheck /></el-icon>
          <span>{{ title }}</span>
        </div>
        <div class="apv-meta">
          <span v-if="docNo" class="apv-docno">{{ docNo }}</span>
          <el-tag v-if="status" :type="statusType" size="small" effect="dark" round>{{ status }}</el-tag>
        </div>
      </div>
    </template>

    <div v-loading="loading" class="apv-body">
      <el-alert v-if="warn" :title="warn" type="warning" :closable="false" show-icon class="apv-warn" />

      <div class="apv-section">
        <slot name="default">
          <el-empty description="暂无详情" :image-size="60" />
        </slot>
      </div>

      <div class="apv-opinion">
        <div class="apv-opinion-label">
          <el-icon><EditPen /></el-icon>
          <span>审核意见</span>
          <span class="apv-optional">（通过可不填，驳回必填）</span>
        </div>
        <el-input
          v-model="opinion"
          type="textarea"
          :rows="2"
          maxlength="200"
          show-word-limit
          resize="none"
          placeholder="可填写审核意见，如无异议直接确认通过即可"
        />
      </div>
    </div>

    <template #footer>
      <div class="apv-footer">
        <el-button @click="onClose">取消</el-button>
        <el-button @click="onSkip">跳过</el-button>
        <el-button type="danger" :loading="loading" @click="onReject">驳回</el-button>
        <el-button :type="confirmType" :loading="loading" @click="onConfirm">
          <el-icon style="margin-right:4px"><Check /></el-icon>{{ confirmText }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { CircleCheck, EditPen, Check } from '@element-plus/icons-vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '审核' },
  docNo: { type: String, default: '' },
  status: { type: String, default: '' },
  statusType: { type: String, default: 'warning' },
  loading: { type: Boolean, default: false },
  confirmText: { type: String, default: '确认通过' },
  confirmType: { type: String, default: 'success' },
  warn: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue', 'confirm', 'cancel', 'skip', 'reject'])

const opinion = ref('')
watch(() => props.modelValue, (v) => { if (v) opinion.value = '' })
watch(() => props.docNo, () => { opinion.value = '' })

function onClose() { opinion.value = ''; emit('update:modelValue', false); emit('cancel') }
function onSkip() { opinion.value = ''; emit('skip') }
function onReject() {
  if (!opinion.value.trim()) { ElMessage.warning('请填写驳回原因'); return }
  emit('reject', opinion.value.trim())
}
function onConfirm() { emit('confirm', opinion.value) }
</script>

<style scoped>
.apv-header { display: flex; align-items: center; justify-content: space-between; padding-right: 16px; }
.apv-title { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 600; color: #303133; }
.apv-title-icon { color: #409eff; font-size: 18px; }
.apv-meta { display: flex; align-items: center; gap: 10px; }
.apv-docno { font-family: 'Consolas', monospace; font-size: 13px; color: #909399; background: #f4f4f5; padding: 2px 10px; border-radius: 10px; }
.apv-body { display: flex; flex-direction: column; gap: 14px; }
.apv-warn { margin: 0; }
.apv-section { border: 1px solid #ebeef5; border-radius: 8px; padding: 12px 14px; background: #fafafa; max-height: 44vh; overflow: auto; }
.apv-opinion { border: 1px solid #ebeef5; border-radius: 8px; padding: 10px 12px; background: #fff; }
.apv-opinion-label { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; color: #606266; margin-bottom: 8px; }
.apv-opinion-label .el-icon { color: #409eff; }
.apv-optional { color: #c0c4cc; font-weight: 400; font-size: 12px; }
.apv-footer { display: flex; justify-content: flex-end; gap: 10px; }
</style>
