// gate.js — the #687 trust-gate seam helper for per-wave-workflow.js.
//
// Design of record: docs/wavemachine-workflows-migration.md §3.4 (trust gate).
// Seam contract: skills/nextwave/SEAMS.md (#687 — real gate signals via sdlc-server
// (+ plan/worker/reconcile MCP + promote)).
//
// WHY A HELPER MODULE: the workflow script cannot call MCP/CLI directly (§3.3) — every
// real action is an agent() call. This module owns, WITHOUT bloating the loop:
//   1. the four trust-signal agent PROMPTS — each names the REAL sdlc-server tool the
//      signal agent must call (commutativity_verify / ci_wait_run on the MR merge-result
//      pipeline [#452] / code-reviewer on a kahuna worktree [#667] / trivy HIGH,CRITICAL),
//      and the EXACT pass predicate the agent must apply.
//   2. the conservative-fail SIG the loop substitutes when a signal agent ERRORS — the
//      production replacement for the skeleton's always-pass gateSignalStub(): an agent or
//      tool error HOLDs the wave, it NEVER silently PASSes (SEAMS invariant 6).
//   3. the promotion agent PROMPT (the success-exit terminal step): wave_finalize opens the
//      kahuna→integration-base MR, pr_merge lands it on all-green, the kahuna branch is
//      deleted, disposition recorded. CODE ONLY — the loop calls it solely on a live wave's
//      success exit (gated by the human cutover, #691); never during a build.
//
// THE INTEGRATION BASE IS NOT NECESSARILY THE PROTECTED BRANCH (#1052). Every branch name in
// this module was called `protectedBranch` until #1052, and that name was a latent bug: inside a
// campaign a wave integrates onto the CAMPAIGN branch (`campaign/<plan>-<slug>`), and the
// protected branch is not written at all until the whole campaign lands at DoD. Passing a
// non-protected ref in a parameter named `protectedBranch` is how the next wrong-target merge
// gets written, so the parameter is `integrationBase` throughout and the prose says the same.
// Standalone /nextwave still passes the protected branch — that is one value of the parameter,
// not its definition.
//
// DIFF-SCOPING (§3.4): every static signal is scoped to the wave's CHANGED FILES
// (kahuna-vs-integration-base), NEVER the whole tree — otherwise pre-existing baseline debt
// spuriously HOLDs an otherwise-clean wave. Lint/typecheck are NOT a fifth signal; they
// ride INSIDE the CI signal (ci_wait_run runs the project's full gate on the merge result).

import { mergeResultVerdict, directMergeReadSteps, headReadLines, targetReadLines, isMergeSha, ciWaitRefLines, noRunProbeLines, noRunHold, PR_WAIT_CI_PROBE } from './merge-result.js'

// ── Conservative-fail SIG (replaces the always-pass gateSignalStub) ──────────────────
// SEAMS invariant 6: when #687 lands, the per-signal `.catch(() => gateSignalStub(...))`
// fallbacks go away. In production an agent/signal ERROR is not evidence of safety — it is
// the ABSENCE of evidence, and the gate is a trust gate, so absence of evidence = HOLD.
// The loop wraps each signal's `.catch` with this: a failed signal returns passed:false.
export function conservativeFail(signal, err) {
  const msg = err?.message || (typeof err === 'string' ? err : JSON.stringify(err ?? 'unknown error'))
  return {
    signal,
    passed: false, // conservative-fail: an errored signal HOLDs the wave, never PASSes
    detail: `signal ERRORED — conservative-fail (HOLD): ${msg}`,
  }
}

// The TRIVY signal's own schema (cc-workflow#1247): the generic SIG plus the coverage counts, so
// the partial-coverage rule below is applied by CODE, not left to the agent's reading of a prompt.
export const TRIVY_SIG = {
  type: 'object',
  additionalProperties: false,
  required: ['signal', 'passed', 'found', 'ingested', 'unscanned', 'declared', 'scanned_sha', 'kahuna_sha'],
  properties: {
    signal: { type: 'string' },
    passed: { type: 'boolean' },
    detail: { type: 'string' },
    found: { type: 'integer' }, // lockfiles the prescribed find printed, less the prompt's two exclusions
    ingested: { type: 'integer' }, // of those, how many a scan returned at least one package for
    unscanned: { type: 'array', items: { type: 'string' } }, // the rest, by path
    declared: { type: 'boolean' }, // a .no-scannable-dependencies with a reason exists at the repo root
    scanned_sha: { type: 'string' }, // #1206: HEAD of the worktree the scans ran over
    kahuna_sha: { type: 'string' }, // #1206: origin/<kahuna> as fetched; the gate requires the two to match
  },
}

// PARTIAL COVERAGE FAILS (cc-workflow#1247). trivy's pip analyzer reads only a file named exactly
// requirements.txt, so a requirements-dev.txt beside it was counted in the denominator and never
// scanned, and a clean result over the other half read as a PASS. A lock that was not scanned is
// not clean. This never turns a failing signal into a passing one; it only HOLDs one that claims
// a pass over part of its denominator, names a lock it did not scan (an agent can miscount
// ingested; it is far less likely to list a path it never examined), or whose counts cannot be
// squared. A declaration applies only when no lock is found, as in scripts/ci/check-scannable.sh:
// .no-scannable-dependencies says there is nothing scannable, which a found lock contradicts, and
// a stale one must not mask a lock trivy cannot read. So a found-but-unscanned lock HOLDs with or
// without a declaration. A lone bun.lockb (found 1, ingested 0) cannot pass; its remedy is bun.lock.
// The agent reports whether the declaration exists, and the rule is applied here, not in the prompt.
// Every HOLD names the rule that fired and keeps the agent's own detail AFTER it, never in place of
// it: a scan that already failed (trivy missing, a DB pull that did not finish) must keep its cause,
// and must not be relabelled ERRORED. Only a result whose counts cannot be read or squared is an error.
function trivyHold(sig, why) {
  return { ...sig, signal: 'trivy', passed: false, detail: `${why}. ${sig.detail ?? ''}`.trim() }
}

export function trivyCoverage(sig) {
  const { found, ingested } = sig ?? {}
  const unscanned = Array.isArray(sig?.unscanned) ? sig.unscanned : []
  // A lock named unscanned is a found lock, so found 0 beside one is a count that cannot be
  // squared. Since found alone unlocks the declaration, trust the named path over the count.
  if (!Number.isInteger(found) || !Number.isInteger(ingested) || ingested < 0 || ingested > found
    || (found === 0 && unscanned.length > 0)) {
    const own = sig?.detail ? `; agent detail: ${sig.detail}` : ''
    return conservativeFail('trivy', `coverage counts missing or inconsistent (found=${found}, ingested=${ingested}, unscanned=${unscanned.length})${own}`)
  }
  if (found === 0 && sig.declared !== true) {
    return trivyHold(sig, 'NOTHING FOUND (HOLD): no lockfile found and no .no-scannable-dependencies declaration')
  }
  if (found > 0 && ingested === 0) {
    const names = unscanned.length ? unscanned.join(', ') : 'not named'
    return trivyHold(sig, `NOTHING INGESTED (HOLD): 0 of ${found} lockfile(s) ingested; UNSCANNED: ${names}. A declaration applies only when no lock is found`)
  }
  if (ingested > 0 && (ingested < found || unscanned.length > 0)) {
    const names = unscanned.length ? unscanned.join(', ') : 'not named'
    const why = ingested < found
      ? `${ingested} of ${found} lockfile(s) ingested`
      : `counts claim full coverage (${ingested} of ${found}) yet name unscanned lock(s)`
    return trivyHold(sig, `PARTIAL COVERAGE (HOLD): ${why}; UNSCANNED: ${names}`)
  }
  return sig
}

// THE SCAN MUST BE OF THE TREE THE GATE JUDGES (cc-workflow#1206). The scan used to run over the
// operator's checkout, on whatever branch it held, so a clean kahuna could HOLD and, worse, a wave
// that added a vulnerable pin could PASS on a clean trunk checkout. The prompt now stages a detached
// worktree of origin/<kahuna>, and this binds the verdict to it in code: both SHAs must be full git
// object names and equal, or the signal HOLDs. Like trivyCoverage, it keeps the agent's detail after
// the rule and never turns a failing signal into a passing one.
export function trivyTreeBound(sig) {
  const scanned = sig?.scanned_sha
  const kahuna = sig?.kahuna_sha
  if (isMergeSha(scanned) && isMergeSha(kahuna) && scanned === kahuna) return sig
  const show = (v) => (typeof v === 'string' && v ? v : 'missing')
  const why = `TREE NOT BOUND (HOLD): scanned_sha=${show(scanned)} kahuna_sha=${show(kahuna)}; the scan is not proven to be of the kahuna tip`
  return sig && typeof sig === 'object' ? trivyHold(sig, why) : conservativeFail('trivy', why)
}

