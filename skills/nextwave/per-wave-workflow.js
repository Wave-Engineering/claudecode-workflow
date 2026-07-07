// per-wave-workflow.js — the production per-wave Workflow (§3 spine).
//
// Design of record: docs/wavemachine-workflows-migration.md
//   §3   the spine: rehydrate → flight loop → trust gate → promote
//   §3.1 the dynamic flight loop (closed legal exits + hard progress guarantee + halt sentinel + dynamic re-plan)
//   §3.2 must-preserve behaviors (surface-concern, defer-a-fix, intra/cross-flight fixes — recorded, never branch-to-halt)
//   §3.3 resumability (rehydrate from wave-status; idempotent workers/reconcile)
//   §3.4 trust gate (4 parallel signals, ff-or-hold)
//   §4   cross-repo (single-repo-per-wave; durable worktrees; 3-point cleanup)
//
// WHAT IS REAL HERE (the validated part — harden, do not reinvent):
//   - the closed-legal-exit while-loop, the halt sentinel, the deterministic
//     progress accounting, and the dynamic re-plan (a surfaced dependency
//     re-opens an issue and becomes the next group). This mirrors the two
//     validated pilots verbatim in control-flow shape:
//       wave-pilot-iter3-spine-wf  (flight → reconcile → gate)
//       wave-pilot-iter3b-replan-wf (the §3.1 dynamic re-plan loop)
//   - the trust gate's 4-signal parallel fan-out + ff-or-hold verdict.
//
// SEAM STATUS (filled by the wave-2 foundational issues):
//   - rehydrate / idempotency               → #686 (FILLED — resume.js)
//   - real gate signals via sdlc-server      → #687 (FILLED — gate.js)
//   - wave-status persistence (durable state) → #688 (FILLED — wave-status.js)
//   See SEAMS.md (this dir) for the exact function/return signatures each seam expects.
//
// The agent() prompts below are REAL (worker / Prime-plan / Prime-reconcile /
// signal). With #687 filled, the sdlc-server MCP TOOL CALLS those agents make are
// REAL too: the four trust signals name commutativity_verify / ci_wait_run (on the MR
// merge-result pipeline [#452]) / code-reviewer on a kahuna worktree [#667] / trivy,
// each errors CONSERVATIVE-FAIL (HOLD, never silent PASS), and the auto-mode promotion
// (wave_finalize → pr_merge) is wired as CODE that runs only on a live wave's success exit.

// #688 wave-status persistence seam helper: durable blob shape/path + the persist
// agent prompts (the MCP record/close calls + the .claude/status/ blob write). See
// wave-status.js + SEAMS.md (#688). The loop calls persistIteration/persistTerminal below.
import { blobPath, toBlob, persistIterationPrompt, persistTerminalPrompt } from './wave-status.js'
// #686 resumability + idempotency seam helper: the rehydrate read-back + agent prompt, and the
// idempotent worktree setup / 3-point cleanup builders + prompts (§3.3/§4.2/§4.3). The pure halves
// (parseRehydrate, the git-command builders) are unit-tested without a live sdlc-server. See resume.js.
import {
  parseRehydrate,
  coldStart,
  rehydratePrompt,
  setupWorktreesPrompt,
  cleanupMergedPrompt,
  cleanupTerminalPrompt,
  wtRoot,
  wtPathFor,
  issueBranchFor,
} from './resume.js'
// #687 trust-gate seam helper: the four trust-signal agent prompts (each naming the real
// sdlc-server tool — commutativity_verify / ci_wait_run on the MR merge-result pipeline [#452] /
// code-reviewer on a kahuna worktree [#667] / trivy), the conservative-fail SIG that replaces the
// always-pass skeleton stub on a signal error (SEAMS invariant 6), and the auto-mode promotion
// prompt (wave_finalize → pr_merge — CODE ONLY, run solely on a live wave's success exit). See gate.js.
import {
  conservativeFail,
  openPromotionPrPrompt,
  OPEN_PR_RESULT,
  commutativitySignalPrompt,
  ciSignalPrompt,
  reviewStagePrompt,
  REVIEW_STAGE,
  reviewSignalPrompt,
  trivySignalPrompt,
  promotePrompt,
  PROMOTE_RESULT,
} from './gate.js'
// #824 (Story 1.2, Plan #822) dispatch ceiling seam: the pure, deterministic enforcement of the
// wave `dispatch` hint /prepwaves (#823) writes into phases-waves.json. normalizeDispatch resolves
// absent→'serialize' (CT-01); applyDispatchCeiling clamps each planned flight-group toward more
// serial (fan → parallel group as-is; serialize/serialize-preferred/absent → single-file). Ceiling,
// never a floor — it only makes a wave MORE serial, never less safe. See dispatch.js.
import { normalizeDispatch, applyDispatchCeiling } from './dispatch.js'

export const meta = {
  name: 'per-wave-workflow',
  description:
    'Production per-wave Workflow (§3 spine): rehydrate → dynamic flight loop (closed legal exits + dynamic re-plan) → trust gate → promote kahuna or hold-for-review. Parameterized by wave issue list, kahuna branch, target repo.',
  phases: [
    { title: 'Rehydrate', detail: 'durable resume — seed loop state from wave-status (§3.3)' },
    { title: 'Flight loop', detail: 'serial groups, parallel issues, dynamic re-plan, CLOSED legal exits (§3.1)' },
    { title: 'Trust gate', detail: '4 signals in parallel → ff-or-hold (success exit only) (§3.4)' },
    { title: 'Promote', detail: 'kahuna→protected-branch on PASS, else hold-for-review' },
  ],
}

