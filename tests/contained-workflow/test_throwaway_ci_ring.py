"""Oracle for Story 2.2 (#967) — the throwaway-CI ring (E2E-01, R-05/R-23/R-24).

The authoritative end-to-end proof is E2E-01 itself: pull the candidate digest
from ghcr, verify labels/permissions/signature/SBOM, install-from-zero, smoke.
That needs a real registry push + a signed digest, so it cannot run in the stock
pytest lane (mirrors test_provenance.py). This module verifies, hermetically, the
properties that make the ring correct:

1. It refuses anything that is not a registry digest — E2E-01 tests the registry
   artifact BY DIGEST, never a local build (R-23). This is a *behavioral* test:
   the guard runs before any tool is required, so it fires with no docker/cosign.
2. Every provenance check (signature, SBOM, pullability/permissions, labels) is
   ordered strictly BEFORE the smoke suite (R-24, AC2).
3. The smoke runs with OAKANDWAVE_REQUIRE_IMAGE, so a red smoke is a hard fail
   that blocks the digest — never a silent skip (R-05/R-23, AC3).
4. The signature check is identity-bound (not a bare `cosign verify`).
5. The image workflow runs the ring as a `smoke` job after `build`, fed the exact
   digest the build job pushed (R-23).

A real-registry branch (skip-gated exactly like test_image.py) runs the whole
ring against a live digest when OAKANDWAVE_RING_DIGEST is set.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RING_SCRIPT = REPO_ROOT / "scripts" / "ci" / "throwaway-ci-ring.sh"
IMAGE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "oakandwave-workflow-image.yml"
SMOKE_SUITE = REPO_ROOT / "tests" / "contained-workflow" / "test_image.py"

# The provenance-check phase markers the ring emits, in the order R-24 requires,
# and the smoke marker that must follow ALL of them.
PROVENANCE_MARKERS = (
    "[ring] verify-signature",
    "[ring] verify-sbom",
    "[ring] verify-pullable",
    "[ring] verify-labels",
)
SMOKE_MARKER = "[ring] smoke"


def _run_ring(digest_ref: str | None) -> subprocess.CompletedProcess[str]:
    """Run the ring script with a controlled DIGEST_REF (or unset) and no ambient
    provenance env. The digest guard runs before any tool is required, so this is
    hermetic for the guard-behavior tests."""
    env = dict(os.environ)
    for k in ("DIGEST_REF", "SMOKE_SUITE", "RING_SKIP_TEARDOWN"):
        env.pop(k, None)
    if digest_ref is not None:
        env["DIGEST_REF"] = digest_ref
    return subprocess.run(
        ["bash", str(RING_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_ring_script_is_executable() -> None:
    """The workflow invokes the ring directly (./scripts/ci/...), so it must be +x."""
    assert RING_SCRIPT.exists(), f"ring script missing: {RING_SCRIPT}"
    assert os.access(RING_SCRIPT, os.X_OK), "ring script must be executable"


def test_ring_refuses_a_moving_tag_ref() -> None:
    """A non-digest ref (a moving tag) is rejected before anything runs (R-23).

    E2E-01 tests the registry artifact by digest, never a local build or a tag —
    the guard fails the ring loud and early, with no docker/cosign needed.
    """
    proc = _run_ring("ghcr.io/wave-engineering/oakandwave-workflow:edge")
    assert proc.returncode != 0, "ring must reject a non-digest (moving-tag) ref"
    combined = proc.stdout + proc.stderr
    assert "non-digest" in combined, f"expected an R-23 refusal message; got:\n{combined}"


def test_ring_requires_a_digest_ref() -> None:
    """With no DIGEST_REF at all, the ring fails loud (fail-closed), never no-ops."""
    proc = _run_ring(None)
    assert proc.returncode != 0, "ring must fail when DIGEST_REF is unset"
    assert "DIGEST_REF" in (proc.stdout + proc.stderr)


def test_ring_never_builds_locally() -> None:
    """The ring pulls by digest and must never build an image (R-23).

    A `docker build`/`buildx build` in the ring would mean testing bytes other
    than the pushed digest — the exact thing R-23 forbids.
    """
    text = RING_SCRIPT.read_text()
    assert "docker pull" in text, "ring must PULL the candidate by digest"
    assert "@sha256:" in text, "ring must guard for a digest ref (R-23)"
    assert "docker build" not in text, "ring must NOT build locally (R-23)"
    assert "buildx build" not in text, "ring must NOT build locally (R-23)"


def test_provenance_is_verified_before_smoke() -> None:
    """Signature, SBOM, permissions, and labels are all checked BEFORE smoke.

    R-24 (AC2): 'Labels, permissions, signature, and SBOM are verified before
    smoke.' Enforced mechanically off the ring's own phase markers — the smoke
    marker must appear after every provenance marker.
    """
    text = RING_SCRIPT.read_text()

    smoke_at = text.find(SMOKE_MARKER)
    assert smoke_at != -1, f"ring must emit a smoke marker {SMOKE_MARKER!r}"

    for marker in PROVENANCE_MARKERS:
        at = text.find(marker)
        assert at != -1, f"ring must emit provenance marker {marker!r}"
        assert at < smoke_at, (
            f"provenance check {marker!r} must run BEFORE the smoke suite (R-24)"
        )


def test_smoke_hard_fails_never_skips() -> None:
    """The smoke runs with OAKANDWAVE_REQUIRE_IMAGE so a red smoke blocks (AC3).

    test_image.py *skips* when the image is absent unless OAKANDWAVE_REQUIRE_IMAGE
    is set; the ring must set it, or a broken/missing candidate would pass as a
    skip instead of blocking the digest (R-05/R-23).
    """
    text = RING_SCRIPT.read_text()
    assert "OAKANDWAVE_REQUIRE_IMAGE=1" in text, (
        "smoke must be REQUIRE_IMAGE so a red/missing image fails, never skips"
    )
    assert "OAKANDWAVE_IMAGE=" in text, "smoke must target the pulled DIGEST_REF"
    assert "test_image.py" in text or "SMOKE_SUITE" in text, (
        "smoke must invoke the image toolchain oracle"
    )


def test_signature_check_is_identity_bound() -> None:
    """The cosign verify binds to a signer identity + issuer, not a bare verify.

    A bare `cosign verify` accepts ANY signature on a public digest; the security
    property is that THIS repo's image workflow signed it (deployment-verification
    §2, R-24).
    """
    text = RING_SCRIPT.read_text()
    assert "cosign verify" in text, "ring must verify the cosign signature"
    assert "--certificate-identity-regexp" in text, "signature check must bind an identity"
    assert "--certificate-oidc-issuer" in text, "signature check must bind the OIDC issuer"
    assert "cosign verify-attestation" in text, "ring must verify the SBOM attestation"
    assert "spdxjson" in text, "SBOM attestation must be the SPDX predicate"


def test_image_workflow_runs_smoke_after_build() -> None:
    """The image workflow wires the ring as a `smoke` job after `build` (R-23)."""
    text = IMAGE_WORKFLOW.read_text()
    assert "throwaway-ci-ring.sh" in text, "workflow must call the ring script"
    assert re.search(r"^\s*smoke:\s*$", text, re.MULTILINE), "workflow needs a `smoke` job"
    assert "needs: build" in text, "smoke must depend on the build job"
    # The build job must export the digest, and smoke must consume THAT digest —
    # the digest tested is the digest built (R-23), never a re-resolved tag.
    assert "digest_ref: ${{ steps.build.outputs.digest_ref }}" in text, (
        "build job must expose the pushed digest as an output"
    )
    assert "needs.build.outputs.digest_ref" in text, (
        "smoke must pull the exact digest the build job pushed"
    )


# --- Real-registry branch (skip-gated, mirrors test_image.py) -----------------


def test_ring_against_live_digest() -> None:
    """Run the whole ring against a real signed digest when one is provided.

    Set OAKANDWAVE_RING_DIGEST to a pushed+signed
    `ghcr.io/<org>/oakandwave-workflow@sha256:…` (and be logged in to ghcr) to
    exercise E2E-01 for real: provenance verification + install-from-zero + smoke.
    Absent that, this skips — the stock lane has no registry artifact to test.
    """
    digest = os.environ.get("OAKANDWAVE_RING_DIGEST")
    if not digest:
        pytest.skip("set OAKANDWAVE_RING_DIGEST to a live signed digest to run E2E-01")
    for tool in ("docker", "cosign", "python3", "curl"):
        if shutil.which(tool) is None:
            pytest.fail(f"OAKANDWAVE_RING_DIGEST set but {tool} not on PATH")

    proc = _run_ring(digest)
    assert proc.returncode == 0, (
        f"ring failed against {digest}:\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
