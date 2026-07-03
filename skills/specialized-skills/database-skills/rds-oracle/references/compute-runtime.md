# RDS for Oracle — Compute Runtime

Platform patterns for EC2, ECS Fargate, EKS, and Lambda. Pair with `connection-auth.md` + the language reference.

## EC2 pattern

Simplest setup. Instance has an IAM instance profile (not hard-coded creds).

```bash
# Install client (thin mode preferred — no Oracle Client needed)
pip install oracledb      # Python
npm install oracledb      # Node.js
```

Attach an IAM role to the EC2 with:

- `secretsmanager:GetSecretValue` on the RDS credentials secret ARN
- `kms:Decrypt` on the CMK (if customer-managed)

Security group: EC2 SG outbound → RDS SG inbound on 1521.

Test:

```bash
bash scripts/test_connectivity.sh <rds-endpoint> 1521
python3 scripts/test_oracle_connection.py <endpoint> 1521 ORCL dbadmin
```

## ECS Fargate pattern

Fargate tasks run in a VPC. Give the **task execution role** (not the task role) permission to read secrets — the ECS agent uses it to inject them:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["secretsmanager:GetSecretValue", "kms:Decrypt"],
    "Resource": [
      "arn:aws:secretsmanager:<region>:<account>:secret:oracle-creds-*",
      "arn:aws:kms:<region>:<account>:key/<key-id>"
    ]
  }]
}
```

Task definition — inject the username/password as env vars from one secret JSON:

```json
{
  "containerDefinitions": [{
    "name": "app",
    "image": "<repo>/app:1.0",
    "secrets": [
      {
        "name": "DB_USERNAME",
        "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789012:secret:oracle-creds-abc:username::"
      },
      {
        "name": "DB_PASSWORD",
        "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789012:secret:oracle-creds-abc:password::"
      }
    ],
    "environment": [
      { "name": "DB_HOST", "value": "mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com" },
      { "name": "DB_PORT", "value": "1521" },
      { "name": "DB_SERVICE", "value": "ORCL" }
    ]
  }],
  "requiresCompatibilities": ["FARGATE"],
  "networkMode": "awsvpc",
  "executionRoleArn": "arn:aws:iam::123456789012:role/ecs-task-execution-role",
  "taskRoleArn": "arn:aws:iam::123456789012:role/ecs-app-role"
}
```

Task (service) networking:

- Subnets: private subnets in the same VPC as RDS (or peered)
- `assignPublicIp: DISABLED` — pull images via NAT gateway or ECR VPC endpoint
- SG: outbound 1521 to RDS SG; outbound 443 to Secrets Manager (or VPC endpoint)

Pool sizing: total connections = tasks × max pool size per task. Fargate auto-scaling ceiling sets the budget.

## EKS pattern — IRSA + Secrets Store CSI Driver

Recommended: inject secrets via the **AWS Secrets Store CSI Driver** with **IRSA** (IAM Roles for Service Accounts).

### 1. Install the CSI driver + AWS provider

```bash
# CSI driver
helm repo add secrets-store-csi-driver https://kubernetes-sigs.github.io/secrets-store-csi-driver/charts
helm install -n kube-system csi-secrets-store secrets-store-csi-driver/secrets-store-csi-driver

# AWS provider
kubectl apply -f https://raw.githubusercontent.com/aws/secrets-store-csi-driver-provider-aws/main/deployment/aws-provider-installer.yaml
```

### 2. Set up IRSA

```bash
# Ensure OIDC provider is associated
eksctl utils associate-iam-oidc-provider --cluster <cluster-name> --approve

# Create service account with IAM role
eksctl create iamserviceaccount \
  --cluster <cluster-name> \
  --namespace default \
  --name oracle-app-sa \
  --attach-policy-arn arn:aws:iam::<account>:policy/OracleSecretsRead \
  --approve
```

`OracleSecretsRead` policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["secretsmanager:GetSecretValue", "kms:Decrypt"],
    "Resource": [
      "arn:aws:secretsmanager:<region>:<account>:secret:oracle-creds-*",
      "arn:aws:kms:<region>:<account>:key/<key-id>"
    ]
  }]
}
```

### 3. SecretProviderClass

