# Neptune Connectivity

Neptune runs inside a VPC by default, but both Neptune Database (engine
≥ 1.4.6.x) and Neptune Analytics support **optional public endpoints**.
Public endpoints are disabled by default and require IAM authentication.
When public endpoints are not enabled, every connection requires VPC access
— this is the most common source of "connection refused" errors.

## Neptune endpoint types

| Endpoint | Service | Use for |
|---|---|---|
| **Cluster endpoint** | Neptune Database | Write operations (points to primary instance) |
| **Reader endpoint** | Neptune Database | Read operations (load-balanced across replicas) |
| **Instance endpoint** | Neptune Database | Direct connection to a specific instance |
| **Graph endpoint** | Neptune Analytics | All operations (`{graph-id}.{region}.neptune-graph.amazonaws.com`) |

Default port: **8182** (Neptune Database), **443** (Neptune Analytics via SDK)

## Option 1: Connect from AWS CloudShell (no EC2 required)

CloudShell VPC environments let you connect directly without a bastion host.

### Step 1 — Create a VPC CloudShell environment

1. Open CloudShell in the AWS Console
2. Choose **Actions → Create VPC Environment**
3. Select the **VPC**, **subnet**, and **security group** that has inbound
   access on port 8182 to your Neptune cluster
4. Choose **Create** — CloudShell restarts inside your private subnet

### Step 2 — Install the Neptune client

```bash
# Install Gremlin console (check https://tinkerpop.apache.org/downloads.html for latest version)
TINKERPOP_VERSION="3.7.2"  # Update to latest stable version
curl -sL "https://downloads.apache.org/tinkerpop/${TINKERPOP_VERSION}/apache-tinkerpop-gremlin-console-${TINKERPOP_VERSION}-bin.zip" -o gremlin-console.zip
unzip gremlin-console.zip
cd "apache-tinkerpop-gremlin-console-${TINKERPOP_VERSION}"
```

### Step 3 — Connect to Neptune

```bash
# Replace with your Neptune cluster endpoint
NEPTUNE_ENDPOINT="your-cluster.cluster-xxxx.us-east-1.neptune.amazonaws.com"

bin/gremlin.sh
# Inside the Gremlin console:
:remote connect tinkerpop.server conf/neptune-remote.yaml
:remote console
```

Create `conf/neptune-remote.yaml`:

```yaml
hosts: [your-cluster.cluster-xxxx.us-east-1.neptune.amazonaws.com]
port: 8182
connectionPool: { enableSsl: true }
serializer: { className: org.apache.tinkerpop.gremlin.driver.ser.GraphSONMessageSerializerV2d0 }
```

⚠️ CloudShell sessions time out after 30 minutes of inactivity. Reinstall
the client after a timeout.

## Option 2: Connect from Lambda

Neptune runs in a VPC. Your Lambda function must also be in the same VPC.

### Lambda VPC configuration

**Important:** Neptune requires SSL/TLS (TLS 1.2+) for ALL connections. IAM authentication with SigV4 signing automatically uses encrypted connections. There is no option to connect over unencrypted protocols.

```python
# Lambda must be configured with:
# - Same VPC as Neptune
# - Subnet with route to Neptune (same AZ recommended)
# - Security group with outbound TCP 8182 to Neptune's security group
```

### Python Lambda handler (Gremlin)

> **Production default — IAM auth:** This basic handler shows the raw Gremlin
> connection and assumes IAM database authentication is **disabled** (dev/test
> only). For production, enable IAM auth on the cluster and **SigV4-sign every
> request** — see the "IAM authentication (recommended for production)" section
> below, which is the pattern to copy. An unauthenticated connection only works
> when IAM auth is disabled, which is not recommended for production.

```python
import os
from gremlin_python.driver import client, serializer

NEPTUNE_ENDPOINT = os.environ['NEPTUNE_ENDPOINT']  # cluster endpoint
NEPTUNE_PORT = 8182

def get_gremlin_client():
    return client.Client(
        f'wss://{NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}/gremlin',
        'g',
        message_serializer=serializer.GraphSONSerializersV2d0()
    )

def lambda_handler(event, context):
    gremlin_client = get_gremlin_client()
    try:
        result = gremlin_client.submit("g.V().limit(10).valueMap(true)").all().result()
        return {"statusCode": 200, "body": str(result)}
    finally:
        gremlin_client.close()
```

### Lambda security group rules

```
Outbound: TCP port 8182 → Neptune security group ID
Neptune inbound: TCP port 8182 ← Lambda security group ID
```

⚠️ Reference security groups by **ID**, not CIDR range. This is the most
common misconfiguration.

