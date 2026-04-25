#!/usr/bin/env bash
# Bootstrap the standard group::value label taxonomy on a GitLab project.
# Idempotent — POST first, then PUT on 409 (already exists) to update.
#
# Mirrors scripts/bootstrap-repo-labels.sh (the GitHub equivalent). Same
# taxonomy, same colors, same descriptions. Differences:
#   - GitLab requires color with leading '#'
#   - No `--force` flag on `glab label create` — use the REST API for upsert
set -euo pipefail

usage() {
	cat <<'EOF'
Usage: bootstrap-repo-labels-gitlab.sh --repo GROUP/[NAMESPACE/]REPO [--waves N] [--dry-run] [-h|--help]

Creates or updates the standard group::value label taxonomy (type, priority,
urgency, size, severity, wave) on a GitLab project.

Required:
  --repo PATH         Target project path (e.g., 'analogicdev/internal/tools/blueshift/blueshift-docmancer-ui')

Options:
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
	echo "--repo is required (GitLab project path, e.g., group/project)" >&2
	usage >&2
	exit 2
fi

if ! [[ "$waves" =~ ^[0-9]+$ ]] || ((waves < 1)); then
	echo "--waves must be a positive integer (got: $waves)" >&2
	exit 2
fi

if ! command -v python3 &>/dev/null; then
	echo "python3 is required for URL encoding but was not found in PATH" >&2
	exit 1
fi

# URL-encode the project path for use in API endpoints
url_encode() {
	python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"
}

repo_encoded=$(url_encode "$repo")

# Canonical taxonomy. Format: name|color(hex, no #)|description
# Mirrors scripts/bootstrap-repo-labels.sh exactly.
labels=(
	"type::feature|0E8A16|New functionality"
	"type::bug|D93F0B|Defect"
	"type::chore|FBCA04|Maintenance, refactoring, dependency updates"
	"type::docs|0075CA|Documentation-only changes"
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

echo "Target project: $repo"
echo "Labels to apply: ${#labels[@]} (including wave::1..${waves})"
if ((dry_run)); then
	echo "DRY RUN — no API calls will be made"
fi
echo

created=0
updated=0
failed=0

for entry in "${labels[@]}"; do
	IFS='|' read -r name color desc <<<"$entry"
	if ((dry_run)); then
		printf '  [dry] %-22s #%s  %s\n' "$name" "$color" "$desc"
		continue
	fi

	# Try POST first (create). GitLab returns 409 if the label already exists.
	# Redirect order is `>/dev/null 2>&1` — reversing it bleeds glab's stderr
	# into the captured status string.
	create_status=$(glab api -X POST "projects/$repo_encoded/labels" \
		-f "name=$name" \
		-f "color=#$color" \
		-f "description=$desc" \
		--silent >/dev/null 2>&1 && echo "created" || echo "failed")

	if [[ "$create_status" == "created" ]]; then
		printf '  [new] %-22s #%s\n' "$name" "$color"
		created=$((created + 1))
		continue
	fi

	# POST failed — try PUT (update existing). Encode the label name for the URL.
	name_encoded=$(url_encode "$name")
	update_status=$(glab api -X PUT "projects/$repo_encoded/labels/$name_encoded" \
		-f "new_name=$name" \
		-f "color=#$color" \
		-f "description=$desc" \
		--silent >/dev/null 2>&1 && echo "updated" || echo "failed")

	if [[ "$update_status" == "updated" ]]; then
		printf '  [upd] %-22s #%s\n' "$name" "$color"
		updated=$((updated + 1))
	else
		printf '  [ERR] %-22s #%s  (POST and PUT both failed)\n' "$name" "$color" >&2
		failed=$((failed + 1))
	fi
done

echo
if ((dry_run)); then
	echo "Dry run complete. ${#labels[@]} labels would be applied."
	exit 0
fi

total=$((created + updated))
echo "Created: $created    Updated: $updated    Failed: $failed    (total applied: $total / ${#labels[@]})"
if ((failed == ${#labels[@]})); then
	echo >&2
	echo "All API calls failed — likely cause: glab not authenticated, project path wrong, or no permission." >&2
	echo "Verify: glab auth status; glab api projects/$repo_encoded -X GET" >&2
fi
if ((failed > 0)); then
	exit 1
fi
