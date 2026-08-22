"""S1.1 / #863 — emit() + durable buffer + fire-and-forget shipper + replay.

Covers R-01 (durable atomic append), R-02 (non-blocking POST when URL set),
R-03 (ingest-down never raises, buffer-only when URL unset), R-04 (ordered
replay via offset marker), and the emit CLI surface used by S1.6/S1.7.

Stdlib-only mock ingest (http.server) — no third-party HTTP fixture.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from wave_status.events import emit as emit_mod
from wave_status.events.emit import buffer_path, emit, ship


# ---------------------------------------------------------------------------
# Mock ingest server (stdlib)
# ---------------------------------------------------------------------------

class _CaptureServer:
    """A tiny HTTP server capturing POSTed bodies + auth headers.

    ``received`` holds ``(path, body_dict_or_str, auth_header)`` tuples in
    arrival order. ``status`` is the code it returns (default 202).
    """

    def __init__(self, status: int = 202, port: int = 0):
        self.received: list[tuple] = []
        self.status = status
        captured = self.received
        status_code = self.status

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length).decode("utf-8") if length else ""
                try:
                    body = json.loads(raw)
                except Exception:
                    body = raw
                captured.append((self.path, body, self.headers.get("Authorization")))
                self.send_response(status_code)
                self.end_headers()

        self._server = HTTPServer(("127.0.0.1", port), Handler)
        self.port = self._server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/ingest"
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        try:
            self._server.shutdown()
        finally:
            self._server.server_close()

    def wait_for(self, n: int, timeout: float = 3.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if len(self.received) >= n:
                return True
            time.sleep(0.02)
        return False


@pytest.fixture()
def buf(tmp_path, monkeypatch) -> Path:
    """A dedicated buffer file for the shipper tests (URL still unset here)."""
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("FLIGHTDECK_EVENTS_PATH", str(path))
    monkeypatch.delenv("FLIGHTDECK_INGEST_URL", raising=False)
    return path


# ---------------------------------------------------------------------------
# R-01 — durable atomic append
# ---------------------------------------------------------------------------

class TestBufferAppend:
    def test_emit_atomic_append_writes_one_jsonl_line(self, buf):
        ev = emit("step", activity_id="camp-1", wave="wave-1", label="planning")
        assert ev is not None
        lines = buf.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        got = json.loads(lines[0])
        assert got["kind"] == "step"
        assert got["activityId"] == "camp-1"
        assert got["wave"] == "wave-1"
        assert got["ts"]

    def test_multiple_emits_append(self, buf):
        emit("step", activity_id="c", wave="w")
        emit("phase", activity_id="c", wave="w")
        emit("activity_end", activity_id="c")
        lines = buf.read_text(encoding="utf-8").splitlines()
        assert [json.loads(x)["kind"] for x in lines] == ["step", "phase", "activity_end"]

    def test_none_scope_tags_absent_not_null(self, buf):
        emit("step", activity_id="c")  # no wave/phase/etc
        got = json.loads(buf.read_text(encoding="utf-8").splitlines()[0])
        assert "wave" not in got and "phase" not in got

    def test_metric_value_none_preserved(self, buf):
        emit("metric", activity_id="c", metric="tokens", value=None)  # #853 stub
        got = json.loads(buf.read_text(encoding="utf-8").splitlines()[0])
        assert got["metric"] == "tokens"
        assert got["value"] is None


# ---------------------------------------------------------------------------
# R-03 — never raise; buffer-only when URL unset
# ---------------------------------------------------------------------------

class TestNeverRaises:
    def test_buffer_only_when_url_unset(self, buf):
        ev = emit("step", activity_id="c")
        assert ev is not None
        assert ship(buf) == 0  # no URL ⇒ shipper no-ops (DI-seam)
        assert buf.exists()

    def test_invalid_event_returns_none_no_raise(self, buf):
        assert emit("not-a-kind", activity_id="c") is None
        # nothing buffered
        assert not buf.exists() or buf.read_text() == ""

    def test_concern_missing_fields_returns_none(self, buf):
        assert emit("concern", activity_id="c") is None  # concernKind/source missing

    def test_disabled_switch_noops(self, buf, monkeypatch):
        monkeypatch.setenv("FLIGHTDECK_EMIT_DISABLED", "1")
        assert emit("step", activity_id="c") is None
        assert not buf.exists()

    def test_emit_state_event_never_raises(self, buf):
        # Bad kind, but the wrapper still must not raise.
        assert emit_mod.emit_state_event("/some/root", "bogus-kind") is None


# ---------------------------------------------------------------------------
# R-02 / IT-09 — non-blocking POST when URL set
# ---------------------------------------------------------------------------

class TestNonBlockingShip:
    def test_post_nonblocking_when_url_set(self, buf, monkeypatch):
        server = _CaptureServer().start()
        try:
            monkeypatch.setenv("FLIGHTDECK_INGEST_URL", server.url)
            monkeypatch.setenv("FLIGHTDECK_INGEST_TOKEN", "sekret")
            ev = emit("step", activity_id="camp-1", wave="w")  # ship_now default
            assert ev is not None  # returns immediately, does not block on POST
            assert server.wait_for(1), "event was not POSTed"
            path, body, auth = server.received[0]
            assert path == "/ingest"
            assert body["kind"] == "step"
            assert auth == "Bearer sekret"
        finally:
            server.stop()


# ---------------------------------------------------------------------------
# R-04 — ordered replay via offset marker + resilience
# ---------------------------------------------------------------------------

class TestReplayAndResilience:
    def test_replay_resends_unsent_in_order(self, buf, monkeypatch):
        # Buffer two events with the URL unset (no auto-ship).
        emit("step", activity_id="c", wave="w1", ship_now=False)
        emit("step", activity_id="c", wave="w2", ship_now=False)

        server = _CaptureServer().start()
        try:
            monkeypatch.setenv("FLIGHTDECK_INGEST_URL", server.url)
            assert ship(buf) == 2
            assert server.wait_for(2)
            waves = [b["wave"] for (_p, b, _a) in server.received]
            assert waves == ["w1", "w2"]  # ordered
            # Offset advanced — a second ship sends nothing new.
            assert ship(buf) == 0
        finally:
            server.stop()

    def test_ingest_down_then_recover(self, buf, monkeypatch):
        # Start a server to claim a port, then stop it → that port is closed.
        dead = _CaptureServer().start()
        port = dead.port
        dead.stop()
        url = f"http://127.0.0.1:{port}/ingest"
        monkeypatch.setenv("FLIGHTDECK_INGEST_URL", url)

        emit("step", activity_id="c", wave="w1", ship_now=False)
        emit("step", activity_id="c", wave="w2", ship_now=False)
        # Ingest down → ship fails, buffers retained, offset unchanged, no raise.
        assert ship(buf) == 0

        # Recover on the same port.
        live = _CaptureServer(port=port).start()
        try:
            assert ship(buf) == 2  # ordered replay on recovery
            assert live.wait_for(2)
            assert [b["wave"] for (_p, b, _a) in live.received] == ["w1", "w2"]
        finally:
            live.stop()


# ---------------------------------------------------------------------------
# CLI surface (used by the session hook S1.7 + Workflow tee S1.6)
# ---------------------------------------------------------------------------

def _run(
    argv: list[str],
    events_path: Path,
    scope_path: Path | None = None,
    extra_env: dict[str, str] | None = None,
):
    # os.environ.copy() inherits the isolation the autouse
    # _isolate_flightdeck_buffer fixture (conftest.py) already set via
    # monkeypatch — including FLIGHTDECK_SCOPE_PATH and the ACTIVITY_ID/AGENT/
    # LOG_REF/EMIT_DISABLED scope defaults. Only override below what a specific
    # test actually needs to differ; never pop the ambient isolation, or a test
    # that doesn't pass scope_path silently loses conftest's protection and can
    # write into THIS repo's real .claude/status/ (the bug that motivated it).
    env = os.environ.copy()
    src = str(Path(__file__).resolve().parent.parent / "src")
    env["PYTHONPATH"] = src + (os.pathsep + env.get("PYTHONPATH", "") if env.get("PYTHONPATH") else "")
    env["FLIGHTDECK_EVENTS_PATH"] = str(events_path)
    # Isolate the shipper too, not just the buffer — an inherited ambient
    # FLIGHTDECK_INGEST_URL (e.g. from ~/.profile) spawns a real daemon thread
    # that races process exit and can segfault the interpreter on the way out
    # (#1149, found while writing these tests). Never leave it set for a test.
    env.pop("FLIGHTDECK_INGEST_URL", None)
    env.pop("FLIGHTDECK_INGEST_TOKEN", None)
    if scope_path is not None:
        env["FLIGHTDECK_SCOPE_PATH"] = str(scope_path)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(argv, capture_output=True, text=True, env=env)


class TestEmitCli:
    def test_module_cli_buffers(self, tmp_path):
        ep = tmp_path / "events.jsonl"
        r = _run(
            [sys.executable, "-m", "wave_status.events.emit", "step",
             "--activity-id", "camp-x", "--wave", "wave-1"],
            ep,
        )
        assert r.returncode == 0, r.stderr
        got = json.loads(ep.read_text(encoding="utf-8").splitlines()[0])
        assert got["kind"] == "step" and got["wave"] == "wave-1"

    def test_wave_status_emit_subcommand(self, tmp_path):
        ep = tmp_path / "events.jsonl"
        r = _run(
            [sys.executable, "-m", "wave_status", "emit", "concern",
             "--activity-id", "camp-x", "--concern-kind", "gate-override",
             "--source", "coded", "--wave", "wave-2"],
            ep,
        )
        assert r.returncode == 0, r.stderr
        got = json.loads(ep.read_text(encoding="utf-8").splitlines()[0])
        assert got["kind"] == "concern"
        assert got["concernKind"] == "gate-override"
        assert got["source"] == "coded"

    def test_metric_stub_value_null_via_cli(self, tmp_path):
        ep = tmp_path / "events.jsonl"
        # No --value ⇒ honest seamed-absent token stub (value: null).
        r = _run(
            [sys.executable, "-m", "wave_status", "emit", "metric",
             "--activity-id", "c", "--metric", "tokens"],
            ep,
        )
        assert r.returncode == 0, r.stderr
        got = json.loads(ep.read_text(encoding="utf-8").splitlines()[0])
        assert got["metric"] == "tokens" and got["value"] is None

    def test_cli_bad_kind_exits_zero_no_buffer(self, tmp_path):
        ep = tmp_path / "events.jsonl"
        r = _run(
            [sys.executable, "-m", "wave_status", "emit", "bogus",
             "--activity-id", "c"],
            ep,
        )
        assert r.returncode == 0  # fire-and-forget: never fail the caller
        assert not ep.exists() or ep.read_text() == ""


class TestResolveAgent:
    """resolve_agent() — the FlightDeck card's Dev-Name title source (#1026)."""

    def test_env_wins(self, monkeypatch):
        from wave_status.events.emit import resolve_agent

        monkeypatch.setenv("FLIGHTDECK_AGENT", "babelfish")
        assert resolve_agent("/any/root") == "babelfish"

    def test_reads_dev_name_from_identity(self, tmp_path, monkeypatch):
        from wave_status.events.emit import resolve_agent

        monkeypatch.delenv("FLIGHTDECK_AGENT", raising=False)
        cl = tmp_path / ".claude"
        cl.mkdir()
        (cl / "agent-identity.json").write_text(
            json.dumps({"dev_name": "dangling-pointer", "dev_team": "bs"}), encoding="utf-8"
        )
        assert resolve_agent(tmp_path) == "dangling-pointer"

    def test_missing_identity_returns_none(self, tmp_path, monkeypatch):
        from wave_status.events.emit import resolve_agent

        monkeypatch.delenv("FLIGHTDECK_AGENT", raising=False)
        assert resolve_agent(tmp_path / "no-such") is None

    def test_env_beats_present_identity_file(self, tmp_path, monkeypatch):
        from wave_status.events.emit import resolve_agent

        cl = tmp_path / ".claude"
        cl.mkdir()
        (cl / "agent-identity.json").write_text(json.dumps({"dev_name": "from-file"}), encoding="utf-8")
        monkeypatch.setenv("FLIGHTDECK_AGENT", "from-env")
        assert resolve_agent(tmp_path) == "from-env"

    def test_malformed_or_nondict_json_returns_none(self, tmp_path, monkeypatch):
        from wave_status.events.emit import resolve_agent

        monkeypatch.delenv("FLIGHTDECK_AGENT", raising=False)
        cl = tmp_path / ".claude"
        cl.mkdir()
        (cl / "agent-identity.json").write_text("not json {", encoding="utf-8")
        assert resolve_agent(tmp_path) is None
        (cl / "agent-identity.json").write_text('["a","list"]', encoding="utf-8")
        assert resolve_agent(tmp_path) is None

    def test_empty_dev_name_returns_none(self, tmp_path, monkeypatch):
        from wave_status.events.emit import resolve_agent

        monkeypatch.delenv("FLIGHTDECK_AGENT", raising=False)
        cl = tmp_path / ".claude"
        cl.mkdir()
        (cl / "agent-identity.json").write_text(json.dumps({"dev_name": ""}), encoding="utf-8")
        assert resolve_agent(tmp_path) is None

    def test_legacy_tmp_fallback(self, tmp_path, monkeypatch):
        # #1026: transition-window fallback to /tmp/claude-agent-<md5(root)>.json
        # when the canonical file is absent (mirrors flightdeck-session-emit.sh).
        import hashlib

        from wave_status.events.emit import resolve_agent

        monkeypatch.delenv("FLIGHTDECK_AGENT", raising=False)
        digest = hashlib.md5(str(tmp_path).encode("utf-8")).hexdigest()
        legacy = Path("/tmp") / f"claude-agent-{digest}.json"
        legacy.write_text(json.dumps({"dev_name": "legacy-name"}), encoding="utf-8")
        try:
            assert resolve_agent(tmp_path) == "legacy-name"  # no canonical file → uses /tmp
        finally:
            legacy.unlink(missing_ok=True)


