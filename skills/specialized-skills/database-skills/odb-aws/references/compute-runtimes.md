# Compute Runtimes — EC2, ECS/Fargate, Lambda, EKS, On-Prem

Per-runtime patterns for connecting to ODB@AWS. All runtimes require: VPC peered to the ODB network, subnet in the matching AZ (see **networking-odb-peering.md** (loaded reference)), SG allowing outbound 1521/2484 to the ODB client subnet CIDR, and the Route 53 Resolver forwarding rule associated with the VPC (see **networking-dns-resolver.md** (loaded reference)). Credentials live in AWS Secrets Manager; wallets follow the distribution pattern in **auth-wallet-tcps.md** (loaded reference).

## EC2 in Peered VPC

### Wallet

```bash
mkdir -p /opt/oracle/wallet
# copy cwallet.sso, tnsnames.ora, sqlnet.ora (via S3 or Secrets Manager)
chmod 600 /opt/oracle/wallet/*
```

### Python example

```python
import json, boto3, oracledb

def get_secret():
    client = boto3.client("secretsmanager")
    return json.loads(client.get_secret_value(SecretId="odb/myapp/credentials")["SecretString"])

secret = get_secret()
pool = oracledb.create_pool(
    user=secret["username"],
    password=secret["password"],
    dsn=f"{secret['host']}:{secret['port']}/{secret['service_name']}",
    config_dir="/opt/oracle/wallet",
    wallet_location="/opt/oracle/wallet",
    wallet_password=secret["wallet_password"],
    min=2, max=10, increment=1,
    tcp_connect_timeout=10,
)
```

### IAM

Instance profile:

```json
{
  "Effect": "Allow",
  "Action": "secretsmanager:GetSecretValue",
  "Resource": "arn:aws:secretsmanager:us-east-1:123456789012:secret:odb/myapp/*"
}
```

### Instant Client (only for thick mode / SQL*Plus)

```bash
sudo dnf install -y oracle-instantclient-release-el9
sudo dnf install -y oracle-instantclient-basic oracle-instantclient-sqlplus
export TNS_ADMIN=/opt/oracle/wallet
sqlplus app_user@mydb_high
```

## ECS / Fargate

`awsvpc` network mode is required for Fargate. Place tasks in the matching AZ.

### Task definition sketch

```json
{
  "family": "odb-app",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "arn:aws:iam::123456789012:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::123456789012:role/ecsTaskRole",
  "containerDefinitions": [
    {
      "name": "app",
      "image": "123456789012.dkr.ecr.us-east-1.amazonaws.com/odb-app:latest",
      "essential": true,
      "secrets": [
        { "name": "DB_SECRET", "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789012:secret:odb/myapp/credentials" }
      ],
      "environment": [ { "name": "WALLET_DIR", "value": "/opt/oracle/wallet" } ],
      "mountPoints": [ { "sourceVolume": "wallet", "containerPath": "/opt/oracle/wallet", "readOnly": true } ]
    },
    {
      "name": "wallet-init",
      "image": "public.ecr.aws/aws-cli/aws-cli:latest",
      "essential": false,
      "command": ["s3", "cp", "s3://odb-wallets/wallet/", "/opt/oracle/wallet/", "--recursive"],
      "__comment": "S3 bucket MUST have SSE-KMS encryption (customer-managed key preferred), versioning enabled, and a bucket policy blocking unencrypted uploads."
      "mountPoints": [ { "sourceVolume": "wallet", "containerPath": "/opt/oracle/wallet" } ]
    }
  ],
  "volumes": [ { "name": "wallet", "host": {} } ]
}
```

### IAM (task role)

```json
{
  "Effect": "Allow",
  "Action": ["secretsmanager:GetSecretValue", "s3:GetObject"],
  "Resource": [
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:odb/myapp/*",
    "arn:aws:s3:::odb-wallets/wallet/*"
  ]
}
```

### Rules

- Pool size 5–20 per task.
- Health check pings the database via `conn.ping()`.
- Fargate cannot domain-join — Kerberos is impractical (use password or OCI IAM token auth).

## Lambda in VPC

### Handler (python-oracledb thin mode + wallet from Secrets Manager)

```python
import json, os, boto3, oracledb, base64, zipfile, io

_conn = None
_wallet_dir = None

def setup_wallet():
    global _wallet_dir
    if _wallet_dir and os.path.exists(f"{_wallet_dir}/cwallet.sso"):
        return _wallet_dir
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=os.environ["WALLET_SECRET"])
    wallet_zip = base64.b64decode(response["SecretBinary"])
    _wallet_dir = "/tmp/wallet"
    os.makedirs(_wallet_dir, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(wallet_zip)) as zf:
        zf.extractall(_wallet_dir)
    return _wallet_dir

def get_secret():
    client = boto3.client("secretsmanager")
    return json.loads(client.get_secret_value(SecretId=os.environ["DB_SECRET"])["SecretString"])

def get_connection():
    global _conn
    if _conn is not None:
        try:
            _conn.ping()
            return _conn
        except Exception:
            _conn = None
    wallet_dir = setup_wallet()
    s = get_secret()
    _conn = oracledb.connect(
        user=s["username"], password=s["password"],
        dsn=f"{s['host']}:{s['port']}/{s['service_name']}",
        config_dir=wallet_dir, wallet_location=wallet_dir,
        wallet_password=s.get("wallet_password"),
        tcp_connect_timeout=10, retry_count=3, retry_delay=1,
    )
    return _conn

def handler(event, context):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT USER FROM DUAL")
        row = cursor.fetchone()
    return {"statusCode": 200, "body": json.dumps({"user": row[0]})}
```

