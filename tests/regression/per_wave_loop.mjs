// per_wave_loop.mjs — the per-wave Workflow's loop and gate, executed (#1210).
//
// Runs the bundled Workflow through per_wave_harness.mjs and pins what a failed agent node does.
// A failed plan or reconcile agent used to throw a TypeError and kill the run with no verdict and
// no terminal disposition (paresieve Plan #5, wave P1W3: "null is not an object (evaluating
// 'rec.concerns')"). Both are now legal exits: gate SKIPPED, integrated:false, a named haltReason,
// and persist:terminal run with disposition "held".
//
// The baseline case runs the defaults end to end and must integrate. Every other case changes one
// node, so an integrated:false there was caused by that node.

import assert from 'node:assert/strict'
import { runPerWave, HARNESS_DEFAULT } from './per_wave_harness.mjs'

let failures = 0
async function check(name, fn) {
  try {
    await fn()
    console.log(`  [PASS] ${name}`)
  } catch (e) {
    failures++
    console.log(`  [FAIL] ${name}\n         ${String(e?.message || e).split('\n').join('\n         ')}`)
  }
}

// A responder that changes only the labels in `over`; a value may be a function (to throw).
const only = (over) => (label) => {
  for (const [key, value] of Object.entries(over)) {
    const hit = key.endsWith('*') ? label.startsWith(key.slice(0, -1)) : label === key
    if (hit) return typeof value === 'function' ? value(label) : value
  }
  return HARNESS_DEFAULT
}
const terminalPrompt = (calls) => calls.filter((c) => c.label === 'persist:terminal').map((c) => c.prompt)

// A halted run: no throw, gate SKIPPED, not integrated, a named reason, and a held terminal record.
function assertHalted(run, reasonPrefix) {
  assert.equal(run.error, null, `the run threw: ${run.error?.stack || run.error}`)
  assert.equal(run.result.gate, 'SKIPPED')
  assert.equal(run.result.integrated, false)
  assert.ok(String(run.result.haltReason).startsWith(reasonPrefix), `haltReason was '${run.result.haltReason}'`)
  // The reason the campaign surfaces leads with the halt; a halt before dispatch adds why (#1204).
  assert.ok(String(run.result.reason).startsWith(run.result.haltReason), `reason was '${run.result.reason}'`)
  const term = terminalPrompt(run.calls)
  assert.equal(term.length, 1, 'persist:terminal runs exactly once')
  assert.ok(term[0].includes('Disposition: "held"'), 'persist:terminal records disposition held')
  assert.ok(term[0].includes(reasonPrefix), 'the held detail names the failure')
  assert.ok(!run.calls.some((c) => c.label.startsWith('gate:') || c.label === 'promote'), 'a halted wave never reaches the gate')
}

console.log('per_wave_loop (#1210)')
console.log('──────────────────────────────────────────')

// The harness's own stubs must be able to fail the way the runtime does, or every case below could
// pass on a script the runtime would kill.
for (const [what, body] of [['Date.now()', 'return Date.now()'], ['new Date()', 'return new Date()'], ['Math.random()', 'return Math.random()']]) {
  await check(`harness: ${what} throws, as in the runtime`, async () => {
    const run = await runPerWave({ source: body })
    assert.ok(run.error && run.error.message.includes(what), `expected ${what} to throw, got ${run.error ?? run.result}`)
  })
}
await check('harness: deterministic Date and Math still work', async () => {
  const run = await runPerWave({ source: "return [new Date('2026-10-24T00:00:00Z').toISOString(), Math.max(1, 2)]" })
  assert.equal(run.error, null, String(run.error))
  assert.deepEqual(run.result, ['2026-10-24T00:00:00.000Z', 2])
})

