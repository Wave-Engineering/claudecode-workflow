// resume.js — the #686 resumability + idempotency seam helper for per-wave-workflow.js.
//
// Design of record: docs/wavemachine-workflows-migration.md
//   §3.3 resumability (rehydrate from wave-status; idempotent worker/reconcile — the crux)
//   §4.2 durable worktrees (idempotent create, reuse-branch-on-resume, never -b)
//   §4.3 cleanup discipline (the 3-point cleanup; prune BRANCHES too, shared wave-<id>/ stem)
// Seam contract: skills/nextwave/SEAMS.md (#686 — resumability / rehydrate / idempotency).
//
// WHY A HELPER MODULE: the workflow script cannot call MCP/CLI directly (§3.3) — every
// side-effect is an agent() call. This module owns the parts that make resume + idempotency
// honor their contracts WITHOUT bloating the loop, and — critically — keeps the PURE,
// deterministic half (blob parse → loop seed; git-command construction) separable and
// unit-testable WITHOUT a live sdlc-server:
//   1. rehydrate's blob → loop-seed reconstruction (the exact inverse of wave-status.js toBlob);
//   2. the rehydrate agent PROMPT (reads .claude/status/, returns the REHYDRATE blob);
//   3. the idempotent worktree setup + 3-point cleanup git-command builders + their agent prompts.
//
// IDEMPOTENCY (SEAMS invariant 3 + 5, §3.3): the crux of safe cross-session resume.
//   - rehydrate()'s `merged` set is AUTHORITATIVE for skip-on-resume. parseRehydrate is total:
//     a missing/corrupt blob degrades to a clean cold start (all issues pending), never throws.
//   - worktree setup reuses an existing branch on resume (`git worktree add <path> <branch>`,
//     never `-b`), so a killed-and-restarted run re-attaches the same worktree instead of failing.
//   - the worker half (status:"already-present") and the reconcile half ("skip if already in
//     kahuna") live in the workflow's agent prompts; this module supplies the structural pieces.

import { blobPath, statusDir } from './wave-status.js'

// ─────────────────────────────────────────────────────────────────────────────
// PURE — the rehydrate read-back half (no I/O, no agent; fully unit-testable).
// These are the exact inverse of wave-status.js toBlob(): blob → REHYDRATE loop seed.
// The loop (per-wave-workflow.js) seeds pending/merged/reworkCount/idleRounds/groupsRun
// from this; reworkCount numeric keys are JSON-stringified in the blob and the loop
// Number-casts them — parseRehydrate returns them faithfully (string-keyed object).
// ─────────────────────────────────────────────────────────────────────────────

// The empty/initial state for a cold start (no prior blob): every issue pending, nothing merged.
export function coldStart(allIssues) {
  return { merged: [], pending: [...(allIssues ?? [])].map(Number), reworkCount: {}, idleRounds: 0, groupsRun: 0 }
}

// Coerce one durable blob (as read from .claude/status/wave-<id>.json) into the REHYDRATE
// loop seed. TOTAL by construction — any missing/garbage field degrades safely so a resume
// never crashes on a half-written or schema-drifted blob (§3.3: a killed run must resume,
// not die again on its own resume). A terminal:'promoted' blob is NOT treated as resumable
// loop state by the per-wave workflow — that pruning is the campaign driver's job (§5) — but
// we still surface it so callers can decide; parseRehydrate only reconstructs the loop core.
//
// `allIssues` is the wave's full issue list: it backfills `pending` so an issue that is
// neither merged nor recorded-pending in a stale blob is still scheduled (never silently dropped).
export function parseRehydrate(blob, allIssues) {
  const all = [...(allIssues ?? [])].map(Number).filter(Number.isFinite)
  if (!blob || typeof blob !== 'object') return coldStart(all)

  const intList = (v) => (Array.isArray(v) ? v.map(Number).filter(Number.isFinite) : [])
  const merged = uniqSorted(intList(blob.merged))
  const mergedSet = new Set(merged)

  // pending = (blob.pending ∪ any allIssues not yet merged), minus anything already merged.
  // The union with allIssues is the safety net: a blob that forgot an issue still schedules it.
  const pendingBlob = intList(blob.pending)
  const backfill = all.filter((n) => !mergedSet.has(n))
  const pending = uniqSorted([...pendingBlob, ...backfill].filter((n) => !mergedSet.has(n)))

  // reworkCount: keep string-keyed (JSON-native); values coerced to finite non-negative ints.
  // The loop Number-casts the keys — we return them faithfully (no cast here) so the round-trip
  // is exactly what wave-status.js documents.
  const reworkCount = {}
  for (const [k, v] of Object.entries(blob.reworkCount ?? {})) {
    const nk = Number(k)
    const nv = Number(v)
    if (Number.isFinite(nk) && Number.isFinite(nv)) reworkCount[String(nk)] = Math.max(0, Math.trunc(nv))
  }

  const idleRounds = clampNonNeg(blob.idleRounds)
  const groupsRun = clampNonNeg(blob.groupsRun)

  return { merged, pending, reworkCount, idleRounds, groupsRun }
}

