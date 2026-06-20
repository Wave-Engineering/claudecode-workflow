// campaign-workflow.js — #749 deterministic AUTO-mode campaign Workflow (the entrypoint).
//
// Design of record: docs/campaign-workflow-design.md §2/§6.1. The auto-mode campaign loop is a
// deterministic Workflow: it iterates the pending waves, runs each per-wave spine
// (per-wave-workflow.js) as a nested workflow(), routes on the {gate, promoted} verdict, calls the
// wave-oversight judgment sub-agent (§2.2 — the launching session cannot re-invoke itself), and
// advances on continue / holds-and-ends on a flag. NO LLM in the loop control flow ⇒ it provably
// cannot stall ⇒ the stall-guard (#736) dissolves.
//
// THIN BY DESIGN: every deterministic decision (parse, rehydrate/prune, verdict + judgment routing,
// the loop driver) lives in campaign-loop.js (pure, unit-tested). This file only WIRES the real
// side-effecting seams — workflow() for the spine, agent() for rehydrate + judgment — into
// runCampaign(). Source-of-truth modules are inlined by campaign-bundle.mjs into the single-file
// artifact campaign-workflow.bundled.js the Workflow tool invokes.
import {
  parseArgs,
  computePending,
  waveIdOf,
  resolveIntentTier,
  runCampaign,
  waveOversightPrompt,
  JUDGMENT_RESULT,
} from './campaign-loop.js'

export const meta = {
  name: 'campaign-workflow',
  description:
    'Deterministic auto-mode campaign Workflow (#749, design §6.1): rehydrate pending waves from durable wave-status → per wave run the per-wave spine, route on {gate, promoted}, call the wave-oversight judgment sub-agent → advance on continue, hold-and-end on a flag. No LLM in the loop ⇒ cannot stall (#736 dissolves). Parameterized by the wave plan + per-wave launch blob via args.',
  phases: [
    { title: 'Rehydrate', detail: 'cold-start: read promoted waves + trajectory from durable wave-status, prune (§6.1.3)' },
    { title: 'Campaign loop', detail: 'per wave: spine → verdict route → wave-oversight judgment → advance/hold (§2)' },
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
// The per-wave spine artifact this campaign drives (nested workflow()). Default to the committed
// bundle next to this file; overridable for tests / alternate deployments.
const PER_WAVE_SCRIPT = params.perWaveScriptPath ?? 'skills/nextwave/per-wave-workflow.bundled.js'

// ── PHASE 1 — REHYDRATE (§6.1.3, reboot-proof) ───────────────────────────────────────────────
// Read the durable wave-status: which waves already PROMOTED (prune them) + the cross-wave
// trajectory (#748) that seeds the judgment agent. The script cannot call the CLI directly, so a
// cheap agent reads it (wave-status trajectory-show + the wave-completion records) and returns the
// structured rehydrate. A read failure is conservative: assume nothing promoted (re-run waves —
// the per-wave spine is idempotent) and an empty trajectory.
phase('Rehydrate')
const REHYDRATE_RESULT = {
  type: 'object',
  additionalProperties: false,
  required: ['promotedWaveIds'],
  properties: {
    promotedWaveIds: { type: 'array', items: { type: 'string' } },
    trajectory: { type: 'array', items: { type: 'object', additionalProperties: true } },
  },
}
const rehydrated = await agent(
  [
    `You are the campaign REHYDRATE node for ${TARGET_REPO} (plan ${PLAN_ID ?? 'n/a'}). Read the durable`,
    `wave-status in the target clone and return the cold-start campaign state. Do NOT do any other work.`,
    ``,
    `Run FROM the target clone (cd ${TARGET_REPO_DIR}) so the CLI resolves its .claude/status/:`,
    `  1. promotedWaveIds: the wave ids whose terminal disposition is 'promoted' (a wave that landed`,
    `     on ${PROTECTED_BRANCH}). Read the durable trajectory + wave-completion records:`,
    `       wave-status trajectory-show   (JSON array; entries with promoted:true are promoted)`,
    `     plus any wave-completion record the store exposes. Be CONSERVATIVE — only list a wave as`,
    `     promoted if the record clearly says so; when unsure, omit it (the spine re-runs idempotently).`,
    `  2. trajectory: the full \`wave-status trajectory-show\` array verbatim (seeds the judgment agent).`,
    ``,
    `If wave-status is absent/empty (fresh campaign) return { promotedWaveIds: [], trajectory: [] }.`,
    `Return EXACTLY: promotedWaveIds (array of strings), trajectory (array of objects).`,
  ].join('\n'),
  { label: 'rehydrate', phase: 'Rehydrate', schema: REHYDRATE_RESULT, agentType: 'general-purpose' },
).catch((e) => {
  log(`[#749] rehydrate soft-fail → assume fresh campaign (spine is idempotent): ${e?.message || e}`)
  return { promotedWaveIds: [], trajectory: [] }
})

const pending = computePending(ALL_WAVES, rehydrated?.promotedWaveIds ?? [])
const baseTrajectory = Array.isArray(rehydrated?.trajectory) ? rehydrated.trajectory : []
log(`[#749] rehydrated — ${(rehydrated?.promotedWaveIds ?? []).length} promoted, ${pending.length} pending: [${pending.map(waveIdOf).join(', ') || 'none'}]`)

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

// ── PHASE 2 — CAMPAIGN LOOP (§2 — control flow is code; judgment is a seam) ───────────────────
phase('Campaign loop')

// Seam 1 — run the per-wave spine as a nested Workflow (one level, §ok: per-wave does not nest).
async function runWave(wave) {
  const id = waveIdOf(wave)
  const perWaveArgs = {
    waveId: id,
    issues: wave.issues ?? [],
    kahunaBranch: wave.kahunaBranch ?? `kahuna/${id}`,
    targetRepo: TARGET_REPO,
    targetRepoDir: TARGET_REPO_DIR,
    protectedBranch: PROTECTED_BRANCH,
    planId: PLAN_ID,
    mode: 'auto', // the campaign Workflow is auto-mode by definition (§2.4); interactive is the skill driver
    preserveKahuna: wave.preserveKahuna ?? params.preserveKahuna ?? false,
  }
  log(`[#749] launching per-wave spine for ${id} (issues ${JSON.stringify(perWaveArgs.issues)})`)
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
      kahunaBranch: wave.kahunaBranch ?? `kahuna/${id}`,
    }),
    { label: `judgment:${id}`, phase: 'Campaign loop', schema: JUDGMENT_RESULT, agentType: 'general-purpose' },
  )
}

