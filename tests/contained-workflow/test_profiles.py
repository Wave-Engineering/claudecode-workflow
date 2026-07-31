"""Oracle for Story 4.1 (#974) — dev-mode vs dogfood profiles + label filtering.

Two acceptance criteria, both proved here as *pure* unit oracles (no docker, no
aoe, no registry) so they run for real in the stock ``pytest tests/`` lane:

* **AC1 [R-21]** — two profiles exist; dev-mode has the skills overlay ON and is
  labeled non-candidate; dogfood is overlay-OFF/image-only and feeds the gate.
  Proved by :func:`test_two_profiles_exist`, :func:`test_dev_mode_overlay_on`,
  :func:`test_dogfood_overlay_off_image_only`, and :func:`test_launch_spec_labels`.
* **AC2 [R-22]** — the gate filters on the label; dev-mode runs/breakages don't
  count toward soak or trip quarantine. The named story oracle,
  :func:`test_profile_filter`, drives mixed soak + quarantine ledgers and asserts
  every dev-mode record is excluded from the aggregated gate signals.

Plus a lock-step guard (:func:`test_alias_sets_match_surgeon`) proving this module
— the canonical owner of the profile label — and the deliberately kit-independent
surgeon (which cannot import it, R-15) agree on the dev-mode/dogfood alias sets.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTAINER_DIR = REPO_ROOT / "containers" / "oakandwave-workflow"
PROFILES_PY = CONTAINER_DIR / "profiles.py"
SURGEON_DIR = REPO_ROOT / "scripts" / "flight-surgeon"

# Path-style import (no PYTHONPATH dependency), mirroring test_gate.py.
sys.path.insert(0, str(CONTAINER_DIR))
import profiles as pf  # noqa: E402


# --- AC1 [R-21] — two profiles exist, with the right overlay/label/candidacy ---


def test_two_profiles_exist():
    """Exactly two profiles: dogfood and dev-mode (R-21)."""
    assert set(pf.PROFILES) == {"dogfood", "dev-mode"}
    assert pf.get_profile("dogfood") is pf.DOGFOOD
    assert pf.get_profile("dev-mode") is pf.DEV_MODE


def test_dev_mode_overlay_on():
    """dev-mode: skills overlay ON, labeled non-candidate (R-21)."""
    assert pf.DEV_MODE.skills_overlay is True
    assert pf.DEV_MODE.candidate is False
    assert pf.DEV_MODE.label == "dev-mode"
    assert pf.skills_overlay_on("dev-mode") is True
    assert pf.is_candidate("dev-mode") is False


def test_dogfood_overlay_off_image_only():
    """dogfood: overlay OFF (image-only), candidate — feeds the gate (R-21)."""
    assert pf.DOGFOOD.skills_overlay is False
    assert pf.DOGFOOD.candidate is True
    assert pf.DOGFOOD.label == "dogfood"
    assert pf.skills_overlay_on("dogfood") is False
    assert pf.is_candidate("dogfood") is True


def test_launch_spec_labels_and_overlay():
    """The launch spec stamps oaw.profile and binds the overlay ONLY for dev-mode.

    "overlay ON" must be a real ``-v`` bind over the baked skills, not a mere flag;
    "overlay OFF" must be the absence of that bind (image-only) — R-21."""
    dog = pf.launch_spec("dogfood", major=1)
    assert dog == ["--label", "oaw.profile=dogfood"]
    assert "-v" not in dog  # image-only

    # Rendering, not launch safety — the overlay-populated guard (#1067) is a
    # separate question, covered by test_dev_mode_refuses_an_empty_overlay.
    dev = pf.launch_spec("dev-mode", major=1, require_populated_overlay=False)
    assert dev[:2] == ["--label", "oaw.profile=dev-mode"]
    assert "-v" in dev
    mount = dev[dev.index("-v") + 1]
    # binds a host skills source over the image's baked skills path
    assert mount.endswith(":" + pf.IMAGE_SKILLS_TARGET)
    assert "<major>" not in mount  # <major> substituted


def test_overlay_mount_major_substitution():
    """The overlay source substitutes <major>; dogfood binds nothing."""
    assert pf.skills_overlay_mount("dogfood", major=2) is None
    m = pf.skills_overlay_mount("dev-mode", major=2)
    assert m is not None and "/2/" in m and "<major>" not in m


def test_unknown_profile_rejected_by_get():
    """A launch must name a real profile — no implicit default (R-22 mislabel guard)."""
    with pytest.raises(pf.ProfileError):
        pf.get_profile("candidate-ish-typo")


def test_aliases_resolve():
    """Common aliases resolve to their canonical profile."""
    assert pf.normalize_profile("dev_mode") == "dev-mode"
    assert pf.normalize_profile("devmode") == "dev-mode"
    assert pf.normalize_profile("DEV") == "dev-mode"
    assert pf.normalize_profile("candidate") == "dogfood"
    assert pf.normalize_profile("nonsense") == "unknown"
    assert pf.normalize_profile(None) == "unknown"


# --- AC2 [R-22] — the gate filters on the label -------------------------------


def test_profile_filter():
    """dev-mode telemetry is excluded from the aggregated soak/quarantine signals.

    The named story oracle. A mixed ledger of dogfood + dev-mode soak sessions and
    quarantine events must fold into gate signals that count **only** the dogfood
    (candidate) records — a dev-mode session cannot inflate soak, and a dev-mode
    breakage cannot trip the zero-quarantines condition (R-22)."""
    soak = [
        {"profile": "dogfood", "hours": 20},
        {"profile": "dogfood", "hours": 10},
        {"profile": "dev-mode", "hours": 500},  # must NOT count toward soak
        {"profile": "dev_mode", "seconds": 3600},  # alias — also excluded
    ]
    quarantines = [
        {"event": "quarantine", "profile": "dogfood", "held_digest": "repo@sha256:a"},
        {"event": "quarantine", "profile": "dev-mode", "held_digest": "repo@sha256:b"},
    ]

    signals = pf.aggregate_gate_signals(soak_records=soak, quarantine_records=quarantines)

    # only the two dogfood soak records (20 + 10) count — the 500h+1h dev-mode soak
    # is excluded.
    assert signals["soak_hours"] == 30
    # only the one dogfood quarantine counts — the dev-mode breakage is excluded.
    assert signals["quarantine_count"] == 1


def test_filter_keeps_unlabeled_as_candidate():
    """Fail-safe: an unlabeled/unknown record is KEPT (candidate) — a real dogfood
    run cannot escape the soak/quarantine accounting merely by lacking a label."""
    records = [
        {"hours": 5},  # no profile key
        {"profile": "unknown", "hours": 7},
        {"profile": "dev-mode", "hours": 99},
    ]
    kept = pf.filter_candidate_records(records)
    assert {r.get("profile") for r in kept} == {None, "unknown"}
    assert len(kept) == 2


def test_dev_mode_only_ledger_yields_zero_soak():
    """A ledger with ONLY dev-mode soak accrues zero candidate soak — the gate then
    reads soak RED on its own (dev-mode can never satisfy the soak condition)."""
    signals = pf.aggregate_gate_signals(
        soak_records=[{"profile": "dev-mode", "hours": 1000}],
        quarantine_records=[],
    )
    assert signals["soak_hours"] == 0
    assert signals["quarantine_count"] == 0


def test_gate_signals_kv_shape():
    """The KV render is exactly the SOAK_HOURS / QUARANTINE_COUNT keys the promote
    wrapper's GATE_SIGNALS_CMD seam sources into the gate."""
    kv = pf.gate_signals_kv({"soak_hours": 30.0, "quarantine_count": 1})
    assert "SOAK_HOURS=30" in kv
    assert "QUARANTINE_COUNT=1" in kv
    # whole soak hours print without a trailing .0 (matches the gate's %g)
    assert "SOAK_HOURS=30.0" not in kv


