// campaign-loop.js — the #749 deterministic auto-mode campaign loop (pure core).
//
// Design of record: docs/campaign-workflow-design.md §2 ("control flow is code; judgment is a
// seam") + §6.1. Seeds the wave-oversight judgment agent (§3/§4) from the durable cross-wave
// trajectory (#748) — see [[project_wave_oversight_failure_catalog]] for the lens.
//
// WHY A PURE CORE MODULE (mirrors wave-status.js / gate.js): a Dynamic Workflow file uses
// top-level `return`/`await` and so cannot be imported by a node test. The deterministic halves
// of the campaign loop — args parse, cold-start rehydrate/prune, verdict + judgment routing, and
// the loop DRIVER itself (with its real side-effects injected as seams) — live here so they are
// UNIT-TESTABLE in isolation, then `campaign-bundle.mjs` inlines them into the single-file
// artifact `campaign-workflow.bundled.js` the Workflow tool invokes.
//
// THE KEY SEAM: `runCampaign` takes `runWave` (launch the per-wave spine) and `judge` (call the
// wave-oversight sub-agent) as INJECTED async functions. The Workflow entrypoint injects the real
// `workflow()` / `agent()` calls; the tests inject scripted fakes — so #749's "multi-wave advances
// on PASS+integrated+continue, ends on a HOLD/flag" procedures are deterministic unit tests, not
// integration runs. No LLM in the loop CONTROL FLOW ⇒ it provably cannot stall (#736 dissolves).

// ── args intake (same contract as per-wave-workflow.js #1/#3: the runtime global is `args`,
//    which may arrive as an object OR a JSON string from tool-call quoting) ──────────────────
export function parseArgs(raw) {
  if (raw == null) return {}
  if (typeof raw === 'string') {
    const s = raw.trim()
    if (!s) return {}
    try {
      return JSON.parse(s)
    } catch (e) {
      throw new Error(`campaign-workflow: \`args\` is a string but not valid JSON: ${e?.message || e}. Pass args as a JSON OBJECT.`)
    }
  }
  if (typeof raw === 'object') return raw
  throw new Error(`campaign-workflow: \`args\` must be an object or JSON string, got ${typeof raw}.`)
}

// ── BRANCH TOPOLOGY (#1052 — one campaign branch all the way through) ────────────────────────
//
// TWO LEVELS, TWO NAMES. A campaign writes the protected branch EXACTLY ONCE, at the DoD gate:
//
//   protected ──┬──────────────────────────────────────────────────────► (one merge, at DoD)
//               │                                                      ▲
//               └─► campaign/<plan>-<slug> ──W1──W2──W3── … ──WN ──────┘
//                        ▲         ▲        ▲
//                     kahuna/<plan>-<waveId>  (one per wave, disposable)
//
// WHY (BJ, 2026-07-26): waves 1..N-1 landed on the protected branch are a half-delivered feature
// wearing a released commit's clothes. It is not an increment until the DoD is met. Three costs of
// the interim merge-back: (1) an abort at wave 4 of 7 must REVERT four promoted waves from trunk
// history instead of deleting one unmerged branch; (2) everyone else working from the protected
// branch pulls half-finished work; (3) it is not a real increment, so calling it one is a lie the
// board tells. The single merge at DoD removes all three by construction.
//
// WHY THIS DISSOLVES #892 (rather than needing a better merge method). #892 is "squash-merge +
// a long-lived integration branch are incompatible": the squash rewrites history the persistent
// kahuna still carries, so wave 2's promotion hits add/add. Here every wave gets a FRESH
// DISPOSABLE kahuna cut off the campaign branch, and nothing continues from it after it lands —
// so a squash is harmless, and there is no interim merge-back for the protected branch to
// diverge from either. The failure mode is unreachable, not mitigated. `preserveKahuna` (#722)
// therefore has nothing left to express in campaign mode: the branch that persists is the
// CAMPAIGN branch, and the per-wave kahuna is disposable again as it was originally.
//
// WHY THE PREFIXES DIFFER (a git constraint, verified empirically, not a style choice). The
// tempting name for a wave branch is a child of the campaign branch — `kahuna/56-plan/w1` under
// `kahuna/56-plan`. That ref is IMPOSSIBLE: git stores branches as files under refs/heads/, so a
// branch cannot be a directory prefix of another branch. Reproduced locally:
//     $ git branch kahuna/56-plan && git branch kahuna/56-plan/w1
//     fatal: cannot lock ref 'refs/heads/kahuna/56-plan/w1':
//            'refs/heads/kahuna/56-plan' exists; cannot create 'refs/heads/kahuna/56-plan/w1'
// Distinct top-level prefixes (`campaign/` vs `kahuna/`) put the two levels in separate
// namespaces, so the D/F conflict cannot arise at any nesting depth. Do NOT "tidy" these into
// one prefix — it re-creates an unrepresentable ref.
const safeRef = (s) => String(s ?? '').replace(/[^A-Za-z0-9._-]/g, '-').replace(/^-+|-+$/g, '')

