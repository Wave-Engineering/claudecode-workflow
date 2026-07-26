#!/usr/bin/env bash
# test_oaw_sign_image_action.sh — #1040.
#
# The oaw-sign-image composite action is the DRY core of fleetwide image signing, so its
# contract is load-bearing: sign the digest, attest the SBOM to rekor OR (for large images)
# to a TSA off-rekor, skip the SBOM when asked, and refuse a non-digest ref. cosign + syft
# are stubbed on PATH so the exact invocations are asserted hermetically (no network, no
# real signing) — a signer only ever run against the happy path is unverified.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ACTION_DIR="$ROOT/.github/actions/oaw-sign-image"
SCRIPT="$ACTION_DIR/oaw-sign-image.sh"
ACTION_YML="$ACTION_DIR/action.yml"
DIGEST="ghcr.io/wave-engineering/example@sha256:$(printf 'a%.0s' {1..64})"

pass=0
fail=0
check() { # label  condition-already-evaluated($?)
	if [[ "$1" == 0 ]]; then
		echo "  [PASS] $2"
		pass=$((pass + 1))
	else
		echo "  [FAIL] $2"
		fail=$((fail + 1))
	fi
}

# --- stub cosign + syft on PATH, logging every call ---------------------------
stub_dir="$(mktemp -d)"
calls="$stub_dir/calls.log"
trap 'rm -rf "$stub_dir"' EXIT
cat >"$stub_dir/cosign" <<EOF
#!/usr/bin/env bash
echo "cosign \$*" >> "$calls"
exit 0
EOF
cat >"$stub_dir/syft" <<EOF
#!/usr/bin/env bash
echo "syft \$*" >> "$calls"
exit 0
EOF
chmod +x "$stub_dir/cosign" "$stub_dir/syft"

run() { # env-assignments...  → runs the signer with stubs on PATH, resets the call log
	: >"$calls"
	env PATH="$stub_dir:$PATH" DIGEST_REF="$DIGEST" "$@" bash "$SCRIPT" >/dev/null 2>&1
}

# 1. Default (SBOM to rekor): sign + attest, NO --tlog-upload=false.
run
grep -q "cosign sign" "$calls"
check $? "default: cosign sign the digest"
grep -q "syft .*spdx-json" "$calls"
check $? "default: syft generates an SBOM"
grep -q "cosign attest" "$calls"
check $? "default: cosign attest the SBOM"
! grep -q -- "--tlog-upload=false" "$calls"
check $? "default: SBOM goes to rekor (no --tlog-upload=false)"
! grep -q -- "--timestamp-server-url" "$calls"
check $? "default: no TSA timestamp (fully rekor, not TSA)"

# 2. Large-image path (SBOM_TLOG=false): attest off-rekor with a TSA timestamp.
run SBOM_TLOG=false
grep -q -- "--tlog-upload=false" "$calls"
check $? "SBOM_TLOG=false: SBOM kept off rekor"
grep -q -- "--timestamp-server-url" "$calls"
check $? "SBOM_TLOG=false: binds an RFC3161 TSA timestamp"

# 3. ATTACH_SBOM=false: sign only, no syft, no attest.
run ATTACH_SBOM=false
grep -q "cosign sign" "$calls"
check $? "attach-sbom=false: still signs"
! grep -q "syft " "$calls"
check $? "attach-sbom=false: no syft"
! grep -q "cosign attest" "$calls"
check $? "attach-sbom=false: no attestation"

# 4. Refuse a non-digest (moving-tag) ref — R-23.
if env PATH="$stub_dir:$PATH" DIGEST_REF="ghcr.io/wave-engineering/example:latest" bash "$SCRIPT" >/dev/null 2>&1; then
	check 1 "refuses a non-digest ref (moving tag)" # returned 0 = did NOT refuse → fail
else
	check 0 "refuses a non-digest ref (moving tag)" # non-zero = refused → pass
fi

# 5. action.yml contract: inputs + installers + runs the bundled script.
grep -q "digest-ref:" "$ACTION_YML"
check $? "action.yml exposes digest-ref input"
grep -q "sbom-tlog:" "$ACTION_YML"
check $? "action.yml exposes the sbom-tlog toggle"
grep -q "sigstore/cosign-installer" "$ACTION_YML"
check $? "action.yml installs cosign"
grep -q 'GITHUB_ACTION_PATH.*/oaw-sign-image.sh' "$ACTION_YML"
check $? "action.yml runs the bundled script via github.action_path"

echo
echo "  Results: $pass passed, $fail failed"
[[ "$fail" == 0 ]]
