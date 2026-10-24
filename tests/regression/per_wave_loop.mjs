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

// ── rework (#1213) ────────────────────────────────────────────────────────────────────────────
// paresieve P3W3: reconcile sent a flight back with the exact fix, and the rework flight returned
// already-present on the same head, because its old commit was still on the branch and its prompt
// never carried the reason. Serialized (one issue per round): round 1 builds #31 at H1 and reconcile
// sends it back with REASON; round 2 is #31's rework flight, which returns `second`.
const H1 = '1'.repeat(40)
const H2 = '2'.repeat(40)
const REASON = 'REWORK-REASON-SENTINEL: pin the ZIP mtime to UTC'
function reworkScenario(second, merge2 = null) {
  let flights31 = 0
  return (label) => {
    if (label === 'flight:#31') return ++flights31 === 1 ? { issue: 31, status: 'implemented', head_sha: H1 } : { issue: 31, ...second }
    if (label === 'merge:1') return { merged: [], needs_rework: [{ issue: 31, reason: REASON }] }
    if (label === 'merge:2' && merge2) return merge2
    return HARNESS_DEFAULT
  }
}
const flightPrompts = (calls, n) => calls.filter((c) => c.label === `flight:#${n}`).map((c) => c.prompt)
const terminalBlob = (calls) => JSON.parse(terminalPrompt(calls)[0].match(/\n(\{\n[\s\S]*?\n\})\n/)[1])

await check('a rework dispatch carries the reason and the rejected head; the first dispatch does not', async () => {
  const run = await runPerWave({ args: RETRY_ARGS, responder: reworkScenario({ status: 'implemented', head_sha: H2 }, { merged: [31], needs_rework: [] }) })
  const [first, second] = flightPrompts(run.calls, 31)
  assert.ok(first.includes('IDEMPOTENT RESUME') && !first.includes('REWORK'), 'the first flight gets the resume check')
  assert.ok(second.includes(REASON), 'the rework flight is told the reason')
  assert.ok(second.includes(H1), 'the rework flight is told the rejected head')
  assert.ok(!second.includes('IDEMPOTENT RESUME'), 'the rework flight is not offered the already-present shortcut')
  assert.ok(second.includes('rework_not_applied'), 'the rework flight is offered rework_not_applied')
})

await check('rework returns already-present on the rejected head → rework-noop:#31, never sent to reconcile', async () => {
  const run = await runPerWave({ args: RETRY_ARGS, responder: reworkScenario({ status: 'already-present', head_sha: H1 }) })
  assertHalted(run, 'rework-noop:#31')
  assert.ok(run.result.haltReason.includes('head 1111111 unchanged'), run.result.haltReason)
  const merge2 = run.calls.find((c) => c.label === 'merge:2')
  assert.ok(merge2 && !merge2.prompt.includes('issue #31'), 'the no-op is not handed to reconcile')
  assert.deepEqual(run.result.reworkCount, { 31: 1 }, 'the no-op dispatch does not count as a rework cycle')
  assert.equal(terminalBlob(run.calls).reworkContext['31'].reason, REASON, 'the held blob keeps the reason for the retry')
})

await check('rework returns "implemented" on the rejected head (abbreviated) → still a no-op', async () => {
  const run = await runPerWave({ args: RETRY_ARGS, responder: reworkScenario({ status: 'implemented', head_sha: H1.slice(0, 12) }) })
  assertHalted(run, 'rework-noop:#31 (head 1111111 unchanged)')
})

await check('rework returns already-present at a NEW head → still a no-op, and the reason does not say "unchanged"', async () => {
  const run = await runPerWave({ args: RETRY_ARGS, responder: reworkScenario({ status: 'already-present', head_sha: H2 }) })
  assertHalted(run, 'rework-noop:#31 (already-present at head 2222222)')
  assert.ok(!run.result.haltReason.includes('unchanged'), run.result.haltReason)
})

// Fanned out, a no-op leaves its group: the sibling still merges, and whatever reconcile claims about
// the no-op it was never given is ignored, so it neither merges nor counts as another rework cycle.
await check('fan: a no-op rework next to a sibling — the sibling merges, reconcile\'s claims about the no-op are ignored', async () => {
  let flights31 = 0
  const run = await runPerWave({
    args: { ...RETRY_ARGS, issues: [31, 33, 35], dispatch: 'fan' },
    responder: (label) => {
      if (label === 'flight:#31') return ++flights31 === 1 ? { issue: 31, status: 'implemented', head_sha: H1 } : { issue: 31, status: 'already-present', head_sha: H1 }
      if (label === 'merge:1') return { merged: [33], needs_rework: [{ issue: 31, reason: REASON }] }
      if (label === 'merge:2') return { merged: [35, 31], needs_rework: [{ issue: 31, reason: 'reconcile re-flags it anyway' }] }
      return HARNESS_DEFAULT
    },
  })
  assertHalted(run, 'rework-noop:#31')
  const merge2 = run.calls.find((c) => c.label === 'merge:2').prompt
  assert.ok(merge2.includes('issue #35') && !merge2.includes('issue #31'), 'only the sibling goes to reconcile')
  assert.deepEqual([...run.result.merged].sort((a, b) => a - b), [33, 35], 'the sibling merged; the no-op did not')
  assert.deepEqual(run.result.reworkCount, { 31: 1 }, 'the re-flag of a no-op is not another rework cycle')
  assert.ok(run.logs.some((l) => l.includes('ignoring reconcile') && l.includes('#31')), 'the ignored claim is logged')
})

