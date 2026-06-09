"""Subprocess contract tests for the JSON success envelope on mutation
subcommands of ``python -m wave_status`` [Issue #495].

The mutation subcommands (``flight``, ``flight-done``, ``close-issue``,
``record-mr``, ``waiting``, ``wavemachine-stop``) used to discard their
state-mutation return value AND crashed during response-shaping with
``'str' object has no attribute 'get'`` (observed in waves pa-4..pa-6 of
mcp-server-sdlc on 2026-04-26).

This file pins the post-fix contract:

* Each command exits 0 on a successful state mutation.
* Each command prints exactly one parseable JSON object to stdout.
* The envelope shape is ``{"ok": True, "state": {...}}``.
* ``state.json`` on disk is unchanged by a dashboard-regen failure
  (i.e. the envelope still prints — the persisted state survives).

These tests intentionally use ``subprocess.run`` against the real CLI
so the contract is enforced at the binary boundary that sdlc-server
MCP wrappers actually call.
"""

from __future__ import annotations

import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Shared fixture data — mirrors tests/conftest.py SAMPLE_PLAN/SAMPLE_FLIGHTS.
# ---------------------------------------------------------------------------

_PLAN: dict = {
    "project": "envelope-test",
    "base_branch": "main",
    "master_issue": 100,
    "phases": [
        {
            "name": "Foundation",
            "waves": [
                {
                    "id": "wave-1",
                    "name": "Wave 1",
                    "issues": [
                        {"number": 13, "title": "Issue 13", "deps": []},
                        {"number": 1, "title": "Issue 1", "deps": []},
                    ],
                },
            ],
        },
    ],
}

_FLIGHTS: list = [
    {"issues": [13, 1], "status": "pending"},
]


def _write_plan(repo: Path) -> None:
    (repo / "plan.json").write_text(json.dumps(_PLAN), encoding="utf-8")


def _write_flights(repo: Path) -> None:
    (repo / "flights.json").write_text(json.dumps(_FLIGHTS), encoding="utf-8")


def _bootstrap_through_flight_started(repo: Path, run_cli) -> None:
    """init -> planning -> flight-plan -> flight 1 (running)."""
    _write_plan(repo)
    _write_flights(repo)
    rc, _, err = run_cli(["init", "plan.json"], repo)
    assert rc == 0, f"init failed: {err}"
    rc, _, err = run_cli(["planning"], repo)
    assert rc == 0, f"planning failed: {err}"
    rc, _, err = run_cli(["flight-plan", "flights.json"], repo)
    assert rc == 0, f"flight-plan failed: {err}"


def _assert_envelope(stdout: str) -> dict:
    """Assert *stdout* contains exactly one ``{ok, state}`` JSON object
    and return the parsed envelope."""
    # Strip trailing newline; mutation handlers print exactly one line.
    payload = stdout.strip()
    assert payload, "expected JSON envelope on stdout, got empty string"
    envelope = json.loads(payload)
    assert isinstance(envelope, dict), (
        f"envelope is not a dict: {type(envelope).__name__}"
    )
    assert envelope.get("ok") is True, (
        f"envelope.ok != True: {envelope!r}"
    )
    assert isinstance(envelope.get("state"), dict), (
        f"envelope.state is not a dict: {envelope!r}"
    )
    return envelope


# ---------------------------------------------------------------------------
# Per-subcommand exit-code + envelope-shape tests
# ---------------------------------------------------------------------------

