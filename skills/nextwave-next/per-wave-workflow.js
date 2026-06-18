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
// WHAT IS A SEAM (stubbed, filled by a wave-2 foundational issue):
//   - rehydrate / idempotency               → TODO(#686 resumability/rehydrate)
//   - real gate signals via sdlc-server      → TODO(#687 gate wiring)
//   - wave-status persistence (durable state) → TODO(#688 wave-status persistence)
//   See SEAMS.md (this dir) for the exact function/return signatures each seam expects.
//
// The agent() prompts below are REAL (worker / Prime-plan / Prime-reconcile /
// signal). The sdlc-server MCP TOOL CALLS those agents make are the seam — the
// stubs return obvious placeholders so the loop runs end-to-end in skeleton form.

// #688 wave-status persistence seam helper: durable blob shape/path + the persist
// agent prompts (the MCP record/close calls + the .claude/status/ blob write). See
// wave-status.js + SEAMS.md (#688). The loop calls persistIteration/persistTerminal below.
import { blobPath, toBlob, persistIterationPrompt, persistTerminalPrompt } from './wave-status.js'

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
// The campaign driver (skills/wavemachine-next) supplies it from the approved
// phase/wave plan. Defaults make the script self-describing when run bare.
// ─────────────────────────────────────────────────────────────────────────────
const params = (typeof input !== 'undefined' && input) || {}
const WAVE_ID = params.waveId ?? 'W-?'
const TARGET_REPO = params.targetRepo ?? 'Wave-Engineering/ccwork-testtarget' // owner/repo for gh -R scoping
const TARGET_REPO_DIR = params.targetRepoDir ?? '/home/bakerb/sandbox/github/ccwork-testtarget' // clone the worktrees attach to
const KAHUNA_BRANCH = params.kahunaBranch ?? `kahuna/${WAVE_ID}` // integration target; never the protected branch
const PROTECTED_BRANCH = params.protectedBranch ?? 'main' // promotion target on the success exit
const ALL_ISSUES = (params.issues ?? []).map(Number) // the wave's issue numbers
const MODE = params.mode ?? 'auto' // 'auto' (gate verdict drives promotion) | 'interactive' (verdict returned, human routes)
const budget = params.budget ?? { total: 0, remaining: () => Infinity } // optional cost guard
const budgetRemaining = typeof budget.remaining === 'function' ? budget.remaining : () => (budget.remaining ?? Infinity) // tolerate `remaining` passed as a number, not a fn

// Closed numeric guards (§3.1) — the whole safety story is these + the exit set.
const MAX_GROUPS = params.maxGroups ?? 24
const MAX_REWORK = params.maxRework ?? 3
const MAX_IDLE = params.maxIdle ?? 2
const COST_FLOOR = params.costFloor ?? 80_000

// Durable worktree root (§4.2) — NOT /tmp (reboot-wiped, resume-hostile). Gitignored, hyphenated stem shared by dir+branch.
const WT_ROOT = `${TARGET_REPO_DIR}/.claude/.worktrees/wave-${WAVE_ID}`
const wtPath = (n) => `${WT_ROOT}/issue-${n}`
const issueBranch = (n) => `wave-${WAVE_ID}/issue-${n}` // shares the wave-<id>/ stem so `git branch -D wave-<id>/*` cleans both

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
    notes: { type: 'string' },
  },
}
const SIG = {
  type: 'object',
  additionalProperties: false,
  required: ['signal', 'passed'],
  properties: { signal: { type: 'string' }, passed: { type: 'boolean' }, detail: { type: 'string' } },
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
    notes: { type: 'string' }, // includes any soft tool error (never halts the wave)
  },
}

// ─────────────────────────────────────────────────────────────────────────────
// SEAM STUBS — return obvious placeholders. The foundational wave-2 issues
// replace each body with the real sdlc-server-backed implementation. The exact
// function names + return shapes here ARE the interface contract (see SEAMS.md).
// ─────────────────────────────────────────────────────────────────────────────

