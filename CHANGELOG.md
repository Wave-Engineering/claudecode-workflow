# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Entries here are curated rather than generated — each states the defect and the reasoning that
produced the fix — so not every tagged release carries a section of its own. Two distinct gaps, which
are worth keeping apart:

- **1.0.0 through 5.1.0** have no section, but their content is not missing: that era was swept into
  the oversized `[6.0.0]` block below rather than filed per release. Reading `[6.0.0]` as "what
  changed in 6.0.0" will mislead you.
- **7.1.2, 7.1.3, 7.1.4, 7.2.0, 7.2.1, 7.3.0, 8.1.0 and 8.1.1** shipped with no curated entry at all.
  For these the record is the auto-generated
  [GitHub release notes](https://github.com/Wave-Engineering/claudecode-workflow/releases), which
  `release.yml` builds from PR titles on every `v*` tag — with one hole: **7.1.3** is a real tag
  (`bae1b8d`) that never got a GitHub Release, so it has no record anywhere but `git log`.

## [Unreleased]

## [8.21.0] - 2026-10-31

A release install now gets the same settings merge and `scripts/` tree as `./install`, and the
image pipeline can no longer move a GHCR version tag or promote a candidate that isn't a
release.

### Upgrading
- **`install-remote.sh` from this release on refuses an older tarball.** v8.21.0 is the first
  release whose tarball ships `scripts/lib/settings-merge.sh`. To install or roll back to an
  older tag, run that tag's own installer:
  `curl -fsSL https://raw.githubusercontent.com/Wave-Engineering/claudecode-workflow/<tag>/scripts/install-remote.sh | bash -s -- --version <tag>`.
  `./install` from a checkout is unaffected.

### Fixed
- **A release install now gets the same settings merge and `scripts/` tree as `./install` (#1360).**
  `install-remote.sh` carried its own copy of the merge, forked before the kit-owned union, the
  old-path migration and the duplicate collapse. The release tarball also shipped only top-level
  `scripts/` files, so every template hook pointed at a missing file. Now the merge lives once in
  `scripts/lib/settings-merge.sh`, and both installers source it. The tarball ships `scripts/`
  recursively with its file modes, plus `assets/logrotate`. `install-remote.sh` refuses a tarball
  older than v8.21.0 (the first with the lib), and `--dry-run` no longer writes settings. Also: a
  plugin the user set to `false` is no longer reported as added, or as missing by `--check`
  (both tested its value, not its key); the template no longer pins `model`; and
  only executable skill helpers get a PATH link. Two skills claiming one helper name now fail the
  install instead of overwriting silently. **The duplicate-hooks guard moved** from
  `scripts/ci/` to `scripts/lib/assert-no-duplicate-hooks.sh`.
- **Only a release reaches `:stable`, and a GHCR version tag never moves (#1359).**
  - **Promotion checks the label.** `promote-oakandwave-image.sh` now refuses a digest whose
    `org.opencontainers.image.version` label is not `X.Y.Z`, using the same rule as the Docker
    Hub mirror (both call the new `scripts/ci/read-oci-version.sh`). Before, a
    `workflow_dispatch` candidate (label `8.14.0-3-gabc`) could reach GHCR `:stable`, which the
    mirror then refused, leaving the two registries' `:stable` on different digests. The
    refusal also shows in a dry run.
  - **Version tags are written once.** The image build now pushes only `:edge`. A tag build's
    `:vX.Y.Z` is written by `oaw-mirror-image` after signing, under a `v`-prefixed regex, and
    refused if it already names another digest. So the tag only ever names a signed digest,
    and a transient signing failure still re-runs green. Before, re-running the build job on a
    `v*` tag silently moved it.
  - **The runbook's promote commands now run.** The ops runbook's §3 named a gate-signals
    script that never existed, set `PROMOTE_ACK` instead of `OPERATOR_ACK`, and never set
    `DIGEST_REF`. It now shows the declared-absent invocation the wrapper reads.

### Image

- **MCP servers:** unchanged from 8.20.0: mcp-server-sdlc v5.2.0, mcp-server-wtf v1.5.2,
  mcp-server-discord v1.4.3 and mcp-server-nerf v2.1.0. crewchat is still not baked: the image
  has no daemon socket.
- **trivy 0.74.0**, unchanged.
- **The duplicate-hooks guard** the image build runs moved to
  `scripts/lib/assert-no-duplicate-hooks.sh` (#1360).

## [8.20.0] - 2026-10-30

Chat moves to the OaW Mattermost server by default: `/owtx` and `/owrx` are new, and `/disc` is
deprecated but unchanged. `/precheck` grades every acceptance box mechanically, and can route
its notice to a lead. The wave gate binds to graded evidence, and `wave-status` can add an issue
to a wave. The crewchat clients move to mattermost-crew v0.2.6. A run of gate and test fixes
rounds it out.

**Needs sdlc v5.2.0 on the host before any auto wave runs.** The per-wave engine now counts a
pinned merge only on pr_merge's `pinned_head_sha` echo, which first ships in mcp-server-sdlc
v5.2.0. Before v5.1.0 the server drops the pin; v5.1.x pins but does not echo. On either, every
auto wave halts `pinned-merge-unproven` after its first group. `./install` pulls the latest sdlc
release, and this release's image bakes v5.2.0.

### Upgrading
- **`/disc` still posts to Discord. Use `/owtx` for OaW Mattermost.** Nothing that worked stops
  working: every `/disc` intent goes where it went, and only gains a one-line deprecation notice.

### Fixed
- **The wave gate binds to graded evidence (#1356).** Each flight is graded on its own head in
  code (`flightCiVerdict`) before reconcile, and only green flights reach it. Reconcile and promote
  merge pinned to the graded head (`expected_head_sha`), and a merge counts only when pr_merge
  reports `merged:true` and echoes that head. The trivy scan must be of the head CI graded. A
  merge that landed without a proven pin is reported `landedUnproven` with its merge commit, never
  as not landed. A new legal exit, `pinned-merge-unproven`, holds the wave on any unproven
  reconcile merge.
- **One lock predicate for the dependency scan (#1358).** `dependency-scan.sh`, the trust gate's
  trivy prompt and `/precheck`'s Job C fallback each counted lockfiles differently, so a precheck
  could pass a tree the trust gate held. `scripts/ci/lock-predicate.sh` is now the one predicate,
  and a test fails CI when the prose copies drift from it. Every trivy run ignores stray
  `.trivyignore` and config files. A summary over 64 KiB no longer false-fails the scan with
  exit 5. CI and the image move to trivy 0.74.0.
- **GitLab merged-results pipelines are found, and a wait fails fast when CI can't start
  (#1357).** A merged-results pipeline runs on `refs/merge-requests/<iid>/merge`, so lookups by
  branch or head SHA never found it, and the wave waited out its whole budget. The prompts name
  the right ref per platform. A probe before each wave wait HOLDs or blocks with the reason
  (`no run for head <sha>; mergeable=<state>`) when no run can start. `precheck-ci-source.sh`
  resolves the merge pipeline bound to HEAD, and `precheck-status.sh post` guards a GitLab MR's
  head pipeline around the post.
- **The push gates allow deleting one non-protected branch (#1364).** A plain
  `git push <remote> --delete <b>` (or `:<b>`) of one branch that isn't protected or a release
  ref passes with no test run and no secret scan, since a delete publishes no code. Deleting a
  protected ref is refused even after a test run.
- **The test sentinel counts only a known exit status (#1361).** It read a field Claude Code
  never sends, so any matching command counted, including a failed lane run. It now writes the
  sentinel only when the test's own status is known to be 0, and a background run never counts.
- **`uninstall.sh` removes only registered MCP servers (#1361, #815, #1152).** It ran every
  listed server's remote uninstaller, registered or not, and `--local` never turned MCP removal
  off (#815). It now skips MCPs under `--local`, removes only servers `claude mcp list` shows,
  and removes nothing when that list can't be read (#1361). The uninstall tests are hermetic
  (#1152), and the vox timeout tests no longer race their signal trap (#1361).
- **An arrow in a squawk's own text is not an answer (#1363).** The drain, banner and doorbell
  read everything after a squawk's last `→` as BJ's answer, so an agent's own prose arrow came
  back as "answered". `sqtk-answer.jq` holds the one rule: compared against the squawk's
  original text, only an arrow added after it marks an answer. The doorbell passes its maps to
  jq through files, so a large squawk list can no longer push it past the 128 KiB argument
  limit and leave it deaf.
- **`generate-status-panel` no longer crashes when a campaign's last wave completes (#1362).**
  `current_wave: null` reached `html.escape`. The CLI dashboard header no longer reads
  "Wave: None".

### Added
- **`wave-status add-issue <wave> <N|owner/repo#N>` (#1362).** It adds an issue to an existing
  wave's plan entry and to `state.json`, so a HOLD fix re-driven with its wave reaches every
  reader of the wave's issue list. It is idempotent for the same wave, and refuses another wave's
  issue, an unknown wave, a new issue on a completed wave and a bad ref. `/wavemachine` says to
  run it before a re-drive.
- **A mechanical AC gate, and no post-merge criteria (#1365).** `/precheck` used to tick
  "Implementation (AC verified)" from the agent's own reading, and nothing read the boxes. The new
  `scripts/precheck-ac-gate.sh` is Job E: every AC box on each closing issue, and every box in the
  PR/MR body, must be checked or carry `WAIVED by BJ <date>: <reason> (<url>)`, and it exits
  non-zero on a fetch error. Its `lint` refuses a criterion that needs a merge to assess (BJ,
  2026-10-24), and `/issue`, `/prepwaves` and devspec upshift run it before they write. The Plan
  template no longer asks for "Kahuna→main MR merged clean", the line a campaign release gate held
  on forever. The release gate's DoD node treats a BJ-waived line as waived.
- **The merge-call notice goes to a named lead (#1365).** A `lead` field in
  `.claude/agent-identity.json` (written by `/grunt`; `/name` now merges the file rather than
  rewriting it) routes `/precheck`'s notice to that lead by `SendMessage`, with no `#precheck` post
  and no `vox`. With no `lead`, the notice goes to BJ as before (`scripts/precheck-notify-target.sh`).
- **`/owtx` and `/owrx`: chat on the OaW Mattermost server by default (#1348).** They replace
  `/disc`'s send and read sides with no verbs: `#<channel>` is a channel, `@<user>` a DM, and a
  bare `/owtx` a roll-call check-in. With no route, neither passes `backend`, so the default
  applies (`home_backend`, then `chat-defaults.json`, which maps every OaW org to
  `mattermost:oaw-dev`, then ask-once). A last token pair of `> discord` or `> <server_id>`
  routes one message elsewhere; it counts only after the closing quote and only for a known
  name, so `"x > y"` stays text. New commands, not a new meaning for `/disc`: a changed default
  would have sent every habitual `/disc send` somewhere new without a word.

### Changed
- **The kit's own notifications go to the default backend (#1348).** `/precheck`'s `#precheck`
  post, `/name`'s roll-call and the wave skills' `#wave-status` announcements name the channel
  and pass no `backend`. Discord channel IDs survive only in each skill's no-crewchat fallback,
  and a test keeps it that way.
- **Pages go through `crewchat-send` first (#1348).** `notify-bj.sh` posts to `#call-4-bj` with
  `crewchat-send` (mattermost-crew #146), as the checkout's agent (`NOTIFY_BJ_REPO_ROOT`), and
  falls back to Discord when it is missing or exits non-zero. It logs which path delivered, and
  exits non-zero only when both fail, so a page never goes quiet. `reseed-kick.sh` passes its
  project root, and godspeed's checkpoint notify now goes through `notify-bj.sh` instead of its
  own copy of the Discord poster. `discord-status-post` stays on Discord: it edits one rich
  embed per project in place, and crewchat has no edit op.
- **The dual-mode rule and the doorbell moved to `docs/chat-tools.md` (#1348).** They are
  cross-skill rules, not `/disc`'s, and the doc is installed to `~/.claude/docs`. It also holds
  the `> <route>` grammar. Every skill that pointed at `/disc` for them points at the doc.
- **crewchat is pinned to v0.2.6 (#1348):** Mattermost channel names resolve (mattermost-crew
  #145), and `crewchat-send` exists (#146).
- **The wave dashboard lives at `.claude/status/dashboard.html` (#1362).** With no `.sdlc/`, it
  is written beside `state.json` instead of as an untracked `.status-panel.html` at the repo
  root. A stale `.status-panel.html` left by an earlier release can be deleted.

### Deprecated
- **`/disc` (#1348).** Use `/owtx` and `/owrx`. Removing it is a later major release.

### Image

- **MCP servers:** mcp-server-sdlc v5.2.0 (was v5.0.4), mcp-server-wtf v1.5.2,
  mcp-server-discord v1.4.3 and mcp-server-nerf v2.1.0. crewchat is still not baked: the image
  has no daemon socket.
- **trivy 0.74.0** (was 0.72.0; #1358).

## [8.19.0] - 2026-10-30

crewchat-doorbell is now the kit's only doorbell: discord-watcher is retired, and the doorbell
arms with no timeout. The crewchat clients move to mattermost-crew v0.2.4. The nerf mode now
decides what the context reseed gate does at the ouch dart. Ship it together with
mcp-server-nerf v2.1.0, which makes `ultraviolence` the default.

### Removed
- **discord-watcher is retired from the kit (#1344).** `crewchat-doorbell` has been the doorbell
  since kit 8.17.0, carrying Discord, Mattermost and squawk answers in one stream on any host that
  runs the crewchat daemon, so the watcher only duplicated it. `mcps.json` no longer lists it, and
  `./install` runs its own uninstaller once wherever `claude mcp list` still shows it. Gone with it:
  - `doorbell-oneshot.sh` and its regression test;
  - `docs/discord-watcher.md`;
  - `/disc`'s `forward`, `directmsg` and `//dm` routes;
  - the container image's baked copy, so the image now carries four kit MCP servers.

  `./install` prunes the installed doc and wrapper from `~/.claude` and `~/.local/bin`. The doc's
  rules that still hold, addressing and signatures, are now in `docs/chat-tools.md`, which the
  install copies to `~/.claude/docs` in its place.

  **Consequence:** a host without the crewchat daemon, including the contained-workflow image,
  has no Discord doorbell from the kit. `disc-server` still sends and reads there.

### Changed
- **The nerf mode now picks what the context reseed gate does (#1352).** The gate used to have
  one behavior, and nerf's modes and ouch dart were read by nothing. `context-reseed-gate.sh` now
  reads `mode` and `darts_pct.ouch` from the session's nerf config (`/tmp/nerf-<session_id>.json`):
  - `ultraviolence` blocks with "run /reseed now", as before;
  - `hurt-me-plenty` blocks and has the agent ask the user before it reseeds;
  - `not-too-rough` gives one reminder per session and no block.

  The threshold is `RESEED_CONTEXT_THRESHOLD_PCT` if set, else `100 - ouch`, else 15. A session
  with no nerf config, or one the hook can't read, behaves exactly as before.

  **Ships with mcp-server-nerf's next release**, which makes `ultraviolence` its default. Until a
  host has that release, a session whose nerf file was written with the old `hurt-me-plenty`
  default asks before reseeding.
- **`/disc` arms `crewchat-doorbell` with no timeout (#1346).** The arm line was
  `CREWCHAT_DOORBELL_TIMEOUT=1800`. Every exit 3 woke the agent for a turn with nothing in it,
  about 48 a day per agent. Since mattermost-crew v0.2.4 the doorbell's failures exit by
  themselves, 2 when the session isn't registered and 4 when the daemon is down, so the timeout
  bought no liveness. Running agents keep the old line until they pick up this release.
- **`install-crewchat.sh` pins mattermost-crew v0.2.4 (#1342).** A v0.2.2 client sends no
  project key, so the daemon can't apply a server's per-project allowlist, and agents in partner
  repos get no account there. Its doorbell also exited 4 on every daemon restart, sending each
  agent back to the one-shots. v0.2.4's doorbell waits 60 s through a restart, and its shim pings
  the daemon every 15 s and registers again by itself, so an idle session's doorbell re-arms
  with no tool call. `/disc`'s and `docs/chat-tools.md`'s exit tables now give exits 2 and 4 that
  60 s grace, and say which causes still exit 4 at once (no permission, a connect timeout, a bad
  reply). The shim's own re-register needs a daemon with `ping`. A v0.2.4 client works against an older daemon: its `ping` gets `unsupported`, and the
  shim falls back to registering on the next tool call. Agents pick it up at their next restart.

### Fixed
- **CI checks Workflow scripts as function bodies, not ESM (#1350).** Node 24's `node --check`
  rejects a Workflow script's top-level `await` and `return`, so every regression test that
  syntax-checked one failed. `scripts/ci/wf-syntax-check.mjs` wraps the script in an async
  function body, the way the Workflow runtime does, and the tests call it.

### Image

- **MCP servers:** mcp-server-sdlc v5.0.4, mcp-server-wtf v1.5.2, mcp-server-discord v1.4.3 and
  mcp-server-nerf v2.1.0 (was v2.0.0). discord-watcher is no longer baked (#1344). crewchat is
  still not baked: the image has no daemon socket.

## [8.18.0] - 2026-10-26

The last kit step before the crewchat daemon's first deploy. The crewchat pin moves to
mattermost-crew v0.2.2, which gives the doorbell's daemon-restart path a working
re-register and puts final names on the first deploy's tools. The vendored `sqtk` moves to
squawkie-talkie v0.12.0, whose `add` no longer truncates a squawk without a word.

### Changed
- **`install-crewchat.sh` pins mattermost-crew v0.2.2 (#1340).**
  - `chat_health()` now re-registers after a daemon restart: the daemon's `health` takes the
    agent's name and answers `not_registered` when it has lost the registration, and the shim
    re-registers on that (mattermost-crew #112). `/disc`'s doorbell exit 2 says to call it, in
    place of 8.17.0's one-message `chat_read`.
  - The nine deprecated `disc_*` alias tools are gone (mattermost-crew #113, D-108). No host had
    run the daemon yet, so the deprecation window covered no one, and the first deploy carries
    no deprecated surface. The four guild ops they carried are `chat_list_channels`,
    `chat_resolve`, `chat_create_channel` and `chat_create_thread`, Discord-only.
    `docs/chat-tools.md` documents them in place of the alias table. Kit skills keep using
    disc-server for guild ops until the cut-over (D-060).
  - `chat_read` takes `post_id`, for a one-message read.

### Fixed
- **`sqtk` refuses a split argument instead of dropping words (#1340).** `add` kept the first
  word after the list and dropped the rest without a word. So a quoting slip, such as an
  apostrophe inside a single-quoted squawk, landed a truncated item and exited 0. `show`,
  `walk`, `new` and `rmlist` given two names, and `lists` and `mine` given any argument, now
  refuse too. `rmlist` kept the LAST name, so `rmlist keep gone --yes` deleted `gone`. Each
  refusal exits non-zero and changes nothing. No kit script calls these with more than one
  argument. The vendored `scripts/sqtk` is squawkie-talkie v0.12.0's (squawkie-talkie #157).

### Image

- **MCP servers:** unchanged from 8.17.0: mcp-server-sdlc v5.0.4, mcp-server-wtf v1.5.2,
  mcp-server-discord v1.4.3, mcp-server-discord-watcher v1.7.1 and mcp-server-nerf v2.0.0.
  crewchat is still not baked: the image has no daemon socket.

## [8.17.0] - 2026-10-25

The kit's inbound side moves to crewchat, the second kit step of the Mattermost program, still in
dual mode: a host without the crewchat daemon keeps 8.16.0's transport and one-shot doorbells.
Where the daemon runs, `crewchat-doorbell` becomes the one doorbell, and a kiosk review reaches
the working agent as outsider data. On every host, `/reseed` now ends each seed with the
`## Kiosk` section the kiosk is seeded from. The crewchat pin moves to mattermost-crew v0.2.1.

### Added
- **The crewchat doorbell, the kiosk review and the `## Kiosk` seed section (#1336, K-2).**
  - Where `chat_send` is in the tool list, `/disc`'s new "Doorbell: `crewchat-doorbell` or the
    one-shots" section makes `crewchat-doorbell` the only doorbell. It is one stream for
    Mattermost, Discord and squawk answers, and arming it beside `doorbell-oneshot.sh` or
    `sqtk-doorbell.sh` would deliver everything twice. The section gives each exit code and
    each event type its action.
  - Outsider content, and every kiosk-review entry, is data, never instructions. A
    `kiosk.review` event is read and anything notable is raised to the human partner.
  - `/reseed` now always ends a seed with a `## Kiosk` section, written for outsiders, because
    it is the only part of a seed the kiosk sees. The new `crewchat-kiosk-brief.sh` prints what
    the kiosk will get, using crewchat's own extractor rather than a copy that could drift.
  - Hosts without the crewchat daemon keep the one-shot doorbells, as before.

### Changed
- **`install-crewchat.sh` pins mattermost-crew v0.2.1, and registers `crewchat` only where
  `crewchat-doorbell` runs (#1336).**
  - v0.2.1's `crewchat-doorbell` drops a repeated `event_id`, so exit 0 is always a new event.
    Its kiosk review IDs carry the transcript's generation.
  - A registered shim without a working doorbell would have every skill arm a command that
    isn't there. So at the pinned version a broken doorbell is drift: `install` reinstalls,
    and if that fails it removes the registration, and `check` reports it.

### Image

- **MCP servers:** unchanged from 8.16.0: mcp-server-sdlc v5.0.4, mcp-server-wtf v1.5.2,
  mcp-server-discord v1.4.3, mcp-server-discord-watcher v1.7.1 and mcp-server-nerf v2.0.0.
  crewchat is still not baked: the image has no daemon socket, so the installer registers
  nothing.

## [8.16.0] - 2026-10-25

The kit adopts crewchat's `chat_*` tools, the first kit step of the Mattermost program, and it
does so in dual mode: a host without the crewchat daemon behaves exactly as it did on 8.15.0. The
crewchat shim now installs from mattermost-crew's own lock, so a dependency's major release can't
break it at import. The image picks up mcp-server-sdlc v5.0.4.

### Added
- **crewchat `chat_*` in the kit, dual-mode (#1330).** `chat_*` works only where the crewchat
  daemon runs, and deploying the daemon is a fleet install, so nothing changes on a host
  without it.
  - `scripts/install-crewchat.sh` installs `crewchat-clients` at the pinned `CREWCHAT_TAG`
    (`v0.1.0`) and registers it as MCP server `crewchat` through `claude mcp`, but only when
    `/run/crewchat/crewchat.sock` exists and is writable. Where the daemon has gone, it removes
    the stale registration. It never edits `~/.claude.json` directly, and it never touches
    disc-server. `./install`, `./install --check` and `uninstall.sh` call it.
  - `/disc` has one transport rule: with `chat_send` in the tool list, use `chat_*` (backend
    `discord` for our channel IDs); otherwise use `mcp__disc-server__disc_*`. `/name`,
    `/precheck` and `/ccwork` follow it or declare their exception.
  - `/name` reports the chat mode: the backends `chat_health` lists, a restart hint when this
    run created the identity the shim reads at start, or Discord only.
  - `docs/chat-tools.md` is the agent-facing `chat_*` reference.

### Fixed
- **The crewchat shim installs from the lock (#1332).** A git-URL `uv tool install` re-resolves
  every dependency and ignores the repo's `uv.lock`. `crewchat-clients` declares only
  `mcp>=1.20`, so the resolver took mcp 2.x, which no longer has `mcp.server.fastmcp`. The shim
  died at import, Claude Code showed "Failed to connect", and `check` still reported clean.
  Found by the K-1 end-to-end run.
  - Install shallow-clones the tag over SSH, exports its lock as constraints, and installs with
    `--constraints`. A failed clone, export or install registers nothing, and removes any
    registration an earlier install left pointing at a broken shim.
  - The pins are kept beside the tool. Install checks the environment against them before it
    registers, and `check` reports drift: a pinned package at another version, or a tool with
    no record.

### Image

- **MCP servers:** mcp-server-sdlc v5.0.4 (from v5.0.3: `ibm` accepts `campaign/<plan>-*`
  integration branches), mcp-server-wtf v1.5.2, mcp-server-discord v1.4.3,
  mcp-server-discord-watcher v1.7.1 and mcp-server-nerf v2.0.0. crewchat is not baked: the
  image has no daemon socket, so the installer registers nothing.

## [8.15.0] - 2026-10-24

Docker Hub images now keep a name after `:stable` moves on: each release gets an immutable
`:X.Y.Z` tag. The fleet's mirrors get two shared actions: one mirrors without ever re-pushing a
version tag, and the other writes each image's digest into its GitHub release. The kit's mirror
now refuses a `:stable` that isn't a release build, so promote only tag-built digests.

### Added
- **Docker Hub gets an immutable version tag (#1324).** The mirror pushed only `:stable`, so
  when `:stable` moved, the previous release's digest had no name on Docker Hub. The mirror now
  also tags the digest `:X.Y.Z`, read from the image's own `org.opencontainers.image.version`
  label, so the workflow still takes no inputs.
  - A version tag is never re-pushed: one already naming a different digest fails the run, and
    nothing is pushed. A tag Docker Hub can't confirm as absent fails it too.
  - A rerun on the same digest pushes `:stable` alone.
  - The job summary prints the digest-pinned ref (`…:X.Y.Z@sha256:…`) for the release notes.
- **Shared `oaw-mirror-image` and `oaw-release-images` actions (#1326)** for the fleet's Docker
  Hub mirrors, next to `oaw-sign-image`. squawkie-talkie, flightdeck and scream-hole each copied a
  loop that re-pushed every tag, version tags included, and published no digest.
  - `oaw-mirror-image` pushes a version tag (`^[0-9]+\.[0-9]+\.[0-9]+$` by default) only when
    absent. It refuses, with nothing pushed, one that names another digest or can't be read. It
    pushes moving tags (`latest`, `X.Y`, `sha-…`) every time, all in one `imagetools create`. Its
    outputs and the job summary carry the digest-pinned refs.
  - `oaw-release-images` writes those refs into the GitHub release as one Images block that a
    rerun replaces. It runs after signing, so a release-API failure can't leave a pushed image
    unsigned. A missing release fails the step, unless `create-if-missing` is set. A repo whose
    release job attaches assets, like the kit's install tarball, must not get an empty release
    in their place, marked latest.

  The kit's own mirror runs the same core, and a separate `release-notes` job, the only one with
  `contents: write`, now fills in the `vX.Y.Z` release.

### Changed
- **The mirror refuses a `:stable` that isn't a release (#1324).** A digest whose version label
  isn't `X.Y.Z`, such as a branch build promoted by hand (`8.14.0-3-g9334c4b`), used to reach
  Docker Hub `:stable`. Now the run fails and Docker Hub keeps its previous `:stable`, so GHCR and
  Docker Hub disagree until a tag-built digest is promoted. Promote only tag-built digests.

### Image

- **MCP servers:** mcp-server-sdlc v5.0.3, mcp-server-wtf v1.5.2, mcp-server-discord v1.4.3,
  mcp-server-discord-watcher v1.7.1 and mcp-server-nerf v2.0.0, all unchanged from 8.14.0.

## [8.14.0] - 2026-10-24

Two changes since 8.13.0: agents now settle stale squawks on their own, and the reseed gate works on
Bedrock model ids. The image picks up discord-watcher v1.7.1.

### Added
- **Squawk curation (#1320).** Squawks went stale: items stayed open after the work that resolved
  them had landed, or after the issue that tracks them was filed. Agents now settle them at the two
  moments they know for certain:
  - **`/issue` Step 4.5**, after creating an issue: record each open item on the repo's triage
    list that the issue plainly covers, with `→ #<N>` as its answer, qualified as
    `<owner>/<repo>#<N>` on another repo's list.
  - **`/reseed` Step 1**, before the seed, while the agent still has the context: walk
    `sqtk mine`, retire what is stale with `→ OBE: <reason>`, and carry what is live in the seed.

  A stale item is retired, never rejected, and on `bj:needs` an agent settles only its own.
- **Reserved list names.** The vendored `sqtk` moves to squawkie-talkie v0.10.0, where `triage`
  means this repo's `<repo>:triage` and `needs` means `bj:needs`. `/sqtk` now teaches those names
  instead of hand-typed list names, which had drifted from agent to agent.

### Fixed
- **The reseed gate never fired on Bedrock (#1318).** The statusline reports `model_id` as
  `us.anthropic.claude-opus-5-5`, but settings key the autocompact window on `claude-opus-5-5`. The
  gate found no window and measured against the 1M model window, so it waited for about 822k
  while autocompact fired at about 367k. One session auto-compacted four times on 2026-10-24
  without a single reseed. The gate now tries the model's keys from most specific to least: as
  given, without `[1m]`, then canonical, with the provider prefix, `-vN:M`, `@version` and the date
  stripped. A window configured for other models but matching none of these keys is reported once
  per session, instead of reading exactly like no window.

### Image

- **MCP servers:** mcp-server-sdlc v5.0.3, mcp-server-wtf v1.5.2, mcp-server-discord v1.4.3,
  mcp-server-discord-watcher **v1.7.1** and mcp-server-nerf v2.0.0. The watcher moved from v1.7.0.
  v1.7.1 is the scream-hole poll fix (mcp-server-discord-watcher#92). The poll cursor crept one
  message per poll, batches arrived newest first, and a burst of more than 50 messages lost some.
  The cursor now advances to the newest id, and batches arrive oldest first. The other four are
  unchanged from 8.13.0.

## [8.13.0] - 2026-10-24

Most of this release is the wave-engine defect chain (#1303): ten fixes to the per-wave Workflow, the
trust gate, wave-status and the `/wavemachine` stall guard. They landed one at a time through
`/autochain` rather than as a wave campaign, because a campaign would have run on the engine being
fixed.

### Added

- **`wavemachine_active` has a lease with an age and an owner (#1110, PR #1307).** A `/wavemachine`
  run that died without `wavemachine-stop` left the flag set forever, and every later
  `wavemachine-start` refused. The flag now records the owning session and host, and its liveness is
  the age of `last_updated`: past 24 h (`WAVEMACHINE_STALE_SECONDS`) it reads lapsed. A lapsed lease
  is taken over only with an explicit `--reclaim`, which is logged loudly and recorded. A live one is
  never reclaimed. `wave-status wavemachine-lease` reports the lease as JSON, and the `/wavemachine`
  pre-flight hands a lapsed lease to the human instead of reclaiming it.

### Changed

- **Partner names are removed from the current tree (#1294, PR #1295).** Comments, docs, this
  changelog, and test and example slugs now use neutral wording. `/ccfold` Step 10 no longer ships a
  hard-coded org-to-identity baseline, which had drifted from the user's real mapping:
  `~/.claude/identity-map.json` is the only source. Git history is untouched.

### Fixed

- **The stall guard no longer false-fires mid-wave (#1205, PR #1309).** The per-wave Workflow's
  agents overwrite `current_action` with fine-grained states (`waiting-ci`, `in-flight`, `merging`),
  so the guard blocked a driver legitimately awaiting a running wave and told it to launch a
  duplicate. The driver's coarse states now also write `driver_action`, which only the driver
  touches, and the guard decides from it. It stays silent on `hold`, and on `awaiting-verdict` or
  `promoting` while the named wave is unfinished. It blocks on `launching`. State with no
  `driver_action` keeps the #736 rule.
- **The stall guard is a script, and stale state never blocks (#1109, PR #1308).** The inline
  Stop-hook guard blocked on any non-await action however old the campaign state was. A flag left by
  a dead run told every later turn to advance a campaign nobody had verified.
  `wavemachine-stall-guard.sh` now gives state older than 24 h, or state with no readable
  `last_updated`, a
  `systemMessage` with its age, owner and the verify/stop/hold options instead of a block. The
  installer removes the old inline guard first, because the hook merge keys on command text and
  would otherwise keep both.
- **A failed plan or reconcile agent holds the wave instead of crashing it (#1210, PR #1310).**
  `agent()` resolves to null when a subagent dies, and throws past the budget ceiling. The Workflow
  read `plan.done` and `rec.concerns` unguarded, so either failure killed the run with a
  `TypeError`: no verdict and no hold recorded. Both now end the loop with `haltReason` `plan agent
  failed: …` or `reconcile agent failed: …`, gate `SKIPPED`, and a held terminal record.
  `tests/regression/per_wave_harness.mjs` runs the committed bundle under node with stubs that fail
  the way the runtime does. It is the first test that executes the loop.
- **A retried wave starts its thrash counter at zero (#1204, PR #1311).** Rehydrate reloaded the
  durable `idleRounds`, so a wave retried after a thrash exit halted again before planning anything,
  and every campaign retry was spent on a run that could not move. `idleRounds` now counts within one
  run. `reworkCount` and the lifetime `groupsRun` bound still carry across retries. A halt before
  any flight launched says so (`exitedBeforeDispatch`).
- **A rework flight is told why, and a no-op rework holds (#1213, PR #1312).** Reconcile's rework
  reason never reached the flight, which was told to check for already-present work first while its
  rejected commit was still on the branch. Every rework came back already-present and counted as a
  cycle until the cap held the wave with the defect unfixed. A rework dispatch now carries the reason
  and the rejected head. A rework that returns already-present, `rework_not_applied` or the
  rejected head halts the wave as `rework-noop:#N`, and the rework context survives a resume.
- **Flights are told not to run `/precheck` (#1209, PR #1313).** A Workflow flight has no Agent
  tool and is told not to push, yet the kit told it to precheck and auto-merge itself into kahuna,
  so every flight reported that it couldn't. Reconcile lands flights on `kahuna/*` and the trust
  gate's review signal reviews the wave. `workerPrompt` now says so. `CLAUDE.md`'s MR Gate exempts
  Workflow flight workers, and its Kahuna exception names the PR/MR into `kahuna/*`, not a Flight
  Agent.
- **The trust gate's trivy signal scans the kahuna tip, bound by SHA (#1206, PR #1314).** It scanned
  whatever the operator's checkout held, so a green verdict could be for a tree that was never the
  wave. It now scans a detached worktree of `origin/<kahuna>` and never touches the checkout. The
  agent returns `scanned_sha` and `kahuna_sha`, and `trivyTreeBound()` holds unless both are full
  SHAs and equal.
- **The trust gate's CI wait is a per-repo budget (#1302, PR #1315).** A hard-coded 420 s meant a
  repo whose cold build takes longer held every wave, and under `/wavemachine` a hold stops the
  campaign. `CI wait budget` in `.claude-project.md`, declared by hand and carried over by `/ccfold`,
  reaches the gate as `ciWaitSec`: an integer in [60, 3600], per phase, default 420. A rejected
  value falls back loudly, with a `[#1302] ignoring ciWaitSec` log line. Waits over 1800 s are
  unproven, and the campaign release gate keeps its own 1800 s wait.
- **`hold_detail` is cleared when a wave leaves held (#1208, PR #1306).** `complete()` and
  `planning()` kept the previous hold's text, so a completed wave still showed why it had once been
  held. A hold without `--detail` likewise now drops the old text. The hold stays on record in its
  `hold_wave` concern event.
- **The push gate exempts `campaign/*` integration refs (#1299, PR #1300).** It exempted
  `kahuna/*` and `wave-*/*` but not the `campaign/<plan_id>-<slug>` branch `/wavemachine` cuts per
  campaign, so a plain push of it was blocked. `pr-ready-gate.sh` already treated `campaign/*` as
  an integration branch.
- **The reseed gate now honors `/autocompact` (#1297, PR #1298).** Claude Code computes the statusline's
  `remaining_percentage` against the *model's* window, and `/autocompact` doesn't change it. With a
  400k autocompact window on a 1M model, autocompact fired near 367k while the 15% gate waited for
  850k, so every session got a lossy `/compact` instead of a reseed. The statusline now also saves
  `used_tokens`, `window_tokens` and `model_id`. `context-reseed-gate.sh` recomputes the percentage
  against what is usable before autocompact fires: `min(model window, autocompact window)` less a 33k
  buffer (`RESEED_AUTOCOMPACT_BUFFER_TOKENS`). The autocompact window comes from
  `CLAUDE_CODE_AUTO_COMPACT_WINDOW` (`400000`, `400k` or `1M`, raised to 100k as Claude Code does),
  else `modelSettings.<model>.autoCompactWindow`, else the top-level `autoCompactWindow`. A 400k window
  now reseeds from ~312k and a 200k one from ~142k, both ahead of autocompact; a plain 1M window moves
  from 850k to ~822k. A reading without the token fields behaves as before.

### Image

- **MCP servers:** mcp-server-sdlc **v5.0.3**, mcp-server-wtf v1.5.2, mcp-server-discord v1.4.3,
  mcp-server-discord-watcher v1.7.0 and mcp-server-nerf v2.0.0. sdlc moved from v5.0.2. v5.0.3
  is the `ci_wait_run` platform fix (mcp-server-sdlc#603), which 8.12.0 listed as merged but
  unreleased. The other four are unchanged from 8.12.0.

## [8.12.0] - 2026-10-23

### Fixed

- **`/precheck` Job B decides its lane source in code before any wait (#1268, PR #1282).** Job B
  used to call `ci_wait_run(timeout_sec: 1800)` straight away, then fall back to the full local
  suite on `NO-RUN`. On GitLab before sdlc#585, and on any repo whose branch pipelines only start
  on demand, that fallback ran every time: a dead wait, followed by a heavy unbooked run on a
  shared box. A new `scripts/precheck-ci-source.sh` answers the question first.
  - **`resolve`** finds a run for the SHA by a direct read. It reads by SHA, so GitLab MR
    pipelines count. It prints the run's own ref, and `ci_wait_run` waits with that ref.
  - **`CI on demand`.** If the repo declares a `CI on demand` command in `.claude-project.md`,
    `resolve` runs it once per SHA. It never starts an undeclared pipeline, because a generic
    trigger can start publish or deploy jobs.
  - **Local fallback.** Otherwise it returns the local fallback at once, with the reason named.
    It works to one wall-clock budget, so it always prints its line.
  - **`coverage`** refuses a run that is missing a declared `CI jobs` entry. On this repo it
    rejected the `mirror` workflow's run, which had been the only run at `main`'s HEAD, as
    `missing validate`.
- **`doorbell-oneshot.sh` warns on an unresolved identity, not just a missing file (#1283,
  PR #1285).** The watcher fails closed on any unresolved field. A file that existed but didn't
  parse, or had an empty `dev_name` or `dev_team`, used to pass the check, and the oneshot then
  hung, which looks exactly like a quiet channel. The check now names the field that failed.
  Like the watcher, it falls back to the legacy `/tmp/claude-agent-<md5(root)>.json`, and it warns
  only when neither file resolves.
- **The push gate exempts `git -C <path> push`, and its test detector counts a repo's own entry
  points (#1287, PR #1288).** Two gaps refused legitimate pushes to an agent's own working
  branch.
  - **`git -C` pushes.** An agent working in a second repo can't stay `cd`'d there, so it pushes
    with `git -C`, and that was never exempt. Now `git -C <plain path> push …` is judged by the
    same rules as a plain push.
  - **Test detection.** `post-tool-test-sentinel.sh` matched only a fixed list. It now also
    counts scripts named like `run_lint.sh`, `run-tests.sh` or `validate.sh`. It also counts any
    command the repo declares on a `.claude-project.md` Toolchain `Validation`, `Tests` or `Lint`
    line. A declared span counts only where a command *starts*: Toolchain lines also put file
    paths in backticks, and `cat pyproject.toml` must not count as a test run.
- **The dependency scan counts Python lockfiles (#1289, PR #1290).** A repo whose only lock was
  `uv.lock` read "0 scannable", so it was reported as having nothing to scan, or failed, without
  the real lock ever being scanned.
  - **Added:** `uv.lock`, `poetry.lock` and `Pipfile.lock`, to all three lock lists
    (`check-scannable.sh`'s arrays, the precheck fallback `find`, and the trust gate's
    `gate.js`). `dependency-scan.sh` has no list of its own; its coverage denominator is what
    `check-scannable.sh` counts. Each type was confirmed against trivy 0.74 before it was added. A drift test now
    keeps the three lists in agreement.
  - **Left out:** `pdm.lock`, because trivy 0.74 has no analyzer for it. Counting it would have
    made every repo carrying one fail as UNSCANNED.

### Image

- **MCP servers:** mcp-server-sdlc v5.0.2, mcp-server-wtf v1.5.2, mcp-server-discord v1.4.3,
  mcp-server-discord-watcher **v1.7.0** and mcp-server-nerf v2.0.0. The watcher moved from
  v1.6.1. v1.7.0 is the doorbell cleanup: a quiet channel's first message is no longer
  swallowed, there is one poll core for both modes, `@agents` is the fleet broadcast, and the
  cursor is saved per transport. The kit installs each server's latest release, so an 8.12.0
  install or image build gets v1.7.0.
- sdlc `main` also has the `ci_wait_run` platform fix (mcp-server-sdlc#603). It isn't released
  yet, so it isn't in this image.

## [8.11.0] - 2026-10-20

### Changed

- **`/precheck`: no sub-agent report is a gate value (#1275, PR #1276).** Jobs A, B and C used to
  be haiku sub-agents, and the gate read what they wrote rather than what the instrument returned.
  On 2026-10-19 that misreported twice:
  - a Job A agent never called `spec_validate_structure`, and labelled its own reading of the
    issue `Raw tool response: ... PASS`;
  - a Job B agent reported `shellcheck exit=0` while its output listed SC1091. The real code was 1,
    and through `xargs` it reads 123.

  The orchestrator now runs each instrument itself and puts its JSON or exit code on the checklist
  as read. Only Job D, the code review, is delegated.
  - **Job A** calls `spec_validate_structure` and reads `valid` / `missing_sections`. A tool error
    FAILs.
  - **Job B-ci** calls `ci_wait_run` and writes the `LANE` line from `final_status`. `NO-RUN` is
    `ok:false` with an error beginning `No CI run found`, and any other `ok:false` is `exit=1`.
    On GitHub it cross-checks the paginated check-run conclusions. `gh run watch --exit-status` is
    never evidence.
  - **Job B-local** runs each lane as `<cmd> > <log> 2>&1; echo "exit=$?"`, one at a time, with a
    long lane in the background. It never pipes a lane through `tail`, `head`, `grep` or `xargs` before `$?`. A
    multi-file linter takes every file as argv.
  - **Job C** runs `dependency-scan.sh` the same way, in the background. A scan that printed no
    `exit=` has no result, and is never a pass.
  - Pinned by `tests/test_precheck_instruments.py`.

  This replaces the interim rule posted to Discord #precheck on 2026-10-19. It reaches a host with
  the next install.

### Fixed

- **trivy's JSON no longer passes through the tool output (#1275, PR #1276; #1277, PR #1279).** The
  Bash tool cuts output at about 30k characters, and trivy lists a target's `Packages` before its
  `Vulnerabilities`. A large lock could be cut between the two and read as ingested with 0
  HIGH/CRITICAL, a false PASS (one `django==2.2.0` pin is about 95 KB of JSON). Two paths had it:
  - `/precheck`'s raw-trivy fallback, the path every repo but cc-workflow takes;
  - the nextwave trust gate's trivy signal, `trivySignalPrompt()`.

  Both now write each run's JSON to its own file, with stderr in a separate file so a warning can't
  make good JSON unparseable. Each run prints its own `exit=` and runs in the background (the trust
  gate's, one at a time). Packages
  and findings are read per target from the file with `jq`. The trust gate's row also carries
  `hc_fixable`, because its pass predicate fails only on a fixable finding. A run with no `exit=`,
  a non-zero one, or an unparseable file is UNSCANNED.
  - The trust gate's work directory is a `<w>` placeholder, filled in from the path `mktemp -d`
    printed. A shell variable doesn't survive between Bash calls, so a `$w` would have written to
    `/trivy-0.json` and held every wave.
  - Not yet seen live: `run_in_background` inside a Workflow `agent()`. If it fails there, the
    signal HOLDs; it never passes.

### Image

- **The MCP servers are unchanged from 8.10.0:** mcp-server-sdlc v5.0.2, mcp-server-wtf v1.5.2,
  mcp-server-discord v1.4.3, mcp-server-discord-watcher v1.6.1 and mcp-server-nerf v2.0.0.

## [8.10.0] - 2026-10-19

### Fixed

- **The nextwave trust gates grade merge-result CI in code (#1211, PR #1270).** A GitLab
  merged-results pipeline runs on an ephemeral merge commit, so its sha is never the MR head
  (0/15 measured on green pipelines). The per-wave CI signal's old rule, "its sha equals the MR
  head", could therefore never pass on green.
  - The per-wave CI signal and the campaign release gate now share one pure predicate,
    `mergeResultVerdict()` in `skills/nextwave/merge-result.js`, inlined into both bundles. It
    binds a pipeline to the head through the merge commit's second parent (`parent_ids[1] ==
    head`, 15/15), or through `sha == head`.
  - `ci_wait_run` is the primary path. A direct read of the MR's
    `refs/merge-requests/<n>/merge` pipelines is used **only when it gives no verdict**. Only
    that ref counts (the #904/#476 guarantees hold), and the newest run wins. A run that can't
    be ordered, because it has no integer id, HOLDs.
  - **A graded red is final**, GitLab's `failed`/`canceled` spellings included. A direct read
    never overrides it.
  - The head is read twice, before `ci_wait_run` and after the last read. A head that moved
    between the two HOLDs. The release merge is pinned to the head the verdict graded.
  - Not in this fix: removing the 420 s / 1800 s waits. That depends on `ci_wait_run` seeing
    GitLab pipelines (sdlc#585, shipped in sdlc v5.0.2, below) and on sdlc's own no-run window.
- **Dependency-scan coverage is matched by name, and partial coverage fails (#1247, PR #1269).**
  trivy's pip analyzer reads only a file named exactly `requirements.txt`. Every other pip lock
  was counted in the coverage denominator but never scanned, so a clean scan of the remaining
  locks read as a PASS.
  - `scripts/ci/check-scannable.sh` is the single source for what a pip lock is
    (`*requirements*.txt`, or `requirements/*.txt`). Each lock that isn't named
    `requirements.txt` is staged alone under that name and scanned.
  - A lock that was counted but not ingested is reported `UNSCANNED`. **New exit 6, PARTIAL
    COVERAGE, fails on every path**: `dependency-scan.sh`, the `/precheck` Job C fallback, and
    the trust gate's trivy signal, which re-checks coverage in code (`trivyCoverage()`).
  - `.no-scannable-dependencies` applies only when no lock is found. A lock that is found but
    not scanned fails, declared or not.

### Image

- **The image bakes mcp-server-sdlc v5.0.2 and mcp-server-discord v1.4.3.**
  - sdlc v5.0.1 and discord v1.4.3 fix their installers: the release tag is resolved from the
    `releases/latest` redirect, and curl network failures are told apart from HTTP errors.
  - sdlc v5.0.2 runs `glab` as argv, so an `&` in a query can no longer background a GitLab
    list call (sdlc#585). This is what lets `ci_wait_run` see GitLab pipelines.
  - The other three are unchanged from 8.9.0: mcp-server-wtf v1.5.2,
    mcp-server-discord-watcher v1.6.1 and mcp-server-nerf v2.0.0. `install-remote.sh` bakes each
    server's latest release at tag time.

## [8.9.0] - 2026-10-19

### Added

- **Squawk lists in the kit (#1236, PR #1265).** squawkie-talkie's lists become how an agent asks
  BJ something and how it hears back.
  - **`sqtk`** is vendored, byte-identical, from squawkie-talkie v0.9.0. It is pinned by sha256 in
    `scripts/ci/sqtk.pin`, written only by `scripts/ci/vendor-sqtk.sh <tag>`, and put on PATH by
    `./install`. `sqtk add` records each squawk in `.claude/sqtk-mine.json`.
  - **`/sqtk`** covers which list to use (`bj:needs`, `<project>:triage`, or any named list), the
    rules for `bj:needs` (end every ask with ` →`), walking a list with BJ, and images.
  - **`sqtk-drain.sh`** (a `UserPromptSubmit` hook, timeout 10) injects each change to the agent's
    own squawks into its next turn, once.
    - It fetches lists least recently first, at most 5 per prompt, within a 5 s budget.
    - It filters each list to this checkout's ids and hands jq files, never argv, so a long list
      can't hit ARG_MAX.
    - It fails open.
    - A squawk that vanishes, or whose list squawkie says is gone, is only marked gone after 3
      misses over a day. A passing 404 or a wrong `SQUAWK_URL` can't drop an answer.
  - **`sqtk-doorbell.sh`** is a one-shot SSE listener for an idle agent, run as a background task.
    Its exit is the wake-up: 0 answered, 2 nothing open, 3 its own timeout, 4 the stream dropped.
    Once the stream is live it catches up through the drain's `--pending`, so an answer that
    landed before arming still rings, carrying the change, and rings only once.
  - **`sqtk-banner.sh`** is an opt-in `Stop` hook that shows BJ the open `bj:needs` items. It is
    wired per session in `settings.local.json`.
  - **Known limit:** ✓ and ✗ need squawk.apps at squawkie-talkie ≥ 0.8.0. The live server is
    older, so `sqtk set --state confirmed|rejected` returns HTTP 400 until it is upgraded, which
    is a production change and BJ's call. Open, `→` answers, retired and recorded work today.
- **`/onboard` (#1239, PR #1263)** brings a fresh agent up to speed in a repo, in order:
  - `/engage`, `/name`, and a seed check (a fresh `.claude/reseed-revive.md` hands off to
    `/reseed revive`);
  - a background code explorer, and a bounded documentation fan-out;
  - every open issue title, with at most 10 reviewed in depth;
  - `/ccfold` through the normal gates when CLAUDE.md is stale;
  - then a hold for tag-up.

### Changed

The first three change how a session runs once the kit is installed.

- **Spotted something outside the work in front of you? Squawk it on `<project>:triage`; don't
  file it (#1236, PR #1262).** It is a new MANDATORY section in `CLAUDE.md`, with a guard line atop
  `/issue` and a paragraph in WAVE_AXIOMS Axiom 4. It keeps three cases apart, each unchanged:
  - an in-lane fix is still done inline;
  - unease about the run in flight is still a `[concern]` comment;
  - an issue the user asked for is still filed with `/issue`.
- **A new merge-gate exception, the Lead-Agent Grant (PR #1262).**
  - The user may name one agent as lead for an organization. That agent self-approves the merge
    on a clean precheck of the exact head, and tags and releases when it judges the time is
    right.
  - The grant is never relayed. The lead checks that its Dev-Name (`.claude/agent-identity.json`)
    and the repo's origin match the grant.
  - A grunt's or peer's PR/MR merges only on the lead's own `/precheck` of that head.
  - The ABSOLUTE prod rule still binds: a tag that changes what prod runs still needs a yes-prod.
  - `/precheck` emits `[AUTO-APPROVED: lead-agent grant]`, and `/mmr` accepts it. Every list of
    the merge exceptions now names both grants.
- **Grunts escalate only to their lead (PR #1262).**
  - Concerns, questions and parks go to the lead by `SendMessage`, never to the human in the
    grunt's own session. Emergency pages are the exception.
  - When `SendMessage` fails, the grunt falls back to `<side-channel>`, addressed
    `@<lead-dev-name>`.
  - A grunt's PR/MR stops at ready, and its `/precheck` STOP becomes the handoff to the lead.
  - The charter template gains `<lead>` and `<lead-dev-name>` slots.
- **CI (#1236, PR #1265):** `validate.sh` now runs `tests/skills/*.sh`, which ran nowhere before.
  Three stale skill tests are re-aimed: nextwave (#712), the label colour (#903) and the prepwaves
  strings (#1186).

### Image

- **The image now bakes mcp-server-sdlc v5.0.0**, the first image server that enforces the
  `precheck` status (#592): `pr_create`/`pr_ready`/`pr_merge`/`pr_merge_wait` refuse a head
  without a pass. This kit posts that status (8.8.0 onward), so the pair is consistent inside the
  image. The other four are unchanged from 8.8.0: mcp-server-wtf v1.5.2, mcp-server-discord
  v1.4.2, mcp-server-discord-watcher v1.6.1 and mcp-server-nerf v2.0.0. `install-remote.sh` bakes
  each server's latest release at tag time.

## [8.8.0] - 2026-10-19

### Changed

- **`/precheck` becomes the PR/MR gate, and approval moves to the merge (#1235).** This changes
  how a session runs. Commit and push are now free on an agent's working branch; the secret scan
  is what still runs there. `/precheck` reviews the pushed commits, reads CI's verdict for the
  pushed HEAD, posts a `precheck` commit status on that exact SHA, and marks the draft PR/MR
  ready. BJ's approval is the merge call (`/mmr`, `/scpmmr` or an affirmative), not the precheck.
  - **The status contract** is in `docs/precheck-status.md`: context, state, description, SHA,
    and who produces and consumes it. `scripts/precheck-status.sh` posts and reads it, and its
    `mark-ready` refuses unless the head carries a pass.
  - **`pr-ready-gate.sh`** (a new `PreToolUse` hook) blocks `gh pr create`/`ready`, a non-draft
    `glab mr create`, and every `glab mr update` without `--draft`, unless the head carries a
    pass. Integration pairs are exempt: a `kahuna/*` or `campaign/*` head, or a `kahuna/*` base.
  - **`/precheck rearm`** renews a stale pass after a later push. It reviews only the commits
    since the last pass, plus a green pipeline, and survives a reseed.
  - **A new CLAUDE.md exception, Standing Merge Grant**, covers a merge grant the user gives for a
    named, bounded effort. Unlike the Kahuna and autochain exceptions, the agent applies it, so
    the grant and its reasoning go on the checklist.
- **Kit callers pass `squash_message`, and `/mmr` merges from the `## Squash commit` block
  (#1257).** This is the kit half of mcp-server-sdlc #592. `/scpmr` and `/precheck` pass
  `squash_message` to `pr_create` only when its schema lists the field, and never on an
  integration pair. On a gated server, `/mmr` merges from the stored block with no
  `squash_message`. On an older server, or on an integration pair, it drafts as before.
- **Release order: this kit ships before the mcp-server-sdlc #592 tag.** It works against both
  server versions. The server is what enforces the `precheck` status on
  `pr_create`/`pr_ready`/`pr_merge`. Until that release is installed, the gate is `/precheck`
  and `/mmr` checking the status.

### Fixed

- **A reseed revive no longer false-pages "auto-revive FAILED" (#1244).** `reseed-kick.sh` read
  only its prompt-hook nonce, so a session that revived through the Skill tool, or inside a turn a
  peer message started, was paged as failed, and its typed sends queued up as stale turns. The
  kicker now reads the session transcript for the revive itself and for whether a turn is
  running. It never types into a busy session, and it waits `RESEED_KICK_LIVE_WAIT` (600 s) for a
  live one before paging.
- **vox's provenance log no longer records credentials from ancestor command lines (#1248).**
  Each logged hop keeps only argv[0] and argv[1], masked (`NAME=value`, secret-named flags, URL
  passwords, token and key shapes) and cut at 160 characters, and the rest is counted. The log is
  created owner-only (0600), and an existing 0644 log is tightened on the next call. Lines
  already written are not scrubbed.
- **`VOX_WAKE` (`noise` | `none`) can turn off vox's Bluetooth wake-noise preamble (#1254).** A
  loudness-normalizing player had turned it into a burst of static. The setting comes from
  `$VOX_WAKE`, then `${XDG_CONFIG_HOME:-$HOME/.config}/vox/wake`, then defaults to `noise`.

### Image

- **The MCP servers in this release's `oakandwave-workflow` image are unchanged from 8.7.0:**
  mcp-server-sdlc v4.4.1, mcp-server-wtf v1.5.2, mcp-server-discord v1.4.2,
  mcp-server-discord-watcher v1.6.1 and mcp-server-nerf v2.0.0. `install-remote.sh` bakes each
  server's latest release at tag time. sdlc is still pre-#592, so inside the image the precheck
  status is checked by the kit, not yet enforced by the server.

## [8.7.0] - 2026-10-18

### Added

- **A secret scan at every commit and push (#1234).** Since #1232, a plain push of an agent's
  working branch no longer waits for a test run. Every OaW repo is public, and a pushed branch is
  published even if it never merges, so the secrets check now sits where that risk is. A
  `PreToolUse` hook, `secret-scan-gate.sh`, runs gitleaks before each `git commit` and `git push`
  and blocks on a finding.
  - **It fails closed.** No gitleaks, no repository, a scan error, a failed `rev-list` or a
    detector that did not load all block, and the hook is registered `"onFailure": "block"`. A
    finding is reported with `--redact`: file, line, rule and commit only, never the secret.
  - **Allowlisting** goes through `.gitleaksignore` (`<file>:<rule>:<line>`) or `.gitleaks.toml`.
    There is no bypass flag.
  - **`./install` provides gitleaks.** `scripts/ci/install-gitleaks.sh` installs a pinned 8.30.1
    (sha256 per platform) for `./install`, CI and the container image. When `PATH` finds a
    gitleaks other than the kit's own copy, `./install` leaves it alone.
  - `git-detect.sh` holds the commit/push detector, shared with `pre-push-test-gate.sh` so the two
    hooks cannot disagree about what is a commit or a push.

### Changed

- **The pre-push gate lets a plain working-branch push through (#1232).** `/precheck` gates the
  PR/MR, not the push. A plain `git push <remote> <branch>` of an agent's own working branch
  (`feature/`, `fix/`, `chore/`, `doc/`) no longer waits for a test run. A project with another
  branch convention adds it as an extended regex in the new `PUSH_GATE_EXTRA_BRANCH_RE`. A
  protected ref is never exempt, whatever that regex says. Apart from those and the existing
  integration-ref exemptions (`kahuna/*`, `wave-*/*`, the active wave's flight branches), every
  push still gates, and a command that is not obviously plain is gated rather than parsed.
- **Skill backups leave the skills tree (#1238).** `./install` writes skill backups to a mirror
  path under `backups/skills/` in the install's `.claude` directory (`~/.claude/`, or the
  project's for `--local`) instead of next to the skill, and moves any `.bak` an older install
  left in the skills tree there. Backups are still kept, never deleted (#714);
  they no longer sit where the skill loader and every grep audit read.

### Image

- **This release's `oakandwave-workflow` image bakes in today's MCP releases:**
  mcp-server-sdlc v4.4.1, mcp-server-wtf v1.5.2, mcp-server-discord v1.4.2 and
  mcp-server-discord-watcher v1.6.1. Their HIGH/CRITICAL advisories are cleared, and sdlc's
  GitLab adapters no longer need glab >= 1.37.0 (autochain #1243).

## [8.6.0] - 2026-10-18

### Changed

- **nerf's darts are percentages, and the kit follows (#1237, mcp-server-nerf#32).** nerf had
  measured no session's context since 2026-05-12, while reporting every session as healthy.
  `context.ts` shelled out to context-crystallizer's analyzer, which #647 deleted, and a null
  reading rendered as "under every threshold".

  **What changes for you:**
  - `/nerf 85`, `/nerf darts 51 63 85`. Token counts (`/nerf 200k`) are rejected now.
  - On the statusline, `ctx ?` means nerf has no usable context reading; `nerf_status` says why.
  - The `ctx` segment of the statusline takes its colors from nerf's new percentage darts.

  **How it works now:**
  - nerf v2.0.0 reads the per-session reading the statusline persists (#1225). A missing or
    stale reading shows as `ctx ?`, with a reason in `nerf_status`.
  - Darts are percentages of the window used, stored under `darts_pct`, so the same darts are
    correct on a 200k window and a 1M one.
  - The `/nerf` skill and `docs/skill-reference.md` now teach percentages.
  - The statusline colors the `ctx` segment by `darts_pct`. It keeps the older token `darts`
    branch and the 13%/25% fallback.
  - `session-start-compact.sh` passes `--not-before`, so a pre-compaction reading is never
    repainted as current. When a render lands a fresh reading while the indicator shows
    `nerf:ctx ?`, the statusline asks nerf (in the background) to repaint.
  - The dead pre-MCP `skills/nerf/lib/nerf_config.py` is gone, along with its tests and
    `tests/test_cc_context.py`.

  **Install this kit and nerf v2.0.0 together; one `./install` pulls both.**
  - **This kit with an older nerf fails silently.** The hook and statusline cope, but `/nerf 85`
    would set darts of 85 *tokens*, leaving `ctx` red for the rest of the session.
  - **nerf v2.0.0 with an older kit fails loudly.** It rejects token arguments with an explicit
    error. That's why nerf was released first.
- **`doc`, never `docs` (#1231, #1230).** The commit-type template and the kit spell the type
  `doc(scope):`, to match the branch prefix, issue type and label.

## [8.5.0] - 2026-10-15

### Added

- **`/autochain` lands in the repo, and its approval moves behind a fail-closed gate (#1224,
  #1101).** The skill existed only at `~/.claude/skills/autochain/SKILL.md` and granted its own
  approval ("a passing `/precheck` is automatic approval for `/scpmmr`"). That contradicted
  `/precheck`'s STOP on every non-kahuna branch. The grant is now policy: CLAUDE.md's "Exception:
  Approved Autochain", enforced by `/precheck` Step 5 through `scripts/autochain-gate.sh`.
  - The gate answers "approved" only for an armed, unexpired (`AUTOCHAIN_TTL_HOURS`, default 12),
    listed issue.
  - `arm` reads BJ's quote from a file, because a shell argument would execute backticks in it.
  - `consume` narrows the approval as each issue merges.

  Job B now runs every validate and test lane and reports each lane's own exit code. Before, it
  stopped at the first lane it found.
- **A context-threshold Stop gate triggers `/reseed` (#1225).**
  - `statusline-command.sh` now persists Claude Code's window-aware `remaining_percentage` per
    session.
  - `context-reseed-gate.sh` blocks a turn's end at ≤ `RESEED_CONTEXT_THRESHOLD_PCT` (default 15)
    and says to reseed.
  - A missing or malformed reading never blocks. Once it persists for three turns, it is reported
    once per session rather than left silently inert.
  - There is no age cutoff: an idle session's old reading is still exact, because remaining
    context only changes when a message renders the statusline.
- **`vox` chunks long messages and explains synthesis failures (#1214).** Synthesis can run slower
  than realtime (a cloned voice took ~28 s for 326 characters). Long messages hit the caller's
  timeout or the provider's 30 s HTTP cap, and nothing played and nothing was reported.
  - Text over `VOX_CHUNK_CHARS` (150) is split at sentence, clause or word boundaries and
    synthesized one part at a time into one clip.
  - Multi-part speech is detached from the caller; background failures go to
    `~/.claude/logs/vox-errors.log`.
  - A provider failure, or a kill during synthesis, now prints why: a caller timeout or an
    over-long message, as distinct from an endpoint that is down.
- **A review-protocol bench (#1195, #1199).** It is tooling to measure whether a Job D prompt
  catches defects that history later proved were there. It does not measure agreement with
  another review.
  - An SZZ bug-origin oracle (`scripts/ci/szz-oracle.sh`), deliberately model-free. It was
    calibrated by hand on 20 pairs before first use: 67% precision after dropping compound
    changesets (`docs/szz-oracle-calibration.md`).
  - Reconstruction of a historical changeset as uncommitted working-tree state, which is the
    condition `/precheck` actually reviews. Fidelity is proven by a tree-hash match with the
    original commit, not by comparison.
  - A runner whose arms differ only in prompt. Tools are restricted with `--tools`, because
    `--allowedTools` restricts nothing.
  - The design record, reconstructed from transcripts after the fact, is
    `docs/design/sketchbook-1195-pmr-bench.md` (#1203). The bench is incomplete: arm A has never
    been run, and there is no judge yet.

### Fixed

- **Reseed auto-revive was a blind two-second keystroke (#1225).**
  - **The kick.** It was `(sleep 2 && tmux send-keys … continue) & disown`: fire-and-forget, with
    no check it landed and a "sent" log line either way, so revives were dropped whenever the TUI
    was slow. `reseed-kick.sh` (launched with `setsid`) now types `/reseed revive` with backoff
    until the `reseed-ack.sh` prompt hook acknowledges it. If nothing acknowledges it, it pages
    BJ. The hook no longer injects the seed.
  - **The seed path.** Seeds now live at one fixed, git-ignored path, `.claude/reseed-revive.md`.
    `/reseed revive` is the single revive command, typed by the kicker or by hand.
- **`install --local` doubled every kit hook on each re-run (#1225).** The settings merge compared
  the template's `~/.claude/...` hook paths against the local file's already-relocated absolute
  ones, never matched, and appended the whole kit again. This repo's local settings carried 16
  duplicate registrations, so the push gate, the secrets gate and both Stop detectors fired twice.
  - The template is now relocated before the merge.
  - `install` runs `assert-no-duplicate-hooks.sh --fix` and then the plain check on every settings
    file it writes, collapsing existing duplicates and aborting on any that survive.
- **`validate.sh` went red on any host with ShellCheck 0.11 (#1218).** 0.11 moved the
  function-level "never invoked" finding from SC2317 to the new code SC2329. `cleanup()` in
  `doorbell-oneshot.sh` runs only through `trap`, and nothing disabled SC2329. CI installs an
  older ShellCheck from apt and stayed green, so the failure appeared only locally. Both disables
  are now kept, and the file is verified clean under 0.9.0 and 0.11.0.

## [8.4.0] - 2026-08-29

### Changed

- **`/precheck`'s code-review re-runs now review only what changed since the
  last completed review (#1194).** Job D was invoked as "review all files
  changed on the branch vs main" on *every* pass, including re-runs after a
  fix — so verifying a two-line correction paid the full ~8-minute cost of
  re-reading a diff that had already been cleared minutes earlier. Three
  passes approaches 30 minutes, which is why a genuinely one-line fix could
  cost 15+ minutes and why agents drift toward filing follow-up issues rather
  than fixing inline (each new issue is another full cycle; the backlog
  symptom and the review cost are the same problem).

  Job D now has two prompts. The **first pass of every cycle is still the full
  `<base>` diff, unconditionally** — the complete diff is reviewed
  exactly once, as before. Re-runs use `git diff <snapshot>`, comparing a
  snapshot of the working tree as the last reviewer saw it against the tree
  as it stands now — so it covers *everything* changed since (uncommitted
  fixes, new commits, and edits to untracked files alike, not only the
  fixes), and carries the prior findings verbatim so the reviewer verifies each one —
  citing `file:line` — rather than rediscovering it. Jobs A, B and C stay
  unscoped on every pass, so the full test suite remains the backstop for
  cross-file breakage.

  Scope is decided by `scripts/ci/precheck-review-scope.sh`, not by prose in
  the skill, and the regression test drives that same script — one
  implementation, tested directly. The state is recorded **after** a pass
  returns and **only** when it returned a parseable verdict; an errored,
  refused, timed-out or empty return clears the marker instead, because a
  sub-agent replying "I could not access the repository" has technically
  *returned* and recording that as reviewed would permanently skip the range.
  Every unresolvable condition — missing marker, garbage marker, garbage-
  collected snapshot, rewritten history, or a state identical to the current
  one — resolves to **full**. There is no code path that yields "review
  nothing".

  **The trap this went through first, recorded because it is the obvious
  implementation.** The initial cut recorded `git rev-parse HEAD` and
  re-reviewed `<prev>..HEAD`. Code review caught that `/precheck` runs *before*
  the commit (`/scp` commits afterwards), so HEAD does not move between passes:
  `prev == HEAD`, `merge-base --is-ancestor` returns 0 because ancestry is
  reflexive so no guard fires, the diff is **empty**, and pass 2 reviews nothing
  while reporting success — on every cycle, not as an edge case. A two-dot
  commit range cannot contain uncommitted work. The shipped version snapshots
  the working tree with `git stash create` (non-mutating) and diffs
  `git diff <snapshot>`, which sees uncommitted fixes and new commits alike;
  untracked files are listed separately because a snapshot cannot contain them.
  The regression test asserts the non-empty delta directly against that
  scenario, so the bug cannot return silently.

  A second review pass then found the same *class* of hole one level down:
  untracked files were tracked by NAME, so an untracked file that existed at
  record time and was edited before the next pass was invisible in both
  channels — `git diff <snapshot>` never shows untracked paths, and a by-name
  set difference sees the name on both sides. Since `/precheck` is pre-commit
  and `/scp` does the `git add`, every new file is untracked for the whole
  cycle, so this was the normal case rather than a corner. Untracked files are
  now recorded as `<blob-hash> <path>`, which makes an edit differ. The test
  also gained a *narrowing* assertion: without one, regressing the snapshot
  back to `rev-parse HEAD` kept every safety check green while the feature
  quietly became a no-op that still cost the eight minutes it exists to save.

  A third pass found the same class once more, one level up: the **full**
  prompt never handed the reviewer untracked files, but `record` afterwards
  wrote them into the reviewed set — so a new file was skipped by pass 1 and
  then correctly omitted by the delta as "already cleared", shipping reviewed
  by nobody. Bookkeeping asserting a coverage claim the prompt never made.
  Both prompts now carry the untracked channel. Recording is pinned to
  *immediately on return, before any edit*, because fix-round-A → record →
  fix-round-B excludes round A from the next delta — the failure that looks
  like it worked. Untracked keys now describe what git will actually store
  rather than just file content: symlinks key on their target (`hash-object`
  follows the link, so retargeting between two same-content files was
  invisible), the exec bit is folded in (`chmod +x` changes what `git add`
  commits), non-regular files are never hashed (`git hash-object` on a FIFO
  blocks forever — a hung gate), and unhashable paths get a per-run nonce so
  they cannot compare equal to themselves and read as reviewed.

  A fourth pass then found the defect at the seam rather than in the logic:
  **both prompts handed the reviewer commands it has no tool to run.**
  `feature-dev:code-reviewer`'s tool list is `Glob, Grep, LS, Read, NotebookRead,
  WebFetch, TodoWrite, WebSearch, KillShell, BashOutput` — no `Bash`. And the
  delta's ref is a dangling `git stash create` SHA: zero refs point at it and it
  has no readable path on disk, so `Read` and `Grep` cannot reach it by any
  route. A reviewer told to fetch it would review nothing and report success —
  the same failure the ref arithmetic was fixed to prevent, re-entering through
  the prompt. (The plugin's own agent definition instructs "review unstaged
  changes from `git diff`", which that agent likewise cannot do.) Both prompts
  now **embed** the gathered content, matching `skills/review/SKILL.md`, with an
  oversize guard that writes a large diff to a file under `<marker_dir>` and
  hands the reviewer the absolute path to `Read` (falling back to `--stat` only
  if that write fails), rather than silent truncation. The reviewer keeps its licence to read wider
  than the diff — that is how it caught the `/devspec upshift` emitter in #1191,
  a file sharing zero lines with the change.

  Measured while diagnosing this: the reviewer reads the **full contents of
  every touched file** (4 whole-file `Read` calls, no offset/limit, zero `Bash`),
  ~47k tokens against a ~14k-token diff. Embedding the diff is therefore not
  merely a workaround for the missing tool — it cuts reviewer input ~3.4x on
  *every* pass including the first, where delta scoping only helps re-runs.

  A fifth pass caught the worst one, in the fix for pass 4's own advice.
  Switching the full prompt to `git diff <base>...HEAD` — to avoid phantom
  deletions if `<base>` advanced mid-cycle — replaced a small problem with a
  fatal one: **three-dot is a commit-to-commit range and excludes the working
  tree by construction.** In a pre-commit gate the changeset IS the working
  tree, so the embedded diff was empty. Measured on the branch itself:
  `git diff main...HEAD` returned **0 bytes** where `git diff $(merge-base)`
  returned **61,193**. The full pass would have handed the reviewer nothing and
  received "No findings" — the very failure delta-scoping was built to prevent,
  reappearing in the one channel delta-scoping does not touch. Fixed by
  resolving the merge-base to a SHA and diffing *that* against the working
  tree, which keeps merge-base semantics AND the uncommitted code.

  Two more from the same pass. `install` excludes `ci/*` from distribution at
  four sites, so `precheck-review-scope.sh` exists only in a cc-workflow
  checkout while the skill ships fleet-wide — every other repo got a failed
  invocation, empty stdout, and an empty "### Untracked files" heading that
  reads as "there are none": the script's own fail-open, reintroduced at the
  invocation boundary. A documented fallback now covers it (see #1141). And
  `resolve` printing `full` did not clear the untracked marker, pairing a full
  tracked diff with a still-delta-scoped untracked list; `full` now widens both
  channels together. `marker_dir` placement is enforced in the tool rather than
  asserted in prose.

  The regression suite had pinned the broken shape for the **third** time, and
  one new guard was itself blind (`[^>]*` terminates at the `>` inside
  `<repo_root>`, so it could never match).

  A sixth pass then found that the *replacement* guard was blind too, in a new
  way: `grep -F 'merge-base <base> HEAD'` was file-wide, and the explanatory
  blockquote above the prompt quotes that same command — so deleting the
  `### Diff` channel outright, or reverting it to bare `git diff <base>`, left
  the suite green. Verified by running both mutations. The guards are now
  scoped to the prompt block itself rather than the prose describing it, which
  is the same lesson the untracked-channel count already learned: **a guard on
  a critical must read the artifact, not the documentation of the artifact.**

  That pass also caught this entry overstating its own coverage — an earlier
  draft claimed the diff-form invariant "carries a live execution assertion
  instead of a grep". It does not. The live block exercises `git` against a
  throwaway fixture, demonstrating *why* the merge-base form is required; no
  edit to the skill can make it fail. The skill's use of that form is
  grep-guarded, now slice-scoped. Congratulating yourself for catching an
  overstated guard, in a paragraph that overstates a guard, is its own lesson.

  Two more from the same pass: the `### Diff` channel was the only one with no
  anti-empty rule — the very channel that failed at 0 bytes — so an unresolvable
  `<base>` (both `gh pr view` and `branch_guard` return branch *names*, which
  may not exist as local refs on a `kahuna/*` flight or a CI clone) would empty
  it silently; and `resolve` must run before `new-untracked`, since the former
  clears the markers that make the latter re-widen.

  Passes 8 and 9 closed the loop on the root cause. Twice more the fix itself
  shipped broken — `split` writing into a directory nothing created (so the
  anti-truncation path produced zero files, every time, and fell through to a
  degraded mode that looked like the design), and a size threshold sitting
  *above* the Bash tool's ~30k output cap, so the transport truncated the diff
  before any guard could fire. Both were **bash written as prose in a markdown
  file that nothing ever executes** — the third instance of that exact cause.
  It is now a tested `gather` subcommand: it writes the diff to disk (never
  through stdout), measures it, splits at 1500 lines, and returns one of
  `files <N> <paths…>` / `empty 0 <path>` / exit 2 with a reason. Four prose
  greps became executed assertions, including a losslessness check.

  Pass 9 then caught the one that mattered most: **the delta was a no-op.**
  `git stash create` builds a commit whose first parent is `HEAD`, so
  `merge-base(snapshot, HEAD)` returns `HEAD` — and `gather` applied merge-base
  unconditionally, collapsing every delta into `git diff HEAD`, i.e. the entire
  uncommitted changeset. The feature that exists to save eight minutes was
  spending all eight while appearing to work. Not even a safe superset: a fix
  that *reverts* a file to its committed content appears in
  `git diff <snapshot>` and vanishes from `git diff HEAD`, escaping review
  outright. It survived because every gather assertion passed the literal
  `main`, exercising only the full path; the narrowing check now runs through
  `gather` itself on a real delta ref.

  **The standing lesson from nine passes:** the script's logic stabilised
  early; almost every later defect lived in the *prompt seam*. A prompt is an
  interface with no type system and no execution, so its only failure signal is
  a reviewer saying "No findings" — indistinguishable from success. Validating
  that seam properly needs the historical-PMR bench (arm A vs arm B over real
  changesets), not hand-verification; a bench run would have caught the no-op
  immediately, because the delta would not have been smaller than the full pass.

  Three defects in this work were found only by mutating the tests rather than
  reading them — including a hostile-filename test whose fixture recorded
  *before* creating the files, so the very defects it targeted could not fire.
  A green suite proves nothing until you have watched it go red on purpose.

  **Deliberately NOT done:** making any part of precheck conditional or
  skippable by issue type, label, or file extension. #1191 was labelled
  `chore`, its own acceptance criteria said "no direct pytest coverage — it's
  a prose skill file," and its diff still contained a real Bash defect that
  only code review caught. Issue type is self-reported intent and says nothing
  about what a diff contains. Scoping a *re-read* is safe because the skipped
  code was genuinely reviewed; skipping a gate on a label is not.

  Also fixes Job D's hardcoded `vs main`, which reviewed the wrong range on
  repos whose default branch is `release/*` and on `kahuna/*` sandbox flights;
  it now uses the live default branch already resolved in Step 1.5.

### Fixed

- **`precheck-review-scope.sh` now ships with the kit (#1197).** It
  lived in `scripts/ci/`, which `install` excludes from distribution at four
  sites — while `skills/precheck/SKILL.md`, which depends on it, ships
  fleet-wide. Every agent outside a cc-workflow checkout would have received a
  Job D whose primary path invokes a tool that is not there, with only prose
  standing between that and a silently empty review channel. It was misfiled:
  unlike `dependency-scan.sh` and `check-scannable.sh` (genuinely dual-use, run
  by `validate.sh` *and* by skills — still #1141), this tool is invoked only by
  the skill. Moved to `scripts/`, so `install` mirrors it to `~/.local/bin/`
  like every other runtime helper. Verified by running install's own
  enumeration predicate, not by reading it — and that predicate is now pinned
  by a test rather than re-checked by hand.

  Resolution is a **ladder**, not a bare `command -v`. A name-only probe reports
  "missing" in two cases where the tool is present: `install --local` places
  scripts in `<repo_root>/.claude/bin`, which the installer deliberately keeps
  **off** `PATH`, and a cc-workflow checkout carries `scripts/` directly. A
  boolean probe would therefore have made the feature inert precisely where it
  is most exercised — including in this repo, which uses `--local` — while
  printing a false "kit not installed". The ladder tries `PATH`, then
  `.claude/bin`, then `scripts/`, and only then declares absence. It runs as a
  Step 0 pre-flight, ahead of the Step 2 call site, because a probe documented
  190 lines after first use is read too late.

- **`scripts/bootstrap-repo-labels{,-gitlab}.sh` no longer fail `shfmt`
  depending on which version you have installed (#1194, follow-on to #1191).**
  The rename guard added in #1191 used `((!old_exists))`. shfmt 3.8.x formats
  that as `((!x))` and shfmt 3.14+ as `(( ! x ))` — mutually exclusive, so the
  file could not satisfy both, and the fix that made CI green left `main`
  failing local validation for anyone on 3.8.x. Rewritten as
  `((old_exists == 0))`, which both versions format identically, with an
  inline comment so it does not get "simplified" back. The underlying cause —
  `validate.yml` installing `shfmt@latest` unpinned — is tracked in #1193.

- **`/issue doc` and `/devspec upshift` now emit `type::doc`, matching what
  `mcp-server-sdlc` v4.3.0 actually accepts (#1191).** `docs` (plural) was an
  agent-introduced myth, not legacy — `work_item`'s `type` enum canonically
  uses singular `doc` as of mcp-server-sdlc#541, with `docs` surviving only
  as a transitional alias mcp-server-sdlc#540 is removing. `/issue`'s skill
  body exposed the correct singular name to callers but silently aliased it
  to `docs` internally; dropping that alias surfaced a real, verified break
  — this GitHub repo's `type::doc` label never existed, only `type::docs`
  did (47 issues carried it), so `/issue doc` would have failed at
  label-application time. Fixed by renaming the live label in place (all
  47 issues preserved — verified via the REST API directly, since
  `gh issue list`'s own search index lags a rename by several seconds),
  not by creating a second label and splitting the taxonomy.

  Also fixed a second, independently-live emitter code review found:
  `/devspec upshift`'s own sub-agent prompt template still instructed
  `Type: <feature|bug|chore|docs>` — every doc-type Story created by that
  path would have hit the same now-deleted label. Bootstrap scripts
  (`scripts/bootstrap-repo-labels{,-gitlab}.sh`) now provision `type::doc`
  and `type::story` (a matching, independently-discovered gap: `SKILL.md`
  lists `type::story` under "Automatic Labels (always applied)" alongside
  `feature`/`bug`/`chore`, but its "On-demand Label Creation" table only
  covers `type::plan` and `epic::N` — every other `type::` label is assumed
  to pre-exist, and nothing had ever created `type::story` on this repo —
  fixed the same way, no split), and gained a one-time rename guard so an
  already-bootstrapped repo migrates its old `type::docs` label instead of
  ending up with both. The guard's existence check went through two rounds
  of self-caught bugs: a `:`-delimited old\|new pair collided with the `::`
  already inside GitHub/GitLab's `group::value` label names (fixed by
  switching to `\|`), and `gh label list` was proven live to lag a fresh
  label mutation by several seconds — replaced with a direct single-label
  REST GET, which is immediately consistent. A follow-up code review then
  caught the guard silently reporting success (exit 0) when both the old
  and new label already existed on a repo — exactly the split taxonomy it
  exists to prevent, since GitHub/GitLab reject a rename onto an existing
  name and the failure went uncounted; it now detects that case explicitly,
  fails loud, and exits non-zero.

  `tests/test_issue_skill.py`'s type-checking assertions were also
  regex-blind: a plain `t in frontmatter.lower()` substring check can't
  distinguish "doc" from "docs" since "doc" is a literal substring of
  "docs". Switched to word-boundary regex matching, verified against a real
  mutation. `docs/phase-epic-taxonomy-devspec.md` — the file `/issue`'s
  skill body names as its taxonomy's authoritative source — got the same
  frozen-content terminology annotation already applied to
  `docs/kahuna-devspec.md`, rather than an edit to its approved body.

- **The kit proved input existed, never that the scanner ingested it (#1137).**
  `check-scannable.sh` is a **pre-scan** denominator — "is there anything to
  scan?" — and it is good at that. But nothing in the kit ran the scan itself:
  the whole dependency check lived as **prose in `/precheck`'s Job C**, asking a
  sub-agent to report the count. It complied, which is the problem — an
  instruction can be forgotten by the next agent, misread, or dropped in a
  rewrite, and the resulting verdict looks identical to a real one.

  Two green checks either side of a stage prove nothing about the stage between
  them. flightdeck sits in exactly that gap: manifests present and countable,
  trivy parsing none of them (`bun.lock` unsupported per flightdeck#8 — a
  diagnosis worth re-measuring, see below), both checks green. **cc-workflow
  turned out to be a partial instance of the same thing** —
  2 scannable manifests, 1 ingested. Root cause, confirmed by measurement rather
  than assumed: not a `bun.lock` parsing limitation, but trivy suppressing
  dev-only dependency trees by default (both bun.lock manifests here are
  entirely devDependencies) — closed by passing `--include-dev-deps` and
  `--list-all-pkgs` (cc-workflow#1169's fix, ported into this script). Nothing
  had ever said so. flightdeck#8's own "unsupported" diagnosis may be the same
  flag artifact rather than a real ecosystem gap — worth re-measuring before any
  fleet-wide remedy assumes otherwise.

  `scripts/ci/dependency-scan.sh` runs the scan and reports what it **actually
  covered**, on every path including the passing one: manifests ingested, package
  count, and a `coverage: N of M` line. A shortfall is stated in the verdict
  itself (`PASS … (COVERS 1/2 — see WARNING above)`), so a copied PASS cannot
  quietly mean half a denominator. Exit codes distinguish conditions that used to
  look alike: **2 = manifests present but zero ingested** is not the same as
  **4 = nothing scannable**, and **5 = scanner/tooling error** (timeout, no
  output, unparseable output, or a partial install) is neither — a broken
  scanner is not an unparseable lockfile, and conflating them sends the
  operator hunting an ecosystem problem that does not exist. `trivy`
  absent is `3` / SKIP, because a hard dependency would make `validate.sh`
  unrunnable on a fresh box — which is how a check gets commented out rather than
  fixed.

  Wired into `validate.sh` (the lane CI runs) and into `/precheck` Job C, which
  now **invokes the tool** instead of describing the report it wants.

  **Scope, because the fix is narrower than the problem:** `install` excludes
  `ci/*` from distribution, so this script lives in a cc-workflow checkout and
  nowhere else. Every other repo still takes Job C's prose fallback — including
  flightdeck, the case that motivated the issue. Shipping it fleet-wide is #1141.
  Also emits the scanner version alongside the counts: a coverage shortfall could
  be an ecosystem limit *or* a stale binary, and the output cannot distinguish
  them without it. `.github/workflows/validate.yml` now installs trivy
  (previously absent, so this script returned 3/[SKIPPED] on every PR and had
  never actually run in the lane CI runs) — the scope limit above is about
  which repos carry the script, not about whether cc-workflow's own CI
  exercises it. Install is checksum-verified against trivy's own published
  checksums (guards transport corruption, not a compromised release — the
  checksums file ships from the same mutable release with no signature
  check), and its DB is cached to soften a cold ghcr.io pull on a repeated
  push to the SAME PR. Honest limit: GitHub scopes a `pull_request` cache to
  that PR's merge ref, so this cannot warm-start a *different* PR's first
  run — every new PR still pays the cold pull once.

  **Made actually true, not just claimed:** the scan now runs with
  `--ignorefile /dev/null` — trivy auto-loads a `.trivyignore` from the
  current working directory by default, which would otherwise make this
  scan's strictness depend on invocation location and let a committed
  ignore file silently suppress findings with nothing checking for one.
  Escape hatch that already existed and is now documented in `/precheck`:
  `DEP_SCAN_SEVERITY` overrides the severity filter for an operator who
  needs to unblock on an unfixable finding before #1188 (whether the gate
  should distinguish fixable from unfixable at all) is decided.

- **`sleep infinity` as PID 1 never reaps zombies — fleet-wide network dropouts (#1179).**
  aoe never runs an entrypoint into the agent; it `docker exec`s `claude` into an
  already-running container, so the top-level exec'd process is parentless from
  birth in that PID namespace (PPID 0 — its real parent, the containerd-shim,
  lives outside the namespace and reaps it fine). The zombies are its
  *children*: when that process forks work and exits without collecting them,
  the kernel reparents the orphans to the namespace's `child_reaper` — PID 1.
  The base image's own `CMD ["sleep", "infinity"]` never `wait()`s on anything,
  so a PID 1 that is merely "alive" never collects what gets reparented to it.
  At fleet scale — every exec, every session, every container, indefinitely —
  this accumulated to roughly 2,000 zombies and produced the network dropouts
  that made the containers unusable.

  Fixed by installing `tini` and declaring it the image's `ENTRYPOINT`, wrapping
  the existing `CMD ["sleep", "infinity"]`. **The first attempt shipped `tini` as
  `CMD` alone and code review caught that this is silently inert**: a trailing
  command argument to `docker run` (`docker run <image> sleep infinity` — the
  common keep-alive idiom for a tool like aoe) discards `CMD` outright but never
  touches `ENTRYPOINT`, so a CMD-only fix reverts to plain `sleep infinity` as PID
  1 with zombies resuming, no error, nothing to indicate why. Reproduced live
  before and after: `tini -- sleep infinity` reaps an orphaned exec'd child (0
  zombies); `sleep infinity` alone does not (1 `<defunct>` zombie).

  Pinned by three static Dockerfile checks (tini installed; `ENTRYPOINT`, not
  `CMD`, carries it; a keep-alive `CMD` still exists for tini to exec) and three
  tests against the built image covering the exact regression: PID 1 is tini
  with no override, PID 1 is *still* tini when a trailing command argument is
  supplied, and an orphaned exec'd child is actually reaped. Mutation-tested
  against a CMD-only variant and a CMD-less variant to confirm each new test
  fails on the variant it exists for before confirming it passes on the fix.

  **Side effect, not a regression:** `tini` installs signal handlers and
  forwards them, so `docker stop` now returns essentially instantly instead of
  burning the full grace period before SIGKILL (the old `sleep infinity` PID 1
  had no handler, and a PID-namespace init silently discards a handler-less
  signal even from an ancestor namespace). Faster teardown, and any in-flight
  `docker exec`'d session loses that grace window when the container is asked
  to stop.

  **Does not retroactively fix a running fleet.** This is an image change: it
  takes effect once a new image is built from a `v*` tag, promoted `:edge` →
  `:stable` per `docs/operations/image-release-cadence.md`, and a container is
  actually recreated from it — an already-running container keeps its old PID 1
  regardless of what merges here.

- **A quoted heredoc stops substitution but not termination (#1136).** #942's rule
  — write prose to a file with `<<'EOF'` — is correct and was incomplete. The
  quoted delimiter suppresses expansion; it does nothing about a body that
  *contains* a line equal to the delimiter, which ends the heredoc there,
  truncates the text, and executes the remainder as shell.

  Hit ten minutes after #942 merged, filing #1135: that issue's body documented a
  `vox <<'EOF'` example, so it contained a line that was exactly `EOF`. `gh` never
  received a coherent body, nothing was created, and it surfaced as a bash parse
  error rather than "your text was truncated" — the same misleading symptom #942
  is about. Same shape as #942's core observation, too: documentation explaining
  heredocs necessarily contains heredocs, so the hazard is worst precisely where
  the documentation is most useful.

  "Use a distinctive delimiter" is the weak mitigation — it works only if the
  author can predict the content, which converts a systematic property back into a
  per-invocation judgement call. **For agent-composed prose the guidance is now to
  avoid a shell heredoc entirely** and write the file with a tool that has no
  delimiter semantics (the `Write` tool). Heredocs remain sanctioned for fixed,
  author-controlled text, and the boundary is stated: whether you know the body in
  advance.

  Three new tests reproduce termination the same way the substitution cases were
  reproduced — including one that lets a "distinctive" delimiter collide with
  content *about* delimiters, demonstrating the weak mitigation failing on its own
  terms. Two further pins require the guidance to state the mechanism (not merely
  the word "terminate" — an earlier pin passed on an unrelated `/lazyriver`
  paragraph containing "terminates") and to name a working non-shell path.

- **Prose passed to a CLI as a double-quoted literal is executed by bash (#942).**
  Backticks and `$(...)` in a double-quoted shell string are command substitution,
  so documentation *about* commands *runs* those commands — and the span is
  **stripped from the text**, so the body silently loses content while the side
  effect happens. The 2026-07-20 near-miss launched `discord-watcher directmsg`
  and an MCP server that then blocked forever on stdin; the call hit its timeout,
  nothing posted, and the natural diagnosis was "network blip, retry."

  **Most of this was already fixed by a mechanism the issue did not anticipate.**
  Issue and PR bodies now go through MCP tools (`work_item`, `pr_create`,
  `pr_comment`, `disc_send`) where `body` is a JSON parameter that never reaches a
  shell — structurally immune, not merely carefully quoted.

  **The live residual was `vox`**, which takes prose on argv, has no `--body-file`,
  and which `/precheck` *prescribed* in the unsafe form — so the announcement fired
  on every gate and every merge was the most likely message to carry a tool name.
  `vox` already reads stdin, so the fix is guidance: `vox <<'EOF' … EOF`. Also
  corrected: `git commit -m "<prose>"` in the cross-repo recipe and `/prepwaves`
  (commit messages are the highest-volume agent-composed prose here), and the
  `/vox` shell example in `docs/skill-reference.md`.

  **The rule is narrower than "don't pass prose inline", and the narrow version is
  the one that works.** Substitution happens at **assignment** — `msg="see
  \`cmd\`"` has already executed by the time anything uses `$msg` — so hoisting
  prose into a variable relocates the symptom and fixes nothing. `msg="$(cat
  file)"` *is* safe, because expansion does not re-parse the value. The invariant:
  **prose must never appear as a double-quoted literal in shell source, anywhere in
  the chain.** A fixed literal with no metacharacters
  (`scripts/godspeed-lookback.sh:861`) is fine and was left alone.

  Pinned by `tests/test_body_never_inline.py` (17 tests, with #1136 below). Every hazard claim is
  reproduced against a marker tool that records actual execution rather than
  inferred from output shape, and each safe-form test has an unsafe-form twin that
  must execute — assertion-liveness (#922), because a suite that only shows the fix
  behaving safely cannot distinguish "fixed" from "this shell never substituted."
  The guards match **invocations, not characters**: scoped to lines that really run
  `git`/`gh`/`glab`/`vox`, permitting bare `"$var"` expansion, ignoring
  slash-command syntax, and honouring a declared `# ANTI-EXAMPLE` sentinel so
  documentation can show the hazard it forbids.

## [8.3.1] - 2026-08-20

### Fixed

- **The test suite wrote the operator's real `~/.gitconfig` on every run (#1130).**
  `tests/contained-workflow/test_bootstrap.py` drives the real `bootstrap.sh` by
  subprocess with `OAW_HOME` redirected to a tempdir — but not `HOME`.
  `ensure_github_auth` runs `git config --global`, and git reads `$HOME`, so every
  run rewrote the host config, silently reinstating a `url.…insteadOf` rewrite the
  operator had deliberately removed after a token leak forced a roll. Reproduced
  with a canary `HOME`: one test, one `.gitconfig`, byte-identical to the block on
  the host.

  **Two things made this worse than a stray write.** It is invisible —
  `git remote -v` and `git remote get-url` both report the *rewritten* URL, so 32
  repos stored as `git@github.com:…` were authenticating with a broadly-scoped PAT
  and nothing said so (only the `ssh://git@github.com/…` spelling escapes the
  rewrite). And it contaminated our own reasoning: `CHANGELOG.md`, the `bootstrap.sh`
  comment, and a test docstring all justified keeping the rewrite by citing that
  `~/.gitconfig` as evidence of operator intent — evidence we had written ~29 hours
  earlier. A leak that corrupts files is recoverable; one that corrupts your evidence
  argues for its own continuation.

  Fixed by `_sealed_env`, which seals `HOME`, `XDG_CONFIG_HOME` and `OAW_HOME`
  together and is now the only sanctioned way to drive the bootstrap;
  `test_beacon_is_silent_on_stdout` likewise no longer runs against the ambient
  `HOME`. Guarded by `test_bootstrap_never_writes_the_operator_home`, which asserts
  the operator's home is **empty** — not merely free of `.gitconfig`, since the next
  leak will have a different filename. Mutation-tested: removing the `HOME` seal
  turns it red with exactly `.gitconfig`.

- **Operators: check your own `~/.gitconfig` (#1130).** The fix stops the leak; it does
  not clean up what three weeks of test runs already wrote. Any host that ran this
  suite still carries the planted block, invisibly routing `git@github.com:` remotes
  onto the PAT — and `git remote -v` will not show it, because it reports the
  *rewritten* URL:

  ```sh
  git config --global --get-regexp '^url\.'          # planted? (git remote -v won't tell you)
  git config --get remote.origin.url                  # the RAW stored remote
  git ls-remote --get-url origin                      # where git will ACTUALLY connect
  ```

  To remove it:

  ```sh
  git config --global --unset-all url."https://github.com/".insteadOf
  ```

  Leave `credential.https://github.com.helper` alone — it is inert for SSH remotes and
  correct for a genuine `https://` one. **Container git is unaffected:** aoe mounts the
  host gitconfig at `/root/.gitconfig` while the agent runs as `ubuntu` with
  `HOME=/home/ubuntu`, and there is no gitconfig parity step, so the host block never
  reached container git.

- **Removed the github URL rewrite from the container (#1130).** With the evidence
  for it withdrawn, the question was re-asked on the container's own merits and the
  answer is no. #1082's diagnosis (container git broken) was right; the cause was
  that the mounted keys were unreachable to the runtime user, fixed by #1085 plus
  `ensure_ssh_parity`. Measured in a live container: `ssh -T` succeeds for both
  forges and `git ls-remote ssh://git@github.com/…` resolves. A rewrite only
  redirects a working SSH path onto a token that also carries full API scope. The
  credential helper stays — inert for SSH remotes, correct for a genuine `https://`
  one. `test_git_transport_matches_the_host_per_forge`, which pinned the wrong
  premise, is replaced by
  `test_git_transport_is_ssh_for_both_forges_with_no_url_rewrite`.

## [8.3.0] - 2026-08-19

### Added

- **Releases carry a registry tag (#1122), and the registry backlog is cleared (#1100).** The image build pushed exactly one tag — `:edge` — so v8.1.1's image was indistinguishable from any intermediate build: retention had no anchor and rollback meant reading OCI labels off candidate digests one at a time. A tag-triggered build now publishes `:vX.Y.Z` **alongside** `:edge` at the same digest, applied as extra `-t` flags on the one `buildx build --push` so the tags name one digest by construction. `workflow_dispatch` still gets `:edge` only — a manual build is a candidate, not a release (#1063).

  `scripts/ci/backfill-release-tags.sh` gave the already-published releases their tags, reading each version from the image's own `org.opencontainers.image.version` label rather than a hand-typed list — a second source of truth can disagree with the artifact, silently. It excludes index **children**: a release digest is an index, its children inherit the same version label, and a naive pass proposed every tag twice with the second write leaving `:v8.1.0` pointing at an attestation manifest. Caught by the dry run.

  **Executed 2026-08-06:** v7.2.0 → v8.2.0 tagged; the registry went from **248 versions to 40**. Every release tag resolves to its original digest, cosign still verifies the fleet's pin, and `aoe-preflight.sh dogfood` passed 15/15 on a real container launch afterwards. Retention now keys on `v*` tags, with `--keep-recent` demoted to a backstop for unreleased candidates.

- **`registry-prune.sh` — clear the GHCR backlog without deleting what the fleet is running (#1100).** 248 versions had accumulated, 155 of them untagged. The standard GHCR recipe is "delete all untagged versions", and running it would have deleted the live fleet's image: a profile pins a **bare digest**, which is correct — it is what makes a release immutable (R-05/R-23) — but leaves no tag behind, so a pinned, actively-running image is indistinguishable from garbage to any tag-based rule. **Untagged does not mean unused**, and the failure is delayed and disconnected: nothing breaks at prune time, it breaks at the next container launch.

  The keep-set is computed from what is actually referenced — profile pins, named tags, a rollback window of the last N manifests, and each survivor's cosign `.sig`/`.att` (a signature orphaned from its subject verifies nothing). **Dry-run by default**; `--apply` is a separate act. It **refuses** on an empty pin list or an empty registry listing rather than concluding there is nothing to protect — the two states in which it would propose deleting everything.

  The rollback window exists because releases are not identifiable in the registry: the build pushes only `:edge`, never `:vX.Y.Z`, and `:stable` has never been created, so v8.1.1's image looks like any intermediate push. Retention is therefore host-side only — the pins live in `~/.config/agent-of-empires/`, so a scheduled Action would run with an empty pin list. Policy documented in `docs/operations/image-release-cadence.md`.

- **Containerised agents have a voice again (#1084).** `vox` could not work inside a container — no provider config, and no player at all (none of `afplay`/`paplay`/`aplay`/`ffplay`, no `libpulse`) — so every agent moved into a container lost the audible interrupt, the thing that gets attention when nobody is watching a Discord channel.

  **Text is forwarded, not audio.** The container's provider spools the message onto a host-visible mount and a `systemd --user` path unit runs the operator's own already-configured `vox` on it. Mounting the host's PipeWire socket was considered and rejected: with no client libraries and no player in the image it would mean adding an entire audio stack to play one sentence, and coupling containers to the host's audio devices.

  No change to `vox` itself — it already resolves `~/.config/vox/{provider,player}` ahead of its bundled defaults, so this is configuration. The **pair** is the mechanism: the provider forwards text and writes an empty `$VOX_OUTPUT_FILE`; the player is a no-op because playback happens on the far side of the mount.

  **Emphatically not `silent.sh`.** Pointing the provider there would also stop the error — by making the agent mute while it believes it has spoken, converting a visible gap into an invisible one. So the provider is **loud when nothing is draining the spool**, which is the assertion that keeps the feature from rotting: that failure is otherwise invisible from inside the container. The drain drops messages older than 15 minutes rather than speaking a stale backlog, and deletes before speaking so a message `vox` rejects cannot be re-spoken forever by a `DirectoryNotEmpty` path unit.

  The host side is one explicit operator command, `oaw-vox-drain --install-units`. `./install` deliberately does not touch systemd: installing units from the kit installer would mutate the operator's running session state under live sibling agents, the exact side effect the contained-workflow campaign exists to eliminate. Runbook: `docs/operations/containerised-vox.md`.

  Adds a `vox-spool` mount (`shared-mutable-rw`, sandbox-scoped and major-partitioned under `~/.oaw/state/<major>/`), so **aoe profiles must be regenerated** — it takes effect on container recreation, leaving running agents untouched.

### Fixed

- **`wtf-post-tool-use.sh` was baked into the image twice, and now cannot be (#1094).** The image's `settings.json` registered it under both `~/.local/share/…` (from `settings.template.json`) and `/home/ubuntu/.local/share/…` (added afterwards by wtf-server's installer, whose idempotency check compared raw strings). Same file, so the hook **ran twice on every tool use** — for weeks, because nothing ever asked the question.

  The source is fixed in mcp-server-wtf#34, but fixing one installer does not close the class: every MCP server's `install-remote.sh` writes hook registrations into that same file during the build, each with its own notion of "already present". So the build now asserts the invariant with `scripts/ci/assert-no-duplicate-hooks.sh` — no two commands under one matcher may **resolve** to the same script. It runs last, after `./install` and every MCP installer have had their say, so it checks the state that actually ships rather than the template's intent.

  Identity is the script, not the spelling: `~/`, `$HOME/` and `${HOME}/` are expanded, arguments ignored, and the `[ -x … ] || exit 0;` guard (#1107) stripped — keying on its leading `[` would call a guarded and a bare spelling two different hooks and report all-clear, which is this bug re-admitted on every container the fleet actually runs. A settings file declaring **no** hooks exits non-zero rather than passing, because an empty denominator is the same shape as the original defect: a question nobody asked.

- **Merged kit hooks no longer break older-image containers (#1107).** `sync_kit_hooks` (#1086) merges the image's hook wiring into `$CLAUDE_CONFIG_DIR/settings.json` — one file shared by every container on the host, **across image versions** — while the hook scripts are image-versioned. A hook new in release N was therefore registered for containers running N-1, and every SessionStart there failed with a missing-hook error. Measured live: 5 of 7 running agents were on older digests referencing `kit-hooks-alive.sh`, which their images do not contain.

  The beacon is *designed* to be absent from older images — that is how #1086's preflight was proven able to fail red-first — so writing it into shared state guaranteed the exact failure it exists to detect, in the wrong place.

  Path-rooted commands are now stored self-guarding, `[ -x <path> ] || exit 0; <path>`, the same convention aoe already uses for its own hooks in that file. Absence becomes inert instead of fatal, and **the hook still runs wherever the script is present** — both halves verified against live containers, not just fixtures. Dedup keys on the *unguarded* command, so the guarded and bare spellings of one hook do not register as two (the #1094 duplicate-execution shape, one layer out). Only conservatively-shaped heads are wrapped: the head is spliced raw into the test, so a metacharacter in it would produce `[ -x /p/x.sh` with no closing `]`, and the trailing `|| exit 0` would then silently swallow a hook whose script is present.

  **Pre-existing bare entries are upgraded in place and duplicates are pruned**, which is what makes the shared file *converge* rather than merely improve. An older image's `sync_kit_hooks` has no notion of the wrapper: it sees head `[`, judges its own bare spelling absent, and appends it — so without a prune the next new-image boot rewrites that copy into a second guarded one and never removes it, and alternating boots between digests grow the list without bound. Mixed digests is the premise of this bug, not an edge case. The prune is scoped to hooks the image ships, so aoe's own wiring is never touched.

  `validate_hook_paths` unwraps the guard rather than skipping it — going blind would trade a noisy failure for a silent one — and stays loud for **unguarded** misses while treating a guarded miss as the declared-inert case it is. The cases a guard could hide are caught in `sync_kit_hooks` against the image that claims the hook: one it never shipped, and one shipped without its exec bit (the guard tests `-x`, so that is skipped exactly like a missing file, where it previously failed loudly with `Permission denied`). That check runs over the image's declared hook set on **every** boot rather than inside the add-if-absent loop, where it would have fired once against a virgin config dir and stayed silent forever after.

  Caught by the operator on a live restart and by no test: the #1086 suite drove the merge against fake homes where the script always existed, so the cross-version case was not representable. It is now — the tests delete the script after merging, which is precisely what an older container sees.

- **`/mmr` and `/scpmmr` could grade the wrong pipeline run and call a merge green (#1124).** Post-merge, both skills called `ci_wait_run` with no `expected_sha`, so the tool graded whatever run was newest *in the list at that moment*. A merge always has some propagation delay before its own run is dispatched, so inside that window the call reads a **previous** merge's already-completed run and returns `ok:true, final_status:"success"` for a commit nobody asked about. Reproduced live (`mcp-server-sdlc#523`): `waited_sec:0` paired with the wrong `sha` was the **only** tell — no error, no warning, and the shape of a fast green. Both call sites now thread `merge_commit_sha` from `pr_merge` through as `expected_sha`, and both are pinned independently by the `TestPostMergeCiWaitUsesExpectedSha` class — `/scpmmr` spells out its own `ci_wait_run` call rather than deferring to `/mmr`'s, so a pin on `/mmr` alone would leave the second call site free to regress with CI green.

  **The `ref` must track the real merge target, never a literal `"main"`** — code review caught that in the first draft, and it is the more dangerous half. On the KAHUNA sandbox path the merge lands on `kahuna/<N>-<slug>`, so pairing a hardcoded `main` with the new `expected_sha` filter would query for a commit that exists on neither ref — converting a silent wrong-green into a hard failure on **every** sandbox merge, i.e. precisely the auto-approved path with no human present to read the mismatch and move on. It now reuses the target `branch_guard` already validated in step 1. Where `merge_commit_sha` is legitimately absent (the merge did not complete synchronously), the skills resolve the target's HEAD or skip the wait — they do not fall back to the unfiltered call that caused this.

## [8.2.0] - 2026-08-05

### Added

- **Containerised agents can build, run and scan container images (#1108).** `podman` is baked into the image, closing the gap that blocked a partner repo's task (swap a runtime image to distroless, shedding 23 unfixable CVEs, 4 CRITICAL) — a containerised agent could not verify it at all. The near-miss is the reason this is `Added` and not deferred again: the agent that hit the gap proposed putting a container-generated key in the operator's `authorized_keys` so it could build on the host. **A missing capability does not just block work, it generates pressure to solve the wrong problem.**

  **⚠️ Host prerequisite — without it the capability reports absent.** Docker's `default-runtime` must be `sysbox-runc`. Under stock `runc` podman cannot create its nested user namespace at all, and `aoe` cannot pass `--runtime` per container (its `[sandbox]` schema has no such key, and `container_runtime` selects the *engine*, not the OCI runtime — agent-of-empires#3218), so this is a daemon-level setting made once per host:

  ```json
  {
      "live-restore": true,
      "default-runtime": "sysbox-runc",
      "runtimes": { "sysbox-runc": { "path": "/usr/bin/sysbox-runc" } }
  }
  ```

  Set `live-restore` in the *same* edit — without it every future daemon restart kills every running container, including live agent sessions. Note also that sysbox rejects `--privileged` and `--network host`; nothing in the fleet uses either, and the opt-out for another workload on the same host is one explicit `--runtime=runc`. Before installing sysbox, pin `bip` and `default-address-pools` to the host's **current** values: its installer otherwise sets `bip` to `172.20.0.1/16` (already occupied by an unrelated project's network on malory) and replaces docker's built-in pools with a single `172.25.0.0/16`. Its precondition check is purely textual, so declaring the existing values both satisfies it and makes it a no-op.

  **Not a docker socket mount**, and the reason is capability rather than trust: over a socket `docker build` runs on the *host* daemon, so the build context and bind-mount paths resolve to host paths the agent cannot see, and concurrent agents collide in one image namespace. **Podman runs as root inside the container** — the mode sysbox is built for, since container-root maps to an unprivileged host uid. Rootless was tried first and is structurally impossible: the kernel refuses an unprivileged procfs mount unless the parent `/proc` is fully visible, and sysbox-fs overlays it, so any Dockerfile with a `RUN` step dies on `mount proc to proc: Operation not permitted`. Elevation is scoped to `/usr/bin/podman` alone via `sudoers.d` plus a PATH wrapper — deliberately not blanket sudo, because a root-written file on a bind mount surfaces as **uid 0 on the host**, which would let agents strand root-owned files in the operator's workspaces. Storage is `vfs`: podman falls back to fuse-overlayfs, which under sysbox dies on `/proc/sys/kernel/overflowuid` (readable at the container's top level, `EIO` from the nested userns), and `mount_program = ""` does not force kernel overlayfs.

  `aoe-preflight.sh` gains a behavioural check backed by `scripts/ci/container-builder-probe.sh`, which **insists on a Dockerfile with a `RUN` step** — a `COPY`-only build succeeds even where nesting is impossible, so a build-only probe reports health on a host that cannot run anything. Its exit codes keep three outcomes apart that a single red/green would merge: broken in our image (fails), host cannot nest (reported as a declared absence with the reason, since the kit's contract is the image digest and this depends on host config outside it), and probe unavailable (no verdict — the base image is pulled from ECR Public rather than Docker Hub after the first real run hit an anonymous rate limit).

## [8.0.0] - 2026-08-03

### Changed

- **Container SSH parity — the operator's keys were mounted and invisible (#1089).** aoe mounts `~/.ssh` to `/root/.ssh` (keys plus a host→identity config) and agents use them constantly: git over SSH for both forges, and troubleshooting remote installs (partner hosts, `agent-smith-ca`), where no token substitutes. The agent runs as `ubuntu` with `HOME=/home/ubuntu`, so `ssh` looked in an empty `/home/ubuntu/.ssh`, fell back to default identity names, and failed `Permission denied (publickey)`. Before #1085 made `/root` traversable it could not have worked at all. `ensure_ssh_parity` links `~/.ssh` to the mounted keys — idempotent, clears `ssh`'s own `known_hosts` scratch dir (which silently appears and made a naive `ln -s` land *inside* it), and refuses loudly to clobber a real `~/.ssh`. Measured after: `ssh -T git@gitlab.com` → *Welcome to GitLab*, and `git ls-remote git@…` succeeds on **both** forges.

  **This also corrects #1082 and retires machinery it added.** That fix concluded, from `gh api user` passing while `git push` failed, that git needed HTTPS+token, and added `url.https://github.com/.insteadOf` plus `credential.helper = !gh auth git-credential`. The diagnosis was half right — git transport *was* broken — and the remedy was wrong: git failed because the mounted keys were unreachable, not because a credential was missing. Routing git onto HTTPS+token worked, but it **changed behaviour rather than restoring it** and bypassed keys provisioned on purpose. The github rewrite was **restored** after review: the operator's own `~/.gitconfig` carries `url.https://github.com/.insteadof` and the gh credential helper, so HTTPS+PAT *is* what a host session uses for github — #1082 was right, and removing it diverged. **[CORRECTED by #1130 — this sentence is wrong, and wrong in an instructive way. That `~/.gitconfig` was written by our own test suite: it sealed `$OAW_HOME` but not `$HOME`, so every run of `tests/contained-workflow/test_bootstrap.py` executed `git config --global` against the operator's real home. The rewrite entered `bootstrap.sh` on 2026-07-31 and this claim was written ~29 hours later, so the "evidence" was almost certainly our own side effect read back as host intent. It is also moot: SSH covers git for both forges in the container (`ensure_ssh_parity`), verified live. The rewrite is removed and the leak sealed.]** gitlab has no host rewrite and stays SSH. The premise "the host uses SSH for git" was true for one forge and generalised to both; a test now pins **both** halves, since pinning either alone is what went wrong. Documented rationale claiming the container deliberately has no `~/.ssh` was **inference from a permissions bug presented as design intent**, and is corrected in `architecture.md` rather than quietly dropped.

  `glab` gains an API credential (file, mode 600, `git_protocol: ssh` matching the host) from the whole-dir secrets mount, unblocking MR/CI work. Its token shape guard accepts `.` — real `glpat-` tokens contain dots, and the first cut rejected the operator's actual token while a dot-free fixture passed. The operator's `~/.local/bin` (139 utilities) is also mounted read-only at `/home/ubuntu/.oaw/overlay/local-bin` and **appended** to PATH — never prepended, since the kit's own bin holds the claude wrapper (#1076) and the MCP binaries, and shadowing it would silently un-bootstrap every agent. Profiles must be regenerated or `check-mount-drift.sh` fails and the mount silently does not happen (the #1069 class).

- **`~/.secrets` is mounted whole-directory read-only again, restoring host-agent parity (#1090).** Reverses the named-single-file scoping from #1061 on an operator decision, recorded so it is not silently restored: *"they all get used by agents one time or another. I don't want to curate which agents will need what access via who's tokens. I just want every agent to have access to all those tokens like they do today."* Two corrections to the #1061 rationale made it reversible: **mounted is not baked** — R-12 keeps secrets out of every image layer and `mounts.d/` entries are *runtime* binds, so "an OaW image on a public registry" was never an argument against a runtime mount (the original framing conflated the two) — and **the trust model is unchanged**, since every *host* agent already reads all ~80 entries; per-agent curation bought no security the fleet does not already grant, and #1089 showed it merely moves the blocker to whoever needs the next credential.

  **Availability and inheritance are separate axes, and only availability widened.** Everything stays **path-modality**: a file must be deliberately opened, whereas an environment variable is inherited by **every child process**. `OAW_SECRET_ENV` remains limited to `CLAUDE_CODE_OAUTH_TOKEN` (the exception argued narrowly in #1076 — that token *is* the agent's identity, so a child stealing it gains nothing the agent lacks), and `gh`'s credential is still written to a file rather than exported (#1082). MCP servers follow the same rule: `disc-server`/`discord-watcher` consume `DISCORD_TOKEN_FILE`/`DISCORD_TOKEN_PATH` — **pointers**, not values — so a new MCP credential gets a pointer line, never a value. Verified on the built image: 81 secrets visible as files, `GH_TOKEN` still absent from the agent environment.

  **The scoping guard was replaced, not deleted.** `test_secrets_mounts_are_scoped_not_whole_dir` existed specifically to stop a silent widening, and its docstring said so; removing it would have left a tripwire's worth of nothing. Widening is now intended, so the guards moved to the invariants that still matter: the mount must be **whole-dir and `ro`** (an `rw` mount would let a container corrupt the operator's entire credential store), and **no secret beyond the documented exception may be env-projected** — which is the real risk once 80 credentials are reachable. Both mutation-tested, along with a scope-back-to-named-files mutation. The separator check that rejects a sibling such as `~/.secrets-partner/…` was preserved while allowing the directory itself; a bare `startswith` would have quietly accepted the sibling.

  Side benefit for R-13: a credential added on the host now appears in every running container immediately, where previously it needed a new mount fragment and a relaunch.

### Removed

- **Slack support, entirely — `/ping`, `/pong`, and `slackbot-send` (#1062).** Both skills were wholly Slack-specific (`#ai-dev`, Slack mrkdwn) with no Discord path, and unused. Removed with them: the `~/.secrets/slack-bot-token` dependency (`deps.json`), the `slack-bot-token` entry in the image build's expected-missing whitelist, the `slack@claude-plugins-official` marketplace plugin (enabled by default with **zero consumers** — its only documented purpose was OAuth on first `/ping`/`/pong` use, so it was costing context every session for a dead integration), and the README's "Slack Setup" section, which instructed new users to provision a bot token for a skill that no longer exists.

  **Already-installed hosts are pruned.** Deleting a skill from source does not uninstall it — `install` walks the surviving `skills/*/` and prunes *within* each, so a skill that vanishes from source is never visited. `~/.claude/skills/ping`, `~/.claude/skills/pong`, `~/.claude/scripts/skills/ping`, and `~/.local/bin/slackbot-send` are now in `DEPRECATED_PATHS`. Without that, the upgrade would have been *worse* than no change: `cellar_deploy` wipes the Cellar copy of `slackbot-send` while `~/.claude/skills/ping/SKILL.md` survives, leaving `/ping` a live, invocable skill whose helper had just been deleted. Guarded by a regression test that plants the installed copies and asserts they are gone.

  **Known gap:** `scripts/install-remote.sh` has no `DEPRECATED_PATHS` mechanism (pre-existing), so tarball-installed hosts retain `/ping` and `/pong` until they are removed by hand.

  Mattermost is the intended successor (partner self-hosted; better IP posture), post-cutover, behind a backend abstraction at the MCP-server layer.

### Fixed

- **`CLAUDE_CONFIG_DIR` pointed at an unreachable `/root` — settings, MCP registrations, onboarding state, workspace trust and credential lookup all landed where the CLI never reads (#1085).** aoe launches with `CLAUDE_CONFIG_DIR=/root/.claude` and mounts its own config there; the image runs as `ubuntu` and `/root` ships `0700`, so the runtime user could not **traverse** it — every path under it was EACCES even though `/root/.claude` itself was ubuntu-owned. **One unobserved variable, five production symptoms:** a Settings Error panel at startup (and the CLI skips files with errors **entirely**, so all hooks and permissions were lost), zero MCP servers, the onboarding wizard on every launch, a trust prompt per workspace, and `401 OAuth access token has been revoked` for a token that returned **HTTP 200** at that moment — the actual culprit being a `.credentials.json` ten days old, which the CLI prefers over `CLAUDE_CODE_OAUTH_TOKEN`.

  **Why three prior fixes did not catch it.** #1076, #1079 and #1082 were each verified green and each partially bypassed in production, because every verification used `docker run` with the profile's `extra_volumes` — which reproduces the **mounts** but not the **launcher**. Only aoe sets `CLAUDE_CONFIG_DIR`. The lesson is not another assertion: *a harness that reproduces the inputs but not the invoker is not a rehearsal.* Hence `scripts/ci/aoe-preflight.sh`, which launches through aoe and asserts eight behaviours from inside the resulting container — proven able to fail by running it against the unfixed image, where it caught exactly the two real defects.

  **Fixed:** `chmod 711 /root` in the image (traverse, not list — `ls /root` still fails); bootstrap resolves the CLI's config through `CLAUDE_CONFIG_DIR` and writes onboarding/trust there; the image's baked `mcpServers` are merged into that file **additively under `flock`**, since it is shared by every container on the host and also carries the operator's own servers; a stored `.credentials.json` is reported at boot with its path and the fact that it **outranks** the mounted token, so a 401 arrives with a filename instead of a wrong accusation; and configured hook paths are validated to resolve **in this namespace**, after production hit `/home/bakerb/.local/share/wtf-server/hooks/wtf-post-tool-use.sh: not found` — a category error, since a host absolute path cannot resolve in a different filesystem namespace.

  The credential store stays **shared on purpose**: the fleet is rate-limited roughly weekly and rotates through several accounts, so one login reaching every agent is a requirement, not a leak. An earlier draft recommended isolating it and was wrong — isolation would have cost one interactive login *per agent* per rotation.

  **Three instrument defects were found in the new tooling itself, each failing in a different direction:** the hook validator's regex matched the slash *after* `$HOME` and reported **13 phantom paths** against a healthy container; the pre-flight's auth check grepped a merged stream and matched the word "revoked" **in its own advice text**, failing a container that authenticated perfectly; and one test invoked bootstrap by a relative path from a temp dir, so it silently exercised nothing. An instrument that cries wolf is worse than none — it teaches the operator to ignore the one warning that will someday be real.

- **Containerised agents could not authenticate to GitHub (#1082).** Found in cut-over pre-flight. An agent reached a prompt and authenticated to Anthropic (#1076/#1079) but `gh` had no credential, so it could not push, open a PR, merge, or run `/scpmmr` — it could think but not land work. Everything else in the pre-flight passed: 39 skills, all five MCP binaries executable, transcripts and memory host-visible (so resume survives container death), workspace writes host-owned as uid 1000, secrets scoped to 2 of ~80. **Fixed with file modality, not env** — `bootstrap.sh` materialises `~/.config/gh/hosts.yml` (mode 600, written under `umask 077`) from a named read-only `github-pat` mount. The host authenticates `gh` via `GH_TOKEN` and copying that pattern would have been one line and the wrong one: an environment variable is inherited by **every child process**, and the only working GitHub credential here carries `admin:enterprise`, `admin:org`, `delete_repo`, `delete:packages` and more. The `CLAUDE_CODE_OAUTH_TOKEN` exception (#1076) was argued narrowly — that token *is* the agent's identity, so a child stealing it gains nothing the agent lacks — and an org-admin PAT does not meet that bar. An operator-placed credential is left alone (host-**scoped**: a bare `grep oauth_token` matches a comment or another forge's token and would log "left alone" while leaving github.com unauthenticated); a missing or empty secret warns and boots, since an agent without GitHub access is degraded but useful while a fatal would mean no agent at all — and `github-pat` is deliberately **not** in `OAW_REQUIRED_SECRETS`, since declaring it required would make R-14 fatal one function earlier and render that documented degraded mode unreachable.

  **Authenticating `gh` was only half the fix, and the first cut shipped the wrong half.** `hosts.yml` authenticates the CLI; `git push` never reads it, and `gh pr create` shells out to `git push`. Verification had been `gh api user` — which passes while the agent still cannot land a commit, because repos carry `git@github.com:` origins and the mounted SSH keys were unreachable to the runtime user (**corrected in #1089** — an earlier draft of this entry claimed the container deliberately had no `~/.ssh`; that was inference from the #1085 permissions bug, not design intent, and the URL-rewrite remedy it justified has since been removed). Measured before the fix: `git push --dry-run` → `Host key verification failed`. Now bootstrap also sets, scoped to github.com, `credential.https://github.com.helper = !gh auth git-credential` **and** `url.https://github.com/.insteadOf = git@github.com:` — only together do they work, since the rewrite is what makes the helper get consulted at all. Proven: `git push --dry-run origin HEAD` → `* [new branch] HEAD -> …` against the real remote. This was exactly the "Config Existence ≠ Config Works" trap in CLAUDE.md, walked into by the change that cites it.

  Also fixed, both latent since #1061 and surfaced by declaring a new secret: **`${!name}` on a hyphenated secret name is a bash ERROR, not an empty lookup** (`github-pat: invalid variable name`), which under `set -e` killed the boot *at that line* — before the fatal, before the accumulate-all-fatals list, before the summary, leaving only a bare bash error to explain why a container had no agent. The existing R-14 tests could not see it: they assert `returncode != 0` plus the secret name in stderr, and bash's own error satisfies both. And `check-mount-drift.sh` told operators to `mkdir -p` a path that must be a **file** for every secret added since its hand-maintained list was written, creating the empty directory its own comment warns about.

  Mutation-tested throughout, including the tempting `export GH_TOKEN="$token"` one-liner. The never-project-to-env rule is now **enforced in the projection loop** rather than asserted in comments — servers enforce, docs suggest. One review remedy was **rejected on measurement**: `gh auth token --hostname github.com` performs a config migration that makes a network call and returns non-zero on a merely-expired token, so it would clobber an operator's credential precisely when stale; an offline host-scoped awk scan replaced it. Known gap, not fixed here: `vox` has no audio from a container (`/dev/snd` absent), so Discord remains the notification path.

- **Containerised agents parked on the first-run onboarding wizard (#1079).** With auth fixed (#1076), a fresh container still never reached a prompt: it walked theme → login menu → trust folder, and an agent parked on a wizard is operationally identical to one parked on a login menu. Provably **not** a credential problem — the stored token returns HTTP 200 and headless `claude -p` succeeds. The contract turned out to be exactly two keys in `~/.claude.json`, derived empirically against the real image rather than guessed: `hasCompletedOnboarding`, plus `projects[<cwd>].hasTrustDialogAccepted`. Two results contradict the obvious guess and are why the fix looks as it does: **`theme` is not part of it** (`hasCompletedOnboarding` covers the theme step), nor is `lastOnboardingVersion` — fortunate, since baking a version string would drift on every base-image CLI bump — and **`--dangerously-skip-permissions` does not bypass the wizard**, so the agent's own flags cannot be relied on. Trust is recorded **per project** and is path-sensitive (trust for `/home/ubuntu` while running in `/workspace` still prompts), so there is no build-time value to bake; `bootstrap.sh` sets it from its own `$PWD`, which is the agent's cwd precisely because the wrapper *sources* it in the agent's process. The write merges rather than replaces — the same file carries the baked MCP registrations — under an exclusive `flock` held across the whole read-modify-write, serialising the JSON fully before touching the file. Both matter because bootstrap now runs on *every* `claude` invocation: unlocked, two interleaved runs lose an update, and the lost update **is** this bug (A reads, B reads, A writes `trust[a]`, B writes without it, agent A parks on the dialog forever); and `open(..., "w")` would truncate at open and stream, leaving a window in which an interrupted write destroys the MCP registrations. It writes in place to preserve ownership and mode — which protects an `ubuntu`-owned file when bootstrap runs as root — **not** because the file might be a bind mount, a rationale given in an earlier draft and void, since `mount_resolver.py` explicitly rejects any mount whose source basename is `.claude.json`. Auto-trust declares a workspace trusted without asking, correct here for exactly one reason — the operator chose the mount — and `OAW_NO_AUTO_TRUST=1` restores the prompt while still clearing onboarding, so the escape hatch is usable rather than all-or-nothing. It is **not** justified by `--dangerously-skip-permissions`, which an earlier draft claimed: that removes tool-use approval, whereas folder trust governs whether the workspace's own project-scoped config (`.mcp.json`, project hooks, project `settings.json`) is loaded and executed, so auto-trust *adds* unprompted execution of repo-supplied config rather than being subsumed by a flag the agent already carries. A corrupt `~/.claude.json` warns instead of aborting: the wrapper sources bootstrap, so failing here would mean no agent at all, and a wizard is bad where no agent is worse. Verified on the built image — fresh container, no manual config, arbitrary workspace path, reaches a prompt 3/3, with the opt-out bringing the dialog back as a positive control. **Methodology note:** the first probe reported every configuration "clean" because the TTY stream interleaves escape codes *between characters*, so the literal phrases never matched; a later run drew a conclusion from a container still carrying a previous probe's mutations. Both were caught by validating the instrument against a case that must fail before trusting any result it reports.

- **`bootstrap.sh` never ran — every containerised agent booted unbootstrapped (#1076).** The bootstrap was written to be the agent's parent (it ends by *"refusing to hand off to the agent"*), but nothing ever invoked it. aoe runs no entrypoint: it starts the image with `sleep infinity` as PID 1 and `docker exec`s `claude` as a **separate** process — measured on a live container, PID 1 = `sleep infinity`, agent = PID 13 with **PPID 0** — so there was no process path from bootstrap to the agent. Skills-sync, settings merge, secret projection and R-14 env validation were all shipped, unit-tested, documented, and **inert**. Auth was merely the first phase whose absence was visible, because it parks the agent on `Select login method:` forever, and an unattended agent on a login menu looks exactly like an idle one. It hid because `test_bootstrap.py` drives `bootstrap.sh` directly by subprocess: that proves the script *works* and never asks whether anything *calls* it — the same declared-but-not-wired shape as the inert R-14 check (#1061), trivy parsing zero manifests (#1056), and `extra_volumes = [0 items]` (#1069). **Fixed** with `containers/oakandwave-workflow/claude-entrypoint.sh`, installed over the `claude` name and `exec`ing the real CLI (moved to `claude-real`). It **sources** bootstrap rather than running it, which is load-bearing and not a style choice: environment flows down, never up, so a child process would export `CLAUDE_CODE_OAUTH_TOKEN` into itself and exit, leaving the agent with nothing and every log looking healthy. Sourcing also preserves the fail-loud contract for free, since bootstrap's `exit 1` aborts the wrapper before the `exec`.

  **The first cut of this fix shipped inert, exactly like the bug it fixes.** Installed only at `/usr/local/bin/claude` — chosen because `/proc/<pid>/exe` on a live agent resolved there — it was never executed, because `docker exec` resolves against the **image's configured PATH**, which reaches the base image's `/root/.local/bin/claude` *before* `/usr/local/bin`. `/proc` had answered "what is this running process", not "what does `docker exec claude` resolve", and those differ. Caught by hiding the wrapper and watching bare `claude` still work. The remedy is not a better path but an asserted property: every reachable `claude` is replaced, and `scripts/ci/assert-no-claude-bypass.sh` walks PATH at **build time** and fails the build if any is not the wrapper (it found **three**), with an empty-denominator guard so "no claude found" can never read as a pass, and empty PATH entries normalised to `.` rather than discarded, since POSIX resolves them to the current directory.

  Two further defects fell out. **The shipped `.env` template aborted the boot:** `OAW_REQUIRED_SECRETS=claude-code-oauth-token discord-bot-token` is `source`d, so unquoted it is not a two-item list but `VAR=first` prefixed to a command named `second` — `line 42: discord-bot-token: command not found`, exit 127. Every fixture used a single-token value, so no test could reach it. **And the guard added for it was itself inert:** bash *strips* `errexit` inside `$( )`, so a command-substitution probe kept sourcing past the first failure and returned the status of the **last** line — and because the template ends with a good `OAW_SECRET_ENV=` line, the guard probed "clean" for the very file it ships, discarded the stderr it had captured, and let the real source die with 127. The probe now runs in a fresh `bash -c` with its own live errexit, stopping at the first failure, and surfaces captured stderr instead of dropping it. Bootstrap's summary line also moved to **stderr**: under `source` + `exec` its fd 1 *is* the agent's, so on stdout it prepended a non-JSON line to every headless `claude -p --output-format json`.

  Verified end to end on a real agent in a real container — `AUTH_OK`, agent process showing as `claude-real`, token present in `/proc/<pid>/environ` — not inferred from configuration. New tests assert the **caller**, execute the real wrapper to prove an `export` survives the `exec`, and strip comments before asserting on the Dockerfile so prose cannot satisfy them; all were mutation-tested red-first. Follow-ups: #1078 (bootstrap's skills host-fill has no mount, so it warns every boot) and #1079 (interactive agents still park on the first-run onboarding wizard — provably *not* auth: the token returns HTTP 200 and headless works).

## [7.1.1] - 2026-07-19

### Fixed

- **Session liveness detection never fired — `skill-gc`/`reorient` could rewrite LIVE agents' transcripts (#919).** `session_liveness()` documented a fail-closed contract whose *strong signal* was "a process holds the transcript fd open". Claude Code appends to its transcript and closes the descriptor, so that branch was dead code. Swept on the development workstation (a single-host observation, not reproducible from a read-only review): **0 of 277 transcripts were held open across 10,613 open fds**, so everything fell through to the 60-second mtime window and **10 of 14 live sessions there classified as STOPPED** — eligible for transcript surgery, and selected by the documented fleet invocation `find-projects --stopped … -exec reorient {} \;`. The suite stayed green throughout because `test_detects_open_fd_as_live` opened the fd *itself* and `test_stopped_vs_running` monkeypatched `_liveness` away; both asserted a path production never took. **Replaced** with a process-identity signal: one `/proc` sweep extracting session UUIDs from `--resume`/`--session-id`/`-r`, covering all four cmdline forms observed in the fleet — bare uuid, `--resume=<uuid>`, and path-valued `--resume /…/<uuid>.jsonl`. Every cmdline is scanned rather than filtering on `argv[0]`, because sessions run under a two-word `argv[0]` (`claude bg-pty-host`) and under the bare version binary (`…/claude/versions/2.1.215`) — a basename filter dropped 4 live sessions. Flag-scoped parsing (not "any UUID in the cmdline") avoids 8 false positives from grunt ids carried in `--append-system-prompt`. The mtime window survives as a **secondary** signal only. Two cmdline forms name no written session at all and fall to **cwd-scoped doubt** (`unknown` → refused) rather than poisoning the fleet: a bare `claude`/`--continue`, which carries no uuid anywhere; and `--resume A --fork-session`, where the fork mints a *new* id, so naming `A` accounts for the source and never the file the process actually writes. The latter is easy to miss precisely because every `--fork-session` in this fleet also passes an explicit `--session-id` — when the new session *is* named the process is fully accounted for and its cwd is deliberately not blanketed. On the development workstation that scoping cost 1 store of 84 its collectability, and the recorded cwd strips the kernel's `" (deleted)"` suffix — left on, the doubt is filed under a path no transcript can match and silently evaporates, which `git worktree remove` under a running agent is enough to trigger. Fail-closed is preserved and widened: no `/proc`, *or* pid dirs exposing no readable cmdline, *or* a `/proc` with no pids at all now yield `unknown` — a blinded scan must never be indistinguishable from a healthy all-clear. `find-projects` hard-errors (rc 2) on `--stopped`/`--running` both when `skill-gc` fails to load **and** when the `/proc` sweep comes back blinded, instead of printing nothing and exiting 0; answering "the fleet is drained" from a detector that saw nothing is what made `./install` look safe under ten live agents. The two tools share one implementation, now asserted by a differential test and a load-path test. Also **~500× faster**: the dead fd scan re-globbed all `/proc` fds *per session* (277 × 10.6k), so `find-projects --stopped` went from >120 s (timed out) to 0.12 s by sweeping once per run. Verified against the development workstation's live fleet: `--running` 6 → 12 stores, every live-with-transcript session detected, **0 live sessions in the `--stopped` set**, and `skill-gc` refuses a real agent idle 34,712 s (578× the window) that the old code evicts. New `tests/test_liveness.py` (38 cases) was red-first against the prior implementation — **28 failed / 10 passed** — and drives the real detector via `/proc` trees built from observed cmdlines. **Known residual (#923):** the blinding guard fires only when *no* cmdline is readable, so a *partially* readable `/proc` (hidepid, PID namespace, another user's `claude`) still fails open; unaffected on hosts where `/proc` carries no `hidepid`.

## [7.1.0] - 2026-07-19

### Fixed

- **Godspeed gated-axis check: gate on ACTIONS, restore the agent's right to assess (#917).** The Stop hook's gated-axis check regex-matched the assistant's *turn text* for keywords (`prod`, `deploy`, `credentials`, …) and explicitly discarded `tool_use` blocks — it judged what the agent said, not what it did. It was wrong in both directions at once: it fired on `"the live deployed tool schema"` (and on any turn *documenting* this hook's own keyword list), while missing `deploy_freshness` because `\bdeploy[a-z]*\b` cannot cross an underscore. A word list cannot separate those; the discriminator is not the word but whether the turn acted. Three changes: **(1) Substrate** — the gate now reads `tool_use`, matching invoked command *verbs* at shell-segment head (plus prod-shaped `Write`/`Edit` paths), so gated keywords appearing as *data* (`grep -P 'prod|deploy'`, a heredoc about this hook) never match, while prefix wrappers that used to defeat `^`-anchoring (`sudo systemctl`, `git -C … push --force`, `timeout N terraform apply`, `sh -c`, subshells, `xargs`) now do. **(2) Agency** — the STOP reason previously ordered *"surface it to BJ before proceeding"*; it now grants an explicit assess-and-continue path. An unconditional halt defeats `/godspeed` and buys nothing, because the hook runs *after* the turn's tools have executed and could never prevent a first action. It is a salience signal, not the enforcement gate — the ABSOLUTE prod rule, `/precheck`, and the human remain the real defenses. **(3) Notification** — a gated trigger no longer fires vox/Discord. Notifying before the agent has assessed makes the *hook* the escalator and spends the user's attention on every false positive; the agent now escalates with its own tools when it judges something merits attention. Extraction is turn-scoped (a union across every assistant message since the last human-text user entry, never `last`) — scoping to a single message failed **open** on the normal pattern, since agents almost always run a verification command after acting, which masked the gated one. Regression coverage grew 39 → 51 shell assertions plus 20 Python subtests, including the multi-message fail-open, prefix wrappers, keywords-as-data, the self-referential case, and positive controls for the kill-switch and loop guard (both had gone vacuous).

- **`/issue` no longer steers agents away from `type: "plan"` (#915).** The skill carried a warning block asserting `work_item` had no `plan` in its type enum, citing `mcp-server-sdlc#477`. That gap was closed by sdlc **v2.1.0** (`mcp-server-sdlc#479`) and #477 is closed — verified against the live deployed tool schema, not repo source. The block was actively harmful, not merely stale: it told agents `/issue plan` could not pass `type: "plan"`, and its fallback guidance (`type: "epic"` plus manual label cleanup) produces exactly the duplicate `type::epic` + `type::plan` taxonomy leak Dev Spec R-19 forbids on GitHub — the bug #903 documented and #479 fixed. Replaced with a positive instruction to pass `type: "plan"`, the sdlc-server ≥ v2.1.0 version floor, and the retained prohibition on substituting `type: "epic"` (which was only ever safe by accident on GitLab). `tests/test_issue_skill.py::TestPlanTypeGapDocumented` — which asserted the removed block's presence — is re-pointed at the new invariant as `TestPlanTypeCallout`, keeping the `type: "epic"` coverage and adding a negative regression so the stale claim cannot creep back.

## [7.0.0] - 2026-07-19

### Added

- **Executor Model — per-wave dispatch, `/lazyriver`, and `/multithread` (Plan #822).** Three coordinated changes that split the wave pipeline's conflated execution concepts. **(1) Per-wave dispatch knob:** `/prepwaves` now classifies each wave with a `dispatch` hint (`fan` \| `serialize` \| `serialize-preferred`) after topology computation (Step 4.A four-rule table), and `/nextwave` reads it to fan flights in parallel or run them single-file. Asymmetric bias — serialize by default; `fan` only when verified-independent and mechanical; intra-wave dependency edges are a hard `serialize` gate (F-8 class). Absent `dispatch` is treated as `serialize` (backward-compatible). Regression-tested in `tests/test_prepwaves_dispatch.py`. **(2) `/lazyriver` goal-seek skill:** a new skill implementing the `probe → journal → judge-sufficiency → steer` loop that runs a *goal* to *sufficiency* (a judgment) rather than a DAG to completeness — sits upstream of `/devspec`, emits a plan or a direct answer, is escalation-corded (leg cap 10 or two consecutive zero-finding legs) with a durable findings journal. Explicitly distinct from the plan-execution activity `/wavemachine`/`/nextwave` run. **(3) `/multithread` companion:** a new skill that turns a serial walk over N independent design items into a concurrent discussion — enumerate + stable-label, independence pass, present all threads with a proposed take each, batch-answer, converge, and emit a decision record — closing in ≈ log(N) round-trips instead of N. Dev Spec: `docs/executor-model-devspec.md` (VRTM Appendix V complete; MV/E2E evidence in `docs/executor-model-mv-results.md`). Closes #822.
- **`/reseed` auto-revive hook (#757).** `SessionStart{matcher:"clear"}` hook (`reseed-revive.sh`) injects the seed content into the fresh agent context and fires a tmux keystroke — no user action needed after `/reseed`. Flow: `/reseed` writes the seed, arms `<project_root>/.claude/reseed-armed.json` (seed_path + tmux_pane + mtime), then sends `/clear` to its own tmux pane via `tmux send-keys`. Hook fires on the fresh session: if armed file is fresh (< 5 min, by mtime — cross-project isolation via CWD-scoped path), seed content is injected via stdout (system-reminder) and `tmux send-keys "continue"` kicks the agent off. Stale armed files trigger a confirm-request instead. Armed file consumed on inject; seed file kept for manual recovery. No user action after `/reseed`; BJ never touches it again.

### Changed

- **The fleet is now queue-less — merge queues and merge trains are removed entirely (#898, #900).** The rulesets were deleted from all six Wave-Engineering repos (classic branch protection, which independently carried the required status checks, was left intact); `gl-settings` disables GitLab merge trains; and every trace of the concept is gone from the kit — the `skip_train` flag and the `merge_group_validated` acceptance are stripped from the wave engine (`gate.js`, `per-wave-workflow.js`, the bundle, `SEAMS.md`), the dead `merge_group:` trigger is removed from `validate.yml`, and the specs, skills, and docs no longer mention or assume either. **Why:** wave work never needed a queue — flights land on the `kahuna/*` integration branch, the engine reconciles them via `commutativity_verify` + dependency-ordered merges, and `kahuna→main` is a single serialized, trust-gated promotion, so nothing ever merges to the protected branch concurrently. The queue only cost us: an extra pipeline per MR on GitLab, the `skip_train`-silently-dropped divergence bug, and the 2026-04-07 outage (postmortem #299). A prior spec claim that GitLab trains "batch flight-MRs into one pipeline run" was **false** — GitLab runs a pipeline *per MR in the train* — and is corrected at the source. Note that GitLab **merged-results pipelines stay ON**: they are not merge trains, and they are what produce the merge-result pipeline the wave gate validates (sdlc #452 — the gate checks the merge *result*, never the branch HEAD). Removing the queue also makes merge method a **per-merge** choice again, since nothing forces one method for everything. `docs/operations/merge-queue-checklist.md` → `docs/operations/branch-protection-checklist.md`, rewritten, **preserving** the load-bearing "config exists ≠ config works" discipline (a red PR must be BLOCKED *and* a green PR must merge — a gate that blocks everything is as broken as one that blocks nothing). Regression is guarded *negatively*: `test_gate_contract` and `gate_signals_roundtrip` now assert `skip_train` is **absent**, and `install` prunes the old runbook from `~/.claude` via `DEPRECATED_PATHS` (it *prescribed* creating a queue, and repos without their own docs resolve kit docs from there).
- Agent identity now stored at `<project_root>/.claude/agent-identity.json` (reboot-durable, gitignored) instead of `/tmp/claude-agent-<md5>.json`. All readers fall back to the legacy `/tmp` path during the transition window. Closes #723.

## [6.1.0] - 2026-06-23

### Fixed

- Corrected the `discord.json` channel schema (nested → flat) across the disc reader (`/disc`), the ccwork writer (`/ccwork discord`), and the `docs/discord-config.md` contract doc. The canonical config uses top-level `default_channel_id`/`roll_call_channel_id` + a flat `channels` name→id string map; the skills previously read/wrote the stale nested `channels.<role>.{id,name}` shape, so `/ccwork`-generated configs were unreadable by `/disc` and config edits were silently ignored in favor of baked-in IDs. Closes #806.

### Added

- `/prepwaves` step 0.5 — **campaign residue gate**: calls `wave_campaign_precheck` (server contract mcp-server-sdlc#457) before any sub-agent fan-out or approval and surfaces a prior campaign's residue (`classification` + `residue{plan_id, wavemachine_active, pending_waves, promoted_waves, kahuna_branches}` + `options`/`recommended`) for an operator preserve-wait / preserve-extend / replace choice; nothing is deleted without explicit confirmation. Subsumes the former narrow `phases-waves.json` multi-Phase guard, with an on-disk fallback for defense-in-depth. Closes #716.
- Kit-canonical docs (`WAVE_AXIOMS.md` + the referenced `docs/*`) are globalized to `~/.claude/` on install, so a `/ccfold`-merged CLAUDE.md resolves them in any repo (single source, no per-repo vendoring). Closes #792.

### Changed

- The **pytest suite now runs in CI** — `scripts/ci/test.sh` on both `pull_request` and `merge_group`. Root-cause fix for the suite rotting unnoticed: it previously ran nowhere in CI. Closes #795 (CI-gating slice; the xfailed-test rewrite remains in #795).
- Triaged the rotted test suite to green (195 → 0 failed): stale wave-engine skill-tests dispositioned via reasoned `xfail` (logic relocated to `per-wave-workflow.js` by #691 / `WAVE_AXIOMS` by #605; covered by the #785 e2e smoke). Closes #753.

## [6.0.0] - 2026-06-20

### Breaking

- Wavemachine Classic mode retired; Kahuna is the only execution shape. Every Plan now bootstraps a `kahuna_branch` at launch and routes Flight PRs through that integration branch, with the four-signal trust gate at Plan completion auto-merging kahuna→protected-branch. The `legacy non-KAHUNA` / `KAHUNA mode` framing is gone from `/wavemachine`, `/nextwave`, `/prepwaves`, `/assesswaves`, and `/devspec`. Hardcoded `main` integration targets in skill bodies have been replaced with abstract phrasing (the project's protected branch, read from `.claude-project.md`). No mode-selection flag, no fallback path. Closes cc-workflow#580.

### Added

- **Campaign-oversight stack (#745).** The between-wave judgment facility, built as three composable pieces: a **durable cross-wave concern-trajectory** (#748) — `wave-status` accumulates each completed wave's terminal record (`{gate, promoted}`, the four trust signals, concerns/deferrals/rework, commutativity verdict, issues; reboot-proof, idempotent, with `trajectory-append`/`trajectory-show` CLI); a **deterministic auto-mode campaign Workflow** (#749) — `campaign-loop.js` + `campaign-workflow.js` iterate pending waves, run each per-wave spine, route on the `{gate, promoted}` verdict, and call the judgment seam — no LLM in the loop control flow, so it provably cannot stall; and the **wave-oversight judgment agent + seed contract** (#750) — seeded no-distillation from tiered intent (devspec → DDD/sketchbook → issues) + the durable trajectory + live inspection, with a failure-shape lens (accumulation / intent-drift / adaptation-vs-drift across trend / absence / confound-control modes).
- Coarse driver-states for the async campaign loop in `wave-status` (#738).

- `/prepwaves` now ends with a `/clear` recommendation and a paste-ready `/wavemachine` seed prompt. The recommendation downgrades to a hint when `nerf_status` reports <30% of soft dart used. Reduces context drift between planning and execution sessions (Plan #581 debrief). Closes #602.
- /wavemachine: long-session drift mitigation — at every wave-to-wave handoff the loop body emits per-wave drift-signal events (`wave_message_length_main`, `wave_stop_hook_blocks`, `wave_concerns_posts`) via `scripts/wavemachine/drift-instrumentation.sh emit-wave-drift` and injects a system-reminder re-grounding payload citing `WAVE_AXIOMS.md` (with explicit Axiom 9 reference). The lightweight payload is unconditional at every wave boundary; mandatory `/engage` and `/compact`-on-N-waves are documented as rejected alternatives held in reserve for empirical escalation. (cc-workflow#601, "Bug C" from Plan #581 campaign A debrief.)
- `wave_wait_for_signal` MCP tool — sanctioned idle-wait for wave-pattern Orchestrators (and Primes) blocking on filesystem-bus completion artifacts. Polls every 5s with configurable timeout (default 1800s) and minimum match count (default 1); accepts literal paths or Bun.Glob patterns. Returns matched paths on success or `timed_out: true` + `partial_matches` on timeout. Replaces ad-hoc `Bash(sleep)` loops and the anxiety-driven premature-exit failure mode (#414).
- **wave-watcher daemon (#578).** New standalone Bun daemon.
- `/wave` skill: thin routing skill wrapping `mcp__sdlc-server__wave_show` so wave-pattern status (Project / Phase / Wave / Flight / Action / Progress / Deferrals) can be checked from any conversation without remembering the MCP tool name. Pure pass-through — no interpretation. Future routes (`/wave health`, `/wave topology`, `/wave next`) documented but reserved for follow-up issues. (#579)
- **Nerf MCP server** — Deterministic context budget management via `nerf-server` MCP. Includes dart thresholds (soft/hard/ouch), behavior modes (not-too-rough, hurt-me-plenty, ultraviolence), statusline indicators, and a terminal-based scope monitor
- **`/nerf` skill** — Thin routing stub for the nerf MCP server with `k`/`m` suffix parsing
- **`/issue` skill** — Create structured issues (feature, bug, chore, docs, epic) with proper templates and labels. Self-contained, dual-platform (GitHub/GitLab)
- **`/ddd` skill** — Domain-Driven Design facilitation with 8-stage event storming, domain model formalization, and PRD generation
- **`/man` skill** — Display usage information for any installed skill via SKILL.md frontmatter
- **`/cryopact` skill** — Background cryo via subagent — preserve state without blocking the main conversation
- **`/disc` skill** — Unified Discord integration: check-in, send, read, list channels, create threads
- **`/view` skill** — Open file/URL in a GUI viewer (read-only) with cross-platform file-opener
- **`/edit` skill** — Open file/URL in a GUI editor for modification
- **`/vox` skill** — Text-to-speech voice announcements via Chatterbox API with local fallback
- **`/precheck` skill** — Pre-commit gate: branch/issue compliance, validation, code review, checklist
- **`/assesswaves` skill** — Quick assessment of wave-pattern suitability for parallel execution
- **`/ccwork` skill** — Onboarding hub with interactive tours, labs, and setup wizards
- **`/scpmr` and `/scpmmr` combo skills** — Stage/commit/push/create PR/merge in one command
- **`/ccfold` skill** — Merge upstream CLAUDE.md template changes into local project CLAUDE.md
- **`sync.sh`** — Reverse-sync: pull local skill/script changes back into the repo
- **Context crystallizer** — Session state preservation pipeline: hooks (PostToolUse, SessionStart, SubagentStop), libraries (context-analyzer, crystallizer), CLI tools (cc-context, cc-cleanup). Tracked in `context-crystallizer/` and installed via `--crystallizer`
- **Discord watcher channel server** — Real-time inter-agent communication via Discord with targeted message filtering, thread polling, voice message STT, and Dev-Name echo suppression
- **Discord bot** — REST API client for Discord: send, read, create channels/threads, resolve names, with 429 retry handling and kill switch
- **Discord status post** — Wave-status embed with auto-updating pinned message, debounce, and dev-team fallback
- **`discord-lock`** — Advisory lock for serializing Discord channel writes across agents
- **`cc-inspector`** — Context window inspector: mitmproxy + Flask UI for API payload capture
- **`generate-status-panel`** — HTML status panel generator for wave progress
- **`worktree-manager`** — Manage isolated worktrees for parallel agent execution
- **Remote installer** — `scripts/install-remote.sh` for curl-pipe-bash installation from GitHub Releases
- **MCP manifest** — `mcps.json` with bundle-install architecture for wtf-server, discord-watcher, and nerf-server
- **GitHub Actions workflow** for GitHub Release packaging
- **Statusline v2** — Two-line layout with per-session indicators, visual refresh, and JSON-based indicator interface
- **Introduction system** — First-run introduction.md display for new skills with marker file gating
- **Work Item Standards** — Label taxonomy (`group::value`), issue templates (feature, bug, chore, docs, epic), and wave-pattern quality requirements in CLAUDE.md
- **`.claude-project.md`** — Cached platform detection results (GitHub/GitLab, CLI tool, labels, CI)
- **Agent identity keying** — Migrated from PPID to project-root md5 hash for stable cross-process resolution
- **PRD template v2.0** — EARS requirements, phased implementation, artifact manifest, CI/CD pipeline, documentation kit, test plan sections, foundation story checklist, one-story-one-repo rule
- **Getting Started guide** — 15-minute walkthrough of first session
- **Skill Reference** — Detailed documentation for all skills
- **Concepts guide** — Architecture overview of the three-layer kit
- **Troubleshooting guide** — Common issues and fixes
- **Discord configuration guide** — Bot token, watcher, inter-agent messaging setup
- **Statusline indicators guide** — Per-session indicator interface documentation

### Changed

- **wavemachine skill**: rename epic→Plan/Phase; add Exhaustive Legal Exits section per Dev Spec §5.3.3. [#512, Story 3.1]
- **nextwave skill**: rename epic→Plan/Phase; add Exhaustive Legal Exits section per Dev Spec §5.3.3. [#513, Story 3.2]
- **prepwaves skill**: rename epic→Plan/Phase; annotate surviving "epic" references as PM-layer. [#514, Story 3.3]
- **devspec skill**: teach Plan/Phase/Wave/Story vocabulary; append Decision-Ledger comments to Plan issue during walk; `/devspec upshift` emits `phases-waves.json` with `plan_id` + per-Story `depends_on`. [#515, Story 3.4]
- **issue skill**: add `type=plan` with Dev Spec §5.1.2 body template; add `--epic N` flag for Story creation; on-demand `label_create` for missing `type::plan` / `epic::N`. [#516, Story 3.5]
- **Refactored `vox` around the provider-hook pattern.** The previous `scripts/vox-tts` embedded five coupled backends (VOX_COMMAND, VOX_ENDPOINT, espeak, piper, say) in one cascade; it has been removed. `scripts/vox` is now a thin dispatcher that resolves a *provider* (synthesis) and a *player* (playback) at runtime. Providers live in `~/.config/vox/provider`; copy-and-adapt examples ship in `scripts/vox-providers/` (`silent.sh`, `openai-endpoint.sh`, `piper-local.sh`, `espeak.sh`, `macos-say.sh`). Contract documented in `scripts/vox-providers/README.md` (VOX_PROVIDER_CONTRACT=1). Closes #398.

  **Migration (existing vox users)**: your prior `VOX_COMMAND` / `VOX_ENDPOINT` settings no longer auto-dispatch. Run `vox --setup` once to pick a provider, or manually:

  ```bash
  cp scripts/vox-providers/openai-endpoint.sh ~/.config/vox/provider
  chmod +x ~/.config/vox/provider
  $EDITOR ~/.config/vox/provider   # set VOX_ENDPOINT, VOX_VOICE at the top
  ```

  `VOX_DISABLED=1` is a new escape hatch for clean no-op exit (CI / headless / temporary silence).

- **Renamed `/prd` skill to `/devspec`** (Development Specification). The old name collided with PM usage of "PRD" (customer need, ROI, value prop); the skill produces an implementation spec for a coding agent, which is semantically distinct. Template renamed to `docs/devspec-template.md`, translation protocol to `docs/DDD-to-devspec-protocol.md`, and output files use the `-devspec.md` suffix. The approval metadata marker changed from `<!-- PRD-APPROVAL -->` to `<!-- DEV-SPEC-APPROVAL -->`. Internal campaign-status stage ID `prd` is preserved for backward compatibility with existing `.sdlc/` state files; only the user-facing display label is updated to "Dev Spec". Closes #327.
- `install.sh --config` now smart-merges `settings.template.json` into existing `settings.json` — missing hooks, plugins, and permissions are added while user customizations are preserved
- `install.sh --check` now reports missing hooks, plugins, MCP server registrations, and crystallizer drift
- `install.sh` supports selective flags: `--skills`, `--scripts`, `--config`, `--mcps`, `--crystallizer`
- Repo restructured: skills carry their own scripts (discord-bot inside disc, file-opener inside view, etc.)
- `/cryopact` delegates to cryo subagent, removes auto-clear, fixes immediate mode
- `/disc` default action changed from read to check-in
- `/nextwave` uses pre-created worktrees instead of isolation worktrees, with granular lifecycle tasks and explicit wave-status calls
- `/pong` uses priority-ordered default discovery flow (active thread → addressed messages → general history)
- `/vox` adds `--output FILE` flag for render-to-disk mode
- Discord config abstracted into `~/.claude/discord.json`
- Agent check-in on session start via `#roll-call` channel
- RC display name set to match Dev-Name at session start
- Introduction-gate marker files use dot prefix for hiding
- Nerf default thresholds lowered for 200k context window safety

### Fixed

- `wave_finalize`: durable-state fallback when wavebus has been cleaned up by `wave_complete`. Re-derives the MR body from `<project>/.claude/status/{phases-waves.json,state.json}` (issue #s + recorded `mr_urls`) so the kahuna→target finalize step succeeds at the end of the last wave instead of returning `no_artifacts`. Bus artifacts still take precedence when present. (#415, Plan #581 incident)
- `/wavemachine`: Wave-to-wave handoff is now a single tool-use boundary — skill body forbids narrative text between waves, and a new doc-shape regression test (`tests/regression/test_wavemachine_handoff_no_narrator.sh`) guards the contract. Closes "Bug B" from Plan #581 campaign A debrief (#600).
- `/nextwave`: Prime(post-flight) prompt now declares the canonical-line contract verbatim with concrete PASS/FAIL/BLOCKED examples, a forbidden-phrases list (including the exact `"Sleep is still running. Let me wait for the notification."` narration that broke Plan #581 wave-2), and an `Exit shape` section as the LAST section of the prompt so it is the most recent context when the agent emits its final message. Closes #606.
- `pr_wait_ci` no longer hangs the full timeout window when a PR/MR has no required status checks. The handler now probes once at t=0; on empty rollup it returns `{ status: "no_checks_required", elapsed_sec, mergeable, blocker? }` instead of polling. Polling-loop behavior for non-empty rollups is unchanged. (#416)
- `install.sh` unbound tmpdir variable on script exit
- `install.sh` handles `claude mcp add` failure gracefully
- Discord-bot 429 retry-after handling and JSONL API call logging
- Discord-bot kill switch to halt all API calls on global 429
- Discord watcher strips punctuation from @-addressing tokens
- Vox Bluetooth wake noise prepend to prevent audio clipping
- Vox help text for `-o` flag and `espeak-ng` fallback
- Wave-status meta-refresh fallback for `file://` dashboard viewing
- Wave-status infers phase/wave position when `current_wave` is null
- Identity keying migrated from PPID to project-root hash (fixes multi-session collisions)
- Ping/pong channel name corrected and channel ID added
- `/precheck` runs immediately without asking permission
- `/issue` removes per-issue approval gate (issues are cheap to edit)

### Removed

- `afk-notify` Stop hook — replaced by kill switch on discord-watcher

### Chore

- `/prepwaves` now refuses to run on a dirty working tree or a non-base branch, listing every offending path so the operator can choose between commit, stash, or discard. A `--force-dirty` override exists for legitimate edge cases and emits a noisy banner before proceeding. Rationale: Plan #581 sandbox cross-talk incident (#603).
- `/devspec approve` now self-commits the Dev Spec (and any auxiliary finalization-track writes) on the active branch with a `docs(devspec): finalize Dev Spec for Plan #N — <slug>` message instead of leaving the changes uncommitted. Refuses to commit on the project's protected base branch. Push remains the operator's affirmative act. (#604)
- WAVE_AXIOMS.md restructured: each axiom now has a stable rule/why/how subsection layout, and a new Axiom 9 ("User attention is the cost. Autonomy is the protection.") binds the autonomy clauses in `/wavemachine`-class skills to the user-attention-protection rationale. The four wave-pattern skill bodies (`/wavemachine`, `/nextwave`, `/prepwaves`, `/assesswaves`) now begin with a `## Axioms` cross-reference block citing the binding axioms by number, and inline justification prose that duplicated the axiom corpus has been replaced with cross-references — single source of truth, no more skill-body drift. (#605)
- New regression check `scripts/ci/check-no-classic-mode.sh` (wrapped by `tests/regression/test_no_classic_mode.sh`) flags Classic-mode taint in wave-pattern skill bodies and the cross-repo recipe; wired into `scripts/ci/validate.sh`'s regression-tests pass.
- **regression test**: grep-based test enforcing R-19 (no pipeline reads of `epic::N` labels); wired into CI. [#517, Story 3.6]

### Documentation

- Added `docs/tools.md` (per-tool reference, seeded with `wave_wait_for_signal`).
- Added `docs/wave-pattern-orchestration.md` with the canonical Orchestrator-wait-on-Flights example.
- **phase-epic-taxonomy VRTM closed**: MV-01..MV-06 executed; all 18 active requirements traced to Pass verifications; Plan #499 flipped to `plan-complete`. [#518, Story 3.7 — closing story for cc-workflow#499]

## [KAHUNA MVP] - 2026-04-25

### Added

- **KAHUNA — autonomous epic delivery via per-epic integration branches.** Lets `/wavemachine` ship a whole epic to `main` in one autonomous run instead of stopping for human review on every Flight MR/PR. All Flights for an epic merge into a short-lived `kahuna/<epic-id>-<slug>` branch (CI-gated, no human review); when the epic is fully assembled and the four-signal trust score is green (commutativity STRONG/MEDIUM, CI green, code-reviewer-clean, trivy zero HIGH/CRITICAL), the system opens a single kahuna→main MR/PR and auto-merges it. Main's existing branch protection, required reviews, and merge rules are unchanged — KAHUNA only relaxes rules on `kahuna/*` branches. cc-workflow surface area in this release:

  - **`/precheck` sandbox awareness** — Detects when a Flight Agent is operating inside a Kahuna sandbox (current branch's base ref matches `^kahuna/[0-9]+-`). When the full checklist passes (validation, code-reviewer no high+ findings, trivy clean, Discord `#precheck` post, vox announcement), `/precheck` emits the sentinel `[AUTO-APPROVED: kahuna sandbox]` and invokes `/scpmmr` directly instead of STOP-and-wait. Outside the sandbox, behavior is unchanged.
  - **`/wavemachine` trust-score gate** — Wavemachine integrates four-signal trust-score evaluation at the kahuna→main MR/PR. Any red signal pauses for human review; degraded-signal fallback to human is automatic, not configured.
  - **`/nextwave` kahuna base-ref plumbing** — Flight sub-agents branch off the kahuna integration branch (not main) and target it as their MR/PR base. The base ref is propagated end-to-end through wave planning, worktree creation, and PR creation.
  - **`wave-status` CLI additions** — New `set-kahuna-branch` subcommand for KAHUNA state writes; renderers for `kahuna_branch` / `kahuna_branches` fields; gate-action surfacing in the dashboard and Discord wave-status embed.
  - **New documentation** — [`docs/kahuna-guide.md`](docs/kahuna-guide.md) (engineer-facing how-to) and [`docs/kahuna-devspec.md`](docs/kahuna-devspec.md) (architecture, rationale, constraints, requirements).

Companion changes ship in `mcp-server-sdlc` (kahuna lifecycle tools, `wave_finalize`, schema relaxations) and `gitlab-settings-automation` (per-platform sandbox configuration). See those repos' CHANGELOGs for details.

## [0.1.0] - 2026-03-22

### Added

- **CLAUDE.md template** — Drop-in project instructions with auto-detection for GitHub and GitLab
  - Platform detection from `git remote -v`
  - Discovery-based code standards (finds project's own tooling)
  - Agent identity system (Dev-Team persisted, Dev-Name/Dev-Avatar per-session)
  - Pre-commit checklist with mandatory verification
  - Secrets guardrail (warn-and-confirm before staging sensitive files)
  - PR/MR description format

- **11 custom skills** — All dual-platform (GitHub + GitLab)
  - `cryo` — Session state preservation before compaction
  - `engage` — Load rules of engagement
  - `ibm` — Issue-Branch-PR/MR workflow
  - `jfail` — CI job/workflow failure analysis
  - `mmr` — Merge PR/MR with squash
  - `nextwave` — Parallel sub-agent execution
  - `ping` — Post to #ai-dev Slack channel
  - `pong` — Read #ai-dev Slack channel
  - `prepwaves` — Dependency wave planning
  - `review` — Code review on staged/branch changes
  - `scp` — Stage/commit/push workflow

- **Utility scripts**
  - `slackbot-send` — Send Slack messages as a named Claude Code agent
  - `job-fetch` — Fetch GitLab CI job traces for analysis
  - `statusline-command.sh` — Custom status line with git info and context window

- **Deployment tooling**
  - `install.sh` — Install skills, scripts, and config with backup and diff-skip
  - `install.sh --check` — Show drift between repo and installed versions
  - `install.sh --dry-run` — Preview changes without modifying files
  - `uninstall.sh` — Clean removal of installed components
  - `settings.template.json` — Portable Claude Code settings template

- **CI and repo scaffolding**
  - GitHub Actions workflow for PR validation
  - `validate.sh` — shellcheck + shfmt + SKILL.md frontmatter checks
  - Issue templates (bug report, feature request)
  - PR template matching CLAUDE.md conventions
  - MIT license
