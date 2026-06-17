# DocumentDB — Schema Advisor

Use-case-first schema design. Start by understanding what the user is building, then produce a concrete schema, index commands, and rationale. DocumentDB's flexible schema means **data accessed together should be stored together** — design for access patterns, not entities.

**Operator verification:** Before recommending any aggregation operator, you MUST verify it is supported in the target DocumentDB version by calling `web_fetch(url="https://docs.aws.amazon.com/documentdb/latest/developerguide/mongo-apis.html")` and searching the returned content. Do not assume support from MongoDB knowledge.

## What to ask upfront

- What they're building (one sentence)
- Target DocumentDB version (default: `8.0` — applies to both instance-based and serverless)

## Workflow

### Step 1: Identify entities, relationships, access patterns

From the user's description, extract:

- **Entities** — the main "things" (products, users, orders, messages)
- **Relationships** — how they relate (users have orders, orders have items)
- **Access patterns** — what queries the app runs (get user by id, list orders by user, search by category)
- **AI/vector need** — does it involve search, recommendations, or embeddings?

### Step 2: Embed vs reference

Core principle: embed when data is always accessed together; reference when it's accessed independently or grows without bound.

| Relationship | Cardinality | Access | Recommendation |
|---|---|---|---|
| User → profile | 1:1 | Always together | **Embed** |
| Order → line items | 1:few (< 100) | Always together | **Embed array** |
| User → orders | 1:many, unbounded | Often separate | **Reference** (orders collection with `userId`) |
| Product → categories | many:many | Varies | **Two-way reference** |
| Post → comments | 1:many, need latest N | Mixed | **Hybrid**: embed latest 3, reference the rest |

**Anti-patterns:**

- **Unbounded arrays** (comments, events, messages) — they push documents toward the 16MB limit. Move to a separate collection.
- **Recreating SQL tables 1:1** — if you always join two tables in SQL, embed them in DocumentDB.
- **Excessive `$lookup`** — denormalize frequently-joined fields at write time.
- **Fields accessed at different frequencies in the same document** — split into hot/cold collections.

### Step 3: Produce JSON document examples

One example per collection, with comments explaining each field choice:

```javascript
{
  "_id": ObjectId("..."),
  "sku": "SHIRT-BLU-L",
  "name": "Classic Blue Shirt",
  "category": "apparel",
  "price": 49.99,
  "attributes": {           // embedded — always accessed with product
    "color": "blue", "size": "L", "material": "cotton"
  },
  "tags": ["shirt", "blue", "cotton"]  // bounded array, safe to embed
}
```

Different documents in the same collection can have different fields — use this for polymorphic data (shoes have size+color, electronics have RAM+storage).

### Step 4: Generate index commands

For every access pattern, produce a ready-to-run `createIndex`. Apply the **ESR rule** for compound indexes — Equality fields first, Sort fields middle, Range fields last:

```javascript
// Single field
db.products.createIndex({ "category": 1 })

// Compound — ESR: equality(userId) → sort(createdAt) → range(price)
db.orders.createIndex({ "userId": 1, "createdAt": -1, "price": 1 })

// TTL — expire documents 30 days after createdAt
db.sessions.createIndex({ "createdAt": 1 }, { expireAfterSeconds: 2592000 })

// Partial (5.0+) — only index active products
db.products.createIndex(
  { "price": 1 },
  { partialFilterExpression: { "status": { "$eq": "active" } } }
)

// Text search
db.articles.createIndex({ "title": "text", "body": "text" })
```

**Constraints:**

- Only one field in a compound index can be an array (multikey)
- `sparse` and `partialFilterExpression` cannot be combined
- Avoid compound indexes with more than 3 fields — write overhead outweighs query benefit for most workloads

### Step 5: Vector search (AI / RAG workloads)

Use DocumentDB native vector search for semantic search, RAG, chatbot memory, recommendations, or anomaly detection.

**Availability:**

- Vector indexes: DocumentDB 5.0+ (instance-based clusters)
- Classic operator (`$search.vectorSearch`): DocumentDB 5.0+
- `$vectorSearch` operator: DocumentDB 8.0+ (both instance-based and serverless)

**Schema — store embedding with source content:**

```javascript
{
  "_id": ObjectId("..."),
  "source": "docs/getting-started.md",
  "chunk_index": 3,
  "text": "Amazon DocumentDB Serverless auto-scales...",
  "embedding": [0.023, -0.117, 0.891, ...],    // 1536 floats for OpenAI ada-002
  "metadata": { "doc_type": "documentation" }
}
```

**Create an HNSW index (recommended for most workloads):**

```javascript
db.runCommand({
  createIndexes: "documents",
  indexes: [{
    key: { "embedding": "vector" },
    name: "embedding_hnsw_idx",
    vectorOptions: {
      type: "hnsw",
      dimensions: 1536,          // match your embedding model
      similarity: "cosine",      // cosine for text; euclidean for images; dotProduct for normalized
      m: 16, efConstruction: 64
    }
  }]
})
```

Use **IVFFlat** instead when index build speed matters more than recall and you have > 1M vectors. Set `lists: sqrt(num_documents)`.

**Query — DocumentDB 8.0+ (`$vectorSearch`):**

```javascript
db.documents.aggregate([
  { $vectorSearch: {
      queryVector: [...],
      path: "embedding",
      index: "embedding_hnsw_idx",
      limit: 10,
      numCandidates: 150
  }}
])
```

**Query — DocumentDB 5.0 (Classic `$search.vectorSearch`):**

```javascript
db.documents.aggregate([
  { $search: {
      vectorSearch: {
        vector: [...],
        path: "embedding",
        similarity: "cosine",
        k: 10,
        efSearch: 40
      }
  }}
])
```

**Dimension limits:** 2,000 with an index, 16,000 without (brute-force scan).

**Note:** DocumentDB does NOT support `knnBeta` or `{ $meta: "vectorSearchScore" }` — those are MongoDB Atlas features. DocumentDB returns matching documents ordered by similarity without an explicit score field.

### Step 6: Flag DocumentDB constraints

Check these against the schema and warn the user about any that apply:

- **16MB document hard limit.** Monitor with `Object.bsonsize(doc)` in mongosh (`$bsonSize` is NOT supported). Use `db.runCommand({collStats: "..."}).avgObjSize` for averages.
- **No schema enforcement by default.** Recommend `$jsonSchema` validation for critical collections.
- **`$graphLookup`** — verify current support status at the [MongoDB API compatibility page](https://docs.aws.amazon.com/documentdb/latest/developerguide/mongo-apis.html) before advising. If unsupported: use the materialized path pattern (store `ancestors` array) or Amazon Neptune. Materialized paths are often the better design even when `$graphLookup` is available.
- **`$facet`** — verify current support status at the same page. If unsupported: split into separate aggregation pipelines and merge in app code.
- **Multikey indexes on large arrays** bloat storage — each element is a separate index entry.

## Output format

Every schema advisor response has three deliverables:

1. **JSON document examples** (one per collection, with field-level comments)
2. **`db.createIndex()` commands** (one per access pattern, ready to run in mongosh)
3. **One-sentence rationale** per embed/reference decision
