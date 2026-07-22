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


def _secrets_mount() -> mr.ResolvedMount:
    """Resolve the checked-in secrets fragment (and only it) for assertions."""
    assert SECRETS_FRAGMENT.is_file(), f"missing secrets fragment: {SECRETS_FRAGMENT}"
    resolved = mr.resolve_manifest(MAJOR, home=FAKE_HOME, mounts_dir=MANIFEST_DIR)
    secrets = [m for m in resolved if m.layer == "read-only-secrets"]
    assert secrets, "no read-only-secrets mount in the resolved manifest"
    assert len(secrets) == 1, f"expected one secrets mount, got {len(secrets)}"
    return secrets[0]


def test_secrets_mount_is_readonly() -> None:
    """R-12: secrets are provided ONLY via the ro mount — the checked-in fragment
    resolves read-only, sourced from ~/.secrets, targeting the bootstrap's dir."""
    m = _secrets_mount()
    assert m.mode == "ro", f"secrets mount must be ro (R-12), got {m.mode!r}"
    assert m.source == "/home/bakerb/.secrets", (
        f"secrets source must be ~/.secrets, got {m.source!r}"
    )
    assert m.target == SECRETS_TARGET, (
        f"secrets target must match bootstrap OAW_SECRETS_DIR default "
        f"({SECRETS_TARGET}), got {m.target!r}"
    )
    # The docker -v rendering carries the :ro suffix — the mount is ro at runtime.
    assert m.to_docker_volume().endswith(":ro"), (
        f"docker volume spec must end :ro, got {m.to_docker_volume()!r}"
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
