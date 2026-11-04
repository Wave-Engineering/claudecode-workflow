#!/usr/bin/env bash
# test_context_math.sh — #1427 regression test for scripts/lib/context-math.sh.
#
# The helper is the one definition of the context-window arithmetic: the reseed gate and the
# statusline both call it, so they cannot disagree. This test pins what it prints for a 1M model
# with and without an autocompact window, for each nerf ouch value, and when nerf's config is
# unreadable — the values the gate acts on — plus the token positions and the runway the
# statusline will show (#1428).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LIB="$REPO_DIR/scripts/lib/context-math.sh"

echo "test_context_math"
echo "──────────────────────────────────────────"

FAILS=0
pass() { echo "  [PASS] $1"; }
fail() {
	echo "  [FAIL] $1"
	FAILS=$((FAILS + 1))
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
# Nothing from the caller's environment may change a case.
unset RESEED_CONTEXT_THRESHOLD_PCT CLAUDE_CODE_AUTO_COMPACT_WINDOW RESEED_AUTOCOMPACT_BUFFER_TOKENS CLAUDE_SETTINGS_FILE

# shellcheck source=scripts/lib/context-math.sh
source "$LIB"

READING="$WORK/reading.json"
NERF="$WORK/nerf.json"
SETTINGS="$WORK/settings.json"
reading() { printf '{"used_tokens": %s, "window_tokens": %s, "model_id": "%s"}\n' "$1" "$2" "${3:-claude-opus-5-5}" >"$READING"; }
nerf() { printf '%s\n' "$1" >"$NERF"; }
settings() { printf '%s\n' "$1" >"$SETTINGS"; }
reset() { rm -f "$READING" "$NERF" "$SETTINGS"; }

# cm [env...] -> runs context_math with the case's three files, prints its output.
cm() { (
	for kv in "$@"; do export "${kv?}"; done
	context_math "$READING" "$NERF" "$SETTINGS"
); }
# got <key> <output> -> the key's value.
got() { grep -m1 "^$1=" <<<"$2" | cut -d= -f2-; }
# expect <label> <output> <key>=<want>...
expect() {
	local label="$1" out="$2" kv k want have bad=""
	shift 2
	for kv in "$@"; do
		k="${kv%%=*}" want="${kv#*=}" have="$(got "$k" "$out")"
		[[ "$have" == "$want" ]] || bad+=" $k: want '$want' got '$have';"
	done
	if [[ -z "$bad" ]]; then pass "$label"; else fail "$label —$bad"; fi
}

# blank <label> <output> <key>... : each key's value must be empty.
blank() {
	local label="$1" out="$2" k bad=""
	shift 2
	for k in "$@"; do [[ -z "$(got "$k" "$out")" ]] || bad+=" $k is '$(got "$k" "$out")';"; done
	if [[ -z "$bad" ]]; then pass "$label"; else fail "$label —$bad"; fi
}

DARTS='{"mode": "ultraviolence", "darts_pct": {"soft": 51, "hard": 63, "ouch": 85}}'

# 1. Every key is always printed, empty when it can't be worked out.
reset
out=$(cm)
want_keys="nerf_mode nerf_soft nerf_hard nerf_ouch threshold_pct used_tokens window_tokens model_id acw_tokens acw_keys acw_filed buffer_tokens ceiling_tokens ceiling_by usable_tokens remaining_pct soft_at_tokens hard_at_tokens ouch_at_tokens reseed_at_tokens autocompact_at_tokens runway_tokens runway_by"
have_keys=$(cut -d= -f1 <<<"$out" | tr '\n' ' ' | sed 's/ $//')
[[ "$have_keys" == "$want_keys" ]] && pass "every key, always, in a fixed order" || fail "keys (got: $have_keys)"
expect "no files at all: ultraviolence, threshold 15, nothing computed" "$out" \
	nerf_mode=ultraviolence threshold_pct=15 buffer_tokens=33000 remaining_pct= usable_tokens= runway_tokens=

# 2. A 1M model with no autocompact window: measured against the model's own window.
reset
reading 400000 1000000
out=$(cm)
expect "1M model, no autocompact window" "$out" \
	acw_tokens= ceiling_tokens=1000000 ceiling_by=autocompact usable_tokens=967000 remaining_pct=58 \
	autocompact_at_tokens=967000 reseed_at_tokens=812281 runway_tokens=412281 runway_by=reseed

# 3. The same model with a 400k autocompact window (settings, keyed by the canonical model name).
settings '{"modelSettings": {"claude-opus-5-5": {"autoCompactWindow": "400k"}}}'
reading 150000 1000000 us.anthropic.claude-opus-5-5
out=$(cm)
expect "1M model, 400k autocompact window from settings (canonical key)" "$out" \
	acw_tokens=400000 ceiling_tokens=400000 "ceiling_by=the 400k autocompact" usable_tokens=367000 remaining_pct=59 \
	reseed_at_tokens=308281 runway_tokens=158281 runway_by=reseed acw_filed=
out=$(cm CLAUDE_CODE_AUTO_COMPACT_WINDOW=200000)
expect "the env window beats settings" "$out" acw_tokens=200000 usable_tokens=167000 remaining_pct=10
out=$(cm CLAUDE_CODE_AUTO_COMPACT_WINDOW=50k)
expect "a window under 100k is raised to 100k" "$out" acw_tokens=100000 usable_tokens=67000
reading 150000 1000000 claude-sonnet-5-5
out=$(cm)
expect "a window configured for other models only: reported, not applied" "$out" \
	acw_tokens= ceiling_by=autocompact "acw_filed=claude-opus-5-5"
[[ "$(got acw_keys "$out")" == "claude-sonnet-5-5, claude-sonnet-5-5, claude-sonnet-5-5" ]] && pass "the keys tried are named" || fail "acw_keys ($(got acw_keys "$out"))"
settings '{"autoCompactWindow": "300k"}'
out=$(cm)
expect "the top-level window (pre-2.1.288 form) is the last resort" "$out" acw_tokens=300000 usable_tokens=267000
reset

# 4. Each nerf ouch value sets the threshold (100 - ouch). The ouch dart sits at ouch% of usable; the
# gate acts a hair sooner, at the first size where the FLOORED remaining percent is <= threshold,
# i.e. just above usable * (ouch - 1) / 100.
reading 400000 1000000
for ouch in 50 70 85 99; do
	nerf "{\"mode\": \"ultraviolence\", \"darts_pct\": {\"soft\": 10, \"hard\": 20, \"ouch\": $ouch}}"
	out=$(cm)
	expect "ouch $ouch: threshold $((100 - ouch))%, dart at $((967000 * ouch / 100)), gate acts at $((967000 * (ouch - 1) / 100 + 1))" "$out" \
		nerf_ouch=$ouch threshold_pct=$((100 - ouch)) ouch_at_tokens=$((967000 * ouch / 100)) \
		reseed_at_tokens=$((967000 * (ouch - 1) / 100 + 1))
done
nerf '{"darts_pct": {"ouch": 100}}'
expect "ouch 100 is out of range: threshold stays 15" "$(cm)" threshold_pct=15
nerf '{"darts_pct": {"ouch": 0}}'
expect "ouch 0 is out of range: threshold stays 15" "$(cm)" threshold_pct=15
nerf '{"darts_pct": {"ouch": "85"}}'
expect "a string ouch is not a number: ignored" "$(cm)" nerf_ouch= threshold_pct=15

# 5. The dart positions and the runway: the nearer of reseed and autocompact.
nerf "$DARTS"
reading 400000 1000000
out=$(cm)
expect "dart positions in tokens (of 967k usable)" "$out" \
	nerf_soft=51 nerf_hard=63 nerf_ouch=85 soft_at_tokens=493170 hard_at_tokens=609210 ouch_at_tokens=821950 reseed_at_tokens=812281 \
	autocompact_at_tokens=967000 runway_tokens=412281 runway_by=reseed
reading 900000 1000000
expect "past the reseed point the runway is 0 and still reseed" "$(cm)" runway_tokens=0 runway_by=reseed
reading 400000 1000000
nerf '{"darts_pct": {"soft": 51, "hard": 63}}'
expect "no ouch dart: the gate's default 15% threshold sets the reseed point" "$(cm)" \
	reseed_at_tokens=812281 runway_by=reseed runway_tokens=412281 ouch_at_tokens=
expect "an env threshold moves the reseed point" "$(cm RESEED_CONTEXT_THRESHOLD_PCT=40)" \
	reseed_at_tokens=570531 runway_tokens=170531 runway_by=reseed
expect "a fractional threshold counts as its integer part (the gate compares a floored percent)" \
	"$(cm RESEED_CONTEXT_THRESHOLD_PCT=12.9)" reseed_at_tokens=$((967000 * 87 / 100 + 1))
expect "threshold 0: reseed is still just before autocompact" "$(cm RESEED_CONTEXT_THRESHOLD_PCT=0)" \
	reseed_at_tokens=957331 runway_tokens=557331 runway_by=reseed
expect "threshold 100 or more: the gate acts at once" "$(cm RESEED_CONTEXT_THRESHOLD_PCT=100)" \
	reseed_at_tokens=0 runway_tokens=0 runway_by=reseed
# Only when the two coincide (a usable window of a few tokens) is autocompact the nearer.
reading 10 1000000
expect "reseed and autocompact coincide: autocompact is named" \
	"$(cm RESEED_AUTOCOMPACT_BUFFER_TOKENS=999950 RESEED_CONTEXT_THRESHOLD_PCT=0)" \
	usable_tokens=50 reseed_at_tokens=50 runway_tokens=40 runway_by=autocompact
settings '{"modelSettings": {"claude-opus-5-5": {"autoCompactWindow": "200k"}}}'
reading 100000 1000000
expect "a small autocompact window shrinks both, reseed stays the nearer" "$(cm)" \
	usable_tokens=167000 reseed_at_tokens=140281 runway_tokens=40281 runway_by=reseed
reset
reading 400000 1000000
nerf '{"darts_pct": {"soft": 51, "hard": 63}}'

# 6. The nerf mode: only the two known names change it; anything unreadable is ultraviolence.
for mode in hurt-me-plenty not-too-rough; do
	nerf "{\"mode\": \"$mode\"}"
	expect "mode $mode" "$(cm)" nerf_mode=$mode
done
nerf '{"mode": "gentle"}'
expect "an unknown mode is ultraviolence" "$(cm)" nerf_mode=ultraviolence
# A malformed darts_pct must not cost the mode: the gate reads this and hurt-me-plenty must stay so.
for bad in '"x"' '[]' '7' 'null' '{"soft": "a", "hard": [], "ouch": {}}'; do
	nerf "{\"mode\": \"hurt-me-plenty\", \"darts_pct\": $bad}"
	expect "darts_pct $bad: the mode survives, no darts" "$(cm)" \
		nerf_mode=hurt-me-plenty nerf_soft= nerf_hard= nerf_ouch= threshold_pct=15
done
nerf '{not json'
expect "an unreadable nerf file: ultraviolence, no darts, threshold 15" "$(cm)" nerf_mode=ultraviolence nerf_ouch= threshold_pct=15
rm -f "$NERF"
expect "no nerf file: ultraviolence" "$(cm)" nerf_mode=ultraviolence nerf_ouch= threshold_pct=15

# 7. The threshold: a numeric env override wins; otherwise 100 - ouch; otherwise 15.
nerf "$DARTS"
expect "env threshold beats ouch" "$(cm RESEED_CONTEXT_THRESHOLD_PCT=30)" threshold_pct=30
expect "a fractional env threshold is kept" "$(cm RESEED_CONTEXT_THRESHOLD_PCT=12.5)" threshold_pct=12.5
expect "a non-numeric env threshold falls through to ouch" "$(cm RESEED_CONTEXT_THRESHOLD_PCT=lots)" threshold_pct=15

# 8. The buffer, and the guards on the reading.
reading 400000 1000000
expect "a custom buffer" "$(cm RESEED_AUTOCOMPACT_BUFFER_TOKENS=100000)" buffer_tokens=100000 usable_tokens=900000
expect "a non-numeric buffer falls back to 33000" "$(cm RESEED_AUTOCOMPACT_BUFFER_TOKENS=lots)" buffer_tokens=33000
reading 400000 20000
blank "a ceiling not above the buffer: no recompute" "$(cm)" usable_tokens remaining_pct
printf '{"used_tokens": "lots", "window_tokens": 1000000}\n' >"$READING"
blank "a non-numeric used_tokens: no recompute" "$(cm)" usable_tokens remaining_pct
printf '{"used_tokens": 5}\n' >"$READING"
blank "no window_tokens: no recompute" "$(cm)" usable_tokens remaining_pct
printf 'garbage\n' >"$READING"
expect "an unreadable reading: no recompute, no crash" "$(cm)" used_tokens= usable_tokens= remaining_pct=
reading 2000000 1000000
expect "more used than usable: remaining is 0, not negative" "$(cm)" remaining_pct=0 runway_tokens=0

# 8b. The helper and the REAL gate agree on where reseed starts: at reseed_at_tokens - 1 the gate stays
# quiet, at reseed_at_tokens it blocks. This is what keeps the statusline's runway from showing room the
# gate has already taken away (the gate compares a floored percentage).
GATE="$REPO_DIR/scripts/hooks/workflow/context-reseed-gate.sh"
GSTATE="$WORK/gate-state"
mkdir -p "$GSTATE" "$WORK/gate-nerf" "$WORK/gate-proj/.claude"
gate_blocks() { # <used> <window> <threshold> [model_id] -> "block" or "quiet"
	local used="$1" window="$2" t="$3" model="${4:-claude-opus-5-5}" out
	printf '{"session_id": "gx", "remaining_percentage": 50, "ts": %s, "used_tokens": %s, "window_tokens": %s, "model_id": "%s"}\n' \
		"$(date +%s)" "$used" "$window" "$model" >"$GSTATE/gx.json"
	out=$(jq -cn --arg c "$WORK/gate-proj" '{session_id: "gx", cwd: $c, stop_hook_active: false}' |
		CLAUDE_CONTEXT_STATE_DIR="$GSTATE" NERF_CONFIG_DIR="$WORK/gate-nerf" CLAUDE_SETTINGS_FILE="$SETTINGS" \
			RESEED_CONTEXT_THRESHOLD_PCT="$t" bash "$GATE")
	if [[ "$out" == *'"decision":"block"'* ]]; then echo block; else echo quiet; fi
}
rm -f "$SETTINGS" "$NERF"
for combo in "1000000 15" "1000000 40" "1000000 0" "200000 15" "200000 30" "1000000 12.5" "500000 5" "1000000 99"; do
	read -r win t <<<"$combo"
	reading 1 "$win"
	r=$(got reseed_at_tokens "$(cm RESEED_CONTEXT_THRESHOLD_PCT="$t")")
	before=$(gate_blocks $((r - 1)) "$win" "$t")
	at=$(gate_blocks "$r" "$win" "$t")
	[[ "$before" == quiet && "$at" == block ]] && pass "window $win, threshold $t: the gate is quiet at $((r - 1)) and blocks at $r" ||
		fail "window $win, threshold $t: reseed_at $r, gate says '$before' at $((r - 1)) and '$at' at $r"
done

# 9. It is a pure function: it writes nothing and doesn't change the caller's shell options.
reading 400000 1000000
before=$(find "$WORK" -type f | sort | xargs md5sum | md5sum)
cm >/dev/null
after=$(find "$WORK" -type f | sort | xargs md5sum | md5sum)
[[ "$before" == "$after" ]] && pass "it writes nothing" || fail "it changed files"
case "$-" in *e*) fail "sourcing set -e" ;; *) pass "sourcing leaves the shell options alone" ;; esac

