/**
 * ECharts 通用封装（composable）
 *
 * 职责：
 *  1. 按需创建 ECharts 实例（容器不可见时不初始化，避免 0 尺寸报错）；
 *  2. 数据变化时重新 setOption（notMerge，防止旧系列残留）；
 *  3. 容器尺寸变化自动 resize —— ResizeObserver 覆盖侧边栏折叠 / Tab 切换 / v-show 恢复 / 窗口缩放；
 *  4. 组件卸载时 dispose 实例、断开 ResizeObserver、移除 window 监听，绝不泄漏。
 *
 * 用法：
 *   const chartRef = ref(null)
 *   const buildOption = () => ({ ... })
 *   useChart(chartRef, buildOption, { watchSources: () => [trendData] })
 *
 * 同时导出项目统一的图表配色与常用 option 片段，保证各页面视觉一致。
 */
import { onBeforeUnmount, shallowRef, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { AxisPointerComponent, GridComponent, LegendComponent, TitleComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

// 按需注册：本项目所有图表统一从 useChart 引入，这里注册一次即可（控制打包体积）
echarts.use([
  LineChart, BarChart, PieChart,
  GridComponent, TooltipComponent, LegendComponent, TitleComponent, AxisPointerComponent,
  CanvasRenderer,
])

/* ------------------------------ 配色 ------------------------------ */
/** 分类/饼图等通用调色板（与系统主色协调） */
export const CHART_COLORS = ['#27D2BF', '#80C1FF', '#10b981', '#8b5cf6', '#e6a23c', '#f56c6c', '#0ea5e9', '#14b8a6']
/** 入库语义色 */
export const COLOR_IN = '#27D2BF'
/** 出库语义色 */
export const COLOR_OUT = '#f56c6c'

/* --------------------------- 通用 option 片段 --------------------------- */
export const AXIS_LABEL = { color: '#94a3b8', fontSize: 12 }
export const AXIS_LINE = { lineStyle: { color: '#e5e7eb' } }
export const SPLIT_LINE = { lineStyle: { color: '#f1f5f9' } }
export const CHART_TOOLTIP = {
  backgroundColor: 'rgba(15,23,42,.92)',
  borderWidth: 0,
  padding: [8, 12],
  textStyle: { color: '#fff', fontSize: 12 },
  extraCssText: 'border-radius:8px;box-shadow:0 6px 20px rgba(15,23,42,.18);',
}
/** 默认绘图区留白（图例在顶部时） */
export const DEFAULT_GRID = { left: 8, right: 18, top: 46, bottom: 6, containLabel: true }

/** 数值千分位 */
export const numText = (v) => Number(v || 0).toLocaleString('zh-CN')

/** 超长文本截断（图表坐标轴标签用，完整内容交给 tooltip） */
export const ellipsis = (text, max = 10) => {
  const s = String(text ?? '')
  if (!s) return '-'
  return s.length > max ? `${s.slice(0, max)}…` : s
}

/** #RRGGBB → rgba(...) */
function hexToRgba(hex, alpha) {
  const raw = String(hex || '').replace('#', '')
  const full = raw.length === 3 ? raw.split('').map(c => c + c).join('') : raw
  const n = parseInt(full, 16)
  if (Number.isNaN(n)) return `rgba(39,210,191,${alpha})`
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}

/** 纵向渐变：折线面积 / 纵向柱状（顶部浓、底部淡） */
export function areaGradient(color, fromOpacity = 0.3, toOpacity = 0.02) {
  return new echarts.graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: hexToRgba(color, fromOpacity) },
    { offset: 1, color: hexToRgba(color, toOpacity) },
  ])
}

/** 横向渐变：横向条形图（左浓右淡） */
export function hBarGradient(color, fromOpacity = 0.95, toOpacity = 0.5) {
  return new echarts.graphic.LinearGradient(0, 0, 1, 0, [
    { offset: 0, color: hexToRgba(color, fromOpacity) },
    { offset: 1, color: hexToRgba(color, toOpacity) },
  ])
}

/** 坐标轴触发的 tooltip 格式化（中文、数值千分位、可带单位） */
export function axisTooltipFormatter(unit = '') {
  return (params) => {
    const arr = Array.isArray(params) ? params : [params]
    if (!arr.length) return ''
    const head = arr[0].axisValueLabel ?? arr[0].name ?? ''
    const rows = arr.map(p => `<div style="display:flex;align-items:center;justify-content:space-between;gap:18px;line-height:20px">`
      + `<span>${p.marker}${p.seriesName}</span><b>${numText(p.value)}${unit ? ' ' + unit : ''}</b></div>`).join('')
    return `<div style="font-weight:600;margin-bottom:4px">${head}</div>${rows}`
  }
}