// THE SCAN MUST BE OF THE HEAD CI GRADED (cc-workflow#1356). trivyTreeBound compares two SHAs that one
// agent read from one local ref, so a fetch that failed and was carried past scans an older kahuna and
// still binds. ciVerdict returns the head the merge-result pipeline was graded on, which another agent
// read from the forge, so the gate compares the two after parallel(): a passing trivy whose kahuna_sha
// is not the CI-graded head HOLDs, and a passing CI with no graded head HOLDs (it binds nothing). Like
// the other binds, it returns a new array and never turns a failing signal into a passing one.
// It finds both signals by label, so a missing label is not a skipped bind: with no `ci` or no `trivy`
// signal there is nothing to bind, and a conservative-fail for each missing one is appended, so the
// gate HOLDs. The workflow forces both labels in code; this is the floor if one is ever lost.
export function bindScanToGradedHead(signals) {
  const ci = signals.find((s) => s?.signal === 'ci')
  const missing = ['ci', 'trivy'].filter((n) => !signals.some((s) => s?.signal === n))
    .map((n) => conservativeFail(n, `no ${n} signal to bind the scan to the graded head`))
  return [...signals.map((s) => {
    if (s === ci && s?.passed && !isMergeSha(s.head)) return conservativeFail('ci', 'CI pass carries no graded head')
    if (s?.signal !== 'trivy' || !s.passed || !ci?.passed || !isMergeSha(ci.head)) return s
    if (s.kahuna_sha === ci.head) return s
    const k8 = typeof s.kahuna_sha === 'string' && s.kahuna_sha ? s.kahuna_sha.slice(0, 8) : 'missing'
    return trivyHold(s, `SCAN NOT OF THE GRADED HEAD (HOLD): CI graded ${ci.head.slice(0, 8)}, trivy scanned ${k8}`)
  }), ...missing]
}

// ── 1. commutativity signal ──────────────────────────────────────────────────────────
// Single-target mode (one changeset = the whole kahuna composed diff): is kahuna safe to
// land on the integration base? pass = verdict ∈ {STRONG, MEDIUM}; every other verdict —
// explicitly PROBE_UNAVAILABLE and ORACLE_REQUIRED (and any timeout sharing their body
// shape) — is conservative-fail (HOLD), per the tool's own contract.
//
// #6 (live-gate finding) — gate-vs-reconcile consistency: the RECONCILE node MAY adjudicate
// an ORACLE_REQUIRED verdict via judgment DURING integration (it has the cross-flight view and
// can run the suite to decide the composed diff is safe). The trust GATE — the UNATTENDED
// auto-promotion decision to land kahuna on the integration base — does NOT: it HOLDs on
// ORACLE_REQUIRED so a human reviews. "Don't auto-promote what the probe can't prove safe." The
// two are not inconsistent — they answer different questions (is this group mergeable now? vs. is
// the whole wave safe to land on the integration base unattended?); the gate is the conservative
// one. This stays equally strict when the base is a campaign branch rather than the protected one
// (#1052): a bad wave integrated into a campaign poisons every later wave built on top of it, and
// unpicking it costs more than the HOLD did — the campaign branch buys the protected branch
// safety, not the gate laxity.
export function commutativitySignalPrompt({ waveId, kahunaBranch, integrationBase, targetRepoDir }) {
  return [
    `Trust-gate COMMUTATIVITY signal for wave ${waveId}.`,
    `Call sdlc-server commutativity_verify in SINGLE-TARGET mode — the KAHUNA composed-diff safety gate:`,
    `  repo_path=${targetRepoDir}`,
    `  base_ref=${integrationBase}`,
    `  changesets=[{ id: "kahuna", head_ref: "${kahunaBranch}" }]`,
    `Apply the pass predicate EXACTLY: passed = (verdict ∈ {STRONG, MEDIUM}). Every other verdict FAILS,`,
    `INCLUDING PROBE_UNAVAILABLE and ORACLE_REQUIRED and any timeout/handler-synthesized body — those are`,
    `CONSERVATIVE-FAIL (the probe could not PROVE the composed diff safe to land unattended, so the gate`,
    `must HOLD for a human), per the tool's documented contract. Do NOT try to adjudicate ORACLE_REQUIRED`,
    `yourself by running the suite — that is the reconcile node's job during integration; the GATE's job is`,
    `to refuse auto-promotion of anything the probe cannot prove safe.`,
    `Do NOT do any other work. Return signal="commutativity", passed (bool), detail (the verdict + 1 line).`,
  ].join('\n')
}

// ── Open the promotion PR (DRAFT) — runs FIRST in the gate, before the signals ─────────
// #5 (live-gate finding, BLOCKING): the CI signal's ci_wait_run on the kahuna→base merge-result
// pipeline returned `no_merge_result_pr` because the promotion PR used to be created AT
// promotion — AFTER the gate. Chicken-and-egg. Fix (reorders §3.4): the gate opens the
// kahuna→base PR as a DRAFT FIRST, so there is a real PR (and its merge-result
// pipeline) for the CI signal to wait on; the gate then decides; on PASS+auto the promote node
// marks it ready and merges THAT SAME PR (it never opens a second one). DRAFT so a green CI
// can't let the platform auto-merge it before the gate has aggregated all four signals.
//
// Idempotent: re-opening an already-open kahuna→base PR returns the existing one (wave_finalize
// is idempotent on the branch pair). opened=false (with a reason) ONLY when the branch/artifacts are
// missing — in which case the gate HOLDs (it cannot prove a wave it can't even PR). Never fabricates.
export function openPromotionPrPrompt({ waveId, kahunaBranch, integrationBase, targetRepo, targetRepoDir, planId }) {
  return [
    `You are the wave GATE PR-OPEN node for wave ${waveId} of ${targetRepo}. Open (idempotently) the`,
    `${kahunaBranch}→${integrationBase} promotion PR/MR as a DRAFT, then return its number. This runs`,
    `BEFORE the trust signals so the CI signal has a real merge-result pipeline to wait on [#5].`,
    `Do NOT merge anything, do NOT mark the PR ready, do NOT run the gate — just open-or-find the draft PR.`,
    ``,
    `1. Open (or return the existing — idempotent) ${kahunaBranch}→${integrationBase} PR via sdlc-server`,
    `   wave_finalize(plan_id=${planId ?? '<the wave plan id>'}, kahuna_branch="${kahunaBranch}",`,
    `   target_branch="${integrationBase}", root="${targetRepoDir}"). The root is LOAD-BEARING (#699 finding`,
    `   #8): wave_finalize defaults to the SESSION's project for both the plan's durable wave-status AND the`,
    `   git branch check — but this wave's plan + the ${kahunaBranch} branch live in the TARGET repo clone`,
    `   ${targetRepoDir}, NOT the session project. Without root it returns kahuna_branch_not_found even though`,
    `   the branch exists on the remote. If it STILL returns kahuna_branch_not_found or no_artifacts, STOP`,
    `   and return opened=false with the reason in notes (the gate will HOLD — do NOT fabricate a PR).`,
    `2. Ensure the PR is a DRAFT (so a green CI cannot auto-merge it before the gate decides): if`,
    `   wave_finalize did not create it as a draft, convert it (gh -R ${targetRepo} pr ready --undo <number>).`,
    `   Re-running on an already-draft PR is a no-op.`,
    ``,
    `Return: opened (true only if a PR exists for the pair), pr_number (integer), pr_ref (URL/ref),`,
    `notes (1-2 sentences; on opened=false include the reason).`,
  ].join('\n')
}

// The PR-open node's structured return (side-effect + the PR identity the later nodes need).
export const OPEN_PR_RESULT = {
  type: 'object',
  additionalProperties: false,
  required: ['opened'],
  properties: {
    opened: { type: 'boolean' }, // a kahuna→integrationBase PR exists for the pair (draft)
    pr_number: { type: 'integer' }, // the CI signal waits on this PR; promote merges it
    pr_ref: { type: 'string' },
    notes: { type: 'string' },
  },
}

