#!/usr/bin/env bash
# Claude Code status line — two rows of divider-separated panels. (#1426, #1427)
#
# Row 1: <panel icons> │ <Model-Effort> │ <nerf> │ <runway> │ <context> │ <floor> │ <Session> │ <Weekly> │ <spend>
# Row 2: <dev-name> <avatar> │ <project>-<branch> (<worktree>) │ <cwd>
#
# A panel with nothing to show is not rendered, and neither is its divider. The dim `│` is the
# only divider. nerf, runway, floor and spend have their places reserved below and print nothing
# yet (#1428 and #1429 fill them).
#
# The payload on stdin is read with ONE jq invocation per render. Git lookups are cached for a few
# seconds per cwd (CLAUDE_STATUSLINE_GIT_TTL, default 5; 0 turns the cache off).

input=$(cat)
now=$(date +%s)

# --- Payload: one jq pass --------------------------------------------------------------------
# Fields are joined with the unit separator (not whitespace, so an empty field stays an empty
# field). The last field is the remaining-context reading, ready to persist (#1225).
IFS=$'\x1f' read -r cwd model effort remaining_pct session_id ctx_in_tokens ctx_out_tokens \
	five_hour_pct seven_day_pct cost_usd has_limits reading_json < <(printf '%s' "$input" | jq -r --argjson t "$now" '
	def num: if type == "number" then . else null end;
	[ (.cwd // .workspace.current_dir // ""),
	  (.model.display_name // ""),
	  (.effort.level // ""),
	  (.context_window.remaining_percentage // ""),
	  (.session_id // ""),
	  (.context_window.total_input_tokens // ""),
	  (.context_window.total_output_tokens // ""),
	  (.rate_limits.five_hour.used_percentage // ""),
	  (.rate_limits.seven_day.used_percentage // ""),
	  (.cost.total_cost_usd | if type == "number" and . > 0 then . else "" end),
	  (if (.rate_limits // null) != null then 1 else 0 end),
	  ({session_id: (.session_id // ""),
	    remaining_percentage: .context_window.remaining_percentage,
	    ts: $t,
	    used_tokens: (.context_window.total_input_tokens | num),
	    window_tokens: (.context_window.context_window_size | num),
	    model_id: (.model.id | if type == "string" and . != "" then . else null end)}
	   | with_entries(select(.value != null)) | tojson)
	] | map(tostring) | join("\u001f")' 2>/dev/null)
ctx_in_int="${ctx_in_tokens%.*}"
ctx_out_int="${ctx_out_tokens%.*}"
[[ "$ctx_in_int" =~ ^[0-9]+$ ]] || ctx_in_int=0
[[ "$ctx_out_int" =~ ^[0-9]+$ ]] || ctx_out_int=0
ctx_used_tokens=$((ctx_in_int + ctx_out_int)) # the legacy nerf `darts` compare input + output

# --- Persist remaining context per session (#1225) -------------------------------------------
# Claude Code hands ONLY the statusline the authoritative, window-aware
# remaining_percentage; nothing else can see it. Persist it so the reseed Stop
# gate (context-reseed-gate.sh) and nerf can read it. Atomic (temp + mv) so a
# reader never sees a half-written file. The session id becomes a filename, so
# anything outside [A-Za-z0-9_-] is refused rather than sanitised. Best-effort:
# a failure here must never cost the statusline its render.
ctx_state_dir="${CLAUDE_CONTEXT_STATE_DIR:-$HOME/.claude/state/context}"
persisted_reading=""
if [ -n "$remaining_pct" ] && [[ "$session_id" =~ ^[A-Za-z0-9_-]+$ ]] && [ -n "$reading_json" ]; then
	{
		ctx_tmp=""
		# The raw numbers (#1297) let the gate measure against an autocompact
		# window: Claude Code computes remaining_percentage against the model's.
		if mkdir -p "$ctx_state_dir" &&
			ctx_tmp="$(mktemp "$ctx_state_dir/.${session_id}.XXXXXX")" &&
			printf '%s\n' "$reading_json" >"$ctx_tmp"; then
			mv -f "$ctx_tmp" "$ctx_state_dir/${session_id}.json" &&
				persisted_reading="$ctx_state_dir/${session_id}.json"
		else
			[ -n "$ctx_tmp" ] && rm -f "$ctx_tmp"
		fi
	} 2>/dev/null
fi

# ANSI colors
c_purple='\033[38;5;97m'
c_fuchsia='\033[38;5;13m'
c_green='\033[01;32m'
c_blue='\033[01;34m'
c_cyan='\033[36m'
c_red='\033[31m'
c_yellow='\033[33m'
c_orange='\033[38;5;208m'
c_dim='\033[2m'
c_reset='\033[00m'

# The one divider: a dim │ with a space each side.
divider=" $(printf '%b' "${c_dim}")│$(printf '%b' "${c_reset}") "

# join_panels PANEL... — the non-empty panels, divided. An empty panel leaves no divider.
join_panels() {
	local out="" p
	for p in "$@"; do
		[ -n "$p" ] || continue
		if [ -n "$out" ]; then out+="$divider"; fi
		out+="$p"
	done
	printf '%s' "$out"
}

# paint COLOR TEXT — TEXT in COLOR, or nothing when TEXT is empty.
paint() {
	[ -n "$2" ] || return 0
	printf '%s' "$(printf '%b' "$1")$2$(printf '%b' "${c_reset}")"
}

# fmt_tokens N — an absolute token count: 999, 1K, 38K, 312K, 1M, 1.2M. No bar, no percent.
fmt_tokens() {
	local n="${1%.*}" k tenths
	[[ "$n" =~ ^[0-9]+$ ]] || return 1
	if ((n < 1000)); then
		printf '%s' "$n"
		return 0
	fi
	k=$(((n + 500) / 1000))
	if ((k < 1000)); then
		printf '%sK' "$k"
		return 0
	fi
	tenths=$(((n + 50000) / 100000)) # in tenths of a million
	if ((tenths % 10 == 0)); then
		printf '%sM' "$((tenths / 10))"
	else
		printf '%s.%sM' "$((tenths / 10))" "$((tenths % 10))"
	fi
}

# runway_fmt N — tokens left, always with a unit: 0K, 1K, 88K, 1.2M.
runway_fmt() {
	if (($1 < 1000)); then
		printf '%sK' "$((($1 + 500) / 1000))"
	else
		fmt_tokens "$1"
	fi
}

# Nerf's emoji sets (#1428): single code points, no variation selector. One is picked per
# (session, dart) by a stable hash, so it does not change between renders.
# shellcheck disable=SC2034  # read through the nameref in pick_emoji
nerf_emoji_soft=(🪶 🧸 🍬 🫧 🧁)
# shellcheck disable=SC2034
nerf_emoji_hard=(🔨 🪨 🧱 🥊 🏏)
# shellcheck disable=SC2034
nerf_emoji_painful=(🔥 💀 🧨 🦂 🌋 👹)
# pick_emoji SESSION DART SET — the emoji for DART from the set named SET (soft|hard|painful).
pick_emoji() {
	local -n set="nerf_emoji_$3"
	local h
	read -r h _ < <(printf '%s' "$1:$2" | cksum)
	printf '%s' "${set[$((${h:-0} % ${#set[@]}))]}"
}

# usage_panel LABEL PCT — "Session:12%", green below 50, yellow from 50, red from 80.
# Nothing when the payload carried no number.
usage_panel() {
	local p="${2%.*}" color
	[[ "$p" =~ ^[0-9]+$ ]] || return 0
	if ((p >= 80)); then
		color="$c_red"
	elif ((p >= 50)); then
		color="$c_yellow"
	else
		color="$c_green"
	fi
	paint "$color" "$1:${p}%"
}

# Shorten path: replace $HOME with ~
short_cwd="${cwd/#$HOME/\~}"

# --- Emoji shortcode conversion ---
# Some agents write Discord/Slack shortcodes instead of Unicode emoji.
# Convert known shortcodes so the statusline always renders correctly.
shortcode_to_emoji() {
	local s="$1"
	case "$s" in
	:mountain:) echo "🏔️" ;;
	:hammer_and_wrench:) echo "🛠️" ;;
	:anchor:) echo "⚓" ;;
	:ocean:) echo "🌊" ;;
	:shield:) echo "🛡️" ;;
	:squid:) echo "🦑" ;;
	:rocket:) echo "🚀" ;;
	:fire:) echo "🔥" ;;
	:skull:) echo "💀" ;;
	:zap:) echo "⚡" ;;
	:eyes:) echo "👀" ;;
	:brain:) echo "🧠" ;;
	:robot:) echo "🤖" ;;
	:crossed_swords:) echo "⚔️" ;;
	:crystal_ball:) echo "🔮" ;;
	:gem:) echo "💎" ;;
	:spider_web:) echo "🕸️" ;;
	:snake:) echo "🐍" ;;
	:wolf:) echo "🐺" ;;
	:eagle:) echo "🦅" ;;
	:ice_cube: | :ice:) echo "🧊" ;;
	:pill:) echo "💊" ;;
	:trumpet: | :postal_horn:) echo "📯" ;;
	:*:) echo "$s" ;; # unknown shortcode — pass through
	*) echo "$s" ;;   # already Unicode — pass through
	esac
}

