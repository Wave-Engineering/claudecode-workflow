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

### Fixed

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

- **Containerised agents can build, run and scan container images (#1108).** `podman` is baked into the image, closing the gap that blocked `blueshift-kb#8` (swap a runtime image to distroless, shedding 23 unfixable CVEs, 4 CRITICAL) — a containerised agent could not verify it at all. The near-miss is the reason this is `Added` and not deferred again: the agent that hit the gap proposed putting a container-generated key in the operator's `authorized_keys` so it could build on the host. **A missing capability does not just block work, it generates pressure to solve the wrong problem.**

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

- **Container SSH parity — the operator's keys were mounted and invisible (#1089).** aoe mounts `~/.ssh` to `/root/.ssh` (keys plus a host→identity config) and agents use them constantly: git over SSH for both forges, and troubleshooting remote installs (blueshift, perkollate, `agent-smith-ca`), where no token substitutes. The agent runs as `ubuntu` with `HOME=/home/ubuntu`, so `ssh` looked in an empty `/home/ubuntu/.ssh`, fell back to default identity names, and failed `Permission denied (publickey)`. Before #1085 made `/root` traversable it could not have worked at all. `ensure_ssh_parity` links `~/.ssh` to the mounted keys — idempotent, clears `ssh`'s own `known_hosts` scratch dir (which silently appears and made a naive `ln -s` land *inside* it), and refuses loudly to clobber a real `~/.ssh`. Measured after: `ssh -T git@gitlab.com` → *Welcome to GitLab*, and `git ls-remote git@…` succeeds on **both** forges.

  **This also corrects #1082 and retires machinery it added.** That fix concluded, from `gh api user` passing while `git push` failed, that git needed HTTPS+token, and added `url.https://github.com/.insteadOf` plus `credential.helper = !gh auth git-credential`. The diagnosis was half right — git transport *was* broken — and the remedy was wrong: git failed because the mounted keys were unreachable, not because a credential was missing. Routing git onto HTTPS+token worked, but it **changed behaviour rather than restoring it** and bypassed keys provisioned on purpose. The github rewrite was **restored** after review: the operator's own `~/.gitconfig` carries `url.https://github.com/.insteadof` and the gh credential helper, so HTTPS+PAT *is* what a host session uses for github — #1082 was right, and removing it diverged. **[CORRECTED by #1130 — this sentence is wrong, and wrong in an instructive way. That `~/.gitconfig` was written by our own test suite: it sealed `$OAW_HOME` but not `$HOME`, so every run of `tests/contained-workflow/test_bootstrap.py` executed `git config --global` against the operator's real home. The rewrite entered `bootstrap.sh` on 2026-07-31 and this claim was written ~29 hours later, so the "evidence" was almost certainly our own side effect read back as host intent. It is also moot: SSH covers git for both forges in the container (`ensure_ssh_parity`), verified live. The rewrite is removed and the leak sealed.]** gitlab has no host rewrite and stays SSH. The premise "the host uses SSH for git" was true for one forge and generalised to both; a test now pins **both** halves, since pinning either alone is what went wrong. Documented rationale claiming the container deliberately has no `~/.ssh` was **inference from a permissions bug presented as design intent**, and is corrected in `architecture.md` rather than quietly dropped.

  `glab` gains an API credential (file, mode 600, `git_protocol: ssh` matching the host) from the whole-dir secrets mount, unblocking MR/CI work. Its token shape guard accepts `.` — real `glpat-` tokens contain dots, and the first cut rejected the operator's actual token while a dot-free fixture passed. The operator's `~/.local/bin` (139 utilities) is also mounted read-only at `/home/ubuntu/.oaw/overlay/local-bin` and **appended** to PATH — never prepended, since the kit's own bin holds the claude wrapper (#1076) and the MCP binaries, and shadowing it would silently un-bootstrap every agent. Profiles must be regenerated or `check-mount-drift.sh` fails and the mount silently does not happen (the #1069 class).

- **`~/.secrets` is mounted whole-directory read-only again, restoring host-agent parity (#1090).** Reverses the named-single-file scoping from #1061 on an operator decision, recorded so it is not silently restored: *"they all get used by agents one time or another. I don't want to curate which agents will need what access via who's tokens. I just want every agent to have access to all those tokens like they do today."* Two corrections to the #1061 rationale made it reversible: **mounted is not baked** — R-12 keeps secrets out of every image layer and `mounts.d/` entries are *runtime* binds, so "an OaW image on a public registry" was never an argument against a runtime mount (the original framing conflated the two) — and **the trust model is unchanged**, since every *host* agent already reads all ~80 entries; per-agent curation bought no security the fleet does not already grant, and #1089 showed it merely moves the blocker to whoever needs the next credential.

  **Availability and inheritance are separate axes, and only availability widened.** Everything stays **path-modality**: a file must be deliberately opened, whereas an environment variable is inherited by **every child process**. `OAW_SECRET_ENV` remains limited to `CLAUDE_CODE_OAUTH_TOKEN` (the exception argued narrowly in #1076 — that token *is* the agent's identity, so a child stealing it gains nothing the agent lacks), and `gh`'s credential is still written to a file rather than exported (#1082). MCP servers follow the same rule: `disc-server`/`discord-watcher` consume `DISCORD_TOKEN_FILE`/`DISCORD_TOKEN_PATH` — **pointers**, not values — so a new MCP credential gets a pointer line, never a value. Verified on the built image: 81 secrets visible as files, `GH_TOKEN` still absent from the agent environment.

  **The scoping guard was replaced, not deleted.** `test_secrets_mounts_are_scoped_not_whole_dir` existed specifically to stop a silent widening, and its docstring said so; removing it would have left a tripwire's worth of nothing. Widening is now intended, so the guards moved to the invariants that still matter: the mount must be **whole-dir and `ro`** (an `rw` mount would let a container corrupt the operator's entire credential store), and **no secret beyond the documented exception may be env-projected** — which is the real risk once 80 credentials are reachable. Both mutation-tested, along with a scope-back-to-named-files mutation. The separator check that rejects `~/.secrets-analogic/…` was preserved while allowing the directory itself; a bare `startswith` would have quietly accepted the sibling.

  Side benefit for R-13: a credential added on the host now appears in every running container immediately, where previously it needed a new mount fragment and a relaunch.

### Removed

- **Slack support, entirely — `/ping`, `/pong`, and `slackbot-send` (#1062).** Both skills were wholly Slack-specific (`#ai-dev`, Slack mrkdwn) with no Discord path, and unused. Removed with them: the `~/.secrets/slack-bot-token` dependency (`deps.json`), the `slack-bot-token` entry in the image build's expected-missing whitelist, the `slack@claude-plugins-official` marketplace plugin (enabled by default with **zero consumers** — its only documented purpose was OAuth on first `/ping`/`/pong` use, so it was costing context every session for a dead integration), and the README's "Slack Setup" section, which instructed new users to provision a bot token for a skill that no longer exists.

  **Already-installed hosts are pruned.** Deleting a skill from source does not uninstall it — `install` walks the surviving `skills/*/` and prunes *within* each, so a skill that vanishes from source is never visited. `~/.claude/skills/ping`, `~/.claude/skills/pong`, `~/.claude/scripts/skills/ping`, and `~/.local/bin/slackbot-send` are now in `DEPRECATED_PATHS`. Without that, the upgrade would have been *worse* than no change: `cellar_deploy` wipes the Cellar copy of `slackbot-send` while `~/.claude/skills/ping/SKILL.md` survives, leaving `/ping` a live, invocable skill whose helper had just been deleted. Guarded by a regression test that plants the installed copies and asserts they are gone.

  **Known gap:** `scripts/install-remote.sh` has no `DEPRECATED_PATHS` mechanism (pre-existing), so tarball-installed hosts retain `/ping` and `/pong` until they are removed by hand.

  Mattermost is the intended successor (Analogic self-hosted; better IP posture), post-cutover, behind a backend abstraction at the MCP-server layer.

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