// ── 2. CI signal (#452: MR merge-result pipeline, NOT merge-commit branch HEAD) ───────
// ci_wait_run on the kahuna→integrationBase MR — the DRAFT PR the gate's PR-OPEN node already
// opened (#5), passed in by number so this signal never races to "find" it (the old
// `no_merge_result_pr` failure). Lint/typecheck ride INSIDE this signal (the project's full
// gate runs in CI), diff-scoped to the wave's changed files (§3.4).
//
// #1211: the agent returns EVIDENCE (MERGE_RESULT_EVIDENCE), and ciVerdict() below grades it with
// the rule the campaign release gate shares (merge-result.js). The #1035 step 2b this replaces told
// the agent to PASS only when the /merge pipeline's sha EQUALED the MR head. A merged-results
// pipeline runs on an ephemeral merge commit, so that never holds on green (0 of 15 measured): the
// fallback could only HOLD, or pass by an agent ignoring its own rule.
//
// #1302: the wait is a per-repo budget (`CI wait budget` in .claude-project.md), because a repo
// whose cold build outlasts 420s would HOLD every wave. CI still running when the budget runs out
// stays a HOLD. 3600s is the cap; no wait over 1800s has been observed to survive one MCP call.
export const CI_WAIT_DEFAULT_SEC = 420
export const CI_WAIT_MAX_SEC = 3600
export function ciWaitBudget(sec) {
  return Number.isInteger(sec) && sec >= 60 && sec <= CI_WAIT_MAX_SEC ? sec : CI_WAIT_DEFAULT_SEC
}

export function ciSignalPrompt({ waveId, kahunaBranch, integrationBase, targetRepo, prNumber, ciWaitSec }) {
  const waitSec = ciWaitBudget(ciWaitSec)
  const prRef = prNumber != null ? `PR #${prNumber}` : `the open ${kahunaBranch}→${integrationBase} PR/MR`
  const head = (field) => headReadLines({ targetRepo, prNumber, field }).map((l) => `   ${l}`)
  return [
    `Trust-gate CI signal for wave ${waveId}. Report EVIDENCE about the ${kahunaBranch}→${integrationBase}`,
    `MERGE-RESULT pipeline — NOT the merge-commit branch HEAD [sdlc #452]. You gather facts only: the gate`,
    `grades them in code, so do not decide pass or fail yourself.`,
    ``,
    `1. The gate's PR-OPEN node already opened the draft promotion PR: ${prRef} (repo=${targetRepo}).`,
    prNumber != null
      ? `   Use that number directly — do NOT search for it. (If for any reason it is not found, say so in`
      : `   Find it via sdlc-server pr_status / pr_list (or gh -R ${targetRepo}). (If none is found, say so in`,
    `   notes and return wait: {}: with no pipeline to grade, the gate HOLDs.)`,
    `   The CI you report on is the pipeline produced by MERGING kahuna INTO ${integrationBase} (the merge`,
    `   result), not the branch's own latest push.`,
    ...head('head_sha'),
    ...noRunProbeLines({ targetRepo, prNumber }).map((l, i) => (i === 0 ? `2. ${l}` : `   ${l}`)),
    `   Then call sdlc-server ci_wait_run (repo=${targetRepo}) with ref=<below>, require_merge_result=true, pr_number=${prNumber != null ? prNumber : '<the PR number>'},`,
    ...ciWaitRefLines({ prNumber, headBranch: kahunaBranch }).map((l) => `   ${l}`),
    `   AND explicit timeout_sec=${waitSec} + poll_interval_sec=15 (#1035 — do NOT omit them). All are load-bearing:`,
    `     • require_merge_result makes the tool refuse to grade a BRANCH pipeline, a SKIPPED one, or a`,
    `       GitLab DETACHED (refs/merge-requests/N/head) pipeline — none of which validated the merge.`,
    `     • pr_number (#476) is the FRESHNESS anchor. Filtering to merge-result runs is not enough: a GREEN`,
    `       merge-result run for a PREVIOUS commit still sits in the list, and grading it would merge`,
    `       code CI never saw. The tool binds the run to the PR/MR's CURRENT head (GitHub: the PR head`,
    `       SHA; GitLab: the MR's head_pipeline) and HOLDs if it cannot prove freshness.`,
    `     • timeout_sec=${waitSec} + poll_interval_sec=15 (#1035) are the BLEED FIX: these merge-result pipelines`,
    `       finish in 2–5 min, but WITHOUT an explicit timeout the tool rides its ~1800s idle default and`,
    `       burned ~30–57 min/wave (P5W12: 57 min to confirm a 156s pipeline). ${CI_WAIT_DEFAULT_SEC}s is the default; per-project`,
    `       override (\`CI wait budget\` in .claude-project.md).`,
    `   Report its answer as wait, copied as returned (ok, final_status, reason, error, sha, run_id, url). Do not interpret it.`,
    ...directMergeReadSteps({ targetRepo, prNumber, windowSec: waitSec }).map((l, i) => (i === 0 ? `3. ${l}` : `   ${l}`)),
    `   The direct read is NOT a branch/head fallback: only a merge-result pipeline bound to the current`,
    `   head can pass, and the gate checks both in code.`,
    `   The project's lint + typecheck RIDE INSIDE this pipeline, diff-scoped to the wave's changed files`,
    `   (§3.4) — they are not a separate signal; pre-existing baseline debt must NOT fail this signal.`,
    `4. LAST, after step 2 and (if you ran it) step 3: the head again. If it moved, what was graded may`,
    `   be the previous head's pipeline, and the gate HOLDs; do not re-run anything to chase it.`,
    ...head('head_sha_final'),
    ...targetReadLines({ targetRepo, branch: integrationBase, field: 'target_sha' }).map((l) => `   ${l}`),
    ``,
    `Do NOT do any other work. Return: pr_number, pr_ref, head_sha (step 1), probe and wait (step 2); merge_commit`,
    `whenever step 3 had you read one (a GitLab green on a sha that is not the head, or the direct read);`,
    `merge_pipelines ONLY if you ran the direct read; head_sha_final and target_sha (step 4); notes (1-2 sentences).`,
    `Report what you READ. A missing fact holds the wave; it never passes it.`,
  ].join('\n')
}

// ── CI verdict (#1211): the merge-result rule is CODE, as trivyCoverage() is for trivy ─────
// Grades the CI signal's MERGE_RESULT_EVIDENCE with mergeResultVerdict(), the predicate the campaign
// release gate uses, and returns the SIG the gate aggregates. The PR number is the one the gate's
// PR-OPEN node opened, not the agent's: evidence about another PR/MR HOLDs, and the /merge ref the
// direct read is filtered on is always this PR's. A HOLD keeps the agent's notes after the rule,
// so the cause it read is never lost to the verdict.
export function ciVerdict(ev, prNumber) {
  const notes = ev?.notes ? ` | agent: ${String(ev.notes).slice(0, 200)}` : ''
  if (prNumber != null && ev?.pr_number != null && ev.pr_number !== prNumber) {
    return {
      signal: 'ci',
      passed: false,
      detail: `HOLD (none): the evidence is for PR #${ev.pr_number}, but the gate opened PR #${prNumber}${notes}`,
    }
  }
  const v = mergeResultVerdict(prNumber != null ? { ...ev, pr_number: prNumber } : ev)
  const sig = { signal: 'ci', passed: v.pass, detail: `${v.pass ? 'PASS' : 'HOLD'} (${v.path}): ${v.reason}${notes}` }
  // #1356: a pass keeps the head it graded, so the promote merge and the trivy bind can bind to it.
  return v.pass ? { ...sig, head: v.head } : sig
}

