#!/usr/bin/env bash
#
# bootstrap.sh — the container bootstrap (Story 1.4, #964, Plan #959).
#
# Runs before the agent (via the aoe-hooks seam — open probe Dev Spec §5.N#5) and
# performs, in order: env validation, skills symlink-sync, settings.local merge,
# and secret sourcing + required-secret validation. It is the load-bearing
# instrument the whole container leans on (SKETCHBOOK D7), so it is written to the
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
#   OAW_SETTINGS_JSON               baked hook wiring (default: $HOME/.claude/settings.json)
#   OAW_SETTINGS_LOCAL              shared knobs mount
#                                   (default: $HOME/.claude/settings.local.json)
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
OAW_SETTINGS_LOCAL="${OAW_SETTINGS_LOCAL:-$OAW_HOME/.claude/settings.local.json}"
OAW_SECRETS_DIR="${OAW_SECRETS_DIR:-$OAW_HOME/.secrets}"
OAW_REQUIRED_SECRETS_MANIFEST="${OAW_REQUIRED_SECRETS_MANIFEST:-$OAW_SECRETS_DIR/required.manifest}"

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

# --- Stage 3: settings.local merge --------------------------------------------

# Claude Code itself merges settings.json (baked hook wiring) with the mounted
# settings.local.json (shared knobs) at runtime (architecture.md §3.3). The
# bootstrap's job is to make the two silent-skip paths loud: a missing
# settings.local mount, and a malformed settings.local that CC's merge would
# silently ignore.
merge_settings() {
	if [[ -f "$OAW_SETTINGS_JSON" ]]; then
		info "settings: image settings.json present"
	else
		warn "settings: image settings.json not found ($OAW_SETTINGS_JSON) — expected baked in the image"
	fi

	if [[ ! -f "$OAW_SETTINGS_LOCAL" ]]; then
		warn "missing mount: settings.local.json not present ($OAW_SETTINGS_LOCAL); Claude Code will use image settings only"
		return 0
	fi

	if python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$OAW_SETTINGS_LOCAL" 2>/dev/null; then
		info "settings: settings.local.json present and valid JSON (Claude Code merges it)"
	else
		warn "settings: settings.local.json is not valid JSON ($OAW_SETTINGS_LOCAL) — Claude Code's merge will ignore/error on it"
	fi
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
		echo "    git_protocol: ${OAW_GH_PROTOCOL:-https}"
	} >"$hosts"
	umask "$old_umask"
	chmod 600 "$hosts"
	info "github: wrote $hosts (mode 600, file modality — NOT exported to env)"

	# AUTHENTICATING gh IS NOT ENOUGH — git is a separate client.
	#
	# hosts.yml authenticates the `gh` CLI. `git push` does not read it, and
	# `gh pr create` shells out to `git push`, so without this the agent can call
	# the API and still not land a single commit. Measured in a container before
	# this block existed:
	#
	#   $ git push --dry-run origin HEAD
	#   Host key verification failed.
	#   fatal: Could not read from remote repository.
	#
	# Two things are needed, and only together:
	#   1. a credential helper, so HTTPS pushes use the token we just wrote;
	#   2. an SSH->HTTPS rewrite, because repos are cloned with `git@github.com:`
	#      origins and the container has no ~/.ssh (deliberately — mounting the
	#      host's private keys is a far larger exposure than a scoped PAT).
	#
	# Scoped to github.com so no other forge's remotes are rewritten. Written to
	# the container-local gitconfig, which dies with the container.
	if command -v gh >/dev/null 2>&1 && command -v git >/dev/null 2>&1; then
		git config --global --replace-all \
			"credential.https://github.com.helper" '!gh auth git-credential' || true
		git config --global --replace-all \
			"url.https://github.com/.insteadOf" "git@github.com:" || true
		info "github: git configured for HTTPS+token (ssh remotes rewritten; no keys needed)"
	else
		warn "github: gh or git missing — git push will NOT be authenticated"
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
	local cfg="$OAW_HOME/.claude.json"

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
	merge_settings
	validate_secrets
	ensure_github_auth
	ensure_onboarding_state

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
