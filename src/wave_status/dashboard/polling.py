"""Dashboard polling script: JavaScript for live-updating the dashboard.

Generates a self-contained ``<script>`` block that:
- Fetches ``state.json`` every 3 seconds  [R-27]
- Updates DOM elements via ``data-*`` attribute selectors  [R-29]
- Disables polling on fetch failure with a fallback notice  [R-28]

No external dependencies — Python 3.10+ stdlib only  [CT-01].
"""

from __future__ import annotations


def render_polling_script() -> str:
    """Return a ``<script>`` block for dashboard live-update polling.

    The script:
    - Uses ``setInterval`` to fetch ``state.json`` every 3 000 ms.
    - On success, updates every element that has a ``data-field`` attribute
      with the corresponding value from the JSON response.
    - On fetch failure (e.g. ``file://`` CORS or network error), clears the
      interval and displays a fallback notice in the footer.
    """
    return """\
<script>
(function () {
  "use strict";

  var POLL_INTERVAL_MS = 3000;
  var timerId = null;

  /**
   * Update a single DOM element from a (possibly nested) state value.
   * Elements declare their binding via data-field="dotted.path".
   */
  function resolve(obj, path) {
    var parts = path.split(".");
    var cur = obj;
    for (var i = 0; i < parts.length; i++) {
      if (cur == null) return undefined;
      cur = cur[parts[i]];
    }
    return cur;
  }

  function applyState(state) {
    var elements = document.querySelectorAll("[data-field]");
    for (var i = 0; i < elements.length; i++) {
      var el = elements[i];
      var field = el.getAttribute("data-field");
      var value = resolve(state, field);
      if (value !== undefined) {
        el.textContent = String(value);
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

    /* Update badge classes for elements with data-status */
    var statusEls = document.querySelectorAll("[data-status]");
    for (var s = 0; s < statusEls.length; s++) {
      var statusEl = statusEls[s];
      var statusField = statusEl.getAttribute("data-status");
      var statusValue = resolve(state, statusField);
      if (statusValue !== undefined) {
        /* Remove existing badge classes */
        statusEl.className = statusEl.className.replace(/badge-\\S+/g, "").trim();
        statusEl.classList.add("badge-" + statusValue.replace(/_/g, "-"));
        statusEl.textContent = statusValue.replace(/_/g, " ");
      }
    }

    /* Update footer timestamp */
    var tsEl = document.querySelector("[data-timestamp]");
    if (tsEl) {
      tsEl.textContent = "Last updated: " + new Date().toLocaleTimeString();
    }
  }

  function pollState() {
    fetch("state.json")
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
