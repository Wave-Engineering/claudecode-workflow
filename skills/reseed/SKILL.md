---
name: reseed
description: Context-window reduction via seed-and-clear — author a durable seed (point at state, carry volatile decisions), then clear and revive. For a cheap summarize, use /compact directly.
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-reseed does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-reseed
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Reseed: Seed-and-Clear Context Reduction

The window is filling up and work is mid-flight, and invoking `/reseed` *is* the
choice to take the **careful** path: author a detailed seed → `/clear` → revive
from it. There is no decision step — in ~50 real uses, seed-and-clear won **100%**
of the time, and deliberating a foregone conclusion would only burn the dying
window this skill exists to protect. **For a cheap summarize where little is at
stake, don't run this — just `/compact` directly.**

The load-bearing idea: **a good seed points at durable artifacts and carries
only volatile working-state.** It mirrors CLAUDE.md's own compact-instructions
("if it's on disk, reference the path"). Anything already on disk — or
auto-reloaded at session start — does not belong in the seed.

## Step 1 — Author the seed

Write the seed following the kernel. **Carry:**

- **Pointers to the durable artifacts that ARE the state** — design docs,
  memory file names, issue numbers, key `file:line` ranges. Reference them;
  **never duplicate** their contents.
- **Volatile working-state** — current branch, uncommitted/modified files, the
  **immediate next action** (be explicit about intent), and open threads.
- **Communication / relationship nuance not re-derivable** — e.g. "user is on a
  phone, expect typos, confirm side-effectful actions," tone, who decides what.
- **Gotchas not to relearn the hard way** — sharp edges, things that already
  bit this session.
- **Conversation-only operating-decisions** — the things said this session that change
  *how you operate* or *what you prioritize* and have **no durable home**: grants/waivers
  ("auto-approve prechecks", standing `/scpmmr`, "don't ask", "I'll handle X"), and the
  priority stack you agreed (focus, ordering, what to do vs defer vs skip). The seed's
  instinct is "point at durable state" — so it systematically drops these, because the
  conversation that holds them is the very thing being dropped; there is nothing to point
  at. Carry each as **decision + why + scope**:
  - the **decision** outright, so the revived agent never *re-derives* it — re-deriving
    from a hint is where a fresh agent mis-scopes a grant or re-litigates a priority;
  - the **why**, so it can *adapt* when the situation deviates instead of blind-following;
  - the **scope/condition/expiry** as the user framed it **AND whether that condition still
    holds right now** — a "while I'm away" grant when the user is *back* must be carried *with*
    its scope **and flagged likely-lapsed**, never as a permanent grant
    (`feedback_approval_requires_intent`). Flattening a scoped grant to an unconditional one is
    the single most common fidelity failure — for every grant, state its live status, not just
    its original scope.

  Elaborate enough to apply without re-deriving; terse enough to stay signal. (The reader
  is a *fresh* window, not a starved one — optimize for signal-density, not minimalism.)

- **Ownership / role assignments** — who owns, reviews, or is blocked on what; lane splits
  and review-reversals agreed this session. A fresh agent that loses these re-collides with
  teammates.
- **Error→fix pairs and open threads** — what bit and how it was resolved, and what's still
  in-flight, so the revived agent neither re-hits the wall nor re-opens settled ground.

**Accuracy over completeness:** state issue/MR/PR open-vs-closed status, commit tips, and
"done/merged" claims **only as the conversation actually established them** — never overclaim
closure or progress. A confidently-wrong status ("#73 is closed") is worse than an honest
"open/unsure": it sends the revived agent down a path that no longer exists.

**Do NOT carry** (it is noise that re-bloats the window):

- Anything that auto-reloads at session start — CLAUDE.md, the MEMORY.md index,
  SessionStart hooks. Trust them; don't restate them.
- Anything already on disk — point at the path instead.

Open the seed with a one-line revival instruction and an ordered "read these
first" list so the revived agent rehydrates deterministically.

**Final re-scan before you hand off.** Re-read your draft seed against the conversation
once more and (a) add any operating decision, open thread, or ownership assignment you
dropped, and (b) verify every grant carries its *live status*, not just its original scope.
This single pass is where the recall the first draft missed gets recovered — a state-focused
seed under-captures on the first pass by construction, so the re-scan is not optional polish.

## Step 2 — Write to the right path (durability caveat)

**`/tmp` is reboot-wiped** (`lesson_tmp_identity_boot_wipe`). That is fine for a
same-session readback, but a seed lost to a reboot leaves no revival path.

- **Same-session reduction** (the normal case) → `/tmp/<topic>-reseed.md` is fine
  (name it for the work, e.g. `/tmp/workflows-migration-reseed.md`).
- **Reduction might span a reboot** (long pause, end-of-day, anything where the
  machine could cycle before revival) → write to a **durable path under
  `.claude/`**, not `/tmp`.

Surface this choice to the human; default to `/tmp` unless a reboot is plausible.

## Step 3 — Hand off

State the next human action unambiguously — the human is about to drop your
context, so a missed instruction can't be re-asked:

> "Seed written to `<path>`. Run `/clear`, then paste: `Read <path> and revive`."

(Once the `SessionStart{clear}` auto-revive hook ships, this collapses further to
"armed — just `/clear`," with the seed injected on revival. Until then, the paste
is the deterministic path.)

## Important

- **Point at disk; carry only volatile state** — the whole skill in one line.
- **Carry the conversation-only decisions** — grants, priorities, and rulings that
  change how you operate and have no durable home; they're the thing a state-focused
  seed silently drops (see Step 1).
- **Live status, not just scope** — every grant must say whether its condition still
  holds *now*; a scoped grant flattened to unconditional is the top fidelity failure.
  State issue/MR status only as the conversation established it, and re-scan once for
  dropped decisions before handing off. (Bench-validated: these lift recall+fidelity
  from ~0.87 to ~0.95 — `reference_reseed_improvement_techniques`.)
- A seed that duplicates a design doc or a memory file has failed its purpose:
  it re-creates the bloat the reduction was meant to remove.
