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
# THE DRIVER'S OWN FIELD (#1205). While a wave runs, the Workflow's agents write
# fine-grained states (waiting-ci, in-flight, merging, planning...) to
# current_action, overwriting the driver's awaiting-verdict, so a guard reading
# current_action blocked mid-wave and told the driver to launch a duplicate
# wave. The driver's coarse states now also go to driver_action, which nothing
# else writes, and the guard decides from it:
#   hold                                               → silent
#   awaiting-verdict, awaited wave not completed/held  → silent (still running)
#   awaiting-verdict, awaited wave completed or held   → block once: act on the
#                                                        verdict if you have it
#   promoting, its wave completed                      → block: launch next
#   promoting, its wave held                           → block: hold, never
#                                                        launch (not integrated)
#   promoting, its wave in any other state             → silent
#   launching, or any other driver action              → block (the stall)
# promoting is sticky (nothing overwrites driver_action after the promotion), so
# without the wave check a driver that promoted and then stopped would never be
# blocked, which is the #600 stall itself.
#
# "Block once" honours the hook input's stop_hook_active. The Workflow marks the
# wave completed or held BEFORE it cleans up and returns its verdict, so for that
# tail a driver woken mid-wave (by the Discord doorbell, say) sees a finished
# wave it has no verdict for. The status alone cannot tell that apart from a
# driver that got its verdict and stopped, so the guard nudges once, worded for
# both, and lets the second stop through. promoting has no such ambiguity: the
# driver writes it only once it holds the verdict, and each promoting reason has
# a write that clears it, so like launching it blocks on every stop.
# State with no driver_action (written before #1205) keeps the old rule on
# current_action.
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
	def stall_reason:
		"/wavemachine is active and the campaign has not reached a terminal exit. The turn ended without launching the next per-wave Workflow and without entering a legitimate async-await (awaiting-verdict), human-pause (hold), or promotion (promoting) state. If a wave is pending, advance the campaign loop now: write the coarse status (wave-status awaiting-verdict <waveId>) in the SAME tool-use block as the per-wave Workflow launch, then end the turn to await the async verdict. If all waves are promoted, take the success exit and run wave-status wavemachine-stop. Do NOT stall — emit the next tool call now.";
	def finished_reason($wave; $status):
		"/wavemachine is active and wave \($wave) is marked \($status). If its per-wave Workflow verdict has reached you, act on it now: promote and launch the next wave, or wave-status hold \"<reason>\". If it has NOT reached you, the Workflow is still finishing (it marks the wave before it cleans up and returns): launch nothing, and end the turn again to wait for it. This reminder fires once; the next stop goes through.";
	def promoted_reason($wave):
		"/wavemachine is active and wave \($wave) is promoted (completed), but the turn ended without launching the next wave. Launch it now (wave-status awaiting-verdict <waveId> in the SAME tool-use block as the per-wave Workflow launch), or, if every wave is promoted, take the success exit and run wave-status wavemachine-stop. Do NOT stall — emit the next tool call now.";
	def not_integrated_reason($wave):
		"/wavemachine is active and wave \($wave) is held: it did not integrate, or it awaits a human promotion. Do NOT launch the next wave. Record the pause with wave-status hold \"<reason>\" and surface it.";
	# The block reason, or null when this turn end is legitimate. $nudged is the
	# hook input stop_hook_active: finished_reason (awaiting-verdict on a
	# finished wave) is a one-time nudge, because during the Workflow tail the
	# wave is marked but its verdict is not yet delivered, and repeating the
	# block there would loop. The promoting reasons block on every stop.
	def block_reason:
		if (.driver_action | type) == "object" then
			(.driver_action.action // "") as $a
			| (.driver_action.wave_id // "") as $w
			| ((.waves // {})[$w].status // "") as $st
			| if $a == "hold" then null
			elif $a == "awaiting-verdict" then
				(if ($st == "completed" or $st == "held") and ($nudged | not) then finished_reason($w; $st) else null end)
			elif $a == "promoting" then
				(if $st == "completed" then promoted_reason($w)
				 elif $st == "held" then not_integrated_reason($w)
				 else null end)
			else stall_reason end
		elif ((.current_action.action // "") | IN("awaiting-verdict", "hold", "promoting")) then null
		else stall_reason end;
	if ((.wavemachine_active // false) | tostring) != "true" then empty
	else
		block_reason as $reason
		| if $reason == null then empty
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
				{decision: "block", reason: $reason}
			end
		end
	end
'

INPUT=$(cat 2>/dev/null || true)
nudged=false
[[ "$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null)" == "true" ]] && nudged=true

out=$(jq -c --argjson stale "$STALE_SECONDS" --argjson now "$(date +%s)" --argjson nudged "$nudged" "$program" "$state" 2>/dev/null) || exit 0
[[ -n "$out" ]] && printf '%s\n' "$out"
exit 0
