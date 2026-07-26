"""Oracle for Story 2.1 (#966) — the CI image pipeline stamps the required OCI
provenance and wires the sign/SBOM/coverage plumbing (R-24, R-06 / DM-05, DM-06).

The authoritative end-to-end proof is E2E-01 (Story 2.2): pull the pushed digest
from ghcr and inspect its labels/signature/SBOM. That cannot run in the stock
pytest lane (no ghcr push, no ~10 GB image), so this module verifies the two
halves that *can* be checked hermetically:

1. ``test_oci_labels`` (the story's named oracle) — drives the single source of
   truth for the provenance labels (``scripts/ci/oakandwave-oci-labels.sh``) with
   a fixture environment and asserts every R-24 label key is present with a sane
   value. Because the build script stamps *these exact lines* as ``docker build
   --label`` args, verifying the producer verifies what lands on the image.

2. Wiring guards — the sign/SBOM script and the workflows are parsed to prove the
   cosign signature, syft SBOM, and coverage-regardless-of-gates plumbing are
   actually connected (config exists != config works, at the unit tier).

A real-image ``docker inspect`` branch (skip-gated exactly like ``test_image.py``)
asserts the static labels the Dockerfile bakes, when the image happens to exist.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LABELS_SCRIPT = REPO_ROOT / "scripts" / "ci" / "oakandwave-oci-labels.sh"
BUILD_SCRIPT = REPO_ROOT / "scripts" / "ci" / "build-oakandwave-image.sh"
SIGN_SCRIPT = REPO_ROOT / "scripts" / "ci" / "sign-oakandwave-image.sh"
IMAGE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "oakandwave-workflow-image.yml"
VALIDATE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "validate.yml"

# The provenance facts R-24 mandates: semver, source repo, git revision, build
# timestamp. Expressed as the canonical OCI label keys the image must carry.
REQUIRED_OCI_LABEL_KEYS = (
    "org.opencontainers.image.version",  # semver
    "org.opencontainers.image.source",  # source repo
    "org.opencontainers.image.revision",  # git revision
    "org.opencontainers.image.created",  # build timestamp
)


def _run_labels_script(env_overrides: dict[str, str]) -> dict[str, str]:
    """Run the labels script with a clean-ish env and parse `key=value` lines."""
    env = dict(os.environ)
    # Drop any ambient provenance env so the fixture is deterministic.
    for k in (
        "OAKANDWAVE_VERSION",
        "OAKANDWAVE_SOURCE",
        "OAKANDWAVE_CREATED",
        "GIT_REVISION",
        "GITHUB_SHA",
        "GITHUB_REPOSITORY",
    ):
        env.pop(k, None)
    env.update(env_overrides)

    proc = subprocess.run(
        ["bash", str(LABELS_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, f"labels script failed:\n{proc.stderr}"

    labels: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        labels[key] = value
    return labels


def test_oci_labels() -> None:
    """The provenance producer emits every required OCI label with a sane value.

    Feeds a fully-specified fixture environment so each of the four R-24 facts is
    exercised end-to-end: the semver, source, revision, and timestamp we pass must
    reappear verbatim under the canonical OCI keys.
    """
    labels = _run_labels_script(
        {
            "OAKANDWAVE_VERSION": "v2.4.1",
            "GITHUB_SHA": "0123456789abcdef0123456789abcdef01234567",
            "GITHUB_REPOSITORY": "Wave-Engineering/claudecode-workflow",
            "OAKANDWAVE_CREATED": "2026-07-22T12:00:00Z",
        }
    )

    for key in REQUIRED_OCI_LABEL_KEYS:
        assert key in labels, f"missing required OCI label {key!r}; got {sorted(labels)}"
        assert labels[key], f"OCI label {key!r} is empty"

    # The leading `v` is stripped — the OCI version label is bare semver.
    assert labels["org.opencontainers.image.version"] == "2.4.1"
    assert (
        labels["org.opencontainers.image.revision"]
        == "0123456789abcdef0123456789abcdef01234567"
    )
    # The source URL is lowercased (#1038): GITHUB_REPOSITORY carries the org's capitals
    # ("Wave-Engineering"), but the label — like the image path — must be lowercase so the
    # Docker Hub mirror and the OaW lowercase-everywhere convention hold. github.com paths
    # are case-insensitive, so this resolves to the identical repo.
    assert (
        labels["org.opencontainers.image.source"]
        == "https://github.com/wave-engineering/claudecode-workflow"
    ), f"source must be lowercased; got {labels['org.opencontainers.image.source']!r}"
    assert labels["org.opencontainers.image.created"] == "2026-07-22T12:00:00Z"


def test_oci_labels_have_failsafe_fallbacks() -> None:
    """With no provenance env at all, the producer still emits every key non-empty.

    Provenance must never silently drop a label just because CI forgot to export a
    variable — a fail-safe default (git describe / HEAD / origin / now) fills each.
    """
    labels = _run_labels_script({})
    for key in REQUIRED_OCI_LABEL_KEYS:
        assert labels.get(key), f"fallback did not populate {key!r}: {labels}"


def test_build_script_stamps_labels_from_the_producer() -> None:
    """The build script sources its --label args from the single-source producer.

    Guards against a drift where the pipeline hand-rolls labels that diverge from
    what the oracle checks.
    """
    text = BUILD_SCRIPT.read_text()
    assert "oakandwave-oci-labels.sh" in text, "build script must call the labels producer"
    assert "--label" in text, "build script must pass labels to docker build"
    assert "--push" in text, "build script must push to the registry (R-05)"
    assert "containerimage.digest" in text, "build script must capture the pushed digest (R-23)"


def test_sign_script_wires_cosign_and_syft() -> None:
    """The sign step attaches BOTH a cosign signature and a syft SBOM (R-24, AC2)."""
    text = SIGN_SCRIPT.read_text()
    assert "cosign sign" in text, "must attach a cosign signature"
    assert "syft " in text, "must generate a syft SBOM"
    assert "cosign attest" in text, "must attest the SBOM to the digest"
    # The signature/SBOM must bind to the immutable digest, never a moving tag.
    assert "@sha256:" in text, "sign script must guard for a digest ref (R-23)"


def test_image_workflow_runs_sign_after_build() -> None:
    """The image workflow builds then signs, keyless via OIDC (id-token: write)."""
    text = IMAGE_WORKFLOW.read_text()
    assert "build-oakandwave-image.sh" in text, "workflow must call the build script"
    assert "sign-oakandwave-image.sh" in text, "workflow must call the sign script"
    assert "id-token: write" in text, "keyless cosign needs OIDC token permission"
    assert "packages: write" in text, "pushing to ghcr needs packages: write"


def test_coverage_uploaded_regardless_of_repo_gates() -> None:
    """Coverage + JUnit are emitted and uploaded even when the suite is red (DM-06).

    R-06/DM-06 call coverage a completeness signal reported *regardless of repo
    gates*: the report env is wired and the upload runs `if: always()`.
    """
    text = VALIDATE_WORKFLOW.read_text()
    assert "CC_TEST_REPORTS_DIR" in text, "test run must be told to emit reports"
    assert "pytest-cov" in text, "coverage report needs pytest-cov installed"
    assert "if: always()" in text, "artifact upload must run regardless of the test gate"
    assert "coverage.xml" in text and "junit.xml" in text, "must upload DM-05 + DM-06"


# --- Real-image branch (skip-gated, mirrors test_image.py) --------------------

DEFAULT_IMAGE = "oakandwave-workflow:edge"


def _resolve_image_or_skip() -> tuple[str, str]:
    docker = shutil.which("docker")
    require = bool(os.environ.get("OAKANDWAVE_REQUIRE_IMAGE"))
    if docker is None:
        msg = "docker binary not found on PATH"
        pytest.fail(msg) if require else pytest.skip(msg)
    ref = os.environ.get("OAKANDWAVE_IMAGE", DEFAULT_IMAGE)
    present = subprocess.run(
        [docker, "image", "inspect", ref], capture_output=True, text=True
    )
    if present.returncode != 0:
        msg = f"image {ref!r} not built locally"
        pytest.fail(msg) if require else pytest.skip(msg)
    return docker, ref


def test_built_image_carries_static_labels() -> None:
    """When the image is present, it carries the Dockerfile's static OCI labels.

    The dynamic provenance (version/revision/created) is stamped by CI at
    build-push time (test_oci_labels covers that producer); the title/source/base
    labels are baked in the Dockerfile and must be inspectable on any local build.
    """
    docker, ref = _resolve_image_or_skip()
    fmt = "{{json .Config.Labels}}"
    proc = subprocess.run(
        [docker, "image", "inspect", "--format", fmt, ref],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "org.opencontainers.image.title" in proc.stdout
    assert "org.opencontainers.image.source" in proc.stdout
