// campaign-workflow.js — #749 deterministic AUTO-mode campaign Workflow (the entrypoint).
//
// Design of record: docs/campaign-workflow-design.md §2/§6.1. The auto-mode campaign loop is a
// deterministic Workflow: it iterates the pending waves, runs each per-wave spine
// (per-wave-workflow.js) as a nested workflow(), routes on the {gate, integrated} verdict, calls the
// wave-oversight judgment sub-agent (§2.2 — the launching session cannot re-invoke itself), and
// advances on continue / holds-and-ends on a flag. NO LLM in the loop control flow ⇒ it provably
// cannot stall ⇒ the stall-guard (#736) dissolves.
//
// #1052 — ONE BRANCH ALL THE WAY THROUGH. Every wave integrates onto a single long-lived CAMPAIGN
// branch; the protected branch is written EXACTLY ONCE, at the end, and only if the DoD is met.
// The topology, the three costs of interim merge-backs, and why this dissolves #892 rather than
// mitigating it are documented in campaign-loop.js (BRANCH TOPOLOGY). This file owns the two nodes
// that shape makes necessary: the campaign-branch BOOTSTRAP (phase 1) and the RELEASE gate
// (phase 3 — DoD verification, then the single trunk merge).
//
// THIN BY DESIGN: every deterministic decision (parse, rehydrate/prune, verdict + judgment + release
// routing, the loop driver) lives in campaign-loop.js (pure, unit-tested). This file only WIRES the
// real side-effecting seams — workflow() for the spine, agent() for bootstrap + rehydrate + judgment
// + DoD + release — into runCampaign(). Source-of-truth modules are inlined by campaign-bundle.mjs
// into the single-file artifact campaign-workflow.bundled.js the Workflow tool invokes.
import {
  parseArgs,
  computePending,
  waveIdOf,
  campaignBranchFor,
  waveKahunaFor,
  isIntegrated,
  resolveIntentTier,
  runCampaign,
  routeRelease,
  waveOversightPrompt,
  dodVerificationPrompt,
  releaseMergePrompt,
  JUDGMENT_RESULT,
  DOD_VERDICT,
  RELEASE_RESULT,
} from './campaign-loop.js'

export const meta = {
  name: 'campaign-workflow',
  description:
    'Deterministic auto-mode campaign Workflow (#749/#1052, design §6.1): bootstrap ONE campaign branch → rehydrate pending waves from durable wave-status → per wave run the per-wave spine onto the campaign branch, route on {gate, integrated}, call the wave-oversight judgment sub-agent → advance on continue, hold-and-end on a flag → at the end verify the DoD and land the campaign on the protected branch in a SINGLE merge. No LLM in the loop ⇒ cannot stall (#736 dissolves). Parameterized by the wave plan + per-wave launch blob via args.',
  phases: [
    { title: 'Bootstrap', detail: 'ensure the campaign branch exists off the protected branch (#1052)' },
    { title: 'Rehydrate', detail: 'cold-start: read integrated waves + trajectory from durable wave-status, prune (§6.1.3)' },
    { title: 'Campaign loop', detail: 'per wave: spine → verdict route → wave-oversight judgment → advance/hold (§2)' },
    { title: 'Release', detail: 'DoD verification, then the single campaign→protected merge (#1052)' },
  ],
}

