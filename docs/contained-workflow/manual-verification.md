# Manual verification procedures — contained workflow

Deliverable **DM-10** (Plan #959, Dev Spec §5.A / §6.4). Procedures that need a
real container + host and cannot run in the automated lane. Each must be
**executed AND recorded** — a silent skip is not a pass (Dev Spec §7 DoD).

The full set is MV-01..MV-07 (Dev Spec §6.4); they land with the stories that
own them and are all executed and recorded in the closing story (4.3, #976).

| ID | Procedure | Requirement | Added in |
|----|-----------|-------------|----------|
| MV-01 | Files land `bakerb`-owned under the me-ful config (isolated profile) | R-04 | Story 1.2 (#962) |
| MV-02 | Live `~/.claude` not exposed under the full custom mount set | R-01, R-03 | Story 1.3+ |
| MV-03 | Network egress reaches scream-hole / discord / github from inside | R-05 | later |
| MV-04 | `aoe send` reaches into a running container (control-plane ingress) | R-15 | Story 3.1 (#970) |
| MV-05 | A broken container quarantines and recreates on `:stable`, zero loss | R-02, R-17 | Story 3.2 (#971) |
| MV-06 | A wedged/OOM-killed `claude` still flushed its transcript | R-15 | Story 3.1 (#970) |
| MV-07 | A secret added mid-session is usable with no container restart | R-13 | Story 1.5 (#965) |

## Execution disposition — closing story 4.3 (#976)

Executed **2026-07-23** in the wave P4W2 flight lane against the locally-built
`oakandwave-workflow:edge` (image ID `sha256:2b75626d6365`). The flight lane has
**docker + the real image** but **no live `aoe` session and no operator** (no
interactive hard-kill, no live ghcr registry). Each MV therefore has two halves:
the **mechanically-verifiable core**, discharged here by the docker-gated
integration/e2e oracle (run green — see the per-MV result logs), and the
**irreducibly-live-`aoe`-session portion**, which needs an operator field-run and
is **explicitly deferred with rationale** (Dev Spec §7 DoD permits an explicit
deferral; a silent skip does not). No MV **failed**; nothing needed a bug issue.

| ID | Disposition | Core executed here (oracle, green) | Live-session portion — deferred |
|----|-------------|------------------------------------|----------------------------------|
| MV-01 | Core PASS · live-half deferred | `test_uid_config`, `test_bind_mount_write_is_host_owned` (IT-04) | `aoe --sandbox` launches with no `--user` override |
| MV-02 | Core PASS · live-half deferred | `test_mounts.py` (memory source sandbox-scoped; live-fleet source rejected) | isolation under the full custom mount set in a live session (§5.N#3) |
| MV-03 | **PASS — fully executed** | docker egress probe: `api.github.com`→200, `discord.com`→200 from inside the image | none (scream-hole is an internal service, not reachable from the flight network — noted, not a blocker) |
| MV-04 | Deferred | `test_surgeon.py` (detection reads transcript, needs no ingress) | `aoe send` host→container ingress — the §5.N#5 open seam |
| MV-05 | Core PASS · live-half deferred | `test_e2e03_real_rollback_preserves_on_disk_work` (E2E-03: real stop/`rm`/recreate, on-disk work survives) | the `aoe`-session trigger path (surgeon → quarantine on a live session) |
| MV-06 | Deferred (fail-safe covered) | `test_read_transcript_tolerates_a_truncated_tail` | a real hard-kill/OOM of `claude` in a live session |
| MV-07 | Core PASS · live-half deferred | `test_secrets_readonly` (IT-02: ro enforced, host-added file visible in a real container) | the mid-session add through a live `aoe` path-consumer |

**Why the deferrals are safe.** MV-04/MV-06 map to §5.N **open probes** the Dev
Spec already flags as unproven, and the surgeon is **fail-safe** against both: it
reads the transcript from outside (never needs `aoe send`), and a lost last-turn
makes it detect a stall *earlier*, never miss one (§5.N#2). Operator field
experience (many hard-kills, never a flush problem) backs MV-06. The deferred
halves are the *live-`aoe`* leg of guarantees whose *mechanics* are proven green
above — an operator replays them on a real fleet session and appends a row to the
matching result log.

---

## MV-01 — Files land `bakerb`-owned under the me-ful config `[R-04]`

**Goal.** Prove that a file written to a bind-mount **from inside** the container
is owned by the host user (`bakerb`, uid 1000), not root — the me-ful ownership
outcome (Dev Spec §5.1, §5.N#1).

**Why manual.** The static config oracle
(`tests/contained-workflow/test_ownership.py::test_uid_config`) proves the
profile is correct and aoe-loadable; the docker-gated integration oracle
(`::test_bind_mount_write_is_host_owned`, IT-04) proves the **image** runs
non-root. This procedure proves the remaining **aoe** guarantee: that
`aoe --sandbox` launches the image *without a `--user` override*, so the running
session is uid-1000 and its bind-mount writes are host-owned. That needs a live
aoe session and cannot run in the pytest lane.

### Preconditions

- **aoe 1.13.0**, **rootful docker** (no userns remap) — `docker info` shows no
  `userns` remap; `id -u` on the host is `1000` (`bakerb`).
- Image built locally:
  `make -C containers/oakandwave-workflow build` → `oakandwave-workflow:edge`.
- The me-ful profile config:
  `containers/oakandwave-workflow/sandbox-profile.toml`.

### Procedure

1. **Create an ISOLATED aoe profile** — never edit the fleet's global config
   (`~/.config/agent-of-empires/config.toml`):

   ```bash
   aoe profile create meful-test
   ```

2. **Install the me-ful config** into that profile only:

   ```bash
   install -m 600 containers/oakandwave-workflow/sandbox-profile.toml \
     ~/.config/agent-of-empires/profiles/meful-test/config.toml
   ```

3. **Prepare a host workspace** to write into (the workspace is host-backed —
   the bind-mount under test):

   ```bash
   mkdir -p /tmp/meful-ws && cd /tmp/meful-ws && git init -q
   ```

4. **Launch a sandbox session on the image** in the isolated profile:

   ```bash
   aoe -p meful-test add --sandbox --sandbox-image oakandwave-workflow:edge \
     --launch /tmp/meful-ws
   ```

   **Confirm** the launch does **not** error with an aoe config-parse /
   `unknown field` message. This checks the profile loads cleanly. (Under aoe
   1.13.0 the `uid`/`user`/`home_dir` keys are declarative; if a future aoe
   rejects them, the fix is to drop those three keys from `[sandbox]` — they are
   inert on 1.13.0 and the uid is delivered by the image `USER` regardless.)

5. **Confirm the runtime identity** inside the container (attach the session):

   ```bash
   id -u    # expect: 1000
   id -un   # expect: ubuntu
   ```

6. **Write a file to the host-backed bind-mount** from inside:

   ```bash
   echo meful > /tmp/meful-ws/meful-probe.txt
   ```

7. **Check ownership on the HOST** (a separate host shell, not the container):

   ```bash
   stat -c '%U %u %G %g  %n' /tmp/meful-ws/meful-probe.txt
   ```

   **EXPECT:** `bakerb 1000 …` — uid `1000`, host user. A `root`/`0` result is a
   **FAIL**.

8. **Record** the result in the log below: date, operator, image digest
   (`docker inspect --format '{{index .RepoDigests 0}}' oakandwave-workflow:edge`
   once pushed, else the local image ID), the `id -u` value, the `stat` output,
   and PASS/FAIL.

### Cleanup

```bash
aoe -p meful-test remove <session-id>   # or delete via the TUI
aoe profile delete meful-test
rm -rf /tmp/meful-ws
```

### Failure handling

If writes land uid-`0`/root-owned:

- Capture the container's effective user and the aoe launch args:
  ```bash
  docker inspect --format '{{.Config.User}}' <container-id>
  docker inspect --format '{{json .Args}}' <container-id>
  ```
- A root result means aoe is launching with a `--user 0` override (or the base
  entrypoint re-escalates). The me-ful lever in aoe 1.13.0 is the **image
  `USER`**; a root outcome despite `USER ubuntu` in the image is a bug — open a
  bug against Story 1.2 (#962) with the `docker inspect` evidence.

### Result log

| Date | Operator | Image digest / ID | `id -u` | `stat` result | PASS/FAIL | Notes |
|------|----------|-------------------|---------|---------------|-----------|-------|
| 2026-07-23 | flight P4W2 (#976) | `sha256:2b75626d6365` | 1000 (image `USER ubuntu`) | uid-1000-owned (oracle) | **PASS (core)** | Image half via `test_ownership.py::test_uid_config` + `::test_bind_mount_write_is_host_owned` (IT-04) green against the real image — a container-written bind-mount file is uid-1000/host-owned, not root. aoe-half (no `--user` override) deferred to an operator field-run. |
| _pending_ | operator | _pending_ | | | _deferred_ | Live-`aoe`-session half: confirm `aoe -p meful-test add --sandbox` launches uid-1000 with no `--user` override; append the `stat` result. |

---

## MV-07 — A secret added mid-session is usable with no container restart `[R-13]`

**Goal.** Prove that a secret the host adds to `~/.secrets` **after** a session
started is usable by a **newly-spawned command inside the running container**,
with **no container restart** — the mid-session liveness of the read-only secrets
mount (Dev Spec §5.5; architecture §3.5).

**Why manual.** The docker-gated integration oracle
(`tests/contained-workflow/test_secrets.py::test_secrets_readonly`, IT-02) proves
the bind-mount is ro and that a host-added file is visible via `docker exec` in a
bare container. This procedure proves the same liveness through the **real aoe
sandbox session** an agent runs in, and through a **path-modality consumer** the
way the kit actually reads a secret — the end-user-visible outcome. It needs a
live aoe session, so it cannot run in the pytest lane.

### Preconditions

- **aoe 1.13.0**, **rootful docker** — as MV-01.
- Image built locally:
  `make -C containers/oakandwave-workflow build` → `oakandwave-workflow:edge`.
- A host `~/.secrets` dir that will be bind-mounted ro (the me-ful profile /
  `20-secrets.toml` wires `~/.secrets` → `/home/ubuntu/.secrets`). For an
  isolated run, point `OAW_SECRETS_DIR` (or the profile's `extra_volumes`) at a
  throwaway dir so you never touch real secrets.

### Procedure

1. **Seed one secret present at launch** in the host secrets dir:

   ```bash
   mkdir -p /tmp/meful-secrets
   printf 'boot-value\n' > /tmp/meful-secrets/AT_BOOT
   ```

2. **Launch a sandbox session** with that dir bind-mounted ro at the secrets
   target (isolated profile, as MV-01; add the volume to the profile's
   `extra_volumes` or pass it through):

   ```bash
   aoe -p meful-test add --sandbox --sandbox-image oakandwave-workflow:edge \
     --launch /tmp/meful-ws
   # ensure -v /tmp/meful-secrets:/home/ubuntu/.secrets:ro is in effect
   ```

3. **Confirm the at-boot secret is readable** inside the running container
   (attach the session):

   ```bash
   cat /home/ubuntu/.secrets/AT_BOOT      # expect: boot-value
   ```

4. **Confirm the mount is read-only** (R-12) — an in-container write must FAIL:

   ```bash
   echo x > /home/ubuntu/.secrets/should_fail   # expect: Read-only file system
   ```

5. **Add a NEW secret ON THE HOST**, mid-session, with the container still
   running (a separate host shell):

   ```bash
   printf 'live-add\n' > /tmp/meful-secrets/MID_SESSION
   ```

6. **Spawn a NEW command inside the SAME running container** (do NOT restart it)
   and read the just-added secret — this is the liveness assertion:

   ```bash
   cat /home/ubuntu/.secrets/MID_SESSION   # expect: live-add
   ```

   **EXPECT:** `live-add` — the host-added file is live with no restart. A
   "No such file or directory" is a **FAIL** (R-13 liveness violated).

7. **(Optional) confirm the env-modality caveat.** If the mount carries a `.env`,
   note that a value *added to `.env` after boot* is **not** seen by env-var
   consumers until a re-source (architecture §3.5 consumer split) — this is
   expected, not a failure. The R-13 liveness guarantee is for **path-modality**
   (loose-file) consumers, which is what step 6 exercises.

8. **Record** the result in the log below: date, operator, image digest/ID, the
   step-3 read, the step-4 write-rejection, the step-6 read, and PASS/FAIL.

### Cleanup

```bash
aoe -p meful-test remove <session-id>
rm -rf /tmp/meful-secrets
```

### Failure handling

- **Step 6 shows the file missing.** The bind-mount is not the live host dir —
  inspect the mount: `docker inspect --format '{{json .Mounts}}' <container-id>`.
  A `volume`/copy source instead of a host `bind` breaks liveness; a stale image
  path or an over-eager copy in the bootstrap would too. Open a bug against
  Story 1.5 (#965) with the `docker inspect` evidence.
- **Step 4 write SUCCEEDS.** The mount is not ro — R-12 violated. Check the
  fragment (`20-secrets.toml` must be `mode = "ro"`; the resolver rejects rw) and
  the effective `-v …:ro` flag.

### Result log

| Date | Operator | Image digest / ID | step-3 read | step-4 write | step-6 read | PASS/FAIL | Notes |
|------|----------|-------------------|-------------|--------------|-------------|-----------|-------|
| 2026-07-23 | flight P4W2 (#976) | `sha256:2b75626d6365` | readable (oracle) | rejected `Read-only file system` (oracle) | host-added file visible (oracle) | **PASS (core)** | IT-02 oracle `test_secrets.py::test_secrets_readonly` green against a real container: the `~/.secrets` bind is ro (in-container write rejected, R-12) and a host-added file is visible via `docker exec` with no restart (R-13). Live-`aoe`-session path-consumer half deferred. |
| _pending_ | operator | _pending_ | | | | _deferred_ | Live-`aoe`-session half: read a mid-session-added secret through a real aoe session's path-consumer; append the step-6 read. |

---

## MV-04 — `aoe send` reaches into a running container (control-plane ingress) `[R-15]`

**Goal.** Prove the host can reach a **control-plane message** into a *running*
sandbox session — `aoe send <session> "<text>"` is delivered to the agent inside
the container. This is the ingress the flight surgeon's remediation and the
quarantine step (Story 3.2, #971) ride: the probe *detects* from outside by
reading the transcript (R-15, no ingress needed), but nudging or stopping a
wedged agent needs a proven host→container control path (Dev Spec TC-7 / §5.N#5 —
the AoE bootstrap/ingress seam is UNPROVEN).

**Why manual.** The surgeon's *detection* is unit-proven
(`tests/contained-workflow/test_surgeon.py`) and reads only the host-backed
transcript — it never sends into the container. But whether `aoe send` traverses
the host↔container boundary at all is a live aoe + docker property (no automated
harness can stand up a real sandbox session in the pytest lane).

### Preconditions

- **aoe 1.13.0**, **rootful docker** — as MV-01.
- Image built locally:
  `make -C containers/oakandwave-workflow build` → `oakandwave-workflow:edge`.
- An isolated aoe profile (as MV-01) so no fleet session is touched.

### Procedure

1. **Launch a sandbox session** on the image in the isolated profile:

   ```bash
   aoe -p meful-test add --sandbox --sandbox-image oakandwave-workflow:edge \
     --launch /tmp/meful-ws
   ```

2. **Note the session id** and confirm it is `running` (or `idle`, i.e. up):

   ```bash
   aoe -p meful-test list --json | jq -r '.[] | "\(.id)\t\(.title)"'
   aoe -p meful-test status -v
   ```

3. **Send a control-plane message** from the host into that session:

   ```bash
   aoe -p meful-test send <session-id> "flight-surgeon ping: reply PONG"
   ```

4. **Confirm the message was delivered** — the agent received the text (visible
   in the attached TUI, or as a new user-turn in the session's **host-backed
   transcript** the surgeon reads):

   ```bash
   # from the host, tail the session's host-backed .jsonl and look for the ping
   python3 scripts/flight-surgeon/surgeon.py --live \
     --transcripts-root ~/.oaw/state/$OAW_MAJOR/transcripts   # locates the transcript path
   ```

   **EXPECT:** the sent text appears as a new user turn in the transcript (and/or
   the agent reacts). A "session not found" / no-delivery is a **FAIL** — the
   host→container control path is not available, and Story 3.2's active
   remediation must fall back to a docker-level stop (`docker stop <cid>`) rather
   than an in-band `aoe send`.

5. **Record** the result: date, operator, image digest/ID, the send command's
   exit, whether the text landed in the transcript, and PASS/FAIL.

### Cleanup

```bash
aoe -p meful-test remove <session-id>
```

### Failure handling

- **`aoe send` errors or the text never lands.** Capture the container id and
  aoe's log (`aoe logs`), and confirm the container is up
  (`docker inspect --format '{{.State.Status}}' <cid>`). A missing ingress path is
  the §5.N#5 seam resolving to "no in-band ingress" — record it and route Story
  3.2 to the docker-level stop path. Open a note against Story 3.2 (#971).

### Result log

| Date | Operator | Image digest / ID | `aoe send` exit | landed in transcript? | PASS/FAIL | Notes |
|------|----------|-------------------|-----------------|-----------------------|-----------|-------|
| 2026-07-23 | flight P4W2 (#976) | `sha256:2b75626d6365` | n/a | n/a | **DEFERRED** | `aoe send` host→container ingress is the §5.N#5 open seam — needs a live aoe session (unavailable in the flight lane). R-15 *detection* (what the surgeon actually rides — it reads the transcript, never sends) is unit-proven: `test_surgeon.py` green. Ingress is Story-3.2 remediation infra; the wrapper already has a `docker stop` fallback if the seam resolves to "no in-band ingress". |
| _pending_ | operator | _pending_ | | | _deferred_ | Live-`aoe`-session run: `aoe -p meful-test send <sid> "…"`; confirm the text lands as a user turn in the host-backed transcript. |

---

## MV-06 — A wedged/OOM-killed `claude` still flushed its transcript `[R-15]`

**Goal.** Prove the surgeon's core assumption: when a `claude` process is
**hard-killed** (SIGKILL / OOM) inside a running container, the host-backed
`.jsonl` transcript still reflects work up to (near) the failure boundary — so the
host-side probe can read it and classify the container. This is the **F1
transcript-flush keystone** (Dev Spec §5.N#2).

**Why manual.** It needs a real container, a real running agent, and a real
hard-kill; the transcript-flush behaviour of the harness under SIGKILL cannot be
exercised in the pytest lane. The surgeon's *parsing* of a truncated tail **is**
unit-proven (`test_read_transcript_tolerates_a_truncated_tail`) — this procedure
proves the upstream fact that a hard-kill leaves a *usable* transcript at all.

**Fail-safe note.** The surgeon is **fail-safe** with respect to this probe: if a
hard-kill loses the last turn, the transcript simply stops growing *earlier*, so
the probe detects the stall **sooner**, never misses it. A lost last-turn cannot
turn a broken container into a "healthy" verdict. Operator field experience (many
hard-kills, never a flush problem) indicates this is likely-ok; this procedure
confirms it and records the boundary behaviour.

### Preconditions

- **aoe 1.13.0**, **rootful docker** — as MV-01.
- Image built locally:
  `make -C containers/oakandwave-workflow build` → `oakandwave-workflow:edge`.
- An isolated aoe profile (as MV-01).

### Procedure

1. **Launch a sandbox session** on the image (isolated profile) and give the agent
   a small task so the transcript is actively growing:

   ```bash
   aoe -p meful-test add --sandbox --sandbox-image oakandwave-workflow:edge \
     --launch /tmp/meful-ws
   aoe -p meful-test send <session-id> "run: for i in 1 2 3; do echo $i; sleep 2; done"
   ```

2. **Confirm the transcript is growing** on the host (record its size/last line):

   ```bash
   python3 scripts/flight-surgeon/surgeon.py --live --transcripts-root ~/.oaw/state/$OAW_MAJOR/transcripts
   # note the resolved transcript path P from the summary, then:
   wc -l "$P"; tail -1 "$P"
   ```

3. **Hard-kill the in-container `claude` process** (SIGKILL — simulate a wedge/OOM,
   NOT a graceful stop):

   ```bash
   cid=$(docker ps --filter name=<session> --format '{{.ID}}')
   docker exec "$cid" bash -lc 'pkill -9 -f claude || kill -9 $(pgrep -o claude)'
   # (or, to simulate OOM at the container level: docker kill --signal=KILL "$cid")
   ```

4. **Read the transcript from the HOST** (the container may be dead) and confirm
   it retained work up to near the kill boundary:

   ```bash
   wc -l "$P"; tail -3 "$P"
   ```

   **EXPECT:** the transcript still parses and reflects the work performed before
   the kill (the last one or two turns may be absent — that is acceptable and
   fail-safe). A **completely empty or unparseable** transcript after real work
   was done is a **FAIL** (the flush keystone does not hold; escalate).

5. **Confirm the surgeon classifies it** — with the process dead the session goes
   `stopped`/`error`, or if aoe still reports `running` the flat transcript trips
   the stall after the threshold:

   ```bash
   python3 scripts/flight-surgeon/surgeon.py --live --transcripts-root ~/.oaw/state/$OAW_MAJOR/transcripts
   ```

   **EXPECT:** the container is not reported healthy-and-progressing — either a
   non-running status, or (if still `running`) a stall once N minutes elapse.

6. **Record** the result: date, operator, image digest/ID, the pre-kill and
   post-kill line counts, whether the transcript remained parseable, the surgeon's
   verdict, and PASS/FAIL.

### Cleanup

```bash
aoe -p meful-test remove <session-id>
```

### Failure handling

- **Transcript empty/unparseable after a hard-kill.** The flush keystone
  (§5.N#2) does not hold for this harness/kill mode — capture the kill signal, the
  container's last logs (`docker logs <cid>`), and the transcript bytes, and open a
  bug against Story 3.1 (#970). The surgeon's stall path still fires (the
  transcript stops growing), so detection is not lost — but the boundary evidence
  is, which this procedure exists to catch.

### Result log

| Date | Operator | Image digest / ID | pre-kill lines | post-kill lines | parseable? | surgeon verdict | PASS/FAIL |
|------|----------|-------------------|----------------|-----------------|------------|-----------------|-----------|
| 2026-07-23 | flight P4W2 (#976) | `sha256:2b75626d6365` | n/a | n/a | yes (oracle) | stall/not-healthy (oracle) | **DEFERRED (fail-safe)** | Real hard-kill/OOM of `claude` in a live session needs an operator. The surgeon's *parsing* of a truncated tail is unit-proven: `test_surgeon.py::test_read_transcript_tolerates_a_truncated_tail` green. Fail-safe: a lost last-turn makes the stall fire *earlier*, never a false-healthy (§5.N#2); operator field experience (many hard-kills, never a flush problem) backs the keystone. |
| _pending_ | operator | _pending_ | | | | | Live run: hard-kill `claude` mid-task, confirm the host-backed transcript still parses and the surgeon does not report healthy-and-progressing. |

---

## MV-05 — A broken container quarantines and recreates on `:stable`, zero loss `[R-02, R-17]`

**Goal.** Prove the whole quarantine lifecycle end-to-end on a **real** container:
a broken `:edge` dogfood container is detected by the flight surgeon, quarantined
(stop → `docker rm` → recreate on `:stable`), and comes back with **zero durable
work lost** — the lossless-rollback keystone (Dev Spec §4.6; R-02/R-17).

**Why manual.** The lossless *mechanics* are unit-proven in the stock pytest lane
(`tests/contained-workflow/test_quarantine.py`) — including the docker-gated
`test_e2e03_real_rollback_preserves_on_disk_work`, which plants a real container
with a host-backed bind holding work, runs the real stop/`rm`/recreate, and asserts
the on-disk file survives. This procedure proves the same through the **real aoe
sandbox session** an agent runs in and the **real surgeon → quarantine wrapper**
trigger path: that `aoe` recreates the session on `:stable`, that host-backed
memory/workspace survive the `docker rm`, and that the quarantined `:edge` digest is
held from promotion. It needs a live aoe session + the `:edge`/`:stable` image pair,
so it cannot run in the pytest lane.

### Preconditions

- **aoe 1.13.0**, **rootful docker** — as MV-01.
- An `:edge` and a `:stable` image (distinct digests). For an isolated run, build
  the image and tag two stand-ins:
  `make -C containers/oakandwave-workflow build` then
  `docker tag oakandwave-workflow:edge oaw-mv05:edge` and
  `docker tag oakandwave-workflow:edge oaw-mv05:stable`.
- An isolated aoe profile (as MV-01) so no fleet session is touched.
- The flight surgeon (`scripts/flight-surgeon/surgeon.py`) and the quarantine
  wrapper (`scripts/ci/quarantine-container.sh`) present.

### Procedure

1. **Launch a dogfood sandbox session on `:edge`** in the isolated profile, with a
   host-backed workspace (the durable mount under test):

   ```bash
   mkdir -p /tmp/mv05-ws && cd /tmp/mv05-ws && git init -q
   aoe -p meful-test add --sandbox --sandbox-image oaw-mv05:edge --launch /tmp/mv05-ws
   ```

2. **Do real work that lands on the host-backed mount** — write a durable artifact
   from inside the session (this is the "work" that must survive):

   ```bash
   echo 'zero-work-lost' > /tmp/mv05-ws/durable-work.txt
   ```

   Confirm on the **host**: `cat /tmp/mv05-ws/durable-work.txt` → `zero-work-lost`.

3. **Plant the break.** Wedge the agent so the surgeon classifies it broken — e.g.
   drive it into a tool loop, or hard-kill `claude` inside the container while aoe
   still reports `running` (as MV-06 step 3). The transcript stops progressing.

4. **Confirm the surgeon flags it** (host-side, reading the host-backed transcript —
   no container access):

   ```bash
   python3 scripts/flight-surgeon/surgeon.py --live \
     --transcripts-root ~/.oaw/state/$OAW_MAJOR/transcripts --fail-on-quarantine ; echo "exit=$?"
   ```

   **EXPECT:** the container is reported `should_quarantine=true` and the exit is
   `3`. A dogfood breakage must flag; a `dev-mode` one would not (R-22).

5. **Note the container id** and **run the quarantine** on the surgeon's verdict:

   ```bash
   cid=$(docker ps --filter name=<session> --format '{{.ID}}')
   CONTAINER_ID="$cid" SHOULD_QUARANTINE=true \
     OAW_STABLE_RESOLVED_REF=oaw-mv05:stable \
     scripts/ci/quarantine-container.sh
   ```

   The wrapper prints the lossless plan (`N host-backed mount(s) preserved`), then
   stops + `docker rm`s the broken container and recreates on `:stable`. It appends
   a quarantine record to `~/.oaw/quarantine/ledger.jsonl`.

6. **Confirm zero work lost** on the **host** — the durable artifact survived the
   `docker rm` + recreate:

   ```bash
   cat /tmp/mv05-ws/durable-work.txt   # expect: zero-work-lost
   ```

   **EXPECT:** `zero-work-lost` — unchanged. A missing/empty file is a **FAIL**
   (R-02 violated — the rollback was not lossless).

7. **Confirm the recreate is on `:stable`** and re-attached the host source:

   ```bash
   new=$(docker ps --filter name=<session> --format '{{.ID}}')
   docker inspect --format '{{.Config.Image}}' "$new"      # expect: oaw-mv05:stable
   docker inspect --format '{{json .Mounts}}' "$new"       # /tmp/mv05-ws still bind-mounted
   ```

8. **Confirm the bad `:edge` digest is held from promotion** — the ledger carries
   the quarantine so the gate's zero-quarantines condition (R-07) trips:

   ```bash
   tail -1 ~/.oaw/quarantine/ledger.jsonl   # {"event":"quarantine","held_digest":"…edge…",…}
   ```

9. **Record** the result in the log below: date, operator, `:edge`/`:stable`
   digests, the surgeon verdict, the step-6 file content, the step-7 image, and
   PASS/FAIL.

### Cleanup

```bash
aoe -p meful-test remove <session-id>
docker rmi oaw-mv05:edge oaw-mv05:stable
rm -rf /tmp/mv05-ws
```

### Failure handling

- **Step 6 file missing/empty.** The durable state was not host-backed, or the
  recreate did not re-attach the source. Inspect the broken container's mounts
  before the run (`docker inspect --format '{{json .Mounts}}' <cid>`): a durable RW
  `volume` (not a `bind`) is the R-01 violation the planner refuses — if the wrapper
  *proceeded*, capture the plan JSON and open a bug against Story 3.2 (#971). If the
  mount was a bind but the file is gone, capture the recreate's `-v` args.
- **Step 4 does not flag.** Confirm the profile label is `dogfood` (a `dev-mode`
  label excludes from quarantine by design, R-22) and that aoe still reports the
  session `running`; a `stopped`/`error` session is a different (non-stall) path.
- **`aoe`-side recreate.** The wrapper recreates via `docker run`; the fleet path
  recreates the aoe **session** on `:stable` (`aoe add --sandbox --sandbox-image
  oaw-mv05:stable`). If the host→container stop seam (MV-04) resolved to "no in-band
  ingress", the wrapper's `docker stop` is the fallback — record which path was used.

### Result log

| Date | Operator | `:edge` / `:stable` digest | surgeon verdict | step-6 content | step-7 image | PASS/FAIL | Notes |
|------|----------|----------------------------|-----------------|----------------|--------------|-----------|-------|
| 2026-07-23 | flight P4W2 (#976) | `sha256:2b75626d6365` (both, tagged stand-ins) | should_quarantine (oracle) | `zero-work-lost` (oracle) | `:stable` (oracle) | **PASS (core)** | E2E-03 oracle `test_quarantine.py::test_e2e03_real_rollback_preserves_on_disk_work` green: plants a real container with host-backed work, runs the real stop/`docker rm`/recreate on `:stable`, and asserts the on-disk artifact survives (R-02/R-17). Live-`aoe`-session trigger path (surgeon→quarantine on a real session) deferred to an operator field-run. |
| _pending_ | operator | _pending_ | | | | _deferred_ | Live run: quarantine a real dogfood `:edge` aoe session and confirm the recreate on `:stable` with zero durable loss. |

---

## MV-02 — Live `~/.claude` not exposed under the full custom mount set `[R-01, R-03]`

**Goal.** Prove that when a container comes up with the **full custom mount
manifest** (the five-layer set of §5.3, memory + secrets + overlay + caches), the
live-fleet `~/.claude` tree is **not** exposed inside it — durable memory reads
and writes land on the sandbox-scoped source `~/.oaw/state/<major>/`, never the
live fleet's `~/.claude/projects/*/memory/` (R-03), and the container filesystem
stays a disposable RTE (R-01).

**Why manual.** The mount **resolver** is unit-proven
(`tests/contained-workflow/test_mounts.py::test_memory_source_scoped` — it rejects
a live-fleet memory source and accepts only a sandbox-scoped one) and IT-03
builds the full mount set in a bare container. This procedure proves the same
**through a live `aoe` sandbox session** with the whole manifest present at once —
the §5.N#3 open probe (the "live `~/.claude` not exposed" result was a single
default-`--sandbox` observation; confirm it holds under the full custom set).

### Preconditions

- **aoe 1.13.0**, **rootful docker** — as MV-01.
- Image built locally; the full mount manifest resolved
  (`containers/oakandwave-workflow/mount_resolver.py` + `mounts.d/`).
- An isolated aoe profile (as MV-01).

### Procedure

1. **Resolve + launch** a sandbox session on the image with the full mount set
   (memory source `~/.oaw/state/<major>/`, ro `~/.secrets`, overlay, caches):

   ```bash
   aoe -p meful-test add --sandbox --sandbox-image oakandwave-workflow:edge \
     --launch /tmp/meful-ws
   ```

2. **Confirm the live-fleet tree is NOT mounted** inside the container:

   ```bash
   docker inspect --format '{{json .Mounts}}' <cid> | jq -r '.[].Source' \
     | grep -F "$HOME/.claude/projects" && echo "EXPOSED (FAIL)" || echo "not exposed (PASS)"
   ```

   **EXPECT:** the live `~/.claude/projects/*/memory/` source appears in **no**
   mount; the only memory source is `~/.oaw/state/<major>/`. A live-fleet source is
   a **FAIL** (R-03 violated).

3. **Confirm durable writes land on the sandbox-scoped source** — write memory
   from inside and confirm it appears under `~/.oaw/state/<major>/` on the host,
   never under `~/.claude`.

4. **Record** the result: date, operator, image ID, the step-2 verdict, and
   PASS/FAIL.

### Failure handling

- **Step 2 shows the live tree.** The resolver was bypassed or a manual `-v`
  leaked the live path. Capture the resolved manifest
  (`mount_resolver.py --emit`) and the container mounts; open a bug against Story
  1.3 (#963).

### Result log

| Date | Operator | Image digest / ID | live tree exposed? | memory source | PASS/FAIL | Notes |
|------|----------|-------------------|--------------------|---------------|-----------|-------|
| 2026-07-23 | flight P4W2 (#976) | `sha256:2b75626d6365` | no (oracle) | `~/.oaw/state/<major>/` (oracle) | **PASS (core)** | Resolver oracle `test_mounts.py::test_memory_source_scoped` green: a live-fleet memory source is rejected, only a sandbox-scoped source resolves (R-03); IT-03 builds the full set clean. Live-`aoe`-session isolation under the full custom mount set (§5.N#3) deferred. |
| _pending_ | operator | _pending_ | | | _deferred_ | Live run: inspect a real aoe session's mounts under the full manifest; confirm no `~/.claude/projects` source. |

---

## MV-03 — Network egress reaches scream-hole / discord / github from inside `[R-05]`

**Goal.** Prove a container built on the image has working **egress on the default
bridge** — it can reach the services the kit depends on (github, discord, and the
OaW scream-hole) from inside, so a dogfood/candidate container is a usable RTE
(R-05; TC-5). Unlike the other MVs this one needs **only docker** — no live `aoe`
session — so it is fully executable in the flight lane.

**Why (partly) manual.** No pytest oracle asserts live external egress (it is
network-dependent and would make the unit lane non-hermetic). A direct
`docker run` + `curl` from inside the real image is the procedure; it was executed
in the closing story.

### Preconditions

- **rootful docker**; the image built (`oakandwave-workflow:edge`).
- Network egress permitted on the default bridge (TC-5: `ghcr.io` needs a token;
  general HTTPS egress otherwise works).

### Procedure

1. **Probe egress from inside the image** (no aoe needed):

   ```bash
   docker run --rm --entrypoint sh oakandwave-workflow:edge -c '
     for url in https://api.github.com https://discord.com/api/v10/gateway \
                <scream-hole-url>; do
       code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 12 "$url")
       echo "$url -> HTTP $code"
     done'
   ```

   **EXPECT:** `HTTP 200` (or another non-error reachable code) for each endpoint
   the environment can route to. A connection error / DNS failure to a routable
   endpoint is a **FAIL** (egress broken).

2. **Record** the result: date, operator, image ID, the per-endpoint codes, and
   PASS/FAIL.

### Failure handling

- **A routable endpoint fails.** Check the docker network mode and the host
  firewall (`docker network inspect bridge`); scream-hole is an **internal** OaW
  service and only resolves on the OaW network — a failure there off-network is
  expected and not a bug.

### Result log

| Date | Operator | Image digest / ID | github | discord | scream-hole | PASS/FAIL | Notes |
|------|----------|-------------------|--------|---------|-------------|-----------|-------|
| 2026-07-23 | flight P4W2 (#976) | `sha256:2b75626d6365` | HTTP 200 | HTTP 200 | not routable off-network | **PASS** | `docker run … curl` from inside the real image: `api.github.com`→200, `discord.com/api/v10/gateway`→200. General egress on the default bridge confirmed (TC-5). scream-hole is an internal service unreachable from the flight network — noted, not a failure; an on-OaW-network operator run appends its code. |
