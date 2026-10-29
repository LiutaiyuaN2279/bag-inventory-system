/**
 * 「服务器地址」配置（仅 APK/移动端使用，浏览器里始终为空 = 用同源相对路径）。
 *
 * 作用：把 `/api/v1` 这种同源请求改写到用户填写的后端地址上
 * （例如 http://192.168.1.10:8000），这样打包成 APK 后手机能连到电脑上的 FastAPI。
 *
 * 之所以不引入 axios baseURL，是因为 download.js 等多处直接写死了
 * `/api/v1...` 的绝对路径，只有统一在请求适配器层改写才能覆盖全部接口。
 */
const SERVER_KEY = 'bag_server_base'

/** 规范化用户输入：补协议、去末尾斜杠，非法值返回空串 */
export function normalizeServerBase(input) {
  let v = String(input || '').trim()
  if (!v) return ''
  // 只填 IP/域名时默认补 http://（局域网后端通常是明文 http）
  if (!/^https?:\/\//i.test(v)) v = 'http://' + v
  v = v.replace(/\/+$/, '')
  try {
    const u = new URL(v)
    if (!u.hostname) return ''
  } catch {
    return ''
  }
  return v
}

export function getServerBase() {
  return normalizeServerBase(localStorage.getItem(SERVER_KEY))
}

export function setServerBase(input) {
  const v = normalizeServerBase(input)
  if (v) localStorage.setItem(SERVER_KEY, v)
  else localStorage.removeItem(SERVER_KEY)
  return v
}

export function hasServerBase() {
  return !!getServerBase()
}

/**
 * 把同源相对路径改写到已配置的后端地址。
 * - 未配置后端：原样返回（浏览器同名部署行为不变）
 * - 已是 http(s) 绝对地址：原样返回
 */
export function resolveUrl(url) {
  const u = String(url || '')
  if (!u) return u
  if (/^(https?:)?\/\//i.test(u) || u.startsWith('data:') || u.startsWith('blob:')) return u
  const base = getServerBase()
  if (!base) return u
  return base + (u.startsWith('/') ? u : '/' + u)
}
