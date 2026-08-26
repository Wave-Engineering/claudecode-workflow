"""Oracle for Story 1.4 — the container bootstrap (#964, Dev Spec §5.4).

The bootstrap (``containers/oakandwave-workflow/bootstrap.sh``) is the
load-bearing instrument that runs before the agent (SKETCHBOOK D7). Its whole
point is **assertion-liveness**: every silent-skip path becomes a LOGGED or
FAILING condition, never "the check that reported fine and did nothing."

These are *pure* unit oracles — no docker, no aoe. Every path the bootstrap
touches is env-injectable (defaults derived from ``$HOME``), so each test builds a
fake ``$OAW_HOME`` in a tempdir, drives the real ``bootstrap.sh`` via subprocess,
and asserts the behavior. They run for real in the stock ``pytest tests/`` lane
(bash + python3 are always present), exactly like the mount-resolver oracle.

Each of the four enumerated silent-skip paths (Dev Spec §5.4 / SKETCHBOOK D7) is
exercised **red-first** — the broken condition is constructed and the guard's
logged/failing signal is asserted — before the guard is trusted:

* missing mount   — ``test_missing_host_skills_mount_is_logged_no_dangling`` `[R-14]`
* shadowed skill  — ``test_skills_sync_image_wins_and_logs_collision`` `[R-06, R-10]`
* dangling link   — ``test_dangling_symlink_is_logged`` `[R-14]`
* missing secret  — ``test_missing_required_secret_fails_loud`` `[R-14]`

``test_bootstrap_failloud`` is the devspec-named oracle: it walks all four paths
red-first in one aggregate assertion.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

@pytest.fixture(autouse=True)
def _no_ambient_claude_config_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let the host's CLAUDE_CONFIG_DIR reach these tests.

    Run this suite INSIDE an aoe container — the dogfood ring is the whole point
    of this plan — and every test that builds its env from os.environ would
    resolve the CLI config to the real, host-mounted, FLEET-SHARED
    /root/.claude/.claude.json: asserting against the wrong file, and MUTATING it
    (a trust entry for the pytest cwd, plus fixture-shaped mcpServers merged in
    permanently, since the merge is add-if-absent and nothing later corrects it).

    Autouse rather than per-call-site: two helpers and several tests construct
    their own env dicts, and patching each is how one gets missed. Tests that
    genuinely need the variable set it explicitly AFTER this runs.
    """
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)


BOOTSTRAP = REPO_ROOT / "containers" / "oakandwave-workflow" / "bootstrap.sh"


def test_bootstrap_script_exists() -> None:
    """The deliverable exists and is executable (the story's target file)."""
    assert BOOTSTRAP.is_file(), f"missing bootstrap: {BOOTSTRAP}"
    assert os.access(BOOTSTRAP, os.X_OK), f"bootstrap is not executable: {BOOTSTRAP}"


def _make_home(
    tmp_path: Path,
    *,
    image_skills: list[str] | None = None,
    host_skills: list[str] | None = None,
    settings_json: bool = True,
    secrets: dict[str, str] | None = None,
    dangling: list[str] | None = None,
) -> Path:
    """Build a fake ``$OAW_HOME`` layout for the bootstrap to operate on.

    ``image_skills`` / ``host_skills`` are skill *names* (each a directory with a
    marker ``SKILL.md``). ``dangling`` names broken symlinks planted in the image
    skills dir. ``secrets`` maps a filename under ``~/.secrets`` to its content
    (``.env`` supported for the env modality).
    """
    home = tmp_path / "home"
    image = home / ".claude" / "skills"
    host = home / ".oaw" / ".claude" / "skills"
    secrets_dir = home / ".secrets"
    image.mkdir(parents=True)
    host.mkdir(parents=True)
    secrets_dir.mkdir(parents=True)

    for name in image_skills or []:
        d = image / name
        d.mkdir()
        (d / "SKILL.md").write_text(f"# image skill {name}\n")
    for name in host_skills or []:
        d = host / name
        d.mkdir()
        (d / "SKILL.md").write_text(f"# host skill {name}\n")
    for name in dangling or []:
        (image / name).symlink_to(home / "does-not-exist" / name)

    if settings_json:
        # A REAL hook, not `{"hooks": {}}`. This file is the merge SOURCE for
        # sync_kit_hooks (#1086), and an empty block would make every cfgdir test
        # exercise the "nothing to merge" branch — a fixture that cannot detect the
        # bug it is fixture for. /bin/true is used so validate_hook_paths, which
        # runs later over the merged result, finds a path that genuinely resolves.
        (home / ".claude" / "settings.json").write_text(
            '{"hooks": {"SessionStart": [{"matcher": "startup", "hooks":'
            ' [{"type": "command", "command": "/bin/true"}]}]}}\n'
        )
    for fname, content in (secrets or {}).items():
        (secrets_dir / fname).write_text(content)

    return home


def _sealed_env(home: Path, **overrides: str) -> dict[str, str]:
    """Environment for driving the real ``bootstrap.sh`` without touching the host.

    ``OAW_HOME`` redirects everything the bootstrap resolves *for itself*. It does
    NOT redirect what the tools it INVOKES resolve. ``ensure_github_auth`` runs
    ``git config --global``, and git reads ``$HOME`` / ``$XDG_CONFIG_HOME`` — so a
    suite that seals only ``OAW_HOME`` writes the operator's real ``~/.gitconfig``
    on every run.

    It did exactly that for three weeks (#1130). Worse, the config it planted was
    later read back and cited in a CHANGELOG entry and a test docstring as
    independent evidence of what the operator wanted. A leak that only corrupts
    files is recoverable; one that corrupts your evidence is not.

    So: seal every home-ish variable, not only the one we named. Anything driving
    the real bootstrap MUST build its env here rather than hand-rolling
    ``{**os.environ, "OAW_HOME": ...}`` — that literal is the bug, and a new call
    site copying it is how the leak comes back.
    """
    env = dict(os.environ)
    env["OAW_HOME"] = str(home)
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    # Two more that redirect writes OUT of the tempdir and that the guard test
    # cannot see, because it only inspects the stand-in operator home:
    #   GIT_CONFIG_GLOBAL outranks $HOME for git itself, so it defeats the seal above.
    #   GLAB_CONFIG_DIR is honoured directly by ensure_gitlab_auth, which would then
    #   write a fixture token into the operator's real glab config.
    # Neither is normally set — scrub them anyway. The cost is two lines; the cost
    # of the last unsealed variable was three weeks of silently rewriting ~/.gitconfig.
    env.pop("GIT_CONFIG_GLOBAL", None)
    env.pop("GLAB_CONFIG_DIR", None)
    # SCRUB the ambient value. Run this suite INSIDE an aoe container — which is
    # the whole point of the dogfood ring — and every test here would resolve the
    # CLI config to the real, host-mounted, FLEET-SHARED /root/.claude/.claude.json:
    # assertions would look at the wrong file, and worse, the tests would mutate
    # shared state (a projects[<pytest cwd>] trust entry, and fixture-shaped
    # mcpServers merged in permanently, since the merge is add-if-absent).
    # _run_cfgdir is the only place this may be set.
    env.pop("CLAUDE_CONFIG_DIR", None)
    env.update(overrides)
    return env


