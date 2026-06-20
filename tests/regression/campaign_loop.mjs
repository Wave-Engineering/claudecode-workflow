// campaign_loop.mjs — #749 deterministic campaign loop, pure-core unit tests.
//
// Run by tests/regression/test_campaign_loop.sh (picked up by scripts/ci/validate.sh).
// Tests the DETERMINISTIC behaviour (#749 Test Procedures) by injecting scripted runWave/judge
// fakes into runCampaign — no real Workflow/agent, so the loop's advance/hold routing is a pure,
// fast unit test.

import {
  parseArgs,
  computePending,
  waveIdOf,
  routeVerdict,
  routeJudgment,
  runCampaign,
  waveOversightPrompt,
  JUDGMENT_RESULT,
} from '../../skills/nextwave/campaign-loop.js'

let passed = 0
let failed = 0
function ok(cond, msg) {
  if (cond) {
    passed++
    console.log(`  [PASS] ${msg}`)
  } else {
    failed++
    console.error(`  [FAIL] ${msg}`)
  }
}

console.log('campaign_loop — #749 deterministic loop')
console.log('──────────────────────────────────────────')

// ── parseArgs ────────────────────────────────────────────────────────────────
ok(JSON.stringify(parseArgs(null)) === '{}', 'parseArgs(null) → {}')
ok(parseArgs('{"a":1}').a === 1, 'parseArgs(JSON string) → object')
ok(parseArgs({ a: 2 }).a === 2, 'parseArgs(object) → passthrough')
let threw = false
try { parseArgs('not json') } catch { threw = true }
ok(threw, 'parseArgs(non-JSON string) throws (fail-loud, not silent {})')

// ── waveIdOf / computePending (cold-start rehydrate + prune) ──────────────────
ok(waveIdOf('wave-3') === 'wave-3', 'waveIdOf(bare id)')
ok(waveIdOf({ id: 'wave-4', issues: [1] }) === 'wave-4', 'waveIdOf(object .id)')
ok(waveIdOf({ waveId: 'wave-5' }) === 'wave-5', 'waveIdOf(object .waveId)')

const allWaves = [{ id: 'wave-1' }, { id: 'wave-2' }, { id: 'wave-3' }, { id: 'wave-4' }]
const pendingAfterReboot = computePending(allWaves, ['wave-1', 'wave-2'])
ok(pendingAfterReboot.map(waveIdOf).join(',') === 'wave-3,wave-4', 'computePending prunes promoted, preserves order (reboot at wave 3)')
ok(computePending(allWaves, []).length === 4, 'computePending([]) → all pending (fresh campaign)')
ok(computePending(allWaves, ['wave-1', 'wave-2', 'wave-3', 'wave-4']).length === 0, 'computePending(all promoted) → none (closed campaign)')
// idempotent: same promoted set → same pending
ok(JSON.stringify(computePending(allWaves, ['wave-1'])) === JSON.stringify(computePending(allWaves, ['wave-1'])), 'computePending is idempotent')

// ── routeVerdict ──────────────────────────────────────────────────────────────
ok(routeVerdict({ gate: 'PASS', promoted: true }).advance === true, 'routeVerdict PASS+promoted → advance')
ok(routeVerdict({ gate: 'PASS', promoted: false }).advance === false, 'routeVerdict PASS+!promoted → HOLD (promoted≠delivered)')
ok(routeVerdict({ gate: 'HOLD' }).advance === false, 'routeVerdict HOLD → hold')
ok(routeVerdict({ gate: 'SKIPPED' }).advance === false, 'routeVerdict SKIPPED → hold')
ok(routeVerdict({}).advance === false, 'routeVerdict {} → hold (conservative)')

// ── routeJudgment ─────────────────────────────────────────────────────────────
ok(routeJudgment({ continue: true }).advance === true, 'routeJudgment continue:true → advance')
ok(routeJudgment({ continue: false, concern: { what: 'drift' } }).advance === false, 'routeJudgment continue:false → hold')
ok(routeJudgment({}).advance === false, 'routeJudgment {} → hold (absence is not a continue)')
ok(routeJudgment(null).advance === false, 'routeJudgment null → hold')

