#!/usr/bin/env bash
# Install wave-watcher binary using the ETXTBSY-safe download-temp-then-mv-f
# pattern from mcp-server-sdlc CHANGELOG v1.0.1. The daemon may be running
# (systemd-supervised) when this runs; rename(2) unlinks the old inode but
# keeps the running process's text segment alive, so the in-flight binary
# is not corrupted.
#
# Usage:
#   ./install-remote.sh                  # install latest release
#   WAVE_WATCHER_VERSION=v0.1.0 ./install-remote.sh
#   ./install-remote.sh --local <path>   # install a locally-built binary

set -euo pipefail

REPO="Wave-Engineering/claudecode-workflow"
BINARY_NAME="wave-watcher"
INSTALL_DIR="${HOME}/.local/bin"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"

LOCAL_PATH=""
for arg in "$@"; do
	case "$arg" in
	--local)
		shift || true
		LOCAL_PATH="${1:-}"
		shift || true
		;;
	--help | -h)
		echo "Usage: install-remote.sh [--local <path>]"
		echo "  --local <path>  Install a locally-built binary instead of downloading"
		echo "  WAVE_WATCHER_VERSION=...  Override release tag"
		exit 0
		;;
	esac
done

mkdir -p "${INSTALL_DIR}"

if [[ -n "${LOCAL_PATH}" ]]; then
	if [[ ! -f "${LOCAL_PATH}" ]]; then
		echo "wave-watcher: local path does not exist: ${LOCAL_PATH}" >&2
		exit 1
	fi
	TMP="${INSTALL_DIR}/${BINARY_NAME}.tmp.$$"
	trap 'rm -f "${TMP}"' EXIT
	cp -f "${LOCAL_PATH}" "${TMP}"
	chmod +x "${TMP}"
	mv -f "${TMP}" "${INSTALL_DIR}/${BINARY_NAME}"
	trap - EXIT
	echo "wave-watcher: installed local build to ${INSTALL_DIR}/${BINARY_NAME}"
else
	OS="$(uname -s)"
	ARCH="$(uname -m)"
	case "${OS}-${ARCH}" in
	Linux-x86_64) PLATFORM="linux-x64" ;;
	Darwin-x86_64) PLATFORM="darwin-x64" ;;
	Darwin-arm64) PLATFORM="darwin-arm64" ;;
	*)
		echo "wave-watcher: unsupported platform: ${OS}-${ARCH}" >&2
		exit 1
		;;
	esac

	TAG="${WAVE_WATCHER_VERSION:-}"
	if [[ -z "${TAG}" ]]; then
		TAG=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" |
			grep '"tag_name"' | head -1 | sed 's/.*"tag_name": "\(.*\)".*/\1/')
	fi
	if [[ -z "${TAG}" ]]; then
		echo "wave-watcher: could not determine release tag (set WAVE_WATCHER_VERSION)" >&2
		exit 1
	fi
	URL="https://github.com/${REPO}/releases/download/${TAG}/${BINARY_NAME}-${PLATFORM}"
	echo "wave-watcher: downloading ${URL}"
	TMP="${INSTALL_DIR}/${BINARY_NAME}.tmp.$$"
	trap 'rm -f "${TMP}"' EXIT
	curl -fsSL --progress-bar "${URL}" -o "${TMP}"
	chmod +x "${TMP}"
	mv -f "${TMP}" "${INSTALL_DIR}/${BINARY_NAME}"
	trap - EXIT
	echo "wave-watcher: installed ${TAG} to ${INSTALL_DIR}/${BINARY_NAME}"
fi

# Install systemd user unit if systemd is present.
SYSTEMD_UNIT_SRC="$(dirname "$0")/systemd/wave-watcher.service"
if [[ -f "${SYSTEMD_UNIT_SRC}" ]] && command -v systemctl >/dev/null 2>&1; then
	mkdir -p "${SYSTEMD_USER_DIR}"
	cp -f "${SYSTEMD_UNIT_SRC}" "${SYSTEMD_USER_DIR}/wave-watcher.service"
	systemctl --user daemon-reload || true
	echo "wave-watcher: systemd user unit installed at ${SYSTEMD_USER_DIR}/wave-watcher.service"
	echo "  enable + start: systemctl --user enable --now wave-watcher"
fi

case ":${PATH}:" in
*":${INSTALL_DIR}:"*) ;;
*)
	echo ""
	echo "wave-watcher: ${INSTALL_DIR} is not on PATH; add it to your shell profile."
	;;
esac
