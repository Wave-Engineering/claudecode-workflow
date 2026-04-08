# Welcome to Project DoD Verification

This skill verifies that a project has met its **Definition of Done** by mechanically checking every deliverable in the Dev Spec's Deliverables Manifest (Section 5.A).

## What It Does

`/dod` reads your Dev Spec, finds the Deliverables Manifest, and checks each row:

- **Docs** -- File exists and is non-empty
- **Code** -- File exists, build succeeds, CI passes
- **Test** -- Results exist, coverage report present, manual procedures executed
- **Trace (VRTM)** -- Every requirement is traced, no "Pending" rows

It also checks the Global Definition of Done (Section 7) and VRTM completeness (Section 9, Appendix V).

## The Verification Report

After checking everything, `/dod` presents a formatted report:

```
Deliverables Manifest: 7/9 verified

  V DM-01  README.md                    README.md exists (847 lines)
  V DM-02  Unified build system         Makefile exists, make test passes
  X DM-04  Automated test suite         reports/junit.xml missing
  O DM-09  User manual                  N/A -- CLI-only tool
  ...

RESULT: NOT READY -- 2 items failing
```

- **V** = verified (passing)
- **X** = failing
- **O** = N/A (opted out with rationale)

## Approval Flow

- If everything passes: "Approve to close the project?"
- If failures exist: "Approve anyway, or fix first?"
- On "fix": lists each failure with a specific remediation step

## Where It Fits in the Pipeline

`/dod` is the **final gate** in the SDLC pipeline:

```
/ddd --> /devspec --> /prepwaves --> /nextwave --> /dod
```

After `/dod` approval, the project is done. If `campaign-status` is active, it transitions the campaign to the DoD review stage.

## Commands

- **`/dod`** -- Run the full DoD verification (same as `/dod check`)
- **`/dod check`** -- Explicit check subcommand

**Ready to verify?** Run `/dod` to check your project's Definition of Done.
