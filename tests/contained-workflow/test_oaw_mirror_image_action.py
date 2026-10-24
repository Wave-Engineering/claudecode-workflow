"""Oracle for #1326: the shared oaw-mirror-image and oaw-release-images actions.

squawkie-talkie, flightdeck and scream-hole each copied a mirror loop that re-pushed every
tag, version tags included, and published no digest. Two actions replace it:
- oaw-mirror-image: a version tag is pushed only when absent, skipped when it already
  names the digest, and refused, with nothing pushed, when it names another digest or
  can't be read. Moving tags are always pushed, all in one imagetools create. It touches
  no GitHub release.
- oaw-release-images, run after signing: the digest-pinned refs go into the GitHub
  release as one Images block that a rerun replaces rather than duplicates.

Both cores are driven for real here, against a stubbed docker and gh.
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
MIRROR_DIR = REPO_ROOT / ".github" / "actions" / "oaw-mirror-image"
RELEASE_DIR = REPO_ROOT / ".github" / "actions" / "oaw-release-images"
MIRROR_CORE = MIRROR_DIR / "oaw-mirror-image.sh"
RELEASE_CORE = RELEASE_DIR / "oaw-release-images.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "oakandwave-workflow-mirror.yml"

SRC = "ghcr.io/wave-engineering/example"
DEST = "docker.io/oakandwave/example"
DIGEST = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64
BEGIN = "<!-- oaw-mirror-image:begin -->"
END = "<!-- oaw-mirror-image:end -->"
REF = f"{DEST}:0.11.0@{DIGEST}"

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

# gh: the Nth `release view` answers per the Nth word of STUB_RELEASE (absent | plain |
# withblock | crlf | inline | error); `release create` exits per STUB_CREATE (ok | exists).
# create and edit log their argv and copy the --notes-file they were handed.
GH_STUB = r"""#!/usr/bin/env bash
printf 'gh %s\n' "$*" >> "$STUB_GH_LOG"
if [[ "$1 $2" == "release view" ]]; then
  n=$(grep -c '^gh release view' "$STUB_GH_LOG")
  read -r -a states <<< "$STUB_RELEASE"
  state="${states[$((n - 1))]:-${states[-1]}}"
  case "$state" in
    absent) echo "release not found" >&2; exit 1 ;;
    plain) printf '%s\n' "## What's changed" "- a thing" ;;
    withblock) printf '%s\n' "## What's changed" "" "$STUB_BEGIN" "### Images" "- old" "$STUB_END" "" "tail line" ;;
    crlf) printf '%s\r\n' "## What's changed" "$STUB_BEGIN" "- old" "$STUB_END" "tail line" ;;
    inline) printf '%s\n' "## What's changed" "see $STUB_BEGIN here" "- old" "$STUB_END" ;;
    *) echo "HTTP 502: Server Error" >&2; exit 1 ;;
  esac
  exit 0
fi
prev=""
for a in "$@"; do
  [[ "$prev" == "--notes-file" ]] && cp "$a" "$STUB_NOTES"
  prev="$a"
done
if [[ "$1 $2" == "release create" && "${STUB_CREATE:-ok}" == "exists" ]]; then
  echo "HTTP 422: Validation Failed (already_exists)" >&2; exit 1
