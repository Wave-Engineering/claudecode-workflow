#!/usr/bin/env python3
"""Mount-manifest resolver — Story 1.3 (#963), Plan #959, Dev Spec §5.3.

The container filesystem is a disposable RTE; every piece of durable state enters
through a **declarative mount manifest** (``mounts.d/*.toml``) that this module
resolves into concrete bind-mounts for the bootstrap (Story 1.4) and the aoe
``[sandbox]`` profile. The manifest is the single source of truth for the
five-layer state taxonomy (§5.3); this resolver is the guard that keeps each
layer honest.

Guards (each fails LOUD — assertion-liveness, D7 — never silently degrades):

* **R-03 — sandbox-scoped memory.** The one rw seam into shared durable state
  (memory) MUST resolve under ``~/.oaw/state/<major>/`` and MUST NOT touch the
  live-fleet ``~/.claude`` tree. Pointing it at ``~/.claude/projects/*/memory``
  would hand a broken ``:edge`` candidate write access to the live fleet's
  memory — the exact shared-mutable-with-live-fleet disease this whole design
  cures, reintroduced at the single rw seam. Rejected here, red-first.

* **R-10 — libc boundary.** A compiled binary in the user overlay is installed
  *in* the container (``install = "in-container"``), never symlinked across the
  host/container libc boundary (a host ELF fails on ``.so``/interpreter mismatch
  in a differently-built container). Scripts and config may symlink. A
  compiled-binary artifact declared ``symlink`` is rejected.

* **R-09 / R-11 — additive composition.** Third-party / user MCP servers compose
  as an *additive fragment* (``compose = "additive"``), never by mounting the
  whole ``~/.claude.json`` (which carries far more than MCP config). The kit's
  own MCP registrations are baked at stable image paths, not mounted. The
  discretionary-tool toolbox (R-11) is a durable, in-container-materialized mount
  decoupled from the kit release.

The resolver never touches the filesystem to validate a path (sources may not
exist yet at resolve time); it reasons purely over normalized path text.

CLI::

    python3 mount_resolver.py --major 8                 # docker -v args
    python3 mount_resolver.py --major 8 --format aoe    # aoe extra_volumes lines
    python3 mount_resolver.py --major 8 --format json   # structured, for the bootstrap
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

# --- Manifest schema constants ------------------------------------------------

MANIFEST_DIR = Path(__file__).resolve().parent / "mounts.d"

# The five-layer state taxonomy (§5.3). "baked-in-image" is not a run mount (it
# is in the image), so it is not a manifest layer; the four run-layer values are.
LAYERS = {
    "shared-mutable-rw",  # memory — the one sandbox-scoped rw seam (R-03)
    "read-only-secrets",  # ~/.secrets ro mount (wired by Story 1.5)
    "user-overlay",  # MCP fragment / toolbox / user scripts (R-09/R-10/R-11)
    "durable-cache",  # CARGO_HOME, GOMODCACHE, uv, ms-playwright (§5.3)
}

MODES = {"rw", "ro"}

# user-overlay artifact classes and their REQUIRED install mechanism (R-10/R-11).
#   compiled-binary -> in-container (never symlinked across the libc boundary)
#   script/config   -> symlink      (portable across the boundary)
#   mcp-fragment    -> additive     (composed, never a whole-file mount)
#   toolbox         -> in-container (materialized durable, R-11)
OVERLAY_INSTALL = {
    "compiled-binary": "in-container",
    "script": "symlink",
    "config": "symlink",
    "mcp-fragment": "additive",
    "toolbox": "in-container",
}

# The sandbox-scoped durable-state root and the live-fleet tree that R-03 fences.
STATE_ROOT_PARTS = (".oaw", "state")  # ~/.oaw/state/<major>/...
LIVE_FLEET_ROOT_PART = ".claude"  # ~/.claude/... — never a sandbox mount source


class ManifestError(ValueError):
    """A manifest entry violates the mount contract. Raised LOUD, never swallowed."""


@dataclass(frozen=True)
class ResolvedMount:
    """A single manifest entry with ``<major>``/``~`` substituted and guards passed."""

    name: str
    layer: str
    source: str  # absolute host path
    target: str  # absolute container path
    mode: str  # rw | ro
    artifact: str | None = None
    install: str | None = None
    compose: str | None = None
    env: dict[str, str] = field(default_factory=dict)

    def to_docker_volume(self) -> str:
        """``docker run -v`` spec: ``source:target[:ro]``."""
        suffix = ":ro" if self.mode == "ro" else ""
        return f"{self.source}:{self.target}{suffix}"

    def to_aoe_extra_volume(self) -> str:
        """aoe ``[sandbox].extra_volumes`` entry (same ``-v`` spelling)."""
        return self.to_docker_volume()


# --- Path helpers (text-only; never hit the filesystem) -----------------------


def _expand(raw: str, major: int | str, home: PurePosixPath) -> str:
    """Substitute ``<major>``, ``~`` and ``$HOME`` in a manifest path string.

    Uses the *provided* home (so tests inject a fake one) rather than the process
    environment. Returns a normalized absolute POSIX path string.
    """
    s = raw.replace("<major>", str(major))
    if s == "~" or s.startswith("~/"):
        s = str(home) + s[1:]
    s = s.replace("$HOME", str(home))
    if not s.startswith("/"):
        raise ManifestError(
            f"path must resolve absolute after expansion, got {s!r} (from {raw!r})"
        )
    return os.path.normpath(s)


def _is_under(child: str, parent: PurePosixPath) -> bool:
    """True iff normalized ``child`` is ``parent`` or lives beneath it."""
    c = PurePosixPath(os.path.normpath(child))
    p = PurePosixPath(os.path.normpath(str(parent)))
    return c == p or p in c.parents


def is_compiled_binary(path: str | os.PathLike) -> bool:
    """Classify a ``~/.local/bin`` entry for R-10 routing.

    Reads the leading magic bytes: an ELF (``\\x7fELF``) is a compiled binary
    (install in-container); a ``#!`` shebang is a script (symlink-safe). Anything
    unreadable/absent is treated conservatively as *not* a plain script, so it is
    not blindly symlinked across the libc boundary.

    This is the runtime primitive the bootstrap (Story 1.4) uses to route each
    overlay artifact; the manifest declares the mechanism per *layer*, this
    classifies an individual *file*.
    """
    try:
        with open(path, "rb") as fh:
            magic = fh.read(4)
    except OSError:
        return True  # conservative: don't symlink something we can't read
    if magic[:4] == b"\x7fELF":
        return True
    if magic[:2] == b"#!":
        return False
    # Unknown magic: treat as a binary (safer to install-in-container than to
    # symlink a possible ELF across the boundary).
    return True


# --- Per-guard validators (individually callable so tests can target them) -----


def check_sandbox_scoped_memory(source: str, major: int | str, home: PurePosixPath) -> None:
    """R-03: a sandbox-scoped rw source is under ``~/.oaw/state/<major>/`` and
    never inside the live-fleet ``~/.claude`` tree. Raises on violation."""
    state_root = home.joinpath(*STATE_ROOT_PARTS, str(major))
    live_root = home.joinpath(LIVE_FLEET_ROOT_PART)

    if _is_under(source, live_root):
        raise ManifestError(
            f"R-03 VIOLATION: sandbox memory source {source!r} is inside the "
            f"live-fleet tree {str(live_root)!r}. The rw memory mount must NEVER "
            f"point at ~/.claude (e.g. ~/.claude/projects/*/memory) — a broken "
            f":edge candidate would gain write access to the live fleet's memory. "
            f"Use a sandbox-scoped path under ~/.oaw/state/<major>/."
        )
    if not _is_under(source, state_root):
        raise ManifestError(
            f"R-03 VIOLATION: sandbox memory source {source!r} is not under the "
            f"sandbox-scoped state root {str(state_root)!r}. The one rw seam into "
            f"durable state must live under ~/.oaw/state/<major>/ so the major "
            f"partitions the namespace (R-20)."
        )


def check_overlay_install(entry: dict) -> None:
    """R-10/R-11: a user-overlay entry's install mechanism matches its artifact.

    compiled-binary/toolbox -> in-container; script/config -> symlink;
    mcp-fragment -> additive. A compiled binary declared ``symlink`` is the R-10
    libc-boundary bug and is rejected."""
    artifact = entry.get("artifact")
    if artifact is None:
        raise ManifestError(
            f"user-overlay mount {entry.get('name')!r} must declare an `artifact` "
            f"(one of {sorted(OVERLAY_INSTALL)})"
        )
    if artifact not in OVERLAY_INSTALL:
        raise ManifestError(
            f"user-overlay mount {entry.get('name')!r} has unknown artifact "
            f"{artifact!r}; expected one of {sorted(OVERLAY_INSTALL)}"
        )
    required = OVERLAY_INSTALL[artifact]
    declared = entry.get("install", required)
    if declared != required:
        raise ManifestError(
            f"R-10 VIOLATION: user-overlay mount {entry.get('name')!r} is a "
            f"{artifact!r} but declares install={declared!r}; it MUST be "
            f"{required!r}. A compiled binary symlinked across the host/container "
            f"libc boundary fails on .so/interpreter mismatch — install it "
            f"in-container instead."
        )


def check_mcp_additive(entry: dict, source: str) -> None:
    """R-09/R-11: an MCP overlay is an additive *fragment*, never the whole
    ``~/.claude.json``. Raises on violation."""
    if entry.get("compose") != "additive":
        raise ManifestError(
            f"R-09 VIOLATION: MCP overlay {entry.get('name')!r} must set "
            f"compose='additive' — third-party/user MCPs compose additively with "
            f"the baked kit registrations, they never replace them."
        )
    if PurePosixPath(source).name == ".claude.json":
        raise ManifestError(
            f"R-09 VIOLATION: MCP overlay {entry.get('name')!r} mounts the whole "
            f"~/.claude.json ({source!r}); mount only an MCP *fragment*. "
            f"~/.claude.json carries far more than MCP config (see docs/mcp-scoping.md)."
        )


# --- Manifest load + resolve --------------------------------------------------


def load_manifest(mounts_dir: Path = MANIFEST_DIR) -> list[dict]:
    """Load every ``*.toml`` fragment in ``mounts_dir``, filename-sorted.

    Drop-in ordering: ``NN-name.toml`` fragments apply in lexical order so an
    operator can slot a fragment deterministically. Each file may hold one or
    more ``[[mount]]`` tables."""
    if not mounts_dir.is_dir():
        raise ManifestError(f"mounts.d manifest directory not found: {mounts_dir}")
    mounts: list[dict] = []
    for toml_path in sorted(mounts_dir.glob("*.toml")):
        with toml_path.open("rb") as fh:
            data = tomllib.load(fh)
        for entry in data.get("mount", []):
            entry = dict(entry)
            entry.setdefault("_fragment", toml_path.name)
            mounts.append(entry)
    return mounts


def resolve_mount(entry: dict, major: int | str, home: PurePosixPath) -> ResolvedMount:
    """Validate + resolve one manifest entry into a ``ResolvedMount`` (all guards
    applied). Raises ``ManifestError`` on any contract violation."""
    name = entry.get("name")
    if not name:
        raise ManifestError(f"mount entry missing `name`: {entry!r}")
    layer = entry.get("layer")
    if layer not in LAYERS:
        raise ManifestError(
            f"mount {name!r} has invalid layer {layer!r}; expected one of {sorted(LAYERS)}"
        )
    mode = entry.get("mode")
    if mode not in MODES:
        raise ManifestError(
            f"mount {name!r} has invalid mode {mode!r}; expected one of {sorted(MODES)}"
        )
    raw_source = entry.get("source")
    raw_target = entry.get("target")
    if not raw_source or not raw_target:
        raise ManifestError(f"mount {name!r} must declare both `source` and `target`")

    source = _expand(raw_source, major, home)
    target = _expand(raw_target, major, home)

    # R-03: the shared-mutable-rw seam (and anything explicitly sandbox_scoped)
    # must resolve sandbox-scoped and clear of the live-fleet tree.
    if layer == "shared-mutable-rw" or entry.get("sandbox_scoped"):
        check_sandbox_scoped_memory(source, major, home)

    # read-only-secrets is inherently ro (fail loud if a fragment says otherwise).
    if layer == "read-only-secrets" and mode != "ro":
        raise ManifestError(
            f"R-12 VIOLATION: secrets mount {name!r} must be mode='ro'; got {mode!r}"
        )

    artifact = entry.get("artifact")
    install = entry.get("install")
    compose = entry.get("compose")
    if layer == "user-overlay":
        check_overlay_install(entry)
        install = entry.get("install", OVERLAY_INSTALL[artifact])
        if artifact == "mcp-fragment":
            check_mcp_additive(entry, source)

    env = entry.get("env") or {}
    if not isinstance(env, dict):
        raise ManifestError(f"mount {name!r} `env` must be a table, got {type(env).__name__}")

    return ResolvedMount(
        name=name,
        layer=layer,
        source=source,
        target=target,
        mode=mode,
        artifact=artifact,
        install=install,
        compose=compose,
        env={str(k): str(v) for k, v in env.items()},
    )


def resolve_manifest(
    major: int | str,
    home: str | os.PathLike | None = None,
    mounts_dir: Path = MANIFEST_DIR,
) -> list[ResolvedMount]:
    """Load and fully resolve the manifest for a given kit ``major`` version.

    ``home`` defaults to the runtime user's ``$HOME``; tests inject a fake root.
    """
    home_path = PurePosixPath(str(home) if home is not None else os.path.expanduser("~"))
    return [resolve_mount(e, major, home_path) for e in load_manifest(mounts_dir)]


# --- CLI ----------------------------------------------------------------------


def _major_from(value: str) -> int:
    """Accept a bare major (``8``) or a full semver (``8.1.0``) → major int."""
    head = value.split(".", 1)[0]
    try:
        return int(head)
    except ValueError as exc:  # noqa: TRY003
        raise SystemExit(f"--major must be an int or semver, got {value!r}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--major",
        required=True,
        help="kit major version (int) or full semver (major extracted)",
    )
    parser.add_argument("--home", default=None, help="override $HOME (test/dry-run)")
    parser.add_argument(
        "--format",
        choices=("docker", "aoe", "json"),
        default="docker",
        help="output shape (default: docker -v args)",
    )
    parser.add_argument(
        "--mounts-dir",
        default=str(MANIFEST_DIR),
        help="manifest directory (default: ./mounts.d)",
    )
    args = parser.parse_args(argv)

    major = _major_from(args.major)
    try:
        resolved = resolve_manifest(major, home=args.home, mounts_dir=Path(args.mounts_dir))
    except ManifestError as exc:
        print(f"mount-manifest error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        payload = [
            {
                "name": m.name,
                "layer": m.layer,
                "source": m.source,
                "target": m.target,
                "mode": m.mode,
                "artifact": m.artifact,
                "install": m.install,
                "compose": m.compose,
                "env": m.env,
            }
            for m in resolved
        ]
        print(json.dumps(payload, indent=2))
    elif args.format == "aoe":
        for m in resolved:
            print(m.to_aoe_extra_volume())
    else:  # docker
        for m in resolved:
            print(f"-v {m.to_docker_volume()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
