<template>
  <router-view />
</template>

<script setup>
</script>

<style>
/* ========== 全局设计变量（全站统一主题源） ========== */
:root {
  --brand: #10b981;            /* 主色：翡翠绿 */
  --brand-dark: #065f46;
  --brand-soft: #ecfdf5;
  --accent: #27D2BF;           /* 辅助色：青绿 */
  --text-1: #1f2937;
  --text-2: #6b7280;
  --text-3: #9ca3af;
  --border: #e8ebf1;
  --bg: #f3f5fa;
  --card: #ffffff;
  --radius: 10px;
  --shadow-sm: 0 1px 3px rgba(16, 24, 40, .06), 0 1px 2px rgba(16, 24, 40, .04);
  --shadow-md: 0 8px 20px rgba(16, 24, 40, .08);

  /* Element Plus 主题覆盖：主色及色阶 */
  --el-color-primary: #10b981;
  --el-color-primary-dark-2: #0c8a66;
  --el-color-primary-light-3: #5cc9a5;
  --el-color-primary-light-5: #8fd9c0;
  --el-color-primary-light-7: #c2ebe0;
  --el-color-primary-light-8: #d6f2e8;
  --el-color-primary-light-9: #ecfaf4;
  --el-border-radius-base: 8px;
  --el-font-family: "PingFang SC", "Microsoft YaHei", system-ui, -apple-system, sans-serif;
}

