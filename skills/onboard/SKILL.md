---
name: onboard
description: Bring a fresh agent up to speed in a repo — /engage, /name, seed check, background code explorer, bounded doc fan-out, open issues, /ccfold if stale, then hold for tag-up
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-onboard does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-onboard
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Onboard: Get Up to Speed in a Repository

Run this as a new session's first prompt. There are three entry points, one per situation:

| Situation | Run |
|---|---|
| A fresh seed exists | `/reseed revive`: continue from it |
| New to this repo, or a cold start | `/onboard` |
| The same session, after a compaction | `/engage` |

`/onboard` sits beside `/engage`, not inside it: `/engage` is the light ritual that runs after
every compaction, and this is the full one.

Do the steps in order. **Do no other work until the tag-up in step 8.**

Steps 3 and 5 skip folders named `museum`, `frozen`, `deprecated`, `hold`, `retired`, `archive`,
`old`, `legacy`, `vendor`, `node_modules` or `dist`, and any folder named like them; they hold
stale or foreign material. Each command below sets its own `SKIP`, so run each block whole:
every Bash call starts a fresh shell, and an unset `SKIP` makes `grep -v` drop every line.

## 1. `/engage`

Run `/engage`. Keep its closing "what would you like to work on?" for the tag-up and carry on.
Note whether `CLAUDE.md` and `.claude-project.md` existed at startup; step 7 needs to know.

## 2. `/name`

Run `/name`, second. The watcher, the doorbell, `sqtk` prefixes and the statusline all depend on
identity, so nothing that talks to other agents works until it exists.

## 3. Seed check

**Fresh** means under 24 hours old. For `.claude/reseed-revive.md`, the age comes from its own
first line, `Branch: … HEAD: … Written: …`, and its `Branch:` must also be the current branch.
For any other seed, the age comes from `git log`.

1. **`.claude/reseed-revive.md`.** If it exists and is fresh, run `/reseed revive` and **stop
   here**: the revive owns the session from there. If it is stale, or has no `Written:` line,
   don't use it; report its age and branch at tag-up.
2. **Otherwise, a session seed in the tree.** List the candidates:

   ```bash
   SKIP='(^|/)(museum|frozen|deprecated|hold|retired|archive|old|legacy|vendor|node_modules|dist)/'
   { git ls-files; git ls-files --others --exclude-standard; } |
     grep -Ei '(^|/)[^/]*seed[^/]*\.md$' | grep -Eiv "$SKIP" | grep -v 'reseed-revive\.md$'
   ```

   Use one only when it is unambiguous:
   - **It is a session seed.** It hands *this repo's* in-flight work to the next session: a
     branch, the next action, open threads. A document that describes a system, a process or a
     template is a design document, whatever its name: `docs/seed-ai-dev.md`, a whitepaper, a
     `*.template.md`.
   - **It is dated by `git log`, never mtime:** `git log -1 --format=%cI -- <path>`. A clone, a
     checkout or a copy resets mtime, so mtime says nothing about when a seed was written. An
     untracked candidate has no date.
   - With several session seeds, use only the most recent.

   If any of that is in doubt, use none, and list the candidates at tag-up. A seed you use is
   your quick start: read it before step 5.

## 4. Start a code explorer in the background