const report = await runCampaign({
  pending,
  runWave,
  judge,
  onEvent: (e) => {
    if (e.type === 'verdict') log(`[#749] ${e.wave}: gate=${e.gate} promoted=${e.promoted} → ${e.advance ? 'gate-advance' : 'HOLD'}`)
    else if (e.type === 'judgment') log(`[#749] ${e.wave}: judgment → ${e.advance ? 'continue' : 'FLAG/hold'}`)
    else if (e.type === 'advanced') log(`[#749] ${e.wave}: ADVANCED`)
  },
})

if (report.outcome === 'completed') {
  log(`[#749] campaign COMPLETE — ${report.wavesAdvanced.length}/${pending.length} waves advanced: [${report.wavesAdvanced.join(', ')}]`)
} else {
  log(`[#749] campaign HELD at ${report.heldAt}: ${report.heldReason} (advanced: [${report.wavesAdvanced.join(', ') || 'none'}])`)
}

// The return IS the campaign result the launching session / operator routes on (§2.2: a Workflow
// ending with a report is the human handoff).
return {
  outcome: report.outcome,
  plan: PLAN_ID,
  targetRepo: TARGET_REPO,
  wavesAdvanced: report.wavesAdvanced,
  heldAt: report.heldAt ?? null,
  heldReason: report.heldReason ?? null,
  wavesCompleted: report.completed.map((c) => ({ wave: c.wave, gate: c.verdict?.gate ?? null, promoted: c.verdict?.promoted === true, judgment: c.judgment ? (c.judgment.continue ? 'continue' : 'flag') : null })),
}
