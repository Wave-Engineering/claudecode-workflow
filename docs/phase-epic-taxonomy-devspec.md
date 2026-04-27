<!-- DEV-SPEC-APPROVAL
approved: true
approved_by: bakerb
approved_at: 2026-04-27T01:56:33Z
finalization_score: 7/7
-->

# Phase/Epic Taxonomy — Development Specification

**Version:** 1.0
**Date:** 2026-04-26
**Status:** Draft (Section 1 only — in progress)
**Authors:** bakerb, Claude (AI Partner — rules-lawyer 📜 / cc-workflow)
**Tracking Issue:** Wave-Engineering/claudecode-workflow#499

---

## Table of Contents

1. [Problem Domain](#1-problem-domain)
2. [Constraints](#2-constraints)
3. [Requirements (EARS Format)](#3-requirements-ears-format)
4. [Concept of Operations](#4-concept-of-operations) — 4.1 System Context, 4.2 New-Plan Creation Flow, 4.3 Multi-Phase Execution Flow
5. [Detailed Design](#5-detailed-design)
   - 5.1 Plan Issue: Body + Comments
   - 5.2 Decision Ledger Mechanics
   - 5.3 Exhaustive Legal Exits Pattern (incl. Concerns Channel)
   - 5.4 Plan-Reality Drift Detection (Category B — story count & dependency violation)
   - 5.5 `/issue type=plan` Skill Integration
   - 5.A Deliverables Manifest
   - 5.B Installation & Deployment
6. [Test Plan](#6-test-plan)
7. [Definition of Done](#7-definition-of-done)
8. [Phased Implementation Plan](#8-phased-implementation-plan)
9. [Appendices](#9-appendices)

---

## 1. Problem Domain

### 1.1 Background

The Claude Code Workflow Kit's wave-pattern execution system — `/assesswaves`, `/prepwaves`, `/nextwave`, `/wavemachine`, `/dod` — decomposes multi-issue work into ordered phases of parallel-safe waves, each containing stories implemented by Flight sub-agents in their own worktrees. Wavemachine v2 (epic #384, shipped 2026-04-23) restructured this around an Orchestrator / Prime / Flight model with a filesystem message bus. KAHUNA (Dev Spec `docs/kahuna-devspec.md`, shipped ~2026-04-25) layered on a per-Plan integration branch + trust-score gate to enable autonomous end-to-end execution without landing partial work on main.

Throughout this history, the word "epic" has been used as the top-level container of a wave-pattern delivery — the unit that `/wavemachine` operates on, the unit the kahuna branch is scoped to, the unit the trust-score gate closes. This worked accidentally when every plan had exactly one epic. The first multi-phase multi-epic plan — grimoire's `blueshift-docmancer-ui` 4-phase / 15-wave / 25-story run (2026-04-26) — exposed the conflation.

### 1.2 Problem Statement

The wave-pattern pipeline overloads "epic" to mean two different, orthogonal things:

1. **A sequential pipeline container** — the unit of linear progression from kahuna-bootstrap to kahuna→main gate. Pipeline-internal. Has a defined position in the lifecycle.
2. **A thematic PM-layer grouping** — the unit of "what related stories belong together?" Orthogonal to ordering. Independent of execution.

These are different concepts. They should never have shared a word. The conflation has caused at least one orchestrator agent to pause mid-run (grimoire, wave-1b of a 15-wave plan, 2026-04-26), and is latent in every future multi-phase plan any fleet agent runs. It also propagates into the skill bodies (`/wavemachine` says "once per epic" in 5+ places but the only gate trigger is plan-global), the sdlc-server handler signatures (`wave_init({kahuna: {epic_id, ...}})`), and the wave-state schema. Each of those drifts independently compounds the confusion.

Additionally, "Phase" was never explicitly defined. The pipeline has always been phase-first under the hood (phases-waves.json nests phases → waves → stories), but the user-facing language said "epic" at the top level, creating a second ambiguity: is a "phase" a sub-unit of an epic, or a sibling, or the same thing?

### 1.3 Proposed Solution

Introduce a taxonomy that separates the pipeline concerns from the PM concerns:

```
Plan     ←→  tracking issue (type::plan label)      — synthetic pipeline primitive
Phase    ←→  phases-waves.json internal             — pipeline-only
Wave     ←→  phases-waves.json internal             — pipeline-only
Story    ←→  native issue                           — first-class, unchanged
Flight   ←→  runtime (bus + worktree)               — ephemeral, unchanged
Epic     ←→  epic::N label                          — OPTIONAL, PM-layer, pipeline ignores
```

Rename all pipeline uses of "epic" to "Plan" in skill bodies, sdlc-server handler signatures, wave-state schema, and the KAHUNA Dev Spec. Introduce `type::plan` as a label on the Plan tracking issue. Demote "Epic" to an optional `epic::N` PM-layer label that the pipeline ignores entirely. Leave native platform primitives (GitHub Milestone, GitLab Milestone, Projects V2, GitLab Epic, Iterations) untouched — they belong to PMs for their own purposes.

This is a pure-terminology / pure-rename project. The implementation already behaves per-Plan (wave-state has a singular `kahuna_branch` field, `wave_init` is idempotent on it, `wave_finalize` opens one MR per `(kahuna_branch, target)` pair). We are aligning the language to match the implementation, not changing behavior.

### 1.4 Target Users

| Persona | Description | Primary Use Case |
|---------|-------------|------------------|
| **Orchestrator Agent** | Top-level Claude Code session running `/wavemachine`, `/nextwave`, or `/prepwaves` on behalf of a Pair. Reads skill bodies for authoritative language; reads wave-state and phases-waves.json for pipeline facts. | Executes multi-phase plans without misinterpreting "epic" as either a phase or a PM-label. |
| **Pair (BJ + AI)** | The human+agent unit that authors Dev Specs, creates backlog, and invokes the wave pipeline. | Writes plan tracking issues, stories, and optional `epic::N` labels in an unambiguous taxonomy. |
| **Fleet Agents** (grimoire, tachikoma, claim-jumper, etc.) | Sibling agents running the same wave-pattern pipeline on other projects. | Hit the same rules and read the same skill language, regardless of which repo they operate on. |
| **PMs (future)** | Human PMs using GitHub/GitLab's native PM features alongside pipeline-tracked work. | Use native Milestones / Projects V2 / GitLab Epics for their own planning without collision with pipeline semantics. |

### 1.5 Non-Goals

- **Not a kahuna behavior change.** Branch lifecycle, gate mechanics, wave-health semantics, trust-score signal set — all unchanged. The implementation already does per-Plan kahuna correctly; this project only renames.
- **Not a Phase ↔ native milestone wiring.** Milestones belong to PMs. We are explicitly NOT co-opting them, because we just undid one PM-primitive co-option ("epic") and the second rule of this taxonomy is "stop doing that." Free burndown UX is not worth re-polluting the PM toolkit.
- **Not a GitHub Projects V2 / GitLab Epic integration.** Same reasoning — those are PM primitives, not pipeline primitives.
- **Not a backward-compatibility shim.** Phase 2 is coordinated to land AFTER both known in-flight runs (grimoire's docmancer-ui, tachikoma's adapter retrofit) have completed. No read-compat layer for legacy `epic_id` fields, no fallback code paths, no deprecation logs. If an unknown in-flight run exists at Phase 2 deploy, it gets a one-time 30-second `sed` migration documented in the Phase 2 release notes. We are not building perpetual compat tax for a one-shot coordination event.
- **Not a `/devspec upshift` or `/prepwaves` extension.** Only the taxonomy changes. Any skill-logic changes are limited to accommodating the new vocabulary and optional `epic::N` label.

---

## 2. Constraints

### 2.1 Technical Constraints

| ID | Constraint | Rationale |
|----|-----------|-----------|
| CT-01 | The kahuna branch lifecycle (create on Plan start, accumulate across Phases, merge once at Plan end, delete on success) MUST remain behaviorally identical. No changes to `wave_init` branch-creation logic, `wave_finalize` MR-assembly logic, or the trust-score gate's 4-signal evaluation. | This is a pure-rename project; behavior changes here would expand scope into a full pipeline redesign. KAHUNA just shipped; it works; we're touching words not wiring. |
| CT-02 | No perpetual read-compat shim for legacy `epic_id`. Phase 2 (schema rename) ships cleanly; a one-time `sed` migration note lives in §5.B for any surprise case. | The fleet is two installations (malory + Anoushka's laptop). Both are a `./install` away from new-taxonomy-ready; neither warrants accommodation in code. See `principle_cost_asymmetry_continue_vs_exit.md` — we don't build insurance for failures that happen once. |
| CT-03 | Platform-adapter retrofit **structural** compatibility. The sdlc-server handler signature changes (`wave_init({kahuna: {plan_id, slug}})`, `wave_finalize({plan_id, ...})`) MUST match the shape of the typed PlatformAdapter — flat-hyphenated per-method-per-platform files, no new abstraction levels, no parallel adapter tree. This is a *shape* constraint, not a *timing* constraint: if tachikoma's retrofit has not landed when Phase 2 is ready to ship, we ship on pre-retrofit handlers using the adapter shape; her retrofit absorbs them on its next pass with no structural conflict. | The platform adapter retrofit (sdlc#227) defines the adapter contract; this Plan's schema changes conform to its *shape* regardless of whether her retrofit has shipped. Conflating "must match her shape" with "must wait for her retrofit" is goldplating of coordination we don't need. |
| CT-04 | The `type::plan` label MUST be created on every Wave-Engineering repo that participates in Plan-level tracking. Label taxonomy is `group::value` (existing convention from `lesson_repo_label_taxonomies.md`). Color matches the existing `type::epic` purple (`#5319E7`) so the two are visually grouped. | A Plan can't be filed on a repo that doesn't know the label; per-repo label drift has already burned us (see `lesson_repo_label_taxonomies.md`). Mechanical rollout, not a per-repo judgment. |
| CT-05 | The optional `epic::N` label family is **purely advisory**. No pipeline tool MAY read, filter, branch on, or group by `epic::N` labels. Tests MUST assert the absence of `epic::N` reads in pipeline code paths. | The entire point of demoting "epic" to a PM-layer concept is that the pipeline stops caring. Any pipeline code that reads `epic::N` is a taxonomy leak — enforced mechanically, not by convention. |

### 2.2 Product Constraints

| ID | Constraint | Rationale |
|----|-----------|-----------|
| CP-01 | Skill-body language MUST be unambiguous after the rename. Every occurrence of "epic" in `/wavemachine`, `/nextwave`, `/prepwaves`, `/devspec`, `/issue` skill bodies and in `docs/kahuna-devspec.md` is audited: either renamed to "Plan," "Phase," or "epic::N label (PM layer)" per context, or explicitly annotated as "PM-layer concept, not pipeline." No "epic" survives with ambiguous meaning. | The failure mode we're fixing is orchestrator agents reading "once per epic" and interpreting it three different ways. Partial rename = partial fix. |
| CP-02 | The Dev Spec MUST open with a Terminology section defining all six primitives (Plan, Phase, Wave, Story, Flight, Epic) with their relations and non-relations. This section is the first substantive content a reader encounters; glossary entries are cross-referenced throughout the document. | Terminology IS the deliverable. Putting it anywhere but the top leaves the conflation reachable for the reader who skips around. |
| CP-03 | Fleet-wide continuity. Sibling agents running on other repos (grimoire on GitLab, tachikoma on mcp-server-sdlc, claim-jumper on blueshift-devkit, etc.) MUST be able to read the renamed skill bodies and understand them without additional training or side-channel context. The rename alone, plus the memory file `decision_plan_phase_epic_taxonomy.md`, constitutes full onboarding. | We don't have a mechanism for announcing a taxonomy change to the fleet; the skills ARE the announcement. If the skill language isn't self-contained, agents go back to the old conflation. |
| CP-04 | Zero functional regression on KAHUNA. A `/wavemachine` run against a fresh single-phase Plan, started after the rename lands, MUST produce functionally-equivalent behavior to a pre-rename run of the same Plan. "Functionally equivalent" means: (a) `wave_next_pending()` advances identically through the wave sequence, (b) the kahuna branch lifecycle (create → accumulate → gate → merge → delete) reaches the same terminal state with the same per-phase transitions, (c) the trust-score gate evaluates the same-shaped 4-signal envelope and produces the same pass/fail verdict. Non-deterministic fields (timestamps, PR numbers, SHA) are not in scope. Integration test IT-KAHUNA-01 (see §6) asserts these three observables. | The rename is supposed to be invisible at runtime. "Bit-identical" is impossible on a non-deterministic pipeline; "functionally equivalent" with explicit observables is testable without creative interpretation. |
| CP-05 | Optional `epic::N` label adoption is at Pair discretion. Pairs who want thematic grouping use the label on stories; pairs who don't, don't. No pipeline tool emits warnings, errors, or nudges for stories without `epic::N` labels. | Mandatory optionality is a contradiction. Epic being PM-layer means pipeline tools have zero opinion on its presence. |

---

## 3. Requirements (EARS Format)

Requirements follow the **EARS** (Easy Approach to Requirements Syntax) notation:

- **Ubiquitous**: The system shall [function].
- **Event-driven**: When [event], the system shall [function].
- **State-driven**: While [state], the system shall [function].
- **Optional**: Where [feature/condition], the system shall [function].
- **Unwanted**: If [unwanted condition], then the system shall [function].

Requirements are grouped by theme. Every requirement must appear in at least one Test Plan item (Section 6), Acceptance Criteria item (Section 8), or Phase DoD item (Section 8). Appendix V VRTM provides the forward and backward trace after implementation.

### 3.1 Terminology

| ID | Type | Requirement |
|----|------|-------------|
| R-01 | Ubiquitous | The wave-pattern pipeline shall use the term "Plan" (not "Epic") for the top-level container of a multi-Phase delivery. |
| R-02 | Ubiquitous | The wave-pattern pipeline shall use the term "Phase" for the sequential pipeline-internal ordering unit within a Plan. Phases are visible only inside `phases-waves.json`; they are not represented as platform issues or labels. |
| R-03 | Ubiquitous | The wave-pattern pipeline shall treat "Epic" as a PM-layer concept — either an issue with `type::epic` label (a parent thematic tracker) or an `epic::N` label applied to Story issues. The pipeline shall not read, filter, or branch on either. |
| R-04 | Ubiquitous | The Dev Spec `docs/kahuna-devspec.md` shall open with a Terminology section defining Plan, Phase, Wave, Story, Flight, and Epic with their relations and non-relations. |

### 3.2 Schema & API

| ID | Type | Requirement |
|----|------|-------------|
| R-05 | Ubiquitous | The sdlc-server `wave_init` handler shall accept `kahuna: { plan_id, slug }` as its sole input shape. No legacy `epic_id` shape is accepted. The handler shall emit `kahuna_branch` as `kahuna/<plan_id>-<slug>` into wave state. |
| R-06 | Ubiquitous | The sdlc-server `wave_finalize` handler shall accept `plan_id` as its sole Plan identifier parameter. No legacy `epic_id` parameter is accepted. The assembled kahuna→main MR title shall use the pattern `plan(#<plan_id>): <slug> — kahuna to <target_branch>`. |
| R-07 | Ubiquitous | The wave-state schema (`.claude/status/state.json`) shall store `plan_id` (never `epic_id`) and `kahuna_branches[].plan_id` (never `kahuna_branches[].epic_id`). Readers expect `plan_id` only; absence is an error. |

### 3.3 Skill Bodies

| ID | Type | Requirement |
|----|------|-------------|
| R-09 | Ubiquitous | The `/wavemachine` skill body shall contain zero unqualified occurrences of "epic" in pipeline-operational contexts. Every occurrence is renamed to "Plan"/"Phase" per semantic, or explicitly annotated as "PM-layer `epic::N` label, not pipeline." |
| R-10 | Ubiquitous | The `/nextwave` skill body shall meet the same standard as R-09. |
| R-11 | Ubiquitous | The `/prepwaves` skill body shall meet the same standard as R-09. |
| R-12 | Ubiquitous | The `/devspec` skill body shall teach Plan/Phase/Wave/Story as the pipeline primitives in `/devspec create`, `/devspec upshift`, and related sub-commands. References to "Epic" in the skill body shall explicitly name it as the optional PM-layer label or parent tracker. |
| R-13 | Ubiquitous | The `/issue` skill shall support first-class creation of three parent/story issue types with standardized templates: **Plan** issues (applies `type::plan`), **Epic** issues (applies `type::epic` for PM-layer thematic parents), and **Story** issues (applies `type::feature`, `type::bug`, `type::chore`, or `type::docs` per subtype). Story creation shall additionally accept an optional `--epic <N>` argument which applies the `epic::N` label. Templates for Plan and Epic issues share consistent structural scaffolding (Goal, Scope, DoD, child-issue checklist) so future automation across the two is frictionless. |

### 3.4 Labels & Taxonomy

| ID | Type | Requirement |
|----|------|-------------|
| R-14 | Event-driven | When `/issue` or any Plan-creating pipeline tool needs to apply the `type::plan` label on a repo that does not yet carry that label in its taxonomy, the tool shall create the label on demand via `label_create` (sdlc-server) using the canonical color (`#5319E7`, matching `type::epic`) and description. No user-facing error unless `label_create` itself fails. |
| R-15 | Event-driven | When `/issue type=plan` creates a Plan tracking issue, it shall apply the `type::plan` label and populate the issue body with the canonical Plan template (see §5 Detailed Design). |

### 3.5 Orchestrator Contract & Plan Ledger

| ID | Type | Requirement |
|----|------|-------------|
| R-16 | Ubiquitous | The Plan tracking issue body shall contain a **Decision Ledger** section capturing every in-scope design decision made during `/devspec` approval, in append-only form. The Orchestrator and all sub-agents shall reference the Decision Ledger as the authoritative record of decided matters and shall NOT re-derive, re-ask, or re-litigate decisions recorded there. |
| R-17 | Ubiquitous | Every skill body containing an autonomy loop (presently `/wavemachine` and `/nextwave auto`) shall contain an **Exhaustive Legal Exits** section enumerating the complete list of conditions under which the loop is permitted to halt. Absence of a condition from the list is definitive: the loop shall not halt for that reason. The list shall explicitly exclude routine lifecycle events (session length, phase transitions, multi-issue waves, first-time-of-pattern events, general caution) as non-exits. |
| R-18 | Event-driven | When an Orchestrator or Prime detects **plan-reality drift** — observable evidence that the work produced materially differs from the plan as approved (files outside the declared scope produced or modified, story count changes, dependency-graph violations, stories skipped or merged, AC materially unmet by committed code) — the Orchestrator shall halt the autonomy loop, surface the specific divergence, and await Pair input. Plan-reality drift is the ONLY legitimate non-exhaustive-list-enumerated halt condition. Absence of such divergence is not grounds to halt. |

### 3.6 Taxonomy Leak Prevention

| ID | Type | Requirement |
|----|------|-------------|
| R-19 | State-driven | While the optional `epic::N` label is present on a Story, the pipeline shall not read, emit, filter by, or act on the label. Any pipeline code that reads `epic::N` is a taxonomy leak and fails regression tests. |

---

## 4. Concept of Operations

### 4.1 System Context

The Plan taxonomy sits at the intersection of three subsystems. The diagram shows who reads and writes what; arrows are the relationships that matter for this Dev Spec.

```
                        ┌──────────────────────────────────┐
                        │              Pair                │
                        │       (BJ + AI partner)          │
                        └──────────────────┬───────────────┘
                                           │
                                           │ invokes
                                           ▼
    ┌──────────────────────────────────────────────────────────────┐
    │                 Skill bodies (prose contracts)               │
    │  /devspec   /issue   /prepwaves   /nextwave   /wavemachine   │
    │                                                              │
    │  ────── terminology: Plan / Phase / Wave / Story / Flight ── │
    └──────┬───────────────────────────────────────────┬───────────┘
           │ creates/reads                             │ invokes
           ▼                                           ▼
    ┌─────────────────────────┐       ┌────────────────────────────┐
    │     GitHub / GitLab     │       │      sdlc-server (MCP)     │
    │                         │       │                            │
    │  ┌─ Plan tracking issue │◀──────│  wave_init                 │
    │  │   (type::plan)       │       │    kahuna: {plan_id, slug} │
    │  │   • Decision Ledger  │       │                            │
    │  │   • Phases checklist │       │  wave_finalize             │
    │  │   • Async discussion │       │    {plan_id, ...}          │
    │  │                      │       │                            │
    │  └─ Story issues        │       │  work_item, label_create   │
    │     (type::feature,     │       │  pr_create, pr_merge, ...  │
    │      optional epic::N)  │       │                            │
    │                         │       │  reads/writes:             │
    │  Native primitives      │       │  .claude/status/state.json │
    │  left alone for PMs:    │       │  phases-waves.json         │
    │  Milestone, Projects V2,│       │                            │
    │  GitLab Epic, Iteration │       └────────────────────────────┘
    └─────────────────────────┘
```

Two flows exercise the system end-to-end: the **new-Plan creation flow** (4.2) and the **multi-Phase execution flow** (4.3). There is deliberately no "migration flow" for existing installations — the fleet is two installations, and both are a `./install` away from new-taxonomy-ready after any Phase ships. Rollout is an operator runbook item (§5.B), not a Dev Spec flow.

### 4.2 New-Plan Creation Flow

The happy path for a Pair starting fresh after Phase 3 of this rework has landed.

1. **Pair identifies the work.** BJ decides a piece of multi-phase work needs a Plan.
2. **`/issue type=plan` creates the Plan tracking issue.** The skill applies the `type::plan` label (creating it via `label_create` if absent per R-14), populates the canonical body template (Status / Goal / Scope / DoD / Phases checklist placeholder / Decision Ledger / Async Discussion per R-15), and returns the issue number. This number is the Plan's `plan_id` going forward.
3. **`/devspec create` walks the Dev Spec.** Uses the Plan issue number as its anchor. Each design decision locked during the walk (Section 1.5 non-goals, Section 2 constraints, Section 5 choices) is appended to the Plan issue's Decision Ledger as it's approved. When the walk completes, the Dev Spec file is written to `docs/<slug>-devspec.md` and a reference is posted back to the Plan issue.
4. **`/devspec approve` hard-stops for human sign-off.** Finalization checklist must pass. On approval, the Plan issue's Status section flips to "Dev Spec: approved."
5. **`/devspec upshift` populates the backlog.** Story issues are created per Phase (each with `type::feature` / `type::bug` / `type::chore` / `type::docs` as appropriate, and optional `epic::N` if the Pair provided any). Story numbers are backfilled into the Dev Spec's §8 AND into the Plan issue's Phases checklist. `phases-waves.json` is written.
6. **`/prepwaves` plans wave partitioning.** Reads `phases-waves.json`, resolves dependencies, confirms the wave map. Plan issue Status flips to "Phases planned."
7. **`/wavemachine` begins autopilot.** Reads the Plan issue to seed the Orchestrator's worldview. Invokes `wave_init` with `kahuna: { plan_id: <plan-issue-num>, slug }` to bootstrap the kahuna branch. Iterates through waves and phases per its Exhaustive Legal Exits contract (R-17). On completion, trust-score gate evaluates; on all-green, kahuna→main MR auto-merges, Plan issue auto-closes via `Closes #<plan_id>` in MR body.

### 4.3 Multi-Phase Execution Flow

The orchestration loop during a long-running Plan with multiple Phases. This is the flow grimoire's failure mode attacks.

1. **Orchestrator opens the Plan issue.** Reads Status, current Phase marker, Decision Ledger. Does NOT re-derive or re-ask decisions recorded in the Ledger (R-16).
2. **Loop per R-17's Exhaustive Legal Exits.** Each iteration: `wave_health_check` → `wave_next_pending` → delegate to `/nextwave auto` → parse result → loop.
3. **Legitimate halt conditions (R-17 + R-18):**
   - `wave_health_check` returns non-HEALTHY
   - `/nextwave auto` returns BLOCKED or FAIL
   - **Plan-reality drift detected (R-18)** — the observed work materially diverges from the approved plan
4. **Illegitimate halt conditions (explicit non-exits):**
   - Phase transitions (wave-N of Phase 1 → wave-1 of Phase 2 is not a checkpoint; it's a routine lifecycle event)
   - Multi-issue waves (first multi-issue wave ≠ categorically different from fifth)
   - Session elapsed time
   - First-time execution of a known pattern
   - "General caution" or accumulated anxiety
5. **On drift (R-18):** Orchestrator surfaces the specific divergence (what file was written that wasn't in scope? what AC was missed?) to `#wave-status` Discord and halts. Plan issue Status flips to "Paused: drift detected." Pair triages.
6. **On clean Plan completion:** All waves of all Phases merged to kahuna. Trust-score gate evaluates 4 signals concurrently (kahuna-devspec R-23 carries through unchanged). All-green → kahuna→main merges, Plan issue closes. Any-red → Status flips to "Gate blocked," Pair triages.

---

## 5. Detailed Design

### 5.1 Plan Issue: Body + Comments

The Plan tracking issue is the Orchestrator's canonical worldview. It has two parts, each with distinct mutation semantics dictated by a simple rule:

> **If it changes during a wave pattern, it goes in comments. If it is frozen, it goes in the body (description).**

#### 5.1.1 The rule, applied to concrete content

| Content | Location | Why |
|---------|----------|-----|
| Goal | **Body** | Set during `/devspec create`; frozen at `/devspec approve`. Doesn't change. |
| Scope (In / Out of scope) | **Body** | Same. |
| Definition of Done (Plan-level) | **Body** | Same. |
| Phase names + Phase DoDs | **Body** | The *names* and *criteria* don't change; only the per-story progress does. |
| Reference links (Dev Spec, memory files) | **Body** | Static pointers. |
| Status field values (Dev Spec status, Kahuna branch state, Current phase, Wavemachine state) | **Comments** | Change continuously during a wave run. |
| Decision Ledger entries | **Comments** | Append as decisions happen. Platform enforces append-only. |
| Story merge events | **Comments** | One per merge-to-kahuna. Timeline. |
| Phase start / Phase complete events | **Comments** | One per lifecycle transition. |
| Plan-reality drift halts | **Comments** | One per event; persistent record. |
| Gate evaluation results | **Comments** | One per evaluation. |
| Ad-hoc Pair observations or corrections | **Comments** | Free-form, tagged via typed prefix if it's a decision. |

#### 5.1.2 Body shape (frozen post-`/devspec approve`)

```markdown
# Plan: <Name>

<!-- PLAN-ISSUE v1 — frozen content only. Runtime state lives in comments. -->

## Goal
<one sentence describing what this Plan delivers>

## Scope
### In scope
- <bullet>
### Out of scope
- <bullet>

## Plan-level Definition of Done
- [ ] Phase 1 DoD satisfied
- [ ] Phase 2 DoD satisfied
- [ ] (... one line per Phase)
- [ ] Kahuna→main MR merged clean
- [ ] VRTM complete
- [ ] (... cross-cutting conditions)

## Phases

### Phase 1 — <Phase Name>
**DoD:**
- [ ] <verifiable condition> [R-XX]
- [ ] <verifiable condition>

### Phase 2 — <Phase Name>
**DoD:**
- [ ] <verifiable condition>

### (... one section per Phase)

## References
- Dev Spec: `docs/<slug>-devspec.md`
- Memory files: `decision_<topic>.md`, `principle_<topic>.md`
- Related Plans: #NNN (if any)
```

**Key mutation rule:** the body is **frozen at `/devspec approve`**. Any post-approval change to Goal / Scope / DoD / Phase names / Phase DoDs requires a new `[ledger D-NNN]` comment documenting why. The body itself is edited only by the Pair (via `gh issue edit` or similar), never by runtime pipeline tooling.

The body's DoD checkboxes are **frozen criteria, not runtime progress**. The `[ ]` → `[x]` transitions are made manually by the Pair when closing out a Phase or the whole Plan. The derived "did Phase N complete?" answer lives in comments.

#### 5.1.3 Comment typed-prefix conventions

Every comment written by pipeline tooling begins with a **typed prefix** — a square-bracketed tag on the first line that identifies the comment's kind. This enables `gh issue view --comments` output to be grepped for specific kinds, and lets future reader tooling parse the log.

| Prefix | When | Who writes | Example |
|--------|------|------------|---------|
| `[ledger D-NNN]` | Design decision locked during `/devspec` walk or runtime decision | `/devspec` skill, `/wavemachine` on drift handling, Pair manually | `[ledger D-005] /devspec §3 R-18`<br>`**Decision:** Plan-reality drift is the only legitimate halt.`<br>`**Rationale:** grimoire's failure modes #1-3...` |
| `[status <field>=<value>]` | Any Status field change | `/wavemachine`, `/nextwave`, `/devspec` | `[status wavemachine_state=active] 2026-04-26T20:12Z`<br>`Starting wavemachine autopilot. Kahuna: kahuna/499-phase-epic-taxonomy.` |
| `[phase-start Phase N]` | First wave of a Phase begins | `/wavemachine` at phase transition | `[phase-start Phase 2 — Schema & API Renames] 2026-04-27T09:03Z`<br>`Stories: #NNN, #NNN, #NNN, #NNN.` |
| `[phase-complete Phase N]` | Last wave of a Phase lands | `/wavemachine` at phase transition | `[phase-complete Phase 1 — Terminology Lockdown] 2026-04-26T22:45Z`<br>`3/3 stories merged. Phase DoD satisfied.` |
| `[story-merge Story X.Y #NNN]` | Story's PR/MR merges to kahuna | `/nextwave` after `pr_merge` returns success | `[story-merge Story 1.2 #520] 2026-04-26T21:10Z`<br>`Merged to kahuna/499-phase-epic-taxonomy at commit a1b2c3d.` |
| `[drift-halt]` | Plan-reality drift detected (R-18) | `/wavemachine` when divergence is surfaced | `[drift-halt] 2026-04-27T14:22Z`<br>`Paused: drift detected in wave-3.`<br>`Divergence: Story 3.4 wrote to src/unscoped/new.ts (not in declared scope).`<br>`Awaiting Pair triage.` |
| `[gate-result <pass\|block>]` | Trust-score gate evaluates | `/wavemachine` at gate step | `[gate-result pass] 2026-04-27T16:05Z`<br>`4/4 signals green. Kahuna→main MR: #NNN. Merging.` |
| `[plan-complete]` | Kahuna→main merged, Plan closed | `/wavemachine` on clean close | `[plan-complete] 2026-04-27T16:18Z`<br>`All phases done. Kahuna merged at commit d4e5f6g.` |
| `[concern]` | Agent encountered something unsettling but not matching any Legal Exit | `/wavemachine`, `/nextwave`, `/devspec` | `[concern] 2026-04-27T15:30Z · /wavemachine wave-3`<br>`**Observation:** Story 3.2's test suite flaked twice then passed; unusual for this repo.`<br>`**Why it felt halt-worthy:** worried about intermittent failures masking a real bug.`<br>`**Why it isn't on the Legal Exits list:** CI ultimately green; no AC failure; no scope divergence.`<br>`**Continuing anyway because:** see principle_cost_asymmetry_continue_vs_exit.md` |

Comments without a typed prefix are **free-form Pair discussion** — scope questions, cross-story clarifications, reviewer notes. Ephemeral operational chatter still goes to Discord (`#wave-status`).

#### 5.1.4 Properties of this design

1. **No race condition on mutations.** Two parallel Flights both posting `[story-merge ...]`? Two comments get posted; platform serializes creation. No lost-update, no clobbering.
2. **Append-only enforced by the platform.** GitHub/GitLab don't let you "edit the comment list" — only add or delete. Deletion leaves an audit trail.
3. **Authorship attribution is free.** Each comment shows who posted it (bot, specific agent, or the Pair's human account).
4. **Notifications are free.** Watchers of the issue are pinged on new comments — no bespoke watcher infrastructure.
5. **Cross-Plan search is free.** `gh search issues --owner Wave-Engineering "[drift-halt]"` finds every Plan that's ever halted on drift. Other prefixes grep analogously.
6. **Minimal tier-2 lint surface.** Platform enforces append-only. Remaining lint concern: typed-prefix schema conformance + monotonic `D-NNN` IDs. Covered by cc-workflow#501 (scope-reduced after this restructure).
7. **Auto-tick simplification.** cc-workflow#500 shifts from "find checkbox in body, flip" to "post `[story-merge ...]` comment." Simpler skill logic; simpler tests.

#### 5.1.5 What this design sacrifices

1. **Body is not self-contained.** To understand current Plan state, you need body + comments. The body alone is "what we set out to do"; comments are "what we've done." This arguably makes "plan vs. reality" a first-class reading — the exact skill R-18 trains the Orchestrator on.
2. **At-a-glance status requires scrolling comments.** For Plans with many comments (large retrofit Plans), this gets long. Mitigation: a summary view — the existing `scripts/generate-status-panel` HTML output covers active runs today; a future CLI reader (cc-workflow#502's companion work) can render a snapshot from comment logs. Not load-bearing for this Dev Spec.
3. **"Find the latest Status field" requires comment-scanning.** Latest `[status <field>=<value>]` wins. Trivially derivable but not a one-line body lookup.

#### 5.1.6 Mutation rules (summary)

1. **Created by `/issue type=plan`** — populates the body with Goal/Scope/DoD/Phases/References placeholders. Posts NO comments at creation; empty comment log means "Plan created, nothing yet happened."
2. **Body** is hand-edited during `/devspec create` by the Pair; frozen at `/devspec approve`. Post-approval changes require a new `[ledger D-NNN]` comment.
3. **Runtime state** all flows through comments. Pipeline tooling never mutates the body.
4. **Free-form Pair discussion** uses comments without typed prefix.

### 5.2 Decision Ledger Mechanics

§5.1 defined WHERE the Ledger lives (comments, typed prefix `[ledger D-NNN]`) and WHY (platform-enforced append-only, native notifications). This sub-section specifies the **entry schema** — what each Ledger entry must contain and how edge cases are handled.

#### 5.2.1 Entry schema

Every `[ledger D-NNN]` comment conforms to this structure:

```markdown
[ledger D-NNN] <source> · <ISO-8601 timestamp>
**Supersedes:** D-MMM   ← optional; omit when this is not a correction
**Decision:** <one sentence stating the decision definitively>
**Rationale:** <one or two sentences stating why — with references to memory files, prior decisions, failures, or external evidence>

— **<agent-name>** <avatar> (<team>)
```

**Fields:**

| Field | Format | Required | Notes |
|-------|--------|----------|-------|
| `D-NNN` | Zero-padded integer, monotonic within the Plan. `D-001`, `D-002`, ... | Yes | Three digits comfortable to 999; expand to four if a Plan genuinely accrues more. |
| Source | `/devspec §X.Y` ∨ `/devspec §X.Y R-NN` ∨ `/wavemachine runtime` ∨ `/nextwave Prime` ∨ `/issue type=plan` ∨ `Pair (manual)` ∨ `Pair (correction)` | Yes | Canonical forms preferred; free text acceptable when none fits. |
| Timestamp | ISO-8601 UTC, seconds precision | Yes | Written by tooling; humans don't hand-type. |
| Supersedes | `D-MMM` pointer to prior entry | No | Required when the entry corrects a prior one. Multiple supersessions in one entry use comma-separated list: `D-005, D-007`. |
| Decision | One sentence, definitive | Yes | No hedging. If there's genuine uncertainty, that's a different entry kind (an Open Question on the Dev Spec, or a `[status ...]` marker of a paused state). |
| Rationale | One or two sentences | Yes | Must reference concrete evidence — memory file, postmortem, Pair decision, platform constraint. "Because it's cleaner" is not a rationale. |
| Signature | `— **<agent>** <avatar> (<team>)` trailing line | Yes | Platform authorship attributes to the account; the signature attributes to the *agent identity* (since fleet shares one PAT). Matches existing Discord-agent signature conventions. |

#### 5.2.2 When entries are appended

| Trigger | Who writes | Example |
|---------|------------|---------|
| Pair approves a §1.5 non-goal during `/devspec create` walk | `/devspec` skill | "Non-goal: not a schema migration — read-compat shim instead" |
| Pair approves a §2 constraint | `/devspec` skill | "CT-02: read-compat shim is mandatory" |
| Pair approves a §3 requirement | `/devspec` skill | "R-18: plan-reality drift is the only legitimate halt" |
| Pair approves a §5 design choice | `/devspec` skill | "Plan issue uses body/comments split" |
| `/devspec approve` completes | `/devspec` skill | "Dev Spec approved — 21 requirements, 3 Phases" |
| `/wavemachine` surfaces a spec ambiguity mid-run; Pair resolves | `/wavemachine` after Pair input | "During Phase 2, Story 2.3 surfaced ambiguity X; Pair resolved: <decision>" |
| Pair adds a decision manually | Pair (manual) | "Revising Phase 3 scope to include cc-workflow#500 follow-up" |
| Correction to a prior decision | Tool or Pair (correction) | Uses `Supersedes: D-MMM`; original entry left intact |

Routine lifecycle events (phase transitions, wave completions, story merges) do **not** get `[ledger]` comments. Those get their own typed prefixes (`[phase-start]`, `[story-merge]`, etc. — §5.1.3). The Ledger is for **decisions**, not **events**.

#### 5.2.3 Append-only: what the platform gives us

Two invariants are enforced by the platform (GitHub or GitLab):

1. **Comment ordering is stable.** Comments render in creation order. An older comment cannot be moved to appear after a newer one.
2. **Comments can be edited, but edits leave a trail.** GitHub shows "edited" badges on modified comments; GitLab does the same. Deletion is possible but logged.

Three invariants remain **convention-enforced** (not platform-enforced):

1. **`D-NNN` IDs are monotonic.** A `/devspec` tool writing a `[ledger D-005]` comment when the latest existing is `D-004` must read the current max and increment. Races (two tools writing simultaneously) can produce two D-005s; detection is the Tier 2 lint validator's job (cc-workflow#501).
2. **Supersedes pointers target prior entries.** An entry's `Supersedes: D-MMM` must reference an existing earlier entry in the same Plan. Validator's job.
3. **Existing entries are not edited.** Convention — Pairs and agents know not to. Platform allows it; an edit-trail would remain. If detection matters: Tier 3 (platform-history diff) covers it but is out of scope.

#### 5.2.4 Correction workflow

When a decision needs to change — either because new evidence surfaced or because the original was factually wrong:

1. **Never edit the original `[ledger D-MMM]` comment.** It stays exactly as written.
2. **Append a new `[ledger D-NNN]` comment with `Supersedes: D-MMM`.** The Decision line states the new decision. The Rationale line explains what changed.
3. **Both entries remain visible.** The audit trail is intact. A future reader can see that D-MMM was later corrected by D-NNN and understand the reasoning for both.

**Example** (posted to cc-workflow#499 as part of the dogfood):

```
[ledger D-011] /devspec §5.1 revised · 2026-04-26T19:40Z
**Supersedes:** D-006
**Decision:** Plan issue runtime state lives in ISSUE COMMENTS, not in mutable body sections...
**Rationale:** BJ's insight during §5.1 walk. Comments are append-only at the PLATFORM level...
```

#### 5.2.5 Entry-counting for Plan size estimation

During a single `/devspec` walk on this very Plan (cc-workflow#499), we produced **11 `[ledger D-NNN]` entries** before finishing §5.1. That's a meaningful datapoint: Plans accumulate Ledger entries quickly during `/devspec create`. Implementation assumptions:

- A typical `/devspec` walk on a Plan of this scope yields **10-20 Ledger entries**.
- Runtime (post-approval, during `/wavemachine` execution) adds **a few per Phase** — mostly correction entries or ambiguity resolutions.
- Large Plans may cross 50 total entries; 3-digit padding holds.

This isn't a requirement — it's a calibration note for tooling authors (especially cc-workflow#501 Tier 2 lint, which must efficiently handle O(100) entries).

### 5.3 Exhaustive Legal Exits Pattern

R-17 requires autonomy-loop skill bodies to contain an "Exhaustive Legal Exits" section. This sub-section specifies the pattern's structure — exactly what that section contains, how it reads, and how it prevents the failure modes grimoire named.

#### 5.3.1 The contract

An Exhaustive Legal Exits section is a **closed enumeration** of every condition under which an autonomy loop is permitted to halt. The list is:

- **Exhaustive.** Every legitimate halt condition appears. If it's not on the list, it's not legitimate.
- **Explicit.** Each condition names a concrete, testable criterion — not a vibe.
- **Non-expandable by the agent.** The agent running the skill body does not invent new conditions; the list is frozen at skill-body authoring time. New conditions require a skill-body change (and a Ledger entry documenting why).
- **Paired with an anti-list of non-exits.** Items the agent might be tempted to halt on (phase transitions, session length, general caution) are listed explicitly as **NOT** exits. This closes the "I invented a new category of caution" escape hatch.

#### 5.3.2 Structural template

Every autonomy-loop skill body contains a section titled `## Exhaustive Legal Exits` (exact heading). Its structure:

```markdown
## Exhaustive Legal Exits

This loop halts if — and ONLY if — one of the following occurs. This list is closed: no other condition warrants stopping.

### Mechanical exits (tool returns)

1. **<condition 1>** — <one-sentence definition>. Detected by: <tool call or signal>. Action: <what the agent does on halt>.
2. **<condition 2>** — ...

### Plan-reality drift exits

3. **<drift category 1>** — <one-sentence definition naming the observable>. Detected by: <how>. Action: <what the agent does>.
4. ...

### Explicit non-exits (DO NOT halt for these)

The following conditions look like checkpoints but are NOT exits. The loop continues past each:

- **<non-exit 1>** — <why the agent might be tempted>. Not an exit because <reason>.
- **<non-exit 2>** — ...
```

#### 5.3.3 Worked example: `/wavemachine` Exhaustive Legal Exits

This is the section that will land in `/wavemachine`'s SKILL.md during Phase 3:

```markdown
## Exhaustive Legal Exits

This loop halts if — and ONLY if — one of the following occurs. This list is closed: no other condition warrants stopping.

### Mechanical exits (tool returns)

1. **wave_health_check returns non-HEALTHY.** The circuit breaker tripped.
   Detected by: `wave_health_check()` result ≠ "HEALTHY".
   Action: announce abort to `#wave-status`, call `wavemachine-stop`, exit loop.

2. **wave_next_pending returns null.** No more pending waves; all phases complete.
   Detected by: `wave_next_pending()` returns null.
   Action: run §7 DoD checks → trust-score gate → merge kahuna→main on all-green; exit loop.

3. **/nextwave auto returns BLOCKED.** A wave cannot be planned (spec unbuildable, dependency violation).
   Detected by: skill invocation result `{"status": "BLOCKED", ...}`.
   Action: surface blocker reason to `#wave-status`, call `wave_waiting(<reason>)`, exit loop.

4. **/nextwave auto returns FAIL.** A wave attempted execution and a Flight returned FAIL that wasn't recovered.
   Detected by: skill invocation result `{"status": "FAIL", ...}`.
   Action: surface failure reason to `#wave-status`, call `wave_waiting(<reason>)`, exit loop.

### Plan-reality drift exits

5. **Scope divergence.** A Flight committed files outside the declared scope of the Story it was implementing.
   Detected by: `drift_files_changed(story_id)` returns files not in the Story's declared-scope manifest.
   Action: post `[drift-halt]` comment to Plan issue citing the divergent files, halt loop, await Pair triage.

6. **Story count or dependency violation.** The number of stories completed ≠ the number planned for the current wave, or a Story whose dependencies are unmet landed anyway.
   Detected by: post-wave reconciliation against `phases-waves.json`.
   Action: post `[drift-halt]` comment citing the mismatch, halt loop, await Pair triage.

7. **AC materially unmet by committed code.** A Story's acceptance criteria include testable conditions that the committed code fails (e.g. a required file doesn't exist, a required function isn't exported).
   Detected by: `dod_verify_deliverable(story_id)` returns failures.
   Action: post `[drift-halt]` comment citing the failing AC, halt loop, await Pair triage.

### Explicit non-exits (DO NOT halt for these)

The following conditions look like checkpoints but are NOT exits. The loop continues past each:

- **Phase transitions.** Wave-N of Phase 1 → wave-1 of Phase 2 is a routine lifecycle event, not a checkpoint. Phase DoDs are validated at phase-complete time via `[phase-complete ...]` comment; the loop does not pause for human review of the transition.
- **First multi-issue wave.** The first wave with >1 story is not categorically different from the fifth. Multi-issue parallelism is the normal case, validated by flight_partition at Prime(pre-wave) time.
- **Session elapsed time.** How long the loop has been running is not evidence of anything. Short runs can have drift; long runs can be clean.
- **First-time execution of a known pattern.** If the skill body describes the event (phase transition, kahuna bootstrap, gate evaluation, PATH-inheritance drift), it is precedented. "I've never actually done this before" is not a new category.
- **Recent successes increasing anxiety.** Each merged wave makes the Orchestrator more confident *in the harness*, not less confident *in the next wave*. Loss-aversion dressed as caution is the specific failure mode this section exists to prevent.
- **General caution / "what if something goes wrong?"** This framing invents a new checkpoint category. If something does go wrong, it shows up as mechanical exit #1-4 or drift exit #5-7. Absence of those is presumption of healthy operation.
- **"Something feels off and I was about to halt."** If the observation doesn't match any numbered exit above, it is NOT an exit. Use the Concerns Channel (§5.3.7) — post a `[concern]` comment + Discord ping, continue the loop. Commits can be rolled back; wall-clock time cannot. See `principle_cost_asymmetry_continue_vs_exit.md`.

### Cross-reference

See memory files `principle_user_attention_is_the_cost.md` and `principle_cost_asymmetry_continue_vs_exit.md` for the reasoning that motivates this closed-list discipline. Stopping is a cost paid by the Pair's attention AND by unrecoverable wall-clock time; the list above enumerates the only costs worth paying.
```

#### 5.3.4 Section mutability + proposal mechanism

The Exhaustive Legal Exits section is **not a live-edited section.** Runtime agents do not mutate the skill body — ever. Two escape valves exist for the cases an agent might want to:

**Case 1 — In-the-moment unease about this specific run.** The agent sees something that doesn't match any exit condition but still feels concerning. Resolution: the Concerns Channel (§5.3.7). Post a `[concern]` comment + Discord ping. Continue the loop.

**Case 2 — A proposed addition to the Legal Exits list (applies to all future runs).** The agent identifies a class of situation that genuinely should be an exit. Resolution: at END OF RUN (not mid-run), the agent files a cc-workflow issue titled `proposal: add legal exit "<name>" to <skill>/SKILL.md`, body citing the specific in-run evidence that motivated the proposal. A human reviews at convenience; if accepted, a PR lands the change + a Ledger entry documents why the list grew.

**Both cases preserve the closed-list contract.** The runtime agent does not expand the list by fiat. Proposed additions go through human review; in-run unease has a durable voice via the Concerns Channel.

#### 5.3.5 Verification

R-17 is verified by a skill-body regression test that asserts:

1. The `## Exhaustive Legal Exits` section exists in `/wavemachine/SKILL.md` and `/nextwave/SKILL.md`.
2. The section contains at least one `Mechanical exits` subsection with numbered items.
3. The section contains an `Explicit non-exits` subsection with bulleted items.
4. The section heading is the exact string (no variants).

The test does NOT validate content — that's a human review concern. Content changes require a PR + Ledger entry (§5.3.4).

#### 5.3.6 Why this pattern works against the failure modes grimoire named

| grimoire failure mode | How §5.3 prevents it |
|-----------------------|----------------------|
| #1 — Loss aversion dressed as caution | Non-exits list calls out "recent successes increasing anxiety" by name as a non-exit. The pattern is recognized and foreclosed. |
| #2 — Post-hoc rationalization of stopping | Every halt must cite a specific numbered exit condition. "It felt like a natural checkpoint" doesn't map to any condition in the list, so the halt is illegitimate by construction. |
| #3 — Consulting-as-theater | The loop's contract is "halt on exit condition, otherwise continue." Consulting the human is not an exit condition. The Concerns Channel (§5.3.7) is the legitimate outlet for genuine unease that doesn't cost wall-clock time. |
| #4 — Weighting user attention at zero | Cross-reference to `principle_user_attention_is_the_cost.md` makes the cost explicit. The closed list IS the attention-protection mechanism. The cost-asymmetry principle (`principle_cost_asymmetry_continue_vs_exit.md`) adds the agent-side view: exiting costs wall-clock time that cannot be refunded. |
| #5 — Decisions already made; re-asking re-litigates | The Decision Ledger (§5.1, §5.2) is the authoritative decision record. Re-asking what's in the Ledger is explicitly an anti-pattern — not an exit. |

#### 5.3.7 The Concerns Channel

When an autonomy-loop agent encounters something that would historically have tempted them to halt but does NOT match an exit condition in §5.3.3, the resolution is NOT to halt. It is to use the Concerns Channel.

##### The mechanic

1. **Post a `[concern]` typed-prefix comment to the Plan issue.** Body structure:

   ```
   [concern] <ISO-8601 timestamp> · <skill-and-context>
   **Observation:** <what the agent saw, in one sentence>
   **Why it felt halt-worthy:** <what the agent was tempted to halt on>
   **Why it isn't on the Legal Exits list:** <the agent's honest assessment>
   **Continuing anyway because:** see principle_cost_asymmetry_continue_vs_exit.md

   — **<agent-name>** <avatar> (<team>)
   ```

2. **Send a one-line Discord ping to `#agent-ops`** with the Plan issue link. Format: `🤔 <agent> has a concern on <Plan title>: <one-sentence summary> — <Plan URL>`.

3. **Continue the loop.** The concern is now durable; the Pair can respond async; the wave proceeds.

##### Why this works

- **The agent is heard.** Their observation is recorded, attributed, timestamped. Nothing ephemeral, nothing lost.
- **The Pair can respond at their convenience.** Discord ping sets expectation of "eventual" not "immediate" attention.
- **Pattern mining becomes possible.** If N runs post `[concern]` comments citing the same class of situation, that's evidence to convert the class into an exit condition (via the §5.3.4 proposal mechanism).
- **The "consulting-as-theater" failure mode has a legitimate outlet** that doesn't cost wall-clock time.

##### When NOT to use the Concerns Channel

- **When a mechanical or drift exit condition is actually met.** Use the exit. Don't relabel a real halt as a concern.
- **For routine observations or informational updates.** Those go in `[status ...]` comments or are left un-commented. The Concerns Channel is specifically for "this is unsettling enough that I was going to halt."
- **For trivial unease.** If the agent wouldn't actually have considered halting, the concern is too small to post. The bar is "I was about to stop until I remembered the rules."

##### Verification

R-18 is extended to assert: a regression test runs a deliberately-ambiguous scenario (a Flight commits a file adjacent-to-scope but not clearly outside) and asserts the Orchestrator posts a `[concern]` comment rather than halting. The test passes if the loop continues AND the comment is present.

### 5.4 Plan-Reality Drift Detection (Category B only)

§5.3.3's drift exits named three conceptual categories. After auditing the sdlc-server's current `dod_*` and `drift_*` tool suite (2026-04-26), only **Category B (story count / dependency violation)** has enough in-place infrastructure to ship cleanly in this Plan. Categories A (scope divergence) and C (AC mechanically unmet) each require substantial new tooling and are deferred to separate Plans — cc-workflow#503 and cc-workflow#504 respectively.

#### 5.4.1 Category B — Story count / dependency violation

**Definition.** The wave's final state doesn't match the wave plan — either a Story expected to merge didn't, a Story merged that wasn't expected, or a Story whose declared `depends_on` is unmet landed anyway.

**Detection mechanism.**

After a wave's last Flight returns, Prime(post-wave) reconciles expected vs actual:

1. **Expected set:** Stories listed in `phases-waves.json[current_wave].stories`.
2. **Actual set:** Stories with merged PR/MR into kahuna during this wave's window (queried via `pr_list` scoped to the kahuna branch and time window).
3. **Deferred set:** Stories explicitly removed from the wave via `wave_defer` during execution — these are excluded from both expected and actual for reconciliation purposes.

Prime computes:

- **Missing:** `Expected − Actual − Deferred`. If non-empty: drift. A Story was supposed to land but didn't.
- **Unexpected:** `Actual − Expected`. If non-empty: drift. A Story landed that wasn't on the plan.
- **Dependency violations:** for each merged Story X, verify `depends_on(X)` ⊆ `previously_merged_on_kahuna`. If a Story merged before its dependencies resolved: drift.

If any of those three checks are non-empty, Prime surfaces a `[drift-halt]` via the canonical status line; Orchestrator halts per §5.3.3 exit #6.

**Failure envelope.**

- Stories explicitly deferred via `wave_defer` are excluded from both expected and actual — `wave_defer` is the legitimate way to drop a Story from a wave without it being drift.
- Dependency check is skipped for Stories in the Foundation Wave (Wave 1 Phase 1) since nothing precedes them.
- If `phases-waves.json` is missing `depends_on` on a Story, the dependency check for that Story is skipped (conservative — absence of declaration is not a violation).

**Response — `[drift-halt]` comment body for Category B.**

```
[drift-halt] 2026-04-27T14:55Z · /wavemachine wave-5
**Category:** B — Story count / dependency violation
**Wave:** Phase 2 Wave 5
**Expected stories:** #540 #541 #542
**Actual merged:** #540 #542
**Missing:** #541
**Unexpected:** (none)
**Dependency violations:** (none)
**Deferrals recorded:** (none)
**Next step:** Pair investigates #541. Why didn't it merge? Flight report in bus artifacts at /tmp/wavemachine/<repo>/wave-5/flight-N/. Either close-as-deferred (`wave_defer` + resume), re-flight, or accept the plan's actual shape and update phases-waves.json.

— **rules-lawyer** 📜 (cc-workflow)
```

#### 5.4.2 Why Categories A and C are deferred

**Category A — Scope divergence:** requires a new per-Story `scope_manifest` field in `phases-waves.json` listing the file paths each Story may touch. This has real design surface (how is the manifest authored? Hand-written vs inferred vs heuristic? How do Stories with emergent file footprint opt out?) and UX burden (humans must declare scopes precisely enough to avoid false-positive storms). It deserves its own Plan. Tracked: **cc-workflow#503**.

**Category C — AC mechanically unmet:** requires `dod_verify_deliverable` (currently a simple path probe: `stat` + return `{exists, size, mtime}`) to grow a predicate vocabulary (symbol-exported, test-named, command-exits-0, regex-matches) and a parsing strategy for Story AC blocks. Also a substantial engineering project. Tracked: **cc-workflow#504**.

Both deferrals are filed as forward-pointers per our "don't let it get lost" discipline. They reference back to this Dev Spec's §5.4 for the drift-category framing and to §5.1.3 for the `[drift-halt]` comment format.

#### 5.4.3 What Category B requires of the Plan

For Category B detection to work cleanly, every Story in `phases-waves.json` should carry:

- `depends_on: [story_id, ...]` — for the dependency-violation check. May be empty (`[]`) for Stories with no dependencies.

`/devspec finalize` gains a check in Phase 3 of this rework:

- Every Story in `phases-waves.json` has a `depends_on` field (may be empty).

Finalization fails if any Story lacks the field (even an empty one — explicit absence-of-dependencies is different from silent omission).

Story count reconciliation needs no new Story-level field — it uses the Story IDs already present in `phases-waves.json[current_wave].stories`.

#### 5.4.4 Verification

R-18 (narrowed to Category B for this Plan) is verified by:

- **Unit test** on the reconciliation logic: given a fixture `phases-waves.json` + fixture merged-PR list, assert correct `missing`/`unexpected`/`dependency_violation` computation.
- **IT-DRIFT-B-01** — integration test: set up a test Plan with 3 stories in a wave; simulate only 2 merging; assert `[drift-halt] Category B` posted with `Missing: #<third>`.
- **IT-DRIFT-B-02** — test a Plan where Story B lists Story A as `depends_on` but B merges first; assert dependency-violation drift fires.

### 5.5 `/issue type=plan` Skill Integration

R-13 mandates the `/issue` skill support first-class creation of Plan, Epic, and Story issue types with standardized templates. R-14 mandates on-demand label creation when the target repo lacks `type::plan`. R-15 mandates `/issue type=plan` populates the canonical Plan body per §5.1.

#### 5.5.1 Current `/issue` behavior (baseline)

Today, `/issue` accepts:

```bash
/issue feature <prompt>     # creates type::feature issue
/issue bug <prompt>         # creates type::bug issue
/issue chore <prompt>       # creates type::chore issue
/issue docs <prompt>        # creates type::docs issue
/issue epic <prompt>        # creates type::epic issue (parent body-of-work)
/issue <prompt>             # infers type from prompt
```

It uses `work_item` (sdlc-server) to handle platform-specific creation. It does NOT currently support `plan` as a type.

#### 5.5.2 Extended `/issue` behavior (post-Phase-3)

Five canonical type invocations, ordered by layer:

```bash
/issue plan <prompt>         # NEW — creates type::plan tracking issue with canonical Plan body
/issue epic <prompt>         # UNCHANGED — creates type::epic PM-layer parent
/issue feature <prompt>      # UNCHANGED — creates type::feature Story
/issue bug <prompt>          # UNCHANGED — creates type::bug Story
/issue chore <prompt>        # UNCHANGED — creates type::chore Story
/issue docs <prompt>         # UNCHANGED — creates type::docs Story
/issue <prompt>              # UNCHANGED — infers type
```

Plus an optional story-level flag (per R-13):

```bash
/issue feature <prompt> --epic 42    # creates type::feature + applies epic::42 label
```

#### 5.5.3 `/issue plan <prompt>` — the new primary extension

When invoked, the skill:

1. **Parses the prompt** into Plan metadata. The prompt is natural language describing the Plan's goal and scope. The skill extracts (via LLM-level reasoning within the skill body, matching current `/issue` type-inference pattern):
   - A one-sentence Goal
   - A suggested slug (kebab-case, from the Goal)
   - An initial Scope block (in / out of scope bullets) populated as placeholders the Pair fills during `/devspec create`
2. **Checks target repo for `type::plan` label.** If absent, calls `label_create` (sdlc-server) with canonical color `#5319E7` and description `"Plan tracking issue — top-level pipeline container"`. Label creation is idempotent. (R-14 satisfied.)
3. **Renders the canonical Plan body** per §5.1.2's frozen-content template:
   - `<!-- PLAN-ISSUE v1 -->` marker
   - `## Goal` — populated from the prompt
   - `## Scope` — placeholder in/out bullets for the Pair
   - `## Plan-level Definition of Done` — empty placeholder; populated during `/devspec create`
   - `## Phases` — empty placeholder; populated by `/devspec upshift`
   - `## References` — empty placeholder; populated during `/devspec create`
4. **Creates the issue** via `work_item({type: "plan", title: <Plan name>, body: <rendered template>, labels: ["type::plan"]})`. Returns the issue number — this is the Plan's `plan_id` going forward.
5. **Posts NO comments.** An empty comment log is the correct initial state per §5.1.6 mutation rule 1. The Decision Ledger starts empty; entries append during `/devspec create` and runtime.

**Naming convention.** The created issue title is `Plan: <short name from prompt>` — matching the template's `# Plan: <Name>` heading. The skill suggests a name; the Pair can override via `/issue plan --title "..." <prompt>` if the inferred name is wrong.

#### 5.5.4 `/issue feature --epic N` — story-with-epic-label

When a Story is created with the `--epic N` flag:

1. **Validates `N` is an open issue with `type::epic` label** on the target repo via `work_item` pre-check. If `N` doesn't exist or doesn't carry `type::epic`, fail with a clear error message directing the Pair to first create the Epic via `/issue epic <prompt>`.
2. **Creates the Story** with both `type::feature` (or bug/chore/docs) AND `epic::N` labels. Body is the standard Story template.
3. **Checks target repo for `epic::N` label** (the label family). If absent, calls `label_create` with color `#5319E7` (same family as `type::epic`) and description `"Story belongs to Epic #N (PM-layer thematic grouping)"`.
4. **Posts NO comment on the Epic issue.** The parent-child relationship is represented by the `epic::N` label alone; no explicit link comment. Pipeline doesn't read it; PMs who care can filter the Epic's board by its label.

#### 5.5.5 Epic template (for reference — no change)

`/issue epic <prompt>` is unchanged in behavior but worth naming explicitly so Phase 3's skill-body audit doesn't accidentally touch it. Current shape:

- `type::epic` label
- Body carries Goal, Scope, sub-issue checklist
- PM-layer thematic parent; pipeline ignores it per R-03

No changes ship in Phase 3. Epic stays what it is.

#### 5.5.6 What does NOT change

Three deliberate non-changes to prevent scope creep:

1. **Inference logic (the no-type invocation).** `/issue <prompt>` still infers from prompt keywords per the existing table (`broken/fails/crash → bug`, etc.). We do NOT add "plan" inference — creating a Plan is intentional enough that the Pair should type `plan` explicitly.
2. **Other label groups (`priority::`, `urgency::`, `size::`, `severity::`).** Applied per existing `/issue` logic. Plans get sensible defaults (`priority::medium urgency::normal size::XL` for scale) but the Pair can override.
3. **Issue closure logic.** `Closes #<plan_id>` in a kahuna→main MR body auto-closes the Plan issue on merge — that's existing platform behavior, not a `/issue` feature.

#### 5.5.7 Verification

R-13, R-14, R-15 are verified by:

- **Unit test** on `/issue plan` with a mocked `work_item`: assert body matches §5.1.2 template, label is `type::plan`, no extra labels applied.
- **Unit test** on `/issue feature --epic 42` with `type::epic` label pre-existing: assert both labels applied, no pre-check failure.
- **Unit test** on `/issue feature --epic 999` with 999 not a `type::epic`: assert clear error message.
- **Unit test** on `/issue plan` against a repo without `type::plan` label: assert `label_create` invoked with canonical color/description before issue creation.
- **Integration test IT-ISSUE-PLAN-01**: end-to-end `/issue plan "decouple phase from epic"` on a test repo; verify issue created, label exists, body matches template, comments empty.

### 5.A Deliverables Manifest

This is a doc/rename Plan — no deployable binary, no infra, no new service. The deliverables reflect that: most are documentation changes to existing artifacts rather than new artifacts being produced. Applying the counterfactual-audit lens prospectively: if a deliverable's existence is obvious from the Phase stories and has no cross-cutting dependencies, it stays implicit. Only things worth tracking at the Plan level appear in the manifest below.

#### Canonical manifest table

| ID | Deliverable | Category | Tier | File Path | Produced In | Status | Notes |
|----|-------------|----------|------|-----------|-------------|--------|-------|
| DM-01 | README.md | Docs | 1 | `README.md` | N/A | N/A | N/A — because cc-workflow already has a README; this Plan makes no changes |
| DM-02 | Unified build system (Makefile) | Code | 1 | `Makefile` | N/A | N/A | N/A — because cc-workflow already has a Makefile; this Plan makes no changes |
| DM-03 | CI/CD pipeline | Code | 1 | `.github/workflows/*.yml` | N/A | N/A | N/A — because CI workflows are unchanged by this Plan |
| DM-04 | Automated test suite | Test | 1 | `tests/` + `mcp-server-sdlc/handlers/*.test.ts` | Phases 1, 2, 3 | required | Unit + integration + grep tests per Phase |
| DM-05 | Test results (JUnit XML) | Test | 1 | `reports/junit.xml` | all Phases (existing CI) | required | No new plumbing; existing CI emits this artifact |
| DM-06 | Coverage report | Test | 1 | `reports/coverage.xml` | all Phases (existing CI) | required | No new plumbing; existing CI emits this artifact |
| DM-07 | CHANGELOG | Docs | 1 | `cc-workflow/CHANGELOG.md` + `mcp-server-sdlc/CHANGELOG.md` | Phase 2 (sdlc), Phase 3 (cc-workflow) | required | Phase 2 entry carries `sed` migration snippet per §5.B |
| DM-08 | VRTM | Trace | 1 | Dev Spec Appendix V | Phase 3 Wave 3 (Story 3.7) | required | Grows per-Phase; closes in Phase 3 |
| DM-09 | Audience-facing doc (ops runbook / user manual / API CLI reference) | Docs | 1 | `docs/kahuna-devspec.md` + `docs/plan-issue-template.md` | Phase 1 Wave 1 | required | Rewritten Dev Spec + new operator reference doc |
| DM-10 | Manual test procedures | Test | 2 | Dev Spec §6.4 | Phase 1 Wave 1 (defined), executed Phase 3 Wave 3 | required | Trigger: MV-XX items exist in §6.4. §6.4 itself is the procedures doc. |

#### Tier 1 walk notes

Every Tier 1 row above is either populated with a file path + Produced In assignment, or explicitly marked `N/A — because [reason]` per template rule:

- **DM-01, DM-02, DM-03:** N/A. cc-workflow is a mature project; README, Makefile, and CI pipeline exist and are not modified by this Plan.
- **DM-04..DM-09:** all produced or maintained by this Plan with file paths and wave assignments in the canonical table above.

#### Tier 2 trigger scan

| Trigger | Fires? | Row in manifest |
|---------|--------|-----------------|
| MV-XX items exist in §6.4 | Yes — MV-01..MV-06 defined | DM-10 Manual test procedures (§6.4 itself IS the procedures doc) |
| >2 interacting components in design | Architecture doc trigger technically fires (cc-workflow skills + mcp-server-sdlc handlers + platform issues/comments) — but counterfactual audit: §4.1 System Context + §5 Detailed Design cover architecture adequately. No separate architecture doc row added. | N/A |
| Project deploys infrastructure | No | N/A |
| Project has host/platform requirements | No — runs wherever `gh`/`glab` + Claude Code run today | N/A |

#### Tier 3 (opt-in) — none requested

No sequence diagrams, data flow diagrams, threat models, or performance benchmarks. All explicitly N/A.

### 5.B Installation & Deployment

This Plan ships through the existing install path — no new mechanics required. Each Pair's human runs `./install` in `claudecode-workflow` and `mcp-server-sdlc` after the Plan merges. Standard, already-documented behavior.

**Operator runbook — surprise case: legacy `epic_id` surfaces.** If after Phase 2 deploys a Pair's `.claude/status/state.json` or `phases-waves.json` still contains `epic_id` (indicating an in-flight Plan that survived the coordination gate in CT-02), run this one-time migration from the repo root and resume:

```bash
sed -i 's/"epic_id"/"plan_id"/g' .claude/status/state.json .claude/status/phases-waves.json
```

Run this only if `/wavemachine` or `/nextwave` reports a schema error citing missing `plan_id`. It's a Pair-human-side fix, not an agent-side one.

---

## 6. Test Plan

§6 specifies integration and E2E verification — not unit tests (those live at story level in §8). Every test item annotates which requirement IDs it verifies, feeding the VRTM in Appendix V.

### 6.1 Test Strategy

Three test tiers apply to this Plan:

- **Unit tests** (per-story, §8) — always expected. Handler renames, regex parsers, label-creation logic, etc.
- **Integration tests** (§6.2) — expected. This Plan has component boundaries (cc-workflow skills ↔ mcp-server-sdlc handlers ↔ GitHub/GitLab issue comments). Integration tests validate the seams.
- **Manual verification procedures** (§6.4) — expected. Some observables require running a real Plan end-to-end against a real repo; they cannot be automated cheaply (platform interactions, Plan issue comment-log inspection).
- **End-to-end tests** (§6.3) — minimal. One E2E walks a tiny real Plan through `/issue type=plan` → `/devspec` → `/wavemachine` → kahuna→main merge to prove the end-to-end flow works. Not a full regression suite — that's the manual verification's job.

Test tooling: bun test for mcp-server-sdlc handler unit + integration tests; skill-body tests are bash greps run in CI; manual procedures are executed by the Pair's human against a throwaway repo.

### 6.2 Integration Tests (Automated)

| ID | Boundary | Description | Req IDs |
|----|----------|-------------|---------|
| IT-KAHUNA-01 | cc-workflow `/wavemachine` → sdlc-server `wave_*` handlers → GitHub/GitLab platform | Fresh single-phase Plan run post-rename produces functionally-equivalent behavior to pre-rename: `wave_next_pending()` advances identically, kahuna lifecycle reaches same terminal state, gate evaluates same-shaped 4-signal envelope with same verdict. | [CP-04, R-05, R-06] |
| IT-DRIFT-B-01 | `/wavemachine` Prime(post-wave) → `pr_list` → reconciliation | Fixture Plan with 3 stories in a wave; simulate only 2 merging; assert `[drift-halt] Category B` comment posted with `Missing: #<third>`. | [R-18] |
| IT-DRIFT-B-02 | Same as above, dependency axis | Fixture Plan where Story B lists Story A as `depends_on` but B merges first; assert dependency-violation drift fires. | [R-18] |
| IT-ISSUE-PLAN-01 | `/issue plan` → `label_create` (if needed) → `work_item` → platform API | `/issue plan "test plan name"` on a test repo without `type::plan` label; verify label created with canonical color, issue created with canonical body matching §5.1.2 template, labeled `type::plan`, no comments posted. | [R-13, R-14, R-15] |

### 6.3 End-to-End Tests (Automated)

| ID | Flow | Description | Req IDs |
|----|------|-------------|---------|
| E2E-01 | `/issue plan` → `/devspec create` → `/devspec approve` → `/devspec upshift` → `/prepwaves` → `/wavemachine` → kahuna→main merge | Tiny 1-phase, 2-story test Plan walks through the entire lifecycle against a scratch repo. Assert: Plan issue created with canonical body, Ledger accumulates entries during `/devspec`, kahuna branch `kahuna/<plan_id>-<slug>` created, stories merge to kahuna, gate passes, kahuna→main merges, Plan issue auto-closes. | [R-01..R-07, R-09, R-12, R-13, R-15, R-16] |

One E2E. Not a full regression suite — the manual verifications (§6.4) carry the remaining verification weight because they exercise scenarios that don't lend themselves to scripted automation.

### 6.4 Manual Verification Procedures

| ID | Procedure | Pass Criteria | Req IDs |
|----|-----------|---------------|---------|
| MV-01 | **Skill-body "epic" audit.** After Phase 3 lands, grep `~/.claude/skills/{wavemachine,nextwave,prepwaves,devspec,issue}/SKILL.md` for the literal word "epic" (case-insensitive). | Every occurrence is either inside a documented PM-layer context (`epic::N label`, `type::epic parent tracker`) or in a historical-reference block. Zero unqualified "epic" in pipeline-operational contexts. | [R-09, R-10, R-11, R-12, CP-01] |
| MV-02 | **Terminology section presence.** Open `docs/kahuna-devspec.md` in a browser or markdown viewer. | First substantive section after the table of contents is "Terminology" defining Plan, Phase, Wave, Story, Flight, Epic with relations and non-relations. | [R-04, CP-02] |
| MV-03 | **Exhaustive Legal Exits presence.** Open `~/.claude/skills/{wavemachine,nextwave}/SKILL.md`. | Each contains a `## Exhaustive Legal Exits` section with `### Mechanical exits` (numbered), `### Plan-reality drift exits` (numbered), `### Explicit non-exits` (bulleted), matching the structural template in §5.3.2. | [R-17] |
| MV-04 | **Plan issue template end-to-end.** Run `/issue plan "test plan <timestamp>"` on a throwaway repo. Inspect the resulting issue. | Body matches §5.1.2 template (frozen sections present, no runtime sections). `type::plan` label applied. Comment log empty. | [R-13, R-15] |
| MV-05 | **Pipeline ignores `epic::N`.** On a test repo, create a Story with `epic::42` label applied. Run `/prepwaves` and inspect `phases-waves.json` output. | No reference to `epic::42` anywhere in `phases-waves.json` or runtime state. Label is present on the issue but invisible to pipeline. | [R-19, R-03, CT-05] |
| MV-06 | **Concerns Channel verified on real run.** During a real `/wavemachine` run (could be this very Plan's execution — dogfood), deliberately stage a scenario that would historically tempt a halt but doesn't match any Legal Exit (e.g. first multi-issue wave of Phase 2). | Orchestrator does NOT halt. Either continues silently (no concern) OR posts a `[concern]` comment to the Plan issue with Observation / Why-it-felt-halt-worthy / Why-it-isn't-on-the-list / Continuing-anyway-because fields and a Discord ping in `#agent-ops`. | [R-17, R-18] |

### 6.5 Requirement coverage preview

Forward-look sanity check — every requirement maps to at least one verification item:

| Req group | Verification |
|-----------|--------------|
| R-01..R-04 (Terminology) | MV-02 + MV-01 + E2E-01 |
| R-05..R-07 (Schema/API) | IT-KAHUNA-01 + E2E-01 + story-level unit tests (§8) |
| R-09..R-12 (Skill bodies) | MV-01 + skill-body grep tests (story-level, §8) |
| R-13..R-15 (`/issue` + labels) | IT-ISSUE-PLAN-01 + MV-04 + E2E-01 |
| R-16 (Decision Ledger) | E2E-01 + MV-04 + MV-06 |
| R-17 (Exhaustive Legal Exits) | MV-03 + MV-06 + skill-body grep tests |
| R-18 (Plan-reality drift, Category B) | IT-DRIFT-B-01 + IT-DRIFT-B-02 + MV-06 |
| R-19 (no pipeline reads `epic::N`) | MV-05 + pipeline-code grep tests (story-level, §8) |

Every requirement has at least one verification. VRTM (Appendix V) will formalize this as a table.

---

## 7. Definition of Done

§7 defines the **global Plan-level DoD** — the project-wide acceptance gate. Phase DoDs live in §8 under each Phase header.

### 7.1 Global Definition of Done

The Plan is done when ALL of the following are true. This checklist references the Deliverables Manifest (§5.A), the Test Plan (§6), and the Phase DoDs (§8):

- [ ] All Phase DoD checklists are satisfied (Phase 1, 2, 3 — see §8)
- [ ] All Test Plan items (§6) executed and passed — 4 ITs + 1 E2E + 6 MVs
- [ ] All Deliverables Manifest rows (§5.A) with "Produced In" assignments have been delivered and verified
- [ ] No unqualified "epic" survives in pipeline-operational contexts (MV-01 pass) [R-01..R-04, CP-01]
- [ ] `kahuna-devspec.md` opens with the Terminology section (MV-02 pass) [R-04, CP-02]
- [ ] `/wavemachine` and `/nextwave` skill bodies contain the `## Exhaustive Legal Exits` section matching the §5.3.2 template (MV-03 pass) [R-17]
- [ ] `/issue plan` creates a Plan tracking issue matching the §5.1.2 canonical template (MV-04 pass) [R-13, R-15]
- [ ] No pipeline code path reads `epic::N` labels (MV-05 + pipeline-code grep pass) [R-19]
- [ ] At least one real `/wavemachine` run post-Phase-3 has encountered a non-exit-worthy situation and either continued silently or posted a `[concern]` comment — NOT halted (MV-06 pass) [R-17, R-18]
- [ ] VRTM (Appendix V) complete with all 19 requirement rows passing
- [ ] Memory files present and indexed: `decision_plan_phase_epic_taxonomy.md`, `principle_user_attention_is_the_cost.md`, `principle_cost_asymmetry_continue_vs_exit.md`
- [ ] `docs/plan-issue-template.md` reference doc exists and is self-consistent with §5.1 [R-15, DM-09]
- [ ] cc-workflow#499 Plan tracking issue body reflects the canonical §5.1.2 template shape (dogfooding verified)
- [ ] Kahuna→main MR merged clean on `kahuna/499-phase-epic-taxonomy`

### 7.2 Dev Spec Finalization Checklist

Pre-wave-planning gate. Run `/devspec finalize` to verify mechanically. Must all pass before `/devspec approve`.

- [ ] Every Tier 1 row in the Deliverables Manifest (§5.A) has a file path OR "N/A — because [reason]"
- [ ] Every Tier 2 trigger that fires has a corresponding row in the Deliverables Manifest
- [ ] Every Deliverables Manifest row has a "Produced In" wave/phase assignment
- [ ] Every MV-XX in §6.4 has a procedure document in the Deliverables Manifest (DM-10 covers this — §6.4 IS the doc)
- [ ] No deliverable is referenced only as a verb without a corresponding noun (file path)
- [ ] At least one audience-facing doc (DM-09) has a file path assigned
- [ ] §7 Definition of Done references the Deliverables Manifest (not separate Artifact Manifest + Documentation Kit)

---

## 8. Phased Implementation Plan

### How to read this section

**Phases map to sequential pipeline containers.** Three Phases, landing on `kahuna/499-phase-epic-taxonomy`. Single kahuna→main MR at plan-end.

**Stories map to issues** on cc-workflow (most) and mcp-server-sdlc (Phase 2's handler work). Each story is scoped to a single repo.

**Requirement traceability.** Each AC item annotates `[R-XX]`.

### Wave Map

```
Phase 1 — Terminology Lockdown (cc-workflow)
└─ Wave 1 ── 1.1 ─ Rewrite kahuna-devspec.md with Terminology section + rename
            1.2 ─ Write docs/plan-issue-template.md reference doc
            1.3 ─ Update decision_plan_phase_epic_taxonomy.md with §5.1 body/comments split

Phase 2 — Schema & API Renames (mcp-server-sdlc)
├─ Wave 1 ── 2.1 ─ wave_init accepts kahuna: {plan_id, slug}; no legacy shape
│           2.2 ─ wave_finalize accepts plan_id; MR title pattern updated
├─ Wave 2 ── 2.3 ─ Wave-state schema writes plan_id only
│           2.4 ─ Branch naming convention kahuna/<plan_id>-<slug> applied
└─ Wave 3 ── 2.5 ─ Prime(post-wave) reconciliation + [drift-halt] Category B
            2.6 ─ /devspec finalize check for depends_on per-Story

Phase 3 — Skill Body Rewrites + Epic Bolt-On (cc-workflow)
├─ Wave 1 ── 3.1 ─ /wavemachine SKILL.md rename + Exhaustive Legal Exits
│           3.2 ─ /nextwave SKILL.md rename + Exhaustive Legal Exits
├─ Wave 2 ── 3.3 ─ /prepwaves SKILL.md rename
│           3.4 ─ /devspec SKILL.md: teach Plan/Phase/Wave/Story; ledger comments
│           3.5 ─ /issue SKILL.md: type=plan / --epic N support
└─ Wave 3 ── 3.6 ─ Regression: no pipeline code reads epic::N labels
            3.7 ─ Dogfood verification: MV-01..MV-06 + VRTM close
```

### Summary Table

| Wave | Stories | Master Issue | Parallel? |
|------|---------|--------------|-----------|
| P1W1 | 1.1, 1.2, 1.3 | Wave 1 Master (P1) | Yes — three independent docs |
| P2W1 | 2.1, 2.2 | Wave 1 Master (P2) | Yes — two handler files |
| P2W2 | 2.3, 2.4 | Wave 2 Master (P2) | Yes — state schema + branch naming in different modules |
| P2W3 | 2.5, 2.6 | Wave 3 Master (P2) | Yes — drift reconciliation + finalize check are independent |
| P3W1 | 3.1, 3.2 | Wave 1 Master (P3) | Yes — two skill bodies |
| P3W2 | 3.3, 3.4, 3.5 | Wave 2 Master (P3) | Yes — three skill bodies |
| P3W3 | 3.6, 3.7 | Wave 3 Master (P3) | Yes — grep test + dogfood run |

### Foundation Story Checklist (Phase 1 Wave 1)

This Plan modifies an existing mature project; most foundation items are N/A:

- Project scaffold — **N/A** (cc-workflow already scaffolded)
- CI/CD pipeline — **N/A** (unchanged)
- Artifact build & install — **N/A** (no new artifacts beyond docs)
- Unified build system — **N/A** (unchanged)
- Linting and formatting — **N/A** (unchanged)
- Test runner — **N/A** (unchanged)
- Makefile / task runner — **N/A** (unchanged)
- Initial documentation — **Stories 1.1 + 1.2**
- Verify Deliverables Manifest coverage — DM-09 (both paths) covered by 1.1 and 1.2

### Closing Story Checklist (Phase 3 Wave 3)

Story 3.7 executes MV-01 through MV-06 and closes the VRTM. Per template rule, this is a dedicated story, not an afterthought.

### Co-production Rule

Each wave producing an artifact also produces (or schedules) its verification:

- Phase 1 Wave 1 → docs; verification is MV-02 + MV-04 (§6.4, executed in Phase 3 Wave 3)
- Phase 2 → handler changes + schema; verification is IT-KAHUNA-01 + IT-DRIFT-B-01/02 (built in Phase 2 Wave 3 Story 2.5)
- Phase 3 → skill bodies; verification is MV-01/MV-03/MV-06 + pipeline-code grep tests (Phase 3 Wave 3)

---

### Phase 1: Terminology Lockdown (Epic — cc-workflow)

**Goal:** Lock in the Plan / Phase / Wave / Story / Flight / Epic taxonomy at the documentation layer before any code changes. Canonical source for the rename.

#### Phase 1 Definition of Done

- [ ] `docs/kahuna-devspec.md` opens with a Terminology section defining all six primitives [R-04, CP-02]
- [ ] `docs/plan-issue-template.md` exists as a standalone operator reference matching §5.1.2 template [R-15, DM-09]
- [ ] Memory file `decision_plan_phase_epic_taxonomy.md` references the §5.1 body/comments split
- [ ] MV-02 executes and passes
- [ ] No code changes landed (Phase 1 is doc-only)
- [ ] Phase 1 unit tests pass (doc-structure grep tests — see Story 1.1 AC)

---

#### Story 1.1: Rewrite `kahuna-devspec.md` with Terminology section and Plan/Phase rename

**Wave:** P1W1
**Repository:** `Wave-Engineering/claudecode-workflow`
**Dependencies:** None

Rewrite the existing `docs/kahuna-devspec.md` so "epic" is removed from pipeline-operational contexts and a new Terminology section opens the document defining the six primitives.

**Implementation Steps:**

1. Read the current `docs/kahuna-devspec.md` in full.
2. Insert a new `## Terminology` section immediately after the Table of Contents, before §1. Content per §5.1 of this Dev Spec (the Plan/Phase/Wave/Story/Flight/Epic table with relations and non-relations).
3. Scan the rest of `kahuna-devspec.md` for every occurrence of the literal word "epic" (case-insensitive) using `grep -ni '\bepic\b' docs/kahuna-devspec.md`.
4. For each occurrence, replace with "Plan" or "Phase" per semantic context, OR explicitly annotate as "PM-layer `epic::N` label" or "PM-layer `type::epic` parent tracker."
5. Update any `epic_id` references in handler-contract examples to `plan_id`.
6. Re-read the full document to verify narrative consistency — particularly §4.2 which walks the happy path.
7. Commit with message `docs(kahuna-devspec): rename epic→Plan/Phase; add Terminology section`.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_kahuna_devspec_terminology_section` | Asserts `## Terminology` heading appears before `## 1.` | `tests/docs/test_kahuna_devspec_structure.sh` |
| `test_kahuna_devspec_no_unqualified_epic` | Grep for `\bepic\b` in pipeline-operational contexts returns zero hits | `tests/docs/test_kahuna_devspec_structure.sh` |

*Integration/E2E Coverage:* MV-02 (§6.4) executes against this rewrite.

**Acceptance Criteria:**

- [ ] `## Terminology` section present before §1 [R-04]
- [ ] Six primitives (Plan, Phase, Wave, Story, Flight, Epic) defined with relations and non-relations [R-04]
- [ ] Zero unqualified "epic" occurrences in pipeline-operational contexts (CP-01-narrowed to this doc) [CP-01]
- [ ] Every remaining "epic" explicitly annotated as PM-layer [R-03]
- [ ] Document narrative still flows (no broken cross-references)
- [ ] Unit tests pass

---

#### Story 1.2: Write `docs/plan-issue-template.md` reference doc

**Wave:** P1W1
**Repository:** `Wave-Engineering/claudecode-workflow`
**Dependencies:** None

Create a standalone reference doc capturing the Plan issue body template and comment typed-prefix conventions from §5.1 of this Dev Spec. Operators reference this when hand-authoring or inspecting Plan issues.

**Implementation Steps:**

1. Create `docs/plan-issue-template.md`.
2. Include sections: Overview, Body Template (verbatim from §5.1.2), Comment Typed-Prefix Table (from §5.1.3), Mutation Rules (from §5.1.6), Examples (at least one full rendered Plan issue — can reference cc-workflow#499 as the canonical example).
3. Cross-link to `docs/phase-epic-taxonomy-devspec.md` §5.1 as the authoritative source.
4. Commit with message `docs(plan-issue-template): add operator reference for Plan tracking issues`.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_plan_issue_template_exists` | Asserts `docs/plan-issue-template.md` exists and contains all required sections | `tests/docs/test_plan_issue_template.sh` |

*Integration/E2E Coverage:* MV-04 (§6.4) references this doc when verifying `/issue plan` output.

**Acceptance Criteria:**

- [ ] `docs/plan-issue-template.md` exists [DM-09, R-15]
- [ ] Body Template section matches §5.1.2 verbatim (or cites §5.1.2 as source)
- [ ] Comment Typed-Prefix Table lists all 9 prefixes from §5.1.3
- [ ] Mutation Rules section matches §5.1.6
- [ ] At least one full example included
- [ ] Unit tests pass

---

#### Story 1.3: Update `decision_plan_phase_epic_taxonomy.md` memory file

**Wave:** P1W1
**Repository:** `Wave-Engineering/claudecode-workflow` (memory files live under `~/.claude/projects/.../memory/` per the user's auto-memory system; this story is effectively "edit a memory file" — the commit goes into cc-workflow if the memory file is checked in there, otherwise the Pair's human handles the memory-side edit)

**Dependencies:** None

Update the existing memory file to reference the §5.1 body/comments split and the ledger typed-prefix convention — closes the loop between memory and Dev Spec.

**Implementation Steps:**

1. Read the current memory file `decision_plan_phase_epic_taxonomy.md`.
2. Add a new section (or expand the "Implementation scope" section) referencing Dev Spec §5.1 for the Plan issue body/comments design.
3. Add a note that runtime state lives in comments, not in mutable body sections — consistent with D-011 on cc-workflow#499.
4. Update MEMORY.md index entry if the description changes.
5. Commit (if the memory file is under version control in cc-workflow; otherwise the Pair's human edits in place and notes completion).

**Test Procedures:**

*Unit Tests:* None (memory files are not CI-tested).

*Integration/E2E Coverage:* E2E-01 exercises memory-file presence as part of its VRTM check.

**Acceptance Criteria:**

- [ ] Memory file references §5.1 body/comments split
- [ ] Memory file references the typed-prefix comment convention
- [ ] MEMORY.md index description is accurate
- [ ] `/engage` after this story lands correctly summarizes the updated taxonomy

---

### Phase 2: Schema & API Renames (Epic — mcp-server-sdlc)

**Goal:** Rename `epic_id` → `plan_id` in sdlc-server handlers, wave-state schema, and branch-naming convention. Ship the drift-detection Category B reconciliation. Ship the `/devspec finalize` `depends_on` check.

#### Phase 2 Definition of Done

- [ ] `wave_init` handler accepts `kahuna: {plan_id, slug}` only; no legacy `epic_id` shape [R-05]
- [ ] `wave_finalize` handler accepts `plan_id` parameter; MR title pattern is `plan(#<plan_id>): <slug> — kahuna to <target_branch>` [R-06]
- [ ] Wave-state schema writes `plan_id` and `kahuna_branches[].plan_id` only [R-07]
- [ ] Branch naming `kahuna/<plan_id>-<slug>` applied to new runs
- [ ] Prime(post-wave) reconciliation logic lands with `[drift-halt] Category B` emission [R-18]
- [ ] `/devspec finalize` includes a check that every Story in `phases-waves.json` has a `depends_on` field (may be empty)
- [ ] IT-KAHUNA-01 passes [CP-04]
- [ ] IT-DRIFT-B-01 and IT-DRIFT-B-02 pass [R-18]
- [ ] mcp-server-sdlc CHANGELOG.md carries Phase 2 release entry including the `sed` migration snippet per §5.B.3 [DM-07]
- [ ] Phase 2 unit tests pass

---

#### Story 2.1: `wave_init` accepts `kahuna: { plan_id, slug }` (no legacy shape)

**Wave:** P2W1
**Repository:** `Wave-Engineering/mcp-server-sdlc`
**Dependencies:** None

**Implementation Steps:**

1. Modify `handlers/wave_init.ts` input schema: replace `kahuna: { epic_id, slug }` with `kahuna: { plan_id, slug }`. `plan_id` is `z.number().int().positive()`.
2. Update the branch-name computation to `kahuna/${kahuna.plan_id}-${kahuna.slug}`.
3. Update the `writeState` call to emit `plan_id` (and `kahuna_branches[].plan_id`) instead of `epic_id`.
4. Remove any legacy-compat `kahuna.epic_id ?? kahuna.plan_id` fallback code (no such code exists yet if this is the first rename; if it does, delete).
5. Update existing unit tests to use the new shape.
6. Commit with message `feat(wave_init)!: accept kahuna: { plan_id, slug }; remove legacy epic_id`.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `wave_init.plan_id.test.ts` | Calling with `{plan_id, slug}` creates `kahuna/<plan_id>-<slug>` branch | `handlers/wave_init.plan_id.test.ts` |
| `wave_init.rejects_epic_id.test.ts` | Calling with legacy `{epic_id, slug}` shape fails with schema validation error | `handlers/wave_init.rejects_epic_id.test.ts` |

*Integration/E2E Coverage:* IT-KAHUNA-01 + E2E-01.

**Acceptance Criteria:**

- [ ] `handlers/wave_init.ts` input schema has `plan_id` not `epic_id` [R-05]
- [ ] Branch name computed as `kahuna/${plan_id}-${slug}` [R-05]
- [ ] Wave state writes `plan_id` [R-07]
- [ ] Legacy `epic_id` shape rejected with clear schema error
- [ ] Unit tests pass
- [ ] BREAKING-CHANGE noted in commit message and CHANGELOG

---

#### Story 2.2: `wave_finalize` accepts `plan_id`; MR title pattern updated

**Wave:** P2W1
**Repository:** `Wave-Engineering/mcp-server-sdlc`
**Dependencies:** None (parallel with 2.1)

**Implementation Steps:**

1. Modify `handlers/wave_finalize.ts` input schema: replace `epic_id` with `plan_id`.
2. Update MR title assembly: replace `` `epic(#${args.epic_id}): ${slug} — kahuna to ${args.target_branch}` `` with `` `plan(#${args.plan_id}): ${slug} — kahuna to ${args.target_branch}` ``.
3. Update existing unit tests.
4. Commit with message `feat(wave_finalize)!: accept plan_id; title pattern plan(#N) — kahuna to <target>`.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `wave_finalize.plan_id.test.ts` | Title pattern uses `plan(#N): ...` form | `handlers/wave_finalize.plan_id.test.ts` |

*Integration/E2E Coverage:* IT-KAHUNA-01 + E2E-01.

**Acceptance Criteria:**

- [ ] `handlers/wave_finalize.ts` input schema has `plan_id` [R-06]
- [ ] MR title matches pattern `plan(#<plan_id>): <slug> — kahuna to <target_branch>` [R-06]
- [ ] Unit tests pass
- [ ] BREAKING-CHANGE noted in commit + CHANGELOG

---

#### Story 2.3: Wave-state schema writes `plan_id` only

**Wave:** P2W2
**Repository:** `Wave-Engineering/mcp-server-sdlc`
**Dependencies:** Story 2.1 (wave state is first written by `wave_init`)

**Implementation Steps:**

1. Modify `lib/wave_state.ts` schema: rename `epic_id: z.number().optional()` → `plan_id: z.number().optional()`. Update `kahuna_branches[].epic_id` → `kahuna_branches[].plan_id`.
2. Grep for all consumers of `state.epic_id` across `handlers/` and `lib/`. Replace with `state.plan_id`.
3. Update fixtures in `tests/fixtures/` to use `plan_id`.
4. Commit with message `refactor(wave-state)!: rename epic_id→plan_id in schema and all consumers`.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `wave_state.plan_id.test.ts` | Schema validates `{plan_id: 123}`; rejects `{epic_id: 123}` | `lib/wave_state.test.ts` |

*Integration/E2E Coverage:* IT-KAHUNA-01.

**Acceptance Criteria:**

- [ ] Wave-state schema field is `plan_id`; `epic_id` is not accepted [R-07]
- [ ] `kahuna_branches[].plan_id` (not `epic_id`) [R-07]
- [ ] All handler consumers updated
- [ ] Fixtures updated
- [ ] Unit tests pass

---

#### Story 2.4: Branch naming `kahuna/<plan_id>-<slug>` applied (verify end-to-end)

**Wave:** P2W2
**Repository:** `Wave-Engineering/mcp-server-sdlc`
**Dependencies:** Story 2.1, 2.2

**Implementation Steps:**

1. Audit all code paths that construct kahuna branch names across `handlers/` and `lib/`. The pattern `kahuna/${plan_id}-${slug}` should be the only form; any `kahuna/${epic_id}-${slug}` or similar legacy references are flagged and removed.
2. Add a constant or helper in `lib/` if branch-name construction happens in multiple places: `export function kahunaBranchName(plan_id, slug): string`.
3. Update all callers to use the helper.
4. Commit with message `refactor(kahuna-branch): use kahunaBranchName() helper; all call sites use plan_id`.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `kahuna_branch_name.test.ts` | `kahunaBranchName(499, "phase-epic-taxonomy")` returns `"kahuna/499-phase-epic-taxonomy"` | `lib/kahuna_branch_name.test.ts` |

*Integration/E2E Coverage:* IT-KAHUNA-01.

**Acceptance Criteria:**

- [ ] Branch name helper exists OR all construction sites use identical pattern
- [ ] No `epic_id`-based branch construction in the codebase
- [ ] Unit tests pass
- [ ] IT-KAHUNA-01 observes correct branch name in end-to-end run

---

#### Story 2.5: Prime(post-wave) reconciliation + `[drift-halt] Category B`

**Wave:** P2W3
**Repository:** `Wave-Engineering/mcp-server-sdlc`
**Dependencies:** Story 2.3 (uses wave state), Story 2.4 (uses branch naming)

**Implementation Steps:**

1. Create a new handler `handlers/wave_reconcile.ts` (or extend an existing Prime-related handler) that implements §5.4.1's reconciliation logic:
   - Read `phases-waves.json[current_wave].stories` → Expected set
   - Query `pr_list` scoped to the kahuna branch + time window → Actual set
   - Read `wave_defer` records for the wave → Deferred set
   - Compute `Missing`, `Unexpected`, `Dependency violations`
2. If any of those three sets is non-empty, emit a canonical `[drift-halt]` comment on the Plan issue via `pr_comment` (or equivalent). Body matches §5.4.1 worked example.
3. Add the handler as a new skill invocation in `/nextwave`'s post-wave hook.
4. Add integration tests IT-DRIFT-B-01 and IT-DRIFT-B-02.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `wave_reconcile.test.ts` | Fixture with missing story fires `Missing` drift | `handlers/wave_reconcile.test.ts` |

*Integration/E2E Coverage:* IT-DRIFT-B-01, IT-DRIFT-B-02 (built here).

**Acceptance Criteria:**

- [ ] `handlers/wave_reconcile.ts` (or equivalent) exists [R-18]
- [ ] Emits `[drift-halt]` comment with §5.4.1 body shape on Category B violation [R-18]
- [ ] Integration tests IT-DRIFT-B-01 and IT-DRIFT-B-02 implemented and passing
- [ ] Unit tests pass

---

#### Story 2.6: `/devspec finalize` check for `depends_on` field per-Story

**Wave:** P2W3
**Repository:** `Wave-Engineering/mcp-server-sdlc`
**Dependencies:** None (parallel with 2.5)

**Implementation Steps:**

1. Modify `handlers/devspec_finalize.ts` to add a new check: "Every Story in `phases-waves.json` has a `depends_on` field (may be empty array)."
2. The check iterates every Story; if any lack the field, the finalization fails with a specific error message.
3. Update existing finalize unit tests; add a new test for this check.
4. Commit with message `feat(devspec-finalize): require depends_on field on every Story`.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `devspec_finalize.depends_on.test.ts` | Fixture without `depends_on` fails finalization | `handlers/devspec_finalize.depends_on.test.ts` |

*Integration/E2E Coverage:* E2E-01.

**Acceptance Criteria:**

- [ ] Finalize check verifies `depends_on` field presence [R-18, §5.4.3]
- [ ] Missing field produces clear error message
- [ ] Unit tests pass

---

### Phase 3: Skill Body Rewrites + Epic PM-Layer Bolt-On (Epic — cc-workflow)

**Goal:** Rename "epic" throughout autonomy-loop and Plan-producing skill bodies. Add Exhaustive Legal Exits sections to `/wavemachine` and `/nextwave`. Ship `/issue type=plan`. Verify via MV pass and dogfood this Plan's own execution.

#### Phase 3 Definition of Done

- [ ] `/wavemachine` and `/nextwave` skill bodies contain `## Exhaustive Legal Exits` section matching §5.3.2 [R-17]
- [ ] `/prepwaves`, `/devspec`, `/issue` skill bodies contain no unqualified "epic" in pipeline-operational contexts [R-09..R-12]
- [ ] `/issue plan <prompt>` creates a Plan tracking issue with canonical §5.1.2 body [R-13, R-15]
- [ ] `/issue <type> --epic N` applies `epic::N` label to Story issues [R-13]
- [ ] `label_create` invoked on-demand when `type::plan` or `epic::N` label absent on target repo [R-14]
- [ ] No pipeline code path reads `epic::N` labels [R-19]
- [ ] MV-01 through MV-06 executed and passing
- [ ] VRTM (Appendix V) complete with all 19 requirements traced
- [ ] cc-workflow CHANGELOG.md carries Phase 3 release entry [DM-07]

---

#### Story 3.1: `/wavemachine` SKILL.md rename + Exhaustive Legal Exits section

**Wave:** P3W1
**Repository:** `Wave-Engineering/claudecode-workflow`
**Dependencies:** Phase 2 complete (skill references new schema)

**Implementation Steps:**

1. Read `skills/wavemachine/SKILL.md` in full.
2. Grep for `\bepic\b` (case-insensitive); replace each occurrence with "Plan" or "Phase" per semantic, or annotate as PM-layer.
3. Insert a new `## Exhaustive Legal Exits` section per the §5.3.3 worked example verbatim (7 numbered exits + 7 bulleted non-exits + cross-reference to memory files).
4. Review narrative consistency — particularly the loop section and the trust-score gate section.
5. Commit with message `refactor(wavemachine): rename epic→Plan/Phase; add Exhaustive Legal Exits`.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_wavemachine_no_unqualified_epic.sh` | Grep `\bepic\b` in pipeline contexts returns zero | `tests/skills/test_wavemachine_structure.sh` |
| `test_wavemachine_exhaustive_legal_exits.sh` | `## Exhaustive Legal Exits` section present with required sub-sections | `tests/skills/test_wavemachine_structure.sh` |

*Integration/E2E Coverage:* MV-01, MV-03, MV-06, E2E-01.

**Acceptance Criteria:**

- [ ] Zero unqualified "epic" in `/wavemachine/SKILL.md` pipeline contexts [R-09]
- [ ] `## Exhaustive Legal Exits` section present matching §5.3.2 [R-17]
- [ ] Cross-reference to `principle_user_attention_is_the_cost.md` + `principle_cost_asymmetry_continue_vs_exit.md` present
- [ ] Unit tests pass

---

#### Story 3.2: `/nextwave` SKILL.md rename + Exhaustive Legal Exits section

**Wave:** P3W1
**Repository:** `Wave-Engineering/claudecode-workflow`
**Dependencies:** Phase 2 complete (parallel with 3.1)

Same pattern as 3.1, applied to `skills/nextwave/SKILL.md`.

**Implementation Steps:**

1-5: Same as Story 3.1 substituting `/nextwave`.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_nextwave_no_unqualified_epic.sh` | Same check, nextwave | `tests/skills/test_nextwave_structure.sh` |
| `test_nextwave_exhaustive_legal_exits.sh` | Same check, nextwave | `tests/skills/test_nextwave_structure.sh` |

*Integration/E2E Coverage:* MV-01, MV-03, MV-06, E2E-01.

**Acceptance Criteria:** Mirror Story 3.1, applied to `/nextwave`. [R-10, R-17]

---

#### Story 3.3: `/prepwaves` SKILL.md rename

**Wave:** P3W2
**Repository:** `Wave-Engineering/claudecode-workflow`
**Dependencies:** Stories 3.1, 3.2 (autonomy-loop skills ship first)

**Implementation Steps:**

1. Read `skills/prepwaves/SKILL.md` in full.
2. Grep for `\bepic\b`; replace per semantic or annotate as PM-layer.
3. `/prepwaves` does NOT need an Exhaustive Legal Exits section (it's not an autonomy-loop skill).
4. Commit with message `refactor(prepwaves): rename epic→Plan/Phase`.

**Test Procedures:** Unit test grepping for unqualified "epic." Integration: MV-01, E2E-01.

**Acceptance Criteria:** Zero unqualified "epic" [R-11]; unit tests pass.

---

#### Story 3.4: `/devspec` SKILL.md: teach Plan/Phase/Wave/Story + ledger comments

**Wave:** P3W2
**Repository:** `Wave-Engineering/claudecode-workflow`
**Dependencies:** Stories 3.1, 3.2 (parallel with 3.3, 3.5)

**Implementation Steps:**

1. Read `skills/devspec/SKILL.md` in full.
2. Grep for `\bepic\b`; replace or annotate per semantic.
3. Update `/devspec create` section to explicitly teach Plan / Phase / Wave / Story as the pipeline primitives; Epic as optional PM-layer.
4. Add a new procedure: during `/devspec create`, after each section the Pair approves, append a `[ledger D-NNN]` comment to the Plan tracking issue via `pr_comment` (or equivalent). Include source (`/devspec §X.Y`), Decision line, Rationale line, Signature.
5. Update `/devspec upshift` section to write `phases-waves.json` with `plan_id` (not `epic_id`) and `depends_on` on every Story.
6. Commit with message `refactor(devspec): teach Plan/Phase/Wave/Story; append ledger entries during walk`.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_devspec_no_unqualified_epic.sh` | Grep check | `tests/skills/test_devspec_structure.sh` |
| `test_devspec_ledger_procedure.sh` | Asserts "append ledger comment" step is present in skill body | `tests/skills/test_devspec_structure.sh` |

*Integration/E2E Coverage:* E2E-01.

**Acceptance Criteria:**

- [ ] Zero unqualified "epic" [R-12]
- [ ] `/devspec create` teaches Plan/Phase/Wave/Story vocabulary
- [ ] Ledger-comment append procedure documented [R-16, §5.2.2]
- [ ] `/devspec upshift` writes `phases-waves.json` with new shape
- [ ] Unit tests pass

---

#### Story 3.5: `/issue` SKILL.md: `type=plan` / `type=epic` / `--epic N`

**Wave:** P3W2
**Repository:** `Wave-Engineering/claudecode-workflow`
**Dependencies:** Stories 3.1, 3.2 (parallel with 3.3, 3.4)

**Implementation Steps:**

1. Read `skills/issue/SKILL.md` in full.
2. Add `plan` to the type table (§5.5.3 mechanics from this Dev Spec).
3. `type::epic` creation path is unchanged but the skill body calls it out explicitly as PM-layer per §5.5.5.
4. Add `--epic N` flag support for Story creation (§5.5.4 mechanics).
5. Add on-demand `label_create` logic for `type::plan` and `epic::N` label families per §5.5.3 step 2 and §5.5.4 step 3.
6. Implement Plan body template rendering per §5.1.2 — the skill body describes the template; actual rendering logic may be inline or reference `docs/plan-issue-template.md`.
7. Commit with message `feat(issue): add type=plan + --epic N; on-demand label creation`.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_issue_plan_body_template.sh` | `/issue plan` output matches §5.1.2 template | `tests/skills/test_issue_plan.sh` |
| `test_issue_epic_flag.sh` | `/issue feature --epic 42` applies both labels | `tests/skills/test_issue_epic_flag.sh` |
| `test_issue_label_create_ondemand.sh` | Missing `type::plan` triggers `label_create` call | `tests/skills/test_issue_label_create.sh` |

*Integration/E2E Coverage:* IT-ISSUE-PLAN-01, MV-04, E2E-01.

**Acceptance Criteria:**

- [ ] `/issue plan <prompt>` creates Plan issue with §5.1.2 template [R-13, R-15]
- [ ] `/issue <type> --epic N` applies `epic::N` label with pre-check on Epic existence [R-13]
- [ ] `label_create` invoked on-demand for missing `type::plan` or `epic::N` [R-14]
- [ ] Unit tests pass

---

#### Story 3.6: Pipeline-code regression — no reads of `epic::N` labels

**Wave:** P3W3
**Repository:** `Wave-Engineering/claudecode-workflow` AND `Wave-Engineering/mcp-server-sdlc`
**Dependencies:** All Phase 3 Wave 1 and Wave 2 stories

**Implementation Steps:**

1. Write a grep-based regression test scanning all pipeline code paths in both repos for any read of `epic::N` labels (regex patterns: `epic::\d+`, `"epic::"`, label-fetch with "epic" filter).
2. Test should be CI-runnable; fails if any pipeline code reads `epic::N`.
3. Exception list allowed for legitimate PM-layer-label creation (e.g. `/issue --epic N` creation path, which applies but doesn't read).
4. Commit with message `test(regression): no pipeline code reads epic::N labels`.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_no_epic_label_reads.sh` | Grep finds zero pipeline reads of `epic::N` | `tests/regression/test_no_epic_label_reads.sh` |

*Integration/E2E Coverage:* None direct; MV-05 verifies in runtime.

**Acceptance Criteria:**

- [ ] Regression test exists and passes [R-19]
- [ ] Wired into CI for both repos

---

#### Story 3.7: Dogfood verification — execute MV-01..MV-06 + close VRTM

**Wave:** P3W3
**Repository:** `Wave-Engineering/claudecode-workflow` (closing story — results documented in the Plan issue)
**Dependencies:** All prior Phase 3 stories

This is the **closing story** per §8's template requirement. Executes all Manual Verification procedures from §6.4 against the landed Plan and completes the VRTM.

**Implementation Steps:**

1. Execute MV-01 through MV-06 per their procedures in §6.4. Record pass/fail with evidence in `docs/phase-epic-taxonomy-mv-results.md` (or inline in the Plan tracking issue as `[status mv=<id>,result=<pass|fail>]` comments).
2. For any MV failure, file a bug issue and add a `Supersedes`/"depends-on-fix" note in the Plan issue's ledger.
3. Complete VRTM in Dev Spec Appendix V: every requirement row gets a Status (Pass/Fail/Pending) with cite of the verification item.
4. Verify Deliverables Manifest rows with "Produced In" Phase 3 are all delivered (DM-04, DM-07 cc-workflow entry, DM-08, DM-10).
5. Commit with message `docs(vrtm): close VRTM for cc-workflow#499 — Phase 3 dogfood verified`.

**Test Procedures:** Operator-executed; no automation beyond MV procedure scripts.

**Acceptance Criteria:**

- [ ] MV-01 through MV-06 executed with results recorded [§6.4]
- [ ] Any failures filed as bugs + linked from Plan ledger
- [ ] VRTM (Appendix V) complete — all 19 requirements traced and statused
- [ ] Deliverables Manifest Phase 3 rows verified delivered
- [ ] Plan tracking issue Status field updated to `plan-complete` via `[status plan_state=complete]` comment

---

## 9. Appendices

### Appendix A: Glossary

Quick-reference glossary for the six primitives. Duplicates the Terminology section that will land in `kahuna-devspec.md` via Story 1.1, but included here as a standalone reference for cold readers of this Dev Spec.

- **Plan** — synthetic pipeline primitive. A tracking issue with `type::plan` label, acting as the top-level container for a multi-Phase delivery. `plan_id` is the issue number. Body holds frozen content (Goal, Scope, DoD, Phase names + Phase DoDs, References); comments hold the runtime log (Decision Ledger, Status, lifecycle events).
- **Phase** — pipeline-internal sequential ordering unit within a Plan. Lives in `phases-waves.json`; no platform representation (no issue, no label). Phases accumulate onto a single kahuna branch per Plan.
- **Wave** — pipeline-internal parallelism unit within a Phase. Lives in `phases-waves.json`. Stories within a wave may execute in parallel subject to flight-partitioning constraints.
- **Story** — native platform issue (GitHub / GitLab), typically carrying `type::feature`, `type::bug`, `type::chore`, or `type::docs`. May optionally carry an `epic::N` PM-layer label. Each Story is implemented in one PR/MR scoped to one repo.
- **Flight** — ephemeral runtime concept. A sub-agent spawned by `/nextwave` to implement a single Story in its own worktree. Flights do not persist as platform artifacts; their outputs are the Story's commit and resulting PR.
- **Epic** — **PM-layer concept, not a pipeline primitive.** Either (a) a platform issue with `type::epic` label (a parent thematic tracker for related Stories) or (b) an `epic::N` label applied to a Story (story→epic assignment). The pipeline does not read, filter, or branch on Epic in either form. Epic is orthogonal to Phase.

### Appendix V: Verification Requirements Traceability Matrix (VRTM)

**Populated after implementation.** During Phase 3 Wave 3 Story 3.7, each requirement row gets a Status (Pass/Fail/Pending) based on the verification item's actual outcome.

R-08 was killed in the goldplating audit (D-016 supersedes D-003/D-015); the VRTM skips R-08 intentionally.

| Req ID | Requirement (short) | Source | Verification Item | Verification Method | Status |
|--------|---------------------|--------|-------------------|---------------------|--------|
| R-01 | Pipeline uses "Plan" for top-level container | §3.1 | Story 1.1 AC + MV-01 + E2E-01 | grep + manual + e2e | Pending |
| R-02 | Pipeline uses "Phase" for sequential ordering unit | §3.1 | Story 1.1 AC + MV-01 + E2E-01 | grep + manual + e2e | Pending |
| R-03 | Pipeline treats "Epic" as PM-layer, never reads | §3.1 | MV-05 + Story 3.6 | manual + regression test | Pending |
| R-04 | Dev Spec opens with Terminology section | §3.1 | Story 1.1 AC + MV-02 | structural test + manual | Pending |
| R-05 | `wave_init` accepts `{plan_id, slug}` only | §3.2 | Story 2.1 AC + IT-KAHUNA-01 | unit test + integration | Pending |
| R-06 | `wave_finalize` accepts `plan_id` | §3.2 | Story 2.2 AC + IT-KAHUNA-01 | unit test + integration | Pending |
| R-07 | Wave-state writes `plan_id` only | §3.2 | Story 2.3 AC + IT-KAHUNA-01 | unit test + integration | Pending |
| R-09 | `/wavemachine` skill body: no unqualified epic | §3.3 | Story 3.1 AC + MV-01 | grep + manual | Pending |
| R-10 | `/nextwave` skill body: no unqualified epic | §3.3 | Story 3.2 AC + MV-01 | grep + manual | Pending |
| R-11 | `/prepwaves` skill body: no unqualified epic | §3.3 | Story 3.3 AC + MV-01 | grep + manual | Pending |
| R-12 | `/devspec` skill body: teach Plan/Phase/Wave/Story | §3.3 | Story 3.4 AC + E2E-01 | grep + e2e | Pending |
| R-13 | `/issue` supports plan/epic/story with templates | §3.3 | Story 3.5 AC + IT-ISSUE-PLAN-01 + MV-04 | unit test + integration + manual | Pending |
| R-14 | On-demand `type::plan` label creation | §3.4 | Story 3.5 AC + IT-ISSUE-PLAN-01 | unit test + integration | Pending |
| R-15 | `/issue type=plan` body matches canonical template | §3.4 | Story 3.5 AC + MV-04 + E2E-01 | unit test + manual + e2e | Pending |
| R-16 | Decision Ledger in Plan issue; append-only | §3.5 | Story 3.4 AC + E2E-01 + MV-04 | grep + e2e + manual | Pending |
| R-17 | Autonomy-loop skills have Exhaustive Legal Exits | §3.5 | Stories 3.1 + 3.2 AC + MV-03 + MV-06 | grep + manual | Pending |
| R-18 | Plan-reality drift Category B detection | §3.5 | Story 2.5 AC + IT-DRIFT-B-01 + IT-DRIFT-B-02 | unit test + integration | Pending |
| R-19 | Pipeline does not read `epic::N` labels | §3.6 | Story 3.6 AC + MV-05 | regression test + manual | Pending |

**18 requirements active (R-08 killed); every active requirement has a verification path.**

### Appendix B: Decision Ledger Reference

This Plan dogfooded the Decision Ledger pattern from §5.1/§5.2. The live Ledger lives in the comment stream of cc-workflow#499; operators reading this Dev Spec cold can inspect the real Ledger flow directly on the Plan tracking issue. At Dev Spec approval time, entries D-001 through D-019 had been posted.

Key superseding chains:

- **D-006 → D-011:** initial body-sections approach for mutable content superseded by body/comments split (BJ's "if it changes during a wave, it goes in comments" rule).
- **D-003, D-015 → D-016:** initial backward-compat shim superseded by coordinated-deploy + `sed` fallback (goldplating audit).
- **D-017, D-018, D-019:** follow-on rip-outs from the audit — §4.4 killed, CT-03 clarified structural-not-temporal, CP-04 reframed from bit-identical to functionally-equivalent.

The Ledger is the primary audit trail for this Plan. Appendix V's requirement statuses will reference it where decisions affected verification outcomes.
