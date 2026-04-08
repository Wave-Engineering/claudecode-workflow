---
name: devspec
description: Interactive Development Specification creation with Deliverables Manifest, finalization checklist, approval gate, and backlog population
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

Check the arguments and conversation context for input mode:

1. **DDD Domain Model** — If the user provides a path to a domain model (e.g., `docs/DOMAIN-MODEL.md`), or says "from the domain model", read it and use the DDD → Dev Spec translation protocol (`docs/DDD-to-devspec-protocol.md`) as the mapping guide.
2. **External Document** — If the user provides a path to any other document (concept doc, brief, notes), read it and extract the concept.
3. **Verbal Description** — If no document is provided, ask the user to describe the project concept verbally.

**If input is a DDD domain model:**
- Read `docs/DDD-to-devspec-protocol.md` for the translation rules
- Apply the 8-step translation as the backbone, but still walk each section interactively
- The protocol provides structure; the user provides judgment

**If input is an external document or verbal:**
- Read the document or capture the verbal description
- Use it as the foundation for drafting each section

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

1. **Assemble the Dev Spec** from all approved sections
2. **Write to** `docs/<project-name>-devspec.md`
3. **Report:** "Dev Spec written to `docs/<project-name>-devspec.md`. Run `/devspec finalize` to verify completeness."

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

I'll run the Section 7.2 finalization checklist mechanically against an existing Dev Spec and report pass/fail for each item.

### Step 1: Locate the Dev Spec

Check for the Dev Spec file:
1. If the user provided a path, use it
2. Otherwise, look for `docs/*-devspec.md` files
3. If multiple Dev Specs exist, ask the user which one to finalize
4. If no Dev Spec exists, tell the user: "No Dev Spec found. Run `/devspec create` first."

### Step 2: Read the Dev Spec

Read the entire Dev Spec file into context. Also read `docs/devspec-template.md` for reference on expected structure.

### Step 3: Run Each Check

Execute each item from the Section 7.2 Dev Spec Finalization Checklist. For each item, report:
- **Pass** or **Fail**
- **Evidence** — what was found (or not found) that determined the result
- **Location** — where in the Dev Spec the relevant content lives

#### Check 1: Tier 1 Deliverables Manifest — File Paths

> Every Tier 1 row in the Deliverables Manifest (5.A) has a file path or "N/A — because [reason]"

**How to verify:**
1. Find Section 5.A in the Dev Spec
2. Identify all rows with Tier = 1
3. For each Tier 1 row, check the "File Path" column
4. Pass if every Tier 1 row has a non-empty file path OR contains "N/A" with a rationale
5. Fail if any Tier 1 row has an empty file path without N/A rationale

#### Check 2: Tier 2 Triggers

> Every Tier 2 trigger that fires has a corresponding row in the Deliverables Manifest

**How to verify:**
1. Check Section 6.4 for MV-XX items → if present, manifest must have a "Manual test procedures" row
2. Count interacting components in Section 5 → if >2, manifest must have an "Architecture doc" row
3. Check for infrastructure deployment references → if present, manifest must have "Deployment verification" row
4. Check for host/platform requirements → if present, manifest must have "Environment prerequisites" row
5. Pass if all fired triggers have corresponding rows
6. Fail if any fired trigger is missing

#### Check 3: Wave Assignments

> Every Deliverables Manifest row has a "Produced In" wave assignment

**How to verify:**
1. Read every row in the Deliverables Manifest (5.A)
2. Check the "Produced In" column for each non-N/A row
3. Pass if every active row has a wave/phase assignment
4. Fail if any active row has an empty "Produced In"

#### Check 4: Manual Verification Coverage

> Every MV-XX in Section 6.4 has a procedure document in the Deliverables Manifest

**How to verify:**
1. List all MV-XX items from Section 6.4
2. For each MV-XX, check that the Deliverables Manifest has a corresponding procedure document
3. Pass if all MV-XX items are covered
4. Fail if any MV-XX lacks a manifest entry

#### Check 5: Verbs Without Nouns

> No deliverable is referenced only as a verb without a corresponding noun (file path)

