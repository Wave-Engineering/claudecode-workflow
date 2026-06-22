---
name: assesswaves
description: Quick assessment of whether a piece of work is suitable for wave-pattern execution (parallel or serial). Lighter than /prepwaves — helps decide decomposition before (or after) issues are created.
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-assesswaves does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-assesswaves
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# AssessWaves — Is This Work Wave-Patternable?

Decide whether a set of work items can benefit from wave-pattern execution. Recommends a topology and verdict; does not create issues or flight plans. Use before `/prepwaves`.

## Axioms

Bound by WAVE_AXIOMS 1, 7, and 10 (`WAVE_AXIOMS.md` at the repo root). **Axiom 1** (serial is a valid topology) and **Axiom 7** (the assessment-skill binding) govern the topology verdict; **Axiom 10** (a wave targets exactly one repo) bounds the recommendation — never recommend a single wave that spans repos; cross-repo work is serial single-repo phases (expand-contract).

## Tools Used

- `mcp__sdlc-server__spec_validate_structure` — check each issue's spec shape
- `mcp__sdlc-server__spec_dependencies` — extract declared edges
- `mcp__sdlc-server__wave_topology` — classify graph as parallel / serial / mixed

## Procedure

1. **Gather items.** Issue numbers given: call `spec_validate_structure(N)` then `spec_dependencies(N)` for each. No args: ask the user or derive from conversation.
2. **File impact.** Launch one Explore sub-agent per item in parallel to identify files touched. Keeps main context clean.
3. **Topology.** Call `wave_topology(...)` on the issue set; otherwise reason manually.
4. **Verdict card.** Present table (work items / wave-able / topology / suggested waves / risk), conflict matrix, wave sketch, risk flags, recommendation (parallel / serial / mixed / restructure / not wave-able).

**Key insight:** serial is a valid wave topology. The wave pattern provides lifecycle tracking and audit trail regardless of parallelism. "Logically sequential" determines topology, not suitability.

**Not this skill:** no issue creation (`/issue`), no flight plans (`/prepwaves`), no execution (`/nextwave`).