await check('baseline: the defaults run a clean wave end to end and integrate', async () => {
  const run = await runPerWave()
  assert.equal(run.error, null, `the run threw: ${run.error?.stack || run.error}`)
  assert.equal(run.result.gate, 'PASS')
  assert.equal(run.result.integrated, true)
  assert.deepEqual([...run.result.merged].sort(), [1, 2])
  assert.ok(terminalPrompt(run.calls)[0].includes('Disposition: "promoted"'))
})

// ── reconcile ─────────────────────────────────────────────────────────────────────────────────
await check('reconcile returns null → reconcile agent failed: agent returned no result', async () => {
  const run = await runPerWave({ responder: only({ 'merge:*': null }) })
  assertHalted(run, 'reconcile agent failed: agent returned no result')
})

await check('reconcile throws → the error text is the reason', async () => {
  const run = await runPerWave({ responder: only({ 'merge:*': () => { throw new Error("You've hit your weekly limit") } }) })
  assertHalted(run, "reconcile agent failed: You've hit your weekly limit")
})

await check('reconcile returns {} → reconcile agent failed: schema-invalid result', async () => {
  const run = await runPerWave({ responder: only({ 'merge:*': {} }) })
  assertHalted(run, 'reconcile agent failed: schema-invalid result')
})

await check('reconcile fails in round 2 → round 1 stays merged, the failed round is not recorded', async () => {
  // dispatch is absent → serialize, so each round is one issue: round 1 merges #1, round 2 fails.
  const run = await runPerWave({ responder: only({ 'merge:2': null }) })
  assertHalted(run, 'reconcile agent failed')
  assert.deepEqual(run.result.merged, [1])
  assert.deepEqual(run.result.pending, [2])
  assert.equal(run.result.groups, 1, 'the failed round is not pushed to groupsRun')
  const blob = JSON.parse(terminalPrompt(run.calls)[0].match(/\n(\{\n[\s\S]*?\n\})\n/)[1])
  assert.deepEqual(blob.merged, [1], 'the terminal blob a fresh run rehydrates from keeps round 1')
  assert.deepEqual(blob.pending, [2])
})

// ── plan ──────────────────────────────────────────────────────────────────────────────────────
await check('plan returns null → plan agent failed: agent returned no result', async () => {
  const run = await runPerWave({ responder: only({ 'plan:*': null }) })
  assertHalted(run, 'plan agent failed: agent returned no result')
})

await check('plan throws → the error text is the reason', async () => {
  const run = await runPerWave({ responder: only({ 'plan:*': () => { throw new Error('subagent refused') } }) })
  assertHalted(run, 'plan agent failed: subagent refused')
})

// The budget is not one failed call: every agent() after it throws, persist:terminal included. The
// honest outcome is the verdict and a soft-failed terminal write, and no durable hold record.
await check('budget spent at the plan → SKIPPED with the reason, terminal write soft-fails, no throw', async () => {
  const run = await runPerWave({ exhaustBudgetAt: 'plan:' })
  assert.equal(run.error, null, `the run threw: ${run.error?.stack || run.error}`)
  assert.equal(run.result.gate, 'SKIPPED')
  assert.equal(run.result.integrated, false)
  assert.ok(String(run.result.haltReason).startsWith('plan agent failed: budget exhausted'), `haltReason was '${run.result.haltReason}'`)
  assert.ok(run.logs.some((l) => l.includes('persistTerminal soft-fail')), 'the terminal write was attempted and soft-failed')
})

await check('budget spent at the reconcile → SKIPPED with the reason, no throw', async () => {
  const run = await runPerWave({ exhaustBudgetAt: 'merge:' })
  assert.equal(run.error, null, `the run threw: ${run.error?.stack || run.error}`)
  assert.equal(run.result.gate, 'SKIPPED')
  assert.ok(String(run.result.haltReason).startsWith('reconcile agent failed: budget exhausted'), `haltReason was '${run.result.haltReason}'`)
})

await check('plan returns {} → plan agent failed: schema-invalid result', async () => {
  const run = await runPerWave({ responder: only({ 'plan:*': {} }) })
  assertHalted(run, 'plan agent failed: schema-invalid result')
})

