"""Oracle for Story 1.5 — the read-only ~/.secrets mount + mid-session liveness
(#965, Dev Spec §5.5, R-12/R-13).

Two verification altitudes, mirroring test_ownership.py:

* **Static config oracles** (pure — run for real in the stock ``pytest tests/``
  lane, no docker). Assert the checked-in ``20-secrets.toml`` fragment resolves
  as a *read-only* mount of ``~/.secrets`` (R-12: provided only via the ro mount,
  never rw), that its target matches the bootstrap's secrets-dir default, and
  that no secret is baked into the image (R-12: never in an image layer) —
  ``mount_resolver`` even fails LOUD if the fragment is fat-fingered to ``rw``.

* **Integration oracle** (``test_secrets_readonly`` — the story's named oracle,
  IT-02). Runs the image via ``docker run`` with ``~/.secrets`` bind-mounted ro:
  the container *cannot* write the mount (R-12 ro), and a file the host adds
  *after* the container started is live inside the running container (R-13).
  Self-skips when docker/the image is absent (like test_image.py);
  ``OAKANDWAVE_REQUIRE_IMAGE`` turns absence into a hard failure so CI proves the
  contract end-to-end.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTAINER_DIR = REPO_ROOT / "containers" / "oakandwave-workflow"
MANIFEST_DIR = CONTAINER_DIR / "mounts.d"
SECRETS_FRAGMENT = MANIFEST_DIR / "20-secrets.toml"
DOCKERFILE = CONTAINER_DIR / "Dockerfile"

# Import the resolver by path (no PYTHONPATH dependency), like test_mounts.py.
sys.path.insert(0, str(CONTAINER_DIR))
import mount_resolver as mr  # noqa: E402

FAKE_HOME = PurePosixPath("/home/bakerb")
MAJOR = 8

# The uid-1000 image whose ro bind-mount we probe; consistent with the other
# docker-gated oracles (test_image.py / test_ownership.py).
SECRETS_IMAGE = "oakandwave-workflow:edge"
SECRETS_TARGET = "/home/ubuntu/.secrets"


# --- Static R-12 oracles (pure; run in the stock lane) ------------------------


def _secrets_mounts() -> list[mr.ResolvedMount]:
    """Resolve the checked-in secrets fragment's mounts for assertions.

    Returns a LIST, not a single mount. #1061 replaced the whole-`~/.secrets`-dir
    mount with named single-file mounts, so the count is a design variable now —
    every added secret is one more entry. This helper deliberately asserts nothing
    about how many there are: pinning the count made the previous version of this
    test fail on a change that strictly *narrowed* exposure, which is backwards
    for a guard whose subject is blast radius.
    """
    assert SECRETS_FRAGMENT.is_file(), f"missing secrets fragment: {SECRETS_FRAGMENT}"
    resolved = mr.resolve_manifest(MAJOR, home=FAKE_HOME, mounts_dir=MANIFEST_DIR)
    secrets = [m for m in resolved if m.layer == "read-only-secrets"]
    assert secrets, "no read-only-secrets mount in the resolved manifest"
    return secrets


def test_secrets_mount_is_readonly() -> None:
    """R-12: secrets are provided ONLY via ro mounts — EVERY resolved
    read-only-secrets mount is ro, sourced from ~/.secrets, and lands under the
    bootstrap's OAW_SECRETS_DIR."""
    mounts = _secrets_mounts()
    for m in mounts:
        assert m.mode == "ro", f"{m.name}: secrets mount must be ro (R-12), got {m.mode!r}"
        # Compare against the path WITH its separator: a bare prefix test would
        # also accept ~/.secrets-analogic/..., which is precisely the blast-radius
        # this guard exists to bound.
        assert m.source.startswith("/home/bakerb/.secrets/"), (
            f"{m.name}: source must be a file under ~/.secrets/, got {m.source!r}"
        )
        assert m.target.startswith(SECRETS_TARGET + "/"), (
            f"{m.name}: target must be under the bootstrap OAW_SECRETS_DIR "
            f"({SECRETS_TARGET}/), got {m.target!r}"
        )
        # The docker -v rendering carries the :ro suffix — ro at runtime.
        assert m.to_docker_volume().endswith(":ro"), (
            f"{m.name}: docker volume spec must end :ro, got {m.to_docker_volume()!r}"
        )