fi
exit 0
"""


def _stubs(tmp_path: Path) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("docker", DOCKER_STUB), ("gh", GH_STUB)):
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    return bindir


def _lines(p: Path) -> list[str]:
    return p.read_text().splitlines() if p.exists() else []


class Mirror:
    def __init__(self, proc, creates, gh_calls, outputs, summary):
        self.proc, self.creates, self.gh_calls = proc, creates, gh_calls
        self.outputs, self.summary = outputs, summary


def _mirror(tmp_path: Path, tags: str, tag_state: dict | None = None) -> Mirror:
    bindir = _stubs(tmp_path)
    log, gh_log = tmp_path / "create.log", tmp_path / "gh.log"
    out, summary = tmp_path / "out", tmp_path / "summary"
    env = {
        "SOURCE_DIGEST_REF": f"{SRC}@{DIGEST}",
        "TAGS": tags,
        "DEST_IMAGE": DEST,
        "GITHUB_OUTPUT": str(out),
        "GITHUB_STEP_SUMMARY": str(summary),
        "STUB_LOG": str(log),
        "STUB_GH_LOG": str(gh_log),
        "STUB_DIGEST": DIGEST,
        "STUB_OTHER": OTHER,
        "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
    }
    for tag, state in (tag_state or {}).items():
        env[f"STUB_TAG_{tag.replace('.', '_')}"] = state
    proc = subprocess.run(
        ["bash", str(MIRROR_CORE)], check=False, env=env, capture_output=True, text=True
    )
    raw = out.read_text() if out.exists() else ""
    outputs: dict[str, str] = {}
    if "release_refs<<" in raw:
        head, _, rest = raw.partition("release_refs<<OAW_MIRROR_EOF\n")
        outputs["release_refs"] = rest.partition("OAW_MIRROR_EOF")[0]
        raw = head
    outputs.update(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    return Mirror(
        proc,
        _lines(log),
        _lines(gh_log),
        outputs,
        summary.read_text() if summary.exists() else "",
    )


GHCR_TAGS = f"{SRC}:0.11.0\n{SRC}:latest\n"


class TestMirror:
    def test_absent_version_and_moving_tag_go_in_one_create(self, tmp_path: Path) -> None:
        r = _mirror(tmp_path, GHCR_TAGS)
        assert r.proc.returncode == 0, r.proc.stderr
        assert len(r.creates) == 1, r.creates
        assert f"--tag {DEST}:0.11.0" in r.creates[0]
        assert f"--tag {DEST}:latest" in r.creates[0]
        assert r.creates[0].endswith(f"{SRC}@{DIGEST}"), "copies the exact digest"
        assert r.outputs["digest"] == DIGEST
        assert r.outputs["release_refs"] == f"{REF}\n"
        assert REF in r.summary
        assert r.gh_calls == [], "the mirror never touches a release"

    def test_version_tag_on_the_digest_is_skipped_moving_still_pushed(
        self, tmp_path: Path
    ) -> None:
        r = _mirror(tmp_path, GHCR_TAGS, {"0.11.0": "same"})
        assert r.proc.returncode == 0, r.proc.stderr
        assert len(r.creates) == 1
        assert f"--tag {DEST}:latest" in r.creates[0]
        assert ":0.11.0" not in r.creates[0], "a version tag is never re-pushed"
        assert r.outputs["release_refs"] == f"{REF}\n"

    def test_nothing_to_push_runs_no_create(self, tmp_path: Path) -> None:
        r = _mirror(tmp_path, f"{SRC}:0.11.0\n", {"0.11.0": "same"})
        assert r.proc.returncode == 0, r.proc.stderr
        assert r.creates == []

    def test_only_moving_tags_leaves_release_refs_empty(self, tmp_path: Path) -> None:
        r = _mirror(tmp_path, f"{SRC}:latest\n{SRC}:latest\n")
        assert r.proc.returncode == 0, r.proc.stderr
        assert r.creates[0].count("--tag") == 1, "duplicates are dropped"
        assert r.outputs["release_refs"] == "", "no blank line for an empty list"
        assert r.summary == ""

    def test_version_tag_on_another_digest_fails_and_pushes_nothing(
        self, tmp_path: Path
    ) -> None:
        r = _mirror(tmp_path, GHCR_TAGS, {"0.11.0": "other"})
        assert r.proc.returncode != 0
        assert r.creates == [], "not even the moving tag"
        assert OTHER in r.proc.stderr and "never re-pushed" in r.proc.stderr

    def test_unreadable_version_tag_fails_and_pushes_nothing(self, tmp_path: Path) -> None:
        r = _mirror(tmp_path, GHCR_TAGS, {"0.11.0": "error"})
        assert r.proc.returncode != 0
        assert r.creates == []
        assert "can't tell whether it exists" in r.proc.stderr

    def test_moving_tags_are_never_inspected_as_versions(self, tmp_path: Path) -> None:
        # flightdeck's tag set: X.Y.Z, X.Y, X and sha-*. Only X.Y.Z is a version tag, so an
        # existing :0.11 on another digest must not block the run.
        tags = f"{SRC}:0.11.0\n{SRC}:0.11\n{SRC}:0\n{SRC}:sha-db3833e\n"
        r = _mirror(tmp_path, tags, {"0.11": "other", "0": "other"})
        assert r.proc.returncode == 0, r.proc.stderr
        for t in ("0.11.0", "0.11", "0", "sha-db3833e"):
            assert f"--tag {DEST}:{t} " in r.creates[0] + " "
        assert r.outputs["release_refs"] == f"{REF}\n"

    def test_comma_separated_tags_are_refused(self, tmp_path: Path) -> None:
        r = _mirror(tmp_path, f"{SRC}:0.11.0,{SRC}:latest")
        assert r.proc.returncode != 0
        assert r.creates == []
        assert "newline-separated" in r.proc.stderr

    def test_a_non_digest_source_is_refused(self, tmp_path: Path) -> None:
        proc = subprocess.run(
            ["bash", str(MIRROR_CORE)],
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


class Release:
    def __init__(self, proc, gh_calls, notes):
        self.proc, self.gh_calls, self.notes = proc, gh_calls, notes

    def edits(self) -> list[str]:
        return [c for c in self.gh_calls if c.startswith(("gh release edit", "gh release create"))]


def _release(
    tmp_path: Path, release: str, refs: str = f"{REF}\n", create: str = "ok"
) -> Release:
    bindir = _stubs(tmp_path)
    gh_log, notes = tmp_path / "gh.log", tmp_path / "notes"
    gh_log.touch()
    env = {
        "RELEASE_TAG": "v0.11.0",
        "RELEASE_REFS": refs,
        "SOURCE_DIGEST_REF": f"{SRC}@{DIGEST}",
        "STUB_GH_LOG": str(gh_log),
        "STUB_NOTES": str(notes),
        "STUB_RELEASE": release,
        "STUB_CREATE": create,
        "STUB_BEGIN": BEGIN,
        "STUB_END": END,
        "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
    }
    proc = subprocess.run(
        ["bash", str(RELEASE_CORE)], check=False, env=env, capture_output=True, text=True
    )
    return Release(proc, _lines(gh_log), notes.read_text() if notes.exists() else "")


class TestRelease:
    def test_missing_release_is_created_with_the_block(self, tmp_path: Path) -> None:
        r = _release(tmp_path, "absent")
        assert r.proc.returncode == 0, r.proc.stderr
        assert len(r.edits()) == 1 and r.edits()[0].startswith("gh release create v0.11.0")
        assert "--verify-tag" in r.edits()[0] and "--generate-notes" in r.edits()[0]
        assert r.notes.count(BEGIN) == 1 and r.notes.count(END) == 1
        assert f"`{REF}`" in r.notes
        assert f"`{SRC}@{DIGEST}`" in r.notes

    def test_existing_release_gets_the_block_appended(self, tmp_path: Path) -> None:
        r = _release(tmp_path, "plain")
        assert r.proc.returncode == 0, r.proc.stderr
        assert r.edits() and r.edits()[0].startswith("gh release edit v0.11.0")
        assert r.notes.startswith("## What's changed\n- a thing\n")
        assert r.notes.count(BEGIN) == 1
        assert f"`{REF}`" in r.notes

    def test_a_rerun_replaces_the_block_instead_of_adding_one(self, tmp_path: Path) -> None:
        r = _release(tmp_path, "withblock")
        assert r.proc.returncode == 0, r.proc.stderr
        assert r.notes.count(BEGIN) == 1 and r.notes.count(END) == 1
        assert "- old" not in r.notes
        assert f"`{REF}`" in r.notes
        assert r.notes.startswith("## What's changed\n")
        assert r.notes.rstrip().endswith("tail line"), "text after the block survives"

    def test_a_crlf_body_is_still_replaced_in_place(self, tmp_path: Path) -> None:
        # A body saved from the web UI comes back with CRLF; the markers must still match.
        r = _release(tmp_path, "crlf")
        assert r.proc.returncode == 0, r.proc.stderr
        assert r.notes.count(BEGIN) == 1 and "- old" not in r.notes
        assert r.notes.rstrip().endswith("tail line")

    def test_markers_out_of_shape_are_refused_not_edited(self, tmp_path: Path) -> None:
        r = _release(tmp_path, "inline")
        assert r.proc.returncode != 0
        assert "out of shape" in r.proc.stderr
        assert r.edits() == []

    def test_losing_the_create_race_edits_the_release_instead(self, tmp_path: Path) -> None:
        # Another job created it between our view and our create: read it again and edit.
        r = _release(tmp_path, "absent plain", create="exists")
        assert r.proc.returncode == 0, r.proc.stderr
        assert [c.split()[2] for c in r.edits()] == ["create", "edit"]
        assert r.notes.startswith("## What's changed\n- a thing\n")
        assert r.notes.count(BEGIN) == 1

    def test_unreadable_release_fails(self, tmp_path: Path) -> None:
        r = _release(tmp_path, "error")
        assert r.proc.returncode != 0
        assert "could not read release" in r.proc.stderr
        assert r.edits() == []

    def test_no_refs_writes_nothing(self, tmp_path: Path) -> None:
        r = _release(tmp_path, "plain", refs="\n")
        assert r.proc.returncode == 0, r.proc.stderr
        assert r.gh_calls == []

    def test_a_ref_without_a_digest_is_refused(self, tmp_path: Path) -> None:
        r = _release(tmp_path, "plain", refs=f"{DEST}:0.11.0\n")
        assert r.proc.returncode != 0
        assert r.gh_calls == []


@pytest.mark.skipif(yaml is None, reason="pyyaml not installed")
class TestShape:
    def test_both_actions_run_their_core_via_bash(self) -> None:
        for d, script, required in (
            (MIRROR_DIR, "oaw-mirror-image.sh", {"source-digest-ref", "tags", "dest-image"}),
            (RELEASE_DIR, "oaw-release-images.sh", {"release-tag", "release-refs"}),
        ):
            doc = yaml.safe_load((d / "action.yml").read_text())
            assert doc["runs"]["using"] == "composite"
            assert {k for k, v in doc["inputs"].items() if v.get("required")} == required
            assert doc["runs"]["steps"][0]["run"] == f'bash "${{GITHUB_ACTION_PATH}}/{script}"'

    def test_mirror_action_holds_no_release_or_token_input(self) -> None:
        doc = yaml.safe_load((MIRROR_DIR / "action.yml").read_text())
        assert "release-tag" not in doc["inputs"] and "github-token" not in doc["inputs"]
        assert set(doc["outputs"]) == {"digest", "release-refs"}

    def test_kit_release_write_is_its_own_job_after_the_mirror(self) -> None:
        doc = yaml.safe_load(WORKFLOW.read_text())
        assert doc["permissions"]["contents"] == "read"
        jobs = doc["jobs"]
        assert "permissions" not in jobs["mirror"], "the signing job stays contents: read"
        notes = jobs["release-notes"]
        assert notes["needs"] == "mirror"
        assert notes["permissions"] == {"contents": "write"}
        step = next(s for s in notes["steps"] if s.get("uses") == "./.github/actions/oaw-release-images")
        assert step["with"]["release-tag"] == "v${{ needs.mirror.outputs.version }}"
        assert step["with"]["release-refs"] == "${{ needs.mirror.outputs.version_ref }}"
        assert jobs["mirror"]["outputs"]["version"] == "${{ steps.mirror.outputs.version }}"