def _run(home: Path, **env_overrides: str) -> subprocess.CompletedProcess[str]:
    env = _sealed_env(home, **env_overrides)
    return subprocess.run(
        ["bash", str(BOOTSTRAP)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


# --- shadowed skill (collision) — [R-06, R-10] --------------------------------


def test_skills_sync_image_wins_and_logs_collision(tmp_path: Path) -> None:
    """Image-wins / host-fills / collision-logged (AC-1).

    ``alpha`` exists in both (collision) → image wins, logged, and NOT relinked.
    ``beta`` is host-only (a gap) → filled by a symlink whose FULL target path
    resolves (the D5 self-reference bug would leave a dangling link).
    """
    home = _make_home(
        tmp_path, image_skills=["alpha"], host_skills=["alpha", "beta"]
    )
    proc = _run(home)
    assert proc.returncode == 0, proc.stderr

    # Collision logged for the shadowed host skill.
    assert "skills-sync collision" in proc.stderr
    assert "alpha" in proc.stderr

    image = home / ".claude" / "skills"
    # Image wins: alpha is still the real baked dir, not a link to the host copy.
    assert (image / "alpha").is_dir()
    assert not (image / "alpha").is_symlink()

    # Host fills the gap: beta is a symlink resolving to the host copy (full path).
    beta = image / "beta"
    assert beta.is_symlink(), "host-only skill should be symlinked in (host-fill)"
    assert beta.exists(), "host-fill link is dangling — the D5 full-target-path bug"
    assert os.readlink(beta) == str(
        home / ".oaw" / ".claude" / "skills" / "beta"
    ), "host-fill must link the FULL target path, never a bare basename"


def test_skills_sync_is_idempotent(tmp_path: Path) -> None:
    """A second boot re-links nothing and raises no error (re-runnable)."""
    home = _make_home(tmp_path, host_skills=["beta"])
    assert _run(home).returncode == 0
    proc = _run(home)
    assert proc.returncode == 0, proc.stderr
    assert "already linked" in proc.stderr
    assert (home / ".claude" / "skills" / "beta").exists()


# --- missing mount ------------------------------------------------------------


def test_missing_host_skills_mount_is_logged_no_dangling(tmp_path: Path) -> None:
    """Absent host skills overlay → logged, and NO dangling link created."""
    home = _make_home(tmp_path)  # host dir exists but is empty…
    # …now remove it entirely to model an absent mount.
    host = home / ".oaw" / ".claude" / "skills"
    (host).rmdir()
    (home / ".oaw" / ".claude").rmdir()

    proc = _run(home)
    assert proc.returncode == 0, proc.stderr
    assert "missing mount" in proc.stderr
    assert "host skills overlay" in proc.stderr
    # No dangling links were manufactured in the image dir.
    image = home / ".claude" / "skills"
    assert not any(p.is_symlink() and not p.exists() for p in image.iterdir())


# NOTE (#1086) — two tests were REMOVED here, not relocated:
# ``test_missing_settings_local_is_logged`` and
# ``test_malformed_settings_local_is_logged``. Both asserted that bootstrap warns
# about ~/.claude/settings.local.json, on the premise that Claude Code merges it
# with the user settings.json. It does not: ``localSettings`` is PROJECT-scoped
# and a settings.local.json beside the USER settings is never read, aoe or not.
# They were well-formed assertions about a file the CLI ignores — green forever,
# guarding nothing. The mount they policed is gone (mounts.d/10-memory.toml), and
# what replaced the whole idea is sync_kit_hooks, covered below.


# --- dangling link ------------------------------------------------------------


def test_dangling_symlink_is_logged(tmp_path: Path) -> None:
    """A dangling symlink in the skills dir is surfaced, not silently skipped."""
    home = _make_home(tmp_path, dangling=["ghost"])
    proc = _run(home)
    assert proc.returncode == 0, proc.stderr
    assert "dangling symlink" in proc.stderr
    assert "ghost" in proc.stderr


# --- missing secret — [R-14] --------------------------------------------------


def test_missing_required_secret_fails_loud(tmp_path: Path) -> None:
    """A missing required secret makes the bootstrap fail loudly (AC-2, R-14)."""
    home = _make_home(tmp_path)
    proc = _run(home, OAW_REQUIRED_SECRETS="FOO_TOKEN")
    assert proc.returncode != 0, "missing required secret must fail loud"
    assert "FATAL" in proc.stderr
    assert "required secret missing" in proc.stderr
    assert "FOO_TOKEN" in proc.stderr


def test_required_secret_present_as_file_passes(tmp_path: Path) -> None:
    """The green half: a present secret file (path modality) satisfies the guard."""
    home = _make_home(tmp_path, secrets={"FOO_TOKEN": "s3cr3t\n"})
    proc = _run(home, OAW_REQUIRED_SECRETS="FOO_TOKEN")
    assert proc.returncode == 0, proc.stderr
    assert "path modality" in proc.stderr


def test_required_secret_present_via_env_passes(tmp_path: Path) -> None:
    """A required secret satisfied by an env var (env modality) passes."""
    home = _make_home(tmp_path)
    proc = _run(home, OAW_REQUIRED_SECRETS="FOO_TOKEN", FOO_TOKEN="from-env")
    assert proc.returncode == 0, proc.stderr
    assert "env modality" in proc.stderr


def test_required_secret_from_manifest_fails_loud(tmp_path: Path) -> None:
    """The values-free manifest (D6) drives the required list; a missing one fails."""
    home = _make_home(tmp_path)
    manifest = home / ".secrets" / "required.manifest"
    # Two names, so the loop is proven to report EVERY missing secret rather than
    # short-circuiting on the first. Neutral second name: Slack was dropped in
    # #1062, and a fixture naming a retired integration reads as live support.
    manifest.write_text("# required secrets\nDISCORD_BOT_TOKEN\n\nSECOND_TOKEN\n")
    proc = _run(home)
    assert proc.returncode != 0
    assert "DISCORD_BOT_TOKEN" in proc.stderr
    assert "SECOND_TOKEN" in proc.stderr


def test_dotenv_is_sourced_for_env_modality(tmp_path: Path) -> None:
    """``.env`` is the env modality: a var it defines satisfies a required secret."""
    home = _make_home(tmp_path, secrets={".env": "FOO_TOKEN=via-dotenv\n"})
    proc = _run(home, OAW_REQUIRED_SECRETS="FOO_TOKEN")
    assert proc.returncode == 0, proc.stderr
    assert "sourced" in proc.stderr


# --- missing required env -----------------------------------------------------


def test_missing_required_env_fails_loud(tmp_path: Path) -> None:
    """env validation has teeth: a declared-but-unset env var fails loud."""
    home = _make_home(tmp_path)
    proc = _run(home, OAW_REQUIRED_ENV="OAW_MUST_EXIST")
    assert proc.returncode != 0
    assert "required env missing" in proc.stderr
    assert "OAW_MUST_EXIST" in proc.stderr


# --- happy path ---------------------------------------------------------------


def test_all_clean_exits_zero(tmp_path: Path) -> None:
    """Fully-provisioned boot: no fatals, exit 0.

    A fully-provisioned boot declares its required set — otherwise R-14 is inert
    and the boot is not, in fact, fully provisioned. `.env` carries POINTERS and
    the declaration; the token is a loose file (#1061).
    """
    home = _make_home(
        tmp_path,
        image_skills=["alpha"],
        host_skills=["beta"],
        secrets={
            ".env": "OAW_REQUIRED_SECRETS=discord-bot-token\n"
                    "DISCORD_TOKEN_PATH=/home/ubuntu/.secrets/discord-bot-token\n",
            "discord-bot-token": "not-a-real-token\n",
        },
    )
    proc = _run(home)
    assert proc.returncode == 0, proc.stderr
    # stderr, not stdout: the wrapper sources bootstrap and then execs the agent,
    # so anything bootstrap puts on fd 1 lands in the AGENT's stdout and corrupts
    # `claude -p --output-format json`. Every bootstrap line must be on stderr.
    assert "0 fatal(s)" in proc.stderr
    assert "0 fatal(s)" not in proc.stdout, (
        "bootstrap must write nothing to stdout — it shares fd 1 with the agent"
    )
    assert "complete" in proc.stderr
    assert "INERT" not in proc.stderr, (
        "a fully-provisioned boot must not report R-14 as inert"
    )


# --- R-14 inert-guard (#1061) --------------------------------------------------
#
# The guard these cover was, until #1061, a pass over an empty denominator: with
# neither OAW_REQUIRED_SECRETS nor a manifest, `required` was empty, the loop ran
# zero times, and validate_secrets returned success while examining nothing.


def test_r14_inert_when_nothing_declared(tmp_path: Path) -> None:
    """No declaration at all -> loud INERT warning (not a silent pass)."""
    home = _make_home(tmp_path, secrets={"discord-bot-token": "tok\n"})
    proc = _run(home)
    assert proc.returncode == 0, "an undeclared set is tolerated, not fatal"
    assert "INERT" in proc.stderr, (
        "R-14 validating nothing must announce itself; a silent pass here is "
        "indistinguishable from a real check"
    )


def test_r14_empty_declaration_is_deliberate_and_quiet(tmp_path: Path) -> None:
    """OAW_REQUIRED_SECRETS="" declares 'none needed' -> no INERT warning."""
    home = _make_home(tmp_path, secrets={".env": 'OAW_REQUIRED_SECRETS=""\n'})
    proc = _run(home)
    assert proc.returncode == 0, proc.stderr
    assert "INERT" not in proc.stderr, (
        "an explicit empty declaration is deliberate and must not warn"
    )


def test_r14_declared_but_missing_secret_is_fatal(tmp_path: Path) -> None:
    """A declared secret that is absent aborts the boot, naming the secret."""
    home = _make_home(
        tmp_path, secrets={".env": "OAW_REQUIRED_SECRETS=discord-bot-token\n"}
    )
    proc = _run(home)
    assert proc.returncode != 0, "a missing required secret must fail the boot"
    assert "discord-bot-token" in proc.stderr, "the fatal must name the secret"


def test_r14_declared_secret_as_directory_is_fatal(tmp_path: Path) -> None:
    """Docker's create-if-missing footgun: a bind whose host source is absent
    appears as an empty DIRECTORY at the target. `-f` must reject it, or the
    consumer fails later with a confusing read error instead of a named secret."""
    home = _make_home(
        tmp_path, secrets={".env": "OAW_REQUIRED_SECRETS=discord-bot-token\n"}
    )
    (home / ".secrets" / "discord-bot-token").mkdir()
    proc = _run(home)
    assert proc.returncode != 0, (
        "a directory standing in for a secret file must fail the boot"
    )
    assert "discord-bot-token" in proc.stderr


def test_missing_env_file_is_announced(tmp_path: Path) -> None:
    """No .env -> warn. Since #1061 replaced the whole-dir mount with file
    mounts, a file bind forces the secrets dir into existence, so the older
    'missing mount: secrets dir not present' warning is unreachable — this is
    the only remaining report of an unprovisioned secrets layer."""
    home = _make_home(tmp_path, secrets={"discord-bot-token": "tok\n"})
    proc = _run(home)
    assert "no " in proc.stderr and ".env" in proc.stderr, (
        "a missing .env must not be a silent skip"
    )


# --- the devspec-named aggregate oracle ---------------------------------------


def test_bootstrap_failloud(tmp_path: Path) -> None:
    """Named oracle (Dev Spec §8, Story 1.4): each silent-skip path logs/fails,
    red-first. Walks all four enumerated paths in one assertion.
    """
    # 1) shadowed skill + 3) dangling link, both LOGGED (non-fatal).
    home = _make_home(
        tmp_path,
        image_skills=["alpha"],
        host_skills=["alpha"],
        dangling=["ghost"],
    )
    # 2) missing mount: the secrets dir. This leg used to be settings.local.json,
    # until #1086 established the CLI never reads a user-level one and the mount
    # was removed — an oracle leg that had been asserting a warning about a file
    # nothing would have opened. The secrets dir is the honest replacement: it is
    # a real mount, and its absence is the R-14 silent-skip this oracle is for.
    import shutil
    shutil.rmtree(home / ".secrets")

    logged = _run(home)
    assert logged.returncode == 0, logged.stderr
    assert "skills-sync collision" in logged.stderr  # shadowed skill
    assert "dangling symlink" in logged.stderr  # dangling link
    assert "missing mount: secrets dir not present" in logged.stderr  # 2) missing mount

    # 4) missing secret FAILS LOUD (the same layout, plus a required secret).
    failed = _run(home, OAW_REQUIRED_SECRETS="MUST_HAVE_TOKEN")
    assert failed.returncode != 0, "missing required secret must fail loud (R-14)"
    assert "FATAL" in failed.stderr
    assert "MUST_HAVE_TOKEN" in failed.stderr


# --- The wiring, not just the script (#1076) ---------------------------------
#
# Everything above drives bootstrap.sh directly by subprocess. That proves the
# script WORKS and is exactly why the real defect shipped: nothing ever ran it.
# aoe `docker exec`s `claude` into the running container as a separate process
# (PID 1 is tini, keeping the container alive — cc-workflow#1179, unrelated to
# this gap), so bootstrap had no process path to the agent and every phase —
# skills-sync, settings merge, secret projection, R-14 validation — was inert
# in production while this file stayed green.
#
# These tests assert the CALLER exists. They are static (no container needed) but
# they bind to the two facts that make the wrapper work, so a future "cleanup"
# that breaks either one fails here instead of in a silent container.

ENTRYPOINT = REPO_ROOT / "containers" / "oakandwave-workflow" / "claude-entrypoint.sh"
DOCKERFILE = REPO_ROOT / "containers" / "oakandwave-workflow" / "Dockerfile"


def test_entrypoint_wrapper_exists_and_is_executable() -> None:
    assert ENTRYPOINT.is_file(), f"missing agent wrapper: {ENTRYPOINT}"
    assert os.access(ENTRYPOINT, os.X_OK), f"wrapper not executable: {ENTRYPOINT}"


def test_wrapper_sources_bootstrap_rather_than_running_it() -> None:
    """Sourcing is load-bearing: environment flows down, never up.

    bootstrap.sh ``export``s CLAUDE_CODE_OAUTH_TOKEN. Run as a CHILD process those
    exports die with it and the agent authenticates with nothing — the identical
    end state to the original bug, with healthy-looking logs. Only ``. bootstrap``
    puts them in the shell that then ``exec``s the agent.
    """
    body = ENTRYPOINT.read_text()
    assert re.search(r"^\s*\.\s+\"\$BOOTSTRAP\"", body, re.M), (
        "wrapper must SOURCE bootstrap (`. \"$BOOTSTRAP\"`); running it as a "
        "subprocess silently drops every export, including the auth token"
    )
    assert re.search(r"^\s*exec\s+\"\$REAL_CLAUDE\"", body, re.M), (
        "wrapper must exec the real CLI so the agent keeps PID/signal semantics"
    )


def _run_wrapper(
    tmp_path: Path, bootstrap_body: str, **env: str
) -> subprocess.CompletedProcess[str]:
    """Execute the REAL wrapper with a stub bootstrap and a stub CLI.

    Both seams are already env-injectable (OAW_BOOTSTRAP / OAW_REAL_CLAUDE), so
    the wrapper can be exercised for real without docker.
    """
    bs = tmp_path / "bs.sh"
    bs.write_text(bootstrap_body)
    cli = tmp_path / "claude-real"
    cli.write_text('#!/bin/sh\necho "cli:${OAW_PROOF:-unset}:$*"\n')
    cli.chmod(0o755)
    return subprocess.run(
        ["bash", str(ENTRYPOINT), "--flag"],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            **os.environ,
            "OAW_BOOTSTRAP": str(bs),
            "OAW_REAL_CLAUDE": str(cli),
            **env,
        },
    )


def test_wrapper_export_actually_reaches_the_exec_d_agent(tmp_path: Path) -> None:
    """BEHAVIOURAL twin of the structural test above.

    The regex test proves the wrapper is *written* to source bootstrap; it never
    executes anything, which is the same "declared, never exercised" shape as the
    defect this whole change fixes. This one runs the real wrapper and proves an
    ``export`` performed inside bootstrap survives into the exec'd process — the
    single property the auth fix depends on.
    """
    proc = _run_wrapper(tmp_path, "export OAW_PROOF=alive\n")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "cli:alive:--flag", (
        "an export from bootstrap must survive into the exec'd agent, and argv "
        f"must pass through; got {proc.stdout!r}"
    )


def test_wrapper_skip_bootstrap_starts_the_agent_unbootstrapped(
    tmp_path: Path,
) -> None:
    """Negative twin: the repair escape hatch runs the CLI with no bootstrap."""
    proc = _run_wrapper(tmp_path, "export OAW_PROOF=alive\n", OAW_SKIP_BOOTSTRAP="1")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "cli:unset:--flag", (
        "OAW_SKIP_BOOTSTRAP must skip bootstrap entirely (no export performed)"
    )
    assert "UNBOOTSTRAPPED" in proc.stderr, "skipping must be loudly announced"


def test_wrapper_fails_closed_when_bootstrap_is_fatal(tmp_path: Path) -> None:
    """A fatal bootstrap must abort BEFORE the agent starts.

    'Refusing to hand off to the agent' is only true if the exec never happens —
    otherwise a boot with a missing secret silently becomes a running agent.
    """
    proc = _run_wrapper(tmp_path, "echo 'boom' >&2\nexit 1\n")
    assert proc.returncode != 0, "a fatal bootstrap must not reach the agent"
    assert "cli:" not in proc.stdout, (
        f"the agent must NEVER be exec'd after a fatal bootstrap; got {proc.stdout!r}"
    )


def test_wrapper_refuses_when_bootstrap_is_missing(tmp_path: Path) -> None:
    """An absent bootstrap must refuse, not 'helpfully' start an unbootstrapped agent."""
    cli = tmp_path / "claude-real"
    cli.write_text('#!/bin/sh\necho "cli:started"\n')
    cli.chmod(0o755)
    proc = subprocess.run(
        ["bash", str(ENTRYPOINT)],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            **os.environ,
            "OAW_BOOTSTRAP": str(tmp_path / "does-not-exist.sh"),
            "OAW_REAL_CLAUDE": str(cli),
        },
    )
    assert proc.returncode != 0
    assert "cli:started" not in proc.stdout
    assert "FATAL" in proc.stderr


def test_dockerfile_installs_wrapper_over_the_resolved_claude_path() -> None:
    """One canonical real binary, with the wrapper installed over the name.

    NOTE: an earlier version of this test asserted that /usr/local/bin/claude was
    "the resolved launch path", on the strength of /proc/<pid>/exe. That was
    wrong — /proc told us what a RUNNING process was, not what `docker exec
    claude` resolves, and those differ. See test_dockerfile_wraps_every_
    reachable_claude_and_asserts_it for the property that actually matters.
    """
    body = DOCKERFILE.read_text()
    assert "mv /usr/local/bin/claude /usr/local/bin/claude-real" in body, (
        "the real CLI must move aside so the wrapper can take its name"
    )
    assert "claude-entrypoint.sh" in body
    assert re.search(r'install -m 0755 "\$wrapper" /usr/local/bin/claude', body), (
        "wrapper must be installed as /usr/local/bin/claude"
    )


def test_secrets_env_example_is_actually_sourceable(tmp_path: Path) -> None:
    """The shipped template must survive `source` — it is sourced verbatim at boot.

    This is the test that would have caught the real defect. Every fixture above
    uses a SINGLE-token value (``FOO_TOKEN``, ``discord-bot-token``), so none of
    them could ever expose the bug: unquoted, ``OAW_REQUIRED_SECRETS=a b`` is not
    a two-item list, it is ``VAR=a`` prefixed to a command named ``b``. The real
    template carried a space, no test sourced it, and the boot died with
    ``line 42: discord-bot-token: command not found`` (exit 127).
    """
    example = REPO_ROOT / "containers" / "oakandwave-workflow" / "secrets-env.example"
    proc = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", f'set -a; . "{example}"; set +a'],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"secrets-env.example is not sourceable: {proc.stderr.strip()}\n"
        "A value containing a space must be QUOTED."
    )


def test_multi_value_required_secrets_survives_sourcing(tmp_path: Path) -> None:
    """A space-separated list in .env must parse as a LIST, not run a command."""
    home = _make_home(
        tmp_path,
        secrets={
            ".env": 'OAW_REQUIRED_SECRETS="alpha-token beta-token"\n',
            "alpha-token": "a\n",
            "beta-token": "b\n",
        },
    )
    proc = _run(home)
    assert "command not found" not in proc.stderr, (
        "unquoted-list regression: .env sourcing executed a value as a command"
    )
    assert proc.returncode == 0, proc.stderr


def test_unsourceable_env_fails_loud_and_names_itself(tmp_path: Path) -> None:
    """A broken .env must produce a named FATAL, not a bare 127.

    Under the wrapper, bootstrap failing means the agent never starts. The operator
    has to be told which file broke and why, or they get a container that simply
    has no agent in it.
    """
    home = _make_home(tmp_path, secrets={".env": "OAW_REQUIRED_SECRETS=alpha beta\n"})
    proc = _run(home)
    assert proc.returncode != 0, "an unsourceable .env must fail the boot"
    assert "FATAL" in proc.stderr
    assert ".env" in proc.stderr
    assert "UNQUOTED" in proc.stderr or "unquoted" in proc.stderr, (
        "the diagnosis must name the likely cause; a bare 127 is not actionable"
    )


def test_unsourceable_env_is_caught_when_the_bad_line_is_not_last(
    tmp_path: Path,
) -> None:
    """The bad line followed by a GOOD one — the shipped template's own shape.

    This is the case a single-line fixture cannot reach, and the first cut of the
    guard failed it. bash STRIPS `errexit` inside ``$( )``, so a command-
    substitution probe kept sourcing past the failure and returned the status of
    the LAST line. secrets-env.example ends with a good ``OAW_SECRET_ENV=`` line,
    so a broken ``OAW_REQUIRED_SECRETS`` above it probed "clean" — the guard was
    inert for the exact file it ships, and the real source then died with 127.

    Measured before the fix:
        probe: reported CLEAN
        captured-but-discarded: .env: line 2: beta: command not found
        real-source exit: 127
    """
    home = _make_home(
        tmp_path,
        secrets={
            ".env": (
                "DISCORD_TOKEN_PATH=/x\n"
                "OAW_REQUIRED_SECRETS=alpha beta\n"  # breaks here…
                'OAW_SECRET_ENV="A=b"\n'  # …but this succeeds LAST
            )
        },
    )
    proc = _run(home)
    assert proc.returncode != 0, (
        "a failure on a non-final line must still fail the boot — a probe that "
        "reports the LAST line's status is inert for every realistic .env"
    )
    assert "FATAL" in proc.stderr
    assert "beta" in proc.stderr, "the captured stderr must be surfaced, not discarded"


def test_bootstrap_writes_nothing_to_stdout(tmp_path: Path) -> None:
    """fd 1 belongs to the AGENT.

    The wrapper sources bootstrap and then execs the CLI in the same process, so
    every byte bootstrap puts on stdout is prepended to the agent's own output.
    One line was on stdout and it corrupted headless runs:

        $ claude -p 'reply with exactly: AUTH_OK'
        bootstrap: 1 warning(s) (0 collision(s), 0 dangling), 0 fatal(s)
        AUTH_OK

    which breaks `--output-format json` / `stream-json` and anything piped to jq.
    """
    home = _make_home(
        tmp_path,
        image_skills=["alpha"],
        secrets={".env": 'OAW_REQUIRED_SECRETS=""\n'},
    )
    proc = _run(home)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "", (
        f"bootstrap must emit nothing on stdout; got {proc.stdout!r}"
    )