// ─────────────────────────────────────────────────────────────────────────────
// PARAMETERS — a per-wave Workflow is launched per wave with this input blob.
// The campaign driver (skills/wavemachine) supplies it from the approved
// phase/wave plan. Defaults make the script self-describing when run bare.
//
// #1/#3/#4 (live-gate findings) — INPUT HANDLING:
//   #1  Read the RUNTIME GLOBAL `args` — NOT `input`. A Dynamic Workflow exposes its input as
//       `args`; the engine read a non-existent `input`, silently got {}, and proceeded with an
//       empty wave (see #4). `input` is never the right global.
//   #3  `args` may arrive as an OBJECT or a JSON STRING (tool-call quoting). parseArgs tolerates
//       both and fails loud on a non-JSON string rather than silently degrading to {}.
//   #4  An empty/missing wave ISSUE LIST is a HARD ERROR. An empty wave makes `pending` empty,
//       so the loop takes the success exit on group 0 and the trust gate opens/promotes at the
//       PROTECTED branch with NOTHING merged — exactly the silent-default-at-real-main the live
//       gate hit. Refuse to run instead (fail-loud); the campaign driver must pass a real wave.
// ─────────────────────────────────────────────────────────────────────────────
function parseArgs(raw) {
  if (raw == null) return {}
  if (typeof raw === 'string') {
    const s = raw.trim()
    if (!s) return {}
    try {
      return JSON.parse(s)
    } catch (e) {
      throw new Error(`per-wave-workflow: \`args\` is a string but not valid JSON: ${e?.message || e}. Pass args as a JSON OBJECT.`)
    }
  }
  if (typeof raw === 'object') return raw
  throw new Error(`per-wave-workflow: \`args\` must be an object or JSON string, got ${typeof raw}.`)
}
const params = parseArgs(typeof args !== 'undefined' ? args : undefined) // #1: the runtime global is `args`, never `input`
const WAVE_ID = params.waveId ?? 'W-?'
const TARGET_REPO = params.targetRepo ?? 'Wave-Engineering/ccwork-testtarget' // owner/repo for gh -R scoping
const TARGET_REPO_DIR = params.targetRepoDir ?? '/home/bakerb/sandbox/github/ccwork-testtarget' // clone the worktrees attach to
const KAHUNA_BRANCH = params.kahunaBranch ?? `kahuna/${WAVE_ID}` // integration target; never the protected branch
const PRESERVE_KAHUNA = params.preserveKahuna ?? false // #722: true ⇒ persistent per-plan kahuna (shared across a plan's waves) — promote does NOT delete it; default false = per-wave disposable (delete on promote)
const PROTECTED_BRANCH = params.protectedBranch ?? 'main' // promotion target on the success exit
const ALL_ISSUES = (params.issues ?? []).map(Number).filter(Number.isFinite) // the wave's issue numbers
// #4 fail-loud: refuse an empty wave rather than silently defaulting the gate at the protected branch.
if (ALL_ISSUES.length === 0) {
  throw new Error(
    `per-wave-workflow: empty wave issue list (params.issues=${JSON.stringify(params.issues ?? null)}). ` +
      `Refusing to run — an empty wave reaches the trust gate with nothing merged and would open/promote ` +
      `at ${PROTECTED_BRANCH}. Launch with {issues:[...]} (and waveId/kahunaBranch/targetRepo) via the ` +
      `Workflow tool's \`args\` as a JSON OBJECT.`,
  )
}
const MODE = params.mode ?? 'auto' // 'auto' (gate verdict drives promotion) | 'interactive' (verdict returned, human routes)
// #824 R-06/CT-01: the wave's dispatch hint (from phases-waves.json via /prepwaves #823, threaded by
// the launcher into args.dispatch). Governs the flight-group planner as a parallelism CEILING below —
// 'fan' → parallel group as-is; 'serialize'/'serialize-preferred'/absent → single-file. Absent → 'serialize'.
const DISPATCH = normalizeDispatch(params.dispatch)
const PLAN_ID = params.planId ?? null // wave plan id — wave_finalize needs it to assemble the kahuna→protected MR body (#687 promote)
const budget = params.budget ?? { total: 0, remaining: () => Infinity } // optional cost guard
const budgetRemaining = typeof budget.remaining === 'function' ? budget.remaining : () => (budget.remaining ?? Infinity) // tolerate `remaining` passed as a number, not a fn

// Closed numeric guards (§3.1) — the whole safety story is these + the exit set.
const MAX_GROUPS = params.maxGroups ?? 24
const MAX_REWORK = params.maxRework ?? 3
const MAX_IDLE = params.maxIdle ?? 2
const COST_FLOOR = params.costFloor ?? 80_000

// Durable worktree root (§4.2) — NOT /tmp (reboot-wiped, resume-hostile). Gitignored, hyphenated
// stem shared by dir+branch. The path/branch helpers live in resume.js (the #686 seam owner) so
// the dir, branch, and the cleanup glob all derive from ONE fs-safe wave-id sanitization (§4.3).
const WT_ROOT = wtRoot(TARGET_REPO_DIR, WAVE_ID)
const issueBranch = (n) => issueBranchFor(WAVE_ID, n) // #848: <type>/<n>-<waveId>-<slug> (deterministic default type/slug), so the push policy accepts it; the -<waveId>- infix scopes cleanup

// ─────────────────────────────────────────────────────────────────────────────
// STRUCTURED-RETURN SCHEMAS (real — these are the agent contracts)
// ─────────────────────────────────────────────────────────────────────────────
const REHYDRATE = {
  type: 'object',
  additionalProperties: false,
  required: ['merged', 'pending'],
  properties: {
    merged: { type: 'array', items: { type: 'integer' } },
    pending: { type: 'array', items: { type: 'integer' } },
    reworkCount: { type: 'object', additionalProperties: { type: 'integer' } },
    idleRounds: { type: 'integer' },
    groupsRun: { type: 'integer' },
  },
}
const NEXTGROUP = {
  type: 'object',
  additionalProperties: false,
  required: ['done', 'group'],
  properties: {
    done: { type: 'boolean' }, // planner can schedule nothing more from current state
    group: { type: 'array', items: { type: 'integer' } }, // the next flight-group (parallel issues)
    rationale: { type: 'string' },
  },
}
const WORK = {
  type: 'object',
  additionalProperties: false,
  required: ['issue', 'status'],
  properties: {
    issue: { type: 'integer' },
    status: { type: 'string', enum: ['implemented', 'blocked', 'already-present'] }, // already-present = idempotent resume hit (§3.3)
    branch: { type: 'string' },
    worktree: { type: 'string' },
    files_changed: { type: 'array', items: { type: 'string' } },
    // §3.2 must-preserve: structured fields the SCRIPT RECORDS but does NOT branch-to-halt on.
    concerns: { type: 'array', items: { type: 'string' } }, // surface-a-concern-and-continue
    deferrals: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['issue', 'reason'],
        properties: { issue: { type: 'integer' }, reason: { type: 'string' }, risk: { type: 'string' } },
      },
    },
    notes: { type: 'string' },
  },
}
const RECONCILE = {
  type: 'object',
  additionalProperties: false,
  required: ['merged', 'needs_rework'],
  properties: {
    merged: { type: 'array', items: { type: 'integer' } }, // issues now on kahuna this round
    needs_rework: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['issue', 'reason'],
        properties: { issue: { type: 'integer' }, reason: { type: 'string' } }, // surfaced dep / interface break
      },
    },
    conflicts_resolved: { type: 'array', items: { type: 'string' } }, // cross-flight fixes done here (§3.2.3)
    concerns: { type: 'array', items: { type: 'string' } },
    suite_summary: { type: 'string' },
    blocked: { type: 'boolean' }, // #724: true ⇒ a push to origin was REJECTED (gate/permissions/protected ref) → HOLD; reconcile must NOT local-merge
    block_reason: { type: 'string' }, // #724: the rejection text, surfaced in the wave HOLD
    notes: { type: 'string' },
  },
}
const SIG = {
  type: 'object',
  additionalProperties: false,
  required: ['signal', 'passed'],
  properties: { signal: { type: 'string' }, passed: { type: 'boolean' }, detail: { type: 'string' } },
}
// #686 — the worktree-setup agent's structured return: issue→path map (string-keyed, JSON-native).
const WORKTREES = {
  type: 'object',
  additionalProperties: false,
  required: ['worktrees'],
  properties: {
    worktrees: { type: 'object', additionalProperties: { type: 'string' } }, // { "<issue>": "<absPath>" }
    notes: { type: 'string' },
  },
}
// #686 — the cleanup agent's structured return (side-effects, not judgment; never halts the wave).
const CLEANUP_RESULT = {
  type: 'object',
  additionalProperties: false,
  required: ['persisted'],
  properties: {
    persisted: { type: 'boolean' },
    recorded: { type: 'array', items: { type: 'integer' } }, // issues cleaned this call
    notes: { type: 'string' },
  },
}
// #688 — the persist agent's structured return (it does side-effects, not judgment).
const PERSIST_RESULT = {
  type: 'object',
  additionalProperties: false,
  required: ['persisted'],
  properties: {
    persisted: { type: 'boolean' }, // the durable blob file was written
    recorded: { type: 'array', items: { type: 'integer' } }, // issues whose MR+close ran this call
    disposition: { type: 'string' }, // terminal only: promoted | held
    path: { type: 'string' }, // the blob path written
    trajectory_appended: { type: 'boolean' }, // #748 terminal only: the cross-wave trajectory entry was upserted
    notes: { type: 'string' }, // includes any soft tool error (never halts the wave)
  },
}