* { box-sizing: border-box; }
html, body, #app { height: 100%; margin: 0; padding: 0; }
body {
  font-family: var(--el-font-family);
  color: var(--text-1);
  background: var(--bg);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* ---------- 卡片统一质感 ---------- */
.el-card {
  border-radius: var(--radius) !important;
  border: 1px solid var(--border) !important;
  box-shadow: var(--shadow-sm) !important;
  transition: box-shadow .2s ease, transform .2s ease;
}
.el-card__header {
  font-weight: 600;
  color: var(--text-1);
  border-bottom: 1px solid var(--border) !important;
  background: linear-gradient(180deg, #fbfcfe, #ffffff);
}

/* ---------- 表格美化 ---------- */
.el-table { border-radius: 8px; overflow: hidden; }
.el-table th.el-table__cell {
  background: #f6f8fc !important;
  color: #374151 !important;
  font-weight: 600;
}
.el-table tbody tr:hover > td { background: #f1faf5 !important; }

/* ---------- 按钮 / 标签 / 输入 ---------- */
.el-button--primary {
  box-shadow: 0 2px 8px rgba(16, 185, 129, .3);
  transition: transform .15s ease, box-shadow .2s ease;
}
.el-button--primary:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(16, 185, 129, .4); }
.el-tag { border-radius: 6px; }
.el-input__wrapper, .el-select__wrapper { border-radius: 8px !important; }

/* ---------- 滚动条 ---------- */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-thumb { background: #cdd5e3; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #aab6cc; }
::-webkit-scrollbar-track { background: transparent; }

/* ---------- 路由切换淡入 ---------- */
.fade-slide-enter-active { transition: opacity .25s ease, transform .25s ease; }
.fade-slide-enter-from { opacity: 0; transform: translateY(6px); }

/* ---------- 所有弹窗居中显示 ---------- */
.el-overlay-dialog {
  display: flex !important;
  align-items: center;
  justify-content: center;
  padding: 24px 16px;
}
.el-overlay-dialog .el-dialog {
  margin: 0 !important;
  max-height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
}
.el-overlay-dialog .el-dialog__body { flex: 1; overflow: auto; }

/* ---------- 通用工具类（供各页面引用） ---------- */
.gradient-text {
  background: linear-gradient(90deg, var(--brand), var(--accent));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.glass-card {
  background: rgba(255, 255, 255, .85);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, .6);
}

/* ==========================================================
   全站设计系统（骨架 / 密度 / 通用组件）
   约定：所有页面外层用 .page 撑满内容区；列表页用
   .card-fill + .table-wrap 让表格区内部滚动、分页固定底部，
   以消除「内容少时下方一大片空白」与「分页被视口切掉」。
   ========================================================== */

/* ---------- 1. 页面骨架 ---------- */
.page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  min-height: 0;
}
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.ph-title {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 17px;
  font-weight: 700;
  letter-spacing: .2px;
  color: var(--text-1);
}
.ph-desc { margin-top: 3px; font-size: 12px; line-height: 1.5; color: var(--text-2); }
.ph-desc b { color: var(--brand-dark); font-weight: 600; }
.ph-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

/* 关键：.page 是定高 flex 纵向容器，页面总高超出内容区时，
   flex 子项会被等比压缩——筛选卡会被压成几像素的白条（控件不可见）。
   除 .card-fill（允许收缩并内部滚动）外，其余区块一律不收缩。
   注：下面的 .card-fill 规则在源码中更靠后，同优先级下会赢回 flex-shrink。 */
.page > * { flex: 0 0 auto; }

/* 撑满剩余高度的卡片 */
.card-fill { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
.card-fill > .el-card__body {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
/* 表格区：内部滚动，表头吸顶，分页留在卡片底部 */
.table-wrap { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
.table-wrap > .el-table { flex: 1 1 auto; min-height: 0; }
.table-wrap .el-table__inner-wrapper { height: 100%; display: flex; flex-direction: column; }
.table-wrap .el-table__body-wrapper { flex: 1 1 auto; min-height: 0; overflow-y: auto; }

/* 卡内工具条：左侧筛选/统计，右侧操作按钮（取代独占一行的筛选卡） */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.toolbar .tb-left,
.toolbar .tb-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
/* 工具条里的内联表单压成一行，靠 gap 控制间距 */
.toolbar .el-form--inline { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.toolbar .el-form-item { margin: 0; }
.toolbar .sort-chips { margin-bottom: 0; }

/* 分页条 */
.pager { display: flex; align-items: center; justify-content: flex-end; gap: 12px; }
.pager .hint { margin-right: auto; font-size: 12px; color: var(--text-2); }
.pager .hint b { color: var(--brand-dark); font-weight: 600; }

/* 两栏栅格：导入导出、报表等页面用 */
.grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(430px, 1fr)); gap: 12px; align-items: start; }

/* ---------- 2. 全站密度 ---------- */
.el-main { padding: 14px 16px 16px; }
.el-card__body { padding: 14px 16px; }
.el-card__header { padding: 11px 16px 11px 22px; position: relative; font-size: 14px; }
/* 卡片标题左侧统一品牌色竖条 */
.el-card__header::before {
  content: '';
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 14px;
  border-radius: 2px;
  background: linear-gradient(180deg, var(--brand), var(--accent));
}
.el-form-item { margin-bottom: 14px; }
.el-dialog__header { padding: 14px 18px; margin-right: 0; border-bottom: 1px solid var(--border); }
.el-dialog__title { font-size: 15px; font-weight: 700; }
.el-dialog__body { padding: 16px 18px; }
.el-dialog__footer { padding: 12px 18px; border-top: 1px solid var(--border); }
.el-table .cell { padding: 0 10px; }
.el-table th.el-table__cell .cell { padding: 6px 10px; white-space: nowrap; }
.el-table .el-table__cell { padding: 6px 0; }
.el-table .el-table__cell.is-hidden > * { visibility: hidden; }
.el-descriptions__label { color: var(--text-2) !important; }
/* 金额/数量列：右对齐 + 等宽数字，小数点对齐 */
.el-table .col-num .cell { text-align: right; font-variant-numeric: tabular-nums; }

/* 表格空数据不留惨白 */
.el-table__empty-block { min-height: 180px; background: #fcfdff; }
.el-table__empty-text { color: var(--text-3); font-size: 13px; }

/* ---------- 3. 通用小组件 ---------- */
/* 统计条：列表页顶部一排小指标，填充空白并提升信息密度 */
.stat-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(158px, 1fr)); gap: 10px; }
.stat-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: linear-gradient(180deg, #fbfdff, #ffffff);
}
.stat-item .si-icon {
  width: 32px; height: 32px; flex: 0 0 32px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 9px; font-size: 17px;
}
.stat-item .si-num { font-size: 18px; font-weight: 700; line-height: 1.15; color: var(--text-1); font-variant-numeric: tabular-nums; }
.stat-item .si-label { font-size: 12px; color: var(--text-2); }

/* 圆点状态 */
.dot { display: inline-flex; align-items: center; gap: 5px; }
.dot::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: currentColor; opacity: .85; }

/* 数值 */
.num { font-variant-numeric: tabular-nums; }
.num-strong { font-variant-numeric: tabular-nums; font-weight: 600; color: var(--text-1); }
</style>
