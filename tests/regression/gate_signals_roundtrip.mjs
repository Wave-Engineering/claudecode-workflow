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
  TRIVY_SIG,
  trivyCoverage,
  promotePrompt,
  PROMOTE_RESULT,
} from '../../skills/nextwave/gate.js'
import { readFileSync } from 'node:fs'

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
  assert.match(tv, /trivy fs --scanners vuln --severity HIGH,CRITICAL --include-dev-deps --list-all-pkgs --format json --quiet/) // #1169 round 2: JSON output required — the predicate reasons over it
  assert.match(tv, /FIRST enumerate the dependency manifests/i) // #1169 round 2: denominator is a prescribed step, not left to the agent to think of
  // #1169 round 3: the enumeration is a REAL, single-line, runnable find command (round 2's
  // version was split across template-literal array elements with no line-continuation, i.e.
  // broken bash if pasted literally) — pin the actual prune clause and the lockfile set,
  // not just the sentence introducing it (a future edit that deletes the find command while
  // keeping the sentence must fail this).
  assert.match(tv, /find \S+ \\\( -name node_modules -o -name \.git .* \\\) -prune -o -type f \\\( -name 'bun\.lock' -o -name 'bun\.lockb'/)
  assert.match(tv, /AVAILABLE FIXED VERSION/i) // pass predicate: only fixable vulns fail
  assert.match(tv, /CONSERVATIVE-FAIL/i) // missing trivy = fail, not pass
  assert.match(tv, /Results carry an empty\/absent\s+Packages list/i) // #1169: ran-but-covered-nothing is ALSO conservative-fail
  // #1247 (babelfish's ruling, reversing #1169 round 3 M-1): the declaration applies only when no
  // lock is found, as check-scannable.sh rules. A found lock that yields nothing is UNSCANNED, and
  // a declaration of "nothing scannable" beside it is a contradiction, not a rescue.
  assert.match(tv, /declaration at the repo root, with a reason, applies only when no\s+lock is found \(found 0\)/)
  assert.match(tv, /It rescues nothing else; any found-but-unscanned lock FAILS, declared or not/)
  assert.doesNotMatch(tv, /rescues BOTH/i)
  ok('trivy prompt: HIGH,CRITICAL + --include-dev-deps + --list-all-pkgs + JSON output + a real runnable enumeration command + declaration applies only when nothing is found')
  // #1247: trivy reads only the exact name requirements.txt, so siblings are scanned alone under it,
  // a partial run fails, and the agent returns the counts the code-side rule below re-checks.
  assert.match(tv, /pip analyzer reads ONLY a file named exactly requirements\.txt/)
  assert.match(tv, /cp '<that file>' \$d\/requirements\.txt && trivy fs --scanners vuln --severity HIGH,CRITICAL --include-dev-deps --list-all-pkgs --format json --quiet \$d; rm -rf \$\{d:\?\}/)
  assert.match(tv, /PARTIAL COVERAGE\s+FAILS/)
  assert.match(tv, /rm -rf \$\{d:\?\}\nIts HIGH\/CRITICAL findings count toward the verdict exactly like the main scan's\./) // as in SKILL.md's fallback
  assert.match(tv, /found \(the denominator: lines the find printed, less the two exclusions above\), ingested\s+\(how many of those are INGESTED\), unscanned/)
  // The second exclusion: a bun.lockb beside a bun.lock is the same packages (check-scannable.sh
  // counts only the bun.lock), so leaving it in would HOLD a fully scanned tree. A lone one is a
  // deliberate HOLD, so the prompt must name the remedy rather than leave the operator guessing.
  assert.match(tv, /a bun\.lockb with a bun\.lock in the same directory[\s\S]*leave that bun\.lockb OUT/)
  assert.match(tv, /a bun\.lockb with NO bun\.lock beside it stays in and is UNSCANNED\s+by design; say in detail that the remedy/)
  assert.match(tv, /A file left out goes in detail, never in unscanned, and is never counted as ingested/)
  // The old CONSERVATIVE-FAIL example (an all-unpinned manifest) is now an exclusion, not a count.
  assert.doesNotMatch(tv, /every entry\s+is an unpinned range/)
  // An unpinned requirements*.txt (no version, so never ingestible) is left out of the
  // denominator exactly as check-scannable.sh leaves it out. Take the pin test FROM the script
  // so the two cannot drift: a second copied literal here would only pin the prompt to itself.
  const cs = readFileSync(new URL('../../scripts/ci/check-scannable.sh', import.meta.url), 'utf8')
  const pinRe = cs.match(/pinned="\$\(grep -cE '([^']+)' "\$req"/)?.[1]
  assert.ok(pinRe, 'check-scannable.sh pin test not found; update this extraction with it')
  assert.ok(tv.includes(`grep -cE '${pinRe}' '<that file>'`), 'trivy prompt must test pins with check-scannable.sh\'s own regex, on a quoted path')
  // The requirements PATTERNS are single-sourced the same way: check-scannable.sh's REQ_FIND,
  // which also reaches dev-requirements.txt and the pip-tools requirements/<name>.txt layout.
  const reqFind = cs.match(/^REQ_FIND=\(\\\( (.+) \\\)\)$/m)?.[1]
  assert.ok(reqFind, 'check-scannable.sh REQ_FIND not found; update this extraction with it')
  assert.ok(tv.includes(` -o ${reqFind} \\) -print`), 'trivy find must carry check-scannable.sh\'s REQ_FIND')
  assert.match(tv, /where it prints 0, leave that file OUT of the denominator/)
  ok('trivy prompt: pip siblings scanned alone, partial coverage fails, unpinned requirements out of the denominator as in check-scannable.sh, counts returned (#1247)')
} catch (e) { bad('signal prompts', e) }

// ── 2b. #1247: the TRIVY coverage rule is CODE, not a prompt instruction ──────────────
try {
  // The issue's measured shape: 4 pip locks found, only the 2 named exactly requirements.txt read.
  const half = trivyCoverage({
    signal: 'trivy', passed: true, detail: '0 HIGH/CRITICAL', found: 4, ingested: 2,
    unscanned: ['requirements-dev.txt', 'sub/requirements-build.txt'],
  })
  assert.equal(half.passed, false, '2 of 4 ingested must HOLD even though the scanned half is clean')
  assert.match(half.detail, /PARTIAL COVERAGE \(HOLD\): 2 of 4 lockfile\(s\) ingested; UNSCANNED: requirements-dev\.txt, sub\/requirements-build\.txt/)
  const full = { signal: 'trivy', passed: true, detail: 'ok', found: 4, ingested: 4, unscanned: [] }
  assert.deepEqual(trivyCoverage(full), full, 'full coverage passes through unchanged')
  // A self-contradictory result (ingested counted as "scanned", yet a path named unscanned) HOLDs.
  const named = trivyCoverage({ signal: 'trivy', passed: true, detail: 'ok', found: 3, ingested: 3, unscanned: ['requirements-dev.txt'] })
  assert.equal(named.passed, false, 'a signal naming an unscanned lock must HOLD even when its counts square')
  assert.match(named.detail, /PARTIAL COVERAGE \(HOLD\): counts claim full coverage \(3 of 3\) yet name unscanned lock\(s\); UNSCANNED: requirements-dev\.txt/)
  const failing = { signal: 'trivy', passed: false, detail: 'CVE-1 fixable', found: 4, ingested: 4, unscanned: [] }
  assert.equal(trivyCoverage(failing).passed, false, 'the rule never turns a fail into a pass')
  // A declaration applies only when no lock is found (check-scannable.sh's rule, one rule on all
  // three paths). A lone bun.lockb (found 1, ingested 0) HOLDs with or without one: its remedy is
  // bun.lock, and a stale declaration must not mask a lock trivy cannot read.
  const lone = { signal: 'trivy', passed: true, detail: 'lone bun.lockb', found: 1, ingested: 0, unscanned: ['bun.lockb'], declared: false }
  for (const declared of [false, true]) {
    const r = trivyCoverage({ ...lone, declared })
    assert.equal(r.passed, false, `a lone bun.lockb must HOLD (declared=${declared})`)
    assert.match(r.detail, /^NOTHING INGESTED \(HOLD\): 0 of 1 lockfile\(s\) ingested; UNSCANNED: bun\.lockb\. A declaration applies only when no lock is found/)
    assert.doesNotMatch(r.detail, /ERRORED/, 'a coverage HOLD is not a signal error')
  }
  const none = { signal: 'trivy', passed: true, detail: 'nothing to scan', found: 0, ingested: 0, unscanned: [] }
  const undeclared = trivyCoverage({ ...none, declared: false })
  assert.equal(undeclared.passed, false, 'nothing found and nothing declared HOLDs')
  assert.match(undeclared.detail, /^NOTHING FOUND \(HOLD\): no lockfile found and no \.no-scannable-dependencies declaration/)
  assert.equal(trivyCoverage({ ...none, declared: undefined }).passed, false, 'an absent declared is not a declaration')
  assert.deepEqual(trivyCoverage({ ...none, declared: true }), { ...none, declared: true }, 'nothing found, but declared, passes through')
  // A HOLD keeps the agent's own cause after its rule (code review I-1): a scan that already
  // failed must not lose "trivy not installed" to a coverage note, nor be relabelled ERRORED.
  const broken = trivyCoverage({ signal: 'trivy', passed: false, detail: 'trivy not installed', found: 2, ingested: 0, unscanned: ['a', 'b'], declared: false })
  assert.equal(broken.passed, false)
  assert.match(broken.detail, /^NOTHING INGESTED \(HOLD\): 0 of 2 lockfile\(s\) ingested; UNSCANNED: a, b\. .*trivy not installed$/)
  assert.doesNotMatch(broken.detail, /ERRORED/)
  const partialBroken = trivyCoverage({ signal: 'trivy', passed: false, detail: 'trivy DB pull failed: 429', found: 2, ingested: 1, unscanned: ['b'], declared: false })
  assert.match(partialBroken.detail, /^PARTIAL COVERAGE \(HOLD\): 1 of 2 lockfile\(s\) ingested; UNSCANNED: b\. trivy DB pull failed: 429$/)
  assert.match(trivyCoverage({ signal: 'trivy', passed: true, detail: 'agent said ok', found: 2 }).detail, /^signal ERRORED — conservative-fail \(HOLD\): coverage counts missing or inconsistent \(found=2, ingested=undefined, unscanned=0\); agent detail: agent said ok$/)
  // found 0 beside a named unscanned lock contradicts itself (delta 4 note, babelfish: do it). found
  // alone unlocks the declaration, so a declared tree must not ride through on the bad count.
  const contradicted = trivyCoverage({ signal: 'trivy', passed: true, detail: 'nothing to scan', found: 0, ingested: 0, unscanned: ['bun.lockb'], declared: true })
  assert.equal(contradicted.passed, false, 'found 0 with a named unscanned lock must HOLD, even declared')
  assert.match(contradicted.detail, /^signal ERRORED — conservative-fail \(HOLD\): coverage counts missing or inconsistent \(found=0, ingested=0, unscanned=1\); agent detail: nothing to scan$/)
  for (const counts of [{}, { found: 2 }, { found: 2, ingested: 3 }, { found: 2, ingested: -1 }, { found: 1.5, ingested: 1 }]) {
    const r = trivyCoverage({ signal: 'trivy', passed: true, unscanned: [], ...counts })
    assert.equal(r.passed, false, `missing or inconsistent counts must conservative-fail: ${JSON.stringify(counts)}`)
  }
  assert.equal(trivyCoverage(undefined).passed, false)
  assert.deepEqual(TRIVY_SIG.required, ['signal', 'passed', 'found', 'ingested', 'unscanned', 'declared'])
  // A pure rule proves nothing if the workflow stops calling it: pin the wiring in source AND bundle.
  for (const f of ['per-wave-workflow.js', 'per-wave-workflow.bundled.js']) {
    const src = readFileSync(new URL(`../../skills/nextwave/${f}`, import.meta.url), 'utf8')
    assert.match(src, /label: 'gate:trivy', phase: 'Trust gate', schema: TRIVY_SIG,/, `${f}: trivy signal must use TRIVY_SIG`)
    assert.match(src, /\)\.then\(trivyCoverage\)\.catch\(\(e\) => conservativeFail\('trivy', e\)\)/, `${f}: trivyCoverage must run on the agent result`)
  }
  ok('trivy coverage: 2-of-4 HOLDs, a named unscanned lock HOLDs, a lone bun.lockb HOLDs declared or not, full passes through, a fail never becomes a pass and keeps its cause, bad counts conservative-fail, wired in source and bundle (#1247)')
} catch (e) { bad('trivy coverage (#1247)', e) }

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