// ─────────────────────────────────────────────────────────────────────────────
// FlightDeck runtime tee (S1.6 / #856). Emit phase/step (+ a token-metric STUB)
// at each spine agent() node, for the operator's FlightDeck. HARD CONSTRAINT
// (TC-2): the Workflow SCRIPT does NO file-I/O and NO Date/Math.random — so these
// helpers are PURE STRING BUILDERS; the actual emit runs INSIDE the agent as a
// fire-and-forget `wave-status emit` Bash call NAMED IN THE PROMPT, never in the
// script body. Node latency is derived downstream from consecutive step
// timestamps (Dev Spec S2.3 — FREE); per-node TOKEN usage is gated on #853 and
// emitted here ONLY as an explicit null stub (R-19 — never a fabricated number).
// Applied to the SPINE nodes (rehydrate / plan / reconcile / open-pr / promote);
// per-node teeing of the parallel workers + the 4 trust signals co-delivers with
// the #853 token instrumentation (those trust/merge-critical prompts stay
// untouched here).
function flightdeckTee(opts) {
  const ph = (opts && opts.phase) || ''
  const label = (opts && opts.label) || ''
  return [
    ``,
    `── FlightDeck telemetry (fire-and-forget; do NOT report on it and do NOT let it affect your task) ──`,
    `As a side action, run these best-effort commands ONCE, ignore any error, then proceed with your real task:`,
    `  wave-status emit step --activity-id '${WAVE_ID}' --wave '${WAVE_ID}' --phase '${ph}' --label '${label}' || true`,
    `  # SEAM #853: per-node token usage is not yet available — emit the token metric with NO value (an honest null stub), never a fabricated number.`,
    `  wave-status emit metric --activity-id '${WAVE_ID}' --wave '${WAVE_ID}' --phase '${ph}' --metric tokens --label '${label}' || true`,
  ].join('\n')
}

// teeAgent(prompt, opts): run a real agent() node with the FlightDeck tee appended
// to its prompt. PURE delegation — string concat + the runtime `agent`; no I/O, no
// Date. Returns agent()'s promise so any existing `.catch(...)` still chains.
function teeAgent(prompt, opts) {
  return agent(prompt + '\n' + flightdeckTee(opts), opts)
}

// ─────────────────────────────────────────────────────────────────────────────
// SEAM STUBS — return obvious placeholders. The foundational wave-2 issues
// replace each body with the real sdlc-server-backed implementation. The exact
// function names + return shapes here ARE the interface contract (see SEAMS.md).
// ─────────────────────────────────────────────────────────────────────────────

// SEAM #686 — durable resume (FILLED). The script can't call MCP/CLI directly (§3.3), so a
// cheap rehydrate agent READS the durable wave-status blob (.claude/status/, NEVER /tmp) and
// returns the REHYDRATE loop seed: {merged, pending, reworkCount, idleRounds, groupsRun}. On a
// COLD start (no blob) it returns all issues pending / nothing merged; on a WARM start it returns
// the persisted core so the loop SKIPS finished work (SEAMS invariant 3 — `merged` is authoritative
// for skip-on-resume). reworkCount keys come back JSON-string-keyed; the loop Number-casts them
// (see the `Object.fromEntries(... Number(k) ...)` seed below). The pure read-back logic is
// resume.js parseRehydrate (unit-tested); the agent is the file read the script can't do itself.
async function rehydrate() {
  const seed = await teeAgent(
    rehydratePrompt({ waveId: WAVE_ID, allIssues: ALL_ISSUES, targetRepo: TARGET_REPO, targetRepoDir: TARGET_REPO_DIR }),
    { label: 'rehydrate', phase: 'Rehydrate', schema: REHYDRATE, agentType: 'general-purpose' },
  ).catch((e) => {
    // A rehydrate failure must NOT kill the resume — degrade to cold start (re-do, never crash on
    // your own restart, §3.3). Idempotent workers/reconcile make the re-run safe.
    log(`[#686] rehydrate soft-fail → cold start: ${e?.message || e}`)
    return null
  })
  if (!seed) return coldStart(ALL_ISSUES)
  // Structural defense (#686 review): normalize the AGENT return through parseRehydrate — excludes
  // merged from pending (so a resume never re-does merged work even if the agent hallucinates an
  // overlap), clamps counters, string-keys reworkCount, backfills dropped issues. The live path now
  // gets the same guarantee the test pins, not the raw agent seed.
  const norm = parseRehydrate(seed, ALL_ISSUES)
  log(`[#686] rehydrated — merged=[${norm.merged.join(',') || 'none'}] pending=[${norm.pending.join(',') || 'none'}] idle=${norm.idleRounds} groups=${norm.groupsRun}`)
  return norm
}

// SEAM #688 — persistence (FILLED). Runs right after Prime(reconcile) each iteration (§3.3):
// per newly-merged issue record its MR + close it, then full-overwrite the durable loop blob.
// Both side-effects ride one persist agent() (the script can't call MCP/CLI directly); the
// blob is the exact REHYDRATE-shape rehydrate() (#686) reads back. Implementation: wave-status.js.
async function persistIteration(state) {
  // #688 wave-status persistence (folded into the reconcile step, §3.3): per newly-merged
  // issue record its MR + close it, then full-overwrite the durable loop blob under
  // .claude/status/ — the EXACT shape rehydrate() (#686) reads back. The script can't call
  // MCP/CLI directly, so both side-effects ride one persist agent() (wave-status.js prompt).
  // Idempotent (SEAMS invariant 5): record/close are issue-keyed (overwrite/no-op); the blob
  // is a full file overwrite — replaying the same state is a no-op-or-overwrite, never a dup.
  const blob = toBlob({
    waveId: WAVE_ID,
    merged: state.merged, pending: state.pending,
    reworkCount: state.reworkCount, idleRounds: state.idleRounds, groupsRun: state.groupsRun,
  })
  const newlyMerged = [...(state.newlyMerged || [])].map(Number)
  const path = blobPath(TARGET_REPO_DIR, WAVE_ID)
  await agent(
    persistIterationPrompt({ waveId: WAVE_ID, targetRepo: TARGET_REPO, kahunaBranch: KAHUNA_BRANCH, newlyMerged, blob, path }),
    {
      label: `persist:${state.groupsRun}`,
      phase: 'Flight loop',
      schema: PERSIST_RESULT,
      agentType: 'general-purpose',
      // Persistence must never halt the wave (§3.2): a failed mirror falls back to a log line,
      // and the loop carries on — the in-memory state is still authoritative this run.
    },
  ).catch((e) => { log(`[#688] persistIteration soft-fail (loop continues): ${e?.message || e}`); return null })
  log(`[#688] persisted iter — merged=[${blob.merged.join(',') || 'none'}] pending=[${blob.pending.join(',') || 'none'}] idle=${blob.idleRounds} groups=${blob.groupsRun} → ${path}`)
}

