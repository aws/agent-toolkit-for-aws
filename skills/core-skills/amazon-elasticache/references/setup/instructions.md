# Setup & Connect

Create ElastiCache caches and connect applications to them.

## Loading

Read this file first. Load files referenced in the workflow steps on demand.

## Check for existing context

Before starting, read `.elasticache/requirements.json` if it exists. Use the values (engine, region, compute, use case, deployment model) as inputs rather than re-asking. If the file doesn't exist and the user skipped requirements, gather the minimum needed: engine (default Valkey), region, VPC, and subnets.

## Preflight (run before any provisioning)

Before creating or modifying anything, verify the execution path works:

1. **Credentials check (primary):** Run `aws sts get-caller-identity`. If it works, use AWS CLI, boto3 SDK, CloudFormation, and the bundled scripts for all control-plane operations.
2. **If credentials fail:** Stop. Tell the user to configure AWS CLI credentials (`aws configure`).
3. **Region:** Confirm region is set (from `.elasticache/requirements.json`, workspace scan, or ask the user).
4. **Permissions:** Run a read-only call to confirm the caller has ElastiCache access. Try `aws elasticache describe-serverless-caches --region <region>` first. If that fails with AccessDenied (the caller may only have node-based permissions), fall back to `aws elasticache describe-replication-groups --region <region>`. Either succeeding confirms ElastiCache access.

If all checks pass, proceed. If any fail, surface the specific error and suggest a fix before continuing.

## Workflow

1. **Select engine** -- skip if already set in `.elasticache/requirements.json`. Default Valkey. See `references/setup/engine-selection.md`.
2. **Select deployment model** -- skip if already set in JSON. Default serverless. See `references/setup/serverless-vs-node.md`.
3. **Estimate cost** -- skip if requirements already ran it. Run `scripts/price_calculator.py --mode serverless --data-gb <N> --ops-per-sec <N>` and `--mode node --node-type <type> --nodes <N> --show-ri-options`.
4. **Create the cache and set up auth** -- see `references/setup/create-secure-cache.md`. Covers provisioning, RBAC, tunnel setup, and restore. AWS CLI/SDK and bundled scripts are the primary path. For auth model decision: see `references/setup/auth-model-selector.md`.
5. **Generate IAM policies** -- see `references/setup/iam-policies.md` for which permissions the caller/app needs.
6. **Validate connectivity** -- run `scripts/test_connection.py <cache-endpoint>`. See `references/setup/connection-guide.md` for TLS gotchas, endpoint formats, and tunnel mode.
   For local development access, use the tunnel scripts:
   - `python3 scripts/find_tunnel_host.py --vpc-id <vpc-id> --region <region>` to locate an SSM-managed instance
   - `python3 scripts/start_tunnel.py --instance-id <id> --cache-host <endpoint> --region <region>` to start the tunnel
7. **Verify security posture** -- run `python3 scripts/security_audit.py --serverless <cache-name>` (or `--replication-group <replication-group-id>`) to verify encryption, auth, network, and backup settings meet best practices.
8. **Emit IaC** -- optional. See `references/setup/iac-reference.md`.

## After provisioning

### Update requirements artifact (single source of truth)

After the cache is created and connectivity is validated, update `.elasticache/requirements.json`. Setup owns the `infrastructure` section and top-level infra fields. Read the existing file first, merge your updates, then write it back. Do not overwrite fields owned by requirements (use_case, patterns, runtime, data_source, etc.).

Update these top-level fields:

- `deployment_model`: "serverless" or "node-based"
- `vpc_id`, `subnet_ids`, `security_group_ids`

Add or update the `infrastructure` section:

```json
{
  "infrastructure": {
    "cache_name": "myapp-cache",
    "resource_id": "myapp-cache",
    "engine_version": "9.0",
    "topology": null,
    "endpoint": "myapp-cache.serverless.use1.cache.amazonaws.com",
    "port": 6379,
    "reader_port": 6380,
    "auth_model": "iam",
    "tls": true,
    "client_library": "valkey-py",
    "execution_path": "cli",
    "access_mode": "tunnel",
    "tunnel_instance_id": "i-0abc123def456",
    "embedding_provider": null,
    "embedding_model": null,
    "embedding_dim": null,
    "embedding_module": null
  }
}
```

