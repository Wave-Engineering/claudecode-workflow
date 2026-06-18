// gate_signals_roundtrip.mjs — #687 trust-gate seam unit test.
//
// Pins the load-bearing #687 invariants that DON'T need a live sdlc-server (the agent()-driven
// signals — commutativity_verify / ci_wait_run / code-reviewer / trivy — need one; those are
// exercised by a live wave, not here). What IS deterministic and load-bearing:
//   1. conservativeFail() — the production replacement for the always-pass gateSignalStub:
//      a signal that ERRORS returns passed:false (HOLD), NEVER passed:true (SEAMS invariant 6).
//   2. each signal prompt names its REAL sdlc-server tool + the EXACT pass predicate, and is
//      diff-scoped (the §3.4 refinement: changed-files, never the whole tree).
//   3. the CI prompt accepts the GitHub merge-queue "merge_group_validated" shape (#452) so a
//      clean merge-queue wave doesn't spuriously HOLD.
//   4. the promote prompt is wave_finalize → pr_merge(skip_train) → delete-branch (CODE ONLY).

import assert from 'node:assert/strict'
import {
  conservativeFail,
  commutativitySignalPrompt,
  ciSignalPrompt,
  reviewSignalPrompt,
  trivySignalPrompt,
  promotePrompt,
  PROMOTE_RESULT,
} from '../../skills/nextwave-next/gate.js'

let failures = 0
const ok = (name) => console.log(`  [PASS] ${name}`)
const bad = (name, e) => { console.log(`  [FAIL] ${name}: ${e?.message || e}`); failures++ }

console.log('test_gate_signals_roundtrip')
console.log('──────────────────────────────────────────')

const A = { waveId: 'W-7', kahunaBranch: 'kahuna/692-x', protectedBranch: 'main', targetRepo: 'org/repo', targetRepoDir: '/tmp/repo' }

// ── 1. conservative-fail: an errored signal HOLDs, never PASSes ───────────────────────
try {
  for (const sig of ['commutativity', 'ci', 'review', 'trivy']) {
    const r = conservativeFail(sig, new Error('agent crashed'))
    assert.equal(r.signal, sig)
    assert.equal(r.passed, false, `${sig} conservative-fail must be passed:false`)
    assert.match(r.detail, /conservative-fail/i)
  }
  // tolerate non-Error throwables (string / object) without losing the HOLD
  assert.equal(conservativeFail('ci', 'boom').passed, false)
  assert.equal(conservativeFail('ci', { code: 7 }).passed, false)
  assert.equal(conservativeFail('ci', undefined).passed, false)
  ok('conservativeFail always returns passed:false (HOLD, never silent PASS)')
} catch (e) { bad('conservative-fail invariant', e) }

// ── 2. each signal prompt names its real tool + pass predicate + is diff-scoped ───────
try {
  const c = commutativitySignalPrompt(A)
  assert.match(c, /commutativity_verify/)
  assert.match(c, /STRONG/); assert.match(c, /MEDIUM/)
  assert.match(c, /PROBE_UNAVAILABLE/) // the conservative-fail verdict is named
  assert.match(c, new RegExp(A.protectedBranch)) // base_ref is the protected branch
  ok('commutativity prompt: commutativity_verify + STRONG/MEDIUM + PROBE_UNAVAILABLE fail')

  const ci = ciSignalPrompt(A)
  assert.match(ci, /ci_wait_run/)
  assert.match(ci, /MERGE-RESULT/) // #452: merge-result pipeline, not branch HEAD
  assert.match(ci, /NOT the merge-commit branch HEAD/)
  assert.match(ci, /merge_group_validated/) // #452 GitHub merge-queue shape accepted
  assert.match(ci, /changed files/) // diff-scoped (§3.4)
  ok('ci prompt: ci_wait_run on MERGE-RESULT pipeline + merge_group_validated + diff-scoped (#452, §3.4)')

  const rv = reviewSignalPrompt(A)
  assert.match(rv, /worktree/i) // #667: runs on a worktree of kahuna
  assert.match(rv, /CHANGED FILES/) // diff-scoped (§3.4)
  assert.match(rv, /critical/i); assert.match(rv, /important/i) // pass predicate
  ok('review prompt: worktree-of-kahuna + diff-scoped + no critical/important (#667, §3.4)')

  const tv = trivySignalPrompt(A)
  assert.match(tv, /trivy fs --scanners vuln --severity HIGH,CRITICAL/)
  assert.match(tv, /AVAILABLE FIXED VERSION/i) // pass predicate: only fixable vulns fail
  assert.match(tv, /CONSERVATIVE-FAIL/i) // missing trivy = fail, not pass
  ok('trivy prompt: HIGH,CRITICAL + available-fix predicate + conservative-fail if uninstalled')
} catch (e) { bad('signal prompts', e) }

// ── 3. promotion is CODE: wave_finalize → pr_merge(skip_train) → delete-branch ────────
try {
  const p = promotePrompt({ ...A, planId: 692 })
  assert.match(p, /wave_finalize/)
  assert.match(p, /pr_merge/)
  assert.match(p, /skip_train/)
  assert.match(p, /pr_merge_wait/) // merge-queue-enforced fallback: wait for the land
  assert.match(p, /delete/i) // kahuna branch deleted after promotion
  assert.match(p, /692/) // plan_id threaded through
  // promoted:true ONLY if the merge actually landed (no fabricated success)
  assert.match(p, /promoted \(true ONLY if the merge actually landed/)
  ok('promote prompt: wave_finalize → pr_merge(skip_train) → delete-branch, promoted-only-if-landed')

  // PROMOTE_RESULT schema shape
  assert.equal(PROMOTE_RESULT.required[0], 'promoted')
  assert.equal(PROMOTE_RESULT.properties.promoted.type, 'boolean')
  ok('PROMOTE_RESULT requires a boolean `promoted`')
} catch (e) { bad('promotion prompt', e) }

console.log('')
if (failures) { console.log(`  ${failures} assertion group(s) failed`); process.exit(1) }
console.log('  all gate-signal checks passed')
