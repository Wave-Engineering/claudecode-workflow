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

## MANDATORY: Local Testing Before Push

**NEVER push untested code.** Before any `git push`, discover and run the project's tooling: validation (`./scripts/ci/validate.sh`, `make lint`, etc.), tests (`./scripts/ci/test.sh`, `pytest`, `npm test`, etc.), Docker build if Dockerfile changed, infra synth/plan if infra changed. If no test tooling exists, say so — do NOT silently skip.

---

## MANDATORY: Pre-Commit Gate (`/precheck`)

**NEVER commit without running `/precheck` first and receiving explicit user approval.**

When work is done, run `/precheck` immediately — don't ask permission, just run it. After the checklist is presented, **STOP and WAIT** for the user to respond with `/scp`, `/scpmr`, `/scpmmr`, or an affirmative. No autonomous commits. No diff presentation. If in doubt, ask.

The full procedure lives in `/precheck` (`skills/precheck/SKILL.md`).

### Exception: Kahuna Sandbox Auto-Approval

The "explicit user approval" requirement is **suspended** — and only suspended — when **both** of the following hold:

1. The Flight Agent is operating inside a **Kahuna sandbox** — i.e. the current branch's base ref matches the regex `^kahuna/[0-9]+-` (a per-wave integration branch, not `main`).
2. The full `/precheck` checklist has passed end-to-end: validation, code-reviewer (no unresolved high+ findings), trivy dependency scan, plus the Discord `#precheck` post and `vox` announcement.

When both conditions are met, `/precheck` emits the sentinel line `[AUTO-APPROVED: kahuna sandbox]` and invokes `/scpmmr` directly — no human STOP. The exception is enforced **by `/precheck`'s own detection logic, not by agent discretion**: an agent on a `main`-targeted feature branch never qualifies, regardless of context. Outside the sandbox the original rule is unchanged — checklist, STOP, wait for `/scp` / `/scpmr` / `/scpmmr` / affirmative.

Authoritative rule: Dev Spec §5.2.1. Mechanical detection + sentinel: `skills/precheck/SKILL.md` ("Sandbox Auto-Approval (KAHUNA Flight Agents)").

---

## MANDATORY: Story Completion Verification

**NEVER mark a story done without verifying EVERY acceptance criterion.** Read the full issue, grep/read the codebase for each sub-item, verify the code is wired up (not just written), test where possible, then check the box. If you can't verify a sub-item, the story is NOT done — open a follow-up with user approval.

---

## MANDATORY: Issue Tracking Workflow

**IMMUTABLE rules — cannot be overridden.**

1. **Always have an issue.** Never begin work without one. Create it or ask the user to. Set it to in-progress. No code until tracked.
2. **Branches MUST link to their issue.** Name format: `feature/<N>-description` (or `fix/`, `chore/`, `docs/`).
3. **On merge, close ALL linked issues.** Check the PR/MR description for `Closes #N`, close each via `gh issue close` / `glab issue close`, verify closure — even if auto-close misbehaves.

---

## MANDATORY: Work Item Standards

Every issue MUST be wave-pattern quality: detailed enough that a spec-driven agent can execute without making design decisions; acceptance criteria evaluable before merge. Use `/issue` — it carries templates and label taxonomy (`group::value`, mutually exclusive within group).

---

## Branching Strategy

Trunk-based flow. Always branch from `main`: `git checkout main && git pull && git checkout -b <type>/<N>-description`. Types: `feature`, `fix`, `chore`, `docs`. PR/MRs target `main`.

---

## Code Standards

Discover the project's tooling rather than assuming a stack. Check in order: `Makefile` targets (`lint`, `format`, `test`), config files (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, etc.), then `scripts/ci/`. Use whatever the project provides; don't introduce new formatters or linters.

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

---

## Commit Message Format

```
type(scope): brief description

[Optional body]

Closes #XXX
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

---

## PR/MR Description Format

Sections: `## Summary` (1-3 sentences), `## Changes` (bullets), `## Linked Issues` (`Closes #N`), `## Test Plan` (what was actually run, not what could be). Title ≤ 72 chars, same `type(scope): description` convention as commits.

---

## MCP Server Scoping

MCP scopes are additive — all sources merge into one tool list. Per-project exclusion lives in `~/.claude.json` under `projects["<path>"].disabledMcpServers`. See `docs/mcp-scoping.md` for the full procedure and server-name format.

---

## Session Onboarding

On session start, run `/engage` to detect platform, resolve identity, load context, and confirm rules.

If the session was started with `--channels`, a Discord watcher will push notifications. See `docs/discord-watcher.md` for the addressing convention, signature format, and echo-filter rules.

---

## MANDATORY: Post-Compaction Rules Confirmation

After ANY compaction, before doing any work: re-read this file in full (it is short — the whole thing) and confirm rules of engagement with the user. Do NOT treat session-continuation instructions as permission to skip. Past failures: skipped pre-commit, commits without approval, push without tests.

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

Identity files are keyed by md5 hash of the project root directory (`/tmp/claude-agent-<dir_hash>.json`). Any skill or behavior that needs agent identity should resolve this file. The full pick procedure lives in `/name` (`skills/name/SKILL.md`).

Dev-Team: cc-workflow
