# DDD → Dev Spec Translation Protocol

> **Recommended:** Use `/devspec create` with a DDD domain model as input to automate this translation interactively. The `/devspec create` skill walks each Dev Spec section with you, applies the mapping rules below, and manages the Deliverables Manifest. This protocol document remains as reference for understanding the mapping, but the primary workflow is now: `/ddd accept` (produces concept handoff) → `/devspec create` (produces Dev Spec).

This guide documents the process for converting a Domain Model (Event Storming output) into a Development Specification following the Dev Spec template (`docs/devspec-template.md`).

## Purpose

After completing Domain-Driven Design via event storming, you have a **Domain Model** — a complete picture of your domain's events, commands, actors, policies, aggregates, and read models. This document shows how to translate that model into an **implementation-ready Dev Spec** that agents and developers can execute from.

**Key principle:** DDD doesn't replace requirements — it **discovers** them. The Dev Spec is still the contract with implementers. This protocol is the bridge.

---

## Prerequisites

Before starting translation, ensure you have:

- [x] **Completed Domain Model** (`docs/DOMAIN-MODEL.md`) with:
  - Events catalog (E-01, E-02, ...)
  - Commands list (C-01, C-02, ...)
  - Actors responsibility matrix
  - Policies table (P-01, P-02, ...) grouped by type
  - Aggregates definition with state machines
  - Read Models inventory
- [x] **Dev Spec Template** (`docs/devspec-template.md`)
- [x] **Project name** for output file naming

---

## Translation Steps

### Step 1: Extract Personas (DDD Actors → Dev Spec Section 1.4)

**Input:** Actors responsibility matrix from Domain Model Section 5
**Output:** Persona table in Dev Spec Section 1.4 (Target Users)

**Process:**

1. For each Actor in the matrix, create a Persona entry
2. Commands issued → Primary Use Case column
3. "Human only" vs "Agent only" vs "Human + Agent" → Description

**Example:**

**From Domain Model:**
```markdown
| Actor | Commands | Responsibility |
|-------|----------|---------------|
| **Executive Producer (Human)** | C-01, C-03, C-11, C-17 | Approval gates, "ship it" decision |
```

**→ Becomes Dev Spec Section 1.4:**
```markdown
| Persona | Description | Primary Use Case |
|---------|-------------|------------------|
| **Executive Producer (Human)** | BJ — commissions videos, approves creative decisions, makes final "ship it" judgment | Issues C-01 (Commission Video), C-03 (Approve Script), C-11 (Approve Voiceover), C-17 (Approve Final Cut). Judgment-based gates where only human can decide. |
```

**Traceability:** Reference command IDs in use case so implementers can trace back to Domain Model.

---

### Step 2: Design Data Model (DDD Aggregates → Dev Spec Section 5.1)

**Input:** Aggregates section from Domain Model Section 7
**Output:** Data Model section (Dev Spec Section 5.1) with state machines, invariants, relationships

**Process:**

1. For each Aggregate:
   - **State field** → State machine diagram (states + transitions + events)
   - **Invariants** → Rules subsection (what cannot happen)
   - **Relationships** → Ownership diagram (what references what)
2. Draw aggregate relationship tree
3. Add monorepo file location table if applicable

**Example:**

**From Domain Model:**
```markdown
#### Video (Root Aggregate)

**State machine:**
- **States:** idea | commissioned | in-production | approved | published | retired | cancelled
- **Transitions:** E-03 (idea → commissioned), E-44 (in-production → approved), E-54 (approved → published), E-63 (any → cancelled)

**Invariants:**
- Cannot publish without E-44 (Final Cut Approved)
- Cannot retire unless state = published
- Cancellation reachable from any pre-published state

**Relationships:**
- References Script (1:1), Creative Briefs (1:many), Voiceover (1:1), Composition (1:1)
```

**→ Becomes Dev Spec Section 5.1:**
````markdown
### 5.1 Data Model

#### Video (Root Aggregate)

**Lifecycle:**
```
idea → commissioned → in-production → approved → published → retired
                         ↓
                     cancelled (reachable from any pre-published state)
```

**State Transitions:**
- E-03: idea → commissioned (Commission Video)
- E-44: in-production → approved (Final Cut Approved)
- E-54: approved → published (Publish Video)
- E-63: any → cancelled (Cancel Video)

**Invariants:**
- Cannot transition to `published` without E-44 (Final Cut Approved) occurring
- Cannot transition to `retired` unless current state = `published`
- E-63 (Cancel Video) can transition from any state except `published`

