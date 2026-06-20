// wave-status.js — the #688 wave-status persistence seam helper for per-wave-workflow.js.
//
// Design of record: docs/wavemachine-workflows-migration.md §3.3 (resumability) + §6.
// Seam contract: skills/nextwave/SEAMS.md (#688 — wave-status persistence).
//
// WHY A HELPER MODULE: the workflow script cannot call MCP/CLI directly (§3.3) — every
// side-effect is an agent() call. This module owns the two things that make persistence
// honor its contract WITHOUT bloating the loop:
//   1. the canonical DURABLE BLOB shape + path — the exact `{merged, pending, reworkCount,
//      idleRounds, groupsRun}` that rehydrate() (#686) reads back (same shape as REHYDRATE).
//   2. the agent PROMPTS that perform the durable side-effects idempotently:
//        - per newly-merged issue: wave_record_mr + wave_close_issue (sdlc-server)
//        - then overwrite the single per-wave blob file under .claude/status/.
//
// IDEMPOTENCY (SEAMS invariant 5): re-running persistIteration/persistTerminal with the
// same state is a no-op-or-overwrite, never a duplicate side-effect:
//   - wave_record_mr / wave_close_issue are keyed on issue_number → recording an
//     already-recorded MR or closing an already-closed issue is an overwrite/no-op.
//   - the blob is a FULL OVERWRITE of one file per wave → replaying identical state
//     produces a file whose rehydrate-core fields ({merged,pending,reworkCount,idleRounds,
//     groupsRun}) are identical; only the `updatedAt` metadata timestamp may differ.
//   - the terminal record is a single keyed wave-completion entry → overwrite, not append.

// ── Durable location (§3.3 — .claude/status/, NEVER /tmp; lesson_tmp_identity_boot_wipe) ──
// Resume state belongs in the TARGET REPO clone's .claude/status/ (gitignored, durable,
// reboot-surviving), alongside the wave the worktrees attach to.
export const statusDir = (targetRepoDir) => `${targetRepoDir}/.claude/status`

// One blob file per wave. Sanitize the wave id for a filesystem-safe name (W-3 → W-3,
// but a slash-bearing id can't become a path separator).
export const blobPath = (targetRepoDir, waveId) =>
  `${statusDir(targetRepoDir)}/wave-${String(waveId).replace(/[^A-Za-z0-9._-]/g, '_')}.json`

// ── The canonical durable blob (the EXACT shape rehydrate() reads back) ──────────────
// state-in uses Sets + numeric-keyed reworkCount (loop-native). toBlob() normalizes to
// the JSON-round-trippable REHYDRATE shape: integer arrays + a plain object. Keys are
// kept numeric-as-string only where JSON forces it (object keys); rehydrate() Number-casts
// them back (per-wave-workflow.js seeds reworkCount with Number(k)). Arrays stay integers.
export function toBlob(state) {
  const intList = (v) => [...(v ?? [])].map(Number).sort((a, b) => a - b)
  const rework = {}
  for (const [k, v] of Object.entries(state.reworkCount ?? {})) {
    const n = Number(k)
    if (Number.isFinite(n)) rework[String(n)] = Number(v) // string keys: JSON-stable; rehydrate Number-casts
  }
  return {
    waveId: state.waveId ?? null,
    schema: 1, // blob schema version — lets rehydrate() (#686) detect/upgrade old shapes
    updatedAt: state.updatedAt ?? null, // stamped by the persist agent at write time (wall clock)
    // ── the REHYDRATE-shaped loop blob ──
    merged: intList(state.merged),
    pending: intList(state.pending),
    reworkCount: rework,
    idleRounds: Number(state.idleRounds) || 0,
    groupsRun: Number(state.groupsRun) || 0,
    // ── terminal disposition (written by persistTerminal; absent until the wave ends) ──
    terminal: state.terminal ?? null, // { disposition: 'promoted'|'held', detail, at } | null
  }
}

// ── persistIteration agent prompt ───────────────────────────────────────────────────
// Performs BOTH durable side-effects in one agent turn (the script can't do them itself):
//   1. per newly-merged issue, the sdlc-server MCP calls (idempotent),
//   2. the full-overwrite blob write.
// `newlyMerged` is the issues merged THIS iteration that still need their MR recorded +
// issue closed; `blob` is the already-normalized object to write verbatim.
export function persistIterationPrompt({ waveId, targetRepo, kahunaBranch, newlyMerged, blob, path }) {
  return [
    `You are the wave-status PERSISTENCE node for wave ${waveId} of ${targetRepo}. You perform two`,
    `DURABLE, IDEMPOTENT side-effects, then return. Do NOT do any other work.`,
    ``,
    `STEP 1 — per newly-merged issue (record MR + close), idempotent:`,
    `  Newly-merged issues this iteration: [${newlyMerged.join(', ') || 'none'}].`,
    `  For EACH, in order:`,
    `    a. Resolve the merge reference into ${kahunaBranch}: the PR/MR that merged the issue's`,
    `       flight branch (wave-${waveId}/issue-<n>) into ${kahunaBranch}. Use the merge-commit or`,
    `       PR ref if discoverable (gh -R ${targetRepo}); else fall back to the ref "${kahunaBranch}".`,
    `    b. Call wave_record_mr(issue_number=<n>, mr_ref=<resolved ref>). This is keyed on the issue —`,
    `       re-recording an already-recorded issue is an OVERWRITE, not a duplicate. Safe to repeat.`,
    `    c. Call wave_close_issue(issue_number=<n>). Closing an already-closed issue is a NO-OP.`,
    `  If a tool errors, record it in notes and CONTINUE — persistence must not halt the wave.`,
    ``,
    `STEP 2 — write the durable loop blob (full overwrite, idempotent):`,
    `  Write EXACTLY this JSON to the file ${path} (create parent dirs as needed; mkdir -p the`,
    `  .claude/status/ directory first). Overwrite any existing content — do NOT merge or append.`,
    `  This file is the resume substrate rehydrate() (#686) reads back. Write the object EXACTLY as`,
    `  given, changing ONLY the "updatedAt" field to the current ISO-8601 time — every other field verbatim:`,
    ``,
    JSON.stringify(blob, null, 2),
    ``,
    `Return: persisted (true if the blob file was written), recorded (array of issue numbers whose`,
    `MR+close you performed), path ("${path}"), notes (1-2 sentences; include any tool error).`,
  ].join('\n')
}

