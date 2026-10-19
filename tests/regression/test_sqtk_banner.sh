#!/usr/bin/env bash
# test_sqtk_banner.sh — #1236 regression test for scripts/hooks/workflow/sqtk-banner.sh.
#
# The banner is the human's glance at what is waiting on him. It must show open items only,
# mark answered ones, stay silent when nothing is open, and never break a turn: any error
# prints nothing and exits 0. curl is stubbed on PATH.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO_DIR/scripts/hooks/workflow/sqtk-banner.sh"

echo "test_sqtk_banner"
echo "──────────────────────────────────────────"

FAILS=0
pass() { echo "  [PASS] $1"; }
fail() {
	echo "  [FAIL] $1"
	FAILS=$((FAILS + 1))
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin"
cat >"$WORK/bin/curl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$CURL_LOG"
[[ "${FAKE_RC:-0}" == 0 ]] || exit "$FAKE_RC"
cat "$FAKE_BODY"
EOF
chmod +x "$WORK/bin/curl"
export CURL_LOG="$WORK/curl.log" FAKE_BODY="$WORK/body.json" FAKE_RC=0 SQUAWK_URL="http://squawk.test"

body() { printf '%s\n' "$1" >"$FAKE_BODY"; }
run() { PATH="$WORK/bin:$PATH" bash "$HOOK" </dev/null; }
msg() { jq -r '.systemMessage // empty' <<<"$1" 2>/dev/null; }

# 1. Open items listed in seq order; closed ones left out; an answered one marked.
body '{"squawks":[
 {"seq":4,"state":"open","text":"[bf·cc] cut sdlc v5? → yes"},
 {"seq":2,"state":"open","text":"[ks·bm] yes-prod for the repoint?\nmore detail"},
 {"seq":3,"state":"confirmed","text":"done already"}]}'
m=$(msg "$(run)")
first=$(sed -n 2p <<<"$m")
[[ "$m" == *"Waiting on BJ (2) in bj:needs"* ]] && pass "count and list named" || fail "header (m='$m')"
[[ "$first" == *"#2 [ks·bm] yes-prod for the repoint?" ]] && pass "seq order, first line only" ||
	fail "order/first line (line='$first')"
[[ "$m" == *"#4 [bf·cc] cut sdlc v5?  (answered)"* ]] && pass "answered item marked" || fail "answered mark (m='$m')"
[[ "$m" != *"done already"* ]] && pass "closed items left out" || fail "closed item shown"

# 1b. An arrow in the prose stays in the shown text; only the last one starts the answer.
body '{"squawks":[{"seq":7,"state":"open","text":"v65 → v66 broke the gate →"}]}'
m=$(msg "$(run)")
[[ "$m" == *"#7 v65 → v66 broke the gate"* && "$m" != *"(answered)"* ]] && pass "prose arrow kept, not an answer" ||
	fail "prose arrow (m='$m')"

# 2. The list's name is URL-encoded on the request.
[[ "$(tail -1 "$CURL_LOG")" == *"name=bj%3Aneeds"* ]] && pass "list name encoded" ||
	fail "encoding ($(tail -1 "$CURL_LOG"))"

# 3. Nothing open: silent.
body '{"squawks":[{"seq":1,"state":"retired","text":"x"}]}'
out=$(run)
[[ -z "$out" ]] && pass "nothing open: silent" || fail "nothing open printed '$out'"

# 4. Fails open.
out=$(FAKE_RC=22 run)
rc=$?
[[ $rc -eq 0 && -z "$out" ]] && pass "server error: silent, exit 0" || fail "server error (rc=$rc)"
body 'garbage'
out=$(run)
rc=$?
[[ $rc -eq 0 && -z "$out" ]] && pass "malformed body: silent, exit 0" || fail "malformed (rc=$rc)"
out=$(SQUAWK_URL='' run)
[[ -z "$out" ]] && pass "no SQUAWK_URL: silent" || fail "no SQUAWK_URL printed"

# 5. The output never blocks a turn.
body '{"squawks":[{"seq":1,"state":"open","text":"x"}]}'
[[ "$(run | jq -r 'has("decision")')" == false ]] && pass "never emits a decision" || fail "emitted a decision"

echo
if [[ $FAILS -eq 0 ]]; then
	echo "  All sqtk-banner checks passed."
	exit 0
fi
echo "  $FAILS sqtk-banner check(s) FAILED."
exit 1