**Relationships:**
- Script: 1:1 (owns)
- Creative Briefs: 1:many (owns)
- Voiceover: 1:1 (owns)
- Composition: 1:1 (owns)
- Reviews: 1:many (owns)
- Renders: 1:many (owns)
````

**Traceability:** Reference event IDs for transitions, maintain link back to Domain Model.

---

### Step 3: Extract Requirements (DDD Policies → Dev Spec Section 3)

**Input:** Policies section from Domain Model Section 6
**Output:** EARS-formatted requirements in Dev Spec Section 3, grouped by theme

**Process:**

1. For each policy, apply the heuristic table below
2. Convert "When/Then" to EARS format
3. Annotate with policy ID for traceability (e.g., `[P-07]`)
4. Group requirements by theme (cascade, quality, notification, lifecycle, etc.)

**Heuristic Table:**

| Policy Type | EARS Pattern | Template |
|-------------|-------------|----------|
| **Cascade** | Event-driven | When [event], the system shall [trigger command/event]. |
| **Quality** | Unwanted | If [bad condition], then the system shall [reject/log/escalate]. |
| **Notification** | Event-driven | When [event], the system shall [notify actor via channel]. |
| **Loop** | State-driven | While [condition not met], the system shall [repeat action]. |

**Example:**

**From Domain Model (Cascade Policy):**
```markdown
| P-07 | Composition Assembled (E-34) + Voiceover Approved (E-24) + Sound Designed (E-29) | Trigger Render Rough Cut (C-16) | First renderable state — join gate |
```

**→ Becomes Dev Spec Section 3:**
```markdown
### 3.2 Production Requirements

| ID | Type | Requirement |
|----|------|-------------|
| R-17 | Event-driven | When Composition Assembled (E-34) AND Voiceover Approved (E-24) AND Sound Designed (E-29), the system shall trigger Render Rough Cut (C-16). [P-07] |
```

**From Domain Model (Quality Policy):**
```markdown
| P-10 | Asset Ingested (E-12) | Validate format, resolution, file size | Catch bad assets before composition |
```

**→ Becomes Dev Spec Section 3:**
```markdown
| R-20 | Unwanted | If Asset Ingested (E-12) with invalid format, incorrect resolution, or excessive file size, then the system shall reject the asset and trigger E-61 (Asset Creation Failed). [P-10] |
```

**Traceability:** Annotate requirements with `[P-XX]` so reviewers can trace back to the policy.

---

### Step 4: Write Operational Flows (DDD Commands → Dev Spec Section 4)

**Input:** Commands section from Domain Model Section 4
**Output:** Concept of Operations flows (Dev Spec Section 4.X)

**Process:**

1. For each command with a serial chain, create a flow subsection
2. **Serial chain** → numbered steps showing event progression
3. **Decision points** → "Gate: [actor] issues [command]"
4. **Loop policies** → "Loop until [exit condition]"
5. **Cascade policies** → show parallel branches (e.g., P-02 triggers 3 workstreams from E-08)
6. **Join gates** → show convergence points (e.g., P-07: three streams merge)

**Example:**

**From Domain Model:**
```markdown
| C-01 | Commission Video | E-01 → E-02 → E-03 → E-04 | "Yes, we're making this" |
```
```markdown
| P-02 | Script Approved (E-08) | Start Request Assets (C-04), Finalize VO Script (C-10), Scaffold Composition (E-30) | Locked script defines what's needed |
```
```markdown
| P-07 | E-34 + E-24 + E-29 | Trigger Render Rough Cut (C-16) | Join gate |
```

**→ Becomes Dev Spec Section 4.2: Primary Production Flow:**
```markdown
### 4.2 Primary Production Flow

**Trigger:** Human (EP) issues **Commission Video** (C-01)

1. **Ideation → Commission** (C-01 serial chain)
   - E-01: Video Idea Captured
   - E-02: Video Brief Written (audience, goal, messages, length)
   - E-03: Video Commissioned (approval gate)
   - E-04: Research Completed

2. **Script Iteration** (C-02, human-in-loop)
   - E-05: Script Drafted
   - E-06: Script Reviewed
   - E-07: Script Revised (loop)
   - **Gate:** Human issues **Approve Script** (C-03) → E-08

3. **Parallel Workstreams** (triggered by P-02 on E-08)
   ```
                    ┌─► Asset Sourcing (C-04, P-02)
                    │
   Script Approved ─┼─► Voiceover Recording (C-10, P-03)
                    │
                    └─► Composition Scaffolding (E-30, P-04)
   ```

4. **Join Gate** (P-07: E-34 + E-24 + E-29 all true)
   - Composition Assembled (E-34)
   - Voiceover Approved (E-24)
   - Sound Designed (E-29)
   - **Trigger:** System automatically initiates **Render Rough Cut** (C-16)

5. **Review Loop** (C-16, human-in-loop)
   - E-38 → E-39 → E-40 → E-41 → E-42 → E-43 (loop until approved)
   - **Gate:** Human issues **Approve Final Cut** (C-17) → E-44

6. **Render Deliverables** (C-18, agent-autonomous, triggered by P-08 on E-44)
   - E-45 → E-46 → E-47 → E-49 → E-50 → E-51 → E-52 (deterministic)

7. **Publication** (C-19, human decides when, agent executes)
   - E-53 → E-54 → E-55
```

