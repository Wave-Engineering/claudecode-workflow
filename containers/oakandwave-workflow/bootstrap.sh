#!/usr/bin/env bash
#
# bootstrap.sh — the container bootstrap (Story 1.4, #964, Plan #959).
#
# Runs before the agent (via the aoe-hooks seam — open probe Dev Spec §5.N#5) and
# performs, in order: env validation, skills symlink-sync, kit hook-wiring merge,
# R-11 toolbox materialisation, and secret sourcing + required-secret validation.
# It is the load-bearing instrument the whole container leans on (SKETCHBOOK D7), so it is written to the
# **assertion-liveness** discipline from line one:
#
#   Every silent-skip path becomes a LOGGED or FAILING condition — never a check
#   that "reported fine and did nothing." The four enumerated silent-skips
#   (Dev Spec §5.4 / SKETCHBOOK D7) each have an explicit guard here:
#
#     missing mount   -> WARN "missing mount: ..."         (logged, tolerated)
#     shadowed skill  -> WARN "skills-sync collision: ..." (logged, image wins)
#     dangling link   -> WARN "dangling symlink: ..."      (logged)
#     missing secret  -> FATAL "required secret missing"   (fails loud, R-14)
#
# Skills-sync (SKETCHBOOK D5): the image bakes skills (versioned, R-06); a host
# overlay may *fill gaps*. The sync is **image-wins / host-fills**: for each host
# skill with no same-named image skill, symlink it into the image skills dir using
# its FULL target path (never a bare basename — the D5 self-reference bug); a host
# skill that collides with an image skill is shadowed (image wins) and LOGGED.
# Skills are symlink-safe artifacts (scripts/markdown, not compiled binaries), so
# symlinking them across the host/container boundary is R-10-correct.
#
# Secrets (SKETCHBOOK D6 as amended by #1061, R-12/R-14): NAMED single-file
# read-only bind-mounts under ~/.secrets — not the whole dir, which handed every
# container both sides of the OaW/Analogic IP boundary. `.env` is the env modality
# (sourced here) and carries POINTERS, never token values; loose files are the
# path modality (NEVER auto-exported to env — that re-leaks via
# /proc/<pid>/environ AND into every child process). The required-secret set is
# declared by OAW_REQUIRED_SECRETS in that .env; any required secret missing at
# boot fails loud. See ../secrets-env.example.
#
# Every path is env-injectable (defaults derived from $HOME) so the oracle
# (tests/contained-workflow/test_bootstrap.py) drives this for real with fake
# dirs — no docker — exactly like the mount-resolver unit oracle. Config knobs:
#
#   OAW_HOME                        root (default: $HOME)
#   OAW_SKILLS_IMAGE                baked skills, image-wins (default: $HOME/.claude/skills)
#   OAW_SKILLS_HOST                 host skills overlay, fills gaps
#                                   (default: $HOME/.oaw/.claude/skills)
#   OAW_SETTINGS_JSON               baked hook wiring, the merge SOURCE
#                                   (default: $HOME/.claude/settings.json)
#   OAW_TOOLBOX_DIR                 R-11 durable toolbox mount, where mise
#                                   materialises declared toolchains
#                                   (default: $HOME/.oaw/toolbox)
#   OAW_SECRETS_DIR                 ro secrets mount (default: $HOME/.secrets)
#   OAW_REQUIRED_SECRETS            whitespace-separated required secret names (wins)
#   OAW_REQUIRED_SECRETS_MANIFEST   values-free manifest file, one name per line,
#                                   `#` comments allowed
#                                   (default: $OAW_SECRETS_DIR/required.manifest)
#   OAW_REQUIRED_ENV                whitespace-separated required env vars (default: HOME)
#   OAW_NO_AUTO_TRUST               set to ANY non-empty value to skip recording
#                                   the workspace as trusted (#1079). Onboarding
#                                   state is still cleared; only the per-project
#                                   trust entry is withheld, so the CLI shows its
#                                   trust dialog. Note `=0` and `=false` also
#                                   disable it — non-empty is the test, matching
#                                   OAW_SKIP_BOOTSTRAP in claude-entrypoint.sh.

set -euo pipefail

WARN_COUNT=0
FATAL_COUNT=0
COLLISION_COUNT=0
DANGLING_COUNT=0

info() { echo "[bootstrap] INFO: $*" >&2; }

warn() {
	echo "[bootstrap] WARN: $*" >&2
	WARN_COUNT=$((WARN_COUNT + 1))
}

# fatal LOGS loud but does NOT exit immediately — we accumulate every fatal so the
# operator sees the full list in one boot, then exit non-zero at the end.
fatal() {
	echo "[bootstrap] FATAL: $*" >&2
	FATAL_COUNT=$((FATAL_COUNT + 1))
}

# --- Config resolution --------------------------------------------------------

OAW_HOME="${OAW_HOME:-${HOME:-}}"
if [[ -z "$OAW_HOME" ]]; then
	echo "[bootstrap] FATAL: neither OAW_HOME nor HOME is set — cannot resolve paths" >&2
	exit 1
fi

OAW_SKILLS_IMAGE="${OAW_SKILLS_IMAGE:-$OAW_HOME/.claude/skills}"
OAW_SKILLS_HOST="${OAW_SKILLS_HOST:-$OAW_HOME/.oaw/.claude/skills}"
OAW_SETTINGS_JSON="${OAW_SETTINGS_JSON:-$OAW_HOME/.claude/settings.json}"
OAW_SECRETS_DIR="${OAW_SECRETS_DIR:-$OAW_HOME/.secrets}"
OAW_REQUIRED_SECRETS_MANIFEST="${OAW_REQUIRED_SECRETS_MANIFEST:-$OAW_SECRETS_DIR/required.manifest}"

# --- The CLI's config location (#1085) ----------------------------------------
#
# THE AGENT DOES NOT NECESSARILY READ $HOME. aoe sets CLAUDE_CONFIG_DIR=/root/.claude
# and mounts its own config there, so everything bootstrap wrote to
# $OAW_HOME/.claude.json was landing in a file the CLI never opened. That single
# mistake produced five separate symptoms in production: a Settings Error panel,
# zero MCP servers, the onboarding wizard returning every launch, a trust prompt
# per workspace, and a "401 token has been revoked" for a token that was valid.
#
# It survived three rounds of verification because every one of them used
# `docker run` with the profile's volumes. Only `aoe` injects CLAUDE_CONFIG_DIR,
# so the harness could not see the bug — the test was the wrong SHAPE, not the
# config. Resolve it here, once, and let every consumer use it.
OAW_CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$OAW_HOME/.claude}"
# The config FILE does not simply live under the config DIR in both cases, and
# assuming it does silently relocates the native (non-aoe) config:
#   CLAUDE_CONFIG_DIR set   -> $CLAUDE_CONFIG_DIR/.claude.json   (verified live)
#   unset                   -> $HOME/.claude.json                (home ROOT, not
#                              $HOME/.claude/.claude.json)
# The first cut collapsed these into one expression and broke every non-aoe path;
# the pre-existing #1079 tests caught it immediately.
if [[ -n "${CLAUDE_CONFIG_DIR:-}" ]]; then
	OAW_CLAUDE_CONFIG_FILE="$CLAUDE_CONFIG_DIR/.claude.json"
else
	OAW_CLAUDE_CONFIG_FILE="$OAW_HOME/.claude.json"
fi
# The pre-aoe location, still the image's own baked copy: it is where `./install`
# registers the kit's MCP servers at BUILD time, so it is the SOURCE we merge
# FROM when the CLI reads somewhere else.
OAW_IMAGE_CONFIG_FILE="$OAW_HOME/.claude.json"
OAW_EFFECTIVE_SETTINGS="$OAW_CLAUDE_CONFIG_DIR/settings.json"

