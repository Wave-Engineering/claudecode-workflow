# MCP Server Logging Standard

**Status:** Accepted
**Scope:** All `Wave-Engineering/mcp-server-*` projects
**Date:** 2026-04-12

---

## Problem

Five MCP servers share a runtime model (TypeScript/Bun compiled binaries) but
have no consistent logging. The discord server logs nothing on API calls. The
watcher logs to stderr with ad-hoc `console.error` prefixed `[server-name]`.
The SDLC server has one `process.stderr.write` across 67 handlers. Nerf logs
nothing at all. This makes diagnosing production issues (rate limits, routing
failures, kill switch triggers) impossible without source inspection.

## Design Principles

1. **Structured JSON lines** — one JSON object per line, machine-parseable,
   `jq`-friendly. No freeform text.
2. **Lightweight** — a single `logger.ts` file per server, no external
   dependencies. Copy-paste, not npm publish.
3. **Stderr + optional file** — always write to stderr (MCP transport
   visibility); optionally write to `~/.claude/logs/<server>.jsonl`.
4. **Environment-driven** — `LOG_LEVEL` and `LOG_FILE` env vars. No config
   files for logging itself.
5. **Non-breaking adoption** — servers can adopt incrementally. Existing
   `console.error` calls migrate to logger calls one handler at a time.

## Log Line Schema

Every log line is a JSON object with these fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `ts` | string (ISO 8601) | yes | Timestamp with milliseconds |
| `server` | string | yes | Server short name: `disc`, `watcher`, `nerf`, `sdlc`, `wtf` |
| `level` | string | yes | `debug`, `info`, `warn`, `error` |
| `event` | string | yes | Event type (see Standard Events below) |
| `msg` | string | no | Human-readable message |
| `...` | any | no | Event-specific fields (see below) |

Example:
```json
{"ts":"2026-04-12T18:32:01.123Z","server":"disc","level":"info","event":"api_call","method":"POST","endpoint":"/channels/123/messages","status":200,"ms":142}
```

## Standard Events

### `api_call` — External API request completed

For any HTTP call to Discord, GitHub, GitLab, or other external service.

| Field | Type | Description |
|-------|------|-------------|
| `method` | string | HTTP method (GET, POST, etc.) |
| `endpoint` | string | API path (no base URL, no query params with secrets) |
| `status` | number | HTTP status code |
| `ms` | number | Request duration in milliseconds |
| `service` | string | `discord`, `github`, `gitlab`, `scream-hole` |
| `retry` | number? | Retry-After value if rate-limited |

### `tool_call` — MCP tool invoked

| Field | Type | Description |
|-------|------|-------------|
| `tool` | string | Tool name (e.g., `disc_send`, `pr_merge`) |
| `ok` | boolean | Whether the tool returned success |
| `ms` | number | Total execution time |
| `error` | string? | Error message if `ok: false` |

### `state_change` — Internal state transition

| Field | Type | Description |
|-------|------|-------------|
| `what` | string | What changed: `kill_switch`, `auth`, `mode`, `config` |
| `from` | string? | Previous state |
| `to` | string | New state |
| `reason` | string? | Why the change happened |

### `subprocess` — Shell command executed

For servers that shell out to CLI tools (sdlc → `gh`/`glab`, commutativity → `commutativity-probe`).

| Field | Type | Description |
|-------|------|-------------|
| `cmd` | string | Command name only (no args — may contain secrets) |
| `exit_code` | number | Process exit code |
| `ms` | number | Execution duration |
| `stderr` | string? | First 200 chars of stderr on failure |

### `poll` — Periodic polling cycle (watcher-specific)

| Field | Type | Description |
|-------|------|-------------|
| `channels` | number | Channels polled this cycle |
| `new_messages` | number | New messages found |
| `ms` | number | Cycle duration |
| `via` | string | `direct` or `scream-hole` |

### `startup` — Server initialization

| Field | Type | Description |
|-------|------|-------------|
| `version` | string? | Server version if available |
| `config` | object | Non-secret config summary (mode, routes, features enabled) |

## Log Levels

| Level | When to use |
|-------|-------------|
| `debug` | Verbose diagnostic info — individual poll results, cache hits, argument details. Off by default. |
| `info` | Normal operations worth recording — API calls, tool invocations, state changes, startup. |
| `warn` | Degraded but recoverable — rate limits, fallbacks, retries, missing optional config. |
| `error` | Failures — unrecoverable errors, auth failures, subprocess crashes. |

Default level: `info`. Set via `LOG_LEVEL=debug` env var.