**Traceability:** Reference command IDs (C-XX), event IDs (E-XX), and policy IDs (P-XX) throughout.

---

### Step 5: Design API/UI (DDD Read Models → Dev Spec Section 5.X)

**Input:** Read Models section from Domain Model Section 8
**Output:** API surface or UI component specs in Dev Spec Section 5.X

**Process:**

1. For each Read Model:
   - **"Shows" column** → API response schema OR UI mockup/wireframe
   - **"Informs Decision" column** → usage documentation (when/why actor uses this)
   - **Actor** → intended consumer
2. Create one endpoint or view per read model
3. Document query parameters, response format, and update frequency

**Example:**

**From Domain Model:**
```markdown
| RM-03 | Rough Cut Player | "Does this cut feel right?" (C-16, C-17) | Video playback, timestamp-linked feedback, script side-by-side, caption toggle |
```

**→ Becomes Dev Spec Section 5.2: Read Model API:**
````markdown
### 5.2 Read Model API

**RM-03: Rough Cut Player** (supports C-16 iteration, C-17 approval decision)

**Purpose:** Allows Executive Producer to review rendered cuts and provide timestamp-linked feedback.

**Endpoint:** `GET /videos/{video_id}/review/{render_id}`

**Response:**
```json
{
  "video_url": "https://...",
  "script": {
    "scenes": [
      {"id": "scene-1", "start_time": 0, "text": "..."}
    ]
  },
  "feedback": [
    {"timestamp": 42.5, "author": "EP", "comment": "Pacing too slow here"}
  ],
  "captions": {
    "enabled": true,
    "url": "https://.../captions.vtt"
  }
}
```

**Used by:** Human (Executive Producer) at C-17 approval gate
**Traceability:** Verifies R-XX (requirement for review capability)
````

---

### Step 6: Create Test Plan (DDD Read Models + Policies → Dev Spec Section 6)

**Input:** Policies (for integration tests), Read Models (for manual verification)
**Output:** Test Plan (Dev Spec Section 6) with IT-XX, E2E-XX, MV-XX items

**Process:**

1. **For each cascade policy** → integration test (verify trigger works)
   - Test: simulate event, verify triggered command/event occurred
2. **For each quality policy** → integration test (verify validation)
   - Test: inject bad data, verify rejection + error handling
3. **For each read model** → manual verification procedure
   - Procedure: steps to exercise the view, pass criteria
4. Annotate each test item with requirement IDs it verifies

**Example:**

**From Policies:**
```markdown
| P-07 | E-34 + E-24 + E-29 | Trigger Render Rough Cut (C-16) | Join gate |
| P-10 | Asset Ingested (E-12) | Validate format, resolution | Catch bad assets |
```

**→ Becomes Dev Spec Section 6.2: Integration Tests:**
```markdown
| ID | Boundary | Description | Req IDs |
|----|----------|-------------|---------|
| IT-07 | Production Orchestrator → Render Queue | Verify P-07 join gate: When E-34, E-24, E-29 all occur (any order), C-16 is triggered exactly once | [R-17] |
| IT-10 | Asset Ingestion → Validator | Verify P-10 quality gate: Asset with invalid format is rejected and E-61 is triggered | [R-20] |
```

**From Read Models:**
```markdown
| RM-03 | Rough Cut Player | Video playback, timestamp feedback |
```

**→ Becomes Dev Spec Section 6.4: Manual Verification:**
```markdown
| ID | Procedure | Pass Criteria | Req IDs |
|----|-----------|--------------|---------|
| MV-03 | **Rough Cut Player UX:** 1. Load `/videos/{id}/review/{render_id}`, 2. Play video, 3. Add timestamp comment at 1:23, 4. Reload page | Comment persists with correct timestamp (1:23), feedback list updates | [R-XX] |
```

---

### Step 7: Decompose into Stories (DDD Aggregates + Policies → Dev Spec Section 8)

**Input:** Aggregates (Section 7), Policies (Section 6), Commands (Section 4) from Domain Model
**Output:** Phased Implementation Plan (Dev Spec Section 8) with stories grouped into waves

