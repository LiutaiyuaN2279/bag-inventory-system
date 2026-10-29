/** Token 存取工具（sessionStorage：关闭标签页即失效，每次打开先登录）。 */
const TOKEN_KEY = 'bag_access_token'

export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token) {
  sessionStorage.setItem(TOKEN_KEY, token)
  // 兼容旧数据：若之前存在 localStorage 中的 token，一并清除，避免残留
  localStorage.removeItem(TOKEN_KEY)
}

export function removeToken() {
  sessionStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(TOKEN_KEY)
}
