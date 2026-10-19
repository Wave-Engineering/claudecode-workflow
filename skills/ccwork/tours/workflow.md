# Tour: Workflow

A guided walkthrough of the issue-to-merge development loop. This tour demonstrates each step of the mandatory workflow using the user's actual project state.

**Pace:** This tour is more hands-on than the orientation. Show each step, explain what it enforces and why, then move to the next.

**Cross-references:** The [Mandatory Workflow](../../../docs/getting-started.md#step-4-the-mandatory-workflow) section in Getting Started covers this same loop as a reference. This tour is the interactive version.

---

## Section 1: The Rule

Narration: "Every change in the ccwork kit follows the same loop: **issue, branch, code, push, precheck, merge**. The system enforces this — it's not optional. Let me show you why each step matters and what happens when you try to skip one."

For the design rationale behind each mandatory rule, see [Mandatory Workflows](../../../docs/concepts.md#mandatory-workflows) in Concepts.

---

## Section 2: Issue First

Narration: "Step one: you need an issue before any code gets written. The issue is the contract — it defines what 'done' looks like."

### Show how to find or create issues

```bash
# Platform detection
REMOTE_URL=$(git remote get-url origin 2>/dev/null)
if echo "$REMOTE_URL" | grep -qi github; then
  CLI="gh"
elif echo "$REMOTE_URL" | grep -qi gitlab; then
  CLI="glab"
fi

# List recent issues
$CLI issue list --limit 5 2>/dev/null || echo "(could not list issues — check CLI auth)"
```

Narration: "Every issue needs labels (type, priority, urgency) and acceptance criteria. The templates in CLAUDE.md define the format — features get implementation steps and test procedures, bugs get reproduction steps and severity."

### Show the IBm reminder

Narration: "If you ever forget the workflow, `/ibm` is the cheat sheet. It resolves your platform, target branch, and walks you through each step. Try it any time."

---

## Section 3: Branch Linked to Issue

Narration: "Step two: create a feature branch linked to your issue. The branch name includes the issue number so the system can trace work back to its origin."

### Show current branch state

```bash
git branch --show-current
echo ""
echo "Branch naming convention:"
echo "  feature/<issue-number>-description"
echo "  fix/<issue-number>-description"
echo "  chore/<issue-number>-description"
echo "  doc/<issue-number>-description"
```

Narration: "The branch name format is `<type>/<issue-number>-<description>`. When `/precheck` runs, it extracts the issue number from your branch name to verify the issue exists and is open. If you're on `main` or a branch without an issue number, it stops you."

---

## Section 4: Code

Narration: "Step three: write the implementation. This is where the actual work happens. You write code, Claude assists — or Claude drives and you review. Either way, the acceptance criteria from the issue define what 'done' means."

### Show the testing gate

```bash
# Check what test tooling exists
test -f ./scripts/ci/validate.sh && echo "validate.sh: found" || echo "validate.sh: not found"
test -f ./Makefile && echo "Makefile: found" || echo "Makefile: not found"
```

Narration: "Testing gates the PR/MR, not the push. Your own working branch — `feature/`, `fix/`, `chore/`, `doc/` — pushes freely as a plain `git push <remote> <branch>`. Before a push to a protected or release branch, or before a PR/MR is marked ready, the tests must pass — `/precheck` reads CI's verdict for the pushed commit and runs local tooling where CI doesn't cover it. This is non-negotiable. The kit looks for `./scripts/ci/validate.sh`, Makefile targets, pytest, npm test — whatever the project provides. If you push untested code, you've wasted CI resources and blocked the pipeline."

---

## Section 5: Commit and Push (Free)

Narration: "Step four: commit and push. On your own working branch this is free — `/scp` needs no precheck and no approval. Two hooks still run: a secret scan at commit and push, and a push gate that refuses protected and release branches. `/scp` opens no PR."

### Show the commit message format

```
type(scope): brief description

[Optional body]

Closes #42
```

Narration: "The commit message follows conventional commit format — `feat`, `fix`, `doc`, `chore`, etc. — with `Closes #<number>` to auto-close the linked issue on merge. Claude writes the commit message, stages specific files (never `git add -A`), and handles the push."

---

## Section 6: The MR Gate and the Merge Call

Narration: "Step five: the MR gate. This is the most important skill in the kit. When your work is done, `/scpmr` opens a **draft** PR/MR — drafts are free, they can't merge, and opening one starts CI — then runs `/precheck`, a multi-step verification of the pushed commits."

### Show what precheck does

Present this sequence:

```
/precheck
  1. Branch & issue check — are you on a feature branch linked to an open issue?
  2. CI and validation — read CI's verdict for the pushed HEAD; run local tooling only where CI doesn't cover it
  3. Code review — launch a code-reviewer sub-agent over the pushed commits
  4. Fix high-risk findings — anything critical gets fixed, committed and pushed before the checklist
  5. Present checklist — full verification: implementation, TODOs, docs, tests, review
  6. On a pass — post the `precheck` commit status and mark the PR/MR ready
  7. STOP and wait — no merge until you give the merge call
```

Narration: "After the checklist, Claude stops. It will not merge until you respond, and a hook refuses to mark a PR/MR ready without the `precheck` status. This is the safety net that keeps unreviewed code out of the protected branch. You give the merge call with one of these:"

| Command | What it does |
|---------|-------------|
| `/mmr` | Merge the prechecked PR/MR |
| `/scpmmr` | After a precheck STOP, the same as `/mmr` |
| an affirmative | Same as `/mmr` |

Narration: "If you push more commits after the pass, `/precheck rearm` reviews only the new commits and waits for a green pipeline — and `/mmr` runs it for you."

---

## Section 7: After Merge

Narration: "One more thing: after a PR is merged, all linked issues must be closed. The `Closes #NNN` in the PR description usually handles this automatically, but the kit verifies it. If auto-close fails, Claude closes the issues manually."

### Show the full loop

```
You:    Let's work on issue #42
Claude: [reads issue, creates branch feature/42-description]

You:    Go ahead and implement it
Claude: [writes code, runs tests, commits and pushes with /scp]

Claude: [runs /scpmr — draft PR #58, then /precheck: CI, code review, checklist]
Claude: PR #58 is ready for your merge call: https://github.com/...

You:    /mmr
Claude: [merges PR #58]

[After merge]
Claude: [closes issue #42]
```

Narration: "That's the loop. Issue, branch, code, push, precheck, merge. Every time, no exceptions. The [Getting Started guide](../../../docs/getting-started.md) covers this same flow as a written reference you can come back to."

---

## Section 8: What's Next

- **Try it for real** — pick an issue (or create one) and go through the full cycle
- **Tour the foundations** — `/ccwork tour foundations` covers session lifecycle skills
- **Back to overview** — `/ccwork tour` for the full orientation
- **Quick reference** — `/ibm` for a one-page workflow reminder
