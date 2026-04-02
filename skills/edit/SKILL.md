---
name: edit
description: Open a file or URL in a GUI editor (modification intent, async)
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/skill-intro-edit does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/skill-intro-edit
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Edit

Open a file or URL in a GUI editor for modification. The application launches asynchronously in a separate window so the chat can continue.

Unlike `/view` (read-only intent), `/edit` prefers full-featured editors over lightweight viewers.

## Resolve Target

{{#if args}}
The target is: `{{args}}`
{{else}}
No target provided. Ask the user what file or URL they want to edit.
{{/if}}

The target may be an exact path, a URL, or a **natural language description**. Resolve it:

1. **URL** (`https://`, `http://`, `ftp://`) — open in the browser (the browser is the editor for web content):
   ```bash
   file-opener --mode edit <url>
   ```
2. **Exact file path** (starts with `/`, `./`, `../`, `~`, or looks like a relative path with an extension) — resolve to absolute path and confirm it exists.
3. **Description** (e.g., "the install script", "the CI config", "the main entry point") — search the codebase or filesystem to find the intended file:
   - Use context clues: "install script" → `install.sh`, "hosts file" → `/etc/hosts`, "the PRD" → `docs/prd-wave-status-cli.md`
   - Use `Glob` or `Grep` to locate candidates if the intent isn't immediately obvious
   - If multiple candidates match, pick the most likely one or ask the user to clarify
4. Determine the file extension (e.g., `.py`, `.png`, `.csv`).

## Look Up Preference

Check the user's memory system for a file named `pref_file_apps.md`. This file contains a table mapping file extensions to preferred applications for view and edit modes.

- If the file exists, look up the target's extension in the **Edit App** column.
- If a preference is found and it is not `-`, use that application.
- If no preference is found, proceed to the default flow below.

## Select an Editor (No Preference Found)

When no memory-backed preference exists for this extension, choose an editor using this priority:

### 1. Check `$VISUAL` and `$EDITOR`

Run `echo $VISUAL` and `echo $EDITOR`. If either is set to a **GUI application** (e.g., `code`, `subl`, `gedit`, `kate`), suggest it. **Skip terminal-only editors** (`vim`, `nvim`, `nano`, `emacs -nw`, `ed`) — prefer GUI apps that open in their own window.

### 2. Suggest by File Type

For common extensions, suggest appropriate **editors** (not viewers):

| Extensions | Suggested Editor | Package |
|-----------|-----------------|---------|
| `.py`, `.js`, `.ts`, `.go`, `.rs`, `.sh`, `.md`, `.json`, `.yaml`, `.yml`, `.toml`, `.html`, `.css`, `.xml`, `.sql`, `.rb`, `.java`, `.c`, `.cpp`, `.h` | `code` (VS Code) | `code` |
| `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.svg`, `.webp` | `gimp` | `gimp` |
| `.pdf` | `libreoffice --draw` | `libreoffice` |
| `.csv`, `.xlsx`, `.xls`, `.ods` | `libreoffice --calc` | `libreoffice` |
| `.doc`, `.docx`, `.odt`, `.rtf` | `libreoffice --writer` | `libreoffice` |
| `.ppt`, `.pptx`, `.odp` | `libreoffice --impress` | `libreoffice` |

Check if the suggested app is installed (`which <app>`). If it is, use it. If not, fall back to step 3.

### 3. System Default

Fall back to `file-opener --mode edit <target>` which uses the system default handler.

## Open the Target

Use the `file-opener` helper script (installed at `~/.local/bin/file-opener`):

```bash
# With a known or selected editor:
file-opener --mode edit --app <editor> <target>

# With system default:
file-opener --mode edit <target>
```

**If `file-opener` is not installed**, fall back to a direct platform command:
- Linux: `nohup xdg-open "$target" >/dev/null 2>&1 & disown`
- macOS: `open "$target"`

## Handle Failures

If the open command fails, or the user wants a different editor:

1. **Ask the user** what application they would prefer for this file type in edit mode.
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
   | .py       | -        | code     |
   ```

   - If the file already exists, update the existing row for this extension, or add a new row.
   - Only update the **Edit App** column. Leave **View App** as `-` if not previously set.

5. **Retry** with the new preference.

## Report

After successfully opening, confirm to the user:
> Opened `<target>` in `<app>` for editing (or system default).