### Environment variables

| Variable | Value |
|---|---|
| `DB_SECRET` | `odb/myapp/credentials` |
| `WALLET_SECRET` | `odb/myapp/wallet` (binary secret holding wallet ZIP) |

### IAM

```json
[
  {
    "Effect": "Allow",
    "Action": "secretsmanager:GetSecretValue",
    "Resource": [
      "arn:aws:secretsmanager:us-east-1:123456789012:secret:odb/myapp/*"
    ]
  },
  {
    "Effect": "Allow",
    "Action": [
      "ec2:CreateNetworkInterface",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DeleteNetworkInterface"
    ],
    "Resource": "*",
    "Condition": {
      "StringEquals": {"aws:RequestedRegion": "us-east-1"}
    }
  }
]
```

These EC2 ENI actions do not support resource-level permissions in IAM, so `Resource: "*"` is required. The `aws:RequestedRegion` condition scopes the permission to the region where the Lambda runs.

### VPC configuration

- Place Lambda in private subnets (matching AZ of the ODB network).
- Add a **Secrets Manager VPC endpoint** so the Lambda does not need a NAT Gateway just for Secrets Manager.
- SG: outbound TCP 1521/2484 to ODB client CIDR; outbound HTTPS 443 for Secrets Manager.

### Rules

- Thin mode only — no Oracle Client layer needed.
- NO connection pool — reuse a single module-level connection across warm invocations.
- Store wallet as Secrets Manager binary secret, extract to `/tmp` on cold start.
- `tcp_connect_timeout=10` to fail fast.
- Cold start: ~2–3s (VPC ENI creation + wallet extract + connection). Consider provisioned concurrency for latency-sensitive endpoints.

### Observability

- Enable VPC Flow Logs on the Lambda's VPC to debug ODB connectivity issues that the application layer cannot see: `aws ec2 create-flow-logs --resource-type VPC --resource-ids <vpc-id> --traffic-type ALL --log-destination-type cloud-watch-logs --log-group-name /aws/vpc/odb-app`.
- Encrypt the CloudWatch log group with a customer-managed KMS key.
- Forward Lambda function logs to CloudWatch with `--logging-config LogFormat=JSON,SystemLogLevel=INFO`.

## EKS with IRSA

### Wallet distribution options

```bash
# Kubernetes Secret
kubectl create secret generic odb-wallet \
  --from-file=cwallet.sso=/path/to/wallet/cwallet.sso \
  --from-file=tnsnames.ora=/path/to/wallet/tnsnames.ora \
  --from-file=sqlnet.ora=/path/to/wallet/sqlnet.ora
```

Or CSI Secrets Store driver:

```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: odb-wallet
spec:
  provider: aws
  parameters:
    objects: |
      - objectName: "odb/myapp/wallet"
        objectType: "secretsmanager"
```

### Pod spec

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: odb-app
spec:
  serviceAccountName: odb-app-sa  # IRSA-enabled
  containers:
    - name: app
      image: 123456789012.dkr.ecr.us-east-1.amazonaws.com/odb-app:latest
      env:
        - { name: WALLET_DIR, value: /opt/oracle/wallet }
        - { name: DB_SECRET, value: odb/myapp/credentials }
      volumeMounts:
        - { name: wallet, mountPath: /opt/oracle/wallet, readOnly: true }
  volumes:
    - name: wallet
      secret: { secretName: odb-wallet }
```

### IRSA

```bash
eksctl create iamserviceaccount \
  --name odb-app-sa --namespace default \
  --cluster <cluster-name> \
  --attach-policy-arn arn:aws:iam::123456789012:policy/ODBSecretsAccess \
  --approve
```

Rules: IRSA (not node instance profile) for Secrets Manager; pool 5–20 per pod; liveness probe should include `conn.ping()`.

## On-Prem Client

Network path: on-prem → DX/VPN → TGW → transit VPC → ODB peering (see **networking-enterprise-hybrid.md** (loaded reference)). On-prem DNS forwards `oraclevcn.com` to a Route 53 Resolver inbound endpoint. On-prem firewalls allow TCP 1521/2484 to the ODB client CIDR.

Python (thin mode) has no native dependencies:

```bash
pip install oracledb
```

Connection pattern identical to EC2 — use the SCAN hostname, wallet for TCPS, Secrets Manager or local secrets backend for credentials.
