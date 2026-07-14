# Snapshots and uniqueness

The single most important MicroVM-specific concept: every MicroVM launched from an image starts from **the same snapshot**. State generated during image build is replicated across all instances.

## What gets snapshotted

During image build, after your `Dockerfile` runs and your `CMD`/`ENTRYPOINT` starts the application, Lambda waits for `/ready` (if enabled), then captures the full OS snapshot:

1. **Disk snapshot** — the rootfs after layer extraction + any files written during init.
2. **Memory snapshot** — RAM image including kernel state, OS state, and every running process started by the entrypoint (including background daemons).

When you `RunMicrovm`, Lambda restores both, and your processes are already running. No `python app.py` re-execution. No connection-pool warmup. No JIT cold-start.

This is what makes fast runs possible — but it also means **anything in memory or on disk at snapshot time is shared**. Snapshots are not updated by the service. It's the customer's responsibility to update them.

## The uniqueness problem

If your build-phase code does any of these, it ends up in the snapshot and is identical across every MicroVM:

- Generates UUIDs / instance IDs.
- Seeds a PRNG with the current time.
- Fetches a secret or token.
- Reads `/dev/urandom` once and caches the bytes.
- Establishes a TCP connection (the connection itself won't survive snapshot, but state derived from it will).

### Fixes, in order of preference

1. **Don't generate it at build time.** Generate at first use, after run.
2. **Generate it in `/run`.** This hook fires once after run (post-snapshot resume) and is the canonical place to create per-VM unique state. Set `microvmHooks.run: "ENABLED"` in `--hooks`.
3. **Read fresh entropy from a CSPRNG.** These are wired to the kernel RNG which Firecracker re-seeds across snapshot resume — see the language table below.
4. **Inject per-VM data via `runHookPayload`.** The opaque blob you pass to `RunMicrovm` is delivered as the request body of `/run`, so you can include tenant IDs, signed URLs, parameter-store paths, etc.

## CSPRNGs that are safe across snapshot resume

| Language | Use | Don't use |
|---|---|---|
| Java | `java.security.SecureRandom` | `java.util.Random`, `Math.random()` seeded once |
| Python | `secrets`, `random.SystemRandom` | `random.random()` with default seed |
| .NET | `System.Security.Cryptography.RandomNumberGenerator` | `System.Random` instance reused across snapshot |
| Node.js | `crypto.randomBytes`, `crypto.randomUUID` | `Math.random()` |
| Go | `crypto/rand` | `math/rand` |
| Rust | `rand::rngs::OsRng` | `rand::thread_rng()` if seeded once before snapshot |
| C/C++ | `getrandom(2)`, `/dev/urandom` per-call | `rand()`, `srand(time(NULL))` once |

The Lambda base ECR image (`public.ecr.aws/lambda/microvms:al2023-minimal`) ships an OpenSSL build that automatically re-seeds entropy on snapshot resume. If you bring your own base image, your OpenSSL version will **not** do this by default — use the Lambda base image or ensure your application reads fresh entropy per-call. Reading `/dev/urandom` per-call is safe — the kernel RNG reseeds on resume.

## Connections and snapshot resume

TCP connections opened in the entrypoint (e.g. an SDK client warming up) are captured in memory but not in any meaningful network sense — the underlying socket isn't valid after resume. **All outbound (non-local) connections are killed on run and resume.** Most AWS SDKs handle this transparently (they retry on `EBADF`/`ECONNRESET`). For other clients, ensure your connection libraries have timeouts and retries configured to re-establish connections automatically.

## Configuration data: env vars vs. run payload vs. execution-role secrets

You have three places to inject configuration:

| Where | Set at | Same for all VMs? | Visible to | Use for |
|---|---|---|---|---|
| **Build env vars** (`--environment-variables`) | Image creation | Yes — burnt into the snapshot | Container env at build time and after resume | Static, non-sensitive: log level, app port, feature toggles |
| **`runHookPayload`** | `RunMicrovm` | No — per-VM | Body of the `/run` POST | Per-VM: tenant ID, session ID, signed URLs, references to secrets |
| **Execution role + AWS SDK** | At run | No — assumed credentials | IMDSv2 in the guest | Real secrets — fetch from Secrets Manager / SSM Parameter Store at runtime |

## Inspecting snapshot sizes

Each successful build records snapshot sizes. Use these to track image bloat over time:

```bash
BUILD_ID=$(aws lambda-microvms list-microvm-image-builds \
  --image-identifier arn:aws:lambda:<region>:<account>:microvm-image:my-image \
  --image-version 1.0 \
  --query 'items[0].buildId' --output text)

aws lambda-microvms get-microvm-image-build \
  --image-identifier arn:aws:lambda:<region>:<account>:microvm-image:my-image \
  --image-version 1.0 \
  --build-id "$BUILD_ID"
```

Fields of interest (nested under `snapshotBuild`):

- `snapshotBuild.memorySnapshotSizeInBytes` — RAM image. Dominated by your application's RSS plus kernel pages dirtied during boot. Big numbers usually mean the app over-eagerly preallocates buffers / loads big models in memory.
- `snapshotBuild.codeInstallSizeInBytes` — size of the code artifact after it's compiled from the Dockerfile and installed in the filesystem. Dominated by the container image.
- `snapshotBuild.diskSnapshotSizeInBytes` — bytes written by the OS or application during boot (does not include codeInstallSizeInBytes).

Heuristics:

- **Resume time scales with snapshot size accessed**, roughly 1 s per 500 MB. Trim aggressively.
- A bloated `diskSnapshot` → audit the Dockerfile (multi-stage builds, `--no-install-recommends`, `dnf clean all`, remove `pip` caches).
- A bloated `memorySnapshot` → check for over-eager warmup (loading every model variant at boot, opening millions of fds, etc.).

## Disk-vs-memory restore behavior

Memory is **eagerly restored** on run/resume, while block device (disk) content is **demand-paged**. This means a larger memory snapshot directly increases the time it takes for a snapshot to fully restore. Keep memory snapshots as small as possible for fast runs — avoid over-eager preallocation of buffers or loading large models entirely into RAM at build time.

## If your app needs unique state at startup

Common patterns:

- **Listen for `/run` and receive the `microvmId` via `runHookPayload`.** `microvmId` is automatically injected in the request. Block your app's request handlers until `/run` returns.
- **Pass it in `runHookPayload`**: the caller (your control plane) generates per-VM state and ships it in the `RunMicrovm` call.
