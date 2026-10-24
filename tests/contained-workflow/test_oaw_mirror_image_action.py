"""Oracle for #1326: the shared oaw-mirror-image action.

squawkie-talkie, flightdeck and scream-hole each copied a mirror loop that re-pushed every
tag, version tags included, and published no digest. The action's core replaces it:
- a version tag is pushed only when absent, skipped when it already names the digest, and
  refused, with nothing pushed, when it names another digest or can't be read;
- moving tags are always pushed, all in one imagetools create;
- the digest-pinned refs go to the outputs, the job summary and, optionally, the GitHub
  release, as one Images block that a rerun replaces rather than duplicates.

The core is driven for real here, against a stubbed docker and gh.
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
ACTION_DIR = REPO_ROOT / ".github" / "actions" / "oaw-mirror-image"
CORE = ACTION_DIR / "oaw-mirror-image.sh"

SRC = "ghcr.io/wave-engineering/example"
DEST = "docker.io/oakandwave/example"
DIGEST = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64
BEGIN = "<!-- oaw-mirror-image:begin -->"
END = "<!-- oaw-mirror-image:end -->"

# docker: `imagetools inspect <DEST>:<tag>` answers per STUB_TAG_<tag with . -> _>
# (absent | same | other | error, default absent); `imagetools create` logs its argv.
DOCKER_STUB = r"""#!/usr/bin/env bash
if [[ "$*" == *"imagetools create"* ]]; then
  printf '%s\n' "$*" >> "$STUB_LOG"
  exit 0
fi
ref="$4"  # buildx imagetools inspect <ref> --format ...
tag="${ref##*:}"
var="STUB_TAG_${tag//./_}"
case "${!var:-absent}" in
  absent) echo "ERROR: $ref: not found" >&2; exit 1 ;;
  same) printf '{"digest":"%s"}\n' "$STUB_DIGEST" ;;
  other) printf '{"digest":"%s"}\n' "$STUB_OTHER" ;;
  *) echo "ERROR: failed to authorize: 401 Unauthorized" >&2; exit 1 ;;
esac
"""

# gh: `release view` answers per STUB_RELEASE (absent | plain | withblock | error);
# create and edit log their argv and copy the --notes-file they were handed.
GH_STUB = r"""#!/usr/bin/env bash
printf 'gh %s\n' "$*" >> "$STUB_GH_LOG"
if [[ "$1 $2" == "release view" ]]; then
  case "$STUB_RELEASE" in
    absent) echo "release not found" >&2; exit 1 ;;
    plain) printf '%s\n' "## What's changed" "- a thing" ;;
    withblock) printf '%s\n' "## What's changed" "" "$STUB_BEGIN" "### Images" "- old" "$STUB_END" "" "tail line" ;;
    *) echo "HTTP 502: Server Error" >&2; exit 1 ;;
  esac
  exit 0
fi
prev=""
for a in "$@"; do
  [[ "$prev" == "--notes-file" ]] && cp "$a" "$STUB_NOTES"
  prev="$a"
