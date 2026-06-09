# ECS Integration with ElastiCache

## Network Mode: awsvpc

Use `awsvpc` network mode for ECS tasks. Each task gets its own Elastic Network Interface (ENI) with a private IP in the VPC, enabling direct communication with ElastiCache endpoints.

## Security Group Configuration

The ECS task security group must allow outbound traffic to the cache security group:

| Direction | Protocol | Port | Target | Purpose |
|-----------|----------|------|--------|---------|
| Task SG outbound | TCP | 6379 | Cache SG | Primary endpoint |
| Task SG outbound | TCP | 6380 | Cache SG | Reader endpoint (serverless only) |
| Cache SG inbound | TCP | 6379 | Task SG | Allow from ECS tasks |
| Cache SG inbound | TCP | 6380 | Task SG | Allow from ECS tasks (serverless) |

## Task Definition Configuration

### Environment variables

```json
{
  "containerDefinitions": [
    {
      "name": "app",
      "environment": [
        { "name": "CACHE_ENDPOINT", "value": "my-cache.serverless.use1.cache.amazonaws.com" },
        { "name": "CACHE_PORT", "value": "6379" }
      ],
      "secrets": [
        {
          "name": "CACHE_PASSWORD",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789012:secret:elasticache/myapp/appuser:password::"
        },
        {
          "name": "CACHE_USERNAME",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789012:secret:elasticache/myapp/appuser:username::"
        }
      ]
    }
  ]
}
```

> **`valueFrom` pattern:** The format is `<secret-arn>:<json-key>:<version-stage>:<version-id>`. The trailing `::` leaves version-stage and version-id empty, which resolves to the latest version (AWSCURRENT).

When using IAM auth instead of passwords, omit the `secrets` block and configure the task role with `elasticache:Connect` permissions.

> **IAM auth note:** The ElastiCache user-id and user-name must be identical when using IAM-authenticated users. If they differ, the IAM auth token signing will not match and the connection will be rejected.

### Task role permissions (IAM auth)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ElastiCacheConnect",
      "Effect": "Allow",
      "Action": "elasticache:Connect",
      "Resource": [
        "arn:aws:elasticache:<region>:<account-id>:serverlesscache:<cache-name>",
        "arn:aws:elasticache:<region>:<account-id>:replicationgroup:<rg-id>",
        "arn:aws:elasticache:<region>:<account-id>:user:<user-id>"
      ]
    }
  ]
}
```

Use `serverlesscache:` for serverless caches, `replicationgroup:` for node-based clusters. Include both if the policy covers multiple deployment types.

### Task execution role permissions (Secrets Manager)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SecretsAccess",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "arn:aws:secretsmanager:<region>:<account-id>:secret:elasticache/*"
    }
  ]
}
```

> **KMS note:** If the secret is encrypted with a customer-managed KMS key (not the default `aws/secretsmanager` key), the execution role also needs `kms:Decrypt` permission on that KMS key ARN. The default AWS-managed key does not require this additional permission.

## Connection Pooling

ECS tasks are long-lived (unlike Lambda). Use connection pools to manage connections efficiently:

- **Pool size**: Match to expected concurrent command usage per task. Start with 10-20 connections.
- **Keep-alive**: Enable TCP keepalive to prevent idle connection drops by NAT gateways or load balancers.
- **Health checks**: Periodically ping the connection to detect stale connections early.
- **Graceful shutdown**: Drain connections on task stop (handle SIGTERM).

## Python Connection (valkey-py with TLS and connection pool)

```python
import os
import valkey

# Connection pool: shared across all requests within this task
# For ElastiCache Serverless (cluster mode enabled), use ValkeyCluster:
_client = valkey.cluster.ValkeyCluster(
    host=os.environ['CACHE_ENDPOINT'],
    port=int(os.environ.get('CACHE_PORT', '6379')),
    username=os.environ.get('CACHE_USERNAME', 'appuser'),
    password=os.environ.get('CACHE_PASSWORD', ''),
    ssl=True,
    ssl_cert_reqs='required',
    decode_responses=True,
    max_connections=20,
    socket_connect_timeout=5,
    socket_timeout=5,
    socket_keepalive=True,
    retry_on_timeout=True,
    health_check_interval=30,
)

# For node-based cluster-mode-disabled deployments, use instead:
# _pool = valkey.ConnectionPool(
#     host=os.environ['CACHE_ENDPOINT'],
#     port=int(os.environ.get('CACHE_PORT', '6379')),
#     ...
# )
# def get_cache_client() -> valkey.Valkey:
#     return valkey.Valkey(connection_pool=_pool)


def get_cache_client() -> valkey.cluster.ValkeyCluster:
    """Return the shared cluster-aware client."""
    return _client


# Usage in a request handler (e.g., Flask, FastAPI)
def handle_request(item_id: str) -> dict:
    cache = get_cache_client()
    key = f"item:{item_id}"
    cached = cache.get(key)
    if cached:
        return {'data': cached, 'source': 'cache'}

    result = fetch_from_database(item_id)
    cache.set(key, result, ex=300)
    return {'data': result, 'source': 'database'}


# Graceful shutdown on SIGTERM
import signal
import sys

def shutdown_handler(signum, frame):
    _client.close()
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown_handler)
```

## Node.js Connection (iovalkey with TLS and connection pool)

```javascript
const { Cluster } = require('iovalkey');

// Cluster client with built-in connection pooling
const client = new Cluster(
  [{ host: process.env.CACHE_ENDPOINT, port: parseInt(process.env.CACHE_PORT || '6379', 10) }],
  {
    dnsLookup: (address, callback) => callback(null, address),
    slotsRefreshTimeout: 2000,
    redisOptions: {
      tls: {},
      username: process.env.CACHE_USERNAME || 'appuser',
      password: process.env.CACHE_PASSWORD,
      connectTimeout: 5000,
      commandTimeout: 5000,
      keepAlive: 30000,
    },
    // Retry strategy for transient failures
    clusterRetryStrategy: (times) => Math.min(times * 100, 3000),
  }
);

client.on('error', (err) => {
  console.error('Cache connection error:', err.message);
});

// Usage in an Express/Fastify route
async function handleRequest(req, res) {
  const key = `item:${req.params.itemId}`;
  const cached = await client.get(key);
  if (cached) {
    return res.json({ data: cached, source: 'cache' });
  }

  const result = await fetchFromDatabase(req.params.itemId);
  await client.set(key, result, 'EX', 300);
  return res.json({ data: result, source: 'database' });
}

// Graceful shutdown
process.on('SIGTERM', async () => {
  await client.quit();
  process.exit(0);
});
```

## CloudFormation snippet: ECS service with cache access

```yaml
ECSTaskDefinition:
  Type: AWS::ECS::TaskDefinition
  Properties:
    NetworkMode: awsvpc
    TaskRoleArn: !GetAtt TaskRole.Arn
    ExecutionRoleArn: !GetAtt ExecutionRole.Arn
    ContainerDefinitions:
      - Name: app
        Image: !Ref AppImage
        Environment:
          - Name: CACHE_ENDPOINT
            Value: !ImportValue cache-stack-Endpoint
          - Name: CACHE_PORT
            Value: '6379'
        Secrets:
          - Name: CACHE_PASSWORD
            ValueFrom: !Sub 'arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:elasticache/myapp/appuser:password::'

ECSService:
  Type: AWS::ECS::Service
  Properties:
    TaskDefinition: !Ref ECSTaskDefinition
    NetworkConfiguration:
      AwsvpcConfiguration:
        Subnets: !Ref PrivateSubnetIds
        SecurityGroups:
          - !Ref TaskSecurityGroup
```