def test_secrets_mounts_are_scoped_not_whole_dir() -> None:
    """#1061: no mount may be the whole ~/.secrets directory.

    The host dir spans both sides of the OaW/Analogic IP boundary (~80 entries);
    the kit consumes one. A whole-dir mount hands every container every credential
    on both sides of that line. This is the guard that keeps a future edit from
    quietly restoring it — the failure it prevents is silent, since a wider mount
    breaks nothing and looks like it works.
    """
    whole_dir = "/home/bakerb/.secrets"
    for m in _secrets_mounts():
        assert m.source != whole_dir, (
            f"{m.name}: mounts the WHOLE secrets dir ({whole_dir}). Mount named "
            f"files instead — see mounts.d/20-secrets.toml and #1061."
        )


def test_secrets_env_declares_no_literal_token() -> None:
    """#1061: no manifest-declared env may carry a literal credential.

    An environment variable is inherited by every child process; a file must be
    deliberately opened. With transcripts host-durable (#1064), a literal token in
    the environment is one `env` dump away from permanent storage.

    SCOPE, stated honestly: this examines the *manifest's* `env` metadata, which is
    the only surface reachable from CI — the host's `~/.secrets/.env` is not in the
    repo and cannot be inspected here. An earlier version of this test looped over
    that metadata without asserting it had any subject at all; since no fragment
    declares `env`, the loop body never ran and the test passed over an empty
    denominator — the very shape `cutover-prerequisites.md` §4 catalogues. The
    guard below therefore asserts the *invariant that is actually checkable*: the
    secrets layer declares no env at all, so the pointer-vs-value question cannot
    be answered wrongly here. If a future fragment adds `env`, this fails and
    forces the author to re-derive the rule rather than inherit a silent pass.
    """
    for m in _secrets_mounts():
        assert not (m.env or {}), (
            f"{m.name} declares manifest env {sorted((m.env or {}))!r}. The secrets "
            f"layer passes POINTERS via the mounted .env file, not manifest env "
            f"metadata — re-read #1061 before adding one."
        )


def test_secrets_rw_fragment_is_rejected() -> None:
    """R-12 red-first: a secrets fragment declared rw fails LOUD in the resolver,
    so the ro contract cannot be fat-fingered open."""
    with pytest.raises(mr.ManifestError, match="R-12"):
        mr.resolve_mount(
            {
                "name": "secrets",
                "layer": "read-only-secrets",
                "mode": "rw",
                "source": "~/.secrets",
                "target": SECRETS_TARGET,
            },
            MAJOR,
            FAKE_HOME,
        )


def test_secrets_never_baked_into_image() -> None:
    """R-12: no secret is baked into an image layer — the Dockerfile never COPY/ADDs
    a host secrets path; secrets arrive only through the runtime ro mount.

    Red-first guard: if a future edit bakes ~/.secrets / a .env / a credential,
    this trips. We scan COPY/ADD instruction lines (not comments, which mention
    ~/.secrets to *explain* why it is NOT baked)."""
    assert DOCKERFILE.is_file(), f"missing Dockerfile: {DOCKERFILE}"
    forbidden = (".secrets", ".env", "secret", "credential", "token", ".pem", ".key")
    offenders: list[str] = []
    for raw in DOCKERFILE.read_text().splitlines():
        line = raw.strip()
        if line.startswith("#"):
            continue
        head = line.split(None, 1)[0].upper() if line else ""
        if head not in {"COPY", "ADD"}:
            continue
        low = line.lower()
        if any(tok in low for tok in forbidden):
            offenders.append(line)
    assert not offenders, (
        "Dockerfile bakes a secret into an image layer (R-12 violation) — "
        f"secrets must come only via the runtime ro mount:\n" + "\n".join(offenders)
    )


# --- Integration oracle: the named story test (docker-gated) ------------------


def _skip_or_fail(msg: str, require: bool) -> None:
    if require:
        pytest.fail(msg + " (OAKANDWAVE_REQUIRE_IMAGE set)")
    pytest.skip(msg)


