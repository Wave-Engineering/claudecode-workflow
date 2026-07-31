# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Removed

- **Slack support, entirely — `/ping`, `/pong`, and `slackbot-send` (#1062).** Both skills were wholly Slack-specific (`#ai-dev`, Slack mrkdwn) with no Discord path, and unused. Removed with them: the `~/.secrets/slack-bot-token` dependency (`deps.json`), the `slack-bot-token` entry in the image build's expected-missing whitelist, the `slack@claude-plugins-official` marketplace plugin (enabled by default with **zero consumers** — its only documented purpose was OAuth on first `/ping`/`/pong` use, so it was costing context every session for a dead integration), and the README's "Slack Setup" section, which instructed new users to provision a bot token for a skill that no longer exists.

  **Already-installed hosts are pruned.** Deleting a skill from source does not uninstall it — `install` walks the surviving `skills/*/` and prunes *within* each, so a skill that vanishes from source is never visited. `~/.claude/skills/ping`, `~/.claude/skills/pong`, `~/.claude/scripts/skills/ping`, and `~/.local/bin/slackbot-send` are now in `DEPRECATED_PATHS`. Without that, the upgrade would have been *worse* than no change: `cellar_deploy` wipes the Cellar copy of `slackbot-send` while `~/.claude/skills/ping/SKILL.md` survives, leaving `/ping` a live, invocable skill whose helper had just been deleted. Guarded by a regression test that plants the installed copies and asserts they are gone.

  **Known gap:** `scripts/install-remote.sh` has no `DEPRECATED_PATHS` mechanism (pre-existing), so tarball-installed hosts retain `/ping` and `/pong` until they are removed by hand.

  Mattermost is the intended successor (Analogic self-hosted; better IP posture), post-cutover, behind a backend abstraction at the MCP-server layer.

### Fixed

- **`bootstrap.sh` never ran — every containerised agent booted unbootstrapped (#1076).** The bootstrap was written to be the agent's parent (it ends by *"refusing to hand off to the agent"*), but nothing ever invoked it. aoe runs no entrypoint: it starts the image with `sleep infinity` as PID 1 and `docker exec`s `claude` as a **separate** process — measured on a live container, PID 1 = `sleep infinity`, agent = PID 13 with **PPID 0** — so there was no process path from bootstrap to the agent. Skills-sync, settings merge, secret projection and R-14 env validation were all shipped, unit-tested, documented, and **inert**. Auth was merely the first phase whose absence was visible, because it parks the agent on `Select login method:` forever, and an unattended agent on a login menu looks exactly like an idle one. It hid because `test_bootstrap.py` drives `bootstrap.sh` directly by subprocess: that proves the script *works* and never asks whether anything *calls* it — the same declared-but-not-wired shape as the inert R-14 check (#1061), trivy parsing zero manifests (#1056), and `extra_volumes = [0 items]` (#1069). **Fixed** with `containers/oakandwave-workflow/claude-entrypoint.sh`, installed over the `claude` name and `exec`ing the real CLI (moved to `claude-real`). It **sources** bootstrap rather than running it, which is load-bearing and not a style choice: environment flows down, never up, so a child process would export `CLAUDE_CODE_OAUTH_TOKEN` into itself and exit, leaving the agent with nothing and every log looking healthy. Sourcing also preserves the fail-loud contract for free, since bootstrap's `exit 1` aborts the wrapper before the `exec`.

  **The first cut of this fix shipped inert, exactly like the bug it fixes.** Installed only at `/usr/local/bin/claude` — chosen because `/proc/<pid>/exe` on a live agent resolved there — it was never executed, because `docker exec` resolves against the **image's configured PATH**, which reaches the base image's `/root/.local/bin/claude` *before* `/usr/local/bin`. `/proc` had answered "what is this running process", not "what does `docker exec claude` resolve", and those differ. Caught by hiding the wrapper and watching bare `claude` still work. The remedy is not a better path but an asserted property: every reachable `claude` is replaced, and `scripts/ci/assert-no-claude-bypass.sh` walks PATH at **build time** and fails the build if any is not the wrapper (it found **three**), with an empty-denominator guard so "no claude found" can never read as a pass, and empty PATH entries normalised to `.` rather than discarded, since POSIX resolves them to the current directory.

  Two further defects fell out. **The shipped `.env` template aborted the boot:** `OAW_REQUIRED_SECRETS=claude-code-oauth-token discord-bot-token` is `source`d, so unquoted it is not a two-item list but `VAR=first` prefixed to a command named `second` — `line 42: discord-bot-token: command not found`, exit 127. Every fixture used a single-token value, so no test could reach it. **And the guard added for it was itself inert:** bash *strips* `errexit` inside `$( )`, so a command-substitution probe kept sourcing past the first failure and returned the status of the **last** line — and because the template ends with a good `OAW_SECRET_ENV=` line, the guard probed "clean" for the very file it ships, discarded the stderr it had captured, and let the real source die with 127. The probe now runs in a fresh `bash -c` with its own live errexit, stopping at the first failure, and surfaces captured stderr instead of dropping it. Bootstrap's summary line also moved to **stderr**: under `source` + `exec` its fd 1 *is* the agent's, so on stdout it prepended a non-JSON line to every headless `claude -p --output-format json`.

  Verified end to end on a real agent in a real container — `AUTH_OK`, agent process showing as `claude-real`, token present in `/proc/<pid>/environ` — not inferred from configuration. New tests assert the **caller**, execute the real wrapper to prove an `export` survives the `exec`, and strip comments before asserting on the Dockerfile so prose cannot satisfy them; all were mutation-tested red-first. Follow-ups: #1078 (bootstrap's skills host-fill has no mount, so it warns every boot) and #1079 (interactive agents still park on the first-run onboarding wizard — provably *not* auth: the token returns HTTP 200 and headless works).

- **Session liveness detection never fired — `skill-gc`/`reorient` could rewrite LIVE agents' transcripts (#919).** `session_liveness()` documented a fail-closed contract whose *strong signal* was "a process holds the transcript fd open". Claude Code appends to its transcript and closes the descriptor, so that branch was dead code. Swept on the development workstation (a single-host observation, not reproducible from a read-only review): **0 of 277 transcripts were held open across 10,613 open fds**, so everything fell through to the 60-second mtime window and **10 of 14 live sessions there classified as STOPPED** — eligible for transcript surgery, and selected by the documented fleet invocation `find-projects --stopped … -exec reorient {} \;`. The suite stayed green throughout because `test_detects_open_fd_as_live` opened the fd *itself* and `test_stopped_vs_running` monkeypatched `_liveness` away; both asserted a path production never took. **Replaced** with a process-identity signal: one `/proc` sweep extracting session UUIDs from `--resume`/`--session-id`/`-r`, covering all four cmdline forms observed in the fleet — bare uuid, `--resume=<uuid>`, and path-valued `--resume /…/<uuid>.jsonl`. Every cmdline is scanned rather than filtering on `argv[0]`, because sessions run under a two-word `argv[0]` (`claude bg-pty-host`) and under the bare version binary (`…/claude/versions/2.1.215`) — a basename filter dropped 4 live sessions. Flag-scoped parsing (not "any UUID in the cmdline") avoids 8 false positives from grunt ids carried in `--append-system-prompt`. The mtime window survives as a **secondary** signal only. Two cmdline forms name no written session at all and fall to **cwd-scoped doubt** (`unknown` → refused) rather than poisoning the fleet: a bare `claude`/`--continue`, which carries no uuid anywhere; and `--resume A --fork-session`, where the fork mints a *new* id, so naming `A` accounts for the source and never the file the process actually writes. The latter is easy to miss precisely because every `--fork-session` in this fleet also passes an explicit `--session-id` — when the new session *is* named the process is fully accounted for and its cwd is deliberately not blanketed. On the development workstation that scoping cost 1 store of 84 its collectability, and the recorded cwd strips the kernel's `" (deleted)"` suffix — left on, the doubt is filed under a path no transcript can match and silently evaporates, which `git worktree remove` under a running agent is enough to trigger. Fail-closed is preserved and widened: no `/proc`, *or* pid dirs exposing no readable cmdline, *or* a `/proc` with no pids at all now yield `unknown` — a blinded scan must never be indistinguishable from a healthy all-clear. `find-projects` hard-errors (rc 2) on `--stopped`/`--running` both when `skill-gc` fails to load **and** when the `/proc` sweep comes back blinded, instead of printing nothing and exiting 0; answering "the fleet is drained" from a detector that saw nothing is what made `./install` look safe under ten live agents. The two tools share one implementation, now asserted by a differential test and a load-path test. Also **~500× faster**: the dead fd scan re-globbed all `/proc` fds *per session* (277 × 10.6k), so `find-projects --stopped` went from >120 s (timed out) to 0.12 s by sweeping once per run. Verified against the development workstation's live fleet: `--running` 6 → 12 stores, every live-with-transcript session detected, **0 live sessions in the `--stopped` set**, and `skill-gc` refuses a real agent idle 34,712 s (578× the window) that the old code evicts. New `tests/test_liveness.py` (38 cases) was red-first against the prior implementation — **28 failed / 10 passed** — and drives the real detector via `/proc` trees built from observed cmdlines. **Known residual (#923):** the blinding guard fires only when *no* cmdline is readable, so a *partially* readable `/proc` (hidepid, PID namespace, another user's `claude`) still fails open; unaffected on hosts where `/proc` carries no `hidepid`.

## [7.1.0] - 2026-07-19

### Fixed

- **Godspeed gated-axis check: gate on ACTIONS, restore the agent's right to assess (#917).** The Stop hook's gated-axis check regex-matched the assistant's *turn text* for keywords (`prod`, `deploy`, `credentials`, …) and explicitly discarded `tool_use` blocks — it judged what the agent said, not what it did. It was wrong in both directions at once: it fired on `"the live deployed tool schema"` (and on any turn *documenting* this hook's own keyword list), while missing `deploy_freshness` because `\bdeploy[a-z]*\b` cannot cross an underscore. A word list cannot separate those; the discriminator is not the word but whether the turn acted. Three changes: **(1) Substrate** — the gate now reads `tool_use`, matching invoked command *verbs* at shell-segment head (plus prod-shaped `Write`/`Edit` paths), so gated keywords appearing as *data* (`grep -P 'prod|deploy'`, a heredoc about this hook) never match, while prefix wrappers that used to defeat `^`-anchoring (`sudo systemctl`, `git -C … push --force`, `timeout N terraform apply`, `sh -c`, subshells, `xargs`) now do. **(2) Agency** — the STOP reason previously ordered *"surface it to BJ before proceeding"*; it now grants an explicit assess-and-continue path. An unconditional halt defeats `/godspeed` and buys nothing, because the hook runs *after* the turn's tools have executed and could never prevent a first action. It is a salience signal, not the enforcement gate — the ABSOLUTE prod rule, `/precheck`, and the human remain the real defenses. **(3) Notification** — a gated trigger no longer fires vox/Discord. Notifying before the agent has assessed makes the *hook* the escalator and spends the user's attention on every false positive; the agent now escalates with its own tools when it judges something merits attention. Extraction is turn-scoped (a union across every assistant message since the last human-text user entry, never `last`) — scoping to a single message failed **open** on the normal pattern, since agents almost always run a verification command after acting, which masked the gated one. Regression coverage grew 39 → 51 shell assertions plus 20 Python subtests, including the multi-message fail-open, prefix wrappers, keywords-as-data, the self-referential case, and positive controls for the kill-switch and loop guard (both had gone vacuous).

