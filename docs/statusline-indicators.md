# Statusline Layout and Per-Session Indicators

The statusline is two rows of panels, divided by a dim `│` (#1426, #1427). Any skill or script can publish indicators to the first panel to communicate state at a glance.

```
Row 1: <panel icons> │ <Model-Effort> │ <nerf> │ <runway> │ <context> │ <floor> │ <Session> │ <Weekly> │ <spend>
Row 2: <dev-name> <avatar> │ <project>-<branch> (<worktree>) │ <cwd>
```

A panel with nothing to show is not rendered, and neither is its divider, on either row.

## Panels

| Panel | Source | Rendering |
|---|---|---|
| Panel icons | the asks file (see [Ask indicators](#ask-indicators-1430)), then the per-session indicators file (below), then the wavemachine marker | asks first, then the indicators, in yellow, unchanged |
| Model-Effort | `model.display_name`, `effort.level` | `Sonnet 5.5-medium`; the `-effort` part is left out when the payload has none |
| Nerf | `${NERF_CONFIG_DIR:-/tmp}/nerf-<session_id>.json` (`mode`, `darts_pct`) and the context size | the next dart not yet reached, with its emoji, its name and a five-cell bar: `🪶 soft ▰▰▰▱▱`. See [Nerf, runway and floor](#nerf-runway-and-floor-1428) |
| Runway | the shared helper | tokens left until the nearer of reseed and autocompact: `↻ 88K auto` or `🗜 62K` |
| Context | `context_window.total_input_tokens` | the absolute size: `999`, `1K`, `38K` (for 37,542), `312K`, `1M`, `1.2M`. No bar and no percent sign. Coloured by nerf's darts when nerf has a config for the session, else green, yellow at 25% remaining, red at 13% |
| Floor | `~/.claude/state/context/<key>.floor.json` | `floor 91K ▼`: the context size right after the last sharp drop, with an arrow against the previous floor |
| Session | `rate_limits.five_hour.used_percentage` | `Session:12%`, only when the payload has it |
| Weekly | `rate_limits.seven_day.used_percentage` | `Weekly:92%`, only when the payload has it |
| Spend | `cost.total_cost_usd` of every session, less the `statusline-spend begin` baselines | `$12.34`: API or Bedrock spend since the begin marker, only when the payload has **no** `rate_limits`. See [Spend](#spend-1429) |
| dev-name avatar | `.claude/agent-identity.json` | as before |
| project-branch (worktree) | git | the project is the main repo's folder (taken from the git common directory, so a linked worktree shows its project, not its own folder); `-<branch>`, or the short commit when the head is detached; ` (<worktree-dir>)` only in a linked worktree. The existing `✓`/`✗` (clean or dirty), `+N` staged and `↑N`/`↓N` marks follow it |
| cwd | the payload | with `$HOME` shortened to `~` |

Session and Weekly turn yellow from 50% and red from 80%.

**One `jq` pass reads the whole payload** on each render, and git lookups are cached for a few seconds per cwd (`CLAUDE_STATUSLINE_GIT_TTL`, default 5; 0 turns the cache off). The remaining-context reading the reseed gate and nerf depend on (`~/.claude/state/context/<session>.json`, #1225) is written exactly as before.

## Nerf, runway and floor (#1428)

All three work from the context size and, for nerf and runway, the shared window math below. They need the model's `context_window_size` in the payload to place anything; without it nerf and runway are not rendered.

**Nerf.** Reads nerf's per-session config. The darts are percentages of the *usable* window (the gate's frame), so with a 1M model and no autocompact window (967,000 usable) darts of 51/63/85 sit at 493,170 / 609,210 / 821,950 tokens. The panel names the next dart the size has not reached: `soft`, then `hard`, then `ouch`; at or past `ouch` it stays on `ouch` with a full bar. The bar is five cells of progress from the previous dart (from 0 for `soft`) to the next one. The colour follows the zones the context panel uses: green below soft, yellow to hard, orange to ouch, red from ouch. No nerf config for the session, or one without all three darts: no panel.

The emoji comes from a set per dart, picked by a stable hash (`cksum` of `<session_id>:<dart>`) so it does not change between renders: soft `🪶 🧸 🍬 🫧 🧁`, hard `🔨 🪨 🧱 🥊 🏏`, and the `ouch` dart (before and after it is reached) `🔥 💀 🧨 🦂 🌋 👹`. All are single code points with no variation selector.

**Runway.** The tokens left until the nearer of the reseed trigger and the autocompact trigger, tagged with which: `↻ 88K auto` when reseed is nearer, `🗜 62K` when autocompact is. The reseed tag is nerf's mode: `auto` (ultraviolence), `ask` (hurt-me-plenty), `nudge` (not-too-rough); an unreadable or missing mode counts as ultraviolence, as the gate treats it. At or past the trigger the number reads `0K` and the panel turns red. The reseed trigger is the first size at which the gate acts: where the integer remaining percent (floored, as the gate compares it) falls to the threshold, which is `100 - ouch` with nerf, else 15, or `RESEED_CONTEXT_THRESHOLD_PCT`. That is up to 1% of the usable window sooner than the ouch dart's own position (`usable * ouch / 100`), and a test runs the real gate at the token before and at the trigger to hold them together. The gate measures it against the same usable window autocompact fires from (#1297), so reseed comes first at any real window size, even with the threshold at 0. `🗜` appears only when the two coincide (a usable window of a few tokens); the branch exists so the panel names autocompact if a future window or threshold ever puts it first.

**Floor.** State is `~/.claude/state/context/<key>.floor.json`, where `<key>` is the dev-name (the session id when there is no identity): `{"floors": [{"size", "ts"}, ...], "last": {"<session id>": <size at that session's previous render>, ...}}`. A drop of at least 30% **and** at least 20,000 tokens against the same session's previous render records the new size as a floor; a session's first render records one too. The previous size is per session, so two sessions of one dev-name rendering alternately do not thrash the shared floors. The last five floors are kept, a size of 0 (Claude Code before its first response) records nothing, and the file is rewritten only when something that matters changed (a floor, a new session, a size 1K or more from `last`, or the session no longer being the most recently rendered of the eight, so a session at a steady size is not evicted by newer ones). The panel shows the latest as `floor 91K`, with ▲ when it is above the previous floor, ▼ below it, `=` within 2K (nothing with a single floor). Writes are atomic and best-effort: a failed one never costs the render, and the panel is still worked out from what is in memory.

## Spend (#1429)

The spend panel shows what an API or Bedrock session has cost since a moment you choose. A subscription session reports a notional cost that means nothing, so the panel appears only when the payload has **no** `rate_limits` and has a cost; it is the last panel on row 1.

**State**, in `~/.claude/state/spend/` (override: `CLAUDE_SPEND_STATE_DIR`):

| File | Content | Written by |
|---|---|---|
| `<session_id>.json` | `{"cost_usd": <number>, "ts": <epoch>}`: that session's latest cost | the statusline, on a render whose cost differs from the file's |
| `begin.json` | `{"ts": <epoch>, "baselines": {"<session_id>": <cost>, ...}}` | `statusline-spend begin` |

The panel is the sum, over every session file, of that session's cost less its baseline (floored at 0); a session with no baseline, such as one first seen after the marker, counts in full. With no marker the sum is everything recorded. It is printed with two decimals, `$12.34`.

**Rules.** The session id is used as a file name only if it matches `^[A-Za-z0-9_-]+$` and is not `begin` (the marker's name); anything else writes nothing (its cost still counts in the sum that render shows, under a placeholder key). Only a session with no `rate_limits` is recorded, so a subscription's notional cost never lands in the sum an API session shows. A cost of 0 shows and records nothing: a fresh session reports 0, and so does a subscriber's first render, before `rate_limits` arrives, so showing it would flash `$0.00` on a session that is not API-billed. Writes are atomic (a temp file, then a move) and best-effort: a failed one never costs the render, and the panel still includes this session's own cost. Session files older than 30 days are pruned whenever one is written; `begin.json` is never pruned. A corrupt state file is skipped, not fatal.

**`statusline-spend`** (installed on `PATH` by `./install --scripts`, like the other scripts):

```
statusline-spend begin   spend marker set: 2 sessions, since 2026-11-02 03:41 EST
statusline-spend show    spend since 2026-11-02 03:41 EST: $12.34 across 3 sessions
                         spend (no begin marker; all recorded sessions): $12.34 across 3 sessions
statusline-spend         (no or an unknown argument) usage on stderr, exit 2
```

`begin` snapshots every existing session file's current cost as its baseline and records the time; running it again replaces the marker and the sum restarts at `$0.00`. The times are local, with the zone abbreviation. The arithmetic is `scripts/lib/spend-math.sh`'s, shared by the panel and the CLI so they cannot disagree.

## Shared window math

The reseed gate and the statusline's nerf, runway and floor panels do their context arithmetic in one place, `scripts/lib/context-math.sh`, so they cannot disagree. `context_math <reading.json> <nerf.json> [<settings.json>]` prints `key=value` lines: nerf's mode and darts, the reseed threshold, the autocompact window, the usable window (the smaller of the model window and the autocompact window, less the ~33k buffer), the remaining percent of it, the darts as token positions, and the runway to the nearer of reseed and autocompact. It writes nothing. See the header of that file for every key.

## How It Works

The statusline script polls a JSON file on each render cycle (~300ms). The file is keyed by `dev_name`, so each session's indicators are naturally scoped and don't collide.

**File:** `/tmp/claude-statusline-<dev_name>.json`

**Schema:**
```json
{
  "indicators": ["● REC", "W2 3/5"]
}
```

Indicators are joined with spaces. Keep each one short (aim for 8 characters or fewer).

## Resolving dev_name

The identity file lives at `<project_root>/.claude/agent-identity.json` (reboot-durable). Fall back to the legacy `/tmp/claude-agent-<md5>.json` if absent (transition window).

**`<project_root>` is where the session was launched, not where the agent is now (#1446).** The statusline reads it from the payload's `workspace.project_dir` ("Project root directory path"), which does not move when the agent changes directory. The payload's `cwd` does move, and resolving from it made the dev-name, the ask indicators and the floor change whenever the agent left the project root. It tries `project_dir` first, then `cwd` for an older payload or a session launched below its project, then the `/tmp` fallback. A hook or script that writes indicators should do the same, with `CLAUDE_PROJECT_DIR` (set in a hook's environment) in place of `pwd`:

```bash
project_root="${CLAUDE_PROJECT_DIR:-$(pwd)}"
agent_file="${project_root}/.claude/agent-identity.json"
if [ ! -f "$agent_file" ]; then
    dir_hash=$(echo -n "$project_root" | md5sum | cut -d' ' -f1)
    agent_file="/tmp/claude-agent-${dir_hash}.json"
fi
dev_name=$(jq -r '.dev_name // empty' "$agent_file" 2>/dev/null)
```

## Writing Indicators

**Always write atomically** (temp file + rename) to avoid the statusline reading a half-written file:

```bash
dev_name=$(jq -r '.dev_name // empty' "$agent_file" 2>/dev/null)
tmp=$(mktemp)
echo '{"indicators": ["● REC", "W2 3/5"]}' > "$tmp"
mv "$tmp" "/tmp/claude-statusline-${dev_name}.json"
```

### Python

```python
import json, os, tempfile, hashlib

def set_indicators(indicators: list[str]):
    # The project root is where the session was launched: not os.getcwd() after the agent has
    # changed directory, and not the git toplevel, which differs from it in a worktree (#1446).
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    agent_file = os.path.join(root, ".claude", "agent-identity.json")
    if not os.path.exists(agent_file):
        dir_hash = hashlib.md5(root.encode()).hexdigest()
        agent_file = f"/tmp/claude-agent-{dir_hash}.json"
    with open(agent_file) as f:
        dev_name = json.load(f).get("dev_name", "")
    if not dev_name:
        return
    path = f"/tmp/claude-statusline-{dev_name}.json"
    fd, tmp = tempfile.mkstemp()
    with os.fdopen(fd, "w") as f:
        json.dump({"indicators": indicators}, f)
    os.rename(tmp, path)
```

## Clearing Indicators

Write an empty array or delete the file:

```bash
tmp=$(mktemp)
echo '{"indicators": []}' > "$tmp" && mv "$tmp" "/tmp/claude-statusline-${dev_name}.json"
# or
rm -f "/tmp/claude-statusline-${dev_name}.json"
```

## Examples

| Use Case | Indicator | Meaning |
|----------|-----------|---------|
| Wave progress | `W2 3/5` | Wave 2, issue 3 of 5 |
| Recording | `● REC` | Session is being recorded/replayed |
| Nerf soft dart | `⚡ 55%` | Past the soft dart (percent of window used) |
| Nerf hard dart | `🔶 70%` | Past the hard dart: reseed soon |
| Nerf ouch dart | `🚨 88%` | Past the ouch dart: the reseed gate fires (what it does depends on the nerf mode) |
| Nerf unknown | `ctx ?` | No usable context reading (missing, stale, or from before a compaction); `nerf_status` says why. The statusline asks nerf to repaint once a fresh reading lands |
| Timer | `⏱ 12m` | Time remaining on a task |
| Build status | `✓ BUILD` | Last build passed |
| Blocked | `⛔ KILL` | Kill switch engaged |

## Ask indicators (#1430)

When an agent has an open ask on the shared `bj:needs` squawk list, the statusline lights an icon for it, by kind and by whether it blocks. It costs no model tokens: a hook rebuilds a small cache from the squawk text, and the statusline only reads the cache.

### The contract (shared with squawkie-talkie#163; change both or neither)

An open `bj:needs` item's text starts with an ask marker: a kind icon, then `❗` exactly when the item is blocking and not a blocker, then a space.

| icon | kind |
|---|---|
| ❓ | question |
| 🔧 | action |
| ✅ | approval |
| ⛔ | blocker (always blocking, no `❗`) |
| 🔔 | unspecified |

An item whose text starts with none of these (an older client's, say) counts as 🔔, non-blocking, and so does one that only has an icon later in the line. The icons are single code points with no variation selector. `sqtk add needs "<text>" --kind approval --blocking` writes the marker; the parser is `ask_split` in `scripts/hooks/workflow/sqtk-answer.jq`, shared by the sync hook and the drain and banner hooks (the answer rules strip the marker first, so reclassifying an ask is never read as an answer).

### The asks file

`/tmp/claude-statusline-<dev_name>.asks.json`, keyed by `dev_name` like the indicators file, and a different file from it:

```json
{"asks": [{"list": "bj:needs", "seq": 12, "kind": "approval", "blocking": true}], "synced_at": 1793000000}
```

It is a cache. The squawk text is the source of truth, so a lost or stale file is rebuilt by the next sync. `scripts/hooks/workflow/sqtk-asks-sync.sh` writes it, atomically.

### What the sync does

It reads this checkout's squawks from `.claude/sqtk-mine.json`, keeps those on `bj:needs`, fetches the list once with `sqtk show bj:needs --json` (the CLI handles the URL and auth), keeps the ones still open, parses each marker, and writes the file.

- A failed fetch (no `SQUAWK_URL`, a dead server, a bad body) leaves the file exactly as it is.
- No open `bj:needs` items removes the file.
- No `.claude/agent-identity.json` does nothing.
- It prints nothing, never blocks, and always exits 0.

### When it runs

| Trigger | Registered in | Runs the sync |
|---|---|---|
| `PostToolUse` on `Bash` | `config/settings.template.json`, its own group | only when the command contains `sqtk add` or `sqtk set` (read from the hook's stdin); any other command exits at once |
| `UserPromptSubmit` | `sqtk-drain.sh` calls it as it ends | at every prompt, whatever the drain did |
| `Stop` | `config/settings.template.json`, its own group | only when the asks file already exists, so a session with no asks pays nothing |

### How it renders

The panel is the first thing on line 1. Asks are grouped and each group shows `<icon>[❗][count]` (the count only above one): blockers first, then blocking asks, then non-blocking ones; inside a tier, approval, action, question, then unspecified. For example `⛔2 ✅❗ ❓3` is two blockers, one blocking approval and three non-blocking questions. A missing, empty or malformed file renders nothing.

## Design Notes

- **Rendezvous key is `dev_name`**, not session_id or PID. The statusline subprocess is detached from the TTY and has no access to session-specific env vars, but it can always resolve `dev_name` through the project-root-hashed identity file.
- **Atomic writes matter** because the statusline polls at ~300ms and `jq` will error on partial JSON.
- **Multiple skills sharing indicators** — the file holds a single flat array. If more than one skill needs to publish indicators simultaneously, each must read-modify-write: read the existing array, update its own entries, and write the full array back. A plain overwrite will replace indicators set by other skills.
- **Ownership** — the session that wrote the file owns it. Since `dev_name` is unique per session, there's no cross-session conflict.
