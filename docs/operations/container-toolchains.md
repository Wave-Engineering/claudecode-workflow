# Giving a containerised agent a toolchain

The image ships **no build toolchain** — no JDK, no Maven, no Node runtime beyond
what the kit itself needs. That is deliberate (R-11): baking a JDK would put a
Java toolchain in every agent that never touches Java, and bumping Maven would
become a kit release.

Instead the image bakes **`mise`**, and toolchains are materialised on demand
into a durable mount that survives container recreation.

## The fast answer

**Per repo** — commit a `mise.toml` at the repo root:

```toml
[tools]
java = "temurin-17"
maven = "3.9"
```

That is all. mise's shims are on the image `PATH`, and they resolve the version
from the current directory's config at exec time — so `mvn -v` works inside that
workspace with no bootstrap step, no shell rc, and nothing installed by hand.
Tools are downloaded on first use into `~/.oaw/toolbox/mise`, which is a durable
mount: the next container gets them already there.

**Per profile** — for something every agent on a profile should have, put the
same file at `~/.oaw/toolbox/mise.toml` on the host. `bootstrap.sh` installs it
at boot, on every agent start. A satisfied manifest is a fast no-op.

## Checking it worked

Ask the way an agent asks — a **non-interactive** shell:

```bash
docker exec -u ubuntu <container> sh -lc 'mvn -v'
```

Not an interactive shell, and not after sourcing anything. Non-interactive shells
never read `~/.bashrc`, so a check that passes only in an interactive session is
testing the wrong thing — that exact gap is why this issue was filed.

## What happens when it cannot install

Nothing fatal. Bootstrap **warns and continues**, and mise's own diagnosis is
printed rather than swallowed:

```
[bootstrap] WARN: toolbox: mise install failed (rc=1) — the agent still starts, toolchains may be missing
[bootstrap] WARN:   mise: failed to resolve host mise-versions.jdx.dev
```

A container with no Maven is bad; a container with no agent is worse. The wrapper
sources bootstrap and then execs the agent, so a fatal here would mean no agent.

## Caches

`~/.m2` is a **durable-cache** mount (`40-durable-caches.toml`), alongside cargo,
go-mod, uv and playwright. The toolbox holds the toolchain; the cache holds what
the toolchain downloads. Without it a cold `mvn` re-fetches the whole dependency
tree every session.

Adding a mount changes the resolved volume set, so profile `extra_volumes` need
regenerating — `scripts/ci/check-mount-drift.sh <profile>` reports the gap and
prints the command.

## The container builder is separate — and it needs one thing from the host

`podman` ships in the image (#1108), so an agent can build, run and scan container
images without host assistance. It is not part of the toolbox: the toolbox
materialises *language* toolchains on demand into a durable mount, while the
builder is a baked capability.

**It requires docker's `default-runtime` to be `sysbox-runc` on the host.** Under
stock `runc` podman cannot create the nested user namespace at all, and `aoe`
cannot pass `--runtime` per container — its `[sandbox]` schema has no such key,
and `container_runtime` selects the *engine* (docker/podman), not the OCI runtime
(agent-of-empires#3218). So this is a daemon-level setting, made once per host:

```bash
# /etc/docker/daemon.json
{
    "default-runtime": "sysbox-runc",
    "runtimes": { "sysbox-runc": { "path": "/usr/bin/sysbox-runc" } }
}
```

Two things worth knowing before enabling it on a host that runs other work:

- **sysbox rejects `--privileged` and `--network host`.** Nothing in the OaW fleet
  uses either, but another project on the same host might. The failure is loud and
  the opt-out is one explicit `--runtime=runc` on that container.
- **Set `live-restore: true` in the same edit.** Without it every future daemon
  restart kills every running container, including live agent sessions. With it,
  the restart that enables sysbox is the last one that costs anything.

Also pin `bip` and `default-address-pools` to the host's *current* values before
installing sysbox. Its installer otherwise rewrites both — it sets `bip` to
`172.20.0.1/16` (which on malory was already occupied by another project's
network) and replaces docker's built-in address pools with a single
`172.25.0.0/16`. Its precondition check is purely textual, so declaring the
existing values both satisfies it and makes it a no-op.

**Verifying it.** `scripts/ci/aoe-preflight.sh <profile>` reports the capability.
A host without sysbox gets `[INFO] container builder unavailable ...` with the
reason — a declared absence, not a failure, because the kit's contract is the
image digest and this depends on host configuration outside it.

## Why not just `apt-get install maven` in the Dockerfile

Because then every agent carries it, the image grows for everyone, and updating
Maven means cutting a kit release — which since #1063 is a deliberate act, not a
merge. The toolbox layer exists so a toolchain can move on the repo's schedule
rather than the kit's.
