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
4. **Cross-repo detection.** For each phase about to be persisted, walk every sub-issue's ref. Resolve each ref's `owner/repo` (per-issue `repo` field, else plan-level `repo`, else the orchestrator's current project repo). Collect distinct repo slugs that differ from the orchestrator's project repo. If the set is non-empty, set `cross_repo: true` and `target_repos: [<slug>, ...]` on that phase in the plan JSON. Single-repo phases leave both fields unset. Cheap — no extra LLM calls; pure walk over refs already in `wave_compute`'s output.
5. **Approval gate.** Wait for explicit user approval. Iterate on the plan here — not during `/nextwave`.
6. **Persist.** Call `wave_init(plan_json)` — the tool auto-detects existing plans and uses extend mode, preserving completed waves. Use phase-prefixed wave IDs (e.g., `wave-2a`) to avoid collisions when extending. Cross-repo fields (`cross_repo`, `target_repos`) round-trip without modification (the underlying `wave-status init` writes the plan dict verbatim to `phases-waves.json`).
7. **Conditional recipe injection.** If any prepped phase has `cross_repo: true`, append the cross-repo recipe to this skill's output by `cat`ing `skills/_shared/recipes/cross-repo-wave-orchestration.md`. Format:

   ```
   ## Cross-Repo Recipe (auto-loaded because Phase X spans repos: <target_repos>)

   <recipe content here>
   ```

   Single-repo runs skip this step entirely — no context bloat. The recipe's content lives in one place; both `/prepwaves` (here) and `/nextwave` (preflight) `cat` from the same file.
8. **Confirm.** Report wave count, issue count, readiness summary, cross-repo status (if any), and "Run `/nextwave` to begin execution."

## Reasoning Rules (Preserve)

- This is a PLANNING skill — no implementation code runs here.
- Push back hard on vague sub-issues. Vague issue → guessing agent; precise issue → executing agent.
- **Serial is a valid wave topology.** Don't reject a linear dependency chain — classify it and let `/nextwave` use its streamlined single-issue path.
- Do NOT create branches at prep time — `/nextwave` creates them from current main at execution time.
- File-level conflict detection is `/nextwave`'s job (flight partitioning). Here you only care about dependency-level ordering.
- Pair: `/prepwaves` plans, `/nextwave` executes one wave at a time.
