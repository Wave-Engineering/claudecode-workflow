"""Tests for the proxy module — state management, buffer, and payload parsing.

Tests exercise real code paths in proxy.py. Mocks are only used for the
mitmproxy flow objects (external boundary).
"""

from __future__ import annotations

import json
import time
import threading
import urllib.request
import urllib.error

import pytest

# Allow importing from the tools/cc-inspector directory
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from proxy import (
    Capture,
    CaptureBuffer,
    InspectorState,
    InspectorAddon,
    parse_system_prompt,
    parse_messages,
    parse_usage,
    build_capture_detail,
    make_control_handler,
    start_control_server,
)


# ---------------------------------------------------------------------------
# CaptureBuffer tests
# ---------------------------------------------------------------------------

class TestCaptureBuffer:
    """Tests for the ring buffer."""

    def test_add_and_len(self) -> None:
        buf = CaptureBuffer(max_size=10)
        assert len(buf) == 0

        cap = Capture(id="1", timestamp=time.time(), request_body={"messages": []})
        buf.add(cap)
        assert len(buf) == 1

    def test_fifo_eviction(self) -> None:
        """Buffer respects max_size, evicting oldest first."""
        buf = CaptureBuffer(max_size=3)

        for i in range(5):
            buf.add(Capture(id=str(i), timestamp=float(i), request_body={}))

        assert len(buf) == 3
        # Oldest should have been evicted
        assert buf.get("0") is None
        assert buf.get("1") is None
        # Newest should remain
        assert buf.get("2") is not None
        assert buf.get("3") is not None
        assert buf.get("4") is not None

    def test_clear(self) -> None:
        buf = CaptureBuffer(max_size=10)
        buf.add(Capture(id="1", timestamp=time.time(), request_body={}))
        buf.add(Capture(id="2", timestamp=time.time(), request_body={}))
        assert len(buf) == 2

        buf.clear()
        assert len(buf) == 0

    def test_get_returns_none_for_missing(self) -> None:
        buf = CaptureBuffer(max_size=10)
        assert buf.get("nonexistent") is None

    def test_list_metadata(self) -> None:
        buf = CaptureBuffer(max_size=10)
        buf.add(Capture(
            id="abc",
            timestamp=1000.0,
            request_body={
                "messages": [{"role": "user", "content": "hi"}],
                "system": [{"type": "text", "text": "you are helpful"}],
            },
            response_body={
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                },
            },
        ))

        meta = buf.list_metadata()
        assert len(meta) == 1
        assert meta[0]["id"] == "abc"
        assert meta[0]["message_count"] == 1
        assert meta[0]["system_blocks"] == 1
        assert meta[0]["usage"]["input_tokens"] == 100

    def test_list_metadata_string_system(self) -> None:
        """System as a string should count as 1 block."""
        buf = CaptureBuffer(max_size=10)
        buf.add(Capture(
            id="x",
            timestamp=1000.0,
            request_body={
                "messages": [],
                "system": "you are helpful",
            },
        ))

        meta = buf.list_metadata()
        assert meta[0]["system_blocks"] == 1

    def test_thread_safety(self) -> None:
        """Buffer should be safe under concurrent access."""
        buf = CaptureBuffer(max_size=100)
        errors: list[Exception] = []

        def writer(start: int) -> None:
            try:
                for i in range(50):
                    buf.add(Capture(
                        id=f"{start}-{i}",
                        timestamp=time.time(),
                        request_body={},
                    ))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # All 200 writes happened; buffer holds at most 100
        assert len(buf) <= 100


# ---------------------------------------------------------------------------
# InspectorState tests (arm/disarm)
# ---------------------------------------------------------------------------