# --- lock-step guard: this module and the surgeon agree on the aliases --------


def test_alias_sets_match_surgeon():
    """This module owns the profile label; the surgeon re-states the alias table
    because it must import only stdlib (R-15) and so cannot import this module. The
    two MUST agree, or a container labeled dev-mode by the launch spec could be read
    as a candidate by the probe (or vice-versa). Assert lock-step."""
    sys.path.insert(0, str(SURGEON_DIR))
    import surgeon as fs  # noqa: E402

    assert pf.DEV_MODE.aliases == fs._DEV_MODE_ALIASES
    assert pf.DOGFOOD.aliases == fs._DOGFOOD_ALIASES
    # and the label key itself is the one string all three components share
    import quarantine as q  # noqa: E402  (colocated in CONTAINER_DIR, already on path)

    assert pf.PROFILE_LABEL_KEY == q.PROFILE_LABEL_KEY == "oaw.profile"


# --- CLI wiring (the gate-signals emitter feeds the promote wrapper) ----------


def test_cli_gate_signals(tmp_path):
    """The --emit gate-signals CLI reads the ledgers, applies the profile filter,
    and prints the KV the wrapper's GATE_SIGNALS_CMD seam expects."""
    soak = tmp_path / "soak.jsonl"
    soak.write_text(
        '{"profile":"dogfood","hours":24}\n{"profile":"dev-mode","hours":99}\n',
        encoding="utf-8",
    )
    quar = tmp_path / "quar.jsonl"
    quar.write_text(
        '{"event":"quarantine","profile":"dev-mode","held_digest":"r@sha256:a"}\n',
        encoding="utf-8",
    )
    out = subprocess.run(
        [
            sys.executable,
            str(PROFILES_PY),
            "--emit",
            "gate-signals",
            "--soak-ledger",
            str(soak),
            "--quarantine-ledger",
            str(quar),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "SOAK_HOURS=24" in out
    assert "QUARANTINE_COUNT=0" in out  # the dev-mode quarantine excluded


def test_cli_launch_emit():
    """The --emit launch CLI renders a profile's docker/aoe args."""
    dev = subprocess.run(
        # --allow-empty-overlay: this asserts RENDERING. Production callers get
        # the guard by default; see test_cli_refuses_empty_overlay.
        [sys.executable, str(PROFILES_PY), "--emit", "launch", "--profile", "dev-mode",
         "--major", "1", "--allow-empty-overlay"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert "--label oaw.profile=dev-mode" in dev
    assert "-v" in dev

    dog = subprocess.run(
        [sys.executable, str(PROFILES_PY), "--emit", "launch", "--profile", "dogfood"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert dog == "--label oaw.profile=dogfood"


# --- dev-mode overlay must not blank the skill surface (#1067) ----------------


def test_dev_mode_refuses_an_empty_overlay(tmp_path) -> None:
    """The overlay is a whole-dir bind over the image skills dir — it REPLACES.
    An empty source therefore yields a container with NO skills, silently, rather
    than the developer's layered over the baked ones."""
    empty = tmp_path / "skills"
    empty.mkdir()
    with pytest.raises(pf.EmptySkillsOverlayError) as exc:
        pf.launch_spec("dev-mode", major=7, skills_overlay_source=str(empty))
    msg = str(exc.value)
    assert "NO skills" in msg, "the refusal must say what would actually happen"
    assert "dogfood" in msg, "it must name the image-only alternative"


def test_dev_mode_accepts_a_populated_overlay(tmp_path) -> None:
    populated = tmp_path / "skills"
    (populated / "myskill").mkdir(parents=True)
    (populated / "myskill" / "SKILL.md").write_text("---\nname: myskill\n---\n")
    args = pf.launch_spec("dev-mode", major=7, skills_overlay_source=str(populated))
    assert "-v" in args and str(populated) in " ".join(args)


def test_dogfood_is_unaffected_by_the_overlay_guard(tmp_path) -> None:
    """dogfood is image-only: no overlay, so an empty source is irrelevant."""
    empty = tmp_path / "nothing"
    empty.mkdir()
    assert pf.launch_spec("dogfood", major=7, skills_overlay_source=str(empty)) == [
        "--label", "oaw.profile=dogfood",
    ]


def test_spec_still_renderable_for_inspection(tmp_path) -> None:
    """Docs/tests must be able to render the spec without a populated host dir."""
    args = pf.launch_spec(
        "dev-mode", major=7, skills_overlay_source=str(tmp_path / "absent"),
        require_populated_overlay=False,
    )
    assert "-v" in args


def test_cli_refuses_empty_overlay_by_default(tmp_path) -> None:
    """Production callers are guarded without opting in — the inspection escape
    must be explicit, or the guard is one forgotten flag from being inert."""
    empty = tmp_path / "skills"
    empty.mkdir()
    proc = subprocess.run(
        [sys.executable, str(PROFILES_PY), "--emit", "launch", "--profile", "dev-mode",
         "--major", "7", "--skills-overlay-source", str(empty)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2, f"expected refusal (exit 2), got {proc.returncode}"
    assert "no skills" in proc.stderr.lower()
    assert "Traceback" not in proc.stderr, "must be a message, not a stack trace"
