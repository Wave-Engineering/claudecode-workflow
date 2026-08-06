"""Pruning the registry without deleting what the fleet is running (#1100).

The standard GHCR cleanup recipe is "delete all untagged versions". Running it
here would have deleted the live fleet's image: a profile pins a BARE DIGEST,
which is correct — it is what makes a release immutable (R-05/R-23) — but leaves
no tag behind, so a pinned, actively-running image is indistinguishable from
garbage to any tag-based rule. **Untagged does not mean unused.**

And the failure is delayed and disconnected: nothing breaks at prune time. It
breaks at the next container launch, with nothing linking the two events. So the
load-bearing tests here are the ones that prove a pinned-but-untagged digest
survives, and that an empty protect-list refuses rather than proposing to delete
everything.

`gh` is stubbed on PATH rather than the listing being injected through a back
door, so the script's real registry path runs.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PRUNE = REPO / "scripts" / "ci" / "registry-prune.sh"

PIN = "sha256:" + "a" * 64
OLD = "sha256:" + "b" * 64
ORPHAN_SUBJ = "sha256:" + "c" * 64


def _version(vid: int, digest: str, tags: list[str], created: str) -> dict:
    return {
        "id": vid,
        "name": digest,
        "metadata": {"container": {"tags": tags}},
        "created_at": created,
    }


def _setup(
    tmp_path: Path,
    versions: list[dict],
    pins: list[str] | None = None,
    children: dict[str, list[str]] | None = None,
) -> dict:
    """A fake profiles root, a `gh` stub serving `versions`, and a `docker` stub
    serving manifests.

    The docker stub is not optional decoration: the script resolves every
    non-cosign digest to find index children, and an unresolvable digest is KEPT
    (parentage unknown is not licence to delete). Without the stub every fixture
    would be unresolvable and every delete-plan assertion would pass vacuously.
    """
    profiles = tmp_path / "profiles" / "dogfood"
    profiles.mkdir(parents=True)
    if pins is None:
        pins = [PIN]
    # The ref must name the package: pin extraction is scoped to THIS package so
    # a profile pinning some other image is not demanded to appear in this
    # listing. A bare "ghcr.io/x/y@…" fixture therefore matches nothing.
    body = "[sandbox]\n" + "".join(
        f'default_image = "ghcr.io/wave-engineering/oakandwave-workflow@{p}"\n'
        for p in pins
    )
    (profiles / "config.toml").write_text(body)

    listing = tmp_path / "versions.json"
    listing.write_text(json.dumps(versions))

    manifests = tmp_path / "manifests.json"
    manifests.write_text(json.dumps(children or {}))

    bindir = tmp_path / "bin"
    bindir.mkdir()
    deleted = tmp_path / "deleted.log"

    docker = bindir / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        '# args: buildx imagetools inspect --raw <ref>@<digest>\n'
        'ref="${!#}"; digest="${ref##*@}"\n'
        f'python3 -c \'\nimport json,sys\nkids=json.load(open("{manifests}")).get(sys.argv[1], [])\n'
        'print(json.dumps({"mediaType": "application/vnd.oci.image.index.v1+json",\n'
        '                  "manifests": [{"digest": d} for d in kids]}))\n'
        "' \"$digest\"\n"
    )
    docker.chmod(0o755)
    gh = bindir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        # DELETE is recorded, never performed.
        'if [[ "$*" == *"-X DELETE"* ]]; then\n'
        f'  printf "%s\\n" "$*" >> "{deleted}"\n'
        "  exit 0\n"
        "fi\n"
        # The listing call: emit one JSON object per line, as --jq would.
        'if [[ "$*" == *"/versions"* ]]; then\n'
        f'  python3 -c \'\nimport json,sys\nfor v in json.load(open("{listing}")):\n'
        '    print(json.dumps({"id": v["id"], "name": v["name"],\n'
        '                      "tags": v["metadata"]["container"]["tags"],\n'
        '                      "created": v["created_at"]}))\n\'\n'
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )
    gh.chmod(0o755)
    return {
        "profiles_root": tmp_path / "profiles",
        "bindir": bindir,
        "deleted": deleted,
    }


def _run(
    env_paths: dict, *args: str, assume_yes: bool = False
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": f"{env_paths['bindir']}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(env_paths["profiles_root"].parent),
    }
    if assume_yes:
        env["OAW_REGISTRY_ASSUME_YES"] = "1"
    return subprocess.run(
        ["bash", str(PRUNE), "--profiles-root", str(env_paths["profiles_root"]), *args],
        capture_output=True,
        text=True,
        env=env,
        stdin=subprocess.DEVNULL,
        timeout=120,
    )


def test_a_pinned_but_untagged_digest_is_never_deleted(tmp_path: Path) -> None:
    """THE #1100 TRAP. This is the exact shape that would have taken the fleet
    down: the running image carries no tag at all."""
    paths = _setup(
        tmp_path,
        [
            _version(1, PIN, [], "2026-08-01T00:00:00Z"),  # pinned, UNTAGGED
            _version(2, OLD, [], "2026-07-01T00:00:00Z"),
        ],
    )
    proc = _run(paths)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "pinned by an aoe profile" in proc.stdout
    assert "KEEP 2" in proc.stdout or "KEEP 1" in proc.stdout
    # And it must not appear in the delete plan at all.
    assert "DELETE 0" in proc.stdout or PIN not in proc.stdout.split("DELETE")[-1]


def test_an_empty_pin_list_refuses_rather_than_deleting_everything(tmp_path: Path) -> None:
    """An empty protect-list makes every downstream check vacuous, and 'nothing
    is in use' is precisely the reading that deletes a running fleet."""
    paths = _setup(tmp_path, [_version(1, PIN, [], "2026-08-01T00:00:00Z")], pins=[])
    proc = _run(paths)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "refusing" in proc.stderr
    assert not paths["deleted"].exists()


