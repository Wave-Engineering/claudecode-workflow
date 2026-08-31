#!/usr/bin/env bash
# pmr-bench-arm.sh — run ONE review protocol against ONE reconstructed changeset.
#
# WHY THIS EXISTS (#1195). pmr-timebubble.sh produces the condition; this is what
# runs a protocol against it. Together they are the instrument: arm A is the
# review prompt as it stood before #1194, arm B is the shape #1194 replaced it
# with, and the bench asks which one catches defects that history later proved
# were there.
#
# THE ONE VARIABLE IS THE PROMPT. Same model, same tools, same reconstructed
# working tree, same repository — only the prompt protocol differs between arms.
# Anything else that varies is a confound, and a confound in a two-arm bench is
# not noise, it is a wrong answer with a confidence interval attached.
#
# BASH IS DISALLOWED, AND THAT IS THE LOAD-BEARING DETAIL. `feature-dev:code-
# reviewer` has no Bash tool — its real list is Glob, Grep, LS, Read,
# NotebookRead, WebFetch, TodoWrite, WebSearch, KillShell, BashOutput. Arm A's
# prompt hands it a COMMAND ("review the files changed vs main"), which it
# cannot run; that impossibility is precisely the defect under measurement. Give
# the arm a Bash tool and it simply runs `git diff` itself, both arms converge,
# and the bench reports no difference between a working protocol and a broken
# one — the most expensive possible way to be wrong. So the tool set is
# constrained here, in the harness, not left to the prompt to request.
#
# WHAT IS NOT REPRODUCED, deliberately: the sub-agent PERSONA. `claude -p`
# cannot select a subagent type, so neither arm gets code-reviewer's system
# prompt. That is a constant across both arms, so it cannot bias the comparison
# — it costs absolute realism, not internal validity. Do not "fix" it for one
# arm only; that would convert a constant into the confound this file exists to
# avoid.
#
# SCORING IS NOT DONE HERE. This emits what the arm said. Whether the arm caught
# the defect is a separate, independently-graded question — a bench that let the
# thing under test grade itself would inherit its blind spots, which is the same
# reason szz-oracle.sh keeps a model out of the oracle entirely.
#
# MODEL CAPACITY IS A REAL CONSTRAINT, measured. The reviewing protocol reads
# whole touched files, not just the diff, so context grows far faster than the
# changeset size suggests. On a 14.6 KB / 4-file fixture:
#   opus   -> completed, ~31-35 turns, ~6.4 min
#   haiku  -> api_error_status 400, terminal_reason "prompt_too_long"
#
# COST PER PASS IS NOT STABLE, and a sweep must be budgeted on the high end.
# Two runs of the SAME fixture, same model, same prompt:
#   --allowedTools  $3.17  (3.0M cache-read tokens)
#   --tools         $9.01  (5.1M cache-read tokens)
# HYPOTHESIS, not a measurement: `--tools` ignores the user/project/local
# settings files, which changes the system-prompt prefix and may be costing a
# cache hit — i.e. the CORRECT instrument may be structurally dearer than the
# broken one. It could equally be ordinary cache-warmth variance between runs.
# Separate the two with paired repeat runs before committing a sweep budget;
# do not plan against $3.
# So haiku is not a cheaper way to run this bench; it is a different experiment
# that mostly measures which fixtures fit in 200k. Note that on that failure the
# envelope still reported `subtype: "success"` while `is_error` was true — which
# is exactly why the parser below checks `is_error` and does not trust `subtype`
# alone.
#
# Usage:
#   pmr-bench-arm.sh <A|B> --bubble DIR --culprit SHA --repo DIR --out DIR
#                          [--model NAME] [--timeout SEC]
# Exit: 0 arm ran and produced a review; 2 unusable input; 3 the arm produced
#       nothing parseable (NOT recorded as "no findings" — see below).
set -euo pipefail

die() {
	echo "pmr-bench-arm: $1" >&2
	exit "${2:-2}"
}

ARM="${1:-}"
shift || true

BUBBLE=""
CULPRIT=""
REPO=""
OUT=""
MODEL="${PMR_BENCH_MODEL:-opus}"
TIMEOUT=900

while [[ $# -gt 0 ]]; do
	case "$1" in
	--bubble)
		BUBBLE="${2:-}"
		[[ -n "$BUBBLE" ]] || die "--bubble needs a directory"
		shift 2
		;;
	--culprit)
		CULPRIT="${2:-}"
		[[ -n "$CULPRIT" ]] || die "--culprit needs a SHA"
		shift 2
		;;
	--repo)
		REPO="${2:-}"
		[[ -n "$REPO" ]] || die "--repo needs a directory"
		shift 2
		;;
	--out)
		OUT="${2:-}"
		[[ -n "$OUT" ]] || die "--out needs a directory"
		shift 2
		;;
	--model)
		MODEL="${2:-}"
		[[ -n "$MODEL" ]] || die "--model needs a name"
		shift 2
		;;
	--timeout)
		TIMEOUT="${2:-}"
		[[ "$TIMEOUT" =~ ^[0-9]+$ ]] || die "--timeout needs an integer"
		shift 2
		;;
	*)
		die "unknown argument: $1"
		;;
	esac
done

case "$ARM" in
A | B) ;;
*) die "usage: pmr-bench-arm.sh <A|B> --bubble DIR --culprit SHA --repo DIR --out DIR" ;;
esac

[[ -d "$BUBBLE" ]] || die "no such bubble: $BUBBLE"
[[ -d "$REPO" ]] || die "no such repo: $REPO"
[[ -n "$CULPRIT" ]] || die "--culprit is required"
mkdir -p "$OUT"

# Clear prior artifacts. `mkdir -p` does not, and a retry into the same out dir
# after a timeout is the obvious operational move -- which would otherwise leave
# the previous attempt's findings.txt (and possibly its `status OK` meta.tsv)
# sitting beside the new attempt's failure, reading as a successful run of the
# CURRENT one. Absence of meta.tsv must never be a legal state either; see
# fail_meta below.
rm -f "$OUT/meta.tsv" "$OUT/findings.txt" "$OUT/envelope.json" "$OUT/stderr.txt"
rm -rf "$OUT/shown"

# Every non-zero exit writes a FAILED record. A driver tabulating $OUT/*/meta.tsv
# must see a failed fixture as FAILED, not have it silently vanish from the
# denominator -- a shrinking denominator is how a bench flatters itself.
fail_meta() { # reason  rc
	printf 'arm\t%s\nculprit\t%s\nstatus\tFAILED\nreason\t%s\nrc\t%s\n' \
		"$ARM" "$CULPRIT" "$1" "$2" >"$OUT/meta.tsv"
}

# The bubble's HEAD *is* the culprit's parent — that is what pmr-timebubble
# builds — so the base for any diff is HEAD itself. Resolving it from the bubble
# rather than accepting it as an argument removes a way for a caller to pass a
# base that does not match the bubble it also passed.
BASE="$(git -C "$BUBBLE" rev-parse HEAD)" || die "cannot resolve bubble HEAD"

# Marker dir for precheck-review-scope.sh. MUST be outside the bubble: the
# script rejects a marker dir inside the tree under review, and it would
# otherwise show up as part of the changeset the arm is asked to review.
MARKER="$(mktemp -d -t pmr-bench-marker.XXXXXX)"
trap 'rm -rf "$MARKER"' EXIT

# Resolution ladder, same rungs and same reason as /precheck's Step 0: PATH
# covers a normal install, .claude/bin covers `install --local` (deliberately
# OFF PATH), scripts/ covers a cc-workflow checkout. A bare `command -v` probe
# reports "missing" in two of those three cases.
SCOPE=""
for cand in \
	"$(command -v precheck-review-scope.sh 2>/dev/null || true)" \
	"$REPO/.claude/bin/precheck-review-scope.sh" \
	"$REPO/scripts/precheck-review-scope.sh"; do
	[[ -n "$cand" && -x "$cand" ]] && {
		SCOPE="$cand"
		break
	}
