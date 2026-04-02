---
name: jfail
description: Fetch and analyze a failed CI job (GitLab) or workflow run (GitHub)
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/skill-intro-jfail does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/skill-intro-jfail
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# CI Job/Workflow Failure Analysis

Fetch and summarize a failed CI job's output without flooding the parent context window.

Supports both **GitLab CI** (jobs) and **GitHub Actions** (workflow runs).

## Detect Platform

Before any other step, detect the platform:

```bash
REMOTE_URL=$(git remote get-url origin 2>/dev/null)
if echo "$REMOTE_URL" | grep -qi github; then
  PLATFORM="github"
elif echo "$REMOTE_URL" | grep -qi gitlab; then
  PLATFORM="gitlab"
else
  echo "Unknown platform — ask the user"
fi
```

## Arguments

{{#if args}}
Job/run identifier: `{{args}}`
- If numeric, treat as a job ID (GitLab) or workflow run ID (GitHub)
- If "latest", find the most recent failed job/run on the current branch
- If "latest <branch>", find the most recent failed job/run on that branch
- A repo path may be included anywhere: `/path/to/repo <job-id>` or `<job-id> /path/to/repo`
{{else}}
No argument provided. Use `latest` to find the most recent failed job/run on the current branch.
{{/if}}

## Workflow

### Step 1: Parse arguments

From the args `{{args}}`, determine:
- **Job/run identifier**: the numeric ID or "latest" (with optional branch)
- **Repo path**: if a filesystem path is included (starts with `/` or `~` or `.`), use it as the `-C` flag (GitLab) or `--repo` context. If the current working directory is already a git repo for the correct project, no extra flag is needed.

### Step 2: Fetch job/run output

#### GitLab

Run `job-fetch [-C /path/to/repo] <job-id|latest> [branch]` using the Bash tool. This writes the full job trace to `/tmp/<job-id>.out` and prints metadata to stdout.

If `job-fetch` returns a 404, the job likely belongs to a different project. Tell the user and ask which repo to use.

Parse the metadata lines from stdout — they are `KEY=VALUE` pairs:
- `JOB_ID`, `JOB_NAME`, `STAGE`, `STATUS`, `REF`, `PIPELINE`, `URL`, `FAILURE_REASON`, `DURATION`, `FINISHED_AT`, `OUTPUT_FILE`, `LINE_COUNT`

#### GitHub

Use `gh` CLI to fetch failed workflow run logs:

1. **Find the failed run** (if "latest"):
   ```bash
   BRANCH=$(git branch --show-current)
   gh run list --branch "$BRANCH" --status failure --limit 1 --json databaseId,name,conclusion,headBranch,url,createdAt
   ```
   If a specific run ID was given, use it directly.

2. **Fetch the run details:**
   ```bash
   gh run view <run-id> --json jobs,name,conclusion,url,headBranch,createdAt
   ```

3. **Download the logs:**
   ```bash
   gh run view <run-id> --log-failed > /tmp/<run-id>.out 2>&1
   ```

4. **Build metadata** from the JSON output:
   - `RUN_ID`, `WORKFLOW_NAME`, `STATUS`, `REF` (headBranch), `URL`, `FAILURE_REASON` (conclusion), `OUTPUT_FILE`, `LINE_COUNT`

If no failed runs are found, tell the user and stop.

### Step 3: Analyze with sub-agent

Launch a sub-agent (subagent_type: `general-purpose`, model: `haiku`) to read and analyze the job output. Pass it this prompt:

---

Read the CI job output file at `[OUTPUT_FILE path from step 2]`.

Your job is to produce a concise failure summary for the parent agent who needs to diagnose and fix the issue. The parent agent WILL NOT see the raw output — only your summary.

**Do the following:**

1. **Strip ANSI codes** — The file contains terminal escape sequences (`[0K`, `[36;1m`, etc.). Ignore them when reading.

2. **Classify the failure** into one of:
   - `test-failure` — pytest/junit/test runner reports failing tests
   - `lint-error` — ruff, black, shellcheck, mypy, checkstyle
   - `build-error` — compilation, package build, Docker/Kaniko build failure
   - `dependency-error` — pip, npm, maven dependency resolution
   - `deploy-error` — deployment script failure
   - `infrastructure` — runner issues, timeout, OOM, network
   - `script-error` — shell script failure (exit code, unset variable, command not found)
   - `unknown` — none of the above

3. **Extract error sections** — Find contiguous blocks of output that contain the actual error. Include enough surrounding context to understand what command or step triggered the error (typically a few lines before the error starts). For each error section:
   - If the section is 30 lines or fewer, include it in full
   - If longer than 30 lines, include the first 15 lines and last 15 lines with a `... [N lines omitted] ...` marker between them

4. **Extract actionable details:**
   - File paths and line numbers mentioned in errors
   - Failing test names
   - The specific command that failed
   - Any error codes or exit codes

5. **Return your analysis in this format:**

```
CLASSIFICATION: <type>
SUMMARY: <one-sentence description of what went wrong>

ERROR SECTIONS:
---
<section 1 with context>
---
<section 2 if applicable>
---

ACTIONABLE:
- <specific file:line or test name or command>
- <etc>
```

Do NOT include the full job output. Do NOT include successful steps (setup, cache, dependency install) unless they are directly relevant to the failure. Be concise but complete — the parent agent should be able to start fixing the issue immediately from your summary alone.

---

### Step 4: Present results

After the sub-agent returns, present the analysis to the user with this structure:

#### GitLab
**Job:** `<JOB_NAME>` (stage: `<STAGE>`) — [link](<URL>)
**Ref:** `<REF>` | **Duration:** `<DURATION>s` | **Reason:** `<FAILURE_REASON>`

#### GitHub
**Workflow:** `<WORKFLOW_NAME>` — [link](<URL>)
**Ref:** `<REF>` | **Conclusion:** `<FAILURE_REASON>`

Then include the sub-agent's classification, summary, error sections, and actionable items.

End with:
> Full output: `<OUTPUT_FILE>` (<LINE_COUNT> lines)

## Important

- The sub-agent does the heavy reading so the parent context stays clean
- **GitLab:** If `job-fetch` fails (wrong project, invalid ID), report the error and stop — do not guess. Job IDs are project-specific. A 404 means the job belongs to a different project — ask the user which repo
- **GitHub:** If `gh run view` fails, the run ID may be wrong or the repo may not match — report the error and stop
- Use `model: haiku` for the sub-agent to minimize cost — this is a summarization task, not a reasoning task
