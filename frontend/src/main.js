import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus, { ElDialog } from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'
import './router/guard' // 注册全局路由守卫
import permissionDirective from './directive/permission'

const app = createApp(App)

// 全局注册 Element Plus 图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.directive('permission', permissionDirective)

// 全局开启所有 Dialog 可拖动（按住标题栏拖动），个别弹窗如需禁用可显式 :draggable="false"
ElDialog.props = ElDialog.props || {}
ElDialog.props.draggable = { type: Boolean, default: true }

app.mount('#app')
