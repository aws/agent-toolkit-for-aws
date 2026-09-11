# Neptune Troubleshooting

This sub-skill covers the most common Neptune failure modes. Agents without
this guidance reproduce incorrect fixes at high rates.

See also: [connectivity.md](connectivity.md) for setup guidance,
[performance.md](performance.md) for optimization.

## Connectivity failures

### Symptom: Connection refused or timeout on port 8182

Most common Neptune error. Almost always a VPC/security group issue.

**Diagnosis checklist:**

1. Is your client (Lambda, EC2, CloudShell) in the **same VPC** as Neptune?
2. Does the Neptune security group have an **inbound rule for TCP 8182**
   from your client's security group (not CIDR)?
3. Does your client security group have an **outbound rule for TCP 8182**
   to Neptune's security group?
4. Are you in a **compatible subnet** (same AZ helps for latency)?

**Fix:**

```bash
# Verify Neptune is reachable from within VPC (run from EC2 or CloudShell in VPC)
nc -zv your-cluster.cluster-xxxx.us-east-1.neptune.amazonaws.com 8182

# If this times out: security group or routing issue
# If this connects: client-side configuration issue
```

```bash
# Add inbound rule to Neptune security group
aws ec2 authorize-security-group-ingress \
  --group-id sg-neptune-xxxx \
  --protocol tcp \
  --port 8182 \
  --source-group sg-client-xxxx  # client's security group ID, NOT a CIDR range
```

### Symptom: 403 Forbidden

IAM authentication is enabled but the request isn't signed.

**Diagnosis tip:** Enable CloudWatch Logs to inspect auth failures:

```bash
aws neptune modify-db-cluster \
  --db-cluster-identifier your-cluster \
  --enable-cloudwatch-logs-exports '["audit"]' \
  --apply-immediately
```

Then check CloudWatch Logs for the `audit` log group to see which requests are failing and why.

**Check if IAM auth is enabled:**

```bash
aws neptune describe-db-clusters \
  --db-cluster-identifier your-cluster \
  --query 'DBClusters[0].IAMDatabaseAuthenticationEnabled'
```

**Option 1: Sign requests with SigV4 (production-recommended):**

See [connectivity.md](connectivity.md) for the full SigV4 signing implementation. A 403 means the request was not signed — the correct fix is to sign the request, **not** to disable IAM auth.

**Option 2: Disable IAM auth (dev/non-production only):**

> ⚠️ Do NOT disable IAM auth on clusters with public endpoints or production data. Only consider this on an isolated, private dev cluster that holds no sensitive data.

```bash
aws neptune modify-db-cluster \
  --db-cluster-identifier your-cluster \
  --no-enable-iam-database-authentication \
  --apply-immediately
```

### Symptom: SSL/TLS handshake error

Neptune requires SSL. Ensure you're using `wss://` (WebSocket) or `https://`
(HTTP) — not `ws://` or `http://`.

```python
# ❌ Wrong
'ws://your-cluster:8182/gremlin'

# ✅ Correct
'wss://your-cluster.cluster-xxxx.us-east-1.neptune.amazonaws.com:8182/gremlin'
```

---

## Query failures

### Symptom: Query times out

Default Neptune query timeout is 120 seconds. Long-running queries indicate:

- Missing early `limit()` or `has()` filter (full graph scan)
- Supernode traversal (vertex with millions of edges)
- Missing index usage

**Profile the query first:**

```groovy
// Add .profile() to see where time is spent
g.V().hasLabel('Person').out('KNOWS').out('KNOWS').profile()

// Look for: traversedEdges and elementCount — high numbers = full scan
// Look for: duration per step
```

**Fix full graph scans:**

```groovy
// ❌ Full scan — traverses all vertices
g.V().out('KNOWS').has('name', 'Alice')

// ✅ Filter early — use has() before traversal
g.V().has('Person', 'name', 'Alice').out('KNOWS')
```

### Symptom: Supernode degrading performance

A vertex with millions of outgoing edges (celebrity, popular product, country)
causes traversals to fan out uncontrollably.

**Identify supernodes:**

```groovy
// Find vertices with the most edges
g.V().project('id', 'degree')
  .by(id)
  .by(bothE().count())
  .order().by('degree', desc)
  .limit(10)
```

**Mitigation strategies:**

```groovy
// Strategy 1: Sample instead of full traversal
g.V().has('Celebrity', 'name', 'Taylor Swift')
  .in('FOLLOWS').sample(1000).values('name')

// Strategy 2: Filter edges before fanning out
g.V().has('Celebrity', 'name', 'Taylor Swift')
  .inE('FOLLOWS').has('since', gt('2023-01-01'))
  .outV().values('name')

// Strategy 3: Partition traversal into batches
// Run in application code with multiple smaller queries
```

### Symptom: ConcurrentModificationException

Occurs under high concurrent write load when multiple transactions modify
the same vertex or edge simultaneously.

