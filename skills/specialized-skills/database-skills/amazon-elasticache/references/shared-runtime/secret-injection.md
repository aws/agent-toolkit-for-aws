# Secret Injection Patterns for ElastiCache Credentials

Standardized patterns for injecting cache credentials into Lambda, ECS, and EKS workloads. The endpoint hostname and port are not secrets and can be passed as plain environment variables. Auth credentials (RBAC passwords or IAM tokens) require secure handling.

## Principles

- Never hardcode credentials in application code or container images
- Use IAM auth when possible to eliminate static secrets entirely
- For RBAC password auth, store credentials in AWS Secrets Manager with rotation enabled
- Inject the endpoint (non-secret) as a plain environment variable
- Inject auth credentials through the most secure path available for each compute platform
- IAM auth requires TLS (in-transit encryption). Serverless caches always have TLS enabled; for node-based clusters, TLS must be explicitly enabled before using IAM or RBAC auth.

## Lambda

### Option 1: IAM Auth (preferred)

No secrets to manage. The Lambda execution role generates a short-lived token at runtime.

IAM policy on the Lambda execution role:

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

Application code (Python):

```python
import os
import boto3
import valkey
from botocore.signers import RequestSigner
from botocore.model import ServiceId

# Non-secret config from environment variables
ENDPOINT = os.environ["CACHE_ENDPOINT"]
PORT = int(os.environ.get("CACHE_PORT", "6379"))
REGION = os.environ["AWS_REGION"]
USER_ID = os.environ.get("CACHE_USER_ID", "appuser")

# Generate IAM token at init (outside handler, reused across warm invocations)
CACHE_NAME = os.environ.get("CACHE_NAME", "cache-01")
CACHE_IS_SERVERLESS = os.environ.get("CACHE_IS_SERVERLESS", "true").lower() == "true"

def generate_token():
    import botocore.session
    session = boto3.Session()
    creds = session.get_credentials().get_frozen_credentials()
    signer = RequestSigner(
        ServiceId("elasticache"), REGION, "elasticache", "v4",
        creds, botocore.session.get_session().get_component("event_emitter"),
    )
    query = f"Action=connect&User={USER_ID}"
    if CACHE_IS_SERVERLESS:
        query += "&ResourceType=ServerlessCache"
    url = signer.generate_presigned_url(
        {"method": "GET", "url": f"https://{CACHE_NAME}/?{query}",
         "body": {}, "headers": {}, "context": {}},
        operation_name="connect", expires_in=900, region_name=REGION,
    )
    return url[len("https://"):] if url.startswith("https://") else url

_client = None

def get_client():
    """Lazy-init connection with IAM auth. Reuses across warm invocations."""
    global _client
    if _client is not None:
        try:
            _client.ping()
            return _client
        except Exception:
            _client = None

    token = generate_token()
    conn_kwargs = dict(
        host=ENDPOINT, port=PORT, ssl=True,
        username=USER_ID, password=token,
        decode_responses=True, socket_connect_timeout=5,
        socket_timeout=5, retry_on_timeout=True,
    )
    if CACHE_IS_SERVERLESS:
        # Serverless requires cluster-mode client
        _client = valkey.ValkeyCluster(**conn_kwargs)
    else:
        _client = valkey.Valkey(**conn_kwargs)
    return _client

def handler(event, context):
    # Note: IAM tokens are valid for 15 min; connections auto-disconnect after 12 hours.
    # For long-lived connections, send AUTH with a new token to extend the connection.
    # Lambda execution environments are typically recycled before the 12-hour limit.
    client = get_client()
    return client.get("key")
```

Environment variables in the Lambda configuration:

```
CACHE_ENDPOINT = your-endpoint.cache.amazonaws.com
CACHE_PORT = 6379
CACHE_USER_ID = appuser
CACHE_NAME = cache-01
CACHE_IS_SERVERLESS = true
```

### Option 2: Secrets Manager (for RBAC password auth)

Store the RBAC password in Secrets Manager and retrieve it at Lambda init.

```python
import os
import json
import boto3
import valkey

ENDPOINT = os.environ["CACHE_ENDPOINT"]
SECRET_ARN = os.environ["CACHE_SECRET_ARN"]

# Retrieve secret at init (outside handler)
sm_client = boto3.client("secretsmanager")
secret = json.loads(
    sm_client.get_secret_value(SecretId=SECRET_ARN)["SecretString"]
)

client = valkey.Valkey(
    host=ENDPOINT, port=6379, ssl=True,
    username=secret["username"], password=secret["password"],
    decode_responses=True,
)

def handler(event, context):
    return client.get("key")
```

