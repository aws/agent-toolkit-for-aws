---
description: Show the whole Continuum security picture, including attack paths, protected assets, proposed fixes, future state, merge path, and decisions.
---

Use the `reporting-continuum-security` skill at `../skills/reporting-continuum-security/SKILL.md`. Follow its shared AWS safety prelude and fast status path. Report the current state across scans, with one Continuum issue per flaw and only exact-code merges. The source checker returns Open only when every significant cited line is unchanged at its position; every other usable-source result needs agent review. Only the agent may conclude Probably fixed after reading current code and Git history. Status is read-only except for private evidence, the owner-only `.continuum/reports/security-report.md`, the local ignore rule and owned temporary source copies. Never write through a symlink. Complete the skill's self-check and deliver the exact Summary and Markdown path.
