// gate_signals_roundtrip.mjs — #687 trust-gate seam unit test.
//
// Pins the load-bearing #687 invariants that DON'T need a live sdlc-server (the agent()-driven
// signals — commutativity_verify / ci_wait_run / code-reviewer / trivy — need one; those are
// exercised by a live wave, not here). What IS deterministic and load-bearing:
//   1. conservativeFail() — the production replacement for the always-pass gateSignalStub:
//      a signal that ERRORS returns passed:false (HOLD), NEVER passed:true (SEAMS invariant 6).
//   2. each signal prompt names its REAL sdlc-server tool + the EXACT pass predicate, and is
//      diff-scoped (the §3.4 refinement: changed-files, never the whole tree).
//   3. the CI pass predicate is CODE (#1211): ciVerdict() passes only a ci_wait_run success or a
//      green merge-result pipeline bound to the current head, and nothing else (#898).
//   4. the promote prompt is wave_finalize → pr_merge → delete-branch (CODE ONLY), and reports
//      promoted ONLY once the merge is observable on the integration base.

import assert from 'node:assert/strict'
import {
  conservativeFail,
  openPromotionPrPrompt,
  OPEN_PR_RESULT,
  commutativitySignalPrompt,
  ciSignalPrompt,
  CI_WAIT_DEFAULT_SEC,
  ciWaitBudget,
  ciVerdict,
  reviewStagePrompt,
  REVIEW_STAGE,
  reviewSignalPrompt,
  trivySignalPrompt,
  TRIVY_SIG,
  trivyCoverage,
  trivyTreeBound,
  bindScanToGradedHead,
  FLIGHT_CI_EVIDENCE,
  flightCiPrompt,
  flightCiVerdict,
  promotePrompt,
  PROMOTE_RESULT,
  pinnedMergeVerdict,
  reconciledMerges,
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
  // #1211: the pass shape is CODE (ciVerdict, section 2c). The prompt only gathers evidence, and must
  // not hand the agent a predicate of its own to apply, generously or not.
  assert.match(ci, /do not decide pass or fail yourself/)
  assert.doesNotMatch(ci, /sha EQUALS/, 'the #1035 2b rule a merged-results pipeline can never satisfy must be gone')
  assert.doesNotMatch(ci, /passed=false|passed \(bool\)/, 'the agent returns evidence, never a verdict')
  assert.match(ci, /timeout_sec=420/) // #1035's bleed fix survives the rewrite
  assert.match(ci, new RegExp(`merge_requests/${PR}/pipelines`)) // the direct read lists THIS MR's pipelines
  assert.match(ci, new RegExp(`refs/merge-requests/${PR}/merge`)) // and names its /merge ref concretely
  assert.match(ci, /parent_ids/) // and reports the merge commit's parents, which bind it to the head
  // #1211 review I-1: the head is read FIRST and again LAST. Read only before the wait, a head that
  // moved during it lets the previous head's green /merge pipeline pass.
  const at = (s) => { const i = ci.indexOf(s); assert.ok(i >= 0, `ci prompt must contain ${s}`); return i }
  assert.ok(at('report it as head_sha,') < at('call sdlc-server ci_wait_run'), 'the first head read comes before ci_wait_run')
  // #1357: the no-run probe runs before the wait, with the draft exemption, and the ref is named.
  assert.ok(at('PROBE, before ci_wait_run: sdlc-server pr_wait_ci(') < at('call sdlc-server ci_wait_run'), 'the probe precedes ci_wait_run')
  assert.match(ci, /ONLY when CI cannot start for this head/)
  assert.ok(ci.includes(`GitLab: ref="refs/merge-requests/${PR}/merge"`), 'GitLab waits on the /merge ref')
  assert.ok(ci.includes('GitHub: ref="kahuna/'), 'GitHub waits on the kahuna branch')
  assert.match(ci, /probe and wait \(step 2\)/)
  assert.ok(at('report it as head_sha_final') > at('DIRECT READ'), 'the final head read comes after ci_wait_run AND the direct read')
  assert.match(ci, /return wait: \{\}/) // the schema requires wait, so "no wait" would be a schema error
  // #476: the gate must REQUIRE a merge-result pipeline. Without this flag the tool
  // will happily grade a branch pipeline — or a SKIPPED one, which GitLab normalizes
  // to "success" — as though it validated the merge. That is a silent false PASS on
  // the only thing standing between an autonomous wave and the integration base.
  assert.match(ci, /require_merge_result=true/)
  // #476: the freshness anchor. Without pr_number the tool cannot prove the run it
  // grades belongs to the CURRENT head — a green merge-result run for a PREVIOUS
  // commit would satisfy the gate and merge code CI never saw.
  assert.match(ci, /pr_number=/)
  assert.match(ci, /not_merge_result/) // no verdict ⇒ the direct merge-result read, never a branch fallback
  assert.match(ci, /changed files/) // diff-scoped (§3.4)
  assert.match(ci, new RegExp(`PR #${PR}`)) // #5: waits on the gate-opened draft PR by number
  assert.match(ci, /do NOT search for it/i) // #5: deterministic, no race to "find" the PR
  ok('ci prompt: ci_wait_run on the gate-opened PR (#5) + MERGE-RESULT + success-only + diff-scoped (#452, §3.4)')

  // #1302: the wait is a per-repo budget. Absent, it is today's 420s; a valid one sets the wait AND
  // the direct-read window; anything else falls back to 420 rather than reaching the tool.
  assert.equal(CI_WAIT_DEFAULT_SEC, 420)
  assert.match(ci, /timeout_sec=420 \+ poll_interval_sec=15/)
  assert.match(ci, /up to ~420s/) // the direct-read window follows the default too
  assert.match(ci, /420s is the default; per-project/)
  assert.match(ci, /`CI wait budget` in \.claude-project\.md/)
  assert.doesNotMatch(ci, /ample headroom/)
  const long = ciSignalPrompt({ ...A, prNumber: PR, ciWaitSec: 2700 })
  assert.match(long, /timeout_sec=2700 \+ poll_interval_sec=15/)
  assert.match(long, /up to ~2700s/)
  assert.doesNotMatch(long, /timeout_sec=420/)
  for (const v of [0, -5, 'abc', 99999, 59, 3601, 2700.5, null, undefined, '2700']) {
    const p = ciSignalPrompt({ ...A, prNumber: PR, ciWaitSec: v })
    assert.match(p, /timeout_sec=420 \+/, `ciWaitSec=${JSON.stringify(v)} must fall back to 420`)
    assert.match(p, /up to ~420s/, `ciWaitSec=${JSON.stringify(v)}: the direct-read window must fall back too`)
    assert.equal(ciWaitBudget(v), 420)
  }
  assert.equal(ciWaitBudget(60), 60)
  assert.equal(ciWaitBudget(3600), 3600)
  ok('ci prompt: the CI wait is a per-repo budget in [60, 3600], defaulting to 420 (#1302)')

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
  assert.match(tv, /THEN enumerate the dependency manifests/i) // #1169 round 2: denominator is a prescribed step, not left to the agent to think of (after #1206's staging)
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
  assert.match(tv, /declaration at the root of <w>\/tree \(the kahuna tip, not the operator's\s+checkout\), with a reason, applies only when no\s+lock is found \(found 0\)/)
  assert.match(tv, /It rescues nothing else; any found-but-unscanned lock FAILS, declared or not/)
  assert.doesNotMatch(tv, /rescues BOTH/i)
  ok('trivy prompt: HIGH,CRITICAL + --include-dev-deps + --list-all-pkgs + JSON output + a real runnable enumeration command + declaration applies only when nothing is found')
  // #1247: trivy reads only the exact name requirements.txt, so siblings are scanned alone under it,
  // a partial run fails, and the agent returns the counts the code-side rule below re-checks.
  assert.match(tv, /pip analyzer reads ONLY a file named exactly requirements\.txt/)
  assert.match(tv, /cp '<that file>' \$d\/requirements\.txt && trivy fs --scanners vuln --severity HIGH,CRITICAL --include-dev-deps --list-all-pkgs --format json --quiet \$d > <w>\/trivy-<n>\.json 2> <w>\/trivy-<n>\.err; echo "exit=\$\?"; rm -rf \$\{d:\?\}/)
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
  // #1277: trivy's JSON goes to a file, never to the tool output, which is cut at ~30k characters
  // between a lock's Packages and its Vulnerabilities (a false PASS). Every command line that runs
  // trivy is checked, so a third scan added later without the capture fails here too: any indented
  // command line that runs `trivy fs `, however it begins (`cd x && trivy fs …`, a `for` loop).
  const runs = tv.split('\n').filter((l) => l.startsWith('  ') && l.includes('trivy fs '))
  assert.ok(runs.length >= 2, `expected the main and the per-file trivy scans, found ${runs.length}`)
  for (const run of runs) {
    // `\s>` and not a bare `>`: `2> <w>/trivy-0.err` contains `> <w>/trivy-` (the #1276 vacuity).
    assert.match(run, /\s>\s*<w>\/trivy-\S+\.json\s/, `stdout not captured: ${run}`)
    assert.match(run, /\s2>\s*<w>\/trivy-\S+\.err/, `stderr not captured: ${run}`)
    assert.ok(run.includes('; echo "exit=$?"'), `trivy run without its own exit=: ${run}`)
  }
  assert.match(tv, /--quiet <w>\/tree > <w>\/trivy-0\.json 2> <w>\/trivy-0\.err; echo "exit=\$\?"\n/)
  // <w> is the literal path mktemp -d printed, never a variable: a variable does not survive
  // between Bash calls, so `> $w/...` in a later call writes to /trivy-0.json and HOLDs every wave.
  assert.match(tv, /mktemp -d, once\. Write the path it prints in place of <w> in every command below/)
  assert.doesNotMatch(tv, /\$w\b/, 'the work directory must be the <w> placeholder, not a $w variable')
  assert.match(tv, /run_in_background: true .*, one at a time, never\s+in parallel/)
  assert.ok(tv.includes(`jq '[.Results[]? | {Target, pkgs: (.Packages // [] | length), hc: ([.Vulnerabilities[]? | select(.Severity=="HIGH" or .Severity=="CRITICAL")] | length), hc_fixable: ([.Vulnerabilities[]? | select((.Severity=="HIGH" or .Severity=="CRITICAL") and ((.FixedVersion // "") != ""))] | length)}]' <w>/trivy-<n>.json`), 'the per-target jq read with hc_fixable is missing')
  assert.match(tv, /\| \{target: \$t, pkg: \.PkgName, id: \.VulnerabilityID, severity: \.Severity, fixed: \.FixedVersion\}\]' <w>\/trivy-<n>\.json/)
  assert.match(tv, /FROM ITS FILE, with jq, never from tool\s+output/)
  assert.match(tv, /A run that printed no exit=, printed a non-zero exit=, or left a file jq cannot parse scanned nothing: every lock it was to cover is UNSCANNED\./)
  assert.match(tv, /INGESTED when a jq row for it shows at least one package/)
  ok('trivy prompt: every scan captured to <w>/trivy-<n>.json + .err with its own exit=, read with jq (hc_fixable), no exit=/non-zero/unparseable = UNSCANNED (#1277)')
  // #1206: the scans run over a detached worktree of origin/<kahuna>, never the operator's checkout.
  assert.ok(tv.includes('git -C /tmp/repo fetch origin kahuna/692-x'), 'the kahuna ref is fetched')
  assert.ok(tv.includes('git -C /tmp/repo rev-parse origin/kahuna/692-x'), 'kahuna_sha is read from the fetched ref')
  assert.ok(tv.includes('worktree add --detach <w>/tree origin/kahuna/692-x'), 'a detached kahuna worktree is staged')
  assert.ok(tv.includes('git -C <w>/tree rev-parse HEAD'), 'scanned_sha is the worktree HEAD')
  assert.ok(tv.includes('worktree remove --force <w>/tree') && tv.includes('worktree prune'), 'the worktree is removed')
  assert.ok(tv.indexOf('worktree add --detach') < tv.indexOf('find <w>/tree'), 'the tree is staged before the enumeration')
  assert.match(tv, /^ {2}find <w>\/tree \\\(/m, 'the enumeration is rooted at the kahuna worktree')
  for (const run of runs.filter((l) => l.includes('--quiet') && !l.includes('$d'))) {
    assert.match(run, /--quiet <w>\/tree >/, `a main scan not rooted at the kahuna worktree: ${run}`)
  }
  assert.doesNotMatch(tv, /find \/tmp\/repo/, 'no enumeration over the operator checkout')
  assert.doesNotMatch(tv, /trivy fs [^\n]*\/tmp\/repo/, 'no scan over the operator checkout')
  assert.doesNotMatch(tv, /ensure [^\n]* is the checked-out/, 'the instruction-only safeguard is gone')
  assert.match(tv, /Do NOT run git checkout or git switch in \/tmp\/repo/)
  assert.match(tv, /\.no-scannable-dependencies file with a reason exists at the root of <w>\/tree/)
  assert.match(tv, /campaign\/692-x/, 'the prose names the integration base')
  ok('trivy prompt: stages a detached origin/<kahuna> worktree, scans and checks only it, returns both SHAs, removes it, never touches the checkout (#1206)')
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
  assert.deepEqual(TRIVY_SIG.required, ['signal', 'passed', 'found', 'ingested', 'unscanned', 'declared', 'scanned_sha', 'kahuna_sha'])
  // A pure rule proves nothing if the workflow stops calling it: pin the wiring in source AND bundle.
  for (const f of ['per-wave-workflow.js', 'per-wave-workflow.bundled.js']) {
    const src = readFileSync(new URL(`../../skills/nextwave/${f}`, import.meta.url), 'utf8')
    assert.match(src, /label: 'gate:trivy', phase: 'Trust gate', schema: TRIVY_SIG,/, `${f}: trivy signal must use TRIVY_SIG`)
    assert.match(src, /\)\.then\(trivyTreeBound\)\.then\(trivyCoverage\)\.catch\(\(e\) => conservativeFail\('trivy', e\)\)/, `${f}: trivyTreeBound then trivyCoverage must run on the agent result`)
    assert.match(src, /trivySignalPrompt\(\{ waveId: WAVE_ID, kahunaBranch: KAHUNA_BRANCH, integrationBase: INTEGRATION_BASE, targetRepoDir: TARGET_REPO_DIR \}\)/, `${f}: the trivy prompt gets the integration base`)
  }
  ok('trivy coverage: 2-of-4 HOLDs, a named unscanned lock HOLDs, a lone bun.lockb HOLDs declared or not, full passes through, a fail never becomes a pass and keeps its cause, bad counts (and found 0 beside a named unscanned lock) conservative-fail, wired in source and bundle (#1247)')
} catch (e) { bad('trivy coverage (#1247)', e) }

// ── 2b'. #1206: the trivy verdict is bound to the kahuna tip in CODE ──────────────────
try {
  const K = 'a'.repeat(40)
  const O = 'b'.repeat(40)
  const clean = { signal: 'trivy', passed: true, detail: '0 HIGH/CRITICAL', found: 1, ingested: 1, unscanned: [], declared: false, scanned_sha: K, kahuna_sha: K }
  assert.deepEqual(trivyTreeBound(clean), clean, 'equal full SHAs pass through unchanged')
  assert.deepEqual(trivyTreeBound({ ...clean, scanned_sha: 'c'.repeat(64), kahuna_sha: 'c'.repeat(64) }).passed, true, 'a SHA-256 repo binds too')
  const holds = {
    'mismatched SHAs (the operator checkout was scanned)': { scanned_sha: O },
    'missing scanned_sha': { scanned_sha: undefined },
    'missing kahuna_sha': { kahuna_sha: undefined },
    'empty SHAs (staging failed)': { scanned_sha: '', kahuna_sha: '' },
    'an abbreviated SHA': { scanned_sha: K.slice(0, 12), kahuna_sha: K.slice(0, 12) },
    'an uppercase SHA': { scanned_sha: K.toUpperCase(), kahuna_sha: K.toUpperCase() },
  }
  for (const [what, over] of Object.entries(holds)) {
    const r = trivyTreeBound({ ...clean, ...over })
    assert.equal(r.passed, false, `${what} must HOLD`)
    assert.equal(r.signal, 'trivy')
    assert.match(r.detail, /^TREE NOT BOUND \(HOLD\): scanned_sha=\S+ kahuna_sha=\S+; .*0 HIGH\/CRITICAL$/, `${what}: detail names both SHAs, then keeps the agent's: ${r.detail}`)
    assert.equal(r.found, 1, `${what}: the coverage counts survive for trivyCoverage`)
  }
  const mm = trivyTreeBound({ ...clean, scanned_sha: O })
  assert.ok(mm.detail.includes(`scanned_sha=${O}`) && mm.detail.includes(`kahuna_sha=${K}`), mm.detail)
  assert.match(trivyTreeBound({ ...clean, scanned_sha: undefined }).detail, /scanned_sha=missing/)
  const failing = { ...clean, passed: false, detail: 'CVE-1 fixable' }
  assert.equal(trivyTreeBound(failing).passed, false, 'a bound failing scan stays failing')
  assert.equal(trivyTreeBound({ ...failing, scanned_sha: O }).passed, false, 'an unbound failing scan stays failing')
  assert.equal(trivyTreeBound(null).passed, false, 'a null result HOLDs')
  // Composed as wired: an unbound scan with good coverage still HOLDs, and keeps the tree rule first.
  const composed = trivyCoverage(trivyTreeBound({ ...clean, scanned_sha: O }))
  assert.equal(composed.passed, false)
  assert.match(composed.detail, /^TREE NOT BOUND/)
  ok('trivyTreeBound: equal full SHAs pass; mismatch / missing / empty / short / uppercase HOLD naming both SHAs; never turns a fail into a pass; composes with trivyCoverage (#1206)')
} catch (e) { bad('trivy tree bound (#1206)', e) }

// ── 2c. #1211: the CI merge-result rule is CODE, shared with the campaign release gate ───────
try {
  const HEAD = '1'.repeat(40) // the MR's current head
  const TARGET = '2'.repeat(40) // the integration base's tip
  const MERGE = '3'.repeat(40) // the ephemeral merge commit a merged-results pipeline runs on
  const REF = `refs/merge-requests/${PR}/merge`
  const NOT_FOUND = { ok: false, error: "No CI run found for ref 'kahuna/692-x'" } // sdlc#585's signature
  // The measured shape of a green GitLab merged-results pipeline (15/15 on 2026-10-19).
  const direct = (over = {}) => ({
    pr_number: PR,
    head_sha: HEAD,
    head_sha_final: HEAD, // the head read again after the last read, unmoved
    target_sha: TARGET, // #1356: the integration base's tip, read last
    wait: NOT_FOUND,
    merge_pipelines: [{ id: 9, ref: REF, status: 'success', sha: MERGE }],
    merge_commit: { sha: MERGE, parent_ids: [TARGET, HEAD] },
    ...over,
  })

  const primary = ciVerdict({ pr_number: PR, head_sha: HEAD, head_sha_final: HEAD, target_sha: TARGET, wait: { ok: true, final_status: 'success', sha: HEAD } }, PR)
  assert.equal(primary.signal, 'ci')
  assert.equal(primary.passed, true, 'a ci_wait_run success passes on the primary path')
  assert.match(primary.detail, /^PASS \(ci_wait_run\)/)
  // #1356: a pass keeps the head it graded; a HOLD carries none.
  assert.equal(primary.head, HEAD, 'a CI pass carries the graded head')
  assert.equal(ciVerdict(direct({ merge_pipelines: [] }), PR).head, undefined, 'a CI HOLD carries no head')
  ok('ciVerdict: a pass carries head; a HOLD does not (#1356)')

  // The case #1035's step 2b could never pass: its sha is the merge commit, never the head.
  const green = ciVerdict(direct(), PR)
  assert.equal(green.passed, true, 'a green 2-parent /merge pipeline whose parent[1] is the head must PASS')
  assert.match(green.detail, /^PASS \(direct\): .*merges the head 11111111/)

  const stale = ciVerdict(direct({ merge_commit: { sha: MERGE, parent_ids: [TARGET, '4'.repeat(40)] } }), PR)
  assert.equal(stale.passed, false, 'parent[1] != head is a stale run and must HOLD')
  assert.match(stale.detail, /^HOLD \(direct\): .*stale run/)

  const red = ciVerdict(direct({ merge_pipelines: [{ id: 9, ref: REF, status: 'failed', sha: MERGE }] }), PR)
  assert.equal(red.passed, false, 'a red direct read must HOLD')
  assert.match(red.detail, /^HOLD \(direct\): .*is failed/)

  const moved = ciVerdict(direct({ wait: { ok: false, final_status: 'not_merge_result', reason: 'not_merge_result' }, head_sha_final: '7'.repeat(40) }), PR)
  assert.equal(moved.passed, false, "a head that moved while it was graded HOLDs, even with the old head's green /merge pipeline")
  assert.match(moved.detail, /^HOLD \(none\): the head moved during grading/)

  const graded = ciVerdict(direct({ wait: { ok: false, final_status: 'failure' } }), PR)
  assert.equal(graded.passed, false, 'a red ci_wait_run is final: a green direct read never overrides it')
  assert.match(graded.detail, /^HOLD \(ci_wait_run\): .*never overrides a graded red/)

  // The PR is the gate's, not the agent's: evidence about another PR HOLDs ...
  const other = ciVerdict(direct({ pr_number: PR + 1 }), PR)
  assert.equal(other.passed, false, 'evidence about another PR must HOLD')
  assert.match(other.detail, new RegExp(`evidence is for PR #${PR + 1}, but the gate opened PR #${PR}`))
  // ... and the /merge ref the direct read is filtered on is the gate's PR's, numbered or not.
  const { pr_number: _n, ...unnumbered } = direct()
  assert.equal(ciVerdict(unnumbered, PR).passed, true, 'a missing agent pr_number takes the gate PR')
  const otherRef = { ...unnumbered, merge_pipelines: [{ id: 9, ref: `refs/merge-requests/${PR + 1}/merge`, status: 'success', sha: MERGE }] }
  assert.equal(ciVerdict(otherRef, PR).passed, false, "another MR's /merge pipeline never counts")

  for (const ev of [{}, null, undefined]) {
    assert.equal(ciVerdict(ev, PR).passed, false, `evidence ${JSON.stringify(ev)} must HOLD`)
  }
  // A HOLD keeps the agent's own notes after the rule, so the cause it read is not lost.
  const noted = ciVerdict(direct({ merge_pipelines: [], notes: 'glab api 401 Unauthorized' }), PR)
  assert.equal(noted.passed, false)
  assert.match(noted.detail, /^HOLD \(direct\): .*\| agent: glab api 401 Unauthorized$/)
  ok('ciVerdict: a ci_wait_run success or a head-bound green /merge pipeline PASSes; stale, red, graded-red, other-PR and missing evidence HOLD (#1211)')

  // The committed bundle (the artifact the Workflow tool runs) must INLINE merge-result.js. A module
  // dropped from bundle.mjs MODULES still bundles "in sync" and parses, then throws a ReferenceError
  // at the gate's first CI signal, so pin the definitions rather than the call sites.
  const bundle = readFileSync(new URL('../../skills/nextwave/per-wave-workflow.bundled.js', import.meta.url), 'utf8')
  for (const def of ['function mergeResultVerdict(', 'function directMergeReadSteps(', 'const MERGE_RESULT_EVIDENCE =', 'function ciVerdict(']) {
    assert.ok(bundle.includes(def), `per-wave-workflow.bundled.js must define ${def.replace(/[ (=]+$/, '')} (merge-result.js inlined, #1211)`)
  }
  ok('per-wave bundle inlines merge-result.js: mergeResultVerdict, directMergeReadSteps, MERGE_RESULT_EVIDENCE and ciVerdict are defined (#1211)')
} catch (e) { bad('ci verdict (#1211)', e) }

// ── 3. promotion is CODE: mark-ready → pr_merge → delete-branch (#5) ──────────────────
// #5: promotion no longer OPENS a PR (the gate's PR-OPEN node already did) — it marks the
// existing draft PR ready and merges it. It must reference the PR number, never wave_finalize.
const GRADED = '9'.repeat(40) // the head the CI signal graded (#1356)
try {
  const p = promotePrompt({ ...A, prNumber: PR, headSha: GRADED })
  assert.match(p, new RegExp(`pr_merge\\(number=<the PR number>, expected_head_sha="${GRADED}"\\)`), '#1356: the merge is pinned to the graded head')
  assert.match(p, /anything but a merge.*head_moved on GitLab, gh_pr_merge_failed on GitHub.*STOP and return promoted=false/s, '#1356: any non-ok pinned merge stops the promote, not only head_moved')
  assert.match(p, /Never retry it\s+without expected_head_sha/, '#1356: a refused pin is never retried unpinned')
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
  assert.match(promotePrompt({ ...A, prNumber: PR, headSha: GRADED }), /delete/i)
  assert.match(promotePrompt({ ...A, prNumber: PR, headSha: GRADED, preserveKahuna: false }), /delete/i)
  // preserveKahuna:true → persistent per-plan kahuna: the prompt must NOT delete it, and must say so.
  const kept = promotePrompt({ ...A, prNumber: PR, headSha: GRADED, preserveKahuna: true })
  assert.doesNotMatch(kept, /--delete/) // no git/gh branch-delete instruction
  assert.doesNotMatch(kept, /disposable/) // not framed as disposable
  assert.match(kept, /do not delete/i)
  assert.match(kept, /#722|persistent per-plan/i)
  ok('promote prompt: preserveKahuna=true keeps the branch; default/false deletes it (#722)')
} catch (e) { bad('promote preserveKahuna gating (#722)', e) }

// ── 3c. #1356 (triage #6): no graded head → the promote prompt is a STOP ─────────────────────
try {
  for (const headSha of [undefined, null, '', 'abc1234', 'AB'.repeat(20)]) {
    const p = promotePrompt({ ...A, prNumber: PR, headSha })
    assert.match(p, /No graded head SHA was handed to\s+you/, `headSha ${JSON.stringify(headSha)} must STOP`)
    assert.match(p, /STOP\. Do NOT mark the PR ready and do NOT\s+merge/)
    assert.doesNotMatch(p, /pr_merge\(/, 'a STOP prompt never names a pr_merge call')
  }
  ok('promotePrompt: no graded head → STOP, no pr_merge (#1356)')
} catch (e) { bad('promote with no graded head (#1356)', e) }

// ── 3d. #1356 review: a pinned merge counts only on the server's echo of the pin ───────────────
// pr_merge's response is mocked: sdlc v5.2.0 returns pinned_head_sha; v5.1.x and older return none.
try {
  const H = 'a'.repeat(40)
  const old = { ok: true, merged: true, merge_commit_sha: 'b'.repeat(40) } // < v5.2.0: no echo
  const echoed = { ...old, pinned_head_sha: H }
  const other = { ...old, pinned_head_sha: 'c'.repeat(40) }
  assert.equal(pinnedMergeVerdict(old, H).landed, false, 'no echo (old server) is refused')
  assert.match(pinnedMergeVerdict(old, H).reason, /v5\.1\.x pins but does not echo, and anything before v5\.1\.0 drops the pin, so no echo means no pin/)
  assert.equal(pinnedMergeVerdict(other, H).landed, false, 'a mismatched echo is refused')
  assert.equal(pinnedMergeVerdict(other, H).reason, 'pr_merge pinned cccccccc, not the graded head aaaaaaaa')
  assert.equal(pinnedMergeVerdict(echoed, H).landed, true, 'an echo of the graded head is merged')
  assert.equal(pinnedMergeVerdict(echoed, null).landed, false, 'no graded head: nothing was pinned to it')
  assert.equal(pinnedMergeVerdict(null, H).landed, false, 'no report is refused')
  // v5.2.0 still echoes on a queue enrollment: the echo alone is not a merge.
  for (const merged of [false, undefined]) {
    const v = pinnedMergeVerdict({ ...echoed, merged, enrolled: true }, H)
    assert.equal(v.landed, false, `an echo with merged:${merged} is not a merge`)
    assert.match(v.reason, /did not report merged:true/)
  }

  const p = promotePrompt({ ...A, prNumber: PR, headSha: GRADED })
  assert.match(p, /v5\.1\.x pins but does not echo, and anything before\s+v5\.1\.0 drops the pin[\s\S]*no echo means no pin/, 'the prompt names the reason')
  assert.match(p, /pinned_head_sha \(pr_merge's, as returned\)/)
  assert.ok(!p.includes(`pinned_head_sha is ${GRADED}`), 'the prompt must not name the passing value to the node relaying the echo')
  for (const k of ['pinned_head_sha', 'merge_commit_sha']) assert.equal(PROMOTE_RESULT.properties[k].type, 'string')

  // Reconcile: a flight counts only when it is in merged AND has a proven merges entry.
  const proof = (issue, over = {}) => ({ issue, merged: true, merge_commit_sha: 'b'.repeat(40), pinned_head_sha: H, ...over })
  const handed = [7, 8, 9, 10, 12, 13, 14].map((issue) => ({ issue, head: H }))
  const rec = {
    merged: [7, 8, 9, 10, 11, 13],
    merges: [
      proof(7), // proven
      proof(8, { pinned_head_sha: undefined }), // old server: no echo
      proof(9, { pinned_head_sha: 'c'.repeat(40) }), // mismatch
      proof(11), // not handed: ignored
      proof(12), // a proof with no merged claim and no rework
      proof(13, { merged: false }), // enrolled, not merged
      proof(14), // undone: in needs_rework too
    ],
    needs_rework: [{ issue: 14, reason: 'interface break' }],
  }
  const r = reconciledMerges(rec, handed)
  assert.deepEqual(r.merged, [7], 'only the proven merge counts')
  assert.deepEqual(r.refused.map((x) => x.issue), [8, 9, 10, 12, 13], 'needs_rework #14 is neither merged nor refused')
  const why = Object.fromEntries(r.refused.map((x) => [x.issue, x.reason]))
  assert.match(why[8], /no echo means no pin/)
  assert.match(why[9], /not the graded head/)
  assert.match(why[10], /reported merged with no merges entry/)
  assert.match(why[12], /no merged claim and no needs_rework/)
  assert.match(why[13], /did not report merged:true/)
  const noCommit = reconciledMerges({ merged: [7], merges: [proof(7, { merge_commit_sha: undefined })] }, [handed[0]])
  assert.deepEqual(noCommit, { merged: [], refused: [{ issue: 7, reason: 'no merge_commit_sha for its merge' }] })
  // babelfish's N1 case: a valid proof plus the same issue in needs_rework.
  assert.deepEqual(reconciledMerges({ merged: [7], merges: [proof(7)], needs_rework: [{ issue: 7, reason: 'x' }] }, [handed[0]]), { merged: [], refused: [] }, 'an undone merge is neither merged nor refused')
  assert.deepEqual(reconciledMerges({ merged: [], needs_rework: [{ issue: 7, reason: 'x' }] }, [handed[0]]), { merged: [], refused: [] }, 'a reworked flight is neither merged nor refused')
  ok('pinnedMergeVerdict/reconciledMerges: no echo (old server) or a mismatch is refused; the graded head echoed is merged (#1356 review)')
} catch (e) { bad('pinned merge echo (#1356 review)', e) }

// ── 4. #1356 (triage #25): the trivy scan binds to the head CI graded ───────────────────────
try {
  const G = '9'.repeat(40)
  const ci = { signal: 'ci', passed: true, detail: 'PASS', head: G }
  const trivy = { signal: 'trivy', passed: true, detail: 'clean', found: 1, ingested: 1, unscanned: [], declared: false, scanned_sha: G, kahuna_sha: G }
  const others = [{ signal: 'commutativity', passed: true }, { signal: 'review', passed: true }]
  const same = [others[0], ci, others[1], trivy]
  assert.deepEqual(bindScanToGradedHead(same), same, 'equal SHAs pass through unchanged')
  const older = { ...trivy, scanned_sha: 'c'.repeat(40), kahuna_sha: 'c'.repeat(40) }
  const held = bindScanToGradedHead([others[0], ci, others[1], older])
  assert.equal(held[3].passed, false, 'trivy kahuna_sha != ci head HOLDs trivy')
  assert.match(held[3].detail, /^SCAN NOT OF THE GRADED HEAD \(HOLD\): CI graded 99999999, trivy scanned cccccccc\. clean$/)
  assert.equal(held[1], ci, 'the CI signal itself is untouched')
  const headless = bindScanToGradedHead([others[0], { ...ci, head: undefined }, others[1], trivy])
  assert.equal(headless[1].passed, false, 'a CI pass with no graded head HOLDs')
  assert.match(headless[1].detail, /CI pass carries no graded head/)
  // never turns a failing signal into a passing one
  const failingTrivy = { ...older, passed: false, detail: 'HIGH found' }
  assert.equal(bindScanToGradedHead([ci, failingTrivy])[1].passed, false)
  const failingCi = { signal: 'ci', passed: false, detail: 'HOLD' }
  const r = bindScanToGradedHead([failingCi, older])
  assert.equal(r[0], failingCi, 'a failing CI is left as it is')
  assert.equal(r[1], older, 'with no graded head to compare to, trivy is left as it is (CI already HOLDs the gate)')
  // #1356 review: the bind finds the scan by its label, so a mislabelled passing scan must not skip it.
  for (const label of ['Trivy', 'dependency-scan']) {
    const mis = bindScanToGradedHead([others[0], ci, others[1], { ...older, signal: label }])
    assert.equal(mis.length, 5, `a ${label}-labelled scan leaves no trivy signal: a HOLD is appended`)
    assert.deepEqual(mis[4], { signal: 'trivy', passed: false, detail: 'signal ERRORED — conservative-fail (HOLD): no trivy signal to bind the scan to the graded head' })
    assert.ok(mis.some((s) => !s.passed), 'the gate HOLDs')
  }
  const noCi = bindScanToGradedHead([others[0], others[1], trivy])
  assert.equal(noCi.at(-1).signal, 'ci')
  assert.equal(noCi.at(-1).passed, false, 'no ci signal: nothing to bind to, HOLD')
  // The workflow forces the label in code, ahead of the binds.
  const wf = readFileSync(new URL('../../skills/nextwave/per-wave-workflow.js', import.meta.url), 'utf8')
  assert.ok(wf.includes(".then((s) => ({ ...s, signal: 'trivy' })).then(trivyTreeBound)"), 'the trivy chain must force its label')
  ok('bindScanToGradedHead: a mislabelled scan or a missing ci signal HOLDs; the trivy label is forced (#1356 review)')
  ok('bindScanToGradedHead: trivy kahuna_sha != ci head HOLDs trivy; equal SHAs pass through; a headless CI pass HOLDs; never turns a fail into a pass (#1356)')
} catch (e) { bad('bindScanToGradedHead (#1356)', e) }

// ── 5. #1356 (triage #39): a flight's CI is graded in code ─────────────────────────────────────
try {
  const FH = 'f'.repeat(40) // the head the flight returned
  const job = (over = {}) => ({ name: 'test', conclusion: 'failure', started_at: '2026-10-25T04:30:00Z', finished_at: '2026-10-25T04:34:10Z', url: 'https://ci/j/1', ...over })
  const ev = (over = {}) => ({ issue: 7, pr_number: 107, head_sha: FH, head_sha_final: FH, wait: { ok: true, final_status: 'success', sha: FH }, ...over })
  const v = (e, head = FH) => flightCiVerdict(e, 7, head)

  const green = v(ev())
  assert.deepEqual(green, { issue: 7, outcome: 'proceed', head: FH, reason: 'CI green on head ffffffff' }, 'green on the flight head proceeds')

  const red = v(ev({ wait: { ok: true, final_status: 'failure', run_id: 5, url: 'https://ci/r/5' }, failed_jobs: [job(), job({ name: 'deploy', conclusion: 'skipped', started_at: null, finished_at: null })] }))
  assert.equal(red.outcome, 'needs_rework', 'failed jobs that ran are needs_rework')
  assert.equal(red.reason, 'CI red on head ffffffff: failed jobs test (https://ci/r/5)', 'the reason names the failed jobs and the run url; skipped jobs are ignored')
  assert.equal(v(ev({ wait: { ok: false, final_status: 'failed' }, failed_jobs: [job()] })).outcome, 'needs_rework', "GitLab's failed spelling is red too")

  // The Wave-Engineering/mattermost-crew#72 shape: every job failed at the instant it started (billing).
  const billing = [job({ name: 'a', started_at: '2026-10-25T04:39:00Z', finished_at: '2026-10-25T04:39:00Z' }), job({ name: 'b', started_at: null, finished_at: null })]
  const b = v(ev({ wait: { ok: true, final_status: 'failure' }, failed_jobs: billing }))
  assert.equal(b.outcome, 'blocked', 'failed jobs with started_at == finished_at (billing) are blocked, never reworked')
  assert.match(b.reason, /failed jobs never ran/)
  assert.equal(v(ev({ wait: { ok: true, final_status: 'failure' }, failed_jobs: [job(), billing[0]] })).outcome, 'blocked', 'one job that never ran holds the whole flight')
  assert.equal(v(ev({ wait: { ok: true, final_status: 'failure' }, failed_jobs: [job(), job({ conclusion: 'timed_out' })] })).outcome, 'blocked', 'an infra conclusion beside a real failure holds')
  assert.match(v(ev({ wait: { ok: true, final_status: 'failure' }, failed_jobs: [] })).reason, /failure with no failed jobs listed/)

  for (const wait of [{ ok: true, final_status: 'cancelled' }, { ok: true, final_status: 'timed_out' }, { ok: false, final_status: 'not_merge_result' }, { ok: false, error: 'No CI run found for ref x' }, {}, undefined]) {
    assert.equal(v(ev({ wait })).outcome, 'blocked', `${JSON.stringify(wait ?? 'absent')} is blocked`)
  }
  assert.match(v(ev({ wait: { ok: false, error: 'No CI run found for ref x' } })).reason, /no verdict: No CI run found/)

  for (const [what, e, head] of [
    ['a PR head that is not the flight head', ev({ head_sha: 'e'.repeat(40), head_sha_final: 'e'.repeat(40) }), FH],
    ['a head that moved between the reads', ev({ head_sha_final: 'e'.repeat(40) }), FH],
    ['an abbreviated flight head', ev({ head_sha: FH.slice(0, 12), head_sha_final: FH.slice(0, 12) }), FH.slice(0, 12)],
    ['no flight head', ev(), null],
  ]) {
    const r = v(e, head)
    assert.equal(r.outcome, 'blocked', `${what} is blocked`)
    assert.match(r.reason, /not the head the flight returned/)
  }
  assert.equal(v(null).outcome, 'blocked', 'null evidence is blocked')
  assert.match(v(null).reason, /no CI evidence for #7/)
  assert.equal(v(ev({ issue: 8 })).outcome, 'blocked', 'evidence about another issue is blocked')
  const pushed = v(ev({ blocked: true, block_reason: 'pre-push gate refused' }))
  assert.equal(pushed.outcome, 'blocked')
  assert.match(pushed.reason, /push rejected: pre-push gate refused/)
  for (const r of [red, b, pushed]) assert.equal(r.head, null, 'only proceed carries a head')
  // #1356 review: a verdict with no PR to merge binds to nothing, and a green run must be of the flight head.
  for (const pr of [undefined, null, 0, -1, 1.5, '107']) {
    const r = v(ev({ pr_number: pr }))
    assert.equal(r.outcome, 'blocked', `pr_number ${JSON.stringify(pr)} is blocked`)
    assert.equal(r.reason, 'the flight CI evidence carries no PR number')
  }
  const tip = { target_sha: 'b'.repeat(40) }
  const elsewhere = v(ev({ ...tip, wait: { ok: true, final_status: 'success', sha: 'e'.repeat(40) } }))
  assert.equal(elsewhere.outcome, 'blocked', 'green on another sha, with no merge commit read, is blocked')
  assert.match(elsewhere.reason, /^a green run not bound to the flight head ffffffff: .*no merge commit read for it has the head as its second parent/)
  assert.match(v(ev({ ...tip, wait: { ok: true, final_status: 'success' } })).reason, /^a green run not bound to the flight head ffffffff: .*names no run sha/, 'green with no sha is blocked')
  assert.equal(v(ev({ wait: { ok: true, final_status: 'success', sha: 'e'.repeat(40) } })).outcome, 'blocked', 'green elsewhere with no kahuna tip is blocked')

  // #1356 C1: a GitLab merged-results run is on an ephemeral merge commit, never the flight head.
  // It binds through mergeResultVerdict's rule: parents exactly [kahuna tip, flight head].
  const KT = 'b'.repeat(40) // the kahuna tip, read last
  const MCS = 'd'.repeat(40) // the run's merge commit
  const gl = (parent_ids, over = {}) => ev({ target_sha: KT, wait: { ok: true, final_status: 'success', sha: MCS }, merge_commit: { sha: MCS, parent_ids }, ...over })
  assert.deepEqual(v(gl([KT, FH])), { issue: 7, outcome: 'proceed', head: FH, reason: 'CI green on head ffffffff (merge commit dddddddd onto the kahuna tip)' }, 'a GitLab merge commit [kahuna tip, flight head] proceeds')
  for (const [what, e, re] of [
    ['a wrong second parent', gl([KT, 'e'.repeat(40)]), /no merge commit read for it has the head as its second parent/],
    ['a stale first parent (the kahuna moved)', gl(['9'.repeat(40), FH]), /STALE: the merge-result pipeline was built on target 99999999, and the target is now bbbbbbbb/],
    ['no kahuna tip read', gl([KT, FH], { target_sha: undefined }), /the target tip was not read/],
    ['a merge commit read for another sha', gl([KT, FH], { merge_commit: { sha: 'e'.repeat(40), parent_ids: [KT, FH] } }), /no merge commit read for it has the head as its second parent/],
    ['three parents', gl([KT, FH, 'e'.repeat(40)]), /no merge commit read for it has the head as its second parent/],
  ]) {
    const r = v(e)
    assert.equal(r.outcome, 'blocked', `${what} is blocked`)
    assert.match(r.reason, re, what)
    assert.equal(r.head, null)
  }
  // #1357: CI never started (Wave-Engineering/mattermost-crew#78's criss-cross base): fail fast with the named reason.
  const never = v(ev({ wait: {}, probe: { status: 'no_checks_yet', blocker: 'conflicts', mergeable_state: 'CONFLICTING/DIRTY' } }))
  assert.equal(never.outcome, 'blocked', 'flightCiVerdict: probe no_checks_yet is blocked')
  assert.equal(never.reason, `no run for head ${FH}; mergeable=CONFLICTING/DIRTY; blocker=conflicts (pr_wait_ci no_checks_yet)`)
  assert.equal(v(ev({ probe: { status: 'no_checks_yet', blocker: 'conflicts' } })).outcome, 'proceed', 'a graded green beats a stale no-run probe')
  assert.match(v(ev({ wait: {}, probe: { status: 'no_checks_yet', blocker: 'draft' } })).reason, /^CI could not grade head/, 'a draft probe is not the no-run reason')
  assert.match(v(ev({ wait: { ok: true, final_status: 'timed_out' }, probe: { status: 'no_checks_yet', blocker: 'checks_not_registered' } })).reason,
    /^CI could not grade head .*final_status=timed_out/, 'a queued run (checks_not_registered) is graded by the wait, not failed fast')
  // #1371 review: a code-red the agent waited on anyway is still rework, whatever the probe said.
  const redAnyway = v(ev({ wait: { ok: true, final_status: 'failure', url: 'https://ci/r/9' }, failed_jobs: [job()], probe: { status: 'no_checks_yet', blocker: 'conflicts' } }))
  assert.equal(redAnyway.outcome, 'needs_rework', 'a graded code-red beats a no-run probe')
  assert.match(v(ev({ wait: { ok: false, error: 'No CI run found for ref x' } })).reason, /must run on PRs into kahuna\/\*/, 'no run names the CI trigger')
  assert.doesNotMatch(v(ev({ wait: { ok: false, error: 'rate limited' } })).reason, /kahuna\/\*/, 'other errors carry no trigger hint')
  ok('flightCiVerdict: green proceeds; ran-red reworks; billing/infra/no-verdict, moved or foreign heads, null evidence and a rejected push are blocked (#1356)')

  // §3.3 resume: an already-present flight whose head is already in the kahuna merged in a dead run.
  const inK = { issue: 7, already_integrated: true, integrated_head: FH, integrated_exit: 0 }
  assert.deepEqual(flightCiVerdict(inK, 7, FH, 'already-present'), { issue: 7, outcome: 'integrated', head: FH, reason: 'head ffffffff is already in the kahuna (a resumed flight)' })
  for (const [what, e, head, status] of [
    ['an implemented flight (it committed nothing new)', inK, FH, 'implemented'],
    ['no status', inK, FH, undefined],
    ['another sha checked', { ...inK, integrated_head: 'e'.repeat(40) }, FH, 'already-present'],
    ['a non-zero exit', { ...inK, integrated_exit: 1 }, FH, 'already-present'],
    ['no exit', { ...inK, integrated_exit: undefined }, FH, 'already-present'],
    ['no flight head', inK, null, 'already-present'],
  ]) {
    const r = flightCiVerdict(e, 7, head, status)
    assert.equal(r.outcome, 'blocked', `${what} is blocked`)
    assert.match(r.reason, /committed nothing new/)
  }
  assert.equal(flightCiVerdict(inK, 7, FH, 'implemented', true).outcome, 'integrated', 'a rework flight at its new head, already merged, is integrated')
  assert.equal(flightCiVerdict(inK, 7, FH, 'rework_not_applied', true).outcome, 'blocked', 'a rework that declined is not a resume')
  assert.equal(flightCiVerdict({ ...ev(), already_integrated: false }, 7, FH, 'already-present').outcome, 'proceed', 'not integrated: graded as usual')
  ok('flightCiVerdict: an already-present flight already in the kahuna is integrated; any other claim of it is blocked (#1356)')

  const fp = flightCiPrompt({ waveId: 'W-7', issue: 7, branch: 'feature/7-W-7-x', worktree: '/wt/7', kahunaBranch: 'kahuna/692-x', targetRepo: 'org/repo', ciWaitSec: 600 })
  assert.match(fp, /git -C \/wt\/7 push origin feature\/7-W-7-x/)
  assert.ok(fp.includes('merge-tree --write-tree origin/kahuna/692-x $(git -C /wt/7 rev-parse HEAD)) && test "$t" = "$(git -C /wt/7 rev-parse origin/kahuna/692-x^{tree})"; echo "exit=$?"'), 'with no flight head it checks the worktree HEAD, by content')
  assert.ok(!fp.includes('is-ancestor'), 'not by ancestry: a squash merge would never match')
  assert.ok(fp.indexOf('merge-tree') < fp.indexOf('push origin'), 'the integrated check runs before the push')
  const fp2 = flightCiPrompt({ waveId: 'W-7', issue: 7, branch: 'b', worktree: '/wt/7', kahunaBranch: 'kahuna/692-x', targetRepo: 'org/repo', ciWaitSec: 600, flightHead: FH })
  assert.ok(fp2.includes(`merge-tree --write-tree origin/kahuna/692-x ${FH})`), 'it checks the head the flight returned')
  assert.match(fp, /pr_create, NOT as a draft/)
  assert.match(fp, /require_merge_result=true, pr_number=<n>,\n {3}timeout_sec=600, poll_interval_sec=15/)
  assert.ok(fp.includes('GitHub: ref="feature/7-W-7-x"') && fp.includes('GitLab: ref="refs/merge-requests/<n>/merge"'), 'the flight names its ref per platform')
  assert.ok(fp.indexOf('pr_wait_ci(') < fp.indexOf('call sdlc-server ci_wait_run'), 'the flight probes before it waits')
  assert.ok(FLIGHT_CI_EVIDENCE.properties.probe, 'the flight evidence carries the probe')
  assert.match(fp, /ci_failed_jobs\(run_id=<wait\.run_id>/)
  assert.match(fp, /report it as head_sha,/)
  assert.match(fp, /report it as head_sha_final,/)
  assert.match(fp, /Do NOT merge, do NOT mark anything ready, do NOT judge/)
  assert.equal(FLIGHT_CI_EVIDENCE.additionalProperties, false)
  assert.deepEqual(FLIGHT_CI_EVIDENCE.required, ['issue'])
  ok('flightCiPrompt gathers push, PR, ci_wait_run, ci_failed_jobs and both head reads, and never merges (#1356)')
} catch (e) { bad('flight CI (#1356)', e) }

console.log('')
if (failures) { console.log(`  ${failures} assertion group(s) failed`); process.exit(1) }
console.log('  all gate-signal checks passed')