Lambda execution role needs:

```json
{
  "Effect": "Allow",
  "Action": "secretsmanager:GetSecretValue",
  "Resource": "<secret-arn>"
}
```

### Option 3: AWS Parameters and Secrets Lambda Extension

Use the `AWS-Parameters-and-Secrets-Lambda-Extension` layer to cache Secrets Manager values locally within the Lambda execution environment, reducing Secrets Manager API calls and latency.

```python
import os
import json
import urllib.request
import valkey

ENDPOINT = os.environ["CACHE_ENDPOINT"]
SECRET_ARN = os.environ["CACHE_SECRET_ARN"]
SECRETS_EXTENSION_PORT = os.environ.get("PARAMETERS_SECRETS_EXTENSION_HTTP_PORT", "2773")

# Retrieve via the local extension HTTP endpoint (cached automatically)
headers = {"X-Aws-Parameters-Secrets-Token": os.environ["AWS_SESSION_TOKEN"]}
url = f"http://localhost:{SECRETS_EXTENSION_PORT}/secretsmanager/get?secretId={SECRET_ARN}"
req = urllib.request.Request(url, headers=headers)
secret = json.loads(urllib.request.urlopen(req).read())

client = valkey.Valkey(
    host=ENDPOINT, port=6379, ssl=True,
    username=secret["username"], password=secret["password"],
    decode_responses=True,
)
```

### Environment Variables (non-secret only)

Safe to pass as plain environment variables:

- `CACHE_ENDPOINT` -- the cache hostname
- `CACHE_PORT` -- 6379 or 6380
- `CACHE_USER_ID` -- the RBAC user ID (not the password)

Never place passwords or auth tokens in Lambda environment variables.

## ECS

### Option 1: IAM Auth (preferred)

Attach `elasticache:Connect` to the ECS task role. The application generates IAM tokens at runtime.

Task role policy (for serverless caches):

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

For node-based clusters (replication groups), use the `replicationgroup` resource type instead of `serverlesscache` in the Resource ARN.

Task definition (environment variables for non-secret config):

```json
{
  "containerDefinitions": [
    {
      "name": "app",
      "image": "your-app-image",
      "environment": [
        { "name": "CACHE_ENDPOINT", "value": "your-endpoint.cache.amazonaws.com" },
        { "name": "CACHE_PORT", "value": "6379" },
        { "name": "CACHE_USER_ID", "value": "appuser" },
        { "name": "AWS_REGION", "value": "us-east-1" }
      ]
    }
  ]
}
```

### Option 2: Secrets Manager via Task Definition

Use the `secrets` block in the ECS task definition to inject Secrets Manager values as environment variables. ECS resolves the secret at task launch.

```json
{
  "containerDefinitions": [
    {
      "name": "app",
      "image": "your-app-image",
      "environment": [
        { "name": "CACHE_ENDPOINT", "value": "your-endpoint.cache.amazonaws.com" }
      ],
      "secrets": [
        {
          "name": "CACHE_USERNAME",
          "valueFrom": "arn:aws:secretsmanager:<region>:<account-id>:secret:<secret-name>:username::"
        },
        {
          "name": "CACHE_PASSWORD",
          "valueFrom": "arn:aws:secretsmanager:<region>:<account-id>:secret:<secret-name>:password::"
        }
      ]
    }
  ]
}
```

Task execution role needs:

```json
{
  "Effect": "Allow",
  "Action": "secretsmanager:GetSecretValue",
  "Resource": "<secret-arn>"
}
```

Note: this resolves the secret at task launch. If the secret is rotated, the running task still uses the old value. For rotation-aware behavior, use the init container pattern or SDK-based refresh.

### Option 3: Init Container for Rotation-Aware Caching

Use an init container to fetch and refresh credentials, writing them to a shared volume that the application container reads.

