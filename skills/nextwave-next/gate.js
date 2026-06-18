// gate.js — the #687 trust-gate seam helper for per-wave-workflow.js.
//
// Design of record: docs/wavemachine-workflows-migration.md §3.4 (trust gate).
// Seam contract: skills/nextwave-next/SEAMS.md (#687 — real gate signals via sdlc-server
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
//      kahuna→protected MR, pr_merge(skip_train:true) lands it on all-green, the kahuna
//      branch is deleted, disposition recorded. CODE ONLY — the loop calls it solely on a
//      live wave's success exit (gated by the human cutover, #691); never during a build.
//
// DIFF-SCOPING (§3.4): every static signal is scoped to the wave's CHANGED FILES
// (kahuna-vs-protected), NEVER the whole tree — otherwise pre-existing baseline debt
// spuriously HOLDs an otherwise-clean wave. Lint/typecheck are NOT a fifth signal; they
// ride INSIDE the CI signal (ci_wait_run runs the project's full gate on the merge result).

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

// ── 1. commutativity signal ──────────────────────────────────────────────────────────
// Single-target mode (one changeset = the whole kahuna composed diff): is kahuna safe to
// land in the protected branch? pass = verdict ∈ {STRONG, MEDIUM}; PROBE_UNAVAILABLE (or a
// timeout sharing its body shape) = conservative-fail, per the tool's own contract.
export function commutativitySignalPrompt({ waveId, kahunaBranch, protectedBranch, targetRepoDir }) {
  return [
    `Trust-gate COMMUTATIVITY signal for wave ${waveId}.`,
    `Call sdlc-server commutativity_verify in SINGLE-TARGET mode — the KAHUNA composed-diff safety gate:`,
    `  repo_path=${targetRepoDir}`,
    `  base_ref=${protectedBranch}`,
    `  changesets=[{ id: "kahuna", head_ref: "${kahunaBranch}" }]`,
    `Apply the pass predicate EXACTLY: passed = (verdict ∈ {STRONG, MEDIUM}). Every other verdict FAILS,`,
    `INCLUDING PROBE_UNAVAILABLE and any timeout/handler-synthesized body — those are CONSERVATIVE-FAIL`,
    `(the probe could not prove safety, so the gate must HOLD), per the tool's documented contract.`,
    `Do NOT do any other work. Return signal="commutativity", passed (bool), detail (the verdict + 1 line).`,
  ].join('\n')
}

// ── 2. CI signal (#452: MR merge-result pipeline, NOT merge-commit branch HEAD) ───────
// ci_wait_run on the kahuna→protected MR. pass accepts BOTH the real green AND the GitHub
// merge-queue "validated, nothing to run on push" shape the tool emits (final_status
// "not_applicable" / reason "merge_group_validated") — else a clean merge-queue wave HOLDs
// spuriously. Lint/typecheck ride INSIDE this signal (the project's full gate runs in CI),
// diff-scoped to the wave's changed files (§3.4).
export function ciSignalPrompt({ waveId, kahunaBranch, protectedBranch, targetRepo }) {
  return [
    `Trust-gate CI signal for wave ${waveId}. Wait on the ${kahunaBranch}→${protectedBranch} MR/PR`,
    `MERGE-RESULT pipeline — NOT the merge-commit branch HEAD [sdlc #452].`,
    ``,
    `1. Find the open ${kahunaBranch}→${protectedBranch} PR/MR (sdlc-server pr_status / pr_list, or`,
    `   gh -R ${targetRepo}). The CI you wait on is the pipeline produced by MERGING kahuna INTO`,
    `   ${protectedBranch} (the merge result), not the branch's own latest push.`,
    `2. Call sdlc-server ci_wait_run on that merge-result ref (repo=${targetRepo}).`,
    `3. Pass predicate — passed = ANY of:`,
    `     • final_status == "success", OR`,
    `     • final_status == "not_applicable" AND reason == "merge_group_validated"  (GitHub merge-queue:`,
    `       a skipped push pipeline + a passing merge_group run IS a validated merge result — do NOT HOLD on it).`,
    `   Any other final_status (failure / timed_out / cancelled / unknown) FAILS.`,
    `   The project's lint + typecheck RIDE INSIDE this pipeline, diff-scoped to the wave's changed files`,
    `   (§3.4) — they are not a separate signal; pre-existing baseline debt must NOT fail this signal.`,
    `Do NOT do any other work. Return signal="ci", passed (bool), detail (final_status/reason + 1 line).`,
  ].join('\n')
}

