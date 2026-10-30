// merge-result.js — the merge-result CI rule the trust gates share (cc-workflow#1211).
//
// WHY A MODULE: the campaign release gate (campaign-loop.js, inlined by campaign-bundle.mjs) and
// the per-wave CI signal (gate.js, inlined by bundle.mjs) grade the same question: is this PR/MR's
// merge-result pipeline green on its CURRENT head? Both fall back to a direct GitLab read when
// sdlc-server ci_wait_run gives no verdict. One pure, unit-tested predicate serves both, so the
// binding rule is applied by code instead of being re-stated in two prompts that an agent may read
// generously. A bundler inlines this file ahead of its consumer, so its top-level names must stay
// unique across the bundle.
//
// THE BINDING FACT: a GitLab merged-results pipeline runs on an EPHEMERAL MERGE COMMIT, so its sha
// is not the MR head (sdlc lib/adapters/resolve-merge-anchor-gitlab.ts says the same). On 15 green
// refs/merge-requests/N/merge pipelines across 8 GitLab projects, measured 2026-10-19: sha == MR
// head 0/15, and the commit's parent_ids == [target tip, MR head] 15/15. A rule that asks for
// sha == head can never pass on green. That was #1035 step 2b's rule, which an agent could only
// satisfy by ignoring it. The rule here binds through the merge commit's second parent; a pipeline
// whose sha IS the head (a merge ref that needed no merge commit) is accepted too.
//
// THE HEAD IS READ TWICE (#1211 review): before ci_wait_run and after the last read. A pass needs
// both reads, equal. Read only before, a head that moved during the wait (which ci_wait_run itself
// refuses as not_merge_result) would let the previous head's green /merge pipeline pass. Read only
// after, a ci_wait_run success for the previous head would bind the merge to one CI never graded.

// The evidence an agent returns about one PR/MR's merge-result pipeline. Facts only: what
// ci_wait_run answered, and what a direct GitLab read showed when it gave no verdict. The agent
// never filters or grades them; mergeResultVerdict() does.
export const MERGE_RESULT_EVIDENCE = {
  type: 'object',
  additionalProperties: false,
  required: ['pr_number', 'wait'],
  properties: {
    pr_number: { type: 'integer' },
    pr_ref: { type: 'string' },
    head_sha: { type: 'string' }, // the PR/MR's head, read BEFORE ci_wait_run
    head_sha_final: { type: 'string' }, // the PR/MR's head, read again AFTER the last read
    target_sha: { type: 'string' }, // #1356: the target branch's tip, read last; a merge commit must be built on it
    wait: {
      // ci_wait_run's answer, copied as returned. ok, final_status and (on success) sha are routed on.
      type: 'object',
      additionalProperties: true,
      properties: {
        ok: { type: 'boolean' },
        final_status: { type: 'string' },
        reason: { type: 'string' },
        error: { type: 'string' },
        sha: { type: 'string' }, // the graded run's commit: the PR head (GitHub), or the merge commit (GitLab)
        run_id: { type: 'integer' },
      },
    },
    merge_pipelines: {
      // GitLab: EVERY pipeline the MR lists, unfiltered. The ref filter and newest-wins are code.
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: true,
        properties: {
          id: { type: 'integer' },
          ref: { type: 'string' },
          status: { type: 'string' },
          sha: { type: 'string' },
        },
      },
    },
    merge_commit: {
      // GitLab: the commit of the newest merge-result pipeline, as repository/commits returns it.
      type: 'object',
      additionalProperties: true,
      properties: {
        sha: { type: 'string' },
        parent_ids: { type: 'array', items: { type: 'string' } },
      },
    },
    notes: { type: 'string' },
  },
}

const MERGE_SHA_RE = /^[0-9a-f]{40}([0-9a-f]{24})?$/ // SHA-1, or SHA-256 on a SHA-256 repo
// A full, lowercase commit SHA, as both forges print one. Anything else cannot bind a merge.
export function isMergeSha(s) {
  return typeof s === 'string' && MERGE_SHA_RE.test(s)
}
// ci_wait_run graded a merge-result run bound to the current head and it was red. That is final:
// a direct read never overrides it. Re-running a red gate is cheap; a wrong green is not.
// GitLab's own spellings (failed, canceled) count too, in case an agent copies a status through.
const MERGE_DEFINITIVE_RED = new Set(['failure', 'cancelled', 'failed', 'canceled'])

