// per_wave_harness.mjs — run the BUNDLED per-wave Workflow under node with stubbed agents (#1210).
//
// The per-wave Workflow is one self-contained script with a top-level `return` and `await`, so it
// cannot be imported. This harness reads the committed bundle (exactly what the Workflow tool runs),
// demotes `export const meta` to a plain const, and wraps the source in an AsyncFunction whose
// parameters are the runtime globals the script uses: args, agent, parallel, log, phase.
//
// The stubs follow the Workflow runtime's documented failure semantics, because a harness that fails
// differently from the runtime proves nothing about it:
//   - agent() resolves to its result, resolves to null when the subagent dies (a terminal API error,
//     an account limit, a skip), and throws past the budget ceiling. A responder returns null or
//     throws to model each.
//   - parallel() never rejects: a thunk that throws resolves to null in the result array.
//
// USAGE:
//   const { result, error, calls, logs } = await runPerWave({ args, responder })
// `responder(label, prompt)` is consulted first for every agent() call. Return HARNESS_DEFAULT (or
// undefined) to use the default response for that label; return null or throw to model a failure.
// The defaults drive a clean wave end to end: every issue implemented and merged, all four gate
// signals passing, the promotion landing. So a case that changes one node and sees integrated:false
// has shown that node caused it, not that the harness never reached the gate.

import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
// PER_WAVE_BUNDLE points the harness at another bundle, e.g. an older one, to show a case fails there.
export const BUNDLE = process.env.PER_WAVE_BUNDLE || join(HERE, '..', '..', 'skills', 'nextwave', 'per-wave-workflow.bundled.js')

export const HARNESS_DEFAULT = Symbol('harness-default')

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const HEAD = 'a'.repeat(40)

export const DEFAULT_ARGS = {
  waveId: 'W1',
  planId: 'P1',
  targetRepo: 'Example-Org/harness-target',
  targetRepoDir: '/nonexistent/harness-target',
  issues: [1, 2],
  mode: 'auto',
}

function loadBody() {
  const src = readFileSync(BUNDLE, 'utf8')
  if (!/^export const meta = /m.test(src)) throw new Error(`harness: no 'export const meta' in ${BUNDLE}`)
  return src.replace(/^export const meta = /m, 'const meta = ')
}

export async function runPerWave({ args = DEFAULT_ARGS, responder = () => HARNESS_DEFAULT } = {}) {
  const calls = []
  const logs = []
  let flightsSinceMerge = [] // issues the flights since the last reconcile implemented

  const defaultFor = (label) => {
    if (label === 'rehydrate') return { merged: [], pending: [...args.issues], reworkCount: {}, idleRounds: 0, groupsRun: 0 }
    if (label.startsWith('kahuna-bootstrap:')) return { ready: true, created: true, head_sha: HEAD.slice(0, 12) }
    if (label.startsWith('plan:')) return { done: false, group: [...args.issues] }
    if (label.startsWith('worktrees:')) return { worktrees: {} }
    if (label.startsWith('flight:#')) {
      const issue = Number(label.slice('flight:#'.length))
      flightsSinceMerge.push(issue)
      return { issue, status: 'implemented' }
    }
    if (label.startsWith('merge:')) {
      const merged = flightsSinceMerge
      flightsSinceMerge = []
      return { merged, needs_rework: [], suite_summary: 'harness: green' }
    }
    if (label.startsWith('persist:')) return { persisted: true }
    if (label.startsWith('cleanup:')) return { cleaned: true }
    if (label === 'gate:open-pr') return { opened: true, pr_number: 99, pr_ref: '#99' }
    if (label === 'gate:commutativity') return { signal: 'commutativity', passed: true, detail: 'harness: commutes' }
    if (label === 'gate:ci') return { pr_number: 99, head_sha: HEAD, head_sha_final: HEAD, wait: { ok: true, final_status: 'success' } }
    if (label === 'gate:review:stage') return { staged: true, workspaceDir: '/nonexistent/ws', changedFiles: ['a.js'] }
    if (label === 'gate:review') return { signal: 'review', passed: true, detail: 'harness: clean' }
    if (label === 'gate:trivy') return { signal: 'trivy', passed: true, found: 1, ingested: 1, unscanned: [], declared: false }
    if (label === 'promote') return { promoted: true, mr_ref: '#99' }
    throw new Error(`harness: no default response for agent label '${label}' — add one`)
  }

  const agent = async (prompt, opts = {}) => {
    const label = opts.label || '(unlabelled)'
    calls.push({ label, prompt })
    const got = await responder(label, prompt)
    return got === HARNESS_DEFAULT || got === undefined ? defaultFor(label) : got
  }
  const parallel = (thunks) => Promise.all(thunks.map((t) => Promise.resolve().then(t).catch(() => null)))
  const log = (m) => { logs.push(String(m)) }
  const phase = () => {}

  const run = new AsyncFunction('args', 'agent', 'parallel', 'log', 'phase', loadBody())
  try {
    return { result: await run(args, agent, parallel, log, phase), error: null, calls, logs }
  } catch (error) {
    return { result: null, error, calls, logs }
  }
}
