import request from '@/utils/request'

export const reportApi = {
  purchaseBySupplier: (params) => request({ url: '/reports/purchase-by-supplier', method: 'get', params }),
  purchaseByMaterial: (params) => request({ url: '/reports/purchase-by-material', method: 'get', params }),
  purchaseSupplierDetail: (params) => request({ url: '/reports/purchase-supplier-detail', method: 'get', params }),
  purchaseOrderDetail: (params) => request({ url: '/reports/purchase-order-detail', method: 'get', params }),
  purchaseMaterialDetail: (params) => request({ url: '/reports/purchase-material-detail', method: 'get', params }),
  inventorySummary: () => request({ url: '/reports/inventory-summary', method: 'get' }),
  inventoryMaterialDetail: (params) => request({ url: '/reports/inventory-material-detail', method: 'get', params }),
  inventoryTrend: (params) => request({ url: '/reports/inventory-trend', method: 'get', params }),
  dashboard: () => request({ url: '/reports/dashboard', method: 'get' }),
  workbench: () => request({ url: '/reports/workbench', method: 'get' })
}