// ── Flight CI (#1356, triage #39): a flight lands on the kahuna only green on its own head ─────
// Prime(reconcile) used to open and merge each flight PR with no CI condition at all, so a flight
// whose check-runs had all failed (a billing failure) squash-merged into the kahuna, while a sibling
// pass in the same wave refused: one wave split two ways. This node runs per flight, between the
// workers and reconcile: it pushes the flight branch, opens its PR into the kahuna, and reports what
// ci_wait_run and ci_failed_jobs say. flightCiVerdict() grades that in code, and only a `proceed`
// flight is handed to reconcile, which then merges it pinned to the graded head.
//
// WHY THE ENGINE AND NOT A SERVER REFUSAL: the engine is the only place that can route all three
// outcomes. proceed goes to reconcile; needs_rework goes back to the flight with the reason (#1213);
// blocked holds the wave. A server refusal of pr_merge into kahuna/* could only say no. The head pin
// on the merge itself is the server half (expected_head_sha, mcp-server-sdlc#609).
export const FLIGHT_CI_EVIDENCE = {
  type: 'object',
  additionalProperties: false,
  required: ['issue'],
  properties: {
    issue: { type: 'integer' },
    pr_number: { type: 'integer' },
    pr_ref: { type: 'string' },
    head_sha: { type: 'string' }, // the flight PR's head, read BEFORE ci_wait_run
    head_sha_final: { type: 'string' }, // the flight PR's head, read again after the wait
    target_sha: { type: 'string' }, // the kahuna's tip, read LAST; a merge commit must be built on it
    wait: { type: 'object', additionalProperties: true }, // ci_wait_run's answer, copied as returned
    merge_commit: {
      // GitLab: the commit of a green run whose sha is not the head (an ephemeral merge commit)
      type: 'object',
      additionalProperties: true,
      properties: { sha: { type: 'string' }, parent_ids: { type: 'array', items: { type: 'string' } } },
    },
    failed_jobs: {
      // ci_failed_jobs(run_id)'s list, copied, only when final_status is failure or cancelled
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: true,
        properties: {
          name: { type: 'string' },
          conclusion: { type: 'string' },
          started_at: { type: ['string', 'null'] },
          finished_at: { type: ['string', 'null'] },
          url: { type: 'string' },
        },
      },
    },
    blocked: { type: 'boolean' }, // the push of the flight branch was rejected
    block_reason: { type: 'string' },
    already_integrated: { type: 'boolean' }, // step 0: merging the flight head into the kahuna changes nothing
    integrated_head: { type: 'string' }, // step 0: the sha that was checked
    integrated_exit: { type: 'integer' }, // step 0: the content check's exit code, as printed
    probe: PR_WAIT_CI_PROBE, // step 3: pr_wait_ci's no-run probe, copied as returned (#1357)
    notes: { type: 'string' },
  },
}

export function flightCiPrompt({ waveId, issue, branch, worktree, kahunaBranch, targetRepo, ciWaitSec, flightHead }) {
  const waitSec = ciWaitBudget(ciWaitSec)
  const head = (field) => headReadLines({ targetRepo, field }).map((l) => `   ${l}`)
  const fh = isMergeSha(flightHead) ? flightHead : `$(git -C ${worktree} rev-parse HEAD)`
  return [
    `You are the FLIGHT CI node for issue #${issue}, wave ${waveId} of ${targetRepo}. You publish the flight's`,
    `branch, open its PR into ${kahunaBranch}, and report what CI says about it. You gather facts only: the`,
    `engine grades them in code.`,
    ``,
    `0. FIRST, is this flight already in ${kahunaBranch}? (A resumed wave whose flight merged before the run died.)`,
    `   This tests CONTENT, not ancestry, because a squash merge leaves the flight head out of the kahuna's history:`,
    `     git -C ${worktree} fetch -q origin ${kahunaBranch}; t=$(git -C ${worktree} merge-tree --write-tree origin/${kahunaBranch} ${fh}) && test "$t" = "$(git -C ${worktree} rev-parse origin/${kahunaBranch}^{tree})"; echo "exit=$?"`,
    `   Report the sha you checked as integrated_head and the printed exit code as integrated_exit. If it`,
    `   is 0, set already_integrated=true and STOP: push nothing, open nothing. Otherwise set`,
    `   already_integrated=false and go on.`,
    `1. Push the branch, as a plain push and nothing else: git -C ${worktree} push origin ${branch}`,
    `   If the push is REJECTED (pre-push gate, permissions, a protected-ref guard), STOP: return`,
    `   blocked=true and the rejection text as block_reason. Never push any other ref.`,
    `2. Open the ${branch}→${kahunaBranch} PR with sdlc-server pr_create, NOT as a draft, or find the open`,
    `   one for that branch pair (idempotent: never open a second). Report its number as pr_number.`,
    ...head('head_sha'),
    ...noRunProbeLines({ targetRepo }).map((l, i) => (i === 0 ? `3. ${l}` : `   ${l}`)),
    `   Then call sdlc-server ci_wait_run(repo=${targetRepo}, ref=<below>, require_merge_result=true, pr_number=<n>,`,
    `   timeout_sec=${waitSec}, poll_interval_sec=15).`,
    ...ciWaitRefLines({ headBranch: branch }).map((l) => `   ${l}`),
    `   Report its answer as wait, copied as returned (ok, final_status, reason, error, sha, run_id, url).`,
    `   GitLab only: when wait is a success whose sha is not head_sha, that sha is the merged-results`,
    `   pipeline's ephemeral merge commit. Read it and report it as merge_commit, exactly as read:`,
    `     glab api "projects/<url-encoded ${targetRepo}>/repository/commits/<wait.sha>" | jq '{sha: .id, parent_ids}'`,
    `4. ONLY if wait.final_status is failure or cancelled: call sdlc-server ci_failed_jobs(run_id=<wait.run_id>,`,
    `   repo=${targetRepo}) and report its failed_jobs list as failed_jobs, copied unfiltered.`,
    `5. The head again.`,
    ...head('head_sha_final'),
    `6. LAST: the kahuna's tip.`,
    ...targetReadLines({ targetRepo, branch: kahunaBranch, field: 'target_sha' }).map((l) => `   ${l}`),
    ``,
    `Do NOT merge, do NOT mark anything ready, do NOT judge: the engine grades this in code.`,
    `Return: issue (${issue}), already_integrated + integrated_head + integrated_exit (step 0), pr_number, pr_ref,`,
    `head_sha, probe and wait (step 3), merge_commit (step 3, GitLab only), failed_jobs (step 4 only), head_sha_final, target_sha,`,
    `blocked + block_reason (step 1 only), notes (1-2 sentences). Report what you READ.`,
  ].join('\n')
}

// Grades one flight's FLIGHT_CI_EVIDENCE. The rules, in order: no evidence, a rejected push, or a PR
// head that is not the head the flight returned (read before and after the wait) is BLOCKED; green on
// that head PROCEEDS, where the run's sha is the head itself (GitHub) or a merge commit with parents
// exactly [kahuna tip, head] (a GitLab merged-results run, bound as mergeResultVerdict binds it); a
// probe saying CI never started is BLOCKED with that reason (#1357); a red whose failed jobs all
// really ran is NEEDS_REWORK (the flight's own code); everything else is BLOCKED. The asymmetry is deliberate: a misread code-red becomes a hold, never a
// merge, so the safety property (never merge red) holds whichever way a job is classified.
//
// CODE-RED, exactly: final_status failure (or GitLab's failed), at least one job concluded failure,
// every such job has started_at and finished_at with finished strictly after started, and no job
// carries an infra conclusion. skipped and neutral jobs are ignored: a real test failure usually skips
// the jobs downstream of it, and GitHub's ci_failed_jobs lists those too. A failed job that never
// started, or ended at the instant it started, is the billing/runner-refusal signature (no steps ran):
// it holds the wave, because re-dispatching the flight cannot fix the account.
//
// INTEGRATED (§3.3 resume): a flight whose head's content is already in the kahuna (merging it changes
// the kahuna's tree not at all, which holds after a squash merge too) merged in an earlier run that died
// before persisting. It counts as merged without a PR, because there is none left to grade. That needs
// a flight that says so: an already-present first flight, or a rework flight, which only reaches here at
// a new head (isNoopRework holds the rest). As before #1356, an already-present flight that committed
// nothing at all also reads as merged: §3.3 trusts the worker's resume check. A first flight that said
// implemented with nothing new for the kahuna committed nothing, so it is blocked, never counted.
// Known risk, kept: a new head is not new content, so a rework flight whose "fix" reverts its own
// commit reads as merged too. A net-change guard would refuse the real resume after cleanupMerged has
// removed the merged flight's branch (its recreated worktree carries no net change), so the trust stays.
const FLIGHT_IGNORED_CONCLUSIONS = new Set(['skipped', 'neutral'])
// A flight PR into kahuna/* gets no run at all when the repo's CI triggers only on PRs into main.
const noRunHint = (error) => (/^No CI run found/i.test(String(error))
  ? '; the repo\'s CI must run on PRs into kahuna/* (docs/operations/branch-protection-checklist.md)'
  : '')
