# Cheat Sheet

Quick reference for all skills and the MCP tools they route to.

## Shipping

| Command | Purpose | MCP Tool |
|---------|---------|----------|
| `/precheck` | Pre-commit gate — verify, review, checklist | `ibm`, `spec_validate_structure` |
| `/scp` | Stage, commit, push, create PR | `pr_list`, `pr_create` |
| `/scpmr` | scp + stop before merge | `pr_list`, `pr_create` |
| `/scpmmr` | scp + merge (full pipeline) | `pr_create`, `pr_wait_ci`, `pr_merge` |
| `/mmr` | Merge existing PR/MR | `pr_status`, `pr_diff`, `pr_wait_ci`, `pr_merge` |
| `/review` | Code review (branch/staged/file/PR) | — (sub-agent) |
| `/jfail` | CI failure analysis | `ci_run_logs`, `ci_failed_jobs` |

## Wave Pattern

| Command | Purpose | MCP Tool |
|---------|---------|----------|
| `/assesswaves` | Triage wave suitability | `spec_validate_structure`, `wave_topology` |
| `/prepwaves` | Validate specs, compute waves, persist plan | `epic_sub_issues`, `wave_compute`, `wave_init` |
| `/nextwave` | Execute one wave (flights) | `wave_next_pending`, `wave_flight`, `wave_flight_done` |
| `/wavemachine` | Autopilot loop across all waves | `wave_health_check`, `wave_next_pending` |
| `/wave` | Show wave status | `wave_show` |

## SDLC Stages

| Command | Purpose | MCP Tool |
|---------|---------|----------|
| `/ddd` | Domain discovery (event storming) | `ddd_locate_sketchbook`, `ddd_verify_committed` |
| `/devspec` | Interactive Dev Spec creation | `devspec_locate`, `devspec_finalize` |
| `/dod` | Definition of Done verification | `dod_load_manifest`, `dod_verify_deliverable` |
| `/sdlc` | Work item creation, ibm check | `work_item`, `ibm` |

## Work Tracking

| Command | Purpose | MCP Tool |
|---------|---------|----------|
| `/issue` | Create structured issues | `work_item` |
| `/ibm` | Issue→Branch→PR compliance | `ibm` |
| `/multithread` | Parallelize discussion over N independent items | — |

## Ops & Troubleshooting

| Command | Purpose | MCP Tool |
|---------|---------|----------|
| `/nerf` | Context budget (darts, modes) | `nerf_status`, `nerf_darts`, `nerf_mode` |
| `/wtf` | Start troubleshooting session | `wtf_freshell` |
| `/wtf now` | Record manual journal entry | `wtf_now` |
| `/wtf happened` | Get incident timeline | `wtf_happened` |
| `/wtf imout` | Suspend recording | `wtf_imout` |
| `/disc` | Discord (send, read, list, create) | `disc_send`, `disc_read`, `disc_list` |

## Session & UI

| Command | Purpose | MCP Tool |
|---------|---------|----------|
| `/engage` | Load rules, restore context | — |
| `/name` | Report/pick session identity | — |
| `/ccfold` | Merge upstream CLAUDE.md template | — |
| `/ccwork` | Onboarding hub (tours, labs, setup) | — |
| `/man` | Skill usage display | — |
| `/vox` | Voice announcements (TTS) | — (script) |
| `/view` | Open file in GUI viewer | — (script) |
| `/edit` | Open file in GUI editor | — (script) |

## CLI Tools

| Command | Purpose |
|---------|---------|
| `campaign-status` | SDLC stage tracking + HTML dashboard |
| `wave-status` | Wave execution lifecycle tracking |
| `vox` | TTS from shell scripts |
| `discord-bot` | Discord REST client |
| `file-opener` | Cross-platform file/URL opener |

---

*Full docs: [Skill Reference](skill-reference.md) · [Tool-Skill Map](tool-skill-map.md)*
