# syntax=docker/dockerfile:1
#
# oakandwave-workflow — the versioned kit image (Story 1.1, Plan #959).
#
# Composition (Dev Spec §5.2):
#   FROM aoe-dev-sandbox  →  kit-dep toolchain layer  →  ./install the kit
#
# The base ships Rust / Python+uv / Node and a uid-1000 `ubuntu` user, but is
# MISSING Go, trivy, shellcheck, shfmt, glab, bao (OpenBao) and aws (TC-3). This
# image bakes those in system-wide (/usr/local/bin — on PATH for every user) and
# installs the kit for the uid-1000 runtime user so the image *digest is the
# release* (R-05) and everything versioned-with-the-release is baked, not
# bind-mounted (R-06).
#
# Reproducibility: every tool version is a pinned ARG (override with --build-arg).
# See the Makefile for the canonical `make build`.

ARG BASE_IMAGE=ghcr.io/agent-of-empires/aoe-dev-sandbox:1.13.0
FROM ${BASE_IMAGE}

# Re-declare after FROM so ${BASE_IMAGE} is in scope for the LABEL below.
ARG BASE_IMAGE

# --- Pinned kit-dep tool versions (override via --build-arg) ------------------
ARG GO_VERSION=1.24.5
ARG SHELLCHECK_VERSION=0.10.0
ARG SHFMT_VERSION=3.10.0
ARG GLAB_VERSION=1.53.0
ARG TRIVY_VERSION=0.72.0
ARG BAO_VERSION=2.6.0
ARG AWSCLI_VERSION=2.24.0
ARG MISE_VERSION=2026.8.0
# mise publishes `linux-x64`, NOT Go's `amd64`. Reusing ${GOARCH} here 404'd the
# build (curl exit 22) — the naming conventions genuinely differ per project, so
# this gets its own arg rather than an assumption that they agree.
ARG MISE_ARCH=x64
# The base is linux/amd64; the fetch URLs below are arch-specific. Rebuild with
# matching ARGs if a multi-arch base is ever introduced.
ARG GOARCH=amd64

