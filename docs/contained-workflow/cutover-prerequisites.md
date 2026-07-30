# Cut-over prerequisites — why these, in this order

Companion to [`architecture.md`](architecture.md) and the Dev Spec. That pair
describes **what** the contained workflow is. This describes **why the
prerequisites to cutting the fleet over are the ones we picked**, and what we
deliberately chose not to fix first.

It exists because the cut-over is big-bang — stop every agent, bring them back
one at a time — and the first container replaces the agent that derived this
reasoning. A plan that lives only in a session transcript does not survive its
own canary.

Derived 2026-07-30. Tracking issues: #1061 (secrets), #1062 (drop Slack),
#1063 (image cadence), #1064 (session durability),
`mcp-server-wtf`#29 (`.wtf/` relocation).

---

## 1. The failure class that connects all of them

Every prerequisite here traces to one pattern: **a component that fails in a way
indistinguishable from having nothing to report.**

A watcher with a revoked token does not exit — it polls forever and delivers
nothing. An agent with unresolved identity fails *closed* and delivers nothing.
A dependency scanner that parses zero manifests reports a clean run. In all
three, "no output" is both the healthy state and the broken state.

That is tolerable at fleet-of-one-box scale because a human notices the silence.
It is **not** tolerable during a staged cut-over, where every agent is expected
to be quiet while it waits its turn. The signal we would rely on to detect a
broken container is the same signal a correctly-idle container produces.

So the bar for a cut-over prerequisite is not "is this bug severe." It is:
**would this failure be visible during the cut-over, or would it look like
progress?**

## 2. What containerisation structurally changes

One container per session means `$HOME` goes from *shared by ~12 agents* to
*private per agent*. Every known defect should be filtered through that before
being called a prerequisite — several fix themselves, and at least one silently
gets worse.

| Behaviour | Today (shared `$HOME`) | After cut-over | Verdict |
|---|---|---|---|
| `~/.claude/discord-forward.json` | One rule, every watcher obeys it | Per agent | **Fixed for free** |
| `~/.claude/discord-bot.auth-failed` | One 401 deafens the whole fleet | Per agent | **Fixed for free** |
| `~/.claude/discord-bot.kill` | Operator brake stops every watcher | Stops **one** container | **Silently degraded** |
| Kit / skills (Cellar) | Edit once, every agent picks it up | Baked per image | **Changed workflow** |
| Session transcripts | Survive on the host | Destroyed with the container | **Broken** — #1064 |
| Secrets | Whole `~/.secrets` readable by all | Named files only, per container | **Fixed by #1061** |

Two rows deserve emphasis because they cut in opposite directions.

**The kill switch descopes with no error.** `touch ~/.claude/discord-bot.kill` is
today a fleet-wide emergency brake (`discord-watcher` `index.ts:256`). After
cut-over the same command pauses exactly one container and reports success. If
anyone reaches for it during an incident they will believe the fleet is stopped
when it is not. This is not a bug to fix so much as a **behaviour change to
document loudly** in the ops runbook.

**Kit distribution inverts.** A skill fix is currently a file copy into the
shared Cellar. Afterwards it is an image rebuild plus an agent restart. That
makes cc-workflow#937 (deliver rule changes to *live* sessions via hooks)
materially more important than its priority suggests: it becomes the only
channel that reaches a running agent between releases.

## 3. `Monitor` is gated, not missing

Recorded here because it cost a full session to establish and the surface
symptom is misleading.

`Monitor.isEnabled()` resolves the server-side feature flag
`tengu_amber_sentinel`, which **defaults to false**. Both local override paths
are compiled out of the shipped bundle — the settings override returns
unconditionally, and the `CLAUDE_INTERNAL_FC_OVERRIDES` read sits after an
unconditional `return`, making it unreachable. The flag can only arrive from the
feature service, and that lookup **short-circuits to false before consulting the
cache** when any of the following hold:

- the provider is not first-party (Bedrock, Vertex / Google Cloud Agent
  Platform, Microsoft Foundry) — overridden by `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`
- gateway auth is in use
- `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`, `DISABLE_TELEMETRY`, or
  `DO_NOT_TRACK` is set
- `DISABLE_GROWTHBOOK` is set

Read out of CLI 2.1.220 on 2026-07-30. Minified identifiers are regenerated per
build, so match on behaviour, not symbol names.

Two consequences for the cut-over. An **Anthropic-authenticated** container with
telemetry disabled still has no `Monitor` — the auth path is not the whole
story. And `--channels` is *correlated but separately gated* (it is
admin-enabled on Team/Enterprise plans), so the two must be diagnosed
independently rather than inferred from one another.

Full operator-facing detail: `skills/disc/SKILL.md`, "Arming the channels-free
doorbell".

## 4. Verify the instruments before trusting them

Three guards were found inert on a single day, each of which would have reported
success while checking nothing:

- **R-14 (fail loud on a missing required secret)** — specified, implemented in `validate_secrets()`, and **inert**: it reads a `required.manifest` that does
  not exist, so the required list is empty and the validation loop never runs.
  It would have waved the #1061 secrets mismatch straight through.