// SEAM #688 — terminal persistence (FILLED): promote OR hold disposition recorded durably
// (wave-completion record + the blob's `terminal` field). Implementation: wave-status.js.
async function persistTerminal(disposition, detail) {
  // #688 wave-status persistence: record the wave's terminal disposition (promoted | held)
  // + detail into wave-status's wave-completion record (so the campaign driver's cold-start
  // rehydrate, §5, can prune a promoted wave) AND stamp it into the durable blob's `terminal`
  // field (so a resume sees the same disposition). Idempotent: a single keyed wave-completion
  // entry + a full blob overwrite — re-running with the same disposition is a no-op-or-overwrite.
  // The terminal blob carries the FINAL loop state via closure (initialized before any call).
  const blob = toBlob({
    waveId: WAVE_ID,
    merged, pending, reworkCount, idleRounds, groupsRun: groupsRunBase + groupsRun.length,
    terminal: { disposition, detail, at: null }, // `at` stamped by the persist agent at write time
  })
  const path = blobPath(TARGET_REPO_DIR, WAVE_ID)
  // #748 — the wave's terminal entry for the durable cross-wave trajectory (the #745/#750
  // judgment seed). The SCRIPT authors every field it already knows (reliable, no agent
  // guesswork); the persist agent adds ONLY the two shell-derived catalog fields
  // (files_touched, engine_fingerprint) best-effort in STEP 3. `signals` carries all four
  // trust signals; `commutativity` lifts that signal's verdict out for the intent-drift lens.
  const trajectoryEntry = {
    gate: gate?.verdict ?? null,                 // PASS | HOLD | SKIPPED
    promoted: disposition === 'promoted',
    detail,
    signals: (gate?.signals || []).map((s) => ({ signal: s.signal, passed: s.passed, detail: s.detail })),
    commutativity: (gate?.signals || []).find((s) => s.signal === 'commutativity')?.detail ?? null,
    concerns: allConcerns,                        // [{issue, concern}] — §3.2 surfaced-and-continued
    deferrals: allDeferrals,                      // §3.2 decided-and-recorded
    rework: reworkCount,                          // {issue: count} — re-open events (catalog C)
    issues: [...merged].map(Number).sort((a, b) => a - b), // issues shipped this wave (catalog A/B)
    groups: groupsRunBase + groupsRun.length,
  }
  await agent(
    persistTerminalPrompt({
      waveId: WAVE_ID, targetRepo: TARGET_REPO, targetRepoDir: TARGET_REPO_DIR,
      kahunaBranch: KAHUNA_BRANCH, protectedBranch: PROTECTED_BRANCH,
      disposition, detail, blob, path, trajectoryEntry,
    }),
    { label: `persist:terminal`, phase: 'Promote', schema: PERSIST_RESULT, agentType: 'general-purpose' },
  ).catch((e) => { log(`[#688] persistTerminal soft-fail: ${e?.message || e}`); return null })
  log(`[#688] persisted terminal — wave ${WAVE_ID} ${disposition}: ${detail} → ${path}`)
}

// SEAM #687 — FILLED. The always-pass gateSignalStub() is GONE: a signal that ERRORS now
// returns conservativeFail() (passed:false → HOLD), never a silent PASS (SEAMS invariant 6).
// The real signal prompts + the conservative-fail SIG + the promotion prompt live in gate.js.

// SEAM #686 — idempotent worktree setup (FILLED). Awaited as a SINGLE step before parallel()
// so workers are HANDED a path, never asked to create one (race-safety is structural, §4.2).
// The agent runs the create-or-reuse git commands (the script can't run git itself, §3.3):
// reuse an existing branch on resume (`git worktree add <path> <branch>`, NEVER -b), after a
// crash-recovery prune/sweep (§4.3). Returns the issue→path map the worker prompt is handed.
// Defensive: if the agent omits a path, fall back to the canonical wtPathFor() so the loop
// always hands every worker a path (the dirs are durable + idempotent regardless).
async function setupWorktrees(group) {
  const res = await agent(
    setupWorktreesPrompt({ waveId: WAVE_ID, targetRepo: TARGET_REPO, targetRepoDir: TARGET_REPO_DIR, kahunaBranch: KAHUNA_BRANCH, group }),
    { label: `worktrees:${group.join(',')}`, phase: 'Flight loop', schema: WORKTREES, agentType: 'general-purpose' },
  ).catch((e) => {
    log(`[#686] setupWorktrees soft-fail (using canonical paths): ${e?.message || e}`)
    return null
  })
  const got = (res && res.worktrees) || {}
  const map = {}
  for (const n of group) map[n] = got[String(n)] || got[n] || wtPathFor(TARGET_REPO_DIR, WAVE_ID, n) // canonical fallback
  log(`[#686] worktrees ready — group [${group.join(', ')}] → ${WT_ROOT}/issue-<n>`)
  return map
}

// SEAM #686 — per-merge cleanup (FILLED). 4-point sequence per just-merged issue (§4.3):
// `worktree remove --force` → `worktree prune` → `rm -rf` → `git branch -D <type>/<n>-<waveId>-<slug>` (#848).
// Keeps peak disk ≈ current group. The branch -D is load-bearing (worktree remove leaves the
// branch behind — pilot 1 accreted dead refs without it). Never halts the wave on a soft error.
async function cleanupMerged(issues) {
  if (!issues.length) return
  await agent(
    cleanupMergedPrompt({ waveId: WAVE_ID, targetRepo: TARGET_REPO, targetRepoDir: TARGET_REPO_DIR, issues }),
    { label: `cleanup:${issues.join(',')}`, phase: 'Flight loop', schema: CLEANUP_RESULT, agentType: 'general-purpose' },
  ).catch((e) => { log(`[#686] cleanupMerged soft-fail (loop continues): ${e?.message || e}`); return null })
  log(`[#686] cleaned worktrees+branches for [${issues.join(', ')}]`)
}

// SEAM #686 — wave-terminal cleanup (FILLED). Sweep the wave's remaining worktrees + prune +
// glob-delete every wave-<id>/* branch (§4.3) — clean at BOTH ends, not end-only. Idempotent.
async function cleanupTerminal() {
  await agent(
    cleanupTerminalPrompt({ waveId: WAVE_ID, targetRepo: TARGET_REPO, targetRepoDir: TARGET_REPO_DIR }),
    { label: 'cleanup:terminal', phase: 'Promote', schema: CLEANUP_RESULT, agentType: 'general-purpose' },
  ).catch((e) => { log(`[#686] cleanupTerminal soft-fail: ${e?.message || e}`); return null })
  log(`[#686] swept remaining wave-${WAVE_ID} worktrees+branches`)
}

