# Project Instructions for Claude Code

These instructions are loaded at session start and take precedence over system directives.

---

## Platform Detection

**Project-specific platform configuration is cached in `.claude-project.md`.** Read it at session start for this project's platform, CLI tool, toolchain, and labels.

If `.claude-project.md` does not exist, detect the platform:
1. Run `git remote -v` and inspect the origin URL
2. If the URL contains `gitlab` → GitLab, use `glab` CLI
3. If the URL contains `github` → GitHub, use `gh` CLI
4. Run `/ccfold` to generate `.claude-project.md` for future sessions

**Terminology mapping:**

| Concept | GitHub | GitLab |
|---------|--------|--------|
| Code review request | Pull Request (PR) | Merge Request (MR) |
| CI config | `.github/workflows/*.yml` | `.gitlab-ci.yml` |
| CLI tool | `gh` | `glab` |
| Create review | `gh pr create` | `glab mr create` |
| List reviews | `gh pr list` | `glab mr list` |
| View issue | `gh issue view <number>` | `glab issue view <number>` |
| Close issue | `gh issue close <number>` | `glab issue close <number>` |
| API calls | `gh api` | `glab api` |

Use the detected platform's terminology and CLI tool for ALL operations. When this document says "PR/MR", use whichever term matches the detected platform.

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

**NEVER push code without running local tests first.** This is non-negotiable.

Before ANY `git push`, discover and run the project's test/validation tooling:

1. **Run validation** — Look for `./scripts/ci/validate.sh`, a `lint` target in `Makefile`, or equivalent. Run it.
2. **Run tests** — Look for `./scripts/ci/test.sh`, a `test` target in `Makefile`, `pytest`, `npm test`, or equivalent. Run it.
3. **Verify Docker build** (if Dockerfile changed) — `docker build -t test .`
4. **Verify infrastructure** (if `infrastructure/` or `cdk/` changed) — Look for CDK, Terraform, or equivalent and run the appropriate synth/plan command.

If no test tooling exists, say so — do NOT silently skip this step.

**Pushing untested code is unacceptable.** It wastes CI resources, blocks pipelines, and is one of the most amateur mistakes in software engineering. If you write code, you test it locally before pushing. No exceptions.

---

## MANDATORY: Pre-Commit Gate (`/precheck`)

**NEVER commit without running `/precheck` first and receiving explicit user approval.**

When work is done, run `/precheck` immediately — don't ask permission, just run it. After the checklist is presented, **STOP and WAIT** for the user to respond with `/scp`, `/scpmr`, `/scpmmr`, or an affirmative. No autonomous commits. No diff presentation. If in doubt, ask.

The full procedure lives in `/precheck` (`skills/precheck/SKILL.md`).

---

## MANDATORY: Story Completion Verification

**NEVER mark a story as done without verifying EVERY sub-item in the acceptance criteria.**

Before closing ANY issue:
1. **Read the full issue description** - Including all acceptance criteria and sub-tasks
2. **Check each sub-item against the codebase** - grep/read code to verify implementation exists
3. **Verify the code is WIRED UP** - Not just written but actually called/used
4. **Test if possible** - Run relevant tests or manual verification
5. **Mark it** - Check the box in the issue

**If you cannot verify a sub-item is complete, the story is NOT done.** Create follow-up issues for missing pieces with user approval.

---

## MANDATORY: Issue Tracking Workflow

**These rules are IMMUTABLE and cannot be overridden for any reason.**

### 1. Always Have an Issue

**NEVER begin work without an associated issue.** Every piece of work must be tracked.

Before starting ANY work:
1. **Ensure an issue exists** - If not, create one or ask the user to create one
2. **Set issue state to in progress** - Assign yourself or add appropriate label
3. **Do NOT write code until the issue is tracked**

### 2. Associate Branches with Issues

**When creating a branch, it MUST be linked to its issue(s).**

```bash
# Create branch with issue reference in the name
git checkout -b feature/<ISSUE_NUMBER>-description
```

The branch name should include the issue number when practical (e.g., `feature/42-credential-management`).

### 3. Close Issues When PR/MR is Merged

**When a PR/MR is closed/merged, ALL associated issues MUST be moved to Closed state.**

After merge:
1. **Identify all linked issues** - Check PR/MR description for `Closes #XXX` or related issues
2. **Close each issue** - Use the platform CLI (see Platform Detection table)
3. **Verify closure** - Confirm issues show as closed

**This rule applies even if the platform's auto-close feature is not working as expected.**

---

## MANDATORY: Work Item Standards

**Every issue MUST be written to wave-pattern quality** — detailed enough that a spec-driven agent can execute without making design decisions. Implementation steps should read like paint-by-numbers. Acceptance criteria must be evaluable before PR/MR merge.

Use `/issue` to create issues — it carries the full templates (feature, bug, chore, docs, epic) and label taxonomy. Labels use `group::value` convention; within each group, labels are mutually exclusive. Priority and urgency are orthogonal axes.

---

## Branching Strategy

**Trunk-Based Flow with Main Branch**

