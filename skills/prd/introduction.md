# Welcome to PRD Creation

This skill provides an interactive, section-by-section workflow for creating Product Requirements Documents. Instead of generating a PRD in one shot, it walks each section collaboratively — drafting, presenting, and waiting for your feedback before moving on.

The centerpiece is the **Deliverables Manifest** (Section 5.A) — a unified table of everything the project must produce: code artifacts, test outputs, documentation, and verification records. Tier 1 items are required by default (opt-out with rationale), Tier 2 items are added when trigger conditions fire, and Tier 3 items are added only on request.

This skill pairs with `/ddd` and `/prepwaves` in the project pipeline. If you have a DDD domain model from `/ddd accept`, use it as input to `/prd create` for structured translation. Once the PRD is finalized, feed it into `/prepwaves` to plan execution waves.

## Commands

- **`/prd create`** — Walk each PRD section interactively, build the Deliverables Manifest, write the PRD
- **`/prd finalize`** — Run the mechanical finalization checklist against an existing PRD

**Ready to begin?** Run `/prd create` to start building your PRD.
