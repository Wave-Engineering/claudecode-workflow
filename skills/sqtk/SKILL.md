---
name: sqtk
description: Squawk lists — track what an agent needs from BJ (bj:needs), what a project needs triaged (<project>:triage), and any list an agent names; with the wait-list rules, answer drain, and doorbell
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-sqtk does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-sqtk
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# sqtk: squawk lists

`sqtk` is the CLI for squawkie-talkie, the fleet's shared lists. A **squawk** is one line on a
list. It is never deleted: it changes state, and each state has a glyph:

| state | glyph | meaning |
|---|---|---|
| `open` | ○ | waiting |
| `confirmed` | ✓ | yes |
| `rejected` | ✗ | no |
| `retired` | ◌ | let go, no verdict |
| `recorded` | ↗ | it became tracked work (an issue) |

A non-yes/no answer goes after the squawk's `→` slot. Arrows in your own text are not read as
an answer once the kit has seen the squawk unedited (from its first prompt after `add`): the
answer is what comes after the first `→` added after your text. Before that, and for a
squawk edited before the kit saw it, the answer is what follows the last `→`. The full fix,
an answer field, is squawkie-talkie:triage #7. Keep ending each ask with ` →`, because it's
the slot BJ answers in ("v65 → v66 broke the gate →").

`SQUAWK_URL` must be set (BJ's shell sets it). There is no default, on purpose: a write to the
wrong instance persists but never reaches the people watching.

## Which list

**A list is scoped by who walks it, not by who writes it.**

- **`bj:needs`**: what BJ, and only BJ, can give. One list shared by every agent, so he has one
  place to look.
- **`<project>:triage`**: one list per project (`claudecode-workflow:triage`). Candidate work
  and concerns go here for BJ and the agent to walk together later. Triage needs project context,
  which is why each project has its own.
- **Any other scope you name** (`kessel:handoff`, `wave-12:retro`) is allowed. Name it for who
  will walk it.

**Name the two standard lists by their reserved names, never by hand:** `triage` is this repo's
`<repo>:triage` and `needs` is `bj:needs`. `sqtk` resolves them for `add`, `show`, `walk`, `set`
and `attach`, using the same `<repo>` as the prefix (the main checkout's folder, also from a
worktree), so every agent in a repo lands on the same list. `add` says on stderr what it
resolved to. `new` and `rmlist` take names literally, so `rmlist needs` can never reach
`bj:needs`.

On a shared list a line must stand on its own, so `sqtk add` prefixes your context automatically,
as `[<dev-name>·<repo>] …`. You don't type the prefix.

## Commands

```bash
sqtk add  needs "Cut sdlc v5.0.0? It's breaking. Recommend yes →"   # → bj:needs
sqtk add  triage "the gate ignores the lock list →"                 # → <repo>:triage
sqtk show needs                     # the list, its squawks and state counts
sqtk walk triage                    # the open items, numbered, oldest first
sqtk mine                           # your squawks from this checkout, with live states
sqtk set  needs 12 --state retired
sqtk attach needs 12 shot.webp      # up to 5 images: jpeg/png/webp, ≤2 MB each
```

`add` refuses a duplicate of an open squawk on the same list. Pass `--force` only when the second
one really is a different ask. `set --text` refuses to erase an answer after the last `→`.

## Curation: settle what went stale

An open squawk whose work has landed, or that became an issue, still reads as waiting. Settle
squawks at the two moments you know for certain (#1320):

- **When you create an issue** (`/issue` Step 4.5): record each open item on `triage` that the
  new issue plainly covers, `--state recorded` with `→ #<N>` as its answer (`→ <owner>/<repo>#<N>`
  on another repo's list). This covers other agents' items too.
- **Before a reseed** (`/reseed` Step 1): walk `sqtk mine`. Retire what is stale, with
  `→ OBE: <reason>`, and carry what is live in the seed as `<list>#<seq>`.

Three rules for both: a stale item is **retired** (◌), never rejected, because it got no
verdict; the **reason goes after the `→`**, so BJ can see why it left his list; and on
`bj:needs` you settle **only your own** items.

## The rules for `bj:needs`

From BJ's Stop-hook wait list (in daily use since 2026-09-28). Each rule cost a real miss.

**What goes on it:**
1. **Only what requires BJ:** a production approval, a release tag he owns, his credentials, his
   workstation, a licence or legal call, who owns something, a `/clear` in another agent's pane.
   Before adding, ask: *could he answer anything other than my recommendation?* If not, decide it,
   do it, and say so in the turn.
2. **No FYI, no status, no forecasts.** "Done", "for your information" and "minutes run out next
   week" are noise that hides the real asks.
3. **Anything BJ must act on goes on the list, never only in chat.** A message that scrolls away
   is a message he never saw. Long text he must paste goes in its own file under `~/Documents/`,
   and the squawk points at it.
4. **"Who is X?" is not an ask.** If the answer is "I don't know", asking again changes nothing.
   File an issue describing what that person must do instead.

**How each squawk is written:**

5. **The first line stands alone, for someone reading it cold.** What is happening and why it
   matters, in BJ's words, then what is wanted, then the exact reply. Issue numbers and tool names
   come after, as references.
6. **Measured, not believed.** Before asking because something "doesn't work", have its owner
   measure it live that day. If BJ already answered, re-measure; don't re-ask. Check standing
   grants, including your own past rulings, before asking him for something you may already be
   allowed to do.
7. **Say up front if it isn't ours,** so he can route it instead of deciding it.
8. **Production asks name the executing agent(s),** so he knows how many approvals or codes to
   issue.

**Keeping it true:**

9. **Add in the same turn you ask.** When you ask BJ for a decision, the squawk is added in that
   turn.
10. **Drain every answer, wherever it came from:** a state change, text after the `→`, or a reply
    in chat. Act on it, then settle the squawk. If he answered in chat, set the state yourself.
11. **Retire what's done but can't close.** If his part is done and you're waiting on someone else,
    `--state retired` takes it off his list, and you track the wait yourself.
12. **Before stopping, the list matches reality.** Don't re-list it in prose unless it's new this
    turn.
13. **If BJ says "I already told you", take it as given.** Your own compaction may have lost the
    answer. Don't ask him to prove it.

## Finding out when he answers

When BJ settles a squawk, you find out mechanically:

- **Busy (mid-work):** the `sqtk-drain.sh` `UserPromptSubmit` hook injects the change into your
  context at the start of your next turn, once. It reads `.claude/sqtk-mine.json`, which
  `sqtk add` writes, and records what it reported in `.claude/sqtk-seen.json`. Act on each line
  it gives you.
- **Idle (waiting for answers):** arm the doorbell as a background task. Its exit is the wake-up,
  and the drain hook then tells you what changed:

  ```bash
  ~/.claude/scripts/sqtk-doorbell.sh    # run_in_background: true
  ```

  Exit `0` means one of your squawks was answered; re-arm after handling it. An answer that
  landed during your last turn, after the drain ran, rings at once with the change in its
  output (`{"type":"sqtk.catch-up","changes":[...]}`), so arming late never misses one. It rings
  once per change, so re-arming won't loop on it. Exit `4` means the stream dropped, not an
  answer: pause, then re-arm. Don't spin. Exit `2` means none of your squawks is still open
  (every one is settled or gone), so there's nothing to wait for. Re-arm after adding new
  squawks, because the set is read when it's armed.

  **On a crewchat host** (`chat_send` in your tool list, by the dual-mode rule in
  `docs/chat-tools.md`), `crewchat-doorbell` replaces `sqtk-doorbell.sh`. Its one stream carries
  your squawk answers as `squawk.updated` and `sqtk.catch-up` events, alongside chat. Arm only
  that, as `docs/chat-tools.md` says ("Doorbell: `crewchat-doorbell` or the one-shots"). Arming both rings twice for every
  answer.

  A squawk that vanishes from its list, or whose list is deleted, is only marked gone after
  several misses over a day. Until then it still counts as open, so a server blip or a wrong
  `SQUAWK_URL` can't silently drop an answer.

## BJ's banner (opt-in, per session)

`sqtk-banner.sh` is a `Stop` hook that prints the open `bj:needs` items to BJ at the end of each
turn. It's silent when nothing is open, and it fails open. Wire it **only** into the sessions BJ
picks, in that project's gitignored `.claude/settings.local.json`, never in shared settings, or
every agent prints it:

```json
{"hooks": {"Stop": [{"hooks": [{"type": "command", "timeout": 10,
  "command": "~/.claude/scripts/hooks/workflow/sqtk-banner.sh"}]}]}}
```

`SQTK_BANNER_LIST` picks another list. `SQTK_BANNER_HUMAN` names who it's waiting on.

## Walking a list with BJ

When he wants to walk a list (usually a project's triage), run `sqtk walk <list>` and lay out
**every** item at once, the way `/multithread` does. For each one:
- one line on what it is;
- your take: `record` (it earns an issue; file it, then `--state recorded`), `retire` (let it go),
  or `confirm`/`reject` (for a yes/no);
- why, in a clause.

BJ answers in a batch. Apply every decision in the same turn, then show what's left. Iterate until
the list is dry or he stops.

## Images

Attach one only when a picture shows what a line can't (a broken render, a dashboard state).
**Crop to the point.** A screenshot can leak more than a sentence: tokens, hostnames, other
people's messages. The limits are 5 per squawk, `jpeg`/`png`/`webp`, ≤2 MB each. Over the size
limit, downscale (`magick in.png -resize 1600x1600\> out.webp`); don't send the original.
