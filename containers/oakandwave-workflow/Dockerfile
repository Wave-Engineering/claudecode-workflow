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

# --- Go -----------------------------------------------------------------------
RUN curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-${GOARCH}.tar.gz" -o /tmp/go.tar.gz \
	&& tar -C /usr/local -xzf /tmp/go.tar.gz \
	&& ln -sf /usr/local/go/bin/go /usr/local/bin/go \
	&& ln -sf /usr/local/go/bin/gofmt /usr/local/bin/gofmt \
	&& rm -f /tmp/go.tar.gz
ENV PATH="/usr/local/go/bin:${PATH}"

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
# (Wave-Engineering/mcp-server-{sdlc,discord,discord-watcher,wtf,nerf} +
# commutativity-probe), each shipping a prebuilt linux-x64 release binary — no
# build secret and no operator step, so the install is hermetic over the public
# network. `./install` (no --no-mcps) walks mcps.json and runs each server's
# install-remote.sh: three register via `claude mcp add`, two via a jq edit of
# ~/.claude.json (pre-created below so the first — disc-server — lands too).
ENV KIT_SRC=/opt/oakandwave-workflow
COPY --chown=ubuntu:ubuntu . ${KIT_SRC}

USER ubuntu
ENV HOME=/home/ubuntu
# Kit scripts install to ~/.local/bin; put it (and go) ahead on PATH.
ENV PATH="/home/ubuntu/.local/bin:/usr/local/go/bin:${PATH}"
WORKDIR ${KIT_SRC}
# install's final step is a runtime-readiness advisory (check-deps.sh) whose exit
# code is the count of missing deps. `bun` (and node/claude) are now on PATH (the
# runtime-exposure layer above), so the advisory no longer flags bun as it did
# under --no-mcps — the remainder are runtime-only items check-deps can never see
# at build time: the secret tokens (slack-bot-token, discord-bot-token; never
# baked — R-12, provided at runtime via the ro ~/.secrets mount) and any
# host-specific hook path in settings.template.json. The tolerance FIRST greps the
# check-deps SUMMARY sentinel (a non-zero rc that ISN'T the advisory is a genuine
# install error → build fails), THEN pipes the advisory through
# `assert-only-expected-deps-missing.sh`, which fails the build if ANY missing dep
# is outside the expected-missing whitelist (the two secret tokens + the runtime-
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

WORKDIR /home/ubuntu

# --- OCI provenance (CI stamps the authoritative semver/revision in Story 2.1) -
LABEL org.opencontainers.image.title="oakandwave-workflow" \
	org.opencontainers.image.description="Versioned OaW Claude Code kit image on the AoE sandbox base" \
	org.opencontainers.image.source="https://github.com/Wave-Engineering/claudecode-workflow" \
	org.opencontainers.image.base.name="${BASE_IMAGE}"

# ENTRYPOINT/CMD inherited from the base (CMD ["sleep","infinity"]); aoe manages
# the container lifecycle and sets the runtime uid via [sandbox] (Story 1.2).
