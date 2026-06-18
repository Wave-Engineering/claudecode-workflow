// resume_rehydrate_roundtrip.mjs — #686 resumability + idempotency round-trip test.
//
// Asserts the load-bearing #686 invariant: a wave-status blob representing a MID-RUN state
// (some issues merged, some pending, a reworkCount) rehydrates to the EXACT loop seed
// {merged, pending, reworkCount, idleRounds, groupsRun} the per-wave Workflow needs to SKIP
// finished work — including the numeric-key round-trip (reworkCount keys are JSON-stringified
// in the blob; the loop Number-casts them, parseRehydrate returns them faithfully string-keyed).
//
// WHAT THIS PROVES (the pure, deterministic half — no live sdlc-server needed):
//   1. toBlob (the #688 serializer persistIteration writes) → JSON file → parseRehydrate (the
//      #686 read-back rehydrate() drives) reconstructs the original loop state exactly. A resumed
//      loop seeds `merged` (authoritative skip set, SEAMS invariant 3) so it does NOT redo merged
//      issues — the kill-resume AC's "already-merged issues are skipped" at the state level.
//   2. Idempotency / stability: re-applying the same rehydrated state (re-serialize → re-parse) is
//      a fixed point — byte-identical blob, identical seed. A killed-and-restarted run that
//      re-rehydrates lands on the same state, never drifting.
//   3. Robustness: a missing / empty / corrupt / partial blob degrades to a clean COLD start (all
//      issues pending, nothing merged) — a killed run resumes, it never dies on its own restart.
//   4. The idempotent worktree-setup + 3-point-cleanup git COMMANDS are correctly shaped:
//      reuse-branch-on-resume (never -b), branch -D present (worktree remove leaves it behind),
//      and dir + branch + cleanup-glob share one wave-<id> stem (§4.2/§4.3, pilot-validated).
//
// WHAT THIS DOES NOT PROVE (needs a live sdlc-server — documented, not faked):
//   The FULL live kill-resume — start a real multi-group wave, kill it mid-reconcile, restart,
//   and observe the resumed run skip already-merged issues with no duplicate merges — is an
//   INTEGRATION test. It exercises the agent()-driven side-effects (wave_record_mr / wave_close_issue
//   on merge, the rehydrate/worktree/cleanup agents actually reading files + running git, the
//   worker's status:"already-present" re-entry, the reconcile "already in kahuna → skip"). Those
//   are NOT exercised here. To run it: see the HOW-TO block at the bottom of this file.

