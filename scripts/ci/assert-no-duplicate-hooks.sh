#!/usr/bin/env bash
# assert-no-duplicate-hooks.sh — no two hook commands under one matcher may
# resolve to the same script.
#
# WHY THIS EXISTS (#1094). The image's baked settings.json registered
# wtf-post-tool-use.sh TWICE under PostToolUse with an empty matcher — once as
# `~/.local/share/...` (from settings.template.json) and once as
# `/home/ubuntu/.local/share/...` (added later by wtf-server's own installer,
# whose idempotency check compared raw strings). Both resolve to the same file,
# so the hook fired twice on every tool use. It went unnoticed for weeks because
# nothing ever asked the question.
#
# The source is fixed in mcp-server-wtf#34, but fixing one installer does not
# make the class impossible: EVERY MCP server's install-remote.sh writes hook
# registrations into this same file during the build, each with its own notion of
# "already present". This asserts the invariant instead of trusting each of them.
#
# IDENTITY MATCHES bootstrap.sh's runtime merge, deliberately. That function
# decides what "one hook" means when merging into the fleet-shared settings; a
# build gate that drew the line somewhere else would either reject a config the
# runtime accepts, or pass one it treats as two. So, exactly as `key()` there:
#   - only PATH-ROOTED heads (`/`, `~`, `$`) carry identity — inline shell, bare
#     builtins and PATH-resolved names are not ours to judge (and keying on a
#     bare first token calls `python3 /a.py` and `python3 /b.py` duplicates);
#   - ARGUMENTS ARE PART OF IDENTITY — `emit.sh idle` and `emit.sh close` are two
#     hooks, and flightdeck-session-emit.sh is exactly that verb-dispatcher shape;
#   - the `[ -x <path> ] || exit 0; <path>` guard (#1107) is stripped, since
#     keying on its leading `[` would call a guarded and a bare spelling of one
#     hook two different hooks and report all-clear.
#
# Usage: assert-no-duplicate-hooks.sh [settings.json]   (default: ~/.claude/settings.json)
# Exit:  0 no duplicates; 1 a duplicate registration exists; 2 unusable input.
set -euo pipefail

SETTINGS="${1:-$HOME/.claude/settings.json}"

if [[ ! -f "$SETTINGS" ]]; then
	echo "assert-no-duplicate-hooks: no settings at $SETTINGS — nothing to check" >&2
	exit 2
fi

python3 - "$SETTINGS" <<'PY'
import json
import os
import re
import sys

path = os.path.abspath(sys.argv[1])

# The home to expand `~` against is derived from the FILE, not the environment.
# `<home>/.claude/settings.json` -> `<home>`. Reading it from $HOME instead makes
# this whole assertion depend on an ambient variable nobody asserts: run it as a
# user whose $HOME differs from the settings file's owning home — an operator
# checking a container's file from a host shell, or one `ENV HOME=` change in the
# Dockerfile — and `~/.local/share/x` stops matching `/home/ubuntu/.local/share/x`,
# so the script reports "no duplicates" over the precise bug it exists to catch.
parent = os.path.dirname(path)
home = os.path.dirname(parent) if os.path.basename(parent) == ".claude" else os.path.expanduser("~")

try:
    with open(path) as fh:
        data = json.load(fh)
except Exception as exc:  # noqa: BLE001 - report, do not mask
    print(f"assert-no-duplicate-hooks: cannot parse {path}: {exc}", file=sys.stderr)
    raise SystemExit(2)

if not isinstance(data, dict):
    print(f"assert-no-duplicate-hooks: {path} is not a JSON object", file=sys.stderr)
    raise SystemExit(2)

GUARD = re.compile(r"^\[ -x \S+ \] \|\| exit 0;\s*")


def resolved(command):
    """The script a command runs plus its arguments, independent of spelling.

    None when the command is not path-rooted — those carry no identity we can
    judge, and pretending otherwise is how `python3 /a.py` and `python3 /b.py`
    become a "duplicate".
    """
    bare = GUARD.sub("", (command or "").strip())
    if not bare:
        return None
    head = bare.split(" ", 1)[0]
    tail = bare[len(head):]
    if head.startswith("~/"):
        script = home + head[1:]
    elif head.startswith("${HOME}/"):
        script = home + head[7:]
    elif head.startswith("$HOME/"):
        script = home + head[5:]
    elif head.startswith(("/", "$")):
        script = os.path.expandvars(head)
    else:
        return None
    return script + tail if script.startswith("/") else None


hooks = data.get("hooks")
if not isinstance(hooks, dict) or not hooks:
    # An empty denominator is not a pass. The whole failure mode here is a
    # question nobody asked, so "asked it and there was nothing to ask about"
    # must be distinguishable from "did not ask".
    print(f"assert-no-duplicate-hooks: {path} declares NO hooks — refusing to "
          "report a clean result over an empty set", file=sys.stderr)
    raise SystemExit(2)

seen = {}
dupes = []
checked = 0
for event, groups in hooks.items():
    if not isinstance(groups, list):
        continue
    for group in groups:
        if not isinstance(group, dict):
            continue
        matcher = group.get("matcher") or ""
        for hook in group.get("hooks") or []:
            if not isinstance(hook, dict) or not isinstance(hook.get("command"), str):
                continue
            script = resolved(hook["command"])
            if script is None:
                continue
            checked += 1
            key = (event, matcher, script)
            if key in seen:
                dupes.append((event, matcher, script, seen[key], hook["command"]))
            else:
                seen[key] = hook["command"]

if not checked:
    # Same doctrine as the no-hooks case, one level down: a hooks block whose
    # every entry was skipped (a schema change, an unexpected shape) would
    # otherwise print a clean result over zero inspected registrations.
    print(f"assert-no-duplicate-hooks: {path} has a hooks block but ZERO "
          "judgeable registrations — refusing to report a clean result",
          file=sys.stderr)
    raise SystemExit(2)

if dupes:
    print(f"assert-no-duplicate-hooks: {len(dupes)} duplicate registration(s) in {path}",
          file=sys.stderr)
    for event, matcher, script, first, second in dupes:
        print(f"  {event} matcher={matcher!r} both resolve to {script}", file=sys.stderr)
        print(f"    1) {first}", file=sys.stderr)
        print(f"    2) {second}", file=sys.stderr)
    print("  a hook registered twice RUNS twice on every matching event",
          file=sys.stderr)
    raise SystemExit(1)

print(f"assert-no-duplicate-hooks: {checked} hook registration(s), no duplicates")
PY
