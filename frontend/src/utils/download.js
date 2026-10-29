import axios from 'axios'
import { ElMessage } from 'element-plus'
import { getToken } from './auth'
import { errorText } from './request'
import { resolveUrl } from './server'

/** Blob → 不含 data: 前缀的 base64（供原生桥写文件） */
function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',')[1] || '')
    reader.onerror = () => reject(reader.error || new Error('读取文件失败'))
    reader.readAsDataURL(blob)
  })
}

/** 下载文件流（绕过统一 JSON 拦截器）。 */
export async function download(url, filename) {
  try {
    const resp = await axios.get(resolveUrl('/api/v1' + url), {
      responseType: 'blob',
      headers: { Authorization: `Bearer ${getToken()}` }
    })

    // 后端出错时返回的是 JSON 错误体（HTTP 200 + code!=0），若直接当文件保存
    // 会下载到一个内容是报错文字的 .xlsx 并提示"导出成功" —— 这里识别出来并提示真实原因
    const contentType = String(resp.headers?.['content-type'] || '')
    if (contentType.includes('application/json')) {
      let msg = '导出失败'
      try {
        const text = await resp.data.text()
        msg = JSON.parse(text)?.message || msg
      } catch (e) {
        // 解析失败就用兜底文案，不向外抛出
      }
      ElMessage.error(msg)
      return
    }

    const blob = new Blob([resp.data], { type: contentType || 'application/octet-stream' })
    // 安卓 WebView 不支持 a[download] 触发保存：转 base64 交给原生写进「下载」目录
    if (window.AndroidBridge && typeof window.AndroidBridge.saveBase64File === 'function') {
      const base64 = await blobToBase64(blob)
      const saved = window.AndroidBridge.saveBase64File(filename, base64, contentType || 'application/octet-stream')
      if (saved) ElMessage.success('已保存到手机下载目录：' + filename)
      else ElMessage.error('保存失败，请检查存储权限')
      return
    }
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    // 立即 revoke 在部分浏览器会中断下载，放到下一个事件循环
    setTimeout(() => URL.revokeObjectURL(link.href), 0)
    ElMessage.success('导出成功')
  } catch (e) {
    // 导出失败给出提示，避免未捕获的 Promise 拒绝
    ElMessage.error(errorText(e))
  }
}
