---
name: precheck
description: Pre-commit gate — verify branch/issue, run code-reviewer, present checklist, then stop and wait for approval
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-precheck does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-precheck
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Pre-Commit Gate

Mandatory verification before any commit. Checks compliance, runs code review, presents the checklist, and **stops**. Does NOT commit/push/PR.

**IMPORTANT: When implementation is done, run this skill IMMEDIATELY. Do NOT ask "shall I run precheck?" or "ready for precheck?" — just start it. The checklist at the end is the approval gate; asking permission to START is a redundant pause.**

## Tools Used
- `mcp__sdlc-server__ibm` — branch/issue workflow (no protected branch; branch linked to an open issue)
- `mcp__sdlc-server__branch_guard` — resolve the live default branch and verify the current branch's base is it (protected-gated, `kahuna/*`-exempt)
- `mcp__sdlc-server__spec_validate_structure` — linked issue has Changes / Tests / AC
- `mcp__disc-server__disc_send` — post approval request to `#precheck` (channel `1491195025198157834`)

## Procedure

### Step 1 — IBM gate (serial, hard stop)
Call `mcp__sdlc-server__ibm` directly (no sub-agent — it's one MCP call). If it fails, stop immediately and do not proceed.

### Step 1.5 — Base-branch gate (serial, hard stop)
Call `mcp__sdlc-server__branch_guard({ role: "base" })`. It resolves the **live** default branch from the git host (never a cached `.claude-project.md` value or `origin/HEAD` — both go stale silently) and checks the branch your work is based on. Interpret the envelope:
- `verdict == "pass"` → continue.
- `verdict == "warn"` → **STOP** and surface `reason` verbatim. Your branch's base is a **protected** branch that is neither the live default nor a `kahuna/*` sandbox — almost always a stale or renamed base (the exact failure this gate exists to catch). Rebase onto the live default, or confirm the base is intentional, before proceeding.
- `{ ok: false }` or any error envelope → **STOP** and surface the error; do not silently continue past a gate that failed to run.

**Protected-gated:** silent when the base is unprotected (feature→feature, stacked branches) or a `kahuna/*` integration branch. Only a protected, non-default, non-sandbox base trips it.

**Scope (known limit):** reliable once a PR exists (it reads the PR's base). Before a PR exists, git can't distinguish "based on a stale default" from "based on the current default, now a bit behind" without false positives, so the pre-PR case is intentionally not gated here — the PR-create and merge target guards catch the wrong-target case. (#888)

**Transition fallback** — *only* until `branch_guard` is deployed on this host's sdlc-server (#465): resolve the live default inline (`gh repo view --json defaultBranchRef -q .defaultBranchRef.name`, or GitLab `glab api "projects/:id" --jq .default_branch`). If an open PR exists, compare its base (`gh pr view --json baseRefName -q .baseRefName`) and STOP if that base is a protected branch that is neither the live default nor matches `^kahuna/[0-9]+-`. Delete this paragraph once `branch_guard` is universal.

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
         Also run: git -C <repo_root> rev-parse HEAD

         Parse the JSON. FIRST report the denominator and the commit, ALWAYS, on one line:
           scanned: <N> manifest(s) at <short-sha>   [list each Target and Type]

         THEN return one of:
           PASS — one or more manifests parsed, zero findings
           NO MANIFESTS — trivy ran and parsed ZERO manifests. This is NOT a pass.
                          Nothing was scanned. Say so; do not report PASS.
           SKIP — trivy not installed
           FINDINGS — list each as: package | CVE | severity | fixed_version (or 'no fix available')
         Do not auto-upgrade anything. Just report."
```

**Report the denominator and the commit before the verdict — never the verdict alone.** Two failures on 2026-07-19 make this non-optional:

- Job C returned `PASS — zero HIGH or CRITICAL` for a repo where trivy parsed **zero manifests**. A pass over an empty denominator is *no scan*, and it is indistinguishable from a clean one. Same shape as the `/mmr` gate in #925: reported fine, did nothing. It had also been masking a real defect for months — a repo whose lockfile was gitignored had therefore *never* been scanned, and the gate's silence and the defect were the same event.
- Two agents both reported `Results=1`, honestly, and disagreed — because they were scanning **different commits**. Denominator-first is necessary and not sufficient: *"how many manifests?"* and *"which commit?"* are two questions, and a local checkout is not the tree that ships. (@strangler)

### A trivy PASS is NOT a dependency clearance for lockfile-based JS/TS projects

**`trivy` parses `bun.lock`, not the installed tree.** It is therefore *structurally* blind to a vulnerable copy nested under a parent — not unlucky, blind by construction. Reproduced independently on four separate trees: **0 HIGH/CRITICAL reported on a tree carrying a known-vulnerable nested `ajv/fast-uri@3.1.0`** that a filesystem probe found immediately.

This matters because it is exactly how a dependency bump becomes cosmetic. **A version outside a parent's declared range does not upgrade that parent — it makes the parent keep a private nested copy.** The top-level lockfile entry reads fixed, trivy agrees, and the CVE is live. A real bump nearly shipped this way; it was caught by reading the nested entry, not by scanning.

**So for any change touching dependencies, trivy is necessary and not sufficient.** Also run:

```bash
cd "$REPO"                      # RELATIVE — an absolute path breaks path-based probes
find node_modules -name package.json | while IFS= read -r f; do
  python3 -c "
import json
try: d=json.load(open('$f'))
except Exception: raise SystemExit
if d.get('name')=='<pkg>': print(d.get('version'), '$f')"
done
# PASS = exactly one line per target, at the pinned version
```

**Read `name` from the file. Never infer identity from the path.** Four path-based variants were tried on 2026-07-19 and every one failed, in both directions:

| variant | failure |
|---|---|
| absolute path | `*/node_modules/` matches the absolute prefix → healthy top-level copy reads as nested (**false positive**) |
| "denominator must be > 0" | bun hoists to a flat tree; zero nested entries is the *correct* answer (**false alarm**) |
| `-path "*pkg*"` | matches `package.json` files *inside* a package — `fast-uri/benchmark/package.json` declares `version 1.0.0` (**false positive**) |
| `-maxdepth 3` | a nested copy's file sits at **depth 5**; the cap **cannot reach the class being searched for** (**FALSE NEGATIVE**) |

Reading `name` is immune to all four **because it never asks the path a question about identity.**

**Validate the probe before trusting a zero.** Plant a copy at depth 5 (`node_modules/<pkg>/node_modules/<target>/package.json` with `name` + `version`), confirm the probe finds it, remove it, confirm the clean tree reads one line. **A probe that has only run on a clean tree has not been tested** — and a probe run on a *flat* tree cannot detect a nested-copy bug at all, which is how the `-maxdepth` variant was reported "verified".

**Durability, with a caveat that produced a false pass.** Deleting the lockfile and reinstalling from the manifest is the right instinct, but a zero afterward can mean the **dependency chain disappeared** rather than the pin held — a parent bumping to a version that drops the vulnerable package entirely. *That zero is chain-absence wearing a pass's clothes.* Force the chain present and A/B the override instead: without → vulnerable version, with → pinned version.

**Why this is written out rather than summarised:** five verification instruments were wrong on 2026-07-19 and **not one was caught by review** — every one by someone running it against a case that could fail. The instrument is a claim, and claims get tested.

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
Collect results from all four jobs, assemble the checklist (see below), then **notify BJ**: `disc_send` to `#precheck`, **then `vox`** — **ALWAYS do both**. If `disc_send` fails (MCP unavailable, network), still do `vox`.

### Step 5 — Sandbox detection + gate
Run **sandbox-context detection** (see "Sandbox Auto-Approval" below): if the current branch's base ref matches `^kahuna/[0-9]+-`, emit the sentinel line `[AUTO-APPROVED: kahuna sandbox]` and invoke `/scpmmr` immediately with no wait; otherwise **STOP.** Wait for `/scp`/`/scpmr`/`/scpmmr`/affirmative. Negative/rework → return to work. Never bypass the STOP on notification failure in non-sandbox contexts.

## Dependency Vulnerability Scan
Delegated to Job C (Haiku sub-agent) in the parallel batch. Interpret the result as:
- **PASS** → checklist item passes.
- **SKIP** → emit `[SKIPPED — trivy not installed]` on the checklist. Do not fail the gate.
- **FINDINGS** → report each finding (package, CVE, severity, fixed version if any) as a deferred checklist item. Do NOT auto-upgrade dependencies — the user approves the codebase state at the gate. Do NOT block the gate on vulnerabilities with no available fix.

## The Checklist (full every time; a checkmark means VERIFIED by reading the codebase)
**Context:** Project | Issue #N — title | Branch `feature/N-...` → `<live default>`
- [ ] Implementation (AC verified) — [ ] TODOs (searched+addressed) — [ ] Docs (reviewed+updated) — [ ] Validation (actually ran)
- [ ] New tests (cover new code) — [ ] All tests pass (entire suite) — [ ] Scripts executed (linting is NOT testing) — [ ] Code review (high+ fixed)
- [ ] Dependencies (trivy: 0 HIGH/CRITICAL, or exceptions documented, or [SKIPPED])

**Summary:** `[codebase]` `[docs]` `[tests]` `[config]`. **Findings:** `[fixed]` / `[deferred]` / "(none)".

## The Notification (Discord + vox)
Resolve identity from `<project_root>/.claude/agent-identity.json`; fall back to `/tmp/claude-agent-<md5>.json` if absent (transition window). Use it for both the Discord post and the vox announcement.

**Important:** Do NOT prefix the Discord post with `@all`, `@<Dev-Team>`, or any `@`-mention. This post is for BJ only (human-facing). The discord-watcher filters by `@`-addressing, so an `@`-prefix would fan the precheck gate notice out to every listening agent in the fleet. Unaddressed is intentional.

**`disc_send` to `#precheck` (`1491195025198157834`) — exact body shape:**
```
⚠️ **Precheck gate — awaiting approval**

**Project:** <project-name>
**Issue:** #<N> — <title>
**Branch:** `<type>/<N>-<slug>` → `<live default>`
**Checklist:** `[codebase]` `[docs]` `[tests]` `[config]`
**Findings:** <fixed> / <deferred> / (none)

Ready for `/scp` / `/scpmr` / `/scpmmr` or rework.

— **<dev-name>** <dev-avatar> (<dev-team>)
```

**`vox`:** same info, conversational, 1-2 sentences, ending with "Ready for your call."

**FRONT-LOAD the speaker identity — open with `"<Dev-Name> here."`** (#952). Synthesis runs at ~1x realtime, so a long body can exhaust a caller's `timeout` budget *during synthesis*, and whatever is still playing gets cut — the tail first. `vox` appends its own `. This is <name>.` sign-off, but the sign-off is the tail, so it is exactly what a truncation drops. Leading with the name means the identity is spoken first and survives a cut. Example: `vox "<Dev-Name> here. Precheck gate ready on #<N>. <one sentence>. Ready for your call."` — do NOT open with "Precheck gate ready on #<N>…" and rely on the appended sign-off to identify you; that identity is the first thing lost. `vox` playback is non-blocking by default (it detaches, so a caller timeout bounds synthesis, not playback), so no flag is needed — just invoke `vox` normally.

## Sandbox Auto-Approval (KAHUNA Flight Agents)

Flight Agents working inside a KAHUNA sandbox push to a per-wave integration branch (`kahuna/<N>-<slug>`), not to `main`. In that context the human gate is a redundant pause — the wave Orchestrator has already decided the wave runs autonomously and reviews aggregated results at the wave gate, not per-flight. The full checklist (validation, code-reviewer, trivy) and Discord/`vox` notifications still run; only the STOP-and-wait step is bypassed.

**Why this exists (narrative).** A wave can dispatch dozens of Flight Agents in parallel; a per-flight human STOP would serialise the wave back to one-at-a-time and defeat the orchestration. The Orchestrator's contract with the human is "I will surface the *wave* result, not every flight." Flight Agents inside the sandbox honour that contract by completing their own quality bar (the full checklist) and then auto-progressing; they never bypass quality, only the human pause. Outside the sandbox — i.e. an agent operating directly against `main` — the original rule applies in full and the STOP is non-negotiable. See Dev Spec §5.2.1 for the authoritative statement; the mechanical detection (regex `^kahuna/[0-9]+-`, sentinel `[AUTO-APPROVED: kahuna sandbox]`) lives below and in the procedure summary above.

**Platform-specific enforcement prerequisite.** The branch-name regex makes the *decision* to auto-approve, but the *safety* of that decision rests on platform-side configuration that constrains what a Flight Agent can actually push to. The two platforms model this differently — and the asymmetry is load-bearing:

- **GitHub:** branch-protection rules (and rulesets) scope per-branch-pattern. The `kahuna/*` pattern is configured to permit the Flight Agent's auto-merge path while leaving `main`'s protection — required status checks, no force-push, no deletion — intact. Configured per-repo via `gh api` / repo settings; in Wave-Engineering repos this is part of the standard merge-config policy. See `docs/operations/branch-protection-checklist.md`.
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

**Non-bypassable items:** validation, code-reviewer (high+ findings still block), trivy scan, Discord `#precheck` post, `vox` announcement, **and `/mmr`'s CI gate**. These run in full regardless of `sandbox_context`. Only the human-approval STOP is replaced by the sentinel + auto-`/scpmmr`.

The CI gate is listed explicitly because **the kahuna sandbox is not the only path that merges without a human.** Autonomous merging also occurs under **`/wavemachine` in `auto` mode** — its promote node performs the kahuna→protected merge with no human halt (interactive mode routes that same merge *to* a human, so the exposure is mode-specific, not skill-wide) — and under an **armed `godspeed` mandate**, whose gated-action list covers force-push, push-to-protected, terraform/kubectl/helm/docker/systemctl and prod-shaped writes but **not merges**, so an armed agent carries straight through one. In both, once the human approval is gone, the CI gate is the *last* thing between a red build and the protected branch.

*(`/lazyriver` is deliberately **not** in that list. It is a `probe → journal → judge → steer` goal-seek loop that terminates by emitting a plan or an answer — it has no merge path at all. It was named here in an earlier draft and the claim was wrong; naming a skill that cannot merge costs the paragraph its credibility with exactly the reader careful enough to check.)*

That gate was **inert on GitHub** until cc-workflow#925: it blocked only on `has_failures` and merged on any unrecognised summary, and `gh pr checks --json` does not exist on the fleet's `gh 2.45.0`, so the summary was always `none`. **Autonomous merge paths and a non-functioning CI gate were composing into an unguarded merge** — and the more autonomy a mode has, the more completely it was unguarded.

`/mmr` step 3 is now default-deny. Do not weaken it back to a blocklist without re-reading that issue, and treat any *new* autonomous merge path as inheriting this dependency: **removing the human raises the CI gate from a second opinion to the only opinion.**

## Rules
No diff. No commit. No skipping code-reviewer. Honesty over speed — no checking items you haven't verified. **Linting is not testing** — passing lint/typecheck does not mean code works. **`vox` is ALWAYS called** — it is NOT a fallback for disc_send failure. Both notifications happen every time.

## New-Repo Onboarding (Branch-Protection End-to-End Dry-Run)

Out of scope for the per-commit gate, but called out here because this skill is the closest thing to an institutional checklist we have: **when configuring branch protection on a new repo, configuration verification is not enough — you MUST prove the gate end-to-end before any real work lands.** "Configuration exists" is not the same as "configuration works."

Two throwaway PRs, both required:

1. A PR with a **failing** check → assert it is **BLOCKED** from merging (the gate holds).
2. A PR that is **green** → assert it **merges through** (the gate passes good work).

A gate that blocks everything is as broken as one that blocks nothing; only the pair proves it. The full runbook lives in `docs/operations/branch-protection-checklist.md`. Same principle as the runtime smoke test in `mcp-server-sdlc` `validate.sh`: verify behavior, not declarations.
