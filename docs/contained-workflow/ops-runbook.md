# Operations runbook — contained workflow

Deliverable **DM-09** (Plan #959, Dev Spec §4 / §5.6 / §5.7). The operator's
day-to-day runbook for the `oakandwave-workflow` image lifecycle: **build a
candidate → dogfood soak → promote → fleet adoption → quarantine + rollback**,
plus the two live-mount operations (add a secret, roll back a bad `:stable`).

This runbook is the *procedure* layer. The *decisions* it invokes live in
unit-tested modules, never in shell (project rule) — every wrapper below only
gathers signals and applies an already-tested plan:

| Concern | Decision module (tested) | Operator wrapper |
|---------|--------------------------|------------------|
| Build + provenance labels | `oakandwave-oci-labels.sh` | `scripts/ci/build-oakandwave-image.sh` |
| Dogfood launch args | `containers/oakandwave-workflow/profiles.py` | `scripts/ci/dogfood-cutover.sh` |
| Soak accrual | `containers/oakandwave-workflow/soak_ledger.py` | `scripts/ci/soak-accrual-bridge.sh` — surgeon `--live` → `soak_ledger.accrue` (#1008) |
| Health verdict | `scripts/flight-surgeon/surgeon.py` | `scripts/flight-surgeon/surgeon.py --live` |
| Promotion gate + retag | `containers/oakandwave-workflow/promotion_gate.py` | `scripts/ci/promote-oakandwave-image.sh` |
| Per-agent adoption | `containers/oakandwave-workflow/adoption.py` | `scripts/ci/adopt-stable.sh` |
| Quarantine + lossless proof | `containers/oakandwave-workflow/quarantine.py` | `scripts/ci/quarantine-container.sh` |

**Companion docs.** Registry-artifact verification at promotion time (OCI
labels, cosign signature, syft SBOM, permissions, digest continuity) is a
separate checklist: `deployment-verification.md` (DM-12). Manual verification
procedures (MV-01..MV-07) are `manual-verification.md` (DM-10). Host
prerequisites are `environment-prerequisites.md` (DM-13). The design authority is
`docs/contained-workflow-devspec.md`.

---

## 0. Prerequisites

- **aoe 1.13.0**, **rootful docker** (no userns remap), host uid `1000`
  (`bakerb`) — full list in `environment-prerequisites.md`.
- `ghcr` auth for pull/push of `oakandwave-workflow:<tag>` (TC-5: the registry
  needs a token; egress on the default bridge otherwise works — MV-03).
- A host `~/.secrets` dir (read-only mount source, §5.5) and `~/.oaw/` for
  sandbox-scoped state (`~/.oaw/state/<major>/`, `~/.oaw/quarantine/`,
  `~/.oaw/adoption/`).

**Every destructive wrapper here defaults to a dry-run plan.** `dogfood-cutover`,
`promote`, `adopt`, and `quarantine` all print the exact commands and change
*nothing* until an explicit `*_APPLY=true` / `*_DRY_RUN=false` operator go. Run
the plan first, read it, then apply.

---

## 1. Build a candidate (`:edge`) — §4.2

The kit change merges to `main`; CI builds `FROM aoe-dev-sandbox:1.13.0` + the
kit-dep toolchain + `./install`, stamps OCI provenance, signs (cosign) + SBOMs
(syft), pushes, and moves the `:edge` tag onto the exact digest built (R-05,
R-23, R-24).

**In CI** (the normal path — `.github/workflows/oakandwave-workflow-image.yml`,
DM-03): the workflow calls the wrapper in one line.

**Locally** (to reproduce or debug a build):

```bash
# Build + load locally, no push (PR-validation modality):
IMAGE=ghcr.io/wave-engineering/oakandwave-workflow PUSH=false \
  scripts/ci/build-oakandwave-image.sh

# Or the plain terminal build (no provenance/push), for a fast inner loop:
make -C containers/oakandwave-workflow build      # -> oakandwave-workflow:edge
```

The wrapper writes the resulting **digest** to stdout (and `$GITHUB_OUTPUT`). The
throwaway-CI ring (E2E-01) then pulls **that digest** — never a moving tag — and
verifies labels/permissions/signature/SBOM before the smoke suite; a red smoke
blocks the digest. See `deployment-verification.md` for the verification
checklist the ring automates.

**Verify the toolchain** on a built image:

```bash
make -C containers/oakandwave-workflow verify
# trivy / shellcheck / shfmt / glab / go all report a version
```

---

## 2. Dogfood soak — §4.3

Cut the OaW dev team onto `:edge` in the **dogfood** profile (skills overlay OFF,
image-only — the profile the gate trusts, R-21) with the flight surgeon watching.
Clean work accrues soak **automatically**: the soak-accrual bridge (`scripts/ci/soak-accrual-bridge.sh`, #1008) drives the flight surgeon over the live ring and feeds each running dogfood session's clean span to `soak_ledger`, so the promotion gate's `SOAK_HOURS` fills over time (run it periodically / from a cron during the cutover). A broken candidate is caught and held.

```bash
# 0) The profile must carry the declared mounts. mounts.d/ is the source of truth,
#    but AoE only applies what extra_volumes lists — a profile missing them comes up
#    with no memory, no secrets and cold caches, silently (#1069). Generate + verify:
#      python3 containers/oakandwave-workflow/mount_resolver.py \
#          --major "$(scripts/ci/oaw-major.sh)" --format aoe-toml   # paste-ready
#      scripts/ci/check-mount-drift.sh dogfood
#    The cutover runs this itself: ADVISORY on plan, FATAL before a real launch.
#    CUTOVER_CHECK_PROFILES names the profiles to check ("dogfood" by default);
#    set it EMPTY to skip. AOE_PROFILE_ROOT relocates the profile dir (test seam).

# 1) PLAN (default): prints the exact `aoe add` line per workspace + the surgeon
#    watch command, launches NOTHING.
EDGE_REF=oakandwave-workflow:edge \
  CUTOVER_WORKSPACES="/path/to/ws1 /path/to/ws2" \
  scripts/ci/dogfood-cutover.sh

# 2) APPLY (deliberate, per-cutover go — this cuts LIVE agents onto the candidate):
DOGFOOD_CUTOVER_APPLY=true EDGE_REF=oakandwave-workflow:edge \
  CUTOVER_WORKSPACES="/path/to/ws1 /path/to/ws2" \
  scripts/ci/dogfood-cutover.sh
```

Each container is launched with the `oaw.profile=dogfood` label
(`profiles.py --emit launch --profile dogfood`). The surgeon and the promotion
gate **filter on that label** — a `dev-mode` run (overlay ON, labelled
non-candidate) never counts toward soak and never trips quarantine (R-22).

**Start the surgeon** watching the dogfood ring (host-side, reads each
container's host-backed transcript — no `docker exec`, no kit dependency, R-15):

```bash
python3 scripts/flight-surgeon/surgeon.py --live \
  --transcripts-root ~/.oaw/state/$OAW_MAJOR/transcripts
```

It correlates transcript growth with aoe status: `running` + flat-for-N-minutes =
stalled; a same-tool-K-times / no-forward-progress heuristic catches loops
(R-16). Clean spans become soak records (`soak_ledger.py`).

**Accrue soak** from the live ring (the R-15 surgeon is stdlib-only and can't import
`soak_ledger`, so a separate bridge runs both — #1008):

```bash
# Feed each running dogfood session's clean span to the gate's soak ledger.
# Idempotent (watermarked per session) — safe to run on a cron during the cutover.
# LOOK_BACK MUST match the cron cadence (see below). Run it AT LEAST every LOOK_BACK.
OAW_SOAK_LEDGER=~/.oaw/soak/ledger.jsonl \
  OAW_SOAK_LOOKBACK_HOURS=1 \
  scripts/ci/soak-accrual-bridge.sh

# Preview what WOULD accrue without writing:
SOAK_BRIDGE_DRY_RUN=true scripts/ci/soak-accrual-bridge.sh
```

The bridge runs `surgeon.py --live` for each session's health verdict + `oaw.profile`
label and `aoe list --json` for its `created_at` (the soak-span start), then hands the
running sessions to `soak_ledger.accrue`. dev-mode (R-22) and broken (§4.3) sessions
are excluded by `soak_ledger` — with a reason, never a silent drop.

**`OAW_SOAK_LOOKBACK_HOURS` (default 1) — set it to the accrual cron cadence.** The
surgeon's verdict is *point-in-time*: it certifies a session clean **now**, not across
its whole history. So each pass credits at most `LOOK_BACK` of soak, ending at the `now`
it just verified — the first pass does **not** back-credit a long-lived session's full
age, and a broken→recovered session does **not** get its dirty gap credited (soak is
*measured, never asserted* — R-07; *clean work only* — §4.3). The contract: run the
bridge **at least every `LOOK_BACK`**. `LOOK_BACK` must be **≥** the interval between
runs (a longer gap silently under-credits the uncovered clean time — the safe
direction), and should be **≈** the cadence (a value much larger than the interval
widens the residual dirty window a recovery pass can reach back over). Example: an
hourly cron ⇒ `OAW_SOAK_LOOKBACK_HOURS=1`.

**The live end-to-end cycle (soak → gate green → promote) is proven in the operator
field-run (MV-04/MV-06); the mapping + accrual are hermetically unit-tested.**

---

## 3. Promote (`:edge → :stable`) — §4.4

Promotion is a **mechanical conjunction** the operator can only *confirm*, never
override (PC-6, R-07). The gate is green only when **all four** are true:

- throwaway-CI E2E-01 **pass** on the candidate digest,
- dogfood **soak met**,
- **zero** quarantines,
- **zero** open Sev-1.

The decision lives in `promotion_gate.py`; the wrapper gathers the four signals
(FlightDeck telemetry + the CI result) and, on green **and** an operator ACK,
retags the **exact digest E2E-01 tested** `:edge → :stable` — no rebuild, same
bytes (R-23).

```bash
# 1) PLAN (default): evaluate the gate, print the verdict + the retag it WOULD do.
PROMOTE_DRY_RUN=true \
  IMAGE=ghcr.io/wave-engineering/oakandwave-workflow \
  GATE_SIGNALS_CMD='scripts/flightdeck/query-gate-signals.sh' \
  scripts/ci/promote-oakandwave-image.sh

# 2) APPLY (only after the plan shows GREEN — the ACK confirms, never substitutes):
PROMOTE_DRY_RUN=false PROMOTE_ACK=true \
  IMAGE=ghcr.io/wave-engineering/oakandwave-workflow \
  GATE_SIGNALS_CMD='scripts/flightdeck/query-gate-signals.sh' \
  scripts/ci/promote-oakandwave-image.sh
```

**Fail-closed:** any signal missing, unknown, or malformed is **RED**. A red gate
— or a green gate with no ACK — exits non-zero and retags nothing. The ACK is a
switch that only closes over an already-green circuit.

---

## 4. Fleet adoption — §4.5

The fleet adopts `:stable` **per-agent, at each agent's own container-recreate
boundary** — never mid-session, never a synchronized flip (R-08). The adoption
decision is unit-tested (`adoption.py`); the wrapper resolves the moving
`:stable` tag to its immutable digest + version and applies the plan.

```bash
# At an agent's recreate boundary (plan by default; ADOPT_DRY_RUN=false to apply):
STABLE_REF=ghcr.io/wave-engineering/oakandwave-workflow:stable \
  ADOPT_DRY_RUN=false scripts/ci/adopt-stable.sh
# emits the digest the NEXT `aoe add` / `docker run` should pin.
```

- **same-major minor/patch** → adopt (safe by same-major compat, R-18; an updated
  and a not-yet-updated agent coexist over one `~/.oaw/state/<major>/` namespace).
- **already current** → no-op (no redundant recreate).
- **major cross** → **held by default**; an opt-in, deliberate cross
  (`ALLOW_MAJOR_CROSS=true`), never automatic (§5.8).

A running container is pinned by digest, so a `:stable` retag can never reach it;
only the next recreate resolves the tag. The wrapper records the prior digest in
`~/.oaw/adoption/rollback` — rollback is a repoint (§7 below).

---

## 5. Quarantine + rollback a broken candidate — §4.6

When the surgeon classifies a **dogfood** `:edge` container broken, quarantine it:
stop → `docker rm` → recreate on `:stable`. Because all durable state is
host-backed, the rollback is **lossless** (R-02, R-17). A unit-tested planner
proves losslessness **before** the destructive `rm` runs: any durable RW state
not on a host-backed bind-mount is a **fail-loud refusal**, never a silent
data-losing `rm`.

```bash
# The surgeon emits the verdict; feed the broken container id to the wrapper.
# It PLANS by default (prints "N host-backed mount(s) preserved"); apply with the
# surgeon's should_quarantine verdict:
cid=$(docker ps --filter name=<session> --format '{{.ID}}')
CONTAINER_ID="$cid" SHOULD_QUARANTINE=true \
  OAW_STABLE_RESOLVED_REF=ghcr.io/wave-engineering/oakandwave-workflow:stable \
  scripts/ci/quarantine-container.sh
```

The wrapper stops + `docker rm`s the broken container (**without `-v`** — the
named/host volumes survive), recreates on `:stable`, and appends a record to
`~/.oaw/quarantine/ledger.jsonl`. That ledger entry is what makes the promotion
gate's **zero-quarantines** condition (§3) trip — the bad `:edge` digest is
**held from promotion** automatically:

```bash
tail -1 ~/.oaw/quarantine/ledger.jsonl   # {"event":"quarantine","held_digest":"…edge…",…}
```

**Confirm zero work lost** after recreate — the host-backed workspace/memory
survived the `rm`:

```bash
docker inspect --format '{{.Config.Image}}' \
  "$(docker ps --filter name=<session> --format '{{.ID}}')"   # -> …:stable
# the durable bind-mount content is unchanged on the host.
```

The full end-to-end quarantine walk-through, with the planted-break and the
zero-loss assertion, is **MV-05** in `manual-verification.md`.

---

## 6. Add a secret mid-session — §4.8

`~/.secrets` is bind-mounted **read-only** into every running container (R-12).
Because it is a host `bind` (not a copy), a file the operator adds mid-session is
**live** with no container restart (R-13):

```bash
# On the HOST — drop a new secret while the container keeps running:
printf 'live-add\n' > ~/.secrets/NEW_TOKEN
```

- **Path-modality** consumers (loose files) see it **immediately** — a
  newly-spawned in-container command reads it with no restart (this is the R-13
  guarantee; **MV-07** exercises it end-to-end).
- **Env-modality** consumers (a value in a `.env` sourced at boot) do **not** see
  a post-boot addition until that *process* re-sources — restart the process, not
  the container (§5.5 consumer split). Prefer file-path secrets for anything that
  may change mid-session.

A missing **required** secret fails the bootstrap **loudly** at boot (R-14) — it
never silently starts without it (`bootstrap.sh`).

---

## 7. Roll back a bad `:stable`

Promotion is a digest retag, so rollback is the same operation in reverse — repoint
`:stable` at the prior good digest. No rebuild.

```bash
# The prior good digest the fleet last adopted:
cat ~/.oaw/adoption/rollback        # <prior-good-digest>

# Repoint the moving :stable tag back onto it, then push the tag:
docker tag <prior-good-digest> ghcr.io/wave-engineering/oakandwave-workflow:stable
docker push ghcr.io/wave-engineering/oakandwave-workflow:stable
```

Agents pick up the rolled-back `:stable` at their **next** recreate (§4) — same
rolling, per-agent boundary as a forward adoption. Running containers are pinned
by digest and are untouched until they recreate. A **major-version** cross on
rollback is the same opt-in gate as a forward cross (§5.8); within a major it is
transparent.

---

## Quick reference

| I need to… | Command |
|------------|---------|
| Build `:edge` locally (no push) | `IMAGE=… PUSH=false scripts/ci/build-oakandwave-image.sh` |
| Verify the image toolchain | `make -C containers/oakandwave-workflow verify` |
| Cut the team onto `:edge` (plan) | `scripts/ci/dogfood-cutover.sh` |
| Cut the team onto `:edge` (apply) | `DOGFOOD_CUTOVER_APPLY=true scripts/ci/dogfood-cutover.sh` |
| Watch the dogfood ring | `python3 scripts/flight-surgeon/surgeon.py --live` |
| Accrue dogfood soak (bridge) | `scripts/ci/soak-accrual-bridge.sh` |
| Evaluate the promotion gate | `PROMOTE_DRY_RUN=true scripts/ci/promote-oakandwave-image.sh` |
| Promote (green + ACK) | `PROMOTE_DRY_RUN=false PROMOTE_ACK=true scripts/ci/promote-oakandwave-image.sh` |
| Adopt `:stable` at recreate | `ADOPT_DRY_RUN=false scripts/ci/adopt-stable.sh` |
| Quarantine a broken container | `CONTAINER_ID=… SHOULD_QUARANTINE=true scripts/ci/quarantine-container.sh` |
| Roll back a bad `:stable` | `docker tag <prior-digest> …:stable && docker push …:stable` |
