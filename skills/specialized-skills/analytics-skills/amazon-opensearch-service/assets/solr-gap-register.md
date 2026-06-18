# Gap Register Skeleton

Use this table verbatim in section **6. Feature Gap Register** of [report-template](report-template.md). Add one row per finding surfaced by Steps 3, 4, and 6 of the workflow. Severity + Lane vocabulary comes from the canonical rubric in [compatibility-rubric](../references/compatibility-rubric.md).

| # | Feature | Solr behavior | OpenSearch alternative | Severity | Lane | Effort | Owner action |
|---|---------|---------------|------------------------|----------|------|--------|--------------|
| 1 | _e.g. eDisMax `mm`_ | _Cross-field minimum-should-match expression_ | `multi_match` + `minimum_should_match` | LOW | migration-specific | S | Translate per [solr-query-behavior-edge-cases](../references/solr-query-behavior-edge-cases.md); validate parity. |
| 2 | _e.g. Custom RequestHandler_ | _Java plugin invoked at query time_ | OpenSearch Search Pipeline (2.9+) or client logic | BLOCKING | risk-blocker | L | Rewrite as a search pipeline; smoke-test. |
| 3 | _e.g. Cross-collection join_ | `{!join fromIndex=...}` | Denormalize at index time, or two-query application-side join | BLOCKING | risk-blocker | M | Decide denormalize vs join at app layer. |
| 4 | _e.g. TrieIntField_ | Trie-indexed integer (deprecated since Solr 7+ in favor of `IntPointField`) | `integer` field type | MEDIUM | migration-specific | S | Recast values to native JSON numbers per [solr-transformation-rules](../references/solr-transformation-rules.md). |
| 5 | _e.g. Function query `recip()`_ | Score boost via Solr function query | `function_score` with `script_score` (Painless) | MEDIUM | risk-blocker | M | Translate; benchmark scoring deltas. |
| 6 | _e.g. cursorMark_ | Solr deep-paging cursor | `search_after` with sort tiebreaker | MEDIUM | migration-specific | S | Update client; deprecate `cursorMark` strings. |
| 7 | _e.g. Spatial `LatLonPointSpatialField`_ | `"lat,lon"` strings | `geo_point` objects | MEDIUM | migration-specific | S | Transform documents at index time. |
| 8 | _e.g. Date math `NOW-1DAY/DAY`_ | Solr date math | OpenSearch `now-1d/d` | LOW | migration-specific | S | Search-and-replace in queries and ISM policies. |

## Severity + Lane vocabulary

Severity values MUST come from the canonical rubric in [compatibility-rubric.md](../references/compatibility-rubric.md) §1 — BLOCKING / HIGH / MEDIUM / LOW only. Lane values MUST come from §2 of the same file — `migration-specific` (the migration plan already includes the remediation) or `risk-blocker` (the customer must act). Only `risk-blocker` rows deduct from the Compatibility readiness weight.

## Effort tiers

- **S** — small; isolated change, mechanical translation or config update.
- **M** — medium; touches multiple components or requires re-indexing.
- **L** — large; usually requires design review, custom code, or behavior validation.

## Constraints

- You MUST keep the column order exactly as shown because downstream tooling parses the table by column position.
- You MUST NOT remove a row to "simplify" the report because every flagged finding belongs in the register, even LOW-level, and removed rows hide findings.
- You MUST use the BLOCKING / HIGH / MEDIUM / LOW vocabulary in the Severity column. You MUST NOT use the legacy Breaking / Warning / Info labels because the canonical rubric in [compatibility-rubric](../references/compatibility-rubric.md) uses the four-tier vocabulary, and mixed labels will confuse the agent's downstream consumer.
- You MUST use the `migration-specific` / `risk-blocker` vocabulary in the Lane column. The Lane is what the FULL_ASSESSMENT §7 split routes by, and what the readiness scoring uses to decide if a row deducts from Compatibility (only `risk-blocker` rows deduct).
- You MUST link every row's "OpenSearch alternative" cell to the relevant reference file when one exists.
