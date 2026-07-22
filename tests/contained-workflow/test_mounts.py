"""Oracle for Story 1.3 — the mount-manifest resolver (#963, Dev Spec §5.3).

The resolver (``containers/oakandwave-workflow/mount_resolver.py``) is the guard
that keeps the five-layer state taxonomy honest. These are *pure* unit oracles —
no docker, no aoe, no filesystem sources — so they run for real in the stock
``pytest tests/`` lane. Each guard is exercised red-first (the violation raises)
and green (the correct shape resolves).

Coverage:

* ``test_memory_source_scoped`` — the named story oracle: a live-fleet memory
  source is rejected; a sandbox-scoped one is accepted `[R-03]`.
* ``test_compiled_binary_installs_in_container`` — a compiled-binary overlay
  symlink is rejected; classification routes ELF→in-container, shebang→symlink
  `[R-10]`.
* ``test_mcp_composes_additively`` — a non-additive or whole-``.claude.json`` MCP
  overlay is rejected; the fragment shape resolves `[R-09, R-11]`.
* ``test_manifest_resolves`` — the checked-in ``mounts.d/`` manifest resolves
  clean end-to-end `[R-03, R-09, R-10, R-11]`.
"""

from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTAINER_DIR = REPO_ROOT / "containers" / "oakandwave-workflow"
MANIFEST_DIR = CONTAINER_DIR / "mounts.d"

# The resolver is a self-contained module colocated with the manifest; import it
# by path (no PYTHONPATH dependency), mirroring test_ownership.py's REPO_ROOT style.
sys.path.insert(0, str(CONTAINER_DIR))
import mount_resolver as mr  # noqa: E402

FAKE_HOME = PurePosixPath("/home/bakerb")
MAJOR = 8


def _resolve_one(entry: dict, major: int = MAJOR, home: PurePosixPath = FAKE_HOME):
    return mr.resolve_mount(entry, major, home)


# --- R-03: sandbox-scoped memory (the named story oracle) ---------------------


def test_memory_source_scoped() -> None:
    """R-03: a live-fleet memory source is rejected; a sandbox-scoped one accepted.

    This is the story's canonical oracle. The rw memory mount is the single seam
    into shared durable state — pointing it at the live ``~/.claude`` tree would
    hand a broken ``:edge`` candidate write access to the fleet's memory.
    """
    base = {
        "name": "memory",
        "layer": "shared-mutable-rw",
        "mode": "rw",
        "target": "/home/ubuntu/.claude/projects/_sandbox/memory",
    }

    # ACCEPT — sandbox-scoped under ~/.oaw/state/<major>/.
    ok = _resolve_one({**base, "source": "~/.oaw/state/<major>/memory"})
    assert ok.source == "/home/bakerb/.oaw/state/8/memory"
    assert ok.mode == "rw"

    # REJECT — the live-fleet memory tree (the exact disease R-03 fences).
    with pytest.raises(mr.ManifestError, match="R-03"):
        _resolve_one({**base, "source": "~/.claude/projects/foo/memory"})

    # REJECT — anywhere under ~/.claude, even if not literally .../memory.
    with pytest.raises(mr.ManifestError, match="R-03"):
        _resolve_one({**base, "source": "~/.claude/projects"})

    # REJECT — off the sandbox-scoped state root entirely (e.g. an arbitrary dir).
    with pytest.raises(mr.ManifestError, match="R-03"):
        _resolve_one({**base, "source": "~/somewhere-else/memory"})

    # REJECT — the WRONG major's state root (namespace partition, R-20): major 9
    # state is not sandbox-scoped for a major-8 resolve.
    with pytest.raises(mr.ManifestError, match="R-03"):
        _resolve_one({**base, "source": "~/.oaw/state/9/memory"})


def test_sandbox_scoped_flag_applies_guard_to_any_layer() -> None:
    """The R-03 guard fires on any mount flagged ``sandbox_scoped``, not only the
    memory layer — a durable-cache mislabeled into the live tree is still caught."""
    entry = {
        "name": "settings-local",
        "layer": "shared-mutable-rw",
        "mode": "rw",
        "sandbox_scoped": True,
        "source": "~/.claude/settings.local.json",
        "target": "/home/ubuntu/.claude/settings.local.json",
    }
    with pytest.raises(mr.ManifestError, match="R-03"):
        _resolve_one(entry)


# --- R-10: compiled binaries install in-container -----------------------------


def test_compiled_binary_installs_in_container() -> None:
    """R-10: a compiled-binary overlay must install in-container, never symlink."""
    good = {
        "name": "user-bin",
        "layer": "user-overlay",
        "artifact": "compiled-binary",
        "mode": "rw",
        "source": "~/.oaw/overlay/<major>/bin",
        "target": "/home/ubuntu/.oaw/overlay/bin",
    }
    resolved = _resolve_one(good)
    assert resolved.install == "in-container"

    # REJECT — a compiled binary declared symlink is the libc-boundary bug.
    with pytest.raises(mr.ManifestError, match="R-10"):
        _resolve_one({**good, "install": "symlink"})

    # Scripts/config default to symlink and resolve clean.
    script = {
        "name": "user-scripts",
        "layer": "user-overlay",
        "artifact": "script",
        "mode": "rw",
        "source": "~/.oaw/overlay/<major>/local-bin",
        "target": "/home/ubuntu/.oaw/overlay/local-bin",
    }
    assert _resolve_one(script).install == "symlink"


