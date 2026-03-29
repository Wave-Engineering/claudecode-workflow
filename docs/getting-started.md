# Getting Started with Claude Code Workflow

This guide walks you through your first 15 minutes with the ccwork kit -- from verifying your install to making your first change through the full workflow. By the end, you will have completed a real issue-to-merge cycle and understand how the system works day to day.

**Prerequisites:** You have already cloned the repo and run `./install.sh`. If not, see the [Quick Start](../README.md#quick-start) in the README.

---

## Step 1: Verify Your Install

Run the drift checker to confirm everything landed correctly:

```bash
cd claudecode-workflow
./install.sh --check
```

You will see output like this for each component:

```
Skills:
  engage          ... in sync
  precheck        ... in sync
  scp             ... in sync
  ...

Scripts:
  discord-bot     ... in sync
  slackbot-send   ... in sync
  ...
```

What to look for:

- **in sync** -- the installed version matches the repo. You are good.
- **DIFFERS** -- your local install has diverged from the repo version. Run `./install.sh` again to update, or `./sync.sh` if you want to pull local edits back into the repo.
- **NOT INSTALLED** -- this component was not installed. Run `./install.sh` (or `./install.sh --skills`, `./install.sh --scripts` for targeted installs).

If everything shows "in sync", move on.

---

## Step 2: Start Your First Session

Open a terminal in any project that has a `CLAUDE.md` file (or copy the template into one):

```bash
cd /path/to/your-project
cp /path/to/claudecode-workflow/CLAUDE.md ./CLAUDE.md
claude
```

Three things happen automatically on your first session in a new project:

### Platform Detection

Claude reads `git remote -v` and determines whether you are on GitHub or GitLab. This controls which CLI tool is used (`gh` vs `glab`), which terminology appears (Pull Request vs Merge Request), and how issues and reviews are managed. You do not configure this -- it is automatic.

### Dev-Team Assignment

Claude looks for the `Dev-Team:` field at the bottom of `CLAUDE.md`. On a brand new project this field is empty, so Claude asks you:

> "What Dev-Team name should I use for this project?"

You provide a short name (e.g., `backend-team`, `cc-workflow`). Claude writes it into `CLAUDE.md` and never asks again for this project.

### Session Identity

Each time you start a new Claude Code session, the agent picks a fresh Dev-Name and Dev-Avatar for itself. You will see something like:

> I'm going by **beacon** :satellite: from team `cc-workflow` this session.

This identity is ephemeral -- a new terminal window means a new name. It exists so that when multiple agents are active (on Discord or Slack), you can tell them apart. The identity is written to a temp file at `/tmp/claude-agent-<hash>.json` where `<hash>` is derived from your project root.

See [Identity System](concepts.md#identity-system) in the concepts doc for the full explanation of why this two-layer system exists.

---

## Step 3: Run `/engage`

Once you are in a session, run:

```
/engage
```

This is the "rules of engagement" skill. It does three things:

1. **Reads CLAUDE.md** and confirms the mandatory rules are loaded -- things like "never commit without `/precheck`", "always have an issue before starting work", and "test before push".
2. **Loads the current plan** if one exists (from a prior `/cryo` freeze or plan mode). If no plan exists, it says so.
3. **Reports ready state** -- your current git branch, any pending work, and asks what you would like to work on.

You should run `/engage` at the start of every session, and especially after context compaction (when Claude's context window fills up and gets summarized). `/engage` is the thaw cycle that restores context after compaction.

**Want a guided tour instead?** Run `/ccwork tour` for an interactive walkthrough of the kit -- it shows you what is installed, how the pieces connect, and runs live commands against your actual setup. You can also run `/ccwork tour workflow` or `/ccwork tour foundations` for focused deep-dives.

---

## Step 4: The Mandatory Workflow

Every change follows the same loop: **issue, branch, code, precheck, ship**. The system enforces this -- if you try to skip steps, Claude will stop you.

### 4a: Start with an Issue

Before writing any code, you need a tracked issue. Either find an existing one or create one:

```
> Let's work on issue #42
```

or

```
> Create an issue for adding retry logic to the upload endpoint
```

Claude uses `gh issue create` or `glab issue create` depending on your platform. The issue must exist before any code is written -- this is a hard rule.

### 4b: Create a Branch

Claude creates a feature branch linked to the issue:

```bash
git checkout -b feature/42-add-retry-logic
```

The branch name includes the issue number so the system can trace work back to its origin. The naming convention is `<type>/<issue-number>-<description>` where type is one of `feature`, `fix`, `chore`, or `docs`.

### 4c: Write Code

This is the part where actual work happens. Claude implements the changes described in the issue. If you are driving, you write the code and Claude assists. If Claude is driving, it implements to the issue spec.

### 4d: Run `/precheck`

When the work is done, run (or Claude proactively runs):

```
/precheck
```

This is the pre-commit gate. It runs through a multi-step verification:

1. **Branch and issue check** -- confirms you are on a feature branch linked to an open issue.
2. **Validation** -- runs `./scripts/ci/validate.sh` or whatever test tooling the project has.
3. **Code review** -- launches a code-reviewer sub-agent that reviews all changed files and flags issues by severity.
4. **Fix high-risk findings** -- anything rated high risk or above gets fixed before the checklist is presented.
5. **Present the checklist** -- a full verification checklist covering implementation completeness, TODOs, docs, tests, and review results.

After the checklist is presented, Claude **stops and waits**. It will not commit until you explicitly approve.

### 4e: Approve and Ship

You have three options for shipping:

| Command | What it does |
|---------|-------------|
| `/scp` | Stage, commit, push (creates a PR if one does not exist) |
| `/scpmr` | Stage, commit, push, create PR/MR -- but do not merge |
| `/scpmmr` | Stage, commit, push, create PR/MR, and merge -- the full pipeline |

Pick one and the system handles the rest: staging specific files (never `git add -A`), writing a conventional commit message with `Closes #42`, pushing to the remote, and creating or merging the PR/MR.

### The Loop in Practice

Here is what a typical session looks like, end to end:

```
You:    Let's work on issue #42
Claude: [reads the issue, creates branch feature/42-add-retry-logic]

You:    Go ahead and implement it
Claude: [writes code, runs tests]

Claude: /precheck
Claude: [runs validation, code review, presents checklist]
Claude: Ready for your call.

You:    /scpmr
Claude: [commits, pushes, creates PR #58]
Claude: PR #58 is up: https://github.com/your-org/your-repo/pull/58
```

---

## Step 5: Explore Further

You now know the core loop. Here is where to go next:

### Understand the Architecture

Read [Concepts](concepts.md) to understand how the three layers (settings, scripts, skills) fit together, why the mandatory workflows exist, and how the skill taxonomy is organized.

### Learn the Skills

The full skill reference is in [Skill Reference](skill-reference.md) with detailed documentation, examples, and common options for every skill. The most commonly used skills beyond the core workflow:

| Skill | When to use it |
|-------|---------------|
| `/cryo` | Before context compaction -- freezes session state so `/engage` can restore it |
| `/review` | Run a standalone code review on staged changes, a branch diff, or a specific file |
| `/ibm` | Quick reminder of the Issue-Branch-PR/MR workflow when you need to reset your mental model |
| `/disc` | Send and read Discord messages, check in to `#roll-call`, manage channels |
| `/vox` | Text-to-speech announcements ("Hey, the build passed") |
| `/jfail` | Fetch and analyze a failed CI job or workflow run |

### Advanced: Parallel Execution

For large features that decompose into independent sub-issues, the wave system lets multiple agents work in parallel:

1. `/assesswaves` -- quick assessment of whether work items are suitable for parallel execution
2. `/prepwaves` -- full planning: validate sub-issue specs, compute dependency waves, partition into flights
3. `/nextwave` -- execute one wave at a time with isolated worktrees and conflict avoidance

See the [Skill Reference](skill-reference.md) for detailed documentation on each, or the [skill SKILL.md files](../skills/) for the raw agent prompts.

### Keep Your Install in Sync

The ccwork kit evolves. To pull in upstream changes:

```bash
cd claudecode-workflow
git pull
./install.sh --check    # see what changed
./install.sh            # update everything
```

To fold upstream CLAUDE.md template changes into a project's local copy:

```
/ccfold
```

This merges new sections and updates while preserving your project-specific content like Dev-Team and any custom sections you have added.

---

## Quick Reference

| What | How |
|------|-----|
| Verify install | `./install.sh --check` |
| Start a session | `claude` in any project with `CLAUDE.md` |
| Load rules | `/engage` |
| Check workflow | `/ibm` |
| Pre-commit gate | `/precheck` |
| Ship code | `/scp`, `/scpmr`, or `/scpmmr` |
| Freeze state | `/cryo` |
| Restore state | `/engage` |
| Update kit | `git pull && ./install.sh` |
| Sync CLAUDE.md | `/ccfold` |
| Skill reference | [docs/skill-reference.md](skill-reference.md) |
| Troubleshooting | [docs/troubleshooting.md](troubleshooting.md) |