def test_an_empty_registry_listing_refuses(tmp_path: Path) -> None:
    """Zero versions back from the API is an instrument failure, not a clean
    registry — concluding 'nothing to protect' from it is the same shape."""
    paths = _setup(tmp_path, [])
    proc = _run(paths)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    # The SPECIFIC guard, not just "some refusal happened": a later keep-set-empty
    # check also refuses here, so asserting on the shared word "EMPTY" could not
    # tell which one fired and passed with this guard deleted.
    assert "registry listing came back EMPTY" in proc.stderr, proc.stderr


def test_cosign_artifacts_of_a_kept_digest_survive(tmp_path: Path) -> None:
    """A subject without its signature cannot be verified, and a signature
    without its subject verifies nothing — they live and die together."""
    sig = "sha256-" + PIN.split(":")[1] + ".sig"
    att = "sha256-" + PIN.split(":")[1] + ".att"
    paths = _setup(
        tmp_path,
        [
            _version(1, PIN, [], "2026-08-01T00:00:00Z"),
            _version(2, "sha256:" + "d" * 64, [sig], "2026-08-01T00:01:00Z"),
            _version(3, "sha256:" + "e" * 64, [att], "2026-08-01T00:02:00Z"),
        ],
    )
    proc = _run(paths)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.count("cosign artifact for") == 2
    assert "DELETE 0" in proc.stdout


