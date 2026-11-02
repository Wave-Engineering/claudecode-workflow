# Statusline Layout and Per-Session Indicators

The statusline is two rows of panels, divided by a dim `│` (#1426, #1427). Any skill or script can publish indicators to the first panel to communicate state at a glance.

```
Row 1: <panel icons> │ <Model-Effort> │ <nerf> │ <runway> │ <context> │ <floor> │ <Session> │ <Weekly> │ <spend>
Row 2: <dev-name> <avatar> │ <project>-<branch> (<worktree>) │ <cwd>
```

A panel with nothing to show is not rendered, and neither is its divider, on either row. The nerf, runway, floor and spend positions are reserved and print nothing yet.

## Panels

| Panel | Source | Rendering |
|---|---|---|
| Panel icons | the asks file (see [Ask indicators](#ask-indicators-1430)), then the per-session indicators file (below), then the wavemachine marker | asks first, then the indicators, in yellow, unchanged |
| Model-Effort | `model.display_name`, `effort.level` | `Sonnet 5.5-medium`; the `-effort` part is left out when the payload has none |
| Context | `context_window.total_input_tokens` | the absolute size: `999`, `1K`, `38K` (for 37,542), `312K`, `1M`, `1.2M`. No bar and no percent sign. Coloured by nerf's darts when nerf has a config for the session, else green, yellow at 25% remaining, red at 13% |
| Session | `rate_limits.five_hour.used_percentage` | `Session:12%`, only when the payload has it |
| Weekly | `rate_limits.seven_day.used_percentage` | `Weekly:92%`, only when the payload has it |
| dev-name avatar | `.claude/agent-identity.json` | as before |
| project-branch (worktree) | git | the project is the main repo's folder (taken from the git common directory, so a linked worktree shows its project, not its own folder); `-<branch>`, or the short commit when the head is detached; ` (<worktree-dir>)` only in a linked worktree. The existing `✓`/`✗` (clean or dirty), `+N` staged and `↑N`/`↓N` marks follow it |
| cwd | the payload | with `$HOME` shortened to `~` |

Session and Weekly turn yellow from 50% and red from 80%.

**One `jq` pass reads the whole payload** on each render, and git lookups are cached for a few seconds per cwd (`CLAUDE_STATUSLINE_GIT_TTL`, default 5; 0 turns the cache off). The remaining-context reading the reseed gate and nerf depend on (`~/.claude/state/context/<session>.json`, #1225) is written exactly as before.

## Shared window math

The reseed gate and (from #1428) the statusline's runway and floor panels do their context arithmetic in one place, `scripts/lib/context-math.sh`, so they cannot disagree. `context_math <reading.json> <nerf.json> [<settings.json>]` prints `key=value` lines: nerf's mode and darts, the reseed threshold, the autocompact window, the usable window (the smaller of the model window and the autocompact window, less the ~33k buffer), the remaining percent of it, the darts as token positions, and the runway to the nearer of reseed and autocompact. It writes nothing. See the header of that file for every key.

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

The identity file lives at `<project_root>/.claude/agent-identity.json` (reboot-durable). Fall back to the legacy `/tmp/claude-agent-<md5>.json` if absent (transition window):

```bash
project_root=$(pwd)
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
import json, os, tempfile, hashlib, subprocess

def set_indicators(indicators: list[str]):
    root = subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True
    ).strip()
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