export function flightCiVerdict(ev, issue, flightHead, status, rework = false) {
  const out = (outcome, reason, head = null) => ({ issue, outcome, head, reason })
  if (!ev || typeof ev !== 'object' || ev.issue !== issue) return out('blocked', `no CI evidence for #${issue}`)
  if (ev.already_integrated === true) {
    const resumed = status === 'already-present' || (rework === true && status === 'implemented')
    if (resumed && isMergeSha(flightHead) && ev.integrated_head === flightHead && ev.integrated_exit === 0) {
      return out('integrated', `head ${flightHead.slice(0, 8)} is already in the kahuna (a resumed flight)`, flightHead)
    }
    return out('blocked', 'the flight head is already in the kahuna, but the flight did not report a resume at that head: it committed nothing new')
  }
  if (ev.blocked === true) return out('blocked', `push rejected: ${ev.block_reason || 'no reason given'}`)
  if (!isMergeSha(flightHead) || ev.head_sha !== flightHead || ev.head_sha_final !== flightHead) {
    return out('blocked', 'the PR head is not the head the flight returned')
  }
  // Reconcile merges the flight by its PR number, so a verdict with no PR to merge binds to nothing.
  if (!Number.isInteger(ev.pr_number) || ev.pr_number <= 0) return out('blocked', 'the flight CI evidence carries no PR number')
  const w = ev.wait ?? {}
  const fs = w.final_status
  if (w.ok === true && fs === 'success') {
    // The run must be bound to the flight head. GitHub reports the head itself. A GitLab merged-results
    // run is on an ephemeral merge commit, never the head (merge-result.js, THE BINDING FACT), so that
    // run binds through mergeResultVerdict's rule: parents exactly [kahuna tip, flight head].
    if (w.sha === flightHead) return out('proceed', `CI green on head ${flightHead.slice(0, 8)}`, flightHead)
    const bound = mergeResultVerdict({ ...ev, head_sha: flightHead, head_sha_final: flightHead })
    if (bound.pass) return out('proceed', `CI green on head ${flightHead.slice(0, 8)} (merge commit ${w.sha.slice(0, 8)} onto the kahuna tip)`, flightHead)
    return out('blocked', `a green run not bound to the flight head ${flightHead.slice(0, 8)}: ${bound.reason}`)
  }
  // #1357: CI never started for this head (a criss-cross base, a hard blocker): fail fast, naming why.
  const nr = noRunHold(ev.probe, flightHead)
  if (nr) return out('blocked', nr)
  const jobs = (Array.isArray(ev.failed_jobs) ? ev.failed_jobs : []).filter((j) => !FLIGHT_IGNORED_CONCLUSIONS.has(j?.conclusion))
  const ran = (j) => {
    const s = Date.parse(j?.started_at ?? '')
    const f = Date.parse(j?.finished_at ?? '')
    return Number.isFinite(s) && Number.isFinite(f) && f > s
  }
  const isRed = fs === 'failure' || fs === 'failed'
  if (isRed && jobs.length > 0 && jobs.every((j) => j.conclusion === 'failure' && ran(j))) {
    const names = jobs.map((j) => j.name || '(unnamed)').join(', ')
    return out('needs_rework', `CI red on head ${flightHead.slice(0, 8)}: failed jobs ${names}${w.url ? ` (${w.url})` : ''}`)
  }
  const why = isRed && jobs.length === 0
    ? 'failure with no failed jobs listed'
    : isRed
      ? 'failed jobs never ran (an infra or billing failure, not the flight\'s code)'
      : fs ? `final_status=${fs}` : w.error ? `no verdict: ${String(w.error).slice(0, 160)}${noRunHint(w.error)}` : 'no verdict'
  return out('blocked', `CI could not grade head ${flightHead.slice(0, 8)}: ${why}`)
}

// ── 3. review signal (#847/ENG-5: 2-step stage→review; specialized reviewer PRESERVED) ─
// The review signal is the ONLY gate signal that reads the code diff. It must NOT provision off
// `origin/main`: on repos where main is a bare scaffold and real work lives on a release branch,
// an origin/main worktree reviews an EMPTY tree → passed:false → spurious HOLD on every wave
// (ENG-5). It is therefore a 2-STEP sub-pipeline (assembled at the call site): a Bash-capable
// general-purpose STAGE agent fetches + diffs origin/<integrationBase>...origin/<kahuna> and
// materializes the changed-file set into a durable review workspace; then the SPECIALIZED
// feature-dev:code-reviewer reviews that workspace. Keeping code-reviewer — NOT the EC-1 swap to
// general-purpose — is the whole point: code-reviewer has no Bash to fetch/materialize the diff
// itself, so the stage step feeds it. The diff is ALWAYS origin/<integrationBase>...origin/<kahuna>,
// NEVER a hard-coded `main`. Scoped to the CHANGED FILES only (§3.4). pass = no critical/important.

// 3a. STAGE — general-purpose (Bash) agent prepares the review workspace + changed-file set.
export function reviewStagePrompt({ waveId, kahunaBranch, integrationBase, targetRepo, targetRepoDir }) {
  return [
    `Trust-gate REVIEW STAGE for wave ${waveId} of ${targetRepo}. You PREPARE the diff the code`,
    `reviewer will read — you do NOT review anything. Work in ${targetRepoDir}.`,
    ``,
    `1. Fetch BOTH refs from origin (never assume the base is 'main' — this wave's base is ${integrationBase}):`,
    `     git -C ${targetRepoDir} fetch origin ${integrationBase} ${kahunaBranch}`,
    `2. Compute the wave's changed-file set — the ${kahunaBranch}-vs-${integrationBase} diff:`,
    `     git -C ${targetRepoDir} diff --name-only origin/${integrationBase}...origin/${kahunaBranch}`,
    `   (three-dot: what changed on ${kahunaBranch} since it diverged from ${integrationBase}.)`,
    `3. Materialize a durable REVIEW WORKSPACE the (Bash-less) reviewer can read natively — EITHER:`,
    `     • a git worktree checked out at origin/${kahunaBranch}:`,
    `         git -C ${targetRepoDir} worktree add --force <workspaceDir> origin/${kahunaBranch}`,
    `       and return its absolute path as workspaceDir; OR`,
    `     • if a worktree cannot be created, write the full unified diff to a file in a workspace dir:`,
    `         git -C ${targetRepoDir} diff origin/${integrationBase}...origin/${kahunaBranch} > <workspaceDir>/kahuna.diff`,
    `       and return that dir as workspaceDir.`,
    `CONSERVATIVE-FAIL: if the fetch errors OR the changed-file set is EMPTY (zero files), return`,
    `staged=false with the reason in notes — an empty/failed stage must HOLD the gate (the reviewer has`,
    `nothing sound to read), it must NEVER let the review signal silently pass.`,
    `Do NOT review, comment on, or modify any code. Return staged (bool), workspaceDir (abs path),`,
    `changedFiles (JSON array of the changed paths), notes (1-2 sentences; on staged=false, the reason).`,
  ].join('\n')
}

// The stage agent's structured return (prepared workspace + changed-file set for the reviewer).
export const REVIEW_STAGE = {
  type: 'object',
  additionalProperties: false,
  required: ['staged'],
  properties: {
    staged: { type: 'boolean' }, // true only if a NON-EMPTY diff was materialized
    workspaceDir: { type: 'string' }, // abs path the reviewer reads (worktree of kahuna, or diff-manifest dir)
    changedFiles: { type: 'array', items: { type: 'string' } }, // origin/<integrationBase>...origin/<kahuna>
    notes: { type: 'string' },
  },
}

// 3b. REVIEW — the SPECIALIZED feature-dev:code-reviewer reads the STAGED workspace (no Bash needed).
export function reviewSignalPrompt({ waveId, kahunaBranch, integrationBase, targetRepoDir, workspaceDir, changedFiles }) {
  const fileList = Array.isArray(changedFiles) && changedFiles.length
    ? changedFiles.join(', ')
    : '(the staged changed-file set)'
  return [
    `Trust-gate REVIEW signal for wave ${waveId}. The STAGE step already prepared the diff FOR you:`,
    `the ${kahunaBranch}-vs-${integrationBase} changed files are materialized in the review workspace`,
    `${workspaceDir || '<the prepared workspace>'} (a worktree checked out at origin/${kahunaBranch}, or a`,
    `written diff manifest there). You do NOT need Bash and must NOT fetch anything — read that workspace.`,
    ``,
    `Review the ${kahunaBranch}-vs-${integrationBase} diff (origin/${integrationBase}...origin/${kahunaBranch},`,
    `NEVER a hard-coded 'main') for correctness / architecture / unstated intent — the rung a test cannot`,
    `encode (§9 verification ladder).`,
    ``,
    `SCOPE STRICTLY to the wave's CHANGED FILES: ${fileList}. NEVER the whole tree (§3.4) —`,
    `pre-existing baseline debt in untouched files must NOT fail this signal.`,
    `Pass predicate: passed = NO critical and NO important findings in the changed files. Nits/minor do`,
    `not fail the signal (record them in detail).`,
    `Do NOT modify any code — this is a read-only signal. Return signal="review", passed (bool),`,
    `detail (finding count by severity + 1 line).`,
  ].join('\n')
}

