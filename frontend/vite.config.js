import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  // 相对路径：打包进 APK 后 WebView 用 file:// 加载，绝对路径 /assets/... 会 404
  base: './',
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5173,
    watch: {
      // Windows 下文件被其他进程（杀毒软件、搜索索引、编辑器）短暂锁定时，
      // fs.watch 会抛 EBUSY，导致 Vite 的 FSWatcher 崩溃退出整个 dev server。
      // 改用轮询绕开该问题；项目规模不大，400ms 间隔的开销可以忽略。
      usePolling: true,
      interval: 400,
      ignored: ['**/node_modules/**', '**/.git/**', '**/dist/**', '**/.tmp/**']
    },
    proxy: {
      // 开发期把 /api 转发到后端，避免跨域
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  }
})
