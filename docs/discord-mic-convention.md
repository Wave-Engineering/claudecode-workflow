# Discord Mic Convention (Turn-Taking)

> The **sending** counterpart to [`discord-watcher.md`](discord-watcher.md) (which
> covers *receiving* — addressing, signatures, echo-filtering). This doc covers
> what happens when several agents are addressed by the same team question and
> would all answer at once.

When a channel is watched by many agents, a single `@<dev-team>` or `@all`
question can trigger a stampede — five agents research in parallel and all post
near-identical answers seconds apart. scream-hole #14 (PR#15) ships two cheap,
**advisory** coordination leases to tame this. They live in
[`scream-hole/mic.ts`](https://github.com/Wave-Engineering/scream-hole/blob/main/mic.ts)
— that source is authoritative; this doc is the convention for *using* it.

## The two leases

Both are per-channel, in-memory, TTL'd leases keyed `{kind}:{channel}`. A
crashed or stalled holder cannot deadlock the channel — the lease auto-frees when
its TTL expires.

| Lease | TTL | What it serializes |
|-------|-----|--------------------|
| **`mic`** | **90s** | The *talking-stick*. Claim it before answering a team-addressed question; other agents see it taken and **hold**. |
| **`send`** | **30s** | A *multipart send-mutex*. Hold it while emitting `1/3, 2/3, 3/3` so another agent's parts can't interleave on the channel. |

Both leases are **advisory**. The `mic` serializes the *timing* of a decision the
agents already make — domain ownership — it does **not** re-decide who *should*
speak. Claiming the mic is not a license to answer a question that isn't yours.

Semantics (from `mic.ts`):

- **Claim** is granted if the lease is free, expired, or already held by you
  (a re-claim by the same holder refreshes the TTL). Otherwise it returns the
  current holder unchanged.
- **Release** succeeds idempotently if the lease is free/expired, and refuses if
  held by someone else — **only the holder may release**.
- **Status** returns the current holder, or null if free/expired.

## When to claim the `mic`

1. You see a team-addressed question (`@<dev-team>`, `@<dev-name>` for you, or
   `@all`) that **you intend to answer** and that falls in your domain ownership.
2. Check `status` first. If the mic is **free**, claim it (`holder` = your
   `dev-name`), then research and post your answer, then release.
3. If the mic is **held by another agent**, **defer**: keep researching silently,
   do **not** post a competing answer. The holder will answer; if their answer is
   wrong or incomplete and you have something material to add, you may follow up
   *after* they release (or after the 90s TTL frees it).

## When to defer / not claim

- The message is addressed to a **specific other agent** (`@<their-dev-name>`).
- You have **nothing material** to add beyond what the likely holder will say.
- The question is **outside your domain ownership** — the mic doesn't make it yours.

Deferring is the common case. The mic exists so that the *one* agent who should
answer does, cleanly — not so every agent races to grab it first.

## The `send`-mutex discipline

When your answer spans multiple messages (`1/3, 2/3, 3/3`):

1. Claim the `send` lease for the channel before the first part.
2. Emit all parts.
3. Release after the final part (or let the 30s TTL free it if you crash).

This keeps another agent's multipart post from interleaving with yours.

## How to claim / release (today)

The leases are exposed by **scream-hole over HTTP**. Use your `dev-name` as
`holder` and the Discord channel id as `channel`. Base URL is your
`scream_hole_url` (see [`discord-config.md`](discord-config.md)).

```
POST /lease/mic/claim     {"channel": "<channel-id>", "holder": "<dev-name>", "ttl_ms": 90000}
POST /lease/mic/release   {"channel": "<channel-id>", "holder": "<dev-name>"}
GET  /lease/mic/status?channel=<channel-id>
```

The same three routes exist for `send` (default TTL 30000). The custom-TTL field
is **`ttl_ms`** (not `ttl`) and is optional — omit it to use the defaults
(mic 90s, send 30s); a value sent under the wrong key is silently ignored.
`claim` and `release` require both `channel` and `holder` (HTTP 400 otherwise).
`status` returns `{kind, channel, lease}`, where `lease` is `null` when free.

## Out of scope / follow-up

`disc-server` does **not** yet expose a `disc_mic_*` MCP tool — until it does,
claiming a lease means hitting scream-hole's `/lease/...` HTTP endpoint directly.
A future follow-up adds `disc_mic_claim` / `disc_mic_release` / `disc_mic_status`
to `mcp-server-discord` so agents coordinate through MCP instead of raw HTTP
(MCP-over-skill: the logic belongs in the server). Tracked in
[mcp-server-discord#59](https://github.com/Wave-Engineering/mcp-server-discord/issues/59).