// ── 4. trivy signal (HIGH/CRITICAL dependency vulns on kahuna) ────────────────────────
// pass = no HIGH/CRITICAL findings WITH AN AVAILABLE FIX (an unfixable upstream advisory
// must not permanently wedge the gate — that is a deferral decision, not a wave defect).
//
// cc-workflow#1169: trivy's fs scanner suppresses devDependencies by default (its own
// "Suppressing dependencies for development and testing" notice) — --include-dev-deps is
// REQUIRED, not optional, for any project (a bun-based tools repo is the measured case) whose
// entire dependency tree is dev-only. Without it, trivy exits clean with a real lockfile
// present and ZERO packages scanned — indistinguishable in the JSON from "scanned, found
// nothing" unless the agent checks the package count. That is exactly the shape this signal's
// own conservative-fail clause was written to catch ("trivy... cannot run"), but the ORIGINAL
// wording only named non-execution — an agent following it literally would read a clean,
// zero-package JSON as a pass. Both gaps close together: the flag makes the scan actually
// cover dev-only trees, and the predicate below now explicitly extends conservative-fail to
// "ran but scanned zero packages against a real lockfile", so a future regression to this same
// shape (a different suppression flag, a different ecosystem) still gets caught by the rule,
// not just by the one flag.
//
// Round-2 review: the command MUST emit JSON (--format json --quiet) — the predicate below
// reasons about a "Results key"/"package count", which a table-format run (the prior wording)
// never produces; an agent given the table command had no artifact to apply the rule to.
// --list-all-pkgs is explicit rather than assumed-default: it only became the default in trivy
// v0.67.0, and this repo pins no minimum version (deps.json marks trivy "optional", no floor),
// so an older install would otherwise never emit the Results[].Packages array the rule reads —
// turning "scan ran clean" into a permanent conservative-fail on every repo, a gate that blocks
// everything being exactly as broken as one that blocks nothing.
//
// Round-3 review (of round-2's own fix): the prescribed `find` was itself broken bash — split
// across template-literal array elements with no line-continuation backslash, so pasted literally
// two of its lines fail/misparse, and it named a prune in prose without a real `-prune` clause
// (reachable: -maxdepth 3 still walks into node_modules/<pkg>/bun.lock). Rebuilt as ONE line,
// TESTED directly in bash against a real tree with a node_modules trap (confirmed: finds the
// real lockfile, prunes the nested copy). Also added bun.lockb — scripts/ci/check-scannable.sh's
// own enumeration (the sibling authority in this repo) already carries it; trivySignalPrompt's
// list mirrors that one now, on purpose, so the two lockfile lists in this repo drift together
// instead of separately (widening beyond that shared set, e.g. Gemfile.lock, is a real gap too,
// but a bigger scope change than this fix — check-scannable.sh doesn't cover it either, so parity
// with it is the bar this fix targets, not universal ecosystem coverage. The Python locks were
// added later, by #1289 below).
//
// cc-workflow#1247: the find counts every pip requirements file (check-scannable.sh's REQ_FIND,
// carried verbatim: *requirements*.txt and requirements/*.txt), but trivy's pip analyzer reads only
// the exact name requirements.txt, so a requirements-dev.txt was in the denominator and never in
// the scan. A 2-of-4 run then passed on the clean half. Siblings are now scanned alone under the
// name trivy reads (scripts/ci/dependency-scan.sh does the same), and the agent returns its counts
// in TRIVY_SIG so trivyCoverage() holds a partial run in code rather than by instruction. A
// requirements file with no '==' pin stays OUT of the denominator, as check-scannable.sh leaves it
// out (UNSCANNABLE): it carries no version, so trivy could never ingest it, and counting it would
// HOLD every wave that also has a real lock (a docs/requirements.txt of `sphinx>=7` is enough).
// So does a bun.lockb beside a bun.lock: the same packages, and the one check-scannable.sh does not
// count. A lone bun.lockb, which trivy cannot parse, stays in and HOLDs by design.
//
// cc-workflow#1277: both scans printed their JSON to stdout, and so into the Bash tool's output, which
// is cut at about 30k characters. trivy lists a target's Packages before its Vulnerabilities, so a big
// lock could be cut between the two and read as ingested and clean: a false PASS (one django==2.2.0
// pin is ~95 KB of JSON). Each run now writes its JSON to a file and jq reads it there, as /precheck's
// raw-trivy fallback has done since #1275, with stderr in its own file so a warning cannot corrupt the
// JSON. The work directory is a <w> placeholder filled from mktemp -d's output, not a $w variable: a
// shell variable does not survive between Bash calls, so `> $w/...` in a later call would write to
// /trivy-0.json, fail, and HOLD every wave. The jq row carries hc_fixable because the pass predicate
// fails only on a fixable finding.
//
// cc-workflow#1289: a repo whose only lock was a uv.lock found nothing here. The find now names the
// Python locks trivy 0.74.0 was measured to ingest (uv.lock, poetry.lock, Pipfile.lock); pdm.lock is
// left out because trivy has no pdm analyzer, and a found lock it cannot read would HOLD every wave
// of a repo that carries one. The names are check-scannable.sh's JS_LOCKS / PAIRED_LOCKS /
// LONE_LOCKS (the reasons per name live there), and test_lock_lists_agree fails when they differ.
//
// cc-workflow#1206: every scan ran over targetRepoDir, the operator's checkout, on whatever branch it
// held; the prompt only asked the agent to "ensure" the kahuna branch was checked out, which it could
// not safely do. The signal now stages its OWN detached worktree of origin/<kahuna> under <w>/tree
// (not the review stage's workspace: that would serialize the two signals, and the review stage can
// fall back to a diff file, which is not a tree), runs the find, the scans and the declaration check
// there, and returns the worktree's HEAD and origin/<kahuna> so trivyTreeBound() binds the verdict to
// the kahuna tip in code. It never checks out or switches in targetRepoDir.
export function trivySignalPrompt({ waveId, kahunaBranch, integrationBase, targetRepoDir }) {
  return [
    `Trust-gate TRIVY signal for wave ${waveId}. Scan the tip of ${kahunaBranch}, the tree the gate judges`,
    `before it lands on ${integrationBase}, for dependency vulnerabilities.`,
    `Do NOT run git checkout or git switch in ${targetRepoDir}: it is the operator's checkout, and the`,
    `branch it holds is not the one being judged. STAGE A DETACHED WORKTREE OF THE KAHUNA TIP FIRST:`,
    `  1. mktemp -d, once. Write the path it prints in place of <w> in every command below: a shell`,
    `     variable does not survive from one Bash call to the next.`,
    `  2. git -C ${targetRepoDir} fetch origin ${kahunaBranch}`,
    `     (other gate signals fetch at the same time: on an error about a ref .lock, wait a few seconds and retry once)`,
    `  3. git -C ${targetRepoDir} rev-parse origin/${kahunaBranch}   → kahuna_sha`,
    `  4. git -C ${targetRepoDir} worktree add --detach <w>/tree origin/${kahunaBranch}`,
    `  5. git -C <w>/tree rev-parse HEAD   → scanned_sha`,
    `If step 2 or step 4 fails, nothing can be scanned: skip to the cleanup, and return passed=false,`,
    `found=0, ingested=0, unscanned=[], declared=false, the error in detail, and the SHAs you have`,
    `("" for one you do not). Every find, scan and file check below runs over <w>/tree, never ${targetRepoDir}.`,
    `THEN enumerate the dependency manifests/lockfiles under <w>/tree — run this exactly (one command, do not split it):`,
    `  find <w>/tree \\( -name node_modules -o -name .git -o -name dist -o -name build -o -name vendor -o -name .venv -o -name venv -o -name target \\) -prune -o -type f \\( -name 'bun.lock' -o -name 'bun.lockb' -o -name 'package-lock.json' -o -name 'yarn.lock' -o -name 'pnpm-lock.yaml' -o -name 'go.sum' -o -name 'Cargo.lock' -o -name 'uv.lock' -o -name 'poetry.lock' -o -name 'Pipfile.lock' -o -name '*requirements*.txt' -o -path '*/requirements/*.txt' \\) -print`,
    `and report the count of lines it prints — this is the denominator the pass predicate below`,
    `needs, not optional context. Two exclusions, both matching scripts/ci/check-scannable.sh:`,
    `(1) a pip requirements file (a line the find printed for its *requirements*.txt or`,
    `requirements/*.txt patterns) with no entry pinned by '==' is a range declaration, not a lock (it`,
    `carries no version, so trivy can never ingest it). Test each requirements file the find printed with`,
    `  grep -cE '^[[:space:]]*[A-Za-z0-9._-]+[[:space:]]*===?[[:space:]]*[0-9]' '<that file>'`,
    `and where it prints 0, leave that file OUT of the denominator and name it in detail as unpinned.`,
    `(2) a bun.lockb with a bun.lock in the same directory is the same packages in bun's old binary`,
    `format, and check-scannable.sh counts only the bun.lock: leave that bun.lockb OUT as well. trivy`,
    `cannot parse bun.lockb at all, so a bun.lockb with NO bun.lock beside it stays in and is UNSCANNED`,
    `by design; say in detail that the remedy is bun's text lockfile, bun.lock (bun 1.2+ writes it).`,
    `A file left out goes in detail, never in unscanned, and is never counted as ingested.`,
    `Capture every trivy run to a file, never to the tool output (cc-workflow#1277). The Bash tool`,
    `cuts its output at about 30k characters, and trivy lists a target's Packages BEFORE its`,
    `Vulnerabilities, so a lock of a few hundred packages can be cut after its packages and before`,
    `its findings: it reads as ingested with 0 HIGH/CRITICAL, a FALSE PASS. Every run's JSON goes in`,
    `<w> (the step-1 directory, beside the tree, never inside it). Run each scan with`,
    `run_in_background: true (a first DB pull can outlast the foreground limit), one at a time, never`,
    `in parallel (they share one trivy cache), in the form shown, where <n> numbers the runs (0 for the`,
    `main scan). stderr has its own file, so a warning cannot make good JSON unparseable.`,
    `THEN run:`,
    `  trivy fs --scanners vuln --severity HIGH,CRITICAL --include-dev-deps --list-all-pkgs --format json --quiet <w>/tree > <w>/trivy-0.json 2> <w>/trivy-0.err; echo "exit=$?"`,
    `--include-dev-deps is REQUIRED — trivy suppresses dev/test dependencies by default, and a`,
    `project whose entire tree is dev-only (e.g. a bun-based tools repo) would otherwise scan`,
    `ZERO packages while still exiting clean (cc-workflow#1169). --list-all-pkgs is required on`,
    `trivy <0.67.0, where it is not yet the default.`,
    `trivy's pip analyzer reads ONLY a file named exactly requirements.txt (cc-workflow#1247), so the`,
    `scan above skips every other pinned requirements file. Scan each of those ALONE, under`,
    `the one name trivy reads, with the same flags and the same capture, giving each its own <n>,`,
    `and count its result for that file:`,
    `  d=$(mktemp -d) && cp '<that file>' $d/requirements.txt && trivy fs --scanners vuln --severity HIGH,CRITICAL --include-dev-deps --list-all-pkgs --format json --quiet $d > <w>/trivy-<n>.json 2> <w>/trivy-<n>.err; echo "exit=$?"; rm -rf \${d:?}`,
    `Its HIGH/CRITICAL findings count toward the verdict exactly like the main scan's.`,
    `Read the packages and findings of every run per target FROM ITS FILE, with jq, never from tool`,
    `output. hc_fixable counts the HIGH/CRITICAL findings that have a fixed version, the ones the pass`,
    `predicate below fails on:`,
    `  jq '[.Results[]? | {Target, pkgs: (.Packages // [] | length), hc: ([.Vulnerabilities[]? | select(.Severity=="HIGH" or .Severity=="CRITICAL")] | length), hc_fixable: ([.Vulnerabilities[]? | select((.Severity=="HIGH" or .Severity=="CRITICAL") and ((.FixedVersion // "") != ""))] | length)}]' <w>/trivy-<n>.json`,
    `  jq '[.Results[]? | .Target as $t | .Vulnerabilities[]? | select(.Severity=="HIGH" or .Severity=="CRITICAL") | {target: $t, pkg: .PkgName, id: .VulnerabilityID, severity: .Severity, fixed: .FixedVersion}]' <w>/trivy-<n>.json`,
    `A run that printed no exit=, printed a non-zero exit=, or left a file jq cannot parse scanned nothing: every lock it was to cover is UNSCANNED.`,
    `A per-file scan's jq row has Target requirements.txt, and that row is that file's.`,
    `A lockfile in the denominator is INGESTED when a jq row for it shows at least one package (for`,
    `go.sum, the row for the go.mod beside it). Every other one is UNSCANNED. PARTIAL COVERAGE`,
    `FAILS: if some lockfiles are INGESTED and any is UNSCANNED, passed=false even when every`,
    `ingested one is clean, because an unscanned lock is not a clean one.`,
    `Pass predicate: passed = NO HIGH/CRITICAL finding that has an AVAILABLE FIXED VERSION. An`,
    `unfixable upstream advisory (no fixed version published) does NOT fail the signal — record it in`,
    `detail as a deferral. CONSERVATIVE-FAIL (passed=false) — the gate must not PASS on the absence`,
    `of a scan — applies to trivy is not installed / the scan cannot run, AND to a manifest count`,
    `(found) greater than 0 where the JSON output has no Results key or Results carry an empty/absent`,
    `Packages list (a real lockfile existed but trivy extracted nothing from it).`,
    `A .no-scannable-dependencies declaration at the root of <w>/tree (the kahuna tip, not the operator's`,
    `checkout), with a reason, applies only when no`,
    `lock is found (found 0): a repo can legitimately have nothing pinnable, and the declaration is`,
    `how it says so. It rescues nothing else; any found-but-unscanned lock FAILS, declared or not, as`,
    `scripts/ci/check-scannable.sh rules. Report the manifest count AND the actual package count`,
    `scanned in detail either way.`,
    `CLEANUP, always, even after a failure:`,
    `  git -C ${targetRepoDir} worktree remove --force <w>/tree; git -C ${targetRepoDir} worktree prune`,
    `Do NOT do any other work beyond the staging, enumeration, scans and cleanup above. Return signal="trivy", passed (bool),`,
    `found (the denominator: lines the find printed, less the two exclusions above), ingested`,
    `(how many of those are INGESTED), unscanned (the UNSCANNED paths), declared (true ONLY if a`,
    `.no-scannable-dependencies file with a reason exists at the root of <w>/tree), scanned_sha and`,
    `kahuna_sha (steps 5 and 3, the full SHAs exactly as git printed them, never abbreviated), and detail`,
    `(scanned_sha + counts + 1 line). The gate re-checks found, ingested, unscanned, declared and the two`,
    `SHAs itself: a scan whose scanned_sha is not kahuna_sha HOLDs.`,
  ].join('\n')
}

