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
| `database.replication_privilege` | each PostgreSQL | `downtime_tolerance` is below one hour | none. Unresolved: a sub-hour tolerance has no compliant method until privileges are known, so the row returns to Clarify. A user answer of `not_available` rejects logical replication and DMS CDC, and the downtime requirement then cannot be met without a remediation or a relaxed tolerance. | Eligibility of logical replication and AWS DMS | Design data selector method rules 2–3; Generate guide PostgreSQL preflight. |
| `database.extensions` | each PostgreSQL | extensions are not discoverable from the inventory or application code | none. Unresolved while an unsupported extension could exist. | RDS versus Aurora versus EC2 target | Design data selector target rule 1. |
| `database.reader_topology` | each PostgreSQL | the inventory shows no replica count and the user mentions read scaling | `writer_only`: one writer, no readers. | Aurora versus RDS and reader instance count | Design data selector target rule 2; Estimate database line quantity. |
| `key_value.migration_strategy` | each Key Value | persistence is on, or the role is queue, session, or primary store | none for a queue, session, primary store, or any store with persistence on: unresolved, because every method but `empty_start` preserves data. `empty_start` (accept an empty store after cutover, queued and session data lost) is a default only for a store already established as a cache with persistence off, and the row is then `not_applicable`. | Key Value migration method (dual-write, snapshot restore, or empty start) | Generate guide Key Value migration section. |

Skip-ahead: for a development-only PostgreSQL with no stated downtime requirement, default `database.downtime_tolerance` to `maintenance_window` and mark `replication_privilege` `not_applicable`. Only a `maintenance_window` answer (or this skip-ahead) permits dump/restore without privilege facts.
