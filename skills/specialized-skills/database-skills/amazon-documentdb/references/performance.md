# DocumentDB — Performance Tuner

Two modes: **reactive** (user has a slow query — diagnose and fix) and **proactive** (general performance review). Both produce concrete index commands and query rewrites you execute against the user's cluster.

**Operator verification:** Before suggesting query rewrites that use specific aggregation operators, verify support by calling `web_fetch(url="https://docs.aws.amazon.com/documentdb/latest/developerguide/mongo-apis.html")` and searching the content.

## What to ask upfront

- Slow query vs general review?
- If slow query: the query itself, collection name, approximate collection size
- Cluster id, region, connection string

## Reactive mode: fix a slow query

### Step 1: Run `explain("executionStats")`

```javascript
// find()
db.collection.find({ field: "value" }).explain("executionStats")

// aggregate()
db.runCommand({
  explain: { aggregate: "collection", pipeline: [...], cursor: {} },
  verbosity: "executionStats"
})
```

### Step 2: Interpret output

| Field | Look for |
|---|---|
| `queryPlanner.winningPlan.stage` | `COLLSCAN` = no index (bad), `IXSCAN` = index used, `SORT` = in-memory sort |
| `executionStats.totalDocsExamined` (8.0+) | Should be close to `nReturned`; large gap = inefficient |
| `executionStats.totalKeysExamined` | Large vs `nReturned` = index not selective enough |
| `executionStats.executionTimeMillis` | Baseline for improvement |
| `queryPlanner.winningPlan.inputStage.indexName` | Which index was chosen |

### Step 3: Apply the fix

**COLLSCAN → create a missing index (ESR rule — equality first, sort, then range):**

```javascript
// Query: db.orders.find({ userId, status })
db.orders.createIndex({ userId: 1, status: 1 })

// Query with sort: include sort field in the same direction
db.products.createIndex({ category: 1, price: -1 })

// Full ESR: equality → sort → range
db.orders.createIndex({ userId: 1, createdAt: -1, price: 1 })
```

**Aggregation pipeline not using an index → put `$match` first:**

```javascript
// BAD — $project before $match destroys indexed field paths
[{ $project: { total: ... } }, { $match: { total: { $gt: 100 } } }]

// GOOD — $match first on indexed fields, compute derived fields after
[{ $match: { price: { $gt: 10 } } }, { $project: { total: ... } }]
```

**IXSCAN with high docs-examined / returned ratio → add selective fields to the compound index.**

**Long-running queries (> 30 minutes) → kill them:**

```javascript
db.adminCommand({ aggregate: 1, pipeline: [
  { $currentOp: {} },
  { $match: { $or: [{ secs_running: { $gt: 1800 } }, { WaitState: { $exists: true } }] } }
], cursor: {} })
```

Long queries block MVCC garbage collection → storage growth → CPU/memory pressure. Recommend application-level query timeouts.

### Step 4: Verify

Re-run `explain()`. Stage should change from `COLLSCAN` to `IXSCAN`, `executionTimeMillis` decrease, `totalDocsExamined` close to `nReturned`. Report before/after.

## Proactive mode: performance review

### Step 1: Query CloudWatch Logs Insights

Profiler log group: `/aws/docdb/<cluster-id>/profiler`.

```
filter ns="<db>.<coll>" | sort millis desc | limit 10
filter planSummary="COLLSCAN" | sort millis desc | limit 20
```

### Step 2: Review indexes

```javascript
db.getCollectionNames().forEach(c => db[c].getIndexes().forEach(printjson))
db.collection.aggregate([{ $indexStats: {} }])   // unused since last restart
```

Look for:

- **Redundant indexes** — `{a:1}` and `{a:1, b:1}` on the same collection. The single-field is covered by the compound; drop it.
- **Compound indexes with > 3 fields** — most filtering uses the first 1–3 fields; extras add write overhead.
- **Multikey indexes on large arrays** — each element is a separate index entry; storage bloat.

### Step 3: Check anti-patterns

| # | Anti-pattern | Fix |
|---|---|---|
| 1 | `COLLSCAN` on large collections | Add index on filter fields; apply ESR rule |
| 2 | Unbounded arrays in documents | Move to a separate collection with a parent-id index |
| 3 | `$match` after `$project` | Put `$match` first on indexed fields |
| 4 | `find()` without projection | Project only needed fields to reduce data transfer |
| 5 | Redundant indexes | Drop prefix indexes covered by compounds |
| 6 | High-cardinality `SORT` without index | Include sort field in the index (matching direction) |
| 7 | Frequent `$lookup` on hot path | Denormalize at write time; add indexes on join keys |

**Connection anti-pattern** (very common): creating `MongoClient` per request skips connection pooling. Create once at module scope; Lambda: outside the handler.

### Step 4: Produce a report

Organize findings by severity:

- **Critical** — COLLSCAN on large collections, long-running queries blocking GC
- **Warning** — redundant indexes, high-cardinality sorts without index
- **Improvement** — missing projections, pipeline ordering

For each finding, give the exact fix command.

## CloudWatch metrics to monitor

| Metric | Meaning |
|---|---|
| `CPUUtilization` | High = COLLSCANs, complex aggregations, connection spikes |
| `DatabaseConnections` | Current connection count |
| `DatabaseConnectionsLimit` | Max allowed — alert when approaching |
| `LongestRunningGCProcess` | > 1800s = long query blocking GC |
| `AvailableMVCCIds` | Low = risk of read-only mode |
| `BufferCacheHitRatio` | Low = queries hitting disk; scale up or add indexes |