// The rule. A graded red is final. Any pass needs the head read twice, equal (see THE HEAD IS
// READ TWICE above), and a pass returns that head, so the merge binds to the head that was graded.
// ci_wait_run is the primary path. Its success binds through the run's own sha: the sha IS the
// head, or it is a merge commit whose parents are [target tip, head]. When it gives NO verdict,
// the direct read decides, under four rules, all applied here:
//   1. only a refs/merge-requests/<n>/merge pipeline counts (never a branch or detached /head run);
//   2. the newest of those wins (a green older run must not hide a red newer one);
//   3. it must be green;
//   4. it must be bound to the head: its sha IS the head, or its merge commit has two parents and
//      the second is the head.
// THE TARGET TIP (#1356): wherever the evidence has a merge commit, its FIRST parent must be the
// target branch's tip as read last. A green /merge pipeline built before the target moved tested a
// diff that no longer exists (a reused release PR is the case), so it HOLDs as stale. The limit,
// kept on purpose: GitHub's run API reports a pull_request run's head_sha as the PR head and never
// exposes the test-merge commit it built, so on GitHub a pass binds to the head only, as before.
// No verdict means empty, ok=false with no final_status ("No CI run found", the sdlc#585
// signature), timed_out, not_merge_result, or anything unrecognised. Every gap HOLDs.
export function mergeResultVerdict(ev) {
  const hold = (path, reason) => ({ pass: false, path, reason })
  const n = ev?.pr_number
  if (!Number.isInteger(n) || n <= 0) {
    return hold('none', `no PR/MR number${ev?.error ? ` (the evidence node errored: ${ev.error})` : ''}, so there is no pipeline to grade`)
  }
  const fs = ev.wait?.final_status
  if (MERGE_DEFINITIVE_RED.has(fs)) {
    return hold('ci_wait_run', `ci_wait_run graded the merge-result pipeline ${fs}; a direct read never overrides a graded red`)
  }
  const head = ev.head_sha
  if (!isMergeSha(head) || !isMergeSha(ev.head_sha_final)) {
    return hold('none', 'the head SHA was not read, well-formed, both before ci_wait_run and after the last read, so nothing graded can be bound to it')
  }
  if (ev.head_sha_final !== head) {
    return hold('none', `the head moved during grading (${head.slice(0, 8)} → ${ev.head_sha_final.slice(0, 8)}), so what was graded may be the previous head's pipeline`)
  }
  const target = ev.target_sha
  if (!isMergeSha(target)) {
    return hold('none', 'the target tip was not read, so the merge result cannot be bound to it')
  }
  // A merge commit binds when it has exactly [target tip, head] as parents. `bound` is the head
  // half; `stale` names a commit that merges the head into a target tip that has since moved.
  const parents = (c, sha) => (c?.sha === sha && Array.isArray(c.parent_ids) && c.parent_ids.length === 2 ? c.parent_ids : null)
  const stale = (path, p0) => hold(path, `STALE: the merge-result pipeline was built on target ${p0.slice(0, 8)}, and the target is now ${target.slice(0, 8)}. Re-run the MR pipeline to re-grade it`)
  if (ev.wait?.ok === true && fs === 'success') {
    const ws = ev.wait.sha
    if (!isMergeSha(ws)) {
      return hold('ci_wait_run', "ci_wait_run's success names no run sha, so the graded run cannot be bound to the head")
    }
    if (ws !== head) {
      const p = parents(ev.merge_commit, ws)
      if (!p || p[1] !== head) {
        return hold('ci_wait_run', `ci_wait_run's green run ${ws.slice(0, 8)} is not the head ${head.slice(0, 8)}, and no merge commit read for it has the head as its second parent`)
      }
      if (p[0] !== target) return stale('ci_wait_run', p[0])
    }
    return { pass: true, path: 'ci_wait_run', head, reason: `ci_wait_run: the merge-result pipeline is green on the head ${head.slice(0, 8)}` }
  }
  const err = ev.wait?.error ? `: ${String(ev.wait.error).slice(0, 160)}` : ''
  const why = !ev.wait ? 'no answer' : fs ? `final_status=${fs}` : `not found${err}`
  const want = `refs/merge-requests/${n}/merge`
  const runs = (Array.isArray(ev.merge_pipelines) ? ev.merge_pipelines : []).filter((p) => p?.ref === want)
  // A merge-result run without an integer id cannot be ordered, so newest-wins cannot be applied:
  // dropping it could let an older green hide it. Hold instead.
  if (runs.some((p) => !Number.isInteger(p.id))) {
    return hold('direct', `ci_wait_run gave no verdict (${why}), and a ${want} pipeline has no integer id, so the newest cannot be determined`)
  }
  if (runs.length === 0) {
    return hold('direct', `ci_wait_run gave no verdict (${why}), and the direct read found no ${want} pipeline`)
  }
  const newest = runs.reduce((a, b) => (b.id > a.id ? b : a))
  const label = `the newest ${want} pipeline, #${newest.id}`
  if (newest.status !== 'success') {
    return hold('direct', `ci_wait_run gave no verdict (${why}); ${label}, is ${newest.status ?? 'without a status'}`)
  }
  if (!isMergeSha(newest.sha)) {
    return hold('direct', `${label} is green, but its sha is missing or malformed, so it cannot be bound to the head`)
  }
  const p = parents(ev.merge_commit, newest.sha)
  if (newest.sha !== head && (!p || p[1] !== head)) {
    return hold('direct', `${label} is green but not bound to the head ${head.slice(0, 8)}: its sha is not the head, and its merge commit's second parent is not the head. It is a stale run`)
  }
  if (newest.sha !== head && p[0] !== target) return stale('direct', p[0])
  return {
    pass: true,
    path: 'direct',
    head,
    reason: `ci_wait_run gave no verdict (${why}); ${label}, is green and ${newest.sha === head ? 'is' : 'merges'} the head ${head.slice(0, 8)}`,
  }
}

