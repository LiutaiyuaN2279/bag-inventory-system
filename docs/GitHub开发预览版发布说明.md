# GitHub 开发预览版发布说明

状态：受限的 GitHub 开发预览。PREVIEW-01、PREVIEW-02、PREVIEW-03 已通过定向审核；随后按用户要求恢复 42 张既有截图和 7 份演示样张，当前文件树为 241 项。更新时间：2026-11-01。本次只恢复素材和文档入口，不改数量核心、安全门禁、依赖或业务逻辑，不重跑应用测试；旧 ZIP 和证据保持不变，未创建新的 GitHub Release。

## 1. 定位与版本来源

本候选供本机演示和开发复现。B-002 WP-3 首批 V2 数量纯核心及内部适配批次已由产品经理确认关闭；这不代表完整 WP-3、C02、历史可信期间、数据库迁移或生产准入通过。

本版本以已审核的 192 文件快照为代码基线，再恢复原提交中的 49 份静态演示素材。仅两份说明文档更新素材和范围描述，原有 190 个非文档文件及 9 份纯核心保持不变。目标为原公开仓库 `LiutaiyuaN2279/bag-inventory-system`，采用保留历史的普通提交。原先排除的 127 个旧文件中恢复 49 个，剩余 78 个仍不在当前树中；旧提交和旧文件继续可访问。**这不是历史清理或敏感信息移除，不代表原仓库历史已完成完整审核。** 原本地工作区及业务数据保持。

## 2. 精确候选范围与归属

当前 Web 开发预览包含 **241 个文件**，即原 192 文件快照加 42 张截图和 7 份演示样张。此前 192 文件 ZIP、`candidate-manifest.json`、`SHA256SUMS.txt` 和 `ZIP-SHA256.txt` 保持原样，它们不适用于本次 241 文件快照。本次只恢复 Git 仓库素材，未创建新的 Release 或替换旧 ZIP；后续若发布新归档，必须按当前提交重新生成文件清单与校验值，不能沿用旧包摘要。原始日志、内部绝对路径及调查资料不公开，原 Git 历史不因此获得完整审核结论。

| 类别 | 数量 | 处理 |
| --- | ---: | --- |
| 未改动的 HEAD 基础文件 | 165 | 后端 app、前端 src、入口、锁文件、许可及最小初始化脚本等 |
| 已验收数量纯核心及对应测试 | 9 | 工作区实际源码，不以 HEAD 替代 |
| 历史运行配套依赖 | 16 | 已审核并由产品经理批准纳入；不代表全部通过 WP-3 验收 |
| 本轮发布材料 | 2 | README 与本说明 |
| 恢复的界面截图 | 42 | 原 `docs/screenshots/` 内容，作为历史界面演示素材，不增加页面验收声明 |
| 恢复的演示单据 | 7 | 原 `test_docs/` 内容：5 张PNG及2份PDF；不视为业务原件或自动导入数据 |

9 个纯核心文件：

- `backend/app/services/audit_delivery.py`
- `backend/app/services/audit_delivery_contract.py`
- `backend/app/services/audit_delivery_fragments.py`
- `backend/app/services/audit_delivery_restrictions.py`
- `backend/app/services/audit_delivery_quantity.py`
- `backend/tests/test_audit_delivery_contract.py`
- `backend/tests/test_audit_delivery_fragments.py`
- `backend/tests/test_audit_delivery_restrictions.py`
- `backend/tests/test_audit_delivery_quantity.py`

16 个历史配套文件（不能表述为全部属于 WP-3 验收）：

