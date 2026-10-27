# Managed Service for Apache Flink Development Best Practices

## Overview

This guide provides Managed Service for Apache Flink-optimized development patterns, anti-patterns, and best practices for building robust, performant, and secure Flink applications on Amazon Managed Service for Apache Flink. For existing applications, use the current user's Flink version. For new applications, assume Flink 2.2 and ask if the user has a preference.

Code examples in this guide use Flink 2.2 APIs by default, which are also compatible with Flink 1.20 unless noted otherwise. See `flink-2x-migration.md` for the complete migration reference.

## Development Patterns

### Best Practices for Managed Service for Apache Flink

**Application Design**:

- Design for KPU-based automatic scaling with service-level parallelism configuration
- Use appropriate parallelism levels as suggestions (Managed Service for Apache Flink service-level settings take precedence)
- Implement proper backpressure handling for Managed Service for Apache Flink's automatic scaling algorithms
- Design stateful operations with Managed Service for Apache Flink-managed checkpoint intervals in mind

**Resource Management**:

- Configure application for KPU-based resource allocation (1 vCPU, 4GB per KPU)
- Let Managed Service for Apache Flink manage checkpoint intervals and retention through service-level configuration
- Monitor resource utilization patterns through CloudWatch metrics
- Implement proper error handling that works with Managed Service for Apache Flink's automatic recovery

**Monitoring and Alerting**:

- Leverage integrated CloudWatch dashboards and metrics
- Configure Managed Service for Apache Flink-specific alarms for KPU utilization and throughput
- Monitor key performance metrics through Managed Service for Apache Flink console and CloudWatch
- Implement application health checks that integrate with Managed Service for Apache Flink monitoring

### Managed Service for Apache Flink-Optimized Application Structure

#### Best Practice: Clean Application Architecture

```java
public class MSFStreamingApp {
    public static void main(String[] args) throws Exception {
        StreamExecutionEnvironment env = StreamExecutionEnvironment.getExecutionEnvironment();
        
        // NO checkpoint configuration in code - managed by MSF service
        DataStream<Event> events = env
            .fromSource(createKinesisSource(), WatermarkStrategy.forMonotonousTimestamps(), "kinesis-source")
            .uid("kinesis-source-uid");
        
        DataStream<ProcessedEvent> processed = events
            .keyBy(Event::getKey)
            .process(new EventProcessor())
            .name("event-processor")
            .uid("event-processor-uid");
        
        processed.sinkTo(createS3Sink())
            .name("s3-sink")
            .uid("s3-sink-uid");
        
        env.execute("MSF Streaming Application");
    }
}
```

`fromSource()`/`sinkTo()` are the recommended APIs for both Flink 1.20 and 2.2. The legacy `addSource()`/`addSink()` APIs are deprecated in 1.20 and removed in 2.x. See `environment-setup.md` for docker-compose.yml setup.

#### Anti-Pattern: Monolithic Processing

```java
// AVOID: Single large operator doing everything
events.map(event -> {
    // Complex transformation logic
    // Multiple business rules
    // Data enrichment
    // Validation
    // Formatting
    return processedEvent;
}); // Hard to debug, scale, and maintain
```

For state management best practices (efficient state usage, TTL, state types, Managed Service for Apache Flink state management), see [state-management.md](state-management.md).

For serialization best practices (performance hierarchy, POJO, Tuple, Avro, Protobuf, Kryo avoidance, state serialization, anti-patterns), see [serialization-guide.md](serialization-guide.md).

## Performance Best Practices

### KPU-Based Resource Configuration

#### Best Practice: Managed Service for Apache Flink KPU-Optimized Applications

```java
// Application code should be KPU-agnostic
StreamExecutionEnvironment env = StreamExecutionEnvironment.getExecutionEnvironment();

// DO NOT set parallelism in application code for Managed Service for Apache Flink deployment
// Managed Service for Apache Flink manages parallelism through KPU configuration

// For local Docker development only:
if (isLocalDevelopment()) {
    int localParallelism = Math.max(1, Runtime.getRuntime().availableProcessors() - 1);
    env.setParallelism(localParallelism);
}

// Set operator-specific parallelism only when business logic or infrastructure requires it
// E.g. you may set parallelism on a Kafka source operator to be equal to number of partitions, if the overall app parallelism is higher than the number of partitions (lower parallelism for source, but enable high parallelism for processing operators with keyBy or similar operators that spread load)
dataStream
    .keyBy(Event::getPartitionKey)
    .process(new HeavyProcessor())
    // Only set if this operator specifically needs different parallelism
    .setParallelism(5);
```

### Error Handling and Recovery in Managed Service for Apache Flink

#### Best Practice: Use Side Outputs for dead letter queues for bad data handling and dependency failures

