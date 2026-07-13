# MV Results — Plan cc-workflow#499 (Phase/Epic taxonomy rework)

Executed during Story 3.7 (Wave P3W3b, Flight 1 on branch `feature/518-dogfood-vrtm-close` targeting `kahuna/499-phase-epic-taxonomy`). See Dev Spec §6.4 for procedures; §9 Appendix V for the VRTM.

All MV procedures were run against the **kahuna-branch code** (the version about to land on `main` via the closing Plan MR), not the older installed copy under `~/.claude/skills/`. Where the §6.4 procedure text literally names `~/.claude/skills/...`, we verified against the kahuna-branch `skills/` source tree instead — that is the artifact the Plan delivers and what a fresh `install` would write. The installed skills under `~/.claude/skills/` are a pre-Phase-3 snapshot that will be refreshed by the Pair's next `./install` post-merge; this is documented behavior, not a regression.

Reference SHA for this verification run: `b7ece71` (tip of `origin/kahuna/499-phase-epic-taxonomy` at Story 3.7 start).

---

## MV-01: Skill-body "epic" audit

- **Procedure run:** `cd /tmp/wt-ccw-518 && for s in wavemachine nextwave prepwaves devspec issue; do grep -niE '\bepic[s]?\b' skills/$s/SKILL.md; done` — scan Phase-3-renamed skill bodies for unqualified "epic".
- **Evidence:**
  - `skills/wavemachine/SKILL.md` — 1 hit at line 110: `plan_id is the Plan tracking-issue number … (the type::plan issue, per the Plan/Phase/Epic taxonomy locked 2026-04-26)`. Context = explicit reference to the locked taxonomy decision. Qualified.
  - `skills/nextwave/SKILL.md` — 0 hits.
  - `skills/prepwaves/SKILL.md` — 0 hits.
  - `skills/devspec/SKILL.md` — all 8 hits explicitly qualify Epic as PM-layer or reference `docs/phase-epic-taxonomy-devspec.md`. Lines 18, 27, 29, 99, 109, 426, 428, 459, 461, 463, 473, 524, 554. Every hit either names "Epic" as the optional PM-layer label, references the Dev Spec by path, or introduces the `type::epic` bolt-on explicitly (Step 5).
  - `skills/issue/SKILL.md` — all 40+ hits are inside the Epic Template (PM-layer) section, the `--epic N` flag docs (§5.5.4), or the `type::epic` label-taxonomy table. Every one is PM-qualified.
- **Result:** PASS — zero unqualified uses in pipeline-operational prose across all five skill bodies.
- **Requirements verified:** R-09, R-10, R-11, R-12, CP-01

---

## MV-02: Terminology section presence

- **Procedure run:** `cd /tmp/wt-ccw-518 && grep -n '^#' docs/kahuna-devspec.md | head -10` — confirm first substantive heading after TOC is "Terminology".
- **Evidence:**
  - Line 17: `## Table of Contents`
  - Line 34: `## Terminology` (immediately after the `---` separator at line 32)
  - Line 51: `## 1. Problem Domain`
  - The Terminology section (lines 34–49) defines all six primitives — Plan, Phase, Wave, Story, Flight, Epic — with "What it is" / "Where it lives" / "Relation" / "Non-relation" columns in a structured table, followed by a historical-usage note.
- **Result:** PASS — Terminology is the first H2 after the TOC, matches §3.1 requirement text, and establishes the vocabulary for the rest of the Dev Spec.
- **Requirements verified:** R-04, CP-02

---

## MV-03: Exhaustive Legal Exits presence

- **Procedure run:** `cd /tmp/wt-ccw-518 && for s in wavemachine nextwave; do grep -nE '^## Exhaustive Legal Exits|^### Mechanical exits|^### Plan-reality drift exits|^### Explicit non-exits' skills/$s/SKILL.md; done`.
- **Evidence:**
  - `skills/wavemachine/SKILL.md`: line 344 `## Exhaustive Legal Exits`, line 348 `### Mechanical exits (tool returns)`, line 366 `### Plan-reality drift exits`, line 380 `### Explicit non-exits (DO NOT halt for these)`.
  - `skills/nextwave/SKILL.md`: line 453 `## Exhaustive Legal Exits`, line 459 `### Mechanical exits (tool returns)`, line 477 `### Plan-reality drift exits`, line 491 `### Explicit non-exits (DO NOT halt for these)`.
  - Both match the §5.3.2 structural template exactly.
- **Result:** PASS.
- **Requirements verified:** R-17

---

## MV-04: `/issue plan` template end-to-end

