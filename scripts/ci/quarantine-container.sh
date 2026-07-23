#!/usr/bin/env bash
# quarantine-container.sh — quarantine a broken :edge container + roll back to
# :stable losslessly (Story 3.2 / #971, Dev Spec §4.6 / §5.7, R-02/R-17).
#
# The remediation the flight surgeon triggers: the surgeon (Story 3.1) DETECTS a
# broken :edge container from the host and emits should_quarantine=true; this
# wrapper ACTS on that verdict — stop → docker rm → recreate on :stable — while a
# unit-tested planner proves the rollback loses no durable state BEFORE the
# destructive rm runs.
#
# The DECISION + the lossless PROOF live in
# containers/oakandwave-workflow/quarantine.py (it refuses a lossy rm: any durable
# RW state not on a host-backed bind-mount is a fail-loud refusal). This wrapper
# only INSPECTS the container, hands the planner the surgeon's verdict, and APPLIES
# the plan (stop / rm-without-`-v` / recreate) — the logic stays in the tested
# module, never in this shell (project rule).
#
# Lossless because the container filesystem is a disposable RTE and ALL durable
# state is host-backed (R-01): docker rm destroys only the writable layer; every
# host-backed bind-mount source survives on the host and the recreate re-attaches
# the identical sources on :stable (§5.6 rollback = repoint at the :stable digest).
#
# Inputs (env):
#   CONTAINER_ID        the broken :edge container to quarantine (required).
#   SHOULD_QUARANTINE   the flight surgeon's verdict; MUST be "true" to proceed —
#                       this wrapper never quarantines a container the surgeon did
#                       not flag (a healthy one, or a dev-mode breakage excluded by
#                       R-22). Default: unset ⇒ abort.
#   STABLE_REF          the :stable moving tag to resolve, registry/image:stable
#                       (default: derived from IMAGE_REPO + STABLE_TAG).
#   IMAGE_REPO          registry/image for the fleet image
#                       (default: ghcr.io/wave-engineering/oakandwave-workflow).
#   STABLE_TAG          the moving tag to roll back to (default: stable).
#   OAW_QUARANTINE_LEDGER   append the quarantine record here so the promotion gate's
#                       zero-quarantines condition (R-07) can read it
#                       (default: ~/.oaw/quarantine/ledger.jsonl).
#   QUARANTINE_DRY_RUN  "true" ⇒ inspect + plan + print, do NOT stop/rm/recreate
#                       (needs OAW_CONTAINER_INSPECT + OAW_STABLE_RESOLVED_REF so it
#                       runs without docker — unit-testable).
#
# Injected resolution seams (used verbatim when set; else resolved via docker):
#   OAW_STABLE_RESOLVED_REF   :stable's immutable digest (skips docker pull/inspect).
#   OAW_CONTAINER_INSPECT     a file holding `docker inspect <cid>` JSON (skips the
#                             live inspect — lets a test drive the whole plan path).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$HERE/../.." && pwd)"
QUARANTINE_PY="$REPO_DIR/containers/oakandwave-workflow/quarantine.py"

CONTAINER_ID="${CONTAINER_ID:-}"
IMAGE_REPO="${IMAGE_REPO:-ghcr.io/wave-engineering/oakandwave-workflow}"
STABLE_TAG="${STABLE_TAG:-stable}"
STABLE_REF="${STABLE_REF:-${IMAGE_REPO}:${STABLE_TAG}}"
LEDGER="${OAW_QUARANTINE_LEDGER:-$HOME/.oaw/quarantine/ledger.jsonl}"
DRY_RUN="${QUARANTINE_DRY_RUN:-false}"

[[ -n "$CONTAINER_ID" ]] || {
	echo "  [!] CONTAINER_ID is required (the broken :edge container to quarantine)" >&2
	exit 1
}

# The surgeon's verdict is the ONLY trigger. Never quarantine a container the
# surgeon did not flag — mirror the planner's own refusal, fail-loud, up front.
if [[ "${SHOULD_QUARANTINE:-}" != "true" ]]; then
	echo "  [!] SHOULD_QUARANTINE != true — refusing. Quarantine acts only on the" >&2
	echo "      flight surgeon's should_quarantine verdict (Dev Spec §5.7)." >&2
	exit 1
fi