function uniqSorted(arr) {
  return [...new Set(arr)].sort((a, b) => a - b)
}
function clampNonNeg(v) {
  const n = Number(v)
  return Number.isFinite(n) && n > 0 ? Math.trunc(n) : 0
}

// ─────────────────────────────────────────────────────────────────────────────
// PURE — git command builders for the idempotent worktree lifecycle (§4.2/§4.3).
// Returned as argv-string commands so the agent prompt can run them verbatim AND a
// test can assert the exact shape (reuse-branch-not-`-b`, branch-prune, glob stem).
// All paths/branches share the `wave-<id>/` stem so one glob cleans dir + branch.
// ─────────────────────────────────────────────────────────────────────────────

// fs-safe wave id (mirror wave-status.js blobPath sanitization so dir/branch/blob agree).
export const safeWaveId = (waveId) => String(waveId).replace(/[^A-Za-z0-9._-]/g, '_')
export const wtRoot = (targetRepoDir, waveId) => `${targetRepoDir}/.claude/.worktrees/wave-${safeWaveId(waveId)}`
export const wtPathFor = (targetRepoDir, waveId, n) => `${wtRoot(targetRepoDir, waveId)}/issue-${n}`
export const issueBranchFor = (waveId, n) => `wave-${safeWaveId(waveId)}/issue-${n}`

// Setup (§4.2 + the §4.3 setup-sweep): for ONE issue, the idempotent create sequence.
// `branchExists` lets the caller (or test) pick the reuse path vs the create path:
//   - branch exists (resume): `git worktree add <path> <branch>` — REUSE, never -b.
//   - branch absent (fresh):  `git worktree add <path> -b <branch> origin/<kahuna>`.
// Either way a `prune` precedes so a stale registration from a crash doesn't block the add.
export function worktreeSetupCmds({ targetRepoDir, waveId, kahunaBranch, issue, branchExists }) {
  const path = wtPathFor(targetRepoDir, waveId, issue)
  const branch = issueBranchFor(waveId, issue)
  const g = `git -C ${q(targetRepoDir)}`
  const add = branchExists
    ? `${g} worktree add ${q(path)} ${q(branch)}` // reuse existing branch on resume (NEVER -b)
    : `${g} worktree add ${q(path)} -b ${q(branch)} ${q(`origin/${kahunaBranch}`)}`
  return [
    `${g} worktree prune`, // crash recovery: drop stale registrations before (re)attaching
    add,
  ]
}

// Per-merge cleanup (§4.3): the 4-point sequence for ONE just-merged issue.
// worktree remove --force → worktree prune → rm -rf → git branch -D wave-<id>/issue-<n>.
// `worktree remove` leaves the branch behind, so the explicit branch -D is load-bearing
// (pilot 1 accreted dead refs without it). Every step tolerates already-absent (idempotent).
export function cleanupMergedCmds({ targetRepoDir, waveId, issue }) {
  const path = wtPathFor(targetRepoDir, waveId, issue)
  const branch = issueBranchFor(waveId, issue)
  const g = `git -C ${q(targetRepoDir)}`
  return [
    `${g} worktree remove --force ${q(path)}`,
    `${g} worktree prune`,
    `rm -rf ${q(path)}`,
    `${g} branch -D ${q(branch)}`,
  ]
}

