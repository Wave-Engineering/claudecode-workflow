// merge_result.mjs — cc-workflow#1211: the merge-result CI rule, as code.
//
// Run by tests/regression/test_merge_result.sh (picked up by scripts/ci/validate.sh).
// mergeResultVerdict() is the predicate the campaign release gate grades its CI evidence with
// (and, after #1211's per-wave half, the per-wave CI signal too). It is pure, so every rule is a
// deterministic unit test: no agent, no GitLab.

import {
  mergeResultVerdict,
  directMergeReadSteps,
  headReadLines,
  targetReadLines,
  isMergeSha,
  MERGE_RESULT_EVIDENCE,
  noRunHold,
  noRunProbeLines,
  ciWaitRefLines,
} from '../../skills/nextwave/merge-result.js'

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

console.log('merge_result — #1211 merge-result CI rule')
console.log('──────────────────────────────────────────')

const N = 42
const HEAD = '1'.repeat(40) // the MR's current head
const TARGET = '2'.repeat(40) // the target branch tip
const MERGE = '3'.repeat(40) // the ephemeral merge commit a merged-results pipeline runs on
const OLD = '4'.repeat(40) // a previous head
const REF = `refs/merge-requests/${N}/merge`

// sdlc#585's signature: ci_wait_run saw no pipeline at all.
const NOT_FOUND = { ok: false, error: `No CI run found for ref 'campaign/56-x'` }
// The measured shape of a green GitLab merged-results pipeline (15/15 on 2026-10-19).
const greenMerge = (over = {}) => ({
  pr_number: N,
  head_sha: HEAD,
  head_sha_final: HEAD, // read again after the last read, unmoved
  target_sha: TARGET, // #1356: the target tip, read last
  wait: NOT_FOUND,
  merge_pipelines: [{ id: 900, ref: REF, status: 'success', sha: MERGE }],
  merge_commit: { sha: MERGE, parent_ids: [TARGET, HEAD] },
  ...over,
})

// ── the primary path ────────────────────────────────────────────────────────────────────────
{
  const v = mergeResultVerdict({ pr_number: N, head_sha: HEAD, head_sha_final: HEAD, target_sha: TARGET, wait: { ok: true, final_status: 'success', sha: HEAD } })
  ok(v.pass === true && v.path === 'ci_wait_run', 'ci_wait_run success passes on the primary path')
  ok(v.head === HEAD, 'a primary pass names the head it graded, for the merge to bind to')
}

