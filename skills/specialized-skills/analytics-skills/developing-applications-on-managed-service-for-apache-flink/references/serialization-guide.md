# Serialization Best Practices

## Overview

This guide covers serialization best practices for Managed Service for Apache Flink applications, including the performance hierarchy of serializer types, POJO and Tuple usage, Avro and Protobuf integration, Kryo avoidance, state serialization considerations, and common anti-patterns.

For general development patterns and application structure, see [best-practices.md](best-practices.md). For state management guidance, see [state-management.md](state-management.md).

Code examples in this guide use Flink 2.2 APIs by default, which are also compatible with Flink 1.20 unless noted otherwise. See `flink-2x-migration.md` for the complete migration reference.

## Performance Hierarchy: Choose the Right Serializer

Flink serialization performance (fastest to slowest):

1. **Flink Tuples/Rows** - Fastest (direct field access, no reflection)
2. **POJOs** - Fast (~30% slower than tuples, supports schema evolution)
3. **Protobuf** - Good performance (~30% slower than POJOs)
4. **Avro Specific** - Moderate (~50% slower than POJOs)
5. **Avro Generic/Thrift** - Slower (~70% slower than POJOs)
6. **Kryo** - Avoid (50%+ performance penalty). Kryo registration convenience methods are removed from `StreamExecutionEnvironment` in Flink 2.x; avoid Kryo entirely.

## POJO Serialization for Managed Service for Apache Flink

```java
// Recommended: Flink POJO for optimal performance with schema evolution
public class OptimizedEvent {
    // All fields must be public or have public getters/setters
    public String eventId;
    public long timestamp;
    public String userId;
    public EventType type;
    
    // Required: public no-argument constructor
    public OptimizedEvent() {}
    
    public OptimizedEvent(String eventId, long timestamp, String userId, EventType type) {
        this.eventId = eventId;
        this.timestamp = timestamp;
        this.userId = userId;
        this.type = type;
    }
}

// Enum types work well with POJO serialization
public enum EventType {
    USER_ACTION, SYSTEM_EVENT, ERROR_EVENT
}
```

## Tuple Types for Maximum Performance

```java
// Use when performance is critical and schema evolution is not needed
DataStream<Tuple4<String, Long, String, Integer>> events = source
    .map(event -> Tuple4.of(event.getId(), event.getTimestamp(), 
                           event.getUserId(), event.getCount()));

// Access fields by position (f0, f1, f2, f3)
events.keyBy(tuple -> tuple.f2) // Key by userId (f2)
      .process(new TupleProcessor());
```

## Avro for External Integration

```java
// Use Avro when integrating with external systems or when advanced schema evolution is needed
public class AvroEventProcessor extends ProcessFunction<SpecificRecordBase, ProcessedEvent> {
    
    @Override
    public void processElement(SpecificRecordBase avroEvent, Context ctx, 
                              Collector<ProcessedEvent> out) {
        if (avroEvent instanceof UserEvent) {
            UserEvent userEvent = (UserEvent) avroEvent;
            ProcessedEvent result = new ProcessedEvent();
            result.setUserId(userEvent.getUserId().toString());
            result.setTimestamp(userEvent.getTimestamp());
            out.collect(result);
        }
    }
}

// Configure Avro serialization
// Note: enableForceAvro() is available in Flink 1.20 but removed in 2.x.
// For Flink 2.2, use AvroTypeInfo explicitly in state descriptors instead.
StreamExecutionEnvironment env = StreamExecutionEnvironment.getExecutionEnvironment();
// Flink 1.20 only:
// env.getConfig().enableForceAvro();
```

## Protobuf Integration

The recommended approach for Protobuf is to convert Protobuf messages to Flink POJOs at the ingestion boundary. This avoids Kryo entirely, giving you fast serialization, schema evolution support, and state compatibility across Flink major versions.

```java
// Recommended: Convert Protobuf to POJO at the boundary, avoiding Kryo entirely
DataStream<MyEvent> events = protobufSource
    .map(proto -> new MyEvent(
        proto.getEventId(),
        proto.getTimestamp(),
        proto.getUserId()));
// MyEvent is a Flink POJO (public fields + no-arg constructor) — fast serialization, schema evolution, no Kryo
```

> **Legacy note — not recommended for new applications:** If you must use Protobuf objects directly in state, you can register them with Kryo via `env.getConfig()`. However, Kryo has a 50%+ performance penalty and Kryo-serialized state does not migrate from Flink 1.x to 2.x. Convenience registration methods on `StreamExecutionEnvironment` are removed in Flink 2.x.
>
> ```java
> // Not recommended — use POJO conversion instead:
> env.getConfig().registerTypeWithKryoSerializer(
>     MyProtobufMessage.class,
>     ProtobufSerializer.class
> );
> ```

