"""Oracle for Story 1.2 — the me-ful sandbox config runs the container as
uid-1000 so files written to bind-mounts land host-user-owned (R-04).

Two verification altitudes:

* **Static config oracle** (``test_uid_config`` and friends). Parses the
  checked-in me-ful sandbox profile (``containers/oakandwave-workflow/
  sandbox-profile.toml``) and asserts it declares the uid-1000 identity, targets
  the uid-1000 image, and carries only ``[sandbox]`` keys aoe 1.13.0 tolerates
  (so the profile always launches). It needs no docker/aoe, so it runs *for
  real* in the stock ``pytest tests/`` lane.

* **Integration oracle** (``test_bind_mount_write_is_host_owned`` — IT-04).
  Runs the image directly via ``docker run -v`` and asserts a file the container
  writes to a bind-mount is uid-1000-owned on the host. Self-skips when docker
  or the image is absent (mirrors ``test_image.py``); ``OAKANDWAVE_REQUIRE_IMAGE``
  turns absence into a hard failure so CI proves the ownership contract.

aoe 1.13.0 finding (load-bearing): the ``[sandbox]`` schema has no native
uid/user/home_dir key — the uid-1000 identity is delivered by the image's
``USER ubuntu`` default (Story 1.1). The declared keys are the identity
contract; ``test_sandbox_keys_are_aoe_loadable`` guards the launch-safety of the
``[sandbox]`` table. The aoe-level guarantee (aoe does not override ``--user``)
is proven manually in MV-01 (``docs/contained-workflow/manual-verification.md``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SANDBOX_PROFILE = (
    REPO_ROOT / "containers" / "oakandwave-workflow" / "sandbox-profile.toml"
)

# The uid-1000 image whose `USER ubuntu` default is the operative me-ful lever.
MEFUL_IMAGE = "oakandwave-workflow:edge"

# aoe 1.13.0 SandboxConfig fields (from the 1.13.0 binary + the resolved global
# config schema) UNION the declared me-ful identity keys the Dev Spec directs.
# A `[sandbox]` key outside this union risks an aoe config-parse rejection at
# session-create — this allowlist is the launch-safety guard.
AOE_113_SANDBOX_KEYS = {
    "auto_cleanup",
    "container_runtime",
    "cpu_limit",
    "custom_instruction",
    "default_image",
    "default_terminal_mode",
    "enabled_by_default",
    "environment",
    "extra_volumes",
    "mount_ssh",
    "port_mappings",
    "selinux_relabel",
    "volume_ignores",
    "volume_ignores_strategy",
}
DECLARED_IDENTITY_KEYS = {"uid", "user", "home_dir"}


def _load() -> dict:
    """Parse the profile; a successful parse is a proxy for aoe-loadable TOML."""
    assert SANDBOX_PROFILE.is_file(), (
        f"missing me-ful sandbox profile: {SANDBOX_PROFILE}"
    )
    with SANDBOX_PROFILE.open("rb") as fh:
        return tomllib.load(fh)


def _sandbox() -> dict:
    cfg = _load()
    sandbox = cfg.get("sandbox")
    assert isinstance(sandbox, dict), "config has no [sandbox] table"
    return sandbox


def test_uid_config() -> None:
    """The named story oracle: the sandbox config sets uid 1000 (R-04).

    'Sets uid 1000' has two faces, both asserted: the config DECLARES the
    uid-1000 identity contract, and it targets the image whose default USER
    (uid-1000 `ubuntu`) is what actually runs the container as 1000 under aoe.
    """
    sandbox = _sandbox()

    # Declared identity: uid 1000.
    assert sandbox.get("uid") == 1000, (
        f"[sandbox].uid must be 1000, got {sandbox.get('uid')!r}"
    )

    # The operative lever: launch the uid-1000 image.
    assert sandbox.get("default_image") == MEFUL_IMAGE, (
        f"[sandbox].default_image must be {MEFUL_IMAGE!r} (its USER is uid-1000), "
        f"got {sandbox.get('default_image')!r}"
    )


def test_meful_identity_reuses_base_ubuntu() -> None:
    """The declared identity reuses the base image's uid-1000 `ubuntu` (TC-2)."""
    sandbox = _sandbox()
    assert sandbox.get("user") == "ubuntu", (
        f"[sandbox].user must reuse the base 'ubuntu' user, got {sandbox.get('user')!r}"
    )
    assert sandbox.get("home_dir") == "/home/ubuntu", (
        f"[sandbox].home_dir must be /home/ubuntu, got {sandbox.get('home_dir')!r}"
    )