```python
import time
from gremlin_python.driver.exception import GremlinServerError

def execute_with_retry(client, query, max_retries=3):
    for attempt in range(max_retries):
        try:
            return client.submit(query).all().result()
        except GremlinServerError as e:
            if 'ConcurrentModificationException' in str(e) and attempt < max_retries - 1:
                time.sleep(0.1 * (2 ** attempt))  # exponential backoff
                continue
            raise

# Also consider: reduce write concurrency, use batch writes during off-peak
```

### Symptom: Empty or partial results (pagination issue)

Neptune does not automatically paginate. Large result sets are silently
truncated or return only the first batch.

```python
# ❌ Returns only first 64KB of results
results = client.submit("g.V().hasLabel('Person').valueMap()").all().result()

# ✅ Paginate explicitly
def paginate_all(client, label, page_size=500):
    all_results = []
    offset = 0
    while True:
        batch = client.submit(
            f"g.V().hasLabel('{label}').range({offset}, {offset + page_size}).valueMap(true)"
        ).all().result()
        if not batch:
            break
        all_results.extend(batch)
        offset += page_size
    return all_results
```

### Symptom: `AccessDeniedException: Authentication Failed` on Neptune Analytics via AWS MCP server

When calling Neptune Analytics data-plane operations (`ExecuteQuery`, `ExecuteQueryWithResults`) through the AWS MCP server's `aws___run_script` tool, every call returns `AccessDeniedException: Authentication Failed` regardless of the caller's IAM permissions or the graph's connectivity mode. Control-plane calls (`CreateGraph`, `GetGraph`, `DeleteGraph`, `ListGraphs`) from the same MCP session with the same principal succeed — so it is not a role, graph, or VPC misconfiguration. The SigV4 signing path in the MCP server does not sign `neptune-graph:ExecuteQuery` correctly.

**Workaround**: use the AWS MCP server for the control plane (create, tag, snapshot, delete the graph), then switch transport for the data plane. Options:

- Local `boto3` session outside the MCP server using the same IAM principal — this works reliably (verified empirically).
- Lambda function in the same account invoking `boto3.client('neptune-graph').execute_query(...)`.
- `aws neptune-graph execute-query` via plain AWS CLI when on a shell with the same credentials.

An upstream bug report to the AWS MCP server team is recommended. Do not try to resolve by escalating IAM privileges — the same role succeeds on the data plane outside MCP, so the failure mode is entirely in how the MCP server builds the SigV4 request for this operation.

---

## Neptune Serverless issues

### Symptom: High latency on first query (cold start)

Neptune Serverless scales down toward its configured `MinCapacity` when
idle — it does NOT scale to zero. Check the Neptune Serverless
capacity-scaling documentation for the minimum allowed `MinCapacity`
value. Cold-scale-up from `MinCapacity` can add 2-10 seconds to the
first query after an idle period.

**Fix for latency-sensitive workloads:**

- Switch to provisioned instances with a minimum of 1 instance
- Or implement a keep-warm Lambda that pings Neptune every 5 minutes

```python
# Keep-warm Lambda (schedule every 5 min with EventBridge)
def handler(event, context):
    client.submit("g.V().limit(1)").all().result()
    return {"status": "warm"}
```

### Symptom: Neptune Serverless not scaling up fast enough

Serverless scales based on Neptune Capacity Units (NCUs). Set
`MinNCUs` and `MaxNCUs` appropriately for your workload.

```bash
aws neptune modify-db-cluster \
  --db-cluster-identifier your-cluster \
  --serverless-v2-scaling-configuration MinCapacity=1,MaxCapacity=8 \
  --apply-immediately
```

---

## Loader / bulk import issues

### Symptom: Neptune bulk loader job fails silently

```bash
# Check loader job status
aws neptune describe-db-instances  # get instance ID

curl -X GET \
  "https://your-cluster:8182/loader/your-load-job-id" \
  -H "Content-Type: application/json"

# Common errors in the response:
# LOAD_S3_ACCESS_DENIED: Neptune IAM role missing S3 permissions
# PARSE_ERROR: CSV/RDF file format issue (check first 10 lines)
# CONSTRAINT_VIOLATION: Duplicate IDs in source data
```

**S3 access fix:**

```bash
# Attach a SCOPED S3 policy (least-privilege) — NOT AmazonS3ReadOnlyAccess (which grants read to every bucket)
aws iam put-role-policy \
  --role-name NeptuneLoadFromS3 \
  --policy-name NeptuneBulkLoadS3Access \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::your-data-bucket",
        "arn:aws:s3:::your-data-bucket/load-prefix/*"
      ]
    }]
  }'
```

## Additional Resources

- AWS docs: "Neptune troubleshooting", "Neptune error messages"
- Related sub-skills: `connectivity` (setup), `performance` (optimization)
- CloudWatch: check GremlinErrors, BufferCacheHitRatio, CPUUtilization first