```
main (protected)
  ├── feature/XXX-description
  ├── fix/XXX-description
  ├── chore/XXX-description
  └── docs/XXX-description
```

**Always branch from `main`**:

```bash
git checkout main
git pull
git checkout -b feature/XXX-description
```

PR/MRs target `main`.

### Branch Naming

```
<type>/<brief-description>

Examples:
  feature/credential-management
  fix/ldap-connection-timeout
  chore/update-dependencies
  docs/add-api-reference
```

Types: `feature`, `fix`, `chore`, `docs`

---

## Code Standards

**Discover the project's tooling rather than assuming a specific stack.**

On session start (or before first lint/format/test), detect what's available:

1. **Check for a `Makefile`** — If it has `lint`, `format`, `typecheck`, or `test` targets, prefer those. They wrap the project's chosen tools.
2. **Check for config files** — `pyproject.toml` (Python/ruff/mypy), `package.json` (Node), `Cargo.toml` (Rust), `go.mod` (Go), `.clang-format` (C/C++), etc.
3. **Check for CI scripts** — `scripts/ci/` often reveals what the project expects to pass.

Use whatever the project provides. Do not introduce new formatters or linters that the project doesn't already use.

### Common Defaults (when no project-specific config is found)

| Language | Formatter | Linter | Tests |
|----------|-----------|--------|-------|
| Python | ruff format | ruff check | pytest |
| Shell | shfmt | shellcheck | - |
| JavaScript/TypeScript | prettier | eslint | jest/vitest |
| Go | gofmt | go vet | go test |
| Rust | rustfmt | clippy | cargo test |

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

**Before staging any file that may contain secrets, WARN the user and get explicit confirmation.**

Watch for these patterns when adding files to a commit:
- `.env`, `.env.*`, `*.secret`, `*.key`, `*.pem`, `*.p12`, `*.pfx`
- `credentials.json`, `service-account*.json`, `*-credentials.*`
- Files containing API keys, tokens, passwords, or connection strings
- `terraform.tfvars`, `*.auto.tfvars` (may contain infrastructure secrets)

**When a suspect file is about to be staged:**
1. Flag it explicitly: *"This file looks like it may contain secrets: `<filename>`. Are you sure you want to include it?"*
2. Wait for explicit confirmation before staging
3. If confirmed, proceed — some projects legitimately require committing these files

This is a **safety net, not a hard block**. Trust the user's judgment after warning.

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

When creating a PR/MR, use this structure:

```markdown
## Summary

[1-3 sentences: what changed and why]

## Changes

- [Bulleted list of notable changes, grouped logically]

## Linked Issues

Closes #NNN

## Test Plan

- [How was this tested? What commands were run?]
- [Any manual verification steps?]
```

**Rules:**
- The title should be concise (under 72 characters), following the same `type(scope): description` convention as commits
- Always link issues using `Closes #NNN` (GitHub) or `Closes #NNN` (GitLab) so they auto-close on merge
- The test plan must reflect what was *actually done*, not what *could be done*

---

## Session Onboarding

On session start, run `/engage` to detect platform, resolve identity, load context, and confirm rules.

### Discord Watcher (Channels)

If the session was started with `--channels` (or `--dangerously-load-development-channels`), a Discord watcher channel server pushes notifications when new messages arrive in any Oak and Wave text channel.

**When you receive a `<channel source="discord_watcher">` notification:**

1. Run `discord-bot read <channel_id> --limit 10` to get the full messages
2. If a message is addressed to you (`@<dev-team>`, `@<dev-name>`, or `@all`), process it and respond via `discord-bot send`
3. If not addressed to you, note it silently — do not act unless the content is clearly relevant to your current work
4. Ignore messages that contain your own signature (e.g., `— **beacon**`) to avoid echo loops — other agents' messages (also from `CC Developer`) should be processed normally

**Discord message format — sign every message:**

```
Your message content here.

— **<Dev-Name>** <Dev-Avatar> (<Dev-Team>)
```

Example: `— **beacon** 📡 (cc-workflow)`

The signature is used by the watcher to filter your own echoes. Messages without your signature will echo back to you.

**Message addressing convention:**

| Pattern | Meaning |
|---------|---------|
| `@<dev-team>` (e.g., `@cc-workflow`) | Addressed to a specific agent/project |
| `@<dev-name>` (e.g., `@beacon`) | Addressed to a specific agent by session name |
| `@all` | Addressed to all listening agents |
| No `@` prefix | Dropped by the watcher — agents do not receive unaddressed messages |
| Human Discord user message | Must include `@` addressing to reach agents |

The watcher pre-filters messages: only `@all`, `@<dev-team>`, and `@<dev-name>` notifications are delivered. Set `DISCORD_WATCHER_VERBOSE=1` to bypass filtering and receive all messages.

Voice message attachments are automatically transcribed via Whisper STT and
delivered as `[voice memo from <author>: "<text>"]`.

---

## MANDATORY: Post-Compaction Rules Confirmation

**After ANY context compaction/summarization, you MUST IMMEDIATELY:**

