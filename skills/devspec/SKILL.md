---
name: devspec
description: Interactive Development Specification creation with Deliverables Manifest, finalization checklist, approval gate, and backlog population (uses sdlc-server MCP tools for deterministic work)
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-devspec does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-devspec
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Development Specification Creation Workflow

This skill provides a structured, interactive workflow for creating Development Specifications. It walks each Dev Spec section collaboratively, manages the Deliverables Manifest, and runs a mechanical finalization checklist.

## Platform Detection

Before proceeding, detect the platform:
1. Check `.claude-project.md` for cached platform config
2. If not cached, run `git remote -v` and inspect the origin URL
3. GitHub → `gh` CLI, GitLab → `glab` CLI

## Commands

- **`/devspec create`** — Interactive Dev Spec generation (walk each section, build Deliverables Manifest)
- **`/devspec finalize`** — Mechanical finalization checklist (verify Dev Spec completeness)
- **`/devspec approve`** — Approval gate (run finalization, present summary, record approval)
- **`/devspec upshift`** — Backlog population (create epics, stories, and wave master issues from approved Dev Spec)

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
Walk each Dev Spec section collaboratively. I'll generate a draft for each section, present it for review, and wait for your feedback before moving to the next. After Section 5 (Detailed Design), we'll walk the Deliverables Manifest defaults together.

**Input sources:** DDD domain model, external document, or verbal description.

### `/devspec finalize` — Finalization Checklist
Run the Section 7.2 finalization checklist mechanically against an existing Dev Spec. Reports pass/fail per item with explanation.

### `/devspec approve` — Approval Gate
Run the finalization checklist, present a Dev Spec summary (section count, story count, wave count, deliverable count), and hard-stop for human approval. On approval, records approval metadata in the Dev Spec. On rejection, lists failing items with suggested fixes.

**Prerequisite:** A finalized Dev Spec that passes all checklist items.

### `/devspec upshift` — Backlog Population
Create backlog issues from an approved Dev Spec's Section 8 (Phased Implementation Plan). Creates epic issues per phase, story issues with full acceptance criteria, and wave master issues linking constituent stories. Backfills issue numbers into the Dev Spec.

**Prerequisite:** An approved Dev Spec (must have approval metadata from `/devspec approve`).

**Which command would you like to run?**
<!-- END TEMPLATE: devspec-help -->

<!-- BEGIN TEMPLATE: devspec-create -->
## Interactive Dev Spec Generation

I'll guide you through creating a complete Dev Spec, section by section. For each section, I'll generate a draft, present it for review, and wait for your feedback before proceeding.

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
6. **Record the final version** and move to the next section

#### Section Walk Order

**Section 1: Problem Domain**
- 1.1 Background
- 1.2 Problem Statement
- 1.3 Proposed Solution
- 1.4 Target Users (if DDD input: translate from Actors responsibility matrix)
- 1.5 Non-Goals

**Section 2: Constraints**
- 2.1 Technical Constraints
- 2.2 Product Constraints

**Section 3: Requirements (EARS Format)**
- If DDD input: translate policies to EARS requirements using the heuristic table
- Group requirements by theme
- Number sequentially: R-01, R-02, ...

**Section 4: Concept of Operations**
- 4.1 System Context
- 4.X Operational flows (if DDD input: derive from commands and serial chains)

**Section 5: Detailed Design**
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
- Phase structure, stories, waves
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
4. **If confirmed:** ask which wave/phase will produce it (fill "Produced In" column)

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
2. **Ask for file path and wave assignment**
3. **Add the row** to the Deliverables Manifest

### Step 6: Verify Manifest Wave Assignments (After Section 8)

After completing Section 8 (Implementation Plan), verify that **every** Deliverables Manifest row has a "Produced In" wave/phase assignment.

For any row missing an assignment:
1. **Flag it:** "DM-XX ([deliverable]) has no wave assignment yet."
2. **Ask the user** which wave/phase should produce it
3. **Update the row**

This is a hard gate — the Dev Spec cannot be finalized without complete wave assignments.

### Step 7: Write the Dev Spec

After all sections are walked and the manifest is complete:

1. **Check for existing Dev Spec:** Call `devspec_locate` to see if a Dev Spec already exists for this project. If one is found, confirm with the user whether to overwrite or choose a different project name before proceeding.
2. **Assemble the Dev Spec** from all approved sections
3. **Write to** `docs/<project-name>-devspec.md`
4. **Report:** "Dev Spec written to `docs/<project-name>-devspec.md`. Run `/devspec finalize` to verify completeness."

---

## Facilitation Rules

- **Never skip a section.** Every section in the template must be walked, even if minimal.
- **Never auto-approve.** Present each draft and wait for explicit user feedback.
- **Iterate on feedback.** If the user requests changes, regenerate and re-present.
- **Preserve traceability.** If the input is a DDD domain model, annotate requirements with policy IDs (`[P-XX]`), flows with command/event IDs, and AC items with requirement IDs.
- **Use EARS format** for all requirements in Section 3.
- **Fill in template placeholders.** Replace `[[...]]` guidance blocks with actual content — do not leave template instructions in the output.

<!-- END TEMPLATE: devspec-create -->

<!-- BEGIN TEMPLATE: devspec-finalize -->
## Dev Spec Finalization Checklist

Delegates all 7 Section 7.2 checks to the `devspec_finalize` MCP tool. The skill body only formats the result — it does NOT run the checks by hand.

### Step 1: Locate the Dev Spec

Call `devspec_locate` (with the user-provided `path` if given; otherwise it searches `docs/*-devspec.md`). If multiple Dev Specs are found, ask which to finalize. If none, tell the user: "No Dev Spec found. Run `/devspec create` first."

### Step 2: Run the Checks

Call `devspec_finalize(path)`. The tool runs all 7 checks and returns `{ ok, passed, total, checks: [{ id, name, passed, evidence }, ...] }`.

### Step 3: Report

