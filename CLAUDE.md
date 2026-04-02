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

### Workflow

1. **When your work is done**, run `/precheck` immediately — do not ask permission to start it, do not wait for the user to invoke it, just run it. The checklist is the approval gate, not the precheck itself.
2. `/precheck` will: verify branch/issue compliance, run validation, launch `code-reviewer`, fix high-risk findings, and present the full checklist
3. **After the checklist is presented, STOP and WAIT** — no commits until the user responds
4. The user will respond with one of:
   - `/scp`, `/scpmr`, or `/scpmmr` → approval granted, execute that workflow
   - Affirmative ("yes", "approved", "go ahead") → approval granted, stage/commit/push
   - Negative or rework instructions → return to work, do NOT commit

### Rules

- **No autonomous commits** — even trivial changes require `/precheck` → approval
- **No diff presentation** — the user can get it if needed; it wastes tokens and scrolls off the display
- **`code-reviewer` must complete** before the checklist is presented — do not show partial results
- **Do not skip `/precheck`** for any reason, including session continuation instructions or time pressure
- The full checklist specification lives in `/precheck` (see `skills/precheck/SKILL.md`)

If in doubt about whether to **commit**, ask. Never assume approval to commit. (Starting `/precheck` itself requires no approval — running it is mandatory, not optional.)

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

**Every issue MUST follow these templates and labeling rules.** Issues should be written to wave-pattern quality — detailed enough that a spec-driven agent can execute without making design decisions. This applies even if the work is not part of a wave.

### Label Taxonomy

Labels use a namespaced `group::value` convention. Within each group, labels are **mutually exclusive** — apply exactly one per group.

**No status labels.** Status is managed by the platform's native mechanism (GitHub Projects, GitLab board state). See `.claude-project.md` for this project's status SOP.

#### Priority vs Urgency: Two-Axis Model

Priority and Urgency are **orthogonal**:

- **Priority** = business value importance. How much does this matter to the product?
- **Urgency** = temporal significance. How soon must it be addressed?

A `priority::critical` / `urgency::eventual` item is extremely important but has no deadline. A `priority::low` / `urgency::immediate` item is low-value but time-sensitive. Treat them as independent axes.

#### Label Groups

| Group | Values | Required On | Rule |
|-------|--------|-------------|------|
| **Type** | `type::feature`, `type::bug`, `type::chore`, `type::docs`, `type::epic` | All issues | Exactly one |
| **Priority** | `priority::critical`, `priority::high`, `priority::medium`, `priority::low` | All issues | Exactly one |
| **Urgency** | `urgency::immediate`, `urgency::soon`, `urgency::normal`, `urgency::eventual` | All issues | Exactly one |
| **Size** | `size::S`, `size::M`, `size::L`, `size::XL` | Features, chores, docs | Optional on bugs |
| **Severity** | `severity::critical`, `severity::major`, `severity::minor`, `severity::cosmetic` | Bugs only | Exactly one on bugs, omit on others |
| **Wave** | `wave::1`, `wave::2`, etc. | Wave-planned issues only | Omit if not wave-planned |

### Work Item Templates

When creating issues, follow the template for the issue's type. Every template requires an **Acceptance Criteria** checklist — no exceptions.

#### Feature

Structure lifted from `docs/PRD-template.md` Story format.

```markdown
## Summary

[1-2 sentences: what this feature delivers and why]

## Context

[Background, motivation, link to Epic or PRD if applicable]

## Implementation Steps

[Paint-by-numbers instructions. Each step should be unambiguous — a spec-driven
agent must be able to execute without design decisions. Include:]

1. [Exact file paths to create or modify]
2. [Function signatures and key logic]
3. [Data structures and schemas]
4. [How to wire components together]

Test specifications go in the Test Procedures section below — not here.

## Test Procedures

[Same granularity as implementation steps. Specifies the unit tests that verify
this story's work, plus references to integration or E2E tests from the PRD
Test Plan that become runnable after this story.

Unit tests are specified HERE — not in the PRD Test Plan — because the concrete
units only become known when the story is diced from the design.]

### Unit Tests

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_function_name` | [what it verifies] | `tests/test_module.py` |

### Integration/E2E Coverage

