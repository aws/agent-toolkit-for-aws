# Phase: Live corpus inventory (ACQUIRE_CORPUS)

Build a **complete, validated inventory** of every live Well-Architected
question and best practice **before any assessment begins**. `ASSESS` MUST NOT
start until the corpus validator passes.

## Retrieval mechanism

Prefer the AWS MCP server's documentation reader — `aws___read_documentation`
(call shape: `{"requests":[{"url": "...", "max_length": 100000}]}`) — when it is
available. When the AWS MCP server is unavailable, fetch the same
`docs.aws.amazon.com` URLs over HTTPS with the environment's web-fetch tool (the
TOC index below is plain JSON that any HTTPS fetch returns intact). If no
documentation access exists at all, enumerate from internal knowledge and disclose
that the inventory could not be verified live. Do not depend on any
non-public/internal MCP, and do not use semantic search to enumerate.

Two facts that determine the method (both verified live):

- The reader **strips markdown link targets** from HTML/MD pages, so you cannot
  follow links between pages and MUST NOT guess or abbreviate page slugs.
- The framework publishes a machine-readable **table-of-contents index**, and the
  reader returns it verbatim. This index is the corpus source.

## Primary source — the TOC index (one call)

Read the framework table of contents:

```
https://docs.aws.amazon.com/wellarchitected/latest/framework/toc-contents.json
```

It returns a JSON tree of the whole framework. Pillars are NOT top-level — they sit
under an "Appendix" node, and there's an extra "Category" grouping level between a
pillar and its questions:

```json
{ "contents": [
  { "title": "Abstract", "href": "abstract.html" },
  { "title": "The pillars of the framework", "href": "the-pillars-of-the-framework.html" },
  { "title": "Appendix", "href": "appendix.html", "contents": [
    { "title": "Operational excellence", "href": "a-operational-excellence.html", "contents": [
      { "title": "Organization", "href": "organization.html", "contents": [
        { "title": "OPS 1. How do you determine what your priorities are?", "href": "ops-01.html", "contents": [
          { "title": "OPS01-BP01 Evaluate external customer needs", "href": "ops_priorities_ext_cust_needs.html" },
          { "title": "OPS01-BP02 Evaluate internal customer needs", "href": "ops_priorities_int_cust_needs.html" }
        ] }
      ] }
    ] }
  ] },
  { "title": "Notices", "href": "notices.html" }
] }
```

Walk the tree recursively. Classify nodes structurally — by parent/child
relationship, not by matching URL patterns — so opaque or renamed hrefs never break
discovery:

- **Pillar node** — a direct child of the "Appendix" node. There are six today; do
  not hardcode which six — discover them structurally so a newly added pillar is
  still covered. Pillar hrefs carry an "a-" prefix (`a-operational-excellence.html`);
  strip it if you need the bare stem for a URL elsewhere, it carries no other meaning.
- **Best-practice node** — `title` matches `^[A-Z]{2,5}\d{2}-BP\d{2}\b`.
  Record: `bp_id` (the matched ID), `bp_title` (the remainder of the title),
  `bp_url` (base + `href`), `question_id` (the `PILLAR##` prefix of the matched ID).
- **Question node** — structurally, any node whose direct children include at least
  one best-practice node. Do NOT match by `href` pattern: `^[a-z]{2,5}-\d{2}\.html$`
  matches 56 of the 57 real question nodes — Sustainability's SUS 1 ships at an opaque
  generated href with no recognizable stem, and a pattern match silently drops it. The
  structural rule (parent-of-a-BP-node) finds all 57 because it never depends on the
  href shape.
- **`pillar_id`/`pillar_name`** — NOT "the enclosing pillar node's title" (that
  resolves one level too shallow, to the Category node, e.g. "Organization"/"Prepare",
  because of the Pillar → Category → Question → BP nesting). Instead, climb ancestors
  from the BP node until you reach the node whose own parent is "Appendix" — that is
  the pillar node — and use its title.

Base for relative `href`s: `https://docs.aws.amazon.com/wellarchitected/latest/framework/`.

Notes:

- Derive the set of questions from the **BP prefixes** (every `SEC02-BP0x` implies
  question `SEC02`); enrich each with the title/URL from its question node when
  present. This is robust to the index listing best practices under both the pillar
  and appendix branches — **dedupe best practices by `bp_id`**.
- Everything needed for the ledger (canonical IDs + titles + URLs + question mapping)
  is in this one document. Do NOT read the individual best-practice pages here; fetch a
  single best-practice page later (during assessment) only when its title is
  insufficient to judge status or when writing a Critical/High recommendation.

## Immediate reduction (context discipline)

Parse the index into records in one pass and MUST NOT re-quote the raw index
afterward. Persist records as you go; do not narrate the tree.

## Records

Write one record per best practice to `corpus/best-practices.jsonl` and one per
question to `corpus/questions.jsonl`, in the run-local working directory you create at
the start of this stage (the `corpus/` folder — scratch state only, never part of the
delivered report). If that working directory is backed by persistent storage, ensure
encryption at rest is enabled (see [security considerations](security-considerations.md)).

Best-practice record (`wa-review.corpus.v1`):

