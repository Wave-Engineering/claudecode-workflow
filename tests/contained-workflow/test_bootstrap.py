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
    manifest.write_text("# required secrets\nDISCORD_BOT_TOKEN\n\nSLACK_BOT_TOKEN\n")
    proc = _run(home)
    assert proc.returncode != 0
    assert "DISCORD_BOT_TOKEN" in proc.stderr
    assert "SLACK_BOT_TOKEN" in proc.stderr


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
    assert "0 fatal(s)" in proc.stdout
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
