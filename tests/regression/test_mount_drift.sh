#!/usr/bin/env bash
# test_mount_drift.sh — #1069: mounts.d/ is the source of truth; a profile is a COPY.
#
# The defect: mount_resolver emits `host:container[:ro]` and AoE's extra_volumes
# consumes exactly that, but the copy is MANUAL and nothing checked it. Observed
# 2026-07-30 — `extra_volumes` was [0 items] on a fresh profile, so every fragment
# (memory, secrets, caches) was declared and applied to NOTHING, silently.
#
# Every case below PLANTS the failure. A drift check that has only ever run against
# a matching pair has not been tested.
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$REPO_DIR/scripts/ci/check-mount-drift.sh"
FAILS=0
pass() { echo "  [PASS] $1"; }
fail() {
	echo "  [FAIL] $1" >&2
	FAILS=$((FAILS + 1))
}

[[ -x "$SCRIPT" ]] || fail "check-mount-drift.sh is not executable"
bash -n "$SCRIPT" || fail "bash -n failed"
pass "syntax + executable"

SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT

# Hermetic on BOTH sides. AOE_PROFILE_ROOT isolates only the PROFILE; the MANIFEST
# side resolves through the process $HOME (mount_resolver -> expanduser). Reading the
# operator's real ~/.oaw made the positive cases pass or fail on host provisioning —
# green here, red on a runner where none of the sources exist. Same green-here/
# red-there split #1067 hit; injecting HOME is what actually closes it.
FAKE_HOME="$SANDBOX/home"
mkdir -p "$FAKE_HOME"
MAJOR=7

# A fake profile root so we never read or mutate the operator's real profiles.
mk_profile() { # <name> <volumes-toml-body>
	mkdir -p "$SANDBOX/profiles/$1"
	{
		echo "[sandbox]"
		echo "extra_volumes = ["
		printf '%s\n' "$2"
		echo "]"
	} >"$SANDBOX/profiles/$1/config.toml"
}

expected="$(HOME="$FAKE_HOME" python3 "$REPO_DIR/containers/oakandwave-workflow/mount_resolver.py" \
	--major "$MAJOR" --format aoe 2>/dev/null)"

# Materialise every declared source so the positive cases test ONE variable (drift)
# rather than tripping the missing-source check at the same time. Kind matters: four
# of these are FILES, and creating a directory in their place reproduces the very
# failure the check warns about.
while IFS= read -r l; do
	[[ -n "$l" ]] || continue
	src="${l%%:*}"
	case "$src" in
	*.json | */.env | */discord-bot-token) install -D /dev/null "$src" 2>/dev/null ;;
	*) mkdir -p "$src" 2>/dev/null ;;
	esac
done <<<"$expected"
[[ -n "$expected" ]] || fail "mount_resolver emitted nothing for major $MAJOR"

all_vols="$(while IFS= read -r l; do [[ -n "$l" ]] && echo "    \"$l\","; done <<<"$expected")"

run() { HOME="$FAKE_HOME" AOE_PROFILE_ROOT="$SANDBOX/profiles" "$SCRIPT" "$@" --major "$MAJOR" 2>&1; }

# --- the real-world case: a profile that copied NOTHING ----------------------
mk_profile empty ""
out="$(run empty)"
rc=$?
[[ "$rc" -eq 3 ]] || fail "an empty extra_volumes must fail (exit 3), got $rc"
grep -q 'DRIFT' <<<"$out" || fail "an empty profile must be reported as drift"
grep -q 'these mounts do not happen' <<<"$out" ||
	fail "the report must say what the drift MEANS, not just that it differs"
pass "empty extra_volumes -> drift (the observed real case)"

# --- a profile missing exactly one entry -------------------------------------
mk_profile partial "$(sed '1d' <<<"$all_vols")"
out="$(run partial)"
rc=$?
[[ "$rc" -eq 3 ]] || fail "a missing entry must fail (exit 3), got $rc"
first_src="$(head -1 <<<"$expected")"
grep -qF "$first_src" <<<"$out" || fail "the report must NAME the missing mount"
pass "one missing entry -> drift, named"

# --- a profile carrying an UNDECLARED entry ----------------------------------
mk_profile extra "$all_vols"$'\n    "/tmp/rogue:/home/ubuntu/rogue",'
out="$(run extra)"
rc=$?
[[ "$rc" -eq 3 ]] || fail "an undeclared entry must fail (exit 3), got $rc"
grep -q '/tmp/rogue' <<<"$out" || fail "the report must NAME the undeclared mount"
grep -q 'unreviewed' <<<"$out" || fail "an undeclared mount must be called out as unreviewed"
pass "undeclared entry -> drift, named"