// ── PARAMETERS (args is the runtime global; tolerate object OR JSON string, #1/#3) ───────────
const params = parseArgs(typeof args !== 'undefined' ? args : undefined)
const PLAN_ID = params.planId ?? null
const TARGET_REPO = params.targetRepo ?? 'Wave-Engineering/ccwork-testtarget'
const TARGET_REPO_DIR = params.targetRepoDir ?? '/home/bakerb/sandbox/github/ccwork-testtarget'
const PROTECTED_BRANCH = params.protectedBranch ?? 'main'
const INTENT_TIER_OVERRIDE = params.intentTier ?? null // explicit override; else resolved by the #750 intent-discovery step (§3)
// The full ordered wave plan: [{ id, issues:[...], kahunaBranch? }, ...]. Fail loud on empty —
// a campaign with no waves is a misconfiguration, not a no-op (mirrors per-wave's empty-wave guard).
const ALL_WAVES = Array.isArray(params.waves) ? params.waves : []
if (ALL_WAVES.length === 0) {
  throw new Error(
    `campaign-workflow: empty wave plan (params.waves=${JSON.stringify(params.waves ?? null)}). ` +
      `Launch with {waves:[{id, issues:[...]}, ...], targetRepo, targetRepoDir} via the Workflow tool's \`args\`.`,
  )
}
// #1052 — THE CAMPAIGN BRANCH. Every wave integrates here; the protected branch is untouched until
// the release gate. An explicit params.campaignBranch wins (a resumed campaign MUST be handed the
// same branch it started on); otherwise derive it deterministically from the plan so a resume that
// forgot to pass it still recomputes the same name rather than silently starting a second campaign.
//
// A random or timestamped component would be WRONG here — it would make the derived name unstable
// across resumes, which is precisely the failure the determinism is protecting against.
//
// There is NO placeholder for a missing planId or slug. campaignBranchFor throws on either, and that
// throw is load-bearing: defaulting them (e.g. to 'plan'/'campaign') makes EVERY under-specified
// campaign resolve to the same `campaign/plan-campaign`, whereupon the bootstrap's reuse-wins rule
// adopts a DIFFERENT campaign's branch and its commits, and the release node lands both campaigns'
// work on trunk as one increment. A campaign launched without a plan id and slug is a
// misconfiguration, not a defaultable case — same fail-loud stance as the empty-plan and
// branch-equals-trunk guards below.
// The explicit override is lowercased through the SAME normalization as the derived name. Otherwise a
// launcher that hand-builds `campaign/56-Blueshift` and a resume that omits the param (deriving
// `campaign/56-blueshift`) would name two different case-sensitive server refs for one campaign — the
// exact fork the derived-path lowercasing exists to prevent, reached by nothing more exotic than
// forgetting to re-pass the parameter.
const CAMPAIGN_BRANCH = String(params.campaignBranch ?? campaignBranchFor({
  planId: PLAN_ID,
  slug: params.slug ?? params.campaignSlug,
})).toLowerCase()
if (CAMPAIGN_BRANCH === PROTECTED_BRANCH) {
  // Fail loud rather than run a campaign whose "integration branch" IS trunk — that would restore
  // per-wave trunk writes under a name that claims otherwise, the exact shape #1052 removes.
  throw new Error(
    `campaign-workflow: campaignBranch (${CAMPAIGN_BRANCH}) must not equal protectedBranch (${PROTECTED_BRANCH}). ` +
      `A campaign integrates onto its own branch and writes the protected branch exactly once, at the DoD gate (#1052).`,
  )
}
// The per-wave spine artifact this campaign drives (nested workflow()). Default to the committed
// bundle next to this file; overridable for tests / alternate deployments.
const PER_WAVE_SCRIPT = params.perWaveScriptPath ?? 'skills/nextwave/per-wave-workflow.bundled.js'
// Skip the trunk merge and end with the campaign branch intact + the DoD verdict reported. For a
// campaign whose release is a human decision (or a dry run). The DoD node still runs — its verdict
// is the useful artifact; only the merge is withheld.
const RELEASE_MODE = params.release === false ? 'hold' : 'auto'

