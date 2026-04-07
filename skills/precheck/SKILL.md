---
name: precheck
description: Pre-commit gate — verify branch/issue, run code-reviewer, present checklist, then stop and wait for approval
---

# Pre-Commit Gate

Mandatory verification before any commit. Checks compliance, runs code review, presents the checklist, and **stops**. Does NOT commit/push/PR. Run when implementation is done — do not ask permission. The checklist is the approval gate.

## Tools Used
- `mcp__sdlc-server__ibm` — branch/issue workflow (no protected branch; branch linked to an open issue)
- `mcp__sdlc-server__spec_validate_structure` — linked issue has Changes / Tests / AC

## Procedure
`ibm()` (stop on fail) → `spec_validate_structure(N)` → run repo validation (`validate.sh`/`make test`/`pytest`/`npm test`); fix failures first → launch `feature-dev:code-reviewer` via Agent over all changed files, WAIT, fix high+ findings → present the checklist → `vox` (identity from `/tmp/claude-agent-<md5>.json`; conversational: name/team/project/issue/summary/"Ready for your call") → **STOP.** Wait for `/scp`/`/scpmr`/`/scpmmr`/affirmative. Negative/rework → return to work.

## The Checklist (full every time; a checkmark means VERIFIED by reading the codebase)
**Context:** Project | Issue #N — title | Branch `feature/N-...` → `main`
- [ ] Implementation (AC verified) — [ ] TODOs (searched+addressed) — [ ] Docs (reviewed+updated) — [ ] Validation (actually ran)
- [ ] New tests (cover new code) — [ ] All tests pass (entire suite) — [ ] Scripts executed (linting is NOT testing) — [ ] Code review (high+ fixed)

**Summary:** `[codebase]` `[docs]` `[tests]` `[config]`. **Findings:** `[fixed]` / `[deferred]` / "(none)".

## Rules
No diff. No commit. No skipping code-reviewer. Honesty over speed — no checking items you haven't verified. **Linting is not testing** — passing lint/typecheck does not mean code works.
