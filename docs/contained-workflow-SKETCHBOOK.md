# Contained Workflow — Sketchbook

Design capture for running the OaW dev team inside AoE sandbox containers, so a
kit update can be **proved out by a team that runs it** before the wider fleet
upgrades — instead of a stop-the-world in-place install under live agents.

Status: **design dialogue, in progress** (BJ + babelfish, 2026-07-22). This file
is the pre-devspec sketch. The eventual Dev Spec supersedes it for execution;
this stays as rationale.

---

## Why this exists

The 2026-07-19/20 fleet upgrade was a nightmare, and it had one root cause:
**`./install` writes a shared `~/.claude`, and every agent on the box reads from
that same tree.** There is no boundary between "the kit I'm testing" and "the kit
the fleet is running." Consequences that night: `./install` run twice under 15
live agents on a false "drained" reading → six watchers on deleted inodes; the
install **clobbered the live Discord token** (wrote `<your-token-here>` over it);
a dangling `~/.claude/mcp.json` registration.

You cannot test a kit update without mutating the state the live fleet depends
on. That is the disease. A container is the cleanest place to put the boundary,
and — proven below — AoE's sandbox draws that boundary exactly where the disease
is: the container is handed `~/.claude/sandbox`, never the live `~/.claude`.

Secondary win the container also buys: it **pins the system toolchain**. Half of
that night's sharpest bugs were un-versioned tool drift (`gh 2.45.0` lacking
`pr checks --json` and `pr update-branch`). An image versions the toolchain.

---

## What we are building

`oakandwave-workflow:<semver>` — an image `FROM ghcr.io/agent-of-empires/aoe-dev-sandbox:<pinned>`
with the OaW kit's missing deps and the kit itself baked in. **The image tag /
digest IS the release**, and promotion is a digest retag:

```
build  oakandwave-workflow:8.0.0   (8.0.0 kit baked in)
   OaW dogfoods it on :edge
   clean per a mechanical gate  →  retag that digest  →  :stable
   fleet pulls :stable
```

A bad kit is `docker rm` + repoint at the prior stable digest. Blast radius:
one container, not the fleet.

---

## Decisions (locked in dialogue)

**D1 — Isolation via AoE per-session sandbox containers.** One container per
session (`aoe add --sandbox`). This cures the shared-`~/.claude` disease not just
ring-vs-fleet but agent-vs-agent. *Observed (default `aoe --sandbox`, one test):*
the sandbox mounts `~/.claude/sandbox` (rw) as the container's `/root/.claude` —
the live `~/.claude` was **not** exposed. This scopes to the default invocation;
the design then adds custom host→container mounts (D4 memory, D6 `~/.secrets`, D10
caches, D4a MCP fragment) whose interaction with isolation is **UNPROVEN** — "the
isolation holds under the full custom mount set" is an explicit next-probe, not an
established fact.

**D2 — The image is the release.** Everything versioned with a kit release is
baked into the image at build time via `./install`. Two image tags (8.0.0 vs
8.1.0) therefore carry different `skills/`, `hooks`, `scripts` — self-contained,
no collision.

**D3 — "me-ful", not rootful.** The container runs as **uid 1000 (bakerb)**, not
root, so files written to bind-mounts land `bakerb`-owned. Lever: AoE's
`[sandbox] uid` / `user` / `home_dir` config. The base image already ships a
uid-1000 user (`ubuntu`); we **reuse/rename that uid** rather than add a second
user at 1000 — ownership works by uid regardless of name. No root writing your
home, no daemon reconfiguration; rootless podman is a fallback we do not need.

**D4 — State taxonomy (the spine).** Every piece of `~/.claude` files onto one of
these axes (extended by the fourth in D4a), and that axis decides how it enters the
container:

| axis | examples | mechanism |
|---|---|---|
| versioned-with-the-release | skills, hook scripts | **baked in the image** (immutable per tag) |
| shared-mutable-across-releases | `projects/*/memory/` | **bind-mount rw** from a **sandbox-scoped host path** (see below) |
| never-persisted | Discord/GH tokens | **ro-mounted, sourced at boot** (never baked) |

