"""Tests for wave_status.dashboard.polling module.

Exercises REAL code paths — no mocking of the module under test.
Validates all acceptance criteria from Issue #17 related to polling.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from wave_status.dashboard.polling import (
    badge_css_and_label,
    render_polling_script,
)


@pytest.fixture()
def _require_node():
    """cc-workflow#1180 code review: FAIL, don't skip, when node is absent.

    Applied only to the two node-executing classes below (via
    ``pytestmark``), not this whole module — the rest of this file is
    substring assertions on the generated script and has no node
    dependency at all. These two classes are the only tests that verify
    the #1180 fix actually works; a silent skip here would read as
    coverage that isn't there, exactly the kind of instrument-lies-about-
    itself gap this codebase treats as a real defect elsewhere. Matches
    the established convention for this repo's other node-dependent test
    (tests/regression/test_campaign_bundle_in_sync.sh hard-FAILs rather
    than skipping when node is missing); every CI runner this project
    targets ships node already (used for skills/nextwave's bundle.mjs),
    so an absence here means something is actually wrong with the
    environment, not a legitimately node-less lane.
    """
    if shutil.which("node") is None:
        pytest.fail("node not on PATH — required to verify the #1180 fix actually works")


# ---------------------------------------------------------------------------
# render_polling_script() tests
# ---------------------------------------------------------------------------


class TestRenderPollingScript:
    """The script block must satisfy R-27, R-28, R-29."""

    def setup_method(self) -> None:
        self.script = render_polling_script()

    def test_returns_string(self) -> None:
        assert isinstance(self.script, str)

    def test_nonempty(self) -> None:
        assert len(self.script) > 0

    # --- Structure ---

    def test_starts_with_script_tag(self) -> None:
        assert self.script.startswith("<script>")

    def test_ends_with_script_tag(self) -> None:
        assert self.script.strip().endswith("</script>")

    def test_script_is_self_contained(self) -> None:
        """No external src= references — must be inline [CT-04]."""
        assert 'src="' not in self.script
        assert "src='" not in self.script

    def test_badge_special_cases_placeholder_is_substituted(self) -> None:
        """cc-workflow#1180 code review: the __BADGE_SPECIAL_CASES__ token
        must never survive into the emitted script — if the substitution
        ever silently stopped happening (a renamed token, a dropped
        .replace()), the resulting JS throws a ReferenceError before
        polling starts, with no fallback-notice path (the throw is outside
        pollState()'s try/catch). TestDataStatusBadgeMapping's node-execution
        tests exercise the mapping algorithm but, before this test existed,
        did so via a hand-rebuilt copy of BADGE_SPECIAL_CASES rather than the
        declaration the generated script actually carries — this asserts the
        serialization step itself, directly."""
        assert "__BADGE_SPECIAL_CASES__" not in self.script
        assert '"open": ["badge-pending", "open"]' in self.script
        assert '"closed": ["badge-closed", "closed"]' in self.script

    # --- R-27: Fetches state.json every 3s ---

    def test_fetches_state_json(self) -> None:
        assert "state.json" in self.script

    def test_uses_fetch_api(self) -> None:
        assert "fetch(" in self.script

    def test_poll_interval_3000ms(self) -> None:
        assert "3000" in self.script

    def test_uses_setinterval(self) -> None:
        assert "setInterval" in self.script

    # --- R-28: Disables on fetch failure with fallback notice ---

    def test_clears_interval_on_error(self) -> None:
        assert "clearInterval" in self.script

    def test_fallback_notice_text(self) -> None:
        # The exact text from the PRD
        assert "Live updates unavailable" in self.script

    def test_fallback_refresh_guidance(self) -> None:
        assert "refresh to update" in self.script

    def test_targets_fallback_notice_element(self) -> None:
        assert "data-fallback-notice" in self.script

    def test_fallback_notice_shown_on_error(self) -> None:
        """The script must make the fallback notice visible."""
        assert 'display' in self.script
        assert 'block' in self.script

    # --- R-29: Uses data-* selectors for DOM updates ---

    def test_uses_data_field_selector(self) -> None:
        assert "data-field" in self.script

    def test_uses_queryselectorall_for_data_attributes(self) -> None:
        assert "querySelectorAll" in self.script

    def test_uses_data_action_banner(self) -> None:
        assert "data-action-banner" in self.script

    def test_uses_data_status(self) -> None:
        assert "data-status" in self.script

    def test_uses_data_timestamp(self) -> None:
        assert "data-timestamp" in self.script

    # --- Action banner class updates ---

    def test_contains_all_action_css_classes(self) -> None:
        """The polling script must know all action CSS class names."""
        expected_classes = [
            "action-preflight",
            "action-planning",
            "action-inflight",
            "action-merging",
            "action-review",
            "action-meatbag",
            "action-idle",
        ]
        for cls in expected_classes:
            assert cls in self.script, f"Missing action class {cls!r} in script"

    def test_contains_all_action_names(self) -> None:
        """The script maps action names to CSS classes."""
        expected_actions = [
            "pre-flight",
            "planning",
            "in-flight",
            "merging",
            "post-wave-review",
            "waiting-on-meatbag",
            "idle",
        ]
        for action in expected_actions:
            assert action in self.script, f"Missing action name {action!r} in script"

    def test_action_lookup_uses_action_field(self) -> None:
        """The action banner must dereference .action, not the whole object."""
        assert "current_action.action" in self.script, (
            "actionMap lookup must use state.current_action.action, "
            "not state.current_action (which is an object, not a string)"
        )

    # --- Nested state value resolution ---

    def test_supports_dotted_paths(self) -> None:
        """The script must support dotted paths like 'current_wave.name'."""
        assert "split" in self.script  # path.split(".")

    # --- Immediate poll on load ---

    def test_immediate_poll_on_load(self) -> None:
        """Should call pollState immediately, not just on interval."""
        # The script calls pollState() after setInterval
        lines = self.script.splitlines()
        # Find setInterval line and then look for a standalone pollState() call after
        found_set_interval = False
        found_immediate_call = False
        for line in lines:
            stripped = line.strip()
            if "setInterval" in stripped:
                found_set_interval = True
            if found_set_interval and stripped == "pollState();":
                found_immediate_call = True
        assert found_set_interval, "Missing setInterval call"
        assert found_immediate_call, "Missing immediate pollState() call after setInterval"


# ---------------------------------------------------------------------------
# state_path parameterization (cc-workflow#444)
# ---------------------------------------------------------------------------


class TestStatePathParameter:
    """The polling script must fetch from the path the generator passes in.

    cc-workflow#444: when the HTML lives at the project root (no .sdlc/),
    the state.json is at .claude/status/state.json — a relative path the
    caller computes and passes in. The default ('state.json') preserves
    the .sdlc/waves/ same-dir layout for backward compat.
    """

    def test_default_path_is_state_json_for_sdlc_layout(self) -> None:
        script = render_polling_script()
        # Default (no arg) keeps the .sdlc/waves/ same-dir behavior.
        assert 'var STATE_URL = "state.json";' in script

    def test_custom_path_is_emitted_into_state_url(self) -> None:
        script = render_polling_script(".claude/status/state.json")
        assert 'var STATE_URL = ".claude/status/state.json";' in script
        # And nothing left over from the default
        assert 'var STATE_URL = "state.json";' not in script

    def test_fetch_uses_state_url_constant_not_literal(self) -> None:
        """fetch() must reference the STATE_URL var, not a hardcoded literal."""
        script = render_polling_script(".claude/status/state.json")
        assert "fetch(STATE_URL)" in script
        # Confirm no hardcoded literal sneaks in alongside
        assert 'fetch("state.json")' not in script

    def test_path_is_json_encoded_against_quote_injection(self) -> None:
        """A path containing a quote character must be safely escaped."""
        # Edge case — unlikely in practice but proves the json.dumps boundary
        script = render_polling_script('weird"path/state.json')
        # The literal " inside the path must appear as \" in the JS source
        assert r'var STATE_URL = "weird\"path/state.json";' in script


# ---------------------------------------------------------------------------
# No external dependencies  [CT-01]
# ---------------------------------------------------------------------------


class TestNoDependencies:
    """Module must only use Python 3.10+ stdlib."""

    def test_polling_imports_only_stdlib(self) -> None:
        """Read polling.py source and verify no non-stdlib imports."""
        polling_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "wave_status",
            "dashboard",
            "polling.py",
        )
        with open(polling_path) as f:
            source = f.read()

        import_lines = [
            line.strip()
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]

        # Per CT-01: stdlib only. Allow `from __future__` and known stdlib
        # modules; reject any third-party or wave_status-internal import that
        # would create a runtime dependency.
        STDLIB_ALLOWED = {
            "json", "os", "sys", "pathlib", "datetime", "html", "tempfile",
            "subprocess", "argparse", "enum", "dataclasses", "collections",
            "typing", "re", "time", "uuid", "io", "shutil",
        }
        for line in import_lines:
            if line.startswith("from __future__"):
                continue
            tokens = line.split()
            mod = tokens[1].split(".")[0] if len(tokens) >= 2 else ""
            assert mod in STDLIB_ALLOWED, (
                f"Non-stdlib import found in polling.py: {line}"
            )


# ---------------------------------------------------------------------------
# Return value consistency
# ---------------------------------------------------------------------------


class TestConsistency:
    """Calling render_polling_script multiple times returns the same result."""

    def test_idempotent(self) -> None:
        a = render_polling_script()
        b = render_polling_script()
        assert a == b


# ---------------------------------------------------------------------------
# Issue #447: data-bind-width handling for gauge fills + rail segments
# ---------------------------------------------------------------------------


class TestBindWidthHandler:
    """The polling JS must update ``style.width`` for elements bound via
    ``data-bind-width="<dotted.path>"``.  This is the live-update mechanism
    for gauge-card progress fills and progress-rail per-phase segments
    that issue #447 fixes (the bare ``data-field="fill"`` was a no-op)."""

    def setup_method(self) -> None:
        self.script = render_polling_script()

    def test_script_queries_data_bind_width(self) -> None:
        assert 'querySelectorAll("[data-bind-width]")' in self.script

    def test_script_reads_data_bind_width_attribute(self) -> None:
        assert 'getAttribute("data-bind-width")' in self.script

    def test_script_writes_style_width(self) -> None:
        assert "style.width" in self.script

    def test_script_appends_percent_unit(self) -> None:
        # The handler appends "%" so the resolved 0..100 number renders as
        # a CSS percentage. Without the unit, `style.width = 42` is invalid.
        assert '+ "%"' in self.script

    def test_script_guards_non_numeric_values(self) -> None:
        # Non-numeric / non-finite resolved values must be silently skipped
        # so missing-derived-state doesn't blow up the dashboard.
        assert "isFinite" in self.script
        assert 'typeof widthValue === "number"' in self.script


# ---------------------------------------------------------------------------
# cc-workflow#1180: resolve() must not split a dotted key on its OWN dots
# ---------------------------------------------------------------------------


def _extract_resolve_fn(script: str) -> str:
    """Pull the standalone `resolve(obj, path, el)` function body out of the
    generated script (bounded by the next function definition), so it can be
    executed under node in isolation — a real behavioral check, not a
    substring assertion. Pure function, no DOM needed beyond a fake `el`
    object with a `.getAttribute` method."""
    start = script.index("function resolve(")
    end = script.index("function applyState(")
    return script[start:end]


def _run_resolve(obj: dict, path: str, field_key: str | None) -> object:
    """Execute the real resolve() from the generated script under node and
    return its result. `field_key` is None to omit the element entirely
    (exercises the no-el path); otherwise a fake element exposing
    getAttribute("data-field-key") -> field_key is passed."""
    resolve_fn = _extract_resolve_fn(render_polling_script())
    el_js = "undefined" if field_key is None else (
        "{ getAttribute: function(name) { return name === \"data-field-key\" ? "
        + json.dumps(field_key) + " : null; } }"
    )
    node_src = f"""
{resolve_fn}
var obj = {json.dumps(obj)};
var result = resolve(obj, {json.dumps(path)}, {el_js});
console.log(JSON.stringify(result === undefined ? "__UNDEFINED__" : result));
"""
    proc = subprocess.run(
        ["node", "-e", node_src], capture_output=True, text=True, timeout=10
    )
    assert proc.returncode == 0, f"node execution failed: {proc.stderr}"
    parsed = json.loads(proc.stdout)
    return None if parsed == "__UNDEFINED__" else parsed


class TestResolveDottedKeyIndirection:
    """The exact failure #1180 reports: a repo-qualified state.json key can
    contain a literal "." (a legal GitHub org/repo name — socket.io,
    docs.rs), and interpolating it straight into a dotted data-field path
    breaks resolve()'s naive path.split(".") walk, silently, forever (the
    poll's `value !== undefined` guard just skips the update). Fixed by a
    "*" template segment substituted from a separate data-field-key
    attribute, resolved as ONE atomic key, never re-split. These tests
    execute the REAL resolve() under node — not a substring check — because
    a bug in exactly this shape (client/server binding-shape drift) already
    shipped once in this file's own history (data-status was wired
    server-side with no renderer ever emitting it, per cc-workflow#1180's
    own linked finding) and a substring assertion would not have caught it."""

    pytestmark = pytest.mark.usefixtures("_require_node")

    def test_star_segment_substituted_from_data_field_key(self) -> None:
        obj = {"issues": {"acme/my.widgets#5": {"status": "closed"}}}
        result = _run_resolve(obj, "issues.*.status", "acme/my.widgets#5")
        assert result == "closed"

    def test_dotted_key_would_break_a_naive_split_without_the_star(self) -> None:
        # Proves the star indirection is load-bearing, not incidental: the
        # SAME key interpolated directly into the path (the pre-#1180
        # shape) must fail to resolve, which is the exact regression this
        # fix exists to prevent from reappearing.
        obj = {"issues": {"acme/my.widgets#5": {"status": "closed"}}}
        result = _run_resolve(obj, "issues.acme/my.widgets#5.status", None)
        assert result is None

    def test_non_dotted_key_still_resolves_via_star(self) -> None:
        # Regression guard: the common case (no dot in the key) must keep
        # working through the new indirection, not just the dotted edge case.
        obj = {"issues": {"acme/widgets#1": {"status": "open"}}}
        result = _run_resolve(obj, "issues.*.status", "acme/widgets#1")
        assert result == "open"

    def test_star_with_no_element_returns_undefined(self) -> None:
        # data-bind-width bindings never carry a "*" today, but resolve()
        # must degrade safely (not throw) if one ever did without a
        # data-field-key to substitute.
        obj = {"issues": {"acme/widgets#1": {"status": "open"}}}
        result = _run_resolve(obj, "issues.*.status", None)
        assert result is None

    def test_mr_urls_binding_shape_with_dotted_key(self) -> None:
        # The MR-link cell's exact binding shape (waves.<wid>.mr_urls.*),
        # not just the status badge's — #1180 fixes both.
        obj = {"waves": {"wave-1": {"mr_urls": {"acme/my.widgets#5": "https://x/pull/1"}}}}
        result = _run_resolve(obj, "waves.wave-1.mr_urls.*", "acme/my.widgets#5")
        assert result == "https://x/pull/1"


def _extract_badge_map_declaration(script: str) -> str:
    """Pull the real `var BADGE_SPECIAL_CASES = {...};` declaration out of
    the generated script — as opposed to hand-building it from the Python
    dict — so a test using it proves the __BADGE_SPECIAL_CASES__ placeholder
    actually substituted, not merely that badge_css_and_label() agrees with
    a copy fed in independently (cc-workflow#1180 code review)."""
    start = script.index("var BADGE_SPECIAL_CASES = ")
    end = script.index(";", start) + 1
    return script[start:end]


def _run_apply_state_on_status_badge(state: dict, field_key: str) -> dict:
    """Run the REAL applyState() against a single fake `[data-status]`
    element and return its resulting className/textContent — a full
    end-to-end behavioral check of the badge-update path (resolve() +
    the open/closed/generic mapping), against a minimal DOM stub."""
    applyState_start_marker = "function applyState("
    pollstate_marker = "function pollState("
    script = render_polling_script()
    resolve_fn = _extract_resolve_fn(script)
    apply_state_fn = script[script.index(applyState_start_marker) : script.index(pollstate_marker)]
    badge_map_decl = _extract_badge_map_declaration(script)

    node_src = f"""
{badge_map_decl}
{resolve_fn}
{apply_state_fn}

var el = {{
  _attrs: {{ "data-status": "issues.*.status", "data-field-key": {json.dumps(field_key)} }},
  className: "badge badge-pending",
  textContent: "",
  getAttribute: function(name) {{ return this._attrs[name] !== undefined ? this._attrs[name] : null; }},
  classList: {{ add: function(cls) {{ el.className = (el.className + " " + cls).trim(); }} }},
}};

global.document = {{
  querySelectorAll: function(sel) {{ return sel === "[data-status]" ? [el] : []; }},
  querySelector: function() {{ return null; }},
}};

applyState({json.dumps(state)});
console.log(JSON.stringify({{ className: el.className, textContent: el.textContent }}));
"""
    proc = subprocess.run(["node", "-e", node_src], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, f"node execution failed: {proc.stderr}"
    return json.loads(proc.stdout)


class TestDataStatusBadgeMapping:
    """cc-workflow#1180: data-status drives BOTH the badge class and label
    on a poll tick, and the mapping must mirror execution_grid.py's
    _render_issue_row exactly — "open" is a special case (badge-pending,
    not the generic badge-open), not the default hyphenated transform.
    Getting this wrong would make the FIRST poll tick after page load
    immediately overwrite a correct initial render with a broken class,
    which is worse than the never-updates bug #1180 exists to fix — this
    executes the REAL applyState() against a minimal DOM stub, not a
    substring check."""

    pytestmark = pytest.mark.usefixtures("_require_node")

    def test_open_status_maps_to_badge_pending_not_badge_open(self) -> None:
        state = {"issues": {"acme/widgets#1": {"status": "open"}}}
        result = _run_apply_state_on_status_badge(state, "acme/widgets#1")
        assert "badge-pending" in result["className"].split()
        assert "badge-open" not in result["className"].split()
        assert result["textContent"] == "open"

    def test_closed_status_maps_to_badge_closed(self) -> None:
        state = {"issues": {"acme/widgets#1": {"status": "closed"}}}
        result = _run_apply_state_on_status_badge(state, "acme/widgets#1")
        assert "badge-closed" in result["className"].split()
        assert result["textContent"] == "closed"

    def test_other_status_uses_generic_hyphenated_mapping(self) -> None:
        state = {"issues": {"acme/widgets#1": {"status": "in_progress"}}}
        result = _run_apply_state_on_status_badge(state, "acme/widgets#1")
        assert "badge-in-progress" in result["className"].split()
        assert result["textContent"] == "in progress"

    def test_dotted_qualified_key_updates_the_badge_on_poll(self) -> None:
        # The end-to-end proof: a repo name containing a literal "." no
        # longer silently breaks the live-poll update for the status badge.
        state = {"issues": {"acme/my.widgets#5": {"status": "closed"}}}
        result = _run_apply_state_on_status_badge(state, "acme/my.widgets#5")
        assert "badge-closed" in result["className"].split()
        assert result["textContent"] == "closed"

    @pytest.mark.parametrize("status", ["open", "closed", "in_progress", "held", "pending"])
    def test_python_and_js_agree_for_every_status(self, status: str) -> None:
        # cc-workflow#1180 code review: the structural fix (BADGE_SPECIAL_CASES
        # as one shared dict) is what makes this true by construction rather
        # than by two hand-synced mappings — this test is the belt-and-
        # suspenders proof that the wiring between the shared dict and its
        # two consumers (Python's badge_css_and_label, the serialized JS)
        # actually holds, for every status this dashboard renders, not just
        # the two originally-special-cased ones. A THIRD special case added
        # to only one side would fail exactly this test.
        expected_css, expected_label = badge_css_and_label(status)
        state = {"issues": {"acme/widgets#1": {"status": status}}}
        result = _run_apply_state_on_status_badge(state, "acme/widgets#1")
        assert result["className"].split() == ["badge", expected_css]
        assert result["textContent"] == expected_label


def _run_apply_state_on_mr_link(
    state: dict, field_key: str, initial_href: str = ""
) -> dict:
    """Run the REAL applyState() against a single fake always-<a> MR-link
    element and return its resulting href/textContent/display — a full
    end-to-end behavioral check of the data-bind-href wiring
    (cc-workflow#1180 code review)."""
    applyState_start_marker = "function applyState("
    pollstate_marker = "function pollState("
    script = render_polling_script()
    resolve_fn = _extract_resolve_fn(script)
    apply_state_fn = script[script.index(applyState_start_marker) : script.index(pollstate_marker)]

    node_src = f"""
{resolve_fn}
{apply_state_fn}

var el = {{
  _attrs: {{
    "data-field": "waves.wave-1.mr_urls.*",
    "data-bind-href": "waves.wave-1.mr_urls.*",
    "data-field-key": {json.dumps(field_key)}
  }},
  href: {json.dumps(initial_href)},
  style: {{ display: "none" }},
  textContent: "",
  getAttribute: function(name) {{ return this._attrs[name] !== undefined ? this._attrs[name] : null; }},
}};

global.document = {{
  querySelectorAll: function(sel) {{
    if (sel === "[data-field]" || sel === "[data-bind-href]") return [el];
    return [];
  }},
  querySelector: function() {{ return null; }},
}};

applyState({json.dumps(state)});
console.log(JSON.stringify({{ href: el.href, textContent: el.textContent, display: el.style.display }}));
"""
    proc = subprocess.run(["node", "-e", node_src], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, f"node execution failed: {proc.stderr}"
    return json.loads(proc.stdout)


class TestDataBindHrefIndirection:
    """cc-workflow#1180 code review: the MR-link cell became a single,
    always-present <a> (never a <span>) specifically so a later poll tick
    can populate href without needing to swap the element's tag — a
    data-field-only update could only ever rewrite textContent, leaving a
    populated cell as unlinked plain text, or a changed URL's href stale
    against its own updated label. These tests run the REAL applyState()
    under node against a fake anchor, not a substring check — the exact
    "wiring looks right but the shipped artifact disagrees" shape #1180
    itself exists to catch."""

    pytestmark = pytest.mark.usefixtures("_require_node")

    def test_href_and_text_populate_once_mr_is_recorded(self) -> None:
        state = {
            "waves": {"wave-1": {"mr_urls": {"acme/widgets#1": "https://github.com/acme/widgets/pull/42"}}}
        }
        result = _run_apply_state_on_mr_link(state, "acme/widgets#1")
        assert result["href"] == "https://github.com/acme/widgets/pull/42"
        assert result["textContent"] == "https://github.com/acme/widgets/pull/42"
        assert result["display"] == ""

    def test_stale_href_is_overwritten_when_mr_url_changes(self) -> None:
        # The "worse than never appearing" case the review flagged: a
        # previously-recorded href must not survive a poll tick that
        # resolves to a different URL — visible text and click target must
        # never be allowed to disagree.
        state = {
            "waves": {"wave-1": {"mr_urls": {"acme/widgets#1": "https://github.com/acme/widgets/pull/99"}}}
        }
        result = _run_apply_state_on_mr_link(
            state, "acme/widgets#1", initial_href="https://github.com/acme/widgets/pull/42"
        )
        assert result["href"] == "https://github.com/acme/widgets/pull/99"

    def test_no_mr_yet_leaves_element_hidden_with_no_href(self) -> None:
        # mr_urls has no entry for this key yet — resolve() returns
        # undefined, and the hidden/no-href initial state must be a silent
        # no-op, never a throw or a literal "undefined" written into href.
        state = {"waves": {"wave-1": {"mr_urls": {}}}}
        result = _run_apply_state_on_mr_link(state, "acme/widgets#1")
        assert result["href"] == ""
        assert result["display"] == "none"

    def test_dotted_qualified_key_updates_href_on_poll(self) -> None:
        # Mirrors test_dotted_qualified_key_updates_the_badge_on_poll for
        # the status badge: a repo name containing a literal "." must not
        # break the href live-update either.
        state = {
            "waves": {
                "wave-1": {"mr_urls": {"acme/my.widgets#5": "https://github.com/acme/my.widgets/pull/7"}}
            }
        }
        result = _run_apply_state_on_mr_link(state, "acme/my.widgets#5")
        assert result["href"] == "https://github.com/acme/my.widgets/pull/7"
