---
name: precheck
description: Pre-commit gate — verify branch/issue, run code-reviewer, present checklist, then stop and wait for approval
---

# Pre-Commit Gate

Mandatory verification before any commit. Checks compliance, runs code review, presents the checklist, and **stops**. Does NOT commit/push/PR.

**IMPORTANT: When implementation is done, run this skill IMMEDIATELY. Do NOT ask "shall I run precheck?" or "ready for precheck?" — just start it. The checklist at the end is the approval gate; asking permission to START is a redundant pause.**

## Tools Used
- `mcp__sdlc-server__ibm` — branch/issue workflow (no protected branch; branch linked to an open issue)
- `mcp__sdlc-server__spec_validate_structure` — linked issue has Changes / Tests / AC
- `mcp__disc-server__disc_send` — post approval request to `#precheck` (channel `1491195025198157834`)

## Procedure
`ibm()` (stop on fail) → `spec_validate_structure(N)` → run repo validation (`validate.sh`/`make test`/`pytest`/`npm test`); fix failures first → **dependency vulnerability scan** (see below) → launch `feature-dev:code-reviewer` via Agent over all changed files, WAIT, fix high+ findings → present the checklist → **notify BJ** (see "The Notification" below): `disc_send` to `#precheck`, **then `vox`** — **ALWAYS do both** → **sandbox-context detection** (see "Sandbox Auto-Approval" below): if the current branch's base ref matches `^kahuna/[0-9]+-`, emit the sentinel line `[AUTO-APPROVED: kahuna sandbox]` and invoke `/scpmmr` immediately with no wait; otherwise **STOP.** Wait for `/scp`/`/scpmr`/`/scpmmr`/affirmative. Negative/rework → return to work. If `disc_send` fails (MCP unavailable, network), still do `vox` — still apply the sandbox-vs-stop logic above. Never bypass the STOP on notification failure in non-sandbox contexts.

## Dependency Vulnerability Scan
Run `trivy fs --scanners vuln --severity HIGH,CRITICAL --format json --quiet .` on the project root. Parse the JSON output (each finding has a `FixedVersion` field — empty string means no fix available).
- **Zero findings** → checklist item passes, move on.
- **Findings exist** → report each finding (package, CVE, severity, fixed version if any) as a deferred checklist item. Do NOT auto-upgrade dependencies — the user approves the codebase state at the gate. Do NOT block the gate on vulnerabilities with no available fix.
- **`trivy` not installed** → skip with a warning on the checklist: `[SKIPPED — trivy not installed]`. Do not fail the gate.

## The Checklist (full every time; a checkmark means VERIFIED by reading the codebase)
**Context:** Project | Issue #N — title | Branch `feature/N-...` → `main`
- [ ] Implementation (AC verified) — [ ] TODOs (searched+addressed) — [ ] Docs (reviewed+updated) — [ ] Validation (actually ran)
- [ ] New tests (cover new code) — [ ] All tests pass (entire suite) — [ ] Scripts executed (linting is NOT testing) — [ ] Code review (high+ fixed)
- [ ] Dependencies (trivy: 0 HIGH/CRITICAL, or exceptions documented, or [SKIPPED])

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

**`vox`:** same info, conversational, 1-2 sentences, ending with "Ready for your call."

## Sandbox Auto-Approval (KAHUNA Flight Agents)

Flight Agents working inside a KAHUNA sandbox push to a per-wave integration branch (`kahuna/<N>-<slug>`), not to `main`. In that context the human gate is a redundant pause — the wave Orchestrator has already decided the wave runs autonomously and reviews aggregated results at the wave gate, not per-flight. The full checklist (validation, code-reviewer, trivy) and Discord/`vox` notifications still run; only the STOP-and-wait step is bypassed.

**Why this exists (narrative).** A wave can dispatch dozens of Flight Agents in parallel; a per-flight human STOP would serialise the wave back to one-at-a-time and defeat the orchestration. The Orchestrator's contract with the human is "I will surface the *wave* result, not every flight." Flight Agents inside the sandbox honour that contract by completing their own quality bar (the full checklist) and then auto-progressing; they never bypass quality, only the human pause. Outside the sandbox — i.e. an agent operating directly against `main` — the original rule applies in full and the STOP is non-negotiable. See Dev Spec §5.2.1 for the authoritative statement; the mechanical detection (regex `^kahuna/[0-9]+-`, sentinel `[AUTO-APPROVED: kahuna sandbox]`) lives below and in the procedure summary above.

**Detection:**
```
current_branch = git rev-parse --abbrev-ref HEAD
base_branch    = parse base ref from most recent PR created by agent (or from context)

if base_branch matches regex "^kahuna/[0-9]+-":
    sandbox_context = true
else:
    sandbox_context = false
```

The detection regex is `^kahuna/[0-9]+-`. Resolve `base_branch` from the most recent PR opened by this agent against the current branch (`gh pr view --json baseRefName`), or from the spawning Orchestrator's context when no PR exists yet.

**Behavior matrix:**
- `sandbox_context == false` (default — feature branch targeting `main`): existing behavior preserved — present checklist, notify, **STOP** and wait for `/scp` / `/scpmr` / `/scpmmr` / affirmative. This is the IT-09 negative case.
- `sandbox_context == true` (Flight Agent on a kahuna sandbox): full checklist runs, full notifications fire, then emit the sentinel line **`[AUTO-APPROVED: kahuna sandbox]`** on stdout, then invoke `/scpmmr` with no wait. The sentinel makes the auto-approval grep-able in transcripts and Discord scrollback.

**Non-bypassable items:** validation, code-reviewer (high+ findings still block), trivy scan, Discord `#precheck` post, `vox` announcement. These run in full regardless of `sandbox_context`. Only the human-approval STOP is replaced by the sentinel + auto-`/scpmmr`.

## Rules
No diff. No commit. No skipping code-reviewer. Honesty over speed — no checking items you haven't verified. **Linting is not testing** — passing lint/typecheck does not mean code works. **`vox` is ALWAYS called** — it is NOT a fallback for disc_send failure. Both notifications happen every time.
