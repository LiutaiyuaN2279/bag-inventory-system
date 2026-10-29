<template>
  <el-container class="layout">
    <el-aside :width="isCollapse ? '64px' : '210px'" class="aside">
      <div class="logo">
        <el-icon size="22"><Box /></el-icon>
        <span v-show="!isCollapse" class="logo-text">箱包采购库存系统</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        :collapse="isCollapse"
        :collapse-transition="false"
        background-color="transparent"
        text-color="#c9d1d9"
        active-text-color="#0FDC78"
        router
        unique-opened
      >
        <template v-for="item in menuList" :key="item.path">
          <!-- 含子菜单的分组 -->
          <el-sub-menu v-if="item.children && item.children.length" :index="resolvePath(item)">
            <template #title>
              <el-icon><component :is="item.meta.icon" /></el-icon>
              <span>{{ item.meta.title }}</span>
            </template>
            <el-menu-item
              v-for="child in item.children"
              :key="child.path"
              :index="resolvePath(item, child)"
            >
              <el-icon><component :is="child.meta.icon" /></el-icon>
              <span>{{ child.meta.title }}</span>
            </el-menu-item>
          </el-sub-menu>
          <!-- 单级菜单 -->
          <el-menu-item v-else :index="resolvePath(item)">
            <el-icon><component :is="item.meta.icon" /></el-icon>
            <span>{{ item.meta.title }}</span>
          </el-menu-item>
        </template>
      </el-menu>
      <!-- 侧栏底部：填掉菜单下方的空档，避免大片深色留白 -->
      <div class="aside-foot">
        <el-icon><Box /></el-icon>
        <span v-show="!isCollapse">演示系统 · v1.0</span>
      </div>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="header-left">
          <el-icon class="collapse-btn" @click="isCollapse = !isCollapse">
            <Fold v-if="!isCollapse" />
            <Expand v-else />
          </el-icon>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: '/' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item>{{ currentTitle }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="header-right">
          <el-dropdown trigger="click" @command="handleSwitch">
            <el-button size="small" round class="switch-btn">
              <el-icon><Switch /></el-icon>
              <span>切换演示身份</span>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="a in accounts"
                  :key="a.username"
                  :command="a.username"
                  :disabled="a.username === userStore.userInfo?.username"
                >
                  <span class="sw-name">{{ a.real_name || a.username }}</span>
                  <span v-if="a.department || a.position" class="sw-meta">
                    {{ [a.department, a.position].filter(Boolean).join(' · ') }}
                  </span>
                  <span class="sw-user">{{ a.username }}</span>
                </el-dropdown-item>
                <el-dropdown-item v-if="!accounts.length" disabled>暂无可切换账号</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-dropdown @command="handleCommand">
            <span class="user-info">
              <el-avatar :size="30" class="avatar">{{ avatarText }}</el-avatar>
              <span class="username">{{ userStore.userInfo?.real_name || '用户' }}</span>
              <span v-if="showRoleTag" class="role-tag">{{ primaryRole }}</span>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { routes } from '@/router'
import { useUserStore } from '@/store/user'
import { accounts as accountsApi } from '@/api/auth'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const isCollapse = ref(false)

/**
 * 窄屏（手机 / APK）适配：桌面版侧栏常驻会挤掉主内容区，
 * 这里在窄屏下自动折叠侧栏，并用 drawer 模式让菜单浮层覆盖（不占宽度）。
 */
const isNarrow = ref(false)
function syncViewport() {
  const narrow = window.innerWidth < 768
  // 首次进入窄屏时自动折叠；从窄屏切回宽屏时恢复展开
  if (narrow !== isNarrow.value) {
    isNarrow.value = narrow
    isCollapse.value = narrow
  }
}
onMounted(() => {
  syncViewport()
  window.addEventListener('resize', syncViewport)
})
onBeforeUnmount(() => window.removeEventListener('resize', syncViewport))
const activeMenu = computed(() => route.path)
const currentTitle = computed(() => route.meta?.title || '')

// 演示用快捷切换：登录页已公开说明所有演示账号统一使用该口令
const DEMO_PASSWORD = 'admin123'
const ROLE_NAMES = {
  admin: '系统管理员',
  manager: '运营主管',
  buyer: '采购员',
  keeper: '仓管员',
  qc: '质检员'
}

const accounts = ref([])
const avatarText = computed(() => (userStore.userInfo?.real_name || '用').charAt(0))
const primaryRole = computed(() => {
  const code = userStore.roles && userStore.roles[0]
  if (!code) return ''
  return ROLE_NAMES[code] || code
})
// 角色标签与姓名重复时（如 admin 的 real_name 就叫「系统管理员」）不再重复显示
const showRoleTag = computed(() => {
  const name = userStore.userInfo?.real_name || ''
  return !!primaryRole.value && primaryRole.value !== name
})

async function loadAccounts() {
  try {
    accounts.value = (await accountsApi()) || []
  } catch {
    accounts.value = []
  }
}

// 一键切换演示身份：重新登录并刷新权限，侧边栏菜单会随权限自动重算
async function handleSwitch(username) {
  if (!username || username === userStore.userInfo?.username) return
  try {
    await userStore.login({ username, password: DEMO_PASSWORD })
    await userStore.getUserInfo()
    ElMessage.success(`已切换为 ${userStore.userInfo?.real_name || username}`)
    router.replace('/dashboard')
  } catch {
    // 失败提示已由 request 拦截器统一给出
  }
}

onMounted(loadAccounts)

// 从根布局路由中提取可见菜单（按权限过滤）
const layoutChildren = computed(() => {
  const root = routes.find((r) => r.path === '/')
  return root ? root.children || [] : []
})

const menuList = computed(() => {
  return layoutChildren.value
    .map((item) => {
      if (item.children && item.children.length) {
        const visible = item.children.filter((c) => hasPerm(c))
        return visible.length ? { ...item, children: visible } : null
      }
      return hasPerm(item) ? item : null
    })
    .filter(Boolean)
})

function hasPerm(item) {
  const perm = item.meta && item.meta.permission
  if (!perm) return true
  return userStore.hasPermission(perm)
}

function resolvePath(parent, child) {
  // basePath 始终为父级完整路径，避免重复拼接
  const base = parent.path.startsWith('/') ? parent.path : '/' + parent.path
  if (!child) return base
  const sub = child.path.startsWith('/') ? child.path : '/' + child.path
  return base + sub
}

async function handleCommand(cmd) {
  if (cmd === 'logout') {
    try { await ElMessageBox.confirm('确定退出登录吗？', '提示', { type: 'warning' }) } catch { return }
    await userStore.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.layout { height: 100vh; }
/* 侧栏统一为一块深绿底，菜单透明铺在其上，底部用 foot 收口 */
.aside {
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, #0a3b2c 0%, #07271d 55%, #061f17 100%);
  transition: width .25s ease;
  overflow: hidden;
  box-shadow: 2px 0 12px rgba(7, 37, 27, .18);
}
.logo {
  height: 56px; flex: 0 0 56px;
  display: flex; align-items: center; justify-content: center; gap: 10px;
  color: #fff; font-weight: 700; letter-spacing: .5px;
  background: rgba(255, 255, 255, .04);
  border-bottom: 1px solid rgba(255, 255, 255, .08);
}
.logo .el-icon { color: #34d9a0; filter: drop-shadow(0 0 6px rgba(52, 217, 160, .5)); }
.logo-text { font-size: 15px; white-space: nowrap; }
.aside-foot {
  flex: 0 0 auto;
  display: flex; align-items: center; gap: 6px;
  padding: 9px 16px;
  font-size: 12px; color: rgba(255, 255, 255, .42);
  border-top: 1px solid rgba(255, 255, 255, .07);
  background: rgba(0, 0, 0, .12);
}
.aside-foot .el-icon { font-size: 14px; }
:deep(.el-menu) {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  border-right: none;
}
/* 菜单项收紧，一屏能放更多入口 */
:deep(.el-menu-item),
:deep(.el-sub-menu__title) { height: 46px; line-height: 46px; }
:deep(.el-menu--collapse .el-menu-item),
:deep(.el-menu--collapse .el-sub-menu__title) { height: 46px; }
:deep(.el-menu-item.is-active) {
  background: rgba(52, 217, 160, .16) !important;
  border-left: 3px solid #34d9a0;
  font-weight: 600;
}
:deep(.el-menu-item:hover), :deep(.el-sub-menu__title:hover) {
  background: rgba(255, 255, 255, .07) !important;
}
:deep(.el-menu-item),
:deep(.el-sub-menu__title) { font-size: 13.5px; }
:deep(.el-menu-item .el-icon),
:deep(.el-sub-menu__title .el-icon) { font-size: 16px; width: 20px; }

.header {
  background: #fff; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between; padding: 0 16px;
  height: 56px;
  box-shadow: 0 1px 4px rgba(16, 24, 40, .04);
  z-index: 5;
}
.header-left { display: flex; align-items: center; gap: 14px; }
.header-right { display: flex; align-items: center; gap: 10px; }
.switch-btn {
  border-color: rgba(16, 185, 129, .35); color: #0f9d76;
  background: rgba(16, 185, 129, .06); font-weight: 600;
}
.switch-btn:hover { border-color: var(--brand); color: var(--brand); background: rgba(16, 185, 129, .12); }
.role-tag {
  font-size: 12px; color: #0f9d76; background: rgba(16, 185, 129, .1);
  border: 1px solid rgba(16, 185, 129, .25); border-radius: 10px; padding: 1px 8px;
}
.collapse-btn { font-size: 20px; cursor: pointer; color: #4b5563; transition: color .2s; }
.collapse-btn:hover { color: var(--brand); }
.user-info { display: flex; align-items: center; gap: 8px; cursor: pointer; padding: 4px 10px; border-radius: 20px; transition: background .2s; }
.user-info:hover { background: #f3f5f9; }
.avatar { background: linear-gradient(135deg, #10b981, #27D2BF); color: #fff; font-weight: 700; box-shadow: 0 2px 6px rgba(16, 185, 129, .35); }
.username { font-size: 14px; color: #374151; }
.main { background: var(--bg); padding: 14px 16px 16px; }

/* 「切换演示身份」下拉项：姓名 + 部门·职位 + 用户名 */
.sw-name { font-size: 13px; color: #1f2937; font-weight: 500; }
.sw-meta { font-size: 11.5px; color: #0f9d76; margin-left: 8px; }
.sw-user { font-size: 11px; color: #9ca3af; margin-left: 8px; font-variant-numeric: tabular-nums; }

/* ---------- 窄屏（手机 / APK）适配 ---------- */
@media (max-width: 767px) {
  /* 顶栏压缩：面包屑很占宽度，直接隐藏，保留折叠按钮与账号入口 */
  .header { padding: 0 10px; height: 52px; }
  .header-left { gap: 8px; min-width: 0; }
  :deep(.el-breadcrumb) { display: none; }
  .header-right { gap: 6px; flex: 0 0 auto; }
  /* 「切换演示身份」文字收起，只留图标，避免把用户信息挤到换行 */
  .switch-btn span { display: none; }
  .switch-btn { padding: 7px 9px; }
  .username, .role-tag { display: none; }
  .user-info { padding: 4px 6px; }
  .main { padding: 10px 10px 14px; }
  /* 窄屏下菜单项字号略大，便于触控 */
  :deep(.el-menu-item), :deep(.el-sub-menu__title) { font-size: 14px; }
  .aside-foot { padding: 8px 10px; }
}
</style>
