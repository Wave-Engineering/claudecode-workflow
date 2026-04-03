---
name: view
description: Open a file or URL in a GUI viewer (read-only intent, async)
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-view does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-view
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# View

Open a file or URL in a GUI application for read-only viewing. The application launches asynchronously in a separate window so the chat can continue.

## Resolve Target

{{#if args}}
The target is: `{{args}}`
{{else}}
No target provided. Ask the user what file or URL they want to view.
{{/if}}

The target may be an exact path, a URL, or a **natural language description**. Resolve it:

1. **URL** (`https://`, `http://`, `ftp://`) — use as-is.
2. **Exact file path** (starts with `/`, `./`, `../`, `~`, or looks like a relative path with an extension) — resolve to absolute path and confirm it exists.
3. **Description** (e.g., "the install script", "the system hosts file", "the main CLI entry point") — search the codebase or filesystem to find the intended file:
   - Use context clues: "install script" → `install.sh`, "hosts file" → `/etc/hosts`, "the PRD" → `docs/prd-wave-status-cli.md`
   - Use `Glob` or `Grep` to locate candidates if the intent isn't immediately obvious
   - If multiple candidates match, pick the most likely one or ask the user to clarify
4. Determine the file extension (e.g., `.pdf`, `.png`, `.html`).

## Look Up Preference

Check the user's memory system for a file named `pref_file_apps.md`. This file contains a table mapping file extensions to preferred applications for view and edit modes.

- If the file exists, look up the target's extension in the **View App** column.
- If a preference is found and it is not `-`, use that application.
- If no preference is found, or the extension is not listed, proceed to the default flow.
- For URLs, skip preference lookup — always open in the system browser.

## Open the Target

Use the `file-opener` helper script (installed at `~/.local/bin/file-opener`):

```bash
# With a known preference:
file-opener --mode view --app <preferred_app> <target>

# With system default:
file-opener --mode view <target>
```

**If `file-opener` is not installed**, fall back to a direct platform command:
- Linux: `nohup xdg-open "$target" >/dev/null 2>&1 & disown`
- macOS: `open "$target"`

## Handle Failures

If the open command fails, or the user says the wrong application opened:

1. **Ask the user** what application they would prefer for this file type in view mode.
2. **Check if it is installed**: run `which <app>`.
3. **If not installed**, suggest an install command:
   - Debian/Ubuntu: `sudo apt install <package>`
   - Fedora: `sudo dnf install <package>`
   - macOS: `brew install <package>`
   - Offer to run the install command for the user.
4. **Save the preference** to memory. Create or update the file `pref_file_apps.md`:

   ```markdown
   ---
   name: Preferred applications for file types
   description: User's preferred GUI applications for opening files, organized by extension and mode (view/edit)
   type: feedback
   ---

   | Extension | View App | Edit App |
   |-----------|----------|----------|
   | .pdf      | evince   | -        |
   ```

   - If the file already exists, update the existing row for this extension, or add a new row.
   - Only update the **View App** column. Leave **Edit App** as `-` if not previously set.

5. **Retry** with the new preference.

## Report

After successfully opening, confirm to the user:
> Opened `<target>` in `<app>` (or system default).
