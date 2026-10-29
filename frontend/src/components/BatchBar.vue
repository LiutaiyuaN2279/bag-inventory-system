<template>
  <!-- 勾选后才出现：不占位、不给页面留空白；勾选后紧跟在工具条下方 -->
  <div v-if="batch && batch.count.value" class="batch-bar">
    <span class="bb-count">
      已选 <b>{{ batch.count.value }}</b> 项
      <el-button link type="primary" size="small" @click="batch.clearSelection()">清空</el-button>
    </span>
    <div class="bb-actions">
      <el-button
        v-for="a in visibleActions"
        :key="a.key"
        :type="a.type || 'default'"
        size="small"
        :icon="a.icon"
        :loading="batch.loading.value"
        @click="$emit('action', a.key)"
      >{{ a.label }}</el-button>
      <slot />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useUserStore } from '@/store/user'

const props = defineProps({
  batch: { type: Object, required: true },
  /** [{ key, label, type?, icon?, perm? }]，perm 为空表示不校验权限 */
  actions: { type: Array, default: () => [] }
})
defineEmits(['action'])

const store = useUserStore()
// 按权限过滤：无权限的批量动作直接不渲染，与行操作按钮的 v-permission 行为一致
const visibleActions = computed(() => props.actions.filter((a) => !a.perm || store.hasPermission(a.perm)))
</script>

<style scoped>
.batch-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  padding: 7px 12px;
  border: 1px solid rgba(16, 185, 129, .35);
  background: var(--brand-soft, #ecfdf5);
  border-radius: 6px;
}
.bb-count { font-size: 12px; color: var(--text-2, #606266); }
.bb-count b { color: var(--brand-dark, #065f46); font-size: 13px; }
.bb-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
</style>
