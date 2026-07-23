<!-- DEV-SPEC-APPROVAL
approved: true
approved_by: BJ
approved_at: 2026-07-22T08:07:06Z
finalization_score: 8/8
-->

# Contained Workflow — Development Specification

**Plan:** #959
**Design source:** `docs/contained-workflow-SKETCHBOOK.md` (merged #958)
**Status:** Approved (BJ, 8/8) — backlog upshifted to #961–#976

## Table of Contents

1. Problem Domain
2. Constraints
3. Requirements (EARS Format)
4. Concept of Operations
5. Detailed Design
6. Test Plan
7. Definition of Done
8. Phased Implementation Plan
9. Appendices

---

## 1. Problem Domain

### 1.1 Background
The OaW fleet runs a shared `~/.claude` kit installed via `./install`; every agent on a workstation reads from that one tree. AoE — the session manager the fleet already uses — natively supports per-session **sandbox containers** (`aoe add --sandbox`), verified on the installed `aoe 1.13.0`.

### 1.2 Problem Statement
There is no boundary between the kit being tested and the kit the fleet runs. A kit update cannot be validated without mutating the shared state the live fleet depends on. The 2026-07-19/20 upgrade demonstrated the cost: `./install` run under 15 live agents left six watchers on deleted inodes, clobbered the live Discord token, and stranded a dangling `mcp.json` registration. Worse, one break blocked **every** agent — a stop-the-world scramble — because all shared one `~/.claude` and one version. Un-versioned toolchain drift (`gh 2.45` lacking `pr checks --json` / `pr update-branch`) compounded it.

### 1.3 Proposed Solution
Package the kit as a **versioned container image** (`oakandwave-workflow:<semver>`) built on the AoE sandbox base, with the kit and its toolchain baked in — so the **image digest *is* the release**. Run the OaW dev team in these containers (the **dogfood ring**) to prove a candidate by working in it before the fleet adopts it. Promote by digest retag (`:edge → :stable`); the fleet adopts `:stable` per-agent at container-recreate. Keep the container a **stateless, disposable RTE** — all durable state lives on host-backed mounts — so a broken candidate is `docker rm`, not an incident.

### 1.4 Target Users
- **OaW dev-agents** (primary) — the dogfood ring; they run `:edge` while building the next kit.
- **The wider OaW fleet** — consumers of promoted `:stable`, adopting per-agent under the compatibility contract.
- **External kit adopters** — the image is an *extensible base*; their own MCPs, CLIs, and dev tools compose via the user-environment overlay.

### 1.5 Non-Goals
- **Multi-agent-runtime portability** (opencode/qwen) — real, but a separate track; this Dev Spec assumes Claude Code.
- **VS Code attach** and the **keycloak CLI** — explicitly dropped.
- **A shared-state migration engine** — the SemVer compatibility contract (§5.8) replaces it; no format-migration machinery is built.
- **Rewriting the kit's workflow logic** — this is packaging and isolation, not a behavior change. Skills, hooks, and MCP servers keep their current semantics.

*(Ledger: D-001)*

---

## 2. Constraints

### 2.1 Technical Constraints
- **TC-1** — AoE's sandbox model is one-container-per-session (`aoe add --sandbox`, verified on `aoe 1.13.0`). Container behavior is configured via `[sandbox]` keys (`user`/`uid`/`home_dir`/`mounts`/`volumes`/…) — capability-confirmed from the binary; exact TOML syntax and runtime behavior UNPROVEN (§5.N).
- **TC-2** — Docker here is rootful, no userns remap: in-container root = host root. "me-ful" (§5.1) requires setting `uid` **and** building the image with a matching uid-1000 user (reusing the base's `ubuntu`).
- **TC-3** — Base image is `ghcr.io/agent-of-empires/aoe-dev-sandbox:1.13.0` (Ubuntu 26.04, ~9.9 GB; tag tracks the aoe binary version). Ships Rust / Python+uv / Node; **missing** Go, trivy, shellcheck, shfmt, glab.
- **TC-4** — Durability requires host-backed mounts. The container filesystem is disposable; anything durable must be host-backed. AoE already host-backs the workspace and `~/.claude/sandbox`.
- **TC-5** — Network egress works on the default bridge (scream-hole, discord, `api.github.com` reachable — proven); `ghcr.io` needs a token.
- **TC-6** — CephFS is org infrastructure mounted with the ceph *admin* key. Containers bind-mount the host's already-mounted `/mnt/cephfs` path; they never mount ceph directly.
- **TC-7** — AoE documents no host↔container networking/exec. Egress is proven; control-plane ingress (`aoe send` into the container) and the bootstrap seam (`aoe-hooks` vs image `ENTRYPOINT`) are UNPROVEN probes (§5.N).

### 2.2 Product Constraints
- **PC-1** — Users are developers; the compatibility contract can rely on developer judgment.
- **PC-2** — Same-major mixing must be safe; a major bump signals a breaking change (§5.8).
- **PC-3** — The base image must stay portable: no OaW-org specifics (cephfs paths, `~/.secrets` contents) baked into the image; org-infra is a run-layer overlay only.
- **PC-4** — The kit is an *extensible base* for adopters; their MCP servers, CLIs, and dev tools compose via the user-environment overlay without kit changes.
- **PC-5** — Secrets are never baked into image layers and must be live-addable mid-session (the read-only `~/.secrets` dir mount, §5.5).
- **PC-6** — Promotion must be mechanical, not a feeling: the optional human ACK can only confirm an already-green gate; it can never substitute for the mechanical conditions.

*(Ledger: D-002)*

---

## 3. Requirements (EARS Format)

Every requirement ID appears in at least one Test Plan item (§6), Story AC (§8), or DoD item (§7); the VRTM (Appendix V) provides the formal trace.

### 3.1 Isolation & statelessness

| ID | Type | Requirement |
|----|------|-------------|
| R-01 | Ubiquitous | The container filesystem shall be a disposable RTE; all durable state shall reside on host-backed mounts. |
| R-02 | Event-driven | WHEN a container is removed and recreated, the system shall lose no durable state. |
| R-03 | Ubiquitous | The rw memory mount's host source shall be a sandbox-scoped path (`~/.oaw/state/<major>/`), never the live-fleet `~/.claude/projects/*/memory/`. |
| R-04 | Ubiquitous | The container shall run as uid 1000 (non-root); files written to bind-mounts shall be host-user-owned. |

### 3.2 Image, release & promotion

| ID | Type | Requirement |
|----|------|-------------|
| R-05 | Ubiquitous | The kit shall be packaged as `oakandwave-workflow:<semver>`; the image digest shall be the release artifact. |
| R-06 | Ubiquitous | For any dogfood/candidate image, everything versioned-with-the-release (skills, hooks, scripts, toolchain) shall be baked into the image and nothing versioned shall be bind-mounted. (The dev-mode profile's skills overlay, R-21, is the explicit non-promotable exception.) |
| R-07 | Event-driven | WHEN the promotion gate's mechanical conditions are all green (throwaway-CI pass, soak met, zero quarantines, zero open Sev-1), THEN promotion `:edge → :stable` shall be permitted, retagging the exact digest E2E-01 tested; a human ACK shall only confirm a green gate, never substitute for it. |
| R-08 | Event-driven | WHEN a minor/patch `:stable` is published, the fleet shall adopt it per-agent at container-recreate, not by synchronized flip. |

### 3.3 State taxonomy & overlay

| ID | Type | Requirement |
|----|------|-------------|
| R-09 | Ubiquitous | Third-party and user MCP servers shall compose via additive scoping; the kit's own MCP registrations shall be baked at stable image paths. |
| R-10 | Unwanted | IF a durable artifact is a compiled binary, THEN it shall be installed in-container, never symlinked across the host/container libc boundary; scripts and config may symlink. |
| R-11 | Ubiquitous | Discretionary dev tools shall install from a declarative manifest into a durable bind-mounted toolbox, decoupled from the kit release. |

### 3.4 Secrets

| ID | Type | Requirement |
|----|------|-------------|
| R-12 | Ubiquitous | Secrets shall never be baked into image layers; they shall be provided via a read-only bind-mount of `~/.secrets`. |
| R-13 | Event-driven | WHEN the host adds a secret file to `~/.secrets` mid-session, the running container shall see it without a restart. |
| R-14 | Unwanted | IF a required secret is missing at boot, THEN the bootstrap shall fail loudly. |

### 3.5 Health probe & escape hatch

| ID | Type | Requirement |
|----|------|-------------|
| R-15 | Ubiquitous | A host-side probe running `:stable` shall detect a broken `:edge` container by reading its host-backed transcript directly, without depending on the container's kit. |
| R-16 | State-driven | WHILE a container's aoe status is `running` and its transcript has not grown for N minutes (or shows a loop signal), the probe shall classify it broken. |
| R-17 | Event-driven | WHEN the probe detects a broken container, THEN it shall quarantine it (stop + roll back to `:stable`) losslessly. |

### 3.6 Compatibility

| ID | Type | Requirement |
|----|------|-------------|
| R-18 | Ubiquitous | Agents on the same major version shall interoperate over shared state; within-major shared-state changes shall be additive and forward-tolerant. |
| R-19 | Unwanted | IF a change breaks same-major shared-state compatibility, THEN it shall require a major bump, and a mechanical guard shall detect the break and block a silent minor ship. |
| R-20 | Ubiquitous | The major version shall partition the shared-state namespace so mixing majors is isolated, not corrupting. |

### 3.7 Profiles

| ID | Type | Requirement |
|----|------|-------------|
| R-21 | Ubiquitous | The system shall provide two container profiles: dev-mode (skills overlay ON, excluded from promotion telemetry) and dogfood (overlay OFF, image-only, feeds the gate). |
| R-22 | Ubiquitous | The health probe and promotion gate shall filter on the profile label; dev-mode runs and breakages shall not count toward soak or trip quarantine. |

### 3.8 Artifact provenance (registry)

| ID | Type | Requirement |
|----|------|-------------|
| R-23 | Ubiquitous | E2E-01 shall run against the candidate pulled from ghcr by digest, never a local build; the digest tested, the digest promoted (R-07), and the digest the fleet pulls shall be identical. |
| R-24 | Ubiquitous | The candidate in ghcr shall carry correct OCI labels (semver, source repo, git revision, build timestamp) and correct registry permissions (fleet-pullable at the intended visibility); E2E-01 shall verify labels, permissions, and the cosign signature / syft SBOM before the smoke suite runs. |

*(Ledger: D-003, D-005)*

---

## 4. Concept of Operations

### 4.1 System Context

```
                 ┌────────────── host workstation ──────────────┐
 operator (BJ) ──┤  aoe + rootful docker                        │
                 │   ├─ :edge containers (dogfood ring) ──┐      │
                 │   ├─ dev-mode containers               │      │
                 │   └─ flight surgeon (:stable) ─watches─┘      │
                 │  /mnt/cephfs (admin key)   ~/.secrets (ro)    │
                 └───────────┬───────────────────────┬──────────┘
                             │ pull/push by digest    │ transcript/telemetry
                        ghcr.io (images)          FlightDeck (#854)
                             │
                        GitHub (source + release + image-build CI)
```

- **Actors:** OaW dev-agents (dogfood ring); the wider fleet (consumers of `:stable`); external adopters; BJ/operator (final ACK on promotion; `:stable` cross on majors).
- **Registry:** `ghcr.io` holds `oakandwave-workflow:<semver>`; `:edge` and `:stable` are moving tags over pinned digests.
- **Telemetry:** FlightDeck (#854) — the event stream the probe writes to and the promotion gate queries.

### 4.2 Build a candidate (`:edge`)
Kit change merges → CI builds `FROM aoe-dev-sandbox:1.13.0` + kit deps + `./install` → pushes to ghcr with OCI labels + cosign/syft → tags the digest `:edge`. The throwaway-CI ring installs it from zero and smokes it; a red smoke blocks the digest.

### 4.3 Dogfood soak
OaW dev-agents launch the dogfood profile on `:edge`. They do real work; host-backed transcript/memory/secrets/toolbox mount in. The flight surgeon watches each container; clean work accrues soak in FlightDeck.

### 4.4 Promotion
The gate queries FlightDeck + the CI result. WHEN all mechanical conditions are green, the operator's ACK confirms and the tested `:edge` digest is retagged `:stable`. No rebuild — a digest promotion.

### 4.5 Fleet adoption
Fleet agents pull `:stable` at their next container-recreate (a restart boundary, never mid-session). Rolling, per-agent; same-major compat lets updated and not-yet-updated agents coexist.

### 4.6 Broken candidate (quarantine & rollback)
The flight surgeon sees `status=running` + a flat transcript for N min (or a loop signal) → quarantine: stop, `docker rm`, recreate on `:stable`. Lossless, because all durable state was host-backed. The operator is alerted; the bad digest is held from promotion.

### 4.7 Kit-dev inner loop
A dev iterating on the next kit runs the dev-mode profile (skills overlay ON) — live-edit kit source, see it instantly, no rebuild. Labeled non-candidate, excluded from soak/quarantine telemetry. The boundary from "iterating" to "proving" is the moment the change is built into `:edge`.

### 4.8 Add a secret mid-session
The operator drops a file into `~/.secrets`; it appears live in every running container's read-only mount. File-path consumers use it immediately; an already-running daemon needing it restarts *that process*, not the container.

---

## 5. Detailed Design

### 5.1 Container & isolation model
Per-session sandbox (`aoe add --sandbox`). **me-ful:** run as uid-1000 via `[sandbox] uid`/`user`/`home_dir`, reusing the base image's uid-1000 `ubuntu` user so bind-mount writes are host-owned (R-04). The **stateless-container invariant** (R-01): the container filesystem is disposable; all durable state is a host-backed mount. Isolation-under-full-mount-set is an open probe (§5.N).

### 5.2 Image composition
`FROM ghcr.io/agent-of-empires/aoe-dev-sandbox:1.13.0` → kit-dep layer (Go, trivy, shellcheck, shfmt, glab; `bao`, `aws` per the tool manifest) → `./install` the kit → the build stage signs (cosign) and SBOMs (syft) the digest and stamps OCI labels (R-05/R-06/R-24). The image *digest* is the release; `:edge`/`:stable` are moving tags.

### 5.3 Mount manifest (state taxonomy)
Five layers, each with a fixed mechanism:
- **Baked-in-image** (versioned): skills, hook scripts, kit MCP registrations (R-06/R-09).
- **Shared-mutable-rw**: memory, from a **sandbox-scoped host source** `~/.oaw/state/<major>/` — never the live-fleet tree (R-03).
- **Read-only secrets**: `~/.secrets` (§5.5).
- **User-environment overlay**: third-party/user MCPs (additive scoping), non-kit scripts (symlink), compiled tools (installed in-container, R-10), the declarative toolbox (R-11).
- **Durable caches**: `CARGO_HOME`, `GOMODCACHE`, `~/.cache/uv`, `~/.cache/ms-playwright`.
`settings.json` is split: image ships hook wiring; a bind-mount provides `settings.local.json`.

### 5.4 Bootstrap script
Runs before the agent (via the `aoe-hooks` seam — open probe §5.N). Performs: skills symlink-sync (image-wins, host-fills, collision-logged), `settings.local` merge, secret sourcing, env validation. **Assertion-liveness:** every silent-skip path (missing mount, missing secret, shadowed skill, dangling link) becomes a logged or failing condition (R-14).

### 5.5 Secrets
Read-only bind-mount of the whole `~/.secrets` dir (R-12). Live mid-session adds (R-13, proven). Prefer file-path consumers (fully live) over env-var consumers. `.env` = env modality, loose files = path modality. Fail loud at boot on a missing required secret (R-14). Whole-dir blast-radius (every ring sees every secret) is flagged; least-privilege scoping is an open item (§5.N).

### 5.6 Promotion & rings
Two rings: **dogfood** (persistent, real-workload) + **throwaway-CI** (install-from-nothing smoke). The promotion gate is a mechanical conjunction queried over FlightDeck + CI (R-07); adoption is rolling per-agent at container-recreate (R-08).

### 5.7 Flight surgeon (health probe)
A host-side process running `:stable` (or bare) reads each `:edge` container's host-backed `.jsonl` transcript directly — fate-independent, because the transcript is written by the harness below the kit (R-15). Correlates transcript growth with aoe status (running/waiting/idle): `running` + flat-for-N-min = stalled; a loop heuristic (same tool K times / no forward progress) catches looping (R-16). On broken: quarantine + lossless rollback (R-17).

### 5.8 Compatibility & versioning
SemVer contract: same-major mixing is safe; a breaking shared-state change bumps the major (R-18). The major partitions the state namespace `~/.oaw/state/<major>/` so mixing majors is isolated, not corrupting (R-20). Within a major, shared-state changes are additive + forward-tolerant. A **mechanical guard** versions the shared-state schema and blocks a silent same-major-breaking minor (R-19).

### 5.9 Profiles
Two profiles: **dev-mode** (skills overlay ON, labeled non-candidate) and **dogfood** (overlay OFF, image-only). The health probe and promotion gate filter on the profile label; dev-mode runs/breakages never count toward soak or trip quarantine (R-21/R-22).

### 5.A Deliverables Manifest

| ID | Deliverable | Category | Tier | File Path | Produced In | Status | Notes |
|----|-------------|----------|------|-----------|-------------|--------|-------|
| DM-01 | README.md | Docs | 1 | `containers/oakandwave-workflow/README.md` | P1W1 (finalized P4W2) | required | Overview, build + run the image and rings |
| DM-02 | Unified build system | Code | 1 | `containers/oakandwave-workflow/Makefile` | P1W1 | required | `make build` / `make test` identical in CI and terminal |
| DM-03 | CI/CD pipeline | Code | 1 | `.github/workflows/oakandwave-workflow-image.yml` | P2W1 | required | Build → push → throwaway-CI smoke |
| DM-04 | Automated test suite | Test | 1 | `tests/contained-workflow/` | P1W1 | required | Unit + integration; grows through all waves |
| DM-05 | Test results (JUnit XML) | Test | 1 | `reports/junit.xml` | P2W1 | required | CI artifact upload |
| DM-06 | Coverage report | Test | 1 | `reports/coverage.xml` | P2W1 | required | Completeness signal, reported regardless of repo gates |
| DM-07 | CHANGELOG | Docs | 1 | N/A — because OaW uses curated release notes as the source of truth (sdlc#459); a CHANGELOG is deliberately not maintained | — | N/A | — |
| DM-08 | VRTM | Trace | 1 | Dev Spec Appendix V | P4W2 | required | Requirement traceability matrix |
| DM-09 | Ops runbook | Docs | 1 | `docs/contained-workflow/ops-runbook.md` | P4W2 | required | Build `:edge` / dogfood / promote / quarantine+rollback |
| DM-10 | Manual verification procedures | Docs | 2 | `docs/contained-workflow/manual-verification.md` | P4W2 | required | Trigger: MV-XX items in §6.4 |
| DM-11 | Architecture document | Docs | 2 | `docs/contained-workflow/architecture.md` | P1W2 | required | Trigger: >2 interacting components |
| DM-12 | Deployment verification procedures | Docs | 2 | `docs/contained-workflow/deployment-verification.md` | P2W1 | required | Trigger: deploys infrastructure (image promotion) |
| DM-13 | Environment prerequisites document | Docs | 2 | `docs/contained-workflow/environment-prerequisites.md` | P1W1 | required | Trigger: host/platform requirements (docker, aoe, cephfs, ~/.secrets, uid) |

### 5.B Installation & Deployment

#### Local Installation
1. `make -C containers/oakandwave-workflow build` — builds `oakandwave-workflow:edge` from the base image + kit.
2. `aoe add --sandbox --sandbox-image oakandwave-workflow:edge <path>` — launch an agent on the candidate.
3. `docker run --rm --entrypoint sh oakandwave-workflow:edge -c 'trivy --version && shellcheck --version && glab --version'` — verify the toolchain.

#### CI/CD Pipeline

| Stage | Trigger | Steps | Artifacts Produced | Gate |
|-------|---------|-------|-------------------|------|
| Validate | every push | lint (shellcheck/shfmt), py_compile | none | must pass to merge |
| Test | every push | pytest + coverage | DM-05, DM-06 | must pass to merge |
| Build | merge to `main` | build image, push to ghcr, cosign + syft, OCI labels | image digest (promotes to `:edge`) | must succeed |
| Smoke (throwaway-CI ring) | after Build | pull digest, verify labels/perms/sig, install-from-zero, smoke | none | red smoke blocks the digest |
| Promote | mechanical gate green + operator ACK | retag tested digest `:edge → :stable` | none (promotes the digest) | all-green mechanical conditions |

#### Production / Release Deployment
Fleet agents adopt `:stable` at container-recreate (rolling, per-agent). Rollback = repoint at the prior `:stable` digest. Major-version crosses are opt-in per the compatibility contract (§5.8).

### 5.N Open Questions
1. **me-ful ownership outcome:** confirm files land `bakerb`-owned once `[sandbox] uid` is set — tested in an isolated aoe profile, never the fleet's global config (MV-01).
2. **F1 transcript-flush keystone:** does a wedged/OOM-killed `claude` still flush the transcript at the failure boundary? Operator field experience (many hard-kills, never a flush issue) indicates likely-ok; the surgeon's detection is fail-safe (a lost last-turn makes it detect the stall *earlier*, not miss it). Confirming probe retained (MV-06).
3. **Isolation under the full custom mount set:** the "live `~/.claude` not exposed" result was one default-`--sandbox` observation; confirm it holds with D-5.3's full mount manifest present (MV-02).
4. **F3 compat-break *enforcement*:** the SemVer policy is settled; mechanically detecting a *semantic* compat break (a field whose meaning changes without its shape changing) is the hard part (R-19) — options: schema-hash gate, field-level contract tests.
5. **AoE bootstrap seam:** does aoe respect the image `ENTRYPOINT`, or `docker exec` claude directly? Determines where the bootstrap (§5.4) hooks in (MV-04 exercises the related control-plane ingress).

*(Ledger: D-004; R-23/R-24 added in D-005)*

---

## 6. Test Plan

### 6.1 Test Strategy
Four tiers, with **red-first assertion-liveness** on every guard (break it, watch it fail, restore):
- **Unit** (story-level, §8): bootstrap silent-skip paths, mount resolver, compat guard, surgeon stall/loop classifier.
- **Integration** (§6.2): image build, secret liveness, ownership, schema-break detector.
- **End-to-end** (§6.3): throwaway-CI ring, promotion cycle, planted-broken quarantine.
- **Manual** (§6.4): the things needing a real container + host.
Coverage is produced as a **completeness signal** (DM-06), reported regardless of any repo gate.

### 6.2 Integration Tests (Automated)
- **IT-01** — Bootstrap skills-sync: image-wins on collision, host fills gaps, every collision logged. `[R-06, R-10]`
- **IT-02** — Secret liveness: a host-added `~/.secrets` file appears live in a running container, readable. `[R-12, R-13]`
- **IT-03** — Mount-manifest build: a `FROM aoe-dev-sandbox` image with the full custom mount set comes up clean. `[R-01, R-03, R-06, R-09, R-10, R-11]`
- **IT-04** — me-ful ownership: files written to bind-mounts are `bakerb`-owned (uid 1000). `[R-04]`
- **IT-05** — Compat guard: a deliberate within-major shared-state schema break trips the gate (red-first). `[R-18, R-19, R-20]`

### 6.3 End-to-End Tests (Automated)
- **E2E-01** — Throwaway-CI ring: pull the candidate digest from ghcr, verify OCI labels + registry permissions + cosign signature/syft SBOM, install from zero, run the smoke suite. A red smoke blocks the digest. `[R-05, R-23, R-24]`
- **E2E-02** — Promotion cycle: soak → mechanical gate green → retag the tested digest `:edge → :stable` in a test namespace → rolling per-agent adoption. `[R-07, R-08]`
- **E2E-03** — Broken-candidate quarantine: plant a broken `:edge` (e.g. a wedged Stop hook), confirm the flight surgeon detects it and rolls back to `:stable` losslessly (durable state intact). `[R-02, R-17]`

### 6.4 Manual Verification Procedures
Procedures live in DM-10 (`docs/contained-workflow/manual-verification.md`); each must be executed AND recorded.
- **MV-01** — Files land `bakerb`-owned under the me-ful config (isolated aoe profile). `[R-04]`
- **MV-02** — The live `~/.claude` is not exposed once the full custom mount set is present. `[R-01, R-03]`
- **MV-03** — Network egress reaches scream-hole / discord / github from inside. `[R-05]`
- **MV-04** — `aoe send` reaches into a running container (control-plane ingress). `[R-15]`
- **MV-05** — A broken container quarantines and recreates on `:stable` with zero work lost. `[R-02, R-17]`
- **MV-06** — A wedged/OOM-killed `claude` still flushed its transcript at the failure boundary (or the surgeon's fallback covers it). `[R-15]`
- **MV-07** — A secret added mid-session is usable by a newly-spawned command with no container restart. `[R-13]`

---

## 7. Definition of Done

The Global DoD references the Deliverables Manifest (§5.A) and the Test Plan (§6).

- [ ] All Phase DoD checklists are satisfied
- [ ] All Test Plan items (§6) executed and passed
- [ ] All deliverables from the Deliverables Manifest (§5.A) produced and verified, with `Produced In` waves complete
- [ ] `oakandwave-workflow:<semver>` builds reproducibly; the throwaway-CI ring installs it from zero and passes smoke `[R-05, R-23, R-24]`
- [ ] me-ful ownership and isolation-under-full-mount-set verified against a real container `[R-01, R-03, R-04]`
- [ ] The flight surgeon detects a planted broken `:edge` and rolls back to `:stable` losslessly `[R-02, R-15, R-16, R-17]`
- [ ] The compat-break guard trips red-first on a within-major schema break `[R-18, R-19, R-20]`
- [ ] The promotion gate is mechanical — no code path promotes without all green conditions — and is demonstrated end-to-end `[R-07, R-08]`
- [ ] Coverage reported as the completeness signal (DM-06)
- [ ] Secrets never baked; live-add works; fail-loud on missing required `[R-12, R-13, R-14]`
- [ ] Profiles enforced; dev-mode excluded from gate/quarantine telemetry `[R-21, R-22]`
- [ ] Every MV-01..MV-07 executed and either passes or is explicitly deferred with rationale (no silent skips)
- [ ] No unresolved high+ code-review findings; `/precheck` green on every merge

### 7.2 Dev Spec Finalization Checklist

- [ ] Every Tier 1 row in the Deliverables Manifest (5.A) has a file path or "N/A — because [reason]"
- [ ] Every Tier 2 trigger that fires has a corresponding row in the Deliverables Manifest
- [ ] Every Deliverables Manifest row has a "Produced In" wave assignment
- [ ] Every MV-XX in Section 6.4 has a procedure document in the Deliverables Manifest
- [ ] No deliverable is referenced only as a verb without a corresponding noun (file path)
- [ ] At least one audience-facing doc (DM-09) has a file path assigned
- [ ] Section 7 Definition of Done references the Deliverables Manifest

---

## 8. Phased Implementation Plan

### How to read this section
Phases run in order; Waves within a Phase are concurrency units; each Story becomes one issue in one repo (`Wave-Engineering/claudecode-workflow`). Every AC is annotated with the requirement ID(s) it verifies.

### Wave Map

```
P1W1 ─┬─ [1.1] Build the image (foundation)
       └─ [1.2] me-ful config + ownership
            │
P1W2 ─┬─ [1.3] Mount-manifest resolver
       ├─ [1.4] Bootstrap script
       └─ [1.5] Secrets mount + liveness
            │
P2W1 ─┬─ [2.1] CI build + push + cosign/syft
       └─ [2.2] Throwaway-CI ring (E2E-01)
            │
P2W2 ─┬─ [2.3] Mechanical promotion gate
       └─ [2.4] Rolling per-agent adoption
            │
P3W1 ─┬─ [3.1] Flight surgeon          P3W2 ─┬─ [3.3] Compat contract + namespace
       └─ [3.2] Quarantine + rollback         └─ [3.4] Compat-break guard
            │                                        │
P4W1 ───── [4.1] Profiles + label filtering
            │
P4W2 ─┬─ [4.2] Dogfood cutover (soak)
       └─ [4.3] Docs + VRTM (closing story)
```

| Wave | Stories | Parallel? |
|------|---------|-----------|
| P1W1 | 1.1, 1.2 | Partial (1.2→1.1) |
| P1W2 | 1.3, 1.4, 1.5 | Partial (1.4→1.3, 1.5→1.4) |
| P2W1 | 2.1, 2.2 | Partial (2.2→2.1) |
| P2W2 | 2.3, 2.4 | Partial (2.4→2.3) |
| P3W1 | 3.1, 3.2 | Partial (3.2→3.1) |
| P3W2 | 3.3, 3.4 | Partial (3.4→3.3) |
| P4W1 | 4.1 | Single story |
| P4W2 | 4.2, 4.3 | Partial (4.3→4.2) |

---

### Phase 1: Image & isolation foundation

**Goal:** an agent boots on the built image as uid-1000 with the full mount manifest.

#### Phase 1 Definition of Done
- [ ] `oakandwave-workflow:edge` builds from the base + kit deps `[R-05, R-06]`
- [ ] An agent boots on the image as uid-1000; bind-mount writes are `bakerb`-owned `[R-04]`
- [ ] The full mount manifest comes up clean; the live `~/.claude` is not exposed `[R-01, R-03]`
- [ ] Secrets mount read-only; a mid-session add appears live `[R-12, R-13]`
- [ ] All Phase 1 unit tests pass; IT-01..IT-04 runnable

#### Story 1.1: Build the `oakandwave-workflow` image (#961)
**Wave:** P1W1
**Dependencies:** None
Build the versioned image from the AoE base plus the kit and its missing toolchain.
**Implementation Steps:**
1. Create `containers/oakandwave-workflow/Dockerfile` — `FROM ghcr.io/agent-of-empires/aoe-dev-sandbox:1.13.0`; add Go, trivy, shellcheck, shfmt, glab, `bao`, `aws`; create/rename a uid-1000 user; `./install` the kit.
2. Create `containers/oakandwave-workflow/Makefile` (DM-02) with `build`, `test`, `ci` targets.
3. Create `containers/oakandwave-workflow/README.md` (DM-01) and `docs/contained-workflow/environment-prerequisites.md` (DM-13).
**Test Procedures:** *Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_image_toolchain` | asserts Go/trivy/shellcheck/shfmt/glab present in the built image | `tests/contained-workflow/test_image.py` |

*Integration/E2E Coverage:* IT-03 (partial — image build half).
**Acceptance Criteria:**
- [ ] The image builds and `docker run` reports all kit-dep tools present `[R-05, R-06]`
- [ ] `make build` and `make test` behave identically in CI and terminal `[R-06]`
- [ ] `containers/oakandwave-workflow/README.md` and `environment-prerequisites.md` exist `[R-05]`

#### Story 1.2: me-ful config + ownership verification (#962)
**Wave:** P1W1
**Dependencies:** 1.1
Configure the sandbox to run as uid-1000 and prove bind-mount writes are host-owned.
**Implementation Steps:**
1. Author the isolated-profile `[sandbox]` config (`uid`, `user`, `home_dir`) reusing the base `ubuntu` uid-1000.
2. Add `tests/contained-workflow/test_ownership.py` and the MV-01 procedure to `docs/contained-workflow/manual-verification.md` (DM-10).
**Test Procedures:** *Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_uid_config` | asserts the sandbox config sets uid 1000 | `tests/contained-workflow/test_ownership.py` |

*Integration/E2E Coverage:* IT-04 (runnable).
**Acceptance Criteria:**
- [ ] A file written to a bind-mount from inside is `bakerb`-owned on the host `[R-04]`
- [ ] MV-01 procedure documented in DM-10 `[R-04]`

#### Story 1.3: Mount-manifest resolver (#963)
**Wave:** P1W2
**Dependencies:** 1.1
Implement the five-layer mount manifest, with the memory source sandbox-scoped.
**Implementation Steps:**
1. Author `containers/oakandwave-workflow/mounts.d/` manifest + resolver; memory source `~/.oaw/state/<major>/`, never the live tree.
2. Implement additive MCP scoping, in-container binary install vs symlink for scripts/config, durable-cache mounts.
3. Author `docs/contained-workflow/architecture.md` (DM-11).
**Test Procedures:** *Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_memory_source_scoped` | rejects a live-fleet memory source; accepts sandbox-scoped | `tests/contained-workflow/test_mounts.py` |

*Integration/E2E Coverage:* IT-03 (runnable).
**Acceptance Criteria:**
- [ ] The manifest resolves with a sandbox-scoped memory source; a live-fleet source is rejected `[R-03]`
- [ ] Compiled binaries install in-container; scripts/config symlink `[R-10]`
- [ ] Third-party/user MCPs compose via additive scoping `[R-09, R-11]`
- [ ] `architecture.md` exists (DM-11)

#### Story 1.4: Bootstrap script (#964)
**Wave:** P1W2
**Dependencies:** 1.3
The container bootstrap: skills-sync, `settings.local` merge, secret sourcing, env validation, assertion-liveness.
**Implementation Steps:**
1. Author `containers/oakandwave-workflow/bootstrap.sh`; skills symlink-sync (image-wins, host-fills, collision-**logged**); `settings.local` merge; source `~/.secrets`; validate required env.
2. Make every silent-skip path (missing mount, missing secret, shadowed skill, dangling link) log or fail.
**Test Procedures:** *Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_bootstrap_failloud` | asserts each silent-skip path logs/fails, red-first | `tests/contained-workflow/test_bootstrap.py` |

*Integration/E2E Coverage:* IT-01 (runnable).
**Acceptance Criteria:**
- [ ] Skills-sync is image-wins/host-fills and logs every collision `[R-06, R-10]`
- [ ] A missing required secret makes the bootstrap fail loudly `[R-14]`
- [ ] Each silent-skip path is shown red-first before the guard is trusted `[R-14]`

#### Story 1.5: Secrets mount + liveness (#965)
**Wave:** P1W2
**Dependencies:** 1.4
Read-only `~/.secrets` dir mount with proven mid-session liveness.
**Implementation Steps:**
1. Wire the ro `~/.secrets` dir mount into the manifest; document the consumer split and blast-radius tradeoff in the architecture doc.
2. Add MV-07 to DM-10.
**Test Procedures:** *Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_secrets_readonly` | container cannot write the mount; host can | `tests/contained-workflow/test_secrets.py` |

*Integration/E2E Coverage:* IT-02 (runnable).
**Acceptance Criteria:**
- [ ] Secrets are never in an image layer; provided only via the ro mount `[R-12]`
- [ ] A host-added file appears live in a running container `[R-13]`

---

### Phase 2: Build pipeline, registry & promotion

**Goal:** E2E-01 green against the registry artifact by digest; digest continuity proven.

#### Phase 2 Definition of Done
- [ ] CI builds, pushes to ghcr with OCI labels + cosign/syft `[R-24]`
- [ ] E2E-01 pulls the candidate by digest and verifies labels/perms/signature before smoke `[R-23, R-24]`
- [ ] The promotion gate is mechanical; the tested digest is what promotes `[R-07, R-23]`
- [ ] Rolling per-agent adoption works at container-recreate `[R-08]`
- [ ] All Phase 2 unit tests pass; E2E-01/E2E-02 runnable

#### Story 2.1: CI image build + push + cosign/syft (#966)
**Wave:** P2W1
**Dependencies:** 1.1
**Implementation Steps:**
1. Author `.github/workflows/oakandwave-workflow-image.yml` (DM-03): build → push to ghcr → cosign sign → syft SBOM → stamp OCI labels (semver, source, revision, timestamp).
2. Configure registry permissions (fleet-pullable, intended visibility); wire JUnit/coverage artifacts (DM-05/DM-06); author `deployment-verification.md` (DM-12).
**Test Procedures:** *Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_oci_labels` | asserts required labels present on the pushed image | `tests/contained-workflow/test_provenance.py` |

*Integration/E2E Coverage:* E2E-01 (partial — build/push half).
**Acceptance Criteria:**
- [ ] The pushed image carries correct OCI labels and registry permissions `[R-24]`
- [ ] A cosign signature and syft SBOM are attached to the digest `[R-24]`
- [ ] Coverage is reported as an artifact regardless of repo gates (DM-06 completeness signal)

#### Story 2.2: Throwaway-CI ring (E2E-01) (#967)
**Wave:** P2W1
**Dependencies:** 2.1
**Implementation Steps:**
1. Author the throwaway-CI ring job: pull the candidate **by digest**, verify labels/permissions/signature/SBOM, install-from-zero, run smoke, tear down.
2. Fail the digest on any verification or smoke failure.
**Test Procedures:** *Integration/E2E Coverage:* E2E-01 (runnable).
**Acceptance Criteria:**
- [ ] E2E-01 tests the registry artifact by digest, never a local build `[R-23]`
- [ ] Labels, permissions, signature, and SBOM are verified before smoke `[R-24]`
- [ ] A red smoke blocks the digest from promotion `[R-05, R-23]`

#### Story 2.3: Mechanical promotion gate (#968)
**Wave:** P2W2
**Dependencies:** 2.2
**Implementation Steps:**
1. Implement the gate as a conjunctive query over FlightDeck + CI (throwaway-CI green, soak met, zero quarantines, zero open Sev-1).
2. The operator ACK can only fire after the query is green; promotion retags the exact tested digest.
**Test Procedures:** *Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_gate_conjunction` | no code path promotes with any condition red | `tests/contained-workflow/test_gate.py` |

*Integration/E2E Coverage:* E2E-02 (partial).
**Acceptance Criteria:**
- [ ] No code path promotes without all conditions green `[R-07]`
- [ ] The promoted digest equals the digest E2E-01 tested `[R-07, R-23]`

#### Story 2.4: Rolling per-agent adoption (#969)
**Wave:** P2W2
**Dependencies:** 2.3
**Implementation Steps:**
1. Implement `:stable` adoption at container-recreate (never mid-session); per-agent, rolling.
**Test Procedures:** *Integration/E2E Coverage:* E2E-02 (runnable).
**Acceptance Criteria:**
- [ ] A minor/patch `:stable` is adopted at the next container-recreate, not by synchronized flip `[R-08]`
- [ ] Updated and not-yet-updated agents coexist `[R-08, R-18]`

---

### Phase 3: Safety & compatibility

**Goal:** a planted broken `:edge` quarantines losslessly; a schema break trips red-first.

#### Phase 3 Definition of Done
- [ ] The flight surgeon detects hung and looping `:edge` containers from outside `[R-15, R-16]`
- [ ] Quarantine + rollback is lossless `[R-02, R-17]`
- [ ] The compat guard blocks a silent same-major-breaking minor `[R-18, R-19, R-20]`
- [ ] All Phase 3 unit tests pass; E2E-03/IT-05 runnable

#### Story 3.1: Flight surgeon (health probe) (#970)
**Wave:** P3W1
**Dependencies:** 1.1
**Implementation Steps:**
1. Author `scripts/flight-surgeon/` — a host-side watcher reading each `:edge` container's host-backed transcript, correlated with aoe status; stall + loop classifiers; profile-label filter.
**Test Procedures:** *Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_stall_and_loop` | classifies flat and repetitive transcripts correctly | `tests/contained-workflow/test_surgeon.py` |

*Integration/E2E Coverage:* MV-04, MV-06 documented.
**Acceptance Criteria:**
- [ ] The probe detects a stall by reading the transcript directly, without the container's kit `[R-15]`
- [ ] `running` + flat-for-N-min and loop signals both classify broken `[R-16]`
- [ ] dev-mode containers are excluded from quarantine `[R-22]`

#### Story 3.2: Quarantine + lossless rollback (#971)
**Wave:** P3W1
**Dependencies:** 3.1, 2.4
**Implementation Steps:**
1. Implement quarantine: stop → `docker rm` → recreate on `:stable`; assert durable state (host-backed) intact.
**Test Procedures:** *Integration/E2E Coverage:* E2E-03 (runnable).
**Acceptance Criteria:**
- [ ] A planted broken `:edge` is quarantined and recreated on `:stable` with zero work lost `[R-02, R-17]`
- [ ] MV-05 documented and executed `[R-17]`

#### Story 3.3: SemVer compat contract + namespace (#972)
**Wave:** P3W2
**Dependencies:** 1.3
**Implementation Steps:**
1. Implement the major-partitioned state namespace `~/.oaw/state/<major>/`; document the additive+forward-tolerant within-major rule.
**Test Procedures:** *Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_namespace_partition` | v-N and v-M states are isolated | `tests/contained-workflow/test_compat.py` |

*Integration/E2E Coverage:* IT-05 (partial).
**Acceptance Criteria:**
- [ ] Same-major agents interoperate; within-major changes are additive/forward-tolerant `[R-18]`
- [ ] Mixing majors is isolated, not corrupting `[R-20]`

#### Story 3.4: Mechanical compat-break guard (#973)
**Wave:** P3W2
**Dependencies:** 3.3
**Implementation Steps:**
1. Version the shared-state schema; implement the guard that trips on a same-major-breaking change and forces a major bump.
**Test Procedures:** *Integration/E2E Coverage:* IT-05 (runnable, red-first).
**Acceptance Criteria:**
- [ ] A deliberate within-major schema break trips the guard (shown red-first) `[R-19]`
- [ ] The guard blocks a silent minor ship of a breaking change `[R-19]`

---

### Phase 4: Profiles, dogfood & docs

**Goal:** OaW team dogfooding on `:edge`; all deliverables produced; VRTM complete.

#### Phase 4 Definition of Done
- [ ] Profiles enforced; the gate/probe filter on the profile label `[R-21, R-22]`
- [ ] The OaW team soaks `:edge` in the dogfood profile
- [ ] All Deliverables Manifest rows delivered; VRTM complete
- [ ] All MV-01..MV-07 executed and recorded (or explicitly deferred)

#### Story 4.1: Dev-mode vs dogfood profiles + label filtering (#974)
**Wave:** P4W1
**Dependencies:** 2.3, 3.1
**Implementation Steps:**
1. Implement the two profiles (overlay ON/OFF) and the profile label; make the gate and surgeon filter on it.
**Test Procedures:** *Unit Tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_profile_filter` | dev-mode telemetry excluded from soak/quarantine | `tests/contained-workflow/test_profiles.py` |

*Integration/E2E Coverage:* advances E2E-02.
**Acceptance Criteria:**
- [ ] Two profiles exist; dev-mode has the overlay ON and is labeled non-candidate `[R-21]`
- [ ] The gate and probe filter on the label; dev-mode runs/breakages don't count `[R-22]`

#### Story 4.2: Dogfood cutover (soak) (#975)
**Wave:** P4W2
**Dependencies:** 4.1, 3.2, 3.4
**Implementation Steps:**
1. Cut the OaW dev team onto `:edge` in the dogfood profile; accrue soak in FlightDeck; the flight surgeon watching.
**Test Procedures:** *Integration/E2E Coverage:* E2E-02 (full lifecycle exercised).
**Acceptance Criteria:**
- [ ] The OaW team works on `:edge` in the dogfood profile with the surgeon active `[R-21]`
- [ ] Soak telemetry accrues in FlightDeck; a promotion cycle completes end-to-end `[R-07, R-08]`

#### Story 4.3: Docs + VRTM (closing story) (#976)
**Wave:** P4W2
**Dependencies:** 4.2
Executes all MV procedures, records evidence, completes the VRTM, and delivers the remaining docs.
**Implementation Steps:**
1. Author `docs/contained-workflow/ops-runbook.md` (DM-09); finalize `manual-verification.md` (DM-10).
2. Execute each MV-01..MV-07; record pass/fail with evidence; open bug issues for failures.
3. Complete Appendix V (VRTM) with final status for every requirement.
**Test Procedures:** *Integration/E2E Coverage:* all MV items executed and recorded.
**Acceptance Criteria:**
- [ ] Every MV-01..MV-07 executed and recorded, or explicitly deferred with rationale `[R-01..R-24 as mapped]`
- [ ] Appendix V VRTM complete with a Status for every requirement
- [ ] DM-01, DM-08, DM-09, DM-10 delivered `[R-05]`

---

## 9. Appendices

### Appendix A: Design source
The authoritative design rationale is `docs/contained-workflow-SKETCHBOOK.md` (merged #958), including the proven/asserted/unproven Verified ledger and the decisions D1–D10 this Dev Spec formalizes. Where this Dev Spec and the sketchbook differ, this Dev Spec governs.

### Appendix V: Verification Requirements Traceability Matrix (VRTM)

**Deliverable DM-08.** Completed by the closing story (4.3, #976), 2026-07-23. Status
for every requirement below.

**Status legend.**
- **Verified** — the requirement's verification item(s) are green: a unit/integration/e2e
  oracle passed (in this closing story's run or in the landed owning story's CI).
- **Verified · live-MV deferred** — the automated oracle discharges the requirement's
  mechanically-testable core; the irreducibly-live-`aoe`-session leg of the paired MV is
  explicitly deferred to an operator field-run (`docs/contained-workflow/manual-verification.md`,
  §7 DoD permits an explicit deferral). No requirement rests **only** on a deferred MV.
- **Verified (shape) · semantic-break deferred** — R-19 only: the shape-break guard is
  proven red-first; mechanically detecting a *semantic* break (a field whose meaning
  changes without its shape changing) is the §5.N#4 open item.

Evidence detail: the oracle names are in the Verification Item column; MV execution and the
deferred halves are recorded in `docs/contained-workflow/manual-verification.md` (DM-10, §
"Execution disposition"); registry-artifact verification is `deployment-verification.md`
(DM-12). Live-registry E2E-01/E2E-02 self-skip in a credential-less worktree and run green
in the image-build CI on the owning-story merges (P2W1/P2W2 promote commits).

| Req ID | Requirement (short) | Source | Verification Item | Verification Method | Status |
|--------|--------------------|--------|-------------------|---------------------|--------|
| R-01 | stateless / host-backed | Story 1.3 / §6 | IT-03, MV-02 | integration / manual | Verified · live-MV deferred (MV-02) |
| R-02 | recreate lossless | Story 3.2 / §6 | E2E-03, MV-05 | e2e / manual | Verified (E2E-03 oracle green) · live-MV deferred (MV-05) |
| R-03 | sandbox-scoped memory source | Story 1.3 | IT-03, MV-02 | integration / manual | Verified (resolver oracle + IT-03) · live-MV deferred (MV-02) |
| R-04 | uid-1000 ownership | Story 1.2 | IT-04, MV-01 | integration / manual | Verified (IT-04 oracle green) · live-MV deferred (MV-01) |
| R-05 | image = release | Story 1.1 / 2.2 | E2E-01, MV-03 | e2e / manual | Verified (MV-03 egress executed; image oracle green; E2E-01 in CI) |
| R-06 | versioned baked | Story 1.1 / 1.4 | IT-01, IT-03 | integration | Verified |
| R-07 | mechanical promotion gate | Story 2.3 | E2E-02, test_gate_conjunction | e2e / unit | **Partial** — gate conjunction unit-verified (test_gate_conjunction green); E2E-02 live cycle NOT run, and the "soak met" leg does not yet auto-accrue (surgeon→`soak_ledger` unwired, **#1008**) — deferred to operator field-run |
| R-08 | rolling adoption | Story 2.4 | E2E-02 | e2e | **Partial** — adoption oracle green (unit); E2E-02 live cycle deferred to operator field-run (auto-soak accrual unwired, **#1008**) |
| R-09 | MCP additive scoping | Story 1.3 | IT-03 | integration | Verified (additive-scoping half) · **kit-MCP-baking half NOT delivered** — the image still `./install --no-mcps` (Dockerfile); baking the kit's own registrations at stable image paths rides with the CI build (#966), still open |
| R-10 | binaries in-container | Story 1.3 / 1.4 | IT-01, IT-03 | integration | Verified |
| R-11 | declarative toolbox | Story 1.3 | IT-03 | integration | Verified |
| R-12 | secrets never baked | Story 1.5 | IT-02 | integration | Verified (IT-02 oracle green) |
| R-13 | secret liveness | Story 1.5 | IT-02, MV-07 | integration / manual | Verified (IT-02 oracle green) · live-MV deferred (MV-07) |
| R-14 | fail-loud missing secret | Story 1.4 | test_bootstrap_failloud | unit | Verified |
| R-15 | host-side probe (kit-independent) | Story 3.1 / §7 DoD | E2E-03, §7 DoD, test_stall_and_loop, MV-06 | e2e / manual / unit | Verified (detection oracles green) · live-MV deferred (MV-04, MV-06 — fail-safe, §5.N#2/#5) |
| R-16 | stall/loop classify | Story 3.1 | test_stall_and_loop | unit | Verified |
| R-17 | quarantine lossless | Story 3.2 | E2E-03, MV-05 | e2e / manual | Verified (E2E-03 oracle green) · live-MV deferred (MV-05) |
| R-18 | same-major interop | Story 3.3 | IT-05 | integration | Verified |
| R-19 | compat-break guard (shape break; semantic-break enforcement open, §5.N#4) | Story 3.4 | IT-05 (red-first) | integration | Verified (shape) · semantic-break deferred (§5.N#4) |
| R-20 | namespace partition | Story 3.3 | test_namespace_partition, IT-05 | unit / integration | Verified |
| R-21 | two profiles | Story 4.1 | test_profile_filter | unit | Verified |
| R-22 | gate/probe profile filter | Story 4.1 / 3.1 | test_profile_filter | unit | Verified |
| R-23 | digest continuity | Story 2.2 / 2.3 | E2E-01 | e2e | Verified (E2E-01 by-digest in CI; deployment-verification.md §5) |
| R-24 | provenance verified | Story 2.1 / 2.2 | E2E-01, test_oci_labels | e2e / unit | Verified (test_oci_labels green; E2E-01 + deployment-verification.md §1–4) |
