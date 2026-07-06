<!-- DEV-SPEC-APPROVAL
approved: true
approved_by: BJ
approved_at: 2026-07-06T12:00:35Z
finalization_score: 8/8
-->

# FlightDeck — Development Specification

> **Status:** APPROVED (BJ · 8/8) · upshifted — 25 Story issues #855–#879 filed, phases-waves.json written. Runtime state on #854.
> **Plan:** #854 · **Decision Ledger:** comments on #854 (`[ledger D-NNN]`) · **Mockup:** https://claude.ai/code/artifact/3a6ff161-9421-4434-98fc-689120474071

---

## 1. Problem Domain

### 1.1 Background
The wave-pattern pipeline runs long, autonomous, multi-agent work in the background — `/wavemachine` campaigns and `/lazyriver` floats. An operator running several concurrently needs to know, at a glance and in real time, what each is doing, what's stalled, and what got papered over. The current status surfaces don't deliver that.

### 1.2 Problem Statement
Three structural failures make today's panels near-useless:
- **Render is an agent chore** — `generate-status-panel` only runs when an agent remembers → stale, no refresh.
- **Truth and view are the same buried artifact** — a hand-regenerated per-project HTML file, not centrally accessible, no durable URL.
- **The renderer recomputes state with its own lookups** — the ENG-7 bug class, where the view disagrees with the engine (every issue shows "pending" when it's closed).

Beyond those: no multi-session view, no idle-but-incomplete stall detection, no papered-over-concern surfacing, and no useful metrics or ETA.

### 1.3 Proposed Solution
**FlightDeck** — a deterministic, event-sourced status console. Every state change emits a typed, scoped event at the lowest deterministic layer to one append-only log; a **containerized service in the Swarm** (behind existing ingress) folds that log into a live UI at a **durable URL**. Campaigns and floats render from one identical card anatomy, with a split machine/blocked-on-you ETA, idle-stall detection + Discord push, a first-class concern queue, and scoped log drill-down. **No agent in the reporting path.**

### 1.4 Target Users
- **Primary — the operator (BJ):** at-a-glance multi-session status, stall detection, and a concern queue to cycle back on.
- **Secondary — the oaw fleet agents:** outbound-only *emitters*; they emit, they never view.
- **Viewers via Swarm ingress:** internal and external (incl. phone), without exposing any agent host.

### 1.5 Non-Goals
- **NG-1** — FlightDeck does not deploy itself; deploy is the operator's step (Dockerfile + Swarm stack file delivered only). *(ABSOLUTE prod rule.)*
- **NG-2** — FlightDeck does not re-implement wave state; it consumes events, never reads/writes `state.json`.
- **NG-3** — No ingress on any agent host; agents are outbound-only emitters.
- **NG-4** — Excludes the #853 self-instrumentation engine work; token metrics stub until it lands.
- **NG-5** — Does not replace the #852 lazyriver go-forward UX; it consumes that emit.
- **NG-6** — v1 is operational *status*, not a BI/analytics warehouse.

---

## 2. Constraints

### 2.1 Technical
- **TC-1** — Emit is fire-and-forget, never on the hot path; durable local buffer; ingest-unreachable ⇒ buffer-only, never raises. Python path stdlib-only.
- **TC-2** — Workflow scripts have no filesystem/`Date`/`Math.random` (breaks resume); runtime emits originate from `agent()` prompts or a post-node hook, never the script body.
- **TC-3** — The event log is the single source of truth; the view is a pure, rebuildable fold (ENG-7 class structurally impossible).
- **TC-4** — One shared, versioned event JSON Schema is the contract; Python emitter + TS service both validate against it (schema, not shared code).
- **TC-5** — Agent hosts are outbound-only; authenticated ingest (token / mTLS).
- **TC-6** — FlightDeck consumes events only; never reads/writes `state.json`.
- **TC-7** — Token metrics gated on #853; stubbed (seamed-absent) until it lands, never faked.
- **TC-8** — Runtime = Bun/TS; store = append-only JSONL log + SQLite materialized view.

### 2.2 Product
- **PC-1** — The operator deploys; Plan delivers Dockerfile + Swarm stack/compose + config only; no Swarm/prod manifest edits, no deploy.
- **PC-2** — Deployed in the Swarm behind existing ingress (internal + external view); no new ingress surface on agent hosts.
- **PC-3** — 100% deterministic status surface (no agent in the reporting path).
- **PC-4** — Campaign and float render from one identical card anatomy (legs ≈ waves).
- **PC-5** — Cutover deletes all four stale renderers; FlightDeck is the single status surface.
- **PC-6** — The concern queue is first-class (papered-over surfacing).

---

## 3. Requirements (EARS)

**Emit**
- **R-01** — When a `wave_status` mutator commits a state change, the emitter shall append a typed, scope-tagged event to the durable local buffer.
- **R-02** — When an event is buffered and `FLIGHTDECK_INGEST_URL` is set, the emitter shall POST it to the ingest endpoint without blocking the caller.
- **R-03** — If the ingest endpoint is unreachable, then the emitter shall retain the event in the buffer and shall not raise to the caller.
- **R-04** — When the ingest endpoint becomes reachable after a failure, the shipper shall replay unsent buffered events in order.
- **R-05** — When a coded escape hatch is taken or an agent declares a DI-seam, the emitter shall emit a `concern` event tagged `coded` or `declared` respectively.

**Ingest & store**
- **R-06** — If an ingest request lacks a valid auth token, then the service shall reject it (401) and shall not persist it.
- **R-07** — If an ingested event fails schema validation, then the service shall reject it (400) and shall not persist it.
- **R-08** — When a valid event is ingested, the service shall append it to the append-only log and update the materialized view via the single fold.
- **R-09** — When the materialized view is dropped or rebuilt, the service shall reproduce identical view state by re-folding the event log.

**View & UI**
- **R-10** — The console shall render campaigns and floats from one identical card anatomy, differing only in the estimator label.
- **R-11** — The console shall be reachable at a durable URL and shall push live updates without a manual refresh.
- **R-12** — Where multiple activities are active, the console shall present them as a card grid by default.
- **R-13** — When the operator toggles a lane's view, the console shall switch that lane between card and dense-table layouts independently (Active → cards, Closed/Idle → table by default).
- **R-14** — While a card is collapsed, the console shall show a compact vitals row; when expanded, it shall show the full metrics grid.
- **R-15** — When the operator selects a log scope (Phase/Wave/Flight/Leg), the console shall show the transcript filtered to that scope.

**Metrics & ETA**
- **R-16** — The console shall derive wall-clock, idle (blocked-on-human), CI-wait, merge-collision, per-wave confidence, and per-wave drift from event data.
- **R-17** — The console shall present the ETA as two independent figures — machine-time and blocked-on-you.
- **R-18** — While an activity is a campaign, the ETA shall be a plan-denominator burn-down that narrows as steps land; while a float, a cord-bounded band with a converging/exploring indicator.
- **R-19** — Where per-node token usage is unavailable (#853 not landed), the token metric shall render as an explicit stub, not a fabricated value.

**Concerns & staleness**
- **R-20** — The console shall aggregate all `concern` events into a global queue, each linked to its exact Phase/Wave/Flight/Leg scope.
- **R-21** — While an activity is stalled with open concerns, the console shall sort it to the top of the deck.
- **R-22** — When an activity's last event is older than the staleness threshold and its terminal state is not reached, the service shall flag it idle-but-incomplete.
- **R-23** — When an activity is flagged idle-but-incomplete, the service shall push an outbound alert via disc-server.

**Cutover & deploy**
- **R-24** — When FlightDeck is confirmed live, the cutover shall delete all four legacy renderers.
- **R-25** — The deliverables shall include a Dockerfile and a Swarm stack/compose file that a human operator deploys.
- **R-26** — If a change would modify a Swarm/prod manifest or perform a deploy, then the pipeline shall not make it (operator-only).

---

## 4. Concept of Operations

### 4.1 System Context
FlightDeck is a passive downstream observer. Data flows one direction — agents never receive anything back:

```
 agent hosts (marlor, …)                        SWARM
 ┌──────────────────────────┐        ┌──────────────────────────────┐
 │ emitters                 │        │  FlightDeck container        │
 │  • state.py mutators     │ POST   │   ingest (auth) → event log  │
 │  • sdlc TS handlers      │──────▶ │   → single fold → SQLite view│
 │  • Workflow-runtime tee  │ (f&f)  │   → metrics/ETA              │
 │  • session hook          │        │   → UI (SSE)  → durable URL  │
 │  • lazyriver leg emit    │        │   → staleness watcher        │
 │  buffer: events.jsonl    │◀─ ─ ─  │   → Discord pusher ──▶ phone │
 └──────────────────────────┘ replay └──────────────────────────────┘
        outbound-only                     behind existing ingress
```

### 4.2 Operational Flows
- **Flow A — Campaign progress lands (no agent action).** wavemachine promotes a wave → `state.py.complete()` commits → `emit()` appends `step(promoted)`+`metric` and POSTs → ingest→log→fold → SSE pushes the updated card. The render is a byproduct of the promote.
- **Flow B — Float converges.** A lazyriver leg journals+judges → emits `step(leg,disposition)`+`metric(findings-velocity)` → log→fold → leg gauge + converging indicator update; on sufficiency, `activity_end` moves it to Closed.
- **Flow C — Papered-over concern surfaces.** Engine hits a coded escape hatch → `concern(coded, scope)` → fold adds it to the global queue + a card chip → operator clicks through to the exact log scope.
- **Flow D — Idle stall detected + pushed.** Watcher flags last-event-past-threshold AND not-terminal → sorts to top of Idle lane + outbound Discord alert → operator catches it early.
- **Flow E — Ingest unreachable (resilience).** POST fails → event stays buffered, caller unaffected (R-03) → on recovery the shipper replays in order (R-04). No data loss.

_(Rebuild-from-log integrity is carried as requirement R-09, not narrated as a ConOps flow.)_

---

## 5. Detailed Design

**Design decisions (this walk):** **F-5** → FlightDeck lives in the repo `Wave-Engineering/flightdeck` (Bun/TS) — **CREATED** (private, default branch `main`); the versioned `schema.json` is vendored from `cc` with a CI drift-check. **F-6** → ingest auth is a **bearer token via a Swarm secret** (token-env seam already in `emit.py`/`emit.ts`; TLS-in-transit at the Swarm ingress; upgradeable to mTLS).

### 5.1 Event schema (the contract)
Versioned `schema.json` + typed constants in `cc:src/wave_status/events/`. Kinds: `activity_start · phase · step · metric · concern · blocked_on_human · ci_wait · activity_end`. Scope tags: `{activityId, kind, phase, wave, flight, agent, ts, logRef}`. Concern kinds: `workaround · di-seam · forced-default · gate-override · self-approval · unresolved-todo`. Python emitter + TS service both validate against it (schema, not shared code); additively versioned.

### 5.2 Emit layer
`emit.py` — durable buffer (`~/.claude/status/events.jsonl`) + fire-and-forget shipper, stdlib-only; threaded through the `state.py` mutators (sdlc CLI-shelling handlers covered for free). `sdlc:lib/flightdeck_emit.ts` — mirror for the non-CLI gate/drift/ci-wait/mr handlers. Workflow-runtime tee via `agent()` prompts / a post-node hook (never the script body). Session hook (Stop/SessionEnd). Lazyriver leg parity (sequenced after #852).

### 5.3 Container service (flightdeck repo)
Bun HTTP: authenticated `POST /ingest` → append-only event log (source of truth) → one pure `fold()` → SQLite materialized view; `rebuild()` re-folds the whole log. `metrics.ts` + `eta.ts` derive wall/idle/ci-wait/collision/confidence/drift from the stream; token split stubbed until #853. Campaign ETA = plan burn-down; float ETA = cord-bounded band + converge/explore.

### 5.4 UI
One-anatomy card + grid (default); per-lane card/table switch (Active→cards, Closed/Idle→table); compact vitals row + expandable full metrics; global concern queue with scope links; split-ETA strip; scoped log viewer. SSE live push.

### 5.5 Staleness watcher + Discord push
`watcher.ts` flags idle-but-incomplete (last event past threshold AND not terminal); `push_discord.ts` sends outbound via disc-server. The container becomes the sole pusher; the agent-host regen push path is retired at cutover.

### 5.6 Deploy artifacts (operator deploys)
`Dockerfile` (Bun, non-root, volume for log+SQLite) + `deploy/flightdeck.stack.yml` + `config/flightdeck.env.example` + operator runbook. Artifacts only — no deploy, no Swarm/prod manifest edits.

### 5.A Deliverables Manifest

| ID | Deliverable | Category | Tier | File Path | Produced In | Status | Notes |
|----|-------------|----------|------|-----------|-------------|--------|-------|
| DM-01 | README | Docs | 1 | `flightdeck/README.md` | P2 → P5 | required | Overview, quickstart |
| DM-02 | Unified build system | Code | 1 | `flightdeck/Makefile` | P2 | required | Bun scripts + Makefile; identical CI/terminal cmds |
| DM-03 | CI/CD pipeline | Code | 1 | `flightdeck/.github/workflows/ci.yml` | P2 | required | build/test/container on every PR |
| DM-04 | Automated test suite | Test | 1 | `flightdeck/tests/` + `cc:tests/test_events_*.py` | all phases | required | unit + integration + E2E |
| DM-05 | Test results (JUnit XML) | Test | 1 | `flightdeck/reports/junit.xml` | P2 | required | CI artifact |
| DM-06 | Coverage report | Test | 1 | `flightdeck/reports/coverage.xml` | P2 | required | CI artifact |
| DM-07 | CHANGELOG | Docs | 1 | `flightdeck/CHANGELOG.md` | P5 | required | release-by-release |
| DM-08 | VRTM | Trace | 1 | Dev Spec Appendix V | P5 | required | R-01..26 traceability |
| DM-09 | Operator deploy + usage runbook | Docs | 1 | `flightdeck/docs/operator-runbook.md` | P5 | required | audience-facing |
| DM-10 | Architecture doc | Docs | 2 | `flightdeck/docs/architecture.md` | P2 | required | trigger: >2 interacting components |
| DM-11 | Deployment verification procedures | Docs | 2 | `flightdeck/docs/deploy-verification.md` | P5 | required | trigger: ships deploy artifacts |
| DM-12 | Environment prerequisites doc | Docs | 2 | `flightdeck/docs/environment.md` | P5 | required | trigger: host/platform reqs (Swarm, volume, secret) |
| DM-13 | Manual verification procedures | Test | 2 | `flightdeck/docs/manual-verification.md` | P5 | required | trigger: MV-01..04 in §6.4 |

### 5.B Installation & Deployment
Operator-deployed (PC-1). The pipeline delivers the `Dockerfile` + `deploy/flightdeck.stack.yml` + `config/flightdeck.env.example` + the deploy runbook (DM-09/DM-11/DM-12); the operator applies the stack to the Swarm behind existing ingress, with a volume for the event log + SQLite view and the ingest-token Swarm secret. No Swarm/prod manifest edits, no deploy, in-pipeline.

### 5.N Open Questions
F-5 and F-6 resolved (see §5 decisions). Residual implementation-time details (non-blocking, defaulted, tunable at build): the staleness threshold value, the target Discord channel for stall alerts, and the SQLite view detail (WAL vs. rebuild-on-boot).

Cross-repo routing: the `flightdeck` repo now exists (Wave-Engineering/flightdeck). Per-story work-repo is encoded in phases-waves.json (`repo` field). Issue-placement reconciliation (the 12 fd-stories' + 2 sdlc-stories' tracking issues currently live in claudecode-workflow) is the explicit `/nextwave`-prep step, verified against `state.py` cross-repo resolution.

## 6. Test Plan

### 6.1 Test Strategy
- **Unit** — pure functions, no I/O: the `fold()` reducer, `metrics`/`eta` derivations (campaign burn-down + float cord-band), schema validation, the qualified-key/scope resolvers.
- **Contract** — every event kind validates against the one shared `schema.json` from both `emit.py` and the TS service; a drift test asserts the flightdeck-vendored schema matches the cc version.
- **Integration** — drive each `state.py` CLI subcommand + each sdlc handler → assert exactly one correctly-typed, correctly-scoped event; ingest auth/validation; fold correctness; rebuild==live; shipper buffer+replay; staleness flag+push.
- **E2E** — a full campaign/float event stream flows emitter → ingest → fold → UI; assert card state, convergence, Closed transition, concern surfacing.
- **Manual (MV)** — deploy to a test Swarm node; verify the durable URL, live SSE refresh, concern click-through, and the Discord stall push on a phone.

### 6.2 Integration Tests
- **IT-01** — `state.py` mutator → one typed/scoped event per mutation. [R-01]
- **IT-02** — sdlc gate/drift/ci-wait/mr handler → its emit. [R-01, R-05]
- **IT-03** — ingest: 401 (no token), 202 (valid), 400 (malformed). [R-06, R-07]
- **IT-04** — fold determinism: canned stream → expected card state. [R-08]
- **IT-05** — rebuild==live: drop view, re-fold, assert equal. [R-09]
- **IT-06** — shipper resilience: ingest down → buffer retains → recovery → ordered replay. [R-03, R-04]
- **IT-07** — staleness watcher → flag + push (mock disc-server). [R-22, R-23]
- **IT-08** — schema drift: vendored flightdeck `schema.json` == cc version. [R-19, TC-4]
- **IT-09** — happy-path POST: with `FLIGHTDECK_INGEST_URL` set, a buffered event is POSTed non-blocking. [R-02]

### 6.3 End-to-End Tests
- **E2E-01** — full campaign stream → UI card renders correct waves/ETA/metrics. [R-10, R-12, R-16, R-17]
- **E2E-02** — float stream → leg gauge + converge/explore indicator; Closed on sufficiency. [R-10, R-18]
- **E2E-03** — concern event → global queue + card chip + scope link resolves to the right log. [R-15, R-20, R-21]

### 6.4 Manual Verification Procedures
- **MV-01** — deploy the container to a test Swarm node; durable URL loads; SSE live-refresh on a running activity. [R-11]
- **MV-02** — trigger idle-but-incomplete; the Discord stall push arrives on a phone. [R-23]
- **MV-03** — concern-queue click-through opens the correct scoped log. [R-15, R-20]
- **MV-04** — per-lane card/table toggle + vitals expand behave as designed. [R-13, R-14]

---

## 7. Definition of Done

### 7.1 Global DoD
- [ ] R-01..R-26 implemented and traced in the VRTM (App. V).
- [ ] Event log is the single source of truth; view is a pure, rebuildable fold (IT-05 green). [R-09]
- [ ] Campaign and float render from one identical anatomy (E2E-01/02). [R-10]
- [ ] Emit is fire-and-forget with ordered replay; no hot-path failure (IT-06). [R-03, R-04]
- [ ] Ingest auth + schema validation enforced (IT-03). [R-06, R-07]
- [ ] Split ETA + honest token stub until #853 (IT-08). [R-17, R-19]
- [ ] Global concern queue with scope links (E2E-03). [R-20]
- [ ] Idle-stall flag + outbound Discord push (IT-07, MV-02). [R-22, R-23]
- [ ] All four legacy renderers deleted; FlightDeck is the single surface. [R-24, PC-5]
- [ ] Deploy artifacts delivered; no Swarm/prod manifest edits; no deploy. [R-25, R-26, PC-1]
- [ ] All Deliverables Manifest rows produced (DM-01..DM-13).
- [ ] Unit/IT/E2E green; MV-01..04 executed.
- [ ] Kahuna→main MR merged clean; VRTM complete.

### 7.2 Dev Spec Finalization Checklist
_(mechanical — verified by `devspec_finalize`)_
- [ ] Every section (1–9) present and non-placeholder.
- [ ] Every requirement (R-01..R-26) in EARS form.
- [ ] Every Story in §8 has a `depends_on` (possibly `[]`).
- [ ] Every Deliverables Manifest row has a Produced-In phase or wave.
- [ ] VRTM present (App. V) covering all requirements.
- [ ] Test Plan traces each requirement (IT/E2E/MV).
- [ ] Approval block present after `/devspec approve`.

---

## 8. Phased Implementation Plan

> Source decomposition: `~/tmp/flightdeck-plan.md`. Repos: **cc** = claudecode-workflow, **sdlc** = mcp-server-sdlc, **fd** = the new `flightdeck` repo. `/devspec upshift` creates one Story issue per Story below.

### Phase 0: Shared contract & scaffolding
#### Phase 0 DoD
- Event schema validates every event kind; #853 linked as the token gate.

#### Story 0.1: Shared event JSON Schema + typed constants (#860)

**Wave:** P0W1 · **Dependencies:** None

Author the versioned event schema + typed constants in `cc:src/wave_status/events/schema.json` + `__init__.py`. Kinds: `activity_start|phase|step|metric|concern|blocked_on_human|ci_wait|activity_end`; scope tags `{activityId,kind,phase,wave,flight,agent,ts,logRef}`; concern kinds. Each `state.py` action maps to a kind.

**Implementation Steps:**

1. Create `cc:src/wave_status/events/schema.json` defining the 8 event kinds, the scope-tag object (`{activityId,kind,phase,wave,flight,agent,ts,logRef}`), and the 6 concern kinds (`workaround|di-seam|forced-default|gate-override|self-approval|unresolved-todo`).
2. Create `cc:src/wave_status/events/__init__.py` exporting typed Python constants mirroring the schema.
3. Map each `state.py` action to an event kind in a lookup table consumed by Story 1.2.

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_event_schema_validates_all_kinds` | Every kind's sample payload validates; every action maps to a kind | `cc:tests/test_event_schema.py` |

**Acceptance Criteria:**

- [ ] `schema.json` defines all 8 event kinds, scope tags, and 6 concern kinds [TC-4]
- [ ] Typed constants exported and match the schema; `test_event_schema.py` green [R-01]

---

#### Story 0.2: Link the #853 self-instrumentation prerequisite (#859)

**Wave:** P0W1 · **Dependencies:** None

Tracking-only: link #853 (per-Workflow-node token usage) as the token-metric gate referenced by Stories 1.6/2.3/3.4. No code.

**Implementation Steps:**

1. Confirm issue #853 is filed and open in `claudecode-workflow`.
2. Record #853 as the token-metric gate in the schema module's notes, referenced by Stories 1.6/2.3/3.4.

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `n/a (tracking)` | Confirms #853 is filed and linked as the token gate | N/A |

**Acceptance Criteria:**

- [ ] #853 confirmed filed and recorded as the token-metric gate [NG-4]
- [ ] Token cells in Stories 1.6/2.3/3.4 stub until #853 lands [TC-7]

---

### Phase 1: Emit layer
#### Phase 1 DoD
- Every deterministic state change emits a typed, scoped event to the durable buffer and ships fire-and-forget; no agent in the reporting path.

#### Story 1.1: emit() + durable buffer + shipper (#863)

**Wave:** P1W1 · **Dependencies:** 0.1

NEW `cc:src/wave_status/events/emit.py` (stdlib-only): validate against the S0.1 schema; atomic-append to `~/.claude/status/events.jsonl`; non-blocking POST to `$FLIGHTDECK_INGEST_URL` with bearer-token auth; replay unsent buffered lines on recovery. DI-seam: URL unset ⇒ buffer-only, never raises.

**Implementation Steps:**

1. Create `cc:src/wave_status/events/emit.py` validating each payload against the S0.1 schema before it is buffered.
2. Implement atomic-append to `~/.claude/status/events.jsonl` and a non-blocking POST to `$FLIGHTDECK_INGEST_URL` with bearer-token auth.
3. Implement the DI-seam: `FLIGHTDECK_INGEST_URL` unset ⇒ buffer-only, never raises to the caller.
4. Implement offset-marker replay of unsent buffered lines when the shipper reconnects.

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_emit_atomic_append` | Durable/atomic append to the buffer file | `cc:tests/test_events_emit.py` |
| `test_emit_replay_resends` | Replay resends unsent buffered lines in order on recovery | `cc:tests/test_events_emit.py` |
| `test_emit_post_nonblocking_when_url_set` (IT-09) | Happy-path POST: with `FLIGHTDECK_INGEST_URL` set, a buffered event is POSTed non-blocking | `cc:tests/test_events_emit.py` |

**Acceptance Criteria:**

- [ ] Buffered append is durable and atomic; unset URL is buffer-only and never raises [R-01, R-02]
- [ ] Ship failure never raises to the caller [R-03]
- [ ] Unsent events replay in order on recovery [R-04]

---

#### Story 1.2: Thread emit into every state.py mutator (#855)

**Wave:** P1W1 · **Dependencies:** 1.1, 0.1

Add `emit()` in `cc:src/wave_status/state.py` mutators (`_set_action`, `planning`, `flight`, `flight_done`, `complete`, `close_issue`, `record_mr`, `append_trajectory`, `init_state`, `set_current_wave`, `wavemachine_start/stop`) with the action→kind mapping. sdlc CLI-shelling handlers are covered for free.

**Implementation Steps:**

1. Add `emit()` calls to every listed `state.py` mutator using the Story 0.1 action→kind mapping.
2. Confirm sdlc CLI-shelling handlers inherit emit coverage for free (no sdlc-side change needed for these paths).

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_state_emit_one_event_per_mutation` | Exactly one correctly-typed/scoped event per mutation (IT-01) | `cc:tests/test_state_emit_integration.py` |

**Acceptance Criteria:**

- [ ] Every listed mutator emits exactly one correctly-typed/scoped event [R-01]
- [ ] `test_state_emit_integration.py` green (IT-01) [R-01]

---

#### Story 1.3: Coded-concern emit at coded escape hatches (#861)

**Wave:** P1W1 · **Dependencies:** 1.1

Emit `concern{source:'coded'}` at the coded escape hatches: ENG-2 forced `chore/` default, ENG-1 gate-skip-but-advance, ENG-6 self-approved MR, ENG-8 kahuna pre-sync (some hatches live in sdlc/nextwave — co-deliver those with S1.5).

**Implementation Steps:**

1. Emit `concern{source:'coded'}` at the ENG-2, ENG-1, ENG-6, and ENG-8 hatch sites reachable from `state.py`.
2. Co-deliver the sdlc/nextwave-side hatches (where the hatch itself lives outside `state.py`) alongside Story 1.5.

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_concern_emit_per_hatch` | Each coded hatch emits a `concern{source:'coded'}` event (IT-02) | `cc:tests/test_events_emit.py` |

**Acceptance Criteria:**

- [ ] All four coded hatches (ENG-1, ENG-2, ENG-6, ENG-8) emit a coded concern [R-05]
- [ ] sdlc/nextwave-side hatches co-delivered with Story 1.5 [R-05]

---

#### Story 1.4: TS emit helper (#862)

**Wave:** P1W2 · **Dependencies:** 0.1

NEW `sdlc:lib/flightdeck_emit.ts` mirroring emit.py (buffer + fire-and-forget POST + bearer auth), consuming the SAME S0.1 schema.

**Implementation Steps:**

1. Create `sdlc:lib/flightdeck_emit.ts` mirroring `emit.py`'s buffer + fire-and-forget POST + bearer-token auth.
2. Validate every emitted payload against the same S0.1 `schema.json` (vendored, not reimplemented).
3. Implement the same unset-URL DI-seam as the Python emitter (buffer-only, never throws).

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_flightdeck_emit_validates_schema` | TS emit validates against the shared S0.1 schema | `sdlc:tests/flightdeck_emit.test.ts` |

**Acceptance Criteria:**

- [ ] TS emit helper mirrors `emit.py`'s buffer + fire-and-forget behavior [TC-4]
- [ ] Validates against the shared schema; test green [R-01, R-02]

---

#### Story 1.5: Wire emit into non-CLI sdlc handlers (#865)

**Wave:** P1W2 · **Dependencies:** 1.4, 0.1

Wire emit into the `sdlc:handlers/` that do NOT go through the wave-status CLI: `commutativity_verify`, `drift_*`, `ci_wait_run`/`pr_wait_ci`, `pr_merge`, `wave_ci_trust_level`, `wave_finalize`. Emit `metric`(collision/drift/confidence), `ci_wait`, `step`(gate/promote), `concern`(gate-override/self-approval).

**Implementation Steps:**

1. Wire `flightdeck_emit.ts` into `commutativity_verify`, `drift_*`, `ci_wait_run`/`pr_wait_ci`, `pr_merge`, `wave_ci_trust_level`, and `wave_finalize`.
2. Emit `metric`(collision/drift/confidence), `ci_wait`, `step`(gate/promote), and `concern`(gate-override/self-approval) from the correct handler.

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_handler_emit_per_handler` | Each listed handler emits its correct kind (IT-02) | `sdlc:tests/handler_emit.test.ts` |

**Acceptance Criteria:**

- [ ] Each of the six handlers emits on its trigger path [R-05]
- [ ] `handler_emit.test.ts` green (IT-02) [R-05]

---

#### Story 1.6: Workflow-runtime tee (#856)

**Wave:** P1W3 · **Dependencies:** 1.1, 0.2

In `cc:skills/nextwave/per-wave-workflow.js`, emit `phase`/`step` + `metric`(latency) at each `agent()` node boundary via the emit CLI. Constraint: no fs/`Date` in the Workflow script — emit from `agent()` prompts / a post-node hook, not the script body. Token metric is a STUB, gated on #853.

**Implementation Steps:**

1. At each `agent()` node boundary in `cc:skills/nextwave/per-wave-workflow.js`, emit `phase`/`step` + `metric`(latency) via the emit CLI.
2. Emit only from `agent()` prompts or a post-node hook — never from the Workflow script body (no fs/`Date`/`Math.random` in-script).
3. Seam the token-usage field absent (explicit stub) until #853 lands.

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_workflow_tee_phase_step_per_node` | Phase/step emitted per node boundary; token field seamed-absent pre-#853 | `cc:skills/nextwave/` skill-test |

**Acceptance Criteria:**

- [ ] Phase/step/latency emitted at each `agent()` node boundary [R-01]
- [ ] No fs/Date/Math.random introduced into the Workflow script body [TC-2]
- [ ] Token metric renders as an explicit stub, not fabricated, pending #853 [R-19]

---

#### Story 1.7: Session hook (#857)

**Wave:** P1W3 · **Dependencies:** 1.1

Stop/SessionEnd hook in `cc:config/settings.template.json` + NEW `cc:scripts/flightdeck-session-emit.sh` emitting session open/idle/close.

**Implementation Steps:**

1. Add a Stop/SessionEnd hook entry in `cc:config/settings.template.json`.
2. Create `cc:scripts/flightdeck-session-emit.sh` emitting session open/idle/close events via the emit CLI.

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_session_hook_emit` | Session open/idle/close events emitted on hook fire | `cc:tests/test_session_hook_emit` |

**Acceptance Criteria:**

- [ ] Stop/SessionEnd hook wired in `settings.template.json` [R-01]
- [ ] `flightdeck-session-emit.sh` emits open/idle/close; test green [R-01]

---

#### Story 1.8: lazyriver leg-agent emit parity (#858)

**Wave:** P1W3 · **Dependencies:** 1.1, 0.1

In `cc:skills/lazyriver/river.js` `legPrompt`, append "-then-emit" so each leg emits `step`(leg≈wave), `concern`(declared, on DI-seam), and `metric`(findings-velocity); add the same to nextwave prompts for declared concerns. Sequence AFTER #852 (or co-deliver on the lazyriver bundle).

**Implementation Steps:**

1. In `cc:skills/lazyriver/river.js` `legPrompt`, append a "-then-emit" instruction so each leg emits `step`(leg≈wave), `concern`(declared), and `metric`(findings-velocity).
2. Add the same declared-concern emit instruction to the nextwave prompts.
3. Sequence delivery after #852 lands (or co-deliver on the lazyriver bundle).

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_lazyriver_leg_emits_step` | A lazyriver leg emits a `step` event | `cc:skills/lazyriver/` skill-test |

**Acceptance Criteria:**

- [ ] Each leg emits `step`(leg≈wave) + `concern`(declared) + `metric`(findings-velocity) [R-01, R-05]
- [ ] Delivery sequenced after #852 lands; float rendering (P3) consumes its progress emit [NG-5]

---

### Phase 2: FlightDeck container service (fd)
#### Phase 2 DoD
- Authenticated ingest → append-only log (single source of truth) → pure fold → SQLite view, fully rebuildable (ENG-7 class impossible).

#### Story 2.1: Service scaffold + authenticated ingest (#872)

**Wave:** P2W1 · **Dependencies:** 0.1

NEW `fd:src/server.ts` (Bun HTTP): `POST /ingest` with bearer-token auth (Swarm secret), validates against S0.1, appends to the log.

**Implementation Steps:**

1. Create `fd:src/server.ts` (Bun HTTP) exposing `POST /ingest`.
2. Enforce bearer-token auth (Swarm secret, F-6) before touching the body.
3. Validate the payload against the S0.1 schema; append to the append-only log on success.

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_ingest_401_unauth` | No/invalid token → 401, not persisted (IT-03) | `fd:tests/ingest.test.ts` |
| `test_ingest_400_malformed` | Schema-invalid event → 400, not persisted (IT-03) | `fd:tests/ingest.test.ts` |

**Acceptance Criteria:**

- [ ] Unauthenticated request rejected 401, not persisted [R-06]
- [ ] Schema-invalid request rejected 400, not persisted [R-07]
- [ ] Valid authenticated request persists (202) [R-08]

---

#### Story 2.2: Event-sourced store + fold + rebuild (#866)

**Wave:** P2W1 · **Dependencies:** 2.1, 0.1

NEW `fd:src/store.ts` + `fold.ts`: append-only JSONL log = source of truth; SQLite materialized view; `fold()` is the ONE pure reducer; `rebuild()` re-folds the whole log.

**Implementation Steps:**

1. Create `fd:src/store.ts` implementing the append-only JSONL log as the source of truth.
2. Create `fd:src/fold.ts` with `fold()` as the ONE pure reducer computing the materialized SQLite view.
3. Implement `rebuild()` to re-fold the whole log.

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_fold_deterministic` | Canned event stream → expected card state (IT-04) | `fd:tests/fold.test.ts` |
| `test_rebuild_equals_live` | Dropped view rebuilt from the log equals the live view (IT-05) | `fd:tests/rebuild.test.ts` |

**Acceptance Criteria:**

- [ ] `fold()` is the single reducer computing view state [R-08]
- [ ] `rebuild()` reproduces identical view state from the log [R-09]

---

#### Story 2.3: Metrics + split-ETA derivation (#869)

**Wave:** P2W1 · **Dependencies:** 2.2, 0.2

NEW `fd:src/metrics.ts` + `eta.ts`: derive wall/idle/ci-wait/collision/confidence/drift from timestamps; split machine vs blocked-on-you ETA; campaign burn-down; float cord-bounded band + converge/explore. Token split reads the stub (blank until #853).

**Implementation Steps:**

1. Create `fd:src/metrics.ts` deriving wall/idle/ci-wait/collision/confidence/drift from event timestamps.
2. Create `fd:src/eta.ts` splitting machine-time from blocked-on-you; campaign = plan burn-down, float = cord-bounded band + converge/explore indicator.
3. Read the token-split metric as the stub (blank) until #853 lands — never fabricate a value.

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_eta_campaign_narrows` | Campaign ETA narrows as steps land (E2E-01) | `fd:tests/eta.test.ts` |
| `test_schema_drift_vendored` | Vendored flightdeck schema.json == cc version (IT-08) | `fd:tests/eta.test.ts` |

**Acceptance Criteria:**

- [ ] Wall/idle/ci-wait/collision/confidence/drift derived from the stream [R-16]
- [ ] Split ETA (machine vs blocked-on-you); campaign burn-down / float band [R-17, R-18]
- [ ] Token metric renders as an explicit stub, not fabricated, pending #853 [R-19]

---

### Phase 3: UI (fd)
#### Phase 3 DoD
- Campaign ≡ float from one card anatomy; global concern queue; per-lane switch; vitals/expand; split-ETA; scoped log viewer; SSE live.

#### Story 3.1: One-anatomy card + card grid (default view) (#868)

**Wave:** P3W1 · **Dependencies:** 2.2, 2.3

NEW `fd:src/ui/card.ts` + `grid.ts`: single card component; campaign/float differ only in the estimator label; card grid is the default view. SSE live push.

**Implementation Steps:**

1. Create `fd:src/ui/card.ts`: a single card component where campaign/float differ only in the estimator label.
2. Create `fd:src/ui/grid.ts`: card grid as the default multi-activity view.
3. Wire SSE live push so card state updates without a manual refresh.
4. Card renders a compact **vitals row** when collapsed and expands to the full metrics grid on interaction (per-lane default: Active expanded, Closed/Idle collapsed).

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_ui_card_one_anatomy` | One card component renders both campaign and float kinds (E2E-01, E2E-02) | `fd:tests/ui_card.test.ts` |

**Acceptance Criteria:**

- [ ] Campaign and float render from one identical card anatomy [R-10]
- [ ] Console reachable at a durable URL with live SSE push [R-11]
- [ ] Multiple active activities present as a card grid by default [R-12]
- [ ] Collapsed card shows the compact vitals row; expanding reveals the full metrics grid [R-14]

---

#### Story 3.2: Dense one-line table toggle (per-lane) (#864)

**Wave:** P3W1 · **Dependencies:** 3.1

NEW `fd:src/ui/table.ts` + a per-lane toggle (Active→cards, Closed/Idle→table by default).

**Implementation Steps:**

1. Create `fd:src/ui/table.ts`: a dense one-line-per-activity table view.
2. Add a per-lane toggle (Active→cards, Closed/Idle→table by default) switching independently per lane.

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_table_n_activities_n_rows` | N activities render N table rows (MV-04) | `fd:tests/ui_table.test.ts` |

**Acceptance Criteria:**

- [ ] Each lane switches between card/table layout independently [R-13]
- [ ] Closed/Idle default to table, Active defaults to cards [R-13]

---

#### Story 3.3: Global concern queue (#867)

**Wave:** P3W1 · **Dependencies:** 2.2

NEW `fd:src/ui/concern_queue.ts`: fold all `concern` events into a GLOBAL queue; each links to its exact Phase/Wave/Flight/Leg scope; stalled-with-open-concerns sorts to top.

**Implementation Steps:**

1. Create `fd:src/ui/concern_queue.ts` folding all `concern` events into one GLOBAL queue.
2. Link each queue entry to its exact Phase/Wave/Flight/Leg scope.
3. Sort stalled activities with open concerns to the top of the deck.

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_concern_queue_ordering_links` | Queue ordering + scope links resolve correctly (E2E-03) | `fd:tests/concern_queue.test.ts` |

**Acceptance Criteria:**

- [ ] All concern events aggregate into one global queue with scope links [R-20]
- [ ] Stalled activities with open concerns sort to the top [R-21]

---

#### Story 3.4: Split-ETA strip (#871)

**Wave:** P3W1 · **Dependencies:** 2.3, 3.1

NEW `fd:src/ui/eta_strip.ts`: headline machine-time next to a separate live blocked-on-you counter.

**Implementation Steps:**

1. Create `fd:src/ui/eta_strip.ts` rendering headline machine-time next to a separate live blocked-on-you counter.
2. Wire the strip to the Story 2.3 `eta.ts` output, keeping the two figures structurally independent.

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_eta_strip_two_figures` | Machine-time and blocked-on-you render as two independent figures | `fd:tests/ui_eta_strip.test.ts` |

**Acceptance Criteria:**

- [ ] ETA presented as two independent figures (machine-time, blocked-on-you) [R-17]

---

#### Story 3.5: Scoped log viewer (#870)

**Wave:** P3W1 · **Dependencies:** 2.2

NEW `fd:src/ui/log_viewer.ts`: resolve `logRef` + filter by scope tag (Phase/Wave/Flight/Leg).

**Implementation Steps:**

1. Create `fd:src/ui/log_viewer.ts` resolving `logRef` from an event's scope tag.
2. Filter the transcript view by the operator-selected scope (Phase/Wave/Flight/Leg).

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_log_viewer_filter_narrows` | Selecting a scope narrows the transcript to that scope (MV-03, E2E-03) | `fd:tests/log_viewer.test.ts` |

**Acceptance Criteria:**

- [ ] Selecting a log scope filters the transcript to that scope [R-15]

---

### Phase 4: Staleness watcher + Discord push (fd)
#### Phase 4 DoD
- Idle-but-incomplete flagged and pushed outbound from the container.

#### Story 4.1: Staleness watcher (#873)

**Wave:** P4W1 · **Dependencies:** 2.2

NEW `fd:src/watcher.ts`: flag when the last event is older than the threshold AND terminal state is not reached.

**Implementation Steps:**

1. Create `fd:src/watcher.ts` computing "last event older than threshold" AND "terminal state not reached".
2. Flag matching activities as idle-but-incomplete for the UI/push consumers.

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_watcher_fires_on_stale` | Watcher fires when stale + non-terminal; silent on fresh/terminal (IT-07) | `fd:tests/watcher.test.ts` |

**Acceptance Criteria:**

- [ ] Idle-but-incomplete flagged when last event exceeds the staleness threshold and terminal state isn't reached [R-22]

---

#### Story 4.2: Discord push (#874)

**Wave:** P4W1 · **Dependencies:** 4.1

NEW `fd:src/push_discord.ts`: outbound push via disc-server on a stale flag (the container becomes the sole pusher; the agent-host regen push path is retired in S5.2).

**Implementation Steps:**

1. Create `fd:src/push_discord.ts` composing and dispatching an outbound alert via disc-server on a stale flag.
2. Confirm the container is the sole pusher (the agent-host regen push path is retired in Story 5.2).

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_push_discord_on_stale_flag` | Push composed + dispatched on a stale flag (mock disc-server) (IT-07, MV-02) | `fd:tests/push_discord.test.ts` |

**Acceptance Criteria:**

- [ ] Stale flag triggers an outbound Discord push via disc-server [R-23]
- [ ] Push arrives on a phone (MV-02 evidence) [R-23]

---

### Phase 5: Cutover + deploy deliverables
#### Phase 5 DoD
- All four stale renderers deleted; FlightDeck the single surface; Dockerfile + Swarm stack delivered (no deploy).

#### Story 5.1: Delete generate-status-panel + refs (#877)

**Wave:** P5W1 · **Dependencies:** 3.1, 4.2

Delete `cc:scripts/generate-status-panel` + remove refs (`install-remote.sh`, `skills/wavemachine/SKILL.md`). Gated on FlightDeck live (operator-confirmed).

**Implementation Steps:**

1. Confirm FlightDeck is live (operator-confirmed) before deleting.
2. Delete `cc:scripts/generate-status-panel` and remove references in `install-remote.sh` and `skills/wavemachine/SKILL.md`.

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_validate_green_no_refs` | `validate.sh` passes; zero live references to the deleted script | `cc:scripts/ci/validate.sh` |

**Acceptance Criteria:**

- [ ] `generate-status-panel` deleted, gated on FlightDeck live [R-24]
- [ ] Zero references remain in `install-remote.sh` / `wavemachine/SKILL.md` [R-24]

---

#### Story 5.2: Delete dashboards + strip regen (#875)

**Wave:** P5W1 · **Dependencies:** 5.1

Delete `cc:src/wave_status/dashboard/*` + `campaign_status/dashboard/*`; strip `_regenerate_dashboard`/`_safe_regenerate_dashboard` + dashboard imports + the `discord-status-post` call from both `__main__.py`. Mutators keep persisting state.json + now emit; no HTML regen.

**Implementation Steps:**

1. Delete `cc:src/wave_status/dashboard/*` and `cc:src/campaign_status/dashboard/*`.
2. Strip `_regenerate_dashboard`/`_safe_regenerate_dashboard`, dashboard imports, and the `discord-status-post` call from both `__main__.py` files.

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_cli_subcommand_ok_and_emits` | Each CLI subcommand still prints `{ok}` and emits, with no regen call | `cc:tests/test.sh` |

**Acceptance Criteria:**

- [ ] Both dashboard directories deleted; regen helpers + discord-status-post call stripped [R-24]
- [ ] `test.sh` green; every CLI subcommand still prints `{ok}` and emits [R-24]

---

#### Story 5.3: Retire scripts/wave-watcher (#876)

**Wave:** P5W1 · **Dependencies:** 5.1

Delete `cc:scripts/wave-watcher/*` (the 4th stale view) once FlightDeck's SSE is live.

**Implementation Steps:**

1. Confirm FlightDeck's SSE is live (its prior-art already harvested into Stories 2.1/4.2).
2. Delete `cc:scripts/wave-watcher/*`.

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_install_uninstall_validate_without_watcher` | install/uninstall + validate green without wave-watcher | `cc:scripts/ci/validate.sh` |

**Acceptance Criteria:**

- [ ] `scripts/wave-watcher/*` deleted once FlightDeck SSE is live [R-24, PC-5]
- [ ] install/uninstall + validate remain green [R-24]

---

#### Story 5.4: Dockerfile (#878)

**Wave:** P5W2 · **Dependencies:** 2.2, 3.1, 4.1

NEW `fd:Dockerfile` (Bun, non-root, persistent volume for the event log + SQLite).

**Implementation Steps:**

1. Author `fd:Dockerfile` on a Bun base image, running as non-root.
2. Declare a persistent volume for the event log + SQLite view.
3. Add a CI job building the image (build only, no push/deploy).

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_docker_build_green` | `docker build` succeeds in CI (build only) | `fd:.github/workflows/ci.yml` |

**Acceptance Criteria:**

- [ ] Image builds non-root with a persistent log+SQLite volume [R-25]
- [ ] CI build-only job green; no deploy step present [R-25, R-26]

---

#### Story 5.5: Swarm stack/compose + config + runbook (#879)

**Wave:** P5W2 · **Dependencies:** 5.4

NEW `fd:deploy/flightdeck.stack.yml` + `fd:config/flightdeck.env.example` + operator runbook — service behind the existing Swarm ingress, volume for log+db, ingest-token secret.

**Implementation Steps:**

1. Author `fd:deploy/flightdeck.stack.yml` placing the service behind the existing Swarm ingress, with a volume for log+db and an ingest-token secret reference.
2. Author `fd:config/flightdeck.env.example` and the operator deploy runbook (DM-09/DM-11/DM-12).
3. Validate the stack file with `docker stack config` / compose-lint in isolation — no apply, no existing Swarm/prod manifest edits.

**Test Procedures:**

| Test Name | Purpose | File Location |
|---|---|---|
| `test_stack_config_lint_isolated` | `docker stack config`/compose-lint validates in isolation (no apply) | `fd:deploy/flightdeck.stack.yml` |

**Acceptance Criteria:**

- [ ] Stack/compose + config + runbook delivered; operator deploys [R-25]
- [ ] No existing Swarm/prod manifest edits; no deploy performed by the pipeline [R-26]

---

## 9. Appendices

### Appendix V — VRTM (skeleton)

| Req | Implemented by (Story) | Verified by (Test) | Status |
|-----|------------------------|--------------------|--------|
| R-01 | 1.1, 1.2 | IT-01 | ☐ |
| R-02 | 1.1 | IT-09 | ☐ |
| R-03 | 1.1 | IT-06 | ☐ |
| R-04 | 1.1 | IT-06 | ☐ |
| R-05 | 1.3, 1.5 | IT-02 | ☐ |
| R-06 | 2.1 | IT-03 | ☐ |
| R-07 | 2.1 | IT-03 | ☐ |
| R-08 | 2.1, 2.2 | IT-04 | ☐ |
| R-09 | 2.2 | IT-05 | ☐ |
| R-10 | 3.1 | E2E-01, E2E-02 | ☐ |
| R-11 | 3.1 | MV-01 | ☐ |
| R-12 | 3.1 | E2E-01 | ☐ |
| R-13 | 3.2 | MV-04 | ☐ |
| R-14 | 3.1 | MV-04 | ☐ |
| R-15 | 3.5 | MV-03, E2E-03 | ☐ |
| R-16 | 2.3 | E2E-01 | ☐ |
| R-17 | 2.3, 3.4 | E2E-01 | ☐ |
| R-18 | 2.3 | E2E-02 | ☐ |
| R-19 | 2.3 | IT-08 | ☐ |
| R-20 | 3.3 | E2E-03 | ☐ |
| R-21 | 3.3 | E2E-03 | ☐ |
| R-22 | 4.1 | IT-07 | ☐ |
| R-23 | 4.2 | IT-07, MV-02 | ☐ |
| R-24 | 5.1, 5.2, 5.3 | cutover verify | ☐ |
| R-25 | 5.4, 5.5 | stack-config lint | ☐ |
| R-26 | 5.5 | review | ☐ |
