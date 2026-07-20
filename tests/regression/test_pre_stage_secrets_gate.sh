#!/usr/bin/env bash
# test_pre_stage_secrets_gate.sh — regression tests for #929
#
# The gate had three defects that composed into something worse than absent:
#
#   1. Unanchored patterns flagged the JS builtin `Object.keys` (via `\.key`)
#      and `foo.environment.ts` (via `\.env`). @treebeard was blocked from
#      committing mcp-logger#3 by exactly this. She escalated instead of using
#      --no-verify, which is why it was found rather than routed around.
#   2. File extraction took everything after `git add`, so a compound command
#      dragged the NEXT command's arguments in as "files".
#   3. Flag-stripping reduced `git add -A` to an empty list, so the broadest
#      staging command was never scanned. Silent, and reported success.
#
# (1) makes people disable the gate; (3) means it was already off where it
# mattered most. Every case below was verified RED against the pre-fix script.
set -uo pipefail

HOOK="$(cd "$(dirname "$0")/../.." && pwd)/scripts/hooks/workflow/pre-stage-secrets-gate.sh"
PASS=0
FAIL=0

# Run the hook with a synthesized PreToolUse payload; echo "BLOCK" or "ALLOW".
run_gate() {
	local cmd="$1" dir="${2:-}"
	local payload out
	payload=$(printf '{"session_id":"test","tool_input":{"command":%s}}' "$(printf '%s' "$cmd" | jq -Rs .)")
	if [[ -n "$dir" ]]; then
		out=$(cd "$dir" && printf '%s' "$payload" | bash "$HOOK" 2>/dev/null || true)
	else
		out=$(printf '%s' "$payload" | bash "$HOOK" 2>/dev/null || true)
	fi
	if printf '%s' "$out" | grep -q '"decision":"block"'; then printf 'BLOCK'; else printf 'ALLOW'; fi
}

check() {
	local label="$1" want="$2" got="$3"
	if [[ "$want" == "$got" ]]; then
		printf '  [+] %s\n' "$label"
		PASS=$((PASS + 1))
	else
		printf '  [x] %s — wanted %s, got %s\n' "$label" "$want" "$got"
		FAIL=$((FAIL + 1))
	fi
}

printf '\n== defect 1: ordinary code must not flag ==\n'
# The exact string that blocked mcp-logger#3.
check "Object.keys as a grep argument" ALLOW \
	"$(run_gate 'git add index.ts && grep -c "Object.keys" index.ts')"
check "foo.environment.ts (contains .env)" ALLOW "$(run_gate 'git add foo.environment.ts')"
check "monkey.test.ts" ALLOW "$(run_gate 'git add monkey.test.ts')"
check "hotkeys.tsx" ALLOW "$(run_gate 'git add src/hotkeys.tsx')"
check "keys.ts" ALLOW "$(run_gate 'git add lib/keys.ts')"

printf '\n== genuine secrets must still block ==\n'
check "server.key" BLOCK "$(run_gate 'git add server.key')"
check ".env" BLOCK "$(run_gate 'git add .env')"
check ".env.local" BLOCK "$(run_gate 'git add .env.local')"
check "cert.pem" BLOCK "$(run_gate 'git add certs/cert.pem')"
check "credentials.json" BLOCK "$(run_gate 'git add credentials.json')"
check "terraform.tfvars" BLOCK "$(run_gate 'git add infra/terraform.tfvars')"
check "svc-credentials.yaml" BLOCK "$(run_gate 'git add svc-credentials.yaml')"

printf '\n== defect 2: compound commands must not leak later arguments ==\n'
check "&& with a secret-shaped arg to the NEXT command" ALLOW \
	"$(run_gate 'git add README.md && cat server.key')"
check "; separated" ALLOW "$(run_gate 'git add README.md ; ls .env')"
check "piped" ALLOW "$(run_gate 'git add README.md | tee .env.local')"
# ...but a secret named on the git add itself still blocks, even in a compound.
check "secret on the git add side of a compound" BLOCK \
	"$(run_gate 'git add .env && echo done')"

printf '\n== defect 3: broad staging must be SCANNED, not skipped ==\n'
TMP=$(mktemp -d)
git -C "$TMP" init -q 2>/dev/null
printf 'x\n' >"$TMP/.env"
printf 'x\n' >"$TMP/README.md"
check "git add -A with a secret present" BLOCK "$(run_gate 'git add -A' "$TMP")"
check "git add . with a secret present" BLOCK "$(run_gate 'git add .' "$TMP")"
check "git add -u with a secret present" BLOCK "$(run_gate 'git add -u' "$TMP")"

TMP2=$(mktemp -d)
git -C "$TMP2" init -q 2>/dev/null
printf 'x\n' >"$TMP2/README.md"
printf 'x\n' >"$TMP2/index.ts"
check "git add -A with NO secret present" ALLOW "$(run_gate 'git add -A' "$TMP2")"
rm -rf "$TMP" "$TMP2"

printf '\n== escape hatch still works ==\n'
check "SECRETS_GATE_DISABLED=1" ALLOW \
	"$(SECRETS_GATE_DISABLED=1 run_gate 'git add .env')"

printf '\n== non-git-add commands are ignored ==\n'
check "git commit" ALLOW "$(run_gate 'git commit -m "add .env support"')"
check "unrelated command naming a secret" ALLOW "$(run_gate 'cat .env')"

printf '\n──────────────────────────────────────────\n'
printf 'Results: %d passed, %d failed\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
