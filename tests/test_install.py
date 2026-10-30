"""Install/uninstall lifecycle tests in a sandboxed HOME.

Tests the full install -> check -> uninstall lifecycle by running
``install.sh`` and ``uninstall.sh`` as subprocesses with ``HOME``
overridden to a temporary directory.  The real ``$HOME`` is never
touched.

Acceptance criteria from issue #41:
- All tests use a sandboxed $HOME
- Install lifecycle: install -> check (clean) -> modify -> check (drift) -> reinstall
- Uninstall removes all artifacts including wave-status binary
- Dry-run mode verified for both install and uninstall
- Tests skip gracefully if required tools are unavailable
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Tuple

import pytest

from tests.sandbox_env import sandbox_env


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_DIR = Path(__file__).resolve().parent.parent

_INSTALL_SCRIPT = str(_REPO_DIR / "install")  # renamed from install.sh in #281
_UNINSTALL_SCRIPT = str(_REPO_DIR / "uninstall.sh")


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

_HAS_BASH = shutil.which("bash") is not None
_HAS_PYTHON3 = shutil.which("python3") is not None

_SKIP_NO_BASH = pytest.mark.skipif(not _HAS_BASH, reason="bash not available")
_SKIP_NO_PYTHON3 = pytest.mark.skipif(
    not _HAS_PYTHON3, reason="python3 not available (needed for zipapp build)"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sandbox_home(tmp_path: Path) -> Path:
    """Create a sandboxed HOME directory mimicking the real structure.

    Layout::

        tmp/
          home/
            .local/bin/
            .claude/
              skills/
              config/

    Returns the ``home/`` path to be used as ``HOME``.
    """
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".claude" / "skills").mkdir(parents=True)
    return home


def _make_env(home: Path) -> dict[str, str]:
    """Build a subprocess environment with HOME, the XDG dirs and uv's tool dirs
    all under the sandbox. HOME alone let uninstall.sh reach the real uv tool dir
    through the inherited XDG_DATA_HOME and wipe crewchat-clients on 2026-10-29
    (see tests/sandbox_env.py)."""
    return sandbox_env(home)


def _stubbed_env(home: Path, mcp_list: str = "") -> dict[str, str]:
    """``_make_env(home)`` with stub ``curl`` and ``claude`` first on PATH (#1361).

    uninstall.sh used to run every mcps.json server's real remote uninstaller from inside
    this suite: real network, and a real ``claude`` (#1152's hang on a dev box). The
    ``curl`` stub logs each URL to ``$STUB_CURL_LOG`` and serves a script that echoes its
    arguments. The ``claude`` stub logs its arguments to ``$STUB_CLAUDE_LOG``, prints
    ``mcp_list`` for ``mcp list``, exits 1 for ``mcp get`` and 0 for anything else. The
    crewchat uninstall never checks its socket. The stubs and the sandboxed uv keep it a
    no-op: the ``claude`` stub's ``mcp get`` reports nothing registered, and uv looks only
    in the sandbox's tool dir.
    """
    stubs = home.parent / "stubs"
    stubs.mkdir(exist_ok=True)
    claude = stubs / "claude"
    claude.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >>"$STUB_CLAUDE_LOG"\n'
        '[[ "$1 $2" == "mcp list" ]] && { cat "$STUB_MCP_LIST"; exit 0; }\n'
        '[[ "$1 $2" == "mcp get" ]] && exit 1\n'
        "exit 0\n"
    )
    curl = stubs / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "${@: -1}" >>"$STUB_CURL_LOG"\n'
        "echo 'echo \"stub-remote $*\"'\n"
    )
    for stub in (claude, curl):
        stub.chmod(0o755)
    listing = home.parent / "mcp-list.txt"
    listing.write_text(mcp_list)

    env = _make_env(home)
    env["PATH"] = f"{stubs}:{env['PATH']}"
    env["STUB_MCP_LIST"] = str(listing)
    env["STUB_CURL_LOG"] = str(home.parent / "curl.log")
    env["STUB_CLAUDE_LOG"] = str(home.parent / "claude.log")
    env["CREWCHAT_SOCKET"] = str(home.parent / "no-daemon.sock")
    return env


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _with_no_mcps(args: list[str]) -> list[str]:
    """Prepend ``--no-mcps`` unless the caller already opted out of MCP install.

    WHY (#1070). Each real ``./install`` here fetched FIVE MCP server binaries
    over the network — measured at ~84% of install wall-clock — and **not one
    assertion in this file examines them**. Grep for `disc-server`/`sdlc-server`:
    the only hits are a documentation path and a comment. Ten tests were paying
    the dominant cost of the suite for coverage that does not exist.

    That cost was not merely slow. On a hosted runner it pushed ``install`` past
    the 120s per-invocation timeout and took CI red on PR #1112 — five failures
    on a changeset that touched nothing install-related. A gate that fails for
    reasons unrelated to the diff teaches people to disbelieve it.

    **Nothing tested today stops being tested.** The coverage this skips is held
    somewhere strictly better: the image build runs a real, complete ``./install``
    and fails unless every server in ``mcps.json`` is registered in
    ``~/.claude.json`` **and** its binary is executable. That is the artifact that
    actually ships, so the division is: the image proves a full install works,
    this file proves the BEHAVIOURS around install — prune, drift, uninstall,
    dry-run, exclusions.

    Deliberately NOT the shared-fixture approach: every test still performs its
    own real install, so the 39-of-47-absolute-symlinks hazard that makes a naive
    ``cp -a`` of an installed tree unsafe simply never arises.

    ``--local`` already implies ``--no-mcps`` (install:219); passing both is
    harmless, but leaving it to the implication would couple this helper to that
    detail, so it is skipped explicitly.
    """
    if "--no-mcps" in args or "--local" in args:
        return args
    return ["--no-mcps"] + args


def run_install(
    args: list[str],
    home: Path,
) -> Tuple[int, str, str]:
    """Run ``install.sh <args>`` with HOME overridden.

    Returns ``(returncode, stdout, stderr)``.
    """
    result = subprocess.run(
        ["bash", _INSTALL_SCRIPT] + _with_no_mcps(args),
        capture_output=True,
        text=True,
        env=_make_env(home),
        timeout=120,
    )
    return result.returncode, result.stdout, result.stderr


def _install_ok(rc: int, out: str, err: str) -> bool:
    """install exits with the COUNT of missing dependencies — a late-stage audit
    unrelated to the install/merge work. In a sandbox HOME those deps are
    legitimately absent, so a non-zero exit is expected; accept it as long as it's
    the dep audit (not a real crash). See #753.
    """
    if rc == 0:
        return True
    combined = (out or "") + (err or "")
    return "dependenc" in combined and "missing" in combined


def run_uninstall(
    args: list[str],
    home: Path,
    *,
    mcp_list: str = "",
) -> Tuple[int, str, str]:
    """Run ``uninstall.sh <args>`` with HOME overridden and ``curl``/``claude`` stubbed.

    Returns ``(returncode, stdout, stderr)``.
    """
    result = subprocess.run(
        ["bash", _UNINSTALL_SCRIPT] + args,
        capture_output=True,
        text=True,
        env=_stubbed_env(home, mcp_list),
        timeout=120,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Inventory helpers — derive the expected artifacts from the repo layout
# ---------------------------------------------------------------------------

def _expected_skill_dirs() -> list[str]:
    """Return skill directory names (e.g. ['ccfold', 'cryo', ...])."""
    return sorted(
        d.name
        for d in (_REPO_DIR / "skills").iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    )


def _expected_helper_scripts() -> list[str]:
    """Return helper script basenames installed to ~/.local/bin/ from skills.

    Only executable non-.md files qualify — .md files are installed into the
    skill directory, and a non-executable helper (e.g. bundle.mjs) lives only
    in the Cellar, with no PATH link (#1360).
    """
    helpers = []
    for skill_dir in (_REPO_DIR / "skills").iterdir():
        if not skill_dir.is_dir():
            continue
        for f in skill_dir.iterdir():
            if f.is_file() and not f.name.endswith(".md") and os.access(f, os.X_OK):
                helpers.append(f.name)
    return sorted(helpers)


def _expected_skill_content_md() -> dict[str, list[str]]:
    """Return a mapping of skill_name -> list of .md filenames (excluding SKILL.md).

    These files are installed into ~/.claude/skills/<skill_name>/ rather than
    ~/.local/bin/.
    """
    result: dict[str, list[str]] = {}
    for skill_dir in (_REPO_DIR / "skills").iterdir():
        if not skill_dir.is_dir():
            continue
        md_files = []
        for f in skill_dir.iterdir():
            if f.is_file() and f.name.endswith(".md") and f.name != "SKILL.md":
                md_files.append(f.name)
        if md_files:
            result[skill_dir.name] = sorted(md_files)
    return result


def _expected_standalone_scripts() -> list[str]:
    """Return standalone script basenames from scripts/ (excluding ci/ dir)."""
    scripts = []
    for f in (_REPO_DIR / "scripts").iterdir():
        if f.is_file():
            scripts.append(f.name)
    return sorted(scripts)


def _expected_package_artifacts() -> list[str]:
    """Return package artifact names (e.g. ['wave-status'])."""
    artifacts = []
    src_dir = _REPO_DIR / "src"
    if src_dir.is_dir():
        for pkg_dir in src_dir.iterdir():
            if pkg_dir.is_dir() and (pkg_dir / "__main__.py").exists():
                artifacts.append(pkg_dir.name.replace("_", "-"))
    return sorted(artifacts)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@_SKIP_NO_BASH
@_SKIP_NO_PYTHON3
class TestInstallCreatesArtifacts:
    """install.sh copies skills, scripts, config, AND builds + installs
    wave-status to $HOME/.local/bin/."""

    def test_install_creates_artifacts(self, sandbox_home: Path) -> None:
        rc, out, err = run_install([], sandbox_home)
        assert _install_ok(rc, out, err), f"install.sh failed (rc={rc}):\nstdout: {out}\nstderr: {err}"

        # --- Skills: SKILL.md installed for each skill ---
        skills_dir = sandbox_home / ".claude" / "skills"
        for skill_name in _expected_skill_dirs():
            skill_md = skills_dir / skill_name / "SKILL.md"
            assert skill_md.exists(), f"Missing skill: {skill_md}"

        # --- Helper scripts from skills (e.g. job-fetch) ---
        bin_dir = sandbox_home / ".local" / "bin"
        for helper in _expected_helper_scripts():
            assert (bin_dir / helper).exists(), f"Missing helper script: {helper}"

        # --- Skill content .md files (e.g. introduction.md) ---
        for skill_name, md_files in _expected_skill_content_md().items():
            for md_file in md_files:
                md_path = skills_dir / skill_name / md_file
                assert md_path.exists(), (
                    f"Missing skill content file: {skill_name}/{md_file}"
                )
                # .md files must NOT be executable
                assert not os.access(str(md_path), os.X_OK), (
                    f"Skill content file should not be executable: {md_path}"
                )

        # --- Standalone scripts ---
        for script_name in _expected_standalone_scripts():
            assert (bin_dir / script_name).exists(), (
                f"Missing standalone script: {script_name}"
            )

        # --- Config: statusline-command.sh ---
        statusline = sandbox_home / ".claude" / "statusline-command.sh"
        assert statusline.exists(), "Missing config: statusline-command.sh"

        # --- Package artifacts (wave-status zipapp) ---
        for artifact in _expected_package_artifacts():
            assert (bin_dir / artifact).exists(), (
                f"Missing package artifact: {artifact}"
            )

        # --- Kit-canonical docs globalized (cc-workflow#792) ---
        # The canonical CLAUDE.md references these; globalizing them under
        # ~/.claude lets a /ccfold-merged CLAUDE.md resolve them in any repo.
        claude_dir = sandbox_home / ".claude"
        for rel in (
            "WAVE_AXIOMS.md",
            "docs/mcp-scoping.md",
            "docs/chat-tools.md",
            "docs/operations/log-rotation.md",
            "docs/operations/branch-protection-checklist.md",
        ):
            assert (claude_dir / rel).exists(), f"kit doc not globalized: {rel}"

    def test_install_prunes_renamed_merge_queue_doc(self, sandbox_home: Path) -> None:
        """A RENAMED kit doc must be pruned from ~/.claude, not merely superseded.

        The doc loop only copies repo->global, so a doc that changed filename
        lingers under ~/.claude forever. That matters here specifically: the old
        merge-queue-checklist.md *prescribes creating a merge queue* ("Create the
        merge queue ruleset", "add merge_group: to the on: block"), which is the
        exact policy #898 removes. Repos that don't carry their own docs resolve
        kit docs from ~/.claude, so a stale copy would keep serving the dead policy
        to every agent in the fleet.

        Plant the stale doc first — otherwise this asserts nothing, since a fresh
        sandbox never had it.
        """
        stale = sandbox_home / ".claude" / "docs" / "operations" / "merge-queue-checklist.md"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text("# Merge Queue Setup Checklist\n\nCreate the merge queue ruleset.\n")
        assert stale.exists(), "fixture failed to plant the stale doc"

        rc, out, err = run_install([], sandbox_home)
        assert _install_ok(rc, out, err), f"install.sh failed (rc={rc}):\nstdout: {out}\nstderr: {err}"

        assert not stale.exists(), (
            "deprecated kit doc survived install: docs/operations/merge-queue-checklist.md "
            "(renamed to branch-protection-checklist.md in #898; add it to DEPRECATED_PATHS)"
        )
        # ...and the replacement is there in its place.
        assert (sandbox_home / ".claude" / "docs" / "operations" / "branch-protection-checklist.md").exists()

    def test_removed_slack_skills_are_pruned(self, sandbox_home: Path) -> None:
        """#1062: /ping and /pong are pruned from an already-installed host.

        Deleting a skill from SOURCE does not uninstall it. `install` walks the
        surviving `skills/*/` and prunes WITHIN each one, so a skill that vanished
        from source is never visited — whole-skill removal is DEPRECATED_PATHS' job.

        Without this, the #1062 upgrade is worse than no change: cellar_deploy wipes
        the Cellar copy of `slackbot-send` while `~/.claude/skills/ping/SKILL.md`
        survives, leaving /ping a live skill whose helper has just been deleted.

        Plant the installed copies first — a fresh sandbox never had them, so
        without the fixture this would assert nothing.
        """
        planted = []
        for rel, body in [
            (".claude/skills/ping/SKILL.md", "---\nname: agent-say\n---\n"),
            (".claude/skills/pong/SKILL.md", "---\nname: pong\n---\n"),
            (".claude/scripts/skills/ping/slackbot-send", "#!/usr/bin/env bash\n"),
        ]:
            f = sandbox_home / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(body)
            planted.append(f)
        for f in planted:
            assert f.exists(), f"fixture failed to plant {f}"

        rc, out, err = run_install([], sandbox_home)
        assert _install_ok(rc, out, err), f"install.sh failed (rc={rc}):\nstdout: {out}\nstderr: {err}"

        for f in planted:
            assert not f.exists(), (
                f"deprecated Slack artifact survived install: {f.relative_to(sandbox_home)} "
                "(/ping and /pong were removed in #1062; add the path to DEPRECATED_PATHS)"
            )

    def test_retired_discord_watcher_artifacts_are_pruned(self, sandbox_home: Path) -> None:
        """#1344: the watcher's kit doc and one-shot wrapper leave an installed host.

        A repo that resolves kit docs from ~/.claude would otherwise keep reading
        instructions for a retired server, and the wrapper would keep arming a
        watcher that is no longer installed. Plant them first, as above.
        """
        planted = []
        for rel, body in [
            (".claude/docs/discord-watcher.md", "# Discord Watcher (Channels)\n"),
            (".claude/scripts/doorbell-oneshot.sh", "#!/usr/bin/env bash\n"),
            (".local/bin/doorbell-oneshot.sh", "#!/usr/bin/env bash\n"),
        ]:
            f = sandbox_home / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(body)
            planted.append(f)

        rc, out, err = run_install([], sandbox_home)
        assert _install_ok(rc, out, err), f"install.sh failed (rc={rc}):\nstdout: {out}\nstderr: {err}"

        for f in planted:
            assert not f.exists(), (
                f"retired discord-watcher artifact survived install: {f.relative_to(sandbox_home)} "
                "(#1344; add the path to DEPRECATED_PATHS)"
            )
        assert (sandbox_home / ".claude" / "docs" / "chat-tools.md").exists()


_DW_URL = (
    "https://raw.githubusercontent.com/Wave-Engineering/mcp-server-discord-watcher"
    "/main/scripts/install-remote.sh"
)


@_SKIP_NO_BASH
class TestDiscordWatcherRetirement:
    """#1344: `./install --mcps` uninstalls a registered discord-watcher, and only then.

    `claude` and `curl` are stubs on PATH, so nothing reaches the network or the real
    ~/.claude.json. The `curl` stub logs each URL and serves a script that echoes its
    arguments, so the test can see both what was fetched and how it was run. The
    crewchat step is pointed at a socket that doesn't exist, so it stays a no-op.
    """

    def _run_mcps(self, tmp_path: Path, home: Path, mcp_list: str) -> Tuple[int, str, Path]:
        stubs = tmp_path / "stubs"
        stubs.mkdir()
        curl_log = tmp_path / "curl.log"
        claude = stubs / "claude"
        claude.write_text(
            "#!/usr/bin/env bash\n"
            '[[ "$1 $2" == "mcp list" ]] && cat "$STUB_MCP_LIST"\n'
            "exit 0\n"
        )
        curl = stubs / "curl"
        curl.write_text(
            "#!/usr/bin/env bash\n"
            'printf "%s\\n" "${@: -1}" >>"$STUB_CURL_LOG"\n'
            "echo 'echo \"stub-remote $*\"'\n"
        )
        for stub in (claude, curl):
            stub.chmod(0o755)
        listing = tmp_path / "mcp-list.txt"
        listing.write_text(mcp_list)

        env = _make_env(home)
        env["PATH"] = f"{stubs}:{env['PATH']}"
        env["STUB_MCP_LIST"] = str(listing)
        env["STUB_CURL_LOG"] = str(curl_log)
        env["CREWCHAT_SOCKET"] = str(tmp_path / "no-daemon.sock")
        result = subprocess.run(
            ["bash", _INSTALL_SCRIPT, "--mcps"],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        return result.returncode, result.stdout + result.stderr, curl_log

    def test_registered_watcher_is_uninstalled(self, tmp_path: Path, sandbox_home: Path) -> None:
        rc, out, curl_log = self._run_mcps(
            tmp_path, sandbox_home, "discord-watcher: bun run index.ts - ✓ Connected\n"
        )
        assert _install_ok(rc, out, ""), f"install --mcps failed (rc={rc}):\n{out}"
        fetched = curl_log.read_text().splitlines()
        assert fetched.count(_DW_URL) == 1, f"the watcher's uninstaller must run once: {fetched}"
        assert "Retiring discord-watcher (#1344)" in out
        assert "stub-remote --uninstall" in out, "it must run as `bash -s -- --uninstall`"
        assert "discord-watcher uninstalled" in out

    def test_absent_watcher_is_left_alone(self, tmp_path: Path, sandbox_home: Path) -> None:
        rc, out, curl_log = self._run_mcps(
            tmp_path, sandbox_home, "sdlc-server: sdlc-server - ✓ Connected\n"
        )
        assert _install_ok(rc, out, ""), f"install --mcps failed (rc={rc}):\n{out}"
        fetched = curl_log.read_text().splitlines() if curl_log.exists() else []
        assert fetched, "the mcps.json servers should still be fetched"
        assert _DW_URL not in fetched, "mcps.json must not install discord-watcher any more"
        assert "Retiring discord-watcher" not in out
        assert "discord-watcher uninstalled" not in out


@_SKIP_NO_BASH
class TestUninstallStaysInSandbox:
    """uninstall.sh's `uv tool uninstall` must act on the sandbox's uv tool dir.

    Regression for 2026-10-29 06:06Z: `_make_env` set only HOME, uv found its tool
    dir through the inherited XDG_DATA_HOME, and this file's uninstall test removed
    the real crewchat-clients. The `uv` stub reports crewchat-clients as installed,
    so `install-crewchat.sh uninstall` reaches `uv tool uninstall`, and logs the dirs
    each call saw. `claude` and `curl` are stubs too, so nothing leaves the sandbox.
    """

    def test_uninstall_tools_see_sandbox_dirs(
        self, tmp_path: Path, sandbox_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stubs = tmp_path / "stubs"
        stubs.mkdir()
        uv_log = tmp_path / "uv.log"
        uv = stubs / "uv"
        uv.write_text(
            "#!/usr/bin/env bash\n"
            'printf "UV_TOOL_DIR=%s XDG_DATA_HOME=%s args=%s\\n" '
            '"$UV_TOOL_DIR" "$XDG_DATA_HOME" "$*" >>"$STUB_UV_LOG"\n'
            'case "$1 $2" in\n'
            '"tool list") echo "crewchat-clients v0.2.4" ;;\n'
            '"tool dir") echo "$UV_TOOL_DIR" ;;\n'
            "esac\n"
            "exit 0\n"
        )
        claude_log = tmp_path / "claude.log"
        claude = stubs / "claude"
        claude.write_text(
            "#!/usr/bin/env bash\n"
            'printf "CLAUDE_CONFIG_DIR=%s args=%s\\n" '
            '"${CLAUDE_CONFIG_DIR-<unset>}" "$*" >>"$STUB_CLAUDE_LOG"\n'
            '[[ "$1 $2" == "mcp get" ]] && exit 1\n'
            "exit 0\n"
        )
        curl = stubs / "curl"
        curl.write_text("#!/usr/bin/env bash\necho 'exit 0'\n")
        for stub in (uv, claude, curl):
            stub.chmod(0o755)

        # A real CLAUDE_CONFIG_DIR, as an aoe session inherits, must not reach `claude`.
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "real-claude-config"))
        env = _make_env(sandbox_home)
        env["PATH"] = f"{stubs}:{env['PATH']}"
        env["STUB_UV_LOG"] = str(uv_log)
        env["STUB_CLAUDE_LOG"] = str(claude_log)
        result = subprocess.run(
            ["bash", _UNINSTALL_SCRIPT],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        out = result.stdout + result.stderr
        assert _install_ok(result.returncode, out, ""), f"uninstall.sh failed:\n{out}"

        calls = uv_log.read_text().splitlines() if uv_log.exists() else []
        uninstalls = [c for c in calls if "args=tool uninstall" in c]
        assert uninstalls, f"the stub must see `uv tool uninstall`, or this proves nothing: {calls}"
        home = str(sandbox_home)
        for call in uninstalls:
            fields = dict(f.split("=", 1) for f in call.split(" args=")[0].split(" "))
            for var in ("UV_TOOL_DIR", "XDG_DATA_HOME"):
                assert fields[var].startswith(home + os.sep), (
                    f"`uv tool uninstall` ran with {var} outside the sandbox: {call}"
                )

        claude_calls = claude_log.read_text().splitlines() if claude_log.exists() else []
        assert claude_calls, "uninstall.sh must reach `claude`, or this proves nothing"
        for call in claude_calls:
            assert call.startswith("CLAUDE_CONFIG_DIR=<unset> "), (
                f"`claude` ran with an inherited CLAUDE_CONFIG_DIR: {call}"
            )


@_SKIP_NO_BASH
@_SKIP_NO_PYTHON3
class TestInstalledBinaryRuns:
    """After install, $HOME/.local/bin/wave-status --help exits 0."""

    def test_installed_binary_runs(self, sandbox_home: Path) -> None:
        rc, out, err = run_install([], sandbox_home)
        assert _install_ok(rc, out, err), f"install failed: {err}"

        wave_status = sandbox_home / ".local" / "bin" / "wave-status"
        assert wave_status.exists(), "wave-status not installed"

        result = subprocess.run(
            [str(wave_status), "--help"],
            capture_output=True,
            text=True,
            env=_make_env(sandbox_home),
            timeout=30,
        )
        assert result.returncode == 0, (
            f"wave-status --help failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


@_SKIP_NO_BASH
@_SKIP_NO_PYTHON3
class TestInstallCheckClean:
    """Immediately after install, install.sh --check reports no drift."""

    @pytest.mark.skipif(
        not os.environ.get("CC_FULL_ENV_TESTS"),
        reason=(
            "Full-environment integration test: asserts a PERFECTLY in-sync install, "
            "which needs the complete toolchain — sudo to write /etc/logrotate.d, secret "
            "tokens, and bun for MCP-server builds. It false-fails in ANY partial env "
            "(CI's minimal runner AND a stock dev box: /etc/ logrotate DIFFERS, tokens "
            "absent). So it runs only when CC_FULL_ENV_TESTS is set. Proper fix: scope "
            "the assertion to sandbox-controllable artifacts (skills/scripts), ignoring "
            "system/secret/build items the sandbox can't provision (cc-workflow#795)."
        ),
    )
    def test_install_check_clean(self, sandbox_home: Path) -> None:
        # Install first
        rc, out, err = run_install([], sandbox_home)
        assert _install_ok(rc, out, err), f"install failed: {err}"

        # Check — should report everything in sync
        rc, out, err = run_install(["--check"], sandbox_home)
        assert _install_ok(rc, out, err), f"--check failed: {err}"
        assert "in sync" in out.lower(), (
            f"Expected 'in sync' in check output, got:\n{out}"
        )
        assert "out of sync" not in out.lower(), (
            f"Unexpected drift detected after clean install:\n{out}"
        )


@_SKIP_NO_BASH
@_SKIP_NO_PYTHON3
class TestInstallCheckDetectsDrift:
    """After modifying an installed artifact, install.sh --check reports drift."""

    def test_install_check_detects_drift(self, sandbox_home: Path) -> None:
        # Install first
        rc, out, err = run_install([], sandbox_home)
        assert _install_ok(rc, out, err), f"install failed: {err}"

        # Modify an installed artifact to create drift
        wave_status = sandbox_home / ".local" / "bin" / "wave-status"
        assert wave_status.exists(), "wave-status not installed"
        wave_status.write_text("#!/bin/bash\necho tampered\n")

        # Check — should report drift
        rc, out, err = run_install(["--check"], sandbox_home)
        # Note: install.sh --check always exits 0, drift is reported textually
        assert _install_ok(rc, out, err), f"--check failed: {err}"
        assert "out of sync" in out.lower(), (
            f"Expected drift report in check output, got:\n{out}"
        )


@_SKIP_NO_BASH
class TestInstallDryRun:
    """install.sh --dry-run creates nothing in $HOME."""

    def test_install_dry_run(self, sandbox_home: Path) -> None:
        rc, out, err = run_install(["--dry-run"], sandbox_home)
        assert _install_ok(rc, out, err), f"--dry-run failed: {err}"

        # The dry-run output should mention "dry-run" or "Dry run"
        assert "dry run" in out.lower() or "dry-run" in out.lower(), (
            f"Expected dry-run indicator in output:\n{out}"
        )

        # Nothing should have been installed
        bin_dir = sandbox_home / ".local" / "bin"
        installed_files = list(bin_dir.iterdir())
        assert len(installed_files) == 0, (
            f"Dry run created files in bin: {installed_files}"
        )

        skills_dir = sandbox_home / ".claude" / "skills"
        skill_contents = list(skills_dir.iterdir())
        assert len(skill_contents) == 0, (
            f"Dry run created files in skills: {skill_contents}"
        )

        statusline = sandbox_home / ".claude" / "statusline-command.sh"
        assert not statusline.exists(), (
            "Dry run created statusline-command.sh"
        )


@_SKIP_NO_BASH
@_SKIP_NO_PYTHON3
class TestUninstallRemovesArtifacts:
    """After install, uninstall.sh removes skills, scripts, config,
    AND wave-status from $HOME/.local/bin/."""

    def test_uninstall_removes_artifacts(self, sandbox_home: Path) -> None:
        # Install first
        rc, out, err = run_install([], sandbox_home)
        assert _install_ok(rc, out, err), f"install failed: {err}"

        # Verify things were installed (sanity check)
        wave_status = sandbox_home / ".local" / "bin" / "wave-status"
        assert wave_status.exists(), "wave-status not installed before uninstall test"

        # Uninstall
        rc, out, err = run_uninstall([], sandbox_home)
        assert _install_ok(rc, out, err), (
            f"uninstall.sh failed (rc={rc}):\nstdout: {out}\nstderr: {err}"
        )

        # --- Skills removed ---
        skills_dir = sandbox_home / ".claude" / "skills"
        for skill_name in _expected_skill_dirs():
            skill_path = skills_dir / skill_name
            assert not skill_path.exists(), (
                f"Skill not removed: {skill_path}"
            )

        # --- Helper scripts removed ---
        bin_dir = sandbox_home / ".local" / "bin"
        for helper in _expected_helper_scripts():
            assert not (bin_dir / helper).exists(), (
                f"Helper script not removed: {helper}"
            )

        # --- Standalone scripts removed ---
        for script_name in _expected_standalone_scripts():
            assert not (bin_dir / script_name).exists(), (
                f"Standalone script not removed: {script_name}"
            )

        # --- Package artifacts removed (wave-status) ---
        for artifact in _expected_package_artifacts():
            assert not (bin_dir / artifact).exists(), (
                f"Package artifact not removed: {artifact}"
            )

        # --- Config removed ---
        statusline = sandbox_home / ".claude" / "statusline-command.sh"
        assert not statusline.exists(), "statusline-command.sh not removed"

        # --- Nothing left the sandbox (#1361) ---
        stub_root = sandbox_home.parent
        assert not (stub_root / "curl.log").exists(), (
            f"uninstall fetched a remote script: {(stub_root / 'curl.log').read_text()}"
        )
        claude_calls = (stub_root / "claude.log").read_text().splitlines()
        assert "mcp list" in claude_calls, "uninstall must read registrations through the stub"


@_SKIP_NO_BASH
class TestUninstallMcpRegistration:
    """uninstall.sh fetches a server's remote uninstaller only when it is registered (#1361)."""

    def test_only_registered_servers_are_uninstalled(self, sandbox_home: Path) -> None:
        rc, out, err = run_uninstall(
            ["--mcps"], sandbox_home, mcp_list="sdlc-server: sdlc-server - ✓ Connected\n"
        )
        assert _install_ok(rc, out, err), f"uninstall --mcps failed (rc={rc}):\n{out}\n{err}"
        mcps = json.loads((_REPO_DIR / "mcps.json").read_text())["mcps"]
        fetched = (sandbox_home.parent / "curl.log").read_text().splitlines()
        assert fetched == [mcps["sdlc-server"]["install_url"]]
        assert out.count("stub-remote --uninstall") == 1
        assert "Not registered: wtf-server" in out

    def test_a_longer_name_is_not_a_registration(self, sandbox_home: Path) -> None:
        # The name must head its line: `sdlc-server-dev` is not `sdlc-server`, and a name
        # in another server's command is not a registration either.
        rc, out, err = run_uninstall(
            ["--mcps"],
            sandbox_home,
            mcp_list="sdlc-server-dev: /opt/sdlc-server --dev - ✓ Connected\n",
        )
        assert _install_ok(rc, out, err), f"uninstall --mcps failed (rc={rc}):\n{out}\n{err}"
        assert not (sandbox_home.parent / "curl.log").exists()
        assert "Not registered: sdlc-server" in out

    def test_unreadable_registrations_skip_removal(self, sandbox_home: Path) -> None:
        env = _stubbed_env(sandbox_home)
        claude = sandbox_home.parent / "stubs" / "claude"
        claude.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"$STUB_CLAUDE_LOG"\nexit 1\n')
        result = subprocess.run(
            ["bash", _UNINSTALL_SCRIPT, "--mcps"],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        out = result.stdout + result.stderr
        assert _install_ok(result.returncode, out, ""), f"uninstall --mcps failed:\n{out}"
        assert not (sandbox_home.parent / "curl.log").exists()
        assert "cannot read MCP registrations (claude mcp list failed) — skipping MCP removal" in out


@_SKIP_NO_BASH
@_SKIP_NO_PYTHON3
class TestUninstallDryRun:
    """uninstall.sh --dry-run removes nothing from $HOME."""

    def test_uninstall_dry_run(self, sandbox_home: Path) -> None:
        # Install first
        rc, out, err = run_install([], sandbox_home)
        assert _install_ok(rc, out, err), f"install failed: {err}"

        # Collect pre-uninstall state
        bin_dir = sandbox_home / ".local" / "bin"
        pre_files = set(f.name for f in bin_dir.iterdir())
        assert len(pre_files) > 0, "Nothing installed — can't test dry-run"

        # Dry-run uninstall
        rc, out, err = run_uninstall(
            ["--dry-run"], sandbox_home, mcp_list="sdlc-server: sdlc-server - ✓ Connected\n"
        )
        assert _install_ok(rc, out, err), f"--dry-run uninstall failed: {err}"

        # A global dry-run still lists a registered server, and only that one (#1361).
        assert "Would uninstall MCP server: sdlc-server" in out
        assert "Would uninstall MCP server: wtf-server" not in out
        assert not (sandbox_home.parent / "curl.log").exists()

        # Output should mention dry-run
        assert "dry run" in out.lower() or "dry-run" in out.lower(), (
            f"Expected dry-run indicator in output:\n{out}"
        )

        # Nothing should have been removed
        post_files = set(f.name for f in bin_dir.iterdir())
        assert pre_files == post_files, (
            f"Dry-run removed files: {pre_files - post_files}"
        )

        # Skills should still exist
        skills_dir = sandbox_home / ".claude" / "skills"
        for skill_name in _expected_skill_dirs():
            assert (skills_dir / skill_name).exists(), (
                f"Dry-run removed skill: {skill_name}"
            )


@_SKIP_NO_BASH
class TestInstallSyntheticTree:
    """End-to-end install behavior on a synthetic ``scripts/`` layout.

    Builds a throwaway "repo" containing a stub install + scripts/ tree,
    then exercises recursion, executable preservation, and exclusion of
    noise subtrees (tests/, fixtures/, __pycache__, .pytest_cache).
    """

    def _build_synthetic_repo(self, tmp_path: Path) -> Path:
        """Materialize a minimal repo at ``tmp_path/repo`` with just scripts/.

        Strips the install script down to the script-copy block alone so the
        test stays fast and doesn't pull in skills/config/MCP machinery.
        """
        repo = tmp_path / "repo"
        scripts = repo / "scripts"
        scripts.mkdir(parents=True)

        # Top-level (flat) script.
        (scripts / "foo").write_text("#!/bin/bash\necho foo\n")
        os.chmod(scripts / "foo", 0o755)

        # Nested executable.
        sub = scripts / "sub"
        sub.mkdir()
        (sub / "bar").write_text("#!/bin/bash\necho bar\n")
        os.chmod(sub / "bar", 0o755)

        # Doubly-nested executable.
        baz = sub / "baz"
        baz.mkdir()
        (baz / "qux").write_text("#!/bin/bash\necho qux\n")
        os.chmod(baz / "qux", 0o755)

        # Non-executable doc.
        (sub / "README.md").write_text("# sub\n")

        # Excluded noise subtree.
        excluded = scripts / "excluded" / "__pycache__"
        excluded.mkdir(parents=True)
        (excluded / "y").write_text("compiled\n")

        # The real install script sources scripts/ci/check-deps.sh at the end
        # for the post-install dep gate. Stub it so the synthetic repo doesn't
        # need the full ci/ tree.
        ci_dir = scripts / "ci"
        ci_dir.mkdir()
        (ci_dir / "check-deps.sh").write_text("check_deps() { return 0; }\n")
        # install sources the shared settings merge (#1360).
        (scripts / "lib").mkdir()
        shutil.copy(_REPO_DIR / "scripts" / "lib" / "settings-merge.sh", scripts / "lib")

        # Drop in a copy of the real install script so we run the actual code.
        shutil.copy(_REPO_DIR / "install", repo / "install")
        os.chmod(repo / "install", 0o755)
        return repo

    def test_recursive_install_with_exclusions(self, tmp_path: Path) -> None:
        repo = self._build_synthetic_repo(tmp_path)
        home = tmp_path / "home"
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".claude" / "skills").mkdir(parents=True)

        env = _make_env(home)
        # --scripts skips skills/config/mcps/crystallizer; depcheck still
        # runs but is harmless on an empty repo.
        result = subprocess.run(
            ["bash", str(repo / "install"), "--scripts"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"install failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Cellar + symlink-farm contract (#560, recommendation B):
        # - Cellar at ~/.claude/scripts/ holds the full recursive tree
        #   (top-level + nested), preserving exec bits and structure.
        # - ~/.local/bin/ holds symlinks ONLY for top-level Cellar entries.
        cellar = home / ".claude" / "scripts"
        bin_dir = home / ".local" / "bin"

        # Cellar mirrors the source tree end-to-end (top-level + nested).
        assert (cellar / "foo").exists(), "flat top-level script missing in Cellar"
        assert (cellar / "sub" / "bar").exists(), (
            "single-nested script missing in Cellar"
        )
        assert (cellar / "sub" / "baz" / "qux").exists(), (
            "double-nested script missing in Cellar"
        )
        # Executable bits preserved end-to-end in the Cellar.
        assert os.access(str(cellar / "foo"), os.X_OK)
        assert os.access(str(cellar / "sub" / "bar"), os.X_OK)
        assert os.access(str(cellar / "sub" / "baz" / "qux"), os.X_OK)
        # Non-executable doc copied to Cellar, NOT marked executable.
        readme = cellar / "sub" / "README.md"
        assert readme.exists(), "non-executable doc not copied to Cellar"
        assert not os.access(str(readme), os.X_OK), (
            "non-executable doc was incorrectly chmod'd +x in Cellar"
        )
        # Excluded subtree not copied to Cellar either.
        assert not (cellar / "excluded" / "__pycache__" / "y").exists(), (
            "excluded __pycache__ subtree was copied"
        )

        # Symlink farm: only top-level entries are symlinked into ~/.local/bin/.
        # Nested entries (sub/, sub/baz/, etc.) stay Cellar-only per
        # recommendation B from #560.
        assert (bin_dir / "foo").is_symlink(), (
            "top-level script should be a symlink in the farm"
        )
        assert not (bin_dir / "sub").exists(), (
            "subtree directories should NOT be mirrored into ~/.local/bin/ "
            "(granularity B per #560)"
        )

    def test_prune_removes_orphan(self, tmp_path: Path) -> None:
        """--prune (legacy, manifest-based) removes ~/.local/bin/<rel> files
        whose source under scripts/<rel> no longer exists.

        Note: under #560's Cellar layout, structural orphan rot is killed
        by the cellar-wipe at install time, so --prune is effectively a
        backwards-compat code path. We exercise it with a synthetic
        manifest entry to confirm it still functions.
        """
        repo = self._build_synthetic_repo(tmp_path)
        home = tmp_path / "home"
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".claude" / "skills").mkdir(parents=True)

        env = _make_env(home)

        # Install once.
        _proc = subprocess.run(
            ["bash", str(repo / "install"), "--scripts"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        rc, out, err = _proc.returncode, _proc.stdout, _proc.stderr
        assert _install_ok(rc, out, err), "first install failed"

        # Plant an orphan (manifest-tracked plain file under ~/.local/bin/).
        # The legacy --prune walks the manifest and removes plain files
        # whose source under scripts/ no longer exists.
        bin_dir = home / ".local" / "bin"
        orphan = bin_dir / "ghost"
        orphan.write_text("#!/bin/bash\necho gone\n")
        os.chmod(orphan, 0o755)
        manifest = bin_dir / ".cc-workflow-manifest"
        with manifest.open("a") as fh:
            fh.write("ghost\n")

        # Prune (non-interactive).
        result = subprocess.run(
            ["bash", str(repo / "install"), "--prune", "--yes"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"prune failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert not orphan.exists(), "orphan was not pruned"
        # Backup retained.
        assert (bin_dir / "ghost.bak").exists(), "orphan backup missing"
        # Cellar live files still present (top-level + nested).
        cellar = home / ".claude" / "scripts"
        assert (cellar / "foo").exists(), "prune removed live top-level Cellar entry"
        assert (cellar / "sub" / "bar").exists(), (
            "prune removed live nested Cellar entry"
        )
        # Symlink farm top-level still present.
        assert (bin_dir / "foo").is_symlink(), (
            "prune removed live top-level symlink-farm entry"
        )

    def test_check_reports_nested_drift(self, tmp_path: Path) -> None:
        """--check reports drift for missing nested files in the Cellar.

        Under #560 the Cellar (~/.claude/scripts/) holds the full recursive
        tree (top-level + nested). Deleting a nested Cellar entry should
        surface as drift — the tree no longer matches the source.
        """
        repo = self._build_synthetic_repo(tmp_path)
        home = tmp_path / "home"
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".claude" / "skills").mkdir(parents=True)

        env = _make_env(home)

        _proc = subprocess.run(
            ["bash", str(repo / "install"), "--scripts"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        rc, out, err = _proc.returncode, _proc.stdout, _proc.stderr
        assert _install_ok(rc, out, err), "install failed"

        # Delete a nested Cellar file; --check should flag the drift.
        target = home / ".claude" / "scripts" / "sub" / "bar"
        assert target.exists()
        target.unlink()

        result = subprocess.run(
            ["bash", str(repo / "install"), "--check"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        assert result.returncode == 0, "check exited non-zero"
        assert "sub/bar" in result.stdout, (
            f"--check did not report missing nested Cellar file:\n{result.stdout}"
        )
        assert "out of sync" in result.stdout.lower(), (
            f"--check did not flag drift:\n{result.stdout}"
        )


def run_install_cwd(
    args: list[str],
    home: Path,
    cwd: Path,
) -> Tuple[int, str, str]:
    """Run ``install <args>`` with HOME overridden AND a specific cwd.

    ``--local`` keys its install root off ``$(pwd)``, not ``$HOME``, so the
    subprocess cwd must be set to the project directory under test.
    """
    result = subprocess.run(
        ["bash", _INSTALL_SCRIPT] + _with_no_mcps(args),
        capture_output=True,
        text=True,
        env=_make_env(home),
        cwd=str(cwd),
        timeout=120,
    )
    return result.returncode, result.stdout, result.stderr


@_SKIP_NO_BASH
@_SKIP_NO_PYTHON3
class TestLocalScopeInstall:
    """``./install --local`` installs into ``<cwd>/.claude/`` instead of
    global ``$HOME``, leaving the global fleet install untouched."""

    def test_local_scope_placement(self, tmp_path: Path) -> None:
        """--local from cwd=project lands skills, Cellar, farm, and settings
        all under project/.claude/."""
        home = tmp_path / "home"
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".claude" / "skills").mkdir(parents=True)
        project = tmp_path / "project"
        project.mkdir()

        rc, out, err = run_install_cwd(["--local"], home, project)
        assert _install_ok(rc, out, err), (
            f"--local install failed (rc={rc}):\nstdout: {out}\nstderr: {err}"
        )

        proj_claude = project / ".claude"
        # Skills land under project/.claude/skills/<name>/SKILL.md.
        for skill_name in _expected_skill_dirs():
            assert (proj_claude / "skills" / skill_name / "SKILL.md").exists(), (
                f"Missing project-local skill: {skill_name}"
            )
        # Cellar at project/.claude/scripts (top-level scripts present).
        assert (proj_claude / "scripts").is_dir(), "project-local Cellar missing"
        # Symlink farm at project/.claude/bin (NOT .claude/scripts).
        assert (proj_claude / "bin").is_dir(), "project-local farm (bin/) missing"
        for script_name in _expected_standalone_scripts():
            assert (proj_claude / "scripts" / script_name).exists(), (
                f"Missing standalone script in project Cellar: {script_name}"
            )
        # Settings merged/installed into project/.claude/settings.json.
        assert (proj_claude / "settings.json").exists(), (
            "project-local settings.json missing"
        )
        # Kit-canonical docs globalized under the project too (cc-workflow#792).
        assert (proj_claude / "WAVE_AXIOMS.md").exists(), (
            "project-local WAVE_AXIOMS.md missing"
        )
        assert (proj_claude / "docs" / "operations" / "log-rotation.md").exists(), (
            "project-local kit docs/ not globalized"
        )

    def test_local_leaves_global_untouched(self, tmp_path: Path) -> None:
        """After --local, the global $HOME/.claude and $HOME/.local/bin stay
        empty/absent — no fleet contamination."""
        home = tmp_path / "home"
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".claude" / "skills").mkdir(parents=True)
        project = tmp_path / "project"
        project.mkdir()

        rc, out, err = run_install_cwd(["--local"], home, project)
        assert _install_ok(rc, out, err), f"--local install failed: {err}"

        # Global skills dir empty.
        global_skills = home / ".claude" / "skills"
        assert list(global_skills.iterdir()) == [], (
            f"--local contaminated global skills: {list(global_skills.iterdir())}"
        )
        # Global bin empty.
        global_bin = home / ".local" / "bin"
        assert list(global_bin.iterdir()) == [], (
            f"--local contaminated global bin: {list(global_bin.iterdir())}"
        )
        # No global settings.json created.
        assert not (home / ".claude" / "settings.json").exists(), (
            "--local created a global settings.json"
        )
        # No global Cellar.
        assert not (home / ".claude" / "scripts").exists(), (
            "--local created a global Cellar"
        )

    def test_default_install_unchanged(self, sandbox_home: Path) -> None:
        """No flag → lands in $HOME as today AND a project-local .claude/ is
        NOT created in cwd (proves --local is strictly opt-in)."""
        # Run default install from a project dir; nothing should land there.
        home = sandbox_home
        project = home.parent / "project"
        project.mkdir()

        rc, out, err = run_install_cwd([], home, project)
        assert _install_ok(rc, out, err), f"default install failed: {err}"

        # Global path populated as usual.
        assert (home / ".claude" / "skills").iterdir(), "global skills not installed"
        wave_status = home / ".local" / "bin" / "wave-status"
        assert wave_status.exists(), "wave-status not in global bin"
        # The cwd project dir must NOT have a .claude/ created by a default run.
        assert not (project / ".claude").exists(), (
            "default (no --local) install created a project-local .claude/"
        )

    def test_local_uninstall(self, tmp_path: Path) -> None:
        """uninstall.sh --local removes the project-scoped install while the
        global install is untouched."""
        home = tmp_path / "home"
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".claude" / "skills").mkdir(parents=True)
        project = tmp_path / "project"
        project.mkdir()

        rc, out, err = run_install_cwd(["--local"], home, project)
        assert _install_ok(rc, out, err), f"--local install failed: {err}"
        # Sanity: project install present.
        assert (project / ".claude" / "skills").is_dir()

        # Uninstall --local from the project dir.
        result = subprocess.run(
            ["bash", _UNINSTALL_SCRIPT, "--local"],
            capture_output=True,
            text=True,
            env=_stubbed_env(home),
            cwd=str(project),
            timeout=120,
        )
        assert _install_ok(result.returncode, result.stdout, result.stderr), (
            f"--local uninstall failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        # --local never touches MCP servers (#815): no header, no fetch.
        assert "Removing MCP servers" not in result.stdout
        assert not (tmp_path / "curl.log").exists()

        # Project skills removed.
        for skill_name in _expected_skill_dirs():
            assert not (project / ".claude" / "skills" / skill_name).exists(), (
                f"project-local skill not removed: {skill_name}"
            )
        # Project statusline removed.
        assert not (project / ".claude" / "statusline-command.sh").exists(), (
            "project-local statusline not removed"
        )
        # Project Cellar removed.
        assert not (project / ".claude" / "scripts").exists(), (
            "project-local Cellar (.claude/scripts) not removed by --local uninstall"
        )
        # Global install never existed → still clean.
        assert list((home / ".claude" / "skills").iterdir()) == [], (
            "--local uninstall touched global skills"
        )

    def test_local_uninstall_dry_run_lists_no_mcps(self, tmp_path: Path) -> None:
        """#815: `uninstall.sh --local --dry-run` lists no MCP server, even with one registered."""
        home = tmp_path / "home"
        (home / ".claude" / "skills").mkdir(parents=True)
        project = tmp_path / "project"
        project.mkdir()
        result = subprocess.run(
            ["bash", _UNINSTALL_SCRIPT, "--local", "--dry-run"],
            capture_output=True,
            text=True,
            env=_stubbed_env(home, "sdlc-server: sdlc-server - ✓ Connected\n"),
            cwd=str(project),
            timeout=120,
        )
        assert _install_ok(result.returncode, result.stdout, result.stderr), result.stderr
        assert "Would uninstall MCP server:" not in result.stdout
        assert not (tmp_path / "curl.log").exists()


@_SKIP_NO_BASH
@_SKIP_NO_PYTHON3
class TestReinstallOverwrites:
    """Installing twice succeeds without errors (second install overwrites)."""

    def test_reinstall_overwrites(self, sandbox_home: Path) -> None:
        # First install
        rc, out, err = run_install([], sandbox_home)
        assert _install_ok(rc, out, err), f"first install failed: {err}"

        # Second install (should succeed — no errors)
        rc, out, err = run_install([], sandbox_home)
        assert _install_ok(rc, out, err), (
            f"second install failed (rc={rc}):\nstdout: {out}\nstderr: {err}"
        )

        # Artifacts should still be present
        wave_status = sandbox_home / ".local" / "bin" / "wave-status"
        assert wave_status.exists(), "wave-status missing after reinstall"

        for skill_name in _expected_skill_dirs():
            skill_md = (
                sandbox_home / ".claude" / "skills" / skill_name / "SKILL.md"
            )
            assert skill_md.exists(), (
                f"Skill missing after reinstall: {skill_name}"
            )