| 文件 | 纳入必要性 |
| --- | --- |
| `.gitignore` | 私有试算等运行产物的排除规则 |
| `backend/.env.example` | 公开模板，非实际配置，不含真实凭据 |
| `backend/app/core/config.py` | 试算归档路径设置 |
| `backend/app/api/v1/audit.py` | 受限试算查询、运行绑定与客户端门禁 |
| `backend/app/services/audit_service.py` | 旧规则线索与 R03/R10 证据不足保护 |
| `backend/app/services/audit_assurance.py` | 旧数据可信范围披露依赖 |
| `backend/app/services/audit_trial_archive.py` | 独立非正式试算归档依赖 |
| `frontend/src/api/audit.js` | 当前审计客户端入口 |
| `frontend/src/api/auditClient.js` | 运行版本绑定 |
| `frontend/src/components/AuditAssuranceNotice.vue` | 限制状态提示 |
| `frontend/src/utils/auditPresentation.js` | 未知数值与导出披露 |
| `frontend/src/views/audit/dashboard.vue` | 受限试算展示 |
| `frontend/src/views/audit/findings.vue` | 审计发现及运行绑定 |
| `frontend/src/views/audit/workflow.vue` | 作业流程及限制提示 |
| `frontend/src/views/audit/workpaper.vue` | 底稿与未知值展示 |
| `frontend/tests/audit-p0.test.js` | 5 项现有前端断言的复现输入 |

其中 10 个为原有跟踪文件的历史修改，6 个为原有未跟踪配套文件。删除这些文件或混用 HEAD 中的旧版本，会造成导入缺失、前后端契约错配或丢失受限提示。当前批准的是这些文件进入干净快照的发布范围，不是将其全部升级为 WP-3 已验收实现；本轮不改其内容。

## 3. 明确排除

以下排除针对当前版本快照及发布附件，不会使原公开仓库旧提交中的文件消失。

- 原 `.env`、访问令牌、私钥和签名材料；示例模板不替代随机运行密钥。
- 全部业务数据库、SQLite WAL/SHM、备份、真实上传件、附件与私人试算快照。
- `.tmp*`、历史测试证据、运行日志、缓存、虚拟环境、`node_modules`、构建产物。
- 内部设计、台账、23 项决定、原验收报告与调查资料；保留在原目录，不自动公开。
- Android 源码、APK 及移动打包材料：本候选只验证 Web 演示，不声称 Android 兼容性。
- 非最小初始化／种子脚本、历史重置／升级脚本及未明确恢复的其他测试附件。已恢复的 `test_docs/` 七份静态演示样张不在该排除范围内。
- 原 89 项后端历史测试：保留原件，本轮没有 V2 迁移授权，不能将其混入当前定向测试或宣称通过。

排除清单中同时记录了具体文件和禁止复制模式；条目数不能解释为被删除的文件数。没有删除、清理或丢弃原文件。候选中不含原数据库，即使是“演示”命名的原库也不复制。

## 4. 安装、初始化与运行

完整 PowerShell 步骤见 [README](../README.md)。只在全新解压候选目录中执行。先确认 8000/5173 未被已有服务占用，再创建新 Python 环境、安装公开依赖；前端使用 `npm ci`，不执行 `npm update`。

### PREVIEW-01：必须在首次打开任何候选页面之前隔离浏览器

启动本机服务后，仍不要使用日常配置或既有会话打开候选登录页、服务器设置页或其他页面。`bag_server_base` 残留可能把请求改写到其他服务器；新解压目录不会清除浏览器同源 localStorage。**页面打开后再清理 localStorage 不构成事前隔离。**

按 README 或以下相同步骤执行一次，先创建全新专用配置并只打开空白页：

```powershell
$previewProfile = Join-Path $env:LOCALAPPDATA ('BagPreview-' + [guid]::NewGuid().ToString('N'))
$previewEdge = Join-Path ${env:ProgramFiles(x86)} 'Microsoft/Edge/Application/msedge.exe'
if (-not (Test-Path -LiteralPath $previewEdge)) { throw '未找到 Edge；不要改用日常浏览会话' }
if (Test-Path -LiteralPath $previewProfile) { throw '配置目录已存在，停止' }
New-Item -ItemType Directory -Path $previewProfile -ErrorAction Stop | Out-Null
& $previewEdge "--user-data-dir=$previewProfile" --no-first-run --no-default-browser-check --disable-sync --disable-extensions --disable-background-networking about:blank
# 在新窗口 edge://version 确认个人资料路径属于 $previewProfile 后，
# 才在该窗口地址栏手动输入 http://127.0.0.1:5173/#/login。
```

