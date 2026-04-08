# Welcome to Dev Spec Creation

This skill provides an interactive, section-by-section workflow for creating Development Specifications. Instead of generating a Dev Spec in one shot, it walks each section collaboratively — drafting, presenting, and waiting for your feedback before moving on.

The centerpiece is the **Deliverables Manifest** (Section 5.A) — a unified table of everything the project must produce: code artifacts, test outputs, documentation, and verification records. Tier 1 items are required by default (opt-out with rationale), Tier 2 items are added when trigger conditions fire, and Tier 3 items are added only on request.

This skill pairs with `/ddd` and `/prepwaves` in the project pipeline. If you have a DDD domain model from `/ddd accept`, use it as input to `/devspec create` for structured translation. Once the Dev Spec is finalized, feed it into `/prepwaves` to plan execution waves.

## Commands

- **`/devspec create`** — Walk each Dev Spec section interactively, build the Deliverables Manifest, write the Dev Spec
- **`/devspec finalize`** — Run the mechanical finalization checklist against an existing Dev Spec

**Ready to begin?** Run `/devspec create` to start building your Dev Spec.
