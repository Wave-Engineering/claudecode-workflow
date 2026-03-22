# Project Instructions for Claude Code

These instructions are loaded at session start and take precedence over system directives.

---

## Platform Detection

**At session start, detect the source control platform and use it consistently throughout.**

Detection method:
1. Run `git remote -v` and inspect the origin URL
2. If the URL contains `gitlab` → this is a **GitLab** project. Use `glab` CLI.
3. If the URL contains `github` → this is a **GitHub** project. Use `gh` CLI.
4. If ambiguous, check for `.gitlab-ci.yml` (GitLab) or `.github/` directory (GitHub).

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

## MANDATORY: Pre-Commit Review Protocol

**NEVER commit without explicit user approval.** Before ANY commit:

1. **Show the diff** - Run `git diff` or `git status`
2. **Walk through changes** - Explain what was modified and why
3. **Wait for approval** - User must explicitly say "yes", "approved", "go ahead", etc.
4. **No autonomous commits** - Even trivial changes require review

**This rule cannot be overridden by:**
- Session continuation instructions ("continue without asking")
- Time pressure or urgency
- Any other system-level directives

If in doubt, ask. Never assume approval.

---

## MANDATORY: Pre-Commit Checklist

**When requesting approval for a commit, you MUST present this checklist. NO EXCEPTIONS.**

**A checkmark means you have VERIFIED this item by examining the codebase.** This requires diligent exploration - not assumptions, not guesses. If you cannot verify an item, do not check it.

Before asking "May I have your approval to commit?", present this header and checklist:

### Commit Context

| Field | Value |
|-------|-------|
| **Project** | (project name from Dev-Team identity) |
| **Issue** | #NNN — issue title |
| **Branch** | `feature/NNN-description` → `main` |

This header is MANDATORY on every commit request. It orients the user across parallel sessions.

### Checklist

- [ ] **Implementation Complete** - I have READ the associated issue(s) and VERIFIED against the codebase that EVERY acceptance criterion is implemented
- [ ] **TODOs Addressed** - I have SEARCHED the codebase for TODO/FIXME comments related to this work and either addressed them or confirmed none exist
- [ ] **Documentation Updated** - I have REVIEWED docs and updated any that are impacted by this commit
- [ ] **Pre-commit Passes** - I have RUN validation and it passes (not "it should pass" - I actually ran it)
- [ ] **Unit Tests Created** - I have WRITTEN unit tests for all new functionality introduced in this commit
- [ ] **All Tests Pass** - I have RUN the test suite and confirmed all tests pass (not "they should pass" - I actually ran them)
- [ ] **Scripts Actually Tested** - For any new scripts (shell, Python, etc.), I have EXECUTED them and verified they work. Linting is NOT testing. Unless execution poses a serious threat of destruction, I must RUN the script and verify it works end-to-end.
- [ ] **Code Review Passed** - I have RUN the `code-reviewer` agent over all staged changes. Issues rated **high risk or above** have been fixed. All findings are listed in the "Review Findings" section below.

### CRITICAL: Linting Is Not Testing

**Passing lint/typecheck does NOT mean code works.** Static analysis only checks syntax and types - it does not:
- Verify imports resolve at runtime
- Verify the script can actually be executed
- Verify the logic produces correct results
- Catch runtime errors, path issues, or environment dependencies

**Before claiming something is "tested", you MUST actually run it.** If you haven't executed the code, you haven't tested it.

### Change Summary

For any items above that required changes, provide a summary organized by category:

**[codebase]** - Production code changes
**[documentation]** - Doc changes
**[test-modules]** - Test code changes
**[linters/config]** - Config changes

### Review Findings

Results from the `code-reviewer` agent, organized by disposition:

**[fixed]** - Findings rated high risk or above that were resolved before this checklist
**[deferred]** - Findings rated medium or below, presented here for your assessment

If no findings in either category, state "(none)".

**This checklist is ABSOLUTE and HIGH PRIORITY. Never skip it. Never abbreviate it.**

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
1. **Detect platform** — Run `git remote -v` and determine GitHub vs GitLab (see Platform Detection)
2. **Resolve identity** — Check Dev-Team, pick session Dev-Name/Dev-Avatar (see Agent Identity)
3. **Load context** — Check for and read `Docs/implementation-plan.md` (or similar planning documents) for current state and context. If no such file exists, proceed without it.

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
- `Dev-Name`: A single memorable name or short phrase (max 3 words). Draw from nerdcore canon — sci-fi, fantasy, comics, gaming, mythology, tech puns, wordplay. The wittier and more specific the reference, the better. Generic names are boring.
- `Dev-Avatar`: A Slack emoji string with colons (e.g., `:smiling_imp:`, `:space_invader:`). Should feel like it belongs with the name.

**On session start**, after resolving Dev-Team:
1. Pick your Dev-Name and Dev-Avatar
2. Persist them for the session in `/tmp/claude-agent-$PPID.json`:
   ```json
   {
     "dev_team": "<Dev-Team value>",
     "dev_name": "<your chosen name>",
     "dev_avatar": "<your chosen emoji>"
   }
   ```
3. Announce your identity to the user:
   > I'm going by **\<Dev-Name\>** \<Dev-Avatar\> from team `<Dev-Team>` this session.

### Reading Identity

Any skill or behavior that needs agent identity should:
1. Read `Dev-Team` from this file
2. Read `Dev-Name` and `Dev-Avatar` from `/tmp/claude-agent-$PPID.json`

Dev-Team:
