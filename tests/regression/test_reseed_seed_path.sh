#!/usr/bin/env bash
# test_reseed_seed_path.sh — #1225 regression test for the reseed seed's home.
#
# The seed lives at ONE path, .claude/reseed-revive.md, and must never be
# committable: it carries session detail, and in a GitLab repo that detail is
# the partner's. The ignore guard is prose in skills/reseed/SKILL.md that an agent
# runs, so this test EXTRACTS the guard from the skill and runs it — a test of a
# copy would pass while the skill drifted.
#
# Asserted in a repo that does NOT already ignore .claude/: after the guard, the
# seed is git-ignored and there is no tracked-file diff; a second run adds no
# second entry.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SKILL="$REPO_DIR/skills/reseed/SKILL.md"

echo "test_reseed_seed_path"
echo "──────────────────────────────────────────"

FAILS=0
pass() { echo "  [PASS] $1"; }
fail() {
	echo "  [FAIL] $1"
	FAILS=$((FAILS + 1))
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# The fenced bash block in SKILL.md that runs `git check-ignore` on the seed.
GUARD="$(awk '
	/^```bash$/ { inb = 1; buf = ""; next }
	/^```$/ && inb { inb = 0; if (buf ~ /check-ignore/ && buf ~ /reseed-revive\.md/) { printf "%s", buf; exit } ; next }
	inb { buf = buf $0 "\n" }
' "$SKILL")"
if [[ -n "$GUARD" ]]; then
	pass "ignore guard found in skills/reseed/SKILL.md"
else
	fail "no bash block with check-ignore + reseed-revive.md in the skill"
fi

if grep -q '\.claude/reseed-revive\.md' "$SKILL" && ! grep -qE '<topic>-reseed\.md|reseed-<topic>' "$SKILL"; then
	pass "the skill names one fixed seed path, no per-topic names"
else
	fail "the skill still describes per-topic seed names"
fi
if grep -q 'seed_path' "$SKILL"; then
	fail "the skill still writes seed_path into the armed file"
else
	pass "the armed file no longer carries seed_path"
fi

R="$WORK/repo"
mkdir -p "$R/.claude"
git -C "$R" init -q
printf 'tracked\n' >"$R/README"
git -C "$R" add README
git -C "$R" -c user.email=t@t -c user.name=t commit -qm init

if git -C "$R" check-ignore -q .claude/reseed-revive.md; then
	fail "fixture already ignores the seed — the test would prove nothing"
fi

(cd "$R" && bash -c "$GUARD")
(cd "$R" && bash -c "$GUARD")
printf 'seed\n' >"$R/.claude/reseed-revive.md"

if git -C "$R" check-ignore -q .claude/reseed-revive.md; then
	pass "seed is git-ignored after the guard"
else
	fail "seed is NOT ignored"
fi
if [[ -z "$(git -C "$R" status --porcelain)" ]]; then
	pass "no tracked-file diff (entry went to info/exclude)"
else
	fail "visible diff: $(git -C "$R" status --porcelain | tr '\n' ' ')"
fi
n=$(grep -c 'reseed-revive.md' "$(git -C "$R" rev-parse --path-format=absolute --git-path info/exclude)")
if [[ "$n" -eq 1 ]]; then
	pass "running the guard twice adds one entry, not two"
else
	fail "exclude has $n entries"
fi

# --- a session rooted in a SUBDIRECTORY (monorepos) -----------------------------
# An exclude entry containing a slash is anchored to the repo root, so a plain
# ".claude/reseed-revive.md" never matches sub/.claude/reseed-revive.md: the seed
# would stay committable and every reseed would append another dead entry.
R2="$WORK/mono"
mkdir -p "$R2/svc/.claude"
git -C "$R2" init -q
printf 'tracked\n' >"$R2/README"
git -C "$R2" add README
git -C "$R2" -c user.email=t@t -c user.name=t commit -qm init
(cd "$R2/svc" && bash -c "$GUARD")
(cd "$R2/svc" && bash -c "$GUARD")
printf 'seed\n' >"$R2/svc/.claude/reseed-revive.md"
if git -C "$R2/svc" check-ignore -q .claude/reseed-revive.md && [[ -z "$(git -C "$R2" status --porcelain)" ]]; then
	pass "subdirectory session: seed ignored, no diff"
else
	fail "subdirectory session: seed NOT ignored ($(git -C "$R2" status --porcelain | tr '\n' ' '))"
fi
n=$(grep -c 'reseed-revive.md' "$(git -C "$R2" rev-parse --path-format=absolute --git-path info/exclude)")
if [[ "$n" -eq 1 ]]; then
	pass "subdirectory session: the guard is idempotent (one entry)"
else
	fail "subdirectory session: exclude has $n entries"
fi

echo ""
if [[ "$FAILS" -gt 0 ]]; then
	echo "  $FAILS assertion(s) failed"
	exit 1
fi
echo "  all assertions passed"