await check('rework returns rework_not_applied → halts with its reason', async () => {
  const run = await runPerWave({ args: RETRY_ARGS, responder: reworkScenario({ status: 'rework_not_applied', not_applied_reason: 'the fix needs a schema change' }) })
  assertHalted(run, 'rework-noop:#31 (the fix needs a schema change)')
})

await check('rework returns a new head → reconciled and merged; the spent context is dropped', async () => {
  const run = await runPerWave({ args: RETRY_ARGS, responder: reworkScenario({ status: 'implemented', head_sha: H2 }, { merged: [31], needs_rework: [] }) })
  assert.equal(run.error, null, `the run threw: ${run.error?.stack || run.error}`)
  assert.ok(run.calls.find((c) => c.label === 'merge:2').prompt.includes('issue #31'), 'the rework goes to reconcile')
  assert.equal(run.result.integrated, true)
  assert.deepEqual([...run.result.merged].sort((a, b) => a - b), [31, 33])
  assert.deepEqual(run.result.reworkCount, { 31: 1 })
  assert.deepEqual(terminalBlob(run.calls).reworkContext, {}, 'a merged issue keeps no rework context')
})

await check('a first-time flight that returns already-present still goes to reconcile (resume is unchanged)', async () => {
  const run = await runPerWave({
    responder: only({ 'flight:#1': { issue: 1, status: 'already-present', head_sha: H1 }, 'merge:1': { merged: [1], needs_rework: [] } }),
  })
  assert.equal(run.error, null, `the run threw: ${run.error?.stack || run.error}`)
  assert.ok(run.calls.find((c) => c.label === 'merge:1').prompt.includes('issue #1'))
  assert.equal(run.result.integrated, true)
})

await check('reconcile_applied_fix is recorded in concerns and returned as reconcileAppliedFixes', async () => {
  const fix = { issue: 1, summary: 'pinned the ZIP mtime to UTC in the packer' }
  const run = await runPerWave({ responder: only({ 'merge:1': { merged: [1], needs_rework: [], reconcile_applied_fix: [fix] } }) })
  assert.equal(run.error, null, `the run threw: ${run.error?.stack || run.error}`)
  assert.deepEqual(run.result.reconcileAppliedFixes, [fix])
  assert.ok(run.result.concerns.some((c) => c.issue === 1 && c.concern === `reconcile_applied_fix: ${fix.summary}`), JSON.stringify(run.result.concerns))
  assert.ok(run.calls.find((c) => c.label === 'merge:1').prompt.includes('reconcile_applied_fix'), 'reconcile is told to record such a fix')
})

await check('a resumed run hands the rework flight the persisted reason and head', async () => {
  const run = await runPerWave({
    args: RETRY_ARGS,
    responder: only({ rehydrate: rehydrated({ reworkCount: { 31: 1 }, reworkContext: { 31: { reason: REASON, head: H1 } } }) }),
  })
  const [first] = flightPrompts(run.calls, 31)
  assert.ok(first.includes(REASON) && first.includes(H1), 'the first flight after a resume is the rework, with its context')
  assert.ok(!flightPrompts(run.calls, 33)[0].includes('REWORK'), 'an issue with no context gets the ordinary prompt')
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

// ── CI wait budget (#1302) ────────────────────────────────────────────────────────────────────
// The budget reaches the live gate:ci prompt; a rejected one falls back to 420 and says so.
const ciPrompt = (run) => run.calls.find((c) => c.label === 'gate:ci').prompt
const budgetLog = (run) => run.logs.filter((l) => l.startsWith('[#1302]'))
const BUDGET_ARGS = { waveId: 'W1', planId: 'P1', targetRepo: 'Example-Org/harness-target', targetRepoDir: '/nonexistent/harness-target', issues: [1, 2], mode: 'auto' }

await check('ciWaitSec 1800 → the gate:ci prompt waits 1800s, nothing logged', async () => {
  const run = await runPerWave({ args: { ...BUDGET_ARGS, ciWaitSec: 1800 } })
  assert.equal(run.error, null, `the run threw: ${run.error?.stack || run.error}`)
  assert.match(ciPrompt(run), /timeout_sec=1800 \+ poll_interval_sec=15/)
  assert.deepEqual(budgetLog(run), [])
})

await check('no ciWaitSec → the gate:ci prompt waits 420s, nothing logged', async () => {
  const run = await runPerWave({ args: BUDGET_ARGS })
  assert.match(ciPrompt(run), /timeout_sec=420 \+ poll_interval_sec=15/)
  assert.deepEqual(budgetLog(run), [])
})

for (const bad of ['1800 s', '1800', 99999, 30]) {
  await check(`ciWaitSec ${JSON.stringify(bad)} → falls back to 420 and logs why`, async () => {
    const run = await runPerWave({ args: { ...BUDGET_ARGS, ciWaitSec: bad } })
    assert.equal(run.error, null, `the run threw: ${run.error?.stack || run.error}`)
    assert.match(ciPrompt(run), /timeout_sec=420 \+ poll_interval_sec=15/)
    const logged = budgetLog(run)
    assert.equal(logged.length, 1, `expected one [#1302] log line, got ${JSON.stringify(run.logs)}`)
    assert.ok(logged[0].includes(`ciWaitSec=${JSON.stringify(bad)}`), logged[0])
    assert.ok(logged[0].includes('CI wait budget'), 'the log points at the line to fix')
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
