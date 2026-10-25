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
# WHY disc-server IS LEFT ALONE. Inbound (the doorbell) stays on discord-watcher until K-2
# (Phase 3), and the Discord-only ops (list, resolve, create) keep their disc-server tools.
# This script never touches another server's registration.
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
CREWCHAT_TAG="v0.1.0"
# SSH, never HTTPS: the repo is private, and git to github.com goes over SSH, not a token.
CREWCHAT_REPO="ssh://git@github.com/Wave-Engineering/mattermost-crew.git"
CREWCHAT_SOCKET="${CREWCHAT_SOCKET:-/run/crewchat/crewchat.sock}"
SERVER_NAME="crewchat"
PACKAGE="crewchat-clients"

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

registered() {
	command -v claude >/dev/null 2>&1 && claude mcp get "$SERVER_NAME" >/dev/null 2>&1
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
	if [[ "$dry_run" == true ]]; then
		info "(dry-run) uv tool install --force $source_spec"
		info "(dry-run) claude mcp add -s user $SERVER_NAME -- <uv tool dir>/crewchat-mcp"
		return 0
	fi
	if [[ "$(installed_version)" != "$want_version" ]]; then
		info "crewchat: installing $PACKAGE $CREWCHAT_TAG"
		uv tool install --force "$source_spec" >/dev/null
	fi
	local bin
	bin="$(uv tool dir --bin 2>/dev/null)/crewchat-mcp"
	if [[ ! -x "$bin" ]]; then
		warn "crewchat: $bin missing after install; not registering."
		return 1
	fi
	if registered; then
		claude mcp remove -s user "$SERVER_NAME" >/dev/null 2>&1 || true
	fi
	claude mcp add -s user "$SERVER_NAME" -- "$bin" >/dev/null
	ok "crewchat: $PACKAGE $CREWCHAT_TAG registered as $SERVER_NAME"
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
	if ! registered; then
		drift "crewchat: $PACKAGE $have installed but $SERVER_NAME NOT REGISTERED"
		return 1
	fi
	info "crewchat: $PACKAGE $have (registered)"
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
