# Cross-Repo Wave Orchestration Recipe

A **cross-repo wave** is one whose sub-issues live in a *different* repo than
the orchestrator's working directory (`CLAUDE_PROJECT_DIR`). Example: the wave
plan lives in `claudecode-workflow` (because the epic does) but every story
modifies code in `mcp-server-sdlc`. This is the standard shape for sdlc-mcp
migration epics.

The default `/nextwave` flow assumes same-repo execution. Cross-repo waves
require a handful of adjustments — none of them obvious the first time you
hit them. This file is the **canonical recipe**. Both `/prepwaves` and
`/nextwave` `cat` from here on demand.

## Plan-JSON schema additions

When `/prepwaves` detects sub-issue refs that don't match the orchestrator's
current repo, it sets two optional fields on each cross-repo phase in the
wave plan JSON:

```json
{
  "name": "Origin Operations (Phase 1)",
  "cross_repo": true,
  "target_repos": ["Wave-Engineering/mcp-server-sdlc"],
  "waves": [...]
}
```

- `cross_repo` (bool) — flag set when *any* sub-issue in the phase resolves
  to a repo different from the orchestrator's project repo.
- `target_repos` (string[]) — distinct list of `owner/repo` slugs across the
  phase's sub-issues. Usually one entry; multi-target is allowed.

Single-repo phases omit both fields. `wave-status init` round-trips them via
the existing whole-plan persistence path (the JSON is written verbatim as
`phases-waves.json` — extra keys are preserved without modification).

## Seven non-obvious facts

1. **`Agent` tool's `isolation: "worktree"` only works on the *current* repo.**
   It creates worktrees of `CLAUDE_PROJECT_DIR`, not an arbitrary target. You
   cannot use it to spawn parallel sub-agents in a different repo.
2. **A single git checkout can only have one branch active at a time.** N
   parallel sub-agents cannot each `git checkout` a different branch in the
   same clone — they would race the working-tree state. You need N
   independent working trees.
3. **`git worktree add` is the cheap solution.** It creates an additional
   working tree at a separate filesystem path with its own `HEAD`, sharing
   the underlying `.git` directory. No full-clone overhead. Each worktree
   can have a different branch checked out simultaneously.
4. **The orchestrator (parent agent) must pre-create the worktrees.**
   Sub-agents must not create their own — race conditions and naming
   conflicts. Pre-create all N up front, one per issue, before spawning any
   execution agents.
5. **Sub-agents are pointed at worktree paths via their prompt, not via
   `Agent` tool flags.** Each Flight prompt includes "Your working directory
   is `/tmp/wt-<slug>-<num>`. Use absolute paths or `cd` to that directory
   before any git/file operations." **No `isolation:` flag on the `Agent`
   call.**
6. **`gh`/`glab` commands must be repo-scoped via
   `-R Wave-Engineering/<target-repo>`.** Since the orchestrator is not
   running from the target repo's directory, every `gh issue view`,
   `gh pr create`, `gh pr merge`, etc. needs `-R`. Do not rely on cwd-based
   repo detection.
7. **`wave-status` state stays in the master plan repo** (where the epic
   lives), not the target repo. The wave-status CLI walks
   `.claude/status/phases-waves.json` from `CLAUDE_PROJECT_DIR`.
   Orchestrator and sub-agents have *different* working directories — that
   is correct and intentional.

## Recipe

### Pre-flight target-repo setup (orchestrator, before Step 1)

```bash
TARGET_REPO=/home/bakerb/sandbox/github/mcp-server-sdlc

# Verify target repo is clean and on main (or kahuna_branch if KAHUNA wave)
git -C "$TARGET_REPO" status --short
git -C "$TARGET_REPO" checkout main
git -C "$TARGET_REPO" pull
```

### Worktree creation loop (one per issue)

```bash
for issue in 76 77 78 79 80 81 82 83 84 85 86 87 88 89; do
  slug="$(gh issue view "$issue" -R Wave-Engineering/mcp-server-sdlc --json title --jq '.title' \
          | sed 's/.*: //; s/[^a-zA-Z0-9]/-/g; s/--*/-/g; s/^-//; s/-$//' \
          | tr '[:upper:]' '[:lower:]' | cut -c1-40)"
  branch="feature/${issue}-${slug}"
  worktree="/tmp/wt-sdlc-${issue}"
  git -C "$TARGET_REPO" worktree add "$worktree" -b "$branch" origin/main
  # Worktrees lack node_modules — install dependencies if the project needs them
  ( cd "$worktree" && bun install ) || true
done
```

For KAHUNA waves, replace `origin/main` with `origin/<kahuna_branch>`.

### Sub-agent prompt template snippet

In the per-issue Flight prompt, drop in (replacing `<num>` and `<slug>`):

```
Your working directory is /tmp/wt-sdlc-<num> (use absolute paths or cd into it before any git/file operations).
Your branch is feature/<num>-<slug> (already checked out in the worktree).

For any GitHub interactions, repo-scope every command:
  gh issue view <num> -R Wave-Engineering/mcp-server-sdlc
  gh pr create   -R Wave-Engineering/mcp-server-sdlc ...
  gh pr merge    -R Wave-Engineering/mcp-server-sdlc ...

Run validation in the worktree:
  cd /tmp/wt-sdlc-<num> && ./scripts/ci/validate.sh
```

**Do NOT pass `isolation: "worktree"` on the `Agent` call.** The pre-created
worktree IS the isolation.

### Per-agent commit / push / PR / merge (Prime(post-flight) or orchestrator)

```bash
git -C /tmp/wt-sdlc-<num> add <files>
git -C /tmp/wt-sdlc-<num> commit -m "type(scope): description

Closes #<num>"
git -C /tmp/wt-sdlc-<num> push -u origin feature/<num>-<slug>

gh pr create -R Wave-Engineering/mcp-server-sdlc \
  --base main --head feature/<num>-<slug> \
  --title "..." --body "..."

gh pr merge <pr-num> -R Wave-Engineering/mcp-server-sdlc \
  --squash --auto --delete-branch
```

For KAHUNA waves, swap `--base main` for `--base <kahuna_branch>` — every
Flight PR targets the kahuna branch, never `main` (Dev Spec §5.2.2).

### Post-wave worktree cleanup

```bash
for wt in /tmp/wt-sdlc-*; do
  git -C "$TARGET_REPO" worktree remove "$wt" --force
done
```

Run this after `wave_complete()` lands and the bus has been cleaned.

## What can go wrong

- **Forgetting `-R` on `gh`/`glab` commands** — they fail with "no PRs
  found" or operate on the wrong repo silently. Every cross-repo `gh`
  invocation needs `-R Wave-Engineering/<target-repo>`.
- **Not pre-creating worktrees** — sub-agents racing each other to
  `git checkout` will leave the target repo in a broken state (detached
  HEAD, half-applied stashes). Pre-create all N before spawning Flights.
- **Accidentally using `isolation: "worktree"` on the `Agent` call** — you
  get a worktree of the *orchestrator's* repo (e.g. `claudecode-workflow`),
  not the target repo. The Flight ends up in the wrong codebase entirely
  and every file path it writes is wrong.
- **Confusing orchestrator cwd with sub-agent cwd** — the orchestrator
  stays in the master plan repo so `wave_show`, `wave_complete`, and
  `wave-status` resolve against the right `.claude/status/`. Sub-agents
  work in their assigned target-repo worktrees. Both are correct; mixing
  them up corrupts wave state.
