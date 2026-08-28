---
name: nextwave
description: Execute one wave via the per-wave Workflow — the §3 spine (rehydrate → dynamic flight loop → trust gate → promote) as a deterministic JS Workflow, not an LLM orchestrator
---

# NextWave — Execute One Wave via the per-wave Workflow

> **The dynamic-workflows per-wave primitive (cut over #691).** Deterministic control flow
> lives in a JS Workflow script, and the LLM is called only for the steps that genuinely
> need judgment (plan / implement / reconcile / review). This replaced the legacy
> LLM-orchestrated `/nextwave` (Orchestrator/Prime/Flight on a filesystem bus). Design of
> record: `docs/wavemachine-workflows-migration.md`.
>
> **Source vs. runnable artifact (live-gate finding #2):** a Dynamic Workflow must be ONE
> self-contained file with `export const meta` first — cross-file `import`s do NOT run as a
> Workflow. So the engine's tested halves live in modules (`per-wave-workflow.js` +
> `wave-status.js`/`resume.js`/`gate.js`) and `bundle.mjs` inlines them into the single-file
> artifact **`per-wave-workflow.bundled.js`** — the file the Workflow tool actually invokes.
> Edit the source modules, then `node skills/nextwave/bundle.mjs`; a regression test
> (`test_bundle_in_sync.sh`) fails if the committed bundle drifts from its source.

**See Also:** `docs/executor-model-devspec.md` (Plan #822 — the executor model: `/nextwave` reads the per-wave `dispatch` hint that `/prepwaves` computes and fans or serializes accordingly; see §5.1 and Story 1.2).

## Axioms

Bound by WAVE_AXIOMS 2, 3, 4, 5, 6, 8, 9 (`WAVE_AXIOMS.md` at the repo root). The
closed-list legal-exits enumeration, the Concerns Channel pressure valve, the
cost-asymmetry default-forward stance, the approval-frequency rule, and the
user-attention-as-cost framing live in that file. In this successor those axioms are
no longer prose the orchestrator must remember — they are **loop guards in the
Workflow script it cannot forget or override** (`per-wave-workflow.js`, §3.1). When
justification prose seems missing, it is in `WAVE_AXIOMS.md` by design.

## What this is

`/nextwave` runs **one** Workflow — `per-wave-workflow.js` — for a single wave.
That script IS the §3 spine:

```
rehydrate (durable resume)
   → flight loop  [ serial groups; parallel issues; dynamic re-plan; CLOSED legal exits ]
       per group:  plan(Prime) → parallel issue-workers → merge+reconcile(Prime)
   → trust gate   [ 4 signals in parallel → one more legal exit ]
   → integrate (kahuna→integration base)  OR  hold-for-review
```

**Where the wave lands (#1052).** The final node merges the kahuna branch into this wave's
**integration base**, which is *not* necessarily the protected branch:

- **inside a campaign** (`/wavemachine`) the base is the campaign's own long-lived branch, so the
  node performs an **integration**; the protected branch is written exactly once, by the campaign's
  release gate, after every wave has integrated *and* the DoD is met.
- **standalone** (a human running one wave) there is no campaign branch, the wave *is* the whole
  increment, and the base defaults to the protected branch — so integration and release coincide.

A wave never decides to write trunk; it writes whatever base it was handed. See the BRANCH TOPOLOGY
note in `campaign-loop.js` for why the interim merge-backs were removed.

Every halt is a coded condition; every judgment is an `agent()`; nothing can stall the
campaign on a question it did not need to ask. The skill's job is thin: resolve the
wave's inputs, launch the Workflow, and surface its verdict.

## Why a Workflow, not an LLM orchestrator

We ran the wave Orchestrator as an LLM doing deterministic control flow — a reasoner
forced to act as a state machine — and patched every recurring stall inside that frame
(WAVE_AXIOMS, the Concerns Channel, the Stop-hook `decision:block`, #78/#79/#90). The
guard-count was the tell: when you keep adding rules to make a tool behave against its
nature, question the tool (`lesson_cage_bars_signal_wrong_tool`). A Workflow relocates
the control flow into deterministic JS and calls the LLM only inside bounded sub-tasks
(a flight implements; a reconcile resolves a conflict), where a "distracted" agent can
only fail *its own task*, never halt the wave. See migration doc §1.

## Inputs (the Workflow's `args`)

The engine reads the Workflow runtime global **`args`** (live-gate finding #1 — NOT `input`;
the old engine read a non-existent `input`, silently got `{}`, and ran an empty wave). Pass
`args` as a **JSON object** (a JSON string is tolerated and parsed, but the object form is
canonical). An **empty / missing `issues` list is fail-loud** (#4): the engine refuses rather
than reaching the trust gate with nothing merged and opening/promoting at the protected branch.

Supplied by the caller (`/wavemachine` per wave, or a human launching one wave):

| Field | Meaning |
|---|---|
| `waveId` | the wave id (e.g. `W-3`) |
| `issues` | the wave's issue numbers (one repo — single-repo-per-wave axiom, §4.1). **Required, non-empty.** |
| `targetRepo` | `owner/repo` for `gh -R` scoping |
| `targetRepoDir` | the clone the durable worktrees attach to (§4.2) |
| `kahunaBranch` | the wave's own integration target; every flight PR targets this, never the integration base and never the protected branch |
| `integrationBase` | #1052: where the kahuna branch merges on the success exit — the **campaign branch** in a campaign, the protected branch for a standalone wave. Defaults to `protectedBranch` (the standalone shape). A campaign driver ALWAYS passes it. |
| `preserveKahuna` | #722: `true` ⇒ persistent per-plan kahuna (shared across a plan's waves) — promote does NOT delete it. Default `false` = per-wave disposable. **Retired inside a campaign (#1052)** — accepted but ignored when `integrationBase !== protectedBranch`. See lifecycle below. |
| `dispatch` | #824: the wave's dispatch hint from `phases-waves.json` (written by `/prepwaves` #823). `fan` ⇒ the planner's conflict-free group runs in parallel; `serialize` / `serialize-preferred` / **absent** ⇒ single-file (one issue per flight-group). Threaded into the engine and **enforced** by the flight loop — see "Dispatch enforcement" below. Absent ⇒ `serialize` (CT-01). |
| `protectedBranch` | the trunk. Used to *recognize* trunk (the engine derives "am I in a campaign?" from `integrationBase !== protectedBranch`), and as the default `integrationBase` for a standalone wave. A campaign wave never writes it. |
| `mode` | `auto` (verdict drives promotion) \| `interactive` (verdict returned; human routes) |
| `planId` | wave plan id — the gate's PR-open node needs it to assemble the kahuna→protected MR body (#687/#5); also keys the FlightDeck activity id (`AID = PLAN_ID \|\| WAVE_ID`), so a standalone run without it degrades to a wave-scoped id (cc-workflow#1171). Read from `phases-waves.json`'s top-level `plan_id` (step 1), written by `/prepwaves`. |
| `budget` | optional `{ total, remaining() }` cost guard (the `cost` legal exit) |

The closed numeric guards (`maxGroups`, `maxRework`, `maxIdle`, `costFloor`) have
safe defaults in the script and rarely need overriding.

### Kahuna branch lifecycle — disposable again (#1052 supersedes #722)

**Inside a campaign, every wave's kahuna is disposable.** It is cut off the campaign branch, the
wave integrates it there, and the promote node deletes it. Nothing continues from a kahuna across
waves, so a **squash** merge is harmless — which is the whole reason the interim merge-backs went
away (#892: a persistent branch plus a squash merge cannot show equality with its base, because the
squash rewrites the history the equality check compares).

The cross-wave state that #722 needed a persistent kahuna for now lives on the **campaign branch**,
which is long-lived by design and never squashed onto (waves merge *into* it; it merges onto trunk
once). `preserveKahuna: true` is therefore **accepted but ignored** when `integrationBase !==
protectedBranch` — a stale launcher passing it cannot resurrect the divergence. The engine logs when
it ignores the flag.

**Standalone waves keep the old semantics.** With no campaign branch, `integrationBase` is the
protected branch, and `preserveKahuna` behaves exactly as #722 documented: `false` (default) ⇒ the
promote node deletes the kahuna after the merge; `true` ⇒ it survives.

### Dispatch enforcement — the `dispatch` hint governs flight parallelism (#824)

`/prepwaves` (#823) annotates every wave in `phases-waves.json` with a `dispatch` field
(`fan` / `serialize` / `serialize-preferred`). `/nextwave` — and `/wavemachine`'s per-wave
launch — **reads that field and threads it into the Workflow `args` (`args.dispatch`)**, and the
engine **enforces** it. This is not documentation-only: post-#691, the real executor is
`per-wave-workflow.js`, whose Prime planner partitions the pending issues into a conflict-free
parallel flight-group by **file conflict** (#705). The dispatch hint is applied on top of that
partition, as a **ceiling on parallelism** (`skills/nextwave/dispatch.js`, `applyDispatchCeiling`):

- **`dispatch: fan`** → the planner's conflict-free group runs **in parallel** as-is. Fan adds no
  parallelism of its own; the #705 file-conflict floor still applies underneath, so a `fan` wave is
  never *less* serialized than the file-conflict analysis demands. *(Asymmetric bias: fanning a wave
  that should have serialized risks a cross-flight conflict the reconcile loop must unwind;
  serializing a wave that could have fanned only costs a little wall-clock. The cheap mistake is
  over-serializing — so an absent or ambiguous hint biases to serialize, never to fan.)*
- **`dispatch: serialize` / `serialize-preferred` / absent** → **single-file**: the loop builds
  **one issue per flight-group**, the rest stay pending and schedule in the next iteration.
  `serialize-preferred` means "serialize unless the operator opts in to fan"; there is no operator
  opt-in signal at execution time, so the executor treats it as `serialize`.
- **If `dispatch` is absent, the default is `serialize` (CT-01)** — a backward-compatible default,
  so an older `phases-waves.json` written before this field existed still executes correctly.

**Ceiling, never a floor.** Dispatch can only make a wave *more* serial (safer) than #705's
file-conflict partitioning would — it never widens a group or adds an issue. The R-03 intra-dependency
hard gate is enforced upstream at plan time by `/prepwaves`, so an intra-dep wave already arrives
annotated `serialize` and never reaches the executor as `fan`.

## Procedure

1. **Resolve wave inputs.** Read the next pending wave for this Plan (`wave_next_pending`),
   its issue list, the `kahuna_branch` (always populated — `/wavemachine` bootstraps it
   at Plan launch), the target repo + clone dir, the protected branch (from
   `.claude-project.md`), the **`integrationBase`** (the campaign branch when running under
   `/wavemachine`; omit for a standalone wave and it defaults to the protected branch, #1052),
   and the wave's **`dispatch`** field (from `phases-waves.json`;
   absent ⇒ `serialize`, CT-01) to thread into `args.dispatch`. Refuse if `kahuna_branch` is
   unset — wave state was not bootstrapped through the campaign launch sequence.

   **Also read `plan_id`** (top-level, in the SAME persisted plan file this step already reads
   for `dispatch` — do not hardcode its path: `status_dir()` resolves `.sdlc/waves/` in a repo
   carrying `.sdlc/`, falling back to `.claude/status/` otherwise, and `/prepwaves`'s
   `campaign-head` call resolves it the same way, so hardcoding either path here would read a
   different plan than the one just prepped in a `.sdlc/`-carrying repo) and thread it into
   **`args.planId`** (cc-workflow#1171). `/prepwaves` writes this field for every plan it
   persists (step 7, backfilling it on an extend of a legacy plan that predates the
   convention), so it is present whether this run is orchestrated by `/wavemachine` or
   standalone — closing the gap where a bare `/nextwave` run left `per-wave-workflow.js`'s
   `AID = PLAN_ID || WAVE_ID` with no `PLAN_ID` and degraded to a wave-scoped (not
   campaign-scoped) FlightDeck activity id, a new id every wave. Absent field (a
   `phases-waves.json` written by something other than `/prepwaves`) ⇒ omit
   `args.planId` — the existing `WAVE_ID` fallback is unchanged, not an error.
2. **Validate specs.** Confirm every wave issue is structurally buildable
   (`spec_validate_structure`). Any INVALID → report and exit (not an error — a Legal Exit).
3. **Launch the Workflow.** Invoke the single-file artifact `per-wave-workflow.bundled.js`
   (via the Workflow tool's `scriptPath`) with the inputs above passed as **`args` (a JSON
   object)**. The script owns everything from here: rehydrate → flight loop → trust gate (which
   opens the kahuna→base DRAFT PR first, then runs the four signals on it, #5) → integrate.
4. **Consume the verdict.** The Workflow's return is the per-wave gate (§5): a Workflow
   cannot pause mid-run for human input, so its *ending with a verdict* IS the gate. The
   return carries `gate` ∈ `PASS | HOLD | SKIPPED`, **`integrated`** ∈ `true | false` (did the
   kahuna→base merge land — the field the campaign loop routes on), `promoted` (the same fact
   under its legacy name, kept so a mid-campaign engine upgrade doesn't strand in-flight
   records), `integrationBase`, plus `concerns`/`deferrals` (informational — surfaced and
   continued, never halted-on). **`gate` and `integrated` are distinct facts** — read both:
   - `auto` + `{ gate:'PASS', integrated:true }` ⇒ the promote node landed the kahuna→base
     merge. In a campaign the wave is on the **campaign branch**, not trunk — it is *integrated,
     not released*; the campaign's DoD gate decides release. Standalone, base *is* trunk, so the
     wave is done. Report which one it was.
   - `auto` + `{ gate:'PASS', integrated:false }` ⇒ the gate passed but the promote node
     **soft-failed — the merge did NOT land** (the wave is recorded HELD; `reason` carries the
     promote error). The code is sound but not on the integration base → surface as a HOLD for
     manual integration, NOT as success. (It can be retried on resume — the kahuna branch
     is gate-clean.)
   - `interactive` + `{ gate:'PASS', integrated:false }` ⇒ by design the Workflow never
     auto-promotes; surface the verdict + the kahuna→base diff and STOP for the human, who
     routes the merge. When the human lands it, the wave's terminal
     disposition is updated to `promoted` in wave-status — that durable record is what
     `/wavemachine`'s interactive branch reads (`waveDisposition`) to advance, so it never
     advances on the operator's word alone. (`/wavemachine` owns this branch in a campaign.)
   - `{ gate:'HOLD' }` / `{ gate:'SKIPPED' }` (always `integrated:false`) ⇒ a trust signal failed
     or the flight loop hit a HOLD exit before the gate; surface the failing signals / halt reason.

   **The durable disposition string is still `promoted | held`** and now means "landed on its
   integration base". It was deliberately not renamed: in-flight campaigns and the `wave-status`
   CLI both read that value, so renaming it would strand every existing record for a vocabulary
   improvement. `released` is a separate, campaign-level fact that only the release node asserts.
5. **Report.** Surface a human-readable summary: groups run, issues merged, any HOLD
   reason, collected concerns/deferrals. Post wave status to `#wave-status` if running
   under a campaign.

## What is REAL vs SEAM in the Workflow

`per-wave-workflow.js` is the **anchor**: the loop / exits / re-plan / gate fan-out are
real and complete (the validated pilot shape, hardened). The sdlc-server tool calls the
agents make were originally staged as **seams** — now all **FILLED**: the bundle ships
real `agent()` calls plus real `pr_merge` / `wave_finalize` / `commutativity_verify`, not
placeholder stubs. The seam contracts (the interface each fill honors) live in
`skills/nextwave/SEAMS.md`:

- **#686** (FILLED) — rehydrate / idempotency (durable resume, worktree setup/cleanup)
- **#687** (FILLED) — real gate signals via sdlc-server (commutativity / CI / review / trivy + promote)
- **#688** (FILLED) — wave-status persistence (the durable resume substrate)

## Must-preserve behaviors (§3.2)

All three live *inside* the Workflow and **none can halt the wave**:

1. **Surface a concern + keep going** — a `concerns[]` field on the worker/reconcile
   return; the script collects it (informational) and does NOT branch on it. "Keep
   going" is the default.
2. **Decide to defer a fix** — the agent decides; returns `deferrals:[{issue,reason,risk}]`;
   the script records and proceeds.
3. **Creatively fix mid-wave without asking** — intra-flight fixes inside the worker's
   worktree; cross-flight fixes in the reconcile agent (the only multi-branch view);
   surfaced dependencies re-open via the re-plan loop. `commutativity_verify` is the detector.

## Exhaustive Legal Exits

Per WAVE_AXIOMS Axiom 3 the legal-exits list is closed — and here it is **mechanically
closed**: the only ways the per-wave Workflow stops are the script's coded exits
(`per-wave-workflow.js` §3.1 loop + §3.4 gate). They are:

| Exit | Condition | Meaning |
|---|---|---|
| success | `pending` empty | all issues merged to kahuna → trust gate runs, then kahuna→integration base |
| runaway | `groupsRun ≥ MAX_GROUPS` | too many groups → human review |
| thrash | `idleRounds ≥ MAX_IDLE` | groups with zero net merges → not converging |
| cost | `budget` floor | stop before the ceiling |
| impasse | planner `done` with pending left | planner can't schedule remaining → human |
| per-issue breaker | issue reworked > `MAX_REWORK` | one issue keeps breaking → human |
| reconcile-blocked | reconcile returns `blocked` | a push to origin was rejected (pre-push gate / permissions / protected ref) → HOLD with the reason; reconcile never substitutes local merges (#724) |
| gate HOLD | a trust signal failed | post-success gate fired → human review |

Unease that matches none of these is NOT an exit: it rides the `concerns[]` channel
(Axiom 4) and the loop continues. The dynamic-flight insight: a dependency that surfaces
mid-wave (reported by reconcile as `needs_rework`) re-opens the issue and becomes the
next group — **no human halt**. That is the failure class the LLM-orchestrator kept
stalling on (#78/#79/#90), now expressed as bounded control flow.

## Non-Negotiables

- EXECUTION primitive — NO design decisions. Workers are SPEC EXECUTORS.
- **NEVER merge directly to the integration base from a flight.** Flight PRs target the kahuna
  branch; the kahuna→base merge is the only path off the kahuna branch and is gated by the
  four-signal trust gate (§3.4).
- **A wave inside a campaign NEVER writes the protected branch (#1052).** Its base is the campaign
  branch; the single trunk write belongs to the campaign's release gate, after the DoD. The engine
  forces this structurally — every gate node takes `integrationBase`, and no wave-level path takes
  `protectedBranch` as a merge target.
- **Single-repo per wave** (§4.1) — a wave resolves to exactly one `target_repo`.
- **Durable worktrees, not `/tmp`** (§4.2, `lesson_tmp_identity_boot_wipe`): the wave's
  worktrees live under `<target>/.claude/.worktrees/wave-<id>/`. Idempotent re-attach on
  resume (reuse the branch, never `-b`); 3-point cleanup; prune branches not just worktrees.
- Deterministic hooks (pre-push test gate, secret gate) fire inside each worker — the
  Workflow orchestrates, it does not enforce.
- One wave per invocation. `/wavemachine` drives the campaign loop over waves.

### Troubleshooting: docs/config waves + the pre-push test gate (#724)

`scripts/hooks/workflow/pre-push-test-gate.sh` blocks `git push` unless a per-session
test sentinel exists. A **docs/config wave** runs no test suite, so reconcile's push to
`kahuna/<N>` had no sentinel and was blocked — and reconcile used to *silently* fall back
to local merge commits, stranding the wave's work off origin and emitting a degenerate
`kahuna→release` MR (`has_conflicts` / `no_merge_result_pr`) that can never promote.

Fixed two ways (#724): (1) the gate now **exempts integration refs** — a push whose
destination refs are all `kahuna/*` or `wave-*/*` exits 0 without a sentinel (those refs
are governed by the four-signal trust gate, not the session heuristic; protected-ref
pushes in the same session still gate). (2) reconcile now **fails loud** — a rejected
push returns `blocked` and HOLDs the wave (the `reconcile-blocked` exit), never a local
merge. **Recovery for a wave stranded by the old behavior:**
`PUSH_GATE_DISABLED=1 git push origin kahuna/<N>` to fast-forward origin, then re-trigger
the promotion MR's gate — fix-forward into the gate, not a bypass.

## Pair

- `/prepwaves` — plans the waves.
- **`/nextwave` — executes one wave via `per-wave-workflow.js`. This skill.**
- `/wavemachine` — drives the campaign loop, one per-wave Workflow per pending wave.
- `/dod` — verifies the project at Plan end.

Successor pairing mirrors the legacy `/prepwaves` → `/nextwave` → `/wavemachine` chain;
`-next` skills are the Dynamic-Workflows variants and do not modify the originals.
