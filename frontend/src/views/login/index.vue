<template>
  <div class="login-wrap">
    <div class="blob blob-a" />
    <div class="blob blob-b" />

    <div class="login-box">
      <!-- 左侧：产品介绍（填满宽屏，避免大片空白） -->
      <aside class="intro">
        <div class="intro-head">
          <h2>让采购、库存与算料<br />跑在同一条流水线上</h2>
          <p>从请购到入库、从 BOM 算料到库存预警，一个系统闭环</p>
        </div>

        <ul class="feat">
          <li v-for="f in FEATURES" :key="f.title">
            <span class="feat-icon"><el-icon :size="17"><component :is="f.icon" /></el-icon></span>
            <div class="feat-text">
              <b>{{ f.title }}</b>
              <span>{{ f.desc }}</span>
            </div>
          </li>
        </ul>

        <div class="intro-foot">
          <span class="pulse" />
          <span>演示系统 · 采购库存 / 费用报销 多岗位身份随时切换</span>
        </div>
      </aside>

      <!-- 右侧：登录表单 -->
      <section class="form-pane">
        <div class="brand">
          <div class="brand-icon"><el-icon size="26"><Box /></el-icon></div>
          <div class="brand-text">
            <h1>箱包采购与库存管理系统</h1>
            <p>面向箱包制造企业的轻量化供应链平台</p>
          </div>
        </div>

        <div v-if="accounts.length" class="acct-block">
          <div class="block-label">
            演示账号（点击自动填充，密码统一 admin123）
            <span class="block-count">{{ accounts.length }} 个</span>
          </div>
          <!--
            账号卡片：按「部门 → 职位」排序后平铺（后端已排好序）。
            卡片压成两行——第一行「姓名 + 账号」，第二行「部门 · 职位」，
            比按部门分组（每组都要一个标题行）矮得多，12 个账号一屏可见、无需滚动。
          -->
          <div class="acct-grid">
            <button
              v-for="a in accounts"
              :key="a.username"
              type="button"
              class="acct"
              :class="{ on: picked === a.username }"
              :title="`${a.real_name}${a.department ? ' · ' + a.department : ''}${a.position ? ' · ' + a.position : ''}（${a.username}）`"
              @click="onPickAccount(a.username)"
            >
              <span class="acct-top">
                <span class="acct-name">{{ a.real_name }}</span>
                <span class="acct-user">{{ a.username }}</span>
              </span>
              <span class="acct-meta">
                <template v-if="a.department">{{ a.department }} · </template>{{ a.position }}
              </span>
            </button>
          </div>
        </div>

        <el-form ref="formRef" :model="form" :rules="rules" size="large" @keyup.enter="onLogin">
          <el-form-item prop="username">
            <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" />
          </el-form-item>
          <el-form-item prop="password">
            <el-input v-model="form.password" type="password" placeholder="密码" :prefix-icon="Lock" show-password />
          </el-form-item>
          <el-button type="primary" class="login-btn" :loading="loading" @click="onLogin">登 录</el-button>
        </el-form>

        <!-- GitHub 快捷登录：未配置 GITHUB_CLIENT_ID/SECRET 时整块不渲染 -->
        <template v-if="ghEnabled">
          <div class="or-line"><span>或</span></div>
          <el-button class="gh-btn" :loading="ghLoading" @click="onGithubLogin">
            <svg class="gh-icon" viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
              <path fill="currentColor" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
            </svg>
            <span>使用 GitHub 登录</span>
          </el-button>
        </template>

        <p class="tip">{{ ghEnabled
          ? 'GitHub 登录后即「系统管理员」，可用顶栏「切换演示身份」体验其他角色视野'
          : '登录后可随时通过顶栏「切换演示身份」体验不同角色的权限差异' }}</p>

        <!-- APK 里后端地址由用户填写，提供入口随时更换 -->
        <p v-if="isApp" class="srv-link">
          当前服务器：<b>{{ serverBase || '未配置' }}</b>
          <el-button link type="primary" size="small" @click="goServer">修改</el-button>
        </p>
      </section>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Box, User, Lock, ShoppingCart, Grid, TrendCharts } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/store/user'
import { accounts as fetchAccounts, githubExchange, githubStatus } from '@/api/auth'
import { getServerBase, resolveUrl } from '@/utils/server'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const formRef = ref()
const loading = ref(false)

// APK 原生容器里才显示「服务器地址」入口，浏览器部署保持原样
const isApp = typeof window !== 'undefined' && !!window.AndroidBridge
const serverBase = ref(getServerBase())
function goServer() {
  router.push('/server')
}

const FEATURES = [
  { icon: ShoppingCart, title: '采购全流程', desc: '请购 · 订单 · 到货 · 退货 闭环留痕' },
  { icon: Box, title: '库存与调拨', desc: '实时库存、盘点、多仓调拨与呆滞预警' },
  { icon: Grid, title: 'BOM 算料', desc: '按成品一键展开物料需求与损耗' },
  { icon: TrendCharts, title: '报表看板', desc: '采购/库存多维统计，按角色呈现' }
]

