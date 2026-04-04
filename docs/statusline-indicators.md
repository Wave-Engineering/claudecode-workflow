# Statusline Per-Session Indicators

The statusline supports per-session indicators — short strings that appear on Line 1, left of the working directory, rendered in yellow. Any skill or script can publish indicators to communicate state at a glance.

```
Line 1: [indicators]  [pwd]  [dev-name] [dev-avatar]
Line 2: [repo @ branch] [status] [ctx remaining] [model]
```

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

The identity file is keyed by the md5 hash of the project root:

```bash
project_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
dir_hash=$(echo -n "$project_root" | md5sum | cut -d' ' -f1)
dev_name=$(jq -r '.dev_name // empty' "/tmp/claude-agent-${dir_hash}.json" 2>/dev/null)
```

## Writing Indicators

**Always write atomically** (temp file + rename) to avoid the statusline reading a half-written file:

```bash
dev_name=$(jq -r '.dev_name // empty' "/tmp/claude-agent-${dir_hash}.json" 2>/dev/null)
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
| Context budget | `🔥 DOOM` | Nerf system in ultraviolence mode |
| Nerf soft dart | `⚡ 120k` | Approaching soft context limit |
| Nerf hard dart | `🔥 160k` | Hit hard context limit |
| Nerf ouch dart | `💀 180k` | At maximum context budget |
| Nerf mode | `🎯 HMP` | Current nerf mode (hurt-me-plenty) |
| Timer | `⏱ 12m` | Time remaining on a task |
| Build status | `✓ BUILD` | Last build passed |
| Blocked | `⛔ KILL` | Kill switch engaged |

## Design Notes

- **Rendezvous key is `dev_name`**, not session_id or PID. The statusline subprocess is detached from the TTY and has no access to session-specific env vars, but it can always resolve `dev_name` through the project-root-hashed identity file.
- **Atomic writes matter** because the statusline polls at ~300ms and `jq` will error on partial JSON.
- **Multiple skills sharing indicators** — the file holds a single flat array. If more than one skill needs to publish indicators simultaneously, each must read-modify-write: read the existing array, update its own entries, and write the full array back. A plain overwrite will replace indicators set by other skills.
- **Ownership** — the session that wrote the file owns it. Since `dev_name` is unique per session, there's no cross-session conflict.
