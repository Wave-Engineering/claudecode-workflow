# MCP Server Scoping

> Originally lived inline in CLAUDE.md. Moved here in #276 to reduce per-session
> context pressure. The content is verbatim — this IS the documentation for the
> `disabledMcpServers` field, which is not surfaced in the official Claude Code
> docs.

Claude Code's MCP scopes are **additive, not exclusive**. Servers from `~/.claude/mcp.json`, `~/.claude/settings.json` (`mcpServers`, `enabledPlugins`), `~/.claude.json` (`mcpServers`), project `.mcp.json`, and claude.ai account-connected plugins all merge into a single deferred tool list at session start. Creating a project `.mcp.json` does NOT replace inherited servers; it adds to them.

## The per-project exclusion knob

`~/.claude.json` → `projects["<project-path>"].disabledMcpServers` is an array of server names to suppress for a specific project. Tools from disabled servers do not appear in the deferred tool list when running in that project. This mechanism works but is undocumented in the official Claude Code docs — it was discovered via direct inspection of `~/.claude.json` (see #266).

**Server name format** — use the exact string reported by `claude mcp list`:
- `claude.ai <Name>` for claude.ai-hosted plugins (spaces, not underscores)
- `plugin:<marketplace>:<name>` for marketplace plugins from `enabledPlugins`
- The raw name for stdio servers (`kapture`, `nerf-server`, etc.)

## Updating the disable list

```bash
# 1. Inventory all currently-resolved servers
claude mcp list

# 2. Edit ~/.claude.json via jq + write-temp-then-mv (not an interactive
#    editor — the file is large and contains session state written back by
#    Claude Code, so mid-session interactive edits race with CC's own writes)
#
# CRITICAL: write to a .new file, NEVER `jq '...' ~/.claude.json > ~/.claude.json`
# directly. The shell truncates the output file to zero bytes before jq reads
# the input, silently destroying your 150KB config. Always use the temp-file
# pattern below.
jq '.projects["/abs/path/to/project"].disabledMcpServers = [
      "plugin:github:github",
      "claude.ai Canva"
    ]' ~/.claude.json > ~/.claude.json.new && mv ~/.claude.json.new ~/.claude.json

# 3. Verify
jq '.projects["/abs/path/to/project"].disabledMcpServers' ~/.claude.json

# 4. Restart Claude Code — changes take effect at the next session start,
#    not mid-session. Verify by checking that the deferred tool list in the
#    new session no longer contains tools from the disabled servers.
```

**Project policy for this repo:** Only servers directly used in this repo's work are kept active. `discord-watcher` (session messaging via `--channels`), `wtf-server` (flight recorder hook), and `plugin:context7:context7` (library docs) are kept. Everything else is disabled for context hygiene. See `~/.claude.json` for the authoritative current list.

## What this does NOT solve

- `.mcp.json` scope merging — there is no "exclusive mode" for project config
- Discoverability — the `disabledMcpServers` field is not surfaced in `claude mcp --help` or the official docs; this page IS the documentation
