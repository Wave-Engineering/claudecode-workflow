---
name: issue
description: Create structured issues (feature, story, bug, chore, docs, epic) with proper templates and labels. Supports both GitHub (gh) and GitLab (glab). Self-contained — does not depend on CLAUDE.md for templates. Sub-issue templates (feature, story, chore, docs, bug) emit the H2 sections that `/prepwaves` and `spec_validate_structure` require, so issues are wave-pattern-ready on first try.
usage: |
  /issue feature <prompt>  Create a feature issue (alias: story)
  /issue story <prompt>    Create a story issue (alias: feature)
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
/issue feature <prompt>       Create a feature issue (alias: story)
/issue story <prompt>          Create a story issue (alias: feature)
/issue bug <prompt>            Create a bug issue
/issue chore <prompt>          Create a chore issue
/issue docs <prompt>           Create a docs issue
/issue epic <prompt>           Create an epic issue
/issue <prompt>                Infer type from the prompt
/issue                         Infer from recent conversation context
```

## Wave-Pattern-Ready Output Guarantee

The sub-issue templates emitted by this skill (`feature`, `story`, `chore`,
`docs`, `bug`) include the six H2 sections required for downstream wave
execution:

- `## Summary`
- `## Implementation Steps` (alias accepted by parser: `## Changes`)
- `## Test Procedures` (alias accepted by parser: `## Tests`)
- `## Acceptance Criteria`
- `## Dependencies`
- `## Metadata`

This means an issue created via `/issue` passes
`mcp__sdlc-server__spec_validate_structure` on first try and is ready to be
picked up by `/prepwaves` without mid-flight body fixes. If a particular
section does not apply to a given issue, emit the heading with a single-line
rationale (e.g. `None` or `N/A — because ...`); never omit the heading.

The `epic` template is intentionally different — epics are parent issues
that decompose into sub-issues, so they are not validated against the
sub-issue grammar.

See `docs/issue-body-grammar.md` in `mcp-server-sdlc` for the authoritative
parser specification.

## Tools Used
- `mcp__sdlc-server__work_item` — create issues cross-platform (handles GitHub/GitLab detection internally)

## Step 1: Parse Arguments