**How to verify:**
1. Scan the Deliverables Manifest for active (non-N/A) rows
2. For each row, verify the "File Path" column contains an actual path (starts with a directory, has an extension, or is a recognizable file reference)
3. Flag any row where the deliverable is described as an action ("run tests", "deploy") but has no file artifact
4. Pass if all active deliverables have concrete file references
5. Fail if any deliverable is verb-only

#### Check 6: Audience-Facing Documentation

> At least one audience-facing doc (DM-09) has a file path assigned

**How to verify:**
1. Find DM-09 (or equivalent audience-facing doc rows) in the Deliverables Manifest
2. Check that at least one has a concrete file path (not N/A)
3. Pass if at least one audience-facing doc has a path
4. Fail if all are N/A or empty

#### Check 7: Definition of Done References

> Section 7 Definition of Done references the Deliverables Manifest (not separate Artifact Manifest + Documentation Kit)

**How to verify:**
1. Read Section 7 (Definition of Done)
2. Check that it references "Deliverables Manifest (Section 5.A)" or equivalent
3. Check that it does NOT reference "Artifact Manifest" and "Documentation Kit" as separate concepts
4. Pass if references are unified
5. Fail if references are split or outdated

### Step 4: Report Summary

After all checks complete, present:

```
## Dev Spec Finalization Report

| # | Check | Result | Evidence |
|---|-------|--------|----------|
| 1 | Tier 1 file paths | PASS/FAIL | [details] |
| 2 | Tier 2 triggers | PASS/FAIL | [details] |
| 3 | Wave assignments | PASS/FAIL | [details] |
| 4 | MV-XX coverage | PASS/FAIL | [details] |
| 5 | Verbs without nouns | PASS/FAIL | [details] |
| 6 | Audience-facing docs | PASS/FAIL | [details] |
| 7 | DoD references | PASS/FAIL | [details] |

**Result: X/7 checks passed. Dev Spec is [ready / not ready] for approval.**
```

If not all checks pass:
- List the specific failures with remediation steps
- Suggest running `/devspec create` to fix the issues interactively

If all checks pass:
- "Dev Spec is ready for approval. Next step: get stakeholder sign-off, then run `/prepwaves` to plan execution."

<!-- END TEMPLATE: devspec-finalize -->

<!-- BEGIN TEMPLATE: devspec-approve -->
## Dev Spec Approval Gate

This is the gate between Dev Spec creation and backlog population. No issues get created until the Dev Spec is explicitly approved by a human.

### Step 1: Locate the Dev Spec

Check for the Dev Spec file:
1. If the user provided a path, use it
2. Otherwise, look for `docs/*-devspec.md` files
3. If multiple Dev Specs exist, ask the user which one to approve
4. If no Dev Spec exists, tell the user: "No Dev Spec found. Run `/devspec create` first."

### Step 2: Run Finalization Checklist

Run the `/devspec finalize` checklist automatically against the Dev Spec. This is the same mechanical checklist from the finalize subcommand.

1. Execute all 7 finalization checks
2. Collect the results

**If any checks fail:**
- Present the finalization report with failures highlighted
- List each failing item with a specific remediation suggestion
- Tell the user: "Dev Spec has N failing checks. Fix these issues and run `/devspec approve` again."
- **Stop here.** Do not proceed to approval.

### Step 3: Present Dev Spec Summary

If all finalization checks pass, present a Dev Spec summary to the user:

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

Count these by scanning the Dev Spec:
- **Sections**: Count top-level `## N.` headings
- **Stories**: Count story entries in Section 8 (look for `#### Story` headings or numbered story items)
- **Waves**: Count wave entries in Section 8 (look for `### Wave` headings or wave references)
- **Deliverables**: Count active (non-N/A) rows in the Deliverables Manifest (Section 5.A)

### Step 4: Hard Stop for Approval

Present the approval prompt and **stop**. Do not proceed until the user responds.

**Tell the user:**

> Dev Spec is ready for approval. All 7 finalization checks passed.
>
> **Approve this Dev Spec? (yes/no)**

**Wait for the user's response.** Do not take any further action until they respond.

### Step 5: Process Response

**On approval (user says yes/approve/confirmed/y):**

1. Add an approval metadata section to the Dev Spec. Insert it after the frontmatter (if any) or at the top of the document, before Section 1:

