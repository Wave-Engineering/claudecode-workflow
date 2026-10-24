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
  assert.equal(run.result.reason, run.result.haltReason, 'the verdict reason the campaign surfaces is the halt reason')
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