await check('plan says done → still the impasse halt, not a plan failure', async () => {
  const run = await runPerWave({ responder: only({ 'plan:*': { done: true, group: [] } }) })
  assertHalted(run, 'impasse')
})

// ── retries (#1204) ───────────────────────────────────────────────────────────────────────────
// paresieve Plan #5, wave P1W2: the blob after a thrash exit. A retry must dispatch, not halt on a
// counter from the previous run; the per-issue rework count and the lifetime group bound carry over.
const RETRY_ARGS = { waveId: 'P1W2', planId: 'P5', targetRepo: 'Example-Org/harness-target', targetRepoDir: '/nonexistent/harness-target', issues: [31, 33], mode: 'auto' }
const rehydrated = (over) => ({ merged: [], pending: [31, 33], reworkCount: {}, idleRounds: 0, groupsRun: 0, ...over })

await check('retry after thrash (saved idleRounds:2) → dispatches flights instead of halting', async () => {
  const run = await runPerWave({ args: RETRY_ARGS, responder: only({ rehydrate: rehydrated({ idleRounds: 2, reworkCount: { 31: 2 }, groupsRun: 2 }) }) })
  assert.equal(run.error, null, `the run threw: ${run.error?.stack || run.error}`)
  assert.ok(run.calls.some((c) => c.label.startsWith('flight:#')), `no flight dispatched; labels: ${run.calls.map((c) => c.label).join(' ')}`)
  assert.equal(run.result.exitedBeforeDispatch, false)
  assert.equal(run.result.integrated, true, 'the recoverable wave integrates')
})

await check('saved reworkCount {31:3} + reconcile flags #31 → rework:#31 after exactly one group', async () => {
  const run = await runPerWave({
    args: RETRY_ARGS,
    responder: only({
      rehydrate: rehydrated({ reworkCount: { 31: 3 } }),
      'merge:*': { merged: [], needs_rework: [{ issue: 31, reason: 'interface break' }] },
    }),
  })
  assertHalted(run, 'rework:#31')
  assert.equal(run.result.haltReason, 'rework:#31')
  assert.equal(run.calls.filter((c) => c.label.startsWith('plan:')).length, 1, 'exactly one group was planned')
  assert.equal(run.result.exitedBeforeDispatch, false)
})

await check('resumed at groupsRun:24 → runaway before dispatch, and the reason says so', async () => {
  const run = await runPerWave({ args: RETRY_ARGS, responder: only({ rehydrate: rehydrated({ groupsRun: 24 }) }) })
  assertHalted(run, 'runaway')
  assert.equal(run.result.haltReason, 'runaway', 'halt keeps its string')
  assert.equal(run.result.loopOutcome, 'runaway', 'loopOutcome keeps its string')
  assert.equal(run.result.exitedBeforeDispatch, true)
  assert.ok(run.result.reason.includes('exited before dispatching any group this run (resumed groupsRun=24, maxGroups=24)'), run.result.reason)
  assert.ok(!run.calls.some((c) => c.label.startsWith('flight:#')))
})

await check('a reconcile failure in round 1 is NOT "before dispatch" — its flights ran', async () => {
  const run = await runPerWave({ responder: only({ 'merge:*': null }) })
  assertHalted(run, 'reconcile agent failed')
  assert.equal(run.result.exitedBeforeDispatch, false)
  assert.ok(!run.result.reason.includes('exited before dispatching'), run.result.reason)
})

await check('a plan failure in round 1 IS "before dispatch"; on a cold start the reason claims no resume', async () => {
  const run = await runPerWave({ responder: only({ 'plan:*': null }) })
  assertHalted(run, 'plan agent failed')
  assert.equal(run.result.exitedBeforeDispatch, true)
  assert.ok(run.result.reason.endsWith('exited before dispatching any group this run'), run.result.reason)
})

