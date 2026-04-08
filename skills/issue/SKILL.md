---
name: issue
description: Create structured issues (feature, bug, chore, docs, epic) with proper templates and labels. Supports both GitHub (gh) and GitLab (glab). Self-contained — does not depend on CLAUDE.md for templates.
usage: |
  /issue feature <prompt>  Create a feature issue
  /issue bug <prompt>      Create a bug issue
  /issue chore <prompt>    Create a chore issue
  /issue docs <prompt>     Create a docs issue
  /issue epic <prompt>     Create an epic issue
  /issue <prompt>          Infer type from the prompt
  /issue                   Infer from recent conversation context
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-issue does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-issue
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Issue — Structured Issue Creation

Create properly templated and labeled issues from a natural language prompt.

## Usage

```
/issue feature <prompt>       Create a feature issue
/issue bug <prompt>            Create a bug issue
/issue chore <prompt>          Create a chore issue
/issue docs <prompt>           Create a docs issue
/issue epic <prompt>           Create an epic issue
/issue <prompt>                Infer type from the prompt
/issue                         Infer from recent conversation context
```

## Step 1: Detect Platform

```bash
REMOTE_URL=$(git remote get-url origin 2>/dev/null)
if echo "$REMOTE_URL" | grep -qi github; then
  PLATFORM="github"; CLI="gh"
elif echo "$REMOTE_URL" | grep -qi gitlab; then
  PLATFORM="gitlab"; CLI="glab"
fi
```

Or read from `.claude-project.md` if it exists.

## Step 2: Parse Arguments