For node-based, `topology` should be: `{ "shards": <n>, "replicas_per_shard": <n> }`. For serverless, use `null`.

`access_mode` is `"tunnel"` (local dev via SSM) or `"direct"` (app runs in VPC). When `access_mode` is `"tunnel"`, proactively start the tunnel before any cache operation instead of waiting for connection failure.

`embedding_provider`, `embedding_model`, `embedding_dim`, and `embedding_module` are set by the genai sub-skill when the user chooses an embedding provider. Examples: `"bedrock"` / `"amazon.titan-embed-text-v2:0"` / `1024` / `"utils/embeddings.py"`. These are `null` until the user works with vector search. Once set, all sub-skills import from `embedding_module` instead of re-asking or regenerating embedding code.

The genai sub-skill also owns a `genai` section:

```json
{
  "genai": {
    "mode": "2",
    "mode_2_path": "server-side",
    "framework": "mem0"
  }
}
```

`mode` is `"1"`, `"2"`, or `"3"` (plain cache, semantic response cache, full vector search). **Important:** Modes 2 (server-side path) and 3 require Valkey 8.2+ on node-based clusters for vector search (FT.CREATE/FT.SEARCH). Serverless does not support vector search. If the user selects mode 2 or 3, verify the engine version supports it before provisioning. `mode_2_path` is `"app-side"` or `"server-side"` (only set when mode is `"2"`). `framework` is the user's chosen framework (`"strands"`, `"mem0"`, `"langchain"`, or `null` for raw client). These are `null` until the user works with genai patterns. Once set, the genai sub-skill skips routing questions on return visits.

## Scaffold Missing Files

When the user's workspace does not contain expected files (e.g., no `requirements.txt`, no `utils/` directory, no `.elasticache/` folder), generate them rather than refusing. The skill should be able to bootstrap a project from scratch:

- If `.elasticache/requirements.json` does not exist, create it with defaults after gathering minimum inputs. If the project has a `.gitignore`, add `.elasticache/` to it. The file may contain VPC IDs, subnet IDs, and endpoint URLs that should not be committed to source control.
- If the user's project has no dependency file (`requirements.txt`, `package.json`, etc.), create one with the needed client library (`valkey`, `redis`, `ioredis`, `lettuce`, etc.).
- If a utility file referenced by `infrastructure.embedding_module` does not exist yet, generate it when the user first works with embeddings.
- If the user asks for working code but has an empty project directory, scaffold the minimum structure: connection utility, main application file, and dependency file. Do not require pre-existing project structure.

## Additional references

These files are not part of the main workflow but load on demand when the situation requires them:

- `references/shared-ux/production-readiness.md` -- when the user asks "is my cache ready for production?" or wants a pre-production gate checklist
- `references/setup/connectivity-diagnostics.md` -- when connection validation fails
- `references/setup/iac-best-practices.md` -- when the user asks about CloudFormation, Terraform, CDK, IaC deployment issues, stack failures, or deploying multiple caches
- `references/setup/cluster-topology.md` -- when configuring node-based cluster mode, shard count, replica count, or subnet IP planning
- `references/setup/service-quotas.md` -- when the user asks about quotas, limits, capacity errors ("maximum number of nodes"), or how to request a limit increase
- `references/shared-foundation/attribution.md` -- when generating CLI commands, SDK code, or IaC
- `references/shared-runtime/lambda.md` -- when connecting from Lambda (cold start, IAM auth, lazy init)
- `references/shared-runtime/ecs.md` -- when connecting from ECS (SIGTERM, task definition, pool drain)
- `references/shared-runtime/eks.md` -- when connecting from EKS (IRSA, service mesh, SecurityGroupPolicy)
- `references/shared-runtime/rds-acceleration.md` -- when caching RDS/Aurora queries (thundering herd, invalidation)
- `references/shared-security/encryption-defaults.md` -- when adding encryption to an existing unencrypted cluster

## Freshness disclaimer

When your response includes pricing, version constraints, or feature availability, include the freshness disclaimer per SKILL.md Global Rule #5: "For current pricing see https://aws.amazon.com/elasticache/pricing/. For current feature availability see https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/."
