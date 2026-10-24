#!/usr/bin/env bash
# wavemachine-stall-guard.sh — CC Stop hook. Blocks a turn that ends while a
# /wavemachine campaign is active but the driver neither launched the next
# per-wave Workflow nor entered a legitimate wait. (#600, #736, #1109)
#
# ASYNC-AWARE (#736). The per-wave Workflow runs async: the driver launches it,
# ends its turn and is re-invoked on the verdict. So the guard is silent on
# awaiting-verdict (an async await), hold (a human pause) and promoting (a
# promotion in progress), and blocks only a launch- or idle-shaped gap.
#
# STALE STATE NEVER BLOCKS (#1109). A flag whose state.json has not been written
# for STALE_SECONDS, or that has no readable last_updated, most likely belongs to
# a run that died without wavemachine-stop. Blocking would force another turn of
# advancing a campaign nobody has verified, so the guard tells the human instead
# (systemMessage) and exits 0. STALE_SECONDS must equal WAVEMACHINE_STALE_SECONDS
# in src/wave_status/state.py; a regression test enforces it. The check runs in
# jq, not Python, because this hook fires on every turn.
#
# It does NOT match on session id: a session id can change across /clear or a
# reseed, and a mismatch rule would silently switch the #600 protection off.
#
# Fails open: no state file, an inactive flag, or any jq error → exit 0, silent.

set -u

STALE_SECONDS=86400

state="${CLAUDE_PROJECT_DIR:-.}/.claude/status/state.json"
[[ -f "$state" ]] || exit 0

# shellcheck disable=SC2016 # $vars below are jq variables, not shell ones
program='
	def parse_ts:
		if type == "string" then
			(sub("\\.[0-9]+"; "") | sub("\\+00:00$"; "Z") | try fromdateiso8601 catch null)
		else null end;
	if ((.wavemachine_active // false) | tostring) != "true" then empty
	elif ((.current_action.action // "") | IN("awaiting-verdict", "hold", "promoting")) then empty
	else
		(.last_updated | parse_ts) as $t
		| (.wavemachine_session_id // "unknown") as $owner
		| if $t == null or ($now - $t) > $stale then
			(if $t == null then "has no readable last_updated, so it is treated as stale"
			 else (($now - $t) as $age
				| "is \(($age / 86400) | floor)d\((($age % 86400) / 3600) | floor)h stale")
			 end) as $how
			| {systemMessage: ("/wavemachine campaign flag \($how) (last_updated \(.last_updated // "none"), owner session \($owner)). Do NOT advance on this state — verify the plan first. To resume: /wavemachine (pre-flight will offer --reclaim). To clear: wave-status wavemachine-stop. To pause honestly: wave-status hold \"<reason>\".")}
		else
			{decision: "block", reason: "/wavemachine is active and the campaign has not reached a terminal exit. The turn ended without launching the next per-wave Workflow and without entering a legitimate async-await (awaiting-verdict), human-pause (hold), or promotion (promoting) state. If a wave is pending, advance the campaign loop now: write the coarse status (wave-status awaiting-verdict <waveId>) in the SAME tool-use block as the per-wave Workflow launch, then end the turn to await the async verdict. If all waves are promoted, take the success exit and run wave-status wavemachine-stop. Do NOT stall — emit the next tool call now."}
		end
	end
'

out=$(jq -c --argjson stale "$STALE_SECONDS" --argjson now "$(date +%s)" "$program" "$state" 2>/dev/null) || exit 0
[[ -n "$out" ]] && printf '%s\n' "$out"
exit 0
