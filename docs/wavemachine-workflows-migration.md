# Wavemachine → Dynamic Workflows: Migration Design

**Status:** on-paper design (no implementation). Closes the design phase tracked in #671.
**Decision in one line:** migrate the wave orchestration to Claude Code **Dynamic Workflows** **for determinism + reliability, not tokens.**

Background memories: `project_workflow_migration`, `lesson_cage_bars_signal_wrong_tool`.

---

## 1. Motivation — why migrate at all

We have been running the wave **Orchestrator as an LLM doing deterministic control flow** — a creative, independent reasoner forced to act as a state machine. Every recurring failure got patched *inside* that frame: WAVE_AXIOMS, the Concerns Channel, Exhaustive Legal Exits, the Stop-hook `decision:block`, and a string of stall bugs (#78 post-wave stall, #79 orchestrator drift, #90 Prime mid-sleep stall). Each patch made the "orchestrator is an agent" frame feel more load-bearing, so we questioned it less.

The root cause was using the wrong tool for control flow. The tell (now a saved lesson): **when you keep adding rule/guard/hook to make a tool behave against its nature, the guard-count is itself the signal to question the tool.** See `lesson_cage_bars_signal_wrong_tool`.

A Dynamic Workflow moves the control flow into a deterministic JS script and calls the LLM only for the steps that genuinely need judgment. It does **not** suppress agent creativity — it **relocates** it: thinking happens *inside* bounded sub-tasks (a flight implements; a reconcile resolves a conflict), where judgment is valuable and where a "distracted" agent can only fail *its own task*, never halt the campaign. The only thing made impossible is the spurious global stall — exactly the failure the cage was built to prevent.

### Why not tokens
The token win is **modest**, and we should not sell the migration on it. Flight handoffs are already lean (return code + file pointer), and the gate already delegates review to a subagent, so the orchestrator window isn't as bloated as it first seems. The real economics:
- **Billed vs. window tokens.** A subagent's internal churn is *billed* but never enters the parent *window*, so it doesn't compound every later orchestrator turn.
- Today's orchestrator accumulates the whole campaign in one growing transcript (quadratic re-send → compaction). A workflow holds that state in **free script variables**; the orchestrator's narration — the per-turn "now do X" — is replaced by zero-token control flow.
- So: flights cost ~the same; the orchestrator costs less; peak window (what triggers our compaction pain) drops materially. Net favorable for long campaigns, but measure it on the pilot.

### What changed in Claude Code that makes this possible
Dynamic Workflows (GA ~2026-06, CLI ≥ 2.1.154): deterministic JS orchestration of subagents — `agent()`, `parallel()`, `pipeline()`, schema-validated structured returns, `isolation:'worktree'`, `/workflows` observability, within-session resume. Plus matured subagents (rich definitions, `skills:` preload, scoped `tools`/`mcpServers`). Our existing investment is **additive**: subagents inherit our `sdlc-server` MCP tools; skills preload into flight agents; deterministic hooks stay for enforcement. Nothing is thrown away.

---

## 2. Vocabulary (load-bearing — see #668)

The word **flight** is overloaded in the current system; this doc uses:
- **flight-group** — a dependency-ordered batch of issues. **Groups are sequential** (`wave-status flight()` enforces strict ordering, [R-11]). A group exists to resolve dependency issues that surface *after* the wave plan is approved.
- **issue / per-issue worker** — the unit of **parallelism**. Within a flight-group, independent issues run **in parallel**, one worker sub-agent each.

So: **`Phase (serial) → Wave (serial) → flight-group (serial) → issues within a group (PARALLEL)`.** Parallelism lives only at the issue level. (#668 tracks de-overloading "flight" in code/docs.)

Roles:
- **Orchestrator** → becomes **the script** (deterministic control flow). Only the top-level session can spawn parallel sub-agents, which is why the script (not Prime) owns the fan-out.
- **Prime** → a **judgment `agent()`**: partitions issues into groups (`flight_partition`/`flight_overlap`) and does post-group **merge + reconcile** (`commutativity_verify`, `pr_merge`, drift checks). Cannot spawn sub-agents.
- **Flight** → a **per-issue worker** `agent()`, worktree-isolated.

---

## 3. The spine

```
rehydrate (durable resume)
   → flight loop  [ serial groups; parallel issues; dynamic re-plan; CLOSED legal exits ]
       per group:  plan(Prime) → parallel issue-workers → merge+reconcile(Prime)
   → trust gate   [ 4 signals in parallel → one more legal exit ]
   → promote (kahuna→main)  OR  hold-for-review
```

Every halt is a coded condition; every judgment is an agent; nothing can stall the campaign on a question it did not need to ask.

### 3.1 The dynamic flight loop

The hard problem is **termination**: a loop that can *add* work (fix-flights for surfaced dependencies) can thrash. The deterministic answer is a **closed set of legal exits + a hard progress guarantee**, checked at the top of every iteration. This is where `pattern_exhaustive_legal_exits` stops being prose the orchestrator must remember and becomes loop guards it cannot forget or override.

```javascript
// state (script-held, free); mirrored durably to wave-status each iteration
const pending = new Set(allIssueNumbers), merged = new Set()
const reworkCount = {}; let lastRework = [], idleRounds = 0
const groupsRun = []
let halt = null                                       // null = still converging; else a HOLD reason (NEVER a success)
const MAX_GROUPS = 24, MAX_REWORK = 3, MAX_IDLE = 2   // closed numeric guards

while (true) {
  // ── CLOSED LEGAL EXITS (the whole safety story) ──
  if (pending.size === 0)             break                       // success (halt stays null)
  if (groupsRun.length >= MAX_GROUPS) { halt='runaway'; break }   // → human review
  if (idleRounds >= MAX_IDLE)         { halt='thrash';  break }   // → human review
  if (budget.total && budget.remaining() < 80_000) { halt='cost'; break }

  // ── PLAN next group from CURRENT state (Prime; judgment) ──
  // sees merged/pending/surfaced → a dependency that appeared mid-wave becomes THIS group
  const plan = await agent(primePlanPrompt(merged, pending, lastRework),
    { label:`plan:${groupsRun.length+1}`, schema:NEXTGROUP, agentType:'general-purpose' })
  if (plan.done || !plan.group.length) { halt='impasse'; break }   // planner can't schedule remaining → human

  // ── RUN group issues in PARALLEL (isolated workers; intra-flight fixes inside) ──
  const built = (await parallel(plan.group.map(n => () =>
      agent(workerPrompt(byNum[n]), { label:`flight:#${n}`, schema:WORK, ...isolationOpt(n) }))))
    .filter(Boolean).filter(w => w.status === 'implemented')

  // ── MERGE + RECONCILE (Prime(post-flight) — the ONLY cross-flight view) ──
  // merges to kahuna; resolves conflicts + interface breaks; reports surfaced deps
  const rec = await agent(primeMergePrompt(built, reworkCount, idleRounds, groupsRun),
    { label:`merge:${groupsRun.length+1}`, schema:RECONCILE, agentType:'general-purpose' })

  // ── DETERMINISTIC state update + progress accounting ──
  const newlyMerged = rec.merged.filter(n => !merged.has(n))
  newlyMerged.forEach(n => { merged.add(n); pending.delete(n) })
  idleRounds = newlyMerged.length ? 0 : idleRounds + 1     // thrash detector
  lastRework = []
  for (const r of rec.needs_rework) {
    if ((reworkCount[r.issue] = (reworkCount[r.issue]||0)+1) > MAX_REWORK) { halt=`rework:#${r.issue}`; break } // per-issue breaker → HOLD, NOT success
    pending.add(r.issue); merged.delete(r.issue); lastRework.push(r)   // surfaced dep → re-opened → next group
  }
  groupsRun.push({ group: plan.group, merged: newlyMerged, rework: rec.needs_rework })
  if (halt) break   // breaker tripped inside the for-loop → leave the while with pending still non-empty
}
```

**Closed legal-exit set:**

| Exit | Condition | Meaning |
|---|---|---|
| success | `pending` empty | all issues merged to kahuna |
| runaway | `groupsRun ≥ MAX_GROUPS` | too many groups → human review |
| thrash | `idleRounds ≥ MAX_IDLE` | groups with zero net merges → not converging |
| cost | `budget` floor | stop before the ceiling |
| impasse | planner `done` w/ pending left | planner can't schedule remaining → human |
| per-issue breaker | issue reworked > `MAX_REWORK` | one issue keeps breaking → human |

**The dynamic-flight insight:** the loop is deterministic and cannot stall; **Prime** exercises the dependency judgment each iteration; a dependency that surfaces mid-wave (reported by reconcile as `needs_rework`) just re-opens the issue and becomes the next group — no human halt. That is the flight mechanism's whole purpose ("fix dependency issues that surface after plan approval"), expressed as a bounded loop.

### 3.2 Must-preserve features (BJ) — all live inside, none can halt the campaign

1. **Surface a concern + keep going** (Concerns Channel) → a field in the worker's structured return; the script collects it (logs/posts) and does **not** branch on it. "Keep going" is the default.
2. **Decide to defer a fix** → the agent *decides* (judgment) and returns `deferrals:[{issue,reason,risk}]`; the script *records* it (wave-status `defer`) and proceeds.
3. **Creatively fix issues mid-wave without asking/stopping** → *intra-flight* fixes happen inside the worker (it has git/edit in its worktree); *cross-flight* fixes (a shared interface two issues touch) happen in the **reconcile** agent — the only node with the multi-branch view; *surfaced dependencies* re-open via the re-plan loop. `commutativity_verify` (existing MCP) is the detector.

Principle: the workflow keeps the **good** autonomy (judge, fix, defer, flag) and removes only the **bad** autonomy (halting the whole campaign on an unneeded question).

### 3.3 Resumability

Two layers, different failures:

| Layer | Survives | Mechanism |
|---|---|---|
| within-session | pause / script-edit | `Workflow({scriptPath, resumeFromRunId})` — cached `agent()` results replay; side-effects already on disk aren't repeated |
| cross-session | session death / **reboot** | mirror canonical state to **wave-status** (`.claude/status/`, durable) every iteration; **rehydrate** on cold start so the loop skips finished work |

- The script can't call MCP/CLI directly → a cheap **rehydrate agent** reads wave-status and returns `{merged, pending, reworkCount, idleRounds, groupsRun}`; the script seeds its variables. **Persistence is folded into Prime(post-flight)** (it already writes wave-status): record each merged issue's MR + close it, then write the loop blob.
- **Idempotency is the crux of safe cross-session resume:** the **worker** must detect "my branch already has this implementation → return existing result," and **reconcile** must detect "this branch is already in kahuna → skip." `commutativity_verify` is read-only (idempotent for free). Make those two re-entrant and a killed run resumes exactly where it died.
- **Durable state must NOT live in `/tmp`** (`lesson_tmp_identity_boot_wipe`). The `/tmp/wavemachine/` bus is fine for within-run comms; resume state belongs in `.claude/status/`.

### 3.4 Trust gate (post-loop)

Runs **only if the loop reached the `success` exit** (all merged to kahuna). The 4 canonical signals run in **parallel** (independent), aggregate to a verdict, and the verdict is a deterministic ff-or-hold:

```javascript
if (!halt && pending.size === 0) {   // success exit ONLY — any HOLD reason (incl. per-issue breaker) skips the gate
  const signals = await parallel([
    () => agent('commutativity_verify across kahuna', {schema:SIG, agentType:'general-purpose'}),
    () => agent('ci_wait_run for the kahuna→main MR merge-result pipeline (NOT the merge-commit ' +
                'branch HEAD; skipped-branch + passing-merge-result = validated) [sdlc #452]',
                {schema:SIG, agentType:'general-purpose'}),
    () => agent('review the full kahuna-vs-main diff',
                {schema:SIG, agentType:'feature-dev:code-reviewer', isolation:'worktree'}), // worktree of kahuna [#667]
    () => agent('trivy HIGH/CRITICAL scan of kahuna', {schema:SIG, agentType:'general-purpose'}),
  ])
  const failed = signals.filter(Boolean).filter(s => !s.passed)
  // AUTO: promote kahuna→main. INTERACTIVE: the workflow ENDS returning the verdict (the return IS the human gate).
  return failed.length === 0 ? { gate:'PASS', promote:'kahuna→main' } : { gate:'HOLD', failing: failed }
}
return { gate:'SKIPPED', reason: halt || 'loop did not reach clean success' }
```

Two current gate bugs are **fixed by construction** here: the CI signal waits on the **MR merge-result pipeline**, not the merge-commit branch HEAD (#452); the review signal runs with **`isolation:'worktree'` on kahuna**, so it sees the branch natively — no diff-materialization workaround (#667). "Hold for review" is one more closed legal exit, lifted to the wave level.

**Static analysis must be diff-scoped (kahuna-vs-main), never tree-scoped** — a refinement the pilot forced (§9). Lint/typecheck are **not a fifth gate signal**; in the real wave they ride **inside the CI signal** (`ci_wait_run` runs the project's full gate). Whatever evaluates static cleanliness — the review signal (already "the kahuna-vs-main diff") and CI's lint/typecheck — must look only at the wave's *changed files*, not the whole tree. Otherwise **pre-existing baseline debt spuriously HOLDs an otherwise-clean wave**: the iter-3 pilot hit exactly this when a standalone lint check (run as a CI stand-in, since a dry-run has no merge-result pipeline to wait on) flagged unused imports in untouched *baseline* test files. Scope static analysis to the diff and a wave is judged on what it changed, nothing else.

---

## 4. Cross-repo

### 4.1 Invariant — a wave targets exactly one repo (→ #670)

The wave is the **atomic promotion unit** (kahuna→main), and atomic promotion is inherently per-repo — there is no two-phase commit across git remotes, so a wave straddling repos could never ff two mains atomically. Cross-repo coordination is expressed through **serial phases** (expand-contract: repo A expands → repo B adopts → repo A contracts), never a straddling wave. `phase.target_repos` may be plural (union across its waves); each **wave** resolves to one `target_repo`. Plan-time validator rejects a wave whose issues resolve to >1 repo. (`cross_repo: true` means *plan repo ≠ target repo*, not multi-target wave.) This collapses the worktree-map / reconcile / gate to single-repo — no repo dimension.

### 4.2 Worktrees

`isolation:'worktree'` only worktrees `CLAUDE_PROJECT_DIR` (the *plan* repo) — wrong codebase for cross-repo flights. So for cross-repo waves the **pre-created target-repo worktree IS the isolation** (current `nextwave` convention: "do NOT pass `isolation:'worktree'`"). Same-repo waves *do* use the flag.

- **Location:** `.claude/.worktrees/wave-<id>/issue-<n>` — durable (**not** today's `/tmp/wt-sdlc-*`, which is reboot-wiped and resume-hostile), gitignored, attached to the target clone.
- **Creation is idempotent:** `git worktree add <path> <existing-branch>` reusing a branch on resume, **never** `-b` (which fails if the branch exists).
- **Race-safety is structural:** the script `await`s a single setup step (create all of a group's worktrees) before `parallel()`. Workers are *handed* a path, never asked to create one.

### 4.3 Cleanup discipline ("damned sure no disk hemorrhage")

Three cleanup points — clean at **both ends**, not just the end (end-only leaks on every crash):

| Point | Action | Why |
|---|---|---|
| setup (wave start) | sweep all **prior** wave-ids' worktree dirs + `git worktree prune` | crash recovery — tidy before build |
| reconcile (per merge) | remove a just-merged issue's worktree | peak disk ≈ current group, not whole wave |
| wave-terminal (promote/hold) | remove the wave's remaining worktrees + prune | prompt reclaim on the normal path |

**Resume tension resolved:** the setup sweep is scoped to `wave-<id> ≠ current`; the current wave's dir is **preserved and re-attached** (idempotent). Removal order is defensive + idempotent: `worktree remove --force` → `worktree prune` → `rm -rf`.

**Prune branches, not just worktrees** (refinement from the §9 multi-repo pilot): `git worktree remove` leaves the branch behind. At reconcile (per merge) and at wave-terminal, also `git branch -D` the wave's merged/abandoned branches, or the target clone slowly accretes dead refs — observed in pilot 1, where three per-wave branches survived worktree removal. **The worktree dir and its branches must share one `wave-<id>` stem** so a single glob (`git branch -D wave-<id>/*`) cleans both: pilot 1 used dir `wave-9001/` but branches `wave9001/…` (no hyphen), so the hyphenated glob would have missed them. Standardize on the hyphenated `wave-<id>/` for both dir and branch.

---

## 5. Outer campaign loop (`/wavemachine`)

`/wavemachine` runs **one per-wave workflow per pending wave** — the §3.1 closed-legal-exits pattern lifted one level. Campaign state (which waves promoted) is script-held and mirrored to wave-status each iteration:

```javascript
const pendingWaves = new Set(approvedWavePlan)    // the pre-approved phase/wave plan; rehydrate prunes promoted (below)
let halt = null                                   // null = converging; else a HOLD reason (NEVER a success)
const waveRetry = {}; const promoted = new Set()
const MAX_WAVES = 64, MAX_WAVE_RETRY = 2, CAMPAIGN_FLOOR = 120_000

while (true) {
  // ── CLOSED LEGAL EXITS (campaign level) ──
  if (pendingWaves.size === 0)        break                          // success — all waves promoted to main
  if (promoted.size >= MAX_WAVES)     { halt='runaway'; break }      // defensive bound → human
  if (budget.total && budget.remaining() < CAMPAIGN_FLOOR) { halt='cost'; break }

  const wave    = nextPendingWave()                                 // from the approved phase/wave plan
  const verdict = await runWaveWorkflow(wave)                       // §3 spine → { gate, promoted, ... }

  // Advance ONLY on PASS **and** promoted: gate==='PASS' is necessary but NOT sufficient — a
  // { gate:'PASS', promoted:false } means the trust gate passed but the kahuna→main merge did NOT
  // land (auto promote node soft-failed → wave recorded HELD; or interactive, where the Workflow
  // never auto-promotes). Either way the wave is not on main → it HOLDs, it does not advance.
  if (verdict.gate === 'PASS' && verdict.promoted === true) {       // landed on main → progress
    promoted.add(wave); pendingWaves.delete(wave); waveRetry[wave] = 0; continue
  }
  // (interactive: surface the verdict + kahuna→main diff, STOP for the human, and on resume advance
  //  only if wave-status durably records the wave `promoted` — symmetric with the auto fact above.)
  if ((waveRetry[wave] = (waveRetry[wave]||0)+1) > MAX_WAVE_RETRY) { halt=`wave-breaker:${wave}`; break } // won't converge → human
  halt = 'wave-hold'; break                                         // HOLD/SKIPPED/PASS-not-promoted → human review
}
```

> The per-wave Workflow returns `{ gate, promoted, ... }` (see `per-wave-workflow.js`) — `gate` and
> `promoted` are **distinct facts**. The campaign advances only when both hold; a `gate:'PASS'` whose
> `promoted` is false is a HOLD, not progress. The operational driver `/wavemachine-next` (#690)
> implements this; the simplified `{ gate: PASS | HOLD | SKIPPED }` shorthand used elsewhere in this
> section predates the `promoted` split and is superseded by the contract here.

**Closed campaign-exit set** (mirrors §3.1; `halt` keeps HOLD distinct from success):

| Exit | Condition | Meaning |
|---|---|---|
| success | `pendingWaves` empty | every wave promoted to main |
| runaway | `promoted ≥ MAX_WAVES` | defensive bound → human |
| cost | budget floor | stop before the ceiling |
| wave-hold | a wave returns HOLD/SKIPPED, or (auto) PASS-but-not-promoted | the per-wave gate fired, or the gate passed but the kahuna→main merge did not land → human review |
| wave-breaker | a non-advanceable verdict > `MAX_WAVE_RETRY` times | one wave won't reach PASS-and-promoted → human |

- **No campaign-level planner → no `plan done`/success collision.** Unlike §3.1's inner loop (which *plans each group* with a judgment agent and must guard `plan.done` against the success exit), §5 draws waves from the **pre-approved** phase/wave plan via `nextPendingWave()` — there is no planner verdict to misread, so success is `pendingWaves` empty and nothing else. The §3.1 sentinel-collision is designed out, not guarded against. (If a campaign ever needs to *re-plan* waves mid-run, it would add a planner agent plus an `impasse` exit, mirroring §3.1.)
- **Progress is structural.** Each iteration either promotes a wave (`PASS` **and** `promoted`) or halts — a campaign iteration cannot make zero net progress and continue, so no idle-round detector is needed; the retry breaker covers a wave that repeatedly fails to reach PASS-and-promoted. A `gate:'PASS'` that did not land on main is not progress.
- **Resumability (mirrors §3.3).** On cold start the campaign rehydrates from wave-status's wave-completion records (`wave_previous_merged` / `wave_topology`) and skips already-promoted waves; `promoted` / `pendingWaves` seed from there. Same durable substrate as the inner loop, one level up.

One Workflow per wave: workflows can't pause mid-run for human input, so the wave-workflow *ending* with a verdict IS the per-wave gate — something *outside* it consumes that verdict and routes. **That something is the `/wavemachine` skill itself:** the loop above runs **in the main session, not as a nested Workflow.** The skill launches one wave-Workflow per wave, reads its verdict, and advances — `auto` advances on `PASS` **and** `promoted`; interactive surfaces the verdict and STOPS for the human, then advances on the human's go **once wave-status records the wave `promoted`** (both modes gate on a durable `promoted` fact). Mode is a one-line advance-vs-wait branch, **not two architectures.**

Why the skill, not a campaign-level Workflow nesting wave-workflows:

1. **Interactive review-between-waves is a hard requirement, and a Workflow can't pause for it** — so the skill driver must exist regardless; a second auto-only nested-Workflow mechanism would merely duplicate it (maintenance + drift cost for no new capability).
2. **The campaign loop is thin** — N pre-approved waves, one launch + verdict each. The determinism that matters, and *all* judgment (drift/merge/review via §3.1 reconcile + the §3.4 trust gate), live *inside* each wave-Workflow; there is almost nothing at the campaign altitude for an LLM to get wrong.
3. **Resume is native and reboot-proof** — the skill rehydrates `promoted`/`pendingWaves` from wave-status (§3.3). A nested campaign-Workflow has only *within-session* resume and would fall back to the same wave-status substrate on reboot anyway.
4. **Observability** — each wave is its own `/workflows` run, individually inspectable, not a child buried inside one giant campaign run.

**Tradeoff accepted:** in unattended `auto`, the main session spends a thin sliver of turns between waves (launch → await → read → launch). Cheap — the heavy work is all inside the wave-workflows (billed, off the main window), so the peak-window/determinism wins are intact.

---

## 6. What stays unchanged

- **sdlc-server MCP** enforcement (subagents inherit it — `feedback_mcp_over_skill`).
- **Deterministic hooks** (pre-push test gate, secret gate) — they must fire every time; workflows orchestrate, they don't enforce.
- **Skills** as procedures (`/precheck`, etc.) — preloadable into flight agents via `skills:`.
- **wave-status** as the durable wave-state store + dashboard source (now also the resume substrate).

---

## 7. Open questions / not-yet-decided

- **Clone location:** dedicated wave-clone vs. reuse the dev's `~/sandbox` clone. Leaning reuse (working-tree-safe; worktrees don't disturb the dev checkout) — the load-bearing fix was the *worktree* location (§4.2), not the clone. Infra call.
- **Latent current-system bug (noted, deliberately unfiled):** today's `/tmp/wt-sdlc-*` + `-b` worktree convention loses in-flight worktrees on reboot and fails to resume (`branch already exists`). Independent of the migration; fix would move worktrees to a durable path + idempotent re-attach.
- **Per-stage model assignment** (cheap stages on Haiku) and **budget** scaling — levers, to tune on the pilot.

*(Resolved and moved into §5: where the campaign loop physically lives — it runs in the `/wavemachine` skill for both modes, not as a nested Workflow. See #677.)*

---

## 8. Pilot plan (needs explicit opt-in — spawns agents that write code)

**Executed 2026-06-17 — results in §9.** This is the plan as designed; §9 records what actually happened (including where these facts were wrong).

**Dry-run first:** implement + verify + report, **no merge**, **static partition** (skip the dynamic re-plan + reconcile) — to validate the shape and measure cost safely.

- Target: `Wave-Engineering/ccwork-testtarget`. *(Correction: the real target was Tier-1 stories **#6/#7/#8** — the earlier `#105/#106/#107` + `phases-waves.json` were stale; that repo holds ~17 open stories #5–#21 and no plan file. The repo is a fully-built fixture, so the pilot branched from a pre-story baseline and used `main` as a correctness oracle — see §9.)*
- Scope: one small wave, 2–3 issues, so the first `/workflows` observation is cheap and legible.
- Measure: **per-flight token baseline** against our real CLAUDE.md + MCP load, vs. a current-model wave's accumulated cost. The measurement is itself a reason to run it.
- Then iterate up: add the merge/reconcile stage → the dynamic re-plan loop → cross-repo worktrees → the trust gate.

---

## 9. Pilot validation (2026-06-17)

The pilot ran as four Workflows against `ccwork-testtarget` stories #6/#7/#8, branched from baseline `5253228` (foundation present, the three stories absent), with `main` as a correctness oracle. **The per-wave spine is validated end-to-end on real code.** No merge to any `main` — all dry-run.

### What ran, and what each run proved

| Run | Added | Result |
|---|---|---|
| Dry-run | self-authored tests only | All 3 flights green — but **structurally divergent** from known-good; #7 silently reimplemented a missing artifact. **Green ≠ correct.** |
| Iter 1 | trust-gate **review** | Reviewer (no test re-run, no peek at `main`) caught both divergent flights (#6 important, #7 critical) and **correctly passed** the one correct flight (#8). Review *discriminates*. |
| Iter 2 | **oracle test** (canonical test as the gate, not self-authored) | All 3 converged to the canonical interface, independently verified not-copied. **~15× cheaper than review** (oracle verify is a mechanical pytest run). |
| Iter 3 | **reconcile + full gate** | Reconcile merged 3 branches, resolved the add/add `tier1/__init__.py` conflict, **commutativity confirmed (51-test suite green, all flights coexisting)**. Gate returned **HOLD** correctly — suite PASS, review PASS w/ a minor incoherence, **lint FAIL** (run standalone as a CI stand-in; see §3.4). |
| 3b | **dynamic re-plan loop** (constructed surfaced-collision scenario) | Two stories collide on `tier1/pricing.py`'s `price()` (provider `(tokens,model)` vs consumer `(tokens)`); the plan grouped them parallel, unaware. The real §3.1 loop ran: **Group 1** built [A,B] → reconcile merged provider A, **reset consumer B keeping integration green (40 passed)**, reported `needs_rework:[B]` → loop re-opened B → **Group 2** re-ran B against merged A, it adapted (43 passed) → `outcome: success` in 2 groups, no human halt. Bounded by `MAX_REWORK`/`MAX_IDLE`/`MAX_GROUPS`. |
| Multi-repo 1 | **target-repo worktree isolation** (§4.2; plan ≠ target) | Plan repo = claudecode-workflow, target = `ccwork-testtarget`. Setup **pre-created** worktrees at `.claude/.worktrees/wave-9001/issue-<n>` (not `isolation:'worktree'`); flights reported `created_own_worktree:false` (race-safe, handed paths); 3-point cleanup left **zero** wave worktrees; **dev checkout untouched** throughout; integration 48 green. |
| Multi-repo 2 | **expand-contract across two repos** (§4.1; #670 one-repo-per-wave) | Constructed provider+consumer (consumer editable-installs provider → tests the live provider main). 3 serial waves, each one repo: **Expand**(provider, `+greet_v2` keeping `greet`) → **Adopt**(consumer, →`greet_v2`) → **Contract**(provider, `−greet`). `all_waves_both_green: true` — neither main ever broken; contract safe only because adopt preceded it. |

### The load-bearing finding — verification is a non-redundant ladder

Self-test (self-consistency) **<** oracle test (contract) **<** lint (hygiene) **<** review (intent/architecture). Each rung caught a class the rung below missed: self-tests passed on divergent code; the oracle pinned the interface; lint caught unused imports pytest ignored; review caught intent-divergence and an incoherent `__init__` docstring. The migration's value is that the **deterministic script composes all of them around judgment agents**, so none gets skipped on a "distracted orchestrator" turn — the whole thesis, demonstrated. Design corollary (§3.1/§3.2): a flight's *verify* should run the story's **acceptance test as an oracle** where one exists — self-authored tests are necessary but not sufficient.

### Cost

~1.0M output tokens across ~22 agent-runs, **all billed off the main-session window** (the §1 "billed vs window" economics, demonstrated). Per-flight implement ≈ 51k; trust-gate review ≈ 90k/flight (expensive — reserve for what a test can't encode); oracle verify ≈ 5k/flight (cheap, deterministic, *guiding*). Prefer oracle tests where the contract can be pinned; reserve LLM review for architecture / security / unstated intent.

### Refinement applied; progression complete

- **Applied (§3.4):** static analysis is **diff-scoped**, not tree-scoped. Iter-3's HOLD came from a standalone lint check (a stand-in for CI's lint/typecheck, which a dry-run can't run) that partly flagged *pre-existing baseline* debt — which must not block a wave.
- **Dynamic re-plan loop (3b) — validated.** The independent pilot stories never surfaced a cross-dependency, so 3b was exercised with the constructed collision above: a surfaced interface break re-opened a flight and the deterministic loop converged in two groups, no human halt. This is the failure class the LLM-orchestrator kept stalling on (#78/#79/#90), now expressed as bounded control flow — reconcile (judgment) detects and reports the break; the loop re-schedules it; the closed guards make non-convergence a bounded exit, not a thrash.

**Every §8 rung and all of §4 (cross-repo) is now exercised and passed** — shape, trust-gate review, oracle test, reconcile + gate, the dynamic re-plan loop, target-repo worktree isolation (§4.2), and expand-contract coordination across two repos (§4.1). The migration design is validated end-to-end on real and constructed scenarios, single- **and** multi-repo. Nothing remains design-only. The remaining §7 items (clone location, the latent worktree bug, per-stage model/budget) are tuning levers, not unproven mechanisms.

---

## 10. References

- **Memories:** `project_workflow_migration`, `lesson_cage_bars_signal_wrong_tool`, `lesson_cross_repo_wave_orchestration`, `lesson_cc_subagent_tools`, `lesson_stop_hook_with_block`, `pattern_exhaustive_legal_exits`, `pattern_concerns_channel`, `principle_user_attention_is_the_cost`, `lesson_tmp_identity_boot_wipe`.
- **Issues:** #668 (flight vocab), #670 (single-repo-per-wave axiom), #667 (gate reviewer / un-checked-out branch), sdlc #452 (ci_wait_run GitLab merge-commit); parsing-crash family fixed: #663/#665, sdlc #445.
- **Skills:** `nextwave` (Orchestrator/Prime/Flight protocol — current), `wavemachine` (campaign loop — current).
- **WAVE_AXIOMS.md** — binding wave-pattern axioms.
