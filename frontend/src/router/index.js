import { createRouter, createWebHashHistory, RouterView } from 'vue-router'
import { h } from 'vue'
import Layout from '@/layout/index.vue'

// 分组占位组件：仅渲染子路由（用于侧边栏多级菜单）
const GroupView = { render: () => h(RouterView) }

export const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/index.vue'),
    meta: { public: true }
  },
  {
    // 服务器地址配置（APK 首次使用 / 更换后端时进入，无需登录）
    path: '/server',
    name: 'ServerSetup',
    component: () => import('@/views/system/server.vue'),
    meta: { public: true }
  },
  {
    path: '/',
    component: Layout,
    redirect: '/login',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/index.vue'),
        meta: { title: '首页看板', icon: 'Odometer', permission: 'dashboard:view' }
      },
      {
        path: 'basic-data',
        component: GroupView,
        meta: { title: '基础数据', icon: 'Folder' },
        children: [
          {
            path: 'materials',
            name: 'Materials',
            component: () => import('@/views/basic-data/materials.vue'),
            meta: { title: '物料管理', icon: 'Goods', permission: 'basic:material:list' }
          },
          {
            path: 'suppliers',
            name: 'Suppliers',
            component: () => import('@/views/basic-data/suppliers.vue'),
            meta: { title: '供应商管理', icon: 'OfficeBuilding', permission: 'basic:supplier:list' }
          },
          {
            path: 'warehouses',
            name: 'Warehouses',
            component: () => import('@/views/basic-data/warehouses.vue'),
            meta: { title: '仓库管理', icon: 'House', permission: 'basic:warehouse:list' }
          }
        ]
      },
      {
        path: 'procurement',
        component: GroupView,
        meta: { title: '采购管理', icon: 'ShoppingCart' },
        children: [
          { path: 'requisition', name: 'Requisition', component: () => import('@/views/procurement/requisition.vue'), meta: { title: '请购单', icon: 'Document', permission: 'purchase:requisition:list' } },
          { path: 'order', name: 'PurchaseOrder', component: () => import('@/views/procurement/order.vue'), meta: { title: '采购订单', icon: 'Tickets', permission: 'purchase:order:list' } },
          { path: 'arrival', name: 'Arrival', component: () => import('@/views/procurement/arrival.vue'), meta: { title: '到货入库', icon: 'Box', permission: 'purchase:arrival:list' } },
          { path: 'return', name: 'PurchaseReturn', component: () => import('@/views/procurement/preturn.vue'), meta: { title: '采购退货', icon: 'RefreshLeft', permission: 'purchase:return:list' } }
        ]
      },
      {
        path: 'ai-ocr',
        name: 'AiOcr',
        component: () => import('@/views/ai/ocr.vue'),
        meta: { title: 'AI 单据识别', icon: 'MagicStick', permission: 'ai:ocr:list' }
      },
      {
        path: 'inventory',
        component: GroupView,
        meta: { title: '库存管理', icon: 'Coin' },
        children: [
          { path: 'query', name: 'InvQuery', component: () => import('@/views/inventory/query.vue'), meta: { title: '库存查询', icon: 'Search', permission: 'inventory:view' } },
          { path: 'transactions', name: 'InvTxn', component: () => import('@/views/inventory/transactions.vue'), meta: { title: '出入库流水', icon: 'List', permission: 'inventory:view' } },
          { path: 'stocktake', name: 'Stocktake', component: () => import('@/views/inventory/stocktake.vue'), meta: { title: '库存盘点', icon: 'EditPen', permission: 'inventory:stocktake' } },
          { path: 'transfers', name: 'Transfers', component: () => import('@/views/inventory/transfers.vue'), meta: { title: '仓库调拨', icon: 'Sort', permission: 'inventory:view' } },
          { path: 'alert', name: 'InvAlert', component: () => import('@/views/inventory/alert.vue'), meta: { title: '预警看板', icon: 'Bell', permission: 'inventory:alert' } }
        ]
      },
      {
        path: 'bom',
        component: GroupView,
        meta: { title: 'BOM 管理', icon: 'Share' },
        children: [
          { path: 'list', name: 'BomList', component: () => import('@/views/bom/list.vue'), meta: { title: 'BOM 清单', icon: 'Files', permission: 'bom:view' } },
          { path: 'calculate', name: 'BomCalc', component: () => import('@/views/bom/calculate.vue'), meta: { title: 'BOM 算料', icon: 'Operation', permission: 'bom:view' } }
        ]
      },
      {
        path: 'production',
        component: GroupView,
        meta: { title: '生产管理', icon: 'Setting' },
        children: [
          { path: 'outsource', name: 'Outsource', component: () => import('@/views/production/outsource.vue'), meta: { title: '外发加工', icon: 'Van', permission: 'outsource:list' } }
        ]
      },
      {
        path: 'quality',
        component: GroupView,
        meta: { title: '质量管理', icon: 'CircleCheck' },
        children: [
          { path: 'iqc', name: 'Iqc', component: () => import('@/views/quality/iqc.vue'), meta: { title: '来料质检', icon: 'DocumentChecked', permission: 'qc:view' } },
          { path: 'fqc', name: 'Fqc', component: () => import('@/views/quality/fqc.vue'), meta: { title: '成品质检', icon: 'Medal', permission: 'qc:view' } }
        ]
      },
      {
        path: 'reports',
        component: GroupView,
        meta: { title: '报表中心', icon: 'DataAnalysis' },
        children: [
          { path: 'purchase', name: 'ReportPurchase', component: () => import('@/views/reports/purchase.vue'), meta: { title: '采购报表', icon: 'Money', permission: 'report:view' } },
          { path: 'inventory', name: 'ReportInventory', component: () => import('@/views/reports/inventory.vue'), meta: { title: '库存报表', icon: 'Box', permission: 'report:view' } }
        ]
      },
      {
        path: 'audit',
        component: GroupView,
        meta: { title: '智能审计', icon: 'Cpu' },
        children: [
          { path: 'dashboard', name: 'AuditDashboard', component: () => import('@/views/audit/dashboard.vue'), meta: { title: '审计工作台', icon: 'Odometer', permission: 'audit:view' } },
          { path: 'findings', name: 'AuditFindings', component: () => import('@/views/audit/findings.vue'), meta: { title: '审计发现', icon: 'Warning', permission: 'audit:view' } },
          { path: 'workflow', name: 'AuditWorkflow', component: () => import('@/views/audit/workflow.vue'), meta: { title: '作业执行流程', icon: 'Operation', permission: 'audit:view' } },
          { path: 'workpaper', name: 'AuditWorkpaper', component: () => import('@/views/audit/workpaper.vue'), meta: { title: '审计工作底稿', icon: 'Document', permission: 'audit:view' } }
        ]
      },
      {
        // 费用报销：侧边栏只放「列表 / 填写 / 待制证 / 凭证列表 / 复核 / 制度」六个入口。
        // 详情、编辑、判读、AI 制证等按 id 打开的功能页统一挂在下方 /rmb 路由树下——
        // layout 的菜单是遍历本路由表自动生成的，且不识别 meta.hidden，
        // 若把带 :id 的页面放进来会渲染成点不开的菜单项。
        path: 'reimburse',
        component: GroupView,
        meta: { title: '费用报销', icon: 'Wallet' },
        children: [
          { path: 'list', name: 'RmbList', component: () => import('@/views/reimburse/index.vue'), meta: { title: '报销单', icon: 'Document', permission: 'reimburse:bill:list' } },
          { path: 'new', name: 'RmbNew', component: () => import('@/views/reimburse/edit.vue'), meta: { title: '填写报销单', icon: 'EditPen', permission: 'reimburse:bill:add' } },
          { path: 'voucher/pending', name: 'RmbVoucherPending', component: () => import('@/views/reimburse/voucher-list.vue'), meta: { title: '待制证', icon: 'Tickets', permission: 'reimburse:voucher:make' } },
          { path: 'voucher/list', name: 'RmbVoucherList', component: () => import('@/views/reimburse/voucher-list.vue'), meta: { title: '凭证列表', icon: 'Files', permission: 'reimburse:voucher:list' } },
          { path: 'voucher/review', name: 'RmbVoucherReview', component: () => import('@/views/reimburse/voucher-review.vue'), meta: { title: '凭证复核', icon: 'Finished', permission: 'reimburse:voucher:review' } },
          { path: 'policy', name: 'RmbPolicy', component: () => import('@/views/reimburse/policy.vue'), meta: { title: '制度管理', icon: 'Setting', permission: 'reimburse:policy:manage' } }
        ]
      },
      {
        path: 'system',
        component: GroupView,
        meta: { title: '系统管理', icon: 'Tools' },
        children: [
          { path: 'users', name: 'Users', component: () => import('@/views/system/users.vue'), meta: { title: '用户管理', icon: 'User', permission: 'system:user:list' } },
          { path: 'roles', name: 'Roles', component: () => import('@/views/system/roles.vue'), meta: { title: '角色权限管理', icon: 'Key', permission: 'system:role:list' } },
          { path: 'logs', name: 'OpLogs', component: () => import('@/views/system/logs.vue'), meta: { title: '操作日志', icon: 'List', permission: 'system:log' } },
          { path: 'excel', name: 'ExcelIO', component: () => import('@/views/system/excel.vue'), meta: { title: '导入导出', icon: 'Download', permission: 'inventory:view' } }
        ]
      }
    ]
  },
  {
    // 费用报销功能页（按 id 打开，不进侧边栏）。
    // 单独挂一层 Layout 树，是为了不复用 layout 的菜单渲染逻辑——菜单只遍历上面 / 的 children，
    // 这里的路由仍包在 Layout 内，所以顶栏、面包屑、页面骨架都照常工作。
    path: '/rmb',
    component: Layout,
    redirect: '/reimburse/list',
    children: [
      { path: 'bill/:id', name: 'RmbDetail', component: () => import('@/views/reimburse/detail.vue'), meta: { title: '报销单详情', permission: 'reimburse:bill:list' } },
      { path: 'bill/:id/edit', name: 'RmbEdit', component: () => import('@/views/reimburse/edit.vue'), meta: { title: '修改报销单', permission: 'reimburse:bill:edit' } },
      { path: 'compliance/:id', name: 'RmbCompliance', component: () => import('@/views/reimburse/compliance.vue'), meta: { title: '合规判读', permission: 'reimburse:check:run' } },
      { path: 'voucher/new/:rid', name: 'RmbVoucherNew', component: () => import('@/views/reimburse/voucher-edit.vue'), meta: { title: 'AI 制证', permission: 'reimburse:voucher:make' } },
      { path: 'voucher/:id/edit', name: 'RmbVoucherEdit', component: () => import('@/views/reimburse/voucher-edit.vue'), meta: { title: '修改凭证', permission: 'reimburse:voucher:make' } },
      { path: 'voucher/:id', name: 'RmbVoucherDetail', component: () => import('@/views/reimburse/voucher-detail.vue'), meta: { title: '凭证详情', permission: 'reimburse:voucher:list' } }
    ]
  },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

export default router
