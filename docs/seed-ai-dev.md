# Seed: Orienting a New AI Developer

You are a Claude Code agent being dropped into an active, multi-repo engineering organization. This doc's job is to get you *functionally* oriented in one read — not exhaustively, just enough that you can pick up work without asking questions the codebase and memory files can answer for you.

Read this end-to-end, then **run `/engage`** before doing anything else. `/engage` loads memory and confirms the rules of engagement. This doc gives you the map; `/engage` tells you where you are on it today.

---

## 1. Who you are collaborating with

**BJ** is the human you work with. Address him by name. BJ + Agent = **"the Pair"** — the fundamental unit of this system's collaboration model. Your first durable reference:

- `memory/concept_pair.md` — what the Pair is and why it matters

BJ runs many concurrent agents across the fleet. He does not have time to micromanage. The following feedback memories are load-bearing for collaboration style — read them first:

- `memory/feedback_design_partner.md` — terse, convicted, defends positions
- `memory/feedback_take_initiative.md` — report-don't-ask on non-architectural calls
- `memory/feedback_precheck_no_ask.md` — run `/precheck` automatically when work is done
- `memory/feedback_stop_asking.md` — don't re-ask after precheck + engage
- `memory/feedback_no_time_nagging.md` — do not comment on session length or hour

---

## 2. What you are working on

The headline project is a **wave-pattern SDLC pipeline** built as Claude Code skills + Model Context Protocol (MCP) servers. The pipeline takes a design intent (via `/ddd` event storming or `/devspec create` directly), compiles it into an executable Plan, decomposes the Plan into Waves of parallel Stories, and executes those Stories via orchestrated parallel sub-agents.

Orient on the architecture via these, in order:

1. `docs/SDLC-VISION.md` — the founding design vision (why skills-as-markdown → MCP-as-handlers; why "big documents in context" had to go)
2. `docs/concepts.md` — concept inventory (Plan / Phase / Wave / Story / Flight / Epic; Orchestrator / Prime / Flight agent roles)
3. `docs/getting-started.md` — 15-minute hands-on walkthrough
4. `docs/kahuna-devspec.md` — **the canonical Dev Spec** for the KAHUNA wave-pattern execution model; also a worked example of what a Dev Spec looks like when fully populated
5. `docs/skill-reference.md` + `docs/tool-skill-map.md` — what each skill does and which MCP tools it calls
6. `memory/project_sdlc_pipeline.md` — current architecture snapshot (skill chain `/ddd → /devspec → /prepwaves → /wavemachine → /dod`)

---

## 3. The taxonomy you must internalize

The pipeline's vocabulary was locked on 2026-04-26 after a major rework (cc-workflow#499 — "Decouple Phase from Epic"). Get this right on day one:

| Term | Role | Storage |
|---|---|---|
| **Plan** | Top-level pipeline container — synthetic tracking issue with `type::plan` label | GitHub/GitLab issue |
| **Phase** | Sequential ordering unit within a Plan (Phase 1 → 2 → 3) | `.claude/status/phases-waves.json` |
| **Wave** | Batch of Stories executed together (parallel or serial) within a Phase | same file |
| **Story** | Single unit of implementable work | GitHub/GitLab issue with `depends_on` metadata |
| **Flight** | Sub-agent execution of a Story inside a Wave | filesystem bus at `/tmp/wavemachine/...` |
| **Epic** | **PM-layer only.** Optional `epic::N` label for thematic grouping. **The pipeline ignores it.** | label |

Backing memory:

- `memory/decision_plan_phase_epic_taxonomy.md` — full taxonomy decision
- `docs/phase-epic-taxonomy-devspec.md` — the Dev Spec that locked it in (also a great worked example)

**Failure mode to avoid:** using "epic" in pipeline-operational contexts. There is a regression test (`tests/regression/test_no_epic_label_reads.sh`) that enforces this — it runs in CI, and the skill bodies were audited clean in Phase 3 of #499.

---

## 4. The repos in the fleet

You are in `claudecode-workflow` (cc-workflow). There are sibling repos; you will touch several.

### Primary

- **`Wave-Engineering/claudecode-workflow`** (this repo) — skills, `install` script, `docs/`, tests. **The skills live here.**
- **`Wave-Engineering/mcp-server-sdlc`** — Model Context Protocol server exposing 73+ tools the skills call (`wave_init`, `wave_flight_plan`, `spec_get`, `pr_merge`, `commutativity_verify`, etc.). Owned by **tachikoma**.

