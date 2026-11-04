#!/usr/bin/env bash
# context-math.sh — the one definition of the context-window arithmetic. (#1427, story 1 of #1426)
#
# SOURCED, never run. The reseed gate (scripts/hooks/workflow/context-reseed-gate.sh) and the
# statusline (config/statusline-command.sh) both call it, so the number the gate acts on and the
# number the operator sees cannot disagree. The code moved here from the gate unchanged, so the
# gate's behaviour and its tests are the same as before.
#
#   source "<scripts>/lib/context-math.sh"
#   context_math <reading.json> <nerf.json> [<settings.json>]
#
# It prints `key=value` lines, one per key, ALWAYS the full set (a key it cannot work out is
# printed empty), so a caller can read them with `while IFS='=' read -r k v`. No side effects: it
# writes nothing, and never exits the caller's shell.
#
# Inputs:
#   reading.json   the statusline's per-session reading (config/statusline-command.sh writes it to
#                  ${CLAUDE_CONTEXT_STATE_DIR:-~/.claude/state/context}/<session_id>.json):
#                  used_tokens, window_tokens and model_id. Missing or unreadable: no recompute.
#   nerf.json      nerf's config: <project>/.claude/nerf.json when it exists, else the legacy
#                  per-session file (${NERF_CONFIG_DIR:-/tmp}/nerf-<session_id>.json). `nerf_config_file`
#                  below picks it (#1448). .mode and .darts_pct.{soft,hard,ouch}. Missing or
#                  unreadable: ultraviolence, no darts (a gate that can't read nerf must never get weaker).
#   settings.json  where modelSettings.<model>.autoCompactWindow is read. Default
#                  ${CLAUDE_SETTINGS_FILE:-~/.claude/settings.json}.
#
# Env: RESEED_CONTEXT_THRESHOLD_PCT, CLAUDE_CODE_AUTO_COMPACT_WINDOW, RESEED_AUTOCOMPACT_BUFFER_TOKENS
#      (the same knobs the gate documents).
#
# THE CEILING (#1297). Claude Code computes remaining_percentage against the MODEL's window, and
# /autocompact does not change it. So the usable window is min(window_tokens, autocompact window)
# less a buffer (~33k: autocompact fires that far below its window), and the remaining percentage
# is measured against that. The autocompact window ("400000", "400k" or "1M"; raised to 100k) comes
# from CLAUDE_CODE_AUTO_COMPACT_WINDOW, else .modelSettings[<key>].autoCompactWindow for the first
# key that has one of: model_id as given, then with "[1m]" stripped, then canonical (provider
# prefix, "-vN:M", "@version" and "-YYYYMMDD" stripped, #1318), else the top-level
# autoCompactWindow (the pre-2.1.288 form). See the gate's header for the known gaps.
#
# THE THRESHOLD, first match wins: a numeric RESEED_CONTEXT_THRESHOLD_PCT; then 100 - the ouch
# dart, when it is an integer from 1 to 99; then 15.
#
# Keys printed:
#   nerf_mode          ultraviolence | hurt-me-plenty | not-too-rough
#   nerf_soft, nerf_hard, nerf_ouch   the darts, percent of the window used (integers), or empty
#   threshold_pct      remaining percent at or below which the gate acts
#   used_tokens, window_tokens, model_id   from the reading (empty when absent or invalid)
#   acw_tokens         the autocompact window in tokens, or empty
#   acw_keys           the settings keys tried for the model, comma separated (empty unless looked up)
#   acw_filed          the models settings holds a window for, comma separated, set only when none of
#                      acw_keys matched (the gate reports this once per session)
#   buffer_tokens      how far below its window autocompact fires
#   ceiling_tokens, ceiling_by   the window the percentage is measured against, and the words for it
#   usable_tokens      ceiling less buffer: what is usable before autocompact fires
#   remaining_pct      the integer percent of usable_tokens left, or empty when it can't be computed
#   soft_at_tokens, hard_at_tokens, ouch_at_tokens   the darts as token positions of context size
#                      (usable * dart / 100); empty without usable or that dart
#   reseed_at_tokens   the first context size at which the gate acts: the first size where remaining_pct
#                      (floored) is at or below threshold_pct, i.e. just above usable * (99 - ti) / 100 for
#                      ti = the threshold's integer part. It sits up to 1% of usable below the ouch dart's
#                      position, because the gate compares a floored percentage. Empty without usable.
#   autocompact_at_tokens   usable_tokens, the size at which autocompact fires (empty without it)
#   runway_tokens      tokens left until the nearer of reseed and autocompact
#   runway_by          which one: reseed | autocompact (empty with runway_tokens)

_cm_is_tokens() { [[ "$1" =~ ^[1-9][0-9]*$ ]]; }

