---
name: prepwaves
description: Validate sub-issue specs, compute dependency waves, prepare for wave-pattern execution
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-prepwaves does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-prepwaves
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# PrepWaves — Plan Wave Execution

Analyze one or more Plan tracking issues, validate their sub-issue specs, compute dependency-ordered waves, and persist the plan so `/nextwave` can execute it. Supports parallel, serial, and mixed topologies.

## Tools Used

- `mcp__sdlc-server__epic_sub_issues` — enumerate children of a Plan tracking issue (the tool name is a historical identifier; it enumerates sub-issues of any parent, and `/prepwaves` calls it on the Plan)
- `mcp__sdlc-server__spec_validate_structure` — pre-flight check each sub-issue's shape (Changes / Tests / Acceptance / Dependencies)
- `mcp__sdlc-server__spec_dependencies` — extract declared edges
- `mcp__sdlc-server__wave_compute` — topological sort into waves
- `mcp__sdlc-server__wave_topology` — classify as parallel / serial / mixed
- `mcp__sdlc-server__wave_init` — persist the plan (supports extend mode for multi-phase)

## Procedure

0. **Multi-Phase guard.** Before any work, check if `.claude/status/phases-waves.json` already exists in the project. If it does, read it and inspect `phases.length`:
   - If `phases.length > 1` (multi-Phase topology already written by `/devspec upshift`): **STOP.** Report to the user: "`phases-waves.json` already contains a multi-Phase topology (N phases, M waves, K stories). This was written by `/devspec upshift` — `/prepwaves` persist is unnecessary. Run `/nextwave` to begin execution, or delete `phases-waves.json` to re-plan from scratch."
   - If `phases.length === 1` and the plan's `plan_id` matches one of the user's input Plan refs: this is a re-run of a single-Phase prep. Proceed normally (wave_init's extend/idempotent path handles it).
   - If the file does not exist: proceed normally (fresh prep).

1. **Inputs.** Plan tracking-issue numbers passed by the user (`/prepwaves #2` or `/prepwaves #2 #3 ...`). Each Plan becomes one Phase in `phases-waves.json`.
2. **Pre-flight readiness table.** For each Plan:
   a. Call `epic_sub_issues(N)` inline to get the list of sub-issue numbers (must complete before spawning validators — you need the list first).
   b. Launch **one Haiku sub-agent per sub-issue in a single message** (parallel). Each sub-agent runs `spec_validate_structure` for its issue and returns a one-line result: `#N | <title> | <deps> | Changes:✓/✗ | Tests:✓/✗ | AC:✓/✗ | <Ready/NOT READY>`. Sub-agents have no data dependencies on each other — all can run concurrently.

   Sub-agent template (one per sub-issue, all launched in a single message):
   ```
   subagent_type: general-purpose
   model: haiku
   prompt: "Call mcp__sdlc-server__spec_validate_structure for issue #<N> in repo <owner/repo>.
            Return a single line: #<N> | <title> | deps:<dep_list or none> | Changes:<✓ or ✗> | Tests:<✓ or ✗> | AC:<✓ or ✗> | <Ready or NOT READY: list missing sections>"
   ```

   Assemble the returned lines into the readiness table. If any sub-issue is NOT READY, stop and ask the user how to proceed.
3. **Compute waves.** Call `wave_compute(epic_ref)` (param name is historical — pass the Plan's issue ref) to get the topologically-sorted wave plan, then `wave_topology(...)` to classify. Present the wave plan (waves, issues, dependency chain, branch naming `feature/<N>-<desc>`).
4. **Cross-repo detection.** For each Phase about to be persisted, walk every sub-issue's ref. Resolve each ref's `owner/repo` (per-issue `repo` field, else plan-level `repo`, else the orchestrator's current project repo). Collect distinct repo slugs that differ from the orchestrator's project repo. If the set is non-empty, set `cross_repo: true` and `target_repos: [<slug>, ...]` on that Phase in the plan JSON. Single-repo Phases leave both fields unset. Cheap — no extra LLM calls; pure walk over refs already in `wave_compute`'s output.
5. **Approval gate.** Wait for explicit user approval. Iterate on the plan here — not during `/nextwave`.
6. **Persist.** Call `wave_init(plan_json)` — the tool auto-detects existing plans and uses extend mode, preserving completed waves. Use Phase-prefixed wave IDs (e.g., `wave-2a`) to avoid collisions when extending. Cross-repo fields (`cross_repo`, `target_repos`) round-trip without modification (the underlying `wave-status init` writes the plan dict verbatim to `phases-waves.json`).
7. **Conditional recipe injection.** If any prepped Phase has `cross_repo: true`, append the cross-repo recipe to this skill's output by `cat`ing `skills/_shared/recipes/cross-repo-wave-orchestration.md`. Format:

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
