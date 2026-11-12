# Retained native evidence, separate from the report

The HTML renderer takes Markdown plus the scoped `{ "items": [...] }` references for reported flaws, not a `{snapshotPath, model}` object. Follow [the Markdown template](../assets/report-template.md) and [the evidence contract](reporting.md). No acquisition helper ships.

Retain raw public list/get responses unchanged in private, Git-ignored evidence. If making a convenience snapshot for paging, preserve this information:

- Resolved signer account, credential selection, Region and environment; optional alias and any target mismatch; latest successful scan and latest attempt separately. Keep private identifiers in the raw ledger, redacted in shareable Limits.
- Source repository revision and source-binding confidence, with any mismatch explicit.
- Newest hydrated finding per Continuum issue, exact-code merge provenance, source-check locations and ratios, selected Open issues and PATCH preview metadata. Keep authoritative synopsis, summary, validation rationale and verdict unchanged.
- The union of list metadata and get bodies, including artifact `contentSizeBytes`, ID and type. Get values win overlaps; retain conflicting list values separately with provenance. Raw responses do not change.
- Every request's non-secret argv, start/end UTC timestamps and response path or error. Enclosing start is the earliest ledger start, including STS; enclosing end is the latest ledger end, including failures.
- Membership established through finding `scanRunId` and proven issue joins, never timestamps. Older repeats, unknown newest verdicts and unlinked candidates stay separately counted; do not list historical issue IDs in Limits.

Read retained slices for paging without AWS refresh. Preserve file hash, order, total, offset and next offset. Report capture failure or partial reads, never silently truncate. Start at 600 requests and 10 minutes, with at most four concurrent requests, and ask before expanding scope or budget. Evidence files are mode 0600 in a directory mode 0700; no automatic cache retention is provided.
