"""Tests for scripts/discord-status-post.

Exercises the pure functions (compute_summary, build_embed, progress_bar)
against real JSON fixtures. Does NOT hit the Discord API.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import the script as a module (it has no .py extension)
# ---------------------------------------------------------------------------

SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "scripts", "discord-status-post"
)
_loader = importlib.machinery.SourceFileLoader("discord_status_post", SCRIPT_PATH)
spec = importlib.util.spec_from_file_location(
    "discord_status_post", SCRIPT_PATH, loader=_loader,
)
dsp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dsp)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PLAN_DATA = {
    "project": "test-project",
    "phases": [
        {
            "name": "Foundation",
            "waves": [
                {
                    "id": "p1w1",
                    "issues": [
                        {"number": 1, "title": "Issue 1"},
                        {"number": 2, "title": "Issue 2"},
                    ],
                },
                {
                    "id": "p1w2",
                    "issues": [
                        {"number": 3, "title": "Issue 3"},
                    ],
                },
            ],
        },
        {
            "name": "Polish",
            "waves": [
                {
                    "id": "p2w1",
                    "issues": [
                        {"number": 4, "title": "Issue 4"},
                    ],
                },
            ],
        },
    ],
}

STATE_DATA = {
    "current_wave": "p1w1",
    "current_action": {
        "action": "in-flight",
        "label": "In-Flight",
        "detail": "doing stuff",
    },
    "issues": {
        "1": {"status": "closed"},
        "2": {"status": "open"},
        "3": {"status": "open"},
        "4": {"status": "open"},
    },
    "deferrals": [
        {"status": "pending", "description": "d1"},
        {"status": "accepted", "description": "d2"},
        {"status": "pending", "description": "d3"},
    ],
    "last_updated": "2026-03-28T12:00:00+00:00",
}

FLIGHTS_DATA = {
    "flights": {
        "p1w1": [
            {"number": 1, "status": "completed"},
            {"number": 2, "status": "running"},
            {"number": 3, "status": "pending"},
        ],
    },
}


def _write_fixtures(tmp_path: Path) -> Path:
    """Write fixture JSON files to tmp_path and return the directory."""
    (tmp_path / "phases-waves.json").write_text(json.dumps(PLAN_DATA))
    (tmp_path / "state.json").write_text(json.dumps(STATE_DATA))
    (tmp_path / "flights.json").write_text(json.dumps(FLIGHTS_DATA))
    return tmp_path


# ---------------------------------------------------------------------------
# progress_bar()
# ---------------------------------------------------------------------------


class TestProgressBar:
    def test_zero_percent(self) -> None:
        bar = dsp.progress_bar(0)
        assert "\u2591" * 20 in bar
        assert "0%" in bar

    def test_fifty_percent(self) -> None:
        bar = dsp.progress_bar(50)
        assert "\u2588" * 10 in bar
        assert "\u2591" * 10 in bar
        assert "50%" in bar

    def test_hundred_percent(self) -> None:
        bar = dsp.progress_bar(100)
        assert "\u2588" * 20 in bar
        assert "100%" in bar

    def test_bar_length_always_20(self) -> None:
        for pct in (0, 25, 50, 75, 100):
            bar = dsp.progress_bar(pct)
            # Count block chars (filled + empty = 20)
            blocks = sum(1 for c in bar if c in ("\u2588", "\u2591"))
            assert blocks == 20, f"pct={pct} produced {blocks} blocks"

    def test_has_angle_brackets(self) -> None:
        bar = dsp.progress_bar(50)
        assert "\u27e8" in bar  # ⟨
        assert "\u27e9" in bar  # ⟩


# ---------------------------------------------------------------------------
# COLOR_MAP
# ---------------------------------------------------------------------------


class TestColorMapping:
    """All 7 action states must map to the correct decimal color."""

    EXPECTED = {
        "idle": 9807270,
        "planning": 3447003,
        "pre-flight": 1752220,
        "in-flight": 3066993,
        "merging": 15844367,
        "post-wave-review": 15105570,
        "waiting-on-meatbag": 15158332,
    }

    def test_all_actions_present(self) -> None:
        for action in self.EXPECTED:
            assert action in dsp.COLOR_MAP, f"Missing color for {action!r}"

    def test_color_values(self) -> None:
        for action, expected_color in self.EXPECTED.items():
            assert dsp.COLOR_MAP[action] == expected_color, (
                f"{action}: expected {expected_color}, got {dsp.COLOR_MAP[action]}"
            )

    def test_no_extra_actions(self) -> None:
        assert set(dsp.COLOR_MAP.keys()) == set(self.EXPECTED.keys())


# ---------------------------------------------------------------------------
# compute_summary()
# ---------------------------------------------------------------------------


class TestComputeSummary:
    def setup_method(self, tmp_path=None) -> None:
        # tmp_path not available in setup_method; use a class-level fixture
        pass

    def test_project_name(self, tmp_path: Path) -> None:
        d = _write_fixtures(tmp_path)
        s = dsp.compute_summary(d)
        assert s["project"] == "test-project"

    def test_phase(self, tmp_path: Path) -> None:
        d = _write_fixtures(tmp_path)
        s = dsp.compute_summary(d)
        assert s["phase"] == "1/2"

    def test_phase_name(self, tmp_path: Path) -> None:
        d = _write_fixtures(tmp_path)
        s = dsp.compute_summary(d)
        assert s["phase_name"] == "Foundation"

    def test_wave(self, tmp_path: Path) -> None:
        d = _write_fixtures(tmp_path)
        s = dsp.compute_summary(d)
        assert s["wave"] == "1/2 in phase 1"

    def test_flight_running(self, tmp_path: Path) -> None:
        d = _write_fixtures(tmp_path)
        s = dsp.compute_summary(d)
        assert s["flight"] == "2/3"

    def test_action_display(self, tmp_path: Path) -> None:
        d = _write_fixtures(tmp_path)
        s = dsp.compute_summary(d)
        assert "in-flight" in s["action"]
        assert "doing stuff" in s["action"]

    def test_action_raw(self, tmp_path: Path) -> None:
        d = _write_fixtures(tmp_path)
        s = dsp.compute_summary(d)
        assert s["action_raw"] == "in-flight"

    def test_progress(self, tmp_path: Path) -> None:
        d = _write_fixtures(tmp_path)
        s = dsp.compute_summary(d)
        assert s["progress"] == "1/4 issues"
        assert s["progress_pct"] == 25

    def test_deferrals(self, tmp_path: Path) -> None:
        d = _write_fixtures(tmp_path)
        s = dsp.compute_summary(d)
        assert s["deferrals"] == "2 pending, 1 accepted"

    def test_last_updated(self, tmp_path: Path) -> None:
        d = _write_fixtures(tmp_path)
        s = dsp.compute_summary(d)
        assert s["last_updated"] == "2026-03-28T12:00:00+00:00"


# ---------------------------------------------------------------------------
# build_embed()
# ---------------------------------------------------------------------------


class TestBuildEmbed:
    def _get_embed(self, tmp_path: Path) -> dict:
        d = _write_fixtures(tmp_path)
        s = dsp.compute_summary(d)
        return dsp.build_embed(s, "cc-workflow")

    def test_title(self, tmp_path: Path) -> None:
        embed = self._get_embed(tmp_path)
        assert "cc-workflow" in embed["title"]
        assert "Wave Status" in embed["title"]

    def test_color_matches_action(self, tmp_path: Path) -> None:
        embed = self._get_embed(tmp_path)
        assert embed["color"] == dsp.COLOR_MAP["in-flight"]

    def test_has_six_fields(self, tmp_path: Path) -> None:
        embed = self._get_embed(tmp_path)
        assert len(embed["fields"]) == 6

    def test_field_names_contain_labels(self, tmp_path: Path) -> None:
        embed = self._get_embed(tmp_path)
        names = [f["name"] for f in embed["fields"]]
        for label in ("Phase", "Wave", "Action", "Flight", "Progress", "Deferrals"):
            assert any(label in n for n in names), f"Missing field containing {label!r}"

    def test_progress_field_has_bar(self, tmp_path: Path) -> None:
        embed = self._get_embed(tmp_path)
        progress_field = embed["fields"][4]
        assert "\u2588" in progress_field["value"]
        assert "\u2591" in progress_field["value"]
        assert "25%" in progress_field["value"]

    def test_footer(self, tmp_path: Path) -> None:
        embed = self._get_embed(tmp_path)
        assert "cc-workflow" in embed["footer"]["text"]

    def test_timestamp(self, tmp_path: Path) -> None:
        embed = self._get_embed(tmp_path)
        assert embed["timestamp"] == "2026-03-28T12:00:00+00:00"

    def test_unknown_action_defaults_to_idle_color(self, tmp_path: Path) -> None:
        d = _write_fixtures(tmp_path)
        s = dsp.compute_summary(d)
        s["action_raw"] = "never-heard-of-this"
        embed = dsp.build_embed(s, "test")
        assert embed["color"] == dsp.COLOR_MAP["idle"]


# ---------------------------------------------------------------------------
# Message ID cache round-trip
# ---------------------------------------------------------------------------


class TestMessageIdCache:
    def test_cache_write_and_read(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "discord-status.json"
        cache = {
            "channel_id": "123456",
            "message_id": "789012",
            "updated_at": "2026-03-28T12:00:00+00:00",
        }
        cache_file.write_text(json.dumps(cache, indent=2) + "\n")
        loaded = dsp.load_json(cache_file)
        assert loaded["channel_id"] == "123456"
        assert loaded["message_id"] == "789012"

    def test_load_json_missing_file(self, tmp_path: Path) -> None:
        result = dsp.load_json(tmp_path / "nonexistent.json")
        assert result == {}


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_flights_shows_em_dash(self, tmp_path: Path) -> None:
        (tmp_path / "phases-waves.json").write_text(json.dumps(PLAN_DATA))
        (tmp_path / "state.json").write_text(json.dumps(STATE_DATA))
        (tmp_path / "flights.json").write_text(json.dumps({"flights": {}}))
        s = dsp.compute_summary(tmp_path)
        assert s["flight"] == "\u2014"

    def test_no_deferrals(self, tmp_path: Path) -> None:
        state = {**STATE_DATA, "deferrals": []}
        (tmp_path / "phases-waves.json").write_text(json.dumps(PLAN_DATA))
        (tmp_path / "state.json").write_text(json.dumps(state))
        (tmp_path / "flights.json").write_text(json.dumps(FLIGHTS_DATA))
        s = dsp.compute_summary(tmp_path)
        assert s["deferrals"] == "0 pending, 0 accepted"

    def test_idle_action_no_detail(self, tmp_path: Path) -> None:
        state = {
            **STATE_DATA,
            "current_action": {"action": "idle", "label": "Idle", "detail": ""},
        }
        (tmp_path / "phases-waves.json").write_text(json.dumps(PLAN_DATA))
        (tmp_path / "state.json").write_text(json.dumps(state))
        (tmp_path / "flights.json").write_text(json.dumps(FLIGHTS_DATA))
        s = dsp.compute_summary(tmp_path)
        assert s["action"] == "idle"
        assert "\u2014" not in s["action"]

    def test_current_wave_none_all_complete(self, tmp_path: Path) -> None:
        state = {
            **STATE_DATA,
            "current_wave": None,
            "waves": {
                "p1w1": {"status": "completed"},
                "p1w2": {"status": "completed"},
                "p2w1": {"status": "completed"},
            },
        }
        (tmp_path / "phases-waves.json").write_text(json.dumps(PLAN_DATA))
        (tmp_path / "state.json").write_text(json.dumps(state))
        (tmp_path / "flights.json").write_text(json.dumps(FLIGHTS_DATA))
        s = dsp.compute_summary(tmp_path)
        assert s["phase_name"] == "Polish"  # last phase name
        assert "0/" not in s["phase"]
        assert s["phase"] == "2/2"

    def test_all_issues_closed_100_percent(self, tmp_path: Path) -> None:
        state = {
            **STATE_DATA,
            "issues": {
                "1": {"status": "closed"},
                "2": {"status": "closed"},
                "3": {"status": "closed"},
                "4": {"status": "closed"},
            },
        }
        (tmp_path / "phases-waves.json").write_text(json.dumps(PLAN_DATA))
        (tmp_path / "state.json").write_text(json.dumps(state))
        (tmp_path / "flights.json").write_text(json.dumps(FLIGHTS_DATA))
        s = dsp.compute_summary(tmp_path)
        assert s["progress_pct"] == 100
        bar = dsp.progress_bar(100)
        assert "\u2591" not in bar.split(" ")[0]  # no empty blocks before the %


# ---------------------------------------------------------------------------
# No external dependencies [CT-01]
# ---------------------------------------------------------------------------


class TestNoDependencies:
    def test_script_imports_only_stdlib(self) -> None:
        with open(SCRIPT_PATH) as f:
            source = f.read()

        import_lines = [
            line.strip()
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]

        stdlib_prefixes = (
            "from __future__",
            "import argparse",
            "import hashlib",
            "import json",
            "import os",
            "import subprocess",
            "import sys",
            "import tempfile",
            "import time",
            "import urllib",
            "from datetime",
            "from pathlib",
        )
        for line in import_lines:
            assert any(line.startswith(p) for p in stdlib_prefixes), (
                f"Non-stdlib import found: {line}"
            )
