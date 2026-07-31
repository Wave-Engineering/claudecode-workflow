#!/usr/bin/env bash
# assert-only-expected-deps-missing.sh — tighten the oakandwave-workflow image's
# check-deps tolerance (#1016).
#
# The image build tolerates check-deps' missing-dependency advisory because a few
# items are legitimately absent at BUILD time and only materialize at runtime:
#   - the discord bot token — never baked (R-12), mounted read-only at runtime;
#   - the wtf-server PostToolUse hook — installed into the user's home at runtime.
# The old tolerance grepped only the SUMMARY sentinel ("required
# dependency/dependencies missing"), which fires on ANY missing count — it could
# not distinguish those expected gaps from a real regression (e.g. gh / jq /
# python3 / curl / glab going missing). This reads the install + check-deps output
# and FAILS unless EVERY missing required dependency is a whitelisted expected gap.
#
# Two independent guards, because check-deps reports missing deps two ways:
#   1. Per-item: each missing REQUIRED dep prints "  [!] <item> — NOT FOUND …"
#      (check-deps.sh _check_hook_scripts/_check_manifest_deps/_check_commands/
#      _check_secrets). Any such line NOT matching the whitelist → fail.
#   2. Count cross-check: check-deps prints "<N> required dependency/dependencies
#      missing." If N exceeds the number of "[!] … NOT FOUND" lines we saw, some
#      missing deps produced NO such line and are UNACCOUNTED — the canonical case
#      is jq itself missing: check-deps' jq-guarded scans bail early (printing a
#      lowercase "jq not found", not "NOT FOUND") yet still count as missing. We
#      refuse to tolerate what we cannot see.
#
# Input:  the combined install + check-deps output on stdin.
# Exit:   0 if every missing REQUIRED dep is whitelisted AND fully accounted for;
#         1 (loud) otherwise.
set -euo pipefail

# Substrings identifying the legitimately-expected-missing items at build time.
# Keep in sync with R-12 (secrets, runtime-mounted) and the runtime-installed
# wtf-server hook. The wtf entry matches by basename so it holds regardless of the
# home prefix ($HOME differs per user / container uid).
# NOTE: slack-bot-token was removed here with Slack support (#1062). Do NOT
# re-add a token to this list without a consumer — a whitelist entry for a
# dependency nothing needs silently tolerates a real gap of the same name.
#
# claude-code-oauth-token's consumer (#1076): bootstrap.sh projects it into
# $CLAUDE_CODE_OAUTH_TOKEN via OAW_SECRET_ENV, and the /usr/local/bin/claude
# wrapper sources bootstrap before exec'ing the agent. It is expected-missing at
# BUILD time for the same reason as discord-bot-token — secrets are mounted at
# runtime, never baked into a layer (R-12).
EXPECTED_MISSING=(
	'claude-code-oauth-token'
	'github-pat'
	'discord-bot-token'
	'wtf-post-tool-use.sh'
)

input="$(cat)"

unexpected=0
not_found_count=0
while IFS= read -r line; do
	# Only the check-deps missing-REQUIRED-dep marker: "  [!] … NOT FOUND …".
	# Anchoring on "[!]" (not a bare "NOT FOUND") avoids a benign upstream
	# "NOT FOUND" elsewhere in the install stream tripping the gate.
	[[ "$line" == *"[!]"*"NOT FOUND"* ]] || continue
	not_found_count=$((not_found_count + 1))
	for pat in "${EXPECTED_MISSING[@]}"; do
		[[ "$line" == *"$pat"* ]] && continue 2
	done
	echo "UNEXPECTED missing dependency (outside the image-build whitelist): ${line}" >&2
	unexpected=1
done <<<"$input"

# Count cross-check: reconcile the SUMMARY count with what we could actually see.
summary_count="$(printf '%s\n' "$input" | grep -oE '[0-9]+ required dependency/dependencies missing' | grep -oE '^[0-9]+' | tail -1 || true)"
if [[ -n "$summary_count" && "$summary_count" -gt "$not_found_count" ]]; then
	echo "check-deps reported ${summary_count} missing dependency/dependencies but only ${not_found_count} appeared as '[!] … NOT FOUND' — $((summary_count - not_found_count)) unaccounted (e.g. jq itself missing bails check-deps' guarded scans before they can report)." >&2
	unexpected=1
fi

if [[ "$unexpected" -ne 0 ]]; then
	echo "check-deps reported a missing dependency outside the expected-missing set — failing the build (#1016)." >&2
	exit 1
fi

echo "check-deps advisory: only expected-missing items (secrets + wtf hook), fully accounted — tolerated."
