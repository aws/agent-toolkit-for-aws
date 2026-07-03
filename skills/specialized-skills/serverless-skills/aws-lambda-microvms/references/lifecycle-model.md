# Lifecycle model

Two state machines (image and MicroVM) plus the lifecycle hook contract your application can optionally implement.

## Image state machine

Image-level state:

```
CREATING ──▶ CREATED ──▶ DELETING
```

Version-level state (`state` + `status`):

```
state: PENDING ──▶ IN_PROGRESS ──▶ SUCCESSFUL
                              └─▶ FAILED

status: ACTIVE | INACTIVE
```

A single image version can produce multiple `Build` records — one per `(architecture, chipset, chipsetGeneration)`. Each build has its own `buildState`: `PENDING` → `IN_PROGRESS` → `SUCCESSFUL` | `FAILED`. List with `list-microvm-image-builds`.

`UpdateMicrovmImageVersion` switches a version's `status` between `ACTIVE` and `INACTIVE` — `RunMicrovm` will only resolve `ACTIVE` versions when no explicit `imageVersion` is supplied.

## MicroVM state machine

```
PENDING
   │
   ▼
RUNNING ◀──── (auto-resume on ingress, or ResumeMicrovm)
   │  ▲
   ▼  │
SUSPENDING ──▶ SUSPENDED
                  │
                  ▼ (after suspendedDurationSeconds, or TerminateMicrovm)
              TERMINATING ──▶ TERMINATED
```

Triggers:

- `RunMicrovm` → `PENDING` → `RUNNING`.
- Idle for `maxIdleDurationSeconds` of no proxy traffic → `SUSPENDING` → `SUSPENDED`. Or call `SuspendMicrovm`.
- Ingress traffic on the endpoint with `autoResumeEnabled: true`, or `ResumeMicrovm` → `RUNNING`.
- `SUSPENDED` for `suspendedDurationSeconds` → terminated.
- Maximum lifetime `maximumDurationInSeconds` (cap 28,800 s = 8 hr) reached → terminated.
- `TerminateMicrovm` from anywhere.

Idle is **measured by traffic through the proxy endpoint**. If your app does outbound work but receives no inbound traffic, the platform will count it as idle. For background workers, set high `maxIdleDurationSeconds` or disable auto-suspend by omitting `idlePolicy` in the request.

## Lifecycle hooks

Your application can implement HTTP endpoints that Lambda invokes at lifecycle transitions. Hooks are **opt-in per image** via the `--hooks` parameter. You must specify the `port` your hooks listen on (commonly `9000`).

### Image build hooks

| Hook | Path | When invoked | Timeout field | Use it for |
|---|---|---|---|---|
| **`/ready`** | `POST /aws/lambda-microvms/runtime/v1/ready` | During image build, before snapshot capture | `readyTimeoutInSeconds` (1–3600) | Confirm app initialized; fail the build if app is broken |
| **`/validate`** | `POST /aws/lambda-microvms/runtime/v1/validate` | After build, on a test MicroVM run from the snapshot | `validateTimeoutInSeconds` (1–3600) | End-to-end smoke test of the snapshot |

Implementing image build hooks is recommended for performance — they ensure your application is fully initialized before the snapshot is captured, resulting in faster runs.

### MicroVM hooks

| Hook | Path | When invoked | Timeout field | Use it for |
|---|---|---|---|---|
| **`/run`** | `POST /aws/lambda-microvms/runtime/v1/run` | Once, immediately after a MicroVM is run (resumed from snapshot) | `runTimeoutInSeconds` (1–60) | Create per-VM unique state, fetch secrets, register with discovery. **Should be quick** — not for long-running work |
| **`/resume`** | `POST /aws/lambda-microvms/runtime/v1/resume` | After `SUSPENDED` → `RUNNING` | `resumeTimeoutInSeconds` (1–60) | Re-establish connections, generate new randomness if your application relies on non-CSPRNGs |
| **`/suspend`** | `POST /aws/lambda-microvms/runtime/v1/suspend` | Just before `RUNNING` → `SUSPENDED` | `suspendTimeoutInSeconds` (1–60) | Return 200 only when the app is ready to be suspended. Customer decides the strategy: wait for in-flight work to drain within the timeout, or return immediately |
| **`/terminate`** | `POST /aws/lambda-microvms/runtime/v1/terminate` | Just before termination | `terminateTimeoutInSeconds` (1–60) | Flush logs, persist state, deregister |