**Process:**

1. **Foundation Wave (Wave 1):**
   - One story per aggregate to implement state machine
   - Foundation checklist items (scaffold, CI, linting, test runner, Makefile)

2. **Policy Waves (Wave 2+):**
   - One story per cascade policy (implement trigger logic)
   - One story per quality policy (implement validation)
   - Group by dependencies (Policy P-06 depends on Policies P-02, P-04 completing)

3. **Read Model Wave:**
   - One story per read model (implement query/view)

4. **Closing Wave (Final):**
   - Manual verification story (execute all MV-XX procedures from Test Plan)
   - Complete VRTM (Appendix V)

5. **Story structure:**
   - Title: Brief description
   - Wave: Number
   - Dependencies: Story IDs or "None"
   - Implementation Steps: Paint-by-numbers instructions
   - Test Procedures: Unit tests (table) + IT/E2E coverage
   - Acceptance Criteria: Checklist with requirement IDs

**Example:**

**From Aggregate:**
```markdown
#### Video (Root Aggregate)
State machine: idea → commissioned → in-production → approved → published → retired
```

**From Policy:**
```markdown
| P-07 | E-34 + E-24 + E-29 | Trigger C-16 | Join gate |
```

**→ Becomes Dev Spec Section 8:**
```markdown
#### Story 1.1: Implement Video Aggregate

**Wave:** 1
**Dependencies:** None

Implement the Video aggregate with full lifecycle state machine.

**Implementation Steps:**
1. Create `Video` class in `src/aggregates/video.py`
2. Add state enum: `VideoState = idea | commissioned | in_production | approved | published | retired | cancelled`
3. Implement state transitions per E-03, E-44, E-54, E-63
4. Enforce invariants:
   - Cannot publish without `final_cut_approved` flag
   - Cannot retire unless `state == published`
5. Add references: `script_id`, `brief_ids[]`, `voiceover_id`, `composition_id`

**Test Procedures:**

*Unit Tests:*
| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_video_lifecycle` | Verify state transitions E-03, E-44, E-54 | `tests/test_video.py` |
| `test_publish_requires_approval` | Verify invariant: cannot publish without E-44 | `tests/test_video.py` |

**Acceptance Criteria:**
- [ ] Video aggregate exists with `VideoState` enum [R-XX]
- [ ] State transitions via E-03, E-44, E-54, E-63 work correctly [R-XX]
- [ ] Cannot publish without E-44, test passes [R-XX]
- [ ] All unit tests in `tests/test_video.py` pass

---

#### Story 2.5: Implement P-07 Join Gate

**Wave:** 2
**Dependencies:** Story 2.1 (Composition), Story 2.3 (Voiceover), Story 2.4 (Sound)

Implement the join gate that triggers rough cut rendering when all three prerequisites are met.

**Implementation Steps:**
1. Create `ProductionOrchestrator` class in `src/orchestration/`
2. Add method `check_rough_cut_readiness(video_id)`:
   - Query Video aggregate for E-34, E-24, E-29 status
   - If all three true AND rough cut not yet rendered, return `True`
3. Add event listener on `CompositionAssembled`, `VoiceoverApproved`, `SoundDesigned`
4. Wire to command dispatcher so C-16 executes

**Test Procedures:**

*Unit Tests:*
| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_join_gate_all_true` | When E-34, E-24, E-29 true, returns `True` | `tests/test_orchestrator.py` |
| `test_join_gate_missing_one` | When any one missing, returns `False` | `tests/test_orchestrator.py` |
| `test_no_duplicate_render` | Render triggered exactly once | `tests/test_orchestrator.py` |

*Integration Coverage:*
- IT-07 — now runnable (this story implements the join gate boundary)

**Acceptance Criteria:**
- [ ] `check_rough_cut_readiness()` returns `True` when all 3 events true [R-17]
- [ ] Returns `False` when any one missing [R-17]
- [ ] Render command enqueued exactly once (no duplicates) [R-17]
- [ ] Test: events in random order trigger correctly [R-17]
- [ ] IT-07 integration test passes
```

**Traceability:** Each AC item annotated with `[R-XX]` links back to requirements, which link back to policies.

---

### Step 8: Preserve Traceability

**Process:**

1. **Add Section 0 to Dev Spec:** "Domain Model Reference" with link to `docs/DOMAIN-MODEL.md`
2. **Append Domain Event Catalog (Appendix D):** Full E-XX list from Domain Model
3. **Create VRTM skeleton (Appendix V):** Table with columns: Req ID, Requirement (short), Source, Verification Item, Verification Method, Status
4. **Cross-reference throughout:**
   - Requirements annotated with `[P-XX]` (policy source)
   - Flows annotated with `C-XX`, `E-XX`, `P-XX`
   - Stories annotated with `[R-XX]` in AC items