// ─────────────────────────────────────────────────────────────────────────────
// REAL agent() PROMPTS (the judgment nodes — these are not seams).
// The sdlc-server tool calls inside them are seams; the prompt shape is real.
// ─────────────────────────────────────────────────────────────────────────────

// Prime(plan): sees CURRENT state (merged/pending/lastRework) and partitions the pending
// issues into the next conflict-free parallel group via flight_overlap/flight_partition.
//
// #705 (re-home of finding #7): the planner does NOT reason about declared `## Dependencies`.
// The wave was already dependency-ordered upstream by wave_compute (prepwaves) — issues WITHIN
// one computed wave are mutually independent by construction, and any external dep is already
// merged in an earlier wave / the base branch. So declared deps are irrelevant at this grain.
// The ONLY ordering that matters here is (a) file conflicts (flight_partition) and (b) a
// dependency that SURFACES at runtime (reconcile reports it in `lastRework`); the dynamic
// re-plan loop is the safety net for any latent intra-wave ordering. Re-deriving dep
// satisfaction from spec_dependencies in prose is what caused the #701 false-impasse — removed.
function primePlanPrompt(merged, pending, lastRework) {
  return [
    `You are the wave PRIME planner for wave ${WAVE_ID} of ${TARGET_REPO}. Pick the NEXT flight-group`,
    `(a set of issues to build IN PARALLEL) from the pending set. This wave was ALREADY dependency-ordered`,
    `upstream (wave_compute / prepwaves), so its issues are independent by construction — you do NOT need to`,
    `read or reason about any issue's declared "## Dependencies"; treat them as already satisfied. Your only`,
    `job is conflict-free parallel batching + scheduling surfaced rework.`,
    `  merged so far: [${[...merged].join(', ') || 'none'}]`,
    `  pending:       [${[...pending].join(', ') || 'none'}]`,
    `  just re-opened by reconcile (surfaced rework — schedule FIRST): ${JSON.stringify(lastRework)}`,
    ``,
    `1. Fetch each pending issue's FILE MANIFEST (sdlc-server spec_get / work_item — files it creates/modifies).`,
    `2. Run flight_overlap + flight_partition over those manifests to pick a maximal NON-CONFLICTING parallel`,
    `   group (issues that do not touch the same source files). Do not guess a partition you can compute.`,
    `3. Any issue in "just re-opened" is a surfaced dependency reconcile reset — put it in THIS group so it`,
    `   re-runs against the now-merged provider.`,
    `Note: a runtime dependency you cannot see here will surface at integration — reconcile detects the break`,
    `and re-opens the consumer (the §3.1 dynamic re-plan loop). You do NOT pre-empt that with declared-dep`,
    `reasoning; you just keep partitioning the pending set.`,
    ``,
    `Return: done (true ONLY if you genuinely cannot form ANY group from a non-empty pending set — a real`,
    `IMPASSE, which should essentially never happen since the wave is pre-ordered; it is NOT a success state),`,
    `group (issue numbers for the next parallel flight-group), rationale (1-2 sentences).`,
  ].join('\n')
}

// Worker: per-issue, worktree-isolated. SPEC EXECUTOR. Idempotent on resume.
// Carries the §3.2 must-preserve fields (concerns/deferrals) as STRUCTURED RETURN.
function workerPrompt(n, worktree) {
  const branch = issueBranch(n)
  return [
    `You are a FLIGHT worker for issue #${n} of ${TARGET_REPO}, wave ${WAVE_ID}.`,
    `Working directory: ${worktree} (handed to you — do NOT create your own worktree). Branch: ${branch}`,
    `(already checked out, based on origin/${KAHUNA_BRANCH}). Your PR targets ${KAHUNA_BRANCH}, NEVER ${PROTECTED_BRANCH}.`,
    ``,
    `IDEMPOTENT RESUME (§3.3): FIRST check if your branch already contains this implementation (e.g. the spec's`,
    `target files exist + the acceptance test passes). If so, return status="already-present" and do NOT redo work.`,
    ``,
    `Otherwise — SPEC EXECUTOR rules:`,
    `1. Fetch the spec + acceptance criteria via the REAL sdlc-server tools for #${n}: spec_get,`,
    `   spec_acceptance_criteria, work_item (the issue body + AC are the executable contract).`,
    `2. Implement EXACTLY what the issue specifies. Where the story has a canonical acceptance test, run it as an`,
    `   ORACLE (self-authored tests are necessary but not sufficient — §9 verification ladder).`,
    `3. Run the project gate in your worktree (./scripts/ci/validate.sh + the test suite). The pre-push test gate`,
    `   + secret gate are deterministic HOOKS — they fire regardless; do not bypass.`,
    `4. Commit in your worktree (do NOT push — Prime(reconcile) handles merge): use a wave-pattern commit message.`,
    `   You MAY make intra-flight fixes freely inside your worktree without asking (§3.2.3).`,
    ``,
    `§3.2 must-preserve — return these as DATA (the script records, it does NOT halt on them):`,
    `  concerns:  things that feel off but are not blockers — "surface a concern and keep going" is the DEFAULT.`,
    `  deferrals: fixes you DECIDE to defer — {issue, reason, risk}. You decide; the script records and proceeds.`,
    ``,
    `Return: issue (${n}), status ("implemented"|"blocked"|"already-present"), branch, worktree, files_changed,`,
    `concerns (array), deferrals (array), notes (1-2 sentences).`,
  ].join('\n')
}

