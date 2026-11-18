import test from 'node:test'
import assert from 'node:assert/strict'
import { createAuditApi } from '../src/api/auditClient.js'
import { formatAuditNumber, withAuditDisclosure } from '../src/utils/auditPresentation.js'

test('concurrent initial queries use a single frozen run', async () => {
  const calls = []
  const api = createAuditApi(async req => {
    calls.push(req)
    return { report_meta: { run_id: req.params?.run_id || 'first' } }
  })
  await Promise.all([api.procedures(), api.findings(), api.workpaper()])
  assert.equal(calls.filter(c => !c.params?.run_id).length, 1)
  assert.ok(calls.filter(c => c.url !== '/audit/report').every(c => c.params.run_id === 'first'))
  assert.ok(calls.every(c => c.headers['X-Audit-Contract'] === 'b002-p0-v1'))
})

test('old row details remain on old run after an explicit new run', async () => {
  const calls = []
  const api = createAuditApi(async req => {
    calls.push(req)
    return { report_meta: { run_id: req.url === '/audit/run' ? 'new' : (req.params?.run_id || 'old') } }
  })
  const old = await api.findings()
  await api.run()
  await api.findingDetail('F001', old.report_meta.run_id)
  assert.equal(calls.at(-1).params.run_id, 'old')
  await api.workpaper()
  assert.equal(calls.at(-1).params.run_id, 'new')
})

test('missing frozen snapshot propagates error without new calculation', async () => {
  let calls = 0
  const api = createAuditApi(async req => {
    calls++
    if (req.params?.run_id) throw new Error('snapshot missing')
    return { report_meta: { run_id: 'old' } }
  })
  await assert.rejects(api.report(), /snapshot missing/)
  assert.equal(calls, 2)
})

test('unknown numbers are not silently formatted as zero', () => {
  for (const v of [null, undefined, '', NaN]) assert.equal(formatAuditNumber(v), '—')
  assert.equal(formatAuditNumber(0), '0.00')
})

test('exports retain trial, scope and version disclosure without mutating rows', () => {
  const rows = [{ amount: 5 }]
  const exported = withAuditDisclosure(rows, { run_id: 'old', business_cutoff: '2026-09-30' })
  assert.match(exported[0].audit_mode, /非正式/)
  assert.equal(exported[0].audit_run_id, 'old')
  assert.equal(exported[0].audit_history_scope, '不可确定')
  assert.equal(exported[0].audit_traceability, '受限')
  assert.deepEqual(rows, [{ amount: 5 }])
})
