# DynamoDB Read-Through and Write-Through Caching (AWS ElastiCache Integration Client)

The AWS ElastiCache Integration Client adds read-through and write-through caching to the application's existing DynamoDB SDK client. Supported reads are served from an ElastiCache Serverless cache; writes go to DynamoDB and update or invalidate the cache. Data-access code does not change, and there is no cache-aside code or valkey-py client to write.

## Prerequisites

- An ElastiCache Serverless cache running Valkey 9.0+. Node-based clusters, Redis OSS, and Memcached are not supported; for those, use cache-aside (`data-modeling` sub-skill).
- Python, Java, or Node.js.

## Setup

| Language | Package | Wiring |
|---|---|---|
| Python | `aws-elasticache-integration-client` (PyPI) | `install()` on the existing boto3 DynamoDB client |
| Node.js | `@aws-sdk/aws-elasticache-integration-client` (npm) | `install({ client, endpoint, cacheName })` on the existing AWS SDK v3 DynamoDB client |
| Java | `software.amazon.elasticache:aws-elasticache-integration-client` (Maven) | `ElastiCacheIntegrationsClient.builder().endpoint(...).cacheName(...).install(...)` on the existing `DynamoDbClient` builder (`installAsync` for `DynamoDbAsyncClient`) |

Python, initialized on first use (never at import time):

```python
import boto3
import aws_elasticache_integration_client

_ddb_client = None

def get_ddb_client():
    global _ddb_client
    if _ddb_client is None:
        _ddb_client = boto3.client("dynamodb", region_name="us-east-1")
        aws_elasticache_integration_client.install(
            client=_ddb_client, endpoint="<cache-endpoint>", cache_name="<cache-name>"
        )
    return _ddb_client
```

## IAM and security

- The application's IAM identity needs `elasticache:Connect` on the cache, plus its usual DynamoDB permissions. Cache misses and writes call DynamoDB with the application's credentials.
- **Warning:** DynamoDB IAM and resource policies are evaluated only when DynamoDB serves the request. A cache hit is served by ElastiCache with no DynamoDB policy check, so anyone with `elasticache:Connect` on the cache can read the cached items, whatever the table's resource policy allows.
- Limit who holds `elasticache:Connect` on the cache, and use a separate cache for each group of principals with different DynamoDB access.
- Java: the cache uses the built `DynamoDbClient`'s region and credentials, so no separate credentials setup is needed. `install()` fails if the builder already sets `httpClient` or `httpClientBuilder`. Pass a custom HTTP client as `originHttpClient` instead.
