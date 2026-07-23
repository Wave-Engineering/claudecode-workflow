# oakandwave-workflow image

The OaW Claude Code kit, packaged as a **versioned container image** on the AoE
sandbox base. The image *digest is the release* (R-05): everything
versioned-with-the-release — skills, hooks, scripts, and the kit-dep toolchain —
is baked in, and nothing versioned is bind-mounted (R-06). Run the OaW dev team
in these containers (the **dogfood ring**) to prove a candidate before the wider
fleet adopts it.

Design authority: `docs/contained-workflow-devspec.md` (Plan #959). The full
lifecycle is built and landed — image + build system, me-ful isolation, the
five-layer mount manifest, the read-only secrets mount, the CI build/push/sign
pipeline, the throwaway-CI ring, the mechanical promotion gate, rolling per-agent
adoption, the flight surgeon + lossless quarantine, the SemVer compat guard, and
the dev-mode/dogfood profiles. The operator's day-to-day runbook is
`docs/contained-workflow/ops-runbook.md`.

## What's in the image

| Layer | Contents |
|-------|----------|
| Base | `ghcr.io/agent-of-empires/aoe-dev-sandbox:1.13.0` — Ubuntu 26.04, Rust / Python+uv / Node, uid-1000 `ubuntu` user |
| Kit-dep toolchain (added) | Go, trivy, shellcheck, shfmt, glab, bao (OpenBao), aws — installed system-wide in `/usr/local/bin`, pinned by `--build-arg` |
| Kit | `./install`-ed skills, scripts, hooks, and config for the uid-1000 user (`/home/ubuntu/.claude`, `/home/ubuntu/.local/bin`) |

The runtime user is **uid-1000 / non-root** (R-04); the me-ful ownership contract
(files land host-user-owned) is wired by the aoe `[sandbox]` config
(`sandbox-profile.toml`).

## Build

```bash
make -C containers/oakandwave-workflow build      # -> oakandwave-workflow:edge
```

`make build` derives every path from the Makefile's own location, so it behaves
identically from any working directory — CI or terminal (R-06). Override the base
or any tool version:

```bash
make -C containers/oakandwave-workflow build \
  BASE_IMAGE=ghcr.io/agent-of-empires/aoe-dev-sandbox:1.13.0 \
  GO_VERSION=1.24.5 TRIVY_VERSION=0.72.0
```

## Verify the toolchain

The named oracle (`tests/contained-workflow/test_image.py::test_image_toolchain`)
runs `docker run` against the built image and asserts every kit-dep tool resolves
and reports a version:

```bash
make -C containers/oakandwave-workflow test   # skips cleanly if the image isn't built
make -C containers/oakandwave-workflow ci     # build, then run the oracle for real
```

`make ci` sets `OAKANDWAVE_REQUIRE_IMAGE=1`, so a missing image is a hard failure
there while remaining a graceful skip in the stock `pytest tests/` lane (the
10 GB image is not present in that environment).

Ad-hoc smoke (Dev Spec §5.B):

```bash
make -C containers/oakandwave-workflow verify
# or directly:
docker run --rm --entrypoint sh oakandwave-workflow:edge \
  -c 'trivy --version && shellcheck --version && glab --version'
```

## Run an agent on the candidate

```bash
aoe add --sandbox --sandbox-image oakandwave-workflow:edge <workspace-path>
```

Host prerequisites (docker, aoe, `~/.secrets`, cephfs, uid mapping, ghcr auth)
are in `docs/contained-workflow/environment-prerequisites.md`.

## Rings & tags (context)

- `:edge` — the candidate under test. The **dogfood ring** (OaW dev-agents) and
  the **throwaway-CI ring** (install-from-zero smoke) prove it.
- `:stable` — the promoted digest the fleet pulls at container-recreate.

Promotion is a digest retag (`:edge → :stable`), never a rebuild — the digest
tested is the digest promoted (R-07/R-23). The build/push/sign pipeline
(`.github/workflows/oakandwave-workflow-image.yml`) and the throwaway-CI ring both
run in CI; the operator flow for building, dogfooding, and promoting a candidate
is `docs/contained-workflow/ops-runbook.md`.

## Fleet adoption

The fleet adopts `:stable` **per-agent, at container-recreate** — never
mid-session, never a synchronized flip (R-08). At *its own* recreate boundary an
agent runs `scripts/ci/adopt-stable.sh`, which resolves the moving `:stable` tag
to its immutable digest + version and asks the unit-tested decision module
(`adoption.py`) whether to adopt:

- **same-major minor/patch** → adopt at recreate (safe by same-major compat,
  R-18; an updated and a not-yet-updated agent coexist over one
  `~/.oaw/state/<major>/` namespace);
- **already current** → no-op (no redundant recreate);
- **major cross** → held by default — an opt-in, deliberate cross (§5.8), never
  automatic (`ALLOW_MAJOR_CROSS=true` opts in).

A running container is pinned by digest, so a `:stable` retag can never reach it;
only the next recreate resolves the tag. Rollback is a repoint at the prior digest
— the wrapper keeps it in `~/.oaw/adoption/rollback` (§5.6).

## Known deferrals

- **commutativity-probe (sdlc-server bundle) is not baked (best-effort).** The
  five kit MCP servers themselves ARE baked (R-09 baking half, delivered in
  #1013 — see below). sdlc-server additionally *bundles* a Python
  `commutativity-probe` CLI; its in-image install is best-effort and currently
  fails because the base `python3` ships without `pip`/`ensurepip`, so the venv
  fallback cannot build it. This does not affect the sdlc-server MCP — the
  `commutativity_verify` handler degrades gracefully to a `PROBE_UNAVAILABLE`
  verdict until the probe is provisioned at runtime. Baking the probe (e.g. a
  root-layer `ensurepip` or a prebuilt probe wheel) is a follow-up.

Delivered since the first cut of this image:

- **Kit MCP servers are now baked (R-09 baking half — #1013).** `./install` runs
  *without* `--no-mcps`: the kit MCP repos are all PUBLIC
  (`Wave-Engineering/mcp-server-{discord,discord-watcher,wtf,nerf,sdlc}`), each
  shipping a prebuilt linux-x64 release binary, so the install is hermetic over
  the public network — no build credentials, no operator step. All five servers
  land registered in the uid-1000 user's `~/.claude.json` `.mcpServers` with
  their binaries in `~/.local/bin`; the Dockerfile asserts this in-build and the
  image oracle re-asserts it (`test_image_kit_mcps_baked`). The *scoping* half —
  additive composition of third-party/user MCPs via the mount manifest + resolver
  (`mounts.d/`, `mount_resolver.py`) — was already delivered.
- **Base language runtimes exposed to the runtime user (#1013).** The base
  installs `claude`/`bun`/`node`/`uv` under `/root` (mode 700), unreachable by
  the uid-1000 user. A root layer now relocates them to `/usr/local/bin` (on PATH
  for every user) so the kit install can register MCP servers (`claude mcp add`)
  and any TS/Bun tooling resolves `bun`/`node`. `cargo`/`rustc` remain root-only
  (no kit component needs them); exposing them is a follow-up if that changes.
