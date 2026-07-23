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

- **Kit MCP servers are not yet baked (open).** `./install` still runs with
  `--no-mcps` (Dockerfile): the kit's MCP servers install from private
  `Wave-Engineering/*` repos over the network, which is non-hermetic and needs
  build-time credentials. The *scoping* half of R-09 is delivered — the mount
  manifest + resolver and the additive composition of third-party/user MCPs
  (`mounts.d/`, `mount_resolver.py`). *Baking* the kit's own MCP registrations at
  stable image paths (the other half of R-09) was slated to ride with the CI
  build (#966) where private-repo credentials are in play, but the image build
  does not yet do it — this half remains open (VRTM R-09 row records it). The
  resolver already documents the stable baked image paths those registrations
  target.
- **Root-scoped base runtimes.** The base installs `bun`/`node`/`uv`/`cargo`
  under `/root`, which the uid-1000 user cannot reach. The baked kit (skills,
  scripts, hooks) needs only `python3` + the system toolchain, so this does not
  affect the kit at runtime; exposing those base runtimes to the runtime user is
  a follow-up if a kit component ever needs them directly.
