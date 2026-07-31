#!/usr/bin/env bash
# check-mount-drift.sh — mounts.d/ is the source of truth; a profile is a COPY (#1069).
#
# WHY THIS EXISTS. `mount_resolver.py --format aoe` emits `host:container[:ro]`
# lines and AoE's `sandbox.extra_volumes` consumes exactly that shape — but the
# copy between them is MANUAL, per-profile, and nothing checked it. So mounts.d/
# is the declared truth while the container actually runs on whatever a human last
# pasted.
#
# Observed 2026-07-30 during cut-over prep: `extra_volumes` was `[0 items]` on a
# freshly created profile. Every fragment — memory, secrets, caches — was declared
# and applied to NOTHING. A container launched then would have come up with no
# memory, no secrets and cold caches, and nothing anywhere would have said so.
#
# That is the defect shape this cut-over keeps producing: the manifest declares it,
# the runtime does not have it, and the gap is silent. Same family as the inert
# R-14 check (#1061), trivy scanning zero manifests (#1056), the surgeon reading
# the wrong transcript root (#1064), and a --depth=1 fetch quietly shallowing the
# repo. It is also load-bearing: #1061's secrets mounts and #1064's transcript
# mount are only REAL if they reach extra_volumes.
#
# WHY IT ALSO STATS EVERY SOURCE. mount_resolver deliberately never touches the
# filesystem (sources may not exist yet — see its module docstring), so nothing
# else catches a path that is declared, copied, and simply absent. Docker's
# create-if-missing then materialises it as an empty DIRECTORY, which is how a
# wrong path becomes empty state instead of an error.
#
# WHY IT READS THE PROFILE FILE, NOT `aoe settings`. `aoe settings explain` does
# not resolve profile-scoped overrides — it reports `schema default` for values the
# TUI shows as `(override, inherits: …)`. The TUI is authoritative; the CLI is not
# a usable verification path today.
#
# Usage:
#   scripts/ci/check-mount-drift.sh <profile> [--major N]
#   scripts/ci/check-mount-drift.sh dogfood dev-mode      # several at once
#
# Exit: 0 in sync; 2 usage/unreadable; 3 drift or a missing host source.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$HERE/../.." && pwd)"
RESOLVER="$REPO_DIR/containers/oakandwave-workflow/mount_resolver.py"
PROFILE_ROOT="${AOE_PROFILE_ROOT:-$HOME/.config/agent-of-empires/profiles}"

MAJOR=""
profiles=()
while (($# > 0)); do
	case "$1" in
	--major)
		MAJOR="${2:-}"
		shift 2
		;;
	--major=*)
		MAJOR="${1#*=}"
		shift
		;;
	-h | --help)
		sed -n '2,36p' "${BASH_SOURCE[0]}"
		exit 0
		;;
	*)
		profiles+=("$1")
		shift
		;;
	esac
done

