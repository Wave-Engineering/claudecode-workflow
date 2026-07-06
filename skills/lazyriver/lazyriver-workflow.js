// lazyriver-workflow.js — the /lazyriver goal-seek loop as a background Workflow (#844).
//
// The goal-seek half of the executor model (Plan #822), migrated from an in-main-
// session skill into a background Workflow — the same move #691 applied to the wave
// engine (per-wave-workflow.js). Runs async/detached so the operator's session stays
// interactive while a goal-seek floats.
//
// SHAPE (mirrors the wave engine's closed-legal-exit spine):
//   rehydrate (resume from journal, else cold-start from the goal)
//     → goal-seek loop  [ per leg: probe → journal → judge → steer ]
//         CLOSED EXITS (coded — cannot be forgotten):
//           sufficient        → emit output (plan | answer)        ← the agent's judgment
//           cord:diminishing  → 2 consecutive zero-finding legs    ← the loop's guard
//           cord:leg-cap      → maxLegs (default 10)               ← the loop's guard
//     → emit  [ sufficient → {output} ; cord → {escalated} verdict the driver surfaces ]
//
// LOAD-BEARING (per the design discussion + SKILL):
//   - The sufficiency CALL is the leg agent's judgment; the CORD is the loop's coded
//     guard. Judgment in the agent, mechanical exit in the script — exactly the wave
//     engine's division of labor.
//   - journal-before-judge: the leg agent writes its journal entry BEFORE it judges,
//     so a cord-fire never loses the leg it just ran (CT-04).
//   - A cord-fire RETURNS an {outcome:'escalated'} verdict — a thing the main session
//     SURFACES to the operator, exactly like a wave HOLD. NEVER a silent background
//     stall. (The whole point of the cord is a human sufficiency call.)
//   - The durable findings journal is the shared state; resume rehydrates it.
//
// No filesystem / no Date in a Workflow script (they break resume): all journal I/O
// and timestamps happen inside agent() calls (the agents have Bash/Write); the script
// owns only control flow. Source of truth: this file + river.js; the Workflow tool runs
// lazyriver-workflow.bundled.js (regenerate via: node skills/lazyriver/bundle.mjs).

import { LEG_SCHEMA, REHYDRATE_SCHEMA, cordCheck, legPrompt, rehydratePrompt } from './river.js'

export const meta = {
  name: 'lazyriver-workflow',
  description:
    'Goal-seek Workflow (Plan #822 goal-seek half): probe to journal to judge to steer loop toward a sufficiency judgment; coded sufficiency-gate + escalation-cord (2 consecutive zero-finding legs or a leg cap). Emits a plan or a direct answer on sufficiency, or an escalated verdict on cord-fire that the driver surfaces. The durable findings journal is the shared state; resume rehydrates it.',
  phases: [
    { title: 'Rehydrate', detail: 'resume from an existing findings journal, else cold-start from the goal' },
    { title: 'Goal-seek loop', detail: 'per leg: probe to journal to judge to steer; CLOSED exits: sufficient or cord (2 zero-finding legs or leg cap)' },
    { title: 'Emit', detail: 'sufficient emits plan or answer; cord returns an escalated verdict the driver surfaces (never a silent stall)' },
  ],
}

// ── PARAMETERS (from the Workflow runtime global `args`, NEVER `input`) ────────
function parseArgs(raw) {
  if (raw == null) return {}
  if (typeof raw === 'string') {
    const s = raw.trim()
    if (!s) return {}
    try {
      return JSON.parse(s)
    } catch (e) {
      throw new Error(`lazyriver-workflow: \`args\` is a string but not valid JSON: ${e?.message || e}. Pass args as a JSON OBJECT.`)
    }
  }
  if (typeof raw === 'object') return raw
  throw new Error(`lazyriver-workflow: \`args\` must be an object or JSON string, got ${typeof raw}.`)
}
const params = parseArgs(typeof args !== 'undefined' ? args : undefined)
const GOAL = params.goal ?? null
// fail-loud: a goal-seek with no goal is the lazyriver analog of the wave engine's empty-wave hard error.
if (!GOAL || typeof GOAL !== 'string' || !GOAL.trim()) {
  throw new Error(`lazyriver-workflow: missing \`goal\`. Launch with args {goal:"<goal statement>", journalPath:"<durable .md path>"}.`)
}
// The durable journal is load-bearing (the loop's memory + resumability) and the script has no
// filesystem, so the launcher must supply a concrete path the leg agents append to. Fail-loud
// rather than invent one (the script cannot mint a unique path — no Date/Math.random).
const JOURNAL_PATH = params.journalPath ?? null
if (!JOURNAL_PATH || typeof JOURNAL_PATH !== 'string') {
  throw new Error(`lazyriver-workflow: missing \`journalPath\`. Supply a durable markdown path the leg agents append to (and resume reopens).`)
}
const MAX_LEGS = Number.isFinite(params.maxLegs) ? params.maxLegs : 10 // SKILL default leg cap
const RESUME = !!params.resume // resume an existing journal (rehydrate its accumulated state)?

