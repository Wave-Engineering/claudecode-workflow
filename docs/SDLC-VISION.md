# SDLC Pipeline — Origin Vision

This document captures the founding design vision for the SDLC pipeline system
as discussed during the March-April 2026 design sessions. It records the
considerations, decisions, rejected alternatives, and motivating quotes that
shaped the architecture.

---

## The Problem

Claude Code skills are full markdown documents loaded into the context window
(500+ lines each). Chaining 5+ skills through a pipeline costs thousands of
tokens per invocation. Changes require editing markdown templates and
reinstalling. The pipeline needed to move from "big documents in context" to
"compact tool calls with server-side logic."

But before building the MCP server, we needed to validate the workflow itself.
Skills became the prototype — each skill boundary defines a future tool boundary.

> "Skills are the prototype. We need to validate the workflow before we freeze
> the tool surface."

---

## Core Concepts

### The Pair

Agent + Human working together as one unit. The pipeline doesn't distinguish
between "the human did this" and "the agent did this." Skills, tools, and
pipeline stages address the Pair, not the individual.

### Content-Agnostic Process Engine

The system understands *process* — which stage you're in, what artifacts are
expected, what gate criteria must pass. It never parses the *meaning* of a
domain model or PRD. It's a configurable process advisor and enforcer.

### Process Packs

The process definition is data, not code. A Process Pack is a distributable
directory containing stage definitions, guidance prompts, output templates, and
gate criteria. Packs can be cloned from a git repo for org-wide central
management and versioning.

### Half-Duplex Director

The MCP initiates by telling the Pair what to do next. The Pair goes away, does
the work, comes back and reports completion. The MCP advances state and issues
the next directive.

> "if it was an MCP... we could abstract all the procedural stuff. You make one
> tool call every now-and-then, and everything else just happens. Your context
> stays crisp and clean like a nun's bedsheets."

---

## Key Design Decisions

### 1. State Lives in Git, Not Locally

Pipeline state is committed to the repo in an `.sdlc/` directory, not kept in
local files under `.claude/`. This enables multi-actor collaboration, machine
portability, and gives git log as an audit trail.

> "sounds like we are checking in the states now, instead of keeping them local.
> I think they need to move out of the `.claude` dir and perhaps into something
> like `.sdlc`, which would be extensible later."

**Rejected alternative:** Local `.claude/status/` state files — "Local state is
a single-player design for a multiplayer problem."

### 2. Org-Wide Dashboard via Raw URLs

One static Pages site for the entire org. The dashboard is code (deployed once).
The state is data (committed per-project, read via `raw.githubusercontent.com`
with PAT auth). This decoupling eliminates Pages rebuild latency.

> "I sometimes watch the panel to know when i am needed (or about to be needed),
> so that lag would translate to delay."

The raw URL approach means updates are visible as soon as they're pushed — no
30-90 second Pages rebuild wait.

**Rejected alternative:** Per-project Pages deployment — requires CI changes,
settings, onboarding per project. The org-wide viewer needs zero per-project
setup.

### 3. Zero-Config Onboarding

> "I would like to do this in such a way that projects do not have to change
> settings, make mods to ci pipelines, or do *anything* to get onboarded. I
> know, tall order."

Projects get dashboards by committing `.sdlc/campaign.json`. No CI changes, no
settings, no Pages configuration. The org-wide viewer discovers them.

### 4. Serial Waves as First-Class Pattern

The wave pattern's primary value is lifecycle tracking, not parallelism. A
single-issue sequential wave is a valid topology — you get tracking, status
panels, and audit trails for free.

> "a situation where we have to do every single issue in series is still a
> candidate for the wave pattern. And if we did that, we get tracking for free."

### 5. Source Files Are Not Artifact Files

A hidden assumption that source files must equal artifact files led to monolithic
scripts. Three independent agents flagged the same anti-pattern, validating the
system's ability to detect design smells.

> "We had an *implied* constraint that source files == artifact files. Amazing,
> you and I *both* had the same wrong assumption. What a fucking world, right?"