class TestScopeMarker:
    """#1148 — the writer half of mcp-server-sdlc#537.

    sdlc-server's own handlers (ci_wait_run, pr_merge, wave_finalize, ...) run
    in the MCP SERVER process, already spawned before a campaign starts, so a
    driver's in-session `export FLIGHTDECK_ACTIVITY_ID=...` can never reach it
    (confirmed live via /proc/<pid>/environ on three running servers — each was
    frozen at spawn with no FLIGHTDECK_ACTIVITY_ID at all, falling through to a
    repo-basename card, #1144's sdlc-server-side mechanism). This marker gives
    the server something live to read instead: `main()` writes it on
    activity_start and clears it on a matching activity_end.
    """

    def test_activity_start_writes_the_marker(self, tmp_path):
        ep = tmp_path / "events.jsonl"
        sp = tmp_path / "scope.json"
        r = _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start",
             "--activity-id", "116", "--agent", "harbinger", "--activity-type", "campaign"],
            ep, sp,
        )
        assert r.returncode == 0, r.stderr
        got = json.loads(sp.read_text(encoding="utf-8"))
        assert got["activityId"] == "116"
        assert got["agent"] == "harbinger"
        # ISO8601 Z-suffixed, matching the contract in mcp-server-sdlc#537 —
        # not asserting an exact value (that would be a flaky test), just shape.
        assert got["updatedAt"].endswith("Z")
        assert "T" in got["updatedAt"]

    def test_no_agent_flag_writes_a_null_agent_not_a_string(self, tmp_path):
        ep = tmp_path / "events.jsonl"
        sp = tmp_path / "scope.json"
        r = _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start",
             "--activity-id", "116", "--activity-type", "campaign"],
            ep, sp,
        )
        assert r.returncode == 0, r.stderr
        got = json.loads(sp.read_text(encoding="utf-8"))
        assert got["agent"] is None

    def test_unresolved_activity_id_writes_no_marker(self, tmp_path):
        # No --activity-id and no FLIGHTDECK_ACTIVITY_ID ⇒ emit()'s own fallback
        # is the literal string "unknown". Writing a marker for that would poison
        # the READ side's fallback chain with "unknown" instead of nothing — worse
        # than no marker at all, since "unknown" would then win over a later,
        # correct env/repo-basename resolution.
        ep = tmp_path / "events.jsonl"
        sp = tmp_path / "scope.json"
        r = _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start"],
            ep, sp,
        )
        assert r.returncode == 0, r.stderr
        assert not sp.exists()

    def test_matching_activity_end_clears_the_marker(self, tmp_path):
        ep = tmp_path / "events.jsonl"
        sp = tmp_path / "scope.json"
        _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start",
             "--activity-id", "116", "--agent", "harbinger", "--activity-type", "campaign"],
            ep, sp,
        )
        assert sp.exists()
        r = _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_end",
             "--activity-id", "116"],
            ep, sp,
        )
        assert r.returncode == 0, r.stderr
        assert not sp.exists()

    def test_mismatched_activity_end_does_not_clear_it(self, tmp_path):
        # An unrelated activity_end in the same repo — a session close, a
        # different activity — must not wipe a live campaign's marker.
        ep = tmp_path / "events.jsonl"
        sp = tmp_path / "scope.json"
        _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start",
             "--activity-id", "116", "--agent", "harbinger", "--activity-type", "campaign"],
            ep, sp,
        )
        r = _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_end",
             "--activity-id", "999"],
            ep, sp,
        )
        assert r.returncode == 0, r.stderr
        got = json.loads(sp.read_text(encoding="utf-8"))
        assert got["activityId"] == "116"

    def test_activity_end_with_no_prior_marker_is_a_noop(self, tmp_path):
        ep = tmp_path / "events.jsonl"
        sp = tmp_path / "scope.json"
        r = _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_end",
             "--activity-id", "116"],
            ep, sp,
        )
        assert r.returncode == 0, r.stderr
        assert not sp.exists()

    def test_a_second_activity_start_overwrites_cleanly(self, tmp_path):
        # No prior activity_end required to start the next campaign — the
        # wavemachine pre-flight already refuses a second concurrent campaign
        # in one repo, so a new activity_start here always supersedes.
        ep = tmp_path / "events.jsonl"
        sp = tmp_path / "scope.json"
        _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start",
             "--activity-id", "116", "--agent", "harbinger", "--activity-type", "campaign"],
            ep, sp,
        )
        _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start",
             "--activity-id", "121", "--agent", "bishop", "--activity-type", "campaign"],
            ep, sp,
        )
        got = json.loads(sp.read_text(encoding="utf-8"))
        assert got == {"activityId": "121", "agent": "bishop", "updatedAt": got["updatedAt"]}

    def test_unwritable_scope_path_does_not_break_the_underlying_emit(self, tmp_path):
        # A FILE sitting where the marker's parent directory needs to be —
        # path.parent.mkdir(parents=True) raises, caught by the marker helper's
        # own guard. The emit it rode in on must still succeed (R-01/R-03: this
        # is instrumentation, a broken marker must never fail the caller).
        ep = tmp_path / "events.jsonl"
        blocker = tmp_path / "blocked"
        blocker.write_text("not a directory", encoding="utf-8")
        sp = blocker / "scope.json"
        r = _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start",
             "--activity-id", "116", "--agent", "harbinger", "--activity-type", "campaign"],
            ep, sp,
        )
        assert r.returncode == 0, r.stderr
        got = json.loads(ep.read_text(encoding="utf-8").splitlines()[0])
        assert got["kind"] == "activity_start" and got["activityId"] == "116"
        assert not sp.exists()

    def test_write_scope_marker_itself_never_raises(self, tmp_path, monkeypatch):
        # DIRECT, in-process — no subprocess, no main()'s own outer try/except
        # around it. main()'s wrapping guard alone would make the CLI-level
        # test above pass even if THIS function's own guard were removed (the
        # buffer append already happened before this runs, so the observable
        # CLI behavior is identical either way) — this is the test that is
        # actually sensitive to whether _write_scope_marker's guard exists.
        from wave_status.events.emit import _write_scope_marker

        blocker = tmp_path / "blocked"
        blocker.write_text("not a directory", encoding="utf-8")
        monkeypatch.setenv("FLIGHTDECK_SCOPE_PATH", str(blocker / "scope.json"))
        _write_scope_marker("116", "harbinger")  # must not raise

    def test_clear_scope_marker_itself_never_raises_on_malformed_json(self, tmp_path, monkeypatch):
        from wave_status.events.emit import _clear_scope_marker_if_matching

        sp = tmp_path / "scope.json"
        sp.write_text("{not valid json", encoding="utf-8")
        monkeypatch.setenv("FLIGHTDECK_SCOPE_PATH", str(sp))
        _clear_scope_marker_if_matching("116")  # must not raise
        assert sp.read_text(encoding="utf-8") == "{not valid json"  # left untouched

    def test_disabled_switch_leaves_a_live_marker_untouched(self, tmp_path):
        # The intent is "a live marker must SURVIVE a disabled emit" — not just
        # "a disabled emit writes nothing new". Targeting a second, never-written
        # path proved only the latter; this targets the SAME marker the first
        # call wrote, so it actually exercises the claim in the test's name.
        ep = tmp_path / "events.jsonl"
        sp = tmp_path / "scope.json"
        _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start",
             "--activity-id", "116", "--agent", "harbinger", "--activity-type", "campaign"],
            ep, sp,
        )
        assert json.loads(sp.read_text(encoding="utf-8"))["activityId"] == "116"

        r2 = _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start",
             "--activity-id", "999", "--agent", "someone-else"],
            ep, sp, extra_env={"FLIGHTDECK_EMIT_DISABLED": "1"},
        )
        assert r2.returncode == 0, r2.stderr
        assert json.loads(sp.read_text(encoding="utf-8"))["activityId"] == "116"

    def test_session_activity_start_does_not_touch_the_marker(self, tmp_path):
        # The critical case: scripts/flightdeck-session-emit.sh ALSO emits
        # activity_start (every SessionStart hook firing), with
        # --activity-type session. This must never create OR overwrite a
        # campaign's marker — a routine session start silently clobbering a
        # live campaign's telemetry would reintroduce #1144.
        ep = tmp_path / "events.jsonl"
        sp = tmp_path / "scope.json"
        _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start",
             "--activity-id", "116", "--agent", "harbinger", "--activity-type", "campaign"],
            ep, sp,
        )
        r = _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start",
             "--activity-id", "session:abc123", "--agent", "harbinger",
             "--activity-type", "session"],
            ep, sp,
        )
        assert r.returncode == 0, r.stderr
        assert json.loads(sp.read_text(encoding="utf-8"))["activityId"] == "116"

    def test_a_bare_session_activity_start_with_no_prior_marker_writes_none(self, tmp_path):
        # The session hook's own legacy-retry path drops --activity-type
        # entirely (an older installed CLI rejects the unknown flag) — so this
        # must ALSO be excluded, not just the explicit --activity-type session
        # case. A denylist on "session" would pass the case above and fail
        # this one; only an allowlist on "campaign" passes both.
        ep = tmp_path / "events.jsonl"
        sp = tmp_path / "scope.json"
        r = _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start",
             "--activity-id", "session:abc123", "--agent", "harbinger"],
            ep, sp,
        )
        assert r.returncode == 0, r.stderr
        assert not sp.exists()

    def test_lifecycle_events_other_than_start_and_end_never_touch_the_marker(self, tmp_path):
        # The per-wave workflow's tee fires step/metric continuously against
        # the same repo, far more often than activity_start/end — the highest-
        # frequency caller of this CLI. It must never create or clear a marker.
        ep = tmp_path / "events.jsonl"
        sp = tmp_path / "scope.json"
        _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start",
             "--activity-id", "116", "--agent", "harbinger", "--activity-type", "campaign"],
            ep, sp,
        )
        for kind, extra in (
            ("step", ["--wave", "wave-1", "--label", "planning"]),
            ("metric", ["--metric", "tokens"]),
            ("phase", ["--phase", "P1"]),
        ):
            r = _run(
                [sys.executable, "-m", "wave_status.events.emit", kind,
                 "--activity-id", "116"] + extra,
                ep, sp,
            )
            assert r.returncode == 0, r.stderr
            marker = json.loads(sp.read_text(encoding="utf-8"))
            assert marker["activityId"] == "116"
            # Also pin agent, not just activityId: these calls pass no --agent,
            # so a mutation that wrongly rewrites the marker on step/metric/phase
            # would drop it to null while activityId (echoed back unchanged)
            # would still read "116" either way — activityId alone can't tell
            # "untouched" apart from "touched with the same id back".
            assert marker["agent"] == "harbinger"

    def test_the_production_default_path_is_cwd_dot_claude_status(self, tmp_path):
        # Every other test in this class runs against FLIGHTDECK_SCOPE_PATH — a
        # real, necessary test seam, but it means the literal PRODUCTION path
        # (the only one that ever runs for real) had zero coverage. This is the
        # one test that exercises it, with the override absent, cwd pinned to a
        # scratch directory instead of the real repo. Also pins the writer's
        # half of the cross-repo contract with mcp-server-sdlc#537.
        ep = tmp_path / "events.jsonl"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
        env["FLIGHTDECK_EVENTS_PATH"] = str(ep)
        env.pop("FLIGHTDECK_INGEST_URL", None)
        env.pop("FLIGHTDECK_INGEST_TOKEN", None)
        env.pop("FLIGHTDECK_SCOPE_PATH", None)  # the one test that must NOT override it
        r = subprocess.run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start",
             "--activity-id", "116", "--agent", "harbinger", "--activity-type", "campaign"],
            capture_output=True, text=True, env=env, cwd=str(tmp_path),
        )
        assert r.returncode == 0, r.stderr
        default_path = tmp_path / ".claude" / "status" / "flightdeck-scope.json"
        assert default_path.exists()
        assert json.loads(default_path.read_text(encoding="utf-8"))["activityId"] == "116"

