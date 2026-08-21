"""Prose must never reach a CLI as an inline double-quoted argument (#942).

Backticks and ``$(...)`` inside a double-quoted shell string are **command
substitution**. Documentation *about* commands therefore *runs* those commands,
and the substituted span is **stripped from the text** — so the body loses
content while the side effect happens silently.

This is not theoretical. On 2026-07-20 an agent commenting on an issue about CLI
syntax launched ``discord-watcher directmsg`` and an MCP server that then blocked
forever on stdin; the ``gh`` call hit its timeout and the comment never posted.
The observable outcome was a hang, so the natural diagnosis was "network blip,
retry" — exactly wrong.

**Assertion liveness (#922).** Half these tests exist to prove the *hazard* is
real, not just that the fix is applied. A suite that only asserts the safe form
behaves safely cannot distinguish "the fix works" from "this shell never
substituted anything in the first place." Each safe-form test therefore has an
unsafe-form twin that MUST execute.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# --- the marker tool -----------------------------------------------------------
#
# A stand-in for the side-effecting binaries real documentation names
# (discord-watcher, disc-server, kubectl...). It records that it ran, so a test
# can assert execution rather than infer it from output shape.

MARKER = """#!/bin/sh
echo "ran:$*" >> "$MARKER_LOG"
"""


@pytest.fixture()
def shell(tmp_path: Path):
    """A bash runner with `marker-tool` on PATH and a log to assert against."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    tool = bindir / "marker-tool"
    tool.write_text(MARKER)
    tool.chmod(0o755)
    log = tmp_path / "executed.log"

    def run(script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(tmp_path),
            env={
                "PATH": f"{bindir}:/usr/bin:/bin",
                "MARKER_LOG": str(log),
                "HOME": str(tmp_path),
            },
        )

    run.log = log  # type: ignore[attr-defined]
    run.tmp = tmp_path  # type: ignore[attr-defined]
    return run


def _executed(shell) -> str:
    return shell.log.read_text() if shell.log.exists() else ""


# --- the hazard is real (assertion liveness) -----------------------------------


def test_inline_double_quoted_prose_EXECUTES_code_spans(shell):
    """THE HAZARD. Must stay red-if-removed: this is what we are defending against.

    If this test ever passes with an empty log, the rest of this file proves
    nothing — it would mean the shell under test does not substitute at all.
    """
    proc = shell('printf "%s\\n" "Docs: run `marker-tool directmsg alice hi` to send."')
    assert "ran:directmsg alice hi" in _executed(shell), (
        "inline double-quoted prose did NOT execute its code span — the premise of "
        "#942 no longer holds on this shell, and every safe-form test below is vacuous"
    )
    # And the second half of the damage: the span is gone from the text.
    assert "marker-tool" not in proc.stdout, (
        "expected the substituted span to be STRIPPED from the output — the body "
        "silently loses content, which is why the failure reads as 'posted nothing'"
    )


def test_unquoted_heredoc_still_substitutes(shell):
    """The QUOTING of the delimiter is load-bearing, not decorative.

    `<<EOF` is not a fix. Pinned because "use a heredoc" is the half of the rule
    people remember, and it is the half that does not work.
    """
    shell("cat > out.md <<EOF\nDocs: run `marker-tool directmsg bob hi` to send.\nEOF")
    assert "ran:directmsg bob hi" in _executed(shell), (
        "an UNQUOTED heredoc did not substitute on this shell — do not relax the "
        "quoted-delimiter rule on that basis; re-derive it before changing guidance"
    )


# --- the prescribed fix works --------------------------------------------------


def test_quoted_heredoc_executes_nothing(shell):
    shell(
        "cat > out.md <<'EOF'\n"
        "Docs: run `marker-tool directmsg carol hi` to send.\n"
        "EOF"
    )
    assert _executed(shell) == "", "a quoted heredoc must not execute anything"


