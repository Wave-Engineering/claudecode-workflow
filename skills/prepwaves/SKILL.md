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

**See Also:** `docs/executor-model-devspec.md` (Plan #822 — the executor model: `/prepwaves` computes the per-wave `fan`/`serialize` dispatch hint that `/nextwave` reads; see §5.1 and Story 1.1).

## Axioms

Bound by WAVE_AXIOMS 1 and 10 (`WAVE_AXIOMS.md` at the repo root). `/prepwaves` is a planning skill, so the campaign-runtime axioms (2–6, 8, 9) bind `/nextwave` and `/wavemachine`, not this skill. **Axiom 1** (serial is a valid topology) governs how it classifies and presents waves; **Axiom 10** (a wave targets exactly one repo) is the plan-time invariant this skill enforces — see the single-repo validator in step 4.

## Tools Used

- `mcp__sdlc-server__wave_campaign_precheck` — residue gate (step 0.5): detect a prior campaign's leftover state (active driver, pending/promoted waves, stale kahuna branches) before planning a new one. Pure read, no mutation (server contract: mcp-server-sdlc#457)
- `mcp__sdlc-server__epic_sub_issues` — enumerate children of a Plan tracking issue (the tool name is a historical identifier; it enumerates sub-issues of any parent, and `/prepwaves` calls it on the Plan)
- `mcp__sdlc-server__spec_validate_structure` — pre-flight check each sub-issue's shape (Changes / Tests / Acceptance / Dependencies)
- `mcp__sdlc-server__spec_dependencies` — extract declared edges
- `mcp__sdlc-server__wave_compute` — topological sort into waves
- `mcp__sdlc-server__wave_topology` — classify as parallel / serial / mixed
- `mcp__sdlc-server__wave_init` — persist the plan (supports extend mode for multi-phase)

## Procedure

0. **Clean-tree gate (FIRST — before anything).** `/prepwaves` MUST refuse to run on a dirty working tree. Another agent's uncommitted work in the same checkout has stranded a prep before (Plan #581: 394 uncommitted lines in a foreign branch required a hand-rolled patch-and-revert to recover). Run `git status --porcelain`; if it returns **any** lines, **STOP** and refuse: report the offending paths (modified + untracked) and tell the user to commit, stash, or clean them first. Do NOT auto-stash or auto-clean — a dirty tree is the user's to resolve, never `/prepwaves`'s. Only a clean tree proceeds to the Campaign residue gate below.

0.5. **Campaign residue gate (`wave_campaign_precheck`).** Before planning a new campaign, call `mcp__sdlc-server__wave_campaign_precheck(root)` (pure read — never mutates) to detect leftover state from a prior campaign in this checkout. This catches the failure mode where a fresh `/prepwaves` silently stomps an in-flight or half-promoted campaign. Branch on the returned `state`:
   - `state == "clean"` → proceed to the Multi-Phase guard.
   - `state == "residue_found"` → **STOP** and surface, do NOT auto-resolve:
     - `classification` — `"dead"` (a stale/abandoned campaign, safe to replace) vs `"ambiguous"` (possibly-live, needs human judgment).
     - `residue` — `plan_id`, `wavemachine_active`, `pending_waves`, `promoted_waves`, `kahuna_branches[]`.
     - `options` (`preserve_wait` / `preserve_extend` / `replace`) and the server's `recommended` option.

     Present these and **wait for the user to choose**. `replace` (the usual `recommended` for `"dead"`) clears the residue and re-plans; `preserve_*` keeps the existing campaign. Never pick for the user — a half-promoted campaign is theirs to resolve.

   Server contract: mcp-server-sdlc#457. Consumer half: cc-workflow#716. Field names are #457's verbatim — read `state`/`classification`/`options`/`recommended`/`residue.kahuna_branches`, not any earlier paraphrase.

1. **Persisted-plan handling — subsumed by the 0.5 residue gate (cc-workflow#716 AC-4).** The former narrow `phases-waves.json` multi-Phase guard is now folded into `wave_campaign_precheck`: an existing persisted plan — including a multi-Phase plan written by `/devspec upshift` — should surface at step 0.5 as `state == "residue_found"` (its `residue.plan_id` + `pending_waves`/`promoted_waves` reflect the persisted plan), and the operator resolves it there:
   - `preserve_wait` / `preserve_extend` → keep the existing plan; run `/nextwave` to execute it (this replaces the old "persist is unnecessary, run `/nextwave`" message).
   - `replace` → clear it and re-plan from scratch.
   - **Single-Phase re-run** (same `plan_id` re-prepped) needs no stop — `wave_init`'s extend/idempotent path at step 7 handles it; proceed normally.
   - **On-disk fallback (don't depend on the seam).** If step 0.5 returned `state == "clean"` but `.claude/status/phases-waves.json` exists with `phases.length > 1`, **STOP anyway**: report the persisted multi-Phase plan and tell the user to run `/nextwave` to execute it or delete the file to re-plan. This keeps the multi-Phase guarantee independent of how `wave_campaign_precheck` classifies a persisted-but-unstarted plan (a freshly `/devspec upshift`'d plan with no runtime footprint may read as `clean` if #457 keys residue on runtime signals) — so prepwaves never silently re-plans over an existing multi-Phase topology.

2. **Inputs.** Plan tracking-issue numbers passed by the user (`/prepwaves #2` or `/prepwaves #2 #3 ...`). Each Plan becomes one Phase in `phases-waves.json`.
3. **Pre-flight readiness table.** For each Plan:
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
4. **Compute waves.** Call `wave_compute(epic_ref)` (param name is historical — pass the Plan's issue ref) to get the topologically-sorted wave plan, then `wave_topology(...)` to classify. Present the wave plan (waves, issues, dependency chain, branch naming `feature/<N>-<desc>`).

   **Single-repo-per-wave validator (Axiom 10).** After computing waves, resolve every issue in each wave to its `owner/repo` (per-issue `repo`, else plan-level `repo`, else the project repo). If any single wave's issues span **more than one** distinct repo, **STOP and refuse** — name the offending wave and its conflicting repos, and tell the planner to split it into serial single-repo phases (expand-contract), never one straddling wave (there is no atomic two-remote promotion). A *phase* may still span repos across its waves (`cross_repo: true`, step 5) — the invariant is per-wave, not per-phase.

   **4.A — Dispatch classification.** After the `wave_topology` call returns, annotate **each** wave with a `dispatch` field that tells `/nextwave` how its flights may execute: `fan` (flights run concurrently), `serialize` (flights run one at a time), or `serialize-preferred` (serialize by default, may fan only if the operator opts in). Apply this four-rule table per wave — *width* is the number of flights (issues) in the wave:

   | Rule | Condition | `dispatch` |
   |---|---|---|
   | 1 | Width = 1 | `serialize` |
   | 2 | Width > 1, **any** intra-wave dependency edge between its flights | `serialize` — **hard gate** (F-8 class); a dep edge inside a wave can never be overridden to `fan` |
   | 3 | Width > 1, all flights independent, work is **mechanical** (no cross-flight learning to share) | `fan` |
   | 4 | Width > 1, all flights independent, work has **learning potential** (a lesson from one flight would sharpen another) | `serialize-preferred` |

   **Asymmetric bias — default is `serialize`.** The two misclassifications are not equally costly. A **wrong `serialize`** costs only wall-clock: the wave still lands, just slower. A **wrong `fan`** can *kill the wave*: flights that were not actually independent corrupt each other's work and the whole wave must be re-run. So when a wave is ambiguous, bias toward `serialize` — **wrong serialize = wall-clock cost; wrong fan = wave kill; default is serialize.** Rule 2 (intra-wave dep edge) is a hard gate, not a bias — it is never overridable to `fan`.

   Embed the resolved value on each wave in the plan JSON as `dispatch: <fan|serialize|serialize-preferred>` (it round-trips through `wave_init` — see step 7).
5. **Cross-repo detection.** For each Phase about to be persisted, walk every sub-issue's ref. Resolve each ref's `owner/repo` (per-issue `repo` field, else plan-level `repo`, else the orchestrator's current project repo). Collect distinct repo slugs that differ from the orchestrator's project repo. If the set is non-empty, set `cross_repo: true` and `target_repos: [<slug>, ...]` on that Phase in the plan JSON. Single-repo Phases leave both fields unset. Cheap — no extra LLM calls; pure walk over refs already in `wave_compute`'s output.
6. **Approval gate.** Before presenting the plan for approval, verify the current branch:
   - Resolve the project's protected branch: read `## Branching` from `.claude-project.md` in the repo root; if the file is absent or the field is missing, default to `main`/`master`.
   - Run `git rev-parse --abbrev-ref HEAD`.
   - If the result is **not** the protected branch or a branch matching `^release/`, **STOP and refuse approval**: report the current branch and tell the user to check out the project's protected branch first. Feature branches cut from a wrong base target the wrong upstream — this must be correct before the plan is locked in.
   - Once the branch check passes, present the wave plan — including **each wave's `dispatch` classification** (`fan` / `serialize` / `serialize-preferred`) from step 4.A alongside its issues and dependency chain — and wait for explicit user approval. Surfacing `dispatch` at the gate lets the operator veto a `fan` before the plan locks in. Iterate on the plan here — not during `/nextwave`.

7. **Persist.** Call `wave_init(plan_json)` — the tool auto-detects existing plans and uses extend mode, preserving completed waves. Use Phase-prefixed wave IDs (e.g., `wave-2a`) to avoid collisions when extending. Cross-repo fields (`cross_repo`, `target_repos`) round-trip without modification (the underlying `wave-status init` writes the plan dict verbatim to `phases-waves.json`). The per-wave `dispatch` field (step 4.A) is round-trippable the same way — `wave_init` persists it verbatim onto each wave in `phases-waves.json`. Reading and *enforcing* that field at execution time is `/nextwave`'s job, delivered by **Story 1.2 (#824)**: a wave (or an older `phases-waves.json`) that carries **no** `dispatch` field will be treated as `serialize` — a backward-compatible default, so plans written before this field existed still execute correctly. Until #824 lands, `/prepwaves` only *writes* the annotation; the executor's dispatch enforcement (in `per-wave-workflow.js`) is #824's deliverable, not this story's.

   **Commit the plan file (required).** After `wave_init` returns, check whether `.claude/status/phases-waves.json` appears in `git status --porcelain` output. If it does (the file is tracked or newly added), commit it:
   ```
   git add .claude/status/phases-waves.json
   git commit -m "chore: persist wave plan for Plan #N"
   ```
   If the file does not appear in `git status` (it is gitignored in this repo), the working tree is already clean — no commit needed. Do NOT skip this check. `/wavemachine`'s pre-flight requires a clean base branch (`base branch clean`). Leaving `phases-waves.json` uncommitted in a tracking repo is the #1 cause of "tidy the sandbox" errors when the campaign starts.
8. **Conditional recipe injection.** If any prepped Phase has `cross_repo: true`, append the cross-repo recipe to this skill's output by `cat`ing `skills/_shared/recipes/cross-repo-wave-orchestration.md`. Format:

   ```
   ## Cross-Repo Recipe (auto-loaded because Phase X spans repos: <target_repos>)

   <recipe content here>
   ```

   Single-repo runs skip this step entirely — no context bloat. The recipe's content lives in one place; both `/prepwaves` (here) and `/nextwave` (preflight) `cat` from the same file.
9. **Confirm + seed a fresh campaign session.** Report wave count, issue count, readiness summary, and cross-repo status (if any). Then emit a final recommendation to start the campaign in a **fresh session** — `/prepwaves` accumulates heavy one-shot planning context (sub-issue bodies, dependency analysis, readiness validation) that adds drift to the execution session, so a `/clear` before `/wavemachine` keeps the campaign's context clean:

   ```
   ✅ Wave plan persisted for Plan #N.

   👉 Recommended next step: `/clear`, then in the fresh session run:

       /wavemachine

   Starting the campaign in a clean session reduces context drift before execution.
   ```

   If the current session has ample headroom (`/nerf status` shows the soft dart <30% consumed), downgrade this to a one-line hint rather than a strong nudge — the `/clear` pays off most when the planning context is already heavy.

## Reasoning Rules (Preserve)

- This is a PLANNING skill — no implementation code runs here.
- Push back hard on vague sub-issues. Vague issue → guessing agent; precise issue → executing agent.
- **Serial is a valid wave topology.** Don't reject a linear dependency chain — classify it and let `/nextwave` use its streamlined single-issue path.
- Do NOT create branches at prep time — `/nextwave` creates them from current main at execution time.
- File-level conflict detection is `/nextwave`'s job (flight partitioning). Here you only care about dependency-level ordering.
- Pair: `/prepwaves` plans, `/nextwave` executes one wave at a time.
