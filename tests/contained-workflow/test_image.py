"""Oracle for Story 1.1 — the built oakandwave-workflow image carries the kit-dep
toolchain (R-05, R-06).

This is a *real-image* oracle, not a proxy: it runs ``docker run`` against the
built image and asserts every kit-dep tool the base is missing (Go, trivy,
shellcheck, shfmt, glab — plus bao and aws from the tool manifest, §5.2) resolves
on PATH and reports a version.

Environment gating (mirrors the repo's CC_FULL_ENV_TESTS philosophy — the 10 GB
image is not present in the stock validate/pytest lane, so its absence must
*skip*, never fail):

* ``OAKANDWAVE_IMAGE`` — image ref to probe (default ``oakandwave-workflow:edge``).
  The Makefile sets this so ``make test`` / ``make ci`` target the right tag.
* ``OAKANDWAVE_REQUIRE_IMAGE`` — when set (``make ci`` sets it after ``make
  build``), a missing docker binary or a missing image is a hard failure rather
  than a skip. This is how CI proves the image was actually built and smoked.

So ``make build`` and ``make test`` behave identically in CI and terminal
(R-06): identical skip semantics when the image is absent, identical assertions
when it is present.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

DEFAULT_IMAGE = "oakandwave-workflow:edge"

# The kit-dep tools the base image (aoe-dev-sandbox) is MISSING and this image
# bakes in (Dev Spec TC-3 / §5.2). Each entry: (binary, version-probe-args).
# `test_image_toolchain` (the story's named oracle) covers the first five; bao
# and aws round out the §5.2 manifest and the Makefile `verify` smoke.
KIT_DEP_TOOLS: list[tuple[str, list[str]]] = [
    ("go", ["version"]),
    ("trivy", ["--version"]),
    ("shellcheck", ["--version"]),
    ("shfmt", ["--version"]),
    ("glab", ["--version"]),
    ("bao", ["version"]),
    ("aws", ["--version"]),
]

# The kit's own MCP servers, baked at stable image paths by `./install` (R-09
# baking half, Story from Plan #959). Each entry is the MCP server name, which is
# BOTH the key under ~/.claude.json `.mcpServers` (registration) AND the basename
# of its prebuilt binary in ~/.local/bin (executable). Sourced from mcps.json.
KIT_MCP_SERVERS: list[str] = [
    "disc-server",
    "discord-watcher",
    "nerf-server",
    "sdlc-server",
    "wtf-server",
]


def _image_ref() -> str:
    return os.environ.get("OAKANDWAVE_IMAGE", DEFAULT_IMAGE)


def _require_image() -> bool:
    return bool(os.environ.get("OAKANDWAVE_REQUIRE_IMAGE"))


def _docker() -> str | None:
    return shutil.which("docker")


def _image_present(docker: str, ref: str) -> bool:
    result = subprocess.run(
        [docker, "image", "inspect", ref],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _resolve_image_or_skip() -> tuple[str, str]:
    """Return (docker_path, image_ref) or skip/fail per the gating env vars."""
    docker = _docker()
    if docker is None:
        msg = "docker binary not found on PATH"
        if _require_image():
            pytest.fail(msg + " (OAKANDWAVE_REQUIRE_IMAGE set)")
        pytest.skip(msg)

    ref = _image_ref()
    if not _image_present(docker, ref):
        msg = (
            f"image {ref!r} not built locally — run "
            f"`make -C containers/oakandwave-workflow build`"
        )
        if _require_image():
            pytest.fail(msg + " (OAKANDWAVE_REQUIRE_IMAGE set)")
        pytest.skip(msg)

    return docker, ref


def _run_in_image(docker: str, ref: str, script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [docker, "run", "--rm", "--entrypoint", "sh", ref, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_image_toolchain() -> None:
    """docker run reports every baked kit-dep tool present on PATH (R-05, R-06).

    Runs a single container that must resolve *every* tool via `command -v` and
    emit a version line for each — a red on any one fails the digest.
    """
    docker, ref = _resolve_image_or_skip()

    # One container, one script: `command -v` proves it's on PATH; the version
    # probe proves it actually executes. `set -e` makes the first miss fatal.
    lines = ["set -e"]
    for binary, args in KIT_DEP_TOOLS:
        lines.append(f"command -v {binary}")
        lines.append(f"{binary} {' '.join(args)}")
    script = "\n".join(lines)

    proc = _run_in_image(docker, ref, script)
    assert proc.returncode == 0, (
        f"toolchain probe failed in {ref}:\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )

    # Every tool's resolved path must appear in stdout (command -v output).
    for binary, _ in KIT_DEP_TOOLS:
        assert f"/{binary}" in proc.stdout or binary in proc.stdout, (
            f"{binary} not resolved on PATH in {ref}:\n{proc.stdout}"
        )


def test_image_kit_mcps_baked() -> None:
    """Every kit MCP server is registered AND its binary is executable (R-09).

    The baking half of R-09: `./install` (no --no-mcps) walks mcps.json and each
    server's install-remote.sh registers it under ~/.claude.json `.mcpServers`
    (three via `claude mcp add`, two via a jq edit) and drops a prebuilt linux-x64
    binary into ~/.local/bin. This asserts both halves for the uid-1000 runtime
    user: registered in config (config-exists) AND the binary is executable
    (config-works). A miss on any one server fails the digest.
    """
    docker, ref = _resolve_image_or_skip()

    servers = " ".join(KIT_MCP_SERVERS)
    script = "\n".join(
        [
            "set -e",
            'cfg="$HOME/.claude.json"',
            'test -f "$cfg"',
            f"for m in {servers}; do",
            '  jq -e --arg m "$m" \'.mcpServers[$m]\' "$cfg" >/dev/null '
            '|| { echo "NOT REGISTERED: $m"; exit 1; }',
            '  test -x "$HOME/.local/bin/$m" '
            '|| { echo "BINARY MISSING/NOT EXECUTABLE: $m"; exit 1; }',
            '  echo "BAKED: $m"',
            "done",
        ]
    )

    proc = _run_in_image(docker, ref, script)
    assert proc.returncode == 0, (
        f"kit MCP baking probe failed in {ref}:\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )

    # Every server must have emitted its BAKED confirmation line.
    for m in KIT_MCP_SERVERS:
        assert f"BAKED: {m}" in proc.stdout, (
            f"{m} not confirmed baked in {ref}:\n{proc.stdout}"
        )


def test_image_commutativity_probe_baked() -> None:
    """sdlc-server's commutativity-probe CLI resolves + runs in-image (#1014, R-09).

    sdlc-server shells out to a ``commutativity-probe`` CLI for its
    ``commutativity_verify`` tool; with the CLI absent from PATH the handler
    degrades to a ``PROBE_UNAVAILABLE`` verdict (conservative-fail). The probe is
    a Python package, and sdlc-server's ``install-remote.sh`` installs it via
    pip/pipx/venv — all of which need pip, which the base ``python3`` lacks (no
    ensurepip). The Dockerfile bakes it with ``uv tool install`` instead. This
    asserts the uid-1000 runtime user resolves the console script on PATH and it
    executes (``--help`` exits 0; a bare invocation would require a subcommand).
    """
    docker, ref = _resolve_image_or_skip()

    script = "\n".join(
        [
            "set -e",
            "command -v commutativity-probe",
            "commutativity-probe --help >/dev/null",
            "echo PROBE_OK",
        ]
    )

    proc = _run_in_image(docker, ref, script)
    assert proc.returncode == 0, (
        f"commutativity-probe not resolvable/executable in {ref}:\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    assert "PROBE_OK" in proc.stdout, (
        f"commutativity-probe did not confirm in {ref}:\n{proc.stdout}"
    )


def test_image_runs_as_non_root_uid_1000() -> None:
    """The image's default user is the uid-1000 (non-root) runtime user (R-04).

    Story 1.2 wires the aoe [sandbox] uid config; this asserts the image half of
    the me-ful contract (TC-2) — a uid-1000 user exists and is the default.
    """
    docker, ref = _resolve_image_or_skip()
    proc = _run_in_image(docker, ref, "id -u; id -un")
    assert proc.returncode == 0, proc.stderr
    uid = proc.stdout.strip().splitlines()[0]
    assert uid == "1000", f"expected default uid 1000, got {uid!r}\n{proc.stdout}"