// SEAM #686 — durable resume. The script can't call MCP/CLI directly (§3.3), so a
// cheap rehydrate agent reads wave-status and returns the loop blob. Stub: cold start.
async function rehydrate() {
  // TODO(#686 resumability/rehydrate): replace with an agent() that reads wave-status
  // (.claude/status/, durable) for this wave and returns {merged, pending, reworkCount,
  // idleRounds, groupsRun}. Must skip already-finished work on a cold restart.
  // Real shape:
  //   return agent(rehydratePrompt(WAVE_ID, ALL_ISSUES, TARGET_REPO),
  //     { label: 'rehydrate', phase: 'Rehydrate', schema: REHYDRATE, agentType: 'general-purpose' })
  log(`[SEAM #686] rehydrate stub → cold start (no prior wave-status state assumed)`)
  return { merged: [], pending: [...ALL_ISSUES], reworkCount: {}, idleRounds: 0, groupsRun: 0 }
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
  await agent(
    persistTerminalPrompt({ waveId: WAVE_ID, targetRepo: TARGET_REPO, disposition, detail, blob, path }),
    { label: `persist:terminal`, phase: 'Promote', schema: PERSIST_RESULT, agentType: 'general-purpose' },
  ).catch((e) => { log(`[#688] persistTerminal soft-fail: ${e?.message || e}`); return null })
  log(`[#688] persisted terminal — wave ${WAVE_ID} ${disposition}: ${detail} → ${path}`)
}

// SEAM #687 — real gate signals. Stub returns a passing placeholder so the gate
// fan-out runs end-to-end. The REAL signal is the agent() prompt shown inline in
// the trust gate below; this helper is only the stubbed return for skeleton runs.
function gateSignalStub(name) {
  // TODO(#687 gate wiring): delete this stub. The trust gate below shows the real
  // agent() calls (commutativity_verify / ci_wait_run on the MR merge-result
  // pipeline [sdlc #452] / code-reviewer on a kahuna worktree [#667] / trivy).
  return { signal: name, passed: true, detail: `[SEAM #687] ${name} stub — always-pass placeholder` }
}

// Worktree setup is awaited as a SINGLE step before parallel() — workers are HANDED
// a path, never asked to create one (race-safety is structural, §4.2). Idempotent:
// reuse an existing branch on resume, never -b (§4.2). Stubbed as a seam of #686 idempotency.
async function setupWorktrees(group) {
  // TODO(#686 resumability/rehydrate): real idempotent worktree creation —
  //   sweep prior wave-ids' dirs + `git worktree prune` (crash recovery, §4.3),
  //   then per issue: if branch exists `git worktree add <path> <branch>` (reuse),
  //   else `git worktree add <path> -b <branch> origin/<KAHUNA_BRANCH>`.
  // Returns a map issue→path the worker prompt is handed.
  const map = {}
  for (const n of group) map[n] = wtPath(n)
  log(`[SEAM #686] worktree setup stub — group [${group.join(', ')}] → ${WT_ROOT}/issue-<n>`)
  return map
}

// 3-point cleanup (§4.3): per-merge removal keeps peak disk ≈ current group.
// Prune branches too (shared wave-<id>/ stem → single glob cleans both).
async function cleanupMerged(issues) {
  // TODO(#686 resumability/rehydrate): real per-merge cleanup —
  //   git -C <repo> worktree remove --force <path>; git worktree prune; rm -rf <path>;
  //   git -C <repo> branch -D wave-<id>/issue-<n>
  if (issues.length) log(`[SEAM #686] cleanup stub — removed worktrees+branches for [${issues.join(', ')}]`)
}
async function cleanupTerminal() {
  // TODO(#686 resumability/rehydrate): wave-terminal sweep — remove remaining
  //   wave-<id> worktrees + `git worktree prune` + `git branch -D wave-<id>/*`.
  log(`[SEAM #686] terminal cleanup stub — swept remaining wave-${WAVE_ID} worktrees+branches`)
}

// ─────────────────────────────────────────────────────────────────────────────
// REAL agent() PROMPTS (the judgment nodes — these are not seams).
// The sdlc-server tool calls inside them are seams; the prompt shape is real.
// ─────────────────────────────────────────────────────────────────────────────