// Wave-terminal cleanup (§4.3): sweep the wave's REMAINING worktrees + prune + glob-delete
// every wave-<id>/* branch. The dir and branches share the wave-<id> stem so a single glob
// (`git branch -D wave-<id>/*`, plus rm -rf of the wave dir) cleans both.
export function cleanupTerminalCmds({ targetRepoDir, waveId }) {
  const root = wtRoot(targetRepoDir, waveId)
  const branchGlob = `wave-${safeWaveId(waveId)}/*`
  const g = `git -C ${q(targetRepoDir)}`
  return [
    // remove each remaining registered worktree under the wave root, then prune the registry
    `for wt in ${q(root)}/issue-*; do [ -e "$wt" ] && ${g} worktree remove --force "$wt" 2>/dev/null || true; done`,
    `${g} worktree prune`,
    `rm -rf ${q(root)}`,
    // delete every branch under the wave stem (worktree remove leaves branches behind).
    // SINGLE-QUOTE the refs pattern: it is a git ref-glob, NOT a shell glob — unquoted, a shell with
    // nullglob/failglob set would expand it against the cwd (→ empty/error → for-each-ref lists ALL
    // refs → branch -D nukes every local branch). safeWaveId guarantees [A-Za-z0-9._-], so the quote is safe.
    `${g} for-each-ref --format='%(refname:short)' 'refs/heads/${branchGlob}' | xargs -r ${g} branch -D`,
  ]
}

// minimal single-quote shell-quoter (paths/branches here are repo-controlled, never user input,
// but quoting keeps spaces + the for-each-ref glob honest).
function q(s) {
  return `'${String(s).replace(/'/g, `'\\''`)}'`
}

// ─────────────────────────────────────────────────────────────────────────────
// AGENT PROMPTS — the I/O half (the script can't read files / run git directly, §3.3).
// Each is a string the workflow hands to agent(); the structured return is asserted by
// the workflow's schema. These are NOT exercised by the unit test (they need a live
// agent/filesystem); the test pins the pure halves above.
// ─────────────────────────────────────────────────────────────────────────────

// rehydrate: read the durable blob and return the REHYDRATE loop seed. The agent reads the
// file (cheap read-only op); the per-wave workflow seeds its loop variables from the return.
// Cold start (no file) → all issues pending. Warm start → the persisted loop core, faithfully.
export function rehydratePrompt({ waveId, allIssues, targetRepo, targetRepoDir }) {
  const path = blobPath(targetRepoDir, waveId)
  const dir = statusDir(targetRepoDir)
  return [
    `You are the wave REHYDRATE node for wave ${waveId} of ${targetRepo}. Your ONLY job: read the durable`,
    `wave-status blob and return the loop seed so a cold-started run resumes exactly where it died (§3.3).`,
    `Do NOT do any other work — no git, no MCP, no implementation. This is a cheap read-only read.`,
    ``,
    `STEP 1 — read the durable blob (durable resume state lives under .claude/status/, NEVER /tmp):`,
    `  Read the file: ${path}`,
    `  (Its parent dir is ${dir}. If the file does NOT exist, this is a COLD START.)`,
    ``,
    `STEP 2 — return the loop seed:`,
    `  COLD START (file absent / empty / unparseable JSON): return`,
    `    merged=[], pending=[${[...(allIssues ?? [])].map(Number).join(', ')}], reworkCount={}, idleRounds=0, groupsRun=0.`,
    `  WARM START (file parses): return its fields VERBATIM —`,
    `    merged   = the blob's "merged" array (issues already on kahuna; the loop SKIPS these),`,
    `    pending  = the blob's "pending" array (issues still to do),`,
    `    reworkCount = the blob's "reworkCount" object EXACTLY (keys are issue numbers as strings —`,
    `                  do NOT renumber or drop them; the loop Number-casts the keys itself),`,
    `    idleRounds  = the blob's "idleRounds" (integer, default 0),`,
    `    groupsRun   = the blob's "groupsRun" (integer, default 0).`,
    `  If a field is missing from an otherwise-valid blob, default it (merged/pending → [], reworkCount → {},`,
    `  idleRounds/groupsRun → 0). Any issue in [${[...(allIssues ?? [])].map(Number).join(', ')}] that is`,
    `  neither merged nor pending in the blob MUST be added to pending (never silently dropped).`,
    ``,
    `Return: merged (int[]), pending (int[]), reworkCount (object), idleRounds (int), groupsRun (int).`,
  ].join('\n')
}