### Supporting MCP servers

- **`Wave-Engineering/mcp-server-discord`** — `disc_send`, `disc_read` (Discord API proxy for inter-agent announcements)
- **`Wave-Engineering/mcp-server-discord-watcher`** — push-to-agent Discord events
- **`Wave-Engineering/mcp-server-wtf`** — WTF flight recorder (journal, replay)
- **`Wave-Engineering/mcp-server-nerf`** — context budget enforcement

### Target-project examples (you may orchestrate against these)

- `blueshift-docmancer-ui` (GitLab, AnalogicDev) — grimoire's KAHUNA proving-ground
- `blueshift-cue` — cue-ball's project
- `bernie` — deep-scan's chatbot platform

Cross-repo orchestration is a real pattern. See `memory/lesson_cross_repo_wave_orchestration.md` before attempting one — there are seven non-obvious facts you will get wrong otherwise.

---

## 5. How work happens: the pipeline

```
idea → /ddd (optional)       → event storming, domain model
     → /devspec create       → Dev Spec: requirements, phases, waves, stories, DoD
     → /devspec approve      → human gate
     → /devspec upshift      → file all issues (Plan + Stories) with proper bodies
     → /prepwaves            → compute wave plan, persist to .claude/status/
     → /wavemachine          → autopilot: loop /nextwave auto until all waves merged
            or
        /nextwave (x N)      → manual: execute one wave at a time with approval gate
     → trust-score gate      → commutativity + CI + reviewer + trivy
     → kahuna→main merge     → final integration
     → /dod                  → Definition of Done verification against Deliverables Manifest
```

**Skill bodies to read when you have time** (not all at once — on demand):

- `skills/wavemachine/SKILL.md` — the autopilot loop
- `skills/nextwave/SKILL.md` — single-wave execution with Orchestrator/Prime/Flight protocol
- `skills/prepwaves/SKILL.md` — wave planning
- `skills/devspec/SKILL.md` — Dev Spec creation + approval + upshift
- `skills/precheck/SKILL.md` — pre-commit gate (includes KAHUNA sandbox auto-approval path)
- `skills/issue/SKILL.md` — structured issue creation with proper templates

---

## 6. Architectural patterns you must recognize

These are the "why the code looks this way" load-bearing patterns. Each has a memory file with the rationale.

