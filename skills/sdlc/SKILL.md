---
name: sdlc
description: SDLC workflow tools — work item creation, branch/PR compliance
---

# SDLC Workflow Tools

Route all /sdlc intents to `sdlc_*` MCP tool calls. Do NOT use bash or shell commands.

## Available Tools

- `work_item` — Create any work item (epic, story, bug, chore, docs, PR, MR) on GitHub or GitLab
- `ibm` — Check issue/branch/PR workflow compliance for the current branch

## Usage

Invoke the appropriate MCP tool directly. The tool handles platform detection (GitHub vs GitLab) internally.