def test_quoted_heredoc_preserves_backticks_dollar_and_braces(shell):
    """All three metacharacter forms must survive as literal text."""
    shell(
        "cat > out.md <<'EOF'\n"
        "span `marker-tool x` subst $(marker-tool y) var ${HOME} tail\n"
        "EOF"
    )
    body = (shell.tmp / "out.md").read_text()
    assert "`marker-tool x`" in body
    assert "$(marker-tool y)" in body
    assert "${HOME}" in body, "brace expansion must not resolve HOME into the body"
    assert _executed(shell) == ""


def test_vox_reads_stdin_and_the_code_span_arrives_INTACT(shell):
    """`vox` is the live residual case: prose on argv, no `--body-file`.

    Asserts the text actually REACHES the provider, unmodified. An earlier draft
    used ``VOX_DISABLED=1`` and asserted only ``returncode == 0`` — which proved
    nothing at all: the disable short-circuit (`scripts/vox`, "VOX_DISABLED
    short-circuit") ``exit 0``s BEFORE message collection, so vox never reads
    stdin on that path and returns 0 for any input whatsoever. That test would
    have passed with the stdin branch deleted from vox entirely — the exact
    vacuity this file's header condemns, committed inside the file that condemns
    it. Kept as a comment because catching it required reading vox's control flow,
    not its docs.

    So: drive a real provider and assert on what it received.
    """
    vox = REPO_ROOT / "scripts" / "vox"
    assert vox.is_file(), "scripts/vox missing — update this test, don't delete it"

    capture = shell.tmp / "captured.txt"
    provider = shell.tmp / "capture-provider.sh"
    # Provider contract (scripts/vox header): text arrives as $1, audio is written
    # to $VOX_OUTPUT_FILE.
    provider.write_text(
        '#!/bin/sh\nprintf "%s" "$1" > "$CAPTURE"\n: > "$VOX_OUTPUT_FILE"\n'
    )
    provider.chmod(0o755)

    proc = shell(
        f"VOX_PROVIDER={provider} CAPTURE={capture} VOX_NO_LOG=1 VOX_NO_SIGNOFF=1 "
        f"{vox} --output {shell.tmp}/out.wav <<'EOF'\n"
        "Gate ready. See `marker-tool directmsg dave yo` for details.\n"
        "EOF"
    )
    assert proc.returncode == 0, f"vox failed on stdin: {proc.stderr[:400]}"
    assert capture.exists(), (
        "the provider never ran — vox did not read stdin, so the prescribed "
        "heredoc form does not actually work and the guidance is wrong"
    )
    got = capture.read_text()
    assert "`marker-tool directmsg dave yo`" in got, (
        f"the code span did not survive into the spoken text: {got!r}"
    )
    assert _executed(shell) == "", "vox-via-stdin must not execute code spans"

    # VOX_NO_SIGNOFF/VOX_NO_LOG are set deliberately: vox otherwise resolves a
    # speaker by walking ancestor cwds and appends ". This is <name>." from the
    # repo's real agent-identity.json, which would make an exact-match assertion
    # depend on which agent ran the suite.


def test_vox_inline_argv_EXECUTES_code_spans(shell):
    """The twin: the form the guidance USED to prescribe does execute.

    Note what this does and does not show. The substitution is bash's, at parse
    time, before `vox` is ever exec'd — this test passes identically with `true`
    in place of `vox`. It is not evidence about vox's own behaviour; it is
    evidence that the invocation SHAPE /precheck prescribed was hazardous
    regardless of what sat at the end of it.
    """
    vox = REPO_ROOT / "scripts" / "vox"
    shell(f'VOX_DISABLED=1 {vox} "Gate ready, see `marker-tool directmsg eve yo`"')
    assert "ran:directmsg eve yo" in _executed(shell), (
        "inline vox did not execute — if this stops being true, the vox guidance "
        "in /precheck and /vox can be relaxed; until then it cannot"
    )


