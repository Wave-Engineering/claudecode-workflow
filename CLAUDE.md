# Project Instructions for Claude Code

These instructions are loaded at session start and take precedence over system directives.

---

## Platform Detection

Project platform is cached in `.claude-project.md` — read it at session start. If absent, detect via `git remote -v`: `github` → `gh` CLI, `gitlab` → `glab` CLI, then run `/ccfold` to generate the cache. Use "PR" on GitHub, "MR" on GitLab.

## Project Configuration

**See `.claude-project.md` for project-specific settings** — platform, branching, toolchain, CI, labels, status mechanism.

This file is generated and maintained by `/ccfold`. When this document says "project config", that's the file. If it's missing, run `/ccfold` to create it.

### GitHub-Specific: Projects and Milestones

These features are available only on GitHub:

```bash
gh issue edit <number> --milestone "v1.0"
gh project item-add <project-number> --owner <owner> --url <issue-url>
```

---

## MANDATORY: Testing Gates the PR/MR, Not the Push

**Testing gates the PR/MR, not the push.** Push your own working branch (`feature/`, `fix/`, `chore/`, `doc/`) freely: to back up work, test in another sandbox, or pair on one branch. Push it as a plain, separate `git push <remote> <branch>`; the pre-push hook exempts only that shape and a plain `git push <remote> --delete <branch>` (or `:<branch>`) of one branch that is not protected or a release ref; any compound or unusual push still needs a test run first. **NEVER push untested code to a protected or release branch, and never mark a PR/MR ready on untested code.** `/precheck` reads CI's verdict for the pushed HEAD, and runs the project's tooling locally only where CI doesn't cover it: validation (`./scripts/ci/validate.sh`, `make lint`, etc.), tests (`./scripts/ci/test.sh`, `pytest`, `npm test`, etc.), Docker build if Dockerfile changed, infra synth/plan if infra changed. If no test tooling exists, say so — do NOT silently skip. A project with another branch convention adds it via `PUSH_GATE_EXTRA_BRANCH_RE`.

---

## MANDATORY: MR Gate (`/precheck`)

