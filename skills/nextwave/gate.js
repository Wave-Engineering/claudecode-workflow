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
//      kahuna→protected MR, pr_merge lands it on all-green, the kahuna branch is deleted,
//      disposition recorded. CODE ONLY — the loop calls it solely on a live wave's success
//      exit (gated by the human cutover, #691); never during a build.
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
// land in the protected branch? pass = verdict ∈ {STRONG, MEDIUM}; every other verdict —
// explicitly PROBE_UNAVAILABLE and ORACLE_REQUIRED (and any timeout sharing their body
// shape) — is conservative-fail (HOLD), per the tool's own contract.
//
// #6 (live-gate finding) — gate-vs-reconcile consistency: the RECONCILE node MAY adjudicate
// an ORACLE_REQUIRED verdict via judgment DURING integration (it has the cross-flight view and
// can run the suite to decide the composed diff is safe). The trust GATE — the auto-promotion
// decision to land kahuna on the PROTECTED branch — does NOT: it HOLDs on ORACLE_REQUIRED so a
// human reviews. "Don't auto-promote what the probe can't prove safe." The two are not
// inconsistent — they answer different questions (is this group mergeable now? vs. is the whole
// wave safe to ff onto the protected branch unattended?); the gate is the conservative one.
export function commutativitySignalPrompt({ waveId, kahunaBranch, protectedBranch, targetRepoDir }) {
  return [
    `Trust-gate COMMUTATIVITY signal for wave ${waveId}.`,
    `Call sdlc-server commutativity_verify in SINGLE-TARGET mode — the KAHUNA composed-diff safety gate:`,
    `  repo_path=${targetRepoDir}`,
    `  base_ref=${protectedBranch}`,
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
// #5 (live-gate finding, BLOCKING): the CI signal's ci_wait_run on the kahuna→protected
// merge-result pipeline returned `no_merge_result_pr` because the promotion PR used to be
// created AT promotion — AFTER the gate. Chicken-and-egg. Fix (reorders §3.4): the gate opens
// the kahuna→protected PR as a DRAFT FIRST, so there is a real PR (and its merge-result
// pipeline) for the CI signal to wait on; the gate then decides; on PASS+auto the promote node
// marks it ready and merges THAT SAME PR (it never opens a second one). DRAFT so a green CI
// can't let the platform auto-merge it before the gate has aggregated all four signals.
//
// Idempotent: re-opening an already-open kahuna→protected PR returns the existing one (wave_finalize
// is idempotent on the branch pair). opened=false (with a reason) ONLY when the branch/artifacts are
// missing — in which case the gate HOLDs (it cannot prove a wave it can't even PR). Never fabricates.
export function openPromotionPrPrompt({ waveId, kahunaBranch, protectedBranch, targetRepo, targetRepoDir, planId }) {
  return [
    `You are the wave GATE PR-OPEN node for wave ${waveId} of ${targetRepo}. Open (idempotently) the`,
    `${kahunaBranch}→${protectedBranch} promotion PR/MR as a DRAFT, then return its number. This runs`,
    `BEFORE the trust signals so the CI signal has a real merge-result pipeline to wait on [#5].`,
    `Do NOT merge anything, do NOT mark the PR ready, do NOT run the gate — just open-or-find the draft PR.`,
    ``,
    `1. Open (or return the existing — idempotent) ${kahunaBranch}→${protectedBranch} PR via sdlc-server`,
    `   wave_finalize(plan_id=${planId ?? '<the wave plan id>'}, kahuna_branch="${kahunaBranch}",`,
    `   target_branch="${protectedBranch}", root="${targetRepoDir}"). The root is LOAD-BEARING (#699 finding`,
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
    opened: { type: 'boolean' }, // a kahuna→protected PR exists for the pair (draft)
    pr_number: { type: 'integer' }, // the CI signal waits on this PR; promote merges it
    pr_ref: { type: 'string' },
    notes: { type: 'string' },
  },
}

// ── 2. CI signal (#452: MR merge-result pipeline, NOT merge-commit branch HEAD) ───────
// ci_wait_run on the kahuna→protected MR — the DRAFT PR the gate's PR-OPEN node already
// opened (#5), passed in by number so this signal never races to "find" it (the old
// `no_merge_result_pr` failure). Lint/typecheck ride INSIDE this signal (the project's full
// gate runs in CI), diff-scoped to the wave's changed files (§3.4).
export function ciSignalPrompt({ waveId, kahunaBranch, protectedBranch, targetRepo, prNumber }) {
  const prRef = prNumber != null ? `PR #${prNumber}` : `the open ${kahunaBranch}→${protectedBranch} PR/MR`
  return [
    `Trust-gate CI signal for wave ${waveId}. Wait on the ${kahunaBranch}→${protectedBranch} MERGE-RESULT`,
    `pipeline — NOT the merge-commit branch HEAD [sdlc #452].`,
    ``,
    `1. The gate's PR-OPEN node already opened the draft promotion PR: ${prRef} (repo=${targetRepo}).`,
    prNumber != null
      ? `   Use that number directly — do NOT search for it. (If for any reason it is not found, that is a`
      : `   Find it via sdlc-server pr_status / pr_list (or gh -R ${targetRepo}). (If none is found, that is a`,
    `   CONSERVATIVE-FAIL: return passed=false — the gate must not PASS without a pipeline to verify.)`,
    `   The CI you wait on is the pipeline produced by MERGING kahuna INTO ${protectedBranch} (the merge`,
    `   result), not the branch's own latest push.`,
    `2. Call sdlc-server ci_wait_run (repo=${targetRepo}) with require_merge_result=true AND`,
    `   pr_number=${prNumber != null ? prNumber : '<the PR number>'}. BOTH are load-bearing (#476):`,
    `     • require_merge_result makes the tool refuse to grade a BRANCH pipeline, a SKIPPED one, or a`,
    `       GitLab DETACHED (refs/merge-requests/N/head) pipeline — none of which validated the merge.`,
    `     • pr_number is the FRESHNESS anchor. Filtering to merge-result runs is not enough: a GREEN`,
    `       merge-result run for a PREVIOUS commit still sits in the list, and grading it would merge`,
    `       code CI never saw. The tool binds the run to the PR/MR's CURRENT head (GitHub: the PR head`,
    `       SHA; GitLab: the MR's head_pipeline) and HOLDs if it cannot prove freshness.`,
    `3. Pass predicate — passed = final_status == "success".`,
    `   Any other final_status FAILS — including "not_merge_result", which means CI never validated the`,
    `   merge (no merged-results pipeline / a branch-only pipeline / a skipped one). Do NOT treat it as`,
    `   a pass, and do NOT fall back to the branch pipeline: HOLD and report the tool's remediation hint.`,
    `   The project's lint + typecheck RIDE INSIDE this pipeline, diff-scoped to the wave's changed files`,
    `   (§3.4) — they are not a separate signal; pre-existing baseline debt must NOT fail this signal.`,
    `Do NOT do any other work. Return signal="ci", passed (bool), detail (final_status/reason + 1 line).`,
  ].join('\n')
}

// ── 3. review signal (#847/ENG-5: 2-step stage→review; specialized reviewer PRESERVED) ─
// The review signal is the ONLY gate signal that reads the code diff. It must NOT provision off
// `origin/main`: on repos where main is a bare scaffold and real work lives on a release branch,
// an origin/main worktree reviews an EMPTY tree → passed:false → spurious HOLD on every wave
// (ENG-5). It is therefore a 2-STEP sub-pipeline (assembled at the call site): a Bash-capable
// general-purpose STAGE agent fetches + diffs origin/<protected>...origin/<kahuna> and
// materializes the changed-file set into a durable review workspace; then the SPECIALIZED
// feature-dev:code-reviewer reviews that workspace. Keeping code-reviewer — NOT the EC-1 swap to
// general-purpose — is the whole point: code-reviewer has no Bash to fetch/materialize the diff
// itself, so the stage step feeds it. The diff is ALWAYS origin/<protected>...origin/<kahuna>,
// NEVER a hard-coded `main`. Scoped to the CHANGED FILES only (§3.4). pass = no critical/important.

// 3a. STAGE — general-purpose (Bash) agent prepares the review workspace + changed-file set.
export function reviewStagePrompt({ waveId, kahunaBranch, protectedBranch, targetRepo, targetRepoDir }) {
  return [
    `Trust-gate REVIEW STAGE for wave ${waveId} of ${targetRepo}. You PREPARE the diff the code`,
    `reviewer will read — you do NOT review anything. Work in ${targetRepoDir}.`,
    ``,
    `1. Fetch BOTH refs from origin (never assume the protected branch is 'main' — it is ${protectedBranch}):`,
    `     git -C ${targetRepoDir} fetch origin ${protectedBranch} ${kahunaBranch}`,
    `2. Compute the wave's changed-file set — the ${kahunaBranch}-vs-${protectedBranch} diff:`,
    `     git -C ${targetRepoDir} diff --name-only origin/${protectedBranch}...origin/${kahunaBranch}`,
    `   (three-dot: what changed on ${kahunaBranch} since it diverged from ${protectedBranch}.)`,
    `3. Materialize a durable REVIEW WORKSPACE the (Bash-less) reviewer can read natively — EITHER:`,
    `     • a git worktree checked out at origin/${kahunaBranch}:`,
    `         git -C ${targetRepoDir} worktree add --force <workspaceDir> origin/${kahunaBranch}`,
    `       and return its absolute path as workspaceDir; OR`,
    `     • if a worktree cannot be created, write the full unified diff to a file in a workspace dir:`,
    `         git -C ${targetRepoDir} diff origin/${protectedBranch}...origin/${kahunaBranch} > <workspaceDir>/kahuna.diff`,
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
    changedFiles: { type: 'array', items: { type: 'string' } }, // origin/<protected>...origin/<kahuna>
    notes: { type: 'string' },
  },
}

// 3b. REVIEW — the SPECIALIZED feature-dev:code-reviewer reads the STAGED workspace (no Bash needed).
export function reviewSignalPrompt({ waveId, kahunaBranch, protectedBranch, targetRepoDir, workspaceDir, changedFiles }) {
  const fileList = Array.isArray(changedFiles) && changedFiles.length
    ? changedFiles.join(', ')
    : '(the staged changed-file set)'
  return [
    `Trust-gate REVIEW signal for wave ${waveId}. The STAGE step already prepared the diff FOR you:`,
    `the ${kahunaBranch}-vs-${protectedBranch} changed files are materialized in the review workspace`,
    `${workspaceDir || '<the prepared workspace>'} (a worktree checked out at origin/${kahunaBranch}, or a`,
    `written diff manifest there). You do NOT need Bash and must NOT fetch anything — read that workspace.`,
    ``,
    `Review the ${kahunaBranch}-vs-${protectedBranch} diff (origin/${protectedBranch}...origin/${kahunaBranch},`,
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
// a live wave's success exit. The kahuna→protected DRAFT PR was ALREADY OPENED by the gate's
// PR-OPEN node (#5) and its merge-result CI was already validated by the CI signal — so promotion
// no longer opens a PR; it marks the EXISTING draft ready and merges it. pr_merge lands it; the
// kahuna branch is deleted; disposition recorded. promoted=true ONLY once the merge is observable
// on the protected branch — enrolled/pending is never treated as done.
//
// SAFETY (#691): this prompt is the CODE for promotion. It executes a real kahuna→protected
// merge, so it runs SOLELY from the workflow's auto+PASS branch on a live wave that reached the
// success exit — which is itself gated by the human cutover (#691). Building/validating this
// module never invokes it.
export function promotePrompt({ waveId, kahunaBranch, protectedBranch, targetRepo, prNumber, preserveKahuna = false }) {
  const prRef = prNumber != null ? `PR #${prNumber}` : `the open ${kahunaBranch}→${protectedBranch} PR`
  // #722: a PER-PLAN kahuna (e.g. kahuna/56-…, shared across a plan's waves 1..N) must PERSIST —
  // deleting it after wave 1 strands waves 2..N off a diverged base. The default (false) keeps the
  // current per-wave disposable behavior: KAHUNA_BRANCH defaults to kahuna/<waveId>, deleted here.
  const step4 = preserveKahuna
    ? [
      `4. Do NOT delete ${kahunaBranch} (#722: preserveKahuna) — it is a PERSISTENT per-plan integration`,
      `   branch shared across this plan's remaining waves; deleting it would strand them off a diverged`,
      `   base. Leave it on origin; the plan's final wave (or the campaign driver) retires it.`,
    ]
    : [
      `4. Once ${kahunaBranch} is on ${protectedBranch}, delete the ${kahunaBranch} branch (gh -R ${targetRepo}`,
      `   api / git push origin --delete) — the wave is done; this per-wave integration branch is disposable.`,
    ]
  return [
    `You are the wave PROMOTION node for wave ${waveId} of ${targetRepo}. The trust gate returned PASS`,
    `and the wave is in AUTO mode. The ${kahunaBranch}→${protectedBranch} DRAFT PR is ALREADY OPEN (${prRef})`,
    `and its merge-result CI was already validated by the gate's CI signal. Land it, then return. Do NOT`,
    `open a new PR (the gate's PR-OPEN node already did, #5); do NOT re-run the gate (it already PASSed).`,
    ``,
    `1. Locate ${prRef}${prNumber != null ? '' : ` (sdlc-server pr_status / pr_list, or gh -R ${targetRepo})`}.`,
    `   If no such PR exists, STOP and return promoted=false with the reason in notes (do NOT fabricate a`,
    `   merge — the gate should have opened it; its absence is an error, not a green light).`,
    `2. Mark it ready for review (un-draft): gh -R ${targetRepo} pr ready <number>. (No-op if already ready.)`,
    `3. Merge it: sdlc-server pr_merge(number=<the PR number>) — commutativity_verify already proved`,
    `   the composed diff safe. Then CONFIRM it actually landed on ${protectedBranch} before reporting`,
    `   promoted: poll until the PR reads state=MERGED with a merge commit (pr_merge_wait, or`,
    `   gh -R ${targetRepo} pr view <number> --json state,mergeCommit). Never treat a pending merge as done.`,
    ...step4,
    ``,
    `Return: promoted (true ONLY if the merge actually landed on ${protectedBranch}), mr_ref (the PR`,
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