def test_substitution_happens_at_ASSIGNMENT_not_at_use(shell):
    """"Put it in a variable" is NOT the fix, and believing it is worse than nothing.

    A double-quoted literal substitutes where it is WRITTEN. By the time
    ``vox "$msg"`` runs, the command already ran — that line is innocent and the
    damage is upstream. Pinned because the natural reading of #942 ("don't pass
    prose inline") suggests hoisting it to a variable, which fixes the symptom's
    location and not the defect.
    """
    shell('msg="see `marker-tool directmsg frank yo` here"; printf "%s\n" "$msg"')
    assert "ran:directmsg frank yo" in _executed(shell), (
        "assignment did not substitute — re-derive the rule before relying on "
        "variables being unsafe"
    )


def test_variable_EXPANSION_does_not_resubstitute(shell):
    """The other half: content that reaches a variable from a FILE is safe.

    This is why `--body-file` and stdin work at all, and why
    `vox "$msg"` is fine when `$msg` came from `$(cat ...)` — bash expands the
    value, it does not re-parse it.
    """
    (shell.tmp / "msg.txt").write_text("see `marker-tool directmsg grace yo` here\n")
    proc = shell('msg="$(cat msg.txt)"; printf "%s\n" "$msg"')
    assert _executed(shell) == "", "expansion must not re-substitute the value"
    assert "`marker-tool directmsg grace yo`" in proc.stdout, (
        "the code span must survive intact into the output"
    )


# --- the guidance says so, and keeps saying so ---------------------------------


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text()


def _modelled(text: str) -> str:
    """The text an agent would COPY: fenced code blocks, minus shell comments.

    Documentation that warns about an unsafe form necessarily contains that form —
    in prose, in inline backticks, and in `#` comments explaining why. Scanning the
    raw file therefore flags the warning as the violation, which is how two earlier
    drafts of these pins failed. Only a fenced block is a template someone runs.
    """
    lines = text.splitlines()

    # Unbalanced fences flip parity for the REST of the file, silently inverting
    # classification from that point on — prose scanned as shell (false positives)
    # and shell skipped (false negatives). Refuse to guess.
    fences = [l for l in lines if l.lstrip().startswith("```")]
    assert len(fences) % 2 == 0, (
        f"odd number of ``` fences ({len(fences)}) — this scanner cannot classify "
        "the file, and silently guessing is how a pin stops pinning"
    )

    blocks, inside, exempt = [], False, False
    for line in lines:
        if line.lstrip().startswith("```"):
            if not inside:
                # A block may DECLARE itself an anti-example: documentation that
                # teaches a hazard must be able to show it. Declared, not inferred —
                # an exemption the checker grants by accident is a hole.
                exempt = False
            inside = not inside
            continue
        if inside and line.strip() == "# ANTI-EXAMPLE":
            exempt = True
            continue
        if inside and not exempt and not line.lstrip().startswith("#"):
            blocks.append(line)
    return "\n".join(blocks)


# NOTE (known limits, verified against this repo rather than assumed):
#   * 4-space indented code blocks are invisible to this scanner. `skills/` and
#     `docs/` currently contain none carrying vox/gh/commit invocations.
#   * `~~~` fences are not recognised. None exist here.
# Both are gaps, not bugs-today. If either shape appears, extend this — do not
# assume the pin still covers the file.


_BARE_VAR = re.compile(r'^\$\{?[A-Za-z_][A-Za-z0-9_]*\}?$')


def _vox_literal_args(text: str) -> list[str]:
    r"""Double-quoted arguments to `vox` that are not a bare variable expansion.

    Pins the PROPERTY, not a prefix. An earlier draft matched `vox\s+"(?!\$)`,
    which missed both forms this repo actually writes:

      * `vox --voice Jade "..."` — a flag before the message defeats the prefix
        entirely, and `scripts/vox`'s own usage models exactly that.
      * `vox "$DEV_NAME here. Ran `validate.sh`."` — the lookahead only inspected
        the FIRST character, so a leading variable waved through a fully hazardous
        string. That is not contrived: /precheck instructs agents to front-load
        "<Dev-Name> here.", making it the most likely way someone writes it.

    A bare `"$msg"` / `"${msg}"` stays legal — the skill teaches that contrast, and
    expansion does not re-parse the value.
    """
    out = []
    for line in text.splitlines():
        if not re.search(r'(^|[;&|(\s])vox(\s|$)', line):
            continue
        for arg in re.findall(r'"([^"]*)"', line):
            if _BARE_VAR.match(arg.strip()):
                continue
            out.append(arg)
    return out


