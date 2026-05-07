# Welcome to Project DoD Verification

This skill verifies that a project has met its **Definition of Done** by mechanically checking every checkbox in the **Plan issue body's DoD section** — the canonical, frozen tracking artifact for a wave-pattern campaign (per the Plan/Phase/Epic taxonomy lock, `docs/phase-epic-taxonomy-devspec.md` §5.1). The Dev Spec is engineering working notes; the Plan issue is the contract.

## What It Does

`/dod` resolves the Plan issue, calls the `plan_load_dod` MCP tool, and verifies each row:

- **Plan-level DoD** -- the project-wide checkboxes in the Plan body's `## Definition of Done` section
- **Per-Phase DoD** -- the checkboxes nested under each phase heading in the Plan body
- **Optional: Deliverables Manifest + VRTM** -- when the Plan's References point at a Dev Spec and the DoD checklist references Section 5.A / Section 9 / Appendix V, `/dod` falls through to the Dev Spec for those mechanical checks

It surfaces errors cleanly — `plan_not_found`, `plan_body_invalid` — never as stack traces.

## Plan-id Resolution Order

When you run `/dod` (or `/dod check`) without an argument, the skill tries to resolve the Plan number from context, in order:

1. **Explicit argument** -- `/dod check 499` always wins
2. **Current branch matches `kahuna/(\d+)-`** -- the standard wave-pattern KAHUNA flight branch shape; the captured digits become the `plan_id`
3. **Most recent PR/MR on this branch** -- best-effort scan of its body for a `Plan: #N` reference
4. **Nothing matches** -- the skill stops with: `No Plan issue resolvable. Pass the Plan number: /dod check <N>`

## Legacy Devspec Fallback

If no Plan issue is resolvable **and** `docs/*-devspec.md` exists, `/dod` falls through to the pre-taxonomy behavior: load the Dev Spec, verify the Deliverables Manifest, Section 7 global DoD, and VRTM directly. The report header carries the banner `[legacy mode — no Plan issue resolved; using Dev Spec directly]` so the operator always knows which gate ran. This is a transition affordance and will be removed after one wave-pattern release confirms all active projects have Plan issues.

## The Verification Report

After checking everything, `/dod` presents a formatted report:

```
Plan #499 — Plan/Phase/Epic taxonomy rework

Plan-level DoD: 6/7 verified
  V All Stories merged via wave-pattern
  V phases-waves.json schema migration committed
  X Dev Spec §8 backfilled with new Story numbers
  ...

Phase 1 — Taxonomy lock + tooling: 4/4
  V /issue plan emits canonical body shape
  V plan_load_dod MCP tool shipped
  ...

Phase 2 — Skill bodies adopt new shape: 3/4
  V /devspec walks Plan issue
  X /dod reads Plan-issue DoD instead of devspec
  ...

Deliverables Manifest: 7/9 verified  (optional, when devspec_path is followed)
  V DM-01  README.md                    README.md exists (847 lines)
  X DM-04  Automated test suite         reports/junit.xml missing
  O DM-09  User manual                  N/A -- CLI-only tool

VRTM: 12/12

RESULT: NOT READY -- 2 items failing
```

- **V** = verified (passing)
- **X** = failing
- **O** = manual-attestation pending (human confirms at the approval step) or N/A (opted out with rationale, in the Manifest)

## Approval Flow

- If everything passes: "Approve to close the project?"
- If failures exist: "Approve anyway, or fix first?"
- For each `O` (manual-attestation) row, an explicit per-row confirmation is required before READY can be declared
- On "fix": lists each failure with a specific remediation step (file path / command / Plan-body checkbox text / Dev Spec section)

## Where It Fits in the Pipeline

`/dod` is the **final gate** in the SDLC pipeline:

```
/ddd --> /devspec --> /prepwaves --> /nextwave (or /wavemachine) --> /dod
```

After `/dod` approval, the project is done. If `campaign-status` is active, it transitions the campaign to the DoD review stage and suggests closing the Plan issue.

## Commands

- **`/dod`** -- Run the full DoD verification, resolving the Plan from context
- **`/dod check`** -- Same as above (explicit subcommand form)
- **`/dod check <N>`** -- Run against Plan issue `#N` explicitly

**Ready to verify?** Run `/dod` to check your project's Definition of Done.
