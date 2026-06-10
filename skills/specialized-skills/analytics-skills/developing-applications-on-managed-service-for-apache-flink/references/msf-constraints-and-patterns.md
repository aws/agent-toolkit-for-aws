# MSF Constraints and Common Patterns

## Overview

This guide covers Managed Service for Apache Flink vs self-managed Flink differences, MSF-specific constraints (resource, network, storage limits), and common MSF patterns including streaming ETL and real-time analytics SQL examples.

For the MSF architecture overview, KPU resource model, and AWS service integration, see [msf-overview.md](msf-overview.md).

## Managed Service for Apache Flink vs Self-Managed Flink

### Key Differences

| Aspect | Managed Service for Apache Flink | Self-Managed Flink |
|--------|-----|-------------------|
| **Flink Version** | Flink 1.20 and 2.2 (managed updates) | Any version (manual upgrades) |
| **Infrastructure Management** | Fully managed by AWS | Manual cluster setup and maintenance |
| **Resource Model** | KPU-based scaling (1 vCPU, 4GB per KPU) | Manual instance type selection and scaling |
| **Parallelism Configuration** | Service-level through Managed Service for Apache Flink console | Application-level in code |
| **Checkpoint Configuration** | Service-level managed by Managed Service for Apache Flink | Application-level configuration required |
| **Savepoint Management** | Managed Service for Apache Flink console and API-based | Manual CLI or API operations |
| **Monitoring** | Integrated CloudWatch | Custom monitoring setup required |
| **Security** | Built-in IAM integration | Manual security configuration |
| **Cost Model** | Pay for KPUs used | Pay for entire cluster resources |

### Configuration Separation

**MSF-Managed (Service-Level)**: Checkpoint intervals/retention/storage, savepoint management, parallelism/KPU scaling, network/VPC/security groups, cluster configuration (JobManager/TaskManager), state backend (RocksDB), fault tolerance settings.

**User-Controlled (Application-Level)**: Business logic, custom serializers/data formats, application properties, source/sink connector configs, custom metrics, watermark strategies, UDFs.

### Advantages of Managed Service for Apache Flink

- No cluster management overhead; automatic failure recovery with service-level checkpoints
- Built-in CloudWatch monitoring and alerting; simplified deployment
- Native AWS service connectivity with optimized connectors; IAM-integrated security
- Automatic KPU-based scaling; elastic resource allocation with pay-per-use pricing

### Considerations for Migration

- Application code remains largely unchanged (target Flink 1.20 or 2.2)
- Remove application-level checkpoint/savepoint configuration (now MSF-managed)
- Update parallelism settings for KPU-based scaling; replace custom monitoring with CloudWatch
- Move checkpoint config to MSF service-level settings; remove cluster-level configurations

## Managed Service for Apache Flink-Specific Constraints and Optimizations

### Service Constraints

**Resource Limits**:

- Maximum parallelism per application: ParallelismPerKPU × KPU limit (default KPU limit is 64; request increase via Service Quotas)
- Maximum memory per KPU: 4 GB (1 vCPU, 4 GB memory, 50 GB storage per KPU)
- Maximum number of applications per account: 50 (adjustable through AWS support)
- Checkpoint interval minimum: 1 second (configured via Managed Service for Apache Flink console, not application code)
- Maximum KPU count per application: 250 (default quota is 64; request increase via Service Quotas)

**Network Constraints**:

- VPC-only deployment (no direct public internet access for security)
- Specific subnet requirements for high availability across multiple AZs
- Managed Service for Apache Flink-managed security group configuration for service communication
- NAT Gateway or VPC endpoints required for external AWS service connectivity
- Cross-region data transfer limitations for compliance and performance

**Storage Constraints**:

- Checkpoints automatically stored in Managed Service for Apache Flink-managed S3 buckets (user cannot configure location)
- Savepoints require user-specified S3 bucket in same region as Managed Service for Apache Flink application
- State backend: RocksDB by default (configurable via AWS support case)
- Recommended maximum state size per key: keep values small (low single-digit MB) for optimal RocksDB performance
- Checkpoint retention managed by Managed Service for Apache Flink service-level policies, not application configuration

## Common Managed Service for Apache Flink Patterns

### Streaming ETL Pattern