# All tool installs run as root and land in system paths; the kit install (last
# stage) drops to the uid-1000 user.
USER root
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Build-time fetch/extract deps (curl is present in the base, but pin the rest).
RUN apt-get update \
	&& apt-get install -y --no-install-recommends ca-certificates curl tar xz-utils unzip \
	&& rm -rf /var/lib/apt/lists/*

# tini — the image's eventual PID 1 (cc-workflow#1179, see the ENTRYPOINT/CMD
# note near the bottom of this file for what it fixes and why). Installed
# here, ahead of the `COPY --chown=ubuntu:ubuntu . ${KIT_SRC}` below, purely
# for layer caching: this package has no dependency on anything the build
# does between here and there, so installing it after that COPY would
# re-hit the Ubuntu archives on every rebuild instead of caching once.
# `tini --version` proves the binary actually runs, matching this file's own
# established idiom for every other tool install (mise, podman, the
# five-runtime probe below, the vox smoke test) — "config exists" is not
# "config works" anywhere else in this file, and this step is no exception.
RUN apt-get update \
	&& apt-get install -y --no-install-recommends tini \
	&& rm -rf /var/lib/apt/lists/* \
	&& /usr/bin/tini --version

# --- Container builder: podman (#1108) ----------------------------------------
# Agents must be able to build, run and scan container images from inside their
# own sandbox. blueshift-kb#8 (swap a runtime image to distroless, shedding 23
# unfixable CVEs) could not be verified without it, and the agent that hit the
# gap tried to route around the boundary rather than stop — a missing capability
# generates pressure to solve the wrong problem.
#
# NOT a docker socket mount. Over a socket, `docker build` executes on the HOST
# daemon, so the build context and every bind-mount path resolve to host paths
# the agent cannot see, and concurrent agents collide in one shared image
# namespace. It is broken for the job, independent of any trust argument.
#
# `nftables` is NOT optional despite being invisible at build time: without it
# `podman build` still succeeds and `podman run` fails with
# `netavark: nftables error: unable to execute "nft"`.
RUN apt-get update \
	&& apt-get install -y --no-install-recommends \
		podman crun conmon netavark passt nftables iptables uidmap fuse-overlayfs sudo \
	&& rm -rf /var/lib/apt/lists/*

# HOST REQUIREMENT: podman needs the `sysbox-runc` OCI runtime as docker's
# default-runtime. Under stock runc the nested user namespace is refused outright
# ("cannot clone: Operation not permitted"). aoe cannot pass --runtime per
# container — its [sandbox] schema has no such key, and `container_runtime`
# selects the ENGINE (docker/podman), not the OCI runtime — so this is a
# daemon-level setting (agent-of-empires#3218). The capability is therefore
# REPORTED by aoe-preflight.sh, never assumed: an adopter without sysbox gets a
# declared, explained absence rather than a red gate for something they did not
# ask for.
#
# Podman runs as ROOT inside the container, which is the mode sysbox is designed
# for: sysbox maps container-root to an unprivileged host uid, so this is not
# host root. Rootless was tried first and is structurally impossible here — the
# kernel refuses an unprivileged procfs mount unless the parent /proc is fully
# visible, and sysbox-fs overlays /proc to virtualise it, so any Dockerfile with
# a RUN step dies on `mount proc to proc: Operation not permitted`.
#
# vfs, deliberately: podman selects fuse-overlayfs when it cannot use kernel
# overlayfs, and under sysbox that fails on `/proc/sys/kernel/overflowuid`
# (present at the container's top level, EIO from the nested userns). Setting
# `mount_program = ""` does not force kernel overlayfs — podman ignores it. vfs
# copies every layer, so it is slower and hungrier, but agents build small
# verification images and the store lives in the container's own writable layer,
# so it cannot grow without bound on the host.
RUN install -d -m 0755 /etc/containers \
	&& printf '%s\n' \
		'[storage]' \
		'driver = "vfs"' \
		> /etc/containers/storage.conf

# The agent runs as uid-1000 `ubuntu`. Elevation is scoped to podman ALONE, not
# blanket sudo. Measured reason, not caution: a root-written file on a bind mount
# surfaces as uid 0 on the HOST (sysbox does not idmap it back to the operator),
# so general sudo would let agents strand root-owned files in the operator's own
# workspaces. This is parity, not new privilege — agents ran on the host as a user
# with passwordless sudo, and `docker run -v` there produced root-owned files the
# same way, because the host daemon ran as root.
#
# The wrapper keeps `podman ...` working unqualified, mirroring the `claude`
# wrapper precedent below; an agent should not have to know about the elevation.
RUN set -eux; \
	printf '%s\n' 'ubuntu ALL=(root) NOPASSWD: /usr/bin/podman' \
		> /etc/sudoers.d/oaw-podman; \
	chmod 0440 /etc/sudoers.d/oaw-podman; \
	visudo -cf /etc/sudoers.d/oaw-podman; \
	printf '%s\n' \
		'#!/bin/bash' \
		'# Podman must run as root inside the sysbox container (see Dockerfile).' \
		'# Re-exec under the scoped sudoers rule unless already root.' \
		'if [ "$(id -u)" -eq 0 ]; then exec /usr/bin/podman "$@"; fi' \
		'exec sudo -n /usr/bin/podman "$@"' \
		> /usr/local/bin/podman; \
	chmod 0755 /usr/local/bin/podman; \
	su ubuntu -c '/usr/local/bin/podman --version'

# --- Go -----------------------------------------------------------------------
RUN curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-${GOARCH}.tar.gz" -o /tmp/go.tar.gz \
	&& tar -C /usr/local -xzf /tmp/go.tar.gz \
	&& ln -sf /usr/local/go/bin/go /usr/local/bin/go \
	&& ln -sf /usr/local/go/bin/gofmt /usr/local/bin/gofmt \
	&& rm -f /tmp/go.tar.gz
ENV PATH="/usr/local/go/bin:${PATH}"

# --- mise (R-11 toolbox installer) --------------------------------------------
# THE INSTALLER IS BAKED; THE TOOLCHAINS ARE NOT. That distinction is the whole
# of R-11 (#1092). Baking a JDK would put a Java toolchain in every agent whether
# or not it touches Java, and would make bumping Maven a KIT RELEASE. mise is one
# ~30 MB static binary that can materialise JDK / Maven / Node / Go / Python on
# demand into the durable toolbox mount, where they survive container recreation
# and are decoupled from the kit's release cadence.
#
# Pinned tarball, not the piped installer script (`curl … | sh`) — same rule as
# trivy and bao above: a build step that executes whatever a URL serves today is
# not reproducible, and it is the supply-chain surface we are here to avoid.
RUN curl -fsSL "https://github.com/jdx/mise/releases/download/v${MISE_VERSION}/mise-v${MISE_VERSION}-linux-${MISE_ARCH}.tar.gz" -o /tmp/mise.tar.gz \
	&& tar -C /tmp -xzf /tmp/mise.tar.gz \
	&& install -m 0755 /tmp/mise/bin/mise /usr/local/bin/mise \
	&& rm -rf /tmp/mise.tar.gz /tmp/mise \
	&& mise --version

# --- shellcheck ---------------------------------------------------------------
RUN curl -fsSL "https://github.com/koalaman/shellcheck/releases/download/v${SHELLCHECK_VERSION}/shellcheck-v${SHELLCHECK_VERSION}.linux.x86_64.tar.xz" -o /tmp/shellcheck.tar.xz \
	&& tar -C /tmp -xJf /tmp/shellcheck.tar.xz \
	&& install -m 0755 "/tmp/shellcheck-v${SHELLCHECK_VERSION}/shellcheck" /usr/local/bin/shellcheck \
	&& rm -rf /tmp/shellcheck.tar.xz "/tmp/shellcheck-v${SHELLCHECK_VERSION}"

# --- shfmt --------------------------------------------------------------------
RUN curl -fsSL "https://github.com/mvdan/sh/releases/download/v${SHFMT_VERSION}/shfmt_v${SHFMT_VERSION}_linux_${GOARCH}" -o /usr/local/bin/shfmt \
	&& chmod 0755 /usr/local/bin/shfmt

# --- glab (GitLab CLI) --------------------------------------------------------
RUN curl -fsSL "https://gitlab.com/gitlab-org/cli/-/releases/v${GLAB_VERSION}/downloads/glab_${GLAB_VERSION}_linux_${GOARCH}.tar.gz" -o /tmp/glab.tar.gz \
	&& tar -C /tmp -xzf /tmp/glab.tar.gz \
	&& install -m 0755 /tmp/bin/glab /usr/local/bin/glab \
	&& rm -rf /tmp/glab.tar.gz /tmp/bin

# --- trivy (pinned release tarball; hermetic — no piped installer) ------------
RUN curl -fsSL "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" -o /tmp/trivy.tar.gz \
	&& tar -C /tmp -xzf /tmp/trivy.tar.gz trivy \
	&& install -m 0755 /tmp/trivy /usr/local/bin/trivy \
	&& rm -f /tmp/trivy.tar.gz /tmp/trivy

# --- bao (OpenBao CLI) --------------------------------------------------------
RUN curl -fsSL "https://github.com/openbao/openbao/releases/download/v${BAO_VERSION}/openbao_${BAO_VERSION}_linux_${GOARCH}.tar.gz" -o /tmp/bao.tar.gz \
	&& tar -C /tmp -xzf /tmp/bao.tar.gz bao \
	&& install -m 0755 /tmp/bao /usr/local/bin/bao \
	&& rm -f /tmp/bao.tar.gz /tmp/bao

# --- aws CLI v2 ---------------------------------------------------------------
RUN curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64-${AWSCLI_VERSION}.zip" -o /tmp/awscli.zip \
	&& unzip -q /tmp/awscli.zip -d /tmp \
	&& /tmp/aws/install --bin-dir /usr/local/bin --install-dir /usr/local/aws-cli \
	&& rm -rf /tmp/awscli.zip /tmp/aws

# --- Expose the base's language runtimes to the uid-1000 runtime user ---------
# The base installs claude, bun, node/npm and uv UNDER /root (mode 700), so the
# uid-1000 `ubuntu` user cannot reach any of them (a known base issue). The kit
# install (next stage) runs AS ubuntu and needs `claude` to register the kit's
# own MCP servers (`claude mcp add --scope user`); deps.json also declares
# `bun`/`node` for MCP tooling. Relocate the standalone binaries — and node's
# runtime tree — to world-readable paths already on the system PATH
# (/usr/local/bin). The standalone binaries are `cp -L`'d (symlinks dereferenced);
# node is copied whole (`cp -a`) but its internal bin symlinks are RELATIVE, so they
# resolve inside /opt/node — either way nothing points back into the unreadable
# /root. Runs as root, BEFORE the USER ubuntu switch. The final
# `su ubuntu` line proves each runtime actually executes as the non-root user
# (config-exists ≠ config-works).
RUN set -eux; \
	install -d -m 0755 /opt; \
	cp -L /root/.local/bin/claude /usr/local/bin/claude; \
	cp -L /root/.bun/bin/bun /usr/local/bin/bun; \
	cp -L /root/.local/bin/uv /usr/local/bin/uv; \
	cp -L /root/.local/bin/uvx /usr/local/bin/uvx; \
	chmod 0755 /usr/local/bin/claude /usr/local/bin/bun /usr/local/bin/uv /usr/local/bin/uvx; \
	ln -sf /usr/local/bin/bun /usr/local/bin/bunx; \
	node_dir="$(dirname "$(dirname "$(readlink -f /root/.local/bin/node)")")"; \
	cp -a "$node_dir" /opt/node; \
	ln -sf /opt/node/bin/node /usr/local/bin/node; \
	ln -sf /opt/node/bin/npm /usr/local/bin/npm; \
	ln -sf /opt/node/bin/npx /usr/local/bin/npx; \
	su ubuntu -c 'export HOME=/home/ubuntu; \
		/usr/local/bin/claude --version \
		&& /usr/local/bin/bun --version \
		&& /usr/local/bin/node --version \
		&& /usr/local/bin/npm --version \
		&& /usr/local/bin/uv --version'

# --- Bake the kit (skills, scripts, hooks, config AND MCP servers) ------------
# Reuse the base's uid-1000 `ubuntu` user (TC-2). The kit installs $HOME-rooted,
# so it must run AS that user for the runtime user to resolve it. The kit's own
# MCP servers ARE baked here (R-09 baking half): every kit MCP repo is PUBLIC
# (Wave-Engineering/mcp-server-{sdlc,discord,discord-watcher,wtf,nerf}), each
# shipping a prebuilt linux-x64 release binary — no build secret and no operator
# step, so the install is hermetic over the public network. `./install` (no
# --no-mcps) walks mcps.json and runs each server's install-remote.sh: three
# register via `claude mcp add`, two via a jq edit of ~/.claude.json (pre-created
# below so the first — disc-server — lands too). sdlc-server additionally bundles
# a Python `commutativity-probe` CLI — NOT a prebuilt binary and NOT in mcps.json;
# it is baked separately in the dedicated step below (#1014).
ENV KIT_SRC=/opt/oakandwave-workflow
COPY --chown=ubuntu:ubuntu . ${KIT_SRC}

USER ubuntu
ENV HOME=/home/ubuntu
# Kit scripts install to ~/.local/bin; put it (and go) ahead on PATH.
# The operator's own ~/.local/bin is mounted at .oaw/overlay/local-bin (#1089)
# and APPENDED — never prepended. The kit's own bin holds the claude wrapper
# (#1076) and the MCP binaries; a host utility must never shadow those.
# mise keeps its installs on the DURABLE toolbox mount, so a materialised
# toolchain survives container recreation instead of being re-downloaded (R-11).
ENV MISE_DATA_DIR=/home/ubuntu/.oaw/toolbox/mise
# The operator manifest IS mise's global config. Without this the shims are on
# PATH but cannot resolve a version — measured: `command -v java` returned the
# shim while `java -version` said "No version is set for shim: java". A shim that
# exists and cannot run is not a toolchain; it is a more confusing absence.
# bootstrap re-exports this to whatever manifest it actually finds, which also
# covers a non-default toolbox path; this ENV is the floor for a bare docker exec.
ENV MISE_GLOBAL_CONFIG_FILE=/home/ubuntu/.oaw/toolbox/mise.toml

# Toolbox shims sit AFTER the kit's own bin dir and BEFORE the system dirs:
#   * after ~/.local/bin so a toolchain can never shadow a kit binary — §3.4's
#     "kit wins over the overlay" keeps the RTE authoritative;
#   * before ${PATH} so a mise-managed JDK does beat a stray system one.
#
# It goes in the IMAGE's ENV deliberately. `docker exec` resolves against the
# image's configured PATH, not a shell's — non-interactive shells never read
# ~/.bashrc, which is exactly why bifrost had to hand-source an env file. A hook
# or an agent-run command must find `mvn` with no shell cooperation at all.
ENV PATH="/home/ubuntu/.local/bin:/usr/local/go/bin:/home/ubuntu/.oaw/toolbox/mise/shims:${PATH}:/home/ubuntu/.oaw/overlay/local-bin"
WORKDIR ${KIT_SRC}
# install's final step is a runtime-readiness advisory (check-deps.sh) whose exit
# code is the count of missing deps. `bun` (and node/claude) are now on PATH (the
# runtime-exposure layer above), so the advisory no longer flags bun as it did
# under --no-mcps — the remainder are runtime-only items check-deps can never see
# at build time: the discord bot token (never baked —
# R-12, provided at runtime via the ro ~/.secrets mount) and any
# host-specific hook path in settings.template.json. The tolerance FIRST greps the
# check-deps SUMMARY sentinel (a non-zero rc that ISN'T the advisory is a genuine
# install error → build fails), THEN pipes the advisory through
# `assert-only-expected-deps-missing.sh`, which fails the build if ANY missing dep
# is outside the expected-missing whitelist (the discord token + the runtime-
# installed wtf-server hook). So a real regression — gh/jq/python3/curl/git going
# missing — can no longer hide behind the content-agnostic sentinel (#1016). The
# real guarantees: a genuine install error aborts under set -euo pipefail BEFORE
# check-deps (sentinel absent → build fails), the whitelist gate rejects any
# unexpected missing dep, and the positive assertions below cover the kit AND all
# five MCP servers.
#
# Pre-create ~/.claude.json ({} is augmented in place): the two jq-registering
# MCPs (disc-server, sdlc-server) skip registration if it is absent, and
# disc-server sorts first — so without this seed the first MCP would silently not
# register. `claude mcp add` (the other three) merges into the same file.
RUN set +e; \
	mkdir -p "$HOME/.claude"; \
	[ -f "$HOME/.claude.json" ] || printf '{}\n' > "$HOME/.claude.json"; \
	out="$(./install --without-logrotate --yes 2>&1)"; rc=$?; \
	set -e; \
	printf '%s\n' "$out"; \
	if [ "$rc" -ne 0 ]; then \
		printf '%s\n' "$out" | grep -q "required dependency/dependencies missing" \
			|| { echo "install failed (not the dependency advisory) — rc=$rc"; exit "$rc"; }; \
		printf '%s\n' "$out" | ./scripts/ci/assert-only-expected-deps-missing.sh; \
	fi; \
	test -d "$HOME/.claude/skills"; \
	test -n "$(find "$HOME/.claude/skills" -name SKILL.md -print -quit)"; \
	test -f "$HOME/.claude/settings.json"; \
	for m in disc-server discord-watcher nerf-server sdlc-server wtf-server; do \
		jq -e --arg m "$m" '.mcpServers[$m]' "$HOME/.claude.json" >/dev/null \
			|| { echo "MCP baking FAILED: $m not registered in ~/.claude.json"; exit 1; }; \
		test -x "$HOME/.local/bin/$m" \
			|| { echo "MCP baking FAILED: $HOME/.local/bin/$m missing or not executable"; exit 1; }; \
		echo "MCP baked: $m (registered + binary executable)"; \
	done

# --- A voice for containerised agents (#1084) ---------------------------------
# `vox` cannot work in here: no provider config, and no player AT ALL — none of
# afplay/paplay/aplay/ffplay, no libpulse. So every agent moved into a container
# lost the audible interrupt, the thing that gets the operator's attention when
# nobody is watching a Discord channel.
#
# Audio is NOT forwarded. Mounting the host's PipeWire socket was considered and
# rejected: with no client libraries and no player in here it would mean adding a
# whole audio stack to every image to play one sentence, and coupling containers
# to the host's audio devices. The TEXT is forwarded instead, to a spool on a
# host-visible mount, where the operator's already-configured vox synthesises and
# plays it (scripts/oaw-vox-drain + the systemd path unit beside it).
#
# vox resolves `~/.config/vox/{provider,player}` before its bundled defaults, so
# this is pure configuration — no change to vox itself. The PAIR is the trick:
# the provider forwards text and writes an empty $VOX_OUTPUT_FILE, and the player
# is a no-op because playback happens on the far side of the mount.
#
# Emphatically NOT silent.sh. Pointing the provider there would also stop the
# error, by making the agent mute and *believing* it had spoken — converting a
# visible gap into an invisible one, which #1084 explicitly refused. host-forward
# is loud when the spool is not being drained.
# OAW_VOX_SPOOL is declared in the mount fragment's `env`, but NOTHING consumes
# manifest env — the resolver emits `source:target` only. Without this ENV the
# provider silently falls back to its own literal default, so the container and
# the mount agree by two independent constants that nobody checks. Set it here so
# the declared variable is real.
ENV OAW_VOX_SPOOL=/home/ubuntu/.oaw/vox-spool
RUN set -eux; \
	install -d -m 0755 "$HOME/.config/vox"; \
	ln -sfn "$HOME/.claude/scripts/vox-providers/host-forward.sh" "$HOME/.config/vox/provider"; \
	ln -sfn "$HOME/.claude/scripts/vox-spool/no-op-player.sh" "$HOME/.config/vox/player"; \
	test -x "$HOME/.config/vox/provider"; \
	test -x "$HOME/.config/vox/player"; \
	OAW_VOX_SPOOL="$(mktemp -d)" vox "image build smoke test" >/dev/null; \
	echo "vox: forwarding provider wired (config-exists is not config-works — that just spoke)"

# --- Bake sdlc-server's commutativity-probe CLI (R-09 residual — #1014) --------
# sdlc-server shells out to a `commutativity-probe` CLI to service its
# `commutativity_verify` tool; with the CLI absent the handler degrades to a
# PROBE_UNAVAILABLE verdict (conservative-fail). The probe is a Python package at
# a pinned tag, NOT a prebuilt release binary like the five servers above.
# sdlc-server's install-remote.sh (run by `./install`) tries pipx / venv+pip /
# pip --user to install it — every path needs pip, which the base's python3 lacks
# (no ensurepip) — so all three no-op with a warning during the install above.
# `uv` (baked onto PATH in the runtime-exposure layer) installs it with its OWN
# build frontend, needing no system pip: it builds the package in an isolated
# environment and drops the `commutativity-probe` console script into
# ~/.local/bin — exactly where sdlc-server's `command -v` resolves it at runtime.
# UV_TOOL_BIN_DIR is pinned to the known-on-PATH bin dir so placement is
# deterministic regardless of any XDG_* the base image may set. The `--help`
# probe exits 0 (bare invocation requires a subcommand); a non-zero aborts the
# build under `set -eux`.
ARG SDLC_PROBE_REF=v0.1.0
RUN set -eux; \
	UV_TOOL_BIN_DIR="$HOME/.local/bin" \
		uv tool install "git+https://github.com/Wave-Engineering/commutativity-probe.git@${SDLC_PROBE_REF}"; \
	command -v commutativity-probe; \
	commutativity-probe --help >/dev/null; \
	echo "commutativity-probe baked: $(command -v commutativity-probe)"

WORKDIR /home/ubuntu

# --- OCI provenance (CI stamps the authoritative semver/revision in Story 2.1) -
LABEL org.opencontainers.image.title="oakandwave-workflow" \
	org.opencontainers.image.description="Versioned OaW Claude Code kit image on the AoE sandbox base" \
	org.opencontainers.image.source="https://github.com/wave-engineering/claudecode-workflow" \
	org.opencontainers.image.base.name="${BASE_IMAGE}"

# --- Agent bootstrap seam (#1076) --------------------------------------------
# MUST BE LAST. The build itself invokes /usr/local/bin/claude (the --version probe
# above and the `claude mcp add` registrations), and once the wrapper is in place
# every such call would run bootstrap — which, at build time, has no ~/.secrets to
# validate. Installing it here means the build uses the real CLI throughout and only
# the RUNTIME gets the wrapper.
#
# Why a wrapper at all: aoe never runs an entrypoint INTO THE AGENT — it
# `docker exec`s `claude` into the running container separately (PID 1 is
# tini keeping the container alive, per the ENTRYPOINT/CMD near the bottom
# of this file; cc-workflow#1179), so bootstrap.sh — skills-sync, settings
# merge, secret projection, R-14 validation — had no process path to the
# agent and never ran. Full rationale in claude-entrypoint.sh.
# /usr/local/bin is root-owned and the build is running as `ubuntu` by here, so
# this step needs root and must hand the uid back — the image's runtime user is
# ubuntu by design (R-04/TC-2, so bind-mount writes are host-owned).
#
# Every reachable `claude` is replaced, not just one: `docker exec` resolves
# against the IMAGE PATH, which reaches /root/.local/bin/claude (base-image
# symlink) before /usr/local/bin. Wrapping only /usr/local/bin/claude left the
# real launch path bypassing bootstrap entirely. assert-no-claude-bypass.sh turns
# that from an assumption into a build-time assertion.
#
# The placement commands need root, but the --version probes run under
# `su ubuntu` (same pattern as the toolchain probe above): ENV HOME is
# /home/ubuntu, so probing as root would let the CLI create root-owned state in
# the runtime user's home — and the agent must be able to write ~/.claude.json
# for MCP registration. That failure would surface later as an MCP bug.
USER root
# /root must be TRAVERSABLE by the runtime user (#1085). aoe sets
# CLAUDE_CONFIG_DIR=/root/.claude and mounts its config there, but this image runs
# as `ubuntu` and /root ships 0700 — so every path under it was EACCES even though
# /root/.claude itself is ubuntu-owned. Production symptoms: a Settings Error panel
# at startup (and settings are skipped ENTIRELY, losing all hooks), zero MCP
# servers, and the onboarding wizard on every launch.
#
# 0711 = traverse, not list: `ls /root` still fails, so this exposes nothing that
# was not already reachable by a caller who knows the exact path. Verified live.
RUN chmod 711 /root
RUN set -eux; \
	wrapper="${KIT_SRC}/containers/oakandwave-workflow/claude-entrypoint.sh"; \
	test -x /usr/local/bin/claude; \
	mv /usr/local/bin/claude /usr/local/bin/claude-real; \
	install -m 0755 "$wrapper" /usr/local/bin/claude; \
	install -m 0755 -o ubuntu -g ubuntu -D "$wrapper" /home/ubuntu/.local/bin/claude; \
	ln -sfn /usr/local/bin/claude /root/.local/bin/claude; \
	su ubuntu -c 'export HOME=/home/ubuntu; \
		/usr/local/bin/claude-real --version \
		&& OAW_SKIP_BOOTSTRAP=1 /usr/local/bin/claude --version'; \
	"${KIT_SRC}/scripts/ci/assert-no-claude-bypass.sh"

# No hook may be registered twice (#1094). The baked settings.json carried
# wtf-post-tool-use.sh under BOTH `~/.local/share/…` (from settings.template.json)
# and `/home/ubuntu/.local/share/…` (added afterwards by wtf-server's installer,
# whose idempotency check compared raw strings) — same file, so it fired twice on
# every tool use, for weeks, because nothing asked.
#
# Runs LAST, after `./install` and every MCP server's install-remote.sh have had
# their say: this asserts the state that actually ships, not the template's
# intent. Fixing the one installer that caused it (mcp-server-wtf#34) does not
# close the class — every MCP installer writes into this same file with its own
# notion of "already present".
#
# The settings path is explicit rather than left to `~`. Note that $HOME here is
# /home/ubuntu, NOT /root: the `ENV HOME` above persists across `USER root`
# (see the note at the USER ubuntu / ENV HOME lines). That is exactly why the
# script derives the home to expand `~` against from the FILE it is given rather
# than from the environment — an assertion whose detection depends on an ambient
# variable nobody asserts reports "no duplicates" the day that variable changes.
RUN HOME=/home/ubuntu "${KIT_SRC}/scripts/ci/assert-no-duplicate-hooks.sh" /home/ubuntu/.claude/settings.json

# --- Zombie reaping: tini as PID 1 (fleet-wide network dropouts) --------------
# aoe never runs its own entrypoint into the agent — it `docker exec`s
# `claude` into an already-running container (see the ENTRYPOINT/CMD note
# below), so the top-level exec'd process is PARENTLESS from birth in the
# container's PID namespace (PPID 0 — its real parent, the containerd-shim,
# lives outside the namespace and reaps IT fine). The zombies are its
# CHILDREN: when that process forks work and exits without collecting them,
# the kernel's find_new_reaper() reparents the orphans to the namespace's
# child_reaper — PID 1. The base image's own CMD, `sleep infinity`, never
# wait()s on anything, so a PID 1 that is merely "alive" does not collect
# what gets reparented to it; a `claude` session that exits or is killed
# without cleaning up its own children leaves them as permanent zombies
# there. At fleet scale (every exec, every session, every container,
# indefinitely) this accumulated to ~2k zombies and caused the network
# dropouts that made the container deployment unusable.
#
# tini is the fix Docker's own `--init` flag would install as a launch-time
# flag — baking it into the image instead means it works regardless of
# whatever aoe (a separate, external tool — not in this repo) passes to
# `docker run`/`docker create`. tini's only job as PID 1 is to reap; it execs
# its argument as its own child and otherwise stays out of the way — the
# "stay alive, keep namespaces open" role the base image already relied on
# `sleep infinity` for is unchanged, tini just adds the missing reap.
#
# Installed in the FIRST apt-get block (top of this file), not here — this
# package has no dependency on anything the build does between there and
# here, and folding it in keeps it a cached layer instead of re-hitting the
# Ubuntu archives on every rebuild this ~15-minute image goes through: the
# earlier `COPY --chown=ubuntu:ubuntu . ${KIT_SRC}` invalidates on every
# repo change, so anything installed AFTER it re-downloads every build, and
# a transient archive failure this late would abort a near-complete build.
USER ubuntu

# CODE REVIEW (cc-workflow#1179): CMD alone does NOT deliver the invariant
# above. CMD survives docker run FLAGS but is discarded outright by a
# trailing COMMAND ARGUMENT — `docker run <image> sleep infinity` (the single
# most common keep-alive idiom for a tool like aoe) would silently drop tini
# and PID 1 goes back to plain `sleep infinity`, no error, zombies resume.
# Every measurement this repo has on file ("PID 1 = sleep infinity" —
# claude-entrypoint.sh, docs/contained-workflow/architecture.md) is
# indistinguishable between "aoe uses the image CMD" and "aoe passes its own
# trailing command" — there is no way to rule out the second from existing
# evidence, which is exactly why ENTRYPOINT is used instead: it is invoked
# with WHATEVER command ends up in play (the image default below, or
# anything aoe supplies) as its arguments, so the reap holds either way. Only
# an explicit `--entrypoint` override defeats it — nothing in this repo's own
# aoe-launch surface does that (`sandbox-profile.toml`'s SandboxConfig schema
# has no such key); the tooling that DOES override it deliberately
# (Makefile, README, the four image tests) uses `--entrypoint sh` for
# interactive/debug shells, which is unaffected by what runs when nothing
# overrides it.
#
# Absolute path (not bare `tini`): `/home/ubuntu/.oaw/toolbox/mise/shims`
# precedes system PATH later in this image, so resolving PID 1 by bare name
# would risk a future mise shim silently shadowing the real binary — the
# same reasoning this file already applies to `/usr/bin/podman` and
# `/usr/local/bin/claude`.
#
# aoe still never runs an entrypoint INTO THE AGENT: it `docker exec`s
# `claude` separately and sets the runtime uid via [sandbox] (Story 1.2); the
# agent is bootstrapped by the /usr/local/bin/claude wrapper installed
# above, not by this ENTRYPOINT/CMD pair, which exists solely to keep the
# container alive with a reaping PID 1.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sleep", "infinity"]