// ── REHYDRATE ─────────────────────────────────────────────────────────────────
phase('Rehydrate')
let legNum = 1 // the leg about to run
let consecutiveZero = 0 // trailing run of zero-finding legs (the diminishing cord counter)
let nextProbe = GOAL // leg 1 probes the goal itself
if (RESUME) {
  const rh = await agent(rehydratePrompt({ goal: GOAL, journalPath: JOURNAL_PATH }), {
    schema: REHYDRATE_SCHEMA,
    label: 'lazyriver:rehydrate',
    phase: 'Rehydrate',
  })
  if (rh) {
    legNum = (rh.legCount || 0) + 1
    // resume is a deliberate "keep probing" signal: reset the diminishing counter so the loop gets a
    // fresh budget rather than immediately re-firing cord:diminishing on leg 0. (Raise maxLegs to
    // resume past a leg-cap — that is the leg-cap lever.) #844 code-review.
    consecutiveZero = 0
    nextProbe = rh.nextProbe || GOAL
    log(`resumed ${JOURNAL_PATH}: ${rh.legCount} legs (${rh.consecutiveZeroFindings || 0} trailing zero-finding — reset for fresh probing) — ${rh.resumeSummary || ''}`)
  } else {
    log(`resume requested but rehydrate returned nothing — cold-starting from the goal`)
  }
}

// ── GOAL-SEEK LOOP (closed legal exits) ───────────────────────────────────────
phase('Goal-seek loop')
let outcome = null // 'sufficient' on the success exit; else null → escalated
let output = null // the plan|answer, on sufficiency
let escalation = null // { reason, legs } on a cord-fire (or a defensive exit)

for (;;) {
  // CODED EXIT — the escalation cord (leg cap OR 2 consecutive zero-finding legs). Checked at the
  // top so it catches the diminishing counter set at the end of the prior iteration AND the cap.
  const cord = cordCheck({ legNum, maxLegs: MAX_LEGS, consecutiveZeroFindings: consecutiveZero })
  if (cord) { escalation = { reason: cord, legs: legNum - 1 }; break }

  const leg = await agent(legPrompt({ goal: GOAL, journalPath: JOURNAL_PATH, legNum, probe: nextProbe }), {
    schema: LEG_SCHEMA,
    label: `lazyriver:leg-${legNum}`,
    phase: 'Goal-seek loop',
  })
  if (!leg) { escalation = { reason: 'leg-agent-died', legs: legNum - 1 }; break } // defensive (agent died/skipped)
  log(`leg ${legNum}: ${leg.zeroNewFindings ? 'zero new findings' : 'new findings'} · sufficiency=${leg.sufficiency} — ${leg.legSummary}`)

  // CODED EXIT — sufficiency (the agent's judgment; the only success exit)
  if (leg.sufficiency === 'sufficient') { outcome = 'sufficient'; output = leg.output; break }

  // update the cord counter (honest zero-finding record), then STEER to the next leg
  consecutiveZero = leg.zeroNewFindings ? consecutiveZero + 1 : 0
  nextProbe = leg.nextProbe
  if (!nextProbe) { escalation = { reason: 'no-next-probe', legs: legNum }; break } // defensive
  legNum++
}

// ── EMIT ──────────────────────────────────────────────────────────────────────
phase('Emit')
// Success ONLY on a sufficient verdict that actually CARRIES output — a contentless 'sufficient'
// (the agent claimed done but produced no plan/answer) is escalated, not emitted as an empty win the
// operator cannot see. The escalation path is otherwise fully guarded. #844 code-review.
if (outcome === 'sufficient' && output && output.content && String(output.content).trim()) {
  log(`SUFFICIENT after ${legNum} legs → emitting ${output.kind || 'output'}`)
  return { outcome: 'sufficient', output, journalPath: JOURNAL_PATH, legs: legNum }
}
if (outcome === 'sufficient') {
  escalation = { reason: 'sufficient-without-output', legs: legNum } // sufficient but nothing to hand off
}
// cord-fire (or a defensive/contentless exit): return an ESCALATED verdict the main session surfaces
// to the operator for a sufficiency call — NEVER a silent background stall. Journal intact + resumable.
log(`ESCALATED (${escalation.reason}) after ${escalation.legs} legs — handing the sufficiency call to the operator`)
return { outcome: 'escalated', reason: escalation.reason, journalPath: JOURNAL_PATH, legs: escalation.legs }
