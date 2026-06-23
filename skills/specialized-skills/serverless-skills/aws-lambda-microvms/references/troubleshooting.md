# Troubleshooting

Failure modes by phase: image build, run, connect/auth, runtime/hooks, networking, lifecycle, shell.

## Image build failures (`state: FAILED`)

Inspect the per-build error:

```bash
aws lambda-microvms list-microvm-image-builds \
  --image-identifier my-image \
  --image-version 1 \
  --query 'items[].[architecture,buildState,stateReason]' --output table
```

| `stateReason` | Cause | Fix |
|---|---|---|
| `S3_ACCESS_DENIED` | Build role can't read the artifact. | Add `s3:GetObject` for the artifact key to the build role. |
| `S3_NO_SUCH_KEY` | Wrong path. | Verify `--code-artifact uri=s3://bucket/key` matches what's in S3. |
| `S3_NO_SUCH_BUCKET` | Bucket doesn't exist. | Create the bucket; check spelling. |
| `S3_INVALID_OBJECT` | Glacier or other non-instant storage class. | Move to Standard. |
| `S3_CROSS_REGION_ACCESS_DENIED` | Artifact in different region than the image. | Re-upload to a bucket in the image's region. |
| `ARCHIVE_DOCKERFILE_NOT_FOUND` | No `Dockerfile` at zip root. | Ensure `Dockerfile` is at the **top level** of the zip — `unzip -l my-app.zip` should show `Dockerfile` first, not `my-app/Dockerfile`. |
| `ARCHIVE_INVALID` | Corrupt or non-zip archive. | Re-create with `zip -r`; verify with `unzip -t`. |
| `CONTAINER_BUILD_FAILED` | Dockerfile error. | Reproduce locally with `docker build` against the same base image. Check the build logs in `/aws/lambda-microvms/<image-name>` in CloudWatch. |
| `DISK_STORAGE_FULL` | Build exceeded disk. | Trim layers (multi-stage builds, `--no-install-recommends`, clean caches). |
| `INTERNAL_PLATFORM_ERROR` | Service-side. | Retry. If persistent, contact support. |

### `/ready` hook caused build failure

The `/ready` and `/validate` hooks are asynchronous — return 503 until the application is ready/validated, and the platform will retry. If the application blocks instead of returning 503, the platform may time out before the configured timeout. If `/ready` never returns 200 (or times out), the build fails. Look at the application's CloudWatch logs (`/aws/lambda-microvms/<image-name>`) for stack traces from your hook server.

### `/validate` hook caused build failure

The validation phase launches a test MicroVM from the snapshot and calls `/validate`. This is an application-level check — use it to verify your app behaves correctly after resume (e.g., that connections are re-established, state is valid).

## Run failures (`RunMicrovm`)

| Error | Likely cause | Fix |
|---|---|---|
| `ResourceNotFoundException` | Image, version, or execution role doesn't exist. | Verify ARNs. For custom images use `imageVersion`; for managed images you can omit it. |
| `ServiceQuotaExceededException` | Hit account-wide MicroVM concurrency or memory cap. | Wait for terminations, request a quota increase. |
| `ValidationException` | Bad input (idle policy missing required fields, malformed connector ARN, etc.). | Check the `message` field — it's specific. |
| `AccessDenied` | Caller can't `lambda:RunMicrovm`, or `iam:PassRole` for the execution role, or `lambda:PassNetworkConnector` (required on every `RunMicrovm`, even with the default connectors). | Add the missing IAM permission to the caller. |
| `ConflictException` | `clientToken` reused with different parameters. | Use a fresh `clientToken` or replay the exact same request. |

## Connect / auth failures

### `401`/`403` from the proxy

- Token expired (max 60 min). Mint a new one with `create-microvm-auth-token`.
- Token was issued to a different MicroVM ID.
- Token has `allowedPorts` and you're requesting a port outside the allowed ranges.

### `502` from the proxy

A 502 can be returned during the first few seconds after the MicroVM is run while the snapshot is being restored.

- App not listening on the routed port (default 8080; use `X-aws-proxy-port` to redirect).
- TLS mismatch — the app is speaking TLS without ALPN advertising HTTP/1.1, or speaking plaintext on a port the proxy thinks is TLS.
- App crashed after run. Check CloudWatch logs.

### `429` from the proxy

