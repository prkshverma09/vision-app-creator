import { createServer } from 'node:http'
import { readFile, stat, mkdtemp } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { spawnSync } from 'node:child_process'
import { extname, join, normalize } from 'node:path'

const root = new URL('../dist/', import.meta.url).pathname
const fixtureRoot = new URL('../../../fixtures/synthetic/video/', import.meta.url).pathname
const app = { id: 'app-e2e', name: 'Untitled app', spec: null, source: null, calibration_id: null, seed_asset_id: null, published_version_id: null, requires_calibration: true, analysis_mode: 'scripted' }
const spec = {
  kind: 'tracked_rules', schema_version: '1.0', title: 'Red light crossing',
  objective: 'Detect vehicles crossing during a red signal',
  evidence_policy: { before_ms: 3000, after_ms: 3000 }, approved_action_refs: [],
  limits: { max_duration_ms: 300000, max_model_calls: 10 },
  rules: [{ rule_id: 'red-crossing', capability_id: 'tracked.red_phase_crossing', object_classes: ['car', 'truck'] }],
}
const event = {
  id: 'event-e2e', run_id: 'run-e2e', attempt_id: 'attempt-e2e', spec_version_id: 'version-e2e',
  calibration_id: 'calibration-e2e', source_range: { start_ms: 500, end_ms: 900 }, rule_id: 'red-crossing',
  track_refs: ['track-1'], facts: { object_class: 'car' },
  evidence: { requested_range: { start_ms: 250, end_ms: 1200 }, actual_range: { start_ms: 250, end_ms: 1200 }, clip_ref: 'clip-e2e', thumbnail_ref: 'thumb-e2e', clipped_start: false, clipped_end: false, state: 'available' },
  machine_decision: 'supported', human_review: 'unreviewed', revision: 1,
}
const assets = new Map()
const runs = new Map()
const polls = new Map()
const videos = new Map()
const videoDir = await mkdtemp(join(tmpdir(), 'vision-e2e-media-'))
let created = false
const json = (res, value, status = 200) => { res.writeHead(status, { 'content-type': 'application/json' }); res.end(JSON.stringify(value)) }
const body = async req => { const chunks = []; for await (const chunk of req) chunks.push(chunk); return chunks.length ? JSON.parse(Buffer.concat(chunks)) : {} }
const reset = () => { app.name = 'Untitled app'; app.spec = null; app.source = null; app.calibration_id = null; app.seed_asset_id = null; app.published_version_id = null; created = false; assets.clear(); runs.clear(); polls.clear(); event.human_review = 'unreviewed'; event.facts = { object_class: 'car' } }

