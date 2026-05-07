---
name: dod
description: Project Definition of Done verification against the Plan-issue DoD — verify every Plan-level + per-Phase checkbox, run tests, optionally fall through to Dev Spec for Deliverables Manifest + VRTM, produce pass/fail report
---

# Project DoD Verification

Read the Definition of Done from the **Plan issue body** (the pipeline's frozen tracking artifact, per the Plan/Phase/Epic taxonomy lock — `docs/phase-epic-taxonomy-devspec.md` §5.1) and mechanically verify every Plan-level and per-Phase checkbox. Optionally fall through to the Dev Spec's Deliverables Manifest + VRTM when the Plan body's References point to one. Generate a pass/fail report and require explicit human sign-off before any campaign state change.

## Tools Used
- `mcp__sdlc-server__plan_load_dod` — resolve Plan-issue body and parse `plan_level_dod`, `phases[].items[]`, optional `devspec_path`
- `mcp__sdlc-server__dod_load_manifest` — load and parse the Deliverables Manifest + Section 7 DoD + VRTM from a Dev Spec (fallback / supplemental)
- `mcp__sdlc-server__dod_verify_deliverable` — run the per-category verification (Docs / Code / Test / Trace)
- `mcp__sdlc-server__dod_run_test_suite` — execute the project's test target and return pass/fail summary
- `mcp__sdlc-server__dod_check_coverage` — parse the coverage report at the declared path

## Commands
`/dod` or `/dod check` — run the full verification, resolving the Plan-issue from context.
`/dod check <N>` — run the full verification against Plan issue `#N` explicitly.

## Procedure

1. **Resolve `plan_id`.** Try the following sources in order; the first match wins:
   1. **User-provided argument** — `/dod check <N>` → `plan_id = N`.
   2. **Current branch matches `kahuna/(\d+)-`** — capture the digits. (Wave-pattern KAHUNA flights live on `kahuna/<plan_id>-<slug>`; this is the common automated path.)
   3. **Most recent PR/MR linked from current branch** — best-effort scan its body for a `Plan: #N` reference (`gh pr view --json body` / `glab mr view`).
   4. **None of the above** — emit: `No Plan issue resolvable. Pass the Plan number: /dod check <N>` and stop.

   If a Plan is resolvable, continue to step 2. If none, fall through to step 1b.

   1b. **Legacy devspec fallback.** If `plan_id` is unresolvable AND `docs/*-devspec.md` exists, drop into the legacy path: skip step 2, set the report header banner `[legacy mode — no Plan issue resolved; using Dev Spec directly]`, jump to step 5 (which loads `dod_load_manifest` against the discovered Dev Spec). This is a transition affordance; remove after one wave-pattern release confirms all active projects have Plan issues.

2. **Load the Plan DoD.** Call `plan_load_dod({ plan_id })`. The MCP tool returns `{ plan_id, title, plan_level_dod[], phases[], devspec_path? }`. Surface error paths cleanly — never as stack traces:
   - `plan_not_found` → `Plan issue #<plan_id> not found in this repo. Verify the number, or pass an explicit one: /dod check <N>.`
   - `plan_body_invalid` → `Plan issue #<plan_id> body is missing required headings: <list>. Fix the body or re-run /issue plan to regenerate the canonical shape.`
   - Any other tool error → surface the message verbatim with the prefix `plan_load_dod failed:` and stop.

3. **Verify Plan-level DoD.** Iterate `plan_level_dod[]`. Each entry is one checkbox in the Plan body's DoD section. For each:
   - If it references a deliverable file/path/CI signal, dispatch to `dod_verify_deliverable`, `dod_run_test_suite`, or `dod_check_coverage` as the existing per-category rules dictate (see step 5 for the rule table).
   - If it is a narrative/manual checkbox (e.g. "All campaign A debrief items resolved"), record it as **manual-attestation pending** — the human approver confirms at step 7.
   - Track per-row V (passing) / X (failing) / O (manual-attestation pending) for the report.

4. **Verify per-Phase DoD.** For each entry in `phases[]`:
   - For each `items[]` row, run the same verification logic as step 3 (mechanical sub-checks via `dod_verify_deliverable` / `dod_run_test_suite` / `dod_check_coverage`; manual-attestation rows tracked as O).
   - Track `Phase <N> — <name>: X/Y verified` for the report header.

5. **Optional Dev Spec fallback for Deliverables Manifest + VRTM.** If `plan_load_dod` returned a non-empty `devspec_path` AND the Plan body's checklist references the Manifest or VRTM (heuristic: any plan-level or phase-level checkbox text contains `Deliverables Manifest`, `VRTM`, `Section 5.A`, `Section 9`, or `Appendix V`), call `dod_load_manifest(devspec_path)` and run the legacy verification:
   - **Docs**: file exists and is non-empty
   - **Code (binary/package)**: file exists; run discovered build if any
   - **Code (CI/CD)**: workflow file exists and last CI run passed (via `gh run list` / `glab ci list`)
   - **Code (build system)**: Makefile/task runner exists and `make test` (or equivalent) passes
   - **Test (results)**: results file exists (e.g. `reports/junit.xml`) with passing counts — call `dod_run_test_suite()` if missing and regenerable
   - **Test (coverage)**: `dod_check_coverage(path)` — file existence is the gate; percentage is informational
   - **Test (manual procedures)**: document exists and has execution evidence
   - **Trace (VRTM)**: every requirement traced, no `Pending` rows, all `Verified By` populated

   If `devspec_path` is absent OR the Plan body does not reference Manifest/VRTM artifacts, skip this step entirely — the Plan-issue DoD is the authoritative gate.

   In **legacy mode** (step 1b fallback): this step is the *only* verification — load the manifest, run all categories, treat Section 7 (global DoD) and VRTM as mandatory.

6. **Present the verification report.**
   - **Header:** `Plan #<plan_id> — <title>`, plus optional `[legacy mode — no Plan issue resolved; using Dev Spec directly]` banner. Project / date / branch.
   - **Plan-level DoD:** `Plan-level DoD: X/Y verified` with one row per item (V / X / O).
   - **Per-Phase DoD:** for each phase, `Phase <N> — <name>: X/Y` with rows.
   - **Optional Deliverables Manifest:** `Deliverables Manifest: X/Y verified` (only if step 5 ran).
   - **Optional VRTM:** `VRTM: X/Y` (only if step 5 ran).
   - **Final line:** `RESULT: READY` or `RESULT: NOT READY -- N items failing`.

7. **Approval flow.** All pass → "Project DoD verified. Approve to close? (yes/no)". Failures → "N items failing. Approve anyway, or fix first? (yes/no/fix)". Manual-attestation rows (O) require explicit confirmation in this step ("Confirmed: <row text>? (yes/no)") before READY can be declared. On **yes**, if `.sdlc/` exists run `campaign-status stage-review dod` and suggest closing the Plan issue. On **fix**, list each failing item with a specific, actionable remediation (file path / command / Plan-body checkbox / Dev Spec section). On **no**, "Deferred. Re-run `/dod` when ready."

## Non-Negotiables

- **The Plan issue body is the source of truth.** Verify against the parsed `plan_level_dod` + `phases[].items[]`, not against the Dev Spec, except in the explicit step-5 fallback or step-1b legacy mode.
- **Mechanical verification only** — file exists or it does not, tests pass or they do not. No "looks good enough" judgments. Manual-attestation rows are surfaced as O and confirmed by the human, never auto-passed.
- **Error paths are clean.** `plan_not_found` and `plan_body_invalid` produce one-line actionable messages, never stack traces. Any other tool error is prefixed `plan_load_dod failed:` with the tool's verbatim message.
- **Legacy fallback is opt-in by absence.** Only triggers when no Plan resolvable AND a Dev Spec exists. Banner is mandatory in that path. Removal target: one wave-pattern release after this skill ships.
- **VRTM completeness is mandatory when present** — `Pending` rows are failures. No exceptions. Applies to step-5 supplemental run and step-1b legacy mode alike.
- **Human approval is required** — even on all-green, present the report and wait. Manual-attestation rows require explicit per-row confirmation.
- **Remediation is actionable** — specific file paths, commands, Plan-body checkbox text, or Dev Spec sections; not vague advice.