Per-MicroVM or account-level rate limit. Back off and retry. Check the docs for the run-rate quota.

### `5xx` while a run was in flight

If the proxy receives traffic before `RunMicrovm` finishes, it may 5xx. Retry connections with backoff rather than polling `get-microvm` state (which is eventually consistent), or rely on `autoResumeEnabled` semantics if you're hitting a recently-suspended MicroVM.

## Auto-resume not working

- Confirm `idlePolicy.autoResumeEnabled: true` was set at run time.
- Confirm the MicroVM's `state` is `SUSPENDED` (not `TERMINATED` — auto-resume doesn't revive terminated VMs).
- The proxy invokes resume then retries connecting a few times with a delay between attempts. If your `/resume` hook is slow or the app doesn't respond in time, the proxy may return an error to the caller.

## Hook timeouts at runtime

| Hook | Symptom | Fix |
|---|---|---|
| `/run` | `RunMicrovm` returns success but VM goes to `TERMINATED` shortly after with `stateReason` mentioning hook failure. | Raise `runTimeoutInSeconds`; move long-running init out of `/run` (it should be quick). |
| `/resume` | First request after resume hangs / 502s. | Raise `resumeTimeoutInSeconds`. Check resume hook for slow operations (DB reconnects, etc.). |
| `/suspend` | VM doesn't actually suspend on idle. | Hook is hanging or returning non-200. Hook should return 200 when the app is ready to suspend. |
| `/terminate` | Logs/state lost on shutdown. | Add a flush in `/terminate` and raise the timeout. |

Hook server **must bind to `0.0.0.0`** on the configured `port` (commonly 9000). `127.0.0.1`-only listeners are unreachable from Lambda's hook caller.

## Network connector troubleshooting

| Issue | Cause | Fix |
|---|---|---|
| Connector stuck in `PENDING` >10 min | ENI provisioning failure (subnet full, missing IAM perms). | Check `StateReason` on `get-network-connector`. Verify the operator role has `ec2:CreateNetworkInterface` and `ec2:CreateTags`. |
| `InvalidGroup.NotFound` | Subnet and SG in different VPCs / regions. | Both must share VPC and Region with the connector. |
| `Unable to assume role` | Operator role trust policy doesn't allow `lambda.amazonaws.com`. | Fix trust policy, retry. |
| `Invalid security token` | Caller's AWS creds are stale. | Refresh credentials. |

## Snapshot / uniqueness symptoms

- All MicroVMs serve the same instance ID / UUID. → Generation happened at build time. Move to `/run` or first-request init. See [`snapshots-and-uniqueness.md`](snapshots-and-uniqueness.md).
- TLS handshakes intermittently fail across multiple VMs. → Predictable PRNG seeded once at build. Switch to a CSPRNG.
- "AWS SDK calls fail with credentials errors after a few hours." → SDK client picked up creds at boot and didn't refresh. Most modern SDKs refresh; verify version.

## Image storage costs growing

Old image versions persist (and bill) even when unused.

```bash
aws lambda-microvms list-microvm-image-versions \
  --image-identifier my-image

aws lambda-microvms delete-microvm-image-version \
  --image-identifier my-image \
  --image-version <old-version>
```

Or mark old versions `INACTIVE` first if you want to keep them around for rollback. INACTIVE versions are still billed.

## Where logs live

| Log | Location |
|---|---|
| Image build logs | `/aws/lambda-microvms/<image-name>` (build role must have `logs:*` on this group) |
| Application stdout / stderr | Same group at runtime, when `executionRoleArn` has `logs:*` |
| Custom CloudWatch logging | Pass `--logging '{"cloudWatch":{"logGroup":"...","logStream":"..."}}'` to `RunMicrovm` |
| CloudTrail | Standard `lambda:*` events in your trail |

> Avoid logging secrets, tokens, or PII to stdout/stderr — application output is forwarded to CloudWatch.

Custom CloudWatch metrics are **not** auto-emitted — publish from inside your application (or run the CloudWatch Agent inside the container). Set up CloudWatch Alarms on key metrics to catch operational issues early. Consider enabling CloudTrail data events for Lambda MicroVM API calls in production environments.

## When all else fails

1. Run with the `SHELL_INGRESS` network connector attached, get a shell auth token, connect via the console "Connect" button.
2. The shell drops into the same container as the running app — same network namespace, same filesystem. You can inspect files, processes, and network state directly.
