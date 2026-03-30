<!-- preamble: This file is shown once on first use of the /issue skill, then deleted. -->

# /issue — Structured Issue Creation

Create properly templated issues from natural language:

```
/issue feature "add dark mode support"
/issue bug "login fails on Safari"
/issue chore "update dependencies"
/issue "the search results are wrong"     ← type inferred
/issue                                     ← uses conversation context
```

Every issue gets the right template (feature, bug, chore, docs, epic), the right labels (`type::`, `priority::`, `urgency::`, `size::`, `severity::`), and is written to wave-quality — detailed enough for a spec-driven agent to execute without design decisions.

You review and approve the draft before it's created. Works on both GitHub and GitLab.