# --- Stage 1: env validation --------------------------------------------------

validate_env() {
	local -a required_env=()
	IFS=' ' read -r -a required_env <<<"${OAW_REQUIRED_ENV:-HOME}"
	local name
	for name in "${required_env[@]:-}"; do
		[[ -n "$name" ]] || continue
		if [[ -z "${!name:-}" ]]; then
			fatal "required env missing: \$$name"
		else
			info "env: \$$name set"
		fi
	done
	return 0
}

# --- Stage 2: skills symlink-sync (image-wins / host-fills, collision-logged) --

# Scan a skills dir for dangling symlinks (a link whose target does not resolve —
# e.g. the D5 bare-basename self-reference bug, or a stale gap-filler). Each is a
# silent-skip path made loud.
scan_dangling() {
	local dir="$1" link
	[[ -d "$dir" ]] || return 0
	shopt -s nullglob
	for link in "$dir"/*; do
		# -L true for a symlink; -e false when its target does not resolve.
		if [[ -L "$link" && ! -e "$link" ]]; then
			warn "dangling symlink: $link -> $(readlink "$link") (target missing)"
			DANGLING_COUNT=$((DANGLING_COUNT + 1))
		fi
	done
	shopt -u nullglob
	return 0
}

sync_skills() {
	local host="$OAW_SKILLS_HOST" image="$OAW_SKILLS_IMAGE"

	if [[ ! -d "$host" ]]; then
		# Missing mount: tolerate it, but say so — and do NOT create dangling
		# links (SKETCHBOOK D5: "tolerate an absent mount without dangling links").
		warn "missing mount: host skills overlay not present ($host); skills-sync host-fill skipped"
		scan_dangling "$image"
		return 0
	fi

	mkdir -p "$image"

	local entry name dest cur
	shopt -s nullglob
	for entry in "$host"/*; do
		name="$(basename "$entry")"
		dest="$image/$name"

		if [[ -L "$dest" ]]; then
			cur="$(readlink "$dest")"
			if [[ "$cur" == "$entry" ]]; then
				# Idempotent re-run: we already linked this gap-filler.
				info "skills-sync: '$name' already linked (host-fill)"
				continue
			fi
			# A link to something else already occupies the name — image wins.
			warn "skills-sync collision: host skill '$name' shadowed (image wins)"
			COLLISION_COUNT=$((COLLISION_COUNT + 1))
			continue
		fi

		if [[ -e "$dest" ]]; then
			# A real baked image skill occupies the name — image wins, host shadowed.
			warn "skills-sync collision: host skill '$name' shadowed by image (image wins)"
			COLLISION_COUNT=$((COLLISION_COUNT + 1))
			continue
		fi

		# Gap: host fills it. FULL target path (D5 fix — never a bare basename,
		# which would self-reference into a dangling link).
		#
		# -f: bootstrap now runs on EVERY `claude` invocation (it is the agent's
		# wrapper), so two concurrent invocations can both pass the `-e "$dest"`
		# check above and race here. Without -f the loser gets "File exists",
		# `set -e` aborts, and THAT agent never starts.
		ln -sfn "$entry" "$dest"
		info "skills-sync: linked host skill '$name' (host-fill)"
	done
	shopt -u nullglob

	scan_dangling "$image"
	return 0
}

# --- Stage 3: the kit's hook wiring, where the CLI reads it (#1086) -----------
#
# R-06 says hook wiring is VERSIONED WITH THE RELEASE — the image digest IS the
# release, so the hooks baked into it are the hooks that run. Under aoe that was
# false: the CLI reads $CLAUDE_CONFIG_DIR/settings.json (aoe's own config, host-
# backed and SHARED by every container) and never opens the image's copy.
#
# It looked healthy, which is why it survived: that shared file had been seeded
# from a host carrying the same kit, so an EQUIVALENT hook set was already sitting
# there and kit hooks did fire. What could not happen was version MOVEMENT. A hook
# the image added, renamed or repointed stayed on the operator's host timetable
# instead of the release's, and nothing reported the gap. R-06 held by coincidence,
# which is not the same as holding — and a coincidence is exactly what a promotion
# gate must not depend on.
#
# MERGE, the same way sync_kit_registrations merges mcpServers, and for the same
# reason: the destination is SHARED and legitimately carries things that are the
# operator's — aoe's own AOE_INSTANCE_ID status hooks, theme, model, permissions.
# So ADD what the image ships and touch nothing else. Image-authoritative for
# hooks; the operator keeps their preferences. (`./install`'s merge_settings applies
# this identical rule for a native install; this is that rule reapplied where aoe
# moved the file out from under it.)
#
# What this deliberately does NOT do is delete host-only hooks. The strong reading
# of "image-authoritative" would clobber aoe's own wiring and break its TUI. Stale
# host-only entries are already covered by validate_hook_paths, which reports any
# configured hook that cannot resolve in this namespace.
#
# NOTE ON settings.local.json — there is no such thing at user level. The R-03
# mount that used to land one at ~/.claude/settings.local.json was removed with
# this change: measured against the real CLI, `localSettings` is PROJECT-scoped
# (<project>/.claude/settings.local.json) and a settings.local.json beside the user
# settings.json is never read, aoe or not. The old Stage 3 warned when that mount
# was missing — an assertion about a file the CLI would have ignored anyway.
sync_kit_hooks() {
	if [[ ! -f "$OAW_SETTINGS_JSON" ]]; then
		warn "hooks: image settings.json not found ($OAW_SETTINGS_JSON) — the release ships no hook wiring to merge"
		return 0
	fi
	if [[ "$OAW_SETTINGS_JSON" == "$OAW_EFFECTIVE_SETTINGS" ]]; then
		info "hooks: the CLI reads the image settings directly — kit wiring already in place"
		return 0
	fi
	command -v python3 >/dev/null 2>&1 || {
		warn "hooks: python3 unavailable — cannot merge kit hook wiring into $OAW_EFFECTIVE_SETTINGS"
		return 0
	}
	# CREATE rather than bail, for the same reason sync_kit_registrations does: a
	# fresh aoe profile has a config dir with no settings.json in it, and warning-
	# and-returning there reproduces the very state this fixes — a container running
	# none of the release's hooks.
	if [[ ! -f "$OAW_EFFECTIVE_SETTINGS" ]]; then
		if mkdir -p "$OAW_CLAUDE_CONFIG_DIR" 2>/dev/null && printf '{}\n' >"$OAW_EFFECTIVE_SETTINGS" 2>/dev/null; then
			info "hooks: created $OAW_EFFECTIVE_SETTINGS (the CLI had no settings there)"
		else
			warn "hooks: $OAW_EFFECTIVE_SETTINGS absent and not creatable — the kit's hooks will not run"
			return 0
		fi
	fi

	local out
	if ! out="$(
		OAW_SRC="$OAW_SETTINGS_JSON" OAW_DST="$OAW_EFFECTIVE_SETTINGS" python3 - <<-'PY' 2>&1
			import fcntl, json, os

			src, dst = os.environ["OAW_SRC"], os.environ["OAW_DST"]
			with open(src) as fh:
			    want = json.load(fh).get("hooks", {})
			if not want:
			    print("no-kit-hooks")
			    raise SystemExit(0)

			def key(matcher, cmd):
			    """Dedup key: two commands that RESOLVE to the same script are one hook.

			    Keying on the raw string is not enough. The image bakes
			    wtf-post-tool-use.sh under BOTH `~/.local/share/...` (from
			    settings.template.json) and `/home/ubuntu/.local/share/...` (added at
			    build time), and the shared settings already carried the absolute form.
			    A string key called those two different hooks and registered the second,
			    so the hook fired TWICE on every tool use — a merge that introduces
			    duplicate execution is not preserving the release's wiring, it is
			    corrupting it. Measured live before this guard existed.

			    Expansion is for the KEY only; what gets written is always the image's
			    own string, byte for byte.
			    """
			    head, sep, tail = cmd.strip().partition(" ")
			    return matcher, os.path.expanduser(os.path.expandvars(head)) + sep + tail

			def commands(group):
			    """(matcher, hook) pairs in one hook group, skipping junk entries."""
			    if not isinstance(group, dict):
			        return
			    matcher = group.get("matcher") or ""
			    for h in group.get("hooks") or []:
			        if isinstance(h, dict) and isinstance(h.get("command"), str):
			            yield matcher, h

			# Locked read-modify-write: this file is shared by every container on the
			# host, so two agents starting together WILL interleave here.
			with open(dst, "r+") as fh:
			    fcntl.flock(fh, fcntl.LOCK_EX)
			    d = json.loads(fh.read() or "{}")
			    if not isinstance(d, dict):
			        raise SystemExit("__ERR__ effective settings is not a JSON object")
			    before = json.loads(json.dumps(d))  # pre-image for the recovery copy
			    have = d.setdefault("hooks", {})
			    if not isinstance(have, dict):
			        raise SystemExit("__ERR__ effective settings has a non-object 'hooks'")

			    added = []
			    for event, groups in want.items():
			        dst_groups = have.setdefault(event, [])
			        if not isinstance(dst_groups, list):
			            continue
			        # Keyed per MATCHER, never by command alone: the kit legitimately
			        # registers one script under several matchers — context-freshness-warn
			        # ships under BOTH `startup` and `resume` — and a command-only key
			        # would silently drop the second registration, which is this bug
			        # wearing a merge's clothes. See key() for the other half (two
			        # spellings of one path are one hook).
			        present = {key(m, h["command"]) for g in dst_groups for m, h in commands(g)}
			        for g in groups or []:
			            missing = []
			            for m, h in commands(g):
			                k = key(m, h["command"])
			                if k in present:
			                    continue
			                # Add to `present` as we go, so a source group that ships the
			                # same script twice under one matcher registers it once.
			                present.add(k)
			                missing.append(h)
			            if not missing:
			                continue
			            # NOT `k` — `k` is the dedup key three lines up. The comprehension
			            # has its own scope so reusing it is harmless, and unreadable.
			            group = {gk: gv for gk, gv in g.items() if gk != "hooks"}
			            group["hooks"] = missing
			            dst_groups.append(group)
			            # (… or ["?"]) — a hook whose command is the empty string is
			            # junk, but IndexError here would abort the whole merge and
			            # take every other event's wiring down with it.
			            added += [f"{event}:{(h['command'].split() or ['?'])[0]}" for h in missing]

			    if added:
			        # RECOVERY COPY before mutating, and an IN-PLACE write after — both
			        # inherited from sync_kit_registrations deliberately. A tmp+rename would
			        # be atomic against a torn write, but it mints a new inode, and this
			        # config directory is bind-mounted; keeping one inode keeps every view of
			        # the file the same file. The residual torn-write risk (kill/ENOSPC
			        # between write and truncate) is what the copy is for, in a file EVERY
			        # container reads.
			        try:
			            with open(dst + ".pre-bootstrap", "w") as bak:
			                bak.write(json.dumps(before, indent=2))
			        except Exception:
			            pass
			        data = json.dumps(d, indent=2)
			        fh.seek(0)
			        fh.write(data)
			        fh.truncate()
			print(",".join(added) if added else "already-present")
		PY
	)"; then
		warn "hooks: could not merge kit hook wiring into $OAW_EFFECTIVE_SETTINGS ($out)"
		return 0
	fi
	case "$out" in
	already-present) info "hooks: kit wiring already present in $OAW_EFFECTIVE_SETTINGS" ;;
	no-kit-hooks) warn "hooks: image settings.json declares no hooks — nothing to merge" ;;
	# No __ERR__ arm: `raise SystemExit("__ERR__ …")` exits 1, so those land in the
	# `if ! out=` branch above with the message already in $out. An arm here would
	# be unreachable — the kind of handler that reads as coverage and is never run.
	*) info "hooks: merged kit wiring into the CLI's settings: $out" ;;
	esac
	return 0
}

# --- Stage 3b: R-11 toolbox — materialise declared toolchains (#1092) ---------
#
# THE MECHANISM WAS DECLARED AND INERT. mounts.d/30-user-overlay.toml has wired
# the toolbox mount since Story 1.3 and described exactly this behaviour; nothing
# ever materialised anything into it. bifrost hit it head-on: `java`, `mvn`,
# `docker` all command-not-found on a Java repo, so every session began by
# bootstrapping the world. Same shape as #1076 (bootstrap never invoked), #1061
# (inert R-14) and #1056 (trivy parsing zero manifests) — the manifest promises
# it, the runtime does not have it, and nothing says so.
#
# The image bakes `mise` (the INSTALLER) and never a toolchain: a baked JDK would
# ride along in every agent that never touches Java, and bumping Maven would
# become a kit release. R-11 exists precisely to avoid that.
#
# Two manifest sources, both honoured, because they answer different questions:
#
#   operator-level  $TOOLBOX/mise.toml     "every agent on this profile needs X"
#   per-repo        <workspace>/mise.toml  "this project needs Java 17 + Maven"
#
# The per-repo case needs nothing from us at boot — mise's shims resolve the
# version from the cwd's config at exec time, which is why shims are on the
# image PATH rather than a toolchain being pinned into it.
#
# NEVER FATAL. The wrapper sources this and then execs the agent, so a fatal here
# means no agent at all: a container with no Maven is bad, a container with no
# agent is worse. Offline, unreadable manifest, mise itself missing — all warn.
sync_toolbox() {
	local toolbox="${OAW_TOOLBOX_DIR:-$OAW_HOME/.oaw/toolbox}"

	if [[ ! -d "$toolbox" ]]; then
		warn "missing mount: toolbox dir not present ($toolbox); declared toolchains cannot be materialised"
		return 0
	fi

	# A manifest is OPTIONAL and its absence is the common case — most agents
	# never touch a toolchain. info, not warn: a warning that fires on every
	# healthy boot is how a fleet learns to stop reading warnings.
	local manifest=""
	local candidate
	for candidate in "$toolbox/mise.toml" "$toolbox/.mise.toml" "$toolbox/config.toml"; do
		[[ -f "$candidate" ]] && {
			manifest="$candidate"
			break
		}
	done
	if [[ -z "$manifest" ]]; then
		info "toolbox: no manifest in $toolbox — per-repo mise.toml still resolves via shims"
		return 0
	fi

	if ! command -v mise >/dev/null 2>&1; then
		warn "toolbox: $manifest declares toolchains but mise is not installed — expected baked in the image"
		return 0
	fi

	# `mise install` is idempotent: a satisfied manifest is a fast no-op, which
	# matters because this runs on EVERY agent start, not once per container.
	# `if ! out=$(...)` — NOT `out=$(...); rc=$?`. This file runs under `set -e`,
	# where a failing command substitution in an assignment aborts the script
	# immediately and the `rc=$?` line never executes. The offline path would then
	# have killed the boot, which is the precise thing the comment above forbids:
	# a container with no agent is worse than one with no Maven. Caught by
	# test_offline_install_warns_but_the_agent_still_starts, not by reading it.
	# EXPORT, so the agent and every hook inherit it. The wrapper SOURCES this
	# script and then execs the agent, so an export here flows down — the same
	# mechanism CLAUDE_CODE_OAUTH_TOKEN relies on. Without it the shims resolve on
	# PATH and then fail with "No version is set for shim", because nothing tells
	# mise which manifest is the global one. Measured in a live container.
	export MISE_GLOBAL_CONFIG_FILE="$manifest"

	local out rc=0
	if ! out="$(mise install --yes 2>&1)"; then
		rc=1
	fi
	if ((rc != 0)); then
		# Offline is the expected non-fatal failure. Report what mise said rather
		# than guessing which of network / bad manifest / disk it was — this
		# script's job is to name the condition, not to diagnose it.
		warn "toolbox: mise install failed (rc=$rc) — the agent still starts, toolchains may be missing"
		while IFS= read -r line; do
			[[ -n "$line" ]] && warn "  mise: $line"
		done <<<"$(printf '%s' "$out" | tail -5)"
		return 0
	fi

	# Regenerate shims, or a freshly-installed tool has no entry on PATH and the
	# install "succeeded" while `mvn` is still command-not-found — a pass that
	# leaves the reported problem exactly where it was.
	mise reshim >/dev/null 2>&1 ||
		warn "toolbox: mise reshim failed — installed tools may not be on PATH"

	info "toolbox: materialised from $manifest"
	return 0
}

# --- Stage 4: secret sourcing + required-secret validation (R-12/R-14) --------

validate_secrets() {
	local dir="$OAW_SECRETS_DIR"

	if [[ -d "$dir" ]]; then
		if [[ -f "$dir/.env" ]]; then
			# Env modality: source .env so env-var consumers see the values.
			# Loose files stay path-modality — NEVER auto-exported (D6).
			#
			# DRY-RUN FIRST, in a SEPARATE bash process. Sourcing runs arbitrary
			# shell in THIS process under `set -e`, so one bad line kills bootstrap
			# outright — and because bootstrap is the agent's exec wrapper, "kills
			# bootstrap" means "the agent never starts". The observed failure was an
			# unquoted list value: `OAW_REQUIRED_SECRETS=a b` is not two items, it is
			# `a` prefixed to a command named `b`, so the boot died on
			# `line 42: discord-bot-token: command not found` with exit 127 and no
			# [bootstrap] prefix to say who had failed or why.
			#
			# THE PROBE MUST NOT BE A COMMAND SUBSTITUTION SUBSHELL. bash STRIPS
			# `errexit` inside $( ) unless `inherit_errexit` is set, so `$( ( set -a;
			# . file ) )` keeps sourcing past the first failure and yields the status
			# of the LAST line. The first cut of this guard did exactly that and was
			# INERT for the very template it ships — secrets-env.example ends with a
			# good `OAW_SECRET_ENV=` line, so a broken OAW_REQUIRED_SECRETS above it
			# probed "clean", the captured stderr was discarded unread, and the real
			# source below then killed the shell with 127. Verified by hand:
			#   probe: reported CLEAN
			#   captured-but-discarded: .env: line 2: beta: command not found
			#   real-source exit: 127
			# A fresh `bash -c` has its own live errexit, so it stops at the FIRST
			# failure — the same line the real source will die on.
			#
			# The probe cannot be `bash -n` — that is a SYNTAX check, and this is a
			# runtime error on a syntactically valid line. Only executing it finds it.
			local env_err env_rc
			env_err="$(bash -euo pipefail -c 'set -a; . "$1"' oaw-env-probe "$dir/.env" 2>&1 >/dev/null)" &&
				env_rc=0 || env_rc=$?
			if ((env_rc != 0)); then
				fatal "secrets: $dir/.env failed to execute (exit $env_rc) — refusing to boot the agent"
				warn "  ${env_err:-(no stderr)}"
				warn "  Most likely an UNQUOTED value containing a space. A sourced"
				warn "  \`VAR=one two\` runs the command \`two\`; write \`VAR=\"one two\"\`."
				warn "  Template: containers/oakandwave-workflow/secrets-env.example"
				return 0
			fi
			# Sourced cleanly but wrote to stderr: not fatal (the real source will
			# survive it too), but never discard the evidence — that is how the first
			# cut of this guard hid its own inertness.
			if [[ -n "$env_err" ]]; then
				warn "secrets: $dir/.env sourced cleanly but wrote to stderr: $env_err"
			fi
			set -a
			# shellcheck disable=SC1090,SC1091
			. "$dir/.env"
			set +a
			info "secrets: sourced $dir/.env (env modality)"
		else
			# MUST NOT be a silent skip (#1061). Since the whole-dir mount was
			# replaced by named file mounts, the `else` below is now unreachable —
			# a file bind FORCES $dir into existence — so this is the only place a
			# missing secrets provision can still be reported. It is also where
			# Docker's create-if-missing bites: a bind whose source is absent
			# appears as an empty DIRECTORY, which `-f` correctly rejects.
			if [[ -e "$dir/.env" ]]; then
				warn "secrets: $dir/.env exists but is not a regular file"
				warn "  Docker creates a DIRECTORY when a bind-mount source is missing on the host."
				warn "  Create ~/.secrets/.env on the HOST (see containers/oakandwave-workflow/secrets-env.example)."
			else
				warn "secrets: no $dir/.env — no pointers, no required-secret declaration"
				warn "  Consumers will fall back to defaults and may find no token at all."
				warn "  See containers/oakandwave-workflow/secrets-env.example."
			fi
		fi
	else
		warn "missing mount: secrets dir not present ($dir)"
	fi

	# Required-secrets list: the env override wins; else the values-free manifest.
	#
	# R-14 IS INERT WHEN BOTH ARE ABSENT (#1061). Before this guard, neither source
	# being present left `required` empty, the validation loop ran zero times, and
	# `validate_secrets` returned success — so the check designed to catch a missing
	# secret at boot reported a clean run while examining nothing. That is the same
	# empty-denominator failure as a scanner that parses zero manifests: a pass over
	# nothing is indistinguishable from a pass over everything.
	#
	# Declaring "this container needs no secrets" is legitimate (the throwaway-CI
	# ring builds without a secrets mount at all), so this WARNS rather than aborts.
	# Set OAW_REQUIRED_SECRETS="" to declare it deliberately and silence the warning.
	# Branch on SET-ness, not emptiness, so the documented precedence actually
	# holds: `OAW_REQUIRED_SECRETS=""` means "deliberately none" and must beat a
	# manifest, rather than falling through to it. `${VAR+set}` expands only when
	# VAR is set (empty included) and is `set -u`-safe.
	local -a required=()
	if [[ -n "${OAW_REQUIRED_SECRETS+set}" ]]; then
		if [[ -n "$OAW_REQUIRED_SECRETS" ]]; then
			IFS=' ' read -r -a required <<<"$OAW_REQUIRED_SECRETS"
		else
			info "secrets: no required secrets declared (OAW_REQUIRED_SECRETS is empty)"
		fi
	elif [[ ! -f "$OAW_REQUIRED_SECRETS_MANIFEST" ]]; then
		warn "secrets: R-14 check is INERT — no \$OAW_REQUIRED_SECRETS and no manifest at $OAW_REQUIRED_SECRETS_MANIFEST"
		warn "  Nothing was validated. A missing token will NOT fail this boot; it will"
		warn "  surface later as an agent that polls normally and delivers nothing."
		warn "  Declare the required set in ~/.secrets/.env (OAW_REQUIRED_SECRETS=...),"
		warn "  or set it to \"\" if none are needed. See secrets-env.example."
	else
		local line
		while IFS= read -r line || [[ -n "$line" ]]; do
			line="${line%%#*}"         # strip comment
			line="$(xargs <<<"$line")" # trim whitespace
			[[ -n "$line" ]] && required+=("$line")
		done <"$OAW_REQUIRED_SECRETS_MANIFEST"
	fi

	# --- secret -> env projection (OAW_SECRET_ENV) ------------------------------
	# Declarative, not hardcoded: `.env` names the pairs, so adding a future
	# env-consuming secret needs no bootstrap change. Format is a space-separated
	# list of ENVVAR=secret-file-name, e.g.
	#     OAW_SECRET_ENV="CLAUDE_CODE_OAUTH_TOKEN=claude-code-oauth-token"
	#
	# This is the deliberate exception to #1061's pointers-not-values rule. That
	# rule exists because env inherits into every child process, which matters for a
	# credential granting access to a system the agent's children have no business
	# touching (the Discord bot token). An agent's OWN auth token is different: a
	# child that steals it gains precisely what the agent already has. Do NOT use
	# this to project third-party credentials.
	local pair envname secname
	for pair in ${OAW_SECRET_ENV:-}; do
		envname="${pair%%=*}"
		secname="${pair#*=}"
		if [[ -z "$envname" || -z "$secname" || "$envname" == "$pair" ]]; then
			warn "secrets: malformed OAW_SECRET_ENV entry '$pair' (want ENVVAR=secret-name)"
			continue
		fi
		# DENY-LIST, enforced here rather than asserted in a comment. The rule
		# "never project this credential into the environment" is only real if the
		# projection loop refuses it — otherwise one OAW_SECRET_ENV line hands an
		# org-admin PAT to every child process (#1082).
		case "$secname" in
		github-pat)
			warn "secrets: refusing to project '$secname' into \$$envname — file modality only (#1082)"
			continue
			;;
		esac
		if [[ -f "$dir/$secname" ]]; then
			export "$envname=$(tr -d '\r\n' <"$dir/$secname")"
			info "secrets: projected '$secname' -> \$$envname"
		else
			# Loud: an agent with no credential does not fail fast — it boots and
			# halts on an interactive login menu forever, which is indistinguishable
			# from an idle agent (#1076).
			fatal "OAW_SECRET_ENV wants '$secname' for \$$envname, but $dir/$secname is absent"
		fi
	done

	# Secret names are FILENAMES, not shell identifiers. `${!name}` on a name
	# containing a hyphen is not a lookup that returns empty — bash rejects it
	# outright ("github-pat: invalid variable name") and, under `set -e`, kills the
	# shell AT THAT LINE: before the fatal, before the accumulate-all-fatals list,
	# before the summary. Under the sourcing wrapper that means no agent at all,
	# with only a bare bash error to explain it. Latent since #1061 because every
	# declared secret happened to be present; adding a NEW required secret to a
	# host that lacks the file is what walks straight into it.
	local name envname
	for name in "${required[@]:-}"; do
		[[ -n "$name" ]] || continue
		envname="${name//[^A-Za-z0-9_]/_}"
		if [[ -f "$dir/$name" ]]; then
			info "secrets: '$name' present (path modality)"
		elif [[ -n "${!envname:-}" ]]; then
			info "secrets: '$name' present (env modality as \$$envname)"
		else
			fatal "required secret missing: '$name' (expected file $dir/$name or env \$$name)"
		fi
	done
	return 0
}

# --- Stored credential vs mounted token (#1085) -------------------------------
#
# Claude Code PREFERS a stored $CLAUDE_CONFIG_DIR/.credentials.json over
# CLAUDE_CODE_OAUTH_TOKEN. Under aoe that store is the operator's shared sandbox
# credential — which is exactly what they want (one login serves every agent, so a
# rate-limit rotation costs one login instead of one per agent) — but it goes
# stale, and when it does the agent reports:
#
#   API Error: 401 OAuth access token has been revoked.
#
# That message names the wrong credential. Observed in production against a
# mounted token that returned HTTP 200 at that very moment; the actual culprit was
# a .credentials.json ten days old. The operator has no way to tell those apart.
#
# We do NOT delete or override it — that would break the shared-login workflow.
# We make it VISIBLE, so "revoked" has a file next to it.
report_stored_credential() {
	local cred="$OAW_CLAUDE_CONFIG_DIR/.credentials.json"
	local have_token=0
	[[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]] && have_token=1

	if [[ -f "$cred" ]]; then
		local age="unknown"
		if command -v stat >/dev/null 2>&1; then
			age="$(stat -c %y "$cred" 2>/dev/null | cut -d. -f1)"
		fi
		info "auth: stored credential present ($cred, modified $age)"
		info "  This OUTRANKS \$CLAUDE_CODE_OAUTH_TOKEN. If the agent reports 401"
		info "  'token has been revoked', suspect THIS FILE before the mounted token —"
		info "  it is shared across containers and goes stale independently (#1085)."
	elif ((have_token)); then
		info "auth: no stored credential — the mounted token will be used"
	else
		warn "auth: no stored credential AND no \$CLAUDE_CODE_OAUTH_TOKEN — the agent will prompt to log in"
	fi
}

# --- SSH parity with a host session (#1089) -----------------------------------
#
# aoe mounts the operator's ~/.ssh to /root/.ssh — keys, and a config mapping
# hosts to identities. Agents use these constantly: git over SSH for both forges,
# and troubleshooting remote installs (blueshift-prod, perkollate-*, agent-smith-ca).
#
# THEY WERE MOUNTED AND INVISIBLE. The agent runs as `ubuntu` with HOME=/home/ubuntu,
# so ssh looks in /home/ubuntu/.ssh, finds nothing, falls back to default identity
# names, and fails `Permission denied (publickey)`. Before #1085 made /root
# traversable it could not have worked at all.
#
# An earlier draft of this file recorded "the container has no ~/.ssh
# (deliberately — mounting host private keys is a larger exposure than a scoped
# PAT)". That was WRONG: it inferred design intent from a permissions bug. The
# keys are provided ON PURPOSE. The goal here is not a reduced-privilege
# container — it is doing exactly what a host session does, so agents keep working
# while the kit is in flux.
#
# One symlink restores it. Measured after: ssh reads the config, offers the mapped
# key, `Welcome to GitLab, @brbaker-alog!`, and `git ls-remote git@…` succeeds for
# BOTH forges. No URL rewriting, no credential helper, no token in git — the host
# uses SSH for git, so the container does too.
ensure_ssh_parity() {
	local src="${OAW_SSH_SOURCE:-/root/.ssh}" dst="$OAW_HOME/.ssh"

	[[ -d "$src" ]] || {
		# WARN, not info: this file's header codifies "missing mount -> WARN". As info,
		# WARN_COUNT stayed 0 and the summary reported a clean boot for a container with
		# no git-over-SSH and no reachable remote hosts.
		warn "missing mount: no $src — git over SSH and remote hosts (blueshift, perkollate) unavailable"
		return 0
	}
	# Already correct?
	if [[ -L "$dst" && "$(readlink -f "$dst" 2>/dev/null)" == "$(readlink -f "$src" 2>/dev/null)" ]]; then
		info "ssh: ~/.ssh already resolves to $src"
		return 0
	fi
	# A REAL dir here is not necessarily the operator's — ssh silently creates one
	# the first time it writes known_hosts, and then `ln -s` lands INSIDE it rather
	# than replacing it (which is exactly how the first attempt at this failed).
	# Only clear it when it holds nothing but ssh's own scratch.
	if [[ -L "$dst" ]]; then
		warn "ssh: $dst is a symlink to $(readlink "$dst" 2>/dev/null) — replacing it with $src"
	fi
	if [[ -e "$dst" && ! -L "$dst" ]]; then
		local stray
		# `|| true`: under set -e a find failure would abort bootstrap — and the
		# wrapper SOURCES this, so that means no agent at all.
		stray="$(find "$dst" -mindepth 1 -maxdepth 1 ! -name known_hosts ! -name 'known_hosts.old' -print -quit 2>/dev/null || true)"
		if [[ -n "$stray" ]]; then
			warn "ssh: $dst exists with real content ($stray) — leaving it alone; mounted keys at $src are NOT in use"
			return 0
		fi
		rm -rf "$dst" || {
			warn "ssh: could not clear $dst — mounted keys at $src are NOT in use"
			return 0
		}
	fi
	if ln -sfn "$src" "$dst" 2>/dev/null; then
		info "ssh: linked ~/.ssh -> $src (keys + host config now visible to the agent)"
	else
		warn "ssh: could not link ~/.ssh -> $src; git over SSH and remote hosts will fail"
	fi
}

# --- GitLab API credential (#1089) --------------------------------------------
#
# glab needs its own config; git does NOT (SSH covers git, see ensure_ssh_parity).
# Token choice: every valid gitlab.com token on the host carries effectively the
# same broad scopes, so there is no least-privilege pick — gitlab-cli-pat is named
# for this use. Override with OAW_GITLAB_SECRET.
ensure_gitlab_auth() {
	local secret="$OAW_SECRETS_DIR/${OAW_GITLAB_SECRET:-gitlab-cli-pat}"
	local cfg_dir="${GLAB_CONFIG_DIR:-$OAW_HOME/.config/glab-cli}"
	local cfg="$cfg_dir/config.yml"

	[[ -f "$secret" ]] || {
		warn "gitlab: no $secret — glab UNAUTHENTICATED (no MR/CI API work)"
		return 0
	}
	local token
	token="$(tr -d '\r\n' <"$secret")"
	[[ -n "$token" ]] || {
		warn "gitlab: $secret is empty — glab UNAUTHENTICATED"
		return 0
	}
	# [A-Za-z0-9._-]: real glpat- tokens contain DOTS. Omitting `.` rejected the
	# operator's actual token while a dot-free fixture passed — a fixture that
	# could not fail. The guard's job is refusing shell/YAML syntax, which it still does.
	if [[ ! "$token" =~ ^[A-Za-z0-9._-]+$ ]]; then
		warn "gitlab: $secret does not look like a bare token (shell/YAML syntax in the file?) — refusing to write"
		return 0
	fi
	if [[ -s "$cfg" ]] && grep -qE '^[[:space:]]+token:[[:space:]]*[^[:space:]]' "$cfg" 2>/dev/null; then
		info "gitlab: $cfg already carries a token — left alone"
		return 0
	fi
	mkdir -p "$cfg_dir"
	rm -f "$cfg"
	local old_umask
	old_umask="$(umask)"
	umask 077
	{
		echo "git_protocol: ssh"
		echo "host: gitlab.com"
		echo "hosts:"
		echo "    gitlab.com:"
		echo "        api_protocol: https"
		echo "        api_host: gitlab.com"
		echo "        token: $token"
	} >"$cfg"
	umask "$old_umask"
	chmod 600 "$cfg"
	info "gitlab: wrote $cfg (mode 600; git_protocol ssh, matching the host)"
}

# --- Kit registrations into the CLI's own config (#1085) ----------------------
#
# `./install` registers the kit's five MCP servers at BUILD time, into the image's
# $HOME/.claude.json. Under aoe the CLI reads $CLAUDE_CONFIG_DIR/.claude.json
# instead, which is aoe's mounted host config — so a production container had
# `mcpServers: []` and not one kit MCP available, while the image's own copy sat
# there fully populated and unread.
#
# ADDITIVE, never clobbering: the CLI's config is SHARED across every container
# (that is deliberate — one login serves the whole fleet, which matters because a
# rate-limit rotation otherwise costs one interactive login per agent), so it also
# carries the operator's own servers. We add what is missing and touch nothing else.
sync_kit_registrations() {
	# Same file: `./install` already wrote there, nothing to do.
	if [[ "$OAW_CLAUDE_CONFIG_FILE" == "$OAW_IMAGE_CONFIG_FILE" ]]; then
		info "mcp: CLI config is the image config — registrations already in place"
		return 0
	fi
	if [[ ! -f "$OAW_IMAGE_CONFIG_FILE" ]]; then
		warn "mcp: no image config at $OAW_IMAGE_CONFIG_FILE — cannot source kit registrations"
		return 0
	fi
	# CREATE it rather than bail. Warning-and-returning here reproduces the exact
	# production state: the CLI then makes the file itself, empty — zero MCP
	# servers, wizard, trust prompt. A fresh host or a new aoe profile hits this,
	# because .claude.json conventionally lives at $HOME root, so a config dir
	# seeded from ~/.claude will not contain one.
	if [[ ! -f "$OAW_CLAUDE_CONFIG_FILE" ]]; then
		if mkdir -p "$OAW_CLAUDE_CONFIG_DIR" 2>/dev/null && printf '{}\n' >"$OAW_CLAUDE_CONFIG_FILE" 2>/dev/null; then
			info "mcp: created empty CLI config at $OAW_CLAUDE_CONFIG_FILE"
		else
			warn "mcp: CLI config $OAW_CLAUDE_CONFIG_FILE absent and not creatable — kit MCP servers will be unavailable"
			return 0
		fi
	fi
	command -v python3 >/dev/null 2>&1 || {
		warn "mcp: python3 unavailable — cannot merge kit registrations"
		return 0
	}

	local out
	if ! out="$(
		OAW_SRC="$OAW_IMAGE_CONFIG_FILE" OAW_DST="$OAW_CLAUDE_CONFIG_FILE" python3 - <<-'PY' 2>&1
			import fcntl, json, os

			src, dst = os.environ["OAW_SRC"], os.environ["OAW_DST"]
			with open(src) as fh:
			    want = json.load(fh).get("mcpServers", {})
			if not want:
			    print("no-kit-servers")
			    raise SystemExit(0)

			# Locked read-modify-write: this file is shared by every container on the
			# host, so two agents starting together WILL interleave here.
			with open(dst, "r+") as fh:
			    fcntl.flock(fh, fcntl.LOCK_EX)
			    d = json.load(fh)
			    d_before = json.loads(json.dumps(d))  # pre-image for the recovery copy
			    have = d.setdefault("mcpServers", {})
			    added = [k for k in want if k not in have]
			    for k in added:
			        have[k] = want[k]
			    if added:
			        # RECOVERY COPY before mutating. Review suggested tmp+os.replace for
			        # crash-atomicity; rejected on a fact it did not have: aoe mounts this
			        # file TWICE — via the directory bind (/root/.claude) AND as a file
			        # bind (/root/.claude.json). A rename mints a new inode, so the
			        # file-bind path would keep resolving to the OLD one and the two views
			        # would silently diverge. In-place keeps them one file.
			        # Residual risk is a torn write (kill/ENOSPC between write and
			        # truncate) leaving invalid JSON in a config shared by EVERY container,
			        # so leave a recoverable copy first.
			        try:
			            with open(dst + ".pre-bootstrap", "w") as bak:
			                bak.write(json.dumps(d_before, indent=2))
			        except Exception:
			            pass
			        data = json.dumps(d, indent=2)
			        fh.seek(0)
			        fh.write(data)
			        fh.truncate()
			print(",".join(added) if added else "already-present")
		PY
	)"; then
		warn "mcp: could not merge kit registrations into $OAW_CLAUDE_CONFIG_FILE ($out)"
		return 0
	fi
	case "$out" in
	already-present) info "mcp: kit registrations already present in $OAW_CLAUDE_CONFIG_FILE" ;;
	no-kit-servers) warn "mcp: image config declares no MCP servers — nothing to merge" ;;
	*) info "mcp: registered into the CLI's config: $out" ;;
	esac
}

# --- Hook paths must resolve INSIDE the container (#1085) ---------------------
#
# The CLI reads $CLAUDE_CONFIG_DIR/settings.json — under aoe that is the
# OPERATOR'S HOST settings, carrying host absolute paths. Observed in production:
#
#   PostToolUse:Bash hook error
#   /bin/sh: 1: /home/bakerb/.local/share/wtf-server/hooks/wtf-post-tool-use.sh: not found
#
# `/home/bakerb` does not exist in the container. This is a CATEGORY error, not a
# preference conflict: a host path cannot resolve in a different filesystem
# namespace. The image's baked settings had the correct /home/ubuntu path all along
# and were simply not the file being read.
#
# We do NOT blanket-rewrite $HOME prefixes. Measured on the operator's host, only
# 1 of 4 host paths was a hook; the rest were workspace references that do not map
# (containers mount workspaces at /workspace/<name>), so rewriting them would
# manufacture plausible-looking paths that do not exist — worse than leaving them
# visibly wrong.
#
# Instead: VERIFY. Every configured hook command that names an absolute path must
# resolve here, and any that does not is reported AT BOOT rather than at first tool
# use. wtf failed loudly only because its target was absent; a hook whose path
# exists in both namespaces would run the wrong thing silently.
validate_hook_paths() {
	[[ -f "$OAW_EFFECTIVE_SETTINGS" ]] || return 0
	command -v python3 >/dev/null 2>&1 || return 0

	local out
	out="$(
		OAW_SETTINGS="$OAW_EFFECTIVE_SETTINGS" python3 - <<-'PY' 2>&1 || true
			import json, os, re

			p = os.environ["OAW_SETTINGS"]
			try:
			    with open(p) as fh:
			        d = json.load(fh)
			except Exception as exc:
			    print(f"__ERR__ {exc}")
			    raise SystemExit(0)

			# Absolute paths appearing in hook commands. Anything relative resolves via
			# PATH and is not ours to judge.
			bad = []
			# EXPAND, do not skip. The first cut used a lookbehind to drop anything
			# preceded by $ or ~ — which killed 13 phantom paths (matching the slash
			# AFTER $HOME) but also made every tilde/$HOME hook unjudgeable. That is not
			# a corner case: every hook in config/settings.template.json is ~/-prefixed,
			# including ~/.local/share/wtf-server/hooks/wtf-post-tool-use.sh, which the
			# image build WHITELISTS as deliberately absent. So the validator would have
			# gone silent on the exact failure that motivated it.
			#
			# Expanding gets both: $HOME/x.sh resolves to a real path (no phantom), and a
			# ~/-prefixed hook that is genuinely missing is still reported.
			#
			# Scan `command` VALUES only — scanning the whole JSON blob also reads
			# `_comment` fields, where a path mentioned in prose becomes a phantom.
			cmds = []

			def collect(node):
			    if isinstance(node, dict):
			        for k, v in node.items():
			            if k == "command" and isinstance(v, str):
			                cmds.append(v)
			            else:
			                collect(v)
			    elif isinstance(node, list):
			        for i in node:
			            collect(i)

			collect(d.get("hooks", {}))

			bad = []
			for cmd in cmds:
			    m = re.match(r"\s*([~$]?[\w{}/.\-]*/[^\s;|&]+)", cmd)
			    if not m:
			        continue
			    cand = os.path.expanduser(os.path.expandvars(m.group(1)))
			    if not cand.startswith("/"):
			        continue
			    if not os.path.exists(cand):
			        bad.append(cand)
			print("\n".join(sorted(set(bad))))
		PY
	)"
	[[ -z "$out" ]] && return 0
	if [[ "$out" == __ERR__* ]]; then
		warn "hooks: could not parse $OAW_EFFECTIVE_SETTINGS (${out#__ERR__ })"
		return 0
	fi
	local line
	while IFS= read -r line; do
		[[ -n "$line" ]] || continue
		warn "hooks: configured hook does not exist in this container: $line"
	done <<<"$out"
	warn "  These come from \$CLAUDE_CONFIG_DIR/settings.json, which under aoe is the"
	warn "  HOST's settings — host absolute paths cannot resolve here (#1085). The hook"
	warn "  will fail at first use; fixing the path at the source is the durable answer."
}

