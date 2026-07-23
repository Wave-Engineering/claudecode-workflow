#!/usr/bin/env bash
# adopt-stable.sh — rolling per-agent :stable adoption at container-recreate
# (Story 2.4 / #969, Dev Spec §4.5 / §5.6 / §5.8, R-08/R-18).
#
# The fleet counterpart to promote-oakandwave-image.sh: promotion *publishes*
# :stable; this runs at a single agent's **container-recreate** boundary and
# adopts it — per-agent, rolling, never mid-session.
#
# This IS the recreate boundary. It resolves the moving :stable tag to its
# immutable digest + version, asks the unit-tested decision module whether to
# adopt, and — on adopt — records the prior digest (so rollback is a repoint,
# §5.6) and emits the digest the next launch (aoe / docker run) should use. It
# NEVER reaches into a running container: a running container is pinned by digest,
# so a :stable retag cannot touch it; only this next-launch resolution adopts the
# new digest. Two agents run this at their own recreate times → rolling, not a
# synchronized flip (R-08).
#
# The DECISION lives in containers/oakandwave-workflow/adoption.py (fail-loud on a
# malformed version, major-cross opt-in). This wrapper only *resolves* :stable and
# *applies* the plan (pin + emit), keeping the adoption logic in Python, never in
# this shell (project rule: decisions in a tested module, not the wrapper).
#
# Inputs (env):
#   STABLE_REF          the :stable moving tag to resolve, registry/image:stable
#                       (default: derived from IMAGE_REPO + STABLE_TAG).
#   IMAGE_REPO          registry/image for the fleet image
#                       (default: ghcr.io/wave-engineering/oakandwave-workflow).
#   STABLE_TAG          the moving tag to adopt (default: stable).
#   OAW_STATE_DIR       per-agent adoption state dir (default: ~/.oaw/adoption).
#                       Holds `current` (the adopted digest) + `rollback` (the
#                       prior digest, for a §5.6 repoint).
#   ALLOW_MAJOR_CROSS   "true" ⇒ opt into a major cross (§5.8); default false ⇒ a
#                       differing major HOLDs (agents coexist in isolated
#                       ~/.oaw/state/<major>/ namespaces until a deliberate cross).
#   ADOPT_DRY_RUN       "true" ⇒ resolve + decide + print the plan, do NOT pull,
#                       pin, or recreate (unit-testable without docker).
#
# Injected resolution seams (used verbatim when set; else resolved via docker) —
# these make the wrapper testable and let a caller supply already-resolved values:
#   OAW_STABLE_RESOLVED_REF / OAW_STABLE_VERSION   :stable's digest + semver.
#   OAW_CURRENT_REF        / OAW_CURRENT_VERSION   the agent's current digest +
#                          semver (default: read from OAW_STATE_DIR/current, or —
#                          on a first-ever adoption — empty ⇒ bootstrap-adopt).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$HERE/../.." && pwd)"
ADOPTION_PY="$REPO_DIR/containers/oakandwave-workflow/adoption.py"

IMAGE_REPO="${IMAGE_REPO:-ghcr.io/wave-engineering/oakandwave-workflow}"
STABLE_TAG="${STABLE_TAG:-stable}"
STABLE_REF="${STABLE_REF:-${IMAGE_REPO}:${STABLE_TAG}}"
OAW_STATE_DIR="${OAW_STATE_DIR:-$HOME/.oaw/adoption}"
DRY_RUN="${ADOPT_DRY_RUN:-false}"

allow_cross=()
[[ "${ALLOW_MAJOR_CROSS:-false}" == "true" ]] && allow_cross=(--allow-major-cross)

# --- Read the OCI version label off a resolved image ref ----------------------
image_version() {
	local ref="$1"
	local labels
	labels="$(docker image inspect --format '{{json .Config.Labels}}' "$ref" 2>/dev/null)" || return 1
	printf '%s' "$labels" | python3 -c \
		'import json,sys; print((json.load(sys.stdin) or {}).get("org.opencontainers.image.version") or "")'
}

