// wave_status_persist_roundtrip.mjs — #688 wave-status persistence round-trip test.
//
// Asserts the load-bearing #688 invariant: the durable loop blob persistIteration writes
// is the EXACT blob rehydrate() (#686) reads back to seed {merged, pending, reworkCount,
// idleRounds, groupsRun}. We exercise the pure, deterministic half end-to-end:
//   loop state (Sets + numeric-keyed reworkCount)
//     → toBlob() (the serializer persistIteration uses)
//     → JSON write to a temp .claude/status/ file (NOT /tmp resume state; tmp is only the
//       test fixture dir — lesson_tmp_identity_boot_wipe is about RESUME state, fine for a test)
//     → read back + JSON.parse
//     → reconstruct the loop seed the way per-wave-workflow.js does (numeric-key cast)
//     → assert deep-equal to the original state.
//
// The agent()-driven side-effects (wave_record_mr / wave_close_issue) are NOT exercised here
// (they need a live sdlc-server); this pins the serialization + numeric-key round-trip, which
// is what makes a killed run resumable.

import { mkdtempSync, writeFileSync, readFileSync, mkdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import assert from 'node:assert/strict'
import { toBlob, blobPath, statusDir, persistTerminalPrompt } from '../../skills/nextwave/wave-status.js'

let failures = 0
const ok = (name) => console.log(`  [PASS] ${name}`)
const bad = (name, e) => { console.log(`  [FAIL] ${name}: ${e?.message || e}`); failures++ }

console.log('test_wave_status_persist_roundtrip')
console.log('──────────────────────────────────────────')

// Mirror per-wave-workflow.js's rehydrate seed (lines ~319-325): numeric-cast reworkCount keys,
// Sets become arrays. This is the exact re-read a future rehydrate() must reproduce.
function seedFromBlob(blob) {
  return {
    merged: new Set((blob.merged || []).map(Number)),
    pending: new Set((blob.pending || []).map(Number)),
    reworkCount: Object.fromEntries(Object.entries(blob.reworkCount || {}).map(([k, v]) => [Number(k), v])),
    idleRounds: blob.idleRounds || 0,
    groupsRun: Number(blob.groupsRun) || 0,
  }
}

// ── Fixture: a mid-wave loop state (the live in-memory shape persistIteration receives) ──
const state = {
  waveId: 'W-7',
  merged: new Set([12, 3, 45]),         // unsorted on purpose — toBlob sorts deterministically
  pending: new Set([8, 100]),
  reworkCount: { 8: 2, 45: 1 },          // numeric keys (loop-native)
  idleRounds: 1,
  groupsRun: 4,
}

const root = mkdtempSync(join(tmpdir(), 'wave-688-rt-'))
try {
  // 1. serialize via the production serializer
  const blob = toBlob(state)

  // path lands under <repoDir>/.claude/status/ and is wave-id-scoped + fs-safe
  try {
    const dir = statusDir(root)
    const path = blobPath(root, state.waveId)
    assert.equal(path, join(root, '.claude', 'status', 'wave-W-7.json'))
    assert.ok(path.startsWith(dir), 'blob path under .claude/status/')
    assert.ok(!path.includes('/tmp/wavemachine'), 'resume state not on the tmp bus')
    ok('blobPath is wave-scoped under .claude/status/')

    // 2. write the durable blob (the persist agent does mkdir -p + overwrite; we mirror it)
    mkdirSync(dir, { recursive: true })
    writeFileSync(path, JSON.stringify(blob, null, 2))

    // 3. read back + parse (the rehydrate agent's job)
    const reread = JSON.parse(readFileSync(path, 'utf8'))

    // 4. reconstruct the loop seed and assert it equals the original live state
    const seed = seedFromBlob(reread)
    assert.deepEqual([...seed.merged].sort((a, b) => a - b), [3, 12, 45])
    assert.deepEqual([...seed.pending].sort((a, b) => a - b), [8, 100])
    assert.deepEqual(seed.reworkCount, { 8: 2, 45: 1 })
    assert.equal(seed.idleRounds, 1)
    assert.equal(seed.groupsRun, 4)
    ok('loop state round-trips through blob (merged/pending/reworkCount/idleRounds/groupsRun)')

    // reworkCount keys are numeric after re-read (JSON stringifies them; rehydrate Number-casts)
    for (const k of Object.keys(seed.reworkCount)) {
      assert.equal(typeof k, 'string') // object keys are always strings in JS...
      assert.ok(Number.isInteger(Number(k))) // ...but each is a clean integer, never NaN
    }
    ok('reworkCount keys survive as clean integers (JSON-string ↔ numeric)')

    // 5. idempotency: re-serializing + re-writing identical state yields byte-identical file
    writeFileSync(path, JSON.stringify(toBlob(state), null, 2))
    const reread2 = readFileSync(path, 'utf8')
    assert.equal(reread2, JSON.stringify(blob, null, 2))
    ok('persist is idempotent (replaying same state → byte-identical blob)')

    // 6. terminal stamp folds into the same blob shape
    const terminalBlob = toBlob({ ...state, terminal: { disposition: 'promoted', detail: 'gate PASS', at: null } })
    assert.equal(terminalBlob.terminal.disposition, 'promoted')
    assert.deepEqual(terminalBlob.merged, blob.merged) // loop state preserved alongside terminal
    ok('terminal disposition folds into the durable blob without disturbing loop state')

    // 7. ENG-1/#846: persistTerminalPrompt STEP 1 branches on disposition —
    //    promoted → `wave-status complete <waveId>`; held → `wave-status hold-wave <waveId>`.
    //    A held wave must NEVER emit `complete` (writing completed on a non-promoted exit
    //    corrupts durable resume/prune state).
    const promoteArgs = {
      waveId: 'W-7', targetRepo: 'o/r', targetRepoDir: '/clone', kahunaBranch: 'kahuna/1-x',
      integrationBase: 'campaign/1-x', disposition: 'promoted', detail: 'gate PASS',
      blob: toBlob(state), path: '/clone/.claude/status/wave-W-7.json', trajectoryEntry: {},
    }
    const promotePrompt = persistTerminalPrompt(promoteArgs)
    assert.ok(promotePrompt.includes('wave-status complete W-7'), 'promoted → wave-status complete <waveId>')
    assert.ok(!promotePrompt.includes('wave-status hold-wave'), 'promoted must NOT hold-wave')
    ok('persistTerminalPrompt promoted-branch emits `wave-status complete <waveId>`')

    const heldPrompt = persistTerminalPrompt({ ...promoteArgs, disposition: 'held', detail: 'gate HOLD: ci' })
    assert.ok(heldPrompt.includes('wave-status hold-wave W-7'), 'held → wave-status hold-wave <waveId>')
    assert.ok(!/wave-status complete\b/.test(heldPrompt), 'held must NEVER call `complete`')
    ok('persistTerminalPrompt held-branch emits `hold-wave`, never `complete`')

    // #1052: the prompt states WHERE the wave landed, and that ref is `integrationBase` (the campaign
    // branch inside a campaign), not the protected branch. Asserted because this test previously
    // passed while rendering `undefined` into both branches of the prompt — it named the base nowhere,
    // so a renamed parameter was invisible here and only failed in a sibling suite.
    for (const [label, p] of [['promoted', promotePrompt], ['held', heldPrompt]]) {
      assert.ok(p.includes('campaign/1-x'), `${label} prompt must name the integration base it landed on (or did not)`)
      assert.ok(!/undefined/.test(p), `${label} prompt must not render undefined (renamed/missing param)`)
    }
    ok('persistTerminalPrompt names the integrationBase in both branches, never `undefined` (#1052)')
  } catch (e) {
    bad('round-trip', e)
  }
} finally {
  rmSync(root, { recursive: true, force: true })
}

console.log('')
if (failures) { console.log(`  ${failures} assertion group(s) failed`); process.exit(1) }
console.log('  all wave-status persist round-trip checks passed')
