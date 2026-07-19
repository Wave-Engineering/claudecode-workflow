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
# Gated-action matching (cc-workflow#917).
#
# The gate keys on what the turn DID (tool_use blocks), never on what it SAID.
# Text matching was wrong in both directions at once: it fired on "the live
# deployed tool schema" (innocent prose) while missing `deploy_freshness` (a
# real token, blocked by \b at the underscore). A word list cannot separate
# those, because the discriminator is not the word — it is whether the turn
# acted. See #917.
#
# Two rules keep the matcher honest:
#   1. VERBS, not nouns. We match invoked commands (`terraform apply`), not
#      scary words (`production`).
#   2. COMMAND POSITION only. Each Bash command is split on shell separators
#      and only the HEAD of a segment is tested, so a gated verb appearing as
#      DATA — `grep 'git push --force' f` — does not match. This is the failure
#      mode a naive scan of tool_use.input would reproduce one layer down.
#
# Known limits (deliberate, documented rather than papered over):
#   - Splitting is textual: a `;`, `|` or `&` INSIDE a quoted string starts a
#     new segment, so `git commit -m "wip; terraform apply later"` can match on
#     the quoted text. That direction fails CLOSED (a spurious salience signal
#     the agent can dismiss in one line), which is the acceptable direction.
#   - Coverage is direct `Bash`/`Write`/`Edit`/`NotebookEdit` only. A sub-agent
#     (`Task`) runs its tools in a separate transcript, and other shell-capable
#     MCP tools are not inspected — neither is visible here.
# ---------------------------------------------------------------------------

# grep -P is required (the patterns use \b, \s and lazy quantifiers, so -E is
# not a drop-in). On a grep without PCRE the match would silently return false —
# i.e. fail OPEN. Probe once and warn loudly rather than gate on nothing.
_godspeed_require_pcre() {
	if ! printf 'x' | grep -Pq 'x' 2>/dev/null; then
		echo "[godspeed] WARNING: grep -P unavailable — gated-action matching is INACTIVE" >&2
		return 1
	fi
	return 0
}

# Gated commands, anchored at segment head (after prefix normalization).
#
# `git` accepts global flags before the subcommand (`git -C <dir> push …`), which
# this repo's worktree/fleet work uses routinely — so the git rules tolerate them
# explicitly rather than anchoring straight to `git push`.
_GODSPEED_GIT_GLOBALS='((-C\s+\S+|--git-dir=\S+|--work-tree=\S+|-c\s+\S+)\s+)*'
_GODSPEED_GATED_CMD_RE="^(git\s+${_GODSPEED_GIT_GLOBALS}push\b[^\n]*?(--force\b|--force-with-lease\b|-f\b)|git\s+${_GODSPEED_GIT_GLOBALS}push\b[^\n]*?\b(main|master|release/)|git\s+${_GODSPEED_GIT_GLOBALS}push\s+--delete\b|terraform\s+(apply|destroy)\b|kubectl\s+(apply|delete|rollout)\b|helm\s+(upgrade|install|uninstall)\b|docker\s+push\b|systemctl\s+(stop|restart|disable)\b|gh\s+release\s+(create|delete)\b)"

