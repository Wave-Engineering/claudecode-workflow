#!/usr/bin/env bash
# Bootstrap the standard group::value label taxonomy on a GitHub repo.
# Idempotent — uses `gh label create --force` which creates or updates.
set -euo pipefail

usage() {
	cat <<'EOF'
Usage: bootstrap-repo-labels.sh [--repo OWNER/REPO] [--waves N] [--dry-run] [-h|--help]

Creates or updates the standard group::value label taxonomy (type, priority,
urgency, size, severity, wave) on a GitHub repo.

Options:
  --repo OWNER/REPO   Target repo (default: current repo via gh)
  --waves N           Number of wave::N labels to create (default: 9)
  --dry-run           Print planned actions, make no API calls
  -h, --help          Show this help
EOF
}

repo=""
waves=9
dry_run=0

while [[ $# -gt 0 ]]; do
	case "$1" in
	--repo)
		repo="$2"
		shift 2
		;;
	--waves)
		waves="$2"
		shift 2
		;;
	--dry-run)
		dry_run=1
		shift
		;;
	-h | --help)
		usage
		exit 0
		;;
	*)
		echo "unknown flag: $1" >&2
		usage >&2
		exit 2
		;;
	esac
done

if [[ -z "$repo" ]]; then
	repo=$(gh repo view --json nameWithOwner -q .nameWithOwner)
fi

if ! [[ "$waves" =~ ^[0-9]+$ ]] || ((waves < 1)); then
	echo "--waves must be a positive integer (got: $waves)" >&2
	exit 2
fi

# Canonical taxonomy. Format: name|color(hex, no #)|description
# Colors match what is currently in use on claudecode-workflow and mirror
# the /issue skill's label reference. Per-value shading (severity, priority)
# uses a red→yellow→green gradient so the group reads at a glance.
labels=(
	"type::feature|0E8A16|New functionality"
	"type::story|0E8A16|New functionality (feature alias)"
	"type::bug|D93F0B|Defect"
	"type::chore|FBCA04|Maintenance, refactoring, dependency updates"
	"type::doc|0075CA|Documentation-only changes"
	"type::epic|5319E7|Parent issue tracking a body of work"

	"priority::critical|B60205|Drop everything"
	"priority::high|D93F0B|Must do this iteration"
	"priority::medium|FBCA04|Should do soon"
	"priority::low|0E8A16|Backlog"

	"urgency::immediate|B60205|Time-critical now"
	"urgency::soon|D93F0B|Near-term deadline"
	"urgency::normal|FBCA04|No special time pressure"
	"urgency::eventual|0E8A16|No deadline"

	"size::S|C5DEF5|Few lines, one file"
	"size::M|0075CA|Multiple files, few hours"
	"size::L|5319E7|Multiple components, roughly a day"
	"size::XL|B60205|Multi-day, likely needs decomposition"

	"severity::critical|B60205|System down, data corruption, security"
	"severity::major|D93F0B|Core broken, no workaround"
	"severity::minor|FBCA04|Impaired but workaround exists"
	"severity::cosmetic|C5DEF5|Visual or UX annoyance"
)

for ((i = 1; i <= waves; i++)); do
	labels+=("wave::${i}|5319E7|Wave ${i}")
done

echo "Target repo: $repo"
echo "Labels to apply: ${#labels[@]} (including wave::1..${waves})"
if ((dry_run)); then
	echo "DRY RUN — no API calls will be made"
fi
echo

# --- One-time label renames (old name -> new name), applied BEFORE the
# create-or-update loop below (cc-workflow#1191 code review). `gh label
# create --force` creates-or-updates BY NAME — it cannot rename, so an
# already-bootstrapped repo re-run against a taxonomy change would
# otherwise silently keep the old label (still attached to its issues)
# alongside a freshly-created new one: a split taxonomy, not a migration.
# Renaming first means the create-or-update loop's entry for the new name
# just updates the color/description of the label the rename already
# produced, and every existing issue's label assignment carries forward
# (GitHub associates by label ID, not name).
renames=(
	"type::docs|type::doc"
)
if ((dry_run)); then
	for pair in "${renames[@]}"; do
		printf '  [dry-rename] %s -> %s (if present)\n' "${pair%%|*}" "${pair##*|}"
	done
else
	for pair in "${renames[@]}"; do
		old="${pair%%|*}"
		new="${pair##*|}"
		# Direct per-label existence probe via the REST API, NOT `gh label
		# list`. `gh label list --json name` has a real, observed propagation
		# lag after a label mutation (cc-workflow#1191 code review) — a label
		# created/renamed moments earlier can be invisible to the list
		# endpoint while `gh api repos/.../labels/<name>` (a single-resource
		# GET) is immediately consistent. Verified live: a throwaway label
		# was 404 via list but 200 via direct GET seconds after creation.
		if gh api "repos/$repo/labels/$old" >/dev/null 2>&1; then
			if gh label edit "$old" --name "$new" --repo "$repo" >/dev/null 2>&1; then
				printf '  [renamed] %-22s -> %s\n' "$old" "$new"
			else
				printf '  [FAIL] could not rename %s -> %s\n' "$old" "$new" >&2
			fi
		fi
	done
fi

applied=0
failed=0
for entry in "${labels[@]}"; do
	IFS='|' read -r name color desc <<<"$entry"
	if ((dry_run)); then
		printf '  [dry] %-22s #%s  %s\n' "$name" "$color" "$desc"
		continue
	fi
	if gh label create "$name" --color "$color" --description "$desc" --force --repo "$repo" >/dev/null 2>&1; then
		printf '  [ok]  %-22s #%s\n' "$name" "$color"
		applied=$((applied + 1))
	else
		printf '  [FAIL] %-22s #%s\n' "$name" "$color" >&2
		failed=$((failed + 1))
	fi
done

echo
if ((dry_run)); then
	echo "Dry run complete. ${#labels[@]} labels would be applied."
	exit 0
fi

echo "Applied: $applied / ${#labels[@]}    Failed: $failed"
if ((failed > 0)); then
	exit 1
fi
