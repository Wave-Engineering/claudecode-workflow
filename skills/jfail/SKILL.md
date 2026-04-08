---
name: jfail
description: Fetch and analyze a failed CI job (GitLab) or workflow run (GitHub)
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-jfail does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-jfail
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# CI Failure Analysis

Fetch and summarize a failed CI run without flooding the parent context. Works on GitHub Actions and GitLab CI — the tools normalize the platform.

## Tools Used

- `mcp__sdlc-server__ci_run_status` — resolve `latest` (optionally on a branch) to a run
- `mcp__sdlc-server__ci_failed_jobs` — list failing jobs for a run
- `mcp__sdlc-server__ci_run_logs` — fetch failed-only log content (truncated) for a job

## Arguments

{{#if args}}
`{{args}}` — numeric run ID, `latest`, or `latest <branch>`.
{{else}}
No argument → default to `latest` on the current branch.
{{/if}}

## Step 1: Parse arguments

Decide mode: numeric `run_id` vs. `latest` (with optional branch). For bare `latest`, use `git branch --show-current`.

## Step 2: Resolve run, find failed job, fetch logs

1. `latest` mode → `ci_run_status({ref: <branch>})`; if not a failure, stop and report. Numeric mode → use the given id.
2. `ci_failed_jobs({run_id})`. If empty, report "no failed jobs" and stop. Pick the first failed `job_id`.
3. `ci_run_logs({run_id, job_id, failed_only: true})` → returns normalized metadata (name, ref, url, conclusion, truncation) and log content as a string.

If any tool errors (invalid ID, wrong repo, 404), report and stop — no shell fallback, no guessing.

## Step 3: Analyze with sub-agent

Launch a sub-agent (`subagent_type: general-purpose`, `model: haiku`) with the log content appended to the prompt. If content is very large (>200 KB), spill to `/tmp/jfail-<run_id>-<job_id>.out` and pass the path instead — agent's judgment. Prompt:

> Analyze the CI failure log (appended / at the given path). The parent agent will only see your summary.
>
> 1. Strip ANSI codes (`[0K`, `[36;1m`, etc.).
> 2. Classify as: `test-failure` / `lint-error` / `build-error` / `dependency-error` / `deploy-error` / `infrastructure` / `script-error` / `unknown`.
> 3. Extract error sections (contiguous blocks with context). ≤30 lines → full; >30 → first 15 + last 15 with `... [N lines omitted] ...`.
> 4. Extract actionable details — file:line, failing test names, exact failing command, exit codes.
> 5. Return exactly:
>    ```
>    CLASSIFICATION: <type>
>    SUMMARY: <one sentence>
>    ERROR SECTIONS:
>    ---
>    <section>
>    ---
>    ACTIONABLE:
>    - <file:line / test / command>
>    ```
>
> Skip setup/cache/install noise unless directly relevant.

## Step 4: Present results

Using the metadata from `ci_run_logs`, show `**Workflow/Job:** <name> — [link](<url>)` and `**Ref:** <ref> | **Conclusion:** <conclusion>`, then the sub-agent's CLASSIFICATION / SUMMARY / ERROR SECTIONS / ACTIONABLE. If `ci_run_logs` reports truncation, append `> Logs truncated by ci_run_logs.` If spilled to a file, append `> Full log: /tmp/jfail-<run_id>-<job_id>.out`.

## Important

- Sub-agent does the heavy reading; parent stays clean. `model: haiku` — summarization, not reasoning.
- Tool failure → report and stop. No shell fallback.
