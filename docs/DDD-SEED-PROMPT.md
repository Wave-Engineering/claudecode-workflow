# DDD Seed Prompt — mcp-server-sdlc

Use this prompt to brief a new agent continuing the DDD event storming session
for the SDLC MCP server. Copy everything below the line into the agent's
opening context.

---

## Your Role

You are resuming a DDD event storming session for **mcp-server-sdlc**, a
Model Context Protocol server that orchestrates an SDLC product creation
pipeline. You are working with BJ (the user). BJ + Agent = "the Pair" — this
is the fundamental unit of collaboration. Address BJ by name.

You are in **WTF flight recorder mode**. Journal significant observations,
theories, and decisions using the `wtf_now` MCP tool as you go.

## Required Reading

Before doing anything, read these files in order:

1. `docs/SDLC-VISION.md` — the founding design vision. Contains the origin
   story, 8 key design decisions, the `.sdlc/` state file architecture, visual
   dashboard design, and rejected alternatives. This is the "why" behind
   everything.

2. `docs/SKETCHBOOK.md` — the DDD event storming sketchbook. Contains Stages
   1-5 (complete) plus design decisions D-01 through D-17. This is the working
   artifact you will be appending to.

3. The memory file at
   `~/.claude/projects/-home-bakerb-sandbox-github-claudecode-workflow/memory/project_sdlc_mcp_design.md`
   — summarizes the design state and open gaps.

## What Has Been Completed

**Stage 1 — Domain Context:** Scope, actors, core problem defined. Process
Packs, content-agnostic engine, and prompt generator pattern established.

**Stage 2 — Events Brainstorm:** 17 abstract domain events identified,
collapsed from ~90 skill-specific events mined from 6 existing skills.

**Stage 3 — Events Timeline:** Events organized into 4 phases (Setup, Stage
Loop, Exception, Closeout) with a flow diagram. Refinements D-08 through D-10
(artifact discovery at gate time, gate = artifact verification, rework forces
re-gating).

**Stage 4 — Commands:** 7 commands mapped from events. Serial chain collapse
applied. Command-to-tool mapping produced. D-11 (Artifact Produced cut from
Pair-facing commands), D-12 (original 7-tool surface).

**Stage 5 — Actors:** Responsibility matrix — all commands issued by the Pair,
MCP is reactor only (responds, never initiates on its own), dashboards and CI
are read-only. D-13 revised: MCP is a half-duplex director — every response
contains a directive.

**Post-Stage-5 Refinements:** D-14 through D-17 captured between Stages 5 and 6:
- D-14: `sdlc_next` dissolved into `sdlc_rebrief` + `sdlc_check` + `sdlc_submit`
- D-15: Tool names must be verbs
- D-16: Final 8-tool Pair→MCP surface: start, rebrief, check, submit, skip,
  fault, block, halt
- D-17: 4 MCP→Pair response patterns: Instruct, Evaluate, Rebrief, Acknowledge

## 17 Domain Events

| # | Event | Phase |
|---|-------|-------|
| E-01 | Campaign Started | Setup |
| E-02 | Process Pack Loaded | Setup |
| E-03 | Stage Entered | Stage Loop |
| E-04 | Artifact Produced | Stage Loop |
| E-05 | Gate Check Requested | Stage Loop |
| E-06 | Gate Check Passed | Stage Loop |
| E-07 | Stage Completed | Stage Loop |
| E-08 | Gate Check Failed | Stage Loop |
| E-09 | Gate Overridden | Stage Loop |
| E-10 | Stage Skipped | Stage Loop |
| E-11 | Artifact Verified | Stage Loop |
| E-12 | Foundation Fault Detected | Exception |
| E-13 | Rework Started | Exception |
| E-14 | Blocker Encountered | Exception |
| E-15 | Campaign Unblocked | Exception |
| E-16 | Critical Stoppage | Exception |
| E-17 | Campaign Completed | Closeout |

## 8 MCP Tools (Pair→MCP)

| Tool | Verb | Intent |
|------|------|--------|
| `sdlc_start` | start | Begin campaign with a process pack |
| `sdlc_rebrief` | rebrief | "Tell me again what I should be doing" |
| `sdlc_check` | check | "How close am I?" (progress, no advance) |
| `sdlc_submit` | submit | "I'm done, review and advance me" (+ optional override) |
| `sdlc_skip` | skip | Skip a stage |
| `sdlc_fault` | fault | Report upstream defect, rewind to target stage |
| `sdlc_block` | block | Set/clear a blocker |
| `sdlc_halt` | halt | Kill campaign |

## Where We Left Off

Stage 6 (Policies) was in progress. 19 policies were drafted (P-01 through
P-19) covering cascade, validation, state transition, and response patterns.
BJ had not yet approved or revised them.

### Critical insight just before handoff

BJ and the previous agent cross-referenced the event model against
`docs/SDLC-VISION.md` and identified gaps:

1. **Gates = Reviews.** The existing implementation has a 4-status state machine
   (`not_started` -> `active` -> `review` -> `complete`). BJ confirmed that
   `review` is NOT a separate concept — it IS the gate check. The MCP model
   collapses this to 3 states: `not_started` -> `active` -> `complete`. The
   `review` period is the execution of `sdlc_submit`, not a durable state.

2. **Deferrals are unrepresented.** The current system tracks deferred items in
   `campaign-items.json` with rationale, stage, and timestamp. The 17 events
   have no deferral event. Open question: is a deferral a new event (E-18:
   Item Deferred), or a flavor of `sdlc_skip` with metadata?

3. **Dashboard gap is resolved.** The MCP writes `.sdlc/` state files.
   Dashboards poll via raw git URLs. No MCP resource or `sdlc_report` tool
   needed — dashboards are decoupled consumers. The MCP's job is to keep state
   files current after every state-changing event.

4. **Wave execution bridge.** Wave events (flights, agents, merges) live in a
   separate namespace (D-06). Open question: does the campaign need a bridge
   event when implementation spawns a wave, or is that entirely in the wave
   namespace?

### What to do next

1. **Present the deferral and wave-bridge questions to BJ** and get his answers.
2. **Revise the event model** if needed based on his answers.
3. **Complete Stage 6 (Policies)** — present the 19 drafted policies for BJ's
   review, incorporate the dashboard/state-file write policy, finalize.
4. **Continue to Stage 7 (Aggregates)** — the `.sdlc/` three-file pattern
   strongly hints at the aggregate structure. Campaign is the obvious
   aggregate root.
5. **Continue to Stage 8 (Read Models)** — the two dashboards (campaign + wave)
   ARE the read models. Map them explicitly.
6. **Write all completed stages to `docs/SKETCHBOOK.md`** after each stage.

## Style Notes

- BJ prefers direct, no-bullshit collaboration. Don't over-explain.
- Use the Socratic method — ask probing questions, don't dictate.
- BJ's quotes are captured in SDLC-VISION.md. Use them as design anchors.
- Record decisions in the sketchbook as `D-NN` with rationale.
- Record events as `E-NN`, commands as `C-NN`, policies as `P-NN`.
- After each stage, checkpoint to `docs/SKETCHBOOK.md` and confirm before
  proceeding.

## Project Location

- Working directory: `/home/bakerb/sandbox/github/claudecode-workflow`
- Platform: GitHub, `gh` CLI
- Branch: `main`
- `docs/SKETCHBOOK.md` is uncommitted — commit when DDD session completes
