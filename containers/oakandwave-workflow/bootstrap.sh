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
		ln -s "$entry" "$dest"
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

	local name
	for name in "${required[@]:-}"; do
		[[ -n "$name" ]] || continue
		if [[ -f "$dir/$name" ]]; then
			info "secrets: '$name' present (path modality)"
		elif [[ -n "${!name:-}" ]]; then
			info "secrets: '$name' present (env modality)"
		else
			fatal "required secret missing: '$name' (expected file $dir/$name or env \$$name)"
		fi
	done
	return 0
}

# --- Main ---------------------------------------------------------------------

main() {
	info "starting (home=$OAW_HOME)"
	validate_env
	sync_skills
	merge_settings
	validate_secrets

	echo "bootstrap: ${WARN_COUNT} warning(s) (${COLLISION_COUNT} collision(s), ${DANGLING_COUNT} dangling), ${FATAL_COUNT} fatal(s)"

	if [[ "$FATAL_COUNT" -gt 0 ]]; then
		echo "[bootstrap] FATAL: $FATAL_COUNT fatal condition(s) — refusing to hand off to the agent" >&2
		exit 1
	fi
	info "complete"
	return 0
}

main "$@"
