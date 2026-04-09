---
name: ibm
description: Verify Issue → Branch → PR/MR workflow compliance via MCP tool
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-ibm does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-ibm
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# IBM: Issue → Branch → PR/MR Workflow Check

## Tools Used
- `mcp__sdlc-server__ibm` — checks branch/issue compliance, platform detection, target branch resolution. All logic is server-side.

## Procedure

1. Call `ibm()` with no arguments. The tool detects platform, validates branch naming, verifies issue linkage, and resolves the target branch — all internally.
2. If it returns errors or remediation steps, present them and **STOP**.
3. If it passes, report the result (platform, issue number, branch, target) and continue.

## Remember

- **No commits without an issue**
- **No pushes without a branch**
- **No merges without a PR/MR**
- **Always target the branch the tool resolves** — never override with a guess
