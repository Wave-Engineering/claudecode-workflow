# scripts/testing

Test infrastructure for the wave-pattern pipeline. Tools here are not part
of any CI/CD pipeline — they exist to set up reproducible test scenarios
that exercise the pipeline itself.

## `wave-fixture-gen.py`

Synthetic wave-pattern fixture generator. Materializes deterministic
conflict and failure scenarios against a target git repo so the KAHUNA
pipeline can be exercised repeatedly. Python 3 stdlib-only; no external
dependencies.

Referenced by KAHUNA Dev Spec (`docs/kahuna-devspec.md` §5.A DM-10, §6.2)
for integration tests IT-03, IT-04, IT-05, IT-08. Outlives KAHUNA — any
wave-pattern work that needs reproducible conflict shapes can use it.

### Scenarios

| Subcommand | Exercises | Red signal expected |
|---|---|---|
| `conflicting-functions` | IT-03, R-12 | `commutativity_verify` → WEAK |
| `trivy-dep-vuln` | IT-04, R-15 | `trivy fs` → HIGH/CRITICAL |
| `critical-code-smell` | IT-05, R-14 | `feature-dev:code-reviewer` → critical |
| `rebase-conflict-setup` | IT-08, R-21 | Flight rebase conflict |

Every scenario:
- Writes branches under the prefix `wave-fixture/<scenario>/…`
- Writes an epic payload JSON to `.wave-fixtures/<scenario>-epic.json`
- Is **deterministic**: same `--repo` + same args → identical commit SHAs
  (fixed author identity + fixed commit timestamps)
- Leaves the caller's starting branch checked out on completion

### Usage

```bash
# Generate
./scripts/testing/wave-fixture-gen.py conflicting-functions --repo /path/to/target
./scripts/testing/wave-fixture-gen.py trivy-dep-vuln --repo /path/to/target
./scripts/testing/wave-fixture-gen.py critical-code-smell --repo /path/to/target
./scripts/testing/wave-fixture-gen.py rebase-conflict-setup --repo /path/to/target

# Clean up
./scripts/testing/wave-fixture-gen.py cleanup --repo /path/to/target
```

Each scenario prints a JSON summary describing the created branches, the
epic payload path, and scenario-specific notes (e.g. which branch to rebase
onto which to reproduce the rebase conflict). File the epic payload via
`gh issue create` / `glab issue create` to exercise the pipeline end-to-end.

Run `./scripts/testing/wave-fixture-gen.py --help` or any subcommand with
`--help` for full usage text.

### Cleanup

```bash
./scripts/testing/wave-fixture-gen.py cleanup --repo /path/to/target
```

Removes every local branch under the `wave-fixture/` prefix and the
`.wave-fixtures/` directory. Idempotent — safe to run repeatedly.

### Tests

Unit tests in `tests/test_wave_fixture_gen.py` exercise each scenario
against a real temp git repo (no mocks of git), verify determinism by
producing the same scenario twice and comparing SHAs, and verify cleanup.
Run via `python3 -m pytest tests/test_wave_fixture_gen.py`.
