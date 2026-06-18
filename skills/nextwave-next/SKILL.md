---
name: nextwave-next
description: Execute one wave via the per-wave Workflow — the §3 spine (rehydrate → dynamic flight loop → trust gate → promote) as a deterministic JS Workflow, not an LLM orchestrator
---

# NextWave-Next — Execute One Wave via the per-wave Workflow

> **Migration successor to `/nextwave`.** This is the Dynamic-Workflows shape of the
> per-wave primitive: the orchestrator's deterministic control flow is moved into a
> JS Workflow script, and the LLM is called only for the steps that genuinely need
> judgment (plan / implement / reconcile / review). The old `/nextwave`
> (Orchestrator/Prime/Flight on a filesystem bus) is unchanged and stays in place during
> migration. Design of record: `docs/wavemachine-workflows-migration.md`.
>
> **Source vs. runnable artifact (live-gate finding #2):** a Dynamic Workflow must be ONE
> self-contained file with `export const meta` first — cross-file `import`s do NOT run as a
> Workflow. So the engine's tested halves live in modules (`per-wave-workflow.js` +
> `wave-status.js`/`resume.js`/`gate.js`) and `bundle.mjs` inlines them into the single-file
> artifact **`per-wave-workflow.bundled.js`** — the file the Workflow tool actually invokes.
> Edit the source modules, then `node skills/nextwave-next/bundle.mjs`; a regression test
> (`test_bundle_in_sync.sh`) fails if the committed bundle drifts from its source.

## Axioms

Bound by WAVE_AXIOMS 2, 3, 4, 5, 6, 8, 9 (`WAVE_AXIOMS.md` at the repo root). The
closed-list legal-exits enumeration, the Concerns Channel pressure valve, the
cost-asymmetry default-forward stance, the approval-frequency rule, and the
user-attention-as-cost framing live in that file. In this successor those axioms are
no longer prose the orchestrator must remember — they are **loop guards in the
Workflow script it cannot forget or override** (`per-wave-workflow.js`, §3.1). When
justification prose seems missing, it is in `WAVE_AXIOMS.md` by design.

## What this is

`/nextwave-next` runs **one** Workflow — `per-wave-workflow.js` — for a single wave.
That script IS the §3 spine:

```
rehydrate (durable resume)
   → flight loop  [ serial groups; parallel issues; dynamic re-plan; CLOSED legal exits ]
       per group:  plan(Prime) → parallel issue-workers → merge+reconcile(Prime)
   → trust gate   [ 4 signals in parallel → one more legal exit ]
   → promote (kahuna→protected)  OR  hold-for-review
```

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

Supplied by the caller (`/wavemachine-next` per wave, or a human launching one wave):

| Field | Meaning |
|---|---|
| `waveId` | the wave id (e.g. `W-3`) |
| `issues` | the wave's issue numbers (one repo — single-repo-per-wave axiom, §4.1). **Required, non-empty.** |
| `targetRepo` | `owner/repo` for `gh -R` scoping |
| `targetRepoDir` | the clone the durable worktrees attach to (§4.2) |
| `kahunaBranch` | the integration target; every flight PR targets this, never the protected branch |
| `protectedBranch` | the promotion target on the success exit |
| `mode` | `auto` (verdict drives promotion) \| `interactive` (verdict returned; human routes) |
| `planId` | wave plan id — the gate's PR-open node needs it to assemble the kahuna→protected MR body (#687/#5) |
| `budget` | optional `{ total, remaining() }` cost guard (the `cost` legal exit) |

The closed numeric guards (`maxGroups`, `maxRework`, `maxIdle`, `costFloor`) have
safe defaults in the script and rarely need overriding.

## Procedure

1. **Resolve wave inputs.** Read the next pending wave for this Plan (`wave_next_pending`),
   its issue list, the `kahuna_branch` (always populated — `/wavemachine-next` bootstraps it
   at Plan launch), the target repo + clone dir, and the protected branch (from
   `.claude-project.md`). Refuse if `kahuna_branch` is unset — wave state was not
   bootstrapped through the campaign launch sequence.
2. **Validate specs.** Confirm every wave issue is structurally buildable
   (`spec_validate_structure`). Any INVALID → report and exit (not an error — a Legal Exit).