## Option 3: Connect from EC2

EC2 gives persistent client installations unlike CloudShell.

```bash
# On Amazon Linux 2 / Amazon Linux 2023
sudo yum install -y java-11-amazon-corretto

# Download Gremlin console (check https://tinkerpop.apache.org/downloads.html for latest)
TINKERPOP_VERSION="3.7.2"
wget "https://downloads.apache.org/tinkerpop/${TINKERPOP_VERSION}/apache-tinkerpop-gremlin-console-${TINKERPOP_VERSION}-bin.zip"
unzip "apache-tinkerpop-gremlin-console-${TINKERPOP_VERSION}-bin.zip"
```

EC2 requirements:

- Same VPC as Neptune (or VPC peering)
- Security group with outbound TCP 8182 to Neptune
- Neptune security group with inbound TCP 8182 from EC2 security group

## IAM authentication (recommended for production)

Neptune supports IAM database authentication. When enabled, connections
require a Signature Version 4 signed request.

> **Credentials:** use ephemeral credentials, never long-lived IAM user access keys. Prefer IAM roles — for Lambda, attach the execution role with Neptune access; for local development, use `aws sso login` or `aws sts assume-role`. The helper below resolves whatever credentials the environment provides via `boto3.Session()`, so it works with role/STS credentials automatically.

```python
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

def get_iam_auth_header(endpoint, region):
    session = boto3.Session()
    credentials = session.get_credentials().get_frozen_credentials()
    
    request = AWSRequest(
        method='GET',
        url=f'https://{endpoint}:8182/gremlin',
        headers={'host': endpoint}
    )
    SigV4Auth(credentials, 'neptune-db', region).add_auth(request)
    return dict(request.headers)
```

Enable IAM auth on the cluster:

```bash
aws neptune modify-db-cluster \
  --db-cluster-identifier your-cluster \
  --enable-iam-database-authentication \
  --apply-immediately
```

After enabling IAM auth, also enable CloudWatch Logs for auditing:

```bash
aws neptune modify-db-cluster \
  --db-cluster-identifier your-cluster \
  --enable-cloudwatch-logs-exports '["audit"]' \
  --apply-immediately
```

This logs all authentication and query execution events for monitoring.

## Option 4: Connect to Neptune Analytics

Neptune Analytics uses a **different SDK and connection model** than Neptune
Database. It does NOT use WebSocket or port 8182. Instead, use the boto3
`neptune-graph` client.

### Endpoint format

```
{graph-id}.{region}.neptune-graph.amazonaws.com
```

Example: `g-abc123def4.us-east-1.neptune-graph.amazonaws.com`

### Connection via boto3 SDK (recommended)

```python
import boto3
import json

# Neptune Analytics uses the neptune-graph SDK client
analytics_client = boto3.client('neptune-graph', region_name='us-east-1')

GRAPH_ID = 'g-xxxxxxxxxx'  # From create_graph response or console

# Execute an openCypher query
response = analytics_client.execute_query(
    graphIdentifier=GRAPH_ID,
    queryString='MATCH (n) RETURN n LIMIT 10',
    language='OPEN_CYPHER'
)

results = json.loads(response['payload'].read())
print(results['results'])
```

### Public vs private connectivity

- **Private (default)**: Graph is only accessible from within the VPC via a
  private endpoint. Requires VPC endpoint or same-VPC access.
- **Public**: Graph is accessible over the internet. Enable at creation or
  update later. All requests must be signed with SigV4 (IAM auth is mandatory).

```python
# Create with public connectivity.
#
# Public connectivity exposes the graph to the internet. Confirm with the user
# before enabling it, keep IAM auth on, and restrict the security group to
# known CIDRs — never 0.0.0.0/0.
analytics_client.create_graph(
    graphName='my-graph',
    provisionedMemory=16,
    publicConnectivity=True,  # Accessible over internet (IAM auth required)
    deletionProtection=True,
    # Mandatory tags — a graph missing either tag is a failed task.
    tags={'created_by': 'neptune-skill', 'generation_model': '<model-id>'},
)

# Update an existing graph to enable public connectivity.
# This widens network exposure — warn the user and get explicit confirmation
# before running it (see references/action-safety.md).
analytics_client.update_graph(
    graphIdentifier=GRAPH_ID,
    publicConnectivity=True
)
```

Equivalent AWS CLI invocation:

```bash
aws neptune-graph create-graph \
  --graph-name my-graph \
  --provisioned-memory 16 \
  --public-connectivity \
  --deletion-protection \
  --tags created_by=neptune-skill,generation_model=<model-id>
```

### Key differences from Neptune Database