# ---------------------------------------------------------------------------
# _godspeed_strip_prefixes <segment>
#
# Normalizes a shell segment down to its invoked command so `^`-anchoring is
# meaningful. Without this, anchoring is trivially defeated by things that
# legally precede a command — most importantly `sudo`, which defeated the entire
# systemctl rule (stopping a unit essentially always needs root). (#917)
#
# Applied repeatedly until stable so wrappers compose (`sudo timeout 30 env …`).
# ---------------------------------------------------------------------------
_godspeed_strip_prefixes() {
	local s="$1" prev="" i=0
	while [[ "$s" != "$prev" ]] && ((i < 6)); do
		prev="$s"
		i=$((i + 1))
		s=$(printf '%s' "$s" | sed -E '
			s/^[[:space:]]+//
			s/^[({`]+[[:space:]]*//
			s/^\$\([[:space:]]*//
			s/^([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)+//
			s/^(sudo|command|nohup|exec|nice|stdbuf|xargs)([[:space:]]+-[^[:space:]]+)*[[:space:]]+//
			s/^env([[:space:]]+-[^[:space:]]+)*[[:space:]]+//
			s/^time([[:space:]]+-[^[:space:]]+)*[[:space:]]+//
			s/^timeout([[:space:]]+-[^[:space:]]+)*[[:space:]]+[0-9]+[smhd]?[[:space:]]+//
			s/^(ba|z|da|k)?sh[[:space:]]+-c[[:space:]]+['"'"'"]?//
			s/^ssh[[:space:]]+([^[:space:]]+[[:space:]]+)+?['"'"'"]//
		')
	done
	printf '%s' "$s"
}

# Gated write targets — the declared/desired-state clause of the ABSOLUTE prod
# rule. Editing these primes a prod change even when nothing deploys today.
_GODSPEED_GATED_PATH_RE='(sites/[^/]*prod[^/]*/|/production/|\.prod\.(ya?ml|json|tf)$|(^|/)prod/[^ ]*\.(ya?ml|json|tf)$)'

# ---------------------------------------------------------------------------
# godspeed_gated_actions <tools_json>
#
# Echoes one line per gated action found (empty output = nothing gated).
# <tools_json> is a JSON array of {name, input} from the last assistant turn.
# ---------------------------------------------------------------------------
godspeed_gated_actions() {
	local tools_json="${1:-}"
	[[ -z "$tools_json" || "$tools_json" == "null" || "$tools_json" == "[]" ]] && return 0
	command -v jq &>/dev/null || return 0
	_godspeed_require_pcre || return 0

	# --- Bash: gated verb at command position ---
	local cmds seg stripped
	cmds=$(printf '%s' "$tools_json" |
		jq -r '.[]? | select(.name == "Bash") | (.input.command // "")' 2>/dev/null || true)

	if [[ -n "$cmds" ]]; then
		# `|| [[ -n "$seg" ]]` is load-bearing: the final segment has no trailing
		# newline, so a bare `read` would return non-zero and silently drop it —
		# failing OPEN (no STOP on a real force-push).
		while IFS= read -r seg || [[ -n "$seg" ]]; do
			[[ -z "${seg// /}" ]] && continue
			stripped=$(_godspeed_strip_prefixes "$seg")
			if printf '%s' "$stripped" | grep -Pq "$_GODSPEED_GATED_CMD_RE" 2>/dev/null; then
				printf 'command: %s\n' "$(printf '%s' "$stripped" | cut -c1-90)"
			fi
		done < <(printf '%s' "$cmds" | tr ';|&' '\n\n\n')
	fi

	# --- Write/Edit: prod-shaped desired-state paths ---
	local paths p
	paths=$(printf '%s' "$tools_json" |
		jq -r '.[]? | select(.name == "Write" or .name == "Edit" or .name == "NotebookEdit")
		       | (.input.file_path // "")' 2>/dev/null || true)

	if [[ -n "$paths" ]]; then
		while IFS= read -r p; do
			[[ -z "$p" ]] && continue
			if printf '%s' "$p" | grep -Pq "$_GODSPEED_GATED_PATH_RE" 2>/dev/null; then
				printf 'write: %s\n' "$p"
			fi
		done <<<"$paths"
	fi
}

# ---------------------------------------------------------------------------
# godspeed_decision <arm_status> <last_assistant_text> <session_id> [tools_json]
#
# Returns the decision given the arm status and context:
#   GO     continue autonomously
#   ASK <d> <bar_pct> <supplied_pct>    checkpoint — surface uncertainty
#   STOP   gated ACTION taken — surface for assessment (agent may continue)
#   NOOP   hook stands down
#
# STOP is a salience signal, NOT an enforcement gate. This hook runs after the
# turn's tools have already executed, so it can never prevent a first action;
# what it can do is stop the agent chaining onward without an explicit
# assessment. The agent retains the right to proceed — see the reason string in
# stop-action-bias-detector.sh. (#917)
# ---------------------------------------------------------------------------
godspeed_decision() {
	local arm_status="$1"
	# shellcheck disable=SC2034  # kept for signature stability; no longer gates
	local last_text="$2"
	local session_id="${3:-}"
	local tools_json="${4:-}"
	local N="${GODSPEED_WINDOW:-200}"
	local verified_pct="${GODSPEED_VERIFIED_CONFIDENCE:-80}"
	local unverified_pct="${GODSPEED_UNVERIFIED_CONFIDENCE:-40}"

	# Gate on ACTIONS taken this turn, never on turn text. Fires regardless of
	# mandate — a godspeed mandate speeds up autonomous work, it does not make
	# a prod-shaped action invisible. But STOP no longer commands a halt; the
	# agent is handed the judgment. (#917)
	local gated
	gated=$(godspeed_gated_actions "$tools_json")
	if [[ -n "$gated" ]]; then
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

	# Operator-facing side-effect kill-switch. When set, the decision logic is
	# still fully exercised (ASK still blocks); only the vox TTS and Discord post
	# are muted. Auto-suppressed under any CI signal (non-empty $CI) so no runner
	# needs the explicit export, plus an explicit GODSPEED_NOTIFY_DISABLED for
	# regression tests that drive the real hook — otherwise each notifying case
	# sprays a real announcement + Discord ping at BJ. (cc-workflow#883)
	#
	# NOTE: only ASK reaches here now. The gated-action path deliberately does
	# NOT notify — notifying on trigger makes the hook the escalator and spends
	# BJ's attention on every false positive, before the agent has assessed
	# anything. The agent escalates with its own tools. (#917)
	if [[ "${GODSPEED_NOTIFY_DISABLED:-0}" == "1" || -n "${CI:-}" ]]; then
		return 0
	fi

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

	# Only ASK notifies (see note above); the STOP branch was removed with #917.
	local vox_msg discord_msg
	vox_msg="Hey BJ, godspeed mandate checkpoint — the agent has a question. Check the terminal."
	discord_msg="⚠️ **Godspeed checkpoint** — mandate at d=${d}/N=${N}. Agent naming its uncertainty.${identity_suffix}"

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
		# Turn-scoped union — must match the hook's extraction exactly. (#917)
		TOOLS_JSON=$(
			[[ -f "$TRANSCRIPT_PATH" ]] && tail -n 600 "$TRANSCRIPT_PATH" 2>/dev/null |
				jq -cs '
					. as $all
					| ([ $all | to_entries[]
						 | select(.value.type == "user"
							 and (((.value.message.content // []) | map(select(.type == "text") | .text) | join("")) | length > 0))
						 | .key ] | last // -1) as $boundary
					| [ $all[($boundary + 1):][]
						| select(.type == "assistant")
						| (.message.content // [])[]
						| select(.type == "tool_use")
						| {name, input} ]
				' 2>/dev/null || echo "[]"
		)
		ARM=$(godspeed_status "$TRANSCRIPT_PATH")
		godspeed_decision "$ARM" "$LAST_TEXT" "$SESSION_ID" "$TOOLS_JSON"
		;;

	*)
		echo "Usage: $0 [--demo | --eval <transcript> | --decide]" >&2
		exit 1
		;;
	esac
fi
