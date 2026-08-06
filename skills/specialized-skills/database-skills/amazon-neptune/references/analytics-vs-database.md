# Neptune Analytics vs Neptune Database

This is one of the most common decision points agents get wrong — they
recommend Neptune Database for workloads that need Neptune Analytics, or
vice versa.

## One-line summary

- **Neptune Database** = transactional graph store, millisecond queries, live app backend, supports Gremlin + openCypher + SPARQL
- **Neptune Analytics** = in-memory graph analytics engine, batch algorithms, BI on graphs, **openCypher only** (no Gremlin, no SPARQL)

### Neptune Analytics does not support Gremlin

Neptune Analytics' `ExecuteQuery` accepts `language='OPEN_CYPHER'` only. Calls with `language='GREMLIN'` return `UnprocessableException: Retry for SDK query requests is suppressed, please resubmit the query` regardless of traversal content or IAM permissions. Any workload that needs Gremlin — including friend-of-friend recommendation traversals and path-analysis patterns — must run on Neptune **Database**, not Analytics. If an existing Gremlin workload wants the Analytics engine's algorithm set, run the algorithms via their openCypher equivalents (`CALL neptune.algo.*`) and keep Gremlin-native queries on Neptune Database.

## When to use Neptune Database

- Live application backend (web app, mobile app, API)
- Millisecond query latency required
- Concurrent reads and writes from multiple clients
- Data must be durable and multi-AZ
- Transactional consistency required (ACID per traversal)
- Ongoing operational queries (fraud checks at transaction time, real-time recommendations)

## When to use Neptune Analytics

- Running graph algorithms on a full snapshot (PageRank, community detection,
  betweenness centrality, label propagation)
- Analyzing graph structure in batch (nightly fraud scoring, weekly recommendation refresh)
- Data science / exploration workloads
- Short-lived analytical jobs (load → analyze → export → shut down)
- Graph machine learning feature extraction
- **GraphRAG** — combining graph traversal with vector similarity search for
  retrieval-augmented generation (see [graphrag.md](graphrag.md))
- **Agentic memory** — long-term agent memory with built-in vector search,
  eliminating the need for a separate vector store (see [agentic-memory.md](agentic-memory.md))

## Common architecture: both together

```
Neptune Database (live, OLTP)
     │
     │  nightly export / sync
     ▼
Neptune Analytics (batch, OLAP)
     │
     │  scores / features written back
     ▼
Neptune Database or DynamoDB (serve results to app)
```

Example: fraud detection

- Neptune Database: real-time ring detection at transaction time (milliseconds)
- Neptune Analytics: nightly PageRank to score accounts by network centrality,
  results stored back for use in real-time decisions

## Neptune Analytics: key capabilities

```python
import boto3

analytics_client = boto3.client('neptune-graph')

# Create a graph (loads data from S3 or Neptune Database)
#
# Secure default: deletionProtection=True. Only ephemeral CI/test graphs that
# an automated harness must tear down should pass False — see "Ephemeral
# CI / test graphs" below.
response = analytics_client.create_graph(
    graphName='fraud-analysis',
    provisionedMemory=16,  # m-NCU (1 m-NCU = 1 GB). Valid range per the CreateGraph API reference; console default 128.
    publicConnectivity=False,
    replicaCount=0,  # 0 for cost savings on batch jobs
    deletionProtection=True,
    # Mandatory tags — a graph missing either tag is a failed task. Follow up
    # with `tag-resource` per references/action-safety.md.
    tags={'created_by': 'neptune-skill', 'generation_model': '<model-id>'},
)

# Run openCypher query with graph algorithms.
#
# NOTE: Neptune Analytics uses different config keys than Neo4j's gds.pageRank.
# Neo4j's maxIterations / nodeLabels / relationshipTypes fail on Neptune with
# ValidationException: Invalid input: Unknown input field(s). See translation
# table below.
query = """
MATCH (n:User)
CALL neptune.algo.pageRank(n, {
    numOfIterations: 20,
    dampingFactor: 0.85,
    edgeLabels: ['FOLLOWS'],
    vertexLabel: 'User'
})
YIELD node, rank
RETURN node.id AS userId, rank AS pageRankScore
ORDER BY rank DESC
LIMIT 100
"""
```

### PageRank: Neptune vs Neo4j parameter names

Neptune Analytics' `neptune.algo.pageRank` and Neo4j's `gds.pageRank` look similar but use different config-map keys. Using Neo4j's keys on Neptune fails with `Invalid input: Unknown input field(s) [nodeLabels, relationshipTypes] present in CALL procedure config map argument`.