// ── PHASE 1 — BOOTSTRAP THE CAMPAIGN BRANCH (#1052) ──────────────────────────────────────────
// Idempotent create-or-reuse, and the ORDER of those two matters: on a resume the branch already
// exists and carries every previously-integrated wave, so re-cutting it from the protected branch
// would silently discard the whole campaign to date. Reuse-if-exists is the correctness case;
// create-if-absent is the fresh-campaign case.
//
// Hard-fails the campaign on error. This is the one place where a soft-fail would be actively
// dangerous: if the campaign branch does not exist, every wave's INTEGRATION_BASE resolves to a
// missing ref, and the recovery an agent would most plausibly reach for is "base it on the
// protected branch instead" — which is exactly the per-wave trunk write this shape exists to
// prevent. No branch, no campaign.
phase('Bootstrap')
const BOOTSTRAP_RESULT = {
  type: 'object',
  additionalProperties: false,
  required: ['ready'],
  properties: {
    ready: { type: 'boolean' },
    created: { type: 'boolean' }, // true = fresh cut off the protected branch; false = reused an existing campaign branch
    head_sha: { type: 'string' },
    notes: { type: 'string' },
  },
}
const bootstrap = await agent(
  [
    `You are the CAMPAIGN BRANCH BOOTSTRAP node for plan ${PLAN_ID ?? 'n/a'} of ${TARGET_REPO}.`,
    `Ensure the campaign branch ${CAMPAIGN_BRANCH} exists on origin. Do NOT do any other work — do not`,
    `merge anything, do not touch ${PROTECTED_BRANCH}, do not create any wave/kahuna branches.`,
    ``,
    `Work in ${TARGET_REPO_DIR}:`,
    `1. git -C ${TARGET_REPO_DIR} fetch origin --prune`,
    `2. If origin/${CAMPAIGN_BRANCH} ALREADY EXISTS: REUSE it. Return ready=true, created=false, and its`,
    `   head sha. Do NOT reset, re-cut, or force-push it — this is a RESUMED campaign and that branch`,
    `   carries every wave integrated so far. Re-cutting it from ${PROTECTED_BRANCH} would silently`,
    `   discard the whole campaign to date; that is the single worst outcome available at this step.`,
    `3. If it does NOT exist: create it from the CURRENT tip of origin/${PROTECTED_BRANCH} and push it:`,
    `     git -C ${TARGET_REPO_DIR} branch ${CAMPAIGN_BRANCH} origin/${PROTECTED_BRANCH}`,
    `     git -C ${TARGET_REPO_DIR} push -u origin ${CAMPAIGN_BRANCH}`,
    `   Return ready=true, created=true, head sha.`,
    `4. VERIFY BY READING BACK — not by the push's exit code: confirm origin/${CAMPAIGN_BRANCH} resolves`,
    `   (git -C ${TARGET_REPO_DIR} rev-parse origin/${CAMPAIGN_BRANCH}) and report that sha.`,
    ``,
    `If the branch can NEITHER be found NOR created, return ready=false with the reason in notes. Do NOT`,
    `substitute ${PROTECTED_BRANCH} or any other ref as a fallback — the campaign will abort, which is`,
    `the correct outcome (#1052: waves must never integrate onto the protected branch).`,
    ``,
    `Return: ready (bool), created (bool), head_sha (string), notes (1-2 sentences).`,
  ].join('\n'),
  { label: 'bootstrap:campaign-branch', phase: 'Bootstrap', schema: BOOTSTRAP_RESULT, agentType: 'general-purpose' },
).catch((e) => ({ ready: false, notes: `bootstrap error: ${e?.message || e}` }))

if (!bootstrap?.ready) {
  throw new Error(
    `campaign-workflow: could not establish the campaign branch ${CAMPAIGN_BRANCH} (${bootstrap?.notes || 'unknown reason'}). ` +
      `Aborting — waves must integrate onto the campaign branch, never onto ${PROTECTED_BRANCH} (#1052).`,
  )
}
log(`[#1052] campaign branch ${CAMPAIGN_BRANCH} ${bootstrap.created ? 'CREATED off' : 'REUSED (resume) — not re-cut from'} ${PROTECTED_BRANCH}${bootstrap.head_sha ? ` @ ${bootstrap.head_sha}` : ''}`)

