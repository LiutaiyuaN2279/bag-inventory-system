/**
 * 差旅与业务招待费报销：前端共用常量与格式化工具
 *
 * 集中维护状态/结论的文案与配色、金额与日期格式化、人民币大写转换，
 * 避免 7 个页面各自抄一份导致口径不一致。
 */

/** 报销单状态（与后端 rmb_reimbursement.status 一致） */
export const BILL_STATUS = ['待判读', '判读不合规', '待确认', '待制证', '已生成凭证', '已作废']

/** 报销单状态 → el-tag type */
export const BILL_STATUS_TYPE = {
  待判读: 'info',
  判读不合规: 'danger',
  待确认: 'warning',
  待制证: 'primary',
  已生成凭证: 'success',
  已作废: 'info'
}

/** 判读结论 → el-tag type */
export const RESULT_TYPE = {
  未判读: 'info',
  合规: 'success',
  需关注: 'warning',
  不合规: 'danger',
  不适用: 'info',
  一致: 'success',
  不一致: 'danger',
  未校验: 'info'
}

/** 分级审批状态 → el-tag type（制度第四条） */
export const APPROVAL_TYPE = {
  未审批: 'info',
  已审批: 'success',
  已驳回: 'danger'
}

/** 凭证状态（与后端 rmb_voucher.status 一致） */
export const VOUCHER_STATUS = ['未复核', '已复核', '已退回']

/** 凭证状态 → el-tag type */
export const VOUCHER_STATUS_TYPE = { 未复核: 'warning', 已复核: 'success', 已退回: 'danger' }

/** 审批层级（与制度勾稽：部门负责人/财务复核=1，部门总监=2，总经理=3；数值由后端计算，前端仅下发文案） */
export const APPROVER_LEVELS = ['部门负责人', '财务复核', '部门总监', '总经理']

/** 金额：千分位 + 固定两位小数 */
export function fmtMoney(v) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '0.00'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** 金额：固定两位小数（不带千分位，供输入框/紧凑展示） */
export function fmtAmount(v) {
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(2) : '0.00'
}

/** 单号等编号：空值统一显示 — */
export function orDash(v) {
  return v === null || v === undefined || v === '' ? '—' : v
}

/** 日期时间：只保留到分钟，避免表格里堆毫秒 */
export function fmtTime(v) {
  if (!v) return '—'
  const s = String(v).replace('T', ' ')
  return s.length > 16 ? s.slice(0, 16) : s
}

/** 日期差（天）：b - a，任一日期非法返回 null */
export function dayDiff(a, b) {
  if (!a || !b) return null
  const da = new Date(String(a).replace(/-/g, '/'))
  const db = new Date(String(b).replace(/-/g, '/'))
  if (Number.isNaN(da.getTime()) || Number.isNaN(db.getTime())) return null
  return Math.round((db.getTime() - da.getTime()) / 86400000)
}

/**
 * 城市名归一（填单页与详情页共用，避免两处口径不一致）。
 * 先去掉「市/地区/自治州/盟」等行政区后缀；传入城市等级表名称时，
 * 再按「站名/机场名包含城市名」做归一（如「上海虹桥」→「上海」）。
 * 无法匹配时返回去后缀后的名称。
 */
export function normalizeCity(raw, cities = []) {
  const s = String(raw || '').trim()
  if (!s) return ''
  const list = (cities || []).map((c) => String(c || '').trim()).filter(Boolean)
  if (list.includes(s)) return s
  const bare = s.replace(/(市|地区|自治州|盟)$/, '')
  if (bare && list.includes(bare)) return bare
  // 「其他城市」是兜底项，不参与包含匹配；按名称长度降序，避免短城市名误命中
  const candidates = list.filter((name) => name !== '其他城市')
  const hit = [...candidates].sort((a, b) => b.length - a.length)
    .find((name) => s.includes(name) || (bare && bare.includes(name)))
  return hit || bare || s
}

/** 城市一致性：归一后相等或互相包含即视为同一城市；任一为空返回 null（无法判断） */
export function sameCity(a, b, cities = []) {
  const x = normalizeCity(a, cities)
  const y = normalizeCity(b, cities)
  if (!x || !y) return null
  return x === y || x.includes(y) || y.includes(x)
}

/**
 * 小写金额转人民币大写（凭证页「金额大写」与打印样式使用）。
 * 以「分」为整数单位计算，规避浮点误差；支持零、整、角分、万亿级。
 */
export function moneyToChinese(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return ''
  const DIGITS = ['零', '壹', '贰', '叁', '肆', '伍', '陆', '柒', '捌', '玖']
  const UNITS = ['', '拾', '佰', '仟']
  const SECTIONS = ['', '万', '亿', '万亿']
  const neg = num < 0
  const cents = Math.round(Math.abs(num) * 100)
  if (cents === 0) return '零元整'
  const jiao = Math.floor(cents / 10) % 10
  const fen = cents % 10
  const intPart = Math.floor(cents / 100)

  // ---- 整数部分：按 4 位一组从高位往低位拼 ----
  let intText = ''
  if (intPart > 0) {
    const groups = []
    let n = intPart
    while (n > 0) {
      groups.push(n % 10000)
      n = Math.floor(n / 10000)
    }
    for (let gi = groups.length - 1; gi >= 0; gi--) {
      const g = groups[gi]
      if (g === 0) {
        // 整组为零：仅当已输出内容且高位仍有非零时才补一个「零」
        if (intText && groups.slice(0, gi).some((x) => x > 0)) intText += '零'
        continue
      }
      const digits = [Math.floor(g / 1000), Math.floor(g / 100) % 10, Math.floor(g / 10) % 10, g % 10]
      let gText = ''
      let zeroPending = false
      for (let k = 0; k < 4; k += 1) {
        const d = digits[k]
        if (d === 0) {
          if (gText) zeroPending = true
        } else {
          if (zeroPending) {
            gText += '零'
            zeroPending = false
          }
          gText += DIGITS[d] + UNITS[3 - k]
        }
      }
      // 非最高组且不足 4 位时，组前补「零」（如 1 万零 5 元）
      if (intText && g < 1000) intText += '零'
      intText += gText + SECTIONS[gi]
    }
  }

  // ---- 小数部分 ----
  let fracText = ''
  if (jiao === 0 && fen === 0) {
    fracText = '整'
  } else {
    if (jiao > 0) fracText += DIGITS[jiao] + '角'
    else if (intPart > 0) fracText += '零'
    if (fen > 0) fracText += DIGITS[fen] + '分'
  }

  return (neg ? '负' : '') + (intText ? intText + '圆' : '') + fracText
}

