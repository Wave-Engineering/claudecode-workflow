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
  campaignBranchFor,
  waveKahunaFor,
  isIntegrated,
  resolveIntentTier,
  routeVerdict,
  routeJudgment,
  routeRelease,
  runCampaign,
  waveOversightPrompt,
  dodVerificationPrompt,
  releaseCiPrompt,
  releaseMergePrompt,
  DOD_VERDICT,
  RELEASE_RESULT,
  JUDGMENT_RESULT,
} from '../../skills/nextwave/campaign-loop.js'
import { directMergeReadSteps } from '../../skills/nextwave/merge-result.js'
import { readFileSync } from 'node:fs'

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

// ── #1052 branch topology (campaign/ vs kahuna/ — the git D/F constraint) ─────
ok(campaignBranchFor({ planId: 56, slug: 'Orion Plan' }) === 'campaign/56-orion-plan', 'campaignBranchFor: campaign/<planId>-<slug>, slugified')
ok(waveKahunaFor({ planId: 56, waveId: 'W-1' }) === 'kahuna/56-W-1', 'waveKahunaFor: kahuna/<planId>-<waveId> (plan-namespaced — two campaigns cannot collide on kahuna/W-1)')
// The prefixes MUST differ: git cannot hold a branch that is a directory prefix of another branch
// (`campaign/56-x` + `campaign/56-x/W-1` → fatal: cannot lock ref … exists). A shared prefix would
// make every wave branch unrepresentable, so this is a correctness assertion, not cosmetics.
{
  const camp = campaignBranchFor({ planId: 56, slug: 'x' })
  const kah = waveKahunaFor({ planId: 56, waveId: 'W-1' })
  ok(!kah.startsWith(`${camp}/`) && !camp.startsWith(`${kah}/`), '#1052: wave kahuna is NOT a path-child of the campaign branch (git D/F ref conflict)')
}
ok(waveKahunaFor({ waveId: 'W-1' }) === 'kahuna/W-1', 'waveKahunaFor without planId → kahuna/<waveId>')
// The campaign slug is human-typed (a plan title), so a case-only restatement must NOT resolve to a
// second campaign branch — git refs are case-sensitive but macOS/Windows checkouts are not, so the
// two could never coexist anyway. The waveId is engine-generated and stays verbatim (one wave, one
// spelling, matching resume.js's flight-branch names).
ok(campaignBranchFor({ planId: 56, slug: 'OrIon PLAN' }) === campaignBranchFor({ planId: 56, slug: 'orion plan' }),
  '#1052: campaign branch is case-INSENSITIVE in the slug (a retitled plan must not fork a second campaign branch)')
ok(waveKahunaFor({ planId: 56, waveId: 'W-1' }) !== waveKahunaFor({ planId: 56, waveId: 'w-1' }),
  '#1052: waveId casing is preserved verbatim (resume.js builds flight branches + its cleanup glob from the same un-lowercased id)')

// ── isIntegrated (the landed predicate, incl. the legacy-record path) ─────────
ok(isIntegrated({ integrated: true }) === true, 'isIntegrated: integrated:true → landed')
ok(isIntegrated({ integrated: false, promoted: true }) === false, 'isIntegrated: explicit integrated:false WINS over a stale promoted:true')
ok(isIntegrated({ promoted: true }) === true, 'isIntegrated: legacy record (promoted only) → landed — a mid-campaign engine upgrade must not stall')
ok(isIntegrated({ promoted: false }) === false, 'isIntegrated: legacy record, not landed')
ok(isIntegrated({}) === false && isIntegrated(null) === false, 'isIntegrated: absence → not landed (conservative)')