// ── PHASE 2 — REHYDRATE (§6.1.3, reboot-proof) ───────────────────────────────────────────────
// Read the durable wave-status: which waves already INTEGRATED (prune them) + the cross-wave
// trajectory (#748) that seeds the judgment agent. The script cannot call the CLI directly, so a
// cheap agent reads it (wave-status trajectory-show + the wave-completion records) and returns the
// structured rehydrate. A read failure is conservative: assume nothing integrated (re-run waves —
// the per-wave spine is idempotent) and an empty trajectory.
//
// #1052: the prune predicate is INTEGRATED, not released. Nothing is released until the campaign
// ends, so a released-keyed rehydrate would prune nothing and re-run the whole campaign on every
// resume. The persisted disposition is still the string 'promoted' (durable value, deliberately not
// renamed — see wave-status.js) and now MEANS "landed on the integration base".
phase('Rehydrate')
const REHYDRATE_RESULT = {
  type: 'object',
  additionalProperties: false,
  required: ['integratedWaveIds'],
  properties: {
    integratedWaveIds: { type: 'array', items: { type: 'string' } },
    trajectory: { type: 'array', items: { type: 'object', additionalProperties: true } },
  },
}
const rehydrated = await agent(
  [
    `You are the campaign REHYDRATE node for ${TARGET_REPO} (plan ${PLAN_ID ?? 'n/a'}). Read the durable`,
    `wave-status in the target clone and return the cold-start campaign state. Do NOT do any other work.`,
    ``,
    `Run FROM the target clone (cd ${TARGET_REPO_DIR}) so the CLI resolves its .claude/status/:`,
    `  1. integratedWaveIds: the wave ids that have LANDED ON THE CAMPAIGN BRANCH ${CAMPAIGN_BRANCH}`,
    `     — i.e. whose terminal disposition is 'promoted' (that durable value means "landed on its`,
    `     integration base", which in a campaign is the campaign branch, NOT ${PROTECTED_BRANCH};`,
    `     #1052). Read the durable trajectory + wave-completion records:`,
    `       wave-status trajectory-show   (JSON array; entries with integrated:true — or, from a`,
    `                                      pre-#1052 record, promoted:true — have landed)`,
    `     plus any wave-completion record the store exposes. Do NOT require anything to be on`,
    `     ${PROTECTED_BRANCH}: nothing in this campaign reaches it until the release gate at the end,`,
    `     so a protected-branch test would report every wave as un-run and re-run the whole campaign.`,
    `     Be CONSERVATIVE — only list a wave as integrated if the record clearly says so; when unsure,`,
    `     omit it (the spine re-runs idempotently, so a false omission costs time, not correctness).`,
    `  2. trajectory: the full \`wave-status trajectory-show\` array verbatim (seeds the judgment agent).`,
    ``,
    `If wave-status is absent/empty (fresh campaign) return { integratedWaveIds: [], trajectory: [] }.`,
    `Return EXACTLY: integratedWaveIds (array of strings), trajectory (array of objects).`,
  ].join('\n'),
  { label: 'rehydrate', phase: 'Rehydrate', schema: REHYDRATE_RESULT, agentType: 'general-purpose' },
).catch((e) => {
  log(`[#749] rehydrate soft-fail → assume fresh campaign (spine is idempotent): ${e?.message || e}`)
  return { integratedWaveIds: [], trajectory: [] }
})

