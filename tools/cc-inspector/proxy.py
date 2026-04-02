"""mitmproxy addon for selective API payload capture.

Intercepts /v1/messages POST requests and responses between Claude Code
and the Anthropic API. When disarmed (default), all traffic passes through
untouched. When armed, captures the next N request/response pairs to an
in-memory ring buffer.

Also exposes a small HTTP control API on a configurable port (default 8001)
for the Flask UI to interact with.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Capture:
    """A captured API request/response pair."""

    id: str
    timestamp: float
    request_body: dict[str, Any]
    response_body: dict[str, Any] | None = None
    request_headers: dict[str, str] = field(default_factory=dict)
    response_headers: dict[str, str] = field(default_factory=dict)


class CaptureBuffer:
    """Thread-safe ring buffer for captured payloads.

    Parameters
    ----------
    max_size:
        Maximum number of captures to retain. Oldest are evicted first (FIFO).
    """

    def __init__(self, max_size: int = 50) -> None:
        self._max_size = max_size
        self._buffer: deque[Capture] = deque(maxlen=max_size)
        self._lock = threading.Lock()

    @property
    def max_size(self) -> int:
        return self._max_size

    def add(self, capture: Capture) -> None:
        with self._lock:
            self._buffer.append(capture)

    def list_metadata(self) -> list[dict[str, Any]]:
        """Return metadata-only summaries (no full payloads)."""
        with self._lock:
            result = []
            for cap in self._buffer:
                usage = {}
                if cap.response_body and "usage" in cap.response_body:
                    usage = cap.response_body["usage"]

                messages = cap.request_body.get("messages", [])
                system = cap.request_body.get("system", [])

                result.append({
                    "id": cap.id,
                    "timestamp": cap.timestamp,
                    "message_count": len(messages),
                    "system_blocks": len(system) if isinstance(system, list) else (1 if system else 0),
                    "usage": usage,
                })
            return result

    def get(self, capture_id: str) -> Capture | None:
        with self._lock:
            for cap in self._buffer:
                if cap.id == capture_id:
                    return cap
            return None

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)


class InspectorState:
    """Shared state for the inspector proxy.

    Thread-safe — accessed by mitmproxy threads and the control API server.
    """

    def __init__(self, max_buffer_size: int = 50) -> None:
        self._lock = threading.Lock()
        self._armed = False
        self._remaining = 0
        self.buffer = CaptureBuffer(max_size=max_buffer_size)
        # Tracks in-flight requests by flow id
        self._pending: dict[str, Capture] = {}

    @property
    def armed(self) -> bool:
        with self._lock:
            return self._armed

    @property
    def remaining(self) -> int:
        with self._lock:
            return self._remaining

    def arm(self, count: int = 1) -> None:
        """Arm capture for the next *count* payloads."""
        with self._lock:
            self._armed = True
            self._remaining = max(1, count)

    def disarm(self) -> None:
        """Cancel armed state."""
        with self._lock:
            self._armed = False
            self._remaining = 0

    def should_capture(self) -> bool:
        """Check if we should capture and decrement the counter."""
        with self._lock:
            if not self._armed or self._remaining <= 0:
                return False
            self._remaining -= 1
            if self._remaining <= 0:
                self._armed = False
            return True

    def register_pending(self, flow_id: str, capture: Capture) -> None:
        """Register a captured request waiting for its response."""
        with self._lock:
            self._pending[flow_id] = capture

    def complete_pending(self, flow_id: str, response_body: dict[str, Any],
                         response_headers: dict[str, str]) -> None:
        """Attach response to a pending capture and move it to the buffer."""
        with self._lock:
            cap = self._pending.pop(flow_id, None)
        if cap is not None:
            cap.response_body = response_body
            cap.response_headers = response_headers
            self.buffer.add(cap)

    def status(self) -> dict[str, Any]:
        """Return current status as a dict."""
        return {
            "armed": self.armed,
            "remaining": self.remaining,
            "buffer_size": len(self.buffer),
            "buffer_max": self.buffer.max_size,
        }


# ---------------------------------------------------------------------------
# Payload parsing helpers
# ---------------------------------------------------------------------------

def parse_system_prompt(request_body: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract system prompt blocks from the request body.

    The Anthropic API accepts ``system`` as either a string or a list of
    content blocks.
    """
    system = request_body.get("system", [])
    if isinstance(system, str):
        return [{"type": "text", "text": system}]
    if isinstance(system, list):
        return system
    return []


