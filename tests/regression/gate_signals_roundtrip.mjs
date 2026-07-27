// gate_signals_roundtrip.mjs — #687 trust-gate seam unit test.
//
// Pins the load-bearing #687 invariants that DON'T need a live sdlc-server (the agent()-driven
// signals — commutativity_verify / ci_wait_run / code-reviewer / trivy — need one; those are
// exercised by a live wave, not here). What IS deterministic and load-bearing:
//   1. conservativeFail() — the production replacement for the always-pass gateSignalStub:
//      a signal that ERRORS returns passed:false (HOLD), NEVER passed:true (SEAMS invariant 6).
//   2. each signal prompt names its REAL sdlc-server tool + the EXACT pass predicate, and is
//      diff-scoped (the §3.4 refinement: changed-files, never the whole tree).
//   3. the CI prompt's pass predicate is final_status == "success" and nothing else (#898).
//   4. the promote prompt is wave_finalize → pr_merge → delete-branch (CODE ONLY), and reports
//      promoted ONLY once the merge is observable on the integration base.

import assert from 'node:assert/strict'
import {
  conservativeFail,
  openPromotionPrPrompt,
  OPEN_PR_RESULT,
  commutativitySignalPrompt,
  ciSignalPrompt,
  reviewStagePrompt,
  REVIEW_STAGE,
  reviewSignalPrompt,
  trivySignalPrompt,
  promotePrompt,
  PROMOTE_RESULT,
} from '../../skills/nextwave/gate.js'

let failures = 0
const ok = (name) => console.log(`  [PASS] ${name}`)
const bad = (name, e) => { console.log(`  [FAIL] ${name}: ${e?.message || e}`); failures++ }

console.log('test_gate_signals_roundtrip')
console.log('──────────────────────────────────────────')

// #1052: the gate's merge target is `integrationBase`, NOT `protectedBranch`. Inside a campaign the
// base is the campaign branch and the protected branch is written exactly once, by the campaign's
// release gate — so the fixture uses a CAMPAIGN branch. A stray `main` in any gate prompt is a real
// failure: it would mean a wave prompt hard-codes trunk instead of honoring the base it was handed.
const A = { waveId: 'W-7', kahunaBranch: 'kahuna/692-x', integrationBase: 'campaign/692-x', targetRepo: 'org/repo', targetRepoDir: '/tmp/repo' }
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
  assert.match(c, new RegExp(A.integrationBase.replace('/', '\\/'))) // base_ref is the INTEGRATION BASE (#1052)
  assert.ok(!/base_ref=undefined/.test(c), 'base_ref must never render undefined (a renamed param silently voids the probe scope)')
  ok('commutativity prompt: commutativity_verify + STRONG/MEDIUM + PROBE_UNAVAILABLE + ORACLE_REQUIRED fail (#6)')

  const ci = ciSignalPrompt({ ...A, prNumber: PR })
  assert.match(ci, /ci_wait_run/)
  assert.match(ci, /MERGE-RESULT/) // #452: merge-result pipeline, not branch HEAD
  assert.match(ci, /NOT the merge-commit branch HEAD/)
  assert.match(ci, /final_status == "success"/) // the ONLY pass shape
  // #476: the gate must REQUIRE a merge-result pipeline. Without this flag the tool
  // will happily grade a branch pipeline — or a SKIPPED one, which GitLab normalizes
  // to "success" — as though it validated the merge. That is a silent false PASS on
  // the only thing standing between an autonomous wave and the integration base.
  assert.match(ci, /require_merge_result=true/)
  // #476: the freshness anchor. Without pr_number the tool cannot prove the run it
  // grades belongs to the CURRENT head — a green merge-result run for a PREVIOUS
  // commit would satisfy the gate and merge code CI never saw.
  assert.match(ci, /pr_number=/)
  assert.match(ci, /not_merge_result/) // and must FAIL on it, never fall back
  assert.match(ci, /changed files/) // diff-scoped (§3.4)
  assert.match(ci, new RegExp(`PR #${PR}`)) // #5: waits on the gate-opened draft PR by number
  assert.match(ci, /do NOT search for it/i) // #5: deterministic, no race to "find" the PR
  ok('ci prompt: ci_wait_run on the gate-opened PR (#5) + MERGE-RESULT + success-only + diff-scoped (#452, §3.4)')

  // #5 — the gate opens the kahuna→base DRAFT PR FIRST (before the signals)
  const op = openPromotionPrPrompt({ ...A, planId: 692 })
  assert.match(op, /wave_finalize/) // opens the kahuna→integrationBase MR
  assert.match(op, /DRAFT/) // as a draft (can't auto-merge before the gate decides)
  assert.match(op, /idempotent/i) // re-open returns the existing PR
  assert.match(op, /do NOT merge/i) // PR-open node never merges
  assert.match(op, /692/) // plan_id threaded through
  assert.match(op, new RegExp(`root="${A.targetRepoDir}"`)) // #8: wave_finalize rooted at the TARGET repo, not the session project
  assert.match(op, /LOAD-BEARING/) // the root rationale is spelled out
  assert.equal(OPEN_PR_RESULT.required[0], 'opened')
  assert.equal(OPEN_PR_RESULT.properties.opened.type, 'boolean')
  assert.equal(OPEN_PR_RESULT.properties.pr_number.type, 'integer')
  ok('open-pr prompt: wave_finalize DRAFT, idempotent, never merges; OPEN_PR_RESULT requires boolean opened (#5)')

  // #847/ENG-5: review is a 2-step stage→review sub-pipeline; diff is origin/<base>...origin/<kahuna>,
  // NEVER a hard-coded `main`. Use a non-default base fixture so a stray `origin/main` is a real failure.
  const RVW = {
    waveId: 'W-7', kahunaBranch: 'kahuna/692-x', integrationBase: 'release',
    targetRepo: 'org/repo', targetRepoDir: '/tmp/repo',
    workspaceDir: '/tmp/rvw-wt', changedFiles: ['src/a.js', 'src/b.py'],
  }
  const stage = reviewStagePrompt(RVW)
  assert.match(stage, /fetch origin release kahuna\/692-x/) // fetches BOTH refs by name (never assumes main)
  assert.match(stage, /origin\/release\.\.\.origin\/kahuna\/692-x/) // diffs origin/<base>...origin/<kahuna>
  assert.match(stage, /CONSERVATIVE-FAIL/i) // empty/failed stage HOLDs, never silent pass
  assert.ok(!/origin\/main/.test(stage), 'stage must NOT reference origin/main (base=release)')
  assert.equal(REVIEW_STAGE.required[0], 'staged')
  assert.equal(REVIEW_STAGE.properties.staged.type, 'boolean')
  ok('review STAGE prompt: fetch+diff origin/<base>...origin/<kahuna>, conservative-fail on empty (ENG-5)')

  const rv = reviewSignalPrompt(RVW)
  assert.match(rv, /origin\/release\.\.\.origin\/kahuna\/692-x/) // base-ref: origin/<base>...origin/<kahuna>
  assert.ok(!/origin\/main/.test(rv), 'review prompt must NEVER reference origin/main (base=release)')
  assert.match(rv, /CHANGED FILES/) // diff-scoped (§3.4)
  assert.match(rv, /src\/a\.js/) // scoped to the staged changed-file set
  assert.match(rv, /critical/i); assert.match(rv, /important/i) // pass predicate
  ok('review prompt: reads staged workspace + origin/<base>...origin/<kahuna> + diff-scoped (ENG-5, §3.4)')

  const tv = trivySignalPrompt(A)
  assert.match(tv, /trivy fs --scanners vuln --severity HIGH,CRITICAL/)
  assert.match(tv, /AVAILABLE FIXED VERSION/i) // pass predicate: only fixable vulns fail
  assert.match(tv, /CONSERVATIVE-FAIL/i) // missing trivy = fail, not pass
  ok('trivy prompt: HIGH,CRITICAL + available-fix predicate + conservative-fail if uninstalled')
} catch (e) { bad('signal prompts', e) }