// The waves already integrated before this run. Kept because the release gate judges completeness
// against the FULL plan (routeRelease): a resumed run's `wavesAdvanced` covers only its own slice,
// so without these a resumed campaign could never satisfy the completeness predicate and would
// never release — it would hold forever with every wave actually integrated.
//
// FILTERED to the plan's own wave ids. This list is agent-reported, and it feeds the completeness
// half of routeRelease — the predicate that authorizes the one write to the protected branch. An
// id that is not in the plan cannot be evidence about the plan, so an over-reporting or confused
// rehydrate agent must not be able to shrink `missing[]` and manufacture a release. (The DoD node is
// the other, independent half of that gate; this makes the completeness half self-consistent too.)
const PLAN_WAVE_IDS = new Set(ALL_WAVES.map((w) => String(waveIdOf(w))))
const reportedIntegrated = (rehydrated?.integratedWaveIds ?? []).map(String)
const ALREADY_INTEGRATED = reportedIntegrated.filter((id) => PLAN_WAVE_IDS.has(id))
for (const id of reportedIntegrated.filter((id) => !PLAN_WAVE_IDS.has(id))) {
  log(`[#1052] discarding rehydrated wave id '${id}' — not in this plan; it cannot count toward release completeness.`)
}
// A freshly-CUT campaign branch and "waves already integrated onto it" cannot both be true. When they
// co-occur, those integrations landed on some OTHER branch (a renamed/case-drifted campaign, a deleted
// and re-cut branch, a stale durable store) — yet ALREADY_INTEGRATED still feeds routeRelease's landed
// set, so `missing[]` could empty and the completeness half of the ONE trunk-write gate would pass on
// evidence about a branch this run never touched. The plan-id filter above hardened this predicate
// against out-of-plan ids; wrong-branch ids are the same class, and both facts are already in hand here.
if (bootstrap.created === true && ALREADY_INTEGRATED.length > 0) {
  throw new Error(
    `campaign-workflow: ${CAMPAIGN_BRANCH} was just CUT FRESH off ${PROTECTED_BRANCH}, but wave-status reports ` +
      `[${ALREADY_INTEGRATED.join(', ')}] already integrated — those landed on a DIFFERENT branch, so they are ` +
      `not on this one. Aborting rather than count them toward release completeness (#1052). Resolve the ` +
      `mismatch (recover the original campaign branch, or clear the stale wave-status records) and re-run.`,
  )
}
const pending = computePending(ALL_WAVES, ALREADY_INTEGRATED)
const baseTrajectory = Array.isArray(rehydrated?.trajectory) ? rehydrated.trajectory : []
log(`[#749] rehydrated — ${ALREADY_INTEGRATED.length} integrated, ${pending.length} pending: [${pending.map(waveIdOf).join(', ') || 'none'}]`)

// #750 INTENT-TIER RESOLVER (§3 — tiered intent, graceful degradation). One-time discovery: an
// agent runs the sdlc-server locators (devspec_locate → ddd_locate_domain_model / ddd_locate_sketchbook)
// and reports WHAT EXISTS + its refs; the pure resolveIntentTier() picks the richest tier, which the
// judgment agent is then told (so it calibrates instead of faking/hedging). An explicit args override
// (params.intentTier) wins; a discovery failure degrades conservatively to issues-only.
const INTENT_DISCOVERY = {
  type: 'object',
  additionalProperties: false,
  properties: {
    devspec: { type: ['string', 'null'] },
    domainModel: { type: ['string', 'null'] },
    sketchbook: { type: ['string', 'null'] },
  },
}
const intent = INTENT_TIER_OVERRIDE
  ? { devspec: null, domainModel: null, sketchbook: null }
  : await agent(
      [
        `You are the campaign INTENT-DISCOVERY node for ${TARGET_REPO} (plan ${PLAN_ID ?? 'n/a'}). Detect the`,
        `richest available intent artifact for the wave-oversight judgment seed (§3). Do NOT do other work.`,
        `Run the sdlc-server locators and return the REF of each that exists (else null):`,
        `  devspec     → devspec_locate`,
        `  domainModel → ddd_locate_domain_model`,
        `  sketchbook  → ddd_locate_sketchbook`,
        `Return EXACTLY: devspec (string ref|null), domainModel (string ref|null), sketchbook (string ref|null).`,
      ].join('\n'),
      { label: 'intent-discovery', phase: 'Rehydrate', schema: INTENT_DISCOVERY, agentType: 'general-purpose' },
    ).catch((e) => {
      log(`[#750] intent-discovery soft-fail → issues-only tier (conservative): ${e?.message || e}`)
      return { devspec: null, domainModel: null, sketchbook: null }
    })
const INTENT_TIER = INTENT_TIER_OVERRIDE ?? resolveIntentTier({ devspec: intent.devspec, domainModel: intent.domainModel, sketchbook: intent.sketchbook })
const INTENT_REFS = { devspec: intent.devspec ?? null, domainModel: intent.domainModel ?? null, sketchbook: intent.sketchbook ?? null }
log(`[#750] intent tier: ${INTENT_TIER}${INTENT_TIER_OVERRIDE ? ' (override)' : ''} — refs ${JSON.stringify(INTENT_REFS)}`)