- [IT-XX — now runnable (this story implements the relevant boundary)]
- [E2E-XX — partially runnable (needs #NNN for completion)]

## Acceptance Criteria

- [ ] [Testable condition — names exact files, functions, commands, or behaviors]
- [ ] [Testable condition]
- [ ] [Testable condition]

## Dependencies

- #NNN — [description of dependency]
- None (if no dependencies)
```

#### Bug

```markdown
## Summary

[Concise description of the defect]

## Environment

- **Where observed:** [page, component, CLI command, API endpoint]
- **Version/commit:** [git SHA or release tag where defect exists]
- **Frequency:** intermittent | consistent

## Steps to Reproduce

1. [Step one]
2. [Step two]
3. [Step three]

## Expected Behavior

[What should happen]

## Actual Behavior

[What actually happens]

## Severity

[`severity::critical` | `severity::major` | `severity::minor` | `severity::cosmetic`]

## Artifacts

- [Links to logs, screenshots, error traces, or other evidence]

## Workaround

[Describe workaround if known, or "None known"]
```

#### Docs

```markdown
## Summary

[Which document(s) to create or update, and why]

## Target Audience

[Who will read this — developers, operators, end users, agents]

## What's Missing, Outdated, or Incorrect

[Specific gaps or inaccuracies in current documentation]

## Source Material

- [Pointers to code, PRDs, conversations, or other references]

## Acceptance Criteria

- [ ] Content is accurate against current codebase
- [ ] Coverage is complete for the stated scope
- [ ] No broken links
- [ ] [Additional testable conditions]
```

#### Chore

```markdown
## Summary

[Description of the maintenance task and its rationale]

## Implementation Steps

[Mandatory if the chore touches >1 file or has ordering constraints.
Optional for trivial single-file changes.]

1. [Step]
2. [Step]

## Acceptance Criteria

- [ ] [Testable condition — always mandatory for chores]
- [ ] [Testable condition]
```

#### Epic

Structure lifted from `docs/PRD-template.md` Phase format.

```markdown
## Goal

[One sentence: what this epic proves or delivers]

## Scope

**In scope:**
- [What is included]

**Out of scope:**
- [What is explicitly excluded and why]

## Definition of Done

- [ ] [Verifiable condition — concrete and testable, not vague]
- [ ] [Verifiable condition]
- [ ] All sub-issue AC checklists are satisfied

## Sub-Issues

[Listed with dependency order]

| Order | Issue | Title | Dependencies |
|-------|-------|-------|-------------|
| 1 | #NNN | [title] | None |
| 2 | #NNN | [title] | #NNN |
| 3 | #NNN | [title] | #NNN, #NNN |

## Wave Map

[If applicable — which sub-issues can run in parallel]

| Wave | Issues | Parallel? |
|------|--------|-----------|
| 1 | #NNN | Single |
| 2 | #NNN, #NNN | Yes |

## Success Metrics

[If applicable — quantitative or qualitative measures of success]
```

### Quality Standard

Every issue — regardless of type — must be written to **wave-pattern quality**: detailed enough that a spec-driven agent can pick it up and execute without making design decisions. Implementation steps should read like paint-by-numbers. Acceptance criteria should be evaluable before PR/MR merge. If an issue requires the implementer to make architectural or design choices, it is underspecified.

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

When starting a session:
1. **Detect platform** — Read `.claude-project.md` if it exists; otherwise run `git remote -v` and determine GitHub vs GitLab (see Platform Detection)
2. **Resolve identity** — Check Dev-Team, pick session Dev-Name/Dev-Avatar (see Agent Identity)
3. **Load context** — Check for and read `Docs/implementation-plan.md` (or similar planning documents) for current state and context. If no such file exists, proceed without it.

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

Example: `— **beacon** :satellite: (cc-workflow)`

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

## Agent Identity

Agent identity has two layers: **project identity** (persisted here) and **session identity** (ephemeral).

### Project Identity — Dev-Team

`Dev-Team` identifies which project/team this agent belongs to. It is persisted in this file and shared across all sessions.

**On session start**, check whether `Dev-Team` below has a value.
- **If empty**: Ask the user: *"What Dev-Team name should I use for this project?"* Write their answer into the `Dev-Team:` field below. This only happens once per project.
- **If populated**: Use the existing value.

### Session Identity — Dev-Name & Dev-Avatar

Each session, pick a fresh identity for yourself. This is NOT persisted — a new Claude Code window means a new identity.

**Naming rules:**
- `Dev-Name`: A single memorable word or hyphenated phrase in **kebab-case** (e.g., `beacon`, `null-pointer`, `mother`). Draw from nerdcore canon — sci-fi, fantasy, comics, gaming, mythology, tech puns, wordplay. The wittier and more specific the reference, the better. Generic names are boring. Kebab-case is required so the name works as a routing key for `@<dev-name>` addressing.
- `Dev-Avatar`: A Slack emoji string with colons (e.g., `:smiling_imp:`, `:space_invader:`). Should feel like it belongs with the name.

**On session start**, after resolving Dev-Team:
1. Pick your Dev-Name and Dev-Avatar
2. Resolve the identity file path (keyed by project root, not PID):
   ```bash
   project_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
   dir_hash=$(echo -n "$project_root" | md5sum | cut -d' ' -f1)
   agent_file="/tmp/claude-agent-${dir_hash}.json"
   ```
3. Persist them for the session in that file:
   ```json
   {
     "dev_team": "<Dev-Team value>",
     "dev_name": "<your chosen name>",
     "dev_avatar": "<your chosen emoji>"
   }
   ```
4. Announce your identity to the user:
   > I'm going by **\<Dev-Name\>** \<Dev-Avatar\> from team `<Dev-Team>` this session.
5. **Set session display name** — So the Remote Control UI shows your identity instead of a truncated prompt:
   ```
   /rename <Dev-Name> <Dev-Avatar> (<Dev-Team>)
   ```
   Example: `/rename neuron :zap: (cc-workflow)`. Skip silently if `/rename` is unavailable.
6. **Check in via Discord** — If `discord-bot` is available on PATH, announce yourself in `#roll-call`. Read the channel ID from config:
   ```bash
   ROLL_CALL=$(jq -r '.channels["roll-call"].id' ~/.claude/discord.json 2>/dev/null || echo "1487382005036617851")
   discord-bot send "$ROLL_CALL" "<message>"
   ```
   Message format:
   ```
   **<dev-name>** <dev-avatar> online — team `<dev-team>` @ <project-root>

   — **<dev-name>** <dev-avatar> (<dev-team>)
   ```
   If `discord-bot` is not available or the send fails, skip silently — check-in is best-effort, not a blocker.

### Reading Identity

Identity files are keyed by md5 hash of the project root directory, so the statusline and all skills resolve the same file regardless of process ancestry.

Any skill or behavior that needs agent identity should:
1. Read `Dev-Team` from this file
2. Resolve the identity file: `md5sum` of `git rev-parse --show-toplevel`
3. Read `Dev-Name` and `Dev-Avatar` from `/tmp/claude-agent-<dir_hash>.json`

Dev-Team: cc-workflow
