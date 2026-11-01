<template>
  <el-alert class="audit-assurance" type="warning" show-icon :closable="false"
    :title="meta.assurance?.notice || '受限试算，非正式历史审计报告；历史可信范围尚未核定。'">
    <p>可支持的正式审计范围：尚未核定。受限范围：当前旧口径线索。份额余额、账龄、逾期和历史期间资格缺证时不可确定。</p>
    <p>已核实事实应保留；未知不等于零，零线索不等于审计通过。历史完整可追溯性尚不具备。</p>
    <p v-if="meta.run_id">试算运行编号：{{ meta.run_id }} · 刷新查看本版本，重新执行生成新版本。</p>
  </el-alert>
</template>

<script setup>
defineProps({ meta: { type: Object, default: () => ({}) } })
</script>

<style scoped>
.audit-assurance { flex: 0 0 auto; margin-bottom: 12px; overflow-wrap: anywhere; }
.audit-assurance p { margin: 4px 0; }
@media print { .audit-assurance { break-inside: avoid; } }
</style>