if ((${#profiles[@]} == 0)); then
	echo "usage: check-mount-drift.sh <profile> [<profile>...] [--major N]" >&2
	exit 2
fi

[[ -n "$MAJOR" ]] || MAJOR="$("$HERE/oaw-major.sh")"

expected="$(python3 "$RESOLVER" --major "$MAJOR" --format aoe)" || {
	echo "check-mount-drift: mount_resolver failed for major $MAJOR" >&2
	exit 2
}

fails=0

# --- every declared host source must EXIST -----------------------------------
# Checked once, independent of any profile: a manifest entry pointing at nothing
# is broken whether or not a profile has copied it yet.
while IFS= read -r line; do
	[[ -n "$line" ]] || continue
	src="${line%%:*}"
	if [[ ! -e "$src" ]]; then
		echo "  [MISSING SOURCE] $src" >&2
		echo "      declared in mounts.d/ but absent on this host. Docker would" >&2
		echo "      create it as an EMPTY DIRECTORY at launch, so the container" >&2
		echo "      comes up with that state blank and no error anywhere." >&2
		# Remediation must match the KIND. Four declared sources are FILES, and
		# mkdir -p on those creates a directory where a file belongs — reproducing
		# exactly the failure this message warns about.
		case "$src" in
		*.json | */.env | */discord-bot-token)
			echo "      fix (this one is a FILE):  install -D /dev/null $src" >&2
			;;
		*)
			echo "      fix (this one is a DIR):   mkdir -p $src" >&2
			;;
		esac
		fails=$((fails + 1))
	fi
done <<<"$expected"

# --- each named profile must match the manifest exactly ----------------------
for prof in "${profiles[@]}"; do
	cfg="$PROFILE_ROOT/$prof/config.toml"
	if [[ ! -f "$cfg" ]]; then
		echo "  [NO CONFIG] profile '$prof' has no config.toml at $cfg" >&2
		echo "      An AoE profile with no config inherits the GLOBAL sandbox" >&2
		echo "      settings, so extra_volumes is empty and every mount is inert." >&2
		fails=$((fails + 1))
		continue
	fi

	actual="$(
		python3 - "$cfg" <<-'PY'
			import sys, tomllib
			try:
			    d = tomllib.load(open(sys.argv[1], "rb"))
			except Exception as exc:            # unreadable/invalid TOML is drift too
			    print(f"__ERROR__ {exc}")
			    raise SystemExit(0)
			for v in d.get("sandbox", {}).get("extra_volumes", []):
			    print(v)
		PY
	)"

	if [[ "$actual" == __ERROR__* ]]; then
		echo "  [UNREADABLE] $cfg: ${actual#__ERROR__ }" >&2
		fails=$((fails + 1))
		continue
	fi

	# Compare as SETS: order is not semantically meaningful to docker, and failing
	# on order would train people to ignore this check.
	missing="$(comm -23 <(sort <<<"$expected") <(sort <<<"$actual") | sed '/^$/d')"
	extra="$(comm -13 <(sort <<<"$expected") <(sort <<<"$actual") | sed '/^$/d')"

	# A profile-rendered mount is not mounts.d drift. Ask profiles.py what it
	# renders for this profile rather than spelling its target here — profiles.py
	# owns IMAGE_SKILLS_TARGET, and duplicating it would be exactly the drift this
	# script exists to catch, one layer up.
	profile_mount="$(python3 "$REPO_DIR/containers/oakandwave-workflow/profiles.py" \
		--emit launch --profile "$prof" --major "$MAJOR" --allow-empty-overlay 2>/dev/null |
		tr ' ' '\n' | grep ':/home/ubuntu/' || true)"
	# profiles.py emits the host side with an unexpanded ~; extra_volumes stores it
	# expanded. Normalise before comparing, or the exclusion silently never matches
	# and dev-mode reports permanent false drift.
	# Per-LINE expansion: ${var/#~} anchors to the start of the whole string, so a
	# multi-line emit would leave every line after the first unexpanded and the
	# exclusion would silently stop matching.
	_expanded=""
	while IFS= read -r _pm; do
		[[ -n "$_pm" ]] || continue
		_expanded+="${_pm/#\~/$HOME}"$'\n'
	done <<<"$profile_mount"
	profile_mount="${_expanded%$'\n'}"
	if [[ -n "$profile_mount" && -n "$extra" ]]; then
		extra="$(grep -vxF "$profile_mount" <<<"$extra" || true)"
	fi

	if [[ -n "$missing" || -n "$extra" ]]; then
		echo "  [DRIFT] profile '$prof' does not match mounts.d/ at major $MAJOR" >&2
		[[ -n "$missing" ]] && {
			echo "    declared but NOT in the profile (these mounts do not happen):" >&2
			while IFS= read -r l; do echo "      - $l" >&2; done <<<"$missing"
		}
		[[ -n "$extra" ]] && {
			echo "    in the profile but NOT declared (unreviewed mounts):" >&2
			while IFS= read -r l; do echo "      + $l" >&2; done <<<"$extra"
		}
		echo "    fix — regenerate the paste-ready block and replace [sandbox].extra_volumes in" >&2
		echo "         $cfg :" >&2
		echo "      python3 containers/oakandwave-workflow/mount_resolver.py --major $MAJOR --format aoe-toml" >&2
		fails=$((fails + 1))
	else
		echo "  [OK] profile '$prof' matches mounts.d/ ($(wc -l <<<"$expected") mounts, major $MAJOR)"
	fi
done

if ((fails > 0)); then
	echo "check-mount-drift: $fails problem(s) — mounts.d/ is the source of truth." >&2
	exit 3
fi
echo "check-mount-drift: in sync (major $MAJOR)"
