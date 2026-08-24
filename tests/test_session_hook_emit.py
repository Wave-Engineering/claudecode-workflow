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
        # carries the hostname in its own `host` field, never as `agent` — see
        # TestAgentIdentity (#1151: not even as a fallback when no identity
        # resolves).
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
    """#947 defect 2 / #1151 (flightdeck#38 follow-up): `agent` is the Dev-Name
    from .claude/agent-identity.json when it resolves; when it doesn't, --agent
    is OMITTED from the emit call entirely (never faked as the hostname) —
    flightdeck#38 gave the deck a real, honest degradation path for a genuinely
    absent agent, so this emitter no longer needs to manufacture one."""

    def _run_with_root(self, root: Path, events_path: Path):
        env = os.environ.copy()
        env["PYTHONPATH"] = _SRC + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["FLIGHTDECK_EVENTS_PATH"] = str(events_path)
        env["FLIGHTDECK_EMIT_CMD"] = "python3 -m wave_status.events.emit"
        env.pop("FLIGHTDECK_INGEST_URL", None)
        env.pop("FLIGHTDECK_EMIT_DISABLED", None)
        env.pop("FLIGHTDECK_SESSION_ID", None)
        # resolve_agent() checks FLIGHTDECK_AGENT BEFORE cwd (code review:
        # this helper's "no identity resolves" tests only hold today because
        # conftest.py's autouse fixture already scrubs this fleet-wide — pop
        # it here too so this helper is self-sufficient and doesn't silently
        # start depending on shell state again if that fixture ever narrows.
        env.pop("FLIGHTDECK_AGENT", None)
        # Claude Code hook payload carries the project cwd.
        payload = json.dumps({"session_id": "sess-id", "cwd": str(root)})
        return subprocess.run(
            ["bash", str(_SCRIPT), "idle"],
            input=payload, capture_output=True, text=True, env=env,
            # #1151: when --agent is omitted, emit.py's own CLI falls back to
            # resolve_agent(Path.cwd()) (cc-workflow#1163) — the SUBPROCESS's
            # cwd, not `root`. In production the hook always runs with cwd ==
            # the project root the payload names, so this matters here ONLY
            # to keep the test honest: without pinning cwd=root, this test
            # would silently resolve THIS repo checkout's own real identity
            # file (whatever the pytest runner's actual cwd happens to be)
            # instead of genuinely exercising "no identity resolves anywhere".
            cwd=root,
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
    def test_identity_missing_omits_agent_honestly(self, tmp_path):
        root = tmp_path / "proj-no-identity"
        root.mkdir()
        ep = tmp_path / "events.jsonl"
        r = self._run_with_root(root, ep)
        assert r.returncode == 0, r.stderr
        ev = _last_event(ep)
        # No fake attribution: --agent was never passed, and cwd (pinned to
        # `root` above) has no identity file either, so the CLI's own
        # auto-resolve fallback also fails — the event carries no agent key
        # at all (build_event drops it), letting flightdeck#38's real
        # unattributed rendering take over instead of a fabricated hostname.
        assert "agent" not in ev
        assert ev["host"]  # host still ships, unaffected

    @pytest.mark.skipif(not _has_jq(), reason="identity resolution requires jq")
    def test_identity_malformed_degrades_not_fails(self, tmp_path):
        root = tmp_path / "proj-bad-identity"
        (root / ".claude").mkdir(parents=True)
        (root / ".claude" / "agent-identity.json").write_text("{not json", encoding="utf-8")
        ep = tmp_path / "events.jsonl"
        r = self._run_with_root(root, ep)
        assert r.returncode == 0, r.stderr  # never fails the turn
        assert "agent" not in _last_event(ep)

    # --- code review: assert on the ACTUAL invoked argv, not just the event.
    # emit.py's own blank-normalization (cc-workflow#1146) would mask a
    # regression to `agent_args=(--agent "$agent")` unconditionally (no `[ -n
    # "$agent" ]` guard) — that regression would send `--agent ""`, and the
    # RESULTING event still carries no `agent` key (emit() drops the
    # normalized-away field), so the tests above alone cannot catch it. These
    # record the real command line, reusing test_legacy_emit_cli_fallback's
    # stub pattern.

    def _run_recording(self, root: Path, tmp_path: Path, *, reject_extra: bool):
        log = tmp_path / "argv.log"
        stub = tmp_path / "record-cli.sh"
        body = "#!/usr/bin/env bash\n" f"printf '%s\\n' \"$@\" >> {log}\n" f'printf -- "---\\n" >> {log}\n'
        if reject_extra:
            body += (
                'for a in "$@"; do\n'
                '  case "$a" in --activity-type|--host) echo "unrecognized arguments" >&2; exit 2 ;; esac\n'
                "done\n"
            )
        body += 'exec python3 -m wave_status.events.emit "$@"\n'
        stub.write_text(body, encoding="utf-8")
        stub.chmod(0o755)
        ep = tmp_path / "events.jsonl"
        env = os.environ.copy()
        env["PYTHONPATH"] = _SRC + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["FLIGHTDECK_EVENTS_PATH"] = str(ep)
        env["FLIGHTDECK_EMIT_CMD"] = f"bash {stub}"
        env.pop("FLIGHTDECK_INGEST_URL", None)
        env.pop("FLIGHTDECK_EMIT_DISABLED", None)
        env.pop("FLIGHTDECK_SESSION_ID", None)
        env.pop("FLIGHTDECK_AGENT", None)
        payload = json.dumps({"session_id": "sess-id", "cwd": str(root)})
        r = subprocess.run(
            ["bash", str(_SCRIPT), "idle"],
            input=payload, capture_output=True, text=True, env=env, cwd=root,
        )
        blocks = [b for b in log.read_text(encoding="utf-8").split("---\n") if b.strip()] if log.exists() else []
        return r, blocks

    def test_agent_flag_genuinely_absent_from_argv(self, tmp_path):
        root = tmp_path / "proj-no-identity"
        root.mkdir()
        r, blocks = self._run_recording(root, tmp_path, reject_extra=False)
        assert r.returncode == 0, r.stderr
        assert len(blocks) == 1  # primary call only, no retry needed
        assert "--agent" not in blocks[0].splitlines()

    def test_agent_flag_absent_on_legacy_retry_path_too(self, tmp_path):
        # #1151 AC2: the omission must apply to the legacy-argument retry
        # call site too, not just the primary — force the retry the same way
        # test_legacy_emit_cli_fallback does (reject --activity-type/--host).
        root = tmp_path / "proj-no-identity"
        root.mkdir()
        r, blocks = self._run_recording(root, tmp_path, reject_extra=True)
        assert r.returncode == 0, r.stderr
        assert len(blocks) == 2  # rejected primary call, then the retry
        for block in blocks:
            assert "--agent" not in block.splitlines()


class TestSessionIdFallbackChain:
    """#1166, AX-4: the fallback chain when hook stdin JSON extraction yields no
    session_id (no jq, non-JSON stdin, or a genuinely bare invocation) must be
    BOTH collision-resistant across concurrent agents in one project AND
    lifecycle-stable across one session's own open/idle/close firings — the
    `basename "$PWD"` fallback this replaces satisfied neither for the common
    case where FLIGHTDECK_SESSION_ID/CLAUDE_CODE_SESSION_ID are both unset.
    """

    def _run_bare(self, cwd: Path, events_path: Path, extra_env: dict) -> subprocess.CompletedProcess:
        # No stdin JSON at all (empty input, matches a non-hook direct
        # invocation) — forces every case here through the env-var fallback
        # chain, never the stdin-JSON primary path.
        env = os.environ.copy()
        env["PYTHONPATH"] = _SRC + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["FLIGHTDECK_EVENTS_PATH"] = str(events_path)
        env["FLIGHTDECK_EMIT_CMD"] = "python3 -m wave_status.events.emit"
        env.pop("FLIGHTDECK_INGEST_URL", None)
        env.pop("FLIGHTDECK_EMIT_DISABLED", None)
        env.pop("FLIGHTDECK_SESSION_ID", None)
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        env.pop("TMUX_PANE", None)
        env.update(extra_env)
        return subprocess.run(
            ["bash", str(_SCRIPT), "idle"],
            input="", capture_output=True, text=True, env=env, cwd=str(cwd),
        )

    def test_claude_code_session_id_used_when_flightdeck_unset(self, tmp_path):
        ep = tmp_path / "events.jsonl"
        r = self._run_bare(
            tmp_path, ep, {"CLAUDE_CODE_SESSION_ID": "cc-sess-1", "TMUX_PANE": "%99"}
        )
        assert r.returncode == 0, r.stderr
        # Wins over TMUX_PANE, proving tier order — not just "resolves to SOMETHING".
        assert _last_event(ep)["activityId"] == "session:cc-sess-1"

    def test_tmux_pane_used_when_neither_session_id_var_set(self, tmp_path):
        ep = tmp_path / "events.jsonl"
        r = self._run_bare(tmp_path, ep, {"TMUX_PANE": "%42"})
        assert r.returncode == 0, r.stderr
        assert _last_event(ep)["activityId"] == "session:tmux-42"

    def test_basename_is_the_absolute_last_resort(self, tmp_path):
        proj = tmp_path / "my-project"
        proj.mkdir()
        ep = tmp_path / "events.jsonl"
        r = self._run_bare(proj, ep, {})  # nothing set at all
        assert r.returncode == 0, r.stderr
        assert _last_event(ep)["activityId"] == "session:my-project"

    def test_two_concurrent_tmux_panes_in_the_same_project_get_distinct_sessions(self, tmp_path):
        # The exact bug #1166 fixes: two agents, same $PWD, both missing
        # FLIGHTDECK_SESSION_ID/CLAUDE_CODE_SESSION_ID — must NOT fold into one
        # card. `basename "$PWD"` alone (the old fallback) would have given both
        # the identical session id here.
        proj = tmp_path / "shared-project"
        proj.mkdir()
        ep = tmp_path / "events.jsonl"
        r_a = self._run_bare(proj, ep, {"TMUX_PANE": "%1"})
        r_b = self._run_bare(proj, ep, {"TMUX_PANE": "%2"})
        assert r_a.returncode == 0 and r_b.returncode == 0
        events = [json.loads(line) for line in ep.read_text(encoding="utf-8").splitlines()]
        activity_ids = {e["activityId"] for e in events}
        assert activity_ids == {"session:tmux-1", "session:tmux-2"}

    def test_one_sessions_own_lifecycle_stays_consistent_across_hook_firings(self, tmp_path):
        # The other half of AX-4: collision-resistance must not come at the
        # cost of stability — open/idle/close are three SEPARATE subprocess
        # firings for the SAME real session and must resolve to the SAME
        # fallback identity, or activity_end would never close the
        # activity_start it belongs to.
        proj = tmp_path / "one-session"
        proj.mkdir()
        ep = tmp_path / "events.jsonl"
        env_extra = {"TMUX_PANE": "%7"}
        for phase in ("open", "idle", "close"):
            env = os.environ.copy()
            env["PYTHONPATH"] = _SRC + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
            env["FLIGHTDECK_EVENTS_PATH"] = str(ep)
            env["FLIGHTDECK_EMIT_CMD"] = "python3 -m wave_status.events.emit"
            env.pop("FLIGHTDECK_INGEST_URL", None)
            env.pop("FLIGHTDECK_EMIT_DISABLED", None)
            env.pop("FLIGHTDECK_SESSION_ID", None)
            env.pop("CLAUDE_CODE_SESSION_ID", None)
            env.update(env_extra)
            r = subprocess.run(
                ["bash", str(_SCRIPT), phase],
                input="", capture_output=True, text=True, env=env, cwd=str(proj),
            )
            assert r.returncode == 0, r.stderr
        events = [json.loads(line) for line in ep.read_text(encoding="utf-8").splitlines()]
        assert len(events) == 3
        ids = {e["activityId"] for e in events}
        assert ids == {"session:tmux-7"}  # all three firings agree


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