// ── PHASE 3 — CAMPAIGN LOOP (§2 — control flow is code; judgment is a seam) ───────────────────
phase('Campaign loop')

// This wave's disposable integration branch. Namespaced under the PLAN so two concurrent campaigns
// in one repo cannot collide on `kahuna/W-1`, and deliberately under a DIFFERENT top-level prefix
// from the campaign branch — a branch cannot be a directory prefix of another branch, so
// `campaign/56-x` + `campaign/56-x/W-1` is an unrepresentable ref (see campaign-loop.js topology).
//
// The per-wave name ALWAYS wins inside a campaign — a plan-supplied `wave.kahunaBranch` is ignored.
// That field is populated by server-side `wave_init`, which cuts ONE plan-scoped
// `kahuna/<plan>-<slug>` off the plan's base_branch (default: trunk). Honoring it here would
// reintroduce exactly what #1052 removes: a branch SHARED across waves (so wave 1's promote deletes
// wave 2's base, since a campaign wave's kahuna is disposable) and cut off TRUNK rather than the
// campaign branch (so each wave's flights would build on a baseline missing every previously
// integrated wave). Log the override rather than dropping it silently — a stale launcher passing the
// field is a real configuration the operator should see named.
const kahunaFor = (wave, id) => {
  const derived = waveKahunaFor({ planId: PLAN_ID, waveId: id })
  if (wave.kahunaBranch && wave.kahunaBranch !== derived) {
    log(`[#1052] ignoring plan-supplied kahunaBranch '${wave.kahunaBranch}' for wave ${id} — using ${derived}, cut off ${CAMPAIGN_BRANCH} (a wave_init plan-scoped branch is shared across waves and based on trunk).`)
  }
  return derived
}

// Seam 1 — run the per-wave spine as a nested Workflow (one level, §ok: per-wave does not nest).
async function runWave(wave) {
  const id = waveIdOf(wave)
  const perWaveArgs = {
    waveId: id,
    issues: wave.issues ?? [],
    kahunaBranch: kahunaFor(wave, id),
    targetRepo: TARGET_REPO,
    targetRepoDir: TARGET_REPO_DIR,
    // #1052 — the wave integrates onto the CAMPAIGN branch and promotes nowhere else. Both are
    // passed: integrationBase is where the wave's PR targets and where its diffs are scoped, while
    // protectedBranch is passed so the spine can tell the two apart (it derives IN_CAMPAIGN from
    // integrationBase !== protectedBranch, which is what retires preserveKahuna and moves the
    // platform issue-close to the release node). Omitting protectedBranch would make the spine
    // default it to 'main' and mis-detect a campaign on any repo whose trunk is named otherwise.
    integrationBase: CAMPAIGN_BRANCH,
    protectedBranch: PROTECTED_BRANCH,
    planId: PLAN_ID,
    mode: 'auto', // the campaign Workflow is auto-mode by definition (§2.4); interactive is the skill driver
    dispatch: wave.dispatch ?? 'serialize', // #824 R-06: thread the per-wave dispatch hint (/prepwaves #823) into the spine's args; absent → serialize (CT-01)
    // NB: preserveKahuna is deliberately NOT threaded (#722 retired in campaign mode, #1052). The
    // branch that must survive across waves is the campaign branch, and it does; each wave's kahuna
    // is disposable again, which is what makes a squash merge harmless and #892 unreachable.
  }
  log(`[#749] launching per-wave spine for ${id} → ${perWaveArgs.kahunaBranch} onto ${CAMPAIGN_BRANCH} (issues ${JSON.stringify(perWaveArgs.issues)})`)
  return workflow({ scriptPath: PER_WAVE_SCRIPT }, perWaveArgs)
}