// The campaign branch: cut off the protected branch once, at campaign start; merged to protected
// once, at the DoD gate. Lives for the whole campaign.
//
// LOWERCASED. The slug comes from a plan title, so it arrives mixed-case, and git refs ARE
// case-sensitive while macOS/Windows checkouts are not — `campaign/56-Blueshift` and
// `campaign/56-blueshift` are two refs that cannot coexist in one working tree. Since the whole
// point of this name is that a resume recomputes it identically, a case-only difference between a
// plan title and its restatement would silently start a SECOND campaign. Lowercase removes the
// axis.
export function campaignBranchFor({ planId, slug } = {}) {
  const p = safeRef(planId)
  const s = safeRef(slug)
  if (!p || !s) throw new Error(`campaignBranchFor: need both planId and slug, got ${JSON.stringify({ planId, slug })}`)
  return `campaign/${p}-${s}`.toLowerCase()
}

// A wave's integration branch: cut off the CAMPAIGN branch, merged into it, then deleted.
// Disposable — see the #892 note above for why that is now safe.
//
// The waveId is kept VERBATIM (unlike the campaign slug above): wave ids are engine-generated
// (`W-1`), not human-typed, so there is no case-drift to guard against. And it must stay verbatim
// so ONE wave has ONE spelling everywhere — resume.js embeds the same id, sanitized but not
// lowercased (`safeWaveId`), in every flight branch (`<type>/<n>-<waveId>-<slug>`) and in the
// terminal cleanup glob that matches them. Lowercasing only here would split a single wave's
// branch names across two casings for no gain.
export function waveKahunaFor({ planId, waveId } = {}) {
  const w = safeRef(waveId)
  if (!w) throw new Error(`waveKahunaFor: need a waveId, got ${JSON.stringify(waveId)}`)
  const p = safeRef(planId)
  return p ? `kahuna/${p}-${w}` : `kahuna/${w}`
}

// ── cold-start rehydrate / prune (§6.1 step 3, reboot-proof) ─────────────────────────────────
// Given the campaign's full ordered wave list and the set of wave ids already INTEGRATED (read
// back from durable wave-status on cold start), return the pending waves IN ORDER. Pure: a reboot
// at wave 5 prunes waves 1–4 and resumes at 5. Idempotent — re-running with the same integrated
// set yields the same pending list.
//
// #1052: the pruning predicate is INTEGRATED (landed on the campaign branch), NOT released
// (landed on protected). Under the single-merge shape nothing is released until every wave is
// integrated, so a released-keyed prune would never prune anything and every resume would re-run
// the whole campaign. This is one of the four `promoted` consumers the split had to reach.
export function computePending(allWaves, integratedWaveIds) {
  const integrated = new Set((integratedWaveIds ?? []).map(String))
  return (allWaves ?? []).filter((w) => !integrated.has(String(waveIdOf(w))))
}

// A wave entry may be a bare id or an object carrying {id|waveId|wave, issues, ...}. One accessor
// so the loop never cares which shape the plan used.
export function waveIdOf(wave) {
  if (wave == null) return null
  if (typeof wave === 'object') return wave.id ?? wave.waveId ?? wave.wave ?? null
  return wave
}

// ── verdict routing (§6.1 step 1) — the per-wave spine's {gate, integrated} return ────────────
//
// #1052 — THE `promoted` SPLIT. `promoted` used to mean one thing because there was one merge per
// wave and it went to the protected branch. Under the single-merge shape those are two different
// events, and conflating them is a correctness bug in both directions:
//
//   integrated — the wave landed on the CAMPAIGN branch. Per-wave. Gates advancing to wave N+1,
//                and is the prune predicate on resume.
//   released   — the CAMPAIGN landed on the protected branch. Once, at the DoD gate. Gates
//                closing issues (#1046) and is the only thing that means "delivered".
//
// A wave that is integrated-but-not-released is the NORMAL mid-campaign state, not a failure —
// which is exactly why the old `promoted`-keyed router would hold every wave forever here.
//
// COMPATIBILITY, and why it is not merely defensive: an in-flight campaign launched by the
// PREVIOUS engine returns `{promoted:true}` from a wave whose spine promoted straight to the
// protected branch, and a resumed campaign can mix old and new records in one trajectory. Reading
// `integrated ?? promoted` treats the old field as what it factually was — that wave DID land
// somewhere the next wave can build on — so a mid-campaign engine upgrade advances instead of
// stalling. (Catalog F: engine drift mid-campaign is a real event, not a hypothetical.)
export function isIntegrated(verdict) {
  if (verdict?.integrated != null) return verdict.integrated === true
  return verdict?.promoted === true // legacy record (pre-#1052 engine) — landed, per the shape of its day
}

