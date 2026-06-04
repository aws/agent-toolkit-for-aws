# Replay Model Rules - CRITICAL

The replay model is the foundation of durable functions. Violations cause subtle, hard-to-debug issues. **Read this carefully.**

## How Replay Works

Durable functions use a "checkpoint and replay" execution model:

1. Code runs from the beginning on every invocation
2. Steps that already completed return their checkpointed results WITHOUT re-executing
3. Code OUTSIDE steps executes again on every replay
4. New steps execute when reached

**Example:**

```typescript
// First execution: Runs lines 1-5
// After wait: Runs lines 1-5 again (line 2 returns cached result)
const data = await context.step('fetch', async () => fetchAPI());  // Line 2: Executes once, cached
await context.wait({ seconds: 60 });                                // Line 3: Waits
const result = await context.step('process', async () => process(data)); // Line 5: Executes after wait
```

## Rule 1: Deterministic Code Outside Steps

**ALL code outside steps MUST produce the same result on every replay.**

### ❌ WRONG - Non-Deterministic Outside Steps

**TypeScript:**

```typescript
// These values change on each replay!
const id = uuid.v4();                    // Different UUID each time
const timestamp = Date.now();            // Different timestamp each time
const random = Math.random();            // Different random number
const now = new Date();                  // Different date each time

await context.step('save', async () => saveData({ id, timestamp }));
```

**Python:**

```python
# These values change on each replay!
id = str(uuid.uuid4())                   # Different UUID each time
timestamp = time.time()                  # Different timestamp each time
random_val = random.random()             # Different random number
now = datetime.now()                     # Different datetime each time

context.step(lambda _: save_data({"id": id}), name='save')
```

### ✅ CORRECT - Non-Deterministic Inside Steps

**TypeScript:**

```typescript
const id = await context.step('generate-id', async () => uuid.v4());
const timestamp = await context.step('get-time', async () => Date.now());
const random = await context.step('random', async () => Math.random());
const now = await context.step('get-date', async () => new Date());

await context.step('save', async () => saveData({ id, timestamp }));
```

**Python:**

```python
id = context.step(lambda _: str(uuid.uuid4()), name='generate-id')
timestamp = context.step(lambda _: time.time(), name='get-time')
random_val = context.step(lambda _: random.random(), name='random')
now = context.step(lambda _: datetime.now(), name='get-date')

context.step(lambda _: save_data({"id": id}), name='save')
```

### Must Be In Steps

- `Date.now()`, `new Date()`, `time.time()`, `datetime.now()`
- `Math.random()`, `random.random()`
- UUID generation (`uuid.v4()`, `uuid.uuid4()`)
- API calls, HTTP requests
- Database queries
- File system operations
- Environment variable reads (if they can change)
- Any external system interaction

## Rule 2: No Nested Durable Operations

**You CANNOT call durable operations inside a step function.**

### ❌ WRONG - Nested Operations

**TypeScript:**

```typescript
await context.step('process', async () => {
  await context.wait({ seconds: 1 });      // ERROR!
  await context.step(async () => ...);     // ERROR!
  await context.invoke('other-fn', ...);   // ERROR!
  return result;
});
```

**Python:**

```python
@durable_step
def process(step_ctx: StepContext):
    context.wait(duration=Duration.from_seconds(1))  # ERROR!
    context.step(lambda _: ..., name='nested')       # ERROR!
    return result

context.step(process())
```

### ✅ CORRECT - Use Child Context

**TypeScript:**

```typescript
await context.runInChildContext('process', async (childCtx) => {
  await childCtx.wait({ seconds: 1 });
  const step1 = await childCtx.step('validate', async () => validate());
  const step2 = await childCtx.step('process', async () => process(step1));
  return step2;
});
```

**Python:**

```python
# Note: validate and process are decorated with @durable_step
def process_child(child_ctx: DurableContext):
    child_ctx.wait(duration=Duration.from_seconds(1))
    step1 = child_ctx.step(validate())
    step2 = child_ctx.step(process(step1))
    return step2

context.run_in_child_context(func=process_child, name='process')
```

