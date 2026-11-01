// C07/C-031: keep one frozen run across lists, details and workpapers.
export function createAuditApi(request) {
  const send = req => request({ ...req, headers: { ...req.headers, 'X-Audit-Contract': 'b002-p0-v1' } })
  let activeRunId = null
  let initial = null
  function remember(data) {
    if (!data?.report_meta?.run_id) throw new Error('试算版本信息缺失，请检查服务版本')
    activeRunId = data.report_meta.run_id
    return data
  }
  async function ensureRun() {
    if (activeRunId) return activeRunId
    if (!initial) {
      initial = send({ url: '/audit/report', method: 'get' }).then(remember).finally(() => { initial = null })
    }
    await initial
    return activeRunId
  }
  async function read(url, params = {}) {
    const runId = params.run_id || await ensureRun()
    return send({ url, method: 'get', params: { ...params, run_id: runId } })
  }
  return {
    config: () => send({ url: '/audit/config', method: 'get' }),
    run: async () => { if (initial) await initial; return remember(await send({ url: '/audit/run', method: 'post' })) },
    report: () => read('/audit/report'),
    procedures: () => read('/audit/procedures'),
    findings: (params = {}) => read('/audit/findings', params),
    findingDetail: (id, runId) => read(`/audit/findings/${encodeURIComponent(id)}`, runId ? { run_id: runId } : {}),
    workpaper: () => read('/audit/workpaper'),
  }
}