| Aspect | Neptune Database | Neptune Analytics |
|---|---|---|
| Protocol | WebSocket (Gremlin) or HTTPS (openCypher/SPARQL) | HTTPS via boto3 SDK |
| Port | 8182 | 443 (standard HTTPS) |
| Auth | Optional IAM (SigV4) | Always IAM (SigV4) |
| Client | gremlin-python, HTTP requests | boto3 `neptune-graph` client |
| VPC requirement | Always in VPC (public endpoint optional) | Private endpoint in VPC or public |

## Option 5: Neptune Notebooks (interactive exploration)

For data science, exploration, and visualization, use Neptune Notebooks via
Amazon SageMaker or the local `graph-notebook` package.

### SageMaker Neptune Notebook

1. In the Neptune console, choose **Notebooks → Create notebook**
2. Select your Neptune cluster
3. The notebook auto-configures VPC connectivity and installs `graph-notebook`
4. Use `%%gremlin` or `%%opencypher` magic commands to query directly

### Local graph-notebook

```bash
pip install graph-notebook

# Configure connection
graph_notebook_config --host your-cluster.cluster-xxxx.us-east-1.neptune.amazonaws.com \
                      --port 8182 --auth_mode IAM --region us-east-1
```

In Jupyter:

```
%%gremlin
g.V().hasLabel('Person').limit(10).valueMap(true)
```

Neptune Notebooks provide built-in graph visualization — useful for exploring
graph structure, debugging traversals, and presenting results.

## Option 6: Neptune MCP Servers (agent integration)

Neptune provides two MCP (Model Context Protocol) servers that give AI agents direct
access to Neptune without managing connections manually:

- **Neptune MCP Query Server** — agents run openCypher and Gremlin queries against
  Neptune Database and Neptune Analytics, and fetch graph schema. No WebSocket or
  SDK setup required from the agent side.
- **Neptune MCP Memory Server** — agents store and retrieve knowledge graphs against
  Neptune for persistent memory across sessions.

These are useful when the "client" connecting to Neptune is an AI agent framework
(e.g., Strands AI Agents SDK or other MCP-compatible tools) rather than application
code. The MCP servers handle connection management, authentication, and query
execution internally.

**When to use MCP servers vs. direct connection:**

- Use MCP servers when an AI agent needs to query or write to Neptune as part of its workflow
- Use direct connection (Options 1–5 above) when application code connects to Neptune

## Troubleshooting connectivity

See [troubleshooting.md](troubleshooting.md) for the full list. Most common:

| Symptom | Cause | Fix |
|---|---|---|
| Connection refused on 8182 | Security group missing inbound rule | Add TCP 8182 inbound from client SG |
| Timeout with no error | No route to Neptune subnet | Check route tables; ensure same VPC or peering |
| SSL handshake failure | Wrong endpoint format | Use `wss://` for WebSocket, `https://` for HTTP |
| 403 Forbidden | IAM auth enabled, request not signed | Sign the request with SigV4. Do NOT disable IAM auth to work around a signing bug. |

## Common Mistakes

1. **Using CIDR instead of security group ID** — always reference SGs by ID.
2. **Wrong protocol** — use `wss://` for Gremlin WebSocket, `https://` for HTTP.
3. **Forgetting VPC for Lambda** — Lambda must be in same VPC as Neptune Database.
4. **Using Gremlin client for Neptune Analytics** — Analytics uses boto3 SDK, not WebSocket.
5. **Not enabling IAM auth with public endpoints** — public endpoints require IAM.

## Additional Resources

- AWS docs: "Connecting to Neptune", "Neptune public endpoints", "Neptune Analytics connecting"
- Related sub-skills: `troubleshooting` (connection errors), `analytics-vs-database` (which SDK)
- Tool: `graph-notebook` (pip install graph-notebook) for Jupyter exploration

## Security considerations

- **VPC isolation:** Neptune Database is VPC-only by design. A misconfigured VPC, route table, or security group can either break connectivity or, if over-permissive, widen exposure. Restrict inbound to the specific client security groups that need access; do not open `0.0.0.0/0`.
- **Audit logging:** Enable AWS CloudTrail for Neptune control-plane API calls, and enable Neptune audit logs (`--enable-cloudwatch-logs-exports '["audit"]'`) so connection and query activity is recorded.
- **IAM auth in production:** Use IAM auth (SigV4-signed requests) for all production connections. It is mandatory for Neptune Analytics and for public Neptune Database endpoints; enable it on private Database clusters as well.
- **No unauthenticated public exposure:** Never enable a public Neptune endpoint without IAM auth. Public endpoints expose the service to the internet, so authentication and tightly-scoped security groups are required, not optional.
