#!/usr/bin/env bash
# registry-prune.sh — prune accumulated GHCR versions WITHOUT deleting anything
# the fleet is running (#1100).
#
# THE TRAP THIS EXISTS TO AVOID. The standard GHCR cleanup recipe is "delete all
# untagged versions". Running it here would have deleted the image the live fleet
# was on:
#
#   profile dogfood → …/oakandwave-workflow@sha256:7e615dd0…
#   that digest in GHCR: tags=[]        ← UNTAGGED
#
# A profile pins a BARE DIGEST. Pinning by digest is correct — it is what makes a
# release immutable (R-05/R-23) — but it leaves no tag behind, so a pinned,
# actively-running image is indistinguishable from garbage to any tag-based
# retention rule. **Untagged does not mean unused.**
#
# And the failure is delayed and disconnected: nothing breaks at prune time. It
# breaks at the next container launch on that profile, with nothing linking the
# two events.
#
# So the keep-set is computed from what is ACTUALLY REFERENCED, not from tags:
#   1. every digest pinned by an aoe profile        (the fleet)
#   2. whatever :edge and any other NAMED tag point at
#   3. the cosign .sig / .att artifacts of everything in 1 and 2 — a signature
#      orphaned from its subject verifies nothing, and deleting the subject while
#      keeping the signature (or vice versa) is worse than deleting neither
#
# DRY RUN BY DEFAULT. Deleting published artifacts is irreversible and
# outward-facing; --apply is a separate, deliberate act.
#
# Usage:
#   registry-prune.sh                      # dry run: show keep vs delete
#   registry-prune.sh --apply              # actually delete (irreversible)
#   registry-prune.sh --profiles-root DIR  # override where pins are read from
#
# Exit: 0 ok; 2 refused (could not establish what to protect); 1 a delete failed.
set -uo pipefail

ORG="${OAW_REGISTRY_ORG:-Wave-Engineering}"
PACKAGE="${OAW_REGISTRY_PACKAGE:-oakandwave-workflow}"
PROFILES_ROOT="${AOE_PROFILE_ROOT:-$HOME/.config/agent-of-empires/profiles}"
APPLY=false
# A ROLLBACK WINDOW. Keeping only what is referenced right now is correct and not
# sufficient: it leaves no previous image to fall back to when the current one
# turns out bad, and the release images are not distinguishable from intermediate
# `:edge` pushes because the build only ever pushes `:edge` — no `:vX.Y.Z`, and
# `:stable` has never been created. Until releases carry registry tags, "the most
# recent N manifests" is the only honest anchor for history.
KEEP_RECENT="${OAW_REGISTRY_KEEP_RECENT:-5}"

while [[ $# -gt 0 ]]; do
	case "$1" in
	--apply)
		APPLY=true
		shift
		;;
	--keep-recent)
		KEEP_RECENT="${2:?--keep-recent needs a count}"
		shift 2
		;;
	--profiles-root)
		PROFILES_ROOT="${2:?--profiles-root needs a path}"
		shift 2
		;;
	--package)
		PACKAGE="${2:?--package needs a name}"
		shift 2
		;;
	--org)
		ORG="${2:?--org needs a name}"
		shift 2
		;;
	-h | --help)
		sed -n '2,30p' "$0"
		exit 0
		;;
	*)
		echo "registry-prune: unknown flag $1" >&2
		exit 2
		;;
	esac
done

command -v gh >/dev/null 2>&1 || {
	echo "registry-prune: gh not found" >&2
	exit 2
}

