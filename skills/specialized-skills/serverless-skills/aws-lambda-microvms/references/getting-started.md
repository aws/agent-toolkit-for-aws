# Getting started

End-to-end: prerequisites → package → create image → run MicroVM → authenticate → call.

## Prerequisites

0. **Check regional availability.** Confirm Lambda MicroVMs is available in your target region — check the Lambda MicroVMs documentation for supported regions. The S3 artifact bucket and any network connectors must be in the same region as the image.
1. **S3 bucket** in the region you'll create the image in. Cross-region access is rejected (`S3_CROSS_REGION_ACCESS_DENIED`).
2. **Build IAM role** that Lambda assumes during image build. Trust policy:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Principal": { "Service": "lambda.amazonaws.com" },
       "Action": "sts:AssumeRole",
       "Condition": {
         "StringEquals": {
           "aws:SourceAccount": "<account-id>"
         }
       }
     }]
   }
   ```

   Permissions on the role:
   - `s3:GetObject` on the artifact key, `s3:PutObject` for build outputs (if you write any).
   - `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`.
   - `ecr:GetAuthorizationToken` if your `Dockerfile` `FROM` references private ECR.
3. **(Optional) Execution role** for runtime — Lambda uses this to ship logs and to expose AWS credentials inside the MicroVM via IMDSv2. Same trust policy as the build role. Without an execution role, application stdout is *not* shipped to CloudWatch.

See [`iam-and-security.md`](iam-and-security.md) for the full breakdown.

## Step 1 — Package the application

A code artifact is a zip containing a `Dockerfile` at the **root** plus any files it references.

```
my-app.zip
├── Dockerfile
├── app.py
└── requirements.txt
```

**Minimal Python example** (Flask app on port 8080, lifecycle hooks on port 9000):

```python
# app.py
from flask import Flask
import threading

# Application port (default routed by proxy from external 80/443)
app = Flask(__name__)
@app.get("/") 
def root(): return {"hello": "world"}

# Lifecycle hooks port
hooks = Flask("hooks")
P = "/aws/lambda-microvms/runtime/v1"
@hooks.post(f"{P}/ready")     
def ready(): return "", 200
@hooks.post(f"{P}/run")        
def run(): return "", 200
@hooks.post(f"{P}/resume")    
def resume(): return "", 200
@hooks.post(f"{P}/suspend")   
def suspend(): return "", 200
@hooks.post(f"{P}/terminate") 
def terminate(): return "", 200

if __name__ == "__main__":
    threading.Thread(target=lambda: hooks.run(host="0.0.0.0", port=9000), daemon=True).start()
    app.run(host="0.0.0.0", port=8080)