| Purpose | Neo4j `gds.pageRank` | Neptune Analytics `neptune.algo.pageRank` |
|---|---|---|
| Node label filter | `nodeLabels: ['User']` (plural list) | `vertexLabel: 'User'` (singular string) |
| Edge label filter | `relationshipTypes: ['FOLLOWS']` | `edgeLabels: ['FOLLOWS']` |
| Iteration count | `maxIterations: 20` | `numOfIterations: 20` |
| Damping factor | `dampingFactor: 0.85` | `dampingFactor: 0.85` (same) |

The algorithm name is case-sensitive — use `neptune.algo.pageRank` (camelCase), not `pagerank` or `PageRank`. The `YIELD` clause returns `(node, rank)` on Neptune, not `(node, score)`.

## Neptune Analytics: loading data

```python
# Load from S3 (CSV or Parquet).
#
# Ensure the source S3 bucket has default encryption (SSE-S3 or SSE-KMS)
# and a bucket policy that denies non-TLS access
# (Condition: {"Bool": {"aws:SecureTransport": "false"}}).
#
# roleArn: scope to LEAST PRIVILEGE — s3:GetObject and s3:ListBucket on the
# specific bucket/prefix only, plus neptune-graph actions scoped to the target
# graph. Do NOT attach AmazonS3FullAccess or Resource:"*" to import roles.
analytics_client.create_graph_using_import_task(
    graphName='fraud-analysis',
    source='s3://your-bucket/graph-data/',
    format='CSV',
    minProvisionedMemory=16,
    maxProvisionedMemory=128,
    roleArn='arn:aws:iam::123456789012:role/NeptuneAnalyticsImportRole',
    deletionProtection=True,
    # Mandatory tags — a graph missing either tag is a failed task.
    tags={'created_by': 'neptune-skill', 'generation_model': '<model-id>'},
    # For production: specify a customer-managed KMS key for the graph
    # (encryption at rest) instead of the default AWS-managed key.
    # kmsKeyIdentifier='arn:aws:kms:us-east-1:123456789012:key/<key-id>',
)
```

Equivalent AWS CLI invocation for the S3 load:

```bash
aws neptune-graph create-graph-using-import-task \
  --graph-name fraud-analysis \
  --source 's3://your-bucket/graph-data/' \
  --format CSV \
  --min-provisioned-memory 16 \
  --max-provisioned-memory 128 \
  --role-arn 'arn:aws:iam::123456789012:role/NeptuneAnalyticsImportRole' \
  --deletion-protection \
  --tags created_by=neptune-skill,generation_model=<model-id>
```

```python
# Load from Neptune Database cluster (bulk-export → import).
#
# The source is an RDS-style Neptune cluster ARN, not a neptune-db ARN.
# The `format` parameter is only for S3 sources (CSV / OPEN_CYPHER /
# PARQUET / NTRIPLES) and is OMITTED when importing from a Neptune cluster
# or snapshot; the import shape is expressed via importOptions.neptune
# instead. Snapshots use the cluster-snapshot resource type:
# `arn:aws:rds:<region>:<account>:cluster-snapshot:<name>`.
#
# Security notes for the IAM role and the export S3 bucket:
# - roleArn: scope to LEAST PRIVILEGE. The role only needs the specific
#   actions required for a bulk export — NOT neptune-db:* or any *FullAccess
#   managed policy. Grant only:
#     * neptune-db:ReadDataViaQuery, neptune-db:GetEngineStatus,
#       neptune-db:GetStatisticsStatus on the specific source cluster ARN
#     * s3:GetObject, s3:PutObject, s3:ListBucket, s3:DeleteObject
#       scoped to arn:aws:s3:::<your-export-bucket>/<prefix>/*
#     * kms:Decrypt, kms:GenerateDataKey on the specific KMS key ARN
#   Consult the Neptune Analytics bulk-import userguide for the exact
#   action list required by your source version, since new actions may
#   be added. Do NOT attach AmazonS3FullAccess / NeptuneFullAccess or use
#   Resource:"*" on production import roles.
# - Trust policy on the import role — prevent confused-deputy attacks by
#   restricting which service/account can assume the role:
#     "Condition": {
#       "StringEquals": {"aws:SourceAccount": "<your-account-id>"},
#       "ArnLike":      {"aws:SourceArn": "arn:aws:neptune-graph:<region>:<account>:*"}
#     }
# - s3ExportPath bucket: enable default encryption (SSE-S3 or SSE-KMS)
#   and attach a bucket policy that denies non-TLS traffic
#   (Condition: {"Bool": {"aws:SecureTransport": "false"}}) so the
#   export is encrypted in transit as well as at rest. The
#   s3ExportKmsKeyId only encrypts the exported objects; the bucket
#   itself needs its own encryption + transport policy.
# - Enable S3 server access logging or CloudTrail S3 data events on the
#   export bucket to audit access to the exported graph data.
# - Treat the export as transient sensitive data: the exported graph
#   may contain PII / financial relationships. Restrict bucket access
#   to the import role + authorized operators only, add an S3
#   lifecycle rule to auto-delete objects after import completes, and
#   ensure CloudWatch Logs for the import task do not log sensitive
#   property values.
analytics_client.create_graph_using_import_task(
    graphName='fraud-analysis',
    source='arn:aws:rds:us-east-1:123456789012:cluster:your-neptune-cluster',
    minProvisionedMemory=16,
    maxProvisionedMemory=128,
    roleArn='arn:aws:iam::123456789012:role/NeptuneAnalyticsImportRole',
    deletionProtection=True,
    importOptions={
        'neptune': {
            's3ExportKmsKeyId': 'arn:aws:kms:us-east-1:123456789012:key/<key-id>',
            's3ExportPath': 's3://your-export-bucket/neptune-export/',
        }
    },
    # Mandatory tags — a graph missing either tag is a failed task.
    tags={'created_by': 'neptune-skill', 'generation_model': '<model-id>'},
)
```

