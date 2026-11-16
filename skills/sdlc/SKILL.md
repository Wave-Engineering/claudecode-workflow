---
name: sdlc
description: SDLC workflow tools — work item creation, branch/PR compliance
---

# SDLC Workflow Tools

Route all /sdlc intents to `sdlc_*` MCP tool calls. Do NOT use bash or shell commands.

**AC and DoD must be checkable before the item closes.** No acceptance criterion or definition-of-done line, in an issue, epic, plan, PR or MR, may wait for something that happens after the item is closed: a merge, release, install, deploy or roll, time passing, a live observation, or someone's later sign-off. Details and rewrites: `docs/ac-checkable-before-close.md`. The `work_item` tool does not check this for you: write the body to a file and run `precheck-ac-gate.sh lint <file>` first (`/issue` Step 2.5), and create nothing on exit 2.

## Available Tools

- `work_item` — Create any work item (epic, story, bug, chore, doc, PR, MR) on GitHub or GitLab
- `ibm` — Check issue/branch/PR workflow compliance for the current branch

## Usage

Invoke the appropriate MCP tool directly. The tool handles platform detection (GitHub vs GitLab) internally.