class TestMutationEnvelope:
    """Each mutation subcommand returns exit 0 and a parseable JSON
    ``{ok, state}`` envelope on stdout."""

    def test_flight_envelope(self, temp_git_repo: Path, run_cli) -> None:
        repo = temp_git_repo
        _bootstrap_through_flight_started(repo, run_cli)
        rc, out, err = run_cli(["flight", "1"], repo)
        assert rc == 0, f"flight failed: {err}"
        env = _assert_envelope(out)
        # Mutation persisted: action transitioned to in-flight.
        assert env["state"]["current_action"]["action"] == "in-flight"

    def test_close_issue_envelope(self, temp_git_repo: Path, run_cli) -> None:
        repo = temp_git_repo
        _bootstrap_through_flight_started(repo, run_cli)
        run_cli(["flight", "1"], repo)
        rc, out, err = run_cli(["close-issue", "13"], repo)
        assert rc == 0, f"close-issue failed: {err}"
        env = _assert_envelope(out)
        assert env["state"]["issues"]["13"]["status"] == "closed"

    def test_record_mr_envelope(self, temp_git_repo: Path, run_cli) -> None:
        repo = temp_git_repo
        _bootstrap_through_flight_started(repo, run_cli)
        run_cli(["flight", "1"], repo)
        rc, out, err = run_cli(["record-mr", "13", "#42"], repo)
        assert rc == 0, f"record-mr failed: {err}"
        env = _assert_envelope(out)
        assert env["state"]["waves"]["wave-1"]["mr_urls"]["13"] == "#42"

    def test_flight_done_envelope(self, temp_git_repo: Path, run_cli) -> None:
        repo = temp_git_repo
        _bootstrap_through_flight_started(repo, run_cli)
        run_cli(["flight", "1"], repo)
        rc, out, err = run_cli(["flight-done", "1"], repo)
        assert rc == 0, f"flight-done failed: {err}"
        env = _assert_envelope(out)
        assert env["state"]["current_action"]["action"] == "merging"

    def test_waiting_envelope(self, temp_git_repo: Path, run_cli) -> None:
        repo = temp_git_repo
        _bootstrap_through_flight_started(repo, run_cli)
        rc, out, err = run_cli(["waiting", "blocked on review"], repo)
        assert rc == 0, f"waiting failed: {err}"
        env = _assert_envelope(out)
        action = env["state"]["current_action"]
        assert action["action"] == "waiting-on-meatbag"
        assert action["detail"] == "blocked on review"

    def test_wavemachine_stop_envelope(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        repo = temp_git_repo
        _bootstrap_through_flight_started(repo, run_cli)
        # wavemachine-stop is idempotent — works whether or not a run is
        # active. Validate the envelope on the no-op path.
        rc, out, err = run_cli(["wavemachine-stop"], repo)
        assert rc == 0, f"wavemachine-stop failed: {err}"
        env = _assert_envelope(out)
        # Field cleared (or never set).
        assert "wavemachine_active" not in env["state"]


# ---------------------------------------------------------------------------
# Regression: state-on-disk matches the envelope's state payload
# ---------------------------------------------------------------------------

class TestEnvelopeReflectsDisk:
    """The ``state`` payload mirrors the on-disk ``state.json``.

    Ensures the envelope is computed from the post-mutation state, not
    a stale snapshot — and gives downstream sdlc-server MCP wrappers a
    reason to trust the payload instead of re-reading the file.
    """

    def test_close_issue_envelope_matches_disk(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        repo = temp_git_repo
        _bootstrap_through_flight_started(repo, run_cli)
        run_cli(["flight", "1"], repo)
        rc, out, _ = run_cli(["close-issue", "13"], repo)
        assert rc == 0
        env = _assert_envelope(out)
        on_disk = json.loads(
            (repo / ".claude" / "status" / "state.json").read_text(
                encoding="utf-8"
            )
        )
        # The envelope's view of issues #13 must match disk.
        assert env["state"]["issues"]["13"] == on_disk["issues"]["13"]


# ---------------------------------------------------------------------------
# Regression: dashboard-regen failure must not eat the envelope
# ---------------------------------------------------------------------------

class TestEnvelopeSurvivesRegen:
    """If the dashboard regen step crashes, the JSON envelope MUST still
    print and the CLI MUST still exit 0 — the state mutation already
    persisted, so the caller deserves an ``ok: true`` response."""

    def test_envelope_prints_when_regen_raises(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """Force ``generate_dashboard`` to raise inside the CLI subprocess
        via an injected ``sitecustomize.py`` (loaded automatically when
        its directory is first on ``PYTHONPATH``) and assert the envelope
        still prints with ``rc=0``."""
        import os
        import subprocess
        import sys

        repo = temp_git_repo
        _bootstrap_through_flight_started(repo, run_cli)

        # Inject sitecustomize that monkey-patches generate_dashboard at
        # interpreter startup, before wave_status.__main__ runs.
        inject_dir = repo / "_inject"
        inject_dir.mkdir()
        (inject_dir / "sitecustomize.py").write_text(
            "import wave_status.dashboard.generator as _g\n"
            "def _boom(*a, **kw):\n"
            "    raise RuntimeError('synthetic regen failure')\n"
            "_g.generate_dashboard = _boom\n",
            encoding="utf-8",
        )

        env = os.environ.copy()
        src_dir = str(Path(__file__).resolve().parent.parent / "src")
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in [str(inject_dir), src_dir, existing] if p
        )

        result = subprocess.run(
            [sys.executable, "-m", "wave_status", "flight", "1"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            env=env,
        )

        # CLI exits 0 even though regen blew up.
        assert result.returncode == 0, (
            f"expected rc=0, got {result.returncode}; "
            f"stderr={result.stderr!r}"
        )
        # Envelope on stdout, with the post-mutation action.
        env_payload = _assert_envelope(result.stdout)
        assert env_payload["state"]["current_action"]["action"] == "in-flight"
        # Failure surfaced as a best-effort stderr warning.
        assert "synthetic regen failure" in result.stderr


# ---------------------------------------------------------------------------
# Regression: non-enveloped mutations (init, complete, ...) must ALSO survive
# a dashboard-regen crash with exit 0. #495 hardened the envelope-printing
# commands but left init/complete/planning/etc. calling the raw regen, so a
# render crash ('str' object has no attribute 'get') surfaced as a non-zero
# exit AFTER the state had already persisted — sdlc-server's wave_init /
# wave_complete wrappers (which key on exit code) then reported ok:false on
# full success, risking a retry into a wave-ID collision.
# ---------------------------------------------------------------------------

class TestNonEnvelopeMutationsSurviveRegen:
    """Mutations that don't print an envelope (their MCP wrappers key on the
    CLI exit code) must still exit 0 when the best-effort dashboard regen
    crashes — the state mutation already persisted."""

    @staticmethod
    def _run_with_regen_boom(repo: Path, args: list[str]):
        import os
        import subprocess
        import sys

        inject_dir = repo / "_inject"
        if not inject_dir.exists():
            inject_dir.mkdir()
            (inject_dir / "sitecustomize.py").write_text(
                "import wave_status.dashboard.generator as _g\n"
                "def _boom(*a, **kw):\n"
                "    raise RuntimeError('synthetic regen failure')\n"
                "_g.generate_dashboard = _boom\n",
                encoding="utf-8",
            )
        env = os.environ.copy()
        src_dir = str(Path(__file__).resolve().parent.parent / "src")
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in [str(inject_dir), src_dir, existing] if p
        )
        return subprocess.run(
            [sys.executable, "-m", "wave_status", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            env=env,
        )

    def test_complete_exits_zero_when_regen_raises(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        repo = temp_git_repo
        _bootstrap_through_flight_started(repo, run_cli)

        result = self._run_with_regen_boom(repo, ["complete"])

        assert result.returncode == 0, (
            f"complete must exit 0 despite a regen crash (state persisted); "
            f"got rc={result.returncode}, stderr={result.stderr!r}"
        )
        assert "synthetic regen failure" in result.stderr
        # The mutation landed: the wave is marked completed on disk.
        state = json.loads(
            (repo / ".claude" / "status" / "state.json").read_text(encoding="utf-8")
        )
        assert state["waves"]["wave-1"]["status"] == "completed"

    def test_init_exits_zero_when_regen_raises(
        self, temp_git_repo: Path
    ) -> None:
        repo = temp_git_repo
        _write_plan(repo)

        result = self._run_with_regen_boom(repo, ["init", "plan.json"])

        assert result.returncode == 0, (
            f"init must exit 0 despite a regen crash (plan persisted); "
            f"got rc={result.returncode}, stderr={result.stderr!r}"
        )
        assert "synthetic regen failure" in result.stderr
        # The plan persisted despite the regen crash.
        assert (repo / ".claude" / "status" / "state.json").exists()
        assert (repo / ".claude" / "status" / "phases-waves.json").exists()
