---
case_shape: SCHEMA_CONVERSION
purpose: Field-by-field mapping from a source schema (Solr schema.xml, Elasticsearch mapping, raw field list) to an OpenSearch index mapping
when_to_use: "User pasted a schema artifact OR asked 'map these fields' / 'convert this schema' / 'what does `<fieldType>` become in OpenSearch'"
NOT_for: Holistic readiness assessment (use FULL_ASSESSMENT), query syntax translation only (use TRANSLATION_TASK), justifying the choice of OpenSearch (use ANTI_PATTERN_PUSHBACK)
length_target: 200-600 words plus the JSON mapping block
---

# Recipe: SCHEMA_CONVERSION

> **Canonical reference.** This is the canonical Solr-7-and-9 field-type-and-deprecation reference for the skill. Other files (assessment-workflow §X-Pack/Solr deprecation, assets/solr-gap-register, asset/report templates) link here for the exhaustive list.

## 1. Detection signals — dispatch here when

Trigger this shape when the user input contains any of the following. **One strong signal is enough**; do not require multiple.

- Pasted XML containing `<field name=` or `<fieldType name=` or `<schema name=` (Solr schema.xml)
- Pasted JSON containing `"mappings"`, `"properties"`, or `"dynamic_templates"` (ES/OS mapping export)
- A flat list of field names with types like `string`, `text_general`, `pdate`, `plong`, `TrieLong`, `EnumField`, `CurrencyField`, `solr.TextField`
- Imperative phrases: "map these fields", "convert this schema", "what's the OpenSearch equivalent of `<type>`", "translate this mapping"
- File references: `schema.xml`, `managed-schema`, `mapping.json`, `_mapping`

If the user pasted a schema **and** asked sizing/readiness questions, dispatch SCHEMA_CONVERSION first, then offer to run FULL_ASSESSMENT as a follow-up. Do not silently merge shapes.

## 2. Required output template

Produce exactly these four sections in this order. Skip any section the user explicitly waived.

### Section A — Field-by-field mapping table

A markdown table with columns: `Source field` | `Source type` | `Target OpenSearch type` | `Mapping options` | `Notes`. **Every source field MUST appear** with either a target mapping or the literal annotation `omit — <reason>`. No silent drops.

### Section B — OpenSearch index mapping (JSON)

A complete, paste-ready `PUT /<index>` body containing `mappings.properties` and any required `settings` (analyzers, normalizers). Must be valid JSON; no `...` ellipses, no `// comments`.

### Section C — Special field bindings

Solr `<uniqueKey>` does not have a direct OpenSearch equivalent — `_id` is metadata, not a field. **Show the binding three ways** so the reader can pick the form that fits their pipeline:

1. **`copy_to` in the JSON mapping** — keep the user's id field as a regular property and copy it where searches need it.
2. **Sample `_bulk` request** — demonstrating the `{"index":{"_id":"<value>"}}` action line that pulls the id from the document at write time.
3. **Prose binding instruction** — one sentence telling the indexer/ETL author to extract the source id field and place it in the action metadata.

### Section D — Gap register

Bulleted list of every source field whose type is **deprecated, removed, or has no direct OpenSearch equivalent**. Always flag at minimum: `TrieLong`/`TrieInt`/`TrieDate` (deprecated since Solr 7, removed in Solr 9), `EnumField` (use `keyword` + application-side ordering), `CurrencyField` (split into `scaled_float` + `keyword` for currency code), `solr.LatLonType` (use `geo_point`), `PreAnalyzedField` (no equivalent — re-analyze at write time).