def test_sandbox_launches_in_a_container() -> None:
    """The profile actually turns the sandbox on (else me-ful never engages)."""
    sandbox = _sandbox()
    assert sandbox.get("enabled_by_default") is True, (
        "[sandbox].enabled_by_default must be true — otherwise sessions run on "
        "the host and the me-ful uid contract never applies"
    )
    assert sandbox.get("container_runtime", "docker") == "docker", (
        "me-ful assumes rootful docker (TC-2); container_runtime must be 'docker'"
    )


def test_sandbox_keys_are_aoe_loadable() -> None:
    """Launch-safety: every [sandbox] key is one aoe 1.13.0 tolerates.

    aoe 1.13.0 has no native uid/user/home_dir sandbox key; those are declarative
    (delivered by the image USER). This guards a future edit from adding a key
    outside the tolerated union and silently breaking the profile launch.
    """
    sandbox = _sandbox()
    allowed = AOE_113_SANDBOX_KEYS | DECLARED_IDENTITY_KEYS
    unexpected = set(sandbox) - allowed
    assert not unexpected, (
        f"[sandbox] has keys aoe 1.13.0 may reject at session-create: "
        f"{sorted(unexpected)}"
    )


# --- IT-04 integration oracle (docker-gated; self-skips without the image) ----


def _skip_or_fail(msg: str, require: bool) -> None:
    if require:
        pytest.fail(msg + " (OAKANDWAVE_REQUIRE_IMAGE set)")
    pytest.skip(msg)


def test_bind_mount_write_is_host_owned() -> None:
    """IT-04 (R-04): a file the container writes to a bind-mount is uid-1000-owned
    on the host, not root.

    Runs the image directly (``docker run -v``), sidestepping the aoe stack: it
    proves the IMAGE half of me-ful — its uid-1000 ``USER`` default makes
    bind-mount writes host-user-owned. The aoe half (aoe does not override
    ``--user``) is MV-01. Self-skips when docker/the image is absent, like the
    image oracle; ``OAKANDWAVE_REQUIRE_IMAGE`` makes absence a hard failure (CI).
    """
    docker = shutil.which("docker")
    require = bool(os.environ.get("OAKANDWAVE_REQUIRE_IMAGE"))
    ref = os.environ.get("OAKANDWAVE_IMAGE", MEFUL_IMAGE)

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

    with tempfile.TemporaryDirectory() as host_dir:
        # World-writable so the container's uid can write regardless of the test
        # runner's uid; the FILE's owner (what R-04 is about) still reflects the
        # writing container's uid.
        os.chmod(host_dir, 0o777)
        proc = subprocess.run(
            [
                docker,
                "run",
                "--rm",
                "-v",
                f"{host_dir}:/mnt/bind",
                ref,
                "sh",
                "-c",
                "id -u > /mnt/bind/uid && touch /mnt/bind/probe",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, (
            f"container write to the bind-mount failed:\n{proc.stderr}"
        )

        probe = Path(host_dir) / "probe"
        assert probe.exists(), "container did not create the bind-mount file"

        in_container_uid = (Path(host_dir) / "uid").read_text().strip()
        assert in_container_uid == "1000", (
            f"container ran as uid {in_container_uid!r}, expected 1000 (non-root)"
        )

        st_uid = probe.stat().st_uid
        assert st_uid == 1000, (
            f"bind-mount file is uid {st_uid} on the host, expected 1000 "
            "(me-ful). uid 0 means the container ran as root — R-04 violated."
        )
