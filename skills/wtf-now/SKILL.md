---
name: wtf-now
description: Record a manual journal entry in the WTF flight recorder
---

# /wtf now — Record a Manual Journal Entry

Add a manual observation to the WTF flight recorder journal. The entry is
stored as a crafted (intentional) record. Classification of the entry's
action type is handled by the background classifier — do not attempt to
infer it here.

## Resolve Intent

The entire argument string after `/wtf now` is the freeform text to record.
There are no subcommands or flags.

Examples:
- `/wtf now the DNS resolver is returning stale records`
- `/wtf now "checked nginx logs — 502s started at 14:32"`
- `/wtf now theory: might be a connection pool exhaustion issue`

## Steps

### 1. Record the entry

Call the `wtf_now` MCP tool with:

```json
{
  "gen_type": "crafted",
  "text": "<user's text>"
}
```

Do **not** set `action_type`. Leave classification to the background
classifier.

### 2. Confirm to the user

Respond with:

> Recorded: <user's text>

Nothing else is needed. Keep it brief so the user can continue
troubleshooting without interruption.
