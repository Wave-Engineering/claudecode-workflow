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

def _run(argv: list[str], events_path: Path):
    env = os.environ.copy()
    src = str(Path(__file__).resolve().parent.parent / "src")
    env["PYTHONPATH"] = src + (os.pathsep + env.get("PYTHONPATH", "") if env.get("PYTHONPATH") else "")
    env["FLIGHTDECK_EVENTS_PATH"] = str(events_path)
    env.pop("FLIGHTDECK_INGEST_URL", None)
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