This led to the three-tier repository taxonomy:
- **Skills** — markdown + co-located helper scripts
- **Packages** — `src/` modules built to standalone executables via zipapp
- **Infrastructure** — CI scripts, installers, configuration

### 6. Skills First, MCP Later

Build the component skills individually, validate the workflow through real
usage, then cast the proven surface as an MCP server. The skill boundaries
define the future tool boundaries.

> "Build the Voltron as separate lions first — once they combine cleanly, cast
> it as a single machine."

### 7. Labels: Priority and Urgency Are Orthogonal

Priority indicates business value. Urgency indicates temporal significance.
Severity is bug-only. Status labels were dropped entirely in favor of native
platform mechanisms.

> "Priority indicates how important it is w.r.t. business value. Urgency
> indicates temporal significance."

**Rejected alternative:** Status labels — "If our prescribed format fucks up
every board across like 100 projects, I am not gonna be a very popular dude."

### 8. Push at Meaningful Moments

State updates push at `flight-done` granularity — not on flight-start
(low-value), not on every issue close (too noisy). The meaningful moments are
`flight-done`, `close-issue`, `complete`, and `defer`.

---

## The Pipeline

Five stages, each with its own skill (now being migrated to MCP tools):

```
Concept Creation (/ddd accept)
  -> PRD Creation (/prd create, finalize, approve)
    -> Backlog Population (/prd upshift, /prepwaves)
      -> Implementation (/nextwave)
        -> DoD Verification (/dod)
```

DDD is one input to the Concept stage, not the only one. External design plans
can be converted to the PRD schema directly.

---

## Captured State: The `.sdlc/` Directory

State is committed to the repo as JSON files under `.sdlc/`. Three files form
the campaign state:

### `campaign.json` — Project Definition

```json
{
  "project": "my-project",
  "stages": ["concept", "prd", "backlog", "implementation", "dod"],
  "created": "2026-04-04T21:00:00Z"
}
```

Immutable after creation. Defines the project name and the ordered stage list.

### `campaign-state.json` — Runtime State

```json
{
  "active_stage": "prd",
  "stages": {
    "concept": "complete",
    "prd": "active",
    "backlog": "not_started",
    "implementation": "not_started",
    "dod": "not_started"
  },
  "last_updated": "2026-04-04T22:15:00Z"
}
```

Mutated by `campaign-status` CLI on every state transition. Each stage moves
through: `not_started` -> `active` -> `review` (for gated stages) -> `complete`.
Writes are atomic (tempfile + `os.replace`) to prevent corruption from
concurrent actors.

### `campaign-items.json` — Deferrals and Work Items

```json
{
  "deferrals": [
    {
      "item": "Performance benchmarking",
      "reason": "Deferred to post-MVP — no production load yet",
      "stage": "implementation",
      "timestamp": "2026-04-05T01:30:00Z"
    }
  ]
}
```

Records items explicitly deferred during the campaign, with rationale and the
stage they were deferred from. This feeds into DoD verification — deferred items
must be acknowledged, not silently forgotten.

### Why JSON in Git

- **Multi-actor:** Multiple Pairs (or CI) can read/write the same state
- **Audit trail:** `git log .sdlc/` shows every state transition with who/when
- **Portability:** No local databases, no external services, no setup
- **Dashboards for free:** Any tool that can read raw file URLs can visualize it

---

## Visual Dashboards

Two dashboard systems exist, both following the same design philosophy: committed
state files as the data source, zero-infrastructure hosting via raw git URLs.

### Wave Status Panel (`.status-panel.html`)

Generated by the `wave-status` CLI during wave execution. A self-contained HTML
file committed to the repo that shows:

- **Progress Rail** — full-width phase-segmented bar with per-phase colors,
  transparency for completion state, global issue count as text overlay
- **Gauge Cards** — wave count, flight count, issues open/closed
- **Execution Grid** — per-wave breakdown with flight assignments and
  issue status

Viewable locally via `file://` (includes meta-refresh fallback for auto-reload)
or via raw git URL. Regenerated on every meaningful state change.

### SDLC Campaign Dashboard (`sdlc-dashboard/index.html`)