```json
{
  "schema_version": "wa-review.corpus.v1",
  "pillar_id": "operational-excellence",
  "pillar_name": "Operational Excellence",
  "question_id": "OPS01",
  "question_title": "OPS 1. How do you determine what your priorities are?",
  "question_url": "https://docs.aws.amazon.com/wellarchitected/latest/framework/ops-01.html",
  "bp_id": "OPS01-BP01",
  "bp_title": "Evaluate external customer needs",
  "bp_url": "https://docs.aws.amazon.com/wellarchitected/latest/framework/ops_priorities_ext_cust_needs.html",
  "retrieved_at": "2026-09-08T12:00:00Z"
}
```

## Validation gate (must pass before ASSESS)

Write `corpus/manifest.json` with counts, per-pillar question counts, provenance
(index URL + UTC retrieval time), which retrieval path was actually used
(`retrieval_method`: one of `mcp_toc_index` / `https_toc_index` /
`mcp_fallback_traversal` / `https_fallback_traversal` / `internal_knowledge_disclosed`),
and a validation verdict. The validator MUST confirm:

- Every pillar discovered in the TOC top-level entries is represented, and each
  discovered pillar carries at least one best practice (do not assert a fixed pillar
  count — a newly added pillar must not fail this check).
- Every BP ID matches canonical `PILLAR##-BP##`; BP IDs are unique after dedupe.
- Question IDs are unique; every question has at least one BP.
- Every BP refers to a discovered question and pillar.
- The global BP set equals the union of per-question BP sets.
- Provenance (index URL, retrieval time) is recorded; no stale/cached manifest is
  silently reused as live content.

A parse that yields **zero** BP IDs, or fewer than a sanity floor, is an acquisition
failure — go to Recovery. **Never invent a BP ID to fill a gap.** As a **post-hoc
sanity check** recorded in the manifest, confirm each discovered pillar carries a
non-trivial number of best practices (> 0, with a plausible spread across pillars
rather than one pillar holding almost all of them) — do not pin the check to specific
question or BP totals. The parsed live index is the sole source of truth for the
inventory.

## Recovery (fallback traversal)

If `toc-contents.json` is unavailable (HTTP/parse error) or yields no best practices:

1. Retry the index read once.
2. If still failing, fall back to **construct-and-iterate** over question pages, which
   the reader supports even though it strips links. The six pillar stems change
   extremely rarely and the appendix/pillar landing pages are too sparse to derive them
   from (each is a 357–610 byte blurb with zero `PILLAR##-BP##` IDs to anchor a
   structural discovery) — for this fallback path only, use the current explicit list:
   `ops` (Operational Excellence), `sec` (Security), `rel` (Reliability), `perf`
   (Performance Efficiency), `cost` (Cost Optimization), `sus` (Sustainability). The
   no-hardcode rule stays for the primary TOC-index path above, which discovers pillars
   structurally; this fallback is already a last resort.

   For each stem, read `<base><stem>-01`, `-02`, … (i.e. `<stem>-NN`), incrementing.
   **Use a lookahead window of at least 2 consecutive missing pages before declaring
   the pillar boundary** — do not stop at the first miss. `sus-01` itself 404s
   (Sustainability's first question lives at an opaque generated slug, not the expected
   stem — the same fact that breaks the primary path's href-pattern question matching),
   so "stop at the first missing page" silently drops all of Sustainability; every
   genuine pillar boundary has 3+ consecutive misses, so a window of 2 safely
   distinguishes an interior gap from a real boundary. Each question page lists its
   `PILLAR##-BP##` IDs as text; derive `question_id` from the BP prefix (not the
   heading, which varies: `SEC 2.` vs `SUS 6`).

   **The page suffix and missing-page signal are the same for both retrieval tools —
   use the `.md` form for both, never `.html`, for this fallback traversal** (verified
   live): `<base>appendix.md`, then `<base><stem>-NN.md`.
   - **`aws___read_documentation`:** stops when a read returns the reader's sentinel
     string `"Documentation page not found."`.
   - **Non-MCP HTTPS web-fetch fallback:** requesting the `.md` form returns a clean
     200 `text/markdown` when the page exists and a clean 404 when it does not — the
     same unambiguous signal as the MCP path. Do NOT request the `.html` form for this
     fallback: a missing `.html` page 302-redirects to the framework root and then
     returns 200, so it never produces a 404 and the traversal cannot terminate.
3. To relocate a specific moved page, use `aws___search_documentation` when the AWS MCP server is
   available; otherwise use the environment's web-search tool scoped to `docs.aws.amazon.com` over
   HTTPS; if neither is available, skip the relocated page and note the gap in the coverage audit.
   Use this ONLY to relocate a moved page — never to supply BP IDs.

## Freshness

Read the index live for every review. Do not reuse a prior run's manifest as current
content unless the user explicitly authorizes a cache whose freshness policy is
disclosed in the coverage audit.

## Transition

`ACQUIRE_CORPUS -> ASSESS` only when `corpus/manifest.json` reports `valid: true`. The
frozen manifest is the sole authority for the expected question and BP sets used by
per-question validation, derivation, and the final report validator.
