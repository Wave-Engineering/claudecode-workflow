# Precheck-asking Stop hook

A Claude Code `Stop` hook that catches "shall I run /precheck?" style asking phrasings and forces the agent to invoke `/precheck` instead. Closes the residual ~10% leak rate that the CLAUDE.md MANDATORY: Pre-Commit Gate prose alone doesn't catch.

Issue: cc-workflow#542 (paired with #541 prose tightening).

## What it does

When the agent finishes a turn, CC fires the Stop hook. The hook reads the JSONL transcript at `$transcript_path` (passed via stdin JSON), extracts the most recent assistant text, and pattern-matches against two regexes:

1. **Interrogative**: trigger word (`shall|should|can|may|do you want me to|ready (for|to)`) within ~40 chars of `precheck`, ending with `?` within ~80 chars.
2. **Deferral**: `let me know` idiom within ~40 chars of `precheck` (no `?` required — deferral is asking-by-omission).

If matched, the hook emits `{"decision":"block","reason":"..."}` to stdout, which forces the assistant to continue this turn with the corrective context — no human intervention required.

If unmatched, the hook exits 0 silently. No-op cost: ~20ms on a 200-event transcript.

## Negative cases (must NOT trigger)

- Documenting precheck after it ran: `/precheck completed cleanly. Ready for your call.`
- Different command: `Shall I run /scp?`
- Distant trigger word and `precheck`: a sentence with both >40 chars apart
- Ordinary checklist text: `Ready for /scp / /scpmr / /scpmmr`

A regression test (`tests/regression/test_precheck_asking_detector.sh`) covers all positive and negative cases plus a performance budget (<500ms CI ceiling, <50ms target).

## Disable temporarily

Two layers, by escalation:

1. **Per-session env var:**
   ```bash
   export PRECHECK_ASKING_HOOK_DISABLED=1
   ```
   The hook honors this on every invocation. Useful when meta-discussing the rule itself (this doc, code-review of the hook source, fixture transcripts) — quoting a forbidden phrase otherwise triggers the hook.

2. **Per-machine: comment out the entry in `~/.claude/settings.json`.** The kit's installer will re-add it on the next `./install` unless you also remove it from `config/settings.template.json` (which would land in a PR).

## Falsy edge — quoting the rule

If the agent writes a message documenting the rule by quoting a forbidden phrase (e.g. *"Don't write 'shall I run /precheck?'"*), the regex will match the quoted phrase and the hook will fire. This is by design — the cost is small (one wasted continuation), and the kill-switch env var exists to suppress it during meta-discussion. Trying to make the regex distinguish "real ask" from "documenting an ask" is a false-precision exercise.

## Performance budget

The hook fires on every Stop in every CC session, so it must be cheap.

| Operation | Cost |
|-----------|------|
| Read stdin JSON | <1ms |
| `tail -n 200` of transcript | <5ms |
| `jq` to extract last assistant text | <10ms |
| Two `grep -P` passes | <5ms |
| **Total target** | **<50ms** |
| **CI ceiling** | **500ms** (tolerates VM variance) |

## Architecture

```
CC agent finishes turn
        │
        ▼
   Stop hook fires
        │
        ▼
  reads $transcript_path via stdin JSON
        │
        ▼
  extracts last assistant text via jq
        │
        ▼
  greps for asking patterns
        │
        ├── match ──▶ emit {"decision":"block","reason":"..."} ──▶ agent continues turn with /precheck
        │
        └── no match ─▶ exit 0, agent's stop is honored
```

## See also

- `scripts/precheck-asking-detector.sh` — hook source
- `tests/regression/test_precheck_asking_detector.sh` — regression tests
- `config/settings.template.json` — Stop hook entry (installed to `~/.claude/settings.json`)
- `CLAUDE.md` — the rule itself (MANDATORY: Pre-Commit Gate)
- Memory: `feedback_precheck_no_ask.md` — paired feedback record with phrasings list
- Issues: cc-workflow#541 (prose half), #542 (this hook)
