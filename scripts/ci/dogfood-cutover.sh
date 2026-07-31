#!/usr/bin/env bash
# dogfood-cutover.sh — cut the OaW dev team onto :edge in the dogfood profile with
# the flight surgeon watching (Story 4.2 / #975, Dev Spec §4.3, R-21/R-22/R-07).
#
# This is the mechanical entrypoint for the dogfood cutover (§4.3): launch each
# target workspace as a dogfood-profile container on :edge, and start the flight
# surgeon watching them so a broken candidate is caught (surgeon.py). Soak accrual is
# now auto-wired: run scripts/ci/soak-accrual-bridge.sh (#1008) periodically alongside
# this cutover — it drives the surgeon over the live ring and feeds each running
# dogfood session's clean span to soak_ledger, so the gate's SOAK_HOURS fills. The
# pieces it composes are already unit-proven; this wrapper only *plans* and — under an
# explicit operator apply — *applies* the launches.
#
# The DECISIONS live in tested modules, never in this shell (project rule):
#   * the dogfood launch args (the oaw.profile=dogfood label, overlay OFF)  —
#     containers/oakandwave-workflow/profiles.py --emit launch --profile dogfood
#   * the health verdict the surgeon acts on                                —
#     scripts/flight-surgeon/surgeon.py
#   * clean-span → soak record                                              —
#     containers/oakandwave-workflow/soak_ledger.py
#
# SAFETY — plan-by-default (this cuts LIVE fleet agents onto a candidate image, so
# it must never launch anything as a side effect of being run):
#   The script DEFAULTS TO A DRY-RUN PLAN — it prints the exact `aoe add` line per
#   workspace and the surgeon watch command, and launches NOTHING. Real launches
#   happen ONLY when DOGFOOD_CUTOVER_APPLY=true AND aoe/docker are present — the
#   operator's deliberate, per-cutover go (mirrors PROMOTE_DRY_RUN / ADOPT_DRY_RUN
#   in the sibling wrappers). A red config (missing image, no workspaces) fails
#   loud; it never silently no-ops into a false "cutover done".
#
# Inputs (env):
#   EDGE_REF            the candidate image the dogfood ring runs (default
#                       ghcr.io/wave-engineering/oakandwave-workflow:edge).
#   CUTOVER_WORKSPACES  whitespace/newline-separated workspace paths to cut over
#                       (required — the OaW dev team's working trees).
#   OAW_MAJOR           the kit major for the dogfood profile's <major> mounts.
#                       DERIVED from the repo tag via scripts/ci/oaw-major.sh; set
#                       explicitly to override. There is no literal default — a
#                       hardcoded major is the #1067 defect, and it fails silently
#                       as empty state rather than loudly.
#   OAW_SOAK_LEDGER     the FlightDeck soak ledger the gate reads (default
#                       ~/.oaw/soak/ledger.jsonl). This script does not write it; the
#                       soak-accrual bridge (scripts/ci/soak-accrual-bridge.sh, #1008)
#                       does — run it periodically alongside this cutover.
#   SURGEON_TRANSCRIPTS_ROOT  root the surgeon resolves host-backed SANDBOX transcripts
#                             (default ~/.oaw/state/$OAW_MAJOR/transcripts; must NOT
#                             be ~/.claude/projects — that is the live fleet's store)
#   DOGFOOD_CUTOVER_APPLY  "true" ⇒ actually launch (operator go); default false ⇒
#                       plan only, launch nothing.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$HERE/../.." && pwd)"
PROFILES_PY="$REPO_DIR/containers/oakandwave-workflow/profiles.py"
SURGEON_PY="$REPO_DIR/scripts/flight-surgeon/surgeon.py"

