"""scripts/bench/claude-openai-shim.py: the OpenAI-shaped judge endpoint over `claude -p` (#1195).

Hermetic: `completion` takes the subprocess runner as an argument, so no test starts `claude`,
binds a port or spends a model call.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

_SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "bench" / "claude-openai-shim.py")
_loader = importlib.machinery.SourceFileLoader("claude_openai_shim", _SCRIPT)
_spec = importlib.util.spec_from_file_location("claude_openai_shim", _SCRIPT, loader=_loader)
shim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shim)

MODEL = "claude-sonnet-5-5"
REQ = {
    "model": MODEL,
    "messages": [
        {"role": "system", "content": "You are a precise code review evaluator."},
        {"role": "user", "content": "Golden: X. Candidate: Y."},
    ],
    "temperature": 0.0,
}
CLI_OUT = {
    "type": "result",
    "is_error": False,
    "result": '{"reasoning": "same", "match": true, "confidence": 0.9}',
    "total_cost_usd": 0.004,
    "duration_ms": 2600,
    "usage": {"input_tokens": 2, "cache_creation_input_tokens": 676, "cache_read_input_tokens": 0,
              "output_tokens": 125},
}


class FakeRun:
    def __init__(self, stdout: str = json.dumps(CLI_OUT), returncode: int = 0, stderr: str = ""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, argv, input, **kw):  # noqa: A002 (subprocess.run's name)
        self.calls.append((argv, input))
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


def test_completion_returns_openai_shape_and_ledger_record():
    run = FakeRun()
    body, record = shim.completion(REQ, MODEL, run=run)
    assert body["object"] == "chat.completion"
    assert body["model"] == MODEL
    assert body["choices"][0]["message"] == {"role": "assistant", "content": CLI_OUT["result"]}
    assert body["usage"] == {"prompt_tokens": 678, "completion_tokens": 125, "total_tokens": 803}
    assert record["total_cost_usd"] == 0.004
    assert record["model"] == MODEL
    assert record["usage"] == CLI_OUT["usage"]


def test_system_message_replaces_claude_codes_prompt_and_user_text_is_stdin():
    run = FakeRun()
    shim.completion(REQ, MODEL, run=run)
    argv, stdin = run.calls[0]
    assert argv[:4] == ["claude", "-p", "--model", MODEL]
    assert argv[argv.index("--system-prompt") + 1] == "You are a precise code review evaluator."
    assert stdin == "Golden: X. Candidate: Y."


def test_every_call_runs_without_tools_mcp_hooks_or_sessions():
    run = FakeRun()
    shim.completion(REQ, MODEL, run=run)
    argv, _ = run.calls[0]
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""
    for flag in ("--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
        assert flag in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert "--bare" not in argv  # --bare takes API-key auth only: that would spend API money


def test_every_call_runs_with_claude_md_discovery_off():
    seen = {}

    def run(argv, input, **kw):  # noqa: A002 (subprocess.run's name)
        seen.update(kw["env"])
        return subprocess.CompletedProcess(argv, 0, json.dumps(CLI_OUT), "")

    shim.completion(REQ, MODEL, run=run)
    assert seen["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"


def test_a_request_for_another_model_is_refused():
    with pytest.raises(shim.ShimError) as e:
        shim.completion({**REQ, "model": "claude-opus-5-5"}, MODEL, run=FakeRun())
    assert e.value.status == 400


def test_a_request_with_no_model_uses_the_shims():
    req = {k: v for k, v in REQ.items() if k != "model"}
    body, _ = shim.completion(req, MODEL, run=FakeRun())
    assert body["model"] == MODEL


@pytest.mark.parametrize("messages", [
    [],
    "not a list",
    [{"role": "system", "content": "only a system message"}],
    [{"role": "assistant", "content": "an earlier turn"}, {"role": "user", "content": "q"}],
    [{"role": "user", "content": ["structured", "content"]}],
])
def test_bad_messages_are_refused(messages):
    with pytest.raises(shim.ShimError) as e:
        shim.completion({**REQ, "messages": messages}, MODEL, run=FakeRun())
    assert e.value.status == 400


def test_a_claude_that_cannot_start_is_a_502_not_a_dropped_connection(monkeypatch):
    """The handler, over loopback, with completion patched: no `claude` process is started."""
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    def no_claude(req, model, run=None):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(shim, "completion", no_claude)
    server = ThreadingHTTPServer(("127.0.0.1", 0), shim.make_handler(MODEL, threading.BoundedSemaphore(1), None))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
                                     data=json.dumps(REQ).encode(), method="POST")
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=10)
        assert e.value.code == 502
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("run", [
    FakeRun(returncode=1, stderr="auth failed"),
    FakeRun(stdout="not json"),
    FakeRun(stdout=json.dumps({**CLI_OUT, "is_error": True, "result": "rate limited"})),
    FakeRun(stdout=json.dumps({**CLI_OUT, "result": None})),
])
def test_a_failed_claude_run_is_a_502_never_an_empty_answer(run):
    with pytest.raises(shim.ShimError) as e:
        shim.completion(REQ, MODEL, run=run)
    assert e.value.status == 502
