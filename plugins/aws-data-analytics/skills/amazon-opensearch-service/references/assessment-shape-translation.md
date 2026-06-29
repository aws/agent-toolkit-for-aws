# Shape recipe: TRANSLATION_TASK

## What this shape is

The user has a working query, request body, or DSL fragment in **another search engine** (Solr, Elasticsearch ≥ 7.11 syntax that needs OS-side adjustments, raw Lucene syntax, or vendor-specific dialect) and wants the **OpenSearch equivalent**. The deliverable is **drop-in JSON or code** that the user can paste into `_search`, `_msearch`, a client SDK call, or an OpenSearch Dashboards Dev Tools tab.

This shape is purely a **syntactic + semantic mapping exercise**. It is NOT a migration assessment, NOT a sizing exercise, and NOT a relevance-tuning engagement.

## When to dispatch here

Detect TRANSLATION_TASK when the user prompt contains any of:

- "translate this Solr query"
- "convert this DSL"
- "what's the OpenSearch equivalent of …"
- "rewrite this for OpenSearch"
- "this is my Solr `q=…&fq=…&qf=…`, give me OpenSearch JSON"
- A pasted Solr URL query string (`/select?q=…&qf=…&pf=…&mm=…&tie=…`)
- A pasted ES query that uses post-fork-only features (e.g. `runtime_mappings` in 7.12+, ES 8.x `knn` top-level field) and the user is targeting AOS managed
- A pasted Lucene `q=` string with field-prefix syntax (`title:headphones AND brand:sony`)

Do NOT dispatch here when:

- The user pasted `schema.xml` or an ES mapping → that's **SCHEMA_CONVERSION**.
- The user wants migration tooling guidance ("how do I move my Solr docs to OS") → that's **FULL_ASSESSMENT** or **FOCUSED_OPERATIONAL**.
- The user asks "how do I write a query that does X" with no source DSL → that's a search-recipe lookup; serve from `references/search-recipes.md` directly.

## Required output template

Produce these sections in order, nothing more:

### 1. Source restatement (1 sentence)

> "Translating Solr 8.11 eDisMax `q=wireless headphones&qf=title^3 description&pf=title^5&mm=2<-25%&q.op=AND&tie=0.3` to OpenSearch 2.x `_search`."

State source engine + version (if known) + the specific query type (eDisMax, dismax, standard, function query, JSON Facet API, …) + target endpoint.

### 2. Drop-in JSON / code (the deliverable)

A single fenced code block, valid JSON, ready to paste into Dev Tools. Preserve field names exactly. Include `query`, `from`/`size`, `sort`, `aggs`, `highlight` blocks as the source request had them.

### 3. Translation fidelity table

For every non-trivial Solr/ES parameter in the source, one row showing **source param → OpenSearch param → fidelity (verbatim / mapped / approximation)**. This is the **heart of the shape** — every syntactic element must be either preserved or explicitly mapped, with no silent drops.

### 4. Approximation caveats (inline, only if any rows in the table are "approximation")

A short bullet list of behavior drift the user must be aware of. Examples:

- **`pf` (phrase boost):** modeled as a `should` clause with `multi_match type: phrase`. Scoring shape differs — Solr's `pf` boosts the whole phrase score additively; OpenSearch's `should` adds a separately-scored phrase match. Re-tune boost values against your judgment list.
- **`tie_breaker` default:** OpenSearch `multi_match best_fields` defaults `tie_breaker: 0.0` (winner-takes-all); Solr eDisMax defaults `tie=0.0` as well, but if the source omitted `tie`, set it explicitly to avoid surprises if you later upgrade.
- **`q.op=AND`:** OpenSearch `query_string` defaults to OR. Set `default_operator: AND` explicitly or results will diverge.

### 5. Verification snippet (optional, 1–3 lines)

If the translation is non-trivial, give the user a 1-line `_validate/query?explain=true` or a 2-doc sanity check they can run to confirm the rewrite parses and scores reasonably.

## NOT REQUIRED — explicitly OMIT

Do NOT produce these sections in TRANSLATION_TASK:

- **Timeline & Resourcing** — removed from the suite. Do NOT estimate engineer-weeks, sprint count, or calendar duration anywhere.
- **Executive Summary** — translation is tactical, not a deliverable that needs an exec frame.
- **Source / Target / Migration Path / Risks** — the four big assessment sections; not applicable here.
- **Sizing / Readiness scorecard** — translation has no infra footprint.
- **Citations section** — only include if you make ≥3 version-volatile claims (e.g. "this only works in OS 2.13+"). For a normal Solr→OS query rewrite, citations are noise.
- **Migration tooling discussion** — do NOT pivot to "and to move your data, use Migration Assistant for Amazon OpenSearch Service…". Stay in the lane.
- **Dollar costs** — universal hard constraint; never produce a dollar figure.
- **Persona-aware framing** — the asker self-selected by pasting DSL; treat them as a search engineer.

