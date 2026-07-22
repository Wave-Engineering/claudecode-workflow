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
| MV-07 | A secret added mid-session is usable with no container restart | R-13 | Story 1.5+ |

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