# --- GitHub credential (#1082) ------------------------------------------------
#
# Without this a containerised agent reaches a prompt, authenticates to Anthropic,
# and then cannot push, open a PR, merge, or run /scpmmr — it can think but not
# land work, which is the whole job.
#
# FILE MODALITY, NOT ENV — this is the point of the function. The host
# authenticates gh via GH_TOKEN and copying that would be one line, but an
# environment variable is inherited by EVERY child process, and the only working
# GitHub credential here carries admin:enterprise, admin:org, delete_repo,
# delete:packages. The CLAUDE_CODE_OAUTH_TOKEN exception was argued narrowly: that
# token IS the agent's own identity, so a child that steals it gains nothing the
# agent does not already have. An org-admin PAT does not meet that bar. Writing
# gh's own credential file means only gh reads it.
#
# Warn, never fatal: an agent with no GitHub access is still useful for local
# work, and the wrapper SOURCES this script, so a fatal here means no agent at all.
ensure_github_auth() {
	local secret="$OAW_SECRETS_DIR/github-pat"
	local cfg_dir="$OAW_HOME/.config/gh"
	local hosts="$cfg_dir/hosts.yml"

	if [[ ! -f "$secret" ]]; then
		warn "github: no $secret — gh will be UNAUTHENTICATED (no push, no PR, no merge)"
		return 0
	fi

	# Never clobber a credential the operator put there deliberately — but scope
	# the check to github.com. A bare `grep oauth_token` matches a commented line
	# or a token for a DIFFERENT host, and would then log "left alone" while
	# leaving github.com unauthenticated: the #1082 failure wearing a success
	# message, which is the shape this whole file is written against.
	# Host-SCOPED, and deliberately not `gh auth token --hostname github.com`:
	# that command performs a config migration which makes a NETWORK call and
	# returns non-zero on a merely-expired token (measured: "failed to migrate
	# config … 401 Bad credentials"). Using it would clobber an operator's
	# credential precisely when it is stale — worse than the host-blind grep it
	# was meant to replace. This awk scan is offline and answers exactly the
	# question asked: is there an oauth_token under the github.com block?
	if [[ -s "$hosts" ]] && awk '
		/^[^[:space:]#]/ { host = $0; sub(/:.*/, "", host) }
		/^[[:space:]]+oauth_token:/ { if (host == "github.com") found = 1 }
		END { exit(found ? 0 : 1) }
	' "$hosts" 2>/dev/null; then
		info "github: $hosts already carries a github.com token — left alone"
		return 0
	fi

	local token
	token="$(tr -d '\r\n' <"$secret")"
	if [[ -z "$token" ]]; then
		warn "github: $secret is empty — gh will be UNAUTHENTICATED"
		return 0
	fi
	# Shape guard. A secret file written as `GH_TOKEN=ghp_x` or `export GH_TOKEN=…`
	# is a very common shape, and interpolating it produces VALID YAML carrying a
	# garbage token — so the failure surfaces later as a puzzling 401 instead of
	# here, where the cause is obvious.
	if [[ ! "$token" =~ ^[A-Za-z0-9_]+$ ]]; then
		warn "github: $secret does not look like a bare PAT (shell/YAML syntax in the file?) — refusing to write"
		return 0
	fi

	mkdir -p "$cfg_dir"
	# Remove first so `umask 077` actually governs creation. Truncating an existing
	# file PRESERVES its mode, so a pre-existing 0644 hosts.yml would receive the
	# token world-readable for the instant before chmod — the very window the
	# umask is here to close.
	rm -f "$hosts"
	# umask before create: the token must never exist world-readable, not even for
	# the instant between creation and chmod.
	local old_umask
	old_umask="$(umask)"
	umask 077
	{
		echo "github.com:"
		echo "    oauth_token: '$token'"
		echo "    git_protocol: ${OAW_GH_PROTOCOL:-ssh}"
	} >"$hosts"
	umask "$old_umask"
	chmod 600 "$hosts"
	info "github: wrote $hosts (mode 600, file modality — NOT exported to env)"

	# RESTORED after being wrongly removed (#1089). The host's own ~/.gitconfig has
	# exactly this, verified:
	#
	#   url.https://github.com/.insteadof      git@github.com:
	#   credential.https://github.com.helper   !gh auth git-credential
	#
	# so HTTPS+PAT *is* what a host session uses for github git — #1082 was right.
	# An earlier draft removed it on the premise "the host uses SSH for git". That is
	# true for GITLAB (the host has no gitlab rewrite) and FALSE for github; it was
	# generalised from one forge to both. Removing it made the container authenticate
	# github git as the SSH key identity while the host uses the PAT identity — a
	# different credential, audit trail and permission set. Under the parity
	# principle that is a regression, not a simplification.
	if command -v git >/dev/null 2>&1; then
		git config --global --replace-all \
			"credential.https://github.com.helper" '!gh auth git-credential' || true
		git config --global --replace-all \
			"url.https://github.com/.insteadOf" "git@github.com:" || true
		info "github: git configured HTTPS+PAT for github.com (matching the host's ~/.gitconfig)"
	fi

}

# --- Onboarding state (#1079) -------------------------------------------------
#
# WHY THIS RUNS AT BOOT RATHER THAN BEING BAKED. A fresh container reaches an
# agent that is authenticated but still parked on the first-run wizard, which for
# an unattended agent is the same outcome as no agent at all. Two keys clear it,
# derived empirically against the real image rather than guessed (each config was
# run repeatedly, because single runs proved non-deterministic):
#
#   hasCompletedOnboarding + trust(cwd)  -> reaches the prompt   (3/3)
#   hasCompletedOnboarding alone         -> trust dialog         (2/2)
#   theme + trust, no hasCompletedOnboarding -> theme picker
#
# Two findings shaped this, and both contradict the obvious guess:
#   * `theme` is NOT required — hasCompletedOnboarding covers the theme step.
#     Neither is `lastOnboardingVersion`, which is fortunate: baking a version
#     string would drift on every base-image CLI bump.
#   * trust is PER-PROJECT and path-sensitive. Trust recorded for /home/ubuntu
#     while the agent runs in /workspace still shows the dialog, so this cannot
#     be baked into the image — the sandbox path varies per session.
#
# `$PWD` is the right key precisely because the wrapper SOURCES this script in
# the agent's own process, so our cwd is the agent's cwd.
#
# `--dangerously-skip-permissions` does NOT bypass the wizard (measured), so the
# agent's own flags cannot be relied on here.
ensure_onboarding_state() {
	local cfg="$OAW_CLAUDE_CONFIG_FILE"

	if [[ ! -f "$cfg" ]]; then
		warn "onboarding: no $cfg — the agent will run the first-run wizard and never reach a prompt"
		return 0
	fi
	if ! command -v python3 >/dev/null 2>&1; then
		warn "onboarding: python3 unavailable — cannot ensure onboarding state; expect the first-run wizard"
		return 0
	fi

	# Auto-trust is a real decision, not a formality: it declares the workspace
	# trusted without asking. It is correct HERE because the OPERATOR chose this
	# mount when launching the sandbox — that is the whole of the argument.
	#
	# It is NOT justified by the agent already running
	# --dangerously-skip-permissions, which an earlier version of this comment
	# claimed. Those gate different things: skip-permissions removes tool-use
	# approval, while folder trust governs whether the workspace's OWN
	# project-scoped config (.mcp.json, project hooks, project settings.json) is
	# loaded and executed. Auto-trust therefore ADDS unprompted execution of
	# repo-supplied config; it is not subsumed by a flag the agent already carries.
	# Same call either way for a mount the operator picked, but do not reason from
	# the flag.
	local trust=1
	[[ -n "${OAW_NO_AUTO_TRUST:-}" ]] && trust=0

	local out
	if ! out="$(
		OAW_CFG="$cfg" OAW_TRUST="$trust" python3 - <<-'PY' 2>&1
			import fcntl, json, os

			cfg, trust = os.environ["OAW_CFG"], os.environ["OAW_TRUST"] == "1"
			# getcwd(), not $PWD: bash keeps the LOGICAL cwd, so if any ancestor
			# exported a PWD traversing a symlink they disagree. Claude Code keys
			# `projects` off the process cwd, so a logical path would file the trust
			# entry under a key it never looks up — reproducing the very dialog this
			# clears. This process already has the agent's cwd.
			ws = os.getcwd()

			try:
			    # r+ and hold an exclusive lock across the whole read-modify-write.
			    # bootstrap runs on EVERY `claude` invocation (it is the agent's
			    # wrapper), so two can interleave — the same race that put -f on the
			    # skills ln above. Unlocked, the lost update IS the bug being fixed:
			    # A reads, B reads, A writes trust[a], B writes without it, and agent
			    # A then parks on the trust dialog forever.
			    with open(cfg, "r+") as fh:
			        fcntl.flock(fh, fcntl.LOCK_EX)
			        d = json.load(fh)

			        changed = []
			        if d.get("hasCompletedOnboarding") is not True:
			            d["hasCompletedOnboarding"] = True
			            changed.append("hasCompletedOnboarding")

			        if trust and ws:
			            entry = d.setdefault("projects", {}).setdefault(ws, {})
			            if entry.get("hasTrustDialogAccepted") is not True:
			                entry["hasTrustDialogAccepted"] = True
			                changed.append(f"trust[{ws}]")

			        if changed:
			            # Serialize FULLY before touching the file: `open(...,"w")`
			            # truncates at open and json.dump streams, leaving a
			            # transient zero-length window in which a container stop or
			            # ENOSPC destroys the baked mcpServers registrations.
			            data = json.dumps(d, indent=2)
			            fh.seek(0)
			            fh.write(data)
			            fh.truncate()
			except Exception as exc:
			    print(f"unusable: {exc}")
			    raise SystemExit(1)

			print(",".join(changed) if changed else "already-set")
		PY
	)"; then
		warn "onboarding: could not update $cfg ($out) — expect the first-run wizard"
		return 0
	fi

	if [[ "$out" == "already-set" ]]; then
		info "onboarding: state already present (no wizard)"
	else
		info "onboarding: set $out"
	fi
	((trust)) || info "onboarding: auto-trust disabled (OAW_NO_AUTO_TRUST) — the trust dialog WILL appear"
}

