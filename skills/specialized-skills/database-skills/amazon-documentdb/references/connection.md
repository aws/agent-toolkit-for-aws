# DocumentDB — Connection and Cluster Setup

Workflow for reaching a working DocumentDB connection. Two entry points:

- **A. New cluster** — no cluster yet, create with serverless defaults
- **B. Existing cluster** — can't connect, need driver config, or want TLS/VPC diagnosis

Ask one question to route: "Do you already have a DocumentDB cluster, or are we starting from scratch?"

## What to ask upfront

- New cluster: cluster id, master password (or use Secrets Manager), region, where the app runs (same VPC / local dev / different VPC)
- Existing cluster: cluster id, region, the error message
- Programming language (Python, Node, Java, Go, C#, Ruby)

**Recommend serverless on 8.0** (`db.serverless`) — auto-scales, costs up to 90% less when idle, and supports all 8.0 features (`$vectorSearch`, Zstd compression). Suggest a fixed instance class only for sustained 24/7 high throughput. Never recommend Elastic Clusters (a separate sharding product lacking transactions, change streams, and many operators).

## Workflow — Entry Point A (new cluster)

### Step 1: Launch everything in parallel

DocumentDB instance creation takes ~7 minutes. **Do not create resources sequentially** — run these three tracks at the same time.

**Track A — DocumentDB cluster + instance.** You MUST run these exact commands — serverless is mandatory unless the user said "provisioned" or "instance-based":

```bash
aws docdb create-db-cluster \
  --db-cluster-identifier <cluster_id> \
  --engine docdb \
  --engine-version 8.0.0 \
  --serverless-v2-scaling-configuration MinCapacity=1,MaxCapacity=16 \
  --master-username adminuser \
  --master-user-password '<password>' \
  --region <region>

aws docdb create-db-instance \
  --db-instance-identifier <cluster_id>-instance \
  --db-instance-class db.serverless \
  --engine docdb \
  --db-cluster-identifier <cluster_id> \
  --region <region>
```

Do NOT substitute `db.t3.medium`, `db.r5.large`, or any other instance class — `db.serverless` is the only correct value here.

For production, prefer `--manage-master-user-password` over the inline `--master-user-password` shown above — DocumentDB generates the password into Secrets Manager with rotation (the two flags are mutually exclusive). Retrieve it via `aws secretsmanager get-secret-value --secret-id <MasterUserSecret-arn>` when building the connection string in Step 3.

**Track B — Access from outside the VPC** (local dev or admin access — pick one option):

**Option 1 (preferred): SSM Session Manager port forwarding** — no SSH key, IAM-controlled.

Prerequisites: SSM Agent on EC2 (pre-installed on AL2023), IAM role with `AmazonSSMManagedInstanceCore`, Session Manager plugin installed locally.

```bash
INSTANCE_ID=$(aws ec2 run-instances \
  --image-id resolve:ssm:/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
  --instance-type t3.micro --iam-instance-profile Name=SSMInstanceProfile \
  --subnet-id <any-subnet-in-docdb-vpc> --no-associate-public-ip-address \
  --region <region> --query 'Instances[0].InstanceId' --output text)

aws ssm start-session --target $INSTANCE_ID \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["<docdb-cluster-endpoint>"],"portNumber":["27017"],"localPortNumber":["27017"]}' \
  --region <region>
```

Add inbound TCP 27017 on DocumentDB SG from the bastion's SG.

**Option 2 (fallback): SSH bastion + tunnel** — use when SSM is not available.

Launch a t3.micro in a public subnet with a key pair and SG allowing SSH from your IP only. Add inbound TCP 27017 on DocumentDB SG from the bastion SG.

**Track C — Download TLS cert:** `curl -s https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o global-bundle.pem`

### Step 2: Poll the DocumentDB instance until available

Don't use `aws docdb wait` — not present in all CLI versions. Use a polling loop:

```bash
for i in $(seq 1 20); do
  STATUS=$(aws docdb describe-db-instances --db-instance-identifier <id>-instance \
    --query 'DBInstances[0].DBInstanceStatus' --output text --region <region>)
  [ "$STATUS" = "available" ] && break
  sleep 30
done
```

### Step 3: Build the connection string

All five parameters are required — DocumentDB rejects or behaves incorrectly without them:

```
mongodb://adminuser:<password>@<endpoint>:27017/?tls=true&tlsCAFile=global-bundle.pem&replicaSet=rs0&readPreference=secondaryPreferred&retryWrites=false
```

| Param | Why |
|---|---|
| `tls=true` + `tlsCAFile` | TLS is required; absent → connection refused |
| `replicaSet=rs0` | Without this, the driver connects to one node only |
| `retryWrites=false` | DocumentDB does not support retryable writes |
| `readPreference=secondaryPreferred` | Distributes reads to replicas |

The string above uses the **primary (master) user**, which is always password-based.

**IAM authentication is also supported** for application / non-admin users (not the primary user) on cluster version 5.0+. It is password-less — connections use short-lived STS tokens — suiting Lambda/ECS/EC2 workloads that run with an IAM role. Trade-offs: requires instance-based 5.0+, a `MONGODB-AWS`-capable driver (`pip install 'pymongo[aws]'`; Node.js ≥ 6.13.1), and an STS dependency at connect time (watch STS throttling at high connection rates).

Create an IAM-backed user as the master user in the `$external` database, then connect with `authSource=$external&authMechanism=MONGODB-AWS` (no credentials in the URI — the driver fetches them from the attached role):

```javascript
use $external;
db.createUser({ user: "arn:aws:iam::<account-id>:role/<app-role>",
  mechanisms: ["MONGODB-AWS"], roles: [ { role: "readWrite", db: "<app-db>" } ] });
```

```
mongodb://<endpoint>:27017/?tls=true&tlsCAFile=global-bundle.pem&replicaSet=rs0&readPreference=secondaryPreferred&retryWrites=false&authSource=%24external&authMechanism=MONGODB-AWS
```

### Step 4: Connect from outside the VPC (local dev only)

**If using SSM (Option 1):** the `aws ssm start-session` command in Track B already establishes the port-forward tunnel. No separate SSH step needed. Connect directly:

```bash
mongosh --tls --tlsAllowInvalidHostnames --tlsCAFile global-bundle.pem \
  --host 127.0.0.1 --port 27017 --username adminuser --password '<pw>' \
  --eval "db.runCommand({ping:1})"
```

**If using SSH bastion (Option 2):** wait 15 seconds after the bastion is running (sshd needs to start), then:

```bash
ssh -i <key-pair-name>.pem \
  -L 27017:<cluster-endpoint>:27017 \
  -o StrictHostKeyChecking=no -o ServerAliveInterval=30 \
  ec2-user@<bastion-public-ip> -N -f
```

Then connect the same way — mongosh needs `--tlsAllowInvalidHostnames` because the hostname resolves to `127.0.0.1`, not the cluster endpoint.

Expected: `{ ok: 1 }`.

### Step 5: Return a ready-to-use driver snippet

Read `references/connection-drivers.md` and substitute the actual endpoint, password, and database name.

## Workflow — Entry Point B (existing cluster)

### Diagnostic commands (always run first)

```bash
aws docdb describe-db-clusters --db-cluster-identifier <name> \
  --query 'DBClusters[*].[DBClusterIdentifier,Endpoint,Port]' --region <region>

aws docdb describe-db-instances --db-instance-identifier <instance-name> \
  --query 'DBInstances[*].DBSubnetGroup.VpcId' --region <region>

nc -zv <cluster-endpoint> 27017
```

### Match the error and apply the fix

| Error | Fix |
|---|---|
| `connection refused`, timeout after 5000ms | SG missing inbound TCP 27017. Add rule from app SG; if outside VPC, set up tunnel |
| `SSL handshake failed`, `certificate verify failed` | Download RDS bundle; verify `tlsCAFile` path |
| `not master` / `not primary` | Add `replicaSet=rs0` to the connection string |
| `Server selection timed out after 30000ms` | Bad cert path or unreachable endpoint — re-run `nc -zv` |
| `getaddrinfo failed` | Wrong endpoint — run `describe-db-clusters` to get the correct one |
| Intermittent write errors under load | Add `retryWrites=false` |

### VPC checklist

- EC2/Lambda and DocumentDB in the **same region** and **same VPC** (or VPC peering)
- DocumentDB SG inbound TCP 27017 from the app SG (preferred) or from a specific IP
- Never open to `0.0.0.0/0`

```bash
aws ec2 authorize-security-group-ingress \
  --group-id <docdb-sg> --protocol tcp --port 27017 \
  --source-group <app-sg> --region <region>
```

### TLS verification

Check the `tls` parameter in the cluster's parameter group (`enabled` default, `disabled`, or `fips-140-3`).

## Serverless constraints

- **Supported on engine 5.0.0 and 8.0.0** — not 3.6 or 4.0
- Supported with Global Clusters
- DCU scaling in 0.5 increments via `MinCapacity` / `MaxCapacity`
- Verify regional availability: `aws docdb describe-orderable-db-instance-options --region <r> --db-instance-class db.serverless --engine docdb`

For driver snippets (Python, Node, Java, Go, C#, Ruby, mongosh), see `references/connection-drivers.md`.
