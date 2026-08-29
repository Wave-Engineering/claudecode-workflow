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
    arrival order. ``status`` is the code it returns (default 202). ``delay``
    (#1149) sleeps that many seconds BEFORE responding — lets a test control
    exactly how long a POST stays in-flight, deterministically, instead of
    relying on real network timing to land inside or outside a join window.
    """

    def __init__(
        self, status: int = 202, port: int = 0, delay: float = 0.0, fail_first_n: int = 0
    ):
        self.received: list[tuple] = []
        self.status = status
        captured = self.received
        status_code = self.status
        request_count = [0]

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def do_POST(self):
                request_count[0] += 1
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length).decode("utf-8") if length else ""
                try:
                    body = json.loads(raw)
                except Exception:
                    body = raw
                if delay:
                    time.sleep(delay)
                captured.append((self.path, body, self.headers.get("Authorization")))
                # #1189: simulate a scanner that transiently 5xx's the first
                # N requests then recovers — real end-to-end exercise of
                # _post()'s own retry loop, not a mocked control-flow stub.
                if request_count[0] <= fail_first_n:
                    self.send_response(503)
                else:
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
# #1149 — bounded join of outstanding shipper threads at TRUE process exit
# only. `emit()`/`_ship_async()` must stay non-blocking for every in-process
# caller (`_cmd_emit`, `_cmd_campaign_head`, direct test calls) — only the
# real ``if __name__ == "__main__":`` guards may call `flush_pending_ships`.
# ---------------------------------------------------------------------------

class TestFlushPendingShips:
    def test_ship_async_registers_the_started_thread(self, buf, monkeypatch):
        server = _CaptureServer().start()
        try:
            monkeypatch.setenv("FLIGHTDECK_INGEST_URL", server.url)
            assert emit_mod._pending_ships == []
            emit("step", activity_id="camp-1", wave="w")
            assert len(emit_mod._pending_ships) == 1
            assert emit_mod._pending_ships[0].name == "flightdeck-ship"
        finally:
            emit_mod.flush_pending_ships(timeout=2.0)
            server.stop()

    def test_flush_joins_a_fast_ship_and_clears_the_registry(self, buf, monkeypatch):
        server = _CaptureServer(delay=0.05).start()
        try:
            monkeypatch.setenv("FLIGHTDECK_INGEST_URL", server.url)
            emit("step", activity_id="camp-1", wave="w")
            assert len(emit_mod._pending_ships) == 1
            emit_mod.flush_pending_ships(timeout=2.0)
            # The join WAITED for the POST rather than abandoning it — the
            # slow (but well within the timeout) response already landed.
            assert server.wait_for(1, timeout=0.1)
            assert emit_mod._pending_ships == []
        finally:
            server.stop()

    def test_flush_is_bounded_not_indefinite(self, buf, monkeypatch):
        # A server that responds slower than the join timeout: flush must
        # still return promptly (bounded), never hang waiting for the POST
        # to finish. This is the R-02-preserving half of the fix — an
        # unbounded join would just move the "caller blocks forever on a
        # dead ingest" failure to a different call site.
        server = _CaptureServer(delay=2.0).start()
        try:
            monkeypatch.setenv("FLIGHTDECK_INGEST_URL", server.url)
            emit("step", activity_id="camp-1", wave="w")
            t0 = time.monotonic()
            emit_mod.flush_pending_ships(timeout=0.2)
            elapsed = time.monotonic() - t0
            assert elapsed < 1.0, f"flush blocked for {elapsed}s against a 0.2s timeout"
            # Registry is cleared regardless of whether the thread finished —
            # waiting on an abandoned thread a second time serves no purpose.
            assert emit_mod._pending_ships == []
        finally:
            server.stop()

    def test_flush_default_timeout_is_flightdeck_ingest_timeout_env(self, monkeypatch):
        monkeypatch.setenv("FLIGHTDECK_INGEST_TIMEOUT", "7.5")
        calls: list[float | None] = []

        class _FakeThread:
            def join(self, timeout=None):
                calls.append(timeout)

        emit_mod._pending_ships.append(_FakeThread())
        emit_mod.flush_pending_ships()  # no explicit timeout ⇒ env default
        assert calls == [7.5]

    def test_flush_never_raises_when_join_raises(self, monkeypatch):
        class _RaisingThread:
            def join(self, timeout=None):
                raise RuntimeError("boom")

        emit_mod._pending_ships.append(_RaisingThread())
        emit_mod.flush_pending_ships(timeout=0.1)  # must not propagate (R-03)
        assert emit_mod._pending_ships == []

    def test_flush_is_a_noop_with_nothing_pending(self):
        assert emit_mod._pending_ships == []
        emit_mod.flush_pending_ships(timeout=0.1)  # no error, nothing to do
        assert emit_mod._pending_ships == []

    def test_flush_std_streams_swallows_a_broken_pipe(self, monkeypatch):
        # A closed reading end (`wave-status show | head -1`) makes flush()
        # raise BrokenPipeError. Letting that propagate out of the
        # `_run_as_script()` finally block would skip the os._exit() call
        # right after it — a clean, fast exit turning into a shutdown
        # traceback. Both streams must be independently guarded: one
        # raising must not prevent the other's flush from being attempted.
        class _Boom:
            def __init__(self):
                self.flushed = False

            def flush(self):
                self.flushed = True
                raise BrokenPipeError(32, "Broken pipe")

        boom_out, boom_err = _Boom(), _Boom()
        monkeypatch.setattr(emit_mod.sys, "stdout", boom_out)
        monkeypatch.setattr(emit_mod.sys, "stderr", boom_err)
        emit_mod._flush_std_streams()  # must not raise
        assert boom_out.flushed and boom_err.flushed


class TestRunAsScriptExitsThroughFlush:
    """Both modules' TRUE top-level entry points are factored into a named
    ``_run_as_script()`` function specifically so this can be tested without
    ever letting a real ``os._exit`` fire — that would kill the pytest
    process. `_run_as_script()` has a THIRD caller beyond the two
    ``if __name__ == "__main__":`` guards exercised here in-process: the
    zipapp shim `scripts/ci/build.sh` generates for the shipped
    `wave-status` binary calls it directly (see
    `tests/test_zipapp.py::TestZipappShipperJoinsOnExit`, which is the
    regression test for THAT path specifically — it caught a real bug this
    module's tests alone did not, since the zipapp shim never runs either
    `__main__` guard). Mocking os._exit and asserting call ORDER is the
    regression test AC #4 on #1149 asked for: it fails on the pre-fix code
    (no `flush_pending_ships` existed to call) with no timing dependency,
    unlike the crash itself (probabilistic, 2/3 in the original report)."""

    def test_emit_module_guard_flushes_before_exit(self, monkeypatch):
        from wave_status.events import emit as emit_module

        order: list[str] = []
        monkeypatch.setattr(emit_module, "main", lambda: (order.append("main"), 0)[1])
        monkeypatch.setattr(
            emit_module, "flush_pending_ships", lambda: order.append("flush")
        )
        monkeypatch.setattr(
            emit_module.os, "_exit", lambda code: order.append(f"exit:{code}")
        )
        emit_module._run_as_script()
        assert order == ["main", "flush", "exit:0"]

    def test_emit_module_guard_flushes_even_when_main_raises(self, monkeypatch):
        from wave_status.events import emit as emit_module

        order: list[str] = []

        def _boom():
            order.append("main")
            raise RuntimeError("kaboom")

        monkeypatch.setattr(emit_module, "main", _boom)
        monkeypatch.setattr(
            emit_module, "flush_pending_ships", lambda: order.append("flush")
        )
        monkeypatch.setattr(
            emit_module.os, "_exit", lambda code: order.append(f"exit:{code}")
        )
        with pytest.raises(RuntimeError):
            emit_module._run_as_script()
        # The finally block still ran flush before the exception propagated —
        # os._exit is unreachable here (the exception wins), which is correct:
        # an unhandled error in the standalone-script form should surface,
        # not be silently swallowed into a clean exit.
        assert order == ["main", "flush"]

    def test_dunder_main_guard_flushes_before_exit_on_success(self, monkeypatch):
        import wave_status.__main__ as main_module

        order: list[str] = []
        monkeypatch.setattr(main_module, "main", lambda: order.append("main"))
        monkeypatch.setattr(
            "wave_status.events.emit.flush_pending_ships",
            lambda: order.append("flush"),
        )
        monkeypatch.setattr(
            main_module.os, "_exit", lambda code: order.append(f"exit:{code}")
        )
        main_module._run_as_script()
        assert order == ["main", "flush", "exit:0"]

    def test_dunder_main_guard_extracts_systemexit_code(self, monkeypatch):
        import wave_status.__main__ as main_module

        order: list[str] = []

        def _exits_nonzero():
            order.append("main")
            raise SystemExit(2)

        monkeypatch.setattr(main_module, "main", _exits_nonzero)
        monkeypatch.setattr(
            "wave_status.events.emit.flush_pending_ships",
            lambda: order.append("flush"),
        )
        monkeypatch.setattr(
            main_module.os, "_exit", lambda code: order.append(f"exit:{code}")
        )
        main_module._run_as_script()
        # flush still ran (finally), and the REAL SystemExit code (2) reached
        # os._exit — not silently coerced to 0 or swallowed.
        assert order == ["main", "flush", "exit:2"]

    def test_dunder_main_guard_systemexit_none_code_means_zero(self, monkeypatch):
        import wave_status.__main__ as main_module

        def _exits_bare():
            raise SystemExit()  # .code is None ⇒ conventionally exit 0

        monkeypatch.setattr(main_module, "main", _exits_bare)
        monkeypatch.setattr("wave_status.events.emit.flush_pending_ships", lambda: None)
        captured: dict[str, int] = {}
        monkeypatch.setattr(
            main_module.os, "_exit", lambda code: captured.__setitem__("code", code)
        )
        main_module._run_as_script()
        assert captured["code"] == 0


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


class TestShipRetryAndLock:
    """cc-workflow#1189 — a single transient POST failure must not wedge the
    entire ordered replay indefinitely, and concurrent ship() calls sharing
    one buffer/offset (every emitting process on a fleet machine) must not
    race each other. Reproduces the exact live failure: FlightDeck delivery
    on a real machine stalled for over a month after one blip, with the
    endpoint reachable and the stuck payload accepted on manual retry."""

    def test_ship_retries_a_transient_failure_and_succeeds(self, buf, monkeypatch):
        # 503 once, then 202 — the real end-to-end shape of the live bug:
        # a blip that resolves within the same call, not a dead endpoint.
        server = _CaptureServer(fail_first_n=1).start()
        try:
            monkeypatch.setenv("FLIGHTDECK_INGEST_URL", server.url)
            emit("step", activity_id="c", wave="w1", ship_now=False)
            assert ship(buf) == 1, "a single transient failure must still ship within one ship() call"
            assert server.wait_for(2)  # the failed attempt + the retry that succeeded
            assert len(server.received) == 2
        finally:
            server.stop()

    def test_ship_gives_up_after_bounded_retries_on_persistent_failure(self, buf, monkeypatch):
        # Always 503 — must still stop (not retry forever, not hang the caller).
        server = _CaptureServer(fail_first_n=10_000).start()
        try:
            monkeypatch.setenv("FLIGHTDECK_INGEST_URL", server.url)
            emit("step", activity_id="c", wave="w1", ship_now=False)
            assert ship(buf) == 0, "a persistently failing endpoint must still give up"
            assert server.wait_for(4)
            # 1 initial attempt + 3 retries (the default backoff schedule's
            # length) — proves it retried, and that it stopped rather than
            # retrying unboundedly.
            assert len(server.received) == 4
            assert emit_mod._read_offset(buf) == 0, "offset must not advance past an unshipped line"
        finally:
            server.stop()

    def test_ship_retry_uses_backoff_not_a_tight_loop(self, buf, monkeypatch):
        # Override the autouse fixture's zeroed backoff for this ONE test —
        # the thing being proven here IS the sleep, so it can't be zeroed.
        monkeypatch.setenv("FLIGHTDECK_POST_RETRY_BACKOFFS", "0.2,0.2,0.2")
        server = _CaptureServer(fail_first_n=10_000).start()
        try:
            monkeypatch.setenv("FLIGHTDECK_INGEST_URL", server.url)
            emit("step", activity_id="c", wave="w1", ship_now=False)
            t0 = time.monotonic()
            assert ship(buf) == 0
            elapsed = time.monotonic() - t0
            assert elapsed >= 0.5, (
                f"elapsed {elapsed}s — too fast for 3 real 0.2s backoffs; "
                "looks like a tight retry loop with no real delay"
            )
        finally:
            server.stop()

    def test_concurrent_ship_calls_do_not_race_the_offset(self, buf, monkeypatch):
        # Ten buffered lines; two threads call ship() against the SAME buffer
        # at once, exactly like two agent processes on one fleet machine both
        # firing _ship_async off unrelated emit() calls.
        server = _CaptureServer(delay=0.05).start()
        try:
            monkeypatch.setenv("FLIGHTDECK_INGEST_URL", server.url)
            for i in range(10):
                emit("step", activity_id="c", wave=f"w{i}", ship_now=False)

            results: list[int] = []

            def _run():
                results.append(ship(buf))

            t1 = threading.Thread(target=_run)
            t2 = threading.Thread(target=_run)
            t1.start()
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)

            assert server.wait_for(10, timeout=5)
            # Exactly one thread must have won the lock and shipped all ten;
            # the other must have found it held and backed off immediately
            # (returned 0) rather than racing a second, overlapping replay.
            assert sorted(results) == [0, 10], (
                f"expected one ship() to do all the work and the other to "
                f"no-op on lock contention, got {results}"
            )
            # No duplicate delivery — the loser never got far enough to send.
            assert len(server.received) == 10
            waves = sorted(b["wave"] for (_p, b, _a) in server.received)
            assert waves == sorted(f"w{i}" for i in range(10))
            assert emit_mod._read_offset(buf) == buf.stat().st_size
        finally:
            server.stop()

    def test_offset_lock_is_released_on_failure(self, buf, monkeypatch):
        # A ship() call against a persistently dead endpoint must not leave
        # its lock held for the NEXT call once the endpoint recovers.
        dead = _CaptureServer().start()
        port = dead.port
        dead.stop()
        monkeypatch.setenv("FLIGHTDECK_INGEST_URL", f"http://127.0.0.1:{port}/ingest")
        emit("step", activity_id="c", wave="w1", ship_now=False)
        assert ship(buf) == 0  # fails, lock must be released on the way out

        live = _CaptureServer(port=port).start()
        try:
            monkeypatch.setenv("FLIGHTDECK_INGEST_URL", live.url)
            assert ship(buf) == 1, "lock from the failed call was not released"
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
    cwd: Path | None = None,
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
    # #1146 step 1: main() now defaults `agent` via resolve_agent(Path.cwd())
    # when `--agent` is omitted, so EVERY subprocess this helper spawns must
    # get an isolated cwd, not just the tests that assert on `agent` today —
    # inheriting pytest's own cwd (this repo's root, which has a REAL
    # .claude/agent-identity.json) would silently stamp a real Dev-Name into
    # every buffered event otherwise. Callers that pass `cwd` explicitly (the
    # tests that exercise this resolution directly) keep their own isolated
    # directory; everyone else falls back to `events_path`'s own tmp_path
    # directory, which is per-test and never carries an identity file.
    return subprocess.run(
        argv, capture_output=True, text=True, env=env,
        cwd=str(cwd) if cwd else str(events_path.parent),
    )


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

    def test_detail_json_decodes_to_an_object_not_a_string(self, tmp_path):
        # #1145: --detail-json exists precisely so a caller with a structured
        # payload (campaign-head) can ship an OBJECT, unlike plain --detail
        # which is a JSON string that flightdeck's asRecord() only accepts as
        # a compatibility shim for the old shape.
        ep = tmp_path / "events.jsonl"
        r = _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start",
             "--activity-id", "camp-x", "--detail-json", '{"planTotal": 3}'],
            ep,
        )
        assert r.returncode == 0, r.stderr
        got = json.loads(ep.read_text(encoding="utf-8").splitlines()[0])
        assert got["detail"] == {"planTotal": 3}
        assert isinstance(got["detail"], dict)

    def test_detail_json_wins_over_plain_detail_when_both_given(self, tmp_path):
        ep = tmp_path / "events.jsonl"
        r = _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start",
             "--activity-id", "camp-x",
             "--detail", "free-form prose",
             "--detail-json", '{"planTotal": 5}'],
            ep,
        )
        assert r.returncode == 0, r.stderr
        got = json.loads(ep.read_text(encoding="utf-8").splitlines()[0])
        assert got["detail"] == {"planTotal": 5}

    def test_malformed_detail_json_never_raises_fire_and_forget(self, tmp_path):
        # Consistent with the rest of this CLI's "never fail a hook" contract
        # (main()'s docstring) — a bad --detail-json exits 0 and buffers
        # nothing, exactly like an unparseable --detail string would.
        ep = tmp_path / "events.jsonl"
        r = _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start",
             "--activity-id", "camp-x", "--detail-json", "{ not json"],
            ep,
        )
        assert r.returncode == 0, r.stderr
        assert not ep.exists() or ep.read_text(encoding="utf-8") == ""

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


class TestExitJoinsShipperEndToEnd:
    """#1149, end to end: a REAL subprocess, through the REAL
    ``if __name__ == "__main__":`` guard (`_run_as_script`), against a REAL
    (slow, but in-bound) ingest server — not mocked, not in-process. This is
    the closest thing to the original crash scenario this suite can assert
    without ever needing the crash to actually reproduce: the process must
    (a) still exit cleanly (not hang, not crash) when the shipper is slow,
    and (b) actually deliver the event before exiting rather than abandoning
    it, proving the join is real and not a no-op.
    """

    def test_cli_process_waits_for_a_slow_but_in_bound_post_before_exiting(
        self, tmp_path
    ):
        server = _CaptureServer(delay=0.3).start()
        try:
            ep = tmp_path / "events.jsonl"
            r = _run(
                [sys.executable, "-m", "wave_status.events.emit", "step",
                 "--activity-id", "camp-1", "--wave", "w"],
                ep,
                extra_env={
                    "FLIGHTDECK_INGEST_URL": server.url,
                    "FLIGHTDECK_INGEST_TIMEOUT": "2",
                },
            )
            assert r.returncode == 0, r.stderr
            # Not abandoned mid-flight: the subprocess's own exit already
            # waited long enough for the 0.3s-delayed POST to land.
            assert len(server.received) == 1, "process exited before the ship landed"
            assert server.received[0][1]["wave"] == "w"
        finally:
            server.stop()

    def test_cli_process_exits_promptly_against_a_hanging_ingest(self, tmp_path):
        # A server that never responds at all (accepts the connection, then
        # sits). The join must still be BOUNDED — the process should exit
        # near FLIGHTDECK_INGEST_TIMEOUT, not hang indefinitely.
        #
        # Asserts BOTH bounds, deliberately: an upper bound alone doesn't
        # distinguish this fix from the pre-fix code, which ALSO exits
        # "promptly" against a hanging ingest — it just never waits on the
        # thread at all (fire-and-forget, exits in ~0.1s regardless of the
        # server). A lower bound close to the configured timeout is what
        # actually proves the join happened rather than being a no-op: on
        # pre-fix code this assertion fails (elapsed lands near 0.1s, not
        # >=1.0s) — confirmed by mutation-reverting this exact test.
        # 5s is comfortably longer than the 1.5s join bound — no need for
        # 30s, which only stalls this test's own teardown (_CaptureServer's
        # single-threaded HTTPServer can't observe shutdown() until the
        # in-flight handler's sleep() returns).
        server = _CaptureServer(delay=5.0).start()
        try:
            ep = tmp_path / "events.jsonl"
            t0 = time.monotonic()
            r = _run(
                [sys.executable, "-m", "wave_status.events.emit", "step",
                 "--activity-id", "camp-1", "--wave", "w"],
                ep,
                extra_env={
                    "FLIGHTDECK_INGEST_URL": server.url,
                    "FLIGHTDECK_INGEST_TIMEOUT": "1.5",
                },
            )
            elapsed = time.monotonic() - t0
            assert r.returncode == 0, r.stderr
            assert elapsed >= 1.0, (
                f"process exited in {elapsed}s — too fast to have joined the "
                "shipper thread against a 1.5s bound; looks like a no-op join"
            )
            assert elapsed < 8.0, f"process took {elapsed}s against a 1.5s ship bound"
        finally:
            server.stop()


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


class TestResolveSession:
    """resolve_session() — the AX-4 stable session identity (#1146 step 3, #1165).

    Unlike resolve_agent(), there is no per-root identity FILE to read — a
    session id is inherently ephemeral/per-process, so this is env-only.
    """

    def test_flightdeck_session_id_wins(self, monkeypatch):
        from wave_status.events.emit import resolve_session

        monkeypatch.setenv("FLIGHTDECK_SESSION_ID", "sess-abc")
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        assert resolve_session() == "sess-abc"

    def test_falls_back_to_claude_code_session_id(self, monkeypatch):
        from wave_status.events.emit import resolve_session

        monkeypatch.delenv("FLIGHTDECK_SESSION_ID", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "claude-sess-1")
        assert resolve_session() == "claude-sess-1"

    def test_flightdeck_session_id_beats_claude_code_session_id(self, monkeypatch):
        from wave_status.events.emit import resolve_session

        monkeypatch.setenv("FLIGHTDECK_SESSION_ID", "from-flightdeck")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "from-claude")
        assert resolve_session() == "from-flightdeck"

    def test_neither_set_returns_none(self, monkeypatch):
        from wave_status.events.emit import resolve_session

        monkeypatch.delenv("FLIGHTDECK_SESSION_ID", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        assert resolve_session() is None

    def test_blank_env_values_are_not_trusted(self, monkeypatch):
        # An exported-but-empty var (the same accidental shape --agent ""
        # normalizes at the CLI layer, #1163) must not resolve to "".
        from wave_status.events.emit import resolve_session

        monkeypatch.setenv("FLIGHTDECK_SESSION_ID", "")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "")
        assert resolve_session() is None


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

    def test_activity_start_with_a_resolvable_session_writes_it_to_the_marker(self, tmp_path):
        # #1165 code review: the marker's `session` param was wired but the
        # ONE production call site never passed it — this pins the fix rather
        # than (as the first draft did) pinning the dead null-forever behavior.
        ep = tmp_path / "events.jsonl"
        sp = tmp_path / "scope.json"
        r = _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start",
             "--activity-id", "116", "--agent", "harbinger", "--activity-type", "campaign"],
            ep, sp,
            extra_env={"FLIGHTDECK_SESSION_ID": "sess-x"},
        )
        assert r.returncode == 0, r.stderr
        got = json.loads(sp.read_text(encoding="utf-8"))
        assert got["session"] == "sess-x"

    def test_no_agent_flag_and_no_resolvable_identity_writes_a_null_agent(self, tmp_path):
        # cc-workflow#1146 step 1: main() now defaults `agent` via
        # resolve_agent(Path.cwd()) when `--agent` is omitted — so this test's
        # "no agent" case requires an isolated cwd with NO
        # .claude/agent-identity.json, or it would silently resolve whatever
        # repo checkout pytest happens to run from (this repo's own real
        # identity file) instead of exercising the genuine null case.
        empty_cwd = tmp_path / "no-identity-here"
        empty_cwd.mkdir()
        ep = tmp_path / "events.jsonl"
        sp = tmp_path / "scope.json"
        r = _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start",
             "--activity-id", "116", "--activity-type", "campaign"],
            ep, sp, cwd=empty_cwd,
        )
        assert r.returncode == 0, r.stderr
        got = json.loads(sp.read_text(encoding="utf-8"))
        assert got["agent"] is None

    def test_no_agent_flag_but_a_resolvable_identity_stamps_it_anyway(self, tmp_path):
        # The positive case cc-workflow#1146 step 1 exists to fix: a caller
        # that never passes --agent at all (every hand-typed `wave-status
        # emit`, every Workflow-generated flightdeckTee line) still gets a
        # real Dev-Name, end-to-end through the CLI — not just in the
        # resolve_agent() unit tests above, which never exercised main()'s
        # own default-injection wiring.
        project = tmp_path / "project"
        (project / ".claude").mkdir(parents=True)
        (project / ".claude" / "agent-identity.json").write_text(
            json.dumps({"dev_name": "cortana", "dev_team": "oaw"}), encoding="utf-8"
        )
        ep = tmp_path / "events.jsonl"
        sp = tmp_path / "scope.json"
        r = _run(
            [sys.executable, "-m", "wave_status.events.emit", "activity_start",
             "--activity-id", "116", "--activity-type", "campaign"],
            ep, sp, cwd=project,
        )
        assert r.returncode == 0, r.stderr
        # Both the buffered event AND the scope marker pick up the default —
        # one resolution, two places it has to actually land.
        event = json.loads(ep.read_text(encoding="utf-8").splitlines()[0])
        assert event["agent"] == "cortana"
        marker = json.loads(sp.read_text(encoding="utf-8"))
        assert marker["agent"] == "cortana"

    def test_explicit_agent_flag_wins_over_a_resolvable_identity(self, tmp_path):
        # An explicit --agent is a caller's deliberate override — the new
        # default-injection in main() must never clobber it, even when cwd
        # ALSO has a resolvable (different) identity.
        project = tmp_path / "project"
        (project / ".claude").mkdir(parents=True)
        (project / ".claude" / "agent-identity.json").write_text(
            json.dumps({"dev_name": "cortana", "dev_team": "oaw"}), encoding="utf-8"
        )
        ep = tmp_path / "events.jsonl"
        r = _run(
            [sys.executable, "-m", "wave_status.events.emit", "step",
             "--activity-id", "116", "--agent", "explicit-override"],
            ep, cwd=project,
        )
        assert r.returncode == 0, r.stderr
        got = json.loads(ep.read_text(encoding="utf-8").splitlines()[0])
        assert got["agent"] == "explicit-override"

    def test_blank_agent_flag_is_treated_as_not_supplied(self, tmp_path):
        # Code review: `--agent ""` / `--agent " "` is the documented
        # accidental shape of an unset shell variable (`--agent "$DEV_NAME"`
        # with DEV_NAME empty) — never a deliberate "suppress attribution"
        # request. Every downstream consumer already normalizes a blank
        # agent to "no attribution" (flightdeck's fold.ts, mcp-server-sdlc's
        # scope-marker read), so a blank flag must resolve from cwd exactly
        # like an omitted one, not ship the blank through untouched.
        project = tmp_path / "project"
        (project / ".claude").mkdir(parents=True)
        (project / ".claude" / "agent-identity.json").write_text(
            json.dumps({"dev_name": "cortana", "dev_team": "oaw"}), encoding="utf-8"
        )
        for blank in ("", " "):
            ep = tmp_path / f"events-{blank!r}.jsonl"
            r = _run(
                [sys.executable, "-m", "wave_status.events.emit", "step",
                 "--activity-id", "116", "--agent", blank],
                ep, cwd=project,
            )
            assert r.returncode == 0, r.stderr
            got = json.loads(ep.read_text(encoding="utf-8").splitlines()[0])
            assert got["agent"] == "cortana"

    def test_blank_agent_flag_with_no_resolvable_identity_omits_the_key(self, tmp_path):
        # The other half of the normalization: blank must land on the SAME
        # "no attribution" outcome as an omitted flag, not a half-fixed
        # `agent: ""` — the exact shape every downstream consumer already
        # treats as falsy-but-present, which the pop() (not just skip) in
        # main() guarantees.
        empty_cwd = tmp_path / "no-identity-here"
        empty_cwd.mkdir()
        ep = tmp_path / "events.jsonl"
        r = _run(
            [sys.executable, "-m", "wave_status.events.emit", "step",
             "--activity-id", "116", "--agent", ""],
            ep, cwd=empty_cwd,
        )
        assert r.returncode == 0, r.stderr
        got = json.loads(ep.read_text(encoding="utf-8").splitlines()[0])
        assert "agent" not in got

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
        assert got == {
            "activityId": "121", "agent": "bishop", "session": None, "updatedAt": got["updatedAt"],
        }

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