# --- 1. What is the fleet running? -------------------------------------------
# RED-FIRST. An empty pin list would make every protection below vacuous — the
# script would happily compute "nothing is in use" and propose deleting the lot.
# That is the single most dangerous state this can be in, so it refuses.
# Only pins that reference THIS package. A profile may legitimately pin a
# different image (a locally-built one, another package), and demanding those
# appear in this package's listing would be a false alarm.
mapfile -t PINS < <(
	grep -rhoE "default_image[^\"]*\"[^\"]*${PACKAGE}[^\"]*@sha256:[0-9a-f]{64}" \
		"$PROFILES_ROOT"/*/config.toml 2>/dev/null |
		grep -oE 'sha256:[0-9a-f]{64}' | sort -u
)
if ((${#PINS[@]} == 0)); then
	echo "registry-prune: NO profile pins found under $PROFILES_ROOT" >&2
	echo "registry-prune: refusing — an empty protect-list makes every check below" >&2
	echo "registry-prune: vacuous, and 'nothing is in use' is exactly the reading" >&2
	echo "registry-prune: that deletes a running fleet. Point --profiles-root at" >&2
	echo "registry-prune: the real profiles, or confirm the fleet is genuinely idle." >&2
	exit 2
fi

echo "==> fleet pins (must survive): ${#PINS[@]}"
printf '    %s\n' "${PINS[@]}"

# --- 2. What is in the registry? ---------------------------------------------
VERSIONS_JSON="$(mktemp)"
trap 'rm -f "$VERSIONS_JSON"' EXIT
if ! gh api --paginate "/orgs/$ORG/packages/container/$PACKAGE/versions" \
	--jq '.[] | {id, name, tags: (.metadata.container.tags // []), created: .created_at}' \
	>"$VERSIONS_JSON" 2>"$VERSIONS_JSON.err"; then
	echo "registry-prune: could not list versions for $ORG/$PACKAGE" >&2
	# Surface gh's own diagnostic: a 403 (missing read:packages), a 404 (wrong
	# org/package) and a rate limit are different problems and collapsing them
	# into one generic line sends people down the wrong path.
	sed 's/^/registry-prune:   /' "$VERSIONS_JSON.err" >&2
	echo "registry-prune: the token needs read:packages (and delete:packages for --apply)" >&2
	exit 2
fi
if [[ ! -s "$VERSIONS_JSON" ]]; then
	echo "registry-prune: the registry listing came back EMPTY — refusing rather than" >&2
	echo "registry-prune: concluding there is nothing to protect" >&2
	exit 2
fi

# COMPLETENESS. Every pin for this package must appear in the listing. If one
# does not, the listing is incomplete — truncated pagination, a permissions gap,
# the wrong package — and a partial listing is dangerous in a specific way:
# things whose protecting reference was not seen look unreferenced. A signature
# whose subject fell outside the page reads as an orphan and gets pruned.
#
# "I could not see it" and "it is not there" are different claims, and only one
# of them is safe to act on.
missing=0
for pin in "${PINS[@]}"; do
	if ! grep -qF "\"$pin\"" "$VERSIONS_JSON"; then
		echo "registry-prune: pinned digest $pin is NOT in the registry listing" >&2
		missing=$((missing + 1))
	fi
done
if ((missing)); then
	echo "registry-prune: refusing — $missing pin(s) unaccounted for means the listing is" >&2
	echo "registry-prune: incomplete, and a partial listing makes protected things look" >&2
	echo "registry-prune: like garbage. Re-run when the full listing is available." >&2
	exit 2
fi

# --- 3. Resolve index children ------------------------------------------------
# A pinned digest is usually an INDEX, not a leaf. buildx pushes an image index
# whose children are the per-arch manifest and a provenance attestation, and GHCR
# lists each child as its own package version — untagged, unpinned, and matching
# no cosign tag. Deleting a child of a live index makes the pinned image
# UNPULLABLE, and like every other failure in this area it surfaces at the next
# container launch rather than at prune time.
#
# Measured on the current pin: mediaType image.index.v1+json, 2 children. They
# survived the first cut of this script only because they happened to be recent
# enough to fall inside the rollback window — luck, not protection.
#
# If children cannot be resolved, this REFUSES. Not knowing whether a version is
# someone's child is not a licence to delete it.
command -v docker >/dev/null 2>&1 || {
	echo "registry-prune: docker not found — cannot resolve index children, refusing" >&2
	exit 2
}
echo "==> resolving manifests (to find index children)…"

# --- 4. Decide, and print the reasoning ---------------------------------------
PLAN="$(mktemp)"
trap 'rm -f "$VERSIONS_JSON" "$PLAN"' EXIT

OAW_PINS="$(printf '%s\n' "${PINS[@]}")" OAW_KEEP_RECENT="$KEEP_RECENT" \
OAW_IMAGE_REF="ghcr.io/${ORG,,}/${PACKAGE}" \
	python3 - "$VERSIONS_JSON" "$PLAN" <<'PY'
import json, os, subprocess, sys

versions = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
pins = {p.strip() for p in os.environ["OAW_PINS"].splitlines() if p.strip()}
keep_recent = int(os.environ.get("OAW_KEEP_RECENT", "5"))
ref = os.environ["OAW_IMAGE_REF"]

# cosign publishes its artifacts as TAGS on their own versions, named after the
# subject digest with ':' swapped for '-'. That is the only link back, so it is
# how a signature is matched to the thing it signs.
#
# ASSUMPTION, worth stating: this is cosign's tag scheme (default through v2.x).
# Under OCI 1.1 referrers mode, signatures are UNTAGGED manifests carrying a
# `subject` field instead — invisible to this matcher and pruned as garbage,
# silently unsigning a live image. Revisit if cosign is moved to that mode.
def subject_of(tags):
    for t in tags:
        if t.endswith((".sig", ".att")) and t.startswith("sha256-"):
            return "sha256:" + t[len("sha256-"):].rsplit(".", 1)[0]
    return None


_manifest_cache = {}


def children_of(digest):
    """Digests this one references, or None if it could not be resolved."""
    if digest in _manifest_cache:
        return _manifest_cache[digest]
    try:
        raw = subprocess.run(
            ["docker", "buildx", "imagetools", "inspect", "--raw", f"{ref}@{digest}"],
            capture_output=True, text=True, timeout=120,
        )
        if raw.returncode != 0:
            _manifest_cache[digest] = None
            return None
        doc = json.loads(raw.stdout)
    except Exception:
        _manifest_cache[digest] = None
        return None
    kids = [m["digest"] for m in (doc.get("manifests") or []) if m.get("digest")]
    _manifest_cache[digest] = kids
    return kids


by_digest = {v["name"]: v for v in versions}
cosign = {v["name"] for v in versions if subject_of(v["tags"])}

# Resolve every non-cosign version once. Expensive (one call each) but this runs
# rarely and by hand, and the alternative is guessing about parentage while
# holding a delete list.
all_children = set()
unresolved = set()
for v in versions:
    if v["name"] in cosign:
        continue
    kids = children_of(v["name"])
    if kids is None:
        unresolved.add(v["name"])
    else:
        all_children.update(kids)

keep, why = set(), {}


def protect(vid, reason):
    keep.add(vid)
    why.setdefault(vid, reason)


for v in versions:
    if v["name"] in pins:
        protect(v["id"], "pinned by an aoe profile")
    named = [t for t in v["tags"] if not (t.startswith("sha256-") and t.endswith((".sig", ".att")))]
    if named:
        protect(v["id"], f"tagged {','.join(named)}")

# Rollback window: the last N things a profile could actually pin. Cosign
# artifacts are excluded (not roll-back targets), and so are index CHILDREN — a
# child is not a release, and counting them silently shrinks the real window.
candidates = [
    v for v in versions
    if v["name"] not in cosign and v["name"] not in all_children
]
for v in sorted(candidates, key=lambda x: x["created"], reverse=True)[:keep_recent]:
    protect(v["id"], "within the rollback window")

# CLOSURE. Keep every descendant of a kept index, and every cosign artifact of
# anything kept — including artifacts of children. Iterate to a fixed point
# rather than snapshotting once: a signature can attach to a child, and a child
# can itself be an index.
changed = True
while changed:
    changed = False
    kept_digests = {v["name"] for v in versions if v["id"] in keep}
    for d in list(kept_digests):
        for kid in (children_of(d) or []):
            kv = by_digest.get(kid)
            if kv and kv["id"] not in keep:
                protect(kv["id"], f"child of a kept index ({d[:19]}…)")
                changed = True
    for v in versions:
        subj = subject_of(v["tags"])
        if subj and subj in kept_digests and v["id"] not in keep:
            protect(v["id"], f"cosign artifact for {subj[:19]}…")
            changed = True

# Anything we could not resolve is kept. "I could not tell" is not "safe to
# delete" — it may be a child of something live.
for v in versions:
    if v["name"] in unresolved and v["id"] not in keep:
        protect(v["id"], "UNRESOLVED — kept because parentage could not be established")

delete = [v for v in versions if v["id"] not in keep]

print(f"==> registry holds {len(versions)} versions "
      f"({len(cosign)} cosign artifacts, {len(all_children)} index children)")
print(f"==> KEEP {len(keep)}")
for v in sorted((v for v in versions if v["id"] in keep), key=lambda x: x["created"], reverse=True):
    print(f"    {v['name']}  {','.join(v['tags']) or '<untagged>'}  — {why[v['id']]}")

# PRINT THE PLAN, not just its size. A tool whose premise is "irreversible,
# verify what you are protecting" must let an operator answer "is digest X in the
# delete set?" — printing a count only made that impossible, and made every test
# that tried to assert on it vacuous.
print(f"==> DELETE {len(delete)}")
for v in sorted(delete, key=lambda x: x["created"], reverse=True):
    print(f"    {v['name']}  {','.join(v['tags']) or '<untagged>'}  {v['created']}")

with open(sys.argv[2], "w") as fh:
    for v in delete:
        fh.write(f"{v['id']}\t{v['name']}\t{','.join(v['tags'])}\n")

if not keep:
    print("registry-prune: keep-set is EMPTY — refusing", file=sys.stderr)
    raise SystemExit(2)
PY
rc=$?
((rc == 0)) || exit "$rc"

DELETE_COUNT="$(wc -l <"$PLAN")"

# --- 5. Apply, or explain how to ----------------------------------------------
if [[ "$APPLY" != true ]]; then
	echo
	echo "==> DRY RUN — nothing deleted."
	echo "    $DELETE_COUNT version(s) would be removed. Re-run with --apply to do it."
	echo "    Deleting published artifacts is irreversible; this is deliberately a"
	echo "    separate act from computing the plan."
	exit 0
fi

# A flag alone is a weak gate for an irreversible, outward-facing delete of this
# size — nothing above required a dry run first, so without this an operator can
# destroy every unprotected published artifact having never seen the list. The
# plan is printed above; make them type the count back.
if [[ -z "${OAW_REGISTRY_ASSUME_YES:-}" ]]; then
	echo
	echo "==> About to IRREVERSIBLY delete $DELETE_COUNT published version(s) from"
	echo "    ghcr.io/${ORG,,}/${PACKAGE}. The full plan is printed above."
	printf '    Type the number of versions to delete to confirm: '
	read -r confirm
	if [[ "$confirm" != "$DELETE_COUNT" ]]; then
		echo "registry-prune: got '$confirm', expected '$DELETE_COUNT' — aborting" >&2
		exit 2
	fi
fi

echo
echo "==> APPLYING: deleting $DELETE_COUNT version(s)"
failed=0
while IFS=$'\t' read -r vid name tags; do
	if gh api -X DELETE "/orgs/$ORG/packages/container/$PACKAGE/versions/$vid" >/dev/null 2>&1; then
		printf '    deleted %s %s\n' "${name:0:19}…" "$tags"
	else
		printf '    FAILED  %s %s\n' "${name:0:19}…" "$tags" >&2
		failed=$((failed + 1))
	fi
done <"$PLAN"

if ((failed)); then
	echo "registry-prune: $failed deletion(s) failed" >&2
	exit 1
fi
echo "==> done"