// ── routeVerdict ──────────────────────────────────────────────────────────────
ok(routeVerdict({ gate: 'PASS', integrated: true }).advance === true, 'routeVerdict PASS+integrated → advance')
ok(routeVerdict({ gate: 'PASS', integrated: false }).advance === false, 'routeVerdict PASS+!integrated → HOLD (integrated≠delivered)')
ok(routeVerdict({ gate: 'PASS', promoted: true }).advance === true, 'routeVerdict PASS+promoted (legacy record) → advance')
ok(routeVerdict({ gate: 'PASS', promoted: false }).advance === false, 'routeVerdict PASS+!promoted → HOLD')
ok(routeVerdict({ gate: 'HOLD' }).advance === false, 'routeVerdict HOLD → hold')
ok(routeVerdict({ gate: 'SKIPPED' }).advance === false, 'routeVerdict SKIPPED → hold')
ok(routeVerdict({}).advance === false, 'routeVerdict {} → hold (conservative)')

// ── #1052 routeRelease — the SINGLE protected-branch write predicate ──────────
const PLAN = [{ id: 'w1' }, { id: 'w2' }, { id: 'w3' }]
const MET = { met: true }
ok(routeRelease({ report: { outcome: 'completed', wavesAdvanced: ['w1', 'w2', 'w3'] }, allWaves: PLAN, dod: MET }).release === true, 'routeRelease: complete plan + DoD met → RELEASE')
ok(routeRelease({ report: { outcome: 'held', heldAt: 'w2', wavesAdvanced: ['w1'] }, allWaves: PLAN, dod: MET }).release === false, 'routeRelease: campaign held → block (even with a met DoD)')
ok(routeRelease({ report: { outcome: 'completed', wavesAdvanced: ['w1', 'w2'] }, allWaves: PLAN, dod: MET }).release === false, 'routeRelease: plan INCOMPLETE (w3 missing) → block — completeness is judged against the FULL plan, not this run')
// The resume case: a run that only advanced w3 still releases, because w1/w2 are durably integrated.
// Without alreadyIntegrated a resumed campaign could NEVER satisfy completeness and would hold
// forever with every wave actually integrated.
ok(routeRelease({ report: { outcome: 'completed', wavesAdvanced: ['w3'], alreadyIntegrated: ['w1', 'w2'] }, allWaves: PLAN, dod: MET }).release === true, 'routeRelease: resumed run + alreadyIntegrated → RELEASE (slice-independent)')
ok(routeRelease({ report: { outcome: 'completed', wavesAdvanced: ['w1', 'w2', 'w3'] }, allWaves: PLAN, dod: { met: false, unmet: ['AC3'] } }).release === false, 'routeRelease: DoD NOT met → block (this is why one-merge-at-the-end is a gate, not decoration)')
ok(routeRelease({ report: { outcome: 'completed', wavesAdvanced: ['w1', 'w2', 'w3'] }, allWaves: PLAN, dod: null }).release === false, 'routeRelease: DoD verdict ABSENT → block (an undeterminable DoD is not a met DoD)')
ok(routeRelease({ report: { outcome: 'completed', wavesAdvanced: ['w1', 'w2', 'w3'] }, allWaves: PLAN, dod: { met: 'yes' } }).release === false, 'routeRelease: malformed DoD (met not === true) → block')
ok(routeRelease({ report: { outcome: 'completed', wavesAdvanced: [] }, allWaves: [], dod: MET }).release === false, 'routeRelease: empty plan → block (a campaign with no waves is a misconfiguration, not a no-op)')
ok(routeRelease({}).release === false, 'routeRelease({}) → block (conservative on absence)')
// A wave id that is not in the plan is not evidence ABOUT the plan. alreadyIntegrated is
// agent-reported and feeds the completeness half of the ONE trunk-write predicate, so a bogus id
// must not be able to shrink missing[] into a release. (campaign-workflow.js filters to the plan's
// id set before this call; this pins that routeRelease does not itself credit unknown ids.)
ok(routeRelease({ report: { outcome: 'completed', wavesAdvanced: ['w1'], alreadyIntegrated: ['w2', 'nope', 'also-not-a-wave'] }, allWaves: PLAN, dod: MET }).release === false,
  '#1052: unknown wave ids in alreadyIntegrated do NOT satisfy completeness (w3 still missing)')