> If you use microVM hooks, you must implement the `/ready` microVM image hook. This ensures your application has booted and can receive hook events.
>
> Always set explicit timeout values in `--hooks` when creating the image — especially for `/ready` (init) and `/run`/`/resume` (any per-VM init work).

### Configuring hooks (image creation)

```bash
--hooks '{
  "port": 9000,
  "microvmImageHooks": {
    "ready": "ENABLED",
    "readyTimeoutInSeconds": 60,
    "validate": "ENABLED",
    "validateTimeoutInSeconds": 10
  },
  "microvmHooks": {
    "run": "ENABLED",
    "runTimeoutInSeconds": 2,
    "resume": "ENABLED",
    "resumeTimeoutInSeconds": 2,
    "suspend": "ENABLED",
    "suspendTimeoutInSeconds": 5,
    "terminate": "ENABLED",
    "terminateTimeoutInSeconds": 5
  }
}'
```

A hook left at its default `DISABLED` is not called even if the application implements the path.

### Hook contract

- Return **HTTP 200** when the hook has completed successfully. For `/ready` and `/validate`, return **503** if the application needs more time — the platform will keep retrying until the configured timeout elapses. Returning 503 quickly is preferred over blocking the request until ready: a blocked call holds the connection open and can consume the entire timeout window in one attempt instead of letting the platform poll.
  - During image build, a `/ready` failure (non-200/503 or timeout) fails the build.
  - At runtime, a hook failure may cause `RunMicrovm` to fail or transition the MicroVM through `TERMINATING` with `stateReason` set.
- The `runHookPayload` you pass to `RunMicrovm` is delivered as the request body of `/run`.

### Sequence: run + ingress + idle + resume + terminate

```
                    Lambda                       Your app
                       │                             │
RunMicrovm ───────────▶│                             │
                       │   resume snapshot           │
                       │   POST /run (runHookPayload)│
                       │────────────────────────────▶│ 200
                       │                             │
                client ──── HTTPS ingress ──────────▶│ (request handled)
                       │ ... no traffic for          │
                       │   maxIdleDurationSeconds ...  │
                       │   POST /suspend             │
                       │────────────────────────────▶│ 200
                       │   suspend (snapshot RAM+disk)
                       │                             │
                client ──── HTTPS ingress ──────────▶│ (auto-resume if enabled)
                       │   resume                    │
                       │   POST /resume              │
                       │────────────────────────────▶│ 200
                       │   ... eventually ...        │
TerminateMicrovm ─────▶│   POST /terminate           │
                       │────────────────────────────▶│ 200
                       │   stop                      │
```

## Idle policy fields

The `idlePolicy` block itself is **optional** on `RunMicrovm` — omit it to disable idle-based auto-suspend entirely. **If you supply the block, all three fields below are required:**

| Field | Range | Notes |
|---|---|---|
| `maxIdleDurationSeconds` | ≥60 | Required if `idlePolicy` is supplied. Idle threshold from last proxy traffic. |
| `suspendedDurationSeconds` | ≥0 | Required if `idlePolicy` is supplied. Time-to-terminate while suspended. `0` means "terminate immediately on suspend." |
| `autoResumeEnabled` | bool | Required if `idlePolicy` is supplied. If true, proxy resumes the VM transparently when traffic arrives at its endpoint. |

`maximumDurationInSeconds` is **not** an `idlePolicy` field — it is a separate top-level `RunMicrovm` flag that sets a hard wall-clock lifetime regardless of activity.

## Hook implementation tips

- **Bind to `0.0.0.0`** on the configured `port`. Lambda calls hooks over the guest's network namespace; localhost-only listeners are unreachable.
- **Run hooks in a separate thread / event loop** from your application server. `/suspend` should still answer 200 even if your main worker pool is busy.
- **Keep `/run` and `/resume` fast.** These hooks are notification mechanisms. If your application needs to run long-running workflows (> 60s) in response, do so asynchronously.
- **Don't use `/run` for long-running init.** That work belongs at image build time so it's captured in the snapshot. Avoid generating random data at build time — if unique random state is needed, invalidate and re-generate using a CSPRNG on `/run`.
- **Make hooks idempotent.** Lambda may retry `/suspend` or `/terminate` under failure conditions.

## Where to go next

- Per-VM uniqueness (entropy, secrets, env vars vs. `runHookPayload`): [`snapshots-and-uniqueness.md`](snapshots-and-uniqueness.md)
- Hook-related failure modes: [`troubleshooting.md`](troubleshooting.md)
