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
  - the **scope/condition/expiry** as the user framed it, so a "while I'm away" grant
    isn't applied as permanent (`feedback_approval_requires_intent`).

  Elaborate enough to apply without re-deriving; terse enough to stay signal. (The reader
  is a *fresh* window, not a starved one — optimize for signal-density, not minimalism.)

**Do NOT carry** (it is noise that re-bloats the window):

- Anything that auto-reloads at session start — CLAUDE.md, the MEMORY.md index,
  SessionStart hooks. Trust them; don't restate them.
- Anything already on disk — point at the path instead.

Open the seed with a one-line revival instruction and an ordered "read these
first" list so the revived agent rehydrates deterministically.

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
- A seed that duplicates a design doc or a memory file has failed its purpose:
  it re-creates the bloat the reduction was meant to remove.
