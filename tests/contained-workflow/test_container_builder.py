"""The container builder (#1108): probe behaviour and image declarations.

The probe's whole value is that it separates three outcomes a single red/green
would collapse: the capability is missing and it is OURS to fix (exit 3), the
HOST cannot nest containers so the absence is declared rather than failed (exit
4), and the probe could not reach a registry so there is no verdict at all (exit
5). Each is asserted here against a stubbed ``podman``, because the real one
needs a sysbox host and a network.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PROBE = REPO / "scripts" / "ci" / "container-builder-probe.sh"
DOCKERFILE = REPO / "containers" / "oakandwave-workflow" / "Dockerfile"


def _run_probe(tmp_path: Path, podman_script: str | None) -> subprocess.CompletedProcess[str]:
    """Drive the real probe with a stub ``podman`` (or none) ahead on PATH."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    if podman_script is not None:
        stub = bindir / "podman"
        stub.write_text(podman_script)
        stub.chmod(0o755)

    # System tools the probe needs (excluding podman, which we're stubbing).
    # PATH is REPLACED, not prepended to, so anything missing here silently
    # resolves to nothing inside a command substitution. `head` was missing
    # while this comment claimed the list was exhaustive — the probe uses
    # `head -1` on the exit-4 path, so its diagnostic was quietly empty.
    for tool in ("bash", "mktemp", "rm", "grep", "tail", "head", "cat"):
        src = shutil.which(tool)
        assert src, f"{tool} must exist to drive the probe"
        dest = bindir / tool
        if not dest.exists():
            dest.symlink_to(src)

    env = dict(os.environ, PATH=str(bindir))
    return subprocess.run(
        ["bash", str(PROBE)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_podman_absent_is_our_regression(tmp_path: Path) -> None:
    """No podman at all is a kit regression (3), never a host excuse (4)."""
    proc = _run_probe(tmp_path, None)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "not installed" in proc.stdout


def test_nesting_refusal_is_a_host_absence_not_a_failure(tmp_path: Path) -> None:
    """The signature that means "this host has no sysbox" must map to 4, so the
    preflight reports a declared absence instead of failing an adopter."""
    proc = _run_probe(
        tmp_path,
        "#!/bin/bash\n"
        'if [ "$1" = "build" ]; then\n'
        # SINGLE-quoted echo. Written double-quoted first, where the backticks
        # podman actually emits became command substitutions: the stub ran `proc`
        # twice and printed "mount  to :", so this test passed via the regex's
        # `Operation not permitted` alternative and never exercised the branch it
        # names. The probe's `.?` exists precisely to tolerate those backticks.
        "  echo 'error running container: mount `proc` to `proc`: Operation not permitted' >&2\n"
        "  exit 1\n"
        "fi\n"
        "exit 0\n",
    )
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert "will not let podman nest" in proc.stdout
    # The diagnostic must name the reason, not trail off empty — an empty reason
    # is what the double-quoted fixture silently produced.
    assert "mount `proc` to `proc`" in proc.stdout, (
        f"the reported reason should quote the runtime's own error: {proc.stdout!r}"
    )


def test_unreachable_registry_yields_no_verdict(tmp_path: Path) -> None:
    """A build failure that is NOT the nesting signature must not be reported as
    a missing capability — an offline runner is not a broken image."""
    proc = _run_probe(
        tmp_path,
        '#!/bin/bash\n'
        'if [ "$1" = "build" ]; then\n'
        '  echo "Error: initializing source docker://alpine:3.20: pinging container registry: dial tcp: lookup registry-1.docker.io: no such host" >&2\n'
        '  exit 125\n'
        'fi\n'
        'exit 0\n',
    )
    assert proc.returncode == 5, proc.stdout + proc.stderr
    assert "registry unreachable" in proc.stdout


def test_build_succeeds_but_run_fails_on_networking_is_ours(tmp_path: Path) -> None:
    """The nftables gap: build passes, run fails. It ships in OUR image, so it
    must be 3 — this is the case that would have escaped a build-only probe."""
    proc = _run_probe(
        tmp_path,
        '#!/bin/bash\n'
        'if [ "$1" = "run" ]; then\n'
        '  echo "Error: netavark: nftables error: unable to execute \\"nft\\": No such file or directory" >&2\n'
        '  exit 126\n'
        'fi\n'
        'exit 0\n',
    )
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "networking is incomplete" in proc.stdout


def test_capability_present(tmp_path: Path) -> None:
    proc = _run_probe(
        tmp_path,
        '#!/bin/bash\n'
        'if [ "$1" = "run" ]; then echo built-in-sandbox; fi\n'
        'exit 0\n',
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "built and ran" in proc.stdout


def test_wrong_output_is_ours_not_a_host_excuse(tmp_path: Path) -> None:
    """A podman that exits 0 and prints the wrong thing must not score a PASS —
    and must be 3, not 4. By that point it has already built AND run a container
    with a RUN step, so nesting provably works and the host cannot be at fault.
    Reporting 4 would route the one provably-working-but-wrong case to a
    non-failing "unavailable on this host" INFO."""
    proc = _run_probe(
        tmp_path,
        "#!/bin/bash\n"
        'if [ "$1" = "run" ]; then echo something-else; fi\n'
        "exit 0\n",
    )
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "unexpected output" in proc.stdout


def test_probe_requires_a_run_step_in_its_dockerfile() -> None:
    """A COPY-only build succeeds even where nesting is impossible, so a probe
    without a RUN step would report health on a host that cannot run anything.
    That is the exact false pass this probe exists to avoid."""
    body = PROBE.read_text()
    # The heredoc is unquoted (<<DF) so ${BASE_IMAGE} expands; do not re-pin the
    # quoted form here or this test breaks on an unrelated edit, as it just did.
    recipe = body.split("<<DF\n", 1)[1].split("\nDF\n", 1)[0]
    assert "RUN " in recipe, "the probe's Dockerfile must execute a process"
    assert "FROM " in recipe, "the probe's Dockerfile must have a base"


# --- image declarations -------------------------------------------------------
# Structural, and deliberately so: these guard DECLARATIONS in the Dockerfile
# against silent removal. Comment lines are stripped first, so an assertion can
# never be satisfied by the prose that explains it.


def _dockerfile_directives() -> str:
    return "\n".join(
        line
        for line in DOCKERFILE.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )


@pytest.mark.parametrize(
    "package",
    ["podman", "nftables", "crun", "conmon", "netavark", "sudo"],
)
def test_image_installs_builder_package(package: str) -> None:
    """nftables in particular: without it `podman build` still passes and only
    `podman run` fails, so its absence hides until an agent tries to use it."""
    assert package in _dockerfile_directives()


def test_elevation_is_scoped_to_podman_not_blanket_sudo() -> None:
    """Blanket sudo would let agents strand root-owned files on the operator's
    bind mounts (a root write surfaces as uid 0 on the HOST, not idmapped back)."""
    directives = _dockerfile_directives()
    assert "ubuntu ALL=(root) NOPASSWD: /usr/bin/podman" in directives
    assert "NOPASSWD: ALL" not in directives


def test_storage_driver_is_vfs() -> None:
    """overlay cannot work under sysbox: podman falls back to fuse-overlayfs,
    which dies on /proc/sys/kernel/overflowuid from the nested userns."""
    assert 'driver = "vfs"' in _dockerfile_directives()
