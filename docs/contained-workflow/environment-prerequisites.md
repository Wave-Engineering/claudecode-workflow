# Environment prerequisites — contained workflow

Host/platform requirements to **build** the `oakandwave-workflow` image and
**run** an agent in it. Deliverable DM-13 (Plan #959, Dev Spec §5.A).

This is the host contract. The image itself is portable and carries no OaW-org
specifics (PC-3) — org infrastructure (cephfs, secrets) is a run-layer overlay,
never baked into a layer.

## Host tooling

| Requirement | Why | Notes |
|-------------|-----|-------|
| **Docker** (rootful, no userns remap) | Build and run the image | In-container root == host root (TC-2). "me-ful" therefore needs the uid-1000 user *and* the aoe `[sandbox] uid` config, not just one. |
| **aoe 1.13.0** | Per-session sandbox launch (`aoe add --sandbox`) | The image base tag tracks this exact aoe version. The sandbox model is one-container-per-session (TC-1). |
| **make**, **python3** | `make build` / `make test`; the toolchain oracle | python3 also drives the kit's zipapp package builds during `./install`. |
| **ghcr.io auth** | Pull the base image | The base `ghcr.io/agent-of-empires/aoe-dev-sandbox:1.13.0` (~9.9 GB) requires a token (TC-5). `docker login ghcr.io` before the first build. |
| Network egress on the default bridge | Fetch pinned toolchain release archives at build time; runtime egress to scream-hole / discord / `api.github.com` | Proven reachable on the default bridge (TC-5). |

## Host-backed state (run layer)

The container filesystem is a **disposable RTE** — all durable state lives on
host-backed mounts, so a broken candidate is `docker rm`, not an incident (R-01).
These are provided at run time (later waves wire the full mount manifest); the
image does not require them to build.

| Host path | Mount | Purpose |
|-----------|-------|---------|
| `~/.oaw/state/<major>/` | rw | Sandbox-scoped memory — **never** the live-fleet `~/.claude/projects/*/memory/` (R-03). The major partitions the namespace so mixing majors is isolated (R-20). |
| `~/.secrets` | **read-only** | Secrets are never baked into image layers (R-12); provided only via this mount, and live-addable mid-session (R-13). Fail loud at boot on a missing required secret (R-14). |
| `/mnt/cephfs` | bind (host's already-mounted path) | Org infrastructure. Containers bind-mount the host's mount; they never mount ceph directly (the admin key stays on the host) (TC-6). |
| `CARGO_HOME`, `GOMODCACHE`, `~/.cache/uv`, `~/.cache/ms-playwright` | rw | Durable caches (Dev Spec §5.3). |

## Identity / uid mapping

- The image ships and defaults to the base's **uid-1000 `ubuntu`** user; the kit
  is installed under `/home/ubuntu` (R-04, TC-2).
- Because docker here is rootful with no userns remap, bind-mount writes are
  owned by whatever uid the container runs as. The operator sets `[sandbox] uid`
  (and `user` / `home_dir`) in an **isolated** aoe profile so writes land
  host-user-owned (`bakerb`) — verified in Story 1.2 (MV-01). Never edit the
  fleet's global aoe config to test this.

## Not required to build

- CephFS, `~/.secrets`, and `~/.oaw/state` are **run-time** concerns; the image
  builds without them.
- The kit's MCP servers are **not** baked in this story (`./install --no-mcps`) —
  see the image README "Deferred". No MCP credentials are needed to build.
