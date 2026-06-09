# EKS Integration with ElastiCache

## VPC CNI: Pods Get VPC IPs

With the Amazon VPC CNI plugin (default on EKS), each pod receives a VPC IP address. This means pods can reach ElastiCache endpoints directly without NAT or proxies, as long as security groups allow the traffic.

## Security Group Configuration

| Approach | How it works |
|----------|-------------|
| **Node security group** (default) | All pods on a node share the node's SG. Add an outbound rule from the node SG to the cache SG on port 6379. |
| **Security groups for pods** (recommended for production) | Pods get their own SGs via the `SecurityGroupPolicy` CRD. Allows per-workload least-privilege access to the cache. |

### Node SG approach (simpler)

Add to the EKS node security group:

| Direction | Protocol | Port | Target | Purpose |
|-----------|----------|------|--------|---------|
| Node SG outbound | TCP | 6379 | Cache SG | Cache endpoint (primary and reader) |
| Node SG outbound | TCP | 6380 | Cache SG | Reader endpoint (serverless only) |
| Cache SG inbound | TCP | 6379 | Node SG | Allow from EKS nodes |
| Cache SG inbound | TCP | 6380 | Node SG | Allow from EKS nodes (serverless) |

### Security groups for pods (per-workload isolation)

First, attach the `AmazonEKSVPCResourceController` managed IAM policy to your EKS cluster role (required prerequisite). Then enable the VPC CNI `ENABLE_POD_ENI` setting and create a `SecurityGroupPolicy`:

```bash
# Attach the required managed policy to the cluster role
aws iam attach-role-policy \
  --role-name <your-eks-cluster-role> \
  --policy-arn arn:aws:iam::aws:policy/AmazonEKSVPCResourceController

# Enable pod ENI on the VPC CNI
kubectl set env daemonset aws-node -n kube-system ENABLE_POD_ENI=true
```

Then create a `SecurityGroupPolicy`:

```yaml
apiVersion: vpcresources.k8s.aws/v1beta1
kind: SecurityGroupPolicy
metadata:
  name: cache-access
  namespace: myapp
spec:
  podSelector:
    matchLabels:
      cache-access: "true"
  securityGroups:
    groupIds:
      - sg-0123456789abcdef0  # Pod SG that allows outbound to cache
```

Add the label `cache-access: "true"` to pods that need cache access.

## Secret Wiring

### Recommended: IAM Roles for Service Accounts (IRSA) with IAM Auth

For IAM auth (no passwords needed), configure IRSA so the pod's service account can call `elasticache:Connect`. This is the preferred approach for Valkey 7.2+ / Redis OSS 7.0+ because it eliminates password management entirely.

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: myapp-sa
  namespace: myapp
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/myapp-cache-role
```

The IAM role trust policy must allow the OIDC provider, and the role must have:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
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

### Alternative: EKS Pod Identity with IAM Auth

EKS Pod Identity (available on EKS 1.28+ with platform version eks.4+) is a newer alternative to IRSA with simpler setup. Both work for ElastiCache IAM auth. See AWS documentation for Pod Identity configuration.

### Alternative: External Secrets Operator (ESO) with RBAC Passwords

Use this when IAM auth is not available (older engine versions) or when the client library does not support IAM token generation. The External Secrets Operator syncs secrets from AWS Secrets Manager into Kubernetes secrets automatically.

Install ESO, then create an `ExternalSecret`:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: cache-credentials
  namespace: myapp
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: cache-credentials
    creationPolicy: Owner
  data:
    - secretKey: username
      remoteRef:
        key: elasticache/myapp/appuser
        property: username
    - secretKey: password
      remoteRef:
        key: elasticache/myapp/appuser
        property: password
```

### Alternative: AWS Secrets and Configuration Provider (ASCP) with RBAC Passwords

Mount secrets directly as files in the pod using the CSI Secrets Store driver with the AWS provider:

```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: cache-credentials
  namespace: myapp
spec:
  provider: aws
  parameters:
    objects: |
      - objectName: "elasticache/myapp/appuser"
        objectType: "secretsmanager"
        jmesPath:
          - path: username
            objectAlias: cache-username
          - path: password
            objectAlias: cache-password
  secretObjects:
    - secretName: cache-credentials
      type: Opaque
      data:
        - objectName: cache-username
          key: username
        - objectName: cache-password
          key: password
```

## Pod Deployment with Cache Access

> **Auth paths:** The example below shows env vars for both IAM auth (via IRSA service account) and RBAC password auth (via Kubernetes secrets). In practice, choose one path: use `serviceAccountName` with IAM token generation and omit the `CACHE_USERNAME`/`CACHE_PASSWORD` secret refs for IAM auth, or use the secret refs and omit the IRSA service account annotation for RBAC password auth.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
  namespace: myapp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: myapp
  template:
    metadata:
      labels:
        app: myapp
        cache-access: "true"  # For SecurityGroupPolicy
    spec:
      serviceAccountName: myapp-sa  # For IRSA (IAM auth) -- omit for RBAC password auth
      containers:
        - name: app
          image: myapp:latest
          env:
            - name: CACHE_ENDPOINT
              value: "my-cache.serverless.use1.cache.amazonaws.com"
            - name: CACHE_PORT
              value: "6379"
            # The following are for RBAC password auth only.
            # For IAM auth, generate a SigV4 token at runtime instead (see IAM Auth Token Generation below).
            - name: CACHE_USERNAME
              valueFrom:
                secretKeyRef:
                  name: cache-credentials
                  key: username
            - name: CACHE_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: cache-credentials
                  key: password
```

## IAM Auth Token Generation

When using IRSA or EKS Pod Identity for IAM auth, the pod's service account provides AWS credentials automatically. Use them to generate a SigV4 presigned URL token:

```python
import os
import botocore.session
from botocore.signers import RequestSigner
from botocore.model import ServiceId

def get_iam_auth_token(cache_name: str, user_id: str, is_serverless: bool = True) -> str:
    region = os.environ.get('AWS_REGION', 'us-east-1')
    session = botocore.session.get_session()
    creds = session.get_credentials().get_frozen_credentials()
    signer = RequestSigner(
        ServiceId("elasticache"), region, "elasticache", "v4",
        creds, session.get_component("event_emitter"),
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
```

Pass the returned token as the `password` parameter when connecting, with `user_id` as `username`.

## Connection Snippets

Connection code is the same as ECS. The key differences are in how secrets are injected (Kubernetes secrets vs ECS secrets) and how network access is configured (pod SG vs task SG).

### Python (redis-py/valkey-py with TLS and RBAC password auth)

> **Note:** The AWS-validated Python client is [redis-py](https://github.com/redis/redis-py) v4.1.2 (AWS-validated). The `valkey-py` package is the Valkey-specific fork with an API-compatible interface. Either can be used; the examples below use `valkey-py` but you can substitute `import redis` and `redis.RedisCluster` if preferred.

```python
import os
import valkey

# Serverless caches operate in cluster mode enabled only.
# You MUST use a cluster-aware client.
cache = valkey.ValkeyCluster(
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
```

### Node.js (iovalkey with TLS)

```javascript
const { Cluster } = require('iovalkey');

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
  }
);
```

## Service Mesh Considerations

If using AWS App Mesh or Istio:

- **Envoy intercepts all outbound TCP by default**. Envoy sidecar proxies intercept all outbound TCP traffic by default via iptables rules. ElastiCache/Redis traffic is passed through as opaque TCP (not HTTP-routed). This can cause issues with MOVED redirects in cluster mode and TLS termination. Consider excluding ElastiCache ports from sidecar interception if you experience connectivity issues.
- **mTLS**: The mesh's mTLS does not apply to cache traffic. ElastiCache has its own TLS (always-on for serverless). Do not double-TLS.
- **Timeouts and retries**: Configure these in your application client, not in the mesh, since the mesh does not manage the cache protocol.
- **Port exclusion**: If you experience connectivity issues, add an outbound exclusion for the cache endpoint IP range or port 6379 (and port 6380 for serverless reader endpoint) in the mesh configuration.