def test_an_orphaned_signature_is_pruned(tmp_path: Path) -> None:
    """A signature whose subject is gone protects nothing and is exactly the
    accumulated clutter this issue is about."""
    orphan = "sha256-" + ORPHAN_SUBJ.split(":")[1] + ".sig"
    paths = _setup(
        tmp_path,
        [
            _version(1, PIN, [], "2026-08-01T00:00:00Z"),
            _version(2, "sha256:" + "f" * 64, [orphan], "2026-07-01T00:00:00Z"),
        ],
    )
    proc = _run(paths, "--keep-recent", "1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DELETE 1" in proc.stdout


def test_the_rollback_window_keeps_recent_manifests(tmp_path: Path) -> None:
    """Keeping only what is referenced right now leaves nothing to roll back to
    when the current image turns out bad — and release images are not
    distinguishable from intermediate :edge pushes, because the build only ever
    pushes :edge.

    The pin is deliberately the OLDEST here so it cannot also fall inside the
    window: a manifest that is both pinned and recent reports the pin reason
    (first reason wins), which made an earlier version of this test count 2 and
    call the code broken when it was the fixture that was ambiguous.
    """
    versions = [_version(1, PIN, [], "2026-07-01T00:00:00Z")]  # oldest
    for i in range(2, 9):
        versions.append(_version(i, f"sha256:{i:064x}", [], f"2026-08-{i:02d}T00:00:00Z"))
    paths = _setup(tmp_path, versions)
    proc = _run(paths, "--keep-recent", "3")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.count("within the rollback window") == 3
    assert "KEEP 4" in proc.stdout, proc.stdout  # 3 recent + the pin


def test_cosign_artifacts_do_not_consume_the_rollback_window(tmp_path: Path) -> None:
    """Counting .sig/.att toward the window would silently halve it — each image
    carries two of them, so a window of 5 would really be a window of 1 or 2."""
    versions = [_version(1, PIN, [], "2026-07-01T00:00:00Z")]  # oldest, see above
    vid = 2
    for i in range(3):
        d = f"sha256:{i:064x}"
        versions.append(_version(vid, d, [], f"2026-08-{10 + i:02d}T00:00:00Z"))
        vid += 1
        versions.append(
            _version(
                vid,
                f"sha256:{vid:064x}",
                ["sha256-" + d.split(":")[1] + ".sig"],
                f"2026-08-{10 + i:02d}T00:01:00Z",
            )
        )
        vid += 1
    paths = _setup(tmp_path, versions)
    proc = _run(paths, "--keep-recent", "3")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # Assert the OUTCOME, not the reason count. Counting reasons passed even when
    # the window was filled with signatures instead of images, because three
    # things were protected either way. What actually matters is that no image is
    # left unprotected: 3 manifests + their 3 signatures + the pin = everything.
    assert "DELETE 0" in proc.stdout, proc.stdout


def test_dry_run_deletes_nothing(tmp_path: Path) -> None:
    """Deleting published artifacts is irreversible and outward-facing, so
    computing the plan and performing it are deliberately separate acts."""
    paths = _setup(
        tmp_path,
        [
            _version(1, PIN, [], "2026-08-01T00:00:00Z"),
            _version(2, OLD, [], "2026-07-01T00:00:00Z"),
        ],
    )
    proc = _run(paths, "--keep-recent", "1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DRY RUN" in proc.stdout
    assert not paths["deleted"].exists(), "a dry run issued DELETE calls"


def test_apply_deletes_only_the_planned_versions(tmp_path: Path) -> None:
    paths = _setup(
        tmp_path,
        [
            _version(1, PIN, [], "2026-08-01T00:00:00Z"),
            _version(2, OLD, [], "2026-07-01T00:00:00Z"),
        ],
    )
    proc = _run(paths, "--keep-recent", "1", "--apply", assume_yes=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = paths["deleted"].read_text().splitlines()
    assert len(calls) == 1, f"expected exactly one delete, got: {calls}"
    assert "/versions/2" in calls[0], calls[0]
    assert "/versions/1" not in calls[0], "the pinned version was deleted"


def test_a_pin_missing_from_the_listing_refuses(tmp_path: Path) -> None:
    """"I could not see it" and "it is not there" are different claims.

    A truncated or permission-limited listing makes protected things look
    unreferenced — a signature whose subject fell outside the page reads as an
    orphan and gets pruned. If a pin for this package is unaccounted for, the
    listing is incomplete and nothing may be deleted on the strength of it.
    """
    paths = _setup(
        tmp_path,
        [_version(1, OLD, [], "2026-08-01T00:00:00Z")],  # the PIN is absent
    )
    proc = _run(paths)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "NOT in the registry listing" in proc.stderr
    assert not paths["deleted"].exists()


def test_a_pin_for_another_package_is_not_demanded(tmp_path: Path) -> None:
    """A profile may legitimately pin a different image — a locally-built one, or
    another package. Demanding those appear in THIS package's listing would be a
    false alarm that blocks every prune."""
    profiles = tmp_path / "profiles" / "other"
    profiles.mkdir(parents=True)
    (profiles / "config.toml").write_text(
        '[sandbox]\ndefault_image = "localhost/some-other-image@' + ORPHAN_SUBJ + '"\n'
    )
    paths = _setup(
        tmp_path,
        [
            _version(1, PIN, [], "2026-08-01T00:00:00Z"),
            _version(2, OLD, [], "2026-07-01T00:00:00Z"),
        ],
    )
    proc = _run(paths, "--keep-recent", "1")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_apply_without_confirmation_aborts(tmp_path: Path) -> None:
    """A flag alone is a weak gate for an irreversible, outward-facing delete.
    Nothing forces a dry run first, so without this an operator can destroy every
    unprotected published artifact having never seen the list."""
    paths = _setup(
        tmp_path,
        [
            _version(1, PIN, [], "2026-08-01T00:00:00Z"),
            _version(2, OLD, [], "2026-07-01T00:00:00Z"),
        ],
    )
    proc = _run(paths, "--keep-recent", "1", "--apply")  # no confirmation supplied
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "aborting" in proc.stderr
    assert not paths["deleted"].exists(), "it deleted without confirmation"


def test_children_of_a_kept_index_are_never_deleted(tmp_path: Path) -> None:
    """THE #1100 TRAP, ONE LAYER DOWN. A pinned digest is usually an INDEX, not a
    leaf: buildx pushes an index whose children are the per-arch manifest and a
    provenance attestation, and GHCR lists each child as its own version —
    untagged, unpinned, matching no cosign tag. Deleting a child of a live index
    makes the pinned image UNPULLABLE.

    Measured on the real registry: the pin resolves to an image index with 2
    children. They survived the first cut of this script only because they were
    recent enough to fall inside the rollback window — luck, not protection.
    """
    child_a = "sha256:" + "1" * 64
    child_b = "sha256:" + "2" * 64
    paths = _setup(
        tmp_path,
        [
            _version(1, PIN, ["edge"], "2026-08-01T00:00:00Z"),
            _version(2, child_a, [], "2026-08-01T00:00:01Z"),
            _version(3, child_b, [], "2026-08-01T00:00:02Z"),
            _version(4, OLD, [], "2020-01-01T00:00:00Z"),
        ],
        children={PIN: [child_a, child_b]},
    )
    proc = _run(paths, "--keep-recent", "1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.count("child of a kept index") == 2, proc.stdout
    # The children must be in KEEP, and only the genuinely-unreferenced OLD goes.
    assert "DELETE 1" in proc.stdout, proc.stdout
    delete_section = proc.stdout.split("==> DELETE")[-1]
    assert child_a not in delete_section and child_b not in delete_section


def test_index_children_do_not_consume_the_rollback_window(tmp_path: Path) -> None:
    """A child is not a release, so counting them shrinks the real window — with
    2 children per push, a window of 5 would really be a window of 1 or 2."""
    # PIN is deliberately OLDEST so it cannot also occupy a window slot: a
    # version that is both pinned and recent reports the pin reason (first reason
    # wins), which makes a reason-count assertion ambiguous.
    versions = [_version(1, PIN, ["edge"], "2020-01-01T00:00:00Z")]
    children = {}
    vid = 2
    for i in range(3):
        idx = f"sha256:{i:064x}"
        kid = f"sha256:{100 + i:064x}"
        versions.append(_version(vid, idx, [], f"2026-08-0{5 + i}T00:00:00Z")); vid += 1
        versions.append(_version(vid, kid, [], f"2026-08-0{5 + i}T00:00:01Z")); vid += 1
        children[idx] = [kid]
    paths = _setup(tmp_path, versions, children=children)
    proc = _run(paths, "--keep-recent", "3")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # 3 indexes in the window (not 1 index + 2 children), each dragging its child.
    assert proc.stdout.count("within the rollback window") == 3, proc.stdout
    assert "DELETE 0" in proc.stdout, proc.stdout


def test_an_unresolvable_digest_is_kept_not_deleted(tmp_path: Path) -> None:
    """"I could not tell" is not "safe to delete" — an unresolvable version may
    be a child of something live."""
    paths = _setup(tmp_path, [_version(1, PIN, ["edge"], "2026-08-01T00:00:00Z"),
                              _version(2, OLD, [], "2020-01-01T00:00:00Z")])
    # Break the resolver.
    (paths["bindir"] / "docker").write_text("#!/usr/bin/env bash\nexit 1\n")
    (paths["bindir"] / "docker").chmod(0o755)
    proc = _run(paths, "--keep-recent", "1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "UNRESOLVED" in proc.stdout
    assert "DELETE 0" in proc.stdout


def test_the_script_is_executable() -> None:
    assert os.access(PRUNE, os.X_OK)
