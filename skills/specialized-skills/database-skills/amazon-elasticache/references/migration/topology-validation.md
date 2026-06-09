# Topology Validation

**When to use:** Before executing a migration, validate source/target topology compatibility: AZ configuration, cross-region constraints, subnet groups, security group ports.

Before executing a migration, validate that the source and target topologies are compatible. Mismatches in availability zones, subnets, or security groups are common causes of migration failure or degraded availability post-cutover.

## Single-AZ to Multi-AZ (and Vice Versa)

**Single-AZ source migrating to Multi-AZ target:**

* This is a common and recommended upgrade path (improves availability).
* Verify that the target VPC has subnets in at least two Availability Zones.
* The target subnet group must include subnets in multiple AZs.
* Check: `aws ec2 describe-subnets --filters "Name=vpc-id,Values=<vpc-id>" --query "Subnets[*].{SubnetId:SubnetId,AZ:AvailabilityZone}"` to confirm AZ coverage.

**Multi-AZ source migrating to Single-AZ target:**

* This is a downgrade in availability. The skill must warn the user that automatic failover will not be available and a node failure will cause downtime.
* Confirm the user explicitly accepts the reduced availability before proceeding.

**Detection commands:**

```bash
# Check source topology (if ElastiCache)
aws elasticache describe-replication-groups \
  --replication-group-id <source-cluster> \
  --query "ReplicationGroups[0].{MultiAZ:MultiAZ,AutoFailover:AutomaticFailover,NodeGroups:NodeGroups[*].NodeGroupMembers[*].PreferredAvailabilityZone}" \
  --region <region>

# Check target subnet group AZ coverage
aws elasticache describe-cache-subnet-groups \
  --cache-subnet-group-name <subnet-group> \
  --query "CacheSubnetGroups[0].Subnets[*].SubnetAvailabilityZone.Name" \
  --region <region>
```

### Cross-Region Replication Constraints

* ElastiCache does not support direct cross-region migration via `start-migration` or `test-migration`.
* For cross-region moves, use snapshot-based migration: export a snapshot to S3 in the source region, copy the RDB file to an S3 bucket in the target region, then restore from the S3 object in the target region.
* Global Datastore is available for ongoing cross-region replication but requires node-based clusters (not serverless).

**Online migration (`start-migration`/`test-migration`) prerequisites for the source:**

* The source Redis must NOT have AUTH enabled.
* The source must have `protected-mode` set to `no`.
* The source must update `bind` to allow inbound connections from ElastiCache nodes.
* The source must not have any renamed commands (e.g., via `rename-command` in redis.conf). ElastiCache uses standard commands during replication.
* The source must be listening on the same port as the target ElastiCache cluster (default 6379).
* The number of logical databases must match between source and target.

**Online migration (`start-migration`/`test-migration`) prerequisites for the target:**

* The target ElastiCache deployment must NOT have encryption in-transit enabled.
* The target must have Multi-AZ enabled.
* The target must be running Valkey 7.2+, or Redis OSS 5.0.6 or higher.
* The target must NOT be part of a Global Datastore.
* The target must have data tiering disabled.

**Cross-region snapshot migration** (three-step process):

Step 1: Export snapshot to S3 in the source region (the S3 bucket must be in the same region as the snapshot):

```bash
aws elasticache copy-snapshot \
  --source-snapshot-name <snapshot-name> \
  --target-snapshot-name <snapshot-name>-export \
  --target-bucket <s3-bucket-in-source-region> \
  --region <source-region>
```

Step 2: Copy the RDB file to an S3 bucket in the target region:

```bash
aws s3 cp s3://<s3-bucket-in-source-region>/<snapshot-name>-export-0001.rdb \
  s3://<s3-bucket-in-target-region>/<snapshot-name>-export-0001.rdb
```

Step 3: Restore from the S3 object in the target region:

```bash
aws elasticache create-replication-group \
  --replication-group-id <new-cluster-id> \
  --replication-group-description "Restored from cross-region snapshot" \
  --engine valkey \
  --snapshot-arns arn:aws:s3:::<s3-bucket-in-target-region>/<snapshot-name>-export-0001.rdb \
  --cache-node-type <node-type> \
  --region <target-region>
```

Note: the `--target-bucket` parameter on `copy-snapshot` is reserved for exporting a snapshot to S3. Do not use it when making a copy of a backup within ElastiCache.

**S3 export** (exports snapshot to an S3 bucket for external use or archival):

```bash
aws elasticache copy-snapshot \
  --source-snapshot-name <snapshot-name> \
  --target-snapshot-name <snapshot-name>-export \
  --target-bucket <s3-bucket-in-same-region> \
  --region <source-region>
```

The ElastiCache backup and the S3 bucket must be in the same AWS Region.

### Subnet Group Compatibility

The target cache must use a subnet group within the same VPC, or a peered/connected VPC, as the application workloads.

**Checks to perform:**

* Confirm the target subnet group exists and has subnets in the required AZs.
* Verify that the target subnets have sufficient available IP addresses for the cache nodes (each node and replica consumes one IP).
* If migrating from self-managed Redis in a different VPC, confirm VPC peering or Transit Gateway connectivity.

```bash
# Check available IPs in target subnets
aws ec2 describe-subnets \
  --subnet-ids <subnet-1> <subnet-2> \
  --query "Subnets[*].{SubnetId:SubnetId,AZ:AvailabilityZone,AvailableIPs:AvailableIpAddressCount}" \
  --region <region>
```

### Shard Count Compatibility

For online migration (`start-migration`), the number of shards in the source and target **must** match. This is a hard prerequisite — online migration will fail if shard counts differ. Verify shard counts match before starting migration.

```bash
# Check shard count on source (self-managed Redis cluster-mode enabled)
valkey-cli -h <source-host> -p <port> CLUSTER INFO | grep cluster_size

# Check shard count on target ElastiCache replication group
aws elasticache describe-replication-groups \
  --replication-group-id <target-cluster> \
  --query "ReplicationGroups[0].NodeGroups | length(@)" \
  --region <region>
```

### Security Group Port Mismatches

Different ElastiCache deployment models use different ports. A security group misconfiguration will cause silent connectivity failures.

| Deployment Model | Default Port | TLS Required? |
|-----------------|:------------:|:-------------:|
| Node-based (no TLS) | 6379 | No |
| Node-based (with TLS) | 6379 | Yes |
| Serverless | 6379 | Yes (always) |

**Common mismatches to check:**

* Source security group allows port 6379 but target security group does not (or vice versa).
* Application security group has outbound rules that restrict the target port.
* When migrating from node-based to serverless, confirm TLS is configured in the client (serverless always requires TLS).
* When migrating from serverless to node-based, confirm the security group allows port 6379 (or the custom port if configured).

**Cross-VPC prerequisite:**

* If the source Redis instance and the target ElastiCache cluster are in different VPCs, VPC peering or Transit Gateway connectivity must be established before starting online migration. The ElastiCache nodes must be able to reach the source Redis IP address over the network.

**Migration-specific security group requirement:**

* During online migration (`start-migration`), ElastiCache nodes connect TO the source Redis instance to replicate data. The security group attached to your source Redis instances must allow **inbound** traffic from ElastiCache nodes on the Redis port.

```bash
# Check inbound rules on the target security group
aws ec2 describe-security-groups \
  --group-ids <target-sg-id> \
  --query "SecurityGroups[0].IpPermissions[?FromPort==\`6379\`]" \
  --region <region>

# Check outbound rules on the application security group
aws ec2 describe-security-groups \
  --group-ids <app-sg-id> \
  --query "SecurityGroups[0].IpPermissionsEgress[?FromPort==\`6379\` || FromPort==\`0\`]" \
  --region <region>
```

**Remediation:** If port mismatches are found, update the security group rules before starting migration. Require explicit user confirmation before modifying security groups.
