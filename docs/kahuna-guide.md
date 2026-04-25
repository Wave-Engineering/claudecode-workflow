# KAHUNA Guide

Run `/wavemachine` autonomously on a multi-issue epic, walk away, come back to a merged epic on main. This guide is for engineers who want to use the KAHUNA integration-branch pattern in practice. For the architecture and rationale, see the [Dev Spec](kahuna-devspec.md).

---

## What KAHUNA Is

KAHUNA is a per-epic integration-branch pattern that lets `/wavemachine` ship a whole epic to `main` in one autonomous run. Instead of every Flight's MR/PR going to `main` and waiting on a human reviewer, all the Flights for an epic merge into a short-lived `kahuna/<epic-id>-<slug>` branch. When the epic is fully assembled and a four-signal trust score is green, the system opens a single kahuna→main MR/PR and auto-merges it.

The contract in one sentence: **MRs into kahuna are relaxed (CI-gated, no human review). MRs from kahuna into main retain full rigor — just gated by composable signals instead of per-MR human review.** Main's safety properties are unchanged.

```
                         ┌─────────────────────────────────────┐
                         │   You — invoke /wavemachine #N      │
                         └──────────────────┬──────────────────┘
                                            ▼
                         ┌─────────────────────────────────────┐
                         │   Orchestrator (top-level CC)       │
                         └──────────────────┬──────────────────┘
                                            │ spawns per wave
                                            ▼
                         ┌─────────────────────────────────────┐
                         │   Prime (per wave) — flight planner │
                         └─────┬───────────────────────────────┘
                               │ spawns per story
                               ▼
                ┌──────────────────────────┐
                │ Flight (per story)       │
                │ feature/<N>-xyz          │
                │ base = kahuna/<epic>-xyz │
                └──────────┬───────────────┘
                           │ MR auto-merges on CI-green
                           ▼
    ┌────────────────────────────────────────────────────────────┐
    │   kahuna/<epic>-xyz                                        │
    │   — accumulates every flight for the epic                  │
    │   — MRs in: no review, CI-gated                            │
    │   — MRs out: trust-score-gated                             │
    └──────────────────────┬─────────────────────────────────────┘
                           │ wave_finalize opens final MR
                           │ when epic complete + DoD passes
                           ▼
    ┌────────────────────────────────────────────────────────────┐
    │   main (production-visible, normal protections)            │
    │   — auto-merges iff all four trust signals are green       │
    └────────────────────────────────────────────────────────────┘
```

The four trust signals at the kahuna→main gate, evaluated in parallel:

1. `commutativity_verify` returns STRONG or MEDIUM on the composed kahuna-vs-main diff
2. CI on the kahuna branch reports success
3. `feature-dev:code-reviewer` finds zero critical or important issues on the composed diff
4. `trivy fs --scanners vuln --severity HIGH,CRITICAL` reports zero findings

