# Plan Issue Template — Operator Reference

**Status:** Reference doc. Authoritative source: [`docs/phase-epic-taxonomy-devspec.md`](./phase-epic-taxonomy-devspec.md) §5.1.

## Overview

The **Plan tracking issue** is the Orchestrator's canonical worldview for a multi-phase Plan. It has two parts, each with distinct mutation semantics:

> **If it changes during a wave pattern, it goes in comments. If it is frozen, it goes in the body (description).**

- **Body** — frozen content: Goal, Scope, Definition of Done, Phase names + DoDs, References. Set during `/devspec create`; frozen at `/devspec approve`. Edited only by the Pair, never by runtime pipeline tooling.
- **Comments** — runtime state: Status fields, Decision Ledger entries, story-merge events, phase transitions, drift halts, gate results, ad-hoc Pair observations. Append-only, platform-enforced.

This doc exists so operators can hand-author or inspect Plan tracking issues without diving into the full Dev Spec. For the underlying rationale (properties this design buys, tradeoffs it accepts), see [§5.1.4–5.1.5 of the Dev Spec](./phase-epic-taxonomy-devspec.md).

Operators reference this doc when:

- Hand-filing a Plan tracking issue (or fixing one filed by `/issue type=plan`).
- Reading an in-flight Plan issue and trying to decode what's body vs. comments.
- Writing tooling that parses Plan comments for typed prefixes.
- Verifying `/issue plan` output against MV-04 (Dev Spec §6.4).

## Body Template

The body shape below is reproduced verbatim from [§5.1.2 of the Dev Spec](./phase-epic-taxonomy-devspec.md). If the two ever disagree, the Dev Spec wins.

```markdown
# Plan: <Name>

<!-- PLAN-ISSUE v1 — frozen content only. Runtime state lives in comments. -->

## Goal
<one sentence describing what this Plan delivers>

## Scope
### In scope
- <bullet>
### Out of scope
- <bullet>

## Plan-level Definition of Done
- [ ] Phase 1 DoD satisfied
- [ ] Phase 2 DoD satisfied
- [ ] (... one line per Phase)
- [ ] Kahuna→main MR merged clean
- [ ] VRTM complete
- [ ] (... cross-cutting conditions)

## Phases

### Phase 1 — <Phase Name>
**DoD:**
- [ ] <verifiable condition> [R-XX]
- [ ] <verifiable condition>

### Phase 2 — <Phase Name>
**DoD:**
- [ ] <verifiable condition>

### (... one section per Phase)

## References
- Dev Spec: `docs/<slug>-devspec.md`
- Memory files: `decision_<topic>.md`, `principle_<topic>.md`
- Related Plans: #NNN (if any)
```

### Body-field semantics

| Field | Location | Why |
|-------|----------|-----|
| Goal | Body | Set during `/devspec create`; frozen at `/devspec approve`. Doesn't change. |
| Scope (In / Out of scope) | Body | Same. |
| Definition of Done (Plan-level) | Body | Same. |
| Phase names + Phase DoDs | Body | The *names* and *criteria* don't change; only the per-story progress does. |
| Reference links (Dev Spec, memory files) | Body | Static pointers. |

The body's DoD checkboxes are **frozen criteria, not runtime progress**. The `[ ]` → `[x]` transitions are made manually by the Pair when closing out a Phase or the whole Plan. The derived "did Phase N complete?" answer lives in comments.

## Comment Typed-Prefix Table

Every comment written by pipeline tooling begins with a **typed prefix** — a square-bracketed tag on the first line that identifies the comment's kind. This enables `gh issue view --comments` output to be grepped for specific kinds, and lets reader tooling parse the log.

