# APK 打包说明

把「箱包采购与库存管理系统」的 **Vue 前端** 打包成 Android APK。
后端仍是原来的 Python FastAPI 服务，跑在电脑上；手机 APK 通过网络连接后端。

**产物**：`dist-apk/箱包采购与库存管理.apk`（约 3.2 MB）

---

## 一、架构关系（重要）

```
┌──────────────────────┐         HTTP          ┌──────────────────────────┐
│   Android APK        │  ──────────────────>  │  电脑上的后端服务         │
│  Vue3 界面 + WebView │   /api/v1/...         │  FastAPI + SQLite         │
└──────────────────────┘                       └──────────────────────────┘
```

APK 里**没有** Python 运行时，所以：

- ✅ 所有界面、菜单、权限、报表、BOM 算料、AI 识别上传都能在手机上操作
- ✅ 数据统一存在电脑的 `backend/data/app.db`，手机与电脑看到同一份数据
- ⚠️ 必须先启动电脑端后端，且手机与电脑在同一局域网 / WiFi

> 想做「完全离线、不连电脑」的版本，需要把后端改写成 Android 本地实现
>（Room/SQLite + Java/Kotlin），属于另一个量级的改造，不是打包配置能解决的。

---

## 二、电脑端后端准备（必须做，否则手机连不上）

### 1. 让后端监听所有网卡

默认只监听 `127.0.0.1` 时手机访问不到：

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 2. 放行防火墙（管理员 PowerShell，执行一次）

```powershell
New-NetFirewallRule -DisplayName "箱包库存后端 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```

### 3. 查看电脑局域网 IP（手机里要填这个）

```powershell
ipconfig | Select-String "IPv4"
```

> 例如查到 `192.168.1.10`，手机里就填 `192.168.1.10:8000`。

### 4. 确认 CORS 允许 APK 来源

APK 内 WebView 的固定源是 `https://appassets.androidplatform.net`。
**这一项已在代码里默认配好**（`backend/app/core/config.py` 的 `CORS_ORIGINS`），
无需手动改。如果你在 `backend/.env` 里自己写过 `CORS_ORIGINS`，
请务必把该项也加进去，否则手机端所有请求会被 CORS 预检拒绝。

---

## 三、安装与首次使用

1. 把 `dist-apk/箱包采购与库存管理.apk` 传到手机（数据线 / 微信文件传输 / QQ 均可）
2. 手机上点击安装；若提示「未知来源」，在弹窗里允许
3. 首次打开进入「连接服务器」页，填入电脑地址（如 `192.168.1.10:8000`）
   - 只填 IP 和端口即可，程序会自动补 `http://`
   - 点「保存并测试连接」，成功后自动跳到登录页
4. 用演示账号登录（密码统一 `admin123`）：
   `admin` / `manager` / `buyer` / `keeper` / `qc`
5. 之后想换服务器：登录页底部「当前服务器」→ 修改

---

## 四、手机端功能说明

| 功能 | 手机端表现 |
| --- | --- |
| 登录 / 权限 / 菜单 | 与电脑一致，72 个权限码完全生效 |
| 单据增删改查、批量操作 | 一致 |
| AI 单据识别 | 可调起系统文件选择器选图上传识别 |
| Excel 导入导出 | 导出保存到手机「下载」目录 |
| 单据打印 | 调起系统打印服务，可另存 PDF 或直连打印机 |
| 报表图表 | ECharts 正常渲染 |
| 窄屏布局 | 侧栏自动折叠为图标条，顶栏精简，看板两列排布 |

---

## 五、重新打包

一键脚本：

```powershell
powershell -ExecutionPolicy Bypass -File build-apk.ps1
```

手动分步：

```powershell
cd frontend
npm run build:apk          # 构建前端 + 自动复制到 android/app/src/main/assets/www

cd ..\android
gradle assembleRelease     # 或 .\gradlew assembleRelease
```

### 签名配置（可选，建议自备）

签名信息**不写在** `build.gradle` 里，而是从 `android/keystore.properties` 读取：

```powershell
copy android\keystore.properties.example android\keystore.properties
# 然后按注释填写 storeFile / storePassword / keyAlias / keyPassword
```

`keystore.properties` 与密钥库文件（`*.keystore`、`*.jks`）都已加入 `.gitignore`，不会进入版本库。

**没有这个文件也不会构建失败**：`build.gradle` 会自动回落到 Android 默认的 debug 签名，
照样能打出可安装的 APK —— 只是签名不同，无法覆盖安装由别的密钥签名的版本。

---

## 六、目录说明

```
android/                                        Android 原生工程
├── app/src/main/assets/www/                    前端构建产物（copy-dist.mjs 自动同步）
├── app/src/main/java/.../MainActivity.java     WebView 容器 + 原生桥
├── app/src/main/res/                           图标、主题、网络安全配置
├── app/baginventory.keystore                   签名密钥（本地自备，已加入 .gitignore）
├── keystore.properties.example                 签名配置模板（复制为 keystore.properties 后填写）
├── app/src/main/res/mipmap-*/ic_launcher.png   应用图标
└── build.gradle / settings.gradle               构建配置

frontend/src/utils/server.js        服务器地址存取与 URL 改写
frontend/src/views/system/server.vue 「连接服务器」页
frontend/scripts/copy-dist.mjs      dist → Android assets 同步脚本
build-apk.ps1                       一键打包脚本
dist-apk/                           最终 APK 输出目录
```