# 10. nerf_config_file (#1448): <project>/.claude/nerf.json when it exists, else the legacy
# per-session file, else nothing. It prints one path and never creates a file.
PROJ="$WORK/proj"
NDIR="$WORK/nerfdir"
mkdir -p "$PROJ/.claude" "$NDIR"
ncf() { (
	export NERF_CONFIG_DIR="$NDIR"
	nerf_config_file "$@"
); }
want_ncf() { # <label> <want> <project> <sid>
	local have
	have=$(ncf "$3" "$4")
	[[ "$have" == "$2" ]] && pass "nerf_config_file: $1" || fail "nerf_config_file: $1 (want '$2', got '$have')"
}
want_ncf "no project file, safe session id: the legacy path" "$NDIR/nerf-s1.json" "$PROJ" s1
printf '{}\n' >"$PROJ/.claude/nerf.json"
want_ncf "a project file is used when there is no per-session file" "$PROJ/.claude/nerf.json" "$PROJ" s1
want_ncf "a new session id still finds the project file" "$PROJ/.claude/nerf.json" "$PROJ" s2
want_ncf "a project file needs no session id" "$PROJ/.claude/nerf.json" "$PROJ" ""
# With both, the NEWER wins: nerf writes only when something is set, so the newer file is the last
# thing set, and a /nerf change through an older server is not ignored behind the project file.
printf '{}\n' >"$NDIR/nerf-s1.json"
touch -d '2 hours ago' "$PROJ/.claude/nerf.json"
want_ncf "both exist, the per-session file is newer: it wins" "$NDIR/nerf-s1.json" "$PROJ" s1
touch -d '2 hours ago' "$NDIR/nerf-s1.json"
touch -d '1 hour ago' "$PROJ/.claude/nerf.json"
want_ncf "both exist, the project file is newer: it wins" "$PROJ/.claude/nerf.json" "$PROJ" s1
want_ncf "…and a new session id (no per-session file) still gets the project file" "$PROJ/.claude/nerf.json" "$PROJ" s2
touch -r "$PROJ/.claude/nerf.json" "$NDIR/nerf-s1.json" # exactly the same timestamp
want_ncf "equal timestamps: the project file wins" "$PROJ/.claude/nerf.json" "$PROJ" s1
chmod 000 "$PROJ/.claude/nerf.json"
if [[ ! -r "$PROJ/.claude/nerf.json" ]]; then
	want_ncf "an unreadable project file does not shadow the per-session file" "$NDIR/nerf-s1.json" "$PROJ" s1
else
	pass "nerf_config_file: (skipped: running as a user who can read a mode-000 file)"
fi
chmod 600 "$PROJ/.claude/nerf.json"
rm -f "$PROJ/.claude/nerf.json" "$NDIR/nerf-s1.json"
want_ncf "an empty project dir falls back to the legacy path" "$NDIR/nerf-s1.json" "" s1
want_ncf "an unsafe session id is refused (no path)" "" "$PROJ" "../etc/x"
want_ncf "neither a project file nor a session id: nothing" "" "$PROJ" ""
[[ -z "$(ls -A "$NDIR")" && ! -e "$PROJ/.claude/nerf.json" ]] && pass "nerf_config_file creates nothing" || fail "nerf_config_file created a file"

echo
if [[ $FAILS -eq 0 ]]; then
	echo "  All context-math checks passed."
	exit 0
fi
echo "  $FAILS context-math check(s) FAILED."
exit 1