// ── persistTerminal agent prompt ────────────────────────────────────────────────────
// Records the wave's terminal disposition into BOTH (a) wave-status's wave-completion
// record (so the campaign driver's cold-start rehydrate can prune a promoted wave, §5),
// and (b) the durable blob's `terminal` field (so a resume sees the same disposition).
export function persistTerminalPrompt({ waveId, targetRepo, targetRepoDir, kahunaBranch, protectedBranch, disposition, detail, blob, path, trajectoryEntry }) {
  return [
    `You are the wave-status PERSISTENCE node for wave ${waveId} of ${targetRepo}. Record the wave's`,
    `TERMINAL disposition durably + idempotently, then return. Do NOT do any other work.`,
    ``,
    `Disposition: "${disposition}" (one of promoted | held). Detail: ${JSON.stringify(detail)}.`,
    ``,
    `STEP 1 — wave-completion record (idempotent): record this wave's terminal disposition + detail`,
    `  into the wave-status wave-completion record for ${waveId} (sdlc-server: wave_complete /`,
    `  wave_finalize as appropriate for the store; if neither applies, the blob in STEP 2 is the`,
    `  authoritative record). This is a SINGLE keyed entry per wave — overwrite, never append. The`,
    `  campaign driver's cold-start rehydrate (§5) reads it to prune a 'promoted' wave.`,
    ``,
    `STEP 2 — stamp the durable blob (full overwrite): write EXACTLY this JSON to ${path} (mkdir -p`,
    `  the .claude/status/ dir first; overwrite, do not merge). Its "terminal" field carries the`,
    `  disposition so a resume sees it. Write EXACTLY as given, changing ONLY "updatedAt" and`,
    `  "terminal.at" to the current ISO-8601 time — every other field verbatim:`,
    ``,
    JSON.stringify(blob, null, 2),
    ``,
    `STEP 3 — append this wave's entry to the DURABLE CROSS-WAVE TRAJECTORY (#748 — the #750 wave-`,
    `  oversight judgment seed). The base entry below is authored by the loop; you ADD two best-effort,`,
    `  shell-derived fields, then upsert it. The append is idempotent per wave (keyed on the wave id —`,
    `  re-running OVERWRITES this wave's entry, never duplicates), so it is safe on resume.`,
    `    a. Compute "files_touched": the changed-file set of this wave, i.e. run`,
    `         git -C ${targetRepoDir} diff --name-only ${protectedBranch}...${kahunaBranch}`,
    `       and put the resulting path list (JSON array of strings) on the entry. On any git error,`,
    `       set files_touched to [] and note it — do NOT fail the step.`,
    `    b. Compute "engine_fingerprint": the md5 of the running per-wave-workflow bundle if you can`,
    `       locate it (e.g. md5sum of per-wave-workflow.bundled.js on PATH/cwd); else set it to null.`,
    `       This is a CONFOUND-CONTROL annotation (engine drift mid-campaign), best-effort only.`,
    `    c. Merge a + b into this base entry (every other field verbatim), then upsert it. To avoid`,
    `       ANY shell-quoting hazard — the entry carries free-text concerns/deferrals/detail that`,
    `       routinely contain apostrophes ("doesn't", "can't"), which would break an inline '...'`,
    `       command — WRITE the merged JSON to a temp file (e.g. ${path}.traj.json) and pass that`,
    `       FILE PATH to the CLI (trajectory-append accepts a path OR '-'). Use the deployed`,
    `       'wave-status' console command run FROM the target clone so it resolves the same`,
    `       .claude/status/ that holds the blob above (NOT 'python3 -m wave_status', which only`,
    `       resolves inside the kit repo; the pre-flight 'command -v wave-status' probe guarantees it):`,
    `         printf '%s' <merged-entry-json> > ${path}.traj.json   # write via your file-write tool, not shell`,
    `         cd ${targetRepoDir} && wave-status trajectory-append ${waveId} ${path}.traj.json`,
    `       The upsert is idempotent per wave id (re-running OVERWRITES this wave's entry); the temp`,
    `       file may be left in place or removed.`,
    `       Base entry (do NOT change these fields; only ADD files_touched + engine_fingerprint):`,
    ``,
    JSON.stringify(trajectoryEntry, null, 2),
    ``,
    `Return: persisted (true if the blob was written), disposition ("${disposition}"), path ("${path}"),`,
    `trajectory_appended (true if STEP 3's CLI upsert succeeded), notes (1-2 sentences; include any tool`,
    `error — persistence must NEVER halt the wave, so a soft-fail is a note, not a throw).`,
  ].join('\n')
}
