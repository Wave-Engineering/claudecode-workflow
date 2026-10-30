#!/usr/bin/env bash
# install-crewchat.sh — install and register the crewchat thin MCP (`crewchat-mcp`), but
# only on a host where the crewchat daemon runs (K-1, #1330).
#
# WHY IT IS GATED ON THE SOCKET. The thin MCP is a client of the crewchat daemon: every
# tool but chat_set_default forwards one frame to /run/crewchat/crewchat.sock. Deploying the
# daemon and broker is a fleet install, and that is BJ's decision (mattermost-crew Dev Spec
# §5.B step 5). On a host without the daemon, a registered crewchat server would fail every
# call, and the skills' dual-mode rule ("chat_* when chat_send is in your tool list, else
# disc_*") would pick the broken path. So no daemon, no registration, and disc-server stays
# the transport exactly as before.
#
# WHY disc-server IS LEFT ALONE. The Discord-only ops (list, resolve, create) keep their
# disc-server tools until the cut-over (mattermost-crew D-060). This script never touches
# another server's registration.
#
# THE DOORBELL (K-2, #1336). The same package ships `crewchat-doorbell`, which is the
# doorbell wherever `chat_send` exists (/disc, "Doorbell: crewchat-doorbell or the
# one-shots"). So registration also requires the doorbell to run. A registered shim with no
# doorbell would have every skill arm a command that isn't there, and the agent would be
# deaf. Unregistered, the skills fall back to sqtk-doorbell.sh for squawks, and the kit has
# no Discord doorbell (discord-watcher was retired, #1344).
#
# WHY THE LOCK, AND NOT A PLAIN `uv tool install`. A git-URL install re-resolves every
# dependency from PyPI and ignores mattermost-crew's uv.lock. crewchat-clients declares only
# `mcp>=1.20`, so the resolver took mcp 2.x, where the shim's `mcp.server.fastmcp` is gone: it
# died at import and Claude Code showed "Failed to connect" (#1332). So the install takes the
# tag's lock as constraints, the same versions mattermost-crew tests (its CT-03: never
# re-resolve), and keeps them beside the tool so `check` can compare against them.
#
# WHY `claude mcp add` AND NOT jq. Every live session writes ~/.claude.json. A jq
# read-modify-write races them and can drop a session's write. The CLI is the supported writer.
#
# Usage:
#   install-crewchat.sh install [--dry-run]   install + register, or print why it skipped
#   install-crewchat.sh check                 report state; exit 1 only on drift
#   install-crewchat.sh uninstall [--dry-run] remove the registration and the uv tool
#
# Environment (for tests): CREWCHAT_SOCKET (default /run/crewchat/crewchat.sock).
# `uv` and `claude` are resolved from PATH.
set -euo pipefail

# The one pinned release. Bump it with each mattermost-crew release the kit adopts.
CREWCHAT_TAG="v0.2.6"
# SSH, never HTTPS: the repo is private, and git to github.com goes over SSH, not a token.
CREWCHAT_REPO="ssh://git@github.com/Wave-Engineering/mattermost-crew.git"
CREWCHAT_SOCKET="${CREWCHAT_SOCKET:-/run/crewchat/crewchat.sock}"
SERVER_NAME="crewchat"
PACKAGE="crewchat-clients"
# The lock's versions, exported at install time and kept in the tool's environment.
CONSTRAINTS_NAME="kit-constraints.txt"

info() { echo "  [+] $*"; }
ok() { echo "  [✓] $*"; }
warn() { echo "  [!] $*"; }
skip() { echo "  [-] $*"; }
drift() { echo "  [~] $*"; }

want_version="${CREWCHAT_TAG#v}"
source_spec="git+${CREWCHAT_REPO}@${CREWCHAT_TAG}#subdirectory=packages/clients"

# Why the daemon can't be used from here, or "" when it can. The socket must exist and be
# writable by this user (membership in crewchat-clients); a socket the agent can't open is
# the same as no daemon.
daemon_unusable() {
	if [[ ! -S "$CREWCHAT_SOCKET" ]]; then
		echo "no crewchat daemon on this host ($CREWCHAT_SOCKET absent)"
	elif [[ ! -w "$CREWCHAT_SOCKET" ]]; then
		echo "$CREWCHAT_SOCKET is not writable by $(id -un) (not in crewchat-clients?)"
	fi
}

# The installed crewchat-clients version per `uv tool list`, or "".
installed_version() {
	command -v uv >/dev/null 2>&1 || return 0
	# `|| true` inside the group: under pipefail a failing `uv tool list` would otherwise
	# make this return non-zero, and `have="$(installed_version)"` would exit the script.
	{ uv tool list 2>/dev/null || true; } |
		awk -v p="$PACKAGE" '$1 == p { sub(/^v/, "", $2); print $2; exit }'
}