// ADVANCE only on a wave that PASSED its trust gate AND actually landed on the campaign branch.
// A PASS that did not land (interactive, or a merge that did not complete) HOLDs — the campaign
// never builds the next wave on a baseline that never landed (catalog signal I: "promoted ≠
// delivered"). Anything else (HOLD/SKIPPED) HOLDs.
export function routeVerdict(verdict) {
  const gate = verdict?.gate ?? null
  const integrated = isIntegrated(verdict)
  if (gate === 'PASS' && integrated) return { advance: true, reason: 'gate PASS and integrated onto the campaign branch' }
  if (gate === 'PASS' && !integrated) {
    return { advance: false, reason: `gate PASS but NOT integrated (${verdict?.reason || 'did not land on the campaign branch'}) — campaign holds rather than build on an un-landed baseline` }
  }
  return { advance: false, reason: `gate ${gate ?? 'UNKNOWN'}${verdict?.reason ? `: ${verdict.reason}` : ''}` }
}

// ── judgment routing (§6.1 step 1 / §2.2) — the wave-oversight sub-agent's verdict ───────────
// ADVANCE only on an explicit continue:true. Anything else — a flag, a malformed/absent verdict —
// HOLDs (absence of a clear "continue" is not a license to proceed; same conservative stance as
// the per-wave trust gate, SEAMS invariant 6).
export function routeJudgment(judgment) {
  if (judgment?.continue === true) return { advance: true, reason: 'judgment: continue' }
  const what = judgment?.concern?.what
  return { advance: false, reason: what ? `judgment flagged: ${what}` : 'judgment did not return continue:true — campaign holds (conservative)' }
}

// ── the loop DRIVER (pure given its injected seams) ──────────────────────────────────────────
// runWave(wave, index)  → Promise<verdict>   (the per-wave spine; verdict carries {gate, integrated}
//                                             — or legacy {gate, promoted}, read via isIntegrated)
// judge(wave, context)  → Promise<judgment>  (the wave-oversight sub-agent; {continue, concern, ...})
//                          context = { completed:[{wave,verdict}], remaining:[waveId], index }
// onEvent(event)        → void               (optional progress sink: {type, wave, ...})
//
// Returns a terminal CAMPAIGN report:
//   { outcome: 'completed' | 'held', wavesAdvanced:[id], heldAt?:id, heldReason?, completed:[{wave,verdict,judgment}] }
// HOLD-and-end is a terminal report, never a throw (a Workflow ending with a report IS the human
// handoff, §2.2). A runWave/judge that THROWS becomes a conservative HOLD on that wave, not a crash.
export async function runCampaign({ pending, runWave, judge, onEvent }) {
  const emit = typeof onEvent === 'function' ? onEvent : () => {}
  const completed = []
  const wavesAdvanced = []
  const waves = pending ?? []

  for (let i = 0; i < waves.length; i++) {
    const wave = waves[i]
    const id = waveIdOf(wave)
    emit({ type: 'wave-start', wave: id, index: i })

    let verdict
    try {
      verdict = await runWave(wave, i)
    } catch (e) {
      return hold(id, `per-wave spine errored: ${e?.message || e}`, completed, wavesAdvanced)
    }
    const vr = routeVerdict(verdict)
    // Emit `integrated` via the same predicate the router used (#1052) — reading raw `promoted`
    // here would log `integrated=false` for a legacy-record wave that just advanced, i.e. the
    // progress line would contradict the decision it is narrating.
    emit({ type: 'verdict', wave: id, gate: verdict?.gate ?? null, integrated: isIntegrated(verdict), advance: vr.advance })
    if (!vr.advance) {
      completed.push({ wave: id, verdict, judgment: null })
      return hold(id, vr.reason, completed, wavesAdvanced)
    }

    // Gate said advance — now the wave-oversight judgment seam (§2.2). It inspects the WHOLE
    // trajectory so far, not just this wave, to catch accumulation / intent-drift the per-wave
    // gate structurally cannot (§4).
    const context = {
      completed: completed.map((c) => ({ wave: c.wave, verdict: c.verdict })), // PRIOR waves (this wave not yet pushed)
      wave: id,         // the JUST-LANDED wave id
      verdict,          // the JUST-LANDED wave's verdict — NOT yet in `completed`; the seam must
                        // surface it (justLanded) + append it to the trajectory, else the judgment
                        // seed is always missing its most-recent wave (the primary evidence).
      remaining: waves.slice(i + 1).map(waveIdOf),
      index: i,
    }
    let judgment
    try {
      judgment = await judge(wave, context)
    } catch (e) {
      completed.push({ wave: id, verdict, judgment: null })
      return hold(id, `wave-oversight judgment errored: ${e?.message || e}`, completed, wavesAdvanced)
    }
    const jr = routeJudgment(judgment)
    emit({ type: 'judgment', wave: id, advance: jr.advance })
    completed.push({ wave: id, verdict, judgment })
    if (!jr.advance) {
      return hold(id, jr.reason, completed, wavesAdvanced)
    }

    wavesAdvanced.push(id)
    emit({ type: 'advanced', wave: id })
  }

  emit({ type: 'campaign-complete', wavesAdvanced })
  return { outcome: 'completed', wavesAdvanced, completed }
}