# --- Agent identity ---
# Resolve from project-local durable path first; fall back to legacy /tmp path
# (transition window — remove fallback after fleet has cycled to the new writer).
dev_name=""
dev_avatar=""
project_root=""
if [ -n "$cwd" ]; then
	project_root="${cwd}"
	agent_file="${project_root}/.claude/agent-identity.json"
	if [ ! -f "$agent_file" ]; then
		dir_hash=$(echo -n "$project_root" | md5sum | cut -d' ' -f1)
		agent_file="/tmp/claude-agent-${dir_hash}.json"
	fi
	if [ -f "$agent_file" ]; then
		IFS=$'\x1f' read -r dev_name dev_avatar < <(jq -r '[.dev_name // "", .dev_avatar // ""] | join("\u001f")' "$agent_file" 2>/dev/null)
		dev_avatar=$(shortcode_to_emoji "$dev_avatar")
	fi
fi

# === PANEL ICONS: asks first, then the per-session indicators, then wavemachine ===

# --- Ask indicators (#1430) ---
# sqtk-asks-sync.sh keeps /tmp/claude-statusline-<dev_name>.asks.json, a cache of this
# agent's open asks on bj:needs: {"asks": [{"kind": "approval", "blocking": true, ...}], ...}.
# Render it as the first panel icons, grouped by kind: blockers first, then blocking asks, then
# non-blocking, each as <icon>[❗][count] ("⛔2 ✅❗ ❓3"). Within a tier: approval, action,
# question, then an unspecified ask. A missing, empty or malformed file renders nothing. One jq
# call; the squawk text is the source of truth and the sync hook rebuilds this file from it.
asks_str=""
if [ -n "$dev_name" ] && [ -f "/tmp/claude-statusline-${dev_name}.asks.json" ]; then
	asks_str=$(jq -r '
		{blocker: ["⛔", 0, 0], approval: ["✅", 1, 0], action: ["🔧", 1, 1],
		 question: ["❓", 1, 2], unspecified: ["🔔", 1, 3]} as $k
		| [(.asks // [])[]
		   | select(type == "object" and (.kind | type) == "string" and $k[.kind] != null)
		   | {icon: $k[.kind][0], tier: (if .kind == "blocker" then 0 elif .blocking == true then 1 else 2 end),
		      rank: $k[.kind][2]}]
		| group_by([.tier, .rank])
		| map(.[0].icon + (if .[0].tier == 1 then "❗" else "" end) + (if length > 1 then "\(length)" else "" end))
		| join(" ")' "/tmp/claude-statusline-${dev_name}.asks.json" 2>/dev/null)
fi

# --- Per-session indicators ---
# Sessions write state to /tmp/claude-statusline-<dev_name>.json
# Format: {"indicators": ["● REC", "W2 3/5", ...]}
indicators_str=""
if [ -n "$dev_name" ]; then
	session_file="/tmp/claude-statusline-${dev_name}.json"
	if [ -f "$session_file" ]; then
		indicators=$(jq -r '.indicators // [] | join(" ")' "$session_file" 2>/dev/null)
		indicators_str=$(paint "$c_yellow" "$indicators")
		# nerf shows `ctx ?` after a compaction (its SessionStart:compact hook
		# rejects the pre-compact reading), and only nerf repaints its own
		# indicator. This render just persisted a fresh reading, so ask nerf to
		# repaint now rather than leave `ctx ?` up until the next nerf call.
		# Background and best-effort: the render never waits on it.
		if [ -n "$remaining_pct" ] && [[ "$session_id" =~ ^[A-Za-z0-9_-]+$ ]] &&
			jq -e '(.indicators // []) | index("nerf:ctx ?")' "$session_file" >/dev/null 2>&1; then
			nerf_bin="${NERF_BIN:-$HOME/.local/bin/nerf-server}"
			if [ -x "$nerf_bin" ]; then
				(cd "${project_root:-.}" 2>/dev/null && "$nerf_bin" refresh-indicator --session-id "$session_id" >/dev/null 2>&1 &)
			fi
		fi
	fi
fi

# --- Wavemachine indicator ---
# /wavemachine writes wavemachine_active:true to .claude/status/state.json at
# launch and clears it on completion/abort. Display 🌊 while active.
# Silent skip if state.json is missing or malformed.
wave_str=""
if [ -n "$project_root" ] && [ -f "$project_root/.claude/status/state.json" ]; then
	wave_active=$(jq -r '.wavemachine_active // false' "$project_root/.claude/status/state.json" 2>/dev/null)
	if [ "$wave_active" = "true" ]; then
		wave_str="🌊"
		# Optional progress when wavemachine tracks wave position
		wave_n=$(jq -r '.wavemachine_active_wave // empty' "$project_root/.claude/status/state.json" 2>/dev/null)
		wave_total=$(jq -r '.wavemachine_total_waves // empty' "$project_root/.claude/status/state.json" 2>/dev/null)
		if [ -n "$wave_n" ] && [ -n "$wave_total" ]; then
			wave_str="🌊 wave ${wave_n}/${wave_total}"
		fi
	fi
fi

icons_panel=""
for part in "$asks_str" "$indicators_str" "$wave_str"; do
	[ -n "$part" ] || continue
	icons_panel+="${icons_panel:+ }$part"
done

# === MODEL-EFFORT: "Sonnet 5.5-medium"; the effort is left out when the payload has none ===
model_panel=""
if [ -n "$model" ]; then
	model_panel=$(paint "$c_purple" "${model}${effort:+-$effort}")
fi

# === CONTEXT: the absolute size, "312K" or "1.2M" (no bar, no percent) ===
# Colors key off nerf dart zones when a nerf config exists for this session;
# otherwise fall back to the legacy 13%/25% thresholds against the full window.
# Current nerf (mcp-server-nerf#32) stores darts as percent of the window used
# under `darts_pct`; an older nerf stores absolute token counts under `darts`.
context_panel=""
if ctx_text=$(fmt_tokens "$ctx_in_tokens"); then
	ctx_color=""
	if [ -n "$remaining_pct" ]; then
		remaining_int=${remaining_pct%.*}

		nerf_config=""
		if [ -n "$session_id" ]; then
			candidate="${NERF_CONFIG_DIR:-/tmp}/nerf-${session_id}.json"
			[ -f "$candidate" ] && nerf_config="$candidate"
		fi

		nerf_pct_soft="" nerf_pct_hard="" nerf_pct_ouch=""
		if [ -n "$nerf_config" ]; then
			IFS=$'\x1f' read -r nerf_pct_soft nerf_pct_hard nerf_pct_ouch < <(jq -r '[.darts_pct.soft // "", .darts_pct.hard // "", .darts_pct.ouch // ""] | map(tostring) | join("\u001f")' "$nerf_config" 2>/dev/null)
		fi

		if [[ "$nerf_pct_soft" =~ ^[0-9]+$ && "$nerf_pct_hard" =~ ^[0-9]+$ && "$nerf_pct_ouch" =~ ^[0-9]+$ ]]; then
			used_int=$((100 - remaining_int))
			if ((used_int >= nerf_pct_ouch)); then
				ctx_color="$c_red"
			elif ((used_int >= nerf_pct_hard)); then
				ctx_color="$c_orange"
			elif ((used_int >= nerf_pct_soft)); then
				ctx_color="$c_yellow"
			else
				ctx_color="$c_green"
			fi
		elif [ -n "$nerf_config" ] && [ -n "$ctx_used_tokens" ] && [ "$ctx_used_tokens" -gt 0 ] 2>/dev/null; then
			nerf_soft=$(jq -r '.darts.soft // empty' "$nerf_config" 2>/dev/null)
			nerf_hard=$(jq -r '.darts.hard // empty' "$nerf_config" 2>/dev/null)
			nerf_ouch=$(jq -r '.darts.ouch // empty' "$nerf_config" 2>/dev/null)

			if [ -n "$nerf_soft" ] && [ -n "$nerf_hard" ] && [ -n "$nerf_ouch" ]; then
				if ((ctx_used_tokens >= nerf_ouch)); then
					ctx_color="$c_red"
				elif ((ctx_used_tokens >= nerf_hard)); then
					ctx_color="$c_orange"
				elif ((ctx_used_tokens >= nerf_soft)); then
					ctx_color="$c_yellow"
				else
					ctx_color="$c_green"
				fi
			else
				# Malformed nerf config — fall back to legacy thresholds
				nerf_config=""
				ctx_color=""
			fi
		fi

		if [ -z "$ctx_color" ]; then
			if ((remaining_int <= 13)); then
				ctx_color="$c_red"
			elif ((remaining_int <= 25)); then
				ctx_color="$c_yellow"
			else
				ctx_color="$c_green"
			fi
		fi
	fi
	if [ -n "$ctx_color" ]; then
		context_panel=$(paint "$ctx_color" "$ctx_text")
	else
		context_panel="$ctx_text"
	fi
fi

# === SESSION and WEEKLY: only when the payload carries them ===
session_panel=$(usage_panel "Session" "$five_hour_pct")
weekly_panel=$(usage_panel "Weekly" "$seven_day_pct")

# === NERF, RUNWAY, FLOOR (#1428) ===
# The context arithmetic is scripts/lib/context-math.sh's, shared with the reseed gate so the
# two cannot disagree. It reads the reading this render just persisted (or a temp copy when the
# state directory can't be written) and nerf's per-session config.
declare -A CM=()
cm_lib=""
for d in "${CLAUDE_STATUSLINE_LIB:-}" "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../scripts/lib" "$HOME/.claude/scripts/lib"; do
	if [ -n "$d" ] && [ -r "$d/context-math.sh" ]; then
		cm_lib="$d/context-math.sh"
		break
	fi
done
nerf_file=""
if [[ "$session_id" =~ ^[A-Za-z0-9_-]+$ ]]; then nerf_file="${NERF_CONFIG_DIR:-/tmp}/nerf-${session_id}.json"; fi
cm_tmp=""
if [ -n "$cm_lib" ] && [ -n "$reading_json" ] && [[ "${ctx_in_tokens%.*}" =~ ^[0-9]+$ ]]; then
	cm_reading="$persisted_reading"
	if [ -z "$cm_reading" ] && cm_tmp=$(mktemp 2>/dev/null) && printf '%s\n' "$reading_json" >"$cm_tmp" 2>/dev/null; then
		cm_reading="$cm_tmp"
	fi
	if [ -n "$cm_reading" ]; then
		# shellcheck source=scripts/lib/context-math.sh
		source "$cm_lib"
		while IFS='=' read -r k v; do CM[$k]="$v"; done < <(context_math "$cm_reading" "$nerf_file" 2>/dev/null)
	fi
	[ -n "$cm_tmp" ] && rm -f "$cm_tmp"
fi

# --- Nerf: the next dart not yet reached, with its emoji, its name and a five-cell bar ---
# The bar is the progress from the previous dart (from 0 for soft) to the next one. Past ouch it is
# full and the name stays "ouch". Colours follow the zones: green below soft, yellow to hard, orange
# to ouch, red from ouch. No nerf config for the session (or none the helper can place): no panel.
nerf_panel=""
if [ -n "$nerf_file" ] && [ -f "$nerf_file" ] && [[ "${CM[used_tokens]:-}" =~ ^[0-9]+$ ]] &&
	[[ "${CM[soft_at_tokens]:-}" =~ ^[0-9]+$ && "${CM[hard_at_tokens]:-}" =~ ^[0-9]+$ && "${CM[ouch_at_tokens]:-}" =~ ^[0-9]+$ ]]; then
	n_used="${CM[used_tokens]}"
	n_soft="${CM[soft_at_tokens]}" n_hard="${CM[hard_at_tokens]}" n_ouch="${CM[ouch_at_tokens]}"
	if ((n_used < n_soft)); then
		n_dart=soft n_set=soft n_prev=0 n_target=$n_soft n_color="$c_green"
	elif ((n_used < n_hard)); then
		n_dart=hard n_set=hard n_prev=$n_soft n_target=$n_hard n_color="$c_yellow"
	elif ((n_used < n_ouch)); then
		n_dart=ouch n_set=painful n_prev=$n_hard n_target=$n_ouch n_color="$c_orange"
	else
		n_dart=ouch n_set=painful n_prev=$n_hard n_target=$n_ouch n_color="$c_red"
	fi
	if ((n_used >= n_ouch)); then
		n_cells=5
	elif ((n_target > n_prev)); then
		n_cells=$(((n_used - n_prev) * 5 / (n_target - n_prev)))
		if ((n_cells < 0)); then n_cells=0; elif ((n_cells > 5)); then n_cells=5; fi
	else
		n_cells=0
	fi
	n_bar=""
	for ((i = 0; i < 5; i++)); do
		if ((i < n_cells)); then n_bar+="▰"; else n_bar+="▱"; fi
	done
	nerf_panel=$(paint "$n_color" "$(pick_emoji "$session_id" "$n_dart" "$n_set") $n_dart $n_bar")
fi

# --- Runway: tokens left until the nearer of reseed and autocompact ---
# "↻ 88K auto" when reseed is nearer (the tag is nerf's mode: auto = ultraviolence, ask =
# hurt-me-plenty, nudge = not-too-rough; an unreadable mode counts as ultraviolence, as in the
# gate), "🗜 62K" when autocompact is. At or past the trigger it reads 0K and the panel turns red.
runway_panel=""
if [[ "${CM[runway_tokens]:-}" =~ ^[0-9]+$ ]]; then
	r_text="$(runway_fmt "${CM[runway_tokens]}")"
	if [ "${CM[runway_by]:-}" = reseed ]; then
		case "${CM[nerf_mode]:-}" in
		hurt-me-plenty) r_mode=ask ;;
		not-too-rough) r_mode=nudge ;;
		*) r_mode=auto ;;
		esac
		r_text="↻ $r_text $r_mode"
	else
		r_text="🗜 $r_text"
	fi
	if [ "${CM[runway_tokens]}" -eq 0 ]; then
		runway_panel=$(paint "$c_red" "$r_text")
	else
		runway_panel="$r_text"
	fi
