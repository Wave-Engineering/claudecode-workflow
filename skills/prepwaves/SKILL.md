---
name: prepwaves
description: Analyze a master issue, validate sub-issue specs, compute dependency waves, and prepare for wave-pattern execution (parallel, serial, or mixed)
---

# PrepWaves — Plan Wave Execution

Analyze one or more epic issues, validate their sub-issue specs, compute dependency-ordered waves, and persist the plan so `/nextwave` can execute it. Supports parallel, serial, and mixed topologies.

## Tools Used

- `mcp__sdlc-server__epic_sub_issues` — enumerate children of an epic
- `mcp__sdlc-server__spec_validate_structure` — pre-flight check each sub-issue's shape (Changes / Tests / Acceptance / Dependencies)
- `mcp__sdlc-server__spec_dependencies` — extract declared edges
- `mcp__sdlc-server__wave_compute` — topological sort into waves
- `mcp__sdlc-server__wave_topology` — classify as parallel / serial / mixed
- `mcp__sdlc-server__wave_init` — persist the plan (supports extend mode for multi-phase)

## Procedure

1. **Inputs.** Master issue numbers passed by the user (`/prepwaves #2` or `/prepwaves #2 #3 ...`). Each epic becomes one phase.
2. **Pre-flight readiness table.** For each epic: call `epic_sub_issues(N)`; for each child call `spec_validate_structure(N)`. Present a table (Issue | Title | Deps | Changes | Tests | AC | Ready?). If any sub-issue is not ready, stop and ask the user how to proceed.
3. **Compute waves.** Call `wave_compute(epic_ref)` to get the topologically-sorted wave plan, then `wave_topology(...)` to classify. Present the wave plan (waves, issues, dependency chain, branch naming `feature/<N>-<desc>`).
4. **Approval gate.** Wait for explicit user approval. Iterate on the plan here — not during `/nextwave`.
5. **Persist.** Call `wave_init(plan_json)` — the tool auto-detects existing plans and uses extend mode, preserving completed waves. Use phase-prefixed wave IDs (e.g., `wave-2a`) to avoid collisions when extending.
6. **Confirm.** Report wave count, issue count, readiness summary, and "Run `/nextwave` to begin execution."

## Reasoning Rules (Preserve)

- This is a PLANNING skill — no implementation code runs here.
- Push back hard on vague sub-issues. Vague issue → guessing agent; precise issue → executing agent.
- **Serial is a valid wave topology.** Don't reject a linear dependency chain — classify it and let `/nextwave` use its streamlined single-issue path.
- Do NOT create branches at prep time — `/nextwave` creates them from current main at execution time.
- File-level conflict detection is `/nextwave`'s job (flight partitioning). Here you only care about dependency-level ordering.
- Pair: `/prepwaves` plans, `/nextwave` executes one wave at a time.
