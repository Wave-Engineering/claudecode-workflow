"""read-oci-version.sh: the one X.Y.Z version-label rule for promotion and mirroring (#1359).

Driven for real with a stub docker first on PATH. No registry is reached.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "read-oci-version.sh"
REF = "ghcr.io/wave-engineering/oakandwave-workflow@sha256:" + "e" * 64

# Answers `{{json .Image}}` with STUB_IMAGE_JSON, and logs every call.
_DOCKER_STUB = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$STUB_DOCKER_LOG"
if [[ "$*" == *"{{json .Image}}"* ]]; then
  printf '%s\n' "$STUB_IMAGE_JSON"
  exit 0
fi
exit 1
"""


def _config(version: str | None) -> dict:
    labels = {"org.opencontainers.image.title": "oakandwave-workflow"}
    if version is not None:
        labels["org.opencontainers.image.version"] = version
    return {"config": {"Labels": labels}}


def _run(tmp_path: Path, ref: str, image: dict) -> tuple[subprocess.CompletedProcess, list[str]]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    docker = bindir / "docker"
    docker.write_text(_DOCKER_STUB)
    docker.chmod(0o755)
    log = tmp_path / "docker.log"
    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
        "STUB_IMAGE_JSON": json.dumps(image),
        "STUB_DOCKER_LOG": str(log),
    }
    proc = subprocess.run(["bash", str(SCRIPT), ref], capture_output=True, text=True, env=env, timeout=30)
    return proc, log.read_text().splitlines() if log.exists() else []


def test_script_is_executable() -> None:
    assert os.access(SCRIPT, os.X_OK)


@pytest.mark.parametrize(
    "image",
    [_config("8.15.0"), {"linux/amd64": _config("8.15.0"), "linux/arm64": _config("8.15.0")}],
    ids=["single-config", "platform-map"],
)
def test_read_oci_version_accepts_a_release_label(tmp_path: Path, image: dict) -> None:
    proc, _ = _run(tmp_path, REF, image)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "8.15.0\n"


@pytest.mark.parametrize(
    "image",
    [
        _config("8.14.0-3-gabc"),
        _config("0.0.0-dev"),
        _config("v8.1.0"),
        _config(None),
        {"linux/amd64": _config("8.15.0"), "linux/arm64": _config("8.14.0")},
    ],
    ids=["git-describe", "dev", "v-prefixed", "missing", "platforms-disagree"],
)
def test_read_oci_version_refuses_non_release_labels(tmp_path: Path, image: dict) -> None:
    proc, _ = _run(tmp_path, REF, image)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert proc.stdout == ""
    assert "[!]" in proc.stderr


def test_read_oci_version_refuses_a_moving_ref(tmp_path: Path) -> None:
    proc, calls = _run(tmp_path, "ghcr.io/wave-engineering/oakandwave-workflow:edge", _config("8.15.0"))
    assert proc.returncode == 1
    assert "not a digest ref" in proc.stderr
    assert calls == [], f"docker was called for a moving ref: {calls}"