// The bound the per-run counter relies on: within a run, MAX_IDLE empty rounds still trip thrash,
// and every empty round still spends the lifetime groupsRun, so a stuck wave reaches runaway.
await check('a stuck retry still trips thrash in-run, and spends the lifetime groupsRun bound', async () => {
  const run = await runPerWave({
    args: RETRY_ARGS,
    responder: only({ rehydrate: rehydrated({ idleRounds: 2, groupsRun: 20 }), 'merge:*': { merged: [], needs_rework: [] } }),
  })
  assertHalted(run, 'thrash')
  assert.equal(run.result.haltReason, 'thrash')
  assert.equal(run.result.exitedBeforeDispatch, false)
  assert.equal(run.calls.filter((c) => c.label.startsWith('plan:')).length, 2, 'MAX_IDLE (2) empty rounds, counted from 0')
  const blob = JSON.parse(terminalPrompt(run.calls)[0].match(/\n(\{\n[\s\S]*?\n\})\n/)[1])
  assert.equal(blob.groupsRun, 22, 'both empty rounds are spent from the lifetime bound')
})

// runaway is checked before thrash, so the retry after that one runs out of lifetime first.
await check('the next stuck retry (resumed at groupsRun:22) halts runaway, not thrash', async () => {
  const run = await runPerWave({
    args: RETRY_ARGS,
    responder: only({ rehydrate: rehydrated({ groupsRun: 22 }), 'merge:*': { merged: [], needs_rework: [] } }),
  })
  assertHalted(run, 'runaway')
  assert.equal(run.result.haltReason, 'runaway')
  assert.equal(run.calls.filter((c) => c.label.startsWith('plan:')).length, 2, 'two rounds reach MAX_GROUPS (24)')
})

// ── the null sweep: every other dereferenced agent result ─────────────────────────────────────
// Nodes after the gate decision cannot block integration, and the flight loop's soft-fail seams
// carry on, so for those the claim is only "no throw". The gate and promote nodes must also leave
// the wave not integrated.
const MUST_NOT_INTEGRATE = ['gate:open-pr', 'gate:commutativity', 'gate:ci', 'gate:review:stage', 'gate:review', 'gate:trivy', 'promote']
const MUST_NOT_THROW = ['rehydrate', 'worktrees:*', 'flight:*', 'persist:*', 'cleanup:*']

for (const label of MUST_NOT_INTEGRATE) {
  await check(`${label} returns null → no throw, not integrated`, async () => {
    const run = await runPerWave({ responder: only({ [label]: null }) })
    assert.equal(run.error, null, `the run threw: ${run.error?.stack || run.error}`)
    assert.equal(run.result.integrated, false)
    assert.equal(terminalPrompt(run.calls).length, 1, 'persist:terminal still runs')
    assert.ok(terminalPrompt(run.calls)[0].includes('Disposition: "held"'))
  })
}

for (const label of MUST_NOT_THROW) {
  await check(`${label} returns null → no throw, and the run still ends with a verdict`, async () => {
    const run = await runPerWave({ responder: only({ [label]: null }) })
    assert.equal(run.error, null, `the run threw: ${run.error?.stack || run.error}`)
    assert.ok(['PASS', 'HOLD', 'SKIPPED'].includes(run.result.gate), `gate was '${run.result.gate}'`)
  })
}

// The one deliberate throw: a wave whose integration branch could not be established refuses to run
// before anything writes, rather than fail later and less clearly (#1052).
await check('kahuna-bootstrap returns null → refuses loudly before any write', async () => {
  const run = await runPerWave({ responder: only({ 'kahuna-bootstrap:*': null }) })
  assert.ok(run.error && /could not establish the wave's integration branch/.test(run.error.message), `error was: ${run.error}`)
  assert.ok(!run.calls.some((c) => /^(plan|flight|merge|persist|gate):/.test(c.label)), 'nothing ran after the bootstrap')
})

console.log('')
if (failures) {
  console.log(`  ${failures} failure(s)`)
  process.exit(1)
}
console.log('  all checks passed')
