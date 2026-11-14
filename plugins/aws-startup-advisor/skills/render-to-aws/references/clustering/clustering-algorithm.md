# Render clustering algorithm

Seed one deployment cluster for each non-null environment ID. Resources without an environment seed by project ID. Resolve topology-only resources such as domains, disks, Build Sources, artifacts, and environment groups into the cluster of their linked service or environment. Preserve production and staging as separate clusters even when they share a project; the project remains an application-family relationship rather than a merge instruction.

After seeding, explicit cross-project workload dependencies may merge components. Repository sharing alone never merges clusters; a shared Build Source is strong evidence but remains subordinate to environment isolation. Members are unique and byte-sorted. A cluster ID hashes the ordered complete member list according to `deterministic-identities.md`. Resources with no safe seed or explicit relationship remain in `unclustered_resource_ids`; every resource occurs exactly once across clusters and that list.