def _docker_and_image_or_skip() -> tuple[str, str]:
    docker = shutil.which("docker")
    require = bool(os.environ.get("OAKANDWAVE_REQUIRE_IMAGE"))
    ref = os.environ.get("OAKANDWAVE_IMAGE", SECRETS_IMAGE)
    if docker is None:
        _skip_or_fail("docker binary not found on PATH", require)
    if (
        subprocess.run(
            [docker, "image", "inspect", ref], capture_output=True
        ).returncode
        != 0
    ):
        _skip_or_fail(
            f"image {ref!r} not built — run "
            f"`make -C containers/oakandwave-workflow build`",
            require,
        )
    return docker, ref  # type: ignore[return-value]


def test_secrets_readonly() -> None:
    """IT-02 (R-12/R-13): the container cannot write the ro secrets mount, and a
    file the host adds mid-session is live inside the running container.

    Runs a long-lived container with ~/.secrets bind-mounted ro, then:
      1. an in-container write attempt FAILS (R-12: ro — host owns the secret);
      2. a file the HOST adds AFTER the container started is readable inside it
         with no restart (R-13: liveness).
    Self-skips without docker/the image; OAKANDWAVE_REQUIRE_IMAGE makes absence a
    hard failure so CI proves the contract.

    KNOWN SCOPE GAP (#1061), stated rather than hidden: this mounts a whole
    tempdir, which is **no longer the shipped mount shape** — `20-secrets.toml`
    now declares named single-FILE binds. The R-12 half generalises (ro is ro);
    the R-13 half does NOT, and the difference matters:

      - dir bind  : a file the host ADDS afterwards appears  (what this proves)
      - file bind : the inode is bound, so an ADD is invisible and an atomic
                    replace (`mv`/`sops`/editor save) silently pins the container
                    to the old content until it is recreated

    So a green run here does not license the claim "rotation is live" for the
    shape we actually ship — only "in-place rewrite of a bound file is live".
    Extending this oracle to the two file mounts is tracked in #1061's follow-up;
    until then, treat the liveness assertion as scoped to the dir shape.
    """
    docker, ref = _docker_and_image_or_skip()

    with tempfile.TemporaryDirectory() as host_secrets:
        # Seed one secret present at launch; add another AFTER launch for R-13.
        (Path(host_secrets) / "AT_BOOT").write_text("boot-value\n")

        cid = subprocess.run(
            [
                docker, "run", "-d", "--rm",
                "-v", f"{host_secrets}:{SECRETS_TARGET}:ro",
                "--entrypoint", "sh", ref,
                "-c", "sleep 60",
            ],
            capture_output=True, text=True, timeout=120,
        )
        assert cid.returncode == 0, f"failed to start container:\n{cid.stderr}"
        container = cid.stdout.strip()
        try:
            def _exec(script: str) -> subprocess.CompletedProcess:
                return subprocess.run(
                    [docker, "exec", container, "sh", "-c", script],
                    capture_output=True, text=True, timeout=60,
                )

            # (0) the at-boot secret is readable inside the container.
            boot = _exec(f"cat {SECRETS_TARGET}/AT_BOOT")
            assert boot.returncode == 0 and "boot-value" in boot.stdout, (
                f"at-boot secret not readable in container:\n{boot.stderr}"
            )

            # (1) R-12: an in-container write to the ro mount FAILS.
            write = _exec(f"echo x > {SECRETS_TARGET}/should_fail")
            assert write.returncode != 0, (
                "container wrote to the ro secrets mount — R-12 violated "
                "(the mount is not read-only)"
            )
            assert not (Path(host_secrets) / "should_fail").exists(), (
                "a file appeared on the host — the ro mount let a write through"
            )

            # (2) R-13: a host-added file mid-session is live in the container.
            (Path(host_secrets) / "MID_SESSION").write_text("live-add\n")
            live = _exec(f"cat {SECRETS_TARGET}/MID_SESSION")
            assert live.returncode == 0 and "live-add" in live.stdout, (
                "host-added secret not visible in the running container — R-13 "
                f"liveness violated:\n{live.stderr}"
            )
        finally:
            subprocess.run(
                [docker, "rm", "-f", container], capture_output=True, timeout=60
            )