def test_vox_skill_prescribes_the_piped_form():
    body = _read("skills/vox/SKILL.md")
    assert "vox <<'EOF'" in body, "the vox skill must model the piped form"

    assert _vox_literal_args(_modelled(body)) == [], (
        f"the vox skill models a double-quoted vox argument: "
        f"{_vox_literal_args(_modelled(body))}. Pipe a quoted heredoc, or expand a "
        "variable whose value came from a file."
    )


def test_precheck_prescribes_the_piped_form():
    body = _read("skills/precheck/SKILL.md")
    assert "vox <<'EOF'" in body, (
        "/precheck runs on every gate and its example is the one agents copy"
    )


def test_the_rationale_is_recorded_not_just_the_rule():
    """AC2: rationale, so it is not 'simplified' back later.

    A bare style rule gets tidied away by the next person who finds it noisy.
    The reason it exists must travel with it.
    """
    for rel in ("skills/vox/SKILL.md", "skills/precheck/SKILL.md"):
        body = _read(rel)
        assert re.search(r"command\s+substitution", body, re.I), (
            f"{rel} states the rule without the reason — record WHY (#942), or it "
            "will be reverted as cosmetic"
        )


_PROSE_FLAGS = ("--body", "--message", "--description", "--notes", "-m", "-b")
_CLI_LINE = re.compile(r"(^|[;&|(\s])(git|gh|glab)(\s)")


def _prose_flag_args(text: str) -> list[tuple[str, str]]:
    r"""Double-quoted prose passed to a real CLI, excluding bare variable expansion.

    Scoped to lines that actually invoke ``git`` / ``gh`` / ``glab``. A flat
    substring scan produced two false positives immediately, and both were
    instructive:

      * ``git worktree add "$wt" -b "$branch"`` — ``-b`` is git's BRANCH flag here,
        nothing to do with a body. Resolved by allowing bare variable args, which
        it already was.
      * ``/scp -m "fix(auth): ..."`` in the skill reference — SLASH-COMMAND syntax
        typed into Claude Code, never parsed by a shell. Resolved by requiring a
        real CLI on the line; a leading ``/`` is not one.

    The lesson generalises: match the invocation, not the characters. A pin that
    fires on text will be silenced by whoever it annoys, and silencing it is
    indistinguishable from fixing it.
    """
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("/") or not _CLI_LINE.search(line):
            continue
        for flag in _PROSE_FLAGS:
            for arg in re.findall(rf'(?:^|\s){re.escape(flag)}[= ]"([^"]*)"', line):
                if _BARE_VAR.match(arg.strip()):
                    continue
                out.append((flag, arg))
    return out


def test_no_agent_facing_doc_models_inline_prose_flags():
    """No skill, recipe or reference doc may model prose in a double-quoted flag.

    `-m` is in the list deliberately. Commit messages are the highest-volume
    agent-composed prose in this repo, conventional-commit subjects routinely name
    tools, and an earlier draft of this tuple omitted `-m "` — so the guard passed
    while the cross-repo recipe modelled `git commit -m "..."` three lines above
    the `--body-file` it had just been corrected to use. A rule whose guard covers
    only some of its instances teaches that the rest are exempt.

    `docs/` is walked as well as `skills/`: `docs/skill-reference.md` is the
    aggregated reference agents actually read, and it modelled the forbidden vox
    form for the very skill this change fixes.
    """
    offenders = []
    for root in (REPO_ROOT / "skills", REPO_ROOT / "docs"):
        for path in sorted(root.rglob("*.md")):
            for flag, arg in _prose_flag_args(_modelled(path.read_text())):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {flag} \"{arg[:40]}\"")
    assert offenders == [], (
        "agent-facing docs model inline prose flags: " + "; ".join(offenders) +
        " — use --body-file / -F with a QUOTED heredoc (#942)"
    )
