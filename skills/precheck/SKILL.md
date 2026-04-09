---
name: precheck
description: Pre-commit gate — verify branch/issue, run code-reviewer, present checklist, then stop and wait for approval
---

# Pre-Commit Gate

Mandatory verification before any commit. Checks compliance, runs code review, presents the checklist, and **stops**. Does NOT commit/push/PR. Run when implementation is done — do not ask permission. The checklist is the approval gate.

## Tools Used
- `mcp__sdlc-server__ibm` — branch/issue workflow (no protected branch; branch linked to an open issue)
- `mcp__sdlc-server__spec_validate_structure` — linked issue has Changes / Tests / AC
- `mcp__disc-server__disc_send` — post approval request to `#precheck` (channel `1491195025198157834`)

## Procedure
`ibm()` (stop on fail) → `spec_validate_structure(N)` → run repo validation (`validate.sh`/`make test`/`pytest`/`npm test`); fix failures first → launch `feature-dev:code-reviewer` via Agent over all changed files, WAIT, fix high+ findings → present the checklist → **notify BJ** (see "The Notification" below): `disc_send` to `#precheck` **then** `vox` locally — **always do both**. → **STOP.** Wait for `/scp`/`/scpmr`/`/scpmmr`/affirmative. Negative/rework → return to work. If `disc_send` fails (MCP unavailable, network), still do `vox` — still STOP and wait for approval. Never bypass the STOP on notification failure.

## The Checklist (full every time; a checkmark means VERIFIED by reading the codebase)
**Context:** Project | Issue #N — title | Branch `feature/N-...` → `main`
- [ ] Implementation (AC verified) — [ ] TODOs (searched+addressed) — [ ] Docs (reviewed+updated) — [ ] Validation (actually ran)
- [ ] New tests (cover new code) — [ ] All tests pass (entire suite) — [ ] Scripts executed (linting is NOT testing) — [ ] Code review (high+ fixed)

**Summary:** `[codebase]` `[docs]` `[tests]` `[config]`. **Findings:** `[fixed]` / `[deferred]` / "(none)".

## The Notification (Discord + vox)
Resolve identity from `/tmp/claude-agent-<md5>.json` (md5 of project root path). Use it for both the Discord post and the vox announcement.

**Important:** Do NOT prefix the Discord post with `@all`, `@<Dev-Team>`, or any `@`-mention. This post is for BJ only (human-facing). The discord-watcher filters by `@`-addressing, so an `@`-prefix would fan the precheck gate notice out to every listening agent in the fleet. Unaddressed is intentional.

**`disc_send` to `#precheck` (`1491195025198157834`) — exact body shape:**
```
⚠️ **Precheck gate — awaiting approval**

**Project:** <project-name>
**Issue:** #<N> — <title>
**Branch:** `<type>/<N>-<slug>` → `main`
**Checklist:** `[codebase]` `[docs]` `[tests]` `[config]`
**Findings:** <fixed> / <deferred> / (none)

Ready for `/scp` / `/scpmr` / `/scpmmr` or rework.

— **<dev-name>** <dev-avatar> (<dev-team>)
```

**`vox` (ALWAYS — not a fallback):** same info, conversational, 1-2 sentences, ending with "Ready for your call." Vox runs regardless of whether `disc_send` succeeded. Discord is for async visibility; vox is for immediate attention. Both are required.

## Rules
No diff. No commit. No skipping code-reviewer. Honesty over speed — no checking items you haven't verified. **Linting is not testing** — passing lint/typecheck does not mean code works.
