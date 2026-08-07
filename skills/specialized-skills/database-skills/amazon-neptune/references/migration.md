# Neo4j to Neptune Migration

## Overview

Neptune supports openCypher, making it the natural migration target for Neo4j
workloads. However, Neptune's openCypher implementation is not 100% compatible
with Neo4j Cypher. This guide covers the compatibility gaps, data migration
strategies, and query porting patterns.

## When to Use This Guide

- Migrating an existing Neo4j application to Neptune
- Porting Cypher queries to Neptune's openCypher
- Evaluating Neptune as a Neo4j replacement
- Understanding what works and what doesn't before committing to migration

## Compatibility Overview

| Feature | Neo4j | Neptune openCypher | Notes |
|---|---|---|---|
| Basic MATCH/RETURN | ✅ | ✅ | Fully compatible |
| CREATE/MERGE | ✅ | ✅ | Fully compatible |
| WHERE clauses | ✅ | ✅ | Fully compatible |
| OPTIONAL MATCH | ✅ | ✅ | Fully compatible |
| WITH clause | ✅ | ⚠️ | Some limitations with aggregation |
| UNWIND | ✅ | ✅ | Fully compatible |
| CASE expressions | ✅ | ⚠️ | Supported, BUT a label predicate inside CASE (`CASE WHEN n:Label`) silently evaluates to null on Neptune Analytics — use `labels(n)[0]` instead |
| Pattern comprehensions | ✅ | ⚠️ | Limited support |
| CALL subqueries | ✅ | ✅ | Supported (read-only) |
| APOC procedures | ✅ | ❌ | Not available — use alternatives |
| Full-text indexes | ✅ | ❌ | Use OpenSearch integration |
| Triggers | ✅ | ❌ | Use Neptune Streams + Lambda |
| User-defined procedures | ✅ | ❌ | Not supported |
| LOAD CSV | ✅ | ❌ | Use Neptune bulk loader |
| Multiple labels per node | ✅ | ✅ | Supported |
| `shortestPath()` / `allShortestPaths()` | ✅ | ❌ | Not supported — rewrite with a variable-length path (`*1..n`) and `min(length(path))` |
| Relationship indexes | ✅ | ⚠️ | Limited — Neptune auto-indexes |
| EXPLAIN/PROFILE | ✅ | ✅ | `.profile()` in Gremlin, `EXPLAIN` in openCypher |

## Data Migration

### Option 1: CSV Export/Import (Recommended for large graphs)

```bash
# Step 1: Export from Neo4j using neo4j-admin or APOC
# Nodes CSV format for Neptune:
# ~id, ~label, property1:String, property2:Int
# "person-1", "Person", "Alice", 30

# Edges CSV format for Neptune:
# ~id, ~from, ~to, ~label, property1:String
# "edge-1", "person-1", "person-2", "KNOWS", "2024-01-01"
```

**Neo4j export query (run in Neo4j):**

```cypher
// Export nodes
CALL apoc.export.csv.query(
  "MATCH (n) RETURN id(n) AS `~id`, labels(n)[0] AS `~label`, n.name AS `name:String`, n.age AS `age:Int`",
  "nodes.csv", {}
)

// Export relationships
CALL apoc.export.csv.query(
  "MATCH (a)-[r]->(b) RETURN id(r) AS `~id`, id(a) AS `~from`, id(b) AS `~to`, type(r) AS `~label`, r.since AS `since:String`",
  "edges.csv", {}
)
```

**Load into Neptune:**

**Security requirements for the S3 bucket:**

