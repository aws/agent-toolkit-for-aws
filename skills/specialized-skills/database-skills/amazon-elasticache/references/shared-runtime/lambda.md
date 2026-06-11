# Lambda Integration with ElastiCache

## VPC Attachment Requirement

Lambda must be deployed in the same VPC as the ElastiCache cache. Without VPC attachment, Lambda cannot reach ElastiCache endpoints.

Configure VPC in the Lambda function:

- Assign at least two private subnets (same ones the cache uses, or subnets that can route to them)
- Assign a security group that allows outbound traffic to the cache security group on port 6379 (and 6380 for serverless reader endpoint)

## IAM Permissions

The Lambda execution role needs two sets of permissions:

### VPC networking (required)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "LambdaVPCAccess",
      "Effect": "Allow",
      "Action": [
        "ec2:CreateNetworkInterface",
        "ec2:DescribeNetworkInterfaces",
        "ec2:DeleteNetworkInterface",
        "ec2:DescribeSubnets",
        "ec2:AssignPrivateIpAddresses",
        "ec2:UnassignPrivateIpAddresses"
      ],
      "Resource": "*"
    }
  ]
}
```

Alternatively, attach the AWS managed policy `AWSLambdaVPCAccessExecutionRole`.

> **Note:** The `AWSLambdaVPCAccessExecutionRole` managed policy also includes CloudWatch Logs permissions (`logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`). If using the custom policy above instead, attach `AWSLambdaBasicExecutionRole` alongside it to retain CloudWatch logging.

### ElastiCache Connect (required for IAM auth)

```json
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
```

Use `serverlesscache:` for serverless caches, `replicationgroup:` for node-based clusters. Include both if the policy covers multiple deployment types.

### Secrets Manager access (required for RBAC password auth)

```json
{
  "Sid": "SecretsAccess",
  "Effect": "Allow",
  "Action": "secretsmanager:GetSecretValue",
  "Resource": "arn:aws:secretsmanager:<region>:<account-id>:secret:elasticache/*"
}
```

## Environment Variables

Set these on the Lambda function configuration:

| Variable | Example | Purpose |
|----------|---------|---------|
| `CACHE_ENDPOINT` | `my-cache-abc123.serverless.use1.cache.amazonaws.com` | Cache hostname |
| `CACHE_PORT` | `6379` | Cache port |
| `CACHE_NAME` | `my-cache` | Cache name (used for IAM token generation) |

For RBAC password auth, reference a Secrets Manager secret rather than storing credentials in environment variables.

## Python Connection (valkey-py with IAM auth)

```python
import os
import boto3
import valkey
from valkey import AuthenticationError

# Module-level: connection is reused across warm invocations
_client = None

def _get_iam_auth_token(cache_name: str, user_id: str, is_serverless: bool = True) -> str:
    """Generate IAM auth token via SigV4 presigned URL."""
    import botocore.session
    from botocore.signers import RequestSigner
    from botocore.model import ServiceId
    region = os.environ.get('AWS_REGION', 'us-east-1')
    session = boto3.Session()
    creds = session.get_credentials().get_frozen_credentials()
    signer = RequestSigner(
        ServiceId("elasticache"), region, "elasticache", "v4",
        creds, botocore.session.get_session().get_component("event_emitter"),
    )
    query = f"Action=connect&User={user_id}"
    if is_serverless:
        query += "&ResourceType=ServerlessCache"
    url = signer.generate_presigned_url(
        {"method": "GET", "url": f"https://{cache_name}/?{query}",
         "body": {}, "headers": {}, "context": {}},
        operation_name="connect", expires_in=900, region_name=region,
    )
    return url[len("https://"):] if url.startswith("https://") else url


def get_cache_client():
    """Lazy-init connection with IAM auth. Reuses across warm invocations."""
    global _client
    if _client is not None:
        try:
            _client.ping()
            return _client
        except Exception:
            _client = None

    endpoint = os.environ['CACHE_ENDPOINT']
    port = int(os.environ.get('CACHE_PORT', '6379'))
    user_id = os.environ.get('CACHE_USER_ID', 'appuser')
    cache_name = os.environ.get('CACHE_NAME', 'cache-01')

    is_serverless = os.environ.get('CACHE_IS_SERVERLESS', 'true').lower() == 'true'
    token = _get_iam_auth_token(cache_name, user_id, is_serverless)

    conn_kwargs = dict(
        host=endpoint,
        port=port,
        username=user_id,
        password=token,
        ssl=True,
        ssl_cert_reqs='required',
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
    )
    if is_serverless:
        # Serverless requires cluster-mode client
        _client = valkey.ValkeyCluster(**conn_kwargs)
    else:
        _client = valkey.Valkey(**conn_kwargs)
    return _client


