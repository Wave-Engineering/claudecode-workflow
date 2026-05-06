#!/usr/bin/env bash
# drift-instrumentation.sh — emit per-wave drift-signal events for /wavemachine campaigns.
#
# Long /wavemachine campaigns (5+ waves) drift in agent behavior: late-campaign
# waves get sloppier checklist treatment, more cross-talk with the user, more
# "is this still right?" pauses. The longer the session, the further the
# Orchestrator agent has drifted from its constitutional rules (CLAUDE.md,
# WAVE_AXIOMS, the skill body it started with). Issue cc-workflow#601 ("Bug C"
# from Plan #581 campaign A debrief) tracks the rework.
#
# This helper standardizes the three per-wave drift-signal events the
# wavemachine SKILL body emits at each `wave_complete` boundary. Events are
# written via the standard `mcp-log` CLI to ~/.claude/logs/mcp.jsonl so the
# fleet logfile aggregator (and any post-campaign report) can detect monotonic
# trends across a campaign's waves.
#
# Usage:
#   drift-instrumentation.sh emit-wave-drift \
#       --plan <plan_id> \
#       --wave <wave_id> \
#       --message-length-main <int> \
#       --stop-hook-blocks <int> \
#       --concerns-posts <int>
#
#   drift-instrumentation.sh self-test
#       Emit one synthetic event per signal (sample values) to stdout in
#       compact JSON form for testing the instrumentation surface without
#       touching the real fleet logfile. Exit 0 on success; exit 1 on any
#       formatting failure.
#
#   drift-instrumentation.sh report <jsonl-path>
#       Read a fleet logfile (or test-harness file) and aggregate the three
#       drift signals into a per-wave trend table. Used for post-campaign
#       reports — answers "did the late-wave drift signals flatten?".
#
# Events emitted (one mcp-log line per signal):
#   - wave_message_length_main  plan=<id> wave=<id> chars=<int>
#   - wave_stop_hook_blocks     plan=<id> wave=<id> count=<int>
#   - wave_concerns_posts       plan=<id> wave=<id> count=<int>
#
# Exit codes:
#   0  success
#   1  usage error or self-test failure
#   2  mcp-log not on PATH (degrades to stderr warning + exit non-zero)

set -euo pipefail

usage() {
	cat <<'EOF'
Usage:
  drift-instrumentation.sh emit-wave-drift \
      --plan <plan_id> --wave <wave_id> \
      --message-length-main <int> \
      --stop-hook-blocks <int> \
      --concerns-posts <int>

  drift-instrumentation.sh self-test
      Emit one synthetic event per signal to stdout (compact JSON) and verify
      formatting without touching the fleet logfile.

  drift-instrumentation.sh report <jsonl-path>
      Aggregate drift events from a fleet logfile or test harness file into a
      per-wave trend table.

Events emitted:
  wave_message_length_main  plan=<id> wave=<id> chars=<int>
  wave_stop_hook_blocks     plan=<id> wave=<id> count=<int>
  wave_concerns_posts       plan=<id> wave=<id> count=<int>
EOF
}

die() {
	echo "drift-instrumentation: $*" >&2
	exit 1
}

require_mcp_log() {
	if ! command -v mcp-log >/dev/null 2>&1; then
		echo "drift-instrumentation: mcp-log not on PATH; cannot emit events" >&2
		exit 2
	fi
}

