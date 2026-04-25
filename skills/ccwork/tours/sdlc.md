# Tour: SDLC

A guided walkthrough of the integration-branch pattern that gates wave-pattern work between flights and `main`. This tour covers KAHUNA — the final stop in the SDLC pipeline before autonomous runs.

**Pace:** Pause after each section. Run the command, then explain what the output means. If a command prints nothing on the user's project, that's a signal — narrate it, don't paper over it.

**Cross-references:** Point users to the detailed docs when appropriate:
- [Kahuna Guide](../../../docs/kahuna-guide.md) for user-facing detail on the integration-branch pattern
- [Kahuna Dev Spec](../../../docs/kahuna-devspec.md) for architecture and design rationale

---

## Section 1: Kahuna — the integration-branch pattern

Narration: "Wave-pattern work spawns a swarm of Flight agents in parallel — each one on its own feature branch, each one trying to merge to `main`. That works fine for two or three flights. Once you have ten flights racing the queue, the merge order starts mattering, CI starts thrashing, and a single broken story can wedge the whole wave. Kahuna fixes that by inserting one integration branch between flights and `main` — flights merge to `kahuna/<wave-id>`, the wave settles, and only after a trust-score gate does kahuna fast-forward into `main`. That's the pattern: a per-wave staging branch that absorbs flight churn so `main` only ever sees a clean, validated wave."

Narration: "The flow is: Orchestrator plans the wave and creates `kahuna/<wave-id>`. Prime fans out flights, each on its own feature branch off kahuna. Flight agents work, run precheck, and merge to kahuna — not main. When every flight in the wave is green, the trust score is computed against kahuna. If the score clears the gate, kahuna fast-forwards into `main`. If it doesn't, the wave is held for review. `main` is the protected production branch; kahuna is the sandbox where a wave gets to be wrong before it gets to be right."

### Check whether KAHUNA is enabled on this project

Narration: "Let's see if the current project actually uses kahuna. There are two signals — the wave-status state file, and the kahuna branches in git. Either one is enough to confirm."

```bash
wave-status show 2>/dev/null | grep -iE 'kahuna|wave|current' | head -10 || echo "(wave-status not initialized for this repo)"
```

Narration: "If wave-status is initialized and the project uses kahuna, you'll see a `kahuna_branch` or `kahuna_branches` field in the output. If you see nothing — or the command says not initialized — kahuna isn't active here yet. That's fine; most everyday work doesn't need it."

### Check for kahuna branches in git

```bash
git branch --list 'kahuna/*' --all 2>/dev/null | head -10 || true
```

Narration: "Each wave gets its own integration branch named `kahuna/<wave-id>-<slug>`. If this list is empty, no wave has staged through kahuna in this repo yet. If you see one or more — those are the per-wave staging branches. They're disposable; once a wave's kahuna branch fast-forwards into main, it can be deleted."

### Check for a local kahuna state file (if applicable)

```bash
ls .kahuna 2>/dev/null && cat .kahuna 2>/dev/null || echo "(no .kahuna state file — project is not kahuna-enabled, or state lives in wave-status)"
```

Narration: "Some projects keep kahuna state in a `.kahuna` file at the repo root; others delegate the whole thing to wave-status. The 'no state file' branch is the common case — don't read it as an error."

---

## Section 2: Where to go from here

Narration: "That's the integration-branch pattern in one tour. For day-to-day usage — when to start a wave, how to read the dashboard, how the trust gate is scored — read the user guide. For the architectural why — the bus, the trust score formula, the recovery semantics — read the dev spec."

- **User-facing usage** — [Kahuna Guide](../../../docs/kahuna-guide.md)
- **Architecture and design** — [Kahuna Dev Spec](../../../docs/kahuna-devspec.md)
- **Wave skills** — `/assesswaves`, `/prepwaves`, `/nextwave`, `/wavemachine` (orientation tour Section 5 covers these)

Narration: "If your project doesn't use kahuna yet, that's okay — you can ship a long way on the basic feature-branch loop covered in the orientation tour. Kahuna earns its keep when you're regularly running 5+ flights in parallel and `main` starts getting churned."