---

## 七、关键实现说明（改动过的地方）

### 1. 服务器地址如何生效

`frontend/src/utils/server.js` 把用户填的地址存进 `localStorage`，
`utils/request.js` 用**请求拦截器**把 `baseURL` 从 `/api/v1` 改成
`http://填写的地址/api/v1`，所有业务接口自动走新地址。

`utils/download.js` 直接调 axios、写死了 `/api/v1...`，
所以单独用 `resolveUrl()` 处理；两处都覆盖才不会有接口漏网。

> 浏览器里 `getServerBase()` 返回空串，行为与原来完全一致，不影响网页部署。

### 2. 用 https 虚拟源加载前端（避免白屏）

前端是 ES Module 构建产物。若用 `file://` 加载，模块脚本会被当作跨域请求拦截，
**页面直接白屏**（这一点已实测复现）。因此 `MainActivity` 使用官方推荐的
`WebViewAssetLoader`，把 assets 映射到 `https://appassets.androidplatform.net`，
拿到正常的 https 源，模块加载、localStorage 全部不受限。

### 3. 明文 HTTP 与 CORS

- Android 9+ 默认禁止 http 明文请求，而局域网后端通常是 `http://IP:8000`，
  所以 `AndroidManifest.xml` 设了 `usesCleartextTraffic="true"` +
  `network_security_config.xml` 放行。
- APK 的源是 `https://appassets.androidplatform.net`，与后端**跨源**，
  因此后端 `CORS_ORIGINS` 必须包含该源，否则预检返回
  `400 Disallowed CORS origin`（已实测并修复）。

### 4. 原生桥（AndroidBridge）

`MainActivity` 通过 `addJavascriptInterface` 暴露：

| 方法 | 用途 |
| --- | --- |
| `saveBase64File(name, base64, mime)` | Excel 导出保存到手机下载目录（Android 10+ 走 MediaStore） |
| `printHtml(html)` | 调起系统打印服务 |
| `toast(msg)` | 原生提示 |

前端在 `utils/download.js`、`utils/print.js`、`router/guard.js`、
`views/login/index.vue` 用 `window.AndroidBridge` 判断是否运行在 APK 中。

### 5. 文件上传

`WebChromeClient.onShowFileChooser` 已实现，`el-upload` 能正常调起
系统文件选择器（含多选），满足 AI 识别与 Excel 导入的需要。

---

## 八、常见问题

**Q：打开 APP 白屏？**
A：确认 `MainActivity` 用的是 `WebViewAssetLoader` + `https://appassets...`
而不是 `file:///android_asset/...`；并确认已执行 `npm run build:apk`
（该命令会把 `dist` 同步进 `assets/www`）。

**Q：提示「无法连接服务器」？**
逐项排查：
1. 后端是否用 `--host 0.0.0.0` 启动（不是 `127.0.0.1`）
2. 电脑防火墙是否放行 8000
3. 手机与电脑是否同一 WiFi
4. 手机浏览器打开 `http://电脑IP:8000/api/health`，能否看到 `{"code":0,...}`
5. 地址是否漏了端口

**Q：能登录但列表都报 CORS 错误？**
A：`backend/.env` 里若自己写过 `CORS_ORIGINS`，需补上
`https://appassets.androidplatform.net`。

**Q：导出文件找不到？**
A：Android 10+ 在「下载 / Download」目录；更低版本需授予存储权限。

**Q：界面字太小 / 排版挤？**
A：这是桌面布局的界面。窄屏已做自动折叠侧栏与两列排布，
建议横屏使用；表格类页面（如采购订单明细）可双指缩放。

**Q：打包报「找不到密钥库」/ 签名相关失败？**
A：两种可能——
1. 已复制 `keystore.properties`，但里面的 `storeFile` 指向的文件不存在。
   把密钥库放回该路径；或者直接删掉 `keystore.properties`，让构建回落到 debug 签名。
2. 想用自己的密钥：按 `keystore.properties.example` 里的 `keytool` 命令先生成密钥库。

---

## 九、本次打包的环境备注

- 打包机原本没有 JDK / Android SDK，工具链是便携化下载到
  `.tmp-run/toolchain`（JDK 17、SDK platform-34 + build-tools 34、Gradle 8.9）。
- 项目路径含中文，AGP 默认会拒绝构建，已在 `android/gradle.properties`
  加 `android.overridePathCheck=true` 放行（实测编译正常）。
- 该机器缺少虚拟化驱动（AEHD/HAXM），Android 模拟器无法启动，
  因此**未能在模拟器里跑安装验证**；改为在浏览器中以相同加载方式
  （相对路径 + hash 路由 + 手机设备尺寸）+ 真实后端完成了端到端验证：
  登录成功、菜单 33 项、看板数据正常、无横向溢出。
- APK 使用自签名证书，可直接安装；如需上架或长期分发，请替换为你自己的 release 密钥
  并妥善保管。签名信息从 `android/keystore.properties` 读取（模板见 `keystore.properties.example`），
  密钥库与配置文件本身都不入版本库。
