---
name: prd
description: Interactive PRD creation with Deliverables Manifest and finalization checklist
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-prd does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-prd
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# PRD Creation Workflow

This skill provides a structured, interactive workflow for creating Product Requirements Documents. It walks each PRD section collaboratively, manages the Deliverables Manifest, and runs a mechanical finalization checklist.

## Platform Detection

Before proceeding, detect the platform:
1. Check `.claude-project.md` for cached platform config
2. If not cached, run `git remote -v` and inspect the origin URL
3. GitHub → `gh` CLI, GitLab → `glab` CLI

## Commands

- **`/prd create`** — Interactive PRD generation (walk each section, build Deliverables Manifest)
- **`/prd finalize`** — Mechanical finalization checklist (verify PRD completeness)

## Usage

```bash
# Create a new PRD interactively
/prd create

# Run the finalization checklist on an existing PRD
/prd finalize

# Show help
/prd
```

---

{{#if (eq args "create")}}
  {{> prd-create}}
{{else if (eq args "finalize")}}
  {{> prd-finalize}}
{{else}}
  {{> prd-help}}
{{/if}}

<!-- BEGIN TEMPLATE: prd-help -->
## /prd Command Reference

You've invoked `/prd` without a command. Use one of:

### `/prd create` — Interactive PRD Generation
Walk each PRD section collaboratively. I'll generate a draft for each section, present it for review, and wait for your feedback before moving to the next. After Section 5 (Detailed Design), we'll walk the Deliverables Manifest defaults together.

**Input sources:** DDD domain model, external document, or verbal description.

### `/prd finalize` — Finalization Checklist
Run the Section 7.2 finalization checklist mechanically against an existing PRD. Reports pass/fail per item with explanation.

**Which command would you like to run?**
<!-- END TEMPLATE: prd-help -->

<!-- BEGIN TEMPLATE: prd-create -->
## Interactive PRD Generation

I'll guide you through creating a complete PRD, section by section. For each section, I'll generate a draft, present it for review, and wait for your feedback before proceeding.

### Step 1: Determine Input Source

**How would you like to provide the concept for this PRD?**

Check the arguments and conversation context for input mode:

1. **DDD Domain Model** — If the user provides a path to a domain model (e.g., `docs/DOMAIN-MODEL.md`), or says "from the domain model", read it and use the DDD-to-PRD translation protocol (`docs/DDD-to-PRD-protocol.md`) as the mapping guide.
2. **External Document** — If the user provides a path to any other document (concept doc, brief, notes), read it and extract the concept.
3. **Verbal Description** — If no document is provided, ask the user to describe the project concept verbally.

**If input is a DDD domain model:**
- Read `docs/DDD-to-PRD-protocol.md` for the translation rules
- Apply the 8-step translation as the backbone, but still walk each section interactively
- The protocol provides structure; the user provides judgment

**If input is an external document or verbal:**
- Read the document or capture the verbal description
- Use it as the foundation for drafting each section

### Step 2: Ask for Project Name

**What should the PRD be named?** (e.g., "my-project" → `docs/my-project-PRD.md`)

Read `docs/PRD-template.md` to load the template structure.

### Step 3: Walk Each Section

For **each** PRD section (1 through 9), follow this pattern:

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
- 7.2 PRD Finalization Checklist (pre-populated from template)

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

After walking Tier 1, scan the PRD content for Tier 2 trigger conditions:

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

This is a hard gate — the PRD cannot be finalized without complete wave assignments.

### Step 7: Write the PRD

After all sections are walked and the manifest is complete:

1. **Assemble the PRD** from all approved sections
2. **Write to** `docs/<project-name>-PRD.md`
3. **Report:** "PRD written to `docs/<project-name>-PRD.md`. Run `/prd finalize` to verify completeness."

---

## Facilitation Rules

- **Never skip a section.** Every section in the template must be walked, even if minimal.
- **Never auto-approve.** Present each draft and wait for explicit user feedback.
- **Iterate on feedback.** If the user requests changes, regenerate and re-present.
- **Preserve traceability.** If the input is a DDD domain model, annotate requirements with policy IDs (`[P-XX]`), flows with command/event IDs, and AC items with requirement IDs.
- **Use EARS format** for all requirements in Section 3.
- **Fill in template placeholders.** Replace `[[...]]` guidance blocks with actual content — do not leave template instructions in the output.

<!-- END TEMPLATE: prd-create -->

<!-- BEGIN TEMPLATE: prd-finalize -->
## PRD Finalization Checklist

I'll run the Section 7.2 finalization checklist mechanically against an existing PRD and report pass/fail for each item.

### Step 1: Locate the PRD

Check for the PRD file:
1. If the user provided a path, use it
2. Otherwise, look for `docs/*-PRD.md` files
3. If multiple PRDs exist, ask the user which one to finalize
4. If no PRD exists, tell the user: "No PRD found. Run `/prd create` first."

### Step 2: Read the PRD

Read the entire PRD file into context. Also read `docs/PRD-template.md` for reference on expected structure.

### Step 3: Run Each Check

Execute each item from the Section 7.2 PRD Finalization Checklist. For each item, report:
- **Pass** or **Fail**
- **Evidence** — what was found (or not found) that determined the result
- **Location** — where in the PRD the relevant content lives

#### Check 1: Tier 1 Deliverables Manifest — File Paths

> Every Tier 1 row in the Deliverables Manifest (5.A) has a file path or "N/A — because [reason]"

**How to verify:**
1. Find Section 5.A in the PRD
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
## PRD Finalization Report

| # | Check | Result | Evidence |
|---|-------|--------|----------|
| 1 | Tier 1 file paths | PASS/FAIL | [details] |
| 2 | Tier 2 triggers | PASS/FAIL | [details] |
| 3 | Wave assignments | PASS/FAIL | [details] |
| 4 | MV-XX coverage | PASS/FAIL | [details] |
| 5 | Verbs without nouns | PASS/FAIL | [details] |
| 6 | Audience-facing docs | PASS/FAIL | [details] |
| 7 | DoD references | PASS/FAIL | [details] |

**Result: X/7 checks passed. PRD is [ready / not ready] for approval.**
```

If not all checks pass:
- List the specific failures with remediation steps
- Suggest running `/prd create` to fix the issues interactively

If all checks pass:
- "PRD is ready for approval. Next step: get stakeholder sign-off, then run `/prepwaves` to plan execution."

<!-- END TEMPLATE: prd-finalize -->

---

## Important Rules

1. **Never skip the interactive walk.** Every section must be presented and approved by the user. Do not generate the entire PRD in one shot.
2. **Tier 1 is opt-OUT.** Every Tier 1 deliverable must be explicitly confirmed or given an "N/A — because [reason]" rationale. Silence is not consent to skip.
3. **Tier 2 triggers are mechanical.** Scan the PRD content for trigger conditions — do not rely on the user to remember them.
4. **Wave assignment is a hard gate.** Every active manifest row must have a "Produced In" wave before the PRD is written.
5. **The Deliverables Manifest is the single source of truth.** Do not create separate artifact manifests or documentation kits — everything goes in 5.A.
6. **Finalization is mechanical.** `/prd finalize` checks are deterministic — no judgment calls, no "looks good enough."
7. **Traceability is non-negotiable.** If the input is a DDD domain model, every requirement must trace back to a policy, every flow to commands/events, every story AC to requirements.
