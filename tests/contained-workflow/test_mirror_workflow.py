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
        # The imagetools copy lives in the script since #1324; TestMirrorScript drives it.
        assert "mirror-oakandwave-image.sh" in text, "must mirror via the mirror script"
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
            check=False,
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


MIRROR_SCRIPT = REPO_ROOT / "scripts" / "ci" / "mirror-oakandwave-image.sh"
DIGEST = "sha256:" + "e" * 64
OTHER_DIGEST = "sha256:" + "f" * 64

# A docker stub for the mirror script's three calls. The source digest's config answers
# `--format {{json .Image}}`; the Docker Hub version tag answers `{{json .Manifest}}` per
# STUB_TAG (absent | same | other | error); `imagetools create` logs its argv and exits 0.
DOCKER_STUB = r"""#!/usr/bin/env bash
if [[ "$*" == *"imagetools create"* ]]; then
  printf '%s\n' "$*" >> "$STUB_CREATE_LOG"
  exit 0
fi
if [[ "$*" == *"{{json .Image}}"* ]]; then
  printf '%s\n' "$STUB_IMAGE_JSON"
  exit 0
fi
case "$STUB_TAG" in
  absent) echo "ERROR: docker.io/oakandwave/oakandwave-workflow:8.14.0: not found" >&2; exit 1 ;;
  same) printf '{"digest":"%s"}\n' "$STUB_DIGEST" ;;
  other) printf '{"digest":"%s"}\n' "$STUB_OTHER_DIGEST" ;;
  *) echo "ERROR: failed to authorize: 401 Unauthorized" >&2; exit 1 ;;
esac
"""


def _labels(version: str | None) -> dict:
    labels = {"org.opencontainers.image.title": "oakandwave-workflow"}
    if version is not None:
        labels["org.opencontainers.image.version"] = version
    return {"config": {"Labels": labels}}


class TestMirrorScript:
    """The mirror script, driven for real with a stubbed docker (#1324)."""

    def _run(
        self, tmp_path: Path, tag: str, image: dict | None = None
    ) -> tuple[subprocess.CompletedProcess, list[str], dict, str]:
        import json

        bindir = tmp_path / "bin"
        bindir.mkdir()
        docker = bindir / "docker"
        docker.write_text(DOCKER_STUB)
        docker.chmod(0o755)
        # A logging gh shadows the real one, which would find this checkout's origin and the
        # operator's credentials: the wrapper must never touch a release (#1326 review).
        gh_log = tmp_path / "gh.log"
        gh = bindir / "gh"
        gh.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "{gh_log}"\nexit 0\n')
        gh.chmod(0o755)
        create_log = tmp_path / "create.log"
        out = tmp_path / "gh_output"
        summary = tmp_path / "summary"
        env = {
            "SRC_DIGEST": f"{GHCR_IMAGE}@{DIGEST}",
            "DOCKERHUB_IMAGE": DOCKERHUB_IMAGE,
            "STABLE_TAG": "stable",
            "GITHUB_OUTPUT": str(out),
            "GITHUB_STEP_SUMMARY": str(summary),
            "STUB_CREATE_LOG": str(create_log),
            "STUB_IMAGE_JSON": json.dumps(image if image is not None else _labels("8.14.0")),
            "STUB_TAG": tag,
            "STUB_DIGEST": DIGEST,
            "STUB_OTHER_DIGEST": OTHER_DIGEST,
            "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
        }
        proc = subprocess.run(
            ["bash", str(MIRROR_SCRIPT)], check=False, env=env, capture_output=True, text=True
        )
        assert not gh_log.exists(), f"the wrapper called gh: {gh_log.read_text()}"
        creates = create_log.read_text().splitlines() if create_log.exists() else []
        outputs = (
            dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)
            if out.exists()
            else {}
        )
        return proc, creates, outputs, summary.read_text() if summary.exists() else ""

    def test_absent_version_tag_is_pushed_with_stable_in_one_create(self, tmp_path: Path) -> None:
        proc, creates, outputs, summary = self._run(tmp_path, "absent")
        assert proc.returncode == 0, proc.stderr
        assert len(creates) == 1, creates
        assert f"--tag {DOCKERHUB_IMAGE}:stable" in creates[0]
        assert f"--tag {DOCKERHUB_IMAGE}:8.14.0" in creates[0]
        assert creates[0].endswith(f"{GHCR_IMAGE}@{DIGEST}"), "copies the exact digest"
        assert outputs["version"] == "8.14.0"
        assert outputs["version_ref"] == f"{DOCKERHUB_IMAGE}:8.14.0@{DIGEST}"
        assert f"{DOCKERHUB_IMAGE}:8.14.0@{DIGEST}" in summary

    def test_version_tag_on_the_same_digest_is_not_repushed(self, tmp_path: Path) -> None:
        proc, creates, outputs, _ = self._run(tmp_path, "same")
        assert proc.returncode == 0, proc.stderr
        assert len(creates) == 1, creates
        assert f"--tag {DOCKERHUB_IMAGE}:stable" in creates[0]
        assert ":8.14.0" not in creates[0], "an existing version tag is never re-pushed"
        assert outputs["version_ref"] == f"{DOCKERHUB_IMAGE}:8.14.0@{DIGEST}"

    def test_version_tag_on_another_digest_fails_and_pushes_nothing(self, tmp_path: Path) -> None:
        proc, creates, _, _ = self._run(tmp_path, "other")
        assert proc.returncode != 0
        assert creates == [], "nothing is pushed, not even :stable"
        assert OTHER_DIGEST in proc.stderr and "never re-pushed" in proc.stderr

    def test_unreadable_version_tag_fails_and_pushes_nothing(self, tmp_path: Path) -> None:
        # A 401 is not "absent": pushing on it could overwrite a tag we couldn't see.
        proc, creates, _, _ = self._run(tmp_path, "error")
        assert proc.returncode != 0
        assert creates == []
        assert "can't tell whether it exists" in proc.stderr

    @pytest.mark.parametrize("version", [None, "", "v8.14.0", "8.14", "8.14.0-rc1"])
    def test_missing_or_non_release_label_fails_and_pushes_nothing(
        self, tmp_path: Path, version: str | None
    ) -> None:
        proc, creates, _, _ = self._run(tmp_path, "absent", image=_labels(version))
        assert proc.returncode != 0
        assert creates == []

    def test_multi_platform_labels_must_agree(self, tmp_path: Path) -> None:
        agree = {"linux/amd64": _labels("8.14.0"), "linux/arm64": _labels("8.14.0")}
        proc, creates, _, _ = self._run(tmp_path, "absent", image=agree)
        assert proc.returncode == 0, proc.stderr
        assert f"--tag {DOCKERHUB_IMAGE}:8.14.0" in creates[0]

        disagree = {"linux/amd64": _labels("8.14.0"), "linux/arm64": _labels("8.13.0")}
        (tmp_path / "again").mkdir()
        proc, creates, _, _ = self._run(tmp_path / "again", "absent", image=disagree)
        assert proc.returncode != 0
        assert creates == []
