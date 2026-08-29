---
name: devspec
description: Create a Development Specification — deliverables manifest, finalization, approval, backlog population
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-devspec does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-devspec
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Development Specification Creation Workflow

This skill provides a structured, interactive workflow for creating Development Specifications. It walks each Dev Spec section collaboratively, manages the Deliverables Manifest, and runs a mechanical finalization checklist.

## Pipeline Taxonomy (authoritative — locked 2026-04-26)

The wave-pattern pipeline is built from four primitives. This skill teaches them explicitly so every Pair walking a Dev Spec shares the same vocabulary (per `docs/phase-epic-taxonomy-devspec.md` R-02..R-04, R-12):

| Primitive | Platform shape | Role |
|-----------|----------------|------|
| **Plan** | GitHub/GitLab issue with `type::plan` label | The top-level container. One issue per Plan; its number is the `plan_id`. Its body holds frozen scope (Goal / Scope / DoD / Phases checklist); its comments hold the Decision Ledger and lifecycle events. `/devspec create` anchors its walk on the Plan issue. |
| **Phase** | Internal to `phases-waves.json` — NO platform issue | A sequential ordering unit within a Plan. Phases partition the Dev Spec's §8 Implementation Plan. They exist only in `phases-waves.json`; they are not issues, not labels. |
| **Wave** | Internal to `phases-waves.json` — NO platform issue | A concurrency unit within a Phase. Stories in the same Wave are parallelizable (by dependency); Waves within a Phase run in order. |
| **Story** | GitHub/GitLab issue with `type::feature` / `type::bug` / `type::chore` / `type::doc` | The smallest execution unit. One issue per Story. Every Story declares its `depends_on` in `phases-waves.json`. |

**Epic is NOT a pipeline primitive.** Epic is an **optional PM-layer label** (`type::epic` on a parent tracker issue; `epic::N` label on child Stories) that a Pair may use to group Stories thematically for program-management rollups. The pipeline (`/prepwaves`, `/nextwave`, `/wavemachine`) does not read `type::epic` or `epic::N`; they read `phases-waves.json`. Treating "Epic" as a pipeline container is the old vocabulary and is explicitly retired.

The rest of this skill body uses Plan / Phase / Wave / Story throughout. When "Epic" appears, it is always qualified as the PM-layer label.

## Platform Detection

Before proceeding, detect the platform:
1. Check `.claude-project.md` for cached platform config
2. If not cached, run `git remote -v` and inspect the origin URL
3. GitHub → `gh` CLI, GitLab → `glab` CLI

## Commands

- **`/devspec create`** — Interactive Dev Spec generation (walk each section, build Deliverables Manifest, append Decision-Ledger comments to the Plan issue)
- **`/devspec finalize`** — Mechanical finalization checklist (verify Dev Spec completeness)
- **`/devspec approve`** — Approval gate (run finalization, present summary, record approval)
- **`/devspec upshift`** — Backlog population (create Story issues from approved Dev Spec, write `phases-waves.json` with `plan_id` + per-Story `depends_on`)

## Usage

```bash
# Create a new Dev Spec interactively
/devspec create

# Run the finalization checklist on an existing Dev Spec
/devspec finalize

# Approve a finalized Dev Spec (human gate)
/devspec approve

# Create backlog issues from an approved Dev Spec
/devspec upshift

# Show help
/devspec
```

---

