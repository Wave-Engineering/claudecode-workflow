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
  openPromotionPrPrompt,
  OPEN_PR_RESULT,
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
const PR = 4242 // the draft promotion PR the gate opens (#5); threaded into ci + promote

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
  assert.match(c, /ORACLE_REQUIRED/) // #6: gate HOLDs on ORACLE_REQUIRED (named explicitly)
  assert.match(c, new RegExp(A.protectedBranch)) // base_ref is the protected branch
  ok('commutativity prompt: commutativity_verify + STRONG/MEDIUM + PROBE_UNAVAILABLE + ORACLE_REQUIRED fail (#6)')

  const ci = ciSignalPrompt({ ...A, prNumber: PR })
  assert.match(ci, /ci_wait_run/)
  assert.match(ci, /MERGE-RESULT/) // #452: merge-result pipeline, not branch HEAD
  assert.match(ci, /NOT the merge-commit branch HEAD/)
  assert.match(ci, /merge_group_validated/) // #452 GitHub merge-queue shape accepted
  assert.match(ci, /changed files/) // diff-scoped (§3.4)
  assert.match(ci, new RegExp(`PR #${PR}`)) // #5: waits on the gate-opened draft PR by number
  assert.match(ci, /do NOT search for it/i) // #5: deterministic, no race to "find" the PR
  ok('ci prompt: ci_wait_run on the gate-opened PR (#5) + MERGE-RESULT + merge_group_validated + diff-scoped (#452, §3.4)')

  // #5 — the gate opens the kahuna→protected DRAFT PR FIRST (before the signals)
  const op = openPromotionPrPrompt({ ...A, planId: 692 })
  assert.match(op, /wave_finalize/) // opens the kahuna→protected MR
  assert.match(op, /DRAFT/) // as a draft (can't auto-merge before the gate decides)
  assert.match(op, /idempotent/i) // re-open returns the existing PR
  assert.match(op, /do NOT merge/i) // PR-open node never merges
  assert.match(op, /692/) // plan_id threaded through
  assert.equal(OPEN_PR_RESULT.required[0], 'opened')
  assert.equal(OPEN_PR_RESULT.properties.opened.type, 'boolean')
  assert.equal(OPEN_PR_RESULT.properties.pr_number.type, 'integer')
  ok('open-pr prompt: wave_finalize DRAFT, idempotent, never merges; OPEN_PR_RESULT requires boolean opened (#5)')

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

// ── 3. promotion is CODE: mark-ready → pr_merge(skip_train) → delete-branch (#5) ───────
// #5: promotion no longer OPENS a PR (the gate's PR-OPEN node already did) — it marks the
// existing draft PR ready and merges it. It must reference the PR number, never wave_finalize.
try {
  const p = promotePrompt({ ...A, prNumber: PR })
  assert.doesNotMatch(p, /wave_finalize/) // #5: promote does NOT open a PR anymore
  assert.match(p, new RegExp(`PR #${PR}`)) // merges the gate-opened draft PR by number
  assert.match(p, /already open/i) // the PR is already open (the gate opened it)
  assert.match(p, /pr ready|mark it ready/i) // un-draft the existing PR before merging
  assert.match(p, /pr_merge/)
  assert.match(p, /skip_train/)
  assert.match(p, /pr_merge_wait/) // merge-queue-enforced fallback: wait for the land
  assert.match(p, /delete/i) // kahuna branch deleted after promotion
  // promoted:true ONLY if the merge actually landed (no fabricated success)
  assert.match(p, /promoted \(true ONLY if the merge actually landed/)
  ok('promote prompt: mark-ready → pr_merge(skip_train) → delete-branch, merges the gate-opened PR, promoted-only-if-landed (#5)')

  // PROMOTE_RESULT schema shape
  assert.equal(PROMOTE_RESULT.required[0], 'promoted')
  assert.equal(PROMOTE_RESULT.properties.promoted.type, 'boolean')
  ok('PROMOTE_RESULT requires a boolean `promoted`')
} catch (e) { bad('promotion prompt', e) }

console.log('')
if (failures) { console.log(`  ${failures} assertion group(s) failed`); process.exit(1) }
console.log('  all gate-signal checks passed')