// ── Promotion (the success-exit terminal step — CODE ONLY) ────────────────────────────
// Called by the workflow ONLY when MODE==='auto' AND the gate verdict is PASS — i.e. only on
// a live wave's success exit. The kahuna→integrationBase DRAFT PR was ALREADY OPENED by the gate's
// PR-OPEN node (#5) and its merge-result CI was already validated by the CI signal — so promotion
// no longer opens a PR; it marks the EXISTING draft ready and merges it. pr_merge lands it; the
// kahuna branch is deleted; disposition recorded. promoted=true ONLY once the merge is observable
// on the integration base — enrolled/pending is never treated as done.
//
// WHAT THIS NODE DOES *NOT* DO (#1052): inside a campaign this merge lands the wave on the
// CAMPAIGN branch, not the protected branch. It is integration, not release. Nothing here closes
// issues, tags, or touches trunk — the campaign's single release merge does that once, at DoD
// (campaign-loop.js releaseMergePrompt). The field is still named `promoted` because it is the
// per-wave spine's existing contract; the campaign loop reads it through isIntegrated().
//
// SAFETY (#691): this prompt is the CODE for promotion. It executes a real merge, so it runs
// SOLELY from the workflow's auto+PASS branch on a live wave that reached the success exit —
// which is itself gated by the human cutover (#691). Building/validating this module never
// invokes it.
//
// THE MERGE BINDS TO THE GRADED HEAD (#1356, triage #6): the head the CI signal graded is passed in as
// headSha and pinned on pr_merge (expected_head_sha), so a push between grading and merging is refused
// rather than landed unseen. With no graded head there is nothing to pin, and the prompt is a STOP, the
// same fail-closed floor as the campaign's releaseMergePrompt.
export function promotePrompt({ waveId, kahunaBranch, integrationBase, targetRepo, prNumber, headSha, preserveKahuna = false }) {
  const prRef = prNumber != null ? `PR #${prNumber}` : `the open ${kahunaBranch}→${integrationBase} PR`
  if (!isMergeSha(headSha)) {
    return [
      `You are the wave PROMOTION node for wave ${waveId} of ${targetRepo}. No graded head SHA was handed to`,
      `you for ${prRef}, so there is nothing to bind the merge to. STOP. Do NOT mark the PR ready and do NOT`,
      `merge. Return promoted=false, with notes saying the gate passed no graded head.`,
    ].join('\n')
  }
  // #722: a PER-PLAN kahuna (e.g. kahuna/56-…, shared across a plan's waves 1..N) must PERSIST —
  // deleting it after wave 1 strands waves 2..N off a diverged base. The default (false) keeps the
  // current per-wave disposable behavior: KAHUNA_BRANCH defaults to kahuna/<waveId>, deleted here.
  //
  // #1052 retires the preserve case INSIDE a campaign: the thing that has to persist across waves
  // is the CAMPAIGN branch, and it now does, so each wave's kahuna is disposable again. The caller
  // (per-wave-workflow.js) forces preserveKahuna=false whenever integrationBase !== the protected
  // branch. The flag survives here for standalone /nextwave, where a per-plan kahuna is still the
  // only cross-wave carrier.
  const step4 = preserveKahuna
    ? [
      `4. Do NOT delete ${kahunaBranch} (#722: preserveKahuna) — it is a PERSISTENT per-plan integration`,
      `   branch shared across this plan's remaining waves; deleting it would strand them off a diverged`,
      `   base. Leave it on origin; the plan's final wave (or the campaign driver) retires it.`,
    ]
    : [
      `4. Once ${kahunaBranch} is on ${integrationBase}, delete the ${kahunaBranch} branch (gh -R ${targetRepo}`,
      `   api / git push origin --delete) — the wave is done; this per-wave integration branch is disposable.`,
    ]
  return [
    `You are the wave PROMOTION node for wave ${waveId} of ${targetRepo}. The trust gate returned PASS`,
    `and the wave is in AUTO mode. The ${kahunaBranch}→${integrationBase} DRAFT PR is ALREADY OPEN (${prRef})`,
    `and its merge-result CI was already validated by the gate's CI signal. Land it, then return. Do NOT`,
    `open a new PR (the gate's PR-OPEN node already did, #5); do NOT re-run the gate (it already PASSed).`,
    ``,
    `1. Locate ${prRef}${prNumber != null ? '' : ` (sdlc-server pr_status / pr_list, or gh -R ${targetRepo})`}.`,
    `   If no such PR exists, STOP and return promoted=false with the reason in notes (do NOT fabricate a`,
    `   merge — the gate should have opened it; its absence is an error, not a green light).`,
    `2. Mark it ready for review (un-draft): gh -R ${targetRepo} pr ready <number>. (No-op if already ready.)`,
    `3. Merge it: sdlc-server pr_merge(number=<the PR number>, expected_head_sha="${headSha}") — commutativity_verify`,
    `   already proved the composed diff safe, and CI graded head ${headSha}. If it returns anything but a merge`,
    `   (ok=false, or any error: head_moved on GitLab, gh_pr_merge_failed on GitHub, where a stale pin is not`,
    `   classified, or anything else), STOP and return promoted=false with the error in notes. Never retry it`,
    `   without expected_head_sha, and never merge any other way: code CI never saw must not land on`,
    `   ${integrationBase}. Copy pr_merge's pinned_head_sha into your return exactly as it came back, or`,
    `   leave it out if the response has none. sdlc v5.1.x pins but does not echo, and anything before`,
    `   v5.1.0 drops the pin without a word and merges unpinned, so no echo means no pin: the workflow`,
    `   checks the echo itself. Then CONFIRM it actually landed on ${integrationBase} before reporting`,
    `   promoted: poll until the PR reads state=MERGED with a merge commit (pr_merge_wait, or`,
    `   gh -R ${targetRepo} pr view <number> --json state,mergeCommit). Never treat a pending merge as done.`,
    ...step4,
    ``,
    `Return: promoted (true ONLY if the merge actually landed on ${integrationBase}), mr_ref (the PR`,
    `URL/number), merged (pr_merge's merged, as returned), pinned_head_sha (pr_merge's, as returned),`,
    `merge_commit_sha (the merge commit),`,
    `notes (1-2 sentences; include any error — and on error, promoted=false).`,
  ].join('\n')
}