// ── 3. promotion is CODE: mark-ready → pr_merge → delete-branch (#5) ──────────────────
// #5: promotion no longer OPENS a PR (the gate's PR-OPEN node already did) — it marks the
// existing draft PR ready and merges it. It must reference the PR number, never wave_finalize.
try {
  const p = promotePrompt({ ...A, prNumber: PR })
  assert.doesNotMatch(p, /wave_finalize/) // #5: promote does NOT open a PR anymore
  assert.match(p, new RegExp(`PR #${PR}`)) // merges the gate-opened draft PR by number
  assert.match(p, /already open/i) // the PR is already open (the gate opened it)
  assert.match(p, /pr ready|mark it ready/i) // un-draft the existing PR before merging
  assert.match(p, /pr_merge/)
  assert.doesNotMatch(p, /skip_train/) // #898: queue-less — no train to skip
  assert.match(p, /pr_merge_wait/) // confirm the merge is observable on the integration base
  assert.match(p, /delete/i) // kahuna branch deleted after promotion
  // promoted:true ONLY if the merge actually landed (no fabricated success)
  assert.match(p, /promoted \(true ONLY if the merge actually landed/)
  ok('promote prompt: mark-ready → pr_merge → delete-branch, merges the gate-opened PR, promoted-only-if-landed (#5)')

  // PROMOTE_RESULT schema shape
  assert.equal(PROMOTE_RESULT.required[0], 'promoted')
  assert.equal(PROMOTE_RESULT.properties.promoted.type, 'boolean')
  ok('PROMOTE_RESULT requires a boolean `promoted`')
} catch (e) { bad('promotion prompt', e) }

// ── 3b. #722: preserveKahuna gates the branch-delete (per-plan persistent vs per-wave disposable) ──
try {
  // default (omitted) and explicit false → per-wave disposable: the prompt DELETES the branch.
  assert.match(promotePrompt({ ...A, prNumber: PR }), /delete/i)
  assert.match(promotePrompt({ ...A, prNumber: PR, preserveKahuna: false }), /delete/i)
  // preserveKahuna:true → persistent per-plan kahuna: the prompt must NOT delete it, and must say so.
  const kept = promotePrompt({ ...A, prNumber: PR, preserveKahuna: true })
  assert.doesNotMatch(kept, /--delete/) // no git/gh branch-delete instruction
  assert.doesNotMatch(kept, /disposable/) // not framed as disposable
  assert.match(kept, /do not delete/i)
  assert.match(kept, /#722|persistent per-plan/i)
  ok('promote prompt: preserveKahuna=true keeps the branch; default/false deletes it (#722)')
} catch (e) { bad('promote preserveKahuna gating (#722)', e) }

console.log('')
if (failures) { console.log(`  ${failures} assertion group(s) failed`); process.exit(1) }
console.log('  all gate-signal checks passed')
