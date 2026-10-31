"""Releases carry a registry tag (#1122).

The image build pushed exactly one tag — `:edge` — so v8.1.1's image was
indistinguishable from any intermediate build. Retention had no anchor (#1100's
pruner approximated release history with "the last N manifests") and rollback
meant reading OCI labels off candidate digests one at a time.

The version tag is written once (#1359). It used to ride the build as a second
`-t`, so re-running the build job on a `v*` tag rebuilt the image and silently
moved GHCR `:vX.Y.Z` to the new digest. Now the build pushes only `:edge`, and
the oaw-mirror-image action writes `:vX.Y.Z` on that exact digest, refusing if
the tag already names another one. The tests below drive the real build script
and the real action core with a stubbed docker.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BUILD = REPO / "scripts" / "ci" / "build-oakandwave-image.sh"
BACKFILL = REPO / "scripts" / "ci" / "backfill-release-tags.sh"
WORKFLOW = REPO / ".github" / "workflows" / "oakandwave-workflow-image.yml"
MIRROR_CORE = REPO / ".github" / "actions" / "oaw-mirror-image" / "oaw-mirror-image.sh"
GHCR = "ghcr.io/wave-engineering/oakandwave-workflow"
DIGEST = "sha256:" + "e" * 64
OTHER = "sha256:" + "f" * 64
V_REGEX = r"^v[0-9]+\.[0-9]+\.[0-9]+$"


def _directives(path: Path) -> str:
    return "\n".join(
        line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")
    )


def _build_steps() -> list[dict]:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["build"]["steps"]


def _version_tag_step() -> dict:
    steps = [s for s in _build_steps() if s.get("uses") == "./.github/actions/oaw-mirror-image"]
    assert len(steps) == 1, f"expected one oaw-mirror-image step in job build, found {len(steps)}"
    return steps[0]


def test_ghcr_version_tag_goes_through_oaw_mirror_image() -> None:
    steps = _build_steps()
    step = _version_tag_step()
    assert step["if"] == "github.ref_type == 'tag'"
    assert step["with"] == {
        "source-digest-ref": "${{ steps.build.outputs.digest_ref }}",
        "tags": "${{ github.ref_name }}",
        "dest-image": "${{ env.IMAGE }}",
        "immutable-tag-regex": V_REGEX,
    }
    names = [s.get("id") or s.get("name", "") for s in steps]
    at = steps.index(step)
    build_at = names.index("build")
    sign_at = next(i for i, s in enumerate(steps) if s.get("name", "").startswith("Sign"))
    assert build_at < sign_at < at, "the version tag must be written after signing, so it only names a signed digest"
    assert not [s for s in steps if "EXTRA_TAGS" in (s.get("env") or {})], "a step still passes EXTRA_TAGS"


def _mirror(tmp_path: Path, tag_state: str) -> tuple[subprocess.CompletedProcess, list[str], str]:
    """Run the action core for TAGS=v9.9.9 under the v regex. ``tag_state`` is what GHCR says
    :v9.9.9 names: ``absent`` or ``other``."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "create.log"
    docker = bindir / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"imagetools create"* ]]; then printf "%s\\n" "$*" >> "$STUB_LOG"; exit 0; fi\n'
        'case "$STUB_TAG" in\n'
        '  absent) echo "ERROR: $STUB_REF: not found" >&2; exit 1 ;;\n'
        '  other) printf \'{"digest":"%s"}\\n\' "$STUB_OTHER" ;;\n'
        "esac\n"
    )
    docker.chmod(0o755)
    out = tmp_path / "gh_output"
    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
        "SOURCE_DIGEST_REF": f"{GHCR}@{DIGEST}",
        "TAGS": "v9.9.9",
        "DEST_IMAGE": GHCR,
        "IMMUTABLE_TAG_REGEX": V_REGEX,
        "GITHUB_OUTPUT": str(out),
        "STUB_LOG": str(log),
        "STUB_TAG": tag_state,
        "STUB_REF": f"{GHCR}:v9.9.9",
        "STUB_OTHER": OTHER,
    }
    env.pop("GITHUB_STEP_SUMMARY", None)
    proc = subprocess.run(["bash", str(MIRROR_CORE)], capture_output=True, text=True, env=env, timeout=30)
    creates = log.read_text().splitlines() if log.exists() else []
    return proc, creates, out.read_text() if out.exists() else ""


def test_v_prefixed_version_tag_is_refused_when_it_names_another_digest(tmp_path: Path) -> None:
    proc, creates, _ = _mirror(tmp_path, "other")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "a version tag is never re-pushed" in proc.stderr
    assert creates == [], f"a v-prefixed version tag was moved: {creates}"


def test_v_prefixed_version_tag_is_pushed_when_absent(tmp_path: Path) -> None:
    proc, creates, out = _mirror(tmp_path, "absent")
    assert proc.returncode == 0, proc.stderr
    assert creates == [f"buildx imagetools create --tag {GHCR}:v9.9.9 {GHCR}@{DIGEST}"], creates
    assert f"{GHCR}:v9.9.9@{DIGEST}" in out, out


