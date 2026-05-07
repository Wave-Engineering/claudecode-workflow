---
name: prepwaves
description: Analyze a master issue, validate sub-issue specs, compute dependency waves, and prepare for wave-pattern execution (parallel, serial, or mixed)
---

# PrepWaves — Plan Wave Execution

## Axioms

This skill is bound by WAVE_AXIOMS 1, 6, 7, 8 — see `WAVE_AXIOMS.md` at the repo root. The "serial is a valid wave topology" rule (Axiom 1), the assessment-skill binding (Axiom 7 — measure justification not parallelism), the approval-frequency rule (Axiom 6 — `/prepwaves` has its own approval gate at step 6, distinct from `/nextwave`'s execution gate), and the axioms-supersede-judgment principle (Axiom 8) live in that file. The mechanical detail below (sandbox-clean pre-flight, readiness table, wave computation, persistence) is the operational binding for those axioms — when justification prose seems missing, it is in `WAVE_AXIOMS.md` by design.

Analyze one or more Plan tracking issues, validate their sub-issue specs, compute dependency-ordered waves, and persist the plan so `/nextwave` can execute it. Supports parallel, serial, and mixed topologies.

## Tools Used

- `mcp__sdlc-server__epic_sub_issues` — enumerate children of a Plan tracking issue (the tool name is a historical identifier; it enumerates sub-issues of any parent, and `/prepwaves` calls it on the Plan)
- `mcp__sdlc-server__spec_validate_structure` — pre-flight check each sub-issue's shape (Changes / Tests / Acceptance / Dependencies)
- `mcp__sdlc-server__spec_dependencies` — extract declared edges
- `mcp__sdlc-server__wave_compute` — topological sort into waves
- `mcp__sdlc-server__wave_topology` — classify as parallel / serial / mixed
- `mcp__sdlc-server__wave_init` — persist the plan (supports extend mode for multi-phase)

## Procedure

1. **Sandbox cleanliness pre-flight (refuse if dirty).** Before doing anything else, verify the working tree is clean and on the project's protected base branch. Run **both** of these from the project root:

   ```bash
   git status --porcelain
   git rev-parse --abbrev-ref HEAD
   ```

   Refuse to proceed and STOP if **either** of the following is true:

   - `git status --porcelain` returns any output (untracked, modified, or staged files present).
   - The current branch is not the project's protected base branch (read from `.claude-project.md`'s `Default branch` field — typically `main` on GitHub repos, may be `release/<ver>` on AnalogicDev GitLab repos, etc.).

   The refusal message MUST include:

   - The exact `git status --porcelain` output (so the operator sees every offending path and can choose between commit, stash, or `git checkout --`).
   - The current branch (when wrong-branch is the cause) and the expected protected base branch.
   - The remediation menu: commit, stash, discard, or checkout the protected base branch.

   **Override (use sparingly, must be noisy).** If the operator passes `--force-dirty` (e.g. `/prepwaves --force-dirty #607`), proceed despite a dirty tree or wrong branch — but emit a loud banner BEFORE step 2 listing every offending path AND the current branch, plus the line `WARNING: --force-dirty bypasses sandbox cleanliness gate. Cross-talk risk is on the operator.` Do not silently absorb the override; the banner is the audit trail.

   **Rationale (load-bearing — do not delete).** This gate exists because of the Plan #581 sandbox cross-talk incident (2026-05-05): another agent's uncommitted work in `fix/377-wave-init-base-branch-persist` (~394 lines) was sitting in the same checkout when `/prepwaves` ran, and required hand-rolled patch-and-revert to recover. A dirty sandbox at prep time is the leading indicator of inter-agent cross-talk. Refusing here is cheap; recovering from a polluted Plan-tracking commit is not.

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
5. **Cross-repo detection.** For each Phase about to be persisted, walk every sub-issue's ref. Resolve each ref's `owner/repo` (per-issue `repo` field, else plan-level `repo`, else the orchestrator's current project repo). Collect distinct repo slugs that differ from the orchestrator's project repo. If the set is non-empty, set `cross_repo: true` and `target_repos: [<slug>, ...]` on that Phase in the plan JSON. Single-repo Phases leave both fields unset. Cheap — no extra LLM calls; pure walk over refs already in `wave_compute`'s output.
6. **Approval gate.** Wait for explicit user approval. Iterate on the plan here — not during `/nextwave`.
7. **Persist.** Call `wave_init(plan_json)` — the tool auto-detects existing plans and uses extend mode, preserving completed waves. Use Phase-prefixed wave IDs (e.g., `wave-2a`) to avoid collisions when extending. Cross-repo fields (`cross_repo`, `target_repos`) round-trip without modification (the underlying `wave-status init` writes the plan dict verbatim to `phases-waves.json`).
8. **Conditional recipe injection.** If any prepped Phase has `cross_repo: true`, append the cross-repo recipe to this skill's output by `cat`ing `skills/_shared/recipes/cross-repo-wave-orchestration.md`. Format:

   ```
   ## Cross-Repo Recipe (auto-loaded because Phase X spans repos: <target_repos>)

   <recipe content here>
   ```

   Single-repo runs skip this step entirely — no context bloat. The recipe's content lives in one place; both `/prepwaves` (here) and `/nextwave` (preflight) `cat` from the same file.
9. **Confirm.** Report wave count, issue count, readiness summary, cross-repo status (if any), and "Run `/nextwave` to begin execution."
10. **Emit seed prompt + `/clear` recommendation (final block).** After persistence and confirmation, end `/prepwaves` output with a paste-ready seed for a fresh `/wavemachine` session. The block lives at the very end of the success path so the operator's eye lands on it last and the slash command is one paste away.

    Default wording (strong nudge — use when the current session has accumulated significant `/prepwaves` planning context):

    ```
    Wave plan persisted for Plan #N.

    Recommended next step: `/clear` then in a fresh session paste:

        /wavemachine

    This reduces context drift before the campaign begins.
    ```

    **Conditional downgrade.** If `mcp__nerf-server__nerf_status` reports the current session is using less than 30% of its soft dart, the recommendation may be downgraded to a hint — same seed, softer language:

    ```
    Wave plan persisted for Plan #N.

    Optional: `/clear` and start a fresh session before `/wavemachine` if you want a clean context. This session has plenty of headroom, so it's not required:

        /wavemachine
    ```

    Either variant: the line containing `/wavemachine` MUST be on its own line, indented as a code block (4-space indent or fenced) so the operator can paste it cleanly without surrounding markdown. No trailing punctuation, no decoration on the slash-command line itself.

    **Rationale (load-bearing — do not delete).** This recommendation exists because of context-rot observed during Plan #581 debrief: `/prepwaves` accumulates a lot of one-shot planning context (sub-issue bodies, dependency analysis, readiness validation, cross-repo recipe injection) that adds noise to the subsequent `/wavemachine` execution session. Carrying that context into the campaign measurably degrades flight-agent prompts down-stream (the noise propagates via the orchestrator's session). A fresh session before `/wavemachine` is the cheapest mitigation — costs one `/clear`, removes a known drift source. The seed-prompt block makes the cheap path the obvious path; do not remove it in a future skill rewrite without an equivalent mitigation.

## Reasoning Rules (Preserve)

- This is a PLANNING skill — no implementation code runs here.
- Push back hard on vague sub-issues. Vague issue → guessing agent; precise issue → executing agent.
- **Serial is a valid wave topology** — per WAVE_AXIOMS Axiom 1. Don't reject a linear dependency chain; classify it and let `/nextwave` use its streamlined single-issue path.
- Do NOT create branches at prep time — `/nextwave` creates them from current main at execution time.
- File-level conflict detection is `/nextwave`'s job (flight partitioning). Here you only care about dependency-level ordering.
- Pair: `/prepwaves` plans, `/nextwave` executes one wave at a time.
