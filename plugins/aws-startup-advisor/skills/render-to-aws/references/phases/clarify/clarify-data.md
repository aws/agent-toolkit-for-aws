---
_fragment: data
_of_phase: clarify
_contributes:
  - preferences.json
---

# Clarify data requirements

For each PostgreSQL resource, resolve only unknown decision inputs: engine version, extensions, required privileges and parameters, logical-replication support, pooling mode, HA, readers, cross-Region need, RTO/RPO, storage and IOPS, connections, demand variability, growth, downtime/CDC requirement, and cost-versus-Aurora operational priority. Resolve source privileges before choosing `pg_dump`/`pg_restore`, logical replication, or AWS DMS. Clarify cannot complete while a non-negotiable compatibility fact could change the single database target.

For each Key Value resource, resolve persistence and accepted data-loss window, eviction, cache/queue/session/primary-store role, command and module compatibility, pub/sub, streams, Lua, failover, operation rate, hot keys, size, connections, and active-active cross-Region writes. Do not infer durability when Render reports persistence off. MemoryDB is considered only for an explicit demonstrated MemoryDB-specific outcome; ordinary compatible workloads default to ElastiCache for Valkey.

Never request database rows, connection information, credentials, Key Value contents, or secret values.