## Avoiding Kryo Fallbacks

### Why Kryo Fallback Matters on MSF

If Flink can't recognize a type as a POJO/Tuple/Avro/Protobuf, it silently falls back to Kryo. On MSF this has three consequences worth treating as blockers, not warnings:

- **~50% performance penalty** vs. POJO serialization, plus larger serialized objects on the wire and in state. On a high-throughput keyed pipeline this dominates per-record cost.
- **Larger checkpoint and shuffle bytes.** Inflated checkpoint size lengthens the checkpoint window and pushes more data across cross-AZ network paths inside MSF.
- **Kryo-serialized state does not migrate from Flink 1.x to 2.x.** This is a hard blocker for in-place version upgrades — see [flink-2x-migration.md](flink-2x-migration.md) for the migration path. Plan to eliminate Kryo *before* the 1→2 upgrade, not after.

### Fail Fast in Development

```java
// Monitor for Kryo fallbacks in logs - these indicate performance issues
// Log message: "Class ... cannot be used as a POJO type because not all fields are valid POJO fields"

// To detect Kryo usage, disable it temporarily during development
StreamExecutionEnvironment env = StreamExecutionEnvironment.getExecutionEnvironment();
env.getConfig().disableGenericTypes(); // Throws exception if Kryo would be used
// This will fail with: "Generic types have been disabled in the ExecutionConfig"
```

Run with `disableGenericTypes()` enabled locally as part of every PR build so Kryo fallbacks fail the build, not production.

## Last Resort: Kryo Type Registration

> **Warning:** Prefer converting to Flink POJOs or Tuples instead of registering Kryo serializers. Kryo-serialized state does not migrate across Flink major versions. Convenience registration methods on `StreamExecutionEnvironment` are removed in Flink 2.x — use `env.getConfig()` methods instead. Use this only when migrating away from Kryo is not yet feasible.

```java
// Last resort — register frequently used types to avoid class name serialization overhead IF you use Kryo
// In Flink 2.x, use env.getConfig() methods (env-level convenience methods are removed)
StreamExecutionEnvironment env = StreamExecutionEnvironment.getExecutionEnvironment();

env.getConfig().registerKryoType(CustomEvent.class);
env.getConfig().registerKryoType(ProcessingResult.class);

env.getConfig().registerTypeWithKryoSerializer(
    ComplexObject.class, 
    CustomKryoSerializer.class
);
```

## State Serialization Considerations

```java
// For state objects, prioritize schema evolution support
public class StatefulProcessor extends KeyedProcessFunction<String, Event, Result> {
    
    // Use POJO or Avro for state that needs to evolve
    private transient ValueState<EventAggregate> aggregateState; // POJO - good performance + evolution
    
    // Use primitive types for simple state
    private transient ValueState<Long> counterState; // Primitive - fastest
    
    @Override
    public void open(OpenContext openContext) throws Exception {
        // POJO state descriptor - supports schema evolution
        ValueStateDescriptor<EventAggregate> aggregateDescriptor = 
            new ValueStateDescriptor<>("aggregate", EventAggregate.class);
        aggregateState = getRuntimeContext().getState(aggregateDescriptor);
        
        // Primitive state descriptor - fastest serialization
        ValueStateDescriptor<Long> counterDescriptor = 
            new ValueStateDescriptor<>("counter", Long.class);
        counterState = getRuntimeContext().getState(counterDescriptor);
    }
}
```

## Anti-Patterns: Serialization Performance Killers

```java
// AVOID: Default Java Serialization (extremely slow)
public class SlowEvent implements Serializable {
    // Java serialization is 10x+ slower than POJO serialization
}

// AVOID: Complex nested objects without proper POJO structure
public class BadEvent {
    private Map<String, Object> data; // Generic Object causes Kryo fallback
    private List<SomeInterface> items; // Interface types cause Kryo fallback
}

// AVOID: Missing no-argument constructor (causes Kryo fallback)
public class InvalidPOJO {
    public String field;
    
    // Missing no-arg constructor - will use Kryo instead of POJO serializer
    public InvalidPOJO(String field) {
        this.field = field;
    }
}

// AVOID: Private fields without getters/setters (causes Kryo fallback)
public class AlmostPOJO {
    private String secretField; // No getter/setter - not a valid POJO field
    public String publicField;   // This is fine
    
    public AlmostPOJO() {} // Constructor is correct
}
```
