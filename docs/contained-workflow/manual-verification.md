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
| MV-04 | `aoe send` reaches into a running container (control-plane ingress) | R-15 | later |
| MV-05 | A broken container quarantines and recreates on `:stable`, zero loss | R-02, R-17 | Story 3.2+ |
| MV-06 | A wedged/OOM-killed `claude` still flushed its transcript | R-15 | later |
| MV-07 | A secret added mid-session is usable with no container restart | R-13 | Story 1.5 (#965) |

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
| _pending_ | _pending_ | _pending_ | | | | Executed and recorded in closing story 4.3 (#976) |

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
| _pending_ | _pending_ | _pending_ | | | | | Executed and recorded in closing story 4.3 (#976) |