function hold(heldAt, heldReason, completed, wavesAdvanced) {
  return { outcome: 'held', heldAt, heldReason, wavesAdvanced, completed }
}

// ── THE RELEASE GATE (#1052) — the single write to the protected branch ───────────────────────
//
// Every wave integrated onto the campaign branch. This is the ONE moment the protected branch is
// written, and it is the only place in the engine allowed to do so. Two conditions, both required:
//
//   1. the campaign COMPLETED — every wave in the plan integrated (not "every pending wave this
//      run"; a resumed run's `pending` is a subset, so completeness is judged against the FULL plan);
//   2. the DoD is met.
//
// WHY THE FULL-PLAN CHECK IS LOAD-BEARING. `runCampaign` returns outcome:'completed' when it
// exhausts the waves IT was given. On a resume that list was already pruned to the pending subset,
// so 'completed' there means "the rest finished" — not "all of them did". Releasing on that alone
// would ship a campaign whose earlier waves were pruned because they were integrated... which is
// fine... OR pruned from a DIFFERENT plan revision, which is not. Comparing against the full
// ordered plan makes the predicate independent of how the run was sliced.
//
// WHY DoD-FAILS-MEANS-NO-MERGE IS THE WHOLE POINT. Without it, "one merge at the end" is
// indistinguishable from "one unconditional merge at the end" — the DoD gate would be decoration
// and the campaign would release whatever it happened to build. This predicate is why the shape is
// safer than per-wave promotion rather than merely tidier.
//
// CONSERVATIVE ON ABSENCE: an unreadable/missing DoD, a malformed verdict, or an unmet criterion
// all BLOCK. An undeterminable DoD is not a met DoD (SEAMS invariant 6). The campaign branch is
// durable, so a blocked release is fully resumable once the DoD is genuinely satisfied — the cost
// of holding is a conversation; the cost of releasing wrongly is a revert of the whole campaign.
export function routeRelease({ report, allWaves, dod } = {}) {
  const outcome = report?.outcome ?? null
  if (outcome !== 'completed') {
    return { release: false, reason: `campaign did not complete (outcome=${outcome ?? 'unknown'}${report?.heldAt ? `, held at ${report.heldAt}` : ''}) — the protected branch is written only on a complete campaign` }
  }

  // Completeness against the FULL plan, not this run's slice (see above).
  const planIds = (allWaves ?? []).map((w) => String(waveIdOf(w)))
  const landed = new Set([
    ...(report?.wavesAdvanced ?? []).map(String),
    // A wave pruned before this run is already integrated durably; the caller passes it through
    // `alreadyIntegrated` on the report when resuming.
    ...(report?.alreadyIntegrated ?? []).map(String),
  ])
  const missing = planIds.filter((id) => !landed.has(id))
  if (missing.length > 0) {
    return { release: false, reason: `campaign incomplete — ${missing.length} of ${planIds.length} wave(s) not integrated: [${missing.join(', ')}]` }
  }
  if (planIds.length === 0) {
    return { release: false, reason: 'empty wave plan — nothing to release (a campaign with no waves is a misconfiguration, not a no-op)' }
  }

  // The DoD verdict. `met:true` is the ONLY release token; everything else holds.
  if (dod == null) {
    return { release: false, reason: 'DoD verdict absent — cannot prove the Definition of Done is met, so the protected branch is not written (an undeterminable DoD is not a met DoD)' }
  }
  if (dod.met !== true) {
    const unmet = Array.isArray(dod.unmet) && dod.unmet.length > 0 ? `: [${dod.unmet.join('; ')}]` : ''
    return { release: false, reason: `DoD not met${unmet}${dod.reason ? ` — ${dod.reason}` : ''}` }
  }

  return { release: true, reason: `campaign complete (${planIds.length} wave(s) integrated) and DoD met` }
}

// The DoD verdict contract the release-gate agent returns. `met` is the only field routed on;
// `unmet` + `reason` exist so a blocked release explains itself to the human without a re-run.
export const DOD_VERDICT = {
  type: 'object',
  additionalProperties: false,
  required: ['met'],
  properties: {
    met: { type: 'boolean' },
    unmet: { type: 'array', items: { type: 'string' } },
    reason: { type: 'string' },
    evidence: { type: 'string' },
  },
}