- **`/issue` no longer steers agents away from `type: "plan"` (#915).** The skill carried a warning block asserting `work_item` had no `plan` in its type enum, citing `mcp-server-sdlc#477`. That gap was closed by sdlc **v2.1.0** (`mcp-server-sdlc#479`) and #477 is closed — verified against the live deployed tool schema, not repo source. The block was actively harmful, not merely stale: it told agents `/issue plan` could not pass `type: "plan"`, and its fallback guidance (`type: "epic"` plus manual label cleanup) produces exactly the duplicate `type::epic` + `type::plan` taxonomy leak Dev Spec R-19 forbids on GitHub — the bug #903 documented and #479 fixed. Replaced with a positive instruction to pass `type: "plan"`, the sdlc-server ≥ v2.1.0 version floor, and the retained prohibition on substituting `type: "epic"` (which was only ever safe by accident on GitLab). `tests/test_issue_skill.py::TestPlanTypeGapDocumented` — which asserted the removed block's presence — is re-pointed at the new invariant as `TestPlanTypeCallout`, keeping the `type: "epic"` coverage and adding a negative regression so the stale claim cannot creep back.

## [7.0.0] - 2026-07-19

### Added

- **Executor Model — per-wave dispatch, `/lazyriver`, and `/multithread` (Plan #822).** Three coordinated changes that split the wave pipeline's conflated execution concepts. **(1) Per-wave dispatch knob:** `/prepwaves` now classifies each wave with a `dispatch` hint (`fan` \| `serialize` \| `serialize-preferred`) after topology computation (Step 4.A four-rule table), and `/nextwave` reads it to fan flights in parallel or run them single-file. Asymmetric bias — serialize by default; `fan` only when verified-independent and mechanical; intra-wave dependency edges are a hard `serialize` gate (F-8 class). Absent `dispatch` is treated as `serialize` (backward-compatible). Regression-tested in `tests/test_prepwaves_dispatch.py`. **(2) `/lazyriver` goal-seek skill:** a new skill implementing the `probe → journal → judge-sufficiency → steer` loop that runs a *goal* to *sufficiency* (a judgment) rather than a DAG to completeness — sits upstream of `/devspec`, emits a plan or a direct answer, is escalation-corded (leg cap 10 or two consecutive zero-finding legs) with a durable findings journal. Explicitly distinct from the plan-execution activity `/wavemachine`/`/nextwave` run. **(3) `/multithread` companion:** a new skill that turns a serial walk over N independent design items into a concurrent discussion — enumerate + stable-label, independence pass, present all threads with a proposed take each, batch-answer, converge, and emit a decision record — closing in ≈ log(N) round-trips instead of N. Dev Spec: `docs/executor-model-devspec.md` (VRTM Appendix V complete; MV/E2E evidence in `docs/executor-model-mv-results.md`). Closes #822.
- **`/reseed` auto-revive hook (#757).** `SessionStart{matcher:"clear"}` hook (`reseed-revive.sh`) injects the seed content into the fresh agent context and fires a tmux keystroke — no user action needed after `/reseed`. Flow: `/reseed` writes the seed, arms `<project_root>/.claude/reseed-armed.json` (seed_path + tmux_pane + mtime), then sends `/clear` to its own tmux pane via `tmux send-keys`. Hook fires on the fresh session: if armed file is fresh (< 5 min, by mtime — cross-project isolation via CWD-scoped path), seed content is injected via stdout (system-reminder) and `tmux send-keys "continue"` kicks the agent off. Stale armed files trigger a confirm-request instead. Armed file consumed on inject; seed file kept for manual recovery. No user action after `/reseed`; BJ never touches it again.

### Changed

- **The fleet is now queue-less — merge queues and merge trains are removed entirely (#898, #900).** The rulesets were deleted from all six Wave-Engineering repos (classic branch protection, which independently carried the required status checks, was left intact); `gl-settings` disables GitLab merge trains; and every trace of the concept is gone from the kit — the `skip_train` flag and the `merge_group_validated` acceptance are stripped from the wave engine (`gate.js`, `per-wave-workflow.js`, the bundle, `SEAMS.md`), the dead `merge_group:` trigger is removed from `validate.yml`, and the specs, skills, and docs no longer mention or assume either. **Why:** wave work never needed a queue — flights land on the `kahuna/*` integration branch, the engine reconciles them via `commutativity_verify` + dependency-ordered merges, and `kahuna→main` is a single serialized, trust-gated promotion, so nothing ever merges to the protected branch concurrently. The queue only cost us: an extra pipeline per MR on GitLab, the `skip_train`-silently-dropped divergence bug, and the 2026-04-07 outage (postmortem #299). A prior spec claim that GitLab trains "batch flight-MRs into one pipeline run" was **false** — GitLab runs a pipeline *per MR in the train* — and is corrected at the source. Note that GitLab **merged-results pipelines stay ON**: they are not merge trains, and they are what produce the merge-result pipeline the wave gate validates (sdlc #452 — the gate checks the merge *result*, never the branch HEAD). Removing the queue also makes merge method a **per-merge** choice again, since nothing forces one method for everything. `docs/operations/merge-queue-checklist.md` → `docs/operations/branch-protection-checklist.md`, rewritten, **preserving** the load-bearing "config exists ≠ config works" discipline (a red PR must be BLOCKED *and* a green PR must merge — a gate that blocks everything is as broken as one that blocks nothing). Regression is guarded *negatively*: `test_gate_contract` and `gate_signals_roundtrip` now assert `skip_train` is **absent**, and `install` prunes the old runbook from `~/.claude` via `DEPRECATED_PATHS` (it *prescribed* creating a queue, and repos without their own docs resolve kit docs from there).
- Agent identity now stored at `<project_root>/.claude/agent-identity.json` (reboot-durable, gitignored) instead of `/tmp/claude-agent-<md5>.json`. All readers fall back to the legacy `/tmp` path during the transition window. Closes #723.

## [6.1.0] - 2026-06-23

### Fixed

- Corrected the `discord.json` channel schema (nested → flat) across the disc reader (`/disc`), the ccwork writer (`/ccwork discord`), and the `docs/discord-config.md` contract doc. The canonical config uses top-level `default_channel_id`/`roll_call_channel_id` + a flat `channels` name→id string map; the skills previously read/wrote the stale nested `channels.<role>.{id,name}` shape, so `/ccwork`-generated configs were unreadable by `/disc` and config edits were silently ignored in favor of baked-in IDs. Closes #806.

### Added

- `/prepwaves` step 0.5 — **campaign residue gate**: calls `wave_campaign_precheck` (server contract mcp-server-sdlc#457) before any sub-agent fan-out or approval and surfaces a prior campaign's residue (`classification` + `residue{plan_id, wavemachine_active, pending_waves, promoted_waves, kahuna_branches}` + `options`/`recommended`) for an operator preserve-wait / preserve-extend / replace choice; nothing is deleted without explicit confirmation. Subsumes the former narrow `phases-waves.json` multi-Phase guard, with an on-disk fallback for defense-in-depth. Closes #716.
- Kit-canonical docs (`WAVE_AXIOMS.md` + the referenced `docs/*`) are globalized to `~/.claude/` on install, so a `/ccfold`-merged CLAUDE.md resolves them in any repo (single source, no per-repo vendoring). Closes #792.

### Changed

- The **pytest suite now runs in CI** — `scripts/ci/test.sh` on both `pull_request` and `merge_group`. Root-cause fix for the suite rotting unnoticed: it previously ran nowhere in CI. Closes #795 (CI-gating slice; the xfailed-test rewrite remains in #795).
- Triaged the rotted test suite to green (195 → 0 failed): stale wave-engine skill-tests dispositioned via reasoned `xfail` (logic relocated to `per-wave-workflow.js` by #691 / `WAVE_AXIOMS` by #605; covered by the #785 e2e smoke). Closes #753.

## [6.0.0] - 2026-06-20

### Breaking

- Wavemachine Classic mode retired; Kahuna is the only execution shape. Every Plan now bootstraps a `kahuna_branch` at launch and routes Flight PRs through that integration branch, with the four-signal trust gate at Plan completion auto-merging kahuna→protected-branch. The `legacy non-KAHUNA` / `KAHUNA mode` framing is gone from `/wavemachine`, `/nextwave`, `/prepwaves`, `/assesswaves`, and `/devspec`. Hardcoded `main` integration targets in skill bodies have been replaced with abstract phrasing (the project's protected branch, read from `.claude-project.md`). No mode-selection flag, no fallback path. Closes cc-workflow#580.

### Added

- **Campaign-oversight stack (#745).** The between-wave judgment facility, built as three composable pieces: a **durable cross-wave concern-trajectory** (#748) — `wave-status` accumulates each completed wave's terminal record (`{gate, promoted}`, the four trust signals, concerns/deferrals/rework, commutativity verdict, issues; reboot-proof, idempotent, with `trajectory-append`/`trajectory-show` CLI); a **deterministic auto-mode campaign Workflow** (#749) — `campaign-loop.js` + `campaign-workflow.js` iterate pending waves, run each per-wave spine, route on the `{gate, promoted}` verdict, and call the judgment seam — no LLM in the loop control flow, so it provably cannot stall; and the **wave-oversight judgment agent + seed contract** (#750) — seeded no-distillation from tiered intent (devspec → DDD/sketchbook → issues) + the durable trajectory + live inspection, with a failure-shape lens (accumulation / intent-drift / adaptation-vs-drift across trend / absence / confound-control modes).
- Coarse driver-states for the async campaign loop in `wave-status` (#738).

- `/prepwaves` now ends with a `/clear` recommendation and a paste-ready `/wavemachine` seed prompt. The recommendation downgrades to a hint when `nerf_status` reports <30% of soft dart used. Reduces context drift between planning and execution sessions (Plan #581 debrief). Closes #602.
- /wavemachine: long-session drift mitigation — at every wave-to-wave handoff the loop body emits per-wave drift-signal events (`wave_message_length_main`, `wave_stop_hook_blocks`, `wave_concerns_posts`) via `scripts/wavemachine/drift-instrumentation.sh emit-wave-drift` and injects a system-reminder re-grounding payload citing `WAVE_AXIOMS.md` (with explicit Axiom 9 reference). The lightweight payload is unconditional at every wave boundary; mandatory `/engage` and `/compact`-on-N-waves are documented as rejected alternatives held in reserve for empirical escalation. (cc-workflow#601, "Bug C" from Plan #581 campaign A debrief.)
- `wave_wait_for_signal` MCP tool — sanctioned idle-wait for wave-pattern Orchestrators (and Primes) blocking on filesystem-bus completion artifacts. Polls every 5s with configurable timeout (default 1800s) and minimum match count (default 1); accepts literal paths or Bun.Glob patterns. Returns matched paths on success or `timed_out: true` + `partial_matches` on timeout. Replaces ad-hoc `Bash(sleep)` loops and the anxiety-driven premature-exit failure mode (#414).
- **wave-watcher daemon (#578).** New standalone Bun daemon.
- `/wave` skill: thin routing skill wrapping `mcp__sdlc-server__wave_show` so wave-pattern status (Project / Phase / Wave / Flight / Action / Progress / Deferrals) can be checked from any conversation without remembering the MCP tool name. Pure pass-through — no interpretation. Future routes (`/wave health`, `/wave topology`, `/wave next`) documented but reserved for follow-up issues. (#579)
- **Nerf MCP server** — Deterministic context budget management via `nerf-server` MCP. Includes dart thresholds (soft/hard/ouch), behavior modes (not-too-rough, hurt-me-plenty, ultraviolence), statusline indicators, and a terminal-based scope monitor
- **`/nerf` skill** — Thin routing stub for the nerf MCP server with `k`/`m` suffix parsing
- **`/issue` skill** — Create structured issues (feature, bug, chore, docs, epic) with proper templates and labels. Self-contained, dual-platform (GitHub/GitLab)
- **`/ddd` skill** — Domain-Driven Design facilitation with 8-stage event storming, domain model formalization, and PRD generation
- **`/man` skill** — Display usage information for any installed skill via SKILL.md frontmatter
- **`/cryopact` skill** — Background cryo via subagent — preserve state without blocking the main conversation
- **`/disc` skill** — Unified Discord integration: check-in, send, read, list channels, create threads
- **`/view` skill** — Open file/URL in a GUI viewer (read-only) with cross-platform file-opener
- **`/edit` skill** — Open file/URL in a GUI editor for modification
- **`/vox` skill** — Text-to-speech voice announcements via Chatterbox API with local fallback
- **`/precheck` skill** — Pre-commit gate: branch/issue compliance, validation, code review, checklist
- **`/assesswaves` skill** — Quick assessment of wave-pattern suitability for parallel execution
- **`/ccwork` skill** — Onboarding hub with interactive tours, labs, and setup wizards
- **`/scpmr` and `/scpmmr` combo skills** — Stage/commit/push/create PR/merge in one command
- **`/ccfold` skill** — Merge upstream CLAUDE.md template changes into local project CLAUDE.md
- **`sync.sh`** — Reverse-sync: pull local skill/script changes back into the repo
- **Context crystallizer** — Session state preservation pipeline: hooks (PostToolUse, SessionStart, SubagentStop), libraries (context-analyzer, crystallizer), CLI tools (cc-context, cc-cleanup). Tracked in `context-crystallizer/` and installed via `--crystallizer`
- **Discord watcher channel server** — Real-time inter-agent communication via Discord with targeted message filtering, thread polling, voice message STT, and Dev-Name echo suppression
- **Discord bot** — REST API client for Discord: send, read, create channels/threads, resolve names, with 429 retry handling and kill switch
- **Discord status post** — Wave-status embed with auto-updating pinned message, debounce, and dev-team fallback
- **`discord-lock`** — Advisory lock for serializing Discord channel writes across agents
- **`cc-inspector`** — Context window inspector: mitmproxy + Flask UI for API payload capture
- **`generate-status-panel`** — HTML status panel generator for wave progress
- **`worktree-manager`** — Manage isolated worktrees for parallel agent execution
- **Remote installer** — `scripts/install-remote.sh` for curl-pipe-bash installation from GitHub Releases
- **MCP manifest** — `mcps.json` with bundle-install architecture for wtf-server, discord-watcher, and nerf-server
- **GitHub Actions workflow** for GitHub Release packaging
- **Statusline v2** — Two-line layout with per-session indicators, visual refresh, and JSON-based indicator interface
- **Introduction system** — First-run introduction.md display for new skills with marker file gating
- **Work Item Standards** — Label taxonomy (`group::value`), issue templates (feature, bug, chore, docs, epic), and wave-pattern quality requirements in CLAUDE.md
- **`.claude-project.md`** — Cached platform detection results (GitHub/GitLab, CLI tool, labels, CI)
- **Agent identity keying** — Migrated from PPID to project-root md5 hash for stable cross-process resolution
- **PRD template v2.0** — EARS requirements, phased implementation, artifact manifest, CI/CD pipeline, documentation kit, test plan sections, foundation story checklist, one-story-one-repo rule
- **Getting Started guide** — 15-minute walkthrough of first session
- **Skill Reference** — Detailed documentation for all skills
- **Concepts guide** — Architecture overview of the three-layer kit
- **Troubleshooting guide** — Common issues and fixes
- **Discord configuration guide** — Bot token, watcher, inter-agent messaging setup
- **Statusline indicators guide** — Per-session indicator interface documentation

### Changed

- **wavemachine skill**: rename epic→Plan/Phase; add Exhaustive Legal Exits section per Dev Spec §5.3.3. [#512, Story 3.1]
- **nextwave skill**: rename epic→Plan/Phase; add Exhaustive Legal Exits section per Dev Spec §5.3.3. [#513, Story 3.2]
- **prepwaves skill**: rename epic→Plan/Phase; annotate surviving "epic" references as PM-layer. [#514, Story 3.3]
- **devspec skill**: teach Plan/Phase/Wave/Story vocabulary; append Decision-Ledger comments to Plan issue during walk; `/devspec upshift` emits `phases-waves.json` with `plan_id` + per-Story `depends_on`. [#515, Story 3.4]
- **issue skill**: add `type=plan` with Dev Spec §5.1.2 body template; add `--epic N` flag for Story creation; on-demand `label_create` for missing `type::plan` / `epic::N`. [#516, Story 3.5]
- **Refactored `vox` around the provider-hook pattern.** The previous `scripts/vox-tts` embedded five coupled backends (VOX_COMMAND, VOX_ENDPOINT, espeak, piper, say) in one cascade; it has been removed. `scripts/vox` is now a thin dispatcher that resolves a *provider* (synthesis) and a *player* (playback) at runtime. Providers live in `~/.config/vox/provider`; copy-and-adapt examples ship in `scripts/vox-providers/` (`silent.sh`, `openai-endpoint.sh`, `piper-local.sh`, `espeak.sh`, `macos-say.sh`). Contract documented in `scripts/vox-providers/README.md` (VOX_PROVIDER_CONTRACT=1). Closes #398.

  **Migration (existing vox users)**: your prior `VOX_COMMAND` / `VOX_ENDPOINT` settings no longer auto-dispatch. Run `vox --setup` once to pick a provider, or manually:

  ```bash
  cp scripts/vox-providers/openai-endpoint.sh ~/.config/vox/provider
  chmod +x ~/.config/vox/provider
  $EDITOR ~/.config/vox/provider   # set VOX_ENDPOINT, VOX_VOICE at the top
  ```

  `VOX_DISABLED=1` is a new escape hatch for clean no-op exit (CI / headless / temporary silence).

- **Renamed `/prd` skill to `/devspec`** (Development Specification). The old name collided with PM usage of "PRD" (customer need, ROI, value prop); the skill produces an implementation spec for a coding agent, which is semantically distinct. Template renamed to `docs/devspec-template.md`, translation protocol to `docs/DDD-to-devspec-protocol.md`, and output files use the `-devspec.md` suffix. The approval metadata marker changed from `<!-- PRD-APPROVAL -->` to `<!-- DEV-SPEC-APPROVAL -->`. Internal campaign-status stage ID `prd` is preserved for backward compatibility with existing `.sdlc/` state files; only the user-facing display label is updated to "Dev Spec". Closes #327.
- `install.sh --config` now smart-merges `settings.template.json` into existing `settings.json` — missing hooks, plugins, and permissions are added while user customizations are preserved
- `install.sh --check` now reports missing hooks, plugins, MCP server registrations, and crystallizer drift
- `install.sh` supports selective flags: `--skills`, `--scripts`, `--config`, `--mcps`, `--crystallizer`
- Repo restructured: skills carry their own scripts (discord-bot inside disc, file-opener inside view, etc.)
- `/cryopact` delegates to cryo subagent, removes auto-clear, fixes immediate mode
- `/disc` default action changed from read to check-in
- `/nextwave` uses pre-created worktrees instead of isolation worktrees, with granular lifecycle tasks and explicit wave-status calls
- `/pong` uses priority-ordered default discovery flow (active thread → addressed messages → general history)
- `/vox` adds `--output FILE` flag for render-to-disk mode
- Discord config abstracted into `~/.claude/discord.json`
- Agent check-in on session start via `#roll-call` channel
- RC display name set to match Dev-Name at session start
- Introduction-gate marker files use dot prefix for hiding
- Nerf default thresholds lowered for 200k context window safety

### Fixed

- `wave_finalize`: durable-state fallback when wavebus has been cleaned up by `wave_complete`. Re-derives the MR body from `<project>/.claude/status/{phases-waves.json,state.json}` (issue #s + recorded `mr_urls`) so the kahuna→target finalize step succeeds at the end of the last wave instead of returning `no_artifacts`. Bus artifacts still take precedence when present. (#415, Plan #581 incident)
- `/wavemachine`: Wave-to-wave handoff is now a single tool-use boundary — skill body forbids narrative text between waves, and a new doc-shape regression test (`tests/regression/test_wavemachine_handoff_no_narrator.sh`) guards the contract. Closes "Bug B" from Plan #581 campaign A debrief (#600).
- `/nextwave`: Prime(post-flight) prompt now declares the canonical-line contract verbatim with concrete PASS/FAIL/BLOCKED examples, a forbidden-phrases list (including the exact `"Sleep is still running. Let me wait for the notification."` narration that broke Plan #581 wave-2), and an `Exit shape` section as the LAST section of the prompt so it is the most recent context when the agent emits its final message. Closes #606.
- `pr_wait_ci` no longer hangs the full timeout window when a PR/MR has no required status checks. The handler now probes once at t=0; on empty rollup it returns `{ status: "no_checks_required", elapsed_sec, mergeable, blocker? }` instead of polling. Polling-loop behavior for non-empty rollups is unchanged. (#416)
- `install.sh` unbound tmpdir variable on script exit
- `install.sh` handles `claude mcp add` failure gracefully
- Discord-bot 429 retry-after handling and JSONL API call logging
- Discord-bot kill switch to halt all API calls on global 429
- Discord watcher strips punctuation from @-addressing tokens
- Vox Bluetooth wake noise prepend to prevent audio clipping
- Vox help text for `-o` flag and `espeak-ng` fallback
- Wave-status meta-refresh fallback for `file://` dashboard viewing
- Wave-status infers phase/wave position when `current_wave` is null
- Identity keying migrated from PPID to project-root hash (fixes multi-session collisions)
- Ping/pong channel name corrected and channel ID added
- `/precheck` runs immediately without asking permission
- `/issue` removes per-issue approval gate (issues are cheap to edit)

### Removed

- `afk-notify` Stop hook — replaced by kill switch on discord-watcher

### Chore

- `/prepwaves` now refuses to run on a dirty working tree or a non-base branch, listing every offending path so the operator can choose between commit, stash, or discard. A `--force-dirty` override exists for legitimate edge cases and emits a noisy banner before proceeding. Rationale: Plan #581 sandbox cross-talk incident (#603).
- `/devspec approve` now self-commits the Dev Spec (and any auxiliary finalization-track writes) on the active branch with a `docs(devspec): finalize Dev Spec for Plan #N — <slug>` message instead of leaving the changes uncommitted. Refuses to commit on the project's protected base branch. Push remains the operator's affirmative act. (#604)
- WAVE_AXIOMS.md restructured: each axiom now has a stable rule/why/how subsection layout, and a new Axiom 9 ("User attention is the cost. Autonomy is the protection.") binds the autonomy clauses in `/wavemachine`-class skills to the user-attention-protection rationale. The four wave-pattern skill bodies (`/wavemachine`, `/nextwave`, `/prepwaves`, `/assesswaves`) now begin with a `## Axioms` cross-reference block citing the binding axioms by number, and inline justification prose that duplicated the axiom corpus has been replaced with cross-references — single source of truth, no more skill-body drift. (#605)
- New regression check `scripts/ci/check-no-classic-mode.sh` (wrapped by `tests/regression/test_no_classic_mode.sh`) flags Classic-mode taint in wave-pattern skill bodies and the cross-repo recipe; wired into `scripts/ci/validate.sh`'s regression-tests pass.
- **regression test**: grep-based test enforcing R-19 (no pipeline reads of `epic::N` labels); wired into CI. [#517, Story 3.6]

### Documentation

- Added `docs/tools.md` (per-tool reference, seeded with `wave_wait_for_signal`).
- Added `docs/wave-pattern-orchestration.md` with the canonical Orchestrator-wait-on-Flights example.
- **phase-epic-taxonomy VRTM closed**: MV-01..MV-06 executed; all 18 active requirements traced to Pass verifications; Plan #499 flipped to `plan-complete`. [#518, Story 3.7 — closing story for cc-workflow#499]

## [KAHUNA MVP] - 2026-04-25

### Added

- **KAHUNA — autonomous epic delivery via per-epic integration branches.** Lets `/wavemachine` ship a whole epic to `main` in one autonomous run instead of stopping for human review on every Flight MR/PR. All Flights for an epic merge into a short-lived `kahuna/<epic-id>-<slug>` branch (CI-gated, no human review); when the epic is fully assembled and the four-signal trust score is green (commutativity STRONG/MEDIUM, CI green, code-reviewer-clean, trivy zero HIGH/CRITICAL), the system opens a single kahuna→main MR/PR and auto-merges it. Main's existing branch protection, required reviews, and merge rules are unchanged — KAHUNA only relaxes rules on `kahuna/*` branches. cc-workflow surface area in this release:

  - **`/precheck` sandbox awareness** — Detects when a Flight Agent is operating inside a Kahuna sandbox (current branch's base ref matches `^kahuna/[0-9]+-`). When the full checklist passes (validation, code-reviewer no high+ findings, trivy clean, Discord `#precheck` post, vox announcement), `/precheck` emits the sentinel `[AUTO-APPROVED: kahuna sandbox]` and invokes `/scpmmr` directly instead of STOP-and-wait. Outside the sandbox, behavior is unchanged.
  - **`/wavemachine` trust-score gate** — Wavemachine integrates four-signal trust-score evaluation at the kahuna→main MR/PR. Any red signal pauses for human review; degraded-signal fallback to human is automatic, not configured.
  - **`/nextwave` kahuna base-ref plumbing** — Flight sub-agents branch off the kahuna integration branch (not main) and target it as their MR/PR base. The base ref is propagated end-to-end through wave planning, worktree creation, and PR creation.
  - **`wave-status` CLI additions** — New `set-kahuna-branch` subcommand for KAHUNA state writes; renderers for `kahuna_branch` / `kahuna_branches` fields; gate-action surfacing in the dashboard and Discord wave-status embed.
  - **New documentation** — [`docs/kahuna-guide.md`](docs/kahuna-guide.md) (engineer-facing how-to) and [`docs/kahuna-devspec.md`](docs/kahuna-devspec.md) (architecture, rationale, constraints, requirements).

Companion changes ship in `mcp-server-sdlc` (kahuna lifecycle tools, `wave_finalize`, schema relaxations) and `gitlab-settings-automation` (per-platform sandbox configuration). See those repos' CHANGELOGs for details.

## [0.1.0] - 2026-03-22

### Added

- **CLAUDE.md template** — Drop-in project instructions with auto-detection for GitHub and GitLab
  - Platform detection from `git remote -v`
  - Discovery-based code standards (finds project's own tooling)
  - Agent identity system (Dev-Team persisted, Dev-Name/Dev-Avatar per-session)
  - Pre-commit checklist with mandatory verification
  - Secrets guardrail (warn-and-confirm before staging sensitive files)
  - PR/MR description format

- **11 custom skills** — All dual-platform (GitHub + GitLab)
  - `cryo` — Session state preservation before compaction
  - `engage` — Load rules of engagement
  - `ibm` — Issue-Branch-PR/MR workflow
  - `jfail` — CI job/workflow failure analysis
  - `mmr` — Merge PR/MR with squash
  - `nextwave` — Parallel sub-agent execution
  - `ping` — Post to #ai-dev Slack channel
  - `pong` — Read #ai-dev Slack channel
  - `prepwaves` — Dependency wave planning
  - `review` — Code review on staged/branch changes
  - `scp` — Stage/commit/push workflow

- **Utility scripts**
  - `slackbot-send` — Send Slack messages as a named Claude Code agent
  - `job-fetch` — Fetch GitLab CI job traces for analysis
  - `statusline-command.sh` — Custom status line with git info and context window

- **Deployment tooling**
  - `install.sh` — Install skills, scripts, and config with backup and diff-skip
  - `install.sh --check` — Show drift between repo and installed versions
  - `install.sh --dry-run` — Preview changes without modifying files
  - `uninstall.sh` — Clean removal of installed components
  - `settings.template.json` — Portable Claude Code settings template

- **CI and repo scaffolding**
  - GitHub Actions workflow for PR validation
  - `validate.sh` — shellcheck + shfmt + SKILL.md frontmatter checks
  - Issue templates (bug report, feature request)
  - PR template matching CLAUDE.md conventions
  - MIT license
