# Connectivity Diagnostics for ElastiCache

Decision-tree diagnostic for "I can't connect to my cache." Work through steps in order; fix at the step where it fails.

## Step 0: Are You in the VPC?

ElastiCache has no public endpoints. Determine where the client runs before diagnosing.

| Client location | Action |
|----------------|--------|
| EC2/Lambda/ECS/EKS in same VPC | Proceed to Step 1 |
| EC2 in different VPC | Verify peering/transit gateway routes, then Step 1 |
| Local laptop / CI runner | Set up SSM tunnel first, then diagnose against `127.0.0.1` with `--tunnel-mode` |

Tunnel setup:

```bash
python3 scripts/find_tunnel_host.py --vpc-id <vpc-id> --region <region>
python3 scripts/start_tunnel.py --instance-id <id> --cache-host <endpoint> --region <region>
python3 scripts/test_connection.py 127.0.0.1 --port 6379 --tunnel-mode --server-name <endpoint>
```

If tunnel fails: check SSM agent status, `AmazonSSMManagedInstanceCore` policy, and routes to SSM endpoints (NAT or VPC endpoints for `ssm`, `ssmmessages`, `ec2messages`).

## Step 1: DNS Resolution

Retrieve the correct endpoint:

```bash
# Serverless
aws elasticache describe-serverless-caches --serverless-cache-name <name> \
  --query 'ServerlessCaches[0].Endpoint'

# Node-based (cluster-mode enabled) -- uses ConfigurationEndpoint
aws elasticache describe-replication-groups --replication-group-id <name> \
  --query 'ReplicationGroups[0].ConfigurationEndpoint'

# Node-based (cluster-mode disabled) -- uses NodeGroups[0].PrimaryEndpoint
aws elasticache describe-replication-groups --replication-group-id <name> \
  --query 'ReplicationGroups[0].NodeGroups[0].PrimaryEndpoint'
```

Note: `ConfigurationEndpoint` is null for cluster-mode-disabled clusters. Use `PrimaryEndpoint` and `ReaderEndpoint` from `NodeGroups[0]` instead.

Common mistakes:

* Using `ConfigurationEndpoint` for cluster-mode-disabled clusters (it will be null)
* Using a node endpoint instead of the configuration endpoint for cluster-mode-enabled caches
* Including the port in the hostname (`endpoint:6379` instead of just `endpoint`)

If DNS times out: verify VPC has `enableDnsSupport` and `enableDnsHostnames` set to `true`.

## Step 2: TCP / Port Reachability

**Serverless caches need both ports open**: 6379 (primary) AND 6380 (reader) in the security group.

Find the cache's security group:

```bash
aws elasticache describe-serverless-caches \
  --serverless-cache-name <name> \
  --query 'ServerlessCaches[0].SecurityGroupIds'
```

Failure causes:

* **Timeout**: security group inbound rule missing for TCP 6379 (and 6380 for serverless) from client's SG or CIDR
* **Refused**: cache not in `available` status, or wrong port
* **Lambda**: must have VPC attachment. Verify with `aws lambda get-function-configuration --function-name <name> --query 'VpcConfig'`

## Step 3: TLS Handshake

Serverless always requires TLS. Node-based requires TLS only if created with `--transit-encryption-enabled`, or if TLS was enabled later via the preferred→required migration path (available for Redis OSS 7.0+/Valkey 7.2+).

ElastiCache-specific failures:

| Symptom | Cause | Fix |
|---------|-------|-----|
| "wrong version number" on serverless | Client connecting without TLS | Set `ssl=True` / `tls: {}` in client |
| "wrong version number" on node-based | Cache created without TLS, client sending TLS | For Redis OSS 7.0+/Valkey 7.2+, enable TLS on existing cluster via `modify-replication-group` with `--transit-encryption-enabled` and `--transit-encryption-mode preferred`, then `required`. For older versions, recreate cache with TLS. |
| Hostname mismatch through tunnel | Cert is for `*.cache.amazonaws.com`, not `127.0.0.1` | `ssl_check_hostname=False` (Python), `checkServerIdentity: () => undefined` (Node), `--insecure` (CLI) |
| Verify code 20 | Missing Amazon Trust Services root CA | Update system CA bundle |

## Step 4: Authentication

Test with CLI:

```bash
# RBAC with password
valkey-cli -h <endpoint> -p 6379 --tls --user <username> --pass <password> PING

# IAM auth -- generate token via Python (no CLI equivalent exists)
# python3 -c "
# import boto3; from botocore.signers import RequestSigner; from botocore.model import ServiceId
# s = boto3.Session(); c = s.get_credentials().get_frozen_credentials()
# sr = RequestSigner(ServiceId('elasticache'), '<region>', 'elasticache', 'v4', c, s._session.get_component('event_emitter'))
# For serverless caches, add ResourceType=ServerlessCache:
# url = sr.generate_presigned_url({'method':'GET','url':'https://<endpoint>/?Action=connect&User=<user-id>&ResourceType=ServerlessCache','body':{},'headers':{},'context':{}}, operation_name='connect', expires_in=900, region_name='<region>')
# For node-based caches, omit ResourceType:
# url = sr.generate_presigned_url({'method':'GET','url':'https://<endpoint>/?Action=connect&User=<user-id>','body':{},'headers':{},'context':{}}, operation_name='connect', expires_in=900, region_name='<region>')
# print(url[len('https://'):])
# "
# Then pass the output as TOKEN:
valkey-cli -h <endpoint> -p 6379 --tls --user <user-id> --pass "$TOKEN" PING
```

ElastiCache-specific auth failures:

| Error | Cause | Fix |
|-------|-------|-----|
| `NOAUTH Authentication required` | Client not sending credentials | Configure username/password in client connection params |
| `WRONGPASS` (RBAC) | Wrong password or user not in cache's user group | Verify user is in the user group linked to the cache |
| `ERR AUTH invalid-iam-credentials` | Expired token (15 min validity) | Regenerate immediately before connecting |
| `ERR AUTH invalid-iam-credentials` | Missing `elasticache:Connect` on both cache AND user ARNs | Add permission on both resource ARNs |
| `ERR AUTH invalid-iam-credentials` | `--user-id` in token generation doesn't match AUTH username | Must be identical |
| `WRONGPASS` (user disabled) | Access string starts with `off` | Change to `on` via `modify-user` |

IAM permission check:

```bash
aws iam simulate-principal-policy --policy-source-arn <role-arn> \
  --action-names elasticache:Connect \
  --resource-arns \
    arn:aws:elasticache:<region>:<account>:serverlesscache:<cache-name> \
    arn:aws:elasticache:<region>:<account>:user:<user-id>
```

## Step 5: Command Permissions (RBAC ACL)

| Error | Cause | Fix |
|-------|-------|-----|
| `NOPERM ... run the 'set' command` | Access string missing command category | Add `+@write` or specific `+set` |
| `NOPERM No permissions to access a key` | Key doesn't match allowed pattern | Update access string pattern or fix app key prefix |
| `NOPERM` on pub/sub | Missing channel permissions | Add `&*` (all channels) or `&prefix:*` |

Commands requiring special categories:

| Command | Required | Notes |
|---------|----------|-------|
| SUBSCRIBE, PUBLISH | `+@pubsub` + channel pattern (`&*`) | |
| EVAL, EVALSHA | `+@scripting` | |
| MULTI, EXEC | `+@transaction` | **IAM re-auth (AUTH/HELLO) cannot be used inside MULTI/EXEC blocks** |

Access string changes take effect on new connections only. Existing connections retain old permissions until reconnect.
