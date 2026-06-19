# Automated Background Testing — Sketchbook

> **Status:** Pre-`/devspec` working notes. This file captures decisions
> agreed during the 2026-05-06/07 design conversation; it is the input to
> `/devspec` (which will produce the formal Dev Spec for the harness Plan).
>
> **Scope of this Plan vs. the parent Epic.** Plan: Gamma elaborates
> Epic #626's **sub-issue #1** ("`/wavemachine` integration harness —
> boots toy plan, asserts canonical artifacts in CI"). It is the
> *foundation* sub-issue of #626, large enough to warrant its own Plan
> tracking issue and `/devspec` walk. Epic #626's other eight sub-issues
> (daemon-process coverage, canonical-line enforcement, bus-path-scheme
> validation, substring→exact-line audit, CHANGELOG-fragment guard,
> harness-backgrounding instrumentation, kahuna-parity preflight,
> auto-merge retry policy) are independent Stories that can be filed
> directly under #626 via `/issue feature --epic 626` without their own
> Plan tracking issues — they are scoped narrowly enough to execute as
> single Stories. Some Plan: Gamma tests (notably 4.6 cross-repo and
> 4.1's `pr_merge` assertion) provide *fixture infrastructure* the
> sub-issue-#8/#9 production fixes will validate against; the harness
> and the production hardening are complementary, not redundant.
>
> **Related:** Epic #626 (cc-workflow) — automated testing gap follow-up
> from the Plan #607 (Beta) debrief.

---

## Why this exists

Plan #607 (Beta) shipped in one autonomous wave-pattern campaign and
surfaced ~8 operational failure modes that were only caught by the
operator hand-recovering during the run itself. Net result of the
campaign: ~15 issues closed, ~15 follow-up issues opened — close to
zero net progress on confidence in the system.

The pattern is "campaign-as-test-of-last-resort": every fix shipped
without harness coverage adds to the surface that needs hand-validation
in the next campaign. The fix for this is a **runnable test kit that
exercises every feature and significant failure-mode of the wave-pattern
pipeline**, on-demand or nightly, unattended.

This sketchbook is the foundational design for that harness.

---

## What we are testing

The wave-pattern pipeline, end-to-end:

- **`mcp-server-sdlc`** — 74 handlers across wave lifecycle, planning,
  spec validation, flight partitioning, drift, commutativity, the
  PlatformAdapter (PR/MR ops), CI ops, campaign ops, IBM gate, etc.
- **`mcp-server-discord`**, **`mcp-server-nerf`**, **`mcp-server-wtf`** —
  the rest of the MCP fleet.
- **`claudecode-workflow`** — orchestration skills (`/precheck`,
  `/issue`, `/devspec`, `/assesswaves`, `/prepwaves`, `/nextwave`,
  `/wavemachine`, `/scp*`, `/mmr`, ...).
- **CLIs** — `wave-status`, `generate-status-panel`, `mcp-log`.
- **Bus scripts** — `scripts/wavebus-*{wave-init,flight-finalize,
  changelog-aggregate,wave-cleanup}`.
- **Wave-pattern v2 architecture** — Orchestrator / Prime / Flight
  protocol, filesystem bus, worktree management, KAHUNA sandbox,
  trust-score gate (commutativity_verify + ci_wait_run + code-reviewer
  Agent + trivy fs).

---

## Tier structure

Test coverage is organized in tiers, cheap-to-expensive. A nightly run
executes all tiers; on-demand can filter by tier.

| Tier | Wall-clock | Determinism | Requires CC harness | Nightly | On-demand default |
|------|-----------|-------------|---------------------|---------|-------------------|
| 0 — static integrity      | <10 s     | Pure         | No                | ✓ | ✓ |
| 1 — unit                  | <1 min    | Pure         | No                | ✓ | ✓ |
| 2 — MCP roundtrip         | 1–5 min   | Mostly       | No                | ✓ | ✓ |
| 3 — skill grain           | 5–15 min  | Mostly       | Stubbed Agent     | ✓ | ✓ |
| 4 — e2e campaign          | 30–90 min | Real-world   | Yes (real Agent)  | ✓ | opt-in |
| 5 — chaos / fault-injection | 30–60 min | Mostly     | Yes (mocked)      | ✓ | opt-in |
| 6 — observability         | <5 min    | Pure         | No                | ✓ | ✓ |

> **Note on the "Nightly" column.** Checkmarks describe the *eventual
> steady-state* coverage, not the v0 reality. v0 ships Tier 0/1/4/6;
> Tiers 2/3/5 are deferred to follow-up Plans. Until they ship, the
> nightly run is the v0 subset.

**Sequencing decision (2026-05-07):** Tier 1 first (runtime shakedown),
then Tier 4 (highest strategic value — campaign-as-test). Tiers 2 and 3
are deliberately deferred — they are unit-style coverage, but operator
pain from Plan #607 was almost entirely at the e2e seam, not in the
units. Tier 4 incidentally exercises ~80% of MCP tools and ~60% of skills
inline, so we are not losing coverage; we are sequencing it. Tiers 2/3
become "backfill on bisection pain" — added when a Tier 4 failure proves
expensive to localize.

The cost we accept: when Tier 4 fails, bisection is slower without unit
fixtures underneath. Mitigated by:
- Heavy reliance on `mcp-log` telemetry — every tool call timestamped and
  correlatable.
- Tier 4 runner gets a `--keep-state` flag preserving bus dirs,
  worktrees, partial logs for forensic replay instead of nuking on
  failure.
- A `--bisect <failure-tag>` mode that re-runs only the suspect step.

---

## Decisions (locked)

| # | Decision | Choice |
|---|---|---|
| 1 | Harness repo location | New repo `Wave-Engineering/ccwork-testtarget` on GitHub |
| 2 | Runner language | Python + pytest |
| 3 | GitHub fixture repos | Private, under `Wave-Engineering/`, run-id-prefixed |
| 4 | GitLab fixture project | `gitlab.com/testtarget/harness-fixture` (proposed name; namespace is BJ's existing `gitlab.com/testtarget/`) |
| 5 | Cost budget | $4–8 / nightly run in Anthropic API tokens — acceptable. Anchor: assumes Opus 4.x at current pricing across ~3 Tier-4 e2e campaigns of ~30-min wall-clock each. Exact derivation deferred to `/devspec` walk. |

### Rationale notes

- **Python over Bun** — the harness talks to MCP servers via the same
  JSON-RPC stdio protocol Claude Code does. This is a *feature*, not a
  compromise: it tests the MCP protocol surface (which is what fails)
  rather than internals. pytest's fixture model maps cleanly to our
  needs (fixture-repo lifecycle, MCP server start/stop, bus state setup,
  snapshot diffing).
- **GitLab parity from day one** — most platform-divergence bugs
  (`skip_train` semantics, approval-rule `protected_branch_ids` scoping,
  GraphQL auto-merge race shape) only surface against real GitLab. A
  GitHub-only Tier 4 would produce a false-confidence nightly: green
  every morning while GitLab campaigns silently break in the field.
  Cost is small if the runner is platform-parameterized from the start
  (one `@pytest.mark.parametrize` axis).
- **Dedicated harness repo over co-location** — the harness is a
  consumer of cc-workflow + MCP fleet, not part of either. Same
  separation-of-concerns logic by which `mcp-server-sdlc` is its own
  repo. Co-location's only benefit is "fewer repos," and we already have
  a fleet.
- **Private fixture repos** — fine-grained PAT scoped to harness-prefixed
  names only. No org-admin, no other repos. Surgical permissions.
- **Naming `ccwork-testtarget`** — parallels `gitlab.com/testtarget/`
  namespace.

---

## v0 scope (the first Plan under Epic #626)

Plan: **"Plan: Gamma — Wave-pattern test harness foundation"** under
Epic #626. Two phases, executed serially.

### Phase 1 — Tier 1 runtime (~2 weeks of stories)

- Harness repo bootstrap (`Wave-Engineering/ccwork-testtarget`) — pytest
  skeleton, report assembler, teardown helpers, fine-grained PAT auth
  setup.
- Tier 0 static checks — CLIs on PATH, MCP `tools/list` snapshot,
  skill frontmatter parse, MEMORY.md integrity, WAVE_AXIOMS.md presence.
- Tier 1 wiring for each MCP server's `bun test` suite (sdlc, discord,
  nerf, wtf) — harness clones, installs, runs each, collects results.
- Tier 1 bus-script unit tests (`wave-init`, `flight-finalize`,
  `changelog-aggregate`, `wave-cleanup`) — each in `tmpdir`, never
  homedir (per `lesson_destructive_test_homedir.md`).
- Tier 1 status-panel snapshot test — feed known fixture state JSON,
  diff against captured HTML output (regression on cc#631-class bugs).
- Nightly cron + Discord report posting to a dedicated `#harness-test`
  channel.

**Done when:** nightly runs, posts a report, all green on a freshly-
installed cc-workflow setup.

### Phase 2 — Tier 4 v0 (~3 weeks of stories)

- Fixture-repo lifecycle — per-run-id-prefixed create + prefix-scoped
  teardown. GitHub fixtures under `Wave-Engineering/`, GitLab fixture
  under `gitlab.com/testtarget/`.
- **Test 4.1** — single-flight, single-issue wave end-to-end against
  GitHub fixture. The smoke test; if this fails, the whole pipeline is
  broken.
- **Test 4.8** — single-flight, single-issue wave end-to-end against
  GitLab fixture. Parametrized 4.1; covers `skip_train` semantics,
  GitLab merge-train warning, approval-rule scoping.
- **Test 4.6** — cross-repo wave end-to-end (GitHub → GitHub). Covers
  worktree pre-creation, `gh -R` scoping, dual kahuna branches.
- Telemetry replay tooling — given a failed Tier 4 run, reconstruct the
  timeline from `~/.claude/logs/mcp.jsonl` and bus state into a single
  forensic doc.
- Tier 4 `--keep-state` mode + `--bisect <failure-tag>` mode.

**Done when:** all three Tier 4 tests run nightly, fail-loud on any
documented failure mode, produce a forensic doc on failure.

### Out of scope for v0 (deferred to follow-up work)

**Deferred test tiers:**

- Tiers 2 / 3 — backfill on bisection pain (added when Tier 4 failure
  proves expensive to localize).
- Tier 5 chaos / fault-injection — separate follow-up Plan once Tier 4
  v0 proves the runner shape.

**Tier 4 deferred tests (full inventory):**

- **4.2** — Multi-flight parallel (1 wave, 3 conflict-free issues, single
  tool-use-block parallel Flight spawn).
- **4.3** — Multi-flight with file conflict (`flight_partition` produces
  2 flights, 2 conflicting issues serialized).
- **4.4** — Multi-wave dependency chain (3 serial waves,
  `wave_previous_merged` gating).
- **4.5** — Multi-phase Plan (2 phases, 4 waves, phase-boundary walking).
- **4.7** — KAHUNA on non-`main` base ref (e.g., `release/<ver>`;
  cc#597 regression target).

These extend 4.1 / 4.6 / 4.8 once the v0 runner shape is proven. Each
adds incremental coverage on a specific orchestration shape.

**Other Epic #626 sub-issues (independent Stories under #626):**

These are *not* part of Plan: Gamma — they ship as standalone Stories
filed directly under Epic #626 via `/issue feature --epic 626`:

- Sub-issue #2 — `wave-watcher` daemon test/installer wiring.
- Sub-issue #3 — Orchestrator-side canonical-line enforcement.
- Sub-issue #4 — Prime(pre-wave) bus-path-scheme assertion.
- Sub-issue #5 — Substring → exact-line test audit.
- Sub-issue #6 — `CHANGELOG.fragment.md` regression guard.
- Sub-issue #7 — Silent Agent-backgrounding instrumentation.
- Sub-issue #8 — `wave_preflight` kahuna-parity assertion.
- Sub-issue #9 — `pr_merge` retry policy for `enablePullRequestAutoMerge`
  race.

Plan: Gamma's tests 4.1 / 4.6 / 4.8 provide the fixture infrastructure
that sub-issues #8 and #9 need to validate their production-side fixes.
The harness and the production hardening are complementary, not
overlapping — the harness *exercises* the system, the sub-issue fixes
*harden* it.

**Acknowledged untestable surfaces:** prompt regression, cost regression,
real-Discord-channel state, behavioral effectiveness of WAVE_AXIOMS on
sub-agent compliance. These are model-fidelity / observational concerns,
not deterministic-CI surfaces.

---

## Tier 1 — what we test (concrete)

### Tier 0 (rolled into Tier 1's runner harness)

- Required CLIs on PATH: `wave-status`, `generate-status-panel`,
  `mcp-log`, `gh`, `glab`, `bun`, `trivy`, `jq`.
- Each MCP server in `~/.config/claude-code/mcp.json` responds to
  `tools/list`. Tool count matches a snapshot (regression catches
  accidental tool removal).
- `WAVE_AXIOMS.md` exists, parses, contains all 9 axioms.
- All skill files have valid frontmatter; tools they reference exist;
  cross-skill links resolve.
- `MEMORY.md` index entries point to existing files; every file in
  `memory/` is referenced.
- CLAUDE.md / CLAUDE.md-loaded sub-files load cleanly.

### Tier 1

- `mcp-server-sdlc bun test` — existing suite, run as-is.
- `mcp-server-discord`, `mcp-server-nerf`, `mcp-server-wtf` test suites.
- Bus scripts (each gets its own pytest module, tmpdir only):
  - `wave-init <slug> 1 1` creates expected directory tree, idempotent
    on second invocation.
  - `flight-finalize` atomically renames `results.md.partial` →
    `results.md`, writes `DONE` with PASS/FAIL.
  - `changelog-aggregate` aggregates 3 fragments into one CHANGELOG
    without duplication, handles "no fragments" gracefully.
  - `wave-cleanup` removes the per-wave bus dir, leaves siblings alone.
- Status-panel snapshot test — fixture state JSON in, HTML out,
  byte-equal to captured snapshot (regression on dict-vs-None bugs
  like cc#631).

---

## Tier 4 — what we test (v0)

### Test 4.1 — Single-flight, single-issue (GitHub)

Plan with 1 Phase, 1 Wave, 1 Story (touch-one-file). `/wavemachine`
runs to terminal. Asserts:

- Kahuna branch created via `wave_init`.
- Kahuna→main MR opened by `wave_finalize`.
- Gate runs all 4 trust signals concurrently (single tool-use block).
- All 4 signals pass.
- `pr_merge` lands the kahuna→main MR.
- Observability events landed in `~/.claude/logs/mcp.jsonl`.
- Status panel reflects terminal state.
- Teardown removes worktrees, kahuna branch, fixture issues.

### Test 4.8 — Single-flight, single-issue (GitLab)

Parametrized 4.1 against `gitlab.com/testtarget/harness-fixture`.
Asserts everything 4.1 asserts, plus:

- `glab` adapter parity for `pr_create`, `pr_merge`, `pr_status`,
  `pr_diff`, `pr_files`, `pr_wait_ci`, `pr_merge_wait`.
- Merge-train-warning emitted to Discord before `pr_merge`.
- Approval rule scoped via `protected_branch_ids` correctly permits
  the auto-merge.
- `skip_train: true` interpreted per platform — silent passthrough on
  GitLab (cannot bypass merge train), bypass-queue on GitHub.

### Test 4.6 — Cross-repo wave (GitHub → GitHub)

Plan in repo A, Stories in repo B. Asserts:

- Pre-created worktrees in repo B (one per issue).
- `gh -R` scoping on every command (no cwd-based detection).
- No `isolation: "worktree"` flag misuse — worktree paths passed via
  prompt.
- Kahuna branches in BOTH repos.
- Both kahuna→main MRs land.
- `wave-status` state lives in master plan repo (repo A), not target
  repo (repo B).
- Teardown unlocks worktrees before force-removal (single `--force`
  fails on locked worktrees).

---

## Open questions (none load-bearing for `/devspec`)

These can be decided during `/devspec` walk or in early Phase 1
stories — they do not block the Plan-tracking-issue creation.

1. Exact PAT scoping shape — is "fine-grained PAT scoped to
   `Wave-Engineering/ccwork-testtarget*` and `Wave-Engineering/
   harness-target-*`" sufficient, or do we need a separate PAT for
   fixture-repo creation vs. the harness repo's own CI?
2. Discord channel naming — `#harness-test` vs. `#wave-status` vs.
   dedicated `#harness-nightly`? Likely the latter, to avoid noise on
   `#wave-status` during nightly runs.
3. Test ordering within a tier — independent (parallel via
   `pytest-xdist`) vs. ordered? Tier 1 should be fully parallel; Tier 4
   tests need fixture-repo isolation per test (per-run-id prefixing)
   but can run in parallel against distinct fixtures.
4. Acceptance criterion for "ship the harness." Proposed: every open
   follow-up bug from Plan #607 has a corresponding test in this kit,
   AND that test currently fails on `main`. Then we fix the bugs in-band
   with harness build, watch tests turn green, ship together.

---

## Next move

Proceed to `/devspec` for **"Plan: Gamma — Wave-pattern test harness
foundation"** under Epic #626 with the scope above. The Dev Spec walk
will produce:

- The frozen Plan tracking-issue body (Goal / Scope / Plan-level DoD /
  Phases / References).
- The Phase 1 and Phase 2 sub-issue inventory (one Story per work item
  enumerated above).
- Cross-references to memory files, CLAUDE.md sections, and the
  failure-mode lessons this harness is designed to catch.

The Dev Spec output supersedes this sketchbook for execution; this file
remains as the design-conversation artifact for posterity.