# --- 1. Resolve :stable → immutable digest + version --------------------------
# A moving tag is resolved to the digest it points at NOW (the "pull at recreate"),
# so the agent adopts the exact bytes promotion blessed — never a re-moving tag.
stable_ref="${OAW_STABLE_RESOLVED_REF:-}"
stable_version="${OAW_STABLE_VERSION:-}"
if [[ -z "$stable_ref" || -z "$stable_version" ]]; then
	if [[ "$DRY_RUN" == "true" ]]; then
		echo "  [!] ADOPT_DRY_RUN needs OAW_STABLE_RESOLVED_REF + OAW_STABLE_VERSION" >&2
		exit 1
	fi
	command -v docker >/dev/null 2>&1 || {
		echo "  [!] docker not found — needed to resolve $STABLE_REF at recreate" >&2
		exit 1
	}
	echo "==> resolving $STABLE_REF at container-recreate (pull the moving tag)"
	docker pull "$STABLE_REF" >/dev/null
	# The digest :stable currently points at (registry/image@sha256:…).
	stable_ref="$(docker image inspect --format '{{index .RepoDigests 0}}' "$STABLE_REF")"
	stable_version="$(image_version "$STABLE_REF")"
fi
[[ -n "$stable_version" ]] || {
	echo "  [!] $STABLE_REF carries no org.opencontainers.image.version label" >&2
	exit 1
}

# --- 2. Determine the agent's CURRENT ref + version (per-agent state) ----------
current_ref="${OAW_CURRENT_REF:-}"
current_version="${OAW_CURRENT_VERSION:-}"
if [[ -z "$current_ref" && -f "$OAW_STATE_DIR/current" ]]; then
	current_ref="$(cat "$OAW_STATE_DIR/current")"
fi
if [[ -z "$current_version" && -f "$OAW_STATE_DIR/current-version" ]]; then
	current_version="$(cat "$OAW_STATE_DIR/current-version")"
fi

# First-ever adoption: no prior version to reason about → bootstrap onto :stable.
if [[ -z "$current_version" ]]; then
	echo "==> no prior adoption recorded — bootstrap-adopt $stable_ref ($stable_version)"
	action="adopt"
	launch_ref="$stable_ref"
	prior_ref=""
else
	# --- 3. Delegate the adopt/hold/noop decision to the tested module --------
	plan_json="$(python3 "$ADOPTION_PY" \
		--current-ref "$current_ref" --current-version "$current_version" \
		--target-ref "$stable_ref" --target-version "$stable_version" \
		--format json "${allow_cross[@]}")"
	read -r action launch_ref prior_ref < <(
		printf '%s' "$plan_json" | python3 -c \
			'import json,sys; p=json.load(sys.stdin); print(p["action"], p["launch_ref"], p.get("prior_ref",""))'
	)
fi

echo "==> adoption plan: action=$action launch=$launch_ref (current=${current_version:-none} -> stable=$stable_version)"

if [[ "$DRY_RUN" == "true" ]]; then
	echo "==> [dry-run] would launch $launch_ref at recreate (no pin, no recreate)"
	echo "$launch_ref"
	exit 0
fi

# --- 4. Apply the plan: pin for rollback, record the adopted digest -----------
# On adopt, `rollback` keeps the PRIOR digest so a §5.6 rollback is a plain
# repoint; `current` records what this recreate launches. On hold/noop nothing
# moves — the agent stays on its current major (coexistence preserved).
mkdir -p "$OAW_STATE_DIR"
if [[ "$action" == "adopt" ]]; then
	[[ -n "$prior_ref" ]] && printf '%s\n' "$prior_ref" >"$OAW_STATE_DIR/rollback"
	printf '%s\n' "$launch_ref" >"$OAW_STATE_DIR/current"
	printf '%s\n' "$stable_version" >"$OAW_STATE_DIR/current-version"
	echo "==> adopted $launch_ref ($stable_version); rollback pin -> ${prior_ref:-<none>}"
else
	echo "==> $action — staying on $current_ref ($current_version); :stable held for an opt-in cross"
fi

# The one line on stdout is the image ref the NEXT launch (aoe / docker run) uses
# at this recreate — the recreate boundary consumes it; a running session never does.
echo "$launch_ref"
