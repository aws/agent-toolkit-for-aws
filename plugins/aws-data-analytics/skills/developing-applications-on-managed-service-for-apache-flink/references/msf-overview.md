# Managed Service for Apache Flink Overview and Concepts Guide

## Introduction

Amazon Managed Service for Apache Flink is a fully managed service that makes it easy to develop, deploy, and operate Apache Flink applications on AWS using Kiro IDE for development. Managed Service for Apache Flink supports Flink 1.20 and Flink 2.2. For new applications, default to Flink 2.2. For existing applications, use the user's current Flink version. This guide provides a comprehensive overview of Managed Service for Apache Flink architecture, KPU-based scaling, service-level configuration, and key differences from self-managed Flink deployments.

Managed Service for Apache Flink abstracts infrastructure complexity while providing the full power of Apache Flink for stream processing, with a clear separation between service-level configuration managed by Managed Service for Apache Flink and application-level configuration controlled by developers through Kiro IDE.

## Managed Service for Apache Flink Architecture Overview

### Service Architecture

Managed Service for Apache Flink abstracts away the complexity of managing Flink clusters while providing the full power of Apache Flink for stream processing. The service architecture consists of:

**Control Plane**:

- Application lifecycle management through Managed Service for Apache Flink console and APIs
- KPU-based automatic scaling and resource management
- Service-level configuration management (checkpoints, savepoints, parallelism)
- Integrated CloudWatch monitoring and logging
- IAM-based security and access control

**Data Plane**:

- Flink JobManager and TaskManager processes managed by Managed Service for Apache Flink
- Managed Service for Apache Flink-controlled checkpointing and savepoint storage in managed S3 buckets
- Optimized network and storage configuration for AWS environment
- Automatic fault tolerance and recovery with service-level checkpoint management

### Key Components

1. **Flink Applications**: Your stream processing logic packaged as JAR files, developed using Kiro IDE
2. **KPU Configuration**: Kinesis Processing Units providing standardized resource allocation (1 vCPU, 4GB memory per KPU)
3. **Service-Level Configuration**: Managed Service for Apache Flink-managed settings for checkpoints, savepoints, parallelism, and infrastructure
4. **Application Configuration**: User-controlled runtime parameters, business logic settings, and connector configurations
5. **CloudWatch Integration**: Automatic metrics collection, logs aggregation, and monitoring dashboards

### KPU-Based Resource Model

**Kinesis Processing Units (KPUs)**:

- **You do not pick instance types or manage TaskManagers directly.** MSF abstracts both away — KPU is the only resource unit you configure. Selecting EC2 instance types is not a setting you can change, including via the console. Custom CPU/memory ratios per KPU also are not configurable in MSF.
- Each KPU provides exactly 1 vCPU and 4 GB of memory (standardized resource allocation), plus 50 GB of running application storage.
- Managed Service for Apache Flink automatically scales KPUs based on application throughput and backpressure metrics
- You configure `Parallelism` (total task slots) and `ParallelismPerKPU` (slots per KPU) at the service level; MSF derives `Allocated KPUs = Parallelism / ParallelismPerKPU`
- KPU allocation determines the maximum parallelism and resource capacity available to your application

**Resource Scaling**:

- Automatic horizontal scaling based on real-time throughput and backpressure analysis
- Service-level parallelism configuration through Managed Service for Apache Flink console overrides application defaults
- Managed Service for Apache Flink manages TaskManager allocation and distribution across KPUs automatically
- Pay-per-use pricing model - only pay for the KPUs your application actively uses
- Scaling decisions are made by Managed Service for Apache Flink based on performance metrics, not manual configuration

## Managed Service for Apache Flink Capabilities

### Core Streaming Capabilities

**Stream Processing APIs**:

- DataStream API for low-level stream processing
- Table API for relational stream processing with improved performance
- Flink SQL for declarative stream analytics with expanded function library
- Complex Event Processing (CEP) for pattern detection (note: Flink 2.x requires explicit TypeInformation for CEP pattern output)

**State Management**:

- Managed keyed state with Managed Service for Apache Flink-controlled automatic checkpointing
- Broadcast state for configuration distribution
- RocksDB state backend optimized for Managed Service for Apache Flink environment
- Automatic state cleanup and TTL management
- Service-level checkpoint configuration (interval, retention, storage)

**Time Processing**:

- Event time processing with watermarks (default and only time characteristic in Flink 2.x)
- Processing time for low-latency scenarios
- Custom timestamp extractors and watermark strategies

### AWS Service Integration

**Data Sources**:

- Amazon Kinesis Data Streams
- Amazon MSK (Managed Streaming for Apache Kafka)
- Amazon S3 for batch processing
- Amazon DynamoDB Streams

**Data Sinks**:

- Apache Iceberg
- Amazon S3 with various formats (Parquet, JSON, CSV)
- Amazon DynamoDB for real-time updates
- Amazon OpenSearch Service
- Amazon Data Firehose
- Custom sinks via AWS SDK

For Managed Service for Apache Flink vs self-managed Flink differences, MSF-specific constraints, and common MSF patterns, see [msf-constraints-and-patterns.md](msf-constraints-and-patterns.md).

## Next Steps

After understanding Managed Service for Apache Flink architecture and capabilities:

1. **Environment Setup**: Configure your Kiro IDE development environment for Managed Service for Apache Flink development with Docker containerization
2. **Development Patterns**: Learn Managed Service for Apache Flink-optimized application patterns and templates
3. **Local Development**: Set up Docker-based local testing workflows in Kiro before Managed Service for Apache Flink deployment
4. **Deployment**: Understand Managed Service for Apache Flink deployment procedures and service-level configuration best practices

For detailed guidance on each of these areas, refer to the corresponding guides in the steering directory. All development workflows are optimized for Kiro IDE with Docker-based local development targeting Managed Service for Apache Flink deployment.