// Seam 2 — the wave-oversight judgment sub-agent (§2.2, #750). Seeded NO-distillation (§3) from the
// resolved intent tier + the durable trajectory (rehydrated base + this run's completed verdicts) +
// the remaining plan + live inspection (the wave's kahuna branch). The §4/§7 failure-shape lens lives
// in waveOversightPrompt; routing + JUDGMENT_RESULT are the stable contract.
async function judge(wave, context) {
  const id = waveIdOf(wave)
  // The trajectory the lens reads as a TIME SERIES must INCLUDE the just-landed wave — context.completed
  // holds only PRIOR waves (this wave isn't pushed until judge returns), so append context.verdict here.
  const trajectory = [
    ...baseTrajectory,
    ...context.completed.map((c) => ({ wave: c.wave, ...(c.verdict || {}) })),
    { wave: id, ...(context.verdict || {}) },
  ]
  return agent(
    waveOversightPrompt({
      justLanded: { wave: id, verdict: context.verdict ?? null },
      trajectory,
      remainingPlan: context.remaining,
      intentTier: INTENT_TIER,
      intentRefs: INTENT_REFS,
      kahunaBranch: kahunaFor(wave, id),
      // #1052: the judge is told BOTH branches so it reads a mid-campaign `promoted:false` as the
      // normal state it now is, and knows a flag here is cheap (trunk is still untouched).
      campaignBranch: CAMPAIGN_BRANCH,
      protectedBranch: PROTECTED_BRANCH,
    }),
    { label: `judgment:${id}`, phase: 'Campaign loop', schema: JUDGMENT_RESULT, agentType: 'general-purpose' },
  )
}

const report = await runCampaign({
  pending,
  runWave,
  judge,
  onEvent: (e) => {
    if (e.type === 'verdict') log(`[#749] ${e.wave}: gate=${e.gate} integrated=${e.integrated} → ${e.advance ? 'gate-advance' : 'HOLD'}`)
    else if (e.type === 'judgment') log(`[#749] ${e.wave}: judgment → ${e.advance ? 'continue' : 'FLAG/hold'}`)
    else if (e.type === 'advanced') log(`[#749] ${e.wave}: ADVANCED`)
  },
})

if (report.outcome === 'completed') {
  log(`[#749] all pending waves integrated — ${report.wavesAdvanced.length}/${pending.length} advanced: [${report.wavesAdvanced.join(', ')}]`)
} else {
  log(`[#749] campaign HELD at ${report.heldAt}: ${report.heldReason} (advanced: [${report.wavesAdvanced.join(', ') || 'none'}])`)
}

// ── PHASE 4 — RELEASE (#1052) — the ONE write to the protected branch ─────────────────────────
// Two gates, in order, and neither is skippable:
//   1. completeness — every wave in the FULL plan integrated (routeRelease; a resumed run's
//      wavesAdvanced is only its own slice, hence alreadyIntegrated),
//   2. the DoD is met — verified against the campaign branch's actual tree, not the checkboxes.
//
// The DoD node runs whenever the loop completed, INCLUDING when release is withheld: the verdict is
// the thing a human needs in order to decide, so producing it is not conditional on acting on it.
// It never runs after a HOLD — verifying a DoD against a knowingly-incomplete campaign would burn a
// long agent turn to restate what routeRelease already knows.
phase('Release')
const wavesIntegrated = [...ALREADY_INTEGRATED, ...report.wavesAdvanced.map(String)]
let dod = null
if (report.outcome === 'completed') {
  dod = await agent(
    dodVerificationPrompt({
      planId: PLAN_ID,
      targetRepo: TARGET_REPO,
      targetRepoDir: TARGET_REPO_DIR,
      campaignBranch: CAMPAIGN_BRANCH,
      protectedBranch: PROTECTED_BRANCH,
      wavesIntegrated,
    }),
    { label: 'release:dod', phase: 'Release', schema: DOD_VERDICT, agentType: 'general-purpose' },
  ).catch((e) => {
    // Conservative on absence (SEAMS invariant 6): a DoD node that ERRORED has not shown the DoD is
    // met, and an undeterminable DoD is not a met DoD. met:false BLOCKS the release; the campaign
    // branch is durable, so this is fully resumable once the DoD genuinely holds.
    log(`[#1052] DoD verification errored → release BLOCKED (conservative): ${e?.message || e}`)
    return { met: false, reason: `DoD verification errored: ${e?.message || e}`, unmet: [] }
  })
  log(`[#1052] DoD verdict: met=${dod?.met === true}${dod?.reason ? ` — ${dod.reason}` : ''}`)
} else {
  log(`[#1052] campaign held before completion — skipping DoD verification (nothing to release)`)
}

