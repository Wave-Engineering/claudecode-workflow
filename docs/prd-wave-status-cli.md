# Wave Status CLI — Product Requirements Document

**Version:** 2.0
**Date:** 2026-03-24
**Status:** Draft
**Authors:** bakerb, Claude (Hexadecimal :crystal_ball:)

---

## Table of Contents

1. [Problem Domain](#1-problem-domain)
2. [Constraints](#2-constraints)
3. [Requirements (EARS Format)](#3-requirements-ears-format)
4. [Concept of Operations](#4-concept-of-operations)
5. [Detailed Design](#5-detailed-design)
6. [Definition of Done](#6-definition-of-done)
7. [Phased Implementation Plan](#7-phased-implementation-plan)
8. [Appendices](#8-appendices)

---

## 1. Problem Domain

### 1.1 Background

The `/nextwave` skill orchestrates parallel sub-agents across isolated git worktrees to implement GitHub/GitLab issues in dependency-ordered waves. During execution, the orchestrating agent needs to communicate progress to the human operator via a self-contained HTML dashboard. The current mechanism works: three JSON files (`phases-waves.json`, `flights.json`, `state.json`) in `<repo>/.claude/status/` are manipulated directly by the agent, and a Python generator script (`generate-status-panel`) renders them into a cyberpunk-themed HTML dashboard.

### 1.2 Problem Statement

The current design requires the AI agent to know three JSON schemas, determine which files to update for each lifecycle transition, remember to call `generate-status-panel` after every state change, and carry ~200+ tokens of JSON manipulation ceremony in its prompt. This creates cognitive overhead (the agent reasons about JSON structure instead of wave execution), token waste (~840 tokens per wave), missed updates (agent forgets to regenerate HTML), and tight coupling (any schema change requires updating skill specs).

### 1.3 Proposed Solution

Replace direct JSON manipulation with a single CLI script (`wave-status`) that provides a task-oriented API with subcommands mapping 1:1 to the wave execution lifecycle. The agent calls one short shell command per transition; the script handles all state updates, validation, and HTML regeneration internally.

### 1.4 Target Users

| Persona | Description | Primary Use Case |
|---------|-------------|------------------|
| **AI orchestration agent** | The `/nextwave` skill running inside Claude Code | Calls `wave-status <subcommand>` at each lifecycle transition to report progress without managing JSON directly |
| **Human operator** | Developer monitoring wave execution progress | Views the generated HTML dashboard in a browser; sees near-real-time updates via JS polling |
| **AI planning agent** | The `/prepwaves` skill that creates the initial wave plan | Calls `wave-status init` once to record the phased wave plan and generate the initial dashboard |

### 1.5 Non-Goals

- **Not a skill update.** Changes to `/nextwave` and `/prepwaves` SKILL.md files to call these commands are a separate task. This PRD covers only the CLI tooling.
- **Not a multi-project dashboard.** Aggregating status across multiple repos is out of scope.
- **Not a theme redesign.** The existing cyberpunk aesthetic is preserved exactly as-is.
- **Not a notification system.** Slack/webhook integrations are future work.

---

## 2. Constraints

### 2.1 Technical Constraints

| ID | Constraint | Rationale |
|----|-----------|-----------|
| CT-01 | Self-contained Python 3.10+ with no external dependencies | Scripts install to `~/.local/bin/` via the project's `install.sh` copy model. No package manager, no virtualenv, no pip. |
| CT-02 | Single executable installed to `~/.local/bin/wave-status`, built from source via `python3 -m zipapp` | The install target is a single file — no fragile import paths at runtime. Source is a standard Python package in `src/wave_status/`, enabling modular development and parallel implementation. The zipapp build step bridges modular source and single-file deployment. |
| CT-03 | JSON file format (`phases-waves.json`, `flights.json`, `state.json`) must be preserved | Backward compatibility with existing projects and the `generate-status-panel` script. |
| CT-04 | HTML output must be self-contained (inline CSS/JS, no external resources) | Dashboards are opened from arbitrary repos on developer machines with no guarantee of network access or build tooling. |
| CT-05 | Must work from any directory within a git repository | Project root discovered via `git rev-parse --show-toplevel`, matching existing script behavior. |
| CT-06 | Source organized as a Python package (`src/wave_status/`) with `__main__.py` entry point | Enables modular development: focused modules, parallel agent implementation, standard Python tooling (pytest imports, type checking). The zipapp build (CT-02) bridges modular source to single-file deployment. |

### 2.2 Product Constraints

| ID | Constraint | Rationale |
|----|-----------|-----------|
| CP-01 | Each subcommand must complete in < 200ms on typical hardware | The agent calls these commands 6-10 times per wave. Latency compounds and wastes context window time. |
| CP-02 | Agent-facing CLI surface must be stable across internal refactors | The whole point is decoupling. Changing JSON structure or HTML layout must not require skill spec updates. |

---

## 3. Requirements (EARS Format)

Requirements follow the **EARS** (Easy Approach to Requirements Syntax) notation:

- **Ubiquitous**: The system shall [function].
- **Event-driven**: When [event], the system shall [function].
- **State-driven**: While [state], the system shall [function].
- **Unwanted**: If [unwanted condition], then the system shall [function].

TRACEABILITY: Every requirement ID appears in at least one Acceptance Criteria item in Section 7 and is tracked in the VRTM (Section 8, Appendix V).

### 3.1 CLI Interface

| ID | Type | Requirement |
|----|------|-------------|
| R-01 | Ubiquitous | The system shall provide a single `wave-status` CLI script with subcommands. |
| R-02 | Event-driven | When `wave-status init <file>` is called, the system shall read the plan, write `phases-waves.json`, initialize `state.json` and `flights.json`, and generate the dashboard. |
| R-03 | Event-driven | When `wave-status init -` is called, the system shall read the plan from stdin. |
| R-04 | Event-driven | When `wave-status flight-plan <file>` is called, the system shall store the flight plan for the current wave in `flights.json` and regenerate the dashboard. |
| R-05 | Event-driven | When any lifecycle subcommand (`preflight`, `planning`, `flight`, `flight-done`, `review`, `complete`, `waiting`) is called, the system shall update `state.json` and regenerate the dashboard. |
| R-06 | Event-driven | When `wave-status show` is called, the system shall print a human-readable summary of current state to stdout without modifying any files. |
| R-07 | Event-driven | When `wave-status close-issue <N>` is called, the system shall set issue N's status to `closed` in `state.json` and regenerate the dashboard. |
| R-08 | Event-driven | When `wave-status record-mr <issue> <mr>` is called, the system shall record the MR/PR reference for the issue in the current wave's `mr_urls` and regenerate the dashboard. |
| R-09 | Event-driven | When `wave-status defer <description> <risk>` is called, the system shall append a deferral with status `pending` to `state.json` and regenerate the dashboard. |
| R-10 | Event-driven | When `wave-status defer-accept <index>` is called, the system shall transition the deferral at that index from `pending` to `accepted` and regenerate the dashboard. |

### 3.2 State Machine

| ID | Type | Requirement |
|----|------|-------------|
| R-11 | Unwanted | If `wave-status flight N` is called and N > 1 and flight N-1 is not `completed`, then the system shall exit with an error message and make no state changes. |
| R-12 | Unwanted | If `wave-status flight-done N` is called and flight N is not `running`, then the system shall exit with an error message and make no state changes. |
| R-13 | Event-driven | When `wave-status complete` is called, the system shall set the current wave to `completed` and advance `current_wave` to the next pending wave (or `null` if all waves are done). |
| R-14 | Unwanted | If `wave-status close-issue <N>` is called and issue N does not exist in the plan, then the system shall exit with an error. |
| R-15 | Unwanted | If `wave-status defer` is called with a risk level other than `low`, `medium`, or `high`, then the system shall exit with an error. |
| R-16 | Unwanted | If `wave-status defer-accept <index>` is called and the index does not exist or the deferral is not `pending`, then the system shall exit with an error. |

### 3.3 Dashboard — Layout and Components

| ID | Type | Requirement |
|----|------|-------------|
| R-17 | Ubiquitous | The system shall generate a self-contained HTML dashboard with all CSS and JS inline. |
| R-18 | Ubiquitous | The dashboard shall display components in this order top-to-bottom: header, action banner, progress rail, gauge cards, pending deferrals, execution grid, accepted deferrals, footer. |
| R-19 | Ubiquitous | The dashboard shall include a **progress rail** — a full-width segmented bar showing global issue completion, with each segment representing one phase. |
| R-20 | Ubiquitous | Each progress rail segment's width shall be proportional to the number of issues in that phase. |
| R-21 | Ubiquitous | The progress rail shall render completed issues at full opacity (alpha 1.0) and remaining issues at 20% opacity (alpha 0.2) within each phase segment. |
| R-22 | Ubiquitous | Progress rail phase segments shall cycle through fuchsia, cyan, green, and yellow (mod 4) to visually distinguish phase boundaries. |
| R-23 | Ubiquitous | The progress rail shall display `w/z issues (p%)` as text above or overlaid on the bar. |
| R-24 | Ubiquitous | The dashboard shall display four **gauge cards**: Phase (x/y), Wave (n/m scoped to current phase), Flight (i/j scoped to current wave), and Deferrals (u pending / v accepted). Each gauge card shall include a progress bar. |
| R-25 | Ubiquitous | The **pending deferrals** section shall appear above the execution grid and shall be visible only when pending deferrals exist (collapses to zero height otherwise). |
| R-26 | Ubiquitous | The **accepted deferrals** section shall appear below the execution grid. |

### 3.4 Dashboard — Dynamic Updates

| ID | Type | Requirement |
|----|------|-------------|
| R-27 | Ubiquitous | The dashboard shall include a JavaScript polling block that fetches `state.json` every 3 seconds and updates dynamic content (action banner, progress rail, gauge cards, issue/wave/flight statuses, MR URLs, deferral sections, footer timestamp) via DOM manipulation. |
| R-28 | Unwanted | If JS polling fails (file:// CORS restriction or network error), the system shall disable polling and display a "Live updates unavailable — refresh to update" notice in the footer. |
| R-29 | Ubiquitous | The dashboard shall use `data-*` attributes on dynamic elements to enable targeted DOM updates without fragile traversal. |
| R-30 | Ubiquitous | The visual design (colors, fonts, layout, animations) shall match the existing cyberpunk theme exactly (see Section 8, Appendix A). |

### 3.5 Error Handling and Infrastructure

| ID | Type | Requirement |
|----|------|-------------|
| R-31 | Unwanted | If the script is run outside a git repository, then it shall exit code 1 with an appropriate error message. |
| R-32 | Ubiquitous | All error messages shall follow the pattern `Error: <what went wrong>. <what to do>.` |
| R-33 | Ubiquitous | The system shall use atomic file writes (write to temp file, then rename) to prevent JS polling from reading half-written JSON. |
| R-34 | Ubiquitous | The system shall discover the project root via `git rev-parse --show-toplevel`. |
| R-35 | Ubiquitous | The system shall create the `.claude/status/` directory if it does not exist. |

---

## 4. Concept of Operations

### 4.1 System Context

```
┌──────────────────┐     shell calls      ┌──────────────┐
│  /prepwaves      │ ──────────────────>   │              │
│  (planning)      │   wave-status init    │              │
└──────────────────┘                       │  wave-status │
                                           │   (CLI)      │
┌──────────────────┐     shell calls       │              │
│  /nextwave       │ ──────────────────>   │              │
│  (execution)     │   wave-status         │              │
│                  │   preflight/flight/   │              │
│                  │   complete/etc.       └──────┬───────┘
└──────────────────┘                              │
                                            reads/writes
                                                  │
                                                  v
                                     ┌─────────────────────┐
                                     │  .claude/status/     │
                                     │  ├ phases-waves.json │
                                     │  ├ flights.json      │
                                     │  └ state.json        │
                                     └──────────┬──────────┘
                                                │
                                           generates
                                                │
                                                v
                                     ┌─────────────────────┐
                                     │ .status-panel.html   │◄── JS polls state.json
                                     │ (browser dashboard)  │    every 3s for live updates
                                     └─────────────────────┘
                                                ^
                                                │
                                            views in browser
                                                │
                                     ┌─────────────────────┐
                                     │   Human operator     │
                                     └─────────────────────┘
```

### 4.2 Typical Wave Execution Flow

1. **Plan creation** (`/prepwaves`): Agent analyzes issues, computes wave order, calls `wave-status init plan.json` once. Dashboard appears with all phases/waves/issues in pending state. The progress rail shows a fully-faded bar segmented by phase.

2. **Wave start** (`/nextwave`): Agent calls `wave-status preflight`, then `wave-status planning`. The action banner updates through lifecycle states.

3. **Flight execution**: After planning agents report, agent calls `wave-status flight-plan flights.json`, then `wave-status flight 1`. Sub-agents execute on worktrees. Agent calls `wave-status record-mr` and `wave-status close-issue` as MRs merge. The progress rail fills incrementally as issues close. Calls `wave-status flight-done 1` when the flight is complete. Repeats for subsequent flights. The Flight gauge card tracks i/j progress within the wave.

4. **Deferrals**: During execution, agent calls `wave-status defer "description" low` for items to revisit. These appear in the pending deferrals section above the execution grid. At wave review, the operator discusses each pending deferral and the agent calls `wave-status defer-accept <index>` for approved ones, which move to the accepted deferrals section below the execution grid.

5. **Wave completion**: Agent calls `wave-status review`, then `wave-status complete`. The gauge cards advance: Wave gauge resets for the new wave within the current phase (or the Phase gauge ticks forward if crossing a phase boundary). Agent calls `wave-status waiting "message"` — the action banner shows the throbbing "waiting on meatbag" state.

6. **Repeat** from step 2 for the next wave until all waves are complete.

### 4.3 Graceful Degradation Flow

When the dashboard is opened via `file://` protocol:
1. JS polling attempts `fetch()` on `state.json`
2. Browser blocks the request (CORS on file://)
3. Polling script catches the error, disables the interval
4. Footer shows "Live updates unavailable — refresh to update"
5. Dashboard remains fully functional as a static snapshot — user refreshes to see updates

---

## 5. Detailed Design

### 5.1 Terminology Dictionary

**Data model — the execution hierarchy:**

| Term | Definition |
|------|-----------|
| **Phase** | A major milestone containing one or more waves. Maps to an Epic in the project tracker. |
| **Wave** | A dependency-ordered group of issues within a phase. All issues in a wave have their dependencies satisfied by prior waves. |
| **Flight** | A conflict-free subset of a wave's issues that can execute in parallel without file-level conflicts. Determined at runtime by planning agents. |
| **Issue** | A single tracked work item (GitHub Issue / GitLab Issue). The atomic unit of work. |
| **Deferral** | An item identified during execution that is deferred for later attention. Lifecycle: `pending` (needs discussion at wave end) → `accepted` (discussed, recorded as a tracking issue). |

**Dashboard layout — named components, top to bottom:**

| Term | Description |
|------|-----------|
| **Header** | Project name + meta line (current wave, base branch, master issue). |
| **Action banner** | Full-width lifecycle state indicator. Shows current step: preflight, planning, in-flight, merging, review, waiting-on-meatbag, or idle. |
| **Progress rail** | Full-width segmented bar showing global issue completion. Each segment is one phase, colored distinctly (fuchsia → cyan → green → yellow, cycling mod 4). Solid = completed issues, faded (80% transparent) = remaining. Text: `w/z issues (p%)`. |
| **Gauge cards** | Four compact cards with progress bars: Phase (x/y), Wave (n/m within current phase), Flight (i/j within current wave), Deferrals (u pending / v accepted). |
| **Pending deferrals** | Table of deferrals needing discussion at wave end. Visible only when pending items exist; collapses to zero height otherwise. |
| **Execution grid** | The phase → wave → flight → issue hierarchy. The main body of the dashboard showing all phases as collapsible sections containing wave cards with issue tables. |
| **Accepted deferrals** | Table of deferrals that have been discussed and recorded as tracking issues. Below the execution grid. |
| **Footer** | Generation timestamp, last state update timestamp. Live-update fallback notice when applicable. |

### 5.2 Subcommand Reference

| Subcommand | Args | State Changes | Output |
|------------|------|---------------|--------|
| `init <file\|->` | Plan JSON | Write all 3 JSON files + dashboard | `Status panel initialized for <project> (<N> phases, <M> waves, <K> issues)` |
| `flight-plan <file\|->` | Flight JSON | Update `flights.json` + dashboard | `Flight plan recorded for <wave> (<N> flights, <M> issues)` |
| `preflight` | — | `current_action` → pre-flight | `Status: pre-flight` |
| `planning` | — | `current_action` → planning; wave → `in_progress` | `Status: planning (<wave>)` |
| `flight <N>` | Flight number | `current_action` → in-flight; flight N → `running` | `Status: flight <N> (<wave>) — issues: #X, #Y` |
| `flight-done <N>` | Flight number | Flight N → `completed`; `current_action` → merging | `Status: flight <N> done (<wave>)` |
| `review` | — | `current_action` → post-wave-review | `Status: review (<wave>)` |
| `complete` | — | Wave → `completed`; advance `current_wave`; action → idle | `Status: <wave> complete. Next: <next>` |
| `waiting [msg]` | Optional message | `current_action` → waiting-on-meatbag | `Status: waiting` or `Status: waiting — <msg>` |
| `show` | — | None (read-only) | Compact state summary to stdout |
| `close-issue <N>` | Issue number | Issue → `closed` | `Issue #<N> closed` |
| `record-mr <issue> <mr>` | Issue number, MR ref | Add to `mr_urls` | `MR <mr> recorded for issue #<issue>` |
| `defer <desc> <risk>` | Description, risk level | Append deferral (`pending`) | `Deferral recorded (<risk>): <desc>` |
| `defer-accept <index>` | Deferral index (1-based) | Deferral → `accepted` | `Deferral <index> accepted: <desc>` |

### 5.3 State Machine

```
                   init
                    │
                    v
              [idle/waiting]
                    │
                preflight
                    │
                    v
                planning
                    │
              flight-plan
                    │
                    v
               flight 1
                    │
                    v
             flight-done 1
                 │     \
                 v      (if more flights)
            flight 2        │
                 │          │
                 v          │
           flight-done 2    │
                 │   ...   /
                 v
               review
                 │
                 v
              complete ──────> advance to next wave
                 │                    │
                 v                    v
              waiting           [idle/waiting]
```

**Strict ordering** (enforced — violations rejected with error):
- `flight N` requires flight N-1 to be `completed` (for N > 1)
- `flight-done N` requires flight N to be `running`

**Soft ordering** (recommended but not enforced):
- `preflight` → `planning` → `flight-plan` → `flight 1` → ... → `review` → `complete`

Rationale for soft macro ordering: agents sometimes skip steps for trivial waves (e.g., single-issue waves may skip `review`). Rejecting valid operations would cause more harm than accepting them out of textbook order. Flight ordering is strict because misordering flights violates dependency guarantees.

**Cross-cutting subcommands** (callable from any state):
- `close-issue`, `record-mr`, `defer`, `defer-accept`, `waiting`, `show`

### 5.4 Deferral Lifecycle

Deferrals have a two-state lifecycle:

```
wave-status defer "description" <risk>       wave-status defer-accept <index>
              │                                          │
              v                                          v
          [pending] ──────────────────────────────> [accepted]
```

- **Pending**: Recorded during wave execution. Displayed in the pending deferrals section (above the execution grid) for discussion at wave end.
- **Accepted**: Operator has reviewed the deferral and it has been recorded as a tracking issue on the platform. Displayed in the accepted deferrals section (below the execution grid).

The Deferrals gauge card shows both counts: `u pending / v accepted`.

Deferral schema in `state.json`:
```json
{
  "deferrals": [
    {"wave": "wave-1", "description": "CP-01 human review", "risk": "low", "status": "pending"},
    {"wave": "wave-1", "description": "README section", "risk": "low", "status": "accepted"}
  ]
}
```

### 5.5 `show` Subcommand Output Format

```
Wave Status: kairos
  Phase:          1/4 (Foundation)
  Wave:           2/2 in phase 1
  Flight:         —
  Action:         waiting-on-meatbag — Wave 2 complete. Ready for /nextwave.
  Progress:       8/11 issues (73%)
  Deferrals:      1 pending, 2 accepted
```

Read-only — no files modified, no dashboard regenerated.

### 5.6 Progress Rail Design

The progress rail is a full-width bar placed between the action banner and the gauge cards. It visualizes global issue completion with phase boundaries.

```
                              8/11 issues (73%)
┌─── Phase 1 (fuchsia) ───┬── Phase 2 (cyan) ──────────┬─ Phase 3 (green) ─┬─ P4 ─┐
│██████████████████████████│███████████░░░░░░░░░░░░░░░░░░│░░░░░░░░░░░░░░░░░░░│░░░░░░│
└──────────────────────────┴────────────────────────────────┴───────────────────┴──────┘
```

- Each phase segment's **width** is proportional to the number of issues in that phase.
- Within each segment, **solid** (full opacity) = closed issues, **faded** (80% transparent) = open issues.
- Phase boundaries are visible as thin borders or gaps.
- Text `w/z issues (p%)` displayed above the bar.

**Phase color cycle** (mod 4):

| Phase mod 4 | Color | Token |
|-------------|-------|-------|
| 1 | Fuchsia | `--fuchsia` (`#ff00ff`) |
| 2 | Cyan | `--cyan` (`#00ffff`) |
| 3 | Green | `--green` (`#00ff88`) |
| 4 | Yellow | `--yellow` (`#ffcc00`) |

Phase 5 cycles back to fuchsia, etc.

### 5.7 Gauge Cards Design

Four cards displayed in a horizontal row below the progress rail.

| Card | Label | Value | Sub-line | Progress bar |
|------|-------|-------|----------|-------------|
| **Phase** | `Phase` | `x/y` | Name of current phase | x/y ratio |
| **Wave** | `Wave` | `n/m` | Scoped to current phase: wave n of m waves in phase x | n/m ratio |
| **Flight** | `Flight` | `i/j` | Scoped to current wave: flight i of j flights. Shows `—` before `flight-plan` is called. | i/j ratio (empty when no flights) |
| **Deferrals** | `Deferrals` | `u pending` | `v accepted` | u/(u+v) ratio — drains toward zero as pending items are accepted |

### 5.8 Dashboard Architecture

The dashboard has two tiers:

**Static tier** (rebuilt on every subcommand that modifies state):
- All layout structure: header, action banner container, progress rail segments, gauge card shells, deferral table structure, execution grid (phase sections, wave cards, issue table rows, flight badges)
- Full CSS and JS polling script

**Dynamic tier** (updated via JS polling of `state.json` every 3s):
- Action banner (text, CSS class, throb animation)
- Progress rail segment fill widths and text
- Gauge card values and progress bar widths
- Issue/wave/flight status badges and icons
- MR URLs in issue table rows
- Pending and accepted deferral counts and table contents
- Footer timestamp

HTML elements use `data-*` attributes for JS targeting:
```html
<td data-issue="13" data-field="status">closed</td>
<div data-wave="wave-1" data-field="status" class="badge completed">completed</div>
<div data-gauge="phase" data-field="value" class="value">1/4</div>
<div data-rail-phase="phase-1" data-field="fill" style="width: 100%"></div>
```

### 5.9 Atomic File Writes

All JSON writes use write-to-tempfile + `os.replace()` (atomic on POSIX). This prevents the JS polling from reading a half-written `state.json`. The tempfile is created in the same directory as the target to guarantee same-filesystem rename.

### 5.10 File Layout

**Source (repo):**

| Path | Purpose |
|------|---------|
| `src/wave_status/` | Python package source (see Section 5.11 for module breakdown) |
| `scripts/ci/build.sh` | Zipapp build script — bundles `src/wave_status/` → `dist/wave-status` |
| `tests/test_wave_status.py` | Test suite |
| `dist/` | Build output directory (gitignored) |

**Installed (local machine):**

| Path | Purpose |
|------|---------|
| `~/.local/bin/wave-status` | Zipapp executable (installed by `install.sh`) |

**Runtime (per-project, gitignored):**

| Path | Purpose |
|------|---------|
| `<repo>/.claude/status/` | Status data directory (created if absent) |
| `<repo>/.claude/status/phases-waves.json` | Phased wave plan (structure) |
| `<repo>/.claude/status/flights.json` | Flight plans per wave (runtime) |
| `<repo>/.claude/status/state.json` | Dynamic state (runtime) |
| `<repo>/.status-panel.html` | Generated dashboard (gitignored) |

### 5.11 Source Package Architecture

```
src/wave_status/
├── __init__.py              # Package marker, version string
├── __main__.py              # CLI entry point — argparse, subcommand dispatch
├── state.py                 # State machine, JSON I/O, atomic writes, path helpers
├── deferrals.py             # Deferral lifecycle (pending → accepted)
└── dashboard/
    ├── __init__.py           # Package marker
    ├── generator.py          # Assembles components into full HTML document
    ├── theme.py              # CSS custom properties, base styles, action banner CSS
    ├── polling.py            # JavaScript polling script with file:// fallback
    ├── progress_rail.py      # Progress rail component
    ├── gauge_cards.py        # Four gauge cards component
    ├── execution_grid.py     # Phase/wave/issue grid component
    └── deferral_sections.py  # Pending + accepted deferral tables
```

**Module boundaries:**

- **`state.py`** and **`deferrals.py`** contain all business logic. They operate on Python dicts (loaded JSON) and have no knowledge of HTML or presentation.
- **`dashboard/*`** modules contain all presentation logic. Each component receives data dicts as arguments and returns an HTML string. Components do not import each other — they share conventions (CSS class names) via the specs, not via code coupling.
- **`__main__.py`** is the wiring layer: parses CLI args, calls business logic, then calls the dashboard generator.
- **`generator.py`** is the composition layer: calls each dashboard component and assembles the results into a complete HTML document.

**Build output:**

```bash
python3 -m zipapp src/wave_status -o dist/wave-status -p '/usr/bin/env python3'
```

The resulting `dist/wave-status` is a single executable file containing the entire package. `install.sh` copies it to `~/.local/bin/wave-status`.

### 5.12 Open Questions

1. **`show` output verbosity:** Should `show` have a `--verbose` flag that dumps the full JSON state? Leaning no — keep it simple, agents can read JSON directly if they need raw data.

---

## 6. Definition of Done

- [ ] All Phase DoD checklists are satisfied
- [ ] `wave-status` source is a Python 3.10+ package in `src/wave_status/` with no external dependencies [R-01, CT-01, CT-06]
- [ ] `scripts/ci/build.sh` produces a working zipapp at `dist/wave-status` [CT-02]
- [ ] `install.sh` builds and installs `wave-status` to `~/.local/bin/` [CT-02]
- [ ] The existing `generate-status-panel` script continues to produce valid output from the same JSON files [CT-03]
- [ ] The example session from Appendix B runs successfully end-to-end [R-02 through R-10]
- [ ] Dashboard displays all named components in the correct order: header, action banner, progress rail, gauge cards, pending deferrals, execution grid, accepted deferrals, footer [R-18]
- [ ] Skill helper scripts co-located with their SKILL.md files (repo taxonomy restructured)
- [ ] All tests pass (`pytest tests/`)

---

## 7. Phased Implementation Plan

### How to read this section

**Phases map to Epics.** This project has one phase — it's tightly scoped.

**Waves enable parallel development.** The modular source package (Section 5.11) was designed specifically to maximize wave parallelism. Each module is an independent file that a separate agent can implement without merge conflicts.

### Wave Map

```
Wave 1 ─┬─ [1.1] State machine        (src/wave_status/state.py)
         ├─ [1.2] Deferral engine       (src/wave_status/deferrals.py)
         ├─ [1.3] Dashboard theme       (src/wave_status/dashboard/theme.py, polling.py)
         └─ [1.4] Repo taxonomy         (install.sh, sync.sh, uninstall.sh, validate.sh)
              │
Wave 2 ─┬─ [2.1] Progress rail         (src/wave_status/dashboard/progress_rail.py)
         ├─ [2.2] Gauge cards           (src/wave_status/dashboard/gauge_cards.py)
         └─ [2.3] Execution grid        (src/wave_status/dashboard/execution_grid.py,
              │                           deferral_sections.py)
              │
Wave 3 ─┬─ [3.1] Dashboard generator   (src/wave_status/dashboard/generator.py)
         └─ [3.2] CLI entry point       (src/wave_status/__main__.py)
              │
Wave 4 ─┬─ [4.1] Build pipeline        (scripts/ci/build.sh, install.sh integration)
         └─ [4.2] Test suite            (tests/test_wave_status.py)
```

| Wave | Stories | Parallel? | Rationale |
|------|---------|-----------|-----------|
| 1 | 1.1, 1.2, 1.3, 1.4 | Yes — all independent files, zero overlap | Business logic, presentation foundation, and repo restructure are fully decoupled |
| 2 | 2.1, 2.2, 2.3 | Yes — each a separate dashboard component | Components receive data dicts and return HTML strings; share CSS conventions, not imports |
| 3 | 3.1, 3.2 | Yes — generator assembles HTML, CLI wires subcommands | Both depend on Wave 1+2 modules but don't touch each other's files |
| 4 | 4.1, 4.2 | Yes — build script and test suite are different files | Tests use `python -m wave_status` against source tree; build produces zipapp separately |

**Total: 11 stories, 4 waves, max parallelism 4.**

---

### Phase 1: Wave Status CLI (Epic)

**Goal:** Replace direct JSON manipulation with a task-oriented CLI built from a modular Python package, installed as a single executable via zipapp.

#### Phase 1 Definition of Done

- [ ] `wave-status init` creates all status files and generates the dashboard [R-02]
- [ ] All 14 subcommands function correctly [R-01 through R-16, R-31, R-32]
- [ ] Flight ordering is strictly enforced [R-11, R-12]
- [ ] Dashboard includes progress rail with phase-colored segments [R-19, R-22]
- [ ] Dashboard includes gauge cards (Phase, Wave, Flight, Deferrals) [R-24]
- [ ] Dashboard includes JS polling with file:// fallback [R-27, R-28]
- [ ] Pending deferrals appear above the execution grid; accepted deferrals below [R-25, R-26]
- [ ] `scripts/ci/build.sh` produces a working zipapp [CT-02, CT-06]
- [ ] `install.sh` builds and installs `wave-status` to `~/.local/bin/` [CT-02]
- [ ] Skill helper scripts co-located with their SKILL.md files
- [ ] All tests pass

---

#### Story 1.1: State Machine

**Wave:** 1
**Dependencies:** None
**File:** `src/wave_status/state.py`

Core state management: JSON I/O with atomic writes, git root discovery, and all state transitions for the wave execution lifecycle. This module contains all business logic for the wave state machine — no presentation, no CLI, no HTML.

**Implementation Steps:**

1. Create `src/wave_status/__init__.py` (package marker with `__version__`)
2. Create `src/wave_status/state.py`
3. Implement path helpers:
   - `get_project_root()` — `git rev-parse --show-toplevel`, raises on failure [R-31, R-34]
   - `status_dir(root)` / `html_path(root)` — path construction
   - `ensure_status_dir(root)` — create `.claude/status/` if absent [R-35]
4. Implement atomic JSON I/O:
   - `load_json(path)` — read and parse
   - `save_json(path, data)` — write to `tempfile.NamedTemporaryFile` in same directory, then `os.replace()` [R-33]
5. Implement state machine operations (all take/return data dicts, I/O via load/save helpers):
   - `init_state(plan_data)` — validate plan (requires `project`, `phases`), write `phases-waves.json`, initialize `state.json` (all waves pending, all issues open, `current_wave` = first wave, `current_action` = idle, empty deferrals), initialize `flights.json` as `{"flights": {}}` [R-02]
   - `store_flight_plan(flights_data)` — store flights keyed by current wave ID in `flights.json` [R-04]
   - `preflight()`, `planning()`, `review()`, `waiting(msg)` — update `current_action` in `state.json` [R-05]
   - `planning()` — also sets current wave to `in_progress`
   - `flight(n)` — **strict**: validate N > 1 requires flight N-1 is `completed`; set flight to `running` [R-11]
   - `flight_done(n)` — **strict**: validate flight N is `running`; set to `completed` [R-12]
   - `complete()` — set wave to `completed`, advance `current_wave` to next pending wave (or `null`) [R-13]
   - `close_issue(n)` — validate issue exists in plan, set to `closed` [R-07, R-14]
   - `record_mr(issue, mr)` — record MR/PR reference for issue [R-08]
   - `show()` — return summary dict without writing anything [R-06]
6. Error handling: raise `ValueError` with messages following `Error: <what>. <fix>.` [R-32]

**Acceptance Criteria:**

- [ ] `state.py` implements all lifecycle transitions [R-05]
- [ ] `init_state()` writes `phases-waves.json`, `state.json`, `flights.json` [R-02]
- [ ] `flight(2)` raises error if flight 1 not completed [R-11]
- [ ] `flight_done(1)` raises error if flight 1 not running [R-12]
- [ ] `complete()` advances `current_wave` to next pending wave [R-13]
- [ ] `close_issue(999)` raises error for nonexistent issue [R-14]
- [ ] `store_flight_plan()` stores flights keyed by current wave ID in `flights.json` [R-04]
- [ ] `show()` returns state dict without modifying files [R-06]
- [ ] JSON writes use `tempfile` + `os.replace()` [R-33]
- [ ] Git root discovery via `git rev-parse --show-toplevel` [R-34]
- [ ] Creates `.claude/status/` if absent [R-35]
- [ ] JSON files (`phases-waves.json`, `flights.json`, `state.json`) preserve existing schema for backward compatibility with `generate-status-panel` [CT-03]
- [ ] Works correctly when invoked from any directory within a git repo [CT-05]
- [ ] Raises appropriate error outside git repo [R-31]
- [ ] Error messages follow `Error: <what>. <fix>.` pattern [R-32]
- [ ] No imports outside Python 3.10+ stdlib [CT-01]

---

#### Story 1.2: Deferral Engine

**Wave:** 1
**Dependencies:** None
**File:** `src/wave_status/deferrals.py`

Deferral lifecycle management: creating, validating, transitioning, and querying deferrals. All methods operate on state data dicts passed as arguments — I/O responsibility stays in `state.py`.

**Implementation Steps:**

1. Create `src/wave_status/deferrals.py`
2. Implement deferral operations:
   - `defer(state_data, description, risk, current_wave)` — validate `risk` in `{low, medium, high}`, append deferral dict with `status: "pending"` to `state_data["deferrals"]` [R-09, R-15]
   - `accept(state_data, index)` — validate 1-based index exists, validate status is `pending`, transition to `accepted` [R-10, R-16]
3. Implement query helpers (used by dashboard components):
   - `pending_count(state_data)` / `accepted_count(state_data)`
   - `pending_list(state_data)` / `accepted_list(state_data)` — filtered sublists

**Acceptance Criteria:**

- [ ] `defer()` appends deferral with status `pending` [R-09]
- [ ] `defer()` rejects risk levels other than low/medium/high [R-15]
- [ ] `accept()` transitions deferral from `pending` to `accepted` [R-10]
- [ ] `accept()` rejects invalid index (out of range) [R-16]
- [ ] `accept()` rejects already-accepted deferral [R-16]
- [ ] Query helpers return correct counts and filtered lists
- [ ] No imports outside Python 3.10+ stdlib [CT-01]

---

#### Story 1.3: Dashboard Theme + Polling

**Wave:** 1
**Dependencies:** None
**Files:** `src/wave_status/dashboard/theme.py`, `src/wave_status/dashboard/polling.py`

CSS design tokens, base styles, action banner states, and JavaScript polling script. These are foundational presentation modules — pure string constants and template functions with no business logic. Other dashboard components in Wave 2 will reference the CSS class names defined here.

**Implementation Steps:**

1. Create `src/wave_status/dashboard/__init__.py` (empty package marker)
2. Create `src/wave_status/dashboard/theme.py`:
   - `CSS_TOKENS` dict: all custom properties from Appendix A (`--bg`, `--surface`, `--fuchsia`, etc.)
   - `PHASE_COLORS` list: `[fuchsia, cyan, green, yellow]` with full/faded rgba values (see Appendix A, progress rail color cycle)
   - `ACTION_BANNER_STATES` dict: maps action names to `{icon, css_class, border_color, animation}` (see Appendix A)
   - `render_base_css()` → returns complete `<style>` content: custom properties, font stack (`JetBrains Mono` etc.), base layout, card styles, badge styles, action banner classes with animations (throb, glow)
3. Create `src/wave_status/dashboard/polling.py`:
   - `render_polling_script()` → returns `<script>` block:
     - Fetches `state.json` every 3s via `setInterval` [R-27]
     - Updates DOM elements via `data-*` attribute selectors [R-29]
     - On fetch error: clears interval, shows "Live updates unavailable — refresh to update" in footer [R-28]

**Acceptance Criteria:**

- [ ] `render_base_css()` includes all CSS custom properties from Appendix A [R-30]
- [ ] CSS includes all 7 action banner states with correct icons, colors, animations [R-30]
- [ ] `render_polling_script()` fetches `state.json` every 3s [R-27]
- [ ] Polling script disables on fetch failure with fallback notice [R-28]
- [ ] Polling script uses `data-*` selectors for DOM updates [R-29]
- [ ] No imports outside Python 3.10+ stdlib [CT-01]

---

#### Story 1.4: Repo Taxonomy Restructure

**Wave:** 1
**Dependencies:** None
**Files:** `install.sh`, `sync.sh`, `uninstall.sh`, `scripts/ci/validate.sh`, `.gitignore`, skill directories

Move skill helper scripts from `scripts/` into their owning skill directories. Update all install/sync/uninstall/validate tooling to support the new layout. Create `config/` directory for infrastructure files. This story touches NO wave-status code — it restructures existing repo assets.

**Context:** Currently, skill helper scripts (`job-fetch`, `slackbot-send`) live in `scripts/` alongside CI tooling and config. This conflates three categories. The new taxonomy:
- `skills/<name>/` — SKILL.md + helper scripts (co-located)
- `config/` — infrastructure config (statusline, settings template)
- `scripts/ci/` — CI/CD tooling only

**Implementation Steps:**

1. Move `scripts/job-fetch` → `skills/jfail/job-fetch`
2. Move `scripts/slackbot-send` → `skills/ping/slackbot-send`
3. Move `scripts/statusline-command.sh` → `config/statusline-command.sh`
4. Move `settings.template.json` → `config/settings.template.json`
5. Update `install.sh`:
   - Skills loop: also copy non-`SKILL.md` files from skill dirs to `~/.local/bin/` with `chmod +x`
   - Config section: read from `config/` instead of `scripts/`
   - Add placeholder comment for package builds (`# Package builds added by Story 4.1`)
6. Update `sync.sh`:
   - Skills section: also detect/sync helper scripts in skill dirs
   - Config section: sync from `config/` path
7. Update `uninstall.sh`:
   - Skills section: also remove helper scripts from `~/.local/bin/` that came from skill dirs
   - Config section: reference `config/` for discovery
8. Update `scripts/ci/validate.sh`:
   - Discover shell scripts from skill dirs (not just `scripts/`)
   - Skip non-shell files (detect via shebang or extension)
   - Add Python syntax check section: `py_compile` for `.py` files in `src/`
9. Add to `.gitignore`: `.status-panel.html`, `dist/`

**Acceptance Criteria:**

- [ ] `skills/jfail/job-fetch` exists; `scripts/job-fetch` removed
- [ ] `skills/ping/slackbot-send` exists; `scripts/slackbot-send` removed
- [ ] `config/statusline-command.sh` exists; `scripts/statusline-command.sh` removed
- [ ] `config/settings.template.json` exists; root `settings.template.json` removed
- [ ] `install.sh` installs skill helpers to `~/.local/bin/` with `chmod +x`
- [ ] `install.sh --check` reports skill helpers correctly
- [ ] `sync.sh --check` detects drift in skill helpers
- [ ] `uninstall.sh` removes skill helpers from `~/.local/bin/`
- [ ] `validate.sh` lints shell scripts discovered from skill dirs
- [ ] `validate.sh` runs Python syntax checks on `src/` files
- [ ] `validate.sh` does not attempt shellcheck on non-shell files
- [ ] `.gitignore` contains `.status-panel.html` and `dist/`
- [ ] All shell scripts pass shellcheck and shfmt

---

#### Story 2.1: Progress Rail

**Wave:** 2
**Dependencies:** Story 1.3 (uses CSS class names and color tokens from theme)
**File:** `src/wave_status/dashboard/progress_rail.py`

Renders the full-width progress rail showing global issue completion with phase-colored segments. Pure presentation — receives data dicts, returns HTML string.

**Implementation Steps:**

1. Create `src/wave_status/dashboard/progress_rail.py`
2. Implement `render_progress_rail(phases_data, state_data)` → HTML string:
   - Compute total issues and closed issues across all phases
   - For each phase:
     - Count issues in phase, count closed issues in phase
     - Compute proportional width as percentage of total issues [R-20]
     - Assign phase color from cycle: `PHASE_COLORS[phase_index % 4]` [R-22]
   - Render container div with:
     - Text overlay: `w/z issues (p%)` centered above bar [R-23]
     - Phase segment divs: proportional `width`, solid fill (rgba 1.0) for completed portion, faded fill (rgba 0.2) for remaining [R-19, R-21]
     - `data-rail-phase="phase-N"` and `data-field="fill"` attributes on fill elements [R-29]
     - Thin borders or gaps between phase segments

**Acceptance Criteria:**

- [ ] Returns valid HTML with phase-colored segments [R-19]
- [ ] Segment widths proportional to issue count per phase [R-20]
- [ ] Completed issues at full opacity (1.0), remaining at 0.2 [R-21]
- [ ] Colors cycle fuchsia → cyan → green → yellow mod 4 [R-22]
- [ ] Text shows `w/z issues (p%)` [R-23]
- [ ] `data-rail-phase` attributes on segments [R-29]
- [ ] No imports outside Python 3.10+ stdlib [CT-01]

---

#### Story 2.2: Gauge Cards

**Wave:** 2
**Dependencies:** Story 1.3 (uses CSS class names from theme)
**File:** `src/wave_status/dashboard/gauge_cards.py`

Renders the four metric gauge cards displayed below the progress rail. Pure presentation — receives data dicts, returns HTML string.

**Implementation Steps:**

1. Create `src/wave_status/dashboard/gauge_cards.py`
2. Implement `render_gauge_cards(phases_data, state_data, flights_data)` → HTML string:
   - **Phase card**: value `x/y` (current phase index / total phases), sub-line = phase name, progress bar = x/y ratio
   - **Wave card**: value `n/m` (current wave position within current phase / total waves in current phase), progress bar = n/m ratio
   - **Flight card**: value `i/j` (current flight / total flights in current wave), sub-line scoped to wave. Shows `—` before `flight-plan` is called (no flights yet). Progress bar = i/j ratio (empty when no flights).
   - **Deferrals card**: value `u pending`, sub-line `v accepted`, progress bar = u/(u+v) ratio (drains toward zero as pending items are accepted)
   - Each card: `data-gauge="<name>"` attribute on card, `data-field="value"` on value element [R-29]

**Acceptance Criteria:**

- [ ] Renders four gauge cards: Phase, Wave, Flight, Deferrals [R-24]
- [ ] Phase shows x/y with phase name sub-line
- [ ] Wave shows n/m scoped to current phase
- [ ] Flight shows i/j scoped to current wave; `—` before `flight-plan`
- [ ] Deferrals shows `u pending` / `v accepted`
- [ ] `data-gauge` and `data-field` attributes on cards [R-29]
- [ ] No imports outside Python 3.10+ stdlib [CT-01]

---

#### Story 2.3: Execution Grid + Deferral Sections

**Wave:** 2
**Dependencies:** Story 1.3 (uses CSS class names from theme)
**Files:** `src/wave_status/dashboard/execution_grid.py`, `src/wave_status/dashboard/deferral_sections.py`

The main body of the dashboard: phase sections containing wave cards with issue tables and flight badges. Plus the pending and accepted deferral tables. Two files, one story — they're small enough to pair and share an agent's context.

**Implementation Steps:**

1. Create `src/wave_status/dashboard/execution_grid.py`:
   - Implement `render_execution_grid(phases_data, state_data, flights_data)` → HTML string:
     - For each phase: section header with phase name/number, phase-colored accent
     - For each wave in phase: wave card with status badge (`pending`/`in_progress`/`completed`)
     - For each issue in wave: table row with issue number, title, status badge, MR link (if recorded)
     - For each flight in wave (if flight plan exists): flight badge with status
     - `data-wave`, `data-issue`, `data-field` attributes on dynamic elements [R-29]
2. Create `src/wave_status/dashboard/deferral_sections.py`:
   - Implement `render_pending_deferrals(state_data)` → HTML string:
     - Table of pending deferrals: 1-based index, wave, description, risk level
     - Container collapses to zero height when no pending items exist [R-25]
     - Orange-accented styling (`--orange` for pending items)
   - Implement `render_accepted_deferrals(state_data)` → HTML string:
     - Table of accepted deferrals: 1-based index, wave, description, risk level [R-26]
     - Subdued styling (resolved = less visual urgency)

**Acceptance Criteria:**

- [ ] Execution grid renders all phases, waves, issues, flights
- [ ] Issue rows show number, title, status badge, MR link [R-07, R-08]
- [ ] Flight badges show status [R-04]
- [ ] `data-wave`, `data-issue`, `data-field` attributes present [R-29]
- [ ] Pending deferrals section visible only when pending items exist [R-25]
- [ ] Pending deferrals section collapses to zero height when empty [R-25]
- [ ] Accepted deferrals section renders below execution grid [R-26]
- [ ] No imports outside Python 3.10+ stdlib [CT-01]

---

#### Story 3.1: Dashboard Generator

**Wave:** 3
**Dependencies:** Stories 1.3, 2.1, 2.2, 2.3 (imports all dashboard components)
**File:** `src/wave_status/dashboard/generator.py`

The composition layer: imports all dashboard components and assembles them into a complete, self-contained HTML document. Also renders the header, action banner, and footer directly (small enough not to need their own modules).

**Implementation Steps:**

1. Create `src/wave_status/dashboard/generator.py`
2. Implement `generate_dashboard(root, phases_data, state_data, flights_data)`:
   - Assemble HTML document in layout order [R-18]:
     1. `<!DOCTYPE html>` + `<head>` with `<style>` from `theme.render_base_css()`
     2. **Header**: project name, current wave, base branch, master issue reference
     3. **Action banner**: map `current_action` from `state_data` to icon/class/animation via `theme.ACTION_BANNER_STATES`
     4. **Progress rail**: from `progress_rail.render_progress_rail()`
     5. **Gauge cards**: from `gauge_cards.render_gauge_cards()`
     6. **Pending deferrals**: from `deferral_sections.render_pending_deferrals()`
     7. **Execution grid**: from `execution_grid.render_execution_grid()`
     8. **Accepted deferrals**: from `deferral_sections.render_accepted_deferrals()`
     9. **Footer**: generation timestamp, last state update timestamp, live-update fallback placeholder
     10. `<script>` from `polling.render_polling_script()`
   - Write assembled HTML to `<root>/.status-panel.html` using atomic write (tempfile + os.replace) [R-33]

**Acceptance Criteria:**

- [ ] Generated HTML is self-contained with inline CSS and JS, no external resources [R-17, CT-04]
- [ ] Layout order: header, action banner, progress rail, gauge cards, pending deferrals, execution grid, accepted deferrals, footer [R-18]
- [ ] Action banner reflects `current_action` state with correct icon/class [R-05]
- [ ] HTML written atomically to `.status-panel.html` [R-33]
- [ ] No imports outside Python 3.10+ stdlib [CT-01]

---

#### Story 3.2: CLI Entry Point

**Wave:** 3
**Dependencies:** Stories 1.1, 1.2, 3.1 (wires all modules together)
**Files:** `src/wave_status/__main__.py`

The argparse-based CLI that wires subcommands to the state machine, deferral engine, and dashboard generator. This is the only module that imports across package boundaries.

**Implementation Steps:**

1. Create `src/wave_status/__main__.py`
2. Implement argument parsing via `argparse` with subcommand dispatch for all 14 subcommands:
   - `init <file|->` — read plan from file or stdin (`-`), call `state.init_state()`, call `dashboard.generate_dashboard()` [R-02, R-03]
   - `flight-plan <file|->` — read flights, call `state.store_flight_plan()`, regenerate dashboard [R-04]
   - `preflight`, `planning`, `flight <N>`, `flight-done <N>`, `review`, `complete`, `waiting [msg]` — call corresponding `state.*()`, regenerate dashboard [R-05]
   - `close-issue <N>` — call `state.close_issue()`, regenerate dashboard [R-07]
   - `record-mr <issue> <mr>` — call `state.record_mr()`, regenerate dashboard [R-08]
   - `defer <desc> <risk>` — call `deferrals.defer()`, save state, regenerate dashboard [R-09]
   - `defer-accept <index>` — call `deferrals.accept()`, save state, regenerate dashboard [R-10]
   - `show` — call `state.show()`, format and print to stdout (NO dashboard regen) [R-06]
3. Implement error handling:
   - Catch `ValueError` from state/deferral modules → format as `Error: <what>. <fix>.`, exit 1 [R-32]
   - Catch unexpected exceptions → exit 2
4. Implement `main()` function as package entry point

**Acceptance Criteria:**

- [ ] `python -m wave_status init plan.json` creates all files + dashboard [R-02]
- [ ] `cat plan.json | python -m wave_status init -` reads from stdin [R-03]
- [ ] `python -m wave_status flight-plan flights.json` stores flights [R-04]
- [ ] All lifecycle subcommands update state and regenerate dashboard [R-05]
- [ ] `python -m wave_status show` prints summary without modifying files [R-06]
- [ ] `python -m wave_status close-issue 13` sets issue 13 to closed [R-07]
- [ ] `python -m wave_status record-mr 13 "#14"` records MR [R-08]
- [ ] `python -m wave_status defer "description" low` appends pending deferral [R-09]
- [ ] `python -m wave_status defer-accept 1` transitions to accepted [R-10]
- [ ] Error messages follow `Error: <what>. <fix>.` pattern [R-32]
- [ ] No imports outside Python 3.10+ stdlib [CT-01]

---

#### Story 4.1: Build Pipeline

**Wave:** 4
**Dependencies:** Stories 3.2, 1.4 (needs source package complete + install.sh restructured)
**Files:** `scripts/ci/build.sh`, updates to `install.sh`, `uninstall.sh`

Zipapp build script that bundles the source package into a single executable. Integrates with `install.sh` so that installing automatically builds from source.

**Implementation Steps:**

1. Create `scripts/ci/build.sh`:
   - Discover `src/*/` directories containing `__main__.py`
   - For each: run `python3 -m zipapp src/<name> -o dist/<name> -p '/usr/bin/env python3'`
   - Create `dist/` directory if absent
   - Report what was built (name, size)
   - Exit 0 on success, exit 1 on failure
2. Update `install.sh`:
   - Before the skills/config copy loops, call `scripts/ci/build.sh` (if `src/` exists)
   - Copy built artifacts from `dist/` to `~/.local/bin/` with `chmod +x`
   - `--check` mode: compare `dist/<name>` against `~/.local/bin/<name>` (rebuild first to ensure fresh comparison)
3. Update `uninstall.sh`:
   - Also remove `~/.local/bin/<name>` for packages discovered in `src/`
4. Add `dist/` to `.gitignore` (if not already added by Story 1.4)

**Acceptance Criteria:**

- [ ] `scripts/ci/build.sh` produces `dist/wave-status` as a valid zipapp [CT-02, CT-06]
- [ ] `dist/wave-status` is executable and runs correctly (`dist/wave-status --help`)
- [ ] `install.sh` calls `build.sh` and installs `wave-status` to `~/.local/bin/`
- [ ] `install.sh --check` reports `wave-status` drift status
- [ ] `uninstall.sh` removes `wave-status` from `~/.local/bin/`
- [ ] `dist/` is in `.gitignore`
- [ ] `build.sh` passes shellcheck and shfmt

---

#### Story 4.2: Test Suite

**Wave:** 4
**Dependencies:** Stories 3.2, 1.2 (needs full source package to test against)
**Files:** `tests/conftest.py`, `tests/test_wave_status.py`

Comprehensive tests covering state machine, deferral lifecycle, validation, and dashboard generation. Tests run against the source package via `python -m wave_status` — no zipapp build required for the test suite itself.

**Implementation Steps:**

1. Create `tests/conftest.py`:
   - Fixture: temp directory with `git init` (satisfies git root requirement)
   - Fixture: sample plan JSON (multi-phase, multi-wave, multi-issue)
   - Fixture: sample flight plan JSON (multi-flight)
   - Helper: run `python -m wave_status <subcommand>` as subprocess in temp dir
2. Create `tests/test_wave_status.py`:
   - **State machine tests:**
     - Happy path: init → preflight → planning → flight-plan → flight 1 → flight-done 1 → review → complete → waiting
     - `flight 2` rejected when flight 1 not completed
     - `flight-done 1` rejected when flight 1 not running
     - `complete` advances to next wave
     - `complete` sets `current_wave` to `null` when all waves done
     - Cross-cutting commands work from any state
   - **Deferral tests:**
     - `defer` creates entry with status `pending`
     - `defer-accept` transitions to `accepted`
     - `defer-accept` rejects invalid index
     - `defer-accept` rejects already-accepted deferral
     - `defer` rejects invalid risk level
   - **Validation tests:**
     - `close-issue 999` rejects nonexistent issue
     - `init` rejects invalid JSON / missing fields
     - Commands fail gracefully outside a git repo
   - **Dashboard tests:**
     - Output is valid HTML with inline CSS/JS
     - Contains `data-*` attributes on dynamic elements
     - Contains "Live updates unavailable" fallback text
     - Contains progress rail with phase segments
     - Contains 4 gauge cards (Phase, Wave, Flight, Deferrals)
     - Pending deferrals section present when pending items exist
     - Pending deferrals section absent when no pending items
     - Accepted deferrals section present below grid
   - **Show test:** output contains phase/wave/flight/action/progress/deferral info; no files modified
   - **Stdin tests:** `init -` and `flight-plan -` read from stdin

**Acceptance Criteria:**

- [ ] `tests/conftest.py` and `tests/test_wave_status.py` exist
- [ ] State machine transitions tested (happy path + rejection cases) [R-11, R-12, R-13]
- [ ] Deferral lifecycle tested (pending → accepted, rejection cases) [R-09, R-10, R-15, R-16]
- [ ] All validation rules tested [R-14, R-15, R-16, R-31]
- [ ] Dashboard tests verify progress rail, gauge cards, JS polling, data attributes [R-19, R-24, R-27, R-28, R-29]
- [ ] Dashboard tests verify pending/accepted deferral placement [R-25, R-26]
- [ ] `show` subcommand test verifies read-only behavior [R-06]
- [ ] `pytest tests/` passes with 0 failures
- [ ] Tests use subprocess calls via `python -m wave_status` (not mocking the module under test)

---

## 8. Appendices

### Appendix A: Visual Theme Specification

The dashboard preserves the existing cyberpunk dark theme. Token values and action banner states are documented here for implementation reference.

**CSS Custom Properties:**

| Token | Value | Usage |
|-------|-------|-------|
| `--bg` | `#0a0a0f` | Page background |
| `--surface` | `#12121a` | Card backgrounds (gauge cards, execution grid) |
| `--surface-2` | `#1a1a26` | Nested surfaces, header bars |
| `--border` | `#2a2a3a` | Borders and dividers |
| `--text` | `#e0e0e8` | Primary text |
| `--text-dim` | `#8888a0` | Secondary text, labels |
| `--fuchsia` | `#ff00ff` | Primary accent, active states, in-flight, progress rail phase 1 |
| `--fuchsia-dim` | `#aa00aa` | Gradient starts |
| `--cyan` | `#00ffff` | Phase headers, preflight action, progress rail phase 2 |
| `--green` | `#00ff88` | Completed states, merge action, progress rail phase 3 |
| `--yellow` | `#ffcc00` | Planning action, progress rail phase 4 |
| `--red` | `#ff4444` | Failed states |
| `--orange` | `#ff8800` | Review action, blocked states, pending deferrals |

**Font stack:** `'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace`

**Action banner states:**

| Action | Icon | CSS Class | Border Color | Animation |
|--------|------|-----------|-------------|-----------|
| `pre-flight` | `&#x1F50D;` (magnifying glass) | `action-preflight` | cyan | none |
| `planning` | `&#x1F9E0;` (brain) | `action-planning` | yellow | none |
| `in-flight` | `&#x1F680;` (rocket) | `action-inflight` | fuchsia | glow shadow |
| `merging` | `&#x1F500;` (shuffle) | `action-merging` | green | none |
| `post-wave-review` | `&#x1F50E;` (right magnifier) | `action-review` | orange | none |
| `waiting-on-meatbag` | `&#x1F9B4;` (bone) | `action-meatbag` | fuchsia | throb 2.5s ease-in-out infinite |
| `idle` | `&#x1F4A4;` (zzz) | `action-idle` | default border | none |

**Progress rail phase color cycle:**

| Phase mod 4 | Color | Completed | Remaining |
|-------------|-------|-----------|-----------|
| 1 | `--fuchsia` | `rgba(255, 0, 255, 1.0)` | `rgba(255, 0, 255, 0.2)` |
| 2 | `--cyan` | `rgba(0, 255, 255, 1.0)` | `rgba(0, 255, 255, 0.2)` |
| 3 | `--green` | `rgba(0, 255, 136, 1.0)` | `rgba(0, 255, 136, 0.2)` |
| 4 | `--yellow` | `rgba(255, 204, 0, 1.0)` | `rgba(255, 204, 0, 0.2)` |

### Appendix B: Example Session

A complete wave execution showing all CLI calls in lifecycle order:

```bash
# /prepwaves creates the plan
wave-status init /tmp/wave-plan.json
# -> Status panel initialized for kairos (4 phases, 6 waves, 11 issues)

# /nextwave begins Wave 1
wave-status preflight
wave-status planning
wave-status flight-plan /tmp/wave1-flights.json
wave-status flight 1
# ... sub-agents execute ...
wave-status record-mr 13 "#14"
wave-status close-issue 13
wave-status record-mr 1 "#15"
wave-status close-issue 1
wave-status flight-done 1
wave-status review
wave-status defer "CP-01 human review of pilot contracts" low
wave-status complete
wave-status waiting "Wave 1 complete. Ready for /nextwave."

# /nextwave begins Wave 2
wave-status preflight
wave-status planning
wave-status flight-plan /tmp/wave2-flights.json
wave-status flight 1
wave-status record-mr 2 "#16"
wave-status close-issue 2
wave-status record-mr 3 "#17"
wave-status close-issue 3
wave-status flight-done 1
wave-status flight 2
wave-status record-mr 5 "#19"
wave-status close-issue 5
wave-status record-mr 4 "#18"
wave-status close-issue 4
wave-status flight-done 2
wave-status review

# Discuss deferrals at wave review
wave-status defer-accept 1
# -> Deferral 1 accepted: CP-01 human review of pilot contracts

wave-status complete
wave-status waiting "Wave 2 complete. Ready for /nextwave."

# Check state at any time
wave-status show
# -> Wave Status: kairos
#      Phase:          1/4 (Foundation)
#      Wave:           2/2 in phase 1
#      Flight:         —
#      Action:         waiting-on-meatbag — Wave 2 complete. Ready for /nextwave.
#      Progress:       6/11 issues (55%)
#      Deferrals:      0 pending, 1 accepted
```

### Appendix V: Verification Requirements Traceability Matrix (VRTM)

| Req ID | Requirement (short) | Story | AC / DoD Item | Verification Method | Status |
|--------|-------------------|-------|--------------|-------------------|--------|
| R-01 | Single CLI with subcommands | 3.2 | CLI entry point with 14 subcommands | Inspection | Pending |
| R-02 | `init` creates all files + dashboard | 1.1, 3.1, 3.2 | init creates 4 files | Integration test | Pending |
| R-03 | `init -` reads stdin | 3.2, 4.2 | stdin test | Integration test | Pending |
| R-04 | `flight-plan` stores flights | 1.1, 3.2 | flight-plan stores for current wave | Integration test | Pending |
| R-05 | Lifecycle subcommands update state | 1.1, 3.1, 3.2 | All lifecycle commands update state + dashboard | Integration test | Pending |
| R-06 | `show` prints summary, read-only | 1.1, 3.2, 4.2 | show test verifies read-only | Integration test | Pending |
| R-07 | `close-issue` sets closed | 1.1, 2.3, 3.2 | close-issue test | Integration test | Pending |
| R-08 | `record-mr` records MR | 1.1, 2.3, 3.2 | record-mr test | Integration test | Pending |
| R-09 | `defer` appends pending deferral | 1.2, 3.2, 4.2 | defer test | Integration test | Pending |
| R-10 | `defer-accept` transitions to accepted | 1.2, 3.2, 4.2 | defer-accept test | Integration test | Pending |
| R-11 | Flight N requires N-1 completed | 1.1, 4.2 | flight 2 rejects if flight 1 not completed | Unit test | Pending |
| R-12 | flight-done N requires N running | 1.1, 4.2 | flight-done rejects if not running | Unit test | Pending |
| R-13 | `complete` advances wave | 1.1, 4.2 | complete advances current_wave | Unit test | Pending |
| R-14 | close-issue rejects nonexistent | 1.1, 4.2 | close-issue 999 rejects | Unit test | Pending |
| R-15 | defer rejects bad risk | 1.2, 4.2 | defer "x" critical rejects | Unit test | Pending |
| R-16 | defer-accept rejects invalid | 1.2, 4.2 | defer-accept 999 rejects | Unit test | Pending |
| R-17 | Self-contained dashboard | 3.1, 4.2 | Dashboard output test | Inspection | Pending |
| R-18 | Dashboard layout order | 3.1, 4.2 | Layout order verified | Integration test | Pending |
| R-19 | Progress rail with phase segments | 2.1, 4.2 | Progress rail present in dashboard | Integration test | Pending |
| R-20 | Segment width proportional to issues | 2.1 | Visual inspection | Inspection | Pending |
| R-21 | Full/faded opacity for completion | 2.1 | CSS uses rgba with 1.0/0.2 alpha | Inspection | Pending |
| R-22 | Phase color cycle (mod 4) | 2.1, 4.2 | Progress rail uses 4-color cycle | Inspection | Pending |
| R-23 | Progress rail text w/z (p%) | 2.1, 4.2 | Text present in dashboard | Integration test | Pending |
| R-24 | Four gauge cards | 2.2, 4.2 | Gauge cards present with correct values | Integration test | Pending |
| R-25 | Pending deferrals above execution grid | 2.3, 4.2 | Section present when pending exist | Integration test | Pending |
| R-26 | Accepted deferrals below execution grid | 2.3, 4.2 | Section present below grid | Integration test | Pending |
| R-27 | JS polling every 3s | 1.3, 4.2 | Dashboard contains polling script | Inspection | Pending |
| R-28 | file:// fallback notice | 1.3, 4.2 | Dashboard contains fallback text | Inspection | Pending |
| R-29 | data-* attributes | 2.1, 2.2, 2.3, 4.2 | Dashboard contains data attributes | Inspection | Pending |
| R-30 | Cyberpunk theme preserved | 1.3 | Visual match (Appendix A) | Inspection | Pending |
| R-31 | Error outside git repo | 1.1, 4.2 | Fails gracefully outside git | Unit test | Pending |
| R-32 | Error message format | 1.1, 3.2, 4.2 | All errors match pattern | Unit test | Pending |
| R-33 | Atomic file writes | 1.1, 3.1 | Uses tempfile + os.replace | Inspection | Pending |
| R-34 | Git root discovery | 1.1 | Uses git rev-parse | Inspection | Pending |
| R-35 | Creates .claude/status/ | 1.1 | init creates directory | Integration test | Pending |

---