```java
public class RobustProcessor extends ProcessFunction<Event, ProcessedEvent> {
    public static final OutputTag<Event> DEAD_LETTER_TAG =
            new OutputTag<Event>("dead-letter") {};
    private transient Counter errorCounter;
    
    @Override
    public void open(OpenContext openContext) throws Exception {
        errorCounter = getRuntimeContext().getMetricGroup().counter("processing_errors");
    }
    
    @Override
    public void processElement(Event event, Context ctx, Collector<ProcessedEvent> out) {
        try {
            // Validate input
            if (!isValidEvent(event)) {
                LOG.warn("Invalid event received: {}", event);
                ctx.output(DEAD_LETTER_TAG, event);
                return;
            }
            
            ProcessedEvent result = processEvent(event);
            out.collect(result);
            
        } catch (TransientException e) {
            // Let Managed Service for Apache Flink handle transient errors through restart strategy
            LOG.warn("Transient error processing event {}, Managed Service for Apache Flink will retry", event.getId(), e);
            throw e; // Managed Service for Apache Flink restart strategy handles this
            
        } catch (Exception e) {
            // Handle permanent errors gracefully
            LOG.error("Permanent error processing event {}", event.getId(), e);
            errorCounter.inc();
            ctx.output(DEAD_LETTER_TAG, event);
            // Don't throw - continue processing other events
        }
    }
}
```

## Configuration Optimization

**Critical Principle**: Managed Service for Apache Flink applications must clearly separate local development configuration from Managed Service for Apache Flink service-level configuration. Managed Service for Apache Flink manages all advance Flink runtime parameters (i.e. `FLINK_PROPERTIES` configs such as `state.backend` and `restart-strategy`) and should not be a consideration for developers outside of local development.

- **Local Docker Configuration**: Used only for Kiro-based development with Docker containers
- **Managed Service for Apache Flink Service Configuration**: Managed through Managed Service for Apache Flink console and service APIs, not in application code
- **Application Code**: Should be environment-agnostic and avoid hardcoded infrastructure settings
- **Advanced Configs**: Configurations for the Flink runtime are managed by Managed Service for Apache Flink and should not be a consideration for developers outside of local development - some configurations can be updated via AWS Support Case requests (such as `state.backend` for RocksDB vs. HashMap) but have significant considerations to weigh for application health and stability and in general should be managed by Managed Service for Apache Flink

### Environment-Specific Configuration Management

#### Best Practice: Clean Configuration Separation

```java
import com.amazonaws.services.kinesisanalytics.runtime.KinesisAnalyticsRuntime;

public class FlinkStreamingJob {
    private static final String LOCAL_PROPS = "flink-application-properties-dev.json";
    
    private static boolean isLocal(StreamExecutionEnvironment env) {
        String runtime = System.getenv("RUNTIME_ENVIRONMENT");
        return env instanceof LocalStreamEnvironment || "local".equalsIgnoreCase(runtime);
    }

    private static Map<String, Properties> loadApplicationProperties(StreamExecutionEnvironment env) throws IOException {
        if (isLocal(env)) {
            InputStream input = FlinkStreamingJob.class.getClassLoader().getResourceAsStream(LOCAL_PROPS);
            if (input == null) throw new IOException("Unable to find " + LOCAL_PROPS);
            java.nio.file.Path tempFile = java.nio.file.Files.createTempFile("flink-app-props", ".json");
            java.nio.file.Files.copy(input, tempFile, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            input.close();
            tempFile.toFile().deleteOnExit();
            return KinesisAnalyticsRuntime.getApplicationProperties(tempFile.toString());
        } else {
            return KinesisAnalyticsRuntime.getApplicationProperties();
        }
    }

    public static void main(String[] args) throws Exception {
        final StreamExecutionEnvironment env = StreamExecutionEnvironment.getExecutionEnvironment();
        if (isLocal(env)) {
            env.enableCheckpointing(10_000);
            env.setParallelism(3);
        }
        final Map<String, Properties> applicationProperties = loadApplicationProperties(env);
    }
}
```

In Managed Service for Apache Flink, application properties are configured at the Application level with property groups (same structure as the local JSON file).

## Anti-Patterns to Avoid

### Deployment Anti-Patterns

1. **Single-Stack IaC Without Pre-Uploaded JAR**
   The MSF application resource validates that the JAR exists in S3 at creation time. A single CloudFormation stack (or equivalent) that creates the S3 bucket and the MSF application together will fail because the JAR hasn't been uploaded yet. Always use a two-phase deployment: deploy infrastructure first, upload the JAR, then deploy the application resource. See [IaC and Deployment Guide](iac-and-deployment.md) for patterns.

### Configuration Anti-Patterns

1. **Hardcoded Infrastructure Configuration in Application Code**
2. **App-Level Savepoint Management**

### Performance Anti-Patterns

1. **KPU-Unaware Parallelism Configuration**

   ```java
   // AVOID: Fixed parallelism that doesn't align with KPU model
   env.setParallelism(7); // Doesn't align with KPU scaling
   dataStream.setParallelism(13); // Arbitrary parallelism, only set when operator requires custom parallelism
   ```

2. **Excessive Rebalancing**

   ```java
   // AVOID: Unnecessary rebalance operations
   stream.rebalance().map(...).rebalance().filter(...);
   // Breaks Managed Service for Apache Flink's automatic load balancing
   ```

3. **Blocking Operations in Processing Functions**

   ```java
   // AVOID: Synchronous external calls that block KPU resources, use Async functions instead
   public void processElement(Event event, Context ctx, Collector<Result> out) {
       Result result = externalService.blockingCall(event); // Blocks KPU
       out.collect(result);
   }
   ```

4. **Large State Objects Without TTL**

   ```java
   // AVOID: Unbounded state growth
   private transient ListState<Event> allEvents; // Can exhaust KPU memory
   private transient MapState<String, LargeObject> cache; // No TTL configured
   ```
