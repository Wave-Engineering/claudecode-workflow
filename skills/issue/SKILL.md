---
name: issue
description: Create structured issues (plan, epic, feature, story, bug, chore, doc) with templates and labels. GitHub and GitLab. Wave-pattern-ready on first try.
usage: |
  /issue plan <prompt>     Create a Plan tracking issue (canonical §5.1.2 body)
  /issue epic <prompt>     Create an Epic parent tracker (PM-layer)
  /issue feature <prompt>  Create a feature Story (alias: story)
  /issue story <prompt>    Create a story Story (alias: feature)
  /issue bug <prompt>      Create a bug Story
  /issue chore <prompt>    Create a chore Story
  /issue doc <prompt>     Create a doc Story
  /issue <type> <prompt> --epic N  Attach epic::N PM-layer label to the Story
  /issue <prompt>          Infer type from the prompt (never infers "plan")
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
/issue plan <prompt>              Create a Plan tracking issue (canonical §5.1.2 body)
/issue epic <prompt>              Create an Epic parent tracker (PM-layer)
/issue feature <prompt>           Create a feature Story (alias: story)
/issue story <prompt>             Create a story Story (alias: feature)
/issue bug <prompt>               Create a bug Story
/issue chore <prompt>             Create a chore Story
/issue doc <prompt>               Create a doc Story
/issue <type> <prompt> --epic N   Attach epic::N PM-layer label to the Story
/issue <prompt>                   Infer type from the prompt (never infers "plan")
/issue                            Infer from recent conversation context
```

## Taxonomy Overview

The `/issue` skill creates three distinct layers of issue, each with its own
template and label family (authoritative source: `docs/phase-epic-taxonomy-devspec.md`
§5.5, cross-ref `docs/kahuna-devspec.md` Terminology section):

| Layer | Type | Label | Role |
|-------|------|-------|------|
| **Plan** | `plan` | `type::plan` | Top-level wave-pipeline tracking issue. Has a canonical frozen body; runtime state lives in comments. One Plan per `/devspec` walk. |
| **Epic** | `epic` | `type::epic` | **PM-layer concept only.** A parent thematic tracker for human project management. The pipeline ignores `type::epic` and `epic::N` labels entirely (per Dev Spec R-03). |
| **Story** | `feature`, `story`, `bug`, `chore`, `doc` | `type::<sub>` | The unit of implementable work — one issue, one branch, one PR/MR, one Flight. Optionally carries an `epic::N` label applied via `--epic N` on creation. |

**Load-bearing distinction:** a Plan is not an Epic. A Plan is a pipeline
artifact the Orchestrator reads; an Epic is a PM-layer grouping the pipeline
never reads. If you find pipeline code inspecting `type::epic` or `epic::N`,
it's a taxonomy leak (Dev Spec R-19). The two types share label colour
`5319E7` because they sit in the same visual family on the project board,
not because they share any pipeline semantics.

## Wave-Pattern-Ready Output Guarantee

The sub-issue templates emitted by this skill (`feature`, `story`, `chore`,
`doc`, `bug`) include the six H2 sections required for downstream wave
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

The `plan` and `epic` templates are intentionally different:

- **Plan** uses the canonical frozen-body template from Dev Spec §5.1.2
  (Goal / Scope / Plan-level DoD / Phases / References). It's not validated
  against the sub-issue grammar; it's the Orchestrator's worldview.
- **Epic** is a PM-layer parent tracker; its body carries Goal / Scope /
  sub-issue checklist for human reference. The pipeline ignores epics.

See `docs/issue-body-grammar.md` in `mcp-server-sdlc` for the authoritative
parser specification (sub-issue grammar), and `docs/plan-issue-template.md`
in this repo for the operator reference on Plan issues.

## Tools Used

- `mcp__sdlc-server__work_item` — create issues cross-platform (handles GitHub/GitLab detection internally)
- `mcp__sdlc-server__label_create` — on-demand label creation for `type::plan` and `epic::N` when the target repo doesn't yet carry them (Dev Spec R-14)
- `mcp__sdlc-server__label_list` — optional pre-check that a label exists before `work_item`; the recommended pattern is to call `label_create` unconditionally and rely on its idempotent behaviour, but `label_list` is available if you need to inspect
- `mcp__sdlc-server__work_item` (read path) — pre-check that `--epic N` references an existing open issue with `type::epic` label before creating the Story (Dev Spec §5.5.4 step 1)

## Step 1: Parse Arguments

{{#if args}}
Parse: `{{args}}`
{{else}}
No arguments — infer the issue from the most recent topic of conversation. Determine the type and content from context and create directly. State your interpretation in the report so the user can edit if the inference was wrong. Never infer `plan` — Plan creation is always intentional; if the conversation implies a Plan, ask explicitly.
{{/if}}

Extract three things:

1. **Type** — the first word if it matches one of:
   `plan`, `epic`, `feature`, `story`, `bug`, `chore`, `doc`.
   `feature` and `story` are aliases and use the same sub-issue template.
   If it doesn't match a type, treat the entire argument (minus flags) as the
   prompt and infer the type from keywords (see table below).
2. **`--epic N` flag** — optional flag anywhere after the type. When present
   on a Story-type invocation (`feature`/`story`/`bug`/`chore`/`doc`),
   captures the integer `N`. Invalid on `plan` and `epic` invocations — if
   `--epic` appears with type=`plan` or type=`epic`, fail with a clear error.
3. **Prompt** — everything after the type (or the entire argument if no type
   prefix), with the `--epic N` token removed if present.

**Type inference rules** (when no explicit type — never infers `plan`):

- Mentions broken, fails, crash, error, wrong → `bug`
- Mentions add, create, build, implement, new → `feature`
- Mentions story, user story, sub-issue under epic → `story`
- Mentions update, fix, clean, refactor, rename, move, upgrade → `chore`
- Mentions document, write doc, README, guide → `doc`
- Mentions epic, phase, milestone, multi-part, thematic parent → `epic`
- Mentions plan, dev spec, kahuna, wave pipeline → **ask explicitly**; do not
  infer `plan`. Creating a Plan tracking issue is intentional (Dev Spec §5.5.6).
- Ambiguous → ask the user

## Step 2: Draft the Issue

Use the prompt (or conversation context) to fill in the appropriate template below. The agent should flesh out the template sections intelligently — don't just echo the prompt back. Think about what a spec-driven implementing agent would need.

**Quality standard:** Every issue should be detailed enough that a spec-driven agent can execute without making design decisions. Implementation steps should read like paint-by-numbers. Acceptance criteria should be evaluable before PR/MR merge.

### Plan Template

**Authoritative source:** Dev Spec §5.1.2 (`docs/phase-epic-taxonomy-devspec.md`).
Operator reference: `docs/plan-issue-template.md`.

When `/issue plan <prompt>` is invoked:

1. **Parse the prompt** into Plan metadata. Extract (via the same LLM reasoning
   used for type inference):
   - A one-sentence Goal.
   - A suggested slug (kebab-case) from the Goal — used as a reminder only;
     the kahuna branch name is chosen later by `/devspec`.
   - Initial In-scope / Out-of-scope bullets as placeholders the Pair fills
     during `/devspec create`.
2. **Render the canonical body** verbatim using the template below. Every
   heading is frozen content per §5.1.6 mutation rule 1; the body is hand-
   edited during `/devspec create` and frozen at `/devspec approve`.
   Post-creation, runtime state flows through comments (never the body) —
   see `docs/plan-issue-template.md` for the comment typed-prefix table.
3. **Title** is `Plan: <short name derived from prompt>`, matching the body's
   `# Plan: <Name>` heading. If the inferred name is wrong, the Pair edits
   the issue directly — cheaper than a re-invocation.