def test_dockerfile_hands_the_uid_back_to_ubuntu() -> None:
    """The wrapper install needs root; the IMAGE must still default to ubuntu.

    /usr/local/bin is root-owned, so the install step switches to `USER root`.
    That step sits after what used to be the final `USER ubuntu`, so dropping the
    trailing hand-back would leave the image running as root — silently breaking
    the host-owned bind-mount contract (R-04/TC-2) that test_ownership.py checks
    from the AoE side. Nothing else asserts the LAST directive.
    """
    users = re.findall(r"^USER\s+(\S+)", DOCKERFILE.read_text(), re.M)
    assert users, "Dockerfile declares no USER"
    assert users[-1] == "ubuntu", (
        f"image must default to ubuntu, but the last USER is {users[-1]!r}; "
        "the root step for the wrapper install must hand the uid back"
    )


# --- zombie reaping: tini as PID 1 (#1179) ------------------------------------

def test_dockerfile_installs_tini() -> None:
    """tini must actually be installed, not just referenced in a comment."""
    text = DOCKERFILE.read_text()
    assert re.search(r"apt-get install.*\btini\b", text), (
        "Dockerfile no longer installs tini — the zombie-reaping fix (#1179) "
        "depends on the binary actually being present"
    )
    assert "tini --version" in text, (
        "the tini install has no verification probe — every other tool "
        "install in this file proves the binary runs (mise --version, "
        "podman --version, ...); tini should not be the exception"
    )


def test_dockerfile_uses_entrypoint_not_cmd_for_tini() -> None:
    """#1179 code review: CMD alone does not deliver the reaping guarantee.

    CMD survives docker run FLAGS but is discarded outright by a trailing
    COMMAND ARGUMENT — `docker run <image> sleep infinity` (the single most
    common keep-alive idiom for a tool like aoe) would silently drop a
    CMD-only tini and PID 1 goes back to plain `sleep infinity`, no error,
    zombies resume. ENTRYPOINT is invoked with whatever command ends up in
    play, so the reap holds regardless of what aoe passes. This is the
    difference between the fix actually working and it being silently inert
    in exactly the scenario it exists to prevent — assert the mechanism, not
    just tini's presence somewhere in the file.
    """
    text = DOCKERFILE.read_text()
    entrypoints = re.findall(r"^ENTRYPOINT\s+(.+)$", text, re.M)
    assert entrypoints, "Dockerfile declares no ENTRYPOINT — tini must be the ENTRYPOINT, not the CMD"
    assert "tini" in entrypoints[-1], (
        f"the last ENTRYPOINT is {entrypoints[-1]!r}, which doesn't run tini — "
        "a trailing docker run command argument would silently discard a "
        "CMD-only tini and reintroduce the zombie-reap gap"
    )
    # The absolute path, matching this file's own habit for /usr/bin/podman and
    # /usr/local/bin/claude — a later PATH entry (the mise toolbox shims)
    # precedes system PATH, so a bare `tini` could resolve to a shadowing shim.
    assert "/usr/bin/tini" in entrypoints[-1], (
        f"ENTRYPOINT {entrypoints[-1]!r} should resolve tini by absolute path, "
        "not rely on PATH order"
    )


def test_dockerfile_keeps_a_keep_alive_cmd() -> None:
    """#1179 code review: the ENTRYPOINT/CMD pair only keeps the container
    alive if a CMD survives to be tini's argument. `ENTRYPOINT ["tini", "--"]`
    with no CMD makes tini exit immediately (nothing to exec), and the
    container exits right after start — silently, since the image tests that
    would catch it (test_image.py) skip when Docker/the built image is
    absent, which is the stock lane. This pins the shape without needing
    Docker: the LAST CMD must be present and non-empty.
    """
    text = DOCKERFILE.read_text()
    cmds = re.findall(r"^CMD\s+(.+)$", text, re.M)
    assert cmds, "Dockerfile declares no CMD — tini has nothing to exec and the container exits immediately"
    assert cmds[-1].strip() not in ("[]", ""), (
        f"the last CMD is {cmds[-1]!r}, which is empty — tini needs a real "
        "keep-alive command as its argument"
    )


# --- no-bypass guard (#1076) --------------------------------------------------

BYPASS_GUARD = REPO_ROOT / "scripts" / "ci" / "assert-no-claude-bypass.sh"


