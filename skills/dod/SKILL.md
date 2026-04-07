---
name: dod
description: Project Definition of Done verification against the Deliverables Manifest — verify every deliverable, run tests, check VRTM, produce pass/fail report
---

# Project DoD Verification

Read the Deliverables Manifest from the project's PRD and mechanically verify every deliverable exists at its declared path, every test passes, and VRTM is complete. Generate a pass/fail report and require explicit human sign-off before any campaign state change.

## Tools Used
- `mcp__sdlc-server__dod_load_manifest` — load and parse the Deliverables Manifest + Section 7 DoD + VRTM from a PRD
- `mcp__sdlc-server__dod_verify_deliverable` — run the per-category verification (Docs / Code / Test / Trace)
- `mcp__sdlc-server__dod_run_test_suite` — execute the project's test target and return pass/fail summary
- `mcp__sdlc-server__dod_check_coverage` — parse the coverage report at the declared path

## Commands
`/dod` or `/dod check` — run the full verification.

## Procedure

1. **Locate the PRD.** Use a user-provided path, else find `docs/*-PRD.md`. Multiple → ask. None → "No PRD found. Run `/prd create` first."
2. **Load the manifest.** Call `dod_load_manifest(prd_path)` to parse Sections 5.A (Deliverables), 7 (global DoD), 8 (phase DoD), and 9/Appendix V (VRTM). Separate active rows from `N/A -- <rationale>` rows (N/A without rationale is flagged).
3. **Verify each active deliverable.** For each row, call `dod_verify_deliverable(row)`. The tool applies the per-category rules:
   - **Docs**: file exists and is non-empty
   - **Code (binary/package)**: file exists; run discovered build if any
   - **Code (CI/CD)**: workflow file exists and last CI run passed (via `gh run list` / `glab ci list`)
   - **Code (build system)**: Makefile/task runner exists and `make test` (or equivalent) passes
   - **Test (results)**: results file exists (e.g. `reports/junit.xml`) with passing counts — call `dod_run_test_suite()` if missing and regenerable
   - **Test (coverage)**: `dod_check_coverage(path)` — file existence is the gate; percentage is informational
   - **Test (manual procedures)**: document exists and has execution evidence
   - **Trace (VRTM)**: every requirement traced, no `Pending` rows, all `Verified By` populated
4. **Check global DoD (Section 7).** Verify each item — phase DoD from Section 8 all checked, test plan items executed, cross-cutting conditions evidence in the codebase.
5. **Check VRTM completeness separately.** Every requirement ID from Section 3 appears; no `Pending` status; no empty `Verified By`.
6. **Present the verification report.** Header: project / PRD path / date. Then `Deliverables Manifest: X/Y verified` with one row per deliverable using V (passing) / X (failing) / O (N/A). Then `Global DoD: X/Y` with item-level results. End with `RESULT: READY` or `RESULT: NOT READY -- N items failing`.
7. **Approval flow.** All pass → "Project DoD verified. Approve to close? (yes/no)". Failures → "N items failing. Approve anyway, or fix first? (yes/no/fix)". On **yes**, if `.sdlc/` exists run `campaign-status stage-review dod` and suggest closing the parent epic. On **fix**, list each failing item with a specific, actionable remediation (file path / command / PRD section). On **no**, "Deferred. Re-run `/dod` when ready."

## Non-Negotiables

- **Mechanical verification only** — file exists or it does not, tests pass or they do not. No "looks good enough" judgments.
- **N/A is not a failure** — but bare `N/A` without a rationale is flagged.
- **VRTM completeness is mandatory** — `Pending` rows are failures. No exceptions.
- **Human approval is required** — even on all-green, present the report and wait.
- **Remediation is actionable** — specific file paths, commands, PRD sections; not vague advice.
- **The Deliverables Manifest is the source of truth** — verify against Section 5.A, not assumptions.
