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

### Step 1 — IBM gate (serial, hard stop)
Call `mcp__sdlc-server__ibm` directly (no sub-agent — it's one MCP call). If it fails, stop immediately and do not proceed.

### Step 2 — Parallel verification batch
After `ibm()` passes, launch all four jobs **in a single message** as parallel Agent calls. Do NOT wait for one before starting the next — they have no data dependencies on each other.

**Job A — Spec validation** `model: haiku`
```
subagent_type: general-purpose
model: haiku
prompt: "Run mcp__sdlc-server__spec_validate_structure for issue #<N> in repo <repo>.
         Return: PASS or FAIL, and if FAIL, list exactly which required H2 sections are missing."
```

**Job B — Repo validation** `model: haiku`
```
subagent_type: general-purpose
model: haiku
prompt: "Run the project's validation and test tooling in <repo_root>.
         First: read .claude-project.md if it exists — use whatever toolchain commands it declares.
         If absent, probe in order: ./scripts/ci/validate.sh, ./scripts/ci/test.sh,
         make test, python3 -m pytest tests/, npm test.
         Run whatever exists. Return: PASS or FAIL, and any error output verbatim (truncated to 50 lines max)."
```

**Job C — Dependency vulnerability scan** `model: haiku`
```
subagent_type: general-purpose
model: haiku
prompt: "Run: trivy fs --scanners vuln --severity HIGH,CRITICAL --format json --quiet <repo_root>
         Parse the JSON. Return one of:
           PASS — zero findings
           SKIP — trivy not installed
           FINDINGS — list each as: package | CVE | severity | fixed_version (or 'no fix available')
         Do not auto-upgrade anything. Just report."
```

**Job D — Code review** `model: opus`
```
subagent_type: feature-dev:code-reviewer
model: opus
prompt: "Review all files changed on the current branch vs main in <repo_root>.
         Use confidence-based filtering — report only issues you are genuinely confident matter.
         Categorize findings as: critical / important / minor.
         Return a structured list; if none, say 'No findings'."
```

### Step 3 — Fix high+ findings (serial)
Wait for all four jobs to return. If Job D (code-reviewer) returned critical or important findings, fix them now before proceeding. Re-run Job D if the fixes were non-trivial. Haiku job failures (B or C) block the checklist item but do not block the gate unless validation itself fails.

### Step 4 — Assemble checklist and notify
Collect results from all four jobs, assemble the checklist (see below), then **notify BJ**: `disc_send` to `#precheck`, **then `vox`** — **ALWAYS do both**. If `disc_send` fails (MCP unavailable, network), still do `vox`. Capture the `vox` exit code and log a `vox_invocation_failed` event to `mcp.jsonl` if non-zero — see the instrumented pattern in **The Notification** below. Best-effort: vox failure does NOT block the gate.

### Step 5 — Sandbox detection + gate
Run **sandbox-context detection** (see "Sandbox Auto-Approval" below): if the current branch's base ref matches `^kahuna/[0-9]+-`, emit the sentinel line `[AUTO-APPROVED: kahuna sandbox]` and invoke `/scpmmr` immediately with no wait; otherwise **STOP.** Wait for `/scp`/`/scpmr`/`/scpmmr`/affirmative. Negative/rework → return to work. Never bypass the STOP on notification failure in non-sandbox contexts.

## Dependency Vulnerability Scan
Delegated to Job C (Haiku sub-agent) in the parallel batch. Interpret the result as:
- **PASS** → checklist item passes.
- **SKIP** → emit `[SKIPPED — trivy not installed]` on the checklist. Do not fail the gate.
- **FINDINGS** → report each finding (package, CVE, severity, fixed version if any) as a deferred checklist item. Do NOT auto-upgrade dependencies — the user approves the codebase state at the gate. Do NOT block the gate on vulnerabilities with no available fix.

## The Checklist (full every time; a checkmark means VERIFIED by reading the codebase)
**Context:** Project | Issue #N — title | Branch `feature/N-...` → `main`
- [ ] Implementation (AC verified) — [ ] TODOs (searched+addressed) — [ ] Docs (reviewed+updated) — [ ] Validation (actually ran)
- [ ] New tests (cover new code) — [ ] All tests pass (entire suite) — [ ] Scripts executed (linting is NOT testing) — [ ] Code review (high+ fixed)
- [ ] Dependencies (trivy: 0 HIGH/CRITICAL, or exceptions documented, or [SKIPPED])

**Summary:** `[codebase]` `[docs]` `[tests]` `[config]`. **Findings:** `[fixed]` / `[deferred]` / "(none)".

**Notification status line** (append to checklist after notifications fire):
- vox success: `vox: ✅ fired`
- vox failure: `vox: ⚠️ failed (rc=N — see mcp.jsonl)`

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

**Instrumented vox invocation (canonical pattern — do NOT use `|| true`):**

Capture `vox`'s exit code and stderr; on non-zero, emit a structured `vox_invocation_failed` event to `mcp.jsonl`. The gate stays best-effort (no block on vox failure) — we just stop hiding it.

```bash
_vox_out=$(vox "<announcement>" 2>&1)
_vox_rc=$?
if [[ $_vox_rc -ne 0 ]]; then
    mcp-log --server precheck --level warn vox_invocation_failed \
        rc=$_vox_rc \
        err="$(printf '%s' "$_vox_out" | head -c 300)" \
        context="precheck"
fi
```

This catches the failure mode `vox` itself can't catch (vox not on PATH, vox segfault, vox absent entirely). Pairs with `vox`-script-side instrumentation (cc-workflow#551), which catches provider/player failures *inside* a successfully-invoked vox. After both layers land, two distinct events are queryable:

- `vox_invocation_failed` (this layer, from `/precheck`) — vox didn't run at all, or returned non-zero
- `call_failed` (vox-script layer) — vox ran but TTS provider/audio player failed

Reflect the outcome on the checklist via the **Notification status line** described above (`vox: ✅ fired` vs `vox: ⚠️ failed (rc=N — see mcp.jsonl)`).

## Sandbox Auto-Approval (KAHUNA Flight Agents)

Flight Agents working inside a KAHUNA sandbox push to a per-wave integration branch (`kahuna/<N>-<slug>`), not to `main`. In that context the human gate is a redundant pause — the wave Orchestrator has already decided the wave runs autonomously and reviews aggregated results at the wave gate, not per-flight. The full checklist (validation, code-reviewer, trivy) and Discord/`vox` notifications still run; only the STOP-and-wait step is bypassed.

**Why this exists (narrative).** A wave can dispatch dozens of Flight Agents in parallel; a per-flight human STOP would serialise the wave back to one-at-a-time and defeat the orchestration. The Orchestrator's contract with the human is "I will surface the *wave* result, not every flight." Flight Agents inside the sandbox honour that contract by completing their own quality bar (the full checklist) and then auto-progressing; they never bypass quality, only the human pause. Outside the sandbox — i.e. an agent operating directly against `main` — the original rule applies in full and the STOP is non-negotiable. See Dev Spec §5.2.1 for the authoritative statement; the mechanical detection (regex `^kahuna/[0-9]+-`, sentinel `[AUTO-APPROVED: kahuna sandbox]`) lives below and in the procedure summary above.

**Platform-specific enforcement prerequisite.** The branch-name regex makes the *decision* to auto-approve, but the *safety* of that decision rests on platform-side configuration that constrains what a Flight Agent can actually push to. The two platforms model this differently — and the asymmetry is load-bearing:

- **GitHub:** branch-protection rules (and rulesets) scope per-branch-pattern. The `kahuna/*` pattern is configured to permit the Flight Agent's auto-merge path while leaving `main`'s required reviews and merge-queue intact. Configured per-repo via `gh api` / repo settings; in Wave-Engineering repos this is part of the standard merge-config policy.
- **GitLab:** approval rules use `protected_branch_ids` to scope per-protected-branch. The `kahuna/*` branches are first protected via `PUT /projects/:id/protected_branches`, then a `kahuna-zero-approvals` rule with `approvals_required: 0` is created and scoped via `protected_branch_ids: [<kahuna_pattern_id>]`. **`merge_request_approval_settings` MUST NOT be used** — that endpoint is project-wide and would unprotect main. The standard deployment is `gl-settings kahuna-sandbox <project-url>` (the composite operation from `gl-settings#27`); see `docs/kahuna-devspec.md` §5.3.1 and `docs/kahuna-settings-deployment.md`.

**If the platform-specific prerequisite is not in place, the auto-approval is unsafe.** A Flight Agent that sentinels-and-merges against a GitLab project missing the `protected_branch_ids`-scoped approval rule may bypass review controls the operator believed were in force. Detection guidance is below.

**Prerequisite detection (best-effort, non-blocking).** Before emitting the sentinel, the skill SHOULD verify the platform-side config exists. If detection is inconclusive, emit a warning rather than blocking — the wave Orchestrator and operator are the final safety net.

- **GitLab** (project platform == `gitlab`): query `glab api projects/:id/approval_rules` and look for a rule (conventionally named `kahuna-zero-approvals`) with `approvals_required: 0` AND a non-empty `protected_branches` array containing a `kahuna/*` pattern. If absent, emit `[WARNING: kahuna sandbox — GitLab approval rule not detected; verify gl-settings kahuna-sandbox has been applied to this project]` on the checklist before the sentinel. Do NOT block the auto-approval on detection failure (the query may fail for permission reasons unrelated to the actual config); the warning is the contract.
- **GitHub** (project platform == `github`): query `gh api repos/:owner/:repo/rulesets` (or `branches/kahuna/*/protection` as a fallback) and look for a rule scoped to the `kahuna/*` pattern. If absent, emit `[WARNING: kahuna sandbox — GitHub branch-protection ruleset for kahuna/* not detected; verify Wave-Engineering merge-config policy has been applied]`. Same non-blocking semantics as GitLab.
- **Detection unavailable** (platform CLI not installed, no network, API returns 403/404): emit `[SKIPPED — kahuna prerequisite detection unavailable]` and proceed. The wave Orchestrator's project-setup gate is the upstream check.

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
No diff. No commit. No skipping code-reviewer. Honesty over speed — no checking items you haven't verified. **Linting is not testing** — passing lint/typecheck does not mean code works. **`vox` is ALWAYS called** — it is NOT a fallback for disc_send failure. Both notifications happen every time. **Do NOT swallow vox's exit code with `|| true`** — use the instrumented pattern in the Notification section so a non-zero vox emits `vox_invocation_failed` to `mcp.jsonl`. Best-effort still applies (vox failure does not block the gate); we just stop hiding the failure.

## New-Repo Onboarding (Merge Queue End-to-End Dry-Run)

Out of scope for the per-commit gate, but called out here because this skill is the closest thing to an institutional checklist we have: **when enabling GitHub Merge Queue on a new repo, configuration verification is not enough — you MUST open a throwaway PR (e.g., README typo fix) and watch it merge through the queue end-to-end before any real work is enrolled.** "Configuration exists" is not the same as "configuration works." The full runbook lives in `docs/operations/merge-queue-checklist.md`; the most common silent failure is a workflow file missing `merge_group:` in its `on:` block, which leaves the required check never firing and PRs sitting in the queue forever. Same principle as the runtime smoke test in `mcp-server-sdlc` `validate.sh`: verify behavior, not declarations.
