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
//   - Once the token budget is spent, EVERY later agent() call throws, not just one. The
//     `exhaustBudgetAt` option models that: from the first call whose label starts with it, all
//     agent() calls throw.
//   - Date.now(), argless new Date() and Math.random() throw (they would break resume). The body is
//     handed shadowed Date and Math that throw the same way, so a future edit that calls one fails
//     here as it would in the runtime.
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

// The runtime's Date and Math, as the script sees them: deterministic use works, the clock and
// randomness throw.
const forbidden = (what) => () => { throw new Error(`${what} is unavailable in a Workflow (it would break resume)`) }
class WorkflowDate extends Date {
  constructor(...a) {
    if (a.length === 0) forbidden('new Date()')()
    super(...a)
  }
  static now() { return forbidden('Date.now()')() }
}
const WorkflowMath = Object.create(Math, { random: { value: forbidden('Math.random()') } })

// `source` replaces the bundle's body, for a test that proves a stub can fail.
export async function runPerWave({ args = DEFAULT_ARGS, responder = () => HARNESS_DEFAULT, exhaustBudgetAt = null, source = null } = {}) {
  const calls = []
  const logs = []
  const flightHeads = {} // issue → the head_sha its latest flight returned (default or responder)
  let budgetSpent = false

  const defaultFor = (label, prompt) => {
    if (label === 'rehydrate') return { merged: [], pending: [...args.issues], reworkCount: {}, idleRounds: 0, groupsRun: 0 }
    if (label.startsWith('kahuna-bootstrap:')) return { ready: true, created: true, head_sha: HEAD.slice(0, 12) }
    if (label.startsWith('plan:')) return { done: false, group: [...args.issues] }
    if (label.startsWith('worktrees:')) return { worktrees: {} }
    if (label.startsWith('flight:#')) {
      const issue = Number(label.slice('flight:#'.length))
      // A full SHA unique to the issue, and unlike the 'N'.repeat(40) heads the rework cases use.
      return { issue, status: 'implemented', head_sha: issue.toString(16).padStart(40, 'e') }
    }
    // #1356: the flight CI node defaults to green on the head its flight returned.
    if (label.startsWith('flight-ci:#')) {
      const issue = Number(label.slice('flight-ci:#'.length))
      const head_sha = flightHeads[issue]
      return { issue, pr_number: 100 + issue, head_sha, head_sha_final: head_sha, wait: { ok: true, final_status: 'success', sha: head_sha } }
    }
    // Reconcile merges every flight its prompt lists (#1356: only the CI-green ones are listed).
    if (label.startsWith('merge:')) {
      const merged = [...String(prompt).matchAll(/^ {3}- issue #(\d+):/gm)].map((m) => Number(m[1]))
      return { merged, needs_rework: [], suite_summary: 'harness: green' }
    }
    if (label.startsWith('persist:')) return { persisted: true }
    if (label.startsWith('cleanup:')) return { cleaned: true }
    if (label === 'gate:open-pr') return { opened: true, pr_number: 99, pr_ref: '#99' }
    if (label === 'gate:commutativity') return { signal: 'commutativity', passed: true, detail: 'harness: commutes' }
    if (label === 'gate:ci') return { pr_number: 99, head_sha: HEAD, head_sha_final: HEAD, target_sha: 'b'.repeat(40), wait: { ok: true, final_status: 'success', sha: HEAD } }
    if (label === 'gate:review:stage') return { staged: true, workspaceDir: '/nonexistent/ws', changedFiles: ['a.js'] }
    if (label === 'gate:review') return { signal: 'review', passed: true, detail: 'harness: clean' }
    if (label === 'gate:trivy') return { signal: 'trivy', passed: true, found: 1, ingested: 1, unscanned: [], declared: false, scanned_sha: HEAD, kahuna_sha: HEAD }
    // An sdlc v5.2.0 pr_merge: it echoes the pin it was given (#1356 review).
    if (label === 'promote') return { promoted: true, merged: true, mr_ref: '#99', pinned_head_sha: String(prompt).match(/expected_head_sha="([0-9a-f]{40})"/)?.[1], merge_commit_sha: 'c'.repeat(40) }
    throw new Error(`harness: no default response for agent label '${label}' — add one`)
  }

  const agent = async (prompt, opts = {}) => {
    const label = opts.label || '(unlabelled)'
    calls.push({ label, prompt })
    if (exhaustBudgetAt !== null && label.startsWith(exhaustBudgetAt)) budgetSpent = true
    if (budgetSpent) throw new Error('budget exhausted: the turn token target is spent')
    const got = await responder(label, prompt)
    let res = got === HARNESS_DEFAULT || got === undefined ? defaultFor(label, prompt) : got
    // A reconcile result that leaves out `merges` gets the proof an sdlc v5.2.0 pr_merge returns for
    // each issue it names merged: the merge commit, and the graded head from the prompt echoed as the
    // pin (#1356 review). A test of an older server sets `merges` itself.
    if (label.startsWith('merge:') && res && typeof res === 'object' && Array.isArray(res.merged) && !('merges' in res)) {
      const heads = Object.fromEntries([...String(prompt).matchAll(/^ {3}- issue #(\d+):.*, graded head ([0-9a-f]{40})$/gm)].map((m) => [Number(m[1]), m[2]]))
      res = { ...res, merges: res.merged.filter((n) => heads[n]).map((n) => ({ issue: n, merged: true, merge_commit_sha: 'd'.repeat(40), pinned_head_sha: heads[n] })) }
    }
    if (label.startsWith('flight:#') && res && typeof res === 'object') flightHeads[Number(label.slice('flight:#'.length))] = res.head_sha
    return res
  }
  const parallel = (thunks) => Promise.all(thunks.map((t) => Promise.resolve().then(t).catch(() => null)))
  const log = (m) => { logs.push(String(m)) }
  const phase = () => {}

  const run = new AsyncFunction('args', 'agent', 'parallel', 'log', 'phase', 'Date', 'Math', source ?? loadBody())
  try {
    return { result: await run(args, agent, parallel, log, phase, WorkflowDate, WorkflowMath), error: null, calls, logs }
  } catch (error) {
    return { result: null, error, calls, logs }
  }
}
