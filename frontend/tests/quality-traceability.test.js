import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { formatAuditNumber } from '../src/utils/auditPresentation.js'

const iqcVue = readFileSync(new URL('../src/views/quality/iqc.vue', import.meta.url), 'utf8')
const script = iqcVue.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
function qualityPage() {
  const calls = []; const warnings = []
  const context = {
    computed: fn => ({ get value() { return fn() } }), reactive: x => x, ref: x => ({ value: x }),
    onMounted() {}, applyRouteFilter() {}, useSort: () => ({}), useBatch: () => ({}),
    Search: {}, Refresh: {}, Plus: {}, DocumentChecked: {}, exportRows() {},
    ElMessage: { warning: x => warnings.push(x), success() {} },
    materialApi: {}, supplierApi: {},
    arrivalApi: {
      list: async () => ({ list: [{ id: 1, actual_receipt_date: '2026-11-01' }, { id: 2 }], total: 2 }),
      detail: async () => ({ supplier_id: 1, items: [{ id: 11, material_id: 2, material_name: '合成物料', arrived_qty: 100 }] })
    },
    qualityApi: {
      iqcList: async () => ({ list: [], total: 0 }),
      iqcCreate: async data => calls.push(['create', JSON.parse(JSON.stringify(data))]),
      iqcDetail: async () => ({ arrival_id: 1, inspection_date: '2026-11-01', release_status: '未放行',
        items: [{ id: 3, arrival_item_id: 11, material_id: 2, material_name: '合成物料', arrived_qty: 100,
                  declared_qualified_qty: 100, sample_qty: 0, qualified_qty: 0, accepted_qty: null, result: '待检' }] }),
      iqcCheck: async (id, data) => calls.push(['check', id, JSON.parse(JSON.stringify(data))]),
      iqcRelease: async (id, data) => calls.push(['release', id, JSON.parse(JSON.stringify(data))])
    }
  }
  vm.runInNewContext(script + '\nglobalThis.result = {onAdd,onArrivalChange,onSubmit,onCheck,saveCheck,onRelease,saveRelease,form,check,release,arrivals,batchActions};', context)
  return { ...context.result, calls, warnings }
}

test('new IQC binds real arrival item IDs and excludes legacy date-less options', async () => {
  const p = qualityPage(); await p.onAdd()
  assert.deepEqual(Array.from(p.arrivals.value, x => x.id), [1])
  p.form.arrival_id = 1; await p.onArrivalChange(1); await p.onSubmit()
  assert.deepEqual(p.calls[0][1], { arrival_id: 1, supplier_id: 1, items: [{ arrival_item_id: 11, material_id: 2 }] })
})

test('inspection never defaults pending to pass or sample to whole accepted quantity', async () => {
  const p = qualityPage(); await p.onCheck({ id: 1 })
  assert.equal(p.check.items[0].result, '')
  assert.equal(p.check.items[0].accepted_qty, null)
  assert.equal(p.check.items[0].arrived_qty, 100)
  await p.saveCheck(); assert.equal(p.calls.length, 0)
  p.check.inspection_date = '2026-11-01'
  Object.assign(p.check.items[0], { sample_qty: 1, qualified_qty: 1, accepted_qty: 100, result: '合格' })
  await p.saveCheck()
  assert.equal(p.calls[0][2].items[0].sample_qty, 1)
  assert.equal(p.calls[0][2].items[0].accepted_qty, 100)
  assert.equal(p.calls[0][2].inspection_date, '2026-11-01')
  assert.ok(p.batchActions.every(a => a.key === 'export'))
})

test('release is separate, exposes its exact scope and requires explicit date and basis', async () => {
  const p = qualityPage(); await p.onRelease({ id: 1 })
  assert.equal(p.release.items[0].arrival_item_id, 11)
  assert.equal(p.release.items[0].declared_qualified_qty, 100)
  assert.equal(p.release.inspection_date, '2026-11-01')
  await p.saveRelease(); assert.equal(p.calls.length, 0)
  p.release.release_date = '2026-11-02'; p.release.release_basis = '明确整批接收依据'
  await p.saveRelease()
  assert.deepEqual(p.calls[0], ['release', 1, { release_date: '2026-11-02', release_basis: '明确整批接收依据' }])
})

const ocrVue = readFileSync(new URL('../src/views/ai/ocr.vue', import.meta.url), 'utf8')
const onImport = ocrVue.match(/async function onImport\(archiveOnly\) \{[\s\S]*?\n\}/)[0]
function ocrPage(date) {
  const calls = []; const warnings = []
  const context = {
    dialog: { record: { id: 1 }, visible: true, form: { order_id: 9, warehouse_id: 8, actual_receipt_date: date } },
    saving: { value: '' }, buildItemsPayload: () => [{ material_id: 1, qty: 100 }],
    ElMessage: { warning: x => warnings.push(x), success() {} }, ElMessageBox: { confirm: async () => {} },
    aiOcrApi: { importRecord: async (id, data) => { calls.push({ ...data }); return {} } }, fetchRecords() {}
  }
  vm.runInNewContext(onImport + '\nglobalThis.invoke = onImport;', context)
  return { invoke: context.invoke, calls, warnings }
}

test('OCR arrival import requires a manual date and passes it without using document dates', async () => {
  const missing = ocrPage(null); await missing.invoke(false)
  assert.equal(missing.calls.length, 0); assert.ok(missing.warnings.length)
  const p = ocrPage('2026-11-01'); await p.invoke(false)
  assert.equal(p.calls[0].actual_receipt_date, '2026-11-01')
})

test('OCR archive-only clears arrival routing even if an order and warehouse remain selected', async () => {
  const p = ocrPage(null); await p.invoke(true)
  assert.equal(p.calls[0].order_id, null)
  assert.equal(p.calls[0].warehouse_id, null)
  assert.equal(p.calls[0].actual_receipt_date, null)
})

test('real finding template expressions distinguish reliable zero and unknown', () => {
  const vue = readFileSync(new URL('../src/views/audit/findings.vue', import.meta.url), 'utf8')
  for (const subject of ['row.amount', 'detail.data.amount']) {
    const expression = [...vue.matchAll(/\{\{([^{}]*?)\}\}/g)].map(m => m[1]).find(x => x.includes(subject) && x.includes('fmt('))
    assert.ok(expression)
    const evaluate = amount => vm.runInNewContext(expression, { row: { amount }, detail: { data: { amount } }, fmt: formatAuditNumber })
    assert.equal(evaluate(0), '¥ 0.00')
    assert.equal(evaluate(null), '—')
    assert.equal(evaluate(undefined), '—')
  }
  assert.match(vue, /未提供独立AI建议/)
  assert.match(vue, /未记录人工确认/)
  assert.match(vue, /单号匹配/)
  assert.match(vue, /truncated/)
})