ok(typeof routeRelease({}).reason === 'string' && routeRelease({}).reason.length > 0, 'routeRelease always carries a human-readable reason')

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

  // 8b. context MUST surface the JUST-LANDED wave's own id + verdict (not yet in `completed`), so the
  // seam can include the most-recent wave in the judgment seed (critical-bug regression).
  let ctxW1 = null
  let ctxW2 = null
  const taggedPass = (g) => ({ gate: 'PASS', promoted: true, tag: g })
  await runCampaign({
    pending: [{ id: 'w1' }, { id: 'w2' }],
    runWave: async (w) => taggedPass(waveIdOf(w)),
    judge: async (w, ctx) => { if (waveIdOf(w) === 'w1') ctxW1 = ctx; else ctxW2 = ctx; return cont },
  })
  ok(ctxW1 && ctxW1.wave === 'w1' && ctxW1.verdict?.tag === 'w1' && ctxW1.completed.length === 0,
    'runCampaign: context surfaces the just-landed wave id+verdict on wave 1 (completed still empty)')
  ok(ctxW2 && ctxW2.wave === 'w2' && ctxW2.verdict?.tag === 'w2' && ctxW2.completed[0]?.verdict?.tag === 'w1',
    'runCampaign: just-landed verdict is THIS wave (w2), not the prior wave (w1) — off-by-one guard')

  // ── #750 intent-tier resolver (pure, deterministic tier selection) ──
  ok(resolveIntentTier({ devspec: 'd.md', domainModel: 'm.md', sketchbook: 's.md' }) === 'devspec', 'resolveIntentTier: devspec wins (richest)')
  ok(resolveIntentTier({ devspec: null, domainModel: 'm.md' }) === 'plan-ddd-sketchbook', 'resolveIntentTier: domainModel → plan-ddd-sketchbook')
  ok(resolveIntentTier({ devspec: null, domainModel: null, sketchbook: 's.md' }) === 'plan-ddd-sketchbook', 'resolveIntentTier: sketchbook → plan-ddd-sketchbook')
  ok(resolveIntentTier({}) === 'issues-only', 'resolveIntentTier: nothing → issues-only')
  ok(resolveIntentTier() === 'issues-only', 'resolveIntentTier(undefined) → issues-only (no throw)')

  // ── #750 the LENS — waveOversightPrompt encodes the §4 framing + the A–J catalog + tier calibration ──
  const prompt = waveOversightPrompt({ justLanded: { wave: 'w2' }, trajectory: [{ wave: 'w1', gate: 'PASS' }], remainingPlan: ['w3'], intentTier: 'devspec', intentRefs: { devspec: 'spec.md' }, kahunaBranch: 'kahuna/w2' })
  ok(/ACCUMULATION/.test(prompt) && /INTENT-DRIFT/.test(prompt), 'lens: §4 accumulation + intent-drift')
  ok(/ADAPTATION/.test(prompt) && /DRIFT/.test(prompt), 'lens: adaptation-vs-drift discriminator')
  ok(/TREND/.test(prompt) && /ABSENCE/.test(prompt) && /CONFOUND/.test(prompt), 'lens: the three detection modes')
  // every catalog cluster A–J present
  for (const c of ['A.', 'B.', 'C.', 'D.', 'E.', 'F.', 'G.', 'H.', 'I.', 'J.']) {
    ok(prompt.includes(`\n${c} `), `lens: failure-shape cluster ${c.replace('.', '')} present`)
  }
  ok(/PROMOTED ≠ DELIVERED/.test(prompt) && /command-ran ≠ thing-attached/.test(prompt), 'lens: the signature catalog tells (I + E) present')
  ok(/DEVSPEC tier/.test(prompt) && /dod_check_coverage/.test(prompt), 'lens: devspec tier calibrates to VRTM/dod tooling')
  ok(waveOversightPrompt({ intentTier: 'issues-only' }).includes('ISSUES-ONLY tier'), 'lens: issues-only tier calibration')
  ok(/kahuna\/w2/.test(prompt), 'lens: names the kahuna branch for live inspection')
  ok(JUDGMENT_RESULT.required.includes('continue') && JUDGMENT_RESULT.additionalProperties === false, 'JUDGMENT_RESULT schema requires continue, no extra props')

  // ── #1052 the release nodes — DoD verification, then the ONE trunk merge ──
  const dodP = dodVerificationPrompt({ planId: '56', targetRepo: 'o/r', targetRepoDir: '/tmp/r', campaignBranch: 'campaign/56-x', protectedBranch: 'main', wavesIntegrated: ['w1', 'w2'] })
  ok(/campaign\/56-x/.test(dodP), 'dod prompt: verifies against the CAMPAIGN branch')
  ok(/plan_load_dod/.test(dodP), 'dod prompt: loads the plan DoD (the criteria, not an invented list)')
  // The DoD node must ANSWER, never act — a node that could merge would make routeRelease advisory.
  ok(!/pr_merge\b/.test(dodP) && !/gh pr merge/.test(dodP), 'dod prompt: NEVER merges — it answers; routing is the pure predicate\'s job')
  ok(DOD_VERDICT.required.includes('met') && DOD_VERDICT.additionalProperties === false, 'DOD_VERDICT schema requires met, no extra props')
  // #1365: a BJ-waived DoD line (e.g. a post-merge criterion) is waived, never unmet.
  ok(dodP.includes('WAIVED by BJ <date>: <reason> (<url>)') && /never count it as unmet/.test(dodP), 'dod prompt: a BJ-waived DoD line is listed as waived, never counted as unmet')
  // #1365: the DoD node runs before the campaign→protected PR exists (it is told not to open one),
  // so a Plan-template DoD line about that PR or its merge-result CI is unmet on every run.
  const planDodLines = []
  for (const f of ['skills/issue/SKILL.md', 'docs/plan-issue-template.md']) {
    const src = readFileSync(new URL(`../../${f}`, import.meta.url), 'utf8')
    for (const sec of src.split('## Plan-level Definition of Done').slice(1)) {
      planDodLines.push(...sec.split('\n## ')[0].split('\n').filter((l) => /^- \[ \]/.test(l)))
    }
  }
  ok(planDodLines.length > 0 && planDodLines.every((l) => !/\bPR\b|pull request|merge.result|campaign→/i.test(l)),
    'plan template: no DoD line needs the campaign→protected PR or its merge-result CI (the DoD node grades before it exists)')

  const relArgs = { planId: '56', targetRepo: 'o/r', campaignBranch: 'campaign/56-x', protectedBranch: 'main', wavesIntegrated: ['w1', 'w2'] }
  const ciP = releaseCiPrompt(relArgs)
  ok(/campaign\/56-x/.test(ciP) && /main/.test(ciP), 'release-CI prompt: names both refs (campaign → protected)')
  // A wave's pipeline ran against the campaign branch, which drifts from trunk — so the release
  // needs its OWN merge-result CI run against current trunk. A branch-CI signal is weaker.
  ok(/require_merge_result=true/.test(ciP) && /ci_wait_run/.test(ciP), 'release-CI prompt: gates on a MERGE-RESULT CI run (no per-wave pipeline tested this diff against current trunk)')
  ok(/timeout_sec=1800, poll_interval_sec=20/.test(ciP), 'release-CI prompt: the explicit bounded wait (#1035)')
  // #1357: ci_wait_run's ref is required, and a GitLab merged-results pipeline is never under the branch.
  ok(ciP.includes('GitLab: ref="refs/merge-requests/<n>/merge"') && ciP.includes('GitHub: ref="campaign/56-x"'),
    'release CI prompt names refs/merge-requests/<n>/merge and the campaign branch')
  ok(ciP.indexOf('pr_wait_ci(') >= 0 && ciP.indexOf('pr_wait_ci(') < ciP.indexOf('sdlc-server ci_wait_run('), 'release-CI prompt: the no-run probe precedes the wait (#1357)')
  // #1211: the release gate had no fallback, so a GitLab ci_wait_run that saw nothing (sdlc#585)
  // waited 1800s and could only hold. It now carries the shared direct read, verbatim.
  ok(ciP.includes(directMergeReadSteps({ targetRepo: 'o/r', windowSec: 600 })[0]), 'release-CI prompt: carries the shared direct /merge read (#1211)')
  ok(/merge_requests\/<n>\/pipelines\?per_page=100/.test(ciP) && /parent_ids/.test(ciP), 'release-CI prompt: the direct read lists pipelines and reads the merge commit parents')
  // The CI node only ANSWERS — a node that could merge would make mergeResultVerdict advisory.
  ok(!/pr merge\b/.test(ciP) && !/pr_merge\b/.test(ciP) && !/pr ready\b/.test(ciP), 'release-CI prompt: NEVER marks ready or merges; it answers and code grades')
  ok(/do NOT merge/.test(ciP), 'release-CI prompt: says so')
  // #1211 review I-1: the head is read FIRST and again LAST, so a head that moved while CI was graded
  // HOLDs instead of passing on the previous head's /merge pipeline.
  const first = ciP.indexOf('report it as head_sha,')
  const last = ciP.indexOf('report it as head_sha_final')
  ok(first >= 0 && first < ciP.indexOf('sdlc-server ci_wait_run('), 'release-CI prompt: the first head read comes before ci_wait_run')
  ok(last > ciP.indexOf('DIRECT READ'), 'release-CI prompt: the final head read comes after ci_wait_run AND the direct read')
  // #1356 (triage #7): the target tip is read last, against the PROTECTED branch, so a /merge pipeline
  // built before trunk moved is held as stale; and the run's sha is copied, so the success path binds.
  const tip = ciP.indexOf("Read the TARGET branch main's tip NOW and report it as target_sha")
  ok(tip > last && ciP.includes('gh api repos/o/r/branches/main --jq .commit.sha'), 'release CI prompt asks for target_sha against the protected branch, after the final head read')
  ok(/head_sha_final and target_sha \(step 4\)/.test(ciP) && /copied as returned \(ok, final_status, reason, error, sha, run_id, url\)/.test(ciP), 'release CI prompt returns target_sha and copies the run sha')

  const relP = releaseMergePrompt({ ...relArgs, prNumber: 77, headSha: 'f'.repeat(40), ciReason: 'graded-green-reason' })
  ok(/campaign\/56-x/.test(relP) && /main/.test(relP), 'release prompt: names both refs (campaign → protected)')
  ok(!/ci_wait_run/.test(relP) && /Do NOT re-gate CI/.test(relP), 'release prompt: no CI wait of its own; the gate graded CI in code before this node (#1211)')
  ok(relP.includes('graded-green-reason'), "release prompt: carries the gate's reason")
  ok(relP.includes(`pr merge 77 --match-head-commit ${'f'.repeat(40)}`), 'release prompt: GitHub merge is bound to the graded head')
  ok(relP.includes(`merge_requests/77/merge?sha=${'f'.repeat(40)}`), 'release prompt: GitLab merge is bound to the graded head')
  ok(/If the merge fails for ANY reason.*STOP and return released=false/s.test(relP), 'release prompt: any failed pinned merge (a moved head is one) is a HOLD, never a merge of unseen code')
  ok(relP.includes('glab mr update 77 --ready -R o/r'), 'release prompt: GitLab marks the MR ready before merging (GitLab refuses to merge a draft)')
  // #1211 review I-2: no graded head, no merge. The old fallback bound to "the head SHA you read now".
  for (const headSha of [undefined, '', 'HEAD', 'F'.repeat(40)]) {
    const stop = releaseMergePrompt({ ...relArgs, prNumber: 77, headSha, ciReason: 'x' })
    ok(/STOP\. Do NOT mark the PR ready and do NOT merge\. Return released=false/.test(stop) && !/pr merge|\/merge\?sha=|pr ready|--ready/.test(stop),
      `release prompt: no well-formed graded head (${JSON.stringify(headSha)}) STOPs with no merge instruction`)
  }

  ok(/Refs #/.test(relP), 'release prompt: honors Refs #N (do-not-close) when closing issues (#1046)')
  ok(RELEASE_RESULT.required.includes('released') && RELEASE_RESULT.additionalProperties === false, 'RELEASE_RESULT schema requires released, no extra props')

  // #1211: a pure rule proves nothing if the workflow stops calling it. Pin the wiring in the source
  // AND the committed bundle (the artifact the Workflow tool runs): the CI node returns evidence,
  // the verdict is computed in code, and the merge node is reached only in the pass branch.
  for (const f of ['campaign-workflow.js', 'campaign-workflow.bundled.js']) {
    const src = readFileSync(new URL(`../../skills/nextwave/${f}`, import.meta.url), 'utf8')
    ok(/label: 'release:ci',\s+phase: 'Release',\s+schema: MERGE_RESULT_EVIDENCE,/.test(src), `${f}: the release-CI node returns MERGE_RESULT_EVIDENCE`)
    ok(/\.catch\(\(e\) => \(\{ error: e\?\.message \|\| String\(e\) \}\)\)\s+const releaseCi = mergeResultVerdict\(ciEvidence\)/.test(src), `${f}: an errored CI node is graded (HOLD), not skipped`)
    ok(/if \(!releaseCi\.pass \|\| !isMergeSha\(releaseCi\.head\)\) \{[\s\S]*?released: false[\s\S]*?\} else \{\s+release = await agent\(\s+releaseMergePrompt\(/.test(src), `${f}: the merge node runs only when the verdict passed with a graded head`)
    ok(/releaseMergePrompt\(\{ \.\.\.releaseArgs, prNumber: ciEvidence\.pr_number, headSha: releaseCi\.head,/.test(src), `${f}: the merge binds to the head the VERDICT names, not to raw evidence (#1211 review I-2)`)
    ok(src.includes('notes: `release CI HOLD: ${why}${agentNotes}`'), `${f}: a release HOLD keeps the agent's notes`)
    // Calls only: the bundle also inlines campaign-loop.js, so it carries the definition too.
    ok((src.match(/(?<!function )releaseMergePrompt\(/g) || []).length === 1, `${f}: releaseMergePrompt is called exactly once (no path around the gate)`)
  }
  // The bundle must also DEFINE what it calls. A module dropped from campaign-bundle.mjs MODULES
  // still bundles "in sync" and parses, then throws a ReferenceError at the release gate.
  const campaignBundle = readFileSync(new URL('../../skills/nextwave/campaign-workflow.bundled.js', import.meta.url), 'utf8')
  for (const def of ['function mergeResultVerdict(', 'function directMergeReadSteps(', 'const MERGE_RESULT_EVIDENCE =']) {
    ok(campaignBundle.includes(def), `campaign-workflow.bundled.js defines ${def.replace(/[ (=]+$/, '')} (merge-result.js inlined)`)
  }

  // The oversight lens must know BOTH branches, so a mid-campaign `promoted:false` reads as the
  // normal state it now is (nothing has shipped yet) rather than as catalog-I evidence.
  const campPrompt = waveOversightPrompt({ justLanded: { wave: 'w2' }, trajectory: [], remainingPlan: ['w3'], intentTier: 'issues-only', kahunaBranch: 'kahuna/56-w2', campaignBranch: 'campaign/56-x', protectedBranch: 'main' })
  ok(/campaign\/56-x/.test(campPrompt), 'lens: names the campaign branch (where the wave INTEGRATED)')

  console.log('')
  if (failed > 0) {
    console.error(`  ${failed} check(s) failed`)
    process.exit(1)
  }
  console.log(`  all ${passed} campaign-loop checks passed`)
}

main().catch((e) => { console.error(`  [FAIL] uncaught: ${e?.stack || e}`); process.exit(1) })
