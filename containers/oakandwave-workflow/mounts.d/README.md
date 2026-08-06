# `mounts.d/` — the mount manifest

Declarative, drop-in manifest for the container's **run-layer** mounts (Dev Spec
§5.3, Story 1.3 #963). The container filesystem is a disposable RTE; every piece
of durable state enters through a mount declared here. `../mount_resolver.py`
loads these fragments, substitutes `<major>` and `~`, enforces the mount
contract, and emits `docker -v` / aoe `extra_volumes` specs for the bootstrap
(Story 1.4).

## Ordering

Fragments apply in **lexical filename order** — the `NN-name.toml` prefix slots a
fragment deterministically. Each file holds one or more `[[mount]]` tables.

## Entry schema

| key | required | values | meaning |
|-----|----------|--------|---------|
| `name` | yes | string | mount identifier |
| `layer` | yes | `shared-mutable-rw` \| `read-only-secrets` \| `user-overlay` \| `durable-cache` | which of the four run-layers (§5.3) |
| `mode` | yes | `rw` \| `ro` | bind-mount mode |
| `source` | yes | path | host source; `<major>` and `~` are substituted |
| `target` | yes | path | container mount point |
| `sandbox_scoped` | no | bool | opt a mount into the R-03 sandbox-scoped guard (implicit for `shared-mutable-rw`) |
| `artifact` | user-overlay only | `compiled-binary` \| `script` \| `config` \| `mcp-fragment` \| `toolbox` | classifies the overlay artifact (drives the install mechanism, R-10/R-11) |
| `install` | no | `in-container` \| `symlink` \| `additive` | install mechanism; defaults from `artifact`, and a mismatch is rejected |
| `compose` | mcp-fragment | `additive` | MCP fragments compose additively, never whole-file (R-09) |
| `env` | no | table | env vars this mount implies (e.g. `CARGO_HOME`) |

## Guards (each fails loud — see `../mount_resolver.py`)

- **R-03** — a `shared-mutable-rw` (or `sandbox_scoped`) source must resolve under
  `~/.oaw/state/<major>/` and **never** inside the live-fleet `~/.claude` tree.
- **R-10** — a `compiled-binary` overlay artifact installs `in-container`, never
  `symlink` (host ELF fails on the libc boundary); scripts/config symlink.
- **R-09 / R-11** — an `mcp-fragment` composes `additive` and is never the whole
  `~/.claude.json`; the `toolbox` is a durable in-container-materialized mount.

## Fragments here

| file | layer | owner story |
|------|-------|-------------|
| `05-transcripts.toml` | shared-mutable-rw (session transcripts) | #1064 |
| `10-memory.toml` | shared-mutable-rw (memory) | 1.3 (#963), #1086 |
| `20-secrets.toml` | read-only-secrets (ro named single-file mounts) | 1.5 (#965), #1061 |
| `30-user-overlay.toml` | user-overlay (MCP fragment, toolbox, user scripts) | 1.3 (#963) |
| `40-durable-caches.toml` | durable-cache (cargo, go-mod, uv, ms-playwright) | 1.3 (#963) |
| `50-vox-spool.toml` | shared-mutable-rw (text forwarded to the host's `vox`) | #1084 |

> **These fragments are INERT until copied into an AoE profile.** `extra_volumes`
> is a manual copy of `mount_resolver.py --format aoe`, so the container runs on
> whatever was last pasted — a fresh profile has `[0 items]` and every mount here
> applies to nothing, silently. `scripts/ci/check-mount-drift.sh <profile>` diffs
> the two and also stats every host source (an absent one is materialised by
> Docker as an empty directory rather than erroring). It runs from
> `dogfood-cutover.sh` — advisory on the plan path, fatal on apply (#1069).

`20-secrets.toml` was a drop-in for Story 1.3's resolver: the
`read-only-secrets` layer and its `mode = "ro"` enforcement (R-12) already
existed, so Story 1.5 added only the fragment (no resolver change). #1061 then
replaced the whole-dir mount with **named single-file** mounts, so a container
sees only the secrets it declares; an in-place rewrite is live mid-session, an
atomic replace is not (inode binding) — see `architecture.md` §3.5.