class TestInspectorState:
    """Tests for arm/disarm state transitions."""

    def test_initial_state(self) -> None:
        state = InspectorState()
        assert not state.armed
        assert state.remaining == 0

    def test_arm_default(self) -> None:
        state = InspectorState()
        state.arm()
        assert state.armed
        assert state.remaining == 1

    def test_arm_with_count(self) -> None:
        state = InspectorState()
        state.arm(5)
        assert state.armed
        assert state.remaining == 5

    def test_disarm(self) -> None:
        state = InspectorState()
        state.arm(3)
        state.disarm()
        assert not state.armed
        assert state.remaining == 0

    def test_should_capture_decrements(self) -> None:
        state = InspectorState()
        state.arm(3)

        assert state.should_capture()
        assert state.remaining == 2
        assert state.should_capture()
        assert state.remaining == 1
        assert state.should_capture()
        assert state.remaining == 0
        # Auto-disarmed
        assert not state.armed
        assert not state.should_capture()

    def test_should_capture_when_disarmed(self) -> None:
        state = InspectorState()
        assert not state.should_capture()

    def test_arm_resets_count(self) -> None:
        """Re-arming while already armed resets the count."""
        state = InspectorState()
        state.arm(2)
        state.should_capture()  # remaining = 1
        state.arm(5)  # re-arm
        assert state.remaining == 5

    def test_pending_capture_flow(self) -> None:
        """Register a pending request, then complete with response."""
        state = InspectorState()
        cap = Capture(
            id="test-1",
            timestamp=time.time(),
            request_body={"messages": [{"role": "user", "content": "hello"}]},
        )
        state.register_pending("flow-1", cap)
        state.complete_pending(
            "flow-1",
            response_body={"usage": {"input_tokens": 10, "output_tokens": 5}},
            response_headers={"content-type": "application/json"},
        )

        assert len(state.buffer) == 1
        stored = state.buffer.get("test-1")
        assert stored is not None
        assert stored.response_body is not None
        assert stored.response_body["usage"]["input_tokens"] == 10

    def test_complete_pending_unknown_flow(self) -> None:
        """Completing an unknown flow should not crash."""
        state = InspectorState()
        state.complete_pending("unknown", {}, {})
        assert len(state.buffer) == 0

    def test_status(self) -> None:
        state = InspectorState(max_buffer_size=25)
        status = state.status()
        assert status == {
            "armed": False,
            "remaining": 0,
            "buffer_size": 0,
            "buffer_max": 25,
        }


# ---------------------------------------------------------------------------
# Payload parsing tests
# ---------------------------------------------------------------------------

