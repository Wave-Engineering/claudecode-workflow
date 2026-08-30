---
name: precheck
description: Pre-commit gate — verify branch/issue, run code-reviewer, present checklist, then stop and wait for approval
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-precheck does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-precheck
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Pre-Commit Gate

Mandatory verification before any commit. Checks compliance, runs code review, presents the checklist, and **stops**. Does NOT commit/push/PR.

**IMPORTANT: When implementation is done, run this skill IMMEDIATELY. Do NOT ask "shall I run precheck?" or "ready for precheck?" — just start it. The checklist at the end is the approval gate; asking permission to START is a redundant pause.**

## Tools Used
- `mcp__sdlc-server__ibm` — branch/issue workflow (no protected branch; branch linked to an open issue)
- `mcp__sdlc-server__branch_guard` — resolve the live default branch and verify the current branch's base is it (protected-gated, `kahuna/*`-exempt)
- `mcp__sdlc-server__spec_validate_structure` — linked issue has Changes / Tests / AC
- `mcp__disc-server__disc_send` — post approval request to `#precheck` (channel `1491195025198157834`)

## Procedure

### Step 1 — IBM gate (serial, hard stop)
Call `mcp__sdlc-server__ibm` directly (no sub-agent — it's one MCP call). If it fails, stop immediately and do not proceed.

### Step 1.5 — Base-branch gate (serial, hard stop)
Call `mcp__sdlc-server__branch_guard({ role: "base" })`. It resolves the **live** default branch from the git host (never a cached `.claude-project.md` value or `origin/HEAD` — both go stale silently) and checks the branch your work is based on. Interpret the envelope:
- `verdict == "pass"` → continue.
- `verdict == "warn"` → **STOP** and surface `reason` verbatim. Your branch's base is a **protected** branch that is neither the live default nor a `kahuna/*` sandbox — almost always a stale or renamed base (the exact failure this gate exists to catch). Rebase onto the live default, or confirm the base is intentional, before proceeding.
- `{ ok: false }` or any error envelope → **STOP** and surface the error; do not silently continue past a gate that failed to run.

**Protected-gated:** silent when the base is unprotected (feature→feature, stacked branches) or a `kahuna/*` integration branch. Only a protected, non-default, non-sandbox base trips it.

**Scope (known limit):** reliable once a PR exists (it reads the PR's base). Before a PR exists, git can't distinguish "based on a stale default" from "based on the current default, now a bit behind" without false positives, so the pre-PR case is intentionally not gated here — the PR-create and merge target guards catch the wrong-target case. (#888)

**Transition fallback** — *only* until `branch_guard` is deployed on this host's sdlc-server (#465): resolve the live default inline (`gh repo view --json defaultBranchRef -q .defaultBranchRef.name`, or GitLab `glab api "projects/:id" --jq .default_branch`). If an open PR exists, compare its base (`gh pr view --json baseRefName -q .baseRefName`) and STOP if that base is a protected branch that is neither the live default nor matches `^kahuna/[0-9]+-`. Delete this paragraph once `branch_guard` is universal.

### Step 2 — Parallel verification batch
After `ibm()` passes: first run `bash <repo_root>/scripts/ci/precheck-review-scope.sh reset <repo_root> <marker_dir>` (this is what makes pass 1 of the cycle mechanically full), then `… resolve …` to learn which Job D prompt to compose, then launch all four jobs **in a single message** as parallel Agent calls. Do NOT wait for one before starting the next — they have no data dependencies on each other. See the Job D section below for both prompts and the full rule.

**Job A — Spec validation** `model: haiku`
```
subagent_type: general-purpose
model: haiku
prompt: "Run mcp__sdlc-server__spec_validate_structure for issue #<N> in repo <repo>.
         Return: PASS or FAIL, and if FAIL, list exactly which required H2 sections are missing."
```

**Job B — Repo validation** `model: haiku`
```
subagent_type: general-purpose
model: haiku
prompt: "Run the project's validation and test tooling in <repo_root>.
         First: read .claude-project.md if it exists — use whatever toolchain commands it declares.
         If absent, probe in order: ./scripts/ci/validate.sh, ./scripts/ci/test.sh,
         make test, python3 -m pytest tests/, npm test.
         Run whatever exists. Return: PASS or FAIL, and any error output verbatim (truncated to 50 lines max)."
```

**Job C — Dependency vulnerability scan** `model: haiku`
```
subagent_type: general-purpose
model: haiku
prompt: "Run: bash <repo_root>/scripts/ci/dependency-scan.sh <repo_root>
         Also run: git -C <repo_root> rev-parse HEAD

         Report the script's output VERBATIM, then its exit code, then the commit.
         Do not summarise, do not re-derive the counts, do not substitute your own
         judgement for the exit code.

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

         If the output carries a `coverage:` line showing fewer ingested than
         scannable, report that shortfall explicitly — a PASS covering 1 of 2
         manifests is a pass over half a denominator.

         If the script is MISSING (older checkout), say so and fall back to
         `trivy fs --scanners vuln --severity HIGH,CRITICAL --include-dev-deps
         --list-all-pkgs --format json --quiet`, reporting the manifest count
         first. Do not report a verdict without a denominator. Both flags are
         REQUIRED on the fallback, not optional (cc-workflow#1169): trivy
         suppresses dev/test dependencies by default (a project whose entire
         dependency tree is dev-only scans ZERO packages without
         --include-dev-deps, while still exiting clean), and --list-all-pkgs
         only became trivy's default in v0.67.0, with this fleet pinning no
         minimum trivy version. dependency-scan.sh itself already carries both
         flags — this fallback exists only for a checkout that predates the
         script."
```

**The denominator is emitted by the tool, not requested from the agent (#1137).** This job used to be prose asking a sub-agent to report the count. It complied — and compliance is the problem: an instruction can be forgotten by the next agent, misread, or quietly dropped in a rewrite, and the resulting verdict looks identical to a real one. `dependency-scan.sh` emits the number on every path including the passing one, so the report survives the agent.

**Reach, stated honestly: cc-workflow only, for now.** `install` excludes `ci/*`
from distribution (four sites), so `dependency-scan.sh` exists in a cc-workflow
checkout and nowhere else. In every other repo this job takes the fallback above —
raw `trivy` with an agent asked to report the count, i.e. exactly the prose path
this replaces. The structural guarantee is real where the script is; the fallback
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

> **Resolve the merge-base to a SHA, then diff against the WORKING TREE: `mb="$(git -C <repo_root> merge-base <base> HEAD)"` then `git -C <repo_root> diff "$mb"`.**
>
> Not `git diff <base>...HEAD`, and not `git diff <base>`. Both are wrong, in opposite directions, and the first one is catastrophic:
> - **`<base>...HEAD`** is a *commit-to-commit* range (`git diff $(merge-base A B) B`), so the working tree and index are excluded **by construction**. In a pre-commit gate the changeset IS the working tree and HEAD has not moved — so this diff is **empty**. Measured on this very branch during #1194: `git diff main...HEAD` returned **0 bytes** while `git diff $(merge-base)` returned **61,193**. Embedding the three-dot form hands the reviewer nothing and gets back "No findings".
> - **bare `git diff <base>`** compares base's *current tip* to the working tree, so if someone pulls `<base>` mid-cycle its new commits appear inverted as phantom deletions.
>
> Resolving the merge-base first gets both properties: merge-base semantics (no phantom deletions) *and* the working tree (the code actually under review).
>
> **`<base>` is the branch this work will merge into — never a hardcoded `main` (#1194).** Resolve it, do not assume it: if a PR/MR exists, it is that PR's base (`gh pr view --json baseRefName -q .baseRefName`); otherwise it is the live default branch that Step 1.5's `branch_guard` already returned as `default_branch`. On a `kahuna/*` sandbox flight the base is the wave integration branch, and on repos whose default is `release/*` it is that release branch. A literal `main` reviews the wrong range in both cases — and on the sandbox path there is no human present to notice the reviewer read a nonsensical diff.

**The first Job D pass of a precheck cycle ALWAYS uses the full prompt.** There is no condition, issue type, label, or file extension that scopes it. The delta prompt exists only to avoid re-reading code a reviewer has *already cleared in this same cycle*; it is not a cheaper first look.

**Both prompts carry the untracked channel, and the full one needs it just as much.** `git diff <base>` does not show untracked paths, and `/precheck` runs before `/scp` does the `git add` — so a brand-new file can be untracked for the whole cycle. Without the second channel the full pass never sees it, yet `record` afterwards writes that file into the reviewed set, so the *next* pass correctly omits it as already-cleared. The file would then ship reviewed by nobody: bookkeeping asserting a coverage claim the prompt never made. Do not drop the untracked block from either prompt on the grounds that a reviewer "would probably run `git status`" — spelling it out in one prompt is already the admission that you cannot rely on that.

**Job D-full** — used when `resolve` (below) printed `full`: the first pass of every cycle, and any pass where the recorded state could not be trusted.

> **The parent gathers the content and embeds it. The reviewer is never handed a command to run.** `feature-dev:code-reviewer` has no `Bash` tool — its tool list is `Glob, Grep, LS, Read, NotebookRead, WebFetch, TodoWrite, WebSearch, KillShell, BashOutput`. Every `<output of: …>` below is substituted by YOU before dispatch. This is not a style preference: the delta prompt's ref is a dangling `git stash create` SHA that no `Read` or `Grep` can reach, so a reviewer told to fetch it would review nothing and report success. (The plugin's own agent definition says "review unstaged changes from `git diff`" — an instruction it cannot follow. `skills/review/SKILL.md` already embeds instead of instructing; match it.)

```
subagent_type: feature-dev:code-reviewer
model: opus
prompt: "Review this changeset in <repo_root>.

         ### Diff — <N> lines total, read ALL of these files before reviewing
         <the paths printed by: precheck-review-scope.sh gather <repo_root> <marker_dir> <base>>

         ### Untracked files — NOT in the diff above, read each IN FULL
         <output of: bash <repo_root>/scripts/ci/precheck-review-scope.sh new-untracked <repo_root> <marker_dir>
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
bash <repo_root>/scripts/ci/precheck-review-scope.sh gather <repo_root> <marker_dir> <base-or-ref>
```

Fourth argument is `<base>` for a full pass, or the `<ref>` from `resolve` for a delta. It prints one of:

| output | meaning | what to do |
|---|---|---|
| `files <N> <path>…` | diff on disk, `<N>` lines total | put **every** path AND the line count in the prompt |
| `empty 0 <path>` | genuinely 0 bytes | legitimate ONLY for an untracked-only changeset — say so **explicitly**; never leave a bare empty heading |
| exit 2 + stderr | target unresolvable, or `git diff` failed | **STOP, do not dispatch.** Fix `<base>` (`origin/<base>`, `git fetch`) — an empty or error-filled `### Diff` reads as "nothing changed" |

**It hands over paths, never pasted content.** The reviewer has `Read`; a path costs a few tokens where an 80 KB body costs twenty thousand, and a paste cannot survive the transport cap anyway. Files split at 1500 lines — under `Read`'s 2000-per-call limit — and you MUST state the total, so the reviewer can verify its own coverage. N paths plus a total tells it when it is done; a single path does not.

**Both prompts, same rules.** The delta channel empties identically, plus one of its own: `resolve` prints two tokens (`delta <ref>`), so parse them — `ref="$(… resolve … | awk '{print $2}')"`. Passing the whole line yields `git diff "delta abc123"`, exit 128, empty stdout.

> **If `scripts/ci/precheck-review-scope.sh` is MISSING, you are not in a cc-workflow checkout.** `install` excludes `ci/*` from distribution (four sites), exactly as documented for Job C above — so this script exists in cc-workflow and nowhere else until #1141 ships `ci/*` with the kit. The skill itself is installed fleet-wide **today**, so this is the common case, not the edge case.
>
> When it is absent: treat scope as **`full`**, and gather the untracked list inline instead —
> ```bash
> git -C <repo_root> ls-files --others --exclude-standard
> ```
> — then note `[delta scoping unavailable — precheck-review-scope.sh not distributed to this repo (#1141)]` on the checklist. **Do not silently substitute an empty section.** A failed invocation produces empty stdout, and an empty "### Untracked files" heading reads as the affirmative "there are none" — the identical fail-open the script closes internally, reintroduced at the invocation boundary.

**Scope is decided by `scripts/ci/precheck-review-scope.sh`, not by you.** The rule is small enough to look obvious and was wrong in a way that reviewed *nothing* while reporting success (see the script's header for the full post-mortem), so it lives in one tested implementation that both this skill and its regression test invoke. Do not re-derive it inline. `<marker_dir>` is this session's scratchpad directory — pass the literal absolute path; it must be outside `<repo_root>` so the marker can never be staged.

**At the start of every precheck cycle, before the parallel batch in Step 2 launches:**
```bash
bash <repo_root>/scripts/ci/precheck-review-scope.sh reset <repo_root> <marker_dir>
```
This is what makes "pass 1 is always full" mechanical rather than conventional. The marker is session-scoped and would otherwise survive into the *next* cycle, where it would scope that cycle's first pass to a stale range — the new work would be invisible. One line removes the possibility.

**Before each Job D pass, ask the script which prompt to use:**
```bash
bash <repo_root>/scripts/ci/precheck-review-scope.sh resolve <repo_root> <marker_dir>
# -> "full"          : use Job D-full
# -> "delta <ref>"   : use Job D-delta, reviewing `git diff <ref>`
```
It prints exactly one verdict and every unresolvable condition prints `full`. There is no path that yields "review nothing".

**Order matters: run `resolve` BEFORE `new-untracked`.** A `full` verdict clears the markers, which is what makes `new-untracked` re-widen to the whole untracked set. Calling `new-untracked` first on a mid-cycle fall-back to `full` returns a still-delta-scoped list and reproduces the mixed-scope defect exactly.

**Record IMMEDIATELY when a Job D pass returns — before you edit a single file** — and only if it actually returned a review:
```bash
bash <repo_root>/scripts/ci/precheck-review-scope.sh record <repo_root> <marker_dir>
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
         <output of: bash <repo_root>/scripts/ci/precheck-review-scope.sh new-untracked <repo_root> <marker_dir>
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

**Why the delta is safe, stated plainly:** `<ref>` is a snapshot of the working tree *as the last reviewer saw it*, so `git diff <ref>` covers everything that changed since — the fixes, any other edits made in between, and any new commits. Nothing on the branch escapes review; the full diff is still reviewed, exactly once, on pass 1. What the delta drops is re-reading already-cleared code. Untracked files are handed over separately because a working-tree snapshot cannot contain them. Jobs A, B, and C stay unscoped and run in full on every pass, so the entire test suite remains the backstop for cross-file breakage the reviewer's dependent-tracing might miss.

**The trap this replaced, so nobody reintroduces it:** the obvious version of this feature records `rev-parse HEAD` and re-reviews `<prev>..HEAD`. Because `/precheck` runs *before* the commit, HEAD does not move between passes — so `prev == HEAD`, `merge-base --is-ancestor` returns 0 (ancestry is reflexive, so no guard fires), the diff is **empty**, and pass 2 reviews nothing while reporting success. That was the first implementation of #1194 and code review caught it. A two-dot commit range cannot contain uncommitted work; do not "simplify" the snapshot back into one.

**Why this optimisation and not a conditional gate.** The expensive thing about precheck is review wall-clock (~8 min/pass; three passes approaches 30 min, which is why a one-line fix can cost 15+ minutes and why agents drift toward filing follow-up issues instead of fixing inline). The tempting "fix" is to skip review for doc-only or chore-labelled work. **Do not.** #1191 was labelled `chore`, its own acceptance criteria said "no direct pytest coverage — it's a prose skill file," and its diff contained a real Bash defect: a rename guard that reported success while doing nothing. Issue type is self-reported *intent* and says nothing about what the diff contains. Scoping a re-read is safe because the skipped code was genuinely reviewed; skipping a gate on a label is not.

### Step 3 — Fix high+ findings (serial)
Wait for all four jobs to return. **The moment Job D returns, run `record` — before touching any file** (or `reset`, if it errored/timed out rather than returning a verdict). Then, if Job D returned critical or important findings, fix them. Re-run Job D after **any** fix — not only "non-trivial" ones. That escape hatch existed because a re-run cost a full ~8-minute re-read; the delta removes the cost, so the judgment call is no longer worth its risk (#1191 is the standing example of a "trivial" change carrying a real defect). Ask `bash <repo_root>/scripts/ci/precheck-review-scope.sh resolve <repo_root> <marker_dir>` which prompt to use; do not decide by eye. Both arguments are required — the script exits 2 with usage if either is missing. Carry the prior pass's findings into the re-run prompt verbatim so it can verify each one rather than rediscover it. Haiku job failures (B or C) block the checklist item but do not block the gate unless validation itself fails.

### Step 4 — Assemble checklist and notify
Collect results from all four jobs, assemble the checklist (see below), then **notify BJ**: `disc_send` to `#precheck`, **then `vox`** — **ALWAYS do both**. If `disc_send` fails (MCP unavailable, network), still do `vox`.

### Step 5 — Sandbox detection + gate
Run **sandbox-context detection** (see "Sandbox Auto-Approval" below): if the current branch's base ref matches `^kahuna/[0-9]+-`, emit the sentinel line `[AUTO-APPROVED: kahuna sandbox]` and invoke `/scpmmr` immediately with no wait; otherwise **STOP.** Wait for `/scp`/`/scpmr`/`/scpmmr`/affirmative. Negative/rework → return to work. Never bypass the STOP on notification failure in non-sandbox contexts.

## Dependency Vulnerability Scan
Delegated to Job C (Haiku sub-agent) in the parallel batch. Interpret the result as:
- **PASS** → checklist item passes.
- **SKIP** → emit `[SKIPPED — trivy not installed]` on the checklist. Do not fail the gate.
- **FINDINGS** (`dependency-scan.sh` exit 1) → report each finding (package, CVE, severity, fixed version if any) as a deferred checklist item. Do NOT auto-upgrade dependencies — the user approves the codebase state at the gate. **The checklist item FAILS on any HIGH/CRITICAL finding, with or without a fix available** — `dependency-scan.sh` does not distinguish them (no `--ignore-unfixed` support; `.trivyignore` is explicitly disabled via `--ignorefile /dev/null`, not merely undocumented), which is stricter than this skill's own prose promised before this scan was a real tool rather than an agent's judgment call. Tracked for a policy decision: #1188. **Escape hatch that exists today, undocumented until now:** `DEP_SCAN_SEVERITY` (env var, default `HIGH,CRITICAL`) overrides the severity filter — e.g. `DEP_SCAN_SEVERITY=CRITICAL ./scripts/ci/validate.sh` to stop blocking on HIGH while #1188 is unresolved. This is a manual, visible override for an operator to reach for, not something Job C or this skill invokes on its own.
- **SCANNER/TOOLING ERROR** (`dependency-scan.sh` exit 5 — timeout, no scanner output, unparseable scanner output, OR a partial install missing `check-scannable.sh`) → the checklist item FAILS. This is not a skip: the scan did not run to completion, which is not evidence of a clean dependency tree. Ordinary triggers (first DB pull, rate-limited/air-gapped network) are not a reason to wave it through.

## The Checklist (full every time; a checkmark means VERIFIED by reading the codebase)
**Context:** Project | Issue #N — title | Branch `feature/N-...` → `<live default>`
- [ ] Implementation (AC verified) — [ ] TODOs (searched+addressed) — [ ] Docs (reviewed+updated) — [ ] Validation (actually ran)
- [ ] New tests (cover new code) — [ ] All tests pass (entire suite) — [ ] Scripts executed (linting is NOT testing) — [ ] Code review (high+ fixed)
- [ ] Dependencies (trivy: 0 HIGH/CRITICAL, or exceptions documented, or [SKIPPED])

**Summary:** `[codebase]` `[docs]` `[tests]` `[config]`. **Findings:** `[fixed]` / `[deferred]` / "(none)".

## The Notification (Discord + vox)
Resolve identity from `<project_root>/.claude/agent-identity.json`; fall back to `/tmp/claude-agent-<md5>.json` if absent (transition window). Use it for both the Discord post and the vox announcement.

**Important:** Do NOT prefix the Discord post with `@all`, `@<Dev-Team>`, or any `@`-mention. This post is for BJ only (human-facing). The discord-watcher filters by `@`-addressing, so an `@`-prefix would fan the precheck gate notice out to every listening agent in the fleet. Unaddressed is intentional.

**`disc_send` to `#precheck` (`1491195025198157834`) — exact body shape:**
```
⚠️ **Precheck gate — awaiting approval**

**Project:** <project-name>
**Issue:** #<N> — <title>
**Branch:** `<type>/<N>-<slug>` → `<live default>`
**Checklist:** `[codebase]` `[docs]` `[tests]` `[config]`
**Findings:** <fixed> / <deferred> / (none)

Ready for `/scp` / `/scpmr` / `/scpmmr` or rework.

— **<dev-name>** <dev-avatar> (<dev-team>)
```

**`vox`:** same info, conversational, 1-2 sentences, ending with "Ready for your call."

**FRONT-LOAD the speaker identity — open with `"<Dev-Name> here."`** (#952). Synthesis runs at ~1x realtime, so a long body can exhaust a caller's `timeout` budget *during synthesis*, and whatever is still playing gets cut — the tail first. `vox` appends its own `. This is <name>.` sign-off, but the sign-off is the tail, so it is exactly what a truncation drops. Leading with the name means the identity is spoken first and survives a cut. Example — **pipe it, never inline** (#942):

```bash
vox <<'EOF'
<Dev-Name> here. Precheck gate ready on #<N>. <one sentence>. Ready for your call.
EOF
```

Do NOT open with "Precheck gate ready on #<N>…" and rely on the appended sign-off to identify you; that identity is the first thing lost.

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

Flight Agents working inside a KAHUNA sandbox push to a per-wave integration branch (`kahuna/<N>-<slug>`), not to `main`. In that context the human gate is a redundant pause — the wave Orchestrator has already decided the wave runs autonomously and reviews aggregated results at the wave gate, not per-flight. The full checklist (validation, code-reviewer, trivy) and Discord/`vox` notifications still run; only the STOP-and-wait step is bypassed.

**Why this exists (narrative).** A wave can dispatch dozens of Flight Agents in parallel; a per-flight human STOP would serialise the wave back to one-at-a-time and defeat the orchestration. The Orchestrator's contract with the human is "I will surface the *wave* result, not every flight." Flight Agents inside the sandbox honour that contract by completing their own quality bar (the full checklist) and then auto-progressing; they never bypass quality, only the human pause. Outside the sandbox — i.e. an agent operating directly against `main` — the original rule applies in full and the STOP is non-negotiable. See Dev Spec §5.2.1 for the authoritative statement; the mechanical detection (regex `^kahuna/[0-9]+-`, sentinel `[AUTO-APPROVED: kahuna sandbox]`) lives below and in the procedure summary above.

**Platform-specific enforcement prerequisite.** The branch-name regex makes the *decision* to auto-approve, but the *safety* of that decision rests on platform-side configuration that constrains what a Flight Agent can actually push to. The two platforms model this differently — and the asymmetry is load-bearing:

- **GitHub:** branch-protection rules (and rulesets) scope per-branch-pattern. The `kahuna/*` pattern is configured to permit the Flight Agent's auto-merge path while leaving `main`'s protection — required status checks, no force-push, no deletion — intact. Configured per-repo via `gh api` / repo settings; in Wave-Engineering repos this is part of the standard merge-config policy. See `docs/operations/branch-protection-checklist.md`.
- **GitLab:** approval rules use `protected_branch_ids` to scope per-protected-branch. The `kahuna/*` branches are first protected via `PUT /projects/:id/protected_branches`, then a `kahuna-zero-approvals` rule with `approvals_required: 0` is created and scoped via `protected_branch_ids: [<kahuna_pattern_id>]`. **`merge_request_approval_settings` MUST NOT be used** — that endpoint is project-wide and would unprotect main. The standard deployment is `gl-settings kahuna-sandbox <project-url>` (the composite operation from `gl-settings#27`); see `docs/kahuna-devspec.md` §5.3.1 and `docs/kahuna-settings-deployment.md`.

**If the platform-specific prerequisite is not in place, the auto-approval is unsafe.** A Flight Agent that sentinels-and-merges against a GitLab project missing the `protected_branch_ids`-scoped approval rule may bypass review controls the operator believed were in force. Detection guidance is below.

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

The detection regex is `^kahuna/[0-9]+-`. Resolve `base_branch` from the most recent PR opened by this agent against the current branch (`gh pr view --json baseRefName`), or from the spawning Orchestrator's context when no PR exists yet.

**Behavior matrix:**
- `sandbox_context == false` (default — feature branch targeting `main`): existing behavior preserved — present checklist, notify, **STOP** and wait for `/scp` / `/scpmr` / `/scpmmr` / affirmative. This is the IT-09 negative case.
- `sandbox_context == true` (Flight Agent on a kahuna sandbox): full checklist runs, full notifications fire, then emit the sentinel line **`[AUTO-APPROVED: kahuna sandbox]`** on stdout, then invoke `/scpmmr` with no wait. The sentinel makes the auto-approval grep-able in transcripts and Discord scrollback.

**Non-bypassable items:** validation, code-reviewer (high+ findings still block), trivy scan, Discord `#precheck` post, `vox` announcement, **and `/mmr`'s CI gate**. These run in full regardless of `sandbox_context`. Only the human-approval STOP is replaced by the sentinel + auto-`/scpmmr`.

The CI gate is listed explicitly because **the kahuna sandbox is not the only path that merges without a human.** Autonomous merging also occurs under **`/wavemachine` in `auto` mode** — its promote node performs the kahuna→protected merge with no human halt (interactive mode routes that same merge *to* a human, so the exposure is mode-specific, not skill-wide) — and under an **armed `godspeed` mandate**, whose gated-action list covers force-push, push-to-protected, terraform/kubectl/helm/docker/systemctl and prod-shaped writes but **not merges**, so an armed agent carries straight through one. In both, once the human approval is gone, the CI gate is the *last* thing between a red build and the protected branch.

*(`/lazyriver` is deliberately **not** in that list. It is a `probe → journal → judge → steer` goal-seek loop that terminates by emitting a plan or an answer — it has no merge path at all. It was named here in an earlier draft and the claim was wrong; naming a skill that cannot merge costs the paragraph its credibility with exactly the reader careful enough to check.)*

That gate was **inert on GitHub** until cc-workflow#925: it blocked only on `has_failures` and merged on any unrecognised summary, and `gh pr checks --json` does not exist on the fleet's `gh 2.45.0`, so the summary was always `none`. **Autonomous merge paths and a non-functioning CI gate were composing into an unguarded merge** — and the more autonomy a mode has, the more completely it was unguarded.

`/mmr` step 3 is now default-deny. Do not weaken it back to a blocklist without re-reading that issue, and treat any *new* autonomous merge path as inheriting this dependency: **removing the human raises the CI gate from a second opinion to the only opinion.**

## Rules
No diff. No commit. No skipping code-reviewer. Honesty over speed — no checking items you haven't verified. **Linting is not testing** — passing lint/typecheck does not mean code works. **`vox` is ALWAYS called** — it is NOT a fallback for disc_send failure. Both notifications happen every time.

## New-Repo Onboarding (Branch-Protection End-to-End Dry-Run)

Out of scope for the per-commit gate, but called out here because this skill is the closest thing to an institutional checklist we have: **when configuring branch protection on a new repo, configuration verification is not enough — you MUST prove the gate end-to-end before any real work lands.** "Configuration exists" is not the same as "configuration works."

Two throwaway PRs, both required:

1. A PR with a **failing** check → assert it is **BLOCKED** from merging (the gate holds).
2. A PR that is **green** → assert it **merges through** (the gate passes good work).

A gate that blocks everything is as broken as one that blocks nothing; only the pair proves it. The full runbook lives in `docs/operations/branch-protection-checklist.md`. Same principle as the runtime smoke test in `mcp-server-sdlc` `validate.sh`: verify behavior, not declarations.
