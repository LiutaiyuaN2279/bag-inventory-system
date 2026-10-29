import { defineStore } from 'pinia'
import { login as loginApi, userinfo as userinfoApi, logout as logoutApi } from '@/api/auth'
import { getToken, setToken, removeToken } from '@/utils/auth'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: getToken(),
    userInfo: null,
    roles: [],
    permissions: [],
    // 用户级「明确禁用」的权限码：优先级高于角色与 admin 身份
    deniedPermissions: []
  }),
  getters: {
    isLogin: (state) => !!state.token,
    /**
     * 权限判定：用户级禁用 > admin 全放行 > 权限码命中。
     * perm 支持单个权限码或数组（数组语义为「满足其一」，与后端 require_permissions 一致；
     * 仅当数组中所有权限码都被禁用时才拦截）。
     */
    hasPermission: (state) => (perm) => {
      const need = Array.isArray(perm) ? perm : [perm]
      if (!need.length) return true
      const denied = state.deniedPermissions || []
      if (need.every((p) => denied.includes(p))) return false
      if (state.roles.includes('admin')) return true
      return need.some((p) => state.permissions.includes(p))
    }
  },
  actions: {
    async login(loginForm) {
      const data = await loginApi(loginForm)
      this.token = data.access_token
      setToken(this.token)
      return data
    },
    /**
     * 已经拿到 token 的登录方式（GitHub 快捷登录票据兑换）。
     * 存下 token 后立刻拉一次用户信息，保证角色/权限状态与口令登录完全一致。
     */
    async loginWithToken(accessToken) {
      this.token = accessToken
      setToken(accessToken)
      return this.getUserInfo()
    },
    async getUserInfo() {
      const data = await userinfoApi()
      this.userInfo = data
      this.roles = data.roles || []
      this.permissions = data.permissions || []
      this.deniedPermissions = data.denied_permissions || []
      return data
    },
    async logout() {
      try {
        await logoutApi()
      } finally {
        this.resetState()
      }
    },
    resetState() {
      this.token = ''
      this.userInfo = null
      this.roles = []
      this.permissions = []
      this.deniedPermissions = []
      removeToken()
    }
  }
})