// setupWorktrees: idempotent create of one worktree PER issue in the group, as a single awaited
// step before parallel() (race-safety is structural, §4.2). Reuse an existing branch on resume
// (never -b). First sweep PRIOR wave-ids' dirs + prune (crash recovery, §4.3). Returns issue→path.
export function setupWorktreesPrompt({ waveId, targetRepo, targetRepoDir, kahunaBranch, group }) {
  const root = wtRoot(targetRepoDir, waveId)
  const pairs = group.map((n) => ({
    issue: n,
    path: wtPathFor(targetRepoDir, waveId, n),
    branch: issueBranchFor(waveId, n),
  }))
  return [
    `You are the wave WORKTREE-SETUP node for wave ${waveId} of ${targetRepo}. Pre-create one durable`,
    `worktree per issue in this group, IDEMPOTENTLY, then return the issue→path map. This is the SINGLE`,
    `awaited step before the parallel workers run — workers are HANDED a path, they never create one (§4.2).`,
    `Do NOT implement anything. Operate in the TARGET clone: ${targetRepoDir}.`,
    ``,
    `STEP 0 — crash-recovery sweep (§4.3): prune stale registrations and remove any PRIOR wave's worktree`,
    `  dirs under ${targetRepoDir}/.claude/.worktrees/ whose stem is NOT wave-${safeWaveId(waveId)} (the`,
    `  CURRENT wave's dir is PRESERVED + re-attached, not swept). Run: git -C ${targetRepoDir} worktree prune.`,
    ``,
    `STEP 1 — per issue, create-or-reuse (idempotent, §4.2). For EACH issue below, in order:`,
    ...pairs.map(
      (p) =>
        `  • issue #${p.issue}: branch ${p.branch}, path ${p.path}.\n` +
        `      If ${p.path} is ALREADY a registered worktree → reuse it as-is (no-op).\n` +
        `      Else if branch ${p.branch} ALREADY exists → git -C ${targetRepoDir} worktree add ${p.path} ${p.branch}  (REUSE the branch — NEVER -b).\n` +
        `      Else (fresh) → git -C ${targetRepoDir} worktree add ${p.path} -b ${p.branch} origin/${kahunaBranch}.`,
    ),
    ``,
    `Worktree root for this wave: ${root} (durable, gitignored — NOT /tmp). The dir + branch share the`,
    `wave-${safeWaveId(waveId)}/ stem so a later glob cleans both.`,
    ``,
    `Return: a "worktrees" object mapping each issue number (as a string key) to its ABSOLUTE worktree path,`,
    `e.g. ${JSON.stringify(Object.fromEntries(pairs.map((p) => [String(p.issue), p.path])))}.`,
  ].join('\n')
}

// cleanupMerged: per just-merged issue, the 4-point removal (§4.3). Keeps peak disk ≈ current group.
export function cleanupMergedPrompt({ waveId, targetRepo, targetRepoDir, issues }) {
  const blocks = issues.map((n) => ({ issue: n, cmds: cleanupMergedCmds({ targetRepoDir, waveId, issue: n }) }))
  return [
    `You are the wave CLEANUP node (per-merge) for wave ${waveId} of ${targetRepo}. Remove the worktree`,
    `AND branch for each just-merged issue so peak disk stays ≈ the current group (§4.3). IDEMPOTENT:`,
    `every step tolerates already-absent — never fail the wave on a missing worktree/branch.`,
    ``,
    `For EACH issue below, run the 4-point sequence in order (worktree remove --force → worktree prune →`,
    `rm -rf → branch -D; the branch -D is load-bearing — worktree remove leaves the branch behind):`,
    ...blocks.flatMap((b) => [`  • issue #${b.issue}:`, ...b.cmds.map((c) => `      ${c}`)]),
    ``,
    `Return: persisted=true once done; recorded = the issue numbers you cleaned; notes (any soft error).`,
  ].join('\n')
}

// cleanupTerminal: wave-terminal sweep (§4.3) — remaining worktrees + prune + glob-delete every branch.
export function cleanupTerminalPrompt({ waveId, targetRepo, targetRepoDir }) {
  const cmds = cleanupTerminalCmds({ targetRepoDir, waveId })
  return [
    `You are the wave CLEANUP node (terminal) for wave ${waveId} of ${targetRepo}. The wave has ended`,
    `(promoted or held) — reclaim disk: remove the wave's REMAINING worktrees + prune + delete every`,
    `wave-${safeWaveId(waveId)}/* branch (§4.3). IDEMPOTENT: tolerate already-absent. Operate in ${targetRepoDir}.`,
    ``,
    `Run, in order (the branch glob is load-bearing — worktree remove leaves branches behind):`,
    ...cmds.map((c) => `  ${c}`),
    ``,
    `Return: persisted=true once done; notes (any soft error — never halt on one).`,
  ].join('\n')
}
