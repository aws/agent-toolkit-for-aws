# Phase: Live corpus inventory (ACQUIRE_CORPUS)

Sections: [Retrieval mechanism](#retrieval-mechanism) · [Primary source: the TOC index](#primary-source--the-toc-index) · [Reading the index](#reading-the-index-bounded) · [Inventory records](#inventory-records) · [Manifest and self-check](#manifest-and-self-check-must-pass-before-assess) · [Recovery (fallback traversal)](#recovery-fallback-traversal) · [Freshness](#freshness) · [Transition](#transition)

Build a **complete, self-checked inventory** of every live Well-Architected
question and best practice **before any assessment begins**. `ASSESS` MUST NOT
start until the manifest self-check below passes. You read the index and write
the records yourself with the client's file tools; nothing here is a program.

## Retrieval mechanism

Use the AWS MCP server's documentation reader — `aws___read_documentation`
(call shape: `{"requests":[{"url": "...", "max_length": 20000, "start_index": 0}]}`) —
when the session has it (a listed tool that must first be loaded counts as present).
Fetch the same `docs.aws.amazon.com` URL over HTTPS with the environment's web-fetch
tool when a call to the reader was actually attempted and returned an error, or from
the start when the session has no such reader: the AWS MCP server is recommended, not
required (the TOC index below is plain JSON that any HTTPS fetch returns intact; the
tool MUST return the raw text, not a summary). Only if no tool could read the index
(each documentation tool the session has actually returned an error, or it has none; a
web-fetch error that names a passing condition, such as a timeout, a 429 or 5xx status or a
failed domain safety check, counts only after three more attempts),
record the raw errors (`aws___read_documentation not available in this session` for a
missing reader) in the `errors` key of `corpus/manifest.json`, stop, and ask the user
before enumerating from internal knowledge. Only on the user's explicit
agreement (an instruction to proceed without pausing or without confirmation is that
agreement: then do not ask) proceed with a degraded, title-based run (`retrieval_method`:
`internal_knowledge_disclosed`) and disclose `BP pages read: 0 / N in scope` and that the
inventory could not be verified live. Do not depend on any
non-public/internal MCP, and do not use semantic search to enumerate.

Two facts that determine the method (both verified live):

- The reader **strips markdown link targets** from HTML/MD pages, so you cannot
  follow links between pages and MUST NOT guess or abbreviate page slugs.
- The framework publishes a machine-readable **table-of-contents index**, and the
  reader returns it verbatim. This index is the corpus source.

## Primary source — the TOC index

Read the framework table of contents:

```text
https://docs.aws.amazon.com/wellarchitected/latest/framework/toc-contents.json
```

It returns a JSON tree of the whole framework. Pillars are NOT top-level — they sit
under the appendix node (live title "Appendix: Questions and best practices"), and
there's an extra "Category" grouping level between a pillar and its questions:

```json
{ "contents": [
  { "title": "Abstract", "href": "abstract.html" },
  { "title": "The pillars of the framework", "href": "the-pillars-of-the-framework.html" },
  { "title": "Appendix: Questions and best practices", "href": "appendix.html", "contents": [
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

Classify nodes structurally — by parent/child relationship, not by matching URL
patterns — so opaque or renamed hrefs never break discovery:

- **Appendix node** — the top-level node whose title begins with "Appendix"
  (case-insensitive prefix match; the live title is "Appendix: Questions and best
  practices", and a bare "Appendix" must also match). Record `appendix_match: "title"`.
  If no top-level title starts with "Appendix", use the one top-level node whose subtree
  holds the most best-practice nodes and record `appendix_match: "structure"`, so title
  wording can drift without breaking discovery. The inventory fails (`valid: false`) when
  no top-level node holds any best-practice node, or when two or more top-level nodes tie
  for the most. A title match with no best-practice nodes beneath it fails with
  `zero best practices parsed`.
- **Pillar node** — a direct child of the Appendix node. Do not hardcode which
  pillars exist or how many — discover them structurally so a newly added or renamed
  pillar is still covered. Pillar hrefs carry an "a-" prefix (`a-operational-excellence.html`),
  but so do Category nodes (`a-data-protection.html` under Security), so the prefix is not a
  pillar marker. The index arrives minified on one line, so counting brackets by hand is
  error-prone; use this cue instead: a new pillar starts where the BP ID prefix changes (`OPS`,
  then `SEC`, ...), its title is the nearest preceding node that is a direct child of the
  Appendix node, and a pillar's subtree has closed once a BP with the next prefix appears (or
  the Appendix node ends). `pillar_id` is the pillar title in lowercase with spaces
  replaced by hyphens (`operational-excellence`).
- **Best-practice node** — `title` matches `^[A-Z]{2,5}\d{2}-BP\d{2}\b`.
  Record: `bp_id` (the matched ID), `bp_title` (the remainder of the title),
  the `href` exactly as written in the node, and `question_id` (the `PILLAR##` prefix of the matched ID).
- **Question node** — structurally, any node whose direct children include at least
  one best-practice node. Do NOT match by `href` pattern: `^[a-z]{2,5}-\d{2}\.html$`
  matches 56 of the 57 real question nodes — Sustainability's SUS 1 ships at an opaque
  generated href with no recognizable stem, and a pattern match silently drops it. The
  structural rule (parent-of-a-BP-node) finds all 57 because it never depends on the
  href shape.
- **`pillar_id`/`pillar_name`** — NOT "the enclosing node's title" one level up (that
  resolves to the Category node, e.g. "Organization"/"Prepare", because of the
  Pillar → Category → Question → BP nesting). Climb ancestors from the BP node until you
  reach the node whose own parent is the Appendix node — that is the pillar node — and use its title.

Base for relative `href`s: `https://docs.aws.amazon.com/wellarchitected/latest/framework/`.
A BP's URL is always `base + href` from its TOC node — never construct it from the ID or title.

Notes:

- Derive the set of questions from the **BP prefixes** (every `SEC02-BP0x` implies
  question `SEC02`); take each question's title and href from its question node. This is
  robust to the index listing best practices under both the pillar and appendix
  branches — **dedupe best practices by `bp_id`**.
- The BP detail pages are NOT read during this stage; they are read in full during
  Step 5, one small shard at a time, and reading every in-scope page there is mandatory
  (see the [evaluation procedure](evaluation-procedure.md)).

## Reading the index (bounded)

The index is about 55 KB. When the session has no `aws___read_documentation`, read it with the
web-fetch tool instead, in as many parts as that tool returns. Otherwise read it with
`aws___read_documentation` in slices:
`max_length` 20000 and `start_index` 0, then the previous response's `end_index`, until
`truncated` is false and `end_index` equals `total_length` (about 3 calls). Note
`total_length`, which you record in the manifest as `index_total_length`. The slices meet exactly at each
`end_index`, so a node can be split across two slices: join the boundary text before
you classify it.

Work through the slices in order. After each slice, write the inventory file of every
pillar whose subtree has closed in the text you have read, and carry an open pillar to the
next slice. Never re-quote the raw index in a message and never write it to a file; the
inventory files are the only copy you keep. If a slice read fails, retry it once from
the same `start_index`; if it still fails, use the web-fetch tool for the index
(`retrieval_method` `https_toc_index`), else go to Recovery.

## Inventory records

Create `corpus/inventory/` in the scratch directory and write one file per pillar,
`corpus/inventory/<pillar_id>.md`, in one write each (about 1.5-3K tokens for the largest
pillar). Scratch state only, never part of the delivered report. If the working
directory is backed by persistent storage, ensure encryption at rest is enabled (see
[security considerations](security-considerations.md)). Format, one line per question
and one line per BP, in TOC order:

```text
# Inventory: Operational excellence
pillar_id: operational-excellence
base: https://docs.aws.amazon.com/wellarchitected/latest/framework/
retrieved_at: 2026-09-08T12:00:00Z

## OPS01 | OPS 1. How do you determine what your priorities are? | ops-01.html
- OPS01-BP01 | Evaluate external customer needs | ops_priorities_ext_cust_needs.html
- OPS01-BP02 | Evaluate internal customer needs | ops_priorities_int_cust_needs.html

counts: questions 11 · best practices 68
```

Each list line (starting with a hyphen) is one BP record (`bp_id | bp_title | href`); its
`question_id` is the question line (starting with `##`) above it, its `bp_url` is
`base + href`. Copy every `href` character for character from the index. The `counts`
line is the number of question lines and BP lines you wrote, counted after writing,
each distinct ID once.

## Manifest and self-check (must pass before ASSESS)

**Count from the enumerated IDs.** Before you write any total, enumerate the BP IDs you
actually found under each pillar in the index text you read: the BP lines of that pillar's
inventory file, each distinct ID once (a BP the index lists twice is counted once). Each
pillar's `bps_per_pillar` value MUST equal the number of distinct BP IDs enumerated for it,
`bp_total` MUST equal the number of distinct BP IDs across all pillars, and the per-pillar
values MUST add up to `bp_total`; the same holds for the question IDs, `questions_per_pillar`
and `question_total`. A total is never estimated, recalled, or taken from an example or an
earlier review: a declared total that differs from the enumerated IDs is an error, so record
it in `errors`, re-derive the IDs from the index (re-read the affected slice) and correct it.

Write `corpus/manifest.json` last, in one small write, with exactly these 12 keys:

```json
{
  "valid": true,
  "retrieval_method": "mcp_toc_index",
  "source": "https://docs.aws.amazon.com/wellarchitected/latest/framework/toc-contents.json",
  "retrieved_at": "2026-09-08T12:00:00Z",
  "pillar_total": 6,
  "question_total": 57,
  "bp_total": 307,
  "index_total_length": 55041,
  "appendix_match": "title",
  "questions_per_pillar": { "operational-excellence": 11 },
  "bps_per_pillar": { "operational-excellence": 68 },
  "errors": []
}
```

The values above are illustrative (the per-pillar maps show one pillar of six).
`retrieval_method` is one of `mcp_toc_index` (the MCP reader), `https_toc_index` (the
web-fetch tool, after a real MCP error or with no MCP reader in the session), `mcp_fallback_traversal`,
`https_fallback_traversal` or `internal_knowledge_disclosed`. `source` is the index URL
actually read (the appendix or landing-page URL on the fallback path), `retrieved_at` the
UTC time of that read (ISO 8601 with a `Z` suffix), and `errors` lists the reasons the
self-check failed (empty when `valid` is true). `index_total_length` is the `total_length`
the reader reported for the index (on the fallback path, or when the web-fetch tool reports
no length, `null`). The fallback path adds a
thirteenth key, `notes`, for the SUS 1 gap. On the `internal_knowledge_disclosed` path no index
was read: set `source` to `""`, `retrieved_at` to the UTC time of the last failed retrieval
attempt, `appendix_match` and `index_total_length` to `null`, and record the raw errors in
`errors`. That manifest only records the failed retrieval; it is not a frozen inventory: write
no inventory files, set `valid` to `false` (the self-check below has nothing read to check),
set `pillar_total`, `question_total` and `bp_total` to the totals you recall, which the
report discloses as recalled and unverified, and set `questions_per_pillar` and
`bps_per_pillar` to empty objects (`{}`), since no per-pillar inventory exists on this path. No BP page is read on this path, so the Step 4
gate does not apply: the run continues title-based only on the user's agreement
([evaluation procedure](evaluation-procedure.md), 5c), and every BP ID it cites follows that
procedure's recalled-ID rule.

**Manifest self-check.** Set `valid` to `true` only after you have confirmed every item
below against the inventory files you wrote (re-read them; they are small). Any failed
item is written to `errors` with `valid: false`, and you fix the inventory (re-read the
affected index slice) before Step 5:

- Every pillar discovered among the Appendix node's direct children has an inventory
  file, and each carries at least one best practice (do not assert a fixed pillar
  count — a newly added pillar must not fail this check).
- Every BP ID matches canonical `PILLAR##-BP##`; BP IDs are unique after dedupe.
- Every BP line has a non-empty `href`, so its `bp_url` is an `https://docs.aws.amazon.com/`
  URL (HTTPS only). A BP without a usable URL cannot be read in Step 5 and fails the check
  (except on the fallback or `internal_knowledge_disclosed` path below, where `href` may be empty).
- Question IDs are unique; every question has at least one BP; every BP's ID prefix is the
  ID of the question it sits under.
- For each pillar, its `bps_per_pillar` value equals the number of distinct BP IDs you
  enumerated in its inventory file (counted line by line, duplicates once, not estimated)
  and its `questions_per_pillar` value the number of its distinct question IDs; each
  `counts` line matches its file; the per-pillar values add up to `bp_total` and
  `question_total`. A declared total that differs from the enumerated IDs fails this check:
  re-derive it from the TOC index, never estimate it.
- Provenance (index URL `source`, retrieval time `retrieved_at`, `index_total_length`) is recorded; no
  stale manifest is silently reused as live content.

These checks are yours; they are not machine-verified, so do them against the files, not
from memory. A second check follows in Step 5: every BP page must open with its own BP ID,
and a `not_found` on a manifest URL first means re-checking that inventory line against the
index (see the evaluation procedure).

A parse that yields **zero** BP IDs is an acquisition failure — go to Recovery.
**Never invent a BP ID to fill a gap.** (The one exception is the title-based run without a
manifest, where the evaluation procedure, 5c, allows high-confidence recalled IDs tagged
unverified; it never fills a gap in an acquired manifest.) As a **post-hoc sanity check**,
confirm each discovered pillar carries a non-trivial number of best practices (> 0, with a
plausible spread across pillars rather than one pillar holding almost all of them) — do not
pin the check to specific question or BP totals. The parsed live index is the sole source
of truth for the inventory.

## Recovery (fallback traversal)

If `toc-contents.json` is unavailable (read or parse error) or yields no best practices:

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

   **Residual gap:** the lookahead window fixes boundary *detection* — it stops the
   traversal from terminating early at the `sus-01` 404 — but it does not recover SUS
   1's *content*. Because SUS 1 ships at an opaque generated slug rather than a
   `sus-NN` URL, this stem-based iteration never fetches it, and step 3's relocation
   search below is scoped to relocating a moved page, never to supplying BP IDs
   directly. If this fallback path is used, record in the `notes` key of `corpus/manifest.json` and the
   coverage audit that SUS 1's best practices could not be retrieved via this path and
   are Cannot Determine — do not let a fallback-completed run appear fully covered
   when SUS 1 is actually missing.

   **BP page URLs on the fallback path:** question pages list BP titles only and guessed
   BP slugs 404, so the BP URL is not known from traversal. Leave `href` empty in the
   inventory; do not search for URLs in this stage. The Step 5 reader locates each page
   (see the reader prompt in the [evaluation procedure](evaluation-procedure.md)), logs the
   query and result for every BP, writes the located URL into the row's `url`, and must then
   read the page with the same full-read and quote proof. A BP whose URL cannot be located is
   `page_unreadable` and counts toward the Step 5c cap, so more than a few unlocatable URLs
   block the report.

   **The page suffix and missing-page signal are the same for both retrieval tools —
   use the `.md` form for both, never `.html`, for this fallback traversal** (verified
   live): `<base><stem>-NN.md`.
   - **`aws___read_documentation`:** stops when a read returns the reader's sentinel
     string `"Documentation page not found."`.
   - **Non-MCP HTTPS web-fetch fallback:** requesting the `.md` form returns a clean
     200 `text/markdown` when the page exists and a clean 404 when it does not — the
     same unambiguous signal as the MCP path. Do NOT request the `.html` form for this
     fallback: a missing `.html` page 302-redirects to the framework root and then
     returns 200, so it never produces a 404 and the traversal cannot terminate.
3. To relocate a specific moved page (or locate a BP page URL on the fallback path), use `aws___search_documentation` when the AWS MCP server is
   available; otherwise use the environment's web-search tool scoped to `docs.aws.amazon.com` over
   HTTPS; if neither is available, skip the relocated page and note the gap in the coverage audit (for a BP page URL on the fallback path, record that BP as `page_unreadable` with `error_code` `not_found` instead, so it counts toward the Step 5c cap).
   Use this ONLY to relocate a moved page or (in Step 5) to locate a BP page URL — never to supply BP IDs.

## Freshness

Read the index live for every review. Do not reuse a prior run's manifest as current
content unless the user explicitly authorizes a cache whose freshness policy is
disclosed in the coverage audit. The one exception is a resume the user explicitly asked
for: the same interrupted run, whose `.wa-review-run` pointer matches the request, with a
valid `corpus/manifest.json` and a `corpus/progress.md`, keeps its frozen manifest (see
[bounded execution](bounded-execution.md)). Every other review request is a new run with a
new run id and scratch directory: it never reads an earlier run's pointer, manifest,
progress file, ledger or report.

## Transition

`ACQUIRE_CORPUS -> ASSESS` only when `corpus/manifest.json` records `valid: true` after the
self-check. The frozen manifest and its inventory files are the sole authority for the
expected question and BP sets used by evaluation, the coverage audit and the report.