# Why the installed `crewchat-doorbell` can't run, or "" when it can. `--help` is argparse's,
# so it exits without touching the socket; `timeout` keeps a broken binary from hanging us.
doorbell_unusable() {
	local bin
	bin="$(uv tool dir --bin 2>/dev/null)/crewchat-doorbell"
	if [[ ! -x "$bin" ]]; then
		echo "$bin missing"
	elif ! timeout 5 "$bin" --help >/dev/null 2>&1; then
		echo "$bin --help failed"
	fi
}

registered() {
	command -v claude >/dev/null 2>&1 && claude mcp get "$SERVER_NAME" >/dev/null 2>&1
}

# The tool's environment, where uv installed it.
tool_env() {
	echo "$(uv tool dir 2>/dev/null)/$PACKAGE"
}

# `name==version` lines, names normalised (PEP 503) and environment markers dropped, so uv's
# export and `uv pip list --format freeze` compare.
normalize_pins() {
	awk '{ sub(/[ \t]*;.*/, ""); gsub(/[ \t]/, "") }
		split($0, a, "==") == 2 { n = tolower(a[1]); gsub(/[-_.]+/, "-", n); print n "==" a[2] }'
}

# Write the tag's uv.lock, exported as constraints for $PACKAGE, to $1. Non-zero on any
# failure, and the caller must not install then: an unconstrained install is the bug.
export_constraints() {
	local out="$1" src rc=0
	src="$(mktemp -d)"
	git -c advice.detachedHead=false clone -q --depth 1 --branch "$CREWCHAT_TAG" "$CREWCHAT_REPO" "$src/repo" &&
		uv export -q --directory "$src/repo" --frozen --package "$PACKAGE" --no-dev \
			--no-emit-workspace --no-hashes --no-header --no-annotate -o "$out" &&
		[[ -s "$out" ]] || rc=1
	rm -rf "$src"
	return "$rc"
}

# Why the installed tool's environment is not the lock's, or "" when it is. Only packages
# that are installed are compared: a pin behind a marker that doesn't apply here is absent.
constraints_drift() {
	local env rec have
	env="$(tool_env)"
	rec="$env/$CONSTRAINTS_NAME"
	if [[ ! -f "$rec" ]]; then
		echo "installed without the lock's constraints"
		return 0
	fi
	if ! have="$(uv pip list --python "$env/bin/python" --format freeze 2>/dev/null)"; then
		echo "can't list the packages in $env"
		return 0
	fi
	awk -F'==' 'NR == FNR { pin[$1] = $2; next }
		($1 in pin) && pin[$1] != $2 { print $1 " is " $2 ", the lock pins " pin[$1]; exit }' \
		<(normalize_pins <"$rec") <(printf '%s\n' "$have" | normalize_pins)
}

# A failed install leaves no registration behind. One from an earlier install points at the
# environment this run replaced or couldn't repair, so it fails OPEN like a stale one.
install_failed() {
	warn "crewchat: $1"
	if registered; then
		claude mcp remove -s user "$SERVER_NAME" >/dev/null
		warn "crewchat: removed the $SERVER_NAME registration; chat stays on disc-server."
	fi
}