const form = reactive({ username: 'admin', password: 'admin123' })
const picked = ref('')
const accounts = ref([])

async function loadAccounts() {
  try { accounts.value = await fetchAccounts() } catch (e) { accounts.value = [] }
}
function onPickAccount(username) {
  if (!username) return
  picked.value = username
  form.username = username
  form.password = 'admin123' // 演示账号统一密码，选中后可直接登录
}

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

async function onLogin() {
  if (!(await formRef.value.validate().catch(() => false))) return
  loading.value = true
  try {
    await userStore.login(form)
    ElMessage.success('登录成功')
    router.push('/dashboard')
  } finally {
    loading.value = false
  }
}

// ---------------- GitHub 快捷登录 ----------------
const ghEnabled = ref(false)
const ghLoading = ref(false)

async function loadGithubStatus() {
  try {
    ghEnabled.value = !!(await githubStatus())?.enabled
  } catch {
    ghEnabled.value = false // 后端没配或不可用时不显示按钮，不影响口令登录
  }
}

/**
 * 去 GitHub 授权。这是整页跳转（不是 axios 请求），所以要用 resolveUrl 拼绝对地址，
 * 这样打包成 APK、后端地址填在「服务器」页时也能正确跳转。
 */
function onGithubLogin() {
  ghLoading.value = true
  window.location.href = resolveUrl('/api/v1/auth/github/login')
}

/**
 * 处理 GitHub 回跳：成功带 gh_code（一次性票据），失败带 gh_error。
 * 票据换到 token 后与口令登录走同一套后续（拉用户信息 → 进首页）。
 */
async function handleGithubCallback() {
  const code = route.query.gh_code
  const err = route.query.gh_error
  if (err) {
    ElMessage.error(String(err))
    cleanCallbackQuery()
    return
  }
  if (!code) return
  ghLoading.value = true
  try {
    const data = await githubExchange(String(code))
    await userStore.loginWithToken(data.access_token)
    ElMessage.success(`欢迎，${data.real_name || data.username}`)
    router.replace('/dashboard')
  } catch {
    // 失败提示由 request 拦截器统一给出
  } finally {
    ghLoading.value = false
    cleanCallbackQuery()
  }
}

/** 清掉地址栏里的 gh_code / gh_error，刷新页面时不会重复兑换（票据本身也只用一次）。 */
function cleanCallbackQuery() {
  const query = { ...route.query }
  delete query.gh_code
  delete query.gh_error
  router.replace({ path: route.path, query })
}

onMounted(() => {
  loadAccounts()
  loadGithubStatus()
  handleGithubCallback()
})
</script>

