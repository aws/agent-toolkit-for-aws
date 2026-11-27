# Phase: Live corpus inventory (ACQUIRE_CORPUS)

Sections: [Retrieval mechanism](#retrieval-mechanism) · [Primary source: the TOC index](#primary-source--the-toc-index) · [Reading the index](#reading-the-index-bounded) · [Inventory records](#inventory-records) · [Manifest and self-check](#manifest-and-self-check-must-pass-before-assess) · [Recovery (fallback traversal)](#recovery-fallback-traversal) · [Freshness](#freshness) · [Transition](#transition)

Build a **complete, self-checked inventory** of every live Well-Architected
capability and best practice **before any assessment begins**. `ASSESS` MUST NOT
start until the manifest self-check below passes. You read the index and write
the records yourself with the client's file tools; nothing here is a program.

Two terms used throughout this skill:

- **Unit** — a group of best practices that share one ID prefix: each of the six
  workload pillars, and Cloud Foundations (prefix `FND`). Units are discovered from the
  index, never assumed.
- **Capability** — the node that holds best practices directly (for example
  `OPS01 Observe from multiple perspectives`), called a question in earlier framework
  versions. The `question_id` and `questions` keys of the skill's files keep their names;
  they hold capabilities.

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

It returns a JSON tree of the whole framework. Units are NOT necessarily top-level, and
the depth from a top-level node to its best practices differs between units. In the
current framework, Cloud Foundations is itself a top-level node
whose children are its capabilities, while the six workload pillars sit one level lower,
under a top-level "Cloud Workloads" node, each with its capabilities as children
(abridged; illustrative titles):

```json
{ "contents": [
  { "title": "Abstract and introduction", "href": "framework.html" },
  { "title": "Cloud Foundations", "href": "cloud-foundations.html", "contents": [
    { "title": "Design principles", "href": "fnd-design-principles.html" },
    { "title": "Multi-account environment", "href": "fnd01.html", "contents": [
      { "title": "FND01-BP01 Establish management account and organizational structure", "href": "fnd01-bp01.html" },
      { "title": "FND01-BP02 Establish ownership for billing, security, and operations", "href": "fnd01-bp02.html" }
    ] }
  ] },
  { "title": "Cloud Workloads", "href": "workloads.html", "contents": [
    { "title": "Operational excellence", "href": "operational-excellence.html", "contents": [
      { "title": "Design principles", "href": "ops-design-principles.html" },
      { "title": "Observe from multiple perspectives", "href": "ops01.html", "contents": [
        { "title": "OPS01-BP01 Develop application telemetry", "href": "ops01-bp01.html" },
        { "title": "OPS01-BP02 Develop user experience telemetry", "href": "ops01-bp02.html" }
      ] }
    ] },
    { "title": "Security", "href": "security.html", "contents": [
      { "title": "Securely operate your workload", "href": "sec01.html", "contents": [
        { "title": "SEC01-BP01 Separate workloads using accounts", "href": "sec01-bp01.html" }
      ] }
    ] }
  ] },
  { "title": "Notices", "href": "notices.html" }
] }
```

Classify nodes structurally — by parent/child relationship and the BP IDs beneath a
node, not by matching node titles or URL patterns — so renamed nodes and hrefs never break
discovery:

- **Best-practice node** — `title` matches `^[A-Z]{2,5}\d{2}-BP\d{2}\b`.
  Record: `bp_id` (the matched ID), `bp_title` (the remainder of the title),
  the `href` exactly as written in the node, and `question_id` (the `PREFIX##` part of
  the matched ID, the capability's ID: `FND01`, `SEC02`).
- **Unit node** (a pillar, or Cloud Foundations) — for each best-practice node, climb
  its ancestors and take the shallowest ancestor whose subtree contains best-practice
  IDs of exactly one alphabetic prefix (for example OPS, SEC, REL, PERF, COST, SUS,
  FND, or any prefix a future release adds). That node is the unit. Do not require an
  "Appendix" node, do not assume a Category level between a unit and its capabilities,
  and do not hardcode which units exist or how many. `pillar_id` is the unit title in
  lowercase with spaces replaced by hyphens (`cloud-foundations`,
  `operational-excellence`), and `pillar_name` is the unit title. A node whose subtree
  holds two or more prefixes (such as "Cloud Workloads") is never a unit; it contains
  units. Record `appendix_match: "prefix_group"` (the values `title` and `structure` are
  read only in manifests from earlier versions of this skill; this version writes
  `prefix_group`).
- **Capability node** — structurally, any node whose direct children include at least
  one best-practice node. Do NOT match by `href` pattern: capability hrefs have changed shape
  before (`ops-01.html` became `ops01.html`) and can change again.
  The structural rule (parent of a BP node) never depends on the href shape.
- **`pillar_id`/`pillar_name` of a BP** — NOT "the enclosing node's title" one level up
  (that is the capability node). Climb ancestors from the BP node to its unit node, as
  defined above, and use that node's title.

The index arrives minified on one line, so counting brackets by hand is error-prone; use
this cue instead: a new unit starts where the BP ID prefix changes (`FND`, then `OPS`,
then `SEC`, ...); its node is the nearest preceding unit node, which in practice is the
nearest preceding node whose direct children are that prefix's capability nodes (a node
such as "Cloud Workloads", whose children are units, is skipped); and a unit's subtree has
closed once a BP with the next prefix appears, or the index ends. When a unit's subtree
closes, confirm it holds one prefix only: if it holds two, the unit is the lower node that
holds each prefix alone.

Base for relative `href`s: `https://docs.aws.amazon.com/wellarchitected/latest/framework/`.
A BP's URL is always `base + href` from its TOC node — never construct it from the ID or title.

Notes:

- Derive the set of capabilities from the **BP prefixes** (every `SEC02-BP0x` implies
  capability `SEC02`); take each capability's title and href from its capability node.
  This is robust to the index listing a best practice in more than one place —
  **dedupe best practices by `bp_id`**.
- The BP detail pages are NOT read during this stage; they are read in full during
  Step 5, one small shard at a time, and reading every in-scope page there is mandatory
  (see the [evaluation procedure](evaluation-procedure.md)).

## Reading the index (bounded)

The index is a few tens of KB (its size changes with each framework release; record the
`total_length` you are given, never an expected size). When the session has no `aws___read_documentation`, read it with the
web-fetch tool instead, in as many parts as that tool returns. Otherwise read it with
`aws___read_documentation` in slices:
`max_length` 20000 and `start_index` 0, then the previous response's `end_index`, until
`truncated` is false and `end_index` equals `total_length` (a few calls). Note
`total_length`, which you record in the manifest as `index_total_length`. The slices meet exactly at each
`end_index`, so a node can be split across two slices: join the boundary text before
you classify it.

Work through the slices in order. After each slice, write the inventory file of every
unit whose subtree has closed in the text you have read, and carry an open unit to the
next slice. Never re-quote the raw index in a message and never write it to a file; the
inventory files are the only copy you keep. If a slice read fails, retry it once from
the same `start_index`; if it still fails, use the web-fetch tool for the index
(`retrieval_method` `https_toc_index`), else go to Recovery.

## Inventory records

Create `corpus/inventory/` in the scratch directory and write one file per unit,
`corpus/inventory/<pillar_id>.md`, in one write each (about 1.5-3K tokens for the largest
unit). Scratch state only, never part of the delivered report. If the working
directory is backed by persistent storage, ensure encryption at rest is enabled (see
[security considerations](security-considerations.md)). Format, one line per capability
and one line per BP, in TOC order (the example is abridged and its values illustrative):

```text
# Inventory: Cloud Foundations
pillar_id: cloud-foundations
base: https://docs.aws.amazon.com/wellarchitected/latest/framework/
retrieved_at: 2026-11-16T12:00:00Z

## FND01 | Multi-account environment | fnd01.html
- FND01-BP01 | Establish management account and organizational structure | fnd01-bp01.html
- FND01-BP02 | Establish ownership for billing, security, and operations | fnd01-bp02.html

counts: capabilities 7 · best practices 45
```

Each list line (starting with a hyphen) is one BP record (`bp_id | bp_title | href`); its
`question_id` is the capability line (starting with `##`) above it, its `bp_url` is
`base + href`. Copy every `href` character for character from the index. The `counts`
line is the number of capability lines and BP lines you wrote, counted after writing,
each distinct ID once.

## Manifest and self-check (must pass before ASSESS)

**Count from the enumerated IDs.** Before you write any total, enumerate the BP IDs you
actually found under each unit in the index text you read: the BP lines of that unit's
inventory file, each distinct ID once (a BP the index lists twice is counted once). Each
unit's `bps_per_pillar` value MUST equal the number of distinct BP IDs enumerated for it,
`bp_total` MUST equal the number of distinct BP IDs across all units, and the per-unit
values MUST add up to `bp_total`; the same holds for the capability IDs, `questions_per_pillar`
and `question_total`. A total is never estimated, recalled, or taken from an example or an
earlier review: a declared total that differs from the enumerated IDs is an error, so record
it in `errors`, re-derive the IDs from the index (re-read the affected slice) and correct it.

Write `corpus/manifest.json` last, in one small write, with exactly these 12 keys (the
`pillar` and `question` key names are kept from earlier versions: `pillar_total` counts
units, Cloud Foundations included, and the `question` keys count capabilities):

```json
{
  "valid": true,
  "retrieval_method": "mcp_toc_index",
  "source": "https://docs.aws.amazon.com/wellarchitected/latest/framework/toc-contents.json",
  "retrieved_at": "2026-11-16T12:00:00Z",
  "pillar_total": 7,
  "question_total": 57,
  "bp_total": 261,
  "index_total_length": 48000,
  "appendix_match": "prefix_group",
  "questions_per_pillar": { "cloud-foundations": 7 },
  "bps_per_pillar": { "cloud-foundations": 45 },
  "errors": []
}
```

The values above are illustrative (the per-unit maps show one unit of seven, and
`index_total_length` is a placeholder for the length you are given), never totals to copy.
`retrieval_method` is one of `mcp_toc_index` (the MCP reader), `https_toc_index` (the
web-fetch tool, after a real MCP error or with no MCP reader in the session), `mcp_fallback_traversal`,
`https_fallback_traversal` or `internal_knowledge_disclosed`. `source` is the index URL
actually read (the framework landing-page URL on the fallback path), `retrieved_at` the
UTC time of that read (ISO 8601 with a `Z` suffix), and `errors` lists the reasons the
self-check failed (empty when `valid` is true). `index_total_length` is the `total_length`
the reader reported for the index (on the fallback path, or when the web-fetch tool reports
no length, `null`). `appendix_match` is `prefix_group` on the index paths and `null` on the
fallback and `internal_knowledge_disclosed` paths. On the `internal_knowledge_disclosed` path no index
was read: set `source` to `""`, `retrieved_at` to the UTC time of the last failed retrieval
attempt, `appendix_match` and `index_total_length` to `null`, and record the raw errors in
`errors`. That manifest only records the failed retrieval; it is not a frozen inventory: write
no inventory files, set `valid` to `false` (the self-check below has nothing read to check),
set `pillar_total`, `question_total` and `bp_total` to the totals you recall, which the
report discloses as recalled and unverified, and set `questions_per_pillar` and
`bps_per_pillar` to empty objects (`{}`), since no per-unit inventory exists on this path. No BP page is read on this path, so the Step 4
gate does not apply: the run continues title-based only on the user's agreement
([evaluation procedure](evaluation-procedure.md), 5c), and every BP ID it cites follows that
procedure's recalled-ID rule.

**Manifest self-check.** Set `valid` to `true` only after you have confirmed every item
below against the inventory files you wrote (re-read them; they are small). Any failed
item is written to `errors` with `valid: false`, and you fix the inventory (re-read the
affected index slice) before Step 5:

- Every unit found by the prefix rule has an inventory file, and each carries at least
  one best practice (do not assert a fixed unit count — a newly added unit must not fail
  this check).
- Every top-level node whose subtree contains at least one best-practice ID is either a
  unit or contains units. If any best-practice ID in the index you read sits outside
  every unit you recorded, the inventory fails: set `valid: false` and record in
  `errors` the node's title and the BP prefixes beneath it.
- Every BP ID matches canonical `PREFIX##-BP##`; BP IDs are unique after dedupe.
- Every BP line has a non-empty `href`, so its `bp_url` is an `https://docs.aws.amazon.com/`
  URL (HTTPS only). A BP without a usable URL cannot be read in Step 5 and fails the check
  (except on the fallback or `internal_knowledge_disclosed` path below, where `href` may be empty).
- Capability IDs are unique; every capability has at least one BP; every BP's ID prefix is
  the ID of the capability it sits under.
- For each unit, its `bps_per_pillar` value equals the number of distinct BP IDs you
  enumerated in its inventory file (counted line by line, duplicates once, not estimated)
  and its `questions_per_pillar` value the number of its distinct capability IDs; each
  `counts` line matches its file; the per-unit values add up to `bp_total` and
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
confirm each discovered unit carries a non-trivial number of best practices (> 0, with a
plausible spread across units rather than one unit holding almost all of them) — do not
pin the check to specific capability or BP totals. The parsed live index is the sole source
of truth for the inventory.

## Recovery (fallback traversal)

If `toc-contents.json` is unavailable (read or parse error) or yields no best practices:

1. Retry the index read once.
2. If still failing, fall back to **construct-and-iterate** over capability pages, which
   the reader supports even though it strips links. The unit stems change
   extremely rarely and the unit landing pages are too sparse to derive them
   from (they carry no `PREFIX##-BP##` IDs to anchor a structural discovery) — for this
   fallback path only, use the current explicit list:
   `fnd` (Cloud Foundations), `ops` (Operational Excellence), `sec` (Security), `rel`
   (Reliability), `perf` (Performance Efficiency), `cost` (Cost Optimization), `sus`
   (Sustainability). The no-hardcode rule stays for the primary TOC-index path above,
   which discovers units structurally; this fallback is already a last resort, and the
   coverage audit names the stems it used.

   For each stem, read `<base><stem>01`, `02`, … (i.e. `<stem>NN`, two digits, no hyphen:
   `fnd01`, `sus04`), incrementing. **Use a lookahead window of at least 2 consecutive
   missing pages before declaring the unit boundary** — do not stop at the first miss, so
   a single missing or moved capability page does not end the unit early. A page counts as
   a **hit** only when it lists at least one BP ID whose prefix is that stem's capability
   (`SUS04-BP01` on `sus04`). A not-found response, a landing or redirect page, a
   bot-check or error page, or a page with no matching BP ID is a **miss**, never a hit.
   Each capability page lists its `PREFIX##-BP##` IDs as text; derive `question_id` from
   the BP prefix (not from the page heading).

   **BP page URLs on the fallback path:** the URL is not taken from traversal. For each
   BP, try `<base><bp_id in lowercase>.md` (for example `fnd01-bp01.md`) and accept it
   only when the page opens with that same BP ID; otherwise leave `href` empty in the
   inventory. The Step 5 reader locates a page that was not accepted (see the reader
   prompt in the [evaluation procedure](evaluation-procedure.md)), logs the query and
   result for every such BP, writes the located URL into the row's `url`, and must then
   read the page with the same full-read and quote proof. A BP whose URL cannot be located is
   `page_unreadable` and counts toward the Step 5c cap, so more than a few unlocatable URLs
   block the report.

   **The page suffix and missing-page signal are the same for both retrieval tools —
   use the `.md` form for both, never `.html`, for this fallback traversal**:
   `<base><stem>NN.md`.
   - **`aws___read_documentation`:** a miss is a read that returns the reader's sentinel
     string `"Documentation page not found."` (or any other miss as defined above).
   - **Non-MCP HTTPS web-fetch fallback:** requesting the `.md` form returns a clean
     200 `text/markdown` when the page exists and a clean 404 when it does not — the
     same unambiguous signal as the MCP path. Do NOT request the `.html` form for this
     fallback: a missing `.html` page redirects to the framework landing page and then
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
expected capability and BP sets used by evaluation, the coverage audit and the report.
