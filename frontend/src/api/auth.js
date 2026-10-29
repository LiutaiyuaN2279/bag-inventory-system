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