def _bypass(tmp_path: Path, entries: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Build a fake PATH of dirs, each optionally holding a `claude`."""
    dirs = []
    for name, content in entries.items():
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        if content is not None:
            f = d / "claude"
            f.write_text(content)
            f.chmod(0o755)
        dirs.append(str(d))
    return subprocess.run(
        ["bash", str(BYPASS_GUARD), ":".join(dirs)],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_wrapper_carries_the_marker_the_guard_greps_for() -> None:
    """The guard identifies the wrapper by marker; losing it breaks the build."""
    assert "OAW-CLAUDE-BOOTSTRAP-WRAPPER" in ENTRYPOINT.read_text()


def test_bypass_guard_is_executable() -> None:
    """The Dockerfile invokes it directly; the tests run it via `bash <path>`.

    Without this, losing the exec bit leaves every test green and breaks only the
    image build — a gap of exactly the kind this changeset exists to close.
    """
    assert BYPASS_GUARD.is_file(), f"missing guard: {BYPASS_GUARD}"
    assert os.access(BYPASS_GUARD, os.X_OK), f"guard is not executable: {BYPASS_GUARD}"


def test_bypass_guard_covers_an_empty_path_entry(tmp_path: Path) -> None:
    """An empty PATH entry means the CURRENT DIRECTORY under POSIX.

    Discarding empties would silently exclude a real bypass slot from a check
    whose entire claim is 'every reachable claude'.
    """
    (tmp_path / "cwd-claude").mkdir()
    f = tmp_path / "cwd-claude" / "claude"
    f.write_text("#!/bin/sh\necho 'not the wrapper'\n")
    f.chmod(0o755)
    proc = subprocess.run(
        ["bash", str(BYPASS_GUARD), ":"],  # two empty entries -> '.' twice
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(tmp_path / "cwd-claude"),
    )
    assert proc.returncode != 0, "an unwrapped claude in '.' must be caught"
    assert "BYPASS" in proc.stderr


def test_bypass_guard_passes_when_every_claude_is_the_wrapper(tmp_path: Path) -> None:
    body = "#!/usr/bin/env bash\n# OAW-CLAUDE-BOOTSTRAP-WRAPPER\n"
    proc = _bypass(tmp_path, {"a": body, "b": body})
    assert proc.returncode == 0, proc.stderr
    assert "all wrapped" in proc.stdout


def test_bypass_guard_fails_on_an_unwrapped_claude(tmp_path: Path) -> None:
    """The real defect: a `claude` earlier on PATH that is not the wrapper.

    This is what /root/.local/bin/claude was — reached by `docker exec` before
    /usr/local/bin, so the agent booted unbootstrapped and said nothing.
    """
    proc = _bypass(
        tmp_path,
        {
            "early": "#!/bin/sh\necho 'the real CLI'\n",
            "late": "#!/usr/bin/env bash\n# OAW-CLAUDE-BOOTSTRAP-WRAPPER\n",
        },
    )
    assert proc.returncode != 0, "an unwrapped claude on PATH must fail the build"
    assert "BYPASS" in proc.stderr
    assert "UNBOOTSTRAPPED" in proc.stderr


def test_bypass_guard_rejects_an_empty_denominator(tmp_path: Path) -> None:
    """Zero `claude` found is NOT a pass — it means nothing was verified.

    Same empty-denominator failure as the inert R-14 check (#1061) and trivy
    parsing zero manifests (#1056): a pass over nothing reads identically to a
    pass over everything.
    """
    (tmp_path / "empty").mkdir()
    proc = subprocess.run(
        ["bash", str(BYPASS_GUARD), str(tmp_path / "empty")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0, "no claude on PATH must fail, not silently pass"
    assert "nothing was verified" in proc.stderr


def test_dockerfile_wraps_every_reachable_claude_and_asserts_it() -> None:
    """Assert on the INSTRUCTIONS, never on the prose.

    Every string checked here also appears in the surrounding comments, which
    explain the defect at length. Matching the raw file would let this test pass
    on the explanation alone: delete the RUN lines, keep the comment, still
    green. Comments are stripped first so the test can only be satisfied by
    something the build actually executes.
    """
    code = "\n".join(
        line
        for line in DOCKERFILE.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    assert "/home/ubuntu/.local/bin/claude" in code, "first PATH entry must be wrapped"
    assert "ln -sfn /usr/local/bin/claude /root/.local/bin/claude" in code, (
        "the base image's /root/.local/bin/claude is reached by `docker exec` "
        "before /usr/local/bin and must point at the wrapper"
    )
    assert re.search(r"assert-no-claude-bypass\.sh\"?\s*$", code, re.M), (
        "the build must INVOKE the no-bypass guard, not merely mention it — "
        "assuming a PATH order is what shipped the wrapper inert the first time"
    )


# --- onboarding state (#1079) -------------------------------------------------
#
# The keys below were derived EMPIRICALLY against the real image, not guessed —
# each candidate config was run repeatedly because single runs proved
# non-deterministic. Two results contradict the obvious guess and are the reason
# these tests assert what they do:
#
#   hasCompletedOnboarding + trust(cwd)      -> reaches the prompt   (3/3)
#   hasCompletedOnboarding alone             -> trust dialog         (2/2)
#   theme + trust, no hasCompletedOnboarding -> theme picker
#
# So `theme` is NOT part of the contract, and neither is `lastOnboardingVersion`.
# Asserting either would pin the image to a value the CLI does not require and
# would drift on every base-image bump.


def _read_cfg(home: Path) -> dict:
    import json

    return json.loads((home / ".claude.json").read_text())


def _home_with_cfg(tmp_path: Path, cfg: str = "{}") -> Path:
    home = _make_home(tmp_path, secrets={".env": 'OAW_REQUIRED_SECRETS=""\n'})
    (home / ".claude.json").write_text(cfg)
    return home


def test_onboarding_state_is_set_so_the_wizard_never_runs(tmp_path: Path) -> None:
    """An agent parked on the first-run wizard is an agent that never starts."""
    home = _home_with_cfg(tmp_path)
    proc = _run(home)
    assert proc.returncode == 0, proc.stderr
    assert _read_cfg(home)["hasCompletedOnboarding"] is True


def test_trust_is_recorded_for_the_ACTUAL_working_directory(tmp_path: Path) -> None:
    """Trust is per-project and path-sensitive — it cannot be baked.

    Measured: trust recorded for /home/ubuntu while the agent runs in /workspace
    still shows the dialog. The sandbox path varies per session, so the key must
    be the agent's real cwd. bootstrap is SOURCED by the wrapper in the agent's
    own process, which is exactly why $PWD is the right key.
    """
    home = _home_with_cfg(tmp_path)
    workspace = tmp_path / "workspace-xyz"
    workspace.mkdir()
    proc = subprocess.run(
        ["bash", str(BOOTSTRAP)],
        capture_output=True,
        text=True,
        env=_sealed_env(home),
        cwd=str(workspace),
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    projects = _read_cfg(home).get("projects", {})
    assert str(workspace) in projects, (
        f"trust must be keyed on the agent's cwd; got {list(projects)}"
    )
    assert projects[str(workspace)]["hasTrustDialogAccepted"] is True


def test_onboarding_state_is_idempotent(tmp_path: Path) -> None:
    """bootstrap runs on EVERY claude invocation — it must not churn the config."""
    home = _home_with_cfg(tmp_path)
    assert _run(home).returncode == 0
    first = (home / ".claude.json").read_text()
    proc = _run(home)
    assert proc.returncode == 0
    assert (home / ".claude.json").read_text() == first, "second run rewrote the config"
    assert "already present" in proc.stderr


def test_auto_trust_is_opt_out_but_onboarding_still_clears(tmp_path: Path) -> None:
    """Auto-trust declares a workspace trusted without asking; keep it reversible.

    Opting out must NOT also re-arm the theme/login wizard — those are a separate
    key, and conflating them would make the escape hatch unusable.
    """
    home = _home_with_cfg(tmp_path)
    proc = _run(home, OAW_NO_AUTO_TRUST="1")
    assert proc.returncode == 0, proc.stderr
    cfg = _read_cfg(home)
    assert cfg["hasCompletedOnboarding"] is True
    assert cfg.get("projects", {}) == {}, "opt-out must record no trust"
    assert "auto-trust disabled" in proc.stderr


def test_existing_config_keys_survive(tmp_path: Path) -> None:
    """~/.claude.json carries the baked MCP registrations — never clobber them."""
    home = _home_with_cfg(tmp_path, '{"mcpServers": {"disc-server": {"x": 1}}}')
    assert _run(home).returncode == 0
    cfg = _read_cfg(home)
    assert cfg["mcpServers"] == {"disc-server": {"x": 1}}, "MCP registrations lost"
    assert cfg["hasCompletedOnboarding"] is True


def test_unreadable_config_warns_and_does_not_abort_the_boot(tmp_path: Path) -> None:
    """A corrupt config must not become 'no agent at all'.

    The wrapper sources bootstrap, so aborting here means the container comes up
    with nothing running. A wizard is bad; no agent is worse.
    """
    original = "{ not json ]"
    home = _home_with_cfg(tmp_path, original)
    proc = _run(home)
    assert proc.returncode == 0, "a corrupt config must not fail the boot"

    # BOTH halves must discriminate. The first cut asserted
    #   "onboarding" in stderr and "WARN" in stderr
    # which is true whenever bootstrap merely MENTIONS onboarding: "WARN" appears
    # in every test in this file (_make_home defaults settings_local=None, so
    # merge_settings always warns about the missing mount), and "onboarding" is
    # satisfied by the SUCCESS path's info line. Verified: mutate the heredoc to
    # swallow the parse error and clobber the config with {} — destroying the
    # baked mcpServers registrations — and the old assertions still passed.
    assert "WARN: onboarding" in proc.stderr, (
        "the warning must be the onboarding one, not any warning at all"
    )
    assert (home / ".claude.json").read_text() == original, (
        "a config bootstrap cannot PARSE must be left byte-identical, never "
        "rewritten — this file carries the baked mcpServers registrations"
    )


def test_absent_config_warns_and_does_not_abort_the_boot(tmp_path: Path) -> None:
    """No ~/.claude.json at all: warn, keep going.

    Warn-only by design — the risk this covers is a future change turning it into
    a `fatal`, which under the sourcing wrapper means no agent at all.
    """
    home = _make_home(tmp_path, secrets={".env": 'OAW_REQUIRED_SECRETS=""\n'})
    cfg = home / ".claude.json"
    if cfg.exists():
        cfg.unlink()
    proc = _run(home)
    assert proc.returncode == 0, "an absent config must not fail the boot"
    assert "WARN: onboarding" in proc.stderr
    assert not cfg.exists(), "bootstrap must not conjure a config it did not find"


# --- GitHub credential (#1082) ------------------------------------------------
#
# FILE modality, deliberately not env. The host authenticates gh via GH_TOKEN and
# copying that would be one line — but an env var is inherited by every child
# process, and the only working GitHub credential here carries admin:enterprise,
# admin:org and delete_repo. The CLAUDE_CODE_OAUTH_TOKEN exception was argued
# narrowly (that token IS the agent's identity); an org-admin PAT does not qualify.


def _home_with_pat(tmp_path: Path, token: str = "ghp_TESTTOKEN") -> Path:
    return _make_home(
        tmp_path,
        secrets={".env": 'OAW_REQUIRED_SECRETS=""\n', "github-pat": f"{token}\n"},
    )


def test_bootstrap_never_writes_the_operator_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE GUARD (#1130). The suite must not write outside its tempdir.

    ``operator_home`` stands in for the real ``~``: it is what ``$HOME`` points at
    when the suite starts. ``_sealed_env`` must override that with the per-test
    tempdir, so a bootstrap run leaves it untouched.

    Why this exists rather than a comment. For three weeks the suite sealed
    ``OAW_HOME`` and not ``HOME``; ``ensure_github_auth`` ran ``git config
    --global``; git read ``$HOME``; and every single run rewrote the operator's
    real ``~/.gitconfig`` — silently reinstating a URL rewrite he had deliberately
    removed after a token leak. Nothing failed, because nothing was looking.

    ASSERT EMPTINESS, not the absence of one filename. Checking only for
    ``.gitconfig`` would pass the day some new bootstrap step writes ``.netrc``,
    and the next leak would be as invisible as this one was.

    MUTATION-TESTED: delete ``env["HOME"] = str(home)`` from ``_sealed_env`` and
    this test must go red. A guard only ever run against the fixed tree is not a
    guard — it is an assertion that happens to be true.
    """
    operator_home = tmp_path / "operator-home"
    operator_home.mkdir()
    monkeypatch.setenv("HOME", str(operator_home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    # A PAT present is what drives ensure_github_auth down the git-config path —
    # the exact route that leaked. A run without one would pass vacuously.
    home = _home_with_pat(tmp_path)
    proc = _run(home)
    assert proc.returncode == 0, proc.stderr

    # POSITIVE half first: prove the git-config path actually executed. Without
    # this the guard passes vacuously the day ensure_github_auth returns early
    # (empty token, shape-guard rejection, `command -v git` false, or the
    # "hosts.yml already carries a token" branch) — an empty denominator wearing
    # a pass's clothes, which is the exact shape this file polices elsewhere.
    # It also pins WHERE the write landed, not only where it did not.
    assert (home / ".gitconfig").is_file(), (
        "bootstrap never reached `git config --global` — this guard proved nothing. "
        "Check that the PAT fixture still drives ensure_github_auth down that path."
    )

    leaked = sorted(child.name for child in operator_home.iterdir())
    assert leaked == [], (
        "bootstrap wrote into the operator's home directory: "
        f"{leaked}. Everything the bootstrap and the tools it invokes touch must "
        "resolve inside the per-test tempdir — see _sealed_env."
    )


def test_github_credential_is_written_as_a_file(tmp_path: Path) -> None:
    home = _home_with_pat(tmp_path)
    proc = _run(home)
    assert proc.returncode == 0, proc.stderr
    hosts = home / ".config" / "gh" / "hosts.yml"
    assert hosts.is_file(), "gh credential file not written — gh stays unauthenticated"
    body = hosts.read_text()
    assert "oauth_token: 'ghp_TESTTOKEN'" in body, (
        "token must be QUOTED so a mis-shaped secret file fails loud rather than "
        "producing valid YAML with a garbage token"
    )
    assert "github.com:" in body


def test_github_credential_is_not_world_readable(tmp_path: Path) -> None:
    """A token file at 0644 is a credential leak to every user on the host."""
    home = _home_with_pat(tmp_path)
    assert _run(home).returncode == 0
    mode = (home / ".config" / "gh" / "hosts.yml").stat().st_mode & 0o777
    assert mode == 0o600, f"hosts.yml must be 0600, got {oct(mode)}"


def test_github_token_is_never_exported_to_the_environment(tmp_path: Path) -> None:
    """The whole point of the file modality.

    bootstrap sources .env with `set -a`, so anything it defines is exported and
    inherited by every child. The PAT must reach gh's config file and nowhere
    else — assert no env var carries the token value.
    """
    home = _home_with_pat(tmp_path, token="ghp_LEAKCANARY")
    proc = subprocess.run(
        ["bash", "-c", f'. "{BOOTSTRAP}" >/dev/null 2>&1; env'],
        capture_output=True,
        text=True,
        env=_sealed_env(home),
        cwd=str(tmp_path),
        timeout=60,
    )
    assert "ghp_LEAKCANARY" not in proc.stdout, (
        "the GitHub PAT leaked into the environment — every child process now "
        "inherits an org-admin credential"
    )


def test_absent_github_pat_warns_but_boots(tmp_path: Path) -> None:
    """No GitHub access is degraded, not fatal — the wrapper sources this."""
    home = _make_home(tmp_path, secrets={".env": 'OAW_REQUIRED_SECRETS=""\n'})
    proc = _run(home)
    assert proc.returncode == 0, "a missing PAT must not abort the boot"
    assert "WARN: github" in proc.stderr
    assert not (home / ".config" / "gh" / "hosts.yml").exists()


def test_existing_github_credential_is_not_clobbered(tmp_path: Path) -> None:
    """An operator-placed credential wins over the mounted secret."""
    home = _home_with_pat(tmp_path)
    hosts = home / ".config" / "gh" / "hosts.yml"
    hosts.parent.mkdir(parents=True, exist_ok=True)
    original = "github.com:\n    oauth_token: ghp_OPERATOR_PUT_THIS_HERE\n"
    hosts.write_text(original)
    proc = _run(home)
    assert proc.returncode == 0, proc.stderr
    assert hosts.read_text() == original, "clobbered an operator-placed credential"


def test_empty_github_pat_warns_and_writes_nothing(tmp_path: Path) -> None:
    """An empty secret file must not produce a credential file with no token."""
    home = _make_home(
        tmp_path, secrets={".env": 'OAW_REQUIRED_SECRETS=""\n', "github-pat": "\n"}
    )
    proc = _run(home)
    assert proc.returncode == 0
    assert "WARN: github" in proc.stderr
    assert not (home / ".config" / "gh" / "hosts.yml").exists()


def test_hyphenated_required_secret_does_not_kill_the_shell(tmp_path: Path) -> None:
    """`${!name}` on a hyphenated name is a bash ERROR, not an empty lookup.

    Secret names are FILENAMES. Bash rejects indirect expansion on a name that is
    not a legal identifier — `github-pat: invalid variable name` — and under
    `set -e` that kills the shell AT THAT LINE: before the fatal, before the
    accumulate-all-fatals list, before the summary. Under the sourcing wrapper it
    means no agent at all, explained only by a bare bash error.

    Latent since #1061 because every declared secret happened to exist; declaring
    a NEW one on a host that lacks the file walks straight into it. The existing
    R-14 tests could not see it — they assert only `returncode != 0` plus the
    secret name in stderr, and bash's own error satisfies both.
    """
    home = _make_home(tmp_path, secrets={".env": 'OAW_REQUIRED_SECRETS="some-hyphenated-token"\n'})
    proc = _run(home)
    assert "invalid variable name" not in proc.stderr, (
        "bash indirect-expansion error leaked — the boot died before reporting why"
    )
    assert "required secret missing: 'some-hyphenated-token'" in proc.stderr, (
        "the real R-14 diagnosis must be reached and printed"
    )
    assert "bootstrap:" in proc.stderr, "the summary line must still be emitted"


def test_github_pat_cannot_be_projected_into_the_environment(tmp_path: Path) -> None:
    """The 'never project this' rule must be ENFORCED, not merely documented.

    Servers enforce; docs suggest. Without this the rule is three comment blocks
    that one OAW_SECRET_ENV line silently overrides, handing an org-admin PAT to
    every child process.
    """
    home = _make_home(
        tmp_path,
        secrets={
            ".env": 'OAW_REQUIRED_SECRETS=""\nOAW_SECRET_ENV="GH_TOKEN=github-pat"\n',
            "github-pat": "ghp_MUSTNOTLEAK\n",
        },
    )
    proc = subprocess.run(
        ["bash", "-c", f'. "{BOOTSTRAP}" >/dev/null 2>&1; env'],
        capture_output=True, text=True,
        env=_sealed_env(home), cwd=str(tmp_path), timeout=60,
    )
    assert "ghp_MUSTNOTLEAK" not in proc.stdout, "deny-list bypassed — PAT reached the env"

    warn_run = _run(home)
    assert "refusing to project" in warn_run.stderr, "the refusal must be loud, not silent"


def test_malformed_pat_file_is_refused(tmp_path: Path) -> None:
    """`GH_TOKEN=ghp_x` in the secret file is a common shape.

    Interpolated, it yields VALID YAML carrying a garbage token, so the failure
    surfaces later as a puzzling 401 instead of here where the cause is obvious.
    """
    home = _make_home(
        tmp_path,
        secrets={".env": 'OAW_REQUIRED_SECRETS=""\n', "github-pat": "export GH_TOKEN=ghp_x\n"},
    )
    proc = _run(home)
    assert proc.returncode == 0
    assert "does not look like a bare PAT" in proc.stderr
    assert not (home / ".config" / "gh" / "hosts.yml").exists()


def _home_with_cfgdir(tmp_path: Path, cli_cfg: str = "{}") -> tuple[Path, Path]:
    home = _make_home(tmp_path, secrets={".env": 'OAW_REQUIRED_SECRETS=""\n'})
    (home / ".claude.json").write_text(
        '{"mcpServers": {"disc-server": {"a": 1}, "sdlc-server": {"b": 2}}}'
    )
    cfgdir = tmp_path / "cfgdir"
    cfgdir.mkdir()
    (cfgdir / ".claude.json").write_text(cli_cfg)
    return home, cfgdir


def _run_cfgdir(home: Path, cfgdir: Path, cwd: Path, **env: str):
    return subprocess.run(
        ["bash", str(BOOTSTRAP)],
        capture_output=True, text=True, timeout=60, cwd=str(cwd),
        env=_sealed_env(home, CLAUDE_CONFIG_DIR=str(cfgdir), **env),
    )


def test_onboarding_state_goes_to_the_cli_config_not_home(tmp_path: Path) -> None:
    """Written where the CLI READS, not where $HOME says."""
    home, cfgdir = _home_with_cfgdir(tmp_path)
    ws = tmp_path / "ws"; ws.mkdir()
    proc = _run_cfgdir(home, cfgdir, ws)
    assert proc.returncode == 0, proc.stderr
    import json as J
    cli = J.loads((cfgdir / ".claude.json").read_text())
    assert cli["hasCompletedOnboarding"] is True
    assert str(ws) in cli.get("projects", {}), "trust must land in the CLI-read config"
    home_cfg = J.loads((home / ".claude.json").read_text())
    assert "hasCompletedOnboarding" not in home_cfg, (
        "writing to $HOME when CLAUDE_CONFIG_DIR is set is the bug"
    )


def test_kit_mcp_registrations_merge_into_the_cli_config(tmp_path: Path) -> None:
    """`./install` registers at BUILD time into $HOME; the CLI reads elsewhere.

    Production had `mcpServers: []` and no kit MCP available while the image's
    own copy sat fully populated and unread.
    """
    home, cfgdir = _home_with_cfgdir(tmp_path, '{"mcpServers": {"operator-own": {"z": 9}}}')
    ws = tmp_path / "ws"; ws.mkdir()
    assert _run_cfgdir(home, cfgdir, ws).returncode == 0
    import json as J
    got = J.loads((cfgdir / ".claude.json").read_text())["mcpServers"]
    assert "disc-server" in got and "sdlc-server" in got, "kit servers not registered"
    assert got["operator-own"] == {"z": 9}, (
        "the CLI config is SHARED across containers and carries the operator's own "
        "servers — the merge must be additive, never a clobber"
    )


def test_stored_credential_is_reported_so_401_has_a_filename(tmp_path: Path) -> None:
    """A stale stored credential outranks the mounted token and lies about it.

    Observed: `401 OAuth access token has been revoked` while the mounted token
    returned HTTP 200. The culprit was a .credentials.json ten days old. The
    operator cannot tell those apart without being told the file exists.
    """
    home, cfgdir = _home_with_cfgdir(tmp_path)
    (cfgdir / ".credentials.json").write_text("{}")
    ws = tmp_path / "ws"; ws.mkdir()
    proc = _run_cfgdir(home, cfgdir, ws)
    assert proc.returncode == 0
    assert "stored credential present" in proc.stderr
    assert "OUTRANKS" in proc.stderr, "the precedence must be stated, not implied"
    assert ".credentials.json" in proc.stderr, "the message must name the file"


def test_unresolvable_hook_path_is_reported_at_boot(tmp_path: Path) -> None:
    """Host absolute paths cannot resolve in a container.

    Production: `/home/bakerb/.local/share/wtf-server/hooks/wtf-post-tool-use.sh:
    not found`. That is a CATEGORY error, not a preference conflict. wtf failed
    loudly only because its target was absent; a hook whose path exists in both
    namespaces would silently run the wrong thing.
    """
    home, cfgdir = _home_with_cfgdir(tmp_path)
    (cfgdir / "settings.json").write_text(
        '{"hooks": {"PostToolUse": [{"hooks": [{"command": "/home/nonexistent/x.sh"}]}]}}'
    )
    ws = tmp_path / "ws"; ws.mkdir()
    proc = _run_cfgdir(home, cfgdir, ws)
    assert proc.returncode == 0, "an unresolvable hook must not abort the boot"
    assert "/home/nonexistent/x.sh" in proc.stderr, "the offending path must be named"
    assert "does not exist in this container" in proc.stderr


def test_resolvable_hook_path_is_not_flagged(tmp_path: Path) -> None:
    """No false alarms — a hook that exists must stay silent."""
    home, cfgdir = _home_with_cfgdir(tmp_path)
    hook = tmp_path / "real-hook.sh"; hook.write_text("#!/bin/sh\n"); hook.chmod(0o755)
    (cfgdir / "settings.json").write_text(
        '{"hooks": {"PostToolUse": [{"hooks": [{"command": "%s"}]}]}}' % hook
    )
    ws = tmp_path / "ws"; ws.mkdir()
    proc = _run_cfgdir(home, cfgdir, ws)
    assert "does not exist in this container" not in proc.stderr


def test_dockerfile_makes_root_traversable_not_listable() -> None:
    """aoe mounts config to /root; the image runs as ubuntu; /root ships 0700.

    711 = traverse, not list. 755 would additionally expose the listing, which is
    not needed and widens it for no benefit.
    """
    body = "\n".join(
        l for l in DOCKERFILE.read_text().splitlines() if not l.lstrip().startswith("#")
    )
    assert "chmod 711 /root" in body, (
        "without this every path under /root is EACCES for the runtime user"
    )
    assert "chmod 755 /root" not in body, "755 exposes the listing unnecessarily"


@pytest.mark.parametrize("prefix", ["$HOME", "${HOME}", "~"])
def test_variable_prefixed_hook_that_EXISTS_is_not_flagged(
    tmp_path: Path, prefix: str
) -> None:
    """Red-first for the 13-phantom regression.

    The first validator matched the slash AFTER `$HOME` and reported
    `/.claude/scripts/hooks/x.sh` — a path never configured — 13 times against a
    healthy container. A plain-absolute-path test cannot see that bug; only a
    variable-prefixed one can.
    """
    home, cfgdir = _home_with_cfgdir(tmp_path)
    (home / ".claude" / "scripts").mkdir(parents=True, exist_ok=True)
    (home / ".claude" / "scripts" / "ok.sh").write_text("#!/bin/sh\n")
    (cfgdir / "settings.json").write_text(
        '{"hooks": {"PostToolUse": [{"hooks": [{"command": "%s/.claude/scripts/ok.sh"}]}]}}'
        % prefix
    )
    ws = tmp_path / "ws"; ws.mkdir()
    proc = _run_cfgdir(home, cfgdir, ws, HOME=str(home))
    assert "does not exist in this container" not in proc.stderr, (
        f"phantom warning for an existing {prefix}-prefixed hook: {proc.stderr}"
    )


def test_variable_prefixed_hook_that_is_MISSING_is_still_flagged(tmp_path: Path) -> None:
    """The over-correction case.

    Fixing the phantoms with a lookbehind made every ~/ and $HOME hook
    unjudgeable — and EVERY hook in config/settings.template.json is ~/-prefixed,
    including one the image build whitelists as deliberately absent. So the
    validator went silent on exactly the failure that motivated it. Expansion,
    not exclusion, is what gets both.
    """
    home, cfgdir = _home_with_cfgdir(tmp_path)
    (cfgdir / "settings.json").write_text(
        '{"hooks": {"PostToolUse": [{"hooks": [{"command": "~/.local/share/gone/hook.sh"}]}]}}'
    )
    ws = tmp_path / "ws"; ws.mkdir()
    proc = _run_cfgdir(home, cfgdir, ws, HOME=str(home))
    assert "does not exist in this container" in proc.stderr, (
        "a ~/-prefixed hook that is genuinely missing must still be reported"
    )
    assert "gone/hook.sh" in proc.stderr


def test_paths_in_comment_fields_are_not_flagged(tmp_path: Path) -> None:
    """Scan `command` values, not the whole JSON blob.

    The settings template carries `_comment` fields; a path mentioned in prose is
    not a configured hook, and warning about it is another way to cry wolf.
    """
    home, cfgdir = _home_with_cfgdir(tmp_path)
    (cfgdir / "settings.json").write_text(
        '{"hooks": {"_comment": "see /nowhere/doc/path.sh", "PostToolUse": []}}'
    )
    ws = tmp_path / "ws"; ws.mkdir()
    proc = _run_cfgdir(home, cfgdir, ws, HOME=str(home))
    assert "/nowhere/doc/path.sh" not in proc.stderr


def test_run_helper_scrubs_ambient_claude_config_dir(tmp_path: Path) -> None:
    """Running this suite INSIDE an aoe container must not touch fleet state.

    Without the scrub, every `_run`-based test resolves the CLI config to the
    real, host-mounted, fleet-SHARED /root/.claude/.claude.json — asserting
    against the wrong file and, worse, mutating it: a trust entry for the pytest
    cwd, plus fixture-shaped mcpServers merged in permanently (the merge is
    add-if-absent, so nothing later corrects them).
    """
    home = _make_home(tmp_path, secrets={".env": 'OAW_REQUIRED_SECRETS=""\n'})
    (home / ".claude.json").write_text("{}")
    decoy = tmp_path / "decoy"; decoy.mkdir()
    (decoy / ".claude.json").write_text('{"canary": true}')
    proc = _run(home, **{})  # ambient value injected below via os.environ
    assert proc.returncode == 0, proc.stderr
    import json as J
    assert J.loads((decoy / ".claude.json").read_text()) == {"canary": True}, (
        "the decoy config was mutated — the ambient CLAUDE_CONFIG_DIR leaked in"
    )
    assert J.loads((home / ".claude.json").read_text()).get("hasCompletedOnboarding") is True


def test_absent_cli_config_is_created_not_bailed_on(tmp_path: Path) -> None:
    """Warning-and-returning here reproduces the exact production state.

    The CLI then creates the file itself, empty: zero MCP servers, wizard, trust
    prompt. A fresh host or new aoe profile hits this, because .claude.json
    conventionally lives at $HOME ROOT, so a config dir seeded from ~/.claude
    will not contain one.
    """
    home = _make_home(tmp_path, secrets={".env": 'OAW_REQUIRED_SECRETS=""\n'})
    (home / ".claude.json").write_text('{"mcpServers": {"disc-server": {"a": 1}}}')
    cfgdir = tmp_path / "empty-cfg"; cfgdir.mkdir()      # no .claude.json inside
    ws = tmp_path / "ws"; ws.mkdir()
    proc = _run_cfgdir(home, cfgdir, ws)
    assert proc.returncode == 0, proc.stderr
    created = cfgdir / ".claude.json"
    assert created.exists(), "bootstrap must create the config, not bail"
    import json as J
    d = J.loads(created.read_text())
    assert "disc-server" in d.get("mcpServers", {}), "kit servers must land in it"
    assert d.get("hasCompletedOnboarding") is True


# --- SSH parity (#1089) -------------------------------------------------------
#
# aoe mounts the operator's ~/.ssh to /root/.ssh — keys plus a host->identity
# config. Agents use these constantly: git over SSH for both forges, and
# troubleshooting remote installs (blueshift-prod, perkollate-*, agent-smith-ca).
#
# They were mounted and INVISIBLE: the agent runs as ubuntu with HOME=/home/ubuntu,
# so ssh looked in /home/ubuntu/.ssh, found nothing, fell back to default identity
# names and failed `Permission denied (publickey)`.
#
# An earlier draft recorded "the container has no ~/.ssh (deliberately)". That was
# WRONG — it inferred design intent from a permissions bug. The keys are provided
# on purpose, and the goal is doing exactly what a host session does.


def _home_with_ssh(tmp_path: Path) -> tuple[Path, Path]:
    home = _make_home(tmp_path, secrets={".env": 'OAW_REQUIRED_SECRETS=""\n'})
    (home / ".claude.json").write_text("{}")
    src = tmp_path / "mounted-ssh"
    src.mkdir()
    (src / "config").write_text("Host gitlab.com\n  IdentityFile ~/.ssh/gitlab.id_ed25519\n")
    (src / "gitlab.id_ed25519").write_text("KEY\n")
    return home, src


def test_mounted_ssh_keys_are_made_visible_to_the_agent(tmp_path: Path) -> None:
    """The keys land in ~/.ssh as links, and ~/.ssh stays a REAL, writable dir.

    Per-file rather than a directory symlink (#1111): the mount is READ-ONLY, so
    a whole-dir link leaves ssh unable to write known_hosts — every new host then
    becomes a prompt or a failure.
    """
    home, src = _home_with_ssh(tmp_path)
    proc = _run(home, OAW_SSH_SOURCE=str(src))
    assert proc.returncode == 0, proc.stderr
    dst = home / ".ssh"
    assert dst.is_dir() and not dst.is_symlink(), (
        "~/.ssh must stay a real dir so known_hosts remains writable"
    )
    assert (dst / "config").is_symlink(), "the host->identity config must be reachable"
    assert (dst / "gitlab.id_ed25519").resolve() == (src / "gitlab.id_ed25519").resolve()
    assert oct(dst.stat().st_mode)[-3:] == "700", "ssh refuses a loose ~/.ssh"


def test_ssh_parity_is_idempotent(tmp_path: Path) -> None:
    """Runs on every agent start, so a satisfied state must relink nothing."""
    home, src = _home_with_ssh(tmp_path)
    assert _run(home, OAW_SSH_SOURCE=str(src)).returncode == 0
    proc = _run(home, OAW_SSH_SOURCE=str(src))
    assert "already carries the mounted keyring" in proc.stderr


def test_known_hosts_is_seeded_as_a_writable_copy(tmp_path: Path) -> None:
    """known_hosts must be BOTH the agent's own AND carry the operator's hosts.

    #1115: the first cut skipped it entirely so it would stay writable, which
    left the agent with an EMPTY known_hosts — and a non-interactive `git` cannot
    answer a host-key prompt. `git ls-remote git@gitlab.com:…` died with "Host
    key verification failed" in a fresh container. Writable but empty is its own
    outage, and every structural assertion passed while it happened.
    """
    home, src = _home_with_ssh(tmp_path)
    (src / "known_hosts").write_text("gitlab.com ssh-ed25519 AAAAOPERATOR\n")
    proc = _run(home, OAW_SSH_SOURCE=str(src))
    assert proc.returncode == 0, proc.stderr

    kh = home / ".ssh" / "known_hosts"
    assert not kh.is_symlink(), "must never link into the read-only mount"
    assert "AAAAOPERATOR" in kh.read_text(), (
        "the operator's host keys must be carried over, or a fresh container "
        "cannot verify any host it has not met"
    )
    kh.write_text(kh.read_text() + "learned.example ssh-ed25519 AAAANEW\n")  # must not raise


def test_an_agents_own_known_hosts_is_not_overwritten(tmp_path: Path) -> None:
    """Copy-if-absent, not copy-always — hosts the agent learned must survive.

    This runs on every agent start, so copying unconditionally would discard
    everything learned since the container came up.
    """
    home, src = _home_with_ssh(tmp_path)
    (src / "known_hosts").write_text("gitlab.com ssh-ed25519 AAAAOPERATOR\n")
    dst = home / ".ssh"
    dst.mkdir()
    (dst / "known_hosts").write_text("learned.example ssh-ed25519 AAAALEARNED\n")
    assert _run(home, OAW_SSH_SOURCE=str(src)).returncode == 0
    assert (dst / "known_hosts").read_text() == "learned.example ssh-ed25519 AAAALEARNED\n"


def test_an_agent_created_ssh_dir_still_gets_the_keys(tmp_path: Path) -> None:
    """THE LIVE FAILURE (#1111), red-first.

    The old guard declined whenever ~/.ssh held anything but known_hosts. So the
    instant an agent wrote a file there — ssh scratch, or a keypair it generated
    because it believed it had no keys — parity was refused forever, with only a
    boot warning nobody reads.

    Observed: an agent reported itself blocked on host access, generated its own
    keypair, and escalated for a privilege it already had, while the operator's
    full keyring sat mounted the whole time. A silent parity gap does not just
    block work — it generates pressure to solve the wrong problem.
    """
    home, src = _home_with_ssh(tmp_path)
    dst = home / ".ssh"
    dst.mkdir()
    (dst / "id_agent_generated").write_text("SELF-MINTED\n")
    (dst / "known_hosts").write_text("somehost\n")

    proc = _run(home, OAW_SSH_SOURCE=str(src))
    assert proc.returncode == 0, proc.stderr
    assert (dst / "gitlab.id_ed25519").is_symlink(), (
        "an agent-created ~/.ssh must NOT block the operator's keys — this is the bug"
    )
    assert (dst / "id_agent_generated").read_text() == "SELF-MINTED\n", (
        "parity adds what is missing and never destroys what is there"
    )


def test_operator_keys_in_a_real_ssh_dir_are_never_destroyed(tmp_path: Path) -> None:
    """Destroying a private key would be unrecoverable. Add, never remove."""
    home, src = _home_with_ssh(tmp_path)
    real = home / ".ssh"
    real.mkdir()
    (real / "id_ed25519").write_text("OPERATOR KEY\n")
    assert _run(home, OAW_SSH_SOURCE=str(src)).returncode == 0
    assert (real / "id_ed25519").read_text() == "OPERATOR KEY\n"
    assert not (real / "id_ed25519").is_symlink(), "an existing file is never replaced"
    assert (real / "config").is_symlink(), "…but missing ones are still supplied"


def test_a_legacy_whole_dir_symlink_is_converted(tmp_path: Path) -> None:
    """Containers provisioned by the pre-#1111 code have ~/.ssh as a dir symlink.

    Correct for keys, but it makes known_hosts unwritable, so it is migrated
    rather than left in place.
    """
    home, src = _home_with_ssh(tmp_path)
    (home / ".ssh").symlink_to(src)
    proc = _run(home, OAW_SSH_SOURCE=str(src))
    assert proc.returncode == 0, proc.stderr
    dst = home / ".ssh"
    assert dst.is_dir() and not dst.is_symlink(), "the legacy dir-symlink must be converted"
    assert (dst / "gitlab.id_ed25519").is_symlink()
    assert "converting the legacy" in proc.stderr


def test_parity_without_a_usable_key_is_loud(tmp_path: Path) -> None:
    """Assert the OUTCOME, not the mechanism.

    Counting symlinks proves the function ran; it does not prove the agent has a
    usable identity. Without this, an agent discovers the gap much later at a git
    push, with no path back to the cause.
    """
    home = _make_home(tmp_path, secrets={".env": 'OAW_REQUIRED_SECRETS=""\n'})
    src = tmp_path / "ssh-src"
    src.mkdir()
    (src / "config").write_text("Host *\n")  # config but NO private key
    proc = _run(home, OAW_SSH_SOURCE=str(src))
    assert proc.returncode == 0
    assert "no private key visible" in proc.stderr


def test_gitlab_api_credential_is_written_as_a_file(tmp_path: Path) -> None:
    home = _make_home(
        tmp_path,
        secrets={
            ".env": 'OAW_REQUIRED_SECRETS=""\n',
            "gitlab-cli-pat": "glpat-AbCd1234.EfGh5678_iJkL-90\n",
        },
    )
    (home / ".claude.json").write_text("{}")
    proc = _run(home)
    assert proc.returncode == 0, proc.stderr
    cfg = home / ".config" / "glab-cli" / "config.yml"
    assert cfg.is_file()
    assert (cfg.stat().st_mode & 0o777) == 0o600
    body = cfg.read_text()
    assert "glpat-AbCd1234.EfGh5678_iJkL-90" in body, (
        "real glpat- tokens contain DOTS; a guard omitting `.` rejected the "
        "operator's actual token while a dot-free fixture passed"
    )
    assert "git_protocol: ssh" in body, "git protocol must match the host's (ssh)"


def test_gitlab_token_is_never_exported_to_the_environment(tmp_path: Path) -> None:
    home = _make_home(
        tmp_path,
        secrets={
            ".env": 'OAW_REQUIRED_SECRETS=""\n',
            "gitlab-cli-pat": "glpat-LEAKCANARY.123_abc-XYZ\n",
        },
    )
    (home / ".claude.json").write_text("{}")
    proc = subprocess.run(
        ["bash", "-c", f'. "{BOOTSTRAP}" >/dev/null 2>&1; env'],
        capture_output=True, text=True, timeout=60,
        env=_sealed_env(home), cwd=str(tmp_path),
    )
    assert "glpat-LEAKCANARY" not in proc.stdout


def test_architecture_doc_retains_every_documented_section() -> None:
    """Guard against silent documentation destruction.

    #1090 replaced a paragraph in architecture.md using a RANGE replace:

        start = s.index("**Blast-radius tradeoff …**")
        end   = s.index("## 4. Boundaries and invariants")
        s = s[:start] + new + s[end:]

    Everything between those anchors went with it — 262 lines covering §3.5.1,
    §3.6, §3.6.1 and §3.7, the documentation from #1076/#1079/#1082/#1085. It
    merged. Nothing failed, because no test asserted the doc's shape and prose
    deletion breaks no code. It surfaced only when a later anchor lookup failed.

    Cheap insurance: name the sections that must exist. A future range-replace
    that eats one fails here instead of on main.
    """
    doc = (
        REPO_ROOT / "docs" / "contained-workflow" / "architecture.md"
    ).read_text()
    required = [
        "### 3.5 Secrets: the read-only mount",
        "### 3.5.1 The CLI does not necessarily read",   # #1085
        "### 3.6 Agent authentication",                   # #1076
        "### 3.6.1 GitHub credential",                    # #1082
        "### 3.6.2 SSH parity",                           # #1089
        "### 3.7 First-run onboarding state",             # #1079
        "## 4. Boundaries and invariants",
    ]
    missing = [h for h in required if h not in doc]
    assert not missing, (
        f"architecture.md lost documented section(s): {missing}. If a section was "
        "renamed deliberately, update this list in the same commit — do NOT delete "
        "the entry, or the guard stops guarding."
    )


def test_operator_local_bin_never_shadows_the_kit() -> None:
    """The kit's own bin holds the claude wrapper and the MCP binaries.

    Mounting the operator's ~/.local/bin OVER /home/ubuntu/.local/bin would
    replace the #1076 wrapper with the host's claude and silently un-bootstrap
    every agent — the exact failure #1076 exists to prevent, reintroduced by a
    convenience mount. It must land beside the kit's bin and be APPENDED to PATH.
    """
    frag = (
        REPO_ROOT / "containers" / "oakandwave-workflow" / "mounts.d" / "30-user-overlay.toml"
    ).read_text()
    assert 'source = "~/.local/bin"' in frag, "operator utilities not mounted"
    assert 'target = "/home/ubuntu/.oaw/overlay/local-bin"' in frag
    assert 'target = "/home/ubuntu/.local/bin"' not in frag, (
        "mounting over the kit's bin would shadow the claude wrapper (#1076)"
    )

    dockerfile = (
        REPO_ROOT / "containers" / "oakandwave-workflow" / "Dockerfile"
    ).read_text()
    path_lines = [l for l in dockerfile.splitlines() if l.startswith("ENV PATH=")]
    assert path_lines, "no ENV PATH in the Dockerfile"
    final = path_lines[-1]
    assert "/home/ubuntu/.oaw/overlay/local-bin" in final, (
        "the overlay must be on PATH or the utilities are invisible"
    )
    kit = final.index("/home/ubuntu/.local/bin")
    overlay = final.index("/home/ubuntu/.oaw/overlay/local-bin")
    assert kit < overlay, (
        "the kit's bin must precede the operator overlay on PATH — otherwise a "
        "host utility named `claude` shadows the bootstrap wrapper"
    )


def test_operator_local_bin_is_read_only() -> None:
    """The container must not write into the operator's real ~/.local/bin."""
    frag = (
        REPO_ROOT / "containers" / "oakandwave-workflow" / "mounts.d" / "30-user-overlay.toml"
    ).read_text()
    block = frag[frag.index('name = "user-local-bin"'):]
    block = block[: block.find("[[mount]]") if "[[mount]]" in block else len(block)]
    assert 'mode = "ro"' in block, "operator bin mount must be read-only"


def test_git_transport_is_ssh_for_both_forges_with_no_url_rewrite() -> None:
    """git in the container goes over SSH, for BOTH forges, with no URL rewriting.

    Replaces ``test_git_transport_matches_the_host_per_forge`` (#1130), which
    asserted the opposite for github and justified it in its docstring by citing
    the operator's ``~/.gitconfig``. That evidence was written by this very suite:
    it sealed ``$OAW_HOME`` but not ``$HOME``, so ``git config --global`` in
    ``ensure_github_auth`` wrote the operator's real config on every run. The test
    pinned a conclusion drawn from our own side effect.

    What is actually true, measured in a live container after ``ensure_ssh_parity``:

        ssh -T git@github.com                   -> Hi bakeb7j0!
        ssh -T git@gitlab.com                   -> Welcome to GitLab, @brbaker-alog!
        git ls-remote ssh://git@github.com/...  -> resolves

    So a rewrite would only redirect a working SSH path onto a broadly-scoped
    token — invisibly, since ``git remote -v`` reports the rewritten URL.

    The credential helper is deliberately still asserted present: it is inert for
    SSH remotes and correct for a genuine ``https://`` one. Only the rewrite was
    the defect.
    """
    body = (
        REPO_ROOT / "containers" / "oakandwave-workflow" / "bootstrap.sh"
    ).read_text()

    # Assert on the CALL, not on prose: this file's own comments discuss the
    # rewrite at length, so a substring check against the whole body would match
    # the explanation of why it is gone.
    # Case-INSENSITIVE, on the bare word. Git config names are case-insensitive, so
    # `url.…insteadof` is legal and identical — and `pushInsteadOf` (the natural
    # reach for "push over HTTPS, fetch over SSH") does not contain the literal
    # ".insteadOf" at all. A substring check on the exact camelCase spelling would
    # wave through both.
    rewrites = [
        l.strip()
        for l in body.splitlines()
        if re.search(r"insteadof", l, re.I) and not l.lstrip().startswith("#")
    ]
    assert rewrites == [], (
        f"a URL rewrite is being configured: {rewrites}. git over SSH works for "
        "both forges; a rewrite silently moves it onto the PAT."
    )

    # Anchored to the CALL, not the raw body: eleven lines above, this test insists
    # on exactly that discipline, and bootstrap.sh's prose now discusses the helper
    # by name. A bare substring check would go green on a comment alone.
    assert re.search(
        r"^\s*git config --global .*\n?.*gh auth git-credential", body, re.M
    ), ("github credential helper is not CONFIGURED — needed for a genuine https remote")

    # Assert the CALL, not the definition. `"ensure_ssh_parity" in body` is
    # satisfied by the function existing while main never invokes it — the
    # declared-but-not-wired shape this repo keeps producing (#1076 most of all).
    # Caught by mutation: removing the call from main left that assertion green.
    assert re.search(r"^\s*ensure_ssh_parity\s*$", body, re.M), (
        "ensure_ssh_parity is never CALLED — the keys stay invisible and git over "
        "SSH fails, which is the failure the rewrite was papering over"
    )


_GUARD_RE = re.compile(r"^\[ -x (?P<path>\S+) \] \|\| exit 0; (?P<cmd>.*)$", re.S)


def _unguard(cmd: str) -> str:
    """Strip the #1107 `[ -x … ] || exit 0;` prefix, if present."""
    m = _GUARD_RE.match(cmd.strip())
    return m.group("cmd") if m else cmd


def _hook_commands_raw(settings: dict, event: str) -> list[tuple[str, str]]:
    """(matcher, command) pairs exactly as stored — guard and all."""
    return [
        (g.get("matcher") or "", h["command"])
        for g in settings.get("hooks", {}).get(event, [])
        for h in g.get("hooks", [])
        if isinstance(h.get("command"), str)
    ]


def _hook_commands(settings: dict, event: str) -> list[tuple[str, str]]:
    """(matcher, command) pairs under one event, with any #1107 guard removed.

    Tests about WHICH hooks are registered should not have to spell the wrapper;
    the guard is a delivery detail. Tests about the wrapper itself use
    ``_hook_commands_raw``.
    """
    return [(m, _unguard(c)) for m, c in _hook_commands_raw(settings, event)]


def test_kit_hooks_merge_into_the_settings_the_cli_reads(tmp_path: Path) -> None:
    """The image's hooks reach $CLAUDE_CONFIG_DIR/settings.json, additively.

    The destination is SHARED by every container and carries aoe's own status
    hooks and the operator's preferences, so this must add and never clobber.
    """
    import json as J

    home, cfgdir = _home_with_cfgdir(tmp_path)
    (cfgdir / "settings.json").write_text(J.dumps({
        "theme": "dark",
        "hooks": {"SessionStart": [
            {"matcher": "startup", "hooks": [
                {"type": "command", "command": "/bin/echo operator-own"}]}]},
    }))
    ws = tmp_path / "ws"; ws.mkdir()
    proc = _run_cfgdir(home, cfgdir, ws)
    assert proc.returncode == 0, proc.stderr

    got = J.loads((cfgdir / "settings.json").read_text())
    pairs = _hook_commands(got, "SessionStart")
    assert ("startup", "/bin/true") in pairs, "the image's hook never arrived"
    assert ("startup", "/bin/echo operator-own") in pairs, (
        "the operator's own hook was dropped — the merge must be additive"
    )
    assert got["theme"] == "dark", "non-hook operator settings must be untouched"


def test_kit_hook_merge_is_idempotent(tmp_path: Path) -> None:
    """A second boot registers nothing twice — a hook that runs twice per event
    is its own bug, and every container boots this code path on every launch."""
    import json as J

    home, cfgdir = _home_with_cfgdir(tmp_path)
    ws = tmp_path / "ws"; ws.mkdir()
    assert _run_cfgdir(home, cfgdir, ws).returncode == 0
    first = _hook_commands(J.loads((cfgdir / "settings.json").read_text()), "SessionStart")
    proc = _run_cfgdir(home, cfgdir, ws)
    assert proc.returncode == 0
    second = _hook_commands(J.loads((cfgdir / "settings.json").read_text()), "SessionStart")
    assert first == second, f"second boot changed the hook set: {first} -> {second}"
    assert "already present" in proc.stderr


# --- #1107: the merge target is SHARED ACROSS IMAGE VERSIONS ------------------
# sync_kit_hooks writes into a file every container on the host reads, while the
# hook scripts are image-versioned. So a hook new in release N is registered for
# containers running N-1, which do not have the script, and every SessionStart
# there fails with a missing-hook error. Caught by the operator on a live restart
# and by no test, because the #1086 suite drove the merge against fake homes where
# the script ALWAYS existed — the cross-version case was not representable.
#
# These tests represent it: the hook script is deleted from the image after the
# merge, which is exactly what an older container sees.


def _run_hook_command(cmd: str) -> subprocess.CompletedProcess[str]:
    """Execute a stored hook command the way the CLI does — through a shell."""
    return subprocess.run(["sh", "-c", cmd], capture_output=True, text=True, timeout=30)


def test_merged_hook_is_inert_when_the_script_is_absent(tmp_path: Path) -> None:
    """THE #1107 REGRESSION. A hook registered by a newer image must not error on
    a container whose image lacks the script."""
    import json as J

    home, cfgdir = _home_with_cfgdir(tmp_path)
    hook = home / ".claude" / "scripts" / "hooks" / "workflow" / "new-in-this-release.sh"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/sh\nexit 0\n")
    hook.chmod(0o755)
    (home / ".claude" / "settings.json").write_text(J.dumps({"hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": [{"type": "command", "command": str(hook)}]}]}}))

    ws = tmp_path / "ws"; ws.mkdir()
    assert _run_cfgdir(home, cfgdir, ws).returncode == 0

    stored = dict(_hook_commands_raw(J.loads((cfgdir / "settings.json").read_text()),
                                     "SessionStart"))["startup"]

    # Now BE the older container: same shared settings, script not in this image.
    hook.unlink()
    proc = _run_hook_command(stored)
    assert proc.returncode == 0, (
        "a hook the running image does not ship must be inert, not an error: "
        f"rc={proc.returncode} stderr={proc.stderr!r}"
    )
    assert "not found" not in (proc.stderr or "").lower(), proc.stderr


def test_the_guard_does_not_disable_the_hook_where_it_exists(tmp_path: Path) -> None:
    """The other half, and the one that makes the guard worth having rather than
    merely quiet: where the script IS present it must still run. A guard that
    silenced the beacon everywhere would pass the test above and gut #1086."""
    import json as J

    home, cfgdir = _home_with_cfgdir(tmp_path)
    marker = tmp_path / "fired"
    hook = home / ".claude" / "scripts" / "hooks" / "workflow" / "beacon.sh"
    hook.parent.mkdir(parents=True)
    hook.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n")
    hook.chmod(0o755)
    (home / ".claude" / "settings.json").write_text(J.dumps({"hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": [{"type": "command", "command": str(hook)}]}]}}))

    ws = tmp_path / "ws"; ws.mkdir()
    assert _run_cfgdir(home, cfgdir, ws).returncode == 0
    stored = dict(_hook_commands_raw(J.loads((cfgdir / "settings.json").read_text()),
                                     "SessionStart"))["startup"]
    assert _run_hook_command(stored).returncode == 0
    assert marker.exists(), "the guard swallowed a hook whose script is present"


