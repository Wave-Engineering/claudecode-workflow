<!-- DEV-SPEC-APPROVAL
approved: true
approved_by: bakerb
approved_at: 2026-04-24T10:27:26Z
finalization_score: 7/7
-->

# Kahuna — Development Specification

**Version:** 1.0
**Date:** 2026-04-24
**Status:** Draft
**Authors:** bakerb, rules-lawyer 📜 (cc-workflow)

---

## Table of Contents

1. [Problem Domain](#1-problem-domain)
2. [Constraints](#2-constraints)
3. [Requirements (EARS Format)](#3-requirements-ears-format)
4. [Concept of Operations](#4-concept-of-operations)
5. [Detailed Design](#5-detailed-design)
   - [5.A Deliverables Manifest](#5a-deliverables-manifest)
   - [5.B Installation & Deployment](#5b-installation--deployment)
6. [Test Plan](#6-test-plan)
7. [Definition of Done](#7-definition-of-done)
   - [7.2 Dev Spec Finalization Checklist](#72-dev-spec-finalization-checklist)
8. [Phased Implementation Plan](#8-phased-implementation-plan)
9. [Appendices](#9-appendices)

---

## Terminology

This spec — and the wave-pattern pipeline it describes — distinguishes **six primitives**. Five are pipeline-native; the sixth (Epic) is a PM-layer concept the pipeline deliberately ignores. Every later section of this document uses these terms in exactly this sense. When an older reader encounters "epic" in pipeline-operational prose, that is a taxonomy leak (see `docs/phase-epic-taxonomy-devspec.md`); report it.

| Primitive | What it is | Where it lives | Relation | Non-relation |
|-----------|-----------|----------------|----------|--------------|
| **Plan** | Top-level container for a multi-Phase delivery. One Plan → one kahuna branch → one kahuna→main MR. Synthetic pipeline primitive. | Platform issue with `type::plan` label; `plan_id` = issue number. Decision Ledger lives in its comments. | A Plan contains one or more Phases. A Plan maps 1:1 to a kahuna branch `kahuna/<plan_id>-<slug>`. | A Plan is **not** a GitHub/GitLab native Milestone, Projects V2 item, GitLab Epic, or Iteration — those are PM-layer primitives left alone. A Plan is **not** a `type::epic` issue. |
| **Phase** | Sequential pipeline-internal ordering unit within a Plan. Phases run in order; waves within a Phase may run in parallel. | `phases-waves.json` (pipeline-only); checklist item in the Plan issue body. | A Phase belongs to exactly one Plan. A Phase contains one or more Waves. | A Phase is **not** a platform issue, label, milestone, or branch. It has no native representation; it exists only in pipeline state. |
| **Wave** | A parallel-safe batch of Stories executed as a unit by Prime + Flight agents. All Stories in a Wave land on the kahuna branch before the next Wave begins. | `phases-waves.json` (pipeline-only); `wave_N` keys in wave state. | A Wave belongs to exactly one Phase. A Wave contains one or more Flights (one Flight per Story). | A Wave is **not** a platform primitive. It has no issue, no label, no branch. |
| **Story** | The unit of implementable work — one issue, one branch, one MR, one Flight. Lands one coherent change on the kahuna branch. | Native platform issue with `type::feature`, `type::bug`, `type::chore`, or `type::docs`. | A Story belongs to exactly one Wave (implicitly, via `phases-waves.json`). A Story may optionally carry an `epic::N` PM-layer label. | A Story is **not** a Plan, even if single-Story Plans exist; the Plan issue is a distinct tracker. |
| **Flight** | Ephemeral runtime agent + worktree + wavebus slot that implements exactly one Story. Returns `PASS`/`FAIL` on the canonical status line. | `/tmp/wavemachine/<slug>/wave-<N>/flight-<M>/` + a git worktree + a feature branch based on the active kahuna branch. | A Flight maps 1:1 to a Story. A Flight opens its MR with `base = <active-kahuna-branch>`. | A Flight is **not** persisted in platform state. Post-completion, only its MR and the wavebus artifact remain; the worktree and agent are torn down. |
| **Epic** | **PM-layer concept only.** Either a `type::epic` parent tracker issue (used by humans for thematic grouping), or an `epic::N` label on Story issues. The pipeline reads neither, filters by neither, and never branches control flow on either. | Optional. Lives on the platform as a `type::epic` issue or as an `epic::N` label on Stories. | An Epic is a PM-facing grouping that **may** span Stories across multiple Plans or none at all. | An Epic is **not** a Plan, a Phase, a Wave, a Story, or a Flight. Any pipeline code that reads `epic::N` or routes on `type::epic` is a taxonomy leak (see `decision_plan_phase_epic_taxonomy.md`). The kahuna branch name uses `<plan_id>`, never an epic identifier. |

**Historical note:** prior versions of this Dev Spec used "epic" in pipeline-operational contexts (e.g., "per-epic integration branch", `epic_id` handler parameters, `kahuna/<epic-id>-<slug>` branch naming). Those usages have been renamed to "Plan" throughout. See `docs/phase-epic-taxonomy-devspec.md` for the rationale and the one-time rename scope.

---

## 1. Problem Domain

### 1.1 Background

The Claude Code Workflow Kit ships a wave-pattern execution system — `/assesswaves`, `/prepwaves`, `/nextwave`, `/wavemachine`, `/dod` — that decomposes a Plan into waves of parallel-safe "flights," each implementing one Story in its own worktree. Wavemachine v2 (shipped 2026-04-23, Plan #384 — tracked historically under the `type::epic` label before the Plan/Phase/Epic taxonomy landed) restructured this around an Orchestrator / Prime / Flight model with a filesystem message bus at `/tmp/wavemachine/`, circuit-breakers via `wave_health_check`, and a canonical status-line protocol so Flights return `PASS`/`FAIL` to Primes to the Orchestrator without the Orchestrator needing to read each Flight's output.

The system was conceptually designed for three progressively autonomous operating modes (Tier 1: agent executes, human merges; Tier 2: agent merges individual changes, human gates the Plan; Tier 3: fully autonomous end-to-end with trust-score-based auto-merge at main). Today the kit operates at Tier 1 only. **Tier 3 is the destination for this Plan.** Tier 2 is referenced in the Phased Implementation Plan (§8) as an intermediate checkpoint during development — it is not a shipping configuration. Once Tier 3 is built, it is the only mode the kit runs in.

The sdlc-server has most of the trust-signal infrastructure required for Tier 3 (`commutativity_verify` returning STRONG/MEDIUM/WEAK/ORACLE_REQUIRED verdicts, `wave_ci_trust_level`, `skip_train` bypass flag on `pr_merge`), but no mechanism exists to route flights away from main or to act on the trust signals without human intervention.

### 1.2 Problem Statement

`/wavemachine` cannot deliver on its core promise today because every Flight's MR requires human approval to merge. Three distinct gates stack against autonomy:

1. **CLAUDE.md mandatory rule** — `/precheck` STOPs before any commit and refuses autonomous approval. Sub-agents cannot approve themselves.
2. **Platform enforcement** — GitHub repos in the Wave-Engineering org have `enablePullRequestAutoMerge: false` and merge-queue strategies; GitLab repos in `analogicdev/*` have branch-name regexes, `commit_committer_check`, and varying review-approval requirements. Any single one blocks autonomous merge.
3. **Branch protection** — if "require pull request reviews" is enabled on the target branch, the agent cannot merge even if it wanted to.

As a result, an overnight `/wavemachine` run stalls at the first Flight that completes, waits for human input, and the autonomous-execution premise collapses. The user ends up batching N reviews at the first morning session anyway, so wavemachine bought nothing except asynchrony of *execution* — not of *integration*.

Relaxing all three gates at the main-branch level is not acceptable. Main is the shipped, production-visible state. The safety properties those gates enforce — human review, CI-green-before-merge, audit trail, conflict resolution at the integration point — must hold for anything landing on main.

### 1.3 Proposed Solution

Introduce a per-Plan **integration branch** called "Kahuna" that lives between individual Flight branches and main. For each Plan processed by the wave-pattern pipeline:

1. `wave_init` creates a `kahuna/<plan-id>-<slug>` branch off the current main head and records it in wave state.
2. Per-flight sub-agents branch off kahuna, not main (`feature/<story-id>-<slug>` with `kahuna/<plan-id>-<slug>` as base ref).
3. Flight MRs target kahuna as their integration branch. The platform is configured such that MRs **into** kahuna merge automatically on CI-green with zero human approval required — the "sandbox" property: kahuna is pre-main staging, not production-visible state.
4. When all stories in the Plan are merged to kahuna and Definition-of-Done checks pass, a new `wave_finalize` tool opens a kahuna→main MR with an auto-assembled body derived from wavebus artifacts (one bullet per flight, linking the original flight MRs).
5. The kahuna→main MR auto-merges when all trust signals are satisfied: `commutativity_verify` reports STRONG or MEDIUM on the composed diff (kahuna vs main), CI on kahuna is green, the `feature-dev:code-reviewer` agent reports no critical or important findings, and `trivy fs` reports zero HIGH/CRITICAL vulnerabilities. Any red signal pauses for human review. There is no per-repo "tier knob" — this is the only mode; degraded-signal fallback to human is automatic, not configured.

What is missing on the sdlc-server side is narrower than it first appears. `pr_create` already accepts a custom `base` ref — flights can target `kahuna/*` today with no plumbing changes. `pr_merge` derives base from the PR itself (set at creation time) and needs no modifications. The actual gaps are: a new `wave_finalize` tool that assembles and opens the kahuna→main MR from wavebus artifacts; a wave-state schema addition for the `kahuna_branch` field; a schema relaxation on `commutativity_verify` so it can gate a single composed kahuna-vs-main diff (today it requires pairwise changesets, min 2 — the underlying `commutativity-probe` binary handles single-target analysis already, only the handler enforces pairwise); and kahuna branch lifecycle primitives (`wave_init` creating the branch, cleanup on Plan close). Outside the sdlc-server surface: per-platform settings automation to establish sandbox properties on kahuna branches, and a `/precheck` adaptation that recognizes "Flight operating inside a Kahuna sandbox" and auto-approves its own `/scpmmr` within that context.

The critical invariant: **MRs into kahuna are relaxed; MRs from kahuna to main retain full rigor — just with a different gating source (trust signals rather than human per-MR).** Main's safety properties are unchanged. The gate moves from "per flight at main" to "one at Plan-close, against the assembled whole, validated by composable signals."

### 1.4 Target Users

| Persona | Description | Primary Use Case |
|---|---|---|
| **BJ (wave-driver)** | Engineer running `/wavemachine` for overnight or long-running autonomous execution on multi-issue Plans. Starts the wave, walks away, evaluates state on return. | Invoke `/wavemachine` on an approved Plan; audit the already-merged-by-trust-score Plan on return (or resume a paused wave when a trust signal went red). |
| **tachikoma (sdlc-server maintainer)** | Dev owning the mcp-server-sdlc tool surface. Implements `wave_finalize`, wave-state schema additions, `commutativity_verify` schema extension. | Consumes the Dev Spec Section 5 tool contracts, delivers against them in parallel with BJ's claudecode-workflow work. |
| **Orchestrator Agent** | Main interactive agent (the top-level Claude Code session). Runs the `/wavemachine` loop. | Reads wave state, spawns Prime agents per wave, consumes canonical status returns, drives the Plan from `wave_init` through `wave_finalize` and cleanup. |
| **Prime Agent** | First agent created per wave. Manages flight planning, flight input/output, and post-wave reconciliation. | Pre-wave: partition stories into parallel-safe flights, generate flight prompts, kick off flights. Post-flight: reconcile results. Post-wave: prepare wavebus artifacts for the Orchestrator's next decision. |
| **Flight Agent** | Sub-agent given a single, specific user story and tasked with implementing it. | Branches off kahuna, implements the story in a worktree, commits, pushes, opens an MR targeting kahuna, self-approves `/scpmmr` because it is operating inside a Kahuna sandbox. |
| **Team members (non-wave contributors)** | Engineers working in the same repos via conventional `feature/...`, `fix/...` branches directly to main. | Continue working normally. Their MRs go to main, do not interact with kahuna branches, do not see kahuna in their daily flow unless they happen to look at `git branch -a`. |

### 1.5 Non-Goals

- **Not a main-branch safety relaxation.** Main's existing protection, review requirements, and merge rules are unchanged. Everything this spec introduces happens below main or at the single gate-point of kahuna→main.
- **Not a replacement for `/precheck` discipline.** `/precheck` still runs inside Flight sub-agents. What changes is the *post-checklist* approval step — it auto-approves within a Kahuna sandbox instead of STOP-and-wait. The checklist itself, the code-reviewer agent, the trivy scan, the validation run — all still happen.
- **Not a mechanism to merge code without CI.** Every Flight MR to kahuna is gated by CI passing. The kahuna→main MR is gated by CI on kahuna passing. There is no path that merges code without CI.
- **Not a cross-Plan trunk.** Kahuna is per-Plan, created fresh from main at Plan start, destroyed after Plan close. It is not a long-lived integration branch like `develop`. No state persists from one Plan to the next on kahuna.
- **Not a substitute for code review of individual changes.** The `feature-dev:code-reviewer` sub-agent still runs on each Flight's changes inside `/precheck`. In Tier 3, the code-reviewer-agent-clean signal is a required input to the trust score for the kahuna→main auto-merge. Code review does not disappear — it moves from gating to signaling.
- **Not a GitLab-only or GitHub-only pattern.** The design is platform-neutral. MVP proof is GitLab (the 29 projects already widened), but the sdlc-server tool surface must work equivalently on both. Platform-specific settings automation lives outside the core spec.

---

## 2. Constraints

### 2.1 Technical Constraints

| ID | Constraint | Rationale |
|----|-----------|-----------|
| **CT-01** | Main branch safety properties are inviolable. Existing branch protection, required-reviews rules, merge-queue configuration, and push restrictions on main must persist unchanged. KAHUNA may only relax rules on `kahuna/*` branches, never on main. | Main is the shipped, production-visible state. Teams outside the wave-pattern workflow depend on its current safety guarantees. The whole point of the integration-branch pattern is to move autonomy below main, not to weaken main itself. |
| **CT-02** | Platform-neutral design. The sdlc-server tool surface (`wave_finalize`, modified `commutativity_verify`, existing `pr_create`/`pr_merge`) must work identically against GitHub and GitLab. Platform-specific differences live in settings automation, not in the core spec. | The wave-pattern kit is already dual-platform. Introducing tool-level platform drift would bifurcate the whole pipeline and destroy the "one spec, two ecosystems" property that makes it maintainable. |
| **CT-03** | No regressions to Wavemachine v2 infrastructure. The filesystem bus (`/tmp/wavemachine/`), the Orchestrator/Prime/Flight protocol, the canonical `PASS`/`FAIL` status-line contract, and `wave_health_check` circuit-breakers must continue to function unchanged when KAHUNA is not in use, and must interoperate with KAHUNA cleanly when it is. | Wavemachine v2 (Plan #384, tracked under the legacy `type::epic` label pre-taxonomy) shipped 2026-04-23 and is in use today. Regressing it to ship KAHUNA would leave the kit worse off on the way to a theoretically better end state. |
| **CT-04** | Existing sdlc-server tool surface must be preserved where it already suffices. `pr_create` and `pr_merge` have the behavior KAHUNA needs — do not modify them. New capability goes in new tools (`wave_finalize`) or narrow schema extensions (`commutativity_verify` min-changeset relaxation). | Per tachikoma's §1 review: touching working tools introduces risk without benefit. The principle is additive, not transformative. Consumer skills that already call these tools in Tier-1 contexts must see no behavioral change. |
| **CT-05** | Kahuna branch lifecycle must be fault-tolerant. A crash, network failure, or agent exit during wave execution must not leave the target project in a state that blocks the next wave run. Specifically: orphaned kahuna branches from a failed wave must be identifiable and cleanable without corrupting state. | BJ runs `/wavemachine` overnight. If a wave crashes at 3 AM and leaves `kahuna/42-foo` half-populated with no cleanup path, the next morning's work is blocked. The persist-on-abort decision (§1.5) makes this constraint concrete: "persist" is only safe if there's a defined way to resume or abandon. |
| **CT-06** | Every Flight MR into kahuna must be gated by CI passing before auto-merge. The sandbox property does not mean "skip CI" — it means "don't require humans." | This is the guardrail that prevents the sandbox from becoming a dumping ground. CI is non-negotiable. Any path that merges to kahuna without CI is a bug. |
| **CT-07** | Flight Agents must commit with an author/committer email verified on the agent's platform account. | Observed on blueshift-devkit during branch-naming recon: `commit_committer_check: true` rejects pushes when the git committer email differs from a verified email on the GitLab user. Projects with this rule enabled will reject every Flight MR unless the agent manages its identity correctly. This is an integration reality, not a goal. |

### 2.2 Product Constraints

| ID | Constraint | Rationale |
|----|-----------|-----------|
| **CP-01** | Invisible to non-wave contributors. Engineers using conventional `feature/`, `fix/`, `chore/`, `doc/` branches against main must see no change to their workflow. They should not need to understand kahuna to continue working normally. | The kit is used by humans and agents side-by-side. A pattern that forces every teammate to learn new rules just to keep pushing their regular code would be rejected on social grounds regardless of technical merit. |
| **CP-02** | Per-project settings configuration required for KAHUNA to function must be deployable via `gl-settings` (GitLab) or equivalent automation. No manual per-repo configuration. | 29 GitLab projects today; target set grows as more teams adopt. Manual settings clicks across dozens of repos is how initiatives get abandoned. If it can't be automated, it can't ship at the scale needed. |
| **CP-03** | Only one active `/wavemachine` run per Plan at a time. A second run cannot start against the same Plan while a prior run's kahuna branch is unresolved (not merged, not abandoned). | Two concurrent wavemachine runs racing on the same kahuna branch would produce corrupted state, lost commits, and untrackable merges. This is a "don't hold it wrong" constraint — the skill must detect and refuse the collision. |
| **CP-04** | The Kahuna sandbox property must be enforceable by the platform — not by convention. If a target platform cannot enforce "auto-merge MRs into `kahuna/*` without review," KAHUNA does not work on that platform. | The whole trust model depends on the platform-level guarantee that kahuna is sandboxed. If that's just "please don't review kahuna MRs too hard," someone will eventually review one and block it, and the autonomous wave run stalls indefinitely. Convention is not enforcement. |
| **CP-05** | Kahuna branches are short-lived (hours to days, not weeks). Projects with long-running Plans must break them into Phases (or split into successor Plans) rather than maintaining a kahuna branch for extended periods. | Long-lived integration branches accumulate merge conflicts against main, create stale-CI problems, and blur the "atomic Plan delivery" property. Capping kahuna lifetime is a product-level forcing function to keep Plans well-scoped. Enforced by convention + `wave_health_check` staleness warning, not hard-blocked. |

---

## 3. Requirements (EARS Format)

Requirements follow the **EARS** notation:

- **Ubiquitous**: The system shall [function].
- **Event-driven**: When [event], the system shall [function].
- **State-driven**: While [state], the system shall [function].
- **Optional**: Where [feature/condition], the system shall [function].
- **Unwanted**: If [unwanted condition], then the system shall [function].

### 3.1 Branch Lifecycle

| ID | Type | Requirement |
|----|------|-------------|
| **R-01** | Event-driven | When `/wavemachine` is invoked on an approved Plan that has no existing active kahuna branch recorded in wave state, the system shall create a branch named `kahuna/<plan-id>-<slug>` off the current main head and record it in wave state. |
| **R-02** | Event-driven | When `/wavemachine` is invoked on an approved Plan that already has an active kahuna branch recorded in wave state, the system shall reuse the existing branch and resume wave execution against it. |
| **R-03** | Event-driven | When `wave_finalize` successfully auto-merges the kahuna→main MR, the system shall delete the kahuna branch from the target platform. |
| **R-04** | Unwanted | If `/wavemachine` aborts mid-Plan due to crash, interrupt, signal failure, or trust-signal rejection, then the system shall preserve the kahuna branch in its current state and transition the existing wave-state action label (used for stages like `planning`, `flight`) to reflect the abort. |

### 3.2 Flight Integration

| ID | Type | Requirement |
|----|------|-------------|
| **R-05** | Ubiquitous | The Flight Agent shall branch its implementation work from the active kahuna branch, not from main. |
| **R-06** | Ubiquitous | The Flight Agent shall open its merge request with `base = <active-kahuna-branch>`, not `base = main`. |
| **R-07** | State-driven | While a Flight Agent is operating inside a Kahuna sandbox (its branch base ref matches the `kahuna/*` pattern), `/precheck` shall auto-approve the Flight's own `/scpmmr` after completing the full checklist (validation, code-reviewer, trivy, notifications) with no STOP-and-wait step. |

### 3.3 Platform Enforcement

| ID | Type | Requirement |
|----|------|-------------|
| **R-08** | State-driven | While a `kahuna/*` branch exists on a project with KAHUNA configuration applied, the platform shall allow merge requests targeting that branch to auto-merge on CI-green with zero human approval required. |
| **R-09** | Ubiquitous | Merge requests targeting main from a `kahuna/*` source branch shall be gated by the trust-score requirements defined in §3.4. |
| **R-10** | Ubiquitous | The branch-naming rules on the target platform shall accept `kahuna/<plan-id>-<slug>` patterns alongside existing accepted prefixes. |

### 3.4 Trust-Score Gate

| ID | Type | Requirement |
|----|------|-------------|
| **R-11** | Event-driven | When the final flight of a Plan successfully merges to kahuna and all Definition-of-Done checks defined in §7 pass, the system shall invoke `wave_finalize` to open a kahuna→main MR with an auto-assembled body summarizing all flights. |
| **R-12** | Ubiquitous | Before the kahuna→main MR auto-merges, `commutativity_verify` shall report a verdict of STRONG or MEDIUM on the composed kahuna-vs-main diff. |
| **R-13** | Ubiquitous | Before the kahuna→main MR auto-merges, CI on the tip of the kahuna branch shall report success. |
| **R-14** | Ubiquitous | Before the kahuna→main MR auto-merges, the `feature-dev:code-reviewer` agent shall report zero critical or important findings on the composed diff. |
| **R-15** | Ubiquitous | Before the kahuna→main MR auto-merges, `trivy fs --scanners vuln --severity HIGH,CRITICAL` shall report zero findings. |
| **R-16** | Unwanted | If any of R-12 through R-15 produces a non-passing result, then the system shall pause the kahuna→main merge, notify the user via Discord (`#wave-status` channel) and vox announcement, and record the failing signal(s) in wave state for resumption after human intervention. |
| **R-23** | Ubiquitous | The four trust-score signals defined in R-12 through R-15 shall be evaluated concurrently, not sequentially. Their results shall be aggregated once all four return, before the merge decision. |

### 3.5 State and Visibility

| ID | Type | Requirement |
|----|------|-------------|
| **R-17** | Ubiquitous | Wave state (`.claude/status/state.json` in the target project) shall include a `kahuna_branch` field when a Plan is executing under KAHUNA, and a `kahuna_branches` history recording all kahuna branches created for past Plans with their disposition (merged, aborted, abandoned). |
| **R-18** | State-driven | While a wave is executing under KAHUNA, `wave-status show` shall display the active kahuna branch name, count of merged flights, count of pending flights, and the current trust-signal summary for the eventual kahuna→main gate. |
| **R-19** | Event-driven | When the kahuna→main merge auto-completes, the system shall emit a Discord notification to the `#wave-status` channel and a vox announcement summarizing the Plan, merged flight count, and final merge commit SHA. |

### 3.6 Safety and Concurrency

| ID | Type | Requirement |
|----|------|-------------|
| **R-20** | Unwanted | If `/wavemachine` is invoked on a Plan that already has an active unresolved kahuna branch, then the system shall refuse to start and report the prior run's state. |
| **R-21** | Event-driven | When a Flight Agent encounters a non-fast-forward situation while pushing its branch (kahuna advanced since flight creation), the system shall attempt `git pull --rebase origin <kahuna-branch>` automatically. On clean rebase, proceed. On rebase conflict, return `FAIL` to Prime with the conflict detail. |
| **R-22** | State-driven | While a kahuna branch has been active longer than the configured TTL threshold (default: 48 hours), `wave_health_check` shall report a staleness warning in its output but shall NOT block further wave execution. |

---

## 4. Concept of Operations

### 4.1 System Context

```
                         ┌─────────────────────────────────────┐
                         │   BJ (wave-driver, human)           │
                         │   invokes /wavemachine on Plan #N   │
                         └──────────────────┬──────────────────┘
                                            │
                                            ▼
                         ┌─────────────────────────────────────┐
                         │   Orchestrator Agent                │
                         │   (top-level Claude Code session)   │
                         └──────────────────┬──────────────────┘
                                            │ spawns per-wave
                                            ▼
                         ┌─────────────────────────────────────┐
                         │   Prime Agent (per wave)            │
                         │   — flight planning + reconcile     │
                         └─────┬──────────────┬────────────────┘
                               │ spawns       │ reconciles
                               │ per story    │ after each flight
                               ▼              │
                ┌──────────────────────────┐  │
                │ Flight Agent (per story) │──┘
                │ feature/<N>-xyz branch   │
                │ base = kahuna/<plan>-xyz │
                └──────────────────────────┘
                               │ opens MR → auto-merge
                               ▼
    ┌────────────────────────────────────────────────────────────┐
    │   kahuna/<plan>-xyz integration branch                     │
    │   — accumulates all flight commits for the Plan            │
    │   — MRs in: no review required, CI-gated                   │
    │   — MRs out: trust-score-gated (§3.4)                      │
    └──────────────────────┬─────────────────────────────────────┘
                           │ wave_finalize opens final MR
                           │ when Plan complete + DoD passes
                           ▼
    ┌────────────────────────────────────────────────────────────┐
    │   main (production-visible, normal protections)            │
    │   — auto-merges iff R-12..R-15 all green                   │
    │   — notifies Discord (#wave-status) + vox on merge         │
    └────────────────────────────────────────────────────────────┘

    External systems touched throughout:
      • sdlc-server MCP (wave_init, pr_create, pr_merge,
                         wave_finalize [new], commutativity_verify)
      • Platform API (GitHub gh / GitLab glab)
      • gl-settings automation (per-project KAHUNA settings)
      • feature-dev:code-reviewer sub-agent (trust signal)
      • trivy fs (trust signal)
      • discord-watcher + disc-server MCP (notifications)
      • vox CLI (speech)
      • wavebus filesystem (/tmp/wavemachine/...)
      • wave-status CLI (state, dashboard)
```

### 4.2 Happy-Path Flow: Overnight Autonomous Plan

Narrative: BJ approves a Dev Spec, runs `/devspec upshift` to populate the backlog with a Plan and its wave-pattern Stories, invokes `/wavemachine` before bed, returns the next morning to find the Plan merged.

1. **Plan start.** BJ runs `/wavemachine` naming an approved Plan. The Orchestrator reads wave state, sees no existing `kahuna_branch` field, calls `wave_init` with the Plan ID.
2. **Kahuna created.** `wave_init` creates `kahuna/<plan-id>-<slug>` off the current main head, writes the branch name into `kahuna_branch` in wave state, and returns success. Wave state `action` = `planning`.
3. **Wave 1 begins.** Orchestrator spawns Prime for Wave 1. Prime reads the wave's stories from `phases-waves.json`, partitions them into parallel-safe flights via `flight_partition`, writes `flights.json`, and spawns one Flight Agent per flight via the `Agent` tool.
4. **Flight execution.** Each Flight Agent:
   - Creates a worktree, branches off `kahuna/<plan-id>-<slug>` (per R-05)
   - Implements the story
   - Runs `/precheck` — the checklist runs fully (validation, code-reviewer, trivy, notifications)
   - Because the base ref is `kahuna/*`, `/precheck` recognizes the sandbox context (per R-07) and auto-approves its own `/scpmmr` without STOP-and-wait
   - `pr_create` opens an MR with `base = kahuna/<plan-id>-<slug>`
   - The platform auto-merges on CI-green (per R-08, enforced by KAHUNA settings applied via gl-settings)
   - Flight writes its `results.md` to the wavebus and returns `PASS` to Prime
5. **Wave reconciliation.** Prime reads all flight results, confirms all `PASS`, reports to Orchestrator. If any `FAIL`, Orchestrator invokes the failure path (§4.4).
6. **Next wave.** Orchestrator loops: spawn Prime for Wave 2, flights merge to the *same* kahuna branch (each flight rebases or merges main→kahuna if the kahuna HEAD has advanced since their branch was created; if that rebase conflicts, they return FAIL — per R-21).
7. **Final wave complete.** The last wave finishes. Orchestrator checks §7 Definition-of-Done items (test suites pass, VRTM updated, etc.). If all pass, invokes `wave_finalize`.
8. **Trust-score gate.** `wave_finalize` opens the kahuna→main MR with an assembled body (one bullet per flight, linking the original flight MRs into kahuna, the issue numbers closed, CI verdicts). The Orchestrator then evaluates the four trust signals (R-12–R-15) in parallel per R-23:
   - `commutativity_verify` with composed-diff mode → STRONG/MEDIUM expected
   - `ci_wait_run(ref=kahuna-branch)` → success expected
   - `feature-dev:code-reviewer` via Agent tool over the full composed diff → zero high+ findings expected
   - `trivy fs` on the kahuna branch → zero HIGH/CRITICAL expected
9. **Auto-merge.** All four green → Orchestrator invokes `pr_merge(kahuna-main-mr-number)` with `skip_train=true` (trust-cleared, bypass merge queue). The merge lands on main as a single squash commit.
10. **Cleanup.** `wave_finalize` deletes the kahuna branch (per R-03), updates wave state to record the disposition in `kahuna_branches` history, emits Discord notification to `#wave-status` + vox announcement (per R-19).
11. **BJ wakes up.** Status panel shows Plan complete, kahuna branch gone, main contains the new commit. The notification thread on Discord has the summary.

### 4.3 Team-Member Coexistence

A non-wave contributor pushing to main while `/wavemachine` runs overnight is a predictable scenario. KAHUNA handles it without requiring the non-wave contributor to change anything.

- The non-wave contributor's MR lands on main as usual — normal review, normal merge queue, normal protections. KAHUNA settings on `kahuna/*` branches do not affect the main-target workflow.
- When the next Flight Agent creates its branch off the (now-stale) kahuna HEAD, the Flight's branch is automatically based on kahuna — not on main. The Flight's work is isolated from the main drift.
- When the Flight's MR merges into kahuna and the next Prime starts the next wave, the new Flight branches off a kahuna that is *still stale relative to main* — this is fine, because the final kahuna→main gate will catch any conflicts at `commutativity_verify` (which computes the composed diff against current main HEAD, not a snapshot).
- If main has drifted so far that commutativity returns WEAK/ORACLE_REQUIRED, the Plan pauses at the gate (per R-16), and BJ handles the reconciliation — either merging main into kahuna and re-running the gate, or rejecting the drift.

**Key property:** team members do not experience any workflow change. They don't see kahuna in their MR-create dropdowns (their UI defaults to main as base), they don't need to know KAHUNA exists, they don't need new permissions or configuration.

### 4.4 Failure and Recovery Flow

#### 4.4.1 Scenario Index

| Trigger | Response pattern | Human recovery |
|---|---|---|
| Flight fails `/precheck` validation | **Procedure A** — validation failure | Fix in flight's worktree, re-run `/wavemachine` |
| Flight rebase conflict when kahuna advanced | **Procedure B** — rebase conflict | Resolve conflict manually, push, re-run wave |
| Trust signal red at kahuna→main gate (any of: commutativity WEAK/ORACLE_REQUIRED, CI red, code-reviewer critical/important, trivy HIGH/CRITICAL) | **Procedure C** — gate signal failure | Fix underlying issue, re-gate (or merge manually after review) |
| Team member's unrelated main merge breaks kahuna composition | Manifests as commutativity WEAK/ORACLE_REQUIRED → **Procedure C** | Merge main into kahuna + re-gate, or accept drift and proceed |
| Orchestrator session crashes mid-Plan | **Procedure D** — crash recovery | Run `/wavemachine` again; wave state + kahuna branch persist, R-02 reuse path picks up |
| Plan fundamentally wrong, BJ wants to drop it | No automated support in MVP | `git push origin --delete kahuna/<plan>-<slug>`, clear `kahuna_branch` from wave state |

#### 4.4.2 Procedure A — Flight Validation Failure

**Detection:** Flight's `/precheck` validation step returns non-zero exit code.

**Agent response:**
1. Flight writes `results.md.partial` with error detail, then atomic-renames to `results.md` via `wavebus/flight-finalize <path> FAIL`
2. `flight-finalize` writes `DONE` sentinel = `FAIL`, prints canonical return line
3. Prime reads flight return, records FAIL in the wave's `merge-report.md`
4. Prime returns `BLOCKED` to Orchestrator per canonical status-line protocol
5. Orchestrator transitions wave state `action` → `failed`, writes failure reason to state
6. Orchestrator emits `disc_send` to `#wave-status` with flight ID, failure summary, and link to `results.md`
7. Orchestrator exits wavemachine loop; kahuna branch preserved (R-04), wavebus preserved for forensics

**Human recovery:** BJ inspects `results.md`, fixes underlying issue in the flight's worktree, commits, pushes, re-runs `/wavemachine` — R-02 reuse path resumes from the failing wave.

#### 4.4.3 Procedure B — Flight Rebase Conflict

**Detection:** Flight's push to its feature branch fails with `non-fast-forward` error because kahuna has advanced since the flight branch was created.

**Agent response:**
1. Flight attempts `git pull --rebase origin <kahuna-branch>` inside its worktree
2. **If rebase succeeds cleanly:** Flight proceeds with push, MR creation, and `/scpmmr` as normal
3. **If rebase produces conflicts:** Flight aborts the rebase with `git rebase --abort`
4. Flight writes `results.md.partial` with conflict detail (files, lines), then `flight-finalize <path> FAIL`
5. Remainder follows Procedure A from step 4 onward (FAIL propagates through Prime to Orchestrator)

**Human recovery:** BJ inspects the conflict, resolves manually in the flight's worktree, commits the resolution, pushes, re-runs `/wavemachine`.

#### 4.4.4 Procedure C — Trust Signal Failure at Gate

**Detection:** During the parallel trust-score evaluation (R-23), any one of the four signals returns a non-passing result:
- `commutativity_verify` verdict = WEAK or ORACLE_REQUIRED
- `ci_wait_run(ref=kahuna-branch)` final_status ≠ "success"
- `feature-dev:code-reviewer` sub-agent reports one or more critical or important findings
- `trivy fs --scanners vuln --severity HIGH,CRITICAL` reports findings with available fixes

**Agent response:**
1. Orchestrator collects all four signal results even if one fails early (do not short-circuit; capturing all four gives the operator complete status)
2. Orchestrator transitions wave state `action` → `gate_blocked`, records which signals failed and their detail payloads
3. Orchestrator emits `disc_send` to `#wave-status` with:
   - Plan name
   - Each failing signal's name + short detail
   - Kahuna branch name
   - The existing open kahuna→main MR URL
4. Orchestrator emits vox announcement: "Kahuna gate blocked for Plan X. N signals red. Ready for your review."
5. Orchestrator exits wavemachine loop; kahuna branch preserved; the kahuna→main MR stays open (un-merged)

**Human recovery:** BJ reviews the failing signals. Three paths:
- Fix the underlying issue (update dep for trivy, fix code for reviewer findings, merge main into kahuna for commutativity drift) and re-run the gate by re-invoking `/wavemachine` at the Plan level — R-02 reuse detects the unresolved state and resumes at the gate
- Accept the signal as a false positive / reviewed-and-overridden and merge the kahuna→main MR manually
- Abandon the Plan per the manual scenario

#### 4.4.5 Procedure D — Orchestrator Crash Mid-Plan

**Detection:** Orchestrator process exits abnormally (crash, OOM, signal, user Ctrl-C). The sub-shell invoking `/wavemachine` terminates.

**System state after crash (all preserved automatically):**
- Wave state (`state.json`) — last-written checkpoint is on disk
- Kahuna branch — live on the platform (per R-04)
- Wavebus `/tmp/wavemachine/<slug>/` — all flight artifacts intact
- Any in-flight MRs on kahuna — remain open (platform doesn't know about the crash)

**Human recovery:** BJ runs `/wavemachine` on the same Plan.
- R-02 fires: existing `kahuna_branch` field in wave state is detected, existing branch is reused
- Orchestrator inspects wave state's last recorded `action` label to determine resume point
- If the last action was `planning`, Orchestrator restarts the current wave's Prime
- If the last action was `flight_in_progress`, Orchestrator verifies which flights actually completed (via MR states on the platform — `pr_status` for each recorded flight MR) and resumes from the first incomplete one
- If the last action was `gate_evaluating`, Orchestrator re-runs the gate (Procedure C)
- Any flight MRs that were left in an intermediate state (PR open but not merged because the Orchestrator died mid-merge) are re-attempted by querying `pr_status` and resuming `pr_merge` if still mergeable

**Important:** The crash-recovery logic must be idempotent. Calling `pr_merge` on an already-merged PR is handled by the tool itself (returns success if already merged). Calling `wave_finalize` on a Plan whose kahuna→main MR already exists is handled by detecting that MR in `pr_list` before creating a new one.

### 4.5 Integration with Existing Wave-Pattern Infrastructure

- **Orchestrator / Prime / Flight protocol (personas from §1.4)** — unchanged. The only behavioral shift is that Flights branch off kahuna instead of main.
- **Filesystem message bus at `/tmp/wavemachine/<slug>/wave-<N>/`** — unchanged. Flight results.md, wave plan.md, merge-report.md all continue as before. No kahuna-specific artifacts.
- **Canonical status-line protocol (Flight → Prime → Orchestrator)** — unchanged. `PASS`/`FAIL` returns still govern the control flow.
- **`wave_health_check` circuit breaker** — extended only to add the kahuna-staleness check (R-22). Core behavior unchanged.
- **`/precheck` mandatory checklist** — unchanged for non-KAHUNA work. For KAHUNA work, the *post-checklist approval step* changes; the checklist itself is identical.
- **`/scp`, `/scpmr`, `/scpmmr`** — unchanged for non-KAHUNA work. For Flights inside a Kahuna sandbox, `/scpmmr` is what auto-runs after `/precheck` auto-approves.
- **Wave state schema (`.claude/status/state.json`)** — extended additively. New fields (`kahuna_branch`, `kahuna_branches` history). Existing fields (`action`, `label`, `current_wave`, etc.) untouched.
- **Existing sdlc-server tool surface** — `pr_create`, `pr_merge` unchanged per tachikoma's §1 review. `commutativity_verify` extended (schema relaxation) rather than replaced.

---

## 5. Detailed Design

### 5.1 sdlc-server Tool Contracts

The sdlc-server changes are additive. Three new/modified tool surfaces plus one wave-state schema extension. Everything else on the server is untouched per CT-04.

#### 5.1.1 `wave_finalize` — new tool

Opens the kahuna→main MR when a Plan's final wave completes. Idempotent: if the MR already exists for the given Plan, returns its details rather than creating a duplicate.

**Signature:**

```typescript
wave_finalize({
  root?: string,            // project path; defaults to CLAUDE_PROJECT_DIR
  plan_id: number,          // Plan issue number (the `type::plan` tracking issue)
  kahuna_branch: string,    // e.g., "kahuna/42-wave-status-cli"
  target_branch?: string,   // defaults to "main"
  body_artifacts_dir?: string  // wavebus artifacts dir for body assembly;
                               // defaults to /tmp/wavemachine/<slug>/
}) → {
  ok: boolean,
  number: number,           // MR/PR number
  url: string,
  state: "open" | "merged",
  created: boolean,         // true if newly created, false if already existed
  body_sha: string          // hash of the assembled body, for drift detection
                            // (computed on EVERY call, including created:false —
                            //  compare across successive calls to detect body drift)
}
```

**Behavior:**
1. Check `pr_list({head: kahuna_branch, base: target_branch})` for an existing open MR. If present, return its details with `created: false`.
2. Assemble the MR body by walking `body_artifacts_dir` / `wave-*/flight-*/results.md` and extracting: flight ID, issue closed, brief summary, link to the flight's original kahuna-target MR.
3. Call `pr_create({title: "plan(#<plan_id>): <slug> — kahuna to main", body: <assembled>, base: target_branch, head: kahuna_branch})`.
4. Return the created MR with `created: true`.

**Error semantics:**
- `ok: false` with `error: "kahuna_branch_not_found"` if the branch doesn't exist on the platform
- `ok: false` with `error: "no_artifacts"` if `body_artifacts_dir` contains no flight results
- Network / API errors propagate as `ok: false` with the underlying message

#### 5.1.2 `commutativity_verify` — schema extension

Relax the minimum `changesets[]` length from 2 to 1. When called with a single-element changeset array, the tool invokes `commutativity-probe analyze --repo <path> --base <base_ref> <single_branch>` in "single-target safety gate" mode rather than pairwise-commutativity mode. The probe binary already supports this invocation; only the handler enforces the pairwise minimum today.

**Updated signature:**

```typescript
commutativity_verify({
  repo_path: string,
  base_ref: string,
  changesets: Array<{ id: string, head_ref: string }>,  // min: 1 (was 2)
  timeout_sec?: number
}) → {
  ok: boolean,
  mode: "pairwise" | "single_target",  // NEW field — disambiguates behavior
  verdict: "STRONG" | "MEDIUM" | "WEAK" | "ORACLE_REQUIRED",
  pairwise_results?: Array<PairResult>,  // populated iff mode === "pairwise"
  single_target_result?: SingleTargetResult,  // populated iff mode === "single_target"
  warnings?: string[]       // optional; emitted when the probe returns an unknown
                            // verdict OR when a defensive guard fires for an
                            // unexpected single-target pair. Consumers should log
                            // and surface these to the operator.
}
```

**Call pattern for the KAHUNA gate (R-12):**

```typescript
commutativity_verify({
  repo_path: "/path/to/target/repo",
  base_ref: "main",
  changesets: [{ id: "kahuna", head_ref: "kahuna/42-foo" }]
}) → {
  ok: true,
  mode: "single_target",
  verdict: "STRONG" | "MEDIUM" | "WEAK" | "ORACLE_REQUIRED",
  single_target_result: { ... }
}
```

**Alternative shape** (open question for tachikoma): a dedicated `commutativity_verify_composed(base_ref, head_ref)` tool that wraps the probe with composed-diff semantics explicitly. Either works. **§5 defaults to schema relaxation** pending tachikoma's preference.

#### 5.1.3 `wave_init` — extension for kahuna branch creation

Extend the existing `wave_init` tool to optionally create and record a kahuna branch. Default behavior unchanged (backward compatible per CT-03).

**Updated signature (additive fields marked NEW):**

```typescript
wave_init({
  root?: string,
  plan: <existing plan JSON shape>,
  extend?: boolean,
  kahuna?: {                                  // NEW optional object
    plan_id: number,                          // Plan issue number (type::plan tracker)
    slug: string                              // "42-wave-status-cli" style
  }
}) → {
  ok: boolean,
  ... existing fields,
  kahuna_branch?: string                      // NEW — populated iff kahuna arg passed
}
```

**Behavior when `kahuna` is passed:**
1. Resolve target platform via `detectPlatformForRef`
2. Get current main head SHA via `gh/glab api`
3. Create branch `kahuna/<plan_id>-<slug>` at that SHA via platform API
4. Update wave state to include `kahuna_branch: "kahuna/<plan_id>-<slug>"`
5. Return the branch name in the response

**Idempotency:** if the branch already exists on the platform AND is already recorded in wave state, return success with the existing name. If it exists on the platform but not in state, refuse (possible orphan from a prior run — human triage).

#### 5.1.4 Wave State Schema Addition

Wave state (`.claude/status/state.json`) gains two top-level fields. Both are optional; absence = legacy (non-KAHUNA) behavior.

```json
{
  "kahuna_branch": "kahuna/42-wave-status-cli",
  "kahuna_branches": [
    {
      "branch": "kahuna/41-prior-plan",
      "plan_id": 41,
      "created_at": "2026-04-23T10:00:00Z",
      "resolved_at": "2026-04-24T02:15:00Z",
      "disposition": "merged",
      "main_merge_sha": "abc123..."
    },
    {
      "branch": "kahuna/40-aborted-plan",
      "plan_id": 40,
      "created_at": "2026-04-22T08:00:00Z",
      "resolved_at": "2026-04-22T09:30:00Z",
      "disposition": "aborted",
      "abort_reason": "code_reviewer_critical_findings"
    }
  ]
}
```

The `action` field (existing; shown as "🧠 PLANNING" etc. on the status panel) gains two new values: `gate_evaluating` and `gate_blocked`. These are reported by `wave-status show` and rendered on the dashboard.

All writes go through the existing `python3 -m wave_status <subcommand>` CLI (never direct edits, per existing CLAUDE.md mandate).

### 5.2 claudecode-workflow Skill Adaptations

#### 5.2.1 `/precheck` — sandbox-aware auto-approval

The mandatory "STOP and wait for approval" behavior is conditional on sandbox context.

**Detection logic (executed after the checklist passes, before the hard-stop):**

```
current_branch = git rev-parse --abbrev-ref HEAD
base_branch    = parse base ref from most recent PR created by agent (or from context)

if base_branch matches regex "^kahuna/[0-9]+-":
    sandbox_context = true
else:
    sandbox_context = false
```

**Behavior:**
- If `sandbox_context == false`: existing behavior — checklist presentation, STOP, wait for `/scp*` or affirmative.
- If `sandbox_context == true`: checklist presentation + notifications still happen (so the operator sees progress on `#precheck`). Immediately after notifications, the skill emits the sentinel line `[AUTO-APPROVED: kahuna sandbox]` and invokes `/scpmmr` with no wait.

**CLAUDE.md mandatory-rule update:** the existing rule "NEVER commit without running `/precheck` first and receiving explicit user approval" gains an exception block noting that auto-approval is valid only when `sandbox_context == true` AND the checklist itself passed. The exception is enforced by `/precheck`'s own detection logic, not by agent discretion.

#### 5.2.2 `/wavemachine` — autonomous gate evaluation and auto-merge

The top-level loop gains three new step groups.

**New step group — pre-wave kahuna bootstrap (runs once per Plan, on first invocation):**
1. Read wave state; if `kahuna_branch` is absent, proceed to creation. If present, skip (resume path).
2. Invoke `wave_init` with the `kahuna: { plan_id, slug }` argument to create and record the branch.
3. Emit `#wave-status` notification: Plan started, kahuna branch created.

**Existing step group — per-wave execution (unchanged behavior, new sandbox-aware Flights):**
- Prime spawned; Flights branch off kahuna, not main. Prime coordinates via existing wavebus protocol.

**New step group — trust-score gate and auto-merge (runs once at Plan completion, after final wave):**
1. DoD checks per §7.
2. Invoke `wave_finalize` to open the kahuna→main MR.
3. Transition wave state `action` → `gate_evaluating`.
4. Invoke the four trust-score signals **concurrently** per R-23:
   - `commutativity_verify(base_ref=main, changesets=[{id:"kahuna", head_ref:<branch>}])`
   - `ci_wait_run(ref=<kahuna_branch>, timeout_sec=1800)`
   - `Agent(subagent_type=feature-dev:code-reviewer, prompt=<composed diff>)` — scoped review over the full kahuna-vs-main diff
   - `Bash("trivy fs --scanners vuln --severity HIGH,CRITICAL --format json --quiet <repo_path>")`
5. Collect all four results. Do not short-circuit (per Procedure C).
6. If all four pass: invoke `pr_merge({number: <kahuna_mr_number>, skip_train: true, squash_message: <assembled>})`. Record disposition in wave state's `kahuna_branches` history. Delete kahuna branch. Emit `#wave-status` notification (R-19) and vox announcement.
7. If any fail: transition wave state `action` → `gate_blocked` with per-signal detail. Emit `#wave-status` notification + vox alert per Procedure C. Preserve kahuna branch. Exit loop.

#### 5.2.3 `/nextwave` — Flight base-ref plumbing

Prime Agent's flight-spawning step passes `kahuna_branch` from wave state into each Flight's prompt. Flights use that as their `git checkout -b feature/<issue>-<slug> origin/<kahuna_branch>` base and their `pr_create({base: <kahuna_branch>})` target.

If wave state has no `kahuna_branch` (legacy non-KAHUNA execution), Flights continue to base off `main` as before. No behavior change for non-KAHUNA consumers.

#### 5.2.4 `/scp`, `/scpmr`, `/scpmmr` — no code changes

These skills need no code changes. They already accept commit messages and call `pr_create` / `pr_merge` without opinions about base ref. The sandbox-aware behavior lives in `/precheck`'s auto-approval logic.

#### 5.2.5 `wave-status` CLI additions

`wave-status show` output gains:
- A "Kahuna" section displaying active `kahuna_branch` and flight counts (merged / pending)
- Trust-signal summary block when `action == gate_evaluating`
- Signal-failure detail block when `action == gate_blocked`
- The `kahuna_branches` history table (collapsible, shows last 10 entries)

The dashboard HTML generator (`src/wave_status/dashboard.py` or equivalent) gains rendering for the same.

#### 5.2.6 Wavebus — no new primitives

The filesystem bus at `/tmp/wavemachine/` operates at a level above git branches. KAHUNA's branch semantics live in git and in wave state, not in wavebus. Existing `wave-init`, `flight-finalize`, and `wave-cleanup` primitives remain unchanged.

### 5.3 Platform Settings Automation

#### 5.3.1 GitLab — `gl-settings` extensions

Today `gl-settings` manages branch protection, tag protection, MR approval rules, MR settings, and generic project settings via its `operations/` module. KAHUNA needs one extension and one new operation.

**Extension — `push-rule` operation:**
- Adds the ability to `PUT /projects/:id/push_rule` with a `branch_name_regex` parameter
- Supports dry-run per gl-settings convention
- Idempotent: no-op if current regex already matches target
- Formalizes the manual sweep done during recon (widening 29 projects to accept `kahuna/*`).

**New operation — `kahuna-sandbox` (composite):**
- For a given project, applies the settings that establish the kahuna sandbox property:
  - `PUT /projects/:id/protected_branches` — protect the `kahuna/*` pattern (developer push + developer merge). Required as a prerequisite for the per-branch approval rule below: GitLab approval rules can only be scoped to *protected* branches.
  - `POST /projects/:id/approval_rules` — create a `kahuna-zero-approvals` rule with `approvals_required: 0`, scoped via `protected_branch_ids: [<kahuna_pattern_id>]` to the protected branch above. **Must NOT use `merge_request_approval_settings`** — that endpoint is project-wide and would unprotect main.
  - `PUT /projects/:id/settings` — `only_allow_merge_if_pipeline_succeeds=true` (so kahuna merges still gate on CI), `squash_option=default_on` (per CT-02), `merge_pipelines_enabled=true`, `merge_trains_enabled=true`. **Merge trains ENABLED**, not disabled — they batch flight-MRs into one pipeline run per train, which is the throughput story autonomous execution needs (R-08). The previous "disabled" wording was an error.
- Provides a single-command bootstrap: `gl-settings kahuna-sandbox <project-url>`
- Includes drift-check mode (via `--dry-run` and `action="would_apply"` per gl-settings convention) for auditing which projects have KAHUNA sandbox settings applied
- As-shipped: `bakeb7j0/gitlab-settings-automation` PR #29 (commit `b2af3d7`)

#### 5.3.2 GitHub — no `gh-settings` tool today

GitHub equivalent work requires direct `gh api` calls to the repo settings endpoints. For MVP, a bash script (`scripts/kahuna/github-apply.sh`) wrapping the relevant `gh api` calls per repo is sufficient. A proper `gh-settings` tool is follow-up work.

GitHub-specific operations per repo:
- Enable auto-merge via `gh repo edit --enable-auto-merge` (repo-level knob)
- Create branch-protection rule for `kahuna/*` pattern with `required_approving_review_count=0`, `required_status_checks.strict=true`
- Main-branch protection unchanged

#### 5.3.3 Per-repo Configuration Manifest

Each project that opts into KAHUNA publishes a small configuration artifact, either a YAML file in the repo (`.kahuna.yml`) or a group-level gl-settings config. Fields:

```yaml
kahuna:
  enabled: true
  ttl_hours: 48           # overridable default from R-22
  plan_label: "type::plan" # how Plans are identified (new taxonomy; legacy `type::epic`
                           # is ignored — PM-layer parent tracker, not pipeline-operational)
  wave_label: "type::chore" # how wave masters are identified (existing convention)
```

This gives per-project control without hardcoding defaults. MVP: a single `.kahuna.yml` in the proving-ground project.

### 5.4 Cross-Repo Coordination

The Dev Spec is canonical in claudecode-workflow. Section 5's sdlc-server contracts are the contract surface tachikoma implements against. The coordination model uses the spec file as the ground truth and the Big Kahuna Discord thread as the real-time amendment channel.

**Freeze discipline:** After approval, §5.1 (sdlc-server tool contracts) is locked. Any mid-flight change requires a spec amendment PR in claudecode-workflow and a corresponding update notice in the Big Kahuna thread. Neither side modifies their working assumption without both steps.

**Parallel-execution plan:**
- BJ drives claudecode-workflow work via `/wavemachine` on a Plan filed in that repo's issue tracker
- Tachikoma drives mcp-server-sdlc work on a parallel Plan in that repo's tracker
- Integration tests live in claudecode-workflow, exercising the full chain against the proving-ground project

### 5.A Deliverables Manifest

Column key — Tier: 1 (required, opt-out with rationale) / 2 (fires on trigger conditions) / 3 (on request only). Req'd: required vs optional. N/A rows note why the deliverable doesn't apply.

| ID | Deliverable | Category | Tier | File Path | Produced In | Req'd | Notes |
|----|-------------|----------|------|-----------|-------------|-------|-------|
| DM-01 | README.md | Docs | 1 | `claudecode-workflow/README.md` (KAHUNA section), `mcp-server-sdlc/README.md` (new tools) | Wave 4 | required | Updates in both repos rather than new file |
| DM-02 | Unified build system | Code | 1 | N/A — because both repos have existing build systems (Makefile in claudecode-workflow, Bun build in mcp-server-sdlc) that already cover KAHUNA changes additively; no new top-level build warranted | — | N/A | — |
| DM-03 | CI/CD pipeline | Code | 1 | N/A — because both repos have existing CI and KAHUNA adds test cases to those existing pipelines rather than introducing a new pipeline | — | N/A | — |
| DM-04 | Automated test suite | Test | 1 | `mcp-server-sdlc/tests/wave_finalize.test.ts`, `mcp-server-sdlc/tests/commutativity_verify_single.test.ts`, `claudecode-workflow/tests/precheck_sandbox.test.py`, `claudecode-workflow/tests/wavemachine_gate.test.py`, `gl-settings/tests/test_push_rule.py`, `gl-settings/tests/test_kahuna_sandbox.py` | Waves 1-3 | required | Unit + integration tests across all three repos |
| DM-05 | Test results (JUnit XML) | Test | 1 | Standard CI output paths in all three repos | Each wave's CI | required | Emitted by existing CI |
| DM-06 | Coverage report | Test | 1 | Standard CI output paths | Each wave's CI | required | Emitted by existing CI |
| DM-07 | CHANGELOG | Docs | 1 | `CHANGELOG.md` in each affected repo | Wave 4 | required | Entries in claudecode-workflow, mcp-server-sdlc, gl-settings |
| DM-08 | VRTM | Trace | 1 | §9 Appendix V of this Dev Spec | Wave 4 | required | Backfilled during execution with test pass evidence |
| DM-09 | Audience-facing doc | Docs | 1 | `claudecode-workflow/docs/kahuna-guide.md` + `claudecode-workflow/skills/ccwork/tours/sdlc.md` | Wave 4 | required | User-facing KAHUNA guide + ccwork tour section |
| DM-10 | Synthetic wave-pattern fixture generator | Test | 2 | `claudecode-workflow/scripts/testing/wave-fixture-gen.py` | Wave 1 | required | Outlives KAHUNA; CLI tool with scenario subcommands (conflicting-functions, trivy-dep-vuln, critical-code-smell, rebase-conflict-setup) |
| DM-11 | Settings-deployment procedures doc | Docs | 2 | `claudecode-workflow/docs/kahuna-settings-deployment.md` | Wave 2 | required | Trigger fired: project deploys infrastructure (gl-settings operations to ≥29 projects) |
| DM-12 | Platform prerequisites doc | Docs | 2 | `claudecode-workflow/docs/kahuna-platform-prerequisites.md` | Wave 2 | required | Trigger fired: project has host/platform requirements (commit_committer_check, merge-queue APIs) |

### 5.B Installation and Deployment

#### 5.B.1 mcp-server-sdlc

`wave_finalize`, `commutativity_verify` extension, and `wave_init` extension ship via standard sdlc-server release channel:
- Handler files added in `handlers/` following the codegen-based registry pattern
- Tests added to `tests/`
- Smoke test verifies new tools appear in `tools/list` response
- Release: standard `bun build --compile`, binary published to GitHub Releases
- Clients upgrade by re-running the install: `curl -fsSL <install-remote.sh> | bash`

#### 5.B.2 claudecode-workflow

Skill changes ship via standard `./install` flow:
- `skills/precheck/SKILL.md` updated with sandbox-aware logic
- `skills/wavemachine/SKILL.md` updated with gate-evaluation and auto-merge step group
- `skills/nextwave/SKILL.md` updated with kahuna base-ref plumbing in Prime/Flight spawn
- `CLAUDE.md` updated with sandbox-exception note on the pre-commit-gate rule
- `src/wave_status/` Python package updated for new state fields and action labels; rebuilt via `./scripts/ci/build.sh` into the zipapp CLI
- Users re-run `./install` in the claudecode-workflow directory; the existing smart-merge on `settings.json` and atomic copy of skills + CLI apply cleanly

#### 5.B.3 gl-settings

`push-rule` operation and `kahuna-sandbox` composite operation ship via standard gl-settings release:
- New operation modules in `gl_settings/operations/`
- Registered in `gl_settings/operations/__init__.py`
- Tests in `tests/`
- Release: version bump, `pip install git+https://...` upgrades consumers
- For the proving-ground project, `gl-settings kahuna-sandbox <project-url>` is invoked once to establish settings

#### 5.B.4 Test-repo Setup

TBD. Proving-ground repo selection deferred. Integration tests and manual verification procedures target "the proving-ground project" abstractly until one is selected.

---

## 6. Test Plan

### 6.1 Test Strategy

Testing operates at three levels:

- **Unit tests** — cover tool implementations inside each MCP server (especially the sdlc-server changes: `wave_finalize`, `commutativity_verify` single-target mode, `wave_init` kahuna extension). Tests run via `bun test` in mcp-server-sdlc's standard CI.
- **Integration tests** — exercise the full KAHUNA flow end-to-end against the proving-ground project. These live in claudecode-workflow, run manually (or via a scheduled CI job) because they require live GitLab API access and the proving-ground project's test Plan.
- **Manual verification procedures** — a checklist executed personally by BJ the first few times KAHUNA processes a real Plan. Catches the things automated tests can't — like whether the notification lands in the right channel, whether the status panel renders the new fields, whether the overnight run actually completes autonomously.

The split is deliberate: unit tests verify correctness, integration tests verify wiring, manual verification verifies *fitness for purpose*.

### 6.2 Integration Tests

| ID | Scenario | Verifies | Pass Criteria |
|----|----------|----------|---------------|
| **IT-01** | Single-flight, single-wave Plan processes autonomously | R-01, R-05, R-06, R-07, R-08, R-11, R-12, R-13, R-14, R-15, R-17, R-19, R-23 | `/wavemachine` on a 1-Story Plan produces: kahuna branch created, flight MR merged to kahuna via auto-merge, kahuna→main MR auto-merged when all four trust signals green, kahuna branch deleted, Discord+vox notifications fired. Whole run completes without human input. |
| **IT-02** | Multi-flight, multi-wave Plan with parallel flights | R-05, R-06, R-07, R-08, R-17 | `/wavemachine` on a 3-wave Plan with 2-flight parallel wave produces expected merge sequence into kahuna; flights observably execute in parallel (timestamp delta < 5s between their MR creations). |
| **IT-03** | Trust-signal failure — commutativity WEAK | R-12, R-16, R-23, R-04 | Setup via `wave-fixture-gen --scenario conflicting-functions`: Plan where kahuna contains conflicting changesets. Expected: `commutativity_verify` returns WEAK, gate blocks, `#wave-status` notification lists failing signal, kahuna branch preserved, `action == gate_blocked`. |
| **IT-04** | Trust-signal failure — trivy finding | R-15, R-16, R-23 | Setup via `wave-fixture-gen --scenario trivy-dep-vuln`: Plan that introduces a vulnerable dep. Expected: trivy signal red, gate blocks, notification names the CVE. |
| **IT-05** | Trust-signal failure — code-reviewer critical | R-14, R-16, R-23 | Setup via `wave-fixture-gen --scenario critical-code-smell`: Plan that includes an obvious critical issue. Expected: code-reviewer flags it, gate blocks, finding in notification. |
| **IT-06** | Team-member drift at gate | R-16, R-23 | Setup: start `/wavemachine` on a Plan, then (during the run) push an unrelated MR to main that touches overlapping files. Expected: commutativity_verify returns WEAK at gate, pause for BJ. |
| **IT-07** | Orchestrator crash recovery | R-02, Procedure D | Setup: start `/wavemachine`, kill the session mid-Plan. Expected: re-running `/wavemachine` on the same Plan resumes from wave state's last recorded action, reuses the existing kahuna branch, no duplicate MRs created. |
| **IT-08** | Flight rebase-conflict handling | R-21, Procedure B | Setup via `wave-fixture-gen --scenario rebase-conflict-setup`: flight branches where flight N+1 touches the same lines as flight N after flight N merges to kahuna. Expected: flight N+1 attempts rebase, detects conflict, returns FAIL, kahuna preserved. |
| **IT-09** | `/precheck` sandbox detection | R-07 | Setup: Flight agent on a `kahuna/*`-based feature branch. Expected: `/precheck` runs full checklist, then auto-approves `/scpmmr` without STOP. Same flight on a `main`-based branch: STOP-and-wait behavior preserved. |
| **IT-10** | Concurrent wavemachine invocation refused | R-20 | Setup: run `/wavemachine` on a Plan, then (in a second session) try to run `/wavemachine` on the same Plan while the first run is still in-flight. Expected: second invocation refused with message naming the prior run's state. |
| **IT-11** | Non-wave teammate workflow unchanged | CP-01 | Setup: during an active `/wavemachine` run, an unrelated `feature/` branch MR opened to main. Expected: that MR behaves identically to pre-KAHUNA — normal review, normal merge queue, normal protections. |
| **IT-12** | Settings-automation drift detection | R-10, CP-02 | Setup: run `gl-settings kahuna-sandbox --check <project-url>` on a project where the KAHUNA settings have been partially removed. Expected: check mode reports the specific drift items. |
| **IT-13** | Vox announcement invoked correctly at Plan completion | R-19 | During IT-01, the Orchestrator invokes `vox` as a subprocess exactly once. Verifiable via subprocess capture wrapper: expected message substring ("merged into main"), subprocess returns exit code 0, Plan ID and merge SHA present in the message string. Does not assert audible playback. |

### 6.3 End-to-End Tests

| ID | Scenario | Fidelity |
|----|----------|----------|
| **E2E-01** | Full overnight run — realistic 5-Story, 3-wave Plan, zero human input between `/wavemachine` invocation and morning status check | No mocks, live GitLab API, real trust-signal evaluation including live `commutativity-probe` subprocess, real CI pipeline runs, real disc-server notifications, real vox announcement |
| **E2E-02** | Multiple concurrent epics on two separate proving-ground projects | **POST-MVP** — deferred until a second proving-ground project is available. Not in scope for v1 delivery. |

### 6.4 Manual Verification Procedures

| ID | Procedure | Expected Observation |
|----|-----------|---------------------|
| **MV-01** | Watch `#wave-status` channel during an IT-01 run | Notifications arrive in order: plan-started, (per flight) flight-merged-to-kahuna, gate-evaluating, plan-merged-to-main. No notifications to `#general` or project-default channel. |
| **MV-02** | Open the wave-status dashboard HTML during an IT-01 run (before gate) | Dashboard shows active `kahuna_branch`, accurate merged-flight count, accurate pending-flight count, action label transitions visible as waves progress |
| **MV-03** | Observe `action` label transitions on status panel during IT-03 (gate failure) | Panel shows `gate_evaluating` → `gate_blocked` with failure reason field populated and rendering correctly |
| **MV-05** | Verify kahuna branch cleanup via `git branch -a --remotes` on the proving-ground project after IT-01 completion | `kahuna/<plan-id>-*` branch no longer present on remote |
| **MV-06** | Verify non-wave workflow during IT-11 | While `/wavemachine` runs, a separate terminal opens a feature/fix MR to main following normal workflow — confirms the normal flow is unblocked and unchanged |
| **MV-07** | Verify 48-hour staleness warning | With wave state's `kahuna_branch` created > 48 hours ago, run `wave_health_check`. Expected: warning printed, does not block further execution. |

### 6.5 Requirement-to-Test Traceability

- **R-01:** IT-01, IT-07
- **R-02:** IT-07
- **R-03:** IT-01, MV-05
- **R-04:** IT-03, IT-04, IT-05, IT-07
- **R-05:** IT-01, IT-02, IT-09
- **R-06:** IT-01, IT-02
- **R-07:** IT-09
- **R-08:** IT-01, IT-12
- **R-09:** IT-11
- **R-10:** IT-12
- **R-11:** IT-01
- **R-12:** IT-01, IT-03
- **R-13:** IT-01
- **R-14:** IT-01, IT-05
- **R-15:** IT-01, IT-04
- **R-16:** IT-03, IT-04, IT-05, IT-06
- **R-17:** IT-01, IT-07
- **R-18:** MV-02
- **R-19:** IT-01, IT-13, MV-01
- **R-20:** IT-10
- **R-21:** IT-08
- **R-22:** MV-07
- **R-23:** IT-01, IT-03

All 22 requirements have at least one verification item.

### 6.6 Test Environment Requirements

- Proving-ground GitLab project with KAHUNA settings applied (via `gl-settings kahuna-sandbox`)
- Bot identity with write access + committer email matching `commit_committer_check` (if enabled)
- Test Plan pre-populated with Story issues decomposed into waves
- Live `commutativity-probe` binary installed locally
- Discord bot with write access to `#wave-status`
- `trivy` installed locally
- `gh` and `glab` CLIs authenticated

Test reset between runs: delete any lingering `kahuna/*` branches, reset wave state by clearing `kahuna_branch` field and `kahuna_branches` history.

---

## 7. Definition of Done

### 7.1 Global DoD Checklist

For the KAHUNA Plan overall. All deliverables in the Deliverables Manifest (Section 5.A) must be produced or explicitly marked N/A; every Tier 1 row with a file path and every Tier 2 row triggered must ship.

- [ ] All requirements R-01 through R-23 have at least one passing verification item (test or AC). VRTM in §9 shows full trace.
- [ ] All Deliverables Manifest (Section 5.A) rows delivered or marked N/A with rationale. Tier 1 rows (DM-01 through DM-09) opt-out-with-rationale honored. Tier 2 rows (DM-10 through DM-12) delivered since their triggers fired. Every row's "Produced In" wave assignment honored.
- [ ] `mcp-server-sdlc` release published with the new `wave_finalize` tool, `commutativity_verify` schema extension, `wave_init` kahuna extension. Release binary available via standard install channel.
- [ ] `claudecode-workflow` release with `/precheck` sandbox detection, `/wavemachine` gate evaluation, `/nextwave` kahuna base-ref plumbing, wave-status CLI updates. Deployed via `./install` with smart-merge intact.
- [ ] `gl-settings` release with new `push-rule` operation and `kahuna-sandbox` composite operation.
- [ ] Proving-ground project selected, KAHUNA settings applied, test Plan pre-populated.
- [ ] Synthetic wave-fixture generator (DM-10) functional for the four MVP scenarios.
- [ ] Integration tests IT-01 through IT-13 all pass against the proving-ground. E2E-01 executes cleanly (E2E-02 deferred).
- [ ] Manual verifications MV-01, MV-02, MV-03, MV-05, MV-06, MV-07 personally verified by BJ on at least one real overnight run.
- [ ] Documentation: `kahuna-settings-deployment.md`, `kahuna-platform-prerequisites.md`, `kahuna-guide.md` published. ccwork tour (`tours/sdlc.md`) updated with KAHUNA section.
- [ ] CHANGELOG entries in all three repos.
- [ ] CLAUDE.md updated with the sandbox-exception note on the pre-commit-gate rule.

### 7.2 Dev Spec Finalization Checklist

Verified mechanically by `devspec_finalize` tool before approval.

- [ ] **F-01: All sections present.** §1–§9 all exist and have non-template content.
- [ ] **F-02: All requirements traced.** Every R-## appears in at least one Test Plan item, Acceptance Criteria, or Phase DoD item.
- [ ] **F-03: All manifest rows have wave assignments.** Every active DM-## in §5.A has a "Produced In" wave.
- [ ] **F-04: All requirements use EARS syntax.** Every R-## matches one of the five EARS forms.
- [ ] **F-05: No template placeholders remaining.** No `[[...]]` guidance blocks or unfilled persona templates in the written spec.
- [ ] **F-06: VRTM skeleton present.** §9 Appendix V has the forward+backward trace stub.
- [ ] **F-07: All non-goals have rationales.** Each §1.5 bullet explains why it's excluded despite seeming in-scope.

---

## 8. Phased Implementation Plan

Three phases, each containing 1–2 waves. Cross-repo: stories tagged with scope so `/devspec upshift` in each repo picks up only its own issues.

### Phase 1: Plumbing

**Phase DoD:** All foundation tools exist and are unit-tested. Wave-state schema extended. gl-settings operations shipped. Proving-ground repo selected and settings applied. Synthetic fixture generator functional.

#### Wave 1 — sdlc-server tool foundations (parallel; tachikoma's lane)

*Stories filed in `Wave-Engineering/mcp-server-sdlc`*

- **Story 1.1:** Add `wave_finalize` handler with unit tests. Idempotency via `pr_list` check. Body assembly from wavebus artifacts.
- **Story 1.2:** Extend `commutativity_verify` — relax schema to min:1 changesets, add `mode` return field, handle single-target invocation path.
- **Story 1.3:** Extend `wave_init` — optional `kahuna` arg for branch creation and wave-state recording. Idempotent on existing branch.
- **Story 1.4:** Wave-state schema — add `kahuna_branch` field (optional), `kahuna_branches` history (array). Update `wave-status` CLI Python reader to parse these fields without errors on older state files.

**AC for Wave 1:** all new/modified tools pass unit tests. `bun test` green. `scripts/ci/smoke.sh` boots the binary and verifies all handlers register. Release candidate built.

#### Wave 2 — claudecode-workflow foundations + gl-settings (parallel with Wave 1)

*Stories filed in `Wave-Engineering/claudecode-workflow`, `bakeb7j0/gitlab-settings-automation`*

- **Story 2.1:** Synthetic wave-fixture generator — `scripts/testing/wave-fixture-gen.py` with four scenario subcommands. [claudecode-workflow]
- **Story 2.2:** Wave-status CLI additions — parse `kahuna_branch` + `kahuna_branches` fields, display on `wave-status show`, render in dashboard HTML. New action labels `gate_evaluating`, `gate_blocked`. [claudecode-workflow]
- **Story 2.3:** `gl-settings push-rule` operation — idempotent, supports dry-run, drift check. [gl-settings]
- **Story 2.4:** `gl-settings kahuna-sandbox` composite operation — applies all required per-project settings. [gl-settings]
- **Story 2.5:** Proving-ground repo selection and KAHUNA settings applied. Publish `kahuna-settings-deployment.md` and `kahuna-platform-prerequisites.md`. [claudecode-workflow — ops]

**AC for Wave 2:** generator produces deterministic scenarios. wave-status CLI renders new fields. gl-settings operations pass tests and dry-run cleanly. Proving-ground ready for IT-## execution.

### Phase 2: Skill Integration

**Phase DoD:** End-to-end skill flow functional. IT-01 passes. Sandbox auto-approval working. Gate evaluation working with all four signals.

#### Wave 3 — Skill adaptations (serial, depends on Phase 1 complete)

*Stories filed in `Wave-Engineering/claudecode-workflow`*

- **Story 3.1:** `/precheck` sandbox detection and auto-approval logic. Update SKILL.md. Test via IT-09.
- **Story 3.2:** `/nextwave` Prime/Flight kahuna base-ref plumbing. Flights branch off kahuna per R-05, MR target per R-06. Test via IT-01 (partial).
- **Story 3.3:** `/wavemachine` gate-evaluation step group. Parallel trust-signal invocation per R-23. Auto-merge via `pr_merge(skip_train=true)`. Notification via `#wave-status`. Test via IT-01.
- **Story 3.4:** CLAUDE.md update — sandbox-exception note on mandatory rule. Update `/precheck`, `/scp*` skill prose.

**AC for Wave 3:** IT-01 passes end-to-end on proving-ground. `/wavemachine` on a 1-Story Plan completes autonomously.

### Phase 3: Verification + Documentation

**Phase DoD:** All MVP integration tests pass. Manual verifications complete. Documentation published. Release tagged in all three repos.

#### Wave 4 — Integration test execution + documentation (parallel substreams)

*Stories filed across all three repos*

- **Story 4.1:** Execute IT-02 through IT-13 against proving-ground. File defects as discovered, fix, re-run until green. [claudecode-workflow]
- **Story 4.2:** Execute E2E-01 (full overnight run). [claudecode-workflow]
- **Story 4.3:** Execute manual verifications MV-01, MV-02, MV-03, MV-05, MV-06, MV-07. [claudecode-workflow]
- **Story 4.4:** Publish `kahuna-guide.md` (user-facing). [claudecode-workflow]
- **Story 4.5:** Update `skills/ccwork/tours/sdlc.md` with KAHUNA section. [claudecode-workflow]
- **Story 4.6:** CHANGELOG entries + README updates in all three repos. [multi-repo]
- **Story 4.7:** VRTM backfill — update §9 Appendix V with actual test↔requirement pass evidence. [claudecode-workflow, updates this Dev Spec]

**AC for Wave 4:** all MVP IT-## and MV-## pass. VRTM complete. Docs live. Release tagged.

---

## 9. Appendices

### Appendix V: VRTM (Verification Requirements Traceability Matrix)

Skeleton at finalization. Backfilled during Wave 4 Story 4.7 with per-item verification evidence (test pass IDs, commit SHAs, review links).

**Status note (2026-04-25):** Backward trace structure populated and forward trace validated. Evidence columns marked `PENDING` reference open issues that will execute the corresponding test runs and supply pass timestamps + run-log links once executed. IT-09 has partial implementation evidence from Wave 3 Story 3.1 (sandbox-detection logic landed); a final IT-09 pass record from a proving-ground run is still pending under #420. No R-## was found unverified; every R-## still maps to at least one verification item.

**Forward trace (requirement → verification):**

| R-## | Verification items |
|---|---|
| R-01 | IT-01, IT-07 |
| R-02 | IT-07 |
| R-03 | IT-01, MV-05 |
| R-04 | IT-03, IT-04, IT-05, IT-07 |
| R-05 | IT-01, IT-02, IT-09 |
| R-06 | IT-01, IT-02 |
| R-07 | IT-09 |
| R-08 | IT-01, IT-12 |
| R-09 | IT-11 |
| R-10 | IT-12 |
| R-11 | IT-01 |
| R-12 | IT-01, IT-03 |
| R-13 | IT-01 |
| R-14 | IT-01, IT-05 |
| R-15 | IT-01, IT-04 |
| R-16 | IT-03, IT-04, IT-05, IT-06 |
| R-17 | IT-01, IT-07 |
| R-18 | MV-02 |
| R-19 | IT-01, IT-13, MV-01 |
| R-20 | IT-10 |
| R-21 | IT-08 |
| R-22 | MV-07 |
| R-23 | IT-01, IT-03 |

**Backward trace (verification → requirements):**

The Pass Status column captures the most recent verification outcome. `PENDING` means the verification item has been specified and (for IT-## driven by code that has shipped) is implementable, but the actual run on the proving-ground project has not yet been executed. The Evidence column links to the issue that owns the run. Once a run completes, replace `PENDING <YYYY-MM-DD>` with `PASS <YYYY-MM-DD>` (or `FAIL <YYYY-MM-DD>` + linked defect) and append the run-log artifact link, the SHA of the kahuna→main merge under test, and the PR/MR where any associated fix landed.

Backward trace is derived by inverting §6.5 Requirement-to-Test Traceability. Where §6.2 IT-## "Verifies" cells list a broader R-## set than §6.5 attributes to that same IT-## (a known forward-trace inconsistency at finalization), this table follows §6.5 — it is the canonical forward trace and is the spec's authoritative source. The §6.2 cells will be reconciled separately.

| Verification | Requirements Covered | Pass Status | Evidence |
|---|---|---|---|
| IT-01 | R-01, R-03, R-05, R-06, R-08, R-11, R-12, R-13, R-14, R-15, R-17, R-19, R-23 | PENDING 2026-04-25 | Execution owned by #420 (single-flight proving-ground run). Implementation shipped: #450 `f61eb98` (precheck sandbox detection), #451 `3c63ddc` (nextwave kahuna base-ref plumbing), #454 `c9354eb` (wavemachine gate evaluation + auto-merge). Run-log link, kahuna→main merge SHA, and Discord/vox capture to be appended on first green run. |
| IT-02 | R-05, R-06 | PENDING 2026-04-25 | Execution owned by #420 (multi-flight, multi-wave proving-ground run). Same Wave 3 implementation set as IT-01. Pass evidence will include parallel-flight timestamp delta < 5s. |
| IT-03 | R-04, R-12, R-16, R-23 | PENDING 2026-04-25 | Execution owned by #420. Setup via `wave-fixture-gen --scenario conflicting-functions` (fixture generator landed under Story 2.1). Pass evidence will include `commutativity_verify` WEAK return, `#wave-status` notification text, kahuna branch persistence check. |
| IT-04 | R-04, R-15, R-16 | PENDING 2026-04-25 | Execution owned by #420. Setup via `wave-fixture-gen --scenario trivy-dep-vuln`. Pass evidence will include trivy CVE in notification body. |
| IT-05 | R-04, R-14, R-16 | PENDING 2026-04-25 | Execution owned by #420. Setup via `wave-fixture-gen --scenario critical-code-smell`. Pass evidence will include code-reviewer critical finding in notification body. |
| IT-06 | R-16 | PENDING 2026-04-25 | Execution owned by #420. Manual drift injection during a live proving-ground run. Pass evidence will include the drifted MR SHA on main and the gate-block notification. |
| IT-07 | R-01, R-02, R-04, R-17 | PENDING 2026-04-25 | Execution owned by #420. Procedure D (crash recovery) drill. Pass evidence will include pre-kill wave-state JSON snapshot, post-resume `kahuna_branch` reuse, and zero duplicate MRs check. |
| IT-08 | R-21 | PENDING 2026-04-25 | Execution owned by #420. Setup via `wave-fixture-gen --scenario rebase-conflict-setup`. Pass evidence will include the FAIL return from the conflicted Flight and kahuna preservation check. |
| IT-09 | R-05, R-07 | PARTIAL 2026-04-25 | Implementation landed: PR #450 (`f61eb98`) — `/precheck` sandbox detection + auto-approval. Negative-case prose committed in `skills/precheck/SKILL.md`. Final IT-09 proving-ground run (positive + negative case) owned by #420. Pass evidence will include the `[AUTO-APPROVED: kahuna sandbox]` sentinel from a real flight and the STOP-and-wait observation from a `main`-based flight. |
| IT-10 | R-20 | PENDING 2026-04-25 | Execution owned by #420. Concurrent-invocation refusal drill. Pass evidence will include the second-invocation refusal message text. |
| IT-11 | R-09 | PENDING 2026-04-25 | Execution owned by #420. Pass evidence shared with MV-06 (separate-terminal feature MR opened during a live `/wavemachine` run). |
| IT-12 | R-08, R-10 | PENDING 2026-04-25 | Execution owned by #420. Setup: `gl-settings kahuna-sandbox --check <project-url>` against a partially-drifted project. Pass evidence will include the drift-item list output. |
| IT-13 | R-19 | PENDING 2026-04-25 | Execution owned by #420; piggybacks on the IT-01 run. Pass evidence will include the captured subprocess message-substring assertion ("merged into main") and exit-code 0. |
| E2E-01 | R-01, R-02, R-03, R-05, R-06, R-08, R-11, R-12, R-13, R-14, R-15, R-17, R-19, R-23 | PENDING 2026-04-25 | Execution owned by #421 (full overnight 5-story, 3-wave realistic run). Covers IT-01's R-set plus R-02 (re-invocation reuse) by virtue of the multi-wave/multi-day run profile. Pass evidence will include start/end timestamps, total elapsed, list of merged flight SHAs, kahuna→main merge SHA, full Discord transcript. No human input between invocation and morning check. |
| MV-01 | R-19 | PENDING 2026-04-25 | Execution owned by #422; observed during the IT-01 run. Pass evidence will include the captured `#wave-status` channel transcript with notification ordering verified. |
| MV-02 | R-18 | PENDING 2026-04-25 | Execution owned by #422; observed during the IT-01 run. Pass evidence will include screenshots of the wave-status dashboard HTML showing active `kahuna_branch`, accurate flight counts, and action-label transitions. |
| MV-03 | R-16 | PENDING 2026-04-25 | Execution owned by #422; observed during the IT-03 run. Pass evidence will include screenshots of the status panel showing `gate_evaluating` → `gate_blocked` with failure-reason field rendered. |
| MV-05 | R-03 | PENDING 2026-04-25 | Execution owned by #422; observed after the IT-01 run. Pass evidence will include the post-run `git branch -a --remotes` output confirming the kahuna branch was deleted. |
| MV-06 | R-09 | PENDING 2026-04-25 | Execution owned by #422; observed during IT-11. Pass evidence will include the unrelated MR's normal-flow merge record. |
| MV-07 | R-22 | PENDING 2026-04-25 | Execution owned by #422. Setup: synthetic wave-state with `kahuna_branch.created_at` > 48h ago. Pass evidence will include the captured `wave_health_check` warning output and the confirmation that wave execution was not blocked. |

**Coverage check:** every R-## (R-01 through R-23) appears in the Requirements Covered column of at least one verification row. No unverified R-## was found, so no follow-up bug is required at this time. Final disposition (PASS/FAIL per row) and the global "every R-## has at least one PASSING verification item" claim will be confirmed when #420, #421, #422 close.

### Appendix D: Glossary

- **KAHUNA** — the integration-branch pattern defined by this spec. Also: "Big Kahuna" — the single merge per Plan onto main.
- **kahuna branch** — `kahuna/<plan-id>-<slug>`, per-Plan ephemeral integration branch.
- **Sandbox** — the relaxed-settings property of a kahuna branch (auto-merge on CI-green, no approvals required).
- **Trust score** — the composite of four signals evaluated in parallel before kahuna→main auto-merge (R-12..R-15 + R-23).
- **Orchestrator / Prime / Flight** — the three Wavemachine v2 agent roles per §1.4.
- **Proving-ground** — the specific GitLab project used for integration test execution (TBD).

### Appendix R: References

- Wavemachine v2 Dev Spec / Plan #384 (claudecode-workflow) — historically filed as `type::epic` pre-taxonomy; the taxonomy rework (Plan `docs/phase-epic-taxonomy-devspec.md`) renames in-flight references to Plan.
- commutativity_verify prior art: existing pairwise implementation in `mcp-server-sdlc/handlers/commutativity_verify.ts`
- gl-settings operations module pattern: `gitlab-settings-automation/gl_settings/operations/__init__.py`
- Discord-watcher filter convention: `docs/discord-watcher.md`
- CLAUDE.md mandatory pre-commit gate: current state of `CLAUDE.md`
