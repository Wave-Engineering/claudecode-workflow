# Scratchpad — Dev Spec traceability + decorative-AC failure mode

**Status:** thinking — not yet ready for an issue.
**Started:** 2026-04-28 by BJ + rules-lawyer.
**Format:** chronological notes, bullets > prose, observations > prescriptions. Edit freely.

---

## Triggering incident

cue-ball (blueshift-cue) shipped Phase 1 work claiming completion against `agentic-devspec.md`. Phase 1 DoD line 1038 mandates "All container images pass image smoke (DM-T2-02)." She delivered:

- `build.sh` — stub (echoes what it would do)
- `image-smoke.sh` — stub
- 5 missing swarm fragments (only `pipeline.yml` exists)
- Stories #67/#68/#96/#97/#98 closed without verifying their image-smoke AC
- VRTM "pass" claims overstated — 8 R-IDs are actually Partial

She self-flagged after BJ asked. Audit-log evidence + transcript at `/tmp/devspec-ignored.txt`.

## Diagnosis — where did the containers actually go missing?

**Initial theory (rules-lawyer):** Skeleton-as-terminal — Story 1.1 permits `build.sh`/`image-smoke.sh` as no-ops at its own boundary; agent treated those stubs as terminal artifacts and didn't return to fill them in at later stories.

**BJ's counter:** "She decided not to do the work. Before a single file was edited, containers were already gone." Failure happened at *spec-write* time, not implementation time.

**Sub-agent's first read:** "Every service story has a Dockerfile implementation step AND an 'image passes image smoke' AC."

**Direct verification (rules-lawyer, targeted reads):** Sub-agent was technically right but misled by counting bullets without weighing them. Reality:

- Each service story (3.1–3.4, 4.1, 4.2) has **one terse Implementation Step bullet** ("Dockerfile and /health endpoint" — verbatim for Story 3.2 step 7).
- Each has **one AC checkbox** ("Docker image passes image smoke") — but the AC is unverifiable as written. Nothing in the story forces the agent to actually run `image-smoke.sh` to tick it.
- No story schedules: filling in `build.sh`/`image-smoke.sh` stubs from Story 1.1, wiring per-service publish into `.gitlab-ci.yml`, registering services in the smoke matrix.

**Synthesis:** Containers are *named* in every story, but not *weighted*. The decorative checkboxes pass spec validation; they don't pass production. cue-ball produced exactly what was scheduled. The spec carries containers all the way to Phase 1 DoD; the dropoff is the row labeled "Story Implementation Steps."

This is a different failure than "agent ignored the spec." It's "spec author scheduled work that's a paper checkbox, not a production deliverable."

## The pattern, named

**Decorative AC.** A Story's Acceptance Criteria checkbox names a deliverable, but the Story's Implementation Steps don't schedule the work that produces that deliverable. The agent ticks the checkbox by hitting some weaker proxy ("Dockerfile compiles locally" instead of "image passes the gate"). The deliverable was load-bearing in §5.A and the global DoD; it's a ghost in the story.

**Stub-orphan.** A deliverable is partially fulfilled by an early-story stub (Story 1.1 ships `image-smoke.sh` as a no-op, by design) but no later story has an Implementation Step that schedules the stub's completion. The deliverable becomes orphaned — owned by §5.A in concept, by Story 1.1 as a stub, by no one for completion.

These are the two structural failure modes the trace-graph would catch.

## Proposal — running traceability graph

### Big idea (BJ)

> Every time a new section is written, there is a check to make sure that everything in the previous section is properly and fully connected to something in the new section. A running traceability graph through the entire document. To finalize a section, *a different agent* checks the traces. The dev agent doesn't see the graph (so they can't game it). The SDLC MCP launches the review agent with `claude -P "prompt"` so the dev agent's context can't poison it.

### Concept extraction

The doc already has IDs we can hang the graph on: `R-NN`, `DM-T2-NN`, `MV-NN`, `IT-NN`, `Story N.M`, Phase IDs, Wave IDs.

One cheap addition: **AC bullet IDs**. `[ ] (AC-3.1.2) Docker image passes image smoke` — minimal markup, machine-extractable.

### Edge types

- `R-22 [verified by] MV-04` (R-ID → verification)
- `MV-04 [executes] DM-T2-02 [via] image-smoke.sh` (verification → deliverable → script)
- `DM-T2-02 [scheduled by] Story 1.1 / Step 11` (deliverable → story implementation step)
- `Story 3.2 / AC-3.2.5 [closes] DM-T2-02` (AC → deliverable)
- `Story 1.1 [permits stub for] image-smoke.sh` (story → script with stub-permission flag)

### Required graph properties (for the review agent to enforce)

