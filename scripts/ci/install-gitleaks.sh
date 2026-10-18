#!/usr/bin/env bash
# install-gitleaks.sh — install the kit's pinned gitleaks into <dest_dir> (#1234).
#
# secret-scan-gate.sh fails closed without gitleaks, so the kit has to ship it. One
# script does it for every consumer: ./install (into ~/.local/bin), CI (before the test
# lane), the tests and the container image, which runs this same script: one pin, so
# none of them can drift from the others.
#
# The sha256 of each tarball is PINNED HERE, not read from the release's own
# checksums.txt. That file is an asset of the same mutable release, fetched over the
# same channel: anyone who could swap the tarball could swap it too. A pin in this repo
# catches a swapped asset; a downloaded checksum only catches a truncated one.
#
# Idempotent: exits 0 without downloading when <dest_dir>/gitleaks is already the
# pinned version. Bash-3.2-safe (./install runs on stock macOS).
#
# Usage: install-gitleaks.sh <dest_dir>
# Exit:  0 installed or already current; 1 download/verify/extract failed;
#        2 usage or unsupported platform
set -uo pipefail

GITLEAKS_VERSION="8.30.1"

dest="${1:-}"
if [[ -z "$dest" ]]; then
	echo "usage: install-gitleaks.sh <dest_dir>" >&2
	exit 2
fi

case "$(uname -s)" in
Linux) os=linux ;;
Darwin) os=darwin ;;
*)
	echo "install-gitleaks: unsupported OS $(uname -s)" >&2
	exit 2
	;;
esac
case "$(uname -m)" in
x86_64 | amd64) arch=x64 ;;
arm64 | aarch64) arch=arm64 ;;
*)
	echo "install-gitleaks: unsupported architecture $(uname -m)" >&2
	exit 2
	;;
esac

case "${os}_${arch}" in
linux_x64) want=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb ;;
linux_arm64) want=e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080 ;;
darwin_x64) want=dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709 ;;
darwin_arm64) want=b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5 ;;
esac

if [[ -x "$dest/gitleaks" ]] && [[ "$("$dest/gitleaks" version 2>/dev/null)" == *"$GITLEAKS_VERSION"* ]]; then
	echo "install-gitleaks: $dest/gitleaks is already $GITLEAKS_VERSION"
	exit 0
fi

asset="gitleaks_${GITLEAKS_VERSION}_${os}_${arch}.tar.gz"
url="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/${asset}"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/install-gitleaks.XXXXXX")" || exit 1
trap 'rm -rf "$tmp"' EXIT

if ! curl -fsSL "$url" -o "$tmp/$asset"; then
	echo "install-gitleaks: download failed: $url" >&2
	exit 1
fi

if command -v sha256sum >/dev/null 2>&1; then
	got="$(sha256sum "$tmp/$asset" | awk '{print $1}')"
else
	got="$(shasum -a 256 "$tmp/$asset" | awk '{print $1}')"
fi
if [[ "$got" != "$want" ]]; then
	echo "install-gitleaks: sha256 mismatch for $asset (want $want, got $got)" >&2
	exit 1
fi

if ! tar -C "$tmp" -xzf "$tmp/$asset" gitleaks; then
	echo "install-gitleaks: could not extract gitleaks from $asset" >&2
	exit 1
fi
mkdir -p "$dest" && install -m 0755 "$tmp/gitleaks" "$dest/gitleaks" || exit 1
echo "install-gitleaks: installed gitleaks $GITLEAKS_VERSION to $dest/gitleaks"