# --- a profile with no config at all ------------------------------------------
out="$(run nonexistent)"
rc=$?
[[ "$rc" -eq 3 ]] || fail "a profile with no config.toml must fail (exit 3), got $rc"
grep -q 'inherits the GLOBAL' <<<"$out" ||
	fail "it must explain WHY a missing config means inert mounts"
pass "no config.toml -> failure, with the reason"

# --- ORDER must not matter ----------------------------------------------------
mk_profile reordered "$(sort -r <<<"$all_vols")"
run reordered >/dev/null 2>&1
rc=$?
[[ "$rc" -eq 0 ]] || fail "reordering must NOT be reported as drift (docker ignores order), got $rc"
pass "reordered volumes are in sync (order is not semantic)"

# --- an exact copy passes -----------------------------------------------------
mk_profile exact "$all_vols"
run exact >/dev/null 2>&1
rc=$?
[[ "$rc" -eq 0 ]] || fail "an exact copy must pass, got $rc"
pass "exact copy -> in sync"

# --- a declared source that does not exist ------------------------------------
# Docker create-if-missing makes this an empty dir rather than an error, which is
# the whole reason the check stats sources at all.
out="$(HOME="$SANDBOX/nohome" AOE_PROFILE_ROOT="$SANDBOX/profiles" "$SCRIPT" exact --major "$MAJOR" 2>&1)"
rc=$?
[[ "$rc" -eq 3 ]] || fail "absent host sources must fail (exit 3), got $rc"
grep -q 'MISSING SOURCE' <<<"$out" || fail "an absent source must be reported"
grep -q 'EMPTY DIRECTORY' <<<"$out" ||
	fail "it must explain the SILENT consequence, not just report absence"
pass "absent host source -> failure, with the silent-failure explanation"

# --- the dev-mode overlay exclusion (the most fragile logic here) -------------
# It was previously untested: no case used a profile name that resolves to a real
# container profile, so profiles.py exited 2, the emit was swallowed, and the parse
# / grep / tilde-expansion never ran at all. Both failure modes are bad — a changed
# emit shape gives PERMANENT false drift (which trains people to ignore the check),
# and an over-broad grep silently excludes real undeclared mounts.
overlay="$FAKE_HOME/.oaw/overlay/$MAJOR/skills:/home/ubuntu/.claude/skills"
mk_profile dev-mode "$all_vols"$'\n    "'"$overlay"'",'
run dev-mode >/dev/null 2>&1
rc=$?
[[ "$rc" -eq 0 ]] ||
	fail "dev-mode's own skills overlay must NOT read as drift (it is profile-rendered), got $rc"
pass "dev-mode skills overlay excluded (derived from profiles.py, not hardcoded)"

# …and the exclusion must not be a blanket pass for anything under /home/ubuntu.
mk_profile dev-mode "$all_vols"$'\n    "'"$overlay"$'",\n    "/tmp/rogue:/home/ubuntu/rogue",'
out="$(run dev-mode)"
rc=$?
[[ "$rc" -eq 3 ]] || fail "an unrelated undeclared mount must still be drift on dev-mode, got $rc"
grep -q '/tmp/rogue' <<<"$out" || fail "the undeclared mount must be named"
pass "dev-mode exclusion is not over-broad (rogue mount still caught)"

# --- the paste-ready remedy must be real TOML that matches the manifest -------
toml="$(HOME="$FAKE_HOME" python3 "$REPO_DIR/containers/oakandwave-workflow/mount_resolver.py" \
	--major "$MAJOR" --format aoe-toml 2>/dev/null)"
python3 - "$MAJOR" <<-PYEOF || fail "aoe-toml output does not parse or does not match --format aoe"
	import subprocess, sys, tomllib, os
	major = sys.argv[1]
	env = dict(os.environ)
	out = subprocess.run(["python3", "$REPO_DIR/containers/oakandwave-workflow/mount_resolver.py",
	                      "--major", major, "--format", "aoe-toml"],
	                     capture_output=True, text=True, env=env).stdout
	gen = tomllib.loads("[sandbox]\n" + out)["sandbox"]["extra_volumes"]
	aoe = subprocess.run(["python3", "$REPO_DIR/containers/oakandwave-workflow/mount_resolver.py",
	                      "--major", major, "--format", "aoe"],
	                     capture_output=True, text=True, env=env).stdout.strip().split("\n")
	raise SystemExit(0 if gen == aoe else 1)
PYEOF
pass "aoe-toml remedy parses as TOML and matches the manifest exactly"

echo ""
if ((FAILS > 0)); then
	echo "  $FAILS mount-drift check(s) FAILED"
	exit 1
fi
echo "  all mount-drift checks passed"
