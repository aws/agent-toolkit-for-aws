# Storage

Pass-2 rubric for storage types that reach it. Thin by design: the storage account and
its four service children are Direct Mappings, so most storage resolves in pass 1 and
never loads this file.

**Outcome is `confidence: inferred`.** Never `deterministic`.

It exists for three things a mapping table cannot hold: the file-share protocol
discriminator, the tiering and lifecycle carry-over, and the resources that arrive here
through `namespace_routing` because they have no row of their own.

## 1. Eliminators

| Candidate                       | Eliminated when                                                                                                                                                                                                            |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **EFS**                         | the share's `enabled_protocol` is **SMB**. EFS is NFS only — this is a protocol boundary, not a preference                                                                                                                 |
| **FSx for Windows File Server** | the share's `enabled_protocol` is **NFS**                                                                                                                                                                                  |
| **S3**                          | the workload needs **POSIX filesystem semantics** — byte-range writes in place, hard links, file locking. S3 is an object store, and an application that mounts a drive letter or a mount point is not doing object access |
| **S3 Glacier / Deep Archive**   | the data is read on a latency-sensitive path. Archive retrieval is minutes to hours                                                                                                                                        |

## 2. The protocol rule (owner decision 11.5)

`Microsoft.Storage/storageAccounts/fileServices/shares` is a **fast-path row**, not a
rubric row, because `enabled_protocol` is a property of the resource itself and there is
no rubric left once you read it:

| `enabled_protocol` | Target                          | Why                                                                                                                                 |
| ------------------ | ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `SMB`              | **FSx for Windows File Server** | SMB shares are usually AD-joined, which lines up with the Windows weighting the rest of this skill assumes. FSx speaks SMB natively |
| `NFS`              | **EFS**                         | Direct protocol match                                                                                                               |

The row is here only so a reviewer can find the reasoning. Do not re-decide it.

**A premium `FileStorage` account has no blob surface at all.** Its `Always → S3` condition
is therefore false, and it emits no target of its own — the shares carry the mapping. That
is the one condition on the storage account row.

## 3. Access tier and lifecycle

Carried across, not re-decided:

| Azure                                                  | AWS                                                                                                                        |
| ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------- |
| `access_tier = "Hot"`                                  | S3 Standard                                                                                                                |
| `access_tier = "Cool"`                                 | S3 Standard-IA                                                                                                             |
| `access_tier = "Cold"`                                 | S3 Glacier Instant Retrieval                                                                                               |
| Archive tier (per-blob)                                | S3 Glacier Flexible Retrieval or Deep Archive — the choice is a retrieval-time decision, so it is a finding, not a mapping |
| `Microsoft.Storage/storageAccounts/managementPolicies` | S3 lifecycle configuration — rule shapes differ; carry the INTENT and say the rules were reauthored                        |

**`is_hns_enabled` (Data Lake Gen2) is a signal, not a tier.** A hierarchical-namespace
account is usually an analytics data lake, so it belongs to whatever cluster the pipeline
is in — and if that cluster hits the `data-pipeline` gate, the account defers with it
rather than mapping to a lone bucket.

## 4. Replication

`account_replication_type` maps to a durability posture, and two of the five have no
direct counterpart:

| Azure            | AWS                                                                                                                                                                                                         |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `LRS`            | S3 Standard — single-region, multi-AZ by default                                                                                                                                                            |
| `ZRS`            | S3 Standard. Already how S3 behaves; no extra configuration and no extra cost                                                                                                                               |
| `GRS` / `RA-GRS` | **S3 Cross-Region Replication**, which is an explicit configuration with its own storage and transfer cost. This is a NEW line item, not a free carry-over — Azure bundles it into the SKU and AWS does not |
| `GZRS`           | S3 + CRR, as GRS                                                                                                                                                                                            |

Emit a `warnings[]` entry for any GRS/GZRS account, because the estimate has to gain a
replication cost that the source's single SKU hid.

## 5. NetApp Files

`Microsoft.NetApp/*` arrives here via `namespace_routing`. Target is **FSx for NetApp
ONTAP** — the same vendor platform, so it is a genuine like-for-like. Capacity pools and
volumes map to a file system and volumes. Treat the service-level (Standard/Premium/Ultra)
as a throughput requirement, not an instance size.

## 6. Output

Per `schema-design-aws.md` § `services[]`: `aws_service`, `aws_config` (storage class,
lifecycle intent, replication, protocol for a share), `confidence: "inferred"`,
`rubric_applied: "storage.md"`, and a `rationale` naming which criterion fired.

There is no storage sizing table, so any capacity figure carried from the source is
`sizing_provenance: "table"` only when it came straight from the source's own quota;
anything derived is `model_prior`.

## Status — build step 5b

Thin on purpose. Blob, container, queue, table and share are all fast-path rows; this file
carries the protocol rule's reasoning, tiering, replication, and the `namespace_routing`
landing zone for `Microsoft.Storage/*` and `Microsoft.NetApp/*` types with no row.
