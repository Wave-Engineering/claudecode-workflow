// campaign-loop.js — the #749 deterministic auto-mode campaign loop (pure core).
//
// Design of record: docs/campaign-workflow-design.md §2 ("control flow is code; judgment is a
// seam") + §6.1. Seeds the wave-oversight judgment agent (§3/§4) from the durable cross-wave
// trajectory (#748) — see [[project_wave_oversight_failure_catalog]] for the lens.
//
// WHY A PURE CORE MODULE (mirrors wave-status.js / gate.js): a Dynamic Workflow file uses
// top-level `return`/`await` and so cannot be imported by a node test. The deterministic halves
// of the campaign loop — args parse, cold-start rehydrate/prune, verdict + judgment routing, and
// the loop DRIVER itself (with its real side-effects injected as seams) — live here so they are
// UNIT-TESTABLE in isolation, then `campaign-bundle.mjs` inlines them into the single-file
// artifact `campaign-workflow.bundled.js` the Workflow tool invokes.
//
// THE KEY SEAM: `runCampaign` takes `runWave` (launch the per-wave spine) and `judge` (call the
// wave-oversight sub-agent) as INJECTED async functions. The Workflow entrypoint injects the real
// `workflow()` / `agent()` calls; the tests inject scripted fakes — so #749's "multi-wave advances
// on PASS+promoted+continue, ends on a HOLD/flag" procedures are deterministic unit tests, not
// integration runs. No LLM in the loop CONTROL FLOW ⇒ it provably cannot stall (#736 dissolves).

// ── args intake (same contract as per-wave-workflow.js #1/#3: the runtime global is `args`,
//    which may arrive as an object OR a JSON string from tool-call quoting) ──────────────────
export function parseArgs(raw) {
  if (raw == null) return {}
  if (typeof raw === 'string') {
    const s = raw.trim()
    if (!s) return {}
    try {
      return JSON.parse(s)
    } catch (e) {
      throw new Error(`campaign-workflow: \`args\` is a string but not valid JSON: ${e?.message || e}. Pass args as a JSON OBJECT.`)
    }
  }
  if (typeof raw === 'object') return raw
  throw new Error(`campaign-workflow: \`args\` must be an object or JSON string, got ${typeof raw}.`)
}

// ── cold-start rehydrate / prune (§6.1 step 3, reboot-proof) ─────────────────────────────────
// Given the campaign's full ordered wave list and the set of wave ids already PROMOTED (read back
// from durable wave-status on cold start), return the pending waves IN ORDER. Pure: a reboot at
// wave 5 prunes waves 1–4 and resumes at 5. Idempotent — re-running with the same promoted set
// yields the same pending list.
export function computePending(allWaves, promotedWaveIds) {
  const promoted = new Set((promotedWaveIds ?? []).map(String))
  return (allWaves ?? []).filter((w) => !promoted.has(String(waveIdOf(w))))
}

// A wave entry may be a bare id or an object carrying {id|waveId|wave, issues, ...}. One accessor
// so the loop never cares which shape the plan used.
export function waveIdOf(wave) {
  if (wave == null) return null
  if (typeof wave === 'object') return wave.id ?? wave.waveId ?? wave.wave ?? null
  return wave
}

// ── verdict routing (§6.1 step 1) — the per-wave spine's {gate, promoted} return ─────────────
// ADVANCE only on a wave that PASSED its trust gate AND actually landed on the protected branch
// (promoted===true). A PASS that did not promote (interactive, or a promotion that did not land)
// HOLDs — the campaign never builds the next wave on a baseline that never reached the trunk
// (catalog signal I: "promoted ≠ delivered"). Anything else (HOLD/SKIPPED) HOLDs.
export function routeVerdict(verdict) {
  const gate = verdict?.gate ?? null
  const promoted = verdict?.promoted === true
  if (gate === 'PASS' && promoted) return { advance: true, reason: 'gate PASS and promoted' }
  if (gate === 'PASS' && !promoted) {
    return { advance: false, reason: `gate PASS but NOT promoted (${verdict?.reason || 'did not land on protected branch'}) — campaign holds rather than build on an un-landed baseline` }
  }
  return { advance: false, reason: `gate ${gate ?? 'UNKNOWN'}${verdict?.reason ? `: ${verdict.reason}` : ''}` }
}

