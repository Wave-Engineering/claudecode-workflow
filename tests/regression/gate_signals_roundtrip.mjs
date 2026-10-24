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
  assert.ok(at('report it as head_sha,') < at('Call sdlc-server ci_wait_run'), 'the first head read comes before ci_wait_run')
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
    wait: NOT_FOUND,
    merge_pipelines: [{ id: 9, ref: REF, status: 'success', sha: MERGE }],
    merge_commit: { sha: MERGE, parent_ids: [TARGET, HEAD] },
    ...over,
  })

  const primary = ciVerdict({ pr_number: PR, head_sha: HEAD, head_sha_final: HEAD, wait: { ok: true, final_status: 'success' } }, PR)
  assert.equal(primary.signal, 'ci')
  assert.equal(primary.passed, true, 'a ci_wait_run success passes on the primary path')
  assert.match(primary.detail, /^PASS \(ci_wait_run\)/)

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
