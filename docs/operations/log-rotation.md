# MCP Log Rotation

The Claude Code kit's MCP fleet writes a unified structured-event log to
`~/.claude/logs/mcp.jsonl`. At ~12 events/sec sustained, the file accrues
roughly 290k events / day and grows on the order of 50 MB / day. Without
rotation, the aggregator reaches multi-GB sizes within weeks — slow to
grep, slow to tail, and an eventual disk-fill risk on developer machines.

The kit ships a `logrotate(8)` policy that lands at
`/etc/logrotate.d/cc-mcp-logs` during install. This doc describes the
policy, the operational commands, and the macOS escape hatch.

## Scope and platform

**Linux only.** `logrotate` is in every standard Linux distro and the kit
relies on the system-wide `cron.daily` (or systemd timer) hook to invoke
it. The `install --with-logrotate` flag is a no-op on macOS / non-Linux
hosts — the installer detects `uname` and skips the step with a notice.

**macOS users:** macOS ships `newsyslog(8)` instead of `logrotate`. The
cc-workflow kit does not currently include a `newsyslog` config; the
recommended workaround is one of:

- Manual rotation: `mv ~/.claude/logs/mcp.jsonl{,.$(date +%Y%m%d)} &&
  : > ~/.claude/logs/mcp.jsonl` on a personal cron / launchd schedule.
- Native `newsyslog` config under `/etc/newsyslog.d/cc-mcp-logs.conf`
  with `B` (binary mode, do not insert "logfile turned over" markers)
  and a size threshold. PRs adding this template welcomed.

If macOS support becomes load-bearing, a separate issue should track it.

## Policy

```
~/.claude/logs/mcp.jsonl {
    size 100M
    daily
    rotate 14
    compress
    delaycompress
    copytruncate
    missingok
    notifempty
}
```

| Directive       | Effect                                                                                |
| --------------- | ------------------------------------------------------------------------------------- |
| `size 100M`     | Rotate when file exceeds 100 MB, regardless of cadence.                               |
| `daily`         | Also rotate every day at the system's `cron.daily` time, even if under the size cap. |
| `rotate 14`     | Keep 14 historical files; the 15th oldest is unlinked.                                |
| `compress`      | Gzip rotated files (`.1.gz`, `.2.gz`, ...).                                           |
| `delaycompress` | Skip compressing the most-recent rotation (so `.1` stays plaintext for grep/tail).   |
| `copytruncate`  | Copy contents to the rotated path, then truncate the live file in place.              |
| `missingok`     | Do not error if the log file does not exist yet (fresh installs).                     |
| `notifempty`    | Do not rotate an empty file.                                                          |

### Why `copytruncate` (load-bearing)

The conventional `logrotate` workflow is rename-and-reopen:

1. `mv mcp.jsonl mcp.jsonl.1`
2. Send SIGHUP (or equivalent) to the writing process so it reopens its
   log file descriptor at the original path.

The kit's MCP servers do **not** handle SIGHUP. They open their log
once at startup and hold the file descriptor for the lifetime of the
process. A rename-and-reopen rotation would orphan the file descriptor —
the OS would keep `mcp.jsonl.1` open under the writing process while the
new `mcp.jsonl` sat on disk receiving zero events. Silent log loss.

`copytruncate` solves this by preserving the inode: the rotation runs
`cp mcp.jsonl mcp.jsonl.1; : > mcp.jsonl`. The MCP server's open file
descriptor still points at the same inode, which has been truncated to
zero. Subsequent writes append to the (now empty) file. There is a small
window during the copy where new events may write into both the source
(before truncate) and the rotated copy (since the copy started); these
are duplicates, not losses, and the timestamp ordering is preserved.

For comparison, the alternative — adding SIGHUP handling to every MCP
server — is a fleet-wide refactor of process lifecycle code. Not worth
it for a log rotation policy.

## Install / uninstall

```bash
# Install (interactive prompt)
./install

# Install non-interactively
./install --with-logrotate

# Skip rotation install (still installs the rest of the kit)
./install --without-logrotate

# Check whether rotation is in place
./install --check
```

`./install --with-logrotate` does the following:

1. Detects platform; bails out cleanly on non-Linux.
2. Renders `assets/logrotate/cc-mcp-logs` with the current user's home.
3. Drops it to `/etc/logrotate.d/cc-mcp-logs` via `sudo install -m 0644`.
4. Runs `sudo logrotate -d /etc/logrotate.d/cc-mcp-logs` for syntax /
   target validation, surfaces stderr.

## Operational commands

```bash
# Validate config without rotating (dry-run, prints what would happen)
sudo logrotate -d /etc/logrotate.d/cc-mcp-logs

# Force-rotate now, ignoring size and cadence thresholds
sudo logrotate -f /etc/logrotate.d/cc-mcp-logs

# Inspect last rotation time
ls -lh ~/.claude/logs/mcp.jsonl*

# Tail the most-recent rotation (uncompressed thanks to delaycompress)
tail -F ~/.claude/logs/mcp.jsonl.1
```

## Disabling temporarily

For short-term high-volume debugging where you want every event in
one file:

```bash
# Move the config aside; logrotate will skip it
sudo mv /etc/logrotate.d/cc-mcp-logs{,.disabled}

# ...debug session here...

# Re-enable
sudo mv /etc/logrotate.d/cc-mcp-logs{.disabled,}
```

Or comment out the entire stanza in place. The kit's `--check` mode
reports the config as missing while it is `.disabled`.

## Removing the policy

```bash
sudo rm /etc/logrotate.d/cc-mcp-logs
```

Existing `.gz` archives under `~/.claude/logs/` are unaffected. To
reclaim disk space:

```bash
rm ~/.claude/logs/mcp.jsonl.*.gz
```

## Verification on a Linux test box

The full operator-side verification list (per cc-workflow#540):

1. `./install --with-logrotate` succeeds on a fresh checkout.
2. `sudo logrotate -d /etc/logrotate.d/cc-mcp-logs` reports no errors.
3. `sudo logrotate -f /etc/logrotate.d/cc-mcp-logs` produces
   `mcp.jsonl.1` (uncompressed); MCP servers continue writing to
   `mcp.jsonl` without restart; no log lines lost.
4. After a second forced run: `mcp.jsonl.1.gz` exists and `mcp.jsonl.1`
   is the most-recent rotation (delaycompress confirmed).
5. `./install --check` reports the rotation config as present and
   surfaces the last-rotation mtime.
