# Managed Service for Apache Flink Development Environment Setup

## Overview

This guide provides setup instructions for Apache Flink development targeting Amazon Managed Service for Apache Flink deployment. The setup ensures compatibility with Managed Service for Apache Flink requirements while enabling efficient local development and testing workflows using Docker containers that mirror the Managed Service for Apache Flink environment. For new applications, default to Flink 2.2. For existing applications, use the user's current Flink version.

## Prerequisites

Before starting, ensure you have:

- Administrative access to your development machine
- Stable internet connection for downloading dependencies
- At least 16GB RAM and 30GB free disk space (for Docker containers)
- Docker Desktop installed and running
- Java 11 (for Flink 1.20) or Java 17 (for Flink 2.2) installed
- Basic familiarity with command-line operations and Docker concepts

## Core Development Environment

### 1. Docker Desktop Installation

Docker is required for running Flink, Kafka, LocalStack, and other infrastructure locally for testing. Ensure Docker is installed.

**Verification:**

```bash
docker --version
docker-compose --version
docker run hello-world
```

### 2. Java Development Kit (JDK) for Container Development

While Flink runs in containers, JDK is still needed for compilation and IDE support. Flink 1.20 requires Java 11. Flink 2.2 requires Java 17 (Java 21 also supported).

**Verification:**

```bash
java -version
javac -version
echo $JAVA_HOME
```

## Docker-Based Flink Development Environment

### Docker Compose Configuration

Create a comprehensive Docker Compose setup that mirrors the Managed Service for Apache Flink environment. Adjust the Flink image tag to match your target version:

- Flink 1.20: `flink:1.20-java11`
- Flink 2.2: `flink:2.2-java17`

**Create `docker-compose.yml` in your project root:**

```yaml
version: '3.8'

# Set FLINK_IMAGE_TAG in your environment or .env file:
#   Flink 1.20: FLINK_IMAGE_TAG=1.20-java11
#   Flink 2.2:  FLINK_IMAGE_TAG=2.2-java17

services:
  # Flink JobManager
  jobmanager:
    image: flink:${FLINK_IMAGE_TAG:-2.2-java17}
    hostname: jobmanager
    container_name: flink-jobmanager
    ports:
      - "8081:8081"
    command: jobmanager
    environment:
      - |
        FLINK_PROPERTIES=
        jobmanager.rpc.address: jobmanager
        jobmanager.memory.process.size: 1600m
        jobmanager.execution.failover-strategy: region
      - RUNTIME_ENVIRONMENT=local
    volumes:
      - ./flink-jobs:/opt/flink/jobs
      - flink-checkpoints:/tmp/flink-checkpoints
      - flink-savepoints:/tmp/flink-savepoints
    networks:
      - flink-network

  # Flink TaskManager
  taskmanager:
    image: flink:${FLINK_IMAGE_TAG:-2.2-java17}
    depends_on:
      - jobmanager
    command: taskmanager
    scale: 2
    environment:
      - |
        FLINK_PROPERTIES=
        jobmanager.rpc.address: jobmanager
        taskmanager.numberOfTaskSlots: 2
        parallelism.default: 2        
        taskmanager.memory.process.size: 1728m
        taskmanager.memory.managed.fraction: 0.4
        state.backend: rocksdb
        state.checkpoints.dir: file:///tmp/flink-checkpoints
        state.savepoints.dir: file:///tmp/flink-savepoints
        execution.checkpointing.interval: 60000
        execution.checkpointing.mode: EXACTLY_ONCE
        restart-strategy: exponential-delay
        restart-strategy.exponential-delay.initial-backoff: 10s
        restart-strategy.exponential-delay.max-backoff: 2min
        restart-strategy.exponential-delay.backoff-multiplier: 2.0
      - RUNTIME_ENVIRONMENT=local
    volumes:
      - ./flink-jobs:/opt/flink/jobs
      - flink-checkpoints:/tmp/flink-checkpoints
      - flink-savepoints:/tmp/flink-savepoints
    networks:
      - flink-network

  # Kafka (for streaming data sources)
  zookeeper:
    image: confluentinc/cp-zookeeper:7.4.0
    hostname: zookeeper
    container_name: zookeeper
    ports:
      - "2181:2181"
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
      ZOOKEEPER_TICK_TIME: 2000
    networks:
      - flink-network

  kafka:
    image: confluentinc/cp-kafka:7.4.0
    hostname: kafka
    container_name: kafka
    depends_on:
      - zookeeper
    ports:
      - "9092:9092"
      - "9101:9101"
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: 'zookeeper:2181'
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:29092,PLAINTEXT_HOST://localhost:9092
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: 1
      KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1
      KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS: 0
      KAFKA_JMX_PORT: 9101
      KAFKA_JMX_HOSTNAME: localhost
    networks:
      - flink-network

  # LocalStack (for local AWS service emulation: Kinesis, S3, DynamoDB, etc.)
  localstack:
    image: localstack/localstack:3.5.0
    container_name: localstack
    ports:
      - "4566:4566"
    environment:
      SERVICES: kinesis,s3,dynamodb,cloudwatch
      DEFAULT_REGION: us-east-1
    networks:
      - flink-network

volumes:
  flink-checkpoints:
  flink-savepoints:

networks:
  flink-network:
    driver: bridge
```

### Starting the Development Environment

**1. Create Project Structure:**

```bash
# Create Managed Service for Apache Flink project directory
mkdir my-msf-app
cd my-msf-app

# Create required directories
mkdir -p flink-jobs src/main/java src/test/java

# Copy docker-compose.yml to project root
```

**2. Start Docker Environment:**

```bash
# Start all services
docker-compose up -d

# Verify services are running
docker-compose ps

# Check taskmanager logs for submitted Flink jobs 
docker-compose logs taskmanager

# Check Flink Web UI
open http://localhost:8081

# Check Kafka
docker-compose exec kafka kafka-topics --bootstrap-server localhost:9092 --list
```

## Build Tools and Dependencies

### Maven Project Template for Managed Service for Apache Flink

Build the JAR in local mode to include Managed Service for Apache Flink provided dependencies:

```bash
# For Flink 1.20 (Java 11):
mvn clean package -Plocal -q

# For Flink 2.2 (Java 17):
# Set JAVA_HOME to your Java 17 installation path before building
export JAVA_HOME=<path-to-java-17>
mvn clean package -Plocal -q

cp target/my-flink-app-1.0.jar flink-jobs/

docker exec flink-jobmanager flink run /opt/flink/jobs/my-flink-app-1.0.jar
```

See `dependency-management.md` for examples of dependencies and pom.xml requried for Managed Service for Apache Flink.

### Managed Service for Apache Flink-Specific Tools

**AWS CLI Managed Service for Apache Flink Commands:**

```bash
# List Managed Service for Apache Flink applications
aws kinesisanalyticsv2 list-applications

# Describe Managed Service for Apache Flink application
aws kinesisanalyticsv2 describe-application --application-name my-app

# Create savepoint
aws kinesisanalyticsv2 create-application-snapshot --application-name my-app --snapshot-name my-snapshot
```
