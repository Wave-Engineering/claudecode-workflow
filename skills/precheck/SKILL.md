---
name: precheck
description: MR gate — review the pushed commits, read CI, post the precheck status, mark the PR/MR ready, then stop for the merge call
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-precheck does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-precheck
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# MR Gate

Precheck is **the gate into a release branch** (#1233, #1235). Commits and pushes to your own working branch are free; precheck gates the **PR/MR**. It reviews the **pushed commits**, which are exactly what the PR/MR carries; reads CI's verdict for the pushed HEAD; and on a pass posts the `precheck` commit status on HEAD and marks the PR/MR **ready**. Then it **stops for the merge call**: BJ's approval is at the merge, where what he approves is something landing.

| Gate | What runs there |
|---|---|
| commit | secret scan of what is staged (`secret-scan-gate.sh`) |
| push | secret scan of the range being pushed; no push to protected or release refs; working-branch pushes are free (`pre-push-test-gate.sh`) |
| **MR (this skill)** | review, acceptance criteria, lanes (CI first), dependency scan, issue spec; posts `precheck` = success and marks ready |
| merge | BJ's approval, or an exception (kahuna and autochain, detected mechanically; a standing merge grant or a lead-agent grant, applied by you); CI green on the merge result (`/mmr`) |

**Drafts are free.** A draft PR/MR can't merge, so `/scpmr` opens one before precheck runs, and CI runs on it. Making it **ready** needs the `precheck` status on its head. `pr-ready-gate.sh` refuses otherwise on the CLI. On the MCP path, sdlc's `pr_create`/`pr_ready`/`pr_merge` refuse from the mcp-server-sdlc release that carries #592. On an older server, nothing on that path checks it except this skill and `/mmr`. The contract is `docs/precheck-status.md`.

**IMPORTANT: When implementation is done, push and run this skill IMMEDIATELY (`/scpmr` does both). Do NOT ask "shall I run precheck?" or "ready for precheck?" — just start it. The checklist at the end is the merge-approval surface; asking permission to START is a redundant pause.**

**Once the PR/MR is open and prechecked, a later push uses `/precheck rearm`** (below): a review of only the new commits plus a green pipeline, with no checklist, no announcement and no STOP, unless the push changes what the MR does (BJ ruling K-11).

## Tools Used
- `mcp__sdlc-server__ibm` — branch/issue workflow (no protected branch; branch linked to an open issue)
- `mcp__sdlc-server__branch_guard` — resolve the live default branch and verify the PR/MR's base is it (protected-gated, `kahuna/*`-exempt)
- `mcp__sdlc-server__spec_validate_structure` — linked issue has Changes / Tests / AC
- `mcp__sdlc-server__pr_list` / `pr_create` (`draft: true`) — find or open the draft PR/MR
- `mcp__sdlc-server__ci_wait_run` — CI's verdict for the pushed HEAD (`expected_sha`)
- the Bash tool — Job B-local's lanes and Job C's `dependency-scan.sh`, each run as `<cmd> > <log> 2>&1; echo "exit=$?"`, so the exit code read is the instrument's own
- `precheck-status.sh` — post and read the `precheck` commit status
- `mcp__disc-server__disc_send` — post the merge-call request to `#precheck` (channel `1491195025198157834`)

## Procedure

### Step 0 — Pre-flight: resolve the scope and status tools (refuse to guess)

Before Step 1, resolve `precheck-review-scope.sh` and `precheck-status.sh` once and reuse those paths for every later call. Step 0.5 already invokes the first, so probing later is too late.

```bash
SCOPE="" STATUS="" CISRC=""
for cand in \
  "$(command -v precheck-review-scope.sh 2>/dev/null)" \
  "<repo_root>/.claude/bin/precheck-review-scope.sh" \
  "<repo_root>/scripts/precheck-review-scope.sh"; do
  [[ -n "$cand" && -x "$cand" ]] && { SCOPE="$cand"; break; }
done
for cand in \
  "$(command -v precheck-status.sh 2>/dev/null)" \
  "<repo_root>/.claude/bin/precheck-status.sh" \
  "<repo_root>/scripts/precheck-status.sh"; do
  [[ -n "$cand" && -x "$cand" ]] && { STATUS="$cand"; break; }
done
for cand in \
  "$(command -v precheck-ci-source.sh 2>/dev/null)" \
  "<repo_root>/.claude/bin/precheck-ci-source.sh" \
  "<repo_root>/scripts/precheck-ci-source.sh"; do
  [[ -n "$cand" && -x "$cand" ]] && { CISRC="$cand"; break; }
done
```

`PATH` covers a normal install; `.claude/bin` covers `install --local` (which is deliberately NOT on `PATH`); `scripts/` covers a cc-workflow checkout. If `SCOPE` misses on all three, the kit is genuinely absent: take the fallback documented in the Job D section and say so on the checklist. **If `STATUS` misses, STOP.** Without it a pass can't be recorded and the PR/MR can't be marked ready, and there's no fallback. Do not improvise. If `CISRC` misses, Job B goes straight to Job B-ci's `ci_wait_run`, as it did before #1268, and the checklist says so.

### Step 0.5 — The pushed commits, and a draft PR/MR (serial, hard stop)

Precheck reviews **what is pushed**, so the working tree must hold nothing else:

```bash
"$SCOPE" ready <repo_root> <marker_dir>   # -> "ready <sha>" | "not-ready <reason>" (exit 1)
```

`not-ready` → **STOP** and surface the reason. Usually the fix is to commit and push (`/scp`): free on a working branch, and gated by the commit and push hooks. Never review a dirty tree and post a pass on a HEAD that does not contain what was reviewed. Keep `<sha>`; it's `HEAD_SHA` for every later step.

Then find the PR/MR: `pr_list({head: "<branch>"})`. If there is none, first mark the issue in review (GitLab Status → `In Test`, read back; on GitHub the linked PR is the marker), as `/scpmr` step 2 does. Then open the PR/MR **as a draft** with `pr_create({..., draft: true, squash_message})`, using a title and body in the CLAUDE.md format. `squash_message` is the exact commit that will land. The rules in `/scpmr` step 2 govern it, including when to omit it: on an older server, or on an integration pair. If `pr_create` fails, put the issue back to `In progress` and STOP. A draft needs no precheck. This is also what gives CI something to run on: many repos run CI only for PRs/MRs (this one does). Keep `PR_NUMBER` and the PR's **base**; the base is `<base>` for every later step.

### Step 1 — IBM gate (serial, hard stop)
Call `mcp__sdlc-server__ibm` directly (no sub-agent — it's one MCP call). If it fails, stop immediately and do not proceed.

### Step 1.5 — Base-branch gate (serial, hard stop)
Call `mcp__sdlc-server__branch_guard({ role: "base" })`. It resolves the **live** default branch from the git host (never a cached `.claude-project.md` value or `origin/HEAD` — both go stale silently) and checks the branch your work is based on. Interpret the envelope:
- `verdict == "pass"` → continue.
- `verdict == "warn"` → **STOP** and surface `reason` verbatim. Your branch's base is a **protected** branch that is neither the live default nor a `kahuna/*` sandbox — almost always a stale or renamed base (the exact failure this gate exists to catch). Rebase onto the live default, or confirm the base is intentional, before proceeding.
- `{ ok: false }` or any error envelope → **STOP** and surface the error; do not silently continue past a gate that failed to run.

**Protected-gated:** silent when the base is unprotected (feature→feature, stacked branches) or a `kahuna/*` integration branch. Only a protected, non-default, non-sandbox base trips it.

**Scope:** reliable once a PR exists, because it reads the PR's base, and since #1235 one always exists by this step (Step 0.5 opens the draft). Before a PR exists, git can't distinguish "based on a stale default" from "based on the current default, now a bit behind" without false positives; that was the known limit of the pre-commit gate (#888).

**Transition fallback** — *only* until `branch_guard` is deployed on this host's sdlc-server (#465): resolve the live default inline (`gh repo view --json defaultBranchRef -q .defaultBranchRef.name`, or GitLab `glab api "projects/:id" --jq .default_branch`). If an open PR exists, compare its base (`gh pr view --json baseRefName -q .baseRefName`) and STOP if that base is a protected branch that is neither the live default nor matches `^kahuna/[0-9]+-`. Delete this paragraph once `branch_guard` is universal.

### Step 2 — Parallel verification batch
**No sub-agent report is a gate value. Jobs A, B and C are instruments the orchestrator runs itself; their JSON or exit code goes on the checklist as read. Only Job D, a judgment, is delegated.**

After `ibm()` passes: first run `precheck-review-scope.sh reset <repo_root> <marker_dir>` (this is what makes pass 1 of the cycle mechanically full), then `… resolve …` to learn which Job D prompt to compose. Then, **in a single message**, dispatch Job D as an Agent call and start A, B and C directly in the same message: Job A's `spec_validate_structure` call, Job B's `resolve` (then its `ci_wait_run` call or its lane commands), and Job C's `dependency-scan.sh` command. Do NOT wait for one before starting the next — they have no data dependencies on each other. See the Job D section below for both prompts and the full rule.

**Why the orchestrator runs them (#1275).** Until #1275 these three were delegated too, and the gate read what the delegate wrote, not what the instrument returned. On 2026-10-19 that misreported twice. A Job A delegate never called `spec_validate_structure`: it read the issue by hand and labelled its own reading `Raw tool response: ... PASS`. A Job B delegate reported `shellcheck exit=0` while its own output listed SC1091 in two files; `shellcheck -f gcc` returns 1 there, and through `xargs` the code reads 123, because `xargs` maps any child exit from 1 to 125 to 123. Reading the instrument's own JSON or `$?` removes the layer that misreported.

**Job A — Spec validation** (instrument: `spec_validate_structure`)

Call `mcp__sdlc-server__spec_validate_structure({ issue_ref: "<owner>/<repo>#<N>" })` yourself, in the same message as the Job D dispatch. The item reads two fields of the returned JSON. It passes only on `ok: true` with `valid: true`. On `valid: false` it FAILS and names the `missing_sections` exactly. Paste the JSON, or its `valid`/`missing_sections` excerpt, into the checklist evidence. A tool error (`ok: false`, or no response) is a FAIL for the item, never a pass.

**Job B — Lanes: CI first** (instruments: `ci_wait_run`, or the lane commands)

**Source rule (#1235, #1268).** CI's verdict for the pushed HEAD is the lane result whenever CI can give one. Running the same lanes again locally spends a shared box on a question CI has already answered. Decide the source in code, before any wait:

```bash
"$CISRC" resolve <repo_root> <marker_dir> <branch> <HEAD_SHA>
```

Run it with a Bash `timeout` of 300000. It budgets itself 90 s of wall clock (`PRECHECK_CI_TRIGGER_WAIT`), including starting a pipeline and waiting for it to appear, so it always prints its line. It prints one line:

- `ci run=<id> ref=<ref>` → run **Job B-ci**, waiting with that `<ref>`.
- `ci triggered run=<id> ref=<ref>` → run **Job B-ci**, waiting with that `<ref>`. No run existed, so the repo's declared `CI on demand` command started one. It runs at most once per SHA.
- `local no-ci` → run **Job B-local**. Checklist: `Validation (local lanes — no CI)`.
- `local NO-RUN <reason>` → run **Job B-local**. Checklist: `Validation (local lanes — CI NO-RUN: <reason>)`.

A `; shared host: …` suffix on a `local` line goes on the checklist as written. Book the host before running the lanes.

`resolve` never starts a pipeline the repo has not declared, because a generic trigger can start publish or deploy jobs. It never leaves Job B waiting on a run that doesn't exist. The repo declares both under Toolchain in `.claude-project.md`, and both are optional:

```
- **CI on demand:** `glab ci run --branch <branch>`
- **CI jobs:** validate, test
```

On GitHub the trigger is `gh workflow run <workflow> --ref <branch>`. `CI jobs` names the jobs a run must contain, all green, to count (see `coverage` below).

The checklist line names the source: `Validation (CI run <id> @ <sha7>)` or `Validation (local lanes — <why>)`.

**Job B-ci**

Call `mcp__sdlc-server__ci_wait_run({ ref: "<ref>", expected_sha: "<HEAD_SHA>", timeout_sec: 1800 })` yourself, where `<ref>` is the one `resolve` printed, not the branch name. On GitLab an MR pipeline's ref is `refs/merge-requests/<iid>/head`, and `ci_wait_run` filters by ref and SHA together, so the branch name would miss the run `resolve` found. (If `CISRC` is missing, use `<branch>`.) It waits server-side until the run completes or times out, so start it in the same message as the Job D dispatch, and the review runs while CI is waited on. From its JSON, write exactly one line yourself:

```
LANE ci:<workflow_name> | exit=<0 if final_status is success, else 1> | run=<run_id> sha=<sha>
```

- **`NO-RUN` is yours to decide, from the JSON.** `ok: false` with an `error` that begins `No CI run found` (and no `run_id` or `final_status`) means no run exists for that SHA. Write `NO-RUN <that error's first sentence>` and run Job B-local.
- Any other `ok: false` is a FAIL for the item (`exit=1`), never `NO-RUN` and never a pass.
- Do not re-derive or soften the status: a `timed_out`, `cancelled` or `failure` run is `exit=1`.
- **On GitHub, cross-check `final_status` against the check-run conclusion:** `gh api --paginate repos/<repo>/commits/<HEAD_SHA>/check-runs --jq '.check_runs[] | {name,conclusion}'` (`--paginate`, because the endpoint returns 30 check-runs a page). If `final_status` is `success` but any check-run's `conclusion` is `failure`, `cancelled`, `timed_out` or `action_required`, or is still `null` (not finished), the lane is `exit=1`. Name that check-run on the checklist. `gh run watch --exit-status` is never evidence (squawk #8): its exit code is the run summary's, which has read `success` while the job's own check-run still read `queued`.

The `LANE … | exit=` line keeps the shape Step 5's autochain path reads.

Then check the run against the repo's declared jobs, with that JSON's `run_id`:

```bash
"$CISRC" coverage <repo_root> <run_id>
```

- `covered` → the `LANE` line stands. No `CI jobs` declared also prints `covered`.
- `not-green <job>=<state>,…` → the lane is `exit=1`. Name those jobs on the checklist.
- `missing <job>,…` → this run is not the lane result. Write `NO-RUN run <run_id> lacks <jobs>` and run Job B-local.
- `unknown <reason>` → a FAIL for the item (`exit=1`), never a pass.

**Job B-local**

Run EVERY validation and test lane in `<repo_root>` yourself, with the Bash tool — not the first one you find. Lanes: every command `.claude-project.md` declares under Toolchain (Validation, Tests, and any other runnable lane). If it declares none, run EACH of these that is present: `./scripts/ci/validate.sh`, `./scripts/ci/test.sh`, `make test`, `python3 -m pytest tests/`, `npm test`. No lane is a superset of another: `validate.sh` passing says nothing about the test suite.

Run one Bash command per lane, in exactly this form, with `run_in_background: true` for a long lane. `<log>` is a file in `<marker_dir>`, one per lane:

```bash
<cmd> > <log> 2>&1; echo "exit=$?"
```

- Read `exit=` from that command's own output (for a background lane, its output once it reports completion). That is the lane's exit code, and nothing else is.
- Never pipe a lane through `tail`, `head`, `grep` or `xargs` before `$?`. A pipe reports the filter's exit, not the lane's, and `xargs` maps any child exit from 1 to 125 to 123. Read `<log>` afterwards, as its own step, for counts and failures.
- Invoke a multi-file linter once, with every file as argv: `shellcheck -f gcc <files...>`, never through `xargs`.
- A lane that has not printed `exit=` has no result. Never write its `LANE` line, or assemble the checklist, while it is still running.
- Run the lanes one at a time, never in parallel with each other: they share the box and its caches (in cc-workflow, `validate.sh` itself runs `dependency-scan.sh`, and so trivy and its cache).

Then write one line per lane yourself, ALL lanes first, then the verdict:

```
LANE <command> | exit=<code> | <counts from its own summary line, e.g. '233 passed'>
VERDICT: PASS only if every lane exited 0; otherwise FAIL
```

For each lane with a non-zero exit, add its failing output verbatim from `<log>` (50 lines max).

**Lanes and exit codes, not a verdict (#1101).** Job B-local used to say "probe in order … run whatever exists", which reads as first-match-wins. In cc-workflow that ran `validate.sh` alone (233/233), reported "Validation (actually ran)", and CI then failed on the pytest lane, which runs as a separate step. The per-lane line is the same denominator-before-verdict discipline Job C uses. Step 5's autochain path reads these `exit=` fields directly, because the gate cannot be met from a PASS/FAIL summary.

**Job C — Dependency vulnerability scan** (instrument: `dependency-scan.sh`)

Run both yourself, as two Bash commands (`<log>` is a file in `<marker_dir>`, as for the lanes):

```bash
bash <repo_root>/scripts/ci/dependency-scan.sh <repo_root> > <log> 2>&1; echo "exit=$?"
git -C <repo_root> rev-parse HEAD
```

Run the scan with `run_in_background: true`. Each trivy run inside it may take up to `DEP_SCAN_TIMEOUT` (300 s by default), which is longer than the Bash tool lets a foreground command run, and a killed command never reaches `echo`. A scan that has not printed `exit=` has no result, and is never a pass.

The item's value is that `exit=`, read from the command's own output and graded by the table below, at that commit. Then read `<log>` in full, and put its `coverage:` line and every UNSCANNED lock by name on the checklist, on every exit. A run covering 1 of 2 manifests is a scan over half a denominator, and it exits 6, not 0. Do not summarise, do not re-derive the counts, and do not substitute your own judgement for the exit code.

```
Exit codes:
  0  scanned, zero HIGH/CRITICAL      -> checklist item PASSES
  1  findings                          -> report each; do NOT auto-upgrade
  2  manifests present, ZERO ingested  -> checklist item FAILS
  3  trivy not installed               -> [SKIPPED]
  4  nothing scannable, absence not declared -> checklist item FAILS
  5  scanner/tooling error (timeout/no output/unparseable/partial
     install) -> checklist item FAILS — this is NOT a skip and NOT
     a pass. Ordinary triggers: first run pulling trivy's DB, a
     rate-limited or air-gapped network. Never treat an
     unmapped/unrecognized exit code as a pass.
  6  PARTIAL COVERAGE (some ingested, some UNSCANNED) -> checklist
     item FAILS — an unscanned lock is not a clean one (#1247)
```

**If the script is missing** (an older checkout, and today every repo but this one; see "Reach" below), run the raw-trivy fallback yourself, with its steps exactly as written:

```
         If the script is MISSING (older checkout), say so and fall back to
         `trivy fs --scanners vuln --severity HIGH,CRITICAL --include-dev-deps
         --list-all-pkgs --format json --quiet <repo_root>`, reporting the
         manifest count first. Do not report a verdict without a denominator.
         Both flags are
         REQUIRED on the fallback, not optional (cc-workflow#1169): trivy
         suppresses dev/test dependencies by default (a project whose entire
         dependency tree is dev-only scans ZERO packages without
         --include-dev-deps, while still exiting clean), and --list-all-pkgs
         only became trivy's default in v0.67.0, with this fleet pinning no
         minimum trivy version. dependency-scan.sh itself already carries both
         flags — this fallback exists only for a checkout that predates the
         script.

         Capture every trivy run to a file, never to the tool output (#1275).
         The Bash tool cuts its output at about 30k characters, and trivy
         lists a target's Packages BEFORE its Vulnerabilities, so a lock of a
         few hundred packages can be cut after its packages and before its
         findings: it reads as ingested with 0 HIGH/CRITICAL, a FALSE PASS.
         Run the main scan, and each per-file scan below, with
         run_in_background: true (a first DB pull can outlast the foreground
         limit), in this form, where <n> numbers the runs (0 for this one):
           trivy fs --scanners vuln --severity HIGH,CRITICAL --include-dev-deps --list-all-pkgs --format json --quiet <repo_root> > <marker_dir>/trivy-0.json 2> <marker_dir>/trivy-0.err; echo "exit=$?"
         stderr has its own file, so a warning cannot make good JSON
         unparseable. Read the packages and findings per target FROM THE
         FILE, with jq, never from tool output:
           jq '[.Results[]? | {Target, pkgs: (.Packages // [] | length), hc: ([.Vulnerabilities[]? | select(.Severity=="HIGH" or .Severity=="CRITICAL")] | length)}]' <marker_dir>/trivy-<n>.json
           jq '[.Results[]? | .Target as $t | .Vulnerabilities[]? | select(.Severity=="HIGH" or .Severity=="CRITICAL") | {target: $t, pkg: .PkgName, id: .VulnerabilityID, severity: .Severity, fixed: .FixedVersion}]' <marker_dir>/trivy-<n>.json
         A run that printed no exit=, printed a non-zero exit=, or left a
         file jq cannot parse scanned nothing: every lock it was to cover is
         UNSCANNED.

         On the fallback, FIRST enumerate the lockfiles. Run this exactly (one
         command, do not split it); it is the trust gate's own find:
           find <repo_root> \( -name node_modules -o -name .git -o -name dist -o -name build -o -name vendor -o -name .venv -o -name venv -o -name target \) -prune -o -type f \( -name 'bun.lock' -o -name 'bun.lockb' -o -name 'package-lock.json' -o -name 'yarn.lock' -o -name 'pnpm-lock.yaml' -o -name 'go.sum' -o -name 'Cargo.lock' -o -name 'uv.lock' -o -name 'poetry.lock' -o -name 'Pipfile.lock' -o -name '*requirements*.txt' -o -path '*/requirements/*.txt' \) -print
         Every line it prints is in the denominator, less two exclusions, both
         matching check-scannable.sh:
         (1) a pip requirements file with no entry pinned by '==' is a range
         declaration, not a lock. Test each one with
           grep -cE '^[[:space:]]*[A-Za-z0-9._-]+[[:space:]]*===?[[:space:]]*[0-9]' '<that file>'
         and where it prints 0, leave it out of the denominator and name it
         as unpinned, not UNSCANNED.
         (2) a bun.lockb with a bun.lock in the same directory is the same
         packages in bun's old binary format: leave it out. A bun.lockb with NO
         bun.lock beside it stays in; trivy cannot parse it, so it is
         UNSCANNED, and the remedy is bun's text lockfile, bun.lock.
         trivy's pip analyzer reads ONLY a file named exactly requirements.txt
         (#1247), so the scan above skips every other pinned requirements
         file. Scan each of those ALONE, under the name trivy reads, with the
         same flags and the same capture, giving each its own <n>:
           d=$(mktemp -d) && cp '<that file>' $d/requirements.txt && trivy fs --scanners vuln --severity HIGH,CRITICAL --include-dev-deps --list-all-pkgs --format json --quiet $d > <marker_dir>/trivy-<n>.json 2> <marker_dir>/trivy-<n>.err; echo "exit=$?"; rm -rf ${d:?}
         Its HIGH/CRITICAL findings count toward the verdict exactly like the
         main scan's. Its jq row's Target reads requirements.txt, and that row
         is that file's. A lock in the denominator is INGESTED when a jq row
         for it shows at least one package (for go.sum, the row for the
         go.mod beside it); every other one is UNSCANNED. Report the
         denominator and the ingested count, and name each UNSCANNED lock,
         before any verdict. Any UNSCANNED lock -> the checklist item FAILS:
         an unscanned lock is not a clean one. A declaration applies only when
         no lock is found; any found-but-unscanned lock FAILS. So an empty
         denominator FAILS unless a .no-scannable-dependencies at the repo
         root declares it with a reason.
```

**The denominator is emitted by the tool, not requested from the agent (#1137).** This job used to be prose asking a sub-agent to report the count. It complied — and compliance is the problem: an instruction can be forgotten by the next agent, misread, or quietly dropped in a rewrite, and the resulting verdict looks identical to a real one. `dependency-scan.sh` emits the number on every path including the passing one, so the report survives the agent.

**Reach, stated honestly: cc-workflow only, for now.** `install` excludes `ci/*`
from distribution (four sites), so `dependency-scan.sh` exists in a cc-workflow
checkout and nowhere else. In every other repo this job takes the fallback above:
raw `trivy`, with the orchestrator counting the denominator by hand from those
steps. That is prose, not a tool that emits the number, so it is exactly the path
the script replaces. The structural guarantee is real where the script is; the fallback
is what actually runs on flightdeck, mcp-server-sdlc and the rest until the kit
ships it (#1141).

It also closes a gap `check-scannable.sh` structurally cannot see. That check is **pre-scan** — it proves input exists. This one is **post-scan** — it proves the scanner ingested that input. Two green checks either side of a stage prove nothing about the stage between them, and flightdeck lives in exactly that gap: manifests present, trivy parsing none of them (`flightdeck#8`), both checks green — though `flightdeck#8`'s own root cause is worth re-measuring before it anchors a remedy (see below). cc-workflow was a partial instance of the same thing before `--include-dev-deps` above: 2 scannable, 1 ingested — not because this trivy build cannot read `bun.lock`, but because both of this repo's `bun.lock` manifests are entirely devDependencies, which trivy suppresses by default. With the flag, both parse cleanly (0 findings each). If flightdeck's tree is also dev-only, its "unsupported" diagnosis may be the same flag artifact, not a real parser gap — worth confirming before #1141 commits to "use a scanner that understands this ecosystem" as the remedy.

**Report the denominator and the commit before the verdict — never the verdict alone.** Two failures on 2026-07-19 make this non-optional:

- Job C returned `PASS — zero HIGH or CRITICAL` for a repo where trivy parsed **zero manifests**. A pass over an empty denominator is *no scan*, and it is indistinguishable from a clean one. Same shape as the `/mmr` gate in #925: reported fine, did nothing. It had also been masking a real defect for months — a repo whose lockfile was gitignored had therefore *never* been scanned, and the gate's silence and the defect were the same event.
- Two agents both reported `Results=1`, honestly, and disagreed — because they were scanning **different commits**. Denominator-first is necessary and not sufficient: *"how many manifests?"* and *"which commit?"* are two questions, and a local checkout is not the tree that ships. (@strangler)

### A trivy PASS is NOT a dependency clearance for lockfile-based JS/TS projects

**`trivy` parses `bun.lock`, not the installed tree.** It is therefore *structurally* blind to a vulnerable copy nested under a parent — not unlucky, blind by construction. Reproduced independently on four separate trees: **0 HIGH/CRITICAL reported on a tree carrying a known-vulnerable nested `ajv/fast-uri@3.1.0`** that a filesystem probe found immediately.

This matters because it is exactly how a dependency bump becomes cosmetic. **A version outside a parent's declared range does not upgrade that parent — it makes the parent keep a private nested copy.** The top-level lockfile entry reads fixed, trivy agrees, and the CVE is live. A real bump nearly shipped this way; it was caught by reading the nested entry, not by scanning.

**So for any change touching dependencies, trivy is necessary and not sufficient.** Also run:

```bash
cd "$REPO"                      # RELATIVE — an absolute path breaks path-based probes
find node_modules -name package.json | while IFS= read -r f; do
  python3 -c "
import json
try: d=json.load(open('$f'))
except Exception: raise SystemExit
if d.get('name')=='<pkg>': print(d.get('version'), '$f')"
done
# PASS = exactly one line per target, at the pinned version
```

**Read `name` from the file. Never infer identity from the path.** Four path-based variants were tried on 2026-07-19 and every one failed, in both directions:

| variant | failure |
|---|---|
| absolute path | `*/node_modules/` matches the absolute prefix → healthy top-level copy reads as nested (**false positive**) |
| "denominator must be > 0" | bun hoists to a flat tree; zero nested entries is the *correct* answer (**false alarm**) |
| `-path "*pkg*"` | matches `package.json` files *inside* a package — `fast-uri/benchmark/package.json` declares `version 1.0.0` (**false positive**) |
| `-maxdepth 3` | a nested copy's file sits at **depth 5**; the cap **cannot reach the class being searched for** (**FALSE NEGATIVE**) |

Reading `name` is immune to all four **because it never asks the path a question about identity.**

**Validate the probe before trusting a zero.** Plant a copy at depth 5 (`node_modules/<pkg>/node_modules/<target>/package.json` with `name` + `version`), confirm the probe finds it, remove it, confirm the clean tree reads one line. **A probe that has only run on a clean tree has not been tested** — and a probe run on a *flat* tree cannot detect a nested-copy bug at all, which is how the `-maxdepth` variant was reported "verified".

**Durability, with a caveat that produced a false pass.** Deleting the lockfile and reinstalling from the manifest is the right instinct, but a zero afterward can mean the **dependency chain disappeared** rather than the pin held — a parent bumping to a version that drops the vulnerable package entirely. *That zero is chain-absence wearing a pass's clothes.* Force the chain present and A/B the override instead: without → vulnerable version, with → pinned version.

**Why this is written out rather than summarised:** five verification instruments were wrong on 2026-07-19 and **not one was caught by review** — every one by someone running it against a case that could fail. The instrument is a claim, and claims get tested.

**Job D — Code review** `model: opus`

Job D has **two** prompts: a **full** pass and a **delta** re-run. Which one you use is not a judgment call — it is decided by the rule below.

> **Resolve the merge-base to a SHA, then diff against the WORKING TREE: `mb="$(git -C <repo_root> merge-base <base> HEAD)"` then `git -C <repo_root> diff "$mb"`.** (`precheck-review-scope.sh gather` does exactly this.) Since #1235, Step 0.5 guarantees the tree equals the pushed HEAD, so this **is** the commit range the PR/MR carries. The mechanics stay working-tree-based on purpose: they stay correct if the tree ever is not clean, and `pmr-bench-arm.sh` still measures the pre-commit protocol through them.
>
> Not `git diff <base>...HEAD`, and not `git diff <base>`. Both are wrong, in opposite directions, and the first one was catastrophic in the pre-commit gate:
> - **`<base>...HEAD`** is a *commit-to-commit* range (`git diff $(merge-base A B) B`), so the working tree and index are excluded **by construction**. In a pre-commit gate the changeset IS the working tree and HEAD has not moved — so this diff is **empty**. Measured on this very branch during #1194: `git diff main...HEAD` returned **0 bytes** while `git diff $(merge-base)` returned **61,193**. Embedding the three-dot form hands the reviewer nothing and gets back "No findings".
> - **bare `git diff <base>`** compares base's *current tip* to the working tree, so if someone pulls `<base>` mid-cycle its new commits appear inverted as phantom deletions.
>
> Resolving the merge-base first gets both properties: merge-base semantics (no phantom deletions) *and* the working tree (the code actually under review).
>
> **`<base>` is the branch this work will merge into — never a hardcoded `main` (#1194).** Resolve it, do not assume it: it is the PR/MR's base, which Step 0.5 recorded (`gh pr view --json baseRefName -q .baseRefName`). On a PR/MR into a `kahuna/*` sandbox the base is the wave integration branch, and on repos whose default is `release/*` it is that release branch. A literal `main` reviews the wrong range in both cases — and on the sandbox path there is no human present to notice the reviewer read a nonsensical diff.

**The first Job D pass of a precheck cycle ALWAYS uses the full prompt.** There is no condition, issue type, label, or file extension that scopes it. The delta prompt exists only to avoid re-reading code a reviewer has *already cleared in this same cycle*; it is not a cheaper first look.

**Both prompts carry the untracked channel, and the full one needs it just as much.** Since #1235 it should be empty: Step 0.5 refuses a tree with an untracked file, and fixes are committed and pushed before a re-run. **A non-empty `new-untracked` mid-cycle means the tree changed outside the commit flow. STOP, then commit and push it or remove it, and re-run `ready`.** The channel stays because it is what proves the emptiness. Under the pre-commit gate it carried real files: `git diff <base>` does not show untracked paths, and a brand-new file could be untracked for the whole cycle. Without the second channel the full pass never sees it, yet `record` afterwards writes that file into the reviewed set, so the *next* pass correctly omits it as already-cleared. The file would then ship reviewed by nobody: bookkeeping asserting a coverage claim the prompt never made. Do not drop the untracked block from either prompt on the grounds that a reviewer "would probably run `git status`" — spelling it out in one prompt is already the admission that you cannot rely on that.

**Job D-full** — used when `resolve` (below) printed `full`: the first pass of every cycle, and any pass where the recorded state could not be trusted.

> **The parent gathers the content and embeds it. The reviewer is never handed a command to run.** `feature-dev:code-reviewer` has no `Bash` tool — its tool list is `Glob, Grep, LS, Read, NotebookRead, WebFetch, TodoWrite, WebSearch, KillShell, BashOutput`. Every `<output of: …>` below is substituted by YOU before dispatch. This is not a style preference: a reviewer with no `git` cannot produce a diff from any ref, so one told to fetch it would review nothing and report success. (Under the pre-commit gate the ref was a dangling `git stash create` SHA; since #1235 it is a pushed commit, and the rule is unchanged.) (The plugin's own agent definition says "review unstaged changes from `git diff`" — an instruction it cannot follow. `skills/review/SKILL.md` already embeds instead of instructing; match it.)

```
subagent_type: feature-dev:code-reviewer
model: opus
prompt: "Review this changeset in <repo_root>.

         ### Diff — <N> lines total, read ALL of these files before reviewing
         <the paths printed by: precheck-review-scope.sh gather <repo_root> <marker_dir> <base>>

         ### Untracked files — NOT in the diff above, read each IN FULL
         <output of: precheck-review-scope.sh new-untracked <repo_root> <marker_dir>
          — prefix each line THAT IS A PATH with <repo_root>/ (Read rejects relative paths);
            pass any line beginning UNRESOLVABLE through verbatim, it is a warning not a file;
            and if the command exits NON-ZERO or writes to stderr, do NOT dispatch — most
            often <marker_dir> is inside <repo_root>, which the script rejects>

         The diff is given so you do not have to reconstruct it. You still have
         Read/Grep/Glob — use them freely to pull in whatever context you need to
         judge these changes: callers, callees, tests, sibling implementations,
         project rules. Do not restrict yourself to the lines above.

         ### Findings from the previous pass (OMIT on a cycle's first pass)
         <prior findings list, verbatim — Job D-full is ALSO the mid-cycle re-run prompt
          when the recorded state could not be trusted; dropping the findings there means
          a bare 'No findings' gets read as 'every prior critical is resolved'>

         If that section is present, return per-finding RESOLVED / NOT RESOLVED / PARTIAL
         FIRST, each with the file:line that demonstrates it — never RESOLVED without
         pointing at the code — then any new issues.

         Use confidence-based filtering — report only issues you are genuinely confident matter.
         Categorize findings as: critical / important / minor.
         Return a structured list; if none, say 'No findings'."
```

**Gathering the diff is `precheck-review-scope.sh gather`, not hand-written bash.** Two hand-written versions shipped broken: `split` does not create its destination directory (the anti-truncation path failed every time), and the size threshold sat *above* the Bash tool's ~30k output cap, so the transport truncated the diff before any guard fired. Prose-bash that nobody executes will be wrong. The subcommand is exercised by the regression suite.

```bash
precheck-review-scope.sh gather <repo_root> <marker_dir> <base-or-ref>
```

Fourth argument is `<base>` for a full pass, or the `<ref>` from `resolve` for a delta. It prints one of:

| output | meaning | what to do |
|---|---|---|
| `files <N> <path>…` | diff on disk, `<N>` lines total | put **every** path AND the line count in the prompt |
| `empty 0 <path>` | genuinely 0 bytes | legitimate ONLY for an untracked-only changeset — say so **explicitly**; never leave a bare empty heading |
| exit 2 + stderr | target unresolvable, or `git diff` failed | **STOP, do not dispatch.** Fix `<base>` (`origin/<base>`, `git fetch`) — an empty or error-filled `### Diff` reads as "nothing changed" |

**It hands over paths, never pasted content.** The reviewer has `Read`; a path costs a few tokens where an 80 KB body costs twenty thousand, and a paste cannot survive the transport cap anyway. Files split at 1500 lines — under `Read`'s 2000-per-call limit — and you MUST state the total, so the reviewer can verify its own coverage. N paths plus a total tells it when it is done; a single path does not.

**Both prompts, same rules.** The delta channel empties identically, plus one of its own: `resolve` prints two tokens (`delta <ref>`), so parse them — `ref="$(… resolve … | awk '{print $2}')"`. Passing the whole line yields `git diff "delta abc123"`, exit 128, empty stdout.

> **Resolution ladder (the rationale; the probe itself runs in Step 0 above).** `command -v` alone is not enough, because a bare-name probe reports "missing" in two cases where the tool is present: `install --local` places scripts in `<repo_root>/.claude/bin`, which the installer deliberately keeps **off** `PATH`; and a cc-workflow checkout carries `scripts/precheck-review-scope.sh` directly. Treating either as "kit not installed" makes the feature inert exactly where it is most exercised, and prints a false diagnostic. Walk the rungs in order and use the first that resolves.
>
> Only when all four fail is the kit genuinely absent. Then: treat scope as **`full`**, gather the untracked list with `git -C <repo_root> ls-files --others --exclude-standard`, and write the diff to disk yourself rather than pasting it (`mb="$(git -C <repo_root> merge-base <base> HEAD)"; git -C <repo_root> diff "$mb" > <marker_dir>/full.diff; split -l 1500 <marker_dir>/full.diff <marker_dir>/part-`), handing over the part paths plus a `wc -l` total. Note `[delta scoping unavailable — kit not installed]` on the checklist. **Never substitute an empty section** — empty reads as the affirmative "there is nothing here".

**Scope is decided by `precheck-review-scope.sh`, not by you.** The rule is small enough to look obvious and was wrong in a way that reviewed *nothing* while reporting success (see the script's header for the full post-mortem), so it lives in one tested implementation that both this skill and its regression test invoke. Do not re-derive it inline. `<marker_dir>` is this session's scratchpad directory — pass the literal absolute path; it must be outside `<repo_root>` so the marker can never be staged.

**At the start of every precheck cycle, before the parallel batch in Step 2 launches:**
```bash
precheck-review-scope.sh reset <repo_root> <marker_dir>
```
This is what makes "pass 1 is always full" mechanical rather than conventional. The marker is session-scoped and would otherwise survive into the *next* cycle, where it would scope that cycle's first pass to a stale range — the new work would be invisible. One line removes the possibility.

**Before each Job D pass, ask the script which prompt to use:**
```bash
precheck-review-scope.sh resolve <repo_root> <marker_dir>
# -> "full"          : use Job D-full
# -> "delta <ref>"   : use Job D-delta, reviewing `git diff <ref>`
```
It prints exactly one verdict and every unresolvable condition prints `full`. There is no path that yields "review nothing".

**Order matters: run `resolve` BEFORE `new-untracked`.** A `full` verdict clears the markers, which is what makes `new-untracked` re-widen to the whole untracked set. Calling `new-untracked` first on a mid-cycle fall-back to `full` returns a still-delta-scoped list and reproduces the mixed-scope defect exactly.

**Record IMMEDIATELY when a Job D pass returns — before you edit a single file** — and only if it actually returned a review:
```bash
precheck-review-scope.sh record <repo_root> <marker_dir>
```
The ordering is load-bearing: the snapshot must equal *what the reviewer saw*. Record → fix → resolve is correct. Fix → record merely wastes a pass (it resolves to `full`). But fix-round-A → record → fix-round-B → resolve **excludes round A from the delta**, so those fixes are never re-read — the unsafe direction, and the one that looks like it worked.

**Record only on a parseable verdict** — a findings list, or the literal `No findings`. On an error, refusal, timeout, or empty return, run `reset` instead, never `record`. A sub-agent that returns the string "I could not access the repository" has *returned*; recording that as reviewed would permanently skip the range. This is the same failure the Job C guidance above is written against: a pass over an empty denominator is not a clean pass, it is no pass, and the two are indistinguishable from the outside unless you refuse to record one as the other.

**Job D-delta** — used when `resolve` printed `delta <ref>`. Same rule: the parent runs the command, the reviewer receives the content.
```
subagent_type: feature-dev:code-reviewer
model: opus
prompt: "Re-review after fixes in <repo_root>.

         ### Changes since the last completed review — <N> lines, read ALL these files
         <the paths printed by: precheck-review-scope.sh gather <repo_root> <marker_dir> <ref>>

         ### Untracked files changed or added since that review — read each IN FULL
         <output of: precheck-review-scope.sh new-untracked <repo_root> <marker_dir>
          — prefix each line THAT IS A PATH with <repo_root>/ (Read rejects relative paths);
            pass any line beginning UNRESOLVABLE through verbatim, it is a warning not a file;
            and if the command exits NON-ZERO or writes to stderr, do NOT dispatch — most
            often <marker_dir> is inside <repo_root>, which the script rejects>

         ### Findings from the previous pass
         <prior findings list, verbatim>

         Read every file the diff touches IN FULL, not only the hunks — a fix that is
         correct in isolation can still break a caller outside the diff. Trace the
         callers and dependents of anything the fix changed. You have Read/Grep/Glob;
         use them.

         Return, in this order:
         1. Per prior finding: RESOLVED / NOT RESOLVED / PARTIAL — each with the file:line
            that demonstrates it. Do not mark RESOLVED without pointing at the code.
         2. Any NEW issue the fixes themselves introduced.
         Use confidence-based filtering on (2). Categorize as critical / important / minor."
```

**Where the stakeholder channel goes when it lands (#1194 follow-on).** Both prompts are sectioned so a contract-graph stakeholder list drops in as one more `###` block — files that share declared contract tokens with the changeset but are not part of it, which a diff can never surface. Keep the "use Read/Grep freely" instruction when it does: whole-file reading is how the reviewer caught the `/devspec upshift` emitter that shared zero lines with the change.

**Why the delta is safe, stated plainly:** `<ref>` is a snapshot of the working tree *as the last reviewer saw it* (since #1235, on a clean tree, that is the reviewed HEAD; in rearm it is the last commit carrying a pass), so `git diff <ref>` covers everything that changed since — the fixes, any other edits made in between, and any new commits. Nothing on the branch escapes review; the full diff is still reviewed, exactly once, on pass 1. What the delta drops is re-reading already-cleared code. Untracked files are handed over separately because a working-tree snapshot cannot contain them. Jobs A, B, and C stay unscoped and run in full on every pass, so the entire test suite remains the backstop for cross-file breakage the reviewer's dependent-tracing might miss.

**The trap this replaced, so nobody reintroduces it:** the obvious version of this feature records `rev-parse HEAD` and re-reviews `<prev>..HEAD`. Because `/precheck` runs *before* the commit, HEAD does not move between passes — so `prev == HEAD`, `merge-base --is-ancestor` returns 0 (ancestry is reflexive, so no guard fires), the diff is **empty**, and pass 2 reviews nothing while reporting success. That was the first implementation of #1194 and code review caught it. A two-dot commit range cannot contain uncommitted work; do not "simplify" the snapshot back into one. (Since #1235 fixes are committed and pushed, so HEAD *does* move and the snapshot `record` stores on a clean tree *is* HEAD. The snapshot code is what makes that correct in both worlds; the equality check in `resolve` is what still refuses an empty delta when nothing was pushed.)

**Why this optimisation and not a conditional gate.** The expensive thing about precheck is review wall-clock (~8 min/pass; three passes approaches 30 min, which is why a one-line fix can cost 15+ minutes and why agents drift toward filing follow-up issues instead of fixing inline). The tempting "fix" is to skip review for doc-only or chore-labelled work. **Do not.** #1191 was labelled `chore`, its own acceptance criteria said "no direct pytest coverage — it's a prose skill file," and its diff contained a real Bash defect: a rename guard that reported success while doing nothing. Issue type is self-reported *intent* and says nothing about what the diff contains. Scoping a re-read is safe because the skipped code was genuinely reviewed; skipping a gate on a label is not.

### Step 3 — Fix high+ findings (serial)
Wait for all four jobs to finish: Job D's Agent to return, and each of A, B and C to give its JSON or `exit=`. **The moment Job D returns, run `record` — before touching any file** (or `reset`, if it errored/timed out rather than returning a verdict). Then, if Job D returned critical or important findings, fix them. Re-run Job D after **any** fix — not only "non-trivial" ones. That escape hatch existed because a re-run cost a full ~8-minute re-read; the delta removes the cost, so the judgment call is no longer worth its risk (#1191 is the standing example of a "trivial" change carrying a real defect). Ask `precheck-review-scope.sh resolve <repo_root> <marker_dir>` which prompt to use; do not decide by eye. Both arguments are required — the script exits 2 with usage if either is missing. Carry the prior pass's findings into the re-run prompt verbatim so it can verify each one rather than rediscover it. A failed Job A, B or C result blocks its checklist item.

**A fix is a commit (#1235).** Fix, then commit and push it (`/scp`), then re-run `ready`; its new SHA is the new `HEAD_SHA`. The pushed fix starts a new CI run, so Job B-ci runs again for the new SHA, and Job D re-runs as the delta `resolve` names. Reviewing an uncommitted fix and then pushing it is the defect this ordering prevents: the pass would describe a tree that is not the commit it gets posted on.

### Step 4 — Assemble the checklist; on a pass, post the status and mark ready
Collect results from all four jobs and assemble the checklist (see below). Then:

1. **A pass** is the mechanical definition Step 5 also uses: every checklist item verified, zero unresolved critical/important findings from the latest Job D pass, every Job B `LANE … | exit=` line `exit=0` (at least one), Job C exit 0. On a pass:
   1. Re-run `"$SCOPE" ready`. It must still print `ready <HEAD_SHA>`; a push since the review means review again, not post.
   2. Post the status: `"$STATUS" post <repo_root> <HEAD_SHA> "#<N> review <passes, e.g. full+delta> clean; lanes <ci|local>; trivy <0|skipped>"`. It reads the status back and exits non-zero if the status isn't there. A failure → STOP and report it; never mark ready without it.
   3. Mark the PR/MR ready: `"$STATUS" mark-ready <repo_root> <PR_NUMBER>` → `ready <N> <sha>`. It refuses (exit 4) unless the PR/MR's head carries the pass, then reads the PR/MR back. On GitHub it uses the GraphQL `markPullRequestReadyForReview` mutation; on GitLab it rewrites the title without the draft prefix. **Never use `gh pr ready` or `glab mr update` for this.** glab rewrites the title on most update flags, and on GitLab the draft state *is* the title, which is why the kit stopped relying on glab's porcelain here. From the mcp-server-sdlc release that carries #592, its `pr_ready` is the MCP equivalent. Any non-zero exit → STOP, and the PR/MR stays a draft.
2. **Short of a pass:** post nothing and leave the PR/MR a draft. Present the checklist with what failed; the STOP below is then for rework. If BJ looks at the exceptions and says to go anyway, that go is what posts the status, with `exceptions approved by BJ: <which>` in the description, and then marks it ready.

Then **notify BJ**: `disc_send` to `#precheck`, **then `vox`**. **ALWAYS do both.** If `disc_send` fails (MCP unavailable, network), still do `vox`.

### Step 5 — Sandbox detection + the merge gate
Precheck has already done everything up to the merge. What remains is the merge call, and that is all an exception skips.

Run **sandbox-context detection** (see "Sandbox Auto-Approval" below): if the PR/MR's base ref matches `^kahuna/[0-9]+-`, emit the sentinel line `[AUTO-APPROVED: kahuna sandbox]` and invoke `/mmr` immediately with no wait.

Otherwise, check for an **approved autochain** (CLAUDE.md "Exception: Approved Autochain", #1224). Resolve `autochain-gate.sh` with the same ladder as Step 0 — `PATH`, then `<repo_root>/.claude/bin/`, then `<repo_root>/scripts/` — and run `autochain-gate.sh check <repo_root> <N>`, where `<N>` is the `issue_number` that `ibm()` returned in Step 1. Auto-approve **only** when it exits 0 printing `approved <epic> armed_at=<ts>` **and** this cycle meets the mechanical pass definition:
- every checklist item verified;
- zero unresolved critical/important findings from the latest Job D pass;
- **every** `LANE … | exit=` line you wrote for Job B, from the instrument's own JSON or `$?`, reads `exit=0`, and there is at least one. A missing lane line, a lane still running, or a bare PASS with no lane lines is not a pass;
- Job C exit 0.

Then put the gate's two output lines (`approved … armed_at=…` and `approval: …`) on the checklist, so the approval being relied on is visible at the moment it is used, emit `[AUTO-APPROVED: autochain #<epic>]`, and invoke `/mmr`. A gate that cannot be found, a `not-approved` (including an expired approval), or any item short of a pass → STOP below. The gate fails closed; so does this step.

Otherwise, a **standing merge grant** (CLAUDE.md "Exception: Standing Merge Grant") also skips the STOP, under all of its conditions: BJ's own words, given directly and recorded in memory; a **bounded, named effort** (a grant for "all PRs", or an old grant that only skipped `/mmr`'s second ask, does not qualify) with this PR plainly inside it; the same mechanical pass as the autochain bullets above; and nothing the prod rule gates, nor any tag, release or install. Put the memory file, BJ's words verbatim, the scope, and one sentence on why this PR is inside it on the checklist, then invoke `/mmr`. This path is applied by you, not detected by a script, so a grant whose scope you have to stretch does not apply. When in doubt, STOP.

Otherwise, a **lead-agent grant** (CLAUDE.md "Exception: Lead-Agent Grant") skips the STOP too, but only in the session of the agent it names. It requires all of these:
- BJ's own words, given directly to you and recorded in your memory.
- The Dev-Name in `.claude/agent-identity.json` matches the name in the grant. The memory loads in every session in this checkout, so its presence proves nothing.
- The repo's origin is in the grant's organization.
- The same mechanical pass, on this exact head.
- Nothing the prod rule gates.

It is never relayed, so a grunt or peer you tasked never applies it. Their PR/MR stops at ready, and you merge it only on your own `/precheck` run on its head. Their precheck, and any `precheck` status it posted, is evidence, not the pass. Put on the checklist the memory file, BJ's words verbatim, the Dev-Name match, and one sentence on why this origin is inside the organization. Then emit `[AUTO-APPROVED: lead-agent grant]` and invoke `/mmr`. When in doubt, STOP.

Notifications fire in every auto-approval path exactly as they would before a STOP. A notification failure is reported on the checklist; it does not change the gate's answer in either direction.

Otherwise **STOP.** The PR/MR is ready and waiting for BJ's merge call: `/mmr`, `/scpmmr`, or an affirmative. Negative or rework → return to work. Fix, commit and push, and the next run is `/precheck rearm` if the PR is still prechecked at an ancestor. Never bypass the STOP on notification failure; outside the auto-approval paths above, never bypass it at all.

### `/precheck rearm` — a push to a prechecked PR/MR (BJ ruling K-11)

The full precheck runs on the exact commit the PR/MR opens ready with. **After that, a push needs only a review of its new commits, a green pipeline at the new head, and any platform approval re-given at the new SHA.** It needs no full re-run, no checklist, no `#precheck` post or `vox`, and no STOP, **unless the push changes what the MR does**. `/mmr` runs this itself when the head has lost its status.

1. `"$SCOPE" ready` → `HEAD_SHA` (STOP on `not-ready`). Then `"$STATUS" pr-head <repo_root> <PR_NUMBER>` and **STOP unless its SHA equals `HEAD_SHA`.** Rearm reviews the local checkout, so the local checkout must be the PR/MR's head. Otherwise the status would land on another branch's commit while the PR/MR being merged was never reviewed.
2. `git -C <repo_root> fetch -q origin <base>`, then `"$STATUS" last-success <repo_root> <base>` → `PREV`. It reads `origin/<base>`, so the fetch is what keeps a commit that another PR already landed from lending this branch its pass. On `none` (no commit on the branch carries a pass), there is nothing to rearm from: run the **full** precheck above. **Any non-zero exit → STOP**: 3 is an API error and 2 is a base it can't resolve. Never treat either as `none` or as a pass.
3. `"$SCOPE" gather <repo_root> <marker_dir> <PREV>`, then Job D-delta (below) with that diff and one more instruction: *"Also answer, first line of your reply: `BEHAVIOUR-CHANGE: yes|no — <one sentence>`. Yes means this delta changes what the MR does: new or removed behaviour, scope, interface or acceptance criteria, as opposed to fixes and adjustments inside what was already reviewed."* Then run Job B yourself for `HEAD_SHA`, by the same source rule as the full gate: B-ci when a CI run exists for `HEAD_SHA`; B-local when B-ci finds `NO-RUN` or the repo has no CI. Otherwise a repo without CI could never rearm clean.
4. **Clean:** no critical or important findings, `BEHAVIOUR-CHANGE: no`, and every lane `exit=0`. Post the status on `HEAD_SHA` with the description `#<N> rearm from <PREV7>: delta clean; lanes <ci|local>`. Make no announcement and no STOP. If BJ's merge go was already given, it still stands: continue to `/mmr`. Re-request platform approvals the push reset (GitLab MR approvals), and say so.
5. **Not clean:** fix it as in Step 3 and rearm again. **`BEHAVIOUR-CHANGE: yes`**, or a reviewer that does not answer the question → run the **full** precheck from Step 0.5, including its checklist, notification and STOP.

The last reviewed SHA comes from the commit status, not from the session marker, so rearm survives a `/clear`, a reseed and a different session.

## Dependency Vulnerability Scan
Job C in the parallel batch: the orchestrator runs `dependency-scan.sh` (or the raw-trivy fallback) itself and reads its exit code. Interpret the result as:
- **PASS** → checklist item passes.
- **SKIP** → emit `[SKIPPED — trivy not installed]` on the checklist. Do not fail the gate.
- **FINDINGS** (`dependency-scan.sh` exit 1) → report each finding (package, CVE, severity, fixed version if any) as a deferred checklist item. Do NOT auto-upgrade dependencies — the user approves the codebase state at the gate. **The checklist item FAILS on any HIGH/CRITICAL finding, with or without a fix available** — `dependency-scan.sh` does not distinguish them (no `--ignore-unfixed` support; `.trivyignore` is explicitly disabled via `--ignorefile /dev/null`, not merely undocumented), which is stricter than this skill's own prose promised before this scan was a real tool rather than an agent's judgment call. Tracked for a policy decision: #1188. **Escape hatch that exists today, undocumented until now:** `DEP_SCAN_SEVERITY` (env var, default `HIGH,CRITICAL`) overrides the severity filter — e.g. `DEP_SCAN_SEVERITY=CRITICAL ./scripts/ci/validate.sh` to stop blocking on HIGH while #1188 is unresolved. This is a manual, visible override for an operator to reach for, not something Job C or this skill invokes on its own.
- **SCANNER/TOOLING ERROR** (`dependency-scan.sh` exit 5 — timeout, no scanner output, unparseable scanner output, OR a partial install missing `check-scannable.sh`) → the checklist item FAILS. This is not a skip: the scan did not run to completion, which is not evidence of a clean dependency tree. Ordinary triggers (first DB pull, rate-limited/air-gapped network) are not a reason to wave it through.
- **PARTIAL COVERAGE** (`dependency-scan.sh` exit 6: some counted locks ingested, at least one UNSCANNED, matched by name) → the checklist item FAILS, naming each unscanned lock. A clean result over part of the denominator is not a pass (#1247); the trust gate's `trivyCoverage()` HOLDs the same shape, so the two gates agree on every lock `check-scannable.sh` counts. They do not yet agree on which locks are counted: a second JS lock in one directory, or a lock with no manifest beside it, is counted by the gate's find alone.

## The Checklist (full every time; a checkmark means VERIFIED by reading the codebase)
**Context:** Project | Issue #N — title | Branch `feature/N-...` → `<base>` | PR/MR #<PR_NUMBER> @ `<HEAD_SHA7>`
- [ ] Implementation (AC verified) — [ ] TODOs (searched+addressed) — [ ] Docs (reviewed+updated) — [ ] Validation (CI run `<id>` @ `<sha7>`, or local lanes — actually ran)
- [ ] New tests (cover new code) — [ ] All tests pass (entire suite) — [ ] Scripts executed (linting is NOT testing) — [ ] Code review (high+ fixed)
- [ ] Dependencies (trivy: 0 HIGH/CRITICAL, or exceptions documented, or [SKIPPED])
- [ ] `precheck` status posted on `<HEAD_SHA7>` and read back — [ ] PR/MR marked ready (or: not posted, still a draft, because <what failed>)

**Summary:** `[codebase]` `[docs]` `[tests]` `[config]`. **Findings:** `[fixed]` / `[deferred]` / "(none)".

## The Notification (Discord + vox)
Resolve identity from `<project_root>/.claude/agent-identity.json`; fall back to `/tmp/claude-agent-<md5>.json` if absent (transition window). Use it for both the Discord post and the vox announcement.

**Important:** Do NOT prefix the Discord post with `@all`, `@<Dev-Team>`, or any `@`-mention. This post is for BJ only (human-facing). The discord-watcher filters by `@`-addressing, so an `@`-prefix would fan the precheck gate notice out to every listening agent in the fleet. Unaddressed is intentional.

**`disc_send` to `#precheck` (`1491195025198157834`) — exact body shape:**
```
⚠️ **Precheck passed — PR/MR ready for your merge call**   (or: ⚠️ **Precheck failed — rework**)

**Project:** <project-name>
**Issue:** #<N> — <title>
**PR/MR:** <url> — `<type>/<N>-<slug>` → `<base>` @ `<sha7>`
**Checklist:** `[codebase]` `[docs]` `[tests]` `[config]`
**Findings:** <fixed> / <deferred> / (none)

Ready for `/mmr` / `/scpmmr` or rework.

— **<dev-name>** <dev-avatar> (<dev-team>)
```

**`vox`:** same info, conversational, 1-2 sentences, ending with "Ready for your merge call." (a pass) or "Back to rework." (a failure).

**FRONT-LOAD the speaker identity — open with `"<Dev-Name> here."`** (#952). Synthesis runs at ~1x realtime, so a long body can exhaust a caller's `timeout` budget *during synthesis*, and whatever is still playing gets cut — the tail first. `vox` appends its own `. This is <name>.` sign-off, but the sign-off is the tail, so it is exactly what a truncation drops. Leading with the name means the identity is spoken first and survives a cut. Example — **pipe it, never inline** (#942):

```bash
vox <<'EOF'
<Dev-Name> here. Precheck passed on #<N>, and the PR is ready. <one sentence>. Ready for your merge call.
EOF
```

Do NOT open with "Precheck passed on #<N>…" and rely on the appended sign-off to identify you; that identity is the first thing lost.

**Two hazards, not one (#942 substitution, #1136 termination).** The quoted
delimiter fixes the first. It does not fix the second: a body containing a line
equal to the delimiter truncates the text there and executes the remainder.

**The boundary is the content, not the author.** A heredoc is safe only when you
can see the whole body in the source and no line of it could equal the delimiter.
The template above has a `<one sentence>` placeholder — so you *cannot* see the
body, and this announcement is the message most likely to carry a code span
(it names issues, branches and scripts). **Compose it with the `Write` tool and
feed it on stdin:**

```bash
vox < /tmp/precheck-announce.md
```

`vox` takes **no path argument** — `vox /tmp/precheck-announce.md` synthesises the
literal path string and exits 0, giving you silence and a success code. Verified;
an earlier draft of this paragraph got it wrong.

**The heredoc is a safety requirement, not formatting.** `vox "…"` passes prose through a double-quoted shell string, where backticks and `$(...)` are command substitution — bash executes them before `vox` runs, and strips them from what gets spoken. A precheck announcement names issues, branches and scripts, so it is exactly the message most likely to carry a code span. The quoted `<<'EOF'` delimiter is load-bearing: a bare `<<EOF` still substitutes. See #942 and `tests/test_body_never_inline.py`.

`vox` playback is non-blocking by default (it detaches, so a caller timeout bounds synthesis, not playback), so no flag is needed — just invoke `vox` normally.

## Sandbox Auto-Approval (KAHUNA Flight Agents)

**Workflow flights do not run `/precheck`.** A flight run by the per-wave Workflow (`/nextwave`, `/wavemachine`) commits in its handed worktree and returns. It never pushes and never runs `/precheck`, `/scp*` or `/mmr`. Prime(reconcile) lands it on `kahuna/*`, and the wave trust gate's review signal is its review. The sdlc server exempts any PR/MR whose base is `kahuna/*` from the `precheck` status (`docs/precheck-status.md`). This section, despite its heading, applies to an agent that opens a PR/MR into `kahuna/*` by hand, for example to repair a held wave (#1209).

Work landing in a KAHUNA sandbox merges into a per-wave integration branch (`kahuna/<N>-<slug>`), not into `main`. In that context the human merge call is a redundant pause — the wave already runs autonomously, and its trust gate reviews the composed `kahuna→base` diff before anything leaves the sandbox. The full checklist (validation, code-reviewer, trivy), the `precheck` status and the Discord/`vox` notifications still run; only the STOP-and-wait for the merge call is bypassed.

**Why this exists (narrative).** The wave's contract with the human is "I will surface the *wave* result, not every change that lands in it." A hand repair into a held wave's integration branch should not re-serialise that wave on a human: the agent landing it completes the full checklist and then auto-progresses. It never bypasses quality, only the human pause; the wave's trust gate reviews the result when the held wave is resumed. Outside the sandbox — i.e. an agent operating directly against `main` — the original rule applies in full and the STOP is non-negotiable, unless one of Step 5's other exceptions applies: an approved autochain, a standing merge grant or a lead-agent grant, each with its own conditions, described in Step 5 rather than here. See Dev Spec §5.2.1 for the authoritative statement; the mechanical detection (regex `^kahuna/[0-9]+-`, sentinel `[AUTO-APPROVED: kahuna sandbox]`) lives below and in the procedure summary above.

**Platform-specific enforcement prerequisite.** The branch-name regex makes the *decision* to auto-approve, but the *safety* of that decision rests on platform-side configuration that constrains what an agent can actually push to. The two platforms model this differently — and the asymmetry is load-bearing:

- **GitHub:** branch-protection rules (and rulesets) scope per-branch-pattern. The `kahuna/*` pattern is configured to permit the auto-merge path into `kahuna/*` while leaving `main`'s protection — required status checks, no force-push, no deletion — intact. Configured per-repo via `gh api` / repo settings; in Wave-Engineering repos this is part of the standard merge-config policy. See `docs/operations/branch-protection-checklist.md`.
- **GitLab:** approval rules use `protected_branch_ids` to scope per-protected-branch. The `kahuna/*` branches are first protected via `PUT /projects/:id/protected_branches`, then a `kahuna-zero-approvals` rule with `approvals_required: 0` is created and scoped via `protected_branch_ids: [<kahuna_pattern_id>]`. **`merge_request_approval_settings` MUST NOT be used** — that endpoint is project-wide and would unprotect main. The standard deployment is `gl-settings kahuna-sandbox <project-url>` (the composite operation from `gl-settings#27`); see `docs/kahuna-devspec.md` §5.3.1 and `docs/kahuna-settings-deployment.md`.

**If the platform-specific prerequisite is not in place, the auto-approval is unsafe.** An agent that sentinels-and-merges against a GitLab project missing the `protected_branch_ids`-scoped approval rule may bypass review controls the operator believed were in force. Detection guidance is below.

**Prerequisite detection (best-effort, non-blocking).** Before emitting the sentinel, the skill SHOULD verify the platform-side config exists. If detection is inconclusive, emit a warning rather than blocking — the wave Orchestrator and operator are the final safety net.

- **GitLab** (project platform == `gitlab`): query `glab api projects/:id/approval_rules` and look for a rule (conventionally named `kahuna-zero-approvals`) with `approvals_required: 0` AND a non-empty `protected_branches` array containing a `kahuna/*` pattern. If absent, emit `[WARNING: kahuna sandbox — GitLab approval rule not detected; verify gl-settings kahuna-sandbox has been applied to this project]` on the checklist before the sentinel. Do NOT block the auto-approval on detection failure (the query may fail for permission reasons unrelated to the actual config); the warning is the contract.
- **GitHub** (project platform == `github`): query `gh api repos/:owner/:repo/rulesets` (or `branches/kahuna/*/protection` as a fallback) and look for a rule scoped to the `kahuna/*` pattern. If absent, emit `[WARNING: kahuna sandbox — GitHub branch-protection ruleset for kahuna/* not detected; verify Wave-Engineering merge-config policy has been applied]`. Same non-blocking semantics as GitLab.
- **Detection unavailable** (platform CLI not installed, no network, API returns 403/404): emit `[SKIPPED — kahuna prerequisite detection unavailable]` and proceed. The wave Orchestrator's project-setup gate is the upstream check.

**Detection:**
```
current_branch = git rev-parse --abbrev-ref HEAD
base_branch    = parse base ref from most recent PR created by agent (or from context)

if base_branch matches regex "^kahuna/[0-9]+-":
    sandbox_context = true
else:
    sandbox_context = false
```

The detection regex is `^kahuna/[0-9]+-`. Resolve `base_branch` from the PR/MR that Step 0.5 found or opened (`gh pr view --json baseRefName`). Since #1235 one always exists by Step 5.

**Behavior matrix:**
- `sandbox_context == false` (default — feature branch targeting `main`): present checklist, notify, **STOP** and wait for BJ's merge call (`/mmr` / `/scpmmr` / affirmative); the PR/MR is already ready. This is the IT-09 negative case. The three exceptions are an approved autochain, a standing merge grant and a lead-agent grant. Step 5 checks each separately, and none changes this matrix entry.
- `sandbox_context == true` (PR/MR into a kahuna sandbox): full checklist runs, full notifications fire, then emit the sentinel line **`[AUTO-APPROVED: kahuna sandbox]`** on stdout, then invoke `/mmr` with no wait. The sentinel makes the auto-approval grep-able in transcripts and Discord scrollback.

**Non-bypassable items:** validation, code-reviewer (high+ findings still block), trivy scan, Discord `#precheck` post, `vox` announcement, **and `/mmr`'s CI gate**. These run in full regardless of `sandbox_context`. Only the human merge-call STOP is replaced by the sentinel + auto-`/mmr`.

The CI gate is listed explicitly because **the kahuna sandbox is not the only path that merges without a human.** Autonomous merging also occurs under **`/wavemachine` in `auto` mode** — its promote node performs the kahuna→protected merge with no human halt (interactive mode routes that same merge *to* a human, so the exposure is mode-specific, not skill-wide) — and under an **armed `godspeed` mandate**, whose gated-action list covers force-push, push-to-protected, terraform/kubectl/helm/docker/systemctl and prod-shaped writes but **not merges**, so an armed agent carries straight through one. **An approved `/autochain` run** is the third (#1224): its merges land on the *protected* branch directly, one per issue, with no human between them — which is why `/autochain plan` refuses a chain unless `wave_ci_trust_level` reports `pre_merge_authoritative`. **A standing merge grant** is the fourth (#1235): `/precheck` invokes `/mmr` itself for a PR inside the grant's scope. **A lead-agent grant** is the fifth: the named lead self-approves on any clean precheck. In all five, once the human approval is gone, the CI gate is the *last* thing between a red build and the protected branch.

*(`/lazyriver` is deliberately **not** in that list. It is a `probe → journal → judge → steer` goal-seek loop that terminates by emitting a plan or an answer — it has no merge path at all. It was named here in an earlier draft and the claim was wrong; naming a skill that cannot merge costs the paragraph its credibility with exactly the reader careful enough to check.)*

That gate was **inert on GitHub** until cc-workflow#925: it blocked only on `has_failures` and merged on any unrecognised summary, and `gh pr checks --json` does not exist on the fleet's `gh 2.45.0`, so the summary was always `none`. **Autonomous merge paths and a non-functioning CI gate were composing into an unguarded merge** — and the more autonomy a mode has, the more completely it was unguarded.

`/mmr` step 3 is now default-deny. Do not weaken it back to a blocklist without re-reading that issue, and treat any *new* autonomous merge path as inheriting this dependency: **removing the human raises the CI gate from a second opinion to the only opinion.**

## Rules
No pasted diff. No merge from this skill (that is `/mmr`, after the STOP or an exception). No skipping code-reviewer. No `precheck` status on a commit that was not the one reviewed. Honesty over speed — no checking items you haven't verified. **Linting is not testing** — passing lint/typecheck does not mean code works. **`vox` is ALWAYS called** — it is NOT a fallback for disc_send failure. Both notifications happen every time.

## New-Repo Onboarding (Branch-Protection End-to-End Dry-Run)

Out of scope for the per-MR gate, but called out here because this skill is the closest thing to an institutional checklist we have: **when configuring branch protection on a new repo, configuration verification is not enough — you MUST prove the gate end-to-end before any real work lands.** "Configuration exists" is not the same as "configuration works."

Two throwaway PRs, both required:

1. A PR with a **failing** check → assert it is **BLOCKED** from merging (the gate holds).
2. A PR that is **green** → assert it **merges through** (the gate passes good work).

A gate that blocks everything is as broken as one that blocks nothing; only the pair proves it. The full runbook lives in `docs/operations/branch-protection-checklist.md`. Same principle as the runtime smoke test in `mcp-server-sdlc` `validate.sh`: verify behavior, not declarations.