// Prime(reconcile): the ONLY cross-flight view. Merges to kahuna, resolves
// conflicts + interface breaks (cross-flight fixes, §3.2.3), reports surfaced deps
// as needs_rework. commutativity_verify is the detector. Folds in persistence (§3.3).
function primeReconcilePrompt(built, merged) {
  const list = built.map((w) => `   - issue #${w.issue}: branch ${w.branch} in ${w.worktree} (status ${w.status})`).join('\n')
  return [
    `You are the wave PRIME reconcile node for wave ${WAVE_ID} of ${TARGET_REPO} — the ONLY node with the`,
    `cross-flight view. Integrate this group's flights into ${KAHUNA_BRANCH} and detect interface breaks.`,
    `Already merged: [${[...merged].join(', ') || 'none'}]. This group's built flights:`,
    list || '   (none built)',
    ``,
    `1. Merge each flight's branch into ${KAHUNA_BRANCH} in dependency order (providers before consumers).`,
    `   IDEMPOTENT (§3.3): if a branch is already in ${KAHUNA_BRANCH}, SKIP it (do not double-merge).`,
    `2. Resolve conflicts coherently — combine, do not drop. A shared interface two issues touch is a CROSS-FLIGHT`,
    `   fix you make HERE (you have the multi-branch view); record it in conflicts_resolved (§3.2.3).`,
    `3. Run the REAL sdlc-server tools: commutativity_verify (PAIRWISE mode across this group's branches —`,
    `   base_ref=${KAHUNA_BRANCH} — to decide whether a merge train is needed) BEFORE merging, then`,
    `   pr_create + pr_merge to land each flight branch into ${KAHUNA_BRANCH}, plus the FULL suite.`,
    `4. If a flight's code BREAKS another's interface (signature mismatch surfaced at integration): UNDO just that`,
    `   flight's merge (keep integration green) and report it in needs_rework with the precise reason — the loop`,
    `   re-opens it as a surfaced dependency and re-schedules it next group (§3.1 dynamic re-plan).`,
    `   // #688 wave-status persistence is FILLED as a standalone step the LOOP runs right after you return`,
    `   //   (persistIteration → wave_record_mr + wave_close_issue per newly-merged issue, then the durable`,
    `   //   loop blob). Do NOT record MRs / close issues here — just return merged; the loop persists it (§3.3).`,
    `5. FAIL LOUD on a REJECTED push (#724): if pushing a flight branch or ${KAHUNA_BRANCH} to origin is rejected —`,
    `   pre-push test gate, permissions, or a protected-ref guard — STOP and return blocked=true + block_reason`,
    `   (the rejection text). Do NOT substitute LOCAL merge commits / local-only branches to "keep going": that`,
    `   strands the wave off origin and produces a degenerate ${KAHUNA_BRANCH}→release MR that can never promote.`,
    `   A blocked push HOLDs the wave with a clear cause — the loop never promotes work that never reached origin.`,
    ``,
    `Return: merged (issues now green in ${KAHUNA_BRANCH} this round), needs_rework (list of {issue, reason} you`,
    `reset), conflicts_resolved (files + 1-line how), concerns (array), suite_summary (final test line),`,
    `blocked (true ONLY if a push to origin was rejected — see step 5) + block_reason, notes.`,
  ].join('\n')
}

// ─────────────────────────────────────────────────────────────────────────────
// PHASE 1 — REHYDRATE (§3.3): seed loop state from durable wave-status.
// ─────────────────────────────────────────────────────────────────────────────
phase('Rehydrate')
const seed = await rehydrate() // SEAM #686

// ─────────────────────────────────────────────────────────────────────────────
// PHASE 2 — THE DYNAMIC FLIGHT LOOP (§3.1) — REAL, complete. The validated part.
// ─────────────────────────────────────────────────────────────────────────────
phase('Flight loop')

// state (script-held, free); mirrored durably to wave-status each iteration (§3.3)
const pending = new Set(seed.pending)
const merged = new Set(seed.merged)
const reworkCount = Object.fromEntries(Object.entries(seed.reworkCount || {}).map(([k, v]) => [Number(k), v])) // numeric keys (JSON resume returns them as strings)
let lastRework = []
let idleRounds = seed.idleRounds || 0
const groupsRun = [] // running record; length seeds from seed.groupsRun for the bound
let groupsRunBase = Math.max(0, Number(seed.groupsRun) || 0) // rehydration-proof: corrupt/missing/negative seed → 0, so the runaway guard always fires
let halt = null // null = still converging; else a HOLD reason (NEVER a success)

// Collected §3.2 must-preserve data — recorded, never branched-on.
const allConcerns = []
const allDeferrals = []

while (true) {
  // ── CLOSED LEGAL EXITS (the whole safety story) ──
  if (pending.size === 0) break // success (halt stays null)
  if (groupsRunBase + groupsRun.length >= MAX_GROUPS) { halt = 'runaway'; break } // → human review
  if (idleRounds >= MAX_IDLE) { halt = 'thrash'; break } // groups with zero net merges → not converging
  if (budget.total && budgetRemaining() < COST_FLOOR) { halt = 'cost'; break } // stop before the ceiling

  // ── PLAN next group from CURRENT state (Prime; judgment) ──
  const plan = await teeAgent(primePlanPrompt(merged, pending, lastRework), {
    label: `plan:${groupsRunBase + groupsRun.length + 1}`,
    phase: 'Flight loop',
    schema: NEXTGROUP,
    agentType: 'general-purpose',
  })
  if (plan.done || !plan.group || plan.group.length === 0) { halt = 'impasse'; break } // planner can't schedule remaining → human

  const planned = plan.group.filter((n) => pending.has(n)) // defensive: only schedule still-pending issues
  if (planned.length === 0) { halt = 'impasse'; break }
  // #824 R-06: apply the wave's dispatch as a CEILING on this group. 'fan' keeps the planner's
  // conflict-free parallel batch (the #705 file-conflict floor already applied); serialize/
  // serialize-preferred/absent force ONE issue (single-file) — the rest stay pending and schedule
  // next iteration. Never widens the group: only ever equal-or-more-serial than the planner (CT-01).
  const group = applyDispatchCeiling(planned, DISPATCH)
  log(`Group ${groupsRunBase + groupsRun.length + 1}: building [${group.join(', ')}] (dispatch: ${DISPATCH}; planned: [${planned.join(', ')}]; merged: [${[...merged].join(', ') || 'none'}])`)

  // ── SETUP: await a single worktree-creation step BEFORE parallel() (race-safe, §4.2) ──
  const wtMap = await setupWorktrees(group) // SEAM #686 (idempotent)

  // ── RUN group issues in PARALLEL (isolated workers; intra-flight fixes inside) ──
  const built = (await parallel(group.map((n) => () =>
    agent(workerPrompt(n, wtMap[n]), {
      label: `flight:#${n}`,
      phase: 'Flight loop',
      schema: WORK,
      agentType: 'general-purpose',
      // Cross-repo wave (§4.2): the pre-created target-repo worktree IS the isolation —
      // do NOT pass isolation:'worktree' (that worktrees the PLAN repo, wrong codebase).
      // Same-repo waves would set isolation:'worktree' here instead.
    }))))
    .filter(Boolean)

  // Collect §3.2 must-preserve data from workers (record; do not branch).
  for (const w of built) {
    for (const c of w.concerns || []) allConcerns.push({ issue: w.issue, concern: c })
    for (const d of w.deferrals || []) allDeferrals.push(d)
  }
  const implemented = built.filter((w) => w.status === 'implemented' || w.status === 'already-present')

  // ── MERGE + RECONCILE (Prime(post-flight) — the ONLY cross-flight view) ──
  const rec = await teeAgent(primeReconcilePrompt(implemented, merged), {
    label: `merge:${groupsRunBase + groupsRun.length + 1}`,
    phase: 'Flight loop',
    schema: RECONCILE,
    agentType: 'general-purpose',
  })
  for (const c of rec.concerns || []) allConcerns.push({ issue: 'reconcile', concern: c })

  // #724: a push rejected by the pre-push gate / permissions / protected-ref guard HOLDs the wave
  // LOUDLY. Reconcile is instructed never to substitute local merge commits (which strand work off
  // origin + emit a degenerate kahuna→release MR), so a blocked reconcile means nothing landed this
  // round. Set halt + break → the gate is skipped and the campaign driver surfaces the block reason.
  if (rec.blocked) { halt = `reconcile-blocked: ${rec.block_reason || 'push to origin rejected'}`; break }

  // ── DETERMINISTIC state update + progress accounting ──
  const newlyMerged = (rec.merged || []).filter((n) => !merged.has(n))
  newlyMerged.forEach((n) => { merged.add(n); pending.delete(n) })
  idleRounds = newlyMerged.length ? 0 : idleRounds + 1 // thrash detector
  await cleanupMerged(newlyMerged) // SEAM #686 — per-merge worktree+branch removal (§4.3)

  lastRework = []
  for (const r of rec.needs_rework || []) {
    const ri = Number(r.issue) // normalize: pending/merged/reworkCount are numeric-keyed (string keys leak in via JSON resume)
    if ((reworkCount[ri] = (reworkCount[ri] || 0) + 1) > MAX_REWORK) {
      halt = `rework:#${ri}` // per-issue breaker → HOLD, NOT success
      break
    }
    pending.add(ri) // surfaced dep → re-opened → next group
    merged.delete(ri)
    lastRework.push(r)
    log(`Surfaced dependency: #${ri} re-opened (rework #${reworkCount[ri]}) — ${r.reason}`)
  }

  groupsRun.push({ group, merged: newlyMerged, needs_rework: rec.needs_rework || [], suite: rec.suite_summary })
  // SEAM #688 — newlyMerged are the issues that need their MR recorded + issue closed THIS
  // iteration; merged/pending/etc. are the full loop blob (the rehydrate substrate, §3.3).
  await persistIteration({ merged, pending, reworkCount, idleRounds, groupsRun: groupsRunBase + groupsRun.length, newlyMerged: newlyMerged.filter((n) => merged.has(n)) }) // defensive: drop any newlyMerged that the rework loop re-opened
  if (halt) break // breaker tripped inside the for-loop → leave the while with pending still non-empty
}

