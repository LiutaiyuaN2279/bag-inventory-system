import { existsSync, rmSync, cpSync, mkdirSync } from 'node:fs'
import { resolve } from 'node:path'

// 构建后自动把 dist 同步到 Android 工程的 assets/www，
// 这样 `npm run build:apk` 一条命令就能得到最新的 APK 前端资源。
//
// 注意：用 process.cwd() 而不是 import.meta.url —— 本项目路径含中文，
// Windows 下 fileURLToPath 会把中文转成 %XX 编码，导致找不到目录。
const frontendDir = process.cwd()
const src = resolve(frontendDir, 'dist')
const dest = resolve(frontendDir, '..', 'android', 'app', 'src', 'main', 'assets', 'www')

if (!existsSync(resolve(src, 'index.html'))) {
  console.error('[copy-dist] 未找到 dist/index.html，请先执行 vite build')
  process.exit(1)
}

rmSync(dest, { recursive: true, force: true })
mkdirSync(dest, { recursive: true })
cpSync(src, dest, { recursive: true })
console.log('[copy-dist] dist -> android/app/src/main/assets/www 完成')
