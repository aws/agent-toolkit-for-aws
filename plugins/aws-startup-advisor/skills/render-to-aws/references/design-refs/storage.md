# Persistent disk selector

Candidate set: `Amazon EFS`, `Amazon EBS`, `Amazon S3`, `Amazon S3-backed file access`. Apply in order and emit exactly one target:

1. If access is object-oriented and the application can use an object API, select S3.
2. If S3 must remain the system of record but verified S3 Files criteria require path access, select S3-backed file access.
3. If Linux/POSIX file semantics are required by Fargate, ECS, EKS, Lambda, multiple instances, or multiple clients, select EFS. This is the startup default for an unresolved single-client container filesystem only after POSIX semantics are established.
4. Select EBS only when compute is explicitly EC2-hosted, single-AZ block coupling and attachment mode are accepted, and discovered POSIX, performance, backup, and recovery requirements fit EBS.
5. If object-versus-file semantics, sharing, compute host, AZ coupling, performance, or recovery facts are missing and can change the winner, return to Clarify.

EBS is never a generic Fargate disk. S3 is never selected for an application that requires unsupported POSIX locking/rename semantics. S3-backed file access is not a vague compromise: it requires evidence that S3 remains authoritative and the selected path-access mechanism meets consistency and operation requirements.

Record evidence, ordered rules evaluated/fired, defaults used, and three rejected candidates with concrete reasons. Preserve mount path, used/provisioned capacity and growth, sharing/concurrency, ownership/permissions/locking/rename, latency/throughput/IOPS, backup/RPO/RTO, region/AZ coupling, and data-transfer/cutover requirements.

Every selected target also carries one migration procedure: pre-copy/delta or bounded downtime; application-consistent writer quiescence; capacity and bandwidth plan; checksum or application-level integrity validation; ownership/permission validation; cutover; rollback; and explicit Render source-retention period. The synthetic disk marker is evidence only and is never customer migration data.