# --- Main ---------------------------------------------------------------------

main() {
	info "starting (home=$OAW_HOME)"
	validate_env
	sync_skills
	sync_kit_hooks
	sync_toolbox
	validate_secrets
	ensure_ssh_parity
	ensure_github_auth
	ensure_gitlab_auth
	sync_kit_registrations
	report_stored_credential
	ensure_onboarding_state
	validate_hook_paths

	# >&2 like every other line here. This was the ONE line on stdout, which was
	# harmless while bootstrap was a separate process — but the wrapper SOURCES it
	# and then execs the agent, so bootstrap's fd 1 IS the agent's fd 1. On stdout
	# it prepends a non-JSON line to every headless run:
	#   $ claude -p 'reply with exactly: AUTH_OK'
	#   bootstrap: 1 warning(s) (0 collision(s), 0 dangling), 0 fatal(s)
	#   AUTH_OK
	# which breaks `--output-format json`/`stream-json` and anything piped to jq.
	echo "bootstrap: ${WARN_COUNT} warning(s) (${COLLISION_COUNT} collision(s), ${DANGLING_COUNT} dangling), ${FATAL_COUNT} fatal(s)" >&2

	if [[ "$FATAL_COUNT" -gt 0 ]]; then
		echo "[bootstrap] FATAL: $FATAL_COUNT fatal condition(s) — refusing to hand off to the agent" >&2
		exit 1
	fi
	info "complete"
	return 0
}

main "$@"