const loopOutcome = halt || (pending.size === 0 ? 'success' : 'incomplete')
log(`Flight loop done: ${loopOutcome} in ${groupsRun.length} groups (concerns: ${allConcerns.length}, deferrals: ${allDeferrals.length})`)

// ─────────────────────────────────────────────────────────────────────────────
// PHASE 3 — TRUST GATE (§3.4) — REAL fan-out. Runs ONLY on the success exit.
// Any HOLD reason (incl. per-issue breaker) skips the gate.
// ─────────────────────────────────────────────────────────────────────────────
phase('Trust gate')
let gate
let promotionPrNumber = null // #5: the draft promotion PR the gate opens; the promote step merges THIS one (never a 2nd)
if (!halt && pending.size === 0) {
  // #5 (live-gate finding, BLOCKING) — OPEN THE PROMOTION PR (DRAFT) FIRST, before the signals.
  // The CI signal waits on the kahuna→protected MERGE-RESULT pipeline (#452); that pipeline only
  // exists once the PR exists. The old order created the PR at promotion (AFTER the gate), so
  // ci_wait_run found `no_merge_result_pr` and the signal had nothing to verify. Opening a DRAFT
  // PR here gives the CI signal a real pipeline AND prevents a green CI from auto-merging before
  // the gate has weighed all four signals. If the PR can't be opened (kahuna branch/artifacts
  // missing), the gate HOLDs — we cannot prove a wave we cannot even PR (conservative, §3.4).
  const prOpen = await teeAgent(
    openPromotionPrPrompt({ waveId: WAVE_ID, kahunaBranch: KAHUNA_BRANCH, protectedBranch: PROTECTED_BRANCH, targetRepo: TARGET_REPO, targetRepoDir: TARGET_REPO_DIR, planId: PLAN_ID }),
    { label: 'gate:open-pr', phase: 'Trust gate', schema: OPEN_PR_RESULT, agentType: 'general-purpose' },
  ).catch((e) => {
    log(`[#5] open promotion PR soft-fail → gate HOLDs (no PR to verify): ${e?.message || e}`)
    return { opened: false, notes: `open-pr error: ${e?.message || e}` }
  })
  promotionPrNumber = prOpen?.opened ? (prOpen.pr_number ?? null) : null
  // HOLD if there is no usable PR. Two ways that happens: (a) the PR didn't open at all, or (b) it
  // reported opened:true but WITHOUT a pr_number. Case (b) matters: `pr_number` is optional in
  // OPEN_PR_RESULT, so a schema-valid `{opened:true}` with no number would leave promotionPrNumber
  // null — the CI signal would then fall back to SEARCH-for-the-PR (re-introducing the very
  // no_merge_result_pr race #5 closed) and the no-2nd-PR guarantee would degrade to agent behavior.
  // Requiring a concrete number here keeps both structural (#699 independent review).
  if (!prOpen || !prOpen.opened || promotionPrNumber == null) {
    const detail = !prOpen || !prOpen.opened
      ? `could not open ${KAHUNA_BRANCH}→${PROTECTED_BRANCH} draft PR: ${prOpen?.notes || 'unknown'}`
      : `PR-open returned opened:true but no pr_number — cannot identify the merge-result pipeline to verify`
    gate = { verdict: 'HOLD', failing: [{ signal: 'open-pr', passed: false, detail }], signals: [] }
  } else {
    log(`[#5] promotion draft PR open — #${promotionPrNumber} (${prOpen.pr_ref || 'ref n/a'}); CI signal will wait on its merge-result pipeline`)

    // The 4 canonical signals run in PARALLEL (independent), aggregate to a verdict. The agent()
    // prompts (gate.js) name the REAL sdlc-server tools; each signal's `.catch` now returns
    // conservativeFail() (passed:false → HOLD), NOT an always-pass stub — an agent/tool error is
    // the absence of evidence, and a trust gate HOLDs on absence of evidence (SEAMS invariant 6).
    const signals = (await parallel([
      // 1. commutativity — kahuna composed-diff safety vs the protected branch (single-target mode)
      () => agent(
        commutativitySignalPrompt({ waveId: WAVE_ID, kahunaBranch: KAHUNA_BRANCH, protectedBranch: PROTECTED_BRANCH, targetRepoDir: TARGET_REPO_DIR }),
        { label: 'gate:commutativity', phase: 'Trust gate', schema: SIG, agentType: 'general-purpose' },
      ).catch((e) => conservativeFail('commutativity', e)),
      // 2. CI on the MR MERGE-RESULT pipeline of the draft PR opened above — NOT the merge-commit branch HEAD (sdlc #452, #5)
      () => agent(
        ciSignalPrompt({ waveId: WAVE_ID, kahunaBranch: KAHUNA_BRANCH, protectedBranch: PROTECTED_BRANCH, targetRepo: TARGET_REPO, prNumber: promotionPrNumber }),
        { label: 'gate:ci', phase: 'Trust gate', schema: SIG, agentType: 'general-purpose' },
      ).catch((e) => conservativeFail('ci', e)),
      // 3. review the kahuna-vs-protected diff via a 2-STEP stage→review sub-pipeline (#847/ENG-5):
      //    a Bash-capable general-purpose STAGE agent fetches + diffs origin/<protected>...origin/<kahuna>
      //    and materializes the changed-file set into a durable workspace; then the SPECIALIZED
      //    feature-dev:code-reviewer reviews that workspace. code-reviewer is PRESERVED (NOT swapped to
      //    general-purpose — the EC-1 shortcut): it has no Bash to fetch the diff, so the stage step feeds
      //    it. The diff is ALWAYS origin/<protected>...origin/<kahuna>, never a hard-coded `main` (the
      //    empty-tree provisioning bug: an origin/main worktree reviews nothing on release-branch repos).
      () => (async () => {
        const staged = await agent(
          reviewStagePrompt({ waveId: WAVE_ID, kahunaBranch: KAHUNA_BRANCH, protectedBranch: PROTECTED_BRANCH, targetRepo: TARGET_REPO, targetRepoDir: TARGET_REPO_DIR }),
          { label: 'gate:review:stage', phase: 'Trust gate', schema: REVIEW_STAGE, agentType: 'general-purpose' },
        )
        // Conservative-fail on a failed/empty stage (fetch error or zero changed files): the reviewer has
        // nothing sound to read, so the signal HOLDs — it never PASSes on an unmaterialized diff (ENG-5).
        if (!staged || !staged.staged || !(Array.isArray(staged.changedFiles) && staged.changedFiles.length)) {
          return conservativeFail('review', `stage step produced no diff to review: ${staged?.notes || 'staged=false'}`)
        }
        return agent(
          reviewSignalPrompt({ waveId: WAVE_ID, kahunaBranch: KAHUNA_BRANCH, protectedBranch: PROTECTED_BRANCH, targetRepoDir: TARGET_REPO_DIR, workspaceDir: staged.workspaceDir, changedFiles: staged.changedFiles }),
          { label: 'gate:review', phase: 'Trust gate', schema: SIG, agentType: 'feature-dev:code-reviewer' },
        )
      })().catch((e) => conservativeFail('review', e)),
      // 4. trivy HIGH/CRITICAL dependency scan of kahuna
      () => agent(
        trivySignalPrompt({ waveId: WAVE_ID, kahunaBranch: KAHUNA_BRANCH, targetRepoDir: TARGET_REPO_DIR }),
        { label: 'gate:trivy', phase: 'Trust gate', schema: SIG, agentType: 'general-purpose' },
      ).catch((e) => conservativeFail('trivy', e)),
      // A null/undefined slot (an SDK-level failure upstream of the per-signal .catch) must become a
      // conservative-fail, NEVER be dropped — the gate must always weigh exactly 4 signals, or a
      // missing signal silently becomes a PASS (absence-of-evidence-as-safety). #687 review.
    ])).map((s, i) => s ?? conservativeFail(['commutativity', 'ci', 'review', 'trivy'][i], 'signal slot returned null/undefined'))

    const failed = signals.filter((s) => !s.passed)
    gate = failed.length === 0
      ? { verdict: 'PASS', promote: `${KAHUNA_BRANCH}→${PROTECTED_BRANCH}`, prNumber: promotionPrNumber, signals }
      : { verdict: 'HOLD', failing: failed, signals }
  }
} else {
  gate = { verdict: 'SKIPPED', reason: halt || 'loop did not reach clean success' }
}