def parse_messages(request_body: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract and annotate messages from the request body."""
    messages = request_body.get("messages", [])
    result = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        # Compute size info
        if isinstance(content, str):
            content_bytes = len(content.encode("utf-8"))
            content_types = ["text"]
        elif isinstance(content, list):
            content_bytes = len(json.dumps(content).encode("utf-8"))
            content_types = list({block.get("type", "unknown") for block in content if isinstance(block, dict)})
        else:
            content_bytes = len(json.dumps(content).encode("utf-8"))
            content_types = ["unknown"]

        result.append({
            "role": role,
            "content": content,
            "content_bytes": content_bytes,
            "estimated_tokens": max(1, content_bytes // 4),  # rough estimate
            "content_types": content_types,
        })
    return result


def parse_usage(response_body: dict[str, Any] | None) -> dict[str, int]:
    """Extract token usage breakdown from the API response."""
    if not response_body or "usage" not in response_body:
        return {}
    usage = response_body["usage"]
    return {
        "input_tokens": usage.get("input_tokens", 0),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
    }


def build_capture_detail(capture: Capture) -> dict[str, Any]:
    """Build a full detail view of a capture for the UI."""
    system_blocks = parse_system_prompt(capture.request_body)
    messages = parse_messages(capture.request_body)
    usage = parse_usage(capture.response_body)

    # Compute stats
    system_bytes = sum(
        len(b.get("text", "").encode("utf-8")) if isinstance(b, dict) else 0
        for b in system_blocks
    )
    message_bytes = sum(m["content_bytes"] for m in messages)

    # Role breakdown
    role_counts: dict[str, int] = {}
    for m in messages:
        role_counts[m["role"]] = role_counts.get(m["role"], 0) + 1

    # Top 5 largest messages
    sorted_msgs = sorted(messages, key=lambda m: m["content_bytes"], reverse=True)
    largest = [
        {
            "index": messages.index(m),
            "role": m["role"],
            "content_bytes": m["content_bytes"],
            "estimated_tokens": m["estimated_tokens"],
        }
        for m in sorted_msgs[:5]
    ]

    total_bytes = system_bytes + message_bytes
    system_ratio = (system_bytes / total_bytes * 100) if total_bytes > 0 else 0

    return {
        "id": capture.id,
        "timestamp": capture.timestamp,
        "model": capture.request_body.get("model", "unknown"),
        "system_prompt": system_blocks,
        "system_bytes": system_bytes,
        "messages": messages,
        "message_bytes": message_bytes,
        "usage": usage,
        "stats": {
            "message_count": len(messages),
            "role_counts": role_counts,
            "largest_messages": largest,
            "system_ratio_pct": round(system_ratio, 1),
            "total_payload_bytes": total_bytes,
        },
        "raw_request": capture.request_body,
        "raw_response": capture.response_body,
    }


# ---------------------------------------------------------------------------
# Control API HTTP server
# ---------------------------------------------------------------------------

def make_control_handler(state: InspectorState) -> type:
    """Create an HTTP request handler class bound to the given state."""

    class ControlHandler(BaseHTTPRequestHandler):
        """HTTP handler for the inspector control API."""

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            """Suppress default logging."""
            pass

        def _send_json(self, data: Any, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))

        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length", 0))
            return self.rfile.read(length) if length > 0 else b""

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/api/status":
                self._send_json(state.status())
            elif self.path == "/api/captures":
                self._send_json(state.buffer.list_metadata())
            elif self.path.startswith("/api/captures/"):
                capture_id = self.path.split("/api/captures/", 1)[1]
                cap = state.buffer.get(capture_id)
                if cap is None:
                    self._send_json({"error": "not found"}, 404)
                else:
                    self._send_json(build_capture_detail(cap))
            else:
                self._send_json({"error": "not found"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/api/arm":
                body = self._read_body()
                count = 1
                if body:
                    try:
                        data = json.loads(body)
                        count = int(data.get("count", 1))
                    except (json.JSONDecodeError, ValueError, TypeError):
                        pass
                state.arm(count)
                self._send_json(state.status())
            elif self.path == "/api/disarm":
                state.disarm()
                self._send_json(state.status())
            else:
                self._send_json({"error": "not found"}, 404)

        def do_DELETE(self) -> None:  # noqa: N802
            if self.path == "/api/captures":
                state.buffer.clear()
                self._send_json({"cleared": True})
            else:
                self._send_json({"error": "not found"}, 404)

    return ControlHandler


def start_control_server(state: InspectorState, port: int = 8001) -> HTTPServer:
    """Start the control API server in a background thread."""
    handler = make_control_handler(state)
    server = HTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# ---------------------------------------------------------------------------
# mitmproxy addon
# ---------------------------------------------------------------------------

class InspectorAddon:
    """mitmproxy addon that intercepts /v1/messages traffic.

    When armed, captures request/response pairs to the shared state buffer.
    When disarmed, passes all traffic through untouched.
    """

    def __init__(self, state: InspectorState | None = None,
                 control_port: int = 8001) -> None:
        self.state = state or InspectorState()
        self._control_server: HTTPServer | None = None
        self._control_port = control_port

    def load(self, loader: Any) -> None:
        """Called when the addon is loaded by mitmproxy."""
        self._control_server = start_control_server(
            self.state, self._control_port
        )

    def request(self, flow: Any) -> None:
        """Called for each intercepted request."""
        # Only intercept POST /v1/messages
        if flow.request.method != "POST":
            return
        if "/v1/messages" not in flow.request.path:
            return

        if not self.state.should_capture():
            return

        try:
            body = json.loads(flow.request.get_text())
        except (json.JSONDecodeError, ValueError):
            return

        headers = dict(flow.request.headers)
        # Strip authorization for safety
        headers.pop("authorization", None)
        headers.pop("Authorization", None)

        capture = Capture(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            request_body=body,
            request_headers=headers,
        )

        self.state.register_pending(flow.id, capture)

    def response(self, flow: Any) -> None:
        """Called for each intercepted response."""
        if flow.request.method != "POST":
            return
        if "/v1/messages" not in flow.request.path:
            return

        try:
            body = json.loads(flow.response.get_text())
        except (json.JSONDecodeError, ValueError):
            body = {}

        headers = dict(flow.response.headers)

        self.state.complete_pending(flow.id, body, headers)

    def done(self) -> None:
        """Called when mitmproxy shuts down."""
        if self._control_server:
            self._control_server.shutdown()


# ---------------------------------------------------------------------------
# mitmproxy entrypoint — instantiate the addon when loaded as a script
# ---------------------------------------------------------------------------

_state = InspectorState()
addons = [InspectorAddon(state=_state)]