4. **Post NO comments at creation.** Empty comment log is the correct initial
   state (Dev Spec §5.1.6 rule 1). The Decision Ledger starts empty; entries
   append during `/devspec create` and runtime.

```markdown
# Plan: <Name>

<!-- PLAN-ISSUE v1 — frozen content only. Runtime state lives in comments. -->

## Goal
<one sentence describing what this Plan delivers>

## Scope
### In scope
- <bullet>
### Out of scope
- <bullet>

## Plan-level Definition of Done
- [ ] Phase 1 DoD satisfied
- [ ] Phase 2 DoD satisfied
- [ ] (... one line per Phase)
- [ ] Kahuna→main MR merged clean
- [ ] VRTM complete
- [ ] (... cross-cutting conditions)

## Phases

### Phase 1 — <Phase Name>
**DoD:**
- [ ] <verifiable condition> [R-XX]
- [ ] <verifiable condition>

### Phase 2 — <Phase Name>
**DoD:**
- [ ] <verifiable condition>

### (... one section per Phase)

## References
- Dev Spec: `docs/<slug>-devspec.md`
- Memory files: `decision_<topic>.md`, `principle_<topic>.md`
- Related Plans: #NNN (if any)
```

### Wave-Pattern Sub-Issue Templates

The five templates below (`feature`, `story`, `chore`, `doc`, `bug`) all
emit the same six required H2 sections so they are recognized by
`spec_validate_structure` and ready for `/prepwaves`. The body inside each
section is tailored to the issue type. **Always emit all six headings**, even
when a section is `None` or `N/A` — the parser only sees H2s.

