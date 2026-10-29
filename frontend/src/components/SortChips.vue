<template>
  <div v-if="rules && rules.length" class="sort-chips">
    <span class="sort-chips__label">多级排序：</span>
    <el-tag
      v-for="(r, i) in rules"
      :key="r.prop"
      closable
      type="primary"
      effect="plain"
      class="sort-chips__item"
      @close="$emit('remove', r.prop)"
    >
      {{ i + 1 }}. {{ r.label }} {{ r.order === 'asc' ? '↑' : '↓' }}
    </el-tag>
    <el-button link type="primary" size="small" @click="$emit('clear')">清除排序</el-button>
  </div>
</template>

<script setup>
defineProps({ rules: { type: Array, default: () => [] } })
defineEmits(['remove', 'clear'])
</script>

<style scoped>
.sort-chips { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.sort-chips__label { font-size: 12px; color: #909399; }
.sort-chips__item { font-weight: normal; }
</style>