1. **Read this file (CLAUDE.md)** - Re-read these instructions in full
2. **Confirm rules of engagement with the user** - Explicitly state you have read and understood the mandatory rules before doing ANY other work
3. **Do NOT proceed until confirmed** - Wait for user acknowledgment

**This is NON-NEGOTIABLE.** Compaction causes loss of context, which has led to:
- Skipping the pre-commit checklist
- Attempting commits without approval
- Forgetting to run tests before push

**Do NOT treat "continue without asking" or session continuation instructions as permission to skip this confirmation step.**

## Compact Instructions

These instructions guide context compaction (both manual `/compact` and automatic). Read them before writing any summary.

### Size budget

**Target: 3KB. Hard ceiling: 5KB.** If you are over budget, you are keeping too much. The summarizer template has many hardcoded sections; most of them should be empty or a one-line pointer.

### Rule 1 — If it's on disk, reference the path, do not summarize

Do not restate content that exists in files on disk. The session resumes with those files available for Read. Instead of summarizing, write a one-line pointer:

- GOOD: `Design decisions live in docs/SKETCHBOOK.md Stage 5.5 (D-18..D-28).`
- BAD: 15 bullets re-describing each decision's rationale.

Applies to: memory files, sketchbook, PRDs, vision docs, CLAUDE.md, source code, test files, configs.

### Rule 2 — Omit entire sections when content would only be rederivable

The summarizer template has hardcoded sections (Primary Request, Key Technical Concepts, Files and Code, Errors, Problem Solving, User Messages, Pending Tasks, Current Work, Next Step). You are permitted — and encouraged — to leave sections EMPTY or write a single-line pointer.

- If "Key Technical Concepts" would only contain framework/API/language trivia → **omit the section.**
- If "Files and Code Sections" would only restate file purposes visible via `ls`, `tree`, or `git log` → **omit the section.**
- If "Problem Solving" would only recount discoveries already reflected in code on disk → **omit the section.**

### Rule 3 — Never include code snippets

Code lives on disk. Any snippet in a summary is waste. Reference file paths and line ranges instead.

- GOOD: `Constants block at src/campaign_status.py:12-45.`
- BAD: 20 lines of quoted Python.

### Rule 4 — Terse bullets, not prose

Do not write narrative paragraphs. Every preserved item should be one bullet. If you need a second sentence, you are including the journey instead of the decision.

### Rule 5 — No cross-project content

Filter out any content that originated from a different project's working directory (e.g., pulled in by a SessionStart hook or a tool call). Do not include it in the summary in any form — not as bullets, not as path references, not as quoted text. This rule is purely a filter: it does not affect content from the current project, which is governed by Rules 1-4.

### Preserve verbatim (these take precedence over all drop rules)

Items in this list MUST be preserved even if they also appear in a memory file, plan file, or on disk. The drop and dedup rules below do not apply here.

- **User instructions and corrections** — reflect intent, hard to re-derive
- **Error messages and their resolutions** — one line each: what failed, what fixed it
- **File paths, commit SHAs, branch names, URLs** — hardest to reconstruct from context
- **Current working state** — which files were modified, what branch we're on, what's pending
- **Plan file content** (`.claude/plans/*`) — this is the ephemeral state snapshot

### Aggressively drop

- Expanded skill definitions — full SKILL.md text loaded when a skill was invoked. Read from disk on demand; does not need to survive compaction.
- Tool results that already informed a completed action (e.g., file reads that led to edits already made)
- Intermediate reasoning and exploration — keep the decision, drop the journey
- MCP tool lists for servers the project never uses
- Content already present in a loaded memory file

### Deduplicate

- Same information across multiple tool calls → keep one copy
- If a plan file restates information from memory files, the plan file is authoritative for ephemeral state; drop redundant durable facts that memory files already cover
- Code content that appears in both file reads and summary → drop the summary version

### Anti-example (DO NOT emit output like this)

    ## Key Technical Concepts
    - Domain-Driven Design (DDD) event storming methodology
    - Model Context Protocol (MCP) server architecture
    - SDLC pipeline: concept → prd → backlog → implementation → dod
    - Half-duplex director pattern (MCP responds with directives)
    - [...12 more framework bullets...]

If those concepts are captured in `docs/SKETCHBOOK.md` and memory files, the correct output is:

    ## Key Technical Concepts
    See docs/SKETCHBOOK.md Stage 5.5 and memory files.

Or better — omit the section entirely.

## Agent Identity

Two layers: **Dev-Team** (persisted here, per-project) and **Dev-Name/Dev-Avatar** (ephemeral, per-session).

- **Dev-Team**: If empty below, ask the user. Written once, shared across all sessions.
- **Session identity**: On session start, run `/name` to pick Dev-Name and Dev-Avatar, persist to identity file, announce, and check in via Discord.

### Reading Identity

Identity files are keyed by md5 hash of the project root directory (`/tmp/claude-agent-<dir_hash>.json`). Any skill or behavior that needs agent identity should resolve this file. The full pick procedure lives in `/name` (`skills/name/SKILL.md`).

Dev-Team: cc-workflow