// The head-SHA read, phrased once. Both gates ask for it twice: first, and again after the last
// read (THE HEAD IS READ TWICE, above). `field` names the evidence property it fills.
export function headReadLines({ targetRepo, prNumber, field }) {
  const n = prNumber != null ? prNumber : '<n>'
  return [
    `Read the PR/MR's head SHA NOW and report it as ${field}, exactly as read:`,
    `  GitHub: gh -R ${targetRepo} pr view ${n} --json headRefOid -q .headRefOid`,
    `  GitLab: glab api "projects/<url-encoded ${targetRepo}>/merge_requests/${n}" | jq -r '.diff_refs.head_sha // .sha'`,
  ]
}

// The target-tip read (#1356), phrased once. Both gates ask for it last, after the final head read,
// so a merge commit built on an older tip is caught. `field` names the evidence property it fills.
export function targetReadLines({ targetRepo, branch, field }) {
  return [
    `Read the TARGET branch ${branch}'s tip NOW and report it as ${field}, exactly as read:`,
    `  GitHub: gh api repos/${targetRepo}/branches/${branch} --jq .commit.sha`,
    `  GitLab: glab api "projects/<url-encoded ${targetRepo}>/repository/branches/<url-encoded ${branch}>" | jq -r .commit.id`,
  ]
}

// The direct-read steps, phrased once so every gate that gathers this evidence asks for the same
// facts in the same shape.
export function directMergeReadSteps({ targetRepo, prNumber, windowSec = 600 }) {
  const n = prNumber != null ? prNumber : '<n>'
  const enc = `<url-encoded ${targetRepo}>`
  return [
    `MERGE COMMIT OF A GRADED GREEN (#1356, GitLab only). Whenever ci_wait_run returned success with a`,
    `sha that is not the head, read that sha's commit and report it as merge_commit:`,
    `      glab api "projects/${enc}/repository/commits/<that sha>" | jq '{sha: .id, parent_ids}'`,
    `DIRECT READ (#1211, GitLab only). Do this ONLY when ci_wait_run gave NO verdict: ok=false with no`,
    `final_status (e.g. "No CI run found", the sdlc#585 signature), or final_status timed_out or`,
    `not_merge_result (GitLab's head_pipeline lags, or names the detached /head pipeline). Skip it when`,
    `ci_wait_run returned success, failure or cancelled: a graded result is final. On GitHub, skip it.`,
    `  • List EVERY pipeline the MR has, unfiltered, and report them as merge_pipelines:`,
    `      glab api "projects/${enc}/merge_requests/${n}/pipelines?per_page=100" | jq '[.[] | {id, ref, status, sha}]'`,
    `  • Take the NEWEST (highest id) whose ref is "refs/merge-requests/${n}/merge". If it is still`,
    `    created/pending/running, re-read every ~20s for up to ~${windowSec}s, then report what you last read.`,
    `  • Read that pipeline's commit and report it as merge_commit:`,
    `      glab api "projects/${enc}/repository/commits/<its sha>" | jq '{sha: .id, parent_ids}'`,
    `  A merged-results pipeline runs on an EPHEMERAL MERGE COMMIT: its sha is not the MR head, and its`,
    `  parents are [target tip, MR head]. The gate binds it to the head through those parents, so`,
    `  report them exactly as read. Never substitute a SHA you did not read, and never filter or`,
    `  judge: code applies the rules (merge-result ref only, newest wins, green, bound to the head).`,
  ]
}