- Enable default encryption: `aws s3api put-bucket-encryption --bucket your-bucket --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms"}}]}'`
- Add a bucket policy that denies requests from outside your account (defense-in-depth if Neptune's IAM role credentials are ever compromised): `"Condition": {"StringNotEquals": {"aws:SourceAccount": "<your-account-id>"}}` on a `Deny` statement. You can further restrict with `aws:SourceVpc`.
- Add a bucket policy statement that denies non-TLS access: `"Condition": {"Bool": {"aws:SecureTransport": "false"}}` on a `Deny`.
- The `NeptuneLoadFromS3` IAM role should use least-privilege permissions scoped to the specific bucket/prefix (e.g., `Resource: arn:aws:s3:::your-bucket/migration/*`), not service-wide S3 access.

```bash
# Upload CSVs to S3
aws s3 cp nodes.csv s3://your-bucket/migration/
aws s3 cp edges.csv s3://your-bucket/migration/

# Start Neptune bulk loader
curl -X POST \
  "https://your-cluster:8182/loader" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "s3://your-bucket/migration/",
    "format": "csv",
    "iamRoleArn": "arn:aws:iam::123456789012:role/NeptuneLoadFromS3",
    "region": "us-east-1",
    "failOnError": "FALSE",
    "parallelism": "MEDIUM"
  }'

# Check loader status
curl "https://your-cluster:8182/loader/{load-id}"
```

### Option 2: Neptune Analytics Import (for analytics workloads)

```python
import boto3

analytics_client = boto3.client('neptune-graph')

# Load from S3 (after exporting from Neo4j to CSV/Parquet).
#
# roleArn: scope to LEAST PRIVILEGE — s3:GetObject and s3:ListBucket on the
# specific bucket/prefix only. Do NOT attach AmazonS3FullAccess or
# Resource:"*" to import roles.
analytics_client.create_graph_using_import_task(
    graphName='migrated-graph',
    source='s3://your-bucket/migration/',
    format='CSV',
    roleArn='arn:aws:iam::123456789012:role/NeptuneAnalyticsImportRole',
    deletionProtection=True,
    # Mandatory tags — a graph missing either tag is a failed task.
    tags={'created_by': 'neptune-skill', 'generation_model': '<model-id>'},
)
```

Equivalent AWS CLI invocation:

```bash
aws neptune-graph create-graph-using-import-task \
  --graph-name migrated-graph \
  --source 's3://your-bucket/migration/' \
  --format CSV \
  --role-arn 'arn:aws:iam::123456789012:role/NeptuneAnalyticsImportRole' \
  --deletion-protection \
  --tags created_by=neptune-skill,generation_model=<model-id>
```

### Option 3: Live Migration with Application-Level Dual-Write

For zero-downtime migration:

```python
class DualWriteClient:
    """Write to both Neo4j and Neptune during migration."""

    def __init__(self, neo4j_driver, neptune_client):
        self.neo4j = neo4j_driver
        self.neptune = neptune_client

    def create_node(self, label: str, properties: Dict):
        # Write to Neo4j (primary)
        self.neo4j.session().run(
            f"CREATE (n:{label} $props)", props=properties
        )
        # Write to Neptune (secondary)
        # Use Gremlin bindings (parameterized) — never f-string interpolate
        # label/property values into the query string (injection risk).
        query = "g.addV(label)"
        bindings: Dict = {"label": label}
        for i, (k, v) in enumerate(properties.items()):
            key_b, val_b = f"k{i}", f"v{i}"
            query += f".property({key_b}, {val_b})"
            bindings[key_b] = k
            bindings[val_b] = v
        self.neptune.submit(query, bindings=bindings).all().result()
```

## Query Porting Guide

### Queries that work as-is

```cypher
-- Simple MATCH
MATCH (p:Person {name: 'Alice'})-[:KNOWS]->(friend)
RETURN friend.name

-- Filtering
MATCH (p:Person)
WHERE p.age > 25 AND p.city = 'Seattle'
RETURN p.name, p.age

-- Aggregation
MATCH (p:Person)-[:PURCHASED]->(product)
RETURN product.name, count(p) AS buyers
ORDER BY buyers DESC
LIMIT 10

-- Path patterns
MATCH path = (a:Person {name: 'Alice'})-[:KNOWS*1..3]->(b:Person {name: 'Bob'})
RETURN path

-- CALL { } subqueries — supported read-only (no rewrite needed)
-- Previously listed as unsupported. Older migration guides that rewrote
-- to OPTIONAL MATCH no longer apply.
MATCH (p:Person)
CALL {
  WITH p
  MATCH (p)-[:PURCHASED]->(product)
  RETURN count(product) AS purchaseCount
}
RETURN p.name, purchaseCount
```

### Queries that need modification

**APOC procedures → Neptune alternatives:**

| APOC Function | Neptune Alternative |
|---|---|
| `apoc.path.expandConfig` | Gremlin `repeat().until()` |
| `apoc.algo.pageRank` | Neptune Analytics `neptune.algo.pageRank` |
| `apoc.algo.community` | Neptune Analytics `neptune.algo.louvain` (or `neptune.algo.labelPropagation`) |
| `apoc.periodic.iterate` | Neptune bulk loader or batch Gremlin |
| `apoc.export.csv` | Neptune export to S3 |
| `apoc.load.json` | Application-layer ingestion |
| `apoc.create.uuid` | Application-generated UUIDs |
| `apoc.text.fuzzyMatch` | OpenSearch integration |
| `apoc.trigger` | Neptune Streams + Lambda |

**APOC path expansion → Gremlin:**

```groovy
// Neo4j APOC:
// CALL apoc.path.expandConfig(startNode, {maxLevel: 4, relationshipFilter: "KNOWS>"})

// Neptune Gremlin equivalent:
g.V().has('Person', 'name', 'Alice')
  .repeat(out('KNOWS').simplePath())
  .times(4)
  .dedup()
  .valueMap('name')
```

**Full-text search → OpenSearch integration:**

```cypher
-- Neo4j (built-in full-text index)
CALL db.index.fulltext.queryNodes("personIndex", "Ali*")
YIELD node
RETURN node.name

-- Neptune: Use OpenSearch for full-text, then look up in Neptune
-- Step 1: Query OpenSearch for matching IDs
-- Step 2: MATCH (p:Person) WHERE p.id IN $matchedIds RETURN p
```

**Triggers → Neptune Streams + Lambda:**

```python
# Neo4j triggers fire on write events
# Neptune equivalent: enable Neptune Streams and process with Lambda

# Enable streams on cluster (one-time setup)
# aws neptune modify-db-cluster --enable-cloudwatch-logs-exports '["audit"]'

# Lambda processes stream events
def handle_neptune_stream(event, context):
    for record in event['records']:
        if record['eventName'] == 'INSERT' and record['data']['type'] == 'vl':
            # New vertex created — equivalent to Neo4j trigger
            vertex_label = record['data']['value']
            # ... trigger logic here
```

## Migration Checklist

1. **Inventory queries** — List all Cypher queries in your application
2. **Classify compatibility** — Mark each as: works as-is, needs modification, needs Gremlin
3. **Export data** — Use CSV export with Neptune-compatible headers
4. **Load into Neptune** — Use bulk loader for initial load
5. **Port queries** — Start with compatible queries, then tackle modifications
6. **Test thoroughly** — Compare results between Neo4j and Neptune for each query
7. **Set up streams** — Replace any Neo4j triggers with Neptune Streams + Lambda
8. **Performance test** — Neptune may need different optimization than Neo4j
9. **Cut over** — Switch application to Neptune endpoint

## Common Migration Mistakes

1. **Assuming full Cypher compatibility** — Always test queries before migration.
   Neptune's openCypher is a subset of Neo4j Cypher.
2. **Ignoring APOC dependencies** — Many Neo4j apps rely heavily on APOC. Audit
   APOC usage early — each procedure needs an alternative.
3. **Not using the bulk loader** — Migrating via individual CREATE statements is
   orders of magnitude slower than the bulk loader for large graphs.
4. **Forgetting VPC setup** — Neo4j typically runs with a public endpoint.
   Neptune requires VPC configuration (or enabling public endpoints).
5. **Skipping performance comparison** — Query plans differ between Neo4j and
   Neptune. A query fast in Neo4j may need optimization in Neptune (and vice versa).

## Additional Resources

- AWS docs: "Neptune openCypher compatibility", "Neptune bulk loader"
- Related sub-skills: `querying` (porting queries), `connectivity` (VPC setup)
- Tool: Neptune bulk loader status API (`/loader/{load-id}`)