不登录浏览器账号，不导入服务器地址、登录状态、扩展或同步配置；仅访问本机演示地址，不设置远程服务器地址，不从原会话点击候选链接。配置路径或组织策略使隔离无法确认时应停止，不能回退日常会话。**这是操作前提，不是应用已经实现强制本机隔离。**

必须在导入应用前将 `DATABASE_URL`、`UPLOAD_DIR`、`AUDIT_TRIAL_ARCHIVE_DIR` 指向新演示目录，设置新随机 `SECRET_KEY`，明确 `AI_OCR_PROVIDER=mock`，关闭 GitHub OAuth 并清空外部凭据；不复制旧 `.env`。初始化只执行现有 `init_db.py` 和 `seed_data.py`。不得运行旧全量 reset、迁移、历史回填或制度文档导入脚本。

管理员演示账号 `admin/admin123`；仅监听 `127.0.0.1`。登录页可列出种子账号，但本轮只承诺管理员验证，不承诺其他角色审批闭环。演示数据由脚本全新生成，没有复制原业务库。

初始化产生物料 165、供应商 42、仓库 11、采购订单 70、到货记录 55、库存记录 541 等合成数据。种子日期使用生成当天；数量与结构可复现，不承诺每次数据库哈希或日期相同。`test_docs/` 的七份演示样张已恢复，但不会自动绑定到模拟 OCR 记录或构成真实来源证据；模拟记录仍可能缺少原件，不能声称实物证据完整。

## 5. 验证来源与限制（PREVIEW-02）

以下分别披露程序员既有日志和产品经理本轮转达的独立审核结论。不能把文档修订或指纹核对计为新的安装、测试或独立复跑。本轮读取了原日志，没有安装、启动或扩大权限尝试。

| 项目 | 验证来源及已支持结论 | 明确限制 |
| --- | --- | --- |
| 后端／前端安装 | 独立审核：离线新装成功；程序员原日志：新环境依赖安装成功 | 离线成功不等于在线下载独立通过；本轮不重新安装，不作扩大权限尝试 |
| 前端构建 | 独立审核：`npm run build -- --configLoader native` 通过；程序员原日志：默认 `npm run build` 成功，Vite 6.4.3 | 默认构建在独立审核环境受限，不写成独立默认构建通过；有大于 500 kB 块警告 |
| 演示初始化 | 程序员原日志：两个最小脚本成功，仅生成新合成库 | 不宣称本轮重新初始化或独立完成整个业务流程；未执行迁移 |
| 接口 | 独立审核：进程内接口验证通过 | 不能据此认定实际端口监听或浏览器链路已独立验证 |
| 实际监听与登录 | 程序员原成功日志经审阅：本机后端、健康检查与 `admin/admin123` 登录成功 | 没有独立复跑实际监听；原服务已停止，本轮不启动 |
| 基础 API | 程序员原日志：userinfo、物料、供应商、采购订单、库存、看板业务 `code=0` | 和进程内验证区分，不增加本轮实测结论 |
| 五页面 | 程序员原 Edge 隔离配置成功日志经审阅：看板、物料、采购订单、库存、审计工作台可显示；三列表各 20 行，23 次 API 响应无错误，pageerror 为 0 | 五页面未独立复跑；不是全系统端到端覆盖 |
| 受限试算 | 程序员原日志：按 run_id 读取报告／发现／底稿，R03/R10 数据不足、命中数 null，旧客户端拒绝 | 版本可读不等于正式审计证据完备，不额外声称本轮或独立实际监听验证 |
| 纯核心 | 程序员既有日志：242 方法、585 实际 subTest，失败／错误／跳过均 0 | 本轮未重跑；87 个 subTest 调用位置不等于 585 个运行子案例；不能替代完整规格或真实资格验证 |
| 前端原断言 | 程序员既有日志：5 测试通过，失败／跳过 0 | 文件保持，本轮未重跑 |

