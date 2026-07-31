# Flight surgeon — host-side health probe

Story 3.1 (#970), Plan #959 — Contained Workflow Dev Spec §5.7.

A **host-side** probe that watches each `:edge` dogfood container and decides
whether it is **broken**, by reading the container's **host-backed `.jsonl`
transcript directly**. The transcript is written by the harness *below* the kit,
so the probe is **fate-independent** (R-15): a wedged, looping, or OOM-killed
agent cannot corrupt the signal, and the probe needs **nothing from inside the
container** — no `docker exec`, no kit import, no MCP call.

## `transcript_resolved` (input and output)

Both an accepted observation key and an emitted report field. `false` means **no
transcript could be resolved for this session — its health was never measured**.

It matters because an unresolved session is not a neutral one: it classifies
`running` with no timestamps, which takes the "no timestamped activity yet"
branch and yields `broken=false`. Without this field it is indistinguishable from
a healthy session, and `soak_accrual_bridge` would credit soak toward promotion on
evidence that does not exist (#1075). Absent in an observation file, it defaults
to `true` — a hand-authored observation supplies its entries directly.

The live seam that produces it is pinned by **MV-05 step 2**, which re-observes
aoe's `/workspace/<name>` mount against a running container.

## What it detects (R-16)

While a container's aoe status is **`running`**:

- **Stall** — the transcript has not grown for N minutes (default 15).
- **Loop** — the same tool action repeats at the tail, or a short tool cycle
  repeats (default: 5 consecutive, cycle period ≤ 4) — "no forward progress".

Both signals are **gated on `running`**: a flat or repetitive transcript while
`idle` / `waiting` / `stopped` / `error` is normal (the agent finished or awaits
input), never a break.

## Profile filter (R-22)

The probe filters on the container's **profile label**. A broken **dev-mode**
container is still reported broken (visible) but is marked
`should_quarantine = false` — dev-mode breakages never trip quarantine or count
toward soak. Exclusion requires an **explicit** `dev-mode` label; an unlabeled or
unknown-profile candidate stays quarantine-**eligible** so a broken candidate
can never escape the probe by lacking a label. The label mechanism itself is
Story 4.1 (#974); this probe *consumes* it.

## Scope — detection only

This story **detects and classifies**. It performs **no quarantine action**
(stop / `docker rm` / recreate on `:stable`) — that is Story 3.2 (#971), which
consumes this module's `should_quarantine` verdict.

## Usage

```bash
# classify an explicit manifest of observations (deterministic; '-' = stdin)
python3 scripts/flight-surgeon/surgeon.py --observations obs.json

# best-effort live gather over aoe sessions (flags the UNPROVEN seams)
python3 scripts/flight-surgeon/surgeon.py --live --transcripts-root ~/.oaw/state/$OAW_MAJOR/transcripts

# a watcher/cron signal: non-zero exit if any quarantine-eligible break
python3 scripts/flight-surgeon/surgeon.py --observations obs.json --fail-on-quarantine
```

Emits a JSON report on stdout (one assessment per container) and a human summary
on stderr. Exit `0` normally, `3` with `--fail-on-quarantine` when a
quarantine-eligible break is present, `2` on a usage/parse error.

### Observation manifest

A JSON list (or `{ "observations": [...] }`) of records:

```json
[
  {
    "container_id": "abc123",
    "title": "dogbox",
    "status": "running",
    "profile": "dogfood",
    "transcript": "/host/path/to/session.jsonl"
  }
]
```

`transcript` (a host path, read directly) may be replaced by inline `entries`
(a list of parsed transcript objects, for testing). An optional `last_growth`
(ISO-8601) supplies a watcher's file-mtime probe when the transcript itself
carries no fresh timestamp.

## The live seam (UNPROVEN — MV-04 / MV-06)

`--live` maps an aoe session to its host-backed transcript path and reads its
profile label. Both depend on aoe's sandbox mount/label layout, which cannot be
proven without a running sandbox (Dev Spec TC-7 / §5.N). The pure classifier is
the story's canonical oracle (`tests/contained-workflow/test_surgeon.py`); the
live wiring is exercised by the manual procedures MV-04 (control-plane ingress)
and MV-06 (transcript-flush-at-failure) in
`docs/contained-workflow/manual-verification.md`.
