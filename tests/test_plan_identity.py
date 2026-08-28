"""tests/test_plan_identity.py — plan-identity / FlightDeck classification
regression tests for cc-workflow#1171.

CT-02 shape (mirrors tests/test_prepwaves_dispatch.py): the deliverable for
#1171 is SKILL.md prose in two files, not an executable classifier — a
standalone `/nextwave` run's FlightDeck card escaping the "headless" UI
bucket depends entirely on an agent following that prose correctly. So the
strongest mechanical check available is a regression on the prose itself:
these tests parse the live skill bodies and assert the specific properties
code review found this design depends on for correctness — not just "the
words campaign-head appear somewhere".

Why this file exists rather than folding into test_prepwaves_dispatch.py or
test_nextwave_skill.py: those files are scoped to Story 1.3 dispatch and the
kahuna base-ref plumbing (#417) respectively; #1171 is a distinct concern
spanning both skills' persist/resolve steps, so it gets its own file, same
precedent as test_prepwaves_dispatch.py itself getting one for Story 1.3.

Discovered during review: a first draft of this fix specified
`wave-status campaign-head --activity-id "$PLAN_ID"` with no instruction for
where `$PLAN_ID` comes from — an unassigned variable, silently swallowed by
the trailing `|| true`, meaning the whole fix would have been inert. These
tests pin the corrected design: resolve the activity id by reading it BACK
from the just-persisted plan file, not from local invocation state.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
PREPWAVES_SKILL = _ROOT / "skills" / "prepwaves" / "SKILL.md"
NEXTWAVE_SKILL = _ROOT / "skills" / "nextwave" / "SKILL.md"


@pytest.fixture(scope="module")
def prepwaves_text() -> str:
    return PREPWAVES_SKILL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def nextwave_text() -> str:
    return NEXTWAVE_SKILL.read_text(encoding="utf-8")


class TestPrepwavesPersistsPlanIdentity:
    """/prepwaves must set a top-level plan_id/slug and pin the FlightDeck
    campaign card — the two-part fix that closes #1171."""

    def test_sets_top_level_plan_id_and_slug(self, prepwaves_text: str) -> None:
        assert "plan_id" in prepwaves_text
        assert "slug" in prepwaves_text
        # Reuses /devspec upshift's established field names, not new ones.
        assert "devspec" in prepwaves_text.lower()

    def test_calls_campaign_head_after_persist(self, prepwaves_text: str) -> None:
        assert "campaign-head" in prepwaves_text
        assert "--activity-id" in prepwaves_text

    def test_does_not_reference_an_unassigned_shell_variable(
        self, prepwaves_text: str
    ) -> None:
        """Regression for the exact defect code review caught: an early draft
        wrote `--activity-id "$PLAN_ID"` with no instruction resolving
        $PLAN_ID anywhere in the file — an empty/unbound variable that
        campaign-head's own empty-id guard would reject, silently swallowed
        by `|| true`. The fix must resolve the id from the persisted file,
        not assume a shell variable exists."""
        assert '"$PLAN_ID"' not in prepwaves_text, (
            "found a literal $PLAN_ID shell-variable reference with no "
            "resolution instruction — this is the exact inert-fix defect "
            "code review caught; resolve the activity id by reading it back "
            "from the persisted plan file instead"
        )

    def test_reads_activity_id_back_from_the_persisted_file(
        self, prepwaves_text: str
    ) -> None:
        """The activity id used for campaign-head must come from what was
        just written to disk, not from this invocation's own local
        variables — that is what guarantees /prepwaves and /nextwave (which
        reads the same file independently, possibly much later) agree on
        one value. See flightdeck#1144 ("one campaign, two activity ids")."""
        assert "read" in prepwaves_text.lower() and "just-persisted" in prepwaves_text.lower()
        assert "flightdeck#1144" in prepwaves_text or "1144" in prepwaves_text

    def test_documents_extend_drops_unknown_top_level_fields(
        self, prepwaves_text: str
    ) -> None:
        """extend_state (state.py) merges only the incoming `phases` array
        into the EXISTING persisted dict and re-saves that dict — any other
        top-level key (plan_id/slug included) is silently dropped on an
        extend of a plan that didn't already have one. The skill text must
        say this plainly, not claim parity with cross_repo/target_repos
        (which round-trip on extend because they are PER-PHASE fields)."""
        assert "extend_state" in prepwaves_text
        assert re.search(r"do(es)? NOT", prepwaves_text), (
            "extend-mode field-drop behavior must be stated as a fact, not "
            "implied — a false 'round trips the same way' claim here already "
            "shipped once and was caught only by code review reading state.py"
        )

    def test_backfills_plan_id_on_legacy_extend(self, prepwaves_text: str) -> None:
        """A plan persisted before this convention existed can never
        acquire a plan_id via wave_init's extend path alone (previous test).
        The skill must instruct a direct one-time patch of the persisted
        file when the read-back comes up empty — not a silent skip, which
        would permanently strand that campaign on flightdeck#1144's
        two-activity-id split every time it's extended."""
        assert "backfill" in prepwaves_text.lower() or "legacy" in prepwaves_text.lower()

    def test_slug_must_agree_with_devspec_when_one_already_exists(
        self, prepwaves_text: str
    ) -> None:
        """The same plan_id+slug pair feeds both kahuna/<id>-<slug> and
        campaign/<id>-<slug> branch names elsewhere in this codebase. If
        /prepwaves derives a DIFFERENT slug than /devspec upshift already
        wrote for the same Plan, the two writers disagree about this
        campaign's own branch names."""
        assert "existing slug" in prepwaves_text.lower() or "already exists" in prepwaves_text.lower()


class TestNextwaveResolvesPlanId:
    """/nextwave must read plan_id back and thread it as args.planId, or a
    standalone run keeps degrading to a wave-scoped FlightDeck activity id."""

    def test_threads_plan_id_into_args(self, nextwave_text: str) -> None:
        assert "args.planId" in nextwave_text
        assert "plan_id" in nextwave_text

    def test_does_not_hardcode_the_status_dir_path(self, nextwave_text: str) -> None:
        """status_dir() (state.py) resolves .sdlc/waves/ in a repo carrying
        .sdlc/, falling back to .claude/status/ otherwise. /prepwaves's
        campaign-head call resolves the same way. A hardcoded literal path
        here would read a DIFFERENT plan than the one /prepwaves just
        wrote in any .sdlc/-carrying repo, silently reading plan_id as
        absent and falling back to the wave-scoped id — the exact
        two-activity-id split this design exists to prevent."""
        assert ".claude/status/phases-waves.json" not in nextwave_text, (
            "found a hardcoded .claude/status/ path for plan_id resolution — "
            "status_dir() prefers .sdlc/waves/ when it exists; hardcoding "
            "either path can silently read the wrong file"
        )
        assert "status_dir" in nextwave_text or ".sdlc" in nextwave_text


def test_stale_docstrings_no_longer_call_1171_unstarted() -> None:
    """__main__.py's _cmd_wave_begin docstring used to say closing the
    headless-classification gap was 'a separate, unstarted architectural
    question, tracked in cc-workflow#1171' — #1171 is this fix. A future
    reader hitting that stale claim would conclude the gap is still open."""
    main_py = (_ROOT / "src" / "wave_status" / "__main__.py").read_text(encoding="utf-8")
    assert "unstarted architectural question" not in main_py