class TestPayloadParsing:
    """Tests for parse_system_prompt, parse_messages, parse_usage."""

    def test_parse_system_prompt_string(self) -> None:
        result = parse_system_prompt({"system": "you are helpful"})
        assert len(result) == 1
        assert result[0]["type"] == "text"
        assert result[0]["text"] == "you are helpful"

    def test_parse_system_prompt_list(self) -> None:
        blocks = [
            {"type": "text", "text": "block 1"},
            {"type": "text", "text": "block 2"},
        ]
        result = parse_system_prompt({"system": blocks})
        assert len(result) == 2
        assert result[1]["text"] == "block 2"

    def test_parse_system_prompt_missing(self) -> None:
        result = parse_system_prompt({})
        assert result == []

    def test_parse_messages_string_content(self) -> None:
        body = {
            "messages": [
                {"role": "user", "content": "hello world"},
            ],
        }
        result = parse_messages(body)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content_bytes"] == len("hello world".encode("utf-8"))
        assert result[0]["content_types"] == ["text"]

    def test_parse_messages_list_content(self) -> None:
        body = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "thinking..."},
                        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"cmd": "ls"}},
                    ],
                },
            ],
        }
        result = parse_messages(body)
        assert len(result) == 1
        assert set(result[0]["content_types"]) == {"text", "tool_use"}

    def test_parse_messages_empty(self) -> None:
        result = parse_messages({})
        assert result == []

    def test_parse_usage_present(self) -> None:
        resp = {
            "usage": {
                "input_tokens": 1000,
                "cache_creation_input_tokens": 200,
                "cache_read_input_tokens": 500,
                "output_tokens": 150,
            },
        }
        result = parse_usage(resp)
        assert result["input_tokens"] == 1000
        assert result["cache_creation_input_tokens"] == 200
        assert result["cache_read_input_tokens"] == 500
        assert result["output_tokens"] == 150

    def test_parse_usage_missing(self) -> None:
        assert parse_usage(None) == {}
        assert parse_usage({}) == {}
        assert parse_usage({"id": "msg_123"}) == {}

    def test_build_capture_detail(self) -> None:
        cap = Capture(
            id="detail-1",
            timestamp=1000.0,
            request_body={
                "model": "claude-opus-4-20250514",
                "system": [{"type": "text", "text": "You are helpful."}],
                "messages": [
                    {"role": "user", "content": "What is 2+2?"},
                    {"role": "assistant", "content": "4"},
                ],
            },
            response_body={
                "usage": {
                    "input_tokens": 50,
                    "output_tokens": 10,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            },
        )

        detail = build_capture_detail(cap)
        assert detail["id"] == "detail-1"
        assert detail["model"] == "claude-opus-4-20250514"
        assert len(detail["system_prompt"]) == 1
        assert len(detail["messages"]) == 2
        assert detail["usage"]["input_tokens"] == 50
        assert detail["stats"]["message_count"] == 2
        assert detail["stats"]["role_counts"]["user"] == 1
        assert detail["stats"]["role_counts"]["assistant"] == 1
        assert len(detail["stats"]["largest_messages"]) == 2
        assert detail["stats"]["system_ratio_pct"] > 0
        assert "raw_request" in detail
        assert "raw_response" in detail


# ---------------------------------------------------------------------------
# Control API tests
# ---------------------------------------------------------------------------

class TestControlAPI:
    """Tests for the HTTP control API server."""

    @pytest.fixture(autouse=True)
    def setup_server(self) -> None:
        """Start a control server on a random port for each test."""
        self.state = InspectorState()
        # Use port 0 to get a random available port
        from http.server import HTTPServer
        handler = make_control_handler(self.state)
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        yield  # type: ignore[misc]

        self.server.shutdown()

    def _get(self, path: str) -> tuple[dict, int]:
        req = urllib.request.Request(f"{self.base_url}{path}")
        try:
            resp = urllib.request.urlopen(req, timeout=2)
            return json.loads(resp.read()), resp.status
        except urllib.error.HTTPError as e:
            return json.loads(e.read()), e.code

    def _post(self, path: str, data: dict | None = None) -> tuple[dict, int]:
        body = json.dumps(data or {}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=2)
            return json.loads(resp.read()), resp.status
        except urllib.error.HTTPError as e:
            return json.loads(e.read()), e.code

    def _delete(self, path: str) -> tuple[dict, int]:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            method="DELETE",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=2)
            return json.loads(resp.read()), resp.status
        except urllib.error.HTTPError as e:
            return json.loads(e.read()), e.code

    def test_get_status(self) -> None:
        data, code = self._get("/api/status")
        assert code == 200
        assert data["armed"] is False
        assert data["buffer_size"] == 0

    def test_arm_default(self) -> None:
        data, code = self._post("/api/arm")
        assert code == 200
        assert data["armed"] is True
        assert data["remaining"] == 1

    def test_arm_with_count(self) -> None:
        data, code = self._post("/api/arm", {"count": 5})
        assert code == 200
        assert data["remaining"] == 5

    def test_disarm(self) -> None:
        self._post("/api/arm", {"count": 3})
        data, code = self._post("/api/disarm")
        assert code == 200
        assert data["armed"] is False

    def test_captures_empty(self) -> None:
        data, code = self._get("/api/captures")
        assert code == 200
        assert data == []

    def test_captures_with_data(self) -> None:
        self.state.buffer.add(Capture(
            id="cap-1",
            timestamp=1000.0,
            request_body={"messages": [], "system": []},
            response_body={"usage": {}},
        ))
        data, code = self._get("/api/captures")
        assert code == 200
        assert len(data) == 1
        assert data[0]["id"] == "cap-1"

    def test_capture_detail(self) -> None:
        self.state.buffer.add(Capture(
            id="cap-2",
            timestamp=1000.0,
            request_body={
                "model": "test-model",
                "messages": [{"role": "user", "content": "hi"}],
                "system": "sys prompt",
            },
            response_body={"usage": {"input_tokens": 10, "output_tokens": 5}},
        ))
        data, code = self._get("/api/captures/cap-2")
        assert code == 200
        assert data["id"] == "cap-2"
        assert data["model"] == "test-model"
        assert len(data["messages"]) == 1

    def test_capture_detail_not_found(self) -> None:
        data, code = self._get("/api/captures/nonexistent")
        assert code == 404

    def test_clear_captures(self) -> None:
        self.state.buffer.add(Capture(
            id="cap-3",
            timestamp=1000.0,
            request_body={"messages": []},
        ))
        assert len(self.state.buffer) == 1

        data, code = self._delete("/api/captures")
        assert code == 200
        assert data["cleared"] is True
        assert len(self.state.buffer) == 0

    def test_unknown_get_endpoint(self) -> None:
        data, code = self._get("/api/unknown")
        assert code == 404

    def test_unknown_post_endpoint(self) -> None:
        data, code = self._post("/api/unknown")
        assert code == 404

    def test_unknown_delete_endpoint(self) -> None:
        data, code = self._delete("/api/unknown")
        assert code == 404