/** 空数据兜底：中性提示语，不抛异常、不留白 */
export function emptyOption(text = '暂无数据') {
  return {
    title: {
      text,
      left: 'center',
      top: 'middle',
      textStyle: { color: '#c0c4cc', fontSize: 14, fontWeight: 400 },
    },
    xAxis: { show: false, type: 'category', data: [] },
    yAxis: { show: false, type: 'value' },
    series: [],
  }
}

/* ------------------------------ 主封装 ------------------------------ */
/**
 * @param {import('vue').Ref<HTMLElement|null>} elRef 图表容器模板 ref
 * @param {() => object} getOption 返回 ECharts option 的函数（每次重绘时求值）
 * @param {{ theme?: string|object, watchSources?: () => any }} [options]
 *        theme：可选主题；watchSources：返回依赖集合的 getter，变化时自动重绘
 * @returns {{ chart: import('vue').ShallowRef, render: () => void, resize: () => void, dispose: () => void }}
 */
export function useChart(elRef, getOption, options = {}) {
  const { theme, watchSources } = options
  const chart = shallowRef(null)
  let ro = null
  let rafId = 0
  let disposed = false

  // 容器是否已有实际尺寸（隐藏的 Tab / v-show 元素为 0）
  const hasSize = (el) => !!(el && (el.clientWidth || el.clientHeight))

  /** 创建实例并写入当前 option */
  function render() {
    if (disposed) return
    const el = elRef.value
    if (!el) return
    // 容器不可见时先不初始化，等 ResizeObserver 通知（避免 ECharts 0 尺寸告警）
    if (!chart.value && !hasSize(el)) return
    if (!chart.value) {
      try {
        chart.value = echarts.init(el, theme, { renderer: 'canvas' })
      } catch (e) {
        console.warn('[useChart] 初始化失败', e)
        return
      }
    }
    let option
    try {
      option = getOption()
    } catch (e) {
      console.warn('[useChart] option 构建异常，已忽略本次渲染', e)
      return
    }
    if (!option) return
    try {
      chart.value.setOption(option, true) // notMerge：数据从有到无时不残留旧系列
    } catch (e) {
      console.warn('[useChart] setOption 异常，已忽略本次渲染', e)
    }
  }

  /** 容器尺寸变化后重绘（同一帧内多次触发只执行一次） */
  function resize() {
    if (disposed || !chart.value || rafId) return
    rafId = requestAnimationFrame(() => {
      rafId = 0
      if (!disposed && chart.value) chart.value.resize()
    })
  }

  function unbind() {
    if (ro) {
      ro.disconnect()
      ro = null
    }
  }

  function bind(el) {
    unbind()
    if (!el || typeof ResizeObserver === 'undefined') return
    ro = new ResizeObserver(() => {
      // 可见性恢复时补一次初始化，否则仅刷新尺寸
      if (chart.value) resize()
      else render()
    })
    ro.observe(el)
  }

  /** 彻底释放：定时帧、观察者、window 监听、ECharts 实例 */
  function dispose() {
    disposed = true
    if (rafId) {
      cancelAnimationFrame(rafId)
      rafId = 0
    }
    unbind()
    if (typeof window !== 'undefined') window.removeEventListener('resize', resize)
    if (chart.value) {
      chart.value.dispose()
      chart.value = null
    }
  }

  // 容器出现 / 更换 / 被 v-if 移除时同步：绑定观察者 + 首次渲染；移除时销毁实例
  watch(elRef, (el) => {
    if (!el) {
      unbind()
      if (chart.value) {
        chart.value.dispose()
        chart.value = null
      }
      return
    }
    bind(el)
    render()
  }, { immediate: true, flush: 'post' })

  // 数据变化 → 重绘（依赖引用变化即触发）
  if (watchSources) watch(watchSources, () => render(), { flush: 'post' })

  // 兜底：不支持 ResizeObserver 时跟随窗口尺寸
  if (typeof window !== 'undefined') window.addEventListener('resize', resize)

  onBeforeUnmount(dispose)

  return { chart, render, resize, dispose }
}
