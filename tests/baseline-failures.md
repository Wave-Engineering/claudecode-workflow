# Pytest Baseline Failures (Triage Pass — Issue #472)

This document records the **pre-existing pytest failure surface** discovered when running the full `pytest tests/` suite on `main`. The project's gating CI (`./scripts/ci/validate.sh`) runs a hand-curated subset (113 tests, 100% pass), so these failures are not merge-blocking today — but they need to be either fixed, properly skipped, or deleted before issue #329 (pytest as a merge gate) becomes actionable.

## Triage Result Summary

| Category | Count | Disposition |
| --- | --- | --- |
| dead-test (feature removed) | 47 | delete or rewrite against replacement |
| bug-in-test (stale path/structure assertion) | 24 | one-line edit per file (rename or remove) |
| bug-in-test (skill rewritten — assertions invalid) | 28 | rewrite the assertions or delete |
| Total | **99** | |

Plus **1 collection error** in `tests/test_discord_status.py` — **fixed in this commit** (pre-existing bug in `scripts/discord-status-post::get_discord_channel` that crashed at import time when `~/.claude/discord.json` used the flat `{role: "<id>"}` shape).

## Categorization Legend

- **bug-in-code** — production code is wrong; test correctly catches it
- **bug-in-test** — production code is correct; test asserts the wrong thing (stale path, refactored API, etc.)
- **env-dependent** — passes in some environments (Linux/macOS, with/without tool X) and not others
- **intentional-skip-not-marked** — the failure represents a known-skipped scenario that should be `pytest.skip(reason=...)` rather than a hard failure
- **dead-test-of-removed-feature** — the test exercises a feature that has been removed from the codebase; the test should be deleted

---

## File-Level Roll-Up

### `tests/test_install.py` — 8/8 failures

**Category: bug-in-test (stale path)**
**Root cause:** `_INSTALL_SCRIPT = str(_REPO_DIR / "install.sh")` (line 33). The script was renamed from `install.sh` to `install` (no extension) in commit `9d0b06d` / PR #281 ("fix(install): add missing ok() helper and rename install.sh to install"). All tests subprocess-exec the script and fail with `FileNotFoundError: install.sh`.
**Disposition:** **One-line edit** — `_INSTALL_SCRIPT = str(_REPO_DIR / "install")` and update the `_UNINSTALL_SCRIPT` constant (already correct). Optionally rename the docstring references. Worth fixing in a small follow-up PR; not in this triage scope.
**Recommended follow-up issue:** "fix(tests): point test_install*.py at the renamed `install` script"

| Test | Category |
| --- | --- |
| `TestInstallCreatesArtifacts::test_install_creates_artifacts` | bug-in-test (stale path: `install.sh` → `install`) |
| `TestInstalledBinaryRuns::test_installed_binary_runs` | bug-in-test (stale path: `install.sh` → `install`) |
| `TestInstallCheckClean::test_install_check_clean` | bug-in-test (stale path: `install.sh` → `install`) |
| `TestInstallCheckDetectsDrift::test_install_check_detects_drift` | bug-in-test (stale path: `install.sh` → `install`) |
| `TestInstallDryRun::test_install_dry_run` | bug-in-test (stale path: `install.sh` → `install`) |
| `TestUninstallRemovesArtifacts::test_uninstall_removes_artifacts` | bug-in-test (stale path: `install.sh` → `install`) |
| `TestUninstallDryRun::test_uninstall_dry_run` | bug-in-test (stale path: `install.sh` → `install`) |
| `TestReinstallOverwrites::test_reinstall_overwrites` | bug-in-test (stale path: `install.sh` → `install`) |

### `tests/test_install_merge.py` — 16/16 failures

**Category: bug-in-test (stale path)**
**Root cause:** Same as `test_install.py` — line 35: `_INSTALL_SCRIPT = str(_REPO_DIR / "install.sh")`. Identical fix.
**Disposition:** Bundle the fix with `test_install.py` in the same follow-up.
**Recommended follow-up issue:** Same as above.

