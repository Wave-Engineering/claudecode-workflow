---
name: ccfold
description: Merge upstream CLAUDE.md template changes into the current project's CLAUDE.md, preserving project-specific content like Dev-Team and custom sections. Fetches the latest template from GitHub.
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-ccfold does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-ccfold
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

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

**Before writing**, back up the existing CLAUDE.md so the user can inspect or extract from it later:

```bash
PROJECT_NAME=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
SESSION_ID="${CLAUDE_SESSION_ID:-$(date +%Y%m%d-%H%M%S)}"
BACKUP="/tmp/CLAUDE.md.bak.${PROJECT_NAME}.${SESSION_ID}"
cp CLAUDE.md "$BACKUP"
```

Tell the user:
> Backed up previous CLAUDE.md to `<backup path>`

Then write the merged CLAUDE.md. The final file should contain:

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

## Step 10: Pin Per-Project Git Identity by Org

After writing `.claude-project.md`, detect the project's git platform/org and pin a repo-local committer identity if the org requires a verified email that differs from the agent's global default.

### Why

Some git hosting orgs (notably AnalogicDev on GitLab) enforce a verified-email push-rule. The default global git identity many agents have set (e.g. `bakerb@waveeng.com`) is not verified on those accounts, so pushes are rejected with:

```
remote: GitLab: You cannot push commits for 'bakerb@waveeng.com'. You can only push commits if the committer email is one of your own verified emails.
```

This step automates the previously-manual `git config user.email <verified-email>` fix. See `lesson_analogicdev_gitlab_setup.md` for the discovery story.

### Storage choice — `~/.claude/identity-map.json` (per-user)

The org → identity mapping lives in **`~/.claude/identity-map.json`**, not in `.claude-project.md`.

**Rationale:**
- **Per-user, shared across projects.** Every clone of every analogicdev project gets the same identity; we don't want to reproduce the mapping in every `.claude-project.md`.
- **Cleanly extensible.** Users add new orgs by editing one JSON file, not by editing SKILL.md or every project's config.
- **Hybrid baseline.** The skill ships with a hard-coded fallback (currently just `analogicdev`) so first-clone agents get the right behavior even before the file exists. The user's JSON, if present, overrides the baseline.

### File format

```json
{
  "analogicdev": {
    "name": "Brian Baker",
    "email": "brbaker@analogic.com"
  }
}
```

Org keys are lower-case. If `~/.claude/identity-map.json` does not exist, the skill falls back to the baseline mapping documented above.

### Procedure

1. **Parse the org from `git remote get-url origin`.** Both SSH and HTTPS forms must be handled.

   ```bash
   ORIGIN=$(git remote get-url origin 2>/dev/null || true)
   # SSH:    git@github.com:owner/repo.git           or  git@gitlab.com:group/sub/repo.git
   # HTTPS:  https://github.com/owner/repo[.git]     or  https://gitlab.com/group/sub/repo[.git]
   ORG=$(echo "$ORIGIN" \
     | sed -E 's#^git@[^:]+:([^/]+)/.*#\1#; s#^https?://[^/]+/([^/]+)/.*#\1#' \
     | tr '[:upper:]' '[:lower:]')
   ```

   For nested GitLab groups (`gitlab.com/analogicdev/internal/tools/...`), the **top-level group** is the org. The sed expression above takes the first path segment after the host, which is correct.

2. **Look up the org.** Read `~/.claude/identity-map.json` if present; otherwise use the baseline below. If the org has no entry, **do nothing and emit no output** (silent for unmapped orgs — see ACs).

   Baseline (hard-coded fallback when `~/.claude/identity-map.json` is missing or doesn't contain the org):

   | Org | Name | Email |
   |---|---|---|
   | `analogicdev` | Brian Baker | `brbaker@analogic.com` |

3. **Check the existing repo-local identity.** Distinguish three cases:

   - **No repo-local override** — `git config --local --get user.email` returns empty (or non-zero exit). The repo currently inherits from global config.
   - **Repo-local override matches the mapping** — already correct, do nothing, suppress output.
   - **Repo-local override differs from the mapping** — the user has explicitly chosen something else. Do **NOT** overwrite. Emit a warning instead.

   The check must use `git config --local --get` (not the unscoped `git config user.email`, which folds in global config and would mask whether a local override exists).

4. **Decide the action:**

   | Repo-local | Global identity matches mapping | Action |
   |---|---|---|
   | unset | yes | nothing (already correct via global) |
   | unset | no  | set `user.email` and `user.name` repo-locally; print confirmation |
   | matches mapping | — | nothing (already correct via local) |
   | differs from mapping | — | emit warning; do not override |

5. **When pinning, set both name and email repo-locally:**

   ```bash
   git config --local user.email "<mapped-email>"
   git config --local user.name "<mapped-name>"
   ```

6. **Output:**

   - On successful pin: `→ pinned identity for <org>: <name> <email>`
   - On warning (local override differs from mapping): `Repo-local identity differs from <org>'s expected committer email; pushes may be rejected if email is unverified.`
   - On no-op (already correct, or org not in mapping): no output

### Test scenarios (verified during implementation)

- Fresh clone of an `analogicdev/*` repo with global `user.email=bakerb@waveeng.com` → repo-local set to `brbaker@analogic.com`, confirmation printed.
- Wave-Engineering clone → no mapping, silent.
- Repo-local already manually set to a non-mapping value → warning printed, no override.
- Repo-local already set to the mapping value → silent no-op.

---

## Notes

- This skill does NOT commit changes. The user handles git workflow after merge.
- If the upstream template and local file are identical, say so and stop.
- The merge is semantic, not mechanical. Use your judgment to combine content intelligently rather than blindly replacing text blocks.
- When in doubt about whether a local change is intentional customization or just an older version of the template, ask the user.