def test_is_compiled_binary_classifier(tmp_path: Path) -> None:
    """The runtime file classifier the bootstrap uses to route each ~/.local/bin
    entry: ELF magic -> in-container; shebang -> symlink; unreadable -> conservative."""
    elf = tmp_path / "an-elf"
    elf.write_bytes(b"\x7fELF\x02\x01\x01\x00rest")
    assert mr.is_compiled_binary(elf) is True

    script = tmp_path / "a-script"
    script.write_text("#!/usr/bin/env bash\necho hi\n")
    assert mr.is_compiled_binary(script) is False

    # Absent path: conservatively NOT a plain script (don't symlink a possible ELF).
    assert mr.is_compiled_binary(tmp_path / "does-not-exist") is True


# --- R-09 / R-11: additive MCP composition ------------------------------------


def test_mcp_composes_additively() -> None:
    """R-09/R-11: an MCP overlay composes additively as a fragment, never as the
    whole ~/.claude.json."""
    good = {
        "name": "mcp-fragment",
        "layer": "user-overlay",
        "artifact": "mcp-fragment",
        "compose": "additive",
        "mode": "ro",
        "source": "~/.oaw/overlay/<major>/mcp.json",
        "target": "/home/ubuntu/.oaw/overlay/mcp.json",
    }
    resolved = _resolve_one(good)
    assert resolved.compose == "additive"

    # REJECT — a non-additive (replacing) MCP overlay.
    with pytest.raises(mr.ManifestError, match="R-09"):
        _resolve_one({**good, "compose": "replace"})

    # REJECT — mounting the whole ~/.claude.json (carries far more than MCP config).
    with pytest.raises(mr.ManifestError, match="R-09"):
        _resolve_one(
            {
                **good,
                "source": "~/.claude.json",
                "target": "/home/ubuntu/.claude.json",
            }
        )


def test_toolbox_is_durable_in_container() -> None:
    """R-11: the discretionary-tool toolbox is a durable, in-container mount."""
    resolved = _resolve_one(
        {
            "name": "toolbox",
            "layer": "user-overlay",
            "artifact": "toolbox",
            "mode": "rw",
            "source": "~/.oaw/toolbox/<major>",
            "target": "/home/ubuntu/.oaw/toolbox",
        }
    )
    assert resolved.install == "in-container"
    assert resolved.mode == "rw"


# --- Schema / structural guards -----------------------------------------------


def test_secrets_layer_must_be_readonly() -> None:
    """R-12: the read-only-secrets layer rejects a rw mode (guards Story 1.5's
    drop-in fragment against a fat-finger)."""
    entry = {
        "name": "secrets",
        "layer": "read-only-secrets",
        "mode": "rw",
        "source": "~/.secrets",
        "target": "/home/ubuntu/.secrets",
    }
    with pytest.raises(mr.ManifestError, match="R-12"):
        _resolve_one(entry)


def test_invalid_layer_and_mode_rejected() -> None:
    """Unknown layer / mode fail loud rather than silently pass."""
    with pytest.raises(mr.ManifestError, match="invalid layer"):
        _resolve_one(
            {"name": "x", "layer": "bogus", "mode": "rw", "source": "/a", "target": "/b"}
        )
    with pytest.raises(mr.ManifestError, match="invalid mode"):
        _resolve_one(
            {
                "name": "x",
                "layer": "durable-cache",
                "mode": "append",
                "source": "/a",
                "target": "/b",
            }
        )


# --- End-to-end: the checked-in manifest resolves clean -----------------------


def test_manifest_resolves() -> None:
    """The real ``mounts.d/`` manifest loads and fully resolves with every guard
    applied `[R-03, R-09, R-10, R-11]`."""
    resolved = mr.resolve_manifest(MAJOR, home=FAKE_HOME, mounts_dir=MANIFEST_DIR)
    by_name = {m.name: m for m in resolved}

    # The three layers Story 1.3 owns are all present.
    assert "memory" in by_name
    assert "mcp-fragment" in by_name
    assert "toolbox" in by_name
    assert any(m.layer == "durable-cache" for m in resolved)

    # The memory mount resolved sandbox-scoped under this major.
    assert by_name["memory"].source == "/home/bakerb/.oaw/state/8/memory"

    # No manifest mount points into the live-fleet ~/.claude tree as its source.
    for m in resolved:
        assert not m.source.startswith("/home/bakerb/.claude"), (
            f"mount {m.name!r} sources from the live-fleet tree: {m.source}"
        )

    # The MCP overlay is an additive fragment, not a whole-file mount.
    mcp = by_name["mcp-fragment"]
    assert mcp.compose == "additive"
    assert not mcp.source.endswith(".claude.json")

    # Durable caches carry their env wiring for the bootstrap to export.
    cargo = by_name["cargo"]
    assert cargo.env.get("CARGO_HOME") == "/home/ubuntu/.cargo"

    # docker -v rendering round-trips (ro suffix only on ro mounts).
    assert mcp.to_docker_volume().endswith(":ro")
    assert not by_name["memory"].to_docker_volume().endswith(":ro")


def test_manifest_dir_exists() -> None:
    """DM sanity: the manifest directory and the fragments Story 1.3 owns are
    checked in. A superset check (not exact equality) so a sibling wave story —
    Story 1.5's ``20-secrets.toml`` — can drop a fragment in without tripping
    this oracle."""
    assert MANIFEST_DIR.is_dir(), f"missing manifest dir: {MANIFEST_DIR}"
    fragments = {p.name for p in MANIFEST_DIR.glob("*.toml")}
    owned = {"10-memory.toml", "30-user-overlay.toml", "40-durable-caches.toml"}
    missing = owned - fragments
    assert not missing, f"missing Story 1.3 manifest fragments: {sorted(missing)}"