| Test | Category |
| --- | --- |
| `TestFreshInstallCopiesTemplate::test_fresh_install_copies_template` | bug-in-test (stale path) |
| `TestMergeAddsMissingHook::test_merge_adds_missing_hook` | bug-in-test (stale path) |
| `TestMergePreservesExistingHooks::test_merge_preserves_existing_hooks` | bug-in-test (stale path) |
| `TestMergeAddsMissingPlugin::test_merge_adds_missing_plugin` | bug-in-test (stale path) |
| `TestMergePreservesExtraPlugins::test_merge_preserves_extra_plugins` | bug-in-test (stale path) |
| `TestMergeUnionsPermissions::test_merge_unions_permissions` | bug-in-test (stale path) |
| `TestMergePreservesUserPermissions::test_merge_preserves_user_permissions` | bug-in-test (stale path) |
| `TestMergeSkipsCommentKeys::test_merge_skips_comment_keys` | bug-in-test (stale path) |
| `TestMergeAddsMissingScalars::test_merge_adds_missing_scalars` | bug-in-test (stale path) |
| `TestMergePreservesExistingScalars::test_merge_preserves_existing_scalars` | bug-in-test (stale path) |
| `TestMergeCreatesBackup::test_merge_creates_backup` | bug-in-test (stale path) |
| `TestMergeDryRun::test_merge_dry_run` | bug-in-test (stale path) |
| `TestCheckReportsMissingHooks::test_check_reports_missing_hooks` | bug-in-test (stale path) |
| `TestCheckReportsMissingPlugins::test_check_reports_missing_plugins` | bug-in-test (stale path) |
| `TestMergeAddsStatusLineWhenAbsent::test_merge_adds_statusline` | bug-in-test (stale path) |
| `TestMergeIdempotent::test_merge_idempotent` | bug-in-test (stale path) |

### `tests/test_discord_bot_help.py` — 34/34 failures

**Category: dead-test-of-removed-feature**
**Root cause:** The bash script `skills/disc/discord-bot` was **deleted** in commit `b079782` / PR #283 ("chore(disc): remove discord-bot bash script replaced by disc-server MCP"). It was replaced by the `disc-server` MCP server (now exposing tools like `mcp__disc-server__disc_send`, `disc_read`, `disc_create_channel`, etc.). All tests in this file exec `skills/disc/discord-bot <subcommand> --help` as a subprocess; the path no longer exists.
**Disposition:** **Delete the entire file.** The discord-bot bash CLI is gone. The corresponding MCP server lives in a separate repo (`mcp-server-disc`-style) and has its own tests there. Keeping these tests creates phantom coverage of a deleted artifact.
**Recommended follow-up issue:** "chore(tests): delete test_discord_bot_help.py (subject script removed in #283)"

All 34 tests below are `dead-test-of-removed-feature`:

`TestSendHelp::*` (7), `TestReadHelp::*` (7), `TestCreateChannelHelp::*` (6), `TestResolveHelp::*` (7), `TestCreateThreadHelp::*` (3), `TestListChannelsHelp::*` (3), `TestCreateChannelErrorMessage::*` (1).

### `tests/test_discord_bot_split.py` — 13/13 failures

