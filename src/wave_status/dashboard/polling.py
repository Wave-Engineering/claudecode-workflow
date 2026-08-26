"""Dashboard polling script: JavaScript for live-updating the dashboard.

Generates a self-contained ``<script>`` block that:
- Fetches ``state.json`` every 3 seconds  [R-27]
- Updates DOM elements via ``data-*`` attribute selectors  [R-29]
- Disables polling on fetch failure with a fallback notice  [R-28]

No external dependencies — Python 3.10+ stdlib only  [CT-01].
"""

from __future__ import annotations


import json as _json

# cc-workflow#1180 code review: the single source of truth for badge
# CSS-class/label special cases, shared between the Python-side initial
# render (execution_grid.py, via badge_css_and_label below) and the
# client-side live-poll JS (serialized into the script by
# render_polling_script). Without ONE shared definition, the two had to be
# hand-kept in sync by comment convention alone — the exact "verify the
# mechanism, not just that a comment claims it" gap this codebase treats as
# a real defect class elsewhere. A THIRD special case added to only one
# side would pass every test that checks each side in isolation while every
# open dashboard repaints wrong 3 seconds after load.
#
# "open" is not a stylistic choice — it names a DIFFERENT word than the
# generic transform would produce ("badge-open"), not just a hyphenation of
# the status text.
BADGE_SPECIAL_CASES: dict[str, tuple[str, str]] = {
    "open": ("badge-pending", "open"),
    "closed": ("badge-closed", "closed"),
}


def badge_css_and_label(status: str) -> tuple[str, str]:
    """Return ``(css_class, label)`` for a raw status string.

    Special-cased via :data:`BADGE_SPECIAL_CASES`; everything else falls
    back to the generic ``badge-<hyphenated>`` / ``<spaced>`` transform.
    Used for every badge this dashboard renders (issue status, wave status,
    flight status) so all three stay in lockstep with the live-poll JS by
    construction, not by separately maintained mappings.
    """
    if status in BADGE_SPECIAL_CASES:
        return BADGE_SPECIAL_CASES[status]
    return "badge-" + status.replace("_", "-"), status.replace("_", " ")


def render_polling_script(state_path: str = "state.json") -> str:
    """Return a ``<script>`` block for dashboard live-update polling.

    The script:
    - Uses ``setInterval`` to fetch ``state_path`` every 3 000 ms. Caller
      supplies the relative path from the HTML file's directory to
      ``state.json`` so the same polling code works for both layouts:
      ``.sdlc/waves/dashboard.html`` (sibling state.json → ``"state.json"``)
      and ``.status-panel.html`` at project root (state under
      ``.claude/status/`` → ``".claude/status/state.json"``).
    - On success, updates every element that has a ``data-field`` attribute
      with the corresponding value from the JSON response.
    - On fetch failure (e.g. ``file://`` CORS or network error), clears the
      interval and displays a fallback notice in the footer.
    """
    # JSON-encode the path so it lands in the JS source as a safe quoted
    # string regardless of operator-controlled characters in the project
    # layout. Spliced via .replace() rather than an f-string so the rest of
    # the JS body's `{`/`}` braces don't need escaping.
    state_path_js = _json.dumps(state_path)
    # BADGE_SPECIAL_CASES serialized as {status: [css, label]} — the single
    # source of truth for badge_css_and_label above, read at runtime by the
    # client instead of a hand-duplicated if/else chain (cc-workflow#1180
    # code review).
    badge_map_js = _json.dumps({k: list(v) for k, v in BADGE_SPECIAL_CASES.items()})
    script = _SCRIPT_TEMPLATE.replace("__STATE_URL__", state_path_js)
    return script.replace("__BADGE_SPECIAL_CASES__", badge_map_js)


