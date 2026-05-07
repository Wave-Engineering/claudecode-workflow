### chore(precheck): log vox-invocation failures instead of swallowing with || true (#550)

`/precheck` no longer wraps `vox` with `|| true`. The skill now documents the canonical instrumented pattern that captures vox's rc + stderr and, on non-zero, emits a `vox_invocation_failed` event to `mcp.jsonl` (server `precheck`, level `warn`). The gate stays best-effort — vox failure does not block — but the failure is no longer hidden.

Checklist now distinguishes vox outcome visually:
- success: `vox: ✅ fired`
- failure: `vox: ⚠️ failed (rc=N — see mcp.jsonl)`

Pairs with cc-workflow#551 (vox-script-side instrumentation). The two layers catch different failure modes:
- `vox_invocation_failed` (this PR, from `/precheck`) — vox didn't run at all, or returned non-zero
- `call_failed` (vox-script) — vox ran but provider/player failed

Files: `skills/precheck/SKILL.md` — Step 4 guidance, Notification section (canonical bash pattern + cross-link), checklist status line, and Rules section all updated.
