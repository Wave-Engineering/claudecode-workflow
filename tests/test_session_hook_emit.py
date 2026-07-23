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
    env.pop("FLIGHTDECK_EMIT_DISABLED", None)
    return subprocess.run(
        ["bash", str(_SCRIPT), phase],
        input=stdin, capture_output=True, text=True, env=env,
    )


def _last_event(events_path: Path) -> dict:
    lines = events_path.read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])


def _has_jq() -> bool:
    from shutil import which
    return which("jq") is not None


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
        env.pop("FLIGHTDECK_EMIT_DISABLED", None)
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
        env.pop("FLIGHTDECK_EMIT_DISABLED", None)
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
        env.pop("FLIGHTDECK_EMIT_DISABLED", None)
        r = subprocess.run(["bash", str(_SCRIPT), "idle"], input="", capture_output=True, text=True, env=env)
        assert r.returncode == 0  # fire-and-forget: a hook must never fail a turn

    def test_session_events_are_presence_shaped(self, tmp_path):
        # #947 defect 1: every session event declares activityType "session" and
        # carries the hostname in its own `host` field (never as `agent` when an
        # identity exists — see TestAgentIdentity).
        ep = tmp_path / "events.jsonl"
        r = _run("idle", ep)
        assert r.returncode == 0, r.stderr
        ev = _last_event(ep)
        assert ev["activityType"] == "session"
        assert ev["host"]  # non-empty hostname

    def test_legacy_emit_cli_fallback(self, tmp_path):
        # #947 deploy-ordering: an OLDER installed emit CLI rejects the additive
        # --activity-type/--host flags (argparse exit 2). The hook must retry with
        # the legacy argument set rather than silently losing the event.
        ep = tmp_path / "events.jsonl"
        stub = tmp_path / "old-cli.sh"
        stub.write_text(
            "#!/usr/bin/env bash\n"
            'for a in "$@"; do\n'
            '  case "$a" in --activity-type|--host) echo "unrecognized arguments" >&2; exit 2 ;; esac\n'
            "done\n"
            f'exec python3 -m wave_status.events.emit "$@"\n',
            encoding="utf-8",
        )
        stub.chmod(0o755)
        env = os.environ.copy()
        env["PYTHONPATH"] = _SRC + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["FLIGHTDECK_EVENTS_PATH"] = str(ep)
        env["FLIGHTDECK_EMIT_CMD"] = f"bash {stub}"
        env["FLIGHTDECK_SESSION_ID"] = "sess-old"
        env.pop("FLIGHTDECK_INGEST_URL", None)
        env.pop("FLIGHTDECK_EMIT_DISABLED", None)
        r = subprocess.run(["bash", str(_SCRIPT), "idle"], input="", capture_output=True, text=True, env=env)
        assert r.returncode == 0
        ev = _last_event(ep)  # the event STILL landed, in the legacy shape
        assert ev["activityId"] == "session:sess-old"
        assert "activityType" not in ev


class TestAgentIdentity:
    """#947 defect 2: `agent` is the Dev-Name from .claude/agent-identity.json;
    the hostname is only the VISIBLE degradation when identity is absent."""

    def _run_with_root(self, root: Path, events_path: Path):
        env = os.environ.copy()
        env["PYTHONPATH"] = _SRC + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["FLIGHTDECK_EVENTS_PATH"] = str(events_path)
        env["FLIGHTDECK_EMIT_CMD"] = "python3 -m wave_status.events.emit"
        env.pop("FLIGHTDECK_INGEST_URL", None)
        env.pop("FLIGHTDECK_EMIT_DISABLED", None)
        env.pop("FLIGHTDECK_SESSION_ID", None)
        # Claude Code hook payload carries the project cwd.
        payload = json.dumps({"session_id": "sess-id", "cwd": str(root)})
        return subprocess.run(
            ["bash", str(_SCRIPT), "idle"],
            input=payload, capture_output=True, text=True, env=env,
        )

    @pytest.mark.skipif(not _has_jq(), reason="identity resolution requires jq")
    def test_identity_file_present_attributes_dev_name(self, tmp_path):
        root = tmp_path / "proj"
        (root / ".claude").mkdir(parents=True)
        (root / ".claude" / "agent-identity.json").write_text(
            json.dumps({"dev_team": "oaw", "dev_name": "babelfish", "dev_avatar": "🐠"}),
            encoding="utf-8",
        )
        ep = tmp_path / "events.jsonl"
        r = self._run_with_root(root, ep)
        assert r.returncode == 0, r.stderr
        ev = _last_event(ep)
        assert ev["agent"] == "babelfish"
        assert ev["host"] != "babelfish"  # hostname rides separately

    @pytest.mark.skipif(not _has_jq(), reason="identity resolution requires jq")
    def test_identity_missing_degrades_to_hostname_visibly(self, tmp_path):
        root = tmp_path / "proj-no-identity"
        root.mkdir()
        ep = tmp_path / "events.jsonl"
        r = self._run_with_root(root, ep)
        assert r.returncode == 0, r.stderr
        ev = _last_event(ep)
        assert ev["agent"] == ev["host"]  # degraded: agent IS the hostname

    @pytest.mark.skipif(not _has_jq(), reason="identity resolution requires jq")
    def test_identity_malformed_degrades_not_fails(self, tmp_path):
        root = tmp_path / "proj-bad-identity"
        (root / ".claude").mkdir(parents=True)
        (root / ".claude" / "agent-identity.json").write_text("{not json", encoding="utf-8")
        ep = tmp_path / "events.jsonl"
        r = self._run_with_root(root, ep)
        assert r.returncode == 0, r.stderr  # never fails the turn
        assert _last_event(ep)["agent"] == _last_event(ep)["host"]


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