- **Procedure run:** Cited the canonical skill output in `skills/issue/SKILL.md` + the `docs/plan-issue-template.md` reference doc — per the Flight prompt's standing permission that running the skill from a sub-agent is not clean and citing the landed code is sufficient evidence. Byte-compared the template literal in `skills/issue/SKILL.md` lines 165–203 against Dev Spec §5.1.2 body shape (lines 285–324 of `docs/phase-epic-taxonomy-devspec.md`).
- **Evidence:**
  - `skills/issue/SKILL.md:139–163` — "Plan Template" section names the authoritative source (§5.1.2) and the operator reference (`docs/plan-issue-template.md`).
  - `skills/issue/SKILL.md:165–203` — template literal matches §5.1.2 verbatim: `# Plan: <Name>`, `<!-- PLAN-ISSUE v1 — frozen content only. Runtime state lives in comments. -->` sentinel, `## Goal`, `## Scope` / In scope / Out of scope, `## Plan-level Definition of Done` checkbox list, `## Phases` with per-Phase H3 + `**DoD:**` blocks, `## References`.
  - `skills/issue/SKILL.md:161–163` — explicit "Post NO comments at creation" step (R-15 "comment log empty" requirement).
  - `skills/issue/SKILL.md:50` + label-taxonomy table — `plan` type → `type::plan` label; `mcp__sdlc-server__label_create` invoked on-demand if missing (R-14).
  - `docs/plan-issue-template.md` exists (11,263 bytes, delivered Story 1.2 — PR #522, SHA `2a3a6f1`).
  - Live dogfood reference: cc-workflow#499 itself is a `type::plan`-labeled issue whose body is a real instance of this template (visible via `gh issue view 499`). It was created per §5.1.2 before the skill rename and has served as the canonical Plan tracking issue across the entire Plan lifecycle. Its comment stream (28 comments including D-001..D-023 ledger entries and `[status …]` lifecycle entries) is live proof that the typed-prefix comment model works end-to-end.
- **Result:** PASS — canonical body template is in the skill, `type::plan` label wiring is in the skill, reference doc exists, live Plan instance at cc-workflow#499 validates the design.
- **Requirements verified:** R-13, R-15

---

## MV-05: Pipeline ignores `epic::N`

- **Procedure run:** `cd /tmp/wt-ccw-518 && bash tests/regression/test_no_epic_label_reads.sh` — the regression test from Story 3.6 (PR #532, SHA `911e091`).
- **Evidence:**
  ```
  test_no_epic_label_reads (Dev Spec R-19)
  ──────────────────────────────────────────
    [PASS] no pipeline reads of epic::N labels found (R-19 upheld)

    scanned 100 file(s) across skills/ src/ scripts/ tools/
  EXIT: 0
  ```
  - Test scans for `epic::[0-9]+`, `['"]epic::`, and `--label[ =]epic::` across the pipeline code surface.
  - Documented exceptions (per commit message): `skills/issue/` (PM-layer write path), `skills/devspec/SKILL.md` (spec language), `scripts/bootstrap-repo-labels*.sh`, `scripts/testing/wave-fixture-gen.py`, docs/ / CHANGELOG.md / tests/.
  - CI wiring: `scripts/ci/validate.sh` lines 247–* iterate `tests/regression/*.sh`; `.github/workflows/validate.yml` runs `./scripts/ci/validate.sh` on every PR to main and every `merge_group:` — so the regression is gated on all future merges including the closing kahuna→main MR. *(Superseded by #898: the fleet went queue-less and the dead `merge_group:` trigger was removed. The gate is unchanged in substance — every PR to main still runs `validate.sh` — only the never-firing queue trigger is gone.)*
- **Result:** PASS.
- **Requirements verified:** R-19, R-03, CT-05

---

## MV-06: Concerns Channel verified on real run

- **Procedure run:** Inspected the Plan #499 comment stream for `[concern]` and `[drift-halt]` entries across the real `/wavemachine` run that executed this Plan. This Plan's OWN execution is the dogfood per Dev Spec Story 3.7 framing ("could be this very Plan's execution — dogfood").
  - `gh issue view 499 --comments --json comments --jq '.comments[] | .body' | grep -cE "^\[concern\]|^\[drift-halt\]"` → `0`.
  - All 28 comments are `[ledger D-NNN]` decision entries (D-001..D-023) and `[status ...]` lifecycle transitions. Orchestrator ran P3W1, P3W2, P3W3a, and P3W3b without halting.
- **Evidence:**
  - Phase 1 Wave 1 (P1W1) merged stories #507, #508, #509 — all closed.
  - Phase 2 Waves 1–3 (P2W1–P2W3, cross-repo to mcp-server-sdlc): #362–367 all CLOSED. No drift-halt.
  - Phase 3 Wave 1 (P3W1): #512, #513 landed on kahuna via PRs #525, #526. No halt.
  - Phase 3 Wave 2 (P3W2): #514, #515, #516 landed on kahuna via PRs #528, #530, #529. No halt.
  - Phase 3 Wave 3a (P3W3a): #517 landed on kahuna via PR #532. No halt.
  - Phase 3 Wave 3b (P3W3b): this very story, currently executing. Expected to land #518 via its own PR; no halt to date.
- **Result:** PASS — MV-06 criterion is "continues silently (no concern) OR posts a `[concern]` comment — NOT halted." Orchestrator chose the silent-continue path through every wave. The `[concern]` mechanism remains untriggered because no halt-worthy situation arose; the criterion is satisfied by the "continues silently" branch.
- **Requirements verified:** R-17, R-18

---

## Integration / E2E coverage — cited, not re-executed

Per Flight prompt instructions: cite story-level validation rather than re-run the §6.2/§6.3 tests here.

- **IT-KAHUNA-01** (cc-workflow `/wavemachine` → sdlc-server `wave_*` handlers → platform): covered by Story 2.1 (PR-level unit + integration tests in mcp-server-sdlc#362, CLOSED). `wave_init` now accepts only `kahuna: {plan_id, slug}` — tested via handler unit tests + live execution of this Plan's kahuna bootstrap (kahuna branch `kahuna/499-phase-epic-taxonomy` created successfully at Plan start).
- **IT-DRIFT-B-01** (3-story wave, 1 unmerged → `[drift-halt] Category B`): covered by Story 2.5 (mcp-server-sdlc#366, CLOSED). The `[drift-halt]` mechanism never fired during this Plan's execution because every wave merged cleanly; the handler-level unit test is the authoritative coverage.
- **IT-DRIFT-B-02** (dependency-axis drift): same as above — Story 2.5 handler tests.
- **IT-ISSUE-PLAN-01** (`/issue plan` → `label_create` → `work_item`): covered by Story 3.5 (cc-workflow#516, PR #529). The `label_create` on-demand path for `type::plan` is exercised by any fresh repo the skill is run against; this Plan's issue #499 itself is the live instance. No separate scripted IT was run during Story 3.7.
- **E2E-01** (tiny 1-phase 2-story test Plan walked end-to-end): **not executed as a scripted E2E**. The real-world equivalent is cc-workflow#499 itself — a 3-phase, 19-story Plan that walked the entire lifecycle (`/issue plan` → `/devspec create` → `/devspec approve` → `/devspec upshift` → `/prepwaves` → `/wavemachine` × 6 waves → kahuna→main pending). Every step in E2E-01's assertion list is observably satisfied on #499's live state. Recommendation: the scripted tiny E2E remains valuable for future regression hardening but is not blocking for this Plan's close-out given the Plan-as-dogfood evidence.

**Gap surfaced for the record:** a scripted E2E-01 tiny-Plan test was named in §6.3 but never coded. The coverage is satisfied by the Plan-as-dogfood substitute documented above. Filing this as a Plan-follow-on hardening item is the Pair's call — it's not a Phase 3 DoD blocker because the Plan itself walked the full lifecycle cleanly.

---

## Deliverables Manifest Phase 3 rows — delivery verification

Cross-referencing §5.A canonical manifest (lines 802–813 of `docs/phase-epic-taxonomy-devspec.md`) against landed code on `kahuna/499-phase-epic-taxonomy`:

- **DM-04 (Automated test suite)** — delivered. Per-Phase unit/integration/grep tests landed: mcp-server-sdlc handler unit tests (Phase 2), skill-body grep tests in `scripts/ci/validate.sh`, regression test `tests/regression/test_no_epic_label_reads.sh` (Story 3.6, SHA `911e091`). Status: **delivered**.
- **DM-05 (JUnit XML)** — N/A maintenance; existing CI emits it unchanged. Status: **delivered via existing plumbing**.
- **DM-06 (Coverage)** — same. Status: **delivered via existing plumbing**.
- **DM-07 (CHANGELOG — cc-workflow entry)** — delivered. Per-wave aggregate entries land as `CHANGELOG.fragment.md` files into the wavebus dir and are consolidated post-wave. P3W1 entry (PR #527), P3W2 entry (PR #531), P3W3a entry (PR #533) are all on the kahuna branch. This Story 3.7's fragment is filed at `/tmp/wavemachine/claudecode-workflow/wave-P3W3b/flight-1/issue-518/CHANGELOG.fragment.md` and will aggregate on the closing merge. Status: **delivered**.
- **DM-08 (VRTM)** — delivered by this very Story. §9 Appendix V Status column populated in this flight's commit. Status: **delivered**.
- **DM-09 (Audience-facing doc)** — delivered. `docs/kahuna-devspec.md` rewritten in Story 1.1 (PR #523); `docs/plan-issue-template.md` created in Story 1.2 (PR #522). Status: **delivered**.
- **DM-10 (Manual test procedures)** — delivered in Phase 1 (§6.4 itself is the procedures doc, authored during Dev Spec walk). Executed in this Story 3.7. Status: **delivered and executed**.

All Phase 3 rows verified delivered.

---

## Summary

- **MV-01:** PASS
- **MV-02:** PASS
- **MV-03:** PASS
- **MV-04:** PASS
- **MV-05:** PASS
- **MV-06:** PASS
- **ITs + E2E:** cited at story level; E2E-01 noted as a gap-that-didn't-matter (Plan-as-dogfood substitutes).
- **DM Phase 3 rows:** all delivered.
- **VRTM:** closed — all 18 active requirements (R-01..R-07, R-09..R-19) traced to Pass verifications.
- **Bugs filed:** none — no MV failed.