import { mkdtempSync, writeFileSync, readFileSync, mkdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import assert from 'node:assert/strict'
import { toBlob, blobPath, statusDir } from '../../skills/nextwave-next/wave-status.js'
import {
  parseRehydrate,
  coldStart,
  worktreeSetupCmds,
  cleanupMergedCmds,
  cleanupTerminalCmds,
  issueBranchFor,
  wtPathFor,
} from '../../skills/nextwave-next/resume.js'

let failures = 0
const ok = (name) => console.log(`  [PASS] ${name}`)
const bad = (name, e) => { console.log(`  [FAIL] ${name}: ${e?.message || e}`); failures++ }

console.log('test_resume_rehydrate_roundtrip')
console.log('──────────────────────────────────────────')

// The wave's full issue list — backfill safety net (an issue absent from a stale blob must still schedule).
const ALL_ISSUES = [3, 8, 12, 45, 100]

// ── Fixture: a MID-RUN loop state (the live in-memory shape persistIteration receives) ──
// merged 3 issues, 2 still pending, with a reworkCount (numeric, loop-native keys), mid-thrash.
const midRun = {
  waveId: 'W-7',
  merged: new Set([12, 3, 45]), // unsorted on purpose — toBlob sorts deterministically
  pending: new Set([8, 100]),
  reworkCount: { 8: 2, 45: 1 }, // numeric keys (loop-native)
  idleRounds: 1,
  groupsRun: 4,
}

const root = mkdtempSync(join(tmpdir(), 'wave-686-rt-'))
try {
  // ── 1. write the durable mid-run blob, then rehydrate it back to the loop seed ──────────
  try {
    const blob = toBlob(midRun)
    const dir = statusDir(root)
    const path = blobPath(root, midRun.waveId)
    assert.ok(path.startsWith(dir) && !path.includes('/tmp/wavemachine'), 'resume state under .claude/status/, not the tmp bus')
    mkdirSync(dir, { recursive: true })
    writeFileSync(path, JSON.stringify(blob, null, 2))

    // rehydrate = read back + parseRehydrate (what rehydrate() returns from the agent's file read)
    const reread = JSON.parse(readFileSync(path, 'utf8'))
    const seed = parseRehydrate(reread, ALL_ISSUES)

    // the loop seeds Sets + Number-casts reworkCount keys exactly as per-wave-workflow.js does
    assert.deepEqual(seed.merged, [3, 12, 45], 'merged set reconstructed (the authoritative skip set)')
    assert.deepEqual(seed.pending, [8, 100], 'pending set reconstructed')
    assert.deepEqual(seed.reworkCount, { 8: 2, 45: 1 }, 'reworkCount round-trips (numeric ↔ JSON-string keys)')
    assert.equal(seed.idleRounds, 1, 'idleRounds (thrash counter) restored')
    assert.equal(seed.groupsRun, 4, 'groupsRun (MAX_GROUPS bound seed) restored')

    // the load-bearing resume guarantee: a resumed loop SKIPS the merged issues.
    for (const m of [3, 12, 45]) assert.ok(!seed.pending.includes(m), `merged #${m} is NOT re-scheduled`)
    ok('mid-run state rehydrates to a loop seed that skips finished work (merged/pending/reworkCount/idleRounds/groupsRun)')

    // reworkCount keys survive as clean integers (JSON stringifies them; the loop Number-casts)
    for (const k of Object.keys(seed.reworkCount)) {
      assert.equal(typeof k, 'string')
      assert.ok(Number.isInteger(Number(k)) && Number(k) >= 0)
    }
    ok('reworkCount keys survive as clean non-negative integers (JSON-string ↔ numeric)')
  } catch (e) { bad('mid-run rehydrate', e) }

  // ── 2. idempotency / stability: re-applying the rehydrated state is a fixed point ───────
  try {
    const blob = toBlob(midRun)
    const seed = parseRehydrate(blob, ALL_ISSUES)
    // feed the rehydrated seed straight back through the serializer → re-parse: must be stable.
    const reseed = parseRehydrate(toBlob({
      waveId: 'W-7',
      merged: seed.merged,
      pending: seed.pending,
      reworkCount: seed.reworkCount,
      idleRounds: seed.idleRounds,
      groupsRun: seed.groupsRun,
    }), ALL_ISSUES)
    assert.deepEqual(reseed, seed, 're-rehydrating the same state is a fixed point (no drift on resume)')
    // and the blob itself is byte-identical on replay (the #688 idempotent-overwrite contract)
    assert.equal(JSON.stringify(toBlob(midRun)), JSON.stringify(blob), 'replaying same state → byte-identical blob')
    ok('rehydrate is idempotent — a killed-and-restarted run re-rehydrates to the identical state')
  } catch (e) { bad('idempotent reseed', e) }

  // ── 3. robustness: missing / empty / corrupt / partial blob → clean COLD start ──────────
  try {
    const cold = coldStart(ALL_ISSUES)
    assert.deepEqual(parseRehydrate(null, ALL_ISSUES), cold, 'no blob (cold start) → all pending, nothing merged')
    assert.deepEqual(parseRehydrate({}, ALL_ISSUES), cold, 'empty blob → all pending')
    assert.deepEqual(parseRehydrate('garbage', ALL_ISSUES), cold, 'non-object blob → cold start, never throws')
    // a partial blob (merged only) backfills pending from ALL_ISSUES minus merged (never drops an issue)
    const partial = parseRehydrate({ merged: [3, 12] }, ALL_ISSUES)
    assert.deepEqual(partial.merged, [3, 12])
    assert.deepEqual(partial.pending, [8, 45, 100], 'partial blob backfills pending from the wave issue list')
    // a blob that merged an issue NOT in ALL_ISSUES keeps it merged (still skipped) without crashing
    const extra = parseRehydrate({ merged: [3, 999], pending: [8] }, ALL_ISSUES)
    assert.ok(extra.merged.includes(999) && !extra.pending.includes(999), 'unknown merged issue stays skipped')
    // adversarial: a blob (or hallucinated agent return) with a merged issue ALSO in pending must never re-schedule it
    const overlap = parseRehydrate({ merged: [3, 12], pending: [3, 8, 100] }, ALL_ISSUES)
    assert.ok(!overlap.pending.includes(3), 'overlap: a merged issue is removed from pending (no re-do of merged work)')
    assert.ok(overlap.pending.includes(8) && overlap.pending.includes(100), 'overlap: non-merged pending preserved')
    ok('a missing/empty/corrupt/partial blob degrades to a safe state — a killed run resumes, never dies on restart')
  } catch (e) { bad('robust cold start', e) }

  // ── 4. idempotent worktree-setup + 3-point cleanup git commands are correctly shaped ────
  try {
    const targetRepoDir = '/home/x/ccwork-testtarget'
    const waveId = 'W-7'
    const kahunaBranch = 'kahuna/W-7'

    // RESUME path: branch already exists → reuse it, NEVER -b (the §4.2 idempotency crux)
    const reuse = worktreeSetupCmds({ targetRepoDir, waveId, kahunaBranch, issue: 8, branchExists: true })
    assert.ok(reuse.some((c) => c.includes('worktree prune')), 'setup prunes stale registrations first (crash recovery)')
    const reuseAdd = reuse.find((c) => c.includes('worktree add'))
    assert.ok(!reuseAdd.includes(' -b '), 'resume reuses the existing branch — NEVER -b (would fail if branch exists)')
    assert.ok(reuseAdd.includes(issueBranchFor(waveId, 8)), 'reuse add names the existing wave branch')

    // FRESH path: branch absent → create with -b off origin/<kahuna>
    const fresh = worktreeSetupCmds({ targetRepoDir, waveId, kahunaBranch, issue: 8, branchExists: false })
    const freshAdd = fresh.find((c) => c.includes('worktree add'))
    assert.ok(freshAdd.includes(' -b '), 'fresh create uses -b')
    assert.ok(freshAdd.includes(`origin/${kahunaBranch}`), 'fresh branch is based on origin/<kahuna>')
    ok('worktree setup is idempotent: reuse-branch-on-resume (never -b), -b only on fresh create')

    // per-merge cleanup = the 4-point sequence, branch -D included, correct order
    const cm = cleanupMergedCmds({ targetRepoDir, waveId, issue: 45 })
    assert.equal(cm.length, 4, '4-point cleanup')
    assert.ok(cm[0].includes('worktree remove --force'), '1: worktree remove --force')
    assert.ok(cm[1].includes('worktree prune'), '2: worktree prune')
    assert.ok(cm[2].startsWith('rm -rf'), '3: rm -rf')
    assert.ok(cm[3].includes('branch -D') && cm[3].includes(issueBranchFor(waveId, 45)),
      '4: branch -D the wave branch (worktree remove leaves the branch behind — pilot-1 dead-ref bug)')
    assert.ok(cm.some((c) => c.includes(wtPathFor(targetRepoDir, waveId, 45))), 'cleanup targets the issue worktree path')
    ok('per-merge cleanup is the 4-point §4.3 sequence with the load-bearing branch -D')

    // terminal cleanup glob shares the wave-<id> stem (single glob cleans dir + branch)
    const ct = cleanupTerminalCmds({ targetRepoDir, waveId })
    assert.ok(ct.some((c) => c.includes('worktree prune')), 'terminal prunes the registry')
    assert.ok(ct.some((c) => c.includes(`wave-${waveId}/`)), 'terminal branch glob shares the wave-<id>/ stem (§4.3 — dir+branch one glob)')
    assert.ok(ct.some((c) => c.includes('branch -D')), 'terminal deletes wave branches, not just worktrees')
    ok('terminal cleanup sweeps remaining worktrees + glob-deletes wave-<id>/* branches (both ends, §4.3)')
  } catch (e) { bad('worktree/cleanup command shape', e) }
} finally {
  rmSync(root, { recursive: true, force: true })
}

console.log('')
if (failures) { console.log(`  ${failures} assertion group(s) failed`); process.exit(1) }
console.log('  all #686 resume + idempotency round-trip checks passed')

// ─────────────────────────────────────────────────────────────────────────────────────────
// HOW TO RUN THE FULL LIVE KILL-AND-RESUME INTEGRATION TEST (requires a live sdlc-server)
// ─────────────────────────────────────────────────────────────────────────────────────────
// The pure half above proves the SERIALIZATION + idempotency contract. The end-to-end AC —
// "a killed run resumes to an identical final state with no duplicated side effects" — is an
// integration test that the unit harness CANNOT cover, because it needs the agent()-driven
// side-effects against a real sdlc-server + a real target repo. To run it manually:
//
//   1. Provision a throwaway target repo + a multi-group wave (e.g. ccwork-testtarget, 4-5 issues
//      with one cross-group dependency so the loop runs ≥2 groups).
//   2. Launch the per-wave Workflow (skills/nextwave-next/per-wave-workflow.js) via the SDK
//      Workflow({ scriptPath }) with { waveId, targetRepo, targetRepoDir, kahunaBranch, issues }.
//   3. KILL the process mid-reconcile of group 2 (after group 1's issues merged + persistIteration
//      wrote .claude/status/wave-<id>.json, before the wave completes). Confirm the durable blob on
//      disk shows group-1 issues in `merged`.
//   4. RESTART the same Workflow with the same input (cold start — no resumeFromRunId). rehydrate()
//      reads the blob; the loop seeds `merged` and SKIPS group 1; setupWorktrees reuses the existing
//      branches (never -b); the worker returns status:"already-present" for anything already done;
//      reconcile SKIPS branches already in kahuna.
//   5. ASSERT: the resumed run's final merged set == an uninterrupted run's; NO issue's MR is
//      recorded twice (wave_record_mr is issue-keyed/idempotent); NO branch is double-merged; the
//      target repo has no duplicate commits on kahuna.
//
// This file deliberately does NOT claim that path is automated. It is the remaining manual gate.
