---
_fragment: storage
_of_phase: clarify
_contributes:
  - preferences.json
---

# Clarify persistent storage requirements

For every persistent disk, preserve discovered mount path and ask only the smallest unresolved set that can change the target:

- Whether access is object-oriented or requires Linux/POSIX path semantics.
- Whether multiple instances or clients require shared concurrent access.
- Whether compute is explicitly EC2-hosted and single-AZ block coupling and the required attachment model are acceptable.
- Required ownership, permissions, locking, atomic rename, file count/size, latency, throughput, IOPS, used/provisioned capacity, and growth.
- Backup/snapshot policy, durability, RPO/RTO, region/AZ constraints, and restore validation.
- Transfer volume, bandwidth, consistency, writer quiescence, pre-copy/delta or downtime method, integrity and permission validation, cutover, rollback, and source retention.

Do not ask the user to choose EFS, EBS, S3, or S3-backed file access. If semantics, sharing, or EC2/AZ coupling remain unknown, the disk selector remains unresolved and Clarify cannot complete.
