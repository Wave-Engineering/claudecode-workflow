// dispatch.js — #824 (Story 1.2, Plan #822): the per-wave DISPATCH ceiling.
//
// Design of record: docs/executor-model-devspec.md §8 Story 1.2.
//
// WHAT THIS IS: the pure, deterministic enforcement half of the wave `dispatch` hint that
// /prepwaves (#823, Story 1.1) writes onto each wave in phases-waves.json. /nextwave threads
// that field into the per-wave Workflow's `args` (args.dispatch), and per-wave-workflow.js's
// flight loop calls applyDispatchCeiling() on every planned flight-group to HONOR it. Living
// in its own importable module (not inline in the Workflow body) is what lets IT-02 unit-test
// the engine's group plan without a live sdlc-server — the same pattern as resume.js / gate.js
// (a Dynamic Workflow file can't be imported by a node test; bundle.mjs inlines this one).
//
// THE MODEL (R-06 / R-07 / CT-01):
//   - `fan`                → run the planner's conflict-free parallel group AS-IS. The #705
//                            file-conflict partitioner already ran upstream (in the Prime planner
//                            via flight_partition), so the group is already the maximal
//                            NON-CONFLICTING batch. `fan` adds no parallelism of its own — it just
//                            declines to serialize further. (Asymmetric-bias note, R-07: fanning a
//                            wave that should have serialized risks a cross-flight conflict the
//                            reconcile loop must unwind; serializing a wave that could have fanned
//                            only costs a little wall-clock. The cheap mistake is over-serializing,
//                            so absent/ambiguous dispatch biases to serialize, never to fan.)
//   - `serialize` /
//     `serialize-preferred` /
//     absent / unknown      → force ONE issue per group (single-file). The remaining planned
//                             issues stay pending and schedule in the NEXT loop iteration, so a
//                             serialize wave drains one flight at a time. `serialize-preferred`
//                             means "serialize unless the operator opts in to fan"; there is no
//                             operator-opt-in signal at execution time, so the executor treats it
//                             as serialize (CT-01: absent → serialize, the backward-compatible
//                             default for plans written before this field existed).
//
// THE CEILING INVARIANT (the load-bearing safety property): dispatch is a CEILING on parallelism,
// never a floor. applyDispatchCeiling can only ever return a group that is the SAME length or
// SHORTER than what the planner scheduled — it never adds an issue and never widens a group. So it
// can only make a wave MORE serial (safer), never less. A `fan` wave still respects the file-
// conflict serialization the planner already applied underneath; the R-03 intra-dependency hard
// gate is enforced upstream at plan time by /prepwaves (#823) — an intra-dep wave already arrives
// annotated `serialize`, so it never reaches here as `fan`.

// Normalize a raw dispatch value to one of the three canonical tokens. Absent, null, non-string,
// or any unrecognized value → 'serialize' (CT-01 backward-compatible default; conservative — an
// unknown hint must never accidentally FAN). Case/whitespace-insensitive so a hand-edited
// phases-waves.json ('Fan', ' serialize ') still classifies.
export function normalizeDispatch(dispatch) {
  const s = typeof dispatch === 'string' ? dispatch.trim().toLowerCase() : ''
  if (s === 'fan') return 'fan'
  if (s === 'serialize-preferred') return 'serialize-preferred'
  if (s === 'serialize') return 'serialize'
  return 'serialize' // absent / null / unknown → serialize (CT-01)
}

// Apply the dispatch ceiling to a planner-produced flight-group.
//   group    — issue numbers the Prime planner scheduled for the next parallel flight (already
//              filtered to still-pending + already file-conflict-partitioned by flight_partition).
//   dispatch — the wave's raw dispatch hint (normalized here).
// Returns the group the engine actually builds this iteration:
//   fan → the group unchanged (parallel; file-conflict floor preserved);
//   serialize / serialize-preferred / absent → just the FIRST issue (single-file). The first
//   element is preserved deliberately: the Prime planner puts surfaced-rework (just-re-opened)
//   issues FIRST, so taking group[0] keeps that scheduling priority.
// Never returns more than `group` had; for a serialize ceiling never returns more than one.
export function applyDispatchCeiling(group, dispatch) {
  const g = Array.isArray(group) ? group : []
  if (g.length === 0) return []
  if (normalizeDispatch(dispatch) === 'fan') return g // parallel: keep the conflict-free group
  return [g[0]] // serialize/serialize-preferred/absent: single-file, priority-preserving
}