## Rule 3: Closure Mutations Are Lost

**Variables mutated inside steps are NOT preserved across replays.**

### ❌ WRONG - Lost Mutations

**TypeScript:**

```typescript
let counter = 0;
await context.step('increment', async () => {
  counter++;  // This mutation is lost!
});
console.log(counter);  // Always 0 on replay!
```

**Python:**

```python
counter = 0
@durable_step
def increment(step_ctx: StepContext):
    nonlocal counter
    counter += 1  # This mutation is lost!

context.step(increment())
print(counter)  # Always 0 on replay!
```

### ✅ CORRECT - Return Values

**TypeScript:**

```typescript
let counter = 0;
counter = await context.step('increment', async () => counter + 1);
console.log(counter);  // Correct value
```

**Python:**

```python
counter = 0
counter = context.step(lambda _: counter + 1, name='increment')
print(counter)  # Correct value
```

## Rule 4: Side Effects Outside Steps Repeat

**Side effects outside steps happen on EVERY replay.**

### ❌ WRONG - Repeated Side Effects

**TypeScript:**

```typescript
console.log('Starting process');     // Logs multiple times!
await sendEmail(user.email);         // Sends multiple emails!
await updateDatabase(data);          // Updates multiple times!

await context.step('process', async () => process());
```

**Python:**

```python
print('Starting process')            # Prints multiple times!
send_email(user.email)               # Sends multiple emails!
update_database(data)                # Updates multiple times!

context.step(lambda _: process(), name='process')
```

### ✅ CORRECT - Side Effects In Steps

**TypeScript:**

```typescript
context.logger.info('Starting process');  // Deduplicated automatically
await context.step('send-email', async () => sendEmail(user.email));
await context.step('update-db', async () => updateDatabase(data));
await context.step('process', async () => process());
```

**Python:**

```python
# Note: Functions are decorated with @durable_step
context.logger.info('Starting process')  # Deduplicated automatically
context.step(send_email(user.email))
context.step(update_database(data))
context.step(process())
```

### Exception: context.logger

`context.logger` is replay-aware and safe to use anywhere. It automatically deduplicates logs across replays.

## Common Pitfalls

### Pitfall 1: Reading Environment Variables

```typescript
// ❌ WRONG if env vars can change
const apiKey = process.env.API_KEY;
await context.step('call-api', async () => callAPI(apiKey));

// ✅ CORRECT
const apiKey = await context.step('get-key', async () => process.env.API_KEY);
await context.step('call-api', async () => callAPI(apiKey));
```

### Pitfall 2: Array/Object Mutations

```typescript
// ❌ WRONG
const items = [];
await context.step('add-item', async () => {
  items.push(newItem);  // Lost on replay
});

// ✅ CORRECT
let items = [];
items = await context.step('add-item', async () => [...items, newItem]);
```

### Pitfall 3: Conditional Logic with Non-Deterministic Values

```typescript
// ❌ WRONG
if (Math.random() > 0.5) {  // Different on each replay!
  await context.step('path-a', async () => ...);
} else {
  await context.step('path-b', async () => ...);
}

// ✅ CORRECT
const shouldTakePathA = await context.step('decide', async () => Math.random() > 0.5);
if (shouldTakePathA) {
  await context.step('path-a', async () => ...);
} else {
  await context.step('path-b', async () => ...);
}
```

## Debugging Replay Issues

If you see inconsistent behavior:

1. **Check for non-deterministic code outside steps**
2. **Verify no nested durable operations**
3. **Look for closure mutations**
4. **Search for side effects outside steps**
5. **Use `context.logger` to trace execution flow**

## Testing Replay Behavior

Always test with multiple invocations to simulate replay:

```typescript
const runner = new LocalDurableTestRunner({ handlerFunction: handler });
const execution = await runner.run({ payload: { test: true } });

// Verify operations executed correctly
const step1 = runner.getOperation('step-name');
expect(step1.getStatus()).toBe(OperationStatus.SUCCEEDED);
```
