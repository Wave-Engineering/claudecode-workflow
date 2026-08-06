# Image release cadence — a merge is not a release

**A candidate image is cut deliberately.** Merging to `main` does not build one,
does not sign one, and does not push one to GHCR. Only a version tag or a manual
dispatch mints a candidate, and only an explicit promote turns a candidate into
`:stable`.

This page is the operator-facing half of #1063. The trigger's own header comment
in `.github/workflows/oakandwave-workflow-image.yml` carries the rationale;
`tests/contained-workflow/test_image_release_cadence.py` pins it.

## Why it changed

Every push to `main` used to run build → cosign sign → syft SBOM → GHCR push
against a ~9.9 GB base. Measured on a **markdown-only** merge (`cc57a75`,
PR #1060): **1049 s / 17.5 min**.

Two costs, and the first is the expensive one:

1. **Throughput.** `/scpmmr` waits on the main-branch pipeline, so *every agent*
   paid ~17.5 min per merge. Post-cutover that is the inner loop for every kit
   change, multiplied across the fleet.
2. **Registry clutter.** Every merge since the workflow landed minted an `:edge`
   that nothing would ever pull.

It also reads better against **R-05 — the image digest *is* the release.**
Minting a signed, SBOM'd release artifact for a typo fix was never what that
invariant meant.

### Why not a `paths:` filter

Because the kit is **baked into the image**. `skills/**`, `scripts/**`,
`config/**` and the container sources genuinely change what ships, so a filter is
either broad enough to save almost nothing, or narrow enough to **silently ship a
stale `:stable`** — a correctness bug wearing a performance fix's clothes.

The right axis is *"did we decide to release?"*, not *"which files moved?"*.

## The three steps

| step | what runs | what it produces |
|---|---|---|
| **1. Cut a candidate** | push a `v*` tag, or run the workflow via `workflow_dispatch` | `:edge` at a new digest, signed + SBOM'd |
| **2. Test the candidate** | `scripts/ci/aoe-preflight.sh <profile>` against that digest, plus the throwaway CI ring | a pass/fail on the exact bytes |
| **3. Promote** | `scripts/ci/promote-oakandwave-image.sh` | `:stable` retagged to the **same digest** |

Step 3 is `docker buildx imagetools create` — a retag, never a rebuild. **The
digest tested is the digest promoted (R-23).** If promotion ever grows a build
step, that invariant is gone; the oracle asserts it has not.

## Cutting a candidate by hand

```bash
gh workflow run "oakandwave-workflow image" --repo Wave-Engineering/claudecode-workflow
```

Manual dispatch exists so that testing a build does not require pretending to
release. Use it for anything you want to exercise before a tag.

## What this means day to day

- **Merging kit changes to `main` is cheap again.** Main still runs `validate`;
  it just no longer builds an image.
- **`:stable` does not move on its own.** It changes only when someone promotes,
  which is the point — the fleet's pinned digest stays put until a human decides.
- **`main` can be ahead of `:stable`.** That is normal and expected now. If you
  need a container carrying an unreleased change, cut a candidate by hand.
- **Before pinning a profile to a new digest**, run `aoe-preflight.sh` against it.
  Verifying through `aoe` rather than around it is the standing rule
  (`docs/contained-workflow/architecture.md` §3.5.1).

## Registry hygiene — and the trap in it

Accumulated `:edge` digests from the old every-merge behaviour are dead weight:
each is a full image layer set nothing will pull. Measured 2026-08-01:

| | count |
|---|---|
| total versions | **228** |
| untagged | **143** |
| cosign `.sig` / `.att` artifacts | 84 |
| real named tags | **1** (`edge`) |

### DO NOT "prune all untagged versions"

That is the standard GHCR cleanup recipe and **it would have deleted the image
the live fleet was running.** Measured on the same day:

```
profile dogfood → ghcr.io/…/oakandwave-workflow@sha256:7e615dd0…
profile mv05    → ghcr.io/…/oakandwave-workflow@sha256:7e615dd0…

that digest in GHCR:  tags=[]      ← UNTAGGED
```

A profile pins a **bare digest**. Pinning by digest is correct — it is what makes
the release immutable (R-05/R-23) — but it leaves no tag behind, so the pinned
image is indistinguishable from garbage to any tag-based retention rule.
**Untagged does not mean unused.**

So pruning is deliberately manual and operator-driven. An automated retention
policy cannot see the operator's profile pins and would eventually delete one out
from under a running fleet — the failure arriving at the *next container launch*,
long after the prune, with nothing connecting the two.

### The retention policy (#1100)

**Use `scripts/ci/registry-prune.sh`. Do not hand-roll a delete.** It computes the
keep-set from what is *actually referenced*, never from tags:

| kept | why |
|---|---|
| every digest pinned by an aoe profile | the fleet is running it |
| whatever `:edge` / `:stable` / any **named** tag points at | it is addressable |
| the last **5** image manifests (`--keep-recent`) | a rollback window |
| each survivor's `.sig` / `.att` | a signature orphaned from its subject verifies nothing, and a subject without its signature cannot be verified |

Everything else is clutter. It is **dry-run by default**; `--apply` is a separate,
deliberate act, because deleting published artifacts is irreversible and
outward-facing.

Four refusals are the point of the tool, not politeness:

- **No profile pins found → it refuses.** An empty protect-list makes every other
  check vacuous, and "nothing is in use" is exactly the reading that deletes a
  running fleet.
- **An empty registry listing → it refuses**, rather than concluding there is
  nothing to protect from an instrument that returned nothing.
- **A pin missing from the listing → it refuses.** The listing is then incomplete
  — truncated pagination, a permissions gap, the wrong package — and a partial
  listing is dangerous in a specific way: things whose protecting reference was
  not seen look unreferenced. *"I could not see it"* and *"it is not there"* are
  different claims, and only one is safe to act on.
- **A digest it cannot resolve is KEPT, not deleted**, and if `docker` is
  unavailable it refuses outright — parentage it cannot establish is not a
  licence to delete.

### The pinned digest is an INDEX, not a leaf

This is the #1100 trap one layer down, and the reason the tool resolves manifests
at all. buildx pushes an **image index**; its children are the per-arch manifest
and a provenance attestation, and GHCR lists **each child as its own version** —
untagged, unpinned, matching no cosign tag. Measured on the current pin:

```
7896722d  (index — what the profile pins, tagged :edge)
├── 001185d8  amd64 image manifest      ← its own GHCR version, untagged
└── 73d1c4d5  attestation manifest      ← its own GHCR version, untagged
```

**Deleting a child makes the pinned image unpullable** — and, as ever here, not at
prune time but at the next container launch. Of 248 versions, **104 are index
children**. The first cut of this script protected only the index; the children
survived by being recent enough to fall inside the rollback window, which is luck
rather than protection. The keep-set is now a closure: every descendant of
anything kept, plus every cosign artifact of anything kept, iterated to a fixed
point.

**Can automation see the pins? Only if it runs where the pins are.** The script
reads `~/.config/agent-of-empires/profiles/*/config.toml`, which exists on the
operator's host and nowhere else — so this must **not** be wired to a scheduled
GitHub Action, which would run with an empty pin list and hit the refusal (or
worse, be "fixed" by removing it). Retention stays a host-side operator step until
releases carry registry tags.

**The rollback window exists because releases are not identifiable in the
registry.** The build pushes only `:edge` — no `:vX.Y.Z` — so v8.1.1's image is
indistinguishable from any intermediate push. Until that changes, "the most recent
N manifests" is the only honest anchor for history. Tagging releases in the
registry would let retention key on something meaningful and is the real fix.

**Always enumerate the pins first** (the script does this, and prints them):

```bash
grep -h default_image ~/.config/agent-of-empires/profiles/*/config.toml
```

Everything in that list must survive, plus the current `:edge`, plus whatever
`:stable` points at, plus each survivor's `.sig` and `.att` artifacts.

### `:stable` does not exist yet

As of 2026-08-01 there is **no `:stable` tag** anywhere in the 228 versions — the
bless-and-promote path is implemented end to end but has never been run, and the
profiles pin bare digests instead. Two consequences:

- Nothing is protected by "keep whatever `:stable` points at" today, because it
  points at nothing. The profile pins are the *only* thing standing between a
  prune and a broken fleet.
- The first real promote is also the first exercise of that path. Run it against a
  candidate you have already preflighted, and verify `:stable` resolves to the
  digest you expect before pointing any profile at it.
