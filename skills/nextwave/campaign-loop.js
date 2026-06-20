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
      completed: completed.map((c) => ({ wave: c.wave, verdict: c.verdict })),
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

// ── wave-oversight judgment prompt (PLACEHOLDER until #750/§6.2) ──────────────────────────────
// #749 step 4: structure the call site + the continue/hold routing NOW; the real seed contract +
// failure-shape lens land in #750. This builder produces a sound, honest interim prompt: it hands
// the agent the durable trajectory + remaining plan (no distillation, §3) and asks the §4 question.
// The output schema is the §3 contract so #750 can swap the prompt body without touching the loop.
export function waveOversightPrompt({ justLanded, trajectory, remainingPlan, intentTier }) {
  return [
    `You are the WAVE-OVERSIGHT judgment agent (campaign-layer, between-wave checkpoint).`,
    `A wave just PASSED its per-wave trust gate and promoted. Decide: given the intent and the`,
    `trajectory SO FAR, is it sound to continue into the rest of the campaign — or is something`,
    `lurking that every individual per-wave gate structurally could not catch?`,
    ``,
    `Intent tier: ${intentTier ?? 'issues-only'} — calibrate rigor to it (devspec ⇒ spec-fidelity;`,
    `issues-only ⇒ "ACs met + trajectory coherent"). Do NOT fake a check you lack the inputs for.`,
    ``,
    `Just-landed wave: ${JSON.stringify(justLanded ?? null)}`,
    ``,
    `Durable cross-wave trajectory (every completed wave's raw record — gate/promoted, the four`,
    `trust signals + detail, concerns, deferrals, rework, commutativity, issues; #748):`,
    JSON.stringify(trajectory ?? [], null, 2),
    ``,
    `Remaining plan (so the judgment is "sound to proceed INTO the rest"): ${JSON.stringify(remainingPlan ?? [])}`,
    ``,
    `Hunt the two failure classes the per-wave gate cannot (§4): ACCUMULATION (multiple green waves`,
    `raising concerns/deferrals/rework in the SAME subsystem ⇒ a lurking architectural problem) and`,
    `INTENT-DRIFT (a wave passes its own self-authored tests yet builds something other than what`,
    `was specified). Distinguish ADAPTATION (a consciously recorded deferral/concern) from DRIFT (a`,
    `silent deviation). You have read tools + the kahuna branch — GO LOOK at the actual code when`,
    `something smells; this is a real inspection, not a record read.`,
    ``,
    `Return EXACTLY: { continue (bool), confidence (0..1), concern: { what, which_waves, which_subsystem,`,
    `severity }, recommendation }. continue:true ONLY if it is genuinely sound to proceed.`,
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
