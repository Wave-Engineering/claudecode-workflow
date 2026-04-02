"""Flask web UI for the context window inspector.

Provides a dashboard for arming/disarming capture and browsing captured
API payloads. Communicates with the mitmproxy addon via its control API.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import requests
from flask import Flask, jsonify, render_template, request, Response


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONTROL_API = os.environ.get("CC_INSPECTOR_CONTROL_URL", "http://127.0.0.1:8001")

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proxy_get(path: str) -> tuple[dict[str, Any] | list, int]:
    """GET from the control API, returning (data, status_code)."""
    try:
        resp = requests.get(f"{CONTROL_API}{path}", timeout=2)
        return resp.json(), resp.status_code
    except requests.ConnectionError:
        return {"error": "proxy not connected"}, 503
    except Exception as exc:
        return {"error": str(exc)}, 500


def _proxy_post(path: str, data: dict | None = None) -> tuple[dict[str, Any], int]:
    """POST to the control API."""
    try:
        resp = requests.post(f"{CONTROL_API}{path}", json=data or {}, timeout=2)
        return resp.json(), resp.status_code
    except requests.ConnectionError:
        return {"error": "proxy not connected"}, 503
    except Exception as exc:
        return {"error": str(exc)}, 500


def _proxy_delete(path: str) -> tuple[dict[str, Any], int]:
    """DELETE on the control API."""
    try:
        resp = requests.delete(f"{CONTROL_API}{path}", timeout=2)
        return resp.json(), resp.status_code
    except requests.ConnectionError:
        return {"error": "proxy not connected"}, 503
    except Exception as exc:
        return {"error": str(exc)}, 500


def _format_timestamp(ts: float) -> str:
    """Format a Unix timestamp for display."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def _human_bytes(n: int) -> str:
    """Format byte count for display."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


# ---------------------------------------------------------------------------
# Template context
# ---------------------------------------------------------------------------

@app.context_processor
def utility_processor() -> dict:
    return {
        "format_timestamp": _format_timestamp,
        "human_bytes": _human_bytes,
    }


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard() -> str:
    """Dashboard page — proxy status, arm/disarm, capture list."""
    status_data, status_code = _proxy_get("/api/status")
    captures_data, _ = _proxy_get("/api/captures")

    connected = status_code != 503
    if not isinstance(captures_data, list):
        captures_data = []

    return render_template(
        "dashboard.html",
        connected=connected,
        status=status_data if connected else {},
        captures=captures_data,
    )


@app.route("/capture/<capture_id>")
def capture_detail(capture_id: str) -> str:
    """Capture detail page — full payload inspection."""
    data, status_code = _proxy_get(f"/api/captures/{capture_id}")

    if status_code == 404:
        return render_template("not_found.html", message="Capture not found"), 404
    if status_code == 503:
        return render_template("not_found.html", message="Proxy not connected"), 503

    return render_template("capture.html", capture=data)


# ---------------------------------------------------------------------------
# API proxy routes (so the frontend JS can call them without CORS issues)
# ---------------------------------------------------------------------------

@app.route("/api/arm", methods=["POST"])
def api_arm() -> tuple[Response, int]:
    body = request.get_json(silent=True) or {}
    data, code = _proxy_post("/api/arm", body)
    return jsonify(data), code


@app.route("/api/disarm", methods=["POST"])
def api_disarm() -> tuple[Response, int]:
    data, code = _proxy_post("/api/disarm")
    return jsonify(data), code


@app.route("/api/status")
def api_status() -> tuple[Response, int]:
    data, code = _proxy_get("/api/status")
    return jsonify(data), code


@app.route("/api/captures")
def api_captures() -> tuple[Response, int]:
    data, code = _proxy_get("/api/captures")
    return jsonify(data), code


@app.route("/api/captures/<capture_id>")
def api_capture_detail(capture_id: str) -> tuple[Response, int]:
    data, code = _proxy_get(f"/api/captures/{capture_id}")
    return jsonify(data), code


@app.route("/api/captures/<capture_id>/export")
def api_capture_export(capture_id: str) -> tuple[Response, int]:
    """Export a capture as a downloadable JSON file."""
    data, code = _proxy_get(f"/api/captures/{capture_id}")
    if code != 200:
        return jsonify(data), code

    # Build export: raw request + response
    export = {
        "id": data.get("id"),
        "timestamp": data.get("timestamp"),
        "model": data.get("model"),
        "request": data.get("raw_request"),
        "response": data.get("raw_response"),
    }

    response = Response(
        json.dumps(export, indent=2),
        mimetype="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="capture-{capture_id[:8]}.json"',
        },
    )
    return response, 200


@app.route("/api/captures", methods=["DELETE"])
def api_clear_captures() -> tuple[Response, int]:
    data, code = _proxy_delete("/api/captures")
    return jsonify(data), code


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("CC_INSPECTOR_UI_PORT", 8002))
    print(f"Inspector UI running at http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