def test_an_existing_bare_entry_is_upgraded_in_place(tmp_path: Path) -> None:
    """Guarding only NEW writes would leave the entry that caused #1107 sitting
    bare in the shared file, still breaking every older container. The fix has to
    reach the state that is already broken."""
    import json as J

    home, cfgdir = _home_with_cfgdir(tmp_path)
    (cfgdir / "settings.json").write_text(J.dumps({"hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": [{"type": "command", "command": "/bin/true"}]}]}}))

    ws = tmp_path / "ws"; ws.mkdir()
    proc = _run_cfgdir(home, cfgdir, ws)
    assert proc.returncode == 0, proc.stderr

    raw = _hook_commands_raw(J.loads((cfgdir / "settings.json").read_text()), "SessionStart")
    assert len(raw) == 1, f"the upgrade duplicated the entry instead of rewriting it: {raw}"
    assert raw[0][1].startswith("[ -x /bin/true ]"), (
        f"the pre-existing bare entry was left unguarded: {raw[0][1]!r}"
    )


def test_a_bare_entry_does_not_get_a_guarded_duplicate(tmp_path: Path) -> None:
    """Dedup must see through the guard. The destination now holds guarded
    spellings while the image ships bare ones; a key that did not unguard would
    call them different hooks and register both — the duplicate-execution bug
    #1094 is about, one layer out."""
    import json as J

    home, cfgdir = _home_with_cfgdir(tmp_path)
    ws = tmp_path / "ws"; ws.mkdir()
    assert _run_cfgdir(home, cfgdir, ws).returncode == 0
    first = _hook_commands_raw(J.loads((cfgdir / "settings.json").read_text()), "SessionStart")
    assert _run_cfgdir(home, cfgdir, ws).returncode == 0
    second = _hook_commands_raw(J.loads((cfgdir / "settings.json").read_text()), "SessionStart")
    assert first == second, f"a second boot changed the stored wiring: {first} -> {second}"
    assert len([c for _, c in second if "/bin/true" in c]) == 1, (
        f"the bare and guarded spellings were registered as two hooks: {second}"
    )


