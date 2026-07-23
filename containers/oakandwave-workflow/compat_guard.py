#!/usr/bin/env python3
"""Mechanical compat-break guard — Story 3.4 (#973), Plan #959, Dev Spec §5.8 (R-19).

The enforcement arm of the SemVer compatibility contract (§5.8). Story 3.3 built
the *policy* runtime — the major-partitioned namespace ``~/.oaw/state/<major>/``
and the coexistence classifier (``adoption.py``). This module is the **mechanical
guard** that keeps a same-major minor from silently breaking that shared state:
it versions the shared-state schema (``state-schema.json``) and, given a baseline
and a candidate schema, decides whether the change is safe to ship WITHIN the
current major or whether it FORCES a major bump.

Requirement this module is the guard for:

* **R-19** — IF a change breaks same-major shared-state compatibility, THEN it
  shall require a major bump, and a mechanical guard shall detect the break and
  block a silent minor ship. The within-major contract (R-18) is that shared-state
  changes are **additive + forward-tolerant**; therefore the ONLY compatible
  within-major mutation of the schema is *adding an optional field*. Anything else
  — removing a field, changing a field's type, or tightening an optional field to
  required (including introducing a NEW required field) — breaks a not-yet-updated
  agent and so must cross a major.

Scope (Dev Spec §5.N#4, VRTM R-19): this guard catches a **shape** break — a
change to the *structure* of the schema. Detecting a *semantic* break (a field
whose meaning changes while its shape is untouched) is an open question and is
explicitly NOT enforced here; a shape-preserving meaning change is the developer's
responsibility under PC-1.

Design — **one shippable path, fail-closed** (assertion-liveness, D7):

* :func:`evaluate_compat` is pure: it always returns a :class:`CompatReport`
  describing the diff and whether the ship is blocked; it never raises for a
  break. A break is DATA on the report (``report.blocked``), so callers can render
  it. A *malformed* schema, by contrast, raises :class:`CompatBreakError` — an
  unparseable contract is fail-loud, never assumed compatible.
* :func:`assert_shippable` is the guard: it raises :class:`CompatBreakError` iff
  the candidate is a breaking change that did NOT bump the major — the silent
  minor ship R-19 forbids. That is the only condition it blocks; a breaking change
  that DID bump the major is permitted (the break is properly signalled), and an
  additive/identical change ships within-major.
* The module never touches git, the network, docker, or a registry — it reasons
  purely over the two schema mappings handed to it. Sourcing the baseline (a
  ``git show BASE:state-schema.json``) and diffing it against the working tree
  live in the wrapper ``scripts/ci/compat-guard.sh``.

CLI::

    # Guard a candidate schema against its committed baseline (the CI gate):
    python3 compat_guard.py --baseline OLD.json --candidate state-schema.json

    # Self-validate a single schema is well-formed (no baseline to diff against):
    python3 compat_guard.py --candidate state-schema.json

Exits 0 when the change is shippable (or the schema self-validates); prints the
red block reason to stderr and exits 2 when the guard trips.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# The compat guard reasons over the SAME SemVer contract the coexistence
# classifier does (§5.8) — reuse its parser so the "did the major bump?" question
# and adoption's "same major?" question can never disagree about what a version
# means. adoption.py is a same-dir peer (the CLI's dir and the test's injected
# CONTAINER_DIR both put it on sys.path).
from adoption import AdoptionError, SemVer, parse_semver  # noqa: E402

# Change classes for a (baseline -> candidate) schema diff.
IDENTICAL = "identical"  # same fields, types, required-ness
ADDITIVE = "additive"  # only new OPTIONAL fields added — compatible within a major
BREAKING = "breaking"  # a removal / retype / tighten / new-required — forces a major

# The closed set of field types the schema may declare. A type outside this set
# is a malformed schema (fail-loud), never a silently-tolerated value.
ALLOWED_TYPES = frozenset(
    {"string", "integer", "number", "boolean", "object", "array", "null"}
)

# The canonical versioned schema this guard protects (relative to this module).
SCHEMA_FILENAME = "state-schema.json"


class CompatBreakError(ValueError):
    """A compat-guard contract violation — a silent same-major break, or a
    malformed schema. Raised LOUD, never swallowed."""


@dataclass(frozen=True)
class FieldSpec:
    """One shared-state field: its wire type and whether a record MUST carry it.

    ``required`` defaults False — the within-major model is forward-tolerant, so a
    reader defaults any absent field; an optional field is the compatible default.
    """

    type: str
    required: bool = False

    @staticmethod
    def from_value(name: str, value: object) -> "FieldSpec":
        if not isinstance(value, dict):
            raise CompatBreakError(
                f"field {name!r} must be an object with a 'type', got {value!r}"
            )
        ftype = value.get("type")
        if not isinstance(ftype, str) or ftype not in ALLOWED_TYPES:
            raise CompatBreakError(
                f"field {name!r} has invalid type {ftype!r} — expected one of "
                f"{sorted(ALLOWED_TYPES)}"
            )
        required = value.get("required", False)
        if not isinstance(required, bool):
            raise CompatBreakError(
                f"field {name!r} 'required' must be a bool, got {required!r}"
            )
        return FieldSpec(type=ftype, required=required)


@dataclass(frozen=True)
class StateSchema:
    """A versioned shared-state schema: a SemVer plus a name->:class:`FieldSpec`
    map. The major partitions the state namespace (R-20); the field map is what
    the guard diffs to classify a change (R-18/R-19)."""

    version: SemVer
    fields: dict[str, FieldSpec]

    @staticmethod
    def from_mapping(data: object) -> "StateSchema":
        """Parse a schema manifest mapping. Fail-loud on anything malformed — an
        unparseable schema must never be assumed compatible."""
        if not isinstance(data, dict):
            raise CompatBreakError(f"schema must be a JSON object, got {type(data).__name__}")
        raw_version = data.get("schema_version")
        if raw_version is None:
            raise CompatBreakError("schema is missing the required 'schema_version' field")
        try:
            version = parse_semver(raw_version)
        except AdoptionError as exc:
            raise CompatBreakError(f"schema_version is not a valid semver: {exc}") from exc
        raw_fields = data.get("fields")
        if not isinstance(raw_fields, dict):
            raise CompatBreakError("schema is missing a 'fields' object")
        fields = {name: FieldSpec.from_value(name, spec) for name, spec in raw_fields.items()}
        return StateSchema(version=version, fields=fields)

    @staticmethod
    def load(path: str | Path) -> "StateSchema":
        p = Path(path)
        try:
            data = json.loads(p.read_text())
        except FileNotFoundError as exc:
            raise CompatBreakError(f"schema file not found: {p}") from exc
        except json.JSONDecodeError as exc:
            raise CompatBreakError(f"schema file {p} is not valid JSON: {exc}") from exc
        return StateSchema.from_mapping(data)


@dataclass(frozen=True)
class SchemaDiff:
    """The classified structural difference between a baseline and a candidate
    schema. ``change`` is the one-word verdict; the tuples name the specific
    fields responsible so a red report can point at them."""

    change: str  # identical | additive | breaking
    added: tuple[str, ...] = ()  # new optional fields (compatible)
    removed: tuple[str, ...] = ()  # dropped fields (breaking)
    retyped: tuple[str, ...] = ()  # fields whose type changed (breaking)
    tightened: tuple[str, ...] = ()  # optional -> required (breaking)
    new_required: tuple[str, ...] = ()  # a NEW required field (breaking)

    @property
    def breaking(self) -> bool:
        return self.change == BREAKING

    def reasons(self) -> list[str]:
        """Human-readable, per-field reasons the change is breaking (empty when
        not breaking). Every reason names the mutation R-18 forbids within a
        major."""
        out: list[str] = []
        if self.removed:
            out.append(f"removed field(s) {list(self.removed)} — a reader keyed on them breaks")
        if self.retyped:
            out.append(f"changed the type of field(s) {list(self.retyped)} — a reader parsing them breaks")
        if self.tightened:
            out.append(
                f"tightened field(s) {list(self.tightened)} from optional to required — "
                f"an old writer that omits them breaks a new reader"
            )
        if self.new_required:
            out.append(
                f"added NEW required field(s) {list(self.new_required)} — an old writer "
                f"never writes them, so a new reader that requires them breaks"
            )
        return out


def diff_schemas(baseline: StateSchema, candidate: StateSchema) -> SchemaDiff:
    """Classify the structural change from ``baseline`` to ``candidate`` against
    the within-major additive+forward-tolerant contract (R-18).

    * A baseline field missing from the candidate is a **removal** (breaking).
    * A retained field whose type changed is a **retype** (breaking).
    * A retained field that went optional -> required is **tightened** (breaking).
    * A field only in the candidate is **added**; if it is required it is a
      **new-required** field (breaking — an old writer never populates it).

    ``breaking`` iff any of removal/retype/tighten/new-required occurred; else
    ``additive`` iff any (optional) field was added; else ``identical``.
    """
    removed: list[str] = []
    retyped: list[str] = []
    tightened: list[str] = []
    for name, base_spec in baseline.fields.items():
        cand_spec = candidate.fields.get(name)
        if cand_spec is None:
            removed.append(name)
            continue
        if cand_spec.type != base_spec.type:
            retyped.append(name)
        # A field going required -> optional is a LOOSENING (still forward-tolerant),
        # not a break; only optional -> required tightens the contract.
        if cand_spec.required and not base_spec.required:
            tightened.append(name)

    added: list[str] = []
    new_required: list[str] = []
    for name, cand_spec in candidate.fields.items():
        if name in baseline.fields:
            continue
        added.append(name)
        if cand_spec.required:
            new_required.append(name)

    breaking = bool(removed or retyped or tightened or new_required)
    if breaking:
        change = BREAKING
    elif added:
        change = ADDITIVE
    else:
        change = IDENTICAL

    return SchemaDiff(
        change=change,
        added=tuple(added),
        removed=tuple(removed),
        retyped=tuple(retyped),
        tightened=tuple(tightened),
        new_required=tuple(new_required),
    )


@dataclass(frozen=True)
class CompatReport:
    """The evaluated guard verdict for a (baseline -> candidate) schema change."""

    diff: SchemaDiff
    baseline_version: SemVer
    candidate_version: SemVer

    @property
    def major_bumped(self) -> bool:
        return self.candidate_version.major > self.baseline_version.major

    @property
    def requires_major_bump(self) -> bool:
        """A breaking change forces a major bump (R-19)."""
        return self.diff.breaking

    @property
    def version_regressed(self) -> bool:
        """The candidate version went backwards — a schema version only ever moves
        forward, so this is a fail-loud sanity violation."""
        return self.candidate_version.triple < self.baseline_version.triple

    @property
    def blocked(self) -> bool:
        """The one condition the guard blocks: a breaking change that did NOT bump
        the major — the silent minor ship R-19 forbids. (A regressed version is
        also blocked as a fail-loud sanity guard.)"""
        return self.version_regressed or (self.diff.breaking and not self.major_bumped)

    def block_reason(self) -> str:
        """Why the ship is blocked (empty iff shippable)."""
        if not self.blocked:
            return ""
        if self.version_regressed:
            return (
                f"schema version regressed {self.candidate_version} < "
                f"{self.baseline_version} — a schema version only moves forward"
            )
        reasons = "; ".join(self.diff.reasons())
        return (
            f"breaking shared-state schema change shipped WITHOUT a major bump "
            f"({self.baseline_version} -> {self.candidate_version}, still major "
            f"{self.candidate_version.major}): {reasons}. A same-major break is "
            f"forbidden (R-18); this change FORCES a major bump to "
            f"{self.baseline_version.major + 1}.0.0 (R-19)."
        )

    def summary(self) -> str:
        verb = {
            IDENTICAL: "IDENTICAL — no schema change",
            ADDITIVE: "ADDITIVE — new optional field(s), safe within-major",
            BREAKING: "BREAKING — forces a major bump",
        }.get(self.diff.change, self.diff.change)
        lines = [
            f"compat guard {self.baseline_version} -> {self.candidate_version}: {verb}",
        ]
        if self.diff.added:
            lines.append(f"  added: {list(self.diff.added)}")
        for r in self.diff.reasons():
            lines.append(f"  break: {r}")
        if self.blocked:
            lines.append(f"  => BLOCKED: {self.block_reason()}")
        else:
            lines.append("  => OK — shippable")
        return "\n".join(lines)


def evaluate_compat(baseline: StateSchema, candidate: StateSchema) -> CompatReport:
    """Evaluate the guard, pure. Always returns a :class:`CompatReport`; a break
    is DATA (``report.blocked``), never an exception here — only a malformed schema
    (rejected upstream in :meth:`StateSchema.from_mapping`) is fail-loud."""
    return CompatReport(
        diff=diff_schemas(baseline, candidate),
        baseline_version=baseline.version,
        candidate_version=candidate.version,
    )


def assert_shippable(baseline: StateSchema, candidate: StateSchema) -> CompatReport:
    """The guard. Raises :class:`CompatBreakError` iff the candidate is a silent
    same-major break (or a version regression); otherwise returns the report.

    This is the single blocking path — the mechanical detection R-19 mandates."""
    report = evaluate_compat(baseline, candidate)
    if report.blocked:
        raise CompatBreakError(report.block_reason())
    return report


# --- CLI ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--candidate",
        required=True,
        help="the candidate (working-tree) schema JSON to guard",
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help="the committed baseline schema JSON to diff against; omit to only "
        "self-validate the candidate is well-formed (e.g. the schema is new)",
    )
    args = parser.parse_args(argv)

    try:
        candidate = StateSchema.load(args.candidate)
        if args.baseline is None:
            print(
                f"compat guard: {args.candidate} self-validates "
                f"(schema_version {candidate.version}, {len(candidate.fields)} field(s)) "
                f"— no baseline to diff against",
                file=sys.stderr,
            )
            print(IDENTICAL)
            return 0
        baseline = StateSchema.load(args.baseline)
        report = evaluate_compat(baseline, candidate)
    except CompatBreakError as exc:
        print(f"compat-guard error: {exc}", file=sys.stderr)
        return 2

    print(report.summary(), file=sys.stderr)
    if report.blocked:
        return 2
    # stdout carries the machine verdict (identical | additive | breaking).
    print(report.diff.change)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