// A PINNED MERGE COUNTS ONLY WHEN THE SERVER SAYS IT PINNED (#1356 review). pr_merge's schema strips
// unknown keys, so an sdlc server before v5.1.0 drops expected_head_sha without an error and merges
// whatever the head is; v5.1.x pins but does not echo. v5.2.0 echoes the SHA it pinned as
// pinned_head_sha, and only when the head it re-reads after the call is that SHA. No echo means no
// pin, and a different one is not the graded head, so both are refused. The echo alone is not a
// merge either: v5.2.0 still echoes on a queue enrollment (merged:false), so `merged` must be true.
export function pinnedMergeVerdict(report, gradedHead) {
  const g8 = isMergeSha(gradedHead) ? gradedHead.slice(0, 8) : 'missing'
  if (!isMergeSha(gradedHead)) return { landed: false, reason: 'no graded head to pin the merge to' }
  if (report?.merged !== true) return { landed: false, reason: `pr_merge did not report merged:true (enrolled or pending is not a merge; graded head ${g8})` }
  const p = report?.pinned_head_sha
  if (typeof p !== 'string' || !p) {
    return { landed: false, reason: `pr_merge returned no pinned_head_sha: sdlc v5.1.x pins but does not echo, and anything before v5.1.0 drops the pin, so no echo means no pin (graded head ${g8}); the host needs sdlc v5.2.0` }
  }
  if (p !== gradedHead) return { landed: false, reason: `pr_merge pinned ${p.slice(0, 8)}, not the graded head ${g8}` }
  return { landed: true, reason: `merge pinned to the graded head ${g8}` }
}

// Reconcile's merges, graded in code (#1356 review). A handed flight is merged only when it is in BOTH
// reconcile's `merged` list and its `merges` proof (the merge commit, merged:true, and a pin echo equal
// to its graded head). A flight in needs_rework is neither merged nor refused, whatever else reconcile
// lists for it: an undone merge must not be counted, or cleanupMerged deletes the worktree of a flight
// about to be reworked and the issue can be closed with nothing landed. Anything else reconcile claims
// merged without that proof is refused, and the wave halts.
export function reconciledMerges(rec, handed) {
  const merges = Array.isArray(rec?.merges) ? rec.merges : []
  const claimed = new Set((rec?.merged || []).map(Number))
  const reworked = new Set((rec?.needs_rework || []).map((r) => Number(r?.issue)))
  const merged = []
  const refused = []
  for (const w of handed) {
    const n = Number(w.issue)
    if (reworked.has(n)) continue
    const m = merges.find((x) => Number(x?.issue) === n)
    if (!claimed.has(n)) {
      if (m) refused.push({ issue: n, reason: 'a merges entry with no merged claim and no needs_rework (its merge may be in the kahuna)' })
      continue
    }
    if (!m) {
      refused.push({ issue: n, reason: 'reported merged with no merges entry (merge_commit_sha, pinned_head_sha)' })
      continue
    }
    if (!isMergeSha(m.merge_commit_sha)) { refused.push({ issue: n, reason: 'no merge_commit_sha for its merge' }); continue }
    const v = pinnedMergeVerdict(m, w.head)
    if (v.landed) merged.push(n)
    else refused.push({ issue: n, reason: v.reason })
  }
  return { merged, refused }
}

// The promotion agent's structured return (side-effect + outcome, not judgment).
export const PROMOTE_RESULT = {
  type: 'object',
  additionalProperties: false,
  required: ['promoted'],
  properties: {
    promoted: { type: 'boolean' }, // true ONLY if the merge actually landed on the integration base
    mr_ref: { type: 'string' },
    pinned_head_sha: { type: 'string' }, // pr_merge's echo of the pin (sdlc >= v5.2.0); absent = no pin
    merged: { type: 'boolean' }, // pr_merge's merged, as returned (an echo on an enrollment is not a merge)
    merge_commit_sha: { type: 'string' },
    notes: { type: 'string' },
  },
}
