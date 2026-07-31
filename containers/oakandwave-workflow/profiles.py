#!/usr/bin/env python3
"""Container profiles + label filtering — Story 4.1 (#974), Plan #959, Dev Spec §5.9.

This module is the **canonical owner** of the two container profiles and the
``oaw.profile`` label the rest of the contained-workflow reads (R-21/R-22):

* **dogfood** — overlay OFF, **image-only**. The candidate ring: its runs feed the
  soak clock and its breakages trip quarantine. It is what the promotion gate
  measures. Labeled ``oaw.profile=dogfood``.
* **dev-mode** — the **skills overlay is ON** (a bind-mount of the developer's
  working-copy skills over the image's baked skills, so a skill edit is testable
  live without a rebuild — the R-06 non-promotable exception). Labeled
  ``oaw.profile=dev-mode`` and marked **non-candidate**: dev-mode runs and
  breakages are **excluded from promotion telemetry** — they never accrue soak and
  never trip quarantine.

Requirements this module is the guard for:

* **R-21** — the system provides two profiles: dev-mode (skills overlay ON, labeled
  non-candidate) and dogfood (overlay OFF, image-only, feeds the gate). Realised as
  the :data:`PROFILES` registry: each :class:`Profile` fixes its label, whether the
  skills overlay is ON, and whether it is a candidate; :func:`launch_spec` renders
  the concrete launch (the ``oaw.profile`` label + — for dev-mode only — the skills
  overlay ``-v`` mount that makes "overlay ON" a real bind, not a flag).
* **R-22** — the health probe **and the promotion gate** filter on the profile
  label; dev-mode runs and breakages do not count toward soak or trip quarantine.
  The **probe** half is the flight surgeon (``scripts/flight-surgeon/surgeon.py``,
  Story 3.1), which already excludes dev-mode from ``should_quarantine``. This
  module is the **gate** half: :func:`filter_candidate_records` drops every
  non-candidate (dev-mode) telemetry record, and :func:`aggregate_gate_signals`
  folds the *filtered* soak/quarantine ledgers into the exact
  ``SOAK_HOURS`` / ``QUARANTINE_COUNT`` signals ``promotion_gate.py`` consumes — so
  a dev-mode session can never inflate soak nor a dev-mode breakage fail the gate.

Design — **fail-safe toward measuring the candidate** (assertion-liveness, D7):

* Candidacy is the *default*: only an **explicit** dev-mode label excludes a record
  from the gate (:func:`is_candidate`). An unlabeled / unknown-profile record stays
  a candidate, so a real dogfood run can never silently escape the soak/quarantine
  accounting merely by lacking a label. This mirrors the surgeon's
  ``quarantine_eligible`` on the probe side — the two halves agree by construction.

Why the label logic is duplicated with the surgeon (and that is correct): the
surgeon imports **only the standard library** so a broken container's kit can never
shape its verdict (R-15). It therefore cannot import this module. The small
normalize/alias table is intentionally re-stated there; **this module is the
canonical definition of record**, and the two are kept in lock-step by
``tests/contained-workflow/test_profiles.py`` (which asserts the alias sets match).

CLI — the gate-signal emitter plugs straight into ``promote-oakandwave-image.sh``'s
``GATE_SIGNALS_CMD`` seam::

    python3 profiles.py --emit gate-signals \\
        --soak-ledger ~/.oaw/soak/ledger.jsonl \\
        --quarantine-ledger ~/.oaw/quarantine/ledger.jsonl
    # -> SOAK_HOURS=<candidate soak sum>
    #    QUARANTINE_COUNT=<candidate quarantine count>

    python3 profiles.py --emit launch --profile dev-mode --major "$(scripts/ci/oaw-major.sh)"
    # -> the docker/aoe launch args: the oaw.profile label + the skills overlay -v
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

# The docker label key that stamps a container's ring. Identical to
# ``quarantine.py``'s ``PROFILE_LABEL_KEY`` (the recreate preserves it verbatim)
# and to the label the surgeon reads — the one string all three agree on (R-22).
PROFILE_LABEL_KEY = "oaw.profile"

# The path the kit bakes skills to inside the image (Dockerfile: USER ubuntu,
# HOME=/home/ubuntu, ``./install`` lands skills under $HOME/.claude/skills). The
# dev-mode overlay binds the developer's working skills over exactly this path.
IMAGE_SKILLS_TARGET = "/home/ubuntu/.claude/skills"

# The default host source for the dev-mode skills overlay, in the same
# ``~/.oaw/overlay/<major>/`` family as the user-overlay mounts (30-user-overlay).
# ``<major>`` is substituted at render time; overridable via the CLI so a developer
# can point the overlay at their live working tree.
DEFAULT_SKILLS_OVERLAY_SOURCE = "~/.oaw/overlay/<major>/skills"


@dataclass(frozen=True)
class Profile:
    """One container profile (R-21).

    ``label`` is the ``oaw.profile`` value stamped on the container and read back by
    the surgeon and the gate filter. ``skills_overlay`` is True iff the dev-mode
    skills overlay is bound (overlay ON). ``candidate`` is True iff the profile
    feeds the promotion telemetry — dogfood is a candidate; dev-mode is **not**, so
    it is excluded from soak and quarantine (R-22)."""

    name: str
    label: str
    skills_overlay: bool
    candidate: bool
    aliases: frozenset[str] = field(default_factory=frozenset)


# --- the two profiles (R-21) --------------------------------------------------

DOGFOOD = Profile(
    name="dogfood",
    label="dogfood",
    skills_overlay=False,  # image-only — nothing bound over the baked skills
    candidate=True,  # feeds the gate: its runs accrue soak, its breakages quarantine
    aliases=frozenset({"dogfood", "dogfood-ring", "candidate"}),
)

DEV_MODE = Profile(
    name="dev-mode",
    label="dev-mode",
    skills_overlay=True,  # the working-copy skills overlay is bound (R-06 exception)
    candidate=False,  # non-candidate — excluded from promotion telemetry (R-22)
    aliases=frozenset({"dev-mode", "dev_mode", "devmode", "dev"}),
)

# Registry, keyed by canonical name. Exactly two profiles exist (R-21).
PROFILES: dict[str, Profile] = {DOGFOOD.name: DOGFOOD, DEV_MODE.name: DEV_MODE}


class ProfileError(ValueError):
    """A profile contract violation. Raised LOUD, never swallowed."""


def normalize_profile(value: object) -> str:
    """Normalize a raw label value to a canonical profile name, or ``unknown``.

    Only an explicit dev-mode / dogfood marker (via each profile's alias set)
    resolves; anything else is ``unknown``. ``unknown`` is treated as a **candidate**
    (see :func:`is_candidate`) so a mislabeled dogfood container is never silently
    dropped from the gate."""
    if not isinstance(value, str):
        return "unknown"
    v = value.strip().lower()
    for prof in PROFILES.values():
        if v in prof.aliases:
            return prof.name
    return "unknown"


def get_profile(name: object) -> Profile:
    """Resolve ``name`` to its canonical :class:`Profile`, else raise.

    Accepts any alias (via :func:`normalize_profile`). An unknown/unresolvable value
    is a loud error — a launch must name one of the two real profiles; there is no
    implicit default (a silent default is exactly the mislabel R-22 guards against)."""
    canonical = normalize_profile(name)
    if canonical not in PROFILES:
        raise ProfileError(
            f"unknown profile {name!r} — must be one of {sorted(PROFILES)} "
            f"(or a recognised alias); there is no implicit default"
        )
    return PROFILES[canonical]


def is_candidate(value: object) -> bool:
    """True iff a record/container with this profile label **counts** toward the
    gate (R-22). dev-mode is the only non-candidate; unknown/unlabeled defaults to
    candidate — fail-safe toward measuring, never toward silently excluding."""
    canonical = normalize_profile(value)
    prof = PROFILES.get(canonical)
    return prof.candidate if prof is not None else True


def skills_overlay_on(value: object) -> bool:
    """True iff the named profile binds the skills overlay (R-21). Only dev-mode
    does; an unknown profile is treated as overlay-OFF (image-only) — the safe,
    promotable shape."""
    canonical = normalize_profile(value)
    prof = PROFILES.get(canonical)
    return bool(prof.skills_overlay) if prof is not None else False


# --- launch spec: the label + the (dev-mode-only) skills overlay (R-21) -------


def skills_overlay_mount(
    profile: object,
    *,
    major: int | str,
    source: str = DEFAULT_SKILLS_OVERLAY_SOURCE,
    mode: str = "rw",
) -> str | None:
    """The ``docker run -v`` spec binding the dev-mode skills overlay, or ``None``.

    Returns ``None`` for any overlay-OFF profile (dogfood, unknown) — image-only, so
    nothing is bound and the baked skills stand. For dev-mode, returns
    ``<host-source>:<image-skills-target>[:mode]`` with ``<major>`` substituted, so
    the developer's working skills shadow the baked ones (overlay ON, R-21). This is
    the R-06 non-promotable exception — the overlay is *why* dev-mode is a
    non-candidate."""
    if not skills_overlay_on(profile):
        return None
    src = str(source).replace("<major>", str(major))
    suffix = "" if mode == "rw" else f":{mode}"
    return f"{src}:{IMAGE_SKILLS_TARGET}{suffix}"


class EmptySkillsOverlayError(ProfileError):
    """dev-mode's overlay source is empty — binding it would BLANK the skills."""


def assert_overlay_populated(mount: str) -> None:
    """Refuse a dev-mode launch whose overlay source is empty or absent (#1067).

    The overlay is a WHOLE-DIRECTORY bind over the image's skills dir, so the
    container sees exactly what the host source contains — it REPLACES, it does not
    merge. `architecture.md` calls it "the developer's working skills bind over the
    baked skills", which reads as an overlay; a whole-dir bind is a replacement.

    The source is empty by default (nothing populates it), so an unguarded dev-mode
    launch comes up with NO SKILLS AT ALL rather than with the developer's layered
    over the baked ones. That is silent — the container starts fine and the agent
    simply has no skills — which is why this raises rather than warns.
    """
    src = Path(mount.split(":", 1)[0]).expanduser()
    try:
        empty = not src.is_dir() or not any(src.iterdir())
    except OSError as exc:
        # An unreadable dir is "not usable as an overlay" just as surely as an
        # empty one — surface it as the same legible refusal rather than letting a
        # raw PermissionError escape as a traceback.
        raise EmptySkillsOverlayError(
            f"dev-mode skills overlay source {src} is not readable: {exc}"
        ) from exc
    if empty:
        raise EmptySkillsOverlayError(
            f"dev-mode skills overlay source {src} is empty or absent. The overlay "
            f"is a whole-directory bind over {IMAGE_SKILLS_TARGET}, so launching "
            "would leave the container with NO skills, not with yours layered over "
            "the baked ones. Populate it (e.g. symlink your working skills into it) "
            "or use the dogfood profile, which is image-only by design."
        )


def launch_spec(
    profile: object,
    *,
    major: int | str,
    skills_overlay_source: str = DEFAULT_SKILLS_OVERLAY_SOURCE,
    require_populated_overlay: bool = True,
) -> list[str]:
    """Render the concrete launch args for a profile (R-21).

    Always stamps ``--label oaw.profile=<label>`` (the string the surgeon and the
    gate filter both read). For dev-mode it additionally appends ``-v <overlay>`` so
    the skills overlay is a **real bind**, not merely a flag — "overlay ON" is
    enforced by the mount, "overlay OFF" by its absence. The wrapper that launches
    the container (or the aoe profile) consumes these args verbatim."""
    prof = get_profile(profile)
    args = ["--label", f"{PROFILE_LABEL_KEY}={prof.label}"]
    mount = skills_overlay_mount(prof.name, major=major, source=skills_overlay_source)
    if mount is not None:
        # Guarded by default: an empty overlay blanks the skill surface silently.
        # Callers rendering a spec for inspection (tests, docs) pass False.
        if require_populated_overlay:
            assert_overlay_populated(mount)
        args += ["-v", mount]
    return args


# --- the gate-side telemetry filter (R-22, the gate half) ---------------------


def _record_profile(record: object) -> object:
    """Extract the ``profile`` field from a telemetry record (quarantine ledger
    entries carry it via ``quarantine.py``'s ``quarantine_record()``; soak records
    carry it per session). A record with no ``profile`` key yields ``None`` — which
    :func:`is_candidate` treats as a candidate, so an unlabeled record is *kept*
    (counted), never silently dropped."""
    if isinstance(record, dict):
        return record.get("profile")
    return None


def filter_candidate_records(records: list[dict]) -> list[dict]:
    """Drop every **non-candidate** (dev-mode) telemetry record (R-22).

    This is the gate-side profile filter: given raw telemetry (soak sessions or
    quarantine events, each tagged with its ``profile``), keep only the records that
    count toward promotion. dev-mode records are removed so they can neither inflate
    soak nor trip the zero-quarantines condition. Unlabeled/unknown records are
    **kept** (candidate by default) — fail-safe toward measuring the candidate."""
    return [r for r in records if isinstance(r, dict) and is_candidate(_record_profile(r))]


def _soak_hours_of(record: dict) -> float:
    """Accrued soak hours for one candidate soak record: ``hours`` if present, else
    ``seconds``/3600. A record with neither contributes 0 (it carries no measurable
    soak) rather than crashing the aggregation."""
    if "hours" in record:
        try:
            return float(record["hours"])
        except (TypeError, ValueError):
            return 0.0
    if "seconds" in record:
        try:
            return float(record["seconds"]) / 3600.0
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def aggregate_gate_signals(
    *,
    soak_records: list[dict],
    quarantine_records: list[dict],
) -> dict[str, float | int]:
    """Fold the **profile-filtered** ledgers into the gate's soak/quarantine signals.

    Both ledgers are passed through :func:`filter_candidate_records` first, so
    dev-mode never contributes (R-22):

    * ``soak_hours`` — the sum of :func:`_soak_hours_of` over the candidate soak
      records (dev-mode soak excluded).
    * ``quarantine_count`` — the count of candidate ``event == "quarantine"`` records
      (a dev-mode breakage, even if one leaked into the ledger, does not count).

    The returned dict is exactly the two signals ``promotion_gate.py`` reads as
    ``--soak-hours`` / ``--quarantines``; :func:`gate_signals_kv` renders them for
    the wrapper's ``GATE_SIGNALS_CMD`` seam."""
    candidate_soak = filter_candidate_records(soak_records)
    candidate_quarantines = filter_candidate_records(quarantine_records)
    soak_hours = sum(_soak_hours_of(r) for r in candidate_soak)
    quarantine_count = sum(
        1 for r in candidate_quarantines if str(r.get("event", "quarantine")) == "quarantine"
    )
    return {"soak_hours": soak_hours, "quarantine_count": quarantine_count}


def gate_signals_kv(signals: dict[str, float | int]) -> str:
    """Render aggregated signals as the ``KEY=VALUE`` lines the promote wrapper's
    ``GATE_SIGNALS_CMD`` seam sources (``SOAK_HOURS`` / ``QUARANTINE_COUNT``). Soak
    hours print with no trailing ``.0`` when whole, matching the gate's ``%g``."""
    soak = signals["soak_hours"]
    soak_str = f"{soak:g}" if isinstance(soak, float) else str(soak)
    return f"SOAK_HOURS={soak_str}\nQUARANTINE_COUNT={int(signals['quarantine_count'])}"


# --- CLI ----------------------------------------------------------------------


def _read_ledger(path: str | None) -> list[dict]:
    """Read a ``.jsonl`` telemetry ledger (one JSON object per line) into a list.

    A missing path or ``None`` yields ``[]`` (no telemetry ⇒ no candidate soak /
    zero counted quarantines — the gate's own fail-closed logic then handles the
    empty-soak case as RED). Blank and malformed lines are skipped."""
    if not path:
        return []
    p = Path(path).expanduser()
    if not p.is_file():
        return []
    out: list[dict] = []
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--emit",
        choices=("gate-signals", "launch"),
        required=True,
        help="gate-signals: profile-filtered SOAK_HOURS/QUARANTINE_COUNT KV for the "
        "promote wrapper's GATE_SIGNALS_CMD seam. launch: a profile's docker/aoe args.",
    )
    parser.add_argument("--soak-ledger", default=None, help="path to the soak .jsonl ledger")
    parser.add_argument(
        "--quarantine-ledger", default=None, help="path to the quarantine .jsonl ledger"
    )
    parser.add_argument(
        "--profile", default=None, help="profile name for --emit launch (dev-mode|dogfood)"
    )
    parser.add_argument(
        # NO literal default. A default here is the #1067 defect relocated from
        # shell to the CLI — it resolves silently to the wrong state namespace.
        # Not argparse-`required` though: --major is only consumed where <major> is
        # actually substituted (a dev-mode overlay), so demanding it for
        # --emit gate-signals or a dogfood launch would be noise. Enforced below,
        # where it is used.
        "--major", default=None,
        help="the state/image major for <major> substitution (derive: scripts/ci/oaw-major.sh)",
    )
    parser.add_argument(
        "--skills-overlay-source",
        default=DEFAULT_SKILLS_OVERLAY_SOURCE,
        help="host source for the dev-mode skills overlay (--emit launch)",
    )
    parser.add_argument(
        "--allow-empty-overlay",
        action="store_true",
        help=(
            "render a dev-mode spec even when the overlay source is empty. For "
            "INSPECTION only — launching with an empty overlay leaves the "
            "container with no skills at all (#1067)"
        ),
    )
    args = parser.parse_args(argv)

    if args.emit == "gate-signals":
        signals = aggregate_gate_signals(
            soak_records=_read_ledger(args.soak_ledger),
            quarantine_records=_read_ledger(args.quarantine_ledger),
        )
        print(gate_signals_kv(signals))
        return 0

    # --emit launch
    if not args.profile:
        print("--profile is required for --emit launch", file=sys.stderr)
        return 2
    # Demand --major only when the rendered spec actually substitutes <major> —
    # i.e. an overlay-ON profile. Guessing a literal is the #1067 defect.
    if args.major is None and "<major>" in args.skills_overlay_source:
        if skills_overlay_on(args.profile):
            print(
                "--major is required for an overlay-ON profile (its source contains "
                "<major>). Derive it: --major \"$(scripts/ci/oaw-major.sh)\". There is "
                "no default on purpose — a literal silently picks the wrong state "
                "namespace (#1067).",
                file=sys.stderr,
            )
            return 2
        args.major = ""  # unused: overlay OFF renders no <major>
    try:
        args_out = launch_spec(
            args.profile,
            major=args.major,
            skills_overlay_source=args.skills_overlay_source,
            require_populated_overlay=not args.allow_empty_overlay,
        )
    except ProfileError as exc:
        print(f"profile error: {exc}", file=sys.stderr)
        return 2
    except EmptySkillsOverlayError as exc:
        print(f"profile error: {exc}", file=sys.stderr)
        return 2
    print(" ".join(args_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