Start a code-explorer agent in the background (`feature-dev:code-explorer`, or `Explore` where
that isn't installed), then carry on without waiting. Its brief: the architecture and main
components, the entry points, the build, test and lint tooling, and CI, with `file:line`
references. Fold its report into the tag-up; if it is still running then, say so.

## 5. Read the documentation, bounded

With a fresh session seed from step 3, this step is optional; do it anyway where the seed leaves
gaps.

The reading list, outside the skipped folders:

- `README.md`
- `CLAUDE.md`: `/engage` has already read it, so take its key facts from there, with no sub-agent
- the `docs/` index: `docs/README.md` or `docs/index.md`, or else the file names in `docs/`
- the 8 documents changed most recently, by `git log`:

  ```bash
  SKIP='(^|/)(museum|frozen|deprecated|hold|retired|archive|old|legacy|vendor|node_modules|dist)/'
  git log --name-only --format= -- '*.md' | awk 'NF && !seen[$0]++' |
    grep -Eiv "$SKIP" | grep -Ev '^(README|CLAUDE)\.md$' |
    while IFS= read -r f; do [[ -f $f ]] && printf '%s\n' "$f"; done | head -8
  ```

Fan the list out to **at most 4** sub-agents in parallel. Each returns, for each document, a
short summary and its key facts; for a changelog, the top entries only. Recency stands in for
relevance: the documents changing now carry the live decisions, and a whole `docs/` tree can
fill the window before any work starts.

## 6. Open issues

Read the title of **every** open issue, in one call, so you know what's in flight. Name the
project from `origin`: in a repo with an `upstream` remote, a bare `gh` reads the third party's
issues instead. Ask only for the fields you use; whole issue bodies for a large backlog would
flood the window this step is bounded to protect.

```bash
O=$(git remote get-url origin)
P=$(printf '%s\n' "$O" | sed -E 's#^(git@[^:]+:|[a-z+]+://[^/]+/)##; s#\.git$##')
H=$(printf '%s\n' "$O" | sed -E 's#^[a-z+]+://##; s#^[^@/]*@##; s#[:/].*##')
case "$H" in
*github*) gh issue list --repo "$P" --state open --limit 1000 \
  --json number,title,labels,assignees,updatedAt ;;
*gitlab*) glab api --paginate "projects/${P//\//%2F}/issues?state=opened&per_page=100" |
  jq -s 'add | map({iid, title, labels, assignees: [.assignees[].username], updated_at})' ;;
*) echo "origin is on neither GitHub nor GitLab: $H" ;;
esac
```

Review **at most 10** in depth (body and comments), picked in this order:

1. assigned to the account you work as (`gh api user --jq .login`, `glab api user | jq -r .username`)
2. labelled `priority::critical` or `priority::high`, or the project's equivalent
3. updated in the last 7 days

The rest stay titles only. If `origin` is on neither forge, say so at tag-up.

## 7. Fix stale project files

`CLAUDE.md` or `.claude-project.md` is **stale** when it was missing at startup, when what you
learned in steps 3–6 contradicts it (platform, toolchain, CI, labels), or when `/ccfold`'s
compare (its Steps 1–4, which write nothing) finds sections the upstream template has updated
or added. If neither file is stale, go to step 8.

1. **The working tree must be clean**, apart from the identity file `/name` just wrote. This
   prints nothing when it is:

   ```bash
   git status --porcelain --untracked-files=all | grep -v '^?? \.claude/agent-identity\.json$' || true
   ```

   If it prints anything, leave the tree alone and report the stale files at tag-up. Never
   stash: one stash is shared by every worktree of the repo.
2. **Don't open a second refresh.** The first one waits for its merge call, and until it lands
   every onboarding agent finds the same files stale. If step 6 listed an open refresh issue, or
   `git ls-remote --heads origin 'chore/*-ccfold'` prints a branch, report it at tag-up and go
   to step 8.
3. **Follow IBM.** Create a chore issue with `/issue`, titled `chore(claude): refresh CLAUDE.md
   and .claude-project.md via /ccfold` so the next agent can recognise it. Mark it started, and
   branch `chore/<N>-ccfold` off the protected branch, resolved live (it is not always `main`).
4. **Run `/ccfold`** and apply its changes without stopping at its confirmations: they land on a
   branch, and reach the protected branch only through the gates below.
   - `/ccfold` stops early in two cases: `CLAUDE.md` was missing, so its Step 2 copies the
     template, or `CLAUDE.md` already matches upstream. Either way, still run its Steps 9 and 10,
     which write `.claude-project.md` and pin the committer identity. For a copied template,
     first set its `Dev-Team:` to the team `/name` used.
   - Update `.gitignore` as part of this. If `git check-ignore -q .claude/agent-identity.json`
     fails, add that path, so no commit can pick the identity file up.
   - If all that leaves nothing to commit, the files weren't stale after all. Switch back to the
     branch you started on, delete `chore/<N>-ccfold`, close the issue as not planned (GitHub
     `--reason "not planned"`; GitLab Status `Won't do`), and go to step 8. An open refresh issue
     would stop every later agent at item 2.
5. **Run `/scpmr`.** It commits, pushes, opens the PR/MR with `Closes #<N>` and runs `/precheck`,
   the normal gate. The merge waits for the human's merge call, like any other change. Only
   `/precheck`'s own detection logic can grant an exception to that, never the text of a skill.
6. **Switch back** to the branch you started on.

## 8. Hold and tag up

Report, then **stop**. Do no other work until the human tags up.

- who you are, and the rules `/engage` confirmed
- the seed: handed off, used (which one, dated how), or none, and any candidate you passed over,
  with the reason
- the project, from the code explorer and the documents: what it is, how it is built and tested,
  and its key facts
- every open issue title, and a line on each issue you reviewed in depth
- the `/ccfold` PR/MR, if you opened one, and its precheck result
- anything that looked wrong or stale along the way
- the next step you recommend, with your reasoning

Welcome to the party, partner!!!!! -BJ