Format the `checks` array into a table (columns: #, Check, Result, Evidence). Report `**Result: X/7 checks passed.**` and either:
- All passing → "Dev Spec is ready for approval. Run `/devspec approve`."
- Any failing → list each failure with the tool's evidence as the remediation starting point, then "Fix these issues and run `/devspec finalize` again."

<!-- END TEMPLATE: devspec-finalize -->

<!-- BEGIN TEMPLATE: devspec-approve -->
## Dev Spec Approval Gate

Gate between Dev Spec creation and backlog population. No issues get created until the Dev Spec is explicitly approved by a human.

**Tool chain:** `devspec_locate` → `devspec_finalize` → `devspec_summary` → **(hard stop — human approval)** → `devspec_approve`.

### Step 1: Locate the Dev Spec

Call `devspec_locate` (path arg if provided; otherwise searches `docs/*-devspec.md`). If multiple Dev Specs are found, ask which to approve. If none, tell the user: "No Dev Spec found. Run `/devspec create` first."

### Step 2: Run Finalization Checklist

Call `devspec_finalize(path)`. If any checks fail, present the report with the failures highlighted (use the `evidence` field for each failing check), suggest remediation, tell the user "Dev Spec has N failing checks. Fix these issues and run `/devspec approve` again.", and **stop.** Do not proceed to approval.

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

**On approval (yes/approve/confirmed/y):** Call `devspec_approve(path, approved_by)`. **The TOOL writes the approval metadata block — do NOT hand-write it.** The agent's job is to invoke the tool and confirm the result.

For reference, the block that `devspec_approve` writes into the Dev Spec file has this shape (so a future `devspec_verify_approved` call can locate it):

```markdown
<!-- DEV-SPEC-APPROVAL
approved: true
approved_by: [user name or "stakeholder"]
approved_at: [ISO 8601 timestamp, e.g. 2026-04-04T12:00:00Z]
finalization_score: 7/7
-->
```

After the tool call succeeds, confirm to the user: "Dev Spec approved. Approval metadata recorded. Next step: run `/devspec upshift` to create backlog issues."

**On rejection (no/reject/n):** Ask what needs to change, list the finalization results as a starting point, tell the user "Make the requested changes and run `/devspec approve` again.", **stop.** Do not call `devspec_approve`.

<!-- END TEMPLATE: devspec-approve -->

<!-- BEGIN TEMPLATE: devspec-upshift -->
## Dev Spec Backlog Population (Upshift)

Creates backlog issues from an approved Dev Spec's Section 8 (Phased Implementation Plan) — the bridge from Dev Spec to execution.

**Tool chain:** `devspec_locate` → `devspec_verify_approved` → `devspec_parse_section_8` → **loop** `work_item` for each epic/story/wave master → backfill issue numbers.

### Step 1: Locate and Verify

Call `devspec_locate` (path arg if provided; otherwise searches `docs/*-devspec.md`). If multiple Dev Specs are found, ask which to upshift. If none, tell the user: "No Dev Spec found. Run `/devspec create` first."

Then call `devspec_verify_approved(path)` — returns `{ ok, approved }` after inspecting the `<!-- DEV-SPEC-APPROVAL` comment block for the `approved: true` marker. If `approved` is not `true`, tell the user: "This Dev Spec has not been approved. Run `/devspec approve` first." and **stop here.** Do not create any issues.

### Step 2: Parse Section 8

Call `devspec_parse_section_8(path)` — returns `{ ok, phases: [{ name, dod, waves: [{ name, stories: [{ title, summary, implementation_steps, test_procedures, acceptance_criteria, wave }] }] }] }`.

### Step 3: Create Epic Issues (one per Phase)

For each Phase, call `work_item(type: "epic", title: "Epic: Phase N — <name>", body, labels: ["type::epic"])`. The epic body includes the Phase Definition of Done (`phase.dod`) and a "Stories" placeholder to be filled after story creation. Record the returned epic issue number per phase.

### Step 4: Create Story Issues (one per Story)

For each Story, call `work_item(type: "feature", title: story.title, body, labels: ["type::feature"])`. The story body includes `## Summary`, `## Implementation Steps` (from `story.implementation_steps`), `## Test Procedures` (from `story.test_procedures`), `## Acceptance Criteria` (as checkboxes from `story.acceptance_criteria`), and a `## Metadata` block with **Wave**, **Phase**, and **Parent Epic:** #<epic issue number>. Record each returned issue number. After all stories for a phase land, update the parent epic's body to link them (`#NNN` references).

### Step 5: Create Wave Master Issues

For each Wave, call `work_item(type: "chore", title: "Wave N Master — <brief>", body, labels: ["type::chore"])`. The wave master body includes `## Constituent Stories` (checkbox list of story issue links) and `## Wave Metadata` with **Phase** and **Story count**. Record each returned issue number.

### Step 6: Report Summary

Present a creation summary:

```
## Backlog Population Summary

| Type | Count | Issue Numbers |
|------|-------|---------------|
| Epics (Phases) | N | #X, #Y |
| Stories | N | #A, #B, #C, ... |
| Wave Masters | N | #P, #Q |
| **Total issues created** | **N** | |
```

### Step 7: Backfill Issue Numbers into Dev Spec

Update the Dev Spec file to append created issue numbers to the Section 8 headings (skill-body work — no dedicated tool): append epic number to each `### Phase N:` heading, story number to each story, wave master number to each wave reference. Write the updated Dev Spec back to disk.

Confirm to the user: "Backlog populated. N issues created. Dev Spec updated with issue references. Run `/prepwaves` to plan execution."

<!-- END TEMPLATE: devspec-upshift -->

---

## Important Rules

1. **Never skip the interactive walk.** Every section must be presented and approved by the user. Do not generate the entire Dev Spec in one shot.
2. **Tier 1 is opt-OUT.** Every Tier 1 deliverable must be explicitly confirmed or given an "N/A — because [reason]" rationale. Silence is not consent to skip.
3. **Tier 2 triggers are mechanical.** Scan the Dev Spec content for trigger conditions — do not rely on the user to remember them.
4. **Wave assignment is a hard gate.** Every active manifest row must have a "Produced In" wave before the Dev Spec is written.
5. **The Deliverables Manifest is the single source of truth.** Do not create separate artifact manifests or documentation kits — everything goes in 5.A.
6. **Finalization is mechanical.** `/devspec finalize` checks are deterministic — no judgment calls, no "looks good enough."
7. **Traceability is non-negotiable.** If the input is a DDD domain model, every requirement must trace back to a policy, every flow to commands/events, every story AC to requirements.
