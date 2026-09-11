# Action Safety Guide

## Neptune Analytics — Tagging Contract (MANDATORY)

Every Neptune Analytics graph created by this skill MUST carry these tags:

- `created_by=neptune-skill`
- `generation_model=<model-id>` (e.g., `claude-sonnet-4-5`)

**Always issue tags in TWO steps.** Inline `--tags` on `create-graph` is unreliable through some MCP serialization paths — do NOT rely on it as the sole tagging mechanism.

### Step 1: Create the graph (inline tags as best-effort)

Default to `--deletion-protection`. Use `--no-deletion-protection` ONLY for
ephemeral/CI graphs that an automated harness must tear down.

```bash
aws neptune-graph create-graph \
  --graph-name <name> \
  --provisioned-memory 128 \
  --deletion-protection \
  --tags created_by=neptune-skill,generation_model=<model-id> \
  --region us-east-1
```

### Step 2: Tag explicitly via `tag-resource` (REQUIRED)
The CreateGraph response includes the graph ARN. Pass it to `tag-resource`.
A graph still in `CREATING` may reject the call, so use a SHORT bounded retry
(a few attempts, a few seconds apart) rather than polling for `AVAILABLE` —
long AVAILABLE-polling times out the MCP connection and some harness tasks
explicitly forbid it.

```bash
aws neptune-graph tag-resource \
  --resource-arn <graph-arn-from-create-response> \
  --tags created_by=neptune-skill,generation_model=<model-id> \
  --region us-east-1
```

This second call is what the validator's `list_tags_for_resource` check relies on. The eval framework will fail any test that omits it. Apply this two-step pattern to every Neptune Analytics creation call — `create-graph`, `create-graph-using-import-task`, `create-graph-snapshot`, private endpoints.

Neptune Database uses a DIFFERENT tagging API — do not use `neptune-graph tag-resource` against a Database ARN:

```bash
# Neptune Analytics resources
aws neptune-graph tag-resource --resource-arn <graph-arn> --tags created_by=neptune-skill,generation_model=<model-id>

# Neptune Database resources (create-db-cluster, create-db-instance)
aws neptune add-tags-to-resource --resource-name <cluster-or-instance-arn> \
  --tags Key=created_by,Value=neptune-skill Key=generation_model,Value=<model-id>
```

---

Safety semantics for destructive and high-impact Neptune operations. Every action
that can cause data loss, downtime, or irreversible changes must follow these safeguards.

## Safety Levels

| Risk Level | Definition | Required Safeguards |
|---|---|---|
| High | Data loss or significant downtime likely. Irreversible. | Explicit user confirmation. Snapshot/export. Impact explanation. |
| Medium | Possible disruption or partial impact. May be reversible. | User confirmation. Recommend snapshot. Explain impact. |
| Low | Minimal risk. Fully reversible or non-destructive. | Inform the user. Proceed with standard confirmation. |

## High Risk Actions

**The agent does NOT execute anything in this section.** SKILL.md lists these
operations under "Do NOT execute" — the agent refuses, explains why, and
redirects to the user's change-control process or the AWS Console. The commands
below document what the USER runs themselves, and the safeguards the agent
should walk them through first.

### Delete Neptune Database Cluster

**Reversibility:** Irreversible. All data permanently deleted unless final snapshot taken.

**Required safeguards:**

1. Always suggest a final snapshot before deletion.
2. Require explicit user confirmation with the cluster identifier.
3. Warn that all data, endpoints, and connections will be destroyed.
4. Confirm the cluster is not referenced by active applications.

```bash
# Step 1: Create final snapshot
aws neptune create-db-cluster-snapshot \
  --db-cluster-identifier my-cluster \
  --db-cluster-snapshot-identifier my-cluster-final-$(date +%Y%m%d) \
  --tags Key=created_by,Value=neptune-skill Key=generation_model,Value=<model-id>

# Step 2: Wait for snapshot to complete
aws neptune wait db-cluster-snapshot-available \
  --db-cluster-snapshot-identifier my-cluster-final-<date>

# Step 3: Delete only after snapshot is available
aws neptune delete-db-cluster \
  --db-cluster-identifier my-cluster \
  --skip-final-snapshot  # Only if snapshot already taken above
```

### Delete Neptune Analytics Graph

**Reversibility:** Irreversible. All in-memory data lost immediately.

**Required safeguards:**

1. Warn that Neptune Analytics is ephemeral — data cannot be recovered.
2. Suggest exporting results to S3 before deletion.
3. Require explicit user confirmation with the graph identifier.

```bash
aws neptune-graph delete-graph --graph-identifier g-xxxxxxxxxx
```

### Drop All Vertices/Edges (g.V().drop() / g.E().drop())

**Reversibility:** Irreversible. All graph data permanently deleted.

**Required safeguards:**

1. Warn about complete data loss.
2. Suggest taking a cluster snapshot before dropping.
3. Require explicit user confirmation.
4. Confirm this is intentional and not a targeted delete scenario.

## Medium Risk Actions

### Modify Cluster (Instance Class, Engine Version)

**Reversibility:** Varies. Instance class changes are reversible; major engine upgrades are not.

**Required safeguards:**

1. Flag that modification may cause brief failover.
2. Recommend applying during maintenance window for production.
3. Create snapshot before major engine version upgrades.
4. For engine upgrades, check client library compatibility.

### Enable/Disable IAM Authentication

**Reversibility:** Reversible, but may disconnect active clients.

**Required safeguards:**

1. Warn that enabling IAM auth requires all clients to sign requests with SigV4.
2. Warn that disabling IAM auth on a public-endpoint cluster removes authentication.
3. Recommend testing in non-production first.

### Enable/Disable Public Endpoints

**Reversibility:** Reversible.

**Required safeguards:**

1. Warn that public endpoints expose the cluster to internet traffic.
2. Confirm IAM auth is enabled (required for public endpoints).
3. Recommend restricting security group inbound rules to specific IPs.

### Scale Down (Instance Class or Reader Replicas)

**Reversibility:** Reversible (scale back up).

**Required safeguards:**

1. Verify remaining capacity handles current data size and query load.
2. Warn about brief failover during instance class change.
3. Check BufferCacheHitRatio — scaling down may push working set out of memory.

## Low Risk Actions

### Create Snapshot — Low risk. No impact on running cluster.
### Describe/List Operations — Read-only. No state change. No safeguards needed.
### Add Read Replicas — Reversible. Brief sync impact on primary for large graphs.
### Modify Tags — Fully reversible. May affect cost allocation and IAM tag policies.

## Never-Auto-Execute List

The agent MUST NEVER execute these, in any context or automation. This list is
the superset of SKILL.md's "Do NOT execute" section — the two must stay in sync.

Mirrors SKILL.md's refuse list:

- Delete cluster / instance / graph — `delete-db-cluster`, `delete-db-instance`, `delete-graph`
- Reset Analytics graph data — `reset-graph`
- Failover — `failover-db-cluster`
- Major engine version upgrade — `modify-db-cluster --engine-version` across majors
- Reboot — `reboot-db-instance`, `reboot-db-cluster`
- Cancel long-running work — `cancel-import-task`, `cancel-export-task`

Additionally never auto-execute:

- `g.V().drop()` or `g.E().drop()` (full data wipe)
- Snapshot deletion (especially the last/only snapshot)
- IAM auth toggle on production clusters
- Public endpoint toggle on production clusters
- Security group rule removal
- Migration cutover execution