# An autocompact window as Claude Code reads it: "400000", "400k", "1M" or "0.4m"; a value under
# 100k is raised to 100k. Prints the token count, or fails.
_cm_acw_tokens() {
	local v="${1,,}" n
	if [[ "$v" =~ ^[0-9]+$ ]]; then
		n=$((10#$v))
	elif [[ "$v" =~ ^([0-9]+([.][0-9]+)?)([km])$ ]]; then
		n=$(awk -v x="${BASH_REMATCH[1]}" -v u="${BASH_REMATCH[3]}" \
			'BEGIN { printf "%d", x * (u == "k" ? 1000 : 1000000) }')
	else
		return 1
	fi
	((n > 0)) || return 1
	((n < 100000)) && n=100000
	echo "$n"
}

# The settings keys a model_id may be filed under, most specific first: as given, without "[1m]",
# then canonical. Canonical strips a provider prefix (Bedrock's "us." / "eu." / "apac." / "global."
# / "us-gov." inference profiles, or a bare "anthropic."), a Bedrock "-vN:M", a Vertex "@version" and
# a "-YYYYMMDD" date (#1318: the statusline says "us.anthropic.claude-opus-5-5" where settings say
# "claude-opus-5-5").
_cm_model_keys() {
	local m="$1" c
	c="$(sed -E 's/\[1m\]$//; s/^([a-z]{2,8}(-[a-z]+)?\.)?anthropic\.//; s/-v[0-9]+(:[0-9]+)?$//; s/@.*$//; s/-[0-9]{8}$//' <<<"$m")"
	printf '%s\n' "$m" "${m%\[1m\]}" "$c"
}

# nerf_config_file <project_dir> <session_id> -> the nerf config file to READ (#1448). Prints one
# path and always returns 0; nothing is created or written. Order:
#   1. <project_dir>/.claude/nerf.json, when it exists. The settings are the project's, so they
#      survive a /clear (which is a new session id), a reseed, a compact, a restart and a reboot.
#   2. the legacy per-session file ${NERF_CONFIG_DIR:-/tmp}/nerf-<session_id>.json, whether or not
#      it exists, so a caller that tests for it behaves as before. An older nerf still writes it.
#   3. nothing (an empty line) when there is neither a project file nor a safe session id.
# The session id becomes part of a file name, so anything outside [A-Za-z0-9_-] is refused.
nerf_config_file() {
	local project="${1:-}" sid="${2:-}"
	if [[ -n "$project" && -f "$project/.claude/nerf.json" ]]; then
		printf '%s\n' "$project/.claude/nerf.json"
	elif [[ "$sid" =~ ^[A-Za-z0-9_-]+$ ]]; then
		printf '%s\n' "${NERF_CONFIG_DIR:-/tmp}/nerf-${sid}.json"
	else
		printf '\n'
	fi
	return 0
}

context_math() {
	local reading="${1:-}" nerf="${2:-}" settings="${3:-${CLAUDE_SETTINGS_FILE:-$HOME/.claude/settings.json}}"
	local nerf_mode=ultraviolence nerf_soft="" nerf_hard="" nerf_ouch="" m d
	local threshold used="" window="" model="" acw="" keys="" raw="" filed="" buffer
	local ceil="" by="" usable="" pct="" soft_at="" hard_at="" ouch_at="" reseed_at="" ac_at=""
	local runway="" runway_by=""

	# nerf's config: the mode picks what happens at the threshold, the darts set where.
	if [[ -n "$nerf" && -f "$nerf" ]]; then
		# One jq for the mode and the three darts. A dart that isn't a number, or a darts_pct that
		# isn't an object, reads as empty WITHOUT losing the mode: a malformed darts_pct must not
		# turn hurt-me-plenty into ultraviolence (the gate reads this too).
		IFS=$'\x1f' read -r m nerf_soft nerf_hard nerf_ouch < <(jq -r '
			def dart(f): try (f | if type == "number" then tostring else "" end) catch "";
			[(.mode // ""), dart(.darts_pct.soft), dart(.darts_pct.hard), dart(.darts_pct.ouch)]
			| join("\u001f")' "$nerf" 2>/dev/null)
		case "$m" in hurt-me-plenty | not-too-rough) nerf_mode="$m" ;; esac
		for d in soft hard ouch; do
			printf -v m '%s' "nerf_$d"
			[[ "${!m}" =~ ^[0-9]{1,3}$ ]] || printf -v "$m" '%s' ""
		done
	fi

	if [[ "${RESEED_CONTEXT_THRESHOLD_PCT:-}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
		threshold="$RESEED_CONTEXT_THRESHOLD_PCT"
	elif [[ "$nerf_ouch" =~ ^[0-9]{1,2}$ ]] && ((10#$nerf_ouch >= 1)); then
		threshold=$((100 - 10#$nerf_ouch))
	else
		threshold=15
	fi

	if [[ -n "$reading" && -f "$reading" ]]; then
		IFS=$'\x1f' read -r used window model < <(jq -r \
			'[(.used_tokens // ""), (.window_tokens // ""), (.model_id // "")] | map(tostring) | join("\u001f")' \
			"$reading" 2>/dev/null)
	fi

	if ! acw="$(_cm_acw_tokens "${CLAUDE_CODE_AUTO_COMPACT_WINDOW:-}")"; then
		acw=""
		if [[ -n "$model" ]]; then
			keys="$(_cm_model_keys "$model" | jq -Rsc 'split("\n") | map(select(length > 0))')"
			raw="$(jq -r --argjson ks "$keys" \
				'(.modelSettings // {}) as $ms | first($ks[] | ($ms[.]?.autoCompactWindow? // empty)) // .autoCompactWindow // empty' \
				"$settings" 2>/dev/null)"
			acw="$(_cm_acw_tokens "$raw")" || acw=""
			# A window is configured for some model but none of this model's keys: the caller says
			# so once, or a key mismatch reads exactly like no window at all.
			if [[ -z "$raw" ]]; then
				filed="$(jq -r '[.modelSettings // {} | to_entries[]? | select(.value.autoCompactWindow? != null) | .key] | join(", ")' \
					"$settings" 2>/dev/null)"
			fi
			keys="$(jq -r 'join(", ")' <<<"$keys")"
		fi
	fi

	# Autocompact fires a fixed buffer BELOW its window (~33k: ~367k of 400k, ~967k of 1M), on a
	# configured window and the model's own alike. So the percentage is of what is usable before it
	# fires: measured against the raw window, a 200k window's gate (170k) would lose to autocompact
	# (~167k).
	buffer="${RESEED_AUTOCOMPACT_BUFFER_TOKENS:-33000}"
	[[ "$buffer" =~ ^[0-9]+$ ]] || buffer=33000
	if [[ "$used" =~ ^[0-9]+$ ]] && _cm_is_tokens "$window"; then
		ceil="$window" by="autocompact"
		if [[ -n "$acw" ]] && ((acw < window)); then
			ceil="$acw" by="the $((acw / 1000))k autocompact"
		fi
		if ((ceil > buffer)); then
			usable=$((ceil - buffer))
			pct=$(((usable - used) * 100 / usable))
			((pct < 0)) && pct=0
			# Where each marker sits, as a context size. Autocompact fires at `usable`. The gate acts at
			# the first size where the integer remaining percent (remaining_pct, floored) is at or below
			# the threshold: with ti = the threshold's integer part, that is the first `used` above
			# usable * (99 - ti) / 100. (Not usable * (100 - threshold) / 100: the gate compares the
			# FLOORED percentage, so it acts up to 1% of usable sooner, and a panel built on the exact
			# fraction would show runway left after the gate had already fired.) A nerf dart sits at
			# <percent used> of usable.
			ac_at="$usable"
			reseed_at="$(awk -v u="$usable" -v t="$threshold" 'BEGIN {
				ti = int(t); r = (ti >= 100) ? 0 : int(u * (99 - ti) / 100) + 1
				if (r > u) r = u
				if (r < 0) r = 0
				printf "%d", r }')"
			if [[ "$nerf_soft" =~ ^[0-9]+$ ]]; then soft_at=$((usable * 10#$nerf_soft / 100)); fi
			if [[ "$nerf_hard" =~ ^[0-9]+$ ]]; then hard_at=$((usable * 10#$nerf_hard / 100)); fi
			if [[ "$nerf_ouch" =~ ^[0-9]+$ ]]; then ouch_at=$((usable * 10#$nerf_ouch / 100)); fi
			# The runway is the distance to the nearer of reseed and autocompact. Both are measured in
			# the same usable window (#1297), so reseed comes first at any real window size; autocompact
			# is named only when the two coincide (a usable window of a few tokens), since a reseed that
			# waits for it is no earlier.
			runway=$((usable - used)) runway_by=autocompact
			if ((reseed_at - used < runway)); then runway=$((reseed_at - used)) runway_by=reseed; fi
			if ((runway < 0)); then runway=0; fi
		fi
	fi

	printf '%s=%s\n' \
		nerf_mode "$nerf_mode" nerf_soft "$nerf_soft" nerf_hard "$nerf_hard" nerf_ouch "$nerf_ouch" \
		threshold_pct "$threshold" used_tokens "$used" window_tokens "$window" model_id "$model" \
		acw_tokens "$acw" acw_keys "$keys" acw_filed "$filed" buffer_tokens "$buffer" \
		ceiling_tokens "$ceil" ceiling_by "$by" usable_tokens "$usable" remaining_pct "$pct" \
		soft_at_tokens "$soft_at" hard_at_tokens "$hard_at" ouch_at_tokens "$ouch_at" reseed_at_tokens "$reseed_at" \
		autocompact_at_tokens "$ac_at" runway_tokens "$runway" runway_by "$runway_by"
}
