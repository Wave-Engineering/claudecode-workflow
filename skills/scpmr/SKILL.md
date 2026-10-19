---
name: scpmr
description: Commit and push, open a draft PR/MR, run /precheck — on a pass the PR/MR is ready for the merge call
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-scpmr does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-scpmr
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Commit, Push, Open PR/MR, Precheck (No Merge)

The PR/MR gate in one command (#1235): `/scp`, then `/precheck`, which opens the draft and on a pass marks it ready. It stops for BJ's merge call. It never merges; that is `/mmr`.

## Tools Used

- `mcp__sdlc-server__pr_list` — does a PR/MR already exist for this branch?
- `mcp__sdlc-server__branch_guard` — validate the base before opening
- `mcp__sdlc-server__pr_create` (`draft: true`) — open the draft

## Procedure

1. **`/scp`**: commit and push, if anything is uncommitted. Free on a working branch.
2. **Open the draft PR/MR**, if none exists (`pr_list({head: "<branch>"})`):
   - **Resolve the base, then validate it.** The base is the **live** default branch (`gh repo view --json defaultBranchRef -q .defaultBranchRef.name` / GitLab `glab api "projects/:id" --jq .default_branch`), unless you are deliberately targeting a non-default branch such as a `kahuna/*` integration branch on a sandbox flight. Call `branch_guard({ role: "target", branch: <that base> })` and on `verdict == "warn"` **STOP**, surfacing `reason`.
   - On `pass`, **mark the issue in review FIRST**, per the lifecycle table (mark when you start a step): GitLab Status → `In Test`, then read it back. On GitHub the linked PR with `Closes #N` is the marker, so there's nothing to set.
   - Then call `pr_create({title, body, base, head, draft: true})`. The title is 72 characters or fewer, in `type(scope): description` form. The body is in the CLAUDE.md PR/MR format: `## Summary`, `## Changes`, `## Linked Issues` with `Closes #N`, `## Test Plan` (what actually ran). Once sdlc#592 ships, `pr_create` also takes the `squash_message`, the exact commit that will land. If `pr_create` fails, put the issue back to `In progress`.
   - A draft needs no precheck: it can't merge, and opening it is what starts CI on repos that run CI only for PRs/MRs.
3. **`/precheck`**: reviews the pushed commits and reads CI. On a pass it posts the `precheck` status and marks the PR/MR **ready**, then STOPs for the merge call (or, under a kahuna, autochain or standing-grant exception, invokes `/mmr` itself).
4. Report the PR/MR URL and its state: ready and waiting for the merge call, or a draft with what failed.

Do NOT merge. That is the distinction from `/scpmmr`.

**Sandbox note.** In KAHUNA sandbox contexts `/precheck` auto-invokes `/mmr` after a pass, because Flight Agents land into the per-wave integration branch and the wave gate, not the flight gate, is where review happens. See `skills/precheck/SKILL.md` and Dev Spec §5.2.1.