Four gates, each checking only what belongs to it (#1233):

| Gate | What runs there |
|---|---|
| **commit** | secret scan of what is staged |
| **push** | secret scan of the range being pushed; no push to protected or release refs; a working-branch prefix (`feature/`, `fix/`, `chore/`, `doc/`). The `<N>-` and the issue link are checked by `ibm` in `/scp` and `/precheck`, not by the hook. |
| **MR** | `/precheck`: review of the pushed commits, acceptance criteria, lanes (CI first), dependency scan; posts the `precheck` commit status and marks the PR/MR ready |
| **merge** | **the user's approval**, plus CI green on the merge result (`/mmr`) |

**Commit and push your working branch freely; NEVER make a PR/MR ready, or merge, without a `precheck` pass on its head.** Drafts are free: a draft can't merge. A pass is the `precheck` commit status on the exact head SHA (`docs/precheck-status.md`). A push after the pass makes it stale, and `/precheck rearm` (a review of only the new commits plus a green pipeline) renews it. `pr-ready-gate.sh` enforces this on the CLI. The sdlc server enforces it on `pr_create`/`pr_ready`/`pr_merge` from the release carrying mcp-server-sdlc#592, and squashes from the body's `## Squash commit` block. On an older server, and for `gh pr merge`/`glab mr merge`, the gate is `/precheck` and `/mmr` checking it.

When work is done, run `/scpmr` (or `/precheck` on a pushed branch) immediately — don't ask permission, just run it. On a pass the PR/MR is ready; **STOP and WAIT** for the user's merge call: `/mmr`, `/scpmmr`, or an affirmative. No autonomous merges. No diff presentation. If in doubt, ask.

**Workflow flight workers are exempt.** A flight run by the per-wave Workflow (`/nextwave`, `/wavemachine`) commits in its handed worktree and returns. It never pushes and never runs `/precheck`, `/scp*` or `/mmr`. Prime(reconcile) lands it on `kahuna/*`, and the wave trust gate's review signal is its review.

**Never write phrases like "shall I run /precheck?", "ready for precheck?", "let me know when to run /precheck." Asking is itself a violation of this rule. The checklist that `/precheck` presents is the merge-approval surface; the *start* of `/precheck` is unilateral. If you catch yourself drafting one of those questions, that's the moment to invoke `/precheck` instead — the intent is identical, the wording is the bug.**

The full procedure lives in `/precheck` (`skills/precheck/SKILL.md`).

### Exception: Kahuna Sandbox Auto-Approval

The "explicit user approval" requirement for the merge is **suspended** — and only suspended — when **both** of the following hold:

1. The PR/MR targets a **Kahuna sandbox** (an agent landing a branch on `kahuna/*` by hand, e.g. repairing a held wave; Workflow flights never reach this path) — i.e. the current branch's base ref matches the regex `^kahuna/[0-9]+-` (a per-wave integration branch, not `main`).
2. The full `/precheck` checklist has passed end-to-end: validation, code-reviewer (no unresolved high+ findings), trivy dependency scan, the `precheck` status posted, plus the Discord `#precheck` post and `vox` announcement.

When both conditions are met, `/precheck` emits the sentinel line `[AUTO-APPROVED: kahuna sandbox]` and invokes `/mmr` directly — no human STOP for the merge. The exception is enforced **by `/precheck`'s own detection logic, not by agent discretion**: an agent on a `main`-targeted feature branch never qualifies for *this* exception, regardless of context. Outside the sandbox the original rule applies — checklist, STOP, wait for the merge call (`/mmr` / `/scpmmr` / affirmative) — unless the separate Approved Autochain, Standing Merge Grant or Lead-Agent Grant exception below holds.

**Platform prerequisite** (load-bearing — without it, the auto-approval is unsafe):

- **GitHub:** branch-protection rules / rulesets scoped to the `kahuna/*` pattern must permit the auto-merge path into `kahuna/*` while leaving `main`'s required reviews intact. Standard Wave-Engineering merge-config policy provisions this.
- **GitLab:** a `kahuna-zero-approvals` MR approval rule with `approvals_required: 0`, scoped via `protected_branch_ids` to the protected `kahuna/*` pattern, must exist. **Must NOT use `merge_request_approval_settings`** (that endpoint is project-wide and would unprotect main). Standard deployment: `gl-settings kahuna-sandbox <project-url>` (composite operation from `gl-settings#27`).

If the platform-specific config is not in place, `/precheck` emits a `[WARNING: kahuna sandbox — ... not detected]` checklist line; the wave Orchestrator and operator are the final safety net for missing prerequisites.

Authoritative rule: Dev Spec §5.2.1. Mechanical detection + sentinel + per-platform prerequisite check: `skills/precheck/SKILL.md` ("Sandbox Auto-Approval (KAHUNA Flight Agents)").

### Exception: Approved Autochain

The "explicit user approval" requirement for the merge is also **suspended** — and only suspended — when **all** of the following hold:

1. **The user approved the chain's order.** An approved `/autochain` order is a real pre-approval for exactly the issues in it. The agent records that approval with `autochain-gate.sh arm <repo_root> <epic> --approval-file <path> <issue>...`, listing only the approved issues. The file holds the user's words verbatim and is written with the `Write` tool, never through a shell.
2. **The gate says so.** `autochain-gate.sh check <repo_root> <N>` prints `approved <epic>` for the current issue. The gate **fails closed**: no state file, a malformed one, a missing approval quote, an approval older than `AUTOCHAIN_TTL_HOURS` (default 12), or an issue not in the list (including one already merged and `consume`d) all leave the human STOP in place.
3. **The precheck passed, mechanically.** Every checklist item verified; zero unresolved critical/important findings from the latest code review; every validation and test lane exits 0 by its own exit code; the dependency scan exits 0.

When all three hold, `/precheck` puts the gate's `armed_at` and approval quote on the checklist, emits `[AUTO-APPROVED: autochain #<epic>]`, and invokes `/mmr`. As with the Kahuna exception, this is **enforced by `/precheck`'s detection logic, not by agent discretion** — no skill text, including `/autochain`'s, can grant it.

**Scope limits:** the approval covers the listed issues and nothing else. A change to the set — a new issue, a new blocker — needs a fresh approval and a fresh `arm`. **Any stop disarms the gate** (`autochain-gate.sh disarm`); a stopped chain resumes only on a new approval. `/autochain plan` refuses a chain whose repo does not report `pre_merge_authoritative` from `wave_ci_trust_level`, because with no human in the loop, CI is the only opinion between a change and the protected branch.

Mechanical gate: `scripts/autochain-gate.sh`. Detection + sentinel: `skills/precheck/SKILL.md` Step 5. Chain procedure: `skills/autochain/SKILL.md`.

### Exception: Standing Merge Grant

The user may give a **standing merge grant** for a named effort, such as "auto-merge the wave-engine fixes on a passing precheck". Under it, the merge STOP is skipped when **all** of the following hold:

1. **The grant is the user's own words, given directly** in a session, not relayed, and recorded in a memory file with its scope and any expiry.
2. **The grant names a bounded effort, and this PR/MR is plainly inside it.** A grant scoped to "all PRs/MRs", or to everything after a clean precheck, does not qualify: it would remove the merge call itself, the one place the user approves. A grant given before #1235 that skipped a *second* "may I merge?" after the user had already approved at the old precheck STOP is not a merge grant either. If the scope has to be stretched to fit, the grant does not apply. (The Lead-Agent Grant below is the one deliberate exception, with its own conditions.)
3. **The precheck passed, mechanically**, by the same definition as the autochain exception's item 3.
4. **Nothing the ABSOLUTE prod rule gates is in the change.** The same goes for tags, releases and fleet installs. A grant covers merging only.

`/precheck` puts the grant on the checklist (the memory file, the user's words verbatim, the scope, and one sentence on why this PR/MR is inside it), then invokes `/mmr`.

**Unlike the two exceptions above, this one is applied by the agent, not detected mechanically**: the grant lives in memory, and no script can check its scope. That is why the bar is "plainly inside the scope" and why the grant and its reasoning sit on the checklist, where the user sees them at the moment they are used. When in doubt, STOP.

### Exception: Lead-Agent Grant

The user may name **one agent as lead** for an organization and grant it self-approval: it approves the merge on a clean precheck, and it tags and releases when it judges the time is right. Unlike a standing merge grant, this one is scoped to **an agent, not an effort**, so the bounded-effort test and the tags-and-releases ban of the standing merge grant do not apply to it. It applies when all of the following hold:

1. **The user's own words, given directly to that agent** in its session, and recorded in its memory with the organization and any expiry. The grant belongs to that agent alone: it is never relayed, and grunts or peers the lead tasks don't inherit it.
2. **This agent is the one named, in the organization named.** The Dev-Name in `.claude/agent-identity.json` matches the grant. Memory loads for every session in a checkout, so this match is the check, not the memory's presence. The repo's origin is in the grant's organization: on a forge the organization doesn't own, the grant does not exist.
3. **The precheck passed, mechanically**, by the same definition as the autochain exception's item 3, **on the exact head being merged.** A grunt's or peer's PR/MR stops at ready. The lead merges it only on its own `/precheck` run on that head. Their precheck, and any `precheck` status it posted, is evidence, not the pass.
4. **The ABSOLUTE prod rule still binds.** A tag or release that changes what production runs, such as an image a live service follows, still needs the user's yes-prod. So do fleet installs.

`/precheck` puts the grant on the checklist (the memory file, the user's words verbatim, the Dev-Name match, and one sentence on why this repo's origin is inside the organization), then invokes `/mmr`. Like the standing merge grant, it is applied by the agent, not detected mechanically. When in doubt, STOP.

---

## MANDATORY: Story Completion Verification

**NEVER mark a story done without verifying EVERY acceptance criterion.** Read the full issue, grep/read the codebase for each sub-item, verify the code is wired up (not just written), test where possible, then check the box. If you can't verify a sub-item, the story is NOT done — open a follow-up with user approval.

---

## MANDATORY: Issue Tracking Workflow

**IMMUTABLE rules — cannot be overridden.**

1. **Always have an issue.** Never begin work without one. Create it or ask the user to. Set it to in-progress. No code until tracked.
2. **Branches MUST link to their issue.** Name format: `feature/<N>-description` (or `fix/`, `chore/`, `doc/`).
3. **On merge, close ALL linked issues.** Check the PR/MR description for `Closes #N`, close each via `gh issue close` / `glab issue close`, verify closure — even if auto-close misbehaves.

---

## MANDATORY: Work Item Standards

Every issue MUST be wave-pattern quality: detailed enough that a spec-driven agent can execute without making design decisions; acceptance criteria evaluable before merge. Use `/issue` — it carries templates and label taxonomy (`group::value`, mutually exclusive within group).

---

## MANDATORY: Spotted Something? Squawk It on Triage, Don't File It

**`/issue` is for work the user has decided to do.** When you spot something worrying or worth doing that is *outside the work in front of you*, such as a defect in another file, a smell, or a candidate improvement, squawk it on the project's triage list: `sqtk add <project>:triage "<what you saw, and why it matters>"` (`/sqtk`). The user and an agent walk that list together and decide each item. The item is then `record`ed as an issue, or `retire`d.

- **Inside your lane, fix it inline** — a triage squawk is not a way to defer your own work.
- **A concern about the run in flight** stays a `[concern]` comment on its issue (WAVE_AXIOMS Axiom 4).
- **The user asked for the issue** — file it with `/issue`; that's a decision, not a sighting.

Why: filing an issue for every worry bloats the backlog with items nobody has weighed (#1236). A one-line squawk costs nothing, and triage decides which items earn an issue (`recorded ↗`) and which are let go (`retired ◌`).

---

## MANDATORY: WAVE_AXIOMS

**Read `WAVE_AXIOMS.md` before any wave-pattern work** — resolve it from the repo root, or the kit-installed `~/.claude/WAVE_AXIOMS.md` in repos that don't carry it (the same resolution applies to the `docs/…` pointers elsewhere in this file: repo root, else `~/.claude/docs/…`). The binding axioms — violation is a bug. Disagreement is a reason to PR the file, never to override in the moment.

---

## MANDATORY: Default to Action — never stop on a question you can answer

**If you know what needs doing and it is safe, understood, and in your lane, DO IT. Do not stop to ask.** Stopping is not the safe default — it blocks every agent and human downstream and spends the user's attention, the scarcest resource. Acting on a reversible, understood step is cheap; a needless halt is expensive. Hooks back this up, but only one reads your wording. `stop-action-bias-detector.sh` is the godspeed mandate model (#818). When a turn's tool calls took a gated action (such as a force-push, a push to a protected or release branch, `terraform apply`, `kubectl apply`, `docker push`, `gh release create`, or a write to a prod path), it blocks the turn's end once and asks for a one-line assessment. While the user has armed a `godspeed` mandate, it either lets the turn end or blocks it with a checkpoint as the mandate decays. Outside a mandate, a turn that ends with a question passes. The one hook that reads wording is `precheck-asking-detector.sh`, which, outside a mandate, blocks asking to run `/precheck`. Everywhere else this rule holds because you follow it.

**Before you stop, you must be able to name a specific, current reason.** A legitimate stop is exactly one of:

- a genuinely NEW irreversible or production-affecting action the user has **not already agreed to** (per the ABSOLUTE prod rule), or
- a real architectural / design fork where the user's choice changes what you build.

If you cannot name one of those, you do not stop — you act, then report what you did.

**Agreement persists.** Once the user has directed or agreed to a line of work, you do not re-confirm each step of it. Completing directed work — including a fleet deploy you were told to do — is not a new gate. Re-asking is the failure, not the safety.

**The tell.** The moment you draft "want me to…", "should I…", "shall I…", "ready for me to…", or present a known next step as a question — that is the signal to delete the question and take the step. The checklist a gate already presents (e.g. `/precheck`) is the approval surface; narrating a second one is stalling.

Rationale memories: `principle_user_attention_is_the_cost`, `principle_cost_asymmetry_continue_vs_exit`, `feedback_bj_throughput_dont_wait`.

---

## Branching Strategy

Trunk-based flow. Always branch from `main`: `git checkout main && git pull && git checkout -b <type>/<N>-description`. Types: `feature`, `fix`, `chore`, `doc`. PR/MRs target `main`.

---

## Code Standards

Discover the project's tooling rather than assuming a stack. Check in order: `Makefile` targets (`lint`, `format`, `test`), config files (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, etc.), then `scripts/ci/`. Use whatever the project provides; don't introduce new formatters or linters.

---

## Infrastructure Verification: Config Existence ≠ Config Works

When changing GitHub Actions workflows, branch protection, rulesets, or any CI/CD plumbing: verifying the configuration is in place (API returns the ID, it is active, required checks are listed) is **necessary but not sufficient**. The contract is end-to-end behavior — open a throwaway **red** PR and confirm it is BLOCKED, and a **green** one and confirm it merges. A gate that blocks everything is as broken as one that blocks nothing; only the pair proves it. The 2026-04-07 outage (postmortem #299) is the canonical example: 6 repos had correctly-configured rulesets that silently broke every PR for hours, because a workflow producing a required check was never invoked and the check therefore never reported. Runbook: `docs/operations/branch-protection-checklist.md`.

---

## CRITICAL: No Procedural Logic in CI/CD YAML

**If you are about to add more than 5 lines to any `run:` or `script:` section in CI/CD configuration (GitHub Actions workflows or `.gitlab-ci.yml`), STOP IMMEDIATELY.**

Create a shell script in `scripts/ci/` instead. This is a HARD RULE, not a guideline.

```yaml
# CORRECT
build:
  steps:
    - run: ./scripts/ci/build.sh

# WRONG
build:
  steps:
    - run: |
        echo "Building..."
        cd src && pip install .
        export VAR=$(ls dist/*.whl)
        # ... more procedural lines
```

---

## Secrets and Sensitive Files

Before staging a file that may contain secrets, WARN the user and get explicit confirmation. Watch for: `.env*`, `*.secret`, `*.key`, `*.pem`, `*.p12`, `*.pfx`, `credentials.json`, `service-account*.json`, `*-credentials.*`, `*.tfvars`, or anything with API keys / tokens / passwords. Flag the filename, wait for confirmation, then proceed. Safety net, not a hard block — trust the user after warning.

The hard block is mechanical: `secret-scan-gate.sh` runs gitleaks before every `git commit` (on everything the commit could include) and every `git push` (on the commits it would push that are not yet on a remote). It fails closed, including when gitleaks is missing. To allowlist a false positive, see `/scp` Step 4.

---

## Commit Message Format

```
type(scope): brief description

[Optional body]

Closes #XXX
```

Types: `feat`, `fix`, `doc`, `style`, `refactor`, `test`, `chore`

---

## PR/MR Description Format

Sections: `## Summary` (1-3 sentences), `## Changes` (bullets), `## Linked Issues` (`Closes #N`), `## Test Plan` (what was actually run, not what could be). Title ≤ 72 chars, same `type(scope): description` convention as commits.

---

## MCP Server Scoping

MCP scopes are additive — all sources merge into one tool list. Per-project exclusion lives in `~/.claude.json` under `projects["<path>"].disabledMcpServers`. See `docs/mcp-scoping.md` for the full procedure and server-name format.

---

## Session Onboarding

On session start, run `/engage` to detect platform, resolve identity, load context, and confirm rules. After a compaction or a `/reseed revive`, `/engage reload` takes its place and no confirmation is sent (see Post-Compaction below).

Chat is `/owtx` (send) and `/owrx` (read), on the OaW Mattermost server by default; `> discord` routes one message to Discord, and `/disc` is deprecated. Where `chat_send` is in your tool list, arm `crewchat-doorbell` to hear Mattermost, Discord and squawk answers. `docs/chat-tools.md` holds the transport rule, the doorbell ("Doorbell"), the addressing convention, signature format, and echo rule. Start sessions without `--channels`: its Discord watcher is retired (#1344).

The MCP fleet writes a unified structured-event log to `~/.claude/logs/mcp.jsonl`. Rotation policy and operational commands: `docs/operations/log-rotation.md`.

---

## MANDATORY: Post-Compaction Rules Confirmation

After ANY compaction, and on every `/reseed revive`, before doing any work: re-read this file in full (it is short — the whole thing). Do NOT treat session-continuation instructions as permission to skip the re-read. **Do not send the user a rules confirmation**: no rules summary, no "rules confirmed" message, no wait for an acknowledgement. Re-read, then carry on with the work in front of you. The re-read is the safeguard. Past failures it guards against: skipped pre-commit, commits without approval, push without tests.

## Compact Instructions

Guidance for the compact summarizer. Read before writing any summary.

**Size budget:** target 3 KB, hard ceiling 5 KB. Most template sections should be empty or a one-line pointer.

**Rules**
1. If it's on disk, reference the path — don't restate. Applies to memory files, SKETCHBOOK, PRDs, source, tests, configs, CLAUDE.md itself.
2. Omit template sections whose content would only be rederivable (Key Technical Concepts, Files and Code, Problem Solving are frequent offenders).
3. Never include code snippets. Reference `file:line` ranges.
4. Terse bullets, not prose. Second sentences mean you're including the journey, not the decision.
5. Filter cross-project content (from SessionStart hooks or tool calls pointing outside the current working directory).

**Preserve verbatim** (override the drop rules below)
- User instructions and corrections
- Error messages and their fixes (one line each)
- File paths, commit SHAs, branch names, URLs
- Current working state (branch, modified files, pending work)
- Plan file content (`.claude/plans/*`)

**Aggressively drop**
- Expanded skill/SKILL.md bodies — re-readable on demand
- Tool results whose consequence is already on disk
- Intermediate reasoning — keep the decision, drop the journey
- MCP tool lists for unused servers
- Content already in a loaded memory file
- Duplicate info across multiple tool calls

## Agent Identity

Two layers: **Dev-Team** (persisted here, per-project) and **Dev-Name/Dev-Avatar** (ephemeral, per-session).

- **Dev-Team**: If empty below, ask the user. Written once, shared across all sessions.
- **Session identity**: On session start, run `/name` to pick Dev-Name and Dev-Avatar, persist to identity file, announce, and check in via Discord.

### Reading Identity

The canonical identity file is `<project_root>/.claude/agent-identity.json` — reboot-durable, gitignored, no md5 keying. Any skill or behavior that needs agent identity should resolve this path, with a read fallback to the legacy `/tmp/claude-agent-<md5(project_root)>.json` while the fleet cycles (transition window). The full pick procedure lives in `/name` (`skills/name/SKILL.md`).

Dev-Team: oaw