{{#if args}}
Parse: `{{args}}`
{{else}}
No arguments — infer the issue from the most recent topic of conversation. Determine the type and content from context and create directly. State your interpretation in the report so the user can edit if the inference was wrong.
{{/if}}

Extract two things:
1. **Type** — the first word if it matches: `feature`, `bug`, `chore`, `docs`, `epic`. If it doesn't match a type, treat the entire argument as the prompt and infer the type.
2. **Prompt** — everything after the type (or the entire argument if no type prefix).

**Type inference rules** (when no explicit type):
- Mentions broken, fails, crash, error, wrong → `bug`
- Mentions add, create, build, implement, new → `feature`
- Mentions update, fix, clean, refactor, rename, move, upgrade → `chore`
- Mentions document, write docs, README, guide → `docs`
- Mentions epic, phase, milestone, multi-part → `epic`
- Ambiguous → ask the user

## Step 3: Draft the Issue

Use the prompt (or conversation context) to fill in the appropriate template below. The agent should flesh out the template sections intelligently — don't just echo the prompt back. Think about what a spec-driven implementing agent would need.

**Quality standard:** Every issue should be detailed enough that a spec-driven agent can execute without making design decisions. Implementation steps should read like paint-by-numbers. Acceptance criteria should be evaluable before PR/MR merge.

### Feature Template

```markdown
## Summary

[1-2 sentences: what this feature delivers and why]

## Context

[Background, motivation, link to Epic or Dev Spec if applicable]

## Implementation Steps

[Paint-by-numbers instructions. Each step should be unambiguous.]

1. [Exact file paths to create or modify]
2. [Function signatures and key logic]
3. [Data structures and schemas]
4. [How to wire components together]

## Test Procedures

### Unit Tests

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_function_name` | [what it verifies] | `tests/test_module.py` |

### Integration/E2E Coverage

- [References to integration tests if applicable]

## Acceptance Criteria

- [ ] [Testable condition — names exact files, functions, commands, or behaviors]
- [ ] [Testable condition]
- [ ] [Testable condition]

## Dependencies

- None (or #NNN — description)
```

### Bug Template

```markdown
## Summary

[Concise description of the defect]

## Environment

- **Where observed:** [page, component, CLI command, API endpoint]
- **Version/commit:** [git SHA or release tag]
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

- [Links to logs, screenshots, error traces]

## Workaround

[Describe workaround if known, or "None known"]
```

### Chore Template

```markdown
## Summary

[Description of the maintenance task and its rationale]

## Implementation Steps

[Mandatory if the chore touches >1 file or has ordering constraints.]

1. [Step]
2. [Step]

## Acceptance Criteria

- [ ] [Testable condition]
- [ ] [Testable condition]
```

### Docs Template

```markdown
## Summary

[Which document(s) to create or update, and why]

## Target Audience

[Who will read this — developers, operators, end users, agents]

## What's Missing, Outdated, or Incorrect

[Specific gaps or inaccuracies]

## Source Material

- [Pointers to code, PRDs, conversations]

## Acceptance Criteria

- [ ] Content is accurate against current codebase
- [ ] Coverage is complete for the stated scope
- [ ] No broken links
- [ ] [Additional testable conditions]
```

### Epic Template

```markdown
## Goal

[One sentence: what this epic proves or delivers]

## Scope

**In scope:**
- [What is included]

**Out of scope:**
- [What is explicitly excluded and why]

## Definition of Done

- [ ] [Verifiable condition]
- [ ] [Verifiable condition]
- [ ] All sub-issue AC checklists are satisfied

## Sub-Issues

| Order | Issue | Title | Dependencies |
|-------|-------|-------|-------------|
| 1 | #NNN | [title] | None |
| 2 | #NNN | [title] | #NNN |

## Wave Map

| Wave | Issues | Parallel? |
|------|--------|-----------|
| 1 | #NNN | Single |
| 2 | #NNN, #NNN | Yes |

## Success Metrics

[Quantitative or qualitative measures of success]
```

## Step 4: Determine Labels

Labels use the `group::value` convention. Within each group, labels are mutually exclusive.

### Automatic Labels (always applied)

| Type | Label |
|------|-------|
| feature | `type::feature` |
| bug | `type::bug` |
| chore | `type::chore` |
| docs | `type::docs` |
| epic | `type::epic` |

### Inferred Labels

Assess and apply values for these groups using judgment. Do not pause to confirm — proceed directly to creation:

| Group | Values | When Required |
|-------|--------|---------------|
| **Priority** | `priority::critical`, `priority::high`, `priority::medium`, `priority::low` | All issues |
| **Urgency** | `urgency::immediate`, `urgency::soon`, `urgency::normal`, `urgency::eventual` | All issues |
| **Size** | `size::S`, `size::M`, `size::L`, `size::XL` | Features, chores, docs (optional on bugs, omit for epics) |
| **Severity** | `severity::critical`, `severity::major`, `severity::minor`, `severity::cosmetic` | Bugs only |
| **Wave** | `wave::1`, `wave::2`, etc. | Wave-planned issues only — omit otherwise |

**Priority vs Urgency are orthogonal:**
- **Priority** = business value importance. How much does this matter?
- **Urgency** = temporal significance. How soon must it be addressed?

Assess labels based on the content — do not ask the user to confirm each one. Use your judgment.

## Step 5: Create the Issue

Create immediately — do not ask for approval. Issues are cheap to edit and close. The user gave intent when they invoked `/issue`; the real review happens in the project board where the editing tools are better.

Write the issue body to a temp file first, then create:

**GitHub:**
```bash
# Write body to temp file (avoids shell escaping issues with multi-line markdown)
cat > /tmp/issue-body.md << 'BODY'
<the filled-in template>
BODY

gh issue create --title "<title>" --label "<comma-separated-labels>" --body-file /tmp/issue-body.md
```

**GitLab:**
```bash
glab issue create --title "<title>" --label "<comma-separated-labels>" --description "$(cat /tmp/issue-body.md)"
```

If a label doesn't exist on the repo, offer to create it:

**GitHub:**
```bash
gh label create "type::feature" --description "Feature request" --color "0E8A16"
```

**GitLab:**
```bash
glab label create "type::feature" --description "Feature request" --color "#0E8A16"
```

## Step 6: Report

Confirm creation with the issue number, URL, and a nudge to review:

> Created **#NNN** — `type(scope): description`
> Labels: `type::feature`, `priority::medium`, `urgency::normal`, `size::M`
> Review and edit: `<issue URL>`

When creating multiple issues in a batch (e.g., epic decomposition), report all of them at the end in a table rather than one at a time:

> | # | Title | Labels |
> |---|-------|--------|
> | #10 | feat(auth): OAuth2 login | type::feature, priority::high, size::M |
> | #11 | feat(auth): session management | type::feature, priority::high, size::M |
>
> Review in your project board: `<project URL>`

## Label Color Reference

When creating labels, use these colors for consistency. **Note:** `gh` expects hex without `#` prefix; `glab` expects it with `#`.

| Group | Color (glab) | Color (gh) |
|-------|-------------|------------|
| `type::` | `#0E8A16` | `0E8A16` |
| `priority::` | `#D93F0B` | `D93F0B` |
| `urgency::` | `#FBCA04` | `FBCA04` |
| `size::` | `#1D76DB` | `1D76DB` |
| `severity::` | `#B60205` | `B60205` |
| `wave::` | `#5319E7` | `5319E7` |
