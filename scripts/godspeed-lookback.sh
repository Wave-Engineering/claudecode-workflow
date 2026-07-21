#!/usr/bin/env bash
# godspeed-lookback.sh — Godspeed mandate lookback utility.
#
# Scans a Claude Code JSONL transcript for the most-recent ARMING `godspeed`
# turn (sentence-initial, or slash-prefixed after a space; not a question, a
# quoted mention, a file path, or a machine-generated turn — see `arms` in the
# jq prelude) and the most-recent `HALT!` in user-role turns, and emits the arm
# status. Sourced by both Stop hooks; also runnable standalone with --demo or
# --eval.
#
# Output of godspeed_status():
#   ARMED <d>     godspeed found d user turns ago; HALT! not newer
#   HALTED        HALT! is newer than godspeed (or godspeed never appeared)
#   UNARMED       no godspeed within the last N user turns
#   UNKNOWN       the scan could not be trusted. Either it could not run at all
#                 (unreadable content shape, or every line in the window
#                 unparseable), or it ran DEGRADED — recovered by dropping torn
#                 lines — and would otherwise have returned ARMED while the
#                 dropped bytes contained a `HALT!`.
#                 NOT the same as UNARMED: callers stand down on both, but
#                 UNKNOWN is reported on stderr instead of passing as all-clear.
#                 A single torn line does NOT blind the window: it is dropped,
#                 the drop is announced, and the scan continues.
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
# Shared jq prelude — ONE implementation of content extraction and arming form.
#
# Injected into every jq program in this file and in the two Stop hooks that
# source it. Deliberately a single string rather than copies: #919 established
# that two module instances of one detector is how a fix reaches half its call
# sites, and these three scripts had ten independent copies of the same
# extraction between them. (#920)
#
# `txt` is the fix for #920. `.message.content` is a plain STRING on a large
# share of user messages — measured 20,174 string / 119,269 array across 3821
# transcripts (1.8 GB, one workstation). jq aborts on the FIRST string it meets,
# so the old array-only `map(...)` did not degrade gracefully; it killed the
# whole scan. 3651 of 3821 transcripts (95.6%) carry at least one, and 261 of
# 303 main-session transcripts (86.1%) do — the failure was total per file, not
# proportional.
#
# An unrecognised shape raises rather than defaulting. A detector that cannot
# read its input must not be able to report "nothing found". (#920)
# ---------------------------------------------------------------------------
# shellcheck disable=SC2016  # jq program — `$`-refs are jq vars, must NOT expand in bash
_GODSPEED_JQ_PRELUDE='
  def txt:
    (.message.content // [])
    | if type == "string" then .
      elif type == "array" then (map(select(.type == "text") | .text) | join(" "))
      else error("godspeed: unhandled .message.content type: \(type)")
      end;

  # Claude Code writes a number of MACHINE-generated turns with role=="user".
  # The Stop hooks own block text is one of them — that is the #921 inversion,
  # the brake pressing the accelerator — but a corpus sweep showed it is a whole
  # family, not one case.
  #
  # Deliberately NOT in this list: `<system-reminder>`. That one is APPENDED to
  # genuine human turns rather than constituting the turn, so excluding on it
  # would silently drop real instructions — including an arming turn that happens
  # to be the first message of a session. Every marker below is the WHOLE turn;
  # that is the property that makes exclusion safe.
  #
  # NONE of these are ^-anchored, deliberately. jq compiles Oniguruma with
  # ONIG_OPTION_SINGLELINE, so `^` is a STRING anchor (\A), not a line anchor —
  # verified with jq -n on the two-line string a\nb: test("^b") is false, and the
  # "m" flag does not change it. An anchored marker would therefore match only at
  # offset 0 of the JOINED text, and `txt` joins an array turns text blocks with
  # a space, so any preceding block would hide the marker. Bare substrings are
  # distinctive enough and cannot be defeated by a leading block. (#921)
  def _injected_envelope_re:
    "\\[godspeed-(GATE|checkpoint|STOP)\\]"
    + "|<task-notification>"
    + "|<local-command-(stdout|stderr)>"
    + "|Base directory for this skill:"
    + "|Caveat: The messages below were generated"
    + "|This session is being continued from a previous conversation"
    + "|Stop hook feedback:";

  # ARMING/HALTING exclusion. Includes slash-command envelopes: a turn that is
  # the expansion of `/precheck` must not arm.
  def is_machine_turn:
    txt | test(_injected_envelope_re + "|<command-(message|name|args)>");

  # DECAY COUNTING is a DIFFERENT question, and for one marker the answer
  # differs. `<command-name>/precheck</command-name>` is machine-FORMATTED but
  # BJ typed it — it is a real interaction, and the mandate is supposed to decay
  # across real interactions. Excluding it from the count would make `d` rise
  # slower than the model intends, which lowers `bar_pct`, which returns GO where
  # the model meant ASK. In this fleet /precheck, /scp and /scpmmr are frequent,
  # so that is a measurable widening of autonomy — the wrong direction to get
  # wrong by accident.
  #
  # So: a command turn does NOT arm, but it DOES count. One predicate cannot
  # answer both questions, which is why there are two. (#921)
  def counts_as_human_turn:
    (txt | test(_injected_envelope_re)) | not;

  # Arming requires a FORM, not a substring. The form was DERIVED FROM THE REAL
  # CORPUS, not from a description of it — an earlier draft of this fix used
  # "the turn IS the token or leads with it", taken from the issue text, and it
  # rejected 3 of the 4 genuine arming turns on this workstation:
  #
  #   godspeed                                                        <- bare
  #   agreed. continuous, phas-boundary reporting.  godspeed, my friend
  #   thank you. please be as autonomous as you can safely be.  /godspeed
  #   roll them in. im working with lots of agents, so /godspeed
  #
  # The real idiom is a TRAILING token, usually slash-prefixed, appended to a
  # sentence of instruction. The true negatives are interrogative or quoted:
  #
  #   are you in godspeed mode?
  #   how do we turn off `/godspeed`?
  #   agentc can merge w/o user approval in wavemachine, lazyriver, and godspeed
  #
  # So the discriminator is NOT position-in-message. It is: the token is either
  # SLASH-PREFIXED (the explicit command form) or SENTENCE-INITIAL, and is not
  # inside a question or a quotation.
  #
  # THE SLASH MUST FOLLOW WHITESPACE OR OPEN THE STRING. This is the single
  # highest-value clause in the definition and it was missing from the first
  # draft, which matched `/godspeed` anywhere. Sweeping 3772 real transcripts for
  # every user turn mentioning the token found 40, of which the draft armed 17
  # and only 4 were genuine — a 76% false-positive rate on a control that GRANTS
  # AUTONOMY. The dominant cause is almost too neat — the file path in this very
  # repo,
  #
  #     scripts/godspeed-lookback.sh
  #
  # contains the literal substring `/godspeed`. So merely NAMING the detector
  # armed it. A code-review prompt, a subagent task-notification, a `git status`
  # paste and a compaction summary all armed the mandate in the sweep. Requiring
  # whitespace before the slash removes that entire family, because a path has a
  # word character there and a typed command has a space.
  #
  # `\n\s*` was also dropped as an arming form. It made ANY line beginning with
  # the token arm, so pasting a quoted example — routine in this repo — armed the
  # mandate. Nothing was lost: all four corpus true-positives arm via the slash
  # form or via `[.!?]\s+`, and the bare-token turn arms via `^`. A clause that
  # no genuine case needs, and that fires on quotation, is not a discriminator.
  #
  # `^` here is a STRING anchor, not a line anchor — jq compiles Oniguruma with
  # ONIG_OPTION_SINGLELINE. Verified rather than assumed:
  #
  #     on the two-line string  a\nb :
  #         test("^b")  ->  false      (a line anchor would give true)
  #         test("^a")  ->  true
  #
  # An earlier revision of this comment asserted the opposite. It mattered: if
  # `^` were a line anchor it would already do everything `\n\s*` did, and
  # dropping that clause would have bought nothing. It is string-anchored, so
  # the removal is what actually closed the pasted-example hole.
  #
  # Belt and braces with is_machine_turn — this failure mode inverts a safety
  # control, so it gets two independent guards. (#921)
  def arms:
    (is_machine_turn | not)
    # Quoted mentions are TALKING ABOUT the command, not issuing it. The corpus
    # carries the token in backticks, in straight double quotes and in smart
    # quotes, always in a sentence about the feature rather than an instruction.
    #
    # The straight single quote is written as the escape \u0027, and the prose
    # prelude avoids apostrophes entirely, because the whole block is a
    # SINGLE-QUOTED shell string: one literal apostrophe — even inside a comment
    # — closes it, and the jq body then reaches bash as commands. It fails
    # loudly, but it fails at source time in a file both Stop hooks source.
    and ((txt | test("[`\"\u0027\u2018\u2019\u201c\u201d]/?godspeed")) | not)
    and ((txt | test("[^.!?\\n]*\\bgodspeed\\b[^.!?\\n]*\\?")) | not)
    and (txt | test("(^|[.!?]\\s+)godspeed\\b|(^|\\s)/godspeed\\b"));

  # HALT! stays a liberal substring match — over-halting is the safe direction —
  # but a hook echo still must not disarm a live mandate. (#921)
  #
  # KNOWN LIMIT: a user turn that QUOTES a sentinel while also saying HALT! is
  # filtered out of the turn list before this runs, so that HALT is not seen.
  # Accepted rather than fixed: it requires BJ to type the literal sentinel, and
  # halting without quoting one works normally. Fixing it needs the arming and
  # halting scans to run over different lists, which breaks the shared index
  # arithmetic that gs_d/halt_d compare on.
  def halts:
    (is_machine_turn | not) and (txt | test("HALT!"));
'

# ---------------------------------------------------------------------------
# _godspeed_jq_scan <scan_lines> <transcript_path> <jq_program> [jq_flags...]
#
# The ONE place a jq program is run over a transcript. All three public
# extractors go through it, so the crash taxonomy is defined once.
#
# Two failure classes reach jq, and they need opposite treatments:
#
#   TYPE failure  — `.message.content` in a shape `txt` cannot read. The prelude
#                   raises deliberately (#920); nothing is recoverable, so this
#                   propagates and the caller reports its own loud default.
#   PARSE failure — a torn write: two JSON objects concatenated by a racing
#                   append (`...LlwqhUPdY6Dphw{"parentUuid":...`), seen on 5 of
#                   3821 transcripts. `jq -s` slurps, so ONE torn line anywhere
#                   in the window aborts the whole scan.
#
# A torn line is durable — it stays in the file — so treating a parse failure as
# fatal would leave that session's mandate permanently unarmable and its #917
# gate STOPping every turn until the bad line aged out of the window. Safe, but
# permanently degraded. So: retry line-wise, DROP the unparseable lines, and say
# so on stderr. Dropping a torn record costs one turn of context; blinding the
# window costs the whole scan.
#
# The retry is also how the two classes are told apart without parsing jq's
# message: if the lenient pass succeeds it was a parse failure (now recovered);
# if it fails the same way it was a type failure (unrecoverable). Healthy
# transcripts never reach the retry and pay nothing for it.
#
# CONTRACT — the caller distinguishes three outcomes by EXIT CODE, and the
# helper writes its own diagnostics to stderr:
#
#   0  clean       — the strict pass succeeded, nothing dropped.
#   2  DEGRADED    — recovered by dropping N unparseable lines. Output is
#                    well-formed but INCOMPLETE. Callers whose answer is a
#                    safety decision must treat this as failure.
#   1  unreadable  — nothing usable; caller reports its own loud default.
#
# The exit code carries this, NOT a global. An earlier draft used
# `_GODSPEED_SCAN_ERR` and it was silently dead: every caller invokes this via
# `out=$(_godspeed_jq_scan ...)`, which is a COMMAND SUBSTITUTION and therefore
# a subshell, so assignments never reached the parent and every "loud" failure
# printed an empty reason. That is the #920 defect reproduced inside the fix for
# #920 — a crash that reports nothing actionable. Exit codes cross a subshell;
# variables do not.
#
# Why DEGRADED is distinct from clean, and why it is not merely cosmetic: a torn
# write is a RACING APPEND, so the torn line sits at the write head — precisely
# where the current turn's records live. Dropping it and returning 0 would let
# `godspeed_turn_tools` emit a well-formed but incomplete tool list, and "I
# dropped the evidence" would render as "no gated action found". Same signature
# as the #917 fail-open. `godspeed_status` can accept the drop (its `d` shifts
# by one, in the safe direction); the action gate cannot.
# ---------------------------------------------------------------------------
_godspeed_jq_scan() {
	local scan_lines="$1" transcript_path="$2" program="$3"
	shift 3

	local out rc
	out=$(
		tail -n "$scan_lines" "$transcript_path" 2>/dev/null |
			jq "$@" "$_GODSPEED_JQ_PRELUDE$program" 2>&1
	)
	rc=$?
	if [[ $rc -eq 0 ]]; then
		printf '%s' "$out"
		return 0
	fi

	local strict_err="$out"

	# `fromjson?` yields nothing on an unparseable line — no `// empty`, which
	# would also swallow a legitimately falsy record.
	local recovered total kept dropped out2 rc2
	recovered=$(
		tail -n "$scan_lines" "$transcript_path" 2>/dev/null |
			jq -Rc 'fromjson?' 2>/dev/null
	)
	total=$(tail -n "$scan_lines" "$transcript_path" 2>/dev/null | grep -c '[^[:space:]]' || true)
	kept=$(printf '%s\n' "$recovered" | grep -c '[^[:space:]]' || true)
	dropped=$((total - kept))

	# Nothing survived. This is a total loss, not a recovery — and it must not be
	# allowed to look like one: an empty stream slurps to `[]`, the program runs
	# cleanly over it, and `godspeed_status` would return a confident UNARMED
	# with rc=0 for a window it could not read at all.
	if [[ $kept -eq 0 ]]; then
		printf 'godspeed: scan window unreadable — %s of %s line(s) unparseable: %s\n' \
			"$dropped" "$total" "${strict_err//$'\n'/ }" >&2
		return 1
	fi

	out2=$(printf '%s\n' "$recovered" | jq "$@" "$_GODSPEED_JQ_PRELUDE$program" 2>&1)
	rc2=$?
	if [[ $rc2 -eq 0 ]]; then
		printf 'godspeed: DEGRADED — dropped %s unparseable line(s) of %s (torn write); result is incomplete\n' \
			"$dropped" "$total" >&2
		printf '%s' "$out2"
		return 2
	fi

	# Report the RETRY's diagnostic, not the strict pass's. When a transcript
	# carries both a torn line and an unreadable content shape, the strict error
	# names the torn write while the durable, actionable problem is the shape.
	printf 'godspeed: transcript scan failed: %s\n' \
		"${out2:-$strict_err}" | tr '\n' ' ' >&2
	printf '\n' >&2
	return 1
}

# ---------------------------------------------------------------------------
# godspeed_status <transcript_path>
#
# Scans the last GODSPEED_WINDOW user turns. Only user-role turns count —
# assistant echoes of "godspeed" do not arm the mandate.
#
# Returns UNKNOWN when the scan could not run. UNKNOWN is NOT UNARMED: the old
# `2>/dev/null || echo "UNARMED"` made a crashed detector byte-identical to a
# healthy one reporting all-clear, which is why this stayed broken through three
# releases. Callers treat UNKNOWN as "no mandate" (the safe direction) but the
# failure is now visible on stderr instead of silent. (#920)
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

	local out rc
	# shellcheck disable=SC2016  # jq program — `$N`/`$rev` are jq vars, must not expand in bash
	out=$(_godspeed_jq_scan "$scan_lines" "$transcript_path" '
      # Collect user turns that carry actual human text — exclude tool-result
      # wrapper entries (type=="user" but content is tool_result blocks with no
      # text).  Without this filter every tool result inflates d by 1, causing
      # the mandate to age out far faster than intended.
      #
      # Injected envelopes are excluded here too: a machine-generated turn is not
      # a human interaction, and counting it would decay the mandate for reasons
      # BJ had no part in.
      #
      # `counts_as_human_turn`, NOT `is_machine_turn` — the two differ on slash
      # commands, which BJ types and which therefore must still decay the
      # mandate even though they must not arm it. (#921)
      [.[] | select(
        .type == "user" and
        ((txt | length) > 0) and
        counts_as_human_turn
      )] as $user_turns |

      # Reverse so index 0 = most-recent user turn.
      ($user_turns | reverse | to_entries) as $rev |

      # Most-recent user turn that ARMS (see `arms`), or -1 if none.
      ($rev | map(select(.value | arms)) | first | .key // -1) as $gs_d |

      # Most-recent user turn carrying HALT!, or -1.
      ($rev | map(select(.value | halts)) | first | .key // -1) as $halt_d |

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
    ' -rs --argjson N "$N")
	rc=$?

	if [[ $rc -eq 1 ]]; then
		echo "UNKNOWN"
		return 0
	fi

	# rc 2 (DEGRADED) is accepted CONDITIONALLY, and only the ARMED verdict is
	# conditional.
	#
	# An earlier revision accepted DEGRADED outright, reasoning that a dropped
	# line only shifts `d` by one, in the safe direction. That reasoning is
	# incomplete by this file's own argument: a torn write is a racing APPEND, so
	# the dropped line sits at the write head — exactly where a just-typed `HALT!`
	# lives. Dropping it returns ARMED where HALTED is correct, and ARMED also
	# makes precheck-asking-detector.sh stand down. A fail-open on the one input
	# whose entire purpose is to revoke autonomy.
	#
	# But withholding ARMED on EVERY degraded scan overshoots in the other
	# direction: it re-blinds the window that the recovery exists to save, which
	# is the explicit thing #920 says must not happen.
	#
	# So ask the precise question instead of assuming the bad case: could the
	# dropped bytes have carried a HALT! at all? The unparseable lines are
	# recoverable in one jq pass, and `HALT!` is a literal. If it is not in them,
	# the drop provably cannot have hidden a halt and ARMED stands. If it is, the
	# verdict is withheld. UNARMED and HALTED both stand callers down, so neither
	# can be made wrong in the dangerous direction by a drop and both pass
	# through untouched — only the verdict that GRANTS latitude has to be
	# re-earned. (#920)
	if [[ $rc -eq 2 && "$out" == "ARMED "* ]]; then
		local dropped_text
		dropped_text=$(
			tail -n "$scan_lines" "$transcript_path" 2>/dev/null |
				jq -Rr 'select((try (fromjson|true) catch false) | not)' 2>/dev/null
		)
		if [[ "$dropped_text" == *'HALT!'* ]]; then
			printf 'godspeed: degraded scan withheld an ARMED verdict — a dropped line carried HALT!\n' >&2
			echo "UNKNOWN"
			return 0
		fi
	fi

	printf '%s\n' "$out"
}

# ---------------------------------------------------------------------------
# godspeed_turn_tools <transcript_path>
#
# Emits the CURRENT TURN's tool_use union as compact JSON — the action gate's
# substrate (#917). Previously this jq lived in two places (here via --decide,
# and in stop-action-bias-detector.sh) with a comment instructing future readers
# to keep them "exactly" in sync. #919 established what that costs: one detector
# with two instances is how a fix reaches half its call sites. One
# implementation, two callers.
#
# Emits the literal EXTRACTION_FAILED on error — NEVER "[]". An extraction that
# could not run is not evidence of no gated action, and `2>/dev/null || echo
# "[]"` is precisely how the #917 gate shipped inert. Callers fail CLOSED on it.
# (#920)
# ---------------------------------------------------------------------------
godspeed_turn_tools() {
	local transcript_path="$1"

	[[ -f "$transcript_path" ]] || {
		echo "[]"
		return 0
	}

	local out rc
	# shellcheck disable=SC2016  # jq program — `$all`/`$boundary` are jq vars, must not expand in bash
	out=$(_godspeed_jq_scan 600 "$transcript_path" '
        . as $all
        | ([ $all | to_entries[]
             | select(.value.type == "user" and ((.value | txt | length) > 0))
             | .key ] | last // -1) as $boundary
        | [ $all[($boundary + 1):][]
            | select(.type == "assistant" and (.message.role // "") == "assistant")
            | (.message.content // [])
            | if type == "array" then .[] else empty end
            | select(.type == "tool_use")
            | {name, input} ]
      ' -cs)
	rc=$?

	# ANY non-clean result fails CLOSED — including rc 2 (DEGRADED). A torn write
	# is a racing append, so the dropped line sits at the write head, which is
	# exactly where THIS turn's assistant records are. A well-formed but
	# incomplete tool list would render "I dropped the evidence" as "no gated
	# action found" — the #917 fail-open, rebuilt inside its own fix. An
	# extraction that lost data is not evidence of no gated action. (#920)
	#
	# THE COST, stated rather than left implicit: a torn line is durable and this
	# window is 600 lines (~20-40 turns), so this returns EXTRACTION_FAILED —
	# and the gate therefore STOPs — on every turn until it ages out. That is the
	# same "permanently degraded" shape godspeed_status refuses to pay, and the
	# difference is deliberate: there, the degraded state withholds a gate; here,
	# it applies one. Paying it in the direction of MORE gating is acceptable.
	#
	# It could be made cheaper by failing closed only when a line was dropped
	# AFTER $boundary — the write-head argument only justifies distrusting drops
	# inside the current turn. Not done here: it needs the helper to report WHERE
	# it dropped, which is a wider contract change than this fix warrants.
	if [[ $rc -ne 0 ]]; then
		echo "EXTRACTION_FAILED"
		return 0
	fi

	[[ -z "$out" || "$out" == "null" ]] && out="[]"
	printf '%s\n' "$out"
}

# ---------------------------------------------------------------------------
# godspeed_last_assistant_text <transcript_path>
#
# Emits the last assistant turn's text. One implementation, three callers
# (--decide and both Stop hooks) — they previously carried three copies, each
# ending in `2>/dev/null`, which routed the prelude's own error() into the void.
# That defeated the point of raising on an unhandled shape: a torn write or an
# unknown content type produced an empty string, and precheck-asking-detector.sh
# exits 0 on empty — inert, with nothing on stderr, BEFORE it ever reaches
# godspeed_status and its UNKNOWN diagnostic.
#
# Emits empty on failure (this text is advisory, not a gate — unlike
# godspeed_turn_tools, which must fail closed) but WARNS on stderr, so a
# degraded hook is observable rather than silent. (#920)
# ---------------------------------------------------------------------------
godspeed_last_assistant_text() {
	local transcript_path="$1"

	[[ -f "$transcript_path" ]] || return 0

	local out rc
	out=$(_godspeed_jq_scan 200 "$transcript_path" '
        [.[] | select(.type == "assistant" and (.message.role // "") == "assistant")]
        | last
        | txt
      ' -rs)
	rc=$?

	# rc 2 (DEGRADED) is accepted: this text is advisory input to the mandate
	# model, never a gate, and the helper has already warned. Only a total loss
	# yields empty. (#920)
	if [[ $rc -eq 1 ]]; then
		return 0
	fi

	printf '%s\n' "$out"
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

	# The caller could not read the turn. Name it rather than returning empty —
	# "no gated actions found" and "I could not look" must not render the same in
	# the block reason. godspeed_decision has already forced STOP. (#920)
	if [[ "$tools_json" == "EXTRACTION_FAILED" ]]; then
		printf 'extraction failed: turn could not be read — treated as gated (fail-closed)\n'
		return 0
	fi

	[[ -z "$tools_json" || "$tools_json" == "null" || "$tools_json" == "[]" ]] && return 0

	# These two remain fail-OPEN by design: making a missing jq/PCRE stop every
	# turn fleet-wide is a behaviour change with a blast radius that needs its
	# own decision, not a drive-by. But they must not be SILENT — an inert gate
	# that says nothing is the exact shape of the three defects above. Tracked
	# separately. (#920)
	command -v jq &>/dev/null || {
		printf 'godspeed: jq unavailable — action gate INERT this turn\n' >&2
		return 0
	}
	_godspeed_require_pcre || {
		printf 'godspeed: PCRE unavailable — action gate INERT this turn\n' >&2
		return 0
	}

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
		done < <(printf '%s' "$cmds" | tr ';|&' '\n')
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

	# The turn could not be read. FAIL CLOSED — an extraction that crashed is not
	# evidence of no gated action. This is the fail-open that shipped in v7.1.0:
	# the jq aborted on string content, `|| echo "[]"` swallowed it, and the gate
	# reported "nothing found" fleet-wide. (#920)
	if [[ "$tools_json" == "EXTRACTION_FAILED" ]]; then
		echo "STOP"
		return 0
	fi

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
	#
	# WHITELIST, not blacklist. Only a well-formed "ARMED <d>" proceeds to the
	# mandate path; everything else — UNARMED, HALTED, UNKNOWN, and any string
	# this function does not recognise — stands down. Enumerating the non-armed
	# states instead would mean an unrecognised status GRANTS autonomy, which is
	# the wrong default for a function whose contract is "an unreadable
	# transcript must never grant autonomy". That is not hypothetical: if jq ever
	# exits 0 while writing to stderr, godspeed_status's 2>&1 capture puts the
	# stderr text in the status, and a blacklist would fall straight through it
	# into the ARMED branch with a garbage d.
	#
	# Note the direction differs from the gated-action check above — there, an
	# extraction that cannot run is not evidence of no gated action and must fail
	# CLOSED. Same crash, opposite safe direction, because one grants latitude
	# and the other withholds it. (#920)
	case "$arm_status" in
	"ARMED "[0-9]*) ;; # fall through to the mandate path below
	*)
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
# Notifies BJ via vox + Discord. Best-effort; never fails.
#
# $1 (kind) is accepted for call-site signature stability but no longer read:
# only ASK reaches here now, since the gated-action path deliberately does NOT
# notify (#917). Binding it to a local would be a dead assignment — see the
# NOTE in the body — so the positional is documented and left unread rather than
# stored. (#948)
# ---------------------------------------------------------------------------
_godspeed_notify() {
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
		LAST_TEXT=$(godspeed_last_assistant_text "$TRANSCRIPT_PATH")
		# Turn-scoped union — ONE implementation, shared with the Stop hook. (#917, #920)
		TOOLS_JSON=$(godspeed_turn_tools "$TRANSCRIPT_PATH")
		ARM=$(godspeed_status "$TRANSCRIPT_PATH")
		godspeed_decision "$ARM" "$LAST_TEXT" "$SESSION_ID" "$TOOLS_JSON"
		;;

	*)
		echo "Usage: $0 [--demo | --eval <transcript> | --decide]" >&2
		exit 1
		;;
	esac
fi