// The release-node result contract — `released` must reflect an ACTUALLY-LANDED merge, never a
// merge-requested-but-pending one (the same discipline the per-wave promote node carries: catalog
// signal I, "promoted ≠ delivered").
export const RELEASE_RESULT = {
  type: 'object',
  additionalProperties: false,
  required: ['released'],
  properties: {
    released: { type: 'boolean' },
    pr_ref: { type: 'string' },
    merge_sha: { type: 'string' },
    notes: { type: 'string' },
  },
}

// ── DoD verification prompt (#1052 — the release gate's evidence step) ───────────────────────
// Runs ONCE, after every wave integrated, BEFORE anything touches the protected branch. It only
// ANSWERS; routeRelease() decides. Keeping the judgment out of the prompt is why "DoD unmet ⇒ no
// merge" is testable without an agent in the loop.
export function dodVerificationPrompt({ planId, targetRepo, targetRepoDir, campaignBranch, protectedBranch, wavesIntegrated }) {
  return [
    `You are the CAMPAIGN RELEASE-GATE DoD node for plan ${planId ?? '<unknown>'} of ${targetRepo}.`,
    `Every wave has integrated onto ${campaignBranch}. NOTHING has touched ${protectedBranch} yet, and`,
    `nothing will unless you can show the Definition of Done is MET. Answer only — do NOT merge, do NOT`,
    `push, do NOT open a PR, do NOT modify any branch. Your verdict is evidence, not a decision.`,
    ``,
    `Waves integrated: [${(wavesIntegrated ?? []).join(', ') || 'none'}].`,
    ``,
    `1. Load the plan's Definition of Done: sdlc-server plan_load_dod(plan_id=${planId ?? '<plan>'},`,
    `   repo="${targetRepo}"). If the plan has a DoD manifest, ALSO run dod_load_manifest +`,
    `   dod_verify_deliverable for each declared deliverable — a wave suite passing is NOT the same as`,
    `   a manifest deliverable existing (the flights wrote both their code and their tests; the manifest`,
    `   is the reference they did not author).`,
    `2. Verify each DoD criterion against the CAMPAIGN BRANCH state, in ${targetRepoDir}:`,
    `     git -C ${targetRepoDir} fetch origin && git -C ${targetRepoDir} diff --stat origin/${protectedBranch}...origin/${campaignBranch}`,
    `   Check the ACTUAL tree, not the issue checkboxes — a checked box is a claim, the tree is the fact.`,
    `   Where a criterion names a test suite, RUN it (dod_run_test_suite / the project's own tooling).`,
    `3. Be specific about what is NOT met. A blocked release must explain itself well enough that the`,
    `   human does not have to re-derive it: name the criterion, not "some criteria failed".`,
    ``,
    `CONSERVATIVE ON ABSENCE — this is the contract, not a preference: if the DoD cannot be LOADED, is`,
    `absent, is ambiguous, or you cannot verify a criterion, return met=false and say why. An`,
    `undeterminable DoD is NOT a met DoD. You are the last check before ${protectedBranch} is written`,
    `for the first and only time in this campaign; a wrong "met" ships a half-built campaign to trunk`,
    `and costs a multi-wave revert, while a wrong "not met" costs one conversation. Bias accordingly.`,
    ``,
    `Return EXACTLY: met (bool), unmet (array of strings — the criteria not satisfied, empty if met),`,
    `reason (1-2 sentences), evidence (what you actually ran/read to decide).`,
  ].join('\n')
}

