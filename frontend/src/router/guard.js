/** 全局路由守卫：登录拦截 + 权限校验。三段式：token → store 用户态 → 路由权限。 */
import router, { routes } from './index'
import { useUserStore } from '@/store/user'
import { getToken } from '@/utils/auth'
import { hasServerBase } from '@/utils/server'

const whiteList = ['/login', '/server']

/** 是否运行在 APK 原生容器里（由 MainActivity 注入 AndroidBridge） */
function isNativeApp() {
  return typeof window !== 'undefined' && !!window.AndroidBridge
}

/**
 * 找当前用户有权访问的第一个菜单路径。
 *
 * 用途：用户没有首页（dashboard:view）权限时的兜底跳转。
 * 早期实现是「无权限就 next('/dashboard')」，当用户连首页权限都没有时会
 * 反复重定向到同一个目标，Vue Router 判定为无限循环而中止导航 ——
 * 表现就是「登录成功但页面不动」。这里改为跳到真正有权访问的页面。
 */
function firstAccessiblePath(store) {
  const skip = (p) => !p || whiteList.includes(p) || p.includes(':pathMatch')

  const walk = (list, base) => {
    for (const r of list || []) {
      if (skip(r.path)) continue
      const full = r.path.startsWith('/')
        ? r.path
        : `${base}/${r.path}`.replace(/\/+/g, '/')
      // 分组路由（component 为 GroupView / Layout）：递归找子路由
      if (r.children && r.children.length) {
        const sub = walk(r.children, full)
        if (sub) return sub
        continue
      }
      if (!r.name) continue
      const perm = r.meta && r.meta.permission
      if (!perm || store.hasPermission(perm)) return full
    }
    return ''
  }
  return walk(routes, '')
}

router.beforeEach(async (to, from, next) => {
  const store = useUserStore()
  const hasToken = getToken()

  // APK 里后端地址不是同源的，未配置时先去「连接服务器」页，否则所有请求都会失败
  if (isNativeApp() && !hasServerBase() && to.path !== '/server') {
    return next('/server')
  }

  if (hasToken) {
    if (to.path === '/login') {
      // 已登录访问登录页：优先去首页；没有首页权限就去第一个可访问页面
      const target = store.hasPermission('dashboard:view')
        ? '/dashboard'
        : (firstAccessiblePath(store) || '/dashboard')
      return next(target)
    }
    // 首次进入需拉取用户信息（含权限码）
    if (!store.userInfo) {
      try {
        await store.getUserInfo()
        return next({ ...to, replace: true })
      } catch {
        store.resetState()
        return next('/login')
      }
    }
    // 路由级权限校验
    const perm = to.meta && to.meta.permission
    if (perm && !store.hasPermission(perm)) {
      // 避免「无权限 → 跳 dashboard → 仍无权限」的无限重定向：
      // 跳到用户真正有权访问的第一个页面；连一个都没有才退回登录页。
      const fallback = firstAccessiblePath(store)
      if (fallback && fallback !== to.path) {
        return next(fallback)
      }
      store.resetState()
      return next('/login')
    }
    return next()
  }

  if (whiteList.includes(to.path)) {
    return next()
  }
  return next('/login')
})