<style scoped>
.login-wrap {
  position: relative; min-height: 100vh; padding: 24px;
  display: flex; align-items: center; justify-content: center;
  overflow: hidden;
  background: linear-gradient(135deg, #05392b 0%, #0d6b52 52%, #27d2bf 100%);
}
.blob { position: absolute; border-radius: 50%; filter: blur(64px); opacity: .45; }
.blob-a { width: 460px; height: 460px; background: #34d9a0; top: -140px; left: -120px; animation: float 9s ease-in-out infinite; }
.blob-b { width: 400px; height: 400px; background: #6ee7d6; bottom: -140px; right: -100px; animation: float 11s ease-in-out infinite reverse; }
@keyframes float { 0%, 100% { transform: translateY(0) scale(1); } 50% { transform: translateY(28px) scale(1.07); } }

.login-box {
  position: relative; z-index: 2; width: min(1000px, 100%);
  display: grid; grid-template-columns: 1.02fr .98fr;
  background: rgba(255, 255, 255, .97); border-radius: 18px; overflow: hidden;
  box-shadow: 0 26px 64px rgba(4, 47, 35, .38);
  backdrop-filter: blur(10px);
}
.login-wrap { overflow-x: hidden; }

/* 左：产品介绍 */
.intro {
  padding: 24px 28px 20px; color: #e6fff6;
  background: linear-gradient(158deg, #062e22 0%, #0a4433 58%, #0e5a42 100%);
  display: flex; flex-direction: column; gap: 14px;
}
.intro-head h2 { margin: 0; font-size: 20px; line-height: 1.4; letter-spacing: .3px; color: #fff; }
.intro-head p { margin: 8px 0 0; font-size: 12px; line-height: 1.6; color: rgba(214, 255, 240, .7); }
.feat { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.feat li {
  display: flex; align-items: flex-start; gap: 8px;
  padding: 7px 9px; border-radius: 9px;
  background: rgba(255, 255, 255, .055); border: 1px solid rgba(255, 255, 255, .08);
}
.feat-icon {
  flex: 0 0 24px; width: 24px; height: 24px; border-radius: 7px;
  display: flex; align-items: center; justify-content: center;
  background: rgba(52, 217, 160, .16); color: #4ee3ac;
}
.feat-text { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.feat-text b { font-size: 12px; font-weight: 600; color: #fff; }
.feat-text span { font-size: 10.5px; color: rgba(203, 250, 232, .62); line-height: 1.4; }
.intro-foot {
  margin-top: auto; display: flex; align-items: center; gap: 7px;
  font-size: 11.5px; color: rgba(203, 250, 232, .6);
}
.pulse { width: 7px; height: 7px; border-radius: 50%; background: #34d9a0; box-shadow: 0 0 0 0 rgba(52, 217, 160, .6); animation: pulse 2s infinite; }
@keyframes pulse { 70% { box-shadow: 0 0 0 8px rgba(52, 217, 160, 0); } 100% { box-shadow: 0 0 0 0 rgba(52, 217, 160, 0); } }

/* 右：表单 */
.form-pane { padding: 24px 30px 20px; display: flex; flex-direction: column; justify-content: center; }
.brand { display: flex; align-items: center; gap: 11px; }
.brand-icon {
  flex: 0 0 44px; width: 44px; height: 44px; border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #10b981, #27d2bf); color: #fff;
  box-shadow: 0 6px 16px rgba(16, 185, 129, .38);
}
.brand-text h1 { margin: 0; font-size: 16px; color: #111827; letter-spacing: .2px; }
.brand-text p { margin: 3px 0 0; font-size: 11.5px; color: #8a8f99; }

.acct-block { margin: 12px 0 2px; }
.block-label {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 11.5px; color: #8a8f99; margin-bottom: 7px;
}
.block-count { font-size: 10.5px; color: #b0b3bb; }

/* ---------- 账号卡片（紧凑两行，按部门排序平铺） ---------- */
.acct-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(146px, 1fr)); gap: 6px;
}
.acct {
  display: flex; flex-direction: column; gap: 0; text-align: left; cursor: pointer;
  padding: 5px 9px; border-radius: 8px; font-family: inherit;
  border: 1px solid var(--border, #e8ebf1); background: #fbfdff;
  transition: all .16s ease; min-width: 0;
}
.acct:hover { border-color: #34d9a0; background: #f1fbf6; transform: translateY(-1px); }
.acct.on { border-color: #10b981; background: #ecfdf5; box-shadow: 0 0 0 2px rgba(16, 185, 129, .12); }
/* 第一行：姓名（粗体）+ 账号（浅灰小字，右对齐） */
.acct-top { display: flex; align-items: baseline; justify-content: space-between; gap: 6px; min-width: 0; }
.acct-name { font-size: 12.5px; font-weight: 600; color: #1f2937; line-height: 1.35; white-space: nowrap; }
.acct-user { font-size: 10px; color: #b0b3bb; font-variant-numeric: tabular-nums; white-space: nowrap; }
/* 第二行：部门 · 职位（主色强调，单行省略，悬停看完整信息） */
.acct-meta {
  font-size: 10.5px; color: #0f9d76; font-weight: 500;
  line-height: 1.3; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.acct-user { font-size: 11px; color: #9ca3af; font-variant-numeric: tabular-nums; }

.form-pane :deep(.el-form) { margin-top: 12px; }
.form-pane :deep(.el-form-item) { margin-bottom: 12px; }
.login-btn { width: 100%; height: 39px; font-size: 14.5px; letter-spacing: 4px; margin-top: 0; }
/* GitHub 快捷登录：分隔线 + 白底描边按钮（右侧表单是浅色底，按钮跟随浅色风格） */
.or-line { display: flex; align-items: center; gap: 10px; margin: 12px 0 10px; color: #b0b3bb; font-size: 11.5px; }
.or-line::before, .or-line::after { content: ''; flex: 1; height: 1px; background: #e8ebf1; }
.gh-btn { width: 100%; height: 39px; font-size: 13.5px; display: flex; align-items: center; justify-content: center; gap: 7px; }
.gh-icon { flex: 0 0 auto; }
.tip { text-align: center; color: #b0b3bb; font-size: 11.5px; margin: 10px 0 0; }
.srv-link { text-align: center; color: #9ca3af; font-size: 12px; margin: 8px 0 0; }
.srv-link b { color: #4b5563; font-weight: 600; }

@media (max-width: 880px) {
  .login-wrap { padding: 16px; align-items: flex-start; overflow-y: auto; }
  .login-box { grid-template-columns: 1fr; width: 100%; }
  .intro { display: none; }
  .form-pane { padding: 24px 18px 20px; min-width: 0; }
  .brand-text h1 { font-size: 15.5px; }
  .brand-text p { font-size: 11.5px; }
  .acct-grid { gap: 6px; }
  .acct { padding: 7px 9px; }
}
</style>
