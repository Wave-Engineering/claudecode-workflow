# Tour: Foundations

A guided walkthrough of the foundational skills — the ones that manage session state, identity, and maintenance. These are the skills you use at session boundaries, not during active development.

**Pace:** Each section covers one skill. Show what it does, run a live command where possible, and explain when to use it.

**Cross-references:** The [Foundation Skills](../../../docs/concepts.md#foundation-skills) table in Concepts provides the quick-reference version of this tour.

---

## Section 1: `/engage` — The Thaw Cycle

Narration: "The most important foundation skill. `/engage` loads your rules, restores context, and confirms ready state. You run it at session start and after every context compaction."

### What it does

1. **Reads CLAUDE.md** and confirms the mandatory rules are loaded
2. **Loads the current plan** if one exists (from a prior `/cryo` or plan mode)
3. **Reports ready state** — current branch, pending work, asks what's next

### When to use it

- **Every session start** — first thing you run (or Claude runs it for you)
- **After context compaction** — when Claude's context window fills and gets summarized, `/engage` is the safety net that restores the rules that compaction may have dropped

### Live check

```bash
echo "CLAUDE.md location:"
ls CLAUDE.md .claude/CLAUDE.md 2>/dev/null || echo "  (not found in current directory)"
```

Narration: "If there's no `CLAUDE.md` in your project, `/engage` still works — it just skips the rules confirmation. Copy the template from the ccwork repo to enable the full workflow."

---

## Section 2: `/cryo` — The Freeze Cycle

Narration: "`/cryo` is the complement to `/engage`. It freezes session state before context compaction hits. Think of it as saving your game."

### What it does

1. **Audits current state** — branch, recent commits, uncommitted work
2. **Curates the plan file** — rewrites it as a snapshot of where things stand RIGHT NOW
3. **Prunes the task list** — deletes completed and stale tasks, keeps pending ones
4. **Confirms** — tells you what was preserved

### When to use it

- **When context is getting full** — you'll notice responses getting shorter or less detailed
- **Before a long break** — if you're stepping away and want to resume later
- **Before any operation that might trigger compaction** — large file reads, long conversations

### The cryo-engage cycle

```
Session start → /engage (thaw)
     ↓
  [work]
     ↓
Context filling up → /cryo (freeze)
     ↓
  [compaction happens]
     ↓
/engage (thaw) → resume work
```

Narration: "`/cryo` writes to the plan file, `/engage` reads from it. They're a matched pair. The plan file is the only thing that survives compaction intact — everything else becomes a lossy summary."

---

## Section 3: `/ccfold` — Template Sync

Narration: "`/ccfold` keeps your project's `CLAUDE.md` in sync with the upstream template. When the kit adds new sections or updates existing ones, `/ccfold` merges them in without overwriting your project-specific content."

### What it does

1. **Fetches** the latest CLAUDE.md template from the canonical repo
2. **Compares** each section between upstream and local
3. **Presents** a merge plan — what will be added, updated, or left alone
4. **Applies** the merge after your approval

### When to use it

- **After pulling kit updates** — `git pull` in the ccwork repo, then `/ccfold` in each project
- **When a new skill appears** — the template often adds references to new skills
- **On first setup** — `/ccfold` also generates `.claude-project.md` with cached platform detection

### Check current state

```bash
test -f .claude-project.md && echo ".claude-project.md: exists (platform cached)" || echo ".claude-project.md: not found (will be generated on next /ccfold)"
```

For the full explanation of how CLAUDE.md works and what `/ccfold` does, see [How CLAUDE.md Works](../../../docs/concepts.md#how-claudemd-works) in Concepts.

---

## Section 4: `/edit` and `/view` — File Access

Narration: "These two skills open files in your GUI applications. `/view` is read-only, `/edit` is for modification. Both are async — they hand off to the OS and return immediately."

### What they do

| Skill | Intent | Example |
|-------|--------|---------|
| `/view` | Read-only viewing | `/view screenshot.png`, `/view https://example.com` |
| `/edit` | Modification | `/edit config.yaml`, `/edit ~/.claude/settings.json` |

### Check the file opener

```bash
which file-opener 2>/dev/null && echo "file-opener: installed" || echo "file-opener: not installed"
```

Narration: "Both skills use the `file-opener` script under the hood, which calls `xdg-open` on Linux or `open` on macOS. You can configure preferred apps per file extension."

---

## Section 5: `/name` — Identity Management

Narration: "`/name` reports or picks your session identity. Every session gets a fresh Dev-Name and Dev-Avatar, but the Dev-Team is persistent."

### Check current identity

```bash
project_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
dir_hash=$(echo -n "$project_root" | md5sum | cut -d' ' -f1)
agent_file="/tmp/claude-agent-${dir_hash}.json"
if [[ -f "$agent_file" ]]; then
  echo "Current identity:"
  cat "$agent_file"
else
  echo "No identity file found. Run /name to create one."
fi
```

### Check Dev-Team

```bash
grep "^Dev-Team:" CLAUDE.md 2>/dev/null || echo "(no Dev-Team field found)"
```

Narration: "Dev-Team identifies your project — it's the same for every session. Dev-Name is ephemeral — a new terminal means a new name. When multiple agents are running, Dev-Team is how you address a project (`@cc-workflow`) and Dev-Name is how you address a specific session (`@beacon`)."

For the full identity system design, see [Identity System](../../../docs/concepts.md#identity-system) in Concepts.

---

## Section 6: `/ibm` — Workflow Reminder

Narration: "The last foundation skill is `/ibm` — Issue, Branch, Merge. It's a quick-reference cheat sheet for the mandatory workflow. Not an executor — it doesn't do anything, just reminds you of the steps."

### When to use it

- When you start a new piece of work and want to make sure you're following the process
- When you come back from a break and need to reorient
- When onboarding someone and want to show them the flow in one page

Narration: "`/ibm` resolves your platform (GitHub vs GitLab), your target branch, and walks you through: issue exists? Branch linked? PR targets the right base? It's the checklist you run through in your head before starting."

---

## Section 7: Summary

Here is the full foundation skill set at a glance:

| Skill | When | What |
|-------|------|------|
| `/engage` | Session start, after compaction | Load rules, restore context |
| `/cryo` | Before compaction, before breaks | Freeze state to plan file |
| `/ccfold` | After kit updates | Merge upstream CLAUDE.md changes |
| `/edit` | When you need to modify a file in GUI | Open in editor |
| `/view` | When you need to view a file in GUI | Open in viewer |
| `/name` | Check or pick identity | Show/set Dev-Name, Dev-Avatar |
| `/ibm` | Workflow check | Quick-reference for the dev loop |

---

## What's Next

- **Try the workflow** — `/ccwork tour workflow` for the full issue-to-merge walkthrough
- **Back to overview** — `/ccwork tour` for the orientation
- **Read the reference** — [Concepts](../../../docs/concepts.md) covers everything in this tour in written form
- **Explore a skill** — run any `/command` to see it in action