createServer(async (req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1:4173')
  if (url.pathname === '/__e2e/reset' && req.method === 'POST') { reset(); return json(res, { ok: true }) }
  if (url.pathname === '/v1/runtime') return json(res, { analysis_mode: 'scripted', provider: 'scripted', model: null, configured: true, external_processing: false, limits: { max_duration_ms: 300000, max_bytes: 100000000 } })
  if (url.pathname === '/v1/apps' && req.method === 'GET') return json(res, { apps: created ? [app] : [] })
  if (url.pathname === '/v1/apps' && req.method === 'POST') { reset(); created = true; return json(res, app) }
  if (url.pathname === `/v1/apps/${app.id}` && req.method === 'GET') return json(res, app)
  if (url.pathname === `/v1/apps/${app.id}/turns` && req.method === 'POST') {
    const input = await body(req)
    if (/face|identity|recogn/i.test(input.message ?? '')) return json(res, { reply: 'Identity recognition is excluded for privacy and safety.', outcome: { kind: 'unsupported_request', code: 'unsupported_capability', reason: 'Identity recognition is excluded' } })
    return json(res, { reply: 'I created a supported red-light crossing policy.', outcome: { kind: 'proposed_version', version: spec } })
  }
  if (url.pathname === `/v1/apps/${app.id}/versions` && req.method === 'POST') { app.spec = (await body(req)).spec; return json(res, app) }
  if (url.pathname === '/v1/uploads' && req.method === 'POST') {
    const { filename } = await body(req)
    const index = assets.size + 1
    const id = index === 1 ? 'asset-e2e' : `asset-e2e-${index}`
    assets.set(id, { asset_id: id, status: 'ready', duration_ms: 5000, width: 320, height: 180, filename, playback_url: `/fixture-${index}.webm` })
    return json(res, { upload_id: id, upload_url: `/v1/upload-bytes/${id}` })
  }
  if (url.pathname.startsWith('/v1/upload-bytes/') && req.method === 'PUT') { for await (const _ of req) { /* consume fixture */ } res.writeHead(204); return res.end() }
  if (/^\/v1\/uploads\/[^/]+\/complete$/.test(url.pathname) && req.method === 'POST') return json(res, assets.get(url.pathname.split('/')[3]))
  if (url.pathname === `/v1/apps/${app.id}/source` && req.method === 'POST') {
    const input = await body(req)
    app.source = assets.get(input.asset_id)
    app.seed_asset_id ??= input.asset_id
    app.calibration_id = null
    await new Promise(resolve => setTimeout(resolve, 100))
    return json(res, app)
  }
  if (url.pathname === `/v1/apps/${app.id}/calibrations` && req.method === 'POST') { app.calibration_id = `calibration-${app.source.asset_id}`; app.published_version_id ??= 'version-e2e'; return json(res, { calibration_id: app.calibration_id, version_id: app.published_version_id }) }
  if (url.pathname === `/v1/apps/${app.id}/runs` && req.method === 'GET') return json(res, { runs: [...runs.values()].map(value => value.run) })
  if (url.pathname === `/v1/apps/${app.id}/runs` && req.method === 'POST') {
    const input = await body(req)
    const source = assets.get(input.asset_id ?? app.source.asset_id)
    const id = runs.size === 0 ? 'run-e2e' : `run-e2e-${runs.size + 1}`
    const run = { id, app_id: app.id, status: 'queued', asset_id: source.asset_id, version_id: app.published_version_id, calibration_id: app.calibration_id, is_seed_run: source.asset_id === app.seed_asset_id, analysis_mode: 'scripted', source: { ...source }, playback_url: source.playback_url, coverage_note: '100% of fixture processed; mocked contract responses, not live accuracy' }
    runs.set(id, { run, events: source.filename === 'green_light_crossing.mp4' ? [] : [{ ...structuredClone(event), run_id: id, calibration_id: app.calibration_id }] })
    polls.set(id, 0)
    return json(res, { run_id: id }, 202)
  }
  if (url.pathname.startsWith('/v1/runs/') && req.method === 'GET') {
    const id = url.pathname.split('/')[3]
    const value = runs.get(id)
    if (!value) return json(res, { message: 'Run not found' }, 404)
    const count = polls.get(id) + 1
    polls.set(id, count)
    value.run.status = count >= 3 ? 'succeeded' : count === 1 ? 'queued' : 'running'
    return json(res, { run: value.run, events: count >= 3 ? value.events : [] })
  }
  if (url.pathname === '/v1/events/event-e2e/review' && req.method === 'POST') { const review = await body(req); const result = runs.get('run-e2e').events[0]; result.human_review = review.human_review; if (review.human_review === 'confirmed_by_user') result.facts = { ...result.facts, action_preview: 'dry-run only; no external request sent', safe_payload: '{"event_id":"event-e2e","decision":"supported"}' }; return json(res, result) }
  if (url.pathname === '/api/v1/media/thumb-e2e') { res.writeHead(200, { 'content-type': 'image/svg+xml' }); return res.end('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="68"><rect width="120" height="68" fill="#22d3ee"/></svg>') }
  if (/^\/fixture-\d+\.webm$/.test(url.pathname) || url.pathname === '/api/v1/media/clip-e2e') {
    const source = [...assets.values()].find(asset => asset.playback_url === url.pathname)
    const filename = source?.filename === 'green_light_crossing.mp4' ? 'green_light_crossing.mp4' : 'red_light_violation.mp4'
    if (!videos.has(filename)) {
      const target = join(videoDir, `${filename}.webm`)
      const result = spawnSync('ffmpeg', ['-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-i', join(fixtureRoot, filename), '-an', '-c:v', 'libvpx', '-f', 'webm', target], { timeout: 30000 })
      if (result.status !== 0) return json(res, { message: `Fixture transcode failed: ${result.stderr}` }, 500)
      videos.set(filename, await readFile(target))
    }
    const data = videos.get(filename)
    const range = /^bytes=(\d+)-(\d*)$/.exec(req.headers.range ?? '')
    if (range) { const start = Number(range[1]); const end = range[2] ? Math.min(Number(range[2]), data.length - 1) : data.length - 1; res.writeHead(206, { 'content-type': 'video/webm', 'accept-ranges': 'bytes', 'content-range': `bytes ${start}-${end}/${data.length}`, 'content-length': end - start + 1 }); return res.end(data.subarray(start, end + 1)) }
    res.writeHead(200, { 'content-type': 'video/webm', 'accept-ranges': 'bytes', 'content-length': data.length }); return res.end(data)
  }
  if (url.pathname.startsWith('/v1/')) return json(res, { code: 'not_found', message: `No mock for ${req.method} ${url.pathname}` }, 404)

  let relative = url.pathname === '/' ? 'index.html' : normalize(url.pathname).replace(/^[/\\]+/, '')
  let file = join(root, relative)
  try { if ((await stat(file)).isDirectory()) file = join(file, 'index.html'); const data = await readFile(file); const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' }; res.writeHead(200, { 'content-type': types[extname(file)] ?? 'application/octet-stream' }); res.end(data) }
  catch { const data = await readFile(join(root, 'index.html')); res.writeHead(200, { 'content-type': 'text/html' }); res.end(data) }
}).listen(4173, '127.0.0.1', () => console.log('e2e-local-contract mock listening on 4173; mocked results are not live accuracy'))