def test_non_path_commands_are_left_alone(tmp_path: Path) -> None:
    """The shared file also carries inline shell and bare builtins. A `-x` test on
    those would be wrong, not merely useless."""
    import json as J

    home, cfgdir = _home_with_cfgdir(tmp_path)
    (home / ".claude" / "settings.json").write_text(J.dumps({"hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": [{"type": "command", "command": "echo hi"}]}]}}))
    ws = tmp_path / "ws"; ws.mkdir()
    assert _run_cfgdir(home, cfgdir, ws).returncode == 0
    raw = dict(_hook_commands_raw(J.loads((cfgdir / "settings.json").read_text()),
                                  "SessionStart"))
    assert raw["startup"] == "echo hi", f"a non-path command was wrapped: {raw['startup']!r}"


def _append_like_an_older_image(cfgdir: Path, event: str, matcher: str, cmd: str) -> None:
    """Reproduce what an N-1 image's sync_kit_hooks does to this file.

    Its ``key()`` predates the guard, so a guarded entry keys on head ``[``, its own
    bare spelling looks absent, and it appends it. That is not a hypothetical: every
    image built between #1086 and #1107 behaves this way, and #1107 exists because
    the fleet runs several digests at once.
    """
    import json as J

    d = J.loads((cfgdir / "settings.json").read_text())
    d.setdefault("hooks", {}).setdefault(event, []).append(
        {"matcher": matcher, "hooks": [{"type": "command", "command": cmd}]})
    (cfgdir / "settings.json").write_text(J.dumps(d))


