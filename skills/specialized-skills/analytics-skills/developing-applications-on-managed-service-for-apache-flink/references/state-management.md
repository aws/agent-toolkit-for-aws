# State Management Best Practices

## Overview

This guide covers state management best practices for Managed Service for Apache Flink applications, including efficient state usage, TTL configuration, state type selection, and Managed Service for Apache Flink-specific state management considerations.

For general development patterns and application structure, see [best-practices.md](best-practices.md). For serialization guidance, see [serialization-guide.md](serialization-guide.md).

Code examples in this guide use Flink 2.2 APIs by default, which are also compatible with Flink 1.20 unless noted otherwise. See `flink-2x-migration.md` for the complete migration reference.

## Efficient State Usage with Managed Service for Apache Flink

- Estimate state size ahead of time to ensure state will remain bounded over time.
- Enable state TTL to ensure state gets cleaned up automatically if not cleaned up manually.
- Use the correct state type for each use case, and perform updates to state in performant way (e.g. make updates to a map key, rather than replacing the entire map).
- AVOID: Storing large objects or unbounded collections in state

### Pick the Right State Type — `MapState` vs `ValueState<Map>`

Use `MapState<K, V>` whenever you need per-key updates inside a logical map. Storing a `Map<K, V>` inside `ValueState<Map<K, V>>` and reading-mutating-writing it on every event is `O(map size)` per access — RocksDB has to deserialize every entry, your code mutates one, and the whole map gets re-serialized and written back. `MapState` is `O(1)` per `put`/`get`/`remove`: each map entry maps to its own RocksDB key, so only the touched entry is read or written.

There is also a state-migration consequence specific to MSF: nested generic collections inside `ValueState` (e.g. `ValueState<Map<String, MyType>>`) typically fall back to Kryo serialization, and **Kryo-serialized state does not migrate from Flink 1.x to 2.x.** `MapState` uses a dedicated `MapSerializer` that does carry across the upgrade. See [serialization-guide.md](serialization-guide.md) for the wider Kryo guidance and [flink-2x-migration.md](flink-2x-migration.md) for the migration impact.

```java
public class OptimizedKeyedProcessor extends KeyedProcessFunction<String, Event, Result> {
    
    // Use appropriate state types
    private transient ValueState<EventAggregate> aggregateState;
    
    @Override
    public void open(OpenContext openContext) throws Exception {
        ValueStateDescriptor<EventAggregate> aggregateDescriptor = 
            new ValueStateDescriptor<>("aggregate", EventAggregate.class);
        
        // TTL configuration - application-level concern
        aggregateDescriptor.enableTimeToLive(StateTtlConfig.newBuilder(Duration.ofHours(24))
            .setUpdateType(StateTtlConfig.UpdateType.OnCreateAndWrite)
            .setStateVisibility(StateTtlConfig.StateVisibility.NeverReturnExpired)
            .build());
        
        aggregateState = getRuntimeContext().getState(aggregateDescriptor);
    }
    
    @Override
    public void processElement(Event event, Context ctx, Collector<Result> out) throws Exception {
        // Efficient state access patterns
        EventAggregate current = aggregateState.value();
        if (current == null) {
            current = new EventAggregate();
        }
        
        // Update state efficiently
        current.update(event);
        aggregateState.update(current);
        
        // Use timers for handling events that occur after the input event - e.g. in this case we want to trigger the output an hour after the input occurs
        ctx.timerService().registerEventTimeTimer(event.getTimestamp() + 3600000); // 1 hour
    }

    @Override
    public void onTimer(long timestamp, OnTimerContext ctx, Collector<Result> out) throws Exception {
        // Handle timer firing - cleanup or emit final results
        EventAggregate current = aggregateState.value();
        if (current != null) {
            // Emit final result or perform cleanup
            out.collect(new Result(ctx.getCurrentKey(), current.getFinalValue()));
            // Clear state after processing to re-initialize if needed
            aggregateState.clear();
        }
    }
}
```

## Managed Service for Apache Flink State Management

Managed Service for Apache Flink service handles:

- State backend configuration (RocksDB with S3 for checkpoints/savepoints)
- Checkpoint storage and retention
- Savepoint management through console
- State size monitoring and alerting
Application code should NOT configure these aspects