// ── 3. review signal (#667: code-reviewer on a worktree of kahuna) ────────────────────
// agentType feature-dev:code-reviewer with isolation:'worktree' (set at the call site, not
// here) so the reviewer sees the kahuna branch NATIVELY — no diff-materialization workaround.
// Scoped to the kahuna-vs-protected diff (CHANGED FILES only, §3.4). pass = no
// critical/important findings.
export function reviewSignalPrompt({ waveId, kahunaBranch, protectedBranch }) {
  return [
    `Trust-gate REVIEW signal for wave ${waveId}. You are running on a WORKTREE of ${kahunaBranch}`,
    `(isolation:'worktree' — the branch is checked out natively; #667). Review the ${kahunaBranch}-vs-`,
    `${protectedBranch} diff for correctness / architecture / unstated intent — the rung a test cannot`,
    `encode (§9 verification ladder).`,
    ``,
    `SCOPE STRICTLY to the wave's CHANGED FILES (the kahuna-vs-${protectedBranch} diff), NEVER the whole`,
    `tree (§3.4) — pre-existing baseline debt in untouched files must NOT fail this signal.`,
    `Pass predicate: passed = NO critical and NO important findings in the changed files. Nits/minor do`,
    `not fail the signal (record them in detail).`,
    `Do NOT modify any code — this is a read-only signal. Return signal="review", passed (bool),`,
    `detail (finding count by severity + 1 line).`,
  ].join('\n')
}

// ── 4. trivy signal (HIGH/CRITICAL dependency vulns on kahuna) ────────────────────────
// pass = no HIGH/CRITICAL findings WITH AN AVAILABLE FIX (an unfixable upstream advisory
// must not permanently wedge the gate — that is a deferral decision, not a wave defect).
export function trivySignalPrompt({ waveId, kahunaBranch, targetRepoDir }) {
  return [
    `Trust-gate TRIVY signal for wave ${waveId}. Scan ${kahunaBranch} for dependency vulnerabilities:`,
    `  trivy fs --scanners vuln --severity HIGH,CRITICAL ${targetRepoDir}`,
    `(ensure ${kahunaBranch} is the checked-out / scanned state of ${targetRepoDir}).`,
    `Pass predicate: passed = NO HIGH/CRITICAL finding that has an AVAILABLE FIXED VERSION. An`,
    `unfixable upstream advisory (no fixed version published) does NOT fail the signal — record it in`,
    `detail as a deferral. If trivy is not installed or the scan cannot run, that is CONSERVATIVE-FAIL`,
    `(passed=false) — the gate must not PASS on the absence of a scan.`,
    `Do NOT do any other work. Return signal="trivy", passed (bool), detail (count + 1 line).`,
  ].join('\n')
}

// ── Promotion (the success-exit terminal step — CODE ONLY) ────────────────────────────
// Called by the workflow ONLY when MODE==='auto' AND the gate verdict is PASS — i.e. only on
// a live wave's success exit. wave_finalize opens (idempotent) the kahuna→protected MR;
// pr_merge(skip_train:true) lands it once the merge-result CI is green (commutativity already
// proved skip_train safe in the gate); the kahuna branch is deleted; disposition recorded.
// On a merge-queue-ENFORCED repo skip_train is silently dropped and the PR is enrolled — the
// agent waits for it to land (pr_merge_wait) rather than treating enrolled-but-not-merged as done.
//
// SAFETY (#691): this prompt is the CODE for promotion. It executes a real kahuna→protected
// merge, so it runs SOLELY from the workflow's auto+PASS branch on a live wave that reached the
// success exit — which is itself gated by the human cutover (#691). Building/validating this
// module never invokes it.
export function promotePrompt({ waveId, kahunaBranch, protectedBranch, targetRepo, planId }) {
  return [
    `You are the wave PROMOTION node for wave ${waveId} of ${targetRepo}. The trust gate returned PASS`,
    `and the wave is in AUTO mode. Land ${kahunaBranch} into ${protectedBranch}, then return. Do NOT do`,
    `any other work; do NOT re-run the gate (it already PASSed).`,
    ``,
    `1. Open (or return the existing — idempotent) ${kahunaBranch}→${protectedBranch} MR via sdlc-server`,
    `   wave_finalize(plan_id=${planId ?? '<the wave plan id>'}, kahuna_branch="${kahunaBranch}",`,
    `   target_branch="${protectedBranch}"). If it returns kahuna_branch_not_found or no_artifacts,`,
    `   STOP and return promoted=false with the reason in notes (do NOT fabricate a merge).`,
    `2. Merge it: sdlc-server pr_merge(number=<the MR number>, skip_train=true) — commutativity_verify`,
    `   already proved the composed diff safe, so the train is unnecessary. On a merge-queue-ENFORCED`,
    `   repo skip_train is silently dropped and the PR is ENROLLED (merged=false, queued): in that case`,
    `   wait for it to actually land on ${protectedBranch} (pr_merge_wait) before reporting promoted.`,
    `3. Once ${kahunaBranch} is on ${protectedBranch}, delete the ${kahunaBranch} branch (gh -R ${targetRepo}`,
    `   api / git push origin --delete) — the wave is done; the integration branch is disposable.`,
    ``,
    `Return: promoted (true ONLY if the merge actually landed on ${protectedBranch}), mr_ref (the MR`,
    `URL/number), notes (1-2 sentences; include any error — and on error, promoted=false).`,
  ].join('\n')
}

// The promotion agent's structured return (side-effect + outcome, not judgment).
export const PROMOTE_RESULT = {
  type: 'object',
  additionalProperties: false,
  required: ['promoted'],
  properties: {
    promoted: { type: 'boolean' }, // true ONLY if the merge actually landed on the protected branch
    mr_ref: { type: 'string' },
    notes: { type: 'string' },
  },
}