```markdown
<!-- DEV-SPEC-APPROVAL
approved: true
approved_by: [user name or "stakeholder"]
approved_at: [ISO 8601 timestamp, e.g. 2026-04-04T12:00:00Z]
finalization_score: 7/7
-->
```

2. Confirm to the user: "Dev Spec approved. Approval metadata recorded. Next step: run `/devspec upshift` to create backlog issues."

**On rejection (user says no/reject/n):**

1. Ask the user what needs to change
2. List the finalization results as a starting point for discussion
3. Tell the user: "Make the requested changes to the Dev Spec, then run `/devspec approve` again."
4. **Stop here.**

<!-- END TEMPLATE: devspec-approve -->

<!-- BEGIN TEMPLATE: devspec-upshift -->
## Dev Spec Backlog Population (Upshift)

Creates backlog issues from an approved Dev Spec's Section 8 (Phased Implementation Plan). This is the bridge from Dev Spec to execution.

### Step 1: Locate and Verify the Dev Spec

Check for the Dev Spec file:
1. If the user provided a path, use it
2. Otherwise, look for `docs/*-devspec.md` files
3. If multiple Dev Specs exist, ask the user which one to upshift
4. If no Dev Spec exists, tell the user: "No Dev Spec found. Run `/devspec create` first."

**Verify approval:**
1. Search the Dev Spec for the approval metadata comment block (`<!-- DEV-SPEC-APPROVAL`)
2. Check that `approved: true` is present in the metadata
3. If no approval metadata is found or `approved` is not `true`:
   - Tell the user: "This Dev Spec has not been approved. Run `/devspec approve` first."
   - **Stop here.** Do not create any issues.

### Step 2: Parse Section 8

Read Section 8 (Phased Implementation Plan) and extract the structure:

1. **Phases** — Each `### Phase N:` heading defines a phase (epic)
2. **Waves** — Each `#### Wave N` or wave reference within a phase
3. **Stories** — Each story entry within a wave (look for `##### Story:` headings, numbered story items, or bullet-pointed stories)

For each story, extract:
- **Title** — The story name/description
- **Implementation steps** — Numbered steps or bullet points under the story
- **Test procedures** — Any test-related items
- **Acceptance criteria** — Checkboxes or criteria items
- **Wave assignment** — Which wave the story belongs to

### Step 3: Create Epic Issues (One per Phase)

For each Phase in Section 8:

1. Create an epic issue using the platform CLI:
   ```
   Title: Epic: Phase N — [Phase Name]
   Body:
   ## Phase Definition of Done
   [Copy the Phase DoD from the Dev Spec]

   ## Stories
   [List story titles that will be linked after creation]

   Labels: type::epic
   ```

2. Record the created issue number

### Step 4: Create Story Issues (One per Story)

For each Story in Section 8:

1. Create an issue using the platform CLI:
   ```
   Title: [Story title from Dev Spec]
   Body:
   ## Summary
   [Story description from Dev Spec]

   ## Implementation Steps
   [Copy implementation steps from Dev Spec]

   ## Test Procedures
   [Copy test procedures from Dev Spec]

   ## Acceptance Criteria
   [Copy acceptance criteria from Dev Spec as checkboxes]

   ## Metadata
   - **Wave:** [wave assignment]
   - **Phase:** [parent phase]
   - **Parent Epic:** #[epic issue number]

   Labels: type::feature
   ```

2. Record the created issue number
3. Link to the parent epic by editing the epic issue body to include `#NNN`

### Step 5: Create Wave Master Issues

For each Wave in Section 8:

1. Collect all story issue numbers created for this wave
2. Create a wave master issue:
   ```
   Title: Wave N Master — [brief description]
   Body:
   ## Constituent Stories
   - [ ] #[story-1-number] — [story-1-title]
   - [ ] #[story-2-number] — [story-2-title]
   ...

   ## Wave Metadata
   - **Phase:** [parent phase]
   - **Story count:** N

   Labels: type::chore
   ```

3. Record the created issue number

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

Update the Dev Spec file to include the created issue numbers:

1. For each Phase heading, append the epic issue number: `### Phase 1: Foundation (#NNN)`
2. For each Story, append the story issue number
3. For each Wave reference, append the wave master issue number
4. Write the updated Dev Spec back to disk

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