// ── the target tip (#1356, triage #7) ───────────────────────────────────────────────────────
{
  const NEWTIP = '8'.repeat(40) // the target after trunk moved past the pipeline's merge commit
  const gl = (over = {}) => ({ pr_number: N, head_sha: HEAD, head_sha_final: HEAD, target_sha: TARGET, wait: { ok: true, final_status: 'success', sha: MERGE }, merge_commit: { sha: MERGE, parent_ids: [TARGET, HEAD] }, ...over })
  ok(mergeResultVerdict(gl()).pass === true, 'GitLab ci_wait_run success on a merge commit with parents [target tip, head] passes')
  const staleP = mergeResultVerdict(gl({ target_sha: NEWTIP }))
  ok(staleP.pass === false && staleP.path === 'ci_wait_run' && /STALE: .*built on target 22222222, and the target is now 88888888/.test(staleP.reason), 'GitLab ci_wait_run success on a merge commit whose parent[0] is not the target tip HOLDs STALE')
  const staleD = mergeResultVerdict(greenMerge({ target_sha: NEWTIP }))
  ok(staleD.pass === false && staleD.path === 'direct' && /STALE/.test(staleD.reason), 'direct-path merge commit with stale parent[0] HOLDs STALE')
  const unread = mergeResultVerdict(gl({ merge_commit: undefined }))
  ok(unread.pass === false && /no merge commit read/.test(unread.reason), 'a ci_wait_run success on a non-head sha with no merge commit read HOLDs')
  for (const target_sha of [undefined, '', 'main', 'AB'.repeat(20)]) {
    ok(mergeResultVerdict(gl({ target_sha })).pass === false && mergeResultVerdict(greenMerge({ target_sha })).pass === false, `a missing or malformed target tip (${JSON.stringify(target_sha)}) HOLDs on both paths`)
  }
  const noSha = mergeResultVerdict({ pr_number: N, head_sha: HEAD, head_sha_final: HEAD, target_sha: TARGET, wait: { ok: true, final_status: 'success' } })
  ok(noSha.pass === false && /names no run sha/.test(noSha.reason), 'a ci_wait_run success without wait.sha HOLDs')
  const gh = mergeResultVerdict({ pr_number: N, head_sha: HEAD, head_sha_final: HEAD, target_sha: NEWTIP, wait: { ok: true, final_status: 'success', sha: HEAD } })
  ok(gh.pass === true && gh.head === HEAD, 'GitHub success with wait.sha == head passes (the documented limit: no merge commit to check)')
  const ff = mergeResultVerdict(greenMerge({ target_sha: NEWTIP, merge_pipelines: [{ id: 900, ref: REF, status: 'success', sha: HEAD }], merge_commit: undefined }))
  ok(ff.pass === true, 'a direct-path pipeline whose sha IS the head has no merge commit, so the tip rule does not apply')
  const steps = directMergeReadSteps({ targetRepo: 'grp/sub/proj', prNumber: N }).join('\n')
  ok(/Whenever ci_wait_run returned success with a\s+sha that is not the head/.test(steps), 'the direct-read steps ask for the merge commit of a graded green on a non-head sha')
  const tip = targetReadLines({ targetRepo: 'grp/sub/proj', branch: 'main', field: 'target_sha' }).join('\n')
  ok(/report it as target_sha/.test(tip) && tip.includes('gh api repos/grp/sub/proj/branches/main --jq .commit.sha') && /repository\/branches\/<url-encoded main>" \| jq -r \.commit\.id/.test(tip), 'the target read names its field and covers GitHub and GitLab')
  ok(MERGE_RESULT_EVIDENCE.properties.target_sha?.type === 'string' && MERGE_RESULT_EVIDENCE.properties.wait.properties.sha?.type === 'string', 'MERGE_RESULT_EVIDENCE carries target_sha and wait.sha')
}

// ── babelfish's four, and the no-answer pair ────────────────────────────────────────────────
{
  const v = mergeResultVerdict(greenMerge())
  ok(v.pass === true && v.path === 'direct', 'ci_wait_run returns nothing, the direct read is green with parents [target, head]: PASS')
  ok(/#900/.test(v.reason) && /merges the head 11111111/.test(v.reason), 'the pass names the pipeline and the head it merges')
  ok(v.head === HEAD, 'a direct pass names the head it bound, for the merge to bind to')
}
{
  const v = mergeResultVerdict(greenMerge({ merge_commit: { sha: MERGE, parent_ids: [TARGET, OLD] } }))
  ok(v.pass === false && /stale/.test(v.reason), 'green, but parent[1] is not the head: HOLD (a run for a previous head)')
}
{
  const v = mergeResultVerdict(greenMerge({ merge_pipelines: [{ id: 900, ref: REF, status: 'failed', sha: MERGE }] }))
  ok(v.pass === false && /#900, is failed/.test(v.reason), 'ci_wait_run returns nothing, the direct read is red: HOLD')
}
for (const red of ['failure', 'cancelled', 'failed', 'canceled']) {
  const v = mergeResultVerdict(greenMerge({ wait: { ok: true, final_status: red } }))
  ok(v.pass === false && v.path === 'ci_wait_run' && /never overrides/.test(v.reason), `a graded ${red} from ci_wait_run plus a green, bound direct read still HOLDs`)
}

// ── what "no verdict" covers: each one opens the direct read ────────────────────────────────
for (const wait of [NOT_FOUND, { ok: true, final_status: 'timed_out' }, { ok: true, final_status: 'not_merge_result', reason: 'not_merge_result' }, { ok: false, reason: 'not_merge_result', final_status: 'not_merge_result', error: 'x' }, {}, undefined]) {
  const label = JSON.stringify(wait ?? 'absent')
  ok(mergeResultVerdict(greenMerge({ wait })).pass === true, `no verdict (${label}) + a green, bound direct read: PASS`)
  ok(mergeResultVerdict({ pr_number: N, head_sha: HEAD, head_sha_final: HEAD, wait }).pass === false, `no verdict (${label}) and no direct read: HOLD`)
}

// ── the head is read twice (#1211 review I-1, I-2) ──────────────────────────────────────────
{
  const NEW = '7'.repeat(40) // the head after a push while the gate waited
  // The review's chain: the head moves during the wait, ci_wait_run refuses ("moved while
  // ci_wait_run was waiting", not_merge_result), the new head gets no /merge pipeline, and the
  // newest one is still the OLD head's, green, its second parent the head read before the wait.
  const moved = {
    ok: false,
    final_status: 'not_merge_result',
    reason: 'not_merge_result',
    error: `#${N} moved while ci_wait_run was waiting: the run that completed validated the PREVIOUS head`,
  }
  const v = mergeResultVerdict(greenMerge({ wait: moved, head_sha_final: NEW }))
  ok(v.pass === false && /head moved during grading \(11111111 → 77777777\)/.test(v.reason), "ci_wait_run's own head-moved refusal never becomes a pass on the previous head's /merge pipeline")
  const primary = mergeResultVerdict({ pr_number: N, head_sha: HEAD, head_sha_final: NEW, wait: { ok: true, final_status: 'success' } })
  ok(primary.pass === false && /head moved/.test(primary.reason), 'a ci_wait_run success HOLDs when the head moved before the last read (it graded the previous head)')
  // 'AB'.repeat(20): an UPPERCASE 40-hex SHA (HEAD is all digits, so its toUpperCase() is itself).
  for (const head_sha_final of [undefined, '', 'HEAD', 'AB'.repeat(20)]) {
    const p = mergeResultVerdict({ pr_number: N, head_sha: HEAD, head_sha_final, wait: { ok: true, final_status: 'success' } })
    ok(p.pass === false && p.head === undefined, `a primary success with no well-formed final head read (${JSON.stringify(head_sha_final)}) HOLDs, naming no head`)
  }
  // A graded red stays final, and says so, even when the head reads are missing.
  const red = mergeResultVerdict({ pr_number: N, wait: { ok: true, final_status: 'failure' } })
  ok(red.pass === false && red.path === 'ci_wait_run', 'a graded red HOLDs as a red, whatever the head reads say')
}

// ── the four direct-read rules ──────────────────────────────────────────────────────────────
{
  // 1. only the merge-result ref counts
  const detached = greenMerge({ merge_pipelines: [{ id: 901, ref: `refs/merge-requests/${N}/head`, status: 'success', sha: HEAD }] })
  ok(mergeResultVerdict(detached).pass === false, 'a green DETACHED /head pipeline never satisfies the gate (#476)')
  const branch = greenMerge({ merge_pipelines: [{ id: 902, ref: 'campaign/56-x', status: 'success', sha: HEAD }] })
  ok(mergeResultVerdict(branch).pass === false, 'a green BRANCH pipeline never satisfies the gate (#904)')
  const otherMr = greenMerge({ merge_pipelines: [{ id: 903, ref: `refs/merge-requests/${N + 1}/merge`, status: 'success', sha: MERGE }] })
  ok(mergeResultVerdict(otherMr).pass === false, "another MR's merge-result pipeline never satisfies the gate")
  // 2. newest wins, whatever order the list arrives in
  const newerRed = greenMerge({
    merge_pipelines: [
      { id: 950, ref: REF, status: 'failed', sha: '5'.repeat(40) },
      { id: 900, ref: REF, status: 'success', sha: MERGE },
    ],
  })
  ok(mergeResultVerdict(newerRed).pass === false, 'an older green run cannot hide a newer red one')
  const newerGreen = greenMerge({
    merge_pipelines: [
      { id: 850, ref: REF, status: 'failed', sha: '5'.repeat(40) },
      { id: 900, ref: REF, status: 'success', sha: MERGE },
      { id: 860, ref: `refs/merge-requests/${N}/head`, status: 'failed', sha: HEAD },
    ],
  })
  ok(mergeResultVerdict(newerGreen).pass === true, 'a retried green run supersedes the older red one (the #1211 infra-retry case)')
  const unordered = greenMerge({
    merge_pipelines: [
      { id: '950', ref: REF, status: 'failed', sha: '5'.repeat(40) },
      { id: 900, ref: REF, status: 'success', sha: MERGE },
    ],
  })
  const u = mergeResultVerdict(unordered)
  ok(u.pass === false && /no integer id/.test(u.reason), 'a merge-result run with a non-integer id HOLDs rather than vanishing behind an older green')
  // 3. it must be green
  const running = greenMerge({ merge_pipelines: [{ id: 900, ref: REF, status: 'running', sha: MERGE }] })
  ok(mergeResultVerdict(running).pass === false, 'a still-running pipeline HOLDs')
  // 4. bound to the current head
  const ff = greenMerge({ merge_pipelines: [{ id: 900, ref: REF, status: 'success', sha: HEAD }], merge_commit: undefined })
  ok(mergeResultVerdict(ff).pass === true, 'a merge ref that IS the head (fast-forward) is bound without a merge commit')
  const otherCommit = greenMerge({ merge_commit: { sha: '6'.repeat(40), parent_ids: [TARGET, HEAD] } })
  ok(mergeResultVerdict(otherCommit).pass === false, "the parents of some OTHER commit do not bind this pipeline")
  const octopus = greenMerge({ merge_commit: { sha: MERGE, parent_ids: [TARGET, HEAD, OLD] } })
  ok(mergeResultVerdict(octopus).pass === false, 'a merge commit must have exactly two parents')
  const flipped = greenMerge({ merge_commit: { sha: MERGE, parent_ids: [HEAD, TARGET] } })
  ok(mergeResultVerdict(flipped).pass === false, 'the head must be the SECOND parent (the first is the target tip)')
  const oneParent = greenMerge({ merge_commit: { sha: MERGE, parent_ids: [HEAD] } })
  ok(mergeResultVerdict(oneParent).pass === false, 'a one-parent commit whose sha is not the head cannot be bound: HOLD')
  const noParents = greenMerge({ merge_commit: { sha: MERGE } })
  ok(mergeResultVerdict(noParents).pass === false, 'a merge commit read without parent_ids cannot be bound: HOLD')
  const noCommit = greenMerge({ merge_commit: undefined })
  ok(mergeResultVerdict(noCommit).pass === false, 'a green merge-commit pipeline with no commit read cannot be bound: HOLD')
}

// ── a vacuous match must not bind ───────────────────────────────────────────────────────────
{
  // undefined === undefined would "bind" an unread pipeline to unread parents.
  const vacuous = greenMerge({ merge_pipelines: [{ id: 900, ref: REF, status: 'success' }], merge_commit: { parent_ids: [TARGET, HEAD] } })
  ok(mergeResultVerdict(vacuous).pass === false, 'a pipeline with no sha, matched to a commit with no sha, HOLDs')
  for (const head_sha of [undefined, '', 'HEAD', '1234abc']) {
    ok(mergeResultVerdict(greenMerge({ head_sha })).pass === false, `a missing or malformed head SHA (${JSON.stringify(head_sha)}) HOLDs`)
  }
  const sha256 = 'a'.repeat(64)
  ok(mergeResultVerdict(greenMerge({ head_sha: sha256, head_sha_final: sha256, merge_commit: { sha: MERGE, parent_ids: [TARGET, sha256] } })).pass === true, 'a SHA-256 head binds like a SHA-1 one')
  ok(isMergeSha(HEAD) && isMergeSha(sha256) && isMergeSha('ab'.repeat(20)) && !isMergeSha('AB'.repeat(20)) && !isMergeSha('1234abc') && !isMergeSha(undefined) && !isMergeSha(42), 'isMergeSha accepts a full lowercase SHA-1 or SHA-256, and nothing else')
}

// ── absent evidence ─────────────────────────────────────────────────────────────────────────
{
  ok(mergeResultVerdict(undefined).pass === false, 'no evidence at all HOLDs')
  const errored = mergeResultVerdict({ error: 'agent timed out' })
  ok(errored.pass === false && /agent timed out/.test(errored.reason), 'an errored evidence node HOLDs and says why')
  ok(mergeResultVerdict({ ...greenMerge(), pr_number: '42' }).pass === false, 'a PR number that is not an integer HOLDs')
}

// ── #1357: the no-run probe fails fast, in code ─────────────────────────────────────────────
{
  const conflicts = { status: 'no_checks_yet', blocker: 'conflicts', mergeable_state: 'CONFLICTING/DIRTY' }
  ok(noRunHold(conflicts, HEAD) === `no run for head ${HEAD}; mergeable=CONFLICTING/DIRTY; blocker=conflicts (pr_wait_ci no_checks_yet)`,
    'noRunHold: no_checks_yet / conflicts gives the named reason')
  ok(noRunHold({ ...conflicts, blocker: 'draft' }, HEAD) === null && noRunHold({ status: 'no_checks_configured', blocker: 'draft' }, HEAD) === null,
    'noRunHold: a draft blocker is never fail-fast, on either status')
  ok(noRunHold({ status: 'no_checks_configured' }, HEAD) === `no run for head ${HEAD}; mergeable=unknown (pr_wait_ci no_checks_configured)`,
    'noRunHold: no mergeable_state prints mergeable=unknown')
  ok(noRunHold({ status: 'no_checks_yet' }, 'abc') === 'no run for head unread; mergeable=unknown (pr_wait_ci no_checks_yet)', 'noRunHold: an unread head says so')
  for (const p of [undefined, null, {}, { status: 'pending' }, { status: 'success' }, 'no_checks_yet']) {
    ok(noRunHold(p, HEAD) === null, `noRunHold: ${JSON.stringify(p)} holds nothing`)
  }
  const probed = mergeResultVerdict(greenMerge({ wait: NOT_FOUND, merge_pipelines: [], probe: conflicts }))
  ok(probed.pass === false && probed.path === 'probe' && probed.reason.startsWith(`no run for head ${HEAD}`),
    'mergeResultVerdict: a no-run probe with no wait verdict HOLDs path probe')
  const graded = mergeResultVerdict({ pr_number: N, head_sha: HEAD, head_sha_final: HEAD, target_sha: TARGET, wait: { ok: true, final_status: 'success', sha: HEAD }, probe: conflicts })
  const red = mergeResultVerdict(greenMerge({ wait: { ok: true, final_status: 'failure' }, probe: conflicts }))
  ok(graded.pass === true && red.pass === false && red.path === 'ci_wait_run',
    'mergeResultVerdict: a graded success beats a no-run probe; a graded red still wins first')
  ok(mergeResultVerdict(greenMerge({ probe: { ...conflicts, blocker: 'draft' } })).pass === true, 'mergeResultVerdict: a draft probe leaves the direct read to grade')
  ok(MERGE_RESULT_EVIDENCE.properties.probe?.additionalProperties === true, 'MERGE_RESULT_EVIDENCE carries the probe, copied as returned')
  const steps = noRunProbeLines({ targetRepo: 'grp/proj', prNumber: N }).join('\n')
  ok(steps.includes(`pr_wait_ci(number=${N}, repo="grp/proj", settle_window_sec=90, timeout_sec=30, poll_interval_sec=15)`) && /AND probe\.blocker is not "draft"/.test(steps),
    'noRunProbeLines: the probe call and its draft exemption')
  const refs = ciWaitRefLines({ prNumber: N, headBranch: 'kahuna/7-x' }).join('\n')
  ok(refs.includes('GitHub: ref="kahuna/7-x"') && refs.includes(`GitLab: ref="${REF}"`), 'ciWaitRefLines: the ref per platform')
}

// ── the contract the agent fills ────────────────────────────────────────────────────────────
{
  ok(MERGE_RESULT_EVIDENCE.additionalProperties === false, 'MERGE_RESULT_EVIDENCE allows no unknown top-level fields')
  ok(JSON.stringify(MERGE_RESULT_EVIDENCE.required) === JSON.stringify(['pr_number', 'wait']), 'MERGE_RESULT_EVIDENCE requires pr_number and wait')
  const steps = directMergeReadSteps({ targetRepo: 'grp/sub/proj', prNumber: N }).join('\n')
  ok(steps.includes(`merge_requests/${N}/pipelines?per_page=100`), 'the direct read lists the MR pipelines')
  ok(/List EVERY pipeline the MR has, unfiltered/.test(steps), 'the agent reports the list unfiltered (the filter is code)')
  ok(/repository\/commits\/<its sha>" \| jq '\{sha: \.id, parent_ids\}'/.test(steps), "the direct read fetches the merge commit's parents")
  ok(/ONLY when ci_wait_run gave NO verdict/.test(steps) && /a graded result is final/.test(steps), 'the direct read is a fallback, never an override')
  ok(MERGE_RESULT_EVIDENCE.properties.head_sha_final?.type === 'string', 'MERGE_RESULT_EVIDENCE carries the second head read')
  const read = headReadLines({ targetRepo: 'grp/sub/proj', prNumber: N, field: 'head_sha_final' }).join('\n')
  ok(/report it as head_sha_final/.test(read), 'the head read names the field it fills')
  ok(read.includes(`gh -R grp/sub/proj pr view ${N} --json headRefOid -q .headRefOid`) && read.includes(`merge_requests/${N}" | jq -r '.diff_refs.head_sha // .sha'`), 'the head read covers GitHub and GitLab')
}

console.log('')
if (failed > 0) {
  console.error(`  ${failed} check(s) failed`)
  process.exit(1)
}
console.log(`  all ${passed} merge-result checks passed`)