// ── release-merge prompt (#1052 — the ONE write to the protected branch) ─────────────────────
// Reached only when routeRelease() returned release:true. Carries its own merge-result CI gate
// against the protected branch, which is NOT redundant with the per-wave signals — see below.
export function releaseMergePrompt({ planId, targetRepo, campaignBranch, protectedBranch, wavesIntegrated }) {
  return [
    `You are the CAMPAIGN RELEASE node for plan ${planId ?? '<unknown>'} of ${targetRepo}. The campaign`,
    `is complete (waves [${(wavesIntegrated ?? []).join(', ') || 'none'}] all integrated onto`,
    `${campaignBranch}) and the DoD gate PASSED. Land ${campaignBranch} → ${protectedBranch}.`,
    ``,
    `THIS IS THE ONLY WRITE TO ${protectedBranch} IN THE ENTIRE CAMPAIGN. It is a real increment for the`,
    `first time: until this merge, ${protectedBranch} has been untouched since the campaign began, and`,
    `everyone else has been working from a trunk this campaign never disturbed. Treat it accordingly.`,
    ``,
    `1. Open the ${campaignBranch}→${protectedBranch} PR (sdlc-server pr_create, or find the existing one`,
    `   — idempotent on the branch pair; do NOT open a second). Title: the plan's release summary.`,
    `   Body: the wave list + the DoD verdict. Open it as a DRAFT so a green CI cannot auto-merge it`,
    `   before you have verified the merge-result pipeline yourself.`,
    ``,
    `2. GATE ON THE MERGE-RESULT PIPELINE AGAINST ${protectedBranch}. This is a REQUIRED, INDEPENDENT`,
    `   check — not a re-run of the per-wave signals, and not optional:`,
    `     sdlc-server ci_wait_run(repo="${targetRepo}", require_merge_result=true, pr_number=<n>,`,
    `                             timeout_sec=1800, poll_interval_sec=20)`,
    `   WHY IT CANNOT BE SKIPPED even though every wave was green: each wave's CI validated`,
    `   kahuna→${campaignBranch}, i.e. the wave against the CAMPAIGN branch. ${campaignBranch} itself`,
    `   drifts from ${protectedBranch} for the whole campaign — other people's merges land on trunk`,
    `   while this campaign runs. So NO per-wave pipeline ever tested this composed diff against the`,
    `   CURRENT ${protectedBranch}. A campaign of all-green waves can still break trunk, and this is`,
    `   the only pipeline that would ever catch it. Use require_merge_result=true (a branch pipeline`,
    `   proves nothing about the merge) and the explicit timeout (#1035 — the default idle bleeds`,
    `   ~30-57 min/run). timeout_sec is 1800 here, not 420: this is a whole-campaign diff, and its`,
    `   pipeline is legitimately longer than a single wave's.`,
    `   If it is NOT green: STOP. Return released=false with the failure in notes. Leave the PR open as`,
    `   a DRAFT and do NOT merge — a red merge-result on the release is exactly the signal the whole`,
    `   no-interim-merge-back shape exists to be able to act on, while trunk is still clean.`,
    ``,
    `3. On green: mark ready (gh -R ${targetRepo} pr ready <n>) and merge it. Then CONFIRM IT LANDED`,
    `   before reporting released — poll until state=MERGED with a merge commit (pr_merge_wait, or`,
    `   gh -R ${targetRepo} pr view <n> --json state,mergeCommit). Never treat a pending merge as done.`,
    `   The merge METHOD does not matter here (squash is fine): nothing continues from ${campaignBranch}`,
    `   after this point, so there is no persistent branch left to diverge (this is what dissolves #892`,
    `   rather than working around it).`,
    ``,
    `4. Only AFTER the merge is confirmed landed: close the campaign's issues (#1046 — an issue closes`,
    `   when its work is on ${protectedBranch}, never before). Honor an explicit do-not-close: if a`,
    `   flight body used "Refs #N" rather than "Closes #N", do NOT close that issue by number — that`,
    `   was a deliberate signal, and overriding it is the #1046 defect. Verify each close by READING`,
    `   THE ISSUE STATE BACK, not by the mutation's return code.`,
    ``,
    `5. Delete ${campaignBranch} on origin — the campaign is released and the branch is spent.`,
    ``,
    `Return: released (true ONLY if the merge actually landed on ${protectedBranch}), pr_ref, merge_sha,`,
    `notes (1-2 sentences; on any failure released=false with the reason).`,
  ].join('\n')
}

// ── intent-tier resolver (§3 — tiered intent, graceful degradation) ──────────────────────────
// A rehydrate agent reports what intent artifacts EXIST (it runs devspec_locate / ddd_locate_*);
// this PURE fn picks the richest available tier so the choice is deterministic + testable. The
// agent is then TOLD its tier and calibrates (rigorous spec-fidelity with a devspec; "ACs met +
// trajectory coherent" with only issues) — naming the tier prevents both faking a check it cannot
// do and hedging when it has solid ground.
export function resolveIntentTier({ devspec, domainModel, sketchbook } = {}) {
  if (devspec) return 'devspec'
  if (domainModel || sketchbook) return 'plan-ddd-sketchbook'
  return 'issues-only'
}

