# Concurrency Safety for LMI

LMI runs multiple invocations concurrently in the same execution environment. The concurrency model differs by runtime — some require thread safety, others provide process isolation.

## Code Review Checklist

When reviewing a function for LMI readiness, check each item:

- [ ] No shared `/tmp` paths (use request ID in filenames, clean up after — shared across ALL runtimes)
- [ ] Database connections use pools (initialized outside handler, not per-invocation)
- [ ] SDK clients outside handler (module-level singletons are fine — they are thread-safe)
- [ ] Logging includes request ID (for tracing concurrent requests)
- [ ] **Node.js/Java/.NET only:** No global/static mutable variables (use immutable or request-local state)
- [ ] **Node.js/Java/.NET only:** Thread-safe libraries only (check DB drivers, HTTP clients, caching libs)
- [ ] **Node.js/Java/.NET only:** No request state in global scope (use AsyncLocalStorage, ThreadLocal, `AsyncLocal<T>`)
- [ ] **Node.js/Java/.NET only:** No environment variable mutation during requests
- [ ] **Python only:** Memory budget accounts for per-process multiplication (memory × concurrency)

## Runtime-Specific Guidance

### Python (Process-Based Isolation)

Python uses **multiple independent processes**, each with its own interpreter and memory space. Global variables, module-level caches, and singleton objects are duplicated per process, not shared. If a function works on standard Lambda today, it works on LMI without code changes related to shared state.

**Key concerns:**

- Memory consumption: total footprint ≈ per-process memory × concurrency. A 200 MB function with 16 concurrent processes can consume 3+ GB.
- `/tmp` filesystem is shared across all processes — use `context.aws_request_id` in filenames
- Each process needs its own connection pool — size pools per-process, not globally
- Prefer 4:1 or 8:1 memory-to-vCPU ratio to accommodate memory multiplication
- Monitor `MemoryUtilization` metric and adjust ratio if needed

**Safe patterns (no locking needed):**

- Module-level mutable globals (isolated per process)
- Module-level SDK clients and caches
- `os.environ` reads

### Node.js (Worker Threads + Async/Await)

Uses worker threads combined with async/await event loops. The handler and global state are **shared across concurrent invocations within a worker thread**.

The `await` keyword yields control to the event loop, which may execute another invocation that overwrites shared state before the first resumes.

**Key concerns:**

- Use `AsyncLocalStorage` from `node:async_hooks` for request context
- Keep mutable state within handler local scope
- Initialize SDK clients and DB pools at module level (they are thread-safe)
- Avoid module-level mutable state (`let count = 0` is a race condition)
- Callback-based handlers are NOT supported on Node.js 22 — use async handlers

### Java (OS Threads)

Uses OS-level threads. Lambda loads the handler class once and invokes `handleRequest` from multiple threads simultaneously.

**Key concerns:**

- Use immutable objects and thread-safe collections (`ConcurrentHashMap`, `Collections.synchronizedList`)
- Initialize SDK clients and connection pools in constructor or static block
- Avoid mutable `static` fields
- Use `ThreadLocal<T>` for request-specific state
- Use HikariCP or similar for connection pooling (AWS SDK for Java 2.x clients are thread-safe)

### .NET (Task-Based Concurrency)

Uses a single process with .NET Tasks (same model as ASP.NET Core). The handler object is shared across all Tasks.

**Key concerns:**

- Use `AsyncLocal<T>` for request-scoped data
- Inject scoped services via DI container
- Initialize `HttpClient` and SDK clients as singletons
- Use `ConcurrentDictionary<TKey, TValue>` and `SemaphoreSlim` for thread-safe access
- Invocation timeouts are NOT enforced by the runtime — use `ILambdaContext.RemainingTime`

## Common Anti-Patterns

| Anti-pattern | Affected Runtimes | Risk | Fix |
|-------------|-------------------|------|-----|
| New DB connection per invocation | All | Exhausts connection limits | Module-level connection pool |
| Hardcoded `/tmp` paths | All | File conflicts across processes | Use `aws_request_id` in path |
| Logging without request ID | All | Unreadable interleaved logs | Include `aws_request_id` |
| Mutable module-level state | Node.js, Java, .NET | Race condition / state corruption | Request-local scope or concurrent collections |
| Setting env vars during request | Node.js, Java, .NET | Race condition | Pass state via parameters |
| Assuming sequential execution | Node.js, Java, .NET | State corruption | Each invocation must be self-contained |
| Ignoring memory multiplication | Python | OOM at high concurrency | Account for per-process × concurrency |

## Powertools for AWS Lambda Compatibility

Powertools handles multi-concurrency transparently. No code changes needed.

| Runtime | Package | Minimum Version |
|---------|---------|-----------------|
| Python | Powertools for AWS Lambda (Python) | 3.23.0 |
| TypeScript | Powertools for AWS Lambda (TypeScript) | 2.29.0 |
| Java | Powertools for AWS Lambda (Java) | 2.8.0 |
| .NET | Powertools for AWS Lambda (.NET) | 3.1.0 |

AWS SDK and X-Ray minimum versions:

| Runtime | AWS SDK minimum | X-Ray SDK minimum |
|---------|----------------|-------------------|
| Node.js | AWS SDK for JavaScript v3 (3.933.0) | 3.12.0 |
| Java | AWS SDK for Java 2.0 (2.34.0) | 2.20.0 |
| .NET | AWSSDK.Core (4.0.0.32) | AWSXRayRecorder.Core (2.16.0) |