| Prefix | When | Who writes |
|--------|------|------------|
| `[ledger D-NNN]` | Design decision locked during `/devspec` walk or runtime decision | `/devspec` skill, `/wavemachine` on drift handling, Pair manually |
| `[status <field>=<value>]` | Any Status field change | `/wavemachine`, `/nextwave`, `/devspec` |
| `[phase-start Phase N]` | First wave of a Phase begins | `/wavemachine` at phase transition |
| `[phase-complete Phase N]` | Last wave of a Phase lands | `/wavemachine` at phase transition |
| `[story-merge Story X.Y #NNN]` | Story's PR/MR merges to kahuna | `/nextwave` after `pr_merge` returns success |
| `[drift-halt]` | Plan-reality drift detected (R-18) | `/wavemachine` when divergence is surfaced |
| `[gate-result <pass\|block>]` | Trust-score gate evaluates | `/wavemachine` at gate step |
| `[plan-complete]` | Kahuna→main merged, Plan closed | `/wavemachine` on clean close |
| `[concern]` | Agent encountered something unsettling but not matching any Legal Exit | `/wavemachine`, `/nextwave`, `/devspec` |

Comments without a typed prefix are **free-form Pair discussion** — scope questions, cross-story clarifications, reviewer notes. Ephemeral operational chatter still goes to Discord (`#wave-status`).

For per-prefix examples and the full rationale (why typed prefixes; properties of this design), see [§5.1.3 of the Dev Spec](./phase-epic-taxonomy-devspec.md).

### Prefix example (Decision Ledger)

```
[ledger D-005] /devspec §3 R-18
**Decision:** Plan-reality drift is the only legitimate halt.
**Rationale:** grimoire's failure modes #1-3 all share the shape "agent paused for non-drift reason."
```

### Prefix example (Story merge)

```
[story-merge Story 1.2 #520] 2026-04-26T21:10Z
Merged to kahuna/499-phase-epic-taxonomy at commit a1b2c3d.
```

### Prefix example (Concern — pressure-valve)

```
[concern] 2026-04-27T15:30Z · /wavemachine wave-3
**Observation:** Story 3.2's test suite flaked twice then passed; unusual for this repo.
**Why it felt halt-worthy:** worried about intermittent failures masking a real bug.
**Why it isn't on the Legal Exits list:** CI ultimately green; no AC failure; no scope divergence.
**Continuing anyway because:** see principle_cost_asymmetry_continue_vs_exit.md
```

## Mutation Rules

Reproduced from [§5.1.6 of the Dev Spec](./phase-epic-taxonomy-devspec.md):

1. **Created by `/issue type=plan`** — populates the body with Goal/Scope/DoD/Phases/References placeholders. Posts NO comments at creation; empty comment log means "Plan created, nothing yet happened."
2. **Body** is hand-edited during `/devspec create` by the Pair; frozen at `/devspec approve`. Post-approval changes require a new `[ledger D-NNN]` comment documenting why.
3. **Runtime state** all flows through comments. Pipeline tooling never mutates the body.
4. **Free-form Pair discussion** uses comments without a typed prefix.

### What this buys (properties of the design)

- **No race condition on mutations.** Two parallel Flights posting `[story-merge ...]`? Two comments get posted; the platform serializes creation. No lost-update, no clobbering.
- **Append-only enforced by the platform.** GitHub/GitLab don't let you "edit the comment list" — only add or delete. Deletion leaves an audit trail.
- **Authorship attribution is free.** Each comment shows who posted it.
- **Notifications are free.** Watchers of the issue are pinged on new comments.
- **Cross-Plan search is free.** `gh search issues --owner Wave-Engineering "[drift-halt]"` finds every Plan that's ever halted on drift. Other prefixes grep analogously.

### What this sacrifices

- **Body is not self-contained.** To understand current Plan state, you need body + comments.
- **At-a-glance status requires scrolling comments.** Mitigation: `scripts/generate-status-panel` HTML snapshot.
- **"Find the latest Status field" requires comment-scanning.** Latest `[status <field>=<value>]` wins.

## Examples

### Canonical in-flight example: cc-workflow#499

