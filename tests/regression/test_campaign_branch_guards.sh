#!/usr/bin/env bash
# test_campaign_branch_guards.sh — #1052: the campaign engine's fail-loud branch guards.
#
# Picked up by scripts/ci/validate.sh's "Regression tests" loop (tests/regression/*.sh).
#
# #1052 replaces per-wave merge-backs to the protected branch with ONE campaign branch that is written
# to trunk exactly once, at the DoD gate. That makes a small set of branch-identity facts load-bearing:
# get any of them wrong and the engine either writes trunk early (the thing #1052 removes) or authorizes
# its single trunk write on evidence about a branch it never touched. Each is enforced in
# campaign-workflow.js as a throw; this asserts those throws exist in BOTH the source and the committed
# bundle (the bundle is the artifact the Workflow tool actually runs — a guard present only in source is
# not deployed). Same wiring-guard shape as test_dispatch_ceiling.sh.
#
# Guards asserted:
#   1. node --check on the source + bundle (syntax must hold).
#   2. campaignBranch === protectedBranch → throw. A campaign whose "integration branch" IS trunk
#      restores per-wave trunk writes under a name claiming otherwise.
#   3. An explicitly-passed campaignBranch is lowercased through the same normalization as the derived
#      name — otherwise a hand-built `campaign/56-Blueshift` and a derived `campaign/56-blueshift` are
#      two different case-sensitive server refs for one campaign.
#   4. bootstrap.created && ALREADY_INTEGRATED.length > 0 → throw. A freshly-cut branch cannot already
#      carry integrated waves; counting them would empty routeRelease's missing[] on the wrong branch.
#   5. The per-wave kahuna name is always DERIVED — a plan-supplied wave.kahunaBranch is never returned
#      (it is plan-scoped and trunk-based: shared across waves, so wave 1's promote deletes wave 2's base).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
NW="skills/nextwave"

echo "test_campaign_branch_guards"
echo "──────────────────────────────────────────"

pass=0
fail=0
check() {
	if [[ -n "$1" ]]; then
		pass=$((pass + 1))
		echo "  [PASS] $2"
	else
		fail=$((fail + 1))
		echo "  [FAIL] $2"
	fi
}

if ! command -v node &>/dev/null; then
	echo "  [FAIL] node not found — required for the #1052 campaign branch-guard test"
	exit 1
fi

# 1. syntax — source and bundle both parse
for f in "$NW/campaign-workflow.js" "$NW/campaign-workflow.bundled.js" "$NW/per-wave-workflow.js"; do
	if node --check "$REPO_DIR/$f" 2>/dev/null; then
		pass=$((pass + 1))
		echo "  [PASS] $(basename "$f") syntax (node --check)"
	else
		fail=$((fail + 1))
		echo "  [FAIL] $(basename "$f") syntax (node --check)"
	fi
done

# 2-4. the campaign-side guards, in source AND bundle
for f in "$NW/campaign-workflow.js" "$NW/campaign-workflow.bundled.js"; do
	src="$(cat "$REPO_DIR/$f")"
	label="$(basename "$f")"

	check "$(grep -F 'must not equal protectedBranch' <<<"$src" || true)" \
		"$label: campaignBranch === protectedBranch throws (no campaign integrating onto trunk)"

	# The override must flow through the same lowercasing as the derived name.
	check "$(grep -F 'params.campaignBranch ?? campaignBranchFor' <<<"$src" | grep -F 'String(' || true)" \
		"$label: an explicit campaignBranch is normalized (lowercased) like the derived one"
	check "$(grep -F '})).toLowerCase()' <<<"$src" || true)" \
		"$label: ... and the normalization is applied to the whole expression, not just the fallback"

	check "$(grep -F 'was just CUT FRESH off' <<<"$src" || true)" \
		"$label: fresh-cut branch + already-integrated waves throws (integrations on a DIFFERENT branch)"

	# The derived per-wave kahuna wins; a plan-supplied one is ignored.
	check "$(grep -F 'waveKahunaFor' <<<"$src" || true)" \
		"$label: the per-wave kahuna name is derived via waveKahunaFor"
	check "$(grep -F 'ignoring plan-supplied kahunaBranch' <<<"$src" || true)" \
		"$label: a plan-supplied wave.kahunaBranch is logged and IGNORED (shared + trunk-based)"
done

# 5. the per-wave half — bootstrap establishes the kahuna off the INTEGRATION BASE, verified, fail-loud
for f in "$NW/per-wave-workflow.js" "$NW/per-wave-workflow.bundled.js"; do
	src="$(cat "$REPO_DIR/$f")"
	label="$(basename "$f")"

	check "$(grep -F 'KAHUNA-BOOTSTRAP' <<<"$src" || true)" \
		"$label: the wave establishes its own kahuna branch (nothing else creates it)"
	check "$(grep -F 'branch ${KAHUNA_BRANCH} origin/${INTEGRATION_BASE}' <<<"$src" || true)" \
		"$label: the kahuna is cut from the INTEGRATION BASE, never the protected branch"
	check "$(grep -F 'must not equal ${label}' <<<"$src" || true)" \
		"$label: kahuna === base/trunk throws (else flights land ungated and the gate's diff is empty)"
	check "$(grep -F 'test(bootstrapSha)' <<<"$src" || true)" \
		"$label: ready requires an observed sha-shaped head_sha (verified, not merely reported)"
done

echo ""
if ((fail > 0)); then
	echo "  $fail check(s) failed"
	exit 1
fi
echo "  all $pass campaign branch-guard checks passed"
