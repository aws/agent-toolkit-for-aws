# Connecting to ElastiCache

ElastiCache-specific connection constraints, tunnel patterns, and runtime gotchas.

## VPC Access Only

ElastiCache runs inside a VPC. You cannot connect from the public internet. Options:

1. Connect from compute in the same VPC (EC2, Lambda, ECS, EKS)
2. SSM port forwarding (no SSH keys needed, use `scripts/start_tunnel.py` and `scripts/find_tunnel_host.py`)
3. Jump host with SSH tunnel

## Jump Host / SSM Tunnel

Primary path (bundled scripts, boto3-based):

```bash
python3 scripts/find_tunnel_host.py --vpc-id <vpc-id> --region <region>
python3 scripts/start_tunnel.py --instance-id <id> --cache-host <endpoint> --region <region>
```

`find_tunnel_host.py` locates an SSM-managed instance in the VPC. `start_tunnel.py` opens the SSM port-forwarding tunnel through it.

After tunnel is established, clean up: stop or terminate the EC2 instance if the skill created one. If `find_tunnel_host.py` reused an existing SSM-managed instance, stopping the tunnel is enough.

## Tunnel Mode TLS Gotcha

When connecting through an SSM tunnel to `127.0.0.1`, the TLS certificate is issued for `*.cache.amazonaws.com`, not localhost. You must disable hostname verification while keeping CA certificate validation.

| Language | Setting |
|----------|---------|
| Python (valkey-py) | `ssl_check_hostname=False` (keep `ssl_cert_reqs="required"`) |
| Node.js (ioredis) | `tls: { checkServerIdentity: () => undefined }` |
| Java (Lettuce) | `redisURI.setVerifyPeer(SslVerifyMode.CA)` |
| Go (go-redis) | `TLSConfig: &tls.Config{InsecureSkipVerify: true, VerifyPeerCertificate: customCACertVerifier}` (use a custom `VerifyPeerCertificate` func to validate the CA chain) |
| CLI | `valkey-cli --tls --insecure` (note: `--insecure` disables both CA and hostname verification) |

**These settings are for local development only. Never use in production.**

## IAM Auth Token Generation

ElastiCache IAM auth uses SigV4 presigned URLs (not a dedicated SDK method):

```python
from botocore.signers import RequestSigner
from botocore.model import ServiceId
import boto3

def generate_iam_auth_token(cache_name: str, user_id: str, region: str, is_serverless: bool = True) -> str:
    import botocore.session
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

token = generate_iam_auth_token(
    "my-cache", "my-iam-user", "us-east-1", is_serverless=True
)
# Pass token as password, user ID as username, ssl=True
```

Constraints:

- Token valid for 15 minutes (for initial AUTH/HELLO). An authenticated connection remains valid for up to 12 hours; re-AUTH with a new token within 12 hours to extend. Connections that are not re-authenticated within 12 hours are terminated.
- IAM auth does NOT work inside MULTI/EXEC transactions
- Requires Valkey 7.2+ or Redis OSS 7.0+

## Endpoint Formats

| Deployment | Primary | Reader |
|-----------|---------|--------|
| Serverless | `name-xxxxx.serverless.use1.cache.amazonaws.com:6379` | `name-xxxxx.serverless.use1.cache.amazonaws.com:6380` |
| Node-based (cluster mode) | `name.xxxxx.clustercfg.use1.cache.amazonaws.com:6379` (configuration endpoint) | *(cluster-aware clients discover shards via the configuration endpoint; use `CLUSTER SLOTS` or `CLUSTER SHARDS` for shard-aware routing)* |
| Node-based (single shard) | `name.xxxxx.ng.0001.use1.cache.amazonaws.com:6379` | (reader endpoint from `describe-replication-groups`) |

> **Note:** Always retrieve endpoints from `describe-serverless-caches` or `describe-replication-groups` rather than constructing them manually. Serverless caches operate in cluster-mode-enabled only; clients must use a cluster-aware driver (e.g., `ValkeyCluster` / `RedisCluster` in Python, `new Redis.Cluster()` in ioredis). For TLS-enabled cluster mode clusters, discovery commands (`cluster slots`, `cluster shards`, `cluster nodes`) return hostnames instead of IPs. The IP Discovery parameter has no effect on TLS-enabled clusters; the IP protocol used is determined by the client's DNS resolution preference.

## TLS Rules

- **Serverless**: TLS always enabled, cannot be disabled. Always use `ssl=True` / `tls: {}`.
- **Node-based**: TLS is optional but recommended. Can be enabled at creation time, or enabled on existing clusters using a two-step migration: first set `transit-encryption-mode` to `preferred` (allows both encrypted and unencrypted connections), then set to `required` (encrypted only).
- Serverless security groups need both port 6379 (primary) and 6380 (reader).

## Authentication by Deployment

| Auth Method | Serverless | Node-Based |
|-------------|-----------|------------|
| RBAC + IAM auth | Yes (preferred) | Yes (preferred) |
| RBAC + password | Yes | Yes |
| AUTH token (legacy) | **NOT supported** | Yes (legacy only) |

## Runtime-Specific Gotchas

### Lambda

- Requires VPC attachment (`VpcConfig` with subnets and security group)
- Needs `ec2:CreateNetworkInterface`, `ec2:DescribeNetworkInterfaces`, `ec2:DeleteNetworkInterface` permissions
- Since the September 2019 Hyperplane ENI improvements, VPC cold starts add only tens to low-hundreds of milliseconds (not the 1-2s of pre-2019 behavior). For IAM-authenticated connections, expect approximately 50-100ms additional overhead (estimate; actual overhead depends on SigV4 signing and network conditions). Reuse connections across invocations via module-level client
- Use IAM auth to avoid managing secrets in environment variables

### ECS

- Use `awsvpc` network mode for per-task ENIs in the same VPC
- Task security group must allow outbound to cache security group on port 6379
- Reuse connections across requests (connection pooling)

### EKS

- VPC CNI plugin affects pod-to-cache reachability; pods must have IPs in the VPC CIDR
- Use Kubernetes secrets or AWS Secrets Manager CSI driver for credential injection
- Pod service account with IAM role for IAM auth (IRSA or EKS Pod Identity)
