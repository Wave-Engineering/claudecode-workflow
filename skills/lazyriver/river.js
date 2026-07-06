// river.js — pure, testable helpers for the /lazyriver goal-seek Workflow (#844).
//
// The agent output schemas, the prompt builders, and the CODED escalation cord.
// These live in a module (not the workflow file) so they can be unit-tested: a
// Dynamic Workflow file uses top-level `await`/`return` (illegal in a plain ESM
// module), so its pure halves are extracted here and inlined into the single-file
// artifact by bundle.mjs. Same split as the wave engine (gate.js / resume.js).
//
// Design of record: docs/executor-model-devspec.md (Plan #822 — the goal-seek
// half). SKILL contract: skills/lazyriver/SKILL.md.

// ── Agent output schemas (agent() forces a StructuredOutput against these) ─────

// One leg's verdict. The leg agent probes, journals (BEFORE it judges), judges
// sufficiency, and — if not yet — steers to the next probe. `zeroNewFindings` is
// the cord counter; `sufficiency` is the agent's judgment (the cord is the loop's).
export const LEG_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['legSummary', 'zeroNewFindings', 'sufficiency'],
  properties: {
    legSummary: { type: 'string' }, // 1-2 lines: what this probe found (for the driver log)
    zeroNewFindings: { type: 'boolean' }, // true IFF this leg added nothing new — the cord counter
    sufficiency: { enum: ['sufficient', 'not-yet'] }, // the agent's call; the cord is the harness's
    output: {
      // set IFF sufficiency === 'sufficient'
      type: ['object', 'null'],
      additionalProperties: false,
      properties: {
        kind: { enum: ['plan', 'answer'] }, // plan → hand to /devspec ; answer → the user
        content: { type: 'string' },
      },
    },
    nextProbe: { type: ['string', 'null'] }, // set IFF sufficiency === 'not-yet'
  },
}

// Rehydrate verdict: read an existing journal and report where the loop stands.
export const REHYDRATE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['legCount', 'consecutiveZeroFindings'],
  properties: {
    legCount: { type: 'integer' }, // how many "## Leg N" entries the journal contains
    consecutiveZeroFindings: { type: 'integer' }, // trailing run of zero-finding legs (seeds the cord)
    nextProbe: { type: ['string', 'null'] }, // the last leg's Steer line, if any
    resumeSummary: { type: 'string' }, // 1-2 lines: where the loop stands
  },
}

// ── Coded escalation cord (the LOOP owns this, NOT the agent) ─────────────────
// The sufficiency CALL is the agent's judgment (LEG_SCHEMA.sufficiency); the CORD
// is a mechanical guard the loop enforces at the top of every iteration. First
// trigger wins. Returns a cord reason, or null to keep looping. SKILL "Escalation
// Cord": leg cap (default 10) OR 2 consecutive zero-finding legs (diminishing).
export function cordCheck({ legNum, maxLegs, consecutiveZeroFindings }) {
  if (legNum > maxLegs) return 'cord:leg-cap' // budget guardrail (checked before running the Nth leg)
  if (consecutiveZeroFindings >= 2) return 'cord:diminishing' // the map stopped moving
  return null
}

// ── Prompt builders ───────────────────────────────────────────────────────────

// One leg: probe → journal (BEFORE judge) → judge sufficiency → steer. The harness
// owns the cord; the agent owns the honest per-leg judgment. File I/O + timestamps
// happen HERE (the agent has Bash/Write) because the Workflow script has neither.
export function legPrompt({ goal, journalPath, legNum, probe }) {
  return [
    `You are running leg ${legNum} of a /lazyriver goal-seek loop (contract: skills/lazyriver/SKILL.md).`,
    `GOAL (run to a SUFFICIENCY judgment, not a task list): ${goal}`,
    `THIS LEG'S PROBE (set by the previous leg's steer; the goal itself on leg 1): ${probe}`,
    ``,
    `First, read the accumulated findings journal for context (may not exist yet on leg 1 — that is fine):`,
    `  ${journalPath}`,
    ``,
    `Run FOUR steps IN ORDER — the order is load-bearing:`,
    `1. PROBE — actually run the probe: research / experiment / implement-a-spike / analyze. Do the work`,
    `   and gather REAL findings. DI-seam-then-close: if the probe needs something not yet built, inject`,
    `   a working default (a seam) and journal it — do NOT block or escalate reflexively.`,
    `2. JOURNAL (before you judge) — append a dated entry to ${journalPath} (create the file if absent):`,
    `     ## Leg ${legNum} — <short probe description>  (<timestamp: run: date -u +%Y-%m-%dT%H:%MZ>)`,
    `     **Probe:** <what you ran>`,
    `     **Findings:** <what you learned — or the literal words "zero new findings" if this leg added nothing>`,
    `     **Sufficiency:** <sufficient | not-yet>`,
    `     **Steer:** <the next probe, if not-yet>`,
    `   Journal-before-judge is non-negotiable: a cord-fire must never lose the leg it just ran (CT-04).`,
    `3. JUDGE — the sufficiency gate: is the GOAL genuinely met (answered / design trusted / hypothesis`,
    `   decided)? Return sufficiency='sufficient' only then; otherwise 'not-yet'. Set zeroNewFindings=true`,
    `   ONLY if this leg added nothing new to the map — be honest; that record is what the escalation cord`,
    `   counts. Do NOT talk yourself into "one more probe".`,
    `4. STEER — if 'not-yet', formulate the single most informative NEXT probe from what THIS leg just`,
    `   taught, and return it as nextProbe. If 'sufficient', produce the OUTPUT: a structured plan`,
    `   (output.kind='plan', to hand to /devspec) when the goal-seek converged on what-to-build, or a`,
    `   direct answer (output.kind='answer', the answer IS the deliverable) otherwise.`,
    ``,
    `Do NOT decide to STOP looping yourself: the escalation cord (2 consecutive zero-finding legs, or the`,
    `leg cap) is enforced by the harness, not you. Your job is one honest leg. Return the structured verdict.`,
  ].join('\n')
}

// Rehydrate on resume: read the existing journal and report the loop's state so the
// script can continue at the right leg with the right cord counter. No probe here.
export function rehydratePrompt({ goal, journalPath }) {
  return [
    `Resuming a /lazyriver goal-seek loop. GOAL: ${goal}`,
    `Read the existing findings journal: ${journalPath}`,
    `Report, as structured output (do NOT run a probe — just read and report):`,
    `  legCount — how many "## Leg N" entries the journal contains.`,
    `  consecutiveZeroFindings — how many of the MOST RECENT consecutive legs recorded "zero new findings"`,
    `    (0 if the last leg found something). This seeds the escalation cord.`,
    `  nextProbe — the Steer line of the LAST leg (the probe to run next), or null if none.`,
    `  resumeSummary — 1-2 lines on where the loop stands.`,
  ].join('\n')
}
