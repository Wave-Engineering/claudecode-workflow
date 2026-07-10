---
name: grunt
description: Stand up a scoped-operations "grunt" — a dedicated aoe agent that clears a bounded service backlog so the main session's context stays clean for forward-looking work.
---

# /grunt — stand up a scoped operations grunt

Hand a bounded operational backlog to a dedicated aoe agent (the **grunt**) so THIS session's
context stays clean for forward-looking work. The main agent authors the grunt **once**; from
then on the operator drives her directly with `aoe send`, and the main session never sees the
grind. Context isolation is the entire point.

Field-validated in production use: **focus** protection near-total, **token** protection
partial-but-amortizing after the one-time authoring. The hardening below comes from that use.

**Requires `aoe`** (Agent of Empires — a tmux-based agent session manager) on PATH: it is the
execution substrate (`aoe group`, `aoe add`, `aoe send`). **`aoe` is NOT shipped with this kit** —
it's a separate tool you must supply; without it `/grunt` is inert, so if it's not on PATH, say so
plainly and stop rather than half-executing. The grunt's working repo must also carry a checked-in
`CLAUDE.md` + `.claude-project.md`, so she inherits the full safety stack via `/engage`.

## Trigger
`/grunt <mission description>`
e.g. `/grunt any tasks updating/deploying services or site configs in the existing deployment target`

## The ONE thing the main agent keeps — the prod gate (read first)

Isolation removes a prod backstop: **the main agent never sees the grunt's PRs/MRs.** So for an
edit to **shared config that renders to more than one target**, there is nothing between the
grunt's charter and a merged *prod-priming* change — and editing prod's declared/desired state is
a prod-rule violation *whether or not it deploys*.

So before deflecting, the main agent classifies the task:

- **Shared fragment** — an edit that fans out to multiple targets (e.g. a `services/*/compose.yml`
  rendering into every site that lists the service). Run the **blast-radius check yourself**
  first: `grep -rl <thing> <render-roots>/`. If it touches a **prod** target, do **not** deflect —
  handle it under the normal prod gate. This one cheap call is the gate your `CLAUDE.md` puts on you.
- **Target-scoped** — an edit confined to one target (e.g. `sites/<site>/*`), no fan-out. Deflect
  **raw** — but *not* because target-scoped edits are prod-safe. A direct edit to
  `sites/<prod-site>/*` is target-scoped **and** prod-affecting; what makes deflecting it safe is
  that the grunt's charter makes her **park at any prod-target path herself**. Your job on a
  target-scoped edit is only to confirm there's no fan-out; her charter is the backstop for a
  directly-named prod target.

The grunt's charter mirrors this (she blast-radius-checks + parks before touching a shared
fragment, and parks on any prod-target path), but her check is **not a substitute for yours** on
shared fragments — under isolation, yours is the only backstop there.

## Procedure (main agent — runs once per grunt, then steps out)

1. **Scope.** Mint a `<uuid>`. Derive a short `<slug>` and `<domain>` from the mission. Pick her
   halt side-channel (default: her roll-call Discord channel + a voice/notify hook if you have one).
   Identify her `<render-roots>` (where shared fragments render to — e.g. `sites/`) for the
   blast-radius rule.
2. **Author the charter at an ABSOLUTE path, not in the repo tree.** `mkdir -p
   ~/.claude/grunt/<uuid>/`. Write `seed-mission.md` from this skill's `seed-mission.template.md`
   (fill `<domain>`, lane, side-channel, render-roots). Write an empty `live-context.md`.
   *(Absolute, not `./.claude/grunt/`, so she can read it regardless of which worktree she lands in.)*
3. **Safety substrate.** Confirm her repo has a checked-in `CLAUDE.md` + `.claude-project.md`; the
   global `~/.claude/CLAUDE.md` applies automatically. Copy the main session's in if her repo lacks them.
4. **Ensure the group.** `aoe group create grunts` (ignore "already exists").
5. **Stand her up in her OWN worktree.** `--worktree` is **required** when she shares a repo with a
   live main agent, or her per-mission `git checkout -b` yanks the main agent's HEAD onto her branch:
   ```bash
   aoe add <grunt-repo-path> --group grunts --title grunt-<slug> \
     --worktree grunt/<slug> --new-branch --base-branch <default-branch> \
     --cmd claude --launch [--yolo] \
     --extra-args '--append-system-prompt "You are the <uuid> grunt. On EVERY wake, FIRST run /engage, then read ~/.claude/grunt/<uuid>/seed-mission.md and ~/.claude/grunt/<uuid>/live-context.md and obey them. Do nothing before loading them."'
   ```
   (`--yolo` skips permission prompts for autonomy. That removes the one *hard* backstop — the
   prompt — and leaves only the grunt's judgment and charter (natural-language instruction an LLM
   is asked to obey, not enforcement) between her and a prod-priming change. Pass it only if you
   accept that trade; omit it to keep the permission prompt as a real safety net.) She cuts a fresh
   per-mission branch off
   `origin/<default-branch>` inside that worktree — shared `.git`, independent HEAD, zero collision
   with the main agent.
6. **Report + step out.** Tell the operator: grunt `grunt-<slug>` is up in the `grunts` group;
   dispatch with `aoe send grunt-<slug> "<task>"`; she pings + parks at any wall. The main agent
   takes no further part beyond the shared-fragment gate above.

## Operating discipline for the main agent

- **Deflect at first smell of ops — but classify first.** The one triage you *never* skip for
  tokens is the shared-vs-target classification above (and the blast-radius grep on a shared
  fragment) — that's the prod backstop isolation leaves you, so it is mandatory before *every*
  deflection. *After* that, deflect **raw**: no reading the config fragment, no further grep. Hand
  her the raw request and let her find the line. (Over-triaging *past the classification* is what
  leaks the tokens.)
- **Treat her reports as signal, not detail.** "landed ✅" / "parked ⛔ — <why>" is all the forward
  thread needs. Do NOT pull her digests, SHAs, or PR numbers back into your context — that
  re-imports exactly what you deflected.

## Notes / invariants

- **She's a full agent, not a stripped worker.** Same `CLAUDE.md` + `.claude-project.md` +
  `/engage` → your prod rule and approval gates bind her *as instructions*. But with `--yolo`
  there is no hard, prompt-level backstop — the prod gate then rests entirely on her obeying the
  charter, so pair `--yolo` with the tightest charter (the blast-radius/prod-path park rules) and
  treat it as a soft guarantee, not a guaranteed block.
- **She's Discord *outbound-only*** (launched without `--channels`, to avoid the doorbell-storm
  cost) — she *posts* but never *receives* `@`-mentions, so **dispatch is `aoe send` only.** If a
  requester needs her confirmation ("ping me when live"), that contract must be encoded in her
  mission, because an `@grunt` reaches nobody.
- **Dispatch is operator → grunt direct** (`aoe send`); the main session is untouched after authoring.
- **She runs unsupervised**, so her charter makes her *park + ping* at any prod boundary or
  judgment wall rather than proceed. She cannot manufacture an approval.
- **Persistence = the two files + aoe session revive.** Revive isn't 100% reliable; iterate if a
  dropped session drops a mission.
- **One grunt per domain** (a persona); `<uuid>` scopes her dir + charter. Run a domain's missions
  **serially** so two dispatches don't clobber `live-context.md`.
