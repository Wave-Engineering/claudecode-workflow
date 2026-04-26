<!-- preamble: This file is shown once on first use of the /issue skill, then deleted. -->

# /issue — Structured Issue Creation

Create properly templated issues from natural language:

```
/issue feature "add dark mode support"
/issue story   "user can reset password from profile page"
/issue bug     "login fails on Safari"
/issue chore   "update dependencies"
/issue "the search results are wrong"     ← type inferred
/issue                                     ← uses conversation context
```

Every issue gets the right template (feature, story, bug, chore, docs, epic), the right labels (`type::`, `priority::`, `urgency::`, `size::`, `severity::`), and is written to wave-quality — detailed enough for a spec-driven agent to execute without design decisions.

**Wave-pattern-ready output guarantee:** the sub-issue templates (feature, story, chore, docs, bug) emit the six H2 sections required by `/prepwaves` and `spec_validate_structure` — `## Summary`, `## Implementation Steps`, `## Test Procedures`, `## Acceptance Criteria`, `## Dependencies`, `## Metadata` — so issues created via `/issue` pass the wave-readiness check on first try, with no mid-flight body fixes. The `epic` template is intentionally different because epics are parents, not sub-issues.

You review and approve the draft before it's created. Works on both GitHub and GitLab.