{{#if (eq args "create")}}
  {{> devspec-create}}
{{else if (eq args "finalize")}}
  {{> devspec-finalize}}
{{else if (eq args "approve")}}
  {{> devspec-approve}}
{{else if (eq args "upshift")}}
  {{> devspec-upshift}}
{{else}}
  {{> devspec-help}}
{{/if}}

<!-- BEGIN TEMPLATE: devspec-help -->
## /devspec Command Reference

You've invoked `/devspec` without a command. Use one of:

### `/devspec create` — Interactive Dev Spec Generation
Walk each Dev Spec section collaboratively. I'll generate a draft for each section, present it for review, wait for your feedback, and — after each section the Pair approves — append a `[ledger D-NNN]` comment to the Plan tracking issue recording the decision. After Section 5 (Detailed Design), we'll walk the Deliverables Manifest defaults together.

**Input sources:** DDD domain model, external document, or verbal description.

**Prerequisite:** A Plan tracking issue (run `/issue plan "<name>"` first if one doesn't exist).

### `/devspec finalize` — Finalization Checklist
Run the Section 7.2 finalization checklist mechanically against an existing Dev Spec. Reports pass/fail per item with explanation.

### `/devspec approve` — Approval Gate
Run the finalization checklist, present a Dev Spec summary (section count, Story count, Wave count, deliverable count), and hard-stop for human approval. On approval, records approval metadata in the Dev Spec and appends a `[ledger D-NNN]` comment to the Plan issue. On rejection, lists failing items with suggested fixes.

**Prerequisite:** A finalized Dev Spec that passes all checklist items.

### `/devspec upshift` — Backlog Population
Create backlog issues from an approved Dev Spec's Section 8 (Phased Implementation Plan). Creates one Story issue per Story from §8, writes `phases-waves.json` with `plan_id` (the Plan issue number) and per-Story `depends_on`, and backfills Story issue numbers into the Dev Spec and the Plan issue's Phases checklist. Optionally creates a PM-layer Epic parent tracker (`type::epic`) if the Pair requests one.

**Prerequisite:** An approved Dev Spec (must have approval metadata from `/devspec approve`).

**Which command would you like to run?**
<!-- END TEMPLATE: devspec-help -->

<!-- BEGIN TEMPLATE: devspec-create -->
## Interactive Dev Spec Generation

I'll guide you through creating a complete Dev Spec, section by section. For each section, I'll generate a draft, present it for review, wait for your feedback, and — once you approve — append a `[ledger D-NNN]` comment to the Plan tracking issue recording the decision. The Decision Ledger (per `docs/phase-epic-taxonomy-devspec.md` §5.1, §5.2) is the authoritative record of decided matters across the Plan's lifecycle.

### Step 0: Resolve the Plan Issue

Before walking the Dev Spec, identify the **Plan tracking issue** this Dev Spec is anchored to:

1. **Ask the user:** "What is the Plan tracking issue number for this Dev Spec?" (e.g., `#499`)
2. If the user does not yet have a Plan issue, tell them: "Create one first with `/issue plan \"<name>\"` — the returned issue number is your `plan_id`. Then re-run `/devspec create`."
3. Record the Plan issue number as `plan_id` for the rest of the walk. Every `[ledger D-NNN]` comment this session appends will target this issue.
4. Determine the starting Ledger ID: fetch the Plan issue's existing comments, find the highest `[ledger D-NNN]` prefix already posted (or zero if none), and continue monotonically from `D-(max+1)`. See Step 3.5 below.

### Step 1: Determine Input Source

**How would you like to provide the concept for this Dev Spec?**

Check the arguments and conversation context for input mode. The three input sources are **equally first-class** — `/devspec create` MUST work with any of them. Do NOT assume a DDD artifact exists on disk.

1. **Verbal Description** — If no document is provided, ask the user to describe the project concept verbally. This is a **first-class input mode** that works without any DDD or external artifacts on disk.
2. **External Document** — If the user provides a path to any non-DDD document (concept doc, brief, notes), read it and extract the concept.
3. **DDD Domain Model** — Only if the user provides a path to a domain model (e.g., `docs/DOMAIN-MODEL.md`), or explicitly says "from the domain model", read it and use the DDD → Dev Spec translation protocol (`docs/DDD-to-devspec-protocol.md`) as the mapping guide. This is **opt-in**, not a prerequisite.

**If input is verbal:**
- Capture the verbal description directly into the section walk
- Do NOT look for `docs/DOMAIN-MODEL.md` or `docs/SKETCHBOOK.md`
- Use the captured description as the foundation for drafting each section

**If input is an external document:**
- Read the document
- Use it as the foundation for drafting each section

**If input is a DDD domain model:**
- Read `docs/DDD-to-devspec-protocol.md` for the translation rules
- Apply the 8-step translation as the backbone, but still walk each section interactively
- The protocol provides structure; the user provides judgment

**Load-bearing decoupling rule:** `/devspec create` must never fail due to a missing `docs/DOMAIN-MODEL.md` or `docs/SKETCHBOOK.md`. Those files are only read in the DDD input mode. In verbal and external-document modes, the skill must not touch them.

### Step 2: Ask for Project Name

**What should the Dev Spec be named?** (e.g., "my-project" → `docs/my-project-devspec.md`)

Read `docs/devspec-template.md` to load the template structure.

### Step 3: Walk Each Section

For **each** Dev Spec section (1 through 9), follow this pattern:

1. **Generate a draft** for the section based on the input source
2. **Present the draft** to the user
3. **Ask for feedback:** "Does this look right? Any changes before we move on?"
4. **Wait for the user to approve or request changes**
5. **Incorporate feedback** — iterate until the user is satisfied
6. **Append a `[ledger D-NNN]` comment to the Plan issue** (see Step 3.5 below) capturing the decisions locked in this section
7. **Record the final version** and move to the next section

### Step 3.5: Append Decision-Ledger Comment to the Plan Issue

**This is the load-bearing step.** After the Pair approves each section, the skill appends a `[ledger D-NNN]` comment to the Plan tracking issue. Per Dev Spec §5.2.1 the entry MUST conform to this schema:

```markdown
[ledger D-NNN] /devspec §X.Y · <ISO-8601 UTC timestamp with seconds>
**Decision:** <one sentence stating the decision definitively — no hedging>
**Rationale:** <one or two sentences referencing concrete evidence: memory file, prior decision, platform constraint, Pair input>

— **<Dev-Name>** <Dev-Avatar> (<Dev-Team>)
```

If the entry **corrects** a prior entry (new evidence, factual fix), include `**Supersedes:** D-MMM` on the line after the header (per §5.2.4 Correction workflow). Never edit the original `D-MMM` comment — append a new one.

**Mechanics:**

1. **Compute the next monotonic ID.** Re-read the Plan issue's comments just before posting (to catch concurrent writes); find the max existing `D-NNN`; post as `D-(max+1)`. The Tier 2 lint validator (cc-workflow#501) will flag collisions if two tools race.
2. **Compose the body** following the §5.2.1 schema above. Source is the canonical `/devspec §X.Y` form; if the decision pins a specific requirement, use `/devspec §X.Y R-NN`.
3. **Resolve agent identity.** Read `<project_root>/.claude/agent-identity.json` for `Dev-Name`, `Dev-Avatar`, and the project's `Dev-Team` from `CLAUDE.md` (fallback: `/tmp/claude-agent-<md5(repo-root)>.json`). These populate the signature line.
4. **Post the comment** by invoking the `pr_comment` MCP tool (`mcp__sdlc-server__pr_comment`) with `{ number: <plan_id>, body: <rendered ledger entry> }`. On GitHub and GitLab the tool targets the unified issue/PR comment stream, so it works for issue comments too.
5. **When to write entries** — per Dev Spec §5.2.2, write a `[ledger D-NNN]` comment for each of:
   - Pair approves a §1.5 non-goal
   - Pair approves a §2 constraint (Technical or Product)
   - Pair approves a §3 requirement (EARS)
   - Pair approves a §5 design choice
   - `/devspec approve` completes (one summary entry)
   Routine lifecycle events (Phase transitions, Wave completions, Story merges) do **not** get `[ledger]` comments — they use their own typed prefixes (`[phase-start]`, `[story-merge]`, etc. per §5.1.3).
6. **If `pr_comment` fails** (network, permissions, rate-limit): retry once; on second failure tell the Pair "Could not append ledger entry D-NNN to Plan issue #<plan_id> — <error>. Paste this into the issue manually:" and render the entry for copy-paste. Do NOT abort the walk — the Dev Spec file is still the primary record; the Ledger is the append-only replay.

**Example** (taken from `docs/phase-epic-taxonomy-devspec.md` §5.2.4):

```
[ledger D-011] /devspec §5.1 revised · 2026-04-26T19:40Z
**Supersedes:** D-006
**Decision:** Plan issue runtime state lives in ISSUE COMMENTS, not in mutable body sections.
**Rationale:** BJ's insight during §5.1 walk. Comments are append-only at the PLATFORM level...

— **Takashi** 🦔 (cc-workflow)
```

#### Section Walk Order

**Section 1: Problem Domain**
- 1.1 Background
- 1.2 Problem Statement
- 1.3 Proposed Solution
- 1.4 Target Users (if DDD input: translate from Actors responsibility matrix)
- 1.5 Non-Goals → **append ledger entry per Non-Goal**

**Section 2: Constraints** → **append ledger entry per Constraint**
- 2.1 Technical Constraints
- 2.2 Product Constraints

**Section 3: Requirements (EARS Format)** → **append ledger entry per Requirement**
- If DDD input: translate policies to EARS requirements using the heuristic table
- Group requirements by theme
- Number sequentially: R-01, R-02, ...

**Section 4: Concept of Operations**
- 4.1 System Context
- 4.X Operational flows (if DDD input: derive from commands and serial chains)

**Section 5: Detailed Design** → **append ledger entry per Design Choice**
- 5.1+ Design topics (project-specific)
- 5.A Deliverables Manifest → **see Step 4 below**
- 5.B Installation & Deployment
- 5.N Open Questions

**Section 6: Test Plan**
- 6.1 Test Strategy
- 6.2 Integration Tests
- 6.3 End-to-End Tests
- 6.4 Manual Verification Procedures

**Section 7: Definition of Done**
- Global DoD checklist
- 7.2 Dev Spec Finalization Checklist (pre-populated from template)

**Section 8: Phased Implementation Plan**
- **Phase** structure, **Stories** grouped into **Waves**
- Each Story declares `depends_on` on other Story titles/IDs (may be empty `[]`)
- After this section: verify manifest wave assignments (see Step 6)

**Section 9: Appendices**
- Appendix V: VRTM skeleton
- Additional appendices as needed

### Step 4: Walk the Deliverables Manifest (After Section 5)

After completing the design topics in Section 5, walk the **Tier 1 Deliverables Manifest defaults** with the user.

For **each** Tier 1 row (DM-01 through DM-09):
1. **Present the row:** ID, deliverable, category, default file path
2. **Ask:** "Confirm this deliverable? If not applicable, provide a rationale (N/A — because [reason])."
3. **Record the response:** confirmed (with any file path adjustments) or N/A with rationale
4. **If confirmed:** ask which Wave/Phase will produce it (fill "Produced In" column)

**Tier 1 defaults to walk:**

| ID | Deliverable | Category |
|----|-------------|----------|
| DM-01 | README.md | Docs |
| DM-02 | Unified build system (Makefile) | Code |
| DM-03 | CI/CD pipeline | Code |
| DM-04 | Automated test suite | Test |
| DM-05 | Test results (JUnit XML) | Test |
| DM-06 | Coverage report | Test |
| DM-07 | CHANGELOG | Docs |
| DM-08 | VRTM | Trace |
| DM-09 | Audience-facing doc (ops runbook, user manual, API/CLI ref) | Docs |

### Step 5: Scan for Tier 2 Triggers

After walking Tier 1, scan the Dev Spec content for Tier 2 trigger conditions:

| Trigger Condition | Deliverable to Add |
|-------------------|--------------------|
| MV-XX items exist in Section 6.4 | Manual test procedures document |
| >2 interacting components in design | Architecture document |
| Project deploys infrastructure | Deployment verification procedures |
| Project has host/platform requirements | Environment prerequisites document |

For each trigger that fires:
1. **Tell the user:** "Tier 2 trigger fired: [condition]. Adding [deliverable] to the manifest."
2. **Ask for file path and Wave assignment**
3. **Add the row** to the Deliverables Manifest

### Step 6: Verify Manifest Wave Assignments (After Section 8)

After completing Section 8 (Implementation Plan), verify that **every** Deliverables Manifest row has a "Produced In" Wave/Phase assignment.

For any row missing an assignment:
1. **Flag it:** "DM-XX ([deliverable]) has no Wave assignment yet."
2. **Ask the user** which Wave/Phase should produce it
3. **Update the row**

This is a hard gate — the Dev Spec cannot be finalized without complete Wave assignments.

### Step 7: Write the Dev Spec

After all sections are walked and the manifest is complete:

1. **Check for existing Dev Spec:** Call `devspec_locate` to see if a Dev Spec already exists for this project. If one is found, confirm with the user whether to overwrite or choose a different project name before proceeding.
2. **Assemble the Dev Spec** from all approved sections
3. **Write to** `docs/<project-name>-devspec.md`
4. **Post a reference comment to the Plan issue** (not a `[ledger]` entry — a plain informational comment): "Dev Spec written to `docs/<project-name>-devspec.md`. Run `/devspec finalize` to verify completeness."
5. **Report to the Pair:** "Dev Spec written to `docs/<project-name>-devspec.md`. Decision Ledger accumulated N entries on Plan issue #<plan_id>. Run `/devspec finalize` to verify completeness."

---

## Facilitation Rules

- **Never skip a section.** Every section in the template must be walked, even if minimal.
- **Never auto-approve.** Present each draft and wait for explicit user feedback.
- **Iterate on feedback.** If the user requests changes, regenerate and re-present.
- **Preserve traceability.** If the input is a DDD domain model, annotate requirements with policy IDs (`[P-XX]`), flows with command/event IDs, and AC items with requirement IDs.
- **Use EARS format** for all requirements in Section 3.
- **Fill in template placeholders.** Replace `[[...]]` guidance blocks with actual content — do not leave template instructions in the output.
- **Append Ledger entries as you go.** Do not batch them at the end of the walk — write one per decision, as the decision is locked (per §5.2.2 trigger table). The append-only Ledger is the audit trail.

<!-- END TEMPLATE: devspec-create -->

<!-- BEGIN TEMPLATE: devspec-finalize -->
## Dev Spec Finalization Checklist

Delegates all 7 Section 7.2 checks to the `devspec_finalize` MCP tool. The skill body only formats the result — it does NOT run the checks by hand.

### Step 1: Locate the Dev Spec

Call `devspec_locate` (with the user-provided `path` if given; otherwise it searches `docs/*-devspec.md`). If multiple Dev Specs are found, ask which to finalize. If none, tell the user: "No Dev Spec found. Run `/devspec create` first."

### Step 2: Run the Checks (and commit on pass)

Call `devspec_finalize(path)`. The tool runs all 7 checks and, **when they all pass, commits its own doc writes** (the `docs/*-devspec.md` Dev Spec + any decision-ledger / memory-file updates) as a single `docs(devspec): finalize Dev Spec for Plan #N` commit on the current branch — **no push**, and it **refuses to commit on a protected branch** (cc-workflow#604; so finalize writes never linger uncommitted and get swept into the next `/precheck`). Returns:

```jsonc
{ "ok", "passed", "total", "checks": [{ "id", "name", "passed", "evidence" }, ...],
  "committed": true|false, "commit_sha": "<sha>"|null, "files": ["docs/...md", ...],
  "refused_reason": null|"protected_branch"|"checks_failed"|"no_changes" }
```

`devspec_finalize` is **idempotent** on the commit — re-running it when the doc writes are already committed (or unchanged) produces no new commit (`committed:false`, `refused_reason:"no_changes"`).

### Step 3: Report

Format the `checks` array into a table (columns: #, Check, Result, Evidence). Report `**Result: X/7 checks passed.**` then:
- **All passing + `committed`** → report the commit: "✅ Committed the Dev Spec doc updates as `docs(devspec): finalize Dev Spec for Plan #N` (`<commit_sha>`, N files). **Not pushed** — it rides your next `/scp` / `/scpmr`. Dev Spec is ready for approval; run `/devspec approve`."
- **All passing + `refused_reason:"protected_branch"`** → warn: "Checks pass, but finalize refused to commit on the protected branch. Switch to a feature branch and re-run `/devspec finalize` so the doc updates are committed there."
- **All passing + `refused_reason:"no_changes"`** → "Dev Spec already committed/unchanged. Ready for approval; run `/devspec approve`."
- **Any failing** → list each failure with the tool's evidence as the remediation starting point, then "Fix these issues and run `/devspec finalize` again." (No commit is attempted when checks fail.)

<!-- END TEMPLATE: devspec-finalize -->

<!-- BEGIN TEMPLATE: devspec-approve -->
## Dev Spec Approval Gate

Gate between Dev Spec creation and backlog population. No Story issues get created until the Dev Spec is explicitly approved by a human.

**Tool chain:** `devspec_locate` → `devspec_finalize` → `devspec_summary` → **(hard stop — human approval)** → `devspec_approve` → `pr_comment` (ledger entry on Plan issue).

### Step 1: Locate the Dev Spec

Call `devspec_locate` (path arg if provided; otherwise searches `docs/*-devspec.md`). If multiple Dev Specs are found, ask which to approve. If none, tell the user: "No Dev Spec found. Run `/devspec create` first."

### Step 2: Run Finalization Checklist

Call `devspec_finalize(path)`. If any checks fail, present the report with the failures highlighted (use the `evidence` field for each failing check), suggest remediation, tell the user "Dev Spec has N failing checks. Fix these issues and run `/devspec approve` again.", and **stop.** Do not proceed to approval. (Per #604 `devspec_finalize` also commits its doc writes on pass, but it is **idempotent** — if `/devspec finalize` already committed them, this re-call makes no new commit [`committed:false, refused_reason:"no_changes"`]; so approving never produces a duplicate finalize commit.)

### Step 3: Present Dev Spec Summary

If all 7 checks pass, call `devspec_summary(path)` — returns `{ ok, sections, stories, waves, deliverables }`. Present:

```
## Dev Spec Approval Summary

| Metric | Count |
|--------|-------|
| Sections | N |
| Stories | N |
| Waves | N |
| Deliverables | N |
| Finalization checks | 7/7 passed |
```

### Step 4: Hard Stop for Approval

Present the approval prompt and **stop**. Do not proceed until the user responds.

> Dev Spec is ready for approval. All 7 finalization checks passed.
>
> **Approve this Dev Spec? (yes/no)**

**Wait for the user's response.**

### Step 5: Process Response

**On approval (yes/approve/confirmed/y):**

1. Call `devspec_approve(path, approved_by)`. **The TOOL writes the approval metadata block — do NOT hand-write it.** The agent's job is to invoke the tool and confirm the result.

2. Append a final `[ledger D-NNN]` comment to the Plan issue recording the approval. Per §5.2.2, `/devspec approve` completing is one of the canonical Ledger triggers. Example body:

   ```
   [ledger D-NNN] /devspec approve · <ISO-8601 UTC>
   **Decision:** Dev Spec approved — N requirements, M Phases, K Waves, L Stories.
   **Rationale:** All 7 finalization checks passed; Pair <approved_by> approved.

   — **<Dev-Name>** <Dev-Avatar> (<Dev-Team>)
   ```

For reference, the block that `devspec_approve` writes into the Dev Spec file has this shape (so a future `devspec_verify_approved` call can locate it):

```markdown
<!-- DEV-SPEC-APPROVAL
approved: true
approved_by: [user name or "stakeholder"]
approved_at: [ISO 8601 timestamp, e.g. 2026-04-04T12:00:00Z]
finalization_score: 7/7
-->
```

After the tool call succeeds and the Ledger entry is posted, confirm to the user: "Dev Spec approved. Approval metadata recorded. Ledger entry D-NNN posted to Plan issue #<plan_id>. Next step: run `/devspec upshift` to create Story issues and write `phases-waves.json`."

**On rejection (no/reject/n):** Ask what needs to change, list the finalization results as a starting point, tell the user "Make the requested changes and run `/devspec approve` again.", **stop.** Do not call `devspec_approve`. Do not post a Ledger entry.

<!-- END TEMPLATE: devspec-approve -->

<!-- BEGIN TEMPLATE: devspec-upshift -->
## Dev Spec Backlog Population (Upshift)

Creates Story issues from an approved Dev Spec's Section 8 (Phased Implementation Plan) and writes `phases-waves.json` — the bridge from Dev Spec to execution.

**Key shape change (per `docs/phase-epic-taxonomy-devspec.md` R-07, R-12, 2026-04-26):** The Plan issue (created earlier by `/issue plan`) is the top-level pipeline container. **Phases do NOT get their own issues** — they live inside `phases-waves.json` only. Upshift creates one issue per Story, writes `phases-waves.json` with `plan_id` and per-Story `depends_on`, and backfills Story numbers into the Dev Spec's §8 and into the Plan issue's Phases checklist.

An optional **PM-layer Epic** (the `type::epic` label, a thematic parent tracker) may be created if the Pair explicitly asks for one; this is purely a program-management convenience and is ignored by `/prepwaves`, `/nextwave`, and `/wavemachine`.

**Tool chain:** `devspec_locate` → `devspec_verify_approved` → `devspec_parse_section_8` → **loop** `work_item` for each Story (type::feature / type::bug / type::chore / type::doc) → write `phases-waves.json` → backfill Story numbers into Dev Spec and Plan issue → post summary comment to Plan issue.

### Step 1: Locate and Verify

Call `devspec_locate` (path arg if provided; otherwise searches `docs/*-devspec.md`). If multiple Dev Specs are found, ask which to upshift. If none, tell the user: "No Dev Spec found. Run `/devspec create` first."

Then call `devspec_verify_approved(path)` — returns `{ ok, approved }` after inspecting the `<!-- DEV-SPEC-APPROVAL` comment block for the `approved: true` marker. If `approved` is not `true`, tell the user: "This Dev Spec has not been approved. Run `/devspec approve` first." and **stop here.** Do not create any issues.

### Step 2: Resolve the Plan Issue

Ask the user (or read from conversation context if previously established) for the Plan tracking issue number. This is the `plan_id` that gets embedded in `phases-waves.json` and referenced from every Story issue body.

### Step 3: Parse Section 8

Call `devspec_parse_section_8(path)` — returns `{ ok, phases: [{ name, dod, waves: [{ name, stories: [{ id, title, summary, implementation_steps, test_procedures, acceptance_criteria, wave, depends_on }] }] }] }`. Each Story carries an `id` (stable identifier from §8, e.g. `3.4`), a `wave` label (e.g. `P3W2`), and a `depends_on` array of Story IDs (may be empty `[]`).

### Step 4: Create Story Issues (parallel batch)

Launch all Stories as **parallel Sonnet sub-agents in a single message** — they have no creation-time dependencies on each other. Do NOT loop serially.

Sub-agent template (one per Story, all launched in a single message):
```
subagent_type: general-purpose
model: sonnet
prompt: "Create a <subtype> issue in repo <owner/repo> using mcp__sdlc-server__work_item.

Type: <feature|bug|chore|doc>  (default: feature if not declared)
Title: <story.title>
Labels: [<type::<subtype>>]

Body (use exactly these H2 sections):

## Summary
<story.summary>

## Implementation Steps
<story.implementation_steps>

## Test Procedures
<story.test_procedures>

## Acceptance Criteria
<story.acceptance_criteria as checkboxes>

## Dependencies
<depends_on story IDs, or 'None'>

## Metadata
**Plan:** #<plan_id>
**Phase:** <phase-name>
**Wave:** <wave-name>
**Depends on:** <story IDs or 'none'>

Return: the issue number and URL only. No other output."
```

Wait for all sub-agents to return. Record each issue number keyed by Story ID (e.g. `{ "1.1": 501, "1.2": 502, ... }`). If any sub-agent fails, report the failure but continue collecting the rest — do not abort the batch. Failed Stories get a `FAILED` marker in the summary; the Pair resolves them manually.

### Step 5 (Optional): Create a PM-Layer Epic Parent Tracker

Ask the Pair: "Do you want a PM-layer Epic parent tracker to group these Stories thematically? This is optional and ignored by the pipeline — it's purely for program-management rollup. (yes/no)"

- **If yes:** Call `work_item(type: "epic", title: "Epic: <theme>", body: <canonical Epic template>, labels: ["type::epic"])`. Then, for each Story issue created in Step 4, apply the `epic::<N>` label (where N is the Epic issue number). This is the sole place the optional Epic PM-layer is wired up; the pipeline itself never reads these labels.
- **If no:** Skip this step. Stories live directly under the Plan issue via `phases-waves.json`.

### Step 6: Write `phases-waves.json` (v3 wave-status schema — DIRECTLY)

Assemble a `phases-waves.json` document at `.claude/status/phases-waves.json` (create the directory if needed) in the **v3 wave-status schema** — the exact shape `wave-status init` consumes, so a fresh `upshift → wave-status init` bootstraps with ZERO hand-edits (#850/ENG-4). Do NOT emit the legacy `{plan_id, slug, phases:[{name, waves:[{name, stories:[{id, issue}]}]}]}` shape — `wave-status init` (v3) requires top-level `project` and keys every wave by `id` and every issue by `number`; the legacy `waves[].name` + `waves[].stories[].issue` shape fails init (`plan is missing required field 'project'`; `KeyError: 'id'`). The upshift→v3 transform used to live only inside the sdlc `wave_init` handler (`normalizePlanJson`), so the decoupled `wave-status init` CLI path — which `/wavemachine` bootstrap and ENG-3a's own workaround hit — had no normalization. The emitter (this skill) now owns the contract.

Map the `devspec_parse_section_8` output into the v3 shape: each parsed `wave.name` → `wave.id`; each `story.issue` → an `issues[].number`; carry `title`; keep `depends_on` (a harmless extra field v3 ignores):

```json
{
  "project": "Wave-Engineering/claudecode-workflow",
  "repo": "Wave-Engineering/claudecode-workflow",
  "base_branch": "main",
  "plan_id": 499,
  "slug": "phase-epic-taxonomy",
  "phases": [
    {
      "name": "Phase 1: Foundation",
      "dod": ["..."],
      "waves": [
        {
          "id": "P1W1",
          "issues": [
            { "number": 501, "title": "...", "depends_on": [] },
            { "number": 502, "title": "...", "depends_on": ["1.1"] }
          ]
        }
      ]
    }
  ]
}
```

**Invariants (v3 wave-status schema; per R-07, R-18):**
- **`project`** (top-level, REQUIRED) — the `owner/repo` slug of the target repo. `wave-status init` rejects a plan without it. Also emit **`repo`** (same `owner/repo`, so `.issues` keys qualify as `owner/repo#N`) and **`base_branch`** (the protected branch, e.g. `main`).
- Every wave has an **`id`** (e.g. `P1W1`) — NOT `name`. `wave-status init` keys wave state by `id` (a missing `id` is a KeyError at init).
- Every wave has an **`issues`** array (NOT `stories`); every issue has a **`number`** (the Story issue created in Step 4) — NOT an `issue`/`id` field. `issues` must be non-empty.
- Every issue keeps its **`depends_on`** field, even if empty (`[]`) — a harmless extra field v3 ignores (topology still comes from the wave partition). Absence is not an error for v3 init, but keep it for downstream planners.
- `plan_id` is the Plan issue number (never `epic_id` — retired). `slug` is the kebab-case slug for kahuna branch naming (`kahuna/<plan_id>-<slug>`).

Write the file. A fresh `wave-status init .claude/status/phases-waves.json` must load it clean (schema_version 3) with no hand-edit — verify with the round-trip test `tests/test_devspec_upshift_roundtrip.py`. This is the authoritative input `/prepwaves` and `/wavemachine` consume.

### Step 7: Backfill Issue Numbers

1. **Into the Dev Spec file:** append the Story issue number to each Story heading in §8 (e.g., `#### Story 3.4: ... (#515)`). Write the updated Dev Spec back to disk.
2. **Into the Plan issue's Phases checklist:** the Plan issue body's Phases checklist (placeholder populated when the Plan was created) gets filled in with Story links. Use `gh issue edit <plan_id>` (or `glab issue update`) to replace the checklist placeholder with the resolved list, e.g.:

   ```markdown
   ## Phases
   - [ ] Phase 1: Foundation
     - [ ] Story 1.1: ... (#501)
     - [ ] Story 1.2: ... (#502)
   ```

   Per §5.1.6 the Plan body is **frozen at `/devspec approve`**; this Phases-checklist backfill is the one permitted post-approval body edit (it's the resolution of a placeholder, not a scope change). Any other post-approval body change requires a `[ledger D-NNN]` comment documenting why.

### Step 8: Report Summary

Present a creation summary:

```
## Backlog Population Summary

| Type | Count | Issue Numbers |
|------|-------|---------------|
| Stories | N | #A, #B, #C, ... |
| PM-layer Epic (optional) | 0 or 1 | #E (if created) |
| **Total issues created** | **N** | |

phases-waves.json written to .claude/status/phases-waves.json
  plan_id: <plan_id>
  phases: N
  waves: M
  issues: K  (v3: waves[].issues[].number; each keeps depends_on)

Plan issue #<plan_id> updated: Phases checklist backfilled.
```

Also post this summary as a plain comment (not a `[ledger]` entry) on the Plan issue so the Pair has a single place to read the backlog state.

Confirm to the user: "Backlog populated. N Story issues created. `phases-waves.json` written with plan_id=<plan_id> and per-Story depends_on. Dev Spec and Plan issue updated with Story references. Run `/nextwave` to begin execution." (Do NOT recommend `/prepwaves` — upshift already wrote the complete multi-Phase topology to `phases-waves.json`; running `/prepwaves` on top of it would be redundant or destructive.)

<!-- END TEMPLATE: devspec-upshift -->

---

## Important Rules

1. **Never skip the interactive walk.** Every section must be presented and approved by the user. Do not generate the entire Dev Spec in one shot.
2. **Append Ledger entries in-flight.** `/devspec create` writes `[ledger D-NNN]` comments to the Plan issue as each section is approved — not in a batch at the end. Per §5.2.2 triggers.
3. **Tier 1 is opt-OUT.** Every Tier 1 deliverable must be explicitly confirmed or given an "N/A — because [reason]" rationale. Silence is not consent to skip.
4. **Tier 2 triggers are mechanical.** Scan the Dev Spec content for trigger conditions — do not rely on the user to remember them.
5. **Wave assignment is a hard gate.** Every active manifest row must have a "Produced In" Wave before the Dev Spec is written.
6. **The Deliverables Manifest is the single source of truth.** Do not create separate artifact manifests or documentation kits — everything goes in 5.A.
7. **Finalization is mechanical.** `/devspec finalize` checks are deterministic — no judgment calls, no "looks good enough."
8. **Traceability is non-negotiable.** If the input is a DDD domain model, every requirement must trace back to a policy, every flow to commands/events, every Story AC to requirements.
9. **Epic is PM-layer only.** The pipeline reads Plan / Phase / Wave / Story from `phases-waves.json`. The `type::epic` label and `epic::N` labels are optional thematic groupings for program management only; they are never read by `/prepwaves`, `/nextwave`, or `/wavemachine`.