### Feature Template (alias: Story)

```markdown
## Summary

[1-2 sentences: what this feature delivers and why. Include Context — background,
motivation, link to Plan or Dev Spec if applicable — as a short sub-paragraph
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
**Plan:** [#NNN or N/A]
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
**Plan:** [#NNN or N/A]
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
**Plan:** [#NNN or N/A]
```

### Epic Template (PM-layer only)

The `epic` type creates a `type::epic` parent tracker for **project-management
thematic grouping**. It is a PM-layer concept: the wave-pipeline (Orchestrator,
`/wavemachine`, `/nextwave`, `/prepwaves`) reads neither `type::epic` issues
nor `epic::N` labels (Dev Spec R-03, R-19). Use `epic` when a human PM wants
to group Stories thematically across multiple Plans or across none at all.
**Do not confuse with `plan`** — Plans are pipeline artifacts, Epics are not.

```markdown
## Goal

[One sentence: what this epic proves or delivers (PM-thematic, not pipeline)]

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

## Success Metrics

[Quantitative or qualitative measures of success]
```

Epic issues created by this skill do NOT receive a `Wave Map` section; wave
planning belongs to the Plan's `/devspec` → `/prepwaves` pipeline, not to the
PM-layer Epic. If human users want a thematic grouping with a wave map, they
can add one by hand after creation.

## Step 3: Determine Labels

Labels use the `group::value` convention. Within each group, labels are mutually exclusive.

### Automatic Labels (always applied)

| Type | Label |
|------|-------|
| plan | `type::plan` |
| epic | `type::epic` |
| feature | `type::feature` |
| story | `type::story` |
| bug | `type::bug` |
| chore | `type::chore` |
| doc | `type::docs` (the canonical GitHub label is plural; the `/issue` user-facing alias `doc` is singular per CLAUDE.md branch-prefix convention) |

### `--epic N` Flag — Optional PM-Layer Label (Dev Spec §5.5.4)

When a Story-type invocation (`feature`, `story`, `bug`, `chore`, `doc`)
includes `--epic N`:

1. **Pre-check `N` exists and is an Epic.** Call `work_item` (read path) to
   fetch issue `#N` on the target repo. Assert it is open and carries the
   `type::epic` label. If the issue doesn't exist, is closed, or lacks
   `type::epic`, fail with a clear error message directing the Pair to first
   create the Epic via `/issue epic <prompt>`. Do not create the Story.
2. **Attach both labels** to the Story being created: `type::<subtype>` AND
   `epic::N`.
3. **On-demand label creation** for the `epic::N` label family — see
   "On-demand label creation" below.
4. **No comment is posted on the Epic issue.** The parent-child relationship
   is represented by the `epic::N` label alone (Dev Spec §5.5.4 step 4).
   The wave pipeline ignores both `type::epic` and `epic::N`; PMs who care
   can filter the Epic's project board by its label.

**`--epic N` is invalid with type=`plan` or type=`epic`.** A Plan is not an
Epic sub-issue; an Epic is not attached to another Epic. If `--epic` appears
on either of those invocations, fail before any create calls.

### On-demand Label Creation (Dev Spec R-14 / §5.5.3 step 2)

Two label families are created on-demand when absent from the target repo:

| Label | Colour | Description | Created by |
|-------|--------|-------------|------------|
| `type::plan` | `5319E7` | `"Plan tracking issue — top-level pipeline container"` | `/issue plan` invocations |
| `epic::<N>` | `5319E7` | `"Story belongs to Epic #N (PM-layer thematic grouping)"` (substitute `<N>`) | `/issue <story> --epic N` invocations |

