---
name: man
description: Display usage information for any installed skill
usage: |
  /man <skill>     Show usage for a skill
  /man             List all installed skills with descriptions
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-man does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-man
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Man: Skill Usage Display

Display usage information for installed skills. Reads the `usage` field from
SKILL.md frontmatter for fast structured output. Falls back to interpreting the
full skill file when no `usage` frontmatter exists.

## Execution

### `/man <skill>` — Show usage for a specific skill

1. **Resolve skill path:**
   ```
   ~/.claude/skills/<skill>/SKILL.md
   ```
   If the file does not exist, report: `No skill found: <skill>`

2. **Read the SKILL.md file.**

3. **Extract frontmatter** — parse the YAML block between the opening and
   closing `---` delimiters. Pull out `name`, `description`, and `usage`.

4. **If `usage` field exists**, display:

   ```
   <name> — <description>

   Usage:
     <usage content, indented 2 spaces>
   ```

5. **If `usage` field is absent**, interpret usage from the full file:
   - Look for a `## Subcommands`, `## Usage`, or similar section
   - Extract the command table or usage patterns
   - Summarize into a CLI-style help block
   - Append: `(No usage frontmatter — interpreted from SKILL.md)`

### `/man` — List all installed skills

1. **Scan** `~/.claude/skills/*/SKILL.md`
2. **Extract** `name` and `description` from each file's frontmatter
3. **Display** as a formatted table, sorted alphabetically:

   ```
   Installed Skills
   ────────────────────────────────────────
   assesswaves   Quick assessment of wave-pattern suitability
   ccfold        Merge upstream CLAUDE.md template changes
   cryo          Cryogenically preserve session state
   ...
   ```

## Important

- **Do NOT invoke the target skill.** `/man nerf` reads the file — it does not
  run `/nerf`. This is a read-only operation.
- **Keep output concise.** The whole point is to avoid loading the full skill
  into context. Don't dump the entire SKILL.md.
- **Frontmatter `usage` field format** is a multi-line string showing invocation
  patterns, one per line, CLI-style. No markdown formatting — plain text.
