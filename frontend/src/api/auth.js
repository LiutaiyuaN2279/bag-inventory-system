import request from '@/utils/request'

export function accounts() {
  return request({ url: '/auth/accounts', method: 'get' })
}

export function login(data) {
  return request({ url: '/auth/login', method: 'post', data })
}

export function userinfo() {
  return request({ url: '/auth/userinfo', method: 'get' })
}

export function logout() {
  return request({ url: '/auth/logout', method: 'post' })
}

/** 是否启用 GitHub 快捷登录（未配置凭证时登录页不显示按钮） */
export function githubStatus() {
  return request({ url: '/auth/github/status', method: 'get' })
}

/** 用 GitHub 回跳带来的一次性票据换正式 token */
export function githubExchange(code) {
  return request({ url: '/auth/github/exchange', method: 'post', data: { code } })
}
