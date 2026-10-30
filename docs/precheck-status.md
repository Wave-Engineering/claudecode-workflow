# The `precheck` commit status

The contract between the kit, which **produces** the mark, and everything that **consumes** it. Change this file first, then the code.

`/precheck` is the MR gate (#1233, #1235). A pass is recorded on the commit it reviewed, as a commit status.

## The status

| field | value |
|---|---|
| GitHub | a commit status (`POST /repos/{owner}/{repo}/statuses/{sha}`) with `context` = `precheck` |
| GitLab | a commit status (`POST /projects/:id/statuses/:sha`) with `name` = `precheck`, attached to the SHA's existing pipeline through `pipeline_id` when one exists |
| state | `success`. No pass means no status. The one exception is the merged-results guard below, which posts `failed` to refuse a pass, replacing any `success` on the head. |
| description | one line, 140 characters or fewer. It names the issue, the review passes and where the lane results came from, for example `#1235 review full+delta clean; lanes ci; trivy 0` |
| SHA | the HEAD that was reviewed. It must already be pushed. |

**Why GitLab passes `pipeline_id`:** a bare status post makes GitLab create a separate "external" pipeline. That pipeline can become the MR's latest pipeline and hide the real CI verdict from the merge check.

**Merged-results MRs (#1357):** the head SHA has no pipeline there, because MR pipelines run on an ephemeral merge commit. So the post is bare by necessity. It still goes on the head, because every reader keys on the head. Before posting, `precheck-status.sh post` reads `head_pipeline` for each open MR at that head. GitLab moves `head_pipeline` in an async worker, so after the read-back the script polls it again: 6 reads, 5 seconds apart (`PRECHECK_HP_POLLS`, `PRECHECK_HP_STEP_SEC`). If one moves in that window, it replaces the `success` with `failed` on the same context and exits 3, so the head carries no pass. What is guaranteed is only that window: a move later than about 30 seconds after the post is not seen.

The guard refuses a pass in three more cases, each by putting `failed` on the head and exiting 3:

- **Already external before the post.** An open MR's `head_pipeline` is an external pipeline, so its CI verdict is already hidden. Nothing but the `failed` status is posted. Re-run the MR pipeline to recover.
- **External during the poll.** A poll reads `head_pipeline` as an external pipeline, whether or not its id moved.
- **A failed re-read.** The MR can't be read during the poll, so the guard can't vouch for the pass.

A `head_pipeline` whose source can't be told counts as external. The pipeline lookup that picks `pipeline_id` skips external pipelines, and pipelines with no source, because after an earlier bare post the newest pipeline for the head is our own external one. If none is left, the post takes the guarded bare path. The `failed` post is tried 3 times. If it still fails, the script says on stderr that the `success` on the head still stands and is not a pass, and exits 3. That `success` must be replaced before the PR/MR is marked ready.

## Reading it

A consumer treats the mark as present **only** when the latest `precheck` status on the exact head SHA is `success`.

- No status, `pending`, `failure`/`error` (GitHub), or `failed`/`canceled` (GitLab) all mean **no pass**.
- A status on an older SHA is no pass either. A push after precheck makes the mark stale by construction.
- A read that fails (an API error or timeout) is **no pass**. Every consumer fails closed.

## Producer and consumers

- **Producer:** `scripts/precheck-status.sh post <repo_root> <sha> <description>`, called by `/precheck` on a pass and by `/precheck rearm` on a clean delta. It reads the status back after posting.
- **Read helpers:**
  - `precheck-status.sh get <repo_root> <sha>` prints `success`, `pending`, `failure` or `none`, and exits 3 on an API error.
  - `precheck-status.sh last-success <repo_root> <base>` prints the newest first-parent commit on the branch that carries a pass. `/precheck rearm` diffs from it.
  - `precheck-status.sh pr-head <repo_root> [<number|url|branch>]` prints a PR/MR as the platform sees it: `<sha> <head-branch> <base-branch>`.
  - `precheck-status.sh branch-head <repo_root> <branch>` prints where a branch points on the platform, which is what a create from it opens with. It exits 3 if the branch can't be read, including a branch that was never pushed.
  - `PRECHECK_SLUG` (with `PRECHECK_PLATFORM`, and optionally `PRECHECK_HOST`) points any of these at another repository, the `-R` case.
  - GitLab reads fail on an error **body** as well as on an exit code, because `glab api` exits 0 on an HTTP error (mcp-server-sdlc#502).
- **Marking ready:** `precheck-status.sh mark-ready <repo_root> <number>` is the kit's one way to make a PR/MR ready. It refuses (exit 4) unless the head carries a pass, then reads the PR/MR back. On GitHub it runs the GraphQL `markPullRequestReadyForReview` mutation (REST has no endpoint for it). On GitLab it PUTs the title with every draft prefix stripped. `/precheck` uses it; nothing in the kit makes a PR/MR ready through `gh pr ready` or `glab mr update`, except the wave engine's integration-branch promotions noted below.
- **Consumers:**
  - `scripts/hooks/workflow/pr-ready-gate.sh` gates the CLI path: `gh pr create` and `gh pr ready`, `glab mr create`, and **every** `glab mr update` without `--draft`. On GitLab the draft state *is* the title prefix (`Draft:`, `[Draft]`, `(Draft)`), and glab rewrites the title on most update flags (`--title`, `--fill`, `--wip`, …), so the gate doesn't model which flags keep it. (`WIP:` and glab's `--wip` haven't counted as drafts since GitLab 14.0.) It checks the PR/MR's own head, read through `pr-head` (or, for a create, `branch-head`), never local HEAD or the local `origin/<branch>`. It is a guard rail for the spellings agents write, not a boundary: an unusual argv spelling or `gh api` gets past it, and the merge-time checks below are the backstop.
  - **mcp-server-sdlc, from the release that carries #592**, gates the MCP path. `pr_create` (non-draft) and `pr_ready` check the head SHA, and `pr_merge` re-checks it at merge time and pins the merge to it. It also squashes from the body's `## Squash commit` block, which `pr_create` writes from `squash_message`. An older server enforces nothing on the MCP path. Neither does `gh pr merge` or `glab mr merge`, so there `/precheck` and `/mmr` checking it is the only gate.
- **Drafts never need the mark.** A draft can't merge.
- **Integration branches are exempt.** A head on `kahuna/*` (wave promotion) or `campaign/*` (campaign → protected), or a **base** on `kahuna/*` (a flight landing into its wave's integration branch), is governed by the wave trust gate: commutativity, merge-result CI, code review and trivy. Nothing reaches a protected branch from `kahuna/*` except through it. This is the same rule as the push gate's integration refs (#724) and the kahuna sandbox auto-approval. The wave engine marks promotion drafts ready itself (`gh -R <repo> pr ready <n>`), and its prime node lands flights with `pr_create` + `pr_merge`.

## Release order

The producer ships before the consumers. If a consumer that requires the mark ships first, every PR is refused until the kit catches up. If the kit ships first, the mark is simply posted and ignored for a while.

The same holds for the squash commit (#1257). The kit passes `squash_message` only to a server whose `pr_create` schema lists it, because an older schema rejects the field, and never on an integration pair, which the gate exempts. `/mmr` merges from the block only for a gated PR/MR on a gated server. In every other case it drafts the message, as it did before. So a kit released first works against both servers, and the mcp-server-sdlc #592 release comes after it. One edge remains: a PR/MR opened on a gated server and merged after a downgrade to an older server takes `/mmr`'s drafted message, because that server never reads the block.
