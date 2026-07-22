# Deployment Verification — `oakandwave-workflow` image (DM-12)

**Trigger for this document (Dev Spec §5.A):** the contained-workflow pipeline
*deploys infrastructure* — it pushes a container image to `ghcr.io` that the OaW
fleet pulls and runs. This runbook is the operator's post-build check that a
pushed candidate is provenance-correct and fleet-pullable **before** it is
allowed anywhere near promotion. It is the manual companion to the automated
throwaway-CI ring (E2E-01, Story 2.2), which performs the same checks in CI and
blocks the digest on any failure.

**Requirements verified here:** R-05 (image = release), R-23 (the digest tested is
the digest promoted), R-24 (OCI labels + registry permissions + cosign signature
+ syft SBOM). **Config existence ≠ config works** (project rule): a workflow that
*ran green* is necessary but not sufficient — verify the artifact itself.

Pipeline under verification: `.github/workflows/oakandwave-workflow-image.yml`
→ `scripts/ci/build-oakandwave-image.sh` (build + label + push, emits the digest)
→ `scripts/ci/sign-oakandwave-image.sh` (cosign sign + syft SBOM attest)
→ `scripts/ci/throwaway-ci-ring.sh` (the `smoke` job — this runbook's §1–§5,
automated, plus install-from-zero and the smoke suite; a red blocks the digest).

The steps below are the manual companion to that ring: run them by hand to audit
a candidate the operator wants to inspect directly. The ring performs the same
provenance checks (labels, permissions, signature, SBOM) *before* it smokes.

---

## 0. Prerequisites

- `docker`, `cosign`, and `syft` on PATH (all three are baked into the image
  itself; on a bare host, install cosign + syft from Sigstore/Anchore releases).
- `ghcr.io` login able to **pull** the target package:
  `echo "$GHCR_TOKEN" | docker login ghcr.io -u <user> --password-stdin`.
- The image reference. Prefer the **digest** the build job emitted
  (`ghcr.io/wave-engineering/oakandwave-workflow@sha256:…`), read from the
  workflow run's `build` step output `digest_ref`. Verifying by digest — never by
  the moving `:edge` tag — is the whole point of R-23.

```bash
# The immutable pin every step below verifies against:
DIGEST_REF="ghcr.io/wave-engineering/oakandwave-workflow@sha256:<digest>"
```

---

## 1. OCI provenance labels (R-24)

The image must carry all four provenance facts — semver, source repo, git
revision, build timestamp — under the canonical OCI keys. These are stamped by
`scripts/ci/oakandwave-oci-labels.sh` (the single source of truth the unit oracle
`tests/contained-workflow/test_provenance.py::test_oci_labels` also checks).

```bash
docker buildx imagetools inspect --format '{{json .Provenance}}{{println}}' "$DIGEST_REF"
docker pull "$DIGEST_REF"
docker image inspect --format '{{json .Config.Labels}}' "$DIGEST_REF" | python3 -m json.tool
```

**Pass criteria** — every key present and non-empty:

| Label key | Fact | Example |
|-----------|------|---------|
| `org.opencontainers.image.version` | semver (bare, no leading `v`) | `2.4.1` |
| `org.opencontainers.image.source` | source repo URL | `https://github.com/Wave-Engineering/claudecode-workflow` |
| `org.opencontainers.image.revision` | git revision (full SHA) | `0123…4567` |
| `org.opencontainers.image.created` | build timestamp (RFC3339, UTC) | `2026-07-22T12:00:00Z` |

The `revision` MUST match the commit the workflow ran on, and `source` MUST point
at this repo — those two are what make the digest auditable back to its source.

---

## 2. Cosign signature (R-24)

Signing is **keyless** (Fulcio-issued cert + Rekor transparency log), driven by
the workflow's OIDC token. Verify the signature exists and was produced by *this
workflow's* identity, not an arbitrary signer:

```bash
cosign verify \
  --certificate-identity-regexp "https://github.com/Wave-Engineering/claudecode-workflow/.github/workflows/oakandwave-workflow-image.yml@.*" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  "$DIGEST_REF"
```

**Pass criteria:** cosign prints a verified signature entry whose certificate
identity is the image workflow and whose issuer is GitHub Actions OIDC. A bare
`cosign verify` that ignores the identity is **not** sufficient — anyone can sign
a public digest; the identity binding is the security property.

---

## 3. Syft SBOM (R-24)

An SPDX SBOM must be attested to the digest so the fleet can audit the image's
contents. Verify the attestation is present and is the SPDX predicate:

```bash
cosign verify-attestation \
  --type spdxjson \
  --certificate-identity-regexp "https://github.com/Wave-Engineering/claudecode-workflow/.*" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  "$DIGEST_REF" | jq -r '.payload' | base64 -d | jq '.predicateType'
```

**Pass criteria:** the attestation verifies and its `predicateType` is the SPDX
type. Spot-check the SBOM lists the baked kit-dep toolchain (go, trivy,
shellcheck, shfmt, glab, bao, aws) — an empty or base-only SBOM means syft ran
against the wrong target.

---

## 4. Registry permissions & visibility (R-24)

R-24 requires the candidate be **fleet-pullable at the intended visibility**. Two
layers, one automated and one operator-owned:

- **Automated (workflow):** `permissions: packages: write` lets the build job push;
  the `org.opencontainers.image.source` label links the package to this repo so it
  inherits the repo's access on ghcr.
- **Operator-owned (one-time, per package):** ghcr package **visibility** and
  **access** are *not* set from workflow YAML. After the first publish, set them in
  the org package settings:
  - Visibility: **internal** (Wave-Engineering members can pull) — the intended
    default for a fleet image. Public only if external kit adopters (§1.4) need it.
  - Ensure the fleet's pull identity (the org, or a fleet PAT) has **read**.

**Verify fleet-pullability from a clean identity** (the check that actually
matters — a package that pushed fine can still be unpullable by the fleet):

```bash
docker logout ghcr.io
echo "$FLEET_GHCR_TOKEN" | docker login ghcr.io -u <fleet-user> --password-stdin
docker pull "$DIGEST_REF"   # MUST succeed as the fleet identity, not just the pusher
```

**Cross-org base pull:** the build itself pulls
`ghcr.io/agent-of-empires/aoe-dev-sandbox` (TC-3/TC-5). If that package is private
to another org, `GITHUB_TOKEN` cannot pull it — provision an `AOE_PULL_TOKEN`
repo secret (a PAT with `read:packages` on agent-of-empires); the login step
prefers it when present.

---

## 5. Digest continuity (R-23)

The digest you verified in steps 1–4 MUST be the same digest that:

1. the `:edge` tag currently points at, and
2. the throwaway-CI ring (E2E-01) tested, and
3. any subsequent promotion (`:edge → :stable`, Story 2.3) retags.

```bash
# The digest behind the moving :edge tag must equal $DIGEST_REF's digest.
docker buildx imagetools inspect ghcr.io/wave-engineering/oakandwave-workflow:edge \
  --format '{{.Manifest.Digest}}'
```

If these diverge, **stop** — a rebuild has occurred between test and promotion and
the provenance chain is broken. Promotion is a digest retag, never a rebuild.

---

## 6. Sign-off

A candidate passes deployment verification only when **all** of §1–§5 pass:
labels correct, signature verifies against the workflow identity, SPDX SBOM
attested, fleet can pull at the intended visibility, and the digest is continuous
from build → edge → (eventual) stable. Record the verified `DIGEST_REF` and the
date; that digest — and only that digest — is eligible for the promotion gate
(Story 2.3, R-07).