```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: oracle-creds
spec:
  provider: aws
  parameters:
    objects: |
      - objectName: "oracle-creds-abc"
        objectType: "secretsmanager"
        jmesPath:
          - path: "username"
            objectAlias: "db-username"
          - path: "password"
            objectAlias: "db-password"
          - path: "host"
            objectAlias: "db-host"
  secretObjects:
  - secretName: oracle-creds-k8s
    type: Opaque
    data:
    - objectName: db-username
      key: db-username
    - objectName: db-password
      key: db-password
```

### 4. Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: oracle-app
spec:
  replicas: 3
  selector:
    matchLabels: { app: oracle-app }
  template:
    metadata:
      labels: { app: oracle-app }
    spec:
      serviceAccountName: oracle-app-sa
      containers:
      - name: app
        image: <repo>/oracle-app:1.0
        env:
        - name: DB_USERNAME
          valueFrom: { secretKeyRef: { name: oracle-creds-k8s, key: db-username } }
        - name: DB_PASSWORD
          valueFrom: { secretKeyRef: { name: oracle-creds-k8s, key: db-password } }
        volumeMounts:
        - name: secrets
          mountPath: /mnt/secrets
          readOnly: true
      volumes:
      - name: secrets
        csi:
          driver: secrets-store.csi.k8s.io
          readOnly: true
          volumeAttributes:
            secretProviderClass: oracle-creds
```

Security group: pod SG (or node SG if not using pod SGs) outbound 1521 → RDS SG inbound 1521.

**Pool sizing**: total Oracle connections = `replicas × poolMax per pod`. Cap HPA `maxReplicas` with this budget in mind.

## Lambda pattern — VPC + Secrets Manager

Lambda must be configured with VPC, private subnets, and a security group. Each Lambda instance maintains its own pool, so keep `max` small (1-2).

### VPC config

```bash
aws lambda update-function-configuration \
  --function-name oracle-reader \
  --vpc-config SubnetIds=subnet-aaa,subnet-bbb,SecurityGroupIds=sg-lambda-oracle \
  --region us-east-1
```

Lambda SG outbound 1521 → RDS SG inbound 1521. Plus outbound 443 to Secrets Manager (via VPC endpoint or NAT).

### Build the oracledb layer (Python)

```bash
mkdir -p python
pip install -t python/ oracledb
zip -r oracledb-layer.zip python/

aws lambda publish-layer-version \
  --layer-name oracledb \
  --zip-file fileb://oracledb-layer.zip \
  --compatible-runtimes python3.11 python3.12
```

Attach to the function:

```bash
aws lambda update-function-configuration \
  --function-name oracle-reader \
  --layers arn:aws:lambda:us-east-1:<account>:layer:oracledb:1
```

### Handler — pool at module scope

```python
import json, os, boto3, oracledb

_secret = json.loads(
    boto3.client("secretsmanager").get_secret_value(
        SecretId=os.environ["SECRET_NAME"]
    )["SecretString"]
)
_pool = oracledb.create_pool(
    user=_secret["username"],
    password=_secret["password"],
    dsn=f'{_secret["host"]}:{_secret["port"]}/{_secret["dbname"]}',
    min=1, max=2,
)

def handler(event, context):
    with _pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute("SELECT sysdate FROM dual")
        return {"result": str(cur.fetchone())}
```

Module-scope init is reused across warm invocations. Each cold start pays the pool-init cost once.

### Cold-start optimization

- **Thin mode** — no native library load, faster init (python-oracledb 6+ default).
- **Smaller deployment package** — drop test data, docs, unused dependencies.
- **Provisioned concurrency** for latency-sensitive workloads — keeps N instances warm.
- **VPC endpoint for Secrets Manager** — avoids NAT gateway DNS round-trip.
- **Keep memory ≤ 1 GB** unless you need more — higher memory = faster but more cost.

### Total-connection budget

Total RDS connections from Lambda = concurrent invocations × `max` pool size. Monitor via CloudWatch `DatabaseConnections`. Cap with Lambda reserved concurrency if needed.

## RDS Proxy — not supported

**RDS Proxy does not support Oracle.** For Oracle connection multiplexing, use Oracle CMAN on EC2 — see `cman-proxy.md`.

## SSM for developer access

See `ssm-tunneling.md` for connecting laptop tools (SQL Developer, Toad, sqlplus) to a private RDS Oracle via SSM port forwarding.