def handler(event, context):
    cache = get_cache_client()
    # Example: cache-aside pattern
    key = f"item:{event.get('item_id')}"
    cached = cache.get(key)
    if cached:
        return {'statusCode': 200, 'body': cached, 'source': 'cache'}

    # On miss: fetch from origin, store with TTL
    result = fetch_from_database(event['item_id'])
    cache.set(key, result, ex=300)  # 5 minute TTL
    return {'statusCode': 200, 'body': result, 'source': 'database'}
```

Key patterns in this snippet:

- **Module-level `_client`**: Connection persists across warm Lambda invocations, avoiding cold-start reconnection overhead
- **Lazy init with health check**: `ping()` validates the connection; recreates on failure
- **IAM auth token**: Generated fresh on each new connection (tokens valid 15 minutes, connections are automatically disconnected after 12 hours unless prolonged by re-authenticating with a new token). For long-lived connections, consider using a Valkey or Redis OSS client that supports a credentials provider interface to auto-generate tokens.
- **TLS enabled**: `ssl=True` is mandatory for serverless caches
- **Timeouts**: Explicit connect and socket timeouts prevent Lambda from hanging

## Python Connection (valkey-py with RBAC password from Secrets Manager)

```python
import os
import json
import valkey
import boto3

_client = None
_secrets_client = boto3.client('secretsmanager')


def _get_credentials() -> tuple[str, str]:
    """Retrieve RBAC credentials from Secrets Manager."""
    secret_name = os.environ.get('CACHE_SECRET_NAME', 'elasticache/myapp/appuser')
    response = _secrets_client.get_secret_value(SecretId=secret_name)
    secret = json.loads(response['SecretString'])
    return secret['username'], secret['password']


def get_cache_client() -> valkey.Valkey:
    """Lazy-init connection with RBAC password auth."""
    global _client
    if _client is not None:
        try:
            _client.ping()
            return _client
        except Exception:
            _client = None

    endpoint = os.environ['CACHE_ENDPOINT']
    port = int(os.environ.get('CACHE_PORT', '6379'))
    username, password = _get_credentials()

    _client = valkey.Valkey(
        host=endpoint,
        port=port,
        username=username,
        password=password,
        ssl=True,
        ssl_cert_reqs='required',
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
    )
    return _client
```

## Node.js Connection (iovalkey with TLS)

**Note:** This example reads credentials from environment variables for simplicity. In production, use IAM authentication or retrieve credentials from Secrets Manager instead of storing passwords in plaintext environment variables.

```javascript
const { Cluster } = require('iovalkey');

// Module-level: reused across warm invocations
let client = null;

function getCacheClient() {
  if (client) return client;

  const endpoint = process.env.CACHE_ENDPOINT;
  const port = parseInt(process.env.CACHE_PORT || '6379', 10);

  // For serverless or cluster-mode-enabled caches
  client = new Cluster(
    [{ host: endpoint, port }],
    {
      dnsLookup: (address, callback) => callback(null, address),
      slotsRefreshTimeout: 2000,
      redisOptions: {
        tls: {},
        username: process.env.CACHE_USERNAME || 'appuser',
        password: process.env.CACHE_PASSWORD,
        connectTimeout: 5000,
        commandTimeout: 5000,
      },
    }
  );

  client.on('error', (err) => {
    console.error('Cache connection error:', err.message);
    client = null;
  });

  return client;
}

exports.handler = async (event) => {
  const cache = getCacheClient();

  const key = `item:${event.itemId}`;
  const cached = await cache.get(key);
  if (cached) {
    return { statusCode: 200, body: cached, source: 'cache' };
  }

  const result = await fetchFromDatabase(event.itemId);
  await cache.set(key, result, 'EX', 300);
  return { statusCode: 200, body: result, source: 'database' };
};
```

## Secret Management

| Method | When to use | How |
|--------|------------|-----|
| **IAM auth (preferred)** | Valkey 7.2+ or Redis OSS 7.0+ serverless or node-based | No secrets to manage. Token generated from IAM credentials. |
| **Secrets Manager** | RBAC with password auth | Store `{"username":"...","password":"..."}` in Secrets Manager. Reference via `CACHE_SECRET_NAME` env var. Enable rotation. |
| **Never in env vars** | Passwords should not be stored as plaintext Lambda environment variables | Use Secrets Manager or IAM auth instead. |

## Cold Start Considerations

- Since the September 2019 Hyperplane ENI improvements, VPC attachment no longer adds significant cold-start latency (significantly reduced from the previous ~14 seconds to under 1 second, per the AWS blog on Hyperplane ENI improvements). This is a one-time cost per execution environment.
- Use provisioned concurrency for latency-sensitive workloads to keep Lambda warm.
- The lazy connection pattern above ensures the cache client is only created when first needed, not during module import (which would add to cold start time if the connection fails).
- IAM auth token generation adds ~50-100ms on first connection (approximate; not an AWS-documented figure). The token is reused for the lifetime of the connection.
