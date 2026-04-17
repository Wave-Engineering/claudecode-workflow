---
name: wtf-happened
description: Retrieve the WTF incident timeline and generate a runbook
---

# /wtf happened — Get the Incident Timeline

Retrieve a distilled timeline of the current troubleshooting incident and
generate a runbook skeleton. Returns a concise summary by default, or the
full untruncated timeline on request.

## Resolve Intent

Parse the invocation arguments:

- **No arguments** — return the summary timeline (default, max 50 lines).
- **`full`** — return the full timeline with no truncation.

## Steps

### 1. Call wtf_happened

Call the `wtf_happened` MCP tool with the appropriate detail level:

**Default (no args):**
```json
{}
```

**Full mode (`/wtf happened full`):**
```json
{
  "detail": "full"
}
```

### 2. Present the result

Display the returned Markdown timeline directly to the user. The tool
response includes a header with duration, entry counts, and status,
followed by a numbered timeline of classified events.

If a runbook was generated, note the file path:

> Runbook written to `.wtf/runbook.md`

### 3. Offer next steps

After presenting the timeline, briefly suggest:

- `/wtf now "<observation>"` to keep recording
- `wtf_freshell` to archive and start a new incident
- `/view .wtf/runbook.md` to review the generated runbook
