# Networking — VPC Lattice

VPC Lattice is useful for a narrow set of ODB@AWS scenarios. For most multi-VPC connectivity, prefer TGW (see **networking-transit-gateway.md** (loaded reference)).

## When to Use VPC Lattice

- Expose ODB@AWS as a managed service to many consumer VPCs without peering or TGW sprawl.
- Enable the ODB network to reach AWS S3 for Data Pump, RMAN backups, or external tables.
- Set up Zero-ETL pipelines from ODB to AWS analytics services.
- Use IAM-based auth policies to control which consumer VPCs can reach the database.

## Architecture

```
Consumer VPC ── Lattice Service Network ── ODB Service (target: SCAN endpoint)
ODB Network ── Lattice ── S3 (Data Pump / RMAN)
```

## Key Concepts

- **Service Network** — logical grouping of services that consumer VPCs associate with.
- **Service** — the ODB endpoint exposed through Lattice.
- **Target group** — points to the SCAN hostname or IPs.
- **Auth policy** — IAM policy controlling which principals or source VPCs can reach the service.

## ODB Network → S3 Access

ODB networks can reach S3 through VPC Lattice for:
- Oracle Data Pump export/import
- RMAN backup to S3
- External tables reading from S3

Configure the S3 access at the ODB network level in the AWS console. The AWS CLI has a corresponding `aws odb` subcommand to enable it; check `aws odb help` for the current command name in your CLI version.

## Limitations

- Lattice adds small latency overhead relative to direct peering; NOT suitable for sub-millisecond OLTP.
- Best for service discovery and access control patterns, not for latency-critical application workloads.

## When NOT to Use VPC Lattice

- Single VPC connecting to ODB → use direct ODB peering (see **networking-odb-peering.md** (loaded reference)).
- Low-latency OLTP workloads → direct peering or TGW.
- Simple multi-VPC in one region → TGW is simpler and cheaper.
