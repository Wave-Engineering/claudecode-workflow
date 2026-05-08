# Development Specification: ccwork-testtarget

**Plan:** [#641](https://github.com/Wave-Engineering/claudecode-workflow/issues/641) — Plan: Wave-pattern test harness foundation
**Parent Epic:** [#626](https://github.com/Wave-Engineering/claudecode-workflow/issues/626) — automated testing gap follow-up
**Sketchbook:** [`docs/automated-background-testing-sketchbook.md`](./automated-background-testing-sketchbook.md) (PR [#640](https://github.com/Wave-Engineering/claudecode-workflow/pull/640))
**Walked:** 2026-05-07 / 2026-05-08 (Loomweaver 🪶, cc-workflow)

<!-- DEV-SPEC-APPROVAL
approved: true
approved_by: BJ
approved_at: 2026-05-08T05:02:58Z
finalization_score: 8/8
-->

---

## Table of Contents

1. [Problem Domain](#1-problem-domain)
2. [Constraints](#2-constraints)
3. [Requirements (EARS Format)](#3-requirements-ears-format)
4. [Concept of Operations](#4-concept-of-operations)
5. [Detailed Design](#5-detailed-design)
6. [Test Plan](#6-test-plan)
7. [Definition of Done](#7-definition-of-done)
8. [Phased Implementation Plan](#8-phased-implementation-plan)
9. [Appendices](#9-appendices)

---

## 1. Problem Domain

### 1.1 Background

The wave-pattern pipeline is a multi-component system spanning four MCP servers (`mcp-server-sdlc`, `mcp-server-discord`, `mcp-server-nerf`, `mcp-server-wtf`), the `claudecode-workflow` skill set, three CLIs (`wave-status`, `generate-status-panel`, `mcp-log`), four bus scripts under `scripts/wavebus/`, and the v2 Orchestrator/Prime/Flight protocol with KAHUNA sandbox. Until now, automated testing has covered unit-level handler correctness inside each MCP server's `bun test` suite plus shape-level grep on documentation and skill bodies. There is no automated test layer that exercises the system as a system — every `/wavemachine` campaign is the integration test of last resort.

Plan #607 (Beta) ran one autonomous campaign and surfaced ~8 operational failure modes during the run itself: Prime sub-agent stalls, watchdog kills, harness backgrounding via cc#490, bus-path miswrite, non-canonical Flight returns, `CHANGELOG.fragment.md` merge conflicts, auto-merge race on `enablePullRequestAutoMerge`, ORACLE_REQUIRED commutativity verdicts on routine multi-issue merges. Each was caught by orchestrator-side hand-recovery during the campaign, not by automation. The post-campaign reviewer pass surfaced three more in the kahuna→main MRs: substring-test anti-pattern (sdlc#415's bullet `—`), 3-fold integration gap on wave-watcher (sdlc#578: tests not wired, smoke test not wired, installer not invoked), and doc-string drift on `pr_wait_ci` (sdlc#416). Net: ~15 follow-up issues opened against ~15 closed. Net confidence change: ≈0.

This Dev Spec is anchored to **Plan: Gamma (#641)**, which elaborates Epic #626's sub-issue #1 — the integration-harness foundation. The other eight sub-issues of Epic #626 ship as standalone Stories under that Epic, not as part of this Plan.

### 1.2 Problem Statement

The wave-pattern pipeline has no test layer between unit-grain handler tests and live multi-hour `/wavemachine` runs. The campaign-as-test-of-last-resort pattern is structurally costly: every campaign re-discovers the same operational failure modes, and every fix shipped without harness coverage adds to the surface that needs hand-validation in the next campaign. The cost is paid in operator wall-clock during live campaigns, not in compute, which means it does not amortize.

### 1.3 Proposed Solution

Ship a runnable test harness — `Wave-Engineering/ccwork-testtarget`, Python + pytest — that exercises the wave-pattern pipeline at two grains:

- **Tier 1 (unit)** — wrap each MCP server's existing `bun test` suite, the four bus scripts, and the status-panel generator's HTML output. Cheap, deterministic, fast.
- **Tier 4 (end-to-end campaign)** — three platform-parameterized tests (4.1 GitHub single-flight, 4.8 GitLab single-flight, 4.6 cross-repo GitHub→GitHub) that drive `/wavemachine` against per-run-id-prefixed fixture repos, assert every canonical artifact, and tear down state on completion.

Tiers 0 (static) and 6 (observability) are folded into Tier 1's runner. Tiers 2 (per-MCP-tool roundtrip), 3 (skill-grain), and 5 (chaos / fault-injection) are deferred to follow-up Plans. The harness runs nightly via cron on a dedicated host and on-demand via a `--tier <list>` CLI flag. A `--keep-state` mode preserves bus dirs / worktrees / partial logs on failure for forensic replay; a `--bisect <step>` mode re-runs only the suspect step.

### 1.4 Target Users

| User | Role | Primary interaction |
|------|------|---------------------|
| **Harness operator** (BJ today; future fleet ops) | Runs nightly cron, reads Discord report, opens forensic docs on red runs | Configures `ccwork-testtarget` repo, holds the fine-grained PAT, owns the cron host |
| **Plan authors** | Write Dev Specs; consume harness signal as the "is the pipeline working?" indicator | Read nightly report; gate Plan launches on green status |
| **Wave Orchestrator agents** | Indirectly benefit when their production fixes are validated by Tier 4 regression tests | Read forensic docs after their own campaigns fail; treat harness as living regression set |
| **`/wavemachine` debuggers** | Use forensic-replay tooling to bisect when a campaign breaks unexpectedly | `--keep-state` + `--bisect` flags; `mcp-log` event correlation |
| **Plan #607 follow-up issues** (cc#629–#638, sdlc#425) | Each becomes a red Tier 4 fixture target — turning green when the production fix lands | Filed as tracked test fixtures; documented in §6 |

### 1.5 Non-Goals

- **NG-01 — Tier 2 / Tier 3 unit-grain coverage.** Per-MCP-tool roundtrip tests and skill-grain tests are valuable but addressable as backfill on bisection pain.
- **NG-02 — Tier 5 chaos / fault-injection.** Deliberate failure-injection tests are a separate follow-up Plan once the v0 runner shape proves out.
- **NG-03 — Tier 4 tests 4.2–4.5 / 4.7.** Multi-flight parallel, multi-flight with file conflict, multi-wave dependency chain, multi-phase Plan, and KAHUNA-on-non-`main`-base are separate work; they extend 4.1 / 4.6 / 4.8.
- **NG-04 — Epic #626 sub-issues #2 through #9.** Daemon-process coverage, canonical-line enforcement, bus-path-scheme assertion, substring → exact-line audit, CHANGELOG-fragment guard, harness-backgrounding instrumentation, kahuna-parity preflight, and `pr_merge` retry policy ship as standalone Stories under Epic #626 via `/issue feature --epic 626`.
- **NG-05 — Behavioral / model-fidelity testing.** Whether sub-agents *follow* WAVE_AXIOMS, prompt regression, cost regression, real-Discord-channel state are observational concerns, not deterministic CI.
- **NG-06 — Re-architecture of the wave-pattern.** This Plan tests the existing pipeline; it does not redesign it.

---

## 2. Constraints

### 2.1 Technical Constraints

- **TC-01 — Runner stack: Python + pytest.** The harness MUST be implemented in Python with pytest as the test framework.
- **TC-02 — MCP server interaction is JSON-RPC stdio only.** The harness MUST drive each MCP server as a subprocess via the same JSON-RPC stdio protocol Claude Code uses. Direct in-process import of MCP server code is forbidden.
- **TC-03 — Filesystem isolation: tmpdir or env-override only.** Tests MUST NOT touch real `$HOME`, `~/.claude/`, `~/.config/claude-code/`, or any path used by a live Claude Code session or another harness instance. All filesystem state lives under a pytest-managed `tmp_path` or a fixture-injected, env-overridden directory. Source: `lesson_destructive_test_homedir.md`.
- **TC-04 — Fixture artifact isolation: per-run-id prefix.** Every Tier 4 fixture creates GitHub/GitLab artifacts with a unique run-id prefix. Teardown deletes by prefix only.
- **TC-05 — Fixture residency: `Wave-Engineering/` (GitHub, private) and `gitlab.com/testtarget/` (GitLab).** All fixture repos / projects live in these namespaces only.
- **TC-06 — Auth via fine-grained, scoped tokens.** GitHub PAT scoped to read+write on `Wave-Engineering/ccwork-testtarget*` and `Wave-Engineering/harness-target-*` only — no org-admin, no other-repo write. GitLab token scoped to `gitlab.com/testtarget/`.
- **TC-07 — No Docker-in-Docker. If DinD is unavoidable, only on self-hosted runners.** The harness MUST NOT use Docker-in-Docker — a Docker daemon nested inside another Docker daemon. Docker on a self-hosted runner is fine; DinD specifically is the prohibited pattern. If a test step genuinely requires nested-Docker semantics, the harness MUST run on a self-hosted runner so the Docker daemon is the host's own — making the situation native Docker, not DinD. GitHub-hosted and GitLab-hosted shared runners MUST NOT be used when DinD would be in the test path.

### 2.2 Product Constraints

- **PC-01 — Unattended nightly execution.** The harness MUST run as a cron job on a dedicated host with zero operator interaction during clean runs. No mid-run prompts.
- **PC-02 — Cost budget: $4–8/night.** Total Anthropic API token cost for one nightly run MUST stay within this band under normal v0 conditions. Sustained overage triggers a Discord notice and is a fail-the-build condition.
- **PC-03 — Forensic-doc-on-failure.** When a Tier 4 test fails, the harness MUST produce a single forensic doc reconstructing the failure timeline from `~/.claude/logs/mcp.jsonl` and bus state.
- **PC-04 — Self-validation contract.** At least one Plan #607 follow-up bug (cc#629–#638, sdlc#425, or successor list) MUST have a corresponding red Tier 4 test that turns green when the production fix lands.
- **PC-05 — Discord notification: dedicated channel, no `@`-mentions.** Reports go to a dedicated `#harness-test` (or operator-chosen) channel. The post body MUST NOT prefix `@all`, `@<Dev-Team>`, or any `@`-mention.

---

## 3. Requirements (EARS Format)

### 3.1 Tier Execution

- **R-01** — When the harness is invoked nightly via cron, the harness shall execute Tier 0, Tier 1, Tier 4, and Tier 6 in order.
- **R-02** — If any tier produces failures, the harness shall continue executing remaining tiers and report cumulative failures at the end of the run rather than early-exit.
- **R-03** — The harness shall support an on-demand invocation mode that filters by tier via a `--tier <list>` CLI flag.

### 3.2 Fixture Lifecycle

- **R-04** — Before any Tier 4 test runs, the harness shall create per-run-id-prefixed fixture artifacts in `Wave-Engineering/` (GitHub) or `gitlab.com/testtarget/` (GitLab) per the test's platform.
- **R-05** — After every Tier 4 test completes (pass or fail), the harness shall tear down all artifacts created with that test's run-id prefix unless `--keep-state` is set.
- **R-06** — Where `--keep-state` is set, the harness shall skip teardown for *failed* tests, persist the fixture state plus bus dirs and partial logs at a documented filesystem path, and emit the path in the forensic doc.
- **R-07** — The harness shall not create, modify, or delete artifacts in any namespace other than `Wave-Engineering/` and `gitlab.com/testtarget/`.

### 3.3 MCP Server Interaction

- **R-08** — When the harness needs to invoke an MCP tool, the harness shall spawn the MCP server as a subprocess and communicate via JSON-RPC over stdio.
- **R-09** — The harness shall not import any MCP server's source code or compiled bindings directly into the test process.

### 3.4 Tier 0 Static Integrity

- **R-10** — When Tier 0 runs, the harness shall verify each of: required CLIs on PATH (`wave-status`, `generate-status-panel`, `mcp-log`, `gh`, `glab`, `bun`, `trivy`, `jq`); each MCP server in the active config responds to `tools/list`; per-server tool count matches a checked-in snapshot; all skill frontmatter parses; `MEMORY.md` index integrity; `WAVE_AXIOMS.md` presence with 9 axioms.

### 3.5 Tier 1 Unit

- **R-11** — When Tier 1 runs, the harness shall execute each of: `mcp-server-sdlc bun test`; `mcp-server-discord bun test`; `mcp-server-nerf bun test`; `mcp-server-wtf bun test`; bus-script unit tests in tmpdir for `wave-init`, `flight-finalize`, `changelog-aggregate`, `wave-cleanup`; status-panel snapshot test.
- **R-12** — The Tier 1 status-panel snapshot test shall feed a known fixture state JSON to `generate-status-panel`, capture the HTML output, and compare byte-equal to a checked-in snapshot.

### 3.6 Tier 4 End-to-End

- **R-13** — When Tier 4 Test 4.1 (GitHub single-flight) runs, the harness shall: create a single-issue fixture Plan in a Wave-Engineering GitHub fixture repo; drive `/wavemachine` to terminal state; assert (a) kahuna branch created via `wave_init`, (b) kahuna→main MR opened by `wave_finalize`, (c) gate ran all 4 trust signals concurrently in a single tool-use block, (d) `pr_merge` landed the MR, (e) observability events landed in `~/.claude/logs/mcp.jsonl`, (f) status panel reflects terminal state, (g) teardown clean.
- **R-14** — When Tier 4 Test 4.8 (GitLab single-flight) runs, the harness shall execute R-13's assertions parametrized for GitLab plus: `glab` adapter parity for `pr_create`/`pr_merge`/`pr_status`/`pr_diff`/`pr_files`/`pr_wait_ci`/`pr_merge_wait`; merge-train-warning emitted to Discord before `pr_merge`; approval rule scoped via `protected_branch_ids` permits the auto-merge; `skip_train: true` interpreted per platform.
- **R-15** — When Tier 4 Test 4.6 (cross-repo) runs, the harness shall execute a wave with the Plan in repo A and Stories in repo B, and assert: pre-created worktrees in repo B, `gh -R` scoping on every command, no `isolation: "worktree"` flag misuse, kahuna branches in BOTH repos, both kahuna→main MRs land, `wave-status` state in master plan repo, worktree teardown unlocks before force-removal.
- **R-16** — If any Tier 4 test fails, the harness shall produce a single forensic doc reconstructing the failure timeline from `~/.claude/logs/mcp.jsonl` and bus state, persist it to a documented filesystem path, and include the path in the Discord nightly report.

### 3.7 Observability

- **R-17** — When the harness starts a tier, completes a tier, starts a Tier 4 test, completes a Tier 4 test, or completes a major Tier 4 step (fixture create, kahuna create, gate run, merge, teardown), the harness shall emit a structured event to `~/.claude/logs/mcp.jsonl` with a documented schema.

### 3.8 Notification

- **R-18** — After each nightly run, the harness shall post a single summary message to the configured Discord channel reporting per-tier pass/fail counts and forensic-doc paths for any failures.
- **R-19** — If a `@`-mention is present in any harness Discord post body, the harness shall reject the post locally (before send), emit a `NOTIFICATION_ATMENTION_BLOCKED` event to `~/.claude/logs/mcp.jsonl`, and continue execution.

### 3.9 Self-Validation

- **R-20** — Before the harness is declared shippable (Plan: Gamma DoD), at least one Plan #607 follow-up bug (cc#629–#638, sdlc#425, or successor list documented at ship time) shall have a corresponding red Tier 4 test that turns green when the production fix lands.

### 3.10 Cost

- **R-21** — When a nightly run's API token cost exceeds $8 on more than one consecutive run, the harness shall post a Discord overage notice and the next run shall fail-the-build with a `BUDGET_EXCEEDED` event.

### 3.11 Auth

- **R-22** — The harness shall use a fine-grained GitHub PAT scoped to read+write on `Wave-Engineering/ccwork-testtarget*` and `Wave-Engineering/harness-target-*` repo names only (no org-admin scope) AND a GitLab token scoped to `gitlab.com/testtarget/` only.

---

## 4. Concept of Operations

### 4.1 System Context

```
                        ┌─────────────────────────────────────┐
                        │       Operator (BJ today)           │
                        │  - Configures harness host          │
                        │  - Reads nightly Discord report     │
                        │  - Reads forensic doc on red runs   │
                        └────────────────┬────────────────────┘
                                         │
                              ┌──────────▼──────────┐
                              │   Cron / on-demand  │
                              │   CLI invocation    │
                              └──────────┬──────────┘
                                         │
                  ┌──────────────────────▼──────────────────────┐
                  │         ccwork-testtarget (this Plan)       │
                  │      Python + pytest harness runner         │
                  │                                             │
                  │  Tier 0 → Tier 1 → Tier 4 → Tier 6          │
                  │  Per-run-id-prefixed fixture lifecycle      │
                  │  JSON-RPC stdio MCP server interaction      │
                  └─┬───────────┬────────────┬───────────┬──────┘
                    │           │            │           │
       (drives)     │           │ (creates)  │ (writes)  │ (posts)
                    │           │            │           │
        ┌───────────▼───────┐  ┌▼──────────┐ ┌▼─────────┐ ┌▼─────────┐
        │  /wavemachine     │  │ Fixture   │ │ ~/.claude│ │ Discord  │
        │  (system under    │  │ repos:    │ │ /logs/   │ │ #harness-│
        │   test, Tier 4)   │  │  GH +     │ │  mcp.    │ │ test     │
        │                   │  │  GitLab   │ │  jsonl   │ │          │
        │  → spawns MCP     │  └───────────┘ └──────────┘ └──────────┘
        │     servers       │
        │  → spawns Claude  │
        │     Code subproc  │
        └───────────────────┘
```

**Key actors:**

| Actor | Role | Interaction |
|-------|------|-------------|
| **Operator** | Human (BJ today; future fleet ops) | Configures host, reads Discord report, reads forensic docs |
| **Cron / CLI** | Harness invoker | Triggers nightly or on-demand runs; passes flags |
| **Harness runner** | This Plan's deliverable | Orchestrates tier execution, manages fixtures, drives system-under-test, emits telemetry |
| **System under test** | `/wavemachine` + Claude Code + MCP fleet + bus scripts + skills | The thing the harness drives during Tier 4 |
| **Fixture repos** | `Wave-Engineering/harness-target-*` (private) + `gitlab.com/testtarget/harness-fixture` | Per-run-id-prefixed scratch artifacts |
| **`mcp.jsonl`** | Fleet-wide structured event log | Harness lifecycle events + sdlc-server tool calls share this file |
| **Discord channel** | `#harness-test` (or operator-configured) | One nightly summary post + per-failure forensic-doc paths |

### 4.2 Operational Flow A: Nightly Clean Run (happy path)

```
00:00  cron fires → harness CLI invoked with no flags
00:00  Tier 0: static integrity checks pass
00:01  Tier 1: bun test suites + bus-script tests + status-panel snapshot all pass
00:08  Tier 4 fixture-repo lifecycle: create harness-<run-id>
00:09  Tier 4 Test 4.1: drive /wavemachine to terminal, all 7 assertions pass
00:35  Tier 4 Test 4.8: same, parametrized for GitLab
01:02  Tier 4 Test 4.6: drive cross-repo wave, dual kahuna→main MRs land
01:35  Tier 4 fixture teardown: delete by run-id prefix
01:36  Tier 6: observability checks
01:36  Discord post: "🌃 Nightly green — Tier 0/1/4/6 all pass, 0 failures, $5.40 spent"
```

### 4.3 Operational Flow B: Nightly with Tier 4 Failure

The nightly cron invocation passes `--keep-state` (per §5.B) so failed Tier 4 tests preserve forensic state automatically.

```
00:00  cron fires → ccwork-testtarget --keep-state
00:01  Tier 0/1 pass
00:08  Tier 4 fixture create ok
00:09  Tier 4 Test 4.1 starts, fails at gate-runs-all-4-trust-signals-concurrently
        (only 3 signals fired in same tool-use block — wave_finalize regression)
00:10  Harness records FAIL, captures bus state, captures mcp.jsonl slice
00:10  --keep-state failure-only persistence kicks in (R-06)
        → fixtures preserved at /var/harness/keepstate/<run-id>-4.1/
00:10  Forensic doc generated at /var/harness/forensics/<run-id>-4.1.md
00:11  Tier 4 Test 4.8: continues per R-02, passes
00:38  Tier 4 Test 4.6: continues, passes
01:11  Discord post: "⚠️ Nightly red — Tier 4.1 failed. Forensic: ... Keepstate: ... $5.80"
```

### 4.4 Operational Flow C: On-Demand Single-Tier Invocation

```
Operator runs: ccwork-testtarget --tier 4 --keep-state
00:00  Harness skips Tier 0/1/6 (per R-03), runs Tier 4 only
00:35  --keep-state set → on PASS, fixture cleanup is skipped; on FAIL, same as Flow B
00:35  Discord post: "Tier 4 only — Tests 4.1/4.6/4.8 green"
```

### 4.5 Operational Flow D: Forensic Replay from a Failed Run

```
Operator opens /var/harness/forensics/<run-id>-4.1.md
  ↓
Doc shows: failure summary, timeline (interleaved harness + mcp.jsonl events),
           preserved-state inventory, bisect hint
  ↓
Operator runs: ccwork-testtarget --tier 4 --bisect gate-trust-signals \
               --replay-from /var/harness/keepstate/<run-id>-4.1/
00:00  Harness loads preserved state, re-executes only the gate step
00:02  Reproduces the failure (or doesn't, if it was flake)
```

---

## 5. Detailed Design

### Index of Design Choices

The 16 design choices below carry IDs `DC-01` through `DC-16` for traceability from §3 requirements, §6 test plan, §8 stories, and the appendices. Each is documented in its corresponding §5 subsection.

| ID | Section | Topic |
|----|---------|-------|
| DC-01 | §5.1 | Runner architecture: src-layout pytest package, one test file per tier |
| DC-02 | §5.2 | Run-id format: `<UTC-YYYYMMDD>-<8-char-hex>` |
| DC-03 | §5.2 | GitHub fixtures: per-run-id repos under `Wave-Engineering/` |
| DC-04 | §5.2 | GitLab fixtures: long-lived project + per-run-id-prefixed branches/MRs/issues + 7-day stale cleanup |
| DC-05 | §5.3 | Fresh subprocess per MCP invocation; auto-generated `MCPClient` API |
| DC-06 | §5.3 | JSON-RPC framing via the `mcp` Python package |
| DC-07 | §5.4 | Tier 4 driver: subprocess-spawn the real `claude` CLI |
| DC-08 | §5.5 | Forensic doc: single Markdown file per failed test |
| DC-09 | §5.5 | Timeline reconstruction: deterministic merge, no LLM at this layer |
| DC-10 | §5.6 | Discord posting via `mcp-server-discord`'s `disc_send` tool |
| DC-11 | §5.6 | `@`-mention regex guardrail rejecting before send |
| DC-12 | §5.7 | Cost tracking via `mcp.jsonl` `tool_call.usage` × `pricing.yml` rates |
| DC-13 | §5.7 | `pricing.yml` flat YAML + Tier 0 unknown-model warning |
| DC-14 | §5.8 | `--keep-state` defaults `false`; on-failure-only persistence when set |
| DC-15 | §5.8 | `--bisect` re-runs named step methods against pre-loaded state |
| DC-16 | §5.9 | Harness's own CI on GitHub-hosted runners; Tier 4 only on cron host |

### 5.1 Runner Architecture

**Choice (DC-01):** Single Python package at `src/ccwork_testtarget/` (src layout), with pytest test files in `tests/` discoverable by default `test_*.py` convention. Tier-level test files (`tests/test_tier0_static.py`, `tests/test_tier1_unit.py`, `tests/test_tier4_e2e.py`, `tests/test_tier6_observability.py`) act as the top-level entry points; Stories may add more granular per-component test files under `tests/_helpers/` as the helper code is built (e.g., `test_mcp_subprocess.py`, `test_fixture_lifecycle.py`, `test_forensic.py`). Per-tier test cases live in classes (`class TestTier4SingleFlightGitHub:`) so pytest's `-k` filter selects naturally. Cross-tier helpers live under `src/ccwork_testtarget/_helpers/` (`mcp_subprocess.py`, `fixture_lifecycle.py`, `forensic.py`, etc.).

### 5.2 Fixture-Repo Lifecycle

**Run-id format:** `<UTC-YYYYMMDD>-<8-char-hex>`, e.g. `20260507-a1b2c3d4`. Hex suffix from `secrets.token_hex(4)` per Python invocation.

**GitHub fixtures** use **per-run-id repos**: each Tier 4 run creates `Wave-Engineering/harness-target-<run-id>` (private), seeds with minimal commit + workflow, runs the test, deletes via `gh repo delete --yes` on teardown. Cross-repo Test 4.6 creates two repos: `harness-target-<run-id>-a` and `-b`.

**GitLab fixture** is one **long-lived project** (`gitlab.com/testtarget/harness-fixture`) with per-run-id-prefixed branches, MRs, and issues. Stale-state cleanup at start of each nightly: any artifact with a run-id prefix older than 7 days deleted unconditionally. Asymmetry with GitHub is platform-driven (project create/delete is heavier on GitLab).

### 5.3 MCP Server Subprocess Management

Each MCP server invocation spawns a fresh subprocess via `subprocess.Popen([...], stdin=PIPE, stdout=PIPE, stderr=PIPE)`. The harness wraps this in an `MCPClient` class with one method per tool (auto-generated from `tools/list` so adding a new MCP tool doesn't require harness changes). Each test gets its own client instance — no client reuse across tests.

JSON-RPC framing per MCP spec (Content-Length headers, JSON body, line-delimited). Harness uses the `mcp` Python package (`pip install mcp`) for protocol handling rather than reimplementing.

### 5.4 Tier 4 `/wavemachine` Driver Model

Tier 4 tests drive `/wavemachine` by **subprocess-spawning the real `claude` CLI** with a constructed prompt and harness-controlled environment. Specifically: the harness writes a temporary `CLAUDE_PROJECT_DIR` (a checkout of cc-workflow at the run's pinned commit), sets `~/.config/claude-code/mcp.json` via env-override to point at the harness's MCP servers, sets `~/.claude/projects/...` paths to a tmpdir, and invokes `claude --print --dangerously-skip-permissions` with the prompt `/wavemachine`. Harness captures stdout/stderr and parses terminal state from the resulting `~/.claude/logs/mcp.jsonl` slice.

This is what the $4–8/night budget pays for. Three Tier-4 campaigns × ~30-min wall-clock × Opus 4.x token spend.

### 5.5 Forensic Doc Generation

Forensic doc is **single Markdown file** per failed test, persisted at `/var/harness/forensics/<run-id>-<test-id>.md`. Format:

```markdown
# Forensic: <run-id> · <test-id>

## Failure summary
- Tier: 4 · Test: 4.1 · Failed assertion: gate-runs-all-4-trust-signals-concurrently
- Expected: 4 trust signals in single tool-use block · Observed: 3

## Timeline
<chronologically interleaved harness lifecycle events + mcp.jsonl tool_call events>

## Preserved state
- Bus dir: /var/harness/keepstate/<run-id>-<test-id>/wavemachine/
- Worktrees: /tmp/wt-harness-<run-id>-* (5 found)
- MCP log slice: /var/harness/keepstate/<run-id>-<test-id>/mcp.jsonl

## Bisect hint
ccwork-testtarget --tier 4 --bisect gate-trust-signals \
  --replay-from /var/harness/keepstate/<run-id>-<test-id>/
```

Timeline reconstruction is a **deterministic merge** of harness's own `event` stream + mcp-server-sdlc's `tool_call` events, sorted by timestamp. No model / LLM reasoning — just data.

### 5.6 Notification Subsystem

Discord posting via existing `mcp-server-discord` MCP server (`disc_send` tool). Channel-id resolution: env var `HARNESS_DISCORD_CHANNEL_ID`; default empty (no posting if unset).

`@`-mention guardrail (R-19) is a regex check on the post body before `disc_send` is called. Pattern: `r'(?<!\w)@(?:all|here|everyone|[A-Z][a-z]+(?:[-_][A-Za-z]+)*)\b'`. If matched: reject post, emit `NOTIFICATION_ATMENTION_BLOCKED` event, continue execution.

### 5.7 Cost Tracking

Per-run cost via Anthropic API's `response.usage.{input_tokens,output_tokens}` written to `mcp.jsonl` by mcp-server-sdlc per tool_call event. Harness sums per-tool tokens for the run, multiplies by checked-in `pricing.yml` (per-model rates), reports dollar figure.

`pricing.yml` is flat YAML keyed by model name, manually updated when Anthropic changes pricing. Harness emits a Tier 0 warning if the active model isn't in `pricing.yml` (catches accidental model upgrades that would silently mis-cost).

### 5.8 `--bisect` and `--keep-state` Mechanics

`--keep-state` defaults to `false`. When `true`, on Tier 4 test FAILURE only: preserve bus dir, worktrees, mcp.jsonl slice, fixture-repo state (pre-teardown snapshot via `gh api` repo dump). Persist to `/var/harness/keepstate/<run-id>-<test-id>/`.

`--bisect <step-name>` re-runs only the named step from a `--replay-from <keepstate-path>`. Step names documented in forensic doc's "Bisect hint" line. Each Tier 4 test class exposes named methods (`step_create_kahuna`, `step_run_gate`, `step_merge_kahuna`, etc.); `--bisect` invokes one method against pre-loaded state.

### 5.9 Harness's Own CI

Harness repo's own CI runs on **GitHub-hosted runners** for unit-test surface (testing the harness's *helper* code, not the system under test). Tier 4 tests do NOT run in CI; they run only via the nightly cron on the dedicated host. CI hosts cannot satisfy TC-07 (no DinD) for Tier 4 patterns involving subprocess Claude CLI.

### 5.A Deliverables Manifest

This is a new-product Plan: a Python harness repo created from scratch in `Wave-Engineering/ccwork-testtarget`. Every Tier 1 deliverable is produced by this Plan (none N/A). Tier 2 triggers fire for architecture, prerequisites, deployment verification, and manual procedures because the harness is a multi-component system that deploys infrastructure (cron + dedicated host) and has host/platform requirements.

#### Canonical manifest table

| ID | Deliverable | Category | Tier | File Path | Produced In | Status | Notes |
|----|-------------|----------|------|-----------|-------------|--------|-------|
| DM-01 | README.md | Docs | 1 | `README.md` | Phase 1 Wave 1 (Story 1.1) | required | Install + usage stub at 1.1; refined throughout |
| DM-02 | Unified build system (Makefile) | Code | 1 | `Makefile` | Phase 1 Wave 1 (Story 1.1) | required | Targets: `install`, `test`, `lint`, `nightly`, `clean`, `snapshot-update` |
| DM-03 | CI/CD pipeline | Code | 1 | `.github/workflows/ci.yml` | Phase 1 Wave 4 (Story 1.11) | required | GitHub-hosted runners only per DC-16; harness's own helper-code tests |
| DM-04 | Helper-code unit test suite | Test | 1 | `tests/_helpers/test_*.py` | Phase 1 (every Story) + Phase 2 (every Story) | required | Test surface for the harness's helper code, NOT the system under test |
| DM-05 | Test results (JUnit XML) | Test | 1 | `test-results.xml` (CI artifact) | Phase 1 Wave 4 (Story 1.11) | required | `pytest --junit-xml` output uploaded by CI |
| DM-06 | Coverage report | Test | 1 | `coverage.xml` + `htmlcov/` | Phase 1 Wave 4 (Story 1.11) | required | `pytest-cov` HTML + XML; coverage badge in README |
| DM-07 | CHANGELOG | Docs | 1 | `CHANGELOG.md` | Phase 1 Wave 1 (Story 1.1) initialized; Phase 2 Wave 4 (Story 2.9) v0.1.0 entry | required | Initialized at 1.1; v0.1.0 entry at ship time |
| DM-08 | VRTM | Trace | 1 | This Dev Spec, Appendix V | Phase 2 Wave 4 (Story 2.9) | required | Skeleton in this Dev Spec; full pass at ship per Story 2.9 |
| DM-09 | Audience-facing doc (operator runbook) | Docs | 1 | `docs/RUNBOOK.md` | Phase 1 Wave 5 (Story 1.12) for Tier 0/1/6; Phase 2 Waves 3–4 (Stories 2.4–2.8) for Tier 4 | required | Install / configure / verify / troubleshoot |
| DM-10 | Architecture document | Docs | 2 | `docs/ARCHITECTURE.md` | Phase 1 Wave 1 (Story 1.1) initial; refined every Story | required | Trigger: >2 interacting components |
| DM-11 | Environment prerequisites | Docs | 2 | `docs/PREREQUISITES.md` | Phase 1 Wave 1 (Story 1.1) | required | Trigger: host/platform requirements (Python, CLIs, tokens, dedicated host) |
| DM-12 | Deployment verification | Docs | 2 | `docs/DEPLOYMENT.md` | Phase 1 Wave 5 (Story 1.12) | required | Trigger: project deploys infrastructure (cron + host + state dirs) |
| DM-13 | Manual test procedures | Docs | 2 | `docs/MANUAL-VERIFICATION.md` | Phase 2 Wave 4 (Story 2.9) | required | Trigger: MV-01 through MV-06 defined in §6.4 |

#### Tier 1 walk notes

Every Tier 1 row above is populated with a file path + Produced In assignment. None are N/A. Rationale:

- **DM-01, DM-02:** new repo — README and Makefile are bootstrapped at Story 1.1.
- **DM-03, DM-05, DM-06:** new CI pipeline produced at Story 1.11 (no pre-existing pipeline to inherit).
- **DM-04:** the harness's *helper code* gets unit tests; the harness's *content* (Tier 0/1/4/6) is the test plan itself per §6.1.
- **DM-07:** new CHANGELOG; initialized at 1.1, v0.1.0 entry at ship time.
- **DM-08:** VRTM skeleton in Appendix V; finalized at Story 2.9.
- **DM-09:** operator runbook is the audience-facing doc; co-produced with code per §8 Co-production Rule.

#### Tier 2 trigger scan

| Trigger | Fires? | Row in manifest |
|---------|--------|-----------------|
| MV-XX items exist in §6.4 | Yes — MV-01 through MV-06 defined | DM-13 (Manual test procedures, `docs/MANUAL-VERIFICATION.md`) |
| >2 interacting components in design | Yes — runner + MCP client + fixture lifecycle + /wavemachine driver + forensic generator + notification + cost tracker (≥7 components) | DM-10 (`docs/ARCHITECTURE.md`) |
| Project deploys infrastructure | Yes — cron job + dedicated host + state directories under `/var/harness/` | DM-12 (`docs/DEPLOYMENT.md`) |
| Project has host/platform requirements | Yes — Python ≥3.11, multiple CLIs on PATH, multiple tokens, dedicated host | DM-11 (`docs/PREREQUISITES.md`) |

All four Tier 2 triggers fire; one manifest row added per trigger (DM-10 through DM-13).

#### Tier 3 (opt-in) — none requested

No sequence diagrams, data flow diagrams, threat models, or performance benchmarks added. All explicitly N/A.

### 5.B Installation & Deployment

**Install (one-time, on the operator's dedicated host):**

```bash
git clone git@github.com:Wave-Engineering/ccwork-testtarget.git
cd ccwork-testtarget
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
command -v gh glab bun trivy jq mcp-log generate-status-panel wave-status
# Configure environment in ~/.harness.env or systemd unit
export ANTHROPIC_API_KEY=...
export HARNESS_GITHUB_TOKEN=...        # fine-grained PAT per TC-06
export HARNESS_GITLAB_TOKEN=...
export HARNESS_DISCORD_CHANNEL_ID=...
ccwork-testtarget --tier 0   # smoke-test
```

**Deploy (cron):** the nightly invocation runs with `--keep-state` so failed Tier 4 tests preserve forensic state automatically (per DC-14 / R-06):

```cron
0 0 * * * cd /home/operator/ccwork-testtarget && source ~/.harness.env && \
          .venv/bin/ccwork-testtarget --keep-state >> /var/log/harness/nightly.log 2>&1
```

**State directories** (created on first run): `/var/harness/forensics/`, `/var/harness/keepstate/`, `/var/log/harness/`. Operator can override paths via `HARNESS_FORENSICS_DIR`, `HARNESS_KEEPSTATE_DIR`, `HARNESS_LOG_DIR`.

### 5.N Open Questions

These are unresolved and tracked for follow-up; they do not block the Dev Spec.

1. **PAT shape.** Single fine-grained PAT scoped to harness namespaces, or split into harness-repo-CI PAT vs. fixture-repo-create PAT? Lean: split. Decide during Phase 1's repo bootstrap (Story 1.1).
2. **Discord channel name.** `#harness-test` vs. `#harness-nightly` vs. piggyback on `#wave-status`. Lean: dedicated `#harness-nightly`. Operator-configurable per DC-10.
3. **Test ordering within a tier.** Tier 1 fully parallel via `pytest-xdist`; Tier 4 serial (per-run-id prefix already isolates, but parallel runs would multiply cost). Re-evaluate if nightly wall-clock becomes a bottleneck.
4. **"Ship the harness" criterion.** Locked: ≥1 red→green pair from Plan #607 follow-up list (PC-04 / R-20).
5. **Watchdog timeout for Tier 4 `claude` subprocess.** Lean: 60-min default, configurable via `HARNESS_TIER4_TIMEOUT_SEC`. Decide during Phase 2 Story 2.4.
6. **Anthropic API outage / rate-limit handling.** Lean: hard-fail with `API_UNAVAILABLE` event, abort remaining Tier 4 tests for the run, post Discord notice. Single retry on first 429 only.
7. **GitHub / GitLab API outage handling.** Same shape as #6: hard-fail with platform-specific event, abort affected platform's tests, continue other platform's tests.

---

## 6. Test Plan

### 6.1 Test Strategy

The harness has two test surfaces:

| Surface | What we test | How |
|---------|-------------|-----|
| Layer 1: Harness helper code | `MCPClient`, `FixtureLifecycle`, `ForensicGenerator`, `NotificationSubsystem`, `CostTracker`, `KeepState`, CLI argument parsing | Unit tests + Integration tests in `tests/_helpers/`. Run on every CI build. |
| Layer 2: Tier execution as a whole | `ccwork-testtarget --tier <N>` actually executes the named tier, returns correct exit code, posts the right Discord message | E2E tests in `tests/e2e/`. Use stub MCP servers and mocked GitHub/GitLab CLIs. |
| Layer 3: Manual verification | Discord lands in correct channel, cron fires, fine-grained PAT can't write to non-harness repos | Operator runbook (DM-09); MV-XX checklist below. |

The harness's *content* (Tier 0/1/4/6 behavior against the system under test) IS the test plan and is described by §3 (Requirements). §6 is about Layer 1.

### 6.2 Integration Tests (Automated)

| ID | Test | What it asserts |
|----|------|-----------------|
| **IT-01** | `MCPClient` round-trip | Spawns stub MCP server subprocess, JSON-RPC framing handled correctly, response parsed, subprocess cleaned up on `MCPClient.close()`. |
| **IT-02** | `FixtureLifecycle.create_github_repo` | Mocks `gh` CLI. Asserts: per-run-id-prefixed repo name, private flag set, seed commit applied. Negative test: refuses to create outside harness namespaces. |
| **IT-03** | `FixtureLifecycle.teardown_by_prefix` | Mocks `gh` CLI. Asserts: only prefix-matching repos deleted; siblings untouched. |
| **IT-04** | `ForensicGenerator.merge_timeline` | Feeds known harness-event stream + known mcp.jsonl slice. Asserts: events sorted by timestamp, output byte-equal to expected Markdown. |
| **IT-05** | `NotificationSubsystem.reject_atmention` | 8 candidate post bodies (4 with @-mentions, 4 without). Asserts: all 4 with rejected; all 4 without accepted. |
| **IT-06** | `CostTracker.compute_run_cost` | Known mcp.jsonl with known token counts + known `pricing.yml`. Asserts: dollar figure to 4-decimal precision. |
| **IT-07** | `CostTracker.unknown_model_warning` | mcp.jsonl with model not in pricing.yml. Asserts: `PRICING_MODEL_UNKNOWN` warning event emitted; cost reported as `null` (not zero). |
| **IT-08** | `KeepState.preserve_on_failure` | Mocks filesystem. Asserts: failed test → preserved bus dir, worktrees, mcp.jsonl slice; passed test → nothing preserved. |
| **IT-09** | `KeepState.preserve_on_failure_with_keep_state_off` | Same as IT-08 but `--keep-state` not set. Asserts: nothing preserved even on failure. |

### 6.3 End-to-End Tests (Automated)

| ID | Test | What it asserts |
|----|------|-----------------|
| **E2E-01** | `ccwork-testtarget --tier 0` | All Tier 0 checks run; exit 0 on green; exit 1 on first failure; structured event per check emitted. |
| **E2E-02** | `ccwork-testtarget --tier 1` (stubbed MCP `bun test`) | Tier 1 sub-suite runner invokes each MCP server's test command; collected results match known-good fixture. |
| **E2E-03** | `ccwork-testtarget --tier 4` (stubbed system-under-test) | Tier 4 runner creates fixture, drives stub `/wavemachine` (in-repo `tests/stubs/fake_wavemachine.py`), asserts canonical artifacts, tears down. |
| **E2E-04** | `ccwork-testtarget` (nightly mode) | Tier 0 → 1 → 4 → 6 in order; on success, Discord summary post matches expected shape. |
| **E2E-05** | `ccwork-testtarget --bisect <step> --replay-from <fixture>` | Re-runs only named step against pre-loaded state; result matches expected. |
| **E2E-06** | Nightly with deliberately-broken Tier 4 | Forensic doc generated at expected path; keepstate dir populated; Discord summary marks Tier 4.X as failed; exit code reflects failure. |
| **E2E-07** | `--tier 4 --keep-state` then `--bisect ... --replay-from ...` | Full happy-path of forensic-replay loop end-to-end. |

### 6.4 Manual Verification Procedures

| ID | Procedure | When to run |
|----|-----------|-------------|
| **MV-01** | Operator post-install verifies a Discord post lands in `$HARNESS_DISCORD_CHANNEL_ID` and is correctly formatted (via `ccwork-testtarget --post-test-message`). | Once per host install; once per Discord channel change. |
| **MV-02** | Operator verifies cron job fires at configured time and stdout/stderr land in `/var/log/harness/nightly.log`. | Once per host install; once per cron schedule change. |
| **MV-03** | Operator verifies fine-grained PAT cannot write to non-harness repos. Procedure: attempt `gh repo create Wave-Engineering/probe-non-harness` — must fail with permission error. | Once per PAT issuance; once per scope change. |
| **MV-04** | Operator inspects a forensic doc rendered in their Markdown viewer. Verify timeline interleave is readable; preserved-state inventory paths exist; bisect hint command is copy-paste-runnable. | Once per major harness release; once per forensic-doc format change. |
| **MV-05** | Operator runs `--bisect` against a real preserved keepstate from a real failed Tier 4 run; verifies the failure reproduces deterministically. | Once per Tier 4 test class added; once per `--bisect` mechanism change. |
| **MV-06** | Operator verifies cost report matches a manual cross-check against the Anthropic billing dashboard for a representative nightly run (within ±10%). | Quarterly, or on suspicion of cost-tracking drift. |

---

## 7. Definition of Done

### 7.1 Global Definition of Done

**Functional contract:**
- [ ] All requirements R-01 through R-22 verified by their corresponding tests (§6) or by Tier 0/1/4/6 execution against a live system-under-test.
- [ ] All technical constraints TC-01 through TC-07 enforced at runtime.
- [ ] All product constraints PC-01 through PC-05 enforced at runtime.

**Coverage:**
- [ ] Tier 0 covers all 8 required CLIs, every MCP server's `tools/list` snapshot, all skill frontmatter, MEMORY.md integrity, WAVE_AXIOMS.md.
- [ ] Tier 1 covers all 4 MCP server `bun test` suites; all 4 bus scripts in tmpdir; status-panel snapshot.
- [ ] Tier 4 covers Tests 4.1, 4.8, 4.6 end-to-end against real fixture repos.
- [ ] Tier 6 covers `mcp.jsonl` schema, status-panel snapshot, Discord round-trip, `vox` best-effort logging.

**Self-validation (load-bearing — PC-04 / R-20):**
- [ ] At least one open Plan #607 follow-up bug has a corresponding red Tier 4 test in the harness.
- [ ] That red test demonstrably turns green when the production fix lands (red→green pair preserved in test history).

**Operational stability:**
- [ ] Nightly cron has run unattended for ≥7 consecutive nights on the dedicated host without operator intervention.
- [ ] Discord summary posts have landed in the configured channel for those 7 nights, none rejected by the `@`-mention guard.
- [ ] No fixture state leak detected across the 7-night window.
- [ ] Total API token cost averages within $4–8/night band; no `BUDGET_EXCEEDED` events on more than 1 of the 7 nights.

**Documentation:**
- [ ] DM-01 through DM-13 all present and current.
- [ ] DM-08 (VRTM) maps every R-NN to its verifying test(s).
- [ ] CHANGELOG.md updated with v0.1.0 release entry.
- [ ] DM-09 covers install, configure, verify, troubleshoot.

**CI / quality:**
- [ ] Harness repo's own CI green on `main` for ≥3 consecutive commits.
- [ ] Helper-code unit coverage ≥80% via `pytest-cov`.
- [ ] MV-01 through MV-06 executed at least once on the dedicated host; signed off in DM-13.

### 7.2 Dev Spec Finalization Checklist

The mechanical checks that `/devspec finalize` runs:

1. **Sections 1–9 all present and non-empty.**
2. **Requirements use EARS format.** Section 3 has R-NN-numbered requirements with EARS phrasing.
3. **Deliverables Manifest exists with ≥9 Tier 1 rows.**
4. **Every active manifest row has a "Produced In" Wave/Phase assignment.**
5. **Every Story in §8 declares `depends_on`** (`[]` for empty).
6. **Section 7.2 finalization checklist exists.**
7. **No template placeholders (`[[...]]`) remaining.**

---

## 8. Phased Implementation Plan

### How to read this section

- **Phase** = sequential ordering unit. Phases run in order; a Phase doesn't start until the prior Phase's DoD is satisfied.
- **Wave** = concurrency unit within a Phase. Stories in the same Wave have no inter-dependencies and run in parallel.
- **Story** = one implementation issue, one branch, one PR, one Flight. Each Story declares `depends_on`.
- Story IDs encode `Phase.SequentialWithinPhase` (e.g., `1.4` = Phase 1, Story 4).
- All Stories target repository `Wave-Engineering/ccwork-testtarget`.

### Foundation Story Checklist

Pre-Phase-1 platform-side setup, executed before Wave 1 spawns (NOT a `/wavemachine` Story):

- [ ] `Wave-Engineering/ccwork-testtarget` repo created on GitHub (private)
- [ ] Fine-grained GitHub PAT issued, scoped per TC-06
- [ ] GitLab project `gitlab.com/testtarget/harness-fixture` created
- [ ] GitLab token issued, scoped to `gitlab.com/testtarget/`
- [ ] Dedicated cron host identified; operator has write access to `/var/harness/`
- [ ] Anthropic API key issued for harness's exclusive use
- [ ] Discord channel `#harness-nightly` (or operator-named) created

The Wave 1 Foundation Story (1.1) covers the *code* foundation: pyproject.toml, Makefile, package skeleton, initial docs.

### Closing Story Checklist

The Phase 2 DoD's "7 consecutive unattended nights" condition + Story 2.9's red→green self-validation contract together fulfill the Closing Story role: every MV procedure (§6.4) is exercised at least once during the 7-night window or in Story 2.9 documentation; VRTM is finalized in DM-08; every active manifest row's "Produced In" assignment is verified delivered. MV-01 through MV-06 are documented in DM-13 as operator procedures; the operator runs them post-install per the runbook.

### Wave Map

```
Phase 1 — Tier 1 Runtime
├── P1W1: 1.1 (foundation)
│         │
├── P1W2: 1.2, 1.3, 1.4 (parallel — independent helpers)
│         │
├── P1W3: 1.5, 1.6, 1.7, 1.8, 1.9 (parallel — tier content)
│         │
├── P1W4: 1.10, 1.11 (parallel — runner + CI)
│         │
└── P1W5: 1.12 (deploy nightly + initial 1-night verification)

Phase 2 — Tier 4 v0
├── P2W1: 2.1, 2.2, 2.3 (parallel — independent helpers)
│         │
├── P2W2: 2.4 (Tier 4 driver)
│         │
├── P2W3: 2.5, 2.6, 2.7 (parallel — Tier 4 tests)
│         │
└── P2W4: 2.8, 2.9 (parallel — replay + self-validation)
```

| Wave | Stories | Master | Parallel? |
|------|---------|--------|-----------|
| P1W1 | 1.1 | 1.1 | Single story |
| P1W2 | 1.2, 1.3, 1.4 | Wave 2 Master | Yes — 3 independent |
| P1W3 | 1.5, 1.6, 1.7, 1.8, 1.9 | Wave 3 Master | Yes — 5 independent |
| P1W4 | 1.10, 1.11 | Wave 4 Master | Yes — 2 independent |
| P1W5 | 1.12 | 1.12 | Single story |
| P2W1 | 2.1, 2.2, 2.3 | Wave 1 Master | Yes — 3 independent |
| P2W2 | 2.4 | 2.4 | Single story |
| P2W3 | 2.5, 2.6, 2.7 | Wave 3 Master | Yes — 3 independent |
| P2W4 | 2.8, 2.9 | Wave 4 Master | Yes — 2 independent |

### Co-production Rule

The harness's documentation surface (DM-09 operator runbook, DM-10 architecture, DM-11 prerequisites, DM-12 deployment, DM-13 manual verification) is co-produced with the code — each Story that produces user-visible behavior also updates the relevant operator-runbook section in the same PR.

---

### Phase 1: Tier 1 Runtime

**Goal:** Ship a working nightly cron that runs Tier 0 (static integrity) + Tier 1 (unit-equivalent) + Tier 6 (observability) end-to-end on a dedicated host with a green Discord summary post.

#### Phase 1 Definition of Done

- [ ] All 12 Phase 1 Stories merged to `main` of `ccwork-testtarget` [R-01, R-02, R-03]
- [ ] `ccwork-testtarget --tier 0` exits 0 on a freshly-installed harness host [R-10]
- [ ] `ccwork-testtarget --tier 1` exits 0; all four MCP server `bun test` suites + four bus-script tests + status-panel snapshot pass [R-11, R-12]
- [ ] `ccwork-testtarget --tier 6` exits 0; `mcp.jsonl` schema validates, Discord round-trip succeeds [R-17, R-18]
- [ ] `ccwork-testtarget` (no flags = nightly) runs Tier 0+1+6 unattended for 1 consecutive night with a green Discord summary post landing in the configured channel [R-01, R-18, R-19]
- [ ] DM-01, DM-02, DM-03, DM-04, DM-05, DM-06, DM-07, DM-09 (Tier 0/1/6 sections), DM-10, DM-11, DM-12 all present and current
- [ ] All Phase 1 unit tests pass

---

#### Story 1.1: Foundation — repo bootstrap + Python package skeleton (#1)

**Wave:** P1W1
**Dependencies:** None

Bootstrap the harness repo with `pyproject.toml`, `Makefile`, package skeleton, and initial documentation drafts. Foundation work — every subsequent Story depends on this.

**Implementation Steps:**

1. Write `pyproject.toml` with `[project]` metadata: name `ccwork-testtarget`, Python ≥3.11, deps `pytest`, `pytest-cov`, `pytest-xdist`, `mcp` (Anthropic MCP Python SDK), `pyyaml`.
2. Write `Makefile` with targets: `install` (`pip install -e .`), `test` (`pytest -v`), `lint` (`ruff check`), `nightly` (`ccwork-testtarget`), `clean`.
3. Create `src/ccwork_testtarget/` package skeleton with `__init__.py`, empty `cli.py`, and an entry point declared in `pyproject.toml` (`[project.scripts] ccwork-testtarget = "ccwork_testtarget.cli:main"`).
4. Create `tests/__init__.py`, `tests/conftest.py` (empty), and `tests/_helpers/`, `tests/e2e/`, `tests/stubs/` directories.
5. Write `README.md` (DM-01) with installation + usage stubs; `CHANGELOG.md` (DM-07) with `0.0.1 - <date>` entry.
6. Write initial `docs/ARCHITECTURE.md` (DM-10) and `docs/PREREQUISITES.md` (DM-11) drafts based on §5 of this Dev Spec.
7. Add `.gitignore` for Python (`__pycache__`, `.venv`, `*.egg-info`, `.pytest_cache`, `htmlcov/`).
8. Add stub `.github/workflows/ci.yml` (filled in by Story 1.11; for now just `runs-on: ubuntu-latest` with no steps).
9. Initial commit on `main`.

**Test Procedures:**

*Unit Tests:* None at this stage (pure scaffold).

*Integration/E2E Coverage:* None.

**Acceptance Criteria:**

- [ ] `git clone` + `pip install -e .` succeeds in a fresh venv [DM-01, DM-02]
- [ ] `make test` succeeds (zero tests yet, but pytest runs without errors) [DM-04]
- [ ] `which ccwork-testtarget` resolves to the package's CLI entry point after install
- [ ] `README.md`, `CHANGELOG.md`, `docs/ARCHITECTURE.md`, `docs/PREREQUISITES.md` all exist and are non-empty [DM-01, DM-07, DM-10, DM-11]
- [ ] `.github/workflows/ci.yml` exists (stub OK)
- [ ] `.gitignore` excludes Python build artifacts

---

#### Story 1.2: `MCPClient` subprocess wrapper + JSON-RPC framing (#2)

**Wave:** P1W2
**Dependencies:** ["1.1"]

Implement the load-bearing MCP interaction primitive: spawn an MCP server as a subprocess, communicate via JSON-RPC over stdio, expose per-tool methods auto-generated from `tools/list`.

**Implementation Steps:**

1. Create `src/ccwork_testtarget/_helpers/mcp_subprocess.py`.
2. Implement `MCPClient` class with `__init__(self, server_cmd: list[str])`, `__enter__`, `__exit__` (subprocess lifecycle), `tools_list() -> list[Tool]`, and dynamic `__getattr__` that routes `client.<tool_name>(**kwargs)` to a JSON-RPC `tools/call` invocation.
3. Use the `mcp` Python package for protocol framing (Content-Length headers, JSON body).
4. Add a stub MCP server at `tests/stubs/echo_mcp.py` that responds to `tools/list` (returns one canned tool `echo`) and `tools/call` (returns the input args).
5. Write IT-01 in `tests/_helpers/test_mcp_subprocess.py`: spawn `tests/stubs/echo_mcp.py` via `MCPClient`, call `tools/list`, call `echo(message="hi")`, assert subprocess clean shutdown on `__exit__`.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_mcp_client_roundtrip` | Spawns stub server, exchanges `tools/list` + `tools/call`, asserts response shape | `tests/_helpers/test_mcp_subprocess.py` |
| `test_mcp_client_subprocess_cleanup` | Asserts subprocess is terminated after `MCPClient.close()` (no zombie processes) | `tests/_helpers/test_mcp_subprocess.py` |
| `test_mcp_client_unknown_tool_raises` | Calling an unknown tool method raises `AttributeError` | `tests/_helpers/test_mcp_subprocess.py` |

*Integration/E2E Coverage:*
- IT-01 — implemented here.

**Acceptance Criteria:**

- [ ] `MCPClient` spawns subprocess, exchanges JSON-RPC, returns parsed response [R-08]
- [ ] No direct imports of any MCP server's source code in `ccwork_testtarget/_helpers/mcp_subprocess.py` (verified by lint rule or grep) [R-09]
- [ ] `tools/list` schema cached on `MCPClient` instance after first call [R-08]
- [ ] All three unit tests pass

---

#### Story 1.3: `NotificationSubsystem` + `@`-mention guardrail (#3)

**Wave:** P1W2
**Dependencies:** ["1.1"]

Implement Discord posting via `mcp-server-discord`'s `disc_send` tool, with an `@`-mention regex guardrail per R-19.

**Implementation Steps:**

1. Create `src/ccwork_testtarget/_helpers/notification.py`.
2. Implement `NotificationSubsystem` class with `__init__(self, channel_id: str | None)`, `post(self, body: str) -> bool`. Reads `HARNESS_DISCORD_CHANNEL_ID` env var if `channel_id` not passed.
3. `post()` runs the `@`-mention regex `r'(?<!\w)@(?:all|here|everyone|[A-Z][a-z]+(?:[-_][A-Za-z]+)*)\b'` on `body`. If matched, emit `NOTIFICATION_ATMENTION_BLOCKED` event to `mcp.jsonl` (use `mcp-log` CLI subprocess), return `False`, do NOT call `disc_send`.
4. Otherwise, invoke `disc_send` via an `MCPClient` instance against `mcp-server-discord`. Return `True` on success.
5. Write IT-05 in `tests/_helpers/test_notification.py`: 8 candidate post bodies (4 with @-mentions, 4 without). Assert: 4 rejected, 4 accepted.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_notification_rejects_atmention_bodies` | 4 @-mention bodies rejected; structured event emitted | `tests/_helpers/test_notification.py` |
| `test_notification_accepts_clean_bodies` | 4 non-@-mention bodies accepted | `tests/_helpers/test_notification.py` |
| `test_notification_no_channel_no_post` | If `HARNESS_DISCORD_CHANNEL_ID` unset, `post()` returns `False` and skips `disc_send` (fails-loud-but-doesn't-block) | `tests/_helpers/test_notification.py` |

*Integration/E2E Coverage:*
- IT-05 — implemented here.

**Acceptance Criteria:**

- [ ] `@`-mention pattern correctly identifies all 4 known forms (`@all`, `@here`, `@everyone`, `@<DevName>`) [R-19]
- [ ] Rejection emits `NOTIFICATION_ATMENTION_BLOCKED` event to `mcp.jsonl` [R-19]
- [ ] Clean bodies post via `disc_send` and return `True` [R-18]
- [ ] All three unit tests pass

---

#### Story 1.4: Structured event emission to `mcp.jsonl` (#4)

**Wave:** P1W2
**Dependencies:** ["1.1"]

Implement the harness's structured event emitter, used by every subsequent Story to record lifecycle events.

**Implementation Steps:**

1. Create `src/ccwork_testtarget/_helpers/events.py`.
2. Define event-type enums: `tier_start`, `tier_complete`, `test_start`, `test_complete`, `test_step_start`, `test_step_complete`, `notification_atmention_blocked`, `pricing_model_unknown`, `budget_exceeded`, `tier4_timeout`, `api_unavailable`, `github_api_unavailable`, `gitlab_api_unavailable`.
3. Implement `emit(event_type: str, **kwargs)` that builds a JSON object with `{ts, event_type, source: "ccwork-testtarget", run_id, ...kwargs}` and appends to `~/.claude/logs/mcp.jsonl`.
4. Document the event schema in `docs/ARCHITECTURE.md` (DM-10 — event-emission section).
5. Provide a context-manager helper `with event_span("test_step", name="step_create_kahuna"): ...` that emits start + complete events with elapsed-time field.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_emit_writes_jsonl_line` | Single `emit()` call appends one valid JSON line to mcp.jsonl | `tests/_helpers/test_events.py` |
| `test_emit_includes_required_fields` | Every event has `ts`, `event_type`, `source`, `run_id` | `tests/_helpers/test_events.py` |
| `test_event_span_emits_start_and_complete` | Context manager emits both events + computes elapsed | `tests/_helpers/test_events.py` |

*Integration/E2E Coverage:* None at this stage; downstream Stories rely on this helper.

**Acceptance Criteria:**

- [ ] `emit()` produces valid JSON lines appended to `~/.claude/logs/mcp.jsonl` (or env-overridden path) [R-17]
- [ ] All 13 documented event types representable [R-17]
- [ ] Schema documented in `docs/ARCHITECTURE.md` [DM-10]
- [ ] All three unit tests pass

---

#### Story 1.5: Tier 0 static checks (#5)

**Wave:** P1W3
**Dependencies:** ["1.2", "1.4"]

Implement Tier 0: required CLIs on PATH, MCP server `tools/list` snapshots, skill frontmatter parse, MEMORY.md integrity, WAVE_AXIOMS.md presence.

**Implementation Steps:**

1. Create `src/ccwork_testtarget/tier0.py` with `run_tier0() -> Tier0Result` returning per-check pass/fail + total exit code.
2. Implement check: `cli_on_path` — assert each of `wave-status`, `generate-status-panel`, `mcp-log`, `gh`, `glab`, `bun`, `trivy`, `jq` resolves via `shutil.which`.
3. Implement check: `mcp_tools_snapshot` — for each MCP server in active config, spawn via `MCPClient`, fetch `tools/list`, compare per-server tool count against `tests/snapshots/mcp_tools_count.yml` (checked-in snapshot).
4. Implement check: `skill_frontmatter_parse` — walk `~/.claude/skills/*/SKILL.md`, parse frontmatter as YAML, assert valid.
5. Implement check: `memory_md_integrity` — read `~/.claude/projects/<project-hash>/memory/MEMORY.md`, assert each linked file exists; assert each file in `memory/` is referenced.
6. Implement check: `wave_axioms_presence` — read `WAVE_AXIOMS.md`, assert presence and 9-axiom count (regex `^## Axiom \d+` — note: two hashes; the file uses H2 headings, not H3).
7. Implement check: `harness_no_mcp_imports` — grep `src/ccwork_testtarget/` for `from mcp_server_*` or `import mcp_server_*`; fail if any matches (R-09).
8. Implement check: `pricing_model_known` — read active pricing.yml, emit `PRICING_MODEL_UNKNOWN` warning if a model referenced in recent runs isn't listed (DC-13).
9. Wire `tier0` into the CLI's `--tier 0` dispatch (filled in by Story 1.10).

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_tier0_cli_on_path_pass` | Mock PATH with all 8 CLIs present → check passes | `tests/_helpers/test_tier0.py` |
| `test_tier0_cli_on_path_fail` | Mock PATH with one CLI missing → check fails with named CLI | `tests/_helpers/test_tier0.py` |
| `test_tier0_mcp_tools_snapshot_drift` | MCP server returns different tool count than snapshot → check fails | `tests/_helpers/test_tier0.py` |
| `test_tier0_harness_no_mcp_imports` | Inject a fake `from mcp_server_sdlc import ...` line → check fails | `tests/_helpers/test_tier0.py` |

*Integration/E2E Coverage:*
- E2E-01 — covers Tier 0 CLI invocation (depends on Story 1.10).

**Acceptance Criteria:**

- [ ] All 7 documented Tier 0 checks implemented [R-10]
- [ ] Each check emits `tier_start` / `tier_complete` event with per-check status [R-17]
- [ ] Tier 0 returns non-zero on any failure; structured event names the failed check [R-10]
- [ ] All four unit tests pass

---

#### Story 1.6: Tier 1 — MCP server `bun test` wiring (#6)

**Wave:** P1W3
**Dependencies:** ["1.4"]

Wire each of the four MCP server `bun test` suites into Tier 1.

**Implementation Steps:**

1. Create `src/ccwork_testtarget/tier1/mcp_servers.py`.
2. Read MCP server clone-paths from `tests/snapshots/mcp_servers.yml` (checked-in: 4 entries — sdlc, discord, nerf, wtf — with git URLs and pin shas).
3. For each entry: clone to a tmpdir (or reuse cached clone if present and pin matches), `bun install`, `bun test --reporter junit`, parse JUnit XML, aggregate results.
4. Emit `test_start` / `test_complete` events per MCP server.
5. Aggregate results into a per-server pass/fail summary for the Tier 1 report.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_tier1_mcp_clone_and_test_pass` | Mock `bun test` returning success JUnit XML → server marked pass | `tests/_helpers/test_tier1_mcp.py` |
| `test_tier1_mcp_clone_and_test_fail` | Mock `bun test` returning failure JUnit XML → server marked fail with parsed failure messages | `tests/_helpers/test_tier1_mcp.py` |
| `test_tier1_mcp_aggregates_all_four` | Mock all 4 servers; aggregate report has 4 entries | `tests/_helpers/test_tier1_mcp.py` |

*Integration/E2E Coverage:*
- E2E-02 — covers full Tier 1 invocation (depends on Story 1.10).

**Acceptance Criteria:**

- [ ] All 4 MCP server `bun test` suites can be invoked through the harness [R-11]
- [ ] Per-server JUnit XML parsed correctly [R-11]
- [ ] Failures aggregate cleanly; one failed server doesn't abort the others (per R-02 spirit) [R-02]
- [ ] All three unit tests pass

---

#### Story 1.7: Tier 1 — bus-script unit tests in tmpdir (#7)

**Wave:** P1W3
**Dependencies:** ["1.4"]

Implement Tier 1 unit tests for the four bus scripts (`wave-init`, `flight-finalize`, `changelog-aggregate`, `wave-cleanup`), all running in tmpdir per `lesson_destructive_test_homedir.md`.

**Implementation Steps:**

1. Create `src/ccwork_testtarget/tier1/bus_scripts.py`.
2. For each bus script: define a pytest fixture that creates a tmpdir, copies the bus script to the tmpdir, exercises it with known inputs, asserts known outputs, tears down tmpdir.
3. `wave-init` test: `wave-init <slug> 1 1` creates expected directory tree; idempotent on second invocation.
4. `flight-finalize` test: writes `results.md.partial`, calls `flight-finalize`, asserts atomic rename to `results.md` + `DONE` file with `PASS`/`FAIL`.
5. `changelog-aggregate` test: 3 known fragment files → aggregates to one CHANGELOG entry without duplication; "no fragments" case handled gracefully.
6. `wave-cleanup` test: removes per-wave bus dir, leaves siblings alone.
7. All tests use `pytest`'s `tmp_path` fixture; no test touches real `$HOME` or `/tmp/wavemachine/`.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_wave_init_creates_directory_tree` | `wave-init <slug> 1 1` produces expected tree | `tests/_helpers/test_tier1_bus.py` |
| `test_wave_init_idempotent` | Second invocation succeeds without error | `tests/_helpers/test_tier1_bus.py` |
| `test_flight_finalize_atomic_rename` | `.partial` → final rename + DONE file | `tests/_helpers/test_tier1_bus.py` |
| `test_changelog_aggregate_three_fragments` | 3 fragments → 1 entry, no duplication | `tests/_helpers/test_tier1_bus.py` |
| `test_changelog_aggregate_no_fragments` | "No fragments" case handled gracefully | `tests/_helpers/test_tier1_bus.py` |
| `test_wave_cleanup_removes_only_target` | Sibling waves untouched | `tests/_helpers/test_tier1_bus.py` |
| `test_no_bus_test_touches_homedir` | All tests use `tmp_path`; verify via grep on test source | `tests/_helpers/test_tier1_bus.py` |

*Integration/E2E Coverage:*
- E2E-02 — covers full Tier 1 invocation.

**Acceptance Criteria:**

- [ ] All 4 bus scripts tested in tmpdir [R-11, TC-03]
- [ ] No test references `$HOME`, `~/.claude/`, `/tmp/wavemachine/` (verified by grep) [TC-03]
- [ ] All seven unit tests pass

---

#### Story 1.8: Tier 1 — status-panel snapshot test (#8)

**Wave:** P1W3
**Dependencies:** ["1.4"]

Implement the status-panel HTML snapshot test (regression target for cc#631-class bugs).

**Implementation Steps:**

1. Create `src/ccwork_testtarget/tier1/status_panel.py`.
2. Create `tests/snapshots/status_panel_input.json` — a known fixture state JSON containing typical wave-pattern state (one Plan, two Phases, three Waves, mix of pending/done Stories, optional kahuna_branch).
3. Create `tests/snapshots/status_panel_expected.html` — the HTML output produced by `generate-status-panel < status_panel_input.json` at the time the snapshot was captured.
4. Test: feed `status_panel_input.json` to `generate-status-panel`, capture stdout, byte-equal compare against `status_panel_expected.html`.
5. On mismatch, the test fails with a `diff` of the first 50 lines of difference. Operator can update the snapshot via `make snapshot-update` (a Makefile target that re-runs the generator and overwrites the expected file).

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_status_panel_snapshot_match` | Generated HTML byte-equal to expected | `tests/_helpers/test_tier1_status_panel.py` |
| `test_status_panel_handles_null_kahuna_branch` | Input with `kahuna_branch: null` doesn't AttributeError (cc#631 regression) | `tests/_helpers/test_tier1_status_panel.py` |

*Integration/E2E Coverage:*
- E2E-02 — covers full Tier 1 invocation.

**Acceptance Criteria:**

- [ ] Snapshot test fails byte-loudly on any HTML drift [R-12]
- [ ] Null `kahuna_branch` regression specifically covered [R-12]
- [ ] `make snapshot-update` regenerates the expected file [DM-02]
- [ ] Both unit tests pass

---

#### Story 1.9: Tier 6 observability checks (#9)

**Wave:** P1W3
**Dependencies:** ["1.3", "1.4"]

Implement Tier 6: `mcp.jsonl` schema validation, status-panel snapshot rerun, Discord post round-trip, `vox` best-effort logging.

**Implementation Steps:**

1. Create `src/ccwork_testtarget/tier6.py`.
2. Implement check: `mcp_jsonl_schema` — read recent N lines from `~/.claude/logs/mcp.jsonl`; for each, validate against the documented schema (DM-10). Fail if any malformed line.
3. Implement check: `status_panel_smoke` — run Story 1.8's snapshot test once more (ensures the panel can render in current env).
4. Implement check: `discord_round_trip` — post a test message via `NotificationSubsystem` to the configured channel; assert post succeeds. Skip with `[SKIPPED]` if `HARNESS_DISCORD_CHANNEL_ID` unset.
5. Implement check: `vox_best_effort_log` — invoke `vox "test"` (best-effort); verify a log line was emitted whether or not vox actually spoke (per `lesson_best_effort_must_log.md`).

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_tier6_mcp_jsonl_schema_pass` | Valid jsonl lines pass schema check | `tests/_helpers/test_tier6.py` |
| `test_tier6_mcp_jsonl_schema_fail` | One malformed line → check fails with line number | `tests/_helpers/test_tier6.py` |
| `test_tier6_discord_skip_when_unset` | Channel unset → `[SKIPPED]` not failure | `tests/_helpers/test_tier6.py` |
| `test_tier6_vox_logs_even_when_silent` | vox unavailable → log entry still produced | `tests/_helpers/test_tier6.py` |

*Integration/E2E Coverage:*
- E2E-04 — covers full nightly mode (depends on Story 1.10).

**Acceptance Criteria:**

- [ ] All 4 documented Tier 6 checks implemented [R-17, R-18]
- [ ] Discord skip-when-unset doesn't fail Tier 6 [R-18]
- [ ] vox best-effort logging verified [DM-09 troubleshoot section]
- [ ] All four unit tests pass

---

#### Story 1.10: Tier-execution runner + `--tier` CLI (#10)

**Wave:** P1W4
**Dependencies:** ["1.5", "1.6", "1.7", "1.8", "1.9"]

Implement the harness's CLI entry point: `--tier <list>` flag, per-tier dispatch, on-error continue-to-next-tier per R-02.

**Implementation Steps:**

1. Edit `src/ccwork_testtarget/cli.py`. Use `argparse` with arguments: `--tier <list>` (comma-separated, default all enabled tiers), `--keep-state` (Phase 2), `--bisect <step>` (Phase 2), `--replay-from <path>` (Phase 2), `--post-test-message` (one-off message for MV-01).
2. Per `--tier` arg, dispatch to `tier0.run_tier0()`, `tier1.run_tier1()`, `tier4.run_tier4()` (Phase 2 stub for now), `tier6.run_tier6()`.
3. Implement R-02: collect results from all dispatched tiers; do not early-exit on tier failure. Final exit code is non-zero iff any tier failed.
4. After all tiers run, post Discord summary via `NotificationSubsystem` (Story 1.3).
5. Wire `mcp-log` event emission per R-17 around each tier's start/complete.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_cli_default_runs_all_enabled_tiers` | `ccwork-testtarget` with no args invokes Tier 0/1/(4-stub)/6 in order | `tests/e2e/test_cli.py` |
| `test_cli_tier_filter_runs_only_named` | `--tier 0` runs only Tier 0; others not invoked | `tests/e2e/test_cli.py` |
| `test_cli_continues_on_tier_failure` | Tier 1 fails → Tier 4 + 6 still run; exit code reflects failure | `tests/e2e/test_cli.py` |
| `test_cli_post_test_message_skips_tiers` | `--post-test-message "hi"` posts via NotificationSubsystem and exits | `tests/e2e/test_cli.py` |

*Integration/E2E Coverage:*
- E2E-01, E2E-02, E2E-04 — implemented here (Tier 4 still stubbed).

**Acceptance Criteria:**

- [ ] `ccwork-testtarget --tier 0` runs Tier 0 only [R-03]
- [ ] `ccwork-testtarget` (no flags) runs Tier 0 → 1 → 4-stub → 6 [R-01]
- [ ] One tier failing does not prevent subsequent tiers from running [R-02]
- [ ] Discord summary post fires after all tiers complete [R-18]
- [ ] All four unit tests pass

---

#### Story 1.11: GitHub Actions CI (#11)

**Wave:** P1W4
**Dependencies:** ["1.2", "1.3", "1.4"]

Set up GitHub Actions CI for the harness's own helper-code unit tests (DM-04, DM-05, DM-06). GitHub-hosted runners only per DC-16.

**Implementation Steps:**

1. Edit `.github/workflows/ci.yml` (stubbed in Story 1.1).
2. Workflow: trigger on `push` and `pull_request`; runs-on `ubuntu-latest`; Python 3.11 setup; `pip install -e .`; `pytest --cov=src/ccwork_testtarget --cov-report=xml --junit-xml=test-results.xml tests/_helpers/`.
3. Upload `test-results.xml` and `coverage.xml` as workflow artifacts.
4. Add a coverage badge to `README.md` (Codecov or shields.io static badge updated by CI).
5. Workflow does NOT invoke Tier 4 tests (`tests/e2e/` is excluded from CI per DC-16).
6. Document the CI shape in `docs/ARCHITECTURE.md` (DM-10).

**Test Procedures:**

*Unit Tests:* None (CI workflow itself).

*Integration/E2E Coverage:* CI green on a smoke PR.

**Acceptance Criteria:**

- [ ] Workflow runs on every PR + push to main [DM-03]
- [ ] JUnit XML uploaded as artifact [DM-05]
- [ ] Coverage XML uploaded as artifact; coverage badge in README [DM-06]
- [ ] Tier 4 tests excluded from CI run (verified via `pytest --collect-only` output) [DC-16, TC-07]
- [ ] CI green on a smoke PR (e.g., README typo) before merging Story 1.11

---

#### Story 1.12: Nightly cron deployment + state directories (#12)

**Wave:** P1W5
**Dependencies:** ["1.10", "1.11"]

Deploy the nightly cron on the dedicated host. Create state directories. Write the operator runbook's Tier 0/1/6 sections.

**Implementation Steps:**

1. Create state directories on the dedicated host: `/var/harness/forensics/`, `/var/harness/keepstate/`, `/var/log/harness/`.
2. Operator-side: `crontab -e` adds `0 0 * * * cd /home/operator/ccwork-testtarget && source ~/.harness.env && .venv/bin/ccwork-testtarget >> /var/log/harness/nightly.log 2>&1`.
3. Set up `~/.harness.env` with `ANTHROPIC_API_KEY`, `HARNESS_GITHUB_TOKEN`, `HARNESS_GITLAB_TOKEN`, `HARNESS_DISCORD_CHANNEL_ID`.
4. Run `ccwork-testtarget --tier 0` on the host as a smoke test.
5. Write Phase 1 sections of `docs/RUNBOOK.md` (DM-09): install, configure env, verify, troubleshoot Tier 0/1/6 failures.
6. Write `docs/DEPLOYMENT.md` (DM-12): cron config, systemd-timer alternative, state-dir layout, env-var override.
7. Wait one calendar night with cron firing; observe Discord post lands; archive `/var/log/harness/nightly.log` for the run.

**Test Procedures:**

*Unit Tests:* None (deployment + manual verification).

*Manual Verification:*
- MV-01: Discord post lands in `$HARNESS_DISCORD_CHANNEL_ID`.
- MV-02: Cron fires at 00:00; output in `/var/log/harness/nightly.log`.

**Acceptance Criteria:**

- [ ] Cron job installed and visible in `crontab -l` [PC-01]
- [ ] State directories created with correct permissions [DM-12]
- [ ] `~/.harness.env` configured with all 4 required env vars [TC-06]
- [ ] One nightly run completes unattended; Discord post lands [PC-01, R-01, R-18]
- [ ] DM-09 (Phase 1 sections), DM-12 written and current [DM-09, DM-12]

---

### Phase 2: Tier 4 v0

**Goal:** Ship Tier 4 e2e tests (Tests 4.1, 4.6, 4.8) running nightly against real fixture repos, with forensic-replay tooling and the self-validation contract demonstrated.

#### Phase 2 Definition of Done

- [ ] All 9 Phase 2 Stories merged [R-04 through R-22]
- [ ] `ccwork-testtarget --tier 4` (or full nightly) exercises Tests 4.1, 4.6, 4.8 against real fixture repos; all three pass [R-13, R-14, R-15]
- [ ] One Plan #607 follow-up bug has a corresponding red Tier 4 test that turns green when the production fix lands (red→green pair preserved in test history) [R-20, PC-04]
- [ ] `ccwork-testtarget --tier 4 --keep-state` then `--bisect <step> --replay-from <path>` reproduces a deliberately-broken Tier 4 run [R-06, R-16]
- [ ] 7 consecutive nights of unattended cron runs on the dedicated host: nightly Discord summaries land, no `@`-mention rejections, no fixture-state leak, cost averages within $4–8/night band [PC-01, PC-02, PC-04, PC-05]
- [ ] DM-09 (Tier 4 sections), DM-12 (Tier 4 deployment), DM-13 (manual verification), DM-08 (VRTM), CHANGELOG v0.1.0 entry — all present and current
- [ ] All Phase 2 unit tests + E2E tests pass

---

#### Story 2.1: `FixtureLifecycle` helper (#13)

**Wave:** P2W1
**Dependencies:** ["1.12"]

Implement per-run-id fixture-repo lifecycle for both GitHub (per-run-id repos) and GitLab (long-lived project + per-run-id-prefixed branches/MRs/issues + 7-day stale cleanup).

**Implementation Steps:**

1. Create `src/ccwork_testtarget/_helpers/fixture_lifecycle.py`.
2. Implement `RunId.generate() -> str` returning `<UTC-YYYYMMDD>-<8-char-hex>` per DC-02.
3. Implement `FixtureLifecycle.create_github_repo(run_id, suffix="")` that calls `gh repo create Wave-Engineering/harness-target-<run-id><suffix> --private` and seeds with a minimal commit (README + `.github/workflows/ci.yml` for the trust-signal gate).
4. Implement `FixtureLifecycle.create_github_cross_repo(run_id)` that creates two repos `harness-target-<run-id>-a` and `-b` for Test 4.6.
5. Implement `FixtureLifecycle.teardown_github(run_id)` that calls `gh repo delete --yes` for every repo with the prefix.
6. Implement `FixtureLifecycle.create_gitlab_branch_set(run_id)` that creates per-run-id-prefixed branches/MRs/issues in `gitlab.com/testtarget/harness-fixture` via `glab`.
7. Implement `FixtureLifecycle.teardown_gitlab(run_id)` that deletes only artifacts with the run-id prefix.
8. Implement `FixtureLifecycle.cleanup_stale_gitlab(older_than_days=7)` that walks all artifacts, parses run-ids, deletes any with date prefix older than 7 days.
9. Negative test: `FixtureLifecycle.create_repo` MUST raise `NamespaceViolation` if asked to create outside `Wave-Engineering/` or `gitlab.com/testtarget/`.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_runid_format` | Generated run-id matches `^\d{8}-[0-9a-f]{8}$` | `tests/_helpers/test_fixture_lifecycle.py` |
| `test_create_github_repo_naming` | `gh repo create` called with `harness-target-<run-id>` | `tests/_helpers/test_fixture_lifecycle.py` |
| `test_teardown_github_only_prefix` | Only matching prefix repos deleted; siblings untouched | `tests/_helpers/test_fixture_lifecycle.py` |
| `test_namespace_violation_on_non_harness_create` | Refuses to create outside harness namespaces | `tests/_helpers/test_fixture_lifecycle.py` |
| `test_cleanup_stale_gitlab_7day` | Mock gitlab artifacts of varying ages → only >7d deleted | `tests/_helpers/test_fixture_lifecycle.py` |

*Integration/E2E Coverage:*
- IT-02, IT-03 — implemented here.

**Acceptance Criteria:**

- [ ] Run-id format matches DC-02 [R-04]
- [ ] GitHub repo create / delete works for both single-repo and cross-repo cases [R-04, R-05]
- [ ] GitLab branch-set create / delete works on the long-lived project [R-04, R-05]
- [ ] Stale cleanup runs at start of nightly per DC-04 [R-05]
- [ ] Namespace violation raised if asked to create outside harness namespaces [R-07]
- [ ] All five unit tests pass

---

#### Story 2.2: `ForensicGenerator` + `KeepState` (#14)

**Wave:** P2W1
**Dependencies:** ["1.12"]

Implement on-failure forensic doc generation + state preservation per DC-08, DC-09, DC-14.

**Implementation Steps:**

1. Create `src/ccwork_testtarget/_helpers/forensic.py`.
2. Implement `ForensicGenerator.merge_timeline(harness_events, mcp_jsonl_slice) -> list[Event]` that interleaves both streams sorted by timestamp.
3. Implement `ForensicGenerator.render(test_id, run_id, failure_summary, timeline, preserved_state_inventory, bisect_hint) -> str` returning the Markdown forensic doc per DC-08.
4. Implement `ForensicGenerator.persist(doc_md, run_id, test_id) -> Path` writing to `/var/harness/forensics/<run-id>-<test-id>.md` (env-overridable via `HARNESS_FORENSICS_DIR`).
5. Create `src/ccwork_testtarget/_helpers/keep_state.py`.
6. Implement `KeepState.preserve(run_id, test_id, bus_dir, worktrees, mcp_jsonl_slice)` that copies all to `/var/harness/keepstate/<run-id>-<test-id>/`.
7. Implement `KeepState` wired into the Tier 4 test runner's failure path (Story 2.4): only on FAIL + only when `--keep-state` set.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_merge_timeline_chronological` | Two known event streams → output sorted by ts | `tests/_helpers/test_forensic.py` |
| `test_render_byte_equal_to_snapshot` | Known input → byte-equal Markdown output | `tests/_helpers/test_forensic.py` |
| `test_persist_writes_to_correct_path` | Doc written to expected forensics path | `tests/_helpers/test_forensic.py` |
| `test_keepstate_preserves_on_failure` | Failure + --keep-state → bus dir + worktrees + mcp.jsonl slice copied | `tests/_helpers/test_keep_state.py` |
| `test_keepstate_no_op_on_pass` | Passing test → nothing preserved | `tests/_helpers/test_keep_state.py` |
| `test_keepstate_no_op_when_flag_off` | Failure + no --keep-state → nothing preserved | `tests/_helpers/test_keep_state.py` |

*Integration/E2E Coverage:*
- IT-04, IT-08, IT-09 — implemented here.

**Acceptance Criteria:**

- [ ] Forensic doc is byte-equal across deterministic re-runs [R-16, DC-09]
- [ ] Persistence path matches DC-08 default + env-override [R-16]
- [ ] KeepState only fires on FAIL + flag set [R-06]
- [ ] All six unit tests pass

---

#### Story 2.3: `CostTracker` + `pricing.yml` (#15)

**Wave:** P2W1
**Dependencies:** ["1.12"]

Implement per-run cost tracking via mcp.jsonl `tool_call` event token-counts × `pricing.yml` rates. Implement R-21 budget overage detection.

**Implementation Steps:**

1. Create `src/ccwork_testtarget/_helpers/cost_tracker.py`.
2. Read `pricing.yml` (checked-in flat YAML keyed by model name with `input_per_mtok` and `output_per_mtok` rates per DC-12, DC-13).
3. Implement `CostTracker.compute_run_cost(run_id) -> float` that walks `mcp.jsonl` for the run, sums per-tool `usage.input_tokens + usage.output_tokens`, multiplies by pricing.
4. If a model in mcp.jsonl is not in `pricing.yml`, emit `PRICING_MODEL_UNKNOWN` warning event; cost reported as `null` for that model's contribution (not zero).
5. Implement `CostTracker.detect_budget_overage(history_days=2) -> bool` that returns True iff the last 2 nightly runs both exceeded $8 (R-21).
6. On detection: emit `BUDGET_EXCEEDED` event to mcp.jsonl; subsequent run fails the build via non-zero exit.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_compute_run_cost_known_model` | Known token counts + pricing.yml → known dollar figure (4-decimal) | `tests/_helpers/test_cost_tracker.py` |
| `test_unknown_model_emits_warning` | Model absent from pricing.yml → PRICING_MODEL_UNKNOWN event + null cost | `tests/_helpers/test_cost_tracker.py` |
| `test_budget_overage_two_consecutive` | 2 consecutive nights >$8 → BUDGET_EXCEEDED detected | `tests/_helpers/test_cost_tracker.py` |
| `test_budget_overage_only_one_night` | 1 night >$8, 1 night <=$8 → no BUDGET_EXCEEDED | `tests/_helpers/test_cost_tracker.py` |

*Integration/E2E Coverage:*
- IT-06, IT-07 — implemented here.

**Acceptance Criteria:**

- [ ] Cost computation matches manual calculation to ±0.01 USD [R-21]
- [ ] Unknown-model warning emitted with model name [DC-13]
- [ ] BUDGET_EXCEEDED detection requires 2 consecutive overage nights [R-21]
- [ ] All four unit tests pass

---

#### Story 2.4: Tier 4 driver — `claude` CLI subprocess invocation (#16)

**Wave:** P2W2
**Dependencies:** ["2.1", "2.2", "2.3"]

Implement the load-bearing Tier 4 mechanism: spawning the real `claude` CLI as a subprocess with harness-controlled environment.

**Implementation Steps:**

1. Create `src/ccwork_testtarget/tier4/driver.py`.
2. Implement `Tier4Driver.invoke_wavemachine(prompt: str, fixture_repo_path: str, env_overrides: dict) -> Tier4Result`:
   - Construct env: `CLAUDE_PROJECT_DIR=<fixture_repo_path>`; `ANTHROPIC_API_KEY=<from harness env>`; tmpdir paths for `~/.config/claude-code/mcp.json` (override pointing at the harness-managed MCP server config) and `~/.claude/projects/...`.
   - Invoke `subprocess.Popen(['claude', '--print', '--dangerously-skip-permissions'], stdin=PIPE, stdout=PIPE, stderr=PIPE, env=...)`.
   - Pipe `prompt` to stdin; capture stdout/stderr; track wall-clock elapsed.
   - On wall-clock > `HARNESS_TIER4_TIMEOUT_SEC` (default 60 min): kill subprocess, emit `TIER4_TIMEOUT` event, return failure.
3. Implement `Tier4Driver.parse_terminal_state(mcp_jsonl_path) -> dict` that reads the post-invocation mcp.jsonl slice and extracts kahuna_branch, kahuna→main MR number, gate signal envelope, etc.
4. Define `Tier4TestBase` class with named step methods (`step_create_kahuna`, `step_run_gate`, `step_merge_kahuna`, `step_teardown`) for `--bisect` (Story 2.8).
5. On any subprocess invocation failure: invoke ForensicGenerator + KeepState (Story 2.2) per failure path.
6. On Anthropic API outage: per Open Question Q6, emit `API_UNAVAILABLE` event; abort remaining Tier 4 tests for the run.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_driver_constructs_env_correctly` | Env-override dict contains all required keys with correct values | `tests/_helpers/test_tier4_driver.py` |
| `test_driver_timeout_kills_subprocess` | Subprocess that exceeds timeout is SIGKILL'd; TIER4_TIMEOUT event emitted | `tests/_helpers/test_tier4_driver.py` |
| `test_driver_parses_terminal_state_kahuna_branch` | Known mcp.jsonl slice → extracted kahuna_branch matches | `tests/_helpers/test_tier4_driver.py` |
| `test_driver_api_unavailable_short_circuits` | Mock 429 from API → API_UNAVAILABLE event + remaining tests skipped | `tests/_helpers/test_tier4_driver.py` |

*Integration/E2E Coverage:*
- E2E-03 (with stub /wavemachine), E2E-06 (deliberate failure), E2E-07 (full replay loop).

**Acceptance Criteria:**

- [ ] Subprocess invocation with full env-override succeeds against a stub /wavemachine [DC-07]
- [ ] Watchdog timeout fires at configured limit [Open Q5 lean]
- [ ] Terminal state parsing extracts kahuna_branch + MR number from mcp.jsonl [R-13]
- [ ] API outage handling per Open Q6 lean [Open Q6]
- [ ] All four unit tests pass

---

#### Story 2.5: Tier 4 Test 4.1 — GitHub single-flight (#17)

**Wave:** P2W3
**Dependencies:** ["2.4"]

Implement Test 4.1: the smoke test for the entire wave-pattern pipeline.

**Implementation Steps:**

1. Create `tests/test_tier4_e2e.py::TestTier4_GitHubSingleFlight`.
2. Use `FixtureLifecycle.create_github_repo(run_id)` to create the fixture repo; seed with a single fixture Story issue (one-file change).
3. Use `Tier4Driver.invoke_wavemachine(prompt='/wavemachine', fixture_repo_path=...)` to drive the full campaign.
4. Assert all 7 R-13 conditions: kahuna branch via `wave_init`, kahuna→main MR via `wave_finalize`, gate ran 4 trust signals concurrently, `pr_merge` landed, observability events, status-panel terminal-state, teardown clean.
5. Use `FixtureLifecycle.teardown_github(run_id)` on success.
6. Document Test 4.1 in `docs/RUNBOOK.md` (DM-09): what it tests, expected wall-clock, expected cost, common failure modes.

**Test Procedures:**

*Unit Tests:* None (this Story IS the test).

*Integration/E2E Coverage:*
- (Test 4.1 itself is the verification artifact for R-13.)

**Acceptance Criteria:**

- [ ] Test 4.1 passes against a fresh fixture repo [R-13]
- [ ] All 7 R-13 sub-assertions are checked individually (each gets its own pytest assertion line) [R-13]
- [ ] Teardown removes the fixture repo on success [R-05]
- [ ] DM-09 Test 4.1 section written
- [ ] Test 4.1 documented in DM-08 VRTM

---

#### Story 2.6: Tier 4 Test 4.8 — GitLab single-flight (#18)

**Wave:** P2W3
**Dependencies:** ["2.4"]

Implement Test 4.8: parametrized 4.1 against `gitlab.com/testtarget/harness-fixture` plus GitLab-specific assertions.

**Implementation Steps:**

1. Create `tests/test_tier4_e2e.py::TestTier4_GitLabSingleFlight`.
2. Use `FixtureLifecycle.create_gitlab_branch_set(run_id)` to seed branch + issue + MR in the long-lived project.
3. Drive `/wavemachine` against the GitLab fixture; assert all R-13 conditions plus R-14: `glab` adapter parity for the seven PR/MR methods; merge-train-warning emitted to Discord before `pr_merge`; approval rule scoped via `protected_branch_ids` permits the auto-merge; `skip_train: true` interpreted per platform.
4. Test reuses Story 2.5's structure with `@pytest.mark.parametrize("platform", ["github", "gitlab"])` where feasible; GitLab-specific assertions live in a separate test method.
5. Document Test 4.8 in `docs/RUNBOOK.md`.

**Test Procedures:**

*Unit Tests:* None.

*Integration/E2E Coverage:*
- (Test 4.8 is the verification artifact for R-14.)

**Acceptance Criteria:**

- [ ] Test 4.8 passes against the GitLab fixture project [R-14]
- [ ] All R-14 GitLab-specific sub-assertions checked [R-14]
- [ ] Teardown removes only run-id-prefixed artifacts; long-lived project unchanged [R-05, DC-04]
- [ ] DM-09 Test 4.8 section written

---

#### Story 2.7: Tier 4 Test 4.6 — cross-repo (#19)

**Wave:** P2W3
**Dependencies:** ["2.4"]

Implement Test 4.6: cross-repo wave (Plan in repo A, Stories in repo B) with worktree pre-creation, dual kahuna branches, and dual kahuna→main MRs.

**Implementation Steps:**

1. Create `tests/test_tier4_e2e.py::TestTier4_CrossRepo`.
2. Use `FixtureLifecycle.create_github_cross_repo(run_id)` to create two fixture repos.
3. Pre-create worktrees in repo B per cross-repo recipe.
4. Drive `/wavemachine` with the cross-repo Plan; assert all R-15 conditions: pre-created worktrees in repo B, `gh -R` scoping, no `isolation: "worktree"` flag misuse, kahuna branches in BOTH repos, both kahuna→main MRs land, `wave-status` state in master plan repo, worktree teardown unlocks before force-removal.
5. Document Test 4.6 in `docs/RUNBOOK.md`.

**Test Procedures:**

*Unit Tests:* None.

*Integration/E2E Coverage:*
- (Test 4.6 is the verification artifact for R-15.)

**Acceptance Criteria:**

- [ ] Test 4.6 passes end-to-end [R-15]
- [ ] All R-15 cross-repo-specific sub-assertions checked [R-15]
- [ ] Worktree teardown unlocks before force-removal (per cross-repo recipe) [R-15]
- [ ] DM-09 Test 4.6 section written

---

#### Story 2.8: `--bisect` and `--keep-state` runtime mechanics (#20)

**Wave:** P2W4
**Dependencies:** ["2.5", "2.6", "2.7"]

Wire the runtime mechanics for `--keep-state` (already preserved by Story 2.2 helpers) and `--bisect <step> --replay-from <path>`.

**Implementation Steps:**

1. Edit `src/ccwork_testtarget/cli.py` to handle `--bisect <step>` and `--replay-from <path>` arg combination.
2. Implement `BisectRunner.replay(step_name, keepstate_path) -> Tier4Result`: load preserved state from `keepstate_path`, find the named step method on the appropriate Tier 4 test class, invoke it with pre-loaded state.
3. Document the bisect-step name registry: each Tier 4 test class exposes step names in a class-level constant; `--bisect` validates the name against the registry before invocation.
4. Update `docs/RUNBOOK.md` with the forensic-replay workflow (operator copies bisect hint command from the forensic doc → re-runs harness → reproduces failure).
5. Implement E2E-05 and E2E-07.

**Test Procedures:**

*Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_bisect_unknown_step_errors` | Unknown step name → clear error message + exit 2 | `tests/e2e/test_bisect.py` |
| `test_bisect_loads_state_correctly` | Mocked replay-from path → state loaded into test class | `tests/e2e/test_bisect.py` |
| `test_bisect_executes_only_named_step` | Step methods other than the named one are NOT invoked | `tests/e2e/test_bisect.py` |

*Integration/E2E Coverage:*
- E2E-05, E2E-07 — implemented here.

**Acceptance Criteria:**

- [ ] `--bisect <step> --replay-from <path>` re-executes only the named step [R-06, DC-15]
- [ ] Unknown step name produces clear error [DC-15]
- [ ] DM-09 forensic-replay workflow documented [DM-09]
- [ ] All three unit tests pass

---

#### Story 2.9: Self-validation contract — red Tier 4 test for one Plan #607 bug (#21)

**Wave:** P2W4
**Dependencies:** ["2.5", "2.6", "2.7"]

Pick one Plan #607 follow-up bug, implement a red Tier 4 test that fails on `main` against the bug, demonstrate the test turns green when the production fix lands. This is the load-bearing acceptance criterion for "ship the harness" (PC-04 / R-20). Also finalizes DM-08 VRTM and DM-13 manual verification doc.

**Implementation Steps:**

1. Pair-pick one bug from cc#629–#638, sdlc#425, or successor list. Document selection rationale in DM-13.
2. Add a Tier 4 test (`tests/test_tier4_e2e.py::TestSelfValidation_<BugRef>`) that exercises the failure mode the bug describes; assert correct behavior; verify the test fails on current `main` before the production fix.
3. Land the production fix in the corresponding production repo (cc-workflow or mcp-server-sdlc) via the standard /wavemachine flow.
4. Re-run the harness Tier 4; verify the previously-red test now passes.
5. Preserve both red and green test runs in the harness's test history (commit logs + CI artifacts) — the audit trail.
6. Finalize DM-08 (VRTM in Appendix V): update every `pending` cell to `verified` for R-NN that has a passing test.
7. Write DM-13 (Manual Verification Procedures): operator runbook entries for MV-01 through MV-06 with expected outputs.

**Test Procedures:**

*Unit Tests:* None (the self-validation test IS the verification).

*Integration/E2E Coverage:*
- The selected bug's red→green Tier 4 test IS the artifact.

**Acceptance Criteria:**

- [ ] One Plan #607 follow-up bug selected; selection documented in DM-13 [R-20, PC-04]
- [ ] Red Tier 4 test exists; demonstrably fails on the pre-fix commit [R-20]
- [ ] Production fix lands; harness Tier 4 turns green; commit history preserves red→green pair [R-20]
- [ ] DM-08 VRTM finalized: every R-NN cell flipped from `pending` to `verified` (or `pending` flagged for follow-up) [DM-08]
- [ ] DM-13 written; covers MV-01 through MV-06 [DM-13]
- [ ] CHANGELOG.md updated with v0.1.0 release entry [DM-07]

---

## 9. Appendices

### Appendix A: Glossary

| Term | Definition |
|------|------------|
| **Harness** | The `Wave-Engineering/ccwork-testtarget` repo and CLI; the deliverable of Plan: Gamma. |
| **System under test (SUT)** | The wave-pattern pipeline: cc-workflow + MCP fleet + skills + bus scripts + KAHUNA. |
| **Tier** | Test-coverage layer (0/1/4/6 for v0). |
| **Run-id** | `<UTC-YYYYMMDD>-<8-char-hex>` (DC-02). One per harness invocation. |
| **Fixture repo** | Throwaway repo (GitHub) or branch/MR/issue set (GitLab) created and torn down per Tier 4 test. |
| **Forensic doc** | Single Markdown file produced on Tier 4 failure; reconstructs failure timeline. |
| **Keepstate dir** | `/var/harness/keepstate/<run-id>-<test-id>/` — preserves bus dirs, worktrees, mcp.jsonl slice, fixture-repo snapshot for failed tests when `--keep-state` is set. |
| **Bisect step** | Named method on a Tier 4 test class that `--bisect` can re-execute against pre-loaded state. |
| **Self-validation contract** | PC-04 / R-20: ≥1 Plan #607 follow-up bug must have a red Tier 4 test that turns green when the production fix lands. |

### Appendix V: Verification Requirements Traceability Matrix (VRTM) — Skeleton

This is the **skeleton**. The full VRTM is finalized in Phase 2 Story 2.9; cells flip from `pending` to `verified` as the corresponding Stories land.

| Req | Description (short) | Verifying test(s) | Producing Story | Status |
|-----|---------------------|--------------------|-----------------|--------|
| R-01 | Nightly executes Tier 0/1/4/6 in order | E2E-04 | 1.10 | pending |
| R-02 | Continue-on-failure, no early-exit | E2E-06 | 1.10 | pending |
| R-03 | `--tier <list>` filter flag | E2E-01, E2E-02, E2E-03 | 1.10 | pending |
| R-04 | Per-run-id-prefix fixture create | IT-02, E2E-03 | 2.1 | pending |
| R-05 | Prefix-scoped teardown | IT-03, E2E-03 | 2.1 | pending |
| R-06 | `--keep-state` failure-only persistence | IT-08, IT-09, E2E-07 | 2.2, 2.8 | pending |
| R-07 | Namespace boundary | IT-02 (negative test) | 2.1 | pending |
| R-08 | MCP via JSON-RPC stdio subprocess | IT-01 | 1.2 | pending |
| R-09 | No direct MCP server imports | Tier 0 static-import check + IT-01 | 1.2, 1.5 | pending |
| R-10 | Tier 0 static checks | E2E-01 | 1.5 | pending |
| R-11 | Tier 1 unit suite | E2E-02 | 1.6, 1.7, 1.8 | pending |
| R-12 | Status-panel byte-equal snapshot | (test in 1.8 itself) | 1.8 | pending |
| R-13 | Test 4.1 GitHub single-flight assertions | (Test 4.1 itself) | 2.5 | pending |
| R-14 | Test 4.8 GitLab single-flight assertions | (Test 4.8 itself) | 2.6 | pending |
| R-15 | Test 4.6 cross-repo assertions | (Test 4.6 itself) | 2.7 | pending |
| R-16 | Forensic doc on Tier 4 failure | E2E-06, IT-04 | 2.2 | pending |
| R-17 | Structured event emission | Tier 6 schema validation (1.9) + every Story emits | 1.4 | pending |
| R-18 | Discord summary post per nightly | Tier 6 round-trip test (1.9) + MV-01 | 1.3 | pending |
| R-19 | `@`-mention guardrail | IT-05 | 1.3 | pending |
| R-20 | Self-validation contract | (Story 2.9 itself; red→green pair IS verification) | 2.9 | pending |
| R-21 | Cost overage detection | IT-06, IT-07 | 2.3 | pending |
| R-22 | Fine-grained PAT scoping | MV-03 (operator action) | (operator) | pending |

**Coverage summary** (at ship time): 22 requirements, 22 with at least one verifying test or operator procedure, 0 unverified.

### Appendix B: Cross-references

**Memory files this Dev Spec leans on:**
- `lesson_destructive_test_homedir.md` — TC-03 source incident
- `lesson_doc_singular_branch_prefix.md` — branch/path naming convention
- `decision_platform_adapter_retrofit.md` — sdlc-server PlatformAdapter retrofit context
- `WAVE_AXIOMS.md` — wave-pattern execution constitution
- `principle_user_attention_is_the_cost.md` — design rationale for unattended cron + forensic-doc-on-failure
- `lesson_cc_subagent_tools.md` — informs DC-07's "subprocess Claude CLI" choice
- `lesson_best_effort_must_log.md` — Tier 6 vox-logging assertion

**External references:**
- Epic [#626](https://github.com/Wave-Engineering/claudecode-workflow/issues/626) — parent Epic
- Plan [#607](https://github.com/Wave-Engineering/claudecode-workflow/issues/607) — origin Plan
- [Sketchbook](./automated-background-testing-sketchbook.md) — design-conversation artifact
- MCP Python SDK: `mcp` package on PyPI
- Anthropic API pricing: refreshed in `pricing.yml` per DC-13

**Decision Ledger:** appended as `[ledger D-NNN]` comments on Plan [#641](https://github.com/Wave-Engineering/claudecode-workflow/issues/641); D-001 through D-060 cover Sections 1.5, 2, 3, and 5.