3. **Launch the Workflow.** Invoke the single-file artifact `per-wave-workflow.bundled.js`
   (via the Workflow tool's `scriptPath`) with the inputs above passed as **`args` (a JSON
   object)**. The script owns everything from here: rehydrate → flight loop → trust gate (which
   opens the kahuna→protected DRAFT PR first, then runs the four signals on it, #5) → promote.
4. **Consume the verdict.** The Workflow's return is the per-wave gate (§5): a Workflow
   cannot pause mid-run for human input, so its *ending with a verdict* IS the gate. The
   return carries `gate` ∈ `PASS | HOLD | SKIPPED` **and** `promoted` ∈ `true | false`, plus
   `concerns`/`deferrals` (informational — surfaced and continued, never halted-on). **`gate`
   and `promoted` are distinct facts** — read both:
   - `auto` + `{ gate:'PASS', promoted:true }` ⇒ the Workflow's promote node landed the
     kahuna→protected merge. The wave is DONE on the protected branch. Report it.
   - `auto` + `{ gate:'PASS', promoted:false }` ⇒ the gate passed but the promote node
     **soft-failed — the merge did NOT land** (the wave is recorded HELD; `reason` carries the
     promote error). The code is sound but not on the protected branch → surface as a HOLD for
     manual promotion, NOT as success. (Promotion can be retried on resume — the kahuna branch
     is gate-clean.)
   - `interactive` + `{ gate:'PASS', promoted:false }` ⇒ by design the Workflow never
     auto-promotes; surface the verdict + the kahuna→protected diff and STOP for the human, who
     routes promotion. When the human lands the kahuna→protected merge, the wave's terminal
     disposition is updated to `promoted` in wave-status — that durable record is what
     `/wavemachine-next`'s interactive branch reads (`waveDisposition`) to advance, so it never
     advances on the operator's word alone. (`/wavemachine-next` owns this branch in a campaign.)
   - `{ gate:'HOLD' }` / `{ gate:'SKIPPED' }` (always `promoted:false`) ⇒ a trust signal failed
     or the flight loop hit a HOLD exit before the gate; surface the failing signals / halt reason.
5. **Report.** Surface a human-readable summary: groups run, issues merged, any HOLD
   reason, collected concerns/deferrals. Post wave status to `#wave-status` if running
   under a campaign.

## What is REAL vs SEAM in the Workflow

`per-wave-workflow.js` is the **anchor**: the loop / exits / re-plan / gate fan-out are
real and complete (the validated pilot shape, hardened). The sdlc-server tool calls the
agents make are **seams**, marked with `// TODO(#…)` and backed by obvious-placeholder
stubs so the skeleton runs end-to-end. The seam contracts live in
`skills/nextwave-next/SEAMS.md`:

- **#686** — rehydrate / idempotency (durable resume, worktree setup/cleanup)
- **#687** — real gate signals via sdlc-server (commutativity / CI / review / trivy + promote)
- **#688** — wave-status persistence (the durable resume substrate)

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
| success | `pending` empty | all issues merged to kahuna → trust gate runs |
| runaway | `groupsRun ≥ MAX_GROUPS` | too many groups → human review |
| thrash | `idleRounds ≥ MAX_IDLE` | groups with zero net merges → not converging |
| cost | `budget` floor | stop before the ceiling |
| impasse | planner `done` with pending left | planner can't schedule remaining → human |
| per-issue breaker | issue reworked > `MAX_REWORK` | one issue keeps breaking → human |
| gate HOLD | a trust signal failed | post-success gate fired → human review |

Unease that matches none of these is NOT an exit: it rides the `concerns[]` channel
(Axiom 4) and the loop continues. The dynamic-flight insight: a dependency that surfaces
mid-wave (reported by reconcile as `needs_rework`) re-opens the issue and becomes the
next group — **no human halt**. That is the failure class the LLM-orchestrator kept
stalling on (#78/#79/#90), now expressed as bounded control flow.

## Non-Negotiables

- EXECUTION primitive — NO design decisions. Workers are SPEC EXECUTORS.
- **NEVER merge directly to the protected branch.** Flight PRs target the kahuna branch;
  the kahuna→protected merge is the only path to the protected branch and is gated by
  the four-signal trust gate (§3.4).
- **Single-repo per wave** (§4.1) — a wave resolves to exactly one `target_repo`.
- **Durable worktrees, not `/tmp`** (§4.2, `lesson_tmp_identity_boot_wipe`): the wave's
  worktrees live under `<target>/.claude/.worktrees/wave-<id>/`. Idempotent re-attach on
  resume (reuse the branch, never `-b`); 3-point cleanup; prune branches not just worktrees.
- Deterministic hooks (pre-push test gate, secret gate) fire inside each worker — the
  Workflow orchestrates, it does not enforce.
- One wave per invocation. `/wavemachine-next` drives the campaign loop over waves.

## Pair

- `/prepwaves` — plans the waves.
- **`/nextwave-next` — executes one wave via `per-wave-workflow.js`. This skill.**
- `/wavemachine-next` — drives the campaign loop, one per-wave Workflow per pending wave.
- `/dod` — verifies the project at Plan end.

Successor pairing mirrors the legacy `/prepwaves` → `/nextwave` → `/wavemachine` chain;
`-next` skills are the Dynamic-Workflows variants and do not modify the originals.
