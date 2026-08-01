"""Oracle for the image release cadence (#1063).

A candidate image is cut **deliberately** — on a version tag or a manual
dispatch — never on every merge to main. Before this, each merge ran
build → cosign → syft → GHCR push on a ~9.9 GB base: 1049 s / 17.5 min measured
on a markdown-only merge (cc57a75, PR #1060). `/scpmmr` waits on the main-branch
pipeline, so the whole fleet paid that per merge.

**These tests PARSE the workflow, they do not grep it.** The trigger's own
explanatory comment now contains the literal string ``branches: [main]`` —
describing what was removed and why. A substring or regex check would match that
prose and report the defect present while the config is correct, which is the
same instrument-reads-its-own-advice failure this repo keeps producing
(bootstrap's hook validator matching its own warning text, cc-workflow#925's
gate matching its own output). Parsing asks the config, not the commentary.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip(
    "yaml",
    reason="PyYAML is required to parse the workflow — a regex fallback would "
    "match the trigger's own explanatory comment and assert nothing",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "oakandwave-workflow-image.yml"


def _triggers() -> dict:
    """The workflow's `on:` block, as data.

    YAML 1.1 resolves the bare key ``on`` to the boolean ``True`` (the
    Norway-problem family), so PyYAML hands it back under ``True`` rather than
    ``"on"``. Look under both — a lookup for only ``"on"`` returns ``None`` here
    and every assertion below would then pass over an empty dict, which is the
    empty-denominator shape rather than a result.
    """
    doc = yaml.safe_load(IMAGE_WORKFLOW.read_text())
    on = doc.get("on", doc.get(True))
    assert isinstance(on, dict), (
        f"could not read the workflow's trigger block (got {type(on).__name__}) — "
        f"refusing to assert against nothing"
    )
    return on


def test_image_workflow_exists() -> None:
    assert IMAGE_WORKFLOW.is_file(), f"missing workflow: {IMAGE_WORKFLOW}"


def test_merging_to_main_does_not_cut_a_candidate() -> None:
    """The defect itself: a merge is not a release.

    Docs-only merges minted a signed, SBOM'd release artifact nothing would pull,
    and blocked every agent's `/scpmmr` for ~17.5 min doing it.
    """
    push = _triggers().get("push") or {}
    assert "branches" not in push, (
        "the image workflow triggers on a branch push again — every merge to "
        f"main will mint an :edge and block /scpmmr ~17.5 min (got {push!r})"
    )


def test_a_version_tag_still_cuts_a_candidate() -> None:
    push = _triggers().get("push") or {}
    assert push.get("tags") == ["v*"], (
        f"a version tag must still build a candidate (got tags={push.get('tags')!r})"
    )


def test_a_candidate_can_still_be_cut_by_hand() -> None:
    """Without this, the only way to get an image is to cut a real version tag —
    which would make testing a build require pretending to release."""
    on = _triggers()
    assert "workflow_dispatch" in on, "manual dispatch must remain available"


def test_no_paths_filter_smuggled_in() -> None:
    """A `paths:` filter is the wrong axis and was rejected on the merits.

    The kit is BAKED into the image, so `skills/**` and `scripts/**` genuinely do
    change it. A filter would either be broad enough to save little, or would
    silently ship a stale :stable — a correctness bug wearing a performance fix's
    clothes. The axis is "did we decide to release", not "which files moved".
    """
    push = _triggers().get("push") or {}
    assert "paths" not in push and "paths-ignore" not in push, (
        "a paths filter cannot decide whether an image is stale — the kit is "
        "baked in, so nearly every path changes the image"
    )


def test_the_promote_path_is_untouched() -> None:
    """#1063 is a TRIGGER change, not a build change.

    `promote-oakandwave-image.sh` retags the exact digest :edge → :stable with no
    rebuild (same bytes, R-23). If this fix ever grows into "rebuild on promote",
    the digest tested stops being the digest promoted.
    """
    promote = REPO_ROOT / "scripts" / "ci" / "promote-oakandwave-image.sh"
    assert promote.is_file(), "the promote script must still exist"
    text = promote.read_text()
    assert "buildx imagetools create" in text or "imagetools" in text, (
        "promote must retag by digest, never rebuild"
    )
    assert "build-oakandwave-image.sh" not in text, (
        "promote must not invoke a build — that would break digest-exactness (R-23)"
    )


def test_release_cadence_is_documented() -> None:
    """The cadence is now a human contract ('a merge is not a release'), and an
    undocumented contract is one nobody can follow."""
    runbook = REPO_ROOT / "docs" / "operations" / "image-release-cadence.md"
    assert runbook.is_file(), f"missing ops runbook: {runbook}"
    text = runbook.read_text().lower()
    assert "not a release" in text, "the runbook must state that a merge is not a release"
    assert "workflow_dispatch" in text or "manual" in text, (
        "the runbook must say how to cut a candidate deliberately"
    )