// ── wave-oversight judgment prompt — THE LENS (#750/§4 + §7) ──────────────────────────────────
// The seed is handed RAW (no distillation, §3): tiered intent + the durable cross-wave trajectory
// (#748) + the just-landed wave + live-inspection tools. The §7 failure-shapes are the crowdsourced
// cross-wave catalog (A–J, [[project_wave_oversight_failure_catalog]]) — "go with what came in over
// Discord" (BJ, 2026-06-20). routeJudgment + JUDGMENT_RESULT are the stable contract; this body is
// the lens. Same record + wrong lens = a checkpoint that rubber-stamps; this is the difference.
export function waveOversightPrompt({ justLanded, trajectory, remainingPlan, intentTier, intentRefs, kahunaBranch, campaignBranch, protectedBranch }) {
  const tier = intentTier ?? 'issues-only'
  const calibration = {
    'devspec': `DEVSPEC tier — the un-gameable reference the flights did not write. Hold spec-fidelity: run dod_check_coverage / dod_verify_deliverable for HARD VRTM + Deliverables-Manifest traceability, and devspec_* checks. A wave that passed its own tests but misses a manifest deliverable is DRIFT.`,
    'plan-ddd-sketchbook': `PLAN/DDD/SKETCHBOOK tier — judge against the recorded decision ledger + domain intent (ddd_locate_domain_model / ddd_locate_sketchbook). No VRTM; "decisions honored + domain model intact + trajectory coherent".`,
    'issues-only': `ISSUES-ONLY tier — no spec/DDD. Judge "each wave's own ACs met + the trajectory is coherent". Be honest about the ceiling: you cannot check spec-fidelity you do not have — do NOT fake it.`,
  }[tier] ?? `ISSUES-ONLY tier.`
  return [
    `You are the WAVE-OVERSIGHT judgment agent — the campaign-layer checkpoint BETWEEN waves. A wave`,
    `just PASSED its per-wave trust gate and INTEGRATED onto the campaign branch`,
    `${campaignBranch ? `(${campaignBranch})` : ''}. Your question (§4): given the INTENT and the`,
    `TRAJECTORY so far, is it sound to continue into the rest of the campaign — or is something lurking`,
    `that every individual per-wave gate structurally could NOT catch? You are the only view with the`,
    `whole trajectory + the un-gameable intent; the flights wrote both their code AND their tests, so`,
    `"green per wave" is not "correct to intent".`,
    ``,
    `#1052 — WHAT "INTEGRATED" MEANS HERE, AND WHY IT RAISES YOUR STAKES. Nothing in this campaign has`,
    `reached ${protectedBranch || 'the protected branch'} yet, and nothing will until every wave lands`,
    `and the DoD gate passes — then it lands in ONE merge. Two consequences for your judgment:`,
    `  • A flag from you is CHEAP right now. The protected branch is untouched, so acting on a concern`,
    `    costs deleting or reworking an unmerged branch — not reverting promoted commits out of trunk`,
    `    history. This is the window where a lurking problem is cheapest to name. Use it.`,
    `  • Trajectory entries reading released:false mid-campaign are the NORMAL state, not a failure`,
    `    signal. Judge on `+'`integrated`'+` and the trust signals. Do NOT read "not yet on the protected`,
    `    branch" as catalog-I evidence ("promoted ≠ delivered") — that shape is about a landed merge whose`,
    `    artifact never actually shipped, not about a campaign correctly withholding its single trunk`,
    `    write until the DoD is met.`,
    `  • Vocabulary note: in a post-#1052 record `+'`promoted`'+` is a SYNONYM for `+'`integrated`'+` (both mean`,
    `    "landed on the campaign branch"), NOT a claim about trunk. So `+'`promoted:false`'+` on a recent entry`,
    `    means the wave did not land — read it as such. Only `+'`released`'+` speaks to the protected branch.`,
    ``,
    `── INTENT TIER: ${tier} ──`,
    calibration,
    intentRefs ? `Intent refs: ${JSON.stringify(intentRefs)}.` : `Intent refs: none discovered.`,
    ``,
    `── THE SEED (raw, no distillation — §3) ──`,
    `Just-landed wave (its diff/signals/reconcile are yours to inspect): ${JSON.stringify(justLanded ?? null)}`,
    `Durable cross-wave trajectory — every completed wave's RAW record (gate/promoted, the four trust`,
    `signals + detail, concerns, deferrals, rework, commutativity, files_touched, engine_fingerprint,`,
    `issues; #748). This is your primary evidence — read it as a TIME SERIES, not a snapshot:`,
    JSON.stringify(trajectory ?? [], null, 2),
    `Remaining plan (judge "sound to proceed INTO the rest"): ${JSON.stringify(remainingPlan ?? [])}`,
    `LIVE INSPECTION: you have read tools and the kahuna branch (${kahunaBranch ?? 'n/a'}) checked out.`,
    `When something smells, GO LOOK at the actual code/tests/manifests — this is a real inspection,`,
    `not a record read. A claim you can verify, verify.`,
    ``,
    `── THREE DETECTION MODES (apply all three) ──`,
    `1. TREND — a metric sliding wrong ACROSS waves (not one bad wave). 2. ABSENCE — a datapoint that`,
    `SHOULD exist and never does (the hardest; you cannot trend your way to "never real"). 3. CONFOUND`,
    `CONTROL — do NOT blame the code for a substrate/engine step-change: if engine_fingerprint changed`,
    `between waves, or a host/env event (reboot, reinstall, DNS) sits at a metric's step, attribute the`,
    `discontinuity to the SUBSTRATE, not the content. Separate environment-caused from content-caused.`,
    ``,
    `── THE FAILURE-SHAPE LENS (crowdsourced cross-wave catalog; hunt every one) ──`,
    `A. GATE-VOUCHED-BUT-WRONG (intent-drift): fix-forward commits in wave N touching files a PRIOR`,
    `   promoted wave shipped (latent doc-vs-impl drift); negative/deny tests asserting only exit!=0`,
    `   not the SPECIFIC error kind (pass spuriously, hide a boundary regression) — esp. in authz/security.`,
    `B. UNDER-SPECIFICATION: the SAME subsystem in ≥3 non-adjacent waves' diffs it wasn't scoped to`,
    `   (under-specified, more latent defects coming); COMMUTATIVITY decay on a SHARED HOTSPOT — the`,
    `   same OVERLAPPING path set tripping ORACLE_REQUIRED across waves (an unfactored shared-infra dep`,
    `   the decomposition missed ⇒ "parallel" waves serialize). NB: ORACLE volume across DIFFERENT files`,
    `   is benign — the smell is the repeated overlap, not the count.`,
    `C. DIVERGENCE RATES: manual-intervention climbing (force-pushes / gate-disables / kahuna-recreates /`,
    `   non-FF resolutions per wave); local-green → rising "fix CI deps/env" commits ("config exists ≠ works").`,
    `D. CROSS-TEAM CONTRACT: a wave adds a HARD dependency on another team's surface with NO`,
    `   graceful-in-absence fallback ⇒ a matched-pair break on a different cadence.`,
    `E. SPY/MOCK-ONLY UN-EXERCISED SURFACE (absence): a runtime boundary (container bring-up, TLS, a`,
    `   shelled binary, an external call) accruing code wave-over-wave while tests that run the REAL`,
    `   artifact stay ~0. The tell is the MISSING real-execution datapoint, not a failing one —`,
    `   "command-ran ≠ thing-attached"; a real run later detonates a CHAIN of never-attached gaps.`,
    `F. SUBSTRATE/ENGINE CONFOUNDS: engine_fingerprint/toolkit drift mid-campaign (wave 1 ran different`,
    `   semantics than wave 7); host/env events. Treat as an ANNOTATION, never a content-trend (mode 3).`,
    `G. IMPERATIVE-WITHOUT-VERIFY-AFTER: mutate-state steps (enable/load/apply/init/up) accrue while`,
    `   read-back-and-ASSERT steps don't — ratio drifting to 1:0. "Assert the post-state, not the command."`,
    `H. STALE EXTERNAL-STATE ASSERTIONS: agent-authored tracker pins / handoffs / reseed text asserting`,
    `   external state (issue open, file shape, branch ahead) from MEMORY not a re-read — fails a re-read.`,
    `I. PROMOTED ≠ DELIVERED ≠ RUNNING: a "promoted" wave whose delivery is a silent no-op — no assertion`,
    `   the RUNNING artifact carries the promoted SHA/digest; deploy-inventory lag (code+tests grow, the`,
    `   publish/fragment/compose inventory doesn't ⇒ "done" on the board, does-not-exist in reality).`,
    `J. CERTIFIER/DOC DRIFT: the facade migrates UP a layer when attacked (features → the tests guarding`,
    `   them → the doc/matrix certifying them); a confidently-wrong authoritative doc contradicting a`,
    `   higher-authority source (CLAUDE.md/spec), propagating by inheritance. A certifier untouched while`,
    `   its subject churned = flag.`,
    ``,
    `── ADAPTATION vs DRIFT (the discriminator) ──`,
    `A deviation CONSCIOUSLY RECORDED (a logged deferral/concern) is ADAPTATION — fine. A SILENT deviation`,
    `from intent is DRIFT — flag it. The two classes the per-wave gate cannot catch: ACCUMULATION (waves`,
    `2,4,5 all raising concerns/deferrals/rework in the SAME subsystem ⇒ a lurking architectural problem`,
    `each individual green gate passed) and INTENT-DRIFT (passes its own tests, builds the wrong thing).`,
    `Devspec + trajectory together make the discrimination possible.`,
    ``,
    `── OUTPUT ── Return EXACTLY: { continue (bool), confidence (0..1), concern: { what, which_waves`,
    `(array), which_subsystem, severity }, recommendation }. continue:true ONLY if genuinely sound to`,
    `proceed; a real lurking smell ⇒ continue:false with a PRECISE concern (which waves, which subsystem).`,
    `Absence of a clear "continue" is not a license to proceed — when uncertain after inspecting, hold.`,
  ].join('\n')
}

// The §3 output contract — the loop routes on `continue`; #750 refines the prompt, not this schema.
export const JUDGMENT_RESULT = {
  type: 'object',
  additionalProperties: false,
  required: ['continue'],
  properties: {
    continue: { type: 'boolean' },
    confidence: { type: 'number' },
    concern: {
      type: 'object',
      additionalProperties: true,
      properties: {
        what: { type: 'string' },
        which_waves: { type: 'array', items: { type: 'string' } },
        which_subsystem: { type: 'string' },
        severity: { type: 'string' },
      },
    },
    recommendation: { type: 'string' },
  },
}
