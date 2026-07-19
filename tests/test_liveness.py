"""Tests for session liveness detection — the ONE implementation shared by
scripts/skill-gc and scripts/find-projects (cc-workflow#919).

Why this file exists
--------------------
`session_liveness()` used to claim a fail-closed contract whose "strong signal"
was *a process holding the transcript fd open*. Claude Code appends and closes,
so that branch never fired. Swept on one workstation (single-host figures): 0 of
277 transcripts were held open across 10,613 open fds, so everything fell through
to a 60-second mtime window and 10 of 14 live sessions there classified as
STOPPED — eligible for transcript surgery by skill-gc/reorient.

The old suite passed throughout, because `test_detects_open_fd_as_live` opened
the fd *itself* and `test_stopped_vs_running` monkeypatched `_liveness` away.
Both tested a path production never takes. These tests drive the real detector.

Fixture policy (charter): transcripts are sampled from REAL sessions under
``~/.claude/projects``; ``_transcript_body()`` records its provenance and
``test_fixture_provenance_is_real_when_available`` fails if a real store was
present but not used. The /proc trees ARE built here — /proc is an OS interface,
not a Claude Code format, and its shape (NUL-separated ``cmdline``, ``cwd``
symlink) is stable and reproduced faithfully.

Every cmdline shape below was observed in the live fleet:
    --resume <uuid>                          pid 15393
    --session-id <uuid>                      pid 604936
    --resume=<uuid>                          pid 1443845  (equals form)
    --resume /abs/path/<uuid>.jsonl          pid 971722   (path-valued)
    --append-system-prompt "...<uuid>..."    pid 2718036  (NOT a session — grunt id)
"""

from __future__ import annotations

import glob
import importlib.machinery
import importlib.util
import json
import os
import time

import pytest

_HERE = os.path.dirname(__file__)