do_install() {
	local dry_run="$1" why
	why="$(daemon_unusable)"
	if [[ -n "$why" ]]; then
		# A registration left from when the daemon was usable fails OPEN: the skills see
		# chat_send and pick a path whose every call fails. Remove it.
		if registered; then
			if [[ "$dry_run" == true ]]; then
				info "(dry-run) claude mcp remove -s user $SERVER_NAME (stale: $why)"
			else
				claude mcp remove -s user "$SERVER_NAME" >/dev/null
				warn "crewchat: removed the stale $SERVER_NAME registration ($why)"
			fi
		fi
		skip "crewchat: skipped, $why. Chat stays on disc-server."
		return 0
	fi
	if ! command -v uv >/dev/null 2>&1; then
		warn "crewchat: uv not found; can't install $PACKAGE. Chat stays on disc-server."
		return 0
	fi
	if ! command -v claude >/dev/null 2>&1; then
		warn "crewchat: claude CLI not found; can't register $SERVER_NAME."
		return 0
	fi
	if ! command -v git >/dev/null 2>&1; then
		warn "crewchat: git not found; can't read $CREWCHAT_TAG's lock. Chat stays on disc-server."
		return 0
	fi
	if [[ "$dry_run" == true ]]; then
		info "(dry-run) git clone --branch $CREWCHAT_TAG $CREWCHAT_REPO; uv export --frozen --package $PACKAGE"
		info "(dry-run) uv tool install --force --constraints <the lock's pins> $source_spec"
		info "(dry-run) claude mcp add -s user $SERVER_NAME -- <uv tool dir>/crewchat-mcp"
		return 0
	fi
	local drift_why=""
	if [[ "$(installed_version)" == "$want_version" ]]; then
		drift_why="$(constraints_drift)"
		# At the right version, a doorbell that doesn't run is a broken environment: reinstall.
		[[ -n "$drift_why" ]] || drift_why="$(doorbell_unusable)"
	fi
	if [[ "$(installed_version)" != "$want_version" || -n "$drift_why" ]]; then
		info "crewchat: installing $PACKAGE $CREWCHAT_TAG${drift_why:+ ($drift_why)}"
		local work
		work="$(mktemp -d)"
		if ! export_constraints "$work/constraints.txt"; then
			rm -rf "$work"
			install_failed "couldn't export $CREWCHAT_TAG's lock from $CREWCHAT_REPO; not installing."
			return 1
		fi
		if ! uv tool install -q --force --constraints "$work/constraints.txt" "$source_spec" >/dev/null ||
			! cp "$work/constraints.txt" "$(tool_env)/$CONSTRAINTS_NAME"; then
			rm -rf "$work"
			install_failed "installing $PACKAGE $CREWCHAT_TAG failed."
			return 1
		fi
		rm -rf "$work"
		# Verify the post-state: registering a shim that can't import is the failure we're here for.
		drift_why="$(constraints_drift)"
		if [[ -n "$drift_why" ]]; then
			install_failed "after install, $drift_why; not registering."
			return 1
		fi
	fi
	local bin
	bin="$(uv tool dir --bin 2>/dev/null)/crewchat-mcp"
	if [[ ! -x "$bin" ]]; then
		install_failed "$bin missing after install; not registering."
		return 1
	fi
	why="$(doorbell_unusable)"
	if [[ -n "$why" ]]; then
		install_failed "$why after install; not registering, so the skills keep the old doorbell."
		return 1
	fi
	if registered; then
		claude mcp remove -s user "$SERVER_NAME" >/dev/null 2>&1 || true
	fi
	claude mcp add -s user "$SERVER_NAME" -- "$bin" >/dev/null
	ok "crewchat: $PACKAGE $CREWCHAT_TAG registered as $SERVER_NAME (crewchat-mcp, crewchat-doorbell)"
}

do_check() {
	local why have
	why="$(daemon_unusable)"
	have="$(installed_version)"
	if [[ -n "$why" ]]; then
		if registered; then
			drift "crewchat: registered, but $why"
			return 1
		fi
		skip "crewchat: not applicable, $why"
		return 0
	fi
	if [[ "$have" != "$want_version" ]]; then
		drift "crewchat: $PACKAGE ${have:-not installed}, want $want_version"
		return 1
	fi
	why="$(constraints_drift)"
	if [[ -n "$why" ]]; then
		drift "crewchat: $PACKAGE $have $why"
		return 1
	fi
	why="$(doorbell_unusable)"
	if [[ -n "$why" ]]; then
		drift "crewchat: $PACKAGE $have installed but $why"
		return 1
	fi
	if ! registered; then
		drift "crewchat: $PACKAGE $have installed but $SERVER_NAME NOT REGISTERED"
		return 1
	fi
	info "crewchat: $PACKAGE $have (registered; crewchat-doorbell runs)"
}

do_uninstall() {
	local dry_run="$1"
	if [[ "$dry_run" == true ]]; then
		info "(dry-run) claude mcp remove -s user $SERVER_NAME; uv tool uninstall $PACKAGE"
		return 0
	fi
	if registered; then
		claude mcp remove -s user "$SERVER_NAME" >/dev/null 2>&1 || true
		info "crewchat: $SERVER_NAME unregistered"
	fi
	if [[ -n "$(installed_version)" ]]; then
		uv tool uninstall "$PACKAGE" >/dev/null 2>&1 || true
		info "crewchat: $PACKAGE removed"
	fi
}

cmd="${1:-}"
dry=false
[[ "${2:-}" == "--dry-run" ]] && dry=true
case "$cmd" in
install) do_install "$dry" ;;
check) do_check ;;
uninstall) do_uninstall "$dry" ;;
*)
	echo "usage: install-crewchat.sh install|check|uninstall [--dry-run]" >&2
	exit 2
	;;
esac