def test_build_pushes_only_the_moving_tag(tmp_path: Path) -> None:
    """Drives the REAL build script with a stubbed docker. EXTRA_TAGS is still set in the
    environment, to prove nothing reads it any more."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    argv = tmp_path / "argv.log"
    docker = bindir / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{argv}"\n'
        # buildx build must leave a metadata file behind or the script bails.
        'if [[ "$*" == *"buildx build"* ]]; then\n'
        '  for a in "$@"; do [[ "$prev" == "--metadata-file" ]] && echo "{}" > "$a"; prev="$a"; done\n'
        "fi\n"
        "exit 0\n"
    )
    docker.chmod(0o755)

    proc = subprocess.run(
        ["bash", str(BUILD)],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        env={
            **os.environ,
            "PATH": f"{bindir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "IMAGE": "ghcr.io/x/oakandwave-workflow",
            "TAG": "edge",
            "EXTRA_TAGS": "v9.9.9",
            "PUSH": "false",
        },
        timeout=120,
    )
    calls = argv.read_text() if argv.exists() else ""
    build = [l for l in calls.splitlines() if "buildx build" in l]
    assert build, f"the build was never invoked: {proc.stdout}{proc.stderr}{calls}"
    assert "-t ghcr.io/x/oakandwave-workflow:edge" in build[0], build[0]
    assert ":v9.9.9" not in build[0], f"the build pushed a version tag: {build[0]}"
    assert build[0].count(" -t ") == 1, build[0]


def test_a_tag_push_supplies_the_version_but_dispatch_does_not() -> None:
    """A manual build is a CANDIDATE, not a release — #1063's whole point is that
    those are different acts, so dispatch must not mint a version tag."""
    assert _version_tag_step()["if"] == "github.ref_type == 'tag'"


def test_the_backfill_reads_the_version_from_the_image() -> None:
    """A hand-maintained digest→version list is a second source of truth that can
    disagree with the artifact, silently. The image already asserts its own
    version via OCI labels."""
    body = _directives(BACKFILL)
    assert "org.opencontainers.image.version" in body
    # And only exact releases: git describe yields 8.2.0-4-g3a7f124 off-tag, which
    # is a candidate, not a release.
    assert r"^[0-9]+\.[0-9]+\.[0-9]+$" in body


def test_the_backfill_excludes_index_children(tmp_path: Path) -> None:
    """A release digest is an INDEX; its children inherit the same version label,
    so a naive pass proposes each tag twice and the second write wins — leaving
    `:v8.1.0` pointing at an attestation manifest rather than the index a profile
    would pin. Caught by the real dry run, where every version appeared twice.

    Behavioural: an earlier structural check (`"children" in body`) passed with
    the filter replaced by `true ||`, which made it decorative.
    """
    parent = "sha256:" + "a" * 64
    child = "sha256:" + "b" * 64
    bindir = tmp_path / "bin"
    bindir.mkdir()

    gh = bindir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\t\\n%s\\t\\n" "{parent}" "{child}"\n'
    )
    gh.chmod(0o755)

    docker = bindir / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        'ref="${!#}"; digest="${ref##*@}"\n'
        'if [[ "$*" == *"--raw"* ]]; then\n'
        f'  if [[ "$digest" == "{parent}" ]]; then\n'
        f'    echo \'{{"manifests":[{{"digest":"{child}"}}]}}\'\n'
        "  else echo '{}'; fi\n"
        "  exit 0\n"
        "fi\n"
        # Both parent and child claim the same version label.
        'if [[ "$*" == *"json .Image"* ]]; then\n'
        '  echo \'{"config":{"Labels":{"org.opencontainers.image.version":"9.9.9"}}}\'\n'
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )
    docker.chmod(0o755)

    proc = subprocess.run(
        ["bash", str(BACKFILL)],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{bindir}:{os.environ.get('PATH', '/usr/bin:/bin')}"},
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # Exactly one proposal — the index. Two means the child would steal the tag.
    assert proc.stdout.count(":v9.9.9") == 1, proc.stdout
    assert parent[:19] in proc.stdout, proc.stdout
    assert child[:19] not in proc.stdout, f"a child was proposed for the release tag: {proc.stdout}"


def test_the_backfill_is_dry_run_by_default() -> None:
    body = _directives(BACKFILL)
    assert "APPLY=false" in body
    assert "DRY RUN" in BACKFILL.read_text()


def test_retag_never_rebuilds() -> None:
    """R-23: the digest tested is the digest promoted. `imagetools create` points
    a new tag at an existing digest; a rebuild would mint a different one."""
    body = _directives(BACKFILL)
    assert "imagetools create" in body
    assert "buildx build" not in body, "the backfill must not build anything"


def test_scripts_are_executable() -> None:
    for s in (BUILD, BACKFILL):
        assert os.access(s, os.X_OK), f"{s} must be executable"


def test_the_build_script_still_parses() -> None:
    assert subprocess.run(["bash", "-n", str(BUILD)]).returncode == 0
    assert subprocess.run(["bash", "-n", str(BACKFILL)]).returncode == 0
