# Lens Guidance — Applying Well-Architected Lenses

Lenses are **additive** — they expand the core framework questions with domain-specific best practices. They do NOT replace the framework questions.

## When to apply a lens

- The workload clearly matches the documented scope of a lens discovered from the live AWS documentation
- The user explicitly asks for a lens-specific review

## How to apply

Use this retrieval ladder for every lens lookup:

1. Use `aws___search_documentation` / `aws___read_documentation` when the AWS MCP server is available.
2. Otherwise, use the environment's web-search or web-fetch tool only over HTTPS against `docs.aws.amazon.com`. Do not use plain HTTP or retrieve lens guidance from other domains.
3. If no tool could read the lens documentation (each of those tools the session has actually returned an error, or it has none; a web-fetch error that names a passing condition, such as a timeout, a 429 or 5xx status or a failed domain safety check, counts only after three more attempts, as for framework pages; record the raw errors), stop and ask the user (an instruction to proceed without pausing or without confirmation is that agreement: then do not ask). Only on the user's explicit agreement proceed from internal knowledge, title-based, and disclose that limitation together with `Lens BP pages read: 0 / {m} (unverified: lens size from internal knowledge; the lens documentation could not be read)`.

- First complete the core framework evaluation (every framework question)
- Then fetch the lens documentation at review time using the retrieval ladder. Search for `AWS Well-Architected {lens name} Lens`, read the lens's per-pillar best-practice pages, and evaluate the additional lens-specific best practices. Lens best practices use the same reader/judge row format and full-read rules as framework BPs (see the [evaluation procedure](evaluation-procedure.md)), and the same row self-check, but the shard plan and progress file cover framework BPs only. Keep lens rows out of the framework shard files and `corpus/progress.md` (write them to `aws-well-architected-review-ledger/lens.md`) and out of the JSON `ledger[]`, and report them only under Lens Findings; a lens BP whose page cannot be read is recorded as `page_unreadable` (Cannot Determine), never judged from its title, and the Lens Findings section states `Lens BP pages read: {n} / {m}` and lists the unreadable ones
- Report lens findings in a separate section after the core findings

**If the user ONLY asks for a named lens review**, that is also valid. Verify the lens name against the live documentation, then fetch only that lens's documentation and evaluate against it. Prefix the standalone lens report with the same `> **Classification: CONFIDENTIAL** — …` banner the other review modes use — a lens review still surfaces sensitive infrastructure detail and unremediated findings — and open it with the Coverage Audit: the run line, `Lens BP pages read: {n} / {m}` and the `Review Integrity:` line ([report template](../assets/report-template.md)).

## Discover available lenses

Do not rely on a hardcoded lens inventory. At review time, use the retrieval ladder to search for `AWS Well-Architected Lenses` and locate the lenses landing page, then use the published documentation as the authoritative list of available lenses and their current names. If no tool could read it (the rule of step 3 above, retries included), stop and ask the user, unless they said to proceed without pausing or without confirmation, which is that agreement; only on their agreement use internal knowledge and disclose that the available-lens list could not be verified live. Treat workload characteristics as signals to search for a relevant lens, not proof that a particular lens exists.