1. **Every concept introduced is referenced downstream.** R-IDs introduced in §3 must be verified by an MV/IT in §6 and have at least one Story Implementation Step that schedules production.
2. **Every AC checkbox traces to an Implementation Step.** If `AC-3.2.5` says "Docker image passes image smoke" and no Implementation Step in Story 3.2 (or any prior story it depends on) is scheduled to produce that, **decorative AC** flag.
3. **Stubs have completion edges.** Any deliverable produced as a stub by Story X must have an outgoing edge to Story Y where the stub is scheduled for completion. **Stub-orphan** flag if missing.
4. **Phase DoD checkboxes trace to stories.** Phase 1 DoD line 1038 ("all container images pass image smoke") must trace to per-story AC that close it. If only Story 1.1 stubs the script and no service-story schedules running it, the DoD is unbacked.

### Where the graph lives

Not in the doc. `.claude/devspec-trace/<plan>.json` — derived, not authored. The doc carries the IDs (already does mostly); the graph extractor parses cross-references; the reviewer validates.

### MCP tool surface (proposed)

```
devspec_section_trace_check(spec_path, section_being_finalized)
  → load existing graph (if any)
  → extract new section's concepts + cross-references
  → spawn `claude -P` with:
      - the JSON graph from sections 1..N-1
      - the raw text of section N
      - a prompt: "validate that no concept introduced earlier is now an
         orphan; flag decorative-AC and stub-orphan patterns; report graph
         additions; refuse to finalize if violations exist"
  → parse structured response
  → persist updated graph
  → return {orphans, decorative_AC, stub_orphans, new_nodes}
```

### Why `claude -P` specifically

The review agent has to be context-isolated from the writing agent. Same-session sub-agents inherit priors and can be unconsciously steered. `claude -P` spawns a fresh Claude with a clean context — only what the prompt + filesystem give it. Can't be poisoned by anything in the writing session.

The MCP tool is the right host because:
- It's already where deterministic checks live (`spec_validate_structure`, `dod_*`, etc.)
- It can persist the graph alongside `.claude/status/` artifacts
- It's the natural integration point for `/devspec` skill workflow

## Open questions

1. **AC ID convention.** `[ ] (AC-3.1.2) Foo` works but bloats every checkbox by 11 chars. Acceptable? Or auto-generate IDs at extraction time and reference by stable hash of the checkbox text? (Auto-gen breaks if BJ edits a checkbox; fragile.)
2. **What's the right granularity for "section finalization"?** Per-story? Per-Phase-section? Whole-doc-at-once? The skill workflow has natural boundaries — `/devspec create` walks sections one by one — but the trace check is most useful between sections, not within.
3. **How does the writing agent learn what's missing without seeing the graph?** The reviewer flags "decorative AC at AC-3.2.5"; the writing agent needs to fix it without seeing the graph state. Maybe the reviewer's output is human-readable bullets ("Story 3.2 AC #5 references DM-T2-02 but no Implementation Step schedules it; add a step or remove the AC") — that's enough for the writer to act on without revealing the full graph.
4. **What about the existing VRTM table?** It's already a partial traceability matrix. Does the new graph subsume it, augment it, or replace it? Probably augment — VRTM is human-facing summary, graph is machine-validated state.
5. **Performance of `claude -P` for every section finalize.** A full Claude spawn is ~15-30s on cold cache. Acceptable for `/devspec create` (interactive); painful if integrated into something tight. Bound the cost somehow.
6. **What happens when the human edits the graph manually?** Should they be able to? If a deliverable is genuinely deferred to a follow-up Plan, an explicit edge `[deferred to plan #N]` needs to be authorable somehow.

## Cross-references

- Original incident: `/tmp/devspec-ignored.txt`
- The spec under analysis: `/home/bakerb/sandbox/gitlab/blueshift-devkit/blueshift-cue/Docs/agentic-devspec.md`
- Existing process: `skills/devspec/SKILL.md` (the `/devspec` walk)
- Existing validators: `mcp-server-sdlc` `spec_validate_structure`, `dod_*` family
- Memory write by cue-ball after the incident: `feedback_devspec_is_canonical.md` (in blueshift-cue project memory, 5.2 KB) — captures her own lesson but doesn't address the structural fix.

## What we're NOT doing yet

- Filing issues. This is too early — design isn't settled, open questions outnumber decisions.
- Writing the tool. Same.
- Updating any existing skill. Same.
- Hand-walking the cue-ball spec to find every other decorative-AC. cue-ball already has the missing-deliverables work in flight; let her finish.

## Next steps (when we pick this up)

- Decide AC ID convention (open question 1)
- Decide section-finalization granularity (open question 2)
- Sketch the reviewer's output format (open question 3)
- If still convinced after sleeping on it, file as a **Dev Spec for cc-workflow** — multi-Phase plan (graph extraction infra, MCP tool, AC ID convention, doc-template update, integration with `/devspec` skill).
