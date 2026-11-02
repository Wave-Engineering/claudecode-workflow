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
#   nerf.json      nerf's per-session config (${NERF_CONFIG_DIR:-/tmp}/nerf-<session_id>.json):
#                  .mode and .darts_pct.{soft,hard,ouch}. Missing or unreadable: ultraviolence,
#                  no darts (a gate that can't read nerf must never get weaker).
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
#   soft_at_tokens, hard_at_tokens, reseed_at_tokens   the darts as token positions of context size
#                      (usable * dart / 100); reseed_at is the ouch dart. Empty without usable or dart.
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

context_math() {
	local reading="${1:-}" nerf="${2:-}" settings="${3:-${CLAUDE_SETTINGS_FILE:-$HOME/.claude/settings.json}}"
	local nerf_mode=ultraviolence nerf_soft="" nerf_hard="" nerf_ouch="" m d
	local threshold used="" window="" model="" acw="" keys="" raw="" filed="" buffer
	local ceil="" by="" usable="" pct="" soft_at="" hard_at="" reseed_at="" ac_at=""
	local runway="" runway_by=""

	# nerf's config: the mode picks what happens at the threshold, the darts set where.
	if [[ -n "$nerf" && -f "$nerf" ]]; then
		m="$(jq -r '.mode // empty' "$nerf" 2>/dev/null || true)"
		case "$m" in hurt-me-plenty | not-too-rough) nerf_mode="$m" ;; esac
		for d in soft hard ouch; do
			m="$(jq -r --arg d "$d" '.darts_pct[$d] | numbers' "$nerf" 2>/dev/null || true)"
			[[ "$m" =~ ^[0-9]{1,3}$ ]] || m=""
			printf -v "nerf_$d" '%s' "$m"
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
		used="$(jq -r '.used_tokens // empty' "$reading" 2>/dev/null || true)"
		window="$(jq -r '.window_tokens // empty' "$reading" 2>/dev/null || true)"
		model="$(jq -r '.model_id // empty' "$reading" 2>/dev/null || true)"
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
			# Where each marker sits, as a context size: autocompact fires at `usable`, and a dart
			# at <percent used> of it (the gate acts when the remaining percent falls to
			# 100 - ouch, which is the same point).
			ac_at="$usable"
			runway=$((usable - used)) runway_by=autocompact
			if [[ "$nerf_soft" =~ ^[0-9]+$ ]]; then soft_at=$((usable * 10#$nerf_soft / 100)); fi
			if [[ "$nerf_hard" =~ ^[0-9]+$ ]]; then hard_at=$((usable * 10#$nerf_hard / 100)); fi
			if [[ "$nerf_ouch" =~ ^[0-9]+$ ]]; then
				reseed_at=$((usable * 10#$nerf_ouch / 100))
				# The runway is the distance to the nearer of reseed and autocompact.
				if ((reseed_at - used < runway)); then runway=$((reseed_at - used)) runway_by=reseed; fi
			fi
			if ((runway < 0)); then runway=0; fi
		fi
	fi

	printf '%s=%s\n' \
		nerf_mode "$nerf_mode" nerf_soft "$nerf_soft" nerf_hard "$nerf_hard" nerf_ouch "$nerf_ouch" \
		threshold_pct "$threshold" used_tokens "$used" window_tokens "$window" model_id "$model" \
		acw_tokens "$acw" acw_keys "$keys" acw_filed "$filed" buffer_tokens "$buffer" \
		ceiling_tokens "$ceil" ceiling_by "$by" usable_tokens "$usable" remaining_pct "$pct" \
		soft_at_tokens "$soft_at" hard_at_tokens "$hard_at" reseed_at_tokens "$reseed_at" \
		autocompact_at_tokens "$ac_at" runway_tokens "$runway" runway_by "$runway_by"
}