def _load(name, script):
    path = os.path.join(_HERE, "..", "scripts", script)
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_file_location(name, path, loader=loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


sg = _load("skill_gc", "skill-gc")
fp = _load("find_projects", "find-projects")

# Fixture uuids are deliberately NOT any session that could exist on a real host:
# an earlier draft used a live agent's real uuid and one test passed against the
# REAL /proc rather than the fixture — green, and proving nothing.
LIVE_UUID = "ffffffff-0000-4000-8000-000000000001"
OTHER_UUID = "ffffffff-0000-4000-8000-000000000002"
GRUNT_UUID = "ffffffff-0000-4000-8000-000000000003"
PROJECT_CWD = "/home/x/proj"
STALE = 8 * 3600  # 8h idle — far beyond LIVE_WINDOW_SECS, like the real fleet


# --------------------------------------------------------------------------- #
# real-transcript fixture sourcing
# --------------------------------------------------------------------------- #
def _real_transcript_head():
    """Lines from a REAL session transcript carrying an intact Skill tool_use ->
    tool_result -> isMeta body chain, or None if no such store exists.

    The chain matters: without a real evictable body, `targets` is empty and every
    "the file was not modified" assertion in the refusal tests holds trivially —
    they would pass even if the gate did nothing. Chain location uses skill-gc's own
    identifier, so the fixture is whatever production actually recognises.
    """
    for p in sorted(glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")),
                    key=os.path.getsize):
        try:
            raw = open(p, encoding="utf-8").read().splitlines(keepends=True)
            events = sg.parse_aligned(raw)
        except (OSError, ValueError):
            continue
        targets = sg.find_skill_body_indices(events)
        if not targets:
            continue
        body_i = min(targets)
        parent = events[body_i].get("parentUuid")
        result_i = next((k for k, e in enumerate(events)
                         if isinstance(e, dict) and e.get("uuid") == parent), None)
        if result_i is None:
            continue
        use_id = next((b.get("tool_use_id") for b in sg._content(events[result_i])
                       if b.get("type") == "tool_result"), None)
        use_i = next((k for k, e in enumerate(events)
                      if any(b.get("type") == "tool_use" and b.get("id") == use_id
                             for b in sg._content(e))), None)
        if use_i is None:
            continue
        keep = sorted({0, use_i, result_i, body_i})
        return [raw[k] for k in keep]
    return None


_REAL_LINES = _real_transcript_head()
FIXTURE_PROVENANCE = "real" if _REAL_LINES else "shape-derived"
# Whether the fixture carries a genuine evictable skill body. Assertions that a
# refusal PREVENTED a write are only meaningful when it does.
HAS_REAL_BODY = _REAL_LINES is not None
needs_real_body = pytest.mark.skipif(
    not HAS_REAL_BODY, reason="no real skill-body chain on this host (CI); gate rc still asserted")


def _transcript_body(cwd=PROJECT_CWD):
    """Transcript lines with `cwd` normalised to `cwd`.

    Real-sourced when a session store is available, including a genuine skill-body
    chain. The fallback reproduces the measured shape: the FIRST record is a summary
    carrying sessionId/leafUuid and **no cwd** — 0 of 80 sampled transcripts had cwd
    on line 1, all 80 had it later. A reader that only inspects line 1 finds nothing.
    """
    if _REAL_LINES:
        out = []
        for line in _REAL_LINES:
            try:
                ev = json.loads(line)
            except ValueError:
                out.append(line)
                continue
            if ev.get("cwd"):
                ev["cwd"] = cwd
            out.append(json.dumps(ev) + "\n")
        assert any('"cwd"' in ln for ln in out), "real fixture lost its cwd record"
        return out
    return [
        json.dumps({"type": "summary", "sessionId": LIVE_UUID, "leafUuid": "x",
                    "timestamp": "2020-01-01T00:00:00.000Z"}) + "\n",
        json.dumps({"type": "user", "cwd": cwd, "timestamp": "2020-01-01T00:00:01.000Z",
                    "message": {"role": "user", "content": "hi"}}) + "\n",
    ]


def _transcript(tmp_path, uuid=LIVE_UUID, idle=STALE, cwd=PROJECT_CWD, store=None):
    d = tmp_path / (store or "store")
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{uuid}.jsonl"
    p.write_text("".join(_transcript_body(cwd)), encoding="utf-8")
    t = time.time() - idle
    os.utime(p, (t, t))
    return str(p)


# --------------------------------------------------------------------------- #
# fake /proc
# --------------------------------------------------------------------------- #
def _proc(tmp_path, procs, name="proc", bare=False):
    """Build a /proc-shaped tree. `procs` is [(pid, argv, cwd_or_None), ...].

    Reproduces the real interface: cmdline is NUL-separated and NUL-terminated,
    cwd is a symlink. A benign init process is always present unless `bare` — a
    real /proc always contains at least the scanning process, so a pid-less tree
    means a blinded scan, not a quiet machine.
    """
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    if not bare:
        procs = [(1, ["/sbin/init", "splash"], "/")] + list(procs)
    for pid, argv, cwd in procs:
        d = root / str(pid)
        d.mkdir()
        (d / "cmdline").write_bytes(b"".join(a.encode() + b"\0" for a in argv))
        if cwd:
            os.symlink(cwd, d / "cwd")
    return str(root)


CLAUDE = "claude"


def _agent(uuid, flag="--resume", form="space"):
    """A real fleet cmdline for a session, in one of the observed flag forms."""
    base = [CLAUDE, "--dangerously-skip-permissions"]
    if form == "space":
        return base + [flag, uuid]
    if form == "equals":
        return base + [f"{flag}={uuid}"]
    if form == "path":
        return base + [flag, f"/home/bakerb/.claude/projects/-home-x-proj/{uuid}.jsonl"]
    raise AssertionError(form)


def _use_proc(monkeypatch, root):
    """Point EVERY loaded skill-gc instance at `root`.

    find-projects loads its own instance of skill-gc via SourceFileLoader — one
    implementation, two module objects — so patching only this file's handle leaves
    find-projects scanning the REAL /proc. An earlier draft rebound `fp._SG = sg` to
    sidestep that; it went green against a live agent's real uuid instead of its
    fixture, proving nothing. Patching each instance drives the genuine load path
    rather than compensating for it.
    """
    for mod in {id(m): m for m in (sg, fp._SG) if m is not None}.values():
        monkeypatch.setattr(mod, "PROC_ROOT", root, raising=False)
    return root


@pytest.fixture(autouse=True)
def _isolate_proc(monkeypatch, tmp_path):
    """Point every test at a process-free /proc so nothing leaks from the real host."""
    _use_proc(monkeypatch, _proc(tmp_path, [], name="empty-proc"))


def test_find_projects_uses_skill_gc_as_its_liveness_engine():
    """The shared-implementation AC, asserted against the module find-projects
    actually loaded — no rebinding involved."""
    assert fp._SG is not None, "find-projects could not load skill-gc"
    assert os.path.realpath(fp._SG.__file__) == os.path.realpath(sg.__file__)
    assert not hasattr(fp, "session_liveness"), "find-projects grew its own copy"
    assert fp._SG.session_liveness.__code__.co_consts == sg.session_liveness.__code__.co_consts


# --------------------------------------------------------------------------- #
# the regression that matters
# --------------------------------------------------------------------------- #
def test_live_but_idle_agent_is_live(tmp_path, monkeypatch):
    """THE #919 regression: an agent idle far beyond LIVE_WINDOW_SECS whose
    process is alive must classify live. 10 of 14 real sessions failed this."""
    t = _transcript(tmp_path, idle=STALE)
    _use_proc(monkeypatch,
                        _proc(tmp_path, [(4242, _agent(LIVE_UUID), PROJECT_CWD)]))
    assert time.time() - os.path.getmtime(t) > sg.LIVE_WINDOW_SECS  # genuinely stale
    assert sg.session_liveness(t) == "live"


@pytest.mark.parametrize("flag,form", [
    ("--resume", "space"),      # pid 15393
    ("--session-id", "space"),  # pid 604936
    ("--resume", "equals"),     # pid 1443845
    ("--resume", "path"),       # pid 971722
    ("--session-id", "equals"),
])
def test_every_observed_cmdline_form_detects_live(tmp_path, monkeypatch, flag, form):
    t = _transcript(tmp_path, idle=STALE)
    _use_proc(monkeypatch,
                        _proc(tmp_path, [(4242, _agent(LIVE_UUID, flag, form), PROJECT_CWD)]))
    assert sg.session_liveness(t) == "live"


def test_short_resume_flag_on_a_claude_cmdline_detects_live(tmp_path, monkeypatch):
    """`claude -r <uuid>` is a documented short form a human will actually type."""
    t = _transcript(tmp_path, idle=STALE)
    _use_proc(monkeypatch,
                        _proc(tmp_path, [(4242, [CLAUDE, "-r", LIVE_UUID], PROJECT_CWD)]))
    assert sg.session_liveness(t) == "live"


def test_short_resume_flag_on_a_non_claude_cmdline_is_ignored(tmp_path, monkeypatch):
    """...but `-r` is far too common to honour everywhere. A grep over the session
    store must not register as a live agent."""
    t = _transcript(tmp_path, idle=STALE)
    argv = ["grep", "-r", f"{LIVE_UUID}.jsonl", "/home/bakerb/.claude/projects"]
    _use_proc(monkeypatch, _proc(tmp_path, [(4242, argv, PROJECT_CWD)]))
    assert sg.session_liveness(t) == "idle"


def test_fork_session_without_an_explicit_id_is_unknown(tmp_path, monkeypatch):
    """`--fork-session` mints a NEW session id. `claude --resume A --fork-session`
    therefore writes a transcript whose uuid appears nowhere on the cmdline, so
    naming A must not be mistaken for having accounted for the process. Without
    this, the forked session falls back to the 60s window — the very hole #919 is
    about. Every --fork-session in the observed fleet also carried --session-id,
    which is exactly why this case is easy to miss."""
    t = _transcript(tmp_path, uuid=LIVE_UUID, idle=STALE, cwd=PROJECT_CWD)
    argv = [CLAUDE, "--resume", OTHER_UUID, "--fork-session"]
    _use_proc(monkeypatch, _proc(tmp_path, [(4242, argv, PROJECT_CWD)]))
    assert sg.session_liveness(t) == "unknown"


def test_fork_session_with_an_explicit_id_does_not_over_poison(tmp_path, monkeypatch):
    """...but when the forked session IS named (`--session-id B --fork-session
    --resume A`, the fleet's own form, pid 971722), the process is fully accounted
    for and must not blanket its cwd — that would strip every co-located session of
    collectability for no gain."""
    named = _transcript(tmp_path, uuid=LIVE_UUID, idle=STALE, cwd=PROJECT_CWD)
    bystander = _transcript(tmp_path, uuid=OTHER_UUID, idle=STALE, cwd=PROJECT_CWD,
                            store="other-store")
    argv = [CLAUDE, "--session-id", LIVE_UUID, "--fork-session",
            "--resume", "ffffffff-0000-4000-8000-00000000000a"]
    _use_proc(monkeypatch, _proc(tmp_path, [(971722, argv, PROJECT_CWD)]))
    assert sg.session_liveness(named) == "live"
    assert sg.session_liveness(bystander) == "idle"


def test_deleted_cwd_suffix_does_not_dissolve_the_doubt(tmp_path, monkeypatch):
    """The kernel appends a literal ' (deleted)' to /proc/<pid>/cwd once the
    directory is unlinked (observed on this host via /proc/274519/exe). Left
    unstripped, the doubt is recorded as '/home/x/proj (deleted)', never matches the
    transcript's '/home/x/proj', and the session silently reads idle. Reachable
    here: `git worktree remove` under a still-running agent."""
    t = _transcript(tmp_path, idle=STALE, cwd=PROJECT_CWD)
    _use_proc(monkeypatch,
                        _proc(tmp_path, [(5150, [CLAUDE, "--continue"],
                                          PROJECT_CWD + " (deleted)")]))
    assert sg.session_liveness(t) == "unknown"


def test_fork_session_equals_form_is_detected(tmp_path, monkeypatch):
    """`--fork-session=true` — commander accepts `=value` for boolean flags, and an
    exact-element `in argv` test would miss it, restoring the fork fail-open."""
    t = _transcript(tmp_path, uuid=LIVE_UUID, idle=STALE, cwd=PROJECT_CWD)
    argv = [CLAUDE, "--resume", OTHER_UUID, "--fork-session=true"]
    _use_proc(monkeypatch, _proc(tmp_path, [(4242, argv, PROJECT_CWD)]))
    assert sg.session_liveness(t) == "unknown"


def test_two_word_argv0_is_not_missed(tmp_path, monkeypatch):
    """`claude bg-pty-host` arrives as a single two-word argv[0] (pids 971657,
    977963). A basename=='claude' filter would drop 4 real live sessions."""
    t = _transcript(tmp_path, idle=STALE)
    argv = ["claude bg-pty-host", "--bg-pty-host", "/tmp/x.sock", "--",
            "/home/bakerb/.local/share/claude/versions/2.1.215",
            "--resume", f"/home/bakerb/.claude/projects/-home-x-proj/{LIVE_UUID}.jsonl"]
    _use_proc(monkeypatch, _proc(tmp_path, [(971657, argv, PROJECT_CWD)]))
    assert sg.session_liveness(t) == "live"


def test_versioned_binary_argv0_is_not_missed(tmp_path, monkeypatch):
    """pid 971722 execs the version binary directly — argv[0] has no 'claude'
    basename at all, yet it owns a live session."""
    t = _transcript(tmp_path, idle=STALE)
    argv = ["/home/bakerb/.local/share/claude/versions/2.1.215",
            "--session-id", LIVE_UUID, "--fork-session"]
    _use_proc(monkeypatch, _proc(tmp_path, [(971722, argv, PROJECT_CWD)]))
    assert sg.session_liveness(t) == "live"


# --------------------------------------------------------------------------- #
# no over-matching (the fix must not fail *closed* everywhere either)
# --------------------------------------------------------------------------- #
def test_unrelated_session_process_leaves_us_idle(tmp_path, monkeypatch):
    t = _transcript(tmp_path, uuid=LIVE_UUID, idle=STALE)
    _use_proc(monkeypatch,
                        _proc(tmp_path, [(4242, _agent(OTHER_UUID), "/somewhere/else")]))
    assert sg.session_liveness(t) == "idle"


def test_uuid_in_append_system_prompt_is_not_a_session(tmp_path, monkeypatch):
    """pid 2718036 carries a grunt id inside --append-system-prompt. A naive
    'any UUID in cmdline' scan false-positives on 8 such ids in the live fleet."""
    t = _transcript(tmp_path, uuid=GRUNT_UUID, idle=STALE)
    argv = [CLAUDE, "--append-system-prompt",
            f"You are the {GRUNT_UUID} grunt. Read seed-mission.md.",
            "--session-id", OTHER_UUID]
    _use_proc(monkeypatch, _proc(tmp_path, [(2718036, argv, "/somewhere/else")]))
    assert sg.session_liveness(t) == "idle"


# --------------------------------------------------------------------------- #
# fail-closed preservation
# --------------------------------------------------------------------------- #
def test_absent_proc_is_unknown(tmp_path, monkeypatch):
    """No /proc (macOS, hardened container) → unknown, never idle."""
    t = _transcript(tmp_path, idle=STALE)
    _use_proc(monkeypatch, str(tmp_path / "nonexistent-proc"))
    assert sg.session_liveness(t) == "unknown"


def test_proc_with_unreadable_cmdlines_is_unknown(tmp_path, monkeypatch):
    """A /proc whose pid dirs exist but expose no readable cmdline — a corrupt or
    restricted mount. A blinded scan must be observably different from a healthy
    scan reporting all-clear.

    Deliberately NOT called a hidepid test: under real hidepid a process can always
    read its own /proc/self/cmdline, so readable >= 1 and the sweep returns a
    populated-but-partial result rather than None. Naming this hidepid would claim a
    guarantee the code does not provide — the exact failure #919 is about.

    That partial-readability gap is real and unclosed; it is tracked as #923 with a
    reproduction, rather than left as a comment nobody can act on.
    """
    root = tmp_path / "hidden-proc"
    (root / "4242").mkdir(parents=True)  # pid dir, no cmdline file
    (root / "4243").mkdir(parents=True)
    t = _transcript(tmp_path, idle=STALE)
    _use_proc(monkeypatch, str(root))
    assert sg.session_liveness(t) == "unknown"


def test_proc_with_no_pids_at_all_is_unknown(tmp_path, monkeypatch):
    """A /proc containing no pid dirs cannot be real — we are ourselves a process.
    Treat it as a blinded scan, not as proof that nothing is running."""
    t = _transcript(tmp_path, idle=STALE)
    _use_proc(monkeypatch, _proc(tmp_path, [], name="bare-proc", bare=True))
    assert sg.session_liveness(t) == "unknown"


def test_unattributable_claude_in_same_cwd_is_unknown(tmp_path, monkeypatch):
    """`claude` / `claude --continue` put NO uuid on the cmdline. UUID matching
    alone would call this session idle — the same silent fail-open as the fd
    scan. Scoped by cwd so it does not poison the whole fleet."""
    t = _transcript(tmp_path, idle=STALE, cwd=PROJECT_CWD)
    _use_proc(monkeypatch,
                        _proc(tmp_path, [(5150, [CLAUDE, "--continue"], PROJECT_CWD)]))
    assert sg.session_liveness(t) == "unknown"


def test_unattributable_claude_elsewhere_does_not_poison(tmp_path, monkeypatch):
    """Scoping check: an unattributable claude in a DIFFERENT cwd must leave this
    session collectable. Measured: only 1 of 84 real stores collides."""
    t = _transcript(tmp_path, idle=STALE, cwd=PROJECT_CWD)
    _use_proc(monkeypatch,
                        _proc(tmp_path, [(5150, [CLAUDE, "--continue"], "/unrelated/dir")]))
    assert sg.session_liveness(t) == "idle"


def _cwdless(tmp_path, idle):
    """A transcript carrying no cwd record at all."""
    d = tmp_path / "store"
    d.mkdir(exist_ok=True)
    p = d / f"{LIVE_UUID}.jsonl"
    p.write_text(json.dumps({"type": "summary", "sessionId": LIVE_UUID}) + "\n", encoding="utf-8")
    t = time.time() - idle
    os.utime(p, (t, t))
    return str(p)


def test_cwdless_transcript_is_collectable(tmp_path, monkeypatch):
    """A transcript with no cwd record must NOT be poisoned by an unattributable
    claude. `cwd` only goes missing on a transcript too young to have logged one,
    and youth is already caught by the mtime window (see the test below). Poisoning
    here would strip every cwd-less transcript of collectability whenever any helper
    claude runs — which is nearly always."""
    p = _cwdless(tmp_path, idle=STALE)
    _use_proc(monkeypatch,
                        _proc(tmp_path, [(5150, [CLAUDE, "--continue"], "/unrelated/dir")]))
    assert sg.session_cwd(p) is None
    assert sg.session_liveness(p) == "idle"


def test_cwdless_but_young_transcript_is_caught_by_recency(tmp_path, monkeypatch):
    """The other half of the argument above: the case a cwd-less transcript could
    plausibly be live in, the recency window already covers."""
    p = _cwdless(tmp_path, idle=0)
    _use_proc(monkeypatch,
                        _proc(tmp_path, [(5150, [CLAUDE, "--continue"], "/unrelated/dir")]))
    assert sg.session_liveness(p) == "live"


def test_non_claude_process_never_makes_us_unknown(tmp_path, monkeypatch):
    """A vim/bash sitting in the project cwd is not a Claude session."""
    t = _transcript(tmp_path, idle=STALE, cwd=PROJECT_CWD)
    _use_proc(monkeypatch,
                        _proc(tmp_path, [(600, ["vim", "notes.md"], PROJECT_CWD)]))
    assert sg.session_liveness(t) == "idle"


def test_fresh_mtime_still_live_without_any_process(tmp_path, monkeypatch):
    """The recency window survives as a SECONDARY signal, never the sole proof."""
    t = _transcript(tmp_path, idle=0)
    _use_proc(monkeypatch, _proc(tmp_path, [], name="p2"))
    assert sg.session_liveness(t) == "live"


# --------------------------------------------------------------------------- #
# skill-gc refusal behaviour
# --------------------------------------------------------------------------- #
def test_skill_gc_refuses_live_idle_agent_without_force(tmp_path, monkeypatch, capsys):
    """AC: skill-gc refuses a live session, proven against a genuinely
    idle-but-running agent — the case that silently proceeded before."""
    t = _transcript(tmp_path, idle=STALE)
    before = open(t, "rb").read()
    _use_proc(monkeypatch,
                        _proc(tmp_path, [(4242, _agent(LIVE_UUID), PROJECT_CWD)]))
    assert sg.main([t, "--apply"]) == 3
    assert open(t, "rb").read() == before
    assert "REFUSING" in capsys.readouterr().err


def test_skill_gc_refuses_unknown_without_force(tmp_path, monkeypatch, capsys):
    t = _transcript(tmp_path, idle=STALE)
    _use_proc(monkeypatch, str(tmp_path / "nonexistent-proc"))
    assert sg.main([t, "--apply"]) == 3
    assert "REFUSING" in capsys.readouterr().err


@needs_real_body
def test_the_refusal_actually_prevents_a_real_write(tmp_path, monkeypatch):
    """The load-bearing pair: --force MUTATES this transcript, so the refused run
    leaving it byte-identical proves the gate stopped a write that would otherwise
    have happened. Without a real evictable body both halves pass vacuously."""
    t = _transcript(tmp_path, idle=STALE)
    original = open(t, "rb").read()
    _use_proc(monkeypatch,
                        _proc(tmp_path, [(4242, _agent(LIVE_UUID), PROJECT_CWD)]))
    assert sg.evict(t)[1], "fixture has no evictable skill body — test is vacuous"

    assert sg.main([t, "--apply"]) == 3
    assert open(t, "rb").read() == original, "refused run still wrote"

    assert sg.main([t, "--apply", "--force", "--backup-dir", str(tmp_path / "bk")]) == 0
    assert open(t, "rb").read() != original, "--force did not write; the pair proves nothing"


def test_force_still_overrides(tmp_path, monkeypatch):
    t = _transcript(tmp_path, idle=STALE)
    _use_proc(monkeypatch,
                        _proc(tmp_path, [(4242, _agent(LIVE_UUID), PROJECT_CWD)]))
    assert sg.main([t, "--apply", "--force", "--backup-dir", str(tmp_path / "bk")]) == 0


# --------------------------------------------------------------------------- #
# differential: selection (find-projects) vs mutation (skill-gc) must agree
# --------------------------------------------------------------------------- #
def _projects_tree(tmp_path):
    """Three stores: one live-but-idle, one genuinely stopped, one fresh."""
    root = tmp_path / "projects"
    root.mkdir()
    _transcript(root, uuid=LIVE_UUID, idle=STALE, cwd=PROJECT_CWD, store="-home-x-proj")
    _transcript(root, uuid=OTHER_UUID, idle=STALE, cwd="/home/x/dead", store="-home-x-dead")
    fresh = "9f3c1a77-2b8e-4d51-a0c6-13e7f9b25d84"
    _transcript(root, uuid=fresh, idle=0, cwd="/home/x/fresh", store="-home-x-fresh")
    return str(root), fresh


def test_selection_may_go_stale_but_mutation_re_checks(tmp_path, monkeypatch):
    """The real divergence risk is not two implementations — it is ONE
    implementation reading a CACHED sweep during selection and a FRESH one during
    mutation. Selection is allowed to go stale (an agent can start mid-fan-out);
    mutation must not. Comparing fp._liveness(sess) to sg.session_liveness(sess)
    with no scan would be tautological — same function, same module — so this
    drives the cached path against a /proc that changes underneath it."""
    root, _ = _projects_tree(tmp_path)
    quiet = _proc(tmp_path, [], name="before")
    _use_proc(monkeypatch, quiet)
    stale = sg.scan_processes()  # captured while nothing was running
    sess = os.path.join(root, "-home-x-proj", f"{LIVE_UUID}.jsonl")
    assert fp._liveness(sess, stale) == "idle"  # selection, using the old sweep

    # the agent starts after selection ran
    _use_proc(monkeypatch,
                        _proc(tmp_path, [(4242, _agent(LIVE_UUID), PROJECT_CWD)], name="after"))
    assert fp._liveness(sess, stale) == "idle"  # cache is still stale, as expected
    assert sg.session_liveness(sess) == "live"  # mutation re-checks and catches it


def test_skill_gc_re_checks_even_when_selection_said_stopped(tmp_path, monkeypatch):
    """End-to-end of the above: a store selected as stopped is still refused at
    --apply time once the agent is running. This is the property that makes a
    cached selection sweep safe."""
    root, _ = _projects_tree(tmp_path)
    _use_proc(monkeypatch, _proc(tmp_path, [], name="quiet"))
    assert fp.main(["--stopped", "--projects-dir", root]) == 0
    sess = os.path.join(root, "-home-x-proj", f"{LIVE_UUID}.jsonl")
    _use_proc(monkeypatch,
                        _proc(tmp_path, [(4242, _agent(LIVE_UUID), PROJECT_CWD)], name="busy"))
    assert sg.main([sess, "--apply"]) == 3


def test_running_reports_the_live_but_idle_store(tmp_path, monkeypatch, capsys):
    root, _ = _projects_tree(tmp_path)
    _use_proc(monkeypatch,
                        _proc(tmp_path, [(4242, _agent(LIVE_UUID), PROJECT_CWD)]))
    assert fp.main(["--running", "--projects-dir", root]) == 0
    out = capsys.readouterr().out
    assert "-home-x-proj" in out, out


def test_stopped_never_returns_a_live_session(tmp_path, monkeypatch, capsys):
    """The exact fleet hazard: `--stopped ... -exec reorient {} \\;` selecting a
    live agent's store."""
    root, _ = _projects_tree(tmp_path)
    _use_proc(monkeypatch,
                        _proc(tmp_path, [(4242, _agent(LIVE_UUID), PROJECT_CWD)]))
    assert fp.main(["--stopped", "--projects-dir", root]) == 0
    out = capsys.readouterr().out
    assert "-home-x-proj" not in out, out
    assert "-home-x-dead" in out, out  # genuinely stopped is still collectable


def test_find_projects_without_skill_gc_hard_fails(tmp_path, monkeypatch, capsys):
    """If skill-gc fails to load, a liveness predicate must ERROR, not answer.
    Quietly reporting 0 running from a detector that never loaded is how ./install
    came to run under ten live agents."""
    root, _ = _projects_tree(tmp_path)
    monkeypatch.setattr(fp, "_SG", None)
    assert fp.main(["--running", "--projects-dir", root]) == 2
    assert "skill-gc not found" in capsys.readouterr().err


def test_find_projects_hard_fails_when_the_sweep_is_blinded(tmp_path, monkeypatch, capsys):
    """The twin of the missing-engine case. If /proc cannot be swept, every session
    resolves to unknown and `--running` would print nothing and exit 0 — byte-for-byte
    identical to a genuinely drained fleet. That is the operator-facing failure that
    made ./install look safe under ten live agents; it must be an error, not silence."""
    root, _ = _projects_tree(tmp_path)
    _use_proc(monkeypatch, str(tmp_path / "nonexistent-proc"))
    assert fp.main(["--running", "--projects-dir", root]) == 2
    err = capsys.readouterr().err
    assert "/proc" in err and "not" in err.lower(), err


def test_proc_swept_once_per_run_not_per_session(tmp_path, monkeypatch):
    """The old detector re-globbed every /proc fd per session (277 x 10.6k).
    Selection must sweep once and reuse it."""
    root, _ = _projects_tree(tmp_path)
    _use_proc(monkeypatch,
                        _proc(tmp_path, [(4242, _agent(LIVE_UUID), PROJECT_CWD)]))
    calls = []
    # Count on the instance find-projects actually calls, not this file's handle —
    # they are distinct module objects loaded from the same file.
    real = fp._SG.scan_processes
    monkeypatch.setattr(fp._SG, "scan_processes",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    assert fp.main(["--stopped", "--projects-dir", root]) == 0
    assert len(calls) == 1, f"swept /proc {len(calls)} times for 3 stores"


# --------------------------------------------------------------------------- #
# fixture provenance
# --------------------------------------------------------------------------- #
def test_fixture_provenance_is_real_when_available():
    """Charter: fixtures come from REAL transcripts. If a session store exists on
    this host and we still fell back to a shape-derived fixture, that is a bug in
    the fixture loader, not an acceptable degradation."""
    if not glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")):
        pytest.skip("no session store on this host (CI) — shape-derived fallback in use")
    assert FIXTURE_PROVENANCE == "real"
