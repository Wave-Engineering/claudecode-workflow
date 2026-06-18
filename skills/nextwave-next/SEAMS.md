# SEAMS — interface contract for `per-wave-workflow.js`

This is the **anchor's interface contract**. `per-wave-workflow.js` (#689) ships the
real, validated spine — the closed-legal-exit flight loop, the dynamic re-plan, and the
trust-gate fan-out. The pieces that touch the real sdlc-server MCP, the durable
wave-status store, and the durable worktrees are **seams**: each is a named function (or
inline `agent()` prompt) with a fixed return shape and an obvious-placeholder stub, so
the skeleton runs end-to-end today and the foundational wave-2 issues fill each seam
**without changing the loop**.

Every seam is marked in the script with a `// TODO(#…)` comment matching the table below.
Filling a seam means: replace the stub body with the real sdlc-server-backed
implementation, keep the **signature and return shape** identical. The loop/exits/re-plan
depend only on the return shapes here — not on how they are produced.

---

## Seam → issue map

| Seam | Issue | What it provides |
|---|---|---|
| rehydrate / idempotency | **#686** | durable resume: seed loop state from wave-status; idempotent worktree setup + 3-point cleanup |
| real gate signals | **#687** | the four trust signals via sdlc-server, the plan/worker/reconcile MCP tool calls, and promotion |
| wave-status persistence | **#688** | the durable resume substrate: per-iteration loop blob + per-issue MR/close + terminal disposition |

---

## #686 — resumability / rehydrate / idempotency

The script cannot call MCP/CLI directly (§3.3), so a cheap rehydrate **agent** reads
wave-status and returns the loop blob; worktree setup/cleanup are idempotent file ops.

### `rehydrate() → REHYDRATE`

```js
// REHYDRATE schema (in per-wave-workflow.js):
{
  merged:      number[],                       // issues already on kahuna (skip them)
  pending:     number[],                       // issues still to do
  reworkCount: { [issueNum: string]: number }, // optional; per-issue rework tally
  idleRounds:  number,                         // optional; thrash counter to restore
  groupsRun:   number,                         // optional; group count to seed the MAX_GROUPS bound
}
```

- **Cold start (no prior state):** `{ merged: [], pending: [...ALL_ISSUES] }` — the stub's behavior.
- **Real impl:** an `agent()` that reads `.claude/status/` (durable, NOT `/tmp`) for this
  `WAVE_ID` and returns the persisted loop blob. The loop seeds `pending`/`merged`/
  `reworkCount`/`idleRounds` and the `groupsRunBase` bound from it. **Idempotency is the
  crux** (§3.3): on resume the loop must skip finished work — which it does as long as
  `rehydrate()` reports the already-merged set accurately.

### `setupWorktrees(group: number[]) → { [issueNum]: worktreePath }`

- Awaited as a **single step before `parallel()`** — workers are *handed* a path, never
  asked to create one (race-safety is structural, §4.2).
- **Idempotent:** reuse an existing branch on resume (`git worktree add <path> <branch>`),
  **never `-b`** (which fails if the branch exists). First, sweep prior wave-ids' worktree
  dirs + `git worktree prune` (crash recovery, §4.3).
- Returns the issue→path map the worker prompt is handed. Paths live under
  `<targetRepoDir>/.claude/.worktrees/wave-<id>/issue-<n>` (durable, gitignored).
- Branch name `wave-<id>/issue-<n>` **shares the `wave-<id>/` stem with the dir** so a
  single glob (`git branch -D wave-<id>/*`) cleans both.

### `cleanupMerged(issues: number[]) → void` and `cleanupTerminal() → void`

3-point cleanup (§4.3), clean at **both ends**:
- `cleanupMerged` — per just-merged issue: `worktree remove --force` → `worktree prune` →
  `rm -rf` → `git branch -D wave-<id>/issue-<n>`. Keeps peak disk ≈ current group.
- `cleanupTerminal` — wave-terminal: remove remaining `wave-<id>` worktrees + prune +
  `git branch -D wave-<id>/*`.
- Removal order is defensive + idempotent. **Prune branches, not just worktrees**
  (`worktree remove` leaves the branch behind).

> The worker's `status: "already-present"` return is the worker-side half of #686
> idempotency: a worker whose branch already carries the implementation returns
> `already-present` and does no work, so a killed run resumes exactly where it died.
> The reconcile's "if a branch is already in kahuna, SKIP it" is the reconcile-side half.

---

## #687 — real gate signals via sdlc-server (+ plan/worker/reconcile MCP + promote)

The `agent()` **prompts** for plan / worker / reconcile / the four gate signals are
**real and shipped** (not seams). The seam is the **sdlc-server tool calls those agents
make** — currently `// TODO(#687 gate wiring)` lines inside the prompts, plus the
`gateSignalStub()` fallback and the promotion stub.

### The four trust signals (§3.4) — each returns `SIG`

```js
// SIG schema:
{ signal: string, passed: boolean, detail?: string }
```

