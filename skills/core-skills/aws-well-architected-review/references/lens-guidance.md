# Lens Guidance — Applying Well-Architected Lenses

Lenses are **additive** — they expand the core framework questions with domain-specific best practices. They do NOT replace the framework questions.

## When to apply a lens

- The workload clearly matches the documented scope of a lens discovered from the live AWS documentation
- The user explicitly asks for a lens-specific review

## How to apply

Use this retrieval ladder for every lens lookup:

1. Use `aws___search_documentation` / `aws___read_documentation` when the AWS MCP server is available.
2. Otherwise, use the environment's web-search or web-fetch tool only over HTTPS against `docs.aws.amazon.com`. Do not use plain HTTP or retrieve lens guidance from other domains.
3. If no documentation access exists, proceed from internal knowledge and disclose that limitation.

- First complete the core framework evaluation (every framework question)
- Then fetch the lens documentation at review time using the retrieval ladder. Search for `AWS Well-Architected {lens name} Lens`, read the lens's per-pillar best-practice pages, and evaluate the additional lens-specific best practices
- Report lens findings in a separate section after the core findings

**If the user ONLY asks for a named lens review**, that is also valid. Verify the lens name against the live documentation, then fetch only that lens's documentation and evaluate against it. Prefix the standalone lens report with the same `> **Classification: CONFIDENTIAL** — …` banner the other review modes use — a lens review still surfaces sensitive infrastructure detail and unremediated findings.

## Discover available lenses

Do not rely on a hardcoded lens inventory. At review time, use the retrieval ladder to search for `AWS Well-Architected Lenses` and locate the lenses landing page, then use the published documentation as the authoritative list of available lenses and their current names. If no documentation access exists, use internal knowledge and disclose that the available-lens list could not be verified live. Treat workload characteristics as signals to search for a relevant lens, not proof that a particular lens exists.
