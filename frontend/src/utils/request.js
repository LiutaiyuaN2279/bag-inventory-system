import axios from 'axios'
import { ElMessage } from 'element-plus'
import { getToken, removeToken } from './auth'
import { getServerBase } from './server'

const service = axios.create({
  baseURL: '/api/v1',
  timeout: 15000
})

// 打包成 APK 后没有同源后端：把请求改写到用户填写的服务器地址。
// 用请求拦截器（而不是适配器）—— axios 在适配器阶段才拼 baseURL，
// 在拦截器里直接把 baseURL 换成后端地址，后续拼接逻辑交给 axios 自己处理。
service.interceptors.request.use((config) => {
  const base = getServerBase()
  if (base) {
    // 把 '/api/v1' 前缀整体搬到后端地址上
    config.baseURL = base + '/api/v1'
  }
  return config
})

/**
 * 从 axios 错误中提取面向用户的中文提示：后端返回的 message 优先，
 * 其次是常见状态码/网络异常的中文文案，英文原文只作最后兜底。
 */
export function errorText(error) {
  const msg = error?.response?.data?.message
  if (typeof msg === 'string' && msg) return msg
  const status = error?.response?.status
  const raw = error?.message || ''
  if (error?.code === 'ECONNABORTED' || /timeout/i.test(raw)) return '请求超时，请重试'
  if (raw === 'Network Error') return '网络连接失败，请检查服务是否启动'
  if (/Failed to fetch|Load failed/i.test(raw)) return '无法连接服务器，请检查服务器地址与网络'
  if (status === 500) return '服务器内部错误'
  if (status === 502 || status === 504) return '服务暂时不可用'
  return raw || '网络异常'
}

// 请求拦截：自动附带 Bearer Token
service.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截：按统一结构 {code,message,data} 分流
service.interceptors.response.use(
  (response) => {
    // 二进制响应（图片/文件下载）不套 {code,message,data} 外壳，原样返回
    const respType = response.config?.responseType
    if (respType === 'blob' || respType === 'arraybuffer') {
      return response.data
    }
    const res = response.data
    if (res.code === 0) {
      return res.data
    }
    // 40100 未登录/过期 → 清理并跳登录
    if (res.code === 40100) {
      removeToken()
      ElMessage.error(res.message || '登录已过期，请重新登录')
      if (!location.hash.includes('/login')) {
        location.hash = '#/login'
      }
      return Promise.reject(new Error(res.message))
    }
    ElMessage.error(res.message || '请求失败')
    return Promise.reject(new Error(res.message))
  },
  (error) => {
    ElMessage.error(errorText(error))
    return Promise.reject(error)
  }
)

export default service