// ── judgment routing (§6.1 step 1 / §2.2) — the wave-oversight sub-agent's verdict ───────────
// ADVANCE only on an explicit continue:true. Anything else — a flag, a malformed/absent verdict —
// HOLDs (absence of a clear "continue" is not a license to proceed; same conservative stance as
// the per-wave trust gate, SEAMS invariant 6).
export function routeJudgment(judgment) {
  if (judgment?.continue === true) return { advance: true, reason: 'judgment: continue' }
  const what = judgment?.concern?.what
  return { advance: false, reason: what ? `judgment flagged: ${what}` : 'judgment did not return continue:true — campaign holds (conservative)' }
}

// ── the loop DRIVER (pure given its injected seams) ──────────────────────────────────────────
// runWave(wave, index)  → Promise<verdict>   (the per-wave spine; verdict carries {gate, promoted})
// judge(wave, context)  → Promise<judgment>  (the wave-oversight sub-agent; {continue, concern, ...})
//                          context = { completed:[{wave,verdict}], remaining:[waveId], index }
// onEvent(event)        → void               (optional progress sink: {type, wave, ...})
//
// Returns a terminal CAMPAIGN report:
//   { outcome: 'completed' | 'held', wavesAdvanced:[id], heldAt?:id, heldReason?, completed:[{wave,verdict,judgment}] }
// HOLD-and-end is a terminal report, never a throw (a Workflow ending with a report IS the human
// handoff, §2.2). A runWave/judge that THROWS becomes a conservative HOLD on that wave, not a crash.
export async function runCampaign({ pending, runWave, judge, onEvent }) {
  const emit = typeof onEvent === 'function' ? onEvent : () => {}
  const completed = []
  const wavesAdvanced = []
  const waves = pending ?? []

  for (let i = 0; i < waves.length; i++) {
    const wave = waves[i]
    const id = waveIdOf(wave)
    emit({ type: 'wave-start', wave: id, index: i })

    let verdict
    try {
      verdict = await runWave(wave, i)
    } catch (e) {
      return hold(id, `per-wave spine errored: ${e?.message || e}`, completed, wavesAdvanced)
    }
    const vr = routeVerdict(verdict)
    emit({ type: 'verdict', wave: id, gate: verdict?.gate ?? null, promoted: verdict?.promoted === true, advance: vr.advance })
    if (!vr.advance) {
      completed.push({ wave: id, verdict, judgment: null })
      return hold(id, vr.reason, completed, wavesAdvanced)
    }

    // Gate said advance — now the wave-oversight judgment seam (§2.2). It inspects the WHOLE
    // trajectory so far, not just this wave, to catch accumulation / intent-drift the per-wave
    // gate structurally cannot (§4).
    const context = {
      completed: completed.map((c) => ({ wave: c.wave, verdict: c.verdict })), // PRIOR waves (this wave not yet pushed)
      wave: id,         // the JUST-LANDED wave id
      verdict,          // the JUST-LANDED wave's verdict — NOT yet in `completed`; the seam must
                        // surface it (justLanded) + append it to the trajectory, else the judgment
                        // seed is always missing its most-recent wave (the primary evidence).
      remaining: waves.slice(i + 1).map(waveIdOf),
      index: i,
    }
    let judgment
    try {
      judgment = await judge(wave, context)
    } catch (e) {
      completed.push({ wave: id, verdict, judgment: null })
      return hold(id, `wave-oversight judgment errored: ${e?.message || e}`, completed, wavesAdvanced)
    }
    const jr = routeJudgment(judgment)
    emit({ type: 'judgment', wave: id, advance: jr.advance })
    completed.push({ wave: id, verdict, judgment })
    if (!jr.advance) {
      return hold(id, jr.reason, completed, wavesAdvanced)
    }

    wavesAdvanced.push(id)
    emit({ type: 'advanced', wave: id })
  }

  emit({ type: 'campaign-complete', wavesAdvanced })
  return { outcome: 'completed', wavesAdvanced, completed }
}

function hold(heldAt, heldReason, completed, wavesAdvanced) {
  return { outcome: 'held', heldAt, heldReason, wavesAdvanced, completed }
}

// ── intent-tier resolver (§3 — tiered intent, graceful degradation) ──────────────────────────
// A rehydrate agent reports what intent artifacts EXIST (it runs devspec_locate / ddd_locate_*);
// this PURE fn picks the richest available tier so the choice is deterministic + testable. The
// agent is then TOLD its tier and calibrates (rigorous spec-fidelity with a devspec; "ACs met +
// trajectory coherent" with only issues) — naming the tier prevents both faking a check it cannot
// do and hedging when it has solid ground.
export function resolveIntentTier({ devspec, domainModel, sketchbook } = {}) {
  if (devspec) return 'devspec'
  if (domainModel || sketchbook) return 'plan-ddd-sketchbook'
  return 'issues-only'
}

