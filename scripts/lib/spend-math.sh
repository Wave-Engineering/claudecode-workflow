#!/usr/bin/env bash
# spend-math.sh — the one definition of "API spend since the begin marker". (#1429, story 3 of #1426)
#
# SOURCED, never run. config/statusline-command.sh (the spend panel) and scripts/statusline-spend
# (`begin`, `show`) both call it, so the panel and the CLI cannot disagree.
#
# State, in ${CLAUDE_SPEND_STATE_DIR:-~/.claude/state/spend}:
#   <session_id>.json   {"cost_usd": <number>, "ts": <epoch>}   one per session, written by the statusline
#   begin.json          {"ts": <epoch>, "baselines": {"<session_id>": <cost>, ...}}   written by `begin`
# "begin" is therefore not a usable session id; spend_session_id_ok refuses it.
#
#   spend_dir                          prints the state directory
#   spend_session_id_ok ID             succeeds for a safe, non-reserved session id
#   spend_summary DIR [SID COST]       prints one line: SUM US COUNT US SAVED US MARKER_TS
#       SUM     the sum over every session file of (its cost less its baseline, floored at 0); a
#               session with no baseline counts in full. With SID and COST, that session's cost is the
#               given one, so a render that cannot write its own file still shows its own spend.
#       COUNT   how many sessions went into SUM
#       SAVED   1 when SID's file already holds exactly COST (nothing to write), else 0
#       MARKER_TS  the begin marker's epoch, or empty
#       US is the unit separator (0x1f). A corrupt state file is skipped, never fatal.
#   spend_money NUMBER                 "$12.34": two decimals, whatever the locale

spend_dir() { printf '%s' "${CLAUDE_SPEND_STATE_DIR:-$HOME/.claude/state/spend}"; }

# A session id becomes a file name, so it is refused rather than sanitised; "begin" is the marker's.
spend_session_id_ok() { [[ "${1:-}" =~ ^[A-Za-z0-9_-]+$ && "${1:-}" != begin ]]; }

# shellcheck disable=SC2016  # a jq program: the $vars are jq's
_SPEND_JQ='
	[inputs | {id: (input_filename | split("/")[-1] | sub("\\.json$"; "")), v: .}] as $all
	| ($all | map(select(.id == "begin")) | first // null) as $b
	| (if $b != null and ($b.v | type) == "object" and ($b.v.baselines | type) == "object" then $b.v.baselines else {} end) as $bl
	| ($all | map(select(.id != "begin" and (.v | type) == "object" and (.v.cost_usd | type) == "number")
	              | {key: .id, value: .v.cost_usd}) | from_entries) as $sess
	| (if $sid != "" and $cost != null then $sess + {($sid): $cost} else $sess end) as $cur
	| ($cur | to_entries
	   | map(.value - (if ($bl[.key] | type) == "number" then $bl[.key] else 0 end) | if . < 0 then 0 else . end)
	   | add // 0) as $sum
	| [$sum, ($cur | length),
	   (if $sid != "" and $cost != null and $sess[$sid] == $cost then 1 else 0 end),
	   (if $b != null and ($b.v | type) == "object" and ($b.v.ts | type) == "number" then $b.v.ts else "" end)]
	| map(tostring) | join("\u001f")'

spend_summary() {
	local dir="$1" sid="${2:-}" cost="${3:-null}" f out
	local files=()
	[[ "$cost" =~ ^-?[0-9]+([.][0-9]+)?([eE][-+]?[0-9]+)?$ ]] || cost=null
	shopt -s nullglob
	for f in "$dir"/*.json; do [[ -f "$f" && ! -L "$f" ]] && files+=("$f"); done
	shopt -u nullglob
	if ((${#files[@]} == 0)); then
		# Nothing on disk: the current session alone, if it has a cost.
		jq -nr --arg sid "$sid" --argjson cost "$cost" \
			'[(if $sid != "" and $cost != null then $cost else 0 end), (if $sid != "" and $cost != null then 1 else 0 end), 0, ""] | map(tostring) | join("\u001f")'
		return 0
	fi
	if out="$(jq -nr --arg sid "$sid" --argjson cost "$cost" "$_SPEND_JQ" "${files[@]}" 2>/dev/null)" && [[ -n "$out" ]]; then
		printf '%s\n' "$out"
		return 0
	fi
	# One of the files is not JSON: keep the readable ones (a bad file must not blank the panel).
	local good=()
	for f in "${files[@]}"; do jq -e . "$f" >/dev/null 2>&1 && good+=("$f"); done
	if ((${#good[@]} == 0)); then
		jq -nr --arg sid "$sid" --argjson cost "$cost" \
			'[(if $sid != "" and $cost != null then $cost else 0 end), (if $sid != "" and $cost != null then 1 else 0 end), 0, ""] | map(tostring) | join("\u001f")'
		return 0
	fi
	jq -nr --arg sid "$sid" --argjson cost "$cost" "$_SPEND_JQ" "${good[@]}" 2>/dev/null
}

# spend_money N — "$12.34". LC_ALL=C so a comma-decimal locale cannot turn it into "12,34".
spend_money() { LC_ALL=C awk -v n="${1:-0}" 'BEGIN { printf "$%.2f", n }'; }
