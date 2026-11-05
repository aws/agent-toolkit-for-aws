# Data selectors

## PostgreSQL target

Candidate set: `Amazon RDS for PostgreSQL`, `Amazon Aurora PostgreSQL`, `Self-managed PostgreSQL on Amazon EC2`. Apply first decisive rule:

1. Compare version, extensions, privileges, logical replication, parameters, and operational dependencies against both managed targets. If exactly one preserves all non-negotiable capabilities, select it. If neither does and the capability cannot be remediated, select self-managed PostgreSQL on EC2 and require specialist validation. If compatibility facts are missing, return to Clarify.
2. Select Aurora when an Aurora-specific outcome is required: Global Database, Aurora reader/autoscaling behavior, Aurora Serverless behavior, or an evidence-backed availability/performance requirement that RDS cannot satisfy.
3. Select RDS for a conventional single-instance or HA PostgreSQL workload with stable demand when it satisfies RTO/RPO, connection, storage, and scaling requirements and no Aurora-specific rule fired.
4. When both managed targets satisfy all requirements, estimate both internally at the required topology and select the lower projected cost unless the user explicitly values an Aurora-only benefit enough to justify its premium.
5. If the required facts for rules 1–4 are missing, return only those question IDs to Clarify.
6. If both remain valid with no demonstrated differentiator, select RDS as the lower-change startup default. Record this default and reject Aurora with the trigger that would have selected it.

The output has one target and records evidence, every rule evaluated/fired, questions/defaults, and both rejected candidates. It never says “RDS or Aurora.”

## PostgreSQL migration method

Candidate set: `pg_dump and pg_restore`, `logical replication`, `AWS Database Migration Service`.

1. For acceptable-downtime full loads with verified source privileges and compatible data size, select native dump/restore.
2. For lower-downtime cutover with verified logical-replication support and a simple PostgreSQL-only path, select logical replication.
3. Select AWS DMS when lower downtime, managed full-load-plus-CDC, validation, or heterogeneous operational control is required and source privileges support it.
4. Missing privilege, downtime, volume, or consistency facts return to Clarify.

## Key Value target

Candidate set: `Amazon ElastiCache for Valkey serverless`, `Amazon ElastiCache for Valkey node-based`, `Amazon MemoryDB`, `Self-managed Valkey on Amazon EC2`.

1. If required commands/modules cannot be preserved by managed candidates, select the smallest explicit remediation; only a non-removable capability selects self-managed Valkey with specialist validation.
2. Select MemoryDB only for an explicit active-active cross-Region write requirement or another demonstrated MemoryDB-specific durability outcome.
3. Select ElastiCache Serverless when compatibility is established, demand is variable/unknown, serverless constraints fit, and persistence/eviction semantics are preserved.
4. Select node-based ElastiCache when stable capacity, node-level control, reserved-node economics, or serverless incompatibility is established.
5. If both ElastiCache modes fit and no differentiator exists, select node-based ElastiCache sized from the source memory plan as the capacity-preserving startup default; record the trigger for Serverless.
6. Missing role, persistence, eviction, compatibility, cross-Region, or sizing facts return to Clarify when they can change the winner.

A source with persistence off is described as a cache/ephemeral queue unless user evidence says otherwise. Preserve maxmemory policy, pub/sub, streams, Lua, accepted data loss, failover, and connection behavior.
