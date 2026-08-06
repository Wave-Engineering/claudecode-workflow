"""Releases carry a registry tag (#1122).

The image build pushed exactly one tag — `:edge` — so v8.1.1's image was
indistinguishable from any intermediate build. Retention had no anchor (#1100's
pruner approximated release history with "the last N manifests") and rollback
meant reading OCI labels off candidate digests one at a time.

The load-bearing property is **same digest, two tags**. A retag-after-push would
leave a window where they disagree and a second thing to get wrong, so the extra
tag is applied in the same `buildx build --push` — asserted here against the
script rather than assumed.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUILD = REPO / "scripts" / "ci" / "build-oakandwave-image.sh"
BACKFILL = REPO / "scripts" / "ci" / "backfill-release-tags.sh"
WORKFLOW = REPO / ".github" / "workflows" / "oakandwave-workflow-image.yml"


def _directives(path: Path) -> str:
    return "\n".join(
        line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")
    )


def test_extra_tags_are_applied_in_the_same_build(tmp_path: Path) -> None:
    """One push, one digest, N tags. A retag-after-push would leave a window in
    which `:edge` and `:vX.Y.Z` disagree, and a second thing to get wrong.

    Drives the REAL script with a stubbed docker and asserts the flags it passed.
    A structural `"extra_tag_args" in <slice of the file>` check passed with the
    -t line deleted, which made it decorative.
    """
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
    assert "-t ghcr.io/x/oakandwave-workflow:v9.9.9" in build[0], (
        f"the version tag was not applied in the same build: {build[0]}"
    )


def test_no_extra_tags_means_no_stray_flags(tmp_path: Path) -> None:
    """An empty EXTRA_TAGS must not produce an empty `-t ''`, which buildx
    rejects — the array-expansion idiom exists for exactly that."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    argv = tmp_path / "argv.log"
    docker = bindir / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{argv}"\n'
        'if [[ "$*" == *"buildx build"* ]]; then\n'
        '  for a in "$@"; do [[ "$prev" == "--metadata-file" ]] && echo "{}" > "$a"; prev="$a"; done\n'
        "fi\n"
        "exit 0\n"
    )
    docker.chmod(0o755)
    subprocess.run(
        ["bash", str(BUILD)],
        capture_output=True, text=True, cwd=str(REPO),
        env={
            **os.environ,
            "PATH": f"{bindir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "IMAGE": "ghcr.io/x/oakandwave-workflow", "TAG": "edge", "PUSH": "false",
        },
        timeout=120,
    )
    build = [l for l in (argv.read_text() if argv.exists() else "").splitlines() if "buildx build" in l]
    assert build, "the build was never invoked"
    assert "-t  " not in build[0] and not build[0].rstrip().endswith("-t"), build[0]


def test_a_tag_push_supplies_the_version_but_dispatch_does_not() -> None:
    """A manual build is a CANDIDATE, not a release — #1063's whole point is that
    those are different acts, so dispatch must not mint a version tag."""
    body = WORKFLOW.read_text()
    m = re.search(r"EXTRA_TAGS:\s*(.+)", body)
    assert m, "the workflow does not pass EXTRA_TAGS"
    expr = m.group(1)
    assert "ref_type == 'tag'" in expr, expr
    # The false branch must be empty, not some default tag.
    assert re.search(r"\|\|\s*''", expr), expr


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
