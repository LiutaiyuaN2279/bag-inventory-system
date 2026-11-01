# 箱包采购与库存管理系统 · 开发预览候选

用于本机演示采购、库存及受限审计界面，并复现 B-002 数量纯核心的合成测试。**本版本是受限的 GitHub 开发预览，不适用于真实经营判断或正式审计结论。**

当前版本包含 **241 个文件**：此前审核的 192 文件代码／文档快照，加按用户要求恢复的 42 张界面截图和 7 份演示单据样张。历史配套和演示素材纳入不代表全部通过 WP-3 或页面验收。原公开仓库 [LiutaiyuaN2279/bag-inventory-system](https://github.com/LiutaiyuaN2279/bag-inventory-system) 保留提交历史，仍有 78 个旧文件不在当前版本中；这不是历史清理或全历史安全审核。原 `.git`、内部证据和私有数据不进入发布包，不强制推送或镜像推送。此前 192 文件 ZIP 及校验值仍只对应旧包；本次素材恢复未创建新的 GitHub Release。范围与验证限制见 [GitHub开发预览版发布说明](docs/GitHub开发预览版发布说明.md)。


## 演示截图与单据样张

以下为既有演示素材，用于了解界面和查看样例，不代表本轮已经重新验证所有页面、角色权限或真实业务流程。

[查看全部42张界面截图](docs/screenshots/) · [查看全部演示单据样张](test_docs/)

| 功能看板 | 登录界面 |
| --- | --- |
| ![功能看板](docs/screenshots/01-dashboard.png) | ![登录界面](docs/screenshots/02-login.png) |
| 采购订单 | 库存查询 |
| ![采购订单](docs/screenshots/07-purchase-order.png) | ![库存查询](docs/screenshots/10-inventory-query.png) |
| AI单据识别 | 岗位看板对照 |
| ![AI单据识别](docs/screenshots/30-ai-ocr.png) | ![岗位看板对照](docs/screenshots/41-roles-dashboard-compare.png) |

演示单据：

- [送货单测试样张](test_docs/送货单_测试样张.png)
- [住宿费专票图片](test_docs/rmb/住宿费专票_上海1650元.png)
- [出租车收据](test_docs/rmb/收据_出租车360元.png)
- [火车票](test_docs/rmb/火车票_杭州至上海.png)
- [餐饮发票](test_docs/rmb/餐饮发票_杭州2400元.png)
- [住宿费专票扫描件PDF](test_docs/rmb/住宿费专票_扫描件.pdf)
- [住宿费专票文本型PDF](test_docs/rmb/住宿费专票_文本型.pdf)

这些静态文件只作为演示样张，不是系统已核验的业务原件。查看或使用样张仍须遵守下文的本机可信数据、浏览器隔离和已知PDF依赖风险限制。


## 可以体验什么

- 管理员演示登录；首页看板、物料、采购订单、库存查询。
- 审计工作台的受限试算、限制披露及运行版本查询。R03/R10 证据不足时停算，未知值保留为未知。
- WP-1 输入／版本边界、WP-2 片段／限制映射、WP-3 首批内部 V2 数量候选路径的纯核心合成回归。

**两个公开数量入口 `evaluate_delivery_scope`、`summarize_delivery_facts` 对合法 V2 仍返回 `quantity_contract_not_ready`。** 内部候选结果为 `synthetic_only`、`formal_eligible=False`，没有接入真实来源、审批或正式业务 API。

界面中的旧 R01—R10 试算线索不代表最新日期设计已全部实现；其中旧 R04 不是已确认的六个月历史中位数规则。界面原有“v1.0”字样也不是正式审计或生产准入声明。

## 本机演示：Windows PowerShell

既有程序员验证环境为 Windows、Python **3.12.14**、Node.js **24.21.0**、npm **11.19.0**。其他平台／版本未验证。后端直接依赖见 `backend/requirements.txt`；前端使用 `package-lock.json` 和 `npm ci`。独立审核确认离线新装成功，**不等于在线下载独立通过**；下列在线安装命令用于复现，不据此增加验证结论。运行阶段只使用本地演示服务。本轮仅修订文档和核对候选指纹，不重跑安装、构建或应用测试，不尝试扩大权限。

**先将经过评审的候选包解压到全新目录。以下命令仅在该目录执行，不要在含业务数据、旧 `.env` 或私人附件的目录运行。** 不复制本项目原数据库、备份或运行环境。

```powershell
# 终端一：当前目录必须是全新解压的候选根目录。
$demoRoot = (Get-Location).Path
if (Test-Path -LiteralPath "$demoRoot/backend/.env") { throw '发现旧环境文件，停止' }
if (Test-Path -LiteralPath "$demoRoot/backend/data") { throw '发现已有数据目录，停止；请换全新目录' }
if (Get-NetTCPConnection -LocalPort 8000,5173 -State Listen -ErrorAction SilentlyContinue) { throw '演示端口已占用，不停止已有服务' }

py -3.12 -m venv .preview-venv
if ($LASTEXITCODE -ne 0) { throw '创建虚拟环境失败' }
$previewPython = "$demoRoot/.preview-venv/Scripts/python.exe"
& $previewPython -m pip install -r "$demoRoot/backend/requirements.txt"
if ($LASTEXITCODE -ne 0) { throw '后端依赖安装失败' }

# 明确覆盖运行配置，不从旧终端继承业务库、AI 或 OAuth 凭据。
$env:DATABASE_URL = 'sqlite:///' + ((Join-Path $demoRoot 'backend/data/app.db') -replace '\\','/')
$env:UPLOAD_DIR = Join-Path $demoRoot 'backend/data/uploads'
$env:AUDIT_TRIAL_ARCHIVE_DIR = Join-Path $demoRoot 'backend/data/audit_trials'
$env:SECRET_KEY = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
$env:AI_OCR_PROVIDER = 'mock'
$env:AI_OCR_API_KEY = ''
$env:AI_OCR_BASE_URL = ''
$env:AI_OCR_MODEL = ''
$env:GITHUB_OAUTH_ENABLED = 'false'
$env:GITHUB_CLIENT_ID = ''
$env:GITHUB_CLIENT_SECRET = ''
$env:OPLOG_RETENTION_DAYS = '0'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = Join-Path $demoRoot 'backend'
Set-Location "$demoRoot/backend"
& $previewPython -B scripts/init_db.py
if ($LASTEXITCODE -ne 0) { throw '初始化失败' }
& $previewPython -B scripts/seed_data.py
if ($LASTEXITCODE -ne 0) { throw '演示数据生成失败' }
& $previewPython -B -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

仅初始化新演示库，不执行重置、升级、迁移或历史回填脚本。演示账号 **admin / admin123**，只供本机使用；不可向公网开放。种子日期相对生成当天，不保证不同日期生成的数据库字节一致。演示单据样张位于 `test_docs/`，不会自动绑定到种子数据或成为业务原件；模拟 OCR 记录仍可能显示“原件未留存”，不代表 OCR 服务或真实来源验证通过。

```powershell
# 终端二：进入同一个全新候选目录的 frontend 子目录。
npm ci --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

### 首次打开页面之前：新建专用浏览器配置（PREVIEW-01）

先完成上面的新目录／本机服务配置，**不要先用日常浏览器打开任何候选页面，包括登录页和服务器设置页**。`bag_server_base` 残留在浏览器 localStorage 中可能改写请求地址；新解压源码目录不会清除同源浏览器状态。页面打开后才清理 localStorage 不能作为隔离前提。

在第三个 PowerShell 终端执行以下步骤；仅创建并使用这次全新的专用配置，不复用日常配置或既有浏览会话：

```powershell
$previewProfile = Join-Path $env:LOCALAPPDATA ('BagPreview-' + [guid]::NewGuid().ToString('N'))
$previewEdge = Join-Path ${env:ProgramFiles(x86)} 'Microsoft/Edge/Application/msedge.exe'
if (-not (Test-Path -LiteralPath $previewEdge)) { throw '未找到 Edge，请先确认独立配置启动方式；不要改用日常会话' }
if (Test-Path -LiteralPath $previewProfile) { throw '配置目录已存在，停止' }
New-Item -ItemType Directory -Path $previewProfile -ErrorAction Stop | Out-Null
# 第一次只打开空白页，不带任何候选页面 URL。
& $previewEdge "--user-data-dir=$previewProfile" --no-first-run --no-default-browser-check --disable-sync --disable-extensions --disable-background-networking about:blank
# 先在新窗口的 edge://version 核对“个人资料路径”位于 $previewProfile 下。
# 确认后，才在该窗口地址栏手动输入 http://127.0.0.1:5173/#/login。
```

不要登录浏览器账号、导入服务器地址／登录状态／扩展或同步配置；不要点击旧窗口中的候选链接。仅访问本机演示地址，**不设置远程服务器地址**。若无法确认新配置实际生效或组织策略阻止隔离，应停止演示，不能回退到日常配置。以上是操作者必须落实的隔离步骤，**不是应用已具备强制本机隔离**。

健康检查为 `http://127.0.0.1:8000/api/health`；如用浏览器查看，也只在上述专用窗口访问。前端开发代理指向本机 8000。两端须配套使用，旧审计客户端会被版本门禁拒绝。验证结束关闭专用窗口，并用服务终端的 Ctrl+C 停止服务，不保留对外监听。

## 可复现验证

```powershell
# 前端目录：锁定依赖安装后。
# 独立审核环境已验证的构建方式；不修改 vite.config.js 或 package.json。
npm run build -- --configLoader native
node --test tests/audit-p0.test.js

# 后端目录：使用上面新建的 Python 环境。
$env:PYTHONPATH = (Get-Location).Path + ';' + (Join-Path (Get-Location).Path 'tests')
& ../.preview-venv/Scripts/python.exe -B -m unittest test_audit_delivery_contract test_audit_delivery_fragments test_audit_delivery_restrictions test_audit_delivery_quantity -v
```

验证来源必须分开：独立审核确认离线新装、`--configLoader native` 构建和进程内接口验证通过；默认 `npm run build` 在审核环境受限。程序员原日志记录默认构建、实际本机监听与五页面成功并已被审阅，**实际监听与五页面没有独立复跑**。native 命令适用于该审核环境及既有 Vite 6.4.3 原生可加载配置，不等于所有运行环境或默认构建都已独立通过。

程序员既有隔离日志记录：**242 个后端方法、585 个实际 subTest，0 失败／错误／跳过；前端 5 项通过。** 后端测试使用合成输入，并由外层验证工具禁止文件写入、数据库、网络和子进程；本轮不新增执行结果。上面的普通 unittest 命令用于复现测试，运行者仍须使用独立目录。失败日志原样保留，不以语法检查或进程内测试代替实际监听／浏览器复跑。

TV-01 曾经获得授权迁移一个 `kind="scope"` 子案例的预期，其旧触发输入保留；不能描述为全部旧断言未变。原 89 项后端历史测试未在本轮迁移或执行，不属于这 242 个方法；原前端 5 项保持，既有执行日志保留，本轮未重跑。数量不能代替完整规格覆盖结论。

## 具体依赖风险（PREVIEW-02／PREVIEW-03，未修复）

审核安装版本包含 **Starlette 0.41.3** 和 **pypdf 5.1.0**，均在以下公告的受影响版本范围内：

- Starlette：[GHSA-2c2j-9gv5-cj73 / CVE-2025-54121](https://github.com/Kludex/starlette/security/advisories/GHSA-2c2j-9gv5-cj73)，大文件 multipart 表单解析可阻塞事件线程并导致拒绝服务，公告列出的修复版本为 0.47.2。
- Starlette Range：[GHSA-7f5h-v6xp-fcq8 / CVE-2025-62727](https://github.com/Kludex/starlette/security/advisories/GHSA-7f5h-v6xp-fcq8)，受影响版本为 0.39.0 至 0.49.0（含），**当前 Starlette 0.41.3 受影响**；特制 Range 请求可能使 `FileResponse`／`StaticFiles` 文件服务耗尽 CPU 并导致拒绝服务。该公告修复版本为 **0.49.1**。
- pypdf：[GHSA-4xc4-762w-m6cg / CVE-2026-22690](https://github.com/py-pdf/pypdf/security/advisories/GHSA-4xc4-762w-m6cg)，非严格模式解析特定畸形 PDF 可能长时间运行，公告列出的修复版本为 6.6.0。

**multipart 公告的 0.47.2 不能替代 Range 公告的 0.49.1 修复要求；这两项 Starlette 已知风险本批均未修复。** 本轮未升级依赖，pypdf 风险同样保留，不能仅以“公告非穷尽”承接已经知道的 Range 漏洞。本版仅限本机、可信合成数据演示，**不处理不可信文件（包括不可信 PDF），不对外监听**；这些使用限制不能修复漏洞，也不是应用已强制拒收所有不可信文件。上述三条公告仍不是完整漏洞清单；全量供应链与许可证审核未完成，不能只以“间接依赖未锁定”概括风险。

## 已知限制

- 未批准正式业务资格、历史可信期间、C02 整体验收、完整 WP-3 或数据库迁移；不自动分配、FIFO、比例分配、审批或恢复。
- 试算快照支持版本读取和内容校验，但本机 JSON 文件不是不可删除、不可篡改存储。缺失证据不能靠哈希补足。
- 工作日历算法、真实证据／审批、生产性能、安全审计、真实 AI、OAuth、Android 及报销完整流程均未在本轮验收。
- 前端构建存在大于 500 kB 的块警告。后端间接依赖尚未完整锁定，不能承诺未来安装解析结果完全相同。
- 当前版本恢复了既有界面截图及演示单据样张，16 个历史配套文件的已批准范围保持。数据库、真实业务附件、`.env`、密钥、私有快照与内部证据不进入本次提交或发布附件。旧提交历史保留，当前文件清单不能替代整个 Git 历史的审核。

项目保留原有 MIT 许可证，见 [LICENSE](LICENSE)。
