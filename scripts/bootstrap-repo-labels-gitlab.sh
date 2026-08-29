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

echo "Target project: $repo"
echo "Labels to apply: ${#labels[@]} (including wave::1..${waves})"
if ((dry_run)); then
	echo "DRY RUN — no API calls will be made"
fi
echo

# --- One-time label renames (old name -> new name), applied BEFORE the
# create-or-update loop below (cc-workflow#1191 code review, mirrors the
# GitHub script). The POST-then-PUT loop below is keyed by NAME on both
# ends (PUT's own `new_name=$name` sets the target to the SAME name it
# already tried), so it cannot migrate an old label to a new one — an
# already-bootstrapped project re-run against a taxonomy change would
# create the new label alongside the old one, still attached to its
# issues: a split taxonomy, not a migration. GitLab's label PUT accepts a
# DIFFERING new_name, so the rename itself is a normal PUT once directed
# at the old name.
renames=(
	"type::docs|type::doc"
)
created=0
updated=0
failed=0
if ((dry_run)); then
	for pair in "${renames[@]}"; do
		printf '  [dry-rename] %s -> %s (if present)\n' "${pair%%|*}" "${pair##*|}"
	done
else
	for pair in "${renames[@]}"; do
		old="${pair%%|*}"
		new="${pair##*|}"
		old_encoded=$(url_encode "$old")
		# Direct per-label existence probe (single-resource GET, supported
		# since GitLab 12.4 with a URL-encoded title as the label_id), NOT a
		# bulk `projects/:id/labels` list+grep. Mirrors the GitHub script's
		# fix (cc-workflow#1191 code review): `gh label list` was proven live
		# to lag a fresh mutation while the single-resource GET was
		# immediately consistent — the bulk-list pattern here carries the
		# same structural risk, so it's replaced on the same reasoning.
		old_exists=0
		glab api "projects/$repo_encoded/labels/$old_encoded" >/dev/null 2>&1 && old_exists=1
		if ((! old_exists)); then
			continue # nothing to migrate — never bootstrapped, or already renamed
		fi
		new_encoded=$(url_encode "$new")
		new_exists=0
		glab api "projects/$repo_encoded/labels/$new_encoded" >/dev/null 2>&1 && new_exists=1
		if ((new_exists)); then
			# Both names live on the project already — e.g. GitLab's issues
			# API auto-creates unknown labels on issue creation, so an agent
			# running `/issue doc` before this project's labels were
			# migrated can leave both names present. PUT new_name=... would
			# 409 here; a bare [FAIL] with no cause is exactly what
			# cc-workflow#1191 code review flagged as reporting success
			# (exit 0) on the split taxonomy this guard exists to prevent.
			# Fail loud instead: this needs a human to move `$old`'s issues
			# onto `$new` and delete `$old`.
			printf '  [CONFLICT] both %s and %s exist — relabel issues off %s and delete it manually\n' "$old" "$new" "$old" >&2
			failed=$((failed + 1))
			continue
		fi
		rename_status=0
		rename_err=$(glab api -X PUT "projects/$repo_encoded/labels/$old_encoded" \
			-f "new_name=$new" --silent 2>&1 >/dev/null) || rename_status=$?
		if ((rename_status == 0)); then
			printf '  [renamed] %-22s -> %s\n' "$old" "$new"
		else
			printf '  [FAIL] could not rename %s -> %s: %s\n' "$old" "$new" "$rename_err" >&2
			failed=$((failed + 1))
		fi
	done
fi

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
