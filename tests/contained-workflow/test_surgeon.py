"""Oracle for Story 3.1 (#970) — the flight surgeon health probe (R-15/R-16/R-22).

The surgeon (``scripts/flight-surgeon/surgeon.py``) is a **host-side** probe that
reads each ``:edge`` container's host-backed ``.jsonl`` transcript directly and
classifies it broken (stall or loop) while correlating with aoe status, filtering
dev-mode out of quarantine. All three acceptance criteria are proved here as pure
unit oracles (no docker, no aoe, no live container), so they run for real in the
stock ``pytest tests/`` lane:

* **AC1 [R-15]** — the probe detects a stall by reading the transcript **directly**,
  without the container's kit. :func:`test_probe_reads_transcript_directly` writes a
  real ``.jsonl`` to disk and the surgeon reads+classifies it with nothing from any
  container; :func:`test_module_is_kit_independent` proves the module imports only
  the standard library.
* **AC2 [R-16]** — ``running`` + flat-for-N-min AND loop signals both classify
  broken. The named story oracle :func:`test_stall_and_loop` drives flat and
  repetitive transcripts; :func:`test_status_gate` proves both signals fire ONLY
  while running.
* **AC3 [R-22]** — dev-mode containers are excluded from quarantine.
  :func:`test_dev_mode_excluded_from_quarantine`.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SURGEON_DIR = REPO_ROOT / "scripts" / "flight-surgeon"
SURGEON_PY = SURGEON_DIR / "surgeon.py"

# Path-style import (no PYTHONPATH dependency), mirroring test_gate.py.
sys.path.insert(0, str(SURGEON_DIR))
import surgeon as fs  # noqa: E402

NOW = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)


# --- transcript fixtures ------------------------------------------------------


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def tool_entry(ts: datetime, name: str, tool_input: dict) -> dict:
    """A Claude Code assistant transcript entry carrying one tool_use block."""
    return {
        "type": "assistant",
        "timestamp": _iso(ts),
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": name, "input": tool_input}],
        },
    }


def text_entry(ts: datetime, text: str) -> dict:
    return {
        "type": "assistant",
        "timestamp": _iso(ts),
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def flat_transcript(last_seconds_ago: float, anchor: datetime = NOW) -> list[dict]:
    """A progressing-then-quiet transcript whose LAST activity is N seconds before
    ``anchor`` (the reference "now")."""
    base = anchor - timedelta(seconds=last_seconds_ago)
    return [
        text_entry(base - timedelta(minutes=5), "starting work"),
        tool_entry(base - timedelta(minutes=3), "Read", {"path": "/a"}),
        tool_entry(base, "Bash", {"cmd": "make test"}),
    ]


def looping_transcript(reps: int, seconds_ago: float = 30.0, anchor: datetime = NOW) -> list[dict]:
    """A RECENT but repetitive transcript: the same tool call ``reps`` times, so it
    is not stalled (fresh) yet shows no forward progress (loop)."""
    base = anchor - timedelta(seconds=seconds_ago)
    entries = [text_entry(base - timedelta(minutes=2), "working")]
    for i in range(reps):
        entries.append(
            tool_entry(base + timedelta(seconds=i), "Bash", {"cmd": "git status"})
        )
    return entries


# --- AC2 [R-16]: the named story oracle — stall AND loop both classify broken -


def test_stall_and_loop() -> None:
    """``running`` + flat-for-N-min and loop signals BOTH classify broken (R-16),
    and neither fires on a fresh, progressing transcript.
    """
    # 1. STALL: running + last activity 20 min ago (> 15 min threshold) → broken.
    stalled = fs.classify_health(
        entries=flat_transcript(last_seconds_ago=20 * 60), status="running", now=NOW
    )
    assert stalled.broken and stalled.stalled and not stalled.looping
    assert stalled.state == fs.STALLED

    # 2. NOT stalled: running + fresh activity (1 min ago) → healthy.
    fresh = fs.classify_health(
        entries=flat_transcript(last_seconds_ago=60), status="running", now=NOW
    )
    assert not fresh.broken and fresh.state == fs.HEALTHY

    # 3. LOOP: running + fresh but the same tool 6× → broken via loop, NOT stall.
    looping = fs.classify_health(
        entries=looping_transcript(reps=6), status="running", now=NOW
    )
    assert looping.broken and looping.looping and not looping.stalled
    assert looping.state == fs.LOOPING

    # 4. NOT looping: running + fresh, varied tool calls → healthy.
    varied = [
        tool_entry(NOW - timedelta(seconds=90), "Read", {"path": "/a"}),
        tool_entry(NOW - timedelta(seconds=60), "Bash", {"cmd": "ls"}),
        tool_entry(NOW - timedelta(seconds=30), "Edit", {"path": "/b"}),
        tool_entry(NOW - timedelta(seconds=10), "Bash", {"cmd": "make"}),
    ]
    healthy = fs.classify_health(entries=varied, status="running", now=NOW)
    assert not healthy.broken and healthy.state == fs.HEALTHY


def test_status_gate() -> None:
    """Both break signals are gated on ``running`` (R-16): the identical flat /
    repetitive transcript is NOT a break while idle / waiting / stopped."""
    for non_running in ("idle", "waiting", "stopped", "error", "unknown"):
        stall_shape = fs.classify_health(
            entries=flat_transcript(last_seconds_ago=60 * 60),
            status=non_running,
            now=NOW,
        )
        assert not stall_shape.broken, f"flat while {non_running} must not be a break"

        loop_shape = fs.classify_health(
            entries=looping_transcript(reps=10), status=non_running, now=NOW
        )
        assert not loop_shape.broken, f"repetitive while {non_running} must not break"


def test_stall_threshold_boundary() -> None:
    """The stall fires at/after the threshold, not before."""
    under = fs.classify_health(
        entries=flat_transcript(last_seconds_ago=14 * 60), status="running", now=NOW
    )
    assert not under.stalled
    over = fs.classify_health(
        entries=flat_transcript(last_seconds_ago=16 * 60), status="running", now=NOW
    )
    assert over.stalled and over.broken


def test_just_launched_running_is_not_stalled() -> None:
    """A running container with no timestamped activity yet must NOT read as a
    stall (fail-safe toward not false-quarantining a just-launched agent)."""
    v = fs.classify_health(entries=[], status="running", now=NOW)
    assert not v.broken and not v.stalled


# --- loop detector shapes (conservative) --------------------------------------


def test_loop_detection_shapes() -> None:
    same = [f"Bash:{json.dumps({'cmd': 'git status'})}"] * 5
    assert fs.detect_loop(same, min_repeats=5).looping

    just_under = same[:4]
    assert not fs.detect_loop(just_under, min_repeats=5).looping

    # A period-2 ping-pong repeated ≥ min_repeats at the tail.
    pingpong = ["A:{}", "B:{}"] * 3
    assert fs.detect_loop(pingpong, min_repeats=3, max_period=4).looping

    # A loop that has since resolved (forward progress at the tail) → NOT looping.
    resolved = (["A:{}"] * 6) + ["B:{}", "C:{}"]
    assert not fs.detect_loop(resolved, min_repeats=5).looping

    # Varied, progressing sequence → never a loop.
    varied = ["A:{}", "B:{}", "C:{}", "D:{}", "E:{}"]
    assert not fs.detect_loop(varied, min_repeats=3, max_period=4).looping


# --- AC1 [R-15]: reads the transcript directly, kit-independently --------------


def test_probe_reads_transcript_directly(tmp_path) -> None:
    """The probe detects a stall by reading a real ``.jsonl`` off disk directly —
    nothing from any container, no kit (R-15)."""
    transcript = tmp_path / "session.jsonl"
    lines = flat_transcript(last_seconds_ago=30 * 60)
    transcript.write_text("\n".join(json.dumps(e) for e in lines) + "\n")

    entries = fs.read_transcript(transcript)
    assert len(entries) == len(lines)
    verdict = fs.classify_health(entries=entries, status="running", now=NOW)
    assert verdict.broken and verdict.stalled


def test_read_transcript_tolerates_a_truncated_tail(tmp_path) -> None:
    """A hard-killed agent may leave a truncated last line; the probe must skip it,
    not crash (fate-independence, R-15)."""
    transcript = tmp_path / "session.jsonl"
    good = json.dumps(tool_entry(NOW - timedelta(minutes=40), "Bash", {"cmd": "x"}))
    transcript.write_text(good + "\n" + '{"type":"assistant","truncat')  # no newline
    entries = fs.read_transcript(transcript)
    assert len(entries) == 1  # the good line survives, the torn one is dropped
    assert fs.read_transcript(tmp_path / "nope.jsonl") == []  # missing file → []


def test_module_is_kit_independent() -> None:
    """R-15: the surgeon depends on nothing from the container's kit — the module
    imports ONLY the Python standard library, so a broken container cannot shape
    the verdict."""
    tree = ast.parse(SURGEON_PY.read_text())
    # An enumeration of the stdlib modules this file uses — NOT a policy
    # narrowing. R-15's guarantee is "nothing from the container's KIT", so a
    # genuinely-stdlib addition (os, for $OAW_MAJOR) preserves it exactly.
    # Anything outside the standard library still fails, which is the point.
    stdlib = {
        "argparse", "json", "os", "subprocess", "sys", "dataclasses",
        "datetime", "pathlib", "__future__",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    leaked = imported - stdlib
    assert not leaked, f"surgeon imports non-stdlib modules (kit dependency risk): {leaked}"


# --- AC3 [R-22]: dev-mode excluded from quarantine ----------------------------


def _broken_running():
    return dict(status="running", entries=flat_transcript(last_seconds_ago=30 * 60))


def test_dev_mode_excluded_from_quarantine() -> None:
    """A broken dev-mode container is reported broken but NEVER quarantined (R-22);
    a broken dogfood (or unlabeled) candidate IS quarantine-eligible."""
    dev = fs.assess(container_id="c1", title="devbox", profile="dev-mode",
                    now=NOW, **_broken_running())
    assert dev.health.broken, "the break is still classified/visible"
    assert not dev.quarantine_eligible
    assert not dev.should_quarantine, "dev-mode must not trip quarantine (R-22)"
    assert any("R-22" in r for r in dev.reasons)

    dog = fs.assess(container_id="c2", title="dogbox", profile="dogfood",
                    now=NOW, **_broken_running())
    assert dog.health.broken and dog.quarantine_eligible and dog.should_quarantine

    # Unlabeled / unknown profile is treated as a candidate — eligible, so a broken
    # one cannot escape the probe by lacking a label.
    for prof in (None, "", "weird"):
        unk = fs.assess(container_id="c3", title="unlabeled", profile=prof,
                        now=NOW, **_broken_running())
        assert unk.quarantine_eligible and unk.should_quarantine

    # A HEALTHY dogfood container is never quarantined.
    ok = fs.assess(container_id="c4", title="healthy", profile="dogfood", status="running",
                   entries=flat_transcript(last_seconds_ago=30), now=NOW)
    assert not ok.health.broken and not ok.should_quarantine


def test_profile_and_status_normalization() -> None:
    assert fs.normalize_profile("DEV-MODE") == fs.DEV_MODE
    assert fs.normalize_profile("Dogfood") == fs.DOGFOOD
    assert fs.normalize_profile(None) == fs.PROFILE_UNKNOWN
    assert fs.quarantine_eligible("dev") is False
    assert fs.quarantine_eligible("dogfood") is True
    assert fs.normalize_status("RUNNING") == fs.RUNNING
    assert fs.normalize_status("bogus") == fs.STATUS_UNKNOWN


# --- aoe status-table parser (the live-gather seam, unit-tested) --------------


def test_parse_status_table() -> None:
    sample = (
        "RUNNING (1):\n"
        "  ⠋ babelfish        claude     ~/sandbox/github/claudecode-workflow\n"
        "\n"
        "IDLE (2):\n"
        "  ⠒ cerberus         claude     ~/sysadmin\n"
        "  ⠒ moho             claude     ~/sandbox/x\n"
        "\n"
        "STOPPED (1):\n"
        "  ⠒ cacophonix       claude     ~/sandbox/github/scream-hole\n"
    )
    states = fs.parse_status_table(sample)
    assert states["babelfish"] == "running"
    assert states["cerberus"] == "idle"
    assert states["moho"] == "idle"
    assert states["cacophonix"] == "stopped"


# --- CLI: the report surface --------------------------------------------------


def _run_cli(*args, stdin=None):
    return subprocess.run(
        [sys.executable, str(SURGEON_PY), *args],
        capture_output=True, text=True, timeout=30, input=stdin,
    )


def test_cli_observations_report(tmp_path) -> None:
    """End-to-end through the CLI: a manifest of observations yields a JSON report
    with the right per-container verdicts, and --fail-on-quarantine signals.

    The CLI classifies against the real wall clock, so fixtures here anchor to
    ``datetime.now`` (not the fixed NOW the pure-function tests use)."""
    real_now = datetime.now(timezone.utc)
    transcript = tmp_path / "dog.jsonl"
    transcript.write_text(
        "\n".join(
            json.dumps(e) for e in flat_transcript(last_seconds_ago=30 * 60, anchor=real_now)
        )
        + "\n"
    )
    manifest = [
        # broken dogfood, read from a real host-backed transcript file (R-15)
        {"container_id": "d1", "title": "dog", "status": "running",
         "profile": "dogfood", "transcript": str(transcript)},
        # broken dev-mode (inline entries) → excluded from quarantine (R-22)
        {"container_id": "v1", "title": "dev", "status": "running",
         "profile": "dev-mode",
         "entries": flat_transcript(last_seconds_ago=30 * 60, anchor=real_now)},
        # healthy dogfood
        {"container_id": "h1", "title": "ok", "status": "running",
         "profile": "dogfood",
         "entries": flat_transcript(last_seconds_ago=30, anchor=real_now)},
    ]
    obs = tmp_path / "obs.json"
    obs.write_text(json.dumps(manifest))

    proc = _run_cli("--observations", str(obs), "--fail-on-quarantine")
    assert proc.returncode == 3, proc.stderr  # one quarantine-eligible break (the dog)
    report = {a["container_id"]: a for a in json.loads(proc.stdout)}
    assert report["d1"]["should_quarantine"] is True
    assert report["v1"]["health"]["broken"] is True
    assert report["v1"]["should_quarantine"] is False  # dev-mode excluded
    assert report["h1"]["health"]["broken"] is False

    # Without --fail-on-quarantine the probe reports and exits 0.
    ok = _run_cli("--observations", str(obs))
    assert ok.returncode == 0, ok.stderr


def test_cli_reads_manifest_from_stdin() -> None:
    manifest = [{"container_id": "s1", "title": "s", "status": "idle",
                 "profile": "dogfood", "entries": []}]
    proc = _run_cli("--observations", "-", stdin=json.dumps(manifest))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)[0]["container_id"] == "s1"


def test_surgeon_is_executable() -> None:
    """A watcher/cron invokes the probe directly, so it must be executable with a
    shebang."""
    import os

    assert SURGEON_PY.exists()
    assert os.access(SURGEON_PY, os.X_OK), "surgeon.py must be executable"
    assert SURGEON_PY.read_text().startswith("#!"), "surgeon.py needs a shebang"


# --- transcripts-root provenance (#1064) --------------------------------------
#
# The seam these cover produced a CONFIDENT WRONG ANSWER, not a miss. Measured on
# the development host 2026-07-30: with --transcripts-root ~/.claude/projects, a
# container on the cc-workflow workspace resolved to the live NATIVE session's
# transcript (19s stale). Wrong in both directions — healthy while natives run,
# stalled the moment the big-bang cut-over stops them.


def test_fleet_transcripts_root_is_refused() -> None:
    """A root inside ~/.claude is the fleet's store, not a sandbox's."""
    with pytest.raises(fs.FleetTranscriptRootError) as exc:
        fs.assert_sandbox_transcripts_root(Path.home() / ".claude" / "projects")
    msg = str(exc.value)
    assert "live-fleet" in msg, "the refusal must say WHY, not just refuse"
    assert "--allow-fleet-transcripts" in msg, "it must name the escape hatch"


def test_fleet_transcripts_root_allowed_with_explicit_flag() -> None:
    """Watching the fleet itself is legitimate — but must be asked for."""
    fs.assert_sandbox_transcripts_root(
        Path.home() / ".claude" / "projects", allow_fleet=True
    )


def test_sandbox_transcripts_root_is_accepted() -> None:
    """The host-backed sandbox root (and a major-specific path under it) pass."""
    fs.assert_sandbox_transcripts_root(Path.home() / ".oaw" / "state")
    fs.assert_sandbox_transcripts_root(
        Path.home() / ".oaw" / "state" / "7" / "transcripts"
    )


def test_default_transcripts_root_is_not_the_fleet_tree() -> None:
    """The DEFAULT must be safe with no flags — the bare `--live` invocation in
    this module's own docstring must not resolve fleet transcripts."""
    fs.assert_sandbox_transcripts_root(
        Path(fs.DEFAULT_TRANSCRIPTS_ROOT).expanduser()
    )


