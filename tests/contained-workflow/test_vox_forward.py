"""A containerised agent's voice (#1084).

`vox` cannot work inside a container: no provider, and no player at all — none of
afplay/paplay/aplay/ffplay, and no libpulse. Discord still reached the operator,
but the audible interrupt, the thing that gets attention when nobody is watching
a channel, was gone for every agent moved into a container.

The fix forwards TEXT, not audio: the container's provider spools a message onto
a host-visible mount and the host's own `vox` synthesises and plays it.

**The load-bearing test in this file is the stale-spool one.** Everything else
verifies the happy path, which is the easy half. If nothing on the host drains
the spool, an agent would otherwise believe it is speaking while the operator
hears silence — the inert-guard shape this repo keeps producing (#1061 R-14,
#1056 trivy, #1069 "[0 items]"). That failure is invisible from inside the
container unless the provider goes out of its way to be loud, so that is the
assertion that keeps this feature from rotting.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PROVIDER = REPO / "scripts" / "vox-providers" / "host-forward.sh"
PLAYER = REPO / "scripts" / "vox-spool" / "no-op-player.sh"
DRAIN = REPO / "scripts" / "oaw-vox-drain"
FRAGMENT = REPO / "containers" / "oakandwave-workflow" / "mounts.d" / "50-vox-spool.toml"
DOCKERFILE = REPO / "containers" / "oakandwave-workflow" / "Dockerfile"


def _spool(tmp_path: Path) -> Path:
    d = tmp_path / "spool"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _forward(
    tmp_path: Path, text: str, *, cwd: Path | None = None, **env: str
) -> subprocess.CompletedProcess[str]:
    spool = _spool(tmp_path)
    return subprocess.run(
        ["bash", str(PROVIDER), text],
        capture_output=True,
        text=True,
        cwd=str(cwd or tmp_path),
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp_path),
            "OAW_VOX_SPOOL": str(spool),
            "VOX_OUTPUT_FILE": str(tmp_path / "out.wav"),
            **env,
        },
        timeout=60,
    )


def _messages(tmp_path: Path) -> list[Path]:
    return sorted(_spool(tmp_path).glob("*.msg"))


def test_host_forward_provider_writes_spool_file(tmp_path: Path) -> None:
    proc = _forward(tmp_path, "hello from a container")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    msgs = _messages(tmp_path)
    assert len(msgs) == 1, f"expected exactly one spooled message, got {msgs}"
    assert "hello from a container" in msgs[0].read_text()


def test_the_provider_satisfies_voxs_audio_contract(tmp_path: Path) -> None:
    """vox hands the provider $VOX_OUTPUT_FILE and then passes it to the player.
    There is no audio to make here, but the file must exist or the pairing breaks
    on whatever vox does with it next."""
    _forward(tmp_path, "anything")
    assert (tmp_path / "out.wav").exists()


def test_host_forward_includes_agent_identity(tmp_path: Path) -> None:
    """Several agents share one host spool, so what is heard must be attributable.

    Identity is project-rooted, and resolved by walking UP from the working
    directory the way vox's own resolve_speaker does. Reading
    `$HOME/.claude/agent-identity.json` instead looked correct and produced
    `dev_name: unknown` against a real container.
    """
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "agent-identity.json").write_text(
        json.dumps({"dev_team": "oaw", "dev_name": "babelfish", "dev_avatar": "X"})
    )
    deep = proj / "src" / "nested"
    deep.mkdir(parents=True)

    proc = _forward(tmp_path, "attributable", cwd=deep)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "dev_name: babelfish" in _messages(tmp_path)[0].read_text()


def test_unconsumed_spool_warns(tmp_path: Path) -> None:
    """THE ONE THAT MATTERS. A spool nobody is draining means the agent is not
    being heard, and it cannot tell from in here. Silence must be loud."""
    spool = _spool(tmp_path)
    stale = spool / "20200101T000000Z.1.1.msg"
    stale.write_text("dev_name: ghost\n\nold\n")
    old = time.time() - 600
    os.utime(stale, (old, old))

    proc = _forward(tmp_path, "am I being heard?")
    assert "WARNING" in proc.stderr, (
        f"a stale spool produced no warning — the agent would believe it spoke: {proc.stderr}"
    )
    assert "NOT heard" in proc.stderr
    # Still spooled: the drain may come back. Warn, do not discard.
    assert any("am I being heard?" in m.read_text() for m in _messages(tmp_path))


def test_a_fresh_spool_does_not_warn(tmp_path: Path) -> None:
    """The warning must discriminate. A queue that is merely busy is not broken,
    and an assertion that fires on every send is one people learn to ignore."""
    spool = _spool(tmp_path)
    (spool / "recent.msg").write_text("dev_name: x\n\njust queued\n")
    proc = _forward(tmp_path, "second message")
    assert "WARNING" not in proc.stderr, proc.stderr


def test_an_unwritable_spool_fails_loudly(tmp_path: Path) -> None:
    """Never a silent success: if the message cannot be spooled at all, the
    provider must fail, not pretend."""
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0o500)
    try:
        proc = subprocess.run(
            ["bash", str(PROVIDER), "cannot write"],
            capture_output=True,
            text=True,
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(tmp_path),
                "OAW_VOX_SPOOL": str(blocked / "nested"),
                "VOX_OUTPUT_FILE": str(tmp_path / "o.wav"),
            },
            timeout=60,
        )
        assert proc.returncode != 0, proc.stdout + proc.stderr
        assert "NO voice" in proc.stderr
    finally:
        blocked.chmod(0o700)


def test_the_message_is_published_atomically(tmp_path: Path) -> None:
    """The host watcher fires on creation, so a half-written file would be spoken
    as a truncated sentence. Nothing may be left behind under a temp name."""
    _forward(tmp_path, "atomic")
    leftovers = [p.name for p in _spool(tmp_path).iterdir() if p.name.startswith(".tmp")]
    assert not leftovers, f"in-flight temp files left in the spool: {leftovers}"


# --- the host half ------------------------------------------------------------


# Real `vox` accepts `--` to end option parsing, and the drain passes it so a
# message starting with `-` is not read as an unknown option. A stub that does
# not consume it records "--" as the message — a test failure with nothing to do
# with the behaviour under test.
_STUB_PREAMBLE = '#!/usr/bin/env bash\n[ "$1" = "--" ] && shift\n'


def _drain(spool: Path, tmp_path: Path, vox_body: str, **env: str):
    fake_vox = tmp_path / "fake-vox"
    fake_vox.write_text(vox_body.replace("#!/usr/bin/env bash\n", _STUB_PREAMBLE, 1))
    fake_vox.chmod(0o755)
    return subprocess.run(
        ["bash", str(DRAIN)],
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp_path),
            "OAW_VOX_SPOOL_HOST": str(spool),
            "OAW_VOX_BIN": str(fake_vox),
            "SPOKEN_LOG": str(tmp_path / "spoken.log"),
            **env,
        },
        timeout=60,
    )


def test_the_drain_speaks_the_body_and_removes_the_file(tmp_path: Path) -> None:
    _forward(tmp_path, "speak me")
    spool = _spool(tmp_path)
    proc = _drain(
        spool, tmp_path, '#!/usr/bin/env bash\necho "SPOKE: $1" >> "$SPOKEN_LOG"\n'
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    spoken = (tmp_path / "spoken.log").read_text()
    assert "speak me" in spoken
    # The header is metadata for triage, not something to read aloud.
    assert "dev_name:" not in spoken
    assert not _messages(tmp_path), "the drain left the message in the spool"


def test_a_message_that_fails_to_speak_is_not_requeued(tmp_path: Path) -> None:
    """Delete-then-speak, deliberately. Re-queuing a message vox rejects makes a
    DirectoryNotEmpty path unit spin on it forever; heard-once-and-lost beats
    repeated-until-the-end-of-time."""
    _forward(tmp_path, "poison")
    spool = _spool(tmp_path)
    proc = _drain(spool, tmp_path, "#!/usr/bin/env bash\nexit 1\n")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not _messages(tmp_path), "a failed message was left to be retried forever"


def test_a_stale_backlog_is_dropped_not_spoken(tmp_path: Path) -> None:
    """Speaking twenty stale status updates at once is worse than dropping them."""
    _forward(tmp_path, "ancient news")
    spool = _spool(tmp_path)
    for m in _messages(tmp_path):
        old = time.time() - 100000
        os.utime(m, (old, old))
    proc = _drain(
        spool, tmp_path, '#!/usr/bin/env bash\necho "SPOKE: $1" >> "$SPOKEN_LOG"\n'
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not (tmp_path / "spoken.log").exists(), "a stale backlog was spoken aloud"
    assert "dropping" in proc.stderr


def test_concurrent_drains_speak_each_message_exactly_once(tmp_path: Path) -> None:
    """The glob is evaluated once per run, so two drains — the path unit's and an
    operator running it by hand, which the runbook tells them to do — can both
    enumerate the same file. Without an atomic claim they both speak it.

    `rm -f` does NOT prevent this: it succeeds for both. Renaming does, because
    `mv` fails once the source is gone.
    """
    spool = _spool(tmp_path)
    for i in range(40):
        (spool / f"m{i}.msg").write_text(f"dev_name: a\n\nmsg-{i}\n")

    fake_vox = tmp_path / "fv"
    fake_vox.write_text(_STUB_PREAMBLE + 'printf "%s\\n" "$1" >> "$SPOKEN_LOG"\n')
    fake_vox.chmod(0o755)
    log = tmp_path / "spoken.log"

    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "OAW_VOX_SPOOL_HOST": str(spool),
        "OAW_VOX_BIN": str(fake_vox),
        "SPOKEN_LOG": str(log),
    }
    procs = [
        subprocess.Popen(
            ["bash", str(DRAIN)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env
        )
        for _ in range(6)
    ]
    for p in procs:
        p.wait(timeout=120)

    spoken = [l for l in log.read_text().splitlines() if l.startswith("msg-")]
    assert len(spoken) == 40, f"expected 40 messages spoken, got {len(spoken)}"
    assert len(set(spoken)) == 40, (
        f"a message was spoken more than once: {sorted(x for x in spoken if spoken.count(x) > 1)[:5]}"
    )
    # NAME THE TWO KINDS OF LEFTOVER APART. An EMPTY directory left behind is not
    # undrained work — it is the #1142 residue: a drain that lost a claim race
    # created `.quarantine` for a file another drain had already taken. Reported
    # as a bare "not fully drained" it reads as a message-handling failure, which
    # is how #1142 came to be filed as a duplicate-announcement race when the two
    # assertions above — the ones this test is named for — had never once failed.
    leftover = sorted(spool.iterdir())
    empty = [p.name for p in leftover if p.is_dir() and not any(p.iterdir())]
    assert not leftover, (
        f"the spool was not fully drained: {[p.name for p in leftover]}"
        + (f" — {empty} left EMPTY, so this is claim-race residue, not undrained work" if empty else "")
    )


def test_the_drain_is_loud_when_vox_is_missing(tmp_path: Path) -> None:
    """Otherwise the host silently discards everything containers spool at it."""
    spool = _spool(tmp_path)
    (spool / "x.msg").write_text("dev_name: a\n\nhi\n")
    proc = subprocess.run(
        ["bash", str(DRAIN)],
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp_path),
            "OAW_VOX_SPOOL_HOST": str(spool),
            "OAW_VOX_BIN": str(tmp_path / "does-not-exist"),
        },
        timeout=60,
    )
    assert proc.returncode != 0
    assert "spooling into a void" in proc.stderr


def test_the_drain_suppresses_a_second_signoff(tmp_path: Path) -> None:
    """The container's vox ALREADY appended `. This is <agent>.` before handing
    the text to the forwarding provider. The host's vox would append another —
    and `resolve_speaker` never returns empty, so from a systemd unit with no
    agent identity anywhere it falls through to `pid N`. The operator would hear
    "…promoted. This is babelfish. This is pid 4711."
    """
    _forward(tmp_path, "wave 3 promoted. This is babelfish.")
    spool = _spool(tmp_path)
    proc = _drain(
        spool,
        tmp_path,
        '#!/usr/bin/env bash\necho "NO_SIGNOFF=${VOX_NO_SIGNOFF:-unset}" >> "$SPOKEN_LOG"\n',
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "NO_SIGNOFF=1" in (tmp_path / "spoken.log").read_text(), (
        "the drain let the host's vox append a second, bogus sign-off"
    )


def test_a_message_starting_with_a_dash_is_still_spoken(tmp_path: Path) -> None:
    """vox rejects unknown `-*` options with exit 1, so without `--` a message
    beginning with a dash is dropped rather than spoken.

    This stub REJECTS a leading dash exactly as vox does, and is built here
    rather than via `_drain` because that helper prepends its own `--`-consuming
    preamble — with both, the `--` is eaten twice and the test fails for the
    wrong reason. A stub that merely echoed $1 passed with `--` removed from the
    drain, which made the assertion decorative.
    """
    _forward(tmp_path, "-v is not a flag here")
    spool = _spool(tmp_path)

    fake_vox = tmp_path / "picky-vox"
    fake_vox.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "--" ]; then shift; '
        'elif [ "${1#-}" != "$1" ]; then echo "unknown option: $1" >&2; exit 1; fi\n'
        'printf "%s\\n" "$1" >> "$SPOKEN_LOG"\n'
    )
    fake_vox.chmod(0o755)

    proc = subprocess.run(
        ["bash", str(DRAIN)],
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp_path),
            "OAW_VOX_SPOOL_HOST": str(spool),
            "OAW_VOX_BIN": str(fake_vox),
            "SPOKEN_LOG": str(tmp_path / "spoken.log"),
        },
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    log = tmp_path / "spoken.log"
    assert log.exists(), (
        f"the message was rejected as an option instead of spoken: {proc.stderr}"
    )
    assert "is not a flag here" in log.read_text()


def test_the_drain_never_leaves_a_triggering_entry(tmp_path: Path) -> None:
    """THE LATCH. The path unit watches DirectoryNotEmpty, so anything left
    behind re-triggers the service immediately and forever; systemd's start
    limiter then refuses the job and fails the PATH unit too, which stops
    watching until someone runs `reset-failed`. Measured: one undrained file
    fired the service 5 times in 2 seconds.

    So no exit path may leave a visible entry — not a stray file, not a
    subdirectory, and not the no-vox bail-out.
    """
    spool = _spool(tmp_path)
    (spool / "stray.txt").write_text("not a message")
    (spool / "subdir").mkdir()
    (spool / "real.msg").write_text("dev_name: a\n\nhello\n")

    proc = subprocess.run(
        ["bash", str(DRAIN)],
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp_path),
            "OAW_VOX_SPOOL_HOST": str(spool),
            "OAW_VOX_BIN": str(tmp_path / "no-such-vox"),
        },
        timeout=60,
    )
    assert proc.returncode != 0, "a missing vox must still be reported"
    assert "spooling into a void" in proc.stderr

    visible = [p.name for p in spool.iterdir() if not p.name.startswith(".")]
    assert not visible, (
        f"entries left that will re-trigger the path unit forever: {visible}"
    )


def test_stray_entries_are_cleared_on_the_normal_path_too(tmp_path: Path) -> None:
    """The bail-out above is only one exit. With a WORKING vox the main loop must
    also leave nothing visible — otherwise a single stray file re-triggers the
    service forever on an otherwise healthy host, which is the same latch by a
    different door. Testing only the bail-out let that survive.
    """
    spool = _spool(tmp_path)
    (spool / "stray.txt").write_text("not a message")
    (spool / "subdir").mkdir()
    (spool / "real.msg").write_text("dev_name: a\n\nhello\n")

    proc = _drain(
        spool, tmp_path, '#!/usr/bin/env bash\necho "$1" >> "$SPOKEN_LOG"\n'
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "hello" in (tmp_path / "spoken.log").read_text()

    visible = [p.name for p in spool.iterdir() if not p.name.startswith(".")]
    assert not visible, (
        f"stray entries left in the watched set on the normal path: {visible}"
    )


def test_quarantined_entries_keep_their_original_names(tmp_path: Path) -> None:
    """Quarantine exists for triage, and triage needs to know WHAT failed.

    The drain claims every entry with a private `.claimed.$$.$RANDOM` rename before
    deciding anything about it (#1142) — that is what makes the decision race-free.
    But the undrainable ones are then quarantined from that claim, so without care
    the quarantine fills with `.claimed.4711.29103` and tells an operator nothing.
    """
    spool = _spool(tmp_path)
    (spool / "stray.txt").write_text("not a message")
    (spool / "subdir").mkdir()
    (spool / "real.msg").write_text("dev_name: a\n\nhello\n")

    proc = _drain(spool, tmp_path, '#!/usr/bin/env bash\necho "$1" >> "$SPOKEN_LOG"\n')
    assert proc.returncode == 0, proc.stdout + proc.stderr

    quarantined = sorted(p.name for p in (spool / ".quarantine").iterdir())
    assert quarantined == ["stray.txt", "subdir"], (
        f"quarantine should name what it holds, got {quarantined}"
    )


def _quarantine_shim(tmp_path: Path, spool: Path) -> Path:
    """Lift `quarantine()` out of the drain so it can be called directly.

    The concurrency test can only reach this function when a race actually lands,
    which is nondeterministic by nature — the #1142 window was a couple of syscalls
    wide and needed artificial widening to reproduce at all. Extracting the function
    and calling it on a chosen input turns "usually catches it" into "always".
    """
    src = DRAIN.read_text()
    m = re.search(r"^quarantine\(\) \{$.*?^\}$", src, re.S | re.M)
    assert m, "quarantine() not found in the drain — extraction pattern is stale"
    return_path = tmp_path / "shim.sh"
    return_path.write_text(
        "#!/usr/bin/env bash\nset -uo pipefail\n"
        f'QUARANTINE="{spool}/.quarantine"\n'
        f"{m.group(0)}\n"
        'quarantine "$@"\n'
    )
    return_path.chmod(0o755)
    return return_path


def test_quarantine_does_not_create_the_directory_for_a_vanished_entry(
    tmp_path: Path,
) -> None:
    """The #1142 invariant, asserted directly instead of waiting for a race.

    A drain that loses a claim used to call `quarantine()` on a path another drain
    had already taken. `mkdir -p` runs before the `mv`, so it created `.quarantine`
    and then failed to move anything into it — leaving an EMPTY directory that says
    "something failed to drain" in the one place an operator looks to ask that.
    """
    spool = _spool(tmp_path)
    shim = _quarantine_shim(tmp_path, spool)

    proc = subprocess.run(
        ["bash", str(shim), str(spool / "already-claimed-by-someone-else.msg")],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not (spool / ".quarantine").exists(), (
        "quarantine() created an empty .quarantine for an entry that was already gone"
    )


@pytest.mark.parametrize("vox_present", [True, False], ids=["normal", "no-vox"])
def test_a_dangling_symlink_is_quarantined_on_both_exits(
    tmp_path: Path, vox_present: bool
) -> None:
    """`-e` stats THROUGH a symlink, so a dangling one reads as absent while still
    being a visible directory entry — and a visible entry is what latches the path
    unit (see the header of the drain).

    Both exits must clear it, and they failed at different times: the bail-out via a
    guard that called the link absent, the normal path via a pre-claim `-e` test that
    skipped it outright. `mv` renames the LINK and never resolves it, so quarantining
    a dangling link works — only the tests guarding it were wrong.
    """
    spool = _spool(tmp_path)
    (spool / "dangling.msg").symlink_to(tmp_path / "nothing-here")
    (spool / "real.msg").write_text("dev_name: a\n\nhello\n")

    vox = tmp_path / "fake-vox"
    if vox_present:
        vox.write_text(_STUB_PREAMBLE + 'printf "%s\\n" "$1" >> "$SPOKEN_LOG"\n')
        vox.chmod(0o755)

    subprocess.run(
        ["bash", str(DRAIN)],
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp_path),
            "OAW_VOX_SPOOL_HOST": str(spool),
            "OAW_VOX_BIN": str(vox),
            "SPOKEN_LOG": str(tmp_path / "spoken.log"),
        },
        timeout=60,
    )

    visible = [p.name for p in spool.iterdir() if not p.name.startswith(".")]
    assert not visible, f"a visible entry was left behind, which latches the unit: {visible}"
    assert "dangling.msg" in [p.name for p in (spool / ".quarantine").iterdir()]


def test_the_service_disables_the_start_limiter() -> None:
    """Without this a burst of announcements trips DefaultStartLimitBurst=5 and
    systemd fails the PATH unit, silently ending the only channel that exists to
    be loud."""
    unit = (REPO / "scripts" / "vox-spool" / "systemd" / "oaw-vox-spool.service").read_text()
    assert "StartLimitIntervalSec=0" in unit
    # It must be in [Unit], not [Service] — systemd parses start rate limiting
    # from the unit section, and a [Service] placement is silently ignored.
    unit_section = unit.split("[Service]", 1)[0]
    assert "StartLimitIntervalSec=0" in unit_section, (
        "StartLimitIntervalSec must be in [Unit]; in [Service] it does nothing"
    )


def test_the_path_unit_carries_no_hardcoded_major() -> None:
    """`state/8/` baked into the unit is the #1067 defect: at the next major the
    container writes state/9 while this watches state/8, and agents go mute.
    scripts/ci/oaw-major.sh exists because two other scripts did exactly this."""
    unit = (REPO / "scripts" / "vox-spool" / "systemd" / "oaw-vox-spool.path").read_text()
    assert "@SPOOL@" in unit, "the spool path must be templated at install time"
    # Comments stripped: the comment EXPLAINING why `state/8/` is wrong contains
    # the literal, so an unstripped scan fails on its own prose. Fifth time that
    # shape has appeared in this repo.
    directives = "\n".join(
        l for l in unit.splitlines() if not l.lstrip().startswith("#")
    )
    assert not re.search(r"state/\d+/", directives), (
        f"hardcoded major in the path unit: {directives}"
    )


def test_the_drain_refuses_rather_than_guessing_a_major(tmp_path: Path) -> None:
    """No literal fallback — `OAW_MAJOR="${OAW_MAJOR:-1}"` is the #1067 defect
    verbatim, and oaw-major.sh's own comment says guessing silently is worse than
    refusing. With no spool to infer from, refuse."""
    proc = subprocess.run(
        ["bash", str(DRAIN), "--status"],
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)},
        timeout=60,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "set OAW_MAJOR" in proc.stderr


def test_the_drain_infers_the_major_from_the_one_spool_present(tmp_path: Path) -> None:
    (tmp_path / ".oaw" / "state" / "11" / "vox-spool").mkdir(parents=True)
    proc = subprocess.run(
        ["bash", str(DRAIN), "--status"],
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)},
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "state/11/vox-spool" in proc.stdout


def test_an_ambiguous_major_refuses_rather_than_picking_one(tmp_path: Path) -> None:
    for major in ("8", "9"):
        (tmp_path / ".oaw" / "state" / major / "vox-spool").mkdir(parents=True)
    proc = subprocess.run(
        ["bash", str(DRAIN), "--status"],
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)},
        timeout=60,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "several spools" in proc.stderr


def test_the_default_spool_matches_the_declared_mount_target(tmp_path: Path) -> None:
    """The provider's fallback and the mount's target are two independent
    constants that must agree. Nothing consumes manifest `env`, so if they ever
    diverge the container writes somewhere the host never sees — and every test
    that sets OAW_VOX_SPOOL explicitly stays green while it happens.
    """
    target = re.search(r'target = "([^"]+)"', FRAGMENT.read_text()).group(1)
    body = PROVIDER.read_text()
    default = re.search(r'SPOOL="\$\{OAW_VOX_SPOOL:-([^}]+)\}"', body).group(1)
    assert default.replace("$HOME", "/home/ubuntu") == target, (
        f"provider default {default!r} does not match the mount target {target!r}"
    )

    # And the image must actually export it, so the declared env is not inert.
    directives = "\n".join(
        line
        for line in DOCKERFILE.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    assert f"ENV OAW_VOX_SPOOL={target}" in directives


def test_the_provider_uses_its_default_when_the_env_is_unset(tmp_path: Path) -> None:
    """Exercises the path production actually takes. Every other test sets
    OAW_VOX_SPOOL, so the default was never run — the classic
    declared-but-unexercised shape."""
    proc = subprocess.run(
        ["bash", str(PROVIDER), "using the default"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp_path),
            "VOX_OUTPUT_FILE": str(tmp_path / "o.wav"),
        },
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    landed = list((tmp_path / ".oaw" / "vox-spool").glob("*.msg"))
    assert len(landed) == 1, f"the default spool path was not used: {proc.stderr}"


# --- wiring -------------------------------------------------------------------


def test_spool_dir_is_an_existing_mounted_path() -> None:
    """The spool must be a declared mount, or the container writes somewhere the
    host never sees and the whole path is silently one-way."""
    text = FRAGMENT.read_text()
    assert 'source = "~/.oaw/state/<major>/vox-spool"' in text
    assert 'target = "/home/ubuntu/.oaw/vox-spool"' in text
    assert 'mode = "rw"' in text
    # R-03: sandbox-scoped under ~/.oaw/state/<major>/, never the live-fleet tree.
    assert "~/.claude" not in text.split("[[mount]]", 1)[1]


def test_the_image_wires_the_provider_and_the_player() -> None:
    """Both halves, or neither works: the provider forwards text and the player
    is a no-op because playback happens on the host. Comments stripped so the
    prose explaining this cannot satisfy the assertion."""
    directives = "\n".join(
        line
        for line in DOCKERFILE.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    assert "vox-providers/host-forward.sh" in directives
    assert "vox-spool/no-op-player.sh" in directives
    assert ".config/vox/provider" in directives
    assert ".config/vox/player" in directives


def test_the_image_does_not_wire_silent_sh() -> None:
    """#1084 refused this explicitly: pointing the provider at silent.sh also
    stops the error, by making the agent mute and believing it spoke. That turns
    a visible gap into an invisible one."""
    directives = "\n".join(
        line
        for line in DOCKERFILE.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    assert "silent.sh" not in directives


@pytest.mark.parametrize("script", [PROVIDER, PLAYER, DRAIN])
def test_scripts_are_executable(script: Path) -> None:
    assert os.access(script, os.X_OK), f"{script} must be executable"


def test_install_carries_the_units_where_the_operator_step_looks() -> None:
    """`--install-units` reads from ~/.claude/scripts/vox-spool/systemd, which is
    where `./install`'s Cellar deploy puts scripts/vox-spool/systemd. If the
    installer stopped carrying them the operator step would fail with "no units",
    and the host side would quietly never exist.

    The installer's rule is "every file under scripts/, except ci/ and the
    excluded names". This checks each file against THAT rule rather than
    re-running find — an earlier version shelled out to a bogus
    `source ./install --source-only`, which failed silently and made the
    assertion fire on an empty list.
    """
    install_src = (REPO / "install").read_text()
    excluded = re.findall(r'SCRIPTS_EXCLUDE_NAMES=\(([^)]*)\)', install_src)
    excluded_names = set(re.findall(r'"([^"]+)"', excluded[0])) if excluded else set()

    for rel in (
        "oaw-vox-drain",
        "vox-providers/host-forward.sh",
        "vox-spool/no-op-player.sh",
        "vox-spool/systemd/oaw-vox-spool.path",
        "vox-spool/systemd/oaw-vox-spool.service",
    ):
        assert (REPO / "scripts" / rel).is_file(), f"{rel} is missing from scripts/"
        assert not rel.startswith("ci/"), f"{rel} sits in the excluded ci/ tree"
        parts = set(Path(rel).parts[:-1])
        assert not (parts & excluded_names), (
            f"{rel} is under an excluded dir {parts & excluded_names} and would not install"
        )


def test_the_units_reference_the_installed_drain_path() -> None:
    """ExecStart must point at where install actually puts the drain. A unit
    naming a path the installer never creates fails only at trigger time — i.e.
    the first time an agent tries to speak, which is the worst moment to find
    out."""
    service = (REPO / "scripts" / "vox-spool" / "systemd" / "oaw-vox-spool.service").read_text()
    assert "ExecStart=%h/.local/bin/oaw-vox-drain" in service

    path_unit = (REPO / "scripts" / "vox-spool" / "systemd" / "oaw-vox-spool.path").read_text()
    # DirectoryNotEmpty, not PathChanged: PathChanged fires on the event, so a
    # message spooled while the service was already running for a previous one is
    # missed and ages into the provider's staleness warning.
    assert "DirectoryNotEmpty=" in path_unit
    assert "vox-spool" in path_unit
