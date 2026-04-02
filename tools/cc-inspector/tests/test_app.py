"""Tests for the Flask web UI application.

Tests exercise real Flask routes. The control API (external boundary) is
mocked via responses or by running a real control server in-process.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import HTTPServer
from unittest.mock import patch

import pytest

# Allow importing from the tools/cc-inspector directory
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from proxy import (
    Capture,
    InspectorState,
    make_control_handler,
    build_capture_detail,
)
from app import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def state() -> InspectorState:
    """Fresh inspector state for each test."""
    return InspectorState()


@pytest.fixture()
def control_server(state: InspectorState):
    """Start a real control server backed by the state fixture."""
    handler = make_control_handler(state)
    server = HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield port

    server.shutdown()


@pytest.fixture()
def client(control_server: int):
    """Flask test client wired to a real control server."""
    app.config["TESTING"] = True
    with patch("app.CONTROL_API", f"http://127.0.0.1:{control_server}"):
        with app.test_client() as c:
            yield c


@pytest.fixture()
def disconnected_client():
    """Flask test client with no backend (proxy disconnected)."""
    app.config["TESTING"] = True
    # Point to a port nothing is listening on
    with patch("app.CONTROL_API", "http://127.0.0.1:19999"):
        with app.test_client() as c:
            yield c


# ---------------------------------------------------------------------------
# Dashboard tests
# ---------------------------------------------------------------------------

class TestDashboard:
    """Tests for the dashboard page and API proxy routes."""

    def test_dashboard_renders(self, client) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"CC Inspector" in resp.data

    def test_dashboard_shows_connected(self, client) -> None:
        resp = client.get("/")
        assert b"Connected" in resp.data

    def test_dashboard_disconnected(self, disconnected_client) -> None:
        resp = disconnected_client.get("/")
        assert resp.status_code == 200
        assert b"Disconnected" in resp.data

    def test_api_status(self, client) -> None:
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["armed"] is False
        assert data["buffer_size"] == 0

    def test_api_arm(self, client) -> None:
        resp = client.post(
            "/api/arm",
            data=json.dumps({"count": 3}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["armed"] is True
        assert data["remaining"] == 3

    def test_api_disarm(self, client) -> None:
        # Arm first
        client.post("/api/arm", data=json.dumps({"count": 5}),
                     content_type="application/json")
        # Then disarm
        resp = client.post("/api/disarm")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["armed"] is False

    def test_api_captures_empty(self, client) -> None:
        resp = client.get("/api/captures")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_api_captures_with_data(self, client, state: InspectorState) -> None:
        state.buffer.add(Capture(
            id="test-cap",
            timestamp=1000.0,
            request_body={"messages": [{"role": "user", "content": "hi"}], "system": []},
            response_body={"usage": {"input_tokens": 10}},
        ))

        resp = client.get("/api/captures")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["id"] == "test-cap"

    def test_api_clear_captures(self, client, state: InspectorState) -> None:
        state.buffer.add(Capture(
            id="to-clear",
            timestamp=1000.0,
            request_body={"messages": []},
        ))
        resp = client.delete("/api/captures")
        assert resp.status_code == 200
        assert resp.get_json()["cleared"] is True
        assert len(state.buffer) == 0

    def test_api_status_disconnected(self, disconnected_client) -> None:
        resp = disconnected_client.get("/api/status")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Capture detail tests
# ---------------------------------------------------------------------------

class TestCaptureDetail:
    """Tests for the capture detail page and export."""

    def _add_sample_capture(self, state: InspectorState) -> str:
        """Add a sample capture and return its id."""
        cap_id = "detail-test-1"
        state.buffer.add(Capture(
            id=cap_id,
            timestamp=1000.0,
            request_body={
                "model": "claude-opus-4-20250514",
                "system": [{"type": "text", "text": "You are a helpful assistant."}],
                "messages": [
                    {"role": "user", "content": "What is 2+2?"},
                    {"role": "assistant", "content": [
                        {"type": "text", "text": "The answer is 4."},
                    ]},
                ],
            },
            response_body={
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cache_creation_input_tokens": 50,
                    "cache_read_input_tokens": 0,
                },
            },
        ))
        return cap_id

    def test_capture_detail_page(self, client, state: InspectorState) -> None:
        cap_id = self._add_sample_capture(state)
        resp = client.get(f"/capture/{cap_id}")
        assert resp.status_code == 200
        assert b"claude-opus-4-20250514" in resp.data
        # System prompt should be visible
        assert b"You are a helpful assistant." in resp.data
        # Messages should be present
        assert b"What is 2+2?" in resp.data

    def test_capture_detail_not_found(self, client) -> None:
        resp = client.get("/capture/nonexistent")
        assert resp.status_code == 404
        assert b"Capture not found" in resp.data

    def test_capture_detail_api(self, client, state: InspectorState) -> None:
        cap_id = self._add_sample_capture(state)
        resp = client.get(f"/api/captures/{cap_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["model"] == "claude-opus-4-20250514"
        assert len(data["messages"]) == 2
        assert data["usage"]["input_tokens"] == 100
        assert data["stats"]["message_count"] == 2
        assert data["stats"]["role_counts"]["user"] == 1

    def test_capture_detail_shows_token_breakdown(self, client, state: InspectorState) -> None:
        cap_id = self._add_sample_capture(state)
        resp = client.get(f"/capture/{cap_id}")
        assert resp.status_code == 200
        # Token usage labels should be in the sidebar
        assert b"Input" in resp.data
        assert b"Cache Create" in resp.data
        assert b"Cache Read" in resp.data
        assert b"Output" in resp.data

    def test_capture_detail_shows_message_types(self, client, state: InspectorState) -> None:
        """Messages with different content types should show appropriate badges."""
        state.buffer.add(Capture(
            id="types-test",
            timestamp=1000.0,
            request_body={
                "model": "test",
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}},
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": "t1", "content": "file.txt"},
                        ],
                    },
                ],
            },
            response_body={"usage": {}},
        ))
        resp = client.get("/capture/types-test")
        assert resp.status_code == 200
        assert b"tool_use" in resp.data
        assert b"tool_result" in resp.data

    def test_export_json(self, client, state: InspectorState) -> None:
        cap_id = self._add_sample_capture(state)
        resp = client.get(f"/api/captures/{cap_id}/export")
        assert resp.status_code == 200
        assert resp.content_type == "application/json"
        assert "attachment" in resp.headers.get("Content-Disposition", "")

        data = json.loads(resp.data)
        assert data["id"] == cap_id
        assert "request" in data
        assert "response" in data
        assert data["request"]["model"] == "claude-opus-4-20250514"

    def test_export_not_found(self, client) -> None:
        resp = client.get("/api/captures/nonexistent/export")
        assert resp.status_code == 404

    def test_capture_detail_disconnected(self, disconnected_client) -> None:
        resp = disconnected_client.get("/capture/any-id")
        assert resp.status_code == 503