Equivalent AWS CLI invocation:

```bash
aws neptune-graph create-graph-using-import-task \
  --graph-name fraud-analysis \
  --source 'arn:aws:rds:us-east-1:123456789012:cluster:your-neptune-cluster' \
  --min-provisioned-memory 16 \
  --max-provisioned-memory 128 \
  --role-arn 'arn:aws:iam::123456789012:role/NeptuneAnalyticsImportRole' \
  --import-options '{"neptune":{"s3ExportKmsKeyId":"arn:aws:kms:us-east-1:123456789012:key/<key-id>","s3ExportPath":"s3://your-export-bucket/neptune-export/"}}' \
  --deletion-protection \
  --tags created_by=neptune-skill,generation_model=<model-id>
```

## Cost model comparison

| Factor | Neptune Database | Neptune Analytics |
|---|---|---|
| Billing | Instance hours + storage GB | NCU hours (while running) |
| Idle cost | Full instance cost | A small fraction of running compute while Stopped (data preserved) — see the Neptune Analytics pricing page for the exact rate |
| Storage | Persistent, auto-grow | In-memory, ephemeral |
| Best cost pattern | Always-on, steady workload | Spin up → analyze → tear down |

**Cost tip**: For batch analytics jobs, create the Neptune Analytics graph,
run your algorithms, export results to S3 or DynamoDB, then delete the graph.
Pay only for the hours the job runs.

### Ephemeral CI / test graphs

`deletionProtection=True` is the secure default and what every example in this
skill uses. The ONE exception is a graph created by an automated CI/test
harness that must tear itself down: those may pass
`deletionProtection=False` at create time so cleanup does not stall on the
CREATING window. Never do this for a graph holding real data.

### Recovering a graph stuck in CREATING with deletion protection

If a graph is already in CREATING with `deletionProtection=True`, `DeleteGraph` returns a validation error until the graph reaches `AVAILABLE`. Recovery sequence (the AGENT must not run these against a graph it did not create — hand them to the user):

1. Wait for status to become `AVAILABLE`.
2. `aws neptune-graph update-graph --graph-identifier <id> --no-deletion-protection`
3. `aws neptune-graph delete-graph --graph-identifier <id>` — the agent MUST NOT run this (see references/action-safety.md Never-Auto-Execute); hand it to the user.

CI automation that creates its own throwaway graphs should pass `deletionProtection=False` at create time rather than relying on the poll-update-delete sequence above.

## Common Mistakes

1. **Using Database for batch algorithms** — Analytics is designed for this.
2. **Forgetting Analytics is ephemeral** — always export results before deletion.
3. **Wrong SDK** — Analytics uses boto3 `neptune-graph`, not Gremlin WebSocket.
4. **Over-sizing provisionedMemory** — check the CreateGraph API reference for the valid m-NCU range (1 m-NCU = 1 GB). Right-size to your graph instead of over-provisioning.
5. **Not considering Analytics for GraphRAG/memory** — it has built-in vector search.
6. **Sending Gremlin to Analytics** — `ExecuteQuery` with `language='GREMLIN'` returns `UnprocessableException`. Analytics is openCypher-only. Use Neptune Database for Gremlin.
7. **Using Neo4j `gds.pageRank` parameter names** — `nodeLabels` / `relationshipTypes` / `maxIterations` fail with `ValidationException` on Neptune. Use `vertexLabel` / `edgeLabels` / `numOfIterations`.
8. **On ephemeral CI graphs only: leaving `deletionProtection=True`** — blocks `DeleteGraph` during the CREATING window, stranding automation until the graph reaches AVAILABLE. Pass `deletionProtection=False` for throwaway test / CI graphs. For any graph holding real data, keep the secure default.

## Additional Resources

- AWS docs: "Neptune Analytics user guide", "Neptune Analytics graph algorithms"
- Related sub-skills: `graphrag` (vector + graph), `agentic-memory` (agent use case)
- Script: `scripts/graphrag_pipeline.py` (Analytics SDK usage examples)
