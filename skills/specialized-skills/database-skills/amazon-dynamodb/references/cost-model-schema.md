# Cost model JSON schema

The cost calculator at `${SKILL_DIR}/scripts/calculate_costs.py` reads a JSON file describing the data model and access patterns, and writes a monthly-cost report in Markdown. This document specifies the JSON shape. (`${SKILL_DIR}` is defined in SKILL.md "Resolving the skill's own paths" — substitute the absolute path of the directory containing SKILL.md.)

The agent generates this JSON from its own in-context design — it is not authored by hand. Everything the calculator needs (RPS, item size, operation, consistency, GSI projection) is already part of a properly produced access-pattern list and schema (per Mechanics #2 and #18). Assembling the JSON is a serialization step, not a separate design exercise.

## Top-level shape

```json
{
  "tables": [ /* Table[] */ ],
  "access_patterns": [ /* AccessPattern[] */ ]
}
```

Only these two arrays are required. Everything else is optional and has sensible defaults.

## Table

```json
{
  "table_name": "Orders",
  "table_class": "STANDARD",
  "global_tables": false,
  "key_schema": {
    "partition_key": "customer_id",
    "sort_key": "order_id"
  },
  "entities": [ /* Entity[] */ ],
  "gsis": [ /* Gsi[] */ ],
  "vector_indexes": [ /* VectorIndex[] */ ]
}
```

| Field | Required | Default | Notes |
|-------|----------|---------|-------|
| `table_name` | yes | — | Must match the `table` value on every access pattern that targets it. |
| `table_class` | no | `"STANDARD"` | `"STANDARD"` or a non-standard value. Storage is priced at the full public Standard rate either way — the 25 GB free tier is **not** applied (it is account-wide and often already consumed). |
| `global_tables` | no | `false` | If `true`, adds 48 bytes per item to storage calculations. |
| `key_schema` | no for calculator, **yes for live deploy** | — | `{"partition_key": "<attr>", "sort_key": "<attr>?"}`. The calculator ignores this; it sizes items generically. The live-deploy path (`${SKILL_DIR}/scripts/deploy_model.py`) requires it to build `CreateTable` kwargs and refuses with a clear error if any table is missing it. Populate from the schema you already derived — the attribute names are the ones you chose per Data modeling #7. **`key_schema` names the key attributes but does NOT carry their type** — the deploy resolves each key's `AttributeType` (S/N/B) by looking the name up in `entities[].attributes[]` or `attribute_definitions` (below). A key whose type is not declared anywhere deploys as **`S`** — so a numeric (epoch sort key, numeric id) or binary key MUST be declared `N`/`B`, or real writes fail with `ValidationException` in production. |
| `attribute_definitions` | no | `[]` | Optional table-level list declaring key attribute types, in the raw-`CreateTable`-API shape: `[{"attribute_name": "order_date", "attribute_type": "N"}]`. The `{"name","type"}` shorthand is also accepted. Read by both `deploy_model.py` and `scripts/benchmark_lambda.py`. An entry here **wins** over an `entities[].attributes[]` type for the same attribute. Use this when you'd rather declare key types at the table level than inside an entity; declaring them in `entities[].attributes[]` is equally valid. |
| `entities` | no | `[]` | Used (a) to size attributes for query projection caps, (b) as a storage fallback when no write pattern targets the table, and (c) as a source of key attribute types (`attributes[].type`) for the live deploy. |
| `gsis` | no | `[]` | Drives write amplification and storage sizing. |
| `vector_indexes` | no | `[]` | Vector indexes on the table. Drives vector write capacity and vector index storage, and is required for a `SearchVectors` access pattern to resolve. See *Vector index* below. |

## Entity

```json
{
  "entity_name": "Order",
  "estimated_item_size_bytes": 2048,
  "estimated_item_count": 500000,
  "attributes": [
    { "name": "order_id", "type": "S" },
    { "name": "status", "type": "S" },
    { "name": "total_cents", "type": "N" }
  ]
}
```

| Field | Required | Default | Notes |
|-------|----------|---------|-------|
| `entity_name` | yes | — | Free-form identifier; used only in cross-references. |
| `estimated_item_size_bytes` | no | 1024 | Used in the storage fallback path. **Excludes vector attributes** — declare the item size without its embeddings and let the calculator derive those from `dimensions`, or an `ALL`-projection vector index double-counts them. See *Vector capacity is metered in BYTES*. |
| `estimated_item_count` | no | 100,000 | Used in the storage fallback path. |
| `attributes` | no | `[]` | Each attribute has a `name` and `type`. Types map to sizes: `S=100`, `N=8`, `BOOL=1`, `B=256`, `L=200`, `M=200`, `SS=200`, `NS=200`, `BS=200`, `NULL=1`. These sizes are heuristics — use them as-is unless you have a stronger reason. **For live deploy this is also where key attribute types come from:** every attribute named in `key_schema` (partition/sort) or in any GSI key MUST appear here (or in the table's `attribute_definitions`) with its true `type`, or the deploy defaults it to `S`. |

Entities are used mainly when access patterns specify a `projection` list. The calculator caps Query/Scan `items_per_request` at the 900 KB page limit based on the sum of projected attribute sizes. If you never use `projection`, the entity list is only consulted for the storage fallback.

> **Key attribute types are load-bearing for live deploy.** DynamoDB types only *key* attributes (PK/SK on the table and every GSI); non-key attributes are schemaless. The deploy builds each table's `AttributeDefinitions` by looking up every key attribute's type in `entities[].attributes[]` and the table-level `attribute_definitions` block (the latter wins on conflict), defaulting to `S` for any it can't find. A key declared (or defaulted) to the wrong type is the one schema error DynamoDB enforces at write time: a numeric epoch sort key left as `S` accepts the seed but rejects real integer writes with `ValidationException`. So whenever a key is an epoch timestamp, a numeric id, or binary, declare it `N`/`B` — in either place — and the benchmark/seed path (which reads the same two sources) will generate matching values automatically.

## GSI

```json
{
  "index_name": "OrdersByCustomer",
  "partition_key": "customer_id",
  "sort_key": "created_at",
  "projection": {
    "type": "ALL"
  }
}
```

With an INCLUDE projection:

```json
{
  "index_name": "OrdersByStatusSparse",
  "partition_key": "status_active",
  "sort_key": "created_at",
  "projection": {
    "type": "INCLUDE",
    "attributes": ["order_id", "customer_id", "total_cents"]
  }
}
```

| Field | Required | Default | Notes |
|-------|----------|---------|-------|
| `index_name` | yes | — | Must match the `index` value on any access pattern that targets it. |
| `partition_key` | no | — | Attribute name of the GSI PK. Used for sparse-GSI detection: if an access pattern provides `attributes_written` and the GSI's PK is not in that list, amplification is skipped for that write. |
| `sort_key` | no | — | Attribute name of the GSI SK. Used together with INCLUDE/KEYS_ONLY projection checks on UpdateItem. |
| `projection.type` | no | `"ALL"` | `"ALL"`, `"INCLUDE"`, or `"KEYS_ONLY"`. Drives both write-amplification size and storage size. |
| `projection.attributes` | no | `[]` | Only for INCLUDE projections. The list is used in UpdateItem amplification checks — if none of the written attributes intersects this list, amplification is skipped. |

Projection ratios (applied to base item size):

- `ALL` → 1.0 (full item written to index; full base-table storage footprint)
- `INCLUDE` → 0.3 (conservative default when the include list is unknown)
- `KEYS_ONLY` → 0.1 (keys + SK only)

> **GSI sparseness (write amplification AND storage).** A DynamoDB item is written to — and stored in — a GSI **only if it carries that GSI's key** (the partition key, plus the sort key if the GSI is composite). This is verified live against `ReturnConsumedCapacity=INDEXES`: an item missing a composite GSI's sort key fired **zero** writes to it. In a single-table design with heterogeneous entities, each GSI is keyed on an attribute only *some* entities have, so most items belong to only one or two of the table's GSIs — not all of them. The calculator models this: **write amplification** uses `entities_written` (above) to bill only the member indexes; **GSI storage** is sized by the byte-share of entities that carry the index's key, not the whole base table. When the model doesn't declare enough to establish membership (no `entities_written`, or a GSI key declared on no entity), the calculator stays at the conservative full-fan-out / full-size upper bound rather than guessing low.

## Vector index

```json
{
  "index_name": "ProductEmbeddingIndex",
  "vector_attribute": "Embedding",
  "dimensions": 1024,
  "distance_function": "COSINE",
  "projection": { "type": "INCLUDE", "attributes": ["Title"] },
  "search_schema": { "partition_key": "Category", "inline_filters": ["Brand"] },
  "estimated_indexed_items": 40000000
}
```

| Field | Required | Default | Notes |
|-------|----------|---------|-------|
| `index_name` | yes | — | Must match the `index` value on any `SearchVectors` access pattern targeting it. |
| `vector_attribute` | yes | — | Attribute holding the embedding. Indexes sharing an attribute MUST agree on `dimensions` — DynamoDB rejects otherwise with `Attributes cannot be redefined`. |
| `dimensions` | yes | — | 1–4096. Fixed at creation; changing it means a new index and a migration. |
| `distance_function` | yes | — | `COSINE`, `EUCLIDEAN`, or `DOT_PRODUCT`. Fixed at creation. |
| `projection.type` | no | `"ALL"` | `ALL`, `INCLUDE`, or `KEYS_ONLY`. This is the dominant cost lever — see below. Fixed at creation. The bare-string shorthand `"projection": "KEYS_ONLY"` is accepted and is equivalent to `{"type": "KEYS_ONLY"}`, the same way `attribute_definitions` accepts the `{"name","type"}` shorthand. |
| `projection.attributes` | no | `[]` | For `INCLUDE`. Sized from `entities[].attributes[]` where declared, else 100 B each. |
| `search_schema.partition_key` | no | — | The vector index partition key (`HASH`). Must also appear in `attribute_definitions` or `entities[].attributes[]`, exactly as a GSI key must. **An item missing this attribute is written to the base table without error and silently excluded from the index** — see SKILL.md Fact #10 and `vector-search.md`. |
| `search_schema.inline_filters` | no | `[]` | Up to 18 `INLINE_FILTER` attributes, optional at search time. |
| `estimated_indexed_items` | no | sum of entity counts | Items actually replicated into the index — i.e. those carrying the vector attribute (and the partition key, if defined). Declare it when only a subset of the table carries embeddings; otherwise the calculator uses the table's whole population, which is a conservative upper bound and is flagged in the report with `*`. |

The calculator **rejects** a model where a vector-index table declares `provisioned_capacity`,
where `dimensions` or `top_k` are out of range, where more than 5 vector indexes are declared
on one table, or where indexes on the same attribute disagree on `dimensions`. These are
service constraints, so a violation means the design cannot be deployed — better to fail than
to price something impossible.

### Vector capacity is metered in BYTES, and the projection is the lever

Vector indexes are billed on three dimensions, separately from base-table RCU/WCU. Rates are
from the AWS Pricing API (us-east-1 Standard); Standard-IA is 125% on requests, 40% on storage.
Rates change and vary by region: these are the values the calculator ships with, and before
quoting a dollar figure to a user in another region — or a long time after this was written —
confirm them against `aws pricing get-products --service-code AmazonDynamoDB` or the DynamoDB
pricing page. The *shape* of the model below is what matters and does not change with the rates.

| Dimension | Rate | How the calculator treats it |
|---|---|---|
| Index storage | $0.25/GB-month (rolls into table storage) | Derived from the design |
| `VectorWriteRequest` | $0.52/GB | Derived — validated to within **2.1%** against live measurement |
| `VectorSearch` | $0.002/GB | **Not priced.** Drivers reported instead — see below |

**Write cost, measured semantics** (controlled probe: two indexes on the same attribute and
dimensions, projection the only variable):

- `KEYS_ONLY` is **flat** — `dimensions × 4` plus ~35 B of key overhead, and **independent of
  item size**. Measured 4,105 / 4,104 / 4,104 B on a 1024-dim index across a minimal item, a
  +10 KB item, and an item carrying a second vector.
- `ALL` adds **the entire rest of the item** to every vector write, including *other vector
  attributes* (carried in base-table form, ~5.5 B per number rather than 4). A 10 KB payload
  added 10,246 B.
- So on a minimal item holding only keys and the vector, **`ALL` costs exactly the same as
  `KEYS_ONLY`**. The projection only costs what the rest of the item costs. Choose it on item
  size, not on the vector.
- The 1 KB per-request minimum only binds below **256 dimensions** (256 × 4 = 1024 B), so it
  is moot for every real embedding model.

> **`estimated_item_size_bytes` EXCLUDES the vector attributes.** Declare the size of the item
> *without* its embeddings; the calculator adds each vector's own footprint from `dimensions`.
> This matters only for `ALL` (and `INCLUDE` naming a vector), where the model is
> `dimensions × 4 + key overhead + the rest of the item` — if the declared size already counted
> the embedding, the vector is billed twice and an `ALL` index looks roughly twice as expensive
> as it is. The convention is this way round because `dimensions` is exact and an item-size
> estimate is not, so deriving the vector's bytes from `dimensions` is strictly more accurate
> than trusting it to be included. A 1024-dim embedding is ~4 KB in the index and ~5.5 KB in
> base-table form, so on a small item this is the difference between a right answer and a
> doubled one.

**Search cost is deliberately not priced.** It bills on the vector data a search examines
inside the index plus the data returned, and the examined fraction varies by an order of
magnitude with index configuration (measured: 12.8% of all vector bytes on a 60-item
unpartitioned index against 1.3% on a 200-item partitioned one). A calibration fitted across
configurations came out 51–69% low at 256/1536/3072 dimensions — exactly where real embedding
models sit. The report gives the measured drivers instead: `TopK` is exactly linear, the
projection is a ~170× multiplier on bytes returned per result (~89 B for `KEYS_ONLY` against
the whole item for `ALL`; a `TopK=100` search on an `ALL` index measured **1.52 MB**), cost is
linear in dimensions at fixed configuration, and index size is *not* a linear driver because
ANN prunes — measured between 10 and 200 vectors in the searched partition. That is not the
same as "population never matters": an **empty** 1024-dimension index measured about **twice**
a populated one, so do not extrapolate the shape down to a sparse or freshly-created index.
Obtain the real figure from `ReturnConsumedCapacity` or the `VectorSearchRequestBytes`
CloudWatch metric — a live validation run measures it for you.

## Access pattern

```json
{
  "pattern_id": "Q8",
  "description": "Get order by ID",
  "operation": "GetItem",
  "table": "Orders",
  "index": null,
  "peak_rps": 800,
  "estimated_item_size_bytes": 2048,
  "items_per_request": 1,
  "consistency": "strong"
}
```

| Field | Required | Default | Notes |
|-------|----------|---------|-------|
| `pattern_id` | yes | — | Short identifier used in the cost report (e.g. `Q8`, `U1`). |
| `description` | no | `""` | One-line human description. |
| `operation` | yes | — | One of: `GetItem`, `Query`, `Scan`, `BatchGetItem`, `TransactGetItems`, `PutItem`, `UpdateItem`, `DeleteItem`, `BatchWriteItem`, `TransactWriteItems`, `SearchVectors`. |
| `table` | yes | — | Name of the target table. |
| `index` | no | `null` | GSI name, if the operation targets a secondary index. |
| `peak_rps` | yes | 0 | Peak requests per second. This multiplies capacity into monthly cost. **If you write `0` the pattern contributes nothing to the bill** — treat this as a mandatory field per Mechanics #2. |
| `avg_rps` | no | = `peak_rps` | Average/typical requests per second, for the **expected-volume** scenario. When any pattern sets it, the report adds a second "Expected Monthly Cost" headline computed at `avg_rps` (the per-op capacity is scale-invariant, so this drives the same CU at a lower rate and also scales storage growth). Defaults to `peak_rps`, so omitting it on every pattern yields the same single peak-sustained headline as before. Translate a stated daily/monthly volume to an average rate (e.g. 15,000 orders/day ÷ 86,400 s ≈ 0.17 rps); do not hand-compute the dollar figure — set this and let the calculator produce it. |
| `estimated_item_size_bytes` | no | 1024 | Per-item size for single-item operations; per-item size for multi-item reads. |
| `items_per_request` | no | 1 | Items returned (Query/Scan) or operated on (BatchGetItem, BatchWriteItem, TransactWriteItems, TransactGetItems). |
| `consistency` | no | `"eventual"` | `"eventual"`, `"strong"`, or `"transactional"`. `transactional` is implied by operation name for Transact* operations. |

A `SearchVectors` pattern is shaped a little differently: it targets a vector index by name,
carries `top_k` instead of `items_per_request`, and takes no `consistency` (vector search is
always eventually consistent, and consumes no RCU).

```json
{
  "pattern_id": "V1",
  "description": "Find similar products",
  "operation": "SearchVectors",
  "table": "Products",
  "index": "ProductEmbeddingIndex",
  "peak_rps": 40,
  "top_k": 10
}
```

The `index` MUST name a vector index declared in that table's `vector_indexes`, or the
calculator refuses the model rather than silently costing nothing.

Optional fields that tighten the estimate:

| Field | Applies to | Purpose |
|-------|------------|---------|
| `top_k` | SearchVectors | Results requested, 1-100. Defaults to 10. **Exactly linear** in the bytes a search returns, so it is the main lever you control at query time. |
| `filter` | Query, Scan | Free-form string; presence triggers a note that FilterExpression doesn't reduce cost. |
| `projection` | Query, Scan | Array of attribute names; used to cap `items_per_request` at the 900 KB page limit. |
| `item_sizes` | Batch*, Transact* | Array of per-item sizes when items vary; overrides `estimated_item_size_bytes` for batch/transact ops. |
| `previous_item_size_bytes` | PutItem, UpdateItem | Billed size is max(before, after). Provide the before-size if you know updates shrink items. |
| `attributes_written` | writes | Array of attribute names the write touches. Drives the **UpdateItem GSI gate** (verified live): an ALL-projection GSI rewrites on any change to an indexed item; an INCLUDE GSI only when a projected attribute changed; a KEYS_ONLY GSI only when its key changed. Changing an attribute that **is** a GSI key costs **2× on that index** (DynamoDB deletes the old index entry and inserts a new one) — set this so the calculator can tell a key-moving update from a plain one. **This field also gates VECTOR write cost, on the same convention:** when it is *provided* and does **not** contain the index's `vector_attribute`, that index is skipped and its vector write line prices at **$0** while every other number looks right — so a write that stores an embedding must list it, `"attributes_written": ["Embedding"]`. When it is *omitted* the calculator cannot tell, so it assumes the vector attribute was touched (conservative upper bound) and says so in the report. Note there is no boolean form of this: a field like `writes_vector_attribute` is not in the schema and is silently ignored. |
| `entities_written` | writes | Which entities a single write call creates/updates, for a single-table design with heterogeneous entities. A list of entity names (repeats allowed) or `[{"entity": "Order", "count": 1}, {"entity": "LineItem", "count": 3}]`. **This is what makes GSI write-amplification accurate on a multi-entity table:** a write amplifies only to the GSIs whose key the written entity actually carries (verified live), so a transaction writing 1 order + 3 line items is billed only the indexes those entities belong to — not every GSI on the table. **Omit it and the calculator falls back to a conservative UPPER BOUND** (every written item charged against every GSI) and says so in the report. On a single-entity table it is unnecessary (the lone entity is the writer). |
| `conditional_fail_rate` | writes | Fraction (0.0–1.0). Failed conditional writes are still billed — this adds their cost on top. |
| `non_existent_rate` | GetItem | Fraction of calls that miss. Attaches a note only; the minimum-RRU cost is already modeled. |
| `write_action` | writes | `"create"`, `"update"`, `"delete"`, or `"mixed"`. Drives storage growth — only creates add storage. Defaults are operation-sensible: PutItem=create, UpdateItem=update, DeleteItem=delete, Batch/Transact=mixed. |
| `retention_days` | writes | Days that created items persist before deletion/expiration. Default 30. Used for steady-state storage sizing. **Honored per pattern** — set it directly on the write pattern and it wins over any requirements default. The resulting storage is a **bounded-retention snapshot** at this window; a no-TTL / "kept forever" table accumulates past it, so do not read the figure as lifetime storage. |
| `source_requirement` | writes | Cross-reference back to a requirements document; only used when a separate requirements JSON is provided. Ignore in normal use. |

## Minimal working example

A tiny Orders table with two patterns — GetItem by id (strong), Query by customer (eventual) — and one GSI:

```json
{
  "tables": [
    {
      "table_name": "Orders",
      "key_schema": {
        "partition_key": "customer_id",
        "sort_key": "order_id"
      },
      "gsis": [
        {
          "index_name": "OrdersByCustomer",
          "partition_key": "customer_id",
          "sort_key": "created_at",
          "projection": { "type": "ALL" }
        }
      ]
    }
  ],
  "access_patterns": [
    {
      "pattern_id": "Q8",
      "description": "Get order by ID",
      "operation": "GetItem",
      "table": "Orders",
      "peak_rps": 800,
      "estimated_item_size_bytes": 2048,
      "consistency": "strong"
    },
    {
      "pattern_id": "Q9",
      "description": "List user orders",
      "operation": "Query",
      "table": "Orders",
      "index": "OrdersByCustomer",
      "peak_rps": 400,
      "estimated_item_size_bytes": 2048,
      "items_per_request": 20,
      "consistency": "eventual"
    }
  ]
}
```

## How it maps to what the skill already produces

The access-pattern list described in SKILL.md already carries the data the calculator needs — the JSON is a literal translation of that table plus the schema:

| Skill artifact | JSON field |
|----------------|-----------|
| Access-pattern list row: RPS | `peak_rps` |
| Access-pattern list row: "items returned per call and approximate item size" | `items_per_request`, `estimated_item_size_bytes` |
| Access-pattern list row: consistency | `consistency` |
| Per-pattern plan: API call | `operation` |
| Per-pattern plan: target table or GSI | `table`, `index` |
| Schema: primary key (PK + optional SK) | `tables[].key_schema` — **required for live deploy**, ignored by the calculator |
| Schema: GSI key attributes and projection | `tables[].gsis[]` |
| Schema: vector index (dimensions, distance function, SearchSchema, projection) | `tables[].vector_indexes[]` |
| Per-pattern plan: a similarity search | `operation: "SearchVectors"` + `index` + `top_k` |
| Schema: Global Tables replication | `tables[].global_tables` |

If a field you would need is not yet in the design, the design itself has a gap — filling the JSON is how you find out.

## Running the calculator

```bash
python3 ${SKILL_DIR}/scripts/calculate_costs.py --model /path/to/dynamodb_data_model.json --output /path/to/cost_report.md
```

The calculator prints where it wrote the report and how many patterns and tables it analyzed. Pricing uses DynamoDB Standard table-class, on-demand public rates; rates vary by region, so confirm the figure against the AWS DynamoDB pricing page (or `aws pricing get-products --service-code AmazonDynamoDB`) for the region you will deploy in before quoting it. Read the disclaimer at the top of the generated report before sharing the number.
