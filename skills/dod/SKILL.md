---
name: dod
description: Project Definition of Done verification against the Deliverables Manifest — verify every deliverable, run tests, check VRTM, produce pass/fail report
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-dod does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-dod
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Project DoD Verification

This skill reads the Deliverables Manifest from the project's PRD and mechanically verifies that every deliverable was produced, every test passed, and every artifact exists at its declared file path. It generates a pass/fail report and requires human sign-off to close the project.

## Platform Detection

Before proceeding, detect the platform:
1. Check `.claude-project.md` for cached platform config
2. If not cached, run `git remote -v` and inspect the origin URL
3. GitHub -> `gh` CLI, GitLab -> `glab` CLI

## Commands

- **`/dod check`** -- Run the full verification. Read the Deliverables Manifest from the PRD, verify each row, report results.
- **`/dod`** (no args) -- Same as `/dod check`.

## Usage

```bash
# Run the full DoD verification
/dod check

# Same as /dod check
/dod
```

---

{{#if (eq args "check")}}
  {{> dod-check}}
{{else}}
  {{> dod-check}}
{{/if}}

<!-- BEGIN TEMPLATE: dod-check -->
## DoD Verification Workflow

### Step 1: Locate the PRD

Find the project's PRD:
1. If the user provided a path, use it
2. Otherwise, look for `docs/*-PRD.md` files
3. If multiple PRDs exist, ask the user which one to verify
4. If no PRD exists, tell the user: "No PRD found. Run `/prd create` first."

### Step 2: Read the PRD

Read the entire PRD file into context. Extract:
1. **Deliverables Manifest (Section 5.A)** -- the table of all deliverables
2. **Section 7 (Definition of Done)** -- the global DoD checklist
3. **Section 9, Appendix V (VRTM)** -- the Verification Requirements Traceability Matrix

### Step 3: Parse the Deliverables Manifest

For each row in the Deliverables Manifest (Section 5.A), extract:
- **ID** (e.g., DM-01)
- **Deliverable** (e.g., README.md)
- **Category** (Docs, Code, Test, Trace)
- **File Path** (the declared file location)
- **Status** (required, N/A, etc.)
- **Notes**

Separate rows into:
- **Active rows** -- rows that need verification (not marked N/A)
- **N/A rows** -- rows marked "N/A -- [reason]" (verify rationale exists, skip verification)

### Step 4: Verify Each Deliverable

For each **active** row, apply the verification logic based on its Category:

#### Category: Docs

1. Check that the file exists at the declared path
2. Check that the file is non-empty (has content)
3. **Pass** if file exists and is non-empty
4. **Fail** if file is missing or empty
5. Report: file path, line count

#### Category: Code (binary/package)

1. Check that the file exists at the declared path
2. If a build command is discoverable (Makefile, package.json, etc.), run it
3. **Pass** if file exists and build succeeds (or no build command found)
4. **Fail** if file is missing or build fails
5. Report: file path, build result

#### Category: Code (CI/CD)

1. Check that the pipeline config file exists (`.github/workflows/*.yml` or `.gitlab-ci.yml`)
2. Check the last CI run status using the platform CLI:
   - GitHub: `gh run list --limit 1 --json status,conclusion`
   - GitLab: `glab ci list --per-page 1`
3. **Pass** if config exists and last CI run passed
4. **Fail** if config is missing or last CI run failed
5. Report: config file path, last run status

#### Category: Code (build system)

1. Check that the Makefile or task runner exists at the declared path
2. Run `make test` (or equivalent test target)
3. **Pass** if file exists and tests pass
4. **Fail** if file is missing or tests fail
5. Report: file path, test result

#### Category: Test (results)

1. Check that the test results file exists at the declared path (e.g., `reports/junit.xml`)
2. If the file exists, parse it for a pass/fail summary
3. **Pass** if file exists and contains passing results
4. **Fail** if file is missing or contains failures
5. Report: file path, pass/fail counts

#### Category: Test (coverage)

1. Check that the coverage report file exists at the declared path (e.g., `reports/coverage.xml`)
2. If the file exists, parse it for the coverage percentage
3. **Pass** if file exists (coverage percentage is informational, not a gate)
4. **Fail** if file is missing
5. Report: file path, coverage percentage

#### Category: Test (manual procedures)

1. Check that the procedures document exists at the declared path
2. Check for recorded results (evidence that the procedures were executed)
3. **Pass** if document exists and has execution records
4. **Fail** if document is missing or has no execution evidence
5. Report: file path, execution status

#### Category: Trace (VRTM)

1. Find the VRTM section in the PRD (Section 9, Appendix V)
2. Parse all rows in the VRTM table
3. Check for any rows with status "Pending" or empty status
4. **Pass** if VRTM is populated and no rows have "Pending" status
5. **Fail** if VRTM has "Pending" rows or is empty
6. Report: row count, pending count

#### N/A Rows

For each N/A row:
1. Verify that a rationale exists after "N/A" (e.g., "N/A -- CLI-only tool, API ref covers usage")
2. Report as "N/A (opted out)" with the rationale
3. These do **not** count as failures

### Step 5: Check Global DoD (Section 7)

Verify each item in the Section 7 Definition of Done checklist:

1. **All Phase DoD checklists satisfied** -- Check Section 8 for Phase DoD items; verify all are checked
2. **All Test Plan items executed and passed** -- Cross-reference Section 6 test items with test results
3. **All deliverables from Deliverables Manifest produced and verified** -- This is the result of Step 4 above
4. **Cross-cutting conditions** -- Verify each additional DoD item by checking the codebase for evidence

### Step 6: Check VRTM Completeness

Verify the VRTM (Section 9, Appendix V) separately:
1. Every requirement ID from Section 3 must appear in the VRTM
2. Every VRTM row must have a non-empty "Verified By" column
3. No VRTM row should have status "Pending"
4. **Pass** if all requirements are traced and verified
5. **Fail** if any requirement is untraced or any row is pending

### Step 7: Present the Verification Report

Format and present the report:

```
======================================================
  Project DoD Verification Report
  Project: <project-name>
  PRD: docs/<project>-PRD.md
  Date: <date>
======================================================

Deliverables Manifest: X/Y verified

  V DM-01  README.md                    README.md exists (847 lines)
  V DM-02  Unified build system         Makefile exists, make test passes
  V DM-03  CI/CD pipeline               .github/workflows/ci.yml exists, last run passed
  X DM-04  Automated test suite         reports/junit.xml missing
  O DM-09  User manual                  N/A -- CLI-only tool, API ref covers usage
  ...

Global DoD (Section 7): X/Y verified
  V All Phase DoD checklists satisfied
  X VRTM has 2 rows with status "Pending"
  ...

RESULT: NOT READY -- 2 items failing

Approve anyway? (yes / no / fix)
```

Use these status indicators:
- **V** (checkmark equivalent) -- verified/passing
- **X** -- failing
- **O** (circle) -- N/A / opted out

### Step 8: Approval Flow

After presenting the report:

1. **If all items pass:**
   - "Project DoD verified. All deliverables confirmed, all tests passed, VRTM complete."
   - "Approve to close the project? (yes / no)"

2. **If failures exist:**
   - "X items failing. Approve anyway, or fix first? (yes / no / fix)"

3. **On approval (user says yes/approve/y):**
   - If `campaign-status` is active (`.sdlc/` directory exists), update the campaign:
     ```bash
     campaign-status stage-review dod
     ```
   - Suggest closing the epic: "DoD approved. Consider closing the parent epic if all phases are complete."

4. **On "fix" (user says fix):**
   - List each failing item with a specific remediation suggestion:
     - Missing file -> "Create [file] at [path]"
     - Failed build -> "Fix build errors and re-run"
     - Pending VRTM rows -> "Update VRTM status for requirements [IDs]"
     - Missing test results -> "Run tests and generate [file]"

5. **On rejection (user says no/reject/n):**
   - "DoD verification deferred. Re-run `/dod` when ready."

<!-- END TEMPLATE: dod-check -->

---

## Important Rules

1. **Mechanical verification only.** Every check is deterministic -- file exists or it does not, tests pass or they do not. No subjective "looks good enough" judgments.
2. **N/A is not a failure.** Rows explicitly marked N/A with a rationale are respected. The rationale must exist -- bare "N/A" without explanation is flagged.
3. **VRTM completeness is mandatory.** Every requirement must be traceable. "Pending" status rows are failures.
4. **Human approval is required.** Even if all items pass, the report must be presented and the user must explicitly approve before any campaign state change.
5. **Remediation is actionable.** When suggesting fixes, provide specific file paths, commands, or PRD sections -- not vague advice.
6. **The Deliverables Manifest is the source of truth.** Verify against Section 5.A, not against assumptions about what should exist.