Both share colour `5319E7` with `type::epic` — they sit in the same visual
family on the project board. This does NOT mean the pipeline treats them
alike; the colour is cosmetic, the semantics are different.

**Procedure (applied before `work_item` creates the issue):**

1. Call `mcp__sdlc-server__label_create` for the required label with its
   canonical colour and description. The tool is idempotent — creating an
   already-existing label succeeds silently. There is no need to pre-check
   via `label_list`; the recommended pattern is unconditional `label_create`.
2. If `label_create` fails for any reason OTHER than "already exists"
   (e.g. permissions, platform outage), surface the error to the Pair and
   abort the issue creation. Do not proceed to `work_item`.
3. Once the label exists, proceed to `work_item` with both the type label
   and (if applicable) the `epic::N` label in the label list.

**Rationale for unconditional `label_create`.** It's one call either way;
the pre-check-then-create pattern is two calls and is no safer. The tool's
idempotent contract lets us skip the branch.

### Inferred Labels

Assess and apply values for these groups using judgment. Do not pause to confirm — proceed directly to creation:

| Group | Values | When Required |
|-------|--------|---------------|
| **Priority** | `priority::critical`, `priority::high`, `priority::medium`, `priority::low` | All issues |
| **Urgency** | `urgency::immediate`, `urgency::soon`, `urgency::normal`, `urgency::eventual` | All issues |
| **Size** | `size::S`, `size::M`, `size::L`, `size::XL` | Features, chores, doc (optional on bugs, omit for plans and epics) |
| **Severity** | `severity::critical`, `severity::major`, `severity::minor`, `severity::cosmetic` | Bugs only |
| **Wave** | `wave::1`, `wave::2`, etc. | Wave-planned Stories only — omit otherwise. Never applied to plan or epic types. |

**Plan defaults.** A Plan typically gets `priority::medium`, `urgency::normal`,
and no `size::` label (Plans are not sized — they decompose into Phases which
decompose into Stories). The Pair can override after creation.

**Priority vs Urgency are orthogonal:**
- **Priority** = business value importance. How much does this matter?
- **Urgency** = temporal significance. How soon must it be addressed?

Assess labels based on the content — do not ask the user to confirm each one. Use your judgment.

## Step 4: Create the Issue

Create immediately — do not ask for approval. Issues are cheap to edit and close. The user gave intent when they invoked `/issue`; the real review happens in the project board where the editing tools are better.

**Order of operations (all invocations):**

1. If the invocation is `/issue plan ...`, call `label_create` for `type::plan`
   (idempotent, see Step 3 "On-demand label creation").
2. If the invocation carries `--epic N`:
   a. Call `work_item` (read path) on `#N` and verify it exists, is open,
      and carries `type::epic`. Abort on failure.
   b. Call `label_create` for `epic::N` (idempotent).
3. Call `mcp__sdlc-server__work_item` with the drafted title, body, and the
   full label list (type label + `epic::N` if applicable + inferred labels).
   The tool handles platform detection and issue creation internally — no
   `gh` or `glab` CLI calls. **Type alias mapping:** when the user-facing
   invocation is `doc`, pass `docs` to `work_item` (the tool's `type` enum
   uses `docs` plural to match the canonical `type::docs` label; the `/issue`
   skill exposes singular `doc` to align with the singular branch prefix per
   CLAUDE.md). Same pattern as `story` ↔ `feature`. `plan` needs no aliasing —
   pass it through unchanged (see the callout below).

If `work_item` reports a missing label at create-time (race or pre-existing
`epic::X` for a different `X`), surface the error; do not silently retry.

> ### Plans: pass `type: "plan"` directly
>
> `/issue plan` passes `type: "plan"` to `work_item`, which applies the `type::plan` label itself.
> Requires **sdlc-server ≥ v2.1.0** (`plan` added to the `type` enum in `mcp-server-sdlc#479`).
>
> **Never** substitute `type: "epic"` for a Plan. `work_item` applies an automatic `type::<type>`
> label, so an `epic` call produces a Plan carrying `type::epic`. On **GitLab** that is invisible —
> `type::epic` and `type::plan` share the `type::` scope key and GitLab's scoped labels are mutually
> exclusive, so a later `type::plan` evicts it. On **GitHub** there are no scoped labels, and the
> Plan ends up carrying **both**, which is precisely the taxonomy leak the Taxonomy Overview forbids
> (Dev Spec R-19). The substitution was only ever safe by accident on one platform.
>
> Step 4's `label_create` precondition still stands: `work_item` *applies* `type::plan` but does not
> create it, and GitHub fails a `--label` for a label that doesn't exist yet.

