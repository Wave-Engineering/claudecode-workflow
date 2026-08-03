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

## What this does NOT give you

**A container builder.** `docker`, `podman` and `buildah` are still absent, and
an agent cannot self-install them: no sudo, no socket, no daemon. So building a
repo's Dockerfiles inside the container does not work.

That is a **privilege** decision — socket mount vs rootless podman vs "Dockerfile
work happens on the host" — with a real security surface, and it is deliberately
not solved as a side effect of a toolchain fix. It needs its own decision and its
own issue.

## Why not just `apt-get install maven` in the Dockerfile

Because then every agent carries it, the image grows for everyone, and updating
Maven means cutting a kit release — which since #1063 is a deliberate act, not a
merge. The toolbox layer exists so a toolchain can move on the repo's schedule
rather than the kit's.