_SCRIPT_TEMPLATE = """\
<script>
(function () {
  "use strict";

  var POLL_INTERVAL_MS = 3000;
  var STATE_URL = __STATE_URL__;
  var timerId = null;
  /* {status: [cssClass, label]} — generated from the SAME Python dict
     execution_grid.py's badge_css_and_label() reads (cc-workflow#1180 code
     review); this is the only place either side's special cases live. */
  var BADGE_SPECIAL_CASES = __BADGE_SPECIAL_CASES__;

  /**
   * Update a single DOM element from a (possibly nested) state value.
   * Elements declare their binding via data-field="dotted.path".
   *
   * A path segment of "*" (cc-workflow#1180) is a placeholder for a
   * server-resolved key that may itself contain a literal "." — a
   * repo-qualified state.json key like "owner/my.repo#5" splits into TWO
   * segments if it were interpolated into the dotted path directly
   * ("issues.owner/my.repo#5.status" -> 4 parts, not 3), silently breaking
   * the walk. The literal key instead rides in a separate data-field-key
   * attribute on the SAME element and is substituted here as one atomic
   * segment, never re-split. `el` is optional so callers with no possible
   * "*" segment can omit it — today that means only data-bind-width
   * callers; data-field, data-status, and data-bind-href bindings all can
   * carry a "*" and must pass their element.
   *
   * LIMIT: at most ONE "*" per path, resolved from the single
   * data-field-key attribute on the element — there is no way to
   * substitute more than one dynamic segment in one binding today. Every
   * OTHER interpolated segment in a path (a wave id, in
   * "waves.<wid>.status") is still a raw string literal, so the identical
   * failure this fix closes for issue/repo keys would reappear for a wave
   * id containing a literal "." — low practical risk today (wave ids in
   * this codebase are planner-authored, hyphenated conventions, e.g.
   * "wave-2a"), but not a fixed one.
   */
  function resolve(obj, path, el) {
    var parts = path.split(".");
    var cur = obj;
    for (var i = 0; i < parts.length; i++) {
      if (cur == null) return undefined;
      var key = parts[i];
      if (key === "*") {
        if (!el) return undefined;
        key = el.getAttribute("data-field-key");
        if (key == null) return undefined;
      }
      cur = cur[key];
    }
    return cur;
  }

  function applyState(state) {
    var elements = document.querySelectorAll("[data-field]");
    for (var i = 0; i < elements.length; i++) {
      var el = elements[i];
      var field = el.getAttribute("data-field");
      var value = resolve(state, field, el);
      if (value !== undefined) {
        el.textContent = String(value);
      }
    }

    /* Update href + visibility for elements bound via data-bind-href
       (cc-workflow#1180 code review). The MR-link cell renders as a single
       <a> at all times; before a URL is recorded it is hidden via inline
       style and carries no href. Once record_mr writes a value, this keeps
       href in lockstep with the same resolved value data-field just wrote
       to textContent above — without it, the cell's visible text and its
       click target could disagree (label updates, link doesn't), or a
       populated cell could stay unlinked plain text forever, since
       data-field alone can only ever rewrite an existing element's
       textContent, never its href or its hidden state. */
    var hrefEls = document.querySelectorAll("[data-bind-href]");
    for (var h = 0; h < hrefEls.length; h++) {
      var hrefEl = hrefEls[h];
      var hrefField = hrefEl.getAttribute("data-bind-href");
      var hrefValue = resolve(state, hrefField, hrefEl);
      if (typeof hrefValue === "string" && hrefValue) {
        hrefEl.href = hrefValue;
        hrefEl.style.display = "";
      }
    }

    /* Update style.width for elements bound via data-bind-width.
       The resolved value is expected to be a number in 0..100 representing
       a percentage. Cosmetic-only — silent no-op when the value is missing
       or not finite. Used by gauge-fill bars and progress-rail segments
       (issue #447). */
    var widthEls = document.querySelectorAll("[data-bind-width]");
    for (var w = 0; w < widthEls.length; w++) {
      var widthEl = widthEls[w];
      var widthField = widthEl.getAttribute("data-bind-width");
      var widthValue = resolve(state, widthField, widthEl);
      if (typeof widthValue === "number" && isFinite(widthValue)) {
        widthEl.style.width = widthValue + "%";
      }
    }

    /* Update action banner class if current_action is present */
    var banner = document.querySelector("[data-action-banner]");
    if (banner && state.current_action) {
      var actionMap = {
        "pre-flight": "action-preflight",
        "planning": "action-planning",
        "in-flight": "action-inflight",
        "merging": "action-merging",
        "post-wave-review": "action-review",
        "waiting-on-meatbag": "action-meatbag",
        "idle": "action-idle"
      };
      /* Remove all action classes */
      var classes = Object.values(actionMap);
      for (var c = 0; c < classes.length; c++) {
        banner.classList.remove(classes[c]);
      }
      var newClass = actionMap[state.current_action.action];
      if (newClass) {
        banner.classList.add(newClass);
      }
    }

    /* Update badge classes for elements with data-status (cc-workflow#1180:
       previously dead — no Python renderer emitted data-status, so a
       qualified-key badge's label could flip via data-field on a poll tick
       while its CSS class stayed stale at whatever the initial render
       painted). Mapping comes from BADGE_SPECIAL_CASES, generated from the
       SAME Python dict execution_grid.py's badge_css_and_label() reads —
       "open" maps to badge-pending/"open", not the generic hyphenated
       form, and that special case now lives in exactly one place instead
       of two hand-synced ones. Getting it wrong here would make the FIRST
       poll tick after page load immediately overwrite a correct initial
       badge-pending render with a wrong badge-open on every open issue,
       forever (every 3s), which is worse than the "never updates" bug
       #1180 exists to fix. */
    var statusEls = document.querySelectorAll("[data-status]");
    for (var s = 0; s < statusEls.length; s++) {
      var statusEl = statusEls[s];
      var statusField = statusEl.getAttribute("data-status");
      var statusValue = resolve(state, statusField, statusEl);
      /* Guard the type, not just presence: state.json is written
         server-side and should only ever carry a string status here, but a
         malformed field (null/number/object) would otherwise throw inside
         .replace() below, and pollState()'s catch() would silently
         misreport that as a FETCH failure, permanently disabling ALL live
         updates for the session (not just this badge) — the same
         typeof guard data-bind-width already applies above. */
      if (typeof statusValue === "string") {
        var special = BADGE_SPECIAL_CASES[statusValue];
        var badgeCss = special ? special[0] : "badge-" + statusValue.replace(/_/g, "-");
        var badgeLabel = special ? special[1] : statusValue.replace(/_/g, " ");
        /* Remove existing badge classes */
        statusEl.className = statusEl.className.replace(/badge-\\S+/g, "").trim();
        statusEl.classList.add(badgeCss);
        statusEl.textContent = badgeLabel;
      }
    }

    /* Update footer timestamp */
    var tsEl = document.querySelector("[data-timestamp]");
    if (tsEl) {
      tsEl.textContent = "Last updated: " + new Date().toLocaleTimeString();
    }
  }

  function pollState() {
    fetch(STATE_URL)
      .then(function (response) {
        if (!response.ok) {
          throw new Error("HTTP " + response.status);
        }
        return response.json();
      })
      .then(function (state) {
        applyState(state);
      })
      .catch(function () {
        /* Disable polling on failure [R-28] */
        if (timerId !== null) {
          clearInterval(timerId);
          timerId = null;
        }
        /* Fall back to meta-refresh for file:// protocol */
        if (window.location.protocol === "file:" &&
            !document.querySelector('meta[http-equiv="refresh"]')) {
          var meta = document.createElement("meta");
          meta.httpEquiv = "refresh";
          meta.content = "5";
          document.head.appendChild(meta);
        }
        var notice = document.querySelector("[data-fallback-notice]");
        if (notice) {
          notice.style.display = "block";
          notice.textContent = "Live updates unavailable \\u2014 refresh to update";
        }
      });
  }

  /* Start polling [R-27] */
  timerId = setInterval(pollState, POLL_INTERVAL_MS);

  /* Run once immediately so the dashboard is current on load */
  pollState();
})();
</script>"""
