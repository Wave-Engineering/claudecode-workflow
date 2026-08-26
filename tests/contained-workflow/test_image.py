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
import time

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


# --- zombie reaping: tini as PID 1 (#1179) ------------------------------------
#
# Deliberately does NOT use _run_in_image / --entrypoint sh: overriding the
# entrypoint is exactly what would make these tests blind to a CMD-only
# regression (code review on #1179) — a fix that only works when nothing
# overrides the command needs a test that runs the image with NOTHING
# overridden, the same way aoe actually launches it.


def _run_detached(docker: str, ref: str, *trailing_command: str) -> str:
    """Start *ref* detached with no entrypoint override; return the container
    id. *trailing_command*, if given, is a COMMAND passed after the image ref
    (docker's own "override CMD" position) — never a docker run flag, which
    must go before the image ref. Caller must stop/remove the container."""
    proc = subprocess.run(
        [docker, "run", "-d", ref, *trailing_command],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"docker run -d failed: {proc.stderr}"
    return proc.stdout.strip()


def test_image_pid_1_is_tini_with_no_override() -> None:
    """PID 1 must be tini when the image runs with its OWN default command —
    the only launch shape that matters, since aoe supplies no entrypoint
    override and this file's other tests cannot see a CMD-only regression."""
    docker, ref = _resolve_image_or_skip()
    cid = _run_detached(docker, ref)
    try:
        time.sleep(1)
        proc = subprocess.run(
            [docker, "exec", cid, "ps", "-p", "1", "-o", "comm="],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, proc.stderr
        comm = proc.stdout.strip()
        assert comm == "tini", (
            f"PID 1 is {comm!r}, not tini — a docker run with no override must "
            "still reap zombies (#1179); a bare `sleep` here means the fix is "
            "CMD-only and silently inert against a trailing command argument"
        )
    finally:
        subprocess.run([docker, "rm", "-f", cid], capture_output=True, timeout=30)


def test_image_pid_1_is_tini_even_with_a_trailing_command_argument() -> None:
    """The exact regression code review caught: a trailing command argument to
    `docker run` (the most common keep-alive idiom for a tool like aoe) must
    NOT discard tini — that is precisely what a CMD-only fix would let happen,
    silently, with zombies resuming and nothing to indicate why."""
    docker, ref = _resolve_image_or_skip()
    cid = _run_detached(docker, ref, "sleep", "infinity")
    try:
        time.sleep(1)
        proc = subprocess.run(
            [docker, "exec", cid, "ps", "-p", "1", "-o", "comm="],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, proc.stderr
        comm = proc.stdout.strip()
        assert comm == "tini", (
            f"PID 1 is {comm!r} when `docker run <image> sleep infinity` supplies "
            "a trailing command — a CMD-only tini would be silently discarded "
            "here, which is exactly the shape that made the original fix inert"
        )
    finally:
        subprocess.run([docker, "rm", "-f", cid], capture_output=True, timeout=30)


def test_image_reaps_an_orphaned_exec_child() -> None:
    """End-to-end: a process orphaned by a `docker exec` session that exits
    must be reaped, not left as a permanent zombie — the actual fleet defect
    (#1179), reproduced against the real built image rather than a synthetic
    minimal container."""
    docker, ref = _resolve_image_or_skip()
    cid = _run_detached(docker, ref)
    try:
        time.sleep(1)
        # Mirror aoe's own shape: docker exec a session that forks a child and
        # exits before the child does, orphaning it for PID 1 to reap.
        exec_proc = subprocess.run(
            [docker, "exec", cid, "bash", "-c", 'bash -c "sleep 1; exit 0" & disown'],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert exec_proc.returncode == 0, exec_proc.stderr
        time.sleep(3)  # let the orphan exit and (if reaped) disappear
        ps_proc = subprocess.run(
            [docker, "exec", cid, "bash", "-c", 'ps -eo stat,cmd | grep -c "^Z" || echo 0'],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert ps_proc.returncode == 0, ps_proc.stderr
        zombie_count = int(ps_proc.stdout.strip().splitlines()[-1])
        assert zombie_count == 0, (
            f"{zombie_count} zombie process(es) found after an orphaned exec "
            "child exited — tini as PID 1 should have reaped it"
        )
    finally:
        subprocess.run([docker, "rm", "-f", cid], capture_output=True, timeout=30)