def test_an_older_image_readding_the_bare_form_converges(tmp_path: Path) -> None:
    """THE CONVERGENCE PROPERTY. Alternating boots between image versions must not
    grow the hook list.

    Without a prune: N writes [G]; N-1 appends bare -> [G, B]; N rewrites B in
    place -> [G, G]; N-1 appends again -> [G, G, B]. Unbounded, and #1094 measured
    that duplicate registrations really do double-fire.
    """
    import json as J

    home, cfgdir = _home_with_cfgdir(tmp_path)
    ws = tmp_path / "ws"; ws.mkdir()

    assert _run_cfgdir(home, cfgdir, ws).returncode == 0
    for _ in range(3):
        _append_like_an_older_image(cfgdir, "SessionStart", "startup", "/bin/true")
        assert _run_cfgdir(home, cfgdir, ws).returncode == 0

    raw = _hook_commands_raw(J.loads((cfgdir / "settings.json").read_text()), "SessionStart")
    hits = [c for _, c in raw if "/bin/true" in c]
    assert len(hits) == 1, f"the hook accumulated {len(hits)} registrations: {raw}"
    assert hits[0].startswith("[ -x /bin/true ]"), hits[0]


def test_the_prune_leaves_host_only_hooks_alone(tmp_path: Path) -> None:
    """The prune must be scoped to hooks THIS image ships. Collapsing entries the
    merge does not own would clobber aoe's own wiring and break its TUI — the
    thing this function has always refused to do."""
    import json as J

    home, cfgdir = _home_with_cfgdir(tmp_path)
    (cfgdir / "settings.json").write_text(J.dumps({"hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": [
            {"type": "command", "command": "/bin/echo aoe-own"},
            {"type": "command", "command": "/bin/echo aoe-own"},
        ]}]}}))
    ws = tmp_path / "ws"; ws.mkdir()
    assert _run_cfgdir(home, cfgdir, ws).returncode == 0
    raw = _hook_commands_raw(J.loads((cfgdir / "settings.json").read_text()), "SessionStart")
    assert len([c for _, c in raw if "aoe-own" in c]) == 2, (
        f"the prune reached host-only entries it does not own: {raw}"
    )


def test_the_build_defect_check_is_live_on_every_boot(tmp_path: Path) -> None:
    """It is the ONE compensating assertion for making absence inert, so it cannot
    be a one-shot. Computed inside the add-if-absent loop it would fire only
    against a virgin config dir and go silent forever after — on every real host
    the kit's hooks are already registered in this long-lived shared file."""
    import json as J

    home, cfgdir = _home_with_cfgdir(tmp_path)
    ghost = home / ".claude" / "scripts" / "hooks" / "workflow" / "never-built.sh"
    (home / ".claude" / "settings.json").write_text(J.dumps({"hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": [{"type": "command", "command": str(ghost)}]}]}}))
    ws = tmp_path / "ws"; ws.mkdir()

    assert "declares a hook it does not ship" in _run_cfgdir(home, cfgdir, ws).stderr
    second = _run_cfgdir(home, cfgdir, ws)
    assert second.returncode == 0, second.stderr
    assert "declares a hook it does not ship" in second.stderr, (
        "the build-defect check went silent on the second boot — which is every "
        f"boot on a real host: {second.stderr}"
    )


def test_a_shipped_but_non_executable_hook_is_reported(tmp_path: Path) -> None:
    """The guard tests `-x`, so a hook that ships without its exec bit is skipped
    at runtime exactly like a missing one. Before #1107 it failed loudly with
    'Permission denied'; checking only existence would trade that for silence."""
    import json as J

    home, cfgdir = _home_with_cfgdir(tmp_path)
    hook = home / ".claude" / "scripts" / "hooks" / "workflow" / "not-executable.sh"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/sh\nexit 0\n")
    hook.chmod(0o644)
    (home / ".claude" / "settings.json").write_text(J.dumps({"hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": [{"type": "command", "command": str(hook)}]}]}}))
    ws = tmp_path / "ws"; ws.mkdir()
    proc = _run_cfgdir(home, cfgdir, ws)
    assert proc.returncode == 0, proc.stderr
    assert "not executable" in proc.stderr, (
        f"a shipped-but-non-executable hook was silently inert: {proc.stderr}"
    )


def test_a_head_with_a_shell_metacharacter_is_not_guarded(tmp_path: Path) -> None:
    """The head is spliced RAW into the test, so `[ -x /p/x.sh;` loses its `]`,
    the shell errors, and the trailing `|| exit 0` swallows a hook whose script is
    present. Refusing to wrap costs the #1107 protection for one odd hook;
    wrapping something unparseable silently disables a working one."""
    import json as J

    home, cfgdir = _home_with_cfgdir(tmp_path)
    cmd = "/bin/true;echo x"
    (home / ".claude" / "settings.json").write_text(J.dumps({"hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": [{"type": "command", "command": cmd}]}]}}))
    ws = tmp_path / "ws"; ws.mkdir()
    assert _run_cfgdir(home, cfgdir, ws).returncode == 0
    raw = dict(_hook_commands_raw(J.loads((cfgdir / "settings.json").read_text()),
                                  "SessionStart"))
    assert raw["startup"] == cmd, f"a metacharacter head was wrapped: {raw['startup']!r}"


def test_a_quoted_path_is_not_guarded(tmp_path: Path) -> None:
    """A quoted command head is not a bare path, so it must be left alone.

    The guard picks its test target by splitting on the first space — which is
    exactly how the shell that runs the hook parses it, so an UNQUOTED path with a
    space is already broken identically with or without the guard. A QUOTED one is
    not broken, and guessing a target from it would produce `[ -x "/path ]` and
    silently disable a hook that works. Left verbatim instead.
    """
    import json as J

    home, cfgdir = _home_with_cfgdir(tmp_path)
    cmd = '"/opt/dir with space/hook.sh"'
    (home / ".claude" / "settings.json").write_text(J.dumps({"hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": [{"type": "command", "command": cmd}]}]}}))
    ws = tmp_path / "ws"; ws.mkdir()
    assert _run_cfgdir(home, cfgdir, ws).returncode == 0
    raw = dict(_hook_commands_raw(J.loads((cfgdir / "settings.json").read_text()),
                                  "SessionStart"))
    assert raw["startup"] == cmd, f"a quoted path was wrapped: {raw['startup']!r}"


def test_an_image_declaring_a_hook_it_does_not_ship_is_reported(tmp_path: Path) -> None:
    """The one case the guard could hide. Absence becomes inert EVERYWHERE, so a
    build defect — this image declaring a hook it never shipped — would be
    absorbed silently. It is caught against the image that claims the hook."""
    import json as J

    home, cfgdir = _home_with_cfgdir(tmp_path)
    ghost = home / ".claude" / "scripts" / "hooks" / "workflow" / "never-built.sh"
    (home / ".claude" / "settings.json").write_text(J.dumps({"hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": [{"type": "command", "command": str(ghost)}]}]}}))
    ws = tmp_path / "ws"; ws.mkdir()
    proc = _run_cfgdir(home, cfgdir, ws)
    assert proc.returncode == 0, proc.stderr
    assert "declares a hook it does not ship" in proc.stderr, (
        f"a hook the image declares but does not ship went unreported: {proc.stderr}"
    )


def test_validate_still_flags_an_unguarded_missing_hook(tmp_path: Path) -> None:
    """The guard must not make the validator blind. An UNGUARDED hook that cannot
    resolve is still a real defect — trading a noisy failure for a silent one is
    the worse of the two, and preflight check 7 greps for exactly this line."""
    import json as J

    home, cfgdir = _home_with_cfgdir(tmp_path)
    # Host-only entry: not something this image ships, so the merge leaves it bare.
    (cfgdir / "settings.json").write_text(J.dumps({"hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": [
            {"type": "command", "command": "/nonexistent/host/only/hook.sh"}]}]}}))
    ws = tmp_path / "ws"; ws.mkdir()
    proc = _run_cfgdir(home, cfgdir, ws)
    assert proc.returncode == 0, proc.stderr
    assert "does not exist in this container" in proc.stderr, (
        f"an unresolvable unguarded hook went unreported: {proc.stderr}"
    )


def test_validate_is_quiet_about_a_guarded_missing_hook(tmp_path: Path) -> None:
    """A guarded path is inert by construction, so reporting it would put a
    warning on every boot of every older container — the 'warning on every boot'
    erosion #1078 closed, reintroduced one layer out."""
    import json as J

    home, cfgdir = _home_with_cfgdir(tmp_path)
    (cfgdir / "settings.json").write_text(J.dumps({"hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": [{"type": "command", "command":
            "[ -x /nonexistent/newer/image/hook.sh ] || exit 0; /nonexistent/newer/image/hook.sh"}]}]}}))
    ws = tmp_path / "ws"; ws.mkdir()
    proc = _run_cfgdir(home, cfgdir, ws)
    assert proc.returncode == 0, proc.stderr
    assert "/nonexistent/newer/image/hook.sh" not in proc.stderr, (
        f"a deliberately-inert guarded hook was warned about: {proc.stderr}"
    )


def test_same_command_under_a_different_matcher_is_not_dropped(tmp_path: Path) -> None:
    """Dedup is on (matcher, command), not command alone.

    The kit legitimately registers one script under several matchers —
    context-freshness-warn.sh ships under BOTH `startup` and `resume`. A
    command-only key silently drops the second registration, which is the very
    bug this merge exists to fix, wearing a merge's clothes.
    """
    import json as J

    home, cfgdir = _home_with_cfgdir(tmp_path)
    (home / ".claude" / "settings.json").write_text(J.dumps({"hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": [{"type": "command", "command": "/bin/true"}]},
        {"matcher": "resume", "hooks": [{"type": "command", "command": "/bin/true"}]},
    ]}}))
    ws = tmp_path / "ws"; ws.mkdir()
    assert _run_cfgdir(home, cfgdir, ws).returncode == 0
    pairs = _hook_commands(J.loads((cfgdir / "settings.json").read_text()), "SessionStart")
    assert ("startup", "/bin/true") in pairs
    assert ("resume", "/bin/true") in pairs, (
        "the resume registration was swallowed by a command-only dedup"
    )


def test_absent_effective_settings_is_created_not_bailed_on(tmp_path: Path) -> None:
    """A fresh aoe profile has a config dir with no settings.json in it.

    Warning-and-returning there reproduces the exact production state this fixes:
    a container running none of the release's hooks.
    """
    import json as J

    home, cfgdir = _home_with_cfgdir(tmp_path)
    ws = tmp_path / "ws"; ws.mkdir()
    assert not (cfgdir / "settings.json").exists()
    proc = _run_cfgdir(home, cfgdir, ws)
    assert proc.returncode == 0, proc.stderr
    assert (cfgdir / "settings.json").is_file(), "bootstrap must create it"
    pairs = _hook_commands(J.loads((cfgdir / "settings.json").read_text()), "SessionStart")
    assert ("startup", "/bin/true") in pairs


def test_malformed_effective_settings_is_not_clobbered(tmp_path: Path) -> None:
    """Unparseable destination → warn and leave it ALONE.

    This file is shared by every container on the host. Overwriting one the
    operator is mid-edit, to 'fix' it, would be a worse failure than the one being
    reported — and the CLI is already showing them a Settings Error.
    """
    home, cfgdir = _home_with_cfgdir(tmp_path)
    (cfgdir / "settings.json").write_text("{ not json at all")
    ws = tmp_path / "ws"; ws.mkdir()
    proc = _run_cfgdir(home, cfgdir, ws)
    assert proc.returncode == 0, "a malformed shared file must not abort the boot"
    assert (cfgdir / "settings.json").read_text() == "{ not json at all"
    # Name the MERGE's own message. A bare "hooks:" match is satisfied by
    # validate_hook_paths, which also chokes on this file and reports it later —
    # so the assertion passed under a mutation that removed the merge entirely.
    # An instrument that reads another function's output is not measuring this one.
    assert "could not merge kit hook wiring" in proc.stderr, (
        "the merge must report its own refusal, not leave it to a later stage"
    )


def test_native_install_does_not_merge_a_file_into_itself(tmp_path: Path) -> None:
    """With no CLAUDE_CONFIG_DIR, source and destination ARE the same file.

    #1085's first cut collapsed the two config locations into one expression and
    broke every non-aoe path; this is the same hazard one function over.
    """
    home = _make_home(tmp_path, secrets={".env": 'OAW_REQUIRED_SECRETS=""\n'})
    before = (home / ".claude" / "settings.json").read_text()
    proc = _run(home)
    assert proc.returncode == 0, proc.stderr
    assert (home / ".claude" / "settings.json").read_text() == before
    assert "reads the image settings directly" in proc.stderr


# --- the beacon that makes "a hook FIRED" assertable (#1086) ------------------


BEACON = REPO_ROOT / "scripts" / "hooks" / "workflow" / "kit-hooks-alive.sh"


def test_beacon_hook_exists_and_is_executable() -> None:
    assert BEACON.is_file(), f"missing beacon hook: {BEACON}"
    assert os.access(BEACON, os.X_OK), f"beacon hook is not executable: {BEACON}"


def test_beacon_writes_its_marker_by_running(tmp_path: Path) -> None:
    """The marker must be a side effect of EXECUTION.

    That is the entire point: a settings file naming a hook proves nothing, and
    in #1086 the file named every right hook for the wrong reason.
    """
    home = tmp_path / "beaconhome"
    (home / ".claude").mkdir(parents=True)
    proc = subprocess.run(
        ["bash", str(BEACON)], capture_output=True, text=True, timeout=30,
        env={**os.environ, "HOME": str(home)},
    )
    assert proc.returncode == 0
    marker = home / ".claude" / ".kit-hooks-alive"
    assert marker.is_file(), "the beacon did not write its marker"
    assert marker.read_text().strip(), "the marker is empty — no timestamp recorded"


def test_beacon_is_silent_on_stdout(tmp_path: Path) -> None:
    """SessionStart stdout becomes additionalContext in the agent's window. A
    beacon that spends context would tax every session for the life of the kit.

    Uses a tempdir HOME, not the ambient one (#1130). This previously ran the
    beacon with ``HOME`` = the operator's real home, so asserting "silent on
    stdout" had the side effect of writing ``~/.claude/.kit-hooks-alive`` on the
    host every run. The marker is a kit file and harmless in itself — but a suite
    that writes outside its tempdir at all is one refactor away from writing
    something that is not harmless, which is precisely how the ~/.gitconfig leak
    happened. The beacon needs ``$HOME/.claude`` to exist; it does not need it to
    be the operator's.
    """
    home = tmp_path / "beaconhome"
    (home / ".claude").mkdir(parents=True)
    proc = subprocess.run(
        ["bash", str(BEACON)], capture_output=True, text=True, timeout=30,
        env={**os.environ, "HOME": str(home)},
    )
    assert proc.stdout == "", f"beacon wrote to stdout: {proc.stdout!r}"


def test_beacon_is_wired_into_the_settings_template() -> None:
    """Shipping the script without registering it is the declared-but-not-wired
    shape this repo keeps producing (#1076 above all)."""
    import json as J

    tmpl = J.loads((REPO_ROOT / "config" / "settings.template.json").read_text())
    cmds = [
        h.get("command", "")
        for g in tmpl["hooks"]["SessionStart"]
        for h in g.get("hooks", [])
    ]
    assert any("kit-hooks-alive.sh" in c for c in cmds), (
        "the beacon is not registered in settings.template.json — it would ship inert"
    )