| Pattern | Memory | Why it exists |
|---|---|---|
| **Orchestrator / Prime / Flight** | `decision_wavemachine_v2.md`, `lesson_cc_subagent_tools.md` | CC sub-agents lack the `Agent` tool — only the top-level session can spawn parallel sub-agents. Prime plans; Orchestrator spawns Flights. |
| **Filesystem message bus** | `decision_wavemachine_v2.md` | Orchestrator context stays O(1) per flight regardless of Flight output size. All flight artifacts at `/tmp/wavemachine/<repo>/wave-<N>/`. |
| **KAHUNA sandbox** | `docs/kahuna-devspec.md`, `memory/decision_plan_phase_epic_taxonomy.md` | Flights PR to a per-Plan `kahuna/<plan_id>-<slug>` integration branch, not `main`. `/precheck` auto-approves inside the sandbox. Trust-score gate on the final `kahuna→main` merge. |
| **Plan issue body/comments split** | `pattern_plan_issue_body_comments_split.md` | Body = frozen post-approval. Runtime state (Decision Ledger, status updates, lifecycle events) = typed-prefix comments (`[ledger D-NNN]`, `[status ...]`, `[phase-start ...]`, etc.). Platform enforces append-only. |
| **Exhaustive Legal Exits** | `pattern_exhaustive_legal_exits.md` | Every autonomy-loop skill body has a closed enumeration of legal halt conditions + explicit non-exits list. Agents do not invent new halt conditions. |
| **Concerns Channel** | `pattern_concerns_channel.md` | When unease doesn't match any Legal Exit: post `[concern]` comment + Discord ping, then **continue** the loop. The concern is durable; the human responds async. |
| **CHANGELOG fragment aggregation** | `pattern_changelog_fragment_aggregation.md` | Flights write `CHANGELOG.fragment.md` per issue; Prime(post-wave) aggregates into one PR. Unblocks parallelism when multiple stories would otherwise serialize on CHANGELOG.md. |
| **Cross-repo wave orchestration** | `lesson_cross_repo_wave_orchestration.md` | Pre-create worktrees of target repo; point sub-agents via prompt; `-R <owner/repo>` on every `gh` call. |
| **Handler registry + test auto-discovery** | `decision_handler_registry.md` | Eliminates per-story shared-file conflicts in MCP servers via `import.meta.glob` (codegen'd for Bun). |

---

## 7. Governing principles (short list, high leverage)

Internalize these two; they resolve most "should I stop or continue?" questions:

- `memory/principle_user_attention_is_the_cost.md` — the scarce resource this system protects is the human's attention, not wall-clock safety. Stopping is expensive.
- `memory/principle_cost_asymmetry_continue_vs_exit.md` — continuing costs revertible commits; exiting costs unrecoverable wall-clock. Prefer continue when unsure; use the Concerns Channel as pressure valve.

---

## 8. How to commit: the gate discipline

**Never commit without `/precheck`.** When your work is done, run `/precheck` immediately — do not ask permission. The skill runs the full checklist (validation, trivy, code-reviewer agent dispatch, Discord + vox announcement), then:

- **On `main`-targeted branches:** stops and waits for `/scp`, `/scpmr`, or `/scpmmr` from the human.
- **On `kahuna/<N>-*` branches (KAHUNA sandbox):** emits `[AUTO-APPROVED: kahuna sandbox]` sentinel and auto-chains to `/scpmmr`. No human STOP.

Reference:

- `skills/precheck/SKILL.md` — authoritative detection logic
- `CLAUDE.md` — the project-instructions contract

---

## 9. The institutional knowledge layer (memory)

Your project memory lives at `~/.claude/projects/-home-bakerb-sandbox-github-claudecode-workflow/memory/`. It auto-loads at session start via `MEMORY.md`. Categories:

- **`concept_*`** — core vocabulary (the Pair, etc.)
- **`decision_*`** — architectural decisions with rationale
- **`pattern_*`** — reusable patterns (body/comments split, Exhaustive Legal Exits, Concerns Channel, etc.)
- **`principle_*`** — foundational principles (user attention, cost asymmetry)
- **`policy_*`** — mechanical rules (Wave-Engineering merge config)
- **`lesson_*`** — debugging gotchas and pitfalls learned the hard way
- **`feedback_*`** — user preferences and collaboration style
- **`project_*`** — snapshots of ongoing projects (upcoming work, SDLC architecture, etc.)
- **`ref_*`** — pointers to external systems (Discord IDs, external tools)
- **`pref_*`** — operational preferences (install tools, etc.)
- **`user_*`** — user-level context

**Always check `MEMORY.md` before adding a new memory file.** If a similar one exists, update it in place. Keep `MEMORY.md` index entries to one line under ~150 characters.

### High-value memory files to read early

- `memory/project_upcoming_work.md` — what the fleet is working on RIGHT NOW (starts stale within a few days; verify against git before acting)
- `memory/decision_plan_phase_epic_taxonomy.md` — locked 2026-04-26 taxonomy
- `memory/lesson_cc_subagent_tools.md` — CC's sub-agent tool distribution (critical for any work that spawns Agents)
- `memory/lesson_cross_repo_wave_orchestration.md` — seven non-obvious facts
- `memory/policy_wave_engineering_merge_config.md` — all Wave-Engineering repos require merge-queue + auto-merge
- `memory/lesson_repo_label_taxonomies.md` — label families differ per repo; verify before batch-filing

---

## 10. Operational grab bag (read on hit)

These are indexed here so when you hit the failure mode, you know where to look:

### MCP servers and tooling

- `memory/lesson_mcp_gotchas.md` — session IDs, binary updates, context patterns
- `memory/lesson_mcp_binary_swap_requires_cc_restart.md` — swapping the MCP binary ≠ refreshing the tool registry
- `memory/lesson_mcp_install_path_skew.md` — `dist/` rebuild vs `~/.local/bin/` subprocess
- `docs/mcp-scoping.md` — scope rules; project vs user vs system
- `docs/mcp-logging-standard.md` — structured logging across all 5 MCP servers

### Git / PR / merge

- `memory/lesson_merge_queue_gh.md` — `gh pr merge` silently fails on merge-queue repos; use `pr_merge` MCP tool
- `memory/lesson_pr_merge_wait_regression.md` — `pr_merge_wait` queue-detection edge case
- `memory/lesson_pr_wait_ci_broken.md` — local `gh` CLI quirks; fall back to `ci_wait_run(ref=branch)`
- `memory/lesson_setup_bun_npmrc_auth.md` — setup-bun action drops GitHub Packages auth
- `memory/lesson_gh_search_org_wide.md` — fleet-wide issue freshness via `gh search issues --owner`
- `docs/operations/merge-queue-checklist.md` — end-to-end merge-queue dry-run runbook (config existence ≠ config works)

### Wave-pattern specifics

- `memory/lesson_wave_status_commands.md` — wave-status CLI subcommands
- `memory/lesson_wave_flight_plan_schema.md` — `wave_flight_plan` expects bare array, not wrapped object
- `memory/lesson_wave_parser_gotchas.md` — section-name rigidity in sdlc-server's parser
- `memory/lesson_wave_superseded_detection.md` — how Flights handle "already fixed" cleanly

### Platform / external systems

- `memory/ref_discord_server.md` — Oak and Wave guild/channel IDs
- `memory/ref_scream_hole.md` — Discord API proxy
- `memory/ref_clawback.md` — session replay tool
- `memory/ref_asset_management.md` — DVC + Cloudflare R2 for binary assets
- `memory/lesson_analogicdev_gitlab_setup.md` — singular `doc/` branch prefix, verified-email requirements
- `memory/lesson_gitlab_smoke_test.md` — pipeline-changing smoke test pattern

---

## 11. The "current state of things" shortcut

When you resume a session after compaction or you are a fresh agent brought in to pick up where someone left off:

1. **Run `/engage`** — loads memory, reads CLAUDE.md, summarizes the active plan.
2. **Read `memory/project_upcoming_work.md`** — what's in-flight.
3. **`git log --oneline -10` + `git branch -a | head -20`** — verify memory against the codebase.
4. **Check `.claude/status/`** for any active wave plan (`phases-waves.json`, `state.json`).
5. **Look at `.claude/plans/session-state.md`** if you were cryo'd — that's the hand-off doc from the prior session.

Memory ages fast. If a memory file names a specific function, PR, or flag: verify it still exists before recommending it. See the "Before recommending from memory" section of the auto-memory system instructions in your system prompt.

---

## 12. What to expect from BJ

- Terse, direct, convicted. Pushes back when he disagrees. Expects the same from you.
- Hates "what if something goes wrong?" hedging. Name the concrete concern or proceed.
- Defaults to trust; follows up with correction if needed. Treat corrections as memory updates.
- Uses voice slash commands liberally. Do not take them as open-ended prompts — execute them directly.
- Does not want commentary on the time of day or session length. Just work.
- Runs 5+ concurrent agents. Your session is one of many. Be brief in surfaces that compete for his attention.

---

## 13. First session checklist

Before your first commit in any session:

- [ ] Run `/engage` — confirms rules, loads memory, summarizes plan
- [ ] If no Dev-Name/Dev-Avatar yet: run `/name` to pick one, announced via Discord
- [ ] Read `memory/project_upcoming_work.md`
- [ ] Verify `git status` + `git branch --show-current` match your expectation
- [ ] Know which repo you are in and whether you are cross-repo-orchestrating

And before your first **any action that touches remote**:

- [ ] `/precheck` ran and passed
- [ ] Human STOP honored (unless KAHUNA sandbox, which auto-approves)

---

## 14. Further reading by topic

If you want to go deeper on a specific area, these are the best long-form docs:

- **Origins of the architecture:** `docs/SDLC-VISION.md`
- **KAHUNA execution model:** `docs/kahuna-devspec.md`
- **DDD → Dev Spec mapping:** `docs/DDD-to-devspec-protocol.md`
- **Dev Spec authoring:** `docs/devspec-template.md`
- **Plan tracking issue shape:** `docs/plan-issue-template.md`
- **Wavemachine v2 design:** `docs/wavemachine-v2-integration.md`, `memory/decision_wavemachine_v2.md`
- **Handler registry pattern (MCP servers):** `memory/decision_handler_registry.md`
- **Adapter retrofit (tachikoma's ongoing work):** `memory/decision_platform_adapter_retrofit.md`
- **Troubleshooting:** `docs/troubleshooting.md`

---

## 15. Done. Now start.

Run `/engage` in your current project. Everything above exists to make that first twenty minutes productive rather than exploratory. Come back to this doc when you hit a failure mode it indexes — not when you need permission to act.

The system is designed to run. Run it.
