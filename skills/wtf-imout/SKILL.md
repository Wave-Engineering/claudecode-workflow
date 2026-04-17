---
name: wtf-imout
description: Suspend the WTF troubleshooting session (preserves data)
---

# /wtf imout — Suspend Troubleshooting Session

Stop recording tool calls but preserve all captured data for later analysis.

## Steps

1. **Call the `wtf_imout` MCP tool** with no arguments.

2. **Parse the response** and report to the user:
   - If `ok: true` → "Recording suspended. Incident {incident_id} preserved for triage via `wtf_happened`."
   - If `ok: false` → "{message}" (e.g., "No active incident to suspend.")

## Important

- This does NOT delete captured data — it only stops future captures
- The suspended incident can still be viewed with `wtf_happened`
- Starting a new `/wtf` session will create a new incident (the suspended one remains archived)