cmd_emit_wave_drift() {
	local plan="" wave="" msg_len="" stop_blocks="" concerns=""

	while [[ $# -gt 0 ]]; do
		case "$1" in
		--plan)
			plan="$2"
			shift 2
			;;
		--wave)
			wave="$2"
			shift 2
			;;
		--message-length-main)
			msg_len="$2"
			shift 2
			;;
		--stop-hook-blocks)
			stop_blocks="$2"
			shift 2
			;;
		--concerns-posts)
			concerns="$2"
			shift 2
			;;
		*)
			die "unknown flag: $1"
			;;
		esac
	done

	[[ -n "$plan" ]] || die "--plan required"
	[[ -n "$wave" ]] || die "--wave required"
	[[ -n "$msg_len" ]] || die "--message-length-main required"
	[[ -n "$stop_blocks" ]] || die "--stop-hook-blocks required"
	[[ -n "$concerns" ]] || die "--concerns-posts required"

	# Validate integer-ness of the three numeric fields. Refuse anything else
	# so emit-time bugs surface immediately rather than dribbling malformed
	# events into the fleet logfile.
	for v in "$msg_len" "$stop_blocks" "$concerns"; do
		[[ "$v" =~ ^[0-9]+$ ]] || die "expected non-negative integer, got '$v'"
	done

	require_mcp_log

	# Three events per wave — one per signal. Emitting them as separate
	# events (rather than one combined event with three fields) keeps the
	# schema consistent with other lifecycle events that follow the
	# event=<one-thing> convention, and makes per-signal trend filtering
	# trivial (one jq select per signal).
	mcp-log wave_message_length_main \
		plan="$plan" wave="$wave" chars="$msg_len"
	mcp-log wave_stop_hook_blocks \
		plan="$plan" wave="$wave" count="$stop_blocks"
	mcp-log wave_concerns_posts \
		plan="$plan" wave="$wave" count="$concerns"
}

cmd_self_test() {
	# Synthesize one event per signal and emit to stdout (NOT mcp-log) so
	# the test harness can validate the format without polluting the fleet
	# logfile. Each line is a compact JSON object in the same shape mcp-log
	# would produce.
	local ts
	ts="$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)"

	for tuple in \
		"wave_message_length_main:chars:8421" \
		"wave_stop_hook_blocks:count:3" \
		"wave_concerns_posts:count:1"; do
		local event="${tuple%%:*}"
		local rest="${tuple#*:}"
		local field="${rest%%:*}"
		local value="${rest#*:}"

		jq -nc \
			--arg ts "$ts" \
			--arg event "$event" \
			--arg field "$field" \
			--argjson value "$value" \
			'{ts: $ts, server: "wave", level: "info", event: $event, plan: 581, wave: "3a", ($field): $value}'
	done
}

cmd_report() {
	[[ $# -eq 1 ]] || die "report requires <jsonl-path>"
	local path="$1"
	[[ -f "$path" ]] || die "file not found: $path"

	# Aggregate by (plan, wave). Output is a tab-separated table:
	#   plan  wave  message_length_main  stop_hook_blocks  concerns_posts
	# Sorted by plan then wave so monotonic trends are visible at a glance.
	# All three signals must be present for a wave to show up — a partial
	# row is a sign the emitter crashed mid-wave.
	jq -rs '
		map(select(.event | test("^wave_(message_length_main|stop_hook_blocks|concerns_posts)$"))) |
		group_by([.plan, .wave]) |
		map({
			plan: .[0].plan,
			wave: .[0].wave,
			message_length_main: (map(select(.event == "wave_message_length_main")) | first | .chars // null),
			stop_hook_blocks:    (map(select(.event == "wave_stop_hook_blocks"))    | first | .count // null),
			concerns_posts:      (map(select(.event == "wave_concerns_posts"))      | first | .count // null)
		}) |
		sort_by([.plan, .wave]) |
		(["plan", "wave", "message_length_main", "stop_hook_blocks", "concerns_posts"] | @tsv),
		(.[] | [.plan, .wave, .message_length_main, .stop_hook_blocks, .concerns_posts] | @tsv)
	' "$path"
}

if [[ $# -lt 1 ]]; then
	usage >&2
	exit 1
fi

subcommand="$1"
shift

case "$subcommand" in
emit-wave-drift)
	cmd_emit_wave_drift "$@"
	;;
self-test)
	cmd_self_test
	;;
report)
	cmd_report "$@"
	;;
-h | --help)
	usage
	;;
*)
	usage >&2
	exit 1
	;;
esac
