# RDS Optimization

## Compute Optimizer for RDS

Supported engines: MySQL, PostgreSQL, Aurora MySQL, Aurora PostgreSQL.

**Metrics analyzed:** CPUUtilization, DatabaseConnections, NetworkReceive/TransmitThroughput, ReadIOPS/WriteIOPS, ReadThroughput/WriteThroughput, EBSIOBalance%/EBSByteBalance%, FreeStorageSpace. With Performance Insights: DBLoad, os.swap.in/out.

**Finding classifications:** `Overprovisioned`, `Underprovisioned`, `Optimized`.

**Finding reason codes:** CPUOverprovisioned, CPUUnderprovisioned, MemoryUnderprovisioned (high swap/OOM), NetworkBandwidthOver/Under, EBSThroughput/IOPSOver/Under, NewGenerationAvailable, NewEngineVersionAvailable.

**Storage findings:** EBSVolumeAllocatedStorageUnderprovisioned, EBSVolumeIOPS/ThroughputOver/Under, NewGenerationStorageTypeAvailable.

```bash
aws compute-optimizer get-rds-db-instance-recommendations \
  --filters Name=Finding,Values=Overprovisioned
```

## Multi-AZ Considerations

- Changes apply to both primary and standby instances
- Failover timing may be affected by instance changes
- Multi-AZ reduces downtime during modifications

## Read Replica Considerations

- Recommendations synchronized with writer for promotion tiers ≤1
- Smaller replica instances may increase replication lag

## Storage Considerations

- Storage can only be increased, not decreased
- Storage type changes may require specific instance types
- gp3 provides more flexible IOPS/throughput provisioning than gp2

## Gotchas

- DB instance modifications typically require brief downtime (5-10 min)
- Engine version upgrades require compatibility assessment
- Parameter group changes may be required after instance class change
- Always take a snapshot before implementing changes
- Performance risk scale: 0-1 Very Low, >1-2 Low, >2-3 Medium, >3-4 High