## Logger Implementation

Each server copies a `logger.ts` file (not a shared dependency — keeps builds
independent). The interface:

```typescript
// logger.ts — MCP structured logger
//
// Usage:
//   import { log } from './logger.ts';
//   log.info('api_call', { method: 'POST', endpoint: '/channels/123/messages', status: 200, ms: 142 });
//   log.warn('state_change', { what: 'kill_switch', to: 'engaged', reason: '429' });
//   log.error('api_call', { method: 'GET', endpoint: '/channels/456/messages', status: 429, ms: 50 }, 'Rate limited');

import { appendFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { mkdirSync, existsSync } from 'node:fs';

const LEVELS = { debug: 0, info: 1, warn: 2, error: 3 } as const;
type Level = keyof typeof LEVELS;

const SERVER_NAME = process.env.MCP_SERVER_NAME || 'unknown';
const LOG_LEVEL: Level = (process.env.LOG_LEVEL as Level) || 'info';
const LOG_FILE = process.env.LOG_FILE; // e.g., ~/.claude/logs/disc.jsonl

function shouldLog(level: Level): boolean {
  return LEVELS[level] >= LEVELS[LOG_LEVEL];
}

function emit(level: Level, event: string, fields: Record<string, unknown>, msg?: string): void {
  if (!shouldLog(level)) return;

  const line: Record<string, unknown> = {
    ts: new Date().toISOString(),
    server: SERVER_NAME,
    level,
    event,
    ...fields,
  };
  if (msg) line.msg = msg;

  const json = JSON.stringify(line);

  // Always stderr
  process.stderr.write(json + '\n');

  // Optional file output
  if (LOG_FILE) {
    try {
      const resolved = LOG_FILE.replace(/^~/, homedir());
      const dir = join(resolved, '..');
      if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
      appendFileSync(resolved, json + '\n');
    } catch {
      // Best-effort — don't crash the server over logging
    }
  }
}

export const log = {
  debug: (event: string, fields: Record<string, unknown> = {}, msg?: string) => emit('debug', event, fields, msg),
  info:  (event: string, fields: Record<string, unknown> = {}, msg?: string) => emit('info', event, fields, msg),
  warn:  (event: string, fields: Record<string, unknown> = {}, msg?: string) => emit('warn', event, fields, msg),
  error: (event: string, fields: Record<string, unknown> = {}, msg?: string) => emit('error', event, fields, msg),
};
```

Each server sets `MCP_SERVER_NAME` in its entry point or build config.

## File Output

When `LOG_FILE` is set (e.g., `LOG_FILE=~/.claude/logs/disc.jsonl`):

- Logs are appended to the file as JSON lines
- Directory is created if it doesn't exist
- No rotation in v1 — files are diagnostic, not archival
- Agents or operators can `tail -f ~/.claude/logs/disc.jsonl | jq .` for live monitoring
- Convention: `~/.claude/logs/<server-short-name>.jsonl`

## Migration Guide

### Phase 1: Add logger, instrument critical paths

Each server adds `logger.ts` and instruments:
- All external API calls (`api_call`)
- Kill switch / auth state changes (`state_change`)
- Startup config (`startup`)
- Errors that are currently swallowed

Existing `console.error` calls can coexist temporarily.

### Phase 2: Replace ad-hoc logging

Migrate remaining `console.error` calls to structured logger calls.
Remove freeform text logging.

### Phase 3: Enable file output fleet-wide

Add `LOG_FILE=~/.claude/logs/<server>.jsonl` to agent launch config or
`.bashrc`. Enables centralized diagnosis without terminal access.

## Per-Server Priority

| Server | Priority | Rationale |
|--------|----------|-----------|
| **disc-server** | P0 | Zero API logging today. Rate limit diagnosis impossible. |
| **discord-watcher** | P0 | Polling is the main rate budget consumer. Scream-hole routing verification needed. |
| **mcp-server-sdlc** | P1 | 67 handlers, subprocess calls to gh/glab. Failure diagnosis requires re-running. |
| **mcp-server-wtf** | P2 | Has some logging already. Lower urgency. |
| **mcp-server-nerf** | P2 | Internal state management only. No external API calls. |

## Security

- Never log Discord bot tokens, API keys, or message content at `info` level
- `debug` level may include message previews (first 100 chars) for diagnosis
- Endpoint paths are logged without query parameters (query strings may contain tokens)
- Subprocess commands log the command name only, not arguments (may contain repo paths, branch names with sensitive info at debug level only)