The Plan tracking issue for the phase-epic-taxonomy Plan ([cc-workflow#499](https://github.com/Wave-Engineering/claudecode-workflow/issues/499)) is the reference implementation. Fetch it to see the body shape in production:

```
gh issue view 499 -R Wave-Engineering/claudecode-workflow
gh issue view 499 -R Wave-Engineering/claudecode-workflow --comments
```

### Rendered example (abridged)

Body:

```markdown
# Plan: Decouple Phase from Epic in Wave-Pattern Taxonomy

<!-- PLAN-ISSUE v1 — frozen content only. Runtime state lives in comments. -->

## Goal
Decouple Phase from Epic in the wave-pattern pipeline taxonomy. Rename "epic" to "Plan" in all pipeline artifacts, and demote "Epic" to an optional PM-layer concept.

## Scope
### In scope
- Rename pipeline artifacts using "epic" in `/wavemachine`, `/nextwave`, `/prepwaves`, `/devspec`, `/issue` skill bodies; sdlc-server handler signatures; wave-state schema field names.
- Introduce `type::plan` label taxonomy with on-demand creation.
- Introduce optional `epic::N` PM-layer label on stories (pipeline ignores it).
- Plan tracking issue body/comments split: frozen content in body; runtime state in comments via typed prefixes.

### Out of scope
- Not a kahuna behavior change. Branch lifecycle, gate mechanics, trust-score signals — all unchanged.
- Not a mid-flight plan migration. In-flight runs complete under legacy naming.

## Plan-level Definition of Done
- [ ] Phase 1 DoD satisfied
- [ ] Phase 2 DoD satisfied
- [ ] Phase 3 DoD satisfied
- [ ] Kahuna→main MR merged clean on `kahuna/499-phase-epic-taxonomy`
- [ ] Memory files present: `decision_plan_phase_epic_taxonomy.md`, `principle_user_attention_is_the_cost.md`
- [ ] VRTM complete

## Phases

### Phase 1 — Terminology Lockdown
**DoD:**
- [ ] `docs/kahuna-devspec.md` rewritten with Terminology section at top [R-01..R-04]
- [ ] Canonical Plan issue template documented [R-15, D-011]

### Phase 2 — Schema & API Renames
**DoD:**
- [ ] `wave_init` accepts `kahuna: { plan_id, slug }`; legacy `epic_id` accepted with deprecation log [R-05, R-08]

### Phase 3 — Skill Body Rewrites + PM-Layer Bolt-On
**DoD:**
- [ ] `/wavemachine`, `/nextwave`, `/prepwaves` skill bodies: zero unqualified "epic" [R-09, R-10, R-11]

## References
- Dev Spec: `docs/phase-epic-taxonomy-devspec.md`
- Memory files: `decision_plan_phase_epic_taxonomy.md`, `principle_user_attention_is_the_cost.md`
```

Comments (excerpt, chronological):

```
[ledger D-001] /devspec §3 R-18
**Decision:** The Plan issue body is frozen at /devspec approve.
**Rationale:** Eliminates lost-update races between concurrent Flights.

[status wavemachine_state=active] 2026-04-26T20:12Z
Starting wavemachine autopilot. Kahuna: kahuna/499-phase-epic-taxonomy.

[phase-start Phase 1 — Terminology Lockdown] 2026-04-26T20:15Z
Stories: #508, #509, #510.

[story-merge Story 1.2 #509] 2026-04-26T21:10Z
Merged to kahuna/499-phase-epic-taxonomy at commit a1b2c3d.

[phase-complete Phase 1 — Terminology Lockdown] 2026-04-26T22:45Z
3/3 stories merged. Phase DoD satisfied.
```

## See also

- [`docs/phase-epic-taxonomy-devspec.md`](./phase-epic-taxonomy-devspec.md) §5.1 — authoritative body/comments design
- [`docs/phase-epic-taxonomy-devspec.md`](./phase-epic-taxonomy-devspec.md) §5.2 — Decision Ledger entry schema
- [`docs/phase-epic-taxonomy-devspec.md`](./phase-epic-taxonomy-devspec.md) §5.3 — Exhaustive Legal Exits pattern
- [`docs/phase-epic-taxonomy-devspec.md`](./phase-epic-taxonomy-devspec.md) §5.5 — `/issue type=plan` skill integration
- `principle_user_attention_is_the_cost.md` — why the Concerns Channel (`[concern]`) exists
- `pattern_plan_issue_body_comments_split.md` — the memory-file version of this rule
- `pattern_concerns_channel.md` — pressure-valve detail