// ── runCampaign — the loop driver (injected fakes) ───────────────────────────
async function main() {
  const pass = { gate: 'PASS', promoted: true }
  const cont = { continue: true }

  // 1. multi-wave, all PASS+promoted+continue → completed
  let r = await runCampaign({
    pending: [{ id: 'w1' }, { id: 'w2' }, { id: 'w3' }],
    runWave: async () => pass,
    judge: async () => cont,
  })
  ok(r.outcome === 'completed' && r.wavesAdvanced.join(',') === 'w1,w2,w3', 'runCampaign: all advance → completed (3 waves)')

  // 2. ends on a HOLD verdict at wave 2 (gate did not pass)
  r = await runCampaign({
    pending: [{ id: 'w1' }, { id: 'w2' }, { id: 'w3' }],
    runWave: async (w) => (waveIdOf(w) === 'w2' ? { gate: 'HOLD' } : pass),
    judge: async () => cont,
  })
  ok(r.outcome === 'held' && r.heldAt === 'w2' && r.wavesAdvanced.join(',') === 'w1', 'runCampaign: HOLD verdict at w2 → held, only w1 advanced')

  // 3. ends on a judgment FLAG at wave 2 (gate passed, oversight flagged)
  r = await runCampaign({
    pending: [{ id: 'w1' }, { id: 'w2' }, { id: 'w3' }],
    runWave: async () => pass,
    judge: async (w) => (waveIdOf(w) === 'w2' ? { continue: false, concern: { what: 'accumulating drift in auth' } } : cont),
  })
  ok(r.outcome === 'held' && r.heldAt === 'w2' && /drift in auth/.test(r.heldReason), 'runCampaign: judgment flag at w2 → held with concern reason')
  ok(r.wavesAdvanced.join(',') === 'w1', 'runCampaign: judgment flag → only w1 advanced (w2 recorded but not advanced)')

  // 4. PASS-but-not-promoted holds (promoted ≠ delivered)
  r = await runCampaign({
    pending: [{ id: 'w1' }, { id: 'w2' }],
    runWave: async (w) => (waveIdOf(w) === 'w1' ? { gate: 'PASS', promoted: false, reason: 'interactive' } : pass),
    judge: async () => cont,
  })
  ok(r.outcome === 'held' && r.heldAt === 'w1', 'runCampaign: PASS-not-promoted at w1 → held immediately')

  // 5. a throwing runWave becomes a conservative HOLD, never a crash
  r = await runCampaign({
    pending: [{ id: 'w1' }],
    runWave: async () => { throw new Error('spine boom') },
    judge: async () => cont,
  })
  ok(r.outcome === 'held' && /spine boom/.test(r.heldReason), 'runCampaign: runWave throw → conservative hold (no crash)')

  // 6. a throwing judge becomes a conservative HOLD
  r = await runCampaign({
    pending: [{ id: 'w1' }],
    runWave: async () => pass,
    judge: async () => { throw new Error('judge boom') },
  })
  ok(r.outcome === 'held' && /judge boom/.test(r.heldReason), 'runCampaign: judge throw → conservative hold')

  // 7. closed campaign (no pending) → completed, nothing advanced (provably terminates)
  r = await runCampaign({ pending: [], runWave: async () => pass, judge: async () => cont })
  ok(r.outcome === 'completed' && r.wavesAdvanced.length === 0, 'runCampaign: empty pending → completed (terminates, no stall)')

  // 8. judge is called with the cross-wave context (accumulation needs the whole trajectory)
  let seenContext = null
  await runCampaign({
    pending: [{ id: 'w1' }, { id: 'w2' }],
    runWave: async () => pass,
    judge: async (w, ctx) => { if (waveIdOf(w) === 'w2') seenContext = ctx; return cont },
  })
  ok(seenContext && seenContext.completed.length === 1 && seenContext.remaining.length === 0 && seenContext.index === 1,
    'runCampaign: judge receives cross-wave context (completed + remaining + index)')

  // ── prompt + schema sanity ──
  const prompt = waveOversightPrompt({ justLanded: { wave: 'w2' }, trajectory: [{ wave: 'w1', gate: 'PASS' }], remainingPlan: ['w3'], intentTier: 'devspec' })
  ok(/ACCUMULATION/.test(prompt) && /INTENT-DRIFT/.test(prompt) && /devspec/.test(prompt), 'waveOversightPrompt encodes the §4 lens + intent tier')
  ok(JUDGMENT_RESULT.required.includes('continue') && JUDGMENT_RESULT.additionalProperties === false, 'JUDGMENT_RESULT schema requires continue, no extra props')

  console.log('')
  if (failed > 0) {
    console.error(`  ${failed} check(s) failed`)
    process.exit(1)
  }
  console.log(`  all ${passed} campaign-loop checks passed`)
}

main().catch((e) => { console.error(`  [FAIL] uncaught: ${e?.stack || e}`); process.exit(1) })