- **The dependency gate** — `trivy` parses **zero** manifests in this repo, and
  a pass over an empty denominator is indistinguishable from a clean scan. Filed
  five separate times (#922, #941, #944, #1053, #1056) over eleven days by five
  agents; never fixed, only re-discovered.
- **A regression assertion** — the doorbell test's `grep -q 'exit 4'` was
  satisfied by an incidental parenthetical elsewhere in the file, not by the
  exit-code contract it intended to protect.

The shared lesson, and the rule this doc asks future work to follow:
**an instrument that has only ever run against a passing case has not been
tested.** Plant a failure, confirm the guard fires, then remove it. This applies
with particular force to the cut-over, because the container bootstrap's guards
are what stand between a misconfiguration and a fleet of silently deaf agents.

Note also the five-way duplicate filing. That pattern gets *worse* with more
agents, not better — more capacity means faster re-discovery of the same
untouched defect, not faster repair.

## 5. The prerequisites, and the one real dependency

| # | Prerequisite | Why it gates the cut-over |
|---|---|---|
| #1061 | Secrets: `.secrets` canonical, named single-file mounts, `.env` carries pointers | Hard blocker. Consumers read `~/secrets`; the mount is `~/.secrets`. Container #1 boots with no Discord at all. |
| #1062 | Drop Slack | `slackbot-send` is the one non-MCP secret consumer, and unused. Removing it keeps #1061 to a single pointer mechanism with no exception. |
| #1064 | Session durability | Transcripts are unmounted; any container replacement destroys the session. |
| #1063 | Image cadence | Not a correctness gate — a throughput one. ~17.5 min per merge, multiplied fleet-wide. |

**What actually shipped, and why it changed mid-implementation.** The design
reviewed here started as "put the token in the environment," with per-MCP-server
`env` as the mitigation for inheritance. Implementation killed that: scoping a
token to an MCP server requires the **literal value inside `mcp.json`**, which is
a worse artifact than the secret file it replaced. Both consumers turned out to
already accept a token *path* env var (`DISCORD_TOKEN_PATH` for the watcher,
`DISCORD_TOKEN_FILE` for disc-server), so `.env` carries **pointers, never
values** and the credential never enters the environment at all.

That keeps the single-input property, removes the inheritance exposure entirely
— nothing for a stray `env` dump to capture into a host-durable transcript
(#1064) — and leaves rotation working without a restart, with one sharp caveat.

**The caveat, because it is a silent failure.** A Docker file bind binds the
**inode**. An in-place rewrite (`printf > file`) is seen by the container; an
atomic replace (`mv`, `sops`, most editors' save) is **not**, permanently and
without any error, until the container is recreated. Rotate in place, or plan on
a restart. This does not undo the #1064 dependency so much as narrow it: #1064
is what makes the restart cheap when a rotation is done the other way.

## 6. Deliberately deferred

- **`parseForwardArgs` accepts any token.** `discord-watcher forward …` (a
  literal ellipsis) wrote a healthy-looking rule that silently misrouted every
  addressed doorbell on the box for ~11 hours. Real, and *not* a prerequisite:
  the fleet-wide blast radius comes from the shared `$HOME`, which the cut-over
  removes. Big-bang means no mixed-mode window in which it stays fleet-global.
  Fix it after.
- **Per-secret scoping across the IP boundary.** The whole-dir mount put every
  Analogic and OaW credential in every container. #1061 closes this incidentally
  by mounting a single `.env`, so no scoping engine is needed today. Revisit if
  the set of container-required secrets ever grows beyond a handful.
- **Mattermost + chat-backend abstraction.** Post-cut-over. Two constraints
  worth carrying forward: abstract at the **MCP-server layer**, not in skill
  prose (servers enforce, skills suggest); and derive backend selection from the
  existing forge rule (GitLab/Analogic → Mattermost, GitHub/OaW → Discord), so
  the abstraction *enforces* the IP boundary rather than merely enabling a
  second chat system.

## 7. Still unverified

Recorded as open questions rather than assumptions:

- **Is the session project directory already bind-mounted by aoe?** If it is,
  `<repo>/.claude/` survives container replacement for free and #1064 only needs
  a transcripts fragment. The `[sandbox]` config carries `volume_ignores` /
  `volume_ignores_strategy = "anonymous"`, and masking subpaths only makes sense
  over a bind-mount — but aoe is a compiled binary and this was inferred from
  config shape, not read from its mount code. One container launch and a
  `mount | grep <repo>` settles it.
- **Where the image build's ~17.5 minutes actually goes** — pull, build, sign,
  SBOM, or push. #1063 removes most builds rather than optimising them, so this
  is only worth measuring if the remaining release-time builds are painful.
- **The `Monitor` gate chain has been read statically, not exercised.** No one
  has flipped `DISABLE_TELEMETRY` and watched the tool disappear. The static
  read is unambiguous; the behavioural confirmation is a five-minute test on a
  throwaway session.
