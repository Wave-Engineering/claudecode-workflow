---
name: reseed
description: Guided context-window reduction — reason about compact vs seed+clear vs seed+compact, recommend one, then author the seed and give the human the exact follow-up
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-reseed does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-reseed
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Reseed: Guided Context-Window Reduction

The context window is filling up and work is mid-flight. This skill runs the
decision — **`/compact`** vs. **seed + `/clear`** vs. **seed + `/compact`** —
recommends one with reasoning tied to the *current* state, and (for the seed
options) authors the seed and hands the human the exact follow-up.

The load-bearing idea: **a good seed points at durable artifacts and carries
only volatile working-state.** It mirrors CLAUDE.md's own compact-instructions
("if it's on disk, reference the path"). Anything already on disk — or
auto-reloaded at session start — does not belong in the seed.

## Step 1 — Assess current state (do this before recommending)

Reason about three things; they decide which option wins:

1. **How full is the window?** Higher pressure favors the tighter options
   (2 over 1; a lean seed over a fat one).
2. **What is the in-flight work?** Shallow / nearly-done → `/compact` alone is
   fine. Deep, multi-thread, easy-to-misremember → protect it with a seed.
3. **How much state is already externalized to disk?** Design docs, memory
   files, issues, committed code. The more that lives on disk, the *less* the
   seed has to carry — which makes seed + `/clear` both safest and tightest.

## Step 2 — Present the 3 options and recommend one

Show all three; **recommend one with reasoning** — don't just ask.

> Given the current context window, what we're doing, and what's left, there
> are 3 ways to shrink the window:
> 1. **`/compact`** — the summarizer compresses the transcript. No seed.
> 2. **Seed + `/clear`** — I write an extremely detailed seed to a file that
>    gets me back to full understanding with a much tighter window; you run
>    `/clear`, then revive me from the seed.
> 3. **Seed + `/compact`** — I write a seed with everything critical and
>    nothing else; you run `/compact`; then I read the seed back to patch any
>    holes the compaction created.

**Recommendation heuristic:**

| Situation | Recommend | Why |
|---|---|---|
| Heavy state already on disk (docs / memories / issues / committed code) | **Option 2** (seed + `/clear`) | Safest *and* tightest — the seed only carries volatile working-state; everything durable is pointed at, not duplicated. `/clear` gives the cleanest window. |
| Little externalized; lots of valuable in-conversation reasoning | **Option 3** (seed + `/compact`) | The seed's redundancy earns its keep — `/compact` keeps a lossy trace, the seed readback patches what it dropped. |
| Work is shallow / nearly done / window not precious | **Option 1** (`/compact`) | Cheapest. But know the cost: it **cedes control of the volatile state to the summarizer** — only acceptable when little is at stake. |

## Step 3 — (Options 2 & 3) Author the seed

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

**Do NOT carry** (it is noise that re-bloats the window):

- Anything that auto-reloads at session start — CLAUDE.md, the MEMORY.md index,
  SessionStart hooks. Trust them; don't restate them.
- Anything already on disk — point at the path instead.

Open the seed with a one-line revival instruction and an ordered "read these
first" list so the revived agent rehydrates deterministically.

## Step 4 — Write to the right path (durability caveat)

**`/tmp` is reboot-wiped** (`lesson_tmp_identity_boot_wipe`). That is fine for a
same-session readback, but a seed lost to a reboot leaves no revival path.

- **Same-session reduction** (the normal case) → `/tmp/<topic>-reseed.md` is fine
  (name it for the work, e.g. `/tmp/workflows-migration-reseed.md`).
- **Reduction might span a reboot** (long pause, end-of-day, anything where the
  machine could cycle before revival) → write to a **durable path under
  `.claude/`**, not `/tmp`.

Surface this choice to the human; default to `/tmp` unless a reboot is plausible.

## Step 5 — Give the exact human follow-up

State the next human action unambiguously — the human is about to drop your
context, so a missed instruction can't be re-asked.

- **Option 1** → "Run `/compact`." (No seed.)
- **Option 2** → "Seed written to `<path>`. Run `/clear`, then paste:
  `Read <path> and revive`."
- **Option 3** → "Seed written to `<path>`. Run `/compact`. When you're back,
  I'll read `<path>` to patch any holes."

## Important

- **Recommend, don't just ask** — the value is the reasoning, not the menu.
- **Point at disk; carry only volatile state** — the whole skill in one line.
- A seed that duplicates a design doc or a memory file has failed its purpose:
  it re-creates the bloat the reduction was meant to remove.
