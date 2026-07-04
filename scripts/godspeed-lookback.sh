#!/usr/bin/env bash
# godspeed-lookback.sh — Godspeed mandate lookback utility.
#
# Scans a Claude Code JSONL transcript for the most-recent `godspeed` and
# `HALT!` in user-role turns and emits the arm status. Sourced by both Stop
# hooks; also runnable standalone with --demo or --eval.
#
# Output of godspeed_status():
#   ARMED <d>     godspeed found d user turns ago; HALT! not newer
#   HALTED        HALT! is newer than godspeed (or godspeed never appeared)
#   UNARMED       no godspeed within the last N user turns
#
# Usage (sourced):
#   source godspeed-lookback.sh
#   result=$(godspeed_status /path/to/transcript.jsonl)
#
# Usage (standalone):
#   ./godspeed-lookback.sh --demo                         # decision matrix
#   ./godspeed-lookback.sh --eval /path/to/transcript     # evaluate file
#   ./godspeed-lookback.sh --decide                       # read CC hook stdin
#
# Env:
#   GODSPEED_WINDOW                  lookback window in user turns (default: 200)
#   GODSPEED_VERIFIED_CONFIDENCE     confidence when test sentinel exists (default: 80)
#   GODSPEED_UNVERIFIED_CONFIDENCE   confidence when no test sentinel (default: 40)
#
# Issue: cc-workflow#818