# ---------------------------------------------------------------------------
# InspectorAddon tests (mitmproxy integration)
# ---------------------------------------------------------------------------

class TestInspectorAddon:
    """Tests for the mitmproxy addon using mock flow objects."""

    def _make_flow(
        self,
        method: str = "POST",
        path: str = "/v1/messages",
        request_body: dict | None = None,
        response_body: dict | None = None,
    ) -> object:
        """Create a mock mitmproxy flow object."""
        req_body = request_body or {"messages": []}
        resp_body = response_body or {"usage": {}}

        class MockHeaders(dict):
            pass

        class MockRequest:
            def __init__(self) -> None:
                self.method = method
                self.path = path
                self.headers = MockHeaders({
                    "content-type": "application/json",
                    "authorization": "Bearer sk-test",
                })

            def get_text(self) -> str:
                return json.dumps(req_body)

        class MockResponse:
            def __init__(self) -> None:
                self.headers = MockHeaders({"content-type": "application/json"})

            def get_text(self) -> str:
                return json.dumps(resp_body)

        class MockFlow:
            def __init__(self) -> None:
                self.id = f"flow-{time.time()}"
                self.request = MockRequest()
                self.response = MockResponse()

        return MockFlow()

    def test_disarmed_no_capture(self) -> None:
        """When disarmed, no captures should occur."""
        state = InspectorState()
        addon = InspectorAddon(state=state)

        flow = self._make_flow()
        addon.request(flow)
        addon.response(flow)

        assert len(state.buffer) == 0

    def test_armed_captures_payload(self) -> None:
        """When armed, should capture the request/response pair."""
        state = InspectorState()
        addon = InspectorAddon(state=state)

        state.arm(1)
        flow = self._make_flow(
            request_body={
                "model": "claude-opus-4-20250514",
                "messages": [{"role": "user", "content": "test"}],
                "system": "be helpful",
            },
            response_body={
                "usage": {"input_tokens": 50, "output_tokens": 10},
            },
        )
        addon.request(flow)
        addon.response(flow)

        assert len(state.buffer) == 1
        # Should have auto-disarmed
        assert not state.armed

    def test_captures_exact_count(self) -> None:
        """Arming for N captures stores exactly N payloads."""
        state = InspectorState()
        addon = InspectorAddon(state=state)

        state.arm(2)

        for i in range(4):
            flow = self._make_flow(
                request_body={"messages": [{"role": "user", "content": f"msg {i}"}]},
            )
            addon.request(flow)
            addon.response(flow)

        # Only 2 should be captured
        assert len(state.buffer) == 2

    def test_ignores_non_post(self) -> None:
        """Non-POST requests should be ignored."""
        state = InspectorState()
        addon = InspectorAddon(state=state)
        state.arm(1)

        flow = self._make_flow(method="GET")
        addon.request(flow)
        # Should still be armed — nothing consumed
        assert state.armed

    def test_ignores_non_messages_path(self) -> None:
        """Requests to paths other than /v1/messages should be ignored."""
        state = InspectorState()
        addon = InspectorAddon(state=state)
        state.arm(1)

        flow = self._make_flow(path="/v1/completions")
        addon.request(flow)
        assert state.armed

    def test_strips_authorization_header(self) -> None:
        """Auth headers should be stripped from captured requests."""
        state = InspectorState()
        addon = InspectorAddon(state=state)
        state.arm(1)

        flow = self._make_flow()
        addon.request(flow)
        addon.response(flow)

        cap = list(state.buffer._buffer)[0]
        assert "authorization" not in cap.request_headers
        assert "Authorization" not in cap.request_headers

    def test_disarm_cancels_armed(self) -> None:
        """Disarming mid-capture should stop further captures."""
        state = InspectorState()
        addon = InspectorAddon(state=state)

        state.arm(5)
        # Capture 2
        for _ in range(2):
            flow = self._make_flow()
            addon.request(flow)
            addon.response(flow)

        assert len(state.buffer) == 2

        # Disarm
        state.disarm()

        # Try to capture more — should not work
        for _ in range(3):
            flow = self._make_flow()
            addon.request(flow)
            addon.response(flow)

        assert len(state.buffer) == 2