done
[[ -n "$SCOPE" ]] || die "precheck-review-scope.sh not found on any rung (PATH, .claude/bin, scripts/)"

# ── Arm A — the protocol as it stood BEFORE #1194 ────────────────────────────
# Reproduced verbatim in shape, including the hardcoded `vs main`. In a bubble
# there is no `main`, which is exactly the class of breakage the bench is here
# to price: the prompt names a command the reviewer cannot run, against a ref
# that need not exist, and the failure surfaces as a confident "No findings".
# Do not "improve" this prompt. Its defects ARE the measurement.
arm_a_prompt() {
	cat <<PROMPT
Review all files changed on the current branch vs main in $BUBBLE.
Use confidence-based filtering — report only issues you are genuinely confident matter.
Categorize findings as: critical / important / minor.
Return a structured list; if none, say 'No findings'.
PROMPT
}

# ── Arm B — the #1194 shape: the parent gathers, the reviewer receives ───────
# Every section is substituted BEFORE dispatch. The reviewer is never handed a
# command, because it has no tool that could run one.
arm_b_prompt() {
	local gathered untracked n_lines paths section_untracked

	gathered="$("$SCOPE" gather "$BUBBLE" "$MARKER" "$BASE")" || {
		fail_meta "gather-failed" 3
		die "gather failed for $BUBBLE" 3
	}
	# gather prints `files <N> <path>…` or `empty 0 <path>`.
	read -r _verdict n_lines paths <<<"$gathered"

	# GIT_CONFIG_GLOBAL/SYSTEM neutralise the out-of-tree ignore sources for
	# this call. pmr-timebubble pins `core.excludesFile=/dev/null` on every call
	# that consults it, for a reason its header states plainly: an operator's
	# global gitignore otherwise decides whether an added file appears in the
	# untracked channel at all. `new-untracked` runs `ls-files --others
	# --exclude-standard` internally and takes no `-c`, so the pin has to arrive
	# through the environment.
	#
	# ONLY ARM B HAS AN UNTRACKED SECTION, so a silent loss here weakens the arm
	# under test, asymmetrically, and varies by whose machine ran the bench.
	# That is the wrong-measurement class this whole issue exists to eliminate,
	# which is why the cross-check below is fatal rather than a warning.
	untracked="$(GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null \
		"$SCOPE" new-untracked "$BUBBLE" "$MARKER")" || untracked=""

	# Cross-check against git's own pinned answer. The environment pin above
	# cannot reach a REPO-level core.excludesFile, and a future edit to the
	# scope script could narrow this channel without touching this file, so the
	# count is verified rather than trusted.
	local n_reported n_expected
	n_reported="$(printf '%s' "$untracked" | grep -cvE '^(UNRESOLVABLE|[[:space:]]*$)' || true)"
	n_expected="$(git -c core.excludesFile=/dev/null -C "$BUBBLE" \
		ls-files --others --exclude-standard | grep -c . || true)"
	if [[ "$n_reported" != "$n_expected" ]]; then
		fail_meta "untracked-channel-mismatch" 3
		die "untracked channel disagrees: prompt would carry $n_reported path(s), git sees $n_expected — refusing to dispatch a prompt that under-describes the changeset" 3
	fi
	if [[ -n "$untracked" ]]; then
		# Read rejects relative paths, so every line that is a PATH is
		# prefixed. A line beginning UNRESOLVABLE is a warning, not a file,
		# and is passed through verbatim.
		section_untracked="$(while IFS= read -r line; do
			[[ -z "$line" ]] && continue
			if [[ "$line" == UNRESOLVABLE* ]]; then
				printf '%s\n' "$line"
			else
				printf '%s/%s\n' "$BUBBLE" "$line"
			fi
		done <<<"$untracked")"
	else
		section_untracked="(none — every changed path is tracked and appears in the diff above)"
	fi

	# An empty diff section reads as the affirmative "nothing changed here", so
	# it is never left bare. It is legitimate only for an untracked-only
	# changeset, and then it says so.
	local diff_section
	if [[ "$_verdict" == "empty" ]]; then
		diff_section="The tracked diff is genuinely EMPTY (0 bytes). This changeset is untracked-only:
it consists entirely of new files that have not been git added, and \`git diff\`
cannot report untracked paths. The entire changeset is in the next section."
	else
		diff_section="$paths"
	fi

	cat <<PROMPT
Review this changeset in $BUBBLE.

### Diff — $n_lines lines total, read ALL of these files before reviewing
$diff_section

### Untracked files — NOT in the diff above, read each IN FULL
$section_untracked

The diff is given so you do not have to reconstruct it. You still have
Read/Grep/Glob — use them freely to pull in whatever context you need to judge
these changes: callers, callees, tests, sibling implementations, project rules.
Do not restrict yourself to the lines above.

Use confidence-based filtering — report only issues you are genuinely confident matter.
Categorize findings as: critical / important / minor.
Return a structured list; if none, say 'No findings'.
PROMPT
}

case "$ARM" in
A) PROMPT="$(arm_a_prompt)" ;;
B) PROMPT="$(arm_b_prompt)" ;;
esac

printf '%s' "$PROMPT" >"$OUT/prompt.txt"

# Preserve exactly what the arm was shown. $MARKER is a temp dir this script
# deletes on exit, so without this the run record names files that no longer
# exist -- and "what did the arm actually see" is the first question anyone asks
# of a surprising score. A bench whose evidence evaporates cannot be audited.
if [[ -d "$MARKER/diff" ]]; then
	mkdir -p "$OUT/shown"
	cp -r "$MARKER/diff/." "$OUT/shown/" 2>/dev/null || true
fi

# --tools, NOT --allowedTools. This distinction is the whole invariant.
#
# `--allowedTools` is a PERMISSION list -- "run these without prompting". It is
# additive to the settings files and removes nothing. The first version of this
# script used it and was silently inert. Measured, from this repo's cwd:
#
#   --allowedTools Glob Grep LS Read NotebookRead TodoWrite
#     -> "Run: echo TOOLTEST_MARKER_12345"  ->  TOOLTEST_MARKER_12345
#   --tools        Glob Grep LS Read NotebookRead TodoWrite
#     -> same prompt                        ->  NOBASH
#
# `--tools` restricts AVAILABILITY and ignores the user/project/local settings
# files, which matters here because ~/.claude/settings.json sets
# `defaultMode: bypassPermissions` and allows `Bash(*)`. Under --allowedTools an
# arm therefore kept Bash, and arm A could simply run `git diff` to recover the
# changeset its prompt failed to hand it -- both arms converge and the bench
# reports "no difference" between a working protocol and a broken one. That is
# the header's own named worst case, and it arrives looking like a clean result.
# A tool that is not in the set cannot be re-enabled by a permission mode, so
# --tools alone closes it; verified in BOTH directions, because a restriction
# that also blocked Read would be just as broken and just as quiet.
#
# The list is code-reviewer's real one (Glob, Grep, LS, Read, NotebookRead,
# WebFetch, TodoWrite, WebSearch, KillShell, BashOutput) minus Bash, minus the
# two Bash-adjacent tools (KillShell, BashOutput), minus the two network tools
# (WebFetch, WebSearch). Dropping the network tools costs a little realism and
# is held CONSTANT across both arms, so it cannot bias the comparison -- but it
# is a deviation, and in this repo the comment is the spec.
TOOLS=(Glob Grep LS Read NotebookRead TodoWrite)

# BOTH directories, and the second one is not optional. `gather` writes the diff
# into $MARKER, so an arm granted only $BUBBLE is handed a path it has no
# permission to Read. It does not error usefully — it reports on whatever it
# could reach, which for arm B is nothing, and returns a confident review of an
# empty changeset. That is the bench's own failure mode reproduced inside the
# bench: a broken instrument and a genuine clean review are the same string.
# Caught on the first live run, where the arm was told to read
# /tmp/pmr-bench-marker.*/diff/full.diff with only the bubble on its allowlist.
started="$(date +%s)"
set +e
timeout "$TIMEOUT" claude -p "$PROMPT" \
	--model "$MODEL" \
	--output-format json \
	--tools "${TOOLS[@]}" \
	--add-dir "$BUBBLE" "$MARKER" \
	>"$OUT/envelope.json" 2>"$OUT/stderr.txt"
rc=$?
set -e
ended="$(date +%s)"

# A timeout, a crash, or an empty envelope is NOT "no findings". Those are the
# same string to a naive parser and opposite facts to the bench — the exact
# confusion that makes an unmeasured prompt seam dangerous in the first place.
# Refuse to emit a scoreable record for a run that did not produce a review.
if ((rc != 0)) || [[ ! -s "$OUT/envelope.json" ]]; then
	echo "pmr-bench-arm: arm $ARM produced no usable output for $CULPRIT (rc=$rc)" >&2
	[[ -s "$OUT/stderr.txt" ]] && tail -5 "$OUT/stderr.txt" >&2
	fail_meta "no-output" "$rc"
	exit 3
fi

python3 - "$OUT" "$ARM" "$CULPRIT" "$BASE" "$MODEL" "$started" "$ended" <<'PY'
import json, sys, pathlib

out, arm, culprit, base, model, started, ended = sys.argv[1:8]
out = pathlib.Path(out)


def unusable(reason):
    """Exit 3 with a FAILED record.

    Every way of not getting a review must land here. The header declares the
    contract as 0 | 2 | 3, and a traceback exiting 1 with no meta.tsv would put
    a driver keying on rc==3 ("unusable, skip") into its unknown-crash path for
    the textbook case of an unusable run.
    """
    print(f"pmr-bench-arm: {reason}", file=sys.stderr)
    (out / "meta.tsv").write_text(
        f"arm\t{arm}\nculprit\t{culprit}\nstatus\tFAILED\nreason\t{reason}\nrc\t3\n"
    )
    sys.exit(3)


try:
    d = json.loads((out / "envelope.json").read_text())
except ValueError as exc:
    unusable(f"envelope is not valid JSON ({exc})")
if not isinstance(d, dict):
    unusable(f"envelope is valid JSON but not an object ({type(d).__name__})")

# The envelope carries its own success signal. Ignoring it leaves the same hole
# the rc/empty guard closes one layer up: a run that exits 0, reports
# is_error, and still has result text would otherwise be written out as a
# scoreable review with status OK.
if d.get("is_error") or (d.get("subtype") or "success") != "success":
    unusable(f"envelope reports failure (is_error={d.get('is_error')}, subtype={d.get('subtype')})")

text = d.get("result", "") or ""
if not text.strip():
    unusable("envelope carried no result text")

(out / "findings.txt").write_text(text)

usage = d.get("usage", {}) or {}
rows = [
    ("arm", arm),
    ("culprit", culprit),
    ("base", base),
    ("model", model),
    ("status", "OK"),
    ("duration_sec", int(ended) - int(started)),
    ("cost_usd", d.get("total_cost_usd", d.get("cost_usd")) or 0),
    ("input_tokens", usage.get("input_tokens", "")),
    ("output_tokens", usage.get("output_tokens", "")),
    ("cache_read_tokens", usage.get("cache_read_input_tokens", "")),
    ("num_turns", d.get("num_turns", "")),
    ("findings_chars", len(text)),
    # ANCHORED, not a substring search. A bare `"no findings" in text` also
    # fires on "no findings of critical severity", "no findings in the
    # untracked section", or a review quoting its own instructions back -- and
    # this column WILL get tabulated, so a loose match becomes an over-reported
    # rate. The verdict is only a verdict when it is the whole review.
    #
    # Recorded, never interpreted here: "No findings" is a legitimate answer and
    # a scoring input, and whether it was CORRECT is the judge's question.
    ("said_no_findings", "yes" if text.strip().strip(".'\"").lower() == "no findings" else "no"),
]
(out / "meta.tsv").write_text("".join(f"{k}\t{v}\n" for k, v in rows))
print("".join(f"{k}\t{v}\n" for k, v in rows), end="")
PY
