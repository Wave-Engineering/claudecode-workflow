<!-- DEV-SPEC-APPROVAL
approved: true
approved_by: BJ
approved_at: 2026-07-04T13:22:51Z
finalization_score: 8/8
-->

# Executor Model — Development Specification

**Plan:** [#822](https://github.com/Wave-Engineering/claudecode-workflow/issues/822)
**Dev Spec ID:** executor-model
**Status:** Draft

---

## 1. Problem Domain

### 1.1 Background

The cc-workflow wave-pattern pipeline executes story backlogs via two execution paths: a parallel pool (fanout via Flight Agents) and a conceptual "lazy river" (serial high-agency execution). These have been framed as two campaign-level modes — a choice made once for the whole campaign. The lazy-river spike (July 2026, `~/Documents/lazy-river-spike.md`) dogfooded both approaches on the 28-story agent-smith backlog, generating findings F-1–F-12, measuring pool vs serial wall-clock (pool ≈ 1.18×), and — via a post-hoc reframe — exposing that the campaign-mode framing is wrong in two independent ways.

### 1.2 Problem Statement

Two distinct conceptual errors in the current kit:

1. **Per-wave vs campaign-level dispatch.** Fan-out only ever happens *inside* a wave — the phase→wave spine is already serial. Treating "pool vs serial" as a campaign-level choice forces an all-or-nothing decision that misses the ~15% of wall-clock that is genuinely fannable (concentrated in a handful of waves) while risking the F-8 class bug (intra-wave dependency violations) wherever the wrong mode is chosen. The per-wave choice is almost always crisp and is computable at prep time.

2. **Goal-seeking is a different activity from plan-execution.** The current "lazy river" has been framed as the serial setting of plan-execution. This is wrong: plan-execution runs a known DAG to *completeness*; goal-seeking runs a probe–judge–steer loop to *sufficiency* (a judgment). They differ in termination condition, parallelizability (epistemic dependency vs artifact dependency), agency profile, and issue semantics. The escalation cord — which never fired across 28 plan-execution legs — belongs to the goal-seek loop, where sufficiency-judgment escalation is the *core termination mechanism*.

### 1.3 Proposed Solution

Three coordinated changes:

1. **Per-wave dispatch knob:** `/prepwaves` annotates each wave with a `fan`/`serialize` hint after topology computation. `/nextwave` reads the hint and dispatches accordingly. Asymmetric bias: serialize by default; fan only when verified-independent and mechanical.

2. **`/lazyriver` goal-seek skill:** A new skill implementing the probe→judge→steer→journal loop. Sufficiency-gated; escalation-corded. Sits *upstream* of `/devspec` — the goal-seek output (a plan or answer) is the input that `/devspec` structures for execution.

3. **`/multithread` companion technique:** A new skill converting the serial walk of N independent design items into a concurrent discussion. Minimizes human round-trips. The wave-pool topology applied to human↔agent dialogue.

### 1.4 Target Users

| Persona | Description | Primary Use Case |
|---|---|---|
| **Wave Orchestrator / Flight Agent** | Autonomous agent executing a wave campaign | Reads per-wave dispatch hints; fans or serializes each wave without manual intervention |
| **Dev Pair (BJ + agent)** | Human + agent doing design or exploration work | Uses `/lazyriver` to goal-seek toward a plan before invoking `/devspec` |
| **Dev Spec writer** | Any pair walking a Dev Spec | Uses `/multithread` to front-load design resolution on complex stories during the §5.N walk |

### 1.5 Non-Goals

- **Not a wave infrastructure rewrite.** Worktrees, kahuna branches, and the campaign runtime are unchanged. The dispatch knob is a parameter on the existing executor, not new infrastructure.
- **Not a `/devspec` or `/ddd` change.** Those skills are unchanged. `/lazyriver` is *upstream* of them and does not modify them.
- **Not fixing mcp-server-sdlc tooling bugs.** F-2, F-6, and F-7 are filed against mcp-server-sdlc scope and are tracked separately.
- **Not a new campaign-mode "pool vs serial" choice UI.** That framing is retired. Per-wave dispatch replaces it.

---

## 2. Constraints

### 2.1 Technical Constraints

| ID | Constraint | Rationale |
|---|---|---|
| CT-01 | The `dispatch` field in `phases-waves.json` wave entries must be optional; a wave entry without it is treated as `serialize` by `/nextwave` | Legacy plans written before this Plan are not broken |
| CT-02 | All deliverables are SKILL.md files and documentation — no new executable infrastructure required | Skills are declarative; existing MCP servers and shell tooling remain unchanged |
| CT-03 | The `/nextwave` dispatch path must not alter the wave-level DoD gate or per-flight CI gate | Parallelism of implementation must not reduce verification rigor |
| CT-04 | The `/lazyriver` escalation cord must terminate without losing accumulated findings | The session journal is the durability mechanism; a cord-fire is not a data-loss event |

### 2.2 Product Constraints

| ID | Constraint | Rationale |
|---|---|---|
| CP-01 | The dispatch model must be consistent with WAVE_AXIOMS.md — Axiom 1 (serial is valid) and Axiom 10 (one repo per wave; per-wave invariant, orthogonal to dispatch hint) | WAVE_AXIOMS are binding |
| CP-02 | `/lazyriver` must be clearly documented as *distinct* from `/wavemachine` and `/nextwave` — these are not variants of the same activity | Conflating them again is the defect this Plan fixes; clarity prevents recurrence |

---

## 3. Requirements

### 3.1 Per-wave dispatch

| ID | Type | Requirement |
|---|---|---|
| R-01 | Ubiquitous | `/prepwaves` shall compute a `dispatch` annotation (`fan` \| `serialize` \| `serialize-preferred`) for each wave after topology computation. |
| R-02 | Ubiquitous | Width-1 waves shall always receive `dispatch: serialize`. |
| R-03 | If [a wave contains an intra-wave dependency edge], then `/prepwaves` shall classify that wave `serialize` as a hard gate regardless of width. |
| R-04 | Where [a wave's flights are verified-independent and the stories are mechanical with no significant cross-flight learning potential], `/prepwaves` shall classify `dispatch: fan`. |
| R-05 | Where [a wave's flights are independent but involve cross-flight learning potential], `/prepwaves` shall surface `dispatch: serialize-preferred` rather than auto-assigning `fan`. |
| R-06 | When [`dispatch: fan`], `/nextwave` shall execute flights in parallel. When [`serialize`, `serialize-preferred`, or absent], `/nextwave` shall execute them single-file. |
| R-07 | Ubiquitous | The asymmetric bias shall be documented in both skills: a wrong `serialize` costs wall-clock; a wrong `fan` can invalidate a wave. Default is `serialize` unless the evidence is positive for `fan`. |

### 3.2 Goal-seek `/lazyriver`

| ID | Type | Requirement |
|---|---|---|
| R-08 | When [invoked with a goal statement], `/lazyriver` shall run a probe→judge-sufficiency→steer→journal loop. |
| R-09 | While [the loop is running], `/lazyriver` shall re-evaluate sufficiency after each leg: "are we there yet, and if not, what is the next probe?" |
| R-10 | If [diminishing returns are detected or the budget is exhausted], `/lazyriver` shall escalate to the user for a sufficiency judgment rather than continuing to loop. |
| R-11 | Ubiquitous | `/lazyriver` shall maintain a per-session findings journal (accumulates across legs) enabling memory and durability. |
| R-12 | When [the loop terminates on sufficiency], `/lazyriver` shall emit a plan (handable to `/devspec`) or a direct answer. |
| R-13 | Ubiquitous | `/lazyriver` shall document the distinction between epistemic dependency (leg N+1 is unknown until leg N's findings land — intrinsically serial) and artifact dependency (DAG edges — fannable where independent). |
| R-14 | Ubiquitous | The escalation cord shall be documented as a `/lazyriver` primitive, not a `/wavemachine` primitive. Its role is safe loop termination in goal-seek, not error recovery in plan-execution. |

### 3.3 `/multithread` companion

| ID | Type | Requirement |
|---|---|---|
| R-15 | When [invoked with a source of N independent items], `/multithread` shall enumerate and label items (T1..TN), run an independence pass, and present all threads at once with a proposed take per thread. |
| R-16 | Ubiquitous | Each thread presentation shall include a proposed take — not a blank question. Reacting to a take is faster than authoring from scratch. |
| R-17 | While [threads remain open], `/multithread` shall accept batch answers covering any subset, mark resolved threads closed, and re-present only the open ones. |
| R-18 | When [all threads are closed], `/multithread` shall emit a decision record formatted for its destination (Dev Spec ledger, PR review responses, or plain list). |
| R-19 | Ubiquitous | Thread labels shall be stable across rounds; resolved threads shall never be renumbered. |

---

## 4. Concept of Operations

### 4.1 System Context

```
 GOAL ──▶  [ /lazyriver ]  ──▶  PLAN  ──▶  [ /devspec + /prepwaves ]  ──▶  [ /wavemachine ]  ──▶  ARTIFACT
           goal-seek loop              plan-structure + dispatch           per-wave executor
           sufficiency-gated           topology + fan/serialize hints      reads dispatch hints
           escalation-corded           computed once at prep               fans or serializes per wave
```

`/multithread` is a facilitation layer usable at any stage: during `/lazyriver` sub-questions, during `/devspec §5.N`, during PR review.

### 4.2 Per-wave dispatch flow

```
/prepwaves:
  wave_compute (topo sort) → wave_topology (parallel/serial/mixed)
  → per-wave dispatch classification:
      width-1                            → serialize
      intra-dep edge present (F-8 class) → serialize [hard gate]
      width-N, independent, mechanical   → fan
      width-N, independent, learning     → serialize-preferred [surface, don't decide]
  → embed dispatch hint in plan JSON
  → wave_init → phases-waves.json

/nextwave (per wave):
  read dispatch from phases-waves.json
  fan  → spawn parallel Flight Agents per flight
  else → execute flights single-file
```

### 4.3 Goal-seek flow

```
User: /lazyriver "understand X" | "is H true?" | "get to a design we trust"

  Loop:
    Probe:   run the current leg (research / experiment / implement / analyze)
    Journal: append findings to per-session journal
    Judge:   "are we there yet?" (sufficiency gate)
             YES → emit plan or answer → terminate
             NO  → diminishing returns? → ESCALATE to user (sufficiency judgment)
             NO  → steer: formulate next probe from this leg's findings → repeat
```

### 4.4 Multithread dialogue flow

```
Agent: enumerate {T1..TN}, independence pass, present all with takes
User:  batch-answer any subset
Agent: "resolved: T1, T3 · still open: T2, T4" — re-present open (takes updated)
User:  batch-answer remainder
Agent: emit decision record (one entry per thread → resolution)
```

---

## 5. Detailed Design

### 5.1 Per-wave dispatch annotation model

The `dispatch` field is added as an optional key to each wave entry in `phases-waves.json`:

```json
{ "name": "P1W2", "dispatch": "fan", "stories": [...] }
```

Classification rules (applied in `/prepwaves` after `wave_topology`, before Step 6 approval gate):

| Wave profile | `dispatch` value |
|---|---|
| Width = 1 | `serialize` |
| Width > 1, any intra-wave dep edge present | `serialize` (hard gate, F-8 class) |
| Width > 1, all flights independent, mechanical | `fan` |
| Width > 1, all flights independent, learning potential | `serialize-preferred` |

**Backward compatibility:** `/nextwave` treats absent `dispatch` as `serialize`.

**Asymmetric bias:** both skills document that wrong `serialize` = wall-clock cost; wrong `fan` = wave kill. The default is `serialize` unless the evidence is positive for `fan`. A human or Orchestrator may override `serialize-preferred` to `fan` with explicit justification.

### 5.2 `/lazyriver` skill structure

```
Invocation: /lazyriver <goal statement>
Optional:   --resume <journal-path>  (continue prior session)

Core loop:
  1. Probe — run the current leg (research, experiment, analysis)
  2. Journal — append findings to per-session markdown journal
  3. Judge — sufficiency gate: "are we there?"
     YES           → emit output → terminate
     DR / budget   → ESCALATE to user for sufficiency judgment
     NO            → steer: "what is the next probe given what we just learned?" → goto 1

Output: structured plan (→ /devspec) | direct answer (→ user)

Non-negotiable safety features:
  - Sufficiency gate: re-evaluated every leg
  - Escalation cord: fires on diminishing returns (2 consecutive legs with zero new findings)
                     or leg-count cap (default: 10)
  - Journal: durable record; cord-fire does not lose accumulated findings
```

### 5.3 `/multithread` skill structure

Directly implemented from `~/Documents/propose-skill-multithread.md` (the proposal is already a near-complete spec). Key structural choices:

- **Step 0:** enumerate + label (T1..TN), split multi-question items, merge duplicates
- **Step 1:** independence pass — annotate couplings (`depends: T1`); flag tight coupling as "handle as pair, don't multithread"
- **Step 2:** present all threads with takes in a compact table (label · item · take · dep note)
- **Step 3:** human batch-answers any subset; silence = still open
- **Step 4:** converge checkpoint — "resolved: … · still open: …"
- **Step 5:** re-present open only (takes updated by resolved context); loop until dry
- **Step 6:** emit decision record (one entry per thread → resolution)

### 5.4 Relationship model

```
/lazyriver  ──upstream──▶  /devspec  ──▶  /prepwaves  ──▶  /wavemachine
(goal-seek)                (plan structure) (topology+dispatch) (execution)

/multithread  ─── facilitation layer; usable at any stage above
```

### 5.A Deliverables Manifest

| ID | Deliverable | Category | Tier | File Path | Produced In | Status | Notes |
|---|---|---|---|---|---|---|---|
| DM-01 | README.md update | Docs | 1 | `README.md` | P1W3 | required | Add /lazyriver + /multithread to skills table; document dispatch model |
| DM-02 | Build system | Code | 1 | `Makefile` | N/A — existing | N/A | No changes needed |
| DM-03 | CI/CD pipeline | Code | 1 | `.github/workflows/validate.yml` | N/A — existing | N/A | Existing CI unchanged; no workflow changes needed |
| DM-04 | Test suite | Test | 1 | `tests/test_prepwaves_dispatch.py` | P1W3 | required | Dispatch annotation regression tests |
| DM-05 | Test results (JUnit XML) | Test | 1 | `reports/junit.xml` | P1W3 | required | CI artifact |
| DM-06 | Coverage report | Test | 1 | `reports/coverage.xml` | P1W3 | required | CI artifact |
| DM-07 | CHANGELOG | Docs | 1 | `CHANGELOG.md` | P3W2 | required | Single entry covering all three phases |
| DM-08 | VRTM | Trace | 1 | `docs/executor-model-devspec.md` §9 Appendix V | P3W2 | required | Filled post-implementation |
| DM-09 | Dev Spec (reference doc) | Docs | 1 | `docs/executor-model-devspec.md` | P1W1 | required | This document is the primary audience-facing reference |
| DM-10 | `/lazyriver` skill | Code | 1 | `skills/lazyriver/SKILL.md` | P2W1 | required | New skill + installed copy to `~/.claude/skills/lazyriver/SKILL.md` |
| DM-11 | `/multithread` skill | Code | 1 | `skills/multithread/SKILL.md` | P3W1 | required | New skill + installed copy to `~/.claude/skills/multithread/SKILL.md` |
| DM-12 | Updated `/prepwaves` skill | Code | 1 | `skills/prepwaves/SKILL.md` | P1W1 | required | Add dispatch annotation section (Step 4.A); mirror installed copy |
| DM-13 | Updated `/nextwave` skill | Code | 1 | `skills/nextwave/SKILL.md` | P1W2 | required | Add dispatch hint reader; mirror installed copy |
| DM-14 | Manual test procedures results | Test | 2 | `docs/executor-model-mv-results.md` | P3W2 | required | MV-01/02/03 pass evidence (Tier 2 — triggered by MV items in §6.4) |

*Tier 2 triggers: >2 interacting components → DM-09 (this Dev Spec) serves as the architecture document. MV-01/MV-02/MV-03 → covered in Story 3.2 closing story.*

### 5.B Installation & Deployment

New and updated skills are installed via `./install.sh` (repo root). The pattern:

```bash
# After editing skills/lazyriver/SKILL.md:
cp skills/lazyriver/SKILL.md ~/.claude/skills/lazyriver/SKILL.md
# Or full reinstall:
./install.sh
```

CI: existing `./scripts/ci/validate.sh` covers all tests. No pipeline changes required.

### 5.N Open Questions

1. **Dispatch field persistence vs ephemeral:** Should `dispatch` be persisted in `phases-waves.json` or computed at `/prepwaves` presentation time only? **Decision:** persist in `phases-waves.json` — `/nextwave` reads it durably without recomputing; marked advisory so the Orchestrator can override with a logged justification.

2. **`serialize-preferred` as JSON value vs conversational note:** **Decision:** both — JSON value `"serialize-preferred"` so it is grep-able, plus a parenthetical note in the wave plan output.

3. **`/lazyriver` journal format:** Markdown notebook vs JSONL. **Decision:** markdown — BJ can inspect mid-session; matches the spike notebook format that worked.

4. **Escalation cord trigger:** Token count, leg count, or diminishing-returns signal? **Decision:** leg-count cap (default 10) plus a diminishing-returns signal (2 consecutive legs with zero new findings); first trigger wins.

---

## 6. Test Plan

### 6.1 Test Strategy

Skills are behavioral documents — testing is integration-level (invoke the skill, verify output shape) and manual verification (run the full flow on real material). The one testable code-adjacent behavior is the `dispatch` annotation in `phases-waves.json` output from `/prepwaves`, verifiable via the persisted JSON or the skill's wave plan presentation. For Phases 2 and 3, testing is behavioral (does the skill follow its procedure) and E2E (does the chain work).

### 6.2 Integration Tests

| ID | Boundary | Description | Req IDs |
|---|---|---|---|
| IT-01 | `/prepwaves` → `phases-waves.json` | Width-1 → `serialize`; width-N clean-independent → `fan`; intra-dep wave → `serialize` regardless of width; absent field in legacy plan → treated as `serialize` by nextwave | R-01, R-02, R-03, R-04 |
| IT-02 | `/nextwave` → flight dispatch | `fan` annotation → parallel flight spawn; `serialize`/`serialize-preferred`/absent → single-file execution | R-06, R-07 |
| IT-03 | `/lazyriver` → loop termination | Invoke with a goal; verify terminates on sufficiency judgment; emits structured plan or answer | R-08, R-09, R-12 |
| IT-04 | `/multithread` → convergence | Invoke on 5 independent items; verify all close in ≤ log₂(5)+1 rounds; decision record emitted | R-15, R-17, R-18 |

### 6.3 End-to-End Tests

| ID | Flow | Description | Req IDs |
|---|---|---|---|
| E2E-01 | Goal → Artifact chain | `/lazyriver` goal → plan → `/devspec create` → `/prepwaves` → verify dispatch hints on each wave → `/nextwave` on a `fan`-annotated wave → parallel dispatch observed | R-08, R-12, R-01, R-06 |
| E2E-02 | Multithread on §5.N | Invoke `/multithread` on a real Dev Spec §5.N open questions block; verify ≤ 3 rounds to dry; decision record in `[ledger D-NNN]` format | R-15, R-17, R-18, R-19 |

### 6.4 Manual Verification Procedures

| ID | Procedure | Pass Criteria | Req IDs |
|---|---|---|---|
| MV-01 | Invoke `/lazyriver` on a real goal; run until the escalation cord fires (force it by exceeding leg cap or producing two zero-finding legs) | Cord fires before budget exhaustion; accumulated journal intact and usable for resumption; no findings are lost | R-10, R-11, R-14 |
| MV-02 | Invoke `/multithread` on 5–10 independent design questions (e.g., the §5.N from this Dev Spec) | All threads close in ≤ 4 rounds; no thread renumbered; decision record emitted and passable to a Dev Spec ledger | R-16, R-17, R-18, R-19 |
| MV-03 | Run `/prepwaves` on a backlog with mixed-width waves: at least one width-1, one width-N clean-independent, one width-N with intra-dep | Each wave receives the correct `dispatch` annotation; asymmetric-bias note present in output; `fan` only appears where appropriate | R-01–R-07 |

---

## 7. Definition of Done

- [x] All Phase DoD checklists satisfied (Phase 1: dispatch knob; Phase 2: /lazyriver; Phase 3: /multithread)
- [x] IT-01, IT-02, IT-03, IT-04 pass [R-01–R-07, R-08, R-09, R-12, R-15, R-17, R-18]
- [x] E2E-01, E2E-02 pass [R-08, R-12, R-01, R-06, R-15, R-17, R-18, R-19]
- [x] MV-01, MV-02, MV-03 executed and pass evidence recorded [R-10, R-11, R-14, R-16, R-17, R-18, R-19]
- [x] All Deliverables Manifest rows (DM-01 through DM-13) produced and verified
- [x] VRTM complete (Appendix V): all R-01–R-19 traced to a verification item [DM-08]
- [x] CHANGELOG updated [DM-07]
- [x] `docs/executor-model-devspec.md` linked from each updated skill (prepwaves, nextwave, lazyriver, multithread)

---

## 8. Phased Implementation Plan

### Wave Map

```
Phase 1 — Per-wave dispatch
  P1W1 ─── [1.1] Update /prepwaves — dispatch annotation
              │
  P1W2 ─── [1.2] Update /nextwave — dispatch hint reader
              │
  P1W3 ─── [1.3] Dispatch regression tests + README + MV-03

Phase 2 — /lazyriver goal-seek  (after Phase 1)
  P2W1 ─── [2.1] Create /lazyriver SKILL.md
              │
  P2W2 ─── [2.2] IT-03 + MV-01 + README finalize

Phase 3 — /multithread companion  (after Phase 2; P3W1 independent of Phase 2)
  P3W1 ─── [3.1] Create /multithread SKILL.md
              │
  P3W2 ─── [3.2] Final close — MV-02, E2E-01/02, VRTM, CHANGELOG
```

---

### Phase 1: Per-wave dispatch

**Goal:** `/prepwaves` annotates each wave with a fan/serialize dispatch hint; `/nextwave` reads it and dispatches accordingly.

#### Phase 1 DoD
- [ ] `/prepwaves` SKILL.md Step 4.A exists with four-rule classification table [R-01–R-05]
- [ ] `/nextwave` SKILL.md reads `dispatch` and fans or serializes [R-06, R-07]
- [ ] IT-01 and IT-02 pass
- [ ] Backward compat verified: existing plans without `dispatch` field are unchanged [CT-01]
- [ ] DM-12 and DM-13 produced and installed

---

#### Story 1.1: Update /prepwaves — dispatch annotation

**Wave:** P1W1 · **Dependencies:** None

Add per-wave dispatch classification to `/prepwaves` SKILL.md between the topology step (Step 4) and the approval gate (Step 6). Embed the `dispatch` field in the per-wave plan JSON before `wave_init`.

**Implementation Steps:**

1. Read `skills/prepwaves/SKILL.md` and locate Step 4 ("Compute waves").
2. After the topology classification call, insert new sub-step **4.A — Dispatch classification** with the four-rule table and the asymmetric bias note.
3. In Step 6 (approval gate wave plan presentation), include the `dispatch` annotation alongside each wave entry.
4. In Step 7 (persist), document `dispatch` as a round-trippable wave field alongside `cross_repo`/`target_repos`.
5. Mirror both `skills/prepwaves/SKILL.md` (source) and `~/.claude/skills/prepwaves/SKILL.md` (installed).

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_dispatch_width1_serialize` | Width-1 waves receive `dispatch: serialize` | `tests/test_prepwaves_dispatch.py` |
| `test_dispatch_fan_independent` | Clean-independent width-N waves receive `dispatch: fan` | `tests/test_prepwaves_dispatch.py` |
| `test_dispatch_hard_gate_intra_dep` | Intra-dep waves receive `dispatch: serialize` regardless of width | `tests/test_prepwaves_dispatch.py` |
| `test_dispatch_backward_compat` | `phases-waves.json` without `dispatch` field — nextwave treats as serialize | `tests/test_prepwaves_dispatch.py` |

**Acceptance Criteria:**

- [ ] Step 4.A in `/prepwaves` documents the four-rule classification table [R-01–R-05]
- [ ] Asymmetric bias note present (wrong serialize = wall-clock; wrong fan = wave kill) [R-07]
- [ ] `dispatch` field present in approval gate wave plan presentation [R-01]
- [ ] Step 7 documents `dispatch` as round-trippable in plan JSON [R-06]
- [ ] Both source and installed copies updated [CT-02]

---

#### Story 1.2: Update /nextwave — dispatch hint reader

**Wave:** P1W2 · **Dependencies:** 1.1

Add dispatch-reading logic to `/nextwave` SKILL.md. After loading a wave from `phases-waves.json`, read `dispatch` and route to fan or single-file execution path.

**Implementation Steps:**

1. Read `skills/nextwave/SKILL.md` and locate the wave execution section (pre-flight prep + flight dispatch).
2. After loading the wave, insert dispatch-reading logic: `dispatch: fan` → existing fan-out path (add asymmetric bias parenthetical); `dispatch: serialize`, `serialize-preferred`, or absent → existing single-file path.
3. Add a note: "If `dispatch` is absent, default is `serialize` (backward compat)."
4. Mirror both source and installed copies.

**Test Procedures:**

*Integration/E2E Coverage:*
- IT-02 (via Story 1.3's dispatch integration test harness)

**Acceptance Criteria:**

- [ ] `/nextwave` reads `dispatch` from the wave entry [R-06]
- [ ] `fan` → fanned; `serialize`/`serialize-preferred`/absent → single-file [R-06]
- [ ] Asymmetric bias note on the `fan` path [R-07]
- [ ] Absent `dispatch` → `serialize` (default) documented [CT-01]
- [ ] Both source and installed copies updated [CT-02]

---

#### Story 1.3: Dispatch regression tests + README + MV-03

**Wave:** P1W3 · **Dependencies:** 1.1, 1.2

Create the dispatch regression test file. Update README. Execute MV-03.

**Implementation Steps:**

1. Create `tests/test_prepwaves_dispatch.py` with the four test cases from Story 1.1 (consistent with existing test suite patterns).
2. Run `make ci` — all tests pass.
3. Update `README.md`: add `/lazyriver` and `/multithread` placeholder entries to the skills table; document per-wave dispatch model (1–2 sentence blurb).
4. Execute MV-03: invoke `/prepwaves` on a mixed-width backlog; verify dispatch annotations; record pass evidence.

**Test Procedures:**

*Unit Tests (created in this story):*
- `test_dispatch_width1_serialize`
- `test_dispatch_fan_independent`
- `test_dispatch_hard_gate_intra_dep`
- `test_dispatch_backward_compat`

**Acceptance Criteria:**

- [ ] `tests/test_prepwaves_dispatch.py` exists; 4 tests, all passing [IT-01, IT-02]
- [ ] `make ci` green [CT-02]
- [ ] README updated with dispatch model description + skill placeholders [DM-01]
- [ ] MV-03 executed; pass evidence recorded [R-01–R-07]

---

### Phase 2: Goal-seek `/lazyriver`

**Goal:** Create `/lazyriver` as a distinct goal-seek skill, clearly positioned upstream of `/devspec`.

#### Phase 2 DoD
- [ ] `skills/lazyriver/SKILL.md` exists and is installed [DM-10]
- [ ] Probe→judge→steer→journal loop documented [R-08, R-09]
- [ ] Sufficiency gate and escalation cord documented [R-10, R-14]
- [ ] Output contract (plan → /devspec; answer → user) documented [R-12]
- [ ] Epistemic vs artifact dependency distinction documented [R-13]
- [ ] IT-03 and MV-01 pass

---

#### Story 2.1: Create /lazyriver SKILL.md

**Wave:** P2W1 · **Dependencies:** None

Primary source material: `~/Documents/propose-executor-model.md` (Parts 3, 4, 5) + spike POST-HOC REFRAME section.

**Implementation Steps:**

1. Create `skills/lazyriver/` directory.
2. Write `skills/lazyriver/SKILL.md`:
   - Frontmatter: `name: lazyriver`, `description: Goal-seek loop — probe, judge sufficiency, steer, journal; emits a plan or answer`
   - Sections: Invocation, Core Loop (4-step schema), Sufficiency Gate, Escalation Cord (leg cap 10 or 2 consecutive zero-finding legs), Output Contract, Relationship to /devspec, Epistemic vs Artifact Dependency (comparison table from propose-executor-model.md §2), Reasoning Rules
   - Include the `GOAL → [/lazyriver] → PLAN → [/devspec] → [/wavemachine] → ARTIFACT` chain diagram
3. Install: `cp skills/lazyriver/SKILL.md ~/.claude/skills/lazyriver/SKILL.md`

**Test Procedures:**

*Integration/E2E Coverage:*
- IT-03: invoke `/lazyriver` on a real goal; verify terminates on sufficiency; emits plan/answer

**Acceptance Criteria:**

- [ ] `skills/lazyriver/SKILL.md` exists [DM-10]
- [ ] Probe→judge→steer→journal loop documented step-by-step [R-08, R-09]
- [ ] Sufficiency gate (re-evaluated each leg) documented [R-09]
- [ ] Escalation cord (DR or leg cap → escalate to user) documented [R-10, R-14]
- [ ] Findings journal (durable, cord-fire ≠ data loss) documented [R-11]
- [ ] Output contract (plan → /devspec; answer → user) documented [R-12]
- [ ] Epistemic dependency distinction documented [R-13]
- [ ] Escalation cord as /lazyriver primitive (not /wavemachine) documented [R-14]
- [ ] Installed to `~/.claude/skills/lazyriver/SKILL.md` [CT-02]

---

#### Story 2.2: IT-03 + MV-01 + README finalize

**Wave:** P2W2 · **Dependencies:** 2.1

Run IT-03. Execute MV-01 (force the escalation cord to fire). Complete README /lazyriver entry.

**Implementation Steps:**

1. Invoke `/lazyriver` on a real goal; verify terminates and emits plan. Record IT-03 pass evidence.
2. Execute MV-01: force the cord to fire; record pass evidence (journal intact post-cord).
3. Update README: replace /lazyriver placeholder with the real description.
4. Run `make ci` — green.

**Acceptance Criteria:**

- [ ] IT-03 pass evidence recorded [R-08, R-09, R-12]
- [ ] MV-01 pass evidence recorded (cord fires; journal intact) [R-10, R-11, R-14]
- [ ] README `/lazyriver` entry complete [DM-01]
- [ ] `make ci` green

---

### Phase 3: `/multithread` companion

**Goal:** Create `/multithread`, execute final verifications, complete VRTM, close the Plan.

#### Phase 3 DoD
- [ ] `skills/multithread/SKILL.md` exists and is installed [DM-11]
- [ ] 6-step procedure documented [R-15–R-19]
- [ ] Canonical example (agent-smith §5.N, 10 threads, ~3 rounds) included
- [ ] IT-04 and MV-02 pass
- [ ] E2E-01, E2E-02 pass
- [ ] CHANGELOG updated [DM-07]
- [ ] VRTM complete [DM-08]

---

#### Story 3.1: Create /multithread SKILL.md

**Wave:** P3W1 · **Dependencies:** None (independent of Phase 2)

Primary source: `~/Documents/propose-skill-multithread.md` (the proposal is already a near-complete spec).

**Implementation Steps:**

1. Create `skills/multithread/` directory.
2. Write `skills/multithread/SKILL.md`:
   - Frontmatter: `name: multithread`, `description: Parallelize N independent design decisions — enumerate, propose takes, batch-answer, converge, emit decision record`
   - Sections: Invocation, Procedure (6 steps), Load-bearing Properties (5 rules from the proposal), Output (decision record), Relationship to Wave Taxonomy, When to Use / When Not, Reasoning Rules
   - Include the canonical example: agent-smith §5.N, 10 open questions, ~3 batched turns
3. Install: `cp skills/multithread/SKILL.md ~/.claude/skills/multithread/SKILL.md`

**Test Procedures:**

*Integration/E2E Coverage:*
- IT-04: invoke `/multithread` on 5 independent items; verify convergence + decision record emitted

**Acceptance Criteria:**

- [ ] `skills/multithread/SKILL.md` exists [DM-11]
- [ ] 6-step procedure documented [R-15, R-17]
- [ ] "Lead with a take" rule documented [R-16]
- [ ] Stable labels + shrinking conversation documented [R-19]
- [ ] Loop-until-dry documented [R-17]
- [ ] Decision record output format documented [R-18]
- [ ] Canonical example (§5.N, 10 threads, ~3 rounds) included
- [ ] "When to use / when not" section included
- [ ] Installed to `~/.claude/skills/multithread/SKILL.md` [CT-02]

---

#### Story 3.2: Final close — MV-02, E2E-01/02, VRTM, CHANGELOG

**Wave:** P3W2 · **Dependencies:** 3.1, 2.2, 1.3

Execute all remaining verifications, complete the VRTM, update CHANGELOG, link dev spec from skills.

**Implementation Steps:**

1. Execute MV-02: invoke `/multithread` on 5–10 independent design questions; record pass evidence (≤ 4 rounds, stable labels, decision record emitted).
2. Execute E2E-01: full chain from goal → /lazyriver → plan → /devspec → /prepwaves → /nextwave on a `fan` wave; record pass evidence.
3. Execute E2E-02: invoke `/multithread` on a real Dev Spec §5.N; verify decision record in `[ledger D-NNN]` format; record pass evidence.
4. Complete VRTM (Appendix V): fill all R-01–R-19 rows with status.
5. Update `CHANGELOG.md` with a single entry covering all three phases.
6. Run `make ci` — green.
7. Add `See Also: docs/executor-model-devspec.md` to each updated skill's header block (prepwaves, nextwave, lazyriver, multithread).

**Acceptance Criteria:**

- [ ] MV-02 pass evidence recorded [R-16, R-17, R-18, R-19]
- [ ] E2E-01 pass evidence recorded [R-08, R-12, R-01, R-06]
- [ ] E2E-02 pass evidence recorded [R-15, R-17, R-18, R-19]
- [ ] VRTM complete: all R-01–R-19 traced [DM-08]
- [ ] CHANGELOG updated [DM-07]
- [ ] `make ci` green
- [ ] Dev spec linked from all four updated skills

---

## 9. Appendices

### Appendix A: Spike Findings Summary (F-1–F-12)

Curated from `~/Documents/lazy-river-spike.md`:

| # | Finding | Disposition |
|---|---|---|
| F-1 | /prepfloat building blocks are platform-coupled | Resolved: /prepfloat collapses into /prepwaves per-wave dispatch |
| F-2 | Parser dropped `depends_on` from `**Wave:**` line format | Fixed (`bf1b304`; separate `**Dependencies:**` line) — mcp-server-sdlc scope |
| F-3 | Compact prose test-procedures don't machine-extract | Confirmed harmless for goal-seek (executor reads AC + impl steps directly) |
| F-4 | §8 → upshift path is fully shared between executors | Confirmed: only execution diverges |
| F-5 | /prepwaves redundant after /devspec upshift | Confirmed: topology computed once, consumed by both |
| F-7 | MCP wave tools fail from non-repo cwd | Resolved: qualified `owner/repo#N` refs work; `--repo` param filed against mcp-server-sdlc |
| F-8 | Hand-assigned wave had intra-wave dep violation | Fixed (`8037349`). This class is caught by the dispatch hard gate (R-03). |
| F-10 | DI-seam-then-close is the systematic answer to float-order friction | Confirmed ×5 across 4 phases; to be documented in /lazyriver Reasoning Rules |
| F-11 | Undeclared shared primitives discoverable mid-float | Confirmed; river absorbs; pool has latent hazard |
| F-12 | Infra stories → artifact + structural validation; defer live bring-up | Confirmed; not an escalation |

### Appendix B: Executor Model (Two-Mode Reframe Summary)

From `~/Documents/propose-executor-model.md`:

| | Plan-execution | Goal-seeking (/lazyriver) |
|---|---|---|
| Input | complete DAG | goal |
| Terminates on | completeness | sufficiency (judgment) |
| Parallelizable? | yes (per-wave) | no — epistemic dependency |
| Agency | ≈ 0 (execute the spec) | maximal (each leg is a steering judgment) |
| Escalation cord | vestigial (0/28 fires) | core loop |

**Measured (agent-smith, build-normalized):** pool ≈ 1.18× the river; the gap is small because 9/18 waves were width-1 and max parallelism was 3.

### Appendix V: VRTM (completed — Story 3.2, #829)

All R-01–R-19 verified. Evidence is the merged story PR/SHA plus the named
verification item (integration test, skill inspection, or manual/E2E procedure).
Manual (MV) and end-to-end (E2E) pass evidence is recorded in
`docs/executor-model-mv-results.md` (DM-14).

| Req ID | Requirement (short) | Source | Verification Item | Method | Status |
|---|---|---|---|---|---|
| R-01 | /prepwaves computes dispatch per wave | Story 1.1 AC | IT-01 + skill inspection | Integration + inspection | **Pass** — Story 1.1 (#830, `0b0cbd2`) Step 4.A; `test_dispatch_fan_independent` green |
| R-02 | Width-1 → serialize | Story 1.1 AC | IT-01 width-1 test | Integration | **Pass** — `test_dispatch_width1_serialize` green (#830, `0b0cbd2`) |
| R-03 | Intra-dep → serialize hard gate | Story 1.1 AC | IT-01 hard gate test | Integration | **Pass** — `test_dispatch_hard_gate_intra_dep` green (#830, `0b0cbd2`) |
| R-04 | Independent mechanical → fan | Story 1.1 AC | IT-01 fan test | Integration | **Pass** — `test_dispatch_fan_independent` green (#830, `0b0cbd2`) |
| R-05 | Learning potential → serialize-preferred | Story 1.1 AC | IT-01 preference test | Integration + inspection | **Pass** — Story 1.1 Step 4.A rule-4 row (#830, `0b0cbd2`); MV-03 |
| R-06 | /nextwave reads dispatch + dispatches | Story 1.2 AC | IT-02 | Integration | **Pass** — Story 1.2 (#824→#832, `0fbec36`); `test_dispatch_backward_compat` green |
| R-07 | Asymmetric bias documented | Story 1.1 + 1.2 AC | Skill inspection + MV-03 | Inspection + manual | **Pass** — bias note in `/prepwaves` + `/nextwave`; MV-03 (Story 1.3, #825→#834, `5ef10e7`) |
| R-08 | /lazyriver probe-judge-steer-journal | Story 2.1 AC | IT-03 | Integration | **Pass** — Story 2.1 (#836, `9803285`) Core Loop; IT-03 (Story 2.2, #838, `e87f5a5`) |
| R-09 | Sufficiency gate each leg | Story 2.1 AC | IT-03 | Integration | **Pass** — Story 2.1 (#836, `9803285`); IT-03 (Story 2.2, #838) |
| R-10 | Escalation cord on DR/budget | Story 2.1 AC | MV-01 | Manual | **Pass** — Story 2.1 (#836); MV-01 cord fired (Story 2.2, #838, `e87f5a5`) |
| R-11 | Findings journal | Story 2.1 AC | IT-03 + MV-01 | Integration + manual | **Pass** — Story 2.1 (#836); MV-01 journal intact post-cord (#838) |
| R-12 | Output: plan or answer | Story 2.1 AC | IT-03 + E2E-01 | Integration + E2E | **Pass** — Story 2.1 (#836); IT-03 (#838); E2E-01 (Story 3.2, #829) |
| R-13 | Epistemic vs artifact dependency | Story 2.1 AC | Skill inspection | Inspection | **Pass** — `/lazyriver` "Epistemic vs Artifact Dependency" section (#836, `9803285`) |
| R-14 | Escalation cord as /lazyriver primitive | Story 2.1 AC | Skill inspection | Inspection + manual | **Pass** — `/lazyriver` cord section (#836); MV-01 (#838) |
| R-15 | /multithread enumerate + present | Story 3.1 AC | IT-04 + E2E-02 | Integration + E2E | **Pass** — Story 3.1 (#817 `1321da2` + #840 `9c5b57a`); IT-04; E2E-02 (#829) |
| R-16 | Take-first rule | Story 3.1 AC | MV-02 | Manual | **Pass** — `/multithread` Reasoning Rule 1 (#817/#840); MV-02 (Story 3.2, #829) |
| R-17 | Batch-answer + converge until dry | Story 3.1 AC | IT-04 + MV-02 | Integration + manual | **Pass** — `/multithread` Steps 3–5 (#817/#840); IT-04; MV-02 (#829) |
| R-18 | Decision record emitted | Story 3.1 AC | IT-04 + E2E-02 | Integration + E2E | **Pass** — `/multithread` Step 6 (#817/#840); E2E-02 `[ledger D-NNN]` record (#829) |
| R-19 | Stable labels | Story 3.1 AC | MV-02 | Manual | **Pass** — `/multithread` Reasoning Rule 3 (#817/#840); MV-02 no-renumber check (#829) |