**Category: dead-test-of-removed-feature**
**Root cause:** Same as `test_discord_bot_help.py` — sources `skills/disc/discord-bot` (line 25) which no longer exists (deleted in #283). The `_split_for_discord` bash function being tested moved into the `disc-server` MCP server.
**Disposition:** **Delete the entire file.** Same reasoning.
**Recommended follow-up issue:** Bundle with `test_discord_bot_help.py` deletion above — single PR.

All 13 tests below are `dead-test-of-removed-feature`:

`TestSplitSizeBoundaries::*` (5), `TestSplitFallbacks::*` (3), `TestSplitUnicode::*` (2), `TestChunkFooter::*` (2), `TestSourcingGuard::*` (1).

### `tests/test_dod_skill.py` — 28/41 failures

**Category: bug-in-test (skill rewritten)**
**Root cause:** The `dod` skill at `skills/dod/SKILL.md` has been rewritten from a multi-template structure (with named templates like `dod-check` extractable via the test's `_extract_template` helper) to a flat procedural format. The 28 failing tests use `_extract_template(skill_text, "dod-check")` which now returns an empty string, so all downstream content assertions fail. Additional failures (e.g. `test_introduction_gate_present`) check for an `introduction-gate` HTML comment that was removed.
**Disposition:** Either (a) rewrite the assertions to match the new flat-procedural skill structure, or (b) delete tests that don't carry weight against the refactored skill. The 13 currently-passing tests in this file (e.g. SKILL.md exists, frontmatter has `name: dod`, introduction.md exists/non-empty) are still useful and should be preserved.
**Recommended follow-up issue:** "fix(tests): rewrite test_dod_skill.py assertions against post-rewrite SKILL.md structure"

| Test | Category |
| --- | --- |
| `TestFrontmatter::test_introduction_gate_present` | bug-in-test (gate comment removed in skill rewrite) |
| `TestTemplate::test_dod_check_template_exists` | bug-in-test (template structure removed in skill rewrite) |
| `TestTemplate::test_has_locate_prd_step` | bug-in-test (template extractor returns empty) |
| `TestTemplate::test_has_read_prd_step` | bug-in-test (template extractor returns empty) |
| `TestTemplate::test_has_verify_step` | bug-in-test (template extractor returns empty) |
| `TestTemplate::test_has_global_dod_step` | bug-in-test (template extractor returns empty) |
| `TestTemplate::test_has_vrtm_step` | bug-in-test (template extractor returns empty) |
| `TestTemplate::test_has_report_step` | bug-in-test (template extractor returns empty) |
| `TestTemplate::test_has_approval_step` | bug-in-test (template extractor returns empty) |
| `TestVerificationCategories::test_docs_category` | bug-in-test (template extractor returns empty) |
| `TestVerificationCategories::test_code_binary_category` | bug-in-test (template extractor returns empty) |
| `TestVerificationCategories::test_code_cicd_category` | bug-in-test (template extractor returns empty) |
| `TestVerificationCategories::test_code_build_system_category` | bug-in-test (template extractor returns empty) |
| `TestVerificationCategories::test_test_results_category` | bug-in-test (template extractor returns empty) |
| `TestVerificationCategories::test_test_coverage_category` | bug-in-test (template extractor returns empty) |
| `TestVerificationCategories::test_test_manual_category` | bug-in-test (template extractor returns empty) |
| `TestVerificationCategories::test_trace_vrtm_category` | bug-in-test (template extractor returns empty) |
| `TestNAHandling::test_na_rows_documented` | bug-in-test (template extractor returns empty) |
| `TestNAHandling::test_na_not_failure` | bug-in-test (template extractor returns empty) |
| `TestNAHandling::test_na_rationale_required` | bug-in-test (template extractor returns empty) |
| `TestReportFormat::test_report_has_project_name` | bug-in-test (template extractor returns empty) |
| `TestReportFormat::test_report_has_prd_path` | bug-in-test (template extractor returns empty) |
| `TestReportFormat::test_report_has_status_indicators` | bug-in-test (template extractor returns empty) |
| `TestApprovalFlow::test_all_pass_flow` | bug-in-test (template extractor returns empty) |
| `TestApprovalFlow::test_failure_flow` | bug-in-test (template extractor returns empty) |
| `TestApprovalFlow::test_campaign_integration` | bug-in-test (template extractor returns empty) |
| `TestApprovalFlow::test_remediation_on_fix` | bug-in-test (template extractor returns empty) |
| `TestApprovalFlow::test_rejection_flow` | bug-in-test (template extractor returns empty) |

---

## What This Triage Did NOT Do

Per scope of issue #472, this commit:

1. Fixed the **collection error** in `tests/test_discord_status.py` (root-caused to `scripts/discord-status-post::get_discord_channel` mishandling the flat `{role: "<id>"}` config shape in `~/.claude/discord.json`; now accepts both `str` and `dict` shapes).
2. Wrote this baseline document.

It did **not**:

- Fix any of the 99 categorized failures.
- Rename `install.sh` references (touches 24 tests; clean follow-up PR).
- Delete the `discord-bot` test files (touches 47 tests; clean follow-up PR).
- Rewrite the `dod` skill tests (touches 28 tests; needs design judgment about which assertions still matter).
- Add a CI gate that runs `pytest tests/` (issue #329's job).

## Recommended Follow-Up Issues

The 99 failures cluster cleanly into **three** follow-up tickets:

1. **fix(tests): repoint test_install.py + test_install_merge.py at renamed `install` script** — 24 failures, single-line edit per file, ~5 min work.
2. **chore(tests): delete test_discord_bot_help.py + test_discord_bot_split.py (script removed in #283)** — 47 failures, file-deletion only, ~5 min work.
3. **fix(tests): rewrite test_dod_skill.py against post-rewrite SKILL.md** — 28 failures, requires design judgment on which assertions remain meaningful, ~30-60 min work.

After all three land, `pytest tests/` should run clean. At that point #329 (pytest as merge gate) becomes actionable.