# --- 1. Resolve :stable → the immutable rollback digest -----------------------
stable_ref="${OAW_STABLE_RESOLVED_REF:-}"
if [[ -z "$stable_ref" ]]; then
	if [[ "$DRY_RUN" == "true" ]]; then
		echo "  [!] QUARANTINE_DRY_RUN needs OAW_STABLE_RESOLVED_REF" >&2
		exit 1
	fi
	command -v docker >/dev/null 2>&1 || {
		echo "  [!] docker not found — needed to resolve $STABLE_REF" >&2
		exit 1
	}
	echo "==> resolving $STABLE_REF (the :stable rollback target)"
	docker pull "$STABLE_REF" >/dev/null
	stable_ref="$(docker image inspect --format '{{index .RepoDigests 0}}' "$STABLE_REF")"
fi

# --- 2. Inspect the broken container ------------------------------------------
inspect_src="${OAW_CONTAINER_INSPECT:-}"
if [[ -z "$inspect_src" ]]; then
	command -v docker >/dev/null 2>&1 || {
		echo "  [!] docker not found — needed to inspect $CONTAINER_ID" >&2
		exit 1
	}
	inspect_src="$(mktemp)"
	trap 'rm -f "$inspect_src"' EXIT
	docker inspect "$CONTAINER_ID" >"$inspect_src"
fi

# --- 3. Plan the quarantine (lossless proof runs HERE, before any rm) ----------
# The planner refuses (non-zero exit) if the rollback cannot be proven lossless —
# so a plan we can read back is itself the go-ahead for the destructive step.
plan_json="$(python3 "$QUARANTINE_PY" \
	--container-inspect "$inspect_src" \
	--stable-ref "$stable_ref" \
	--should-quarantine \
	--format json)"

read -r name profile recreate_image < <(
	printf '%s' "$plan_json" | python3 -c \
		'import json,sys; p=json.load(sys.stdin); print(p["name"] or p["container_id"], p["profile"] or "unknown", p["recreate_image"])'
)
# The -v args re-attaching every host-backed mount verbatim (newline-delimited).
mapfile -t vol_args < <(
	printf '%s' "$plan_json" | python3 -c \
		'import json,sys; [print(v) for v in json.load(sys.stdin)["recreate_volume_args"]]'
)

echo "==> quarantine plan: $name (profile=$profile) -> recreate on $recreate_image"
echo "    preserving ${#vol_args[@]} host-backed mount(s) — proven lossless"

if [[ "$DRY_RUN" == "true" ]]; then
	echo "==> [dry-run] would: stop $CONTAINER_ID; docker rm $CONTAINER_ID; recreate on $recreate_image"
	printf '%s\n' "$plan_json"
	exit 0
fi

# --- 4. Apply: stop → rm (NO -v) → recreate on :stable ------------------------
# rm is deliberately WITHOUT -v: the destructive step touches ONLY the disposable
# writable layer; host binds are not docker's to remove and any stray volume is
# left intact. Every durable mount is host-backed (proven in step 3), so this loses
# nothing.
echo "==> stopping $CONTAINER_ID"
docker stop "$CONTAINER_ID" >/dev/null || true
echo "==> removing $CONTAINER_ID (disposable RTE — host-backed state survives)"
docker rm "$CONTAINER_ID" >/dev/null

recreate=(docker run -d --label "oaw.profile=${profile}")
[[ -n "$name" ]] && recreate+=(--name "$name")
for v in "${vol_args[@]}"; do
	[[ -n "$v" ]] && recreate+=(-v "$v")
done
recreate+=("$recreate_image")

echo "==> recreating on :stable ($recreate_image), re-attaching the host sources"
new_cid="$("${recreate[@]}")"
echo "==> recreated as $new_cid — durable state intact (§5.6 lossless rollback)"

# --- 5. Ledger the quarantine so the promotion gate holds the bad digest (R-07)
mkdir -p "$(dirname "$LEDGER")"
record="$(python3 "$QUARANTINE_PY" \
	--container-inspect "$inspect_src" \
	--stable-ref "$stable_ref" \
	--should-quarantine \
	--format record)"
printf '%s\n' "$record" >>"$LEDGER"
echo "==> ledgered quarantine -> $LEDGER (the quarantined :edge digest is held from promotion)"

# The one line on stdout is the recreated container id.
echo "$new_cid"