// ── wave-oversight judgment prompt — THE LENS (#750/§4 + §7) ──────────────────────────────────
// The seed is handed RAW (no distillation, §3): tiered intent + the durable cross-wave trajectory
// (#748) + the just-landed wave + live-inspection tools. The §7 failure-shapes are the crowdsourced
// cross-wave catalog (A–J, [[project_wave_oversight_failure_catalog]]) — "go with what came in over
// Discord" (BJ, 2026-06-20). routeJudgment + JUDGMENT_RESULT are the stable contract; this body is
// the lens. Same record + wrong lens = a checkpoint that rubber-stamps; this is the difference.
export function waveOversightPrompt({ justLanded, trajectory, remainingPlan, intentTier, intentRefs, kahunaBranch }) {
  const tier = intentTier ?? 'issues-only'
  const calibration = {
    'devspec': `DEVSPEC tier — the un-gameable reference the flights did not write. Hold spec-fidelity: run dod_check_coverage / dod_verify_deliverable for HARD VRTM + Deliverables-Manifest traceability, and devspec_* checks. A wave that passed its own tests but misses a manifest deliverable is DRIFT.`,
    'plan-ddd-sketchbook': `PLAN/DDD/SKETCHBOOK tier — judge against the recorded decision ledger + domain intent (ddd_locate_domain_model / ddd_locate_sketchbook). No VRTM; "decisions honored + domain model intact + trajectory coherent".`,
    'issues-only': `ISSUES-ONLY tier — no spec/DDD. Judge "each wave's own ACs met + the trajectory is coherent". Be honest about the ceiling: you cannot check spec-fidelity you do not have — do NOT fake it.`,
  }[tier] ?? `ISSUES-ONLY tier.`
  return [
    `You are the WAVE-OVERSIGHT judgment agent — the campaign-layer checkpoint BETWEEN waves. A wave`,
    `just PASSED its per-wave trust gate and promoted to the protected branch. Your question (§4):`,
    `given the INTENT and the TRAJECTORY so far, is it sound to continue into the rest of the`,
    `campaign — or is something lurking that every individual per-wave gate structurally could NOT`,
    `catch? You are the only view with the whole trajectory + the un-gameable intent; the flights`,
    `wrote both their code AND their tests, so "green per wave" is not "correct to intent".`,
    ``,
    `── INTENT TIER: ${tier} ──`,
    calibration,
    intentRefs ? `Intent refs: ${JSON.stringify(intentRefs)}.` : `Intent refs: none discovered.`,
    ``,
    `── THE SEED (raw, no distillation — §3) ──`,
    `Just-landed wave (its diff/signals/reconcile are yours to inspect): ${JSON.stringify(justLanded ?? null)}`,
    `Durable cross-wave trajectory — every completed wave's RAW record (gate/promoted, the four trust`,
    `signals + detail, concerns, deferrals, rework, commutativity, files_touched, engine_fingerprint,`,
    `issues; #748). This is your primary evidence — read it as a TIME SERIES, not a snapshot:`,
    JSON.stringify(trajectory ?? [], null, 2),
    `Remaining plan (judge "sound to proceed INTO the rest"): ${JSON.stringify(remainingPlan ?? [])}`,
    `LIVE INSPECTION: you have read tools and the kahuna branch (${kahunaBranch ?? 'n/a'}) checked out.`,
    `When something smells, GO LOOK at the actual code/tests/manifests — this is a real inspection,`,
    `not a record read. A claim you can verify, verify.`,
    ``,
    `── THREE DETECTION MODES (apply all three) ──`,
    `1. TREND — a metric sliding wrong ACROSS waves (not one bad wave). 2. ABSENCE — a datapoint that`,
    `SHOULD exist and never does (the hardest; you cannot trend your way to "never real"). 3. CONFOUND`,
    `CONTROL — do NOT blame the code for a substrate/engine step-change: if engine_fingerprint changed`,
    `between waves, or a host/env event (reboot, reinstall, DNS) sits at a metric's step, attribute the`,
    `discontinuity to the SUBSTRATE, not the content. Separate environment-caused from content-caused.`,
    ``,
    `── THE FAILURE-SHAPE LENS (crowdsourced cross-wave catalog; hunt every one) ──`,
    `A. GATE-VOUCHED-BUT-WRONG (intent-drift): fix-forward commits in wave N touching files a PRIOR`,
    `   promoted wave shipped (latent doc-vs-impl drift); negative/deny tests asserting only exit!=0`,
    `   not the SPECIFIC error kind (pass spuriously, hide a boundary regression) — esp. in authz/security.`,
    `B. UNDER-SPECIFICATION: the SAME subsystem in ≥3 non-adjacent waves' diffs it wasn't scoped to`,
    `   (under-specified, more latent defects coming); COMMUTATIVITY decay on a SHARED HOTSPOT — the`,
    `   same OVERLAPPING path set tripping ORACLE_REQUIRED across waves (an unfactored shared-infra dep`,
    `   the decomposition missed ⇒ "parallel" waves serialize). NB: ORACLE volume across DIFFERENT files`,
    `   is benign — the smell is the repeated overlap, not the count.`,
    `C. DIVERGENCE RATES: manual-intervention climbing (force-pushes / gate-disables / kahuna-recreates /`,
    `   non-FF resolutions per wave); local-green → rising "fix CI deps/env" commits ("config exists ≠ works").`,
    `D. CROSS-TEAM CONTRACT: a wave adds a HARD dependency on another team's surface with NO`,
    `   graceful-in-absence fallback ⇒ a matched-pair break on a different cadence.`,
    `E. SPY/MOCK-ONLY UN-EXERCISED SURFACE (absence): a runtime boundary (container bring-up, TLS, a`,
    `   shelled binary, an external call) accruing code wave-over-wave while tests that run the REAL`,
    `   artifact stay ~0. The tell is the MISSING real-execution datapoint, not a failing one —`,
    `   "command-ran ≠ thing-attached"; a real run later detonates a CHAIN of never-attached gaps.`,
    `F. SUBSTRATE/ENGINE CONFOUNDS: engine_fingerprint/toolkit drift mid-campaign (wave 1 ran different`,
    `   semantics than wave 7); host/env events. Treat as an ANNOTATION, never a content-trend (mode 3).`,
    `G. IMPERATIVE-WITHOUT-VERIFY-AFTER: mutate-state steps (enable/load/apply/init/up) accrue while`,
    `   read-back-and-ASSERT steps don't — ratio drifting to 1:0. "Assert the post-state, not the command."`,
    `H. STALE EXTERNAL-STATE ASSERTIONS: agent-authored tracker pins / handoffs / reseed text asserting`,
    `   external state (issue open, file shape, branch ahead) from MEMORY not a re-read — fails a re-read.`,
    `I. PROMOTED ≠ DELIVERED ≠ RUNNING: a "promoted" wave whose delivery is a silent no-op — no assertion`,
    `   the RUNNING artifact carries the promoted SHA/digest; deploy-inventory lag (code+tests grow, the`,
    `   publish/fragment/compose inventory doesn't ⇒ "done" on the board, does-not-exist in reality).`,
    `J. CERTIFIER/DOC DRIFT: the facade migrates UP a layer when attacked (features → the tests guarding`,
    `   them → the doc/matrix certifying them); a confidently-wrong authoritative doc contradicting a`,
    `   higher-authority source (CLAUDE.md/spec), propagating by inheritance. A certifier untouched while`,
    `   its subject churned = flag.`,
    ``,
    `── ADAPTATION vs DRIFT (the discriminator) ──`,
    `A deviation CONSCIOUSLY RECORDED (a logged deferral/concern) is ADAPTATION — fine. A SILENT deviation`,
    `from intent is DRIFT — flag it. The two classes the per-wave gate cannot catch: ACCUMULATION (waves`,
    `2,4,5 all raising concerns/deferrals/rework in the SAME subsystem ⇒ a lurking architectural problem`,
    `each individual green gate passed) and INTENT-DRIFT (passes its own tests, builds the wrong thing).`,
    `Devspec + trajectory together make the discrimination possible.`,
    ``,
    `── OUTPUT ── Return EXACTLY: { continue (bool), confidence (0..1), concern: { what, which_waves`,
    `(array), which_subsystem, severity }, recommendation }. continue:true ONLY if genuinely sound to`,
    `proceed; a real lurking smell ⇒ continue:false with a PRECISE concern (which waves, which subsystem).`,
    `Absence of a clear "continue" is not a license to proceed — when uncertain after inspecting, hold.`,
  ].join('\n')
}

// The §3 output contract — the loop routes on `continue`; #750 refines the prompt, not this schema.
export const JUDGMENT_RESULT = {
  type: 'object',
  additionalProperties: false,
  required: ['continue'],
  properties: {
    continue: { type: 'boolean' },
    confidence: { type: 'number' },
    concern: {
      type: 'object',
      additionalProperties: true,
      properties: {
        what: { type: 'string' },
        which_waves: { type: 'array', items: { type: 'string' } },
        which_subsystem: { type: 'string' },
        severity: { type: 'string' },
      },
    },
    recommendation: { type: 'string' },
  },
}