**⚠️ The rw memory mount's host source MUST be sandbox-scoped — never the live
fleet tree.** The bidirectional `projects/*/memory/` mount is the one rw seam into
durable state; if an implementer points it at the live `~/.claude/projects/*/memory/`,
a broken `:edge` candidate gains write access to the live fleet's memory — the exact
shared-mutable-with-live-fleet disease this whole design exists to cure, reintroduced
at the single rw seam. The host source is a **sandbox/`~/.oaw/state/<major>/…` path**
(consistent with F3's major-partitioned namespace), and it is *never* the live-fleet
tree. This reconciles with D1: "the live `~/.claude` is not exposed" only holds if
this mount obeys that rule.

`settings.json` straddles, so it is **split**: the image ships `settings.json`
(hook wiring — versioned, because hook registrations point at script paths that
live in the image), and a bind-mount provides `settings.local.json`
(permissions / env / identity — the genuinely shared knobs). Claude Code merges
the two.

**D4a — the fourth axis: the user-environment overlay.** Beyond ours-versioned /
ours-shared / never-persisted there is the **user's own environment** — their MCP
servers, their non-kit CLIs, their discretionary dev tools. This axis matters most
because **adopters of the kit bring their own** — the kit ships an *extensible
base*, not a closed environment. Three mechanisms, by artifact type:

- **Config & scripts** (MCP fragments, dotfiles, `~/.local/bin` shebang scripts) —
  symlink-sync / bind-mount. Portable across the boundary. (`chezmoi` is already in
  use — the existing durable-config answer, and a hint at the manifest model.)
- **Compiled binaries** (third-party ELF) — **installed *in* the container** to a
  durable bind-mounted dir. **Never symlinked host→container**: a host ELF binary
  linked into a differently-built container fails on libc/`.so`/interpreter
  mismatch. Measured: `~/.local/bin` is 154 shebang-scripts (symlink-safe) + 26 ELF
  (hazard); the 26 split into ours (baked) and third-party (install-in-container).
- **Discretionary dev tools** — a **declarative manifest** (`mise` / `nix` /
  apt-list; `uv`, `pre-commit` already present) that an in-container installer
  materializes into a durable `~/.oaw/toolbox`. Decoupled from kit releases
  (updating `ripgrep` is not a kit release), reproducible on a fresh box, user-owned.

**MCP config splits like `settings.json`.** Ours (`disc-server`, `sdlc-server` …)
bake into the image — version-coupled, and baking them **kills the dangling-
registration bug** (a stale path pointing at a moved binary — the watcher
`mcp.json` incident) because the image path is stable. Third-party + user MCPs
(kapture, context7, mermaid, atlassian) **compose via the additive scoping already
governed by `docs/mcp-scoping.md`**, bind-mounted as a *fragment* — never the whole
`~/.claude.json`, which carries far more than MCP config.

**PATH precedence:** kit binaries (image) win over the user overlay, to keep the
RTE authoritative (the same digest=behavior rule as D5).

**D5 — Skills symlink-sync is an OPT-IN DEV MODE, off in the dogfood/promotion
ring.** Mechanic (`startup → sync → run`): mount host `~/.oaw/.claude/skills` at a
shadow path; the boot script runs, per entry, `ln -s <full-target>`
(non-forcing) into `~/.claude/skills`. Non-forcing = **image wins, host fills
gaps**, and host edits to gap-fillers track live. But live host overrides mean the
digest no longer uniquely determines behavior — which breaks the promotion gate —
so this is **off by default**; a true dogfood runs image-only skills, and dev-
iterate mode is a boot flag. Requirements when on: fix the loop to use the full
target path (bare basename self-references); **log every collision** (a silently
shadowed host skill is the night's own "did nothing, said nothing" defect);
tolerate an absent mount without dangling links.

**D6 — Secrets: ro bind-mount of the whole `~/.secrets` DIR (not just `.env`).**
*Proven (tested):* a directory bind-mount is **live** — a file the host adds mid-run
appears in the running container immediately, readable, no restart; ro blocks the
container from writing while the host keeps rw. *Asserted (correct Docker behavior,
not separately tested here):* mounting the *directory* (not the `.env` file) also
fixes live `.env` edits (a single-file mount pins the inode; editor save-rename
would strand the container on the stale copy), and the env-vs-file consumer
distinction below. Consumer split:
**file-path consumers** (`--token-file`, `cat`-on-demand) are fully live;
**env-var consumers** get new commands live but an already-running daemon needs
*that process* restarted (whole-container-restart → at most one-process-restart,
often zero). **Prefer file-path consumption where a tool supports it** — it makes
the touchiest credentials the easiest to rotate. `.env` (env modality) vs loose
files (path modality) are a deliberate per-consumer choice, not redundancy; do
**not** auto-export loose files to env (re-leaks via `/proc/<pid>/environ`).
Hygiene: dir 700, files 600, gitignored fleet-wide, never in an image layer, a
**values-free manifest** of what belongs there, and **fail loud at boot** on any
required secret missing. **Blast-radius tradeoff (open):** mounting the *whole*
directory means every sandbox sees *every* client's credentials — including material
across the GitLab/GitHub IP boundary (Analogic-proprietary vs OaW). The whole-dir
mount is chosen for the inode/liveness reasons above; **least-privilege scoping of
which secrets a given ring gets is not yet designed** and should be, before this
carries real client material.

**D7 — The bootstrap script is the load-bearing instrument.** Skills-sync,
`settings.local`, memory mount, secret sourcing, env validation all hang off one
container bootstrap that runs before the agent. It must be built with the
assertion-liveness discipline from line one: **every silent-skip becomes a logged
or failing condition** (missing mount, missing secret, shadowed skill, dangling
link). Anything less hand-crafts a fresh generation of "the check that reported
fine and did nothing."

**D8 — Two rings.** The **dogfood** ring (persistent, real-workload canary — the
OaW team working on the *next* kit while running the current candidate) and a
**throwaway CI** ring (installs the kit from zero, runs a smoke suite, dies —
proving install-from-nothing + reproducibility). Different jobs; that night needed
both, and the install-from-nothing case is exactly what nobody tested before
going live.

**D9 — Durable, declarative dev-tool install (the `~/.oaw/toolbox`).** The status
quo — `~/.local/bin` with 198 entries, `.bak` cruft, `aoe-1.11.2`/`1.11.3`/`aoe`
side by side, a Python/ML stack tangled with kit binaries — is **unreproducible**:
no manifest, no provenance, no way to rebuild it on a fresh box. The container
forces the reckoning the junk drawer let us dodge. The durable answer is the
inverse of accretion: a **declarative tool manifest** materialized by an
in-container installer into a **persistent bind-mounted `~/.oaw/toolbox`** on
PATH — reproducible, user-owned, and decoupled from the kit release. This is not
only a container need; it hands every kit adopter a dev environment they can
rebuild from a manifest.

**D10 — Durable caches (bind-mounted, unversioned, performance).** Distinct from
the toolbox (which holds *tools you install*): this holds *artifacts you don't want
to re-fetch per container spin-up*. Bind-mount, shared across containers:
- Rust `CARGO_HOME` (registry + git), Go `GOMODCACHE`, Python `~/.cache/uv`.
- Playwright browsers (~1 GB) at `~/.cache/ms-playwright` — CLI in the image,
  browsers installed once into the cache.
Rule: share **download** caches freely (pure fetches, safe); share **build**
caches (`target/`, `GOCACHE`) only with care — toolchain/arch-sensitive, corrupt
across mismatched images.

### Tool manifests (settled so far)

**Image — kit hard-deps** (RTE breaks without them): `trivy`, `shellcheck`,
`shfmt`, `glab` (dual-platform; also gives `glab ci lint` for `.gitlab-ci.yml` —
no separate linter needed). *Base already ships:* git, gh, node, bun, npm, jq,
python3+uv, ripgrep, curl, claude, **Rust**.

**Image — near-universal / OaW-regular**: `yamllint`, `pre-commit`, `bao` CLI
(client work — a tool, NOT our secrets backend; D6 unchanged), `aws` CLI,
**Go** (missing from base — add it).

**Toolbox (D9), not the image**: `kubectl`, `ansible`+`ansible-lint`, and
(build-pipeline, not runtime) `cosign` / `syft` / `oras` — used to sign + SBOM the
*image itself*, so they belong in the image-**build** stage, not baked into the
runtime.

**Dropped** (BJ, explicit): keycloak CLI (`kc`) and VS Code attach — neither
earns a place; VS Code is human ergonomics, not the agent RTE.

**Credentials for all client-work CLIs** (bao token, `~/.aws`, keycloak admin)
flow through **D6** — the tools are cheap, their credentials are the integration.

---

## Rationale notes

- **Promotion is only real if axis-1 is truly immutable in the ring.** "The digest
  is the release" holds only when skills/hooks can't be live-overridden — hence D5
  being off by default. The taxonomy is the design; the bootstrap is its enforcement.
- **The container retires an incident, not just a risk.** Tonight's token clobber
  happened because the token lived *inline* in `~/.claude.json`, which an installer
  rewrote. Under D6 secrets live only in `~/.secrets`, mounted **read-only**, and
  nothing installs there — the clobber becomes structurally impossible.
- **Fidelity cuts both ways.** The base image's `gh 2.96` is *newer* than the
  fleet's `2.45` — so container-proven ≠ fleet-safe on a 2.45-specific bug, BUT
  2.96 ships the fix for the exact gaps (#925 inert `/mmr` gate, #946/#951 no
  `pr update-branch`) we worked around all night. If the image's toolchain becomes
  the fleet target, containerizing incidentally retires a bug class. (Open decision.)

---

## Verified ledger (proven-by-test vs asserted)

**PROVEN this session (method noted):**
- **Network egress** — from a default-network container: `scream-hole…/health`,
  `discord.com/api/v10/gateway`, `api.github.com`, `github.com` all **200**;
  `ghcr.io/v2/` **401** (reachable, unauth — correct, not a fault). The one thing
  the AoE guide left undocumented; it was the make-or-break and it's green.
- **Image extend** — `oaw-kit:spike = aoe-dev-sandbox:1.13.0 + shellcheck + shfmt
  v3.13.1 + trivy 0.72.0`, builds clean, +180 MB.
- **Isolation** — `aoe --sandbox` mounts `~/.claude/**sandbox**` (rw) as
  `/root/.claude`, `.gitconfig` (ro), scratch + artifacts/hooks dirs. Live
  `~/.claude` **not** exposed.
- **User** — rootful docker, in-container uid=0 = host root; root-owned files
  land in `~/.claude/sandbox` (the papercut D3 fixes).
- **Secrets liveness** — dir bind-mount ro: host-added file appears live in the
  running container and is readable; container write → "Read-only file system",
  host write allowed.

**CAPABILITY-CONFIRMED (binary string table; exact syntax/behavior untested):**
- AoE `[sandbox]` keys: `user`, `uid`, `home_dir`, `mounts`, `volumes`,
  `mount_ssh`, `keep_container`, `environment`, `volume_ignores`,
  `default_image`, `enabled_by_default`.
- Default image `ghcr.io/agent-of-empires/aoe-dev-sandbox:1.13.0` — **registry-
  authoritative** (tracks the aoe binary version); base has a uid-1000 `ubuntu` user.

**UNPROVEN / next probes:**
- Exact `[sandbox]` TOML syntax and the me-ful **ownership outcome** (test: set
  `uid`, write a file, confirm `bakerb`-owned) — in an **isolated aoe profile**,
  never the fleet's global config.
- Kit `./install` into the image (needs a GH token — private repo).
- Discord **delivery** via a containerized disc-server (needs a token / test
  channel — not the live fleet token in a spike).
- `aoe send` reaching **into** the container (control-plane ingress).
- `git push` escaping.
- The **bootstrap seam**: `aoe --sandbox` mounts `/tmp/aoe-hooks-<uid>/<id>` — an
  apparent native container-hooks mechanism; may be where the bootstrap belongs.
  Open: does aoe respect the image `ENTRYPOINT` or `docker exec` claude directly?
- **F1 keystone (untested assumption):** F1's health probe rests on "the `.jsonl`
  transcript is written by Claude Code — the harness, below the kit — so a broken
  skill/hook cannot stop it." Probably true, but it is the keystone of the whole
  probe and is currently *asserted*. Probe: does a wedged / OOM-killed `claude`
  still flush the transcript at the failure boundary, or can the failure that breaks
  the agent also swallow the last turns the surgeon relies on?
- **Isolation under the custom mount set** — the D1 "not exposed" result was one
  default-`--sandbox` observation; confirm it holds once D4 memory / D6 `~/.secrets`
  / D10 caches / D4a MCP mounts are all present.

---

## Open decisions (BJ)

1. **Toolchain: pin-to-fleet vs move-fleet-to-image.** Pin the image's `gh` to the
   fleet's 2.45, or adopt 2.96 as the target and roll the fleet up behind the
   validated ring? (babelfish recommends move-to-2.96 — it ships the fix for
   #925/#946/#951.) Not blocking the spike; lands at productionization.
2. **Credential injection** for the remaining spike proofs — GH token mount for
   install/push; a scoped **test** Discord token/channel for delivery rather than
   the live fleet token in a throwaway container.
3. **Who watches the watcher — RESOLVED by Float 1 (health-probe half).** The
   out-of-band probe is the transcript "flight surgeon" (see Resolved §F1): a
   host-side watcher reading each `:edge` container's host-backed `.jsonl` directly.
   Residual: the keystone assumption (harness writes the transcript below the kit)
   is an untested probe — see the Verified ledger's UNPROVEN list.
4. **Agent portability & the repo name.** "claudecode-workflow" is tight — the
   value (wave pattern, SDLC gates, MCP core) is agent-agnostic, and the image is
   already named `oakandwave-workflow`. AoE itself is multi-agent (ships `claude` +
   `opencode`, ACP-threaded). The MCP-over-skill architecture already makes a port
   cheap: MCP servers + bash scripts are portable; skills, hook *wiring*, config
   paths, `CLAUDE.md`→`AGENTS.md` need real porting (translation, not path swaps).
   Caveat: plumbing-portability ≠ execution-quality — a small local **qwen** will
   connect but underperform on the judgment-heavy parts (review, wave gates).
   Recommendation: architect a portable MCP core + thin per-runtime adapters, spike
   a real opencode+qwen adapter to *measure* the coupling, rename on proof not spec.
5. **BJ's floats** — _(placeholder; a couple of things BJ wants to raise)_

### Resolved during float review

**Float 1 (escape-hatch half) — RESOLVED (stateless-container invariant).**
- **Decision:** adopt the top-level invariant — **the container filesystem is a
  disposable RTE; every durable byte lives on a host-backed mount.** Then `docker rm`
  on a broken `:edge` container loses nothing.
- **Rationale (BJ's Option B beats Option A):** extracting work *before* killing the
  container depends on the broken container cooperating — fragile in exactly the F1
  scenario. Host-backing the durable surface means the work was never trapped; no
  rescue needed. Structural beats heroic — same principle as the health probe (don't
  depend on the broken thing to save itself).
- **Already true, mostly:** AoE host-backs the workspace (`…/scratch/<id>` →
  `/workspace`, and worktrees live on the host); `~/.claude/sandbox` and memory are
  host-backed too. We are hardening an existing property.
- **Work item:** audit the *durable surface* — anything written outside the mounts
  (`/tmp`, `/root`, build artifacts) is at risk. Define where durable output goes and
  keep it inside the mounts. (Same shape as F3's "define the surface.")
- **Layering:** host-backed mount survives *container* death; `git push` survives
  *host* death. Dogfood ring: host-backed is the operative tier.
**Float 1 (health-probe half) — RESOLVED (transcript flight surgeon).**
- **Key move:** the `.jsonl` transcript is written by **Claude Code itself — the
  harness, below the kit** — so a broken skill/hook *cannot* stop it being written,
  and (per the stateless invariant) it lives on a host-backed mount. A **host-side
  watcher** (running `:stable` or bare) reads each `:edge` container's transcript
  *directly off the host* — the tested cannot blind the tester.
- **Correlated signals (all host-side, kit-independent):** container/`claude`
  liveness + CPU; transcript growth cross-referenced with **aoe's own status**
  (running/waiting/idle — aoe already tracks it). `status=running` + transcript flat
  for N min = hung; `waiting/idle` = legitimately paused. On "broken": alert +
  **quarantine** the container — stop it from producing more (bad) work and trigger
  the now-lossless escape hatch (`docker rm` + recreate on `:stable`, per the
  stateless invariant). *("Quarantine" = this stop-and-roll-back action; used by F2
  and F4 below.)*
- **Residual (implementation):** transcript-flat catches a *hung* agent; a *looping*
  agent grows the transcript repetitively → needs a cheap loop heuristic (same tool
  K times / no forward progress for N turns). Stall detection is free; loop is a small
  add.
- **Reuses:** the stateless invariant (host-backed transcript) + FlightDeck (#854) as
  the dashboard.

**Float 2 — RESOLVED (mechanical gate + rolling adoption).**
- **Promotion trigger** is a *conjunction* of mechanical conditions, all already
  emitted by the ring: throwaway-CI (D8) green on the digest · N-session/M-day soak
  in the dogfood ring · zero F1 quarantines during soak · zero open Sev-1 kit-caused
  incidents. **THEN** an optional human final-ACK that can only fire *after* the gate
  is green — it confirms green, never replaces it. ("Sounded right to four of us"
  can't promote.) The gate is a **query over FlightDeck + the CI result**, not new
  instrumentation.
- **Distribution:** minor/patch `:stable` → agents auto-adopt on next session
  (rolling, per-agent), safe by F3's same-major compat; rollback = repoint prior
  digest (lossless). Major → opt-in, deliberate cross, separate state namespace.
- **Sidesteps #937:** a new `:stable` takes effect at *container-recreate* (a restart
  boundary), never mid-session — so the hardest part of #937 (mutating a *live*
  agent) does not arise.
- **Residual (policy):** the soak thresholds (N, M) are knobs, not design gaps.

**Float 4 — RESOLVED (two profiles, gate trusts only the pure one).**
- **`dev-mode` profile:** D5 overlay ON — live-edit kit source, see it instantly.
  Labeled NON-CANDIDATE, **excluded from promotion telemetry**.
- **`dogfood` profile:** overlay OFF, image-only, digest = behavior. Feeds the gate.
- **Critical wiring:** F1 and F2 filter on the profile label — a dev-mode container's
  runs never count toward soak and its breakage never trips a quarantine (you're
  *supposed* to be breaking it). The boundary between iterating and proving is the
  moment a change is built into `:edge`.


**Float 3 — shared-state compatibility → RESOLVED (SemVer contract).**
- **Contract (BJ):** users are developers; mixing kit versions is safe **within the
  same MAJOR**. Any change that endangers/breaks compatibility with prior agents →
  **bump the MAJOR**. The developer decides when to cross a major.
- **Payoff:** *decouples the fleet* — per-agent rolling recovery instead of
  stop-the-world. Direct fix for the 2026-07-19/20 scramble, where one break blocked
  every agent because all shared one `~/.claude` / one version. Run a mix of
  containers; clear each agent's blocker and move that agent along independently.
- **Refinements (babelfish):**
  - *Keep the promise mechanically — the POLICY is resolved, the ENFORCEMENT is
    still design-open.* The SemVer policy (above) is settled. But mechanically
    **detecting a semantic compat break** in a shared-mutable format — so a
    breaking change can't ship silently under a minor — is the hard, unsolved part,
    and it is exactly the "check that must actually do the thing" class this repo
    keeps getting burned by. Sketch: version the shared-state schema and gate on a
    schema-hash/field change; but a field's *meaning* changing without its shape
    changing would slip that. **Treat enforcement as a design-open work item for the
    Dev Spec**, not folded into RESOLVED — else the resolution inherits the
    silent-ship risk it claims to fix.
  - *Define the surface* — the contract covers the *formats* of exactly the D4
    bind-mounted shared-mutable files (memory, `settings.local`, …). Baked-image
    state is per-version by definition, out of scope.
  - *Major partitions the state namespace* (`~/.oaw/state/v8` vs `v9`) — mixing
    majors is **isolated (safe)**, not shared (corrupting). "Up to them" = accept
    partitioned state.
  - *Within a major* — shared-state changes must be **additive + forward-tolerant**
    (readers ignore unknown fields); minors mix in both directions.
  - *Feeds Float 2* — mixed-minor safety makes promotion a rolling per-agent adoption
    and defuses the auto-pull blast-radius **within a major**.

---

## Corrections log (kept for honesty)

- **Image name**, three sources three answers: doc said `aoe-sandbox:latest`;
  `strings` on the binary said `aoe-dev-sandbox:0.10` (a **string-adjacency**
  artifact — org from one image, tag from the `njbrake/*` namespace); the
  **registry** (authority) said `:1.13.0`. Two "verified" sources were wrong.
- **False gates I set and retracted:** the toolchain decision "blocking" the spike
  (it only blocks productionization); a "non-PR path to main" (branch protection
  forbids it); "sandbox sessions never age out" (the deck's closed lane already
  handles it). Twice I confirmed an instrument was broken, then asserted a
  consequence without checking it was reachable.

---

## Next move

Finish the spike's remaining proofs (gated on decision #2), map the aoe-hooks
seam, run the me-ful ownership test in an isolated profile — then turn this into a
`/devspec`. The design above is enough of a spine to formalize once BJ's floats
and the three open decisions land.