def test_gather_live_refuses_a_fleet_root(tmp_path) -> None:
    """The guard is wired into the live path, not merely available.

    A guard that exists but is never called is the defect this whole issue is
    about, so assert the call site rather than the function.
    """
    class _Args:
        transcripts_root = str(Path.home() / ".claude" / "projects")
        allow_fleet_transcripts = False

    with pytest.raises(fs.FleetTranscriptRootError):
        fs._gather_live(_Args(), runner=lambda *a, **k: "")


def test_refused_root_exits_2_without_a_traceback() -> None:
    """The refusal must reach the operator as a MESSAGE, not a stack trace.

    FleetTranscriptRootError began life as a bare RuntimeError, which is in none
    of main()'s except branches — so the carefully-worded refusal arrived as the
    tail of a traceback and the exit code was 1, breaking the documented contract
    (0 normal / 2 usage / 3 quarantine). The in-process tests could not see this
    because they never cross the CLI boundary.
    """
    proc = subprocess.run(
        [sys.executable, str(SURGEON_PY), "--live",
         "--transcripts-root", str(Path.home() / ".claude" / "projects")],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2, (
        f"a refused root is a usage error (exit 2), got {proc.returncode}"
    )
    assert "Traceback" not in proc.stderr, (
        "the refusal must be a message, not a stack trace:\n" + proc.stderr
    )
    assert "live-fleet" in proc.stderr


# --- container workspace slug (#1075) ------------------------------------------
#
# Found by MV-05, the first cut-over step that launches a container. aoe mounts a
# workspace at /workspace/<name>, NOT at its host path — measured from a live
# container: `docker inspect` gave `/tmp/mv05-ws -> /workspace/mv05-ws` with
# WorkingDir `/workspace/mv05-ws`, and the agent's own /proc/<pid>/cwd agreed.
# Claude Code derives its transcript dir from cwd, so the agent writes under
# `-workspace-mv05-ws` while `aoe list` reports the HOST path. Slugging the host
# path could never match, so NO containerised session resolved — every container
# read healthy, quarantine never fired, and soak accrued unmeasured.


def test_container_workspace_path_derivation() -> None:
    assert fs.container_workspace_path("/tmp/mv05-ws") == "/workspace/mv05-ws"
    assert fs.container_workspace_path("/home/bakerb/sandbox/github/x") == "/workspace/x"
    assert fs.container_workspace_path("/tmp/trailing/") == "/workspace/trailing"


def test_resolves_the_container_written_slug(tmp_path) -> None:
    """The transcript is written INSIDE the container, so the lookup must slug the
    container path even though aoe reports the host one."""
    d = tmp_path / "-workspace-mv05-ws"
    d.mkdir()
    (d / "96304b8d-c729-4fd1-b971-90176cb53cf5.jsonl").write_text("{}\n")
    got = fs._newest_transcript_for(tmp_path, "/tmp/mv05-ws")
    assert got is not None, "a containerised session's transcript must resolve"
    assert got.parent.name == "-workspace-mv05-ws"


def test_host_slug_alone_does_not_resolve(tmp_path) -> None:
    """Regression guard for the pre-#1075 behaviour: a transcript sitting under the
    HOST-path slug must NOT satisfy the lookup, or the bug is back."""
    d = tmp_path / "-tmp-mv05-ws"
    d.mkdir()
    (d / "s.jsonl").write_text("{}\n")
    assert fs._newest_transcript_for(tmp_path, "/tmp/mv05-ws") is None


def test_unresolved_transcript_is_visible_in_the_json_report() -> None:
    """The promotion gate reads the JSON, not the stderr warning — so 'never
    measured' has to travel with the verdict. Note broken stays False: an
    unresolved transcript is not evidence of a break, which is exactly why it
    would otherwise read as health."""
    a = fs.assess_record(
        {"container_id": "c1", "title": "t", "status": "running",
         "profile": "dogfood", "entries": [], "transcript_resolved": False}
    )
    d = a.as_dict()
    assert d["transcript_resolved"] is False
    assert d["health"]["broken"] is False


def test_observation_files_default_to_resolved() -> None:
    """Hand-authored observations supply entries directly, so the pre-#1075
    contract must be unchanged for them."""
    a = fs.assess_record(
        {"container_id": "c2", "title": "t", "status": "running",
         "profile": "dogfood", "entries": []}
    )
    assert a.as_dict()["transcript_resolved"] is True


def test_fleet_mode_resolves_native_host_slug(tmp_path) -> None:
    """--allow-fleet-transcripts watches NATIVE sessions, whose cwd IS the host
    path. Converting to /workspace/<name> there matches nothing and reports every
    fleet session unmeasured — and fleet mode is the PRE-cut-over configuration,
    the one usable today. #1075's fix silently killed it until this test."""
    d = tmp_path / "-home-bakerb-sandbox-github-claudecode-workflow"
    d.mkdir()
    (d / "s.jsonl").write_text("{}\n")
    host = "/home/bakerb/sandbox/github/claudecode-workflow"
    assert fs._newest_transcript_for(tmp_path, host, allow_fleet=True) is not None
    # …and without the flag the container derivation still applies.
    assert fs._newest_transcript_for(tmp_path, host) is None


def test_prefix_collision_does_not_match(tmp_path) -> None:
    """Exact parent-dir match, not substring. `-workspace-app-2` must not satisfy
    a lookup for `app`, or a wedged agent inherits a neighbour's transcript."""
    d = tmp_path / "-workspace-app-2"
    d.mkdir()
    (d / "s.jsonl").write_text("{}\n")
    assert fs._newest_transcript_for(tmp_path, "/x/app") is None


def test_degenerate_path_is_unresolved_not_wildcard(tmp_path) -> None:
    """An empty slug would disable filtering and return the newest .jsonl anywhere,
    reported as RESOLVED — the confident-wrong-verdict this issue removes."""
    d = tmp_path / "-workspace-anything"
    d.mkdir()
    (d / "s.jsonl").write_text("{}\n")
    for degenerate in ("/", ".", ""):
        assert fs._newest_transcript_for(tmp_path, degenerate) is None, degenerate
    assert fs.container_workspace_path("/") == ""
