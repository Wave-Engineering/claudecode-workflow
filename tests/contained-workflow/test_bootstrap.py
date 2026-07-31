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

* missing mount   — ``test_missing_host_skills_mount_is_logged_no_dangling``,
  ``test_missing_settings_local_is_logged`` `[R-14]`
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
    settings_local: str | None = None,
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
        (home / ".claude" / "settings.json").write_text('{"hooks": {}}\n')
    if settings_local is not None:
        (home / ".claude" / "settings.local.json").write_text(settings_local)
    for fname, content in (secrets or {}).items():
        (secrets_dir / fname).write_text(content)

    return home


def _run(home: Path, **env_overrides: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["OAW_HOME"] = str(home)
    env.update(env_overrides)
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


def test_missing_settings_local_is_logged(tmp_path: Path) -> None:
    """Absent settings.local mount → logged (silent-skip made loud), non-fatal."""
    home = _make_home(tmp_path)  # no settings_local
    proc = _run(home)
    assert proc.returncode == 0, proc.stderr
    assert "missing mount: settings.local.json" in proc.stderr


def test_malformed_settings_local_is_logged(tmp_path: Path) -> None:
    """Malformed settings.local → loud warning (CC's merge would silently drop it)."""
    home = _make_home(tmp_path, settings_local="{ this is not json ]")
    proc = _run(home)
    assert proc.returncode == 0, proc.stderr
    assert "not valid JSON" in proc.stderr


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
        settings_local='{"permissions": {}}\n',
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
    logged = _run(home)
    assert logged.returncode == 0, logged.stderr
    assert "skills-sync collision" in logged.stderr  # shadowed skill
    assert "dangling symlink" in logged.stderr  # dangling link
    assert "missing mount: settings.local.json" in logged.stderr  # 2) missing mount

    # 4) missing secret FAILS LOUD (the same layout, plus a required secret).
    failed = _run(home, OAW_REQUIRED_SECRETS="MUST_HAVE_TOKEN")
    assert failed.returncode != 0, "missing required secret must fail loud (R-14)"
    assert "FATAL" in failed.stderr
    assert "MUST_HAVE_TOKEN" in failed.stderr


# --- The wiring, not just the script (#1076) ---------------------------------
#
# Everything above drives bootstrap.sh directly by subprocess. That proves the
# script WORKS and is exactly why the real defect shipped: nothing ever ran it.
# aoe starts the image with `sleep infinity` as PID 1 and `docker exec`s `claude`
# as a separate process, so bootstrap had no process path to the agent and every
# phase — skills-sync, settings merge, secret projection, R-14 validation — was
# inert in production while this file stayed green.
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
        settings_local="{}",
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
        env={**os.environ, "OAW_HOME": str(home)},
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
