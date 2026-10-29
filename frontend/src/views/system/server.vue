<template>
  <div class="srv-wrap">
    <div class="srv-card">
      <div class="srv-brand">
        <div class="srv-icon"><el-icon size="24"><Connection /></el-icon></div>
        <div>
          <h1>连接服务器</h1>
          <p>请填写运行本系统的电脑地址，手机需与电脑处于同一网络</p>
        </div>
      </div>

      <el-form label-position="top" @submit.prevent>
        <el-form-item label="服务器地址">
          <el-input
            v-model="input"
            size="large"
            placeholder="例如 192.168.1.10:8000"
            clearable
            @keyup.enter="submit"
          />
        </el-form-item>
      </el-form>

      <div class="srv-tip">
        支持只填 IP 和端口，会自动补上 http://；也支持 https:// 域名。
      </div>

      <div class="srv-actions">
        <el-button type="primary" size="large" :loading="testing" style="width: 100%" @click="submit">
          {{ testing ? '正在连接…' : '保存并测试连接' }}
        </el-button>
      </div>

      <div v-if="saved" class="srv-ok">
        <el-icon><CircleCheckFilled /></el-icon>
        <span>连接成功：{{ savedName }}</span>
      </div>
      <div v-if="error" class="srv-err">{{ error }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getServerBase, normalizeServerBase, setServerBase } from '@/utils/server'

const router = useRouter()
const input = ref(getServerBase())
const testing = ref(false)
const error = ref('')
const savedName = ref('')

/**
 * 保存并探活：直接请求后端 /api/health（不经过统一拦截器，
 * 避免连不上时先弹一堆错误提示）。
 */
async function submit() {
  error.value = ''
  savedName.value = ''
  const base = normalizeServerBase(input.value)
  if (!base) {
    error.value = '地址格式不正确，示例：192.168.1.10:8000'
    return
  }
  testing.value = true
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 8000)
  try {
    const resp = await fetch(base + '/api/health', { signal: controller.signal })
    const data = await resp.json()
    if (!resp.ok || (data && data.code !== 0)) throw new Error('返回异常')
    setServerBase(base)
    savedName.value = (data.data && data.data.app) || base
    ElMessage.success('服务器连接成功')
    setTimeout(() => router.replace('/login'), 600)
  } catch (e) {
    error.value = '连接失败。请确认：电脑已启动后端服务（uvicorn 监听 0.0.0.0:8000）、'
      + '手机与电脑在同一 WiFi、电脑防火墙已放行该端口。'
  } finally {
    clearTimeout(timer)
    testing.value = false
  }
}
</script>

<style scoped>
.srv-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: linear-gradient(135deg, #eef4ff 0%, #f7f9fc 55%, #eefaf3 100%);
}
.srv-card {
  width: 100%;
  max-width: 440px;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 12px 40px rgba(31, 56, 105, 0.12);
  padding: 28px 24px;
}
.srv-brand { display: flex; gap: 12px; align-items: flex-start; margin-bottom: 20px; }
.srv-icon {
  width: 44px; height: 44px; flex: none; border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  color: #fff; background: linear-gradient(135deg, #3b82f6, #2563eb);
}
.srv-brand h1 { font-size: 19px; margin: 0 0 4px; color: #1f2937; }
.srv-brand p { margin: 0; font-size: 12.5px; line-height: 1.5; color: #6b7280; }
.srv-tip { font-size: 12px; color: #909399; line-height: 1.6; margin: -4px 0 18px; }
.srv-actions { margin-top: 4px; }
.srv-ok, .srv-err {
  margin-top: 14px; font-size: 13px; line-height: 1.6;
  display: flex; gap: 6px; align-items: flex-start;
}
.srv-ok { color: #16a34a; }
.srv-err { color: #dc2626; }
</style>