## Solr → OpenSearch query translation reference table

This is the canonical lookup. Use it; do NOT re-derive per request.

| Solr (or ES 7.x dialect) | OpenSearch | Fidelity | Notes |
|---|---|---|---|
| `q=headphones` | `{"multi_match": {"query": "headphones", "fields": ["title", "description"]}}` | mapped | Solr searches `df` (default field); OS has no `_all` — name fields explicitly. |
| `q=title:headphones` | `{"match": {"title": "headphones"}}` | verbatim | Field-scoped match. |
| `q.op=AND` | `"default_operator": "AND"` (on `query_string`) **or** `"operator": "AND"` (on `match` / `multi_match`) | verbatim | OpenSearch defaults to OR. **#1 cause of result divergence.** Always set explicitly. |
| `defType=edismax` | `multi_match` `type: best_fields` | mapped | Closest semantic equivalent; not byte-identical scoring. |
| `qf=title^3 description^1 tags^2` | `"fields": ["title^3", "description^1", "tags^2"]` | verbatim | Boosts pass through unchanged. |
| `pf=title^5` (phrase boost) | `should: [{"multi_match": {"query": "<q>", "type": "phrase", "fields": ["title^5"]}}]` | approximation | Scoring shape differs — see caveats. |
| `pf2=title^3` / `pf3=title^2` | Two `should` clauses with `match_phrase` and `slop` adjustment | approximation | Solr's bigram/trigram phrase boost has no exact OS equivalent. |
| `tie=0.3` | `"tie_breaker": 0.3` (on `multi_match best_fields`) | verbatim | Same semantics. |
| `mm=2<-25%` | `"minimum_should_match": "2<-25%"` | verbatim | **Syntax passes UNCHANGED** — same parser. |
| `mm=100%` | `"minimum_should_match": "100%"` | verbatim | All clauses must match. |
| `fq=in_stock:true` | `bool.filter: [{"term": {"in_stock": true}}]` | verbatim | Filter context — no scoring, cacheable. |
| `bq=category:electronics^2` (boost query) | `should: [{"term": {"category": {"value": "electronics", "boost": 2}}}]` | verbatim | Additive scoring boost. |
| `bf=recip(ms(NOW,timestamp),3.16e-11,1,1)` (boost function) | `function_score` with `gauss` or `exp` decay on `timestamp` | mapped | Solr `recip` is a hyperbolic decay; OS `gauss`/`exp` give equivalent shape — re-tune scale. |
| `sort=score desc, price asc` | `"sort": [{"_score": "desc"}, {"price": "asc"}]` | verbatim | `score` → `_score`. |
| `start=20&rows=20` | `"from": 20, "size": 20` | verbatim | |
| `fl=title,price,_score` | `"_source": ["title", "price"]` (`_score` always returned) | verbatim | |
| `hl=true&hl.fl=title` | `"highlight": {"fields": {"title": {}}}` | verbatim | |
| `facet=true&facet.field=category` | `"aggs": {"by_category": {"terms": {"field": "category.keyword"}}}` | mapped | Use `.keyword` sub-field for terms agg. |
| `facet.range=price&facet.range.start=0&facet.range.end=100&facet.range.gap=20` | `"aggs": {"price_ranges": {"range": {"field": "price", "ranges": [{"to":20},{"from":20,"to":40},…]}}}` | mapped | OS uses explicit range buckets. |
| `mlt=true` | `more_like_this` query | mapped | Same semantics, different request shape. |
| `wt=json` | (default) `Accept: application/json` | verbatim | OS speaks JSON natively. |
| `group=true&group.field=brand` | `"collapse": {"field": "brand.keyword"}` | mapped | OS `collapse` ≈ Solr field collapsing for top-1 per group. |
| `cursorMark=*` | `search_after` + tiebreaker sort | mapped | OS deep pagination via PIT + `search_after`. |

## Worked exemplar

> **User:** Translate this Solr query: `q=wireless headphones&defType=edismax&qf=title^3 description^1 tags^2&pf=title^5&mm=2<-25%&q.op=AND&tie=0.3&fq=in_stock:true&start=0&rows=20&sort=score desc, price asc&hl=true&hl.fl=title`
>
> **Assistant response (this is the shape):**

