---
name: scpmmr
description: Commit, push, open + precheck the PR/MR, then merge it — /scpmr then /mmr; typed after a precheck STOP it is the merge call
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-scpmmr does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-scpmmr
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Commit, Push, Precheck, Merge

`/scpmr`, then `/mmr` (#1235). The underlying skills use Origin Operations MCP tools: `/scpmr` uses `pr_list` + `pr_create` (draft) and `/precheck`; `/mmr` uses `pr_status` + `pr_wait_ci` + `pr_merge` + `ci_wait_run`.

## Two ways in

- **BJ types it after a precheck STOP.** The PR/MR is already prechecked and ready, so `/scpmmr` **is the merge call**. Skip straight to `/mmr`. Do not re-run `/scp` or `/precheck`; nothing changed. (If HEAD moved since the pass, `/mmr` runs `/precheck rearm` itself.)
- **Typed with nothing prechecked yet** (work done, nothing pushed or no ready PR): run `/scpmr`. Its `/precheck` STOPs for the merge call as usual, **unless** an exception applies (kahuna sandbox, armed autochain, standing merge grant, lead-agent grant), in which case `/precheck` invokes `/mmr` itself. **`/scpmmr` typed *before* a precheck is not approval of a merge nobody has seen.** It means "take it all the way to the gate."

## Procedure

1. `/scpmr`, unless the PR/MR is already ready with a `precheck` pass on its head (see above).
2. `/mmr`, on BJ's merge call. **Skip this step if `/precheck` already ran `/mmr` under an exception:** check `pr_status` first, and if the PR/MR is `merged`, go to step 3. Running `/mmr` again on a merged PR/MR would STOP on `state != open` and report a failure after a merge that succeeded. `/mmr` merges directly via `pr_merge` (the fleet is queue-less). Post-merge, `ci_wait_run(ref: <the actual merge target — main OR kahuna/<N>-<slug> on the sandbox path, never a hardcoded literal>, expected_sha: <merge_commit_sha from pr_merge>, timeout_sec: 1800)` confirms the target-branch pipeline lands clean. **Always pass `expected_sha`**: without it, a propagation race can silently grade a previous merge's already-completed run instead of the one that just landed (`mcp-server-sdlc#523`). **`ref` must track the real target, not a literal `"main"`**: on the sandbox path the merge lands on `kahuna/*`, and pairing a hardcoded `main` with `expected_sha` turns a clean merge into a spurious failure with no human present to catch it. See `/mmr`'s step 8 for the full mechanism.
3. `vox` announcement (best-effort): identity from `<project_root>/.claude/agent-identity.json` (fallback: `/tmp/claude-agent-<md5>.json`), then name/team/project/issue/PR/"merged into main"

## Important

- Convenience shortcut — does NOT skip any safety checks
- The merge needs a `precheck` pass on the PR/MR's head **and** BJ's merge call (or an exception)
- CI verification before merge is handled by `pr_wait_ci` inside `/mmr`
- Any step failure → STOP and report, do NOT continue to the next step

**Sandbox invocation path.** On a KAHUNA sandbox (base ref matches `^kahuna/[0-9]+-`), `/precheck` prints the sentinel `[AUTO-APPROVED: kahuna sandbox]` and invokes `/mmr` itself after a pass. The sentinel is the approval signal; there is no separate human STOP for a PR/MR into the sandbox. The merge lands the branch onto the per-wave integration branch (`kahuna/<N>-<slug>`), not `main`; the wave Orchestrator handles the eventual `main` merge at the wave gate. See `skills/precheck/SKILL.md` and Dev Spec §5.2.1.
