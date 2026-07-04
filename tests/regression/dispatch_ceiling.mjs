// dispatch_ceiling.mjs — #824 (Story 1.2) IT-02: the per-wave DISPATCH ceiling.
//
// Asserts on the ENGINE's group plan, not on SKILL.md prose (the wave-1a review-gate finding):
// applyDispatchCeiling() is the exact function per-wave-workflow.js's flight loop calls on every
// planner-produced flight-group to honor the wave's `dispatch` hint, so exercising it here pins the
// executor's real dispatch behavior without a live sdlc-server (same unit-testable-pure-half pattern
// as wave_status_persist_roundtrip.mjs). The .sh wrapper additionally greps source + bundle to prove
// the loop actually CALLS this function (the enforcement path can't silently vanish).
//
// Contract under test:
//   fan                          → planner's parallel group as-is (file-conflict floor preserved)
//   serialize / serialize-pref / → single-file (one issue per group); the rest re-schedule next loop
//     absent / unknown             (CT-01: absent → serialize, backward-compatible default)
//   CEILING invariant            → output length ≤ input length for EVERY dispatch (never widens)

import assert from 'node:assert/strict'
import { applyDispatchCeiling, normalizeDispatch } from '../../skills/nextwave/dispatch.js'

let failures = 0
const ok = (name) => console.log(`  [PASS] ${name}`)
const bad = (name, e) => { console.log(`  [FAIL] ${name}: ${e?.message || e}`); failures++ }
const check = (name, fn) => { try { fn(); ok(name) } catch (e) { bad(name, e) } }

console.log('test_dispatch_ceiling (IT-02)')
console.log('──────────────────────────────────────────')

const G = [7, 2, 3] // 7 first ⇒ surfaced-rework priority the planner encodes; must be preserved

// ── fan → parallel group unchanged (R-06) ──
check('fan → planner parallel group unchanged', () => {
  assert.deepEqual(applyDispatchCeiling(G, 'fan'), [7, 2, 3])
})

// ── serialize → single-file, first-issue-preserving (R-06) ──
check('serialize → single-file group [first]', () => {
  assert.deepEqual(applyDispatchCeiling(G, 'serialize'), [7])
})
check('serialize-preferred → single-file (no operator opt-in at exec time)', () => {
  assert.deepEqual(applyDispatchCeiling(G, 'serialize-preferred'), [7])
})

// ── CT-01: absent / null / unknown → serialize (single-file) ──
check('absent (undefined) → single-file [CT-01 default]', () => {
  assert.deepEqual(applyDispatchCeiling(G, undefined), [7])
})
check('null → single-file [CT-01]', () => {
  assert.deepEqual(applyDispatchCeiling(G, null), [7])
})
check('unknown string → single-file (conservative; never accidentally fan)', () => {
  assert.deepEqual(applyDispatchCeiling(G, 'parallel-please'), [7])
})

// ── case / whitespace tolerance (hand-edited phases-waves.json) ──
check('" Fan " (case/space) → parallel', () => {
  assert.deepEqual(applyDispatchCeiling(G, ' Fan '), [7, 2, 3])
})

// ── CEILING invariant: output length ≤ input length for EVERY dispatch (never widens, never adds) ──
check('ceiling: fan never widens the planner group', () => {
  assert.ok(applyDispatchCeiling(G, 'fan').length <= G.length)
})
check('ceiling: serialize collapses to ≤ 1 issue', () => {
  for (const d of ['serialize', 'serialize-preferred', undefined, null, 'junk']) {
    assert.ok(applyDispatchCeiling(G, d).length <= 1, `dispatch=${String(d)}`)
  }
})
check('ceiling: output is always a subset-prefix of the input (no invented issues)', () => {
  for (const d of ['fan', 'serialize', 'serialize-preferred', undefined]) {
    const out = applyDispatchCeiling(G, d)
    assert.deepEqual(out, G.slice(0, out.length), `dispatch=${String(d)}`)
  }
})

// ── single-issue group is unaffected by ANY dispatch (already single-file) ──
check('single-issue group unchanged under fan and serialize', () => {
  assert.deepEqual(applyDispatchCeiling([9], 'fan'), [9])
  assert.deepEqual(applyDispatchCeiling([9], 'serialize'), [9])
})

// ── empty group → empty (no crash; nothing to build) ──
check('empty group → empty for fan and serialize', () => {
  assert.deepEqual(applyDispatchCeiling([], 'fan'), [])
  assert.deepEqual(applyDispatchCeiling([], 'serialize'), [])
})
check('non-array group → empty (defensive)', () => {
  assert.deepEqual(applyDispatchCeiling(undefined, 'fan'), [])
  assert.deepEqual(applyDispatchCeiling(null, 'serialize'), [])
})

// ── normalizeDispatch: canonical tokens + CT-01 default ──
check('normalizeDispatch canonicalizes and defaults absent → serialize', () => {
  assert.equal(normalizeDispatch('fan'), 'fan')
  assert.equal(normalizeDispatch('serialize'), 'serialize')
  assert.equal(normalizeDispatch('serialize-preferred'), 'serialize-preferred')
  assert.equal(normalizeDispatch('FAN'), 'fan')
  assert.equal(normalizeDispatch(undefined), 'serialize')
  assert.equal(normalizeDispatch(null), 'serialize')
  assert.equal(normalizeDispatch(''), 'serialize')
  assert.equal(normalizeDispatch('nonsense'), 'serialize')
})

console.log('──────────────────────────────────────────')
if (failures) {
  console.log(`  ${failures} assertion(s) FAILED`)
  process.exit(1)
}
console.log('  all dispatch-ceiling (IT-02) assertions passed')
