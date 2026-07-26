"""Oracle for #1038 — the Docker Hub :stable mirror + re-sign, moved into GitHub Actions.

Promotion is operator-run (no OIDC), so keyless cosign can't re-sign there; and
`cosign copy` is deprecated in the pinned cosign v2.6.4. So the OIDC half — mirror the
already-promoted GHCR :stable to docker.io/oakandwave and RE-SIGN it — runs in a GHA
`workflow_dispatch` job (id-token: write). The mechanical gate + edge->stable retag stay
operator-side; this workflow only ever touches an ALREADY-promoted :stable.

Two things proved here:
  1. The workflow's load-bearing shape (trigger, id-token, mirror target, re-sign, and the
     safety invariant that it NEVER touches :edge).
  2. resolve-stable-digest.sh derives the Docker Hub digest ref from the same content sha
     and rejects a non-digest pin — exercised hermetically (no docker/registry needed).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

try:
    import yaml
except ImportError:  # pragma: no cover - yaml is a test dep
    yaml = None

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "oakandwave-workflow-mirror.yml"
RESOLVE_SCRIPT = REPO_ROOT / "scripts" / "ci" / "resolve-stable-digest.sh"

GHCR_IMAGE = "ghcr.io/wave-engineering/oakandwave-workflow"
DOCKERHUB_IMAGE = "docker.io/oakandwave/oakandwave-workflow"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


class TestMirrorWorkflowShape:
    def test_workflow_exists(self) -> None:
        assert WORKFLOW.exists(), f"mirror workflow not found at {WORKFLOW}"

    @pytest.mark.skipif(yaml is None, reason="pyyaml not installed")
    def test_workflow_dispatch_and_oidc(self) -> None:
        doc = yaml.safe_load(_workflow_text())
        # `on:` parses to the truthy key True in YAML 1.1 — accept either spelling.
        triggers = doc.get("on", doc.get(True))
        assert "workflow_dispatch" in triggers, "must be workflow_dispatch (operator-triggered)"
        assert doc["permissions"]["id-token"] == "write", (
            "keyless cosign re-sign needs id-token: write (the whole reason this is in GHA)"
        )

    def test_mirrors_to_dockerhub_and_resigns(self) -> None:
        text = _workflow_text()
        assert DOCKERHUB_IMAGE in text, "must mirror to docker.io/oakandwave/oakandwave-workflow"
        assert "resolve-stable-digest.sh" in text, "must resolve the :stable digest"
        assert "imagetools create" in text, "must mirror via imagetools create"
        assert "sign-oakandwave-image.sh" in text, "must re-sign the mirrored Docker Hub digest"
        assert "dockerhub_digest_ref" in text, "re-sign must target the Docker Hub digest ref"

    def test_never_touches_edge(self) -> None:
        # Safety invariant: only an already-promoted :stable reaches the public brand.
        # Check the workflow LOGIC (YAML comments stripped) — an explanatory comment that
        # names :edge to say we never use it is fine; an actual :edge tag/var is not.
        code = "\n".join(line.split("#", 1)[0] for line in _workflow_text().splitlines())
        assert ":edge" not in code, "the mirror workflow logic must never reference a :edge tag"
        assert "edge" not in code, (
            "the mirror workflow logic must carry no edge tag/var — only the promoted :stable"
        )


class TestResolveStableDigest:
    def _run(self, env_extra: dict) -> subprocess.CompletedProcess:
        env = {
            "GHCR_IMAGE": GHCR_IMAGE,
            "DOCKERHUB_IMAGE": DOCKERHUB_IMAGE,
            "STABLE_TAG": "stable",
            "PATH": os.environ.get("PATH", ""),
            **env_extra,
        }
        return subprocess.run(
            ["bash", str(RESOLVE_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
        )

    def test_pinned_digest_derives_matching_dockerhub_ref(self, tmp_path: Path) -> None:
        # With an explicit digest pin, no registry access is needed; assert the Docker Hub
        # ref is the same content sha under the oakandwave repo (R-23: same digest published).
        out = tmp_path / "gh_output"
        sha = "sha256:" + "a" * 64
        proc = self._run(
            {"STABLE_DIGEST_INPUT": f"{GHCR_IMAGE}@{sha}", "GITHUB_OUTPUT": str(out)}
        )
        assert proc.returncode == 0, proc.stderr
        outputs = dict(
            line.split("=", 1) for line in out.read_text().splitlines() if "=" in line
        )
        assert outputs["digest_ref"] == f"{GHCR_IMAGE}@{sha}"
        assert outputs["dockerhub_digest_ref"] == f"{DOCKERHUB_IMAGE}@{sha}"

    def test_rejects_a_non_digest_pin(self, tmp_path: Path) -> None:
        # A moving tag can't be signed (sign-oakandwave-image.sh refuses non-digest refs);
        # the resolver must reject it up front rather than pass a tag downstream.
        proc = self._run(
            {"STABLE_DIGEST_INPUT": f"{GHCR_IMAGE}:stable", "GITHUB_OUTPUT": str(tmp_path / "o")}
        )
        assert proc.returncode != 0, "a non-digest pin must be rejected"
        assert "digest ref" in proc.stderr