// ─────────────────────────────────────────────────────────────────────────────
// PHASE 4 — PROMOTE or HOLD-FOR-REVIEW.
//   AUTO: promote kahuna→protected on PASS.
//   INTERACTIVE: the workflow ENDS returning the verdict (the return IS the human gate, §5).
// ─────────────────────────────────────────────────────────────────────────────
phase('Promote')
let result
if (gate.verdict === 'PASS') {
  if (MODE === 'auto') {
    // #687/#5 promotion (CODE, runs ONLY here — a live wave's auto+PASS success exit, itself gated
    // by the human cutover #691). The kahuna→protected DRAFT PR (#${promotionPrNumber}) was already
    // opened by the gate's PR-OPEN node and its merge-result CI already validated — so promotion
    // marks THAT SAME PR ready and pr_merge(skip_train:true) lands it (commutativity already proved
    // skip_train safe); the kahuna branch is deleted. It never opens a second PR. The script can't
    // call MCP/CLI directly (§3.3) — the promote agent does it.
    const promo = await teeAgent(
      promotePrompt({ waveId: WAVE_ID, kahunaBranch: KAHUNA_BRANCH, protectedBranch: PROTECTED_BRANCH, targetRepo: TARGET_REPO, prNumber: promotionPrNumber, preserveKahuna: PRESERVE_KAHUNA }),
      { label: 'promote', phase: 'Promote', schema: PROMOTE_RESULT, agentType: 'general-purpose' },
    ).catch((e) => {
      // A promotion error must NOT be reported as a successful promote (conservative): record HELD,
      // surface the error, and let the campaign driver / human route it (§5). The gate PASSed, so the
      // kahuna branch is sound — promotion can be retried on resume; we never claim a merge that failed.
      log(`[#687] promote soft-fail — wave HELD for manual promotion: ${e?.message || e}`)
      return { promoted: false, notes: `promote error: ${e?.message || e}` }
    })
    const promoted = !!(promo && promo.promoted)
    await persistTerminal(promoted ? 'promoted' : 'held',
      promoted
        ? `gate PASS, promoted ${KAHUNA_BRANCH}→${PROTECTED_BRANCH}${promo.mr_ref ? ` (${promo.mr_ref})` : ''}`
        : `gate PASS, promotion did not land — ${promo?.notes || 'see promote node'}; HELD for manual promotion`) // SEAM #688
    result = promoted
      ? { gate: 'PASS', promoted: true, wave: WAVE_ID, mr_ref: promo.mr_ref }
      : { gate: 'PASS', promoted: false, wave: WAVE_ID, reason: `promotion did not land: ${promo?.notes || 'see promote node'}` }
  } else {
    // INTERACTIVE: do NOT promote — return the verdict; the campaign driver surfaces it + the human routes.
    await persistTerminal('held', 'gate PASS, interactive — awaiting human promotion') // SEAM #688
    result = { gate: 'PASS', promoted: false, wave: WAVE_ID, reason: 'interactive: human routes promotion' }
  }
} else if (gate.verdict === 'HOLD') {
  await persistTerminal('held', `gate HOLD: ${(gate.failing || []).map((s) => s.signal).join(', ')}`) // SEAM #688
  result = { gate: 'HOLD', wave: WAVE_ID, failing: gate.failing }
} else {
  await persistTerminal('held', `gate SKIPPED: ${gate.reason}`) // SEAM #688
  result = { gate: 'SKIPPED', wave: WAVE_ID, reason: gate.reason, haltReason: halt }
}

// Wave-terminal cleanup (§4.3): remove remaining worktrees + prune (both ends, not end-only).
await cleanupTerminal() // SEAM #686

// The return IS the per-wave gate the campaign driver (§5) consumes and routes on.
return {
  wave: WAVE_ID,
  kahunaBranch: KAHUNA_BRANCH,
  targetRepo: TARGET_REPO,
  loopOutcome,
  groups: groupsRunBase + groupsRun.length,
  groupsRun,
  merged: [...merged],
  pending: [...pending],
  reworkCount,
  concerns: allConcerns, // §3.2 surfaced-and-continued — informational
  deferrals: allDeferrals, // §3.2 decided-and-recorded — informational
  gate: result.gate,
  ...result,
}
