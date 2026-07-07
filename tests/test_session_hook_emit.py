"""S1.7 / #857 — session hook: settings wiring + flightdeck-session-emit.sh.

Verifies the Stop / SessionEnd / SessionStart hooks are wired in
config/settings.template.json and that scripts/flightdeck-session-emit.sh emits
a correctly-typed session event for each phase (open/idle/close), fire-and-forget
(always exit 0, buffer-only offline).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "flightdeck-session-emit.sh"
_SETTINGS = _REPO / "config" / "settings.template.json"
_SRC = str(_REPO / "src")


def _run(phase: str, events_path: Path, stdin: str = ""):
    env = os.environ.copy()
    env["PYTHONPATH"] = _SRC + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["FLIGHTDECK_EVENTS_PATH"] = str(events_path)
    env["FLIGHTDECK_EMIT_CMD"] = "python3 -m wave_status.events.emit"
    env["FLIGHTDECK_SESSION_ID"] = "sess-abc"
    env.pop("FLIGHTDECK_INGEST_URL", None)
    return subprocess.run(
        ["bash", str(_SCRIPT), phase],
        input=stdin, capture_output=True, text=True, env=env,
    )


def _last_event(events_path: Path) -> dict:
    lines = events_path.read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])


class TestScriptEmits:
    @pytest.mark.parametrize(
        "phase,kind",
        [("open", "activity_start"), ("idle", "step"), ("close", "activity_end")],
    )
    def test_phase_maps_to_kind(self, tmp_path, phase, kind):
        ep = tmp_path / "events.jsonl"
        r = _run(phase, ep)
        assert r.returncode == 0, r.stderr
        ev = _last_event(ep)
        assert ev["kind"] == kind
        assert ev["activityId"] == "session:sess-abc"
        assert ev["label"] == f"session-{phase}"
        assert ev["phase"] == "session"

    def test_default_phase_is_idle(self, tmp_path):
        ep = tmp_path / "events.jsonl"
        env = os.environ.copy()
        env["PYTHONPATH"] = _SRC
        env["FLIGHTDECK_EVENTS_PATH"] = str(ep)
        env["FLIGHTDECK_EMIT_CMD"] = "python3 -m wave_status.events.emit"
        env["FLIGHTDECK_SESSION_ID"] = "s"
        env.pop("FLIGHTDECK_INGEST_URL", None)
        r = subprocess.run(["bash", str(_SCRIPT)], input="", capture_output=True, text=True, env=env)
        assert r.returncode == 0
        assert _last_event(ep)["kind"] == "step"

    def test_session_id_from_stdin_json(self, tmp_path):
        ep = tmp_path / "events.jsonl"
        env = os.environ.copy()
        env["PYTHONPATH"] = _SRC
        env["FLIGHTDECK_EVENTS_PATH"] = str(ep)
        env["FLIGHTDECK_EMIT_CMD"] = "python3 -m wave_status.events.emit"
        env.pop("FLIGHTDECK_SESSION_ID", None)
        env.pop("FLIGHTDECK_INGEST_URL", None)
        # Claude Code passes the hook payload as JSON on stdin.
        payload = json.dumps({"session_id": "from-stdin", "hook_event_name": "Stop"})
        r = subprocess.run(
            ["bash", str(_SCRIPT), "idle"],
            input=payload, capture_output=True, text=True, env=env,
        )
        assert r.returncode == 0
        # jq may or may not be installed; if present the stdin id wins.
        act = _last_event(ep)["activityId"]
        if _has_jq():
            assert act == "session:from-stdin"
        else:
            assert act.startswith("session:")

    def test_always_exits_zero_even_on_emit_failure(self, tmp_path):
        ep = tmp_path / "events.jsonl"
        env = os.environ.copy()
        env["FLIGHTDECK_EVENTS_PATH"] = str(ep)
        env["FLIGHTDECK_EMIT_CMD"] = "false"  # force the emit command to fail
        env["FLIGHTDECK_SESSION_ID"] = "s"
        env.pop("FLIGHTDECK_INGEST_URL", None)
        r = subprocess.run(["bash", str(_SCRIPT), "idle"], input="", capture_output=True, text=True, env=env)
        assert r.returncode == 0  # fire-and-forget: a hook must never fail a turn


def _has_jq() -> bool:
    from shutil import which
    return which("jq") is not None


class TestSettingsWiring:
    def _hooks(self) -> dict:
        return json.loads(_SETTINGS.read_text(encoding="utf-8"))["hooks"]

    def _commands(self, event: str) -> list[str]:
        cmds: list[str] = []
        for block in self._hooks().get(event, []):
            for h in block.get("hooks", []):
                cmds.append(h.get("command", ""))
        return cmds

    def test_stop_wires_idle(self):
        assert any("flightdeck-session-emit.sh idle" in c for c in self._commands("Stop"))

    def test_session_end_wires_close(self):
        assert any("flightdeck-session-emit.sh close" in c for c in self._commands("SessionEnd"))

    def test_session_start_wires_open(self):
        assert any("flightdeck-session-emit.sh open" in c for c in self._commands("SessionStart"))

    def test_existing_stop_hooks_preserved(self):
        # Additive: the precheck-asking + stop-action-bias + stall-guard hooks
        # must remain wired (we only appended).
        cmds = " ".join(self._commands("Stop"))
        assert "precheck-asking-detector.sh" in cmds
        assert "stop-action-bias-detector.sh" in cmds
        assert "wavemachine_active" in cmds  # the stall-guard inline command