// Prime(plan): sees CURRENT state (merged/pending/lastRework). A dependency that
// surfaced mid-wave (in lastRework) becomes THIS group. Uses flight_partition/flight_overlap.
function primePlanPrompt(merged, pending, lastRework) {
  return [
    `You are the wave PRIME planner for wave ${WAVE_ID} of ${TARGET_REPO}. Plan the NEXT flight-group from`,
    `CURRENT state — independent issues run in parallel within a group; dependency-ordered across groups.`,
    `  merged so far: [${[...merged].join(', ') || 'none'}]`,
    `  pending:       [${[...pending].join(', ') || 'none'}]`,
    `  just re-opened (surfaced deps to schedule FIRST): ${JSON.stringify(lastRework)}`,
    ``,
    `For each pending issue fetch its spec (sdlc-server spec_get / work_item) and file manifest, then run`,
    `flight_overlap + flight_partition to pick a maximal NON-CONFLICTING parallel group. A surfaced dependency`,
    `from "just re-opened" goes in THIS group (re-run against the now-merged provider). When in doubt, sequence.`,
    `// TODO(#687 gate wiring): real spec_get / flight_partition / flight_overlap sdlc-server calls.`,
    ``,
    `Return: done (true ONLY if nothing schedulable remains — that is an IMPASSE, not success),`,
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
    `1. Fetch the spec + acceptance criteria (sdlc-server spec_get / spec_acceptance_criteria for #${n}).`,
    `   // TODO(#687 gate wiring): real spec_get / spec_acceptance_criteria + work_item sdlc-server calls.`,
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
    `3. Run commutativity_verify across the merged set + the FULL suite (the composition / commutativity check).`,
    `   // TODO(#687 gate wiring): real commutativity_verify + merge (pr_create/pr_merge) sdlc-server calls.`,
    `4. If a flight's code BREAKS another's interface (signature mismatch surfaced at integration): UNDO just that`,
    `   flight's merge (keep integration green) and report it in needs_rework with the precise reason — the loop`,
    `   re-opens it as a surfaced dependency and re-schedules it next group (§3.1 dynamic re-plan).`,
    `   // #688 wave-status persistence is FILLED as a standalone step the LOOP runs right after you return`,
    `   //   (persistIteration → wave_record_mr + wave_close_issue per newly-merged issue, then the durable`,
    `   //   loop blob). Do NOT record MRs / close issues here — just return merged; the loop persists it (§3.3).`,
    ``,
    `Return: merged (issues now green in ${KAHUNA_BRANCH} this round), needs_rework (list of {issue, reason} you`,
    `reset), conflicts_resolved (files + 1-line how), concerns (array), suite_summary (final test line), notes.`,
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
  const plan = await agent(primePlanPrompt(merged, pending, lastRework), {
    label: `plan:${groupsRunBase + groupsRun.length + 1}`,
    phase: 'Flight loop',
    schema: NEXTGROUP,
    agentType: 'general-purpose',
  })
  if (plan.done || !plan.group || plan.group.length === 0) { halt = 'impasse'; break } // planner can't schedule remaining → human

  const group = plan.group.filter((n) => pending.has(n)) // defensive: only schedule still-pending issues
  if (group.length === 0) { halt = 'impasse'; break }
  log(`Group ${groupsRunBase + groupsRun.length + 1}: building [${group.join(', ')}] (merged: [${[...merged].join(', ') || 'none'}])`)

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
  const rec = await agent(primeReconcilePrompt(implemented, merged), {
    label: `merge:${groupsRunBase + groupsRun.length + 1}`,
    phase: 'Flight loop',
    schema: RECONCILE,
    agentType: 'general-purpose',
  })
  for (const c of rec.concerns || []) allConcerns.push({ issue: 'reconcile', concern: c })

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
  await persistIteration({ merged, pending, reworkCount, idleRounds, groupsRun: groupsRunBase + groupsRun.length, newlyMerged })
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
if (!halt && pending.size === 0) {
  // The 4 canonical signals run in PARALLEL (independent), aggregate to a verdict.
  // The agent() prompts are REAL; the sdlc-server tool calls inside them are SEAM #687.
  const signals = (await parallel([
    // 1. commutativity across kahuna
    () => agent(
      [
        `Trust-gate COMMUTATIVITY signal for wave ${WAVE_ID}. Run commutativity_verify across ${KAHUNA_BRANCH}`,
        `(base ${PROTECTED_BRANCH}). pass = verdict ∈ {STRONG, MEDIUM}; fail otherwise (incl. PROBE_UNAVAILABLE`,
        `= conservative-fail). // TODO(#687 gate wiring): real commutativity_verify sdlc-server call.`,
        `Return signal="commutativity", passed (bool), detail.`,
      ].join('\n'),
      { label: 'gate:commutativity', phase: 'Trust gate', schema: SIG, agentType: 'general-purpose' },
      // TODO(#687): each gate signal's .catch falls back to an always-PASS stub (skeleton only). When the
      // real signals land, drop these fallbacks so an agent error HOLDs (conservative-fail), never PASSes.
    ).catch(() => gateSignalStub('commutativity')),
    // 2. CI on the MR merge-result pipeline — NOT the merge-commit branch HEAD (sdlc #452)
    () => agent(
      [
        `Trust-gate CI signal for wave ${WAVE_ID}. ci_wait_run for the ${KAHUNA_BRANCH}→${PROTECTED_BRANCH} MR`,
        `MERGE-RESULT pipeline (NOT the merge-commit branch HEAD; skipped-branch + passing-merge-result =`,
        `validated) [sdlc #452]. Lint/typecheck ride INSIDE this signal, diff-scoped to the wave's changed files`,
        `(never tree-scoped — §3.4). // TODO(#687 gate wiring): real ci_wait_run sdlc-server call.`,
        `Return signal="ci", passed (final_status==success), detail.`,
      ].join('\n'),
      { label: 'gate:ci', phase: 'Trust gate', schema: SIG, agentType: 'general-purpose' },
    ).catch(() => gateSignalStub('ci')),
    // 3. review the full kahuna-vs-main diff — worktree of kahuna, native checkout (#667)
    () => agent(
      [
        `Trust-gate REVIEW signal for wave ${WAVE_ID}. Review the full ${KAHUNA_BRANCH}-vs-${PROTECTED_BRANCH}`,
        `diff for correctness / architecture / unstated intent (the rung a test cannot encode — §9 ladder).`,
        `Scope to the wave's CHANGED FILES only (§3.4). pass = no critical/important findings.`,
        `Return signal="review", passed (bool), detail.`,
      ].join('\n'),
      {
        label: 'gate:review',
        phase: 'Trust gate',
        schema: SIG,
        agentType: 'feature-dev:code-reviewer',
        isolation: 'worktree', // worktree of kahuna so the reviewer sees the branch natively (#667)
      },
    ).catch(() => gateSignalStub('review')),
    // 4. trivy HIGH/CRITICAL dependency scan of kahuna
    () => agent(
      [
        `Trust-gate TRIVY signal for wave ${WAVE_ID}. Run trivy fs --scanners vuln --severity HIGH,CRITICAL on`,
        `${KAHUNA_BRANCH}. pass = no HIGH/CRITICAL findings with available fixes.`,
        `// TODO(#687 gate wiring): the trivy scan rides the deterministic pre-push/secret hooks + this signal.`,
        `Return signal="trivy", passed (bool), detail.`,
      ].join('\n'),
      { label: 'gate:trivy', phase: 'Trust gate', schema: SIG, agentType: 'general-purpose' },
    ).catch(() => gateSignalStub('trivy')),
  ])).filter(Boolean)

  const failed = signals.filter((s) => !s.passed)
  gate = failed.length === 0
    ? { verdict: 'PASS', promote: `${KAHUNA_BRANCH}→${PROTECTED_BRANCH}`, signals }
    : { verdict: 'HOLD', failing: failed, signals }
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
    // TODO(#687 gate wiring): real promotion — wave_finalize opens the kahuna→protected MR,
    //   pr_merge(skip_train:true) on all-green, delete the kahuna branch, record disposition.
    log(`[SEAM #687] promote stub — would auto-merge ${KAHUNA_BRANCH}→${PROTECTED_BRANCH}`)
    await persistTerminal('promoted', `gate PASS, ${KAHUNA_BRANCH}→${PROTECTED_BRANCH}`) // SEAM #688
    result = { gate: 'PASS', promoted: true, wave: WAVE_ID }
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