```java
KinesisStreamsSource<ProcessedRecord> kdsSource =
        KinesisStreamsSource.<ProcessedRecord>builder()
                .setStreamArn("arn:aws:kinesis:us-east-1:123456789012:stream/test-stream")
                .setSourceConfig(sourceConfig)
                .setDeserializationSchema(new ProcessedRecordDeserializationSchema())
                .setKinesisShardAssigner(ShardAssignerFactory.uniformShardAssigner())
                .build();
                
DataStream<ProcessedRecord> processed = env
    .fromSource(kdsSource,
            WatermarkStrategy.<ProcessedRecord>forBoundedOutOfOrderness(Duration.ofSeconds(5))
                    .withTimestampAssigner((event, ts) -> event.getTimestamp())
                    .withIdleness(Duration.ofSeconds(10)),
            "Kinesis Source")
    .keyBy(ProcessedRecord::getKey)
    .window(TumblingEventTimeWindows.of(Duration.ofMinutes(5)))
    .aggregate(new AggregationFunction());

KinesisStreamsSink<ProcessedRecord> kdsSink =
    KinesisStreamsSink.<ProcessedRecord>builder()
        .setKinesisClientProperties(sinkProperties)
        .setSerializationSchema(new ProcessedRecordSerializationSchema())
        .setPartitionKeyGenerator(element -> String.valueOf(element.hashCode()))
        .setStreamArn("arn:aws:kinesis:us-east-1:123456789012:stream/sink-stream")
        // IMPORTANT: true ensures the job fails on write errors, letting Flink's
        // checkpoint/restart mechanism retry rather than silently dropping records.
        // Use false only for best-effort delivery where availability is prioritized
        // over data completeness — but be aware that failed records are lost.
        .setFailOnError(true)
        .setMaxBatchSize(500)
        .setMaxInFlightRequests(50)
        .setMaxBufferedRequests(10_000)
        .setMaxBatchSizeInBytes(5 * 1024 * 1024)
        .setMaxTimeInBufferMS(5000)
        .setMaxRecordSizeInBytes(1 * 1024 * 1024)
        .build();

processed.sinkTo(kdsSink);
```

### Real-time Analytics Pattern

```sql
-- Managed Service for Apache Flink-optimized Flink SQL for real-time analytics
CREATE TABLE kinesis_source (
    user_id STRING,
    event_type STRING,
    timestamp_col TIMESTAMP(3),
    WATERMARK FOR timestamp_col AS timestamp_col - INTERVAL '5' SECOND
) WITH (
    'connector' = 'kinesis',
    'stream' = 'user-events',
    'aws.region' = 'us-east-1',
    'format' = 'json'
);

CREATE TABLE s3_sink (
    window_start TIMESTAMP(3),
    window_end TIMESTAMP(3),
    user_count BIGINT,
    event_count BIGINT
) WITH (
    'connector' = 'filesystem',
    'path' = 's3://analytics-bucket/results/',
    'format' = 'parquet'
);

INSERT INTO s3_sink
SELECT 
    window_start,
    window_end,
    COUNT(DISTINCT user_id) as user_count,
    COUNT(*) as event_count
FROM TABLE(
    TUMBLE(TABLE kinesis_source, DESCRIPTOR(timestamp_col), INTERVAL '1' HOUR))
GROUP BY window_start, window_end;
```

### Local Docker Configuration vs Managed Service for Apache Flink Service Configuration

**IMPORTANT DISTINCTION**: Local Docker configuration is for development only and differs significantly from Managed Service for Apache Flink service configuration.

#### Managed Service for Apache Flink Service Configuration (Production Deployment)

**Managed Service for Apache Flink KPU Configuration (Service Level)**
Configured through Managed Service for Apache Flink console - NOT in application code. KPU Configuration:

- Each KPU: 1 vCPU, 4 GB memory
- You configure `Parallelism` (total task slots) and `ParallelismPerKPU` (task slots per KPU, default 1, max 8)
- Allocated KPUs = Parallelism / ParallelismPerKPU
- Auto-scaling: adjusts `CurrentParallelism` within Min/Max KPU bounds
- Managed Service for Apache Flink automatically manages task slot allocation

**Managed Service for Apache Flink Service Configuration (Console/API Only)**
Managed Service for Apache Flink manages these through service configuration:

State backend:

- RocksDB (configurable via support case)
Checkpoint Configuration:
- Interval: 60 seconds (configurable)
- Storage: S3 (Managed Service for Apache Flink-managed bucket)
Savepoint Configuration:
- Storage: S3 (Managed Service for Apache Flink-managed)
- Triggered through Managed Service for Apache Flink console/API
Parallelism Configuration:
- Parallelism: Total task slots (service-level setting)
- ParallelismPerKPU: Task slots per KPU (default 1, max 8)
- Allocated KPUs = Parallelism / ParallelismPerKPU
- Auto-scaling: adjusts CurrentParallelism within configured bounds
