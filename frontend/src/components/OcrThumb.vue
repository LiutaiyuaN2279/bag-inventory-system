<template>
  <!-- 原图未留存（升级前的历史记录 / 归档文件被清理）：只提示，不显示破图 -->
  <span v-if="!record || !record.has_image" class="thumb-none" :title="noImageTip">未留存</span>
  <div v-else-if="url" class="thumb-box">
    <el-image :src="url" :preview-src-list="[url]" :initial-index="0" :fit="fit" preview-teleported
              :style="boxStyle" class="thumb-img">
      <template #error><span class="thumb-none">加载失败</span></template>
    </el-image>
    <span v-if="showTip" class="thumb-tip">点击放大</span>
  </div>
  <span v-else class="thumb-none">加载中…</span>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { aiOcrApi } from '@/api/aiOcr'

/**
 * 识别记录的原照片缩略图。
 *
 * 原图接口需要 Bearer 头，而 `<img src>` 无法带自定义请求头，
 * 所以这里统一走 axios 取 Blob（request.js 对 responseType=blob 直通），
 * 再转成 objectURL 交给 el-image；el-image 的 preview 负责点击放大。
 *
 * 每个记录 id 只取一次：跨行/跨弹窗复用同一 objectURL（演示库图片很少，
 * 整页会话期内不主动回收，避免列表滚动时反复请求）。
 */
const props = defineProps({
  record: { type: Object, default: null },
  size: { type: [Number, String], default: 48 },
  // 说明性文字只在列表缩略图上显示；弹窗里已有「原图」字段标签，无需重复
  showTip: { type: Boolean, default: true },
  // 缩略图取 cover（裁切成方块）；弹窗里看整张单据用 contain 更合适
  fit: { type: String, default: 'cover' }
})

const cache = new Map()      // recordId -> objectURL
const url = ref('')
const noImageTip = computed(() => (props.record?.image_name
  ? `原图未留存（${props.record.image_name}）`
  : '原图未留存'))
// 弹窗可传字符串尺寸（如 '100%'），列表传数字像素
const boxStyle = computed(() => (typeof props.size === 'number'
  ? { width: `${props.size}px`, height: `${props.size}px` }
  : { width: props.size, height: props.size }))

async function load() {
  const rec = props.record
  if (!rec?.has_image) return
  const hit = cache.get(rec.id)
  if (hit) {
    url.value = hit
    return
  }
  try {
    const blob = await aiOcrApi.image(rec.id)
    const objUrl = URL.createObjectURL(blob)
    cache.set(rec.id, objUrl)
    url.value = objUrl
  } catch {
    // 取图失败不打断页面：request.js 已弹出错误提示，这里只需保持「加载中」以外的降级态
    url.value = ''
  }
}

onMounted(load)
</script>

<style scoped>
.thumb-box { position: relative; display: inline-block; line-height: 0; }
.thumb-img { border: 1px solid var(--border-1, #e6eaf2); border-radius: 4px; cursor: zoom-in; }
.thumb-tip { display: none; }
.thumb-box:hover .thumb-tip {
  display: block; position: absolute; inset: auto 0 0 0; text-align: center;
  font-size: 10px; line-height: 14px; color: #fff; background: rgba(0, 0, 0, .45);
  border-radius: 0 0 4px 4px;
}
.thumb-none { color: var(--text-3, #9aa4b2); font-size: 12px; }
</style>