```json
{
  "containerDefinitions": [
    {
      "name": "secret-init",
      "image": "amazon/aws-cli",
      "essential": false,
      "command": [
        "sh", "-c",
        "aws secretsmanager get-secret-value --secret-id $SECRET_ARN --query SecretString --output text > /secrets/cache-creds.json"
      ],
      "environment": [
        { "name": "SECRET_ARN", "value": "<secret-arn>" }
      ],
      "mountPoints": [
        { "sourceVolume": "secrets", "containerPath": "/secrets" }
      ]
    },
    {
      "name": "app",
      "image": "your-app-image",
      "dependsOn": [
        { "containerName": "secret-init", "condition": "SUCCESS" }
      ],
      "mountPoints": [
        { "sourceVolume": "secrets", "containerPath": "/secrets", "readOnly": true }
      ]
    }
  ],
  "volumes": [
    { "name": "secrets" }
  ]
}
```

## EKS

### Option 1: IAM Auth via IRSA (preferred)

Use IAM Roles for Service Accounts (IRSA) to grant the pod's service account `elasticache:Connect` permission. No secrets stored in Kubernetes.

1. Create an IAM role with `elasticache:Connect` and a trust policy for the EKS OIDC provider.
2. Annotate the Kubernetes service account:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: cache-app
  namespace: default
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::<account-id>:role/CacheAppRole
```

1. The pod uses the service account and generates IAM auth tokens at runtime using the injected AWS credentials.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cache-app
spec:
  template:
    spec:
      serviceAccountName: cache-app
      containers:
        - name: app
          image: your-app-image
          env:
            - name: CACHE_ENDPOINT
              value: "your-endpoint.cache.amazonaws.com"
            - name: CACHE_PORT
              value: "6379"
            - name: CACHE_USER_ID
              value: "appuser"
```

### Option 2: External Secrets Operator (for RBAC password auth)

Sync Secrets Manager secrets into Kubernetes Secrets using the External Secrets Operator (ESO).

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: cache-creds
  namespace: default
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: cache-creds
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

Reference in the pod:

```yaml
containers:
  - name: app
    image: your-app-image
    env:
      - name: CACHE_ENDPOINT
        value: "your-endpoint.cache.amazonaws.com"
      - name: CACHE_USERNAME
        valueFrom:
          secretKeyRef:
            name: cache-creds
            key: username
      - name: CACHE_PASSWORD
        valueFrom:
          secretKeyRef:
            name: cache-creds
            key: password
```

The `refreshInterval` ensures rotated secrets are picked up automatically. ESO creates a standard Kubernetes Secret that stays in sync with Secrets Manager.

### Option 3: AWS Secrets and Config Provider (ASCP) for CSI Driver

Mount Secrets Manager secrets as files in the pod filesystem using the AWS Secrets Store CSI Driver.

```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: cache-creds
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
    - secretName: cache-creds-k8s
      type: Opaque
      data:
        - objectName: cache-username
          key: username
        - objectName: cache-password
          key: password
```

Pod spec:

```yaml
spec:
  serviceAccountName: cache-app
  containers:
    - name: app
      image: your-app-image
      volumeMounts:
        - name: secrets
          mountPath: /mnt/secrets
          readOnly: true
      env:
        - name: CACHE_ENDPOINT
          value: "your-endpoint.cache.amazonaws.com"
  volumes:
    - name: secrets
      csi:
        driver: secrets-store.csi.k8s.io
        readOnly: true
        volumeAttributes:
          secretProviderClass: cache-creds
```

The ASCP driver rotates mounted secrets automatically based on the configured rotation interval.

## Decision Guide

| Factor | IAM Auth | Secrets Manager (injected) | Secrets Manager (CSI/ESO) |
|--------|----------|---------------------------|---------------------------|
| No static secrets | Yes | No | No |
| Works with serverless caches | Yes | Yes | Yes |
| IAM re-auth inside MULTI/EXEC | Not supported (MULTI/EXEC data commands still work on IAM-authenticated connections) | N/A | N/A |
| Rotation handling | Automatic (token refresh) | Manual restart or SDK refresh | Automatic (ESO/ASCP) |
| Lambda | Preferred | Good | Not applicable |
| ECS | Preferred | Good (task definition secrets) | Not applicable |
| EKS | Preferred (IRSA) | Good (ESO) | Good (ASCP) |

Default recommendation: use IAM auth when the workload runs on Valkey 7.2+ or Redis OSS 7.0+ with TLS enabled. Note that IAM re-authentication cannot occur inside `MULTI`/`EXEC` blocks, but MULTI/EXEC commands themselves work on IAM-authenticated connections. Fall back to Secrets Manager with rotation for all other cases.