def test_tilde_and_absolute_forms_of_one_hook_register_once(tmp_path: Path) -> None:
    """Two commands that RESOLVE to the same script are one hook.

    Not hypothetical — measured live. The image bakes wtf-post-tool-use.sh under
    BOTH ``~/.local/share/...`` (settings.template.json) and
    ``/home/ubuntu/.local/share/...`` (added at build time), and the shared
    settings already carried the absolute form. A string-keyed dedup called those
    two different hooks and registered the second, so it fired TWICE on every
    tool use. A merge that introduces duplicate execution is not preserving the
    release's wiring — it is corrupting it.
    """
    import json as J

    home, cfgdir = _home_with_cfgdir(tmp_path)
    # The image ships both spellings, exactly as the real one does.
    (home / ".claude" / "settings.json").write_text(J.dumps({"hooks": {"PostToolUse": [
        {"matcher": "", "hooks": [{"type": "command", "command": "~/hook.sh"}]},
        {"matcher": "", "hooks": [
            {"type": "command", "command": str(home) + "/hook.sh"}]},
    ]}}))
    (home / "hook.sh").write_text("#!/bin/sh\nexit 0\n")
    ws = tmp_path / "ws"; ws.mkdir()
    proc = _run_cfgdir(home, cfgdir, ws, HOME=str(home))
    assert proc.returncode == 0, proc.stderr

    got = _hook_commands(J.loads((cfgdir / "settings.json").read_text()), "PostToolUse")
    assert len(got) == 1, f"the same hook registered {len(got)} times: {got}"


def test_absolute_form_already_present_blocks_the_tilde_form(tmp_path: Path) -> None:
    """The destination's spelling wins when both name the same script.

    This is the live case: the shared settings carried the absolute path (a
    by-hand #1085 fix) and the image ships the tilde form. Adding the tilde form
    on top is what doubled the hook.
    """
    import json as J

    home, cfgdir = _home_with_cfgdir(tmp_path)
    (home / ".claude" / "settings.json").write_text(J.dumps({"hooks": {"PostToolUse": [
        {"matcher": "", "hooks": [{"type": "command", "command": "~/hook.sh"}]}]}}))
    (home / "hook.sh").write_text("#!/bin/sh\nexit 0\n")
    (cfgdir / "settings.json").write_text(J.dumps({"hooks": {"PostToolUse": [
        {"matcher": "", "hooks": [
            {"type": "command", "command": str(home) + "/hook.sh"}]}]}}))
    ws = tmp_path / "ws"; ws.mkdir()
    assert _run_cfgdir(home, cfgdir, ws, HOME=str(home)).returncode == 0

    got = _hook_commands(J.loads((cfgdir / "settings.json").read_text()), "PostToolUse")
    assert got == [("", str(home) + "/hook.sh")], f"tilde form was added on top: {got}"


# --- R-11 toolbox materialisation (#1092) ------------------------------------
#
# The mount has been declared since Story 1.3 and nothing ever materialised into
# it. bifrost hit the consequence head-on: `java`, `mvn`, `docker` all
# command-not-found on a Java repo, so every session started by bootstrapping the
# world. Same declared-but-not-wired shape as #1076, #1061 and #1056.
#
# `mise` is stubbed here rather than really installing a JDK: these assert the
# BOOTSTRAP's contract (when does it invoke, what does it tolerate, does it
# reshim), not mise's. A test that downloaded a real toolchain would be slow
# enough to get deleted, and would be testing someone else's software.


def _stub_mise(binroot: Path, *, exit_code: int = 0, message: str = "") -> Path:
    """A fake `mise` that records its argv so we can assert what bootstrap asked."""
    binroot.mkdir(parents=True, exist_ok=True)
    stub = binroot / "mise"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$@" >> "{binroot}/calls.log"\n'
        f'[[ -n "{message}" ]] && echo "{message}" >&2\n'
        f"exit {exit_code}\n"
    )
    stub.chmod(0o755)
    return stub


def _run_toolbox(home: Path, toolbox: Path, binroot: Path | None = None, **env: str):
    e = _sealed_env(home, OAW_TOOLBOX_DIR=str(toolbox))
    if binroot is not None:
        e["PATH"] = f"{binroot}:{e['PATH']}"
    e.update(env)
    return subprocess.run(
        ["bash", str(BOOTSTRAP)], capture_output=True, text=True, timeout=60, env=e
    )


def test_declared_toolchain_is_materialised(tmp_path: Path) -> None:
    """The defect itself: a declared manifest must actually be installed."""
    home = _make_home(tmp_path, secrets={".env": 'OAW_REQUIRED_SECRETS=""\n'})
    toolbox = tmp_path / "toolbox"
    toolbox.mkdir()
    (toolbox / "mise.toml").write_text('[tools]\njava = "17"\nmaven = "3.9"\n')
    binroot = tmp_path / "bin"
    proc = _run_toolbox(home, toolbox, binroot=_stub_mise(binroot).parent)

    assert proc.returncode == 0, proc.stderr
    calls = (binroot / "calls.log").read_text()
    assert "install" in calls, f"bootstrap never ran `mise install` (calls: {calls!r})"
    assert "materialised" in proc.stderr


def test_reshim_runs_after_install(tmp_path: Path) -> None:
    """Without a reshim, a freshly-installed tool has no PATH entry.

    The install would "succeed" while `mvn` stays command-not-found — a pass that
    leaves the reported problem exactly where it was.
    """
    home = _make_home(tmp_path, secrets={".env": 'OAW_REQUIRED_SECRETS=""\n'})
    toolbox = tmp_path / "toolbox"
    toolbox.mkdir()
    (toolbox / "mise.toml").write_text('[tools]\njava = "17"\n')
    binroot = tmp_path / "bin"
    _run_toolbox(home, toolbox, binroot=_stub_mise(binroot).parent)
    assert "reshim" in (binroot / "calls.log").read_text(), "install without reshim"


def test_absent_manifest_is_info_not_a_warning(tmp_path: Path) -> None:
    """Most agents never touch a toolchain, so no manifest is the COMMON case.

    A warning on every healthy boot is how a fleet learns to stop reading
    warnings — the same erosion this file's assertion-liveness discipline exists
    to prevent, arriving from the opposite direction.
    """
    home = _make_home(tmp_path, secrets={".env": 'OAW_REQUIRED_SECRETS=""\n'})
    toolbox = tmp_path / "toolbox"
    toolbox.mkdir()
    proc = _run_toolbox(home, toolbox)
    assert proc.returncode == 0
    assert "toolbox: no manifest" in proc.stderr
    assert "WARN: toolbox: no manifest" not in proc.stderr


def test_missing_toolbox_mount_is_logged(tmp_path: Path) -> None:
    """An absent mount is the enumerated silent-skip — it must be loud."""
    home = _make_home(tmp_path, secrets={".env": 'OAW_REQUIRED_SECRETS=""\n'})
    proc = _run_toolbox(home, tmp_path / "does-not-exist")
    assert proc.returncode == 0
    assert "missing mount: toolbox dir not present" in proc.stderr


def test_offline_install_warns_but_the_agent_still_starts(tmp_path: Path) -> None:
    """A container with no Maven is bad; a container with no AGENT is worse.

    The wrapper SOURCES bootstrap and then execs the CLI, so a fatal here means
    no agent at all.
    """
    home = _make_home(tmp_path, secrets={".env": 'OAW_REQUIRED_SECRETS=""\n'})
    toolbox = tmp_path / "toolbox"
    toolbox.mkdir()
    (toolbox / "mise.toml").write_text('[tools]\njava = "17"\n')
    binroot = tmp_path / "bin"
    _stub_mise(binroot, exit_code=1, message="failed to resolve host mise-versions.jdx.dev")
    proc = _run_toolbox(home, toolbox, binroot=binroot)

    assert proc.returncode == 0, "an offline toolbox must never fail the boot"
    assert "mise install failed" in proc.stderr
    assert "mise-versions" in proc.stderr, "mise's own diagnosis must be surfaced, not swallowed"


def test_manifest_without_mise_is_reported(tmp_path: Path) -> None:
    """A declared toolchain and no installer is exactly #1092 in miniature."""
    home = _make_home(tmp_path, secrets={".env": 'OAW_REQUIRED_SECRETS=""\n'})
    toolbox = tmp_path / "toolbox"
    toolbox.mkdir()
    (toolbox / "mise.toml").write_text('[tools]\njava = "17"\n')
    empty = tmp_path / "emptybin"
    empty.mkdir()
    # PATH with no mise on it at all.
    proc = _run_toolbox(home, toolbox, PATH=f"{empty}:/usr/bin:/bin")
    assert proc.returncode == 0
    assert "mise is not installed" in proc.stderr


# --- the image half: installer baked, toolchain NOT ---------------------------

DOCKERFILE = REPO_ROOT / "containers" / "oakandwave-workflow" / "Dockerfile"


def _dockerfile_instructions() -> str:
    """The Dockerfile with comments stripped.

    Scanning the raw text asks the COMMENTARY, not the config. The block
    explaining mise necessarily names the toolchains it can materialise ("JDK /
    Maven / Node …"), so a raw-text check for "maven" matches the sentence that
    says we do NOT bake Maven — and reports the defect present while the image is
    correct. That is the same instrument-reads-its-own-advice failure as
    bootstrap's hook validator matching its own warning text and #1063's trigger
    test matching its own rationale; it was caught here by this very assertion
    failing against a correct Dockerfile.
    """
    return "\n".join(
        ln for ln in DOCKERFILE.read_text().splitlines() if not ln.lstrip().startswith("#")
    )


def test_image_bakes_the_installer_not_the_toolchain() -> None:
    """R-11's whole point. A baked JDK rides along in every agent that never
    touches Java, and bumping Maven becomes a kit release."""
    instructions = _dockerfile_instructions()
    assert "mise" in instructions, "the toolbox installer must be baked"
    lowered = instructions.lower()
    for forbidden in ("openjdk", "temurin", "adoptium", "maven-3", "apt-get install -y maven"):
        assert forbidden not in lowered, (
            f"{forbidden!r} is baked into the base image — R-11 exists to keep "
            f"per-repo toolchains OUT of the image"
        )


def test_toolbox_shims_are_on_the_image_path_not_a_shell_rc() -> None:
    """`docker exec` resolves against the IMAGE's PATH, not a shell's.

    Non-interactive shells never read ~/.bashrc, which is why bifrost had to
    hand-source an env file. A hook or an agent-run command must find `mvn` with
    no shell cooperation at all — so the shims live in ENV PATH.
    """
    path_lines = [
        ln for ln in _dockerfile_instructions().splitlines() if ln.startswith("ENV PATH=")
    ]
    assert path_lines, "no ENV PATH in the Dockerfile"
    final = path_lines[-1]
    assert "toolbox/mise/shims" in final, f"shims not on the image PATH: {final}"

    entries = final.split("PATH=", 1)[1].strip('"').split(":")
    shims = next(i for i, e in enumerate(entries) if "mise/shims" in e)
    kit = next(i for i, e in enumerate(entries) if e.endswith("/.local/bin"))
    assert kit < shims, (
        "toolbox shims precede the kit's own bin dir — a user toolchain could "
        "shadow a kit binary and §3.4 keeps the RTE authoritative"
    )


def test_mise_is_pinned_not_piped() -> None:
    """A build step that executes whatever a URL serves today is not
    reproducible; it is the supply-chain surface the pinned-tarball rule exists
    to avoid (same rule as trivy and bao)."""
    instructions = _dockerfile_instructions()
    assert "ARG MISE_VERSION=" in instructions, "mise must be version-pinned"
    assert "mise.run" not in instructions, (
        "mise must be installed from a pinned tarball, never a piped installer"
    )


def test_toolbox_exports_the_global_config_so_shims_can_resolve(tmp_path: Path) -> None:
    """A shim on PATH that cannot resolve a version is not a toolchain.

    Measured live before this existed: `command -v java` returned the shim while
    `java -version` said "No version is set for shim: java". The shims resolve
    their version from mise's GLOBAL config, and nothing pointed at the operator
    manifest — so the install succeeded and the tool still would not run.

    The wrapper SOURCES bootstrap and then execs the agent, so exporting here is
    what carries it to the agent and every hook — the same mechanism
    CLAUDE_CODE_OAUTH_TOKEN depends on.
    """
    body = BOOTSTRAP.read_text()
    assert re.search(r'^\texport MISE_GLOBAL_CONFIG_FILE="\$manifest"$', body, re.M), (
        "sync_toolbox must EXPORT MISE_GLOBAL_CONFIG_FILE to the manifest it found; "
        "a non-exported assignment dies with this shell and the agent sees nothing"
    )


def test_image_sets_a_global_config_floor_for_bare_docker_exec() -> None:
    """bootstrap's export covers a non-default toolbox path, but a bare
    `docker exec` that never ran bootstrap still needs the default to resolve."""
    instructions = _dockerfile_instructions()
    assert "ENV MISE_GLOBAL_CONFIG_FILE=" in instructions, (
        "the image must name the operator manifest as mise's global config"
    )
    assert "ENV MISE_DATA_DIR=/home/ubuntu/.oaw/toolbox/mise" in instructions, (
        "mise's data dir must be the DURABLE toolbox mount, or every container "
        "re-downloads the toolchain it already had"
    )


# --- skills host-fill: the mount exists now (#1078) ---------------------------
#
# The host-fill path was declared from the start and NOTHING EVER MOUNTED TO IT.
# It stayed invisible until #1076 made bootstrap actually run, and then every
# agent boot warned. A warning that is always true is one operators learn to
# skip — the same erosion as #1061's inert R-14 and #1056's zero manifests.
#
# The fix is NOT to silence it. #1078 says so explicitly ("an unconditional
# demote reproduces the inert-guard shape one layer down"), so the two states are
# made distinguishable instead: empty-and-mounted is info, declared-and-absent
# stays a WARN.


def test_present_but_empty_host_overlay_is_info_not_a_warning(tmp_path: Path) -> None:
    """The common, healthy case. Most operators ship no extra skills."""
    home = _make_home(tmp_path, secrets={".env": 'OAW_REQUIRED_SECRETS=""\n'})
    proc = _run(home)  # _make_home creates the host skills dir, empty
    assert proc.returncode == 0, proc.stderr
    assert "INFO: skills-sync: host overlay present and empty" in proc.stderr
    assert "missing mount: host skills overlay" not in proc.stderr, (
        "an empty mounted overlay must not warn — that WARN fired on every boot "
        "of every agent and is what taught the fleet to skip bootstrap output"
    )


def test_absent_host_overlay_still_warns(tmp_path: Path) -> None:
    """Now that a mount is declared, absence means it did not happen.

    This must NOT be demoted along with the empty case, or the guard becomes
    inert exactly where it finally has something real to catch.
    """
    home = _make_home(tmp_path, secrets={".env": 'OAW_REQUIRED_SECRETS=""\n'})
    (home / ".oaw" / ".claude" / "skills").rmdir()
    (home / ".oaw" / ".claude").rmdir()
    proc = _run(home)
    assert proc.returncode == 0
    # Assert the LEVEL, not just the text. The first cut matched only the
    # message, which is byte-identical between `warn` and `info` — so a mutation
    # that demoted this exact guard passed all three tests. Asserting a string
    # that survives the change you are guarding against is not a guard.
    assert "WARN: missing mount: host skills overlay not present" in proc.stderr, (
        "declared-and-absent must stay a WARN; demoting it alongside the empty "
        "case is the inert-guard shape #1078 explicitly forbids"
    )


def test_host_fill_still_fills_when_the_overlay_has_skills(tmp_path: Path) -> None:
    """The behaviour the quiet path must not have broken."""
    home = _make_home(tmp_path, image_skills=["alpha"], host_skills=["beta"])
    proc = _run(home)
    assert proc.returncode == 0, proc.stderr
    beta = home / ".claude" / "skills" / "beta"
    assert beta.is_symlink() and beta.exists(), "host-fill stopped filling gaps"
    assert "host overlay present and empty" not in proc.stderr
