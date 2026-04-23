# Wavemachine v2 — Integration Test Plan

## Overview

This document is the integration-test harness for the wavemachine v2
Orchestrator/Prime/Flight pipeline (epic #384). It specifies **ten scenarios
plus one tool-probe gate** that together prove the v2 shape works end-to-end:
the Orchestrator has `Agent`, Prime/Flight do not, the filesystem bus carries
all inter-agent data, parallel flights actually parallelize, failure modes
(explicit FAIL, silent crash, malformed return, pre-wave BLOCKED) are handled
cleanly, cross-repo targeting works, and Orchestrator context stays bounded.

The test plan is split across two issues:

- **#389 (this scaffolding pass)** — authors this document; completes
  everything verifiable by sub-agent inspection (Gate 0, Scenarios 5, 6, 7, 10)
  with evidence inlined here.
- **#396 (live-run pass)** — executes the remaining scenarios in a top-level
  Orchestrator session, replacing the PENDING stubs below with real timing data,
  bus-tree snapshots, and PASS/FAIL verdicts.

> **Why the split.** `/nextwave` and `/wavemachine` can only be faithfully
> exercised from a top-level CC session because sub-agents lack the `Agent`
> tool (see `lesson_cc_subagent_tools.md`). A wave-pattern execution agent
> (itself a sub-agent) physically cannot run Scenarios 1–4, 8, 9. Those are
> live-run only. Scenarios 5, 6, 7, 10 and Gate 0 can be verified by reading
> the skill body + scripts, so they land here.

## Quick status table

| ID | Scenario | Status |
|---|---|---|
| Gate 0 | CC tool-probe (Orchestrator vs. sub-agent) | **COMPLETED** |
| 1 | Single-wave, single-issue | **PENDING (#396)** |
| 2 | Single-wave, 2-issue parallel flight | **PENDING (#396)** |
| 3 | Multi-flight wave (dep-chain) | **PENDING (#396)** |
| 4 | `/wavemachine` happy-path 2-wave | **PENDING (#396)** |
| 5 | Injected FAIL from Flight | **COMPLETED** |
| 6 | Silent crash (no DONE sentinel) | **COMPLETED** |
| 7 | Malformed Flight return | **COMPLETED** |
| 8 | Pre-wave BLOCKED (unresolvable dep graph) | **PENDING (#396)** |
| 9 | Cross-repo wave (stories in target repo) | **PENDING (#396)** |
| 10 | Orchestrator context-size bound | **COMPLETED (methodology); measurement PENDING (#396)** |

## Reproducibility conventions

All live scenarios assume:

- A **throwaway test repo** (fresh or a dedicated sandbox) whose issues can be
  safely closed; `/prepwaves` has already authored a wave plan over those
  issues.
- **Clean bus state** before each run: `rm -rf /tmp/wavemachine/<repo-slug>`
  and `wave-status init` (or the campaign equivalent) from scratch.
- **Clean working tree** on the target repo's base branch.
- Identity file at `/tmp/claude-agent-<md5>.json` resolved via `/name` so
  Discord announcements include the agent label.
- Commands are quoted with the wave root in angle brackets — substitute the
  actual path printed by `scripts/wavebus/wave-init`.

Signals captured per live run (Scenarios 1–4, 8, 9):

- Start / end timestamps of the Orchestrator run.
- Per-Flight start timestamp (from the Agent tool-use block timing) — used to
  prove parallelism in Scenario 2.
- `ls -R <wave-root>` after each flight and at the end of the run.
- `wave_show()` JSON output at each step.
- The final line of each Flight return (must match the canonical regex).
- Discord posts to `#wave-status` (`1487386934094462986`).

---

## Gate 0 — CC tool-probe

### What it tests
Confirms the fundamental precondition the entire v2 design is built on:
**the top-level Orchestrator has `Agent`/`Task`; sub-agents do not.** If this
flips on a future CC release, v2's parallelism collapses silently (the v1 bug)
and every downstream scenario's verdict becomes meaningless.

### Methodology
1. In a top-level CC session (the Orchestrator), inspect the tool list. Look
   for `Agent` and `Task` in the top-of-prompt tool schemas.
2. Spawn a sub-agent via `Agent` with a one-liner prompt: *"Reply with a JSON
   array of your tool names."* Capture its tool list.
3. Cross-reference against `lesson_cc_subagent_tools.md` — the locked-in list
   for CC 2.1.110 through 2.1.116 is:
   - Foreground sub-agent:
     `["Bash","Edit","Glob","Grep","Read","ScheduleWakeup","Skill","ToolSearch","Write"]`
   - Background sub-agent (via `run_in_background: true`):
     `["Bash","Edit","Glob","Grep","Read","Skill","ToolSearch","Write"]`

### Expected outcome
- Orchestrator tool list **includes** `Agent` (and/or `Task`).
- Sub-agent tool list **excludes** `Agent` and `Task` at every depth.
- Any deviation → file a regression issue against v2 and stop all downstream
  testing; the design precondition is broken.

### Status: COMPLETED

**Evidence from this very session** (the spec executor for #389 is itself a
sub-agent spawned via `Agent` by a higher-level Orchestrator). The tools
available to this sub-agent are:

```
Bash, Edit, Glob, Grep, Read, ScheduleWakeup, Skill, ToolSearch, Write
```

No `Agent`, no `Task`. Matches the foreground sub-agent signature documented
in `lesson_cc_subagent_tools.md` verbatim. The lesson file itself is the
authoritative probe record — bisected across CC 2.1.110 → 2.1.116, no version
in that band grants sub-agents `Agent`/`Task`. See
`/home/bakerb/.claude/projects/-home-bakerb-sandbox-github-claudecode-workflow/memory/lesson_cc_subagent_tools.md`
lines 9–36.

**Orchestrator-side confirmation** (still required in the live run, cheap to
redo):
`#396` executor should paste its own top-of-prompt tool list into this doc as
part of the Scenario 1 preamble — it will show `Agent` present, closing the
loop.

---

## Scenario 1 — Single-wave, single-issue

### What it tests
The minimal end-to-end path: one wave, one flight, one issue. Proves the
Orchestrator→Prime(pre-wave)→Flight→Prime(post-flight)→Prime(post-wave)
sequence works when nothing is parallel and nothing is gnarly. Baseline for
every other scenario.

### Methodology
1. Prepare a throwaway epic with a single wave containing exactly one spec-driven
   issue whose acceptance criteria are trivially satisfiable (e.g. add a
   comment to a file).
2. From an Orchestrator session, run `/nextwave` (interactive mode).
3. Approve the gate when it fires.
4. Capture:
   - Bus tree after Prime(pre-wave) writes `plan.md` and `prompt.md`.
   - Flight's final canonical return line.
   - Prime(post-flight) JSON return.
   - Prime(post-wave) JSON return.
   - `wave_show()` after completion.
   - Discord post in `#wave-status`.

### Expected outcome
- All three Prime returns are `PASS`.
- `wave_show()` reports the wave complete.
- PR merged, issue closed on remote.
- `scripts/wavebus/wave-cleanup` succeeds (bus directory gone).
- Discord shows `🏄 Wave N started` and `✅ Wave N complete`.
- **PASS criterion:** every expected observation above holds; no stray state
  on disk; issue closed.

### Status: PENDING (#396 live run)

---

## Scenario 2 — Single-wave, 2-issue parallel flight

### What it tests
Parallelism. Two issues in the same flight must spawn as sibling Flight
agents within a **single** Orchestrator tool-use block (per
`skills/nextwave/SKILL.md` Step 3b). Proves the v1 bug (silent serialization)
is gone: both Flights start within seconds of each other.

### Methodology
1. Throwaway epic with one wave containing two mutually non-overlapping issues
   (`flight_overlap` returns empty intersection → single flight with both
   issues).
2. Run `/nextwave`.
3. Instrument: before issuing the Agent calls in Step 3b, log timestamp T0;
   each Flight's first Bash call timestamps T1_a, T1_b.
4. Approve the gate; let it merge.
5. Capture both Flight's first observable timestamps from the session log
   (e.g. the `git status` or `validate.sh` start time, whichever is earliest).

### Expected outcome
- |T1_a − T1_b| < 5 seconds — Flights are concurrent, not serialized.
- Both Flights return `PASS` and emit the canonical line.
- Prime(post-flight) runs `commutativity_verify` on both changesets (this is
  the multi-issue path — single-issue flights skip it per
  `skills/nextwave/SKILL.md` Step 3e bullet 3).
- Both PRs merge; both issues close.
- **PASS criterion:** timestamp delta < 5 s AND commutativity verification
  ran AND both PRs merged cleanly.

### Status: PENDING (#396 live run)

---

## Scenario 3 — Multi-flight wave (dep-chain)

### What it tests
Flight sequencing inside a single wave when `flight_partition` detects a
file-level conflict. Flight 1 lands, Flight 2 runs against the updated base,
inter-flight re-validation fires if needed
(`skills/nextwave/SKILL.md` Step 3g).

### Methodology
1. Throwaway epic with one wave containing three issues where issues A and C
   both modify `package.json` (force two flights: {A, B} and {C}, or {A} and
   {B, C} depending on partitioning).
2. Confirm `plan.md` in the bus records ≥ 2 flights.
3. Run `/nextwave`. Approve the flight-1 gate; watch Prime(post-flight)
   flight-1 merge; observe inter-flight re-validation (`drift_files_changed`);
   approve flight-2 gate; watch it merge.
4. Capture bus tree between flights — should show `flight-1/merge-report.md`
   present and `flight-2/` populated only after flight-1 completes.

### Expected outcome
- `plan.md` shows the partition rationale referencing the overlapping file.
- Flight-1 merges before Flight-2 starts (ordering enforced).
- Inter-flight re-validation emits one of: `PLAN VALID`, `PLAN VALID (minor)`,
  `PLAN INVALIDATED`, `ESCALATE` for any issue whose manifest intersects
  flight-1's committed file set.
- All PRs merge; all issues close.
- **PASS criterion:** flight ordering enforced AND re-validation fired (or
  cleanly skipped via the serial fast-path with justification in
  Prime(post-flight)'s report) AND all issues closed.

### Status: PENDING (#396 live run)

---

## Scenario 4 — `/wavemachine` happy-path 2-wave

### What it tests
The autopilot loop itself. Two waves in sequence; `wave_health_check` stays
HEALTHY; `wave_next_pending` drives iteration; `wavemachine_active` flag
lifecycle (set on entry, cleared on every exit path) matches the 🌊 statusline
indicator the whole time.

Unblocked by #393 (canonical status JSON emission in `/nextwave auto`) —
without that, the loop couldn't parse the per-wave return.

### Methodology
1. Throwaway epic split into two waves (wave 1: 1–2 issues; wave 2: 1–2
   issues; no cross-wave spec dependencies).
2. Run `/wavemachine` from a top-level session.
3. Observe pre-flight checks pass (plan exists, no concurrent wavemachine,
   base clean, previous-wave-merged trivially true, pending waves > 0,
   `wavemachine_active` not already set).
4. Watch both waves land in order. Capture the canonical status JSON emitted
   at the end of each `/nextwave auto` invocation — should be
   `{"status":"OK","wave_id":"<id>"}`.
5. Verify `wavemachine_active` is `true` during the run (read
   `.claude/status/state.json`) and cleared to `false` on clean completion.
6. Check Discord: `🌊 Wavemachine started`, `🏄 Wave 1 started`,
   `✅ Wave 1 complete`, `🏄 Wave 2 started`, `✅ Wave 2 complete`,
   `✅ Wavemachine complete`.

### Expected outcome
- Both waves merge cleanly via `/nextwave auto` (no human approval gates;
  `wave_ci_trust_level` stands in).
- `wavemachine_active` flag toggles exactly twice: `true` on entry, `false`
  on exit.
- `wave_health_check` called at the top of each iteration.
- `wave_next_pending()` returns null after wave 2, loop exits cleanly.
- **PASS criterion:** both waves merged AND flag lifecycle clean AND Discord
  announcement set complete AND no state left in `/tmp/wavemachine/<slug>/`.

### Status: PENDING (#396 live run)

---

## Scenario 5 — Injected FAIL from Flight

### What it tests
The FAIL-path cascade: a Flight calls `flight-finalize` with `FAIL`, the
canonical line arrives as `... FAIL`, the Orchestrator parses it, the DONE
sentinel verification matches, Prime(post-flight) is spawned and reports
`BLOCKED`, and the wave halts.

### Methodology
Static inspection of the three wiring points:

1. **Flight stub prompt** (`skills/nextwave/SKILL.md` lines 249–256) —
   instructs the Flight to call `flight-finalize <partial> FAIL` when any AC
   fails or mechanical check is red.
2. **`scripts/wavebus/flight-finalize`** — confirms FAIL is accepted, DONE
   sentinel gets `"FAIL"`, canonical line echoes `<results.md> FAIL`.
3. **Orchestrator Step 3c** (`skills/nextwave/SKILL.md` lines 108–112) —
   parses the canonical line; verifies the DONE sentinel matches.
4. **Prime(post-flight) Step 1** (`skills/nextwave/SKILL.md` line 133) —
   reads `DONE`; if any FAIL, writes `BLOCKED` report naming the failing
   issue.
5. **Orchestrator Step 3f** (`skills/nextwave/SKILL.md` lines 149–152) —
   on `FAIL`/`BLOCKED`, stops the per-flight loop and leaves the bus for
   forensics.

To observe end-to-end in a live run, use a dummy issue whose spec is
intentionally unsatisfiable (e.g. require a file that the spec says must not
exist) and run `/nextwave`; this is a subset of Scenario 1's setup and cheap
to add.

### Expected outcome
Static: each of the five wiring points above is present and correct. The
canonical flow `Flight FAIL → DONE sentinel "FAIL" → Orchestrator records
FAIL → Prime(post-flight) BLOCKED report → Orchestrator halts` is
unambiguous from reading the skill + script.

### Status: COMPLETED

**Evidence:**

1. `scripts/wavebus/flight-finalize` lines 30–33 — status validation:

   ```bash
   if [[ "$status" != "PASS" && "$status" != "FAIL" ]]; then
           echo "error: status must be PASS or FAIL, got '$status'" >&2
           exit 1
   fi
   ```

2. `scripts/wavebus/flight-finalize` lines 65–68 — DONE sentinel + canonical
   echo (identical shape for PASS and FAIL):

   ```bash
   # Write DONE sentinel with exactly PASS or FAIL, no trailing newline.
   printf '%s' "$status" >"$done_path"

   echo "$results_path $status"
   ```

3. `skills/nextwave/SKILL.md:108-112` — Orchestrator Step 3c parses and
   verifies:

   > Each Flight's last message is exactly one line matching
   > `^(/tmp/wavemachine/[^\s]+/results\.md) (PASS|FAIL)$`. Orchestrator:
   > - Parses each line. Malformed → record as FAIL, note "malformed return".
   > - Verifies the `DONE` sentinel (`/tmp/wavemachine/.../issue-<X>/DONE`)
   >   exists and contains `PASS` or `FAIL` matching the returned line.
   >   Mismatch → FAIL.
   > - Reads each `results.md` into context (small, summary + checklist).

4. `skills/nextwave/SKILL.md:133` — Prime(post-flight) Step 1:

   > For each issue X in this flight, read
   > `<wave-root>/flight-<M>/issue-<X>/results.md` and verify `DONE` contains
   > `PASS`. If any FAIL, stop and write a `BLOCKED` report naming the
   > failing issues.

5. `skills/nextwave/SKILL.md:152` — Orchestrator Step 3f:

   > `FAIL` / `BLOCKED` → stop the per-flight loop. Leave the bus in place.
   > Surface to user with the `report_path`. In **auto mode**, emit the
   > canonical status line (see "Step 6 — Final status emission") before
   > returning control.

6. `skills/nextwave/SKILL.md:203-205` — auto-mode status mapping for
   Prime(post-flight) FAIL / BLOCKED:

   > Step 3f Prime(post-flight) `BLOCKED` → `{"status":"BLOCKED","wave_id":"<N>","reason":"..."}`
   > Step 3f Prime(post-flight) `FAIL` → `{"status":"FAIL","wave_id":"<N>","reason":"..."}`

**Verdict:** PASS. The FAIL cascade is wired correctly end-to-end: Flight emits
FAIL via `flight-finalize` → DONE sentinel carries `"FAIL"` → Orchestrator
parses + verifies match → Prime(post-flight) reads DONE, writes BLOCKED → the
per-flight loop halts → in auto mode, `/wavemachine` receives BLOCKED/FAIL
canonical status JSON and exits the loop.

---

## Scenario 6 — Silent crash (no DONE sentinel)

### What it tests
What happens when a Flight dies without running `flight-finalize` (network
hiccup, process kill, tool error that aborts the sub-agent mid-run). The
canonical return line is never emitted; no DONE sentinel exists. The
Orchestrator's Step 3c verification must catch this and record FAIL.

### Methodology
Static inspection:

1. **`flight-finalize` is the ONLY code path that writes `DONE`.** Grep the
   codebase for any other writer — there isn't one (confirmed via
   `scripts/wavebus/` — no other script touches `DONE`; the Flight stub
   doesn't write it directly).
2. **If `flight-finalize` never runs**, `DONE` does not exist.
3. **Orchestrator Step 3c** (`skills/nextwave/SKILL.md:108-112`) parses the
   Flight's final message. If the final message isn't the canonical line
   (because the Flight crashed before emitting it), the parse falls through
   to "malformed → record as FAIL, note 'malformed return'."
4. **DONE-sentinel check** — Step 3c's second bullet verifies the sentinel's
   contents match the returned line; if the sentinel is **missing**, that's a
   mismatch → FAIL.

Mentally simulate: Flight dies silently. Orchestrator's last Agent return is
empty or truncated (non-matching). Step 3c falls through to the malformed
path. Even if the sentinel check is reached, the file doesn't exist and the
mismatch → FAIL. Prime(post-flight)'s Step 1 (line 133) re-checks DONE and
flags BLOCKED. Wave halts; bus stays for forensics.

### Expected outcome
Static: the Orchestrator guard at Step 3c catches both (a) missing canonical
line and (b) missing/non-matching DONE. Either alone is sufficient to record
FAIL; the two guards are defense-in-depth.

### Status: COMPLETED

**Evidence:**

1. `skills/nextwave/SKILL.md:108` — canonical regex (single-line match):

   > Each Flight's last message is exactly one line matching
   > `^(/tmp/wavemachine/[^\s]+/results\.md) (PASS|FAIL)$`.

2. `skills/nextwave/SKILL.md:110` — malformed handling:

   > Parses each line. Malformed → record as FAIL, note "malformed return".

3. `skills/nextwave/SKILL.md:111` — DONE sentinel verification:

   > Verifies the `DONE` sentinel (`/tmp/wavemachine/.../issue-<X>/DONE`)
   > exists and contains `PASS` or `FAIL` matching the returned line.
   > Mismatch → FAIL.

4. `scripts/wavebus/flight-finalize` is the only writer of `DONE` (line 66:
   `printf '%s' "$status" >"$done_path"`). If the Flight crashes before
   calling it, the file does not exist.

5. `skills/nextwave/SKILL.md:133` — Prime(post-flight) re-verifies DONE:

   > For each issue X in this flight, read
   > `<wave-root>/flight-<M>/issue-<X>/results.md` and verify `DONE` contains
   > `PASS`. If any FAIL, stop and write a `BLOCKED` report naming the
   > failing issues.

**Verdict:** PASS. The two-guard design (Orchestrator regex + DONE sentinel
verification, re-checked by Prime(post-flight)) ensures a silently-crashed
Flight always cascades to FAIL. No code path treats an absent DONE as
success. Bus state is preserved for forensics
(`skills/nextwave/SKILL.md:191` — "Failure / abort path: DO NOT cleanup").

---

## Scenario 7 — Malformed Flight return

### What it tests
A Flight emits something that *looks* like the canonical line but isn't:
trailing whitespace, a different path prefix, extra prose around it, wrong
status token, or the partial path instead of `results.md`. All must be
rejected by the Orchestrator's canonical regex at `skills/nextwave/SKILL.md`
line 37 (also re-stated at line 108) and recorded as FAIL.

### Methodology
1. Extract the canonical regex verbatim from `skills/nextwave/SKILL.md:37`:

   ```
   ^(/tmp/wavemachine/[^\s]+/results\.md) (PASS|FAIL)$
   ```

2. Enumerate failure modes and confirm the regex rejects each. Probe
   (executed via `python3 -c`):

   | Input | Verdict |
   |---|---|
   | `/tmp/wavemachine/foo/wave-1/flight-1/issue-42/results.md PASS` | match |
   | `/tmp/wavemachine/foo/wave-1/flight-1/issue-42/results.md FAIL` | match |
   | `...results.md PASS ` (trailing space) | reject |
   | `/home/bakerb/results.md PASS` (wrong path prefix) | reject |
   | `Done! /tmp/wavemachine/.../results.md PASS` (leading prose) | reject |
   | `...results.md PASS — all green` (trailing prose) | reject |
   | `...results.md OK` (wrong status token) | reject |
   | `...results.md.partial PASS` (wrong filename) | reject |
   | `` (empty) | reject |

3. Confirm the DONE-sentinel mismatch guard catches the one edge case the
   regex alone might pass — e.g. a Flight that hand-crafts a valid-looking
   line without actually calling `flight-finalize` (so no DONE is written).
4. In a live run (nice-to-have, not required for this verdict), a malformed
   return can be injected by overriding the Flight stub to print a custom
   final line; observe the Orchestrator records FAIL and Prime(post-flight)
   reports BLOCKED.

### Expected outcome
Static: every failure mode enumerated above is rejected by the regex; the
DONE-sentinel guard provides defense-in-depth against the "looks canonical
but no DONE" edge case.

### Status: COMPLETED

**Evidence:**

1. Canonical regex, `skills/nextwave/SKILL.md:37`:

   > **Canonical Flight return regex:**
   > `^(/tmp/wavemachine/[^\s]+/results\.md) (PASS|FAIL)$`.
   > Anything else → Orchestrator treats as FAIL (malformed).

2. Same regex restated at `skills/nextwave/SKILL.md:108` (Step 3c).

3. Python probe results (executed `python3 -c` on the eight representative
   cases above — all pass-through cases matched, all malformed cases
   rejected). Summary:

   ```
   valid-PASS        match=True
   valid-FAIL        match=True
   trailing-space    match=False
   wrong-path        match=False
   leading-prose     match=False
   trailing-prose    match=False
   wrong-status      match=False
   partial-path      match=False
   empty             match=False
   ```

4. **One subtlety worth recording**: Python's `re.match` with `$` treats
   `\n` as end-of-string, so a trailing newline happens to match when using
   `$` but not `\Z`. Bash's `[[ =~ ]]` (with the anchored pattern) rejects
   trailing newline. The Orchestrator is an LLM parsing text — the intent is
   "one exact line, nothing else" — which the skill body makes explicit at
   lines 86, 145, 178, 256 ("exactly one line, no prose, no fences").
   Implementers doing a Python/JS parse of the final message should strip
   trailing whitespace before matching, or anchor with `\Z` / equivalent.

5. Defense-in-depth guard — `skills/nextwave/SKILL.md:111`: DONE sentinel
   verification catches any canonical-looking line not actually produced by
   `flight-finalize`.

**Verdict:** PASS. The regex rejects every realistic malformation; the DONE
sentinel mismatch catches the adversarial "spoofed canonical line" edge case.

---

## Scenario 8 — Pre-wave BLOCKED (unresolvable dep graph)

### What it tests
Prime(pre-wave) detects that a wave's issue set cannot be planned — e.g. a
spec is missing acceptance criteria, two issues have a circular file
dependency that `flight_partition` cannot resolve, or `spec_get` returns a
structural error. Prime writes `plan.md` with `BLOCKED`, emits the JSON
return with `status: "BLOCKED"`, and the Orchestrator halts before any
Flight spawns.

### Methodology
1. Prepare a throwaway wave where one issue's spec is deliberately malformed
   (e.g. the "Acceptance Criteria" section is empty, or the AC is
   structurally impossible to satisfy — contradictory constraints). An
   alternative is two issues that `flight_overlap` reports as mutually
   required to modify the same file AND depend on each other's output.
2. Run `/nextwave`. Watch Prime(pre-wave) spawn.
3. Observe its JSON return: `{"plan_path":"...","status":"BLOCKED","flights":[]}`.
4. Confirm:
   - `plan.md` exists in the bus, contains a human-readable blocker reason
     naming the failing issue(s).
   - No `flight-1/issue-*/prompt.md` files were written (Prime halted before
     that step).
   - No Flight sub-agents were spawned.
   - Orchestrator posts BLOCKED notice to `#wave-status`.
   - Bus is left intact for forensics (no `wave-cleanup`).
   - In auto mode (if driving from `/wavemachine`), the Orchestrator emits
     `{"status":"BLOCKED","wave_id":"<N>","reason":"<one-line from plan.md>"}`
     as its final message.

### Expected outcome
- `plan.md` present, names the blocker.
- No Flight spawned; no remote state changed.
- Bus left for forensics.
- Correct canonical status JSON in auto mode (per
  `skills/nextwave/SKILL.md:202`).
- **PASS criterion:** BLOCKED correctly propagates; zero remote writes; bus
  preserved; status JSON matches the spec's mapping table.

### Status: PENDING (#396 live run)

---

## Scenario 9 — Cross-repo wave

### What it tests
The wave plan lives in repo A; the stories (issues) live in target repo B.
Confirms:
- Bus slug keys off **target repo** (per `decision_wavemachine_v2.md` §
  "Testing plan" bullet 6 and `lesson_cross_repo_wave_orchestration.md`).
- Worktrees are created in target repo B (`git -C <target-repo> worktree add`),
  not via the Agent tool's `isolation: "worktree"` flag (which wouldn't know
  about the cross-repo target).
- Flight `prompt.md` references the cross-repo worktree path explicitly.
- PRs are filed against repo B.

### Methodology
1. Set up two repos: repo A (orchestrator, where the wave plan lives via
   `/prepwaves`), repo B (target, where the issues are filed).
2. In repo A, `/prepwaves <master-epic-url-in-B>` — the plan records the
   target repo slug explicitly.
3. From a top-level session in repo A, run `/nextwave`. Watch the
   Orchestrator's Step 1 resolve the **target** repo slug, not repo A's.
4. Pre-create worktrees: `git -C <repo-B-path> worktree add /tmp/wt-<slug>-<X>
   -b feature/<X>-desc` for each issue. Confirmed in
   `skills/nextwave/SKILL.md:59`:

   > Cross-repo: create them now via `git -C <target-repo> worktree add
   > /tmp/wt-<slug>-<issue> -b feature/<issue>-<desc>` (one per issue).

5. Capture bus root — must be `/tmp/wavemachine/<repo-B-slug>/wave-<N>/`.
6. Observe Flights work in the repo-B worktrees; Prime(post-flight) pushes
   + opens PRs against repo B.
7. Confirm PRs land on repo B; issues close on repo B.

### Expected outcome
- Bus root uses target repo slug (repo B), **not** the Orchestrator's cwd
  (repo A).
- Worktrees live under `/tmp/wt-<B-slug>-<issue>/` and are git-worktrees of
  repo B.
- PRs filed against repo B.
- **PASS criterion:** bus path points to B AND PRs are on B AND repo A has
  no stray branches / state.

### Status: PENDING (#396 live run)

---

## Scenario 10 — Orchestrator context-size bound

### What it tests
The architectural claim at the heart of v2: the filesystem bus keeps
Orchestrator tokens O(1) per flight regardless of Flight content size.
Stated explicitly in `skills/nextwave/SKILL.md:19`:

> Filesystem bus keeps Orchestrator tokens O(1) per flight regardless of
> flight content size.

And in `decision_wavemachine_v2.md` §4:

> Orchestrator context holds only paths and status tokens. Everything that
> flows between agents (Flight prompts, Flight results, Prime reports) lives
> on disk.

If this claim is false, v2 has the same scaling problem v1 had with "inline
design" alternatives — the Orchestrator's context balloons proportional to
how much Flight sub-agents produce.

### Methodology

**Two comparisons, both needed:**

1. **v2 actual** (measured in #396): After Scenario 4 completes (2 waves,
   ~4 issues total), capture the Orchestrator session's token count via CC's
   built-in session statusline or API usage report. Record:
   - Tokens held before `/wavemachine` starts.
   - Tokens held after Wave 1 completes (mid-run).
   - Tokens held after Wave 2 completes (end of run).
   - The delta attributable to Flight outputs = the O(1) portion we want to
     bound.

2. **Naive "inline design" estimate** (computed, not measured): For the same
   scenario, estimate how many tokens the Orchestrator would hold if
   Flight outputs lived inline instead of on disk:
   - Each Flight's `results.md` (commit SHA, files changed, test results,
     reviewer findings, AC checklist, concerns) — realistically
     500–2000 tokens per issue.
   - Each Prime(post-flight) report — 500–1500 tokens.
   - Each Prime(post-wave) merge-report — 1000–3000 tokens.
   - Total naive = sum of all of the above for the 4 issues + 2 flights + 2
     waves.

**Ratio test:** v2 actual / naive inline.

**Per-flight increment (the real O(1) test):** after each flight in Wave 1,
record Orchestrator tokens; after each flight in Wave 2, record again.
The per-flight token growth should be small and constant — roughly the size
of one canonical return line (≈ 30 tokens) plus the `results.md` summary
the Orchestrator reads (per `skills/nextwave/SKILL.md:112` — "Reads each
`results.md` into context (small, summary + checklist)"). Growth should
NOT scale with the size of work each Flight performed.

### Expected outcome
- v2 actual / naive < 30% (per #396 acceptance criterion bullet 4).
- Per-flight Orchestrator token growth is bounded (< ~200 tokens per
  flight beyond the summary read).
- Growth does not correlate with Flight output size: a Flight that produces
  a 10KB vs. a 50KB `results.md` should leave roughly the same Orchestrator
  token footprint (because the summary Orchestrator reads is bounded by
  Prime's structure, not Flight's work volume).

### Status: COMPLETED (methodology); measurement PENDING (#396)

**Why methodology counts as COMPLETED here.** The measurement protocol is
load-bearing — if #396's executor doesn't know *which* token-count fields to
capture and *when*, the Scenario 10 verdict is unreproducible. This section
locks that down:

- **What to capture**: Orchestrator session tokens at T0 (pre-run), T1
  (after wave 1 post-wave Prime returns), T2 (after wave 2 post-wave Prime
  returns), plus a per-flight snapshot at each Prime(post-flight) return.
- **Where to find it**: CC's built-in usage report on the session (the
  tokens-used field shown during / at the end of each assistant message), or
  the Anthropic console billing log for the session's API calls.
- **How to compute the comparison**: pull the `results.md`, per-flight
  `merge-report.md`, and per-wave `merge-report.md` from the bus (preserved
  on the filesystem for the run), count tokens in each (trivially via
  `wc -w` × 1.3 or an actual tokenizer), sum to produce the naive-inline
  estimate, divide v2 actual / naive.

**Architectural evidence that v2 should bound:**

1. `skills/nextwave/SKILL.md:19`:

   > Filesystem bus keeps Orchestrator tokens O(1) per flight regardless of
   > flight content size.

2. `skills/nextwave/SKILL.md:110-112` — Orchestrator explicitly only reads
   the summary/checklist into context, not the full Flight output:

   > Parses each line. Malformed → record as FAIL, note "malformed return".
   > Verifies the `DONE` sentinel ... exists and contains `PASS` or `FAIL` ...
   > Reads each `results.md` into context (small, summary + checklist).

3. `decision_wavemachine_v2.md:56-58`:

   > Orchestrator context holds only paths and status tokens. Everything
   > that flows between agents (Flight prompts, Flight results, Prime
   > reports) lives on disk.

**Verdict for methodology:** PASS. The capture points, storage locations,
and ratio formula are pinned to specific file paths and fields. #396's
executor can mechanically fill in the numbers.

**Verdict for measurement:** PENDING (#396) — requires live Orchestrator run.

---

## How to run this test plan (for #396's executor)

1. Read this document top to bottom.
2. For each scenario currently marked **PENDING (#396)**:
   - Follow the Methodology bullet list.
   - Capture the signals listed under "Reproducibility conventions".
   - Replace the PENDING stub with: actual commands run, timing data,
     bus-tree snapshot excerpt (trimmed with `[...]` if large), Prime return
     JSON payloads, Discord post text, and a final PASS/FAIL verdict line.
3. For Scenario 10, fill in the v2-actual token counts and the naive-inline
   estimate; compute the ratio; record the per-flight increment table.
4. If any scenario fails, file a bug issue, fix it, re-run before closing
   #396 (per #396's acceptance criterion: "No scenario closes with
   unresolved FAIL").
5. PR against `main` with a test-plan summary in the PR description
   (aggregate PASS/FAIL across all live-run scenarios).

## Cross-references

- **Epic**: `#384` — Wavemachine v2 rewrite.
- **This issue (scaffolding)**: `#389`.
- **Live-run follow-up**: `#396`.
- **Wave 1–3 merged deliverables**: `#385` (wavebus scripts), `#386`
  (`/nextwave` rewrite), `#387` (`/wavemachine` rewrite), `#388` (docs),
  `#393` (canonical status JSON emission).
- **Design references**:
  - `skills/nextwave/SKILL.md` — Orchestrator/Prime/Flight protocol.
  - `skills/wavemachine/SKILL.md` — autopilot loop + circuit breaker.
  - `skills/wavemachine/introduction.md` — mental model.
  - `scripts/wavebus/flight-finalize` — atomic completion primitive.
  - `scripts/wavebus/wave-init` — bus creation primitive.
  - `scripts/wavebus/wave-cleanup` — safe teardown primitive.
  - `decision_wavemachine_v2.md` — v2 design doc (user memory).
  - `lesson_cc_subagent_tools.md` — the CC sub-agent tool distribution
    evidence (user memory).
  - `lesson_cross_repo_wave_orchestration.md` — Scenario 9 reference (user
    memory).