done
exit 0
"""


class Run:
    def __init__(self, proc, creates, gh_calls, notes, outputs, summary):
        self.proc = proc
        self.creates = creates
        self.gh_calls = gh_calls
        self.notes = notes
        self.outputs = outputs
        self.summary = summary


def _run(
    tmp_path: Path,
    tags: str,
    tag_state: dict | None = None,
    release_tag: str = "",
    release: str = "absent",
) -> Run:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("docker", DOCKER_STUB), ("gh", GH_STUB)):
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    log, gh_log, notes = tmp_path / "create.log", tmp_path / "gh.log", tmp_path / "notes"
    out, summary = tmp_path / "out", tmp_path / "summary"
    env = {
        "SOURCE_DIGEST_REF": f"{SRC}@{DIGEST}",
        "TAGS": tags,
        "DEST_IMAGE": DEST,
        "RELEASE_TAG": release_tag,
        "GITHUB_OUTPUT": str(out),
        "GITHUB_STEP_SUMMARY": str(summary),
        "STUB_LOG": str(log),
        "STUB_GH_LOG": str(gh_log),
        "STUB_NOTES": str(notes),
        "STUB_DIGEST": DIGEST,
        "STUB_OTHER": OTHER,
        "STUB_RELEASE": release,
        "STUB_BEGIN": BEGIN,
        "STUB_END": END,
        "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
    }
    for tag, state in (tag_state or {}).items():
        env[f"STUB_TAG_{tag.replace('.', '_')}"] = state
    proc = subprocess.run(
        ["bash", str(CORE)], check=False, env=env, capture_output=True, text=True
    )

    def lines(p: Path) -> list[str]:
        return p.read_text().splitlines() if p.exists() else []

    raw = out.read_text() if out.exists() else ""
    outputs: dict[str, str] = {}
    if "release_refs<<" in raw:
        head, _, rest = raw.partition("release_refs<<OAW_MIRROR_EOF\n")
        outputs["release_refs"] = rest.partition("OAW_MIRROR_EOF")[0].strip()
        raw = head
    outputs.update(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    return Run(
        proc,
        lines(log),
        lines(gh_log),
        notes.read_text() if notes.exists() else "",
        outputs,
        summary.read_text() if summary.exists() else "",
    )


GHCR_TAGS = f"{SRC}:0.11.0\n{SRC}:latest\n"


class TestPush:
    def test_absent_version_and_moving_tag_go_in_one_create(self, tmp_path: Path) -> None:
        r = _run(tmp_path, GHCR_TAGS)
        assert r.proc.returncode == 0, r.proc.stderr
        assert len(r.creates) == 1, r.creates
        assert f"--tag {DEST}:0.11.0" in r.creates[0]
        assert f"--tag {DEST}:latest" in r.creates[0]
        assert r.creates[0].endswith(f"{SRC}@{DIGEST}"), "copies the exact digest"
        assert r.outputs["digest"] == DIGEST
        assert r.outputs["release_refs"] == f"{DEST}:0.11.0@{DIGEST}"
        assert f"{DEST}:0.11.0@{DIGEST}" in r.summary

    def test_version_tag_on_the_digest_is_skipped_moving_still_pushed(
        self, tmp_path: Path
    ) -> None:
        r = _run(tmp_path, GHCR_TAGS, {"0.11.0": "same"})
        assert r.proc.returncode == 0, r.proc.stderr
        assert len(r.creates) == 1
        assert f"--tag {DEST}:latest" in r.creates[0]
        assert ":0.11.0" not in r.creates[0], "a version tag is never re-pushed"
        assert r.outputs["release_refs"] == f"{DEST}:0.11.0@{DIGEST}"

    def test_nothing_to_push_runs_no_create(self, tmp_path: Path) -> None:
        r = _run(tmp_path, f"{SRC}:0.11.0\n", {"0.11.0": "same"})
        assert r.proc.returncode == 0, r.proc.stderr
        assert r.creates == []

    def test_version_tag_on_another_digest_fails_and_pushes_nothing(
        self, tmp_path: Path
    ) -> None:
        r = _run(tmp_path, GHCR_TAGS, {"0.11.0": "other"})
        assert r.proc.returncode != 0
        assert r.creates == [], "not even the moving tag"
        assert OTHER in r.proc.stderr and "never re-pushed" in r.proc.stderr

    def test_unreadable_version_tag_fails_and_pushes_nothing(self, tmp_path: Path) -> None:
        r = _run(tmp_path, GHCR_TAGS, {"0.11.0": "error"})
        assert r.proc.returncode != 0
        assert r.creates == []
        assert "can't tell whether it exists" in r.proc.stderr

    def test_moving_tags_are_never_inspected_as_versions(self, tmp_path: Path) -> None:
        # flightdeck's tag set: X.Y.Z, X.Y, X and sha-*. Only X.Y.Z is a version tag, so an
        # existing :0.11 on another digest must not block the run.
        tags = f"{SRC}:0.11.0\n{SRC}:0.11\n{SRC}:0\n{SRC}:sha-db3833e\n"
        r = _run(tmp_path, tags, {"0.11": "other", "0": "other"})
        assert r.proc.returncode == 0, r.proc.stderr
        for t in ("0.11.0", "0.11", "0", "sha-db3833e"):
            assert f"--tag {DEST}:{t} " in r.creates[0] + " "
        assert r.outputs["release_refs"] == f"{DEST}:0.11.0@{DIGEST}"

    def test_a_non_digest_source_is_refused(self, tmp_path: Path) -> None:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        proc = subprocess.run(
            ["bash", str(CORE)],
            check=False,
            env={
                "SOURCE_DIGEST_REF": f"{SRC}:latest",
                "TAGS": "latest",
                "DEST_IMAGE": DEST,
                "PATH": os.environ.get("PATH", ""),
            },
            capture_output=True,
            text=True,
        )
        assert proc.returncode != 0
        assert "digest ref" in proc.stderr


class TestRelease:
    def test_no_release_tag_never_calls_gh(self, tmp_path: Path) -> None:
        r = _run(tmp_path, GHCR_TAGS)
        assert r.proc.returncode == 0, r.proc.stderr
        assert r.gh_calls == []

    def test_missing_release_is_created_with_the_block(self, tmp_path: Path) -> None:
        r = _run(tmp_path, GHCR_TAGS, release_tag="v0.11.0", release="absent")
        assert r.proc.returncode == 0, r.proc.stderr
        create = [c for c in r.gh_calls if c.startswith("gh release create")]
        assert len(create) == 1, r.gh_calls
        assert "v0.11.0" in create[0]
        assert "--verify-tag" in create[0] and "--generate-notes" in create[0]
        assert r.notes.count(BEGIN) == 1 and r.notes.count(END) == 1
        assert f"`{DEST}:0.11.0@{DIGEST}`" in r.notes
        assert f"`{SRC}@{DIGEST}`" in r.notes

    def test_existing_release_gets_the_block_appended(self, tmp_path: Path) -> None:
        r = _run(tmp_path, GHCR_TAGS, release_tag="v0.11.0", release="plain")
        assert r.proc.returncode == 0, r.proc.stderr
        assert any(c.startswith("gh release edit v0.11.0") for c in r.gh_calls), r.gh_calls
        assert r.notes.startswith("## What's changed\n- a thing\n")
        assert r.notes.count(BEGIN) == 1
        assert f"`{DEST}:0.11.0@{DIGEST}`" in r.notes

    def test_a_rerun_replaces_the_block_instead_of_adding_one(self, tmp_path: Path) -> None:
        r = _run(tmp_path, GHCR_TAGS, release_tag="v0.11.0", release="withblock")
        assert r.proc.returncode == 0, r.proc.stderr
        assert r.notes.count(BEGIN) == 1 and r.notes.count(END) == 1
        assert "- old" not in r.notes
        assert f"`{DEST}:0.11.0@{DIGEST}`" in r.notes
        assert r.notes.startswith("## What's changed\n")
        assert r.notes.rstrip().endswith("tail line"), "text after the block survives"

    def test_unreadable_release_fails(self, tmp_path: Path) -> None:
        r = _run(tmp_path, GHCR_TAGS, release_tag="v0.11.0", release="error")
        assert r.proc.returncode != 0
        assert "could not read release" in r.proc.stderr
        assert not any("release create" in c or "release edit" in c for c in r.gh_calls)


class TestActionShape:
    @pytest.mark.skipif(yaml is None, reason="pyyaml not installed")
    def test_composite_action_runs_the_core_via_bash(self) -> None:
        doc = yaml.safe_load((ACTION_DIR / "action.yml").read_text())
        assert doc["runs"]["using"] == "composite"
        for name in ("source-digest-ref", "tags", "dest-image"):
            assert doc["inputs"][name]["required"] is True
        step = doc["runs"]["steps"][0]
        assert step["run"] == 'bash "${GITHUB_ACTION_PATH}/oaw-mirror-image.sh"'
        assert step["env"]["GH_REPO"] == "${{ github.repository }}"
        assert set(doc["outputs"]) == {"digest", "release-refs"}