For the upstream Solr 9 upgrade-notes catalog (additions / removals / behavior changes), see [Solr major changes](https://solr.apache.org/guide/solr/latest/upgrade-notes/major-changes-in-solr-9.html).

### Section E — Migration path callout (1-2 sentences)

State the recommended reindex strategy in one or two sentences: typically "logstash or a custom ETL reads from the Solr `/select` cursor and writes to OpenSearch `_bulk`; do a dual-write window if downtime is unacceptable." Do not expand this into a full migration plan.

### Section F — One inline doc URL footer

A single line at the bottom: `Reference: https://docs.aws.amazon.com/opensearch-service/latest/developerguide/supported-operations.html` (or a more specific page if relevant — field-data-types, analyzers, etc.). One URL. Not a list.

## 3. NOT REQUIRED — explicitly omit

Do **NOT** include any of the following in a SCHEMA_CONVERSION response:

- **Timeline & Resourcing — removed from the suite entirely.** No engineer-weeks, no calendar estimates, no staffing.
- Forced sizing section (no shard math, no instance picks, no storage calculations) — that is FULL_ASSESSMENT territory.
- Readiness score / scorecard / traffic-light grid.
- The 9-section assessment structure.
- Customer-specific trade-offs ("you should consider X for your business" framing).
- Pricing tables or cost estimates.
- Standalone risks/blockers register beyond the gap-register deprecations in Section D — SCHEMA_CONVERSION ships only the gap-register, not the FULL_ASSESSMENT §7 two-table split.

If the user wants any of the above, tell them you'll switch shapes and ask for the inputs FULL_ASSESSMENT needs.

## 4. Worked exemplar

> **User:** "Convert this Solr schema for OpenSearch."
>
> ```xml
> <field name="product_id" type="string" indexed="true" stored="true" required="true"/>
> <field name="title"      type="text_general" indexed="true" stored="true"/>
> <field name="price"      type="TrieLong" indexed="true" stored="true"/>
> <field name="created"    type="pdate" indexed="true" stored="true"/>
> <field name="status"     type="EnumField" enumsConfig="enums.xml" enumName="status"/>
> <uniqueKey>product_id</uniqueKey>
> ```
>
> **Response:**
>
> **A. Field mapping**
>
> | Source field | Source type | Target OS type | Options | Notes |
> |---|---|---|---|---|
> | product_id | string | `keyword` | `copy_to: ["_id_src"]` | Bound to `_id` — see Section C |
> | title | text_general | `text` | `analyzer: standard`, sub-field `title.keyword` of type `keyword` | Multi-field for sort/agg |
> | price | TrieLong | `long` | — | **deprecated since Solr 7, removed in Solr 9** — straight long replacement |
> | created | pdate | `date` | `format: strict_date_optional_time` | |
> | status | EnumField | `keyword` | — | OpenSearch has no enum; use keyword and order at app layer |
>
> **B. JSON mapping**
>
> ```json
> PUT /products
> {
>   "mappings": {
>     "properties": {
>       "product_id": { "type": "keyword" },
>       "title":      { "type": "text", "fields": { "keyword": { "type": "keyword", "ignore_above": 256 } } },
>       "price":      { "type": "long" },
>       "created":    { "type": "date", "format": "strict_date_optional_time" },
>       "status":     { "type": "keyword" }
>     }
>   }
> }
> ```
>
> **C. uniqueKey → _id binding (three forms)**
>
> 1. **copy_to in JSON** — already shown: keep `product_id` as a `keyword` field and reference it in your indexer.
> 2. **Sample _bulk** —
>
>    ```
>    POST /_bulk
>    { "index": { "_index": "products", "_id": "SKU-12345" } }
>    { "product_id": "SKU-12345", "title": "Wireless mouse", "price": 2999, "created": "2026-05-30T12:00:00Z", "status": "ACTIVE" }
>    ```
>
> 3. **Prose** — your ETL must read `product_id` from each Solr document and place its value in the `_id` field of the bulk action metadata; OpenSearch will reject documents whose action line omits `_id` only if you require deterministic ids.
>
> **D. Gap register**
>
> - `TrieLong` — deprecated Solr 7, removed Solr 9 → `long`
> - `EnumField` — no OpenSearch equivalent → `keyword` + application-side ordering
>
> **E. Migration path** — Use Logstash with the `solr` input plugin or a cursor-based ETL writing to `_bulk`; run a dual-write window during cutover if zero downtime is required.
>
> **F.** Reference: https://docs.aws.amazon.com/opensearch-service/latest/developerguide/supported-operations.html

## 5. Pre-emit checklist (tick before responding)

Tick each box. If any box cannot be ticked, fix the response before sending.

- [ ] Every source field appears in the mapping table (no silent drops; explicit `omit — reason` if dropped).
- [ ] JSON mapping block is valid, paste-ready, no `...` or comments.
- [ ] `<uniqueKey>` (or equivalent id field) is shown in **all three** binding forms: copy_to JSON,_bulk sample, prose.
- [ ] At least one row in the gap register is labeled with deprecation provenance (e.g., "deprecated since Solr 7") if a deprecated type appears in the source.
- [ ] `TrieLong` / `TrieInt` / `TrieDate` rows, if present, are explicitly labeled deprecated.
- [ ] Exactly one doc URL footer at the bottom — not a list.
- [ ] Migration path callout is 1-2 sentences, not a plan.
- [ ] **No Timeline & Resourcing section.** No engineer-weeks. No calendar estimates.
- [ ] No readiness score, no forced sizing, no 9-section structure.
- [ ] Response is within the 200-600 word target (excluding the JSON block).
