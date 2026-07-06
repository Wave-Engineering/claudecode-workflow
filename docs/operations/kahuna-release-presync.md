# KAHUNA ↔ Release Pre-Sync Runbook (ENG-8 workaround)

Operational runbook for keeping a **persistent per-plan kahuna** (`preserveKahuna: true`) mergeable into its release/protected branch across a multi-wave campaign.

> **⚠️ THE REAL ENGINE FIX IS TRACKED ELSEWHERE — DO NOT PATCH THE ENGINE FOR ENG-8 HERE.**
> This document is a **manual workaround only**. The durable fix (having promotion sync release back into kahuna so the merge-base never falls back to the pre-campaign base) is being developed under a separate work item and is **hands-off** in `claudecode-workflow`. Do **not** add an ENG-8 engine patch to `skills/nextwave/*` in this repo. If you believe the engine needs to change, comment on the tracking issue — don't edit the engine here.

## Why This Document Exists

With `preserveKahuna: true` (a per-plan persistent kahuna, e.g. `kahuna/18-agent-posture`, shared across a plan's waves 1..N), promotion merges **kahuna → release** but **nothing merges release back into kahuna**. After the first wave promotes, the release branch has advanced but kahuna has not caught up. On the *next* wave's promotion the merge-base between kahuna and release falls back to the **pre-campaign base**, so every promotion after the first is evaluated as an **add/add conflict** against release's new commits.

The symptom the operator sees:

- The trust gate's **CI signal returns `no_merge_result_pr`** (the kahuna → release MR cannot produce a clean merge-result pipeline), and
- the wave **HOLDs** on promotion despite sound code.

Discovered in Plan #18 (agent-posture), logged as **ENG-8**.

The mechanism in one line: **kahuna only ever gives to release; it never takes back — so it drifts off release's advancing head, and the second promotion onward conflicts.**

## The Fix: Pre-Sync kahuna With release Before Each Wave

Before starting each wave's flight loop, fast-forward kahuna so it contains **all of release**, taking kahuna's side on any true divergence. Run this in the **target repo clone** (the one the worktrees attach to), with `<release>` = the protected branch (e.g. `main` or `release`) and `<kahuna>` = the persistent per-plan kahuna branch:

```bash
# 1. Refresh local refs for both branches.
git fetch origin <release> <kahuna>

# 2. Check out kahuna and merge release into it, preferring kahuna on conflict.
git checkout <kahuna>
git merge -X ours --no-edit origin/<release>

# 3. SAFETY CHECK (load-bearing): the resulting kahuna tree MUST contain all of release.
#    `-X ours` resolves CONFLICTING hunks in kahuna's favor, but it must NOT drop
#    release-only files/commits. Verify there is nothing in release that is missing
#    from the merged kahuna:
if [ -n "$(git diff --stat origin/<release> HEAD -- 2>/dev/null)" ]; then
  # There ARE differences — confirm every one is a kahuna-side ADDITION, not a
  # release change that got lost. List release commits not yet in kahuna:
  git log --oneline HEAD..origin/<release>
  # Expected: EMPTY. If it lists commits, STOP — kahuna is missing release work;
  # do NOT push. Investigate (see "When the safety check fails" below).
fi

# 4. Push the synced kahuna.
git push origin <kahuna>
```

**Why `-X ours` and not `-X theirs`:** kahuna is the *superset* integration branch — it carries the campaign's in-flight work plus everything already promoted. On a genuine conflict we keep kahuna's resolution (the campaign's intent) while still absorbing release's *non-conflicting* advances. The safety check in step 3 is what guarantees `-X ours` did not silently discard a release-only change — **never skip it.**

**When to run it:** once per wave, **before** the wave's flight loop starts (before any flight branches off kahuna). This keeps kahuna's merge-base with release current, so the wave's eventual kahuna → release promotion is a clean fast-forwardable merge rather than an add/add conflict.

### The safety check, explained

`git log --oneline HEAD..origin/<release>` lists commits reachable from `origin/<release>` but **not** from the merged kahuna `HEAD`. After a correct sync this list is **empty** — kahuna contains all of release. A **non-empty** list means the merge left release commits behind (kahuna is not a superset of release): **do not push.** See below.

## Reactive Unblock: A Promotion MR Already Stuck

If a promotion MR is **already** HOLDing with `no_merge_result_pr` / an add/add conflict (you didn't pre-sync, or release advanced mid-wave), resolve it by making kahuna a **superset of release**, then let the gate re-evaluate:

```bash
git fetch origin <release> <kahuna>
git checkout <kahuna>
git merge -X ours --no-edit origin/<release>     # kahuna wins conflicts; absorb release advances
git log --oneline HEAD..origin/<release>          # SAFETY: must be EMPTY (kahuna ⊇ release)
git push origin <kahuna>
```

Then re-run the wave / re-trigger the gate (`/wavemachine`): the kahuna → release MR now has a current merge-base and its merge-result pipeline runs clean. This is the same operation as the pre-sync — the only difference is you're applying it *reactively* to unblock a stuck MR rather than *proactively* before the wave.

### When the safety check fails

If `git log --oneline HEAD..origin/<release>` is **non-empty** after the merge, kahuna is missing release work — pushing would regress release on the next promotion. Do **not** push. Instead:

1. Inspect the listed commits (`git show <sha>`). These are release changes `-X ours` dropped as conflicting.
2. Re-merge **without** the ours bias and resolve each conflict by hand so both sides' intent survives:
   ```bash
   git merge --abort
   git merge --no-edit origin/<release>   # resolve conflicts manually, preserving release's changes
   git log --oneline HEAD..origin/<release>   # re-verify: now EMPTY
   git push origin <kahuna>
   ```
3. If the conflict is genuinely non-mechanical (semantic divergence between the campaign and a teammate's landed change), escalate — this is the integration question the gate exists to surface, not something to force.

## Checklist

- [ ] Ran the pre-sync (`fetch → checkout kahuna → merge -X ours release → safety check → push`) **before** the wave started.
- [ ] The safety check `git log --oneline HEAD..origin/<release>` was **empty** before pushing.
- [ ] Confirmed the trust gate's CI signal no longer returns `no_merge_result_pr`.
- [ ] Did **not** add any ENG-8 engine patch to `skills/nextwave/*` (the real fix is tracked elsewhere).

## Pointers

- **KAHUNA operator guide:** [`../kahuna-guide.md`](../kahuna-guide.md) — enabling KAHUNA, reading notifications, and the trust-gate failure modes (Procedure C: merging release into kahuna when commutativity goes red is the same shape as this pre-sync).
- **Persistent per-plan kahuna (`preserveKahuna`):** [`../kahuna-guide.md`](../kahuna-guide.md#expected-behavior) and the per-wave engine's kahuna lifecycle section in `../../skills/nextwave/SKILL.md` (#722).
- **Wave-execution architecture:** [`../wavemachine-workflows-migration.md`](../wavemachine-workflows-migration.md) §3/§5 — the per-wave Workflow spine, the campaign loop, and promotion.