# ---------------------------------------------------------------------------
# godspeed_status <transcript_path>
#
# Scans the last GODSPEED_WINDOW user turns. Only user-role turns count —
# assistant echoes of "godspeed" do not arm the mandate.
# ---------------------------------------------------------------------------
godspeed_status() {
	local transcript_path="$1"
	local N="${GODSPEED_WINDOW:-200}"

	[[ -f "$transcript_path" ]] || {
		echo "UNARMED"
		return 0
	}

	# Read enough lines to cover N user turns. Each user turn has at least
	# one line; with interleaved assistant/tool lines the real count is higher.
	# 20× N + 500 is a conservative ceiling that stays fast.
	local scan_lines=$((N * 20 + 500))

	tail -n "$scan_lines" "$transcript_path" 2>/dev/null |
		jq -rs --argjson N "$N" '
      # Collect user turns that carry actual human text — exclude tool-result
      # wrapper entries (type=="user" but content is tool_result blocks with no
      # text).  Without this filter every tool result inflates d by 1, causing
      # the mandate to age out far faster than intended.
      [.[] | select(
        .type == "user" and
        ((.message.content // []) | map(select(.type == "text") | .text) | join("") | length > 0)
      )] as $user_turns |

      # Reverse so index 0 = most-recent user turn.
      ($user_turns | reverse | to_entries) as $rev |

      # Find the most-recent user turn containing \bgodspeed\b (case-sensitive,
      # word-bounded). Assistant echoes are excluded because we already filtered
      # to type=="user". Returns the first (most-recent) matching entry index,
      # or -1 if none.
      ($rev | map(select(
        (.value.message.content // []) |
        map(select(.type == "text") | .text) |
        join(" ") |
        test("\\bgodspeed\\b")
      )) | first | .key // -1) as $gs_d |

      # Find the most-recent user turn containing "HALT!" (exact, case-sensitive).
      ($rev | map(select(
        (.value.message.content // []) |
        map(select(.type == "text") | .text) |
        join(" ") |
        test("HALT!")
      )) | first | .key // -1) as $halt_d |

      # Decision:
      # - godspeed not found or aged out → UNARMED
      # - HALT! is more recent (smaller d = closer to present) → HALTED
      # - otherwise → ARMED <d>
      if $gs_d == -1 or $gs_d >= $N then
        "UNARMED"
      elif $halt_d != -1 and $halt_d < $gs_d then
        "HALTED"
      else
        "ARMED \($gs_d)"
      end
    ' 2>/dev/null || echo "UNARMED"
}

# ---------------------------------------------------------------------------
# godspeed_decision <arm_status> <last_assistant_text> <session_id>
#
# Returns the decision given the arm status and context:
#   GO     continue autonomously
#   ASK <d> <bar_pct> <supplied_pct>    checkpoint — surface uncertainty
#   STOP   gated axis hit — always surface regardless of mandate
#   NOOP   hook stands down
# ---------------------------------------------------------------------------
godspeed_decision() {
	local arm_status="$1"
	local last_text="$2"
	local session_id="${3:-}"
	local N="${GODSPEED_WINDOW:-200}"
	local verified_pct="${GODSPEED_VERIFIED_CONFIDENCE:-80}"
	local unverified_pct="${GODSPEED_UNVERIFIED_CONFIDENCE:-40}"

	# Hard gate — always fires regardless of mandate or loop state.
	#
	# Narrowed from the original pattern: removed `delete`, `drop`, `tag`,
	# `wipe`, standalone `ship`/`publish`/`release` — all fire on benign
	# narration (e.g. "I'll delete the temp file", "publish the docs"). The
	# remaining words are specific enough to be unambiguous infra/ops indicators.
	# `migrat[a-z]*` (was `migrat`) fixes the word-boundary false-negative on
	# "migrate"/"migration".
	local PATTERN_GATED_AXIS='(?i)\b(prod(?:uction)?|deploy[a-z]*|rollout|force[\- ]?push|go[\- ]?live|cut[\- ]?over|promote|rotate|tear[\- ]?down|irreversible|destroy[a-z]*|destructive|credential[a-z]*|secret[a-z]*|migrat[a-z]*|fleet[\- ]wide)\b|(merge|push)\s+(to\s+)?(main|master|prod)\b'
	if printf '%s' "$last_text" | grep -Pq "$PATTERN_GATED_AXIS" 2>/dev/null; then
		echo "STOP"
		return 0
	fi

	# No mandate → hook stands down.
	case "$arm_status" in
	UNARMED | HALTED)
		echo "NOOP"
		return 0
		;;
	esac

	# Mandate active — extract d and compute bar.
	local d
	d=$(echo "$arm_status" | awk '{print $2}')
	local bar_pct=$((d * 100 / N))

	# Verification sentinel (written by post-tool-test-sentinel.sh).
	local sentinel="/tmp/claude-tests-ran-${session_id}"
	local supplied_pct
	if [[ -n "$session_id" && -s "$sentinel" ]]; then
		supplied_pct="$verified_pct"
	else
		supplied_pct="$unverified_pct"
	fi

	if ((supplied_pct >= bar_pct)); then
		echo "GO"
	else
		echo "ASK $d $bar_pct $supplied_pct"
	fi
}

# ---------------------------------------------------------------------------
# _godspeed_notify <kind> [d] [N]
#
# Notifies BJ via vox + Discord on STOP or ASK. Best-effort; never fails.
# kind: "STOP" | "ASK"
# ---------------------------------------------------------------------------
_godspeed_notify() {
	local kind="$1"
	local d="${2:-?}"
	local N="${GODSPEED_WINDOW:-200}"

	# Agent identity (best-effort).
	local identity_suffix=""
	local identity_file=""
	if [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
		identity_file="${CLAUDE_PROJECT_DIR}/.claude/agent-identity.json"
	fi
	if [[ -f "$identity_file" ]] && command -v jq &>/dev/null; then
		local dev_name dev_avatar dev_team
		dev_name=$(jq -r '.dev_name // empty' "$identity_file" 2>/dev/null || true)
		dev_avatar=$(jq -r '.dev_avatar // empty' "$identity_file" 2>/dev/null || true)
		dev_team=$(jq -r '.dev_team // empty' "$identity_file" 2>/dev/null || true)
		[[ -n "$dev_name" ]] && identity_suffix=" — **${dev_name}** ${dev_avatar} (${dev_team})"
	fi

	local vox_msg discord_msg
	if [[ "$kind" == "STOP" ]]; then
		vox_msg="Hey BJ, a Stop hook fired — gated axis detected. Check the terminal."
		discord_msg="🛑 **Godspeed STOP** — gated axis detected in last assistant turn. Session paused.${identity_suffix}"
	else
		vox_msg="Hey BJ, godspeed mandate checkpoint — the agent has a question. Check the terminal."
		discord_msg="⚠️ **Godspeed checkpoint** — mandate at d=${d}/N=${N}. Agent naming its uncertainty.${identity_suffix}"
	fi

	# vox (best-effort).
	if command -v vox &>/dev/null; then
		vox "$vox_msg" 2>/dev/null || true
	fi

	# Discord via stdlib python3 (no external deps).
	local token_file="$HOME/secrets/discord-bot-token"
	if [[ -f "$token_file" ]]; then
		local token
		token=$(tr -d '[:space:]' <"$token_file")
		python3 -c "
import urllib.request, json, sys
token, channel_id, msg = sys.argv[1], '1518536836673310800', sys.argv[2]
req = urllib.request.Request(
    f'https://discord.com/api/v10/channels/{channel_id}/messages',
    data=json.dumps({'content': msg}).encode(),
    headers={'Authorization': f'Bot {token}', 'Content-Type': 'application/json'},
    method='POST'
)
urllib.request.urlopen(req, timeout=5)
" "$token" "$discord_msg" 2>/dev/null || true
	fi
}

# ---------------------------------------------------------------------------
# Standalone entrypoint (only when executed directly, not sourced).
# ---------------------------------------------------------------------------
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
	case "${1:-}" in
	--demo)
		N="${GODSPEED_WINDOW:-200}"
		V="${GODSPEED_VERIFIED_CONFIDENCE:-80}"
		U="${GODSPEED_UNVERIFIED_CONFIDENCE:-40}"
		echo "Godspeed decision matrix (N=${N}, verified=${V}%, unverified=${U}%)"
		echo ""
		printf "%-6s %-5s %-26s %-26s\n" "d" "bar%" "VERIFIED (tests green)" "UNVERIFIED"
		printf "%-6s %-5s %-26s %-26s\n" "------" "-----" "------------------------" "------------------------"
		for d in 0 25 50 100 150 190 200 250; do
			if ((d > N)); then
				printf "%-6s %-5s %-26s %-26s\n" "$d" "—" "NOOP (aged out)" "NOOP (aged out)"
				continue
			fi
			bar=$((d * 100 / N))
			v_out="GO"
			((V < bar)) && v_out="ASK"
			u_out="GO"
			((U < bar)) && u_out="ASK"
			((d == N)) && {
				v_out="ASK"
				u_out="ASK"
			}
			printf "%-6s %-5s %-26s %-26s\n" "$d" "${bar}%" "$v_out" "$u_out"
		done
		echo ""
		echo "Overrides: gated-axis → STOP (any d);  HALT! newer than godspeed → NOOP"
		;;

	--eval)
		transcript="${2:-}"
		[[ -z "$transcript" ]] && {
			echo "Usage: $0 --eval <transcript.jsonl>" >&2
			exit 1
		}
		godspeed_status "$transcript"
		;;

	--decide)
		INPUT=$(cat 2>/dev/null || true)
		TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null || true)
		SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)
		LAST_TEXT=$(
			[[ -f "$TRANSCRIPT_PATH" ]] && tail -n 200 "$TRANSCRIPT_PATH" 2>/dev/null |
				jq -rs '[.[] | select(.type == "assistant")] | last |
					(.message.content // []) | map(select(.type == "text") | .text) | join(" ")
				' 2>/dev/null || echo ""
		)
		ARM=$(godspeed_status "$TRANSCRIPT_PATH")
		godspeed_decision "$ARM" "$LAST_TEXT" "$SESSION_ID"
		;;

	*)
		echo "Usage: $0 [--demo | --eval <transcript> | --decide]" >&2
		exit 1
		;;
	esac
fi