// Pass the pre-run integrations through on the report so the pure predicate can judge completeness
// against the whole plan without needing to know how this run was sliced.
const releaseRoute = routeRelease({
  report: { ...report, alreadyIntegrated: ALREADY_INTEGRATED },
  allWaves: ALL_WAVES,
  dod,
})

let release = null
if (releaseRoute.release && RELEASE_MODE === 'auto') {
  log(`[#1052] RELEASE GATE PASSED — ${releaseRoute.reason}. Landing ${CAMPAIGN_BRANCH} → ${PROTECTED_BRANCH} (the campaign's only trunk write).`)
  release = await agent(
    releaseMergePrompt({
      planId: PLAN_ID,
      targetRepo: TARGET_REPO,
      campaignBranch: CAMPAIGN_BRANCH,
      protectedBranch: PROTECTED_BRANCH,
      wavesIntegrated,
    }),
    { label: 'release:merge', phase: 'Release', schema: RELEASE_RESULT, agentType: 'general-purpose' },
  ).catch((e) => {
    // A failed release is NOT reported as released, and it is NOT a campaign failure either: every
    // wave is integrated and durable on the campaign branch, so the merge is retryable. Never claim
    // a merge that did not land (catalog signal I).
    log(`[#1052] release merge soft-fail — campaign branch intact, release retryable: ${e?.message || e}`)
    return { released: false, notes: `release error: ${e?.message || e}` }
  })
  log(release?.released
    ? `[#1052] RELEASED — ${CAMPAIGN_BRANCH} landed on ${PROTECTED_BRANCH}${release.merge_sha ? ` @ ${release.merge_sha}` : ''}`
    : `[#1052] NOT released — ${release?.notes || 'see release node'}. ${CAMPAIGN_BRANCH} is intact; retry once the blocker clears.`)
} else if (releaseRoute.release) {
  log(`[#1052] release gate PASSED but release:false was requested — holding. ${CAMPAIGN_BRANCH} is ready to land on ${PROTECTED_BRANCH}.`)
} else {
  log(`[#1052] release BLOCKED — ${releaseRoute.reason}. ${PROTECTED_BRANCH} untouched; ${CAMPAIGN_BRANCH} preserved for inspection/resume.`)
}

// The return IS the campaign result the launching session / operator routes on (§2.2: a Workflow
// ending with a report is the human handoff). `integrated` and `released` are reported SEPARATELY
// and are not interchangeable: waves can be fully integrated while released is false, which is a
// campaign awaiting its DoD, not a delivered increment (#1052).
return {
  outcome: report.outcome,
  plan: PLAN_ID,
  targetRepo: TARGET_REPO,
  campaignBranch: CAMPAIGN_BRANCH,
  protectedBranch: PROTECTED_BRANCH,
  wavesAdvanced: report.wavesAdvanced,
  wavesIntegrated,
  heldAt: report.heldAt ?? null,
  heldReason: report.heldReason ?? null,
  dod: dod ? { met: dod.met === true, unmet: dod.unmet ?? [], reason: dod.reason ?? null } : null,
  release: {
    attempted: release != null,
    released: release?.released === true,
    reason: releaseRoute.reason,
    pr_ref: release?.pr_ref ?? null,
    merge_sha: release?.merge_sha ?? null,
    notes: release?.notes ?? null,
  },
  // isIntegrated(), not an inline OR: the predicate gives an explicit `integrated:false` precedence
  // over a stale `promoted:true`, and an OR-form silently inverts that — reporting a wave the loop
  // correctly HELD as integrated. One predicate, one place (campaign-loop.js).
  wavesCompleted: report.completed.map((c) => ({ wave: c.wave, gate: c.verdict?.gate ?? null, integrated: isIntegrated(c.verdict), judgment: c.judgment ? (c.judgment.continue ? 'continue' : 'flag') : null })),
}
