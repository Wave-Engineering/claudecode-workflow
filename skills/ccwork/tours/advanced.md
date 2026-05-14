# Tour: Advanced Pipeline

A guided walkthrough of the full SDLC pipeline — from domain discovery through autonomous wave execution. This tour covers the "concept to merged code" chain: `/ddd` → `/devspec` → `/prepwaves` → `/nextwave` → `/wavemachine`.

**Pace:** Each section covers one pipeline stage. Explain what it does, show how to check whether it has been run in the current project, and clarify when you would vs. wouldn't use it. Do NOT execute the skills — these are destructive (they create issues, plans, files). Show, don't run.

**Cross-references:**
- [Concepts: Advanced Skills](../../../docs/concepts.md#advanced-skills) for the architectural picture
- [KAHUNA Guide](../../../docs/kahuna-guide.md) for the integration-branch pattern
- [Skill Reference: Advanced Skills](../../../docs/skill-reference.md#advanced-skills----domain-driven-design) for full syntax

---

## Section 1: The Pipeline at a Glance

Narration: "The advanced pipeline takes you from a vague idea to merged, tested code — with every decision tracked. Each stage produces an artifact that feeds the next. You can enter at any point (not everything needs event storming), but the full chain looks like this:"

```
  /ddd begin       →  SKETCHBOOK.md (raw domain events)
  /ddd draft       →  DOMAIN-MODEL.md (formalized model)
  /ddd accept      →  handoff to /devspec
  /devspec create  →  <project>-devspec.md (8-section spec)
  /devspec approve →  approval metadata stamped
  /devspec upshift →  Story issues + phases-waves.json
  /prepwaves       →  wave plan validated and persisted
  /nextwave        →  one wave executed (flights merge)
  /wavemachine     →  autopilot loop across all waves
```

Narration: "Think of it as a compiler: domain knowledge is source code, the pipeline compiles it into executable work items, and the wave pattern is the runtime. Most projects skip the first three steps and enter at `/devspec create` with an existing concept doc or verbal description."

---

## Section 2: `/ddd` — Domain Discovery

Narration: "Domain-Driven Design via event storming. This is the optional first stage — use it when you're starting from scratch and need to *discover* what the system should do, rather than translating known requirements."

### What it produces

| Command | Output |
|---------|--------|
| `/ddd begin` | `docs/SKETCHBOOK.md` — raw event storm (8 stages) |
| `/ddd draft` | `docs/DOMAIN-MODEL.md` — formalized domain model |
| `/ddd accept` | Verification pass → hands off to `/devspec create` |

### Check if DDD has been run

```bash
ls docs/SKETCHBOOK.md docs/DOMAIN-MODEL.md 2>/dev/null || echo "(no DDD artifacts in this project)"
```

### When to use it

- Greenfield project where the domain is unclear
- Translating business requirements from stakeholders
- When you want structured domain vocabulary before writing specs

### When to skip it

- You already have a concept doc or PRD
- The work is a well-understood feature addition
- You're implementing from an existing design

Narration: "DDD is Socratic — the agent asks probing questions, challenges assumptions, and builds the model collaboratively. It's the highest-touch stage. If you already know what to build, jump to `/devspec create` and feed it your concept doc."

---

## Section 3: `/devspec` — Specification

Narration: "The Dev Spec is the contract between the Pair and the execution pipeline. It captures architecture, stories, phasing, and acceptance criteria — everything a spec-driven agent needs to implement without making design decisions."

### What it produces

| Command | Output |
|---------|--------|
| `/devspec create` | `docs/<project>-devspec.md` (8 sections, interactive) |
| `/devspec finalize` | Finalization checklist (7 mechanical checks) |
| `/devspec approve` | Approval metadata stamped in Dev Spec |
| `/devspec upshift` | Story issues + `phases-waves.json` |

### Check if a Dev Spec exists

```bash
ls docs/*-devspec.md 2>/dev/null || echo "(no Dev Spec in this project)"
```

### Check for phases-waves.json (upshift output)

```bash
cat .claude/status/phases-waves.json 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'Plan: #{d.get(\"plan_id\", \"?\")}')
phases = d.get('phases', [])
for p in phases:
    waves = p.get('waves', [])
    stories = sum(len(w.get('stories', [])) for w in waves)
    print(f'  Phase {p.get(\"phase\", \"?\")}: {len(waves)} waves, {stories} stories')
" 2>/dev/null || echo "(no phases-waves.json — /devspec upshift has not been run)"
```

### The interactive flow

Narration: "Unlike a one-shot generator, `/devspec create` walks each section collaboratively — it drafts, presents, gets your feedback, iterates, then moves on. After each section the Pair approves, it posts a Decision Ledger entry to the Plan tracking issue. The Deliverables Manifest (Section 5.A) is particularly important — it's the single source of truth for all project outputs, and it's opt-OUT: you must explicitly N/A items you skip."

### Key concept: Plan → Phase → Wave → Story

```
Plan (tracking issue, type::plan)
  └── Phase (sequential ordering, internal to phases-waves.json)
        └── Wave (batch of stories, executed together)
              └── Story (single implementable issue)
```

Narration: "This taxonomy was locked in April 2026 after a major rework. Plan is the top container, Phase orders execution, Wave batches stories by dependency, Story is the atomic work unit. Epic is only a PM-layer label — the pipeline never reads it."

---

## Section 4: `/prepwaves` — Validation and Planning

Narration: "Once you have stories in issues and a `phases-waves.json`, `/prepwaves` validates that everything is actually ready for execution. It's the pre-flight checklist before the wave pattern starts merging code."

### What it does

1. Reads the Plan tracking issue and enumerates its sub-issues
2. Validates each sub-issue spec in parallel (Changes / Tests / AC sections present?)
3. Computes a topological sort from declared dependencies
4. Presents a pre-flight report: ready items, not-ready items, wave assignments
5. Persists the validated plan so `/nextwave` can pick it up

### Check pre-flight state

```bash
wave-status show 2>/dev/null | head -20 || echo "(wave-status not initialized)"
```

### When it blocks

Narration: "If a sub-issue is missing its Changes, Tests, or Acceptance Criteria section, `/prepwaves` flags it as NOT READY and refuses to include it in the wave plan. Fix the issue spec, then re-run. This gate exists because Flight Agents executing stories are spec-driven — they cannot make design decisions, only implement what the spec says."

---

## Section 5: `/nextwave` — Single Wave Execution

Narration: "This is where code gets written. `/nextwave` picks up the next pending wave from the plan and executes it — spawning Flight Agents that each implement one Story on an isolated branch."

### Three agent roles

| Role | What it does | Where it runs |
|------|-------------|---------------|
| **Orchestrator** | Drives the loop, spawns Flights in parallel | Top-level session (has `Agent` tool) |
| **Prime** | Pre-wave planning, post-flight merge/CI/reconcile | Sub-agent (sequential, one per wave) |
| **Flight** | Implements one Story, runs precheck, reports PASS/FAIL | Sub-agent (parallel, one per issue) |

### Execution modes

- **Parallel** — multiple Flight Agents on isolated worktrees (conflict detection via `flight_overlap`)
- **Serial** — single-issue flights, fast-path (no worktree isolation)
- **Mixed** — some waves parallel, some serial

### The filesystem bus

```bash
ls /tmp/wavemachine/ 2>/dev/null && echo "(active wave data above)" || echo "(no active waves)"
```

Narration: "Agents communicate via files under `/tmp/wavemachine/<repo>/wave-<N>/`, not through Orchestrator context. This keeps the context window clean and provides a forensic audit trail. Each flight writes `results.md` and a `DONE` file (contents: PASS or FAIL)."

### One wave per invocation

Narration: "`/nextwave` executes exactly one wave and returns. The user controls the pace. For automated multi-wave execution, use `/wavemachine`."

---

## Section 6: `/wavemachine` — Autopilot

Narration: "The fire-and-forget mode. `/wavemachine` is `make all` for the wave pattern: it loops `/nextwave` across every pending wave until the plan is exhausted or something breaks."

### What makes it safe

- **Health check** (`wave_health_check`) before every iteration — circuit breaker for stuck states
- **KAHUNA sandbox** — flights merge to an integration branch (`kahuna/<wave-id>`), not directly to `main`
- **Trust score gate** — commutativity, CI, code-reviewer, trivy must all pass before kahuna→main
- **Legal exits** — closed enumeration of halt conditions (WAVE_AXIOMS.md)

### Check KAHUNA state

```bash
git branch -r --list 'origin/kahuna/*' 2>/dev/null | head -5 || echo "(no kahuna branches)"
```

### The loop (simplified)

```
while wave_next_pending() is not null:
    wave_health_check() — break if unhealthy
    /nextwave auto     — execute one wave
    check result       — break if FAIL
done
wave_finalize()        — compute trust score, merge kahuna→main
```

Narration: "The human's contract with `/wavemachine` is: approve at the start (by invoking it after `/prepwaves`), approve at the end (the trust-score gate). The middle is autonomous. If something breaks, it stops and reports — it never silently continues past a failure."

---

## Section 7: Putting It Together

Narration: "Here's how a typical project flows through the pipeline, from first idea to merged code:"

```
Day 1:  /ddd begin          → explore the domain with the Pair
        /ddd draft          → formalize into DOMAIN-MODEL.md
        /ddd accept         → hand off to devspec

Day 2:  /devspec create     → 8 interactive sections, Decision Ledger on Plan issue
        /devspec finalize   → mechanical completeness check
        /devspec approve    → human stamps approval
        /devspec upshift    → create Story issues + phases-waves.json

Day 3:  /prepwaves #N       → validate specs, compute waves, persist plan
        /wavemachine        → autopilot: flights execute, merge, reconcile
                            → trust gate: kahuna→main
```

Narration: "In practice, most runs start at Day 2 or even Day 3 — you enter wherever you have enough clarity. The pipeline is a funnel, not a mandatory gauntlet. But every stage that runs adds traceability: from domain event → spec section → story → flight → merged commit."

---

## What's Next

- **Try the workflow tour** — `/ccwork tour workflow` for the basic issue-to-merge loop
- **Read the KAHUNA guide** — `docs/kahuna-guide.md` for integration-branch detail
- **See the axioms** — `WAVE_AXIOMS.md` for the binding rules of autonomous execution
- **Back to overview** — `/ccwork tour` for the full orientation
