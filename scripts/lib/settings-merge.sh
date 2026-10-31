# shellcheck shell=bash
# settings-merge.sh — the one settings.json merge, sourced by ./install and
# scripts/install-remote.sh (#1360). A library: source it, never run it.
#
# Before #1360 the remote installer carried its own copy of the merge, forked
# before #734, and it had lost the kit-owned "*"-matcher union, the old hook-path
# migration, the #1109 inline stall-guard removal and the #1225 duplicate
# collapse. One definition here keeps the two installers from drifting again.
#
# Contract. The caller defines, before calling anything here:
#   info ok warn skip drift    one-line output helpers
#   CELLAR_DIR SCRIPTS_DIR CLAUDE_DIR
#   LOCAL_MODE                 optional; "true" for ./install --local, unset otherwise
# jq is required (merge_settings warns and returns 1 without it). python3 is
# optional: without it the duplicate check warns and passes.
#
# The release tarball ships this directory as scripts/lib/, and both installers
# deploy it to $CELLAR_DIR/lib/. It is a subdirectory, so it is never farmed onto PATH.

SETTINGS_MERGE_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# In a $HOME/.claude/settings.json, rewrite any hook command path of the
# shape "~/.local/bin/hooks/..." to "~/.claude/scripts/hooks/...". Walks
# every hooks.<event>[].hooks[].command and applies a literal-string replace.
# Idempotent. Modifies $1 in place via tmpfile rotation.
rewrite_old_hook_paths_in_settings() {
	local target="$1"
	[[ -f "$target" ]] || return 0
	command -v jq &>/dev/null || return 0
	# jq walk: for any string ending up under hooks.*.hooks.*.command,
	# rewrite leading "~/.local/bin/hooks/" → "~/.claude/scripts/hooks/".
	local rewritten
	rewritten=$(jq '
		if .hooks then
			.hooks |= with_entries(
				if .key == "_comment" then . else
					.value |= map(
						.hooks |= map(
							if .command and (.command | startswith("~/.local/bin/hooks/")) then
								.command = ("~/.claude/scripts/hooks/" + (.command | ltrimstr("~/.local/bin/hooks/")))
							else . end
						)
					)
				end
			)
		else . end
	' "$target")
	echo "$rewritten" >"$target"
}

# #1109: the wavemachine stall guard used to ship as ONE INLINE shell command
# under hooks.Stop. The merge below keys template hooks on their exact command
# text, so once the guard moved to a script, an upgraded host would keep the old
# inline copy beside the new one and both would fire. Remove every inline (not
# path-based: the command does not start with ~, / or $) Stop command that reads
# wavemachine_active from .claude/status/state.json, and any matcher group left
# empty. Modifies $1 in place; prints the number of commands removed.
remove_legacy_inline_stall_guard() {
	local target="$1"
	if [[ ! -f "$target" ]] || ! command -v jq &>/dev/null; then
		echo 0
		return 0
	fi
	# shellcheck disable=SC2016 # $c is a jq variable, not a shell one
	local legacy='def legacy: (.command // "") as $c
		| ($c | test("^[~/$]") | not)
		and ($c | contains("wavemachine_active"))
		and ($c | contains(".claude/status/state.json"));'
	local count rewritten
	count=$(jq "$legacy"' [.hooks.Stop[]?.hooks[]? | select(legacy)] | length' "$target" 2>/dev/null) || count=0
	if [[ "$count" -gt 0 ]]; then
		rewritten=$(jq "$legacy"'
			.hooks.Stop |= (map(.hooks |= ((. // []) | map(select(legacy | not))))
				| map(select((.hooks | length) > 0)))' "$target") || {
			echo 0
			return 0
		}
		echo "$rewritten" >"$target"
	fi
	echo "$count"
}

# --local only: rewrite KIT-OWNED hook command paths in a settings.json from
# their global "~/"-relative form (which ALWAYS expands to $HOME, pointing at
# the GLOBAL install) to ABSOLUTE project-local paths under <cwd>/.claude/.
# Absolute (not "~/"-relative, not "./"-relative) because cwd at hook-exec
# time is not guaranteed. Three kit prefixes are rewritten:
#   ~/.claude/scripts/hooks/...          → $CELLAR_DIR/hooks/...
#   ~/.local/bin/<name>                  → $SCRIPTS_DIR/<name>
#   bash ~/.claude/statusline-command.sh → bash $CLAUDE_DIR/statusline-command.sh
# Foreign/absolute non-kit paths (e.g. /opt/..., a sibling-repo hook) and any
# inline hook using $CLAUDE_PROJECT_DIR (already project-relative) are LEFT
# UNTOUCHED. Must run AFTER the settings merge — the merge's kit-ownership
# detection keys on the original "~/.claude/" / "~/.local/bin/" template
# strings; absolute <cwd>/.claude/... still matches its "\.claude/" probe.
# Walks hooks.<event>[].hooks[].command AND statusLine.command. Modifies $1
# in place via tmpfile rotation. Idempotent for already-absolute paths.
rewrite_kit_hook_paths_to_local() {
	local target="$1"
	[[ -f "$target" ]] || return 0
	command -v jq &>/dev/null || return 0
	local rewritten
	rewritten=$(jq \
		--arg cellar_hooks "$CELLAR_DIR/hooks/" \
		--arg farm "$SCRIPTS_DIR/" \
		--arg statusline "bash $CLAUDE_DIR/statusline-command.sh" '
		# Rewrite a single command string from its global kit form to the
		# absolute project-local equivalent. Non-kit strings pass through.
		def relocate:
			if . == null then .
			elif startswith("~/.claude/scripts/hooks/") then
				$cellar_hooks + ltrimstr("~/.claude/scripts/hooks/")
			elif startswith("~/.local/bin/") then
				$farm + ltrimstr("~/.local/bin/")
			elif . == "bash ~/.claude/statusline-command.sh" then
				$statusline
			else . end;
		(if .hooks then
			.hooks |= with_entries(
				if .key == "_comment" then . else
					.value |= map(
						.hooks |= map(
							if .command then .command |= relocate else . end
						)
					)
				end
			)
		else . end)
		| (if (.statusLine | type) == "object" and (.statusLine.command? != null)
			then .statusLine.command |= relocate else . end)
	' "$target")
	echo "$rewritten" >"$target"
}

# Detect any settings.json hook command paths of the old form. Prints the
# offending event names (one per line) for use in --check drift reporting.
detect_old_hook_paths_in_settings() {
	local target="$1"
	[[ -f "$target" ]] || return 0
	command -v jq &>/dev/null || return 0
	jq -r '
		.hooks // {} | to_entries[] |
		select(.key != "_comment") |
		. as $e |
		.value |
		map(.hooks // []) | add // [] |
		map(.command // "") |
		map(select(startswith("~/.local/bin/hooks/"))) |
		if length > 0 then $e.key else empty end
	' "$target" 2>/dev/null
}

# Collapse, then independently verify, duplicate hook registrations in a
# settings file this install just wrote (#1225). A hook registered twice RUNS
# twice — a --local install that doubled every kit hook went unnoticed because
# the only duplicate check ran in the container build, never on a host. Identity
# ("what is one hook") lives in assert-no-duplicate-hooks.sh alone; the fixer and
# the checker are the same script, so they cannot disagree. A duplicate that
# survives --fix aborts the install (set -e) rather than shipping a doubled file.
assert_no_duplicate_hooks() {
	local target="$1" guard="$SETTINGS_MERGE_LIB_DIR/assert-no-duplicate-hooks.sh" out rc
	if ! command -v python3 &>/dev/null || [[ ! -f "$guard" ]]; then
		warn "cannot check $target for duplicate hook registrations (python3 or $guard missing)"
		return 0
	fi
	# Exit 2 is "nothing judgeable" (no path-rooted hook commands) — reported, not
	# fatal: there is no duplicate to ship. Exit 1 is a duplicate and IS fatal.
	rc=0
	out=$(bash "$guard" --fix "$target" 2>&1) || rc=$?
	if [[ $rc -eq 2 ]]; then
		warn "hooks — duplicate check had nothing to judge: ${out#assert-no-duplicate-hooks: }"
		return 0
	elif [[ $rc -ne 0 ]]; then
		warn "duplicate-hook check failed on $target:"
		printf '%s\n' "$out" >&2
		return 1
	fi
	# if/fi, not `[[ ]] && drift`: under set -e a loop whose last body command
	# is a false `[[ ]]` returns 1 and would abort the install.
	while IFS= read -r line; do
		if [[ "$line" == *collapsed* ]]; then
			drift "${line#assert-no-duplicate-hooks: }"
		fi
	done <<<"$out"
	if ! out=$(bash "$guard" "$target" 2>&1); then
		warn "duplicate hook registrations remain in $target after --fix:"
		printf '%s\n' "$out" >&2
		return 1
	fi
	ok "hooks — ${out#assert-no-duplicate-hooks: }"
}

merge_settings() {
	local template="$1" target="$2"

	# Requires jq
	if ! command -v jq &>/dev/null; then
		warn "jq not found — cannot merge settings.json"
		return 1
	fi

	# --local: merge against a RELOCATED copy of the template (#1225). The local
	# file holds kit hooks at absolute <cwd>/.claude/... paths (rewritten by the
	# previous install), while the template spells them "~/.claude/...". Compared
	# raw, no template signature ever matched a local one, so every re-run
	# appended the whole kit again and the post-merge rewrite made the copies
	# absolute too — every kit hook doubled per run. Relocating the template first
	# compares like with like. The kit-ownership probe below ("\.claude/") still
	# matches the absolute form.
	local tpl_local=""
	if [[ "${LOCAL_MODE:-false}" == true ]]; then
		tpl_local="$(mktemp)"
		cp "$template" "$tpl_local"
		rewrite_kit_hook_paths_to_local "$tpl_local"
		template="$tpl_local"
	fi

	cp "$target" "${target}.bak"

	# Migrate any pre-Cellar hook command paths (~/.local/bin/hooks/...) to
	# the new Cellar location (~/.claude/scripts/hooks/...) BEFORE merge so
	# the union step compares apples to apples (template uses new paths).
	local old_path_events
	old_path_events=$(detect_old_hook_paths_in_settings "$target")
	if [[ -n "$old_path_events" ]]; then
		rewrite_old_hook_paths_in_settings "$target"
		while IFS= read -r ev; do
			[[ -z "$ev" ]] && continue
			info "hooks.$ev — migrated old path(s) ~/.local/bin/hooks/... → ~/.claude/scripts/hooks/..."
		done <<<"$old_path_events"
	fi

	# Drop the pre-#1109 inline stall guard, so the script version that the
	# union below adds is the only one left.
	local legacy_guards
	legacy_guards=$(remove_legacy_inline_stall_guard "$target")
	if [[ "$legacy_guards" -gt 0 ]]; then
		info "hooks.Stop — removed $legacy_guards inline wavemachine stall guard(s), replaced by wavemachine-stall-guard.sh (#1109)"
	fi

	# Deep merge: template into local, preserving user customizations
	# Rules:
	#   1. Top-level keys (scalars AND objects like statusLine): added only if ABSENT locally
	#   2. hooks:
	#      - Event keys missing locally: added from template
	#      - Event keys present in both: matcher arrays unioned by .matcher value
	#        (template matcher entries whose .matcher is not in the local array
	#        are appended; existing local entries are left untouched, preserving
	#        user customizations to the per-matcher hooks list)
	#   3. permissions.allow: union of both arrays (deduplicated)
	#   4. enabledPlugins: add missing keys from template; leave existing alone
	#   5. _comment keys: stripped from result (template-only documentation)
	#   6. Any key present locally but not in template: preserve as-is
	local merged
	merged=$(jq -s '
		# .[0] = template, .[1] = local

		# Top-level keys from template (excluding special-merge keys)
		(.[0] | to_entries | map(
			select(.key | IN("hooks", "permissions", "enabledPlugins", "_comment") | not)
		)) as $tpl_defaults |

		# Capture local keys before entering reduce
		(.[1] | keys) as $local_keys |

		# Merge hooks: add missing event keys AND union matcher arrays for shared keys
		((.[0].hooks // {}) | to_entries | map(
			select(.key != "_comment")
		)) as $tpl_hooks |
		((.[1].hooks // {}) | to_entries | map(
			select(.key != "_comment")
		)) as $local_hooks |
		((.[1].hooks // {}) | keys) as $local_hook_keys |
		# New event keys (template only) — add wholesale
		($tpl_hooks | map(select(.key | IN($local_hook_keys[]) | not))) as $new_hooks |
		# Shared event keys — union hook arrays, preserving user overrides while
		# still deploying the multi-hook kit events (#734, option C).
		# (No apostrophes in these comments — they live inside a single-quoted jq
		# program and an apostrophe would terminate the shell string.)
		# Three add-conditions for a template entry, gated first on de-dup
		# (its command-signature must not already be present locally):
		#   1. NEW matcher (not in local) — add (preserves #556 AC1).
		#   2. EXISTING matcher, but the entry is KIT-OWNED (a command referencing
		#      a kit path: ~/.local/bin/ or .claude/) — add. This is the #734 fix:
		#      the kit ships multiple distinct "*" Stop hooks (precheck-asking +
		#      wavemachine guard + stop-action-bias) that must coexist; a plain
		#      matcher-keyed union silently dropped all but the first.
		#   3. EXISTING matcher, NOT kit-owned — DO NOT add. A user hook under a
		#      shared matcher still overrides the kit version (preserves #556 AC2);
		#      the kit never resurrects or layers onto a genuinely-custom user hook.
		# Local/user hooks are always preserved; identical hooks never duplicated.
		# Signature = sorted list of .hooks[].command.
		($tpl_hooks | map(select(.key | IN($local_hook_keys[]))) | map({
			key: .key,
			value: (
				(.value // []) as $tpl_arr |
				(($local_hooks | from_entries)[.key] // []) as $local_arr |
				($local_arr | map([.hooks[].command // empty] | sort)) as $local_sigs |
				($local_arr | map(.matcher)) as $local_matchers |
				$local_arr + ($tpl_arr | map(select(
					(([.hooks[].command // empty] | sort) as $sig | ($local_sigs | map(. == $sig) | any) | not)
					and (
						(.matcher as $m | $local_matchers | index($m) | not)
						or ([.hooks[].command // empty] | map(test("\\.local/bin/|\\.claude/")) | any)
					)
				)))
			)
		}) | from_entries) as $merged_shared_hooks |

		# Merge permissions.allow: union
		((.[0].permissions.allow // []) + (.[1].permissions.allow // []) | unique) as $merged_perms |

		# Merge enabledPlugins: add missing keys
		((.[0].enabledPlugins // {}) | to_entries) as $tpl_plugins |
		((.[1].enabledPlugins // {}) | keys) as $local_plugin_keys |
		($tpl_plugins | map(select(.key | IN($local_plugin_keys[]) | not))) as $new_plugins |

		# Build result: start with local, add missing pieces
		.[1]
		| .permissions.allow = $merged_perms
		| .hooks = ((.hooks // {}) + ($new_hooks | from_entries) + $merged_shared_hooks)
		| .enabledPlugins = ((.enabledPlugins // {}) + ($new_plugins | from_entries))
		| reduce ($tpl_defaults[] | select(.key | IN($local_keys[]) | not)) as $s (.; .[$s.key] = $s.value)
		| del(._comment)
		| del(.hooks._comment)
	' "$template" "$target")

	echo "$merged" >"$target"

	# --local: relocate kit-owned "~/"-relative hook paths to absolute
	# project-local paths. AFTER the merge so the kit-ownership union above
	# saw the original template strings (it keys on "~/.claude/" / "~/.local/bin/").
	if [[ "${LOCAL_MODE:-false}" == true ]]; then
		rewrite_kit_hook_paths_to_local "$target"
	fi

	# Collapse any duplicates already present (a file doubled by an older
	# install) and fail on any that survive.
	assert_no_duplicate_hooks "$target"

	# Report what changed

	# Report new hooks (and new matchers within shared event keys)
	for hook_event in $(jq -r '.hooks // {} | keys[] | select(. != "_comment")' "$template"); do
		if jq -e ".hooks.\"${hook_event}\"" "${target}.bak" &>/dev/null; then
			# Event already exists locally — diff matcher arrays and report any
			# template matchers that were appended by the union-merge.
			local added_matchers
			added_matchers=$(jq -r --arg ev "$hook_event" --slurpfile bak "${target}.bak" '
				(($bak[0].hooks[$ev] // []) | map(.matcher)) as $local_ms |
				(.hooks[$ev] // []) | map(.matcher) | map(select(. as $m | $local_ms | index($m) | not)) | .[]
			' "$target")
			if [[ -z "$added_matchers" ]]; then
				skip "hooks.$hook_event — already present (skipped)"
			else
				while IFS= read -r m; do
					[[ -z "$m" ]] && continue
					info "hooks.$hook_event — matcher \"$m\" added"
				done <<<"$added_matchers"
			fi
		else
			info "hooks.$hook_event — added"
		fi
	done

	# Report new plugins
	for plugin in $(jq -r '.enabledPlugins // {} | keys[]' "$template"); do
		# has(), not a value test: a plugin the user set to false is present (#1360).
		if jq -e --arg p "$plugin" '.enabledPlugins | has($p)' "${target}.bak" &>/dev/null; then
			skip "enabledPlugins.$plugin — already present (skipped)"
		else
			info "enabledPlugins.$plugin — added"
		fi
	done

	# Report permissions
	local old_perm_count new_perm_total
	old_perm_count=$(jq '.permissions.allow | length' "${target}.bak")
	new_perm_total=$(jq '.permissions.allow | length' "$target")
	local perm_diff=$((new_perm_total - old_perm_count))
	if [[ $perm_diff -gt 0 ]]; then
		info "permissions — $perm_diff new entries merged"
	else
		skip "permissions — no new entries"
	fi

	[[ -z "$tpl_local" ]] || rm -f "$tpl_local"
}
