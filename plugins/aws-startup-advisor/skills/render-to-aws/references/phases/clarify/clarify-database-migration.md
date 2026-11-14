---
_fragment: database-migration
_of_phase: clarify
_contributes:
  - preferences.json
---
# Clarify database and Key Value migration inputs
These rows supply the inputs to the PostgreSQL target, PostgreSQL migration method, and Key Value selectors. Use the inventory first: a discovered engine version, plan, disk size, replica set, persistence setting, or maxmemory policy is recorded with provenance `discovered` and is never asked. Never request rows, connection strings, credentials, or Key Value contents. All rows use topic `data` and one row per resource.

| `question_id` | Resource | Ask when | Default and consequence | `decision_changed` | Consumer |
| --- | --- | --- | --- | --- | --- |
| `database.downtime_tolerance` | each PostgreSQL | always | `maintenance_window`: dump/restore with writers stopped. Longer outage, simplest path. | PostgreSQL migration method | Design data selector method rules 1–3; Generate migrate-postgres script stages. |
| `database.replication_privilege` | each PostgreSQL | `downtime_tolerance` is below one hour | `not_available`: logical replication and DMS CDC are rejected and the method falls back to dump/restore. | Eligibility of logical replication and AWS DMS | Design data selector method rules 2–3; Generate guide PostgreSQL preflight. |
| `database.extensions` | each PostgreSQL | extensions are not discoverable from the inventory or application code | none. Unresolved while an unsupported extension could exist. | RDS versus Aurora versus EC2 target | Design data selector target rule 1. |
| `database.reader_topology` | each PostgreSQL | the inventory shows no replica count and the user mentions read scaling | `writer_only`: one writer, no readers. | Aurora versus RDS and reader instance count | Design data selector target rule 2; Estimate database line quantity. |
| `key_value.migration_strategy` | each Key Value | persistence is on, or the role is queue, session, or primary store | `empty_start`: accept an empty cache after cutover. Queued and session data is lost. | Key Value migration method (dual-write, snapshot restore, or empty start) | Generate guide Key Value migration section. |

Skip-ahead: for a development-only PostgreSQL with no stated downtime requirement, default `database.downtime_tolerance` to `maintenance_window` and mark `replication_privilege` `not_applicable`.