已由独立审核验证的构建命令，在全新候选副本的前端目录、依赖已就绪时执行：

```powershell
npm run build -- --configLoader native
```

该命令使用现有 Vite 的原生配置加载器，不改业务代码、配置或锁文件；适用于审核所用环境和现有可被原生加载的配置，不保证其他 Node／平台或默认加载路径已通过。本轮不实际执行此命令。

安装首次因受限进程的 Windows 用户目录或网络权限失败；首次演示检查因验证脚本误用 `/auth/me` 出现 404，随后改用真实 `/auth/userinfo`。另一轮保护器未识别隔离目录的 SQLite 只读 URI，被安全拒绝；修正验证保护器路径识别后重新检查成功。原失败日志均保留，没有改业务源码或删除失败证据。

上段描述程序员历史尝试，不是本轮重试或安装授权。本轮没有尝试修饰失败结果或扩大权限。历史验证工具曾清空继承的业务配置、固定写入路径并限制 I/O；其隔离浏览器和保护器只属于验证工具，不是应用已经具备的强制安全能力。原日志保留供审阅，不随候选公开。

### 具体已知依赖风险：没有升级，风险仍存在

审核安装版本为 **Starlette 0.41.3**、**pypdf 5.1.0**；程序员安装版本记录与这两个版本一致。以下三条官方公告分别覆盖当前组件版本；multipart 与 Range 两项 Starlette 风险必须并列披露：