An org-wide static viewer deployed once to GitHub/GitLab Pages. 863 lines of
self-contained HTML+CSS+JS with a cyberpunk aesthetic:

- **Monospace terminal font** (Courier New / Fira Code)
- **Dark theme** — deep navy/purple backgrounds (`#0a0a1a`, `#12122a`)
- **Neon accents** — cyan (`#00e5ff`) for headers, magenta (`#ff00ff`) for
  highlights, green (`#39ff14`) for success, red (`#ff1744`) for failures
- **Glow effects** — CSS box-shadow on key elements for the "screen glow" feel

The dashboard fetches `campaign-state.json` via `raw.githubusercontent.com`
(authenticated with a PAT stored in localStorage) and renders:

- **Stage Progress Rail** — horizontal node chain showing each stage's status
  (not started / active / review / complete) with color-coded backgrounds
- **Live/Stale badge** — green "LIVE" with 4-second polling, red pulsing "STALE"
  if fetch fails
- **Per-repo configuration** — owner/repo fields in the header, persisted to
  localStorage

The key architectural insight: **dashboard code is deployed once, state data is
committed per-project.** The viewer never needs redeployment when new projects
start — it just needs the repo coordinates.

> "could pages *point* to the raw file link in the repo? We could move it to
> point to each feature branch as it is created, so still a little lag during
> the initial cutover to a new branch, but once we were on it, it could be
> snappy as fuck."

### Supporting Infrastructure

- **campaign-status CLI** — 7 subcommands (`init`, `stage-start`, `stage-review`,
  `stage-complete`, `defer`, `show`, `dashboard-url`) managing `.sdlc/` state.
  The abstraction layer between skills and state files.
- **wave-status CLI** — wave/flight execution tracking, generates
  `.status-panel.html`. Subcommands include `init`, `extend`, `complete`, and
  `discord-lock` for debounced Discord embed updates.
- **sdlc-dashboard viewer** — the org-wide Pages site described above

---

## Alternatives Considered and Rejected

| Alternative | Why Rejected |
|-------------|-------------|
| Three separate CLI scripts | One script = one install, one file to maintain, no shared-library question |
| Single monolithic Python file | Three independent agents flagged the same anti-pattern |
| Build artifacts in source tree | "The idea that we have artifacts in our source repository feel icky" |
| Per-project Pages deployment | Requires CI changes and onboarding; org-wide viewer needs zero setup |
| HTML regeneration on Pages push | Raw URL fetching eliminates Pages rebuild latency |
| Component/area labels | "3 years from now, every person and every AI has done their own 'thing' to define the area" |
| Building the MCP server first | Skills prototype validates the workflow before freezing the tool surface |

---

## The Voltron Moment

> "When these Cool Cats come together, they make something greater than the sum
> of their parts... an SDLC subsystem. Did you just gasp? I got chills."

The realization that the individual skills — DDD, PRD, prepwaves, nextwave,
DoD — compose into a complete SDLC subsystem. Each skill works standalone, but
together they form something greater.

### Triple Bootstrap

The system was used to build itself. The SDLC pipeline skills were designed,
specified, and implemented using the same wave pattern and tracking tools they
provide.

> "lets add just the phase and no issues under it. When we hit it, we will use
> the skills prototype to concept, design, implement, and test the sdlc
> prototype. NOW we are meta-as-fuck!!!!!"

> "We need to go deeper. Lets fucking incept this thing!"

---

## End-State Vision: mcp-server-sdlc

The skills-based implementation is the proof of concept. The end state is an MCP
server that:

1. Loads a Process Pack (local dir or git clone) to configure the pipeline
2. Guides the Pair through stages via prompt generation
3. Validates gate criteria by scanning the git remote for expected artifacts
4. Tracks campaign state as the single source of truth
5. Serves dashboard data to external viewers
6. Supports wave-pattern execution as a parallel tool namespace

The DDD event storming for this MCP server is captured in `SKETCHBOOK.md`.

---

*Reconstructed from session transcripts: `aaacfa4b` (2026-03-29),
`b3ff9c1e` (2026-03-31), `1d2d50a7` (2026-04-04/05).*