Translating Solr 8.x eDisMax `q=wireless headphones` (qf/pf/mm/tie/q.op/fq/sort/highlight) to OpenSearch 2.x `_search`.

```json
GET products/_search
{
  "query": {
    "bool": {
      "must": [
        {
          "multi_match": {
            "query": "wireless headphones",
            "type": "best_fields",
            "fields": ["title^3", "description^1", "tags^2"],
            "operator": "AND",
            "minimum_should_match": "2<-25%",
            "tie_breaker": 0.3
          }
        }
      ],
      "should": [
        {
          "multi_match": {
            "query": "wireless headphones",
            "type": "phrase",
            "fields": ["title^5"]
          }
        }
      ],
      "filter": [
        {"term": {"in_stock": true}}
      ]
    }
  },
  "from": 0,
  "size": 20,
  "sort": [{"_score": "desc"}, {"price": "asc"}],
  "highlight": {"fields": {"title": {}}}
}
```

| Solr param | OpenSearch | Fidelity |
|---|---|---|
| `defType=edismax` | `multi_match` `type: best_fields` | mapped |
| `qf=title^3 description^1 tags^2` | `fields: ["title^3","description^1","tags^2"]` | verbatim |
| `pf=title^5` | `should` + `multi_match type: phrase` | approximation |
| `mm=2<-25%` | `minimum_should_match: "2<-25%"` | verbatim |
| `q.op=AND` | `operator: "AND"` | verbatim |
| `tie=0.3` | `tie_breaker: 0.3` | verbatim |
| `fq=in_stock:true` | `filter` term clause | verbatim |
| `sort=score desc, price asc` | `sort: [{"_score":"desc"},{"price":"asc"}]` | verbatim |
| `hl=true&hl.fl=title` | `highlight.fields.title` | verbatim |

**Approximation caveats:**

- **`pf` phrase boost:** modeled as a separate `should` clause; Solr eDisMax adds the `pf` score to the eDisMax sum, OpenSearch adds the `should` score to the bool sum. Top-N order should be similar but not identical — re-tune `pf` boost (using the example value `^5`) against your judgment list.
- **`q.op=AND`:** set as `operator: "AND"` on `multi_match` (cleaner than `query_string` for this case). OpenSearch defaults to OR — without this, recall would explode.

To sanity-check parsing: `POST products/_validate/query?explain=true` with the same body — confirms the BoolQuery / DisjunctionMaxQuery structure matches expectation.

## Pre-emit checklist (TRANSLATION_TASK-specific)

Before sending the response, tick every box:

- [ ] First sentence is the **source restatement** (engine + version + query type + target endpoint), not tool narration.
- [ ] Output contains a **single, valid, copy-pasteable JSON block** for `_search` (or the right endpoint).
- [ ] Every parameter from the source request is **either present in the OS JSON or explicitly mapped in the fidelity table** — no silent drops.
- [ ] **`q.op` / `default_operator`** is handled explicitly: if the source had AND (Solr `q.op=AND` OR an explicit `AND`/`&&` boolean operator inside a Lucene `query_string` query), it MUST appear **in the JSON itself** — `operator: "AND"` on `match`/`multi_match`, or `default_operator: "AND"` on `query_string`. Discussing it only in prose or in the approximation caveats does NOT satisfy this rule (the customer is told to drop the JSON in directly, so the JSON has to be correct on its own). Apply this to **every query** in a multi-query translation, not only the first.
- [ ] **`mm` / `minimum_should_match`** preserved verbatim (same parser; do not "simplify" `2<-25%`).
- [ ] **eDisMax `qf` boosts** preserved verbatim in `multi_match.fields`.
- [ ] Any `pf` / `pf2` / `pf3` is in a separate `should` clause AND flagged in caveats as **approximation**.
- [ ] `tie_breaker` is set explicitly when the source had `tie` (do not rely on defaults).
- [ ] Field names that need `.keyword` sub-field for `term` / `terms agg` / `sort` are using it.
- [ ] **NO `Timeline & Resourcing` section.** **NO** Executive Summary. **NO** Sizing. **NO** migration tooling pivot.
- [ ] **NO dollar figures** anywhere.
- [ ] No marketing tone ("seamless", "robust", "best-in-class", "elegant", "cleanly").
- [ ] Citations section omitted unless ≥3 version-volatile claims were made.
- [ ] If approximation rows exist, the **caveats bullet list is present** — never leave approximation unflagged.