fi

# --- Floor: the context size right after the last sharp drop (a reseed, clear or compact) ---
# A drop of at least 30% AND at least 20K tokens against the same session's previous render records
# the new size as a floor; a session's first render records one too. State is ~/.claude/state/context/
# <key>.floor.json, keyed by dev-name (the session id when there is none): {floors: [{size, ts}] (the
# last five), last: {<session id>: the size at that session's previous render} (the eight most
# recently rendered sessions)}. Shown as "floor 91K" with an arrow
# against the previous floor: ▲ above it, ▼ below, = within 2K. No floor yet: no panel. Writes are
# atomic and best-effort: a failed one never costs the render. One jq reads the state and works
# out the new one (the state file is its last argument, /dev/null when there is none).
floor_panel=""
floor_key=""
if [[ "$dev_name" =~ ^[A-Za-z0-9._-]+$ ]]; then
	floor_key="$dev_name"
elif [[ "$session_id" =~ ^[A-Za-z0-9_-]+$ ]]; then
	floor_key="$session_id"
fi
if [ -n "$floor_key" ]; then
	floor_file="$ctx_state_dir/${floor_key}.floor.json"
	floor_src=/dev/null
	if [ -f "$floor_file" ] && [ -O "$floor_file" ] && [ ! -L "$floor_file" ]; then floor_src="$floor_file"; fi
	# A size of 0 is Claude Code before its first response, not a context that shrank to nothing:
	# it records nothing, or the floor would be pinned at 0.
	floor_size=null
	if [[ "${ctx_in_tokens%.*}" =~ ^[0-9]+$ ]] && ((10#${ctx_in_tokens%.*} > 0)); then floor_size="${ctx_in_tokens%.*}"; fi
	# The "previous render" is per SESSION (`last` maps session id to its last size), so two sessions
	# of one dev-name rendering alternately each compare with themselves and do not thrash the shared
	# floors. A session new to the file records a floor on its first render. The file is rewritten only
	# when something changed that matters: a floor, a new session, a size 1K or more from `last`, or
	# the session no longer being the most recently rendered one (so a session sitting at a steady size
	# still moves to the end of the eight and is not evicted by newer ones).
	# shellcheck disable=SC2016  # a jq program: the $vars are jq's
	floor_jq='
		def abs: if . < 0 then -. else . end;
		(([inputs] | first // {}) | if type == "object" then . else {} end) as $st
		| (($st.floors // []) | if type == "array" then .[-5:] else [] end) as $fl
		| (($st.last // {}) | if type == "object" then . else {} end) as $lasts
		| ($lasts[$sid] // null) as $prev
		| (if $size == null then false
		   elif ($fl | length) == 0 or $prev == null then true
		   else ($prev - $size) >= 20000 and (($prev - $size) * 100 >= $prev * 30) end) as $rec
		| (if $rec then (($fl + [{size: $size, ts: $now}]) | .[-5:]) else $fl end) as $nfl
		| (if $size == null then $lasts else ((($lasts | del(.[$sid])) + {($sid): $size}) | to_entries | .[-8:] | from_entries) end) as $nlasts
		| {floors: $nfl, last: $nlasts} as $new
		| [($nfl | last | .size // ""), ($nfl | if length > 1 then .[-2].size else "" end),
		   (if $size == null then 0
		    elif $rec or $prev == null or (($prev - $size) | abs) >= 1000 or ($st.floors | type) != "array"
		         or (($lasts | keys_unsorted | last) != $sid) then 1
		    else 0 end),
		   ($new | tojson)] | map(tostring) | join("\u001f")'
	floor_out=$(jq -nr --argjson size "$floor_size" --argjson now "$now" --arg sid "$session_id" "$floor_jq" "$floor_src" 2>/dev/null) ||
		floor_out=$(jq -nr --argjson size "$floor_size" --argjson now "$now" --arg sid "$session_id" "$floor_jq" /dev/null 2>/dev/null)
	IFS=$'\x1f' read -r f_size f_prev f_changed f_state <<<"$floor_out"
	if [[ "$f_changed" == 1 && -n "$f_state" ]]; then
		{
			f_tmp=""
			if mkdir -p "$ctx_state_dir" && f_tmp=$(mktemp "$ctx_state_dir/.floor.XXXXXX") && printf '%s\n' "$f_state" >"$f_tmp"; then
				mv -f "$f_tmp" "$floor_file"
			else
				[ -n "$f_tmp" ] && rm -f "$f_tmp"
			fi
		} 2>/dev/null
	fi
	if [[ "$f_size" =~ ^[0-9]+$ ]]; then
		floor_panel="floor $(fmt_tokens "$f_size")"
		if [[ "$f_prev" =~ ^[0-9]+$ ]]; then
			if ((f_size - f_prev > 2000)); then
				floor_panel+=" $(paint "$c_yellow" "▲")"
			elif ((f_prev - f_size > 2000)); then
				floor_panel+=" $(paint "$c_green" "▼")"
			else
				floor_panel+=" ="
			fi
		fi
	fi
fi

# === SPEND (#1429): API or Bedrock spend since the begin marker ===
# A subscription session reports a notional cost that means nothing, so the panel appears only when
# the payload has NO rate_limits and carries a cost above zero (a fresh session, and a subscriber's
# first render before rate_limits arrives, both report 0: nothing is known yet, so nothing is shown or
# recorded). This session's latest cost is recorded in
# ~/.claude/state/spend/<session_id>.json ({"cost_usd", "ts"}), only when it changed, atomically and
# best-effort; files older than 30 days are pruned then. The panel is the sum over every session file
# of (its cost less its baseline from `statusline-spend begin`), "$12.34". The arithmetic is
# scripts/lib/spend-math.sh's, shared with the CLI. This session's own cost is passed in, so a render
# that cannot write still shows it. An unsafe session id (or "begin", the marker's name) writes nothing.
spend_panel=""
if [ "$has_limits" = 0 ] && [[ "$cost_usd" =~ ^[0-9]+([.][0-9]+)?([eE][-+]?[0-9]+)?$ ]] && [ -n "$cm_lib" ] &&
	[ -r "${cm_lib%/*}/spend-math.sh" ]; then
	# shellcheck source=scripts/lib/spend-math.sh
	source "${cm_lib%/*}/spend-math.sh"
	spend_state_dir="$(spend_dir)"
	spend_sid=""
	if spend_session_id_ok "$session_id"; then spend_sid="$session_id"; fi
	# An unsafe or missing id can't name a file, but its cost still counts in the sum it shows: it
	# goes in under a placeholder key and is never written.
	IFS=$'\x1f' read -r spend_sum _ spend_saved _ < <(spend_summary "$spend_state_dir" "${spend_sid:-unkeyed-session}" "$cost_usd")
	if [[ "$spend_sum" =~ ^[0-9]+([.][0-9]+)?([eE][-+]?[0-9]+)?$ ]]; then
		spend_panel="$(spend_money "$spend_sum")"
	fi
	if [ -n "$spend_sid" ] && [ "$spend_saved" = 0 ]; then
		{
			spend_tmp=""
			if mkdir -p "$spend_state_dir" && spend_tmp=$(mktemp "$spend_state_dir/.spend.XXXXXX") &&
				printf '{"cost_usd": %s, "ts": %s}\n' "$cost_usd" "$now" >"$spend_tmp"; then
				mv -f "$spend_tmp" "$spend_state_dir/${spend_sid}.json"
				find "$spend_state_dir" -maxdepth 1 -type f -name '*.json' ! -name begin.json -mtime +30 -delete
			else
				[ -n "$spend_tmp" ] && rm -f "$spend_tmp"
			fi
		} 2>/dev/null
	fi
fi

# === ROW 2 ===
agent_panel=""
if [ -n "$dev_name" ]; then
	agent_panel="$(paint "$c_fuchsia" "$dev_name")${dev_avatar:+ $dev_avatar}"
fi

# --- Git: project-branch (worktree), cached a few seconds per cwd ---
# Project is the main repo's folder, taken from the git common directory so a linked worktree
# shows its project and not the worktree's folder. (worktree) appears only in a linked worktree.
# Cache lines: project, branch, worktree, dirty, staged, ahead, behind.
git_lookup() {
	local out gitdir common top branch_line branch ahead=0 behind=0 staged=0 dirty=0 line status_lines
	[ -n "$cwd" ] || return 1
	out=$(GIT_OPTIONAL_LOCKS=0 git -C "$cwd" rev-parse --git-dir --git-common-dir --show-toplevel 2>/dev/null) || return 1
	gitdir=$(sed -n 1p <<<"$out")
	common=$(sed -n 2p <<<"$out")
	top=$(sed -n 3p <<<"$out")
	[[ "$gitdir" == /* ]] || gitdir="$cwd/$gitdir"
	[[ "$common" == /* ]] || common="$cwd/$common"
	gitdir=$(cd "$gitdir" 2>/dev/null && pwd -P) || return 1
	common=$(cd "$common" 2>/dev/null && pwd -P) || return 1

	local project worktree=""
	if [[ "$common" == */.git ]]; then project=$(basename "${common%/.git}"); else project=$(basename "${common%.git}"); fi
	if [ "$gitdir" != "$common" ]; then worktree=$(basename "$top"); fi

	local git_output
	git_output=$(GIT_OPTIONAL_LOCKS=0 git -C "$cwd" status --porcelain -b 2>/dev/null) || return 1
	branch_line="${git_output%%$'\n'*}"
	branch="${branch_line#\#\# }"
	branch="${branch%%...*}"
	branch="${branch%% \[*}"
	if [[ "$branch" == "HEAD (no branch)"* || "$branch" == "No commits yet on "* || "$branch" == "Initial commit on "* ]]; then
		if [[ "$branch" == "No commits yet on "* ]]; then
			branch="${branch#No commits yet on }"
		elif [[ "$branch" == "Initial commit on "* ]]; then # git before 2.28
			branch="${branch#Initial commit on }"
		else
			branch=$(GIT_OPTIONAL_LOCKS=0 git -C "$cwd" rev-parse --short HEAD 2>/dev/null)
		fi
	fi
	if [[ "$branch_line" =~ \[ahead\ ([0-9]+) ]]; then ahead="${BASH_REMATCH[1]}"; fi
	if [[ "$branch_line" =~ behind\ ([0-9]+) ]]; then behind="${BASH_REMATCH[1]}"; fi
	if [[ "$git_output" == *$'\n'* ]]; then
		status_lines="${git_output#*$'\n'}"
		while IFS= read -r line; do
			[[ "${line:0:1}" =~ [MADRC] ]] && ((staged++))
			[[ "${line:1:1}" =~ [MADRC\?] ]] && ((dirty++))
		done <<<"$status_lines"
	fi
	printf '%s\n%s\n%s\n%s\n%s\n%s\n%s\n' "$project" "$branch" "$worktree" "$dirty" "$staged" "$ahead" "$behind"
}

git_info=""
if [ -n "$cwd" ]; then
	git_ttl="${CLAUDE_STATUSLINE_GIT_TTL:-5}"
	[[ "$git_ttl" =~ ^[0-9]+$ ]] || git_ttl=5
	# The cache is this user's own: the file name carries the uid, and a file that is not ours (or is
	# a link) is never read. The directory is often a shared /tmp, so a file there could have been
	# planted by anyone, and what is read back ends up in arithmetic and on the terminal.
	git_cache="${CLAUDE_STATUSLINE_CACHE_DIR:-${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}}/claude-statusline-git-$(id -u)-$(echo -n "$cwd" | md5sum | cut -d' ' -f1)"
	if ((git_ttl > 0)) && [ -f "$git_cache" ] && [ -O "$git_cache" ] && [ ! -L "$git_cache" ] &&
		cache_mtime=$(stat -c %Y "$git_cache" 2>/dev/null) && ((now - cache_mtime < git_ttl)); then
		git_info=$(cat "$git_cache" 2>/dev/null)
	else
		if git_info=$(git_lookup); then
			if ((git_ttl > 0)); then
				git_tmp=$(mktemp "${git_cache}.XXXXXX" 2>/dev/null) &&
					{ printf '%s\n' "$git_info" >"$git_tmp" && mv -f "$git_tmp" "$git_cache"; } 2>/dev/null
				[ -n "${git_tmp:-}" ] && rm -f "$git_tmp" 2>/dev/null
			fi
		else
			git_info=""
		fi
	fi
fi

project_panel=""
if [ -n "$git_info" ]; then
	{
		IFS= read -r g_project
		IFS= read -r g_branch
		IFS= read -r g_worktree
		IFS= read -r g_dirty
		IFS= read -r g_staged
		IFS= read -r g_ahead
		IFS= read -r g_behind
	} <<<"$git_info"
	# Whatever the lines hold, they are text for the terminal and numbers for arithmetic: strip
	# control characters from the text and take anything that is not a number as 0.
	g_project="${g_project//[[:cntrl:]]/}"
	g_branch="${g_branch//[[:cntrl:]]/}"
	g_worktree="${g_worktree//[[:cntrl:]]/}"
	for n in g_dirty g_staged g_ahead g_behind; do
		[[ "${!n}" =~ ^[0-9]+$ ]] || printf -v "$n" 0
	done
	project_text="${g_project}-${g_branch}"
	[ -n "$g_worktree" ] && project_text+=" (${g_worktree})"
	project_panel=$(paint "$c_cyan" "$project_text")
	if ((g_dirty > 0)); then
		project_panel+=" $(paint "$c_red" "✗")"
	else
		project_panel+=" $(paint "$c_green" "✓")"
	fi
	if ((g_staged > 0)); then project_panel+=" $(paint "$c_yellow" "+${g_staged}")"; fi
	if ((g_ahead > 0)); then project_panel+=" $(paint "$c_yellow" "↑${g_ahead}")"; fi
	if ((g_behind > 0)); then project_panel+=" $(paint "$c_yellow" "↓${g_behind}")"; fi
fi

cwd_panel=$(paint "$c_blue" "$short_cwd")

# === Render ===
printf '%s\n' "$(join_panels "$icons_panel" "$model_panel" "$nerf_panel" "$runway_panel" "$context_panel" "$floor_panel" "$session_panel" "$weekly_panel" "$spend_panel")"
printf '%s\n' "$(join_panels "$agent_panel" "$project_panel" "$cwd_panel")"