```

```dockerfile
# Dockerfile
FROM public.ecr.aws/lambda/microvms:al2023-minimal
RUN dnf install -y python3 python3-pip && dnf clean all
RUN pip install --no-cache-dir flask==3.0.3
COPY app.py .
EXPOSE 8080 9000
CMD ["python", "app.py"]
```

Upload:

```bash
zip my-app.zip Dockerfile app.py
aws s3 cp my-app.zip s3://${BUCKET}/microvm-images/my-first-image/code-artifact.zip
```

## Step 2 — List managed base images

A custom image must be built *on top of* a Lambda-managed base image (Amazon Linux 2023 + service components).

```bash
aws lambda-microvms list-managed-microvm-images
```

Pick an `imageArn` from the output (e.g. `arn:aws:lambda:<region>:aws:microvm-image:al2023-1`).

## Step 3 — Create the MicroVM image

```bash
aws lambda-microvms create-microvm-image \
  --name my-first-image \
  --description "Hello world Flask app" \
  --base-image-arn arn:aws:lambda:<region>:aws:microvm-image:al2023-1 \
  --build-role-arn arn:aws:iam::123456789012:role/MicroVMBuildRole \
  --code-artifact '{"uri":"s3://my-bucket/microvm-images/my-first-image/code-artifact.zip"}' \
  --hooks '{
    "port": 9000,
    "microvmImageHooks": {
      "ready": "ENABLED",
      "readyTimeoutInSeconds": 60
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

Response includes the `imageArn` and a starting `state` of `CREATING`.

Build proceeds: Lambda fetches the zip, compiles the Dockerfile into an OCI image, starts your app via `CMD`/`ENTRYPOINT`, calls `/ready`, captures the snapshot, then optionally calls `/validate` on a test run.

## Step 4 — Wait for the build to succeed

Pass the `imageArn` returned by `create-microvm-image` to `--image-identifier`. Image versions are `major.minor`; use the full string (e.g. `1.0`).

```bash
aws lambda-microvms get-microvm-image \
  --image-identifier arn:aws:lambda:<region>:123456789012:microvm-image:my-first-image \
  --query 'state'
```

Image state: `CREATING` → `CREATED`. Version state: `PENDING` → `IN_PROGRESS` → `SUCCESSFUL` (or `FAILED`). Inspect per-architecture builds:

```bash
aws lambda-microvms list-microvm-image-builds \
  --image-identifier arn:aws:lambda:<region>:123456789012:microvm-image:my-first-image \
  --image-version 1.0
```

If a build fails, `stateReason` carries an error code from [`troubleshooting.md`](troubleshooting.md).

## Step 5 — Run a MicroVM

`run-microvm` requires the **full `major.minor` version string** (`1.0`); Pass the image ARN as `--image-identifier`.

```bash
aws lambda-microvms run-microvm \
  --image-identifier arn:aws:lambda:<region>:123456789012:microvm-image:my-first-image \
  --image-version 1.0 \
  --execution-role-arn arn:aws:iam::123456789012:role/MicroVMExecutionRole \
  --idle-policy '{
    "maxIdleDurationSeconds": 900,
    "suspendedDurationSeconds": 300,
    "autoResumeEnabled": true
  }' \
  --maximum-duration-in-seconds 28800 \
  --logging '{"cloudWatch":{"logGroup":"/aws/lambda-microvms/my-first-image"}}'
```

Response:

```json
{
  "microvmId": "microvm-...",
  "state": "PENDING",
  "endpoint": "<microvm-id>.lambda-microvm.<region>.on.aws",
  "imageArn": "arn:aws:lambda:<region>:<account>:microvm-image:my-first-image",
  "imageVersion": "1.0",
  "maximumDurationInSeconds": 28800,
  "startedAt": "2026-01-01T00:00:00Z"
}
```

The MicroVM is ready when you can successfully ingress into it. Note that `get-microvm` state is eventually consistent and may lag behind reality — determine readiness by attempting to connect rather than polling the API.

Typically ready within 1–10 s depending on snapshot size.

## Step 6 — Authenticate and call

Generate an auth token (max 60 min):

```bash
TOKEN=$(aws lambda-microvms create-microvm-auth-token \
  --microvm-identifier microvm-... \
  --expiration-in-minutes 30 \
  --allowed-ports '[{"port":8080}]' \
  --query 'authToken."X-aws-proxy-auth"' --output text)

curl "https://<microvm-endpoint>/" \
  -H "X-aws-proxy-auth: $TOKEN" \
  -H "X-aws-proxy-port: 8080"
```

Default proxy target is **port 8080** inside the MicroVM. Override per-request with `X-aws-proxy-port`. For browsers / WebSockets see [`networking.md`](networking.md).

## Step 7 — Suspend / resume / terminate

```bash
# Manual lifecycle control
aws lambda-microvms suspend-microvm  --microvm-identifier microvm-...
aws lambda-microvms resume-microvm   --microvm-identifier microvm-...
aws lambda-microvms terminate-microvm --microvm-identifier microvm-...
```

If `autoResumeEnabled: true`, the proxy resumes a suspended MicroVM transparently when ingress traffic arrives.

## Step 8 — Iterate (versions)

To ship new code, **create a new version** of the image. Use:

```bash
aws lambda-microvms update-microvm-image \
  --image-identifier arn:aws:lambda:<region>:123456789012:microvm-image:my-first-image \
  --base-image-arn arn:aws:lambda:<region>:aws:microvm-image:al2023-1 \
  --build-role-arn arn:aws:iam::<acct>:role/MicroVMBuildRole \
  --code-artifact '{"uri":"s3://.../v2.zip"}'
```

Then `update-microvm-image-version --status ACTIVE|INACTIVE` to control which versions are usable, and `delete-microvm-image-version` to clean up.

Note: image **versions incur storage cost** even when no MicroVMs are running on them — clean up old ones. `delete-microvm-image-version` cannot remove the **last remaining version** — use `delete-microvm-image` to remove the whole image instead.

## Common pitfalls (quick list)

- Forgetting to `EXPOSE <your application port>` in the Dockerfile — all apps run in a container, so the port your hooks and server bind to must be exposed.
- Forgetting to bind hooks to `0.0.0.0` — Lambda calls hooks over the network namespace, so localhost-only listeners are unreachable.
- Generating per-instance state in the Dockerfile — that state is **shared** across all MicroVMs from the snapshot. See [`snapshots-and-uniqueness.md`](snapshots-and-uniqueness.md).
- We recommend using `public.ecr.aws/lambda/microvms:al2023-minimal` as the base registry. See [`snapshots-and-uniqueness.md`](snapshots-and-uniqueness.md).
- Cross-region S3 artifact — must match the image's region.
