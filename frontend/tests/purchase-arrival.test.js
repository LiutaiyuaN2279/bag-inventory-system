import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const vue = readFileSync(new URL('../src/views/procurement/arrival.vue', import.meta.url), 'utf8')
const script = vue.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')

// 执行真实页面脚本，仅替代Vue/UI/网络依赖；不重写业务函数。
function page(api = {}) {
  const calls = []; const warnings = []; const created = []
  const context = {
    ref: value => ({ value }), reactive: value => value,
    computed: fn => ({ get value() { return fn() } }), onMounted: () => {},
    applyRouteFilter: () => {}, useSort: () => ({}),
    useBatch: () => ({ clearSelection() {} }), Search: {}, Refresh: {}, Plus: {}, Van: {},
    ElMessage: { warning: m => warnings.push(m), success() {} }, ElMessageBox: {},
    arrivalApi: { list: async () => ({ list: [], total: 0 }), create: async data => created.push(JSON.parse(JSON.stringify(data))) },
    orderApi: {
      list: async params => { calls.push({ ...params }); return api.list?.(params) || { list: [], total: 0 } },
      detail: async id => api.detail?.(id) || { items: [] }
    }, warehouseApi: {}, exportRows() {}, sumBy() {}
  }
  vm.runInNewContext(script + '\n globalThis.result = {onAdd,onOrderChange,onSubmit,form,orders,warehouses,dialog};', context)
  context.result.warehouses.value = [{ id: 1 }]
  context.result.form.actual_receipt_date = "2026-11-01"
  return { ...context.result, calls, warnings, created }
}

test('order picker includes both states past the first page and preserves filterable search', async () => {
  const p = page({ list: ({ status, page, page_size }) => {
    const all = Array.from({ length: 205 }, (_, n) => ({ id: (status === '已审核' ? 0 : 1000) + n, order_no: status + n }))
    return { list: all.slice((page - 1) * page_size, page * page_size), total: all.length }
  } })
  await p.onAdd()
  assert.equal(p.orders.value.length, 410)
  assert.ok(p.orders.value.some(o => o.order_no === '部分到货204'))
  assert.deepEqual([...new Set(p.calls.map(c => c.status))].sort(), ['已审核', '部分到货'].sort())
  for (const status of ['已审核', '部分到货']) assert.ok(p.calls.filter(c => c.status === status).length > 1)
  assert.match(vue, /<el-select[^>]*v-model="form.order_id"[^>]*filterable/)
  assert.ok(p.orders.value.filter(o => o.order_no.includes('204')).length === 2)
})

test('remaining quantity uses arrived including pending receipts and excludes fully arrived lines', async () => {
  const p = page({ detail: () => ({ items: [
    { id: 10, material_id: 1, qty: 100, arrived_qty: 40, inbound_qty: 0 },
    { id: 11, material_id: 1, qty: 50, arrived_qty: 50, inbound_qty: 0 },
    { id: 12, material_id: 2, qty: 20, arrived_qty: 25, inbound_qty: 20 }
  ] }) })
  p.form.order_id = 1
  await p.onOrderChange(1)
  assert.equal(p.form.items.length, 1)
  assert.equal(p.form.items[0].order_item_id, 10)
  assert.equal(p.form.items[0].arrived_qty, 60)
  assert.equal(p.form.items[0].qualified_qty, 60)
  await p.onSubmit()
  assert.deepEqual(p.created[0].items.map(i => [i.order_item_id, i.arrived_qty]), [[10, 60]])
})

test('fully arrived pending order cannot produce an empty submission', async () => {
  const p = page({ detail: () => ({ items: [{ id: 1, qty: 100, arrived_qty: 100 }] }) })
  p.form.order_id = 1
  await p.onOrderChange(1)
  await p.onSubmit()
  assert.equal(p.form.items.length, 0)
  assert.equal(p.created.length, 0)
  assert.ok(p.warnings.length)
})

test('a delivery may omit an unshipped zero row while preserving distinct order item IDs', async () => {
  const p = page({ detail: () => ({ items: [
    { id: 1, material_id: 1, qty: 100, arrived_qty: 0 },
    { id: 2, material_id: 1, qty: 100, arrived_qty: 40 }
  ] }) })
  p.form.order_id = 1
  await p.onOrderChange(1)
  p.form.items[0].arrived_qty = 0
  p.form.items[0].qualified_qty = 0
  await p.onSubmit()
  assert.deepEqual(p.created[0].items.map(i => i.order_item_id), [2])
})

test('invalid negative nonfinite blank and over-remaining quantities are never silently filtered', async () => {
  for (const [field, value] of [['arrived_qty', -1], ['qualified_qty', -1], ['arrived_qty', NaN],
    ['arrived_qty', Infinity], ['arrived_qty', null], ['arrived_qty', ''], ['arrived_qty', 'bad'],
    ['qualified_qty', NaN], ['qualified_qty', null], ['arrived_qty', 61], ['qualified_qty', 61]]) {
    const p = page({ detail: () => ({ items: [{ id: 1, qty: 100, arrived_qty: 40 }] }) })
    p.form.order_id = 1; await p.onOrderChange(1)
    p.form.items[0][field] = value
    await p.onSubmit()
    assert.equal(p.created.length, 0, field + ':' + value)
    assert.ok(p.warnings.length)
  }
})

test('a zero arrival with positive qualified quantity is rejected rather than dropped', async () => {
  const p = page({ detail: () => ({ items: [{ id: 1, qty: 100, arrived_qty: 0 }] }) })
  p.form.order_id = 1; await p.onOrderChange(1)
  p.form.items[0].arrived_qty = 0
  await p.onSubmit()
  assert.equal(p.created.length, 0)
  assert.ok(p.warnings.length)
})

test('clearing order selection clears stale lines without querying a nonexistent order', async () => {
  let detailCalls = 0
  const p = page({ detail: () => { detailCalls++; return { items: [] } } })
  p.form.items.push({ order_item_id: 9 })
  await p.onOrderChange(null)
  assert.equal(detailCalls, 0)
  assert.equal(p.form.items.length, 0)
})

test('continuous units use the existing two-decimal receipt precision', async () => {
  const p = page({ detail: () => ({ items: [{ id: 1, qty: 0.3, arrived_qty: 0.1, unit: '米' }] }) })
  p.form.order_id = 1
  await p.onOrderChange(1)
  assert.equal(p.form.items[0].arrived_qty, 0.2)
  assert.equal(p.form.items[0].qualified_qty, 0.2)
})

test('a delayed response for a previous order cannot overwrite the current selection', async () => {
  let resolveFirst
  const p = page({ detail: id => id === 1 ? new Promise(resolve => { resolveFirst = resolve })
    : { items: [{ id: 22, qty: 100, arrived_qty: 40 }] } })
  p.form.order_id = 1
  const first = p.onOrderChange(1)
  p.form.order_id = 2
  await p.onOrderChange(2)
  resolveFirst({ items: [{ id: 11, qty: 100, arrived_qty: 0 }] })
  await first
  assert.equal(p.form.items[0].order_item_id, 22)
  await p.onSubmit()
  assert.equal(p.created[0].order_id, 2)
  assert.deepEqual(p.created[0].items.map(i => i.order_item_id), [22])
})

