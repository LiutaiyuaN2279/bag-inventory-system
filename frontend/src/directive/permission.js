/** 按钮级权限指令：v-permission="'basic:material:add'" 或 v-permission="['a','b']"。 */
import { useUserStore } from '@/store/user'

function check(value) {
  // 统一走 store.hasPermission，保证「用户级禁用 / admin 短路 / 权限码命中」三处逻辑一致
  return useUserStore().hasPermission(value)
}

// 官方推荐做法：只控制显隐、不移除 DOM 节点，避免绕过 Vue 渲染器导致 removeChild 报错
function apply(el, binding) {
  el.style.display = check(binding.value) ? '' : 'none'
}

export default {
  mounted(el, binding) {
    apply(el, binding)
  },
  // 权限变化（如切换账号）后重新判定
  updated(el, binding) {
    apply(el, binding)
  }
}