EDGE_REF="${EDGE_REF:-ghcr.io/wave-engineering/oakandwave-workflow:edge}"
# Derived, never a literal (#1067). A hardcoded major shares one state namespace
# across kit generations (defeating R-20) and, when wrong, fails SILENTLY as
# empty state rather than loudly. --check also refuses an unprovisioned major.
OAW_MAJOR="$("$HERE/oaw-major.sh")"
export OAW_MAJOR # surgeon.py narrows its default transcripts root from this
OAW_SOAK_LEDGER="${OAW_SOAK_LEDGER:-$HOME/.oaw/soak/ledger.jsonl}"
# Sandbox transcripts are host-backed under ~/.oaw/state/<major>/transcripts
# (mounts.d/05-transcripts.toml). This USED to default to $HOME/.claude/projects
# — the live fleet's own store — which does not merely miss: the surgeon resolves
# the newest .jsonl matching the workspace slug, so a container picked up a NATIVE
# session's transcript and was classified on it (#1064). The major is known here,
# so pass the exact root rather than the module's wider default.
SURGEON_TRANSCRIPTS_ROOT="${SURGEON_TRANSCRIPTS_ROOT:-$HOME/.oaw/state/$OAW_MAJOR/transcripts}"
APPLY="${DOGFOOD_CUTOVER_APPLY:-false}"

# --- Fail-closed on a red config ----------------------------------------------
: "${CUTOVER_WORKSPACES:?CUTOVER_WORKSPACES must list the OaW workspace paths to cut over}"

# The dogfood launch args (label + overlay-OFF) from the tested profile module —
# NEVER hand-spelled here, so "dogfood is image-only" stays a property of profiles.py.
dogfood_args="$(python3 "$PROFILES_PY" --emit launch --profile dogfood --major "$OAW_MAJOR")"

echo "==> dogfood cutover onto $EDGE_REF (major $OAW_MAJOR)"
echo "    dogfood launch args (from profiles.py): $dogfood_args"

# --- Plan the per-workspace launches ------------------------------------------
# Each workspace becomes one dogfood-profile sandbox on :edge. `aoe add --sandbox`
# is the one-container-per-session seam (TC-1); the profile args stamp
# oaw.profile=dogfood so the surgeon and the gate both filter on it (R-22).
# Refuse an unprovisioned major before the FIRST real launch — not on the plan
# path. A wrong/absent major is silent (docker materialises each missing bind
# source as an empty dir, so memory and caches come up blank), so the guard has to
# fire; but gating the documented dry run on host provisioning would break its
# "launches NOTHING" contract and make it fail on any checkout without ~/.oaw.
if [[ "$APPLY" == "true" ]]; then
	"$HERE/oaw-major.sh" --check >/dev/null
fi

launched=0
for ws in $CUTOVER_WORKSPACES; do
	launch_cmd=(aoe add --sandbox --sandbox-image "$EDGE_REF")
	# shellcheck disable=SC2206 # intentional word-split: profiles.py emits shell args
	launch_cmd+=($dogfood_args "$ws")
	echo "==> [$ws] ${launch_cmd[*]}"
	if [[ "$APPLY" == "true" ]]; then
		command -v aoe >/dev/null 2>&1 || {
			echo "  [!] DOGFOOD_CUTOVER_APPLY=true but aoe not on PATH — cannot launch" >&2
			exit 1
		}
		"${launch_cmd[@]}"
		launched=$((launched + 1))
	fi
done

# --- Start the surgeon watching the dogfood ring ------------------------------
# The surgeon reads each :edge container's host-backed transcript (fate-independent,
# R-15), filters on the profile label (dev-mode excluded, R-22), and fails non-zero
# on a quarantine-eligible break so a cron/watcher can trigger quarantine.
surgeon_cmd=(
	python3 "$SURGEON_PY" --live
	--transcripts-root "$SURGEON_TRANSCRIPTS_ROOT"
	--fail-on-quarantine
)
echo "==> flight surgeon watch command: ${surgeon_cmd[*]}"
echo "    soak ledger (the gate reads it): $OAW_SOAK_LEDGER"
echo "    accrue soak from the live ring: scripts/ci/soak-accrual-bridge.sh (#1008)"

if [[ "$APPLY" != "true" ]]; then
	echo "==> [plan] DOGFOOD_CUTOVER_APPLY!=true — planned $(echo "$CUTOVER_WORKSPACES" | wc -w) launch(es), launched 0, started no surgeon."
	echo "    Re-run with DOGFOOD_CUTOVER_APPLY=true (operator go) to cut over for real."
	exit 0
fi

echo "==> apply: launched $launched dogfood container(s); starting the surgeon watch"
exec "${surgeon_cmd[@]}"