Any red signal pauses the merge for your review. See [Procedure C](#what-happens-when-a-trust-signal-goes-red) below.

For the source of truth on the architecture see [`docs/kahuna-devspec.md`](kahuna-devspec.md) §4.1 (system context), §3.4 (trust-score gate), §4.4 (failure flows).

---

## When to Use It

Use KAHUNA when:

- The work decomposes into an **epic with multiple wave-pattern stories** — typically 3+ issues that can be planned, partitioned into flights, and executed serially or in parallel.
- The epic has been through `/devspec` and the backlog has been populated by `/devspec upshift`.
- You want to run `/wavemachine` for hours or overnight without babysitting individual MR/PR merges.
- The repo has KAHUNA settings applied (see [How to Enable](#how-to-enable-kahuna-on-a-new-project)).

Don't use KAHUNA for:

- **Single-issue fixes.** A one-off `fix/123-typo` does not need an integration branch. Just use the normal `/scpmr` flow.
- **Work without a Dev Spec.** KAHUNA assumes a finalized spec with a deliverables manifest the agents can verify against. No spec, no autonomy.
- **Long-lived integration branches.** A kahuna branch is short-lived (hours to days, not weeks). If your epic is so large that the kahuna branch would persist for a week, break it into phased sub-epics — see Dev Spec §2 CP-05.
- **Repos that haven't been configured for KAHUNA.** Without the platform-level "auto-merge into `kahuna/*`" guarantee, the autonomous run will stall at the first Flight MR. Convention is not enforcement.

---

## How to Enable KAHUNA on a New Project

KAHUNA needs a one-time per-repo configuration so the platform will auto-merge MRs targeting `kahuna/*` branches without human approval. The full procedure — settings to apply, automation tooling, prerequisite verification — lives in the dedicated deployment guide:

- **GitLab:** see `docs/kahuna-settings-deployment.md` (deployed via `gl-settings kahuna-sandbox` composite operation).
- **GitHub:** check `docs/kahuna-settings-deployment.md` for current GitHub support; at MVP, GitLab is the proving ground.

Don't try to apply settings by hand. The deployment guide is automation-driven precisely because manual clicks across N repos is how initiatives get abandoned (Dev Spec §2 CP-02).

---

## How to Invoke an Autonomous Run

Once your epic exists in the backlog and the target repo has KAHUNA settings applied:

```
/wavemachine
```

That's it. Pick the approved epic when prompted, or pass it directly:

```
/wavemachine 42
```

### Expected Behavior

`/wavemachine` runs an Orchestrator → Prime → Flight loop per the Wavemachine v2 protocol:

1. **Kahuna creation.** First wave: the Orchestrator detects no existing `kahuna_branch` in wave state and calls `wave_init` to create `kahuna/<epic-id>-<slug>` off the current main head. Wave state records the branch name.
2. **Wave execution.** The Orchestrator spawns a Prime per wave. Prime partitions the wave's stories into parallel-safe flights and spawns one Flight Agent per flight. Each Flight branches off kahuna, implements its story, runs `/precheck`, and auto-approves its own `/scpmmr` (sandbox auto-approval per Dev Spec §3.2 R-07).
3. **Per-flight auto-merge.** Each Flight's MR/PR targets kahuna and auto-merges as soon as CI is green — no human review required, by design.
4. **Final wave + gate.** When the last wave completes and Definition-of-Done checks pass, the Orchestrator invokes `wave_finalize`. That opens a kahuna→main MR/PR with an assembled body listing every flight that landed, and evaluates the four trust signals in parallel.
5. **Auto-merge to main.** All four signals green → `pr_merge(skip_train=true)`. The kahuna branch is deleted (per R-03). Wave state records the disposition in `kahuna_branches` history.
6. **Notifications.** Discord `#wave-status` gets an embed with phase/wave/action/flight progress and a color-coded status sidebar. On final merge, you get a `#wave-status` message and a vox announcement summarizing the epic, merged-flight count, and final commit SHA.

### Reading the Notifications

While the run is in flight, watch:

- **Discord `#wave-status`** — single embed per project, edited in place. Shows phase, current wave, action label, current flight, progress bar, and any deferrals. Color-coded sidebar maps to action state (planning, flight, gate_evaluating, gate_blocked, complete, failed).
- **vox announcements** — speech for major transitions (wave done, gate blocked, epic merged). Best-effort; skipped silently if not configured.
- **`wave-status show`** — CLI snapshot. Displays the active kahuna branch, merged-flight count, pending-flight count, and the trust-signal summary for the eventual gate.

If `#wave-status` shows action `gate_blocked`, see the next section.

---

## What Happens When a Trust Signal Goes Red

The kahuna→main gate evaluates four signals concurrently. If any one returns a non-passing result, the run pauses — it does **not** abandon the epic, **does not** merge anyway, **does not** delete the kahuna branch. The sequence (Dev Spec §4.4.4 Procedure C):

1. Orchestrator captures all four signal results, even after one fails (so you get the complete picture, not a short-circuited one).
2. Wave state transitions `action` → `gate_blocked`. The failing signals and their detail payloads are recorded.
3. Discord `#wave-status` gets a message with: epic name, each failing signal's name and detail, the kahuna branch name, and the open kahuna→main MR/PR URL.
4. vox announces: *"Kahuna gate blocked for epic X. N signals red. Ready for your review."*
5. The Orchestrator exits the loop. The kahuna branch is preserved. The kahuna→main MR/PR stays open and un-merged.

### How to Resume

You have three paths:

| Path | When to use it | What you do |
|------|----------------|-------------|
| **Fix and re-gate** | A real problem in the composed diff (failing tests, code-reviewer findings, trivy vuln, commutativity drift) | Fix the underlying issue. For commutativity drift, that often means merging `main` into the kahuna branch. Re-run `/wavemachine` at the epic level — R-02 reuse detects the unresolved state and resumes at the gate. |
| **Override and merge** | The signal is a false positive you've reviewed and accepted | Merge the kahuna→main MR/PR manually via the platform UI. Wave state will reconcile on the next `/wavemachine` invocation. |
| **Abandon the epic** | The epic is fundamentally wrong | Delete the kahuna branch (`git push origin --delete kahuna/<epic>-<slug>`), clear `kahuna_branch` from wave state. There is no automated abandon flow in MVP. |

The "fix and re-gate" path is idempotent: calling `wave_finalize` on an epic whose kahuna→main MR/PR already exists detects it via `pr_list` and re-evaluates the gate against the existing MR rather than opening a new one.

### Other Failure Modes

`#wave-status` shows other action states for non-gate failures. The full catalog is in Dev Spec §4.4:

- **`failed` after a flight validation failure** — Procedure A. Inspect the flight's `results.md` in the wavebus, fix in the worktree, re-run `/wavemachine`.
- **`failed` after a flight rebase conflict** — Procedure B. Resolve the conflict manually in the flight's worktree, push, re-run.
- **Crash mid-epic (Orchestrator exits abnormally)** — Procedure D. Re-run `/wavemachine`; wave state and the kahuna branch persist on disk and on the platform, and R-02 reuse picks up where the crash hit.

---

## Team-Member Coexistence (FAQ)

> *"My teammate is going to push to main while I run `/wavemachine` overnight. Will it break their flow? Will it break the run?"*

No, on both counts. KAHUNA is designed to be invisible to non-wave contributors — Dev Spec §1.5 non-goals and §2 CP-01 make this an explicit constraint.

**For the non-wave contributor:**

- Their MR/PR lands on main as normal — full review, full merge queue, full protections. KAHUNA settings on `kahuna/*` branches do not affect the main-target workflow.
- They don't see kahuna in their MR-create dropdowns (the UI defaults to main as base).
- They don't need new permissions, new tooling, new mental model. They keep working as before.

**For the wave run:**

- When the next Flight Agent creates its branch, the Flight branches off kahuna — not off main. The Flight's work is isolated from the main drift caused by the teammate's commit.
- The next Flight's MR/PR merges into kahuna, not main. No interaction with the teammate's commit happens until the kahuna→main gate at epic close.
- At the gate, `commutativity_verify` computes the composed diff against the **current** main HEAD (not a snapshot from when kahuna was created), so the teammate's commit is part of the analysis.
- If main has drifted enough that commutativity returns WEAK or ORACLE_REQUIRED, the gate goes red and you handle the reconciliation per [Procedure C above](#what-happens-when-a-trust-signal-goes-red) — typically by merging main into kahuna and re-running the gate. This is intentional: the gate exists precisely to catch this case.

The key property: the wave run and the teammate's normal work don't have to coordinate. Each side does its thing; the gate catches the integration question.

> *"What about CI cost? Are kahuna branches racking up pipeline minutes?"*

Each Flight MR triggers CI on the Flight's branch and on kahuna (the merge target) — same as any normal MR. The kahuna→main MR triggers one more CI run on kahuna's tip before the gate evaluates. So per epic, CI cost is roughly `N + 1` runs where N is the flight count. No worse than N normal MRs.

> *"Can I run two `/wavemachine` invocations on the same epic at once?"*

No. Dev Spec §2 CP-03: only one active run per epic. The skill detects an existing unresolved kahuna branch and refuses to start a second run (R-20). If you want to abandon a run mid-flight, follow the manual abandon path above.

> *"Can I push to a kahuna branch directly?"*

You can, but you shouldn't. The branch is owned by the wave run. If you want to fix something in-flight, do it in the relevant Flight's worktree (the wavebus exposes the path) and let the Flight push. Direct pushes to kahuna risk fighting the Orchestrator's reconciliation.

---

## Pointers

- **Architecture deep-dive:** [`docs/kahuna-devspec.md`](kahuna-devspec.md) — full Dev Spec including requirements, design, test plan, and VRTM.
- **Wavemachine v2 reference:** [`docs/wavemachine-v2-integration.md`](wavemachine-v2-integration.md) — Orchestrator/Prime/Flight protocol, filesystem bus, status-line contract.
- **Onboarding tour:** run `/ccwork tour workflow` for the standard Issue → Branch → Code → Precheck → Ship loop. The KAHUNA-specific tour section will be added in `tours/sdlc.md` (forthcoming).
- **Concepts:** [`docs/concepts.md`](concepts.md) — how skills, scripts, and settings fit together.
- **Getting started:** [`docs/getting-started.md`](getting-started.md) — first-session walkthrough; KAHUNA is the next step after that loop is comfortable.