5. **After implementation:** Complete VRTM with Pass/Fail/Pending status

**Example Section 0:**
```markdown
## 0. Domain Model Reference

This Dev Spec was generated from a Domain Model created via Event Storming (Domain-Driven Design). The complete Domain Model is preserved at `docs/DOMAIN-MODEL.md`.

**Traceability:**
- Requirements (Section 3) extracted from Policies (Domain Model Section 6)
- Data Model (Section 5.1) derived from Aggregates (Domain Model Section 7)
- Operational Flows (Section 4) derived from Commands (Domain Model Section 4)
- Implementation Stories (Section 8) decomposed from Aggregates + Policies

**Key mappings:**
- Policy P-07 → Requirement R-17 → Story 2.5
- Aggregate Video → Data Model Section 5.1 → Story 1.1
- Command C-01 → Flow Section 4.2 → Stories 1.X, 2.X

For full event catalog, see Appendix D. For verification traceability, see Appendix V (VRTM).
```

---

## Quality Checks

Before declaring translation complete, verify:

- [ ] **Every policy** has a corresponding requirement in Section 3
- [ ] **Every aggregate** has a data model subsection in Section 5.1
- [ ] **Every command** appears in an operational flow in Section 4
- [ ] **Every read model** has an API/UI design in Section 5 and a test item in Section 6
- [ ] **Every requirement** is annotated with policy ID (e.g., `[P-07]`)
- [ ] **Every story AC item** is annotated with requirement ID (e.g., `[R-17]`)
- [ ] **Domain Model** appended to Dev Spec as Section 0 reference
- [ ] **Event catalog** included as Appendix D
- [ ] **VRTM skeleton** created as Appendix V

If any check fails, the translation is incomplete. Return to the missing step.

---

## Common Pitfalls

### 1. Forgetting Loop Exit Conditions
**Problem:** Policy P-XX says "iterate C-16" but doesn't specify exit.
**Fix:** Every loop must have an explicit exit condition in the flow. Example: "Loop C-16 until C-17 (Approve Final Cut) or C-21 (Cancel Video)".

### 2. Orphaned Policies
**Problem:** Policy P-XX is in Domain Model but no requirement in Dev Spec.
**Fix:** Apply Step 3 heuristic to every policy — no policy should be skipped.

### 3. Vague Requirements
**Problem:** "System shall handle X" — not specific enough.
**Fix:** EARS format forces precision. "When [event], system shall [specific action]".

### 4. Missing Join Gates
**Problem:** Cascade policies P-02, P-03, P-04 all trigger from E-08, but no join gate when they complete.
**Fix:** Look for accumulator policies (like P-28) or explicit join policies (like P-07) that converge parallel streams. Document convergence in flows.

### 5. Read Models Without Tests
**Problem:** Read model RM-03 has API design but no MV-XX test.
**Fix:** Every read model needs at least one manual verification procedure in Section 6.4.

### 6. Stories Without Traceability
**Problem:** Story AC items don't reference requirement IDs.
**Fix:** Annotate every AC item with `[R-XX]` so VRTM can be completed post-implementation.

---

## Output Artifacts

After completing this protocol, you will have:

1. **Dev Spec** (`docs/[project]-devspec.md`) with:
   - Section 0: Domain Model Reference
   - Section 1.4: Personas (from Actors)
   - Section 3: Requirements (from Policies, EARS format)
   - Section 4: Operational Flows (from Commands)
   - Section 5.1: Data Model (from Aggregates)
   - Section 5.X: API/UI Design (from Read Models)
   - Section 6: Test Plan (from Policies + Read Models)
   - Section 8: Implementation Stories (from Aggregates + Policies)
   - Appendix D: Domain Event Catalog
   - Appendix V: VRTM skeleton
2. **Full traceability:** Policy → Requirement → Flow → Story → AC → Test
3. **Implementation-ready spec:** Agents can execute from Dev Spec with confidence

The Dev Spec can now feed into existing workflow: `/prepwaves` → `/nextwave` → execution.

---

## Maintenance

**If the Domain Model changes after `/ddd accept`:**
1. Update `docs/DOMAIN-MODEL.md` with changes
2. Re-run `/ddd accept` to regenerate Dev Spec
3. Domain Model is the source of truth — Dev Spec is always derivable

**Do not edit Dev Spec directly.** Treat it as compiled output from the Domain Model.