{{#if args}}
Parse: `{{args}}`
{{else}}
No arguments — infer the issue from the most recent topic of conversation. Determine the type and content from context and create directly. State your interpretation in the report so the user can edit if the inference was wrong.
{{/if}}

Extract two things:
1. **Type** — the first word if it matches: `feature`, `story`, `bug`, `chore`, `docs`, `epic`. `feature` and `story` are aliases and use the same template. If it doesn't match a type, treat the entire argument as the prompt and infer the type.
2. **Prompt** — everything after the type (or the entire argument if no type prefix).

**Type inference rules** (when no explicit type):
- Mentions broken, fails, crash, error, wrong → `bug`
- Mentions add, create, build, implement, new → `feature`
- Mentions story, user story, sub-issue under epic → `story`
- Mentions update, fix, clean, refactor, rename, move, upgrade → `chore`
- Mentions document, write docs, README, guide → `docs`
- Mentions epic, phase, milestone, multi-part → `epic`
- Ambiguous → ask the user

## Step 2: Draft the Issue

Use the prompt (or conversation context) to fill in the appropriate template below. The agent should flesh out the template sections intelligently — don't just echo the prompt back. Think about what a spec-driven implementing agent would need.

**Quality standard:** Every issue should be detailed enough that a spec-driven agent can execute without making design decisions. Implementation steps should read like paint-by-numbers. Acceptance criteria should be evaluable before PR/MR merge.

### Wave-Pattern Sub-Issue Templates

The five templates below (`feature`, `story`, `chore`, `docs`, `bug`) all
emit the same six required H2 sections so they are recognized by
`spec_validate_structure` and ready for `/prepwaves`. The body inside each
section is tailored to the issue type. **Always emit all six headings**, even
when a section is `None` or `N/A` — the parser only sees H2s.

### Feature Template (alias: Story)

```markdown
## Summary

[1-2 sentences: what this feature delivers and why. Include Context — background,
motivation, link to Epic or Dev Spec if applicable — as a short sub-paragraph
under the Summary heading rather than a separate H2, so the parser sees the
canonical Summary section.]

## Implementation Steps

[Paint-by-numbers instructions. Each step should be unambiguous.]

1. [Exact file paths to create or modify]
2. [Function signatures and key logic]
3. [Data structures and schemas]
4. [How to wire components together]

## Test Procedures

*Unit tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_function_name` | [what it verifies] | `tests/test_module.py` |

*Integration coverage:*

- [IT-## or test reference, or `None` if not applicable]

## Acceptance Criteria

- [ ] [Testable condition — names exact files, functions, commands, or behaviors]
- [ ] [Testable condition]
- [ ] [Testable condition]

## Dependencies

- None
- [or `[#NNN](url) — description` per dependency]

## Metadata

**Wave:** [N or N/A]
**Parent Epic:** [#NNN or N/A]
**Wave Master:** [#NNN or N/A]
```

### Story Template

The Story template is identical to the Feature template — `story` and
`feature` are aliases. The underlying `mcp__sdlc-server__work_item` tool's
`type` enum uses `story`; the `/issue` skill exposes both names so callers
can use whichever matches their mental model.

### Bug Template

```markdown
## Summary

[Concise description of the defect.]

**Environment:** [page, component, CLI command, API endpoint]
**Version/commit:** [git SHA or release tag]
**Frequency:** intermittent | consistent

**Steps to reproduce:**

1. [Step one]
2. [Step two]
3. [Step three]

**Expected:** [What should happen]
**Actual:** [What actually happens]

## Implementation Steps

[Paint-by-numbers fix steps. If root cause is unknown, state the diagnostic
plan first, then the fix steps to be filled in once root cause is confirmed.]

1. [Locate offending code at exact path]
2. [Describe the change]
3. [Update or add the regression test]

## Test Procedures

*Regression test:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_<bug_name>_regression` | reproduces the original failure and proves the fix | `tests/test_module.py` |

*Manual verification:* [steps to manually confirm the fix in the affected
environment, or `N/A`]

## Acceptance Criteria

- [ ] Regression test added and passing
- [ ] Original repro steps produce expected behavior
- [ ] No related regressions introduced
- [ ] [Additional testable conditions]

## Dependencies

- None
- [or `[#NNN](url) — description` per dependency]

## Metadata

**Severity:** [`severity::critical` | `severity::major` | `severity::minor` | `severity::cosmetic`]
**Wave:** [N or N/A]
**Artifacts:** [links to logs, screenshots, error traces, or `None`]
**Workaround:** [describe if known, or `None known`]
```

### Chore Template

```markdown
## Summary

[Description of the maintenance task and its rationale.]

## Implementation Steps

[Mandatory if the chore touches >1 file or has ordering constraints.]

1. [Step]
2. [Step]

## Test Procedures

*Verification:*

- [Command to run after the chore completes, or specific test file to confirm green]
- [`N/A — chore is doc-only / config-only` if no executable verification applies]

## Acceptance Criteria

- [ ] [Testable condition]
- [ ] [Testable condition]

## Dependencies

- None
- [or `[#NNN](url) — description` per dependency]

## Metadata

**Wave:** [N or N/A]
**Parent Epic:** [#NNN or N/A]
```

### Docs Template

```markdown
## Summary

[Which document(s) to create or update, and why.]

**Target audience:** [developers, operators, end users, agents]
**What's missing, outdated, or incorrect:** [specific gaps or inaccuracies]
**Source material:** [pointers to code, PRDs, conversations]

## Implementation Steps

1. [File path to create or update]
2. [Outline of sections to add or revise]
3. [Cross-references to update elsewhere]

## Test Procedures

*Verification:*

- [ ] Markdown lint passes (if a linter is configured)
- [ ] All links resolve (manual or scripted check)
- [ ] Code samples, if any, run as written against current `main`
- [`N/A` for any item that does not apply]

## Acceptance Criteria

- [ ] Content is accurate against current codebase
- [ ] Coverage is complete for the stated scope
- [ ] No broken links
- [ ] [Additional testable conditions]

## Dependencies

- None
- [or `[#NNN](url) — description` per dependency]

## Metadata

**Wave:** [N or N/A]
**Parent Epic:** [#NNN or N/A]
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

## Step 3: Determine Labels

Labels use the `group::value` convention. Within each group, labels are mutually exclusive.

### Automatic Labels (always applied)

| Type | Label |
|------|-------|
| feature | `type::feature` |
| story | `type::story` |
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

## Step 4: Create the Issue

Create immediately — do not ask for approval. Issues are cheap to edit and close. The user gave intent when they invoked `/issue`; the real review happens in the project board where the editing tools are better.

Call `work_item` with the drafted title, body, and labels. The tool handles platform detection and issue creation internally — no `gh` or `glab` CLI calls.

If a label doesn't exist on the repo, the tool or platform will report it. Offer to create missing labels via CLI as a one-time setup step (label CRUD MCP tool is planned but not yet available).

## Step 5: Report

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
