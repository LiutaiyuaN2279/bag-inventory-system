<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    :width="width"
    align-center
    draggable
    destroy-on-close
    class="detail-dialog"
    @close="onClose"
    @update:model-value="(v) => $emit('update:modelValue', v)"
  >
    <template #header>
      <div class="dtl-header">
        <div class="dtl-title">
          <el-icon class="dtl-title-icon"><Document /></el-icon>
          <span>{{ title }}</span>
        </div>
        <div class="dtl-meta">
          <span v-if="docNo" class="dtl-docno">{{ docNo }}</span>
          <el-tag v-if="status" :type="statusType" size="small" effect="dark" round>{{ status }}</el-tag>
        </div>
      </div>
    </template>

    <div v-loading="loading" class="dtl-body">
      <slot name="default">
        <el-empty description="暂无详情" :image-size="60" />
      </slot>
    </div>

    <template #footer>
      <div class="dtl-footer">
        <el-button v-if="printable" type="primary" icon="Printer" @click="onPrint">打印</el-button>
        <el-button @click="onClose">关闭</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed } from 'vue'
import { Document } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { printDocument } from '@/utils/print'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '详情' },
  docNo: { type: String, default: '' },
  status: { type: String, default: '' },
  statusType: { type: String, default: 'info' },
  loading: { type: Boolean, default: false },
  width: { type: String, default: '1000px' },
  // 打印数据：单据对象，或返回单据对象的函数；不传则不显示「打印」按钮
  printData: { type: [Object, Function], default: null }
})
const emit = defineEmits(['update:modelValue'])

const printable = computed(() => !!props.printData)

function onClose() { emit('update:modelValue', false) }

/** 打印当前单据：同步取数，异常统一提示，不产生未捕获的 Promise */
function onPrint() {
  try {
    const doc = typeof props.printData === 'function' ? props.printData() : props.printData
    if (!doc) return ElMessage.warning('暂无可打印的单据数据')
    printDocument(doc)
  } catch (e) {
    ElMessage.error('打印失败：' + (e && e.message ? e.message : e))
  }
}
</script>

<style scoped>
.dtl-header { display: flex; align-items: center; justify-content: space-between; padding: 2px 18px 12px 2px; border-bottom: 1px solid #ebeef5; margin-bottom: 4px; }
.dtl-title { display: flex; align-items: center; gap: 10px; font-size: 17px; font-weight: 700; color: #1f2937; letter-spacing: .3px; }
.dtl-title-icon { color: #fff; background: linear-gradient(135deg,#409eff,#36cfc9); width: 26px; height: 26px; border-radius: 7px; display:flex; align-items:center; justify-content:center; font-size: 16px; }
.dtl-meta { display: flex; align-items: center; gap: 10px; }
.dtl-docno { font-family: 'Consolas', monospace; font-size: 13px; color: #606266; background: #f4f4f5; padding: 3px 12px; border-radius: 12px; }
.dtl-body { max-height: 70vh; overflow: auto; padding: 6px 4px 6px 0; }
.dtl-footer { display: flex; justify-content: flex-end; gap: 10px; padding-top: 10px; border-top: 1px solid #ebeef5; margin-top: 8px; }
/* 深槽滚动条 */
.dtl-body::-webkit-scrollbar { width: 8px; }
.dtl-body::-webkit-scrollbar-thumb { background: #c0c4cc; border-radius: 4px; }
.dtl-body::-webkit-scrollbar-thumb:hover { background: #909399; }
</style>
<style>
/* 弹窗最大宽度不超过视口，小屏自适应 */
.detail-dialog { --el-dialog-margin-top: 6vh !important; }
.detail-dialog .el-dialog { max-width: 94vw; border-radius: 12px; overflow: hidden; }
</style>
