---
name: ccfold
description: Merge upstream CLAUDE.md template changes into the current project's CLAUDE.md, preserving project-specific content like Dev-Team and custom sections. Fetches the latest template from GitHub.
---

# CCFold — Merge Upstream CLAUDE.md Template

You are merging the latest CLAUDE.md template from the `claudecode-workflow` repo into the current project's CLAUDE.md.

Follow these steps exactly.

---

## Step 1: Fetch the Upstream Template

Fetch the latest CLAUDE.md from the canonical source:

```bash
gh api repos/Wave-Engineering/claudecode-workflow/contents/CLAUDE.md \
  --jq '.content' | base64 -d > /tmp/claudemd-upstream.md
```

If this fails (no `gh` auth, repo not accessible), fall back:
```bash
curl -sL "https://raw.githubusercontent.com/Wave-Engineering/claudecode-workflow/main/CLAUDE.md" \
  > /tmp/claudemd-upstream.md
```

Read the fetched file to confirm it looks valid (starts with `# Project Instructions for Claude Code`).

---

## Step 2: Read the Local CLAUDE.md

Read the current project's `CLAUDE.md` from the project root.

**If no CLAUDE.md exists:** Tell the user and offer to copy the upstream template as-is. If they accept, copy it, clear the `Dev-Team:` value, and stop.

**If CLAUDE.md exists:** Continue to Step 3.

---

## Step 3: Identify Sections

Parse both files into sections by splitting on `## ` headers. Each section consists of its `## ` header line and all content until the next `## ` header or end of file. The preamble before the first `## ` header is also a section (the title block).

For each file, build a list of section names (the text after `## `).

---

## Step 4: Compare and Classify

Compare the two section lists and classify each section:

| Category | Meaning | Action |
|----------|---------|--------|
| **Identical** | Same header and same content in both | Skip — no change needed |
| **Updated** | Same header, different content | Upstream has improvements — propose merge |
| **New upstream** | Header exists upstream but not locally | New section added to template — propose adding |
| **Local only** | Header exists locally but not upstream | Project-specific customization — preserve as-is |

---

## Step 5: Preserve Project-Specific Content

These items MUST be preserved from the local file, never overwritten by upstream:

- The `Dev-Team:` value at the bottom of the Agent Identity section
- Any section that exists only locally (classified as "Local only" above)
- Any content appended below the `Dev-Team:` line

When merging the `## Agent Identity` section, always keep the local `Dev-Team:` value even if the surrounding text is updated from upstream.

---

## Step 6: Present the Merge Plan

Show the user a summary:

```
CLAUDE.md merge: upstream → local
══════════════════════════════════════════

  [=] Section Name                    (identical — no change)
  [~] Section Name                    (updated upstream)
  [+] Section Name                    (new in upstream)
  [-] Section Name                    (local only — preserved)

══════════════════════════════════════════
X sections unchanged, Y to update, Z to add
```

For each `[~]` (updated) section, show a concise summary of what changed — not a raw diff, but a human-readable description. For example:
> `[~] Code Standards` — Upstream added Go and Rust to the defaults table and reworded the discovery instructions.

For each `[+]` (new) section, show the section title and a one-line summary of its purpose.

---

## Step 7: Confirm

Ask: **"Apply these changes to CLAUDE.md?"** and wait for explicit approval.

The user may also:
- Ask to skip specific sections ("skip the Code Standards update")
- Ask to see the full diff for a specific section
- Ask to abort

---

## Step 8: Apply

Write the merged CLAUDE.md. The final file should contain:

1. All sections from upstream, in upstream order, with updates applied
2. All local-only sections, appended after the last upstream section (but before `Dev-Team:` if they were originally above it)
3. The `Dev-Team:` value preserved from the local file

After writing, show:
> "CLAUDE.md updated. Review with `git diff CLAUDE.md`."

---

## Step 9: Discover and Write Project Configuration

After merging CLAUDE.md, generate or update `.claude-project.md` in the project root. This file caches project-specific settings so agents don't re-discover them every session.

### Discovery

Run these commands to populate each section:

1. **Platform** — `git remote get-url origin` to determine host (GitHub/GitLab) and CLI (`gh`/`glab`)
2. **Default branch** — `git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@'`
3. **Existing labels** — `gh label list --limit 50 --json name,description` (GitHub) or `glab label list` (GitLab)
4. **CI system** — Check for `.github/workflows/` (GitHub Actions) and/or `.gitlab-ci.yml` (GitLab CI)
5. **Toolchain** — Check for `scripts/ci/validate.sh`, `scripts/ci/build.sh`, `Makefile`, `pytest`, `package.json`, etc.

### Writing `.claude-project.md`

Use this template structure:

```markdown
# Project Configuration

<!-- Auto-generated by /ccfold. Manual edits are preserved on re-fold. -->

## Platform
- **Host:** (GitHub | GitLab)
- **CLI:** (gh | glab)
- **Remote:** (origin URL)

## Branching
- **Default branch:** (discovered)
- **Merge strategy:** squash

## Status Mechanism
- **Type:** (GitHub native | label-based | Projects columns)
- **Agent instruction:** (how to transition status)

## Existing Labels
<!-- Labels in use on this repo — do not conflict -->
(list from label discovery, organized by prefix)

## Toolchain
- **Validation:** (command or "none")
- **Tests:** (command or "none")
- **Build:** (command or "none")
- **Lint:** (tools discovered)

## CI
- **System:** (GitHub Actions | GitLab CI | both)
- **Config:** (path(s) to CI config files)
```

### Update vs Create

- **If `.claude-project.md` does not exist:** Create it from scratch using the template above, populated with discovered values.
- **If `.claude-project.md` already exists:** Preserve any content outside the auto-generated sections. Update the auto-generated sections (those between `<!-- Auto-generated -->` markers) with fresh discovery results. Manual edits in non-templated areas are kept.

### Show the user what was written

After writing `.claude-project.md`, show:
> "`.claude-project.md` updated with project configuration. Review with `git diff .claude-project.md`."

---

## Notes

- This skill does NOT commit changes. The user handles git workflow after merge.
- If the upstream template and local file are identical, say so and stop.
- The merge is semantic, not mechanical. Use your judgment to combine content intelligently rather than blindly replacing text blocks.
- When in doubt about whether a local change is intentional customization or just an older version of the template, ask the user.