| 组件／当前版本 | 官方安全公告 | 风险与当前处置 |
| --- | --- | --- |
| Starlette 0.41.3 | [GHSA-2c2j-9gv5-cj73 / CVE-2025-54121](https://github.com/Kludex/starlette/security/advisories/GHSA-2c2j-9gv5-cj73)；公告列出的修复版本为 0.47.2 | 大文件 multipart 表单解析可阻塞事件线程并导致拒绝服务；本轮未升级、风险未消除 |
| Starlette 0.41.3（Range） | [GHSA-7f5h-v6xp-fcq8 / CVE-2025-62727](https://github.com/Kludex/starlette/security/advisories/GHSA-7f5h-v6xp-fcq8)；受影响版本为 0.39.0 至 0.49.0（含），当前 0.41.3 受影响；该公告修复版本为 **0.49.1** | 特制 Range 请求可能使 `FileResponse`／`StaticFiles` 文件服务耗尽 CPU 并导致拒绝服务；本批未修复 |
| pypdf 5.1.0 | [GHSA-4xc4-762w-m6cg / CVE-2026-22690](https://github.com/py-pdf/pypdf/security/advisories/GHSA-4xc4-762w-m6cg)；公告列出的修复版本为 6.6.0 | 非严格模式解析特定畸形 PDF 可能长时间运行；本轮未升级、风险未消除 |

**multipart 公告的 0.47.2 不能替代 Range 公告的 0.49.1 修复要求；两项 Starlette 已知风险本批均未修复。** 本轮没有升级依赖，pypdf 风险也仍存在，不能仅以“公告非穷尽”代替已知 Range 漏洞披露。

本版**仅限本机、可信合成数据演示，不处理不可信文件（包括不可信 PDF），不对外监听**。使用限制仅降低暴露，不修复漏洞，也不代表应用已强制拒收不可信文件。不能只用“间接依赖未锁定”替代上述具体风险披露。上述三条公告仍不是穷尽漏洞清单；全量供应链与许可证审核未完成。

## 6. 数量门禁与审计限制

公开 Python 入口 `evaluate_delivery_scope`、`summarize_delivery_facts` 继续对合法 V2 抛出 `quantity_contract_not_ready`，非法输入继续按原契约拒绝。没有客户端 ready 开关，没有旧算法回退，没有恢复 None 日期隐式授信。

WP-3 本批内部候选支持合成数量与局部状态验证，始终带 `synthetic_only`、`formal_eligible=False`。这不是 Web 业务 API 已采用这些结果的证明。页面旧试算使用独立旧口径线索，R03/R10 暂停确定性份额结论；其余 R01—R10 也不能据此声称通过最新整体日期设计。旧 R04 界面不是六个月中位数正式基准。

没有核验的历史期间保持不可确定；未知不得当零，线索不得当违规结论或正式审计通过。独立 JSON 快照的版本读取和哈希校验不能证明不可删除、不可篡改、完整原件保全或正式历史可重现性。

## 7. 测试迁移与未验证事项

TV-01 是经明确授权迁移 `test_ir02_unrelated_inactive_and_historical_decisions_do_not_pollute` 中一个 `kind="scope"` 子案例的预期；触发输入保留，其他五种控制的输入和预期保持。不能写成“所有旧断言未变”。原始断言快照与失败日志留在私人证据目录，未加入公开包。

本轮没有迁移或重跑原 89 项历史后端测试，没有宣布原149规格全部通过，没有重新做独立验收。242 方法的通过不替代完整规格覆盖、真实来源／权限／审批验收。

未验证：真实 AI/OAuth、真实附件与来源服务、业务审批、工作日历算法完整能力、Android、报销完整流程、生产级性能及安全、远程部署、持久化迁移与历史回填。完整工作日历输入并不保证算法已支持，候选输出须如实区分能力不足与证据不足。

## 8. 条件发布范围与剩余限制

1. 当前文件树为 241 项：以已审核的 192 文件代码快照为基线，恢复用户明确要求的 49 份历史静态素材。两份文档之外，原有 190 文件及9份纯核心保持已审核内容；恢复素材逐项复用原提交的文件对象，不增加业务功能验收声明。
2. Starlette 0.41.3 和 pypdf 5.1.0 的上述已知风险保留；后端间接依赖未完全锁定，全量供应链与许可证审核未完成。本轮不改依赖、锁文件或配置。
3. 原仓库继续公开，保留提交历史。当前版本在 192 文件基线上恢复49份素材，总计241项；其余78个旧文件仍只在历史版本中可访问。不将此更新称为历史删除、秘密清除或全历史审核，不使用强制推送或镜像推送。
4. 浏览器隔离必须在首次打开任何页面前落实；源码目录隔离不能替代浏览器隔离，也不代表应用强制只连本机。
5. 实际监听及五页面仅有经审阅的程序员成功日志，未独立复跑；离线安装、native 构建、进程内接口不能扩展为在线下载／默认构建／实际浏览器链路的独立通过。
6. 生产部署、账户加固、正式业务接入、迁移及门禁解除不属于本次开发预览范围。原仓库更新分支和 PR 与正式业务启用分开；合并及预发布采用明确授权，不自动升级为完整 C02 或迁移准入。

公开候选不需要内部业务未决事项被擅自补定；真实交付／证据／审批／正式历史审计的未决事项继续保持原状态。

## 9. 公开校验与私人证据边界

可公开旁件只含必要相对路径和哈希，不含内部绝对路径、调查资料或整目录日志。此前192文件清单、ZIP、校验旁件及原始日志保持不变，不会被本次素材恢复覆盖，也不得作为当前241文件版本的校验。当前提交的49份素材与原历史文件对象一致，原有190个非文档文件及9份纯核心保持不变。本次没有创建或上传新的Release附件；未来若发布新包，须按当前树重新生成清单、ZIP和校验值。原本地工作区、Git状态及业务数据不被覆盖。