## Batch Creation (N > 1 issues in one pass)

When a calling agent (e.g. `/devspec`, `/prepwaves`) needs to create multiple
issues in a single pass, spawn them as **parallel sub-agents** rather than
looping serially. This keeps the issue-drafting work out of the main context
window and collapses wall-clock time to the slowest single issue.

**When to use:** any time the caller has ≥ 2 issues to create in the same
invocation and the issues have no creation-time dependencies on each other
(i.e. no issue needs the number of another issue before it can be created).

**When NOT to use:** if issue B needs the number of issue A to embed in its
body (e.g. a Plan issue that references sub-issues by number). Create A first,
then batch the rest.

**Sub-agent template** (one per issue, all launched in a single message):

```
subagent_type: general-purpose
model: sonnet
prompt: "Create a <type> issue in repo <owner/repo> using the /issue skill.

Type: <feature|bug|chore|doc|story|plan|epic>
Repo: <owner/repo>
Epic flag: <--epic N, or omit>

Intent:
<Full description of what this issue should cover. Be specific enough that
the sub-agent can fill out all six required H2 sections (Summary, Implementation
Steps, Test Procedures, Acceptance Criteria, Dependencies, Metadata) without
making design decisions. This is the same quality bar as a human /issue prompt.>

Label hints (override sub-agent judgment if supplied):
- priority: <critical|high|medium|low, or omit to let sub-agent infer>
- urgency: <immediate|soon|normal|eventual, or omit>
- size: <S|M|L|XL, or omit>
- wave: <N, or omit>

Return: issue number and URL only. No other output."
```

**Model:** `sonnet` — issue body quality is load-bearing (Flight Agents execute
directly from it). Do not downgrade to Haiku.

**Collecting results:** each sub-agent returns `{number, url}`. Assemble these
into the batch report table in Step 5. If any sub-agent fails, report the
failure inline in the table row rather than aborting the whole batch.

## Step 5: Report

Confirm creation with the issue number, URL, and a nudge to review:

> Created **#NNN** — `type(scope): description`
> Labels: `type::feature`, `priority::medium`, `urgency::normal`, `size::M`
> Review and edit: `<issue URL>`

For a Plan invocation:

> Created Plan **#NNN** — `Plan: <Name>`
> Labels: `type::plan`, `priority::medium`, `urgency::normal`
> Body: canonical §5.1.2 template (Goal / Scope / DoD / Phases / References)
> Comments: none (correct initial state per Dev Spec §5.1.6 rule 1)
> Next: run `/devspec create <N>` to begin the Dev Spec walk.
> Review and edit: `<issue URL>`

For a Story invocation with `--epic N`:

> Created **#NNN** — `feat(scope): description`
> Labels: `type::feature`, `epic::42`, `priority::medium`, `urgency::normal`, `size::M`
> Epic: #42 (PM-layer thematic grouping; pipeline ignores)
> Review and edit: `<issue URL>`

When creating multiple issues in a batch (e.g., Plan decomposition from a
devspec walk), report all of them at the end in a table rather than one at a
time:

> | # | Title | Labels |
> |---|-------|--------|
> | #10 | feat(auth): OAuth2 login | type::feature, priority::high, size::M |
> | #11 | feat(auth): session management | type::feature, priority::high, size::M |
>
> Review in your project board: `<project URL>`

## Label Colour Reference

When creating labels, use these colours for consistency.

> **Pass a bare 6-char hex. No `#`.** `mcp__sdlc-server__label_create` validates `color` against
> `^[0-9a-fA-F]{6}$` and **rejects the `#`-prefixed form outright**. The tool handles any
> platform-specific translation internally — callers never pass `#`.

| Group | Colour |
|-------|--------|
| `type::plan` | `5319E7` |
| `type::epic` | `5319E7` |
| `type::<story-subtype>` | `0E8A16` |
| `priority::` | `D93F0B` |
| `urgency::` | `FBCA04` |
| `size::` | `1D76DB` |
| `severity::` | `B60205` |
| `wave::` | `5319E7` |
| `epic::<N>` | `5319E7` |