Run **in parallel** (single `parallel([...])` block — already wired). Each is an
`agent()` whose prompt names the real sdlc-server call; #687 makes the call real:

| Signal | `agentType` | Real sdlc-server call | pass = |
|---|---|---|---|
| commutativity | `general-purpose` | `commutativity_verify(base_ref=<protected>, changesets=[{id:"kahuna", head_ref:<kahuna>}])` | verdict ∈ {STRONG, MEDIUM}; `PROBE_UNAVAILABLE` = **conservative-fail** |
| ci | `general-purpose` | `ci_wait_run` on the **kahuna→protected MR merge-result pipeline** (NOT merge-commit branch HEAD) [sdlc #452] | `final_status == "success"` |
| review | `feature-dev:code-reviewer` (`isolation:'worktree'` on kahuna [#667]) | code-reviewer over the **kahuna-vs-protected diff**, diff-scoped (§3.4) | no critical/important findings |
| trivy | `general-purpose` | `trivy fs --scanners vuln --severity HIGH,CRITICAL` on kahuna | no HIGH/CRITICAL with available fixes |

- The gate is a **unanimous** gate: `failed.length === 0` ⇒ PASS, else HOLD.
- Static analysis must be **diff-scoped (kahuna-vs-main), never tree-scoped** (§3.4) — or
  pre-existing baseline debt spuriously HOLDs an otherwise-clean wave. Lint/typecheck are
  **not** a fifth signal; they ride inside the CI signal.

### plan / worker / reconcile MCP calls

Inside the (real) prompts, replace the `// TODO(#687 gate wiring)` lines with real calls:
- **plan:** `spec_get`, `work_item`, `flight_overlap`, `flight_partition`. Returns `NEXTGROUP`.
- **worker:** `spec_get`, `spec_acceptance_criteria`. Implements + commits in the handed
  worktree. Returns `WORK` (incl. the §3.2 `concerns`/`deferrals` fields). Inherits the
  sdlc-server MCP + deterministic hooks; preload skills via the agent's `skills:`.
- **reconcile:** `commutativity_verify`, `pr_create`/`pr_merge` to kahuna. Returns `RECONCILE`
  (`merged`, `needs_rework:[{issue,reason}]`, `conflicts_resolved`, `concerns`). Persistence
  folds in here (see #688).

### Promotion (the success-exit terminal step)

The `MODE === 'auto'` PASS branch currently logs a `[SEAM #687] promote stub`. #687 makes
it real: `wave_finalize` opens the kahuna→protected MR, `pr_merge(skip_train:true)` on
all-green, delete the kahuna branch, record disposition. `interactive` mode never
promotes — it returns the verdict (the return IS the human gate, §5).

---

## #688 — wave-status persistence (the durable resume substrate)

Persistence is **folded into the reconcile node** (it already writes wave-status, §3.3).
Three call sites in the script, all currently log-only stubs:

### `persistIteration(state) → void` — called every loop iteration

```js
// state shape passed in:
{ merged: Set<number>, pending: Set<number>,
  reworkCount: { [issue]: number }, idleRounds: number, groupsRun: number }
```

- **Per merged issue:** `wave_record_mr(issue_number, mr_ref)` + `wave_close_issue(issue)`.
- **Then write the loop blob** durably to `.claude/status/` (the exact blob `rehydrate()`
  reads back — same shape as `REHYDRATE`). This is what makes a killed run resumable.

### `persistTerminal(disposition, detail) → void` — at promote/hold

- `disposition ∈ {"promoted", "held"}`. Record the wave's terminal disposition + `detail`
  into wave-status's wave-completion record, so the **campaign driver's** rehydrate (§5,
  `/wavemachine-next`) can prune a promoted wave on cold start.

> **Durable state must NOT live in `/tmp`** (`lesson_tmp_identity_boot_wipe`). The
> `/tmp/wavemachine/` bus is fine for within-run comms; resume state belongs in
> `.claude/status/`.

---

## Invariants the seams must not break

These hold for the skeleton today and must keep holding after every seam is filled —
they are what make the loop deterministic and resumable:

1. **The loop reads only the return shapes above** — never how they were produced. A seam
   fill changes the body, never the signature.
2. **Workers are handed a worktree path; they never create one.** Setup is a single
   awaited step before `parallel()`.
3. **`rehydrate()`'s `merged` set is authoritative for skip-on-resume.** If it is accurate,
   the loop resumes correctly; idempotent workers/reconcile make re-runs safe even if not.
4. **The trust gate runs ONLY on the success exit** (`!halt && pending.size === 0`). Any
   HOLD reason (incl. per-issue breaker) skips it — that is by construction, not a seam.
5. **Persistence is idempotent** — re-running `persistIteration` / `persistTerminal` with
   the same state is a no-op-or-overwrite, never a duplicate-side-effect.
6. **The `#687` gate stubs are the ONLY always-pass placeholders.** Once #687 lands, real
   signals replace them; until then a skeleton run reaches PASS so the full spine is
   exercisable end-to-end.
