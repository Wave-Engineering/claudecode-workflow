---
name: reseed
description: Context-window reduction via seed-and-clear — author a durable seed (point at state, carry volatile decisions), then clear and revive. `/reseed revive` continues from the seed. For a cheap summarize, use /compact directly.
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-reseed does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-reseed
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Reseed: Seed-and-Clear Context Reduction

## `/reseed revive` — continue from the seed

**If invoked as `/reseed revive`, do only this section.** It is what the automatic kick
types after `/clear`, and what BJ types by hand from a cold start — the same command either
way.

1. Read `<project_root>/.claude/reseed-revive.md`. If it does not exist, say so plainly and
   stop — there is nothing to revive from.
2. Print its age, its recorded branch and HEAD against the current `git branch --show-current`
   and `git rev-parse --short HEAD`. A mismatch is information, not a reason to refuse: say
   it, then carry on.
3. Run `/engage`, then continue the work the seed names as its immediate next action.

No freshness gate here: an explicit `/reseed revive` is the intent.

## `/reseed` — seed and clear

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

**First, curate your squawks (#1320).** You can judge which of them are stale only now, while
you still hold the context; the revived agent would be guessing from the seed. Run
`sqtk mine`, and for each item still open (○), do one of two things:

- **Stale:** it landed, was decided, was superseded, or is no longer true. Retire it, with the
  reason as its answer:

  ```bash
  sqtk set <list> <seq> --state retired --text "<the item's text> → OBE: <reason, with the PR or issue>"
  ```

  If the text already ends with `→`, write the reason after that arrow instead of adding a
  second. Retired (◌), never rejected: a stale item got no verdict.
- **Still live:** carry it in the seed's open threads as `<list>#<seq>`, with one line on what
  it is waiting for.

Only your own squawks: `sqtk mine` lists exactly those. On `bj:needs` never touch another
agent's item. Skip this silently when `SQUAWK_URL` is unset or nothing is recorded.

Then write the seed following the kernel. **Carry:**

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

(The `## Kiosk` section below is the one exception: it is written for outsiders, not for the
revived agent, so it restates in public terms what the rest of the seed points at.)

**Always write a `## Kiosk` section, last in the seed (#1336).** On a host running the
crewchat daemon, the MCP shim extracts **only** this section and seeds your kiosk from it.
The kiosk answers people outside your crew while social is off, and they read its answers
(mattermost-crew R-32). It never sees the rest of the seed. Write it as if posting it in a
public channel:

- **Put in:** who you are and what you work on, at a level you'd share with anyone; the kinds
  of question you can field; how to reach your human partner.
- **Never put in:** anything else from this seed (grants, open threads, branch or file state,
  private repo paths), secrets or credentials, client or partner names, unreleased plans,
  and anything you'd squawk rather than post.
- **No `## ` heading inside it.** The next `## ` heading ends the section (`### ` is fine, and
  so is a `## ` inside a code fence). Putting it last means nothing after it can be swallowed.
- **Empty is allowed.** If nothing is outsider-safe, write the heading with no body, and the
  kiosk answers "I have nothing to share yet." A missing heading gets the same answer, but
  write it anyway, so the choice is visible.

Open the seed with a one-line revival instruction and an ordered "read these
first" list so the revived agent rehydrates deterministically.

**Final re-scan before you hand off.** Re-read your draft seed against the conversation
once more and (a) add any operating decision, open thread, or ownership assignment you
dropped, and (b) verify every grant carries its *live status*, not just its original scope.
This single pass is where the recall the first draft missed gets recovered — a state-focused
seed under-captures on the first pass by construction, so the re-scan is not optional polish.

## Step 2 — Write seed and arm the auto-revive hook

The seed has **one path**, always: `<project_root>/.claude/reseed-revive.md`, overwritten on
every reseed. One path is what makes `/reseed revive` possible without anyone knowing a
filename — free-form names left 14 seeds under two conventions in one repo, and BJ hunting
for the right one by hand.

First make sure the seed can never be committed. `info/exclude` is per-clone and untracked,
so this adds no diff in any repo — and a seed carries session detail that, in a GitLab repo,
is the partner's:

```bash
git check-ignore -q .claude/reseed-revive.md ||
  printf '%s\n' '**/.claude/reseed-revive.md' >>"$(git rev-parse --git-path info/exclude)"
```

(The `**/` matters: an exclude entry with a slash in it is anchored to the repo root, so a
session rooted in a subdirectory would never match it — the seed would stay committable
and every reseed would append another dead entry.)

Write the seed with the `Write` tool (never a heredoc — a seed is full of backticks). Its
first lines record where it was cut, so `/reseed revive` can show drift:

```
Branch: <git branch --show-current>   HEAD: <git rev-parse --short HEAD>   Written: <UTC timestamp>
```

Then print what the kiosk will see, and re-read it as an outsider would:

```bash
crewchat-kiosk-brief.sh
```

It runs crewchat's own extractor, so what it prints is exactly what the kiosk gets. On a host
without crewchat it says there is nothing to check. If it shows anything from the rest of the
seed, or anything private, fix the section and run it again before you go on. The check is a
backstop, not a gate: the shim pushes the section whenever the seed file changes, so a bad
one may already be live until your fix is written. Get it right in the draft.

Then arm the hook so the next `/clear` auto-revives without any user action:

```bash
jq -n --arg a "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg p "${TMUX_PANE:-}" \
  '{armed_at: $a, tmux_pane: $p}' >"$(pwd)/.claude/reseed-armed.json"
```

## Step 3 — Trigger the clear

With the hook armed, trigger `/clear` immediately via tmux — do not ask the user to do it:

```bash
~/.claude/scripts/pane-send.sh "${TMUX_PANE}" "/clear"
```

It clears the input line first, so a half-typed draft in the pane is discarded rather
than submitted with `/clear` appended.

Then end your turn with a brief note:

> "Seed written and armed. Clearing now — I'll auto-revive and continue."

The `SessionStart{clear}` hook (`reseed-revive.sh`) fires on the fresh session, points it at
the seed, and launches `reseed-kick.sh`, which types `/reseed revive` into the pane until
the session acknowledges it. Either signal counts: the `reseed-ack.sh` prompt hook removes
a nonce when `/reseed revive` is submitted, or the session's transcript shows the agent's own
tool call on the seed. So a revive through the Skill tool, or inside a turn that a peer
message or task notification started, needs no prompt. While the session is busy with a turn,
the kicker does not type, because a send would only queue behind the turn. When the session is
idle and still hasn't revived, it sends once. If no acknowledgement arrives, it pages BJ via vox
and `#call-4-bj` (`notify-bj.sh`: `crewchat-send` first, Discord as the fallback), naming the pane. Outcomes are logged to
`~/.claude/logs/reseed-kick.log`.

**If tmux is not available** (`$TMUX_PANE` empty): fall back to the manual flow:

> "Seed written. Run `/clear`, then `/reseed revive`."

**The automatic trigger.** A Stop hook (`context-reseed-gate.sh`) acts when remaining context
is at or below the threshold: `RESEED_CONTEXT_THRESHOLD_PCT` if it's a number, else `100 - ` nerf's
`ouch` dart, else 15. What it does depends on the session's nerf mode (`/nerf mode`):

| nerf mode | at the threshold |
|---|---|
| `ultraviolence` (default) | blocks the turn: run this skill now, before anything else |
| `hurt-me-plenty` | blocks the turn: tell the user, and ask whether to reseed now or after the current step; don't reseed without the answer |
| `not-too-rough` | no block: one reminder per session that `/reseed` is advised |

A session with no nerf config, or one the hook can't read, gets `ultraviolence`. Autocompact
stays the backstop under every mode. The reading comes from the
statusline, so headless (`claude -p`) sessions never have one and the gate never fires
there. It reports a missing reading only after three turns without one, which most
headless runs never reach, so there it is usually silent.

## Important

- **Point at disk; carry only volatile state** — the whole skill in one line.
- **End every seed with `## Kiosk`**, written for outsiders: the only part of the seed a
  crewchat kiosk sees. Check it with `crewchat-kiosk-brief.sh`.
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
