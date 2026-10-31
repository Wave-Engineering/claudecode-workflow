#!/usr/bin/env python3
"""claude-openai-shim.py — serve OpenAI chat.completions from `claude -p`, for the Job D bench (#1195).

The golden-comment benchmark's extract, dedup and judge steps call an OpenAI-compatible
endpoint (`MARTIAN_BASE_URL`). This shim answers that endpoint with headless `claude -p`, so the
judge runs on the same subscription as the reviewer arms: no API key and no API spend. It
stays one fixed model for every arm, named in every result.

Each call runs `claude -p` with its tools, MCP servers, user settings (so hooks), slash commands
and session persistence switched off, and the request's system message in place of Claude
Code's own. Measured on 2026-10-31: 676 input tokens, $0.004 and about 4 s for a judge call.
Not `--bare`, which accepts only API-key auth.

Concurrency is capped (`--workers`), because each `claude -p` is a process with its own memory
on a shared host. The cap is the shim's, not upstream's: the benchmark fires 30 to 50 calls at
once.

Every call appends one line to the ledger (`--ledger`): the model, the CLI's own
`total_cost_usd`, token usage and wall-clock. That is the judge's measured cost.

Usage:
    claude-openai-shim.py --model claude-sonnet-5-5 [--port 0] [--workers 6] [--ledger <path>]
        Prints `listening http://127.0.0.1:<port>/v1`, then serves until killed. Point the
        benchmark at it: MARTIAN_BASE_URL=<that url> MARTIAN_API_KEY=unused MARTIAN_MODEL=<model>.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

CLAUDE_FLAGS = [
    "--setting-sources", "",
    "--strict-mcp-config",
    "--tools", "",
    "--disable-slash-commands",
    "--no-session-persistence",
    "--output-format", "json",
]


class ShimError(Exception):
    """A request the shim refuses (400) or a `claude -p` run that failed (502)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def split_messages(messages: Any) -> tuple[str, str]:
    """The system prompt and the user text from an OpenAI `messages` list.

    System messages join into the system prompt; user messages join into the prompt. Anything
    else is refused: the benchmark sends one system and one user message, and a shim that
    silently dropped an assistant turn would answer a different question.
    """
    if not isinstance(messages, list) or not messages:
        raise ShimError(400, "messages must be a non-empty list")
    system: list[str] = []
    user: list[str] = []
    for m in messages:
        if not isinstance(m, dict) or not isinstance(m.get("content"), str):
            raise ShimError(400, "each message needs a string content")
        role = m.get("role")
        if role == "system":
            system.append(m["content"])
        elif role == "user":
            user.append(m["content"])
        else:
            raise ShimError(400, f"unsupported role: {role!r}")
    if not user:
        raise ShimError(400, "no user message")
    return "\n\n".join(system), "\n\n".join(user)


def claude_argv(model: str, system: str) -> list[str]:
    argv = ["claude", "-p", "--model", model, *CLAUDE_FLAGS]
    if system:
        argv += ["--system-prompt", system]
    return argv


def completion(req: dict[str, Any], model: str, run=subprocess.run) -> tuple[dict[str, Any], dict[str, Any]]:
    """Answer one chat.completions request. Returns (response body, ledger record).

    The shim's model is fixed: a request naming another one is refused, so a misconfigured
    MARTIAN_MODEL can never quietly change the judge.
    """
    asked = req.get("model")
    if asked not in (None, model):
        raise ShimError(400, f"this shim serves {model}, not {asked}")
    system, prompt = split_messages(req.get("messages"))
    start = time.monotonic()
    proc = run(claude_argv(model, system), input=prompt, capture_output=True, text=True, timeout=300)
    wall = round(time.monotonic() - start, 3)
    if proc.returncode != 0:
        raise ShimError(502, f"claude -p exited {proc.returncode}: {proc.stderr.strip()[:500]}")
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise ShimError(502, f"claude -p printed no JSON: {e}") from e
    if out.get("is_error") or not isinstance(out.get("result"), str):
        raise ShimError(502, f"claude -p reported an error: {str(out.get('result'))[:500]}")
    usage = out.get("usage") or {}
    prompt_tokens = sum(int(usage.get(k) or 0) for k in (
        "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    completion_tokens = int(usage.get("output_tokens") or 0)
    body = {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": out["result"]},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": model,
        "total_cost_usd": out.get("total_cost_usd"),
        "usage": usage,
        "wall_s": wall,
        "duration_ms": out.get("duration_ms"),
    }
    return body, record


def make_handler(model: str, workers: threading.BoundedSemaphore, ledger: str | None):
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # stderr stays for errors only
            pass

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:  # noqa: N802 (http.server's name)
            if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
                self._send(404, {"error": {"message": f"no route {self.path}"}})
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
                req = json.loads(self.rfile.read(n) or b"{}")
                with workers:
                    body, record = completion(req, model)
            except ShimError as e:
                print(f"claude-openai-shim: {e.status} {e}", file=sys.stderr)
                self._send(e.status, {"error": {"message": str(e)}})
                return
            except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
                self._send(400 if isinstance(e, json.JSONDecodeError) else 504, {"error": {"message": str(e)}})
                return
            if ledger:
                with lock, open(ledger, "a") as f:
                    f.write(json.dumps(record) + "\n")
            self._send(200, body)

    return Handler


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--model", required=True)
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--ledger")
    a = p.parse_args(argv)
    server = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(
        a.model, threading.BoundedSemaphore(a.workers), a.ledger))
    print(f"listening http://127.0.0.1:{server.server_address[1]}/v1", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
